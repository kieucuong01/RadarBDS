from types import SimpleNamespace
from unittest import mock

import cli.crawlers as crawlers


class _FakeDbContext:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, *_args, **_kwargs):
        return self

    def fetchone(self):
        return ["2026-06-02 21:00:00"]


class _FakeCrawler:
    SOURCE_NAME = "fake"

    def run(self, mode, headless=True):
        return {"new": 0, "skipped": 0, "errors": 0}


class _FailingSecondaryCrawler:
    SOURCE_NAME = "secondary"

    def __init__(self, events):
        self.events = events

    def run(self, mode, headless=True):
        self.events.append("secondary")
        raise RuntimeError("secondary crawler should not block facebook")


def test_daily_facebook_crawl_uses_profile_daily_limits():
    captured = {}

    def fake_facebook_crawl_to_raw(**kwargs):
        captured.update(kwargs)
        return {
            "fetched": 1,
            "inserted": 1,
            "skipped": 0,
            "irrelevant": 0,
            "out_of_area": 0,
            "refreshed_images": 0,
        }

    args = SimpleNamespace(
        source=None,
        visible=False,
        no_reprocess=True,
        no_alert=True,
    )

    with mock.patch.object(crawlers, "init_schema"), \
         mock.patch.object(crawlers, "get_conn", return_value=_FakeDbContext()), \
         mock.patch("db.crawl_runs.start_crawl_run", return_value=123) as start_run, \
         mock.patch("db.crawl_runs.finish_crawl_run") as finish_run, \
         mock.patch.object(crawlers, "_get_crawlers", return_value=[_FakeCrawler()]), \
         mock.patch.object(crawlers, "_facebook_crawl_to_raw", side_effect=fake_facebook_crawl_to_raw), \
         mock.patch.object(crawlers, "cmd_export_raw"), \
         mock.patch.object(crawlers, "_maybe_send_ops_alert"):
        crawlers._cmd_crawl(args, mode="incremental")

    assert captured["mode"] == "incremental"
    assert captured.get("limit_override") is None
    assert captured["scheduled_only"] is True
    start_run.assert_not_called()
    finish_run.assert_not_called()


def test_daily_crawl_reprocesses_facebook_without_running_secondary_sources():
    events = []
    download_calls = {}

    def fake_facebook_crawl_to_raw(**_kwargs):
        events.append("facebook")
        return {
            "fetched": 1,
            "inserted": 1,
            "skipped": 0,
            "irrelevant": 0,
            "out_of_area": 0,
            "refreshed_images": 0,
        }

    def fake_reprocess():
        events.append("reprocess")
        return {
            "listings": {"new": 1, "updated": 0},
            "valuation": {"total": 1, "signals": 1, "outliers": 0},
        }

    args = SimpleNamespace(
        source=None,
        visible=False,
        no_reprocess=False,
        no_alert=True,
    )

    with mock.patch.object(crawlers, "init_schema"), \
         mock.patch.object(crawlers, "get_conn", return_value=_FakeDbContext()), \
         mock.patch.object(crawlers, "_get_crawlers", return_value=[_FailingSecondaryCrawler(events)]), \
         mock.patch.object(crawlers, "_facebook_crawl_to_raw", side_effect=fake_facebook_crawl_to_raw), \
         mock.patch("cleansing.reprocess.run_full_reprocess", side_effect=fake_reprocess), \
         mock.patch("cleansing.download_images.download_images", side_effect=lambda **kwargs: download_calls.update(kwargs)), \
         mock.patch.object(crawlers, "_clean_broker_images_after_download"), \
         mock.patch.object(crawlers, "cmd_export_raw"), \
         mock.patch.object(crawlers, "_maybe_send_ops_alert"), \
         mock.patch.object(crawlers, "_prewarm_dashboard_cache"):
        crawlers._cmd_crawl(args, mode="incremental")

    assert events == ["facebook", "reprocess"]
    assert download_calls == {"limit": 500}


def test_facebook_crawl_records_health_row():
    def fake_build_record(post):
        return {
            "url": post["url"],
            "post_id": post["post_id"],
            "contact_phone": "",
            "imgs": post.get("imgs") or [],
        }

    class _FakeFacebookCrawler:
        def crawl_all(self, *_args, **_kwargs):
            return [
                {"url": "https://facebook.test/1", "post_id": "1", "text": "ban dat 100m2", "imgs": []},
                {"url": "https://facebook.test/2", "post_id": "2", "text": "tin linh tinh", "imgs": []},
            ]

    with mock.patch("crawler.facebook_apify.FacebookApifyCrawler", return_value=_FakeFacebookCrawler()), \
         mock.patch("crawler.facebook_apify.load_profiles", return_value=[{"url": "https://facebook.test/a"}]), \
         mock.patch("crawler.facebook_chrome.is_relevant", side_effect=lambda text: "ban dat" in text), \
         mock.patch("crawler.facebook_chrome.build_record", side_effect=fake_build_record), \
         mock.patch("config.area_profiles.post_mentions_other_city", return_value=False), \
         mock.patch("db.crawl_runs.start_crawl_run", return_value=123) as start_run, \
         mock.patch("db.crawl_runs.finish_crawl_run") as finish_run, \
         mock.patch.object(crawlers, "insert_raw", return_value=456):
        stats = crawlers._facebook_crawl_to_raw(mode="incremental")

    assert stats["fetched"] == 2
    assert stats["inserted"] == 1
    start_run.assert_called_once_with("facebook", "all")
    finish_run.assert_called_once_with(123, {"fetched": 2, "new": 1, "skipped": 1})


def test_postprocess_downloads_processed_listing_images_first():
    calls = {}
    args = SimpleNamespace(no_reprocess=False)

    with mock.patch("cleansing.reprocess.run_full_reprocess", return_value={
            "listings": {"new": 2, "updated": 0, "processed_ids": [10, 20]},
            "valuation": {"total": 2, "signals": 0, "outliers": 0},
         }), \
         mock.patch("cleansing.download_images.download_images", side_effect=lambda **kwargs: calls.update(kwargs)), \
         mock.patch.object(crawlers, "_clean_broker_images_after_download"):
        assert crawlers._postprocess_crawl_batch(args, 2, source_filter="facebook", image_limit=500)

    assert calls == {"limit": 500, "listing_ids": [10, 20]}


def test_postprocess_skips_busy_image_lock_without_failing_crawl():
    args = SimpleNamespace(no_reprocess=False)

    with mock.patch("cleansing.reprocess.run_full_reprocess", return_value={
            "listings": {"new": 1, "updated": 0, "processed_ids": [10]},
            "valuation": {"total": 1, "signals": 0, "outliers": 0},
         }), \
         mock.patch(
             "cleansing.download_images.download_images",
             side_effect=RuntimeError("Another Radar BDS job is already running: download-images"),
         ), \
         mock.patch.object(crawlers, "_clean_broker_images_after_download") as clean:
        assert crawlers._postprocess_crawl_batch(args, 1, source_filter="facebook", image_limit=500)

    clean.assert_not_called()


def test_daily_primary_does_not_load_secondary_crawlers():
    args = SimpleNamespace(
        source=None,
        visible=False,
        no_reprocess=True,
        no_alert=True,
    )

    with mock.patch.object(crawlers, "init_schema"), \
         mock.patch.object(crawlers, "get_conn", return_value=_FakeDbContext()), \
         mock.patch.object(crawlers, "_get_crawlers", side_effect=AssertionError("secondary crawler loader should not run")), \
         mock.patch.object(crawlers, "_facebook_crawl_to_raw", return_value={
             "fetched": 0,
             "inserted": 0,
             "skipped": 0,
             "irrelevant": 0,
             "out_of_area": 0,
             "refreshed_images": 0,
         }), \
         mock.patch("cleansing.download_images.download_images"), \
         mock.patch.object(crawlers, "_clean_broker_images_after_download"), \
         mock.patch.object(crawlers, "_maybe_send_ops_alert"), \
         mock.patch.object(crawlers, "_prewarm_dashboard_cache"):
        crawlers._cmd_crawl(args, mode="incremental")


def test_secondary_crawl_limits_image_backfill():
    calls = {}

    class _NewCrawler:
        SOURCE_NAME = "guland"

        def run(self, mode, headless=True):
            return {"new": 1, "skipped": 0, "errors": 0}

    args = SimpleNamespace(
        source="guland",
        visible=False,
        no_reprocess=False,
        no_alert=True,
    )

    with mock.patch.object(crawlers, "init_schema"), \
         mock.patch.object(crawlers, "get_conn", return_value=_FakeDbContext()), \
         mock.patch.object(crawlers, "_get_crawlers", return_value=[_NewCrawler()]), \
         mock.patch("cleansing.reprocess.run_full_reprocess", return_value={
             "listings": {"new": 1, "updated": 0},
             "valuation": {"total": 1, "signals": 0, "outliers": 0},
         }), \
         mock.patch("cleansing.download_images.download_images", side_effect=lambda **kwargs: calls.setdefault("download", kwargs)), \
         mock.patch.object(crawlers, "_clean_broker_images_after_download", side_effect=lambda **kwargs: calls.setdefault("clean", kwargs)), \
         mock.patch.object(crawlers, "cmd_export_raw"), \
         mock.patch.object(crawlers, "_maybe_send_ops_alert"), \
         mock.patch.object(crawlers, "_prewarm_dashboard_cache"):
        crawlers._cmd_crawl(args, mode="incremental")

    assert calls["download"] == {"limit": 500}
    assert calls["clean"] == {"source": "guland", "limit": 500}
