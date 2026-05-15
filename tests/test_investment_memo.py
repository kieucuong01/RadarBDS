import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock


class InvestmentMemoTest(unittest.TestCase):
    def setUp(self):
        from db import connection
        from db.schema import init_schema
        import app as app_module

        self.tmpdir = Path(tempfile.mkdtemp())
        self.db_path = self.tmpdir / "radar_memo.db"
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

        connection.close_all()
        for patcher in reversed(self.patches):
            patcher.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _insert_listing(self, conn, **kw):
        defaults = {
            "source": "facebook",
            "source_id": None,
            "url": None,
            "title": "Lo dat memo",
            "description": "Ban gap can kiem tra phap ly",
            "ward": "Tan An",
            "area_m2": 100.0,
            "property_type": "dat_nen",
            "tx_type": "ban",
            "price_ty": 2.0,
            "price_per_m2": 20.0,
            "road_tier": 2,
            "road_type": "duong nhua",
            "has_so": 1,
            "price_dropped": 0,
            "price_drop_pct": None,
            "price_first_ty": 2.0,
            "suspicious_bait": 0,
            "probably_sold": 0,
            "possibly_duplicate": 0,
            "duplicate_of_id": None,
            "posted_at": "2026-05-01",
            "crawled_at": "2026-05-01",
        }
        defaults.update(kw)
        if defaults["source_id"] is None:
            defaults["source_id"] = f"src-{defaults['title']}-{defaults['price_ty']}-{defaults['area_m2']}"
        if defaults["url"] is None:
            defaults["url"] = f"https://example.test/{defaults['source_id']}"
        cur = conn.execute(
            """
            INSERT INTO listings (
                source, source_id, url, title, description, ward, area_m2,
                property_type, tx_type, price_ty, price_per_m2, road_tier,
                road_type, has_so, price_dropped, price_drop_pct, price_first_ty,
                suspicious_bait, probably_sold, possibly_duplicate, duplicate_of_id,
                posted_at, crawled_at
            ) VALUES (
                :source, :source_id, :url, :title, :description, :ward, :area_m2,
                :property_type, :tx_type, :price_ty, :price_per_m2, :road_tier,
                :road_type, :has_so, :price_dropped, :price_drop_pct, :price_first_ty,
                :suspicious_bait, :probably_sold, :possibly_duplicate, :duplicate_of_id,
                :posted_at, :crawled_at
            )
            """,
            defaults,
        )
        return cur.lastrowid

    def _insert_valuation(self, conn, listing_id, **kw):
        defaults = {
            "listing_id": listing_id,
            "fair_ppm2": 30.0,
            "actual_ppm2": 20.0,
            "mos_pct": 33.3,
            "is_signal": 1,
            "n_segment": 40,
            "signal_score": 70,
            "is_outlier": 0,
        }
        defaults.update(kw)
        conn.execute(
            """
            INSERT INTO valuation_results (
                listing_id, fair_ppm2, actual_ppm2, mos_pct, is_signal,
                n_segment, signal_score, is_outlier
            ) VALUES (
                :listing_id, :fair_ppm2, :actual_ppm2, :mos_pct, :is_signal,
                :n_segment, :signal_score, :is_outlier
            )
            """,
            defaults,
        )

    def _seed_strong_deal(self, *, suspicious_bait=0):
        from db.connection import get_conn

        with get_conn() as conn:
            listing_id = self._insert_listing(conn, title="Strong deal", suspicious_bait=suspicious_bait)
            self._insert_valuation(conn, listing_id)
            for idx, ppm2 in enumerate([21.0, 22.0, 23.0], start=1):
                self._insert_listing(
                    conn,
                    title=f"Comp {idx}",
                    source_id=f"comp-{idx}-{suspicious_bait}",
                    url=f"https://example.test/comp-{idx}-{suspicious_bait}",
                    price_ty=ppm2 * 100 / 1000,
                    price_per_m2=ppm2,
                    area_m2=100.0 + idx,
                )
        return listing_id

    def _login_as(self, tier="free"):
        from auth.core import SESSION_COOKIE_NAME
        from db.connection import get_conn

        token = f"{tier}-token"
        with get_conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO users (identifier, identifier_type, password_hash, tier)
                VALUES (?, 'phone', 'hash', ?)
                """,
                (f"09000000{len(tier)}", tier),
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

    def test_strong_deal_with_good_comps_explains_below_fair(self):
        from services.investment_memo import load_investment_memo

        listing_id = self._seed_strong_deal()
        memo = load_investment_memo(str(self.db_path), listing_id, tier="free")

        self.assertEqual(memo["verdict"], "below_fair")
        self.assertNotIn("required_mos_pct", memo["metrics"])
        self.assertNotIn("recommended_offer_ty", memo["metrics"])
        self.assertNotIn("skip_if_above_ty", memo["metrics"])
        self.assertNotIn("next_actions", memo)
        self.assertNotIn("strengths", memo)
        self.assertEqual(memo["comps_summary"]["count"], 3)
        self.assertTrue(any("Fair total" in x for x in memo["valuation_explanation"]))

    def test_thin_comps_and_unknown_road_mark_data_limited(self):
        from db.connection import get_conn
        from services.investment_memo import load_investment_memo

        with get_conn() as conn:
            listing_id = self._insert_listing(conn, title="Thin deal", road_tier=0, road_type="unknown")
            self._insert_valuation(conn, listing_id, fair_ppm2=40.0, actual_ppm2=20.0, mos_pct=50.0)

        memo = load_investment_memo(str(self.db_path), listing_id, tier="free")

        self.assertEqual(memo["verdict"], "data_limited")
        self.assertTrue(any("Cấp đường" in x for x in memo["missing_info"]))

    def test_missing_valuation_returns_needs_review(self):
        from db.connection import get_conn
        from services.investment_memo import load_investment_memo

        with get_conn() as conn:
            listing_id = self._insert_listing(conn, title="No valuation")

        memo = load_investment_memo(str(self.db_path), listing_id, tier="free")

        self.assertEqual(memo["verdict"], "needs_review")
        self.assertIsNone(memo["metrics"]["fair_total_ty"])

    def test_suspicious_bait_is_risk_flagged(self):
        from services.investment_memo import load_investment_memo

        listing_id = self._seed_strong_deal(suspicious_bait=1)
        memo = load_investment_memo(str(self.db_path), listing_id, tier="free")

        self.assertEqual(memo["verdict"], "risk_flagged")
        self.assertTrue(any("giá mồi" in x for x in memo["risk_warnings"]))
        blob = json.dumps(memo, ensure_ascii=False).lower()
        self.assertNotIn("đàm phán", blob)
        self.assertNotIn("bỏ qua nếu", blob)
        self.assertNotIn("nên gọi", blob)

    def test_non_admin_memo_does_not_expose_source_url_or_phone(self):
        from services.investment_memo import load_investment_memo

        listing_id = self._seed_strong_deal()
        memo = load_investment_memo(str(self.db_path), listing_id, tier="free")
        blob = json.dumps(memo)

        self.assertNotIn("contact_phone", blob)
        self.assertTrue(all(not c.get("url") for c in memo["comps_summary"]["top"]))

    def test_api_guest_gets_locked_response(self):
        listing_id = self._seed_strong_deal()

        response = self.client.get(f"/api/listing/{listing_id}/memo")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["reason"], "login_required")

    def test_api_free_gets_full_memo(self):
        listing_id = self._seed_strong_deal()
        self._login_as("free")

        response = self.client.get(f"/api/listing/{listing_id}/memo")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["verdict"], "below_fair")

    def test_existing_guest_listing_redaction_still_applies(self):
        listing_id = self._seed_strong_deal()
        from db.connection import get_conn

        with get_conn() as conn:
            conn.execute("UPDATE listings SET posted_at='2099-01-01' WHERE id=?", (listing_id,))

        response = self.client.get(f"/api/listing/{listing_id}")
        data = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(data["url"])
        self.assertIsNone(data["price_ty"])


if __name__ == "__main__":
    unittest.main()
