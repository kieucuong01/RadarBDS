import shutil
import sqlite3
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class MarketDataImageOrderingTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.db_path = self.tmpdir / "market_images.db"
        conn = sqlite3.connect(self.db_path)
        conn.executescript(
            """
            CREATE TABLE listings (
                id INTEGER PRIMARY KEY,
                source TEXT,
                url TEXT,
                title TEXT,
                review_hidden INTEGER DEFAULT 0,
                is_blacklisted INTEGER DEFAULT 0,
                crawled_at TEXT,
                posted_at TEXT
            );
            CREATE TABLE valuation_results (
                listing_id INTEGER,
                is_signal INTEGER,
                mos_pct REAL,
                fair_ppm2 REAL,
                signal_score REAL,
                trust_tier TEXT,
                trust_score INTEGER,
                legal_status TEXT,
                legal_flags TEXT
            );
            CREATE TABLE price_history (
                listing_id INTEGER,
                recorded_at TEXT,
                price_ty REAL
            );
            CREATE TABLE listing_images (
                id INTEGER PRIMARY KEY,
                listing_id INTEGER,
                img_url TEXT,
                img_order INTEGER,
                img_type TEXT,
                local_path TEXT
            );
            CREATE TABLE legal_verifications (
                listing_id INTEGER PRIMARY KEY,
                status TEXT,
                confidence_score INTEGER,
                thua_so TEXT,
                to_ban_do TEXT,
                legal_area_m2 REAL,
                legal_residential_m2 REAL,
                legal_address TEXT,
                legal_ward TEXT,
                legal_road_text TEXT,
                legal_road_code TEXT,
                road_match_status TEXT,
                conflict_flags TEXT
            );
            """
        )
        conn.execute(
            """
            INSERT INTO listings (id, source, url, title, crawled_at)
            VALUES (1, 'guland', 'https://guland.test/post/1', 'Tin co so hong', '2026-05-01')
            """
        )
        conn.execute(
            "INSERT INTO valuation_results (listing_id, is_signal) VALUES (1, 1)"
        )
        conn.execute(
            """
            INSERT INTO listing_images (listing_id, img_url, img_order, img_type, local_path)
            VALUES
              (1, 'https://cdn.test/land.jpg', 0, 'cover', 'data/images/land.jpg'),
              (1, 'https://cdn.test/sohong.jpg', 3, 'so_hong', 'data/images/sohong.jpg')
            """
        )
        conn.commit()
        conn.close()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_primary_images_prefers_so_hong(self):
        import services.market_data as market_data

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        with mock.patch.object(market_data, "resolve_image_url", side_effect=lambda local, remote, prefer_thumb=False: local or remote):
            images = market_data._primary_images(conn, [1])
        conn.close()

        self.assertEqual(images[1], "data/images/sohong.jpg")

    def test_listing_detail_gallery_orders_so_hong_first(self):
        import services.market_data as market_data

        @contextmanager
        def fake_read_conn(_db_path=None):
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            try:
                yield conn
            finally:
                conn.close()

        with mock.patch.object(market_data, "_read_conn", fake_read_conn), \
             mock.patch.object(market_data, "resolve_image_url", side_effect=lambda local, remote, prefer_thumb=False: local or remote):
            detail = market_data.load_listing_detail(str(self.db_path), 1, tier="admin", delay_hours=0)

        self.assertEqual(detail["images"], ["data/images/sohong.jpg", "data/images/land.jpg"])


if __name__ == "__main__":
    unittest.main()
