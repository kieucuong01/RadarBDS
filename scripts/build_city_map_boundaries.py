"""Build reproducible pre/post-2025 boundary snapshots for city map products."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
import unicodedata

import requests
from shapely import make_valid
from shapely.geometry import (
    GeometryCollection,
    MultiPolygon,
    Polygon,
    mapping,
    shape,
)
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.city_map_products import get_city_map_page


STANFORD_ARCGIS_QUERY_URL = (
    "https://services8.arcgis.com/p9AYirapk3vVPTbb/arcgis/rest/services/"
    "3rd_Level_Administrative_Boundaries_Vietnam/FeatureServer/0/query"
)
STANFORD_METADATA_URL = (
    "https://geodiscovery.uwm.edu/catalog/stanford-dk039bc2779/metadata"
)
STANFORD_SOURCE = "Stanford Geospatial Center / GADM v2.8 snapshot"
DERIVED_SOURCE = "Radar BDS derived boundary"
CURRENT_BOUNDARIES_PATH = (
    ROOT / "static/maps/binh-duong/current-36-wards.geojson"
)
DERIVATION_RULES = {
    "thuan-an": {
        "Vĩnh Phú": {
            "current_units": ("Bình Hòa", "Lái Thiêu"),
        },
    },
    "di-an": {
        "An Bình": {
            "current_units": ("Dĩ An",),
        },
    },
    "ben-cat": {},
}


def _normalized_name(value: str | None) -> str:
    text = (value or "").replace("đ", "d").replace("Đ", "D")
    decomposed = unicodedata.normalize("NFKD", text)
    without_marks = "".join(
        character
        for character in decomposed
        if not unicodedata.combining(character)
    )
    normalized = re.sub(r"\s+", " ", without_marks).strip().casefold()
    return re.sub(r"^(phuong|xa|thi tran)\s+", "", normalized)


def _slugify(value: str) -> str:
    normalized = _normalized_name(value)
    return re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")


def _load_json(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _polygonal(geometry: BaseGeometry, context: str) -> Polygon | MultiPolygon:
    repaired = make_valid(geometry) if not geometry.is_valid else geometry
    if isinstance(repaired, (Polygon, MultiPolygon)) and not repaired.is_empty:
        return repaired
    if isinstance(repaired, GeometryCollection):
        parts = [
            part
            for part in repaired.geoms
            if isinstance(part, (Polygon, MultiPolygon)) and not part.is_empty
        ]
        if parts:
            unioned = unary_union(parts)
            if isinstance(unioned, (Polygon, MultiPolygon)) and not unioned.is_empty:
                return unioned
    raise ValueError(f"{context} must resolve to Polygon/MultiPolygon")


def _round_coordinates(value):
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, (list, tuple)):
        return [_round_coordinates(item) for item in value]
    return value


def _geometry_payload(geometry: BaseGeometry) -> dict:
    payload = mapping(geometry)
    payload["coordinates"] = _round_coordinates(payload["coordinates"])
    return payload


def derive_residual_boundary(
    target: BaseGeometry,
    sourced_boundaries: tuple[BaseGeometry, ...],
    *,
    context: str,
) -> Polygon | MultiPolygon:
    """Return meaningful target area not covered by sourced legacy polygons."""

    target_polygon = _polygonal(target, f"{context} target")
    sourced_union = (
        unary_union(
            [
                _polygonal(item, f"{context} sourced boundary")
                for item in sourced_boundaries
            ]
        )
        if sourced_boundaries
        else GeometryCollection()
    )
    residual = _polygonal(
        target_polygon.difference(sourced_union),
        f"{context} residual",
    )
    pieces = list(residual.geoms) if isinstance(residual, MultiPolygon) else [residual]
    minimum_area = max(target_polygon.area * 0.0005, 1e-12)
    meaningful = [piece for piece in pieces if piece.area >= minimum_area]
    if not meaningful:
        raise ValueError(f"{context} residual has no meaningful polygon")
    derived = _polygonal(
        max(meaningful, key=lambda piece: piece.area),
        f"{context} derived",
    )
    overlap = derived.intersection(sourced_union).area
    if overlap > max(derived.area * 1e-8, 1e-12):
        raise ValueError(f"{context} derived boundary overlaps sourced geometry")
    if not target_polygon.buffer(1e-10).covers(derived):
        raise ValueError(f"{context} derived boundary leaves its target area")
    return derived


def _stanford_features() -> list[dict]:
    response = requests.get(
        STANFORD_ARCGIS_QUERY_URL,
        params={
            "where": "1=1",
            "outFields": "*",
            "f": "geojson",
            "returnGeometry": "true",
            "geometry": "106.35,10.80,107.00,11.35",
            "geometryType": "esriGeometryEnvelope",
            "inSR": "4326",
            "spatialRel": "esriSpatialRelIntersects",
            "outSR": "4326",
        },
        headers={"User-Agent": "Radar BDS city boundary builder/1.0"},
        timeout=60,
    )
    response.raise_for_status()
    payload = response.json()
    features = payload.get("features")
    if not isinstance(features, list):
        raise ValueError("Stanford ArcGIS response has no GeoJSON features")
    return features


def _source_feature_by_name(
    features: list[dict],
    *,
    district: str,
    name: str,
) -> dict:
    for feature in features:
        properties = feature.get("properties") or {}
        if (
            _normalized_name(properties.get("NAME_1"))
            == _normalized_name("Bình Dương")
            and _normalized_name(properties.get("NAME_2"))
            == _normalized_name(district)
            and _normalized_name(properties.get("NAME_3"))
            == _normalized_name(name)
        ):
            return feature
    raise ValueError(f"Missing Stanford boundary: {district} / {name}")


def _current_features(page: dict, current_payload: dict) -> dict[str, dict]:
    by_name = {}
    expected = set(page["current_names"])
    for feature in current_payload.get("features", []):
        properties = feature.get("properties") or {}
        if (
            properties.get("group") == page["city_name"]
            and properties.get("name") in expected
        ):
            by_name[properties["name"]] = feature
    missing = expected - set(by_name)
    if missing:
        raise ValueError(
            f"Missing current {page['city_name']} boundaries: {sorted(missing)}"
        )
    return by_name


def _current_ward_after(page: dict, legacy_name: str) -> str:
    normalized = _normalized_name(legacy_name)
    matches = []
    for current in page["current_units"]:
        former = _normalized_name(current.get("former_units", ""))
        if current["name"] == legacy_name or normalized in former:
            matches.append(current["name"])
    return ", ".join(matches)


def _legacy_feature(
    page: dict,
    unit: dict,
    geometry: BaseGeometry,
    *,
    source_id: str,
    boundary_source: str,
    derived_from: str = "",
) -> dict:
    derived = boundary_source == "derived_boundary"
    return {
        "type": "Feature",
        "properties": {
            "slug": _slugify(unit["name"]),
            "name": unit["name"],
            "layer": "legacy",
            "unit_type": unit["unit_type"],
            "group": f"{page['city_name']} trước 2025",
            "summary": (
                "Ranh suy luận tham khảo từ phần dư hình học."
                if derived
                else "Ranh đơn vị cũ tham khảo từ snapshot hành chính lịch sử."
            ),
            "dashboard_href": page["dashboard_signal_href"],
            "dashboard_label": page["dashboard_label"],
            "source": DERIVED_SOURCE if derived else STANFORD_SOURCE,
            "source_url": STANFORD_METADATA_URL,
            "source_id": source_id,
            "former_units": "",
            "boundary_source": boundary_source,
            "boundary_claim": True,
            "derived_from": derived_from,
            "last_updated": page["updated_at"],
            "is_derived_boundary": derived,
            "boundary_confidence": (
                "derived_reference" if derived else "source_snapshot"
            ),
            "current_ward_after_2025": _current_ward_after(
                page,
                unit["name"],
            ),
        },
        "geometry": _geometry_payload(geometry),
    }


def _current_feature(page: dict, unit: dict, source_feature: dict) -> dict:
    source_properties = source_feature.get("properties") or {}
    geometry = _polygonal(shape(source_feature["geometry"]), unit["name"])
    return {
        "type": "Feature",
        "properties": {
            "slug": _slugify(unit["name"]),
            "name": unit["name"],
            "layer": "current",
            "unit_type": unit["unit_type"],
            "group": page["city_name"],
            "summary": (
                f"Phường {unit['name']} thuộc khu vực {page['city_name']} "
                "sau sắp xếp năm 2025."
            ),
            "dashboard_href": page["dashboard_signal_href"],
            "dashboard_label": page["dashboard_label"],
            "source": source_properties.get("source", "OpenStreetMap"),
            "former_units": unit["former_units"],
        },
        "geometry": _geometry_payload(geometry),
    }


def _legacy_centers(page: dict, legacy_features: list[dict]) -> dict:
    centers = []
    for feature in legacy_features:
        properties = feature["properties"]
        point = shape(feature["geometry"]).representative_point()
        centers.append(
            {
                "type": "Feature",
                "properties": {
                    "name": properties["name"],
                    "source": properties["source"],
                    "source_url": properties["source_url"],
                    "confidence": (
                        "medium"
                        if properties["is_derived_boundary"]
                        else "high"
                    ),
                    "boundary_claim": False,
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [
                        round(point.x, 6),
                        round(point.y, 6),
                    ],
                },
            }
        )
    return {"type": "FeatureCollection", "features": centers}


def build_city_boundaries(
    city_slug: str,
    source_features: list[dict],
    *,
    current_payload: dict | None = None,
) -> tuple[dict, dict, dict]:
    """Build legacy, current, and legacy-center GeoJSON for an allowlisted city."""

    page = get_city_map_page(city_slug)
    if page["city_slug"] == "thu-dau-mot":
        raise ValueError("use the dedicated Thủ Dầu Một boundary builder")
    if current_payload is None:
        current_payload = _load_json(CURRENT_BOUNDARIES_PATH)
    current_by_name = _current_features(page, current_payload)
    source_by_name: dict[str, dict] = {}
    for unit in page["legacy_units"]:
        if unit["name"] in page["derived_legacy_units"]:
            continue
        source_by_name[unit["name"]] = _source_feature_by_name(
            source_features,
            district=page["city_name"],
            name=unit["name"],
        )

    legacy_features = []
    rules = DERIVATION_RULES.get(page["city_slug"])
    if rules is None:
        raise ValueError(f"Missing derivation rules: {page['city_slug']}")
    for unit in page["legacy_units"]:
        name = unit["name"]
        if name in rules:
            rule = rules[name]
            target = unary_union(
                [
                    shape(current_by_name[current_name]["geometry"])
                    for current_name in rule["current_units"]
                ]
            )
            subtract = tuple(
                shape(source_feature["geometry"])
                for source_feature in source_by_name.values()
            )
            geometry = derive_residual_boundary(
                target,
                subtract,
                context=f"{page['city_name']} / {name}",
            )
            derived_from = (
                "Current "
                + ", ".join(rule["current_units"])
                + " boundaries minus all sourced "
                + page["city_name"]
                + " legacy polygons; largest meaningful residual retained"
            )
            legacy_features.append(
                _legacy_feature(
                    page,
                    unit,
                    geometry,
                    source_id=f"derived:{_slugify(name)}",
                    boundary_source="derived_boundary",
                    derived_from=derived_from,
                )
            )
            continue

        source_feature = source_by_name[name]
        source_properties = source_feature.get("properties") or {}
        legacy_features.append(
            _legacy_feature(
                page,
                unit,
                _polygonal(shape(source_feature["geometry"]), name),
                source_id=f"FID:{source_properties.get('FID', '')}",
                boundary_source="source_snapshot",
            )
        )

    current_features = [
        _current_feature(page, unit, current_by_name[unit["name"]])
        for unit in page["current_units"]
    ]
    if len(legacy_features) != page["legacy_count"]:
        raise ValueError("legacy boundary count does not match taxonomy")
    if len(current_features) != page["current_count"]:
        raise ValueError("current boundary count does not match taxonomy")
    legacy_payload = {
        "type": "FeatureCollection",
        "name": (
            f"TP {page['city_name']} trước sắp xếp 2025 - "
            f"{page['legacy_count']} ranh đơn vị cũ tham khảo"
        ),
        "updated_at": page["updated_at"],
        "features": legacy_features,
    }
    current_output = {
        "type": "FeatureCollection",
        "name": (
            f"Khu vực {page['city_name']} sau sắp xếp 2025 - "
            f"{page['current_count']} phường hiện tại"
        ),
        "updated_at": page["updated_at"],
        "features": current_features,
    }
    return legacy_payload, current_output, _legacy_centers(page, legacy_features)


def _write_json(path: Path, payload: dict, *, compact: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":") if compact else None,
        indent=None if compact else 2,
    )
    path.write_text(text + "\n", encoding="utf-8")


def write_city_boundaries(
    city_slug: str,
    legacy: dict,
    current: dict,
    centers: dict,
) -> tuple[Path, Path, Path, Path]:
    page = get_city_map_page(city_slug)
    prefix = city_slug.replace("-", "_")
    config_legacy = (
        ROOT / "config/map_products" / f"{prefix}_legacy_boundaries.geojson"
    )
    config_centers = (
        ROOT / "config/map_products" / f"{prefix}_legacy_ward_centers.geojson"
    )
    static_legacy = ROOT / page["legacy_geojson_url"].lstrip("/")
    static_current = ROOT / page["current_geojson_url"].lstrip("/")
    _write_json(config_legacy, legacy, compact=False)
    _write_json(config_centers, centers, compact=False)
    _write_json(static_legacy, legacy, compact=True)
    _write_json(static_current, current, compact=True)
    return config_legacy, config_centers, static_legacy, static_current


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--city",
        required=True,
        choices=("thuan-an", "di-an", "ben-cat"),
    )
    args = parser.parse_args(argv)
    legacy, current, centers = build_city_boundaries(
        args.city,
        _stanford_features(),
    )
    paths = write_city_boundaries(args.city, legacy, current, centers)
    derived = [
        feature["properties"]["name"]
        for feature in legacy["features"]
        if feature["properties"]["boundary_source"] == "derived_boundary"
    ]
    print(
        f"{args.city} legacy={len(legacy['features'])} "
        f"current={len(current['features'])} "
        f"derived={','.join(derived) if derived else 'none'}"
    )
    for path in paths:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
