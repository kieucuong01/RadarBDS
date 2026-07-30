from unittest import mock

from crawler.guland_pw import GulandCrawler
from services.guland_reconciliation import ExistingGulandSnapshot


FIRST_SEEN = "2026-07-01T08:00:00+07:00"


def _run_cards(monkeypatch, cards, snapshots, details):
    crawler = GulandCrawler()
    crawler._stats = {
        "fetched": 0,
        "new": 0,
        "updated": 0,
        "skipped": 0,
        "errors": 0,
        "error_details": [],
    }
    fetched_urls = []
    seen_urls = []

    monkeypatch.setattr(
        crawler,
        "_scroll_all_cards",
        lambda page, base_url, incremental: cards,
    )
    monkeypatch.setattr(
        crawler,
        "_load_existing_snapshots",
        lambda urls: snapshots,
    )

    def fetch(_page, urls):
        fetched_urls.extend(urls)
        return {url: details[url] for url in urls}

    monkeypatch.setattr(crawler, "_fetch_details_batch", fetch)
    monkeypatch.setattr(
        crawler,
        "_mark_seen_urls",
        lambda urls: seen_urls.extend(urls) or len(urls),
    )
    monkeypatch.setattr(
        crawler,
        "_build_record",
        lambda card, detail: {
            "url": card["url"],
            "post_id": card.get("post_id", ""),
            "title": "Guland test listing",
            "price_ty": card.get("price_ty"),
            "area_m2": 100.0,
        },
    )
    def insert_new(card, _record):
        crawler._stats["new"] += 1
        return 9000 + int(card["post_id"])

    monkeypatch.setattr(crawler, "_insert_new_record", insert_new)
    monkeypatch.setattr(
        crawler,
        "_refresh_changed_record",
        lambda snapshot, record: snapshot.raw_id,
    )

    crawler._run_crawl(
        page=object(),
        base_url="https://guland.vn/test",
        incremental=True,
    )
    return crawler._stats, fetched_urls, seen_urls


def test_guland_counts_fetched_cards_before_filtering_existing_urls(monkeypatch):
    cards = [
        {
            "url": "https://guland.vn/post/a-1",
            "post_id": "1",
            "title": "A",
            "price_raw": "2 tỷ",
        },
        {
            "url": "https://guland.vn/post/b-2",
            "post_id": "2",
            "title": "B",
            "price_raw": "2 tỷ",
        },
        {
            "url": "https://guland.vn/post/c-3",
            "post_id": "3",
            "title": "C",
            "price_raw": "2 tỷ",
        },
    ]
    existing_url = cards[1]["url"]
    snapshots = {
        existing_url: ExistingGulandSnapshot(
            22,
            32,
            existing_url,
            "2",
            2.0,
            FIRST_SEEN,
            "active",
        )
    }
    details = {
        cards[0]["url"]: {
            "url": cards[0]["url"],
            "http_status": 200,
            "page_status": "live",
            "detail_price_raw": "2 tỷ",
        },
        cards[2]["url"]: {
            "url": cards[2]["url"],
            "http_status": 200,
            "page_status": "live",
            "detail_price_raw": "2 tỷ",
        },
    }

    stats, _fetched_urls, _seen_urls = _run_cards(
        monkeypatch,
        cards,
        snapshots,
        details,
    )

    assert stats["new"] == 2
    assert stats["fetched"] == 3


def test_existing_same_price_marks_seen_without_detail(monkeypatch):
    url = "https://guland.vn/post/same-2001"
    card = {
        "url": url,
        "post_id": "2001",
        "price_raw": "2,5 tỷ",
    }
    snapshot = ExistingGulandSnapshot(
        21,
        31,
        url,
        "2001",
        2.5,
        FIRST_SEEN,
        "active",
    )

    stats, fetched_urls, seen_urls = _run_cards(
        monkeypatch,
        [card],
        {url: snapshot},
        {},
    )

    assert stats["existing"] == 1
    assert stats["unchanged"] == 1
    assert stats["updated"] == 0
    assert fetched_urls == []
    assert seen_urls == [url]


def test_existing_changed_price_enters_detail_batch(monkeypatch):
    url = "https://guland.vn/post/changed-2002"
    card = {
        "url": url,
        "post_id": "2002",
        "price_raw": "2,7 tỷ",
    }
    snapshot = ExistingGulandSnapshot(
        22,
        32,
        url,
        "2002",
        2.5,
        FIRST_SEEN,
        "active",
    )
    detail = {
        "url": url,
        "http_status": 200,
        "page_status": "live",
        "detail_price_raw": "2,7 tỷ",
    }

    stats, fetched_urls, _seen_urls = _run_cards(
        monkeypatch,
        [card],
        {url: snapshot},
        {url: detail},
    )

    assert fetched_urls == [url]
    assert stats["updated"] == 1
    assert stats["refreshed_raw_ids"] == [22]


def test_build_record_adds_valid_source_coordinate_fields():
    crawler = GulandCrawler()
    card = {
        "url": "https://guland.vn/post/dat-tan-an-1231140",
        "source_list_url": (
            "https://guland.vn/mua-ban-dat-tho-cu-"
            "phuong-tan-an-thanh-pho-thu-dau-mot-binh-duong"
        ),
        "post_id": "1231140",
        "title": "Bán đất Tân An",
        "price_raw": "2 tỷ",
        "area_raw": "100 m²",
        "pm2_raw": "20 tr/m²",
        "date_raw": "Hôm nay",
        "source_coordinate_url": (
            "https://www.google.com/maps/search/"
            "?api=1&query=11.028099613958%2C106.6206724626"
        ),
    }
    decision = mock.Mock(
        status="valid",
        lat=11.028099613958,
        lng=106.6206724626,
        sanitized_url=(
            "https://www.google.com/maps/search/"
            "?api=1&query=11.0280996%2C106.6206725"
        ),
    )
    with (
        mock.patch(
            "crawler.guland_pw.evaluate_guland_coordinate_url",
            return_value=decision,
        ),
        mock.patch(
            "crawler.guland_pw.raw_coordinate_fields",
            return_value={
                "source_lat": decision.lat,
                "source_lng": decision.lng,
                "source_coordinate_url": decision.sanitized_url,
                "source_coordinate_provider": "guland_directions",
                "source_coordinate_captured_at": "2026-07-30T12:34:56+07:00",
            },
        ),
    ):
        record = crawler._build_record(card, {})

    assert record["source_lat"] == 11.028099613958
    assert record["source_lng"] == 106.6206724626
    assert record["source_coordinate_provider"] == "guland_directions"
    assert record["ward"] == "Tân An"


def test_build_record_keeps_listing_when_coordinate_is_invalid():
    crawler = GulandCrawler()
    card = {
        "url": "https://guland.vn/post/dat-tan-an-1231140",
        "source_list_url": (
            "https://guland.vn/mua-ban-dat-tho-cu-"
            "phuong-tan-an-thanh-pho-thu-dau-mot-binh-duong"
        ),
        "post_id": "1231140",
        "title": "Bán đất Tân An",
        "price_raw": "2 tỷ",
        "area_raw": "100 m²",
        "pm2_raw": "20 tr/m²",
        "source_coordinate_url": (
            "https://www.google.com/maps/search/"
            "?api=1&query=110.99336%2C106.655556689"
        ),
    }
    decision = mock.Mock(
        status="invalid",
        reason="invalid_lat_lng_order",
        lat=None,
        lng=None,
        sanitized_url="",
    )
    with mock.patch(
        "crawler.guland_pw.evaluate_guland_coordinate_url",
        return_value=decision,
    ):
        record = crawler._build_record(card, {})

    assert record["url"].endswith("-1231140")
    assert "source_lat" not in record
    assert "source_lng" not in record
