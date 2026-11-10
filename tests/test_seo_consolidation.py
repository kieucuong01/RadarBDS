import json
from html import escape

import pytest

from config.seo_articles import ARTICLE_REDIRECTS, SEO_ARTICLES
from config.seo_guides import PRODUCT_GUIDES
from config.seo_pages import SEO_PAGES


@pytest.mark.parametrize("prefix", ["/tin-tuc/", "/kien-thuc/", "/bao-cao/"])
def test_retired_articles_redirect_directly_from_every_alias(prefix):
    import app as radar_app

    client = radar_app.app.test_client()
    for slug, target in ARTICLE_REDIRECTS.items():
        response = client.get(prefix + slug + "?utm_source=seo&ref=old")
        assert response.status_code == 301
        assert response.headers["Location"] == target + "?utm_source=seo&ref=old"
        assert client.get(target).status_code == 200
        assert slug not in SEO_ARTICLES
    assert client.get(prefix + "unknown-retired-article").status_code == 404


def test_canonical_registry_and_links_do_not_advertise_retired_articles():
    import app as radar_app

    with radar_app.app.test_request_context("/sitemap.xml"):
        sitemap = radar_app.sitemap_xml().get_data(as_text=True)
    for slug, target in ARTICLE_REDIRECTS.items():
        assert f"<loc>https://radarbds.vn/tin-tuc/{slug}</loc>" not in sitemap
        assert f"<loc>https://radarbds.vn{target}</loc>" in sitemap
        for page in [*SEO_ARTICLES.values(), *SEO_PAGES.values()]:
            for link in page.get("local_links", []):
                assert link.get("href", "").split("?")[0] != "/tin-tuc/" + slug


def test_merge_preserves_newer_snapshot_and_corrects_invalid_date():
    page = SEO_ARTICLES["gia-dat-dinh-hoa-hien-bao-nhieu"]
    assert page["article"]["modified_at"] == "2026-10-15"
    assert "15,8" in json.dumps(page, ensure_ascii=False)
    assert "05/13/2026" not in json.dumps(SEO_ARTICLES)


def test_guides_render_index_and_link_to_working_tools():
    import app as radar_app

    client = radar_app.app.test_client()
    for page in PRODUCT_GUIDES.values():
        response = client.get(page["path"])
        html = response.get_data(as_text=True)
        assert response.status_code == 200
        assert f'<h1>{page["hero_title"]}</h1>' in html
        assert f'https://radarbds.vn{page["path"]}' in html
        assert f'href="{escape(page["primary_href"])}"' in html
        assert "Số liệu theo kỳ" not in html
        if page.get("hide_lead_capture"):
            assert '<section class="seo-lead-capture"' not in html
    old = client.get("/tin-tuc/gia-dat-phu-tan-hien-bao-nhieu").get_data(as_text=True)
    assert "Số liệu theo kỳ, không phải bảng giá trực tiếp" in old
    assert 'href="/gia-dat/thu-dau-mot"' in old
    portal = client.get("/tin-tuc").get_data(as_text=True)
    assert all(page["path"] in portal for page in PRODUCT_GUIDES.values())
