from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Mapping, Sequence

from shapely.geometry import LineString, Point, shape
from shapely.ops import unary_union
from shapely.validation import make_valid

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.listing_map import (
    LISTING_MAP_AUTO_ACCEPT_THRESHOLD,
    LISTING_MAP_AUTO_OVERRIDE_PATH,
    LISTING_MAP_BOUNDS,
    LISTING_MAP_FORCE_AGGREGATE_ROADS,
    LISTING_MAP_OVERRIDE_PATH,
    LISTING_MAP_WARD_BOUNDARY_PATHS,
)
from services.listing_location_auto_registry import (
    BrowserLocationEvidence,
    canonical_evidence_hash,
    legacy_compatibility_reason,
    parse_google_maps_coordinates,
)
from services.listing_location_resolver import (
    normalize_location_token,
    normalize_road_token,
)


OUTPUT_NAMES = (
    "ward-centers.json",
    "road-centers.json",
    "landmark-centers.json",
    "manifest.json",
)
_LANDMARK_NAME_RE = re.compile(
    r"\b(?:tdc|tai dinh cu|kdc|khu dan cu|khu do thi|du an)\b",
    re.IGNORECASE,
)


def _json_bytes(payload: Mapping) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _payload_sha256(payload: object) -> str:
    return hashlib.sha256(_json_bytes(payload)).hexdigest()


def _inside_bounds(lat: float, lng: float) -> bool:
    (south, west), (north, east) = LISTING_MAP_BOUNDS
    return south <= lat <= north and west <= lng <= east


def _element_point(element: Mapping) -> tuple[float, float]:
    if element.get("type") == "node":
        lat, lng = element.get("lat"), element.get("lon")
    else:
        center = element.get("center") or {}
        lat, lng = center.get("lat"), center.get("lon")
        if lat is None or lng is None:
            geometry = element.get("geometry") or []
            if geometry:
                lat = sum(float(point["lat"]) for point in geometry) / len(geometry)
                lng = sum(float(point["lon"]) for point in geometry) / len(geometry)
    try:
        point = float(lat), float(lng)
    except (TypeError, ValueError):
        raise ValueError(
            f"OSM {element.get('type')} {element.get('id')} has no usable point"
        ) from None
    if not _inside_bounds(*point):
        raise ValueError(
            f"OSM {element.get('type')} {element.get('id')} "
            "is outside listing map bounds"
        )
    return point


def _segment_length_m(first: Mapping, second: Mapping) -> float:
    return _distance_m(
        float(first["lat"]),
        float(first["lon"]),
        float(second["lat"]),
        float(second["lon"]),
    )


def _distance_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    d_lat = lat2_rad - lat1_rad
    d_lng = math.radians(lng2 - lng1)
    value = (
        math.sin(d_lat / 2) ** 2
        + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(d_lng / 2) ** 2
    )
    return 6371008.8 * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


def _road_center(elements: list[Mapping]) -> tuple[float, float]:
    weighted_lat = 0.0
    weighted_lng = 0.0
    total_length = 0.0
    fallback_points = []
    for element in elements:
        if not (element.get("tags") or {}).get("highway"):
            raise ValueError(f"OSM way {element.get('id')} is not a highway")
        geometry = element.get("geometry") or []
        if len(geometry) < 2:
            fallback_points.append(_element_point(element))
            continue
        for first, second in zip(geometry, geometry[1:], strict=False):
            lat = (float(first["lat"]) + float(second["lat"])) / 2
            lng = (float(first["lon"]) + float(second["lon"])) / 2
            if not _inside_bounds(lat, lng):
                raise ValueError(
                    f"OSM way {element.get('id')} is outside listing map bounds"
                )
            length = _segment_length_m(first, second)
            weighted_lat += lat * length
            weighted_lng += lng * length
            total_length += length
    if total_length > 0:
        return weighted_lat / total_length, weighted_lng / total_length
    if fallback_points:
        return (
            sum(point[0] for point in fallback_points) / len(fallback_points),
            sum(point[1] for point in fallback_points) / len(fallback_points),
        )
    raise ValueError("road source has no usable highway geometry")


def _element_index(osm_payload: Mapping) -> dict[tuple[str, int], Mapping]:
    index = {}
    for element in osm_payload.get("elements") or []:
        element_type = str(element.get("type") or "")
        try:
            element_id = int(element["id"])
        except (KeyError, TypeError, ValueError):
            continue
        index[(element_type, element_id)] = element
    return index


def _validate_canonical_wards(
    sources: Mapping,
    mapped_keys: set[tuple[str, str]],
) -> None:
    required = {
        (
            str(item.get("city") or "").strip(),
            normalize_location_token(item.get("ward") or ""),
        )
        for item in sources.get("canonical_wards") or []
    }
    missing = sorted(required - mapped_keys)
    if missing:
        labels = ", ".join(f"{city}/{ward}" for city, ward in missing)
        raise ValueError(f"missing canonical ward: {labels}")


def _boundary_city(payload: Mapping, path: Path) -> str:
    explicit = str(payload.get("city") or "").strip()
    if explicit:
        return explicit
    token = normalize_location_token(f"{path.stem} {payload.get('name') or ''}")
    if "thu dau mot" in token:
        return "THỦ DẦU MỘT"
    if "ben cat" in token:
        return "BẾN CÁT"
    if "thuan an" in token:
        return "THUẬN AN"
    if "di an" in token:
        return "DĨ AN"
    raise ValueError(f"boundary city is missing for {path}")


def _load_ward_boundaries(
    paths: Sequence[Path],
) -> tuple[
    dict[tuple[str, str], tuple[str, object, Mapping]],
    list[Mapping],
]:
    boundaries = {}
    payloads = []
    for raw_path in paths:
        path = Path(raw_path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        payloads.append(payload)
        city = _boundary_city(payload, path)
        for feature in payload.get("features") or []:
            properties = feature.get("properties") or {}
            ward = str(properties.get("name") or "").strip()
            geometry_payload = feature.get("geometry")
            if not ward or not geometry_payload:
                raise ValueError(f"invalid ward boundary in {path}")
            geometry = shape(geometry_payload)
            if not geometry.is_valid:
                repaired = make_valid(geometry)
                if repaired.geom_type == "GeometryCollection":
                    repaired = unary_union(
                        [
                            item
                            for item in repaired.geoms
                            if item.geom_type in {"Polygon", "MultiPolygon"}
                        ]
                    )
                geometry = repaired
            if (
                geometry.is_empty
                or not geometry.is_valid
                or geometry.geom_type not in {"Polygon", "MultiPolygon"}
            ):
                raise ValueError(f"invalid ward boundary geometry for {ward}")
            key = city, normalize_location_token(ward)
            if key in boundaries:
                raise ValueError(f"duplicate ward boundary: {city}/{key[1]}")
            boundaries[key] = (ward, geometry, properties)
    return boundaries, payloads


def _way_line(element: Mapping) -> LineString | None:
    geometry = element.get("geometry") or []
    if len(geometry) < 2:
        return None
    try:
        line = LineString(
            (float(point["lon"]), float(point["lat"])) for point in geometry
        )
    except (KeyError, TypeError, ValueError):
        return None
    return line if line.is_valid and not line.is_empty else None


def _representative_line_point(geometry) -> tuple[float, float]:
    if geometry.geom_type in {"MultiLineString", "GeometryCollection"}:
        lines = [
            item
            for item in geometry.geoms
            if item.geom_type in {"LineString", "LinearRing"} and item.length > 0
        ]
        if lines:
            geometry = max(lines, key=lambda item: item.length)
    point = geometry.interpolate(0.5, normalized=True)
    return float(point.y), float(point.x)


def _accuracy_radius_m(geometry, lat: float, lng: float) -> float:
    min_lng, min_lat, max_lng, max_lat = geometry.bounds
    radius = max(
        _distance_m(lat, lng, corner_lat, corner_lng)
        for corner_lat, corner_lng in (
            (min_lat, min_lng),
            (min_lat, max_lng),
            (max_lat, min_lng),
            (max_lat, max_lng),
        )
    )
    return round(max(radius, 75.0), 1)


def _line_parts(geometry) -> list[LineString]:
    if geometry.is_empty:
        return []
    if geometry.geom_type == "LineString":
        return [geometry]
    parts = []
    for child in getattr(geometry, "geoms", ()):
        parts.extend(_line_parts(child))
    return parts


def _connected_road_components(
    parts: Sequence[tuple[int, object]],
) -> list[tuple[object, list[int]]]:
    """Group touching OSM segments without merging disconnected namesakes."""
    pending = [
        (way_id, line)
        for way_id, geometry in parts
        for line in _line_parts(geometry)
        if not line.is_empty and line.length > 0
    ]
    pending.sort(key=lambda item: (item[0], tuple(item[1].bounds)))
    components = []
    while pending:
        way_id, line = pending.pop(0)
        component = [(way_id, line)]
        changed = True
        while changed:
            changed = False
            remaining = []
            component_geometry = unary_union(
                [candidate for _candidate_id, candidate in component]
            )
            for candidate_id, candidate in pending:
                if component_geometry.intersects(candidate):
                    component.append((candidate_id, candidate))
                    changed = True
                else:
                    remaining.append((candidate_id, candidate))
            pending = remaining
        geometry = unary_union(
            [candidate for _candidate_id, candidate in component]
        )
        components.append(
            (
                geometry,
                sorted({candidate_id for candidate_id, _line in component}),
            )
        )
    return sorted(
        components,
        key=lambda item: (
            item[1],
            tuple(round(value, 9) for value in item[0].bounds),
        ),
    )


def _normalize_landmark_token(value: str) -> str:
    token = normalize_location_token(value)
    token = re.sub(r"^tai dinh cu\b", "tdc", token)
    token = re.sub(r"^khu dan cu\b", "kdc", token)
    return " ".join(token.split())


def _validate_aliases(
    rows: Sequence[Mapping],
    *,
    landmark: bool,
) -> dict[tuple[str, str, str], list[str]]:
    aliases_by_scope: dict[tuple[str, str, str], list[str]] = {}
    seen: dict[tuple[str, str, str], str] = {}
    normalizer = _normalize_landmark_token if landmark else normalize_road_token
    for row in rows:
        canonical = normalizer(str(row.get("canonical") or ""))
        if not canonical:
            raise ValueError("alias canonical value is required")
        city = normalize_location_token(row.get("city") or "")
        ward = normalize_location_token(row.get("ward") or "")
        for raw_alias in (row.get("aliases") or []):
            alias = normalizer(str(raw_alias or ""))
            if not alias:
                raise ValueError("empty alias is invalid")
            scope_key = city, ward, alias
            previous = seen.get(scope_key)
            if previous is not None and previous != canonical:
                raise ValueError(f"duplicate alias in one scope: {alias}")
            seen[scope_key] = canonical
            aliases_by_scope.setdefault((city, ward, canonical), []).append(alias)
    return {
        scope_key: sorted(set(values + [scope_key[2]]))
        for scope_key, values in aliases_by_scope.items()
    }


def _aliases_for_scope(
    aliases_by_scope: Mapping[tuple[str, str, str], list[str]],
    *,
    city: str,
    ward: str,
    canonical: str,
) -> list[str]:
    normalized_city = normalize_location_token(city)
    normalized_ward = normalize_location_token(ward)
    aliases = {canonical}
    for scope in (
        ("", "", canonical),
        ("", normalized_ward, canonical),
        (normalized_city, "", canonical),
        (normalized_city, normalized_ward, canonical),
    ):
        aliases.update(aliases_by_scope.get(scope, ()))
    return sorted(aliases)


def _validate_override_point(
    row: Mapping,
    *,
    boundaries: Mapping,
    label: str,
) -> tuple[float, float]:
    required = ("source", "source_url", "verified_at")
    if any(not str(row.get(field) or "").strip() for field in required):
        raise ValueError(f"{label} coordinate override requires provenance")
    source_url = str(row.get("source_url") or "").strip()
    if not source_url.startswith("https://"):
        raise ValueError(f"{label} source URL must use HTTPS")
    try:
        lat = float(row["lat"])
        lng = float(row["lng"])
    except (KeyError, TypeError, ValueError):
        raise ValueError(f"{label} coordinate override is invalid") from None
    if not _inside_bounds(lat, lng):
        raise ValueError(f"{label} coordinate override is outside map bounds")

    scope = (
        str(row.get("city") or "").strip(),
        normalize_location_token(row.get("ward") or ""),
    )
    boundary = boundaries.get(scope)
    if boundary and not boundary[1].covers(Point(lng, lat)):
        allowed = bool(row.get("allow_boundary_mismatch"))
        reason = str(row.get("boundary_mismatch_reason") or "").strip()
        if not allowed or not reason:
            raise ValueError(f"{label} boundary mismatch requires explicit reason")
    return lat, lng


def _build_ward_rows(
    sources: Mapping,
    index: Mapping,
) -> tuple[list[dict], set[tuple[str, str]]]:
    ward_rows = []
    ward_keys: set[tuple[str, str]] = set()
    for source in sources.get("wards") or []:
        city = str(source.get("city") or "").strip()
        ward = str(source.get("ward") or "").strip()
        key = city, normalize_location_token(ward)
        if not city or not key[1]:
            raise ValueError("ward city and name are required")
        if key in ward_keys:
            raise ValueError(f"duplicate normalized ward: {city}/{key[1]}")
        point_source = source.get("point")
        provenance = str(source.get("source") or "").strip()
        source_url = str(source.get("source_url") or "").strip()
        element_key = None
        if point_source is not None:
            try:
                lat = float(point_source["lat"])
                lng = float(point_source["lng"])
            except (KeyError, TypeError, ValueError):
                raise ValueError(f"verified ward point is invalid for {ward}") from None
            if (
                not _inside_bounds(lat, lng)
                or not provenance
                or not source_url.startswith("https://")
            ):
                raise ValueError(f"verified ward point is invalid for {ward}")
        else:
            element_key = (
                str(source.get("osm_type") or ""),
                int(source.get("osm_id") or 0),
            )
            element = index.get(element_key)
            if not element:
                raise ValueError(
                    f"missing OSM {element_key[0]} {element_key[1]} for ward {ward}"
                )
            lat, lng = _element_point(element)
            provenance = "OpenStreetMap"
            source_url = (
                f"https://www.openstreetmap.org/"
                f"{element_key[0]}/{element_key[1]}"
            )
        ward_keys.add(key)
        fallback_parent = str(source.get("fallback_parent") or "").strip()
        default_label = (
            f"Theo trung tâm {fallback_parent} (xấp xỉ cho {ward})"
            if fallback_parent
            else f"Theo trung tâm {ward}"
        )
        row = {
            "city": city,
            "ward": ward,
            "normalized_ward": key[1],
            "lat": round(lat, 7),
            "lng": round(lng, 7),
            "label": str(source.get("label") or default_label).strip(),
            "source": provenance,
            "source_url": source_url,
        }
        if fallback_parent:
            row["fallback_parent"] = fallback_parent
        if element_key is not None:
            row["osm_type"] = element_key[0]
            row["osm_id"] = element_key[1]
        ward_rows.append(row)
    _validate_canonical_wards(sources, ward_keys)
    return ward_rows, ward_keys


def _generated_road_rows(
    osm_payload: Mapping,
    boundaries: Mapping,
) -> list[dict]:
    grouped: dict[str, list[tuple[Mapping, LineString]]] = {}
    display_names: dict[str, str] = {}
    for element in osm_payload.get("elements") or []:
        tags = element.get("tags") or {}
        if element.get("type") != "way" or not tags.get("highway"):
            continue
        raw_name = str(tags.get("name") or tags.get("ref") or "").strip()
        if not raw_name:
            continue
        line = _way_line(element)
        if line is None:
            continue
        normalized = normalize_road_token(raw_name)
        if not normalized:
            continue
        grouped.setdefault(normalized, []).append((element, line))
        display_names.setdefault(normalized, raw_name)

    rows = []
    for (city, normalized_ward), (ward, polygon, _properties) in boundaries.items():
        for normalized_road, parts in grouped.items():
            clipped_parts = []
            for element, line in parts:
                clipped = line.intersection(polygon)
                if clipped.is_empty or getattr(clipped, "length", 0) <= 0:
                    continue
                clipped_parts.append((int(element["id"]), clipped))
            if not clipped_parts:
                continue
            for clipped_geometry, sorted_ids in _connected_road_components(
                clipped_parts
            ):
                lat, lng = _representative_line_point(clipped_geometry)
                road_name = display_names[normalized_road]
                rows.append(
                    {
                        "city": city,
                        "ward": ward,
                        "normalized_ward": normalized_ward,
                        "road_name": road_name,
                        "normalized_road": normalized_road,
                        "lat": round(lat, 7),
                        "lng": round(lng, 7),
                        "accuracy_radius_m": _accuracy_radius_m(
                            clipped_geometry, lat, lng
                        ),
                        "label": f"Theo tên đường {road_name}, {ward}",
                        "source": "OpenStreetMap",
                        "source_url": (
                            f"https://www.openstreetmap.org/way/{sorted_ids[0]}"
                        ),
                        "osm_way_ids": sorted_ids,
                    }
                )
    return rows


_MAX_AGGREGATE_ROAD_RADIUS_M = 750.0


def _add_aggregate_road_rows(rows: Sequence[dict]) -> list[dict]:
    grouped: dict[tuple[str, str, str], list[dict]] = {}
    for row in rows:
        if row.get("aggregate"):
            continue
        key = (
            str(row["city"]),
            str(row["normalized_ward"]),
            str(row["normalized_road"]),
        )
        grouped.setdefault(key, []).append(row)

    output = list(rows)
    for (_city, _normalized_ward, _normalized_road), parts in sorted(grouped.items()):
        if len(parts) < 2:
            continue
        if any(row.get("landmark_keys") for row in parts):
            continue
        force_aggregate = (
            normalize_location_token(_city),
            _normalized_ward,
            _normalized_road,
        ) in LISTING_MAP_FORCE_AGGREGATE_ROADS
        if any(
            row.get("aggregate")
            and (
                str(row["city"]),
                str(row["normalized_ward"]),
                str(row["normalized_road"]),
            )
            == (_city, _normalized_ward, _normalized_road)
            for row in rows
        ):
            continue
        lat = sum(float(row["lat"]) for row in parts) / len(parts)
        lng = sum(float(row["lng"]) for row in parts) / len(parts)
        radius = max(
            _distance_m(lat, lng, float(row["lat"]), float(row["lng"]))
            + float(row.get("accuracy_radius_m") or 75)
            for row in parts
        )
        if radius > _MAX_AGGREGATE_ROAD_RADIUS_M and not force_aggregate:
            continue
        osm_way_ids = sorted(
            {
                int(way_id)
                for row in parts
                for way_id in (row.get("osm_way_ids") or ())
            }
        )
        first = sorted(
            parts,
            key=lambda row: (
                str(row.get("road_name") or ""),
                float(row["lat"]),
                float(row["lng"]),
            ),
        )[0]
        aggregate = {
            **first,
            "lat": round(lat, 7),
            "lng": round(lng, 7),
            "accuracy_radius_m": round(max(radius, 75.0), 1),
            "source": "OpenStreetMap aggregate",
            "source_url": str(first.get("source_url") or ""),
            "osm_way_ids": osm_way_ids,
            "aggregate": True,
            "component_count": len(parts),
        }
        output.append(aggregate)
    return output


def _legacy_road_rows(
    sources: Mapping,
    index: Mapping,
    *,
    strict: bool = True,
    skip_keys: set[tuple[str, str, str]] | None = None,
) -> tuple[list[dict], list[dict]]:
    rows = []
    rejected = []
    seen = set()
    skip_keys = skip_keys or set()
    for source in sources.get("roads") or []:
        city = str(source.get("city") or "").strip()
        ward = str(source.get("ward") or "").strip()
        road_name = str(source.get("road_name") or "").strip()
        key = city, normalize_location_token(ward), normalize_road_token(road_name)
        if not all(key):
            raise ValueError("road city, ward, and name are required")
        if key in seen:
            raise ValueError(
                f"duplicate normalized road: {city}/{key[1]}/{key[2]}"
            )
        seen.add(key)
        if key in skip_keys:
            continue
        way_ids = sorted({int(item) for item in source.get("osm_way_ids") or []})
        if not way_ids:
            if strict:
                raise ValueError(f"road {road_name} has no OSM way IDs")
            rejected.append(
                {"key": "/".join(key), "reason": "legacy_source_has_no_way_ids"}
            )
            continue
        elements = []
        missing_ids = []
        for way_id in way_ids:
            element = index.get(("way", way_id))
            if not element:
                missing_ids.append(way_id)
                continue
            elements.append(element)
        if missing_ids:
            if strict:
                raise ValueError(
                    f"missing OSM way {missing_ids[0]} for road {road_name}"
                )
            rejected.append(
                {
                    "key": "/".join(key),
                    "reason": "legacy_osm_way_missing",
                    "osm_way_ids": missing_ids,
                }
            )
            continue
        if any(not (element.get("tags") or {}).get("highway") for element in elements):
            if strict:
                bad = next(
                    element
                    for element in elements
                    if not (element.get("tags") or {}).get("highway")
                )
                raise ValueError(f"OSM way {bad.get('id')} is not a highway")
            rejected.append(
                {"key": "/".join(key), "reason": "legacy_way_not_highway"}
            )
            continue
        lat, lng = _road_center(elements)
        rows.append(
            {
                "city": city,
                "ward": ward,
                "normalized_ward": key[1],
                "road_name": road_name,
                "normalized_road": key[2],
                "lat": round(lat, 7),
                "lng": round(lng, 7),
                "accuracy_radius_m": 75.0,
                "label": f"Theo tên đường {road_name}, {ward}",
                "source": "OpenStreetMap",
                "source_url": f"https://www.openstreetmap.org/way/{way_ids[0]}",
                "osm_way_ids": way_ids,
            }
        )
    return rows, rejected


def _generated_landmark_rows(
    osm_payload: Mapping,
    boundaries: Mapping,
    aliases_by_scope: Mapping[tuple[str, str, str], list[str]],
) -> list[dict]:
    grouped = {}
    for element in osm_payload.get("elements") or []:
        tags = element.get("tags") or {}
        name = str(tags.get("name") or "").strip()
        normalized = _normalize_landmark_token(name)
        if not normalized or not _LANDMARK_NAME_RE.search(normalized):
            continue
        try:
            lat, lng = _element_point(element)
        except ValueError:
            continue
        point = Point(lng, lat)
        for (city, normalized_ward), (ward, polygon, _properties) in boundaries.items():
            if not polygon.covers(point):
                continue
            key = city, normalized_ward, normalized
            grouped.setdefault(key, []).append(
                (
                    str(element.get("type") or ""),
                    int(element["id"]),
                    name,
                    ward,
                    lat,
                    lng,
                )
            )

    rows = []
    for (city, normalized_ward, normalized), candidates in grouped.items():
        clusters = []
        for candidate in sorted(candidates, key=lambda item: (item[0], item[1])):
            candidate_lat, candidate_lng = candidate[4], candidate[5]
            for cluster in clusters:
                if any(
                    _distance_m(
                        candidate_lat,
                        candidate_lng,
                        member[4],
                        member[5],
                    )
                    <= 250.0
                    for member in cluster
                ):
                    cluster.append(candidate)
                    break
            else:
                clusters.append([candidate])
        for cluster in clusters:
            element_type, element_id, name, ward, lat, lng = cluster[0]
            cluster_radius = max(
                (
                    _distance_m(lat, lng, member[4], member[5])
                    for member in cluster
                ),
                default=0.0,
            )
            rows.append(
                {
                    "city": city,
                    "ward": ward,
                    "normalized_ward": normalized_ward,
                    "landmark_name": name,
                    "normalized_landmark": normalized,
                    "aliases": _aliases_for_scope(
                        aliases_by_scope,
                        city=city,
                        ward=ward,
                        canonical=normalized,
                    ),
                    "lat": round(lat, 7),
                    "lng": round(lng, 7),
                    "accuracy_radius_m": round(
                        max(cluster_radius, 150.0),
                        1,
                    ),
                    "label": f"Theo địa danh {name}, {ward}",
                    "source": "OpenStreetMap",
                    "source_url": (
                        f"https://www.openstreetmap.org/"
                        f"{element_type}/{element_id}"
                    ),
                    "osm_type": element_type,
                    "osm_id": element_id,
                }
            )
    return rows


def _merge_curated_roads(
    rows: list[dict],
    override_rows: Sequence[Mapping],
    boundaries: Mapping,
    aliases_by_scope: Mapping[tuple[str, str, str], list[str]],
) -> list[dict]:
    curated = {}
    for source in override_rows:
        city = str(source.get("city") or "").strip()
        ward = str(source.get("ward") or "").strip()
        road_name = str(source.get("road_name") or "").strip()
        normalized_ward = normalize_location_token(ward)
        normalized_road = normalize_road_token(road_name)
        if not city or not normalized_ward or not normalized_road:
            raise ValueError("curated road city, ward, and road_name are required")
        lat, lng = _validate_override_point(
            source,
            boundaries=boundaries,
            label=f"curated road {road_name}",
        )
        row = {
            "city": city,
            "ward": ward,
            "normalized_ward": normalized_ward,
            "road_name": road_name,
            "normalized_road": normalized_road,
            "aliases": _aliases_for_scope(
                aliases_by_scope,
                city=city,
                ward=ward,
                canonical=normalized_road,
            ),
            "lat": round(lat, 7),
            "lng": round(lng, 7),
            "accuracy_radius_m": max(
                float(source.get("accuracy_radius_m") or 75), 0
            ),
            "label": str(
                source.get("label") or f"Theo tên đường {road_name}, {ward}"
            ),
            "source": str(source["source"]).strip(),
            "source_url": str(source["source_url"]).strip(),
            "verified_at": str(source["verified_at"]).strip(),
        }
        if source.get("allow_boundary_mismatch"):
            row["boundary_mismatch_reason"] = str(
                source.get("boundary_mismatch_reason") or ""
            ).strip()
        landmark_keys = sorted(
            {
                _normalize_landmark_token(value)
                for value in (source.get("landmark_keys") or [])
                if _normalize_landmark_token(value)
            }
        )
        if landmark_keys:
            row["landmark_keys"] = landmark_keys
        scope_key = tuple(landmark_keys)
        curated_key = (
            city,
            normalized_ward,
            normalized_road,
            scope_key,
        )
        if curated_key in curated:
            raise ValueError(
                "duplicate curated road in the same landmark scope"
            )
        curated[curated_key] = row
    curated_bases = {
        (city, ward, road)
        for city, ward, road, _scope in curated
    }
    preserved = [
        row
        for row in rows
        if (
            row["city"],
            row["normalized_ward"],
            row["normalized_road"],
        )
        not in curated_bases
    ]
    return preserved + list(curated.values())


def _merge_curated_landmarks(
    rows: list[dict],
    override_rows: Sequence[Mapping],
    boundaries: Mapping,
    aliases_by_scope: Mapping[tuple[str, str, str], list[str]],
) -> list[dict]:
    curated = {}
    for source in override_rows:
        city = str(source.get("city") or "").strip()
        ward = str(source.get("ward") or "").strip()
        name = str(source.get("landmark_name") or "").strip()
        normalized_ward = normalize_location_token(ward)
        normalized = _normalize_landmark_token(name)
        if not city or not normalized_ward or not normalized:
            raise ValueError(
                "curated landmark city, ward, and landmark_name are required"
            )
        lat, lng = _validate_override_point(
            source,
            boundaries=boundaries,
            label=f"curated landmark {name}",
        )
        row = {
            "city": city,
            "ward": ward,
            "normalized_ward": normalized_ward,
            "landmark_name": name,
            "normalized_landmark": normalized,
            "aliases": _aliases_for_scope(
                aliases_by_scope,
                city=city,
                ward=ward,
                canonical=normalized,
            ),
            "lat": round(lat, 7),
            "lng": round(lng, 7),
            "accuracy_radius_m": max(
                float(source.get("accuracy_radius_m") or 150), 0
            ),
            "label": str(source.get("label") or f"Theo địa danh {name}, {ward}"),
            "source": str(source["source"]).strip(),
            "source_url": str(source["source_url"]).strip(),
            "verified_at": str(source["verified_at"]).strip(),
        }
        if source.get("allow_boundary_mismatch"):
            row["boundary_mismatch_reason"] = str(
                source.get("boundary_mismatch_reason") or ""
            ).strip()
        curated[(city, normalized_ward, normalized)] = row
    preserved = [
        row
        for row in rows
        if (
            row["city"],
            row["normalized_ward"],
            row["normalized_landmark"],
        )
        not in curated
    ]
    return preserved + list(curated.values())


def _manual_override_identities(
    manual: Mapping,
) -> set[tuple[str, str, str, str, str]]:
    identities = set()
    for kind, collection, name_field, normalizer in (
        ("road", "roads", "road_name", normalize_road_token),
        (
            "landmark",
            "landmarks",
            "landmark_name",
            _normalize_landmark_token,
        ),
    ):
        for row in manual.get(collection) or ():
            base = (
                kind,
                str(row.get("city") or "").strip(),
                normalize_location_token(row.get("ward") or ""),
                normalizer(str(row.get(name_field) or "")),
            )
            if kind == "road":
                landmark_scopes = {
                    _normalize_landmark_token(landmark)
                    for landmark in row.get("landmark_keys") or ()
                    if _normalize_landmark_token(landmark)
                }
                if not landmark_scopes:
                    identities.add((*base, ""))
                for landmark_scope in landmark_scopes:
                    identities.add((
                        *base,
                        landmark_scope,
                    ))
            else:
                identities.add((*base, ""))
    return identities


def _auto_override_identity(
    evidence: BrowserLocationEvidence,
) -> tuple[str, str, str, str, str]:
    normalizer = (
        normalize_road_token
        if evidence.candidate_type == "road"
        else _normalize_landmark_token
    )
    return (
        evidence.candidate_type,
        evidence.city,
        normalize_location_token(evidence.ward),
        normalizer(evidence.canonical),
        (
            _normalize_landmark_token(evidence.landmark_scope)
            if evidence.candidate_type == "road"
            else ""
        ),
    )


def combine_location_overrides(
    manual: Mapping,
    auto: Mapping,
) -> dict:
    """Merge validated automatic suggestions below manual override priority."""
    manual_version = str(manual.get("resolver_version") or "").strip()
    auto_version = str(auto.get("resolver_version") or "").strip()
    if not manual_version or manual_version != auto_version:
        raise ValueError("manual and auto override versions must match")

    combined = {
        "resolver_version": manual_version,
        "road_aliases": [
            dict(row) for row in manual.get("road_aliases") or ()
        ],
        "roads": [dict(row) for row in manual.get("roads") or ()],
        "landmark_aliases": [
            dict(row) for row in manual.get("landmark_aliases") or ()
        ],
        "landmarks": [dict(row) for row in manual.get("landmarks") or ()],
        "auto_override_count": 0,
    }
    manual_identities = _manual_override_identities(manual)
    manual_bases = {
        identity[:4] for identity in manual_identities
    }
    auto_identities = set()
    auto_road_scopes: dict[
        tuple[str, str, str, str],
        set[str],
    ] = {}

    entries = auto.get("entries", [])
    if entries is None:
        entries = []
    if not isinstance(entries, list):
        raise ValueError("auto override entries must be a list")
    for raw_entry in sorted(
        entries,
        key=lambda row: str(
            row.get("candidate_key") if isinstance(row, Mapping) else ""
        ),
    ):
        if not isinstance(raw_entry, Mapping):
            raise ValueError("auto override entry must be an object")
        if str(raw_entry.get("status") or "") != "accepted":
            continue
        try:
            confidence = float(raw_entry.get("confidence"))
        except (TypeError, ValueError):
            continue
        if confidence < LISTING_MAP_AUTO_ACCEPT_THRESHOLD:
            continue

        evidence = BrowserLocationEvidence.from_mapping(raw_entry)
        identity = _auto_override_identity(evidence)
        base_identity = (*identity[:4], "")
        if (
            identity in manual_identities
            or base_identity in manual_identities
            or (
                not identity[4]
                and identity[:4] in manual_bases
            )
        ):
            continue
        if identity in auto_identities:
            raise ValueError("duplicate automatic override identity")
        if evidence.candidate_type == "road":
            base_identity = identity[:4]
            existing_scopes = auto_road_scopes.get(base_identity, set())
            landmark_scope = identity[4]
            if (
                (not landmark_scope and existing_scopes)
                or (landmark_scope and "" in existing_scopes)
            ):
                raise ValueError("overlapping automatic road scopes")

        evidence_hash = str(raw_entry.get("evidence_hash") or "").strip()
        if evidence_hash != canonical_evidence_hash(evidence):
            raise ValueError("automatic override evidence hash mismatch")
        coordinates = parse_google_maps_coordinates(evidence.source_url)
        if coordinates is None:
            raise ValueError("automatic override source coordinates are invalid")
        try:
            stored_coordinates = (
                float(raw_entry["lat"]),
                float(raw_entry["lng"]),
            )
        except (KeyError, TypeError, ValueError):
            raise ValueError(
                "automatic override coordinates are invalid"
            ) from None
        if any(
            abs(stored - derived) > 0.0000001
            for stored, derived in zip(
                stored_coordinates,
                coordinates,
                strict=True,
            )
        ):
            raise ValueError("automatic override coordinates do not match URL")

        alias_row = {
            "city": evidence.city,
            "ward": evidence.ward,
            "canonical": evidence.canonical,
            "aliases": sorted(set(evidence.aliases)),
        }
        curated_row = {
            "accuracy_radius_m": (
                90.0 if evidence.candidate_type == "road" else 140.0
            ),
            "city": evidence.city,
            "lat": coordinates[0],
            "lng": coordinates[1],
            "source": "Google Maps browser suggestion",
            "source_url": evidence.source_url,
            "verified_at": evidence.checked_at,
            "ward": evidence.ward,
        }
        mismatch_reason = legacy_compatibility_reason(
            evidence,
            coordinates[0],
            coordinates[1],
        )
        if mismatch_reason:
            curated_row["allow_boundary_mismatch"] = True
            curated_row["boundary_mismatch_reason"] = mismatch_reason
        if evidence.candidate_type == "road":
            curated_row["road_name"] = evidence.canonical
            if evidence.landmark_scope:
                curated_row["landmark_keys"] = [
                    evidence.landmark_scope
                ]
            combined["road_aliases"].append(alias_row)
            combined["roads"].append(curated_row)
        else:
            curated_row["landmark_name"] = evidence.canonical
            combined["landmark_aliases"].append(alias_row)
            combined["landmarks"].append(curated_row)
        auto_identities.add(identity)
        if evidence.candidate_type == "road":
            auto_road_scopes.setdefault(identity[:4], set()).add(identity[4])
        combined["auto_override_count"] += 1
    return combined


def build_location_registries(
    osm_payload: Mapping,
    sources: Mapping,
    output_dir: Path,
    *,
    overrides: Mapping | None = None,
    auto_overrides: Mapping | None = None,
    boundary_paths: Sequence[Path] = (),
) -> tuple[Path, Path, Path, Path]:
    resolver_version = str(sources.get("resolver_version") or "").strip()
    if not resolver_version:
        raise ValueError("resolver_version is required")
    overrides = overrides or {
        "resolver_version": resolver_version,
        "road_aliases": [],
        "roads": [],
        "landmark_aliases": [],
        "landmarks": [],
    }
    manual_overrides = overrides
    override_version = str(overrides.get("resolver_version") or "").strip()
    if override_version and override_version != resolver_version:
        raise ValueError("override resolver_version does not match sources")
    auto_overrides = auto_overrides or {
        "resolver_version": resolver_version,
        "entries": [],
    }
    overrides = combine_location_overrides(manual_overrides, auto_overrides)

    index = _element_index(osm_payload)
    ward_rows, _ward_keys = _build_ward_rows(sources, index)
    boundaries, boundary_payloads = _load_ward_boundaries(boundary_paths)
    road_aliases = _validate_aliases(
        overrides.get("road_aliases") or [],
        landmark=False,
    )
    landmark_aliases = _validate_aliases(
        overrides.get("landmark_aliases") or [],
        landmark=True,
    )

    generated_roads = (
        _generated_road_rows(osm_payload, boundaries) if boundaries else []
    )
    generated_keys = {
        (row["city"], row["normalized_ward"], row["normalized_road"])
        for row in generated_roads
    }
    legacy_roads, legacy_rejections = _legacy_road_rows(
        sources,
        index,
        strict=not bool(boundaries),
        skip_keys=generated_keys,
    )
    road_rows = _merge_curated_roads(
        legacy_roads + generated_roads,
        overrides.get("roads") or [],
        boundaries,
        road_aliases,
    )
    road_rows = _add_aggregate_road_rows(road_rows)
    for row in road_rows:
        row.setdefault(
            "aliases",
            _aliases_for_scope(
                road_aliases,
                city=row["city"],
                ward=row["ward"],
                canonical=row["normalized_road"],
            ),
        )

    landmark_rows = _generated_landmark_rows(
        osm_payload,
        boundaries,
        landmark_aliases,
    )
    landmark_rows = _merge_curated_landmarks(
        landmark_rows,
        overrides.get("landmarks") or [],
        boundaries,
        landmark_aliases,
    )
    road_key_counts = {}
    for row in road_rows:
        key = (
            row["city"],
            row["normalized_ward"],
            row["normalized_road"],
        )
        road_key_counts[key] = road_key_counts.get(key, 0) + 1
    detected_ambiguous_road_count = sum(
        count > 1 for count in road_key_counts.values()
    )
    landmark_key_counts = {}
    for row in landmark_rows:
        key = (
            row["city"],
            row["normalized_ward"],
            row["normalized_landmark"],
        )
        landmark_key_counts[key] = landmark_key_counts.get(key, 0) + 1
    detected_ambiguous_landmark_count = sum(
        count > 1 for count in landmark_key_counts.values()
    )

    ward_payload = {
        "resolver_version": resolver_version,
        "wards": sorted(
            ward_rows,
            key=lambda row: (
                normalize_location_token(row["city"]),
                row["normalized_ward"],
            ),
        ),
    }
    road_payload = {
        "resolver_version": resolver_version,
        "roads": sorted(
            road_rows,
            key=lambda row: (
                normalize_location_token(row["city"]),
                row["normalized_ward"],
                row["normalized_road"],
                row["lat"],
                row["lng"],
            ),
        ),
    }
    landmark_payload = {
        "resolver_version": resolver_version,
        "landmarks": sorted(
            landmark_rows,
            key=lambda row: (
                normalize_location_token(row["city"]),
                row["normalized_ward"],
                row["normalized_landmark"],
                row["lat"],
                row["lng"],
            ),
        ),
    }
    ward_bytes = _json_bytes(ward_payload)
    road_bytes = _json_bytes(road_payload)
    landmark_bytes = _json_bytes(landmark_payload)
    manifest_payload = {
        "resolver_version": resolver_version,
        "osm_sha256": _payload_sha256(osm_payload),
        "sources_sha256": _payload_sha256(sources),
        "overrides_sha256": _payload_sha256(manual_overrides),
        "auto_overrides_sha256": _payload_sha256(auto_overrides),
        "auto_override_count": int(overrides["auto_override_count"]),
        "boundaries_sha256": _payload_sha256(boundary_payloads),
        "ward_registry_sha256": hashlib.sha256(ward_bytes).hexdigest(),
        "road_registry_sha256": hashlib.sha256(road_bytes).hexdigest(),
        "landmark_registry_sha256": hashlib.sha256(landmark_bytes).hexdigest(),
        "ward_count": len(ward_rows),
        "road_count": len(road_rows),
        "landmark_count": len(landmark_rows),
        "ambiguous_landmark_count": detected_ambiguous_landmark_count,
        "ambiguous_road_count": max(
            int(
                sources.get(
                    "ambiguous_road_count",
                    len(sources.get("ambiguous_roads") or []),
                )
            ),
            detected_ambiguous_road_count,
            0,
        ),
        "rejected_road_count": max(
            int(
                sources.get(
                    "rejected_road_count",
                    len(sources.get("rejected_roads") or []),
                )
            ),
            0,
        )
        + len(legacy_rejections),
        "legacy_rejections": sorted(
            legacy_rejections,
            key=lambda row: (row["key"], row["reason"]),
        ),
    }
    manifest_bytes = _json_bytes(manifest_payload)

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    payloads = (ward_bytes, road_bytes, landmark_bytes, manifest_bytes)
    with tempfile.TemporaryDirectory(
        prefix=".listing-locations-",
        dir=output_dir.parent,
    ) as temporary:
        temporary_dir = Path(temporary)
        for name, content in zip(OUTPUT_NAMES, payloads, strict=True):
            (temporary_dir / name).write_bytes(content)
        for name in OUTPUT_NAMES:
            os.replace(temporary_dir / name, output_dir / name)
    return tuple(output_dir / name for name in OUTPUT_NAMES)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build deterministic listing location registries."
    )
    parser.add_argument("--osm-json", type=Path, required=True)
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--overrides", type=Path, default=LISTING_MAP_OVERRIDE_PATH)
    parser.add_argument(
        "--auto-overrides",
        type=Path,
        default=LISTING_MAP_AUTO_OVERRIDE_PATH,
    )
    parser.add_argument(
        "--boundary",
        type=Path,
        action="append",
        dest="boundaries",
    )
    args = parser.parse_args()

    osm_payload = json.loads(args.osm_json.read_text(encoding="utf-8"))
    sources = json.loads(args.sources.read_text(encoding="utf-8"))
    overrides = json.loads(args.overrides.read_text(encoding="utf-8"))
    auto_overrides = json.loads(
        args.auto_overrides.read_text(encoding="utf-8")
    )
    paths = build_location_registries(
        osm_payload,
        sources,
        args.output_dir,
        overrides=overrides,
        auto_overrides=auto_overrides,
        boundary_paths=tuple(args.boundaries or LISTING_MAP_WARD_BOUNDARY_PATHS),
    )
    for path in paths:
        print(path.as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
