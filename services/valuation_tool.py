from __future__ import annotations

import logging
from datetime import date
from math import isfinite
from threading import RLock
from typing import Any
from urllib.parse import quote, urlencode

from analytics.valuation import Listing, ValuationEngine
from config.property_types import PROPERTY_TYPE_LABELS, normalize_property_type
from db.connection import get_conn
from services.market_data import CITY_MAP, redact_for_tier
from services.signal_quality import split_quality_flags


logger = logging.getLogger(__name__)

VALUATION_TOOL_CITY_MAP = {
    city: tuple(wards)
    for city, wards in CITY_MAP.items()
    if city in {"THỦ DẦU MỘT", "BẾN CÁT"}
}
CONFIDENCE_LABELS = {
    "high": "Tin cậy cao",
    "medium": "Tin cậy vừa",
    "low": "Tin cậy thấp",
}
BASELINE_EXCLUDE_QUALITY_FLAGS = frozenset({
    "approximate_price_text",
    "ambiguous_price_text",
    "too_low_absolute_price",
    "missing_area_evidence",
    "source_category_conflict",
    "multi_lot_listing",
    "area_dimension_conflict",
    "suspicious_bait",
    "extreme_guland_ppm2",
    "review_bad_valuation",
    "review_bad_extraction",
    "guland_cluster_flood",
})

_MODEL_CACHE_LOCK = RLock()
_MODEL_CACHE: dict[str, Any] = {
    "version": None,
    "data_as_of": None,
    "engine": None,
}


class ValuationToolError(ValueError):
    pass


def _row_value(row, key: str, default=None):
    try:
        value = row[key]
    except (KeyError, IndexError, TypeError):
        return default
    return default if value is None else value


def _date_value(value) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _date_string(value) -> str | None:
    parsed = _date_value(value)
    return parsed.isoformat() if parsed else None


def _baseline_quality_flags(value) -> tuple[str, ...]:
    return tuple(sorted(split_quality_flags(value) & BASELINE_EXCLUDE_QUALITY_FLAGS))


def _float(
    payload: dict[str, Any],
    key: str,
    *,
    min_value: float | None = None,
    max_value: float | None = None,
) -> float:
    try:
        value = float(payload.get(key))
    except (TypeError, ValueError):
        raise ValuationToolError(f"{key}_invalid")
    if not isfinite(value):
        raise ValuationToolError(f"{key}_invalid")
    if min_value is not None and value < min_value:
        raise ValuationToolError(f"{key}_invalid")
    if max_value is not None and value > max_value:
        raise ValuationToolError(f"{key}_invalid")
    return value


def _optional_float(
    payload: dict[str, Any],
    key: str,
    *,
    min_value: float | None = None,
    max_value: float | None = None,
) -> float | None:
    raw = payload.get(key)
    if raw in (None, ""):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise ValuationToolError(f"{key}_invalid")
    if not isfinite(value):
        raise ValuationToolError(f"{key}_invalid")
    if min_value is not None and value < min_value:
        raise ValuationToolError(f"{key}_invalid")
    if max_value is not None and value > max_value:
        raise ValuationToolError(f"{key}_invalid")
    return value


def _listing_from_row(row) -> Listing:
    quality_flags = _baseline_quality_flags(_row_value(row, "source_quality_flags", ""))
    return Listing(
        id=int(row["id"]),
        area=row["area"] or "Bình Dương",
        ward=row["ward"] or "unknown",
        property_type=normalize_property_type(row["property_type"] or "dat_nen"),
        tx_type=(row["tx_type"] or "ban").strip().lower().replace("bán", "ban").replace("thuê", "thue"),
        price_per_m2=float(row["price_per_m2"]),
        price_total=float(row["price_ty"] or 0),
        area_m2=float(row["area_m2"] or 0),
        frontage_m=float(row["frontage_m"]) if row["frontage_m"] else None,
        depth_m=float(row["depth_m"]) if row["depth_m"] else None,
        tho_cu_m2=float(row["tho_cu_m2"]) if row["tho_cu_m2"] else None,
        tho_cu_ratio=float(row["tho_cu_ratio"]) if row["tho_cu_ratio"] else None,
        road_type=row["road_type"] or "unknown",
        road_tier=int(row["road_tier"] or 0),
        has_so=bool(row["has_so"]),
        is_hot=bool(row["is_hot"]),
        price_dropped=bool(row["price_dropped"]),
        crawled_at=_date_value(row["crawled_at"]),
        posted_at=_date_value(row["posted_at"]),
        url=row["url"] or "",
        contact_phone="",
        title=row["title"] or "",
        description=row["description"] or "",
        source=row["source"] or "",
        duplicate_of_id=int(row["duplicate_of_id"]) if row["duplicate_of_id"] else None,
        source_quality_flags=quality_flags,
        exclude_from_baseline=bool(quality_flags),
    )


def _training_snapshot_version() -> tuple[str, str | None]:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT COALESCE(MAX(id), 0) AS max_listing_id,
                   COUNT(*) AS listing_count,
                   MAX(COALESCE(posted_at, crawled_at)) AS data_as_of,
                   MAX(updated_at) AS max_updated_at,
                   COALESCE((SELECT MAX(id) FROM valuation_results), 0) AS max_valuation_id
              FROM listings
             WHERE price_per_m2 IS NOT NULL AND price_per_m2 > 0
               AND price_ty IS NOT NULL AND price_ty > 0
               AND area_m2 IS NOT NULL AND area_m2 > 0
               AND COALESCE(probably_sold,0) = 0
               AND COALESCE(is_blacklisted,0) = 0
               AND COALESCE(review_hidden,0) = 0
            """
        ).fetchone()
    version = ":".join(
        str(_row_value(row, key, 0))
        for key in ("max_listing_id", "listing_count", "max_updated_at", "max_valuation_id")
    )
    return version, _date_string(_row_value(row, "data_as_of"))


def _load_training_listings(limit: int = 30000) -> list[Listing]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            WITH latest_quality AS (
                SELECT listing_id, source_quality_flags, source_quality_recheck,
                       ROW_NUMBER() OVER (
                           PARTITION BY listing_id
                           ORDER BY computed_at DESC, id DESC
                       ) AS quality_rank
                  FROM valuation_results
            )
            SELECT l.id, l.title, l.description, l.area, l.ward, l.property_type, l.tx_type,
                   l.price_per_m2, l.price_ty, l.area_m2, l.frontage_m, l.depth_m,
                   l.road_type, l.road_tier, l.tho_cu_m2, l.tho_cu_ratio, l.has_so,
                   l.is_hot, l.price_dropped, l.crawled_at, l.posted_at, l.url, l.source,
                   l.duplicate_of_id, q.source_quality_flags, q.source_quality_recheck
              FROM listings l
              LEFT JOIN latest_quality q
                ON q.listing_id = l.id AND q.quality_rank = 1
             WHERE l.price_per_m2 IS NOT NULL AND l.price_per_m2 > 0
               AND l.price_ty IS NOT NULL AND l.price_ty > 0
               AND l.area_m2 IS NOT NULL AND l.area_m2 > 0
               AND COALESCE(l.probably_sold,0) = 0
               AND COALESCE(l.is_blacklisted,0) = 0
               AND COALESCE(l.review_hidden,0) = 0
             ORDER BY l.id DESC
             LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [_listing_from_row(row) for row in rows]


def _reset_model_cache_for_tests() -> None:
    with _MODEL_CACHE_LOCK:
        _MODEL_CACHE.update(version=None, data_as_of=None, engine=None)


def _get_cached_engine() -> tuple[ValuationEngine, str | None]:
    with _MODEL_CACHE_LOCK:
        version, data_as_of = _training_snapshot_version()
        if _MODEL_CACHE["engine"] is not None and _MODEL_CACHE["version"] == version:
            return _MODEL_CACHE["engine"], _MODEL_CACHE["data_as_of"]

        try:
            training = _load_training_listings()
            engine = ValuationEngine()
            engine.fit(training)
        except Exception:
            if _MODEL_CACHE["engine"] is not None:
                logger.exception("Valuation tool model refresh failed; serving last good model")
                return _MODEL_CACHE["engine"], _MODEL_CACHE["data_as_of"]
            raise

        _MODEL_CACHE.update(version=version, data_as_of=data_as_of, engine=engine)
        return engine, data_as_of


def _normalize_city_and_ward(payload: dict[str, Any]) -> tuple[str, str]:
    city = str(payload.get("city") or "").strip().upper()
    ward = str(payload.get("ward") or "").strip()
    if not ward:
        raise ValuationToolError("ward_required")

    if not city:
        city = next(
            (candidate for candidate, wards in VALUATION_TOOL_CITY_MAP.items() if ward in wards),
            "",
        )
    if city not in VALUATION_TOOL_CITY_MAP:
        raise ValuationToolError("city_invalid")
    if ward not in VALUATION_TOOL_CITY_MAP[city]:
        raise ValuationToolError("ward_invalid")
    return city, ward


def _target_listing(payload: dict[str, Any]) -> Listing:
    city, ward = _normalize_city_and_ward(payload)
    property_type = normalize_property_type(payload.get("property_type") or "dat_nen")
    if property_type not in PROPERTY_TYPE_LABELS:
        raise ValuationToolError("property_type_invalid")
    area_m2 = _float(payload, "area_m2", min_value=1, max_value=1_000_000)
    price_ty = _optional_float(payload, "price_ty", min_value=0.01, max_value=100_000)
    price_per_m2 = round(price_ty * 1000 / area_m2, 3) if price_ty else 0
    road_tier_value = _optional_float(payload, "road_tier", min_value=0, max_value=4) or 0
    if not road_tier_value.is_integer():
        raise ValuationToolError("road_tier_invalid")
    road_tier = int(road_tier_value)
    target = Listing(
        id=0,
        area="Bình Dương",
        ward=ward,
        property_type=property_type,
        tx_type="ban",
        price_per_m2=price_per_m2,
        price_total=price_ty or 0,
        area_m2=area_m2,
        frontage_m=_optional_float(payload, "frontage_m", min_value=0.1, max_value=10_000),
        depth_m=_optional_float(payload, "depth_m", min_value=0.1, max_value=10_000),
        tho_cu_m2=None,
        road_type=str(payload.get("road_type") or "unknown").strip()[:80] or "unknown",
        road_tier=road_tier,
        has_so=bool(payload.get("has_so", True)),
        source="user_tool",
    )
    target.city = city
    return target


def _load_comparables(target: Listing, limit: int = 5) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            WITH latest_quality AS (
                SELECT listing_id, source_quality_flags, source_quality_recheck,
                       ROW_NUMBER() OVER (
                           PARTITION BY listing_id
                           ORDER BY computed_at DESC, id DESC
                       ) AS quality_rank
                  FROM valuation_results
            )
            SELECT l.id, l.title, l.description, l.url, l.contact_phone, l.seller_name,
                   l.price_ty, l.price_per_m2, l.area_m2, l.frontage_m, l.depth_m,
                   l.road_tier, l.posted_at, l.crawled_at,
                   q.source_quality_flags
              FROM listings l
              LEFT JOIN latest_quality q
                ON q.listing_id = l.id AND q.quality_rank = 1
             WHERE l.ward = ?
               AND l.property_type = ?
               AND l.duplicate_of_id IS NULL
               AND l.price_per_m2 IS NOT NULL AND l.price_per_m2 > 0
               AND l.area_m2 IS NOT NULL AND l.area_m2 > 0
               AND COALESCE(l.probably_sold,0) = 0
               AND COALESCE(l.is_blacklisted,0) = 0
               AND COALESCE(l.review_hidden,0) = 0
             ORDER BY CASE WHEN COALESCE(l.road_tier,0) = ? THEN 0 ELSE 1 END ASC,
                      ABS(COALESCE(l.area_m2, 0) - ?) ASC,
                      COALESCE(l.posted_at, l.crawled_at) DESC,
                      l.id DESC
             LIMIT ?
            """,
            (target.ward, target.property_type, target.road_tier, target.area_m2, max(limit * 5, limit)),
        ).fetchall()
    candidates = [
        {
            "id": row["id"],
            "title": row["title"],
            "description": row["description"],
            "url": row["url"],
            "contact_phone": row["contact_phone"],
            "seller_name": row["seller_name"],
            "price_ty": round(float(row["price_ty"] or 0), 2),
            "price_per_m2": round(float(row["price_per_m2"] or 0), 1),
            "area_m2": round(float(row["area_m2"] or 0), 1),
            "frontage_m": round(float(row["frontage_m"]), 1) if row["frontage_m"] else None,
            "depth_m": round(float(row["depth_m"]), 1) if row["depth_m"] else None,
            "road_tier": int(row["road_tier"] or 0),
            "date": _date_string(row["posted_at"] or row["crawled_at"]),
        }
        for row in rows
        if not _baseline_quality_flags(_row_value(row, "source_quality_flags", ""))
    ]
    return candidates[:limit]


def _dashboard_url(target: Listing) -> str:
    query = urlencode(
        {
            "tab": "signals",
            "city": target.city,
            "ward": target.ward,
            "prop_type": target.property_type,
            "date_range": "all",
            "mos_min": 0,
        },
        quote_via=quote,
    )
    return f"/?{query}"


def _price_position_label(mos_pct: float | None) -> str | None:
    if mos_pct is None:
        return None
    if mos_pct >= 10:
        return "Thấp hơn giá tham khảo"
    if mos_pct <= -10:
        return "Cao hơn giá tham khảo"
    return "Gần giá tham khảo"


def estimate_property_value(payload: dict[str, Any], *, tier: str = "guest") -> dict[str, Any]:
    target = _target_listing(payload or {})
    engine, data_as_of = _get_cached_engine()
    selection = engine._select_pricing_basis(target)
    if not selection:
        return {
            "ok": False,
            "error": "cannot_estimate",
            "message": "Chưa đủ dữ liệu so sánh hợp lệ cho khu vực hoặc loại hình này.",
        }
    model, base_ppm2, _price_basis, basis_count = selection
    fair_ppm2 = model.predict_fair_ppm2(target, base_override=base_ppm2)
    if not fair_ppm2:
        return {
            "ok": False,
            "error": "cannot_estimate",
            "message": "Chưa đủ dữ liệu so sánh hợp lệ cho khu vực hoặc loại hình này.",
        }

    input_ppm2 = round(target.price_per_m2, 1) if target.price_per_m2 else None
    mos_pct = round((fair_ppm2 - target.price_per_m2) / fair_ppm2 * 100, 1) if input_ppm2 else None
    confidence = model.confidence_level()
    dashboard_url = _dashboard_url(target)
    estimate = {
        "city": target.city,
        "ward": target.ward,
        "property_type": target.property_type,
        "property_type_label": PROPERTY_TYPE_LABELS.get(target.property_type, target.property_type),
        "area_m2": round(target.area_m2, 1),
        "input_price_ty": round(target.price_total, 2) if target.price_total else None,
        "input_ppm2": input_ppm2,
        "fair_ppm2": round(fair_ppm2, 2),
        "fair_price_ty": round(fair_ppm2 * target.area_m2 / 1000, 2),
        "mos_pct": mos_pct,
        "price_position_label": _price_position_label(mos_pct),
        "confidence": confidence,
        "confidence_label": CONFIDENCE_LABELS.get(confidence, "Tin cậy thấp"),
        "basis_count": int(basis_count),
        "data_as_of": data_as_of,
    }

    comparables_locked = tier not in {"free", "vip", "admin"}
    comparables = []
    if not comparables_locked:
        comparables = [
            redact_for_tier(item, tier)
            for item in _load_comparables(target, limit=5)
        ]

    return {
        "ok": True,
        "estimate": estimate,
        "comparables": comparables,
        "comparables_locked": comparables_locked,
        "dashboard_url": dashboard_url,
    }
