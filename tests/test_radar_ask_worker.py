from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from threading import Event, Thread
from types import SimpleNamespace
from uuid import uuid4

import pytest

from db import connection
from db.connection import get_conn
from db.schema import init_schema
from services.radar_ask.contracts import (
    AskDepth,
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
    execute_leased_run,
)
from services.radar_ask.provider import ProviderUnavailable
from services.radar_ask.registry import DEFAULT_TOOL_REGISTRY, ToolRegistration, ToolRegistry
from services.radar_ask.repository import InvalidRunTransition, RadarAskRepository
from services.radar_ask.worker import RadarAskWorker, RadarAskWorkerDisabled


NOW = datetime(2026, 8, 5, 5, 0, tzinfo=timezone.utc)


@dataclass(frozen=True)
class WorkerUsers:
    vip_id: int


@pytest.fixture
def worker_repo():
    token = uuid4().hex
    connection.close_all()
    init_schema()
    with get_conn() as conn:
        cursor = conn.execute(
            """
            INSERT INTO users (identifier, identifier_type, password_hash, tier)
            VALUES (?, 'email', 'test-hash', 'vip')
            """,
            (f"radar-ask-worker-{token}@example.test",),
        )
        user = WorkerUsers(vip_id=int(cursor.lastrowid))

    repository = RadarAskRepository()
    yield repository, user

    with get_conn() as conn:
        conn.execute("DELETE FROM radar_ask_usage WHERE user_id=?", (user.vip_id,))
        conn.execute("DELETE FROM users WHERE id=?", (user.vip_id,))
    connection.close_all()


def queue_run(
    repository: RadarAskRepository,
    user: WorkerUsers,
    *,
    key: str,
    available_at: datetime | None = None,
):
    decision = deep_decision()
    run = repository.create_run(
        user_id=user.vip_id,
        question=f"Nghien cuu sau {key}",
        idempotency_key=key,
        requested_depth="deep",
    )
    queued = repository.transition_run(
        run.id,
        user_id=user.vip_id,
        expected={"created"},
        target="queued",
        effective_depth="deep",
        route=decision.model_dump(mode="json"),
        model="deepseek-v4-pro",
    )
    reservation_id = uuid4()
    with get_conn() as conn:
        conn.execute(
            "UPDATE radar_ask_runs SET available_at=? WHERE id=?",
            (available_at or datetime.now(timezone.utc) - timedelta(seconds=5), queued.id),
        )
        conn.execute(
            """
            INSERT INTO radar_ask_usage (
                id, run_key, user_id, tier, model, depth,
                usage_date, usage_month, settlement_status, question_status,
                reserved_usd, reservation_expires_at
            ) VALUES (
                ?, ?, ?, 'vip', 'deepseek-v4-pro', 'deep',
                ?, ?, 'reserved', 'reserved', 0.24, ?
            )
            """,
            (
                reservation_id,
                queued.id,
                user.vip_id,
                NOW.date(),
                NOW.date().replace(day=1),
                NOW + timedelta(minutes=10),
            ),
        )
    return queued, reservation_id


def deep_decision() -> RouteDecision:
    return RouteDecision(
        depth=AskDepth.DEEP,
        question_type="portfolio_research",
        tool_calls=[
            ToolCall(
                call_id="deep-market-1",
                name="rank_price_drop_areas",
                arguments={"window_days": 30, "limit": 10},
            )
        ],
        generated=True,
        use_thinking=True,
    )


def evidence_bundle() -> EvidenceBundle:
    return EvidenceBundle(
        question_snapshot="Nghien cuu sau",
        calculations={"answer_summary": "Phu My co 3 tin hieu can kiem tra."},
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
        retrieval_quality=RetrievalQuality.SUFFICIENT,
    )


def provider_answer() -> dict[str, object]:
    return {
        "answered": True,
        "depth": "deep",
        "verdict": "can_kiem_tra_them",
        "direct_answer": "Phu My co 3 tin hieu can kiem tra.",
        "claims": [
            {
                "text": "Co 3 tin hieu trong mau hien tai.",
                "evidence_ids": ["market:phu-my:drop-count"],
                "numeric_value": "3",
                "unit": "tin",
            }
        ],
        "as_of": NOW.isoformat(),
        "dataset_version": "signals:12",
    }


class ProviderSpy:
    def __init__(self, *, error: Exception | None = None, block: Event | None = None):
        self.error = error
        self.block = block
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        if self.block is not None:
            self.block.wait(timeout=2)
        if self.error is not None:
            raise self.error
        return ProviderResponse(
            content="{}",
            json_value=provider_answer(),
            usage=ProviderUsage(input_tokens=100, output_tokens=50),
        )


class FakeLimits:
    def __init__(self, *, hard_stop: bool = False):
        self.hard_stop = hard_stop
        self.settlements: list[dict[str, object]] = []

    def reserve_question(self, **kwargs):
        return UsageReservation(
            reservation_id=uuid4(),
            run_id=kwargs["run_id"],
            user_id=kwargs["user_id"],
            tier=kwargs["tier"],
            reserved_usd=Decimal("0.24"),
        )

    def settle_question(self, **kwargs):
        self.settlements.append(dict(kwargs))
        return UsageSettlement(
            reservation_id=kwargs["reservation_id"],
            outcome=kwargs["outcome"],
            actual_usd=Decimal("0"),
            question_consumed=kwargs["outcome"] in {RunOutcome.ANSWERED, RunOutcome.INSUFFICIENT},
        )

    def month_snapshot(self, **_kwargs):
        return SimpleNamespace(
            committed_plus_reserved_usd=Decimal("51" if self.hard_stop else "0")
        )


class FakeBurst:
    def check(self, **_kwargs):
        return None


def make_registry() -> ToolRegistry:
    metadata = DEFAULT_TOOL_REGISTRY.get("rank_price_drop_areas")
    return ToolRegistry(
        {
            metadata.name: ToolRegistration(
                name=metadata.name,
                description=metadata.description,
                args_model=metadata.args_model,
                handler=lambda *, args, context: evidence_bundle(),
            )
        }
    )


def worker_dependencies(repository, provider, *, enabled=True, hard_stop=False):
    settings = SimpleNamespace(
        enabled=enabled,
        allowed_tiers=frozenset({"vip"}),
        free_model="deepseek-v4-flash",
        smart_model="deepseek-v4-pro",
        deep_timeout_seconds=60,
        worker_concurrency=2,
        monthly_hard_stop_usd=Decimal("50"),
    )
    return OrchestratorDependencies(
        settings=settings,
        repository=repository,
        limits=FakeLimits(hard_stop=hard_stop),
        burst=FakeBurst(),
        router=lambda *_args, **_kwargs: deep_decision(),
        registry=make_registry(),
        provider=provider,
        clock=lambda: NOW,
    )


def test_two_workers_cannot_lease_same_run(worker_repo):
    repository, user = worker_repo
    queued, _reservation_id = queue_run(repository, user, key="exclusive")

    with ThreadPoolExecutor(max_workers=2) as executor:
        first, second = executor.map(
            lambda owner: repository.lease_next_run(worker_id=owner, lease_seconds=90),
            ("w1", "w2"),
        )

    leased = [run for run in (first, second) if run is not None]
    assert [run.id for run in leased] == [queued.id]


def test_lease_orders_available_then_created_and_only_deep(worker_repo):
    repository, user = worker_repo
    current = datetime.now(timezone.utc)
    later, _ = queue_run(repository, user, key="later", available_at=current - timedelta(minutes=1))
    earlier, _ = queue_run(repository, user, key="earlier", available_at=current - timedelta(minutes=2))
    older_created, _ = queue_run(
        repository,
        user,
        key="older-created",
        available_at=current - timedelta(seconds=30),
    )
    newer_created, _ = queue_run(
        repository,
        user,
        key="newer-created",
        available_at=current - timedelta(seconds=30),
    )
    with get_conn() as conn:
        conn.execute(
            "UPDATE radar_ask_runs SET created_at=? WHERE id=?",
            (current - timedelta(minutes=4), older_created.id),
        )
        conn.execute(
            "UPDATE radar_ask_runs SET created_at=? WHERE id=?",
            (current - timedelta(minutes=3), newer_created.id),
        )
    non_deep = repository.create_run(
        user_id=user.vip_id,
        question="Not a deep run",
        idempotency_key="not-deep",
        requested_depth="standard",
    )
    with get_conn() as conn:
        conn.execute(
            "UPDATE radar_ask_runs SET status='queued', effective_depth='standard' WHERE id=?",
            (non_deep.id,),
        )

    first = repository.lease_next_run(worker_id="ordered", lease_seconds=90)
    second = repository.lease_next_run(worker_id="ordered", lease_seconds=90)
    third = repository.lease_next_run(worker_id="ordered", lease_seconds=90)
    fourth = repository.lease_next_run(worker_id="ordered", lease_seconds=90)

    assert first is not None and first.id == earlier.id
    assert second is not None and second.id == later.id
    assert third is not None and third.id == older_created.id
    assert fourth is not None and fourth.id == newer_created.id


def test_worker_token_owns_renew_complete_and_fail(worker_repo):
    repository, user = worker_repo
    queued, _ = queue_run(repository, user, key="ownership")
    leased = repository.lease_next_run(worker_id="owner", lease_seconds=90)
    assert leased is not None

    with pytest.raises(InvalidRunTransition):
        repository.renew_lease(queued.id, worker_id="intruder", lease_seconds=90)
    renewed = repository.renew_lease(queued.id, worker_id="owner", lease_seconds=120)
    assert renewed.worker_id == "owner"
    assert renewed.lease_until is not None and renewed.lease_until > leased.lease_until

    with pytest.raises(InvalidRunTransition):
        repository.complete_leased_run(
            queued.id,
            worker_id="intruder",
            target="completed",
            outcome="answered",
            answer=provider_answer(),
        )
    completed = repository.complete_leased_run(
        queued.id,
        worker_id="owner",
        target="completed",
        outcome="answered",
        answer=provider_answer(),
    )
    assert completed.status == "completed"
    assert completed.worker_id is None and completed.lease_until is None


def test_retry_backoff_then_maximum_two_attempts_releases_reservation(worker_repo):
    repository, user = worker_repo
    queued, reservation_id = queue_run(repository, user, key="retry")
    first = repository.lease_next_run(worker_id="retry-worker", lease_seconds=90)
    assert first is not None and first.attempt_count == 1

    requeued = repository.fail_leased_run(
        queued.id,
        worker_id="retry-worker",
        outcome="provider_failure",
        error_code="provider_unavailable",
        retryable=True,
    )
    assert requeued.status == "queued"
    assert timedelta(seconds=9) <= requeued.available_at - datetime.now(timezone.utc) <= timedelta(seconds=11)

    with get_conn() as conn:
        conn.execute("UPDATE radar_ask_runs SET available_at=NOW() WHERE id=?", (queued.id,))
    second = repository.lease_next_run(worker_id="retry-worker", lease_seconds=90)
    assert second is not None and second.attempt_count == 2
    terminal = repository.fail_leased_run(
        queued.id,
        worker_id="retry-worker",
        outcome="provider_failure",
        error_code="provider_unavailable",
        retryable=True,
    )
    assert terminal.status == "failed"
    assert terminal.attempt_count == 2
    with get_conn() as conn:
        usage = conn.execute(
            "SELECT settlement_status, question_status FROM radar_ask_usage WHERE id=?",
            (reservation_id,),
        ).fetchone()
    assert tuple(usage) == ("released", "released")


def test_expired_lease_recovery_requeues_then_terminally_fails(worker_repo):
    repository, user = worker_repo
    first_run, _ = queue_run(repository, user, key="recover-one")
    second_run, second_reservation = queue_run(repository, user, key="recover-two")
    first = repository.lease_next_run(worker_id="dead-1", lease_seconds=90)
    second = repository.lease_next_run(worker_id="dead-2", lease_seconds=90)
    assert {first.id, second.id} == {first_run.id, second_run.id}
    with get_conn() as conn:
        conn.execute(
            "UPDATE radar_ask_runs SET lease_until=NOW()-INTERVAL '1 second' WHERE id=?",
            (first_run.id,),
        )
        conn.execute(
            """
            UPDATE radar_ask_runs
            SET lease_until=NOW()-INTERVAL '1 second', attempt_count=2
            WHERE id=?
            """,
            (second_run.id,),
        )

    recovered = repository.recover_expired_leases()

    assert recovered == {"requeued": 1, "failed": 1}
    with get_conn() as conn:
        states = {
            row["id"]: row["status"]
            for row in conn.execute(
                "SELECT id, status FROM radar_ask_runs WHERE id=ANY(?::uuid[])",
                ([first_run.id, second_run.id],),
            ).fetchall()
        }
        usage = conn.execute(
            "SELECT settlement_status FROM radar_ask_usage WHERE id=?",
            (second_reservation,),
        ).fetchone()
    assert states[first_run.id] == "queued"
    assert states[second_run.id] == "failed"
    assert usage["settlement_status"] == "released"


def test_recovery_terminally_fails_queued_run_with_released_reservation(worker_repo):
    repository, user = worker_repo
    queued, reservation_id = queue_run(repository, user, key="released-reservation")
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE radar_ask_usage
            SET settlement_status='released', question_status='released',
                outcome='cancelled', settled_at=NOW()
            WHERE id=?
            """,
            (reservation_id,),
        )

    recovered = repository.recover_expired_leases()

    assert recovered == {"requeued": 0, "failed": 1}
    with get_conn() as conn:
        run = conn.execute(
            "SELECT status, outcome, error_code FROM radar_ask_runs WHERE id=?",
            (queued.id,),
        ).fetchone()
    assert tuple(run) == ("failed", "cancelled", "reservation_unavailable")


def test_hard_budget_stop_happens_before_provider_and_releases(worker_repo):
    repository, user = worker_repo
    queued, reservation_id = queue_run(repository, user, key="budget-stop")
    leased = repository.lease_next_run(worker_id="budget-worker", lease_seconds=90)
    provider = ProviderSpy()
    deps = worker_dependencies(repository, provider, hard_stop=True)

    result = execute_leased_run(leased, worker_id="budget-worker", dependencies=deps)

    assert result.status is RunStatus.FAILED
    assert result.error_code == "monthly_budget_hard_stop"
    assert provider.requests == []
    with get_conn() as conn:
        usage = conn.execute(
            "SELECT settlement_status, question_status FROM radar_ask_usage WHERE id=?",
            (reservation_id,),
        ).fetchone()
    assert tuple(usage) == ("released", "released")


def test_retryable_provider_failure_requeues_same_owned_run(worker_repo):
    repository, user = worker_repo
    queued, _ = queue_run(repository, user, key="provider-retry")
    leased = repository.lease_next_run(worker_id="provider-worker", lease_seconds=90)
    provider = ProviderSpy(error=ProviderUnavailable("private detail"))
    deps = worker_dependencies(repository, provider)

    result = execute_leased_run(leased, worker_id="provider-worker", dependencies=deps)

    assert result.run_id == queued.id
    assert result.status is RunStatus.QUEUED
    assert len(provider.requests) == 1
    assert deps.limits.settlements == []


def test_successful_deep_execution_completes_owned_run_and_settles(worker_repo):
    repository, user = worker_repo
    queued, _ = queue_run(repository, user, key="provider-success")
    leased = repository.lease_next_run(worker_id="success-worker", lease_seconds=90)
    provider = ProviderSpy()
    deps = worker_dependencies(repository, provider)

    result = execute_leased_run(leased, worker_id="success-worker", dependencies=deps)

    assert result.run_id == queued.id
    assert result.status is RunStatus.COMPLETED
    assert result.answer is not None
    assert len(provider.requests) == 1
    assert deps.limits.settlements[0]["outcome"] is RunOutcome.ANSWERED
    with get_conn() as conn:
        assistant = conn.execute(
            """
            SELECT COUNT(*) AS total FROM radar_ask_messages
            WHERE session_id=? AND role='assistant'
            """,
            (queued.session_id,),
        ).fetchone()
    assert assistant["total"] == 1


def test_deep_request_only_enqueues_without_provider_call(monkeypatch):
    import app as radar_app
    import routes.radar_ask_api as ask_api
    import services.radar_ask.service as ask_service

    provider = ProviderSpy()
    repository = SimpleNamespace()
    run = SimpleNamespace(
        id=uuid4(),
        session_id=uuid4(),
        user_id=17,
        idempotency_key="deep-public",
        question="Phan tich sau lo 123",
        requested_depth="deep",
        effective_depth=None,
        status="created",
        outcome=None,
        route=None,
        answer=None,
        model=None,
        error_code=None,
        retryable=False,
    )
    transitions = []

    def create_run(**_kwargs):
        return run

    def transition_run(_run_id, **kwargs):
        transitions.append(kwargs)
        for name in ("effective_depth", "route", "model"):
            if name in kwargs:
                setattr(run, name, kwargs[name])
        run.status = kwargs["target"]
        return run

    repository.create_run = create_run
    repository.transition_run = transition_run
    deps = worker_dependencies(repository, provider)

    monkeypatch.setenv("RADAR_ASK_ENABLED", "1")
    monkeypatch.setenv("RADAR_ASK_ALLOWED_TIERS", "vip")
    monkeypatch.setattr(ask_api, "current_user", lambda: {"id": 17, "tier": "vip"})
    monkeypatch.setattr(ask_api, "current_tier", lambda: "vip")
    monkeypatch.setattr(ask_service, "_dependencies", lambda: deps)
    response = radar_app.app.test_client().post(
        "/api/radar-ask/questions",
        json={"question": "Phan tich sau lo 123", "requested_depth": "deep"},
        headers={"Idempotency-Key": "deep-public"},
    )

    assert response.status_code == 202
    assert response.get_json()["status"] == "queued"
    assert transitions[-1]["target"] == "queued"
    assert provider.requests == []


def test_feature_off_worker_refuses_before_leasing():
    repository = SimpleNamespace(lease_calls=0)

    def lease_next_run(**_kwargs):
        repository.lease_calls += 1

    repository.lease_next_run = lease_next_run
    deps = worker_dependencies(repository, ProviderSpy(), enabled=False)
    worker = RadarAskWorker(dependencies=deps, worker_id="disabled")

    with pytest.raises(RadarAskWorkerDisabled):
        worker.run_forever()
    assert repository.lease_calls == 0


def test_graceful_stop_finishes_active_run_and_does_not_lease_again():
    release_provider = Event()
    provider = ProviderSpy(block=release_provider)
    leased = SimpleNamespace(id=uuid4())

    class FakeRepository:
        def __init__(self):
            self.lease_calls = 0

        def recover_expired_leases(self):
            return {"requeued": 0, "failed": 0}

        def lease_next_run(self, **_kwargs):
            self.lease_calls += 1
            return leased if self.lease_calls == 1 else None

        def renew_lease(self, *_args, **_kwargs):
            return leased

    repository = FakeRepository()
    deps = worker_dependencies(repository, provider)
    completed = Event()

    def execute(_run, **_kwargs):
        provider.complete(SimpleNamespace())
        completed.set()

    worker = RadarAskWorker(
        dependencies=deps,
        worker_id="sigterm-worker",
        poll_seconds=0.01,
        execute_fn=execute,
    )
    thread = Thread(target=worker.run_forever)
    thread.start()
    while repository.lease_calls == 0:
        Event().wait(0.01)
    worker.request_stop()
    release_provider.set()
    thread.join(timeout=2)

    assert not thread.is_alive()
    assert completed.is_set()
    assert repository.lease_calls == 1
