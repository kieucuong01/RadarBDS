"""Adaptive Radar Ask routing with deterministic simple-question Fast Paths."""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Callable, Mapping, Protocol

from pydantic import ValidationError

from .contracts import (
    AskContext,
    AskDepth,
    AskQuestionRequest,
    PlannerResult,
    RouteDecision,
    ToolCall,
)
from .registry import APPROVED_TOOL_NAMES, DEFAULT_TOOL_REGISTRY, ToolRegistry


class RoutingError(RuntimeError):
    """Base class for safe Radar Ask routing failures."""


class PlannerRequired(RoutingError):
    """Raised when no deterministic route matches and no planner is injected."""


class RoutingPolicyViolation(RoutingError):
    """Raised when a typed plan exceeds its bounded execution policy."""


class Planner(Protocol):
    def __call__(
        self,
        *,
        request: AskQuestionRequest,
        context: AskContext,
        allowed_tools: tuple[str, ...],
        deadline: float | None = None,
    ) -> PlannerResult | RouteDecision | Mapping[str, Any]: ...


_WARD_ALIASES = {
    "tuong binh hiep": "Tương Bình Hiệp",
    "chanh nghia": "Chánh Nghĩa",
    "chanh my": "Chánh Mỹ",
    "dinh hoa": "Định Hòa",
    "hiep an": "Hiệp An",
    "hiep thanh": "Hiệp Thành",
    "hoa phu": "Hòa Phú",
    "phu cuong": "Phú Cường",
    "phu hoa": "Phú Hòa",
    "phu loi": "Phú Lợi",
    "phu my": "Phú Mỹ",
    "phu tan": "Phú Tân",
    "phu tho": "Phú Thọ",
    "tan an": "Tân An",
    "my phuoc 1": "Mỹ Phước 1",
    "my phuoc 2": "Mỹ Phước 2",
    "my phuoc 3": "Mỹ Phước 3",
    "my phuoc": "Mỹ Phước",
    "tan dinh": "Tân Định",
    "thoi hoa": "Thới Hòa",
}
_DEEP_MARKERS = (
    "nghien cuu sau",
    "phan tich ky",
    "phan tich sau",
    "deep research",
    "dao sau",
)


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    text = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    text = text.replace("đ", "d").replace("Đ", "D")
    return " ".join(text.replace("đ", "d").replace("Đ", "D").lower().split())


def _contains_phrase(text: str, phrase: str) -> bool:
    return bool(re.search(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])", text))


def _known_wards(folded: str) -> list[str]:
    matches: list[tuple[int, str]] = []
    for alias, canonical in _WARD_ALIASES.items():
        match = re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", folded)
        if match:
            matches.append((match.start(), canonical))
    matches.sort()
    seen: set[str] = set()
    result: list[str] = []
    for _position, canonical in matches:
        if canonical not in seen:
            seen.add(canonical)
            result.append(canonical)
    return result[:5]


def _parse_number(match: re.Match[str] | None) -> float | None:
    if match is None:
        return None
    try:
        return float(match.group(1).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _budget_ty(folded: str) -> float | None:
    value = _parse_number(
        re.search(r"(?:ngan sach|tam|co)\s*(\d+(?:[,.]\d+)?)\s*(?:ty|ti)\b", folded)
    )
    return value if value is not None and 0.1 <= value <= 500 else None


def _max_ppm2(folded: str) -> float | None:
    value = _parse_number(
        re.search(r"(?:duoi|toi da|max)\s*(\d+(?:[,.]\d+)?)\s*trieu(?:\s*/\s*m2)?", folded)
    )
    return value if value is not None and 0.1 <= value <= 1_000 else None


def _target_area_m2(folded: str) -> float | None:
    value = _parse_number(re.search(r"(\d+(?:[,.]\d+)?)\s*m2\b", folded))
    return value if value is not None and 5 <= value <= 100_000 else None


def _property_type(folded: str) -> str | None:
    if "dat nen" in folded:
        return "dat_nen"
    if "nha dat" in folded or "nha pho" in folded:
        return "nha_dat"
    if "dat" in folded:
        return "dat"
    return None


def _road_from_question(question: str) -> str | None:
    match = re.search(
        r"(?:đường|duong)\s+"
        r"([A-Za-zÀ-ỹ0-9][A-Za-zÀ-ỹ0-9 ._-]{1,80}?)"
        r"(?=\s+(?:là|la|bao nhiêu|bao nhieu|hiện tại|hien tai)\b|[?.,]|$)",
        question,
        flags=re.I,
    )
    if match is None:
        return None
    road = " ".join(match.group(1).split()).strip(" .,-")
    return road or None


def _depth_requested(request: AskQuestionRequest, folded: str) -> AskDepth | None:
    if request.requested_depth is not None:
        return request.requested_depth
    if any(marker in folded for marker in _DEEP_MARKERS):
        return AskDepth.DEEP
    return None


def _clarification(question: str, *, requested_depth: AskDepth | None) -> RouteDecision:
    folded = _fold(question)
    if "duong" in folded:
        message = "Bạn cho tôi tên đường chính xác và phường/khu vực của lô đất nhé?"
    else:
        message = "Bạn mở đúng tin hoặc gửi mã tin Radar để tôi phân tích chính xác lô đất nhé?"
    return RouteDecision(
        depth=requested_depth or AskDepth.FAST,
        question_type="clarification",
        tool_calls=[],
        generated=False,
        use_thinking=False,
        needs_clarification=True,
        clarification_question=message,
    )


def _call(call_id: str, name: str, arguments: dict[str, Any]) -> ToolCall:
    return ToolCall(call_id=call_id, name=name, arguments=arguments)


def _base_decision(
    *,
    question_type: str,
    calls: list[ToolCall],
    generated: bool,
    freshness_hours: int | None = None,
) -> RouteDecision:
    return RouteDecision(
        depth=AskDepth.FAST,
        question_type=question_type,
        tool_calls=calls,
        generated=generated,
        use_thinking=False,
        required_freshness_hours=freshness_hours,
    )


def _finalize(
    decision: RouteDecision,
    *,
    context: AskContext,
    requested_depth: AskDepth | None,
    registry: ToolRegistry,
) -> RouteDecision:
    if decision.needs_clarification:
        return decision
    depth = requested_depth or decision.depth
    generated = decision.generated or depth is AskDepth.DEEP
    if depth is AskDepth.DEEP:
        max_calls = 2 if context.tier == "free" else 4
    else:
        max_calls = 2
    if len(decision.tool_calls) > max_calls:
        raise RoutingPolicyViolation("route exceeds the tool-call limit")
    for call in decision.tool_calls:
        registry.validate_call(call)
    thinking = generated and depth is AskDepth.DEEP and context.tier in {"vip", "admin"}
    return RouteDecision(
        depth=depth,
        question_type=decision.question_type,
        tool_calls=decision.tool_calls,
        generated=generated,
        use_thinking=thinking,
        needs_clarification=False,
        clarification_question=None,
        required_freshness_hours=decision.required_freshness_hours,
    )


def _deterministic_route(
    request: AskQuestionRequest,
    context: AskContext,
) -> RouteDecision | None:
    question = request.question
    folded = _fold(question)
    requested_depth = _depth_requested(request, folded)
    has_placeholder = bool(re.search(r"(?<![a-z0-9])x{2,}(?![a-z0-9])", folded))
    listing_reference = any(
        phrase in folded for phrase in ("lo dat nay", "lo nay", "tin nay")
    )
    valuation_question = "dinh gia" in folded and any(
        phrase in folded for phrase in ("tai sao", "vi sao", "giai thich")
    )
    listing_risk_question = listing_reference and any(
        phrase in folded
        for phrase in (
            "rui ro",
            "can kiem tra",
            "dang kiem tra khong",
            "co dang kiem tra",
            "deal sach",
            "co nen xem",
            "co nen mua",
            "phap ly",
        )
    )
    road_question = "duong" in folded and any(
        phrase in folded for phrase in ("gia", "bao nhieu", "hien tai", "mat tien")
    )

    if has_placeholder and (valuation_question or road_question):
        return _clarification(question, requested_depth=requested_depth)
    if (
        (valuation_question or listing_risk_question)
        and listing_reference
        and context.page.listing_id is None
    ):
        return _clarification(question, requested_depth=requested_depth)

    if valuation_question and context.page.listing_id is not None:
        listing_id = context.page.listing_id
        decision = RouteDecision(
            depth=AskDepth.STANDARD,
            question_type="valuation_explanation",
            tool_calls=[
                _call("listing-facts", "get_listing_facts", {"listing_id": listing_id}),
                _call("valuation-trace", "explain_valuation", {"listing_id": listing_id}),
            ],
            generated=True,
            use_thinking=False,
            required_freshness_hours=24,
        )
        return decision

    if listing_risk_question and context.page.listing_id is not None:
        return _base_decision(
            question_type="listing_risk",
            calls=[
                _call(
                    "listing-risk",
                    "inspect_listing_risks",
                    {"listing_id": context.page.listing_id},
                )
            ],
            generated=False,
            freshness_hours=24,
        )

    if road_question:
        road = _road_from_question(question)
        if not road:
            return _clarification(question, requested_depth=requested_depth)
        arguments: dict[str, Any] = {
            "road": road,
            "property_type": _property_type(folded),
            "window_days": 90,
        }
        if context.page.ward:
            arguments["ward"] = context.page.ward
        else:
            wards_in_question = _known_wards(folded)
            if len(wards_in_question) == 1:
                arguments["ward"] = wards_in_question[0]
        return _base_decision(
            question_type="road_market_estimate",
            calls=[_call("road-market", "estimate_road_market", arguments)],
            generated=False,
            freshness_hours=24,
        )

    wards = _known_wards(folded)
    if len(wards) >= 2 and any(
        marker in folded for marker in ("so sanh", "khac nhau", "voi", "va")
    ):
        return _base_decision(
            question_type="area_comparison",
            calls=[
                _call(
                    "area-comparison",
                    "compare_areas",
                    {
                        "areas": wards[:4],
                        "property_type": _property_type(folded),
                        "window_days": 90,
                    },
                )
            ],
            generated=False,
            freshness_hours=24,
        )

    if (
        len(wards) == 1
        and "giam gia" not in folded
        and "bang gia dat" not in folded
        and ("gia" in folded or "dat" in folded)
        and any(marker in folded for marker in ("bao nhieu", "hien tai", "khoang", "mat bang", "gio"))
    ):
        return _base_decision(
            question_type="area_market_estimate",
            calls=[
                _call(
                    "area-market",
                    "compare_areas",
                    {
                        "areas": wards,
                        "property_type": _property_type(folded),
                        "window_days": 90,
                    },
                )
            ],
            generated=False,
            freshness_hours=24,
        )

    deal_intent_markers = (
        "kiem",
        "tim",
        "lo nao",
        "co lo",
        "re",
        "ok",
        "dang kiem tra",
        "deal",
    )
    if len(wards) == 1 and "giam gia" not in folded and any(
        marker in folded for marker in deal_intent_markers
    ):
        arguments: dict[str, Any] = {
            "wards": wards,
            "mos_min_pct": 10.0,
            "limit": 10,
        }
        property_type = _property_type(folded)
        if property_type:
            arguments["property_types"] = [property_type]
        target_area = _target_area_m2(folded)
        if target_area is not None:
            arguments["min_area_m2"] = round(target_area * 0.9, 2)
            arguments["max_area_m2"] = round(target_area * 1.1, 2)
        return _base_decision(
            question_type="deal_search",
            calls=[_call("deal-search", "search_deals", arguments)],
            generated=False,
            freshness_hours=24,
        )

    budget = _budget_ty(folded)
    if budget is not None and any(
        marker in folded for marker in ("ngan sach", "nen xem", "mua", "phuong nao")
    ):
        arguments = {"budget_ty": budget, "limit": 10}
        if "thu dau mot" in folded:
            arguments["city"] = "Thủ Dầu Một"
        elif "ben cat" in folded:
            arguments["city"] = "Bến Cát"
        return _base_decision(
            question_type="budget_match",
            calls=[_call("budget-match", "match_budget", arguments)],
            generated=False,
            freshness_hours=24,
        )

    max_ppm2 = _max_ppm2(folded)
    if max_ppm2 is not None and any(marker in folded for marker in ("tin nao", "deal", "dang kiem tra")):
        return _base_decision(
            question_type="deal_search",
            calls=[
                _call(
                    "deal-search",
                    "search_deals",
                    {
                        "max_price_per_m2_million": max_ppm2,
                        "mos_min_pct": 15.0,
                        "limit": 10,
                    },
                )
            ],
            generated=False,
            freshness_hours=24,
        )

    if "giam gia" in folded and any(
        marker in folded
        for marker in ("khu nao", "nhieu", "xep hang", "bao nhieu", "may lo", "co bao nhieu")
    ):
        window_days = 1 if "hom nay" in folded else 7
        arguments: dict[str, Any] = {"window_days": window_days, "limit": 10}
        if len(wards) == 1:
            arguments["wards"] = wards
        return _base_decision(
            question_type="price_drop_ranking",
            calls=[
                _call(
                    "price-drop-ranking",
                    "rank_price_drop_areas",
                    arguments,
                )
            ],
            generated=False,
            freshness_hours=24,
        )

    market_trend_markers = (
        "xu huong",
        "thi truong",
        "dang tang",
        "dang giam",
        "tang hay giam",
        "giam hay tang",
        "co tin hieu gi",
        "co nen dau tu",
        "dang dau tu",
        "nen dau tu",
        "nen xem khong",
        "khu nay the nao",
        "khu nay sao",
    )
    if any(marker in folded for marker in market_trend_markers):
        arguments: dict[str, Any] = {"window_days": 90}
        if context.page.ward:
            arguments["ward"] = context.page.ward
        elif len(wards) == 1:
            arguments["ward"] = wards[0]
        if context.page.road:
            arguments["road"] = context.page.road
        property_type = _property_type(folded)
        if property_type:
            arguments["property_type"] = property_type
        if "ward" in arguments or "road" in arguments:
            return _base_decision(
                question_type="market_trend",
                calls=[_call("market-trend", "get_market_trend", arguments)],
                generated=False,
                freshness_hours=24,
            )

    if "bang gia dat" in folded and any(
        marker in folded for marker in ("dinh gia", "thuc te", "dung de", "phap ly")
    ):
        return _base_decision(
            question_type="official_price_explanation",
            calls=[
                _call(
                    "official-docs",
                    "search_official_documents",
                    {"query": question, "limit": 5},
                )
            ],
            generated=False,
            freshness_hours=24 * 30,
        )
    return None


def route_question(
    request: AskQuestionRequest,
    context: AskContext,
    *,
    planner: Planner | None = None,
    registry: ToolRegistry = DEFAULT_TOOL_REGISTRY,
) -> RouteDecision:
    deterministic = _deterministic_route(request, context)
    requested_depth = _depth_requested(request, _fold(request.question))
    if deterministic is not None:
        return _finalize(
            deterministic,
            context=context,
            requested_depth=requested_depth,
            registry=registry,
        )
    if planner is None:
        raise PlannerRequired("question requires the typed planner")
    try:
        planned_value = planner(
            request=request,
            context=context,
            allowed_tools=tuple(registry.registrations),
        )
        raw_decision = (
            planned_value.decision
            if isinstance(planned_value, PlannerResult)
            else planned_value
        )
        planned = RouteDecision.model_validate(
            raw_decision
        )
    except (ValidationError, TypeError, ValueError) as exc:
        raise RoutingPolicyViolation("planner returned an invalid typed route") from exc
    return _finalize(
        planned,
        context=context,
        requested_depth=requested_depth,
        registry=registry,
    )


def finalize_planned_route(
    decision: RouteDecision,
    *,
    request: AskQuestionRequest,
    context: AskContext,
    registry: ToolRegistry = DEFAULT_TOOL_REGISTRY,
) -> RouteDecision:
    """Apply request/tier/registry policy to an already typed provider route."""
    return _finalize(
        RouteDecision.model_validate(decision),
        context=context,
        requested_depth=_depth_requested(request, _fold(request.question)),
        registry=registry,
    )
