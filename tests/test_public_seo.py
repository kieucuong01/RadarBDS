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
    assert "<loc>https://radarbds.vn/</loc>" in sitemap
    assert "<loc>https://radarbds.vn/binh-duong</loc>" in sitemap
    assert "<loc>https://radarbds.vn/san-deal-bds</loc>" in sitemap
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
    assert 'href="/?tab=signals&amp;intent=watchlist"' in html
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
    assert "Báo cáo thị trường BĐS Bình Dương tháng 06/2026" in html
    assert "Số tin mới" in html
    assert "Giá/m² trung vị" in html
    assert "Khu giảm giá" in html
    assert "Khu nhiều tín hiệu" in html
    assert "Nhận định từ dữ liệu Radar" in html
    assert "application/ld+json" in html
    assert '"@type": "Article"' in html
    assert "datePublished" in html
    assert "Phường nên mở tiếp từ báo cáo" in html
    assert 'href="/binh-duong/phuong-phu-my"' in html
    assert 'href="/binh-duong/phuong-hiep-an"' in html
    assert "đồng dẫn đầu actionable signals" in html


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


def test_knowledge_article_renders_canonical_content_and_funnel_markers():
    import app as radar_app

    path = "/kien-thuc/ban-dat-binh-duong-cach-loc-tin-dang-kiem-tra"
    client = radar_app.app.test_client()
    response = client.get(path)
    html = response.get_data(as_text=True)

    with radar_app.app.test_request_context("/sitemap.xml"):
        sitemap = radar_app.sitemap_xml().get_data(as_text=True)

    assert response.status_code == 200
    assert f'<link rel="canonical" href="https://radarbds.vn{path}">' in html
    assert f"<loc>https://radarbds.vn{path}</loc>" in sitemap
    assert "Bán đất Bình Dương: cách lọc tin đáng kiểm tra trước khi đi xem" in html
    assert "6 dấu hiệu để biết một tin bán đất Bình Dương có đáng kiểm tra hay không" in html
    assert 'href="/?tab=signals&amp;intent=watchlist"' in html
    assert "Watchlist -&gt; Telegram -&gt; VIP lead" in html
    assert "Radar BDS là bộ lọc dữ liệu" in html
    assert 'class="hero-map-stage"' in html
    assert "Đi tiếp từ bài này" in html
    assert 'href="/ban-dat-binh-duong"' in html
    assert 'href="/binh-duong/ben-cat"' in html
    assert 'href="/san-deal-bds"' in html
    assert '"@type": "Article"' in html
    assert '"@type": "Organization"' in html
    assert "datePublished" in html


def test_thu_dau_mot_ward_pricing_article_renders_canonical_content_and_funnel_markers():
    import app as radar_app

    path = "/kien-thuc/gia-dat-thu-dau-mot-theo-phuong-vi-sao-phai-tach-phu-my-hiep-an-chanh-nghia"
    client = radar_app.app.test_client()
    response = client.get(path)
    html = response.get_data(as_text=True)

    with radar_app.app.test_request_context("/sitemap.xml"):
        sitemap = radar_app.sitemap_xml().get_data(as_text=True)

    assert response.status_code == 200
    assert f'<link rel="canonical" href="https://radarbds.vn{path}">' in html
    assert f"<loc>https://radarbds.vn{path}</loc>" in sitemap
    assert "Giá đất Thủ Dầu Một theo phường: vì sao phải tách Phú Mỹ, Hiệp An, Chánh Nghĩa trước khi so giá" in html
    assert "6 dấu hiệu để biết bạn đang so đúng giá đất Thủ Dầu Một theo phường hay đang gom sai mặt bằng" in html
    assert 'href="/?tab=signals&amp;intent=watchlist"' in html
    assert "Dashboard -&gt; Watchlist -&gt; Telegram/VIP lead" in html
    assert "Radar BDS là bộ lọc dữ liệu ban đầu" in html
    assert 'href="/binh-duong/thu-dau-mot"' in html
    assert 'href="/binh-duong/phuong-phu-my"' in html
    assert 'href="/binh-duong/phuong-hiep-an"' in html
    assert 'href="/binh-duong/phuong-chanh-nghia"' in html
    assert 'href="/san-deal-bds"' in html
    assert '"@type": "Article"' in html
    assert "datePublished" in html


def test_binh_duong_land_pricing_scope_article_renders_canonical_content_and_funnel_markers():
    import app as radar_app

    path = "/kien-thuc/dat-binh-duong-vi-sao-khong-nen-so-gia-toan-tinh-truoc-khi-loc-tin"
    client = radar_app.app.test_client()
    response = client.get(path)
    html = response.get_data(as_text=True)

    with radar_app.app.test_request_context("/sitemap.xml"):
        sitemap = radar_app.sitemap_xml().get_data(as_text=True)

    assert response.status_code == 200
    assert f'<link rel="canonical" href="https://radarbds.vn{path}">' in html
    assert f"<loc>https://radarbds.vn{path}</loc>" in sitemap
    assert "Đất Bình Dương: vì sao không nên so giá toàn tỉnh trước khi lọc tin" in html
    assert "6 dấu hiệu cho thấy bạn đang so đất Bình Dương đúng khu hay đang gom sai cả tỉnh" in html
    assert 'href="/?tab=signals&amp;intent=watchlist"' in html
    assert "Dashboard -&gt; Watchlist -&gt; Telegram/VIP lead" in html
    assert "Radar BDS là bộ lọc dữ liệu ban đầu" in html
    assert 'href="/ban-dat-binh-duong"' in html
    assert 'href="/binh-duong/thu-dau-mot"' in html
    assert 'href="/binh-duong/ben-cat"' in html
    assert 'href="/binh-duong/my-phuoc"' in html
    assert 'href="/san-deal-bds"' in html
    assert '"@type": "Article"' in html
    assert "datePublished" in html


def test_phu_my_ward_comparison_article_renders_canonical_content_and_funnel_markers():
    import app as radar_app

    path = "/kien-thuc/nha-dat-phu-my-thu-dau-mot-cach-so-dung-voi-hiep-an-chanh-nghia"
    client = radar_app.app.test_client()
    response = client.get(path)
    html = response.get_data(as_text=True)

    with radar_app.app.test_request_context("/sitemap.xml"):
        sitemap = radar_app.sitemap_xml().get_data(as_text=True)

    assert response.status_code == 200
    assert f'<link rel="canonical" href="https://radarbds.vn{path}">' in html
    assert f"<loc>https://radarbds.vn{path}</loc>" in sitemap
    assert "Nhà đất Phú Mỹ Thủ Dầu Một: cách so đúng với Hiệp An, Chánh Nghĩa trước khi xuống tiền" in html
    assert "6 dấu hiệu cho thấy bạn đang so nhà đất Phú Mỹ đúng cách hay đang kéo nhầm mặt bằng của ward khác" in html
    assert 'href="/?tab=signals&amp;intent=watchlist"' in html
    assert "Dashboard -&gt; Watchlist -&gt; Telegram/VIP lead" in html
    assert "Radar BDS là bộ lọc dữ liệu ban đầu" in html
    assert 'href="/binh-duong/phuong-phu-my"' in html
    assert 'href="/binh-duong/phuong-hiep-an"' in html
    assert 'href="/binh-duong/phuong-chanh-nghia"' in html
    assert 'href="/binh-duong/thu-dau-mot"' in html
    assert 'href="/san-deal-bds"' in html
    assert '"@type": "Article"' in html
    assert "datePublished" in html


def test_ben_cat_cluster_article_renders_canonical_content_and_funnel_markers():
    import app as radar_app
    from config.seo_articles import SEO_ARTICLES

    path = "/kien-thuc/nha-dat-ben-cat-binh-duong-cach-tach-my-phuoc-tan-dinh-thoi-hoa-truoc-khi-so-gia"
    article = SEO_ARTICLES["nha-dat-ben-cat-binh-duong-cach-tach-my-phuoc-tan-dinh-thoi-hoa-truoc-khi-so-gia"]
    client = radar_app.app.test_client()
    response = client.get(path)
    html = response.get_data(as_text=True)

    with radar_app.app.test_request_context("/sitemap.xml"):
        sitemap = radar_app.sitemap_xml().get_data(as_text=True)

    assert response.status_code == 200
    assert f'<link rel="canonical" href="https://radarbds.vn{path}">' in html
    assert f"<loc>https://radarbds.vn{path}</loc>" in sitemap
    assert article["hero_title"] in html
    assert article["market_snapshot"]["title"] in html
    assert article["market_snapshot"]["body"] in html
    assert 'href="/?tab=signals&amp;intent=watchlist"' in html
    assert "Dashboard -&gt; Watchlist -&gt; Telegram/VIP lead" in html
    assert "Knowledge / Ben Cat Binh Duong" in html
    assert 'href="/binh-duong/ben-cat"' in html
    assert 'href="/binh-duong/my-phuoc"' in html
    assert 'href="/binh-duong/phuong-tan-dinh"' in html
    assert 'href="/binh-duong/phuong-thoi-hoa"' in html
    assert 'href="/kien-thuc/dat-my-phuoc-binh-duong-cach-tach-my-phuoc-1-2-3-de-khong-so-sai-gia"' in html
    assert 'href="/san-deal-bds"' in html
    assert '"@type": "Article"' in html
    assert "datePublished" in html


def test_all_knowledge_articles_are_indexed_and_render_funnel_markers():
    import app as radar_app
    from config.seo_articles import SEO_ARTICLES

    client = radar_app.app.test_client()

    with radar_app.app.test_request_context("/sitemap.xml"):
        sitemap = radar_app.sitemap_xml().get_data(as_text=True)

    for article in SEO_ARTICLES.values():
        path = article["path"]
        response = client.get(path)
        html = response.get_data(as_text=True)

        assert response.status_code == 200
        assert f'<link rel="canonical" href="https://radarbds.vn{path}">' in html
        assert f"<loc>https://radarbds.vn{path}</loc>" in sitemap
        assert article["hero_title"] in html
        assert 'class="hero-map-stage"' in html
        assert article["market_snapshot"]["title"] in html
        assert article["final_cta"]["button"] in html
        assert "Đi tiếp từ bài này" in html
        assert 'href="/?tab=signals&amp;intent=watchlist"' in html
        assert "Telegram" in html
        assert '"@type": "Article"' in html
        assert '"@type": "Organization"' in html
        assert "datePublished" in html


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
    article_html = Path("templates/seo_article.html").read_text(encoding="utf-8")

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
