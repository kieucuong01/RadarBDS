"""Read-only tools for the deterministic RadarBDS assistant."""
from __future__ import annotations

from typing import Any

from config.property_types import normalize_property_types
from services.market_data import load_dashboard_summary, load_signals, load_trend_data


def _sources_for_tier(tier: str) -> list[str]:
    # Keep public assistant aligned with user-facing source policy.
    return ["facebook"] if tier != "admin" else ["facebook"]


def normalize_filter_draft(filter_draft: dict[str, Any] | None) -> dict[str, Any]:
    raw = filter_draft or {}
    wards = raw.get("ward") or raw.get("wards") or []
    prop_types = raw.get("property_type") or raw.get("prop_types") or []
    if isinstance(wards, str):
        wards = [wards]
    if isinstance(prop_types, str):
        prop_types = [prop_types]
    def as_bool(value: Any) -> bool:
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on", "co", "có"}
        return bool(value)

    def as_num(value: Any) -> float | None:
        if value in (None, ""):
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if number > 0 else None

    def as_mos(value: Any) -> int:
        try:
            number = int(float(value or 0))
        except (TypeError, ValueError):
            return 0
        return max(0, min(70, number))

    normalized = {
        "ward": [str(w).strip() for w in wards if str(w).strip()],
        "property_type": normalize_property_types(str(p).strip() for p in prop_types if str(p).strip()),
        "mos_min": as_mos(raw.get("mos_min")),
        "only_drops": as_bool(raw.get("only_drops")),
        "price_min": as_num(raw.get("price_min")),
        "price_max": as_num(raw.get("price_max")),
        "area_min": as_num(raw.get("area_min")),
        "area_max": as_num(raw.get("area_max")),
        "q": (raw.get("q") or raw.get("keyword") or "").strip() if isinstance(raw.get("q") or raw.get("keyword") or "", str) else "",
    }
    return normalized


def _range_num(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def get_deal_snapshot(filter_draft: dict[str, Any] | None, *, tier: str = "guest", limit: int = 5) -> dict[str, Any]:
    filt = normalize_filter_draft(filter_draft)
    try:
        payload = load_signals(
            None,
            sources=_sources_for_tier(tier),
            wards=filt["ward"],
            prop_types=filt["property_type"],
            only_drops=filt["only_drops"],
            mos_min=filt["mos_min"],
            price_min=_range_num(filt["price_min"]),
            price_max=_range_num(filt["price_max"]),
            area_min=_range_num(filt["area_min"]),
            area_max=_range_num(filt["area_max"]),
            keyword=filt["q"],
            tier=tier,
            limit=limit,
            include_total=True,
            sort="score_desc",
        )
    except Exception:
        return {"total": 0, "signals": [], "error": "signals_unavailable"}
    return {
        "total": payload.get("total", len(payload.get("signals") or [])),
        "signals": payload.get("signals") or [],
    }


def get_market_snapshot(filter_draft: dict[str, Any] | None, *, tier: str = "guest") -> dict[str, Any]:
    filt = normalize_filter_draft(filter_draft)
    try:
        dashboard = load_dashboard_summary(
            None,
            sources=_sources_for_tier(tier),
            wards=filt["ward"],
            prop_types=filt["property_type"],
            only_drops=filt["only_drops"],
            mos_min=filt["mos_min"],
            price_min=_range_num(filt["price_min"]),
            price_max=_range_num(filt["price_max"]),
            area_min=_range_num(filt["area_min"]),
            area_max=_range_num(filt["area_max"]),
            keyword=filt["q"],
            tier=tier,
            include_trend=False,
        )
    except Exception:
        return {"stats": {}, "market": {}, "error": "dashboard_unavailable"}
    return {
        "stats": dashboard.get("stats") or {},
        "market": dashboard.get("market") or {},
        "all_wards": dashboard.get("all_wards") or [],
    }


def get_trend_snapshot(filter_draft: dict[str, Any] | None, *, tier: str = "guest") -> dict[str, Any]:
    filt = normalize_filter_draft(filter_draft)
    try:
        trend = load_trend_data(
            None,
            sources=_sources_for_tier(tier),
            wards=filt["ward"],
            prop_types=filt["property_type"],
            only_drops=filt["only_drops"],
            price_min=_range_num(filt["price_min"]),
            price_max=_range_num(filt["price_max"]),
            area_min=_range_num(filt["area_min"]),
            area_max=_range_num(filt["area_max"]),
            keyword=filt["q"],
        )
    except Exception:
        return {"trend": {}, "error": "trend_unavailable"}
    return {"trend": trend or {}}


def summarize_signal_cards(signals: list[dict[str, Any]], limit: int = 3) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for item in (signals or [])[:limit]:
        cards.append({
            "type": "deal",
            "listing_id": item.get("id"),
            "title": item.get("title"),
            "ward": item.get("ward"),
            "price_ty": item.get("price_ty"),
            "mos_pct": item.get("mos_pct_display", item.get("mos_pct")),
            "road_label": item.get("road_label"),
            "price_dropped": bool(item.get("price_dropped")),
        })
    return cards
