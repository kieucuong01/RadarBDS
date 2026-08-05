from __future__ import annotations

import os
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

import app as radar_app
from db import radar_ask_connection
from services.radar_ask.config import RadarAskSettings
from services.radar_ask.contracts import (
    AskContext,
    AskDepth,
    AskQuestionRequest,
    EvidenceItem,
    RouteDecision,
    RunStatus,
    SourceKind,
    ToolCall,
    UsageReservation,
)
from services.radar_ask.evidence import EvidenceBuilder
from services.radar_ask.orchestrator import OrchestratorDependencies
from services.radar_ask.registry import DEFAULT_TOOL_REGISTRY
from scripts.verify_radar_ask_ui import _valid_qa_capability


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 8, 5, 6, 0, tzinfo=timezone.utc)
MAX_RESPONSE_BYTES = 128 * 1024


@dataclass(frozen=True)
class _Run:
    id: UUID
    session_id: UUID
    user_id: int
    idempotency_key: str
    question: str
    requested_depth: str | None
    status: str = "created"
    effective_depth: str | None = None
    route: dict[str, object] | None = None
    answer: dict[str, object] | None = None
    model: str | None = None
    outcome: str | None = None
    error_code: str | None = None
    retryable: bool = False
    worker_id: str | None = None
    lease_until: datetime | None = None


class _CountingRepository:
    def __init__(self) -> None:
        self.run: _Run | None = None
        self.calls: list[str] = []
        self.tool_calls: list[dict[str, object]] = []

    def create_run(self, **kwargs):
        self.calls.append("create_run")
        if self.run is None:
            self.run = _Run(
                id=uuid4(),
                session_id=kwargs["session_id"] or uuid4(),
                user_id=kwargs["user_id"],
                idempotency_key=kwargs["idempotency_key"],
                question=kwargs["question"],
                requested_depth=kwargs["requested_depth"],
            )
        return self.run

    def get_run(self, *, user_id, run_id):
        self.calls.append("get_run")
        return self.run if self.run and (self.run.user_id, self.run.id) == (user_id, run_id) else None

    def claim_reserved_run(self, _run_id, **kwargs):
        self.calls.append("claim_reserved_run")
        assert self.run is not None and self.run.status == "created"
        self.run = replace(
            self.run,
            status="running",
            worker_id=kwargs["owner_id"],
            effective_depth=kwargs.get("effective_depth"),
            route=kwargs.get("route"),
            model=kwargs.get("model"),
        )
        return self.run

    def transition_run(self, _run_id, **kwargs):
        self.calls.append("transition_run")
        assert self.run is not None and self.run.status in kwargs["expected"]
        self.run = replace(
            self.run,
            status=kwargs["target"],
            worker_id=None if kwargs["target"] != "running" else self.run.worker_id,
        )
        return self.run

    def finalize_sync_run(self, _run_id, **kwargs):
        self.calls.append("finalize_sync_run")
        assert self.run is not None and self.run.worker_id == kwargs["owner_id"]
        self.run = replace(
            self.run,
            status=kwargs["target"],
            outcome=kwargs["outcome"],
            answer=kwargs["answer"],
            worker_id=None,
        )
        return self.run

    def record_tool_call(self, **kwargs):
        self.tool_calls.append(dict(kwargs))

    def record_evidence(self, **_kwargs):
        raise AssertionError("Deep enqueue must not persist evidence inline")


class _Limits:
    def reserve_question(self, **kwargs):
        return UsageReservation(
            reservation_id=uuid4(),
            run_id=kwargs["run_id"],
            user_id=kwargs["user_id"],
            tier=kwargs["tier"],
            reserved_usd=Decimal("0"),
        )


class _Burst:
    def check(self, **_kwargs):
        return None


class _ProviderSpy:
    def __init__(self) -> None:
        self.requests: list[object] = []

    def complete(self, request):
        self.requests.append(request)
        raise AssertionError("deterministic/queued request must not call a provider")


def _settings() -> RadarAskSettings:
    return RadarAskSettings(
        enabled=True,
        allowed_tiers=frozenset({"free", "vip", "admin"}),
        deepseek_api_key="offline-test-key",
        deepseek_base_url="https://api.deepseek.com",
        database_url="postgresql://radar_ask_ro:test@127.0.0.1:15432/radar_bds_test",
        db_pool_max=1,
        db_pool_timeout_seconds=1.0,
        router_model="deepseek-v4-flash",
        free_model="deepseek-v4-flash",
        smart_model="deepseek-v4-pro",
        monthly_warning_usd=Decimal("20"),
        monthly_hard_stop_usd=Decimal("50"),
        cost_safety_multiplier=Decimal("2"),
        retention_days=90,
        usage_retention_months=13,
        provider_timeout_seconds=30,
        deep_timeout_seconds=60,
        worker_concurrency=2,
        statement_timeout_ms=2_000,
        evidence_row_limit=50,
        knowledge_vector_enabled=False,
    )


def _client_for(monkeypatch, decision: RouteDecision):
    import routes.radar_ask_api as ask_api
    import services.radar_ask.service as ask_service

    repository = _CountingRepository()
    provider = _ProviderSpy()
    dependencies = OrchestratorDependencies(
        settings=_settings(),
        repository=repository,
        limits=_Limits(),
        burst=_Burst(),
        router=lambda *_args, **_kwargs: decision,
        registry=DEFAULT_TOOL_REGISTRY,
        provider=provider,
        clock=lambda: NOW,
        persistence_sleep=lambda _seconds: None,
    )
    monkeypatch.setenv("RADAR_ASK_ENABLED", "1")
    monkeypatch.setenv("RADAR_ASK_ALLOWED_TIERS", "free,vip,admin")
    monkeypatch.setattr(ask_api, "current_user", lambda: {"id": 17, "tier": "vip"})
    monkeypatch.setattr(ask_api, "current_tier", lambda: "vip")
    monkeypatch.setattr(ask_service, "_dependencies", lambda: dependencies)
    return radar_app.app.test_client(), repository, provider


def _assert_private_bounded(response) -> None:
    assert response.headers["Cache-Control"] == "private, no-store"
    assert "X-Radar-Public-Cache" not in response.headers
    assert len(response.data) <= MAX_RESPONSE_BYTES


def test_fast_request_has_zero_provider_calls_and_bounded_work(monkeypatch):
    decision = RouteDecision(
        depth=AskDepth.FAST,
        question_type="performance_probe",
        generated=False,
    )
    client, repository, provider = _client_for(monkeypatch, decision)

    response = client.post(
        "/api/radar-ask/questions",
        json={"question": "Tóm tắt nhanh dữ liệu hiện có", "requested_depth": "fast"},
        headers={"Idempotency-Key": "perf-fast-1"},
    )

    assert response.status_code == 200
    assert response.get_json()["status"] == RunStatus.INSUFFICIENT.value
    assert provider.requests == []
    assert repository.calls == ["create_run", "claim_reserved_run", "finalize_sync_run"]
    _assert_private_bounded(response)


def test_deep_submit_enqueues_without_inline_tool_or_provider_execution(monkeypatch):
    decision = RouteDecision(
        depth=AskDepth.DEEP,
        question_type="performance_probe",
        tool_calls=[
            ToolCall(
                call_id="perf-deep-1",
                name="rank_price_drop_areas",
                arguments={"window_days": 30, "limit": 10},
            )
        ],
        generated=False,
    )
    client, repository, provider = _client_for(monkeypatch, decision)

    response = client.post(
        "/api/radar-ask/questions",
        json={"question": "Nghiên cứu sâu khu Phú Mỹ", "requested_depth": "deep"},
        headers={"Idempotency-Key": "perf-deep-1"},
    )

    assert response.status_code == 202
    assert response.get_json()["status"] == RunStatus.QUEUED.value
    assert provider.requests == []
    assert repository.tool_calls == []
    assert repository.calls == ["create_run", "claim_reserved_run", "transition_run"]
    _assert_private_bounded(response)


def test_history_and_poll_payloads_are_paginated_private_and_bounded(monkeypatch):
    import routes.radar_ask_api as ask_api

    session_id = uuid4()
    run_id = uuid4()
    sessions = [
        SimpleNamespace(
            id=uuid4(), user_id=17, title=f"Phiên {index}", summary={}, created_at=NOW, updated_at=NOW
        )
        for index in range(50)
    ]
    sessions[0] = SimpleNamespace(
        id=session_id, user_id=17, title="Phiên hiện tại", summary={}, created_at=NOW, updated_at=NOW
    )
    messages = [
        SimpleNamespace(
            id=uuid4(), session_id=session_id, run_id=None, role="assistant",
            content="Nội dung ngắn", answer=None, created_at=NOW,
        )
        for _index in range(100)
    ]
    run = SimpleNamespace(
        id=run_id, session_id=session_id, user_id=17, status="queued", answer=None,
        retryable=False, error_code=None,
    )

    class HistoryRepository:
        requested_limits: list[int] = []

        def list_sessions(self, *, limit, **_kwargs):
            self.requested_limits.append(limit)
            return sessions[:limit]

        def get_session(self, *, user_id, session_id: UUID):
            return sessions[0] if user_id == 17 and session_id == sessions[0].id else None

        def list_messages(self, *, limit, **_kwargs):
            self.requested_limits.append(limit)
            return messages[:limit]

        def get_run(self, *, user_id, run_id: UUID):
            return run if user_id == 17 and run_id == run.id else None

    repository = HistoryRepository()
    monkeypatch.setenv("RADAR_ASK_ENABLED", "1")
    monkeypatch.setenv("RADAR_ASK_ALLOWED_TIERS", "vip")
    monkeypatch.setattr(ask_api, "current_user", lambda: {"id": 17, "tier": "vip"})
    monkeypatch.setattr(ask_api, "current_tier", lambda: "vip")
    monkeypatch.setattr(ask_api, "get_repository", lambda: repository)
    client = radar_app.app.test_client()

    responses = (
        client.get("/api/radar-ask/sessions?limit=999"),
        client.get(f"/api/radar-ask/sessions/{session_id}?message_limit=999"),
        client.get(f"/api/radar-ask/runs/{run_id}"),
    )

    assert [response.status_code for response in responses] == [200, 200, 200]
    assert repository.requested_limits == [50, 100]
    assert len(responses[0].get_json()["sessions"]) == 50
    assert len(responses[1].get_json()["messages"]) == 100
    for response in responses:
        _assert_private_bounded(response)


def test_evidence_rows_and_read_statement_time_are_hard_bounded(monkeypatch):
    builder = EvidenceBuilder(question_snapshot="Đo giới hạn bằng dữ liệu giả", row_limit=50)
    for index in range(51):
        builder.add(
            EvidenceItem(
                evidence_id=f"perf:{index}",
                source_kind=SourceKind.MARKET_STAT,
                source_ref=f"fixture:{index}",
                value=index,
                as_of=NOW,
                dataset_version="fixture:v1",
            )
        )
    bundle = builder.build()
    assert len(bundle.items) == 50
    assert "evidence_row_limit_reached" in bundle.warnings

    class FakeConnection:
        def __init__(self) -> None:
            self.statements: list[tuple[str, object]] = []

        def execute(self, sql, params=None):
            self.statements.append((" ".join(str(sql).split()), params))
            return self

        @contextmanager
        def transaction(self):
            yield self

    connection = FakeConnection()

    class FakePool:
        @contextmanager
        def connection(self, **_kwargs):
            yield connection

    monkeypatch.setattr(radar_ask_connection, "get_radar_ask_read_pool", lambda **_kwargs: FakePool())
    with radar_ask_connection.get_radar_ask_read_conn(settings=_settings()):
        pass

    assert connection.statements == [
        ("SET TRANSACTION READ ONLY", None),
        ("SELECT set_config('statement_timeout', %s, true)", ("2000",)),
    ]


def test_rendered_verifier_has_safe_offline_config_check(tmp_path):
    env = {
        **os.environ,
        "RADAR_ASK_TEST_IDENTIFIER": "seeded-vip@example.test",
        "RADAR_ASK_TEST_PASSWORD": "fixture-password",
        "RADAR_ASK_FAKE_PROVIDER": "1",
    }
    result = subprocess.run(
        [
            sys.executable,
            "-X",
            "utf8",
            "scripts/verify_radar_ask_ui.py",
            "--check-config",
            "--base-url",
            "http://127.0.0.1:5000",
            "--output",
            str(ROOT / "artifacts" / "radar-ask" / "config-check"),
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert list(tmp_path.iterdir()) == []


def test_rendered_verifier_requires_server_owned_fake_provider_and_test_db_proof():
    valid = {
        "mode": "radar_ask_test",
        "provider": "fake",
        "database": "radar_bds_test",
        "live_provider_allowed": False,
    }
    headers = {"X-Radar-Ask-QA-Provider": "fake"}

    assert _valid_qa_capability(valid, headers) is True
    for changed in (
        {**valid, "provider": "deepseek"},
        {**valid, "database": "radar_bds"},
        {**valid, "live_provider_allowed": True},
    ):
        assert _valid_qa_capability(changed, headers) is False
    assert _valid_qa_capability(valid, {}) is False

    source = (ROOT / "scripts" / "verify_radar_ask_ui.py").read_text(encoding="utf-8")
    main_source = source[source.index("def main()") :]
    assert main_source.index("_verify_server_capability") < main_source.index("sync_playwright")
    assert "login_user.get(\"tier\") != \"admin\"" in source
    assert "observation[\"path\"] == f'/api/radar-ask/runs/{deep[\"run_id\"]}'" in source
    assert "observation[\"http_status\"] == 200" in source
    assert "deep_terminal_poll_count" in source


def test_k6_profile_is_valid_ecmascript_without_installing_k6():
    script = ROOT / "scripts" / "load" / "radar_ask_load.js"
    source = script.read_text(encoding="utf-8")
    result = subprocess.run(
        ["node", "--input-type=module", "--check"],
        cwd=ROOT,
        input=source,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert "executor: 'per-vu-iterations'" in source
    assert "executor: 'constant-vus'" not in source
    assert "iterations: 1" in source
    assert "AUTHENTICATED_SCENARIOS.length * VUS_PER_SCENARIO" in source
    assert "/api/radar-ask/qa-capabilities" in source
    assert "live_provider_allowed === false" in source
    assert "from 'k6/execution'" in source
    assert "sleep(" not in source
    assert "VUS_PER_SCENARIO || '20'" in source
    assert "PUBLIC_PATHS[publicIndex]" in source
    assert "PUBLIC_PATHS[__ITER" not in source


def test_committed_qa_harness_is_loopback_fake_and_test_database_only():
    source = (ROOT / "scripts" / "radar_ask_qa_server.py").read_text(encoding="utf-8")

    assert 'database != "radar_bds_test"' in source
    assert 'run_simple(\n        "127.0.0.1"' in source
    assert 'os.environ.pop("DEEPSEEK_API_KEY", None)' in source
    assert '"live_provider_allowed": False' in source
    assert 'QA_CAPABILITY_HEADER = ("X-Radar-Ask-QA-Provider", "fake")' in source
    assert "DeepSeekProvider" not in source
    assert "--seed-count" in source
    assert "default=100" in source
    main_source = source[source.index("def main(") :]
    assert main_source.index("if args.check_config") < main_source.index("_write_seed_file")
