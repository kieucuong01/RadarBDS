import json
import re


def test_news_archive_has_distinct_title_bounded_pages_and_complete_discovery():
    import app as radar_app
    from config.seo_articles import SEO_ARTICLES
    from services.news_editorial import is_public_article
    client = radar_app.app.test_client()
    seen = []
    path = "/tin-tuc/du-lieu-radarbds"
    while path:
        html = client.get(path).get_data(as_text=True)
        assert "Phân tích giá rao Bình Dương" in html
        cards = re.findall(r'data-news-card-path="([^"]+)"', html)
        featured = re.findall(r'data-news-featured="([^"]+)"', html)
        assert len(cards) <= 12
        seen.extend(featured + cards)
        next_link = re.search(r'<a[^>]+rel="next"[^>]+href="([^"]+)"', html)
        path = next_link.group(1).replace("&amp;", "&") if next_link else None
    expected = {article["path"] for article in SEO_ARTICLES.values()
                if article["path"].startswith("/tin-tuc/") and not article.get("news") and is_public_article(article)}
    assert set(seen) == expected
    assert len(seen) == len(set(seen))
    page2 = client.get("/tin-tuc/du-lieu-radarbds?page=2").get_data(as_text=True)
    assert 'href="https://radarbds.vn/tin-tuc/du-lieu-radarbds?page=2"' in page2
    assert "Trang 2" in page2
    for raw in re.findall(r'<script type="application/ld\+json">(.*?)</script>', page2, re.S):
        json.loads(raw)


def test_news_archive_searches_all_articles_before_pagination():
    import app as radar_app
    client = radar_app.app.test_client()
    html = client.get("/tin-tuc/du-lieu-radarbds?q=phu+loi").get_data(as_text=True)
    assert "noindex,follow" in html
    assert 'name="q"' in html and 'value="phu loi"' in html
    assert 'data-news-card-path=' in html
    assert client.get("/tin-tuc/du-lieu-radarbds?page=0").status_code == 404
    assert client.get("/tin-tuc/du-lieu-radarbds?page=9999999999999").status_code == 404


def test_privacy_page_is_public_and_linked_from_forms_and_footer():
    import app as radar_app
    client = radar_app.app.test_client()
    response = client.get("/chinh-sach-bao-mat")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "radarbds@gmail.com" in html and "0343216024" in html
    assert 'href="https://radarbds.vn/chinh-sach-bao-mat"' in html
    tool = client.get("/bang-gia-dat-tphcm").get_data(as_text=True)
    assert 'href="/chinh-sach-bao-mat"' in tool
