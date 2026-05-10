import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _listing_rec(**overrides):
    rec = {
        "raw_id": None,
        "source": "guland",
        "source_id": "1123539",
        "url": "https://guland.vn/post/dat-chinh-chu-1134m2-truc-duong-dx84-tdm-binh-duong-1123539",
        "title": "Đất chính chủ 113,4m2, trục đường DX84, TDM, Bình Dương",
        "description": "Đất chính chủ 113,4m2, trục đường DX84",
        "area": "Phú Lợi",
        "ward": "Phú Lợi",
        "raw_area_text": "113,4m2",
        "price_ty": 1.74,
        "price_per_m2": 15.4,
        "area_m2": 113.0,
        "property_type": "dat_nen",
        "tx_type": "ban",
        "frontage_m": None,
        "depth_m": None,
        "road_width_m": None,
        "road_type": "duong_nhua",
        "road_tier": 2,
        "has_so": True,
        "is_hot": False,
        "contact_phone": None,
        "seller_name": None,
        "post_date": "2026-05-06",
    }
    rec.update(overrides)
    return rec


class PriceHistoryTest(unittest.TestCase):
    def setUp(self):
        from db import connection
        from db.schema import init_schema

        self.tmpdir = Path(tempfile.mkdtemp())
        self.db_path = self.tmpdir / "radar_test.db"
        connection.close_all()
        self.db_path_patch = mock.patch.object(connection, "DB_PATH", self.db_path)
        self.db_path_patch.start()
        init_schema()

    def tearDown(self):
        from db import connection

        connection.close_all()
        self.db_path_patch.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _history_rows(self):
        from db.connection import get_conn

        with get_conn() as conn:
            return conn.execute("""
                SELECT price_ty, price_per_m2, crawl_run_id
                FROM price_history
                ORDER BY recorded_at ASC, id ASC
            """).fetchall()

    def test_upsert_listing_same_price_does_not_duplicate_history(self):
        from db.listings import upsert_listing

        listing_id, is_new = upsert_listing(_listing_rec(), crawl_run_id=1)
        self.assertTrue(is_new)

        same_listing_id, is_new = upsert_listing(_listing_rec(), crawl_run_id=2)
        self.assertEqual(same_listing_id, listing_id)
        self.assertFalse(is_new)

        rows = self._history_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["price_ty"], 1.74)
        self.assertEqual(rows[0]["crawl_run_id"], 1)

    def test_upsert_listing_changed_price_adds_one_history_snapshot(self):
        from db.listings import upsert_listing

        upsert_listing(_listing_rec(), crawl_run_id=1)
        upsert_listing(_listing_rec(price_ty=1.70, price_per_m2=15.04), crawl_run_id=2)
        upsert_listing(_listing_rec(price_ty=1.70, price_per_m2=15.04), crawl_run_id=3)

        rows = self._history_rows()
        self.assertEqual([r["price_ty"] for r in rows], [1.74, 1.70])
        self.assertEqual([r["crawl_run_id"] for r in rows], [1, 2])

    def test_upsert_listing_over_40pct_drop_marks_suspicious_bait(self):
        from db.connection import get_conn
        from db.listings import upsert_listing

        listing_id, _ = upsert_listing(_listing_rec(price_ty=2.0, price_per_m2=20.0), crawl_run_id=1)
        upsert_listing(_listing_rec(price_ty=1.0, price_per_m2=10.0), crawl_run_id=2)

        with get_conn() as conn:
            row = conn.execute("""
                SELECT price_dropped, price_drop_pct, suspicious_bait
                FROM listings
                WHERE id = ?
            """, (listing_id,)).fetchone()

        self.assertEqual(row["price_dropped"], 0)
        self.assertIsNone(row["price_drop_pct"])
        self.assertEqual(row["suspicious_bait"], 1)

    def test_history_api_compacts_repeated_snapshots_and_current_price(self):
        from app import app
        from db.connection import get_conn

        with get_conn() as conn:
            cur = conn.execute("""
                INSERT INTO listings (
                    source, source_id, url, title, ward, area_m2, property_type,
                    price_ty, price_per_m2, updated_at, probably_sold
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """, (
                "guland", "1123539", "https://example.test/dx84",
                "Đất chính chủ 113,4m2, trục đường DX84", "Phú Lợi", 113.0,
                "dat_nen", 1.74, 15.4, "2026-05-07T12:25:35",
            ))
            listing_id = cur.lastrowid
            conn.executemany("""
                INSERT INTO price_history (listing_id, price_ty, price_per_m2, recorded_at)
                VALUES (?, ?, ?, ?)
            """, [
                (listing_id, 1.74, 15.4, "2026-05-06 22:58:26"),
                (listing_id, 1.74, 15.4, "2026-05-07 01:25:13"),
                (listing_id, 1.74, 15.4, "2026-05-07 05:25:35"),
            ])

        response = app.test_client().get(f"/api/history/{listing_id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["history"], [{"date": "2026-05-06", "price_ty": 1.74}])


if __name__ == "__main__":
    unittest.main()
