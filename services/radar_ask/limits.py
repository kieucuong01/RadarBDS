"""Durable daily quota and atomic monthly cost controls for Radar Ask."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Callable
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from db.connection import PgConnection, get_conn

from .config import RadarAskSettings, VALID_TIERS
from .contracts import ProviderUsage, RunOutcome, UsageReservation, UsageSettlement
from .quota_settings import load_radar_ask_quota_settings


BANGKOK = ZoneInfo("Asia/Bangkok")
DEFAULT_RESERVATION_TTL = timedelta(minutes=10)
MONEY_QUANTUM = Decimal("0.000001")
PRICING_VERSION = "deepseek-v4-usd-2026-08-04"

# Official DeepSeek USD prices per one million tokens, checked 2026-08-04:
# https://api-docs.deepseek.com/quick_start/pricing
MODEL_PRICES_USD_PER_MILLION: dict[str, tuple[Decimal, Decimal, Decimal]] = {
    "deepseek-v4-flash": (Decimal("0.0028"), Decimal("0.14"), Decimal("0.28")),
    "deepseek-v4-pro": (Decimal("0.003625"), Decimal("0.435"), Decimal("0.87")),
}
CONSUMED_OUTCOMES = frozenset({RunOutcome.ANSWERED, RunOutcome.INSUFFICIENT})


class RadarAskLimitError(RuntimeError):
    """Base class for safe quota and budget domain failures."""


class QuotaExceeded(RadarAskLimitError):
    def __init__(self, *, tier: str, limit: int, used: int, reset_at: datetime):
        self.tier = tier
        self.limit = limit
        self.used = used
        self.reset_at = reset_at
        super().__init__("Daily Radar Ask question limit reached")


class BudgetHardStop(RadarAskLimitError):
    def __init__(self, *, projected_usd: Decimal, hard_stop_usd: Decimal):
        self.projected_usd = projected_usd
        self.hard_stop_usd = hard_stop_usd
        super().__init__("Monthly Radar Ask budget is locked")


class ReservationNotFound(RadarAskLimitError):
    """Raised when settlement references an unknown reservation UUID."""


class ReservationOwnershipConflict(RadarAskLimitError):
    """Raised when a run-key replay changes user or tier ownership."""


class ReservationUnavailable(RadarAskLimitError):
    """Raised when an idempotent run ledger cannot safely be reused."""


class UnknownModelPricing(RadarAskLimitError):
    """Raised rather than undercounting a provider model with unknown pricing."""


class PlannerUsageConflict(RadarAskLimitError):
    """A planner component may be recorded once, with exact replay allowed."""


@dataclass(frozen=True)
class BudgetWarning:
    projected_usd: Decimal
    warning_usd: Decimal


@dataclass(frozen=True)
class MonthBudgetSnapshot:
    usage_month: date
    actual_usd: Decimal
    active_reserved_usd: Decimal
    committed_plus_reserved_usd: Decimal
    warning: BudgetWarning | None


def _money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("limit clock must return a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _periods(now: datetime) -> tuple[date, date, datetime]:
    local = _aware_utc(now).astimezone(BANGKOK)
    usage_date = local.date()
    usage_month = usage_date.replace(day=1)
    next_day = datetime.combine(
        usage_date + timedelta(days=1),
        datetime.min.time(),
        tzinfo=BANGKOK,
    )
    return usage_date, usage_month, next_day


def calculate_provider_cost(model: str, usage: ProviderUsage) -> Decimal:
    """Calculate cache-aware provider cost without trusting aggregate input alone."""
    if model == "none":
        if any(
            (
                usage.input_tokens,
                usage.output_tokens,
                usage.cache_hit_input_tokens,
                usage.cache_miss_input_tokens,
            )
        ):
            raise UnknownModelPricing("deterministic runs cannot contain provider usage")
        return Decimal("0.000000")
    prices = MODEL_PRICES_USD_PER_MILLION.get(model)
    if prices is None:
        raise UnknownModelPricing("provider pricing is not configured for this model")
    hit_rate, miss_rate, output_rate = prices
    hit_tokens = int(usage.cache_hit_input_tokens)
    reported_miss = int(usage.cache_miss_input_tokens)
    unclassified = max(int(usage.input_tokens) - hit_tokens - reported_miss, 0)
    miss_tokens = reported_miss + unclassified
    million = Decimal("1000000")
    cost = (
        Decimal(hit_tokens) * hit_rate
        + Decimal(miss_tokens) * miss_rate
        + Decimal(usage.output_tokens) * output_rate
    ) / million
    return _money(cost)


class RadarAskLimitService:
    def __init__(
        self,
        *,
        settings: RadarAskSettings | None = None,
        now_fn: Callable[[], datetime] | None = None,
        reservation_ttl: timedelta = DEFAULT_RESERVATION_TTL,
    ):
        self.settings = settings or RadarAskSettings.from_env()
        self.now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        if reservation_ttl < timedelta(seconds=30) or reservation_ttl > timedelta(hours=1):
            raise ValueError("reservation_ttl must be between 30 seconds and 1 hour")
        self.reservation_ttl = reservation_ttl

    def _now(self) -> datetime:
        return _aware_utc(self.now_fn())

    @staticmethod
    def _lock(conn: PgConnection, key: str) -> None:
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(?, 0))",
            (key,),
        )

    @staticmethod
    def _release_expired(
        conn: PgConnection,
        *,
        usage_month: date,
        now: datetime,
    ) -> None:
        conn.execute(
            """
            WITH expired AS (
                SELECT
                    u.id,
                    u.reserved_usd,
                    u.planner_actual_usd
                        + COALESCE(SUM(a.actual_usd)
                            FILTER (WHERE a.recorded_at IS NOT NULL), 0) AS known_actual_usd,
                    u.planner_prompt_tokens
                        + COALESCE(SUM(a.prompt_tokens)
                            FILTER (WHERE a.recorded_at IS NOT NULL), 0) AS prompt_tokens,
                    u.planner_completion_tokens
                        + COALESCE(SUM(a.completion_tokens)
                            FILTER (WHERE a.recorded_at IS NOT NULL), 0) AS completion_tokens,
                    u.planner_cache_hit_tokens
                        + COALESCE(SUM(a.cache_hit_tokens)
                            FILTER (WHERE a.recorded_at IS NOT NULL), 0) AS cache_hit_tokens,
                    u.planner_cache_miss_tokens
                        + COALESCE(SUM(a.cache_miss_tokens)
                            FILTER (WHERE a.recorded_at IS NOT NULL), 0) AS cache_miss_tokens,
                    (
                        r.status='running'
                        AND (
                            r.worker_id LIKE 'planner:provider:%'
                            OR r.worker_id LIKE 'sync:provider:%'
                        )
                    ) AS provider_ambiguous
                FROM radar_ask_usage u
                LEFT JOIN radar_ask_runs r ON r.id=u.run_key
                LEFT JOIN radar_ask_usage_attempts a
                       ON a.reservation_id=u.id AND a.run_key=u.run_key
                WHERE u.settlement_status='reserved'
                  AND u.usage_month=?
                  AND u.reservation_expires_at <= ?
                GROUP BY u.id, r.status, r.worker_id
            )
            UPDATE radar_ask_usage u
            SET settlement_status='released',
                question_status='released',
                outcome=CASE WHEN expired.provider_ambiguous
                             THEN 'database_failure' ELSE 'cancelled' END,
                actual_usd=CASE WHEN expired.provider_ambiguous
                                THEN GREATEST(
                                    expired.reserved_usd,
                                    expired.known_actual_usd
                                )
                                ELSE expired.known_actual_usd END,
                prompt_tokens=expired.prompt_tokens,
                completion_tokens=expired.completion_tokens,
                cache_hit_tokens=expired.cache_hit_tokens,
                cache_miss_tokens=expired.cache_miss_tokens,
                settled_at=COALESCE(u.settled_at, ?),
                updated_at=?
            FROM expired
            WHERE u.id=expired.id AND u.settlement_status='reserved'
            """,
            (usage_month, now, now, now),
        )

    @staticmethod
    def _budget_totals(
        conn: PgConnection,
        *,
        usage_month: date,
        now: datetime,
    ) -> tuple[Decimal, Decimal]:
        row = conn.execute(
            """
            SELECT
                COALESCE(SUM(actual_usd), 0) AS actual_usd,
                COALESCE(SUM(
                    CASE
                        WHEN settlement_status='reserved'
                         AND reservation_expires_at > ?
                        THEN reserved_usd
                        ELSE 0
                    END
                ), 0) AS active_reserved_usd
            FROM radar_ask_usage
            WHERE usage_month=?
            """,
            (now, usage_month),
        ).fetchone()
        assert row is not None
        return _money(Decimal(row["actual_usd"])), _money(Decimal(row["active_reserved_usd"]))

    def _warning(
        self,
        projected: Decimal,
    ) -> BudgetWarning | None:
        if projected < self.settings.monthly_warning_usd:
            return None
        return BudgetWarning(
            projected_usd=_money(projected),
            warning_usd=_money(self.settings.monthly_warning_usd),
        )

    @staticmethod
    def _daily_limit(conn: PgConnection, *, tier: str) -> int | None:
        return load_radar_ask_quota_settings(conn).limit_for_tier(tier)

    @staticmethod
    def _used_daily_questions(
        conn: PgConnection,
        *,
        user_id: int,
        usage_date: date,
        now: datetime,
    ) -> int:
        used_row = conn.execute(
            """
            SELECT COUNT(*) AS used
            FROM radar_ask_usage
            WHERE user_id=? AND usage_date=?
              AND (
                question_status='answered'
                OR (
                    question_status='reserved'
                    AND settlement_status='reserved'
                    AND reservation_expires_at > ?
                )
              )
            """,
            (user_id, usage_date, now),
        ).fetchone()
        return int(used_row["used"] if used_row is not None else 0)

    @staticmethod
    def _raise_if_daily_quota_exceeded(
        conn: PgConnection,
        *,
        tier: str,
        user_id: int,
        usage_date: date,
        now: datetime,
        reset_at: datetime,
    ) -> None:
        limit = RadarAskLimitService._daily_limit(conn, tier=tier)
        if limit is None:
            return
        used = RadarAskLimitService._used_daily_questions(
            conn,
            user_id=user_id,
            usage_date=usage_date,
            now=now,
        )
        if used >= limit:
            raise QuotaExceeded(
                tier=tier,
                limit=limit,
                used=used,
                reset_at=reset_at,
            )

    def reserve_question(
        self,
        *,
        user_id: int,
        tier: str,
        run_id: UUID | str,
        max_cost_usd: Decimal,
        model: str | None = None,
        depth: str | None = None,
    ) -> UsageReservation:
        if user_id <= 0 or tier not in VALID_TIERS:
            raise ValueError("an authenticated Radar Ask tier is required")
        try:
            run_key = UUID(str(run_id))
        except (TypeError, ValueError) as exc:
            raise ValueError("run_id must be a UUID") from exc
        maximum = Decimal(max_cost_usd)
        if not maximum.is_finite() or maximum < 0 or maximum > Decimal("10"):
            raise ValueError("max_cost_usd must be between 0 and 10")
        if depth not in {None, "fast", "standard", "deep"}:
            raise ValueError("depth is invalid")
        effective_model = model or (
            self.settings.smart_model if tier in {"vip", "admin"} else self.settings.free_model
        )
        if maximum == 0 and model is None:
            effective_model = "none"
        if effective_model not in {*MODEL_PRICES_USD_PER_MILLION, "none"}:
            raise UnknownModelPricing("provider pricing is not configured for this model")

        now = self._now()
        usage_date, usage_month, reset_at = _periods(now)
        reserved = _money(maximum * self.settings.cost_safety_multiplier)
        expires_at = now + self.reservation_ttl
        # Expiry cleanup must survive a later quota/budget/unavailable rejection.
        # The admission transaction reacquires the same lock and repeats cleanup,
        # so no unlocked capacity can be consumed between these two scopes.
        with get_conn() as release_conn:
            self._lock(release_conn, f"radar_ask_budget:{usage_month:%Y-%m}")
            self._release_expired(release_conn, usage_month=usage_month, now=now)
        with get_conn() as conn:
            self._lock(conn, f"radar_ask_budget:{usage_month:%Y-%m}")
            self._release_expired(conn, usage_month=usage_month, now=now)
            self._lock(conn, f"radar_ask_quota:{user_id}:{usage_date.isoformat()}")

            existing = conn.execute(
                "SELECT * FROM radar_ask_usage WHERE run_key=?",
                (run_key,),
            ).fetchone()
            if existing is not None:
                if existing["user_id"] != user_id or existing["tier"] != tier:
                    raise ReservationOwnershipConflict(
                        "run reservation belongs to another user or tier"
                    )
                if (
                    existing["settlement_status"] == "reserved"
                    and existing["question_status"] == "reserved"
                    and existing["reservation_expires_at"] > now
                ):
                    actual, active = self._budget_totals(
                        conn,
                        usage_month=existing["usage_month"],
                        now=now,
                    )
                    return UsageReservation(
                        reservation_id=existing["id"],
                        run_id=existing["run_key"],
                        user_id=user_id,
                        tier=tier,
                        reserved_usd=existing["reserved_usd"],
                        warning_active=self._warning(actual + active) is not None,
                    )

                pristine_run = conn.execute(
                    """
                    SELECT id FROM radar_ask_runs
                    WHERE id=? AND user_id=? AND status='created'
                      AND route_json IS NULL AND answer_json IS NULL
                      AND outcome IS NULL AND worker_id IS NULL
                      AND effective_depth IS NULL AND model IS NULL
                      AND error_code IS NULL AND started_at IS NULL
                      AND attempt_count=0
                    FOR UPDATE
                    """,
                    (run_key, user_id),
                ).fetchone()
                pristine_usage = (
                    existing["settlement_status"] == "released"
                    and existing["question_status"] == "released"
                    and existing["outcome"] == RunOutcome.CANCELLED.value
                    and Decimal(existing["actual_usd"]) == 0
                    and existing["planner_recorded_at"] is None
                    and int(existing["prompt_tokens"]) == 0
                    and int(existing["completion_tokens"]) == 0
                    and int(existing["cache_hit_tokens"]) == 0
                    and int(existing["cache_miss_tokens"]) == 0
                    and existing["usage_date"] == usage_date
                    and existing["usage_month"] == usage_month
                )
                if pristine_run is None or not pristine_usage:
                    raise ReservationUnavailable(
                        "run reservation is no longer active or safely reusable"
                    )

                self._raise_if_daily_quota_exceeded(
                    conn,
                    tier=tier,
                    user_id=user_id,
                    usage_date=usage_date,
                    now=now,
                    reset_at=reset_at,
                )
                actual, active = self._budget_totals(
                    conn,
                    usage_month=usage_month,
                    now=now,
                )
                projected = _money(actual + active + reserved)
                if reserved > 0 and projected > self.settings.monthly_hard_stop_usd:
                    raise BudgetHardStop(
                        projected_usd=projected,
                        hard_stop_usd=_money(self.settings.monthly_hard_stop_usd),
                    )
                warning = self._warning(projected)
                reactivated = conn.execute(
                    """
                    UPDATE radar_ask_usage
                    SET model=?, depth=?, settlement_status='reserved',
                        question_status='reserved', reserved_usd=?, actual_usd=0,
                        pricing_version=?, reservation_expires_at=?, outcome=NULL,
                        prompt_tokens=0, completion_tokens=0,
                        cache_hit_tokens=0, cache_miss_tokens=0,
                        settled_at=NULL, updated_at=?
                    WHERE id=? AND run_key=? AND settlement_status='released'
                      AND question_status='released' AND actual_usd=0
                      AND planner_recorded_at IS NULL
                    RETURNING *
                    """,
                    (
                        effective_model,
                        depth,
                        reserved,
                        PRICING_VERSION,
                        expires_at,
                        now,
                        existing["id"],
                        run_key,
                    ),
                ).fetchone()
                if reactivated is None:
                    raise ReservationUnavailable(
                        "run reservation lost its reactivation lock"
                    )
                return UsageReservation(
                    reservation_id=reactivated["id"],
                    run_id=reactivated["run_key"],
                    user_id=user_id,
                    tier=tier,
                    reserved_usd=reactivated["reserved_usd"],
                    warning_active=warning is not None,
                )

            self._raise_if_daily_quota_exceeded(
                conn,
                tier=tier,
                user_id=user_id,
                usage_date=usage_date,
                now=now,
                reset_at=reset_at,
            )

            actual, active = self._budget_totals(
                conn,
                usage_month=usage_month,
                now=now,
            )
            projected = _money(actual + active + reserved)
            if reserved > 0 and projected > self.settings.monthly_hard_stop_usd:
                raise BudgetHardStop(
                    projected_usd=projected,
                    hard_stop_usd=_money(self.settings.monthly_hard_stop_usd),
                )
            warning = self._warning(projected)
            reservation_id = uuid4()
            conn.execute(
                """
                INSERT INTO radar_ask_usage (
                    id, run_key, user_id, tier, model, depth,
                    usage_date, usage_month, settlement_status, question_status,
                    reserved_usd, actual_usd, pricing_version,
                    reservation_expires_at, created_at, updated_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, 'reserved', 'reserved',
                    ?, 0, ?, ?, ?, ?
                )
                """,
                (
                    reservation_id,
                    run_key,
                    user_id,
                    tier,
                    effective_model,
                    depth,
                    usage_date,
                    usage_month,
                    reserved,
                    PRICING_VERSION,
                    expires_at,
                    now,
                    now,
                ),
            )
        return UsageReservation(
            reservation_id=reservation_id,
            run_id=run_key,
            user_id=user_id,
            tier=tier,  # type: ignore[arg-type]
            reserved_usd=reserved,
            warning_active=warning is not None,
        )

    def record_planner_usage(
        self,
        *,
        reservation_id: UUID | str,
        model: str,
        usage: ProviderUsage,
    ) -> None:
        """Persist one Flash planning component before any later settlement."""
        try:
            reservation_key = UUID(str(reservation_id))
        except (TypeError, ValueError) as exc:
            raise ValueError("reservation_id must be a UUID") from exc
        if model not in MODEL_PRICES_USD_PER_MILLION:
            raise UnknownModelPricing("planner pricing is not configured for this model")
        actual_usd = calculate_provider_cost(model, usage)
        now = self._now()
        with get_conn() as conn:
            period = conn.execute(
                "SELECT usage_month FROM radar_ask_usage WHERE id=?",
                (reservation_key,),
            ).fetchone()
            if period is None:
                raise ReservationNotFound("usage reservation was not found")
            self._lock(conn, f"radar_ask_budget:{period['usage_month']:%Y-%m}")
            row = conn.execute(
                "SELECT * FROM radar_ask_usage WHERE id=? FOR UPDATE",
                (reservation_key,),
            ).fetchone()
            if row is None:
                raise ReservationNotFound("usage reservation was not found")
            if row["planner_recorded_at"] is not None:
                stored = (
                    row["planner_model"],
                    row["planner_prompt_tokens"],
                    row["planner_completion_tokens"],
                    row["planner_cache_hit_tokens"],
                    row["planner_cache_miss_tokens"],
                    row["planner_actual_usd"],
                )
                expected = (
                    model,
                    usage.input_tokens,
                    usage.output_tokens,
                    usage.cache_hit_input_tokens,
                    usage.cache_miss_input_tokens,
                    actual_usd,
                )
                if stored != expected:
                    raise PlannerUsageConflict("planner usage was already recorded differently")
                return
            if row["settlement_status"] != "reserved":
                raise PlannerUsageConflict("planner usage cannot be added after settlement")
            updated = conn.execute(
                """
                UPDATE radar_ask_usage
                SET planner_model=?, planner_prompt_tokens=?,
                    planner_completion_tokens=?, planner_cache_hit_tokens=?,
                    planner_cache_miss_tokens=?, planner_actual_usd=?,
                    planner_recorded_at=?, updated_at=?
                WHERE id=?
                RETURNING *
                """,
                (
                    model,
                    usage.input_tokens,
                    usage.output_tokens,
                    usage.cache_hit_input_tokens,
                    usage.cache_miss_input_tokens,
                    actual_usd,
                    now,
                    now,
                    reservation_key,
                ),
            ).fetchone()
            if updated is None:
                raise PlannerUsageConflict("planner usage lost its reservation lock")

    def settle_question(
        self,
        *,
        reservation_id: UUID | str,
        usage: ProviderUsage,
        outcome: RunOutcome,
    ) -> UsageSettlement:
        try:
            reservation_key = UUID(str(reservation_id))
        except (TypeError, ValueError) as exc:
            raise ValueError("reservation_id must be a UUID") from exc
        normalized_outcome = outcome if isinstance(outcome, RunOutcome) else RunOutcome(outcome)
        now = self._now()
        with get_conn() as conn:
            period = conn.execute(
                "SELECT usage_month FROM radar_ask_usage WHERE id=?",
                (reservation_key,),
            ).fetchone()
            if period is None:
                raise ReservationNotFound("usage reservation was not found")
            self._lock(conn, f"radar_ask_budget:{period['usage_month']:%Y-%m}")
            row = conn.execute(
                "SELECT * FROM radar_ask_usage WHERE id=? FOR UPDATE",
                (reservation_key,),
            ).fetchone()
            if row is None:
                raise ReservationNotFound("usage reservation was not found")
            self._lock(
                conn,
                f"radar_ask_quota:{row['user_id']}:{row['usage_date'].isoformat()}",
            )
            if row["settlement_status"] != "reserved":
                stored_outcome = RunOutcome(row["outcome"] or RunOutcome.CANCELLED.value)
                return UsageSettlement(
                    reservation_id=row["id"],
                    outcome=stored_outcome,
                    actual_usd=row["actual_usd"],
                    question_consumed=row["question_status"] == "answered",
                )

            answer_usd = calculate_provider_cost(row["model"] or "none", usage)
            actual_usd = _money(Decimal(row["planner_actual_usd"]) + answer_usd)
            consumed = normalized_outcome in CONSUMED_OUTCOMES
            settlement_status = "settled" if consumed else "released"
            question_status = "answered" if consumed else "released"
            updated = conn.execute(
                """
                UPDATE radar_ask_usage
                SET settlement_status=?, question_status=?, actual_usd=?,
                    prompt_tokens=?, completion_tokens=?, cache_hit_tokens=?,
                    cache_miss_tokens=?, outcome=?, settled_at=?, updated_at=?
                WHERE id=? AND settlement_status='reserved'
                RETURNING *
                """,
                (
                    settlement_status,
                    question_status,
                    actual_usd,
                    int(row["planner_prompt_tokens"]) + usage.input_tokens,
                    int(row["planner_completion_tokens"]) + usage.output_tokens,
                    int(row["planner_cache_hit_tokens"]) + usage.cache_hit_input_tokens,
                    int(row["planner_cache_miss_tokens"]) + usage.cache_miss_input_tokens,
                    normalized_outcome.value,
                    now,
                    now,
                    reservation_key,
                ),
            ).fetchone()
            assert updated is not None
        return UsageSettlement(
            reservation_id=reservation_key,
            outcome=normalized_outcome,
            actual_usd=actual_usd,
            question_consumed=consumed,
        )

    def month_snapshot(self, *, now: datetime | None = None) -> MonthBudgetSnapshot:
        current = _aware_utc(now) if now is not None else self._now()
        _usage_date, usage_month, _reset_at = _periods(current)
        with get_conn() as conn:
            actual, active = self._budget_totals(
                conn,
                usage_month=usage_month,
                now=current,
            )
        projected = _money(actual + active)
        return MonthBudgetSnapshot(
            usage_month=usage_month,
            actual_usd=actual,
            active_reserved_usd=active,
            committed_plus_reserved_usd=projected,
            warning=self._warning(projected),
        )


def reserve_question(
    *,
    user_id: int,
    tier: str,
    run_id: UUID | str,
    max_cost_usd: Decimal,
) -> UsageReservation:
    return RadarAskLimitService().reserve_question(
        user_id=user_id,
        tier=tier,
        run_id=run_id,
        max_cost_usd=max_cost_usd,
    )


def settle_question(
    *,
    reservation_id: UUID | str,
    usage: ProviderUsage,
    outcome: RunOutcome,
) -> UsageSettlement:
    return RadarAskLimitService().settle_question(
        reservation_id=reservation_id,
        usage=usage,
        outcome=outcome,
    )
