"""Bounded DeepSeek Flash planner for non-deterministic Radar Ask questions."""
from __future__ import annotations

import json
import re
from decimal import Decimal

from pydantic import ValidationError

from .config import RadarAskSettings
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
_LABELED_PERSON = re.compile(
    r"(?i)\b(?:chủ\s*đất|chủ\s*nhà|môi\s*giới|người\s*bán|khách\s*hàng|họ\s*tên)"
    r"\s*[:=-]?\s*[^,;\n]{2,80}"
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
    ):
        self.settings = settings
        self.provider = provider
        self.registry = registry

    def __call__(
        self,
        *,
        request: AskQuestionRequest,
        context: AskContext,
        allowed_tools: tuple[str, ...],
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
                "tool_registry": definitions,
                "route_schema": RouteDecision.model_json_schema(mode="validation"),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        response = self.provider.complete(
            ProviderRequest(
                model=self.settings.router_model,
                messages=[
                    ProviderMessage(role="system", content=system),
                    ProviderMessage(role="user", content=user),
                ],
                max_output_tokens=PLANNER_MAX_OUTPUT_TOKENS,
                thinking_enabled=False,
                json_mode=True,
            )
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
