"""Private, owner-scoped HTTP boundary for Radar Ask."""
from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from flask import Blueprint, jsonify, make_response, request
from pydantic import ValidationError
from werkzeug.exceptions import BadRequest

from auth.core import current_tier, current_user, reject_cross_site_session_request
from services.radar_ask.burst import BurstExceeded
from services.radar_ask.contracts import AskContext, AskQuestionRequest, RunStatus
from services.radar_ask.limits import BudgetHardStop, QuotaExceeded
from services.radar_ask.orchestrator import RadarAskFeatureDisabled, RadarAskTierDenied
from services.radar_ask.repository import IdempotencyConflict, OwnedResourceNotFound
from services.radar_ask.service import (
    feature_enabled,
    feedback_payload,
    get_repository,
    message_payload,
    run_payload,
    run_radar_question,
    run_record_payload,
    session_payload,
    tier_allowed,
)


bp = Blueprint("radar_ask_api", __name__)
_MAX_JSON_BYTES = 16_384


def api_error(code: str, message: str, status: int, retry_after: int | None = None):
    body: dict[str, Any] = {"error": {"code": code, "message": message}}
    if retry_after is not None:
        body["error"]["retry_after_seconds"] = retry_after
    response = jsonify(body)
    response.status_code = status
    response.headers["Cache-Control"] = "private, no-store"
    return response


def _private(response):
    response.headers["Cache-Control"] = "private, no-store"
    response.headers.pop("X-Radar-Public-Cache", None)
    return response


@bp.after_request
def _private_radar_ask_response(response):
    return _private(response)


def _gate():
    if not feature_enabled():
        return api_error("not_found", "Khong tim thay tai nguyen.", 404)
    user = current_user()
    tier = current_tier()
    if not user or tier == "guest":
        return api_error("login_required", "Vui long dang nhap de dung Radar Ask.", 401)
    if not tier_allowed(tier):
        return api_error("tier_required", "Goi tai khoan hien tai chua duoc cap Radar Ask.", 403)
    try:
        user_id = int(user["id"])
    except (KeyError, TypeError, ValueError):
        return api_error("login_required", "Vui long dang nhap de dung Radar Ask.", 401)
    if user_id <= 0:
        return api_error("login_required", "Vui long dang nhap de dung Radar Ask.", 401)
    return user_id, tier


def _write_gate():
    if not feature_enabled():
        return None
    rejected = reject_cross_site_session_request()
    if rejected is None:
        return None
    return api_error("cross_site_request", "Yeu cau khong hop le.", 403)


def _json_object() -> dict[str, Any] | None:
    if request.content_length is not None and request.content_length > _MAX_JSON_BYTES:
        return None
    try:
        payload = request.get_json(silent=False)
    except BadRequest:
        return None
    return payload if isinstance(payload, dict) else None


def _uuid(value: str) -> UUID | None:
    try:
        return UUID(value)
    except (TypeError, ValueError, AttributeError):
        return None


def _cursor(value: str | None) -> tuple[datetime, UUID] | None:
    if not value:
        return None
    try:
        padded = value + "=" * (-len(value) % 4)
        raw = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
        stamp = datetime.fromisoformat(str(raw["at"]))
        identifier = UUID(str(raw["id"]))
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            return None
        return stamp.astimezone(timezone.utc), identifier
    except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def _encode_cursor(stamp: datetime, identifier: UUID) -> str:
    raw = json.dumps({"at": stamp.isoformat(), "id": str(identifier)}, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")


def _limit(name: str, maximum: int, default: int) -> int | None:
    raw = request.args.get(name)
    if raw is None:
        return default
    try:
        return max(1, min(int(raw), maximum))
    except (TypeError, ValueError):
        return None


def _audit(action: str, *, user_id: int, tier: str, context: dict[str, Any]) -> None:
    """Best-effort audit event containing IDs/counts only, never chat content."""
    try:
        import app as app_module

        app_module.log_audit(user_id, tier, action, context=context)
    except Exception:
        return


@bp.post("/api/radar-ask/questions")
def ask_question():
    write_rejection = _write_gate()
    if write_rejection is not None:
        return write_rejection
    gate = _gate()
    if not isinstance(gate, tuple):
        return gate
    user_id, tier = gate
    payload = _json_object()
    if payload is None:
        return api_error("invalid_request", "Noi dung yeu cau khong hop le.", 400)
    try:
        typed = AskQuestionRequest.model_validate(payload)
    except ValidationError:
        return api_error("invalid_request", "Noi dung yeu cau khong hop le.", 400)
    idempotency_key = request.headers.get("Idempotency-Key")
    if idempotency_key is not None and (not idempotency_key.strip() or len(idempotency_key.strip()) > 128):
        return api_error("invalid_request", "Khoa idempotency khong hop le.", 400)
    try:
        result = run_radar_question(
            typed,
            AskContext(user_id=user_id, tier=tier),
            idempotency_key=idempotency_key.strip() if idempotency_key else None,
        )
    except IdempotencyConflict:
        return api_error("idempotency_conflict", "Yeu cau nay xung dot voi lan gui truoc.", 409)
    except OwnedResourceNotFound:
        return api_error("not_found", "Khong tim thay tai nguyen.", 404)
    except QuotaExceeded as exc:
        retry_after = max(1, int((exc.reset_at - datetime.now(timezone.utc)).total_seconds()))
        return api_error("daily_quota_exceeded", "Da dat gioi han cau hoi trong ngay.", 429, retry_after)
    except BurstExceeded as exc:
        return api_error("burst_limit_exceeded", "Vui long thu lai sau it phut.", 429, exc.retry_after_seconds)
    except BudgetHardStop:
        return api_error("monthly_budget_hard_stop", "Dich vu tam dung de bao ve ngan sach.", 507)
    except RadarAskTierDenied:
        return api_error("tier_required", "Goi tai khoan hien tai chua duoc cap Radar Ask.", 403)
    except RadarAskFeatureDisabled:
        return api_error("not_found", "Khong tim thay tai nguyen.", 404)
    except Exception:
        return api_error("provider_unavailable", "Dich vu tam thoi chua san sang.", 503)
    if result.status is RunStatus.FAILED:
        return api_error(result.error_code or "provider_unavailable", "Dich vu tam thoi chua san sang.", 503)
    response = jsonify(run_payload(result, tier=tier))
    response.status_code = 202 if result.status in {RunStatus.QUEUED, RunStatus.CREATED, RunStatus.RUNNING} else 200
    return _private(response)


@bp.get("/api/radar-ask/runs/<run_id>")
def get_run(run_id: str):
    gate = _gate()
    if not isinstance(gate, tuple):
        return gate
    user_id, tier = gate
    parsed = _uuid(run_id)
    if parsed is None:
        return api_error("not_found", "Khong tim thay tai nguyen.", 404)
    run = get_repository().get_run(user_id=user_id, run_id=parsed)
    if run is None:
        return api_error("not_found", "Khong tim thay tai nguyen.", 404)
    try:
        return _private(jsonify(run_record_payload(run, tier=tier)))
    except (TypeError, ValueError):
        return api_error("provider_unavailable", "Dich vu tam thoi chua san sang.", 503)


@bp.get("/api/radar-ask/sessions")
def list_sessions():
    gate = _gate()
    if not isinstance(gate, tuple):
        return gate
    user_id, _tier = gate
    limit = _limit("limit", 50, 20)
    cursor = _cursor(request.args.get("cursor"))
    if limit is None or (request.args.get("cursor") and cursor is None):
        return api_error("invalid_request", "Phan trang khong hop le.", 400)
    before_at, before_id = cursor if cursor is not None else (None, None)
    rows = get_repository().list_sessions(
        user_id=user_id,
        limit=limit,
        before_updated_at=before_at,
        before_id=before_id,
    )
    return _private(jsonify({"sessions": [session_payload(row) for row in rows], "limit": limit, "next_cursor": _encode_cursor(rows[-1].updated_at, rows[-1].id) if len(rows) == limit else None}))


@bp.get("/api/radar-ask/sessions/<session_id>")
def get_session(session_id: str):
    gate = _gate()
    if not isinstance(gate, tuple):
        return gate
    user_id, _tier = gate
    parsed = _uuid(session_id)
    limit = _limit("message_limit", 100, 50)
    cursor = _cursor(request.args.get("message_cursor"))
    if parsed is None:
        return api_error("not_found", "Khong tim thay tai nguyen.", 404)
    if limit is None or (request.args.get("message_cursor") and cursor is None):
        return api_error("invalid_request", "Phan trang khong hop le.", 400)
    repository = get_repository()
    session = repository.get_session(user_id=user_id, session_id=parsed)
    if session is None:
        return api_error("not_found", "Khong tim thay tai nguyen.", 404)
    before_at, before_id = cursor if cursor is not None else (None, None)
    try:
        messages = repository.list_messages(user_id=user_id, session_id=parsed, limit=limit, before_created_at=before_at, before_id=before_id)
    except OwnedResourceNotFound:
        return api_error("not_found", "Khong tim thay tai nguyen.", 404)
    return _private(jsonify({"session": session_payload(session), "messages": [message_payload(row) for row in messages], "message_limit": limit, "next_message_cursor": _encode_cursor(messages[0].created_at, messages[0].id) if len(messages) == limit else None}))


@bp.patch("/api/radar-ask/sessions/<session_id>")
def rename_session(session_id: str):
    write_rejection = _write_gate()
    if write_rejection is not None:
        return write_rejection
    gate = _gate()
    if not isinstance(gate, tuple):
        return gate
    user_id, _tier = gate
    parsed = _uuid(session_id)
    payload = _json_object()
    if parsed is None:
        return api_error("not_found", "Khong tim thay tai nguyen.", 404)
    if payload is None or not isinstance(payload.get("title"), str):
        return api_error("invalid_request", "Tieu de khong hop le.", 400)
    try:
        session = get_repository().rename_session(user_id=user_id, session_id=parsed, title=payload["title"])
    except ValueError:
        return api_error("invalid_request", "Tieu de khong hop le.", 400)
    if session is None:
        return api_error("not_found", "Khong tim thay tai nguyen.", 404)
    return _private(jsonify({"session": session_payload(session)}))


@bp.delete("/api/radar-ask/sessions/<session_id>")
def delete_session(session_id: str):
    write_rejection = _write_gate()
    if write_rejection is not None:
        return write_rejection
    gate = _gate()
    if not isinstance(gate, tuple):
        return gate
    user_id, tier = gate
    parsed = _uuid(session_id)
    if parsed is None or not get_repository().delete_session(user_id=user_id, session_id=parsed):
        return api_error("not_found", "Khong tim thay tai nguyen.", 404)
    _audit("radar_ask_session_deleted", user_id=user_id, tier=tier, context={"session_id": str(parsed)})
    response = make_response("", 204)
    return _private(response)


@bp.delete("/api/radar-ask/sessions")
def delete_all_sessions():
    write_rejection = _write_gate()
    if write_rejection is not None:
        return write_rejection
    gate = _gate()
    if not isinstance(gate, tuple):
        return gate
    user_id, tier = gate
    count = get_repository().delete_all_sessions(user_id=user_id)
    _audit("radar_ask_sessions_deleted", user_id=user_id, tier=tier, context={"count": count})
    response = make_response("", 204)
    return _private(response)


@bp.post("/api/radar-ask/messages/<message_id>/feedback")
def add_feedback(message_id: str):
    write_rejection = _write_gate()
    if write_rejection is not None:
        return write_rejection
    gate = _gate()
    if not isinstance(gate, tuple):
        return gate
    user_id, _tier = gate
    parsed = _uuid(message_id)
    payload = _json_object()
    if parsed is None:
        return api_error("not_found", "Khong tim thay tai nguyen.", 404)
    if payload is None or payload.get("rating") not in {"helpful", "not_helpful"}:
        return api_error("invalid_request", "Danh gia khong hop le.", 400)
    note = payload.get("note")
    if note is not None and not isinstance(note, str):
        return api_error("invalid_request", "Danh gia khong hop le.", 400)
    try:
        feedback = get_repository().add_feedback(user_id=user_id, message_id=parsed, rating=payload["rating"], note=note)
    except OwnedResourceNotFound:
        return api_error("not_found", "Khong tim thay tai nguyen.", 404)
    except ValueError:
        return api_error("invalid_request", "Danh gia khong hop le.", 400)
    return _private(jsonify({"feedback": feedback_payload(feedback)}))
