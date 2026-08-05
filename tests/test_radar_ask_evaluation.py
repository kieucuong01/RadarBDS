from __future__ import annotations

import copy
import json
import os
import re
import socket
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import scripts.evaluate_radar_ask as evaluation_module
from services.radar_ask.config import RadarAskSettings
from services.radar_ask.contracts import ProviderUsage
from scripts.evaluate_radar_ask import (
    REQUIRED_CATEGORIES,
    RecordingGuardError,
    ReleaseGateError,
    assert_release_gates,
    capture_planner_provider_payload,
    evaluate_corpus,
    load_corpus,
    record_provider_cases,
    sanitize_record,
    validate_record_output_path,
    verify_test_database_url,
)


ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "tests" / "fixtures" / "radar_ask" / "golden_questions.json"
SCRIPT_PATH = ROOT / "scripts" / "evaluate_radar_ask.py"

APPROVED_QUESTIONS = {
    "Ngân sách 2.5 tỷ ở Thủ Dầu Một nên xem phường nào?",
    "Phú Mỹ và Định Hòa giá đất nền khác nhau sao?",
    "Tin nào dưới 20 triệu/m² đang đáng kiểm tra?",
    "Khu nào có nhiều tín hiệu giảm giá hôm nay?",
    "Bảng giá đất TP.HCM có dùng để định giá thực tế không?",
}


@pytest.fixture(scope="module")
def golden_corpus():
    return load_corpus(CASES_PATH)


@pytest.fixture(scope="module")
def golden_report(golden_corpus):
    return evaluate_corpus(golden_corpus, mode="deterministic")


def test_golden_fixture_is_versioned_bounded_and_covers_every_release_category(golden_corpus):
    cases = golden_corpus["cases"]
    assert golden_corpus["schema_version"] == 1
    assert re.fullmatch(r"radar-ask-golden-v\d+", golden_corpus["dataset_version"])
    assert 120 <= len(cases) <= 250
    assert len({case["id"] for case in cases}) == len(cases)
    assert len({case["question"] for case in cases}) == len(cases)
    assert REQUIRED_CATEGORIES <= {case["category"] for case in cases}
    assert APPROVED_QUESTIONS <= {case["question"] for case in cases}


def test_golden_observations_have_pragmatic_independent_diversity(golden_corpus):
    fixtures = golden_corpus["fixtures"]
    cases = golden_corpus["cases"]

    assert len(fixtures["evidence_bundles"]) >= 24
    assert len(fixtures["answer_candidates"]) >= 24
    assert len(fixtures["planner_outputs"]) >= 12

    road_cases = [case for case in cases if case["category"] == "exact_road_market_price"]
    road_names = {
        re.search(r"đường\s+(.+?)(?:\s+(?:hiện tại|là|bao nhiêu)|\?)", case["question"], re.I).group(1)
        for case in road_cases
    }
    assert len(road_names) >= 5
    assert len({case["expected"]["numeric_value"] for case in road_cases}) >= 5

    valuation_cases = [
        case for case in cases if case["category"] == "listing_valuation_explanation"
    ]
    assert len({case["page_context"]["listing_id"] for case in valuation_cases}) >= 4
    assert len({case["expected"]["numeric_value"] for case in valuation_cases}) >= 4
    assert len(
        {
            case["expected"]["numeric_value"]
            for case in cases
            if case["expected"]["numeric_value"] is not None
        }
    ) >= 10

    grounded_categories = {
        "budget_to_ward",
        "ward_comparison",
        "listing_valuation_explanation",
        "exact_road_market_price",
        "deals_under_ppm2",
        "price_drop_areas",
        "official_land_price_purpose",
    }
    for category in grounded_categories:
        pairs = {
            (
                tuple(sorted(case["observed"].get("evidence_by_tool", {}).values())),
                case["observed"].get("answer_candidate_id"),
            )
            for case in cases
            if case["category"] == category
        }
        assert len(pairs) >= 2, category


def test_each_case_keeps_expected_truth_separate_from_observed_fixtures(golden_corpus):
    for case in golden_corpus["cases"]:
        assert set(case) == {
            "id",
            "category",
            "question",
            "tier",
            "authenticated",
            "page_context",
            "expected",
            "observed",
        }
        expected = case["expected"]
        assert {
            "depth",
            "question_type",
            "tools",
            "required_evidence_kinds",
            "forbidden_evidence_kinds",
            "answer_class",
            "verdict",
            "numeric_tolerance",
            "validation_outcome",
        } <= set(expected)
        assert "answer" not in expected
        assert "evidence" not in expected
        assert "planner_output" not in expected
        assert set(case["observed"]) <= {
            "planner_output_id",
            "evidence_by_tool",
            "answer_candidate_id",
        }


def test_fixture_has_no_real_contact_or_account_identifiers(golden_corpus):
    encoded = json.dumps(golden_corpus, ensure_ascii=False)
    phone_matches = re.findall(r"(?<!\d)(?:\+?84|0)(?:[ .-]?\d){9,10}(?!\d)", encoded)
    assert set(phone_matches) <= {"0000 000 000"}
    assert "0000 000 000 (số giả lập)" in encoded
    assert re.search(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", encoded, re.I) is None
    assert re.search(r"\b(?:cccd|cmnd|mst|số tài khoản|so tai khoan)\s*[:#-]?\s*\d{6,}\b", encoded, re.I) is None
    assert "tên minh họa" in encoded


def test_default_evaluation_is_offline_and_does_not_open_database(monkeypatch, golden_corpus):
    def forbidden_network(*_args, **_kwargs):
        raise AssertionError("deterministic evaluation attempted network access")

    monkeypatch.setattr(socket, "create_connection", forbidden_network)
    monkeypatch.setenv("DATABASE_URL", "postgresql://forbidden.invalid/radar_bds")
    monkeypatch.setenv("RADAR_TEST_DATABASE_URL", "postgresql://forbidden.invalid/radar_bds_test")

    report = evaluate_corpus(golden_corpus, mode="deterministic")

    assert report["mode"] == "deterministic"
    assert report["network_calls"] == 0
    assert report["database_calls"] == 0


def test_denied_auth_cases_use_real_http_gate_and_never_reach_downstream(
    monkeypatch,
    golden_corpus,
):
    denied = copy.deepcopy(golden_corpus)
    denied["cases"] = [case for case in denied["cases"] if not case["authenticated"]]

    def forbidden(*_args, **_kwargs):
        raise AssertionError("denied Radar Ask case reached routing, provider, or tool execution")

    monkeypatch.setattr(evaluation_module, "route_question", forbidden)
    monkeypatch.setattr(evaluation_module, "execute_tool", forbidden)
    monkeypatch.setattr(evaluation_module, "capture_planner_provider_payload", forbidden)

    report = evaluate_corpus(denied, mode="deterministic")

    assert report["metrics"]["auth_policy_pass_rate"] == 1.0
    assert report["denominators"]["auth"] == len(denied["cases"])


def test_actual_http_gate_regression_lowers_auth_metric(monkeypatch, golden_corpus):
    baseline = evaluate_corpus(golden_corpus, mode="deterministic")
    from routes import radar_ask_api as radar_ask_api_route

    def deny_everyone_regression():
        return radar_ask_api_route.api_error(
            "login_required",
            "login required",
            401,
        )

    monkeypatch.setattr(
        radar_ask_api_route,
        "_gate",
        deny_everyone_regression,
    )
    mutated = evaluate_corpus(golden_corpus, mode="deterministic")

    assert baseline["metrics"]["auth_policy_pass_rate"] == 1.0
    assert mutated["metrics"]["auth_policy_pass_rate"] < 1.0


def test_real_typed_planner_payload_exposes_carry_forward_name_leaks_without_network(
    golden_corpus,
):
    by_id = {case["id"]: case for case in golden_corpus["cases"]}

    captured = {
        case_id: capture_planner_provider_payload(golden_corpus, by_id[case_id])
        for case_id in ("privacy-001", "privacy-002", "privacy-004", "privacy-006")
    }
    assert all('"tool_registry"' in payload for payload in captured.values())
    expected_failures = set()
    for case_id, payload in captured.items():
        expected = by_id[case_id]["expected"]
        folded = payload.casefold()
        leaks_name = any(
            token.casefold() in folded
            for token in expected.get("planner_private_tokens", [])
        )
        loses_semantics = any(
            token.casefold() not in folded
            for token in expected.get("planner_required_semantics", [])
        )
        if leaks_name or loses_semantics:
            expected_failures.add(case_id)

    report = evaluate_corpus(golden_corpus, mode="deterministic")
    privacy_failures = {
        failure["case_id"]
        for failure in report["failures"]
        if failure["dimension"] == "privacy:planner_payload"
    }
    assert privacy_failures == expected_failures


def test_golden_release_gates(golden_report):
    metrics = golden_report["metrics"]
    assert metrics["routing_accuracy"] >= 0.95
    assert metrics["tool_selection_accuracy"] >= 0.95
    assert metrics["numeric_grounding_rate"] == 1.0
    assert metrics["citation_validity_rate"] == 1.0
    assert metrics["privacy_pass_rate"] == 1.0
    assert metrics["auth_policy_pass_rate"] == 1.0
    assert metrics["unsupported_claim_rate"] == 0.0
    assert_release_gates(golden_report)


def test_refusal_and_answer_classes_are_scored_independently(golden_report):
    assert golden_report["metrics"]["answer_class_accuracy"] == 1.0
    assert golden_report["metrics"]["refusal_accuracy"] == 1.0


def test_report_is_deterministic_bounded_and_contains_no_prompts_or_raw_evidence(golden_corpus):
    first = evaluate_corpus(golden_corpus, mode="deterministic")
    second = evaluate_corpus(copy.deepcopy(golden_corpus), mode="deterministic")
    assert first == second
    encoded = json.dumps(first, ensure_ascii=False, sort_keys=True).encode("utf-8")
    assert len(encoded) <= 131_072
    assert b'"question"' not in encoded
    assert b'"prompt"' not in encoded
    assert b'"raw_evidence"' not in encoded
    assert b"http://" not in encoded
    assert b"https://" not in encoded


def test_expected_truth_is_not_used_as_the_planner_observation(golden_corpus):
    mutated = copy.deepcopy(golden_corpus)
    case = next(
        item
        for item in mutated["cases"]
        if item["observed"].get("planner_output_id")
    )
    planner_id = case["observed"]["planner_output_id"]
    mutated["fixtures"]["planner_outputs"][planner_id]["question_type"] = "wrong_route"

    report = evaluate_corpus(mutated, mode="deterministic")

    assert report["metrics"]["routing_accuracy"] < 0.95
    with pytest.raises(ReleaseGateError, match="routing_accuracy"):
        assert_release_gates(report)


def test_numeric_mutation_fails_numeric_gate_independently(golden_corpus):
    baseline = evaluate_corpus(golden_corpus, mode="deterministic")
    mutated = copy.deepcopy(golden_corpus)
    case = next(
        item
        for item in mutated["cases"]
        if item["expected"]["validation_outcome"] == "accept"
        and item["expected"]["numeric_tolerance"] is not None
    )
    answer_id = case["observed"]["answer_candidate_id"]
    candidate = mutated["fixtures"]["answer_candidates"][answer_id]
    candidate["claims"][0]["numeric_value"] = 999
    candidate["claims"][0]["text"] = "Giá rao tham khảo là 999 triệu/m²."
    candidate["direct_answer"] = "Giá rao tham khảo là 999 triệu/m²."

    report = evaluate_corpus(mutated, mode="deterministic")

    assert report["metrics"]["numeric_grounding_rate"] < 1.0
    assert report["metrics"]["privacy_pass_rate"] == baseline["metrics"]["privacy_pass_rate"]


def test_record_output_guard_requires_ignored_reports_path(tmp_path):
    reports_path = ROOT / "reports" / "radar_ask_provider_record.json"
    assert validate_record_output_path(reports_path, repo_root=ROOT) == reports_path.resolve()
    with pytest.raises(RecordingGuardError, match="reports"):
        validate_record_output_path(tmp_path / "record.json", repo_root=ROOT)
    with pytest.raises(RecordingGuardError, match="golden"):
        validate_record_output_path(CASES_PATH, repo_root=ROOT)


def test_provider_recording_requires_cost_confirmation_before_runner_call(golden_corpus, tmp_path):
    calls = []
    output = ROOT / "reports" / "guard-test.json"

    with pytest.raises(RecordingGuardError, match="confirm-live-cost"):
        record_provider_cases(
            golden_corpus,
            output_path=output,
            confirm_live_cost=False,
            provider_case_runner=lambda case, corpus: calls.append(case),
            repo_root=ROOT,
        )

    assert calls == []
    assert not output.exists()


def test_recording_sanitizes_typed_envelopes_and_never_mutates_golden(golden_corpus):
    corpus_before = copy.deepcopy(golden_corpus)
    records = record_provider_cases(
        golden_corpus,
        output_path=ROOT / "reports" / "sanitizer-test.json",
        confirm_live_cost=True,
        provider_case_runner=lambda case, corpus: {
            "case_id": case["id"],
            "status": "completed",
            "model": "deepseek-test",
            "usage": {"input_tokens": 12, "output_tokens": 8},
            "actual_usd": "0.0001",
            "prompt": "đừng lưu câu hỏi",
            "raw_evidence": {"phone": "0901 234 567"},
            "account_id": "acct-secret-77",
            "answer": {
                "answered": True,
                "depth": "fast",
                "verdict": "can_kiem_tra_them",
                "direct_answer": "Nguyễn Văn An nói xem https://secret.example, acct-secret-77.",
                "claims": [{"text": "Provider claim secret", "evidence_ids": ["raw-evidence-77"]}],
                "key_metrics": [{"label": "Giá bí mật", "value": "acct-secret-77", "evidence_ids": ["raw-evidence-77"]}],
                "source_cards": [{
                    "evidence_id": "raw-evidence-77",
                    "title": "Nguồn Nguyễn Văn An",
                    "source_kind": "market_stat",
                    "source_ref": "acct-secret-77",
                    "as_of": "2026-08-04T00:00:00Z",
                    "href": "https://secret.example",
                }],
                "as_of": "2026-08-04T00:00:00Z",
                "dataset_version": "acct-secret-77",
            },
        },
        repo_root=ROOT,
        write_output=False,
        case_limit=1,
    )

    assert golden_corpus == corpus_before
    encoded = json.dumps(records, ensure_ascii=False)
    for forbidden in (
        "prompt",
        "raw_evidence",
        "account_id",
        "0901 234 567",
        "https://secret.example",
        "acct-secret-77",
        "Nguyễn Văn An",
        "raw-evidence-77",
        "Provider claim secret",
        "Giá bí mật",
    ):
        assert forbidden not in encoded
    answer = records["records"][0]["answer"]
    assert answer["direct_answer"] == "[provider text removed]"
    assert answer["claims"][0]["text"] == "[provider claim removed]"
    assert answer["claims"][0]["evidence_ids"] == ["evidence-001"]
    assert answer["key_metrics"][0]["evidence_ids"] == ["evidence-001"]
    assert answer["source_cards"][0]["evidence_id"] == "evidence-001"
    assert answer["source_cards"][0]["source_ref"] == "source-001"
    assert answer["source_cards"][0]["href"] is None


def test_live_recording_prompt_has_schema_and_no_golden_answer_or_raw_evidence(
    monkeypatch,
    golden_corpus,
):
    case = copy.deepcopy(
        next(item for item in golden_corpus["cases"] if item["id"] == "valuation-001")
    )
    case["question"] = "Nguyễn Văn An hỏi lô này, tài khoản acct-secret-77"
    fixture_answer = golden_corpus["fixtures"]["answer_candidates"][
        case["observed"]["answer_candidate_id"]
    ]
    captured = {}

    class FakeProvider:
        def complete_json(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                json_value=copy.deepcopy(fixture_answer),
                usage=ProviderUsage(),
            )

    monkeypatch.setattr(
        evaluation_module,
        "DeepSeekProvider",
        lambda *, settings: FakeProvider(),
    )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key-not-live")
    runner = evaluation_module._live_provider_runner(RadarAskSettings.from_env())

    runner(case, golden_corpus)

    prompt = json.loads(captured["messages"][0].content)
    encoded = json.dumps(prompt, ensure_ascii=False)
    assert set(prompt) == {
        "task",
        "question",
        "expected_depth",
        "allowed_evidence_ids",
        "answer_schema",
    }
    assert prompt["allowed_evidence_ids"] == ["evidence-001", "evidence-002"]
    assert "shape_example" not in encoded
    assert fixture_answer["direct_answer"] not in encoded
    assert "ev-listing" not in encoded
    assert "ev-valuation" not in encoded
    assert "Nguyễn Văn An" not in encoded
    assert "acct-secret-77" not in encoded
    assert len(encoded.encode("utf-8")) <= 48_000


def test_sanitize_record_is_recursive_bounded_and_keeps_only_record_contract():
    sanitized = sanitize_record(
        {
            "case_id": "case-1",
            "status": "completed",
            "model": "deepseek-test",
            "usage": {"input_tokens": 5, "output_tokens": 4, "secret": "x"},
            "actual_usd": "0.01",
            "answer": {
                "answered": False,
                "depth": "standard",
                "verdict": "khong_du_du_lieu",
                "direct_answer": "Email owner@example.com; CCCD: 012345678901",
                "claims": [],
                "key_metrics": [],
                "source_cards": [],
                "as_of": "2026-08-04T00:00:00Z",
                "dataset_version": "record:test",
            },
            "unexpected": "drop me",
        }
    )
    encoded = json.dumps(sanitized, ensure_ascii=False)
    assert set(sanitized) == {"case_id", "status", "model", "usage", "actual_usd", "answer"}
    assert set(sanitized["usage"]) == {"input_tokens", "output_tokens", "cache_hit_input_tokens", "cache_miss_input_tokens"}
    assert "owner@example.com" not in encoded
    assert "012345678901" not in encoded
    assert len(encoded.encode("utf-8")) < 64_000

    malformed = {
        "case_id": "case-2",
        "status": "completed",
        "model": "deepseek-test",
        "answer": {
            "answered": False,
            "depth": "standard",
            "verdict": "khong_du_du_lieu",
            "direct_answer": "Không đủ dữ liệu.",
            "claims": [{"text": "Không đủ dữ liệu.", "evidence_ids": [], "nested": {"secret": "x"}}],
            "as_of": "2026-08-04T00:00:00Z",
            "dataset_version": "record:test",
        },
    }
    with pytest.raises(RecordingGuardError, match="typed envelope"):
        sanitize_record(malformed)


@pytest.mark.parametrize(
    ("url", "valid"),
    [
        ("postgresql://radar:test@127.0.0.1:15432/radar_bds_test", True),
        ("postgresql+psycopg://radar:test@127.0.0.1:15432/radar_bds_test", True),
        ("postgresql://radar:test@127.0.0.1:15432/radar_bds", False),
        ("postgresql://radar:test@prod.example/radar_bds_test", False),
    ],
)
def test_db_backed_evaluation_guard_accepts_only_exact_local_test_database(url, valid):
    if valid:
        assert verify_test_database_url(url) == "radar_bds_test"
    else:
        with pytest.raises(ValueError, match="radar_bds_test"):
            verify_test_database_url(url)


def test_deterministic_cli_writes_utf8_report_and_exits_nonzero_on_open_privacy_gate(tmp_path):
    output = tmp_path / "golden-report.json"
    result = subprocess.run(
        [
            sys.executable,
            "-X",
            "utf8",
            str(SCRIPT_PATH),
            "--cases",
            str(CASES_PATH),
            "--mode",
            "deterministic",
            "--output",
            str(output),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONUTF8": "1"},
        timeout=30,
    )
    assert result.returncode == 2
    assert "privacy_pass_rate" in result.stderr
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["case_count"] >= 120
    assert report["release_gate_passed"] is False
    assert report["metrics"]["privacy_pass_rate"] < 1.0
    assert "Ngân sách" not in output.read_text(encoding="utf-8")


def test_record_provider_cli_refuses_missing_confirmation_without_network(tmp_path):
    missing_cases = tmp_path / "must-not-load-corpus.json"
    result = subprocess.run(
        [
            sys.executable,
            "-X",
            "utf8",
            str(SCRIPT_PATH),
            "--cases",
            str(missing_cases),
            "--record-provider",
            "--output",
            str(ROOT / "reports" / "must-not-exist.json"),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONUTF8": "1", "DEEPSEEK_API_KEY": ""},
        timeout=5,
    )
    assert result.returncode == 2
    assert "--confirm-live-cost" in (result.stderr + result.stdout)
    assert "Traceback" not in (result.stderr + result.stdout)
    assert not (ROOT / "reports" / "must-not-exist.json").exists()
