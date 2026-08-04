from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest

from db import connection
from db.connection import get_conn
from db.schema import init_schema
from services.radar_ask.repository import RadarAskRepository
from services.radar_ask.retention import (
    RadarAskRetentionService,
    purge_expired_content,
    purge_expired_usage,
)


BANGKOK = ZoneInfo("Asia/Bangkok")
NOW = datetime(2026, 8, 5, 12, 0, tzinfo=BANGKOK)


@dataclass(frozen=True)
class RetentionUser:
    id: int


@pytest.fixture
def retention_env():
    connection.close_all()
    init_schema()
    token = uuid4().hex
    with get_conn() as conn:
        cursor = conn.execute(
            """
            INSERT INTO users (identifier, identifier_type, password_hash, tier)
            VALUES (?, 'email', 'test-hash', 'vip')
            """,
            (f"radar-ask-retention-{token}@example.test",),
        )
        user = RetentionUser(id=int(cursor.lastrowid))
    yield RadarAskRepository(), user
    with get_conn() as conn:
        conn.execute("DELETE FROM radar_ask_usage WHERE user_id=?", (user.id,))
        conn.execute("DELETE FROM users WHERE id=?", (user.id,))
    connection.close_all()


def _terminal_run(repository: RadarAskRepository, user: RetentionUser, *, key: str):
    run = repository.create_run(
        user_id=user.id,
        question=f"Nghien cuu retention {key}",
        idempotency_key=key,
    )
    running = repository.transition_run(
        run.id,
        user_id=user.id,
        expected={"created"},
        target="running",
    )
    return repository.transition_run(
        running.id,
        user_id=user.id,
        expected={"running"},
        target="completed",
        outcome="answered",
        answer={"direct_answer": "Noi dung da het han."},
    )


def _age_session_content(session_id: UUID, *, when: datetime) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE radar_ask_sessions SET created_at=?, updated_at=? WHERE id=?",
            (when, when, session_id),
        )
        conn.execute(
            "UPDATE radar_ask_messages SET created_at=? WHERE session_id=?",
            (when, session_id),
        )
        conn.execute(
            """
            UPDATE radar_ask_runs
            SET created_at=?, updated_at=?, completed_at=?
            WHERE session_id=?
            """,
            (when, when, when, session_id),
        )
        conn.execute(
            """
            UPDATE radar_ask_tool_calls SET created_at=?, completed_at=?
            WHERE run_id IN (SELECT id FROM radar_ask_runs WHERE session_id=?)
            """,
            (when, when, session_id),
        )
        conn.execute(
            """
            UPDATE radar_ask_evidence SET created_at=?
            WHERE run_id IN (SELECT id FROM radar_ask_runs WHERE session_id=?)
            """,
            (when, session_id),
        )
        conn.execute(
            """
            UPDATE radar_ask_feedback SET created_at=?
            WHERE message_id IN (SELECT id FROM radar_ask_messages WHERE session_id=?)
            """,
            (when, session_id),
        )


def _content_counts() -> dict[str, int]:
    with get_conn() as conn:
        return {
            table: int(conn.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()["count"])
            for table in (
                "radar_ask_sessions",
                "radar_ask_messages",
                "radar_ask_runs",
                "radar_ask_tool_calls",
                "radar_ask_evidence",
                "radar_ask_feedback",
            )
        }


def _insert_usage(user: RetentionUser, *, usage_month: datetime) -> UUID:
    reservation_id = uuid4()
    run_key = uuid4()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO radar_ask_usage (
                id, run_key, user_id, tier, model, depth,
                usage_date, usage_month, settlement_status, question_status,
                actual_usd, prompt_tokens, completion_tokens, outcome,
                reservation_expires_at, settled_at
            ) VALUES (?, ?, ?, 'vip', 'deepseek-v4-pro', 'deep', ?, ?,
                'settled', 'answered', 0.031, 12, 7, 'answered', ?, ?)
            """,
            (
                reservation_id,
                run_key,
                user.id,
                usage_month.date(),
                usage_month.date().replace(day=1),
                NOW,
                NOW,
            ),
        )
        conn.execute(
            """
            INSERT INTO radar_ask_usage_attempts (
                id, reservation_id, run_key, attempt_count, worker_id, model,
                actual_usd, outcome, recorded_at
            ) VALUES (?, ?, ?, 1, 'retention-test', 'deepseek-v4-pro',
                0.031, 'answered', ?)
            """,
            (uuid4(), reservation_id, run_key, NOW),
        )
    return reservation_id


def _month_before(value: datetime, months: int) -> datetime:
    ordinal = value.year * 12 + value.month - 1 - months
    return value.replace(year=ordinal // 12, month=ordinal % 12 + 1, day=1)


def test_content_cutoff_cascades_expired_terminal_history_and_preserves_active_content(retention_env):
    """Deleting a 91-day terminal session must not reach 89-day or active history."""
    repository, user = retention_env
    old = _terminal_run(repository, user, key="old")
    repository.record_tool_call(
        run_id=old.id,
        tool_call_key="retention-tool",
        tool_name="market_summary",
        arguments={"ward": "Phu My"},
        result_summary={"count": 1},
        status="completed",
    )
    repository.record_evidence(
        run_id=old.id,
        evidence_key="retention-evidence",
        evidence_kind="market_stat",
        source_ref="market:phu-my",
        payload={"sample": 1},
        min_tier="vip",
        as_of=NOW,
    )
    assistant = repository.create_message(
        user_id=user.id,
        session_id=old.session_id,
        role="assistant",
        content="Cau tra loi cu.",
    )
    repository.add_feedback(
        user_id=user.id,
        message_id=assistant.id,
        rating="helpful",
        note="Ghi chu cu.",
    )
    _age_session_content(old.session_id, when=NOW - timedelta(days=91))

    recent = _terminal_run(repository, user, key="recent")
    _age_session_content(recent.session_id, when=NOW - timedelta(days=89))

    queued = repository.create_run(
        user_id=user.id,
        question="Hang doi cu van phai giu.",
        idempotency_key="queued",
    )
    repository.transition_run(
        queued.id,
        user_id=user.id,
        expected={"created"},
        target="queued",
    )
    _age_session_content(queued.session_id, when=NOW - timedelta(days=91))

    running = repository.create_run(
        user_id=user.id,
        question="Dang xu ly cu van phai giu.",
        idempotency_key="running",
    )
    repository.transition_run(
        running.id,
        user_id=user.id,
        expected={"created"},
        target="running",
    )
    _age_session_content(running.session_id, when=NOW - timedelta(days=91))

    result = purge_expired_content(clock=lambda: NOW)

    assert result["sessions"] == 1
    assert result["batches"] >= 1
    with get_conn() as conn:
        assert conn.execute("SELECT 1 FROM radar_ask_sessions WHERE id=?", (old.session_id,)).fetchone() is None
        assert conn.execute("SELECT 1 FROM radar_ask_runs WHERE id=?", (old.id,)).fetchone() is None
        assert conn.execute("SELECT COUNT(*) AS count FROM radar_ask_tool_calls").fetchone()["count"] == 0
        assert conn.execute("SELECT COUNT(*) AS count FROM radar_ask_evidence").fetchone()["count"] == 0
        assert conn.execute("SELECT COUNT(*) AS count FROM radar_ask_feedback").fetchone()["count"] == 0
        assert conn.execute("SELECT 1 FROM radar_ask_sessions WHERE id=?", (recent.session_id,)).fetchone() is not None
        assert conn.execute("SELECT 1 FROM radar_ask_runs WHERE id=?", (recent.id,)).fetchone() is not None
        assert conn.execute("SELECT 1 FROM radar_ask_sessions WHERE id=?", (queued.session_id,)).fetchone() is not None
        assert conn.execute("SELECT status FROM radar_ask_runs WHERE id=?", (queued.id,)).fetchone()["status"] == "queued"
        assert conn.execute("SELECT 1 FROM radar_ask_sessions WHERE id=?", (running.session_id,)).fetchone() is not None
        assert conn.execute("SELECT status FROM radar_ask_runs WHERE id=?", (running.id,)).fetchone()["status"] == "running"


def test_expired_empty_sessions_are_deleted_in_500_id_batches_and_rerun_is_idempotent(retention_env):
    """A batch-size regression must not turn retention into one unbounded delete."""
    _repository, user = retention_env
    old = NOW - timedelta(days=91)
    with get_conn() as conn:
        conn.executemany(
            """
            INSERT INTO radar_ask_sessions (id, user_id, title, summary_json, created_at, updated_at)
            VALUES (?, ?, 'Expired session', '{}'::jsonb, ?, ?)
            """,
            [(uuid4(), user.id, old, old) for _ in range(501)],
        )

    service = RadarAskRetentionService(clock=lambda: NOW)
    first = service.purge_expired_content()
    second = service.purge_expired_content()

    assert first["sessions"] == 501
    assert first["batches"] == 2
    assert second == {"sessions": 0, "runs": 0, "messages": 0, "batches": 0}


def test_dry_run_mutates_nothing_and_usage_keeps_13_month_buckets_but_purges_14th(retention_env):
    """Dry-run and accounting retention must not erase current retained totals."""
    repository, user = retention_env
    expired = _terminal_run(repository, user, key="dry-run")
    _age_session_content(expired.session_id, when=NOW - timedelta(days=91))
    retained_usage = [_insert_usage(user, usage_month=_month_before(NOW, months)) for months in range(13)]
    expired_usage = _insert_usage(user, usage_month=_month_before(NOW, 13))
    before = _content_counts()

    dry_content = purge_expired_content(dry_run=True, clock=lambda: NOW)
    dry_usage = purge_expired_usage(dry_run=True, clock=lambda: NOW)

    assert dry_content["sessions"] == 1
    assert dry_usage["usage"] == 1
    assert _content_counts() == before
    with get_conn() as conn:
        assert all(
            conn.execute("SELECT 1 FROM radar_ask_usage WHERE id=?", (reservation_id,)).fetchone() is not None
            for reservation_id in retained_usage
        )
        assert conn.execute("SELECT 1 FROM radar_ask_usage WHERE id=?", (expired_usage,)).fetchone() is not None

    applied = purge_expired_usage(clock=lambda: NOW)

    assert applied["usage"] == 1
    assert applied["attempts"] == 1
    with get_conn() as conn:
        assert all(
            conn.execute("SELECT 1 FROM radar_ask_usage WHERE id=?", (reservation_id,)).fetchone() is not None
            for reservation_id in retained_usage
        )
        assert conn.execute("SELECT 1 FROM radar_ask_usage WHERE id=?", (expired_usage,)).fetchone() is None
        assert conn.execute("SELECT COUNT(*) AS count FROM radar_ask_usage_attempts").fetchone()["count"] == 13


def test_expired_terminal_run_is_purged_from_a_session_with_a_running_sibling(retention_env):
    repository, user = retention_env
    old = _terminal_run(repository, user, key="shared-old")
    active = repository.create_run(user_id=user.id, session_id=old.session_id, question="Dang chay", idempotency_key="shared-active")
    repository.transition_run(active.id, user_id=user.id, expected={"created"}, target="running")
    _age_session_content(old.session_id, when=NOW - timedelta(days=91))
    with get_conn() as conn:
        conn.execute("UPDATE radar_ask_runs SET created_at=?, updated_at=?, completed_at=? WHERE id=?", (NOW - timedelta(days=91), NOW - timedelta(days=91), NOW - timedelta(days=91), old.id))
    purge_expired_content(clock=lambda: NOW)
    with get_conn() as conn:
        assert conn.execute("SELECT 1 FROM radar_ask_runs WHERE id=?", (old.id,)).fetchone() is None
        assert conn.execute("SELECT status FROM radar_ask_runs WHERE id=?", (active.id,)).fetchone()["status"] == "running"


def test_clock_boundary_and_legacy_messages_preserve_nonterminal_sessions(retention_env):
    repository, user = retention_env
    with pytest.raises(ValueError):
        RadarAskRetentionService(clock=lambda: NOW.replace(tzinfo=None)).purge_expired_content(dry_run=True)
    boundary = _terminal_run(repository, user, key="boundary")
    _age_session_content(boundary.session_id, when=NOW - timedelta(days=90))
    legacy = repository.create_run(user_id=user.id, question="legacy", idempotency_key="legacy")
    with get_conn() as conn:
        conn.execute("UPDATE radar_ask_messages SET run_id=NULL, created_at=? WHERE session_id=?", (NOW - timedelta(days=91), legacy.session_id))
        conn.execute("UPDATE radar_ask_sessions SET updated_at=? WHERE id=?", (NOW - timedelta(days=91), legacy.session_id))
    purge_expired_content(clock=lambda: NOW)
    with get_conn() as conn:
        assert conn.execute("SELECT 1 FROM radar_ask_runs WHERE id=?", (boundary.id,)).fetchone() is not None
        assert conn.execute("SELECT 1 FROM radar_ask_messages WHERE session_id=?", (legacy.session_id,)).fetchone() is not None


def test_dry_run_matches_apply_for_shared_expired_run(retention_env):
    repository, user = retention_env
    old = _terminal_run(repository, user, key="parity-old")
    repository.record_tool_call(run_id=old.id, tool_call_key="parity-tool", tool_name="market", arguments={}, result_summary={}, status="completed")
    repository.record_evidence(run_id=old.id, evidence_key="parity-evidence", evidence_kind="market", source_ref="market:old", payload={}, min_tier="vip", as_of=NOW)
    answer = repository.create_message(user_id=user.id, session_id=old.session_id, run_id=old.id, role="assistant", content="old")
    repository.add_feedback(user_id=user.id, message_id=answer.id, rating="helpful")
    active = repository.create_run(user_id=user.id, session_id=old.session_id, question="active", idempotency_key="parity-active")
    repository.transition_run(active.id, user_id=user.id, expected={"created"}, target="queued")
    with get_conn() as conn:
        conn.execute("UPDATE radar_ask_runs SET created_at=?, updated_at=?, completed_at=? WHERE id=?", (NOW-timedelta(days=91), NOW-timedelta(days=91), NOW-timedelta(days=91), old.id))
    dry = purge_expired_content(dry_run=True, clock=lambda: NOW)
    applied = purge_expired_content(clock=lambda: NOW)
    assert dry["runs"] == applied["runs"] == 1
    assert dry["messages"] == applied["messages"] == 2
    with get_conn() as conn:
        assert conn.execute("SELECT COUNT(*) AS count FROM radar_ask_tool_calls WHERE run_id=?", (old.id,)).fetchone()["count"] == 0
        assert conn.execute("SELECT COUNT(*) AS count FROM radar_ask_evidence WHERE run_id=?", (old.id,)).fetchone()["count"] == 0
        assert conn.execute("SELECT COUNT(*) AS count FROM radar_ask_feedback WHERE message_id=?", (answer.id,)).fetchone()["count"] == 0


def test_more_than_500_owned_runs_and_messages_are_processed_in_multiple_batches(retention_env):
    repository, user = retention_env
    session = repository.create_session(user_id=user.id, title="bulk")
    old = NOW - timedelta(days=91)
    rows = [(uuid4(), session.id, user.id, f"bulk-{i}", f"q{i}", old, old, old) for i in range(501)]
    with get_conn() as conn:
        conn.executemany(
            """INSERT INTO radar_ask_runs (id,session_id,user_id,idempotency_key,question,status,created_at,updated_at,completed_at)
            VALUES (?, ?, ?, ?, ?, 'completed', ?, ?, ?)""", rows,
        )
        conn.executemany(
            "INSERT INTO radar_ask_messages (id,session_id,run_id,role,content,created_at) VALUES (?, ?, ?, 'user', 'old', ?)",
            [(uuid4(), session.id, row[0], old) for row in rows],
        )
        conn.execute("UPDATE radar_ask_sessions SET created_at=?, updated_at=? WHERE id=?", (old, old, session.id))
    result = purge_expired_content(clock=lambda: NOW)
    assert result["runs"] == 501 and result["messages"] == 501 and result["batches"] >= 5


def test_more_than_500_usage_and_attempts_are_processed_in_multiple_batches(retention_env):
    _repository, user = retention_env
    old = _month_before(NOW, 13)
    ids = [_insert_usage(user, usage_month=old) for _ in range(501)]
    result = purge_expired_usage(clock=lambda: NOW)
    assert result == {"usage": 501, "attempts": 501, "batches": 4}
    with get_conn() as conn:
        assert conn.execute("SELECT COUNT(*) AS count FROM radar_ask_usage WHERE id=ANY(?)", (ids,)).fetchone()["count"] == 0


def test_created_and_clarifying_runs_and_their_messages_are_preserved(retention_env):
    repository, user = retention_env
    created = repository.create_run(user_id=user.id, question="created", idempotency_key="created-old")
    clarifying = repository.create_run(user_id=user.id, question="clarifying", idempotency_key="clarifying-old")
    repository.transition_run(clarifying.id, user_id=user.id, expected={"created"}, target="clarifying")
    _age_session_content(created.session_id, when=NOW-timedelta(days=91))
    _age_session_content(clarifying.session_id, when=NOW-timedelta(days=91))
    purge_expired_content(clock=lambda: NOW)
    with get_conn() as conn:
        assert conn.execute("SELECT status FROM radar_ask_runs WHERE id=?", (created.id,)).fetchone()["status"] == "created"
        assert conn.execute("SELECT status FROM radar_ask_runs WHERE id=?", (clarifying.id,)).fetchone()["status"] == "clarifying"
        assert conn.execute("SELECT COUNT(*) AS count FROM radar_ask_messages WHERE run_id IN (?, ?)", (created.id, clarifying.id)).fetchone()["count"] == 2


def test_new_run_messages_have_foreign_key_ownership(retention_env):
    repository, user = retention_env
    run = repository.create_run(user_id=user.id, question="linked", idempotency_key="linked")
    repository.create_message(user_id=user.id, session_id=run.session_id, run_id=run.id, role="assistant", content="linked answer")
    with get_conn() as conn:
        assert conn.execute("SELECT COUNT(*) AS count FROM radar_ask_messages WHERE run_id=?", (run.id,)).fetchone()["count"] == 2
        with pytest.raises(Exception):
            conn.execute("INSERT INTO radar_ask_messages (id,session_id,run_id,role,content) VALUES (?, ?, ?, 'user', 'bad')", (uuid4(), run.session_id, uuid4()))
