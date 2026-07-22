import sys
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class ValuationToolTest(unittest.TestCase):
    def setUp(self):
        from db import connection
        from db.schema import init_schema
        import app as app_module

        self.token = uuid.uuid4().hex
        self.url_prefix = f"https://valuation-tool-{self.token}.test"
        self.ward = f"ToolWard{self.token[:8]}"
        self.session_token = f"valuation-tool-free-{self.token}"
        self.user_identifier = f"valuation-tool-{self.token}@test.local"
        self.listing_ids = []
        connection.close_all()
        init_schema()
        self._delete_test_rows()
        self.client = app_module.app.test_client()
        self._seed_training_rows()

    def tearDown(self):
        from db import connection

        self._delete_test_rows()
        connection.close_all()

    def _delete_test_rows(self):
        from db.connection import get_conn

        with get_conn() as conn:
            conn.execute("DELETE FROM user_sessions WHERE token = ?", (self.session_token,))
            conn.execute("DELETE FROM users WHERE identifier = ?", (self.user_identifier,))
            rows = conn.execute(
                "SELECT id FROM listings WHERE url LIKE ?",
                (f"{self.url_prefix}%",),
            ).fetchall()
            ids = {r["id"] for r in rows}
            ids.update(self.listing_ids)
            if not ids:
                return
            placeholders = ",".join("?" * len(ids))
            params = list(ids)
            conn.execute(f"DELETE FROM price_history WHERE listing_id IN ({placeholders})", params)
            conn.execute(f"DELETE FROM valuation_results WHERE listing_id IN ({placeholders})", params)
            try:
                conn.execute(f"DELETE FROM valuation_shadow_results WHERE listing_id IN ({placeholders})", params)
            except Exception:
                pass
            conn.execute(f"DELETE FROM listing_images WHERE listing_id IN ({placeholders})", params)
            conn.execute(f"DELETE FROM listings WHERE id IN ({placeholders})", params)

    def _seed_training_rows(self):
        from db.connection import get_conn

        with get_conn() as conn:
            for idx in range(18):
                cur = conn.execute(
                    """
                    INSERT INTO listings (
                        source, source_id, url, title, description, area, ward,
                        property_type, tx_type, price_ty, price_per_m2, area_m2,
                        frontage_m, depth_m, road_type, road_tier, has_so,
                        probably_sold, is_blacklisted, review_hidden, crawled_at, posted_at
                    ) VALUES (
                        'facebook', ?, ?, 'Training tool listing', 'Training row',
                        'Bình Dương', ?, 'dat_nen', 'ban', ?, ?, 100,
                        5, 20, 'duong_nhua', 2, 1,
                        0, 0, 0, datetime('now'), datetime('now')
                    )
                    """,
                    (
                        f"valuation-tool-{self.token}-{idx}",
                        f"{self.url_prefix}/{idx}",
                        self.ward,
                        2.0 + (idx % 3) * 0.05,
                        20.0 + (idx % 3) * 0.5,
                    ),
                )
                self.listing_ids.append(cur.lastrowid)

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

    def test_guest_can_view_page_but_cannot_run_valuation(self):
        page = self.client.get("/dinh-gia-bds")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn("Định giá lô đất Bình Dương", html)
        self.assertIn("application/ld+json", html)
        self.assertIn("FAQPage", html)
        self.assertIn("valuation-tool-premium-first-form-20260722", html)
        self.assertIn("valuation-workspace", html)
        self.assertIn("Không cần nhập giá", html)

        response = self.client.post(
            "/api/valuation-tool/estimate",
            json={
                "ward": self.ward,
                "property_type": "dat_nen",
                "area_m2": 100,
                "road_tier": 2,
                "frontage_m": 5,
                "depth_m": 20,
                "has_so": True,
            },
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["error"], "tier_required")
        self.assertEqual(response.get_json()["required"], "free")

    def test_free_user_gets_estimate_from_project_valuation_engine(self):
        self._login_as_free()

        response = self.client.post(
            "/api/valuation-tool/estimate",
            json={
                "ward": self.ward,
                "property_type": "dat_nen",
                "area_m2": 100,
                "road_tier": 2,
                "frontage_m": 5,
                "depth_m": 20,
                "has_so": True,
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["estimate"]["ward"], self.ward)
        self.assertEqual(payload["estimate"]["property_type"], "dat_nen")
        self.assertGreater(payload["estimate"]["fair_ppm2"], 0)
        self.assertGreater(payload["estimate"]["fair_price_ty"], 0)
        self.assertIsNone(payload["estimate"]["input_ppm2"])
        self.assertIsNone(payload["estimate"]["mos_pct"])
        self.assertGreater(payload["estimate"]["segment_n"], 0)
        self.assertIn("basis=", payload["estimate"]["note"])

    def test_invalid_input_returns_validation_error(self):
        self._login_as_free()

        response = self.client.post(
            "/api/valuation-tool/estimate",
            json={"ward": self.ward, "property_type": "dat_nen", "area_m2": 0},
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.get_json()["error"], "validation_error")

    def test_valuation_tool_is_in_sitemap(self):
        response = self.client.get("/sitemap.xml")
        self.assertEqual(response.status_code, 200)
        self.assertIn("/dinh-gia-bds", response.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
