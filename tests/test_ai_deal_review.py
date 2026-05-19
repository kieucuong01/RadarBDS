import io
import json
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class AiDealReviewTest(unittest.TestCase):
    def setUp(self):
        from db import connection
        from db.schema import init_schema

        self.tmpdir = Path(tempfile.mkdtemp())
        self.db_path = self.tmpdir / "radar_ai_review.db"
        connection.close_all()
        self.db_patch = mock.patch.object(connection, "DB_PATH", self.db_path)
        self.db_patch.start()
        init_schema()

    def tearDown(self):
        from db import connection

        connection.close_all()
        self.db_patch.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    # ---- helpers -------------------------------------------------------
    def _insert_signal(self, *, url, ward="Phú Hòa", price_ty=2.0,
                       area_m2=80.0, signal_score=70, mos_pct=35.0):
        from db.connection import get_conn

        with get_conn() as conn:
            lid = conn.execute(
                """
                INSERT INTO listings (source, url, title, ward, property_type,
                    price_ty, area_m2, road_tier, has_so, crawled_at)
                VALUES ('guland', ?, 'Tin test', ?, 'dat_nen',
                        ?, ?, 1, 1, '2026-05-01T00:00:00')
                """,
                (url, ward, price_ty, area_m2),
            ).lastrowid
            conn.execute(
                """
                INSERT INTO valuation_results (listing_id, fair_ppm2,
                    actual_ppm2, mos_pct, is_signal, signal_score, n_segment)
                VALUES (?, 30.0, 20.0, ?, 1, ?, 25)
                """,
                (lid, mos_pct, signal_score),
            )
            return lid

    def _save_args(self, **kw):
        base = dict(id=None, verdict=None, confidence=None, reasoning=None,
                    red_flags=None, needs_map_check=False)
        base.update(kw)
        return SimpleNamespace(**base)

    def _run_save(self, **kw):
        from cli.review import cmd_review_save

        return cmd_review_save(self._save_args(**kw))

    def _run_queue(self, top=5, ward=None):
        from cli.review import cmd_review_queue

        buf = io.StringIO()
        with redirect_stdout(buf):
            cmd_review_queue(SimpleNamespace(top=top, ward=ward))
        return json.loads(buf.getvalue())

    def _count(self, table):
        from db.connection import get_conn

        with get_conn() as conn:
            return conn.execute(f"SELECT COUNT(*) c FROM {table}").fetchone()["c"]

    # ---- 1. idempotent schema -----------------------------------------
    def test_schema_idempotent(self):
        from db.connection import get_conn
        from db.schema import init_schema

        init_schema()  # second call must not raise
        with get_conn() as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name='ai_deal_review'"
            ).fetchone()
            self.assertIsNotNone(row)

    # ---- 2. review-save validation ------------------------------------
    def test_review_save_insert_and_validation(self):
        lid = self._insert_signal(url="https://t.test/1")
        self._run_save(id=lid, verdict="suspect", confidence=0.7,
                       reasoning="nghi mồi", red_flags="mồi;giá ảo",
                       needs_map_check=True)
        from db.connection import get_conn

        with get_conn() as conn:
            r = conn.execute(
                "SELECT * FROM ai_deal_review WHERE listing_id=?", (lid,)
            ).fetchone()
        self.assertEqual(r["verdict"], "suspect")
        self.assertEqual(r["needs_map_check"], 1)
        self.assertEqual(json.loads(r["red_flags"]), ["mồi", "giá ảo"])
        self.assertEqual(r["model"], "claude-code-interactive")

        with self.assertRaises(SystemExit):
            self._run_save(id=lid, verdict="bogus", reasoning="x")
        with self.assertRaises(SystemExit):
            self._run_save(id=lid, verdict="cheap_real",
                           confidence=1.5, reasoning="x")

    # ---- 3. review-queue excludes already reviewed --------------------
    def test_review_queue_excludes_reviewed(self):
        a = self._insert_signal(url="https://t.test/a")
        b = self._insert_signal(url="https://t.test/b")
        out = self._run_queue()
        self.assertEqual(out["count"], 2)

        self._run_save(id=a, verdict="cheap_real", confidence=0.8,
                       reasoning="rẻ thật")
        out2 = self._run_queue()
        self.assertEqual(out2["count"], 1)
        self.assertEqual(out2["items"][0]["listing_id"], b)
        self.assertIn("memo", out2["items"][0])

    # ---- 4. disagreement strict mapping -------------------------------
    def test_disagreement_strict(self):
        import app as app_module

        with mock.patch.object(app_module.db_mod, "DB_PATH", self.db_path):
            client = app_module.app.test_client()
            self._login_admin(client)

            cases = [
                ("correct", "suspect", True),
                ("maybe", "cheap_real", False),
                ("good", "cheap_real", False),
                ("bad", "cheap_real", True),
            ]
            ids = {}
            for human, ai, expected in cases:
                lid = self._insert_signal(url=f"https://t.test/d-{human}-{ai}")
                ids[lid] = (human, ai, expected)
                self._insert_human_label(lid, human)
                self._run_save(id=lid, verdict=ai, confidence=0.6,
                               reasoning="r")

            resp = client.get("/admin/api/ai-training/disagreements")
            self.assertEqual(resp.status_code, 200)
            shown = {it["id"] for it in resp.get_json()["items"]}
            for lid, (human, ai, expected) in ids.items():
                self.assertEqual(lid in shown, expected,
                                 f"{human}+{ai} expected shown={expected}")

    # ---- 5. anti-bias separation --------------------------------------
    def test_anti_bias_separation(self):
        import app as app_module

        lid = self._insert_signal(url="https://t.test/ab")
        # human label must NOT create ai_deal_review
        self._insert_human_label(lid, "bad", via_app=app_module)
        self.assertEqual(self._count("ai_deal_review"), 0)

        from db.connection import get_conn

        with get_conn() as conn:
            hidden_before = conn.execute(
                "SELECT COALESCE(review_hidden,0) h FROM listings WHERE id=?",
                (lid,),
            ).fetchone()["h"]

        # review-save must NOT touch ai_training_feedback / review_hidden
        before_fb = self._count("ai_training_feedback")
        self._run_save(id=lid, verdict="cheap_real", confidence=0.9,
                       reasoning="rẻ thật")
        self.assertEqual(self._count("ai_training_feedback"), before_fb)
        with get_conn() as conn:
            hidden_after = conn.execute(
                "SELECT COALESCE(review_hidden,0) h FROM listings WHERE id=?",
                (lid,),
            ).fetchone()["h"]
        self.assertEqual(hidden_before, hidden_after)

    # ---- shared admin helpers -----------------------------------------
    def _login_admin(self, client):
        from auth.core import SESSION_COOKIE_NAME
        from db.connection import get_conn

        token = "ai-review-admin-token"
        with get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO users (identifier, identifier_type, "
                "password_hash, tier) VALUES ('admin','email','h','admin')"
            )
            conn.execute(
                "INSERT INTO user_sessions (token, user_id, expires_at) "
                "VALUES (?, ?, '2099-01-01T00:00:00')",
                (token, cur.lastrowid),
            )
        try:
            client.set_cookie(SESSION_COOKIE_NAME, token)
        except TypeError:
            client.set_cookie("localhost", SESSION_COOKIE_NAME, token)

    def _insert_human_label(self, listing_id, verdict, via_app=None):
        if via_app is not None:
            with via_app.app.test_request_context():
                from db.connection import get_conn

                with get_conn() as conn:
                    via_app._save_ai_training_feedback(
                        conn, listing_id, {"verdict": verdict})
            return
        from db.connection import get_conn

        with get_conn() as conn:
            conn.execute(
                "INSERT INTO ai_training_feedback (listing_id, actor, "
                "verdict) VALUES (?, 'admin', ?)",
                (listing_id, verdict),
            )


if __name__ == "__main__":
    unittest.main()
