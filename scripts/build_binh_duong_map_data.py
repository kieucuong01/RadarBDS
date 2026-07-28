"""Build deterministic administrative GeoJSON snapshots for the public map page."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode

import requests

from config.binh_duong_map import (
    BINH_DUONG_CURRENT_AREAS,
    BINH_DUONG_LEGACY_AREAS,
    BINH_DUONG_MAP_UPDATED_AT,
    GEObOUNDARIES_ADM2_API,
)


NOMINATIM_LOOKUP_URL = "https://nominatim.openstreetmap.org/lookup"
USER_AGENT = "RadarBDSMapBuilder/1.0 (+https://radarbds.vn/ban-do-binh-duong)"
POLYGON_TYPES = {"Polygon", "MultiPolygon"}
BINH_DUONG_BOUNDS = {
    "min_lon": 106.25,
    "max_lon": 107.10,
    "min_lat": 10.75,
    "max_lat": 11.65,
}


def _http_get_json(url: str) -> Any:
    response = requests.get(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        timeout=60,
    )
    response.raise_for_status()
    return response.json()


def _public_properties(area: dict, layer: str, source: str) -> dict:
    properties = {
        "slug": area["slug"],
        "name": area["name"],
        "layer": layer,
        "unit_type": area["unit_type"],
        "group": area["group"],
        "summary": area["summary"],
        "dashboard_href": area["dashboard_href"],
        "dashboard_label": area["dashboard_label"],
        "source": source,
    }
    if area.get("former_units"):
        properties["former_units"] = area["former_units"]
    return properties


def _feature_collection(name: str, source: str, features: list[dict]) -> dict:
    return {
        "type": "FeatureCollection",
        "name": name,
        "source": source,
        "updated_at": BINH_DUONG_MAP_UPDATED_AT,
        "features": features,
    }


def _geometry_is_in_binh_duong(geometry: dict) -> bool:
    coordinates = geometry.get("coordinates")
    points: list[tuple[float, float]] = []

    def collect(value: Any) -> None:
        if (
            isinstance(value, list)
            and len(value) >= 2
            and isinstance(value[0], (int, float))
            and isinstance(value[1], (int, float))
        ):
            points.append((float(value[0]), float(value[1])))
            return
        if isinstance(value, list):
            for item in value:
                collect(item)

    collect(coordinates)
    if not points:
        return False
    center_lon = (min(point[0] for point in points) + max(point[0] for point in points)) / 2
    center_lat = (min(point[1] for point in points) + max(point[1] for point in points)) / 2
    return (
        BINH_DUONG_BOUNDS["min_lon"] <= center_lon <= BINH_DUONG_BOUNDS["max_lon"]
        and BINH_DUONG_BOUNDS["min_lat"] <= center_lat <= BINH_DUONG_BOUNDS["max_lat"]
    )


def normalize_legacy_features(payload: dict) -> dict:
    features = payload.get("features") if isinstance(payload, dict) else None
    if not isinstance(features, list):
        raise ValueError("invalid geoBoundaries FeatureCollection")

    by_name: dict[str, list[dict]] = {}
    for feature in features:
        properties = feature.get("properties") or {}
        name = str(properties.get("shapeName") or "").strip()
        if name:
            by_name.setdefault(name, []).append(feature)

    expected_names = [area["source_name"] for area in BINH_DUONG_LEGACY_AREAS]
    selected_by_name = {
        name: [
            feature
            for feature in by_name.get(name, [])
            if _geometry_is_in_binh_duong(feature.get("geometry") or {})
        ]
        for name in expected_names
    }
    missing = [name for name in expected_names if len(selected_by_name[name]) != 1]
    if missing:
        raise ValueError(f"missing geoBoundaries features: {', '.join(missing)}")

    normalized: list[dict] = []
    for area in BINH_DUONG_LEGACY_AREAS:
        source_feature = selected_by_name[area["source_name"]][0]
        geometry = source_feature.get("geometry") or {}
        if geometry.get("type") not in POLYGON_TYPES:
            raise ValueError(f"{area['name']} must use polygon geometry")
        normalized.append(
            {
                "type": "Feature",
                "properties": _public_properties(area, "legacy", "geoBoundaries"),
                "geometry": geometry,
            }
        )

    return _feature_collection(
        "9 đơn vị cấp huyện Bình Dương cũ",
        "geoBoundaries ADM2",
        normalized,
    )


def normalize_current_features(payload: list[dict]) -> dict:
    if not isinstance(payload, list):
        raise ValueError("invalid Nominatim lookup response")

    relation_counts = Counter(
        int(item.get("osm_id"))
        for item in payload
        if item.get("osm_type") == "relation" and item.get("osm_id") is not None
    )
    duplicate_ids = sorted(relation_id for relation_id, count in relation_counts.items() if count > 1)
    if duplicate_ids:
        raise ValueError(f"duplicate OpenStreetMap relation: {duplicate_ids[0]}")

    by_id = {
        int(item["osm_id"]): item
        for item in payload
        if item.get("osm_type") == "relation" and item.get("osm_id") is not None
    }
    expected_ids = [area["osm_relation_id"] for area in BINH_DUONG_CURRENT_AREAS]
    missing_ids = [relation_id for relation_id in expected_ids if relation_id not in by_id]
    if missing_ids:
        raise ValueError(f"missing OpenStreetMap relations: {missing_ids[0]}")

    normalized: list[dict] = []
    for area in BINH_DUONG_CURRENT_AREAS:
        source_feature = by_id[area["osm_relation_id"]]
        source_category = str(
            source_feature.get("category")
            or source_feature.get("class")
            or ""
        ).strip()
        source_type = str(source_feature.get("type") or "").strip()
        if source_category != "boundary" or source_type != "administrative":
            raise ValueError(f"{area['name']} must be an administrative boundary")

        expected_name = f"{area['unit_type']} {area['name']}"
        relation_name = str(source_feature.get("name") or "").strip()
        display_name = str(source_feature.get("display_name") or "").strip()
        display_primary_name = display_name.split(",", 1)[0].strip()
        if (
            relation_name.casefold() != expected_name.casefold()
            or display_primary_name.casefold() != expected_name.casefold()
        ):
            raise ValueError(f"OpenStreetMap name mismatch for {area['name']}")

        geometry = source_feature.get("geojson") or {}
        if geometry.get("type") not in POLYGON_TYPES:
            raise ValueError(f"{area['name']} must use polygon geometry")

        try:
            lon = float(source_feature["lon"])
            lat = float(source_feature["lat"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"{area['name']} has invalid coordinates") from exc
        if not (
            BINH_DUONG_BOUNDS["min_lon"] <= lon <= BINH_DUONG_BOUNDS["max_lon"]
            and BINH_DUONG_BOUNDS["min_lat"] <= lat <= BINH_DUONG_BOUNDS["max_lat"]
        ):
            raise ValueError(f"{area['name']} is outside Bình Dương bounds")

        normalized.append(
            {
                "type": "Feature",
                "properties": _public_properties(area, "current", "OpenStreetMap"),
                "geometry": geometry,
            }
        )

    return _feature_collection(
        "36 phường xã thuộc khu vực Bình Dương cũ sau sắp xếp 2025",
        "OpenStreetMap administrative relations",
        normalized,
    )


def _nominatim_lookup_url() -> str:
    osm_ids = ",".join(f"R{area['osm_relation_id']}" for area in BINH_DUONG_CURRENT_AREAS)
    query = urlencode(
        {
            "format": "jsonv2",
            "osm_ids": osm_ids,
            "polygon_geojson": 1,
            "polygon_threshold": 0.0002,
        }
    )
    return f"{NOMINATIM_LOOKUP_URL}?{query}"


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def build_map_files(
    output_dir: Path,
    http_get: Callable[[str], Any] = _http_get_json,
) -> tuple[Path, Path]:
    metadata = http_get(GEObOUNDARIES_ADM2_API)
    geometry_url = str((metadata or {}).get("simplifiedGeometryGeoJSON") or "").strip()
    if not geometry_url.startswith("https://"):
        raise ValueError("geoBoundaries metadata is missing simplified geometry URL")

    legacy = normalize_legacy_features(http_get(geometry_url))
    current = normalize_current_features(http_get(_nominatim_lookup_url()))

    output_dir.mkdir(parents=True, exist_ok=True)
    legacy_path = output_dir / "legacy-districts.geojson"
    current_path = output_dir / "current-36-wards.geojson"
    _write_json(legacy_path, legacy)
    _write_json(current_path, current)
    return legacy_path, current_path


def main() -> int:
    output_dir = Path(__file__).resolve().parents[1] / "static" / "maps" / "binh-duong"
    legacy_path, current_path = build_map_files(output_dir)
    print(f"generated {legacy_path}")
    print(f"generated {current_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
