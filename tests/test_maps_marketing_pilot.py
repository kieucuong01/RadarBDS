from urllib.parse import parse_qs, urlsplit

import app as radar_app
from config.seo_articles import SEO_ARTICLES
from scripts.radar_social_auto_post import article_candidates


GUIDE = "cach-doc-ban-do-su-dung-dat-2030-va-quy-hoach-phan-khu"


def test_planning_examples_connect_public_routes_to_scoped_maps():
    client = radar_app.app.test_client()
    for path in ("/ban-do-thu-dau-mot", "/ban-do-ben-cat"):
        response = client.get(path)
        assert response.status_code == 200
        assert 'data-map-selection-planning' in response.get_data(as_text=True)
    for path in ("/binh-duong/ben-cat", "/binh-duong/my-phuoc"):
        assert "Mở quy hoạch khu vực" in client.get(path).get_data(as_text=True)

    guide = SEO_ARTICLES[GUIDE]
    guide_response = client.get(guide["path"])
    assert guide_response.status_code == 200
    html = guide_response.get_data(as_text=True)
    for demo, layer, city, district in zip(
        guide["map_demos"], ("land_use_2030", "land_use_2030", "partition"),
        ("THỦ DẦU MỘT", "BẾN CÁT", "BẾN CÁT"), ("718", "721", "721"), strict=True,
    ):
        link = urlsplit(demo["href"])
        query = parse_qs(link.query)
        assert query["city"] == [city]
        assert query["planning"] == [layer]
        assert parse_qs(link.fragment)["district"] == [district]
        assert f'data-track-cta="{demo["id"]}"' in html
    for path in ("/quy-hoach-binh-duong", "/sitemap.xml"):
        assert guide["path"] in client.get(path).get_data(as_text=True)
    assert GUIDE not in {slug for _, slug in article_candidates()}


def test_planning_lookup_tracking_discards_location_and_identifiers():
    assert "planning_lookup" in radar_app.ALLOWED_TRACK_ACTIONS
    assert radar_app._safe_planning_lookup_context({
        "method": "coordinates", "outcome": "located", "coordinates": [11, 106], "parcel": "17",
    }) == {"method": "coordinates", "outcome": "located"}
    assert radar_app._safe_planning_lookup_context({"method": "11.123", "outcome": "17"}) == {}


def test_new_planning_guides_have_canonical_and_links_from_relevant_pages():
    client = radar_app.app.test_client()
    sitemap = client.get("/sitemap.xml").get_data(as_text=True)
    for slug, referring_path, expected_cta in (
        ("my-phuoc-thuoc-phuong-nao-sau-sap-nhap", "/ban-do-ben-cat", "#layer-legacy/area-my-phuoc"),
        ("ranh-thua-chong-lop-quy-hoach-can-kiem-tra-gi", "/quy-hoach-binh-duong/quy-hoach-phan-khu", "planning=partition"),
    ):
        path = f"/tin-tuc/{slug}"
        response = client.get(path)
        html = response.get_data(as_text=True)
        assert response.status_code == 200
        assert f'rel="canonical" href="https://radarbds.vn{path}"' in html
        assert expected_cta in html
        assert f'href="{path}"' in client.get(referring_path).get_data(as_text=True)
        assert f"https://radarbds.vn{path}</loc>" in sitemap
