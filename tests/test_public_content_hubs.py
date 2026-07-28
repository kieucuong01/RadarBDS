import json
import re
from pathlib import Path

import pytest

from config.seo_articles import KNOWLEDGE_HUB, SEO_ARTICLES


NEWS_CATEGORY_LABELS = {
    "du-lieu-gia-dat": "Giá đất theo phường",
    "so-sanh-khu-vuc": "So sánh khu vực",
    "huong-dan-doc-du-lieu": "Hướng dẫn đọc dữ liệu",
    "kiem-tra-tin-rao": "Kiểm tra tin rao",
}


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

    assert "Đang phủ 13 phường Thủ Dầu Một" in report_html
    assert "Tin tức BĐS Bình Dương từ dữ liệu Radar BDS" in news_html


def test_seo_lead_form_fails_closed_to_post_when_javascript_is_unavailable():
    import app as radar_app

    html = radar_app.app.test_client().get("/bao-cao").get_data(as_text=True)

    assert re.search(
        r'<form[^>]+class="seo-lead-capture-form"[^>]+method="post"[^>]+action="/api/leads"',
        html,
    )
    assert 'name="return_path" value="/bao-cao"' in html
    assert 'name="source_context" value="seo_report_hub_lead"' in html


def test_form_encoded_lead_redirect_never_places_phone_in_location(monkeypatch):
    import app as radar_app

    captured = {}

    def fake_create(payload, **_kwargs):
        captured.update(payload)
        return {"ok": True, "lead_id": 123}, 200

    monkeypatch.setattr(radar_app.admin_leads, "create_lead", fake_create)
    response = radar_app.app.test_client().post(
        "/api/leads",
        data={
            "zalo_phone": "0901 222 333",
            "source_context": "seo_report_hub_lead",
            "return_path": "/bao-cao",
        },
        environ_base={"REMOTE_ADDR": "10.91.1.1"},
    )

    assert response.status_code == 303
    assert response.headers["Location"] == "/bao-cao?lead=success"
    assert "0901" not in response.headers["Location"]
    assert "return_path" not in captured
    assert captured["zalo_phone"] == "0901 222 333"


@pytest.mark.parametrize(
    "return_path",
    ("https://evil.example/steal", "/\\evil.example/steal"),
)
def test_form_encoded_lead_rejects_open_redirect_target(monkeypatch, return_path):
    import app as radar_app

    monkeypatch.setattr(
        radar_app.admin_leads,
        "create_lead",
        lambda payload, **_kwargs: ({"ok": True, "lead_id": 456}, 200),
    )
    response = radar_app.app.test_client().post(
        "/api/leads",
        data={
            "zalo_phone": "0901 222 334",
            "return_path": return_path,
        },
        environ_base={"REMOTE_ADDR": "10.91.1.2"},
    )

    assert response.status_code == 303
    assert response.headers["Location"] == "/bao-cao?lead=success"


def test_json_lead_client_keeps_json_response_contract(monkeypatch):
    import app as radar_app

    monkeypatch.setattr(
        radar_app.admin_leads,
        "create_lead",
        lambda payload, **_kwargs: ({"ok": True, "lead_id": 789}, 200),
    )
    response = radar_app.app.test_client().post(
        "/api/leads",
        json={"zalo_phone": "0901 222 335"},
        environ_base={"REMOTE_ADDR": "10.91.1.3"},
    )

    assert response.status_code == 200
    assert response.get_json() == {"ok": True, "lead_id": 789}


def test_news_hub_is_dashboard_first_and_has_progressive_discovery():
    import app as radar_app

    html = radar_app.app.test_client().get("/tin-tuc").get_data(as_text=True)

    assert 'data-track-cta="news_hub_dashboard"' in html
    assert 'href="/?tab=signals"' in html
    assert 'id="newsHubSearch"' in html
    assert 'data-news-category="all"' in html
    assert 'data-news-results-status' in html
    assert 'data-news-load-more' in html
    assert 'data-news-load-more-row hidden' in html
    assert 'data-news-empty-state' in html
    assert 'js/seo_news_hub.js' in html
    assert "SEO/AIO" not in html
    assert "Số bài phân tích" in html
    css = Path("static/css/seo.css").read_text(encoding="utf-8")
    assert "Shared SEO dropdowns are click-controlled" in css


def test_news_hub_archive_cards_render_left_thumbnails():
    import app as radar_app

    html = radar_app.app.test_client().get("/tin-tuc").get_data(as_text=True)
    archive_cards = re.findall(
        r'<article\s+class="hub-card news-article-card"[\s\S]*?</article>',
        html,
    )

    assert archive_cards
    for card in archive_cards:
        assert 'class="news-card-thumb"' in card
        assert 'class="news-card-body"' in card
        assert card.index('class="news-card-thumb"') < card.index('class="news-card-body"')
        assert 'data-news-thumb-category="' in card
        assert 'aria-label="Đọc ' in card
        assert 'data-track-cta="news_hub_article_thumb"' in card


def test_news_hub_featured_is_not_repeated_in_archive():
    import app as radar_app

    html = radar_app.app.test_client().get("/tin-tuc").get_data(as_text=True)
    featured_path = SEO_ARTICLES[KNOWLEDGE_HUB["featured_slug"]]["path"]

    assert html.count(f'data-news-featured="{featured_path}"') == 1
    assert f'data-news-card-path="{featured_path}"' not in html


def test_news_hub_archive_is_recent_first_and_dates_are_localized():
    import app as radar_app

    html = radar_app.app.test_client().get("/tin-tuc").get_data(as_text=True)
    modified_dates = re.findall(r'data-modified-at="(\d{4}-\d{2}-\d{2})"', html)

    assert modified_dates
    assert modified_dates == sorted(modified_dates, reverse=True)
    assert re.search(r'<time datetime="\d{4}-\d{2}-\d{2}">Cập nhật \d{2}/\d{2}/\d{4}</time>', html)


def test_news_taxonomy_resolves_only_to_canonical_keys_and_labels():
    import app as radar_app

    news_items = [
        (slug, item)
        for slug, item in SEO_ARTICLES.items()
        if str(item.get("path") or "").startswith("/tin-tuc/")
    ]

    for slug, item in news_items:
        category = radar_app._news_category_for_article(slug, item)
        assert category["key"] in NEWS_CATEGORY_LABELS
        assert category["label"] == NEWS_CATEGORY_LABELS[category["key"]]

    with pytest.raises(ValueError, match="Unknown news category"):
        radar_app._news_category_for_article(
            "invalid-category",
            {"category": {"key": "not-a-real-category", "label": "Sai nhóm"}},
        )


def test_news_hub_item_list_contains_each_article_once():
    import app as radar_app

    html = radar_app.app.test_client().get("/tin-tuc").get_data(as_text=True)
    blocks = re.findall(r'<script type="application/ld\+json">\s*(.*?)\s*</script>', html, re.S)
    payload = json.loads(blocks[-1])
    item_list = next(item for item in payload["@graph"] if item["@type"] == "ItemList")
    urls = [item["url"] for item in item_list["itemListElement"]]
    expected_count = sum(
        str(item.get("path") or "").startswith("/tin-tuc/")
        for item in SEO_ARTICLES.values()
    )

    assert len(urls) == expected_count
    assert len(urls) == len(set(urls))


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


def test_report_hub_scope_and_empty_city_state_match_published_coverage():
    import app as radar_app

    html = radar_app.app.test_client().get("/bao-cao").get_data(as_text=True)

    assert "<h1>Báo cáo thị trường BĐS Thủ Dầu Một</h1>" in html
    assert 'data-filter-city="tdm" aria-pressed="false"' in html
    assert re.search(
        r'data-filter-city="ben-cat"[^>]+aria-disabled="true"[^>]+disabled',
        html,
    )
    assert "Bến Cát · Sắp có" in html


def test_report_hub_filter_state_is_shareable_and_restorable():
    import app as radar_app

    html = radar_app.app.test_client().get("/bao-cao").get_data(as_text=True)
    js = Path("static/js/seo_report_hub.js").read_text(encoding="utf-8")

    assert 'id="reportPeriodSelect"' in html
    assert 'src="/static/js/seo_report_hub.js"' in html
    assert "new URLSearchParams(window.location.search)" in js
    assert "window.history.replaceState" in js
    assert "popstate" in js
    assert "report_filter_used" in js
    assert "search_query" not in js
    assert "query: query" not in js


def test_report_hub_latest_is_not_repeated_and_archive_cards_have_one_link():
    import app as radar_app

    html = radar_app.app.test_client().get("/bao-cao").get_data(as_text=True)
    featured = re.search(r'data-featured-report="([^"]+)"', html)
    archive_paths = re.findall(r'data-report-path="([^"]+)"', html)
    archive_cards = re.findall(
        r'<a class="hub-card report-archive-card"[\s\S]*?</a>',
        html,
    )

    assert featured
    assert featured.group(1) not in archive_paths
    assert archive_cards
    assert len(archive_cards) == len(archive_paths)
    assert all(card.count("href=") == 1 for card in archive_cards)
    assert '<div class="report-featured-thumb" aria-hidden="true">' in html
    assert '<a class="report-featured-thumb"' not in html


def test_report_detail_has_early_live_dashboard_cta_with_safe_tracking():
    import app as radar_app

    html = radar_app.app.test_client().get(
        "/bao-cao/phu-tan-thang-06-2026"
    ).get_data(as_text=True)

    assert 'class="report-live-cta"' in html
    assert html.index('class="report-live-cta"') < html.index(
        'class="seo-report-block"'
    )
    assert "Xem deal đang hoạt động tại Phú Tân" in html
    assert "tab=signals" in html
    assert "ward=Ph%C3%BA+T%C3%A2n" in html
    assert "date_range=all" in html
    assert "mos_min=10" in html
    assert 'data-report-action="dashboard"' in html


def test_report_specific_analytics_actions_are_allowlisted():
    import app as radar_app

    assert {
        "report_filter_used",
        "report_open",
        "report_dashboard_click",
        "report_listing_click",
    } <= radar_app.ALLOWED_TRACK_ACTIONS


def test_report_charts_have_accessible_text_fallbacks():
    import app as radar_app

    html = radar_app.app.test_client().get(
        "/bao-cao/phu-tan-thang-06-2026"
    ).get_data(as_text=True)
    canvases = re.findall(r"<canvas[^>]+>", html)

    assert canvases
    assert all('role="img"' in canvas for canvas in canvases)
    assert all('aria-label="' in canvas for canvas in canvases)
    assert html.count('class="chart-data-summary sr-only"') == len(canvases)


def test_report_featured_images_are_lazy_sized_and_listing_tracked():
    import app as radar_app

    html = radar_app.app.test_client().get(
        "/bao-cao/phu-tan-thang-06-2026"
    ).get_data(as_text=True)
    cards = re.findall(
        r'<a class="featured-listing-card report-signal-card[^"]*"[\s\S]*?</a>',
        html,
    )

    assert cards
    for card in cards:
        assert 'loading="lazy"' in card
        assert 'width="640"' in card
        assert 'height="360"' in card
        assert 'data-report-action="listing"' in card
        assert 'data-listing-id="' in card


def test_report_dates_and_mobile_controls_are_explicit():
    import app as radar_app

    html = radar_app.app.test_client().get(
        "/bao-cao/phu-tan-thang-06-2026"
    ).get_data(as_text=True)
    css = Path("static/css/seo.css").read_text(encoding="utf-8")

    assert 'class="report-data-as-of"' in html
    assert re.search(r'<time datetime="\d{4}-\d{2}-\d{2}">', html)
    assert ".report-period-select-wrap" in css
    assert "font-size: 16px" in css
    assert ".report-live-cta" in css
    assert ".report-detail .report-signal-card" in css


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
    assert re.search(
        r"<loc>https://radarbds\.vn/tin-tuc</loc>\s*<lastmod>\d{4}-\d{2}-\d{2}</lastmod>",
        sitemap,
    )
    client = radar_app.app.test_client()
    for article in SEO_ARTICLES.values():
        html = client.get(article["path"]).get_data(as_text=True)
        assert f'<link rel="canonical" href="https://radarbds.vn{article["path"]}">' in html
        assert f"<loc>https://radarbds.vn{article['path']}</loc>" in sitemap
        modified_at = (article.get("article") or {}).get("modified_at")
        if modified_at:
            assert (
                f"<loc>https://radarbds.vn{article['path']}</loc>\n"
                f"    <lastmod>{modified_at}</lastmod>"
            ) in sitemap


def test_llms_txt_includes_news_hub():
    import app as radar_app

    response = radar_app.app.test_client().get("/llms.txt")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Tin tức dữ liệu: https://radarbds.vn/tin-tuc" in body


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

