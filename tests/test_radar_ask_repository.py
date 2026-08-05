from __future__ import annotations

from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import subprocess
import sys
from uuid import UUID, uuid4

import pytest

from db import connection
from db.connection import get_conn
from db.schema import init_schema
from services.radar_ask.repository import (
    IdempotencyConflict,
    ImmutableAuditConflict,
    InvalidRunTransition,
    OwnedResourceNotFound,
    RadarAskRepository,
)
from services.radar_ask.contracts import ProviderUsage


@dataclass(frozen=True)
class RepositoryUsers:
    free_id: int
    vip_id: int


@pytest.fixture
def repository_env():
    token = uuid4().hex
    identifiers = [f"radar-ask-free-{token}@example.test", f"radar-ask-vip-{token}@example.test"]
    connection.close_all()
    init_schema()
    with get_conn() as conn:
        ids = []
        for identifier, tier in zip(identifiers, ("free", "vip"), strict=True):
            cursor = conn.execute(
                """
                INSERT INTO users (identifier, identifier_type, password_hash, tier)
                VALUES (?, 'email', 'test-hash', ?)
                """,
                (identifier, tier),
            )
            ids.append(int(cursor.lastrowid))

    users = RepositoryUsers(free_id=ids[0], vip_id=ids[1])
    repository = RadarAskRepository()
    yield repository, users

    with get_conn() as conn:
        conn.execute(
            "DELETE FROM radar_ask_usage WHERE user_id IN (?, ?)",
            (users.free_id, users.vip_id),
        )
        conn.execute(
            "DELETE FROM users WHERE id IN (?, ?)",
            (users.free_id, users.vip_id),
        )
    connection.close_all()


def test_schema_creates_active_tables_indexes_constraints_and_keeps_legacy(repository_env):
    _repository, _users = repository_env
    expected_tables = {
        "radar_ask_sessions",
        "radar_ask_messages",
        "radar_ask_runs",
        "radar_ask_tool_calls",
        "radar_ask_evidence",
        "radar_ask_usage",
        "radar_ask_feedback",
    }
    expected_indexes = {
        "idx_radar_ask_sessions_owner_updated",
        "idx_radar_ask_messages_session_created",
        "idx_radar_ask_messages_retention",
        "idx_radar_ask_runs_session_created",
        "idx_radar_ask_runs_queue",
        "idx_radar_ask_tool_calls_run",
        "idx_radar_ask_evidence_run",
        "idx_radar_ask_usage_user_day",
        "idx_radar_ask_usage_month",
        "idx_radar_ask_feedback_message",
    }
    with get_conn() as conn:
        tables = {
            row["table_name"]
            for row in conn.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema='public'
                  AND (table_name LIKE 'radar_ask_%' OR table_name LIKE 'assistant_%')
                """
            ).fetchall()
        }
        indexes = {
            row["indexname"]
            for row in conn.execute(
                """
                SELECT indexname
                FROM pg_indexes
                WHERE schemaname='public' AND tablename LIKE 'radar_ask_%'
                """
            ).fetchall()
        }
        usage_types = {
            row["column_name"]: row["data_type"]
            for row in conn.execute(
                """
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_schema='public' AND table_name='radar_ask_usage'
                  AND column_name IN (
                      'usage_date', 'usage_month', 'reserved_usd', 'actual_usd',
                      'planner_model', 'planner_actual_usd', 'planner_recorded_at'
                  )
                """
            ).fetchall()
        }

    assert expected_tables <= tables
    assert {
        "assistant_sessions",
        "assistant_messages",
        "assistant_feedback",
        "assistant_user_profiles",
    } <= tables
    assert expected_indexes <= indexes
    assert usage_types == {
        "usage_date": "date",
        "usage_month": "date",
        "reserved_usd": "numeric",
        "actual_usd": "numeric",
        "planner_model": "text",
        "planner_actual_usd": "numeric",
        "planner_recorded_at": "timestamp with time zone",
    }


def test_session_lookup_and_rename_are_owner_scoped(repository_env):
    repository, users = repository_env
    session = repository.create_session(user_id=users.free_id, title="Phú Mỹ")

    assert isinstance(session.id, UUID)
    assert repository.get_session(user_id=users.free_id, session_id=session.id) == session
    assert repository.get_session(user_id=users.vip_id, session_id=session.id) is None
    assert repository.rename_session(
        user_id=users.vip_id,
        session_id=session.id,
        title="Không được đổi",
    ) is None
    renamed = repository.rename_session(
        user_id=users.free_id,
        session_id=session.id,
        title="  So sánh Phú Mỹ  ",
    )
    assert renamed is not None
    assert renamed.title == "So sánh Phú Mỹ"


def test_messages_feedback_and_reads_require_session_ownership(repository_env):
    repository, users = repository_env
    session = repository.create_session(user_id=users.free_id, title="Giá đất")
    user_message = repository.create_message(
        user_id=users.free_id,
        session_id=session.id,
        role="user",
        content="Giá Phú Mỹ?",
    )
    assistant_message = repository.create_message(
        user_id=users.free_id,
        session_id=session.id,
        role="assistant",
        content="Mẫu hiện tại có giá chào trung vị 18 triệu/m².",
        answer={"answered": True, "evidence_ids": ["ev_1"]},
    )

    assert [message.id for message in repository.list_messages(
        user_id=users.free_id,
        session_id=session.id,
        limit=20,
    )] == [user_message.id, assistant_message.id]
    with pytest.raises(OwnedResourceNotFound):
        repository.list_messages(user_id=users.vip_id, session_id=session.id, limit=20)
    feedback = repository.add_feedback(
        user_id=users.free_id,
        message_id=assistant_message.id,
        rating="helpful",
        note="Có số liệu rõ",
    )
    assert feedback.message_id == assistant_message.id
    with pytest.raises(OwnedResourceNotFound):
        repository.add_feedback(
            user_id=users.vip_id,
            message_id=assistant_message.id,
            rating="not_helpful",
        )


def test_message_content_preserves_markdown_line_breaks(repository_env):
    repository, users = repository_env
    session = repository.create_session(user_id=users.free_id, title="Phân tích")
    content = "Kết luận:\n\n- Giá chào: 18 triệu/m²\n- Cỡ mẫu: 20"

    message = repository.create_message(
        user_id=users.free_id,
        session_id=session.id,
        role="assistant",
        content=content,
        answer={"answered": True},
    )

    assert message.content == content


def test_create_run_is_idempotent_but_rejects_changed_question(repository_env):
    repository, users = repository_env
    first = repository.create_run(
        user_id=users.free_id,
        question="Giá Phú Mỹ?",
        idempotency_key="question-1",
    )
    replay = repository.create_run(
        user_id=users.free_id,
        question="Giá Phú Mỹ?",
        idempotency_key="question-1",
    )

    assert replay.id == first.id
    assert replay.session_id == first.session_id
    assert replay.status == "created"
    messages = repository.list_messages(
        user_id=users.free_id,
        session_id=first.session_id,
        limit=20,
    )
    assert [(message.role, message.content) for message in messages] == [
        ("user", "Giá Phú Mỹ?"),
    ]
    with pytest.raises(IdempotencyConflict):
        repository.create_run(
            user_id=users.free_id,
            question="Giá Định Hòa?",
            idempotency_key="question-1",
        )


def _reserve_planning_run(*, run, user_id: int, tier: str = "vip") -> UUID:
    reservation_id = uuid4()
    now = datetime.now(timezone.utc)
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO radar_ask_usage (
                id, run_key, user_id, tier, model, depth,
                usage_date, usage_month, settlement_status, question_status,
                reserved_usd, reservation_expires_at
            ) VALUES (?, ?, ?, ?, 'deepseek-v4-pro', NULL,
                      ?, ?, 'reserved', 'reserved', 0.25, ?)
            """,
            (
                reservation_id,
                run.id,
                user_id,
                tier,
                now.date(),
                now.date().replace(day=1),
                now + timedelta(minutes=10),
            ),
        )
    return reservation_id


def test_planning_claim_is_exclusive_across_real_database_threads(repository_env):
    repository, users = repository_env
    run = repository.create_run(
        user_id=users.vip_id,
        question="Câu hỏi chưa khớp deterministic route",
        idempotency_key="planner-thread-claim",
    )
    _reserve_planning_run(run=run, user_id=users.vip_id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = pool.map(
            lambda owner: repository.claim_planning(
                run.id,
                user_id=users.vip_id,
                planner_id=owner,
                lease_seconds=90,
            ),
            ("planner:a", "planner:b"),
        )

    claimed = [candidate for candidate in (first, second) if candidate is not None]
    assert len(claimed) == 1
    assert claimed[0].status == "running"
    assert claimed[0].worker_id in {"planner:a", "planner:b"}
    assert claimed[0].lease_until is not None
    assert claimed[0].lease_until > datetime.now(timezone.utc)


def test_planning_claim_is_exclusive_across_real_database_processes(repository_env):
    repository, users = repository_env
    run = repository.create_run(
        user_id=users.vip_id,
        question="Câu hỏi planner tranh chấp process",
        idempotency_key="planner-process-claim",
    )
    _reserve_planning_run(run=run, user_id=users.vip_id)
    script = (
        "import sys; from uuid import UUID; "
        "from services.radar_ask.repository import RadarAskRepository; "
        "claimed=RadarAskRepository().claim_planning(UUID(sys.argv[1]), "
        "user_id=int(sys.argv[2]), planner_id=sys.argv[3], lease_seconds=90); "
        "print('claimed' if claimed is not None else 'replay')"
    )
    processes = [
        subprocess.Popen(
            [
                sys.executable,
                "-X",
                "utf8",
                "-c",
                script,
                str(run.id),
                str(users.vip_id),
                owner,
            ],
            cwd=str(Path(__file__).resolve().parents[1]),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for owner in ("planner:process-a", "planner:process-b")
    ]
    results = [process.communicate(timeout=15) for process in processes]

    assert [process.returncode for process in processes] == [0, 0], results
    outcomes = [stdout.strip().splitlines()[-1] for stdout, _stderr in results]
    assert sorted(outcomes) == ["claimed", "replay"]


def test_planning_finalize_atomically_persists_route_usage_and_handoff(repository_env):
    repository, users = repository_env
    run = repository.create_run(
        user_id=users.vip_id,
        question="Phân tích một câu hỏi chưa khớp",
        idempotency_key="planner-atomic-finalize",
    )
    reservation_id = _reserve_planning_run(run=run, user_id=users.vip_id)
    claimed = repository.claim_planning(
        run.id,
        user_id=users.vip_id,
        planner_id="planner:atomic",
        lease_seconds=90,
    )
    assert claimed is not None
    route = {
        "depth": "deep",
        "question_type": "market_trend",
        "tool_calls": [],
        "generated": True,
        "use_thinking": False,
    }
    usage = ProviderUsage(
        input_tokens=17,
        output_tokens=3,
        cache_hit_input_tokens=5,
        cache_miss_input_tokens=12,
    )

    queued = repository.finalize_planning(
        run.id,
        user_id=users.vip_id,
        planner_id="planner:atomic",
        reservation_id=reservation_id,
        planner_model="deepseek-v4-flash",
        answer_model="deepseek-v4-pro",
        effective_depth="deep",
        route=route,
        usage=usage,
        target="queued",
    )

    assert queued.status == "queued"
    assert queued.route == route
    assert queued.worker_id is None and queued.lease_until is None
    with get_conn() as conn:
        ledger = conn.execute(
            """
            SELECT planner_model, planner_prompt_tokens, planner_completion_tokens,
                   planner_cache_hit_tokens, planner_cache_miss_tokens,
                   planner_actual_usd, planner_recorded_at
            FROM radar_ask_usage WHERE id=?
            """,
            (reservation_id,),
        ).fetchone()
    assert ledger is not None
    assert tuple(ledger)[:5] == ("deepseek-v4-flash", 17, 3, 5, 12)
    assert ledger["planner_actual_usd"] > 0
    assert ledger["planner_recorded_at"] is not None


def test_planning_failure_atomically_accounts_known_usage_and_releases(repository_env):
    repository, users = repository_env
    run = repository.create_run(
        user_id=users.vip_id,
        question="Planner trả cấu trúc không hợp lệ",
        idempotency_key="planner-atomic-failure",
    )
    reservation_id = _reserve_planning_run(run=run, user_id=users.vip_id)
    claimed = repository.claim_planning(
        run.id,
        user_id=users.vip_id,
        planner_id="planner:failure",
        lease_seconds=90,
    )
    assert claimed is not None
    usage = ProviderUsage(input_tokens=41, output_tokens=9)

    failed = repository.fail_planning(
        run.id,
        user_id=users.vip_id,
        planner_id="planner:failure",
        reservation_id=reservation_id,
        planner_model="deepseek-v4-flash",
        usage=usage,
        outcome="validation_failure",
        error_code="routing_failed",
        retryable=False,
    )

    assert failed.status == "failed"
    assert failed.worker_id is None and failed.lease_until is None
    with get_conn() as conn:
        ledger = conn.execute(
            """
            SELECT settlement_status, question_status, outcome,
                   planner_prompt_tokens, planner_completion_tokens,
                   planner_actual_usd, planner_recorded_at
            FROM radar_ask_usage WHERE id=?
            """,
            (reservation_id,),
        ).fetchone()
    assert ledger is not None
    assert tuple(ledger)[:5] == (
        "released",
        "released",
        "validation_failure",
        41,
        9,
    )
    assert ledger["planner_actual_usd"] > 0
    assert ledger["planner_recorded_at"] is not None


def test_run_reads_are_owner_scoped_and_terminal_transition_is_immutable(repository_env):
    repository, users = repository_env
    run = repository.create_run(
        user_id=users.free_id,
        question="Giá Phú Mỹ?",
        idempotency_key="transition-1",
    )

    assert repository.get_run(user_id=users.free_id, run_id=run.id) is not None
    assert repository.get_run(user_id=users.vip_id, run_id=run.id) is None
    with pytest.raises(InvalidRunTransition):
        repository.transition_run(
            run.id,
            user_id=users.vip_id,
            expected={"created"},
            target="running",
        )
    running = repository.transition_run(
        run.id,
        expected={"created"},
        target="running",
    )
    completed = repository.transition_run(
        running.id,
        expected={"running"},
        target="completed",
        outcome="answered",
    )
    assert completed.status == "completed"
    assert completed.outcome == "answered"
    with pytest.raises(InvalidRunTransition):
        repository.transition_run(
            run.id,
            expected={"completed"},
            target="running",
        )
    with pytest.raises(InvalidRunTransition):
        repository.transition_run(
            run.id,
            expected={"completed"},
            target="completed",
            outcome="cancelled",
        )


def test_run_transition_atomically_persists_route_model_and_answer(repository_env):
    repository, users = repository_env
    run = repository.create_run(
        user_id=users.vip_id,
        question="Phân tích Phú Mỹ",
        idempotency_key="payload-transition-1",
    )
    route = {
        "depth": "standard",
        "question_type": "market_recommendation",
        "tool_calls": [],
        "generated": True,
    }
    running = repository.transition_run(
        run.id,
        user_id=users.vip_id,
        expected={"created"},
        target="running",
        effective_depth="standard",
        route=route,
        model="deepseek-v4-pro",
    )
    answer = {
        "answered": True,
        "depth": "standard",
        "direct_answer": "Cần kiểm tra thêm.",
        "as_of": "2026-08-04T06:30:00Z",
        "dataset_version": "signals:12",
    }
    completed = repository.transition_run(
        run.id,
        user_id=users.vip_id,
        expected={"running"},
        target="completed",
        outcome="answered",
        answer=answer,
    )

    assert running.effective_depth == "standard"
    assert running.route == route
    assert running.model == "deepseek-v4-pro"
    assert completed.answer == answer



def test_tool_and_evidence_audit_rows_are_idempotent_and_immutable(repository_env):
    repository, users = repository_env
    run = repository.create_run(
        user_id=users.vip_id,
        question="So sánh hai phường",
        idempotency_key="audit-1",
    )
    tool = repository.record_tool_call(
        run_id=run.id,
        tool_call_key="call-1",
        tool_name="compare_areas",
        arguments={"wards": ["Phú Mỹ", "Định Hòa"]},
        result_summary={"sample_size": 20},
        status="completed",
    )
    replayed_tool = repository.record_tool_call(
        run_id=run.id,
        tool_call_key="call-1",
        tool_name="compare_areas",
        arguments={"wards": ["Phú Mỹ", "Định Hòa"]},
        result_summary={"sample_size": 20},
        status="completed",
    )
    evidence = repository.record_evidence(
        run_id=run.id,
        evidence_key="ev-market-1",
        evidence_kind="market_stat",
        source_ref="market:phu-my",
        payload={"value": 18_000_000, "unit": "VND/m2"},
        min_tier="free",
        as_of=datetime(2026, 8, 4, tzinfo=timezone.utc),
    )

    assert replayed_tool.id == tool.id
    assert evidence.evidence_key == "ev-market-1"
    with pytest.raises(ImmutableAuditConflict):
        repository.record_tool_call(
            run_id=run.id,
            tool_call_key="call-1",
            tool_name="compare_areas",
            arguments={"wards": ["Khác"]},
            result_summary={"sample_size": 1},
            status="completed",
        )


def test_owned_delete_cascades_raw_content_but_preserves_usage(repository_env):
    repository, users = repository_env
    run = repository.create_run(
        user_id=users.free_id,
        question="Giá Phú Mỹ?",
        idempotency_key="delete-1",
    )
    message = repository.create_message(
        user_id=users.free_id,
        session_id=run.session_id,
        role="user",
        content="Giá Phú Mỹ?",
    )
    repository.record_tool_call(
        run_id=run.id,
        tool_call_key="delete-call",
        tool_name="get_market_trend",
        arguments={"ward": "Phú Mỹ"},
        result_summary={"sample_size": 5},
        status="completed",
    )
    repository.record_evidence(
        run_id=run.id,
        evidence_key="delete-ev",
        evidence_kind="market_stat",
        source_ref="market:phu-my",
        payload={"value": 18_000_000},
        min_tier="free",
        as_of=datetime.now(timezone.utc),
    )
    with get_conn() as conn:
        usage_id = uuid4()
        conn.execute(
            """
            INSERT INTO radar_ask_usage (
                id, run_key, user_id, tier, usage_date, usage_month,
                settlement_status, question_status, reserved_usd, actual_usd
            ) VALUES (?, ?, ?, 'free', CURRENT_DATE, date_trunc('month', CURRENT_DATE)::date,
                      'settled', 'answered', 0, ?)
            """,
            (usage_id, run.id, users.free_id, Decimal("0.001")),
        )

    assert repository.delete_session(user_id=users.vip_id, session_id=run.session_id) is False
    assert repository.delete_session(user_id=users.free_id, session_id=run.session_id) is True
    with get_conn() as conn:
        assert conn.execute("SELECT 1 FROM radar_ask_messages WHERE id=?", (message.id,)).fetchone() is None
        assert conn.execute("SELECT 1 FROM radar_ask_runs WHERE id=?", (run.id,)).fetchone() is None
        assert conn.execute("SELECT 1 FROM radar_ask_tool_calls WHERE run_id=?", (run.id,)).fetchone() is None
        assert conn.execute("SELECT 1 FROM radar_ask_evidence WHERE run_id=?", (run.id,)).fetchone() is None
        assert conn.execute("SELECT 1 FROM radar_ask_usage WHERE id=?", (usage_id,)).fetchone() is not None


def test_delete_all_sessions_only_deletes_the_owner(repository_env):
    repository, users = repository_env
    repository.create_session(user_id=users.free_id, title="Một")
    repository.create_session(user_id=users.free_id, title="Hai")
    vip_session = repository.create_session(user_id=users.vip_id, title="VIP")

    assert repository.delete_all_sessions(user_id=users.free_id) == 2
    assert repository.get_session(user_id=users.vip_id, session_id=vip_session.id) is not None
