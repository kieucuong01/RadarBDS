import shutil
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class ReprocessReviewHiddenPolicyTest(unittest.TestCase):
    def setUp(self):
        from db import connection
        from db.schema import init_schema

        self.tmpdir = Path(tempfile.mkdtemp())
        self.db_path = self.tmpdir / "radar_reprocess_hidden.db"
        self.token = uuid.uuid4().hex
        self.inserted_ids = []
        connection.close_all()
        self.db_patch = mock.patch.object(connection, "DB_PATH", self.db_path)
        self.db_patch.start()
        init_schema()
        self._delete_test_rows()

    def tearDown(self):
        from db import connection

        try:
            self._delete_test_rows()
        finally:
            connection.close_all()
            self.db_patch.stop()
            shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _delete_test_rows(self):
        from db.connection import get_conn

        ids = list(getattr(self, "inserted_ids", []) or [])
        with get_conn() as conn:
            if ids:
                placeholders = ",".join("?" for _ in ids)
                conn.execute(f"DELETE FROM valuation_results WHERE listing_id IN ({placeholders})", ids)
                conn.execute(f"DELETE FROM ai_training_feedback WHERE listing_id IN ({placeholders})", ids)
                conn.execute(f"DELETE FROM listings WHERE id IN ({placeholders})", ids)
            conn.execute("DELETE FROM listings WHERE url LIKE ?", (f"https://t.test/{self.token}/%",))

    def _test_url(self, url):
        return url.replace("https://t.test/", f"https://t.test/{self.token}/", 1)

    def _reprocess_inserted(self):
        from cleansing.reprocess import reprocess_valuation

        ids = list(self.inserted_ids)
        return reprocess_valuation(incremental_ids=ids, training_ids=ids)

    def _insert_listing(self, *, url, ppm2, review_hidden=0, source="guland",
                        crawled_at="2026-05-01T00:00:00", posted_at=None,
                        suspicious_bait=0, title="Tin test", description=None):
        from db.connection import get_conn

        area_m2 = 100.0
        price_ty = round(ppm2 * area_m2 / 1000, 3)
        url = self._test_url(url)
        with get_conn() as conn:
            listing_id = conn.execute(
                """
                INSERT INTO listings (
                    source, url, title, description, area, ward, property_type, tx_type,
                    price_per_m2, price_ty, area_m2, road_type, road_tier,
                    has_so, crawled_at, posted_at, review_hidden, suspicious_bait
                )
                VALUES (
                    ?, ?, ?, ?, 'Tan An', 'Tan An', 'dat_nen',
                    'ban', ?, ?, ?, 'duong_nhua', 2, 1,
                    ?, ?, ?, ?
                )
                """,
                (
                    source, url, title, description, ppm2, price_ty, area_m2,
                    crawled_at, posted_at, review_hidden, suspicious_bait,
                ),
            ).lastrowid
        self.inserted_ids.append(listing_id)
        return listing_id

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
            self._insert_listing(
                url=f"https://t.test/visible-{i}",
                ppm2=15.0,
                source="facebook",
            )
            for i in range(18)
        ]

        for i in range(18):
            lid = self._insert_listing(
                url=f"https://t.test/hidden-bad-high-{i}",
                ppm2=60.0,
                review_hidden=1,
                source="facebook",
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
            source="facebook",
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
            source="facebook",
        )
        self._insert_feedback(
            fake_lid,
            "fake_price",
            extraction="all_correct",
            valuation="fake_price",
        )

        stats = self._reprocess_inserted()
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

    def test_hidden_bad_data_wrong_extraction_can_recheck_with_low_sample_segment(self):
        from cleansing.reprocess import reprocess_valuation
        from db.connection import get_conn

        for i in range(3):
            self._insert_listing(
                url=f"https://t.test/low-sample-visible-{i}",
                ppm2=15.0,
                source="facebook",
            )

        visible_cheap = self._insert_listing(
            url="https://t.test/low-sample-visible-cheap",
            ppm2=9.0,
            source="facebook",
        )
        recheck_lid = self._insert_listing(
            url="https://t.test/low-sample-hidden-recheck",
            ppm2=9.0,
            review_hidden=1,
            source="facebook",
        )
        self._insert_feedback(
            recheck_lid,
            "bad_data",
            extraction="wrong_road",
            valuation="cannot_price",
        )

        self._reprocess_inserted()

        with get_conn() as conn:
            visible = conn.execute(
                "SELECT is_signal FROM valuation_results WHERE listing_id=?",
                (visible_cheap,),
            ).fetchone()
            recheck = conn.execute(
                "SELECT is_signal FROM valuation_results WHERE listing_id=?",
                (recheck_lid,),
            ).fetchone()

        self.assertIsNotNone(visible)
        self.assertEqual(visible["is_signal"], 0)
        self.assertIsNotNone(recheck)
        self.assertEqual(recheck["is_signal"], 1)

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

        self._reprocess_inserted()

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

    def test_reprocess_marks_two_week_old_guland_signal_for_source_qc(self):
        from cleansing.reprocess import reprocess_valuation
        from db.connection import get_conn

        for i in range(30):
            self._insert_listing(
                url=f"https://t.test/facebook-baseline-two-week-{i}",
                ppm2=15.0,
                source="facebook",
            )

        stale_lid = self._insert_listing(
            url="https://t.test/two-week-guland",
            ppm2=8.5,
            source="guland",
            posted_at="2026-04-17T00:00:00",
            crawled_at="2026-05-01T00:00:00",
        )
        trusted_stale_lid = self._insert_listing(
            url="https://t.test/trusted-two-week-guland",
            ppm2=8.5,
            source="guland",
            posted_at="2026-04-17T00:00:00",
            crawled_at="2026-05-01T00:00:00",
        )
        self._insert_feedback(
            trusted_stale_lid,
            "cheap_real",
            extraction="all_correct",
            valuation="cheap_real",
        )

        self._reprocess_inserted()

        with get_conn() as conn:
            stale = conn.execute(
                """
                SELECT is_signal, source_quality_recheck, source_quality_flags
                FROM valuation_results
                WHERE listing_id=?
                """,
                (stale_lid,),
            ).fetchone()
            trusted = conn.execute(
                """
                SELECT is_signal, source_quality_recheck, source_quality_flags
                FROM valuation_results
                WHERE listing_id=?
                """,
                (trusted_stale_lid,),
            ).fetchone()

        self.assertIsNotNone(stale)
        self.assertEqual(stale["is_signal"], 0)
        self.assertEqual(stale["source_quality_recheck"], 1)
        self.assertIn("old_guland_post", stale["source_quality_flags"])

        self.assertIsNotNone(trusted)
        self.assertEqual(trusted["is_signal"], 1)
        self.assertEqual(trusted["source_quality_recheck"], 0)
        self.assertNotIn("old_guland_post", trusted["source_quality_flags"] or "")

    def test_reprocess_marks_guland_cluster_flood_for_source_qc(self):
        from cleansing.reprocess import reprocess_valuation
        from db.connection import get_conn

        for i in range(30):
            self._insert_listing(
                url=f"https://t.test/facebook-baseline-cluster-{i}",
                ppm2=15.0,
                source="facebook",
            )

        clustered_ids = [
            self._insert_listing(
                url=f"https://t.test/guland-cluster-{i}",
                ppm2=8.5,
                source="guland",
                posted_at="2026-05-01T00:00:00",
                crawled_at="2026-05-01T00:00:00",
                title=f"Ban gap lo dat flood {i}",
            )
            for i in range(4)
        ]
        singleton_id = self._insert_listing(
            url="https://t.test/guland-singleton",
            ppm2=8.5,
            source="guland",
            posted_at="2026-05-01T00:00:00",
            crawled_at="2026-05-01T00:00:00",
            title="Ban gap lo dat rieng le",
        )

        self._reprocess_inserted()

        with get_conn() as conn:
            clustered = conn.execute(
                f"""
                SELECT listing_id, is_signal, source_quality_recheck,
                       source_quality_flags
                FROM valuation_results
                WHERE listing_id IN ({','.join('?' for _ in clustered_ids)})
                ORDER BY listing_id
                """,
                clustered_ids,
            ).fetchall()
            singleton = conn.execute(
                """
                SELECT is_signal, source_quality_recheck, source_quality_flags
                FROM valuation_results
                WHERE listing_id=?
                """,
                (singleton_id,),
            ).fetchone()

        self.assertEqual(len(clustered), 4)
        for row in clustered:
            self.assertEqual(row["is_signal"], 0)
            self.assertEqual(row["source_quality_recheck"], 1)
            self.assertIn("guland_cluster_flood", row["source_quality_flags"])

        self.assertIsNotNone(singleton)
        self.assertEqual(singleton["is_signal"], 1)
        self.assertEqual(singleton["source_quality_recheck"], 0)
        self.assertNotIn("guland_cluster_flood", singleton["source_quality_flags"] or "")


if __name__ == "__main__":
    unittest.main()
