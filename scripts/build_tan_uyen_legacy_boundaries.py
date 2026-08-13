"""Build the checked 12-ward legacy Tân Uyên boundary snapshot."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import unicodedata

import requests
from shapely import make_valid
from shapely.geometry import MultiPolygon, Polygon, mapping, shape
from shapely.ops import unary_union


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "config/map_products/tan_uyen_legacy_boundaries.geojson"
CURRENT_BOUNDARIES = ROOT / "static/maps/binh-duong/current-36-wards.geojson"
QUERY_URL = (
    "https://services8.arcgis.com/p9AYirapk3vVPTbb/arcgis/rest/services/"
    "3rd_Level_Administrative_Boundaries_Vietnam/FeatureServer/0/query"
)
METADATA_URL = (
    "https://geodiscovery.uwm.edu/catalog/stanford-dk039bc2779/metadata"
)
WARDS = (
    "Hội Nghĩa",
    "Khánh Bình",
    "Phú Chánh",
    "Tân Hiệp",
    "Tân Phước Khánh",
    "Tân Vĩnh Hiệp",
    "Thạnh Hội",
    "Thạnh Phước",
    "Thái Hòa",
    "Uyên Hưng",
    "Vĩnh Tân",
    "Bạch Đằng",
)
DERIVED = {
    "Tân Hiệp": ("Tân Hiệp", ("Khánh Bình",)),
    "Thạnh Hội": (
        "Tân Khánh",
        ("Thạnh Phước", "Tân Phước Khánh", "Tân Vĩnh Hiệp", "Thái Hòa"),
    ),
}


def _normalized(value: str | None) -> str:
    text = (value or "").replace("đ", "d").replace("Đ", "D")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", text).strip().casefold()


def _round(value):
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, (list, tuple)):
        return [_round(item) for item in value]
    return value


def _polygonal(geometry, label: str):
    if not geometry.is_valid:
        geometry = make_valid(geometry)
    if isinstance(geometry, (Polygon, MultiPolygon)) and not geometry.is_empty:
        return geometry
    if hasattr(geometry, "geoms"):
        polygons = [
            item
            for item in geometry.geoms
            if isinstance(item, (Polygon, MultiPolygon)) and not item.is_empty
        ]
        if polygons:
            return unary_union(polygons)
    raise ValueError(f"Invalid polygonal geometry: {label}")


def _current_boundary(name: str):
    payload = json.loads(CURRENT_BOUNDARIES.read_text(encoding="utf-8"))
    for feature in payload.get("features") or []:
        props = feature.get("properties") or {}
        if props.get("group") == "Tân Uyên" and props.get("name") == name:
            return _polygonal(shape(feature["geometry"]), name)
    raise ValueError(f"Missing current Tân Uyên boundary: {name}")


def build() -> tuple[dict, list[dict]]:
    response = requests.get(
        QUERY_URL,
        params={
            "where": "1=1",
            "outFields": "*",
            "f": "geojson",
            "returnGeometry": "true",
            "geometry": "106.60,10.88,106.90,11.22",
            "geometryType": "esriGeometryEnvelope",
            "inSR": "4326",
            "spatialRel": "esriSpatialRelIntersects",
            "outSR": "4326",
        },
        headers={"User-Agent": "Radar BDS legacy boundary builder/1.0"},
        timeout=60,
    )
    response.raise_for_status()
    source_features = response.json().get("features") or []
    selected = {}
    for feature in source_features:
        props = feature.get("properties") or {}
        if _normalized(props.get("NAME_1")) != "binh duong":
            continue
        if _normalized(props.get("NAME_2")) != "tan uyen":
            continue
        for ward in WARDS:
            if _normalized(props.get("NAME_3")) == _normalized(ward):
                selected[ward] = feature
                break
    missing = sorted(set(WARDS) - set(selected) - set(DERIVED))
    if missing:
        raise ValueError(f"Missing Stanford Tân Uyên wards: {missing}")

    derived_geometries = {}
    for ward, (current_name, subtract_names) in DERIVED.items():
        current = _current_boundary(current_name)
        subtract = unary_union(
            [_polygonal(shape(selected[name]["geometry"]), name) for name in subtract_names]
        )
        derived_geometries[ward] = _polygonal(
            current.difference(subtract), ward
        )

    output_features = []
    centers = []
    for ward in WARDS:
        source = selected.get(ward)
        geometry = derived_geometries.get(ward)
        if geometry is None:
            geometry = _polygonal(shape(source["geometry"]), ward)
        point = geometry.representative_point()
        centers.append(
            {"ward": ward, "lat": round(point.y, 6), "lng": round(point.x, 6)}
        )
        geometry_payload = mapping(geometry)
        geometry_payload["coordinates"] = _round(geometry_payload["coordinates"])
        is_derived = ward in derived_geometries
        output_features.append(
            {
                "type": "Feature",
                "properties": {
                    "name": ward,
                    "source": (
                        "Radar BDS derived boundary"
                        if is_derived
                        else "Stanford Geospatial Center / GADM v2.8 snapshot"
                    ),
                    "source_url": METADATA_URL,
                    "source_id": (
                        f"derived:{_normalized(ward).replace(' ', '-')}"
                        if is_derived
                        else f"FID:{(source.get('properties') or {}).get('FID', '')}"
                    ),
                    "boundary_claim": True,
                    "boundary_source": (
                        "derived_boundary" if is_derived else "source_snapshot"
                    ),
                    "derived_from": (
                        "Current post-2025 boundary minus sourced legacy neighbours"
                        if is_derived
                        else ""
                    ),
                },
                "geometry": geometry_payload,
            }
        )
    payload = {
        "type": "FeatureCollection",
        "name": "TP Tân Uyên trước sắp xếp 2025 - 12 ranh đơn vị cũ tham khảo",
        "city": "TÂN UYÊN",
        "source": "Stanford Geospatial Center / GADM v2.8 snapshot",
        "updated_at": "2026-08-14",
        "features": output_features,
    }
    return payload, centers


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    payload, centers = build()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"output": str(args.output), "centers": centers}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
