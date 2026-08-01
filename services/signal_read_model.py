"""Transactional PostgreSQL read model for compact public signal cards."""

from dataclasses import dataclass
import time

from db.guland_publishers import (
    publisher_feed_join_sql,
    publisher_sort_rank_from_join_sql,
    publisher_visibility_from_join_sql,
)
from db.public_dataset_versions import (
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
    _max_sql,
    _signal_listing_data_sql,
    build_deal_sql,
    effective_price_drop_select_sql,
    listing_activity_at_sql,
    related_price_drop_join_sql,
)
from services.signal_quality import LATEST_VALUATION_CTE, actionable_signal_sql


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
    "actual_ppm2",
    "fair_ppm2",
    "fair_ppm2_old",
    "fair_ppm2_new",
    "mos_pct",
    "mos_pct_old",
    "mos_pct_new",
    "signal_score",
    "is_actionable",
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
        ({actual_expr}) AS actual_ppm2,
        ({fair_expr}) AS fair_ppm2,
        v.fair_ppm2 AS fair_ppm2_old,
        sv.fair_ppm2 AS fair_ppm2_new,
        ({mos_expr}) AS mos_pct,
        v.mos_pct AS mos_pct_old,
        sv.mos_pct AS mos_pct_new,
        {score_expr} AS signal_score,
        ({actionable_expr}) AS is_actionable,
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
      AND {complete_listing_expr}
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
        versions = get_dataset_versions(conn, (DATASET_SIGNALS,))
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
        (DATASET_SIGNALS, DATASET_MARKET)
        if market_changed
        else (DATASET_SIGNALS,)
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
