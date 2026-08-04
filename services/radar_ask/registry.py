"""Typed, fixed Radar Ask evidence-tool registry and dispatch boundary."""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
from typing import Any, Callable, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .contracts import AskContext, EvidenceBundle, ProviderToolDefinition, ToolCall


class ToolRegistryError(RuntimeError):
    """Base class for fail-closed registry errors."""


class ToolNotAllowed(ToolRegistryError):
    def __init__(self, tool_name: str):
        self.tool_name = tool_name
        super().__init__("Requested Radar Ask tool is not allowlisted")


class ToolArgumentsInvalid(ToolRegistryError):
    def __init__(self, tool_name: str):
        self.tool_name = tool_name
        super().__init__("Radar Ask tool arguments are invalid")


class ToolNotImplemented(ToolRegistryError):
    def __init__(self, tool_name: str):
        self.tool_name = tool_name
        super().__init__("Radar Ask evidence tool is not available yet")


_UNSAFE_VALUE_PATTERNS = (
    re.compile(r"(?:https?|ftp|file)://", re.I),
    re.compile(r"(?:^|[\s'\"])(?:\.\.[\\/]|[A-Za-z]:[\\/]|/(?:etc|proc|sys|var|home)/)", re.I),
    re.compile(r"\b(?:select\s+.+\s+from|insert\s+into|update\s+.+\s+set|delete\s+from|drop\s+table|alter\s+table|create\s+table)\b", re.I),
    re.compile(r"(?:__import__|\beval\s*\(|\bexec\s*\(|\blambda\s+)", re.I),
)


def _walk_values(value: Any):
    if isinstance(value, Mapping):
        for nested in value.values():
            yield from _walk_values(nested)
    elif isinstance(value, (list, tuple, set)):
        for nested in value:
            yield from _walk_values(nested)
    else:
        yield value


class SafeToolArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    @model_validator(mode="after")
    def reject_code_urls_and_paths(self):
        for value in _walk_values(self.model_dump(mode="python")):
            if isinstance(value, str) and any(
                pattern.search(value) for pattern in _UNSAFE_VALUE_PATTERNS
            ):
                raise ValueError("unsafe tool argument")
        return self


class ResolveListingArgs(SafeToolArgs):
    listing_id: int | None = Field(default=None, gt=0)


class ResolveLocationArgs(SafeToolArgs):
    city: str | None = Field(default=None, min_length=2, max_length=120)
    ward: str = Field(min_length=2, max_length=120)


class ResolveRoadArgs(SafeToolArgs):
    road: str = Field(min_length=2, max_length=180)
    city: str | None = Field(default=None, min_length=2, max_length=120)
    ward: str | None = Field(default=None, min_length=2, max_length=120)


class ListingFactsArgs(SafeToolArgs):
    listing_id: int = Field(gt=0)


class HistoryArgs(SafeToolArgs):
    listing_id: int = Field(gt=0)
    limit: int = Field(default=20, ge=1, le=50)


class ExplainValuationArgs(SafeToolArgs):
    listing_id: int = Field(gt=0)


class ComparableArgs(SafeToolArgs):
    listing_id: int = Field(gt=0)
    limit: int = Field(default=10, ge=3, le=20)
    window_days: int = Field(default=180, ge=30, le=365)


class SampleQualityArgs(SafeToolArgs):
    listing_id: int = Field(gt=0)


class RoadMarketArgs(SafeToolArgs):
    road: str = Field(min_length=2, max_length=180)
    ward: str | None = Field(default=None, min_length=2, max_length=120)
    city: str | None = Field(default=None, min_length=2, max_length=120)
    property_type: str | None = Field(default=None, max_length=80)
    window_days: int = Field(default=90, ge=30, le=180)


class CompareAreasArgs(SafeToolArgs):
    areas: list[str] = Field(min_length=2, max_length=4)
    property_type: str | None = Field(default=None, max_length=80)
    window_days: int = Field(default=90, ge=30, le=180)


class MarketTrendArgs(SafeToolArgs):
    ward: str | None = Field(default=None, min_length=2, max_length=120)
    road: str | None = Field(default=None, min_length=2, max_length=180)
    property_type: str | None = Field(default=None, max_length=80)
    window_days: int = Field(default=90, ge=1, le=180)


class MatchBudgetArgs(SafeToolArgs):
    budget_ty: Decimal = Field(gt=Decimal("0"), le=Decimal("500"))
    city: str | None = Field(default=None, min_length=2, max_length=120)
    wards: list[str] = Field(default_factory=list, max_length=10)
    property_types: list[str] = Field(default_factory=list, max_length=5)
    limit: int = Field(default=10, ge=1, le=20)


class SearchDealsArgs(SafeToolArgs):
    max_price_per_m2_million: Decimal | None = Field(
        default=None,
        gt=Decimal("0"),
        le=Decimal("1000"),
    )
    max_budget_ty: Decimal | None = Field(
        default=None,
        gt=Decimal("0"),
        le=Decimal("500"),
    )
    wards: list[str] = Field(default_factory=list, max_length=10)
    property_types: list[str] = Field(default_factory=list, max_length=5)
    mos_min_pct: Decimal = Field(default=Decimal("15"), ge=Decimal("10"), le=Decimal("80"))
    limit: int = Field(default=10, ge=1, le=20)


class RankPriceDropAreasArgs(SafeToolArgs):
    window_days: int = Field(default=1, ge=1, le=30)
    limit: int = Field(default=10, ge=1, le=20)


class InspectListingRisksArgs(SafeToolArgs):
    listing_id: int = Field(gt=0)


class OfficialLandPriceArgs(SafeToolArgs):
    area: str = Field(min_length=2, max_length=160)
    street: str = Field(min_length=2, max_length=180)
    segment: str | None = Field(default=None, max_length=300)


class SearchOfficialDocumentsArgs(SafeToolArgs):
    query: str = Field(min_length=3, max_length=500)
    limit: int = Field(default=5, ge=1, le=10)


@dataclass(frozen=True)
class ToolContext:
    ask: AskContext
    read_conn_factory: Callable[[], Any] | None = None


ToolHandler = Callable[..., EvidenceBundle]


@dataclass(frozen=True)
class ToolRegistration:
    name: str
    description: str
    args_model: type[BaseModel]
    handler: ToolHandler | None = None

    def __post_init__(self):
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,79}", self.name):
            raise ValueError("tool registration name is invalid")
        if not self.description or len(self.description) > 1_000:
            raise ValueError("tool description is invalid")
        if not issubclass(self.args_model, BaseModel):
            raise TypeError("args_model must be a Pydantic model")


class ToolRegistry:
    def __init__(self, registrations: Mapping[str, ToolRegistration]):
        copied = dict(registrations)
        if not copied or len(copied) > 18:
            raise ValueError("tool registry must contain between 1 and 18 tools")
        for key, registration in copied.items():
            if key != registration.name:
                raise ValueError("tool registry key must match registration name")
        self.registrations = MappingProxyType(copied)

    def get(self, name: str) -> ToolRegistration:
        registration = self.registrations.get(name)
        if registration is None:
            raise ToolNotAllowed(name)
        return registration

    def validate_call(self, call: ToolCall) -> BaseModel:
        registration = self.get(call.name)
        try:
            return registration.args_model.model_validate(call.arguments)
        except (ValidationError, ValueError, TypeError) as exc:
            raise ToolArgumentsInvalid(call.name) from exc

    def provider_definitions(self) -> list[ProviderToolDefinition]:
        return [
            ProviderToolDefinition(
                name=registration.name,
                description=registration.description,
                parameters=registration.args_model.model_json_schema(mode="validation"),
            )
            for registration in self.registrations.values()
        ]


APPROVED_TOOL_NAMES = (
    "resolve_listing",
    "resolve_location",
    "resolve_road",
    "get_listing_facts",
    "get_price_history",
    "get_lot_history",
    "explain_valuation",
    "find_comparables",
    "check_sample_quality",
    "estimate_road_market",
    "compare_areas",
    "get_market_trend",
    "match_budget",
    "search_deals",
    "rank_price_drop_areas",
    "inspect_listing_risks",
    "lookup_official_land_price",
    "search_official_documents",
)


def _lazy_entity_handler(function_name: str) -> ToolHandler:
    def handler(*, args: BaseModel, context: ToolContext) -> EvidenceBundle:
        from .tools import entities

        function = getattr(entities, function_name)
        return function(args=args, context=context)

    return handler


def _lazy_listing_handler(function_name: str) -> ToolHandler:
    def handler(*, args: BaseModel, context: ToolContext) -> EvidenceBundle:
        from .tools import listings

        function = getattr(listings, function_name)
        return function(args=args, context=context)

    return handler


def _lazy_valuation_handler(function_name: str) -> ToolHandler:
    def handler(*, args: BaseModel, context: ToolContext) -> EvidenceBundle:
        from .tools import valuation

        function = getattr(valuation, function_name)
        return function(args=args, context=context)

    return handler


def _lazy_market_handler(function_name: str) -> ToolHandler:
    def handler(*, args: BaseModel, context: ToolContext) -> EvidenceBundle:
        from .tools import market

        function = getattr(market, function_name)
        return function(args=args, context=context)

    return handler


def _registration(
    name: str,
    description: str,
    args_model: type[BaseModel],
    handler: ToolHandler | None = None,
):
    return ToolRegistration(
        name=name,
        description=description,
        args_model=args_model,
        handler=handler,
    )


_DEFAULT_REGISTRATIONS = {
    item.name: item
    for item in (
        _registration(
            "resolve_listing",
            "Resolve one tier-visible Radar listing reference.",
            ResolveListingArgs,
            _lazy_entity_handler("resolve_listing"),
        ),
        _registration(
            "resolve_location",
            "Resolve a bounded canonical Radar market location.",
            ResolveLocationArgs,
            _lazy_entity_handler("resolve_location"),
        ),
        _registration(
            "resolve_road",
            "Resolve one road in city and ward context.",
            ResolveRoadArgs,
            _lazy_entity_handler("resolve_road"),
        ),
        _registration(
            "get_listing_facts",
            "Return redacted facts for one listing.",
            ListingFactsArgs,
            _lazy_listing_handler("get_listing_facts"),
        ),
        _registration(
            "get_price_history",
            "Return bounded asking-price history.",
            HistoryArgs,
            _lazy_listing_handler("get_price_history"),
        ),
        _registration(
            "get_lot_history",
            "Return bounded canonical-lot repost history.",
            HistoryArgs,
            _lazy_listing_handler("get_lot_history"),
        ),
        _registration(
            "explain_valuation",
            "Return the persisted deterministic valuation trace.",
            ExplainValuationArgs,
            _lazy_valuation_handler("explain_valuation"),
        ),
        _registration(
            "find_comparables",
            "Return bounded eligible comparable listings.",
            ComparableArgs,
            _lazy_valuation_handler("find_comparables"),
        ),
        _registration(
            "check_sample_quality",
            "Assess deterministic valuation sample quality.",
            SampleQualityArgs,
            _lazy_valuation_handler("check_sample_quality"),
        ),
        _registration(
            "estimate_road_market",
            "Estimate bounded asking-market statistics for a road.",
            RoadMarketArgs,
            _lazy_market_handler("estimate_road_market"),
        ),
        _registration(
            "compare_areas",
            "Compare bounded asking-market statistics across areas.",
            CompareAreasArgs,
            _lazy_market_handler("compare_areas"),
        ),
        _registration(
            "get_market_trend",
            "Return a bounded market trend window.",
            MarketTrendArgs,
            _lazy_market_handler("get_market_trend"),
        ),
        _registration(
            "match_budget",
            "Match a bounded budget to eligible market areas.",
            MatchBudgetArgs,
            _lazy_market_handler("match_budget"),
        ),
        _registration(
            "search_deals",
            "Search current actionable Radar deal candidates.",
            SearchDealsArgs,
            _lazy_market_handler("search_deals"),
        ),
        _registration(
            "rank_price_drop_areas",
            "Rank areas by bounded current price-drop signals.",
            RankPriceDropAreasArgs,
            _lazy_market_handler("rank_price_drop_areas"),
        ),
        _registration(
            "inspect_listing_risks",
            "Return deterministic risk flags for one listing.",
            InspectListingRisksArgs,
            _lazy_market_handler("inspect_listing_risks"),
        ),
        _registration("lookup_official_land_price", "Look up one curated official land-price row.", OfficialLandPriceArgs),
        _registration("search_official_documents", "Search curated official and Radar knowledge only.", SearchOfficialDocumentsArgs),
    )
}

DEFAULT_TOOL_REGISTRY = ToolRegistry(_DEFAULT_REGISTRATIONS)
TOOL_REGISTRY = DEFAULT_TOOL_REGISTRY.registrations


def execute_tool(
    call: ToolCall,
    context: ToolContext,
    *,
    registry: ToolRegistry = DEFAULT_TOOL_REGISTRY,
) -> EvidenceBundle:
    registration = registry.get(call.name)
    args = registry.validate_call(call)
    if registration.handler is None:
        raise ToolNotImplemented(call.name)
    result = registration.handler(args=args, context=context)
    if isinstance(result, EvidenceBundle):
        return result
    try:
        return EvidenceBundle.model_validate(result)
    except (ValidationError, TypeError, ValueError) as exc:
        raise ToolRegistryError("Radar Ask tool returned an invalid evidence bundle") from exc
