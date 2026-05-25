"""
Smoke tests — ValuationEngine (fit + predict + signal threshold).
Chạy: python tests/test_valuation.py
"""
import sys
from pathlib import Path
from datetime import date
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analytics.valuation import (
    Listing, ValuationEngine,
    compute_signal_score, proximity_score_for_ward, remove_outliers,
)


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

    # Unknown ward is valuated for audit, but never promoted to a signal.
    target_unknown = _make_listing(998, 8.0, area=100, ward="unknown")
    r_unknown = engine.valuate(target_unknown)
    assert r_unknown is not None and r_unknown.is_signal is False

    # Listing bằng fair → không signal
    target2 = _make_listing(1000, 15.0, area=100)
    result2 = engine.valuate(target2)
    assert result2 is not None and result2.is_signal is False


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


def test_guland_requires_stronger_signal_than_facebook():
    listings = [_make_listing(i, 15.0, source="facebook") for i in range(30)]
    engine = ValuationEngine()
    engine.fit(listings)

    facebook_target = _make_listing(1001, 10.5, source="facebook")
    guland_same_discount = _make_listing(1002, 10.5, source="guland")
    guland_deeper_discount = _make_listing(1003, 9.0, source="guland")

    assert engine.valuate(facebook_target).is_signal is True
    assert engine.valuate(guland_same_discount).is_signal is False
    assert engine.valuate(guland_deeper_discount).is_signal is True


def test_guland_quality_flags_keep_valuation_but_suppress_signal():
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
    assert result.is_signal is False
    assert result.source_quality_recheck is True
    assert "old_guland_post" in result.source_quality_flags


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


def test_has_so_discount():
    listings = [_make_listing(i, 15.0, road_tier=2) for i in range(10)]
    engine = ValuationEngine()
    engine.fit(listings)

    with_so = engine.valuate(_make_listing(200, 10.0, has_so=True))
    no_so = engine.valuate(_make_listing(201, 10.0, has_so=False))

    assert with_so and no_so
    assert no_so.price_per_m2_fair < with_so.price_per_m2_fair


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
