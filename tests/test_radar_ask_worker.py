from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import subprocess
import sys
import textwrap
from threading import Event, Thread
from time import monotonic
from types import SimpleNamespace
from uuid import uuid4

import pytest
from psycopg.errors import NumericValueOutOfRange

from db import connection
from db.connection import get_conn
from db.schema import init_schema
from services.radar_ask.contracts import (
    AskContext,
    AskDepth,
    AskQuestionRequest,
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
    execute_leased_run,
    run_question,
)
from services.radar_ask.provider import ProviderUnavailable
from services.radar_ask.config import RadarAskSettings
from services.radar_ask.limits import RadarAskLimitService, calculate_provider_cost
from services.radar_ask.planner import DeepSeekTypedPlanner
from services.radar_ask.registry import DEFAULT_TOOL_REGISTRY, ToolRegistration, ToolRegistry
from services.radar_ask.repository import InvalidRunTransition, RadarAskRepository
from services.radar_ask.routing import route_question
from services.radar_ask.worker import RadarAskWorker, RadarAskWorkerDisabled


NOW = datetime(2026, 8, 5, 5, 0, tzinfo=timezone.utc)


class FakeMonotonic:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value


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
    def __init__(
        self,
        *,
        error: Exception | None = None,
        block: Event | None = None,
        cancel_on_complete: Event | None = None,
        started: Event | None = None,
    ):
        self.error = error
        self.block = block
        self.cancel_on_complete = cancel_on_complete
        self.started = started
        self.requests = []
        self.deadlines = []

    def complete(self, request):
        self.requests.append(request)
        if self.started is not None:
            self.started.set()
        if self.block is not None:
            self.block.wait(timeout=2)
        if self.error is not None:
            raise self.error
        if self.cancel_on_complete is not None:
            self.cancel_on_complete.set()
        return ProviderResponse(
            content="{}",
            json_value=provider_answer(),
            usage=ProviderUsage(input_tokens=100, output_tokens=50),
        )

    def complete_until(self, request, *, deadline):
        self.deadlines.append(deadline)
        return self.complete(request)


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
            reservation_id=leased.reservation_id,
            usage=ProviderUsage(),
        )
    completed = repository.complete_leased_run(
        queued.id,
        worker_id="owner",
        target="completed",
        outcome="answered",
        answer=provider_answer(),
        reservation_id=leased.reservation_id,
        usage=ProviderUsage(),
    )
    assert completed.status == "completed"
    assert completed.worker_id is None and completed.lease_until is None
    with get_conn() as conn:
        assistant = conn.execute(
            "SELECT run_id FROM radar_ask_messages WHERE session_id=? AND role='assistant'",
            (queued.session_id,),
        ).fetchone()
    assert assistant is not None and assistant["run_id"] == queued.id


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
        reservation_id=reservation_id,
        usage=ProviderUsage(),
        lease_seconds=90,
    )
    assert requeued.status == "queued"
    assert timedelta(seconds=9) <= requeued.available_at - datetime.now(timezone.utc) <= timedelta(seconds=11)
    with get_conn() as conn:
        first_usage = conn.execute(
            "SELECT reservation_expires_at FROM radar_ask_usage WHERE id=?",
            (reservation_id,),
        ).fetchone()
    assert first_usage["reservation_expires_at"] >= requeued.available_at + timedelta(seconds=89)

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
        reservation_id=reservation_id,
        usage=ProviderUsage(),
        lease_seconds=90,
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
    first_run, first_reservation = queue_run(repository, user, key="recover-one")
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
        first_usage = conn.execute(
            """
            SELECT u.reservation_expires_at, r.available_at
            FROM radar_ask_usage u JOIN radar_ask_runs r ON r.id=u.run_key
            WHERE u.id=?
            """,
            (first_reservation,),
        ).fetchone()
    assert states[first_run.id] == "queued"
    assert states[second_run.id] == "failed"
    assert usage["settlement_status"] == "released"
    assert first_usage["reservation_expires_at"] >= first_usage["available_at"] + timedelta(seconds=89)


def test_expired_planner_lease_fails_and_releases_without_replan_or_worker_queue(worker_repo):
    repository, user = worker_repo
    run = repository.create_run(
        user_id=user.vip_id,
        question="Câu hỏi planner bị mất phản hồi commit",
        idempotency_key="expired-planner-lease",
    )
    reservation_id = uuid4()
    now = datetime.now(timezone.utc)
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO radar_ask_usage (
                id, run_key, user_id, tier, model, depth,
                usage_date, usage_month, settlement_status, question_status,
                reserved_usd, reservation_expires_at
            ) VALUES (?, ?, ?, 'vip', 'deepseek-v4-pro', NULL,
                      ?, ?, 'reserved', 'reserved', 0.25, ?)
            """,
            (
                reservation_id,
                run.id,
                user.vip_id,
                now.date(),
                now.date().replace(day=1),
                now + timedelta(minutes=10),
            ),
        )
    claimed = repository.claim_planning(
        run.id,
        user_id=user.vip_id,
        planner_id="planner:claimed:expired",
        lease_seconds=90,
    )
    assert claimed is not None
    with get_conn() as conn:
        conn.execute(
            "UPDATE radar_ask_runs SET lease_until=NOW()-INTERVAL '1 second' WHERE id=?",
            (run.id,),
        )

    recovered = repository.recover_expired_leases()

    assert recovered == {"requeued": 0, "failed": 1}
    stored = repository.get_run(user_id=user.vip_id, run_id=run.id)
    assert stored is not None
    assert stored.status == "failed"
    assert stored.error_code == "planner_lease_expired"
    assert stored.attempt_count == 0
    assert repository.lease_next_run(worker_id="deep-worker", lease_seconds=90) is None
    with get_conn() as conn:
        ledger = conn.execute(
            """
            SELECT settlement_status, question_status, outcome, reserved_usd, actual_usd
            FROM radar_ask_usage WHERE id=?
            """,
            (reservation_id,),
        ).fetchone()
    assert ledger is not None
    assert tuple(ledger) == (
        "released",
        "released",
        "database_failure",
        Decimal("0.250000"),
        Decimal("0.000000"),
    )


def test_expired_sync_owner_fails_terminally_and_is_never_requeued_to_deep_worker(worker_repo):
    repository, user = worker_repo
    run = repository.create_run(
        user_id=user.vip_id,
        question="Sync request crashed before atomic finalize",
        idempotency_key="expired-sync-owner",
    )
    reservation_id = uuid4()
    now = datetime.now(timezone.utc)
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO radar_ask_usage (
                id, run_key, user_id, tier, model, depth,
                usage_date, usage_month, settlement_status, question_status,
                reserved_usd, reservation_expires_at
            ) VALUES (?, ?, ?, 'vip', 'deepseek-v4-pro', 'standard',
                      ?, ?, 'reserved', 'reserved', 0.25, ?)
            """,
            (
                reservation_id,
                run.id,
                user.vip_id,
                now.date(),
                now.date().replace(day=1),
                now + timedelta(minutes=10),
            ),
        )
    claimed = repository.claim_reserved_run(
        run.id,
        user_id=user.vip_id,
        owner_id="sync:claimed:expired",
        reservation_id=reservation_id,
        lease_seconds=90,
        effective_depth="standard",
        route={"depth": "standard", "question_type": "test", "tool_calls": [], "generated": True, "use_thinking": False},
        model="deepseek-v4-pro",
    )
    assert claimed is not None
    with get_conn() as conn:
        conn.execute(
            "UPDATE radar_ask_runs SET lease_until=NOW()-INTERVAL '1 second' WHERE id=?",
            (run.id,),
        )

    recovered = repository.recover_expired_leases()

    assert recovered == {"requeued": 0, "failed": 1}
    stored = repository.get_run(user_id=user.vip_id, run_id=run.id)
    assert stored is not None
    assert stored.status == "failed"
    assert stored.error_code == "sync_lease_expired"
    assert stored.attempt_count == 0
    assert repository.lease_next_run(worker_id="deep-worker", lease_seconds=90) is None
    with get_conn() as conn:
        ledger = conn.execute(
            """
            SELECT settlement_status, question_status, outcome, reserved_usd, actual_usd
            FROM radar_ask_usage WHERE id=?
            """,
            (reservation_id,),
        ).fetchone()
    assert tuple(ledger) == (
        "released",
        "released",
        "database_failure",
        Decimal("0.250000"),
        Decimal("0.000000"),
    )


@pytest.mark.parametrize("namespace", ["planner", "sync"])
def test_expired_provider_phase_conservatively_covers_ambiguous_spend(worker_repo, namespace):
    repository, user = worker_repo
    run = repository.create_run(
        user_id=user.vip_id,
        question="Provider returned while database was unavailable",
        idempotency_key=f"expired-{namespace}-provider-phase",
    )
    reservation_id = uuid4()
    now = datetime.now(timezone.utc)
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO radar_ask_usage (
                id, run_key, user_id, tier, model, depth,
                usage_date, usage_month, settlement_status, question_status,
                reserved_usd, reservation_expires_at
            ) VALUES (?, ?, ?, 'vip', 'deepseek-v4-pro', 'standard',
                      ?, ?, 'reserved', 'reserved', 0.25, ?)
            """,
            (
                reservation_id,
                run.id,
                user.vip_id,
                now.date(),
                now.date().replace(day=1),
                now + timedelta(minutes=10),
            ),
        )
    claimed_owner = f"{namespace}:claimed:expired"
    provider_owner = f"{namespace}:provider:expired"
    claimed = repository.claim_reserved_run(
        run.id,
        user_id=user.vip_id,
        owner_id=claimed_owner,
        reservation_id=reservation_id,
        lease_seconds=300,
        effective_depth="standard",
        route={
            "depth": "standard",
            "question_type": "test",
            "tool_calls": [],
            "generated": True,
            "use_thinking": False,
        },
        model="deepseek-v4-pro",
    )
    assert claimed is not None
    rotated = repository.renew_request_lease(
        run.id,
        user_id=user.vip_id,
        owner_id=claimed_owner,
        provider_owner_id=provider_owner,
        lease_seconds=300,
    )
    assert rotated.worker_id == provider_owner
    with get_conn() as conn:
        conn.execute(
            "UPDATE radar_ask_runs SET lease_until=NOW()-INTERVAL '1 second' WHERE id=?",
            (run.id,),
        )

    assert repository.recover_expired_leases() == {"requeued": 0, "failed": 1}

    with get_conn() as conn:
        ledger = conn.execute(
            """
            SELECT settlement_status, question_status, outcome, reserved_usd, actual_usd
            FROM radar_ask_usage WHERE id=?
            """,
            (reservation_id,),
        ).fetchone()
    assert tuple(ledger) == (
        "released",
        "released",
        "database_failure",
        Decimal("0.250000"),
        Decimal("0.250000"),
    )


def test_request_owner_rotation_rejects_stale_claimed_owner(worker_repo):
    repository, user = worker_repo
    run = repository.create_run(
        user_id=user.vip_id,
        question="Owner rotation",
        idempotency_key="request-owner-rotation",
    )
    reservation_id = uuid4()
    now = datetime.now(timezone.utc)
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO radar_ask_usage (
                id, run_key, user_id, tier, model, depth,
                usage_date, usage_month, settlement_status, question_status,
                reserved_usd, reservation_expires_at
            ) VALUES (?, ?, ?, 'vip', 'deepseek-v4-pro', 'standard',
                      ?, ?, 'reserved', 'reserved', 0.25, ?)
            """,
            (
                reservation_id,
                run.id,
                user.vip_id,
                now.date(),
                now.date().replace(day=1),
                now + timedelta(minutes=10),
            ),
        )
    claimed_owner = "sync:claimed:rotation"
    provider_owner = "sync:provider:rotation"
    claimed = repository.claim_reserved_run(
        run.id,
        user_id=user.vip_id,
        owner_id=claimed_owner,
        reservation_id=reservation_id,
        lease_seconds=300,
        effective_depth="standard",
        route={"depth": "standard"},
        model="deepseek-v4-pro",
    )
    assert claimed is not None
    repository.renew_request_lease(
        run.id,
        user_id=user.vip_id,
        owner_id=claimed_owner,
        provider_owner_id=provider_owner,
        lease_seconds=300,
    )

    finalize_kwargs = {
        "user_id": user.vip_id,
        "reservation_id": reservation_id,
        "target": "failed",
        "outcome": "provider_failure",
        "usage": ProviderUsage(input_tokens=10, output_tokens=2),
        "error_code": "provider_unavailable",
        "retryable": True,
    }
    with pytest.raises(InvalidRunTransition):
        repository.finalize_sync_run(
            run.id,
            owner_id=claimed_owner,
            **finalize_kwargs,
        )
    terminal = repository.finalize_sync_run(
        run.id,
        owner_id=provider_owner,
        **finalize_kwargs,
    )
    assert terminal.status == "failed"


class BarrierRequestProvider:
    def __init__(self, response: ProviderResponse):
        self.response = response
        self.started = Event()
        self.release = Event()
        self.requests = []
        self.deadlines: list[float] = []

    def complete(self, _request):
        raise AssertionError("request provider must always use an absolute deadline")

    def complete_until(self, request, *, deadline):
        self.requests.append(request)
        self.deadlines.append(deadline)
        self.started.set()
        assert self.release.wait(timeout=5)
        return self.response


def _real_request_dependencies(repository, user, provider, *, planner=None, router=None):
    settings = replace(
        RadarAskSettings.from_env(),
        enabled=True,
        allowed_tiers=frozenset({"vip"}),
        provider_timeout_seconds=120,
        deep_timeout_seconds=120,
    )
    return OrchestratorDependencies(
        settings=settings,
        repository=repository,
        limits=RadarAskLimitService(settings=settings),
        burst=FakeBurst(),
        router=router or route_question,
        registry=make_registry(),
        provider=provider,
        clock=lambda: datetime.now(timezone.utc),
        planner=planner,
    )


def test_real_planner_provider_barrier_cannot_be_recovered_during_paid_call(worker_repo):
    repository, user = worker_repo
    planner_usage = ProviderUsage(
        input_tokens=100,
        output_tokens=20,
        cache_miss_input_tokens=100,
    )
    provider = BarrierRequestProvider(
        ProviderResponse(
            json_value=RouteDecision(
                depth=AskDepth.FAST,
                question_type="clarification",
                generated=False,
                needs_clarification=True,
                clarification_question="Bạn muốn xem phường nào?",
            ).model_dump(mode="json"),
            usage=planner_usage,
        )
    )
    settings = replace(
        RadarAskSettings.from_env(),
        enabled=True,
        allowed_tiers=frozenset({"vip"}),
        provider_timeout_seconds=120,
        deep_timeout_seconds=120,
    )
    planner = DeepSeekTypedPlanner(
        settings=settings,
        provider=provider,
        registry=make_registry(),
    )
    dependencies = _real_request_dependencies(
        repository,
        user,
        provider,
        planner=planner,
    )
    outcomes: list[object] = []

    thread = Thread(
        target=lambda: outcomes.append(
            run_question(
                AskQuestionRequest(question="Khu này đang có xu hướng gì?"),
                AskContext(user_id=user.vip_id, tier="vip"),
                dependencies=dependencies,
                idempotency_key="real-planner-provider-barrier",
            )
        )
    )
    thread.start()
    assert provider.started.wait(timeout=5)

    assert repository.recover_expired_leases() == {"requeued": 0, "failed": 0}
    with get_conn() as conn:
        active = conn.execute(
            """
            SELECT id, worker_id, lease_until > NOW() AS lease_active
            FROM radar_ask_runs WHERE user_id=?
            ORDER BY created_at DESC LIMIT 1
            """,
            (user.vip_id,),
        ).fetchone()
    assert active["worker_id"].startswith("planner:provider:")
    assert active["lease_active"] is True

    provider.release.set()
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert len(outcomes) == 1 and outcomes[0].status is RunStatus.CLARIFYING
    with get_conn() as conn:
        ledger = conn.execute(
            """
            SELECT settlement_status, actual_usd, prompt_tokens, completion_tokens
            FROM radar_ask_usage u
            JOIN radar_ask_runs r ON r.id=u.run_key
            WHERE r.id=?
            """,
            (active["id"],),
        ).fetchone()
        message_count = conn.execute(
            """
            SELECT COUNT(*) AS count FROM radar_ask_messages m
            JOIN radar_ask_runs r ON r.id=m.run_id
            WHERE r.id=? AND m.role='assistant'
            """,
            (active["id"],),
        ).fetchone()["count"]
    assert tuple(ledger) == ("released", Decimal("0.000020"), 100, 20)
    assert message_count == 1
    assert len(provider.requests) == 1


def test_real_sync_provider_barrier_cannot_be_recovered_and_finalizes_exactly_once(worker_repo):
    repository, user = worker_repo
    usage = ProviderUsage(
        input_tokens=200,
        output_tokens=30,
        cache_miss_input_tokens=200,
    )
    answer = provider_answer()
    answer["depth"] = "standard"
    provider = BarrierRequestProvider(
        ProviderResponse(json_value=answer, usage=usage)
    )
    decision = RouteDecision(
        depth=AskDepth.STANDARD,
        question_type="market_research",
        tool_calls=[
            ToolCall(
                call_id="sync-barrier-1",
                name="rank_price_drop_areas",
                arguments={"window_days": 30, "limit": 10},
            )
        ],
        generated=True,
        use_thinking=False,
    )
    dependencies = _real_request_dependencies(
        repository,
        user,
        provider,
        router=lambda *_args, **_kwargs: decision,
    )
    outcomes: list[object] = []

    thread = Thread(
        target=lambda: outcomes.append(
            run_question(
                AskQuestionRequest(question="Phân tích khu này"),
                AskContext(user_id=user.vip_id, tier="vip"),
                dependencies=dependencies,
                idempotency_key="real-sync-provider-barrier",
            )
        )
    )
    thread.start()
    assert provider.started.wait(timeout=5)

    assert repository.recover_expired_leases() == {"requeued": 0, "failed": 0}
    with get_conn() as conn:
        active = conn.execute(
            """
            SELECT id, worker_id, lease_until > NOW() AS lease_active
            FROM radar_ask_runs WHERE user_id=?
            ORDER BY created_at DESC LIMIT 1
            """,
            (user.vip_id,),
        ).fetchone()
    assert active["worker_id"].startswith("sync:provider:")
    assert active["lease_active"] is True

    provider.release.set()
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert len(outcomes) == 1 and outcomes[0].status is RunStatus.COMPLETED
    with get_conn() as conn:
        ledger = conn.execute(
            """
            SELECT settlement_status, actual_usd, prompt_tokens, completion_tokens
            FROM radar_ask_usage u
            JOIN radar_ask_runs r ON r.id=u.run_key
            WHERE r.id=?
            """,
            (active["id"],),
        ).fetchone()
        message_count = conn.execute(
            """
            SELECT COUNT(*) AS count FROM radar_ask_messages m
            JOIN radar_ask_runs r ON r.id=m.run_id
            WHERE r.id=? AND m.role='assistant'
            """,
            (active["id"],),
        ).fetchone()["count"]
    assert tuple(ledger) == ("settled", Decimal("0.000113"), 200, 30)
    assert message_count == 1
    assert len(provider.requests) == 1


def test_real_total_outage_after_paid_call_recovers_provider_phase_conservatively(worker_repo):
    _repository, user = worker_repo

    class OutageRepository(RadarAskRepository):
        unavailable = True

        def get_run(self, **kwargs):
            if self.unavailable:
                raise RuntimeError("database read unavailable")
            return super().get_run(**kwargs)

        def finalize_sync_run(self, run_id, **kwargs):
            if self.unavailable:
                raise RuntimeError("database write unavailable")
            return super().finalize_sync_run(run_id, **kwargs)

    repository = OutageRepository()
    usage = ProviderUsage(
        input_tokens=200,
        output_tokens=30,
        cache_miss_input_tokens=200,
    )
    answer = provider_answer()
    answer["depth"] = "standard"
    provider = BarrierRequestProvider(ProviderResponse(json_value=answer, usage=usage))
    provider.release.set()
    decision = RouteDecision(
        depth=AskDepth.STANDARD,
        question_type="market_research",
        tool_calls=[
            ToolCall(
                call_id="outage-provider-1",
                name="rank_price_drop_areas",
                arguments={"window_days": 30, "limit": 10},
            )
        ],
        generated=True,
        use_thinking=False,
    )
    dependencies = _real_request_dependencies(
        repository,
        user,
        provider,
        router=lambda *_args, **_kwargs: decision,
    )

    with pytest.raises(RuntimeError):
        run_question(
            AskQuestionRequest(question="Phân tích khu này"),
            AskContext(user_id=user.vip_id, tier="vip"),
            dependencies=dependencies,
            idempotency_key="real-sync-total-outage-recovery",
        )

    assert len(provider.requests) == 1
    with get_conn() as conn:
        active = conn.execute(
            """
            SELECT r.id, r.status, r.worker_id, u.id AS reservation_id,
                   u.settlement_status, u.reserved_usd, u.actual_usd
            FROM radar_ask_runs r JOIN radar_ask_usage u ON u.run_key=r.id
            WHERE r.user_id=? ORDER BY r.created_at DESC LIMIT 1
            """,
            (user.vip_id,),
        ).fetchone()
    assert active["status"] == "running"
    assert active["worker_id"].startswith("sync:provider:")
    assert active["settlement_status"] == "reserved"
    assert active["actual_usd"] == Decimal("0.000000")

    repository.unavailable = False
    with get_conn() as conn:
        conn.execute(
            "UPDATE radar_ask_runs SET lease_until=NOW()-INTERVAL '1 second' WHERE id=?",
            (active["id"],),
        )
    assert repository.recover_expired_leases() == {"requeued": 0, "failed": 1}
    with get_conn() as conn:
        recovered = conn.execute(
            """
            SELECT r.status, r.outcome, r.error_code, u.settlement_status,
                   u.outcome AS usage_outcome, u.reserved_usd, u.actual_usd
            FROM radar_ask_runs r JOIN radar_ask_usage u ON u.run_key=r.id
            WHERE r.id=?
            """,
            (active["id"],),
        ).fetchone()
    assert tuple(recovered) == (
        "failed",
        "database_failure",
        "sync_lease_expired",
        "released",
        "database_failure",
        active["reserved_usd"],
        active["reserved_usd"],
    )


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
    with get_conn() as conn:
        assistant = conn.execute(
            """
            SELECT COUNT(*) AS total FROM radar_ask_messages
            WHERE session_id=? AND role='assistant'
            """,
            (queued.session_id,),
        ).fetchone()
        usage = conn.execute(
            """
            SELECT settlement_status, question_status, outcome,
                   prompt_tokens, completion_tokens, actual_usd
            FROM radar_ask_usage WHERE run_key=?
            """,
            (queued.id,),
        ).fetchone()
    assert assistant["total"] == 1
    assert tuple(usage)[:5] == ("settled", "answered", "answered", 100, 50)
    assert usage["actual_usd"] > 0


def test_deep_worker_settlement_adds_final_usage_to_persisted_planner_usage(worker_repo):
    repository, user = worker_repo
    queued, reservation_id = queue_run(repository, user, key="planner-plus-worker")
    planner_usage = ProviderUsage(
        input_tokens=400,
        output_tokens=60,
        cache_miss_input_tokens=400,
    )
    planner_cost = calculate_provider_cost("deepseek-v4-flash", planner_usage)
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE radar_ask_usage
            SET planner_model='deepseek-v4-flash', planner_prompt_tokens=?,
                planner_completion_tokens=?, planner_cache_hit_tokens=?,
                planner_cache_miss_tokens=?, planner_actual_usd=?,
                planner_recorded_at=NOW()
            WHERE id=?
            """,
            (
                planner_usage.input_tokens,
                planner_usage.output_tokens,
                planner_usage.cache_hit_input_tokens,
                planner_usage.cache_miss_input_tokens,
                planner_cost,
                reservation_id,
            ),
        )
    leased = repository.lease_next_run(worker_id="planner-worker", lease_seconds=90)
    provider = ProviderSpy()
    deps = worker_dependencies(repository, provider)

    result = execute_leased_run(leased, worker_id="planner-worker", dependencies=deps)

    assert result.status is RunStatus.COMPLETED
    final_usage = ProviderUsage(input_tokens=100, output_tokens=50)
    expected_cost = planner_cost + calculate_provider_cost("deepseek-v4-pro", final_usage)
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT prompt_tokens, completion_tokens, actual_usd, settlement_status
            FROM radar_ask_usage WHERE id=?
            """,
            (reservation_id,),
        ).fetchone()
    assert tuple(row) == (500, 110, expected_cost, "settled")


def test_lease_loss_after_provider_response_records_usage_before_terminal_failure(worker_repo):
    repository, user = worker_repo
    queued, reservation_id = queue_run(repository, user, key="lease-loss-usage")
    leased = repository.lease_next_run(worker_id="lease-loss-worker", lease_seconds=90)
    cancellation = Event()
    provider = ProviderSpy(cancel_on_complete=cancellation)
    deps = worker_dependencies(repository, provider)

    result = execute_leased_run(
        leased,
        worker_id="lease-loss-worker",
        dependencies=deps,
        cancelled=cancellation.is_set,
    )

    assert result.status is RunStatus.FAILED
    assert result.error_code == "worker_lease_lost"
    assert len(provider.deadlines) == 1
    with get_conn() as conn:
        usage = conn.execute(
            """
            SELECT settlement_status, outcome, prompt_tokens, completion_tokens, actual_usd
            FROM radar_ask_usage WHERE id=?
            """,
            (reservation_id,),
        ).fetchone()
    assert tuple(usage)[:4] == ("released", "provider_failure", 100, 50)
    assert usage["actual_usd"] > 0


def test_success_finalization_rolls_back_run_message_and_usage_together(worker_repo):
    repository, user = worker_repo
    queued, reservation_id = queue_run(repository, user, key="atomic-success")
    leased = repository.lease_next_run(worker_id="atomic-success-worker", lease_seconds=90)
    assert leased is not None
    overflowing_usage = ProviderUsage(input_tokens=10**15, output_tokens=10**15)

    with pytest.raises(NumericValueOutOfRange):
        repository.complete_leased_run(
            queued.id,
            worker_id="atomic-success-worker",
            target="completed",
            outcome="answered",
            answer=provider_answer(),
            reservation_id=reservation_id,
            usage=overflowing_usage,
        )

    with get_conn() as conn:
        run = conn.execute(
            "SELECT status, worker_id FROM radar_ask_runs WHERE id=?",
            (queued.id,),
        ).fetchone()
        messages = conn.execute(
            "SELECT COUNT(*) AS total FROM radar_ask_messages WHERE session_id=? AND role='assistant'",
            (queued.session_id,),
        ).fetchone()
        usage = conn.execute(
            "SELECT settlement_status, question_status FROM radar_ask_usage WHERE id=?",
            (reservation_id,),
        ).fetchone()
    assert tuple(run) == ("running", "atomic-success-worker")
    assert messages["total"] == 0
    assert tuple(usage) == ("reserved", "reserved")


def test_failure_finalization_rolls_back_ledger_and_run_together(worker_repo):
    repository, user = worker_repo
    queued, reservation_id = queue_run(repository, user, key="atomic-failure")
    leased = repository.lease_next_run(worker_id="atomic-failure-worker", lease_seconds=90)
    assert leased is not None
    repository.fail_leased_run(
        queued.id,
        worker_id="atomic-failure-worker",
        outcome="provider_failure",
        error_code="provider_unavailable",
        retryable=True,
        reservation_id=reservation_id,
        usage=ProviderUsage(),
        lease_seconds=90,
    )
    with get_conn() as conn:
        conn.execute("UPDATE radar_ask_runs SET available_at=NOW() WHERE id=?", (queued.id,))
    second = repository.lease_next_run(
        worker_id="atomic-failure-worker",
        lease_seconds=90,
    )
    assert second is not None and second.attempt_count == 2

    with pytest.raises(NumericValueOutOfRange):
        repository.fail_leased_run(
            queued.id,
            worker_id="atomic-failure-worker",
            outcome="provider_failure",
            error_code="provider_unavailable",
            retryable=True,
            reservation_id=reservation_id,
            usage=ProviderUsage(input_tokens=10**15, output_tokens=10**15),
            lease_seconds=90,
        )

    with get_conn() as conn:
        run = conn.execute(
            "SELECT status, worker_id FROM radar_ask_runs WHERE id=?",
            (queued.id,),
        ).fetchone()
        usage = conn.execute(
            "SELECT settlement_status, question_status FROM radar_ask_usage WHERE id=?",
            (reservation_id,),
        ).fetchone()
    assert tuple(run) == ("running", "atomic-failure-worker")
    assert tuple(usage) == ("reserved", "reserved")


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
        worker_id=None,
        lease_until=None,
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
        if run.status != "running":
            run.worker_id = None
            run.lease_until = None
        return run

    def claim_reserved_run(_run_id, **kwargs):
        run.status = "running"
        run.worker_id = kwargs["owner_id"]
        run.lease_until = NOW + timedelta(seconds=kwargs["lease_seconds"])
        for name in ("effective_depth", "route", "model"):
            if kwargs.get(name) is not None:
                setattr(run, name, kwargs[name])
        return run

    repository.create_run = create_run
    repository.get_run = lambda **_kwargs: run
    repository.claim_reserved_run = claim_reserved_run
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

        def recover_expired_leases(self, **_kwargs):
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


def test_lost_renewal_signals_active_execution_to_cancel():
    leased = SimpleNamespace(id=uuid4(), reservation_id=uuid4())
    cancelled_seen = Event()

    class LostLeaseRepository:
        def __init__(self):
            self.lease_calls = 0

        def recover_expired_leases(self, **_kwargs):
            return {"requeued": 0, "failed": 0}

        def lease_next_run(self, **_kwargs):
            self.lease_calls += 1
            return leased if self.lease_calls == 1 else None

        def renew_lease(self, *_args, **_kwargs):
            raise InvalidRunTransition("lost")

    repository = LostLeaseRepository()
    deps = worker_dependencies(repository, ProviderSpy())

    def execute(_run, *, cancelled, **_kwargs):
        while not cancelled():
            Event().wait(0.01)
        cancelled_seen.set()

    worker = RadarAskWorker(
        dependencies=deps,
        worker_id="lost-renewal-worker",
        lease_seconds=1,
        poll_seconds=0.01,
        execute_fn=execute,
    )
    thread = Thread(target=worker.run_forever)
    thread.start()
    assert cancelled_seen.wait(timeout=2)
    worker.request_stop()
    thread.join(timeout=2)

    assert not thread.is_alive()


def test_real_lost_renewal_records_attempt_usage_once_and_next_owner_settles_total(worker_repo):
    repository, user = worker_repo
    queued, reservation_id = queue_run(repository, user, key="real-lost-renewal")
    provider_started = Event()
    release_provider = Event()
    renewal_lost = Event()

    class ObservedRepository(RadarAskRepository):
        def renew_lease(self, *args, **kwargs):
            try:
                return super().renew_lease(*args, **kwargs)
            except InvalidRunTransition:
                renewal_lost.set()
                raise

    observed = ObservedRepository()
    assert callable(getattr(observed, "record_attempt_usage", None))
    provider = ProviderSpy(block=release_provider, started=provider_started)
    deps = worker_dependencies(observed, provider)
    fake_clock = FakeMonotonic()
    worker = RadarAskWorker(
        dependencies=deps,
        worker_id="combined-loss-worker",
        lease_seconds=1,
        poll_seconds=0.01,
        monotonic_fn=fake_clock,
    )
    thread = Thread(target=worker.run_forever)
    thread.start()
    assert provider_started.wait(timeout=2)

    with get_conn() as conn:
        conn.execute(
            "UPDATE radar_ask_runs SET lease_until=NOW()-INTERVAL '1 second' WHERE id=?",
            (queued.id,),
        )
    assert repository.recover_expired_leases(lease_seconds=1) == {
        "requeued": 1,
        "failed": 0,
    }
    fake_clock.value = 2.0
    assert renewal_lost.wait(timeout=2)
    release_provider.set()

    deadline = monotonic() + 2
    first_attempt = None
    while monotonic() < deadline:
        with get_conn() as conn:
            first_attempt = conn.execute(
                """
                SELECT prompt_tokens, completion_tokens, actual_usd, outcome
                FROM radar_ask_usage_attempts
                WHERE run_key=? AND attempt_count=1
                """,
                (queued.id,),
            ).fetchone()
        if first_attempt is not None and first_attempt["prompt_tokens"] == 100:
            break
        Event().wait(0.01)
    worker.request_stop()
    thread.join(timeout=2)

    assert not thread.is_alive()
    assert first_attempt is not None
    assert tuple(first_attempt)[:2] == (100, 50)
    assert first_attempt["actual_usd"] > 0
    assert first_attempt["outcome"] == "provider_failure"
    with pytest.raises(InvalidRunTransition):
        observed.record_attempt_usage(
            run_id=queued.id,
            reservation_id=reservation_id,
            attempt_count=1,
            worker_id="stale-intruder",
            usage=ProviderUsage(input_tokens=100, output_tokens=50),
            outcome="provider_failure",
        )
    with get_conn() as conn:
        first_run = conn.execute(
            "SELECT status, worker_id FROM radar_ask_runs WHERE id=?",
            (queued.id,),
        ).fetchone()
        assistant_count = conn.execute(
            "SELECT COUNT(*) AS total FROM radar_ask_messages WHERE session_id=? AND role='assistant'",
            (queued.session_id,),
        ).fetchone()
        conn.execute("UPDATE radar_ask_runs SET available_at=NOW() WHERE id=?", (queued.id,))
    assert tuple(first_run) == ("queued", None)
    assert assistant_count["total"] == 0

    second = repository.lease_next_run(worker_id="second-owner", lease_seconds=90)
    assert second is not None and second.attempt_count == 2
    second_result = execute_leased_run(
        second,
        worker_id="second-owner",
        dependencies=worker_dependencies(repository, ProviderSpy()),
    )
    assert second_result.status is RunStatus.COMPLETED

    observed.record_attempt_usage(
        run_id=queued.id,
        reservation_id=reservation_id,
        attempt_count=1,
        worker_id="combined-loss-worker",
        usage=ProviderUsage(input_tokens=100, output_tokens=50),
        outcome="provider_failure",
    )
    with get_conn() as conn:
        total = conn.execute(
            """
            SELECT prompt_tokens, completion_tokens, actual_usd, settlement_status
            FROM radar_ask_usage WHERE id=?
            """,
            (reservation_id,),
        ).fetchone()
    assert tuple(total)[:2] == (200, 100)
    assert total["actual_usd"] > first_attempt["actual_usd"]
    assert total["settlement_status"] == "settled"


def test_shutdown_drain_returns_at_active_deadline():
    leased = SimpleNamespace(id=uuid4(), reservation_id=uuid4())
    started = Event()
    release = Event()

    class FakeRepository:
        def __init__(self):
            self.lease_calls = 0

        def recover_expired_leases(self, **_kwargs):
            return {"requeued": 0, "failed": 0}

        def lease_next_run(self, **_kwargs):
            self.lease_calls += 1
            return leased if self.lease_calls == 1 else None

        def renew_lease(self, *_args, **_kwargs):
            return leased

    repository = FakeRepository()
    deps = worker_dependencies(repository, ProviderSpy())
    deps.settings.deep_timeout_seconds = 0.05

    def execute(_run, **_kwargs):
        started.set()
        release.wait(timeout=2)

    worker = RadarAskWorker(
        dependencies=deps,
        worker_id="bounded-stop-worker",
        poll_seconds=0.01,
        execute_fn=execute,
    )
    thread = Thread(target=worker.run_forever)
    thread.start()
    assert started.wait(timeout=1)
    worker.request_stop()
    thread.join(timeout=1)
    release.set()

    assert not thread.is_alive()


def test_cli_process_exits_at_deadline_with_blocked_execution():
    script = textwrap.dedent(
        """
        import sys
        from threading import Event, Timer
        from types import SimpleNamespace
        from uuid import uuid4

        import radar
        from services.radar_ask.worker import RadarAskWorker

        leased = SimpleNamespace(id=uuid4(), reservation_id=uuid4())

        class Repository:
            def __init__(self):
                self.calls = 0
            def recover_expired_leases(self, **_kwargs):
                return {"requeued": 0, "failed": 0}
            def lease_next_run(self, **_kwargs):
                self.calls += 1
                return leased if self.calls == 1 else None
            def renew_lease(self, *_args, **_kwargs):
                return leased

        dependencies = SimpleNamespace(
            settings=SimpleNamespace(
                enabled=True,
                worker_concurrency=1,
                deep_timeout_seconds=0.10,
            ),
            repository=Repository(),
        )

        def blocked(_run, **_kwargs):
            Event().wait(60)

        def command(_args):
            worker = RadarAskWorker(
                dependencies=dependencies,
                worker_id="subprocess-worker",
                poll_seconds=0.01,
                execute_fn=blocked,
            )
            Timer(0.05, worker.request_stop).start()
            worker.run_forever()

        radar.cmd_radar_ask_worker = command
        sys.argv = ["radar.py", "radar-ask-worker"]
        radar.main()
        """
    )

    completed = subprocess.run(
        [sys.executable, "-X", "utf8", "-c", script],
        capture_output=True,
        text=True,
        timeout=4,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
