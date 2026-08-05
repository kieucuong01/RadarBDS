from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from threading import Event, Lock
from uuid import uuid4

import pytest

from db import connection
from db.connection import get_conn
from db.schema import init_schema
from services.radar_ask.config import RadarAskSettings
from services.radar_ask.contracts import (
    AskContext,
    AskQuestionRequest,
    EvidenceBundle,
    EvidenceItem,
    ProviderResponse,
    ProviderUsage,
    RetrievalQuality,
    RouteDecision,
    SourceKind,
    ToolCall,
)
from services.radar_ask.limits import BudgetHardStop, RadarAskLimitService
from services.radar_ask.orchestrator import OrchestratorDependencies, run_question
from services.radar_ask.planner import DeepSeekTypedPlanner
from services.radar_ask.registry import DEFAULT_TOOL_REGISTRY, ToolRegistration, ToolRegistry
from services.radar_ask.repository import RadarAskRepository
from services.radar_ask.routing import route_question


NOW = datetime(2042, 2, 3, 4, 0, tzinfo=timezone.utc)


def _assert_test_database() -> None:
    with get_conn() as conn:
        database = conn.execute("SELECT current_database() AS name").fetchone()["name"]
    assert database == "radar_bds_test"


@pytest.fixture
def database_user():
    connection.close_all()
    init_schema()
    _assert_test_database()
    token = uuid4().hex
    with get_conn() as conn:
        cursor = conn.execute(
            """
            INSERT INTO users (identifier, identifier_type, password_hash, tier)
            VALUES (?, 'email', 'test-hash', 'vip')
            """,
            (f"radar-ask-concurrency-{token}@example.test",),
        )
        user_id = int(cursor.lastrowid)
    yield user_id
    with get_conn() as conn:
        conn.execute("DELETE FROM radar_ask_usage WHERE user_id=?", (user_id,))
        conn.execute("DELETE FROM users WHERE id=?", (user_id,))
    connection.close_all()


class _Burst:
    def check(self, **_kwargs):
        return None


def _evidence() -> EvidenceBundle:
    return EvidenceBundle(
        question_snapshot="Phân tích khu này",
        calculations={"answer_summary": "Phú Mỹ có 3 tín hiệu cần kiểm tra."},
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


def _registry() -> ToolRegistry:
    metadata = DEFAULT_TOOL_REGISTRY.get("rank_price_drop_areas")
    return ToolRegistry(
        {
            metadata.name: ToolRegistration(
                name=metadata.name,
                description=metadata.description,
                args_model=metadata.args_model,
                handler=lambda *, args, context: _evidence(),
            )
        }
    )


def _answer() -> dict[str, object]:
    return {
        "answered": True,
        "depth": "standard",
        "verdict": "can_kiem_tra_them",
        "direct_answer": "Phú Mỹ có 3 tín hiệu cần kiểm tra.",
        "claims": [
            {
                "text": "Có 3 tín hiệu trong mẫu hiện tại.",
                "evidence_ids": ["market:phu-my:drop-count"],
                "numeric_value": "3",
                "unit": "tin",
            }
        ],
        "as_of": NOW.isoformat(),
        "dataset_version": "signals:12",
    }


class _TwoStageProvider:
    def __init__(self):
        self.started = Event()
        self.release = Event()
        self.lock = Lock()
        self.requests = []

    def complete_until(self, request, *, deadline):
        with self.lock:
            index = len(self.requests)
            self.requests.append(request)
        if index == 0:
            self.started.set()
            assert self.release.wait(timeout=5)
            return ProviderResponse(
                json_value=RouteDecision(
                    depth="standard",
                    question_type="market_research",
                    tool_calls=[
                        ToolCall(
                            call_id="market-1",
                            name="rank_price_drop_areas",
                            arguments={"window_days": 30, "limit": 10},
                        )
                    ],
                    generated=True,
                ).model_dump(mode="json"),
                usage=ProviderUsage(input_tokens=10, output_tokens=2),
            )
        return ProviderResponse(
            json_value=_answer(),
            usage=ProviderUsage(input_tokens=20, output_tokens=4),
        )


def test_same_idempotency_key_runs_one_planner_and_one_answer_call(database_user):
    _assert_test_database()
    repository = RadarAskRepository()
    provider = _TwoStageProvider()
    settings = replace(
        RadarAskSettings.from_env(),
        enabled=True,
        allowed_tiers=frozenset({"vip"}),
        router_model="deepseek-v4-flash",
        smart_model="deepseek-v4-pro",
        provider_timeout_seconds=30,
        deep_timeout_seconds=60,
    )
    dependencies = OrchestratorDependencies(
        settings=settings,
        repository=repository,
        limits=RadarAskLimitService(settings=settings, now_fn=lambda: NOW),
        burst=_Burst(),
        router=route_question,
        registry=_registry(),
        provider=provider,
        planner=DeepSeekTypedPlanner(
            settings=settings,
            provider=provider,
            registry=_registry(),
        ),
        clock=lambda: NOW,
    )
    request = AskQuestionRequest(question="Khu này đang có xu hướng gì?")
    context = AskContext(user_id=database_user, tier="vip")
    key = f"same-key-{uuid4()}"

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(
            run_question,
            request,
            context,
            dependencies=dependencies,
            idempotency_key=key,
        )
        assert provider.started.wait(timeout=5)
        replay = pool.submit(
            run_question,
            request,
            context,
            dependencies=dependencies,
            idempotency_key=key,
        )
        replay_result = replay.result(timeout=5)
        provider.release.set()
        first_result = first.result(timeout=5)

    assert first_result.run_id == replay_result.run_id
    assert len(provider.requests) == 2
    with get_conn() as conn:
        run = conn.execute(
            "SELECT id, status FROM radar_ask_runs WHERE user_id=? AND idempotency_key=?",
            (database_user, key),
        ).fetchone()
        ledger_count = conn.execute(
            "SELECT COUNT(*) AS count FROM radar_ask_usage WHERE run_key=?",
            (run["id"],),
        ).fetchone()["count"]
        roles = [
            row["role"]
            for row in conn.execute(
                "SELECT role FROM radar_ask_messages WHERE run_id=? ORDER BY created_at",
                (run["id"],),
            ).fetchall()
        ]
    assert run["status"] == "completed"
    assert ledger_count == 1
    assert roles == ["user", "assistant"]


def test_monthly_budget_contention_never_crosses_50(database_user):
    _assert_test_database()
    settings = replace(
        RadarAskSettings.from_env(),
        monthly_warning_usd=Decimal("20"),
        monthly_hard_stop_usd=Decimal("50"),
        cost_safety_multiplier=Decimal("2"),
    )
    service = RadarAskLimitService(settings=settings, now_fn=lambda: NOW)

    def reserve(_index):
        try:
            return service.reserve_question(
                user_id=database_user,
                tier="admin",
                run_id=uuid4(),
                max_cost_usd=Decimal("3"),
                model="deepseek-v4-pro",
                depth="standard",
            )
        except BudgetHardStop as exc:
            return exc

    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(reserve, range(20)))

    accepted = [item for item in results if not isinstance(item, BudgetHardStop)]
    rejected = [item for item in results if isinstance(item, BudgetHardStop)]
    snapshot = service.month_snapshot()
    assert accepted and rejected
    assert sum(item.reserved_usd for item in accepted) == Decimal("48.000000")
    assert snapshot.committed_plus_reserved_usd == Decimal("48.000000")
    assert snapshot.committed_plus_reserved_usd <= Decimal("50")
