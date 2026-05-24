import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class ReprocessReviewHiddenPolicyTest(unittest.TestCase):
    def setUp(self):
        from db import connection
        from db.schema import init_schema

        self.tmpdir = Path(tempfile.mkdtemp())
        self.db_path = self.tmpdir / "radar_reprocess_hidden.db"
        connection.close_all()
        self.db_patch = mock.patch.object(connection, "DB_PATH", self.db_path)
        self.db_patch.start()
        init_schema()

    def tearDown(self):
        from db import connection

        connection.close_all()
        self.db_patch.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _insert_listing(self, *, url, ppm2, review_hidden=0, source="guland",
                        crawled_at="2026-05-01T00:00:00", posted_at=None,
                        suspicious_bait=0):
        from db.connection import get_conn

        area_m2 = 100.0
        price_ty = round(ppm2 * area_m2 / 1000, 3)
        with get_conn() as conn:
            return conn.execute(
                """
                INSERT INTO listings (
                    source, url, title, area, ward, property_type, tx_type,
                    price_per_m2, price_ty, area_m2, road_type, road_tier,
                    has_so, crawled_at, posted_at, review_hidden, suspicious_bait
                )
                VALUES (
                    ?, ?, 'Tin test', 'Tan An', 'Tan An', 'dat_nen',
                    'ban', ?, ?, ?, 'duong_nhua', 2, 1,
                    ?, ?, ?, ?
                )
                """,
                (source, url, ppm2, price_ty, area_m2, crawled_at, posted_at, review_hidden, suspicious_bait),
            ).lastrowid

    def _insert_feedback(self, listing_id, verdict, extraction="all_correct",
                         valuation=None):
        from db.connection import get_conn

        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO ai_training_feedback (
                    listing_id, actor, verdict, extraction_verdict,
                    valuation_verdict
                )
                VALUES (?, 'admin', ?, ?, ?)
                """,
                (listing_id, verdict, extraction, valuation or verdict),
            )

    def test_reprocess_valuation_values_hidden_bad_data_but_excludes_it_from_training(self):
        from cleansing.reprocess import reprocess_valuation
        from db.connection import get_conn

        visible_ids = [
            self._insert_listing(url=f"https://t.test/visible-{i}", ppm2=15.0)
            for i in range(18)
        ]

        for i in range(18):
            lid = self._insert_listing(
                url=f"https://t.test/hidden-bad-high-{i}",
                ppm2=60.0,
                review_hidden=1,
            )
            self._insert_feedback(
                lid,
                "bad_data",
                extraction="wrong_area",
                valuation="cannot_price",
            )

        recheck_lid = self._insert_listing(
            url="https://t.test/hidden-bad-recheck",
            ppm2=9.0,
            review_hidden=1,
        )
        self._insert_feedback(
            recheck_lid,
            "bad_data",
            extraction="wrong_price",
            valuation="cannot_price",
        )

        fake_lid = self._insert_listing(
            url="https://t.test/hidden-fake-price",
            ppm2=9.0,
            review_hidden=1,
        )
        self._insert_feedback(
            fake_lid,
            "fake_price",
            extraction="all_correct",
            valuation="fake_price",
        )

        stats = reprocess_valuation()
        self.assertGreater(stats["total"], 0)

        with get_conn() as conn:
            visible = conn.execute(
                """
                SELECT fair_ppm2, is_signal
                FROM valuation_results
                WHERE listing_id=?
                """,
                (visible_ids[0],),
            ).fetchone()
            recheck = conn.execute(
                """
                SELECT fair_ppm2, is_signal
                FROM valuation_results
                WHERE listing_id=?
                """,
                (recheck_lid,),
            ).fetchone()
            fake = conn.execute(
                "SELECT id FROM valuation_results WHERE listing_id=?",
                (fake_lid,),
            ).fetchone()

        self.assertIsNotNone(visible)
        self.assertLess(visible["fair_ppm2"], 25.0)
        self.assertEqual(visible["is_signal"], 0)

        self.assertIsNotNone(recheck)
        self.assertEqual(recheck["is_signal"], 1)

        self.assertIsNone(fake)

    def test_reprocess_marks_old_guland_signal_for_source_qc_without_pushing_signal(self):
        from cleansing.reprocess import reprocess_valuation
        from db.connection import get_conn

        for i in range(30):
            self._insert_listing(
                url=f"https://t.test/facebook-baseline-{i}",
                ppm2=15.0,
                source="facebook",
            )

        old_guland_lid = self._insert_listing(
            url="https://t.test/old-guland",
            ppm2=8.5,
            source="guland",
            posted_at="2026-01-01T00:00:00",
            crawled_at="2026-05-01T00:00:00",
        )
        trusted_old_guland_lid = self._insert_listing(
            url="https://t.test/trusted-old-guland",
            ppm2=8.5,
            source="guland",
            posted_at="2026-01-01T00:00:00",
            crawled_at="2026-05-01T00:00:00",
        )
        self._insert_feedback(
            trusted_old_guland_lid,
            "all_correct",
            extraction="all_correct",
            valuation="cheap_real",
        )
        fresh_guland_lid = self._insert_listing(
            url="https://t.test/fresh-guland",
            ppm2=8.5,
            source="guland",
            posted_at="2026-05-01T00:00:00",
            crawled_at="2026-05-01T00:00:00",
        )

        reprocess_valuation()

        with get_conn() as conn:
            old_row = conn.execute(
                """
                SELECT fair_ppm2, is_signal, source_quality_recheck,
                       source_quality_flags
                FROM valuation_results
                WHERE listing_id=?
                """,
                (old_guland_lid,),
            ).fetchone()
            fresh_row = conn.execute(
                """
                SELECT fair_ppm2, is_signal, source_quality_recheck,
                       source_quality_flags
                FROM valuation_results
                WHERE listing_id=?
                """,
                (fresh_guland_lid,),
            ).fetchone()
            trusted_row = conn.execute(
                """
                SELECT fair_ppm2, is_signal, source_quality_recheck,
                       source_quality_flags
                FROM valuation_results
                WHERE listing_id=?
                """,
                (trusted_old_guland_lid,),
            ).fetchone()

        self.assertIsNotNone(old_row)
        self.assertGreater(old_row["fair_ppm2"], 0)
        self.assertEqual(old_row["is_signal"], 0)
        self.assertEqual(old_row["source_quality_recheck"], 1)
        self.assertIn("old_guland_post", old_row["source_quality_flags"])

        self.assertIsNotNone(fresh_row)
        self.assertEqual(fresh_row["is_signal"], 1)
        self.assertEqual(fresh_row["source_quality_recheck"], 0)

        self.assertIsNotNone(trusted_row)
        self.assertEqual(trusted_row["is_signal"], 1)
        self.assertEqual(trusted_row["source_quality_recheck"], 0)
        self.assertNotIn("old_guland_post", trusted_row["source_quality_flags"] or "")


if __name__ == "__main__":
    unittest.main()
