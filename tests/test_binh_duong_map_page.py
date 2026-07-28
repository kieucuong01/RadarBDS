from __future__ import annotations

import json
import re
from pathlib import Path

from config.binh_duong_map import (
    BINH_DUONG_CURRENT_AREAS,
    BINH_DUONG_LEGACY_AREAS,
    BINH_DUONG_MAP_PAGE,
)


EXPECTED_LEGACY_NAMES = {
    "Thủ Dầu Một",
    "Bến Cát",
    "Dĩ An",
    "Tân Uyên",
    "Thuận An",
    "Bàu Bàng",
    "Bắc Tân Uyên",
    "Dầu Tiếng",
    "Phú Giáo",
}

EXPECTED_CURRENT_NAMES = {
    "Đông Hòa",
    "Dĩ An",
    "Tân Đông Hiệp",
    "An Phú",
    "Bình Hòa",
    "Lái Thiêu",
    "Thuận An",
    "Thuận Giao",
    "Thủ Dầu Một",
    "Phú Lợi",
    "Chánh Hiệp",
    "Bình Dương",
    "Hòa Lợi",
    "Phú An",
    "Tây Nam",
    "Long Nguyên",
    "Bến Cát",
    "Chánh Phú Hòa",
    "Vĩnh Tân",
    "Bình Cơ",
    "Tân Uyên",
    "Tân Hiệp",
    "Tân Khánh",
    "Thới Hòa",
    "Thường Tân",
    "Bắc Tân Uyên",
    "Phú Giáo",
    "Phước Hòa",
    "Phước Thành",
    "An Long",
    "Trừ Văn Thố",
    "Bàu Bàng",
    "Long Hòa",
    "Thanh An",
    "Dầu Tiếng",
    "Minh Thạnh",
}


def test_binh_duong_map_registry_has_exact_administrative_units():
    assert len(BINH_DUONG_LEGACY_AREAS) == 9
    assert {item["name"] for item in BINH_DUONG_LEGACY_AREAS} == EXPECTED_LEGACY_NAMES
    assert len({item["slug"] for item in BINH_DUONG_LEGACY_AREAS}) == 9

    assert len(BINH_DUONG_CURRENT_AREAS) == 36
    assert {item["name"] for item in BINH_DUONG_CURRENT_AREAS} == EXPECTED_CURRENT_NAMES
    assert len({item["slug"] for item in BINH_DUONG_CURRENT_AREAS}) == 36
    assert sum(item["unit_type"] == "Phường" for item in BINH_DUONG_CURRENT_AREAS) == 24
    assert sum(item["unit_type"] == "Xã" for item in BINH_DUONG_CURRENT_AREAS) == 12


def test_binh_duong_map_registry_uses_safe_dashboard_and_geometry_identifiers():
    all_areas = [*BINH_DUONG_LEGACY_AREAS, *BINH_DUONG_CURRENT_AREAS]

    assert all(item["dashboard_href"].startswith("/?tab=signals") for item in all_areas)
    assert all(item["dashboard_label"].startswith(("Lọc tin", "Xem tin")) for item in all_areas)
    assert all(item["summary"].strip() for item in all_areas)
    assert all(item["group"].strip() for item in all_areas)

    relation_ids = [item["osm_relation_id"] for item in BINH_DUONG_CURRENT_AREAS]
    assert len(set(relation_ids)) == 36
    assert all(isinstance(relation_id, int) and relation_id > 0 for relation_id in relation_ids)


def test_binh_duong_map_page_metadata_targets_the_new_canonical_route():
    assert BINH_DUONG_MAP_PAGE["path"] == "/ban-do-binh-duong"
    assert BINH_DUONG_MAP_PAGE["hero_title"] == "Bản đồ Bình Dương"
    assert BINH_DUONG_MAP_PAGE["default_layer"] == "legacy"
    assert BINH_DUONG_MAP_PAGE["legacy_geojson_path"].endswith("legacy-districts.geojson")
    assert BINH_DUONG_MAP_PAGE["current_geojson_path"].endswith("current-36-wards.geojson")
    assert "?v=" in BINH_DUONG_MAP_PAGE["legacy_geojson_url"]
    assert "?v=" in BINH_DUONG_MAP_PAGE["current_geojson_url"]
    assert len(BINH_DUONG_MAP_PAGE["faq"]) >= 3
    assert len(BINH_DUONG_MAP_PAGE["source_links"]) >= 3


def test_binh_duong_map_geojson_snapshots_match_registry_exactly():
    expected = {
        "legacy": BINH_DUONG_LEGACY_AREAS,
        "current": BINH_DUONG_CURRENT_AREAS,
    }
    paths = {
        "legacy": BINH_DUONG_MAP_PAGE["legacy_geojson_path"],
        "current": BINH_DUONG_MAP_PAGE["current_geojson_path"],
    }

    for layer, areas in expected.items():
        payload = json.loads(Path(paths[layer].lstrip("/")).read_text(encoding="utf-8"))
        features = payload["features"]

        assert payload["type"] == "FeatureCollection"
        assert [feature["properties"]["slug"] for feature in features] == [
            area["slug"] for area in areas
        ]
        assert [feature["properties"]["name"] for feature in features] == [
            area["name"] for area in areas
        ]
        assert {feature["properties"]["layer"] for feature in features} == {layer}
        assert all(
            feature["geometry"]["type"] in {"Polygon", "MultiPolygon"}
            for feature in features
        )


def test_binh_duong_map_route_renders_progressive_content_and_accessible_controls():
    import app as radar_app

    response = radar_app.app.test_client().get("/ban-do-binh-duong")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert len(re.findall(r"<h1(?:\s|>)", html)) == 1
    assert "Bản đồ Bình Dương" in html
    assert (
        '<link rel="canonical" href="https://radarbds.vn/ban-do-binh-duong">'
        in html
    )
    assert 'data-nav="ban-do-binh-duong" aria-current="page"' in html
    assert 'data-map-layer="legacy"' in html
    assert 'data-map-layer="current"' in html
    assert 'data-map-layer="legacy" aria-pressed="true"' in html
    assert 'data-map-layer="current" aria-pressed="false"' in html
    assert 'data-legacy-geojson="/static/maps/binh-duong/legacy-districts.geojson?v=' in html
    assert 'data-current-geojson="/static/maps/binh-duong/current-36-wards.geojson?v=' in html
    assert html.count('data-map-directory-item="legacy"') == 9
    assert html.count('data-map-directory-item="current"') == 36
    assert 'data-binh-duong-map-status' in html
    assert 'aria-live="polite"' in html
    assert 'data-binh-duong-map-fallback' in html
    assert 'data-binh-duong-map-retry' in html
    assert 'data-binh-duong-map-selection' in html
    assert 'data-binh-duong-map-canvas' in html
    assert 'data-map-mobile-cta' in html
    assert "bd-map-20260728-4" in html
    assert "geoBoundaries" in html
    assert "ranh cấp huyện Việt Nam (năm 2020)" in html
    assert "OpenStreetMap" in html
    assert "không thay thế" in html.lower()
    assert 'href="/?tab=signals' in html
    assert 'rel="noopener"' in html
    assert 'target="_blank"' in html
    assert "seo_landing_viewed" in html
    assert html.count('data-track-cta="binh_duong_map_legacy_dashboard"') == 9
    assert html.count('data-track-cta="binh_duong_map_current_dashboard"') == 36
    for internal_term in ("SEO/AIO", "map-first", "Mỗi card", "CTA", "trang detail"):
        assert internal_term not in html


def test_binh_duong_map_schema_has_two_datasets_and_unique_legacy_item_list():
    import app as radar_app

    html = radar_app.app.test_client().get("/ban-do-binh-duong").get_data(as_text=True)
    blocks = re.findall(
        r'<script type="application/ld\+json">\s*(.*?)\s*</script>',
        html,
        re.S,
    )
    payload = json.loads(blocks[-1])
    graph = payload["@graph"]

    assert any(item["@type"] == "WebPage" for item in graph)
    assert any(item["@type"] == "BreadcrumbList" for item in graph)
    assert any(item["@type"] == "FAQPage" for item in graph)
    datasets = [item for item in graph if item["@type"] == "Dataset"]
    assert len(datasets) == 2
    assert all(len(item["isBasedOn"]) >= 2 for item in datasets)

    item_list = next(item for item in graph if item["@type"] == "ItemList")
    urls = [item["url"] for item in item_list["itemListElement"]]
    assert len(urls) == len(set(urls)) == 9
    assert all(
        url.startswith("https://radarbds.vn/ban-do-binh-duong#layer-legacy/area-")
        for url in urls
    )


def test_binh_duong_map_discovery_surfaces_and_tracking_are_wired():
    import app as radar_app

    client = radar_app.app.test_client()
    with radar_app.app.test_request_context("/sitemap.xml"):
        sitemap = radar_app.sitemap_xml().get_data(as_text=True)
    with radar_app.app.test_request_context("/llms.txt"):
        llms = radar_app.llms_txt().get_data(as_text=True)
    planning_html = client.get("/quy-hoach-binh-duong").get_data(as_text=True)
    map_html = client.get("/ban-do-binh-duong").get_data(as_text=True)

    assert sitemap.count("<loc>https://radarbds.vn/ban-do-binh-duong</loc>") == 1
    assert re.search(
        r"<loc>https://radarbds\.vn/ban-do-binh-duong</loc>"
        rf"\s*<lastmod>{BINH_DUONG_MAP_PAGE['updated_at']}</lastmod>",
        sitemap,
    )
    assert llms.count("https://radarbds.vn/ban-do-binh-duong") == 1
    assert 'href="/ban-do-binh-duong"' in planning_html
    assert 'href="/ban-do-binh-duong"' in map_html
    assert "binh_duong_map_layer_selected" in radar_app.ALLOWED_TRACK_ACTIONS
    assert "binh_duong_map_area_selected" in radar_app.ALLOWED_TRACK_ACTIONS


def test_binh_duong_map_page_does_not_emit_future_area_routes():
    import app as radar_app

    html = radar_app.app.test_client().get("/ban-do-binh-duong").get_data(as_text=True)

    for area in [*BINH_DUONG_LEGACY_AREAS, *BINH_DUONG_CURRENT_AREAS]:
        assert f'href="/ban-do-binh-duong/{area["slug"]}"' not in html


def test_binh_duong_map_css_reserves_map_space_and_accessible_controls():
    css = Path("static/css/binh_duong_map.css").read_text(encoding="utf-8")

    assert "min-height: 44px" in css
    assert "scroll-margin-top:" in css
    assert ":focus-visible" in css
    assert "height: 620px" in css
    assert "height: 430px" in css
    assert "scroll-margin-top: 136px" in css
    assert "@media (prefers-reduced-motion: reduce)" in css
    assert "overflow-x: clip" in css
    assert ".bd-map-mobile-cta.is-visible" in css
    assert ".bd-map-current-row .bd-map-area-actions a {\n  display: none;" not in css
    assert ".bd-map-area-card .bd-map-area-actions a {\n    display: none;" not in css
