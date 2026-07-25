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

    def test_primary_images_keeps_original_order_while_legal_image_feature_disabled(self):
        import services.market_data as market_data

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        with mock.patch.object(market_data, "resolve_image_url", side_effect=lambda local, remote, prefer_thumb=False: local or remote):
            images = market_data._primary_images(conn, [1])
        conn.close()

        self.assertFalse(market_data.LEGAL_IMAGE_EVIDENCE_ENABLED)
        self.assertEqual(images[1], "data/images/land.jpg")

    def test_listing_detail_gallery_keeps_original_order_while_legal_image_feature_disabled(self):
        import services.market_data as market_data

        @contextmanager
        def fake_read_conn(_db_path=None):
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row

            class StaticCursor:
                def fetchone(self):
                    row = dict(conn.execute(
                        "SELECT * FROM listings WHERE id=1"
                    ).fetchone())
                    row.update({
                        "is_signal": 1,
                        "mos_pct": 0,
                        "fair_ppm2": 0,
                        "signal_score": 0,
                        "trust_tier": "candidate_signal",
                        "trust_score": 0,
                        "legal_status": "unverified",
                        "legal_flags": "",
                        "is_fresh_locked": 0,
                    })
                    return row

            class DetailConnection:
                def execute(self, sql, params=None):
                    if "FROM listings l" in sql:
                        return StaticCursor()
                    return conn.execute(sql, params or ())

                def close(self):
                    conn.close()

            try:
                yield DetailConnection()
            finally:
                conn.close()

        with mock.patch.object(market_data, "_read_conn", fake_read_conn), \
             mock.patch.object(market_data, "resolve_image_url", side_effect=lambda local, remote, prefer_thumb=False: local or remote):
            detail = market_data.load_listing_detail(str(self.db_path), 1, tier="admin")

        self.assertEqual(detail["images"], ["data/images/land.jpg", "data/images/sohong.jpg"])

    def test_signal_row_hides_legal_doc_image_presence_while_feature_disabled(self):
        import services.market_data as market_data

        row = {
            "id": 1,
            "title": "Tin co anh so hong",
            "mos_pct": 35.5,
            "actual_ppm2": 2.4,
            "fair_ppm2": 4.1,
            "area_m2": 100.0,
            "price_ty": 0.24,
            "property_type": "dat_tho_cu",
            "is_hot": 0,
            "price_dropped": 0,
            "suspicious_bait": 0,
            "price_drop_pct": None,
            "price_first_ty": None,
            "duplicate_of_id": None,
            "url": "https://example.test/listing/1",
            "posted_at": "2026-05-01",
            "crawled_at": "2026-05-01",
            "ward": "Tan An",
            "signal_score": 80,
            "trust_tier": "candidate_signal",
            "trust_score": 0,
            "legal_status": "unverified",
            "legal_flags": "",
            "has_legal_doc_image": 1,
            "source": "guland",
            "road_tier": 3,
            "has_so": 1,
            "is_fresh_locked": 0,
        }

        record = market_data._format_signal_row(row, primary_img="data/images/sohong.jpg", tier="admin")

        self.assertFalse(record["has_legal_doc_image"])
        self.assertEqual(record["primary_img"], "data/images/sohong.jpg")

    def test_signal_row_defaults_has_so_to_true_unless_title_is_explicit_no_so(self):
        import services.market_data as market_data

        row = {
            "id": 1,
            "title": "Tin co anh so hong",
            "mos_pct": 35.5,
            "actual_ppm2": 2.4,
            "fair_ppm2": 4.1,
            "area_m2": 100.0,
            "price_ty": 0.24,
            "property_type": "dat_tho_cu",
            "is_hot": 0,
            "price_dropped": 0,
            "suspicious_bait": 0,
            "price_drop_pct": None,
            "price_first_ty": None,
            "duplicate_of_id": None,
            "url": "https://example.test/listing/1",
            "posted_at": "2026-05-01",
            "crawled_at": "2026-05-01",
            "ward": "Tan An",
            "signal_score": 80,
            "trust_tier": "candidate_signal",
            "trust_score": 0,
            "legal_status": "unverified",
            "legal_flags": "",
            "has_legal_doc_image": 0,
            "source": "guland",
            "road_tier": 3,
            "has_so": 0,
            "is_fresh_locked": 0,
        }

        default_record = market_data._format_signal_row(row, primary_img="", tier="admin")
        no_so_record = market_data._format_signal_row(
            {**row, "title": "Dat vi bang giay tay, chua co so"},
            primary_img="",
            tier="admin",
        )

        self.assertTrue(default_record["has_so"])
        self.assertFalse(no_so_record["has_so"])


if __name__ == "__main__":
    unittest.main()
