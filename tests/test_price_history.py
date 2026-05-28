import shutil
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _listing_rec(**overrides):
    rec = {
        "raw_id": None,
        "source": "guland",
        "source_id": "1123539",
        "url": "https://guland.vn/post/dat-chinh-chu-1134m2-truc-duong-dx84-tdm-binh-duong-1123539",
        "title": "Dat chinh chu 113,4m2, truc duong DX84, TDM, Binh Duong",
        "description": "Dat chinh chu 113,4m2, truc duong DX84",
        "area": "Phu Loi",
        "ward": "Phu Loi",
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
        self.token = uuid.uuid4().hex
        self.url_prefix = f"https://price-history-{self.token}.test"
        self.source_id = f"price-history-{self.token}"
        self.listing_ids = []
        connection.close_all()
        self.db_path_patch = mock.patch.object(connection, "DB_PATH", self.db_path)
        self.db_path_patch.start()
        init_schema()
        self._delete_test_rows()

    def tearDown(self):
        from db import connection

        self._delete_test_rows()
        connection.close_all()
        self.db_path_patch.stop()
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

    def _rec(self, **overrides):
        data = {
            "source_id": self.source_id,
            "url": f"{self.url_prefix}/listing",
        }
        data.update(overrides)
        return _listing_rec(**data)

    def _track(self, listing_id):
        self.listing_ids.append(listing_id)
        return listing_id

    def _history_rows(self, listing_id):
        from db.connection import get_conn

        with get_conn() as conn:
            return conn.execute("""
                SELECT price_ty, price_per_m2, crawl_run_id
                FROM price_history
                WHERE listing_id = ?
                ORDER BY recorded_at ASC, id ASC
            """, (listing_id,)).fetchall()

    def test_upsert_listing_same_price_does_not_duplicate_history(self):
        from db.listings import upsert_listing

        listing_id, is_new = upsert_listing(self._rec(), crawl_run_id=1)
        self._track(listing_id)
        self.assertTrue(is_new)

        same_listing_id, is_new = upsert_listing(self._rec(), crawl_run_id=2)
        self.assertEqual(same_listing_id, listing_id)
        self.assertFalse(is_new)

        rows = self._history_rows(listing_id)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["price_ty"], 1.74)
        self.assertEqual(rows[0]["crawl_run_id"], 1)

    def test_upsert_listing_changed_price_adds_one_history_snapshot(self):
        from db.listings import upsert_listing

        listing_id, _ = upsert_listing(self._rec(), crawl_run_id=1)
        self._track(listing_id)
        upsert_listing(self._rec(price_ty=1.70, price_per_m2=15.04), crawl_run_id=2)
        upsert_listing(self._rec(price_ty=1.70, price_per_m2=15.04), crawl_run_id=3)

        rows = self._history_rows(listing_id)
        self.assertEqual([r["price_ty"] for r in rows], [1.74, 1.70])
        self.assertEqual([r["crawl_run_id"] for r in rows], [1, 2])

    def test_upsert_listing_missing_price_or_area_preserves_last_known_values(self):
        from db.connection import get_conn
        from db.listings import upsert_listing

        listing_id, _ = upsert_listing(self._rec(), crawl_run_id=1)
        self._track(listing_id)

        same_listing_id, is_new = upsert_listing(
            self._rec(price_ty=None, price_per_m2=None, area_m2=None),
            crawl_run_id=2,
        )

        self.assertEqual(same_listing_id, listing_id)
        self.assertFalse(is_new)
        with get_conn() as conn:
            row = conn.execute(
                "SELECT price_ty, price_per_m2, area_m2 FROM listings WHERE id=?",
                (listing_id,),
            ).fetchone()

        self.assertEqual(row["price_ty"], 1.74)
        self.assertEqual(row["price_per_m2"], 15.4)
        self.assertEqual(row["area_m2"], 113.0)

    def test_upsert_listing_existing_row_enriches_dimensions_from_new_parse(self):
        from db.connection import get_conn
        from db.listings import upsert_listing

        listing_id, _ = upsert_listing(self._rec(), crawl_run_id=1)
        self._track(listing_id)

        same_listing_id, is_new = upsert_listing(
            self._rec(frontage_m=4.0, depth_m=28.0),
            crawl_run_id=2,
        )

        self.assertEqual(same_listing_id, listing_id)
        self.assertFalse(is_new)
        with get_conn() as conn:
            row = conn.execute(
                "SELECT frontage_m, depth_m FROM listings WHERE id=?",
                (listing_id,),
            ).fetchone()

        self.assertEqual(row["frontage_m"], 4.0)
        self.assertEqual(row["depth_m"], 28.0)

    def test_upsert_listing_over_40pct_drop_marks_suspicious_bait(self):
        from db.connection import get_conn
        from db.listings import upsert_listing

        listing_id, _ = upsert_listing(self._rec(price_ty=2.0, price_per_m2=20.0), crawl_run_id=1)
        self._track(listing_id)
        upsert_listing(self._rec(price_ty=1.0, price_per_m2=10.0), crawl_run_id=2)

        with get_conn() as conn:
            row = conn.execute("""
                SELECT price_dropped, price_drop_pct, suspicious_bait
                FROM listings
                WHERE id = ?
            """, (listing_id,)).fetchone()

        self.assertEqual(row["price_dropped"], 0)
        self.assertIsNone(row["price_drop_pct"])
        self.assertEqual(row["suspicious_bait"], 1)

    def test_dedup_reconciles_price_first_from_history_before_drop_flag(self):
        from cleansing.dedup import _reconcile_price_first_from_history
        from db.connection import get_conn

        with get_conn() as conn:
            cur = conn.execute("""
                INSERT INTO listings (
                    source, source_id, url, title, ward, area_m2, property_type,
                    price_ty, price_per_m2, price_first_ty, price_dropped,
                    price_drop_pct, suspicious_bait, probably_sold
                ) VALUES (
                    'facebook', ?, ?, 'Same URL dropped but first price was reset',
                    'Tan Dinh', 150, 'dat_nen', 1.0, 6.67, 1.0, 0,
                    NULL, 0, 0
                )
            """, (f"{self.source_id}-history-reconcile", f"{self.url_prefix}/history-reconcile"))
            listing_id = self._track(cur.lastrowid)
            conn.executemany("""
                INSERT INTO price_history (listing_id, price_ty, price_per_m2, recorded_at)
                VALUES (?, ?, ?, ?)
            """, [
                (listing_id, 1.6, 10.67, "2026-05-26 16:38:30"),
                (listing_id, 1.0, 6.67, "2026-05-28 09:39:54"),
            ])

            _reconcile_price_first_from_history(conn)

            row = conn.execute("""
                SELECT price_first_ty, price_dropped, price_drop_pct, suspicious_bait
                FROM listings
                WHERE id=?
            """, (listing_id,)).fetchone()

        self.assertEqual(row["price_first_ty"], 1.6)
        self.assertEqual(row["price_dropped"], 1)
        self.assertAlmostEqual(row["price_drop_pct"], 37.5)
        self.assertEqual(row["suspicious_bait"], 0)

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
                "guland", f"{self.source_id}-api", f"{self.url_prefix}/dx84",
                "Dat chinh chu 113,4m2, truc duong DX84", "Phu Loi", 113.0,
                "dat_nen", 1.74, 15.4, "2026-05-07T12:25:35",
            ))
            listing_id = self._track(cur.lastrowid)
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
