from __future__ import annotations

import json
import sys
from dataclasses import replace
from types import ModuleType, SimpleNamespace

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
    SessionMemory,
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

    def complete_until(self, request, *, deadline):
        assert deadline > 0
        return self.complete(request)


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


def test_planner_receives_bounded_current_session_context():
    provider = FakeProvider(
        ProviderResponse(json_value=valid_route(), usage=ProviderUsage(input_tokens=1))
    )
    planner = DeepSeekTypedPlanner(
        settings=planner_settings(),
        provider=provider,
        registry=DEFAULT_TOOL_REGISTRY,
    )

    planner(
        request=AskQuestionRequest(question="Rẻ hơn nữa thì sao?"),
        context=AskContext(
            user_id=7,
            tier="admin",
            recent_turns=["user: Tân An khoảng 500 m2"],
            session_memory=SessionMemory(
                wards=["Tân An"],
                min_area_m2=450,
                max_area_m2=550,
                previous_question_type="deal_search",
            ),
        ),
        allowed_tools=tuple(DEFAULT_TOOL_REGISTRY.registrations),
    )

    payload = json.loads(provider.requests[0].messages[-1].content or "{}")
    conversation = payload["conversation_context"]
    assert conversation["memory"]["wards"] == ["Tân An"]
    assert conversation["memory"]["min_area_m2"] == 450
    assert conversation["memory"]["max_area_m2"] == 550
    assert conversation["recent_turns"] == ["user: Tân An khoảng 500 m2"]


def test_planner_minimizes_hostile_pii_but_keeps_useful_location_and_road_context():
    provider = FakeProvider(
        ProviderResponse(json_value=valid_route(), usage=ProviderUsage(input_tokens=1))
    )
    planner = DeepSeekTypedPlanner(
        settings=planner_settings(),
        provider=provider,
        registry=DEFAULT_TOOL_REGISTRY,
    )

    planner(
        request=AskQuestionRequest(
            question=(
                "So sánh Phú Mỹ và Định Hòa, liên hệ owner@example.test; "
                "chủ đất Nguyễn Văn A; CCCD 079123456789; CMND 123456789; "
                "MST 0312345678; STK 012345678901; thửa 1234 tờ bản đồ 56"
            )
        ),
        context=AskContext.model_validate(
            {
                "user_id": 7,
                "tier": "vip",
                "page": {
                    "city": "Thủ Dầu Một",
                    "ward": "Phú Mỹ - email hint@example.test",
                    "road": "DX 068; môi giới Trần Thị B; STK 998877665544",
                },
                "session_summary": "private CCCD 001122334455",
                "recent_turns": ["khách hàng Lê Văn C, email c@example.test"],
            }
        ),
        allowed_tools=tuple(DEFAULT_TOOL_REGISTRY.registrations),
    )

    serialized = "\n".join(message.content or "" for message in provider.requests[0].messages)
    for sensitive in (
        "owner@example.test",
        "hint@example.test",
        "Nguyễn Văn A",
        "Trần Thị B",
        "079123456789",
        "123456789",
        "0312345678",
        "012345678901",
        "998877665544",
        "thửa 1234",
        "tờ bản đồ 56",
        "001122334455",
        "Lê Văn C",
        "c@example.test",
    ):
        assert sensitive not in serialized
    assert "Phú Mỹ" in serialized
    assert "Định Hòa" in serialized
    assert "Thủ Dầu Một" in serialized
    assert "DX 068" in serialized
    assert "session_summary" not in serialized
    assert "recent_turns" in serialized
    assert "[REDACTED_PERSON]" in serialized
    assert "[REDACTED_EMAIL]" in serialized


@pytest.mark.parametrize(
    "question",
    [
        "Môi giới đang đẩy giá đất Phú Mỹ như thế nào?",
        "Chủ đất giảm giá vì sao?",
        "Chủ đất: không giảm giá vì sao?",
        "Môi giới: đang đẩy giá đất?",
    ],
)
def test_planner_person_redaction_retains_unlabeled_market_semantics(question):
    provider = FakeProvider(
        ProviderResponse(json_value=valid_route(), usage=ProviderUsage(input_tokens=1))
    )
    planner = DeepSeekTypedPlanner(
        settings=planner_settings(),
        provider=provider,
        registry=DEFAULT_TOOL_REGISTRY,
    )

    planner(
        request=AskQuestionRequest(question=question),
        context=AskContext(user_id=7, tier="vip"),
        allowed_tools=tuple(DEFAULT_TOOL_REGISTRY.registrations),
    )

    outbound = provider.requests[0].messages[1].content or ""
    assert question in outbound
    assert "[REDACTED_PERSON]" not in outbound


def test_planner_payload_includes_investor_intent_examples_for_common_vietnamese_queries():
    provider = FakeProvider(
        ProviderResponse(json_value=valid_route(), usage=ProviderUsage(input_tokens=1))
    )
    planner = DeepSeekTypedPlanner(
        settings=planner_settings(),
        provider=provider,
        registry=DEFAULT_TOOL_REGISTRY,
    )

    planner(
        request=AskQuestionRequest(question="kiếm cho tôi lô đất tại Tân An ok xíu"),
        context=AskContext(user_id=7, tier="admin"),
        allowed_tools=tuple(DEFAULT_TOOL_REGISTRY.registrations),
    )

    outbound = provider.requests[0]
    system = outbound.messages[0].content or ""
    payload = json.loads(outbound.messages[1].content or "{}")
    examples = payload["intent_examples"]

    assert "đời thường" in system
    assert {
        "question": "kiếm cho tôi lô đất tại Tân An ok xíu",
        "tool": "search_deals",
        "property_types": ["dat_nen"],
    } in [
        {
            "question": example["question"],
            "tool": example["tool_calls"][0]["name"],
            "property_types": example["tool_calls"][0]["arguments"].get("property_types"),
        }
        for example in examples
        if example["tool_calls"]
    ]
    assert any(
        example["question"] == "Tân An có lô nào 500m2 rẻ k"
        and example["tool_calls"][0]["arguments"]["min_area_m2"] == 450.0
        and example["tool_calls"][0]["arguments"]["max_area_m2"] == 550.0
        for example in examples
    )
    assert any(
        example["question"] == "hiện có bao nhiêu lô giảm giá ở Tân An"
        and example["tool_calls"][0]["name"] == "rank_price_drop_areas"
        and example["tool_calls"][0]["arguments"]["wards"] == ["Tân An"]
        for example in examples
    )
    assert any(
        example["question"] == "đất Tân An giờ giá bao nhiêu"
        and example["question_type"] == "area_market_estimate"
        and example["tool_calls"][0]["name"] == "compare_areas"
        and example["tool_calls"][0]["arguments"]["areas"] == ["Tân An"]
        for example in examples
    )
    assert any(
        example["question"] == "Xin chào"
        and example["question_type"] == "conversation"
        and example["tool_calls"] == []
        for example in examples
    )
    assert any(
        example["question"] == "Bạn làm được gì?"
        and example["question_type"] == "help"
        and example["tool_calls"] == []
        for example in examples
    )
    assert any(
        example["question"] == "kiếm cho tôi lô đất ok xíu"
        and example["question_type"] == "clarification"
        and example["needs_clarification"] is True
        and "khu vực" in example["clarification_question"].lower()
        for example in examples
    )
    assert any(
        example["question"] == "Tân An có gì đáng xem"
        and example["question_type"] == "deal_search"
        and example["tool_calls"][0]["name"] == "search_deals"
        and example["tool_calls"][0]["arguments"]["wards"] == ["Tân An"]
        for example in examples
    )


@pytest.mark.parametrize(
    ("question", "private_name"),
    [
        ("Chủ đất Nguyễn Văn A?", "Nguyễn Văn A"),
        ("chủ đất: nguyễn văn a;", "nguyễn văn a"),
        ("Môi giới: trần thị b.", "trần thị b"),
        ("Người bán Lê Thị Ánh!", "Lê Thị Ánh"),
    ],
)
def test_planner_redacts_labeled_names_with_sentence_punctuation_and_delimiter(
    question,
    private_name,
):
    provider = FakeProvider(
        ProviderResponse(json_value=valid_route(), usage=ProviderUsage(input_tokens=1))
    )
    planner = DeepSeekTypedPlanner(
        settings=planner_settings(),
        provider=provider,
        registry=DEFAULT_TOOL_REGISTRY,
    )

    planner(
        request=AskQuestionRequest(question=question),
        context=AskContext(user_id=7, tier="vip"),
        allowed_tools=tuple(DEFAULT_TOOL_REGISTRY.registrations),
    )

    outbound = provider.requests[0].messages[1].content or ""
    assert private_name not in outbound
    assert "[REDACTED_PERSON]" in outbound


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
    redis_module = ModuleType("redis")
    redis_exceptions_module = ModuleType("redis.exceptions")
    redis_exceptions_module.RedisError = RuntimeError
    redis_module.Redis = SimpleNamespace(from_url=lambda *_args, **_kwargs: SimpleNamespace())
    redis_module.exceptions = redis_exceptions_module
    monkeypatch.setitem(sys.modules, "redis", redis_module)
    monkeypatch.setitem(sys.modules, "redis.exceptions", redis_exceptions_module)

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
