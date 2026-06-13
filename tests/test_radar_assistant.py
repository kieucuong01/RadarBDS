import shutil
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class RadarAssistantIntentTest(unittest.TestCase):
    def test_parse_budget_drop_filter(self):
        from services.assistant_intents import parse_assistant_intent

        parsed = parse_assistant_intent("Toi co 2 ty muon dat Tan An co giam gia")

        self.assertEqual(parsed["intent"], "build_filter")
        self.assertEqual(parsed["entities"]["price_max_ty"], 2.0)
        self.assertEqual(parsed["entities"]["wards"], ["Tân An"])
        self.assertEqual(parsed["entities"]["prop_types"], ["dat_nen"])
        self.assertTrue(parsed["entities"]["only_drops"])
        self.assertEqual(parsed["filter"]["mos_min"], 10)

    def test_parse_listing_specific_redirect(self):
        from services.assistant_intents import parse_assistant_intent

        parsed = parse_assistant_intent("Tin 52480 dang mua khong?")

        self.assertEqual(parsed["intent"], "listing_specific_redirect")
        self.assertEqual(parsed["entities"]["listing_id"], 52480)


class RadarAssistantApiTest(unittest.TestCase):
    def setUp(self):
        from db import connection
        from db.schema import init_schema
        import app as app_module

        self.tmpdir = Path(tempfile.mkdtemp())
        self.db_path = self.tmpdir / "radar_assistant.db"
        self.token = uuid.uuid4().hex
        self.url_prefix = f"https://assistant-{self.token}.test"
        self.ward = f"AssistantWard{self.token[:8]}"
        self.user_identifier = f"assistant-free-{self.token}@example.test"
        self.session_token = f"assistant-free-token-{self.token}"
        self.listing_ids = []

        connection.close_all()
        self.patches = [
            mock.patch.object(connection, "DB_PATH", self.db_path),
            mock.patch.object(app_module.db_mod, "DB_PATH", self.db_path),
        ]
        for patcher in self.patches:
            patcher.start()

        init_schema()
        self._delete_test_rows()
        self.client = app_module.app.test_client()
        self.signal_id = self._seed_signal("Assistant test signal")

    def tearDown(self):
        from db import connection

        self._delete_test_rows()
        connection.close_all()
        for patcher in reversed(self.patches):
            patcher.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _delete_test_rows(self):
        from db.connection import get_conn

        with get_conn() as conn:
            existing_tables = {
                r["table_name"] for r in conn.execute(
                    """
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema='public'
                      AND table_name IN ('assistant_feedback','assistant_messages','assistant_sessions','assistant_user_profiles')
                    """
                ).fetchall()
            }
            user_rows = conn.execute(
                "SELECT id FROM users WHERE identifier = ?",
                (self.user_identifier,),
            ).fetchall()
            user_ids = {r["id"] for r in user_rows}
            if "assistant_sessions" in existing_tables:
                session_rows = conn.execute(
                    """
                    SELECT id FROM assistant_sessions
                    WHERE session_token LIKE ?
                       OR session_token = ?
                    """,
                    (f"asst-{self.token}%", f"asst-{self.token}-guest"),
                ).fetchall()
                session_ids = {r["id"] for r in session_rows}
                if user_ids:
                    placeholders = ",".join("?" * len(user_ids))
                    rows_by_user = conn.execute(
                        f"SELECT id FROM assistant_sessions WHERE user_id IN ({placeholders})",
                        list(user_ids),
                    ).fetchall()
                    session_ids.update(r["id"] for r in rows_by_user)
                if session_ids:
                    placeholders = ",".join("?" * len(session_ids))
                    params = list(session_ids)
                    if "assistant_feedback" in existing_tables:
                        conn.execute(
                            f"""
                            DELETE FROM assistant_feedback
                            WHERE message_id IN (
                                SELECT id FROM assistant_messages WHERE session_id IN ({placeholders})
                            )
                            """,
                            params,
                        )
                    if "assistant_messages" in existing_tables:
                        conn.execute(f"DELETE FROM assistant_messages WHERE session_id IN ({placeholders})", params)
                    conn.execute(f"DELETE FROM assistant_sessions WHERE id IN ({placeholders})", params)
            if user_ids and "assistant_user_profiles" in existing_tables:
                placeholders = ",".join("?" * len(user_ids))
                conn.execute(f"DELETE FROM assistant_user_profiles WHERE user_id IN ({placeholders})", list(user_ids))
            conn.execute("DELETE FROM user_sessions WHERE token = ?", (self.session_token,))
            conn.execute("DELETE FROM users WHERE identifier = ?", (self.user_identifier,))
            rows = conn.execute(
                "SELECT id FROM listings WHERE url LIKE ?",
                (f"{self.url_prefix}%",),
            ).fetchall()
            ids = {r["id"] for r in rows}
            ids.update(self.listing_ids)
            if ids:
                placeholders = ",".join("?" * len(ids))
                params = list(ids)
                conn.execute(f"DELETE FROM ai_deal_review WHERE listing_id IN ({placeholders})", params)
                conn.execute(f"DELETE FROM ai_training_feedback WHERE listing_id IN ({placeholders})", params)
                conn.execute(f"DELETE FROM valuation_shadow_results WHERE listing_id IN ({placeholders})", params)
                conn.execute(f"DELETE FROM valuation_results WHERE listing_id IN ({placeholders})", params)
                conn.execute(f"DELETE FROM listing_images WHERE listing_id IN ({placeholders})", params)
                conn.execute(f"DELETE FROM listings WHERE id IN ({placeholders})", params)

    def _seed_signal(self, title):
        from db.connection import get_conn

        with get_conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO listings (
                    source, source_id, url, title, description, ward,
                    area_m2, property_type, price_ty, price_per_m2,
                    price_dropped, probably_sold, possibly_duplicate,
                    posted_at, crawled_at
                ) VALUES (
                    'facebook', ?, ?, ?, 'Assistant listing description',
                    ?, 100, 'dat_nen', 2.0, 20.0,
                    1, 0, 0, datetime('now'), datetime('now')
                )
                """,
                (f"assistant-{self.token}", f"{self.url_prefix}/signal", title, self.ward),
            )
            listing_id = cur.lastrowid
            self.listing_ids.append(listing_id)
            conn.execute(
                """
                INSERT INTO valuation_results (
                    listing_id, fair_ppm2, actual_ppm2, mos_pct,
                    is_signal, signal_score
                ) VALUES (?, 30.0, 20.0, 33.3, 1, 80)
                """,
                (listing_id,),
            )
            run_id = conn.execute(
                """
                INSERT INTO valuation_model_runs (model_name, model_version, status)
                VALUES ('median_road_tier', 'median_road_tier_v1', 'complete')
                """
            ).lastrowid
            conn.execute(
                """
                INSERT INTO valuation_shadow_results (
                    model_run_id, listing_id, fair_ppm2, actual_ppm2, mos_pct,
                    is_signal, signal_score, source_quality_flags
                ) VALUES (?, ?, 30.0, 20.0, 33.3, 1, 80, '')
                """,
                (run_id, listing_id),
            )
            return listing_id

    def _login_as_free(self):
        from auth.core import SESSION_COOKIE_NAME
        from db.connection import get_conn

        with get_conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO users (identifier, identifier_type, password_hash, tier)
                VALUES (?, 'email', 'hash', 'free')
                """,
                (self.user_identifier,),
            )
            conn.execute(
                """
                INSERT INTO user_sessions (token, user_id, expires_at)
                VALUES (?, ?, '2099-01-01T00:00:00')
                """,
                (self.session_token, cur.lastrowid),
            )
        try:
            self.client.set_cookie(SESSION_COOKIE_NAME, self.session_token)
        except TypeError:
            self.client.set_cookie("localhost", SESSION_COOKIE_NAME, self.session_token)

    def test_chat_build_filter_returns_action_and_logs_without_training_feedback(self):
        response = self.client.post(
            "/api/chat",
            json={
                "message": "Toi co 2 ty muon dat Tan An co giam gia",
                "session_id": f"asst-{self.token}-guest",
            },
        )

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["intent"], "build_filter")
        action = data["actions"][0]
        self.assertEqual(action["type"], "apply_filter")
        self.assertEqual(action["filter"]["price_max"], 2.0)
        self.assertEqual(action["filter"]["ward"], ["Tân An"])
        self.assertEqual(action["filter"]["property_type"], ["dat_nen"])
        self.assertEqual(action["filter"]["mos_min"], 10)
        self.assertTrue(action["filter"]["only_drops"])

        from db.connection import get_conn

        with get_conn() as conn:
            placeholders = ",".join("?" * len(self.listing_ids))
            training_count = conn.execute(
                f"SELECT COUNT(*) FROM ai_training_feedback WHERE listing_id IN ({placeholders})",
                list(self.listing_ids),
            ).fetchone()[0]
            message_count = conn.execute(
                """
                SELECT COUNT(*) AS n
                FROM assistant_messages m
                JOIN assistant_sessions s ON s.id = m.session_id
                WHERE s.session_token = ?
                """,
                (f"asst-{self.token}-guest",),
            ).fetchone()[0]
        self.assertEqual(training_count, 0)
        self.assertGreaterEqual(message_count, 2)

    def test_chat_watchlist_and_lead_actions(self):
        self._login_as_free()

        watch = self.client.post(
            "/api/chat",
            json={"message": "Tao watchlist Tan An duoi 3 ty MOS 15%"},
        )
        self.assertEqual(watch.status_code, 200)
        watch_data = watch.get_json()
        self.assertEqual(watch_data["intent"], "watchlist_create")
        self.assertEqual(watch_data["actions"][0]["type"], "open_watchlist")
        self.assertEqual(watch_data["actions"][0]["filter"]["price_max"], 3.0)
        self.assertEqual(watch_data["actions"][0]["filter"]["mos_min"], 15)

        lead = self.client.post("/api/chat", json={"message": "Muon di xem dat"})
        self.assertEqual(lead.status_code, 200)
        lead_data = lead.get_json()
        self.assertEqual(lead_data["intent"], "lead_intent")
        self.assertEqual(lead_data["actions"][0]["type"], "open_lead")

    def test_chat_listing_specific_redirect(self):
        response = self.client.post(
            "/api/chat",
            json={"message": f"Tin {self.signal_id} dang mua khong?"},
        )

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["intent"], "listing_specific_redirect")
        self.assertEqual(data["actions"][0]["type"], "open_listing_memo")
        self.assertEqual(data["actions"][0]["listing_id"], self.signal_id)
        self.assertIn("Cố vấn", data["answer"])


if __name__ == "__main__":
    unittest.main()
