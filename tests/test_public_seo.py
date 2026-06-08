import json
import importlib
from pathlib import Path

from PIL import Image


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
    dashboard_meta = radar_app._site_meta("/dashboard")

    assert meta["canonical_url"] == "https://radarbds.vn/"
    assert meta["og_url"] == "https://radarbds.vn/"
    assert dashboard_meta["canonical_url"] == "https://radarbds.vn/dashboard"
    assert dashboard_meta["og_url"] == "https://radarbds.vn/dashboard"
    assert meta["og_image"].startswith("https://radarbds.vn/")
    assert meta["og_image"].endswith("/static/images/seo/radarbds-og.png")
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
    assert "<loc>https://radarbds.vn/binh-duong</loc>" not in sitemap
    assert "<loc>https://radarbds.vn/san-deal-bds</loc>" in sitemap
    assert "localhost" not in robots + sitemap
    assert "127.0.0.1" not in robots + sitemap


def test_homepage_is_binh_duong_landing_and_dashboard_has_own_url():
    import app as radar_app

    client = radar_app.app.test_client()

    home = client.get("/")
    dashboard = client.get("/dashboard")
    legacy_binh_duong = client.get("/binh-duong")

    home_html = home.get_data(as_text=True)
    dashboard_html = dashboard.get_data(as_text=True)

    assert home.status_code == 200
    assert '<link rel="canonical" href="https://radarbds.vn/">' in home_html
    assert 'class="seo-page seo-page-market"' in home_html
    assert "Săn deal nhà đất Bình Dương bằng dữ liệu" in home_html
    assert 'href="/dashboard"' in home_html
    assert '<a href="/dashboard">Dashboard</a>' in home_html

    assert dashboard.status_code == 200
    assert '<link rel="canonical" href="https://radarbds.vn/dashboard">' in dashboard_html
    assert "window.INITIAL_WARDS_BY_CITY" in dashboard_html

    assert legacy_binh_duong.status_code == 301
    assert legacy_binh_duong.headers["Location"] == "/"


def test_foundational_seo_pages_render_canonical_content():
    import app as radar_app

    client = radar_app.app.test_client()
    expected = {
        "/": "Săn deal nhà đất Bình Dương bằng dữ liệu",
        "/san-deal-bds": "Cách Radar BDS lọc tin rẻ thật",
    }

    for path, heading in expected.items():
        response = client.get(path)
        html = response.get_data(as_text=True)

        assert response.status_code == 200
        assert f'<link rel="canonical" href="https://radarbds.vn{path}">' in html
        assert heading in html
        assert "https://radarbds.vn/static/images/seo/radarbds-og.png" in html
        assert "localhost" not in html
        assert "127.0.0.1" not in html


def test_binh_duong_location_landing_pages_render_and_are_indexed():
    import app as radar_app

    client = radar_app.app.test_client()
    expected = {
        "/binh-duong/thu-dau-mot": "Thủ Dầu Một",
        "/binh-duong/ben-cat": "Bến Cát",
        "/binh-duong/phuong-phu-my": "Phú Mỹ",
        "/binh-duong/phuong-tuong-binh-hiep": "Tương Bình Hiệp",
        "/binh-duong/phuong-tan-dinh": "Tân Định",
        "/binh-duong/phuong-chanh-phu-hoa": "Chánh Phú Hòa",
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

    assert "/binh-duong/duong-" not in sitemap


def test_street_name_seo_pages_are_not_indexed():
    import app as radar_app

    client = radar_app.app.test_client()
    street_paths = [
        "/binh-duong/duong-dx013",
        "/binh-duong/duong-dx20",
        "/binh-duong/duong-dl12",
    ]

    with radar_app.app.test_request_context("/sitemap.xml"):
        sitemap = radar_app.sitemap_xml().get_data(as_text=True)

    for path in street_paths:
        response = client.get(path)

        assert response.status_code == 404
        assert f"<loc>https://radarbds.vn{path}</loc>" not in sitemap


def test_unknown_binh_duong_location_seo_page_404s():
    import app as radar_app

    response = radar_app.app.test_client().get("/binh-duong/khu-vuc-khong-co")

    assert response.status_code == 404


def test_manifest_uses_radarbds_standalone_start_url():
    manifest = json.loads(Path("static/manifest.webmanifest").read_text(encoding="utf-8"))
    icons = {icon["src"]: icon for icon in manifest["icons"]}

    assert manifest["name"] == "Radar BDS"
    assert manifest["start_url"] == "https://radarbds.vn/dashboard"
    assert manifest["scope"] == "https://radarbds.vn/"
    assert manifest["display"] == "standalone"
    assert "https://radarbds.vn/static/images/app-icon-192.png" in icons
    assert "https://radarbds.vn/static/images/app-icon-512.png" in icons
    assert "https://radarbds.vn/static/images/app-icon-maskable-512.png" in icons
    assert icons["https://radarbds.vn/static/images/app-icon-maskable-512.png"]["purpose"] == "maskable"
    assert icons["https://radarbds.vn/static/images/app-icon-192.png"]["sizes"] == "192x192"
    assert icons["https://radarbds.vn/static/images/app-icon-512.png"]["sizes"] == "512x512"


def test_seo_and_home_screen_icon_assets_are_wired_and_sized():
    dashboard_html = Path("templates/index.html").read_text(encoding="utf-8")
    seo_html = Path("templates/seo_landing.html").read_text(encoding="utf-8")

    for html in (dashboard_html, seo_html):
        assert "images/favicon-32.png" in html
        assert "images/favicon-16.png" in html
        assert "images/apple-touch-icon.png" in html
        assert "manifest.webmanifest') }}?v=app-icon-20260608" in html

    expected_sizes = {
        "static/images/logo.png": (1024, 1024),
        "static/images/app-icon-192.png": (192, 192),
        "static/images/app-icon-512.png": (512, 512),
        "static/images/app-icon-maskable-512.png": (512, 512),
        "static/images/apple-touch-icon.png": (180, 180),
        "static/images/favicon-32.png": (32, 32),
        "static/images/favicon-16.png": (16, 16),
        "static/images/seo/radarbds-og.png": (1200, 630),
    }
    for path, size in expected_sizes.items():
        assert Path(path).exists(), path
        with Image.open(path) as img:
            assert img.size == size
