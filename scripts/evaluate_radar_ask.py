"""Versioned, deterministic release evaluation for Hỏi Radar BDS.

The default mode is deliberately hermetic: route decisions, typed tool
dispatch, evidence validation, and answer validation run against checked-in
fixtures only. Live DeepSeek recording is a separate, explicit-cost path and
its sanitized output is never used to rewrite golden expectations.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from collections import Counter
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from unittest.mock import patch
from urllib.parse import urlparse

from flask import Flask
from pydantic import ValidationError

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.radar_ask.config import RadarAskSettings
from services.radar_ask.contracts import (
    AnswerEnvelope,
    AskContext,
    AskDepth,
    AskQuestionRequest,
    EvidenceBundle,
    PageContext,
    ProviderMessage,
    ProviderResponse,
    ProviderUsage,
)
from services.radar_ask.limits import calculate_provider_cost
from services.radar_ask.planner import DeepSeekTypedPlanner
from services.radar_ask.provider import DeepSeekProvider
from services.radar_ask.registry import (
    DEFAULT_TOOL_REGISTRY,
    ToolContext,
    ToolRegistration,
    ToolRegistry,
    ToolRegistryError,
    execute_tool,
)
from services.radar_ask.routing import RoutingError, route_question
from services.radar_ask.validator import AnswerValidationError, validate_answer
from routes import radar_ask_api as radar_ask_api_route


SCHEMA_VERSION = 1
MAX_CORPUS_BYTES = 1_500_000
MAX_REPORT_BYTES = 131_072
MAX_RECORDING_BYTES = 2_000_000
EVALUATION_NOW = datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc)

REQUIRED_CATEGORIES = frozenset(
    {
        "approved_examples",
        "budget_to_ward",
        "ward_comparison",
        "listing_valuation_explanation",
        "exact_road_market_price",
        "deals_under_ppm2",
        "price_drop_areas",
        "official_land_price_purpose",
        "ambiguous_entity_clarification",
        "insufficient_data",
        "stale_conflicting_evidence",
        "tier_mos_behavior",
        "adversarial_citation_numeric",
        "privacy_semantics",
        "auth_policy",
    }
)

RELEASE_THRESHOLDS = {
    "routing_accuracy": Decimal("0.95"),
    "tool_selection_accuracy": Decimal("0.95"),
    "numeric_grounding_rate": Decimal("1"),
    "citation_validity_rate": Decimal("1"),
    "privacy_pass_rate": Decimal("1"),
    "auth_policy_pass_rate": Decimal("1"),
    "unsupported_claim_rate": Decimal("0"),
}

_PHONE_RE = re.compile(r"(?<!\d)(?:\+?84|0)(?:[ .-]?\d){9,10}(?!\d)")
_URL_RE = re.compile(r"\b(?:https?|ftp)://[^\s<>'\"]+", re.I)
_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
_BEARER_RE = re.compile(r"\bBearer\s+[A-Za-z0-9._~+\-/]+=*", re.I)
_ACCOUNT_TOKEN_RE = re.compile(r"\bacct-[a-z0-9-]{3,}\b", re.I)
_COMMON_PERSON_NAME_RE = re.compile(
    r"\b(?:Nguyễn|Trần|Lê|Phạm|Hoàng|Huỳnh|Phan|Vũ|Võ|Đặng|Bùi|Đỗ|Hồ|Ngô|Dương|Lý)"
    r"(?:\s+[A-Za-zÀ-ỹĐđ]{1,30}){1,3}\b",
    re.I,
)
_LABELED_IDENTIFIER_RE = re.compile(
    r"\b(?:cccd|cmnd|mã số thuế|ma so thue|mst|số tài khoản|so tai khoan|"
    r"tài khoản|tai khoan|mã thửa|ma thua|số thửa|so thua)\s*[:#-]?\s*"
    r"[A-Za-z0-9.-]{4,}\b",
    re.I,
)
_LABELED_PERSON_RE = re.compile(
    r"\b(chủ đất|môi giới|họ tên|người bán|tên)\s+"
    r"([A-ZĐ][a-zà-ỹ]+(?:\s+[A-ZĐ][a-zà-ỹ]+){1,4})\b"
)
_FORBIDDEN_RECORD_KEYS = frozenset(
    {
        "prompt",
        "messages",
        "question",
        "raw_evidence",
        "evidence",
        "phone",
        "url",
        "href",
        "account_id",
        "user_id",
        "session_id",
        "run_id",
    }
)
_ALLOWED_RECORD_KEYS = (
    "case_id",
    "status",
    "model",
    "usage",
    "actual_usd",
    "answer",
)
_ALLOWED_USAGE_KEYS = (
    "input_tokens",
    "output_tokens",
    "cache_hit_input_tokens",
    "cache_miss_input_tokens",
)


class CorpusError(ValueError):
    """Golden fixture violates the bounded evaluation contract."""


class ReleaseGateError(RuntimeError):
    """One or more deterministic release thresholds failed."""


class RecordingGuardError(RuntimeError):
    """Live provider recording was requested without every safety guard."""


def _bounded_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _validate_case_shape(case: Mapping[str, Any], *, index: int) -> None:
    required = {
        "id",
        "category",
        "question",
        "tier",
        "authenticated",
        "page_context",
        "expected",
        "observed",
    }
    if set(case) != required:
        raise CorpusError(f"case {index} has an invalid top-level shape")
    if not isinstance(case["id"], str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,79}", case["id"]):
        raise CorpusError(f"case {index} has an invalid id")
    if case["category"] not in REQUIRED_CATEGORIES:
        raise CorpusError(f"case {case['id']} has an unknown category")
    if not isinstance(case["question"], str) or not 3 <= len(case["question"]) <= 2_000:
        raise CorpusError(f"case {case['id']} has an invalid question")
    if case["tier"] not in {"free", "vip", "admin"}:
        raise CorpusError(f"case {case['id']} has an invalid tier")
    if not isinstance(case["authenticated"], bool):
        raise CorpusError(f"case {case['id']} has an invalid auth fixture")
    if not isinstance(case["page_context"], Mapping):
        raise CorpusError(f"case {case['id']} has invalid page context")
    expected = case["expected"]
    observed = case["observed"]
    if not isinstance(expected, Mapping) or not isinstance(observed, Mapping):
        raise CorpusError(f"case {case['id']} lacks independent expected/observed data")
    expected_required = {
        "depth",
        "question_type",
        "tools",
        "required_evidence_kinds",
        "forbidden_evidence_kinds",
        "answer_class",
        "verdict",
        "numeric_value",
        "numeric_tolerance",
        "validation_outcome",
    }
    if not expected_required <= set(expected):
        raise CorpusError(f"case {case['id']} has incomplete expected truth")
    if any(key in expected for key in ("answer", "evidence", "planner_output")):
        raise CorpusError(f"case {case['id']} mixes expected truth with observations")
    if set(observed) - {"planner_output_id", "evidence_by_tool", "answer_candidate_id"}:
        raise CorpusError(f"case {case['id']} has unknown observed fixture fields")
    if expected["validation_outcome"] not in {
        "accept",
        "reject_numeric",
        "reject_citation",
        "reject_privacy",
        "reject_unsupported",
    }:
        raise CorpusError(f"case {case['id']} has invalid validation outcome")


def load_corpus(path: str | Path) -> dict[str, Any]:
    fixture_path = Path(path)
    raw = fixture_path.read_bytes()
    if len(raw) > MAX_CORPUS_BYTES:
        raise CorpusError("golden corpus exceeds the bounded size")
    try:
        corpus = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise CorpusError("golden corpus must be valid UTF-8 JSON") from exc
    if not isinstance(corpus, dict) or corpus.get("schema_version") != SCHEMA_VERSION:
        raise CorpusError("golden corpus schema version is unsupported")
    if not re.fullmatch(r"radar-ask-golden-v\d+", str(corpus.get("dataset_version", ""))):
        raise CorpusError("golden corpus dataset version is invalid")
    fixtures = corpus.get("fixtures")
    cases = corpus.get("cases")
    if not isinstance(fixtures, dict) or set(fixtures) != {
        "planner_outputs",
        "evidence_bundles",
        "answer_candidates",
    }:
        raise CorpusError("golden fixture catalogs are invalid")
    if not isinstance(cases, list) or not 120 <= len(cases) <= 250:
        raise CorpusError("golden corpus must contain between 120 and 250 cases")
    ids: set[str] = set()
    questions: set[str] = set()
    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            raise CorpusError(f"case {index} must be an object")
        _validate_case_shape(case, index=index)
        if case["id"] in ids or case["question"] in questions:
            raise CorpusError("golden case ids and questions must be unique")
        ids.add(case["id"])
        questions.add(case["question"])
    missing = REQUIRED_CATEGORIES - {case["category"] for case in cases}
    if missing:
        raise CorpusError(f"golden corpus is missing categories: {sorted(missing)}")
    return corpus


def _fixture_registry(
    corpus: Mapping[str, Any],
    case: Mapping[str, Any],
) -> ToolRegistry:
    catalogs = corpus["fixtures"]["evidence_bundles"]
    evidence_by_tool = case["observed"].get("evidence_by_tool", {})

    def registration_for(name: str, original: ToolRegistration) -> ToolRegistration:
        def handler(*, args, context):
            del args, context
            fixture_id = evidence_by_tool.get(name)
            if fixture_id is None:
                return EvidenceBundle(
                    question_snapshot=f"fixture:{case['id']}",
                    retrieval_quality="insufficient",
                    missing_requirements=["fixture_evidence_not_configured"],
                )
            try:
                raw_bundle = catalogs[fixture_id]
            except KeyError as exc:
                raise CorpusError(
                    f"case {case['id']} references unknown evidence fixture {fixture_id}"
                ) from exc
            return EvidenceBundle.model_validate(raw_bundle)

        return ToolRegistration(
            name=name,
            description=original.description,
            args_model=original.args_model,
            handler=handler,
        )

    return ToolRegistry(
        {
            name: registration_for(name, original)
            for name, original in DEFAULT_TOOL_REGISTRY.registrations.items()
        }
    )


def _planner_for_case(corpus: Mapping[str, Any], case: Mapping[str, Any]):
    planner_id = case["observed"].get("planner_output_id")
    if not planner_id:
        return None
    try:
        output = copy.deepcopy(corpus["fixtures"]["planner_outputs"][planner_id])
    except KeyError as exc:
        raise CorpusError(
            f"case {case['id']} references unknown planner fixture {planner_id}"
        ) from exc

    def planner(*, request, context, allowed_tools):
        del request, context, allowed_tools
        return copy.deepcopy(output)

    return planner


class _CapturePlannerProvider:
    def __init__(self, planner_output: Mapping[str, Any]):
        self.planner_output = copy.deepcopy(planner_output)
        self.requests: list[Any] = []

    def complete(self, request):
        self.requests.append(request)
        return ProviderResponse(
            json_value=copy.deepcopy(self.planner_output),
            usage=ProviderUsage(),
        )

    def complete_until(self, request, *, deadline):
        if deadline <= 0:
            raise ValueError("planner capture deadline must be positive")
        return self.complete(request)


def capture_planner_provider_payload(
    corpus: Mapping[str, Any],
    case: Mapping[str, Any],
) -> str:
    """Capture the real typed planner user message without network/provider I/O."""
    planner_id = case["observed"].get("planner_output_id")
    if not planner_id:
        raise CorpusError(f"case {case['id']} has no planner observation to capture")
    try:
        planner_output = corpus["fixtures"]["planner_outputs"][planner_id]
    except KeyError as exc:
        raise CorpusError(f"case {case['id']} references an unknown planner fixture") from exc
    provider = _CapturePlannerProvider(planner_output)
    settings = replace(
        RadarAskSettings.from_env(),
        enabled=False,
        database_url="",
        deepseek_api_key="",
        router_model="deepseek-capture-fixture",
    )
    registry = _fixture_registry(corpus, case)
    planner = DeepSeekTypedPlanner(
        settings=settings,
        provider=provider,
        registry=registry,
        monotonic_fn=lambda: 1_000.0,
    )
    context = AskContext(
        user_id=99_999,
        tier=case["tier"],
        page=PageContext.model_validate(case["page_context"]),
    )
    planner(
        request=AskQuestionRequest(
            question=case["question"],
            page_context=context.page,
        ),
        context=context,
        allowed_tools=tuple(registry.registrations),
        deadline=1_030.0,
    )
    if len(provider.requests) != 1:
        raise CorpusError("typed planner capture did not issue exactly one fake-provider request")
    user_messages = [
        message.content or ""
        for message in provider.requests[0].messages
        if message.role == "user"
    ]
    if len(user_messages) != 1:
        raise CorpusError("typed planner capture has an invalid user-message shape")
    return user_messages[0]


def _answer_for_case(corpus: Mapping[str, Any], case: Mapping[str, Any]) -> Mapping[str, Any]:
    answer_id = case["observed"].get("answer_candidate_id")
    if not answer_id:
        raise CorpusError(f"case {case['id']} has no answer candidate")
    try:
        return copy.deepcopy(corpus["fixtures"]["answer_candidates"][answer_id])
    except KeyError as exc:
        raise CorpusError(
            f"case {case['id']} references unknown answer fixture {answer_id}"
        ) from exc


def _numbers(value: Any) -> list[Decimal]:
    found: list[Decimal] = []
    if isinstance(value, bool) or value is None:
        return found
    if isinstance(value, (int, float, Decimal)):
        try:
            parsed = Decimal(str(value))
        except InvalidOperation:
            return found
        if parsed.is_finite():
            found.append(parsed)
        return found
    if isinstance(value, Mapping):
        for nested in value.values():
            found.extend(_numbers(nested))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for nested in value:
            found.extend(_numbers(nested))
    return found


def _answer_references(answer: Mapping[str, Any]) -> tuple[list[str], bool]:
    references: list[str] = []
    unsupported = False
    for claim in answer.get("claims", []):
        ids = claim.get("evidence_ids", []) if isinstance(claim, Mapping) else []
        if isinstance(claim, Mapping) and claim.get("material", True) and not ids:
            unsupported = True
        references.extend(str(value) for value in ids)
    for metric in answer.get("key_metrics", []):
        ids = metric.get("evidence_ids", []) if isinstance(metric, Mapping) else []
        references.extend(str(value) for value in ids)
    return references, unsupported


def _redact_text(value: str) -> str:
    text = value
    for pattern in (
        _URL_RE,
        _EMAIL_RE,
        _PHONE_RE,
        _BEARER_RE,
        _LABELED_IDENTIFIER_RE,
        _ACCOUNT_TOKEN_RE,
        _COMMON_PERSON_NAME_RE,
    ):
        text = pattern.sub("[đã ẩn]", text)
    text = _LABELED_PERSON_RE.sub(lambda match: f"{match.group(1)} [đã ẩn]", text)
    return text


def _redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return _redact_text(value)
    if isinstance(value, Mapping):
        return {
            str(key): _redact_value(nested)
            for key, nested in value.items()
            if str(key).lower() not in _FORBIDDEN_RECORD_KEYS
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_redact_value(nested) for nested in value]
    return value


def _has_sensitive_value(value: Any) -> bool:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return any(
        pattern.search(encoded)
        for pattern in (
            _PHONE_RE,
            _URL_RE,
            _EMAIL_RE,
            _BEARER_RE,
            _LABELED_IDENTIFIER_RE,
        )
    ) or bool(_LABELED_PERSON_RE.search(encoded))


def _classify_validation_error(exc: AnswerValidationError | None) -> str | None:
    if exc is None:
        return None
    message = str(exc).lower()
    if "numeric" in message or "does not match cited evidence" in message:
        return "reject_numeric"
    if "redacted source data" in message:
        return "reject_privacy"
    if "material claims require evidence" in message:
        return "reject_unsupported"
    if "evidence" in message or "citation" in message or "source" in message:
        return "reject_citation"
    return "reject_other"


def _ratio(passed: int, total: int) -> float:
    return round(passed / total, 6) if total else 1.0


def _observe_auth_gate(case: Mapping[str, Any], *, user_id: int) -> tuple[tuple[Any, ...], bool]:
    """Exercise the real HTTP authorization gate with fixture-owned identity inputs."""
    authenticated = bool(case["authenticated"])
    tier = str(case["tier"])
    expected = (
        ("owner", user_id, tier)
        if authenticated
        else ("error", 401, "login_required")
    )
    app = Flask("radar-ask-golden-auth")
    with app.test_request_context("/api/radar-ask/evaluation", method="POST"):
        with (
            patch.object(radar_ask_api_route, "feature_enabled", return_value=True),
            patch.object(
                radar_ask_api_route,
                "current_user",
                return_value={"id": user_id} if authenticated else None,
            ),
            patch.object(
                radar_ask_api_route,
                "current_tier",
                return_value=tier if authenticated else "guest",
            ),
            patch.object(radar_ask_api_route, "tier_allowed", return_value=True),
        ):
            observed = radar_ask_api_route._gate()
    if isinstance(observed, tuple):
        actual = ("owner", observed[0], observed[1])
        allowed = True
    else:
        body = observed.get_json(silent=True) or {}
        error = body.get("error") if isinstance(body, Mapping) else {}
        code = error.get("code") if isinstance(error, Mapping) else None
        actual = ("error", observed.status_code, code)
        allowed = False
    return (expected == actual, allowed)


def evaluate_corpus(corpus: Mapping[str, Any], *, mode: str = "deterministic") -> dict[str, Any]:
    if mode != "deterministic":
        raise ValueError("default evaluation supports deterministic mode only")
    counters: Counter[str] = Counter()
    failures: list[dict[str, str]] = []

    for case in corpus["cases"]:
        expected = case["expected"]
        counters["cases"] += 1
        counters["routing_total"] += 1
        counters["tools_total"] += 1
        counters["privacy_total"] += 1
        counters["auth_total"] += 1

        auth_ok, gate_allowed = _observe_auth_gate(
            case,
            user_id=10_000 + counters["cases"],
        )
        if auth_ok:
            counters["auth_pass"] += 1
        else:
            failures.append({"case_id": case["id"], "dimension": "auth:http_gate"})

        if not gate_allowed:
            routing_ok = expected["question_type"] == "auth_required" and expected["depth"] == "denied"
            tools_ok = expected["tools"] == []
            counters["refusal_total"] += 1
            if routing_ok:
                counters["routing_pass"] += 1
            if tools_ok:
                counters["tools_pass"] += 1
            if auth_ok and expected["answer_class"] == "denied":
                counters["refusal_pass"] += 1
            counters["privacy_pass"] += 1
            continue

        context = AskContext(
            user_id=10_000 + counters["cases"],
            tier=case["tier"],
            page=PageContext.model_validate(case["page_context"]),
        )
        request = AskQuestionRequest(
            question=case["question"],
            page_context=context.page,
        )
        registry = _fixture_registry(corpus, case)
        try:
            decision = route_question(
                request,
                context,
                planner=_planner_for_case(corpus, case),
                registry=registry,
            )
        except (RoutingError, ToolRegistryError, ValidationError, ValueError, TypeError):
            failures.append({"case_id": case["id"], "dimension": "routing"})
            failures.append({"case_id": case["id"], "dimension": "tools"})
            counters["privacy_pass"] += 1
            continue
        actual_tools = [call.name for call in decision.tool_calls]
        routing_ok = (
            decision.depth.value == expected["depth"]
            and decision.question_type == expected["question_type"]
        )
        tools_ok = actual_tools == expected["tools"]
        if routing_ok:
            counters["routing_pass"] += 1
        else:
            failures.append(
                {
                    "case_id": case["id"],
                    "dimension": f"routing:{decision.question_type}:{decision.depth.value}",
                }
            )
        if tools_ok:
            counters["tools_pass"] += 1
        else:
            failures.append(
                {"case_id": case["id"], "dimension": "tools:" + ",".join(actual_tools)}
            )

        # Keep downstream dimensions independent: a router/tool miss is
        # counted only in those gates and cannot manufacture a citation or
        # numeric failure by retrieving the wrong evidence set.
        if not routing_ok or not tools_ok:
            answer = _answer_for_case(corpus, case)
            if not _has_sensitive_value(answer):
                counters["privacy_pass"] += 1
            else:
                failures.append({"case_id": case["id"], "dimension": "privacy"})
            continue

        bundles: list[EvidenceBundle] = []
        for call in decision.tool_calls:
            bundles.append(execute_tool(call, ToolContext(ask=context), registry=registry))
        evidence_items = [item for bundle in bundles for item in bundle.items]
        evidence_ids = {item.evidence_id for item in evidence_items}
        evidence_kinds = {item.source_kind.value for item in evidence_items}
        required_kinds = set(expected["required_evidence_kinds"])
        forbidden_kinds = set(expected["forbidden_evidence_kinds"])
        evidence_policy_ok = required_kinds <= evidence_kinds and not (forbidden_kinds & evidence_kinds)
        counters["evidence_total"] += 1
        if evidence_policy_ok:
            counters["evidence_pass"] += 1

        answer = _answer_for_case(corpus, case)
        references, unsupported = _answer_references(answer)
        citation_observed_ok = (
            not unsupported
            and all(reference in evidence_ids for reference in references)
            and evidence_policy_ok
        )
        validation_error: AnswerValidationError | None = None
        validated: AnswerEnvelope | None = None
        try:
            validated = validate_answer(
                answer,
                bundles,
                tier=case["tier"],
                expected_depth=decision.depth,
                now=EVALUATION_NOW,
                required_freshness_hours=decision.required_freshness_hours,
            )
        except AnswerValidationError as exc:
            validation_error = exc
        observed_outcome = _classify_validation_error(validation_error) or "accept"
        expected_outcome = expected["validation_outcome"]
        validation_ok = observed_outcome == expected_outcome
        counters["validation_total"] += 1
        if validation_ok:
            counters["validation_pass"] += 1
        else:
            failures.append(
                {
                    "case_id": case["id"],
                    "dimension": (
                        f"validation:{observed_outcome}:expected:{expected_outcome}:"
                        f"{str(validation_error or 'accepted')[:96]}"
                    ),
                }
            )

        answer_class_ok = (
            bool(answer.get("answered")) == (expected["answer_class"] == "answered")
            and answer.get("verdict") == expected["verdict"]
        )
        counters["answer_total"] += 1
        if answer_class_ok:
            counters["answer_pass"] += 1
        if expected["answer_class"] == "insufficient":
            counters["refusal_total"] += 1
            if answer_class_ok and validation_ok:
                counters["refusal_pass"] += 1
            else:
                failures.append({"case_id": case["id"], "dimension": "refusal"})

        if expected_outcome == "reject_citation":
            citation_ok = not citation_observed_ok and observed_outcome == "reject_citation"
            counters["citation_total"] += 1
        elif expected_outcome in {"accept", "reject_numeric"}:
            citation_ok = citation_observed_ok
            counters["citation_total"] += 1
        else:
            citation_ok = True
        if expected_outcome in {"accept", "reject_numeric", "reject_citation"}:
            if citation_ok:
                counters["citation_pass"] += 1
            else:
                failures.append({"case_id": case["id"], "dimension": "citation"})

        expected_number = expected.get("numeric_value")
        tolerance = expected.get("numeric_tolerance")
        if tolerance is not None or expected_outcome == "reject_numeric":
            counters["numeric_total"] += 1
            if expected_outcome == "reject_numeric":
                numeric_ok = observed_outcome == "reject_numeric"
            else:
                candidate_numbers = [
                    Decimal(str(claim["numeric_value"]))
                    for claim in answer.get("claims", [])
                    if isinstance(claim, Mapping) and claim.get("numeric_value") is not None
                ]
                target = Decimal(str(expected_number))
                allowed = Decimal(str(tolerance))
                numeric_ok = (
                    validated is not None
                    and any(abs(value - target) <= allowed for value in candidate_numbers)
                    and any(
                        abs(value - target) <= allowed
                        for bundle in bundles
                        for item in bundle.items
                        for value in _numbers(item.value)
                    )
                )
            if numeric_ok:
                counters["numeric_pass"] += 1
            else:
                failures.append({"case_id": case["id"], "dimension": "numeric"})

        provider_view = [bundle.model_dump(mode="json") for bundle in bundles]
        unsafe = _has_sensitive_value(answer) or _has_sensitive_value(provider_view)
        planner_payload_ok = True
        private_tokens = [str(value) for value in expected.get("planner_private_tokens", [])]
        required_semantics = [
            str(value) for value in expected.get("planner_required_semantics", [])
        ]
        if private_tokens or required_semantics:
            outbound = capture_planner_provider_payload(corpus, case)
            folded_outbound = outbound.casefold()
            leaked_private = any(
                token.casefold() in folded_outbound for token in private_tokens
            )
            missing_semantics = any(
                token.casefold() not in folded_outbound for token in required_semantics
            )
            expected_person_redaction_missing = bool(private_tokens) and (
                "[redacted_person]" not in folded_outbound
            )
            semantic_over_redaction = bool(required_semantics) and (
                "[redacted_person]" in folded_outbound
            )
            planner_payload_ok = not (
                leaked_private
                or missing_semantics
                or expected_person_redaction_missing
                or semantic_over_redaction
            )
        if expected_outcome == "reject_privacy":
            privacy_ok = unsafe and observed_outcome == "reject_privacy" and planner_payload_ok
        else:
            privacy_ok = not unsafe and planner_payload_ok
        if privacy_ok:
            counters["privacy_pass"] += 1
        else:
            dimension = "privacy:planner_payload" if not planner_payload_ok else "privacy"
            failures.append({"case_id": case["id"], "dimension": dimension})

        mos_ok = True
        for call in decision.tool_calls:
            if call.name != "search_deals":
                continue
            mos = Decimal(str(call.arguments.get("mos_min_pct", 15)))
            floor = Decimal("15") if case["tier"] == "free" else Decimal("10")
            if mos < floor:
                mos_ok = False
        counters["tier_policy_total"] += 1
        if mos_ok:
            counters["tier_policy_pass"] += 1
        else:
            failures.append({"case_id": case["id"], "dimension": "tier_policy"})

        if unsupported and validation_error is None:
            counters["unsupported_accepted"] += 1

    metrics = {
        "routing_accuracy": _ratio(counters["routing_pass"], counters["routing_total"]),
        "tool_selection_accuracy": _ratio(counters["tools_pass"], counters["tools_total"]),
        "numeric_grounding_rate": _ratio(counters["numeric_pass"], counters["numeric_total"]),
        "citation_validity_rate": _ratio(counters["citation_pass"], counters["citation_total"]),
        "privacy_pass_rate": _ratio(counters["privacy_pass"], counters["privacy_total"]),
        "auth_policy_pass_rate": _ratio(counters["auth_pass"], counters["auth_total"]),
        "unsupported_claim_rate": _ratio(counters["unsupported_accepted"], counters["cases"]),
        "evidence_policy_rate": _ratio(counters["evidence_pass"], counters["evidence_total"]),
        "answer_class_accuracy": _ratio(counters["answer_pass"], counters["answer_total"]),
        "refusal_accuracy": _ratio(counters["refusal_pass"], counters["refusal_total"]),
        "validation_expectation_rate": _ratio(counters["validation_pass"], counters["validation_total"]),
        "tier_policy_rate": _ratio(counters["tier_policy_pass"], counters["tier_policy_total"]),
    }
    report = {
        "schema_version": SCHEMA_VERSION,
        "dataset_version": corpus["dataset_version"],
        "mode": mode,
        "case_count": counters["cases"],
        "category_counts": dict(sorted(Counter(case["category"] for case in corpus["cases"]).items())),
        "metrics": metrics,
        "denominators": {
            "routing": counters["routing_total"],
            "tools": counters["tools_total"],
            "numeric": counters["numeric_total"],
            "citation": counters["citation_total"],
            "privacy": counters["privacy_total"],
            "auth": counters["auth_total"],
        },
        "failures": failures[:250],
        "network_calls": 0,
        "database_calls": 0,
    }
    try:
        assert_release_gates(report)
    except ReleaseGateError:
        report["release_gate_passed"] = False
    else:
        report["release_gate_passed"] = True
    if len(_bounded_json_bytes(report)) > MAX_REPORT_BYTES:
        raise CorpusError("evaluation report exceeds the bounded size")
    return report


def assert_release_gates(report: Mapping[str, Any]) -> None:
    metrics = report.get("metrics", {})
    failed: list[str] = []
    for name, threshold in RELEASE_THRESHOLDS.items():
        try:
            actual = Decimal(str(metrics[name]))
        except (KeyError, InvalidOperation, TypeError, ValueError):
            failed.append(f"{name}=missing")
            continue
        if name == "unsupported_claim_rate":
            if actual != threshold:
                failed.append(f"{name}={actual}")
        elif actual < threshold:
            failed.append(f"{name}={actual}")
    if failed:
        raise ReleaseGateError("release thresholds failed: " + ", ".join(failed))


def verify_test_database_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"postgres", "postgresql", "postgresql+psycopg"}:
        raise ValueError("DB-backed evaluation requires PostgreSQL radar_bds_test")
    database = parsed.path.lstrip("/")
    if database != "radar_bds_test" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("DB-backed evaluation requires exact local radar_bds_test")
    return database


def validate_record_output_path(path: str | Path, *, repo_root: str | Path) -> Path:
    root = Path(repo_root).resolve()
    output = Path(path).resolve()
    reports = (root / "reports").resolve()
    golden = (root / "tests" / "fixtures" / "radar_ask" / "golden_questions.json").resolve()
    if output == golden or "golden" in output.name.lower():
        raise RecordingGuardError("provider recordings must never overwrite golden truth")
    try:
        output.relative_to(reports)
    except ValueError as exc:
        raise RecordingGuardError("provider recordings must use an explicit ignored reports/ path") from exc
    if output == reports or output.suffix.lower() != ".json":
        raise RecordingGuardError("provider recording output must be a JSON file under reports/")
    return output


def sanitize_record(raw: Mapping[str, Any]) -> dict[str, Any]:
    answer_raw = raw.get("answer")
    answer: dict[str, Any] | None = None
    if isinstance(answer_raw, Mapping):
        try:
            typed = AnswerEnvelope.model_validate(answer_raw)
        except ValidationError as exc:
            raise RecordingGuardError("provider recording answer is not a typed envelope") from exc
        typed_answer = typed.model_dump(mode="json")
        evidence_aliases: dict[str, str] = {}
        source_aliases: dict[str, str] = {}

        def evidence_alias(value: object) -> str:
            key = str(value)
            if key not in evidence_aliases:
                evidence_aliases[key] = f"evidence-{len(evidence_aliases) + 1:03d}"
            return evidence_aliases[key]

        def source_alias(value: object) -> str:
            key = str(value)
            if key not in source_aliases:
                source_aliases[key] = f"source-{len(source_aliases) + 1:03d}"
            return source_aliases[key]

        answer = {
            "answered": typed_answer["answered"],
            "depth": typed_answer["depth"],
            "verdict": typed_answer["verdict"],
            "direct_answer": "[provider text removed]",
            "claims": [
                {
                    "text": "[provider claim removed]",
                    "evidence_ids": [evidence_alias(value) for value in claim["evidence_ids"]],
                    "material": claim["material"],
                    "numeric_value": claim["numeric_value"],
                    "unit": "[unit removed]" if claim["unit"] is not None else None,
                }
                for claim in typed_answer["claims"]
            ],
            "key_metrics": [
                {
                    "label": "[provider metric removed]",
                    "value": "[provider value removed]",
                    "unit": "[unit removed]" if metric["unit"] is not None else None,
                    "evidence_ids": [
                        evidence_alias(value) for value in metric["evidence_ids"]
                    ],
                }
                for metric in typed_answer["key_metrics"]
            ],
            "favorable_thesis": (
                "[provider thesis removed]"
                if typed_answer["favorable_thesis"] is not None
                else None
            ),
            "counter_thesis": (
                "[provider thesis removed]"
                if typed_answer["counter_thesis"] is not None
                else None
            ),
            "risks": ["[provider risk removed]" for _ in typed_answer["risks"]],
            "confidence": typed_answer["confidence"],
            "confidence_reasons": [
                "[provider reason removed]" for _ in typed_answer["confidence_reasons"]
            ],
            "next_verification_steps": [
                "[provider step removed]" for _ in typed_answer["next_verification_steps"]
            ],
            "source_cards": [
                {
                    "evidence_id": evidence_alias(card["evidence_id"]),
                    "title": "[provider source removed]",
                    "source_kind": card["source_kind"],
                    "source_ref": source_alias(card["source_ref"]),
                    "as_of": card["as_of"],
                    "href": None,
                }
                for card in typed_answer["source_cards"]
            ],
            "suggested_followups": [
                "[provider followup removed]" for _ in typed_answer["suggested_followups"]
            ],
            "as_of": typed_answer["as_of"],
            "dataset_version": "recorded-dataset",
        }
        try:
            answer = AnswerEnvelope.model_validate(answer).model_dump(mode="json")
        except ValidationError as exc:
            raise RecordingGuardError("sanitized provider answer is not a typed envelope") from exc
    usage_raw = raw.get("usage") if isinstance(raw.get("usage"), Mapping) else {}
    usage = {
        key: max(0, int(usage_raw.get(key, 0) or 0))
        for key in _ALLOWED_USAGE_KEYS
    }
    sanitized = {
        "case_id": _redact_text(str(raw.get("case_id", "unknown")))[:80],
        "status": _redact_text(str(raw.get("status", "unknown")))[:40],
        "model": _redact_text(str(raw.get("model", "unknown")))[:120],
        "usage": usage,
        "actual_usd": _redact_text(str(raw.get("actual_usd", "0")))[:32],
        "answer": answer,
    }
    if len(_bounded_json_bytes(sanitized)) > 64_000:
        raise RecordingGuardError("one sanitized provider record exceeds 64 KB")
    return {key: sanitized[key] for key in _ALLOWED_RECORD_KEYS}


def record_provider_cases(
    corpus: Mapping[str, Any],
    *,
    output_path: str | Path,
    confirm_live_cost: bool,
    provider_case_runner: Callable[[Mapping[str, Any], Mapping[str, Any]], Mapping[str, Any]],
    repo_root: str | Path,
    write_output: bool = True,
    case_limit: int | None = None,
) -> dict[str, Any]:
    output = validate_record_output_path(output_path, repo_root=repo_root)
    if not confirm_live_cost:
        raise RecordingGuardError("--record-provider requires --confirm-live-cost")
    selected = corpus["cases"][: case_limit if case_limit is not None else len(corpus["cases"])]
    records = [sanitize_record(provider_case_runner(case, corpus)) for case in selected]
    payload = {
        "schema_version": SCHEMA_VERSION,
        "dataset_version": corpus["dataset_version"],
        "recording_kind": "sanitized-provider-observation",
        "golden_truth_updated": False,
        "records": records,
    }
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if len(encoded.encode("utf-8")) > MAX_RECORDING_BYTES:
        raise RecordingGuardError("sanitized provider recording exceeds 2 MB")
    if write_output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(encoded, encoding="utf-8", newline="\n")
    return payload


def _live_provider_runner(settings: RadarAskSettings):
    if not settings.deepseek_api_key:
        raise RecordingGuardError("DEEPSEEK_API_KEY is required for provider recording")
    provider = DeepSeekProvider(settings=settings)

    def run(case: Mapping[str, Any], corpus: Mapping[str, Any]) -> Mapping[str, Any]:
        raw_evidence_ids = sorted(
            {
                item["evidence_id"]
                for fixture_id in case["observed"].get("evidence_by_tool", {}).values()
                for item in corpus["fixtures"]["evidence_bundles"][fixture_id].get("items", [])
            }
        )
        evidence_ids = [f"evidence-{index:03d}" for index, _ in enumerate(raw_evidence_ids, 1)]
        model = settings.free_model if case["tier"] == "free" else settings.smart_model
        safe_question = _redact_text(str(case["question"]))
        if _has_sensitive_value(safe_question):
            raise RecordingGuardError("provider recording question contains sensitive data")
        prompt = {
            "task": "Return one typed Radar Ask AnswerEnvelope JSON. Do not add phone numbers, URLs, names, or account identifiers.",
            "question": safe_question,
            "expected_depth": case["expected"]["depth"],
            "allowed_evidence_ids": evidence_ids,
            "answer_schema": AnswerEnvelope.model_json_schema(mode="validation"),
        }
        if len(_bounded_json_bytes(prompt)) > 48_000:
            raise RecordingGuardError("provider recording prompt exceeds 48 KB")
        response = provider.complete_json(
            model=model,
            messages=[
                ProviderMessage(
                    role="user",
                    content=json.dumps(prompt, ensure_ascii=False, separators=(",", ":")),
                )
            ],
            max_output_tokens=1_600,
            thinking_enabled=case["expected"]["depth"] == "deep" and case["tier"] in {"vip", "admin"},
        )
        answer = AnswerEnvelope.model_validate(response.json_value)
        return {
            "case_id": case["id"],
            "status": "completed",
            "model": model,
            "usage": response.usage.model_dump(mode="json"),
            "actual_usd": str(calculate_provider_cost(model, response.usage)),
            "answer": answer.model_dump(mode="json"),
        }

    return run


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", required=True, type=Path)
    parser.add_argument("--mode", choices=("deterministic",), default="deterministic")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--record-provider", action="store_true")
    parser.add_argument("--confirm-live-cost", action="store_true")
    parser.add_argument("--case-limit", type=int, default=None)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        corpus = load_corpus(args.cases)
        if args.record_provider:
            output = validate_record_output_path(args.output, repo_root=Path.cwd())
            if not args.confirm_live_cost:
                raise RecordingGuardError("--record-provider requires --confirm-live-cost")
            settings = RadarAskSettings.from_env()
            record_provider_cases(
                corpus,
                output_path=output,
                confirm_live_cost=True,
                provider_case_runner=_live_provider_runner(settings),
                repo_root=Path.cwd(),
                case_limit=args.case_limit,
            )
            print(json.dumps({"recorded": True, "output": str(output)}, ensure_ascii=False))
            return 0
        report = evaluate_corpus(corpus, mode=args.mode)
        _write_json(args.output, report)
        assert_release_gates(report)
        print(json.dumps(report["metrics"], ensure_ascii=False, sort_keys=True))
        return 0
    except (CorpusError, RecordingGuardError, ReleaseGateError, ValueError) as exc:
        print(f"Radar Ask evaluation failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
