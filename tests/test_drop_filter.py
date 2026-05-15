import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class DropFilterTest(unittest.TestCase):
    def setUp(self):
        from db import connection
        from db.schema import init_schema
        import app as app_module

        self.tmpdir = Path(tempfile.mkdtemp())
        self.db_path = self.tmpdir / "radar_drop_filter.db"
        connection.close_all()
        self.patches = [
            mock.patch.object(connection, "DB_PATH", self.db_path),
            mock.patch.object(app_module.db_mod, "DB_PATH", self.db_path),
        ]
        for p in self.patches:
            p.start()

        init_schema()
        self.client = app_module.app.test_client()
        self._seed()

    def tearDown(self):
        from db import connection

        connection.close_all()
        for p in reversed(self.patches):
            p.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _seed(self):
        from db.connection import get_conn

        with get_conn() as conn:
            conn.execute("""
                INSERT INTO listings (
                    source, source_id, url, title, ward, area_m2, property_type,
                    price_ty, price_per_m2, price_first_ty, price_dropped,
                    price_drop_pct, probably_sold, possibly_duplicate, duplicate_of_id,
                    posted_at, crawled_at
                ) VALUES (
                    'facebook', 'old', 'https://example.test/old', 'Old listing',
                    'Tân An', 100, 'dat_nen', 2.0, 20, 2.0, 0,
                    NULL, 0, 0, NULL,
                    datetime('now', '-10 days'), datetime('now', '-10 days')
                )
            """)
            self.old_id = conn.execute("SELECT id FROM listings WHERE source_id='old'").fetchone()[0]
            conn.execute("""
                INSERT INTO listings (
                    source, source_id, url, title, ward, area_m2, property_type,
                    price_ty, price_per_m2, price_first_ty, price_dropped,
                    price_drop_pct, probably_sold, possibly_duplicate, duplicate_of_id,
                    posted_at, crawled_at
                ) VALUES (
                    'facebook', 'new', 'https://example.test/new', 'New lower repost',
                    'Tân An', 100, 'dat_nen', 1.9, 19, 2.0, 1,
                    5.0, 0, 1, ?,
                    datetime('now', '-10 days'), datetime('now', '-10 days')
                )
            """, (self.old_id,))

    def _login_as_free(self):
        from auth.core import SESSION_COOKIE_NAME
        from db.connection import get_conn

        token = "drop-filter-free-token"
        with get_conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO users (identifier, identifier_type, password_hash, tier)
                VALUES ('0900000099', 'phone', 'hash', 'free')
                """
            )
            conn.execute(
                """
                INSERT INTO user_sessions (token, user_id, expires_at)
                VALUES (?, ?, '2099-01-01T00:00:00')
                """,
                (token, cur.lastrowid),
            )
        try:
            self.client.set_cookie(SESSION_COOKIE_NAME, token)
        except TypeError:
            self.client.set_cookie("localhost", SESSION_COOKIE_NAME, token)

    def test_normal_listing_view_hides_duplicate_repost(self):
        response = self.client.get("/api/listings?city=Khac")
        self.assertEqual(response.status_code, 200)
        ids = [row["id"] for row in response.get_json()["listings"]]
        self.assertEqual(len(ids), 1)

    def test_drop_filter_shows_duplicate_price_drop_repost(self):
        self._login_as_free()
        response = self.client.get("/api/listings?city=Khac&only_drops=1")
        self.assertEqual(response.status_code, 200)
        rows = response.get_json()["listings"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "New lower repost")
        self.assertTrue(rows[0]["price_dropped"])
        self.assertEqual(rows[0]["duplicate_of_id"], self.old_id)


if __name__ == "__main__":
    unittest.main()
