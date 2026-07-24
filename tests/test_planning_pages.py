import json
from pathlib import Path

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
    assert 'data-planning-empty' in html
    assert "Chưa có bài trong nhóm này" in html
    assert "Đang được xem nhiều" in html
    assert "Vành đai 3" in html
    assert "Mỹ Phước - Tân Vạn" in html
    for page in PLANNING_PAGE_LIST:
        assert f'href="{page["path"]}"' in html
        assert page["category_label"] in html
    assert '"@type": "CollectionPage"' in html
    assert '"@type": "ItemList"' in html
    assert '"@type": "BreadcrumbList"' in html


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
    for action in ("map_layer_toggled", "map_fullscreen_clicked", "map_area_cta_clicked"):
        assert action in radar_app.ALLOWED_TRACK_ACTIONS
        assert action in js


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
