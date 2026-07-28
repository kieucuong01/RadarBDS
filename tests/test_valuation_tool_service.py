import unittest
from concurrent.futures import ThreadPoolExecutor
from time import sleep
from unittest.mock import patch

from services import market_data, valuation_tool


class _FakeModel:
    n_samples = 120

    def predict_fair_ppm2(self, target, base_override=None):
        return 20.0

    def confidence_level(self):
        return "high"


class _FakeEngine:
    def __init__(self):
        self.fit_calls = 0

    def fit(self, listings):
        self.fit_calls += 1

    def _select_pricing_basis(self, target):
        return _FakeModel(), 20.0, "ward_road_tier", 18


class ValuationToolServiceTest(unittest.TestCase):
    def tearDown(self):
        reset = getattr(valuation_tool, "_reset_model_cache_for_tests", None)
        if reset:
            reset()

    def test_target_is_limited_to_supported_cities_and_ignores_tho_cu(self):
        target = valuation_tool._target_listing(
            {
                "city": "THỦ DẦU MỘT",
                "ward": "Phú Mỹ",
                "property_type": "dat_nen",
                "area_m2": 100,
                "tho_cu_m2": 100,
            }
        )

        self.assertEqual(target.ward, "Phú Mỹ")
        self.assertIsNone(target.tho_cu_m2)

        with self.assertRaisesRegex(valuation_tool.ValuationToolError, "city_invalid"):
            valuation_tool._target_listing(
                {
                    "city": "DĨ AN",
                    "ward": "Dĩ An",
                    "property_type": "dat_nen",
                    "area_m2": 100,
                }
            )

        with self.assertRaisesRegex(valuation_tool.ValuationToolError, "area_m2_invalid"):
            valuation_tool._target_listing(
                {
                    "city": "THỦ DẦU MỘT",
                    "ward": "Phú Mỹ",
                    "property_type": "dat_nen",
                    "area_m2": "NaN",
                }
            )

    def test_baseline_quality_contract_ignores_display_only_confidence_flags(self):
        flags = valuation_tool._baseline_quality_flags(
            "low_segment_confidence,low_road_confidence,missing_area_evidence"
        )

        self.assertEqual(flags, ("missing_area_evidence",))

    def test_model_cache_fits_once_and_refreshes_when_data_version_changes(self):
        engines = []

        def make_engine():
            engine = _FakeEngine()
            engines.append(engine)
            return engine

        with (
            patch.object(
                valuation_tool,
                "_training_snapshot_version",
                side_effect=[("v1", "2026-07-28"), ("v1", "2026-07-28"), ("v2", "2026-07-29")],
            ),
            patch.object(valuation_tool, "_load_training_listings", return_value=[object()]),
            patch.object(valuation_tool, "ValuationEngine", side_effect=make_engine),
        ):
            valuation_tool._reset_model_cache_for_tests()
            first, first_date = valuation_tool._get_cached_engine()
            second, second_date = valuation_tool._get_cached_engine()
            refreshed, refreshed_date = valuation_tool._get_cached_engine()

        self.assertIs(first, second)
        self.assertIsNot(first, refreshed)
        self.assertEqual([engine.fit_calls for engine in engines], [1, 1])
        self.assertEqual((first_date, second_date, refreshed_date), ("2026-07-28", "2026-07-28", "2026-07-29"))

    def test_failed_refresh_keeps_last_good_model(self):
        good = _FakeEngine()

        class BrokenEngine:
            def fit(self, listings):
                raise RuntimeError("fit failed")

        with (
            patch.object(
                valuation_tool,
                "_training_snapshot_version",
                side_effect=[("v1", "2026-07-28"), ("v2", "2026-07-29")],
            ),
            patch.object(valuation_tool, "_load_training_listings", return_value=[object()]),
            patch.object(valuation_tool, "ValuationEngine", side_effect=[good, BrokenEngine()]),
        ):
            valuation_tool._reset_model_cache_for_tests()
            first, first_date = valuation_tool._get_cached_engine()
            stale, stale_date = valuation_tool._get_cached_engine()

        self.assertIs(first, stale)
        self.assertEqual((first_date, stale_date), ("2026-07-28", "2026-07-28"))

    def test_concurrent_cold_requests_fit_only_once(self):
        engines = []

        def make_engine():
            engine = _FakeEngine()
            engines.append(engine)
            return engine

        def slow_training_load():
            sleep(0.05)
            return [object()]

        with (
            patch.object(valuation_tool, "_training_snapshot_version", return_value=("v1", "2026-07-28")),
            patch.object(valuation_tool, "_load_training_listings", side_effect=slow_training_load),
            patch.object(valuation_tool, "ValuationEngine", side_effect=make_engine),
        ):
            valuation_tool._reset_model_cache_for_tests()
            with ThreadPoolExecutor(max_workers=4) as executor:
                results = list(executor.map(lambda _: valuation_tool._get_cached_engine()[0], range(4)))

        self.assertEqual(len(engines), 1)
        self.assertTrue(all(engine is results[0] for engine in results))
        self.assertEqual(engines[0].fit_calls, 1)

    def test_signal_card_formatter_keeps_internal_detail_link_and_redacts_non_admin(self):
        row = {
            "id": 10,
            "title": "Bán đất 0909 123 456",
            "description": "Gọi 0909 123 456 để xem đất",
            "url": "https://facebook.example/listing",
            "contact_phone": "0909123456",
            "seller_name": "Môi giới A",
            "fair_ppm2": 20.0,
            "mos_pct": 10.0,
            "actual_ppm2": 18.0,
            "area_m2": 100.0,
            "frontage_m": 5.0,
            "depth_m": 20.0,
            "price_ty": 1.8,
            "property_type": "dat_nen",
            "is_hot": 0,
            "price_dropped": 0,
            "suspicious_bait": 0,
            "price_drop_pct": 0,
            "price_first_ty": None,
            "duplicate_of_id": None,
            "posted_at": "2026-07-28T08:00:00",
            "crawled_at": "2026-07-28T09:00:00",
            "ward": "Phú Mỹ",
            "signal_score": 72,
            "source": "facebook",
            "road_tier": 2,
            "road_type": "mặt tiền",
            "road_name": "DX 01",
            "road_width_m": 6,
            "tho_cu_m2": 100,
            "tho_cu_ratio": 1,
            "has_so": 1,
        }

        guest = market_data.format_signal_card_record(
            row,
            primary_img="/static/data/images/thumbs/10.webp",
            tier="guest",
        )
        admin = market_data.format_signal_card_record(row, tier="admin")

        self.assertEqual(guest["detail_href"], "/listing/10")
        self.assertEqual(admin["detail_href"], "/listing/10")
        self.assertEqual(guest["url"], None)
        self.assertNotIn("0909", str(guest))
        self.assertIn("0909", str(admin))
        self.assertIn("facebook.example", str(admin))

    def test_all_tiers_get_six_internal_comparable_cards_with_non_admin_redaction(self):
        comparable = {
            "id": 10,
            "title": "Bán đất 0909 123 456",
            "url": "https://facebook.example/listing",
            "contact_phone": "0909123456",
            "detail_href": "/listing/10",
            "price_ty": 1.8,
            "actual_ppm2": 18,
            "fair_ppm2": 20,
            "mos_pct": 10,
            "area_m2": 100,
            "road_tier": 2,
            "primary_img": "/static/data/images/thumbs/10.webp",
        }

        def comparable_for_tier(target, *, limit, tier):
            self.assertEqual(limit, 6)
            return [market_data.redact_for_tier(comparable, tier)]

        with (
            patch.object(valuation_tool, "_get_cached_engine", return_value=(_FakeEngine(), "2026-07-28")),
            patch.object(valuation_tool, "_load_comparables", side_effect=comparable_for_tier) as load_comparables,
        ):
            guest = valuation_tool.estimate_property_value(
                {
                    "city": "THỦ DẦU MỘT",
                    "ward": "Phú Mỹ",
                    "property_type": "dat_nen",
                    "area_m2": 100,
                    "price_ty": 1.8,
                },
                tier="guest",
            )
            free = valuation_tool.estimate_property_value(
                {
                    "city": "THỦ DẦU MỘT",
                    "ward": "Phú Mỹ",
                    "property_type": "dat_nen",
                    "area_m2": 100,
                    "price_ty": 1.8,
                },
                tier="free",
            )
            vip = valuation_tool.estimate_property_value(
                {
                    "city": "THỦ DẦU MỘT",
                    "ward": "Phú Mỹ",
                    "property_type": "dat_nen",
                    "area_m2": 100,
                },
                tier="vip",
            )
            admin = valuation_tool.estimate_property_value(
                {
                    "city": "THỦ DẦU MỘT",
                    "ward": "Phú Mỹ",
                    "property_type": "dat_nen",
                    "area_m2": 100,
                },
                tier="admin",
            )

        self.assertTrue(guest["ok"])
        self.assertFalse(guest["comparables_locked"])
        self.assertEqual(len(guest["comparables"]), 1)
        self.assertEqual(guest["estimate"]["basis_count"], 18)
        self.assertEqual(guest["estimate"]["confidence_label"], "Tin cậy cao")
        self.assertEqual(guest["estimate"]["data_as_of"], "2026-07-28")
        self.assertEqual(guest["estimate"]["mos_pct"], 10.0)
        self.assertNotIn("note", guest["estimate"])
        self.assertNotIn("segment_n", guest["estimate"])
        self.assertIn("city=TH%E1%BB%A6%20D%E1%BA%A6U%20M%E1%BB%98T", guest["dashboard_url"])

        for result in (guest, free, vip, admin):
            self.assertFalse(result["comparables_locked"])
            self.assertEqual(result["comparables"][0]["detail_href"], "/listing/10")
        for result in (guest, free, vip):
            rendered = str(result["comparables"][0])
            self.assertNotIn("0909", rendered)
            self.assertNotIn("facebook.example", rendered)
        self.assertIn("0909", str(admin["comparables"][0]))
        self.assertIn("facebook.example", str(admin["comparables"][0]))
        self.assertEqual(load_comparables.call_count, 4)


if __name__ == "__main__":
    unittest.main()
