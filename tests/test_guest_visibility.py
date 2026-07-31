import shutil
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class GuestVisibilityTest(unittest.TestCase):
    def setUp(self):
        from db import connection
        from db.schema import init_schema
        import app as app_module

        self.tmpdir = Path(tempfile.mkdtemp())
        self.db_path = self.tmpdir / "radar_guest_visibility.db"
        self.token = uuid.uuid4().hex
        self.url_prefix = f"https://guest-visibility-{self.token}.test"
        self.ward = f"GuestWard{self.token[:8]}"
        self.session_token = f"guest-visibility-free-{self.token}"
        self.user_identifier = f"guest-visibility-{self.token}@test.local"
        self.listing_ids = []
        connection.close_all()
        self.patches = [
            mock.patch.object(connection, "DB_PATH", self.db_path),
            mock.patch.object(app_module.db_mod, "DB_PATH", self.db_path),
        ]
        for p in self.patches:
            p.start()

        init_schema()
        self._delete_test_rows()
        self.client = app_module.app.test_client()
        self.listing_id = self._seed_fresh_signal()

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
            conn.execute(f"DELETE FROM legal_verifications WHERE listing_id IN ({placeholders})", params)
            conn.execute(f"DELETE FROM listings WHERE id IN ({placeholders})", params)

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

    def _seed_fresh_signal(self):
        from db.connection import get_conn

        with get_conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO listings (
                    source, source_id, url, title, description, ward,
                    area_m2, property_type, price_ty, price_per_m2,
                    is_hot, price_dropped, suspicious_bait,
                    probably_sold, possibly_duplicate, posted_at, crawled_at
                ) VALUES (
                    'facebook', ?, ?,
                    'Fresh guest-visible signal', 'Fresh listing description',
                    ?, 100, 'dat_nen', 2.0, 20.0,
                    0, 0, 0, 0, 0, datetime('now'), datetime('now')
                )
                """,
                (f"fresh-guest-visible-{self.token}", f"{self.url_prefix}/fresh", self.ward),
            )
            listing_id = cur.lastrowid
            self.listing_ids.append(listing_id)
            conn.execute(
                """
                INSERT INTO valuation_results (
                    listing_id, fair_ppm2, actual_ppm2, mos_pct,
                    is_signal, signal_score
                ) VALUES (?, 30.0, 20.0, 33.3, 1, 70)
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
                ) VALUES (?, ?, 30.0, 20.0, 33.3, 1, 70, '')
                """,
                (run_id, listing_id),
            )
            return listing_id

    def test_guest_sees_fresh_signal_card_content_without_source_url(self):
        response = self.client.get(f"/api/signals?city=Khac&ward={self.ward}&limit=5")
        self.assertEqual(response.status_code, 200)

        signals = response.get_json()["signals"]
        self.assertEqual(len(signals), 1)
        row = signals[0]
        self.assertEqual(row["title"], "Fresh guest-visible signal")
        self.assertEqual(row["price_ty"], 2.0)
        self.assertEqual(row["url"], None)
        self.assertNotIn("locked_reason", row)
        self.assertFalse(row["is_fresh_locked"])

    def test_signal_feed_uses_latest_valuation_once_per_listing(self):
        from db.connection import get_conn

        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO valuation_results (
                    listing_id, fair_ppm2, actual_ppm2, mos_pct,
                    is_signal, signal_score
                ) VALUES (?, 40.0, 20.0, 50.0, 1, 90)
                """,
                (self.listing_id,),
            )

        response = self.client.get(f"/api/signals?city=Khac&ward={self.ward}&limit=5")
        self.assertEqual(response.status_code, 200)

        payload = response.get_json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual(len(payload["signals"]), 1)
        self.assertEqual(payload["signals"][0]["id"], self.listing_id)
        self.assertEqual(payload["signals"][0]["fair_ppm2_old"], 40.0)
        self.assertEqual(payload["signals"][0]["mos_pct_display"], 33.3)
        self.assertEqual(payload["signals"][0]["signal_score"], 90)

        dashboard = self.client.get(f"/api/dashboard?city=Khac&ward={self.ward}")
        self.assertEqual(dashboard.status_code, 200)
        self.assertEqual(dashboard.get_json()["stats"]["signals"], 1)

    def test_signal_feed_requires_price_and_area_even_with_stale_valuation(self):
        from db.connection import get_conn

        with get_conn() as conn:
            cases = [
                ("missing-price", None, 10.5, 95.0, 15.8, 10.5),
                ("missing-area", 1.77, 6.2, None, 12.2, 6.2),
            ]
            for slug, price_ty, price_per_m2, area_m2, fair_ppm2, actual_ppm2 in cases:
                cur = conn.execute(
                    """
                    INSERT INTO listings (
                        source, source_id, url, title, description, ward,
                        area_m2, property_type, price_ty, price_per_m2,
                        is_hot, price_dropped, suspicious_bait,
                        probably_sold, possibly_duplicate, posted_at, crawled_at
                    ) VALUES (
                        'facebook', ?, ?,
                        ?, 'Incomplete stale valuation listing',
                        ?, ?, 'dat_nen', ?, ?,
                        0, 0, 0, 0, 0, datetime('now'), datetime('now')
                    )
                    """,
                    (
                        f"{slug}-{self.token}",
                        f"{self.url_prefix}/{slug}",
                        f"Incomplete {slug}",
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
                    ) VALUES (?, ?, ?, 35.0, 1, 70)
                    """,
                    (listing_id, fair_ppm2, actual_ppm2),
                )

        response = self.client.get(f"/api/signals?city=Khac&ward={self.ward}&limit=20")
        self.assertEqual(response.status_code, 200)

        payload = response.get_json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual([row["id"] for row in payload["signals"]], [self.listing_id])

    def test_signal_feed_requires_conservative_mos_from_lower_model(self):
        from db.connection import get_conn

        with get_conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO listings (
                    source, source_id, url, title, description, ward,
                    area_m2, property_type, price_ty, price_per_m2,
                    is_hot, price_dropped, suspicious_bait,
                    probably_sold, possibly_duplicate, posted_at, crawled_at
                ) VALUES (
                    'facebook', ?, ?,
                    'New model only signal', 'Fresh listing description',
                    ?, 100, 'dat_nen', 2.0, 20.0,
                    0, 0, 0, 0, 0, datetime('now'), datetime('now')
                )
                """,
                (f"new-model-only-{self.token}", f"{self.url_prefix}/new-model-only", self.ward),
            )
            listing_id = cur.lastrowid
            self.listing_ids.append(listing_id)
            conn.execute(
                """
                INSERT INTO valuation_results (
                    listing_id, fair_ppm2, actual_ppm2, mos_pct,
                    is_signal, signal_score
                ) VALUES (?, 21.0, 20.0, 4.8, 0, 0)
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
                ) VALUES (?, ?, 24.0, 20.0, 16.7, 1, 55, '')
                """,
                (run_id, listing_id),
            )
            cur = conn.execute(
                """
                INSERT INTO listings (
                    source, source_id, url, title, description, ward,
                    area_m2, property_type, price_ty, price_per_m2,
                    is_hot, price_dropped, suspicious_bait,
                    probably_sold, possibly_duplicate, posted_at, crawled_at
                ) VALUES (
                    'facebook', ?, ?,
                    'Both models conservative signal', 'Fresh listing description',
                    ?, 100, 'dat_nen', 2.0, 20.0,
                    0, 0, 0, 0, 0, datetime('now'), datetime('now')
                )
                """,
                (f"both-models-{self.token}", f"{self.url_prefix}/both-models", self.ward),
            )
            both_id = cur.lastrowid
            self.listing_ids.append(both_id)
            conn.execute(
                """
                INSERT INTO valuation_results (
                    listing_id, fair_ppm2, actual_ppm2, mos_pct,
                    is_signal, signal_score
                ) VALUES (?, 26.0, 20.0, 23.1, 1, 60)
                """,
                (both_id,),
            )
            conn.execute(
                """
                INSERT INTO valuation_shadow_results (
                    model_run_id, listing_id, fair_ppm2, actual_ppm2, mos_pct,
                    is_signal, signal_score, source_quality_flags
                ) VALUES (?, ?, 24.0, 20.0, 16.7, 1, 55, '')
                """,
                (run_id, both_id),
            )

        response = self.client.get(f"/api/signals?city=Khac&ward={self.ward}&limit=10")
        self.assertEqual(response.status_code, 200)
        rows = {row["id"]: row for row in response.get_json()["signals"]}

        self.assertNotIn(listing_id, rows)
        self.assertIn(both_id, rows)
        row = rows[both_id]
        self.assertEqual(row["signal_model"], "display_mos")
        self.assertEqual(row["fair_ppm2_old"], 26.0)
        self.assertEqual(row["fair_ppm2_new"], 24.0)
        self.assertEqual(row["fair_ppm2_display"], 24.0)
        self.assertAlmostEqual(row["mos_pct_display"], 16.7, places=1)

        self._login_as_free()
        filtered = self.client.get(f"/api/signals?city=Khac&ward={self.ward}&limit=10&mos_min=20")
        self.assertEqual(filtered.status_code, 200)
        filtered_ids = {row["id"] for row in filtered.get_json()["signals"]}
        self.assertNotIn(both_id, filtered_ids)

    def test_free_user_cannot_filter_below_model_signal_threshold(self):
        from db.connection import get_conn

        with get_conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO listings (
                    source, source_id, url, title, description, ward,
                    area_m2, property_type, price_ty, price_per_m2,
                    is_hot, price_dropped, suspicious_bait,
                    probably_sold, possibly_duplicate, posted_at, crawled_at
                ) VALUES (
                    'facebook', ?, ?,
                    'Below ten percent conservative deal', 'Fresh listing description',
                    ?, 100, 'dat_nen', 2.0, 20.0,
                    0, 0, 0, 0, 0, datetime('now'), datetime('now')
                )
                """,
                (f"below-ten-{self.token}", f"{self.url_prefix}/below-ten", self.ward),
            )
            listing_id = cur.lastrowid
            self.listing_ids.append(listing_id)
            conn.execute(
                """
                INSERT INTO valuation_results (
                    listing_id, fair_ppm2, actual_ppm2, mos_pct,
                    is_signal, signal_score, source_quality_flags
                ) VALUES (?, 21.8, 20.0, 8.3, 0, 20, '')
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
                ) VALUES (?, ?, 22.5, 20.0, 11.1, 0, 25, '')
                """,
                (run_id, listing_id),
            )

        default_response = self.client.get(f"/api/signals?city=Khac&ward={self.ward}&limit=20")
        self.assertEqual(default_response.status_code, 200)
        default_ids = {row["id"] for row in default_response.get_json()["signals"]}
        self.assertNotIn(listing_id, default_ids)

        self._login_as_free()
        filtered_response = self.client.get(f"/api/signals?city=Khac&ward={self.ward}&limit=20&mos_min=5")
        self.assertEqual(filtered_response.status_code, 200)
        rows = {row["id"]: row for row in filtered_response.get_json()["signals"]}
        self.assertNotIn(listing_id, rows)

    def test_signal_feed_hides_display_mos_deals_with_hard_quality_flags(self):
        from db.connection import get_conn

        with get_conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO listings (
                    source, source_id, url, title, description, ward,
                    area_m2, property_type, price_ty, price_per_m2,
                    is_hot, price_dropped, suspicious_bait,
                    probably_sold, possibly_duplicate, posted_at, crawled_at
                ) VALUES (
                    'facebook', ?, ?,
                    'QC flagged display MOS deal', 'Fresh listing description',
                    ?, 100, 'dat_nen', 2.0, 20.0,
                    0, 0, 0, 0, 0, datetime('now'), datetime('now')
                )
                """,
                (f"qc-flagged-deal-{self.token}", f"{self.url_prefix}/qc-flagged-deal", self.ward),
            )
            listing_id = cur.lastrowid
            self.listing_ids.append(listing_id)
            conn.execute(
                """
                INSERT INTO valuation_results (
                    listing_id, fair_ppm2, actual_ppm2, mos_pct,
                    is_signal, signal_score, source_quality_recheck, source_quality_flags
                ) VALUES (?, 30.0, 20.0, 33.3, 0, 10, 1, 'review_bad_extraction')
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
                    is_signal, signal_score, source_quality_recheck, source_quality_flags
                ) VALUES (?, ?, 28.0, 20.0, 28.6, 0, 10, 1, 'review_bad_extraction')
                """,
                (run_id, listing_id),
            )

        response = self.client.get(f"/api/signals?city=Khac&ward={self.ward}&limit=20")
        self.assertEqual(response.status_code, 200)
        rows = {row["id"]: row for row in response.get_json()["signals"]}
        self.assertNotIn(listing_id, rows)

        dashboard = self.client.get(f"/api/dashboard?city=Khac&ward={self.ward}")
        self.assertEqual(dashboard.status_code, 200)
        self.assertEqual(dashboard.get_json()["stats"]["signals"], 1)

    def test_drop_filter_includes_canonical_with_higher_price_repost(self):
        from db.connection import get_conn
        from services.market_data import load_signals

        with get_conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO listings (
                    source, source_id, url, title, description, ward,
                    area_m2, property_type, price_ty, price_per_m2,
                    is_hot, price_dropped, suspicious_bait,
                    probably_sold, possibly_duplicate, duplicate_of_id,
                    posted_at, crawled_at
                ) VALUES (
                    'facebook', ?, ?,
                    'Older higher-price repost', 'Same lot repost',
                    ?, 100, 'dat_nen', 2.3, 23.0,
                    0, 0, 0, 0, 1, ?,
                    datetime('now','-1 day'), datetime('now','-1 day')
                )
                """,
                (
                    f"higher-price-repost-{self.token}",
                    f"{self.url_prefix}/higher-price-repost",
                    self.ward,
                    self.listing_id,
                ),
            )
            self.listing_ids.append(cur.lastrowid)

        result = load_signals(
            self.db_path,
            sources=["facebook"],
            wards=[self.ward],
            only_drops=True,
            tier="admin",
        )

        rows = result["signals"]
        self.assertEqual([row["id"] for row in rows], [self.listing_id])
        self.assertTrue(rows[0]["price_dropped"])
        self.assertEqual(rows[0]["price_first_ty"], 2.3)
        self.assertAlmostEqual(rows[0]["drop_pct"], 13.04, places=2)

    def test_guest_sees_fresh_listing_detail_without_source_url(self):
        response = self.client.get(f"/api/listing/{self.listing_id}")
        self.assertEqual(response.status_code, 200)

        data = response.get_json()
        self.assertEqual(data["title"], "Fresh guest-visible signal")
        self.assertEqual(data["description"], "Fresh listing description")
        self.assertEqual(data["price_ty"], 2.0)
        self.assertEqual(data["url"], None)

    def test_guest_listing_detail_redacts_phone_numbers_embedded_in_description(self):
        from db.connection import get_conn
        from services.market_data import load_listing_detail

        description = "Fresh listing description.\nLH 038 294 1231 gap em Phuong giap chu."
        with get_conn() as conn:
            conn.execute(
                "UPDATE listings SET description=?, seller_name=? WHERE id=?",
                (description, "Phuong Giap", self.listing_id),
            )

        response = self.client.get(f"/api/listing/{self.listing_id}")
        self.assertEqual(response.status_code, 200)

        guest_data = response.get_json()
        self.assertNotIn("038 294 1231", guest_data["description"])
        self.assertNotIn("0382941231", guest_data["description"])
        self.assertNotIn("Phuong", guest_data["description"])
        self.assertNotIn("giap chu", guest_data["description"])
        self.assertIn("Liên hệ tư vấn", guest_data["description"])

        guest_detail = load_listing_detail(str(self.db_path), self.listing_id, tier="guest")
        self.assertIsNone(guest_detail["listing"]["seller_name"])

        admin_data = load_listing_detail(str(self.db_path), self.listing_id, tier="admin")
        self.assertEqual(admin_data["listing"]["description"], description)
        self.assertEqual(admin_data["listing"]["seller_name"], "Phuong Giap")

    def test_redact_for_tier_hides_embedded_phone_numbers_for_non_admin_tiers(self):
        from services.market_data import redact_for_tier

        record = {
            "title": "Ban dat goi 0382941231",
            "description": "Lien he +84 38 294 1231 hoac 038.294.1231",
            "url": "https://example.test/listing",
            "contact_phone": "0382941231",
            "seller_name": "Phuong Giap",
        }

        for tier in ("guest", "free", "vip"):
            redacted = redact_for_tier(record, tier)
            self.assertNotIn("0382941231", redacted["title"])
            self.assertNotIn("+84 38 294 1231", redacted["description"])
            self.assertNotIn("038.294.1231", redacted["description"])
            self.assertIn("Liên hệ tư vấn", redacted["title"])
            self.assertIn("Liên hệ tư vấn", redacted["description"])
            self.assertIsNone(redacted["url"])
            self.assertIsNone(redacted["contact_phone"])
            self.assertIsNone(redacted["seller_name"])

        admin = redact_for_tier(record, "admin")
        self.assertEqual(admin, record)


if __name__ == "__main__":
    unittest.main()
