import shutil
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class ReprocessMapLocationIsolationTest(unittest.TestCase):
    @mock.patch(
        "services.listing_location_backfill.backfill_listing_locations",
        return_value={"scanned": 2, "updated": 2},
    )
    def test_map_location_backfill_receives_incremental_ids(self, backfill):
        from cleansing.reprocess import _run_listing_map_backfill

        result = _run_listing_map_backfill([7, 9], full=False)

        self.assertEqual(result, {"scanned": 2, "updated": 2})
        backfill.assert_called_once_with(listing_ids=[7, 9], full=False)

    @mock.patch(
        "services.listing_location_backfill.backfill_listing_locations",
        side_effect=RuntimeError("map registry unavailable"),
    )
    def test_map_location_failure_is_isolated(self, _backfill):
        from cleansing.reprocess import _run_listing_map_backfill

        result = _run_listing_map_backfill([7], full=True)

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"], "map registry unavailable")

    @mock.patch(
        "services.listing_location_backfill.backfill_listing_locations",
        return_value={"scanned": 20, "updated": 5},
    )
    def test_full_map_location_backfill_is_explicitly_full(self, backfill):
        from cleansing.reprocess import _run_listing_map_backfill

        result = _run_listing_map_backfill([7, 9], full=True)

        self.assertEqual(result["scanned"], 20)
        backfill.assert_called_once_with(listing_ids=None, full=True)


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
                        suspicious_bait=0, title="Tin dau tu", description=None,
                        area_m2=100.0, property_type="dat_nen"):
        from db.connection import get_conn

        price_ty = round(ppm2 * area_m2 / 1000, 3)
        if description is None:
            description = f"Diện tích {area_m2:g}m2"
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
                    ?, ?, ?, ?, 'Tan An', 'Tan An', ?,
                    'ban', ?, ?, ?, 'duong_nhua', 2, 1,
                    ?, ?, ?, ?
                )
                """,
                (
                    source, url, title, description, property_type, ppm2, price_ty, area_m2,
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
                """
                SELECT is_signal, source_quality_recheck, source_quality_flags
                FROM valuation_results WHERE listing_id=?
                """,
                (visible_cheap,),
            ).fetchone()
            recheck = conn.execute(
                """
                SELECT is_signal, source_quality_recheck, source_quality_flags
                FROM valuation_results WHERE listing_id=?
                """,
                (recheck_lid,),
            ).fetchone()

        self.assertIsNotNone(visible)
        self.assertEqual(visible["is_signal"], 1)
        self.assertEqual(visible["source_quality_recheck"], 0)
        self.assertIn("low_segment_confidence", visible["source_quality_flags"])
        self.assertIsNotNone(recheck)
        self.assertEqual(recheck["is_signal"], 1)

    def test_positive_human_feedback_keeps_low_segment_signal_actionable(self):
        from db.connection import get_conn
        from services.signal_quality import is_actionable_signal

        for i in range(3):
            self._insert_listing(
                url=f"https://t.test/positive-low-sample-base-{i}",
                ppm2=15.0,
                source="facebook",
            )

        cheap_lid = self._insert_listing(
            url="https://t.test/positive-low-sample-cheap",
            ppm2=9.0,
            source="facebook",
        )
        self._insert_feedback(cheap_lid, "all_correct", valuation="cheap_real")

        self._reprocess_inserted()

        with get_conn() as conn:
            row = conn.execute(
                """
                SELECT is_signal, source_quality_recheck, source_quality_flags
                FROM valuation_results WHERE listing_id=?
                """,
                (cheap_lid,),
            ).fetchone()

        self.assertIsNotNone(row)
        self.assertEqual(row["is_signal"], 1)
        self.assertEqual(row["source_quality_recheck"], 0)
        self.assertNotIn("low_segment_confidence", row["source_quality_flags"] or "")
        self.assertTrue(is_actionable_signal(row))

    def test_reprocess_marks_bad_price_quality_flags_for_qc_not_actionable(self):
        from db.connection import get_conn
        from services.signal_quality import is_actionable_signal

        for i in range(30):
            self._insert_listing(
                url=f"https://t.test/quality-baseline-{i}",
                ppm2=15.0,
                source="facebook",
            )
        for i in range(18):
            self._insert_listing(
                url=f"https://t.test/quality-baseline-house-{i}",
                ppm2=35.0,
                source="facebook",
                property_type="nha_dat",
            )

        discount_lid = self._insert_listing(
            url="https://t.test/discount-as-price",
            ppm2=0.67,
            source="facebook",
            title="Rẻ hơn thị trường 100 triệu, lô đất DL12 Mỹ Phước 3",
            description="Diện tích 5x30m, sổ sẵn",
            area_m2=150.0,
        )
        down_payment_lid = self._insert_listing(
            url="https://t.test/down-payment-as-price",
            ppm2=7.58,
            source="facebook",
            title="Đưa trước 500 triệu còn lại ngân hàng hỗ trợ trả góp",
            description="Nhà tại Mỹ Phước diện tích 66m2",
            area_m2=66.0,
        )
        large_lot_lid = self._insert_listing(
            url="https://t.test/large-lot-risk",
            ppm2=5.0,
            source="facebook",
            title="Bán đất vườn mặt tiền DX72 Định Hòa hơn 1200m2",
            description="Lô lớn cần kiểm tra riêng trước khi coi là deal",
            area_m2=1200.0,
        )
        area_conflict_lid = self._insert_listing(
            url="https://t.test/area-dimension-conflict",
            ppm2=3.84,
            source="guland",
            title="B\u00e1n \u0111\u1ea5t 593m\u00b2 2.28 t\u1ef7 t\u1ea1i Ph\u01b0\u1eddng T\u01b0\u01a1ng B\u00ecnh Hi\u1ec7p",
            description="Di\u1ec7n t\u00edch 6 x24 th\u1ed5 c\u01b0 45 m. Gi\u00e1 2 t\u1ef7 280",
            area_m2=593.0,
        )
        source_category_conflict_lid = self._insert_listing(
            url="https://guland.vn/mua-ban-can-ho-chung-cu-dinh-hoa/source-category-conflict",
            ppm2=7.0,
            source="guland",
            title="B\u00e1n \u0111\u1ea5t \u0110\u1ecbnh Ho\u00e0 nh\u01b0ng source category l\u00e0 c\u0103n h\u1ed9",
            description="Di\u1ec7n t\u00edch 100 m\u00b2, \u0111\u1ea5t th\u1ed5 c\u01b0.",
            area_m2=100.0,
            property_type="dat_nen",
        )
        multi_lot_lid = self._insert_listing(
            url="https://guland.vn/post/lo-1-300m2-215ty-lo-2-4837m2-255ty-test",
            ppm2=7.17,
            source="guland",
            title="L\u00f4 1-300m2-2,15t\u1ef7/ L\u00f4 2-483,7m2-2,55t\u1ef7",
            description=(
                "L\u00f4 1-300m2-2,15t\u1ef7\n"
                "L\u00f4 2-483,7m2-2,55t\u1ef7\n"
                "15 ng\u00e0y c\u00f3 s\u1ed5.ch\u01b0a th\u1ed5 c\u01b0 h\u1ed7 tr\u1ee3 l\u00ean tho\u1ea3i m\u00e1i"
            ),
            area_m2=300.0,
            property_type="dat_nen",
        )
        approximate_price_lid = self._insert_listing(
            url="https://t.test/approximate-price",
            ppm2=6.5,
            source="facebook",
            title="Mặt tiền Tân Định giá 1ty3xxtr",
            description="DT 5x40 thổ cư 60m, giá chủ ghi 1ty3xxtr, sai số hàng chục triệu.",
            area_m2=200.0,
        )
        ambiguous_price_lid = self._insert_listing(
            url="https://t.test/ambiguous-price",
            ppm2=6.5,
            source="facebook",
            title="Mặt tiền Tân Định giá 12.x tỷ",
            description="DT 5x40 thổ cư 60m, giá chủ ghi 12.x tỷ nên chênh hàng trăm triệu.",
            area_m2=200.0,
        )
        missing_area_evidence_lid = self._insert_listing(
            url="https://t.test/missing-area-evidence",
            ppm2=22.0,
            source="facebook",
            title="Nhà mặt tiền Định Hòa giá 2 tỷ 380",
            description="Sát bệnh viện, đường nhựa lớn, liên hệ xem nhà.",
            area_m2=104.0,
            property_type="nha_dat",
        )

        self._reprocess_inserted()

        with get_conn() as conn:
            target_ids = [
                discount_lid,
                down_payment_lid,
                large_lot_lid,
                area_conflict_lid,
                source_category_conflict_lid,
                multi_lot_lid,
                approximate_price_lid,
                ambiguous_price_lid,
                missing_area_evidence_lid,
            ]
            rows = {
                r["listing_id"]: dict(r)
                for r in conn.execute(
                    f"""
                    SELECT listing_id, is_signal, source_quality_recheck,
                           source_quality_flags
                    FROM valuation_results
                    WHERE listing_id IN ({','.join('?' for _ in target_ids)})
                    """,
                    target_ids,
                ).fetchall()
            }

        self.assertNotIn("parsed_discount_as_price", rows[discount_lid]["source_quality_flags"])
        self.assertIn("too_low_absolute_price", rows[discount_lid]["source_quality_flags"])
        self.assertEqual(rows[discount_lid]["is_signal"], 1)
        self.assertEqual(rows[discount_lid]["source_quality_recheck"], 1)
        self.assertFalse(is_actionable_signal(rows[discount_lid]))

        self.assertNotIn("down_payment_as_price", rows[down_payment_lid]["source_quality_flags"])
        self.assertIn("too_low_absolute_price", rows[down_payment_lid]["source_quality_flags"])
        self.assertEqual(rows[down_payment_lid]["source_quality_recheck"], 1)
        self.assertFalse(is_actionable_signal(rows[down_payment_lid]))

        self.assertNotIn("large_lot_model_risk", rows[large_lot_lid]["source_quality_flags"])
        self.assertEqual(rows[large_lot_lid]["source_quality_recheck"], 0)
        self.assertTrue(is_actionable_signal(rows[large_lot_lid]))

        self.assertIn("area_dimension_conflict", rows[area_conflict_lid]["source_quality_flags"])
        self.assertEqual(rows[area_conflict_lid]["source_quality_recheck"], 1)
        self.assertFalse(is_actionable_signal(rows[area_conflict_lid]))

        self.assertIn("source_category_conflict", rows[source_category_conflict_lid]["source_quality_flags"])
        self.assertEqual(rows[source_category_conflict_lid]["source_quality_recheck"], 1)
        self.assertFalse(is_actionable_signal(rows[source_category_conflict_lid]))

        self.assertIn("multi_lot_listing", rows[multi_lot_lid]["source_quality_flags"])
        self.assertEqual(rows[multi_lot_lid]["source_quality_recheck"], 1)
        self.assertFalse(is_actionable_signal(rows[multi_lot_lid]))

        self.assertIn("approximate_price_text", rows[approximate_price_lid]["source_quality_flags"])
        self.assertNotIn("ambiguous_price_text", rows[approximate_price_lid]["source_quality_flags"])
        self.assertEqual(rows[approximate_price_lid]["source_quality_recheck"], 0)
        self.assertTrue(is_actionable_signal(rows[approximate_price_lid]))

        self.assertIn("ambiguous_price_text", rows[ambiguous_price_lid]["source_quality_flags"])
        self.assertEqual(rows[ambiguous_price_lid]["source_quality_recheck"], 1)
        self.assertFalse(is_actionable_signal(rows[ambiguous_price_lid]))

        self.assertIn("missing_area_evidence", rows[missing_area_evidence_lid]["source_quality_flags"])
        self.assertEqual(rows[missing_area_evidence_lid]["source_quality_recheck"], 1)
        self.assertFalse(is_actionable_signal(rows[missing_area_evidence_lid]))

    def test_quality_flags_mark_multi_lot_nha_tro_posts(self):
        from cleansing.reprocess import _valuation_quality_flags

        class Row(dict):
            def __missing__(self, key):
                return None

        row = Row({
            "source": "facebook",
            "source_id": "multi-lot-nha-tro",
            "url": "https://t.test/multi-lot-nha-tro",
            "title": "Ch\u1ee7 g\u1eedi m\u1ea5y c\u0103n nh\u00e0 \u1edf nh\u00e0 tr\u1ecd",
            "description": (
                "Tr\u1ecd m\u1edbi: 5m Nh14 2t\u1ef7650; 5m H29 DH8 2650; "
                "10m G4 NG4 5t2; 10m N12 mp1 5t1; "
                "G\u00f3c c\u00f3 kiot 320m2 DF6-NF4 5t1."
            ),
            "price_ty": 2.65,
            "price_per_m2": 8.0,
            "area_m2": 320.0,
            "property_type": "nha_tro",
        })

        self.assertIn("multi_lot_listing", _valuation_quality_flags(row))

    def test_apartment_unit_scaled_price_is_suppressed(self):
        from cleansing.reprocess import _valuation_quality_flags

        class Row(dict):
            def __missing__(self, _key):
                return None

        row = Row({
            "source": "guland",
            "source_id": "bad-apartment-price",
            "url": "https://guland.test/bad-apartment-price",
            "title": "Căn hộ giá 1,72 tỷ",
            "description": "Diện tích 60m2",
            "property_type": "chung_cu",
            "tx_type": "ban",
            "price_ty": 0.002,
            "price_per_m2": 0.033,
            "area_m2": 60,
        })

        self.assertIn("too_low_absolute_price", _valuation_quality_flags(row))

    def test_quality_flags_merge_persisted_extraction_flags(self):
        from cleansing.reprocess import _valuation_quality_flags

        class Row(dict):
            def __missing__(self, _key):
                return None

        row = Row({
            "source": "guland",
            "url": "https://guland.test/persisted-integrity-flag",
            "title": "Bán đất giá tốt",
            "description": "",
            "property_type": "dat_nen",
            "tx_type": "ban",
            "price_ty": 2.0,
            "price_per_m2": 20.0,
            "area_m2": 100.0,
            "extraction_quality_flags": "price_area_inconsistent",
        })

        self.assertIn("price_area_inconsistent", _valuation_quality_flags(row))

    def test_quality_flags_detect_unverified_unit_price_invariant(self):
        from cleansing.reprocess import _valuation_quality_flags

        class Row(dict):
            def __missing__(self, _key):
                return None

        row = Row({
            "source": "guland",
            "url": "https://guland.test/unverified-unit-price",
            "title": "Bán đất giá tốt",
            "description": "Liên hệ chính chủ",
            "property_type": "dat_nen",
            "tx_type": "ban",
            "price_ty": 2.0,
            "price_per_m2": 10.0,
            "area_m2": 100.0,
        })

        self.assertIn("price_area_inconsistent", _valuation_quality_flags(row))

    def test_quality_flags_use_irregular_geometry_tolerance(self):
        from cleansing.reprocess import _valuation_quality_flags

        class Row(dict):
            def __missing__(self, _key):
                return None

        base = {
            "source": "facebook",
            "url": "https://facebook.test/geometry-tolerance",
            "title": "Bán đất 100m2 giá 2 tỷ",
            "property_type": "dat_nen",
            "tx_type": "ban",
            "price_ty": 2.0,
            "price_per_m2": 20.0,
            "area_m2": 100.0,
        }
        irregular = Row({**base, "description": "Lô xéo hậu ngang 5m dài 40m"})
        regular = Row({**base, "description": "Đất vuông ngang 5m dài 40m"})

        self.assertNotIn("area_dimension_conflict", _valuation_quality_flags(irregular))
        self.assertIn("area_dimension_conflict", _valuation_quality_flags(regular))

    def test_positive_feedback_does_not_override_deterministic_integrity(self):
        from cleansing.reprocess import _source_quality_flags

        class Row(dict):
            def __missing__(self, _key):
                return None

        row = Row({
            "source": "facebook",
            "url": "https://facebook.test/positive-multi-lot",
            "title": "Bán gấp 2 lô Chánh Mỹ",
            "description": "Giá tốt liên hệ",
            "property_type": "dat_nen",
            "tx_type": "ban",
            "price_ty": 2.0,
            "price_per_m2": 20.0,
            "area_m2": 100.0,
            "feedback_verdict": "all_correct",
            "feedback_extraction_verdict": "all_correct",
            "feedback_valuation_verdict": "cheap_real",
        })

        self.assertIn("multi_lot_listing", _source_quality_flags(row))

    def test_quality_flags_allow_land_use_for_warehouse_text(self):
        from cleansing.reprocess import _valuation_quality_flags

        class Row(dict):
            def __missing__(self, key):
                return None

        land_use = Row({
            "source": "facebook",
            "source_id": "land-use-warehouse",
            "url": "https://facebook.com/test/land-use-warehouse",
            "title": "Dat dep phu hop lam kho xuong biet thu",
            "description": "Ban dat 1083m2 tho cu 200m, khu dat rong phu hop lam kho xuong.",
            "price_ty": 5.5,
            "price_per_m2": 5.1,
            "area_m2": 1083.0,
            "property_type": "dat_nen",
        })
        wrong_category = Row({
            **land_use,
            "source": "guland",
            "url": "https://guland.vn/mua-ban-kho-xuong-dinh-hoa/source-category-conflict",
            "source_id": "wrong-category",
        })

        self.assertNotIn("source_category_conflict", _valuation_quality_flags(land_use))
        self.assertIn("source_category_conflict", _valuation_quality_flags(wrong_category))

    def test_quality_flags_distinguish_masked_price_precision(self):
        from cleansing.reprocess import _valuation_quality_flags

        class Row(dict):
            def __missing__(self, key):
                return None

        base = {
            "source": "facebook",
            "source_id": "masked-price",
            "url": "https://t.test/masked-price",
            "price_ty": 3.5,
            "price_per_m2": 20.0,
            "area_m2": 175.0,
            "property_type": "dat_nen",
        }

        approximate = Row({
            **base,
            "title": "Gia 3t5x",
            "description": "Hang chuc trieu bi che nhung hang tram trieu da ro.",
        })
        approximate_star = Row({
            **base,
            "title": "Gia 3ty5*",
            "description": "Hang chuc trieu bi che nhung hang tram trieu da ro.",
        })
        ambiguous = Row({
            **base,
            "title": "Gia 3ty**",
            "description": "Hang tram trieu bi che nen khong duoc coi la gia 3 ty.",
        })

        self.assertIn("approximate_price_text", _valuation_quality_flags(approximate))
        self.assertNotIn("ambiguous_price_text", _valuation_quality_flags(approximate))
        self.assertIn("approximate_price_text", _valuation_quality_flags(approximate_star))
        self.assertNotIn("ambiguous_price_text", _valuation_quality_flags(approximate_star))
        self.assertIn("ambiguous_price_text", _valuation_quality_flags(ambiguous))

    def test_reprocess_keeps_old_and_fresh_guland_signal_strength_actionable(self):
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
        self.assertEqual(old_row["is_signal"], 1)
        self.assertEqual(old_row["source_quality_recheck"], 0)
        self.assertNotIn("old_guland_post", old_row["source_quality_flags"])
        self.assertNotIn("guland_weak_signal", old_row["source_quality_flags"])
        self.assertNotIn("guland_user_facing_risk", old_row["source_quality_flags"])

        self.assertIsNotNone(fresh_row)
        self.assertEqual(fresh_row["is_signal"], 1)
        self.assertEqual(fresh_row["source_quality_recheck"], 0)
        self.assertNotIn("guland_weak_signal", fresh_row["source_quality_flags"])
        self.assertNotIn("guland_user_facing_risk", fresh_row["source_quality_flags"])

        self.assertIsNotNone(trusted_row)
        self.assertEqual(trusted_row["is_signal"], 1)
        self.assertEqual(trusted_row["source_quality_recheck"], 0)
        self.assertNotIn("old_guland_post", trusted_row["source_quality_flags"] or "")

    def test_reprocess_keeps_two_week_old_guland_signal_strength_actionable(self):
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
        self.assertEqual(stale["is_signal"], 1)
        self.assertEqual(stale["source_quality_recheck"], 0)
        self.assertNotIn("old_guland_post", stale["source_quality_flags"])
        self.assertNotIn("guland_weak_signal", stale["source_quality_flags"])
        self.assertNotIn("guland_user_facing_risk", stale["source_quality_flags"])

        self.assertIsNotNone(trusted)
        self.assertEqual(trusted["is_signal"], 1)
        self.assertEqual(trusted["source_quality_recheck"], 0)
        self.assertNotIn("old_guland_post", trusted["source_quality_flags"] or "")

    def test_reprocess_does_not_generate_retired_guland_cluster_flood(self):
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
            self.assertEqual(row["is_signal"], 1)
            self.assertNotIn(
                "guland_cluster_flood",
                row["source_quality_flags"] or "",
            )

        self.assertIsNotNone(singleton)
        self.assertEqual(singleton["is_signal"], 1)
        self.assertEqual(singleton["source_quality_recheck"], 0)
        self.assertNotIn("guland_weak_signal", singleton["source_quality_flags"])
        self.assertNotIn("guland_user_facing_risk", singleton["source_quality_flags"])
        self.assertNotIn("guland_cluster_flood", singleton["source_quality_flags"] or "")


if __name__ == "__main__":
    unittest.main()
