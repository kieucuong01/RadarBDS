"""Normalize frozen WGS84 source snapshots into deterministic map layers."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
from pathlib import Path
import re
from typing import Any
import unicodedata

from shapely import make_valid
from shapely.geometry import (
    GeometryCollection,
    LineString,
    MultiLineString,
    MultiPolygon,
    Point,
    Polygon,
    shape,
)
from shapely.geometry.base import BaseGeometry
from shapely.ops import polygonize, unary_union

from .models import MapPoint, MapProductSpec, load_neighborhood_points


@dataclass(frozen=True)
class NamedGeometry:
    name: str
    geometry: BaseGeometry
    source_id: str = ""
    properties: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class StreetGeometry:
    name: str
    geometry: BaseGeometry
    road_class: str
    source_id: str = ""


@dataclass(frozen=True)
class NormalizedMapLayers:
    legacy_boundaries: tuple[NamedGeometry, ...]
    current_boundaries: tuple[NamedGeometry, ...]
    legacy_ward_centers: tuple[MapPoint, ...]
    streets: tuple[StreetGeometry, ...]
    hydro: tuple[NamedGeometry, ...]
    poi: tuple[MapPoint, ...]
    neighborhoods: tuple[MapPoint, ...]
    source_manifest: dict[str, dict]


def _read_payload(value: Path | str | bytes | dict) -> dict:
    if isinstance(value, dict):
        payload = value
    elif isinstance(value, bytes):
        try:
            payload = json.loads(value.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"Invalid source JSON: {exc}") from exc
    else:
        try:
            payload = json.loads(Path(value).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Unable to read source JSON from {value}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("Source JSON root must be an object")
    return payload


def _normalized_name(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    without_marks = "".join(
        character
        for character in decomposed
        if not unicodedata.combining(character)
    )
    normalized = re.sub(r"\s+", " ", without_marks).strip().casefold()
    return re.sub(r"^(phuong|xa|thi tran)\s+", "", normalized)


def _polygonal_only(geometry: BaseGeometry, context: str) -> Polygon | MultiPolygon:
    if geometry.is_empty:
        raise ValueError(f"{context} geometry is empty")
    repaired = make_valid(geometry) if not geometry.is_valid else geometry
    if isinstance(repaired, (Polygon, MultiPolygon)):
        polygonal = repaired
    elif isinstance(repaired, GeometryCollection):
        polygons = [
            part
            for part in repaired.geoms
            if isinstance(part, (Polygon, MultiPolygon)) and not part.is_empty
        ]
        polygonal = unary_union(polygons) if polygons else GeometryCollection()
    else:
        polygonal = GeometryCollection()
    if polygonal.is_empty or polygonal.geom_type not in {"Polygon", "MultiPolygon"}:
        raise ValueError(f"{context} must resolve to Polygon or MultiPolygon")
    if not polygonal.is_valid:
        raise ValueError(f"{context} could not be safely repaired")
    return polygonal


def _member_lines(element: dict, role: str) -> list[LineString]:
    lines = []
    for member in element.get("members", []):
        if member.get("type") != "way" or member.get("role", "") != role:
            continue
        coordinates = [
            (point["lon"], point["lat"])
            for point in member.get("geometry", [])
            if isinstance(point, dict) and "lon" in point and "lat" in point
        ]
        if len(coordinates) >= 2:
            lines.append(LineString(coordinates))
    return lines


def _polygons_from_lines(lines: list[LineString]) -> BaseGeometry:
    if not lines:
        return GeometryCollection()
    polygons = list(polygonize(unary_union(lines)))
    if polygons:
        return unary_union(polygons)
    closed = [
        Polygon(list(line.coords))
        for line in lines
        if line.is_ring and len(line.coords) >= 4
    ]
    return unary_union(closed) if closed else GeometryCollection()


def _relation_polygon(element: dict, context: str) -> Polygon | MultiPolygon:
    outer = _polygons_from_lines(_member_lines(element, "outer"))
    if outer.is_empty:
        raise ValueError(f"{context} has no closed outer boundary")
    inner = _polygons_from_lines(_member_lines(element, "inner"))
    geometry = outer.difference(inner) if not inner.is_empty else outer
    return _polygonal_only(geometry, context)


def _feature_name(properties: dict) -> str:
    for key in ("name:vi", "name"):
        value = properties.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _boundary_candidates(
    payload: dict,
    source_key: str,
    expected_names: set[str],
) -> list[NamedGeometry]:
    candidates: list[NamedGeometry] = []
    if payload.get("type") == "FeatureCollection":
        features = payload.get("features")
        if not isinstance(features, list):
            raise ValueError(f"{source_key} features must be an array")
        for index, feature in enumerate(features):
            if not isinstance(feature, dict) or feature.get("type") != "Feature":
                continue
            properties = feature.get("properties") or {}
            name = _feature_name(properties)
            geometry_value = feature.get("geometry")
            if (
                not name
                or _normalized_name(name) not in expected_names
                or not isinstance(geometry_value, dict)
            ):
                continue
            try:
                geometry = shape(geometry_value)
            except Exception as exc:
                raise ValueError(
                    f"{source_key} feature {index} has invalid geometry: {exc}"
                ) from exc
            candidates.append(
                NamedGeometry(
                    name=name,
                    geometry=_polygonal_only(
                        geometry, f"{source_key} feature {name}"
                    ),
                    source_id=str(feature.get("id", index)),
                    properties={
                        str(key): str(value)
                        for key, value in properties.items()
                        if value is not None
                    },
                )
            )
        return candidates

    elements = payload.get("elements")
    if not isinstance(elements, list):
        raise ValueError(
            f"{source_key} must be GeoJSON or an Overpass elements response"
        )
    for element in elements:
        if not isinstance(element, dict) or element.get("type") != "relation":
            continue
        tags = element.get("tags") or {}
        name = _feature_name(tags)
        if not name or _normalized_name(name) not in expected_names:
            continue
        candidates.append(
            NamedGeometry(
                name=name,
                geometry=_relation_polygon(
                    element, f"{source_key} relation {element.get('id')}"
                ),
                source_id=f"relation/{element.get('id')}",
                properties={
                    str(key): str(value)
                    for key, value in tags.items()
                    if value is not None
                },
            )
        )
    return candidates


def _select_exact_boundaries(
    payload: dict,
    expected_names: tuple[str, ...],
    source_key: str,
) -> tuple[NamedGeometry, ...]:
    expected = {_normalized_name(name): name for name in expected_names}
    matched: dict[str, list[NamedGeometry]] = {
        normalized: [] for normalized in expected
    }
    for candidate in _boundary_candidates(payload, source_key, set(expected)):
        normalized = _normalized_name(candidate.name)
        if normalized in matched:
            matched[normalized].append(candidate)

    missing = [
        expected[normalized]
        for normalized, features in matched.items()
        if not features
    ]
    duplicates = [
        expected[normalized]
        for normalized, features in matched.items()
        if len(features) > 1
    ]
    if missing or duplicates:
        details = []
        if missing:
            details.append(f"missing={missing}")
        if duplicates:
            details.append(f"duplicates={duplicates}")
        raise ValueError(
            f"{source_key} must resolve to exactly {len(expected_names)} named "
            f"Polygon/MultiPolygon features ({'; '.join(details)})"
        )

    return tuple(
        NamedGeometry(
            name=name,
            geometry=matched[_normalized_name(name)][0].geometry,
            source_id=matched[_normalized_name(name)][0].source_id,
            properties=matched[_normalized_name(name)][0].properties or {},
        )
        for name in expected_names
    )


def _select_exact_legacy_boundaries(
    payload: dict,
    expected_names: tuple[str, ...],
) -> tuple[NamedGeometry, ...]:
    try:
        boundaries = _select_exact_boundaries(
            payload,
            expected_names,
            "legacy_boundaries",
        )
    except ValueError as exc:
        raise ValueError(
            "legacy_boundaries must resolve to exactly 14 legacy boundary "
            f"Polygon/MultiPolygon features: {exc}"
        ) from exc
    if len(boundaries) != 14:
        raise ValueError("legacy_boundaries must resolve to exactly 14 legacy boundary features")
    allowed_sources = {"source_snapshot", "derived_boundary"}
    derived_names = set()
    for boundary in boundaries:
        properties = boundary.properties or {}
        if properties.get("boundary_claim", "").casefold() != "true":
            raise ValueError(
                f"legacy boundary {boundary.name} must set boundary_claim=true"
            )
        boundary_source = properties.get("boundary_source", "")
        if boundary_source not in allowed_sources:
            raise ValueError(
                f"legacy boundary {boundary.name} has invalid boundary_source"
            )
        if boundary_source == "derived_boundary":
            derived_names.add(boundary.name)
            if not properties.get("derived_from", "").strip():
                raise ValueError(
                    f"legacy boundary {boundary.name} must record derived_from"
                )
    if derived_names != {"Hòa Phú", "Phú Tân"}:
        raise ValueError(
            "legacy_boundaries must mark exactly Hòa Phú and Phú Tân as "
            f"derived_boundary (actual={sorted(derived_names)})"
        )
    return boundaries


def _line_geometry(element: dict) -> LineString | None:
    raw_geometry = element.get("geometry")
    if not isinstance(raw_geometry, list):
        return None
    coordinates = [
        (point["lon"], point["lat"])
        for point in raw_geometry
        if isinstance(point, dict) and "lon" in point and "lat" in point
    ]
    return LineString(coordinates) if len(coordinates) >= 2 else None


def _line_parts(geometry: BaseGeometry) -> tuple[BaseGeometry, ...]:
    if geometry.is_empty:
        return ()
    if isinstance(geometry, (LineString, MultiLineString)):
        return (geometry,)
    if isinstance(geometry, GeometryCollection):
        return tuple(
            part
            for part in geometry.geoms
            if isinstance(part, (LineString, MultiLineString)) and not part.is_empty
        )
    return ()


def _road_class(highway: str) -> str:
    value = highway.casefold()
    if value in {"motorway", "motorway_link", "trunk", "trunk_link"}:
        return "trunk"
    for road_class in ("primary", "secondary", "tertiary"):
        if value in {road_class, f"{road_class}_link"}:
            return road_class
    return "local"


def _element_point(element: dict) -> Point | None:
    if element.get("type") == "node":
        lon, lat = element.get("lon"), element.get("lat")
        if isinstance(lon, (int, float)) and isinstance(lat, (int, float)):
            return Point(float(lon), float(lat))
        return None
    line = _line_geometry(element)
    if line is not None:
        if line.is_ring and len(line.coords) >= 4:
            return Polygon(line.coords).representative_point()
        return line.centroid
    if element.get("type") == "relation":
        try:
            return _relation_polygon(
                element, f"POI relation {element.get('id')}"
            ).representative_point()
        except ValueError:
            return None
    return None


def _distance_meters(left: MapPoint, right: MapPoint) -> float:
    mean_lat = math.radians((left.lat + right.lat) / 2)
    dx = math.radians(right.lon - left.lon) * math.cos(mean_lat)
    dy = math.radians(right.lat - left.lat)
    return 6_371_008.8 * math.hypot(dx, dy)


def _detail_layers(
    payload: dict,
    old_city: BaseGeometry,
) -> tuple[tuple[StreetGeometry, ...], tuple[NamedGeometry, ...], tuple[MapPoint, ...]]:
    elements = payload.get("elements")
    if not isinstance(elements, list):
        raise ValueError("osm_detail must contain an Overpass elements array")

    streets: list[StreetGeometry] = []
    hydro: list[NamedGeometry] = []
    poi: list[MapPoint] = []
    for element in elements:
        if not isinstance(element, dict):
            continue
        tags = element.get("tags") or {}
        source_id = f"{element.get('type', 'element')}/{element.get('id', '')}"
        line = _line_geometry(element)
        if line is not None and isinstance(tags.get("highway"), str):
            clipped = old_city.intersection(line)
            for part in _line_parts(clipped):
                streets.append(
                    StreetGeometry(
                        name=_feature_name(tags),
                        geometry=part,
                        road_class=_road_class(tags["highway"]),
                        source_id=source_id,
                    )
                )
        if line is not None and isinstance(tags.get("waterway"), str):
            clipped = old_city.intersection(line)
            for part in _line_parts(clipped):
                hydro.append(
                    NamedGeometry(
                        name=_feature_name(tags) or tags["waterway"],
                        geometry=part,
                        source_id=source_id,
                    )
                )

        if not (tags.get("amenity") or tags.get("tourism")):
            continue
        name = _feature_name(tags)
        point = _element_point(element)
        if not name or point is None or point.is_empty or not old_city.covers(point):
            continue
        candidate = MapPoint(
            name=name,
            lon=float(point.x),
            lat=float(point.y),
            source=f"OpenStreetMap {source_id}",
            confidence="high",
        )
        duplicate = any(
            _normalized_name(existing.name) == _normalized_name(candidate.name)
            and _distance_meters(existing, candidate) <= 25
            for existing in poi
        )
        if not duplicate:
            poi.append(candidate)

    streets.sort(
        key=lambda feature: (
            feature.road_class,
            _normalized_name(feature.name),
            feature.source_id,
        )
    )
    hydro.sort(
        key=lambda feature: (_normalized_name(feature.name), feature.source_id)
    )
    poi.sort(key=lambda point: (_normalized_name(point.name), point.lon, point.lat))
    return tuple(streets), tuple(hydro), tuple(poi)


def _source_manifest(snapshots: dict[str, Any]) -> dict[str, dict]:
    directories = {
        Path(value).parent
        for value in snapshots.values()
        if isinstance(value, (str, Path))
    }
    for directory in sorted(directories, key=str):
        manifest_path = directory / "source-snapshots.json"
        if manifest_path.exists():
            value = _read_payload(manifest_path)
            return {
                str(key): record
                for key, record in value.items()
                if isinstance(record, dict)
            }
    return {}


def _load_exact_legacy_centers(
    snapshot: Path | str | bytes | dict,
    expected_names: tuple[str, ...],
) -> tuple[MapPoint, ...]:
    if not isinstance(snapshot, (Path, str)):
        raise ValueError(
            "legacy_ward_centers must be a frozen GeoJSON snapshot path"
        )
    try:
        points = load_neighborhood_points(Path(snapshot))
    except ValueError as exc:
        raise ValueError(f"Invalid legacy ward center Points: {exc}") from exc
    by_name = {point.name: point for point in points}
    expected = set(expected_names)
    actual = set(by_name)
    if len(points) != 14 or actual != expected:
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        raise ValueError(
            "legacy_ward_centers must resolve to exactly 14 legacy ward "
            f"center Points (missing={missing}; unexpected={unexpected})"
        )
    return tuple(by_name[name] for name in expected_names)


def build_normalized_layers(
    spec: MapProductSpec,
    snapshots: dict[str, Path | str | bytes | dict],
    neighborhood_points: tuple[MapPoint, ...],
) -> NormalizedMapLayers:
    """Validate current polygons and legacy reference points in WGS84."""

    required = {
        "legacy_boundaries",
        "legacy_ward_centers",
        "current_boundaries",
        "osm_detail",
    }
    missing_sources = sorted(required - set(snapshots))
    if missing_sources:
        raise ValueError(f"Missing required source snapshots: {missing_sources}")
    for point in neighborhood_points:
        if point.geometry_type != "Point":
            raise ValueError(
                f"Neighborhood {point.name!r} must use Point geometry"
            )
        if not (
            math.isfinite(point.lon)
            and math.isfinite(point.lat)
            and -180 <= point.lon <= 180
            and -90 <= point.lat <= 90
        ):
            raise ValueError(
                f"Neighborhood {point.name!r} has invalid WGS84 coordinates"
            )

    legacy_centers = _load_exact_legacy_centers(
        snapshots["legacy_ward_centers"],
        spec.legacy_wards,
    )
    legacy_boundaries = _select_exact_legacy_boundaries(
        _read_payload(snapshots["legacy_boundaries"]),
        spec.legacy_wards,
    )
    current = _select_exact_boundaries(
        _read_payload(snapshots["current_boundaries"]),
        spec.current_wards,
        "current_boundaries",
    )
    current_extent = unary_union([feature.geometry for feature in current])
    if current_extent.is_empty:
        raise ValueError("Current five-ward union is empty")
    streets, hydro, poi = _detail_layers(
        _read_payload(snapshots["osm_detail"]),
        current_extent,
    )
    return NormalizedMapLayers(
        legacy_boundaries=legacy_boundaries,
        current_boundaries=current,
        legacy_ward_centers=legacy_centers,
        streets=streets,
        hydro=hydro,
        poi=poi,
        neighborhoods=tuple(neighborhood_points),
        source_manifest=_source_manifest(snapshots),
    )
