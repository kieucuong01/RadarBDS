from __future__ import annotations

from datetime import date
from typing import Any

from analytics.valuation import Listing, ValuationEngine
from config.property_types import PROPERTY_TYPE_LABELS, normalize_property_type
from db.connection import get_conn


class ValuationToolError(ValueError):
    pass


def _date_value(value) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _float(payload: dict[str, Any], key: str, *, min_value: float | None = None) -> float:
    try:
        value = float(payload.get(key))
    except (TypeError, ValueError):
        raise ValuationToolError(f"{key}_invalid")
    if min_value is not None and value < min_value:
        raise ValuationToolError(f"{key}_invalid")
    return value


def _optional_float(payload: dict[str, Any], key: str, *, min_value: float | None = None) -> float | None:
    raw = payload.get(key)
    if raw in (None, ""):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise ValuationToolError(f"{key}_invalid")
    if min_value is not None and value < min_value:
        raise ValuationToolError(f"{key}_invalid")
    return value


def _listing_from_row(row) -> Listing:
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
    )


def _load_training_listings(limit: int = 30000) -> list[Listing]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, title, description, area, ward, property_type, tx_type,
                   price_per_m2, price_ty, area_m2, frontage_m, depth_m,
                   road_type, road_tier, tho_cu_m2, tho_cu_ratio, has_so,
                   is_hot, price_dropped, crawled_at, posted_at, url, source,
                   duplicate_of_id
              FROM listings
             WHERE price_per_m2 IS NOT NULL AND price_per_m2 > 0
               AND price_ty IS NOT NULL AND price_ty > 0
               AND area_m2 IS NOT NULL AND area_m2 > 0
               AND COALESCE(probably_sold,0) = 0
               AND COALESCE(is_blacklisted,0) = 0
               AND COALESCE(review_hidden,0) = 0
             ORDER BY id DESC
             LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [_listing_from_row(row) for row in rows]


def _target_listing(payload: dict[str, Any]) -> Listing:
    ward = str(payload.get("ward") or "").strip()
    if not ward:
        raise ValuationToolError("ward_required")
    property_type = normalize_property_type(payload.get("property_type") or "dat_nen")
    if property_type not in PROPERTY_TYPE_LABELS:
        raise ValuationToolError("property_type_invalid")
    area_m2 = _float(payload, "area_m2", min_value=1)
    price_ty = _optional_float(payload, "price_ty", min_value=0.01)
    price_per_m2 = round(price_ty * 1000 / area_m2, 3) if price_ty else 0
    road_tier = int(_optional_float(payload, "road_tier", min_value=0) or 0)
    if road_tier > 4:
        raise ValuationToolError("road_tier_invalid")
    return Listing(
        id=0,
        area="Bình Dương",
        ward=ward,
        property_type=property_type,
        tx_type="ban",
        price_per_m2=price_per_m2,
        price_total=price_ty or 0,
        area_m2=area_m2,
        frontage_m=_optional_float(payload, "frontage_m", min_value=0.1),
        depth_m=_optional_float(payload, "depth_m", min_value=0.1),
        tho_cu_m2=_optional_float(payload, "tho_cu_m2", min_value=0),
        road_type=str(payload.get("road_type") or "unknown").strip()[:80] or "unknown",
        road_tier=road_tier,
        has_so=bool(payload.get("has_so", True)),
        source="user_tool",
    )


def _load_comparables(target: Listing, limit: int = 5) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, title, price_ty, price_per_m2, area_m2, frontage_m, depth_m,
                   road_tier, posted_at, crawled_at
              FROM listings
             WHERE ward = ?
               AND property_type = ?
               AND price_per_m2 IS NOT NULL AND price_per_m2 > 0
               AND area_m2 IS NOT NULL AND area_m2 > 0
               AND COALESCE(probably_sold,0) = 0
               AND COALESCE(is_blacklisted,0) = 0
               AND COALESCE(review_hidden,0) = 0
             ORDER BY ABS(COALESCE(area_m2, 0) - ?) ASC, id DESC
             LIMIT ?
            """,
            (target.ward, target.property_type, target.area_m2, limit),
        ).fetchall()
    return [
        {
            "id": row["id"],
            "title": row["title"],
            "price_ty": round(float(row["price_ty"] or 0), 2),
            "price_per_m2": round(float(row["price_per_m2"] or 0), 1),
            "area_m2": round(float(row["area_m2"] or 0), 1),
            "frontage_m": round(float(row["frontage_m"]), 1) if row["frontage_m"] else None,
            "depth_m": round(float(row["depth_m"]), 1) if row["depth_m"] else None,
            "road_tier": int(row["road_tier"] or 0),
            "date": row["posted_at"] or row["crawled_at"],
        }
        for row in rows
    ]


def estimate_property_value(payload: dict[str, Any]) -> dict[str, Any]:
    target = _target_listing(payload or {})
    training = _load_training_listings()
    engine = ValuationEngine()
    engine.fit(training)
    selection = engine._select_pricing_basis(target)
    if not selection:
        return {
            "ok": False,
            "error": "cannot_estimate",
            "message": "Chưa đủ dữ liệu so sánh cho khu vực hoặc loại hình này.",
        }
    model, base_ppm2, price_basis, basis_count = selection
    fair_ppm2 = model.predict_fair_ppm2(target, base_override=base_ppm2)
    if not fair_ppm2:
        return {
            "ok": False,
            "error": "cannot_estimate",
            "message": "Chưa đủ dữ liệu so sánh cho khu vực hoặc loại hình này.",
        }

    input_ppm2 = round(target.price_per_m2, 1) if target.price_per_m2 else None
    mos_pct = round((fair_ppm2 - target.price_per_m2) / fair_ppm2 * 100, 1) if input_ppm2 else None
    estimate = {
        "ward": target.ward,
        "property_type": target.property_type,
        "property_type_label": PROPERTY_TYPE_LABELS.get(target.property_type, target.property_type),
        "area_m2": round(target.area_m2, 1),
        "input_price_ty": round(target.price_total, 2) if target.price_total else None,
        "input_ppm2": input_ppm2,
        "fair_ppm2": round(fair_ppm2, 2),
        "fair_price_ty": round(fair_ppm2 * target.area_m2 / 1000, 2),
        "mos_pct": mos_pct,
        "confidence": model.confidence_level(),
        "segment_n": model.n_samples,
        "note": f"model=valuation_tool | basis={price_basis} | basis_n={basis_count}",
    }
    return {"ok": True, "estimate": estimate, "comparables": _load_comparables(target)}
