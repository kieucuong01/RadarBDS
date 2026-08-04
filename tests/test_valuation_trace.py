from __future__ import annotations

from datetime import date

import pytest

from analytics.valuation import (
    Listing,
    ValuationAdjustment,
    ValuationEngine,
    ValuationTrace,
)


def make_listing(listing_id: int, ppm2: float, **overrides) -> Listing:
    area_m2 = float(overrides.pop("area_m2", 100.0))
    return Listing(
        id=listing_id,
        area=overrides.pop("area", "Tân An"),
        ward=overrides.pop("ward", "Tân An"),
        property_type=overrides.pop("property_type", "dat_nen"),
        tx_type="ban",
        price_per_m2=ppm2,
        price_total=ppm2 * area_m2 / 1_000,
        area_m2=area_m2,
        frontage_m=overrides.pop("frontage_m", 5.0),
        depth_m=overrides.pop("depth_m", 20.0),
        road_tier=overrides.pop("road_tier", 2),
        has_so=overrides.pop("has_so", True),
        crawled_at=date.today(),
        source="facebook",
        measurement_provenance=overrides.pop(
            "measurement_provenance",
            {"area_m2": "declared_text", "frontage_m": "source_text"},
        ),
        **overrides,
    )


def fitted_engine() -> ValuationEngine:
    engine = ValuationEngine()
    engine.fit(
        [
            make_listing(
                index,
                18.0 + (index % 4) * 0.5,
                area_m2=90.0 + index,
            )
            for index in range(1, 25)
        ]
    )
    return engine


def test_trace_reproduces_fair_value_and_total_without_changing_model_result():
    target = make_listing(
        9001,
        13.0,
        area_m2=120.0,
        frontage_m=5.0,
        depth_m=35.0,
        title="Lô góc đã có sổ",
    )
    result = fitted_engine().valuate(target)

    assert result is not None
    trace = result.valuation_trace
    assert trace["trace_version"] == 1
    assert trace["model_name"] == "road_tier_hierarchical"
    assert trace["model_version"] == "road_tier_hierarchical_v1"
    assert trace["final_fair_ppm2"] == pytest.approx(result.price_per_m2_fair, abs=0.01)
    assert trace["final_fair_total"] == pytest.approx(
        result.price_per_m2_fair * target.area_m2,
        abs=1,
    )
    assert trace["sample_count"] == result.segment_n
    assert 0 < len(trace["comparable_listing_ids"]) <= 20
    assert trace["comparable_listing_ids"] == sorted(trace["comparable_listing_ids"])
    assert trace["measurement_provenance"] == target.measurement_provenance

    applied_delta = sum(item["delta_ppm2"] for item in trace["adjustments"])
    assert trace["baseline_ppm2"] + applied_delta == pytest.approx(
        trace["final_fair_ppm2"],
        abs=0.02,
    )
    assert any(item["code"] == "corner" and item["applied"] for item in trace["adjustments"])
    assert any(item["code"] == "negotiation" and item["applied"] for item in trace["adjustments"])


def test_trace_records_requested_effective_segment_fallback_and_suppressed_factors():
    target = make_listing(
        9002,
        12.0,
        ward="Định Hòa",
        area="Định Hòa",
        road_tier=4,
        frontage_m=None,
        depth_m=None,
    )
    result = fitted_engine().valuate(target)

    assert result is not None
    trace = result.valuation_trace
    assert "Định Hòa" in trace["requested_segment"]
    assert trace["effective_segment"]
    assert trace["fallback_reason"]
    assert isinstance(trace["suppressed_factors"], list)
    assert "lot_shape" in trace["suppressed_factors"]
    assert trace["quality_flags"] == sorted(result.source_quality_flags)


def test_trace_serializer_rejects_non_finite_values():
    trace = ValuationTrace(
        trace_version=1,
        model_name="road_tier_hierarchical",
        model_version="road_tier_hierarchical_v1",
        requested_segment="Tân An|dat_nen|ban|road_bucket_2",
        effective_segment="Tân An|dat_nen|ban|exact",
        fallback_reason=None,
        baseline_ppm2=float("nan"),
        adjustments=(
            ValuationAdjustment(
                code="negotiation",
                input_value=None,
                multiplier=0.95,
                delta_ppm2=-1.0,
                applied=True,
                reason="expected negotiation",
            ),
        ),
        final_fair_ppm2=19.0,
        final_fair_total=1_900.0,
        confidence_low_ppm2=None,
        confidence_high_ppm2=None,
        sample_count=20,
        comparable_listing_ids=(1, 2),
        quality_flags=(),
        suppressed_factors=(),
        measurement_provenance={},
    )

    with pytest.raises(ValueError, match="finite"):
        trace.to_json_dict()
