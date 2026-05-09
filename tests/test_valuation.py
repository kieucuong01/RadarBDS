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
    compute_signal_score, remove_outliers,
)


def _make_listing(lid: int, ppm2: float, area: float = 100, **kw) -> Listing:
    return Listing(
        id=lid, area="Tân An", property_type="dat_nen", tx_type="ban",
        ward=kw.get("ward", "Tân An"),
        price_per_m2=ppm2, price_total=round(ppm2 * area / 1000, 2),
        area_m2=area, crawled_at=date.today(),
        has_so=kw.get("has_so", True),
        frontage_m=kw.get("frontage_m", 5.0),
        road_tier=kw.get("road_tier", 2),
        contact_phone=kw.get("contact_phone", ""),
        **{k: v for k, v in kw.items() if k not in {"ward", "has_so", "frontage_m", "road_tier", "contact_phone"}},
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


def test_signal_score_bounds():
    listing = _make_listing(1, 10.0, area=100, frontage_m=5, is_hot=True, price_dropped=True)
    # MOS 50% → 25pt + area 10 + price 10 + hot 10 + frontage 10 + drop 10 = 75
    score = compute_signal_score(listing, mos_pct=50.0)
    assert 0 <= score <= 100
    assert score >= 60  # có nhiều bonus

    # MOS 0% → chỉ bonus (diện tích+giá = 20)
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
