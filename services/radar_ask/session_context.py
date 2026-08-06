"""Bounded, current-session memory for Radar Ask requests."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .contracts import AskContext, SessionMemory
from .registry import APPROVED_TOOL_NAMES
from .repository import RadarAskSessionContextRecord


MAX_RECENT_TURNS = 6
MAX_TURN_CHARS = 600


def _strings(value: Any, *, maximum: int) -> list[str]:
    values: Sequence[Any]
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        values = value
    else:
        return []
    result: list[str] = []
    for item in values:
        if not isinstance(item, str):
            continue
        normalized = " ".join(item.split())
        if normalized and len(normalized) <= maximum and normalized not in result:
            result.append(normalized)
    return result


def _number(value: Any, *, maximum: float) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if 0 < parsed <= maximum else None


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _memory_from_routes(routes: Sequence[Mapping[str, Any]]) -> SessionMemory:
    memory: dict[str, Any] = {}
    for raw_route in routes:
        question_type = raw_route.get("question_type")
        if "previous_question_type" not in memory and isinstance(question_type, str):
            memory["previous_question_type"] = question_type
        calls = raw_route.get("tool_calls")
        if not isinstance(calls, Sequence) or isinstance(calls, (str, bytes)):
            continue
        for raw_call in calls:
            if not isinstance(raw_call, Mapping):
                continue
            if raw_call.get("name") not in APPROVED_TOOL_NAMES:
                continue
            arguments = raw_call.get("arguments")
            if not isinstance(arguments, Mapping):
                continue
            if "city" not in memory:
                values = _strings(arguments.get("city"), maximum=120)
                if values:
                    memory["city"] = values[0]
            if "wards" not in memory:
                wards = _strings(arguments.get("wards"), maximum=120)
                if not wards:
                    wards = _strings(arguments.get("areas"), maximum=120)
                if not wards:
                    wards = _strings(arguments.get("ward"), maximum=120)
                if wards:
                    memory["wards"] = wards[:10]
            if "road" not in memory:
                values = _strings(arguments.get("road"), maximum=180)
                if values:
                    memory["road"] = values[0]
            if "property_types" not in memory:
                property_types = _strings(
                    arguments.get("property_types"), maximum=80
                )
                if not property_types:
                    property_types = _strings(
                        arguments.get("property_type"), maximum=80
                    )
                if property_types:
                    memory["property_types"] = property_types[:5]
            if "budget_ty" not in memory:
                budget = _number(arguments.get("budget_ty"), maximum=500)
                if budget is None:
                    budget = _number(arguments.get("max_budget_ty"), maximum=500)
                if budget is not None:
                    memory["budget_ty"] = budget
            for field in ("min_area_m2", "max_area_m2"):
                if field not in memory:
                    area = _number(arguments.get(field), maximum=100_000)
                    if area is not None:
                        memory[field] = area
            if "listing_id" not in memory:
                listing_id = _positive_int(arguments.get("listing_id"))
                if listing_id is not None:
                    memory["listing_id"] = listing_id
    return SessionMemory.model_validate(memory)


def _recent_turns(stored: RadarAskSessionContextRecord) -> list[str]:
    turns: list[str] = []
    for message in stored.messages[-MAX_RECENT_TURNS:]:
        if message.role not in {"user", "assistant"}:
            continue
        content = str(message.content or "").strip()[:MAX_TURN_CHARS]
        if content:
            turns.append(f"{message.role}: {content}")
    return turns


def hydrate_session_context(
    base: AskContext,
    stored: RadarAskSessionContextRecord,
) -> AskContext:
    """Return an immutable request context hydrated from one owned chat."""
    turns = _recent_turns(stored)
    return base.model_copy(
        update={
            "recent_turns": turns or list(base.recent_turns),
            "session_memory": _memory_from_routes(stored.routes),
        }
    )


__all__ = ("hydrate_session_context",)
