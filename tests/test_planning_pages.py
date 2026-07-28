import json
import re
from pathlib import Path

import pytest

from config.planning_pages import PLANNING_PAGE_LIST


def test_planning_hub_renders_category_cards_and_nav():
    import app as radar_app

    response = radar_app.app.test_client().get("/quy-hoach-binh-duong")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert '<link rel="canonical" href="https://radarbds.vn/quy-hoach-binh-duong">' in html
    assert "Bản đồ quy hoạch Bình Dương cũ" in html
    assert 'data-nav="quy-hoach" aria-current="page"' in html
    assert 'data-planning-filter="transport"' in html
    assert 'data-planning-filter="boundary"' in html
    assert 'data-planning-filter="landuse"' not in html
    assert 'data-planning-filter="industrial"' not in html
    assert 'role="group"' in html
    assert 'aria-pressed="true"' in html
    assert "Tất cả (5)" in html
    assert "Tuyến giao thông (4)" in html
    assert "Địa giới (1)" in html
    assert 'data-planning-empty' in html
    assert "Chưa có bài trong nhóm này" in html
    assert "Nên xem trước" in html
    assert "Đang được xem nhiều" not in html
    assert "Vành đai 3" in html
    assert "Mỹ Phước - Tân Vạn" in html
    for page in PLANNING_PAGE_LIST:
        assert f'href="{page["path"]}"' in html
        assert page["category_label"] in html
    assert '"@type": "CollectionPage"' in html
    assert '"@type": "ItemList"' in html
    assert '"@type": "BreadcrumbList"' in html


def test_planning_hub_rejects_unknown_categories():
    import app as radar_app

    resolver = getattr(radar_app, "_planning_category_for_page", None)
    assert callable(resolver)

    with pytest.raises(ValueError, match="Unknown planning category"):
        resolver({"slug": "invalid", "category": "not-a-category"})


def test_planning_hub_renders_data_derived_stats_and_user_language():
    import app as radar_app

    html = radar_app.app.test_client().get("/quy-hoach-binh-duong").get_data(as_text=True)

    assert "5 chuyên đề" in html
    assert "2 nhóm nội dung" in html
    assert "Cập nhật gần nhất" in html
    assert "Bình Dương cũ là địa bàn tỉnh Bình Dương trước khi sắp xếp hành chính" in html
    assert "Chọn bản đồ cần xem" in html
    assert "Lọc tin đang bán theo khu vực" in html
    for internal_term in ("Map-first", "Mỗi card", "trang detail", "CTA về dashboard", "Signal khu này"):
        assert internal_term not in html


def test_planning_hub_cards_use_unique_previews_and_explicit_dashboard_labels():
    import app as radar_app

    html = radar_app.app.test_client().get("/quy-hoach-binh-duong").get_data(as_text=True)
    preview_paths = re.findall(
        r'<img[^>]+src="(/static/maps/planning/previews/[^"]+\.svg)"',
        html,
    )

    assert len(preview_paths) == 5
    assert len(set(preview_paths)) == 5
    assert 'loading="lazy"' in html
    assert 'width="480"' in html
    assert 'height="300"' in html
    assert html.count("Xem tin Thủ Dầu Một") == 2
    assert html.count("Xem tin Bến Cát") == 2
    assert html.count("Xem toàn bộ tin") == 1
    for page in PLANNING_PAGE_LIST:
        assert f'data-planning-slug="{page["slug"]}"' in html
        assert f'/static/maps/planning/previews/{page["slug"]}.svg' in html


def test_planning_hub_tracking_partial_and_hooks_are_present():
    import app as radar_app

    html = radar_app.app.test_client().get("/quy-hoach-binh-duong").get_data(as_text=True)

    assert "seo_landing_viewed" in html
    assert 'data-track-cta="planning_hub_hero_list"' in html
    assert 'data-track-cta="planning_hub_hero_dashboard"' in html
    assert 'data-track-cta="planning_hub_article_thumb"' in html
    assert 'data-track-cta="planning_hub_article_title"' in html
    assert 'data-track-cta="planning_hub_article_open"' in html
    assert 'data-track-cta="planning_hub_article_dashboard"' in html
    assert "planning_hub_filter_selected" in radar_app.ALLOWED_TRACK_ACTIONS
    assert "planning_hub_card_clicked" in radar_app.ALLOWED_TRACK_ACTIONS


def test_planning_hub_item_list_is_unique_and_keeps_editorial_order():
    import app as radar_app

    html = radar_app.app.test_client().get("/quy-hoach-binh-duong").get_data(as_text=True)
    blocks = re.findall(r'<script type="application/ld\+json">\s*(.*?)\s*</script>', html, re.S)
    payload = json.loads(blocks[-1])
    item_list = next(item for item in payload["@graph"] if item["@type"] == "ItemList")
    urls = [item["url"] for item in item_list["itemListElement"]]

    expected = [f"https://radarbds.vn{page['path']}" for page in PLANNING_PAGE_LIST]
    assert urls == expected
    assert len(urls) == len(set(urls)) == 5


def test_planning_detail_map_first_contract_and_schema():
    import app as radar_app

    path = "/quy-hoach-binh-duong/vanh-dai-3"
    response = radar_app.app.test_client().get(path)
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert f'<link rel="canonical" href="https://radarbds.vn{path}">' in html
    assert "Bản đồ Vành đai 3 qua Bình Dương cũ" in html
    assert 'class="planning-map"' in html
    assert 'data-geojson="/static/maps/planning/vanh-dai-3.geojson"' in html
    assert "leaflet@1.9.4/dist/leaflet.css" in html
    assert 'integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY="' in html
    assert "leaflet@1.9.4/dist/leaflet.js" in html
    assert "Thông tin tham khảo" in html
    assert "Không thay thế tra cứu pháp lý thửa đất" in html
    assert "Lớp bản đồ" in html
    assert "Tin đang bán quanh khu này" in html
    assert "Tổng quan các phân đoạn Vành đai 3" in html
    assert "Tân Vạn - Bình Chuẩn" in html
    assert "Focus trên bản đồ" in html
    assert "Khu vực Bình Dương bị ảnh hưởng" in html
    assert 'data-map-area-cta' in html
    assert '"@type": "Article"' in html
    assert '"@type": "FAQPage"' in html
    assert '"@type": "Dataset"' in html
    assert '"@type": "BreadcrumbList"' in html


def test_all_planning_detail_pages_render_and_are_indexed():
    import app as radar_app

    client = radar_app.app.test_client()
    with radar_app.app.test_request_context("/sitemap.xml"):
        sitemap = radar_app.sitemap_xml().get_data(as_text=True)

    assert "<loc>https://radarbds.vn/quy-hoach-binh-duong</loc>" in sitemap
    for page in PLANNING_PAGE_LIST:
        response = client.get(page["path"])
        html = response.get_data(as_text=True)

        assert response.status_code == 200
        assert f'<link rel="canonical" href="https://radarbds.vn{page["path"]}">' in html
        assert f"<loc>https://radarbds.vn{page['path']}</loc>" in sitemap
        assert page["hero_title"] in html
        assert page["geojson_path"] in html
        assert "/quy-hoach-binh-duong" in html
        assert 'href="/?tab=signals' in html


def test_planning_llms_and_tracking_hooks_are_wired():
    import app as radar_app

    with radar_app.app.test_request_context("/llms.txt"):
        llms = radar_app.llms_txt().get_data(as_text=True)
    js = Path("static/js/planning_maps.js").read_text(encoding="utf-8")

    assert "https://radarbds.vn/quy-hoach-binh-duong" in llms
    assert "https://radarbds.vn/quy-hoach-binh-duong/vanh-dai-3" in llms
    assert "https://radarbds.vn/quy-hoach-binh-duong/dia-gioi-36-phuong-xa-binh-duong-cu" in llms
    for page in PLANNING_PAGE_LIST:
        assert f"https://radarbds.vn{page['path']}" in llms
    for action in ("map_layer_toggled", "map_fullscreen_clicked", "map_area_cta_clicked"):
        assert action in radar_app.ALLOWED_TRACK_ACTIONS
        assert action in js


def test_planning_sitemap_uses_updated_at_as_lastmod():
    import app as radar_app

    with radar_app.app.test_request_context("/sitemap.xml"):
        sitemap = radar_app.sitemap_xml().get_data(as_text=True)

    for page in [radar_app.PLANNING_HUB, *PLANNING_PAGE_LIST]:
        entry = re.search(
            rf"<url>\s*<loc>https://radarbds\.vn{re.escape(page['path'])}</loc>"
            rf"\s*<lastmod>{re.escape(page['updated_at'])}</lastmod>",
            sitemap,
        )
        assert entry, page["path"]


def test_planning_pages_use_shareable_og_image_and_current_cache_keys():
    import app as radar_app

    client = radar_app.app.test_client()
    for path in ["/quy-hoach-binh-duong", PLANNING_PAGE_LIST[0]["path"]]:
        html = client.get(path).get_data(as_text=True)
        assert (
            '<meta property="og:image" '
            'content="https://radarbds.vn/static/images/seo/radarbds-og.png">'
        ) in html
        assert "planning-hub-20260728-1" in html or "planning-map-20260728-1" in html


def test_planning_geojson_files_are_valid_feature_collections():
    for page in PLANNING_PAGE_LIST:
        path = Path(page["geojson_path"].lstrip("/"))
        payload = json.loads(path.read_text(encoding="utf-8"))

        assert payload["type"] == "FeatureCollection"
        assert payload["features"]
        layers = {feature["properties"]["layer"] for feature in payload["features"]}
        assert layers
        assert layers.intersection({"route", "boundary"})
        for feature in payload["features"]:
            assert feature["geometry"]["type"] in {"LineString", "Polygon", "Point"}
            assert feature["properties"]["name"]
