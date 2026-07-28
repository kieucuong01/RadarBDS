import copy
import json
from pathlib import Path

import pytest

from map_products.models import (
    load_neighborhood_points,
    load_product_spec,
    load_source_registry,
)


ROOT = Path(__file__).resolve().parents[1]


def test_thu_dau_mot_product_has_exact_units_and_price():
    spec = load_product_spec(
        ROOT / "config/map_products/thu_dau_mot_product.json"
    )
    assert spec.slug == "thu-dau-mot-map-bundle"
    assert spec.version == "1.0"
    assert spec.price_vnd == 99_000
    assert spec.formats == ("pdf", "svg", "kml")
    assert set(spec.legacy_wards) == {
        "Chánh Mỹ", "Chánh Nghĩa", "Định Hòa", "Hiệp An", "Hiệp Thành",
        "Hòa Phú", "Phú Cường", "Phú Hòa", "Phú Lợi", "Phú Mỹ",
        "Phú Tân", "Phú Thọ", "Tân An", "Tương Bình Hiệp",
    }
    assert set(spec.current_wards) == {
        "Thủ Dầu Một", "Phú Lợi", "Chánh Hiệp", "Bình Dương", "Phú An",
    }


def test_every_source_has_license_and_snapshot_contract():
    sources = load_source_registry(
        ROOT / "config/map_products/thu_dau_mot_sources.json"
    )
    assert {"legacy_boundaries", "current_boundaries", "osm_detail", "font"} <= {
        source.key for source in sources
    }
    assert all(source.license_name and source.license_url for source in sources)
    assert all(
        source.snapshot_strategy
        in {"fixed_url", "dated_query", "repo_snapshot"}
        for source in sources
    )


def test_neighborhoods_are_named_points_not_claimed_boundaries():
    points = load_neighborhood_points(
        ROOT / "config/map_products/thu_dau_mot_neighborhoods.geojson"
    )
    assert points
    assert all(point.geometry_type == "Point" for point in points)
    assert all(
        point.name and point.source and point.confidence in {"high", "medium"}
        for point in points
    )


def _neighborhood_document() -> dict:
    return json.loads(
        (ROOT / "config/map_products/thu_dau_mot_neighborhoods.geojson").read_text(
            encoding="utf-8"
        )
    )


def _write_neighborhood_document(tmp_path: Path, document: dict) -> Path:
    path = tmp_path / "neighborhoods.geojson"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def test_neighborhood_loader_rejects_polygon_geometry(tmp_path: Path):
    document = _neighborhood_document()
    document["features"][0]["geometry"] = {
        "type": "Polygon",
        "coordinates": [[[106.65, 10.97], [106.66, 10.97], [106.65, 10.97]]],
    }

    with pytest.raises(ValueError, match="Point geometry"):
        load_neighborhood_points(_write_neighborhood_document(tmp_path, document))


def test_neighborhood_loader_rejects_boundary_claims(tmp_path: Path):
    document = _neighborhood_document()
    document["features"][0]["properties"]["boundary_claim"] = True

    with pytest.raises(ValueError, match="boundary_claim must be false"):
        load_neighborhood_points(_write_neighborhood_document(tmp_path, document))


@pytest.mark.parametrize("mutation", ["unknown", "missing"])
def test_neighborhood_loader_rejects_unknown_or_missing_properties(
    tmp_path: Path, mutation: str
):
    document = _neighborhood_document()
    properties = document["features"][0]["properties"]
    if mutation == "unknown":
        properties["unreviewed"] = "value"
    else:
        del properties["source_url"]

    with pytest.raises(ValueError, match="invalid keys"):
        load_neighborhood_points(_write_neighborhood_document(tmp_path, document))


def test_neighborhood_loader_rejects_invalid_coordinates(tmp_path: Path):
    document = _neighborhood_document()
    document["features"][0]["geometry"]["coordinates"][0] = 181

    with pytest.raises(ValueError, match="out of range"):
        load_neighborhood_points(_write_neighborhood_document(tmp_path, document))


def test_neighborhood_loader_rejects_duplicate_names(tmp_path: Path):
    document = _neighborhood_document()
    document["features"].append(copy.deepcopy(document["features"][0]))

    with pytest.raises(ValueError, match="duplicate names"):
        load_neighborhood_points(_write_neighborhood_document(tmp_path, document))
