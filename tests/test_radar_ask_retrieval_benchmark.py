from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.radar_ask_retrieval_benchmark import (
    PRODUCTION_RETRIEVAL_LIMIT,
    activation_gate,
    build_report,
    evaluate_rankings,
    load_benchmark_fixture,
)


CASES = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "radar_ask"
    / "retrieval_cases.json"
)


def test_fixture_has_50_non_pii_cases_across_required_categories():
    benchmark = load_benchmark_fixture(CASES)

    assert len(benchmark.cases) >= 50
    assert {case.category for case in benchmark.cases} == {
        "address_alias",
        "post_merger_ward",
        "legal_terminology",
        "official_land_price",
        "market_paraphrase",
        "exact_source",
    }
    encoded = json.dumps(benchmark.raw, ensure_ascii=False)
    assert "@" not in encoded
    assert "http://" not in encoded
    assert "https://" not in encoded
    assert PRODUCTION_RETRIEVAL_LIMIT == 5


def test_metrics_are_computed_by_category_and_exact_source():
    benchmark = load_benchmark_fixture(CASES)
    rankings = {
        case.case_id: list(case.accepted_chunk_ids)
        for case in benchmark.cases
    }
    metrics = evaluate_rankings(benchmark, rankings)

    assert metrics["macro_recall_at_5"] == 1.0
    assert metrics["mrr_at_10"] == 1.0
    assert metrics["exact_source_recall_at_5"] == 1.0
    assert set(metrics["categories"]) == {
        case.category for case in benchmark.cases
    }


@pytest.mark.parametrize(
    ("semantic_recall", "exact_source", "memory_mb", "latency_ms", "expected"),
    [
        (0.90, 0.90, 300.0, 200.0, True),
        (0.87, 0.90, 300.0, 200.0, False),
        (0.90, 0.84, 300.0, 200.0, False),
        (0.90, 0.90, 350.0, 200.0, False),
        (0.90, 0.90, 300.0, 251.0, False),
    ],
)
def test_activation_gate_is_fail_closed(
    semantic_recall,
    exact_source,
    memory_mb,
    latency_ms,
    expected,
):
    decision = activation_gate(
        fts_macro_recall_at_5=0.80,
        semantic_macro_recall_at_5=semantic_recall,
        exact_source_recall_at_5=exact_source,
        peak_memory_mb=memory_mb,
        memory_allowance_mb=1_024.0,
        p95_query_latency_ms=latency_ms,
        worker_processes=3,
        production_path_verified=True,
    )

    assert decision["eligible"] is expected


def test_activation_gate_rejects_non_production_semantic_path():
    decision = activation_gate(
        fts_macro_recall_at_5=0.80,
        semantic_macro_recall_at_5=0.90,
        exact_source_recall_at_5=0.90,
        peak_memory_mb=300.0,
        memory_allowance_mb=1_024.0,
        p95_query_latency_ms=200.0,
        worker_processes=3,
        production_path_verified=False,
    )

    assert decision["eligible"] is False
    assert decision["checks"]["production_hnsw_rrf_path_verified"] is False


def test_report_contains_metrics_but_no_raw_document_text():
    benchmark = load_benchmark_fixture(CASES)
    rankings = {
        case.case_id: list(case.accepted_chunk_ids)
        for case in benchmark.cases
    }
    report = build_report(
        benchmark=benchmark,
        mode="fts",
        rankings=rankings,
        latencies_ms=[1.0] * len(benchmark.cases),
        indexing_time_ms=2.0,
        peak_memory_mb=12.0,
    )
    encoded = json.dumps(report, ensure_ascii=False)

    assert report["case_count"] == len(benchmark.cases)
    assert "corpus" not in report
    assert benchmark.corpus[0].text not in encoded
