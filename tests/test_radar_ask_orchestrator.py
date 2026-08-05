from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from threading import Event
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
    PlannerResult,
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
    correction_limit,
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
    worker_id: str | None = None
    lease_until: datetime | None = None


class FakeRepository:
    def __init__(self):
        self.runs: dict[tuple[int, str], FakeRun] = {}
        self.transitions: list[dict[str, object]] = []
        self.tools: list[dict[str, object]] = []
        self.evidence: list[dict[str, object]] = []
        self.messages: list[dict[str, object]] = []
        self.planning_claims: list[dict[str, object]] = []
        self.planning_finalizations: list[dict[str, object]] = []
        self.planning_failures: list[dict[str, object]] = []
        self.sync_claims: list[dict[str, object]] = []
        self.sync_finalizations: list[dict[str, object]] = []

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

    def get_run(self, *, user_id, run_id):
        return next(
            (item for item in self.runs.values() if item.id == run_id and item.user_id == user_id),
            None,
        )

    def claim_planning(self, run_id, **kwargs):
        run = self.get_run(user_id=kwargs["user_id"], run_id=run_id)
        assert run is not None
        if run.status != "created":
            return None
        run = replace(
            run,
            status="running",
            worker_id=kwargs["planner_id"],
            lease_until=NOW + timedelta(seconds=kwargs.get("lease_seconds", 90)),
        )
        self.runs[(run.user_id, run.idempotency_key)] = run
        self.planning_claims.append(dict(kwargs))
        return run

    def claim_reserved_run(self, run_id, **kwargs):
        run = self.get_run(user_id=kwargs["user_id"], run_id=run_id)
        assert run is not None
        if run.status != "created":
            return None
        run = replace(
            run,
            status="running",
            worker_id=kwargs["owner_id"],
            lease_until=NOW + timedelta(seconds=kwargs.get("lease_seconds", 90)),
            effective_depth=kwargs.get("effective_depth") or run.effective_depth,
            route=dict(kwargs["route"]) if kwargs.get("route") is not None else run.route,
            model=kwargs.get("model") or run.model,
        )
        self.runs[(run.user_id, run.idempotency_key)] = run
        self.sync_claims.append(dict(kwargs))
        if str(kwargs["owner_id"]).startswith("planner:"):
            self.planning_claims.append(dict(kwargs))
        return run

    def finalize_planning(self, run_id, **kwargs):
        run = self.get_run(user_id=kwargs["user_id"], run_id=run_id)
        assert run is not None and run.worker_id == kwargs["planner_id"]
        target = kwargs["target"]
        run = replace(
            run,
            status=target,
            effective_depth=kwargs["effective_depth"],
            route=dict(kwargs["route"]),
            model=kwargs["answer_model"],
            worker_id=None if target == "queued" else run.worker_id,
            lease_until=None if target == "queued" else run.lease_until,
        )
        self.runs[(run.user_id, run.idempotency_key)] = run
        self.planning_finalizations.append(dict(kwargs))
        return run

    def fail_planning(self, run_id, **kwargs):
        run = self.get_run(user_id=kwargs["user_id"], run_id=run_id)
        assert run is not None and run.worker_id == kwargs["planner_id"]
        run = replace(
            run,
            status="failed",
            outcome=kwargs["outcome"],
            error_code=kwargs["error_code"],
            retryable=kwargs["retryable"],
            worker_id=None,
            lease_until=None,
        )
        self.runs[(run.user_id, run.idempotency_key)] = run
        self.planning_failures.append(dict(kwargs))
        return run

    def finalize_sync_run(self, run_id, **kwargs):
        run = self.get_run(user_id=kwargs["user_id"], run_id=run_id)
        assert run is not None
        if run.status == kwargs["target"]:
            return run
        assert run.status == "running" and run.worker_id == kwargs["owner_id"]
        answer = dict(kwargs["answer"]) if kwargs.get("answer") is not None else None
        run = replace(
            run,
            status=kwargs["target"],
            outcome=kwargs["outcome"],
            effective_depth=kwargs.get("effective_depth") or run.effective_depth,
            route=dict(kwargs["route"]) if kwargs.get("route") is not None else run.route,
            answer=answer,
            model=kwargs.get("model") or run.model,
            error_code=kwargs.get("error_code"),
            retryable=kwargs.get("retryable", False),
            worker_id=None,
            lease_until=None,
        )
        self.runs[(run.user_id, run.idempotency_key)] = run
        self.sync_finalizations.append(dict(kwargs))
        if answer is not None:
            self.messages.append(
                {
                    "user_id": run.user_id,
                    "session_id": run.session_id,
                    "role": "assistant",
                    "content": answer["direct_answer"],
                    "answer": answer,
                    "run_id": run.id,
                }
            )
        return run

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
        self.planner_usage: list[dict[str, object]] = []

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

    def record_planner_usage(self, **kwargs):
        self.planner_usage.append(dict(kwargs))


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
    handler=None,
) -> OrchestratorDependencies:
    repo = FakeRepository()
    limits = FakeLimits(reserve_error=reserve_error)
    burst = FakeBurst()
    evidence = bundle or grounded_bundle()
    registry = make_registry(handler or (lambda *, args, context: evidence))

    def router(request, context, **kwargs):
        return decision

    return OrchestratorDependencies(
        settings=SimpleNamespace(
            enabled=enabled,
            allowed_tiers=frozenset({"free", "vip", "admin"}),
            free_model="deepseek-v4-flash",
            smart_model="deepseek-v4-pro",
            router_model="deepseek-v4-flash",
            monthly_hard_stop_usd=Decimal("50"),
        ),
        repository=repo,
        limits=limits,
        burst=burst,
        router=router,
        registry=registry,
        provider=provider or FakeProvider(),
        clock=lambda: NOW,
    )


def test_unmatched_question_claims_before_typed_planner_and_atomically_persists_usage_route():
    events: list[str] = []
    class OrderedRepository(FakeRepository):
        def claim_reserved_run(self, run_id, **kwargs):
            events.append("claim")
            return super().claim_reserved_run(run_id, **kwargs)

        def finalize_planning(self, run_id, **kwargs):
            events.append("finalize")
            return super().finalize_planning(run_id, **kwargs)

        def finalize_sync_run(self, run_id, **kwargs):
            events.append("sync_finalize")
            return super().finalize_sync_run(run_id, **kwargs)

    repo = OrderedRepository()

    class OrderedLimits(FakeLimits):
        def reserve_question(self, **kwargs):
            events.append("reserve")
            return super().reserve_question(**kwargs)

        def settle_question(self, **kwargs):
            events.append("settle")
            return super().settle_question(**kwargs)

    planner_usage = ProviderUsage(
        input_tokens=300,
        output_tokens=60,
        cache_miss_input_tokens=300,
    )

    def planner(**_kwargs):
        events.append("planner")
        return PlannerResult(
            decision=RouteDecision(
                depth=AskDepth.STANDARD,
                question_type="market_trend",
                tool_calls=[
                    ToolCall(
                        call_id="planner-trend-1",
                        name="get_market_trend",
                        arguments={"ward": "Phu My", "window_days": 90},
                    )
                ],
                generated=True,
            ),
            usage=planner_usage,
        )

    provider = FakeProvider(
        response=ProviderResponse(
            json_value=generated_answer(),
            usage=ProviderUsage(input_tokens=700, output_tokens=120),
        )
    )
    metadata = DEFAULT_TOOL_REGISTRY.get("get_market_trend")
    registry = ToolRegistry(
        {
            metadata.name: ToolRegistration(
                name=metadata.name,
                description=metadata.description,
                args_model=metadata.args_model,
                handler=lambda *, args, context: grounded_bundle(),
            )
        }
    )
    limits = OrderedLimits()
    from services.radar_ask.routing import route_question

    dependencies = OrchestratorDependencies(
        settings=SimpleNamespace(
            enabled=True,
            allowed_tiers=frozenset({"free", "vip", "admin"}),
            free_model="deepseek-v4-flash",
            smart_model="deepseek-v4-pro",
            router_model="deepseek-v4-flash",
            monthly_hard_stop_usd=Decimal("50"),
        ),
        repository=repo,
        limits=limits,
        burst=FakeBurst(),
        router=route_question,
        registry=registry,
        provider=provider,
        clock=lambda: NOW,
        planner=planner,
    )

    result = run_question(
        AskQuestionRequest(question="Phu My dang co xu huong the nao?"),
        make_context("vip"),
        dependencies=dependencies,
        idempotency_key="planned-standard-1",
    )

    assert result.status is RunStatus.COMPLETED
    assert events == ["reserve", "claim", "planner", "finalize", "sync_finalize"]
    assert limits.reservations[0]["max_cost_usd"] == Decimal("0.13")
    assert limits.reservations[0]["model"] == "deepseek-v4-pro"
    assert repo.planning_finalizations[0]["planner_model"] == "deepseek-v4-flash"
    assert repo.planning_finalizations[0]["usage"] == planner_usage
    assert limits.settlements == []
    assert repo.sync_finalizations[0]["usage"] == ProviderUsage(input_tokens=700, output_tokens=120)


def test_deterministic_fast_does_not_call_planner_or_reserve_provider_cost():
    calls = []

    def planner(**_kwargs):
        calls.append("planner")
        raise AssertionError("deterministic Fast must not plan")

    deps = make_deps(decision=fast_decision())
    deps = replace(deps, planner=planner)

    result = run_question(
        AskQuestionRequest(question="Khu nao giam gia hom nay?"),
        make_context(),
        dependencies=deps,
        idempotency_key="fast-no-planner-reservation",
    )

    assert result.status is RunStatus.COMPLETED
    assert calls == []
    assert deps.limits.reservations[0]["max_cost_usd"] == Decimal("0")
    assert deps.limits.planner_usage == []


def test_planner_failure_records_known_usage_then_releases_without_answered_quota():
    usage = ProviderUsage(input_tokens=150, output_tokens=25, cache_miss_input_tokens=150)

    def planner(**_kwargs):
        raise ProviderUnavailable("private planner error", usage=usage)

    from services.radar_ask.routing import route_question

    repo = FakeRepository()
    limits = FakeLimits()
    dependencies = OrchestratorDependencies(
        settings=SimpleNamespace(
            enabled=True,
            allowed_tiers=frozenset({"free", "vip", "admin"}),
            free_model="deepseek-v4-flash",
            smart_model="deepseek-v4-pro",
            router_model="deepseek-v4-flash",
            monthly_hard_stop_usd=Decimal("50"),
        ),
        repository=repo,
        limits=limits,
        burst=FakeBurst(),
        router=route_question,
        registry=DEFAULT_TOOL_REGISTRY,
        provider=FakeProvider(),
        clock=lambda: NOW,
        planner=planner,
    )

    result = run_question(
        AskQuestionRequest(question="Phu My dang co xu huong the nao?"),
        make_context("vip"),
        dependencies=dependencies,
        idempotency_key="planner-failure-cost",
    )

    assert result.status is RunStatus.FAILED
    assert result.error_code == "planner_unavailable"
    assert result.retryable is True
    assert limits.planner_usage == []
    assert limits.settlements == []
    assert repo.planning_failures[0]["planner_model"] == "deepseek-v4-flash"
    assert repo.planning_failures[0]["usage"] == usage
    assert repo.planning_failures[0]["outcome"] == RunOutcome.PROVIDER_FAILURE.value


def test_planned_deep_persists_validated_route_and_preflight_usage_before_queue():
    planner_usage = ProviderUsage(input_tokens=250, output_tokens=40)

    def planner(**_kwargs):
        return PlannerResult(
            decision=RouteDecision(
                depth=AskDepth.DEEP,
                question_type="deep_market_research",
                tool_calls=[
                    ToolCall(
                        call_id="planned-deep-1",
                        name="rank_price_drop_areas",
                        arguments={"window_days": 30, "limit": 10},
                    )
                ],
                generated=True,
            ),
            usage=planner_usage,
        )

    from services.radar_ask.routing import route_question

    repo = FakeRepository()
    limits = FakeLimits()
    dependencies = OrchestratorDependencies(
        settings=SimpleNamespace(
            enabled=True,
            allowed_tiers=frozenset({"free", "vip", "admin"}),
            free_model="deepseek-v4-flash",
            smart_model="deepseek-v4-pro",
            router_model="deepseek-v4-flash",
            monthly_hard_stop_usd=Decimal("50"),
        ),
        repository=repo,
        limits=limits,
        burst=FakeBurst(),
        router=route_question,
        registry=make_registry(lambda *, args, context: grounded_bundle()),
        provider=FakeProvider(),
        clock=lambda: NOW,
        planner=planner,
    )

    result = run_question(
        AskQuestionRequest(question="Danh gia toan dien xu huong khu vuc nay"),
        make_context("vip"),
        dependencies=dependencies,
        idempotency_key="planned-deep-route",
    )

    stored = next(iter(repo.runs.values()))
    assert result.status is RunStatus.QUEUED
    assert stored.route == RouteDecision.model_validate(stored.route).model_dump(mode="json")
    assert stored.route["question_type"] == "deep_market_research"
    assert stored.route["depth"] == "deep"
    assert repo.planning_finalizations[0]["usage"] == planner_usage
    assert limits.settlements == []
    assert dependencies.provider.requests == []


def test_planned_deep_clarification_finalizes_directly_and_never_queues():
    planner_usage = ProviderUsage(input_tokens=33, output_tokens=7)

    def planner(**_kwargs):
        return PlannerResult(
            decision=RouteDecision(
                depth=AskDepth.DEEP,
                question_type="clarification",
                tool_calls=[],
                generated=True,
                needs_clarification=True,
                clarification_question="Bạn muốn phân tích phường nào?",
            ),
            usage=planner_usage,
        )

    from services.radar_ask.routing import route_question

    repository = FakeRepository()
    dependencies = OrchestratorDependencies(
        settings=SimpleNamespace(
            enabled=True,
            allowed_tiers=frozenset({"free", "vip", "admin"}),
            free_model="deepseek-v4-flash",
            smart_model="deepseek-v4-pro",
            router_model="deepseek-v4-flash",
            monthly_hard_stop_usd=Decimal("50"),
        ),
        repository=repository,
        limits=FakeLimits(),
        burst=FakeBurst(),
        router=route_question,
        registry=DEFAULT_TOOL_REGISTRY,
        provider=FakeProvider(),
        clock=lambda: NOW,
        planner=planner,
    )

    result = run_question(
        AskQuestionRequest(question="Phân tích sâu khu này"),
        make_context("vip"),
        dependencies=dependencies,
        idempotency_key="planned-deep-clarification",
    )

    assert result.status is RunStatus.CLARIFYING
    assert result.answer is not None
    assert result.answer.direct_answer == "Bạn muốn phân tích phường nào?"
    assert repository.planning_finalizations == []
    assert len(repository.sync_finalizations) == 1
    finalized = repository.sync_finalizations[0]
    assert finalized["target"] == RunStatus.CLARIFYING.value
    assert finalized["planner_usage"] == planner_usage
    assert finalized["effective_depth"] == AskDepth.DEEP.value
    assert dependencies.provider.requests == []


@pytest.mark.parametrize("commit_mode", ["ambiguous", "precommit"])
def test_sync_finalize_retry_never_repeats_provider(commit_mode):
    class FlakyFinalizeRepository(FakeRepository):
        def __init__(self):
            super().__init__()
            self.raised = False

        def finalize_sync_run(self, run_id, **kwargs):
            if not self.raised and commit_mode == "precommit":
                self.raised = True
                raise RuntimeError("commit failed before durable write")
            result = super().finalize_sync_run(run_id, **kwargs)
            if not self.raised and commit_mode == "ambiguous":
                self.raised = True
                raise RuntimeError("ambiguous commit acknowledgement")
            return result

    provider = FakeProvider(
        response=ProviderResponse(
            json_value=generated_answer(),
            usage=ProviderUsage(input_tokens=80, output_tokens=16),
        )
    )
    repository = FlakyFinalizeRepository()
    dependencies = make_deps(decision=standard_decision(), provider=provider)
    dependencies = replace(dependencies, repository=repository)
    request = AskQuestionRequest(question="Phân tích giá khu này")

    first = run_question(
        request,
        make_context("vip"),
        dependencies=dependencies,
        idempotency_key=f"sync-{commit_mode}",
    )
    replay = run_question(
        request,
        make_context("vip"),
        dependencies=dependencies,
        idempotency_key=f"sync-{commit_mode}",
    )

    assert first.status is RunStatus.COMPLETED
    assert replay.status is RunStatus.COMPLETED
    assert len(provider.requests) == 1
    assert len(repository.sync_finalizations) == 1


def test_ambiguous_planner_finalize_reconciles_durable_route_without_replanning():
    class CommitThenRaiseRepository(FakeRepository):
        def __init__(self):
            super().__init__()
            self.raised = False

        def finalize_planning(self, run_id, **kwargs):
            result = super().finalize_planning(run_id, **kwargs)
            if not self.raised:
                self.raised = True
                raise RuntimeError("ambiguous commit acknowledgement")
            return result

    planner_calls = 0

    def planner(**_kwargs):
        nonlocal planner_calls
        planner_calls += 1
        return PlannerResult(
            decision=RouteDecision(
                depth=AskDepth.STANDARD,
                question_type="market_trend",
                tool_calls=[
                    ToolCall(
                        call_id="ambiguous-trend-1",
                        name="get_market_trend",
                        arguments={"ward": "Phu My", "window_days": 90},
                    )
                ],
                generated=True,
            ),
            usage=ProviderUsage(input_tokens=31, output_tokens=7),
        )

    provider = FakeProvider(
        response=ProviderResponse(
            json_value=generated_answer(),
            usage=ProviderUsage(input_tokens=70, output_tokens=12),
        )
    )
    metadata = DEFAULT_TOOL_REGISTRY.get("get_market_trend")
    repository = CommitThenRaiseRepository()
    dependencies = OrchestratorDependencies(
        settings=SimpleNamespace(
            enabled=True,
            allowed_tiers=frozenset({"free", "vip", "admin"}),
            free_model="deepseek-v4-flash",
            smart_model="deepseek-v4-pro",
            router_model="deepseek-v4-flash",
            monthly_hard_stop_usd=Decimal("50"),
        ),
        repository=repository,
        limits=FakeLimits(),
        burst=FakeBurst(),
        router=__import__(
            "services.radar_ask.routing",
            fromlist=["route_question"],
        ).route_question,
        registry=ToolRegistry(
            {
                metadata.name: ToolRegistration(
                    name=metadata.name,
                    description=metadata.description,
                    args_model=metadata.args_model,
                    handler=lambda *, args, context: grounded_bundle(),
                )
            }
        ),
        provider=provider,
        clock=lambda: NOW,
        planner=planner,
    )

    result = run_question(
        AskQuestionRequest(question="Phu My hien co xu huong gi?"),
        make_context("vip"),
        dependencies=dependencies,
        idempotency_key="planner-ambiguous-finalize",
    )

    assert result.status is RunStatus.COMPLETED
    assert planner_calls == 1
    assert len(repository.planning_claims) == 1
    assert len(repository.planning_finalizations) == 1


def test_precommit_planner_persistence_failure_is_terminal_and_replay_never_replans():
    class RaiseBeforeCommitRepository(FakeRepository):
        def finalize_planning(self, run_id, **kwargs):
            raise RuntimeError("database failed before commit")

    planner_calls = 0

    def planner(**_kwargs):
        nonlocal planner_calls
        planner_calls += 1
        return PlannerResult(
            decision=RouteDecision(
                depth=AskDepth.DEEP,
                question_type="deep_market_research",
                tool_calls=[],
                generated=True,
            ),
            usage=ProviderUsage(input_tokens=23, output_tokens=5),
        )

    from services.radar_ask.routing import route_question

    repository = RaiseBeforeCommitRepository()
    dependencies = OrchestratorDependencies(
        settings=SimpleNamespace(
            enabled=True,
            allowed_tiers=frozenset({"free", "vip", "admin"}),
            free_model="deepseek-v4-flash",
            smart_model="deepseek-v4-pro",
            router_model="deepseek-v4-flash",
            monthly_hard_stop_usd=Decimal("50"),
        ),
        repository=repository,
        limits=FakeLimits(),
        burst=FakeBurst(),
        router=route_question,
        registry=DEFAULT_TOOL_REGISTRY,
        provider=FakeProvider(),
        clock=lambda: NOW,
        planner=planner,
    )
    request = AskQuestionRequest(question="Đánh giá toàn diện thị trường này")

    first = run_question(
        request,
        make_context("vip"),
        dependencies=dependencies,
        idempotency_key="planner-precommit-failure",
    )
    replay = run_question(
        request,
        make_context("vip"),
        dependencies=dependencies,
        idempotency_key="planner-precommit-failure",
    )

    assert first.status is RunStatus.FAILED
    assert first.error_code == "planner_persistence_failed"
    assert replay.status is RunStatus.FAILED
    assert planner_calls == 1
    assert repository.planning_failures[0]["usage"] == ProviderUsage(
        input_tokens=23,
        output_tokens=5,
    )


def test_concurrent_idempotent_replay_observes_claimed_run_and_only_owner_plans():
    planner_started = Event()
    release_planner = Event()
    planner_calls = 0

    def planner(**_kwargs):
        nonlocal planner_calls
        planner_calls += 1
        planner_started.set()
        assert release_planner.wait(timeout=3)
        return PlannerResult(
            decision=RouteDecision(
                depth=AskDepth.STANDARD,
                question_type="market_trend",
                tool_calls=[
                    ToolCall(
                        call_id="concurrent-trend-1",
                        name="get_market_trend",
                        arguments={"ward": "Phu My", "window_days": 90},
                    )
                ],
                generated=True,
            ),
            usage=ProviderUsage(input_tokens=19, output_tokens=4),
        )

    from services.radar_ask.routing import route_question

    metadata = DEFAULT_TOOL_REGISTRY.get("get_market_trend")
    repository = FakeRepository()
    dependencies = OrchestratorDependencies(
        settings=SimpleNamespace(
            enabled=True,
            allowed_tiers=frozenset({"free", "vip", "admin"}),
            free_model="deepseek-v4-flash",
            smart_model="deepseek-v4-pro",
            router_model="deepseek-v4-flash",
            monthly_hard_stop_usd=Decimal("50"),
        ),
        repository=repository,
        limits=FakeLimits(),
        burst=FakeBurst(),
        router=route_question,
        registry=ToolRegistry(
            {
                metadata.name: ToolRegistration(
                    name=metadata.name,
                    description=metadata.description,
                    args_model=metadata.args_model,
                    handler=lambda *, args, context: grounded_bundle(),
                )
            }
        ),
        provider=FakeProvider(
            response=ProviderResponse(
                json_value=generated_answer(),
                usage=ProviderUsage(input_tokens=50, output_tokens=10),
            )
        ),
        clock=lambda: NOW,
        planner=planner,
    )
    request = AskQuestionRequest(question="Phu My hien co xu huong nao?")

    with ThreadPoolExecutor(max_workers=1) as pool:
        owner = pool.submit(
            lambda: run_question(
                request,
                make_context("vip"),
                dependencies=dependencies,
                idempotency_key="planner-concurrent-replay",
            )
        )
        assert planner_started.wait(timeout=3)
        replay = run_question(
            request,
            make_context("vip"),
            dependencies=dependencies,
            idempotency_key="planner-concurrent-replay",
        )
        release_planner.set()
        completed = owner.result(timeout=3)

    assert replay.status is RunStatus.RUNNING
    assert completed.status is RunStatus.COMPLETED
    assert planner_calls == 1
    assert len(repository.planning_claims) == 1


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
    assert deps.repository.sync_finalizations[0]["outcome"] == RunOutcome.ANSWERED.value
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
    assert deps.repository.sync_finalizations[0]["usage"].output_tokens == 120
    assert deps.repository.sync_finalizations[0]["outcome"] == RunOutcome.ANSWERED.value
    assert len(provider.requests) == 1
    assert provider.requests[0].json_mode is True
    assert provider.requests[0].thinking_enabled is False
    assert deps.repository.messages[-1]["role"] == "assistant"
    assert deps.repository.messages[-1]["run_id"] == result.run_id


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
    assert deps.repository.sync_finalizations[0]["outcome"] == RunOutcome.CLARIFICATION.value
    assert deps.provider.requests == []


def test_provider_failure_releases_question_and_money():
    known_usage = ProviderUsage(input_tokens=61, output_tokens=9)
    provider = FakeProvider(
        error=ProviderUnavailable("private provider detail", usage=known_usage)
    )
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
    assert deps.repository.sync_finalizations[0]["outcome"] == RunOutcome.PROVIDER_FAILURE.value
    assert deps.repository.sync_finalizations[0]["usage"] == known_usage
    assert "private provider detail" not in str(deps.repository.sync_finalizations[-1])


def test_tool_failure_after_sync_claim_atomically_fails_without_provider_call():
    def broken_tool(**_kwargs):
        raise RuntimeError("private database detail")

    deps = make_deps(decision=fast_decision(), handler=broken_tool)

    result = run_question(
        AskQuestionRequest(question="Khu nào giảm giá hôm nay?"),
        make_context(),
        dependencies=deps,
        idempotency_key="sync-tool-failure",
    )

    assert result.status is RunStatus.FAILED
    assert result.error_code == "evidence_execution_failed"
    assert deps.provider.requests == []
    assert len(deps.repository.sync_claims) == 1
    assert len(deps.repository.sync_finalizations) == 1
    finalized = deps.repository.sync_finalizations[0]
    assert finalized["target"] == RunStatus.FAILED.value
    assert finalized["outcome"] == RunOutcome.DATABASE_FAILURE.value
    assert finalized["usage"] == ProviderUsage()
    assert "private database detail" not in str(finalized)


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
    assert deps.repository.sync_finalizations[0]["outcome"] == RunOutcome.VALIDATION_FAILURE.value


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
    assert deps.repository.sync_finalizations[0]["outcome"] == RunOutcome.INSUFFICIENT.value


@pytest.mark.parametrize(
    ("depth", "tier", "expected"),
    [
        (AskDepth.FAST, "free", 0),
        (AskDepth.STANDARD, "free", 1),
        (AskDepth.STANDARD, "admin", 1),
        (AskDepth.DEEP, "free", 1),
        (AskDepth.DEEP, "vip", 2),
        (AskDepth.DEEP, "admin", 2),
    ],
)
def test_corrective_retrieval_limits_are_bounded_by_depth_and_tier(depth, tier, expected):
    assert correction_limit(depth, tier) == expected


def test_standard_repair_expands_window_once_then_synthesizes_from_repaired_evidence():
    seen_windows: list[int] = []

    def handler(*, args, context):
        seen_windows.append(args.window_days)
        if len(seen_windows) == 1:
            return grounded_bundle(quality=RetrievalQuality.REPAIR).model_copy(
                update={"missing_requirements": ["fresh_evidence_required"]}
            )
        return grounded_bundle()

    provider = FakeProvider(response=ProviderResponse(json_value=generated_answer()))
    deps = make_deps(
        decision=standard_decision(),
        provider=provider,
        handler=handler,
    )

    result = run_question(
        AskQuestionRequest(question="Phân tích khu đang giảm giá"),
        make_context(),
        dependencies=deps,
        idempotency_key="repair-standard-1",
    )

    assert result.status is RunStatus.COMPLETED
    assert seen_windows == [1, 7]
    assert len(deps.repository.tools) == 2
    assert len(provider.requests) == 1


def test_exhausted_standard_repair_returns_grounded_insufficient_without_provider():
    seen_windows: list[int] = []

    def handler(*, args, context):
        seen_windows.append(args.window_days)
        return grounded_bundle(quality=RetrievalQuality.REPAIR).model_copy(
            update={"missing_requirements": ["minimum_three_road_listings_required"]}
        )

    provider = FakeProvider(response=ProviderResponse(json_value=generated_answer()))
    deps = make_deps(
        decision=standard_decision(),
        provider=provider,
        handler=handler,
    )

    result = run_question(
        AskQuestionRequest(question="Phân tích khu đang giảm giá"),
        make_context("vip"),
        dependencies=deps,
        idempotency_key="repair-exhausted-1",
    )

    assert result.status is RunStatus.INSUFFICIENT
    assert result.answer is not None and result.answer.verdict is AskVerdict.INSUFFICIENT
    assert "minimum_three_road_listings_required" in result.answer.next_verification_steps
    assert seen_windows == [1, 7]
    assert provider.requests == []


def test_fast_path_never_runs_corrective_retrieval():
    calls = 0

    def handler(*, args, context):
        nonlocal calls
        calls += 1
        return grounded_bundle(quality=RetrievalQuality.REPAIR)

    deps = make_deps(decision=fast_decision(), handler=handler)

    result = run_question(
        AskQuestionRequest(question="Khu nào giảm giá hôm nay?"),
        make_context(),
        dependencies=deps,
        idempotency_key="fast-no-repair-1",
    )

    assert result.status is RunStatus.INSUFFICIENT
    assert calls == 1
    assert deps.provider.requests == []


def test_standard_correction_limit_counts_retrievals_not_batches_of_tool_calls():
    seen_windows: list[int] = []

    def handler(*, args, context):
        seen_windows.append(args.window_days)
        evidence = EvidenceItem(
            evidence_id=f"market:window:{args.window_days}",
            source_kind=SourceKind.MARKET_STAT,
            source_ref=f"market:window:{args.window_days}",
            value=3,
            unit="tin",
            as_of=NOW,
            dataset_version=f"signals:{args.window_days}",
            sample_size=3,
        )
        return EvidenceBundle(
            question_snapshot="Khu nào giảm giá?",
            items=[evidence],
            missing_requirements=["more_evidence_required"],
            retrieval_quality=RetrievalQuality.REPAIR,
        )

    decision = standard_decision().model_copy(
        update={
            "tool_calls": [
                ToolCall(
                    call_id="standard-a",
                    name="rank_price_drop_areas",
                    arguments={"window_days": 1},
                ),
                ToolCall(
                    call_id="standard-b",
                    name="rank_price_drop_areas",
                    arguments={"window_days": 2},
                ),
            ]
        }
    )
    deps = make_deps(decision=decision, handler=handler)

    result = run_question(
        AskQuestionRequest(question="Phân tích khu đang giảm giá"),
        make_context("vip"),
        dependencies=deps,
        idempotency_key="correction-total-limit-1",
    )

    assert result.status is RunStatus.INSUFFICIENT
    assert seen_windows == [1, 2, 7]
    assert len(deps.repository.tools) == 3


def test_provider_receives_tier_filtered_evidence_without_private_keys():
    private = EvidenceItem(
        evidence_id="market:admin-only",
        source_kind=SourceKind.MARKET_STAT,
        source_ref="https://private.example/source",
        value={"user_id": 999, "phone": "0909 123 456", "secret_note": "hidden"},
        unit="tin",
        as_of=NOW,
        dataset_version="signals:12",
        sample_size=3,
        min_tier="admin",
    )
    evidence = grounded_bundle().model_copy(
        update={"items": [*grounded_bundle().items, private]}
    )
    provider = FakeProvider(response=ProviderResponse(json_value=generated_answer()))
    deps = make_deps(
        decision=standard_decision(),
        bundle=evidence,
        provider=provider,
    )

    result = run_question(
        AskQuestionRequest(question="Phân tích khu đang giảm giá"),
        make_context("free"),
        dependencies=deps,
        idempotency_key="provider-tier-filter-1",
    )

    assert result.status is RunStatus.FAILED
    assert result.error_code == "answer_validation_failed"
    assert provider.requests == []


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
