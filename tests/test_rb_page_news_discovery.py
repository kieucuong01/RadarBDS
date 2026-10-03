from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts import rb_page_news_discovery as news

VN_TZ = timezone(timedelta(hours=7))
NOW = datetime(2026, 9, 12, 12, 0, tzinfo=VN_TZ)


class FakeResponse:
    def __init__(self, url: str, text: str, status_code: int = 200):
        self.url = url
        self.text = text
        self.content = text.encode("utf-8")
        self.status_code = status_code
        self.encoding = "utf-8"
        self.headers = {"content-type": "text/html; charset=utf-8"}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def install_fake_fetch(monkeypatch, pages: dict[str, str]) -> None:
    canonical_pages = {news.canonicalize_url(k): v for k, v in pages.items()}

    def fake_fetch(url: str, *, session=None):
        clean = news.canonicalize_url(url)
        assert clean in canonical_pages, f"unexpected fetch {url} -> {clean}"
        return FakeResponse(clean, canonical_pages[clean])

    monkeypatch.setattr(news, "_fetch_url", fake_fetch)


def test_collect_news_returns_source_contract_with_metadata_date_and_clean_body(monkeypatch):
    feed_url = "https://vnexpress.net/rss/bat-dong-san.rss"
    article_url = "https://vnexpress.net/binh-duong-can-ho-tre-123.html"
    install_fake_fetch(
        monkeypatch,
        {
            feed_url: f"""<?xml version='1.0'?><rss><channel><item>
                <title>Bình Dương mở thêm tuyến metro kết nối nhà ở phía Đông</title>
                <link>{article_url}?utm_source=feed</link>
                <pubDate>Sat, 12 Sep 2026 08:30:00 +0700</pubDate>
            </item></channel></rss>""",
            article_url: """<html><head>
                <link rel="canonical" href="https://vnexpress.net/binh-duong-can-ho-tre-123.html?utm_campaign=x">
                <meta property="og:title" content="Bình Dương mở thêm tuyến metro kết nối nhà ở phía Đông">
                <meta property="article:published_time" content="2026-09-12T08:30:00+07:00">
                </head><body><nav>menu rác</nav><article>
                <h1>Bình Dương mở thêm tuyến metro kết nối nhà ở phía Đông</h1>
                <p>Thông tin mới về kết nối Bình Dương, TP.HCM phía Đông và nhà ở cho người mua.</p>
                <p>Người mua cần kiểm tra pháp lý dự án, tiến độ được phê duyệt và kết nối thực tế.</p>
                </article><footer>footer rác</footer></body></html>""",
        },
    )
    monkeypatch.setattr(news, "SOURCES", [{"publisher": "VnExpress", "url": feed_url, "kind": "rss"}])

    report = news.collect_news(now=NOW, limit=12)

    assert report["schema"] == "rb_page_news_discovery.v1"
    assert datetime.fromisoformat(report["generated_at"]) == NOW
    assert report["errors"] == []
    assert len(report["candidates"]) == 1
    candidate = report["candidates"][0]
    assert set(candidate) == {
        "id",
        "url",
        "publisher",
        "title",
        "published_at",
        "fetched_at",
        "text",
        "content_sha256",
        "is_primary",
        "eligible",
        "classification",
        "trend_evidence",
        "location",
        "topic_key",
        "score",
        "requires_primary",
        "rejection_reasons",
    }
    assert candidate["id"] == hashlib.sha256(article_url.encode("utf-8")).hexdigest()[:16]
    assert candidate["url"] == article_url
    assert candidate["publisher"] == "VnExpress"
    assert candidate["title"] == "Bình Dương mở thêm tuyến metro kết nối nhà ở phía Đông"
    assert candidate["published_at"] == "2026-09-12T08:30:00+07:00"
    assert candidate["fetched_at"] == NOW.isoformat()
    assert "menu rác" not in candidate["text"]
    assert "footer rác" not in candidate["text"]
    assert "Thông tin mới" in candidate["text"]
    assert candidate["content_sha256"] == hashlib.sha256(candidate["text"].encode()).hexdigest()
    assert candidate["is_primary"] is False
    assert candidate["eligible"] is True
    assert candidate["classification"] == "news_candidate"
    assert candidate["trend_evidence"] == []
    assert candidate["location"] == "Bình Dương"
    assert candidate["requires_primary"] is True
    assert candidate["rejection_reasons"] == []


def test_collect_news_keeps_rejected_candidates_for_unknown_old_future_and_irrelevant_dates(monkeypatch):
    feed_url = "https://tuoitre.vn/rss/nha-dat.rss"
    old_url = "https://tuoitre.vn/old.html"
    future_url = "https://tuoitre.vn/future.html"
    unknown_url = "https://tuoitre.vn/unknown.html"
    other_url = "https://tuoitre.vn/other.html"
    body = "<html><body><article><p>Nội dung đủ dài về bất động sản nhưng thiếu điều kiện hợp lệ.</p></article></body></html>"
    install_fake_fetch(
        monkeypatch,
        {
            feed_url: f"""<rss><channel>
                <item><title>Bình Dương tin quá cũ</title><link>{old_url}</link><pubDate>Tue, 01 Sep 2026 08:00:00 +0700</pubDate></item>
                <item><title>Bình Dương tin tương lai</title><link>{future_url}</link><pubDate>Sat, 12 Sep 2026 12:30:00 +0700</pubDate></item>
                <item><title>Bình Dương không có ngày</title><link>{unknown_url}</link></item>
                <item><title>Biệt thự nghỉ dưỡng ở nơi khác</title><link>{other_url}</link><pubDate>Sat, 12 Sep 2026 08:00:00 +0700</pubDate></item>
            </channel></rss>""",
            old_url: body,
            future_url: body,
            unknown_url: body,
            other_url: body,
        },
    )
    monkeypatch.setattr(news, "SOURCES", [{"publisher": "Tuổi Trẻ", "url": feed_url, "kind": "rss"}])

    report = news.collect_news(now=NOW, limit=12)

    assert len(report["candidates"]) == 4
    by_url = {c["url"]: c for c in report["candidates"]}
    assert by_url[old_url]["eligible"] is False
    assert "published_older_than_7_days" in by_url[old_url]["rejection_reasons"]
    assert by_url[future_url]["eligible"] is False
    assert "published_in_future" in by_url[future_url]["rejection_reasons"]
    assert by_url[unknown_url]["eligible"] is False
    assert "unknown_published_at" in by_url[unknown_url]["rejection_reasons"]
    assert by_url[other_url]["eligible"] is False
    assert "not_relevant_location_or_policy" in by_url[other_url]["rejection_reasons"]


def test_cafeland_listing_html_discovers_articles_and_deduplicates_story_topics(monkeypatch):
    listing_url = "https://cafeland.vn/tin-tuc/"
    first = "https://cafeland.vn/tin-tuc/binh-duong-cap-nhat-quy-hoach-1.html"
    duplicate = "https://cafeland.vn/tin-tuc/binh-duong-cap-nhat-quy-hoach-1.html?fbclid=abc"
    second = "https://cafeland.vn/tin-tuc/binh-duong-cap-nhat-quy-hoach-2.html"
    article_html = """<html><head><meta property="article:published_time" content="2026-09-11T10:00:00+07:00"></head>
        <body><article><h1>Bình Dương cập nhật quy hoạch đô thị mới</h1>
        <p>Văn bản liên quan quy hoạch đô thị tại Bình Dương, người mua cần đối chiếu nguồn chính thức.</p></article></body></html>"""
    install_fake_fetch(
        monkeypatch,
        {
            listing_url: f"""<html><body>
                <a href="{first}">Bình Dương cập nhật quy hoạch đô thị mới</a>
                <a href="{duplicate}">Bình Dương cập nhật quy hoạch đô thị mới</a>
                <a href="{second}">Bình Dương cập nhật quy hoạch đô thị mới!</a>
            </body></html>""",
            first: article_html,
            second: article_html,
        },
    )
    monkeypatch.setattr(news, "SOURCES", [{"publisher": "CafeLand", "url": listing_url, "kind": "html"}])

    report = news.collect_news(now=NOW, limit=12)

    assert len(report["candidates"]) == 1
    assert report["candidates"][0]["url"] == first
    assert report["candidates"][0]["topic_key"] == news.make_topic_key("Bình Dương cập nhật quy hoạch đô thị mới")


def test_http_safety_blocks_non_https_private_and_unallowlisted_hosts():
    for bad in ("http://vnexpress.net/rss/bat-dong-san.rss", "https://127.0.0.1/a", "https://example.com/a"):
        try:
            news.validate_public_https_url(bad)
        except ValueError as exc:
            assert str(exc)
        else:  # pragma: no cover - clearer assertion message
            raise AssertionError(f"accepted unsafe URL {bad}")


def test_atomic_write_json_replaces_complete_report(tmp_path):
    out = tmp_path / "report.json"
    report = {"schema": "rb_page_news_discovery.v1", "generated_at": NOW.isoformat(), "candidates": [], "errors": []}

    news.atomic_write_json(out, report)

    assert out.read_text(encoding="utf-8").endswith("\n")
    assert '"schema": "rb_page_news_discovery.v1"' in out.read_text(encoding="utf-8")
    assert not list(Path(tmp_path).glob("*.tmp"))
