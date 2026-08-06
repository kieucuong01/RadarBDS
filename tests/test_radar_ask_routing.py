from __future__ import annotations

from dataclasses import dataclass

import pytest
from pydantic import BaseModel, ConfigDict, Field

from services.radar_ask.contracts import (
    AskContext,
    AskDepth,
    AskQuestionRequest,
    EvidenceBundle,
    PageContext,
    RetrievalQuality,
    RouteDecision,
    ToolCall,
)
from services.radar_ask.registry import (
    APPROVED_TOOL_NAMES,
    DEFAULT_TOOL_REGISTRY,
    ToolArgumentsInvalid,
    ToolContext,
    ToolNotAllowed,
    ToolRegistration,
    ToolRegistry,
    execute_tool,
)
from services.radar_ask.routing import (
    PlannerRequired,
    RoutingPolicyViolation,
    route_question,
)


class PlannerSpy:
    def __init__(self, result=None):
        self.result = result
        self.calls = []

    def __call__(self, *, request, context, allowed_tools):
        self.calls.append((request, context, allowed_tools))
        return self.result

    @property
    def call_count(self):
        return len(self.calls)


def make_context(
    *,
    tier: str = "free",
    listing_id: int | None = None,
    ward: str | None = None,
) -> AskContext:
    return AskContext(
        user_id=42,
        tier=tier,
        page=PageContext(listing_id=listing_id, ward=ward),
    )


@pytest.mark.parametrize(
    ("question", "tool_name", "question_type"),
    [
        (
            "Ngân sách 2.5 tỷ ở Thủ Dầu Một nên xem phường nào?",
            "match_budget",
            "budget_match",
        ),
        (
            "Phú Mỹ và Định Hòa giá đất nền khác nhau sao?",
            "compare_areas",
            "area_comparison",
        ),
        (
            "Tin nào dưới 20 triệu/m² đang đáng kiểm tra?",
            "search_deals",
            "deal_search",
        ),
        (
            "Khu nào có nhiều tín hiệu giảm giá hôm nay?",
            "rank_price_drop_areas",
            "price_drop_ranking",
        ),
        (
            "Bảng giá đất TP.HCM có dùng để định giá thực tế không?",
            "search_official_documents",
            "official_price_explanation",
        ),
        (
            "Phú Mỹ đang có xu hướng thế nào?",
            "get_market_trend",
            "market_trend",
        ),
        (
            "Phú Mỹ có nên đầu tư không?",
            "get_market_trend",
            "market_trend",
        ),
        (
            "Giá đất nền Phú Mỹ hiện tại khoảng bao nhiêu?",
            "compare_areas",
            "area_market_estimate",
        ),
        (
            "đất Tân An giờ bao nhiêu",
            "compare_areas",
            "area_market_estimate",
        ),
        (
            "hiện có bao nhiêu lô giảm giá ở Tân An",
            "rank_price_drop_areas",
            "price_drop_ranking",
        ),
    ],
)
def test_approved_simple_questions_use_fast_path_without_planner(
    question,
    tool_name,
    question_type,
):
    planner = PlannerSpy()

    decision = route_question(
        AskQuestionRequest(question=question),
        make_context(),
        planner=planner,
    )

    assert decision.depth is AskDepth.FAST
    assert decision.tool_calls[0].name == tool_name
    assert decision.question_type == question_type
    assert decision.use_thinking is False
    assert planner.call_count == 0


def test_fast_patterns_extract_bounded_business_arguments():
    budget = route_question(
        AskQuestionRequest(question="Ngân sách 2,5 tỷ ở Thủ Dầu Một nên xem phường nào?"),
        make_context(),
    )
    comparison = route_question(
        AskQuestionRequest(question="Phú Mỹ và Định Hòa giá đất nền khác nhau sao?"),
        make_context(),
    )
    deals = route_question(
        AskQuestionRequest(question="Tin nào dưới 20 triệu/m² đang đáng kiểm tra?"),
        make_context(),
    )
    area_price = route_question(
        AskQuestionRequest(question="Giá đất nền Phú Mỹ hiện tại khoảng bao nhiêu?"),
        make_context(),
    )

    assert budget.tool_calls[0].arguments == {
        "budget_ty": 2.5,
        "city": "Thủ Dầu Một",
        "limit": 10,
    }
    assert comparison.tool_calls[0].arguments["areas"] == ["Phú Mỹ", "Định Hòa"]
    assert comparison.tool_calls[0].arguments["property_type"] == "dat_nen"
    assert deals.tool_calls[0].arguments["max_price_per_m2_million"] == 20.0
    assert deals.tool_calls[0].arguments["mos_min_pct"] == 15.0
    assert area_price.tool_calls[0].arguments == {
        "areas": ["Phú Mỹ"],
        "property_type": "dat_nen",
        "window_days": 90,
    }


def test_tan_an_investor_questions_keep_the_right_intent():
    area_price = route_question(
        AskQuestionRequest(question="đất Tân An giờ bao nhiêu"),
        make_context(),
    )
    price_drop_count = route_question(
        AskQuestionRequest(question="hiện có bao nhiêu lô giảm giá ở Tân An"),
        make_context(tier="admin"),
    )

    assert area_price.question_type == "area_market_estimate"
    assert area_price.tool_calls[0].arguments["areas"] == ["Tân An"]
    assert area_price.tool_calls[0].arguments["property_type"] == "dat_nen"
    assert price_drop_count.question_type == "price_drop_ranking"
    assert price_drop_count.tool_calls[0].arguments["wards"] == ["Tân An"]


def test_fuzzy_tan_an_deal_questions_use_typed_planner_for_intent():
    soft_planner = PlannerSpy(
        {
            "depth": "fast",
            "question_type": "deal_search",
            "tool_calls": [
                {
                    "call_id": "plan-soft-deal",
                    "name": "search_deals",
                    "arguments": {
                        "wards": ["Tân An"],
                        "property_types": ["dat_nen"],
                        "mos_min_pct": 10.0,
                        "limit": 10,
                    },
                }
            ],
            "generated": False,
            "use_thinking": False,
        }
    )
    soft_deal = route_question(
        AskQuestionRequest(question="kiếm cho tôi lô đất tại Tân An ok xíu"),
        make_context(tier="admin"),
        planner=soft_planner,
    )

    large_planner = PlannerSpy(
        {
            "depth": "fast",
            "question_type": "deal_search",
            "tool_calls": [
                {
                    "call_id": "plan-large-deal",
                    "name": "search_deals",
                    "arguments": {
                        "wards": ["Tân An"],
                        "mos_min_pct": 10.0,
                        "limit": 10,
                        "min_area_m2": 450.0,
                        "max_area_m2": 550.0,
                    },
                }
            ],
            "generated": False,
            "use_thinking": False,
        }
    )
    large_cheap_deal = route_question(
        AskQuestionRequest(question="Tân An có lô nào 500m2 rẻ k"),
        make_context(tier="admin"),
        planner=large_planner,
    )

    assert soft_planner.call_count == 1
    assert soft_deal.question_type == "deal_search"
    assert soft_deal.tool_calls[0].arguments["wards"] == ["Tân An"]
    assert soft_deal.tool_calls[0].arguments["mos_min_pct"] == 10.0
    assert large_planner.call_count == 1
    assert large_cheap_deal.question_type == "deal_search"
    assert large_cheap_deal.tool_calls[0].arguments["wards"] == ["Tân An"]
    assert large_cheap_deal.tool_calls[0].arguments["min_area_m2"] == 450.0
    assert large_cheap_deal.tool_calls[0].arguments["max_area_m2"] == 550.0


def test_fuzzy_deal_question_without_planner_fails_closed():
    with pytest.raises(PlannerRequired):
        route_question(
            AskQuestionRequest(question="kiếm cho tôi lô đất tại Tân An ok xíu"),
            make_context(tier="admin"),
        )


def test_official_price_explanation_stays_deterministic_for_simple_policy_question():
    decision = route_question(
        AskQuestionRequest(question="Bảng giá đất TP.HCM có dùng để định giá thực tế không?"),
        make_context(),
    )

    assert decision.depth is AskDepth.FAST
    assert decision.question_type == "official_price_explanation"
    assert decision.generated is False
    assert decision.tool_calls[0].name == "search_official_documents"


def test_current_listing_explanation_uses_page_context_without_guessing():
    planner = PlannerSpy()
    decision = route_question(
        AskQuestionRequest(question="Lô đất này tại sao được định giá 2,5 tỷ?"),
        make_context(tier="vip", listing_id=123),
        planner=planner,
    )

    assert decision.depth is AskDepth.STANDARD
    assert [call.name for call in decision.tool_calls] == [
        "get_listing_facts",
        "explain_valuation",
    ]
    assert all(call.arguments["listing_id"] == 123 for call in decision.tool_calls)
    assert decision.use_thinking is False
    assert planner.call_count == 0


def test_current_listing_risk_question_uses_page_context_without_planner():
    planner = PlannerSpy()
    decision = route_question(
        AskQuestionRequest(question="Tin này có rủi ro gì cần kiểm tra không?"),
        make_context(tier="vip", listing_id=123),
        planner=planner,
    )

    assert decision.depth is AskDepth.FAST
    assert decision.question_type == "listing_risk"
    assert [call.name for call in decision.tool_calls] == ["inspect_listing_risks"]
    assert decision.tool_calls[0].arguments == {"listing_id": 123}
    assert decision.generated is False
    assert planner.call_count == 0


def test_exact_road_market_question_uses_deterministic_market_tool():
    decision = route_question(
        AskQuestionRequest(
            question="Giá hiện tại với đất mặt tiền đường DX 071 là bao nhiêu?"
        ),
        make_context(ward="Định Hòa"),
    )

    assert decision.depth is AskDepth.FAST
    assert decision.tool_calls[0].name == "estimate_road_market"
    assert decision.tool_calls[0].arguments["road"] == "DX 071"
    assert decision.tool_calls[0].arguments["ward"] == "Định Hòa"


def test_exact_road_market_uses_ward_written_in_the_question():
    decision = route_question(
        AskQuestionRequest(
            question="Giá đất mặt tiền đường D1, Phú Mỹ hiện tại khoảng bao nhiêu?"
        ),
        make_context(),
    )

    assert decision.depth is AskDepth.FAST
    assert decision.tool_calls[0].name == "estimate_road_market"
    assert decision.tool_calls[0].arguments["road"] == "D1"
    assert decision.tool_calls[0].arguments["ward"] == "Phú Mỹ"


@pytest.mark.parametrize(
    "question",
    [
        "Lô đất này tại sao được định giá 2,5 tỷ?",
        "Lô đất này có rủi ro gì?",
        "Lô đất XXX tại sao được định giá 2 tỷ?",
        "Giá đất mặt tiền đường XXX hiện tại là bao nhiêu?",
    ],
)
def test_ambiguous_listing_or_road_requests_ask_one_clarification(question):
    planner = PlannerSpy()
    decision = route_question(
        AskQuestionRequest(question=question),
        make_context(),
        planner=planner,
    )

    assert decision.needs_clarification is True
    assert decision.clarification_question
    assert decision.tool_calls == []
    assert planner.call_count == 0


def test_explicit_deep_research_is_bounded_and_thinking_only_for_smart_tier():
    free = route_question(
        AskQuestionRequest(
            question="Nghiên cứu sâu lô đất này vì sao định giá như vậy?"
        ),
        make_context(tier="free", listing_id=88),
    )
    vip = route_question(
        AskQuestionRequest(
            question="Phân tích kỹ lô đất này vì sao định giá như vậy?"
        ),
        make_context(tier="vip", listing_id=88),
    )

    assert free.depth is AskDepth.DEEP
    assert free.use_thinking is False
    assert len(free.tool_calls) == 2
    assert all(call.arguments == {"listing_id": 88} for call in free.tool_calls)
    assert vip.depth is AskDepth.DEEP
    assert vip.use_thinking is True
    assert len(vip.tool_calls) == 2
    assert all(call.arguments == {"listing_id": 88} for call in vip.tool_calls)


def test_explicit_requested_depth_is_honored_without_adding_tools():
    request = AskQuestionRequest(
        question="Tin nào dưới 20 triệu/m² đang đáng kiểm tra?",
        requested_depth=AskDepth.DEEP,
    )

    decision = route_question(request, make_context(tier="vip"))

    assert decision.depth is AskDepth.DEEP
    assert len(decision.tool_calls) == 1
    assert decision.use_thinking is True


def test_unmatched_question_calls_typed_planner_once():
    planned = {
        "depth": "standard",
        "question_type": "market_advice",
        "tool_calls": [
            {
                "call_id": "plan-1",
                "name": "get_market_trend",
                "arguments": {"ward": "Phú Mỹ", "window_days": 90},
            }
        ],
        "generated": True,
        "use_thinking": False,
    }
    planner = PlannerSpy(planned)

    decision = route_question(
        AskQuestionRequest(question="Tôi nên bắt đầu phân tích từ đâu?"),
        make_context(),
        planner=planner,
    )

    assert isinstance(decision, RouteDecision)
    assert planner.call_count == 1
    assert decision.tool_calls[0].name == "get_market_trend"
    assert set(planner.calls[0][2]) == set(APPROVED_TOOL_NAMES)


def test_planner_can_route_small_talk_without_database_tools():
    planner = PlannerSpy(
        {
            "depth": "standard",
            "question_type": "conversation",
            "tool_calls": [],
            "generated": True,
            "use_thinking": True,
        }
    )

    decision = route_question(
        AskQuestionRequest(question="Xin chào"),
        make_context(tier="admin"),
        planner=planner,
    )

    assert planner.call_count == 1
    assert decision.depth is AskDepth.FAST
    assert decision.question_type == "conversation"
    assert decision.tool_calls == []
    assert decision.generated is False
    assert decision.use_thinking is False


def test_consultant_style_vague_investor_question_uses_planner_clarification():
    planner = PlannerSpy(
        {
            "depth": "fast",
            "question_type": "clarification",
            "tool_calls": [],
            "generated": True,
            "needs_clarification": True,
            "clarification_question": "Anh muốn tìm ở khu vực nào và ngân sách khoảng bao nhiêu?",
        }
    )

    decision = route_question(
        AskQuestionRequest(question="kiếm cho tôi lô đất ok xíu"),
        make_context(tier="admin"),
        planner=planner,
    )

    assert planner.call_count == 1
    assert decision.needs_clarification is True
    assert decision.question_type == "clarification"
    assert decision.tool_calls == []
    assert "khu vực" in (decision.clarification_question or "").lower()


def test_planner_routes_ward_opportunity_question_to_deal_search():
    planner = PlannerSpy(
        {
            "depth": "fast",
            "question_type": "deal_search",
            "tool_calls": [
                {
                    "call_id": "plan-ward-opportunity",
                    "name": "search_deals",
                    "arguments": {
                        "wards": ["Tân An"],
                        "mos_min_pct": 10.0,
                        "limit": 10,
                    },
                }
            ],
            "generated": False,
            "use_thinking": False,
        }
    )

    decision = route_question(
        AskQuestionRequest(question="Tân An có gì đáng xem"),
        make_context(tier="admin"),
        planner=planner,
    )

    assert planner.call_count == 1
    assert decision.question_type == "deal_search"
    assert decision.tool_calls[0].name == "search_deals"
    assert decision.tool_calls[0].arguments["wards"] == ["Tân An"]


def test_unmatched_question_without_planner_fails_closed():
    with pytest.raises(PlannerRequired):
        route_question(
            AskQuestionRequest(question="Tôi nên bắt đầu phân tích từ đâu?"),
            make_context(),
        )


def test_planner_unknown_tool_is_rejected_before_dispatch():
    planner = PlannerSpy(
        {
            "depth": "standard",
            "question_type": "unsafe",
            "tool_calls": [
                {"call_id": "x", "name": "run_sql", "arguments": {"sql": "SELECT *"}}
            ],
            "generated": True,
        }
    )

    with pytest.raises(ToolNotAllowed):
        route_question(
            AskQuestionRequest(question="Cho tôi tự truy vấn"),
            make_context(),
            planner=planner,
        )


def test_planner_tool_count_is_capped_by_depth_and_tier():
    calls = [
        {
            "call_id": f"c-{index}",
            "name": "get_listing_facts",
            "arguments": {"listing_id": index + 1},
        }
        for index in range(4)
    ]
    free_planner = PlannerSpy(
        {
            "depth": "deep",
            "question_type": "deep_listing",
            "tool_calls": calls[:3],
            "generated": True,
        }
    )
    vip_planner = PlannerSpy(
        {
            "depth": "deep",
            "question_type": "deep_listing",
            "tool_calls": calls,
            "generated": True,
        }
    )

    with pytest.raises(RoutingPolicyViolation, match="tool-call limit"):
        route_question(
            AskQuestionRequest(question="Nghiên cứu sâu danh mục"),
            make_context(tier="free"),
            planner=free_planner,
        )
    accepted = route_question(
        AskQuestionRequest(question="Nghiên cứu sâu danh mục"),
        make_context(tier="vip"),
        planner=vip_planner,
    )
    assert len(accepted.tool_calls) == 4


def test_default_registry_contains_only_approved_phase_two_tools():
    assert set(DEFAULT_TOOL_REGISTRY.registrations) == set(APPROVED_TOOL_NAMES)
    assert len(APPROVED_TOOL_NAMES) == 18


@pytest.mark.parametrize(
    "call",
    [
        ToolCall(
            call_id="extra",
            name="search_deals",
            arguments={"limit": 5, "sql": "SELECT * FROM users"},
        ),
        ToolCall(
            call_id="limit",
            name="search_deals",
            arguments={"limit": 500},
        ),
        ToolCall(
            call_id="url",
            name="search_official_documents",
            arguments={"query": "https://evil.example/fetch", "limit": 5},
        ),
        ToolCall(
            call_id="path",
            name="search_official_documents",
            arguments={"query": "../../etc/passwd", "limit": 5},
        ),
        ToolCall(
            call_id="python",
            name="search_official_documents",
            arguments={"query": "__import__('os').system('id')", "limit": 5},
        ),
    ],
)
def test_unsafe_extra_or_out_of_range_tool_arguments_are_rejected(call):
    with pytest.raises(ToolArgumentsInvalid):
        DEFAULT_TOOL_REGISTRY.validate_call(call)


def test_unknown_tool_is_rejected_before_handler_lookup():
    call = ToolCall(call_id="unknown", name="fetch_url", arguments={})

    with pytest.raises(ToolNotAllowed):
        execute_tool(call, ToolContext(ask=make_context()))


class FakeArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    listing_id: int = Field(gt=0)


def test_registry_validates_typed_args_then_dispatches_fake_handler():
    observed = []

    def handler(*, args, context):
        observed.append((args, context))
        return EvidenceBundle(
            question_snapshot="Tin #7",
            retrieval_quality=RetrievalQuality.SUFFICIENT,
        )

    registry = ToolRegistry(
        {
            "fake_listing": ToolRegistration(
                name="fake_listing",
                description="Test-only listing tool",
                args_model=FakeArgs,
                handler=handler,
            )
        }
    )
    context = ToolContext(ask=make_context())

    result = execute_tool(
        ToolCall(
            call_id="fake",
            name="fake_listing",
            arguments={"listing_id": 7},
        ),
        context,
        registry=registry,
    )

    assert result.retrieval_quality is RetrievalQuality.SUFFICIENT
    assert observed[0][0].listing_id == 7
    assert observed[0][1] is context
