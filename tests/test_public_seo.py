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
    binh_duong_meta = radar_app._site_meta("/binh-duong")

    assert meta["canonical_url"] == "https://radarbds.vn/"
    assert meta["og_url"] == "https://radarbds.vn/"
    assert binh_duong_meta["canonical_url"] == "https://radarbds.vn/binh-duong"
    assert binh_duong_meta["og_url"] == "https://radarbds.vn/binh-duong"
    assert meta["og_image"].startswith("https://radarbds.vn/")
    assert meta["og_image"].endswith("/static/images/seo/radarbds-og.png")
    assert "localhost" not in meta["canonical_url"]
    assert "127.0.0.1" not in meta["canonical_url"]


def test_robots_and_sitemap_use_public_domain():
    import app as radar_app
    from config.seo_articles import SEO_ARTICLES

    with radar_app.app.test_request_context("/robots.txt"):
        robots = radar_app.robots_txt().get_data(as_text=True)
    with radar_app.app.test_request_context("/sitemap.xml"):
        sitemap = radar_app.sitemap_xml().get_data(as_text=True)

    assert "Sitemap: https://radarbds.vn/sitemap.xml" in robots
    assert "User-agent: OAI-SearchBot\nAllow: /" in robots
    assert "User-agent: *\nAllow: /" in robots
    assert "<loc>https://radarbds.vn/</loc>" in sitemap
    assert "<loc>https://radarbds.vn/binh-duong</loc>" in sitemap
    assert "<loc>https://radarbds.vn/san-deal-bds</loc>" in sitemap
    assert "<loc>https://radarbds.vn/bang-gia-dat-tphcm</loc>" in sitemap
    assert "<loc>https://radarbds.vn/bao-cao</loc>" in sitemap
    assert "<loc>https://radarbds.vn/kien-thuc</loc>" not in sitemap
    for article in SEO_ARTICLES.values():
        assert f"<loc>https://radarbds.vn{article['path']}</loc>" in sitemap
    assert "localhost" not in robots + sitemap
    assert "127.0.0.1" not in robots + sitemap


def test_homepage_is_dashboard_and_binh_duong_is_seo_landing():
    import app as radar_app

    client = radar_app.app.test_client()

    home = client.get("/")
    dashboard = client.get("/dashboard")
    binh_duong = client.get("/binh-duong")

    home_html = home.get_data(as_text=True)
    binh_duong_html = binh_duong.get_data(as_text=True)

    assert home.status_code == 200
    assert '<link rel="canonical" href="https://radarbds.vn/">' in home_html
    assert "window.INITIAL_WARDS_BY_CITY" in home_html
    assert 'class="seo-page seo-page-market"' not in home_html
    assert "Phân tích" in home_html
    assert "Thị trường & Deal" not in home_html
    assert "Công cụ" in home_html
    assert 'href="/dinh-gia-bds"' in home_html
    assert 'href="/bang-gia-dat-tphcm"' in home_html
    assert 'href="/tin-tuc"' in home_html
    assert 'href="/bao-cao"' in home_html
    tools_block = home_html.split('aria-label="Công cụ Radar"', 1)[1].split("</details>", 1)[0]
    assert 'href="/binh-duong"' not in tools_block
    assert 'href="/san-deal-bds"' not in tools_block

    assert dashboard.status_code == 301
    assert dashboard.headers["Location"] == "/"

    assert binh_duong.status_code == 200
    assert '<link rel="canonical" href="https://radarbds.vn/binh-duong">' in binh_duong_html
    assert 'class="seo-page seo-page-market"' in binh_duong_html
    assert "Nhà đất Bình Dương: radar săn deal giá tốt theo dữ liệu thị trường" in binh_duong_html
    assert 'href="/dashboard"' not in binh_duong_html
    assert '<a href="/">Dashboard</a>' in binh_duong_html


def test_google_site_tags_are_env_driven(monkeypatch):
    import app as radar_app

    monkeypatch.setattr(radar_app, "GOOGLE_ANALYTICS_ID", "G-TEST1234")
    monkeypatch.setattr(radar_app, "GOOGLE_SEARCH_CONSOLE_VERIFICATION", "search-console-token")

    client = radar_app.app.test_client()
    home_html = client.get("/", base_url="https://radarbds.vn").get_data(as_text=True)
    binh_duong_html = client.get("/binh-duong", base_url="https://radarbds.vn").get_data(as_text=True)

    for html in (home_html, binh_duong_html):
        assert '<meta name="google-site-verification" content="search-console-token">' in html
        assert '<script async src="https://www.googletagmanager.com/gtag/js' not in html
        assert 'const analyticsId = "G-TEST1234";' in html
        assert 'script.src = "https://www.googletagmanager.com/gtag/js?id=" + encodeURIComponent(analyticsId);' in html
        assert 'window.gtag("config", analyticsId);' in html


def test_google_site_tags_reach_report_article_and_hubs(monkeypatch):
    import app as radar_app

    monkeypatch.setattr(radar_app, "GOOGLE_ANALYTICS_ID", "G-TEST1234")
    monkeypatch.setattr(radar_app, "GOOGLE_SEARCH_CONSOLE_VERIFICATION", "search-console-token")

    client = radar_app.app.test_client()
    paths = [
        "/bao-cao",
        "/bao-cao/bds-binh-duong-thang-06-2026",
        "/tin-tuc",
        "/tin-tuc/gia-rao-khac-gia-giao-dich-the-nao",
    ]

    for path in paths:
        response = client.get(path, base_url="https://radarbds.vn")
        html = response.get_data(as_text=True)
        assert response.status_code == 200
        assert '<meta name="google-site-verification" content="search-console-token">' in html
        assert 'const analyticsId = "G-TEST1234";' in html
        assert 'const analyticsId = "";' not in html
        assert 'script.src = "https://www.googletagmanager.com/gtag/js?id=" + encodeURIComponent(analyticsId);' in html
        assert "fetch('/api/track'" in html
        assert "social_utm_visit" in html
        assert "cta_clicked" in html


def test_rendered_landing_and_report_include_canonical_acquisition_tracking():
    import app as radar_app

    client = radar_app.app.test_client()
    landing_html = client.get(
        "/binh-duong/phuong-phu-my?utm_source=facebook&utm_medium=social"
    ).get_data(as_text=True)
    report_html = client.get(
        "/bao-cao/bds-binh-duong-thang-06-2026?utm_source=chatgpt"
    ).get_data(as_text=True)

    for html in (landing_html, report_html):
        assert "const acquisitionContext" in html
        assert "social_utm_visit" in html
        assert "ai_referral_visit" in html
        assert "cta_clicked" in html
        assert "referrer: document.referrer" not in html


def test_report_hub_prefers_master_report_and_news_hub_is_reader_facing():
    import app as radar_app

    client = radar_app.app.test_client()
    report_html = client.get("/bao-cao").get_data(as_text=True)
    news_html = client.get("/tin-tuc/du-lieu-radarbds").get_data(as_text=True)
    landing_html = client.get("/binh-duong").get_data(as_text=True)

    assert '<a class="seo-primary-cta" href="/bao-cao/bds-binh-duong-thang-07-2026"' in report_html
    assert "SEO / AIO / AI-SEO" not in news_html
    assert "Dữ liệu thị trường" in news_html
    assert "Tìm nhanh bài phân tích phù hợp" in news_html
    assert 'href="/bao-cao/bds-binh-duong-thang-06-2026"' in landing_html
    assert 'href="/tin-tuc"' in landing_html


def test_article_and_report_detail_pages_render_article_open_graph_metadata():
    import app as radar_app

    client = radar_app.app.test_client()
    article_html = client.get("/tin-tuc/gia-rao-khac-gia-giao-dich-the-nao").get_data(as_text=True)
    report_html = client.get("/bao-cao/bds-binh-duong-thang-06-2026").get_data(as_text=True)
    news_hub_html = client.get("/tin-tuc").get_data(as_text=True)
    report_hub_html = client.get("/bao-cao").get_data(as_text=True)

    assert '<meta property="og:type" content="article">' in article_html
    assert '<meta property="article:published_time" content="2026-07-25">' in article_html
    assert '<meta property="article:modified_time" content="2026-07-25">' in article_html
    assert '<meta property="og:type" content="article">' in report_html
    assert '<meta property="article:published_time" content="2026-07-09">' in report_html
    assert '<meta property="article:modified_time" content="2026-07-09">' in report_html
    assert '<meta property="og:type" content="website">' in news_hub_html
    assert '<meta property="article:published_time"' not in news_hub_html
    assert '<meta property="og:type" content="website">' in report_hub_html
    assert '<meta property="article:published_time"' not in report_hub_html


def test_google_site_tags_are_omitted_without_env(monkeypatch):
    import app as radar_app

    monkeypatch.setattr(radar_app, "GOOGLE_ANALYTICS_ID", "")
    monkeypatch.setattr(radar_app, "GOOGLE_SEARCH_CONSOLE_VERIFICATION", "")

    html = radar_app.app.test_client().get("/").get_data(as_text=True)

    assert "google-site-verification" not in html
    assert "googletagmanager.com/gtag/js" not in html


def test_live_domain_renders_radarbds_ga4_by_default(monkeypatch):
    import app as radar_app

    monkeypatch.setattr(radar_app, "GOOGLE_ANALYTICS_ID", "G-YRJZ26W8Y2")

    html = radar_app.app.test_client().get("/", base_url="https://radarbds.vn").get_data(as_text=True)

    assert '<script async src="https://www.googletagmanager.com/gtag/js' not in html
    assert 'const analyticsId = "G-YRJZ26W8Y2";' in html
    assert 'window.RadarLoadAnalytics = loadRadarAnalytics;' in html


def test_binh_duong_landing_has_dashboard_preview_metrics_and_dashboard_cta():
    import app as radar_app

    response = radar_app.app.test_client().get("/binh-duong")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'class="seo-dashboard-preview"' in html
    assert "/static/images/seo/dashboard-preview.png" in html
    assert 'href="/?tab=signals"' in html
    assert 'href="/dashboard"' not in html
    assert "Xem dashboard thật" in html
    assert "Tin rao được chuẩn hóa" in html
    assert "Tín hiệu đang theo dõi" in html
    assert "Cập nhật dữ liệu định kỳ" in html

    preview_path = Path("static/images/seo/dashboard-preview.png")
    assert preview_path.exists()
    with Image.open(preview_path) as img:
        assert img.size[0] >= 1000
        assert img.size[1] >= 620


def test_foundational_seo_pages_render_canonical_content():
    import app as radar_app

    client = radar_app.app.test_client()
    expected = {
        "/binh-duong": "Nhà đất Bình Dương: radar săn deal giá tốt theo dữ liệu thị trường",
        "/ban-dat-binh-duong": "Bán đất Bình Dương: lọc đất nền, đất thổ cư có biên an toàn",
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


def test_ban_dat_binh_duong_is_distinct_land_landing():
    import app as radar_app

    client = radar_app.app.test_client()
    response = client.get("/ban-dat-binh-duong")
    html = response.get_data(as_text=True)

    with radar_app.app.test_request_context("/sitemap.xml"):
        sitemap = radar_app.sitemap_xml().get_data(as_text=True)

    assert response.status_code == 200
    assert '<link rel="canonical" href="https://radarbds.vn/ban-dat-binh-duong">' in html
    assert "<loc>https://radarbds.vn/ban-dat-binh-duong</loc>" in sitemap
    assert "đất Bình Dương" in html
    assert "bán đất Bình Dương" in html
    assert "đất nền" in html
    assert "đất thổ cư" in html
    assert "Bảng giá/m² tham chiếu" in html
    assert "Tin đang theo dõi" in html
    assert "Khu có tín hiệu MOS tốt" in html
    assert "Cảnh báo tin giá ảo" in html
    assert "dat binh duong" in html


def test_binh_duong_market_report_page_is_indexed_and_citable():
    import app as radar_app

    path = "/bao-cao/bds-binh-duong-thang-06-2026"
    client = radar_app.app.test_client()
    response = client.get(path)
    html = response.get_data(as_text=True)

    with radar_app.app.test_request_context("/sitemap.xml"):
        sitemap = radar_app.sitemap_xml().get_data(as_text=True)

    assert response.status_code == 200
    assert f'<link rel="canonical" href="https://radarbds.vn{path}">' in html
    assert f"<loc>https://radarbds.vn{path}</loc>" in sitemap
    assert "Báo cáo thị trường BĐS Thủ Dầu Một tháng 06/2026" in html
    assert "Mẫu hợp lệ" in html
    assert "Giá/m² trung vị" in html
    assert "Giảm giá" in html
    assert "Actionable" in html
    assert "Nhận định từ dữ liệu Radar" in html
    assert '"@type": "Report"' in html
    assert "datePublished" in html
    assert "Đọc sâu hơn" in html
    assert 'href="/binh-duong/phuong-phu-my"' in html
    assert 'href="/binh-duong/phuong-hiep-an"' in html
    assert 'class="hero-map-stage"' not in html
    assert "Hơn 1.000 nhà đầu tư tin dùng Radar BDS" not in html
    assert "Dữ liệu tổng hợp từ tin rao công khai" in html
    assert 'class="seo-lead-capture"' in html
    assert 'data-source-context="seo_report_lead"' in html
    assert 'class="seo-lead-capture-form"' in html
    assert "'/api/leads'" in html


def test_legacy_phu_my_news_url_redirects_to_current_article_and_preserves_query():
    import app as radar_app

    response = radar_app.app.test_client().get(
        "/tin-tuc/gia-dat-phu-my-thu-dau-mot-cap-nhat-thang-7-2026?utm_source=facebook"
    )

    assert response.status_code == 301
    assert response.headers["Location"] == (
        "/tin-tuc/gia-dat-phu-my-hien-bao-nhieu?utm_source=facebook"
    )


def test_removed_knowledge_url_redirects_to_closest_current_article_and_preserves_query():
    import app as radar_app

    response = radar_app.app.test_client().get(
        "/kien-thuc/dat-binh-duong-vi-sao-khong-nen-so-gia-toan-tinh-truoc-khi-loc-tin"
        "?utm_source=bing"
    )

    assert response.status_code == 301
    assert response.headers["Location"] == (
        "/tin-tuc/cach-xem-gia-dat-binh-duong-khong-bi-so-sai?utm_source=bing"
    )


def test_truncated_gia_rao_news_url_redirects_to_canonical_article():
    import app as radar_app

    response = radar_app.app.test_client().get("/tin-tuc/gia-rao-k")

    assert response.status_code == 301
    assert response.headers["Location"] == "/tin-tuc/gia-rao-khac-gia-giao-dich-the-nao"


def test_legacy_knowledge_phu_my_url_redirects_to_current_news_article():
    import app as radar_app

    response = radar_app.app.test_client().get(
        "/kien-thuc/gia-dat-phu-my-thu-dau-mot-cap-nhat-thang-7-2026?utm_source=ga4"
    )

    assert response.status_code == 301
    assert response.headers["Location"] == (
        "/tin-tuc/gia-dat-phu-my-hien-bao-nhieu?utm_source=ga4"
    )


def test_legacy_knowledge_tdm_ward_separation_url_redirects_to_comparison_article():
    import app as radar_app

    response = radar_app.app.test_client().get(
        "/kien-thuc/gia-dat-thu-dau-mot-theo-phuong-vi-sao-phai-tach-phu-my-hiep-an-chanh-nghia"
    )

    assert response.status_code == 301
    assert response.headers["Location"] == "/tin-tuc/phuong-nao-thu-dau-mot-gia-dat-con-de-mua"


def test_legacy_report_article_urls_redirect_to_news_and_sitemap_uses_canonical_news_paths():
    import app as radar_app

    client = radar_app.app.test_client()
    legacy = "/bao-cao/gia-dat-phu-tan-thu-dau-mot-cap-nhat-thang-7-2026"
    canonical = "/tin-tuc/gia-dat-phu-tan-thu-dau-mot-cap-nhat-thang-7-2026"
    response = client.get(legacy + "?utm_source=facebook")

    with radar_app.app.test_request_context("/sitemap.xml"):
        sitemap = radar_app.sitemap_xml().get_data(as_text=True)

    assert response.status_code == 301
    assert response.headers["Location"] == canonical + "?utm_source=facebook"
    assert f"<loc>https://radarbds.vn{legacy}</loc>" not in sitemap
    assert f"<loc>https://radarbds.vn{canonical}</loc>" in sitemap
    canonical_html = client.get(canonical).get_data(as_text=True)
    assert "giá trung vị" in canonical_html
    assert "mức giá ở giữa" not in canonical_html


def test_binh_duong_location_landing_pages_render_and_are_indexed():
    import app as radar_app

    client = radar_app.app.test_client()
    expected = {
        "/binh-duong/thu-dau-mot": "Thủ Dầu Một",
        "/binh-duong/ben-cat": "Bến Cát",
        "/binh-duong/phuong-hiep-an": "Hiệp An",
        "/binh-duong/phuong-phu-my": "Phú Mỹ",
        "/binh-duong/phuong-tuong-binh-hiep": "Tương Bình Hiệp",
        "/binh-duong/phuong-tan-dinh": "Tân Định",
        "/binh-duong/phuong-chanh-phu-hoa": "Chánh Phú Hòa",
        "/binh-duong/my-phuoc-1": "Mỹ Phước 1",
        "/binh-duong/my-phuoc-2": "Mỹ Phước 2",
        "/binh-duong/my-phuoc-3": "Mỹ Phước 3",
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


def test_knowledge_articles_render_editorial_content_without_internal_marketing_labels():
    import app as radar_app
    from config.seo_articles import SEO_ARTICLES

    client = radar_app.app.test_client()
    with radar_app.app.test_request_context("/sitemap.xml"):
        sitemap = radar_app.sitemap_xml().get_data(as_text=True)

    editorial_slugs = [
        slug
        for slug, article in SEO_ARTICLES.items()
        if str(article.get("path") or "").startswith("/kien-thuc/")
    ]

    for slug in editorial_slugs:
        article = SEO_ARTICLES[slug]
        path = article["path"]
        response = client.get(path)
        html = response.get_data(as_text=True)

        assert response.status_code == 200
        assert f'<link rel="canonical" href="https://radarbds.vn{path}">' in html
        assert f"<loc>https://radarbds.vn{path}</loc>" in sitemap
        assert article["hero_title"] in html
        assert len(article["article"]["intro"]) >= 2
        assert len(article["article"]["sections"]) >= 4
        assert 'class="article-toc"' in html
        assert 'class="hero-map-stage"' not in html
        assert "Checklist trước khi đi tiếp" in html
        assert "Câu hỏi thường gặp" in html
        assert "Bài và trang liên quan" in html
        assert 'href="/?tab=signals"' in html
        assert '"@type": "BlogPosting"' in html
        assert '"@type": "Organization"' in html
        assert "datePublished" in html
        for internal_term in ("Internal links", "SEO địa phương", "VIP lead", "Telegram", "watchlist funnel"):
            assert internal_term not in html

def test_unknown_knowledge_article_404s():
    import app as radar_app

    response = radar_app.app.test_client().get("/kien-thuc/khong-ton-tai")

    assert response.status_code == 404


def test_manifest_uses_radarbds_standalone_start_url():
    manifest = json.loads(Path("static/manifest.webmanifest").read_text(encoding="utf-8"))
    icons = {icon["src"]: icon for icon in manifest["icons"]}

    assert manifest["name"] == "Radar BDS"
    assert manifest["start_url"] == "https://radarbds.vn/"
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
    article_html = (Path("templates/seo_article.html").read_text(encoding="utf-8") + Path("templates/partials/seo_head.html").read_text(encoding="utf-8"))

    for html in (dashboard_html, seo_html, article_html):
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
            if path in {"static/images/favicon-32.png", "static/images/favicon-16.png"}:
                assert img.mode == "RGBA"
                assert img.getpixel((0, 0))[3] == 0
