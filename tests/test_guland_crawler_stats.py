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
