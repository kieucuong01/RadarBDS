from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from services.radar_ask.config import RadarAskSettings
from services.radar_ask.contracts import (
    AskContext,
    AskDepth,
    AskQuestionRequest,
    PlannerResult,
    ProviderResponse,
    ProviderUsage,
    RouteDecision,
    ToolCall,
)
from services.radar_ask.planner import DeepSeekTypedPlanner, PlannerOutputInvalid
from services.radar_ask.provider import ProviderInvalidResponse
from services.radar_ask.registry import (
    DEFAULT_TOOL_REGISTRY,
    ToolArgumentsInvalid,
    ToolNotAllowed,
)
from services.radar_ask.routing import finalize_planned_route


class FakeProvider:
    def __init__(self, response: ProviderResponse):
        self.response = response
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        return self.response


def planner_settings() -> RadarAskSettings:
    return replace(
        RadarAskSettings.from_env(),
        router_model="deepseek-v4-flash",
    )


def valid_route() -> dict[str, object]:
    return {
        "depth": "standard",
        "question_type": "market_trend",
        "tool_calls": [
            {
                "call_id": "planner-market-1",
                "name": "get_market_trend",
                "arguments": {"ward": "Phu My", "window_days": 90},
            }
        ],
        "generated": True,
        "use_thinking": False,
    }


def test_typed_planner_returns_route_and_usage_without_mutable_side_channel():
    usage = ProviderUsage(
        input_tokens=420,
        output_tokens=80,
        cache_miss_input_tokens=420,
    )
    provider = FakeProvider(ProviderResponse(json_value=valid_route(), usage=usage))
    planner = DeepSeekTypedPlanner(
        settings=planner_settings(),
        provider=provider,
        registry=DEFAULT_TOOL_REGISTRY,
    )

    result = planner(
        request=AskQuestionRequest(
            question=(
                "Phan tich Phu My; goi 0909 123 456; "
                "https://evil.example/private; Authorization: Bearer private-token"
            )
        ),
        context=AskContext(user_id=7, tier="vip"),
        allowed_tools=tuple(DEFAULT_TOOL_REGISTRY.registrations),
    )

    assert result == PlannerResult(
        decision=RouteDecision.model_validate(valid_route()),
        usage=usage,
    )
    assert not hasattr(planner, "last_usage")
    outbound = provider.requests[0]
    assert outbound.model == "deepseek-v4-flash"
    assert outbound.json_mode is True
    assert outbound.thinking_enabled is False
    serialized = "\n".join(message.content or "" for message in outbound.messages)
    assert "0909 123 456" not in serialized
    assert "evil.example" not in serialized
    assert "private-token" not in serialized
    assert "[REDACTED]" in serialized


def test_invalid_typed_planner_output_preserves_known_provider_usage():
    usage = ProviderUsage(input_tokens=90, output_tokens=10, cache_miss_input_tokens=90)
    provider = FakeProvider(
        ProviderResponse(
            json_value={**valid_route(), "arbitrary_sql": "SELECT * FROM users"},
            usage=usage,
        )
    )
    planner = DeepSeekTypedPlanner(
        settings=planner_settings(),
        provider=provider,
        registry=DEFAULT_TOOL_REGISTRY,
    )

    with pytest.raises(PlannerOutputInvalid) as caught:
        planner(
            request=AskQuestionRequest(question="Tu truy van du lieu cho toi"),
            context=AskContext(user_id=7, tier="vip"),
            allowed_tools=tuple(DEFAULT_TOOL_REGISTRY.registrations),
        )

    assert caught.value.usage == usage


@pytest.mark.parametrize(
    ("call", "error_type"),
    [
        (
            ToolCall(call_id="sql", name="run_sql", arguments={"query": "SELECT * FROM users"}),
            ToolNotAllowed,
        ),
        (
            ToolCall(
                call_id="url",
                name="search_official_documents",
                arguments={"query": "https://evil.example/private"},
            ),
            ToolArgumentsInvalid,
        ),
    ],
)
def test_finalized_planner_route_rejects_hostile_tools_and_arguments(call, error_type):
    decision = RouteDecision(
        depth=AskDepth.STANDARD,
        question_type="hostile",
        tool_calls=[call],
        generated=True,
    )

    with pytest.raises(error_type):
        finalize_planned_route(
            decision,
            request=AskQuestionRequest(question="Hay lam dieu nguy hiem"),
            context=AskContext(user_id=7, tier="vip"),
            registry=DEFAULT_TOOL_REGISTRY,
        )


def test_production_composition_injects_typed_planner_for_unmatched_question(monkeypatch):
    import services.radar_ask.service as service

    settings = planner_settings()
    response = ProviderResponse(json_value=valid_route(), usage=ProviderUsage(input_tokens=1))
    provider = FakeProvider(response)
    monkeypatch.setattr(service.RadarAskSettings, "from_env", lambda: settings)
    monkeypatch.setattr(service, "get_repository", lambda: SimpleNamespace())
    monkeypatch.setattr(service, "RadarAskLimitService", lambda **_kwargs: SimpleNamespace())
    monkeypatch.setattr(service, "get_burst_limiter", lambda: SimpleNamespace())
    monkeypatch.setattr(service, "DeepSeekProvider", lambda **_kwargs: provider)

    dependencies = service._dependencies()
    planned = dependencies.planner(
        request=AskQuestionRequest(question="Phu My dang co xu huong the nao?"),
        context=AskContext(user_id=7, tier="vip"),
        allowed_tools=tuple(DEFAULT_TOOL_REGISTRY.registrations),
    )
    decision = finalize_planned_route(
        planned.decision,
        request=AskQuestionRequest(question="Phu My dang co xu huong the nao?"),
        context=AskContext(user_id=7, tier="vip"),
        registry=DEFAULT_TOOL_REGISTRY,
    )

    assert decision.question_type == "market_trend"
    assert decision.tool_calls[0].name == "get_market_trend"
    assert planned.usage.input_tokens == 1


def test_provider_invalid_json_error_exposes_accumulated_known_usage():
    error = ProviderInvalidResponse(
        "invalid planner JSON",
        usage=ProviderUsage(input_tokens=11, output_tokens=3),
    )
    assert error.usage == ProviderUsage(input_tokens=11, output_tokens=3)
