from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from services.radar_ask.config import (
    REQUEST_DB_TOOL_MARGIN_SECONDS,
    REQUEST_OWNER_LEASE_SECONDS,
    REQUEST_PROVIDER_BUDGET_CAP_SECONDS,
    RadarAskSettings,
    request_provider_budget_seconds,
    resolve_model_policy,
)
from services.radar_ask.contracts import (
    AnswerClaim,
    AnswerEnvelope,
    AskDepth,
    AskQuestionRequest,
    AskVerdict,
    EvidenceBundle,
    EvidenceItem,
    ModelPolicy,
    PageContext,
    ProviderMessage,
    ProviderResponse,
    ProviderUsage,
    RouteDecision,
    RunStatus,
    SourceKind,
    SourceCard,
    ToolCall,
)


def test_question_normalizes_whitespace_and_rejects_blank_or_extra_input():
    request = AskQuestionRequest(question="  Giá   Phú Mỹ?  ")

    assert request.question == "Giá Phú Mỹ?"
    with pytest.raises(ValidationError):
        AskQuestionRequest(question="   ")
    with pytest.raises(ValidationError):
        AskQuestionRequest(question="Giá Phú Mỹ?", sql="SELECT 1")


def test_question_bounds_length_and_accepts_typed_session_and_depth():
    session_id = uuid4()

    request = AskQuestionRequest(
        question="Phân tích sâu lô đất này",
        session_id=session_id,
        requested_depth=AskDepth.DEEP,
    )

    assert request.session_id == session_id
    assert request.requested_depth is AskDepth.DEEP
    with pytest.raises(ValidationError):
        AskQuestionRequest(question="x" * 2_001)


def test_tool_call_rejects_unknown_fields_and_oversized_arguments():
    call = ToolCall(
        call_id="call-1",
        name="compare_areas",
        arguments={"wards": ["Phú Mỹ", "Định Hòa"]},
    )

    assert call.name == "compare_areas"
    with pytest.raises(ValidationError):
        ToolCall(call_id="call-2", name="sql", arguments={}, query="SELECT * FROM users")
    with pytest.raises(ValidationError):
        ToolCall(call_id="call-3", name="compare_areas", arguments={"payload": "x" * 8_193})


def test_page_context_rejects_oversized_filter_payload():
    with pytest.raises(ValidationError, match="active filters exceed"):
        PageContext(active_filters={"query": "x" * 8_193})


def test_evidence_contract_bounds_provenance_and_numeric_quality():
    item = EvidenceItem(
        evidence_id="ev_listing_123",
        source_kind=SourceKind.LISTING,
        source_ref="listing:123",
        value=20_000_000,
        unit="VND/m2",
        calculation_method="asking_price / area_m2",
        as_of=datetime(2026, 8, 4, tzinfo=timezone.utc),
        dataset_version="listings:7",
        sample_size=1,
        confidence=Decimal("0.90"),
        provenance={"listing_id": "123"},
        quality_flags=["asking_price"],
        min_tier="free",
    )

    assert item.value == 20_000_000
    assert item.confidence == Decimal("0.90")
    with pytest.raises(ValidationError):
        EvidenceItem(
            evidence_id="ev_bad",
            source_kind=SourceKind.MARKET_STAT,
            source_ref="market:bad",
            value=1,
            as_of=datetime.now(timezone.utc),
            dataset_version="signals:7",
            confidence=Decimal("1.01"),
        )


def test_evidence_bundle_and_route_decision_enforce_collection_caps():
    item = EvidenceItem(
        evidence_id="ev_1",
        source_kind=SourceKind.MARKET_STAT,
        source_ref="market:phu-my",
        value=18_000_000,
        unit="VND/m2",
        as_of=datetime(2026, 8, 4, tzinfo=timezone.utc),
        dataset_version="listings:7",
    )
    bundle = EvidenceBundle(question_snapshot="Giá Phú Mỹ?", items=[item])

    assert bundle.items == [item]
    with pytest.raises(ValidationError):
        EvidenceBundle(question_snapshot="x", items=[item] * 51)
    with pytest.raises(ValidationError):
        RouteDecision(
            depth=AskDepth.DEEP,
            question_type="market",
            tool_calls=[
                ToolCall(call_id=f"call-{index}", name="compare_areas", arguments={})
                for index in range(9)
            ],
            generated=True,
        )


def test_answer_and_usage_contracts_reject_untrusted_shape_and_negative_tokens():
    answer = AnswerEnvelope(
        answered=True,
        depth=AskDepth.STANDARD,
        verdict=AskVerdict.NEEDS_CHECKS,
        direct_answer="Phú Mỹ có giá chào thấp hơn trong mẫu hiện có.",
        claims=[AnswerClaim(text="Trung vị thấp hơn", evidence_ids=["ev_1"])],
        as_of=datetime(2026, 8, 4, tzinfo=timezone.utc),
        dataset_version="listings:7",
    )

    assert answer.verdict is AskVerdict.NEEDS_CHECKS
    assert answer.claims[0].evidence_ids == ["ev_1"]
    with pytest.raises(ValidationError):
        AnswerEnvelope(
            answered=True,
            depth=AskDepth.FAST,
            direct_answer="x",
            as_of=datetime.now(timezone.utc),
            dataset_version="listings:7",
            html="<script>alert(1)</script>",
        )
    with pytest.raises(ValidationError):
        ProviderUsage(input_tokens=-1)


def test_source_card_rejects_script_urls_but_allows_https_and_same_origin_paths():
    base = {
        "evidence_id": "ev_doc_1",
        "title": "Bảng giá đất TP.HCM",
        "source_kind": SourceKind.OFFICIAL_DOCUMENT,
        "source_ref": "knowledge:doc:1",
        "as_of": datetime(2026, 8, 4, tzinfo=timezone.utc),
    }

    assert SourceCard(**base, href="https://thuvienphapluat.vn/van-ban/1").href.startswith("https://")
    assert SourceCard(**base, href="/tin-tuc/bang-gia-dat").href.startswith("/")
    with pytest.raises(ValidationError, match="safe HTTPS or same-origin"):
        SourceCard(**base, href="javascript:alert(1)")


def test_provider_reasoning_is_excluded_from_serialized_contracts():
    response = ProviderResponse(
        content="Kết quả",
        reasoning_content="private chain of thought",
        usage=ProviderUsage(input_tokens=1, output_tokens=1),
    )

    assert response.reasoning_content == "private chain of thought"
    assert "reasoning_content" not in response.model_dump()
    message = ProviderMessage(
        role="assistant",
        content="Kết quả",
        reasoning_content="private continuation state",
    )
    assert message.reasoning_content == "private continuation state"
    assert "reasoning_content" not in message.model_dump()


@pytest.mark.parametrize(
    ("tier", "depth", "expected_model", "expected_thinking"),
    [
        ("free", AskDepth.FAST, "deepseek-v4-flash", False),
        ("free", AskDepth.DEEP, "deepseek-v4-flash", False),
        ("vip", AskDepth.STANDARD, "deepseek-v4-pro", False),
        ("vip", AskDepth.DEEP, "deepseek-v4-pro", True),
        ("admin", AskDepth.DEEP, "deepseek-v4-pro", True),
    ],
)
def test_tier_model_policy_is_exact(tier, depth, expected_model, expected_thinking):
    policy = resolve_model_policy(tier=tier, depth=depth, generated=True)

    assert isinstance(policy, ModelPolicy)
    assert policy.model == expected_model
    assert policy.thinking_enabled is expected_thinking


def test_deterministic_policy_has_zero_tokens_and_cost():
    policy = resolve_model_policy(tier="free", depth=AskDepth.FAST, generated=False)

    assert policy.model == "none"
    assert policy.max_input_tokens == 0
    assert policy.max_output_tokens == 0
    assert policy.max_cost_usd == Decimal("0")


def test_model_policy_rejects_guest_and_unknown_tiers():
    for tier in ("guest", "enterprise", ""):
        with pytest.raises(ValueError, match="authenticated tier"):
            resolve_model_policy(tier=tier, depth=AskDepth.FAST, generated=True)


def test_safe_settings_defaults_keep_feature_off_and_admin_only(monkeypatch):
    for name in (
        "RADAR_ASK_ENABLED",
        "RADAR_ASK_ALLOWED_TIERS",
        "RADAR_ASK_MONTHLY_WARN_USD",
        "RADAR_ASK_MONTHLY_HARD_USD",
        "RADAR_ASK_COST_SAFETY_MULTIPLIER",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = RadarAskSettings.from_env()

    assert settings.enabled is False
    assert settings.allowed_tiers == frozenset({"admin"})
    assert settings.monthly_warning_usd == Decimal("20")
    assert settings.monthly_hard_stop_usd == Decimal("50")
    assert settings.cost_safety_multiplier == Decimal("2.0")
    assert settings.provider_timeout_seconds == 30
    assert settings.deep_timeout_seconds == 60
    assert settings.evidence_row_limit == 50


def test_request_provider_budget_always_leaves_database_tool_margin():
    assert REQUEST_OWNER_LEASE_SECONDS == 300
    assert REQUEST_PROVIDER_BUDGET_CAP_SECONDS == 240
    assert REQUEST_DB_TOOL_MARGIN_SECONDS >= 30
    assert request_provider_budget_seconds(30) == 60
    assert request_provider_budget_seconds(120) == 240
    assert (
        REQUEST_OWNER_LEASE_SECONDS
        > REQUEST_PROVIDER_BUDGET_CAP_SECONDS + REQUEST_DB_TOOL_MARGIN_SECONDS
    )


def test_settings_repr_never_exposes_provider_or_database_secrets(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-secret-value")
    monkeypatch.setenv("RADAR_ASK_DATABASE_URL", "database-secret-value")

    rendered = repr(RadarAskSettings.from_env())

    assert "deepseek-secret-value" not in rendered
    assert "database-secret-value" not in rendered


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("RADAR_ASK_ALLOWED_TIERS", "admin,guest", "allowed tier"),
        ("RADAR_ASK_MONTHLY_WARN_USD", "51", "warning"),
        ("RADAR_ASK_MONTHLY_HARD_USD", "0", "hard stop"),
        ("RADAR_ASK_PROVIDER_TIMEOUT_SECONDS", "0", "provider timeout"),
        ("RADAR_ASK_EVIDENCE_ROW_LIMIT", "500", "evidence row limit"),
    ],
)
def test_settings_reject_unsafe_environment_values(monkeypatch, name, value, message):
    monkeypatch.setenv(name, value)

    with pytest.raises(ValueError, match=message):
        RadarAskSettings.from_env()


def test_run_status_contract_contains_only_approved_lifecycle_states():
    assert {status.value for status in RunStatus} == {
        "created",
        "clarifying",
        "queued",
        "running",
        "completed",
        "insufficient",
        "failed",
        "cancelled",
    }
