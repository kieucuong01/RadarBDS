import shutil
import sys
import tempfile
import unittest
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
        connection.close_all()
        self.patches = [
            mock.patch.object(connection, "DB_PATH", self.db_path),
            mock.patch.object(app_module.db_mod, "DB_PATH", self.db_path),
        ]
        for p in self.patches:
            p.start()

        init_schema()
        self.client = app_module.app.test_client()
        self.listing_id = self._seed_fresh_signal()

    def tearDown(self):
        from db import connection

        connection.close_all()
        for p in reversed(self.patches):
            p.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

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
                    'facebook', 'fresh-guest-visible', 'https://example.test/fresh',
                    'Fresh guest-visible signal', 'Fresh listing description',
                    'Tân An', 100, 'dat_nen', 2.0, 20.0,
                    0, 0, 0, 0, 0, datetime('now'), datetime('now')
                )
                """
            )
            listing_id = cur.lastrowid
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
        response = self.client.get("/api/signals?city=Khac&limit=5")
        self.assertEqual(response.status_code, 200)

        signals = response.get_json()["signals"]
        self.assertEqual(len(signals), 1)
        row = signals[0]
        self.assertEqual(row["title"], "Fresh guest-visible signal")
        self.assertEqual(row["price_ty"], 2.0)
        self.assertEqual(row["url"], None)
        self.assertNotIn("locked_reason", row)
        self.assertFalse(row["is_fresh_locked"])

    def test_guest_sees_fresh_listing_detail_without_source_url(self):
        response = self.client.get(f"/api/listing/{self.listing_id}")
        self.assertEqual(response.status_code, 200)

        data = response.get_json()
        self.assertEqual(data["title"], "Fresh guest-visible signal")
        self.assertEqual(data["description"], "Fresh listing description")
        self.assertEqual(data["price_ty"], 2.0)
        self.assertEqual(data["url"], None)


if __name__ == "__main__":
    unittest.main()
