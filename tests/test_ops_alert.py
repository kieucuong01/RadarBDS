import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class OpsAlertTest(unittest.TestCase):
    def test_crawl_daily_no_new_records_still_runs_ops_alert(self):
        from contextlib import contextmanager
        import cli.crawlers as crawlers

        class FakeConn:
            def execute(self, _sql, _params=None):
                return SimpleNamespace(fetchone=lambda: ["2026-05-26T00:00:00"])

        @contextmanager
        def fake_get_conn():
            yield FakeConn()

        class FakeCrawler:
            SOURCE_NAME = "guland"

            def run(self, mode, headless):
                return {"new": 0, "skipped": 0, "errors": 0}

        import cleansing.download_images as download_module

        fake_download = mock.Mock(return_value=0)
        args = SimpleNamespace(source=None, visible=False, no_reprocess=False, no_alert=False)

        with mock.patch.object(crawlers, "init_schema", return_value=None), \
             mock.patch.object(crawlers, "_get_crawlers", return_value=[FakeCrawler()]), \
             mock.patch.object(crawlers, "_facebook_crawl_to_raw", return_value={
                 "fetched": 0,
                 "inserted": 0,
                 "skipped": 0,
                 "irrelevant": 0,
                 "refreshed_images": 0,
                 "out_of_area": 0,
             }), \
             mock.patch.object(crawlers, "get_conn", fake_get_conn), \
             mock.patch.object(crawlers, "_clean_broker_images_after_download", return_value={}), \
             mock.patch.object(crawlers, "_maybe_send_ops_alert") as ops_alert, \
             mock.patch.object(crawlers, "_prewarm_dashboard_cache") as prewarm, \
             mock.patch.object(download_module, "download_images", fake_download):
            crawlers._cmd_crawl(args, mode="incremental")

        fake_download.assert_called_once_with(limit=200)
        ops_alert.assert_called_once_with("2026-05-26T00:00:00", [])
        prewarm.assert_called_once_with()

    def test_send_ops_alert_noop_when_chat_id_missing(self):
        from alerts import ops

        with mock.patch.dict(os.environ, {"OPS_ALERT_CHAT_ID": ""}, clear=False):
            self.assertFalse(ops.send_ops_alert("anything"))

    def test_send_ops_alert_routes_to_send_message_to_with_prefix(self):
        from alerts import ops

        with mock.patch.dict(os.environ, {"OPS_ALERT_CHAT_ID": "999"}, clear=False), \
             mock.patch("alerts.telegram.send_message_to", return_value=True) as send:
            self.assertTrue(ops.send_ops_alert("boom"))
            send.assert_called_once()
            args, _ = send.call_args
            self.assertEqual(args[0], "999")
            self.assertIn("Radar BDS OPS", args[1])
            self.assertIn("boom", args[1])

    def test_summarize_empty_rows_is_unhealthy(self):
        from alerts.ops import summarize_crawl_health

        unhealthy, msg = summarize_crawl_health([])
        self.assertTrue(unhealthy)
        self.assertIn("Không có run", msg)

    def test_summarize_flags_error_status(self):
        from alerts.ops import summarize_crawl_health

        row = {"source": "guland", "status": "error", "n_fetched": 0,
               "n_new": 0, "error_msg": "Cloudflare 403"}
        unhealthy, msg = summarize_crawl_health([row])
        self.assertTrue(unhealthy)
        self.assertIn("❌ ERROR guland", msg)
        self.assertIn("Cloudflare 403", msg)

    def test_summarize_flags_zero_fetched(self):
        from alerts.ops import summarize_crawl_health

        row = {"source": "batdongsan", "status": "done", "n_fetched": 0,
               "n_new": 0, "error_msg": ""}
        unhealthy, msg = summarize_crawl_health([row])
        self.assertTrue(unhealthy)
        self.assertIn("⚠️ ZERO FETCHED batdongsan", msg)

    def test_summarize_treats_new_records_as_healthy_even_if_fetched_missing(self):
        from alerts.ops import summarize_crawl_health

        row = {"source": "guland", "status": "done", "n_fetched": 0,
               "n_new": 29, "error_msg": ""}
        unhealthy, msg = summarize_crawl_health([row])
        self.assertFalse(unhealthy)
        self.assertIn("OK guland", msg)

    def test_summarize_healthy_run(self):
        from alerts.ops import summarize_crawl_health

        rows = [
            {"source": "guland", "status": "done", "n_fetched": 120,
             "n_new": 30, "error_msg": ""},
        ]
        unhealthy, msg = summarize_crawl_health(rows)
        self.assertFalse(unhealthy)
        self.assertIn("✅ OK guland", msg)


if __name__ == "__main__":
    unittest.main()
