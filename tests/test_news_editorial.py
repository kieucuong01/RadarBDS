"""One sourced event has one reader destination across web and social."""

import copy
import json
import re

import pytest


SOURCE = "https://baochinhphu.vn/tin-ha-tang-123.htm"


def news_article():
    return {
        "path": "/tin-tuc/tin-ha-tang-radar",
        "hero_title": "Hạ tầng: thông tin đã được xác nhận",
        "description": "Góc nhìn người mua và những điều cần kiểm tra.",
        "article": {"published_at": "2026-10-15", "modified_at": "2026-10-15"},
        "news": {
            "status": "published",
            "event_key": "ha-tang-20261015",
            "topic": "ha-tang",
            "event_status": "Mục tiêu, chưa hoàn thành",
            "sources": [{"url": SOURCE, "publisher": "Báo Chính phủ", "published_at": "2026-10-14"}],
            "media": [{"kind": "facebook", "url": "https://www.facebook.com/radarbdsvn/posts/123", "verified": True}],
        },
    }


def test_merge_replaces_matching_source_keeps_unrelated_and_sorts():
    from services.news_editorial import merge_hot_topic_items

    external = [
        {"slug": "source", "source_url": SOURCE + "?utm_source=facebook", "published_at": "2026-10-14"},
        {"slug": "other", "source_url": "https://cafeland.vn/another.htm", "published_at": "2026-10-13"},
    ]
    cards = merge_hot_topic_items({"radar": news_article()}, external)

    assert len(cards) == 2
    assert cards[0]["url"] == "/tin-tuc/tin-ha-tang-radar"
    assert cards[0]["is_external"] is False
    assert cards[0]["source_url"] == SOURCE
    assert cards[1]["url"] == "https://cafeland.vn/another.htm"
    assert cards[1]["is_external"] is True
    assert "url" not in external[0]  # Presentation must not mutate stored evidence.


@pytest.mark.parametrize("change", ["draft", "missing-source", "unsafe-source", "invalid-date", "missing-event"])
def test_unpublishable_news_never_hides_original_source(change):
    from services.news_editorial import is_public_article, merge_hot_topic_items

    article = news_article()
    if change == "draft":
        article["news"]["status"] = "draft"
    elif change == "missing-source":
        article["news"]["sources"] = []
    elif change == "unsafe-source":
        article["news"]["sources"][0]["url"] = "javascript:alert(1)"
    elif change == "invalid-date":
        article["news"]["sources"][0]["published_at"] = "not-a-date"
    else:
        article["news"].pop("event_key")
    assert not is_public_article(article)
    cards = merge_hot_topic_items({"radar": article}, [{"source_url": SOURCE}])
    assert len(cards) == 1 and cards[0]["is_external"]


@pytest.mark.parametrize("bad", [None, {}, "bad", [], {"status": "published", "sources": "bad"}])
def test_malformed_news_containers_fail_closed(configured_news, bad):
    radar_app, article = configured_news
    article["news"] = bad
    client = radar_app.app.test_client()
    assert client.get(article["path"]).status_code == 404
    assert article["hero_title"] not in client.get("/tin-tuc").get_data(as_text=True)
    assert client.get("/sitemap.xml").status_code == 200


@pytest.mark.parametrize("bad", ["bad", [], None])
def test_malformed_article_dates_do_not_break_hub_or_sitemap(configured_news, bad):
    radar_app, article = configured_news
    article["article"] = bad
    client = radar_app.app.test_client()
    for path in ("/tin-tuc/chu-de-nong", "/sitemap.xml"):
        assert client.get(path).status_code == 200


def test_event_dedupe_uses_editorial_key_and_media_requires_verified_safe_url():
    from services.news_editorial import merge_hot_topic_items, news_metadata

    first = news_article()
    second = copy.deepcopy(first)
    second["path"] = "/tin-tuc/duplicate"
    second["article"]["modified_at"] = "2026-10-14"
    first["news"]["media"] += [
        {"kind": "video", "url": "https://youtube.com/watch?v=draft", "verified": False},
        {"kind": "video", "url": "javascript:alert(1)", "verified": True},
        {"kind": "video", "url": "https://evil.example/video", "verified": True},
        {"kind": [], "url": "https://youtube.com/watch?v=bad", "verified": True},
    ]
    assert len(merge_hot_topic_items({"first": first, "second": second}, [])) == 1
    assert len(news_metadata(first)["media"]) == 1


@pytest.fixture
def configured_news(monkeypatch):
    import app as radar_app

    monkeypatch.setattr(radar_app, "SEO_ARTICLES", {slug: item for slug, item in radar_app.SEO_ARTICLES.items() if not item.get("news")})
    slug, base = next((slug, item) for slug, item in radar_app.SEO_ARTICLES.items() if item["path"].startswith("/tin-tuc/"))
    article = copy.deepcopy(base)
    for key, value in news_article().items():
        if key != "article":
            article[key] = value
    article["article"]["published_at"] = "2026-10-15"
    article["article"]["modified_at"] = "2026-10-15"
    monkeypatch.setitem(radar_app.SEO_ARTICLES, "tin-ha-tang-radar", article)

    class Repository:
        def list_published(self, **kwargs):
            return [{"item_type": "hot_topic", "slug": "source", "title": "Tiêu đề báo gốc", "source_url": SOURCE, "source_name": "Báo Chính phủ", "published_at": "2026-10-14"}] if kwargs.get("item_type") == "hot_topic" else []

    monkeypatch.setattr(radar_app, "_public_content_repository", Repository())
    return radar_app, article


def test_portal_hot_hub_and_data_archive_share_correct_classification(configured_news):
    radar_app, article = configured_news
    client = radar_app.app.test_client()
    for path in ("/tin-tuc", "/tin-tuc/chu-de-nong"):
        html = client.get(path).get_data(as_text=True)
        assert f'href="{article["path"]}"' in html
        assert "Tiêu đề báo gốc" not in html
    archive = client.get("/tin-tuc/du-lieu-radarbds").get_data(as_text=True)
    assert article["hero_title"] not in archive


def test_article_sources_media_breadcrumb_and_schema_agree(configured_news):
    radar_app, article = configured_news
    html = radar_app.app.test_client().get(article["path"]).get_data(as_text=True)
    assert f'href="{SOURCE}"' in html
    assert "Mục tiêu, chưa hoàn thành" in html
    assert 'href="https://www.facebook.com/radarbdsvn/posts/123"' in html
    assert 'href="/tin-tuc/chu-de-nong"' in html
    assert 'href="/tin-tuc/du-lieu-radarbds"' not in re.search(r'<nav[^>]*aria-label="Breadcrumb".*?</nav>', html, re.S).group(0)
    graphs = [json.loads(s) for s in re.findall(r'<script type="application/ld\+json">\s*(.*?)\s*</script>', html, re.S)]
    node = next(n for g in graphs for n in g.get("@graph", []) if n.get("@type") == "NewsArticle")
    assert node["citation"] == [SOURCE]
    assert node["url"] == "https://radarbds.vn" + article["path"]


def test_draft_news_is_not_public_or_in_sitemap(configured_news):
    radar_app, article = configured_news
    article["news"]["status"] = "draft"
    client = radar_app.app.test_client()
    assert client.get(article["path"]).status_code == 404
    assert "https://radarbds.vn" + article["path"] not in client.get("/sitemap.xml").get_data(as_text=True)


def test_article_artwork_is_rendered_once_and_shared_in_schema(configured_news):
    radar_app, article = configured_news
    artwork = {
        "src": "/static/images/seo/news/apartment-budget-20261016.webp",
        "alt": "Máy tính và mặt bằng minh họa ngân sách căn hộ",
        "caption": "Ảnh minh họa AI, không phải dự án thực tế.",
        "width": 1672,
        "height": 941,
    }
    article["article"]["illustration"] = artwork
    html = radar_app.app.test_client().get(article["path"]).get_data(as_text=True)
    assert html.count(f'src="{artwork["src"]}"') == 1
    assert 'width="1672" height="941"' in html
    assert artwork["caption"] in html
    assert html.index('class="article-visual-figure"') < html.index('class="article-toc"')
    graphs = [json.loads(s) for s in re.findall(r'<script type="application/ld\+json">\s*(.*?)\s*</script>', html, re.S)]
    node = next(n for g in graphs for n in g.get("@graph", []) if n.get("@type") == "NewsArticle")
    assert node["image"] == "https://radarbds.vn" + artwork["src"]
    assert f'content="{node["image"]}"' in html


def test_pilot_artwork_files_match_their_declared_dimensions():
    from pathlib import Path
    from PIL import Image
    from config.seo_hot_topic_articles import HOT_TOPIC_ARTICLES

    root = Path(__file__).resolve().parents[1]
    for page in HOT_TOPIC_ARTICLES.values():
        artwork = page["article"]["illustration"]
        with Image.open(root / artwork["src"].lstrip("/")) as image:
            assert image.size == (artwork["width"], artwork["height"])
            assert image.format == "WEBP"
        assert "minh họa AI" in artwork["caption"]


def test_social_sources_resolve_to_same_published_article_without_guessing():
    from services.news_editorial import article_for_sources

    article = news_article()
    assert article_for_sources({"one": article}, [SOURCE + "?utm_medium=social"]) == article["path"]
    assert article_for_sources({"one": article}, ["https://cafeland.vn/unrelated"]) is None
    article["news"]["status"] = "draft"
    assert article_for_sources({"one": article}, [SOURCE]) is None


def test_pilot_articles_have_valid_sources_verified_posts_and_resolving_internal_links():
    import app as radar_app
    from config.seo_hot_topic_articles import HOT_TOPIC_ARTICLES
    from services.news_editorial import news_metadata

    client = radar_app.app.test_client()
    for article in HOT_TOPIC_ARTICLES.values():
        assert news_metadata(article)
        response = client.get(article["path"])
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert '"NewsArticle"' in html
        assert "Muốn nhận 5 tin đáng kiểm tra mới nhất" not in html
        assert "Nguồn:" not in article["hero_title"]
        for link in article["local_links"]:
            assert client.get(link["href"]).status_code in {200, 301}
