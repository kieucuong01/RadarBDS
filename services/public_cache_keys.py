"""Deterministic, tier-safe keys for public response caches.

Callers must pass parsed and bounded values. Raw query strings, cookies, and
client-only parameters intentionally never cross this boundary.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

ALLOWED_QUERY_FIELDS = frozenset(
    {
        "active_city",
        "wards",
        "sources",
        "prop_types",
        "only_drops",
        "trend_period",
        "mos_min",
        "area_min",
        "area_max",
        "price_min",
        "price_max",
        "area_ranges",
        "price_ranges",
        "keyword",
        "date_range",
        "include_trend",
        "include_guland_high_activity",
        "sort",
        "page",
        "limit",
        "include_total",
    }
)
MULTI_VALUE_FIELDS = frozenset(
    {"wards", "sources", "prop_types", "area_ranges", "price_ranges"}
)
VALID_TIERS = frozenset({"guest", "free", "vip", "admin"})
VALID_ENDPOINTS = frozenset({"signals", "counts", "dashboard"})


def _scalar(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return float(format(value, ".12g"))
    return str(value).strip()


def canonical_query(query: Mapping[str, object]) -> dict[str, object]:
    """Return stable response-changing query state and discard unknown fields."""
    normalized: dict[str, object] = {}
    for key in sorted(ALLOWED_QUERY_FIELDS):
        if key not in query or query[key] is None:
            continue
        value = query[key]
        if key in MULTI_VALUE_FIELDS:
            items = (
                value
                if isinstance(value, (list, tuple, set, frozenset))
                else (value,)
            )
            normalized[key] = sorted(
                {_scalar(item) for item in items if str(item).strip()}
            )
        else:
            normalized[key] = _scalar(value)
    return normalized


def build_public_cache_key(
    *,
    endpoint: str,
    tier: str,
    versions: Mapping[str, int],
    query: Mapping[str, object],
    schema_version: int = 1,
) -> str:
    """Hash canonical query state into a versioned Redis namespace key."""
    if endpoint not in VALID_ENDPOINTS or tier not in VALID_TIERS:
        raise ValueError("invalid public cache namespace")
    version_tuple = ",".join(
        f"{name}={int(versions[name])}" for name in sorted(versions)
    )
    body = json.dumps(
        canonical_query(query),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    digest = hashlib.sha256(body).hexdigest()
    return (
        f"radar:public:v{int(schema_version)}:{endpoint}:{tier}:"
        f"{version_tuple}:{digest}"
    )
