import shutil
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class SourcePolicyTest(unittest.TestCase):
    def setUp(self):
        from db import connection
        from db.schema import init_schema
        import app as app_module

        self.tmpdir = Path(tempfile.mkdtemp())
        self.db_path = self.tmpdir / "radar_source_policy.db"
        self.token = uuid.uuid4().hex
        self.url_prefix = f"https://source-policy-{self.token}.test"
        self.ward = f"SourceWard{self.token[:8]}"
        self.admin_identifier = f"source-admin-{self.token}@example.test"
        self.admin_token = f"source-admin-token-{self.token}"
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
        self.facebook_id = self._seed_signal(
            source="facebook",
            title="Facebook source policy signal",
            source_id="fb",
        )
        self.guland_id = self._seed_signal(
            source="guland",
            title="Guland source policy signal",
            source_id="guland",
        )

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
            conn.execute("DELETE FROM user_sessions WHERE token = ?", (self.admin_token,))
            conn.execute("DELETE FROM users WHERE identifier = ?", (self.admin_identifier,))

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
            conn.execute(f"DELETE FROM listing_images WHERE listing_id IN ({placeholders})", params)
            conn.execute(f"DELETE FROM legal_verifications WHERE listing_id IN ({placeholders})", params)
            conn.execute(f"DELETE FROM listings WHERE id IN ({placeholders})", params)

    def _seed_signal(self, *, source, title, source_id, area_m2=100, price_ty=2.0):
        from db.connection import get_conn
        price_per_m2 = round(price_ty * 1000 / area_m2, 2) if area_m2 else None

        with get_conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO listings (
                    source, source_id, url, title, description, ward,
                    area_m2, property_type, price_ty, price_per_m2,
                    is_hot, price_dropped, suspicious_bait,
                    probably_sold, possibly_duplicate, posted_at, crawled_at
                ) VALUES (
                    ?, ?, ?, ?, 'Source policy listing',
                    ?, ?, 'dat_nen', ?, ?,
                    0, 0, 0, 0, 0, datetime('now'), datetime('now')
                )
                """,
                (
                    source,
                    f"{source_id}-{self.token}",
                    f"{self.url_prefix}/{source_id}",
                    title,
                    self.ward,
                    area_m2,
                    price_ty,
                    price_per_m2,
                ),
            )
            listing_id = cur.lastrowid
            self.listing_ids.append(listing_id)
            conn.execute(
                """
                INSERT INTO valuation_results (
                    listing_id, fair_ppm2, actual_ppm2, mos_pct,
                    is_signal, signal_score
                ) VALUES (?, 30.0, ?, 33.3, 1, 70)
                """,
                (listing_id, price_per_m2),
            )
            return listing_id

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

    def test_guest_source_query_is_forced_to_facebook(self):
        response = self.client.get(
            f"/api/signals?city=Khac&ward={self.ward}&source=guland&limit=10"
        )
        self.assertEqual(response.status_code, 200)

        payload = response.get_json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual([s["source"] for s in payload["signals"]], ["facebook"])
        self.assertEqual(payload["signals"][0]["title"], "Facebook source policy signal")

    def test_guest_dashboard_defaults_to_facebook_only(self):
        response = self.client.get(f"/api/dashboard?city=Khac&ward={self.ward}")
        self.assertEqual(response.status_code, 200)

        payload = response.get_json()
        self.assertEqual(payload["active_sources"], ["facebook"])
        self.assertEqual(payload["all_sources"], ["facebook"])
        self.assertEqual(payload["stats"]["total"], 1)
        self.assertEqual(payload["stats"]["signals"], 1)

    def test_admin_can_select_guland_source(self):
        self._login_as_admin()

        response = self.client.get(
            f"/api/signals?city=Khac&ward={self.ward}&source=guland&limit=10"
        )
        self.assertEqual(response.status_code, 200)

        payload = response.get_json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual([s["source"] for s in payload["signals"]], ["guland"])
        self.assertEqual(payload["signals"][0]["title"], "Guland source policy signal")

    def test_admin_default_source_is_facebook(self):
        self._login_as_admin()

        response = self.client.get(f"/api/signals?city=Khac&ward={self.ward}&limit=10")
        self.assertEqual(response.status_code, 200)

        payload = response.get_json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual([s["source"] for s in payload["signals"]], ["facebook"])

    def test_signal_feed_accepts_multiple_area_ranges(self):
        self._seed_signal(source="facebook", title="Area 200 signal", source_id="fb-area-200", area_m2=200, price_ty=2.0)
        self._seed_signal(source="facebook", title="Area 600 signal", source_id="fb-area-600", area_m2=600, price_ty=6.0)

        response = self.client.get(
            f"/api/signals?city=Khac&ward={self.ward}&area_range=150:500&area_range=500:&limit=20"
        )
        self.assertEqual(response.status_code, 200)

        titles = {row["title"] for row in response.get_json()["signals"]}
        self.assertNotIn("Facebook source policy signal", titles)
        self.assertIn("Area 200 signal", titles)
        self.assertIn("Area 600 signal", titles)

    def test_signal_feed_accepts_multiple_price_ranges(self):
        self._seed_signal(source="facebook", title="Price 0.5 signal", source_id="fb-price-low", area_m2=100, price_ty=0.5)
        self._seed_signal(source="facebook", title="Price 3 signal", source_id="fb-price-mid", area_m2=100, price_ty=3.0)
        self._seed_signal(source="facebook", title="Price 5 signal", source_id="fb-price-high", area_m2=100, price_ty=5.0)

        response = self.client.get(
            f"/api/signals?city=Khac&ward={self.ward}&price_range=:1&price_range=5:&limit=20"
        )
        self.assertEqual(response.status_code, 200)

        titles = {row["title"] for row in response.get_json()["signals"]}
        self.assertIn("Price 0.5 signal", titles)
        self.assertIn("Price 5 signal", titles)
        self.assertNotIn("Facebook source policy signal", titles)
        self.assertNotIn("Price 3 signal", titles)

    def test_source_filter_group_only_renders_for_admin(self):
        guest_html = self.client.get("/").get_data(as_text=True)
        self.assertNotIn("NGUỒN DỮ LIỆU", guest_html)
        self.assertNotIn('id="sourceFilters"', guest_html)

        self._login_as_admin()
        admin_html = self.client.get("/").get_data(as_text=True)

        self.assertIn("NGUỒN DỮ LIỆU", admin_html)
        self.assertIn('id="sourceFilters"', admin_html)
        self.assertRegex(
            admin_html,
            r'name="source"\s+value="facebook"\s+checked',
        )
        guland_pos = admin_html.index('value="guland"')
        self.assertNotIn("checked", admin_html[guland_pos:guland_pos + 100])


if __name__ == "__main__":
    unittest.main()
