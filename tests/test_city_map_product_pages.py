from __future__ import annotations

import json
import re

import pytest


CITY_CASES = (
    (
        "/ban-do-thuan-an",
        "Thuận An",
        "thuan-an",
        "thuan-an-map-bundle",
        10,
        5,
        "Vĩnh Phú",
    ),
    (
        "/ban-do-di-an",
        "Dĩ An",
        "di-an",
        "di-an-map-bundle",
        7,
        3,
        "An Bình",
    ),
    (
        "/ban-do-ben-cat",
        "Bến Cát",
        "ben-cat",
        "ben-cat-map-bundle",
        8,
        6,
        "",
    ),
)


def _graph(response) -> list[dict]:
    blocks = re.findall(
        r'<script type="application/ld\+json">\s*(.*?)\s*</script>',
        response.get_data(as_text=True),
        re.S,
    )
    assert blocks
    return json.loads(blocks[-1])["@graph"]


@pytest.mark.parametrize(
    (
        "path",
        "city_name",
        "city_slug",
        "product_slug",
        "legacy_count",
        "current_count",
        "derived_name",
    ),
    CITY_CASES,
)
def test_city_page_has_unique_content_schema_and_server_checkout(
    path,
    city_name,
    city_slug,
    product_slug,
    legacy_count,
    current_count,
    derived_name,
):
    import app as radar_app

    response = radar_app.app.test_client().get(path)
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert f"<h1>Bản đồ TP {city_name}" in html
    assert f"Bản đồ TP {city_name} tương tác" in html
    assert f"{legacy_count} " in html
    assert f"{current_count} phường hiện tại" in html
    assert f'data-checkout-path="{path}/checkout"' in html
    assert f'data-product-slug="{product_slug}"' in html
    assert "/ban-do-thu-dau-mot/checkout" not in html
    assert "Hòa Phú và Phú Tân" not in html
    if derived_name:
        assert derived_name in html
        assert "ranh suy luận" in html

    graph = _graph(response)
    item_lists = [item for item in graph if item.get("@type") == "ItemList"]
    assert [item["numberOfItems"] for item in item_lists] == [
        legacy_count,
        current_count,
    ]
    product = next(item for item in graph if item.get("@type") == "Product")
    assert product["sku"] == f"{product_slug}-v1.0"
    datasets = [item for item in graph if item.get("@type") == "Dataset"]
    assert {item["@id"] for item in datasets} == {
        f"https://radarbds.vn{path}#dataset-legacy-{legacy_count}-{city_slug}",
        f"https://radarbds.vn{path}#dataset-current-{current_count}-{city_slug}",
    }


@pytest.mark.parametrize(
    "city_slug,edition,expected_count",
    tuple(
        (case[2], edition, count)
        for case in CITY_CASES
        for edition, count in (
            ("truoc-sap-nhap", case[4]),
            ("sau-sap-nhap", case[5]),
        )
    ),
)
def test_city_geojson_routes_are_allowlisted_and_cacheable(
    city_slug,
    edition,
    expected_count,
):
    import app as radar_app

    response = radar_app.app.test_client().get(
        f"/du-lieu/ban-do-{city_slug}/{edition}.geojson"
    )

    assert response.status_code == 200
    assert response.headers["Content-Type"] == (
        "application/geo+json; charset=utf-8"
    )
    assert response.headers["Cache-Control"] == "public, max-age=86400"
    assert len(response.get_json()["features"]) == expected_count


def test_unknown_city_or_edition_geojson_is_404():
    import app as radar_app

    client = radar_app.app.test_client()
    assert (
        client.get(
            "/du-lieu/ban-do-khong-ton-tai/truoc-sap-nhap.geojson"
        ).status_code
        == 404
    )
    assert (
        client.get(
            "/du-lieu/ban-do-thuan-an/khong-hop-le.geojson"
        ).status_code
        == 404
    )
