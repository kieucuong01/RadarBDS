from pathlib import Path

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
