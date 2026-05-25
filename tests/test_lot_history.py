import shutil
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class LotHistoryApiTest(unittest.TestCase):
    def setUp(self):
        from db import connection
        from db.schema import init_schema
        import app as app_module

        self.tmpdir = Path(tempfile.mkdtemp())
        self.db_path = self.tmpdir / "radar_lot_history.db"
        self.token = uuid.uuid4().hex
        self.url_prefix = f"https://lot-history-{self.token}.test"
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
        self._seed()

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

    def _insert_listing(self, conn, **kw):
        defaults = {
            "source": "facebook",
            "source_id": f"src-{self.token}",
            "url": f"{self.url_prefix}/src",
            "title": "Listing",
            "ward": f"LotWard{self.token[:8]}",
            "area_m2": 100,
            "property_type": "dat_nen",
            "price_ty": 2.0,
            "price_per_m2": 20,
            "price_first_ty": 2.0,
            "price_dropped": 0,
            "price_drop_pct": None,
            "probably_sold": 0,
            "possibly_duplicate": 0,
            "duplicate_of_id": None,
            "posted_at": "2026-05-01",
        }
        defaults.update(kw)
        cur = conn.execute("""
            INSERT INTO listings (
                source, source_id, url, title, ward, area_m2, property_type,
                price_ty, price_per_m2, price_first_ty, price_dropped,
                price_drop_pct, probably_sold, possibly_duplicate, duplicate_of_id,
                posted_at
            ) VALUES (
                :source, :source_id, :url, :title, :ward, :area_m2, :property_type,
                :price_ty, :price_per_m2, :price_first_ty, :price_dropped,
                :price_drop_pct, :probably_sold, :possibly_duplicate, :duplicate_of_id,
                :posted_at
            )
        """, defaults)
        listing_id = cur.lastrowid
        self.listing_ids.append(listing_id)
        return listing_id

    def _seed(self):
        from db.connection import get_conn

        with get_conn() as conn:
            self.canonical_id = self._insert_listing(
                conn,
                source_id=f"fb-old-{self.token}",
                url=f"{self.url_prefix}/fb-old",
                title="Facebook canonical",
                posted_at="2026-05-01",
            )
            self.facebook_same_price_id = self._insert_listing(
                conn,
                source_id=f"fb-same-{self.token}",
                url=f"{self.url_prefix}/fb-same",
                title="Facebook same price repost",
                price_ty=2.0,
                possibly_duplicate=1,
                duplicate_of_id=self.canonical_id,
                posted_at="2026-05-03",
            )
            self.guland_same_price_id = self._insert_listing(
                conn,
                source="guland",
                source_id=f"gl-same-{self.token}",
                url=f"{self.url_prefix}/gl-same",
                title="Guland same price repost",
                price_ty=2.0,
                possibly_duplicate=1,
                duplicate_of_id=self.canonical_id,
                posted_at="2026-05-04",
            )
            self.guland_drop_id = self._insert_listing(
                conn,
                source="guland",
                source_id=f"gl-drop-{self.token}",
                url=f"{self.url_prefix}/gl-drop",
                title="Guland lower repost",
                price_ty=1.9,
                price_first_ty=2.0,
                price_dropped=1,
                price_drop_pct=5.0,
                possibly_duplicate=1,
                duplicate_of_id=self.canonical_id,
                posted_at="2026-05-05",
            )

    def test_lot_history_includes_facebook_same_price_and_non_facebook_drop_only(self):
        response = self.client.get(f"/api/history/{self.canonical_id}")
        self.assertEqual(response.status_code, 200)
        lot_history = response.get_json()["lot_history"]
        ids = [row["id"] for row in lot_history]

        self.assertIn(self.canonical_id, ids)
        self.assertIn(self.facebook_same_price_id, ids)
        self.assertIn(self.guland_drop_id, ids)
        self.assertNotIn(self.guland_same_price_id, ids)


if __name__ == "__main__":
    unittest.main()
