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
from services.radar_ask.contracts import ProviderUsage, RunOutcome
from services.radar_ask.limits import (
    BudgetHardStop,
    BudgetWarning,
    QuotaExceeded,
    RadarAskLimitService,
    calculate_provider_cost,
)


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
    [("free", "free_id", 5), ("vip", "vip_id", 20), ("admin", "admin_id", 100)],
)
def test_daily_tier_limits_are_durable(limit_environment, tier, user_field, limit):
    service, users, _clock, _settings = limit_environment
    user_id = getattr(users, user_field)

    for _ in range(limit):
        _reserve(service, user_id=user_id, tier=tier)

    with pytest.raises(QuotaExceeded) as exc_info:
        _reserve(service, user_id=user_id, tier=tier)
    assert exc_info.value.limit == limit
    assert exc_info.value.used == limit


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
