from __future__ import annotations

from typing import Any


AGENT_SCHEMA_VERSION = "1.0"
AGENT_CACHE_CONTROL = (
    "public, max-age=300, stale-while-revalidate=86400"
)


def _base_url(value: str) -> str:
    return str(value or "").strip().rstrip("/")


def _guest_rules() -> dict[str, object]:
    return {
        "effective_mos_min": 15,
        "mos_min_override": "ignored",
        "only_drops": "ignored",
    }


def build_agent_site_manifest(*, base_url: str) -> dict[str, Any]:
    base = _base_url(base_url)
    return {
        "schema_version": AGENT_SCHEMA_VERSION,
        "site": {
            "name": "Radar BDS",
            "url": base,
            "language": "vi-VN",
            "description": (
                "Radar BDS chuẩn hóa tin rao bất động sản Bình Dương và "
                "cung cấp signal công khai để sàng lọc trước khi người dùng "
                "tự thẩm định."
            ),
        },
        "markets": {
            "country": "VN",
            "province": "Bình Dương",
            "primary": ["Thủ Dầu Một", "Bến Cát"],
            "sources": ["facebook", "guland"],
        },
        "capabilities": [
            {
                "id": "find_signals",
                "method": "GET",
                "url": f"{base}/api/signals",
            },
            {
                "id": "count_signals",
                "method": "GET",
                "url": f"{base}/api/counts",
            },
        ],
        "not_supported": [
            "authentication",
            "favorites",
            "lead_submission",
            "phone_numbers",
            "original_listing_urls",
            "saved_searches",
            "watchlists",
            "write_actions",
        ],
        "discovery": {
            "openapi": f"{base}/agent/openapi.json",
            "llms": f"{base}/llms.txt",
            "robots": f"{base}/robots.txt",
            "sitemap": f"{base}/sitemap.xml",
        },
        "usage": {
            "recommended_flow": [
                "Translate the user's need into public filters.",
                (
                    "Call /api/signals with include_total=0 and limit no "
                    "greater than 30."
                ),
                "Compare only fields returned in the same response.",
                (
                    "Explain that a signal is a screening aid, not a "
                    "purchase recommendation."
                ),
                "Send the user to detail_href for verification and next steps.",
            ],
            "recommended_query": {
                "include_total": 0,
                "limit": 30,
                "sort": "score_desc",
            },
            "guest_rules": _guest_rules(),
        },
        "freshness": {
            "dataset_header": "X-Radar-Dataset-Version",
            "cache_header": "X-Radar-Public-Cache",
            "record_dates": ["card_date_reason", "days_ago"],
        },
        "citation": {
            "canonical_link_field": "detail_href",
            "recommended_fields": [
                "title",
                "ward",
                "price_label",
                "area_m2",
                "mos_pct",
                "signal_score",
                "detail_href",
            ],
        },
        "limitations": [
            "Signals are screening aids, not purchase recommendations.",
            (
                "Listing data can be incomplete, stale, duplicated, or "
                "changed by the publisher."
            ),
            (
                "Users must independently verify location, planning, legal "
                "status, dimensions, and price."
            ),
        ],
    }


def _parameter(
    name: str,
    schema: dict[str, Any],
    description: str,
    *,
    repeated: bool = False,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "name": name,
        "in": "query",
        "required": False,
        "description": description,
        "schema": schema,
    }
    if repeated:
        result["style"] = "form"
        result["explode"] = True
    return result


def _filter_parameters() -> list[dict[str, Any]]:
    return [
        _parameter(
            "city",
            {"type": "string"},
            "City name; defaults to Thủ Dầu Một.",
        ),
        _parameter(
            "ward",
            {"type": "array", "items": {"type": "string"}},
            "Repeat to select wards.",
            repeated=True,
        ),
        _parameter(
            "source",
            {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": ["facebook", "guland"],
                },
            },
            "Repeat to select public sources.",
            repeated=True,
        ),
        _parameter(
            "prop_type",
            {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": [
                        "dat_nen",
                        "nha_dat",
                        "chung_cu",
                        "nha_tro",
                    ],
                },
            },
            "Repeat to select property types.",
            repeated=True,
        ),
        _parameter(
            "area_min",
            {"type": "number", "minimum": 0},
            "Minimum lot area in square metres.",
        ),
        _parameter(
            "area_max",
            {"type": "number", "minimum": 0},
            "Maximum lot area in square metres.",
        ),
        _parameter(
            "price_min",
            {"type": "number", "minimum": 0},
            "Minimum listing price in billion VND.",
        ),
        _parameter(
            "price_max",
            {"type": "number", "minimum": 0},
            "Maximum listing price in billion VND.",
        ),
        _parameter(
            "q",
            {"type": "string"},
            "Bounded public keyword search.",
        ),
        _parameter(
            "date_range",
            {
                "type": "string",
                "enum": ["1w", "1m", "3m", "6m", "1y", "all"],
            },
            "Listing activity window.",
        ),
    ]


def build_agent_openapi_document(*, base_url: str) -> dict[str, Any]:
    base = _base_url(base_url)
    signal_parameters = _filter_parameters() + [
        _parameter(
            "page",
            {
                "type": "integer",
                "minimum": 1,
                "maximum": 2000,
                "default": 1,
            },
            "Result page.",
        ),
        _parameter(
            "limit",
            {
                "type": "integer",
                "minimum": 1,
                "maximum": 100,
                "default": 30,
            },
            "Page size; agents should use at most 30.",
        ),
        _parameter(
            "sort",
            {
                "type": "string",
                "enum": [
                    "newest",
                    "price_m2_asc",
                    "price_asc",
                    "mos_desc",
                    "score_desc",
                ],
                "default": "newest",
            },
            "Signal ordering.",
        ),
        _parameter(
            "include_total",
            {"type": "integer", "enum": [0, 1], "default": 1},
            (
                "Use 0 for the first agent query; call /api/counts "
                "separately when a count is needed."
            ),
        ),
    ]
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Radar BDS Read-only Agent API",
            "version": AGENT_SCHEMA_VERSION,
            "description": (
                "Guest-safe signal discovery. No authentication or write "
                "actions are supported."
            ),
        },
        "servers": [{"url": base}],
        "tags": [
            {
                "name": "signals",
                "description": (
                    "Public, redacted Bình Dương signal discovery."
                ),
            }
        ],
        "paths": {
            "/api/signals": {
                "get": {
                    "operationId": "findSignals",
                    "summary": "Find public actionable signals",
                    "tags": ["signals"],
                    "parameters": signal_parameters,
                    "x-radar-guest-rules": _guest_rules(),
                    "responses": {
                        "200": {
                            "description": (
                                "Paginated, redacted public signal cards."
                            ),
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "$ref": (
                                            "#/components/schemas/SignalPage"
                                        )
                                    }
                                }
                            },
                        },
                        "503": {
                            "description": (
                                "Temporary public-read backpressure; retry "
                                "with bounded exponential backoff."
                            )
                        },
                    },
                }
            },
            "/api/counts": {
                "get": {
                    "operationId": "countSignals",
                    "summary": (
                        "Count signals for the current public filters"
                    ),
                    "tags": ["signals"],
                    "parameters": _filter_parameters(),
                    "x-radar-guest-rules": _guest_rules(),
                    "responses": {
                        "200": {
                            "description": "Public filtered counters.",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "$ref": (
                                            "#/components/schemas/CountSummary"
                                        )
                                    }
                                }
                            },
                        },
                        "503": {
                            "description": (
                                "Temporary public-read backpressure; retry "
                                "with bounded exponential backoff."
                            )
                        },
                    },
                }
            },
        },
        "components": {
            "schemas": {
                "SignalCard": {
                    "type": "object",
                    "required": ["id", "detail_href", "title", "ward"],
                    "properties": {
                        "id": {"type": "integer"},
                        "detail_href": {
                            "type": "string",
                            "description": "Canonical public handoff path.",
                        },
                        "title": {"type": "string"},
                        "ward": {"type": "string"},
                        "price_ty": {"type": ["number", "null"]},
                        "price_label": {"type": ["string", "null"]},
                        "area_m2": {"type": ["number", "null"]},
                        "actual_ppm2": {"type": ["number", "null"]},
                        "fair_ppm2": {"type": ["number", "null"]},
                        "mos_pct": {"type": ["number", "null"]},
                        "signal_score": {"type": ["number", "null"]},
                        "source": {"type": ["string", "null"]},
                        "days_ago": {"type": ["integer", "null"]},
                        "card_date_reason": {
                            "type": ["string", "null"]
                        },
                    },
                    "additionalProperties": True,
                },
                "SignalPage": {
                    "type": "object",
                    "properties": {
                        "signals": {
                            "type": "array",
                            "items": {
                                "$ref": "#/components/schemas/SignalCard"
                            },
                        },
                        "page": {"type": "integer"},
                        "limit": {"type": "integer"},
                        "total": {"type": ["integer", "null"]},
                    },
                    "additionalProperties": True,
                },
                "CountSummary": {
                    "type": "object",
                    "additionalProperties": True,
                },
            }
        },
    }
