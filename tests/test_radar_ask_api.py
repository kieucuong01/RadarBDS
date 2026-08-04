from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

import app as radar_app
from services.radar_ask.contracts import AnswerEnvelope, AskDepth, AskRunResult, RunStatus
from services.radar_ask.limits import BudgetHardStop, QuotaExceeded


NOW = datetime(2026, 8, 5, 4, 0, tzinfo=timezone.utc)


def answered_run(*, status: RunStatus = RunStatus.COMPLETED) -> AskRunResult:
    return AskRunResult(
        run_id=uuid4(),
        session_id=uuid4(),
        status=status,
        answer=AnswerEnvelope(
            answered=True,
            depth=AskDepth.FAST,
            direct_answer="Mau du lieu hien tai cho thay gia chao can kiem tra them.",
            next_verification_steps=["Kiem tra phap ly"],
            as_of=NOW,
            dataset_version="signals:12",
        ),
    )


@dataclass
class FakeRepository:
    run: object | None = None
    sessions: list[object] | None = None
    messages: list[object] | None = None
    deleted: list[UUID] | None = None

    def __post_init__(self):
        self.sessions = self.sessions or []
        self.messages = self.messages or []
        self.deleted = self.deleted or []

    def get_run(self, *, user_id, run_id):
        return self.run if self.run and self.run.user_id == user_id else None

    def list_sessions(self, *, user_id, limit, before_updated_at=None, before_id=None):
        return self.sessions[:limit]

    def get_session(self, *, user_id, session_id):
        return next((item for item in self.sessions if item.id == session_id and item.user_id == user_id), None)

    def list_messages(self, *, user_id, session_id, limit, before_created_at=None, before_id=None):
        if self.get_session(user_id=user_id, session_id=session_id) is None:
            from services.radar_ask.repository import OwnedResourceNotFound

            raise OwnedResourceNotFound()
        return self.messages[:limit]

    def rename_session(self, *, user_id, session_id, title):
        session = self.get_session(user_id=user_id, session_id=session_id)
        if session is None:
            return None
        return SimpleNamespace(**{**session.__dict__, "title": title})

    def delete_session(self, *, user_id, session_id):
        if self.get_session(user_id=user_id, session_id=session_id) is None:
            return False
        self.deleted.append(session_id)
        return True

    def delete_all_sessions(self, *, user_id):
        return len([item for item in self.sessions if item.user_id == user_id])

    def add_feedback(self, *, user_id, message_id, rating, note=None):
        message = next((item for item in self.messages if item.id == message_id), None)
        if message is None or self.get_session(user_id=user_id, session_id=message.session_id) is None:
            from services.radar_ask.repository import OwnedResourceNotFound

            raise OwnedResourceNotFound()
        return SimpleNamespace(id=uuid4(), message_id=message_id, user_id=user_id, rating=rating, note=note, created_at=NOW)


@pytest.fixture
def api_client(monkeypatch):
    import routes.radar_ask_api as ask_api

    monkeypatch.setenv("RADAR_ASK_ENABLED", "1")
    monkeypatch.setenv("RADAR_ASK_ALLOWED_TIERS", "free,vip,admin")
    monkeypatch.setattr(ask_api, "current_user", lambda: {"id": 11, "tier": "free"})
    monkeypatch.setattr(ask_api, "current_tier", lambda: "free")
    monkeypatch.setattr(ask_api, "get_repository", lambda: FakeRepository())
    monkeypatch.setattr(ask_api, "run_radar_question", lambda *args, **kwargs: answered_run())
    return radar_app.app.test_client()


def assert_private(response):
    assert response.headers["Cache-Control"] == "private, no-store"
    assert "X-Radar-Public-Cache" not in response.headers


def test_feature_off_fails_closed_without_public_cache(monkeypatch):
    monkeypatch.delenv("RADAR_ASK_ENABLED", raising=False)
    client = radar_app.app.test_client()

    page = client.get("/hoi-radar-bds")
    response = client.get("/api/radar-ask/sessions")

    assert page.status_code == response.status_code == 404
    assert_private(page)
    assert_private(response)


def test_guest_cannot_open_or_ask(monkeypatch):
    import routes.radar_ask_api as ask_api

    monkeypatch.setenv("RADAR_ASK_ENABLED", "1")
    monkeypatch.setattr(ask_api, "current_user", lambda: None)
    monkeypatch.setattr(ask_api, "current_tier", lambda: "guest")
    client = radar_app.app.test_client()

    assert client.get("/hoi-radar-bds").status_code == 401
    response = client.post("/api/radar-ask/questions", json={"question": "Gia Phu My?"})
    assert response.status_code == 401
    assert response.get_json()["error"]["code"] == "login_required"
    assert_private(response)


@pytest.mark.parametrize("tier", ("free", "vip", "admin"))
def test_authenticated_allowed_tiers_can_open_private_page(api_client, monkeypatch, tier):
    import routes.radar_ask_api as ask_api
    import routes.public as public_routes

    monkeypatch.setattr(ask_api, "current_user", lambda: {"id": 11, "tier": tier})
    monkeypatch.setattr(ask_api, "current_tier", lambda: tier)
    monkeypatch.setattr(public_routes, "current_user", lambda: {"id": 11, "tier": tier})
    monkeypatch.setattr(public_routes, "current_tier", lambda: tier)

    response = api_client.get("/hoi-radar-bds")
    assert response.status_code == 200
    assert_private(response)


@pytest.mark.parametrize("payload", ({}, {"question": " "}, {"question": "x" * 2001}))
def test_question_rejects_invalid_or_oversized_json(api_client, payload):
    response = api_client.post("/api/radar-ask/questions", json=payload)
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "invalid_request"
    assert_private(response)


def test_write_rejects_cross_site_session_request(api_client):
    from auth.core import SESSION_COOKIE_NAME

    api_client.set_cookie(SESSION_COOKIE_NAME, "session-bound-request")
    response = api_client.post(
        "/api/radar-ask/questions",
        json={"question": "Gia Phu My?"},
        headers={"Origin": "https://attacker.example"},
    )
    assert response.status_code == 403
    assert response.get_json()["error"]["code"] == "cross_site_request"
    assert_private(response)


def test_fast_question_returns_public_answer_contract_and_idempotency(api_client, monkeypatch):
    import routes.radar_ask_api as ask_api

    calls = []

    def fake_run(request, context, *, idempotency_key):
        calls.append((request.question, context.user_id, context.tier, idempotency_key))
        return answered_run()

    monkeypatch.setattr(ask_api, "run_radar_question", fake_run)
    response = api_client.post(
        "/api/radar-ask/questions",
        json={"question": " Gia Phu My? "},
        headers={"Idempotency-Key": "request-11"},
    )
    body = response.get_json()

    assert response.status_code == 200
    assert set(("run_id", "session_id", "status", "answer", "quota", "cost_state")) <= set(body)
    assert body["answer"]["next_checks"] == ["Kiem tra phap ly"]
    assert "next_verification_steps" not in body["answer"]
    assert calls == [("Gia Phu My?", 11, "free", "request-11")]
    assert_private(response)


def test_deep_question_returns_accepted(api_client, monkeypatch):
    import routes.radar_ask_api as ask_api

    monkeypatch.setattr(ask_api, "run_radar_question", lambda *args, **kwargs: answered_run(status=RunStatus.QUEUED))
    response = api_client.post("/api/radar-ask/questions", json={"question": "Nghien cuu sau Phu My"})

    assert response.status_code == 202
    assert response.get_json()["status"] == "queued"
    assert_private(response)


@pytest.mark.parametrize(
    ("error", "status", "code"),
    (
        (QuotaExceeded(tier="free", limit=5, used=5, reset_at=NOW), 429, "daily_quota_exceeded"),
        (BudgetHardStop(projected_usd=1, hard_stop_usd=1), 507, "monthly_budget_hard_stop"),
    ),
)
def test_quota_and_budget_errors_are_sanitized(api_client, monkeypatch, error, status, code):
    import routes.radar_ask_api as ask_api

    def raise_error(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(ask_api, "run_radar_question", raise_error)
    response = api_client.post("/api/radar-ask/questions", json={"question": "Gia Phu My?"})
    assert response.status_code == status
    assert response.get_json()["error"]["code"] == code
    assert_private(response)


def test_cross_user_run_is_not_disclosed(api_client, monkeypatch):
    import routes.radar_ask_api as ask_api

    foreign = SimpleNamespace(
        id=uuid4(), session_id=uuid4(), user_id=22, status="completed", answer=None,
        retryable=False, error_code=None,
    )
    monkeypatch.setattr(ask_api, "get_repository", lambda: FakeRepository(run=foreign))
    response = api_client.get(f"/api/radar-ask/runs/{foreign.id}")
    assert response.status_code == 404
    assert_private(response)
    assert str(foreign.id) not in response.get_data(as_text=True)


def test_invalid_session_cursor_is_rejected_without_database_fallback(api_client):
    response = api_client.get("/api/radar-ask/sessions?cursor=%25%25%25")

    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "invalid_request"
    assert_private(response)


def test_history_repository_failure_returns_private_generic_service_error(api_client, monkeypatch):
    import routes.radar_ask_api as ask_api

    class FailingRepository:
        def list_sessions(self, **_kwargs):
            raise RuntimeError("database pool password=do-not-disclose")

    monkeypatch.setattr(ask_api, "get_repository", lambda: FailingRepository())
    response = api_client.get("/api/radar-ask/sessions")

    assert response.status_code == 503
    assert response.get_json() == {
        "error": {
            "code": "service_unavailable",
            "message": "Dich vu tam thoi chua san sang.",
        }
    }
    assert "password" not in response.get_data(as_text=True)
    assert_private(response)


def test_session_history_rename_delete_and_feedback_are_owner_scoped(api_client, monkeypatch):
    import routes.radar_ask_api as ask_api

    session = SimpleNamespace(id=uuid4(), user_id=11, title="Phu My", summary={}, created_at=NOW, updated_at=NOW)
    message = SimpleNamespace(id=uuid4(), session_id=session.id, role="assistant", content="Noi dung", answer=None, created_at=NOW)
    repo = FakeRepository(sessions=[session], messages=[message])
    monkeypatch.setattr(ask_api, "get_repository", lambda: repo)

    listed = api_client.get("/api/radar-ask/sessions?limit=999")
    detail = api_client.get(f"/api/radar-ask/sessions/{session.id}?message_limit=999")
    renamed = api_client.patch(f"/api/radar-ask/sessions/{session.id}", json={"title": "Ten moi"})
    feedback = api_client.post(f"/api/radar-ask/messages/{message.id}/feedback", json={"rating": "helpful"})
    deleted = api_client.delete(f"/api/radar-ask/sessions/{session.id}")
    deleted_all = api_client.delete("/api/radar-ask/sessions")

    assert listed.status_code == detail.status_code == renamed.status_code == feedback.status_code == 200
    assert listed.get_json()["limit"] == 50
    assert detail.get_json()["message_limit"] == 100
    assert renamed.get_json()["session"]["title"] == "Ten moi"
    assert feedback.get_json()["feedback"]["rating"] == "helpful"
    assert deleted.status_code == deleted_all.status_code == 204
    for response in (listed, detail, renamed, feedback, deleted, deleted_all):
        assert_private(response)
