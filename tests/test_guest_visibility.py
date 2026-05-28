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
        self.assertEqual(payload["signals"][0]["mos_pct"], 50.0)
        self.assertEqual(payload["signals"][0]["signal_score"], 90)

        dashboard = self.client.get(f"/api/dashboard?city=Khac&ward={self.ward}")
        self.assertEqual(dashboard.status_code, 200)
        self.assertEqual(dashboard.get_json()["stats"]["signals"], 1)

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
