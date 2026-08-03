"""Transactional PostgreSQL read model for compact public signal cards."""

from dataclasses import dataclass
import os
import time

from config.property_types import normalize_property_types
from config.settings import LEGAL_IMAGE_EVIDENCE_ENABLED
from db.guland_publishers import (
    publisher_feed_join_sql,
    publisher_sort_rank_from_join_sql,
    publisher_visibility_from_join_sql,
)
from db.public_dataset_versions import (
    DATASET_LISTINGS,
    DATASET_MARKET,
    DATASET_SIGNALS,
    bump_dataset_versions,
    get_dataset_versions,
)
from services.market_data import (
    LEGAL_DOC_IMAGE_SELECT_SQL,
    LEGAL_IMAGE_ORDER_SQL,
    LATEST_SHADOW_VALUATION_CTE,
    RELATED_PRICE_DROP_CTE,
    DEFAULT_VISIBLE_SOURCES,
    _format_signal_row,
    _max_sql,
    _open_read_conn,
    _range_filters,
    _row_get,
    _signal_listing_data_sql,
    build_deal_sql,
    effective_price_drop_select_sql,
    keyword_search_filter,
    listing_activity_at_sql,
    listing_date_range_filter,
    related_price_drop_join_sql,
    resolve_image_url,
)
from services.signal_quality import (
    DEFAULT_SIGNAL_MOS_MIN_PCT,
    LATEST_VALUATION_CTE,
    actionable_signal_sql,
    effective_signal_mos_min,
)


READ_MODEL_COLUMNS = (
    "listing_id",
    "title",
    "description",
    "source",
    "source_status",
    "url",
    "ward",
    "property_type",
    "area_m2",
    "frontage_m",
    "depth_m",
    "price_ty",
    "listing_price_per_m2",
    "actual_ppm2",
    "fair_ppm2",
    "fair_ppm2_old",
    "fair_ppm2_new",
    "mos_pct",
    "mos_pct_old",
    "mos_pct_new",
    "signal_score",
    "is_actionable",
    "listing_is_signal",
    "is_hot",
    "possibly_duplicate",
    "price_dropped",
    "price_drop_pct",
    "price_first_ty",
    "suspicious_bait",
    "duplicate_of_id",
    "activity_at",
    "crawled_at",
    "posted_at",
    "first_seen_at",
    "price_updated_at",
    "road_name",
    "road_type",
    "road_width_m",
    "road_tier",
    "tho_cu_m2",
    "tho_cu_ratio",
    "has_so",
    "trust_tier",
    "trust_score",
    "legal_status",
    "legal_flags",
    "source_quality_flags",
    "source_quality_recheck",
    "has_legal_doc_image",
    "publisher_visible_public",
    "publisher_rank",
    "primary_image_id",
    "image_count",
    "refreshed_at",
)

PUBLIC_READ_TABLES = (
    "listings",
    "valuation_results",
    "valuation_shadow_results",
    "listing_images",
    "listing_publishers",
    "source_publishers",
    "signal_card_read_model",
)


@dataclass(frozen=True)
class SignalReadModelRefresh:
    mode: str
    affected_rows: int
    versions: dict[str, int]
    duration_ms: float


def _select_sql(listing_ids: tuple[int, ...] | None) -> tuple[str, tuple[int, ...]]:
    ids = tuple(listing_ids or ())
    listing_id_clause = ""
    if ids:
        markers = ",".join("?" for _ in ids)
        listing_id_clause = f"AND l.id IN ({markers})"

    deal = build_deal_sql(0)
    actual_expr = deal.actual_expr
    fair_expr = deal.fair_expr
    mos_expr = deal.mos_expr
    actionable_expr = actionable_signal_sql("v")
    score_expr = _max_sql(
        "COALESCE(v.signal_score, 0)",
        "COALESCE(sv.signal_score, 0)",
    )
    complete_listing_expr = _signal_listing_data_sql("l")
    is_actionable_expr = (
        f"(({complete_listing_expr}) AND ({actionable_expr}))"
    )
    listing_is_signal_expr = (
        f"(({actionable_signal_sql('v')}) "
        f"AND ({actionable_signal_sql('sv')}))"
    )
    public_visibility_expr = publisher_visibility_from_join_sql("l", "feed_sp")
    publisher_rank_expr = publisher_sort_rank_from_join_sql("l", "feed_sp")
    primary_image_order_sql = (
        LEGAL_IMAGE_ORDER_SQL.replace("img_type", "li.img_type")
        .replace("img_order", "li.img_order")
        .replace(", id", ", li.id")
    )
    price_drop_select = effective_price_drop_select_sql(
        "l",
        "related_drop",
        boolean_flag=True,
    )

    sql = f"""
    WITH {LATEST_VALUATION_CTE},
         {LATEST_SHADOW_VALUATION_CTE},
         {RELATED_PRICE_DROP_CTE}
    SELECT
        l.id AS listing_id,
        COALESCE(l.title, '') AS title,
        COALESCE(l.description, '') AS description,
        l.source,
        COALESCE(l.source_status, 'unknown') AS source_status,
        COALESCE(l.url, '') AS url,
        l.ward,
        l.property_type,
        l.area_m2,
        l.frontage_m,
        l.depth_m,
        l.price_ty,
        l.price_per_m2 AS listing_price_per_m2,
        ({actual_expr}) AS actual_ppm2,
        ({fair_expr}) AS fair_ppm2,
        v.fair_ppm2 AS fair_ppm2_old,
        sv.fair_ppm2 AS fair_ppm2_new,
        ({mos_expr}) AS mos_pct,
        v.mos_pct AS mos_pct_old,
        sv.mos_pct AS mos_pct_new,
        {score_expr} AS signal_score,
        ({is_actionable_expr}) AS is_actionable,
        ({listing_is_signal_expr}) AS listing_is_signal,
        COALESCE(l.is_hot, 0)::boolean AS is_hot,
        COALESCE(l.possibly_duplicate, 0)::boolean AS possibly_duplicate,
        {price_drop_select},
        COALESCE(l.suspicious_bait, 0)::boolean AS suspicious_bait,
        l.duplicate_of_id,
        NULLIF(({listing_activity_at_sql('l')})::text, '')::timestamptz
            AS activity_at,
        l.crawled_at,
        l.posted_at,
        l.first_seen_at,
        l.price_updated_at::text AS price_updated_at,
        l.road_name,
        l.road_type,
        l.road_width_m,
        COALESCE(l.road_tier, 0) AS road_tier,
        l.tho_cu_m2,
        l.tho_cu_ratio,
        COALESCE(l.has_so, 0)::boolean AS has_so,
        COALESCE(v.trust_tier, sv.trust_tier, 'candidate_signal')
            AS trust_tier,
        COALESCE(v.trust_score, sv.trust_score, 0) AS trust_score,
        COALESCE(v.legal_status, sv.legal_status, 'unverified')
            AS legal_status,
        COALESCE(v.legal_flags, sv.legal_flags, '') AS legal_flags,
        COALESCE(v.source_quality_flags, sv.source_quality_flags, '')
            AS source_quality_flags,
        COALESCE(
            v.source_quality_recheck,
            sv.source_quality_recheck,
            0
        )::boolean AS source_quality_recheck,
        ({LEGAL_DOC_IMAGE_SELECT_SQL})::boolean AS has_legal_doc_image,
        ({public_visibility_expr}) AS publisher_visible_public,
        ({publisher_rank_expr}) AS publisher_rank,
        primary_img.id AS primary_image_id,
        COALESCE(img_count.image_count, 0)::integer AS image_count,
        NOW() AS refreshed_at
    FROM listings l
    LEFT JOIN latest_valuation v ON v.listing_id=l.id
    LEFT JOIN latest_shadow_valuation sv ON sv.listing_id=l.id
    {publisher_feed_join_sql('l', 'feed_lp', 'feed_sp')}
    {related_price_drop_join_sql('l', 'related_drop')}
    LEFT JOIN LATERAL (
        SELECT li.id
        FROM listing_images li
        WHERE li.listing_id=l.id
        ORDER BY {primary_image_order_sql}
        LIMIT 1
    ) primary_img ON TRUE
    LEFT JOIN LATERAL (
        SELECT COUNT(*)::integer AS image_count
        FROM listing_images li
        WHERE li.listing_id=l.id
    ) img_count ON TRUE
    WHERE COALESCE(l.probably_sold, 0)=0
      AND COALESCE(l.is_blacklisted, 0)=0
      AND COALESCE(l.review_hidden, 0)=0
      AND COALESCE(l.source_status, 'unknown') <> 'inactive'
      {listing_id_clause}
    """
    return sql, ids


def _column_list() -> str:
    return ", ".join(READ_MODEL_COLUMNS)


def _insert_staged_rows(conn) -> int:
    columns = _column_list()
    cursor = conn.execute(
        f"INSERT INTO signal_card_read_model ({columns}) "
        f"SELECT {columns} FROM signal_card_read_model_stage"
    )
    return max(int(cursor.rowcount or 0), 0)


def _insert_selected_rows(conn, listing_ids: tuple[int, ...]) -> int:
    select_sql, params = _select_sql(listing_ids)
    cursor = conn.execute(
        f"INSERT INTO signal_card_read_model ({_column_list()}) {select_sql}",
        params,
    )
    return max(int(cursor.rowcount or 0), 0)


def refresh_signal_card_read_model(
    conn,
    *,
    listing_ids: tuple[int, ...] | None,
    market_changed: bool = False,
) -> SignalReadModelRefresh:
    started = time.perf_counter()
    ids = (
        None
        if listing_ids is None
        else tuple(
            dict.fromkeys(int(value) for value in listing_ids if int(value) > 0)
        )
    )
    if ids is not None and not ids:
        versions = get_dataset_versions(
            conn, (DATASET_SIGNALS, DATASET_LISTINGS)
        )
        return SignalReadModelRefresh("noop", 0, versions, 0.0)
    if ids is not None and len(ids) > 500:
        ids = None

    if ids is None:
        conn.execute("DROP TABLE IF EXISTS signal_card_read_model_stage")
        select_sql, select_params = _select_sql(None)
        conn.execute(
            "CREATE TEMP TABLE signal_card_read_model_stage "
            "ON COMMIT DROP AS "
            + select_sql,
            select_params,
        )
        conn.execute("LOCK TABLE signal_card_read_model IN ACCESS EXCLUSIVE MODE")
        conn.execute("DELETE FROM signal_card_read_model")
        affected = _insert_staged_rows(conn)
        mode = "full"
    else:
        markers = ",".join("?" for _ in ids)
        conn.execute(
            f"DELETE FROM signal_card_read_model WHERE listing_id IN ({markers})",
            ids,
        )
        affected = _insert_selected_rows(conn, ids)
        mode = "incremental"

    datasets = (
        (DATASET_SIGNALS, DATASET_LISTINGS, DATASET_MARKET)
        if market_changed
        else (DATASET_SIGNALS, DATASET_LISTINGS)
    )
    versions = bump_dataset_versions(conn, datasets)
    return SignalReadModelRefresh(
        mode,
        int(affected),
        versions,
        round((time.perf_counter() - started) * 1000, 2),
    )


def analyze_public_read_tables(conn) -> None:
    conn.execute("ANALYZE " + ", ".join(PUBLIC_READ_TABLES))


def _statement_timeout_ms() -> int:
    try:
        value = int(os.getenv("RADAR_SIGNAL_QUERY_TIMEOUT_MS", "5000"))
    except (TypeError, ValueError):
        value = 5000
    return min(max(value, 100), 60000)


def _read_model_sort_sql(sort_key: str, alias: str) -> str:
    newest = (
        f"{listing_activity_at_sql(alias)} DESC, "
        f"{alias}.listing_id DESC"
    )
    sort_map = {
        "newest": newest,
        "price_m2_asc": (
            f"{alias}.actual_ppm2 IS NULL, {alias}.actual_ppm2 ASC, "
            f"{alias}.listing_id DESC"
        ),
        "price_asc": (
            f"{alias}.price_ty IS NULL, {alias}.price_ty ASC, "
            f"{alias}.listing_id DESC"
        ),
        "mos_desc": (
            f"{alias}.mos_pct IS NULL, {alias}.mos_pct DESC, "
            f"{alias}.listing_id DESC"
        ),
    }
    score_parts = []
    if LEGAL_IMAGE_EVIDENCE_ENABLED:
        score_parts.extend(
            (
                f"CASE COALESCE({alias}.trust_tier, 'candidate_signal') "
                "WHEN 'has_legal_doc' THEN 0 ELSE 1 END ASC",
                f"COALESCE({alias}.trust_score, 0) DESC",
            )
        )
    score_parts.extend(
        (
            f"COALESCE({alias}.signal_score, 0) DESC",
            f"{alias}.mos_pct DESC",
            f"{alias}.listing_id DESC",
        )
    )
    sort_map["score_desc"] = ", ".join(score_parts)
    selected = sort_map.get(sort_key or "newest", newest)
    return f"{alias}.publisher_rank ASC, {selected}"


def _read_model_filters(
    *,
    sources=None,
    wards=None,
    prop_types=None,
    only_drops=False,
    mos_min=DEFAULT_SIGNAL_MOS_MIN_PCT,
    area_min=0,
    area_max=0,
    price_min=0,
    price_max=0,
    area_ranges=None,
    price_ranges=None,
    keyword="",
    date_range=None,
    allow_high_activity=False,
) -> tuple[str, list]:
    sources = list(sources or DEFAULT_VISIBLE_SOURCES)
    prop_types = normalize_property_types(prop_types)
    clauses = [
        "rm.is_actionable",
        "(? OR rm.publisher_visible_public)",
        "COALESCE(rm.mos_pct, 0) >= ?",
    ]
    params: list = [bool(allow_high_activity), float(mos_min or 0)]
    clauses.append("rm.price_dropped" if only_drops else "NOT rm.possibly_duplicate")

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
    return " AND ".join(clauses), params


def build_signal_read_model_filters(**kwargs) -> tuple[str, list]:
    """Build the canonical public signal predicate for adjacent read models."""
    return _read_model_filters(**kwargs)


def count_signals_from_read_model(
    conn,
    *,
    sources=None,
    wards=None,
    prop_types=None,
    only_drops=False,
    mos_min=0,
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
) -> int:
    """Count the exact public signal feed without rebuilding valuations."""
    mos_min = effective_signal_mos_min(tier, mos_min, was_explicit=True)
    if tier == "guest":
        only_drops = False

    allow_high_activity = bool(
        tier == "admin" and include_guland_high_activity
    )
    where_sql, params = _read_model_filters(
        sources=sources,
        wards=wards,
        prop_types=prop_types,
        only_drops=only_drops,
        mos_min=mos_min,
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
        SELECT COUNT(*) AS signals
        FROM signal_card_read_model rm
        WHERE {where_sql}
        """,
        params,
    ).fetchone()
    return int(_row_get(row, "signals", 0) or 0)


def load_signals_from_read_model(
    db_path,
    sources=None,
    wards=None,
    prop_types=None,
    only_drops=False,
    mos_min=DEFAULT_SIGNAL_MOS_MIN_PCT,
    sort="newest",
    page=1,
    limit=30,
    area_min=0,
    area_max=0,
    price_min=0,
    price_max=0,
    tier="guest",
    area_ranges=None,
    price_ranges=None,
    keyword="",
    include_total=True,
    date_range=None,
    include_guland_high_activity=False,
):
    mos_min = effective_signal_mos_min(tier, mos_min, was_explicit=True)
    if tier == "guest":
        only_drops = False

    page = max(int(page or 1), 1)
    limit = min(max(int(limit or 30), 1), 100)
    offset = (page - 1) * limit
    query_limit = limit if include_total else limit + 1
    allow_high_activity = bool(
        tier == "admin" and include_guland_high_activity
    )
    where_sql, params = _read_model_filters(
        sources=sources,
        wards=wards,
        prop_types=prop_types,
        only_drops=only_drops,
        mos_min=mos_min,
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
    candidate_order = _read_model_sort_sql(sort, "rm")
    result_order = _read_model_sort_sql(sort, "c")
    total_select = ", COUNT(*) OVER() AS total_count" if include_total else ""

    conn = _open_read_conn(db_path)
    try:
        conn.execute(
            "SELECT set_config('statement_timeout', ?, true)",
            (f"{_statement_timeout_ms()}ms",),
        )
        rows = conn.execute(
            f"""
            WITH candidates AS MATERIALIZED (
                SELECT rm.*{total_select}
                FROM signal_card_read_model rm
                WHERE {where_sql}
                ORDER BY {candidate_order}
                LIMIT ? OFFSET ?
            )
            SELECT c.listing_id AS id,
                   c.*,
                   c.fair_ppm2 AS fair_ppm2_display,
                   c.mos_pct AS mos_pct_display,
                   'display_mos' AS signal_model,
                   li.local_path AS primary_local_path,
                   li.img_url AS primary_img_url,
                   0 AS is_fresh_locked
            FROM candidates c
            LEFT JOIN listing_images li ON li.id=c.primary_image_id
            ORDER BY {result_order}
            """,
            params + [query_limit, offset],
        ).fetchall()
    finally:
        conn.close()

    has_more_without_total = (not include_total) and len(rows) > limit
    if not include_total:
        rows = rows[:limit]
    total = int(_row_get(rows[0], "total_count", 0)) if include_total and rows else 0
    signals = [
        _format_signal_row(
            row,
            resolve_image_url(
                _row_get(row, "primary_local_path"),
                _row_get(row, "primary_img_url"),
                prefer_thumb=True,
            ),
            tier=tier,
        )
        for row in rows
    ]
    payload = {
        "signals": signals,
        "page": page,
        "limit": limit,
        "has_more": (
            has_more_without_total
            if not include_total
            else page * limit < total
        ),
        "sort": sort or "newest",
        "tier": tier,
    }
    if include_total:
        payload["total"] = total
        payload["pages"] = (total + limit - 1) // limit if limit else 1
    return payload
