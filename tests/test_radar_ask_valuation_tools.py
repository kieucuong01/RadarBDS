from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from services.radar_ask.contracts import AskContext, SourceKind, ToolCall
from services.radar_ask.registry import (
    ComparableArgs,
    ExplainValuationArgs,
    SampleQualityArgs,
    ToolContext,
    execute_tool,
)
from services.radar_ask.tools.valuation import (
    check_sample_quality,
    explain_valuation,
    find_comparables,
)


NOW = datetime(2026, 8, 4, 10, 0, tzinfo=timezone.utc)


class FakeResult:
    def __init__(self, rows):
        self.rows = list(rows)

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


def target_row(listing_id=123):
    return {
        "listing_id": listing_id,
        "title": "Lô đất an toàn",
        "source": "facebook",
        "ward": "Phú Mỹ",
        "road_name": "Đường N1",
        "road_tier": 2,
        "property_type": "dat_nen",
        "price_ty": 1.8,
        "price_per_m2": 18.0,
        "area_m2": 100.0,
        "frontage_m": 5.0,
        "depth_m": 20.0,
        "has_so": True,
        "possibly_duplicate": False,
        "suspicious_bait": False,
        "extraction_quality_flags": "",
        "measurement_provenance": '{"area_m2":"declared_text"}',
        "public_visible": True,
        "crawled_at": NOW,
        "last_seen_at": NOW,
    }


def valuation_row(*, trace=True, valuation_id=10, computed_at=NOW):
    return {
        "valuation_id": valuation_id,
        "model_run_id": 7,
        "listing_id": 123,
        "fair_ppm2": 22.0,
        "actual_ppm2": 18.0,
        "mos_pct": 18.18,
        "is_signal": True,
        "signal_score": 80,
        "segment": "Phú Mỹ|dat_nen|ban",
        "n_segment": 8,
        "source_quality_flags": "low_segment_confidence",
        "source_quality_recheck": False,
        "legal_status": "unverified",
        "trust_tier": "candidate_signal",
        "trust_score": 40,
        "legal_flags": "",
        "computed_at": computed_at,
        "valuation_trace": {
            "trace_version": 1,
            "model_name": "segment_regression",
            "model_version": "main_v1",
            "requested_segment": "Phú Mỹ|dat_nen|ban|road_bucket_2",
            "effective_segment": "Phú Mỹ|dat_nen|ban|road_bucket_2",
            "fallback_reason": None,
            "baseline_ppm2": 20.0,
            "adjustments": [
                {
                    "code": "road_width",
                    "input_value": 6,
                    "multiplier": 1.1,
                    "delta_ppm2": 2.0,
                    "applied": True,
                    "reason": "wider road",
                }
            ],
            "final_fair_ppm2": 22.0,
            "final_fair_total": 2200.0,
            "confidence_low_ppm2": None,
            "confidence_high_ppm2": None,
            "sample_count": 8,
            "comparable_listing_ids": [201, 202],
            "quality_flags": ["low_segment_confidence"],
            "suppressed_factors": [],
            "measurement_provenance": {"area_m2": "declared_text"},
        }
        if trace
        else {},
    }


def comparable_row(listing_id, ppm2, *, flags="", duplicate=False, bait=False):
    row = target_row(listing_id)
    row.update(
        price_ty=round(ppm2 * 100 / 1000, 3),
        price_per_m2=ppm2,
        extraction_quality_flags=flags,
        possibly_duplicate=duplicate,
        suspicious_bait=bait,
        crawled_at=NOW - timedelta(days=10),
        last_seen_at=NOW - timedelta(days=10),
        fair_ppm2=ppm2 + 2,
        mos_pct=8.0,
        valuation_id=listing_id + 1000,
        valuation_computed_at=NOW - timedelta(days=40),
    )
    return row


class FakeValuationConnection:
    def __init__(self, *, trace=True, comparables_error: Exception | None = None):
        self.queries: list[tuple[str, tuple]] = []
        self.listing = target_row()
        self.valuation = valuation_row(trace=trace)
        self.comparables_error = comparables_error
        self.comparables = [
            comparable_row(201, 19),
            comparable_row(202, 20),
            comparable_row(203, 1, flags="missing_area_evidence"),
            comparable_row(204, 2, duplicate=True),
            comparable_row(205, 3, bait=True),
            comparable_row(206, 21),
        ]

    def execute(self, sql, params=()):
        normalized = " ".join(sql.split()).lower()
        self.queries.append((sql, tuple(params)))
        if "set_config('statement_timeout'" in normalized:
            return FakeResult([{"set_config": str(params[0])}])
        if "radar_ask:valuation_listing" in normalized:
            return FakeResult([self.listing])
        if "radar_ask:latest_valuation" in normalized:
            return FakeResult([self.valuation])
        if "radar_ask:comparables" in normalized:
            if self.comparables_error is not None:
                raise self.comparables_error
            return FakeResult(self.comparables)
        raise AssertionError(f"unexpected valuation query: {normalized}")


@contextmanager
def fake_factory(connection):
    yield connection


def context(connection, tier="free"):
    return ToolContext(
        ask=AskContext(user_id=22, tier=tier),
        read_conn_factory=lambda: fake_factory(connection),
    )


def test_explain_valuation_returns_persisted_trace_not_reconstructed_math():
    connection = FakeValuationConnection(trace=True)

    bundle = explain_valuation(
        args=ExplainValuationArgs(listing_id=123),
        context=context(connection),
    )

    trace_item = next(item for item in bundle.items if item.source_kind is SourceKind.VALUATION)
    assert trace_item.value["trace"]["baseline_ppm2"] == 20.0
    assert trace_item.value["trace"]["adjustments"][0]["delta_ppm2"] == 2.0
    assert "comparable_listing_ids" not in trace_item.value["trace"]
    assert trace_item.value["trace"]["comparable_listing_refs"] == [
        "radar-listing:201",
        "radar-listing:202",
    ]
    assert trace_item.value["fair_total_ty"] == 2.2
    assert "historical_valuation_trace" not in bundle.missing_requirements


def test_explain_valuation_refuses_to_reverse_engineer_missing_legacy_trace():
    bundle = explain_valuation(
        args=ExplainValuationArgs(listing_id=123),
        context=context(FakeValuationConnection(trace=False)),
    )

    assert "historical_valuation_trace" in bundle.missing_requirements
    assert "legacy_valuation_trace_unavailable" in bundle.warnings
    assert all("adjustments" not in item.value for item in bundle.items)


def test_explain_valuation_keeps_trace_when_optional_comparables_timeout():
    bundle = explain_valuation(
        args=ExplainValuationArgs(listing_id=123),
        context=context(FakeValuationConnection(comparables_error=TimeoutError("slow"))),
    )

    trace_item = next(item for item in bundle.items if item.source_kind is SourceKind.VALUATION)
    assert trace_item.value["trace"]["baseline_ppm2"] == 20.0
    assert "valuation_comparables_not_currently_available" in bundle.warnings
    assert bundle.missing_requirements == []


def test_find_comparables_is_bounded_and_excludes_bad_inputs():
    bundle = find_comparables(
        args=ComparableArgs(listing_id=123, limit=3, window_days=180),
        context=context(FakeValuationConnection()),
    )

    refs = [item.value["listing_ref"] for item in bundle.items]
    assert refs == ["radar-listing:201", "radar-listing:202", "radar-listing:206"]
    assert bundle.calculations["sample_count"] == 3
    assert bundle.calculations["metric"] == "asking_price_per_m2"
    first = bundle.items[0]
    assert first.value["listing_as_of"].startswith("2026-07-25")
    assert first.value["valuation_as_of"].startswith("2026-06-25")
    assert first.as_of == NOW - timedelta(days=40)


def test_check_sample_quality_keeps_low_confidence_as_warning_not_blocker():
    bundle = check_sample_quality(
        args=SampleQualityArgs(listing_id=123),
        context=context(FakeValuationConnection()),
    )

    assert bundle.calculations["sample_count"] == 8
    assert bundle.calculations["quality"] == "usable_with_caution"
    assert "low_segment_confidence" in bundle.warnings
    assert bundle.missing_requirements == []


def test_valuation_queries_order_latest_snapshot_explicitly():
    connection = FakeValuationConnection()
    explain_valuation(
        args=ExplainValuationArgs(listing_id=123),
        context=context(connection),
    )

    valuation_sql = next(sql for sql, _ in connection.queries if "radar_ask:latest_valuation" in sql)
    normalized = " ".join(valuation_sql.lower().split())
    assert "order by computed_at desc, valuation_id desc" in normalized
    assert "limit 1" in normalized


def test_valuation_registry_dispatches_three_real_handlers():
    connection = FakeValuationConnection()
    calls = [
        ToolCall(call_id="v1", name="explain_valuation", arguments={"listing_id": 123}),
        ToolCall(call_id="v2", name="find_comparables", arguments={"listing_id": 123, "limit": 3}),
        ToolCall(call_id="v3", name="check_sample_quality", arguments={"listing_id": 123}),
    ]

    assert all(execute_tool(call, context(connection)).question_snapshot for call in calls)
