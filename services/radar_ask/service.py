"""HTTP-safe composition and serialization for the Radar Ask product boundary."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from .burst import get_burst_limiter
from .config import VALID_TIERS, RadarAskSettings
from .contracts import AnswerEnvelope, AskContext, AskQuestionRequest, AskRunResult, RunStatus
from .limits import RadarAskLimitService
from .orchestrator import OrchestratorDependencies, run_question
from .planner import DeepSeekTypedPlanner
from .provider import DeepSeekProvider
from .registry import DEFAULT_TOOL_REGISTRY
from .repository import (
    RadarAskFeedbackRecord,
    RadarAskMessageRecord,
    RadarAskRepository,
    RadarAskRunRecord,
    RadarAskSessionRecord,
)
from .routing import route_question
from .source_links import source_card_details


def feature_enabled() -> bool:
    return os.getenv("RADAR_ASK_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}


def tier_allowed(tier: str) -> bool:
    """Check the cheap request gate before constructing provider dependencies."""
    allowed = {
        part.strip().lower()
        for part in os.getenv("RADAR_ASK_ALLOWED_TIERS", "admin").split(",")
        if part.strip()
    }
    return tier in VALID_TIERS and tier in allowed


def get_repository() -> RadarAskRepository:
    return RadarAskRepository()


def _dependencies() -> OrchestratorDependencies:
    settings = RadarAskSettings.from_env()
    provider = DeepSeekProvider(settings=settings)
    return OrchestratorDependencies(
        settings=settings,
        repository=get_repository(),
        limits=RadarAskLimitService(settings=settings),
        burst=get_burst_limiter(),
        router=route_question,
        registry=DEFAULT_TOOL_REGISTRY,
        provider=provider,
        clock=lambda: datetime.now(timezone.utc),
        planner=DeepSeekTypedPlanner(
            settings=settings,
            provider=provider,
            registry=DEFAULT_TOOL_REGISTRY,
        ),
    )


def run_radar_question(
    request: AskQuestionRequest,
    context: AskContext,
    *,
    idempotency_key: str | None,
) -> AskRunResult:
    """Execute only through the typed orchestration boundary."""
    return run_question(
        request,
        context,
        dependencies=_dependencies(),
        idempotency_key=idempotency_key,
    )


def _answer_payload(answer: AnswerEnvelope | None) -> dict[str, Any] | None:
    if answer is None:
        return None
    payload = answer.model_dump(mode="json")
    payload["next_checks"] = payload.pop("next_verification_steps", [])
    # Raw source references stay private. Deterministic same-origin fallbacks
    # make older persisted answers clickable without a data migration.
    source_cards = []
    for card, serialized in zip(answer.source_cards, payload.get("source_cards", [])):
        title, fallback_href = source_card_details(
            source_kind=card.source_kind,
            source_ref=card.source_ref,
            existing_title=card.title,
        )
        source_cards.append(
            {
                "evidence_id": serialized.get("evidence_id"),
                "title": title,
                "source_kind": serialized.get("source_kind"),
                "as_of": serialized.get("as_of"),
                "href": card.href or fallback_href,
            }
        )
    payload["source_cards"] = source_cards
    return payload


def run_payload(result: AskRunResult, *, tier: str) -> dict[str, Any]:
    return {
        "run_id": str(result.run_id),
        "session_id": str(result.session_id),
        "status": result.status.value,
        "answer": _answer_payload(result.answer),
        "quota": {"tier": tier},
        "cost_state": {"state": "available"},
    }


def run_record_payload(run: RadarAskRunRecord, *, tier: str) -> dict[str, Any]:
    answer = None
    if run.answer is not None:
        try:
            answer = AnswerEnvelope.model_validate(run.answer)
        except (TypeError, ValueError):
            answer = None
    result = AskRunResult(
        run_id=run.id,
        session_id=run.session_id,
        status=RunStatus(run.status),
        answer=answer,
        retryable=run.retryable,
        error_code=run.error_code,
    )
    return run_payload(result, tier=tier)


def session_payload(session: RadarAskSessionRecord) -> dict[str, Any]:
    return {
        "id": str(session.id),
        "title": session.title,
        "created_at": session.created_at.isoformat(),
        "updated_at": session.updated_at.isoformat(),
    }


def message_payload(message: RadarAskMessageRecord) -> dict[str, Any]:
    answer = None
    if message.answer is not None:
        try:
            answer = _answer_payload(AnswerEnvelope.model_validate(message.answer))
        except (TypeError, ValueError):
            answer = None
    return {
        "id": str(message.id),
        "role": message.role,
        "content": message.content,
        "answer": answer,
        "created_at": message.created_at.isoformat(),
    }


def feedback_payload(feedback: RadarAskFeedbackRecord) -> dict[str, Any]:
    return {
        "id": str(feedback.id),
        "message_id": str(feedback.message_id),
        "rating": feedback.rating,
        "note": feedback.note,
        "created_at": feedback.created_at.isoformat(),
    }
