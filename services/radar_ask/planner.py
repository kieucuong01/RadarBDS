"""Bounded DeepSeek Flash planner for non-deterministic Radar Ask questions."""
from __future__ import annotations

import json
import re
from decimal import Decimal
from time import monotonic
from typing import Callable

from pydantic import ValidationError

from .config import RadarAskSettings, request_provider_budget_seconds
from .contracts import (
    AskContext,
    AskQuestionRequest,
    PlannerResult,
    ProviderMessage,
    ProviderRequest,
    RouteDecision,
)
from .provider import ProviderInvalidResponse, RadarAskProvider
from .registry import ToolRegistry


PLANNER_MAX_OUTPUT_TOKENS = 1_200
PLANNER_MAX_COST_USD = Decimal("0.01")
INVESTOR_INTENT_EXAMPLES = (
    {
        "question": "kiếm cho tôi lô đất tại Tân An ok xíu",
        "depth": "fast",
        "question_type": "deal_search",
        "tool_calls": [
            {
                "call_id": "example-deal-search",
                "name": "search_deals",
                "arguments": {
                    "wards": ["Tân An"],
                    "property_types": ["dat"],
                    "mos_min_pct": 10.0,
                    "limit": 10,
                },
            }
        ],
        "rule": "Câu hỏi đời thường muốn tìm lô đáng xem/rẻ/ok thì dùng search_deals, không dùng compare_areas.",
    },
    {
        "question": "Tân An có lô nào 500m2 rẻ k",
        "depth": "fast",
        "question_type": "deal_search",
        "tool_calls": [
            {
                "call_id": "example-area-deal",
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
        "rule": "Diện tích mục tiêu có thể đổi thành khoảng +/-10% để tìm deal gần nhu cầu.",
    },
    {
        "question": "hiện có bao nhiêu lô giảm giá ở Tân An",
        "depth": "fast",
        "question_type": "price_drop_ranking",
        "tool_calls": [
            {
                "call_id": "example-price-drop-count",
                "name": "rank_price_drop_areas",
                "arguments": {
                    "wards": ["Tân An"],
                    "window_days": 7,
                    "limit": 10,
                },
            }
        ],
        "rule": "Câu hỏi số lượng lô giảm giá theo phường dùng rank_price_drop_areas với wards, không dùng compare_areas.",
    },
)
_PHONE = re.compile(r"(?<!\d)(?:\+?84|0)(?:[\s.()-]*\d){8,10}(?!\d)")
_URL = re.compile(r"(?i)\b(?:https?://|www\.)[^\s\"'<>]+")
_EMAIL = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
_SECRET = re.compile(
    r"(?i)\b(?:authorization\s*:\s*)?bearer\s+[A-Za-z0-9._~+/=-]{8,}"
)
_SENSITIVE_IDENTIFIER = re.compile(
    r"(?i)\b(?:cccd|cmnd|căn\s*cước(?:\s*công\s*dân)?|mã\s*số\s*thuế|mst|"
    r"số\s*tài\s*khoản|stk|tài\s*khoản\s*ngân\s*hàng)\s*[:#=-]?\s*"
    r"[A-Z0-9][A-Z0-9 .-]{5,30}"
)
_PARCEL_IDENTIFIER = re.compile(
    r"(?i)\b(?:thửa(?:\s*đất)?|số\s*thửa)\s*(?:số)?\s*[:#=-]?\s*\d{1,8}"
    r"(?:\s*(?:[,;/ -]|và)\s*(?:tờ(?:\s*bản\s*đồ)?|tbđ)\s*(?:số)?\s*"
    r"[:#=-]?\s*\d{1,6})?"
)
_PERSON_WORD = r"[A-Za-zÀ-ỹĐđ'’\-]{1,31}"
_PERSON_LABEL = r"(?:chủ\s*đất|chủ\s*nhà|môi\s*giới|người\s*bán|khách\s*hàng|họ\s*tên)"
_NON_NAME_START = r"(?:không|chưa|đang|đã|sẽ|muốn|cần|bán|giảm|tăng)"
_LABELED_PERSON = re.compile(
    rf"(?i:\b{_PERSON_LABEL})"
    rf"\s*(?:[:=-]\s*)?(?!(?i:{_NON_NAME_START})\b)"
    rf"{_PERSON_WORD}(?:\s+{_PERSON_WORD}){{0,4}}"
    r"(?=\s*(?:[,;.!?\n]|$))"
)


class PlannerOutputInvalid(ProviderInvalidResponse):
    """The provider call incurred usage but did not produce a typed route."""


def _redact(value: str | None, *, maximum: int) -> str | None:
    if value is None:
        return None
    bounded = value[:maximum]
    bounded = _SECRET.sub("[REDACTED]", bounded)
    bounded = _URL.sub("[REDACTED]", bounded)
    bounded = _EMAIL.sub("[REDACTED_EMAIL]", bounded)
    bounded = _LABELED_PERSON.sub("[REDACTED_PERSON]", bounded)
    bounded = _PARCEL_IDENTIFIER.sub("[REDACTED_PARCEL]", bounded)
    bounded = _SENSITIVE_IDENTIFIER.sub("[REDACTED_IDENTIFIER]", bounded)
    return _PHONE.sub("[REDACTED_PHONE]", bounded)


class DeepSeekTypedPlanner:
    """Return a typed route and its provider usage as one immutable value."""

    def __init__(
        self,
        *,
        settings: RadarAskSettings,
        provider: RadarAskProvider,
        registry: ToolRegistry,
        monotonic_fn: Callable[[], float] = monotonic,
    ):
        self.settings = settings
        self.provider = provider
        self.registry = registry
        self.monotonic_fn = monotonic_fn

    def __call__(
        self,
        *,
        request: AskQuestionRequest,
        context: AskContext,
        allowed_tools: tuple[str, ...],
        deadline: float | None = None,
    ) -> PlannerResult:
        allowed = tuple(dict.fromkeys(allowed_tools))
        if (
            not allowed
            or len(allowed) > 18
            or any(name not in self.registry.registrations for name in allowed)
        ):
            raise ValueError("planner tool allowlist is invalid")
        definitions = [
            definition.model_dump(mode="json")
            for definition in self.registry.provider_definitions()
            if definition.name in allowed
        ]
        page = {
            "listing_id": context.page.listing_id,
            "city": _redact(context.page.city, maximum=120),
            "ward": _redact(context.page.ward, maximum=120),
            "road": _redact(context.page.road, maximum=180),
        }
        system = (
            "Ban la bo dinh tuyen nghien cuu BDS cua Radar. Tra dung mot RouteDecision JSON. "
            "Chi chon tool trong registry va chi dung arguments dung JSON schema. "
            "Khong tao SQL, URL, file path, shell command, tool moi, du lieu nguoi dung, "
            "hay noi dung bang chung. Chon do sau toi thieu: fast cho mot phep tra cuu, "
            "standard cho so sanh toi da hai tool, deep khi can nhieu mien bang chung. "
            "Voi cau hoi đời thường nhu ok xiu, re, co lo nao, dang xem, hay bao nhieu lo, "
            "hay doc intent_examples de chon typed tool dung y dinh dau tu. "
            "Neu hoi so luong lo giam gia theo phuong, dung rank_price_drop_areas voi wards. "
            "Khong tu dat use_thinking; server se quyet dinh."
        )
        user = json.dumps(
            {
                "question": _redact(request.question, maximum=2_000),
                "tier": context.tier,
                "requested_depth": (
                    request.requested_depth.value if request.requested_depth else None
                ),
                "page_context": page,
                "intent_examples": INVESTOR_INTENT_EXAMPLES,
                "tool_registry": definitions,
                "route_schema": RouteDecision.model_json_schema(mode="validation"),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        absolute_deadline = (
            float(deadline)
            if deadline is not None
            else self.monotonic_fn()
            + request_provider_budget_seconds(self.settings.provider_timeout_seconds)
        )
        response = self.provider.complete_until(
            ProviderRequest(
                model=self.settings.router_model,
                messages=[
                    ProviderMessage(role="system", content=system),
                    ProviderMessage(role="user", content=user),
                ],
                max_output_tokens=PLANNER_MAX_OUTPUT_TOKENS,
                thinking_enabled=False,
                json_mode=True,
            ),
            deadline=absolute_deadline,
        )
        try:
            decision = RouteDecision.model_validate(response.json_value)
        except (ValidationError, TypeError, ValueError) as exc:
            raise PlannerOutputInvalid(
                "planner returned an invalid typed route",
                usage=response.usage,
            ) from exc
        return PlannerResult(decision=decision, usage=response.usage)


__all__ = (
    "DeepSeekTypedPlanner",
    "PLANNER_MAX_COST_USD",
    "PlannerOutputInvalid",
)
