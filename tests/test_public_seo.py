import json
from pathlib import Path


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
    assert "localhost" not in robots + sitemap
    assert "127.0.0.1" not in robots + sitemap


def test_manifest_uses_radarbds_standalone_start_url():
    manifest = json.loads(Path("static/manifest.webmanifest").read_text(encoding="utf-8"))

    assert manifest["name"] == "Radar BDS"
    assert manifest["start_url"] == "https://radarbds.vn/"
    assert manifest["scope"] == "https://radarbds.vn/"
    assert manifest["display"] == "standalone"
    assert manifest["icons"][0]["src"].startswith("https://radarbds.vn/")
