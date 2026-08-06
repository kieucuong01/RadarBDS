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
from .provider import ProviderError


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
CONVERSATION_QUESTION_TYPES = frozenset({"conversation", "help", "off_topic"})


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


def _listing_ids_from_question(question: str) -> list[int]:
    """Extract explicit Radar listing IDs from user-visible follow-up text."""
    matches = re.findall(
        r"(?i)(?:#|tin\s*#?|mã\s*tin\s*#?|ma\s*tin\s*#?)\s*(\d{1,9})",
        question,
    )
    result: list[int] = []
    seen: set[int] = set()
    for raw in matches:
        listing_id = int(raw)
        if listing_id <= 0 or listing_id in seen:
            continue
        seen.add(listing_id)
        result.append(listing_id)
        if len(result) >= 2:
            break
    return result


def _max_ppm2(folded: str) -> float | None:
    value = _parse_number(
        re.search(r"(?:duoi|toi da|max)\s*(\d+(?:[,.]\d+)?)\s*trieu(?:\s*/\s*m2)?", folded)
    )
    return value if value is not None and 0.1 <= value <= 1_000 else None


def _property_type(folded: str) -> str | None:
    if "dat nen" in folded:
        return "dat_nen"
    if "nha dat" in folded or "nha pho" in folded:
        return "nha_dat"
    if "dat" in folded:
        return "dat_nen"
    return None


def _is_area_price_question(folded: str) -> bool:
    if "gia" not in folded:
        return False
    if any(
        marker in folded
        for marker in (
            "bao nhieu",
            "hien tai",
            "khoang",
            "mat bang gia",
            "gia sao",
            "gia the nao",
            "gia tam nao",
            "gia gio",
        )
    ):
        return True
    return bool(re.search(r"\bgia\b.*\b(?:nhieu|the nao|tam nao)\b[?!.]*$", folded))


def _asks_for_other_area(folded: str) -> bool:
    return any(
        marker in folded
        for marker in ("phuong khac", "khu khac", "cho khac", "noi khac")
    )


def _effective_wards(explicit_wards: list[str], context: AskContext, folded: str) -> list[str]:
    if explicit_wards:
        return explicit_wards
    if _asks_for_other_area(folded):
        return []
    if context.page.ward:
        return [context.page.ward]
    return list(context.session_memory.wards)


def _effective_property_types(explicit: str | None, context: AskContext) -> list[str]:
    if explicit:
        return [explicit]
    return list(context.session_memory.property_types)


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
    if decision.question_type in CONVERSATION_QUESTION_TYPES:
        if decision.tool_calls:
            raise RoutingPolicyViolation("conversation routes cannot include tool calls")
        return RouteDecision(
            depth=AskDepth.FAST,
            question_type=decision.question_type,
            tool_calls=[],
            generated=True,
            use_thinking=False,
            needs_clarification=False,
            clarification_question=None,
            required_freshness_hours=None,
        )
    depth = requested_depth or decision.depth
    generated = decision.generated or depth is AskDepth.DEEP
    if depth is AskDepth.FAST and decision.tool_calls:
        generated = False
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
    listing_id = context.page.listing_id or context.session_memory.listing_id
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
    explicit_listing_ids = _listing_ids_from_question(question)

    if explicit_listing_ids and any(
        marker in folded for marker in ("so sanh", "khac nhau", "voi")
    ):
        return RouteDecision(
            depth=AskDepth.STANDARD,
            question_type="listing_comparison",
            tool_calls=[
                _call(f"valuation-{listing_id}", "explain_valuation", {"listing_id": listing_id})
                for listing_id in explicit_listing_ids[:2]
            ],
            generated=True,
            use_thinking=False,
            required_freshness_hours=24,
        )

    if explicit_listing_ids and (
        valuation_question
        or any(marker in folded for marker in ("giai thich", "tai sao", "vi sao", "dinh gia"))
    ):
        listing_id = explicit_listing_ids[0]
        return RouteDecision(
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

    if has_placeholder and (valuation_question or road_question):
        return _clarification(question, requested_depth=requested_depth)
    if (
        (valuation_question or listing_risk_question)
        and listing_reference
        and listing_id is None
    ):
        return _clarification(question, requested_depth=requested_depth)

    if valuation_question and listing_id is not None:
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

    if listing_risk_question and listing_id is not None:
        return _base_decision(
            question_type="listing_risk",
            calls=[
                _call(
                    "listing-risk",
                    "inspect_listing_risks",
                    {"listing_id": listing_id},
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
        road_wards = _effective_wards(_known_wards(folded), context, folded)
        if len(road_wards) == 1:
            arguments["ward"] = road_wards[0]
        return _base_decision(
            question_type="road_market_estimate",
            calls=[_call("road-market", "estimate_road_market", arguments)],
            generated=False,
            freshness_hours=24,
        )

    explicit_wards = _known_wards(folded)
    wards = _effective_wards(explicit_wards, context, folded)
    explicit_property_type = _property_type(folded)
    property_types = _effective_property_types(explicit_property_type, context)
    if len(explicit_wards) >= 2 and any(
        marker in folded for marker in ("so sanh", "khac nhau", "voi", "va")
    ):
        return _base_decision(
            question_type="area_comparison",
            calls=[
                _call(
                    "area-comparison",
                    "compare_areas",
                    {
                        "areas": explicit_wards[:4],
                        "property_type": explicit_property_type,
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
        and (
            _is_area_price_question(folded)
            or any(marker in folded for marker in ("mat bang", "gio"))
        )
    ):
        return _base_decision(
            question_type="area_market_estimate",
            calls=[
                _call(
                    "area-market",
                    "compare_areas",
                    {
                        "areas": wards,
                        "property_type": property_types[0] if property_types else None,
                        "window_days": 90,
                    },
                )
            ],
            generated=False,
            freshness_hours=24,
        )

    budget = _budget_ty(folded)
    if budget is not None and (
        any(marker in folded for marker in ("ngan sach", "nen xem", "mua", "phuong nao"))
        or bool(wards)
    ):
        arguments = {"budget_ty": budget, "limit": 10}
        if "thu dau mot" in folded:
            arguments["city"] = "Thủ Dầu Một"
        elif "ben cat" in folded:
            arguments["city"] = "Bến Cát"
        elif context.page.city:
            arguments["city"] = context.page.city
        elif context.session_memory.city:
            arguments["city"] = context.session_memory.city
        if wards:
            arguments["wards"] = wards[:10]
        if property_types:
            arguments["property_types"] = property_types[:5]
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
        if len(explicit_wards) == 1:
            arguments["ward"] = explicit_wards[0]
        elif context.page.ward and not _asks_for_other_area(folded):
            arguments["ward"] = context.page.ward
        elif len(wards) == 1:
            arguments["ward"] = wards[0]
        if context.page.road:
            arguments["road"] = context.page.road
        if property_types:
            arguments["property_type"] = property_types[0]
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


def _explicit_area_comparison_guard(
    request: AskQuestionRequest,
    context: AskContext,
) -> RouteDecision | None:
    """High-confidence correction when the user explicitly compares named areas.

    The typed planner remains the first intent layer, but it can occasionally
    narrow a multi-area comparison to the first area.  This guard preserves the
    user's explicit comparison set before the evidence presenter runs.
    """
    deterministic = _deterministic_route(request, context)
    if deterministic is None or deterministic.question_type != "area_comparison":
        return None
    areas = deterministic.tool_calls[0].arguments.get("areas") if deterministic.tool_calls else None
    if not isinstance(areas, list) or len(areas) < 2:
        return None
    return deterministic


def _route_covers_explicit_comparison(
    planned: RouteDecision,
    guard: RouteDecision,
) -> bool:
    expected = guard.tool_calls[0].arguments.get("areas") if guard.tool_calls else None
    if not isinstance(expected, list):
        return True
    expected_set = {str(area) for area in expected}
    for call in planned.tool_calls:
        if call.name != "compare_areas":
            continue
        planned_areas = call.arguments.get("areas")
        if isinstance(planned_areas, list) and expected_set.issubset(
            {str(area) for area in planned_areas}
        ):
            return planned.question_type == "area_comparison"
    return False


def route_question(
    request: AskQuestionRequest,
    context: AskContext,
    *,
    planner: Planner | None = None,
    registry: ToolRegistry = DEFAULT_TOOL_REGISTRY,
) -> RouteDecision:
    requested_depth = _depth_requested(request, _fold(request.question))
    planner_failed_invalid = False
    if planner is not None:
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
            planned = RouteDecision.model_validate(raw_decision)
            finalized = _finalize(
                planned,
                context=context,
                requested_depth=requested_depth,
                registry=registry,
            )
            comparison_guard = _explicit_area_comparison_guard(request, context)
            if comparison_guard is not None and not _route_covers_explicit_comparison(
                finalized,
                comparison_guard,
            ):
                return _finalize(
                    comparison_guard,
                    context=context,
                    requested_depth=requested_depth,
                    registry=registry,
                )
            return finalized
        except ProviderError:
            planner_failed_invalid = False
        except (ValidationError, TypeError, ValueError):
            planner_failed_invalid = True

    deterministic = _deterministic_route(request, context)
    if deterministic is not None:
        return _finalize(
            deterministic,
            context=context,
            requested_depth=requested_depth,
            registry=registry,
        )
    if planner is None:
        raise PlannerRequired("question requires the typed planner")
    if planner_failed_invalid:
        raise RoutingPolicyViolation("planner returned an invalid typed route")
    raise PlannerRequired("question requires the typed planner")


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
