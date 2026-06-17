"""
Smoke tests — ValuationEngine (fit + predict + signal threshold).
Chạy: python tests/test_valuation.py
"""
import sys
from pathlib import Path
from datetime import date
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analytics.valuation import (
    Listing, SegmentModel, ValuationEngine,
    compute_signal_score, proximity_score_for_ward, remove_outliers,
)
from analytics.hierarchical_valuation import MedianRoadTierValuationEngine


def _make_listing(lid: int, ppm2: float, area: float = 100, **kw) -> Listing:
    return Listing(
        id=lid, area="Tân An", property_type=kw.get("property_type", "dat_nen"), tx_type="ban",
        ward=kw.get("ward", "Tân An"),
        price_per_m2=ppm2, price_total=round(ppm2 * area / 1000, 2),
        area_m2=area, crawled_at=date.today(),
        has_so=kw.get("has_so", True),
        frontage_m=kw.get("frontage_m", 5.0),
        road_tier=kw.get("road_tier", 2),
        contact_phone=kw.get("contact_phone", ""),
        **{k: v for k, v in kw.items() if k not in {"ward", "property_type", "has_so", "frontage_m", "road_tier", "contact_phone"}},
    )


def test_remove_outliers():
    vals = [10, 10, 10, 10, 10, 100]  # 100 là outlier
    cleaned, mean, std = remove_outliers(vals, sigma=2.0)
    assert 100 not in cleaned
    assert abs(mean - 10) < 0.1


def test_engine_fit_basic():
    # 20 listings cluster quanh 15 triệu/m² — segment đủ mẫu → medium confidence
    listings = [_make_listing(i, 15 + (i % 5) * 0.2) for i in range(20)]
    engine = ValuationEngine()
    engine.fit(listings)

    key = ("Tân An", "dat_nen", "ban")
    assert key in engine._models
    model = engine._models[key]
    assert model.fitted
    assert 14 < model.median_ppm2 < 17
    # 20 core samples ≥ MIN_SAMPLES(15) → medium
    assert model.confidence_level() in ("medium", "high")


def test_engine_signal_threshold():
    # Tạo 30 listings quanh 15 tr/m² → median 15
    listings = [_make_listing(i, 15.0) for i in range(30)]
    engine = ValuationEngine()
    engine.fit(listings)

    # Listing cheaper than fair value by more than the fixed MOS threshold should signal.
    target_hot = _make_listing(999, 9.5, area=100, is_hot=True)
    r_hot = engine.valuate(target_hot)
    assert r_hot is not None and r_hot.is_signal is True

    # Deal cheaper than fair value by about 16% should now count as a signal.
    target_moderate_discount = _make_listing(997, 12.0, area=100)
    r_moderate = engine.valuate(target_moderate_discount)
    assert r_moderate is not None and r_moderate.is_signal is True

    # Unknown ward is valuated for audit, but never promoted to a signal.
    target_unknown = _make_listing(998, 8.0, area=100, ward="unknown")
    r_unknown = engine.valuate(target_unknown)
    assert r_unknown is not None and r_unknown.is_signal is False

    # Listing bằng fair → không signal
    target2 = _make_listing(1000, 15.0, area=100)
    result2 = engine.valuate(target2)
    assert result2 is not None and result2.is_signal is False


def test_median_road_tier_area_adjustment_is_segment_relative():
    listings = [_make_listing(i, 20.0, area=100.0, road_tier=2) for i in range(20)]
    engine = MedianRoadTierValuationEngine()
    engine.fit(listings)

    standard = engine.valuate(_make_listing(1001, 18.0, area=100.0, road_tier=2))
    small = engine.valuate(_make_listing(1002, 18.0, area=60.0, road_tier=2))
    large = engine.valuate(_make_listing(1003, 18.0, area=400.0, road_tier=2))

    assert standard is not None and small is not None and large is not None
    assert small.price_per_m2_fair == round(standard.price_per_m2_fair * 1.05, 2)
    assert large.price_per_m2_fair == round(standard.price_per_m2_fair * 0.80, 2)
    assert "large_lot_model_risk" not in large.source_quality_flags


def test_median_road_tier_very_large_lot_gets_risk_flag_and_stronger_penalty():
    listings = [_make_listing(i, 20.0, area=100.0, road_tier=2) for i in range(20)]
    engine = MedianRoadTierValuationEngine()
    engine.fit(listings)

    standard = engine.valuate(_make_listing(1101, 18.0, area=100.0, road_tier=2))
    very_large = engine.valuate(_make_listing(1102, 18.0, area=700.0, road_tier=2))

    assert standard is not None and very_large is not None
    assert very_large.price_per_m2_fair == round(standard.price_per_m2_fair * 0.65, 2)
    assert "large_lot_model_risk" in very_large.source_quality_flags


def test_median_road_tier_uses_bucket_median_and_small_road_penalties():
    samples = []
    for i in range(8):
        samples.append(_make_listing(2000 + i, 20.0, road_tier=1))
    samples.append(_make_listing(2099, 80.0, road_tier=1))
    for i in range(20):
        samples.append(_make_listing(3000 + i, 20.0, road_tier=2))
        samples.append(_make_listing(4000 + i, 12.0, road_tier=3))
    engine = MedianRoadTierValuationEngine()
    engine.fit(samples)

    tier1 = engine.valuate(_make_listing(5101, 15.0, road_tier=1))
    tier2 = engine.valuate(_make_listing(5102, 15.0, road_tier=2))
    tier3 = engine.valuate(_make_listing(5103, 15.0, road_tier=3))
    tier4 = engine.valuate(_make_listing(5104, 15.0, road_tier=4))
    tier5 = engine.valuate(_make_listing(5105, 15.0, road_tier=5))
    tier0 = engine.valuate(_make_listing(5106, 15.0, road_tier=0))

    assert tier1 and tier2 and tier3 and tier4 and tier5 and tier0
    assert tier1.price_per_m2_fair == tier2.price_per_m2_fair
    assert tier1.price_per_m2_fair == round(20.0 * 0.95, 2)
    assert tier2.price_per_m2_fair > tier3.price_per_m2_fair
    assert tier4.price_per_m2_fair == round(tier3.price_per_m2_fair * 0.85, 2)
    assert tier5.price_per_m2_fair == round(tier3.price_per_m2_fair * 0.75, 2)
    assert "low_road_confidence" in tier0.source_quality_flags


def test_median_road_tier_sparse_bucket_falls_back_to_segment_median():
    samples = []
    for i in range(2):
        samples.append(_make_listing(6000 + i, 80.0, road_tier=1))
    for i in range(18):
        samples.append(_make_listing(6100 + i, 20.0, road_tier=2))
    for i in range(18):
        samples.append(_make_listing(6200 + i, 12.0, road_tier=3))
    engine = MedianRoadTierValuationEngine()
    engine.fit(samples)

    tier1 = engine.valuate(_make_listing(6301, 15.0, road_tier=1))

    assert tier1 is not None
    assert tier1.price_per_m2_fair == round(20.0 * 0.95, 2)


def test_main_valuation_falls_back_to_market_cluster_same_road_tier():
    samples = []
    for i in range(10):
        samples.append(_make_listing(7000 + i, 20.0, ward="Tân An", road_tier=2))
    for offset, ward in enumerate(("Chánh Mỹ", "Tương Bình Hiệp", "Hiệp An")):
        for i in range(8):
            samples.append(_make_listing(7100 + offset * 100 + i, 12.0, ward=ward, road_tier=3))

    engine = ValuationEngine()
    engine.fit(samples)

    result = engine.valuate(_make_listing(7999, 10.0, ward="Tân An", road_tier=3))

    assert result is not None
    assert result.price_per_m2_fair == 11.4
    assert "basis=market_cluster:tdm_tan_an_west:road_bucket_3" in result.note


def test_social_housing_is_not_valuated_against_landed_house_market():
    listings = (
        [_make_listing(i, 15.0, property_type="nha_dat") for i in range(30)]
        + [_make_listing(100 + i, 25.0, area=30, property_type="nha_o_xa_hoi") for i in range(30)]
    )
    engine = ValuationEngine()
    engine.fit(listings)

    target = _make_listing(
        1004,
        8.0,
        area=30,
        property_type="nha_o_xa_hoi",
        title="Nhà ở xã hội Becamex Định Hòa",
    )

    assert engine.valuate(target) is None


def test_guland_low_quality_samples_do_not_pollute_baseline():
    clean_samples = [_make_listing(i, 15.0, source="facebook") for i in range(18)]
    noisy_guland = [
        _make_listing(100 + i, 60.0, source="guland", source_quality_flags=("extreme_guland_ppm2",))
        for i in range(18)
    ]
    engine = ValuationEngine()
    engine.fit(clean_samples + noisy_guland)

    target = _make_listing(999, 15.0, source="facebook")
    result = engine.valuate(target)

    assert result is not None
    assert result.price_per_m2_fair < 25.0


def test_guland_bad_human_valuation_labels_do_not_pollute_baseline():
    clean_samples = [_make_listing(i, 15.0, source="facebook") for i in range(18)]
    reviewed_bad_guland = [
        _make_listing(200 + i, 60.0, source="guland", source_quality_flags=("review_bad_valuation",))
        for i in range(18)
    ]
    engine = ValuationEngine()
    engine.fit(clean_samples + reviewed_bad_guland)

    result = engine.valuate(_make_listing(999, 15.0, source="facebook"))

    assert result is not None
    assert result.price_per_m2_fair < 25.0


def test_default_valuation_baseline_uses_facebook_only():
    facebook_samples = [_make_listing(i, 20.0, source="facebook") for i in range(35)]
    low_guland_samples = [
        _make_listing(300 + i, 8.0, source="guland")
        for i in range(18)
    ]
    engine = ValuationEngine()
    engine.fit(facebook_samples + low_guland_samples)

    result = engine.valuate(_make_listing(999, 20.0, source="facebook"))

    assert result is not None
    assert result.segment_n == len(facebook_samples)
    assert result.price_per_m2_fair > 18.0


def test_strict_guland_supplements_thin_facebook_baseline_with_lower_weight():
    facebook_samples = [_make_listing(i, 20.0, source="facebook", road_tier=2) for i in range(10)]
    strict_guland_samples = [
        _make_listing(400 + i, 10.0, source="guland", road_tier=2)
        for i in range(20)
    ]
    engine = ValuationEngine()
    engine.fit(facebook_samples + strict_guland_samples)

    result = engine.valuate(_make_listing(999, 15.0, source="facebook", road_tier=2))

    assert result is not None
    assert result.segment_n == 30
    assert 14.0 < result.price_per_m2_fair < 17.0


def test_supplemental_guland_requires_strict_training_quality():
    facebook_samples = [_make_listing(i, 20.0, source="facebook", road_tier=2) for i in range(10)]
    flagged_guland_samples = [
        _make_listing(
            500 + i,
            10.0,
            source="guland",
            road_tier=2,
            source_quality_flags=("old_guland_post",),
        )
        for i in range(20)
    ]
    engine = ValuationEngine()
    engine.fit(facebook_samples + flagged_guland_samples)

    result = engine.valuate(_make_listing(999, 15.0, source="facebook", road_tier=2))

    assert result is not None
    assert result.segment_n == len(facebook_samples)
    assert result.price_per_m2_fair == 19.0


def test_supplemental_guland_large_lot_requires_known_road_tier():
    facebook_samples = [
        _make_listing(i, 5.0, area=1200.0, property_type="dat_vuon", source="facebook", road_tier=3)
        for i in range(10)
    ]
    unknown_tier_guland_samples = [
        _make_listing(600 + i, 2.0, area=1200.0, property_type="dat_vuon", source="guland", road_tier=0)
        for i in range(20)
    ]
    engine = ValuationEngine()
    engine.fit(facebook_samples + unknown_tier_guland_samples)

    result = engine.valuate(
        _make_listing(999, 3.0, area=1200.0, property_type="dat_vuon", source="facebook", road_tier=3)
    )

    assert result is not None
    assert result.segment_n == len(facebook_samples)
    assert result.price_per_m2_fair == 4.75


def test_training_dedupes_duplicate_reposts_by_canonical_lot():
    base_samples = [_make_listing(i, 10.0, source="facebook", road_tier=3) for i in range(15)]
    canonical_high = _make_listing(1000, 30.0, source="facebook", road_tier=3)
    duplicate_reposts = []
    for i in range(40):
        dup = _make_listing(1100 + i, 30.0, source="facebook", road_tier=3)
        dup.duplicate_of_id = canonical_high.id
        duplicate_reposts.append(dup)

    engine = ValuationEngine()
    engine.fit(base_samples + [canonical_high] + duplicate_reposts)

    target = _make_listing(9999, 10.0, source="facebook", road_tier=3)
    result = engine.valuate(target)

    assert result is not None
    assert result.price_per_m2_fair < 15.0


def test_guland_requires_stronger_signal_than_facebook():
    from services.signal_quality import is_actionable_signal

    listings = [_make_listing(i, 15.0, source="facebook") for i in range(30)]
    engine = ValuationEngine()
    engine.fit(listings)

    facebook_target = _make_listing(1001, 12.5, source="facebook")
    guland_same_discount = _make_listing(1002, 12.5, source="guland")
    guland_deeper_discount = _make_listing(1003, 11.4, source="guland")

    facebook_result = engine.valuate(facebook_target)
    weak_guland_result = engine.valuate(guland_same_discount)
    deep_guland_result = engine.valuate(guland_deeper_discount)

    assert facebook_result.is_signal is True
    assert is_actionable_signal(facebook_result) is True
    assert weak_guland_result.is_signal is True
    assert weak_guland_result.source_quality_recheck is True
    assert "guland_weak_signal" in weak_guland_result.source_quality_flags
    assert is_actionable_signal(weak_guland_result) is False
    assert deep_guland_result.is_signal is True
    assert deep_guland_result.source_quality_recheck is True
    assert "guland_user_facing_risk" in deep_guland_result.source_quality_flags
    assert is_actionable_signal(deep_guland_result) is False


def test_guland_with_positive_feedback_or_legal_evidence_can_be_actionable():
    from services.signal_quality import is_actionable_signal

    listings = [_make_listing(i, 15.0, source="facebook") for i in range(30)]
    engine = ValuationEngine()
    engine.fit(listings)

    reviewed = _make_listing(2001, 11.0, source="guland")
    reviewed.positive_feedback = True
    legal_evidence = _make_listing(2002, 11.0, source="guland")
    legal_evidence.trust_tier = "has_legal_doc"

    reviewed_result = engine.valuate(reviewed)
    legal_result = engine.valuate(legal_evidence)

    assert reviewed_result.is_signal is True
    assert reviewed_result.source_quality_recheck is False
    assert is_actionable_signal(reviewed_result) is True
    assert legal_result.is_signal is True
    assert legal_result.source_quality_recheck is False
    assert is_actionable_signal(legal_result) is True


def test_guland_quality_flags_keep_valuation_but_suppress_signal():
    from services.signal_quality import is_actionable_signal

    listings = [_make_listing(i, 15.0, source="facebook") for i in range(30)]
    engine = ValuationEngine()
    engine.fit(listings)

    target = _make_listing(
        2001,
        8.5,
        source="guland",
        source_quality_flags=("old_guland_post",),
    )
    result = engine.valuate(target)

    assert result is not None
    assert result.price_per_m2_fair > 0
    assert result.is_signal is True
    assert result.source_quality_recheck is True
    assert "old_guland_post" in result.source_quality_flags
    assert is_actionable_signal(result) is False


def test_low_segment_confidence_keeps_model_signal_with_warning_badge_only():
    from services.signal_quality import is_actionable_signal

    listings = [_make_listing(i, 15.0, source="facebook") for i in range(8)]
    engine = ValuationEngine()
    engine.fit(listings)

    target = _make_listing(2201, 8.5, source="facebook")
    result = engine.valuate(target)

    assert result is not None
    assert result.is_signal is True
    assert result.source_quality_recheck is False
    assert "low_segment_confidence" in result.source_quality_flags
    assert is_actionable_signal(result) is True


def test_legal_conflict_keeps_valuation_but_suppresses_signal():
    listings = [_make_listing(i, 15.0, source="facebook") for i in range(30)]
    engine = ValuationEngine()
    engine.fit(listings)

    target = _make_listing(
        2101,
        8.5,
        legal_status="conflict",
        legal_flags=("area_mismatch", "road_conflict"),
        trust_tier="candidate_signal",
        trust_score=25,
    )
    result = engine.valuate(target)

    assert result is not None
    assert result.price_per_m2_fair > 0
    assert result.is_signal is False
    assert result.trust_tier == "candidate_signal"
    assert result.trust_score == 25
    assert "road_conflict" in result.legal_flags


def test_verified_legal_signal_carries_trust_fields():
    listings = [_make_listing(i, 15.0, source="facebook") for i in range(30)]
    engine = ValuationEngine()
    engine.fit(listings)

    target = _make_listing(
        2102,
        8.5,
        legal_status="verified",
        trust_tier="legal_verified_signal",
        trust_score=92,
        legal_flags=(),
    )
    result = engine.valuate(target)

    assert result is not None
    assert result.is_signal is True
    assert result.legal_status == "verified"
    assert result.trust_tier == "legal_verified_signal"
    assert result.trust_score == 92


def test_proximity_score_is_ward_level_and_bounded():
    central = proximity_score_for_ward("Phú Cường")
    industrial = proximity_score_for_ward("Mỹ Phước 3")

    assert 1 <= central <= 5
    assert 1 <= industrial <= 5
    assert proximity_score_for_ward("unknown") == 0


def test_signal_score_adds_proximity_without_affecting_cap():
    unknown = _make_listing(3001, 10.0, ward="unknown", is_hot=False)
    central = _make_listing(3002, 10.0, ward="Phú Cường", is_hot=False)
    capped = _make_listing(
        3003,
        1.0,
        ward="Phú Cường",
        area=100,
        is_hot=True,
        price_dropped=True,
    )

    assert compute_signal_score(central, mos_pct=30.0) > compute_signal_score(unknown, mos_pct=30.0)
    assert compute_signal_score(capped, mos_pct=200.0) == 100


def test_signal_score_bounds():
    listing = _make_listing(1, 10.0, area=100, frontage_m=5, is_hot=True, price_dropped=True)
    score = compute_signal_score(listing, mos_pct=50.0)
    assert 0 <= score <= 100
    assert score >= 60  # MOS + liquidity + hot/drop + proximity bonuses

    # MOS 0% still gets bounded non-MOS bonuses.
    score_low = compute_signal_score(_make_listing(2, 10.0, area=100, is_hot=False), mos_pct=0.0)
    assert 0 <= score_low <= 100


def test_road_tier_adjustment():
    # Use fewer than MIN_SAMPLES so the median fallback path applies road multipliers.
    listings = [_make_listing(i, 15.0, road_tier=2) for i in range(10)]
    engine = ValuationEngine()
    engine.fit(listings)

    # Listing tier 1 (đường tên) → fair value ×2
    t1 = _make_listing(100, 20.0, road_tier=1)
    r1 = engine.valuate(t1)
    # Listing tier 4 (hẻm xe máy) has a lower fallback multiplier.
    t4 = _make_listing(101, 20.0, road_tier=4)
    r4 = engine.valuate(t4)

    assert r1 and r4
    # Tier 1 fair > Tier 4 fair cho cùng 1 actual price
    assert r1.price_per_m2_fair > r4.price_per_m2_fair


def test_small_land_lot_size_premium_is_capped_at_twenty_percent():
    listings = [_make_listing(i, 20.0, area=135.0, road_tier=2) for i in range(10)]
    engine = ValuationEngine()
    engine.fit(listings)

    target = _make_listing(200, 10.0, area=62.3, road_tier=2)
    result = engine.valuate(target)

    assert result is not None
    assert result.price_per_m2_fair == 22.8


def test_regression_model_does_not_apply_extra_size_premium():
    model = SegmentModel(("Tân An", "dat_nen", "ban"))
    model.fitted = True
    model.n_samples = 20
    model.ref_area_m2 = 135.0
    model.beta = [20.0, 0.0, 0.0, 0.0, 0.0]

    target = _make_listing(201, 10.0, area=62.3, road_tier=2)

    assert model.predict_fair_ppm2(target) == 19.0


def test_regression_tier3_is_at_least_twenty_percent_below_tier2():
    model = SegmentModel(("TÃ¢n An", "dat_nen", "ban"))
    model.fitted = True
    model.n_samples = 20
    model.beta = [20.0, 0.0, 0.0, 8.0, 0.0]

    tier2 = _make_listing(202, 10.0, area=100.0, road_tier=2)
    tier3 = _make_listing(203, 10.0, area=100.0, road_tier=3)

    tier2_fair = model.predict_fair_ppm2(tier2)
    tier3_fair = model.predict_fair_ppm2(tier3)

    assert tier2_fair == 19.0
    assert tier3_fair == 15.2
    assert tier3_fair <= round(tier2_fair * 0.8, 2)


def test_has_so_discount():
    listings = [_make_listing(i, 15.0, road_tier=2) for i in range(10)]
    engine = ValuationEngine()
    engine.fit(listings)

    with_so = engine.valuate(_make_listing(200, 10.0, has_so=True))
    default_false = engine.valuate(_make_listing(201, 10.0, has_so=False))
    explicit_no_so = engine.valuate(
        _make_listing(
            202,
            10.0,
            has_so=False,
            title="Dat vi bang giay tay, chua co so",
        )
    )

    assert with_so and default_false and explicit_no_so
    assert default_false.price_per_m2_fair == with_so.price_per_m2_fair
    assert explicit_no_so.price_per_m2_fair < with_so.price_per_m2_fair


if __name__ == "__main__":
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS {t.__name__}")
        except AssertionError as e:
            print(f"  FAIL {t.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"  ERROR {t.__name__}: {type(e).__name__}: {e}")
            failed += 1
    print(f"\n{'OK' if failed == 0 else 'FAILED'}: {len(tests)-failed}/{len(tests)} passed")
    sys.exit(0 if failed == 0 else 1)
