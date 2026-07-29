from pathlib import Path
import json

import pytest


EXPECTED_COUNTS = {
    "thu-dau-mot": (14, 5),
    "thuan-an": (10, 5),
    "di-an": (7, 3),
    "ben-cat": (8, 6),
}

EXPECTED_PATHS = {
    "/ban-do-thu-dau-mot",
    "/ban-do-thuan-an",
    "/ban-do-di-an",
    "/ban-do-ben-cat",
}


def test_registry_exposes_unique_city_pages_and_product_identity():
    from config.city_map_products import CITY_MAP_PRODUCTS, get_city_map_page

    pages = [get_city_map_page(slug) for slug in EXPECTED_COUNTS]

    assert set(CITY_MAP_PRODUCTS) == set(EXPECTED_COUNTS)
    assert {page["path"] for page in pages} == EXPECTED_PATHS
    assert len({page["product_slug"] for page in pages}) == 4
    assert len({page["tracking_prefix"] for page in pages}) == 4
    assert all(page["price_vnd"] == 99_000 for page in pages)


@pytest.mark.parametrize(
    ("city_slug", "legacy_count", "current_count"),
    [
        ("thu-dau-mot", 14, 5),
        ("thuan-an", 10, 5),
        ("di-an", 7, 3),
        ("ben-cat", 8, 6),
    ],
)
def test_registry_taxonomy_counts_match_each_city(
    city_slug,
    legacy_count,
    current_count,
):
    from config.city_map_products import get_city_map_page

    page = get_city_map_page(city_slug)

    assert len(page["legacy_units"]) == legacy_count
    assert len(page["current_units"]) == current_count
    assert page["legacy_count"] == legacy_count
    assert page["current_count"] == current_count
    assert len({item["name"] for item in page["legacy_units"]}) == legacy_count
    assert len({item["name"] for item in page["current_units"]}) == current_count


def test_ben_cat_preserves_legacy_phu_an_as_commune():
    from config.city_map_products import get_city_map_page

    page = get_city_map_page("ben-cat")
    phu_an = next(
        item for item in page["legacy_units"] if item["name"] == "Phú An"
    )

    assert phu_an["unit_type"] == "Xã cũ"


def test_unknown_city_and_path_are_rejected():
    from config.city_map_products import (
        get_city_map_page,
        get_city_map_page_by_path,
    )

    with pytest.raises(KeyError):
        get_city_map_page("../../etc")
    with pytest.raises(KeyError):
        get_city_map_page_by_path("/ban-do-khong-ton-tai")


@pytest.mark.parametrize(
    ("filename", "city_slug", "city_name", "derived"),
    [
        (
            "thu_dau_mot_product.json",
            "thu-dau-mot",
            "Thủ Dầu Một",
            ("Hòa Phú", "Phú Tân"),
        ),
        ("thuan_an_product.json", "thuan-an", "Thuận An", ("Vĩnh Phú",)),
        ("di_an_product.json", "di-an", "Dĩ An", ("An Bình",)),
        ("ben_cat_product.json", "ben-cat", "Bến Cát", ()),
    ],
)
def test_product_specs_carry_city_identity_and_derived_boundary_contract(
    filename,
    city_slug,
    city_name,
    derived,
):
    from map_products.models import load_product_spec

    spec = load_product_spec(Path("config/map_products") / filename)

    assert spec.city_slug == city_slug
    assert spec.city_name == city_name
    assert spec.derived_legacy_wards == derived
    assert spec.price_vnd == 99_000


def test_product_spec_rejects_derived_name_outside_legacy_taxonomy(tmp_path):
    from map_products.models import load_product_spec

    payload = json.loads(
        Path("config/map_products/di_an_product.json").read_text(encoding="utf-8")
    )
    payload["derived_legacy_wards"] = ["Không thuộc Dĩ An"]
    path = tmp_path / "invalid-product.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError, match="derived_legacy_wards"):
        load_product_spec(path)
