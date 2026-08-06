from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from threading import Lock
from uuid import uuid4

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from db import connection
from db.connection import get_conn
from db.schema import init_schema
from services.radar_ask.burst import BurstExceeded, BurstLimiter
from services.radar_ask.config import RadarAskSettings
from services.radar_ask.contracts import (
    AskContext,
    AskDepth,
    AskQuestionRequest,
    ProviderUsage,
    RouteDecision,
    RunOutcome,
)
from services.radar_ask.limits import (
    BudgetHardStop,
    BudgetWarning,
    PlannerUsageConflict,
    QuotaExceeded,
    RadarAskLimitService,
    ReservationUnavailable,
    calculate_provider_cost,
)
from services.radar_ask.quota_settings import save_radar_ask_quota_settings
from services.radar_ask.orchestrator import OrchestratorDependencies, run_question
from services.radar_ask.repository import RadarAskRepository
from services.radar_ask.registry import DEFAULT_TOOL_REGISTRY


@dataclass(frozen=True)
class LimitUsers:
    free_id: int
    vip_id: int
    admin_id: int


class MutableClock:
    def __init__(self, value: datetime):
        self.value = value

    def __call__(self) -> datetime:
        return self.value


@pytest.fixture
def limit_environment():
    token = uuid4().hex
    connection.close_all()
    init_schema()
    ids: list[int] = []
    with get_conn() as conn:
        for tier in ("free", "vip", "admin"):
            cursor = conn.execute(
                """
                INSERT INTO users (identifier, identifier_type, password_hash, tier)
                VALUES (?, 'email', 'test-hash', ?)
                """,
                (f"radar-ask-limit-{tier}-{token}@example.test", tier),
            )
            ids.append(int(cursor.lastrowid))

    users = LimitUsers(*ids)
    clock = MutableClock(datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc))
    settings = replace(
        RadarAskSettings.from_env(),
        monthly_warning_usd=Decimal("20"),
        monthly_hard_stop_usd=Decimal("50"),
        cost_safety_multiplier=Decimal("2"),
    )
    service = RadarAskLimitService(settings=settings, now_fn=clock)
    yield service, users, clock, settings

    with get_conn() as conn:
        conn.execute(
            "DELETE FROM radar_ask_usage WHERE user_id IN (?, ?, ?)",
            (users.free_id, users.vip_id, users.admin_id),
        )
        conn.execute(
            "DELETE FROM users WHERE id IN (?, ?, ?)",
            (users.free_id, users.vip_id, users.admin_id),
        )
    save_radar_ask_quota_settings(free_daily_limit=5, vip_daily_limit=20, updated_by="pytest-reset")
    connection.close_all()


def _reserve(
    service: RadarAskLimitService,
    *,
    user_id: int,
    tier: str,
    max_cost: str = "0",
    model: str | None = None,
):
    return service.reserve_question(
        user_id=user_id,
        tier=tier,
        run_id=uuid4(),
        max_cost_usd=Decimal(max_cost),
        model=model,
    )


def test_schema_has_expiring_reservations_and_active_budget_index(limit_environment):
    _service, _users, _clock, _settings = limit_environment
    with get_conn() as conn:
        columns = {
            row["column_name"]
            for row in conn.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema='public' AND table_name='radar_ask_usage'
                """
            ).fetchall()
        }
        indexes = {
            row["indexname"]
            for row in conn.execute(
                """
                SELECT indexname FROM pg_indexes
                WHERE schemaname='public' AND tablename='radar_ask_usage'
                """
            ).fetchall()
        }

    assert {"reservation_expires_at", "pricing_version"} <= columns
    assert "idx_radar_ask_usage_active_reservations" in indexes


@pytest.mark.parametrize(
    ("tier", "user_field", "limit"),
    [("free", "free_id", 5), ("vip", "vip_id", 20)],
)
def test_daily_free_and_vip_limits_are_durable(limit_environment, tier, user_field, limit):
    service, users, _clock, _settings = limit_environment
    user_id = getattr(users, user_field)

    for _ in range(limit):
        _reserve(service, user_id=user_id, tier=tier)

    with pytest.raises(QuotaExceeded) as exc_info:
        _reserve(service, user_id=user_id, tier=tier)
    assert exc_info.value.limit == limit
    assert exc_info.value.used == limit


def test_daily_free_and_vip_limits_are_admin_configurable(limit_environment):
    service, users, _clock, _settings = limit_environment
    save_radar_ask_quota_settings(free_daily_limit=2, vip_daily_limit=3, updated_by="pytest")

    for _ in range(2):
        _reserve(service, user_id=users.free_id, tier="free")
    with pytest.raises(QuotaExceeded) as free_exc:
        _reserve(service, user_id=users.free_id, tier="free")
    assert free_exc.value.limit == 2

    for _ in range(3):
        _reserve(service, user_id=users.vip_id, tier="vip")
    with pytest.raises(QuotaExceeded) as vip_exc:
        _reserve(service, user_id=users.vip_id, tier="vip")
    assert vip_exc.value.limit == 3


def test_zero_daily_limit_locks_free_or_vip(limit_environment):
    service, users, _clock, _settings = limit_environment
    save_radar_ask_quota_settings(free_daily_limit=0, vip_daily_limit=20, updated_by="pytest")

    with pytest.raises(QuotaExceeded) as exc_info:
        _reserve(service, user_id=users.free_id, tier="free")

    assert exc_info.value.limit == 0
    assert exc_info.value.used == 0


def test_admin_has_no_daily_question_quota_but_usage_is_tracked(limit_environment):
    service, users, _clock, _settings = limit_environment

    for _ in range(105):
        _reserve(service, user_id=users.admin_id, tier="admin")

    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS total
            FROM radar_ask_usage
            WHERE user_id=? AND tier='admin' AND question_status='reserved'
            """,
            (users.admin_id,),
        ).fetchone()

    assert int(row["total"]) == 105


def test_daily_limit_rolls_over_at_midnight_asia_bangkok(limit_environment):
    service, users, clock, _settings = limit_environment
    clock.value = datetime(2026, 8, 4, 16, 59, tzinfo=timezone.utc)
    for _ in range(5):
        _reserve(service, user_id=users.free_id, tier="free")
    with pytest.raises(QuotaExceeded):
        _reserve(service, user_id=users.free_id, tier="free")

    clock.value = datetime(2026, 8, 4, 17, 0, tzinfo=timezone.utc)
    next_day = _reserve(service, user_id=users.free_id, tier="free")

    assert next_day.user_id == users.free_id
    with get_conn() as conn:
        dates = {
            row["usage_date"]
            for row in conn.execute(
                "SELECT usage_date FROM radar_ask_usage WHERE user_id=?",
                (users.free_id,),
            ).fetchall()
        }
    assert len(dates) == 2


@pytest.mark.parametrize(
    "outcome",
    [
        RunOutcome.CLARIFICATION,
        RunOutcome.PROVIDER_FAILURE,
        RunOutcome.VALIDATION_FAILURE,
        RunOutcome.DATABASE_FAILURE,
        RunOutcome.CANCELLED,
    ],
)
def test_non_answer_outcomes_release_daily_question(limit_environment, outcome):
    service, users, _clock, _settings = limit_environment
    reservation = _reserve(service, user_id=users.free_id, tier="free", max_cost="0.01")
    settlement = service.settle_question(
        reservation_id=reservation.reservation_id,
        usage=ProviderUsage(input_tokens=100, output_tokens=20),
        outcome=outcome,
    )

    assert settlement.question_consumed is False
    for _ in range(5):
        _reserve(service, user_id=users.free_id, tier="free")
    with pytest.raises(QuotaExceeded):
        _reserve(service, user_id=users.free_id, tier="free")


def test_grounded_insufficient_outcome_consumes_question(limit_environment):
    service, users, _clock, _settings = limit_environment
    reservation = _reserve(service, user_id=users.free_id, tier="free")
    settlement = service.settle_question(
        reservation_id=reservation.reservation_id,
        usage=ProviderUsage(),
        outcome=RunOutcome.INSUFFICIENT,
    )

    assert settlement.question_consumed is True
    for _ in range(4):
        _reserve(service, user_id=users.free_id, tier="free")
    with pytest.raises(QuotaExceeded):
        _reserve(service, user_id=users.free_id, tier="free")


def test_reservation_is_idempotent_for_same_run(limit_environment):
    service, users, _clock, _settings = limit_environment
    run_id = uuid4()
    first = service.reserve_question(
        user_id=users.free_id,
        tier="free",
        run_id=run_id,
        max_cost_usd=Decimal("0.03"),
    )
    replay = service.reserve_question(
        user_id=users.free_id,
        tier="free",
        run_id=run_id,
        max_cost_usd=Decimal("9"),
    )

    assert replay.reservation_id == first.reservation_id
    assert replay.reserved_usd == first.reserved_usd == Decimal("0.060000")
    with get_conn() as conn:
        count = conn.execute(
            "SELECT COUNT(*) AS total FROM radar_ask_usage WHERE run_key=?",
            (run_id,),
        ).fetchone()["total"]
    assert count == 1


def test_expired_pristine_created_run_replay_reactivates_under_fresh_locks(limit_environment):
    _service, users, clock, settings = limit_environment
    service = RadarAskLimitService(
        settings=settings,
        now_fn=clock,
        reservation_ttl=timedelta(seconds=30),
    )
    run = RadarAskRepository().create_run(
        user_id=users.free_id,
        question="Replay an toàn",
        idempotency_key=f"expired-replay-{uuid4()}",
    )
    first = service.reserve_question(
        user_id=users.free_id,
        tier="free",
        run_id=run.id,
        max_cost_usd=Decimal("0.03"),
        model="deepseek-v4-flash",
        depth="standard",
    )
    clock.value += timedelta(seconds=31)
    for _index in range(4):
        _reserve(service, user_id=users.free_id, tier="free")

    replay = service.reserve_question(
        user_id=users.free_id,
        tier="free",
        run_id=run.id,
        max_cost_usd=Decimal("0.04"),
        model="deepseek-v4-pro",
        depth="deep",
    )

    assert replay.reservation_id == first.reservation_id
    assert replay.reserved_usd == Decimal("0.080000")
    with pytest.raises(QuotaExceeded):
        _reserve(service, user_id=users.free_id, tier="free")
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT settlement_status, question_status, reserved_usd, model, depth,
                   outcome, actual_usd, reservation_expires_at
            FROM radar_ask_usage WHERE id=?
            """,
            (first.reservation_id,),
        ).fetchone()
    assert tuple(row)[:7] == (
        "reserved",
        "reserved",
        Decimal("0.080000"),
        "deepseek-v4-pro",
        "deep",
        None,
        Decimal("0.000000"),
    )
    assert row["reservation_expires_at"] == clock.value + timedelta(seconds=30)


def test_expired_replay_cannot_bypass_fresh_monthly_hard_stop(limit_environment):
    _service, users, clock, settings = limit_environment
    service = RadarAskLimitService(
        settings=settings,
        now_fn=clock,
        reservation_ttl=timedelta(seconds=30),
    )
    run = RadarAskRepository().create_run(
        user_id=users.admin_id,
        question="Replay qua hard stop",
        idempotency_key=f"expired-budget-{uuid4()}",
    )
    first = service.reserve_question(
        user_id=users.admin_id,
        tier="admin",
        run_id=run.id,
        max_cost_usd=Decimal("1"),
        model="deepseek-v4-pro",
        depth="standard",
    )
    clock.value += timedelta(seconds=31)
    for amount in ("10", "10", "5"):
        _reserve(service, user_id=users.admin_id, tier="admin", max_cost=amount)

    with pytest.raises(BudgetHardStop):
        service.reserve_question(
            user_id=users.admin_id,
            tier="admin",
            run_id=run.id,
            max_cost_usd=Decimal("0.01"),
            model="deepseek-v4-pro",
            depth="standard",
        )

    with get_conn() as conn:
        row = conn.execute(
            "SELECT settlement_status, question_status FROM radar_ask_usage WHERE id=?",
            (first.reservation_id,),
        ).fetchone()
        stored_run = conn.execute(
            "SELECT status FROM radar_ask_runs WHERE id=?",
            (run.id,),
        ).fetchone()
    assert tuple(row) == ("released", "released")
    assert stored_run["status"] == "created"


def test_hard_stopped_same_key_replay_cancels_created_run(limit_environment):
    _service, users, _clock, settings = limit_environment
    live_clock = MutableClock(datetime.now(timezone.utc))
    service = RadarAskLimitService(
        settings=settings,
        now_fn=live_clock,
        reservation_ttl=timedelta(seconds=30),
    )
    repository = RadarAskRepository()
    key = f"hard-stop-replay-{uuid4()}"
    request = AskQuestionRequest(question="Phân tích giá khu này")
    run = repository.create_run(
        user_id=users.admin_id,
        question=request.question,
        idempotency_key=key,
    )
    reservation = service.reserve_question(
        user_id=users.admin_id,
        tier="admin",
        run_id=run.id,
        max_cost_usd=Decimal("1"),
        model="deepseek-v4-pro",
        depth="standard",
    )
    live_clock.value += timedelta(seconds=31)
    for amount in ("10", "10", "5"):
        _reserve(service, user_id=users.admin_id, tier="admin", max_cost=amount)

    class Burst:
        def check(self, **_kwargs):
            return None

    class Provider:
        def complete(self, _request):
            raise AssertionError("hard-stopped replay must not call provider")

    decision = RouteDecision(
        depth=AskDepth.STANDARD,
        question_type="clarification",
        generated=True,
        needs_clarification=True,
        clarification_question="Bạn muốn hỏi khu nào?",
    )
    enabled_settings = replace(
        settings,
        enabled=True,
        allowed_tiers=frozenset({"free", "vip", "admin"}),
    )
    with pytest.raises(BudgetHardStop):
        run_question(
            request,
            AskContext(user_id=users.admin_id, tier="admin"),
            dependencies=OrchestratorDependencies(
                settings=enabled_settings,
                repository=repository,
                limits=service,
                burst=Burst(),
                router=lambda *_args, **_kwargs: decision,
                registry=DEFAULT_TOOL_REGISTRY,
                provider=Provider(),
                clock=live_clock,
            ),
            idempotency_key=key,
        )

    durable = repository.get_run(user_id=users.admin_id, run_id=run.id)
    assert durable is not None
    assert durable.status == "cancelled"
    assert durable.error_code == "monthly_budget_hard_stop"
    with get_conn() as conn:
        ledger = conn.execute(
            "SELECT settlement_status, question_status FROM radar_ask_usage WHERE id=?",
            (reservation.reservation_id,),
        ).fetchone()
    assert tuple(ledger) == ("released", "released")


def test_same_key_replay_reactivates_then_creates_no_duplicate_chat_messages(limit_environment):
    _service, users, _clock, settings = limit_environment
    live_clock = MutableClock(datetime.now(timezone.utc))
    service = RadarAskLimitService(
        settings=settings,
        now_fn=live_clock,
        reservation_ttl=timedelta(seconds=30),
    )
    repository = RadarAskRepository()
    key = f"reactivated-chat-{uuid4()}"
    request = AskQuestionRequest(question="Lô này là lô nào?")
    run = repository.create_run(
        user_id=users.free_id,
        question=request.question,
        idempotency_key=key,
    )
    first = service.reserve_question(
        user_id=users.free_id,
        tier="free",
        run_id=run.id,
        max_cost_usd=Decimal("0.03"),
        model="deepseek-v4-flash",
        depth="standard",
    )
    live_clock.value += timedelta(seconds=31)

    class Burst:
        def check(self, **_kwargs):
            return None

    class Provider:
        def complete(self, _request):
            raise AssertionError("clarification replay must not call provider")

    decision = RouteDecision(
        depth=AskDepth.STANDARD,
        question_type="clarification",
        generated=False,
        needs_clarification=True,
        clarification_question="Bạn vui lòng cung cấp mã tin hoặc vị trí lô đất.",
    )
    enabled_settings = replace(
        settings,
        enabled=True,
        allowed_tiers=frozenset({"free", "vip", "admin"}),
    )
    result = run_question(
        request,
        AskContext(user_id=users.free_id, tier="free"),
        dependencies=OrchestratorDependencies(
            settings=enabled_settings,
            repository=repository,
            limits=service,
            burst=Burst(),
            router=lambda *_args, **_kwargs: decision,
            registry=DEFAULT_TOOL_REGISTRY,
            provider=Provider(),
            clock=live_clock,
        ),
        idempotency_key=key,
    )

    assert result.status.value == "clarifying"
    with get_conn() as conn:
        ledger = conn.execute(
            "SELECT id, settlement_status, question_status FROM radar_ask_usage WHERE run_key=?",
            (run.id,),
        ).fetchone()
        messages = conn.execute(
            "SELECT role FROM radar_ask_messages WHERE run_id=? ORDER BY created_at",
            (run.id,),
        ).fetchall()
    assert ledger["id"] == first.reservation_id
    assert tuple(ledger)[1:] == ("released", "released")
    assert [row["role"] for row in messages] == ["user", "assistant"]


def test_expired_non_pristine_usage_is_never_reactivated(limit_environment):
    _service, users, clock, settings = limit_environment
    service = RadarAskLimitService(
        settings=settings,
        now_fn=clock,
        reservation_ttl=timedelta(seconds=30),
    )
    run = RadarAskRepository().create_run(
        user_id=users.vip_id,
        question="Planner đã tốn chi phí",
        idempotency_key=f"non-pristine-{uuid4()}",
    )
    reservation = service.reserve_question(
        user_id=users.vip_id,
        tier="vip",
        run_id=run.id,
        max_cost_usd=Decimal("0.13"),
        model="deepseek-v4-pro",
        depth="standard",
    )
    service.record_planner_usage(
        reservation_id=reservation.reservation_id,
        model="deepseek-v4-flash",
        usage=ProviderUsage(input_tokens=10, output_tokens=2),
    )
    clock.value += timedelta(seconds=31)

    with pytest.raises(ReservationUnavailable):
        service.reserve_question(
            user_id=users.vip_id,
            tier="vip",
            run_id=run.id,
            max_cost_usd=Decimal("0.13"),
            model="deepseek-v4-pro",
            depth="standard",
        )

    with get_conn() as conn:
        row = conn.execute(
            "SELECT settlement_status, actual_usd FROM radar_ask_usage WHERE id=?",
            (reservation.reservation_id,),
        ).fetchone()
    assert row["settlement_status"] == "released"
    assert row["actual_usd"] > 0


def test_warning_at_20_and_hard_stop_above_50(limit_environment):
    service, users, _clock, _settings = limit_environment
    before_warning = _reserve(
        service,
        user_id=users.admin_id,
        tier="admin",
        max_cost="9.99",
    )
    warning = _reserve(
        service,
        user_id=users.admin_id,
        tier="admin",
        max_cost="0.01",
    )
    _reserve(
        service,
        user_id=users.admin_id,
        tier="admin",
        max_cost="10",
    )
    at_limit = _reserve(
        service,
        user_id=users.admin_id,
        tier="admin",
        max_cost="5",
    )

    assert before_warning.warning_active is False
    assert warning.warning_active is True
    assert at_limit.warning_active is True
    with pytest.raises(BudgetHardStop) as exc_info:
        _reserve(
            service,
            user_id=users.admin_id,
            tier="admin",
            max_cost="0.000001",
        )
    assert exc_info.value.hard_stop_usd == Decimal("50")
    assert exc_info.value.projected_usd > Decimal("50")
    snapshot = service.month_snapshot()
    assert snapshot.committed_plus_reserved_usd == Decimal("50.000000")
    assert isinstance(snapshot.warning, BudgetWarning)


def test_budget_overrun_still_allows_zero_cost_deterministic_question(limit_environment):
    service, users, clock, _settings = limit_environment
    usage_date = clock.value.astimezone(timezone(timedelta(hours=7))).date()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO radar_ask_usage (
                id, run_key, user_id, tier, model, usage_date, usage_month,
                settlement_status, question_status, reserved_usd, actual_usd,
                outcome, reservation_expires_at
            ) VALUES (
                ?, ?, ?, 'admin', 'deepseek-v4-pro', ?, ?,
                'settled', 'answered', 0, 51,
                'answered', ?
            )
            """,
            (
                uuid4(),
                uuid4(),
                users.admin_id,
                usage_date,
                usage_date.replace(day=1),
                clock.value + timedelta(minutes=10),
            ),
        )

    reservation = _reserve(
        service,
        user_id=users.admin_id,
        tier="admin",
        max_cost="0",
    )

    assert reservation.reserved_usd == Decimal("0.000000")
    assert reservation.warning_active is True


def test_abandoned_reservation_expires_and_releases_quota_and_budget(limit_environment):
    _service, users, clock, settings = limit_environment
    service = RadarAskLimitService(
        settings=settings,
        now_fn=clock,
        reservation_ttl=timedelta(seconds=30),
    )
    first = _reserve(
        service,
        user_id=users.admin_id,
        tier="admin",
        max_cost="10",
    )
    _reserve(service, user_id=users.admin_id, tier="admin", max_cost="10")
    _reserve(service, user_id=users.admin_id, tier="admin", max_cost="5")
    assert service.month_snapshot().active_reserved_usd == Decimal("50.000000")
    with pytest.raises(BudgetHardStop):
        _reserve(service, user_id=users.admin_id, tier="admin", max_cost="0.01")

    clock.value += timedelta(seconds=31)
    replacement = _reserve(
        service,
        user_id=users.admin_id,
        tier="admin",
        max_cost="10",
    )

    assert replacement.reserved_usd == Decimal("20.000000")
    with get_conn() as conn:
        expired = conn.execute(
            "SELECT settlement_status, question_status FROM radar_ask_usage WHERE id=?",
            (first.reservation_id,),
        ).fetchone()
    assert tuple(expired) == ("released", "released")


def test_settlement_is_idempotent_and_records_first_usage_only(limit_environment):
    service, users, _clock, _settings = limit_environment
    reservation = _reserve(
        service,
        user_id=users.vip_id,
        tier="vip",
        max_cost="1",
        model="deepseek-v4-pro",
    )
    first = service.settle_question(
        reservation_id=reservation.reservation_id,
        usage=ProviderUsage(
            input_tokens=1_000_000,
            cache_hit_input_tokens=1_000_000,
            output_tokens=1_000_000,
        ),
        outcome=RunOutcome.ANSWERED,
    )
    replay = service.settle_question(
        reservation_id=reservation.reservation_id,
        usage=ProviderUsage(input_tokens=1, output_tokens=1),
        outcome=RunOutcome.CANCELLED,
    )

    assert replay == first
    assert first.actual_usd == Decimal("0.873625")
    assert first.question_consumed is True


def test_provider_cost_uses_cache_hit_miss_and_output_rates():
    usage = ProviderUsage(
        input_tokens=2_000_000,
        cache_hit_input_tokens=1_000_000,
        cache_miss_input_tokens=1_000_000,
        output_tokens=1_000_000,
    )

    assert calculate_provider_cost("deepseek-v4-flash", usage) == Decimal("0.422800")
    assert calculate_provider_cost("deepseek-v4-pro", usage) == Decimal("1.308625")


def test_concurrent_budget_reservations_never_cross_hard_stop(limit_environment):
    service, users, _clock, _settings = limit_environment

    def reserve_once(_index: int):
        try:
            return _reserve(
                service,
                user_id=users.admin_id,
                tier="admin",
                max_cost="3",
            )
        except BudgetHardStop as exc:
            return exc

    with ThreadPoolExecutor(max_workers=20) as executor:
        results = list(executor.map(reserve_once, range(20)))

    accepted = [item for item in results if not isinstance(item, BudgetHardStop)]
    assert sum(item.reserved_usd for item in accepted) <= Decimal("50")
    assert len(accepted) == 8
    assert service.month_snapshot().committed_plus_reserved_usd == Decimal("48.000000")


def test_concurrent_free_reservations_never_cross_daily_limit(limit_environment):
    service, users, _clock, _settings = limit_environment

    def reserve_once(_index: int):
        try:
            return _reserve(service, user_id=users.free_id, tier="free")
        except QuotaExceeded as exc:
            return exc

    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(reserve_once, range(10)))

    accepted = [item for item in results if not isinstance(item, QuotaExceeded)]
    assert len(accepted) == 5


def test_planner_usage_is_durable_idempotent_and_additive_to_answer_usage(limit_environment):
    service, users, _clock, _settings = limit_environment
    reservation = _reserve(
        service,
        user_id=users.vip_id,
        tier="vip",
        max_cost="0.13",
        model="deepseek-v4-pro",
    )
    planner_usage = ProviderUsage(
        input_tokens=500,
        output_tokens=75,
        cache_miss_input_tokens=500,
    )
    answer_usage = ProviderUsage(
        input_tokens=900,
        output_tokens=150,
        cache_hit_input_tokens=300,
        cache_miss_input_tokens=600,
    )

    service.record_planner_usage(
        reservation_id=reservation.reservation_id,
        model="deepseek-v4-flash",
        usage=planner_usage,
    )
    service.record_planner_usage(
        reservation_id=reservation.reservation_id,
        model="deepseek-v4-flash",
        usage=planner_usage,
    )
    settlement = service.settle_question(
        reservation_id=reservation.reservation_id,
        usage=answer_usage,
        outcome=RunOutcome.ANSWERED,
    )

    expected_cost = calculate_provider_cost("deepseek-v4-flash", planner_usage) + calculate_provider_cost(
        "deepseek-v4-pro", answer_usage
    )
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT planner_model, planner_prompt_tokens, planner_completion_tokens,
                   planner_actual_usd, prompt_tokens, completion_tokens, actual_usd
            FROM radar_ask_usage WHERE id=?
            """,
            (reservation.reservation_id,),
        ).fetchone()

    assert settlement.actual_usd == expected_cost
    assert row["planner_model"] == "deepseek-v4-flash"
    assert row["planner_prompt_tokens"] == 500
    assert row["planner_completion_tokens"] == 75
    assert row["prompt_tokens"] == 1400
    assert row["completion_tokens"] == 225
    assert row["actual_usd"] == expected_cost

    with pytest.raises(PlannerUsageConflict):
        service.record_planner_usage(
            reservation_id=reservation.reservation_id,
            model="deepseek-v4-flash",
            usage=ProviderUsage(input_tokens=1),
        )


@pytest.mark.parametrize(
    "outcome",
    [
        RunOutcome.CLARIFICATION,
        RunOutcome.INSUFFICIENT,
        RunOutcome.PROVIDER_FAILURE,
        RunOutcome.VALIDATION_FAILURE,
    ],
)
def test_planner_usage_survives_every_terminal_settlement(limit_environment, outcome):
    service, users, _clock, _settings = limit_environment
    reservation = _reserve(
        service,
        user_id=users.vip_id,
        tier="vip",
        max_cost="0.13",
        model="deepseek-v4-pro",
    )
    usage = ProviderUsage(input_tokens=100, output_tokens=20, cache_miss_input_tokens=100)
    service.record_planner_usage(
        reservation_id=reservation.reservation_id,
        model="deepseek-v4-flash",
        usage=usage,
    )

    settlement = service.settle_question(
        reservation_id=reservation.reservation_id,
        usage=ProviderUsage(),
        outcome=outcome,
    )

    assert settlement.actual_usd == calculate_provider_cost("deepseek-v4-flash", usage)
    assert settlement.question_consumed is (outcome is RunOutcome.INSUFFICIENT)


def test_expired_planned_reservation_releases_but_keeps_known_planner_cost(limit_environment):
    service, users, clock, _settings = limit_environment
    reservation = _reserve(
        service,
        user_id=users.vip_id,
        tier="vip",
        max_cost="0.13",
        model="deepseek-v4-pro",
    )
    usage = ProviderUsage(input_tokens=200, output_tokens=30, cache_miss_input_tokens=200)
    service.record_planner_usage(
        reservation_id=reservation.reservation_id,
        model="deepseek-v4-flash",
        usage=usage,
    )
    clock.value += timedelta(minutes=11)

    _reserve(service, user_id=users.admin_id, tier="admin")

    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT settlement_status, question_status, actual_usd,
                   prompt_tokens, completion_tokens
            FROM radar_ask_usage WHERE id=?
            """,
            (reservation.reservation_id,),
        ).fetchone()
    assert tuple(row) == (
        "released",
        "released",
        calculate_provider_cost("deepseek-v4-flash", usage),
        200,
        30,
    )


def test_expired_queued_retry_settles_planner_and_every_recorded_attempt_once(
    limit_environment,
):
    service, users, clock, _settings = limit_environment
    repository = RadarAskRepository()
    run = repository.create_run(
        user_id=users.vip_id,
        question="Nghiên cứu sâu khu vực",
        idempotency_key=f"expiry-attempts-{uuid4()}",
        requested_depth="deep",
    )
    reservation = service.reserve_question(
        user_id=users.vip_id,
        tier="vip",
        run_id=run.id,
        max_cost_usd=Decimal("0.12"),
        model="deepseek-v4-pro",
        depth="deep",
    )
    planner_usage = ProviderUsage(
        input_tokens=100,
        output_tokens=20,
        cache_miss_input_tokens=100,
    )
    service.record_planner_usage(
        reservation_id=reservation.reservation_id,
        model="deepseek-v4-flash",
        usage=planner_usage,
    )
    repository.transition_run(
        run.id,
        user_id=users.vip_id,
        expected={"created"},
        target="queued",
        effective_depth="deep",
        route={
            "depth": "deep",
            "question_type": "market_research",
            "tool_calls": [],
            "generated": True,
            "use_thinking": True,
        },
        model="deepseek-v4-pro",
    )
    with get_conn() as conn:
        conn.execute(
            "UPDATE radar_ask_usage SET reservation_expires_at=NOW()+INTERVAL '10 minutes' WHERE id=?",
            (reservation.reservation_id,),
        )
    leased = repository.lease_next_run(worker_id="attempt-owner", lease_seconds=90)
    assert leased is not None and leased.id == run.id
    answer_attempt_usage = ProviderUsage(
        input_tokens=200,
        output_tokens=30,
        cache_miss_input_tokens=200,
    )
    queued = repository.fail_leased_run(
        run.id,
        worker_id="attempt-owner",
        outcome=RunOutcome.PROVIDER_FAILURE.value,
        error_code="provider_unavailable",
        retryable=True,
        reservation_id=reservation.reservation_id,
        usage=answer_attempt_usage,
        lease_seconds=90,
    )
    assert queued.status == "queued"
    with get_conn() as conn:
        conn.execute(
            "UPDATE radar_ask_usage SET reservation_expires_at=? WHERE id=?",
            (clock.value - timedelta(seconds=1), reservation.reservation_id),
        )

    _reserve(service, user_id=users.admin_id, tier="admin")
    with get_conn() as conn:
        first = conn.execute(
            """
            SELECT settlement_status, question_status, outcome, actual_usd,
                   prompt_tokens, completion_tokens, cache_miss_tokens
            FROM radar_ask_usage WHERE id=?
            """,
            (reservation.reservation_id,),
        ).fetchone()

    assert tuple(first) == (
        "released",
        "released",
        "cancelled",
        Decimal("0.000133"),
        300,
        50,
        300,
    )

    _reserve(service, user_id=users.admin_id, tier="admin")
    with get_conn() as conn:
        replay = conn.execute(
            """
            SELECT settlement_status, question_status, outcome, actual_usd,
                   prompt_tokens, completion_tokens, cache_miss_tokens
            FROM radar_ask_usage WHERE id=?
            """,
            (reservation.reservation_id,),
        ).fetchone()
    assert tuple(replay) == tuple(first)


class FakeRedis:
    def __init__(self):
        self.counts: dict[str, int] = {}
        self.calls: list[tuple] = []
        self.lock = Lock()

    def eval(self, script, numkeys, key, limit, ttl):
        with self.lock:
            self.calls.append((script, numkeys, key, limit, ttl))
            count = self.counts.get(key, 0) + 1
            self.counts[key] = count
            return [1 if count <= int(limit) else 0, count]


class UnavailableRedis:
    def eval(self, *_args):
        raise RedisConnectionError("redis unavailable in test")


@pytest.mark.parametrize(
    ("tier", "limit"),
    [("free", 2), ("vip", 5), ("admin", 10)],
)
def test_redis_burst_limits_are_atomic_per_minute(tier, limit):
    redis = FakeRedis()
    limiter = BurstLimiter(redis_client=redis, clock=lambda: 1_723_000_000.0)

    for _ in range(limit):
        limiter.check(user_id=42, tier=tier)
    with pytest.raises(BurstExceeded) as exc_info:
        limiter.check(user_id=42, tier=tier)

    assert exc_info.value.limit == limit
    assert redis.calls[-1][2].startswith("radar-ask:burst:42:")
    assert redis.calls[-1][4] == 120


@pytest.mark.parametrize(
    ("tier", "fallback_limit"),
    [("free", 1), ("vip", 2), ("admin", 5)],
)
def test_redis_unavailable_uses_half_allowance_local_fail_closed(tier, fallback_limit):
    limiter = BurstLimiter(
        redis_client=UnavailableRedis(),
        clock=lambda: 1_723_000_000.0,
    )

    for _ in range(fallback_limit):
        limiter.check(user_id=77, tier=tier)
    with pytest.raises(BurstExceeded) as exc_info:
        limiter.check(user_id=77, tier=tier)

    assert exc_info.value.limit == fallback_limit
    assert exc_info.value.fallback_active is True


def test_local_fallback_resets_on_next_minute_without_database_access():
    now = [1_723_000_000.0]
    limiter = BurstLimiter(redis_client=UnavailableRedis(), clock=lambda: now[0])
    limiter.check(user_id=88, tier="free")
    with pytest.raises(BurstExceeded):
        limiter.check(user_id=88, tier="free")

    now[0] += 60
    limiter.check(user_id=88, tier="free")


def test_local_fallback_is_memory_bounded_and_fails_closed_at_capacity():
    limiter = BurstLimiter(
        redis_client=UnavailableRedis(),
        clock=lambda: 1_723_000_000.0,
        local_max_keys=2,
    )
    limiter.check(user_id=1, tier="free")
    limiter.check(user_id=2, tier="free")

    with pytest.raises(BurstExceeded) as exc_info:
        limiter.check(user_id=3, tier="free")

    assert exc_info.value.fallback_active is True
