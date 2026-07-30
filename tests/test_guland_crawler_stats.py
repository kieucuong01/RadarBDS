from unittest import mock

from crawler.guland_pw import GulandCrawler


def test_guland_counts_fetched_cards_before_filtering_existing_urls(monkeypatch):
    crawler = GulandCrawler()
    crawler._stats = {"fetched": 0, "new": 0, "skipped": 0, "errors": 0, "error_details": []}
    cards = [
        {"url": "https://guland.vn/post/a-1", "title": "A"},
        {"url": "https://guland.vn/post/b-2", "title": "B"},
        {"url": "https://guland.vn/post/c-3", "title": "C"},
    ]

    monkeypatch.setattr(crawler, "_scroll_all_cards", lambda page, base_url, incremental: cards)
    monkeypatch.setattr(crawler, "url_exists", lambda url: url.endswith("b-2"))
    monkeypatch.setattr(crawler, "_fetch_details_batch", lambda page, urls: {url: {} for url in urls})
    monkeypatch.setattr(
        crawler,
        "_build_record",
        lambda card, detail: {"title": card["title"], "price_ty": 1.0, "area_m2": 100.0},
    )
    monkeypatch.setattr(crawler, "upsert_raw", lambda url, record: True)

    new_count = crawler._run_crawl(page=object(), base_url="https://guland.vn/test", incremental=True)

    assert new_count == 2
    assert crawler._stats["fetched"] == 3


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
