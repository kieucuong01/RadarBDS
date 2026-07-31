import sys
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class DropFilterTest(unittest.TestCase):
    def setUp(self):
        from db import connection
        from db.schema import init_schema
        import app as app_module

        self.token = uuid.uuid4().hex
        self.url_prefix = f"https://drop-filter-{self.token}.test"
        self.ward = f"DropWard{self.token[:8]}"
        self.user_identifier = f"drop-filter-{self.token}@test.local"
        self.session_token = f"drop-filter-free-token-{self.token}"
        self.listing_ids = []
        connection.close_all()

        init_schema()
        self._delete_test_rows()
        self.client = app_module.app.test_client()
        self._seed()

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
            conn.execute(f"DELETE FROM listing_images WHERE listing_id IN ({placeholders})", params)
            conn.execute(f"DELETE FROM legal_verifications WHERE listing_id IN ({placeholders})", params)
            conn.execute(f"DELETE FROM listings WHERE id IN ({placeholders})", params)

    def _seed(self):
        from db.connection import get_conn

        with get_conn() as conn:
            cur = conn.execute("""
                INSERT INTO listings (
                    source, source_id, url, title, ward, area_m2, property_type,
                    price_ty, price_per_m2, price_first_ty, price_dropped,
                    price_drop_pct, probably_sold, possibly_duplicate, duplicate_of_id,
                    posted_at, crawled_at
                ) VALUES (
                    'facebook', ?, ?, 'Old listing',
                    ?, 100, 'dat_nen', 2.0, 20, 2.0, 0,
                    NULL, 0, 0, NULL,
                    datetime('now', '-10 days'), datetime('now', '-10 days')
                )
            """, (f"old-{self.token}", f"{self.url_prefix}/old", self.ward))
            self.old_id = cur.lastrowid
            self.listing_ids.append(self.old_id)
            cur = conn.execute("""
                INSERT INTO listings (
                    source, source_id, url, title, ward, area_m2, property_type,
                    price_ty, price_per_m2, price_first_ty, price_dropped,
                    price_drop_pct, probably_sold, possibly_duplicate, duplicate_of_id,
                    posted_at, crawled_at
                ) VALUES (
                    'facebook', ?, ?, 'New lower repost',
                    ?, 100, 'dat_nen', 1.9, 19, 2.0, 1,
                    5.0, 0, 1, ?,
                    datetime('now', '-10 days'), datetime('now', '-10 days')
                )
            """, (f"new-{self.token}", f"{self.url_prefix}/new", self.ward, self.old_id))
            self.new_id = cur.lastrowid
            self.listing_ids.append(self.new_id)

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

    def test_normal_listing_view_hides_duplicate_repost(self):
        response = self.client.get(f"/api/listings?city=Khac&ward={self.ward}")
        self.assertEqual(response.status_code, 200)
        ids = [row["id"] for row in response.get_json()["listings"]]
        self.assertEqual(ids, [self.old_id])

    def test_drop_filter_shows_duplicate_price_drop_repost(self):
        self._login_as_free()
        response = self.client.get(f"/api/listings?city=Khac&ward={self.ward}&only_drops=1")
        self.assertEqual(response.status_code, 200)
        rows = response.get_json()["listings"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "New lower repost")
        self.assertTrue(rows[0]["price_dropped"])
        self.assertEqual(rows[0]["duplicate_of_id"], self.old_id)


if __name__ == "__main__":
    unittest.main()
