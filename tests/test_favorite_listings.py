import shutil
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class FavoriteListingsTest(unittest.TestCase):
    def setUp(self):
        from db import connection
        from db.schema import init_schema
        import app as app_module

        self.tmpdir = Path(tempfile.mkdtemp())
        self.db_path = self.tmpdir / "radar_favorites.db"
        self.token = uuid.uuid4().hex
        self.url = f"https://favorite-listings-{self.token}.test/listing"
        self.session_token = f"favorite-listings-{self.token}"
        self.user_identifier = f"favorite-listings-{self.token}@test.local"
        connection.close_all()
        self.patches = [
            mock.patch.object(connection, "DB_PATH", self.db_path),
            mock.patch.object(app_module.db_mod, "DB_PATH", self.db_path),
        ]
        for p in self.patches:
            p.start()

        init_schema()
        self.client = app_module.app.test_client()
        self._delete_test_rows()
        self.listing_id = self._seed_listing()

    def tearDown(self):
        from db import connection

        self._delete_test_rows()
        connection.close_all()
        for p in reversed(self.patches):
            p.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _delete_test_rows(self):
        from db.connection import get_conn

        with get_conn() as conn:
            conn.execute("DELETE FROM user_sessions WHERE token = ?", (self.session_token,))
            has_favorites = bool(conn.execute(
                """
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema='public' AND table_name='user_favorite_listings'
                """
            ).fetchone())
            user = conn.execute("SELECT id FROM users WHERE identifier = ?", (self.user_identifier,)).fetchone()
            if user and has_favorites:
                conn.execute("DELETE FROM user_favorite_listings WHERE user_id = ?", (user["id"],))
            row = conn.execute("SELECT id FROM listings WHERE url = ?", (self.url,)).fetchone()
            if row:
                if has_favorites:
                    conn.execute("DELETE FROM user_favorite_listings WHERE listing_id = ?", (row["id"],))
                conn.execute("DELETE FROM listings WHERE id = ?", (row["id"],))
            conn.execute("DELETE FROM users WHERE identifier = ?", (self.user_identifier,))

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

    def _seed_listing(self):
        from db.connection import get_conn

        with get_conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO listings (
                    source, source_id, url, title, ward, area_m2, property_type,
                    price_ty, price_per_m2, probably_sold, possibly_duplicate
                ) VALUES (
                    'facebook', ?, ?, 'Favorite test listing', 'FavoriteWard',
                    90, 'dat_nen', 1.8, 20, 0, 0
                )
                """,
                (f"favorite-{self.token}", self.url),
            )
            return cur.lastrowid

    def test_guest_cannot_save_favorite(self):
        res = self.client.post(f"/api/favorites/{self.listing_id}")
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.get_json()["error"], "tier_required")

    def test_logged_in_user_can_add_list_and_remove_favorite(self):
        self._login_as_free()

        saved = self.client.post(f"/api/favorites/{self.listing_id}")
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.get_json(), {"ok": True, "listing_id": self.listing_id, "favorite": True})

        listed = self.client.get("/api/favorites")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.get_json()["listing_ids"], [self.listing_id])

        removed = self.client.delete(f"/api/favorites/{self.listing_id}")
        self.assertEqual(removed.status_code, 200)
        self.assertEqual(removed.get_json(), {"ok": True, "listing_id": self.listing_id, "favorite": False})

        listed_after = self.client.get("/api/favorites")
        self.assertEqual(listed_after.get_json()["listing_ids"], [])

    def test_cannot_favorite_missing_listing(self):
        self._login_as_free()

        res = self.client.post("/api/favorites/999999999")

        self.assertEqual(res.status_code, 404)
        self.assertEqual(res.get_json(), {"ok": False, "error": "not_found"})

    def test_saved_listings_page_renders_grid_and_reuses_signal_modal(self):
        res = self.client.get("/bds-da-luu")

        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        self.assertIn("window.RADAR_SAVED_PAGE = true;", html)
        self.assertIn('id="savedListingsGrid"', html)
        self.assertIn('id="signalModal"', html)
        self.assertIn("loadSavedListingsPage(true)", html)
        self.assertIn("saved-header-brand", html)
        self.assertIn("saved-listings-header-images-20260722", html)

        signals_js = (Path(__file__).resolve().parent.parent / "static" / "js" / "main" / "signals.js").read_text(encoding="utf-8")
        self.assertIn("primary_img: images[0] || ''", signals_js)
        self.assertIn("imgs: images", signals_js)

    def test_account_menu_links_to_saved_listings_after_watchlist(self):
        self._login_as_free()

        res = self.client.get("/bds-da-luu")

        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        menu = html[html.index('id="userMenuDropdown"'):html.index("RadarAuth.logout()", html.index('id="userMenuDropdown"'))]
        self.assertLess(menu.index("RadarAuth.openWatchlistModal()"), menu.index("window.location.href='/bds-da-luu'"))
        self.assertIn("window.location.href='/bds-da-luu'", menu)


if __name__ == "__main__":
    unittest.main()
