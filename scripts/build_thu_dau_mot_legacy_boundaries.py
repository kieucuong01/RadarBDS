"""Build the checked 14-ward legacy boundary snapshot for Thu Dau Mot.

The script intentionally does not copy coordinates from commercial reference
pages. It combines a public historical GADM v2.8 snapshot for the 12 available
legacy Thu Dau Mot wards with the already-curated current OSM boundary for the
new Bình Dương ward. The two wards missing from the historical snapshot
(`Hòa Phú`, `Phú Tân`) are derived from the residual area after removing sourced
`Phú Mỹ` and `Phú Chánh`, then assigned to the nearest legacy ward centre.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
import unicodedata

import requests
from shapely import make_valid
from shapely.geometry import MultiPolygon, Point, Polygon, mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from map_products.models import load_product_spec


STANFORD_ARCGIS_QUERY_URL = (
    "https://services8.arcgis.com/p9AYirapk3vVPTbb/arcgis/rest/services/"
    "3rd_Level_Administrative_Boundaries_Vietnam/FeatureServer/0/query"
)
STANFORD_METADATA_URL = (
    "https://geodiscovery.uwm.edu/catalog/stanford-dk039bc2779/metadata"
)
CURRENT_BOUNDARIES_PATH = ROOT / "static/maps/binh-duong/current-36-wards.geojson"
LEGACY_CENTERS_PATH = (
    ROOT / "config/map_products/thu_dau_mot_legacy_ward_centers.geojson"
)
SPEC_PATH = ROOT / "config/map_products/thu_dau_mot_product.json"
DEFAULT_OUTPUT_PATH = (
    ROOT / "config/map_products/thu_dau_mot_legacy_boundaries.geojson"
)

DERIVED_NAMES = ("Hòa Phú", "Phú Tân")
DERIVED_NAME_SET = set(DERIVED_NAMES)
SOURCE_TEXT = "Stanford Geospatial Center / GADM v2.8 snapshot"
DERIVED_TEXT = "Radar BDS derived boundary"
DERIVED_FROM = (
    "Current Bình Dương ward boundary minus sourced Phú Mỹ and Phú Chánh "
    "polygons; residual pieces assigned to nearest legacy ward center"
)


def _normalized_name(value: str | None) -> str:
    text = (value or "").replace("\u0111", "d").replace("\u0110", "D")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(character for character in text if not unicodedata.combining(character))
    text = re.sub(r"\s+", " ", text).strip().casefold()
    return re.sub(r"^(phuong|xa|thi tran)\s+", "", text)


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _polygonal(geometry: BaseGeometry, context: str) -> Polygon | MultiPolygon:
    repaired = make_valid(geometry) if not geometry.is_valid else geometry
    if isinstance(repaired, (Polygon, MultiPolygon)) and not repaired.is_empty:
        return repaired
    if hasattr(repaired, "geoms"):
        polygons = [
            part
            for part in repaired.geoms
            if isinstance(part, (Polygon, MultiPolygon)) and not part.is_empty
        ]
        if polygons:
            unioned = unary_union(polygons)
            if isinstance(unioned, (Polygon, MultiPolygon)) and not unioned.is_empty:
                return unioned
    raise ValueError(f"{context} must resolve to Polygon/MultiPolygon")


def _round_coordinates(value):
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, list):
        return [_round_coordinates(item) for item in value]
    if isinstance(value, tuple):
        return [_round_coordinates(item) for item in value]
    return value


def _stanford_features() -> list[dict]:
    response = requests.get(
        STANFORD_ARCGIS_QUERY_URL,
        params={
            "where": "1=1",
            "outFields": "*",
            "f": "geojson",
            "returnGeometry": "true",
            "geometry": "106.55,10.90,106.85,11.15",
            "geometryType": "esriGeometryEnvelope",
            "inSR": "4326",
            "spatialRel": "esriSpatialRelIntersects",
            "outSR": "4326",
        },
        headers={"User-Agent": "Radar BDS legacy boundary builder/1.0"},
        timeout=60,
    )
    response.raise_for_status()
    payload = response.json()
    features = payload.get("features")
    if not isinstance(features, list):
        raise ValueError("Stanford ArcGIS response has no GeoJSON features")
    return features


def _feature_by_name(
    features: list[dict],
    *,
    province: str,
    district: str,
    name: str,
) -> dict:
    for feature in features:
        properties = feature.get("properties") or {}
        if (
            _normalized_name(properties.get("NAME_1")) == _normalized_name(province)
            and _normalized_name(properties.get("NAME_2")) == _normalized_name(district)
            and _normalized_name(properties.get("NAME_3")) == _normalized_name(name)
        ):
            return feature
    raise ValueError(f"Missing source feature: {province} / {district} / {name}")


def _source_boundary_feature(name: str, source_feature: dict) -> dict:
    properties = source_feature.get("properties") or {}
    geometry = _polygonal(shape(source_feature["geometry"]), name)
    geometry_payload = mapping(geometry)
    geometry_payload["coordinates"] = _round_coordinates(geometry_payload["coordinates"])
    return {
        "type": "Feature",
        "properties": {
            "name": name,
            "source": SOURCE_TEXT,
            "source_url": STANFORD_METADATA_URL,
            "boundary_claim": True,
            "boundary_source": "source_snapshot",
            "derived_from": "",
            "source_id": f"FID:{properties.get('FID', '')}",
        },
        "geometry": geometry_payload,
    }


def _current_binh_duong_boundary() -> BaseGeometry:
    payload = _load_json(CURRENT_BOUNDARIES_PATH)
    for feature in payload.get("features", []):
        properties = feature.get("properties") or {}
        if _normalized_name(properties.get("name")) == "binh duong":
            return _polygonal(shape(feature["geometry"]), "current Bình Dương")
    raise ValueError("Missing current Bình Dương ward boundary")


def _legacy_centers() -> dict[str, Point]:
    payload = _load_json(LEGACY_CENTERS_PATH)
    centers: dict[str, Point] = {}
    for feature in payload.get("features", []):
        properties = feature.get("properties") or {}
        name = properties.get("name")
        geometry = feature.get("geometry") or {}
        if isinstance(name, str) and geometry.get("type") == "Point":
            centers[name] = Point(geometry["coordinates"])
    return centers


def _derived_boundary_features(
    source_features: list[dict],
    sourced_by_name: dict[str, dict],
) -> dict[str, dict]:
    current_binh_duong = _current_binh_duong_boundary()
    source_phu_my = shape(sourced_by_name["Phú Mỹ"]["geometry"])
    source_phu_chanh = shape(
        _feature_by_name(
            source_features,
            province="Bình Dương",
            district="Tân Uyên",
            name="Phú Chánh",
        )["geometry"]
    )
    residual = _polygonal(
        current_binh_duong.difference(unary_union([source_phu_my, source_phu_chanh])),
        "Hòa Phú/Phú Tân residual",
    )
    pieces = list(residual.geoms) if isinstance(residual, MultiPolygon) else [residual]
    pieces = [piece for piece in pieces if piece.area > 0.0000001]
    if len(pieces) < 2:
        raise ValueError("Residual must contain at least two meaningful pieces")

    centers = _legacy_centers()
    missing_centers = sorted(DERIVED_NAME_SET - set(centers))
    if missing_centers:
        raise ValueError(f"Missing legacy centers for derived wards: {missing_centers}")

    grouped: dict[str, list[BaseGeometry]] = {name: [] for name in DERIVED_NAMES}
    for piece in pieces:
        nearest_name = min(
            DERIVED_NAMES,
            key=lambda name: piece.distance(centers[name]),
        )
        grouped[nearest_name].append(piece)

    features: dict[str, dict] = {}
    for name in DERIVED_NAMES:
        if not grouped[name]:
            raise ValueError(f"Derived ward {name} received no residual geometry")
        geometry = _polygonal(unary_union(grouped[name]), name)
        geometry_payload = mapping(geometry)
        geometry_payload["coordinates"] = _round_coordinates(
            geometry_payload["coordinates"]
        )
        features[name] = {
            "type": "Feature",
            "properties": {
                "name": name,
                "source": DERIVED_TEXT,
                "source_url": STANFORD_METADATA_URL,
                "boundary_claim": True,
                "boundary_source": "derived_boundary",
                "derived_from": DERIVED_FROM,
                "source_id": f"derived:{_normalized_name(name).replace(' ', '-')}",
            },
            "geometry": geometry_payload,
        }
    return features


def build_legacy_boundaries() -> dict:
    spec = load_product_spec(SPEC_PATH)
    source_features = _stanford_features()
    sourced_by_name: dict[str, dict] = {}
    for name in spec.legacy_wards:
        if name in DERIVED_NAME_SET:
            continue
        source_feature = _feature_by_name(
            source_features,
            province="Bình Dương",
            district="Thủ Dầu Một",
            name=name,
        )
        sourced_by_name[name] = _source_boundary_feature(name, source_feature)

    derived = _derived_boundary_features(source_features, sourced_by_name)
    output_features = []
    for name in spec.legacy_wards:
        output_features.append(derived[name] if name in derived else sourced_by_name[name])
    if len(output_features) != 14:
        raise ValueError("Legacy boundary snapshot must contain 14 features")
    return {
        "type": "FeatureCollection",
        "name": "TP Thủ Dầu Một trước sắp xếp 2025 - 14 ranh phường tham khảo",
        "source": (
            "12 boundaries from Stanford Geospatial Center GADM v2.8 snapshot; "
            "Hòa Phú and Phú Tân derived by Radar BDS from current OSM boundary "
            "and sourced neighbouring polygons"
        ),
        "updated_at": "2026-07-29",
        "features": output_features,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    args = parser.parse_args(argv)
    payload = build_legacy_boundaries()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"legacy_boundaries={args.output}")
    print(f"features={len(payload['features'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
