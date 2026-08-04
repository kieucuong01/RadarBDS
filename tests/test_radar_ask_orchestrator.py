from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from services.radar_ask.contracts import (
    AnswerClaim,
    AnswerEnvelope,
    AskContext,
    AskDepth,
    AskQuestionRequest,
    AskVerdict,
    EvidenceBundle,
    EvidenceItem,
    ProviderResponse,
    ProviderUsage,
    RetrievalQuality,
    RouteDecision,
    RunOutcome,
    RunStatus,
    SourceKind,
    ToolCall,
    UsageReservation,
    UsageSettlement,
)
from services.radar_ask.orchestrator import (
    OrchestratorDependencies,
    RadarAskFeatureDisabled,
    run_question,
)
from services.radar_ask.limits import BudgetHardStop, QuotaExceeded
from services.radar_ask.provider import ProviderUnavailable
from services.radar_ask.registry import (
    DEFAULT_TOOL_REGISTRY,
    ToolRegistration,
    ToolRegistry,
)
from services.radar_ask.validator import AnswerValidationError, validate_answer


NOW = datetime(2026, 8, 4, 6, 30, tzinfo=timezone.utc)


def make_context(tier: str = "free") -> AskContext:
    return AskContext(user_id=17, tier=tier)


def grounded_bundle(*, quality: RetrievalQuality = RetrievalQuality.SUFFICIENT) -> EvidenceBundle:
    return EvidenceBundle(
        question_snapshot="Khu nào giảm giá?",
        calculations={"answer_summary": "Phú Mỹ có 3 tín hiệu giảm giá cần kiểm tra."},
        items=[
            EvidenceItem(
                evidence_id="market:phu-my:drop-count",
                source_kind=SourceKind.MARKET_STAT,
                source_ref="market:phu-my",
                value=3,
                unit="tin",
                as_of=NOW,
                dataset_version="signals:12",
                sample_size=18,
                confidence=Decimal("0.82"),
            )
        ],
        retrieval_quality=quality,
    )


def generated_answer(
    *,
    depth: AskDepth = AskDepth.STANDARD,
    direct_answer: str = "Phú Mỹ đang có 3 tín hiệu giảm giá đáng kiểm tra.",
    evidence_ids: list[str] | None = None,
    verdict: object = AskVerdict.NEEDS_CHECKS,
) -> dict[str, object]:
    return {
        "answered": True,
        "depth": depth.value,
        "verdict": verdict.value if isinstance(verdict, AskVerdict) else verdict,
        "direct_answer": direct_answer,
        "claims": [
            {
                "text": "Có 3 tín hiệu trong mẫu hiện tại.",
                "evidence_ids": evidence_ids
                if evidence_ids is not None
                else ["market:phu-my:drop-count"],
                "numeric_value": "3",
                "unit": "tin",
            }
        ],
        "as_of": NOW.isoformat(),
        "dataset_version": "signals:12",
    }


@dataclass
class FakeRun:
    id: UUID
    session_id: UUID
    user_id: int
    idempotency_key: str
    question: str
    requested_depth: str | None
    effective_depth: str | None = None
    status: str = "created"
    outcome: str | None = None
    route: dict[str, object] | None = None
    answer: dict[str, object] | None = None
    model: str | None = None
    error_code: str | None = None
    retryable: bool = False


class FakeRepository:
    def __init__(self):
        self.runs: dict[tuple[int, str], FakeRun] = {}
        self.transitions: list[dict[str, object]] = []
        self.tools: list[dict[str, object]] = []
        self.evidence: list[dict[str, object]] = []
        self.messages: list[dict[str, object]] = []

    def create_run(self, *, user_id, question, idempotency_key, session_id, requested_depth):
        key = (user_id, idempotency_key)
        if key not in self.runs:
            self.runs[key] = FakeRun(
                id=uuid4(),
                session_id=session_id or uuid4(),
                user_id=user_id,
                idempotency_key=idempotency_key,
                question=question,
                requested_depth=requested_depth,
            )
        return self.runs[key]

    def transition_run(self, run_id, **kwargs):
        run = next(item for item in self.runs.values() if item.id == run_id)
        assert run.status in kwargs["expected"]
        updates = {
            "status": kwargs["target"],
            "outcome": kwargs.get("outcome"),
        }
        for name in (
            "effective_depth",
            "route",
            "answer",
            "model",
            "error_code",
            "retryable",
        ):
            if name in kwargs:
                updates[name] = kwargs[name]
        run = replace(run, **updates)
        self.runs[(run.user_id, run.idempotency_key)] = run
        self.transitions.append(dict(kwargs))
        return run

    def record_tool_call(self, **kwargs):
        self.tools.append(dict(kwargs))

    def record_evidence(self, **kwargs):
        self.evidence.append(dict(kwargs))

    def create_message(self, **kwargs):
        self.messages.append(dict(kwargs))


class FakeLimits:
    def __init__(self, reserve_error: Exception | None = None):
        self.reservations: list[dict[str, object]] = []
        self.settlements: list[dict[str, object]] = []
        self.reserve_error = reserve_error

    def reserve_question(self, **kwargs):
        self.reservations.append(dict(kwargs))
        if self.reserve_error is not None:
            raise self.reserve_error
        return UsageReservation(
            reservation_id=uuid4(),
            run_id=kwargs["run_id"],
            user_id=kwargs["user_id"],
            tier=kwargs["tier"],
            reserved_usd=Decimal(kwargs["max_cost_usd"]) * Decimal("2"),
        )

    def settle_question(self, **kwargs):
        self.settlements.append(dict(kwargs))
        outcome = kwargs["outcome"]
        return UsageSettlement(
            reservation_id=kwargs["reservation_id"],
            outcome=outcome,
            actual_usd=Decimal("0"),
            question_consumed=outcome in {RunOutcome.ANSWERED, RunOutcome.INSUFFICIENT},
        )


class FakeBurst:
    def __init__(self):
        self.calls: list[tuple[int, str]] = []

    def check(self, *, user_id: int, tier: str):
        self.calls.append((user_id, tier))


class FakeProvider:
    def __init__(self, response: ProviderResponse | None = None, error: Exception | None = None):
        self.response = response
        self.error = error
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response


def make_registry(handler) -> ToolRegistry:
    metadata = DEFAULT_TOOL_REGISTRY.get("rank_price_drop_areas")
    return ToolRegistry(
        {
            metadata.name: ToolRegistration(
                name=metadata.name,
                description=metadata.description,
                args_model=metadata.args_model,
                handler=handler,
            )
        }
    )


def make_deps(
    *,
    decision: RouteDecision,
    bundle: EvidenceBundle | None = None,
    provider: FakeProvider | None = None,
    enabled: bool = True,
    reserve_error: Exception | None = None,
) -> OrchestratorDependencies:
    repo = FakeRepository()
    limits = FakeLimits(reserve_error=reserve_error)
    burst = FakeBurst()
    evidence = bundle or grounded_bundle()
    registry = make_registry(lambda *, args, context: evidence)

    def router(request, context, **kwargs):
        return decision

    return OrchestratorDependencies(
        settings=SimpleNamespace(
            enabled=enabled,
            allowed_tiers=frozenset({"free", "vip", "admin"}),
            free_model="deepseek-v4-flash",
            smart_model="deepseek-v4-pro",
        ),
        repository=repo,
        limits=limits,
        burst=burst,
        router=router,
        registry=registry,
        provider=provider or FakeProvider(),
        clock=lambda: NOW,
    )


def fast_decision() -> RouteDecision:
    return RouteDecision(
        depth=AskDepth.FAST,
        question_type="price_drop_areas",
        tool_calls=[
            ToolCall(
                call_id="fast-1",
                name="rank_price_drop_areas",
                arguments={"window_days": 1},
            )
        ],
        generated=False,
    )


def standard_decision() -> RouteDecision:
    return RouteDecision(
        depth=AskDepth.STANDARD,
        question_type="market_recommendation",
        tool_calls=[
            ToolCall(
                call_id="standard-1",
                name="rank_price_drop_areas",
                arguments={"window_days": 1},
            )
        ],
        generated=True,
    )


def test_fast_deterministic_answer_has_zero_provider_cost_and_grounded_sources():
    deps = make_deps(decision=fast_decision())

    result = run_question(
        AskQuestionRequest(question="Khu nào giảm giá hôm nay?"),
        make_context(),
        dependencies=deps,
        idempotency_key="fast-1",
    )

    assert result.status is RunStatus.COMPLETED
    assert result.answer is not None
    assert result.answer.direct_answer == "Phú Mỹ có 3 tín hiệu giảm giá cần kiểm tra."
    assert result.answer.source_cards[0].evidence_id == "market:phu-my:drop-count"
    assert deps.provider.requests == []
    assert deps.limits.reservations[0]["max_cost_usd"] == Decimal("0")
    assert deps.limits.settlements[0]["outcome"] is RunOutcome.ANSWERED
    assert len(deps.repository.tools) == 1
    assert len(deps.repository.evidence) == 1


def test_generated_standard_answer_reserves_calls_provider_validates_and_settles():
    response = ProviderResponse(
        json_value=generated_answer(),
        usage=ProviderUsage(input_tokens=700, output_tokens=120, cache_miss_input_tokens=700),
        finish_reason="stop",
    )
    provider = FakeProvider(response=response)
    deps = make_deps(decision=standard_decision(), provider=provider)

    result = run_question(
        AskQuestionRequest(question="Phân tích khu đang giảm giá"),
        make_context(),
        dependencies=deps,
        idempotency_key="standard-1",
    )

    assert result.status is RunStatus.COMPLETED
    assert deps.limits.reservations[0]["max_cost_usd"] == Decimal("0.03")
    assert deps.limits.reservations[0]["model"] == "deepseek-v4-flash"
    assert deps.limits.settlements[0]["usage"].output_tokens == 120
    assert deps.limits.settlements[0]["outcome"] is RunOutcome.ANSWERED
    assert len(provider.requests) == 1
    assert provider.requests[0].json_mode is True
    assert provider.requests[0].thinking_enabled is False
    assert deps.repository.messages[-1]["role"] == "assistant"


def test_provider_boundary_redacts_phone_urls_and_secret_like_tokens_from_context():
    provider = FakeProvider(response=ProviderResponse(json_value=generated_answer()))
    deps = make_deps(decision=standard_decision(), provider=provider)
    context = AskContext(
        user_id=17,
        tier="vip",
        session_summary="Môi giới 0909 123 456 đăng tại https://guland.vn/tin/123",
        recent_turns=["Authorization: Bearer private-session-token"],
    )

    result = run_question(
        AskQuestionRequest(
            question="Phân tích tin https://batdongsan.com.vn/x, gọi 0912 345 678"
        ),
        context,
        dependencies=deps,
        idempotency_key="provider-redaction-1",
    )

    assert result.status is RunStatus.COMPLETED
    outbound = provider.requests[0].messages[1].content or ""
    assert "0909 123 456" not in outbound
    assert "0912 345 678" not in outbound
    assert "guland.vn" not in outbound
    assert "batdongsan.com.vn" not in outbound
    assert "private-session-token" not in outbound
    assert "[REDACTED]" in outbound


def test_deep_vip_is_queued_without_tool_or_provider_execution():
    decision = RouteDecision(
        depth=AskDepth.DEEP,
        question_type="portfolio_research",
        tool_calls=[
            ToolCall(
                call_id="deep-1",
                name="rank_price_drop_areas",
                arguments={"window_days": 30},
            )
        ],
        generated=True,
        use_thinking=True,
    )
    deps = make_deps(decision=decision)

    result = run_question(
        AskQuestionRequest(question="Nghiên cứu sâu danh mục"),
        make_context("vip"),
        dependencies=deps,
        idempotency_key="deep-1",
    )

    assert result.status is RunStatus.QUEUED
    assert deps.provider.requests == []
    assert deps.repository.tools == []
    assert deps.limits.reservations[0]["max_cost_usd"] == Decimal("0.12")
    assert deps.limits.reservations[0]["model"] == "deepseek-v4-pro"
    assert deps.limits.settlements == []


def test_clarification_releases_question_reservation():
    decision = RouteDecision(
        depth=AskDepth.STANDARD,
        question_type="clarification",
        generated=False,
        needs_clarification=True,
        clarification_question="Bạn muốn hỏi lô nào?",
    )
    deps = make_deps(decision=decision)

    result = run_question(
        AskQuestionRequest(question="Lô này giá sao?"),
        make_context(),
        dependencies=deps,
        idempotency_key="clarify-1",
    )

    assert result.status is RunStatus.CLARIFYING
    assert result.answer is not None
    assert result.answer.direct_answer == "Bạn muốn hỏi lô nào?"
    assert deps.limits.settlements[0]["outcome"] is RunOutcome.CLARIFICATION
    assert deps.provider.requests == []


def test_provider_failure_releases_question_and_money():
    provider = FakeProvider(error=ProviderUnavailable("private provider detail"))
    deps = make_deps(decision=standard_decision(), provider=provider)

    result = run_question(
        AskQuestionRequest(question="Phân tích khu đang giảm giá"),
        make_context("vip"),
        dependencies=deps,
        idempotency_key="provider-fail-1",
    )

    assert result.status is RunStatus.FAILED
    assert result.error_code == "provider_unavailable"
    assert result.retryable is True
    assert deps.limits.settlements[0]["outcome"] is RunOutcome.PROVIDER_FAILURE
    assert "private provider detail" not in str(deps.repository.transitions[-1])


@pytest.mark.parametrize(
    "answer",
    [
        generated_answer(direct_answer="Mua ngay lô này."),
        generated_answer(direct_answer="Gọi 0909 123 456 để chốt."),
        generated_answer(direct_answer="Xem https://guland.vn/tin/bi-mat để mua."),
        generated_answer(evidence_ids=["evidence:invented"]),
        generated_answer(verdict="nen_mua_ngay"),
    ],
)
def test_malicious_or_unsupported_provider_answer_fails_closed(answer):
    provider = FakeProvider(response=ProviderResponse(json_value=answer))
    deps = make_deps(decision=standard_decision(), provider=provider)

    result = run_question(
        AskQuestionRequest(question="Có nên mua không?"),
        make_context("vip"),
        dependencies=deps,
        idempotency_key=f"invalid-{uuid4()}",
    )

    assert result.status is RunStatus.FAILED
    assert result.error_code == "answer_validation_failed"
    assert deps.limits.settlements[0]["outcome"] is RunOutcome.VALIDATION_FAILURE


def test_numeric_material_claim_requires_existing_evidence():
    answer = AnswerEnvelope(
        answered=True,
        depth=AskDepth.STANDARD,
        verdict=AskVerdict.NEEDS_CHECKS,
        direct_answer="Giá tham khảo hiện tại cần kiểm tra thêm.",
        claims=[AnswerClaim(text="Giá khoảng 20 triệu/m².", evidence_ids=[])],
        as_of=NOW,
        dataset_version="signals:12",
    )

    with pytest.raises(AnswerValidationError):
        validate_answer(answer, [grounded_bundle()], tier="free", expected_depth=AskDepth.STANDARD)


def test_grounded_insufficient_result_consumes_one_question_without_provider():
    deps = make_deps(
        decision=fast_decision(),
        bundle=grounded_bundle(quality=RetrievalQuality.INSUFFICIENT),
    )

    result = run_question(
        AskQuestionRequest(question="Khu nào giảm giá hôm nay?"),
        make_context(),
        dependencies=deps,
        idempotency_key="insufficient-1",
    )

    assert result.status is RunStatus.INSUFFICIENT
    assert result.answer is not None and result.answer.answered is False
    assert result.answer.verdict is AskVerdict.INSUFFICIENT
    assert deps.limits.settlements[0]["outcome"] is RunOutcome.INSUFFICIENT


def test_idempotent_completed_run_returns_stored_answer_without_reexecution():
    deps = make_deps(decision=standard_decision())
    stored = FakeRun(
        id=uuid4(),
        session_id=uuid4(),
        user_id=17,
        idempotency_key="same-request",
        question="Phân tích khu đang giảm giá",
        requested_depth=None,
        effective_depth="standard",
        status="completed",
        outcome="answered",
        answer=generated_answer(),
        model="deepseek-v4-flash",
    )
    deps.repository.runs[(17, "same-request")] = stored

    result = run_question(
        AskQuestionRequest(question=stored.question),
        make_context(),
        dependencies=deps,
        idempotency_key="same-request",
    )

    assert result.run_id == stored.id
    assert result.status is RunStatus.COMPLETED
    assert result.answer is not None
    assert deps.limits.reservations == []
    assert deps.provider.requests == []
    assert deps.repository.tools == []


def test_feature_setting_is_checked_before_burst_or_persistence():
    deps = make_deps(decision=fast_decision(), enabled=False)

    with pytest.raises(RadarAskFeatureDisabled):
        run_question(
            AskQuestionRequest(question="Khu nào giảm giá?"),
            make_context(),
            dependencies=deps,
        )

    assert deps.burst.calls == []
    assert deps.repository.runs == {}


@pytest.mark.parametrize(
    ("error", "expected_outcome", "expected_code"),
    [
        (
            QuotaExceeded(tier="vip", limit=20, used=20, reset_at=NOW),
            RunOutcome.CANCELLED.value,
            "daily_quota_exceeded",
        ),
        (
            BudgetHardStop(projected_usd=Decimal("50.01"), hard_stop_usd=Decimal("50")),
            RunOutcome.BUDGET_HARD_STOP.value,
            "monthly_budget_hard_stop",
        ),
    ],
)
def test_daily_quota_and_monthly_budget_failures_remain_distinct(
    error,
    expected_outcome,
    expected_code,
):
    deps = make_deps(
        decision=standard_decision(),
        reserve_error=error,
    )

    with pytest.raises(type(error)):
        run_question(
            AskQuestionRequest(question="Phân tích khu đang giảm giá"),
            make_context("vip"),
            dependencies=deps,
            idempotency_key=f"limit-{expected_code}",
        )

    stored = next(iter(deps.repository.runs.values()))
    assert stored.status == RunStatus.CANCELLED.value
    assert stored.outcome == expected_outcome
    assert stored.error_code == expected_code
    assert deps.limits.settlements == []
