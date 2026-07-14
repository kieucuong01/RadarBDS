import sys
import unittest
import uuid
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class AdminGrowthTest(unittest.TestCase):
    anchor = "2097-07-14"
    current_at = "2097-07-14T02:00:00"
    previous_at = "2097-07-13T02:00:00"

    def setUp(self):
        from auth.core import SESSION_COOKIE_NAME
        from db.connection import get_conn
        import app as app_module

        self.token = uuid.uuid4().hex
        self.admin_identifier = f"growth-admin-{self.token}@example.test"
        self.session_token = f"growth-session-{self.token}"
        self.listing_ids = []
        self.user_ids = []

        with get_conn() as conn:
            admin = conn.execute(
                """
                INSERT INTO users (identifier, identifier_type, password_hash, tier, created_at)
                VALUES (?, 'email', 'hash', 'admin', '2020-01-01T00:00:00')
                """,
                (self.admin_identifier,),
            )
            self.admin_id = admin.lastrowid
            conn.execute(
                """
                INSERT INTO user_sessions (token, user_id, expires_at)
                VALUES (?, ?, '2099-01-01T00:00:00')
                """,
                (self.session_token, self.admin_id),
            )

        self.client = app_module.app.test_client()
        try:
            self.client.set_cookie(SESSION_COOKIE_NAME, self.session_token)
        except TypeError:
            self.client.set_cookie("localhost", SESSION_COOKIE_NAME, self.session_token)

    def tearDown(self):
        from db.connection import get_conn

        with get_conn() as conn:
            conn.execute("DELETE FROM lead_captures WHERE note=?", (self.token,))
            if self.user_ids:
                placeholders = ",".join("?" * len(self.user_ids))
                conn.execute(f"DELETE FROM user_audit_log WHERE user_id IN ({placeholders})", self.user_ids)
                conn.execute(f"DELETE FROM users WHERE id IN ({placeholders})", self.user_ids)
            if self.listing_ids:
                placeholders = ",".join("?" * len(self.listing_ids))
                conn.execute(f"DELETE FROM valuation_results WHERE listing_id IN ({placeholders})", self.listing_ids)
                conn.execute(f"DELETE FROM price_history WHERE listing_id IN ({placeholders})", self.listing_ids)
                conn.execute(f"DELETE FROM listings WHERE id IN ({placeholders})", self.listing_ids)
            conn.execute("DELETE FROM raw_listings WHERE url LIKE ?", (f"https://growth-{self.token}.example/%",))
            conn.execute("DELETE FROM user_sessions WHERE token=?", (self.session_token,))
            conn.execute("DELETE FROM users WHERE id=?", (self.admin_id,))

    def _insert_listing(self, source, suffix, *, event_at=None, duplicate_of_id=None, signal=True):
        from db.connection import get_conn

        event_at = event_at or self.current_at
        url = f"https://growth-{self.token}.example/{source}/{suffix}"
        with get_conn() as conn:
            raw = conn.execute(
                """
                INSERT INTO raw_listings (source, source_id, url, raw_json, crawled_at)
                VALUES (?, ?, ?, '{}', ?)
                """,
                (source, f"{source}-{suffix}-{self.token}", f"{url}/raw", event_at),
            )
            listing = conn.execute(
                """
                INSERT INTO listings (
                    raw_id, source, source_id, url, title, price_ty, price_first_ty,
                    price_per_m2, area_m2, property_type, ward, crawled_at,
                    first_seen_at, duplicate_of_id, possibly_duplicate
                ) VALUES (?, ?, ?, ?, ?, 1.8, 2.0, 18.0, 100.0, 'dat_nen',
                          'Phú Mỹ', ?, ?, ?, ?)
                """,
                (
                    raw.lastrowid,
                    source,
                    f"{source}-{suffix}-{self.token}",
                    url,
                    suffix,
                    event_at,
                    event_at,
                    duplicate_of_id,
                    1 if duplicate_of_id else 0,
                ),
            )
            listing_id = listing.lastrowid
            conn.execute(
                """
                INSERT INTO valuation_results (
                    listing_id, fair_ppm2, actual_ppm2, mos_pct, is_signal,
                    source_quality_recheck, source_quality_flags, computed_at
                ) VALUES (?, 25.0, 18.0, 28.0, ?, 0, '', ?)
                """,
                (listing_id, 1 if signal else 0, event_at),
            )
        self.listing_ids.append(listing_id)
        return listing_id

    def _insert_price_drop(self, listing_id, at):
        from db.connection import get_conn

        with get_conn() as conn:
            conn.execute(
                "INSERT INTO price_history (listing_id, price_ty, recorded_at) VALUES (?, 2.0, ?)",
                (listing_id, at.replace("02:00:00", "01:00:00")),
            )
            conn.execute(
                "INSERT INTO price_history (listing_id, price_ty, recorded_at) VALUES (?, 1.8, ?)",
                (listing_id, at.replace("02:00:00", "03:00:00")),
            )
            conn.execute(
                "INSERT INTO price_history (listing_id, price_ty, recorded_at) VALUES (?, 1.7, ?)",
                (listing_id, at.replace("02:00:00", "04:00:00")),
            )

    def _insert_user(self, suffix, tier="free", *, active=True):
        from db.connection import get_conn

        identifier = f"growth-{suffix}-{self.token}@example.test"
        with get_conn() as conn:
            user = conn.execute(
                """
                INSERT INTO users (identifier, identifier_type, password_hash, tier, created_at)
                VALUES (?, 'email', 'hash', ?, ?)
                """,
                (identifier, tier, self.current_at),
            )
            user_id = user.lastrowid
            if active:
                conn.execute(
                    """
                    INSERT INTO user_audit_log (user_id, tier, action, created_at)
                    VALUES (?, ?, 'dashboard_viewed', ?)
                    """,
                    (user_id, tier, self.current_at),
                )
        self.user_ids.append(user_id)
        return user_id

    def _seed_growth_data(self):
        from db.connection import get_conn

        facebook = self._insert_listing("facebook", "facebook-canonical")
        self._insert_listing("facebook", "facebook-repost", duplicate_of_id=facebook)
        guland = self._insert_listing("guland", "guland-canonical")
        self._insert_listing("batdongsan", "legacy-canonical")
        self._insert_listing("facebook", "previous", event_at=self.previous_at)
        self._insert_price_drop(facebook, self.current_at)
        self._insert_price_drop(guland, self.current_at)

        regular_user = self._insert_user("regular")
        self._insert_user("audit-admin", tier="admin")

        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO lead_captures (
                    created_at, listing_id, listing_url, zalo_phone, source_context,
                    note, status, user_id, tier, urgency
                ) VALUES (?, ?, '', '0900000001', 'card_signal', ?, 'deposit', ?, 'free', 'standard')
                """,
                (self.current_at, facebook, self.token, regular_user),
            )
            conn.execute(
                """
                INSERT INTO lead_captures (
                    created_at, listing_id, listing_url, zalo_phone, source_context,
                    note, status, tier, urgency
                ) VALUES (?, ?, '', '0900000002', 'card_signal', ?, 'new', 'guest', 'guest')
                """,
                (self.current_at, guland, self.token),
            )
            conn.execute(
                """
                INSERT INTO lead_captures (
                    created_at, listing_id, listing_url, zalo_phone, source_context,
                    note, status, tier, urgency
                ) VALUES (?, NULL, '', '0900000003', 'card_signal', ?, 'new', 'guest', 'guest')
                """,
                (self.current_at, self.token),
            )

    def test_growth_endpoint_requires_admin(self):
        client = self.client.application.test_client()

        response = client.get(f"/admin/api/growth?period=day&anchor={self.anchor}")

        self.assertEqual(response.status_code, 403)

    def test_growth_endpoint_validates_period_and_anchor(self):
        bad_period = self.client.get(f"/admin/api/growth?period=quarter&anchor={self.anchor}")
        bad_anchor = self.client.get("/admin/api/growth?period=day&anchor=14-07-2097")

        self.assertEqual(bad_period.status_code, 400)
        self.assertEqual(bad_period.get_json()["error"], "invalid_period")
        self.assertEqual(bad_anchor.status_code, 400)
        self.assertEqual(bad_anchor.get_json()["error"], "invalid_anchor")

    def test_growth_defaults_to_facebook_and_can_include_guland(self):
        self._seed_growth_data()

        facebook_response = self.client.get(
            f"/admin/api/growth?period=day&anchor={self.anchor}"
        )
        combined_response = self.client.get(
            f"/admin/api/growth?period=day&anchor={self.anchor}&include_guland=1"
        )

        self.assertEqual(facebook_response.status_code, 200)
        facebook = facebook_response.get_json()
        combined = combined_response.get_json()

        self.assertEqual(facebook["filters"]["sources"], ["facebook"])
        self.assertEqual(combined["filters"]["sources"], ["facebook", "guland"])
        self.assertEqual(facebook["summary"]["crawled"]["current"], 2)
        self.assertEqual(combined["summary"]["crawled"]["current"], 3)
        self.assertEqual(facebook["summary"]["signals"]["current"], 1)
        self.assertEqual(combined["summary"]["signals"]["current"], 2)
        self.assertEqual(facebook["summary"]["unique_lots"]["current"], 1)
        self.assertEqual(combined["summary"]["unique_lots"]["current"], 2)
        self.assertEqual(facebook["summary"]["price_drops"]["current"], 1)
        self.assertEqual(combined["summary"]["price_drops"]["current"], 2)
        self.assertEqual(facebook["summary"]["signups"]["current"], 2)
        self.assertEqual(combined["summary"]["signups"]["current"], 2)
        self.assertEqual(facebook["summary"]["leads"]["current"], 1)
        self.assertEqual(combined["summary"]["leads"]["current"], 2)
        self.assertEqual(facebook["summary"]["leads"]["unattributed_current"], 1)
        self.assertEqual(facebook["ratios"]["signal_yield_pct"], 50.0)
        self.assertEqual(facebook["ratios"]["unique_lot_yield_pct"], 50.0)
        self.assertEqual(facebook["ratios"]["active_users"], 1)
        self.assertEqual(facebook["ratios"]["lead_to_deposit_pct"], 100.0)
        self.assertEqual(combined["ratios"]["lead_to_deposit_pct"], 50.0)
        self.assertEqual(len(facebook["series"]), 24)
        self.assertEqual(sum(row["price_drops"] for row in facebook["series"]), 1)


if __name__ == "__main__":
    unittest.main()
