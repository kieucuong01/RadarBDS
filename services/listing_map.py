"""Compact grouped read model for listing map surfaces."""
from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass, replace
import threading
import time

from config.listing_map import LISTING_MAP_RESOLVER_VERSION
from config.property_types import PROPERTY_TYPE_LABELS, normalize_property_types
from db.connection import get_conn
from services.market_data import (
    DEFAULT_VISIBLE_SOURCES,
    LATEST_SHADOW_VALUATION_CTE,
    _days_ago,
    _signal_listing_data_sql,
    build_deal_sql,
    build_listing_filters,
    listing_activity_at_sql,
    listing_card_activity,
    normalize_sources_for_tier,
    resolve_image_url,
)
from services.signal_quality import LATEST_VALUATION_CTE


MAP_CACHE_TTL_SECONDS = 60
MAP_CACHE_MAX_ENTRIES = 128
_ALLOWED_LOCATION_RELATIONS = frozenset({"", "on", "at", "near", "alley"})
_cache: OrderedDict[tuple, tuple[float, dict]] = OrderedDict()
_cache_lock = threading.Lock()


@dataclass(frozen=True)
class MapFilters:
    city: str = ""
    wards: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()
    prop_types: tuple[str, ...] = ()
    only_drops: bool = False
    mos_min: int = 10
    area_min: float = 0
    area_max: float = 0
    price_min: float = 0
    price_max: float = 0
    area_ranges: tuple[tuple[float, float], ...] = ()
    price_ranges: tuple[tuple[float, float], ...] = ()
    keyword: str = ""
    date_range: str = "3m"
    complete_only: bool = False


def clear_listing_map_cache() -> None:
    with _cache_lock:
        _cache.clear()


def _row_value(row, key, default=None):
    if row is None:
        return default
    try:
        value = row[key]
    except (KeyError, IndexError, TypeError):
        try:
            value = row.get(key, default)
        except AttributeError:
            return default
    return default if value is None else value


def _normalized_filters(filters: MapFilters, tier: str) -> MapFilters:
    sources = tuple(
        normalize_sources_for_tier(filters.sources, tier)
        if tier != "admin"
        else (filters.sources or DEFAULT_VISIBLE_SOURCES)
    )
    return replace(
        filters,
        wards=tuple(dict.fromkeys(filters.wards)),
        sources=sources,
        prop_types=tuple(normalize_property_types(filters.prop_types)),
        only_drops=False if tier == "guest" else bool(filters.only_drops),
        mos_min=10 if tier == "guest" else int(filters.mos_min or 0),
        area_ranges=tuple(tuple(item) for item in filters.area_ranges),
        price_ranges=tuple(tuple(item) for item in filters.price_ranges),
    )


def get_listing_map_data_version(conn) -> str:
    """Return a cross-process invalidation fingerprint from source timestamps."""
    row = conn.execute(
        """
        SELECT GREATEST(
            COALESCE((
                SELECT MAX(GREATEST(
                    COALESCE(NULLIF(updated_at, '')::timestamptz, 'epoch'),
                    COALESCE(NULLIF(review_hidden_at, '')::timestamptz, 'epoch')
                ))
                FROM listings
            ), 'epoch'),
            COALESCE((
                SELECT MAX(NULLIF(computed_at, '')::timestamptz)
                FROM valuation_results
            ), 'epoch'),
            COALESCE((
                SELECT MAX(NULLIF(computed_at, '')::timestamptz)
                FROM valuation_shadow_results
            ), 'epoch'),
            COALESCE((
                SELECT MAX(updated_at)
                FROM listing_map_locations
            ), 'epoch')
        )::text AS data_version
        """
    ).fetchone()
    return str(_row_value(row, "data_version", "epoch"))


def _cache_get(key: tuple) -> dict | None:
    now = time.monotonic()
    with _cache_lock:
        entry = _cache.get(key)
        if entry is None:
            return None
        expires_at, payload = entry
        if expires_at <= now:
            _cache.pop(key, None)
            return None
        _cache.move_to_end(key)
        return deepcopy(payload)


def _cache_put(key: tuple, payload: dict) -> dict:
    with _cache_lock:
        _cache[key] = (
            time.monotonic() + MAP_CACHE_TTL_SECONDS,
            deepcopy(payload),
        )
        _cache.move_to_end(key)
        while len(_cache) > MAP_CACHE_MAX_ENTRIES:
            _cache.popitem(last=False)
    return deepcopy(payload)


def _filtered_sql(mode: str, filters: MapFilters) -> tuple[str, list]:
    where_sql, params = build_listing_filters(
        sources=list(filters.sources),
        wards=list(filters.wards),
        prop_types=list(filters.prop_types),
        only_drops=filters.only_drops,
        prefix="l.",
        area_min=filters.area_min,
        area_max=filters.area_max,
        price_min=filters.price_min,
        price_max=filters.price_max,
        area_ranges=filters.area_ranges,
        price_ranges=filters.price_ranges,
        keyword=filters.keyword,
        date_range=filters.date_range,
        require_complete=filters.complete_only if mode == "all" else False,
    )
    deal = build_deal_sql(filters.mos_min)
    mode_condition = ""
    if mode == "signals":
        mode_condition = (
            f" AND ({deal.condition})"
            f" AND {_signal_listing_data_sql('l')}"
        )
    return (
        f"""
        SELECT l.id,
               l.title,
               l.price_ty,
               l.area_m2,
               l.property_type,
               l.ward,
               l.road_name,
               l.posted_at,
               l.crawled_at,
               l.first_seen_at,
               l.price_updated_at,
               {listing_activity_at_sql('l')} AS activity_at,
               l.source,
               ({deal.mos_expr}) AS mos_pct,
               CASE WHEN ({deal.condition}) THEN 1 ELSE 0 END AS is_signal
        FROM listings l
        LEFT JOIN latest_valuation v ON v.listing_id = l.id
        LEFT JOIN latest_shadow_valuation sv ON sv.listing_id = l.id
        WHERE {where_sql}{mode_condition}
        """,
        params,
    )


def _base_cte(filtered_sql: str) -> str:
    return f"""
        WITH {LATEST_VALUATION_CTE},
             {LATEST_SHADOW_VALUATION_CTE},
             filtered AS MATERIALIZED (
                 {filtered_sql}
             )
    """


def load_listing_map_summary(
    *,
    mode: str,
    tier: str,
    filters: MapFilters,
) -> dict:
    if mode not in {"signals", "all"}:
        raise ValueError("invalid map mode")
    filters = _normalized_filters(filters, tier)
    filtered_sql, params = _filtered_sql(mode, filters)

    with get_conn() as conn:
        data_version = get_listing_map_data_version(conn)
        cache_key = (
            "summary",
            tier,
            mode,
            filters,
            LISTING_MAP_RESOLVER_VERSION,
            data_version,
        )
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached

        rows = conn.execute(
            _base_cte(filtered_sql)
            + f"""
            SELECT ml.location_key,
                   ml.lat,
                   ml.lng,
                   ml.location_precision,
                   ml.location_label,
                   ml.accuracy_radius_m,
                   ''::TEXT AS relation,
                   COUNT(*)::INTEGER AS listing_count,
                   MAX(f.mos_pct) AS best_mos,
                   SUM(COUNT(*)) OVER()::INTEGER AS total_count,
                   COALESCE(
                       SUM(COUNT(ml.listing_id)) OVER(),
                       0
                   )::INTEGER AS mapped_count,
                   COALESCE(
                       SUM(COUNT(*)) FILTER (
                           WHERE ml.location_precision = 'exact'
                       ) OVER(),
                       0
                   )::INTEGER AS exact_count,
                   COALESCE(
                       SUM(COUNT(*)) FILTER (
                           WHERE ml.location_precision = 'road'
                       ) OVER(),
                       0
                   )::INTEGER AS road_count,
                   COALESCE(
                       SUM(COUNT(*)) FILTER (
                           WHERE ml.location_precision = 'landmark'
                       ) OVER(),
                       0
                   )::INTEGER AS landmark_count,
                   0::INTEGER AS nearby_count,
                   COALESCE(
                       SUM(COUNT(*)) FILTER (
                           WHERE ml.location_precision = 'ward'
                       ) OVER(),
                       0
                   )::INTEGER AS ward_count
            FROM filtered f
            LEFT JOIN listing_map_locations ml
              ON ml.listing_id = f.id
             AND ml.location_precision IN (
                   'exact',
                   'road',
                   'landmark',
                   'ward'
             )
            GROUP BY ml.location_key,
                     ml.lat,
                     ml.lng,
                     ml.location_precision,
                     ml.location_label,
                     ml.accuracy_radius_m
            ORDER BY CASE ml.location_precision
                         WHEN 'exact' THEN 0
                         WHEN 'road' THEN 1
                         WHEN 'landmark' THEN 2
                         WHEN 'ward' THEN 3
                         ELSE 4
                     END,
                     COUNT(*) DESC,
                     ml.location_key
            """,
            params,
        ).fetchall()

    first = rows[0] if rows else None
    total = int(_row_value(first, "total_count", 0) or 0)
    mapped = int(_row_value(first, "mapped_count", 0) or 0)
    locations = []
    for row in rows:
        location_key = _row_value(row, "location_key")
        if not location_key:
            continue
        raw_radius = _row_value(row, "accuracy_radius_m")
        try:
            accuracy_radius_m = (
                max(float(raw_radius), 0.0)
                if raw_radius is not None
                else None
            )
        except (TypeError, ValueError):
            accuracy_radius_m = None
        relation = str(_row_value(row, "relation", "") or "").strip().lower()
        if relation not in _ALLOWED_LOCATION_RELATIONS:
            relation = ""
        locations.append({
            "location_key": str(location_key),
            "lat": float(_row_value(row, "lat", 0)),
            "lng": float(_row_value(row, "lng", 0)),
            "precision": str(_row_value(row, "location_precision", "")),
            "label": str(_row_value(row, "location_label", "")),
            "accuracy_radius_m": accuracy_radius_m,
            "relation": relation,
            "listing_count": int(_row_value(row, "listing_count", 0) or 0),
            "best_mos": round(
                float(_row_value(row, "best_mos", 0) or 0),
                1,
            ),
        })
    payload = {
        "mode": mode,
        "resolver_version": LISTING_MAP_RESOLVER_VERSION,
        "data_version": data_version,
        "summary": {
            "total": total,
            "mapped": mapped,
            "unmapped_count": total - mapped,
            "exact_count": int(_row_value(first, "exact_count", 0) or 0),
            "road_count": int(_row_value(first, "road_count", 0) or 0),
            "landmark_count": int(
                _row_value(first, "landmark_count", 0) or 0
            ),
            "nearby_count": 0,
            "ward_count": int(_row_value(first, "ward_count", 0) or 0),
        },
        "locations": locations,
    }
    return _cache_put(cache_key, payload)


def load_listing_map_items(
    *,
    mode: str,
    tier: str,
    filters: MapFilters,
    location_key: str,
    page: int,
    limit: int,
) -> dict:
    if mode not in {"signals", "all"}:
        raise ValueError("invalid map mode")
    filters = _normalized_filters(filters, tier)
    page = max(int(page), 1)
    limit = min(max(int(limit), 1), 50)
    offset = (page - 1) * limit
    filtered_sql, params = _filtered_sql(mode, filters)

    with get_conn() as conn:
        data_version = get_listing_map_data_version(conn)
        cache_key = (
            "items",
            tier,
            mode,
            filters,
            LISTING_MAP_RESOLVER_VERSION,
            data_version,
            location_key,
            page,
            limit,
        )
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached
        rows = conn.execute(
            _base_cte(filtered_sql)
            + """
            SELECT COUNT(*) OVER()::INTEGER AS total_count,
                   f.id,
                   f.title,
                   f.price_ty,
                   f.area_m2,
                   f.property_type,
                   f.ward,
                   f.road_name,
                   f.posted_at,
                   f.crawled_at,
                   f.first_seen_at,
                   f.price_updated_at,
                   f.activity_at,
                   f.source,
                   f.mos_pct,
                   f.is_signal,
                   primary_img.local_path AS primary_local_path,
                   primary_img.img_url AS primary_img_url
            FROM filtered f
            JOIN listing_map_locations ml ON ml.listing_id = f.id
            LEFT JOIN LATERAL (
                SELECT li.local_path, li.img_url
                FROM listing_images li
                WHERE li.listing_id = f.id
                ORDER BY li.img_order, li.id
                LIMIT 1
            ) primary_img ON TRUE
            WHERE ml.location_key = ?
            ORDER BY f.activity_at DESC, f.id DESC
            LIMIT ? OFFSET ?
            """,
            params + [location_key, limit, offset],
        ).fetchall()

    total = int(_row_value(rows[0], "total_count", 0) or 0) if rows else 0
    items = []
    for row in rows:
        prop_type = str(_row_value(row, "property_type", "") or "")
        activity_at, card_date_reason = listing_card_activity(row)
        items.append({
            "id": int(_row_value(row, "id", 0)),
            "title": str(_row_value(row, "title", "") or ""),
            "price_ty": _row_value(row, "price_ty"),
            "area_m2": _row_value(row, "area_m2"),
            "prop_type": prop_type,
            "prop_type_label": PROPERTY_TYPE_LABELS.get(prop_type, prop_type),
            "ward": str(_row_value(row, "ward", "") or ""),
            "road_name": str(_row_value(row, "road_name", "") or ""),
            "source": str(_row_value(row, "source", "") or ""),
            "mos_pct": round(
                float(_row_value(row, "mos_pct", 0) or 0),
                1,
            ),
            "is_signal": bool(_row_value(row, "is_signal", 0)),
            "days_ago": _days_ago(activity_at),
            "card_date_reason": card_date_reason,
            "thumbnail": resolve_image_url(
                _row_value(row, "primary_local_path"),
                _row_value(row, "primary_img_url"),
                prefer_thumb=True,
            ) or "",
        })
    payload = {
        "mode": mode,
        "location_key": location_key,
        "items": items,
        "total": total,
        "page": page,
        "limit": limit,
        "pages": (total + limit - 1) // limit if limit else 1,
        "has_more": page * limit < total,
        "data_version": data_version,
    }
    return _cache_put(cache_key, payload)
