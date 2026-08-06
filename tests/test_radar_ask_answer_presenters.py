from datetime import datetime, timezone

from services.radar_ask.answer_presenters import present_deterministic_answer
from services.radar_ask.contracts import (
    AskDepth,
    EvidenceBundle,
    EvidenceItem,
    RetrievalQuality,
    RouteDecision,
    SourceKind,
)
from services.radar_ask.validator import validate_answer


NOW = datetime(2026, 8, 6, 3, 0, tzinfo=timezone.utc)


def decision(question_type: str) -> RouteDecision:
    return RouteDecision(
        depth=AskDepth.FAST,
        question_type=question_type,
        generated=False,
    )


def item(
    evidence_id: str,
    *,
    source_ref: str,
    value: dict,
    kind: SourceKind = SourceKind.MARKET_STAT,
    sample_size: int | None = None,
) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=evidence_id,
        source_kind=kind,
        source_ref=source_ref,
        value=value,
        unit=None,
        calculation_method="fixture",
        as_of=NOW,
        dataset_version="fixture:v1",
        sample_size=sample_size,
    )


def validated(answer, bundle: EvidenceBundle):
    return validate_answer(
        answer,
        [bundle],
        tier="admin",
        expected_depth=AskDepth.FAST,
        now=NOW,
        required_freshness_hours=24,
    )


def test_budget_answer_ranks_wards_and_cites_each_aggregate():
    rows = [
        {
            "ward": "Phú Mỹ",
            "listing_count": 3,
            "median_asking_price_ty": 2.2,
            "median_asking_ppm2_million": 20,
            "budget_headroom_ty": 0.3,
        },
        {
            "ward": "Định Hòa",
            "listing_count": 2,
            "median_asking_price_ty": 2.4,
            "median_asking_ppm2_million": 24,
            "budget_headroom_ty": 0.1,
        },
    ]
    bundle = EvidenceBundle(
        question_snapshot="Ngân sách 2,5 tỷ nên xem phường nào?",
        calculations={"budget_ty": 2.5, "matched_listing_count": 5, "area_matches": rows},
        items=[
            item(
                "budget:phu-my",
                source_ref="budget-area:Phú Mỹ:Thủ Dầu Một",
                value={**rows[0], "budget_ty": 2.5},
                sample_size=3,
            ),
            item(
                "budget:dinh-hoa",
                source_ref="budget-area:Định Hòa:Thủ Dầu Một",
                value={**rows[1], "budget_ty": 2.5},
                sample_size=2,
            ),
        ],
    )

    answer = validated(
        present_deterministic_answer(decision("budget_match"), bundle, now=NOW),
        bundle,
    )

    assert answer.direct_answer.startswith("Với ngân sách 2,5 tỷ")
    assert "Phú Mỹ" in answer.direct_answer
    assert "Định Hòa" in answer.direct_answer
    assert "mở các nguồn bên dưới" not in answer.direct_answer.lower()
    assert [claim.evidence_ids for claim in answer.claims] == [
        ["budget:phu-my"],
        ["budget:dinh-hoa"],
    ]


def test_area_comparison_answers_which_area_has_lower_observed_asking_price():
    phu_my = {
        "ward": "Phú Mỹ",
        "sample_count": 8,
        "median_asking_ppm2_million": 20,
        "p25_asking_ppm2_million": 18,
        "p75_asking_ppm2_million": 22,
    }
    dinh_hoa = {
        "ward": "Định Hòa",
        "sample_count": 7,
        "median_asking_ppm2_million": 24,
        "p25_asking_ppm2_million": 21,
        "p75_asking_ppm2_million": 27,
    }
    bundle = EvidenceBundle(
        question_snapshot="Phú Mỹ và Định Hòa khác nhau sao?",
        calculations={
            "metric": "asking_price_per_m2",
            "window_days": 90,
            "areas": {"Phú Mỹ": phu_my, "Định Hòa": dinh_hoa},
        },
        items=[
            item("area:phu-my", source_ref="ward-market:Phú Mỹ:90d", value=phu_my, sample_size=8),
            item("area:dinh-hoa", source_ref="ward-market:Định Hòa:90d", value=dinh_hoa, sample_size=7),
        ],
    )

    answer = validated(
        present_deterministic_answer(decision("area_comparison"), bundle, now=NOW),
        bundle,
    )

    assert "Phú Mỹ đang có mức chào thấp hơn Định Hòa" in answer.direct_answer
    assert "20 triệu/m²" in answer.direct_answer
    assert "24 triệu/m²" in answer.direct_answer
    assert {claim.evidence_ids[0] for claim in answer.claims} == {
        "area:phu-my",
        "area:dinh-hoa",
    }


def test_deal_search_lists_matches_and_cites_each_exact_listing():
    first = {
        "listing_ref": "radar-listing:701",
        "ward": "Phú Mỹ",
        "asking_price_ty": 2.2,
        "asking_price_per_m2_million": 18,
        "fair_price_per_m2_million": 22,
        "mos_pct": 18,
        "signal_score": 80,
    }
    second = {
        "listing_ref": "radar-listing:702",
        "ward": "Định Hòa",
        "asking_price_ty": 2.4,
        "asking_price_per_m2_million": 19,
        "fair_price_per_m2_million": 23,
        "mos_pct": 17,
        "signal_score": 76,
    }
    bundle = EvidenceBundle(
        question_snapshot="Tin nào dưới 20 triệu/m² đáng kiểm tra?",
        calculations={"result_count": 2, "effective_mos_min_pct": 15},
        items=[
            item(
                "deal:701",
                kind=SourceKind.VALUATION,
                source_ref="radar-signal:701",
                value=first,
            ),
            item(
                "deal:702",
                kind=SourceKind.VALUATION,
                source_ref="radar-signal:702",
                value=second,
            ),
        ],
    )

    answer = validated(
        present_deterministic_answer(decision("deal_search"), bundle, now=NOW),
        bundle,
    )

    assert "2 tin đáng kiểm tra" in answer.direct_answer
    assert "#701" in answer.direct_answer
    assert "#702" in answer.direct_answer
    assert [claim.evidence_ids for claim in answer.claims] == [["deal:701"], ["deal:702"]]


def test_price_drop_answer_ranks_ward_aggregates():
    areas = [
        {"ward": "Phú Mỹ", "signal_count": 3, "median_price_drop_pct": 8, "median_mos_pct": 18},
        {"ward": "Định Hòa", "signal_count": 2, "median_price_drop_pct": 6, "median_mos_pct": 17},
    ]
    bundle = EvidenceBundle(
        question_snapshot="Khu nào có nhiều tín hiệu giảm giá hôm nay?",
        calculations={"window_days": 1, "areas": areas},
        items=[
            item("drop:phu-my", source_ref="price-drop-area:Phú Mỹ:1d", value=areas[0], sample_size=3),
            item("drop:dinh-hoa", source_ref="price-drop-area:Định Hòa:1d", value=areas[1], sample_size=2),
        ],
    )

    answer = validated(
        present_deterministic_answer(decision("price_drop_ranking"), bundle, now=NOW),
        bundle,
    )

    assert answer.direct_answer.startswith("Hôm nay, Phú Mỹ đang có nhiều tín hiệu giảm giá nhất")
    assert "3 tín hiệu" in answer.direct_answer
    assert [claim.evidence_ids for claim in answer.claims] == [
        ["drop:phu-my"],
        ["drop:dinh-hoa"],
    ]


def test_road_market_answer_labels_exact_road_sample():
    value = {
        "road": "ĐL1",
        "ward": "Phú Mỹ",
        "market_scope": "exact_road",
        "window_days": 90,
        "sample_count": 6,
        "median_asking_ppm2_million": 21,
        "p25_asking_ppm2_million": 19,
        "p75_asking_ppm2_million": 24,
    }
    bundle = EvidenceBundle(
        question_snapshot="Giá hiện tại mặt tiền đường ĐL1 là bao nhiêu?",
        calculations=value,
        items=[
            item(
                "road:phu-my",
                source_ref="road-market:Phú Mỹ:ĐL1:exact_road:90d",
                value=value,
                sample_size=6,
            )
        ],
    )

    answer = validated(
        present_deterministic_answer(decision("road_market_estimate"), bundle, now=NOW),
        bundle,
    )

    assert "mẫu đúng tuyến ĐL1 tại Phú Mỹ" in answer.direct_answer
    assert "21 triệu/m²" in answer.direct_answer
    assert answer.claims[0].evidence_ids == ["road:phu-my"]


def test_insufficient_evidence_does_not_create_unrelated_claim_or_source():
    bundle = EvidenceBundle(
        question_snapshot="Ngân sách 2,5 tỷ nên xem phường nào?",
        retrieval_quality=RetrievalQuality.INSUFFICIENT,
        missing_requirements=["no_eligible_listings_within_budget"],
    )

    answer = present_deterministic_answer(decision("budget_match"), bundle, now=NOW)

    assert answer.answered is False
    assert answer.claims == []
    assert answer.source_cards == []
    assert "chưa đủ dữ liệu" in answer.direct_answer.lower()
