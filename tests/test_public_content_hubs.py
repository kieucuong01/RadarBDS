from pathlib import Path

import pytest

from config.seo_articles import KNOWLEDGE_HUB, SEO_ARTICLES


ARTICLE_EXPECTATIONS = {
    slug: article["article"]["sections"][0]["heading"]
    for slug, article in SEO_ARTICLES.items()
    if str(article.get("path") or "").startswith("/kien-thuc/")
}


def test_content_hubs_include_reports_news_and_legacy_knowledge():
    import app as radar_app

    client = radar_app.app.test_client()
    report = client.get("/bao-cao")
    knowledge = client.get("/kien-thuc")
    news = client.get("/tin-tuc")

    assert report.status_code == 200
    assert knowledge.status_code == 301
    assert knowledge.headers["Location"] == "/tin-tuc"
    assert news.status_code == 200

    report_html = report.get_data(as_text=True)
    news_html = news.get_data(as_text=True)
    assert '<link rel="canonical" href="https://radarbds.vn/bao-cao">' in report_html
    assert '<link rel="canonical" href="https://radarbds.vn/tin-tuc">' in news_html
    assert 'class="seo-page report-hub"' in report_html
    assert 'class="seo-page knowledge-hub"' in news_html
    for html in (report_html, news_html):
        assert "hub-hero" in html
        assert "hub-hero-grid" in html
        assert "hub-insight-panel" in html
        assert 'class="hub-card-number"' in html or 'class="hub-featured-index"' in html
        assert '"@type": "CollectionPage"' in html
        assert '"@type": "ItemList"' in html
        assert '"@type": "BreadcrumbList"' in html
    assert 'class="seo-lead-capture"' in report_html
    assert 'class="seo-lead-capture"' in news_html
    assert 'data-source-context="seo_report_hub_lead"' in report_html
    assert 'data-source-context="seo_news_hub_lead"' in news_html
    assert "'/api/leads'" in report_html
    assert "'/api/leads'" in news_html

    assert "Hiện ưu tiên Thủ Dầu Một" in report_html
    assert "Tin tức BĐS Bình Dương từ dữ liệu Radar BDS" in news_html


@pytest.mark.parametrize(
    ("path", "active"),
    [
        ("/binh-duong", "binh-duong"),
        ("/dinh-gia-bds", "dinh-gia"),
        ("/bang-gia-dat-tphcm", "bang-gia-dat"),
        ("/quy-hoach-binh-duong", "quy-hoach"),
        ("/bao-cao", "bao-cao"),
        ("/tin-tuc", "tin-tuc"),
        ("/san-deal-bds", "san-deal"),
    ],
)
def test_shared_navigation_and_active_state(path, active):
    import app as radar_app

    html = radar_app.app.test_client().get(path).get_data(as_text=True)
    for item in ("binh-duong", "quy-hoach", "dinh-gia", "bang-gia-dat", "bao-cao", "tin-tuc", "san-deal"):
        assert f'data-nav="{item}"' in html
    assert f'data-nav="{active}" aria-current="page"' in html
    assert ">Bán đất</a>" not in html


def test_report_detail_is_data_first_tdm_report():
    import app as radar_app

    path = "/bao-cao/bds-binh-duong-thang-06-2026"
    html = radar_app.app.test_client().get(path).get_data(as_text=True)

    assert "Báo cáo thị trường BĐS Thủ Dầu Một tháng 06/2026" in html
    assert 'class="seo-report-block"' in html
    assert 'class="hero-map-stage"' not in html
    assert '"@type": "Report"' in html
    assert "Hơn 1.000 nhà đầu tư tin dùng Radar BDS" not in html
    assert "Dữ liệu tổng hợp từ tin rao công khai" in html
    assert "Phạm vi dữ liệu" in html
    assert "Kỳ dữ liệu" in html
    assert 'data-nav="bao-cao" aria-current="page"' in html
    assert "Trang chủ" in html
    assert "Báo cáo tháng 06/2026" in html


def test_all_articles_have_distinct_editorial_structure_and_user_language():
    import app as radar_app

    client = radar_app.app.test_client()
    for slug, required_heading in ARTICLE_EXPECTATIONS.items():
        article = SEO_ARTICLES[slug]
        html = client.get(article["path"]).get_data(as_text=True)

        assert len(article["article"]["intro"]) >= 2
        assert len(article["article"]["sections"]) >= 4
        assert required_heading in html
        assert 'class="article-toc"' in html
        assert 'class="hero-map-stage"' not in html
        assert '"@type": "BlogPosting"' in html
        assert html.count("<h1") == 1
        for section in article["article"]["sections"]:
            assert section["id"]
            assert section["heading"] in html
            assert len(section["paragraphs"]) >= 2

        for internal_term in ("Internal links", "SEO địa phương", "VIP lead", "Telegram", "watchlist funnel"):
            assert internal_term not in html


def test_hubs_are_in_sitemap_and_detail_canonicals_stay_unchanged():
    import app as radar_app

    with radar_app.app.test_request_context("/sitemap.xml"):
        sitemap = radar_app.sitemap_xml().get_data(as_text=True)

    assert "<loc>https://radarbds.vn/bao-cao</loc>" in sitemap
    assert "<loc>https://radarbds.vn/kien-thuc</loc>" not in sitemap
    assert "<loc>https://radarbds.vn/tin-tuc</loc>" in sitemap
    client = radar_app.app.test_client()
    for article in SEO_ARTICLES.values():
        html = client.get(article["path"]).get_data(as_text=True)
        assert f'<link rel="canonical" href="https://radarbds.vn{article["path"]}">' in html
        assert f"<loc>https://radarbds.vn{article['path']}</loc>" in sitemap


def test_accessibility_and_mobile_table_guards_are_present():
    css = Path("static/css/seo.css").read_text(encoding="utf-8")

    assert ":focus-visible" in css
    assert "min-height: 44px" in css
    assert "width: calc(100vw - 32px)" in css
    assert ".table-scroll-hint" in css

def test_all_public_content_json_ld_is_valid():
    import json
    import re
    import app as radar_app

    paths = ["/bao-cao", "/tin-tuc", "/bao-cao/bds-binh-duong-thang-06-2026"]
    paths.extend(article["path"] for article in SEO_ARTICLES.values())
    client = radar_app.app.test_client()

    for path in paths:
        html = client.get(path).get_data(as_text=True)
        blocks = re.findall(r'<script type="application/ld\+json">\s*(.*?)\s*</script>', html, re.S)
        assert blocks, path
        for block in blocks:
            payload = json.loads(block)
            assert payload["@context"] == "https://schema.org"

