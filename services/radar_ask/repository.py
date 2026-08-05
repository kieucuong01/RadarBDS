"""Durable, owner-scoped persistence for Radar Ask.

This module stores chat content and immutable audit records. Normal reservation
policy lives in the limit service; leased worker finalization is kept here so
the run, assistant message, and exact usage reservation commit atomically.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Collection, Mapping
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

from db.connection import PgConnection, PgRow, get_conn

from .config import RadarAskSettings
from .contracts import ProviderUsage, RunOutcome
from .limits import BANGKOK, CONSUMED_OUTCOMES, MONEY_QUANTUM, calculate_provider_cost


TERMINAL_RUN_STATUSES = frozenset({"completed", "insufficient", "failed", "cancelled"})
RUN_STATUSES = frozenset(
    {"created", "clarifying", "queued", "running", *TERMINAL_RUN_STATUSES}
)
ALLOWED_RUN_TRANSITIONS = {
    "created": frozenset({"clarifying", "queued", "running", "cancelled"}),
    "queued": frozenset({"running", "cancelled"}),
    "running": frozenset(
        {"clarifying", "completed", "insufficient", "failed", "cancelled"}
    ),
    "clarifying": frozenset(),
    "completed": frozenset(),
    "insufficient": frozenset(),
    "failed": frozenset(),
    "cancelled": frozenset(),
}
RUN_OUTCOMES = frozenset(
    {
        "answered",
        "insufficient",
        "clarification",
        "provider_failure",
        "validation_failure",
        "database_failure",
        "budget_hard_stop",
        "cancelled",
    }
)
RETENTION_BATCH_SIZE = 500
ADMIN_METRIC_WINDOWS = ("today", "last_7_days", "month")
ADMIN_MODEL_BUCKETS = frozenset({"none", "deepseek-v4-flash", "deepseek-v4-pro"})


class RadarAskRepositoryError(RuntimeError):
    """Base class for repository domain failures."""


class OwnedResourceNotFound(RadarAskRepositoryError):
    """Raised when a resource is missing or is not owned by the caller."""


class IdempotencyConflict(RadarAskRepositoryError):
    """Raised when an idempotency key is reused for different input."""


class InvalidRunTransition(RadarAskRepositoryError):
    """Raised when a guarded run-state transition cannot be applied."""


class ImmutableAuditConflict(RadarAskRepositoryError):
    """Raised when an immutable audit key is replayed with different data."""


@dataclass(frozen=True)
class RadarAskSessionRecord:
    id: UUID
    user_id: int
    title: str
    summary: dict[str, Any]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class RadarAskMessageRecord:
    id: UUID
    session_id: UUID
    run_id: UUID | None
    role: str
    content: str
    answer: dict[str, Any] | None
    created_at: datetime


@dataclass(frozen=True)
class RadarAskRunRecord:
    id: UUID
    session_id: UUID
    user_id: int
    idempotency_key: str
    question: str
    requested_depth: str | None
    effective_depth: str | None
    status: str
    outcome: str | None
    route: dict[str, Any] | None
    answer: dict[str, Any] | None
    model: str | None
    error_code: str | None
    retryable: bool
    available_at: datetime
    worker_id: str | None
    lease_until: datetime | None
    attempt_count: int
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    updated_at: datetime
    reservation_id: UUID | None = None
    tier: str | None = None
    reserved_usd: Decimal | None = None


@dataclass(frozen=True)
class RadarAskToolCallRecord:
    id: UUID
    run_id: UUID
    tool_call_key: str
    tool_name: str
    arguments: dict[str, Any]
    result_summary: dict[str, Any]
    status: str
    created_at: datetime
    completed_at: datetime | None


@dataclass(frozen=True)
class RadarAskEvidenceRecord:
    id: UUID
    run_id: UUID
    evidence_key: str
    evidence_kind: str
    source_ref: str
    payload: dict[str, Any]
    min_tier: str
    as_of: datetime
    created_at: datetime


@dataclass(frozen=True)
class RadarAskFeedbackRecord:
    id: UUID
    message_id: UUID
    user_id: int
    rating: str
    note: str | None
    created_at: datetime


def _bounded_text(value: str, *, field: str, maximum: int) -> str:
    normalized = " ".join(str(value).split())
    if not normalized or len(normalized) > maximum:
        raise ValueError(f"{field} must contain between 1 and {maximum} characters")
    return normalized


def _optional_note(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.split())
    if len(normalized) > 500:
        raise ValueError("note must not exceed 500 characters")
    return normalized or None


def _bounded_content(value: str, *, maximum: int) -> str:
    normalized = str(value).strip()
    if not normalized or len(normalized) > maximum:
        raise ValueError(f"content must contain between 1 and {maximum} characters")
    return normalized


def _row_dict(row: PgRow) -> dict[str, Any]:
    return dict(row.items())


def _admin_window() -> dict[str, Any]:
    return {
        "questions": 0,
        "runs": 0,
        "by_tier": {},
        "by_model": {},
        "by_depth": {},
        "by_outcome": {},
        "latency_ms": {"p50": None, "p95": None},
        "rates": {
            "provider_failure": 0.0,
            "validation_failure": 0.0,
            "insufficient": 0.0,
        },
        "tokens": {"input": 0, "output": 0, "cache_hit": 0, "cache_miss": 0},
        "feedback_by_question_cohort": {"helpful": 0, "not_helpful": 0},
    }


def _money_text(value: Any) -> str:
    return format(Decimal(value or 0).quantize(MONEY_QUANTUM), "f")


def _admin_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("metrics clock must be timezone-aware")
    return value.astimezone(timezone.utc)


def _session_from_row(row: PgRow) -> RadarAskSessionRecord:
    data = _row_dict(row)
    return RadarAskSessionRecord(
        id=data["id"],
        user_id=data["user_id"],
        title=data["title"],
        summary=data["summary_json"],
        created_at=data["created_at"],
        updated_at=data["updated_at"],
    )


def _message_from_row(row: PgRow) -> RadarAskMessageRecord:
    data = _row_dict(row)
    return RadarAskMessageRecord(
        id=data["id"],
        session_id=data["session_id"],
        run_id=data.get("run_id"),
        role=data["role"],
        content=data["content"],
        answer=data["answer_json"],
        created_at=data["created_at"],
    )


def _run_from_row(row: PgRow) -> RadarAskRunRecord:
    data = _row_dict(row)
    return RadarAskRunRecord(
        id=data["id"],
        session_id=data["session_id"],
        user_id=data["user_id"],
        idempotency_key=data["idempotency_key"],
        question=data["question"],
        requested_depth=data["requested_depth"],
        effective_depth=data["effective_depth"],
        status=data["status"],
        outcome=data["outcome"],
        route=data["route_json"],
        answer=data["answer_json"],
        model=data["model"],
        error_code=data["error_code"],
        retryable=data["retryable"],
        available_at=data["available_at"],
        worker_id=data["worker_id"],
        lease_until=data["lease_until"],
        attempt_count=data["attempt_count"],
        created_at=data["created_at"],
        started_at=data["started_at"],
        completed_at=data["completed_at"],
        updated_at=data["updated_at"],
        reservation_id=data.get("reservation_id"),
        tier=data.get("reservation_tier"),
        reserved_usd=data.get("reserved_usd"),
    )


def _tool_from_row(row: PgRow) -> RadarAskToolCallRecord:
    data = _row_dict(row)
    return RadarAskToolCallRecord(
        id=data["id"],
        run_id=data["run_id"],
        tool_call_key=data["tool_call_key"],
        tool_name=data["tool_name"],
        arguments=data["arguments_json"],
        result_summary=data["result_summary_json"],
        status=data["status"],
        created_at=data["created_at"],
        completed_at=data["completed_at"],
    )


def _evidence_from_row(row: PgRow) -> RadarAskEvidenceRecord:
    data = _row_dict(row)
    return RadarAskEvidenceRecord(
        id=data["id"],
        run_id=data["run_id"],
        evidence_key=data["evidence_key"],
        evidence_kind=data["evidence_kind"],
        source_ref=data["source_ref"],
        payload=data["payload_json"],
        min_tier=data["min_tier"],
        as_of=data["as_of"],
        created_at=data["created_at"],
    )


def _feedback_from_row(row: PgRow) -> RadarAskFeedbackRecord:
    data = _row_dict(row)
    return RadarAskFeedbackRecord(
        id=data["id"],
        message_id=data["message_id"],
        user_id=data["user_id"],
        rating=data["rating"],
        note=data["note"],
        created_at=data["created_at"],
    )


class RadarAskRepository:
    """PostgreSQL repository with ownership checks at every user boundary."""

    def create_session(
        self,
        *,
        user_id: int,
        title: str,
        summary: Mapping[str, Any] | None = None,
    ) -> RadarAskSessionRecord:
        normalized_title = _bounded_text(title, field="title", maximum=200)
        with get_conn() as conn:
            return self._create_session(
                conn,
                user_id=user_id,
                title=normalized_title,
                summary=dict(summary or {}),
            )

    @staticmethod
    def _create_session(
        conn: PgConnection,
        *,
        user_id: int,
        title: str,
        summary: dict[str, Any],
    ) -> RadarAskSessionRecord:
        row = conn.execute(
            """
            INSERT INTO radar_ask_sessions (id, user_id, title, summary_json)
            VALUES (?, ?, ?, ?)
            RETURNING *
            """,
            (uuid4(), user_id, title, Jsonb(summary)),
        ).fetchone()
        assert row is not None
        return _session_from_row(row)

    def get_session(self, *, user_id: int, session_id: UUID) -> RadarAskSessionRecord | None:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM radar_ask_sessions WHERE id=? AND user_id=?",
                (session_id, user_id),
            ).fetchone()
        return _session_from_row(row) if row is not None else None

    def list_sessions(
        self,
        *,
        user_id: int,
        limit: int = 20,
        before_updated_at: datetime | None = None,
        before_id: UUID | None = None,
    ) -> list[RadarAskSessionRecord]:
        """Return owner-scoped sessions in stable newest-first keyset order."""
        bounded_limit = max(1, min(int(limit), 50))
        if (before_updated_at is None) != (before_id is None):
            raise ValueError("session cursor must include timestamp and id")
        where = "user_id=?"
        params: list[Any] = [user_id]
        if before_updated_at is not None and before_id is not None:
            where += " AND (updated_at < ? OR (updated_at = ? AND id < ?))"
            params.extend((before_updated_at, before_updated_at, before_id))
        params.append(bounded_limit)
        with get_conn() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM radar_ask_sessions
                WHERE {where}
                ORDER BY updated_at DESC, id DESC
                LIMIT ?
                """,
                tuple(params),
            ).fetchall()
        return [_session_from_row(row) for row in rows]

    def rename_session(
        self,
        *,
        user_id: int,
        session_id: UUID,
        title: str,
    ) -> RadarAskSessionRecord | None:
        normalized = _bounded_text(title, field="title", maximum=200)
        with get_conn() as conn:
            row = conn.execute(
                """
                UPDATE radar_ask_sessions
                SET title=?, updated_at=NOW()
                WHERE id=? AND user_id=?
                RETURNING *
                """,
                (normalized, session_id, user_id),
            ).fetchone()
        return _session_from_row(row) if row is not None else None

    def create_message(
        self,
        *,
        user_id: int,
        session_id: UUID,
        role: str,
        content: str,
        answer: Mapping[str, Any] | None = None,
        run_id: UUID | None = None,
    ) -> RadarAskMessageRecord:
        if role not in {"user", "assistant"}:
            raise ValueError("role must be user or assistant")
        normalized = _bounded_content(content, maximum=12_000)
        with get_conn() as conn:
            row = conn.execute(
                """
                INSERT INTO radar_ask_messages (id, session_id, run_id, role, content, answer_json)
                SELECT ?, s.id, ?, ?, ?, ?
                FROM radar_ask_sessions s
                WHERE s.id=? AND s.user_id=?
                  AND (?::uuid IS NULL OR EXISTS (SELECT 1 FROM radar_ask_runs r WHERE r.id=? AND r.session_id=s.id AND r.user_id=s.user_id))
                RETURNING *
                """,
                (
                    uuid4(),
                    run_id,
                    role,
                    normalized,
                    Jsonb(dict(answer)) if answer is not None else None,
                    session_id,
                    user_id,
                    run_id,
                    run_id,
                ),
            ).fetchone()
            if row is None:
                raise OwnedResourceNotFound("session was not found")
            conn.execute(
                "UPDATE radar_ask_sessions SET updated_at=NOW() WHERE id=? AND user_id=?",
                (session_id, user_id),
            )
        return _message_from_row(row)

    def list_messages(
        self,
        *,
        user_id: int,
        session_id: UUID,
        limit: int = 50,
        before_created_at: datetime | None = None,
        before_id: UUID | None = None,
    ) -> list[RadarAskMessageRecord]:
        bounded_limit = max(1, min(int(limit), 100))
        if (before_created_at is None) != (before_id is None):
            raise ValueError("message cursor must include timestamp and id")
        with get_conn() as conn:
            owned = conn.execute(
                "SELECT 1 FROM radar_ask_sessions WHERE id=? AND user_id=?",
                (session_id, user_id),
            ).fetchone()
            if owned is None:
                raise OwnedResourceNotFound("session was not found")
            where = "session_id=?"
            params: list[Any] = [session_id]
            if before_created_at is not None and before_id is not None:
                where += " AND (created_at < ? OR (created_at = ? AND id < ?))"
                params.extend((before_created_at, before_created_at, before_id))
            params.append(bounded_limit)
            rows = conn.execute(
                f"""
                SELECT *
                FROM (
                SELECT * FROM radar_ask_messages
                    WHERE {where}
                    ORDER BY created_at DESC, id DESC
                    LIMIT ?
                ) recent
                ORDER BY created_at, id
                """,
                tuple(params),
            ).fetchall()
        return [_message_from_row(row) for row in rows]

    def add_feedback(
        self,
        *,
        user_id: int,
        message_id: UUID,
        rating: str,
        note: str | None = None,
    ) -> RadarAskFeedbackRecord:
        if rating not in {"helpful", "not_helpful"}:
            raise ValueError("rating must be helpful or not_helpful")
        normalized_note = _optional_note(note)
        with get_conn() as conn:
            owned = conn.execute(
                """
                SELECT 1
                FROM radar_ask_messages m
                JOIN radar_ask_sessions s ON s.id=m.session_id
                WHERE m.id=? AND s.user_id=? AND m.role='assistant'
                """,
                (message_id, user_id),
            ).fetchone()
            if owned is None:
                raise OwnedResourceNotFound("assistant message was not found")
            row = conn.execute(
                """
                INSERT INTO radar_ask_feedback (id, message_id, user_id, rating, note)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (user_id, message_id)
                DO UPDATE SET rating=EXCLUDED.rating, note=EXCLUDED.note
                RETURNING *
                """,
                (uuid4(), message_id, user_id, rating, normalized_note),
            ).fetchone()
        assert row is not None
        return _feedback_from_row(row)

    def create_run(
        self,
        *,
        user_id: int,
        question: str,
        idempotency_key: str,
        session_id: UUID | None = None,
        requested_depth: str | None = None,
    ) -> RadarAskRunRecord:
        normalized_question = _bounded_text(question, field="question", maximum=2_000)
        normalized_key = _bounded_text(
            idempotency_key,
            field="idempotency_key",
            maximum=128,
        )
        if requested_depth not in {None, "fast", "standard", "deep"}:
            raise ValueError("requested_depth is invalid")

        with get_conn() as conn:
            existing = conn.execute(
                "SELECT * FROM radar_ask_runs WHERE user_id=? AND idempotency_key=?",
                (user_id, normalized_key),
            ).fetchone()
            if existing is not None:
                return self._resolve_idempotent_run(existing, normalized_question)

            if session_id is None:
                session = self._create_session(
                    conn,
                    user_id=user_id,
                    title=normalized_question[:200],
                    summary={},
                )
                owned_session_id = session.id
            else:
                owned = conn.execute(
                    "SELECT id FROM radar_ask_sessions WHERE id=? AND user_id=?",
                    (session_id, user_id),
                ).fetchone()
                if owned is None:
                    raise OwnedResourceNotFound("session was not found")
                owned_session_id = session_id

            row = conn.execute(
                """
                INSERT INTO radar_ask_runs (
                    id, session_id, user_id, idempotency_key, question, requested_depth
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT (user_id, idempotency_key) DO NOTHING
                RETURNING *
                """,
                (
                    uuid4(),
                    owned_session_id,
                    user_id,
                    normalized_key,
                    normalized_question,
                    requested_depth,
                ),
            ).fetchone()
            if row is None:
                row = conn.execute(
                    "SELECT * FROM radar_ask_runs WHERE user_id=? AND idempotency_key=?",
                    (user_id, normalized_key),
                ).fetchone()
                assert row is not None
                return self._resolve_idempotent_run(row, normalized_question)
            conn.execute(
                """
                INSERT INTO radar_ask_messages (id, session_id, run_id, role, content)
                VALUES (?, ?, ?, 'user', ?)
                """,
                (uuid4(), owned_session_id, row["id"], normalized_question),
            )
            conn.execute(
                "UPDATE radar_ask_sessions SET updated_at=NOW() WHERE id=? AND user_id=?",
                (owned_session_id, user_id),
            )
        return _run_from_row(row)

    @staticmethod
    def _resolve_idempotent_run(row: PgRow, question: str) -> RadarAskRunRecord:
        if row["question"] != question:
            raise IdempotencyConflict("idempotency key belongs to a different question")
        return _run_from_row(row)

    def get_run(self, *, user_id: int, run_id: UUID) -> RadarAskRunRecord | None:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM radar_ask_runs WHERE id=? AND user_id=?",
                (run_id, user_id),
            ).fetchone()
        return _run_from_row(row) if row is not None else None

    def claim_planning(
        self,
        run_id: UUID,
        *,
        user_id: int,
        planner_id: str,
        lease_seconds: int = 90,
    ) -> RadarAskRunRecord | None:
        """Atomically grant one bounded planner lease after reservation."""
        owner = _bounded_text(planner_id, field="planner_id", maximum=128)
        if not owner.startswith("planner:"):
            raise ValueError("planner_id must use the planner namespace")
        duration = int(lease_seconds)
        if not 1 <= duration <= 300:
            raise ValueError("lease_seconds must be between 1 and 300")
        with get_conn() as conn:
            row = conn.execute(
                """
                UPDATE radar_ask_runs r
                SET status='running', worker_id=?,
                    lease_until=NOW() + (? || ' seconds')::interval,
                    started_at=COALESCE(started_at, NOW()),
                    retryable=FALSE, error_code=NULL, updated_at=NOW()
                FROM radar_ask_usage u
                WHERE r.id=? AND r.user_id=? AND r.status='created'
                  AND r.route_json IS NULL
                  AND u.run_key=r.id AND u.settlement_status='reserved'
                RETURNING r.*
                """,
                (owner, duration, run_id, user_id),
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                """
                UPDATE radar_ask_usage
                SET reservation_expires_at=GREATEST(reservation_expires_at, ?),
                    updated_at=NOW()
                WHERE run_key=? AND settlement_status='reserved'
                """,
                (row["lease_until"], run_id),
            )
        return _run_from_row(row)

    @staticmethod
    def _record_planner_component(
        conn: PgConnection,
        *,
        ledger: PgRow,
        planner_model: str,
        usage: ProviderUsage,
    ) -> None:
        actual_usd = calculate_provider_cost(planner_model, usage)
        expected = (
            planner_model,
            usage.input_tokens,
            usage.output_tokens,
            usage.cache_hit_input_tokens,
            usage.cache_miss_input_tokens,
            actual_usd,
        )
        if ledger["planner_recorded_at"] is not None:
            stored = (
                ledger["planner_model"],
                ledger["planner_prompt_tokens"],
                ledger["planner_completion_tokens"],
                ledger["planner_cache_hit_tokens"],
                ledger["planner_cache_miss_tokens"],
                ledger["planner_actual_usd"],
            )
            if stored != expected:
                raise InvalidRunTransition(
                    "planner usage was already recorded differently"
                )
            return
        if ledger["settlement_status"] != "reserved":
            raise InvalidRunTransition("planner reservation is unavailable")
        updated = conn.execute(
            """
            UPDATE radar_ask_usage
            SET planner_model=?, planner_prompt_tokens=?,
                planner_completion_tokens=?, planner_cache_hit_tokens=?,
                planner_cache_miss_tokens=?, planner_actual_usd=?,
                planner_recorded_at=NOW(), updated_at=NOW()
            WHERE id=? AND run_key=? AND settlement_status='reserved'
              AND planner_recorded_at IS NULL
            RETURNING *
            """,
            (
                *expected,
                ledger["id"],
                ledger["run_key"],
            ),
        ).fetchone()
        if updated is None:
            raise InvalidRunTransition("planner usage lost its reservation lock")

    def finalize_planning(
        self,
        run_id: UUID,
        *,
        user_id: int,
        planner_id: str,
        reservation_id: UUID,
        planner_model: str,
        answer_model: str,
        effective_depth: str,
        route: Mapping[str, Any],
        usage: ProviderUsage,
        target: str,
    ) -> RadarAskRunRecord:
        """Persist the validated route and billed planner result under its lease."""
        owner = _bounded_text(planner_id, field="planner_id", maximum=128)
        if not owner.startswith("planner:"):
            raise ValueError("planner_id must use the planner namespace")
        if effective_depth not in {"fast", "standard", "deep"}:
            raise ValueError("effective_depth is invalid")
        if target not in {"running", "queued"}:
            raise ValueError("planning target is invalid")
        if (target == "queued") != (effective_depth == "deep"):
            raise ValueError("only Deep planning may be queued")
        normalized_planner_model = _bounded_text(
            planner_model,
            field="planner_model",
            maximum=120,
        )
        normalized_answer_model = _bounded_text(
            answer_model,
            field="answer_model",
            maximum=120,
        )
        route_payload = dict(route)
        with get_conn() as conn:
            current = conn.execute(
                """
                SELECT * FROM radar_ask_runs
                WHERE id=? AND user_id=? AND status='running'
                  AND worker_id=? AND lease_until > NOW()
                FOR UPDATE
                """,
                (run_id, user_id, owner),
            ).fetchone()
            if current is None:
                raise InvalidRunTransition("planning lease is not owned by this request")
            ledger = self._lock_usage_ledger(
                conn,
                run_id=run_id,
                reservation_id=reservation_id,
            )
            self._record_planner_component(
                conn,
                ledger=ledger,
                planner_model=normalized_planner_model,
                usage=usage,
            )
            row = conn.execute(
                """
                UPDATE radar_ask_runs
                SET status=?, effective_depth=?, route_json=?, model=?,
                    worker_id=CASE WHEN ?='queued' THEN NULL ELSE worker_id END,
                    lease_until=CASE WHEN ?='queued' THEN NULL ELSE lease_until END,
                    retryable=FALSE, error_code=NULL, updated_at=NOW()
                WHERE id=? AND user_id=? AND status='running' AND worker_id=?
                  AND lease_until > NOW()
                RETURNING *
                """,
                (
                    target,
                    effective_depth,
                    Jsonb(route_payload),
                    normalized_answer_model,
                    target,
                    target,
                    run_id,
                    user_id,
                    owner,
                ),
            ).fetchone()
            if row is None:
                raise InvalidRunTransition("planning handoff lost its lease")
        return _run_from_row(row)

    def fail_planning(
        self,
        run_id: UUID,
        *,
        user_id: int,
        planner_id: str,
        reservation_id: UUID,
        planner_model: str,
        usage: ProviderUsage,
        outcome: str,
        error_code: str,
        retryable: bool,
    ) -> RadarAskRunRecord:
        """Atomically account known planner usage and terminate its owned lease."""
        owner = _bounded_text(planner_id, field="planner_id", maximum=128)
        if not owner.startswith("planner:"):
            raise ValueError("planner_id must use the planner namespace")
        if outcome not in {"provider_failure", "validation_failure", "database_failure"}:
            raise ValueError("planning failure outcome is invalid")
        normalized_error = _bounded_text(error_code, field="error_code", maximum=80)
        normalized_model = _bounded_text(
            planner_model,
            field="planner_model",
            maximum=120,
        )
        with get_conn() as conn:
            current = conn.execute(
                """
                SELECT * FROM radar_ask_runs
                WHERE id=? AND user_id=? AND status='running'
                  AND worker_id=? AND lease_until > NOW()
                FOR UPDATE
                """,
                (run_id, user_id, owner),
            ).fetchone()
            if current is None:
                raise InvalidRunTransition("planning lease is not owned by this request")
            ledger = self._lock_usage_ledger(
                conn,
                run_id=run_id,
                reservation_id=reservation_id,
            )
            self._record_planner_component(
                conn,
                ledger=ledger,
                planner_model=normalized_model,
                usage=usage,
            )
            row = conn.execute(
                """
                UPDATE radar_ask_runs
                SET status='failed', outcome=?, error_code=?, retryable=?,
                    worker_id=NULL, lease_until=NULL,
                    completed_at=COALESCE(completed_at, NOW()), updated_at=NOW()
                WHERE id=? AND user_id=? AND status='running' AND worker_id=?
                RETURNING *
                """,
                (outcome, normalized_error, bool(retryable), run_id, user_id, owner),
            ).fetchone()
            if row is None:
                raise InvalidRunTransition("planning failure lost its lease")
            self._settle_leased_usage(
                conn,
                run_id=run_id,
                reservation_id=reservation_id,
                outcome=outcome,
            )
        return _run_from_row(row)

    def lease_next_run(
        self,
        *,
        worker_id: str,
        lease_seconds: int = 90,
    ) -> RadarAskRunRecord | None:
        """Lease one ready Deep run with PostgreSQL as the concurrency authority."""
        owner = _bounded_text(worker_id, field="worker_id", maximum=128)
        duration = int(lease_seconds)
        if not 1 <= duration <= 300:
            raise ValueError("lease_seconds must be between 1 and 300")
        with get_conn() as conn:
            leased = conn.execute(
                """
                WITH candidate AS (
                    SELECT r.id
                    FROM radar_ask_runs r
                    JOIN radar_ask_usage u ON u.run_key=r.id
                    WHERE r.status='queued'
                      AND r.effective_depth='deep'
                      AND r.available_at <= NOW()
                      AND r.attempt_count < 2
                      AND u.settlement_status='reserved'
                    ORDER BY r.available_at, r.created_at
                    FOR UPDATE OF r, u SKIP LOCKED
                    LIMIT 1
                )
                UPDATE radar_ask_runs r
                SET status='running', worker_id=?,
                    lease_until=NOW() + (? || ' seconds')::interval,
                    attempt_count=attempt_count + 1,
                    started_at=COALESCE(started_at, NOW()),
                    retryable=FALSE, error_code=NULL, updated_at=NOW()
                FROM candidate
                WHERE r.id=candidate.id
                RETURNING r.id, r.lease_until, r.attempt_count
                """,
                (owner, duration),
            ).fetchone()
            if leased is None:
                return None
            conn.execute(
                """
                UPDATE radar_ask_usage
                SET reservation_expires_at=GREATEST(reservation_expires_at, ?),
                    updated_at=NOW()
                WHERE run_key=? AND settlement_status='reserved'
                """,
                (leased["lease_until"], leased["id"]),
            )
            conn.execute(
                """
                INSERT INTO radar_ask_usage_attempts (
                    id, reservation_id, run_key, attempt_count, worker_id, model
                )
                SELECT ?, u.id, u.run_key, ?, ?, COALESCE(u.model, 'none')
                FROM radar_ask_usage u
                WHERE u.run_key=? AND u.settlement_status='reserved'
                ON CONFLICT (run_key, attempt_count) DO NOTHING
                """,
                (uuid4(), leased["attempt_count"], owner, leased["id"]),
            )
            attempt = conn.execute(
                """
                SELECT worker_id FROM radar_ask_usage_attempts
                WHERE run_key=? AND attempt_count=?
                """,
                (leased["id"], leased["attempt_count"]),
            ).fetchone()
            if attempt is None or attempt["worker_id"] != owner:
                raise InvalidRunTransition("run attempt ownership could not be recorded")
            row = conn.execute(
                """
                SELECT r.*, u.id AS reservation_id,
                       u.tier AS reservation_tier, u.reserved_usd
                FROM radar_ask_runs r
                JOIN radar_ask_usage u ON u.run_key=r.id
                WHERE r.id=? AND r.worker_id=? AND r.status='running'
                  AND u.settlement_status='reserved'
                """,
                (leased["id"], owner),
            ).fetchone()
        assert row is not None
        return _run_from_row(row)

    def renew_lease(
        self,
        run_id: UUID,
        *,
        worker_id: str,
        lease_seconds: int = 90,
    ) -> RadarAskRunRecord:
        owner = _bounded_text(worker_id, field="worker_id", maximum=128)
        duration = int(lease_seconds)
        if not 1 <= duration <= 300:
            raise ValueError("lease_seconds must be between 1 and 300")
        with get_conn() as conn:
            row = conn.execute(
                """
                UPDATE radar_ask_runs
                SET lease_until=NOW() + (? || ' seconds')::interval,
                    updated_at=NOW()
                WHERE id=? AND status='running' AND worker_id=?
                  AND lease_until > NOW()
                RETURNING *
                """,
                (duration, run_id, owner),
            ).fetchone()
            if row is None:
                raise InvalidRunTransition("run lease is not owned by this worker")
            conn.execute(
                """
                UPDATE radar_ask_usage
                SET reservation_expires_at=GREATEST(reservation_expires_at, ?),
                    updated_at=NOW()
                WHERE run_key=? AND settlement_status='reserved'
                """,
                (row["lease_until"], run_id),
            )
        return _run_from_row(row)

    def complete_leased_run(
        self,
        run_id: UUID,
        *,
        worker_id: str,
        target: str,
        outcome: str,
        answer: Mapping[str, Any],
        reservation_id: UUID,
        usage: ProviderUsage,
    ) -> RadarAskRunRecord:
        owner = _bounded_text(worker_id, field="worker_id", maximum=128)
        if target not in {"completed", "insufficient"}:
            raise ValueError("leased completion target is invalid")
        if outcome not in {"answered", "insufficient"}:
            raise ValueError("leased completion outcome is invalid")
        answer_payload = dict(answer)
        content = _bounded_content(answer_payload.get("direct_answer", ""), maximum=12_000)
        with get_conn() as conn:
            row = conn.execute(
                """
                UPDATE radar_ask_runs
                SET status=?, outcome=?, answer_json=?, retryable=FALSE,
                    error_code=NULL, worker_id=NULL, lease_until=NULL,
                    completed_at=COALESCE(completed_at, NOW()), updated_at=NOW()
                WHERE id=? AND status='running' AND worker_id=?
                  AND lease_until > NOW()
                RETURNING *
                """,
                (target, outcome, Jsonb(answer_payload), run_id, owner),
            ).fetchone()
            if row is None:
                raise InvalidRunTransition("run lease is not owned by this worker")
            conn.execute(
                """
                INSERT INTO radar_ask_messages (id, session_id, run_id, role, content, answer_json)
                VALUES (?, ?, ?, 'assistant', ?, ?)
                """,
                (uuid4(), row["session_id"], row["id"], content, Jsonb(answer_payload)),
            )
            conn.execute(
                "UPDATE radar_ask_sessions SET updated_at=NOW() WHERE id=?",
                (row["session_id"],),
            )
            self._settle_leased_usage(
                conn,
                run_id=run_id,
                reservation_id=reservation_id,
                outcome=outcome,
                attempt_count=int(row["attempt_count"]),
                worker_id=owner,
                usage=usage,
            )
        return _run_from_row(row)

    def fail_leased_run(
        self,
        run_id: UUID,
        *,
        worker_id: str,
        outcome: str,
        error_code: str,
        retryable: bool,
        reservation_id: UUID,
        usage: ProviderUsage,
        lease_seconds: int = 90,
    ) -> RadarAskRunRecord:
        """Requeue a retryable first attempt or terminally fail the owned lease."""
        owner = _bounded_text(worker_id, field="worker_id", maximum=128)
        if outcome not in RUN_OUTCOMES - {"answered", "insufficient", "clarification"}:
            raise ValueError("leased failure outcome is invalid")
        normalized_error = _bounded_text(error_code, field="error_code", maximum=80)
        if not normalized_error.replace("_", "").isalnum() or normalized_error.lower() != normalized_error:
            raise ValueError("error_code must contain lowercase letters, digits, or underscores")
        grace = int(lease_seconds)
        if not 1 <= grace <= 300:
            raise ValueError("lease_seconds must be between 1 and 300")
        with get_conn() as conn:
            current = conn.execute(
                """
                SELECT * FROM radar_ask_runs
                WHERE id=? AND status='running' AND worker_id=?
                  AND lease_until > NOW()
                FOR UPDATE
                """,
                (run_id, owner),
            ).fetchone()
            if current is None:
                raise InvalidRunTransition("run lease is not owned by this worker")
            should_retry = bool(retryable) and int(current["attempt_count"]) < 2
            if should_retry:
                delay = 10 if int(current["attempt_count"]) == 1 else 30
                self._lock_usage_ledger(
                    conn,
                    run_id=run_id,
                    reservation_id=reservation_id,
                )
                self._record_attempt_usage(
                    conn,
                    run_id=run_id,
                    reservation_id=reservation_id,
                    attempt_count=int(current["attempt_count"]),
                    worker_id=owner,
                    usage=usage,
                    outcome=outcome,
                )
                extended = conn.execute(
                    """
                    UPDATE radar_ask_usage
                    SET reservation_expires_at=GREATEST(
                            reservation_expires_at,
                            NOW() + (? || ' seconds')::interval
                        ),
                        updated_at=NOW()
                    WHERE id=? AND run_key=? AND settlement_status='reserved'
                    RETURNING *
                    """,
                    (delay + grace, reservation_id, run_id),
                ).fetchone()
                if extended is None:
                    raise InvalidRunTransition("run reservation is unavailable for retry")
                row = conn.execute(
                    """
                    UPDATE radar_ask_runs
                    SET status='queued', outcome=NULL, error_code=?, retryable=TRUE,
                        available_at=NOW() + (? || ' seconds')::interval,
                        worker_id=NULL, lease_until=NULL, updated_at=NOW()
                    WHERE id=? AND status='running' AND worker_id=?
                    RETURNING *
                    """,
                    (normalized_error, delay, run_id, owner),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    UPDATE radar_ask_runs
                    SET status='failed', outcome=?, error_code=?, retryable=FALSE,
                        worker_id=NULL, lease_until=NULL,
                        completed_at=COALESCE(completed_at, NOW()), updated_at=NOW()
                    WHERE id=? AND status='running' AND worker_id=?
                    RETURNING *
                    """,
                    (outcome, normalized_error, run_id, owner),
                ).fetchone()
                self._settle_leased_usage(
                    conn,
                    run_id=run_id,
                    reservation_id=reservation_id,
                    outcome=outcome,
                    attempt_count=int(current["attempt_count"]),
                    worker_id=owner,
                    usage=usage,
                )
        assert row is not None
        return _run_from_row(row)

    def record_attempt_usage(
        self,
        *,
        run_id: UUID,
        reservation_id: UUID,
        attempt_count: int,
        worker_id: str,
        usage: ProviderUsage,
        outcome: str,
    ) -> None:
        """Record cost for one immutable lease attempt without finalizing its run."""
        owner = _bounded_text(worker_id, field="worker_id", maximum=128)
        attempt = int(attempt_count)
        if attempt not in {1, 2}:
            raise ValueError("attempt_count must be 1 or 2")
        if outcome not in RUN_OUTCOMES:
            raise ValueError("attempt outcome is invalid")
        with get_conn() as conn:
            self._lock_usage_ledger(
                conn,
                run_id=run_id,
                reservation_id=reservation_id,
            )
            self._record_attempt_usage(
                conn,
                run_id=run_id,
                reservation_id=reservation_id,
                attempt_count=attempt,
                worker_id=owner,
                usage=usage,
                outcome=outcome,
            )

    @staticmethod
    def _record_attempt_usage(
        conn: PgConnection,
        *,
        run_id: UUID,
        reservation_id: UUID,
        attempt_count: int,
        worker_id: str,
        usage: ProviderUsage,
        outcome: str,
    ) -> None:
        normalized_outcome = RunOutcome(outcome)
        attempt = conn.execute(
            """
            SELECT * FROM radar_ask_usage_attempts
            WHERE reservation_id=? AND run_key=? AND attempt_count=? AND worker_id=?
            FOR UPDATE
            """,
            (reservation_id, run_id, attempt_count, worker_id),
        ).fetchone()
        if attempt is None:
            raise InvalidRunTransition("run attempt is not owned by this worker")
        actual_usd = calculate_provider_cost(attempt["model"], usage)
        if attempt["recorded_at"] is not None:
            expected = (
                usage.input_tokens,
                usage.output_tokens,
                usage.cache_hit_input_tokens,
                usage.cache_miss_input_tokens,
                actual_usd,
                normalized_outcome.value,
            )
            stored = (
                attempt["prompt_tokens"],
                attempt["completion_tokens"],
                attempt["cache_hit_tokens"],
                attempt["cache_miss_tokens"],
                attempt["actual_usd"],
                attempt["outcome"],
            )
            if stored != expected:
                raise InvalidRunTransition("run attempt usage was already recorded differently")
            return

        updated = conn.execute(
            """
            UPDATE radar_ask_usage_attempts
            SET prompt_tokens=?, completion_tokens=?, cache_hit_tokens=?,
                cache_miss_tokens=?, actual_usd=?, outcome=?, recorded_at=NOW()
            WHERE reservation_id=? AND run_key=? AND attempt_count=?
              AND worker_id=? AND recorded_at IS NULL
            RETURNING *
            """,
            (
                usage.input_tokens,
                usage.output_tokens,
                usage.cache_hit_input_tokens,
                usage.cache_miss_input_tokens,
                actual_usd,
                normalized_outcome.value,
                reservation_id,
                run_id,
                attempt_count,
                worker_id,
            ),
        ).fetchone()
        if updated is None:
            raise InvalidRunTransition("run attempt usage lost its lock")

        # If another owner already settled the run, append this late cost once.
        conn.execute(
            """
            UPDATE radar_ask_usage
            SET actual_usd=actual_usd+?, prompt_tokens=prompt_tokens+?,
                completion_tokens=completion_tokens+?,
                cache_hit_tokens=cache_hit_tokens+?,
                cache_miss_tokens=cache_miss_tokens+?, updated_at=NOW()
            WHERE id=? AND run_key=? AND settlement_status<>'reserved'
            """,
            (
                actual_usd,
                usage.input_tokens,
                usage.output_tokens,
                usage.cache_hit_input_tokens,
                usage.cache_miss_input_tokens,
                reservation_id,
                run_id,
            ),
        )

    @staticmethod
    def _lock_usage_ledger(
        conn: PgConnection,
        *,
        run_id: UUID,
        reservation_id: UUID,
    ) -> PgRow:
        period = conn.execute(
            """
            SELECT usage_month FROM radar_ask_usage
            WHERE id=? AND run_key=?
            """,
            (reservation_id, run_id),
        ).fetchone()
        if period is None:
            raise InvalidRunTransition("run reservation was not found")
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(?, 0))",
            (f"radar_ask_budget:{period['usage_month']:%Y-%m}",),
        )
        ledger = conn.execute(
            "SELECT * FROM radar_ask_usage WHERE id=? AND run_key=? FOR UPDATE",
            (reservation_id, run_id),
        ).fetchone()
        if ledger is None:
            raise InvalidRunTransition("run reservation was not found")
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(?, 0))",
            (f"radar_ask_quota:{ledger['user_id']}:{ledger['usage_date'].isoformat()}",),
        )
        return ledger

    def _settle_leased_usage(
        self,
        conn: PgConnection,
        *,
        run_id: UUID,
        reservation_id: UUID,
        outcome: str,
        attempt_count: int | None = None,
        worker_id: str | None = None,
        usage: ProviderUsage | None = None,
    ) -> None:
        normalized_outcome = RunOutcome(outcome)
        ledger = self._lock_usage_ledger(
            conn,
            run_id=run_id,
            reservation_id=reservation_id,
        )
        if ledger["settlement_status"] != "reserved":
            if ledger["outcome"] == normalized_outcome.value:
                return
            raise InvalidRunTransition("run reservation was already settled differently")

        if attempt_count is not None:
            assert worker_id is not None and usage is not None
            self._record_attempt_usage(
                conn,
                run_id=run_id,
                reservation_id=reservation_id,
                attempt_count=attempt_count,
                worker_id=worker_id,
                usage=usage,
                outcome=outcome,
            )
        totals = conn.execute(
            """
            SELECT COALESCE(SUM(actual_usd), 0) AS actual_usd,
                   COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                   COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                   COALESCE(SUM(cache_hit_tokens), 0) AS cache_hit_tokens,
                   COALESCE(SUM(cache_miss_tokens), 0) AS cache_miss_tokens
            FROM radar_ask_usage_attempts
            WHERE reservation_id=? AND run_key=? AND recorded_at IS NOT NULL
            """,
            (reservation_id, run_id),
        ).fetchone()
        assert totals is not None
        consumed = normalized_outcome in CONSUMED_OUTCOMES
        settlement_status = "settled" if consumed else "released"
        question_status = "answered" if consumed else "released"
        updated = conn.execute(
            """
            UPDATE radar_ask_usage
            SET settlement_status=?, question_status=?, actual_usd=?,
                prompt_tokens=?, completion_tokens=?, cache_hit_tokens=?,
                cache_miss_tokens=?, outcome=?, settled_at=NOW(), updated_at=NOW()
            WHERE id=? AND run_key=? AND settlement_status='reserved'
            RETURNING *
            """,
            (
                settlement_status,
                question_status,
                Decimal(ledger["planner_actual_usd"])
                + Decimal(totals["actual_usd"]),
                int(ledger["planner_prompt_tokens"]) + int(totals["prompt_tokens"]),
                int(ledger["planner_completion_tokens"])
                + int(totals["completion_tokens"]),
                int(ledger["planner_cache_hit_tokens"])
                + int(totals["cache_hit_tokens"]),
                int(ledger["planner_cache_miss_tokens"])
                + int(totals["cache_miss_tokens"]),
                normalized_outcome.value,
                reservation_id,
                run_id,
            ),
        ).fetchone()
        if updated is None:
            raise InvalidRunTransition("run reservation settlement lost its lock")

    def recover_expired_leases(self, *, lease_seconds: int = 90) -> dict[str, int]:
        """Recover crashed workers without allowing a third attempt or orphaned hold."""
        grace = int(lease_seconds)
        if not 1 <= grace <= 300:
            raise ValueError("lease_seconds must be between 1 and 300")
        counts = {"requeued": 0, "failed": 0}
        with get_conn() as conn:
            expired_planners = conn.execute(
                """
                SELECT * FROM radar_ask_runs
                WHERE status='running' AND worker_id LIKE 'planner:%'
                  AND lease_until <= NOW()
                ORDER BY lease_until, created_at
                FOR UPDATE SKIP LOCKED
                """
            ).fetchall()
            for current in expired_planners:
                conn.execute(
                    """
                    UPDATE radar_ask_runs
                    SET status='failed', outcome='database_failure',
                        error_code='planner_lease_expired', retryable=FALSE,
                        worker_id=NULL, lease_until=NULL,
                        completed_at=COALESCE(completed_at, NOW()), updated_at=NOW()
                    WHERE id=? AND status='running' AND worker_id LIKE 'planner:%'
                      AND lease_until <= NOW()
                    """,
                    (current["id"],),
                )
                reservation = conn.execute(
                    """
                    SELECT id FROM radar_ask_usage
                    WHERE run_key=? AND settlement_status='reserved'
                    """,
                    (current["id"],),
                ).fetchone()
                if reservation is not None:
                    self._settle_leased_usage(
                        conn,
                        run_id=current["id"],
                        reservation_id=reservation["id"],
                        outcome="database_failure",
                    )
                counts["failed"] += 1

            unavailable = conn.execute(
                """
                UPDATE radar_ask_runs r
                SET status='failed', outcome='cancelled',
                    error_code='reservation_unavailable', retryable=FALSE,
                    worker_id=NULL, lease_until=NULL,
                    completed_at=COALESCE(completed_at, NOW()), updated_at=NOW()
                WHERE r.status='queued' AND r.effective_depth='deep'
                  AND NOT EXISTS (
                      SELECT 1 FROM radar_ask_usage u
                      WHERE u.run_key=r.id AND u.settlement_status='reserved'
                  )
                RETURNING r.id
                """
            ).fetchall()
            counts["failed"] += len(unavailable)
            rows = conn.execute(
                """
                SELECT * FROM radar_ask_runs
                WHERE status='running' AND lease_until <= NOW()
                  AND (worker_id IS NULL OR worker_id NOT LIKE 'planner:%')
                ORDER BY lease_until, created_at
                FOR UPDATE SKIP LOCKED
                """
            ).fetchall()
            for current in rows:
                attempts = int(current["attempt_count"])
                if attempts < 2:
                    delay = 10 if attempts == 1 else 30
                    reservation = conn.execute(
                        """
                        UPDATE radar_ask_usage
                        SET reservation_expires_at=GREATEST(
                                reservation_expires_at,
                                NOW() + (? || ' seconds')::interval
                            ),
                            updated_at=NOW()
                        WHERE run_key=? AND settlement_status='reserved'
                        RETURNING *
                        """,
                        (delay + grace, current["id"]),
                    ).fetchone()
                    if reservation is None:
                        conn.execute(
                            """
                            UPDATE radar_ask_runs
                            SET status='failed', outcome='cancelled',
                                error_code='reservation_unavailable', retryable=FALSE,
                                worker_id=NULL, lease_until=NULL,
                                completed_at=COALESCE(completed_at, NOW()), updated_at=NOW()
                            WHERE id=? AND status='running' AND lease_until <= NOW()
                            """,
                            (current["id"],),
                        )
                        counts["failed"] += 1
                        continue
                    conn.execute(
                        """
                        UPDATE radar_ask_runs
                        SET status='queued', outcome=NULL,
                            error_code='worker_lease_expired', retryable=TRUE,
                            available_at=NOW() + (? || ' seconds')::interval,
                            worker_id=NULL, lease_until=NULL, updated_at=NOW()
                        WHERE id=? AND status='running' AND lease_until <= NOW()
                        """,
                        (delay, current["id"]),
                    )
                    counts["requeued"] += 1
                    continue
                conn.execute(
                    """
                    UPDATE radar_ask_runs
                    SET status='failed', outcome='database_failure',
                        error_code='worker_lease_expired', retryable=FALSE,
                        worker_id=NULL, lease_until=NULL,
                        completed_at=COALESCE(completed_at, NOW()), updated_at=NOW()
                    WHERE id=? AND status='running' AND lease_until <= NOW()
                    """,
                    (current["id"],),
                )
                reservation = conn.execute(
                    """
                    SELECT id FROM radar_ask_usage
                    WHERE run_key=? AND settlement_status='reserved'
                    """,
                    (current["id"],),
                ).fetchone()
                if reservation is not None:
                    self._settle_leased_usage(
                        conn,
                        run_id=current["id"],
                        reservation_id=reservation["id"],
                        usage=ProviderUsage(),
                        outcome="database_failure",
                    )
                counts["failed"] += 1
        return counts

    def transition_run(
        self,
        run_id: UUID,
        *,
        user_id: int | None = None,
        expected: Collection[str],
        target: str,
        outcome: str | None = None,
        effective_depth: str | None = None,
        route: Mapping[str, Any] | None = None,
        answer: Mapping[str, Any] | None = None,
        model: str | None = None,
        error_code: str | None = None,
        retryable: bool | None = None,
    ) -> RadarAskRunRecord:
        expected_statuses = sorted(set(expected))
        if not expected_statuses or any(value not in RUN_STATUSES for value in expected_statuses):
            raise ValueError("expected contains an invalid run status")
        if target not in RUN_STATUSES:
            raise ValueError("target is an invalid run status")
        if any(target not in ALLOWED_RUN_TRANSITIONS[value] for value in expected_statuses):
            raise InvalidRunTransition("requested run transition is not allowed")
        if outcome is not None and outcome not in RUN_OUTCOMES:
            raise ValueError("outcome is invalid")
        if user_id is not None and user_id <= 0:
            raise ValueError("user_id must be positive")
        if effective_depth not in {None, "fast", "standard", "deep"}:
            raise ValueError("effective_depth is invalid")
        normalized_model = None
        if model is not None:
            normalized_model = _bounded_text(model, field="model", maximum=120)
        normalized_error = None
        if error_code is not None:
            normalized_error = _bounded_text(error_code, field="error_code", maximum=80)
            if not normalized_error.replace("_", "").isalnum() or normalized_error.lower() != normalized_error:
                raise ValueError("error_code must contain lowercase letters, digits, or underscores")
        terminal = target in TERMINAL_RUN_STATUSES
        with get_conn() as conn:
            row = conn.execute(
                """
                UPDATE radar_ask_runs
                SET status=?, outcome=?,
                    effective_depth=COALESCE(?, effective_depth),
                    route_json=COALESCE(?, route_json),
                    answer_json=COALESCE(?, answer_json),
                    model=COALESCE(?, model),
                    error_code=COALESCE(?, error_code),
                    retryable=COALESCE(?, retryable),
                    worker_id=CASE WHEN ?='running' THEN worker_id ELSE NULL END,
                    lease_until=CASE WHEN ?='running' THEN lease_until ELSE NULL END,
                    started_at=CASE
                        WHEN ?='running' AND started_at IS NULL THEN NOW()
                        ELSE started_at
                    END,
                    completed_at=CASE WHEN ? THEN COALESCE(completed_at, NOW()) ELSE completed_at END,
                    updated_at=NOW()
                WHERE id=?
                  AND (?::bigint IS NULL OR user_id=?)
                  AND status=ANY(?::text[])
                  AND status NOT IN ('completed', 'insufficient', 'failed', 'cancelled')
                RETURNING *
                """,
                (
                    target,
                    outcome,
                    effective_depth,
                    Jsonb(dict(route)) if route is not None else None,
                    Jsonb(dict(answer)) if answer is not None else None,
                    normalized_model,
                    normalized_error,
                    retryable,
                    target,
                    target,
                    target,
                    terminal,
                    run_id,
                    user_id,
                    user_id,
                    expected_statuses,
                ),
            ).fetchone()
            if row is None:
                current = conn.execute(
                    "SELECT status FROM radar_ask_runs WHERE id=?",
                    (run_id,),
                ).fetchone()
                if current is None:
                    raise InvalidRunTransition("run was not found")
                raise InvalidRunTransition("run status changed before the guarded transition")
        return _run_from_row(row)

    def record_tool_call(
        self,
        *,
        run_id: UUID,
        tool_call_key: str,
        tool_name: str,
        arguments: Mapping[str, Any],
        result_summary: Mapping[str, Any],
        status: str,
    ) -> RadarAskToolCallRecord:
        key = _bounded_text(tool_call_key, field="tool_call_key", maximum=128)
        name = _bounded_text(tool_name, field="tool_name", maximum=128)
        if status not in {"planned", "running", "completed", "failed"}:
            raise ValueError("tool call status is invalid")
        immutable = {
            "tool_name": name,
            "arguments_json": dict(arguments),
            "result_summary_json": dict(result_summary),
            "status": status,
        }
        with get_conn() as conn:
            row = conn.execute(
                """
                INSERT INTO radar_ask_tool_calls (
                    id, run_id, tool_call_key, tool_name,
                    arguments_json, result_summary_json, status, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, CASE WHEN ? IN ('completed', 'failed') THEN NOW() END)
                ON CONFLICT (run_id, tool_call_key) DO NOTHING
                RETURNING *
                """,
                (
                    uuid4(),
                    run_id,
                    key,
                    name,
                    Jsonb(immutable["arguments_json"]),
                    Jsonb(immutable["result_summary_json"]),
                    status,
                    status,
                ),
            ).fetchone()
            if row is None:
                row = conn.execute(
                    "SELECT * FROM radar_ask_tool_calls WHERE run_id=? AND tool_call_key=?",
                    (run_id, key),
                ).fetchone()
                assert row is not None
                existing = _row_dict(row)
                if any(existing[field] != value for field, value in immutable.items()):
                    raise ImmutableAuditConflict("tool-call key belongs to different audit data")
        return _tool_from_row(row)

    def record_evidence(
        self,
        *,
        run_id: UUID,
        evidence_key: str,
        evidence_kind: str,
        source_ref: str,
        payload: Mapping[str, Any],
        min_tier: str,
        as_of: datetime,
    ) -> RadarAskEvidenceRecord:
        key = _bounded_text(evidence_key, field="evidence_key", maximum=160)
        kind = _bounded_text(evidence_kind, field="evidence_kind", maximum=80)
        source = _bounded_text(source_ref, field="source_ref", maximum=500)
        if min_tier not in {"free", "vip", "admin"}:
            raise ValueError("min_tier is invalid")
        immutable = {
            "evidence_kind": kind,
            "source_ref": source,
            "payload_json": dict(payload),
            "min_tier": min_tier,
            "as_of": as_of,
        }
        with get_conn() as conn:
            row = conn.execute(
                """
                INSERT INTO radar_ask_evidence (
                    id, run_id, evidence_key, evidence_kind,
                    source_ref, payload_json, min_tier, as_of
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (run_id, evidence_key) DO NOTHING
                RETURNING *
                """,
                (uuid4(), run_id, key, kind, source, Jsonb(dict(payload)), min_tier, as_of),
            ).fetchone()
            if row is None:
                row = conn.execute(
                    "SELECT * FROM radar_ask_evidence WHERE run_id=? AND evidence_key=?",
                    (run_id, key),
                ).fetchone()
                assert row is not None
                existing = _row_dict(row)
                if any(existing[field] != value for field, value in immutable.items()):
                    raise ImmutableAuditConflict("evidence key belongs to different audit data")
        return _evidence_from_row(row)

    def admin_metrics(
        self,
        *,
        settings: RadarAskSettings,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Return bounded aggregate metadata for the Admin control room.

        Operational metrics start from the indexed run timestamp so failures
        that happen before reservation remain visible. Cost and token totals
        stay on the immutable usage ledger. Conversation content is never
        selected; feedback is grouped by its question-run cohort.
        """
        current = _admin_aware_utc(now or datetime.now(timezone.utc))
        local_date = current.astimezone(BANGKOK).date()
        month_start = local_date.replace(day=1)
        window_start_dates = {
            "today": local_date,
            "last_7_days": local_date - timedelta(days=6),
            "month": month_start,
        }
        window_start_times = {
            key: datetime.combine(value, datetime.min.time(), tzinfo=BANGKOK).astimezone(timezone.utc)
            for key, value in window_start_dates.items()
        }
        scan_start_date = min(window_start_dates.values())
        scan_start_time = min(window_start_times.values())
        usage_months = sorted({scan_start_date.replace(day=1), month_start})
        warning = Decimal(settings.monthly_warning_usd).quantize(MONEY_QUANTUM)
        hard_stop = Decimal(settings.monthly_hard_stop_usd).quantize(MONEY_QUANTUM)
        if warning <= 0 or hard_stop <= warning:
            raise ValueError("metrics budget thresholds are invalid")
        allowed_models = sorted(ADMIN_MODEL_BUCKETS)

        windows = {key: _admin_window() for key in ADMIN_METRIC_WINDOWS}
        window_date_params = (
            window_start_dates["today"],
            window_start_dates["last_7_days"],
            window_start_dates["month"],
        )
        window_time_params = (
            window_start_times["today"],
            window_start_times["last_7_days"],
            window_start_times["month"],
        )
        with get_conn() as conn:
            grouped_rows = conn.execute(
                """
                WITH window_defs(window_key, start_at) AS (
                    VALUES
                        ('today', ?::timestamptz),
                        ('last_7_days', ?::timestamptz),
                        ('month', ?::timestamptz)
                ),
                bounded_runs AS MATERIALIZED (
                    SELECT
                        r.id,
                        r.created_at,
                        r.model,
                        COALESCE(r.effective_depth,r.requested_depth) AS depth,
                        r.outcome,
                        usage.tier
                    FROM radar_ask_runs r
                    LEFT JOIN radar_ask_usage usage ON usage.run_key=r.id
                    WHERE r.created_at>=? AND r.created_at<=?
                )
                SELECT
                    w.window_key,
                    CASE
                        WHEN b.tier IN ('free','vip','admin') THEN b.tier
                        ELSE 'unassigned'
                    END AS tier_bucket,
                    CASE
                        WHEN b.model IS NULL THEN 'unassigned'
                        WHEN b.model=ANY(?::text[]) THEN b.model
                        ELSE 'other'
                    END AS model_bucket,
                    CASE WHEN b.depth IN ('fast','standard','deep') THEN b.depth ELSE 'unassigned' END AS depth_bucket,
                    CASE
                        WHEN b.outcome IS NULL THEN 'pending'
                        WHEN b.outcome IN (
                            'answered','insufficient','clarification','provider_failure',
                            'validation_failure','database_failure','budget_hard_stop','cancelled'
                        ) THEN b.outcome
                        ELSE 'other'
                    END AS outcome_bucket,
                    COUNT(b.id) AS questions,
                    COUNT(b.id) AS runs
                FROM window_defs w
                LEFT JOIN bounded_runs b
                  ON b.created_at>=w.start_at AND b.created_at<=?
                GROUP BY w.window_key,tier_bucket,model_bucket,depth_bucket,outcome_bucket
                ORDER BY w.window_key,tier_bucket,model_bucket,depth_bucket,outcome_bucket
                """,
                (*window_time_params, scan_start_time, current, allowed_models, current),
            ).fetchall()

            health_rows = conn.execute(
                """
                WITH window_defs(window_key, start_at) AS (
                    VALUES
                        ('today', ?::timestamptz),
                        ('last_7_days', ?::timestamptz),
                        ('month', ?::timestamptz)
                ),
                bounded_runs AS MATERIALIZED (
                    SELECT
                        id,created_at,outcome,started_at,completed_at
                    FROM radar_ask_runs
                    WHERE created_at>=? AND created_at<=?
                )
                SELECT
                    w.window_key,
                    COUNT(b.id) FILTER (WHERE b.outcome IS NOT NULL) AS terminal_runs,
                    COUNT(b.id) FILTER (WHERE b.outcome='provider_failure') AS provider_failures,
                    COUNT(b.id) FILTER (WHERE b.outcome='validation_failure') AS validation_failures,
                    COUNT(b.id) FILTER (WHERE b.outcome='insufficient') AS insufficient_runs,
                    percentile_disc(0.5) WITHIN GROUP (
                        ORDER BY EXTRACT(EPOCH FROM (b.completed_at-b.started_at))*1000
                    ) FILTER (WHERE b.completed_at IS NOT NULL AND b.started_at IS NOT NULL) AS p50_ms,
                    percentile_disc(0.95) WITHIN GROUP (
                        ORDER BY EXTRACT(EPOCH FROM (b.completed_at-b.started_at))*1000
                    ) FILTER (WHERE b.completed_at IS NOT NULL AND b.started_at IS NOT NULL) AS p95_ms
                FROM window_defs w
                LEFT JOIN bounded_runs b
                  ON b.created_at>=w.start_at AND b.created_at<=?
                GROUP BY w.window_key
                ORDER BY w.window_key
                """,
                (*window_time_params, scan_start_time, current, current),
            ).fetchall()

            token_rows = conn.execute(
                """
                WITH window_defs(window_key, start_date) AS (
                    VALUES
                        ('today', ?::date),
                        ('last_7_days', ?::date),
                        ('month', ?::date)
                ),
                bounded_usage AS MATERIALIZED (
                    SELECT
                        usage_date,prompt_tokens,completion_tokens,
                        cache_hit_tokens,cache_miss_tokens
                    FROM radar_ask_usage
                    WHERE usage_month=ANY(?::date[])
                      AND usage_date>=? AND usage_date<=?
                )
                SELECT
                    w.window_key,
                    COALESCE(SUM(b.prompt_tokens),0) AS prompt_tokens,
                    COALESCE(SUM(b.completion_tokens),0) AS completion_tokens,
                    COALESCE(SUM(b.cache_hit_tokens),0) AS cache_hit_tokens,
                    COALESCE(SUM(b.cache_miss_tokens),0) AS cache_miss_tokens
                FROM window_defs w
                LEFT JOIN bounded_usage b
                  ON b.usage_date>=w.start_date AND b.usage_date<=?
                GROUP BY w.window_key
                ORDER BY w.window_key
                """,
                (*window_date_params, usage_months, scan_start_date, local_date, local_date),
            ).fetchall()

            cost_row = conn.execute(
                """
                SELECT
                    COALESCE(SUM(actual_usd),0) AS actual_usd,
                    COALESCE(SUM(
                        CASE WHEN settlement_status='reserved' AND reservation_expires_at>?
                             THEN reserved_usd ELSE 0 END
                    ),0) AS reserved_usd
                FROM radar_ask_usage
                WHERE usage_month=?
                """,
                (current, month_start),
            ).fetchone()
            assert cost_row is not None

            queue_row = conn.execute(
                """
                SELECT
                    COUNT(*) AS depth,
                    CASE WHEN MIN(created_at) IS NULL THEN NULL
                         ELSE GREATEST(0,FLOOR(EXTRACT(EPOCH FROM (?-MIN(created_at)))))::bigint
                    END AS oldest_age_seconds
                FROM radar_ask_runs
                WHERE status='queued'
                """,
                (current,),
            ).fetchone()
            assert queue_row is not None

            feedback_rows = conn.execute(
                """
                WITH window_defs(window_key, start_at) AS (
                    VALUES
                        ('today', ?::timestamptz),
                        ('last_7_days', ?::timestamptz),
                        ('month', ?::timestamptz)
                ),
                bounded_runs AS MATERIALIZED (
                    SELECT id,created_at
                    FROM radar_ask_runs
                    WHERE created_at>=? AND created_at<=?
                )
                SELECT
                    w.window_key,
                    CASE WHEN f.rating IN ('helpful','not_helpful') THEN f.rating ELSE 'other' END AS rating_bucket,
                    COUNT(f.id) AS total
                FROM window_defs w
                LEFT JOIN bounded_runs r
                  ON r.created_at>=w.start_at AND r.created_at<=?
                LEFT JOIN radar_ask_messages m ON m.run_id=r.id
                LEFT JOIN radar_ask_feedback f ON f.message_id=m.id
                GROUP BY w.window_key,rating_bucket
                ORDER BY w.window_key,rating_bucket
                """,
                (*window_time_params, scan_start_time, current, current),
            ).fetchall()

        for row in grouped_rows:
            key = row["window_key"]
            questions = int(row["questions"] or 0)
            runs = int(row["runs"] or 0)
            if key not in windows or questions <= 0:
                continue
            target = windows[key]
            target["questions"] += questions
            target["runs"] += runs
            for field, bucket in (
                ("by_tier", row["tier_bucket"]),
                ("by_model", row["model_bucket"]),
                ("by_depth", row["depth_bucket"]),
                ("by_outcome", row["outcome_bucket"]),
            ):
                target[field][bucket] = target[field].get(bucket, 0) + questions

        for row in token_rows:
            key = row["window_key"]
            if key not in windows:
                continue
            windows[key]["tokens"] = {
                "input": int(row["prompt_tokens"] or 0),
                "output": int(row["completion_tokens"] or 0),
                "cache_hit": int(row["cache_hit_tokens"] or 0),
                "cache_miss": int(row["cache_miss_tokens"] or 0),
            }

        for row in health_rows:
            key = row["window_key"]
            if key not in windows:
                continue
            terminal = int(row["terminal_runs"] or 0)
            windows[key]["latency_ms"] = {
                "p50": round(float(row["p50_ms"])) if row["p50_ms"] is not None else None,
                "p95": round(float(row["p95_ms"])) if row["p95_ms"] is not None else None,
            }
            windows[key]["rates"] = {
                "provider_failure": round(int(row["provider_failures"] or 0) / terminal, 6)
                if terminal else 0.0,
                "validation_failure": round(int(row["validation_failures"] or 0) / terminal, 6)
                if terminal else 0.0,
                "insufficient": round(int(row["insufficient_runs"] or 0) / terminal, 6)
                if terminal else 0.0,
            }

        for row in feedback_rows:
            key = row["window_key"]
            rating = row["rating_bucket"]
            if key in windows and rating in {"helpful", "not_helpful"}:
                windows[key]["feedback_by_question_cohort"][rating] += int(row["total"] or 0)

        actual = Decimal(cost_row["actual_usd"] or 0).quantize(MONEY_QUANTUM)
        reserved = Decimal(cost_row["reserved_usd"] or 0).quantize(MONEY_QUANTUM)
        projected = (actual + reserved).quantize(MONEY_QUANTUM)
        cost_state = "hard_stop" if projected >= hard_stop else (
            "warning" if projected >= warning else "normal"
        )
        return {
            "generated_at": current.isoformat(),
            "windows": windows,
            "cost": {
                "usage_month": month_start.isoformat(),
                "actual_usd": _money_text(actual),
                "reserved_usd": _money_text(reserved),
                "projected_usd": _money_text(projected),
                "warning_usd": _money_text(warning),
                "hard_stop_usd": _money_text(hard_stop),
                "state": cost_state,
            },
            "queue": {
                "depth": int(queue_row["depth"] or 0),
                "oldest_age_seconds": int(queue_row["oldest_age_seconds"])
                if queue_row["oldest_age_seconds"] is not None else None,
            },
        }

    def delete_session(self, *, user_id: int, session_id: UUID) -> bool:
        with get_conn() as conn:
            cursor = conn.execute(
                "DELETE FROM radar_ask_sessions WHERE id=? AND user_id=?",
                (session_id, user_id),
            )
            deleted = cursor.rowcount
        return deleted == 1

    def delete_all_sessions(self, *, user_id: int) -> int:
        with get_conn() as conn:
            cursor = conn.execute(
                "DELETE FROM radar_ask_sessions WHERE user_id=?",
                (user_id,),
            )
            deleted = cursor.rowcount
        return max(deleted, 0)

    @staticmethod
    def _content_counts_for_sessions(conn: PgConnection, session_ids: list[UUID]) -> dict[str, int]:
        return {
            "sessions": len(session_ids),
            "runs": int(
                conn.execute(
                    "SELECT COUNT(*) AS count FROM radar_ask_runs WHERE session_id=ANY(?)",
                    (session_ids,),
                ).fetchone()["count"]
            ),
            "messages": int(
                conn.execute(
                    "SELECT COUNT(*) AS count FROM radar_ask_messages WHERE session_id=ANY(?)",
                    (session_ids,),
                ).fetchone()["count"]
            ),
        }

    def count_expired_content(self, *, cutoff: datetime) -> dict[str, int]:
        """Count only raw-content candidates; this method never mutates persisted data."""
        with get_conn() as conn:
            sessions = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM radar_ask_sessions s
                WHERE s.updated_at < ?
                  AND NOT EXISTS (
                      SELECT 1 FROM radar_ask_messages m
                      WHERE m.session_id=s.id AND m.created_at >= ?
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM radar_ask_runs r
                      WHERE r.session_id=s.id AND r.status<>ALL(?::text[])
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM radar_ask_runs r
                      WHERE r.session_id=s.id
                        AND COALESCE(r.completed_at, r.updated_at, r.created_at) >= ?
                  )
                """,
                (cutoff, cutoff, list(TERMINAL_RUN_STATUSES), cutoff),
            ).fetchone()["count"]
            runs = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM radar_ask_runs r
                WHERE r.status=ANY(?::text[])
                  AND COALESCE(r.completed_at, r.updated_at, r.created_at) < ?
                """,
                (list(TERMINAL_RUN_STATUSES), cutoff),
            ).fetchone()["count"]
            messages = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM radar_ask_messages m
                LEFT JOIN radar_ask_runs r ON r.id=m.run_id
                WHERE (r.status=ANY(?::text[]) AND COALESCE(r.completed_at,r.updated_at,r.created_at) < ?)
                   OR (m.run_id IS NULL AND m.created_at < ? AND NOT EXISTS (
                       SELECT 1 FROM radar_ask_runs active WHERE active.session_id=m.session_id AND active.status<>ALL(?::text[])
                   ))
                """,
                (list(TERMINAL_RUN_STATUSES), cutoff, cutoff, list(TERMINAL_RUN_STATUSES)),
            ).fetchone()["count"]
        return {"sessions": int(sessions), "runs": int(runs), "messages": int(messages)}

    def purge_expired_content_batch(self, *, cutoff: datetime) -> dict[str, int] | None:
        """Delete one bounded raw-content target set without touching nonterminal work."""
        with get_conn() as conn:
            feedback_ids = [row["id"] for row in conn.execute(
                """SELECT f.id FROM radar_ask_feedback f JOIN radar_ask_messages m ON m.id=f.message_id
                LEFT JOIN radar_ask_runs r ON r.id=m.run_id
                WHERE (r.status=ANY(?::text[]) AND COALESCE(r.completed_at,r.updated_at,r.created_at) < ?)
                   OR (m.run_id IS NULL AND m.created_at < ? AND NOT EXISTS (SELECT 1 FROM radar_ask_runs a WHERE a.session_id=m.session_id AND a.status<>ALL(?::text[])))
                ORDER BY f.created_at,f.id FOR UPDATE OF f,m SKIP LOCKED LIMIT ?""",
                (list(TERMINAL_RUN_STATUSES), cutoff, cutoff, list(TERMINAL_RUN_STATUSES), RETENTION_BATCH_SIZE),
            ).fetchall()]
            if feedback_ids:
                conn.execute("DELETE FROM radar_ask_feedback WHERE id=ANY(?)", (feedback_ids,))
                return {"sessions": 0, "runs": 0, "messages": 0}
            tool_ids = [row["id"] for row in conn.execute(
                """SELECT t.id FROM radar_ask_tool_calls t JOIN radar_ask_runs r ON r.id=t.run_id
                WHERE r.status=ANY(?::text[]) AND COALESCE(r.completed_at,r.updated_at,r.created_at) < ?
                ORDER BY t.created_at,t.id FOR UPDATE OF t,r SKIP LOCKED LIMIT ?""",
                (list(TERMINAL_RUN_STATUSES), cutoff, RETENTION_BATCH_SIZE),
            ).fetchall()]
            if tool_ids:
                conn.execute("DELETE FROM radar_ask_tool_calls WHERE id=ANY(?)", (tool_ids,))
                return {"sessions": 0, "runs": 0, "messages": 0}
            evidence_ids = [row["id"] for row in conn.execute(
                """SELECT e.id FROM radar_ask_evidence e JOIN radar_ask_runs r ON r.id=e.run_id
                WHERE r.status=ANY(?::text[]) AND COALESCE(r.completed_at,r.updated_at,r.created_at) < ?
                ORDER BY e.created_at,e.id FOR UPDATE OF e,r SKIP LOCKED LIMIT ?""",
                (list(TERMINAL_RUN_STATUSES), cutoff, RETENTION_BATCH_SIZE),
            ).fetchall()]
            if evidence_ids:
                conn.execute("DELETE FROM radar_ask_evidence WHERE id=ANY(?)", (evidence_ids,))
                return {"sessions": 0, "runs": 0, "messages": 0}
            message_ids = [row["id"] for row in conn.execute(
                """SELECT m.id FROM radar_ask_messages m JOIN radar_ask_runs r ON r.id=m.run_id
                WHERE r.status=ANY(?::text[]) AND COALESCE(r.completed_at,r.updated_at,r.created_at) < ?
                ORDER BY m.created_at,m.id FOR UPDATE OF m,r SKIP LOCKED LIMIT ?""",
                (list(TERMINAL_RUN_STATUSES), cutoff, RETENTION_BATCH_SIZE),
            ).fetchall()]
            if message_ids:
                deleted = conn.execute(
                    "DELETE FROM radar_ask_messages m WHERE id=ANY(?) "
                    "AND NOT EXISTS (SELECT 1 FROM radar_ask_feedback f WHERE f.message_id=m.id)",
                    (message_ids,),
                )
                return {"sessions": 0, "runs": 0, "messages": max(deleted.rowcount, 0)}
            run_ids = [
                row["id"]
                for row in conn.execute(
                    """
                    SELECT r.id
                    FROM radar_ask_runs r
                    JOIN radar_ask_sessions s ON s.id=r.session_id
                    WHERE r.status=ANY(?::text[])
                      AND COALESCE(r.completed_at, r.updated_at, r.created_at) < ?
                      AND NOT EXISTS (SELECT 1 FROM radar_ask_tool_calls t WHERE t.run_id=r.id)
                      AND NOT EXISTS (SELECT 1 FROM radar_ask_evidence e WHERE e.run_id=r.id)
                      AND NOT EXISTS (SELECT 1 FROM radar_ask_messages m WHERE m.run_id=r.id)
                    ORDER BY COALESCE(r.completed_at, r.updated_at, r.created_at), r.id
                    FOR UPDATE OF r, s SKIP LOCKED
                    LIMIT ?
                    """,
                    (
                        list(TERMINAL_RUN_STATUSES), cutoff,
                        RETENTION_BATCH_SIZE,
                    ),
                ).fetchall()
            ]
            if run_ids:
                deleted = conn.execute(
                    """DELETE FROM radar_ask_runs r WHERE id=ANY(?)
                    AND NOT EXISTS (SELECT 1 FROM radar_ask_tool_calls t WHERE t.run_id=r.id)
                    AND NOT EXISTS (SELECT 1 FROM radar_ask_evidence e WHERE e.run_id=r.id)
                    AND NOT EXISTS (SELECT 1 FROM radar_ask_messages m WHERE m.run_id=r.id)
                    """,
                    (run_ids,),
                )
                return {"sessions": 0, "runs": max(deleted.rowcount, 0), "messages": 0}

            message_ids = [
                row["id"]
                for row in conn.execute(
                    """
                    SELECT m.id
                    FROM radar_ask_messages m
                    JOIN radar_ask_sessions s ON s.id=m.session_id
                    WHERE m.run_id IS NULL AND m.created_at < ?
                      AND NOT EXISTS (SELECT 1 FROM radar_ask_runs a WHERE a.session_id=m.session_id AND a.status<>ALL(?::text[]))
                    ORDER BY m.created_at, m.id
                    FOR UPDATE OF m, s SKIP LOCKED
                    LIMIT ?
                    """,
                    (cutoff, list(TERMINAL_RUN_STATUSES), RETENTION_BATCH_SIZE),
                ).fetchall()
            ]
            if message_ids:
                deleted = conn.execute(
                    "DELETE FROM radar_ask_messages m WHERE id=ANY(?) "
                    "AND NOT EXISTS (SELECT 1 FROM radar_ask_feedback f WHERE f.message_id=m.id)",
                    (message_ids,),
                )
                return {"sessions": 0, "runs": 0, "messages": max(deleted.rowcount, 0)}
            session_ids = [row["id"] for row in conn.execute(
                """SELECT s.id FROM radar_ask_sessions s WHERE s.updated_at < ?
                AND NOT EXISTS (SELECT 1 FROM radar_ask_runs r WHERE r.session_id=s.id)
                AND NOT EXISTS (SELECT 1 FROM radar_ask_messages m WHERE m.session_id=s.id)
                ORDER BY s.updated_at,s.id FOR UPDATE SKIP LOCKED LIMIT ?""",
                (cutoff, RETENTION_BATCH_SIZE),
            ).fetchall()]
            if session_ids:
                deleted = conn.execute(
                    """DELETE FROM radar_ask_sessions s WHERE id=ANY(?)
                    AND NOT EXISTS (SELECT 1 FROM radar_ask_runs r WHERE r.session_id=s.id)
                    AND NOT EXISTS (SELECT 1 FROM radar_ask_messages m WHERE m.session_id=s.id)
                    """,
                    (session_ids,),
                )
                return {"sessions": max(deleted.rowcount, 0), "runs": 0, "messages": 0}
        return None

    def count_expired_usage(self, *, cutoff_month: date) -> dict[str, int]:
        """Count content-free usage rows eligible for the 13-month accounting purge."""
        with get_conn() as conn:
            usage = int(
                conn.execute(
                    "SELECT COUNT(*) AS count FROM radar_ask_usage WHERE usage_month < ?",
                    (cutoff_month,),
                ).fetchone()["count"]
            )
            attempts = int(
                conn.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM radar_ask_usage_attempts a
                    JOIN radar_ask_usage u ON u.id=a.reservation_id
                    WHERE u.usage_month < ?
                    """,
                    (cutoff_month,),
                ).fetchone()["count"]
            )
        return {"usage": usage, "attempts": attempts}

    def purge_expired_usage_batch(self, *, cutoff_month: date) -> dict[str, int] | None:
        """Delete one bounded aggregate batch; usage-attempt rows cascade with its ledger."""
        with get_conn() as conn:
            attempt_ids = [row["id"] for row in conn.execute(
                """SELECT a.id FROM radar_ask_usage_attempts a JOIN radar_ask_usage u ON u.id=a.reservation_id
                WHERE u.usage_month < ? ORDER BY a.leased_at,a.id FOR UPDATE OF a,u SKIP LOCKED LIMIT ?""",
                (cutoff_month, RETENTION_BATCH_SIZE),
            ).fetchall()]
            if attempt_ids:
                conn.execute("DELETE FROM radar_ask_usage_attempts WHERE id=ANY(?)", (attempt_ids,))
                return {"usage": 0, "attempts": len(attempt_ids)}
            usage_ids = [
                row["id"]
                for row in conn.execute(
                    """
                    SELECT id FROM radar_ask_usage
                    WHERE usage_month < ?
                    ORDER BY usage_month, id
                    FOR UPDATE SKIP LOCKED
                    LIMIT ?
                    """,
                    (cutoff_month, RETENTION_BATCH_SIZE),
                ).fetchall()
            ]
            if not usage_ids:
                return None
            attempts = 0
            deleted = conn.execute(
                "DELETE FROM radar_ask_usage u WHERE id=ANY(?) "
                "AND NOT EXISTS (SELECT 1 FROM radar_ask_usage_attempts a WHERE a.reservation_id=u.id)",
                (usage_ids,),
            )
        return {"usage": max(deleted.rowcount, 0), "attempts": attempts}
