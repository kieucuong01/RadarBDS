import json
import importlib
from pathlib import Path


def test_site_seo_env_text_falls_back_when_corrupted(monkeypatch):
    from config import settings

    monkeypatch.setenv("SITE_TITLE", "Radar BDS - S?n deal nh? ??t B?nh D??ng b?ng d? li?u")
    monkeypatch.setenv(
        "SITE_DESCRIPTION",
        "Radar BDS thu th?p, chu?n h?a v? ph?n t?ch tin rao nh? ??t B?nh D??ng.",
    )
    monkeypatch.setenv(
        "SITE_KEYWORDS",
        "radar bds, s?n deal b?t d?ng s?n, nh? d?t B?nh D??ng",
    )

    reloaded = importlib.reload(settings)

    assert reloaded.SITE_TITLE == "Radar BDS - Săn deal nhà đất Bình Dương bằng dữ liệu"
    assert "?" not in reloaded.SITE_DESCRIPTION
    assert "Bình Dương" in reloaded.SITE_KEYWORDS


def test_public_seo_defaults_point_to_radarbds_domain():
    import app as radar_app

    meta = radar_app._site_meta("/")

    assert meta["canonical_url"] == "https://radarbds.vn/"
    assert meta["og_url"] == "https://radarbds.vn/"
    assert meta["og_image"].startswith("https://radarbds.vn/")
    assert "localhost" not in meta["canonical_url"]
    assert "127.0.0.1" not in meta["canonical_url"]


def test_robots_and_sitemap_use_public_domain():
    import app as radar_app

    with radar_app.app.test_request_context("/robots.txt"):
        robots = radar_app.robots_txt().get_data(as_text=True)
    with radar_app.app.test_request_context("/sitemap.xml"):
        sitemap = radar_app.sitemap_xml().get_data(as_text=True)

    assert "Sitemap: https://radarbds.vn/sitemap.xml" in robots
    assert "<loc>https://radarbds.vn/</loc>" in sitemap
    assert "<loc>https://radarbds.vn/binh-duong</loc>" in sitemap
    assert "<loc>https://radarbds.vn/san-deal-bds</loc>" in sitemap
    assert "localhost" not in robots + sitemap
    assert "127.0.0.1" not in robots + sitemap


def test_foundational_seo_pages_render_canonical_content():
    import app as radar_app

    client = radar_app.app.test_client()
    expected = {
        "/binh-duong": "Săn deal nhà đất Bình Dương bằng dữ liệu",
        "/san-deal-bds": "Cách Radar BDS lọc tin rẻ thật",
    }

    for path, heading in expected.items():
        response = client.get(path)
        html = response.get_data(as_text=True)

        assert response.status_code == 200
        assert f'<link rel="canonical" href="https://radarbds.vn{path}">' in html
        assert heading in html
        assert "https://radarbds.vn/static/images/logo.png" in html
        assert "localhost" not in html
        assert "127.0.0.1" not in html


def test_binh_duong_location_landing_pages_render_and_are_indexed():
    import app as radar_app

    client = radar_app.app.test_client()
    expected = {
        "/binh-duong/thu-dau-mot": "Thủ Dầu Một",
        "/binh-duong/ben-cat": "Bến Cát",
        "/binh-duong/phuong-phu-my": "Phú Mỹ",
        "/binh-duong/duong-dx013": "DX013",
    }

    with radar_app.app.test_request_context("/sitemap.xml"):
        sitemap = radar_app.sitemap_xml().get_data(as_text=True)

    for path, phrase in expected.items():
        response = client.get(path)
        html = response.get_data(as_text=True)

        assert response.status_code == 200
        assert f'<link rel="canonical" href="https://radarbds.vn{path}">' in html
        assert f"<loc>https://radarbds.vn{path}</loc>" in sitemap
        assert phrase in html
        assert "Khu vực liên quan" in html
        assert "localhost" not in html
        assert "127.0.0.1" not in html


def test_unknown_binh_duong_location_seo_page_404s():
    import app as radar_app

    response = radar_app.app.test_client().get("/binh-duong/khu-vuc-khong-co")

    assert response.status_code == 404


def test_manifest_uses_radarbds_standalone_start_url():
    manifest = json.loads(Path("static/manifest.webmanifest").read_text(encoding="utf-8"))

    assert manifest["name"] == "Radar BDS"
    assert manifest["start_url"] == "https://radarbds.vn/"
    assert manifest["scope"] == "https://radarbds.vn/"
    assert manifest["display"] == "standalone"
    assert manifest["icons"][0]["src"].startswith("https://radarbds.vn/")
