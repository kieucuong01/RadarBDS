import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class OpsAlertTest(unittest.TestCase):
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
