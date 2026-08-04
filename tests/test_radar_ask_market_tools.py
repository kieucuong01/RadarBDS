from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest

from services.radar_ask.contracts import AskContext, SourceKind, ToolCall
from services.radar_ask.registry import (
    CompareAreasArgs,
    InspectListingRisksArgs,
    MarketTrendArgs,
    MatchBudgetArgs,
    RankPriceDropAreasArgs,
    RoadMarketArgs,
    SearchDealsArgs,
    ToolContext,
    execute_tool,
)
from services.radar_ask.tools.market import (
    compare_areas,
    estimate_road_market,
    get_market_trend,
    inspect_listing_risks,
    match_budget,
    rank_price_drop_areas,
    search_deals,
)


NOW = datetime(2026, 8, 4, 9, 0, tzinfo=timezone.utc)


class FakeResult:
    def __init__(self, rows):
        self.rows = list(rows)

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


def market_row(
    listing_id: int,
    ppm2: float,
    *,
    ward: str = "Phú Mỹ",
    road_name: str = "Đường N1",
    days_ago: int = 10,
    public_visible: bool = True,
    quality_flags: str = "",
    duplicate: bool = False,
    bait: bool = False,
):
    return {
        "listing_id": listing_id,
        "title": f"Lô {listing_id}",
        "source": "facebook",
        "ward": ward,
        "road_name": road_name,
        "road_tier": 2,
        "property_type": "dat_nen",
        "price_ty": round(ppm2 * 100 / 1000, 3),
        "price_per_m2": ppm2,
        "area_m2": 100.0,
        "frontage_m": 5.0,
        "depth_m": 20.0,
        "has_so": True,
        "price_dropped": False,
        "price_drop_pct": None,
        "possibly_duplicate": duplicate,
        "suspicious_bait": bait,
        "extraction_quality_flags": quality_flags,
        "public_visible": public_visible,
        "activity_at": NOW - timedelta(days=days_ago),
        "crawled_at": NOW - timedelta(days=days_ago),
    }


class FakeMarketConnection:
    def __init__(self):
        self.queries: list[tuple[str, tuple]] = []
        self.exact_90 = [market_row(i, 18 + i) for i in range(1, 6)]
        self.exact_180 = list(self.exact_90)
        self.fallback = [market_row(i + 20, 20 + i) for i in range(6)]
        self.area_rows = {
            "Phú Mỹ": [market_row(30 + i, value) for i, value in enumerate((18, 20, 22, 24, 26))],
            "Định Hòa": [
                market_row(40 + i, value, ward="Định Hòa")
                for i, value in enumerate((14, 15, 16, 17, 18))
            ],
        }
        self.trend_rows = [
            market_row(50, 18, days_ago=80),
            market_row(51, 20, days_ago=70),
            market_row(52, 22, days_ago=20),
            market_row(53, 24, days_ago=10),
        ]
        self.budget_rows = [
            market_row(60, 20, ward="Phú Mỹ"),
            market_row(61, 21, ward="Phú Mỹ"),
            market_row(62, 15, ward="Định Hòa"),
        ]
        self.deal_rows = [
            {
                **market_row(701, 17),
                "fair_ppm2": 22.0,
                "mos_pct": 22.7,
                "signal_score": 81,
                "is_actionable": False,
                "publisher_visible_public": True,
                "refreshed_at": NOW,
            },
            {
                **market_row(702, 18),
                "fair_ppm2": 22.0,
                "mos_pct": 18.2,
                "signal_score": 76,
                "is_actionable": True,
                "publisher_visible_public": True,
                "refreshed_at": NOW,
            },
            {
                **market_row(703, 19),
                "fair_ppm2": 22.0,
                "mos_pct": 13.6,
                "signal_score": 68,
                "is_actionable": True,
                "publisher_visible_public": True,
                "refreshed_at": NOW,
            },
        ]
        self.drop_rows = [
            {
                **self.deal_rows[1],
                "ward": "Phú Mỹ",
                "price_dropped": True,
                "price_drop_pct": 8.0,
            },
            {
                **self.deal_rows[2],
                "ward": "Định Hòa",
                "price_dropped": True,
                "price_drop_pct": 12.0,
                "mos_pct": 18.0,
            },
            {
                **self.deal_rows[2],
                "listing_id": 704,
                "ward": "Định Hòa",
                "price_dropped": True,
                "price_drop_pct": 6.0,
                "mos_pct": 20.0,
            },
        ]
        self.risk_listing = {
            **market_row(900, 9.0, quality_flags="low_segment_confidence,missing_area_evidence"),
            "possibly_duplicate": True,
            "suspicious_bait": True,
        }
        self.risk_valuation = {
            "valuation_id": 99,
            "listing_id": 900,
            "fair_ppm2": 20.0,
            "actual_ppm2": 9.0,
            "mos_pct": 55.0,
            "is_signal": True,
            "signal_score": 80,
            "n_segment": 2,
            "source_quality_flags": "low_segment_confidence,missing_area_evidence",
            "source_quality_recheck": True,
            "legal_status": "unverified",
            "trust_tier": "candidate_signal",
            "trust_score": 20,
            "legal_flags": "",
            "computed_at": NOW,
            "valuation_trace": {},
        }

    def execute(self, sql, params=()):
        normalized = " ".join(sql.split()).lower()
        self.queries.append((sql, tuple(params)))
        if "set_config('statement_timeout'" in normalized:
            return FakeResult([{"set_config": str(params[0])}])
        if "radar_ask:road_scopes" in normalized:
            allowed_wards = set(params[1:-1])
            wards = sorted(
                {
                    row["ward"]
                    for row in self.exact_180
                    if not allowed_wards or row["ward"] in allowed_wards
                }
            )
            return FakeResult(
                [{"ward": ward, "sample_count": 1, "as_of": NOW} for ward in wards]
            )
        if "radar_ask:road_exact" in normalized:
            window = int(params[-2]) if len(params) >= 2 else 90
            return FakeResult(self.exact_90 if window <= 90 else self.exact_180)
        if "radar_ask:road_fallback" in normalized:
            return FakeResult(self.fallback)
        if "radar_ask:area_sample" in normalized:
            return FakeResult(self.area_rows.get(str(params[0]), []))
        if "radar_ask:market_trend" in normalized:
            return FakeResult(
                [
                    {
                        "period": "previous",
                        "sample_count": 2,
                        "median_asking_ppm2_million": 19.0,
                        "activity_at": NOW - timedelta(days=70),
                    },
                    {
                        "period": "current",
                        "sample_count": 2,
                        "median_asking_ppm2_million": 23.0,
                        "activity_at": NOW - timedelta(days=10),
                    },
                ]
            )
        if "radar_ask:budget" in normalized:
            return FakeResult(self.budget_rows)
        if "radar_ask:deals" in normalized:
            return FakeResult(self.deal_rows)
        if "radar_ask:price_drop_areas" in normalized:
            grouped = {}
            for row in self.drop_rows:
                if not row["is_actionable"] or float(row["mos_pct"]) < 15:
                    continue
                grouped.setdefault(row["ward"], []).append(row)
            result = []
            for ward, rows in grouped.items():
                drops = sorted(float(row["price_drop_pct"]) for row in rows)
                mos = sorted(float(row["mos_pct"]) for row in rows)
                result.append(
                    {
                        "ward": ward,
                        "signal_count": len({row["listing_id"] for row in rows}),
                        "median_price_drop_pct": sum(drops) / len(drops),
                        "median_mos_pct": sum(mos) / len(mos),
                        "as_of": NOW,
                    }
                )
            return FakeResult(
                sorted(result, key=lambda row: row["signal_count"], reverse=True)
            )
        if "radar_ask:risk_listing" in normalized:
            return FakeResult([self.risk_listing])
        if "radar_ask:risk_valuation" in normalized:
            return FakeResult([self.risk_valuation])
        raise AssertionError(f"unexpected market query: {normalized}")


@contextmanager
def fake_factory(connection):
    yield connection


def context(connection, tier="free"):
    return ToolContext(
        ask=AskContext(user_id=21, tier=tier),
        read_conn_factory=lambda: fake_factory(connection),
    )


@pytest.mark.parametrize(
    ("sample_count", "expected_scope", "warning"),
    [(5, "exact_road", None), (3, "exact_road", "low_sample"), (2, "ward_road_tier_fallback", "insufficient_exact_road")],
)
def test_exact_road_thresholds(sample_count, expected_scope, warning):
    connection = FakeMarketConnection()
    connection.exact_90 = connection.exact_90[:sample_count]
    connection.exact_180 = connection.exact_180[:sample_count]

    bundle = estimate_road_market(
        args=RoadMarketArgs(road="Đường N1", ward="Phú Mỹ", window_days=90),
        context=context(connection),
    )

    assert bundle.calculations["market_scope"] == expected_scope
    if warning:
        assert warning in bundle.warnings
    else:
        assert warning not in bundle.warnings
    assert bundle.calculations["median_asking_ppm2_million"] > 0
    assert bundle.calculations["p25_asking_ppm2_million"] <= bundle.calculations["p75_asking_ppm2_million"]


def test_road_market_discloses_90_to_180_day_extension():
    connection = FakeMarketConnection()
    connection.exact_90 = connection.exact_90[:2]
    connection.exact_180 = [market_row(i, 18 + i, days_ago=120) for i in range(1, 5)]

    bundle = estimate_road_market(
        args=RoadMarketArgs(road="Đường N1", ward="Phú Mỹ", window_days=90),
        context=context(connection),
    )

    assert bundle.calculations["market_scope"] == "exact_road"
    assert bundle.calculations["window_days_used"] == 180
    assert "extended_window_90_to_180_days" in bundle.warnings


def test_road_market_discloses_the_actual_requested_window_extension():
    connection = FakeMarketConnection()
    connection.exact_90 = connection.exact_90[:2]
    connection.exact_180 = connection.exact_180[:4]

    bundle = estimate_road_market(
        args=RoadMarketArgs(road="Đường N1", ward="Phú Mỹ", window_days=30),
        context=context(connection),
    )

    assert "extended_window_30_to_180_days" in bundle.warnings
    assert "extended_window_90_to_180_days" not in bundle.warnings


def test_road_market_requires_clarification_for_same_road_in_multiple_wards():
    connection = FakeMarketConnection()
    connection.exact_90 = [
        market_row(1, 20, ward="Phú Mỹ"),
        market_row(2, 21, ward="Định Hòa"),
        market_row(3, 22, ward="Phú Mỹ"),
        market_row(4, 23, ward="Định Hòa"),
    ]
    connection.exact_180 = list(connection.exact_90)

    bundle = estimate_road_market(
        args=RoadMarketArgs(road="Đường N1"),
        context=context(connection),
    )

    assert bundle.needs_clarification is True
    assert set(bundle.clarification_candidates) == {
        "Đường N1, Phú Mỹ",
        "Đường N1, Định Hòa",
    }
    assert bundle.items == []


def test_road_market_rejects_city_and_ward_mismatch():
    bundle = estimate_road_market(
        args=RoadMarketArgs(
            road="Đường N1",
            ward="Phú Mỹ",
            city="Bến Cát",
        ),
        context=context(FakeMarketConnection()),
    )

    assert "city_ward_scope_mismatch" in bundle.missing_requirements


def test_market_sample_excludes_quality_blockers_duplicates_and_bait():
    connection = FakeMarketConnection()
    connection.exact_90.extend(
        [
            market_row(91, 1, quality_flags="missing_area_evidence"),
            market_row(92, 2, duplicate=True),
            market_row(93, 3, bait=True),
        ]
    )

    bundle = estimate_road_market(
        args=RoadMarketArgs(road="Đường N1", ward="Phú Mỹ"),
        context=context(connection),
    )

    assert bundle.calculations["sample_count"] == 5
    assert bundle.calculations["median_asking_ppm2_million"] == 21.0


def test_compare_areas_labels_asking_market_and_returns_each_area():
    bundle = compare_areas(
        args=CompareAreasArgs(areas=["Phú Mỹ", "Định Hòa"]),
        context=context(FakeMarketConnection()),
    )

    assert set(bundle.calculations["areas"]) == {"Phú Mỹ", "Định Hòa"}
    assert bundle.calculations["metric"] == "asking_price_per_m2"
    assert all(item.source_kind is SourceKind.MARKET_STAT for item in bundle.items)


def test_market_trend_compares_server_calculated_period_medians():
    connection = FakeMarketConnection()
    bundle = get_market_trend(
        args=MarketTrendArgs(ward="Phú Mỹ", window_days=90),
        context=context(connection),
    )

    assert bundle.calculations["previous_median_asking_ppm2_million"] == 19.0
    assert bundle.calculations["current_median_asking_ppm2_million"] == 23.0
    assert bundle.calculations["change_pct"] == pytest.approx(21.05, abs=0.01)
    trend_sql = next(sql for sql, _ in connection.queries if "radar_ask:market_trend" in sql)
    normalized = " ".join(trend_sql.lower().split())
    assert "percentile_cont(0.5)" in normalized
    assert "group by period" in normalized


def test_match_budget_ranks_areas_without_calling_llm_for_arithmetic():
    connection = FakeMarketConnection()
    connection.budget_rows.append(market_row(63, 14, ward="Mỹ Phước 1"))
    bundle = match_budget(
        args=MatchBudgetArgs(budget_ty="2.5", city="THỦ DẦU MỘT", limit=10),
        context=context(connection),
    )

    assert bundle.calculations["budget_ty"] == 2.5
    assert bundle.calculations["matched_listing_count"] == 3
    assert bundle.calculations["area_matches"][0]["ward"] == "Phú Mỹ"


def test_search_deals_uses_only_actionable_gate_and_public_mos_floor():
    bundle = search_deals(
        args=SearchDealsArgs(max_price_per_m2_million=20, mos_min_pct=10),
        context=context(FakeMarketConnection(), tier="free"),
    )

    refs = {item.value["listing_ref"] for item in bundle.items}
    assert "radar-listing:701" not in refs
    assert "radar-listing:702" in refs
    assert "radar-listing:703" not in refs
    assert bundle.calculations["effective_mos_min_pct"] == 15.0


@pytest.mark.parametrize("tier", ["vip", "admin"])
def test_smart_tiers_can_explicitly_inspect_10_to_14_9_mos_with_warning(tier):
    bundle = search_deals(
        args=SearchDealsArgs(mos_min_pct=12),
        context=context(FakeMarketConnection(), tier=tier),
    )

    refs = {item.value["listing_ref"] for item in bundle.items}
    assert "radar-listing:703" in refs
    assert bundle.calculations["effective_mos_min_pct"] == 12.0
    assert "below_public_mos_threshold_caution" in bundle.warnings


def test_rank_price_drop_areas_uses_actionable_rows_and_counts_unique_listings():
    connection = FakeMarketConnection()
    bundle = rank_price_drop_areas(
        args=RankPriceDropAreasArgs(window_days=1),
        context=context(connection),
    )

    assert bundle.calculations["areas"][0]["ward"] == "Định Hòa"
    assert bundle.calculations["areas"][0]["signal_count"] == 2
    drop_sql = next(sql for sql, _ in connection.queries if "radar_ask:price_drop_areas" in sql)
    normalized = " ".join(drop_sql.split()).lower()
    assert "price_updated_at::timestamptz >=" in normalized
    assert "mos_pct>=15" in normalized
    assert "publisher_visible_public" in normalized
    assert "group by ward" in normalized


def test_inspect_listing_risks_separates_blockers_from_confidence_warning():
    bundle = inspect_listing_risks(
        args=InspectListingRisksArgs(listing_id=900),
        context=context(FakeMarketConnection()),
    )

    assert "missing_area_evidence" in bundle.calculations["blocking_flags"]
    assert "possibly_duplicate" in bundle.calculations["blocking_flags"]
    assert "suspicious_bait" in bundle.calculations["blocking_flags"]
    assert "low_segment_confidence" in bundle.calculations["warning_flags"]


def test_inspect_listing_risks_accepts_has_document_and_surfaces_legal_conflicts():
    connection = FakeMarketConnection()
    connection.risk_valuation.update(
        legal_status="has_document",
        trust_tier="has_legal_doc",
        legal_flags="road_conflict",
        source_quality_flags="",
        source_quality_recheck=False,
    )
    connection.risk_listing.update(
        extraction_quality_flags="",
        possibly_duplicate=False,
        suspicious_bait=False,
    )

    bundle = inspect_listing_risks(
        args=InspectListingRisksArgs(listing_id=900),
        context=context(connection),
    )

    assert "legal_status_not_verified" not in bundle.calculations["warning_flags"]
    assert "road_conflict" in bundle.calculations["blocking_flags"]


def test_market_registry_dispatches_all_seven_real_handlers():
    connection = FakeMarketConnection()
    calls = [
        ToolCall(call_id="m1", name="estimate_road_market", arguments={"road": "Đường N1", "ward": "Phú Mỹ"}),
        ToolCall(call_id="m2", name="compare_areas", arguments={"areas": ["Phú Mỹ", "Định Hòa"]}),
        ToolCall(call_id="m3", name="get_market_trend", arguments={"ward": "Phú Mỹ"}),
        ToolCall(call_id="m4", name="match_budget", arguments={"budget_ty": "2.5"}),
        ToolCall(call_id="m5", name="search_deals", arguments={}),
        ToolCall(call_id="m6", name="rank_price_drop_areas", arguments={}),
        ToolCall(call_id="m7", name="inspect_listing_risks", arguments={"listing_id": 900}),
    ]

    assert all(execute_tool(call, context(connection)).question_snapshot for call in calls)
