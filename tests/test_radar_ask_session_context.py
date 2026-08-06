from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from services.radar_ask.contracts import AskContext
from services.radar_ask.repository import (
    RadarAskMessageRecord,
    RadarAskSessionContextRecord,
)
from services.radar_ask.session_context import hydrate_session_context


NOW = datetime(2026, 8, 6, 6, 0, tzinfo=timezone.utc)


def message(role: str, content: str) -> RadarAskMessageRecord:
    return RadarAskMessageRecord(
        id=uuid4(),
        session_id=uuid4(),
        run_id=None,
        role=role,
        content=content,
        answer=None,
        created_at=NOW,
    )


def route(question_type: str, name: str, arguments: dict[str, object]):
    return {
        "depth": "fast",
        "question_type": question_type,
        "tool_calls": [
            {"call_id": f"context-{name}", "name": name, "arguments": arguments}
        ],
        "generated": False,
    }


def test_resolver_keeps_latest_allowlisted_route_values_and_six_turns():
    stored = RadarAskSessionContextRecord(
        messages=tuple(message("user", f"turn-{index}") for index in range(8)),
        routes=(
            route(
                "deal_search",
                "search_deals",
                {
                    "wards": ["Tân An"],
                    "max_budget_ty": 3,
                    "min_area_m2": 450,
                    "max_area_m2": 550,
                    "sql": "SELECT * FROM users",
                },
            ),
            route(
                "market_trend",
                "get_market_trend",
                {"ward": "Định Hòa", "property_type": "dat_nen"},
            ),
        ),
    )

    hydrated = hydrate_session_context(
        AskContext(user_id=7, tier="admin"),
        stored,
    )

    assert hydrated.session_memory.wards == ["Tân An"]
    assert hydrated.session_memory.property_types == ["dat_nen"]
    assert hydrated.session_memory.budget_ty == 3
    assert hydrated.session_memory.min_area_m2 == 450
    assert hydrated.session_memory.max_area_m2 == 550
    assert hydrated.session_memory.previous_question_type == "deal_search"
    assert hydrated.recent_turns == [
        "user: turn-2",
        "user: turn-3",
        "user: turn-4",
        "user: turn-5",
        "user: turn-6",
        "user: turn-7",
    ]
    assert "SELECT" not in hydrated.model_dump_json()


def test_resolver_preserves_base_page_and_never_crosses_empty_context():
    base = AskContext.model_validate(
        {
            "user_id": 8,
            "tier": "admin",
            "page": {"ward": "Phú Mỹ", "listing_id": 123},
        }
    )

    hydrated = hydrate_session_context(
        base,
        RadarAskSessionContextRecord(messages=(), routes=()),
    )

    assert hydrated.page == base.page
    assert hydrated.session_memory.wards == []
    assert hydrated.recent_turns == []


def test_resolver_bounds_turn_length_and_ignores_non_typed_routes():
    stored = RadarAskSessionContextRecord(
        messages=(message("assistant", "x" * 800),),
        routes=(
            {
                "question_type": "conversation",
                "tool_calls": [],
                "generated": True,
                "secret": "private-token",
            },
        ),
    )

    hydrated = hydrate_session_context(
        AskContext(user_id=9, tier="free"),
        stored,
    )

    assert hydrated.recent_turns == [f"assistant: {'x' * 600}"]
    assert hydrated.session_memory.previous_question_type == "conversation"
    assert "private-token" not in hydrated.model_dump_json()
