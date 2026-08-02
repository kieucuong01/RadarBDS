"""Bounded legacy and read-model loaders for the public all-listings feed."""

from __future__ import annotations

from collections import defaultdict
import os

from config.property_types import normalize_property_types
from db.guland_publishers import publisher_sort_rank_sql
from services.image_assets import resolve_image_url
from services.market_data import (
    DEFAULT_VISIBLE_SOURCES,
    LEGAL_IMAGE_ORDER_SQL,
    LATEST_SHADOW_VALUATION_CTE,
    _days_ago,
    _display_fair_sql,
    _display_mos_sql,
    _open_read_conn,
    _range_filters,
    _row_get,
    build_listing_filters,
    keyword_search_filter,
    listing_activity_at_sql,
    listing_card_activity,
    listing_date_range_filter,
    redact_for_tier,
    signal_badge_metadata,
)
from services.signal_quality import LATEST_VALUATION_CTE, actionable_signal_sql


VALID_LISTING_SORTS = frozenset(
    {"area", "price", "price_m2", "fair", "date", "ward", "prop_type"}
)


def _statement_timeout_ms() -> int:
    try:
        value = int(os.getenv("RADAR_SIGNAL_QUERY_TIMEOUT_MS", "5000"))
    except (TypeError, ValueError):
        value = 5000
    return min(max(value, 100), 60000)


def listing_read_model_enabled(listings_version: int) -> bool:
    listing_flag = os.getenv(
        "RADAR_LISTING_READ_MODEL_ENABLED", "1"
    ).strip() != "0"
    signal_flag = os.getenv(
        "RADAR_SIGNAL_READ_MODEL_ENABLED", "0"
    ).strip() == "1"
    return listing_flag and signal_flag and int(listings_version or 0) > 0


def listing_sort_sql(sort_by: str, sort_dir: str, alias: str) -> str:
    selected = sort_by if sort_by in VALID_LISTING_SORTS else "date"
    direction = "DESC" if str(sort_dir).lower() == "desc" else "ASC"
    expressions = {
        "area": f"{alias}.area_m2",
        "price": f"{alias}.price_ty",
        "price_m2": f"{alias}.listing_price_per_m2",
        "fair": f"{alias}.fair_ppm2",
        "date": listing_activity_at_sql(alias),
        "ward": f"{alias}.ward",
        "prop_type": f"{alias}.property_type",
    }
    return (
        f"{alias}.publisher_rank ASC, "
        f"{expressions[selected]} {direction} NULLS LAST, "
        f"{alias}.listing_id DESC"
    )


def build_listing_read_model_filters(
    *,
    sources=None,
    wards=None,
    prop_types=None,
    only_drops=False,
    area_min=0,
    area_max=0,
    price_min=0,
    price_max=0,
    area_ranges=None,
    price_ranges=None,
    keyword="",
    date_range=None,
    complete_only=False,
    allow_high_activity=False,
) -> tuple[str, list]:
    sources = list(sources or DEFAULT_VISIBLE_SOURCES)
    prop_types = normalize_property_types(prop_types)
    clauses: list[str] = []
    params: list = []
    if not allow_high_activity:
        clauses.append("rm.publisher_visible_public")
    clauses.append(
        "rm.price_dropped" if only_drops else "NOT rm.possibly_duplicate"
    )

    for column, values in (
        ("ward", wards),
        ("source", sources),
        ("property_type", prop_types),
    ):
        normalized = list(values or ())
        if normalized:
            clauses.append(
                f"rm.{column} IN ({','.join('?' for _ in normalized)})"
            )
            params.extend(normalized)

    range_clauses, range_params = _range_filters(
        area_min,
        area_max,
        price_min,
        price_max,
        "rm.",
        area_ranges=area_ranges,
        price_ranges=price_ranges,
    )
    clauses.extend(range_clauses)
    params.extend(range_params)

    search_clauses, search_params = keyword_search_filter(keyword, "rm.")
    clauses.extend(search_clauses)
    params.extend(search_params)

    date_clauses, date_params = listing_date_range_filter(date_range, "rm.")
    clauses.extend(date_clauses)
    params.extend(date_params)

    if complete_only:
        clauses.extend(
            (
                "NULLIF(TRIM(COALESCE(rm.ward, '')), '') IS NOT NULL",
                "COALESCE(rm.price_ty, 0) > 0",
                "COALESCE(rm.area_m2, 0) > 0",
            )
        )
    return " AND ".join(clauses), params


def load_listing_counts_from_read_model(
    conn,
    *,
    sources=None,
    wards=None,
    prop_types=None,
    only_drops=False,
    area_min=0,
    area_max=0,
    price_min=0,
    price_max=0,
    area_ranges=None,
    price_ranges=None,
    keyword="",
    tier="guest",
    date_range=None,
    include_guland_high_activity=False,
) -> dict[str, int]:
    """Load badge metrics from the same compact projection as Tin rao."""
    allow_high_activity = bool(
        tier == "admin" and include_guland_high_activity
    )
    where_sql, params = build_listing_read_model_filters(
        sources=sources,
        wards=wards,
        prop_types=prop_types,
        only_drops=only_drops,
        area_min=area_min,
        area_max=area_max,
        price_min=price_min,
        price_max=price_max,
        area_ranges=area_ranges,
        price_ranges=price_ranges,
        keyword=keyword,
        date_range=date_range,
        allow_high_activity=allow_high_activity,
    )
    row = conn.execute(
        f"""
        SELECT
            COUNT(*) AS total,
            COALESCE(SUM(CASE WHEN rm.is_hot THEN 1 ELSE 0 END), 0) AS hot,
            COALESCE(SUM(CASE WHEN (
                COALESCE(rm.posted_at, rm.crawled_at) IS NOT NULL
                AND CAST(COALESCE(rm.posted_at, rm.crawled_at) AS TIMESTAMP)
                    >= datetime('now', '-7 days')
            ) THEN 1 ELSE 0 END), 0) AS new_recent_days_7,
            COALESCE(SUM(CASE WHEN rm.price_dropped THEN 1 ELSE 0 END), 0)
                AS price_drops
        FROM signal_card_read_model rm
        WHERE {where_sql}
        """,
        params,
    ).fetchone()
    return {
        "total": int(_row_get(row, "total", 0) or 0),
        "hot": int(_row_get(row, "hot", 0) or 0),
        "new_recent_days_7": int(
            _row_get(row, "new_recent_days_7", 0) or 0
        ),
        "price_drops": int(_row_get(row, "price_drops", 0) or 0),
    }


def _valid_price_drop_values(price_ty, price_first_ty) -> bool:
    try:
        price = float(price_ty) if price_ty is not None else None
        first_price = (
            float(price_first_ty) if price_first_ty is not None else None
        )
    except (TypeError, ValueError):
        return False
    return bool(
        price
        and first_price
        and price < first_price * 0.99
        and price >= first_price * 0.60
    )


def _drop_pct_from_prices(price_ty, price_first_ty):
    if not _valid_price_drop_values(price_ty, price_first_ty):
        return None
    price = float(price_ty)
    first_price = float(price_first_ty)
    return round((first_price - price) / first_price * 100, 2)


def _rounded(row, key, *, default=None):
    value = _row_get(row, key)
    return round(value, 1) if value else default


def _format_listing_row(row, imgs: list[str], *, tier: str) -> dict:
    badge_meta = signal_badge_metadata(row)
    activity_at, card_date_reason = listing_card_activity(row)
    price_ty = _row_get(row, "price_ty")
    price_first_ty = _row_get(row, "price_first_ty")
    price_dropped = _valid_price_drop_values(price_ty, price_first_ty)
    drop_pct = _drop_pct_from_prices(price_ty, price_first_ty)
    fair_ppm2 = _rounded(row, "fair_ppm2")
    mos_pct = _rounded(row, "mos_pct", default=0)
    fair_display = _rounded(row, "fair_ppm2_display", default=fair_ppm2)
    mos_display = _rounded(row, "mos_pct_display", default=mos_pct)
    return redact_for_tier(
        {
            "id": int(_row_get(row, "id")),
            "title": _row_get(row, "title", "") or "",
            "description": _row_get(row, "description", "") or "",
            "price_ty": price_ty,
            "area_m2": _row_get(row, "area_m2"),
            "frontage_m": _row_get(row, "frontage_m"),
            "depth_m": _row_get(row, "depth_m"),
            "price_per_m2": _rounded(row, "listing_price_per_m2"),
            "prop_type": _row_get(row, "property_type"),
            "prop_type_label": badge_meta["property_type_label"],
            "road_tier": _row_get(row, "road_tier"),
            "road_type": _row_get(row, "road_type"),
            "road_width_m": badge_meta["road_width_m"],
            "road_label": badge_meta["road_label"],
            "street_label": badge_meta["street_label"],
            "tho_cu_m2": badge_meta["tho_cu_m2"],
            "tho_cu_ratio": badge_meta["tho_cu_ratio"],
            "tho_cu_label": badge_meta["tho_cu_label"],
            "ward": _row_get(row, "ward"),
            "url": _row_get(row, "url"),
            "is_signal": bool(
                _row_get(row, "actionable_signal", False)
            ),
            "mos_pct": mos_pct,
            "fair_ppm2": fair_ppm2,
            "fair_ppm2_old": _rounded(row, "fair_ppm2_old"),
            "fair_ppm2_new": _rounded(row, "fair_ppm2_new"),
            "mos_pct_old": _rounded(row, "mos_pct_old", default=0),
            "mos_pct_new": _rounded(row, "mos_pct_new", default=0),
            "fair_ppm2_display": fair_display,
            "mos_pct_display": mos_display,
            "days_ago": _days_ago(activity_at),
            "card_date_reason": card_date_reason,
            "is_hot": bool(_row_get(row, "is_hot", False)),
            "price_dropped": price_dropped,
            "suspicious_bait": bool(
                _row_get(row, "suspicious_bait", False)
            ),
            "drop_pct": drop_pct,
            "price_first_ty": price_first_ty,
            "duplicate_of_id": _row_get(row, "duplicate_of_id"),
            "source": _row_get(row, "source"),
            "imgs": imgs,
            "is_fresh_locked": bool(
                _row_get(row, "is_fresh_locked", False)
            ),
        },
        tier,
    )


def _image_map(conn, listing_ids: list[int]) -> dict[int, list[str]]:
    if not listing_ids:
        return {}
    markers = ",".join("?" for _ in listing_ids)
    rows = conn.execute(
        f"""
        SELECT listing_id, local_path, img_url
        FROM listing_images
        WHERE listing_id IN ({markers})
        ORDER BY listing_id, {LEGAL_IMAGE_ORDER_SQL}
        """,
        listing_ids,
    ).fetchall()
    result: dict[int, list[str]] = defaultdict(list)
    for row in rows:
        listing_id = int(_row_get(row, "listing_id"))
        local_path = _row_get(row, "local_path")
        img_url = _row_get(row, "img_url")
        url = resolve_image_url(local_path, img_url)
        if url:
            result[listing_id].append(url)
    return dict(result)


def load_listings_from_read_model(
    db_path,
    *,
    sources=None,
    wards=None,
    prop_types=None,
    only_drops=False,
    sort_by="date",
    sort_dir="desc",
    page=1,
    limit=50,
    area_min=0,
    area_max=0,
    price_min=0,
    price_max=0,
    area_ranges=None,
    price_ranges=None,
    keyword="",
    tier="guest",
    date_range=None,
    complete_only=False,
    include_guland_high_activity=False,
) -> dict:
    page = min(max(int(page or 1), 1), 2000)
    limit = min(max(int(limit or 50), 1), 100)
    offset = (page - 1) * limit
    allow_high_activity = bool(
        tier == "admin" and include_guland_high_activity
    )
    where_sql, params = build_listing_read_model_filters(
        sources=sources,
        wards=wards,
        prop_types=prop_types,
        only_drops=only_drops,
        area_min=area_min,
        area_max=area_max,
        price_min=price_min,
        price_max=price_max,
        area_ranges=area_ranges,
        price_ranges=price_ranges,
        keyword=keyword,
        date_range=date_range,
        complete_only=complete_only,
        allow_high_activity=allow_high_activity,
    )
    page_order_sql = listing_sort_sql(sort_by, sort_dir, "f")
    result_order_sql = listing_sort_sql(sort_by, sort_dir, "rm")

    conn = _open_read_conn(db_path)
    try:
        conn.execute(
            "SELECT set_config('statement_timeout', ?, true)",
            (f"{_statement_timeout_ms()}ms",),
        )
        rows = conn.execute(
            f"""
            WITH filtered AS MATERIALIZED (
                SELECT rm.listing_id,
                       rm.publisher_rank,
                       rm.area_m2,
                       rm.price_ty,
                       rm.listing_price_per_m2,
                       rm.fair_ppm2,
                       rm.source,
                       rm.price_updated_at,
                       rm.first_seen_at,
                       rm.crawled_at,
                       rm.posted_at,
                       rm.ward,
                       rm.property_type
                FROM signal_card_read_model rm
                WHERE {where_sql}
            ),
            page_ids AS MATERIALIZED (
                SELECT f.listing_id
                FROM filtered f
                ORDER BY {page_order_sql}
                LIMIT ? OFFSET ?
            ),
            totals AS (
                SELECT COUNT(*) AS total_count FROM filtered
            )
            SELECT rm.listing_id AS id,
                   rm.*,
                   totals.total_count,
                   rm.fair_ppm2 AS fair_ppm2_display,
                   rm.mos_pct AS mos_pct_display,
                   rm.listing_is_signal AS actionable_signal,
                   0 AS is_fresh_locked
            FROM totals
            LEFT JOIN page_ids p ON TRUE
            LEFT JOIN signal_card_read_model rm
              ON rm.listing_id=p.listing_id
            ORDER BY {result_order_sql}
            """,
            params + [limit, offset],
        ).fetchall()

        total = (
            int(_row_get(rows[0], "total_count", 0) or 0) if rows else 0
        )
        candidates = [row for row in rows if _row_get(row, "id") is not None]
        listing_ids = [int(_row_get(row, "id")) for row in candidates]
        images = _image_map(conn, listing_ids)
    finally:
        conn.close()

    listings = [
        _format_listing_row(
            row,
            images.get(int(_row_get(row, "id")), []),
            tier=tier,
        )
        for row in candidates
    ]
    return {
        "listings": listings,
        "total": total,
        "page": page,
        "limit": limit,
        "pages": (total + limit - 1) // limit if limit else 1,
        "has_more": page * limit < total,
        "tier": tier,
    }


def _row_dict(row) -> dict:
    if isinstance(row, dict):
        return dict(row)
    return {key: row[key] for key in row.keys()}


def _load_listing_feed_legacy(
    db_path,
    *,
    sources=None,
    wards=None,
    prop_types=None,
    only_drops=False,
    sort_by="date",
    sort_dir="desc",
    page=1,
    limit=50,
    area_min=0,
    area_max=0,
    price_min=0,
    price_max=0,
    area_ranges=None,
    price_ranges=None,
    keyword="",
    tier="guest",
    date_range=None,
    complete_only=False,
    include_guland_high_activity=False,
) -> dict:
    page = min(max(int(page or 1), 1), 2000)
    limit = min(max(int(limit or 50), 1), 100)
    offset = (page - 1) * limit
    allow_high_activity = bool(
        tier == "admin" and include_guland_high_activity
    )
    where_sql, params = build_listing_filters(
        sources=sources,
        wards=wards,
        prop_types=prop_types,
        only_drops=only_drops,
        prefix="l.",
        area_min=area_min,
        area_max=area_max,
        price_min=price_min,
        price_max=price_max,
        area_ranges=area_ranges,
        price_ranges=price_ranges,
        keyword=keyword,
        date_range=date_range,
        require_complete=complete_only,
        include_guland_high_activity=allow_high_activity,
    )

    actual_expr = "COALESCE(v.actual_ppm2, sv.actual_ppm2, l.price_per_m2)"
    display_fair_expr = _display_fair_sql("v", "sv")
    display_mos_expr = _display_mos_sql("v", "sv", actual_expr)
    signal_condition = (
        f"({actionable_signal_sql('v')}) "
        f"AND ({actionable_signal_sql('sv')})"
    )
    selected_sort = sort_by if sort_by in VALID_LISTING_SORTS else "date"
    direction = "DESC" if str(sort_dir).lower() == "desc" else "ASC"
    sort_columns = {
        "area": "l.area_m2",
        "price": "l.price_ty",
        "price_m2": "l.price_per_m2",
        "fair": f"({display_fair_expr})",
        "date": listing_activity_at_sql("l"),
        "ward": "l.ward",
        "prop_type": "l.property_type",
    }
    order_sql = (
        f"{publisher_sort_rank_sql('l')} ASC, "
        f"{sort_columns[selected_sort]} {direction} NULLS LAST, l.id DESC"
    )

    conn = _open_read_conn(db_path)
    try:
        rows = conn.execute(
            f"""
            WITH {LATEST_VALUATION_CTE},
                 {LATEST_SHADOW_VALUATION_CTE}
            SELECT l.*,
                   l.price_per_m2 AS listing_price_per_m2,
                   {listing_activity_at_sql('l')} AS activity_at,
                   ({display_mos_expr}) AS mos_pct,
                   ({display_fair_expr}) AS fair_ppm2,
                   v.fair_ppm2 AS fair_ppm2_old,
                   sv.fair_ppm2 AS fair_ppm2_new,
                   v.mos_pct AS mos_pct_old,
                   sv.mos_pct AS mos_pct_new,
                   ({display_fair_expr}) AS fair_ppm2_display,
                   ({display_mos_expr}) AS mos_pct_display,
                   GREATEST(
                       COALESCE(v.signal_score,0),
                       COALESCE(sv.signal_score,0)
                   ) AS signal_score,
                   CASE WHEN {signal_condition}
                        THEN 1 ELSE 0 END AS actionable_signal,
                   0 AS is_fresh_locked
            FROM listings l
            LEFT JOIN latest_valuation v ON l.id=v.listing_id
            LEFT JOIN latest_shadow_valuation sv ON l.id=sv.listing_id
            WHERE {where_sql}
            ORDER BY {order_sql}
            LIMIT ? OFFSET ?
            """,
            params + [limit, offset],
        ).fetchall()
        total_row = conn.execute(
            f"SELECT COUNT(*) AS total FROM listings l WHERE {where_sql}",
            params,
        ).fetchone()
        total = int(_row_get(total_row, "total", 0) or 0)
        listing_ids = [int(_row_get(row, "id")) for row in rows]
        images = _image_map(conn, listing_ids)

        related_drop_map = {}
        if listing_ids:
            markers = ",".join("?" for _ in listing_ids)
            drop_rows = conn.execute(
                f"""
                SELECT drop_child.duplicate_of_id AS listing_id,
                       MAX(drop_child.price_ty) AS first_price
                FROM listings drop_child
                JOIN listings parent
                  ON parent.id=drop_child.duplicate_of_id
                WHERE drop_child.duplicate_of_id IN ({markers})
                  AND COALESCE(drop_child.probably_sold,0)=0
                  AND COALESCE(drop_child.is_blacklisted,0)=0
                  AND COALESCE(drop_child.review_hidden,0)=0
                  AND drop_child.price_ty IS NOT NULL
                  AND parent.price_ty IS NOT NULL
                  AND drop_child.price_ty > parent.price_ty * 1.01
                  AND parent.price_ty >= drop_child.price_ty * 0.60
                GROUP BY drop_child.duplicate_of_id
                """,
                listing_ids,
            ).fetchall()
            related_drop_map = {
                int(_row_get(row, "listing_id")): _row_get(
                    row, "first_price"
                )
                for row in drop_rows
            }
    finally:
        conn.close()

    listings = []
    for row in rows:
        record = _row_dict(row)
        listing_id = int(record["id"])
        related_first = related_drop_map.get(listing_id)
        if related_first is not None and record.get("price_ty"):
            record["price_first_ty"] = related_first
            record["price_drop_pct"] = round(
                (
                    (float(related_first) - float(record["price_ty"]))
                    / float(related_first)
                    * 100
                ),
                2,
            )
        listings.append(
            _format_listing_row(
                record,
                images.get(listing_id, []),
                tier=tier,
            )
        )
    return {
        "listings": listings,
        "total": total,
        "page": page,
        "limit": limit,
        "pages": (total + limit - 1) // limit if limit else 1,
        "has_more": page * limit < total,
        "tier": tier,
    }


def load_listing_feed(
    db_path,
    *,
    sources=None,
    wards=None,
    prop_types=None,
    only_drops=False,
    sort_by="date",
    sort_dir="desc",
    page=1,
    limit=50,
    area_min=0,
    area_max=0,
    price_min=0,
    price_max=0,
    area_ranges=None,
    price_ranges=None,
    keyword="",
    tier="guest",
    date_range=None,
    complete_only=False,
    include_guland_high_activity=False,
    listings_version=0,
) -> dict:
    loader_kwargs = {
        "sources": sources,
        "wards": wards,
        "prop_types": prop_types,
        "only_drops": only_drops,
        "sort_by": sort_by,
        "sort_dir": sort_dir,
        "page": page,
        "limit": limit,
        "area_min": area_min,
        "area_max": area_max,
        "price_min": price_min,
        "price_max": price_max,
        "area_ranges": area_ranges,
        "price_ranges": price_ranges,
        "keyword": keyword,
        "tier": tier,
        "date_range": date_range,
        "complete_only": complete_only,
        "include_guland_high_activity": include_guland_high_activity,
    }
    if listing_read_model_enabled(listings_version):
        return load_listings_from_read_model(db_path, **loader_kwargs)
    return _load_listing_feed_legacy(db_path, **loader_kwargs)
