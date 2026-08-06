from __future__ import annotations

from datetime import datetime, timezone
import sys
from types import ModuleType, SimpleNamespace
from uuid import uuid4


if "redis" not in sys.modules:
    redis_module = ModuleType("redis")
    redis_module.Redis = type("Redis", (), {})
    redis_exceptions_module = ModuleType("redis.exceptions")
    redis_exceptions_module.RedisError = RuntimeError
    redis_module.exceptions = redis_exceptions_module
    sys.modules["redis"] = redis_module
    sys.modules["redis.exceptions"] = redis_exceptions_module

from services.radar_ask import service
from services.radar_ask.contracts import (
    AskContext,
    AskQuestionRequest,
    AskRunResult,
    RunStatus,
)
from services.radar_ask.repository import (
    RadarAskMessageRecord,
    RadarAskSessionContextRecord,
)


NOW = datetime(2026, 8, 6, 6, 0, tzinfo=timezone.utc)


class FakeContextRepository:
    def __init__(self, stored):
        self.stored = stored
        self.calls = []

    def load_session_context(self, **kwargs):
        self.calls.append(dict(kwargs))
        return self.stored


def test_run_radar_question_hydrates_only_the_owned_current_session(monkeypatch):
    session_id = uuid4()
    stored = RadarAskSessionContextRecord(
        messages=(
            RadarAskMessageRecord(
                id=uuid4(),
                session_id=session_id,
                run_id=None,
                role="user",
                content="Đất Định Hòa thì sao?",
                answer=None,
                created_at=NOW,
            ),
        ),
        routes=(
            {
                "depth": "fast",
                "question_type": "market_trend",
                "tool_calls": [
                    {
                        "call_id": "context-trend",
                        "name": "get_market_trend",
                        "arguments": {"ward": "Định Hòa", "window_days": 90},
                    }
                ],
                "generated": False,
            },
        ),
    )
    repository = FakeContextRepository(stored)
    captured = {}
    dependency_marker = SimpleNamespace(repository=repository)
    monkeypatch.setattr(service, "get_repository", lambda: repository)

    def fake_dependencies(repository=None):
        captured["dependency_repository"] = repository
        return dependency_marker

    monkeypatch.setattr(service, "_dependencies", fake_dependencies)

    def fake_run_question(request, context, *, dependencies, idempotency_key):
        captured["context"] = context
        captured["dependencies"] = dependencies
        return AskRunResult(
            run_id=uuid4(),
            session_id=session_id,
            status=RunStatus.COMPLETED,
        )

    monkeypatch.setattr(service, "run_question", fake_run_question)

    result = service.run_radar_question(
        AskQuestionRequest(
            question="Giá tầm 3 tỷ thôi",
            session_id=session_id,
        ),
        AskContext(user_id=7, tier="admin"),
        idempotency_key="follow-up",
    )

    assert result.status is RunStatus.COMPLETED
    assert repository.calls == [{"user_id": 7, "session_id": session_id}]
    assert captured["context"].session_memory.wards == ["Định Hòa"]
    assert captured["context"].recent_turns == ["user: Đất Định Hòa thì sao?"]
    assert captured["dependency_repository"] is repository
    assert captured["dependencies"] is dependency_marker


def test_run_radar_question_without_session_does_not_load_chat_memory(monkeypatch):
    repository = FakeContextRepository(
        RadarAskSessionContextRecord(messages=(), routes=())
    )
    captured = {}
    monkeypatch.setattr(service, "get_repository", lambda: repository)
    monkeypatch.setattr(
        service,
        "_dependencies",
        lambda repository=None: SimpleNamespace(repository=repository),
    )

    def fake_run_question(request, context, *, dependencies, idempotency_key):
        captured["context"] = context
        return AskRunResult(
            run_id=uuid4(),
            session_id=uuid4(),
            status=RunStatus.COMPLETED,
        )

    monkeypatch.setattr(service, "run_question", fake_run_question)

    service.run_radar_question(
        AskQuestionRequest(question="Xin chào"),
        AskContext(user_id=8, tier="free"),
        idempotency_key="new-chat",
    )

    assert repository.calls == []
    assert captured["context"].recent_turns == []
    assert captured["context"].session_memory.wards == []
