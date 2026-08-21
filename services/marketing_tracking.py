"""PII-free normalization for first-party marketing audit events."""

from __future__ import annotations

import ipaddress
import re
from urllib.parse import parse_qsl, unquote, urlsplit


MARKETING_TRACK_ACTIONS = frozenset(
    {
        "seo_landing_viewed",
        "report_viewed",
        "social_utm_visit",
        "ai_referral_visit",
        "cta_clicked",
        "lead_capture_submit",
    }
)
CHANNELS = frozenset({"organic", "social", "ai", "direct_unknown"})
AI_SOURCES = frozenset({"chatgpt", "gemini", "perplexity", "copilot"})

_UTM_FIELDS = (
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_content",
    "utm_term",
)
_TOKEN_PATTERN = re.compile(r"[a-z0-9][a-z0-9._+-]*(?: [a-z0-9._+-]+)*")
_SLUG_PATTERN = re.compile(r"[a-z0-9][a-z0-9/_-]*")
_HOST_PATTERN = re.compile(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?")
_PHONE_LIKE_PATTERN = re.compile(r"(?:\+?84|0)\d{8,10}")
_DASHBOARD_TABS = frozenset({"signals", "all", "market", "insights"})
_DASHBOARD_FILTER_KEYS = frozenset(
    {
        "ward",
        "city",
        "source",
        "prop_type",
        "price_range",
        "area_range",
        "price_min",
        "price_max",
        "area_min",
        "area_max",
        "date_range",
        "mos_min",
    }
)


def _has_control_characters(value: str) -> bool:
    return any(ord(character) < 32 or ord(character) == 127 for character in value)


def _looks_sensitive_token(value: str) -> bool:
    compact = re.sub(r"[\s().-]+", "", value)
    if _PHONE_LIKE_PATTERN.fullmatch(compact) is not None:
        return True
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True


def _bounded_token(value: object, limit: int = 80) -> str | None:
    if not isinstance(value, str) or _has_control_characters(value):
        return None
    normalized = re.sub(r"\s+", " ", value.strip().lower())[:limit]
    if (
        not normalized
        or _TOKEN_PATTERN.fullmatch(normalized) is None
        or _looks_sensitive_token(normalized)
    ):
        return None
    return normalized


def _safe_internal_path(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if (
        not candidate
        or _has_control_characters(candidate)
        or "\\" in candidate
        or candidate.startswith("//")
    ):
        return None
    parsed = urlsplit(candidate)
    if parsed.scheme or parsed.netloc or not parsed.path.startswith("/"):
        return None
    decoded_path = unquote(parsed.path)
    if (
        _has_control_characters(decoded_path)
        or "\\" in decoded_path
        or decoded_path.startswith("//")
    ):
        return None
    return parsed.path[:180]


def _safe_slug(value: object) -> str | None:
    if not isinstance(value, str) or _has_control_characters(value):
        return None
    normalized = value.strip().strip("/").lower()[:180]
    if not normalized or _SLUG_PATTERN.fullmatch(normalized) is None:
        return None
    return normalized


def _external_destination_class(hostname: str) -> str:
    host = hostname.lower().rstrip(".")
    if host == "zalo.me" or host.endswith(".zalo.me"):
        return "external:zalo"
    if (
        host in {"facebook.com", "m.me", "messenger.com"}
        or host.endswith(".facebook.com")
        or host.endswith(".messenger.com")
    ):
        return "external:facebook"
    if host in {"t.me", "telegram.me"} or host.endswith(".telegram.me"):
        return "external:telegram"
    return "external:other"


def _safe_destination(value: object) -> str | None:
    internal = _safe_internal_path(value)
    if internal is not None:
        return internal
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if (
        not candidate
        or _has_control_characters(candidate)
        or candidate.startswith("//")
    ):
        return None
    parsed = urlsplit(candidate)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return None
    return _external_destination_class(parsed.hostname)


def _dashboard_handoff_metadata(value: object) -> dict[str, str]:
    """Retain only dashboard tab and filter names, never filter values."""
    if _safe_internal_path(value) != "/" or not isinstance(value, str):
        return {}
    try:
        pairs = parse_qsl(urlsplit(value.strip()).query, keep_blank_values=False)
    except ValueError:
        return {}

    tabs = {
        raw_value.strip().lower()
        for raw_key, raw_value in pairs
        if raw_key.strip().lower() == "tab" and raw_value.strip()
    }
    safe: dict[str, str] = {}
    if len(tabs) == 1:
        tab = next(iter(tabs))
        if tab in _DASHBOARD_TABS:
            safe["dashboard_tab"] = tab

    filter_keys = sorted(
        {
            raw_key.strip().lower()
            for raw_key, _raw_value in pairs
            if raw_key.strip().lower() in _DASHBOARD_FILTER_KEYS
        }
    )
    if filter_keys:
        safe["dashboard_filter_keys"] = ",".join(filter_keys)
    return safe


def _ai_source_for_host(value: object) -> tuple[str, str] | None:
    if not isinstance(value, str) or _has_control_characters(value):
        return None
    host = value.strip().lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    if not host or _HOST_PATTERN.fullmatch(host) is None:
        return None
    if (
        host == "chatgpt.com"
        or host.endswith(".chatgpt.com")
        or host == "chat.openai.com"
        or host.endswith(".openai.com")
    ):
        return "chatgpt", host
    if host == "gemini.google.com":
        return "gemini", host
    if host == "perplexity.ai" or host.endswith(".perplexity.ai"):
        return "perplexity", host
    if host == "copilot.microsoft.com":
        return "copilot", host
    return None


def _copy_page_fields(safe: dict[str, object], context: dict[str, object]) -> None:
    for field in ("path", "page_path"):
        value = _safe_internal_path(context.get(field))
        if value is not None:
            safe[field] = value
    page_slug = _safe_slug(context.get("page_slug"))
    if page_slug is not None:
        safe["page_slug"] = page_slug


def _copy_acquisition_fields(
    safe: dict[str, object],
    context: dict[str, object],
) -> None:
    channel = _bounded_token(context.get("channel"))
    if channel in CHANNELS:
        safe["channel"] = channel
    for field in _UTM_FIELDS:
        value = _bounded_token(context.get(field))
        if value is not None:
            safe[field] = value

    supplied_ai_source = _bounded_token(context.get("ai_source"))
    host_identity = _ai_source_for_host(context.get("referrer_host"))
    if supplied_ai_source in AI_SOURCES:
        safe["ai_source"] = supplied_ai_source
    if host_identity is not None:
        host_source, host = host_identity
        if supplied_ai_source in (None, host_source):
            safe.setdefault("ai_source", host_source)
            safe["referrer_host"] = host


def sanitize_marketing_context(
    action: str,
    context: object,
) -> dict[str, object]:
    """Return only bounded fields that are safe for first-party aggregation."""
    if action not in MARKETING_TRACK_ACTIONS or not isinstance(context, dict):
        return {}

    safe: dict[str, object] = {}
    _copy_page_fields(safe, context)
    _copy_acquisition_fields(safe, context)

    if action == "cta_clicked":
        for field in ("cta_name", "location", "source_surface"):
            value = _bounded_token(context.get(field))
            if value is not None:
                safe[field] = value
        destination_value = context.get("destination", context.get("target"))
        destination = _safe_destination(destination_value)
        if destination is not None:
            safe["destination"] = destination
        safe.update(_dashboard_handoff_metadata(destination_value))

    if action == "lead_capture_submit":
        source_context = _bounded_token(context.get("source_context"))
        if source_context is not None:
            safe["source_context"] = source_context

    return safe
