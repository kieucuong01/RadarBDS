from pathlib import Path

import pytest

from config.seo_articles import SEO_ARTICLES


ARTICLE_EXPECTATIONS = {
    "ban-dat-binh-duong-cach-loc-tin-dang-kiem-tra": "Chọn đúng phạm vi trước khi nhìn vào giá rao",
    "dat-my-phuoc-binh-duong-cach-tach-my-phuoc-1-2-3-de-khong-so-sai-gia": "Mỹ Phước 1, 2, 3 cần được đọc như ba tiểu khu",
    "gia-dat-thu-dau-mot-theo-phuong-vi-sao-phai-tach-phu-my-hiep-an-chanh-nghia": "Ba phường, ba bối cảnh so sánh khác nhau",
    "dat-binh-duong-vi-sao-khong-nen-so-gia-toan-tinh-truoc-khi-loc-tin": "Một con số toàn tỉnh không trả lời được lô đất có đáng xem hay không",
    "nha-dat-phu-my-thu-dau-mot-cach-so-dung-voi-hiep-an-chanh-nghia": "Phú Mỹ không phải bản sao giá của Hiệp An hay Chánh Nghĩa",
    "nha-dat-ben-cat-binh-duong-cach-tach-my-phuoc-tan-dinh-thoi-hoa-truoc-khi-so-gia": "Bến Cát là phạm vi rộng, không phải một mặt bằng giá duy nhất",
}


def test_two_content_hubs_exist_and_news_hub_does_not():
    import app as radar_app

    client = radar_app.app.test_client()
    report = client.get("/bao-cao")
    knowledge = client.get("/kien-thuc")

    assert report.status_code == 200
    assert knowledge.status_code == 200
    assert client.get("/tin-tuc").status_code == 404

    report_html = report.get_data(as_text=True)
    knowledge_html = knowledge.get_data(as_text=True)
    assert '<link rel="canonical" href="https://radarbds.vn/bao-cao">' in report_html
    assert '<link rel="canonical" href="https://radarbds.vn/kien-thuc">' in knowledge_html
    assert 'class="seo-page report-hub"' in report_html
    assert 'class="seo-page knowledge-hub"' in knowledge_html
    for html in (report_html, knowledge_html):
        assert '"@type": "CollectionPage"' in html
        assert '"@type": "ItemList"' in html
        assert '"@type": "BreadcrumbList"' in html

    assert "Hiện ưu tiên Thủ Dầu Một" in report_html
    assert "Cách đọc giá đất Thủ Dầu Một theo từng phường" in knowledge_html


@pytest.mark.parametrize(
    ("path", "active"),
    [
        ("/binh-duong", "binh-duong"),
        ("/bao-cao", "bao-cao"),
        ("/kien-thuc", "kien-thuc"),
        ("/san-deal-bds", "san-deal"),
    ],
)
def test_shared_navigation_and_active_state(path, active):
    import app as radar_app

    html = radar_app.app.test_client().get(path).get_data(as_text=True)
    for item in ("binh-duong", "bao-cao", "kien-thuc", "san-deal"):
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

        for internal_term in ("Internal links", "SEO địa phương", "VIP lead", "funnel"):
            assert internal_term not in html


def test_hubs_are_in_sitemap_and_detail_canonicals_stay_unchanged():
    import app as radar_app

    with radar_app.app.test_request_context("/sitemap.xml"):
        sitemap = radar_app.sitemap_xml().get_data(as_text=True)

    assert "<loc>https://radarbds.vn/bao-cao</loc>" in sitemap
    assert "<loc>https://radarbds.vn/kien-thuc</loc>" in sitemap
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

    paths = ["/bao-cao", "/kien-thuc", "/bao-cao/bds-binh-duong-thang-06-2026"]
    paths.extend(article["path"] for article in SEO_ARTICLES.values())
    client = radar_app.app.test_client()

    for path in paths:
        html = client.get(path).get_data(as_text=True)
        blocks = re.findall(r'<script type="application/ld\+json">\s*(.*?)\s*</script>', html, re.S)
        assert blocks, path
        for block in blocks:
            payload = json.loads(block)
            assert payload["@context"] == "https://schema.org"

