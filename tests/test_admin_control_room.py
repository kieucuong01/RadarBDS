import shutil
import sys
import tempfile
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class AdminControlRoomGateTest(unittest.TestCase):
    def setUp(self):
        from db import connection
        from db.schema import init_schema
        import app as app_module

        self.tmpdir = Path(tempfile.mkdtemp())
        self.db_path = self.tmpdir / "radar_admin_gate.db"
        self.admin_identifier = f"admin-{uuid.uuid4().hex}@example.test"
        self.admin_token = f"admin-control-room-token-{uuid.uuid4().hex}"
        connection.close_all()
        self.patches = [
            mock.patch.object(connection, "DB_PATH", self.db_path),
            mock.patch.object(app_module.db_mod, "DB_PATH", self.db_path),
        ]
        for patcher in self.patches:
            patcher.start()

        init_schema()
        self.client = app_module.app.test_client()

    def tearDown(self):
        from db import connection
        from db.connection import get_conn

        try:
            with get_conn() as conn:
                conn.execute("DELETE FROM user_sessions WHERE token = ?", (self.admin_token,))
                conn.execute("DELETE FROM users WHERE identifier = ?", (self.admin_identifier,))
                conn.execute("DELETE FROM listings WHERE url LIKE ?", ("https://example.test/%",))
                conn.execute("DELETE FROM raw_listings WHERE url LIKE ?", ("https://example.test/%",))
                conn.execute("DELETE FROM crawl_runs WHERE area LIKE ?", ("ops-test-%",))
        except Exception:
            pass

        connection.close_all()
        for patcher in reversed(self.patches):
            patcher.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _login_as_admin(self):
        from auth.core import SESSION_COOKIE_NAME
        from db.connection import get_conn

        with get_conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO users (identifier, identifier_type, password_hash, tier)
                VALUES (?, 'email', 'hash', 'admin')
                """,
                (self.admin_identifier,),
            )
            conn.execute(
                """
                INSERT INTO user_sessions (token, user_id, expires_at)
                VALUES (?, ?, '2099-01-01T00:00:00')
                """,
                (self.admin_token, cur.lastrowid),
            )
        try:
            self.client.set_cookie(SESSION_COOKIE_NAME, self.admin_token)
        except TypeError:
            self.client.set_cookie("localhost", SESSION_COOKIE_NAME, self.admin_token)

    def test_guest_control_room_renders_login_modal_gate(self):
        response = self.client.get("/admin/control-room")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('id="authModal"', html)
        self.assertIn("Đăng nhập admin", html)
        self.assertIn("js/auth.js", html)
        self.assertNotIn("js/admin.js", html)

    def test_guest_admin_api_still_requires_admin(self):
        response = self.client.get("/admin/api/users")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["error"], "admin_required")

    def test_admin_session_loads_control_room_workspace(self):
        self._login_as_admin()

        response = self.client.get("/admin/control-room")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("js/admin.js", html)
        self.assertNotIn('id="authModal"', html)

    def test_ai_training_requires_explicit_valuation_choice_in_js(self):
        js = (Path(__file__).resolve().parent.parent / "static/js/admin.js").read_text(
            encoding="utf-8"
        )

        self.assertNotIn(
            'class="chip active" data-card="${cid}" data-group="valuation" data-value="cheap_real"',
            js,
        )
        self.assertIn("if (extractionOk && !valuation)", js)

    def test_admin_js_has_loading_toast_feedback_for_actions(self):
        root = Path(__file__).resolve().parent.parent
        js = (root / "static/js/admin.js").read_text(encoding="utf-8")
        css = (root / "static/css/admin.css").read_text(encoding="utf-8")

        self.assertIn("function showAdminToast", js)
        self.assertIn("async function withAdminToast", js)
        self.assertIn("adminToastDepth", js)
        self.assertIn("Dang xu ly tac vu", js)
        self.assertIn("facebook-crawl/jobs", js)
        self.assertIn("Fetched ${Number(crawl.fetched || 0)}", js)
        self.assertIn("Reprocess new ${Number(reprocess.new || 0)}", js)
        self.assertIn(".admin-toast-root", css)
        self.assertIn(".admin-toast.loading", css)

    def test_admin_manual_first_crawl_allows_900_post_limit(self):
        import app as app_module

        self._login_as_admin()

        class FakeThread:
            def __init__(self, target=None, args=(), daemon=None):
                self.target = target
                self.args = args
                self.daemon = daemon

            def start(self):
                return None

        with app_module.FACEBOOK_CRAWL_LOCK:
            app_module.FACEBOOK_CRAWL_JOBS.clear()
            app_module.FACEBOOK_CRAWL_JOB_ORDER.clear()

        with mock.patch.object(app_module.threading, "Thread", FakeThread):
            response = self.client.post(
                "/admin/api/facebook-crawl/run",
                json={
                    "url": "https://www.facebook.com/nhadatkhanhmy",
                    "mode": "first",
                    "limit": 900,
                    "download_images": False,
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["job"]["limit"], 900)

    def test_admin_crawl_config_includes_ops_summary(self):
        import app as app_module
        from db.connection import get_conn

        self._login_as_admin()
        token = uuid.uuid4().hex[:8]
        area = f"ops-test-{token}"
        started_ok = f"2099-01-01T00:{int(token[:2], 16) % 50:02d}:00"
        started_err = f"2099-01-01T00:{int(token[:2], 16) % 50:02d}:30"
        with get_conn() as conn:
            raw = conn.execute(
                """
                INSERT INTO raw_listings (source, url, raw_json)
                VALUES (?, ?, ?)
                """,
                ("facebook", f"https://example.test/{uuid.uuid4().hex}", "{}"),
            )
            listing = conn.execute(
                """
                INSERT INTO listings (
                    raw_id, source, url, title, area, property_type,
                    price_ty, price_per_m2, area_m2
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    raw.lastrowid,
                    "facebook",
                    f"https://example.test/listing/{uuid.uuid4().hex}",
                    "Signal seed",
                    "Ben Cat",
                    "dat",
                    1.0,
                    10.0,
                    100.0,
                ),
            )
            conn.execute(
                """
                INSERT INTO valuation_results (listing_id, fair_ppm2, actual_ppm2, mos_pct, is_signal)
                VALUES (?, 10, 7, 30, 1)
                """,
                (listing.lastrowid,),
            )
            conn.execute(
                """
                INSERT INTO crawl_runs (
                    source, area, n_fetched, n_new, n_updated, n_skipped,
                    status, error_msg, started_at, finished_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "guland",
                    area,
                    12,
                    4,
                    2,
                    1,
                    "done",
                    "",
                    started_ok,
                    "2099-01-01T00:59:00",
                ),
            )
            conn.execute(
                """
                INSERT INTO crawl_runs (
                    source, area, n_fetched, n_new, n_updated, n_skipped,
                    status, error_msg, started_at, finished_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "batdongsan",
                    area,
                    0,
                    0,
                    0,
                    0,
                    "error",
                    "Cloudflare",
                    started_err,
                    "2099-01-01T00:58:00",
                ),
            )

        with mock.patch.object(app_module, "_daily_crawl_schedule_status", return_value={
            "task_name": "RadarBDS_DailyCrawl",
            "installed": True,
            "state": "Ready",
            "next_run_time": "5/27/2026 9:00:00 PM",
            "last_run_time": "5/26/2026 9:00:00 PM",
            "last_result": "0",
            "run_time": "21:00",
            "task_to_run": "cmd /c crawl-daily",
            "error": "",
        }), mock.patch.object(app_module, "_active_radar_lock_blockers", return_value=[
            {"name": "reprocess", "pid": 1234, "state": "idle in transaction", "age_seconds": 90}
        ]):
            response = self.client.get("/admin/api/facebook-crawl/config")

        self.assertEqual(response.status_code, 200)
        ops = response.get_json()["summary"]["ops"]
        self.assertEqual(ops["schedule"]["run_time"], "21:00")
        self.assertEqual(ops["last_run"]["source"], "batdongsan")
        self.assertEqual(ops["last_24h"]["new"], 4)
        self.assertGreaterEqual(ops["signal_count"], 1)
        self.assertEqual(ops["source_errors"][0]["source"], "batdongsan")
        self.assertEqual(ops["lock_blockers"][0]["name"], "reprocess")

    def test_admin_js_renders_crawl_ops_panel(self):
        root = Path(__file__).resolve().parent.parent
        js = (root / "static/js/admin.js").read_text(encoding="utf-8")
        html = (root / "templates/admin_control_room.html").read_text(encoding="utf-8")
        css = (root / "static/css/admin.css").read_text(encoding="utf-8")

        self.assertIn('id="crawlOpsPanel"', html)
        self.assertIn("function renderCrawlOps", js)
        self.assertIn("source_errors", js)
        self.assertIn("lock_blockers", js)
        self.assertIn("RadarBDS_DailyCrawl", js)
        self.assertIn(".crawl-ops-panel", css)

    def test_admin_crawl_reprocesses_only_refreshed_raw_ids(self):
        import app as app_module
        import cli.crawlers as crawlers
        import cleansing.reprocess as reprocess
        import db.connection as connection

        @contextmanager
        def fake_lock(_name):
            yield

        job_id = f"job-{uuid.uuid4().hex}"
        with app_module.FACEBOOK_CRAWL_LOCK:
            app_module.FACEBOOK_CRAWL_JOBS[job_id] = {
                "id": job_id,
                "status": "queued",
                "stage": "queued",
                "mode": "daily",
                "profile_url": "https://www.facebook.com/nhadatkhanhmy",
                "broker_name": "Duy Khánh bds",
                "city": "Thủ Dầu Một",
                "limit": 30,
                "days": 7,
                "download_images": False,
                "stats": {},
                "logs": [],
            }
            app_module.FACEBOOK_CRAWL_JOB_ORDER.append(job_id)

        calls = {}

        def fake_crawl_to_raw(**_kwargs):
            return {
                "fetched": 12,
                "inserted": 0,
                "skipped": 0,
                "irrelevant": 0,
                "out_of_area": 0,
                "range_filtered": 0,
                "refreshed_images": 12,
                "refreshed_raw_ids": [101, 102, 103],
            }

        def fake_reprocess(**kwargs):
            calls.update(kwargs)
            return {"listings": {"processed_ids": [1, 2, 3]}, "valuation": {"total": 3}}

        with mock.patch.object(connection, "advisory_lock", fake_lock), \
             mock.patch.object(crawlers, "_facebook_crawl_to_raw", side_effect=fake_crawl_to_raw), \
             mock.patch.object(reprocess, "run_full_reprocess", side_effect=fake_reprocess):
            app_module._run_admin_facebook_crawl_job(job_id)

        self.assertEqual(calls.get("source"), "facebook")
        self.assertEqual(calls.get("raw_ids"), [101, 102, 103])
        self.assertFalse(calls.get("full", False))
        self.assertEqual(app_module.FACEBOOK_CRAWL_JOBS[job_id]["status"], "succeeded")
        logs = "\n".join(app_module.FACEBOOK_CRAWL_JOBS[job_id]["logs"])
        self.assertIn("fetched=12", logs)
        self.assertIn("skipped=0", logs)
        self.assertIn("Reprocess xong: processed=3, new=0, updated=0, skipped=0", logs)
