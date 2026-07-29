"""Compact, tier-safe comparable listing cards for detail surfaces."""
from __future__ import annotations

import re
import unicodedata

from services.market_data import (
    LATEST_SHADOW_VALUATION_CTE,
    _display_fair_sql,
    _display_mos_sql,
    format_signal_card_record,
    resolve_image_url,
)
from services.signal_quality import LATEST_VALUATION_CTE


def _fold(value: object) -> str:
    text = str(value or "").replace("Đ", "D").replace("đ", "d")
    return "".join(
        char
        for char in unicodedata.normalize("NFD", text)
        if unicodedata.category(char) != "Mn"
    ).lower()


def _title_tokens(value: object) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", _fold(value))
        if len(token) >= 2
    }


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def load_listing_comparables(conn, listing_id: int, tier: str, limit: int = 18) -> list[dict]:
    """Return ranked signal-card records without repeating the current listing."""
    current = conn.execute(
        """
        SELECT id, title, ward, area_m2, property_type, road_tier, price_per_m2
        FROM listings
        WHERE id = ?
        """,
        (listing_id,),
    ).fetchone()
    if not current or not current["ward"]:
        return []

    area = float(current["area_m2"] or 0)
    actual_ppm2 = float(current["price_per_m2"] or 0)
    area_min = max(1.0, area * 0.75) if area else 1.0
    area_max = area * 1.30 if area else 20_000.0
    ppm2_min = actual_ppm2 * 0.55 if actual_ppm2 else 0.0
    ppm2_max = actual_ppm2 * 1.45 if actual_ppm2 else 999_999.0
    display_fair = _display_fair_sql("v", "sv")
    display_mos = _display_mos_sql(
        "v",
        "sv",
        "COALESCE(v.actual_ppm2, sv.actual_ppm2, l.price_per_m2)",
    )

    where = [
        "l.id <> ?",
        "l.ward = ?",
        "l.price_ty > 0",
        "l.area_m2 BETWEEN ? AND ?",
        "COALESCE(l.probably_sold,0)=0",
        "COALESCE(l.is_blacklisted,0)=0",
        "COALESCE(l.review_hidden,0)=0",
        "COALESCE(l.possibly_duplicate,0)=0",
    ]
    params: list[object] = [listing_id, current["ward"], area_min, area_max]
    if current["property_type"]:
        where.append("l.property_type = ?")
        params.append(current["property_type"])
    if actual_ppm2 > 0:
        where.append("COALESCE(l.price_per_m2,0) BETWEEN ? AND ?")
        params.extend([ppm2_min, ppm2_max])
    if current["road_tier"] is not None:
        where.append("(l.road_tier IS NULL OR ABS(l.road_tier - ?) <= 1)")
        params.append(current["road_tier"])

    rows = conn.execute(
        f"""
        WITH {LATEST_VALUATION_CTE},
             {LATEST_SHADOW_VALUATION_CTE}
        SELECT l.id, l.title, l.description, l.url, l.ward, l.price_ty,
               l.area_m2, l.frontage_m, l.depth_m, l.price_per_m2,
               l.property_type, l.road_tier, l.road_name, l.road_type,
               l.road_width_m, l.tho_cu_m2, l.tho_cu_ratio,
               l.posted_at, l.crawled_at, l.source, l.is_hot,
               l.price_dropped, l.suspicious_bait, l.price_drop_pct,
               l.price_first_ty, l.duplicate_of_id, l.has_so,
               COALESCE(v.actual_ppm2, sv.actual_ppm2, l.price_per_m2) AS actual_ppm2,
               ({display_fair}) AS fair_ppm2,
               v.fair_ppm2 AS fair_ppm2_old,
               sv.fair_ppm2 AS fair_ppm2_new,
               ({display_mos}) AS mos_pct,
               v.mos_pct AS mos_pct_old,
               sv.mos_pct AS mos_pct_new,
               ({display_fair}) AS fair_ppm2_display,
               ({display_mos}) AS mos_pct_display,
               'display_mos' AS signal_model,
               GREATEST(COALESCE(v.signal_score,0), COALESCE(sv.signal_score,0)) AS signal_score,
               COALESCE(v.trust_tier, sv.trust_tier, 'candidate_signal') AS trust_tier,
               COALESCE(v.trust_score, sv.trust_score, 0) AS trust_score,
               COALESCE(v.legal_status, sv.legal_status, 'unverified') AS legal_status,
               COALESCE(v.legal_flags, sv.legal_flags, '') AS legal_flags,
               COALESCE(v.source_quality_flags, sv.source_quality_flags, '') AS source_quality_flags,
               COALESCE(v.source_quality_recheck, sv.source_quality_recheck, 0) AS source_quality_recheck,
               0 AS has_legal_doc_image,
               primary_img.local_path AS primary_local_path,
               primary_img.img_url AS primary_img_url,
               COALESCE(img_count.image_count, 0) AS image_count,
               0 AS is_fresh_locked
        FROM listings l
        LEFT JOIN latest_valuation v ON v.listing_id = l.id
        LEFT JOIN latest_shadow_valuation sv ON sv.listing_id = l.id
        LEFT JOIN LATERAL (
            SELECT li.local_path, li.img_url
            FROM listing_images li
            WHERE li.listing_id = l.id
            ORDER BY li.img_order, li.id
            LIMIT 1
        ) primary_img ON TRUE
        LEFT JOIN LATERAL (
            SELECT COUNT(*)::INTEGER AS image_count
            FROM listing_images li
            WHERE li.listing_id = l.id
        ) img_count ON TRUE
        WHERE {" AND ".join(where)}
        ORDER BY ABS(l.area_m2 - ?) ASC,
                 ABS(COALESCE(l.price_per_m2,0) - ?) ASC,
                 COALESCE(l.posted_at, l.crawled_at) DESC
        LIMIT 40
        """,
        params + [area, actual_ppm2],
    ).fetchall()

    current_tokens = _title_tokens(current["title"])
    ranked = []
    for row in rows:
        candidate_area = float(row["area_m2"] or 0)
        candidate_ppm2 = float(row["price_per_m2"] or 0)
        area_gap = abs(candidate_area - area) / area if area and candidate_area else 0.0
        ppm2_gap = (
            abs(candidate_ppm2 - actual_ppm2) / actual_ppm2
            if actual_ppm2 and candidate_ppm2
            else 0.0
        )
        road_gap = (
            abs(int(row["road_tier"]) - int(current["road_tier"]))
            if row["road_tier"] is not None and current["road_tier"] is not None
            else 0
        )
        score = 100.0
        score -= min(45.0, area_gap * 55.0)
        score -= min(30.0, ppm2_gap * 30.0)
        score -= min(12.0, road_gap * 6.0)
        score += min(12.0, _jaccard(current_tokens, _title_tokens(row["title"])) * 12.0)
        ranked.append((round(max(0.0, min(99.0, score)), 1), area_gap, row))

    ranked.sort(key=lambda item: (-item[0], item[1], -(item[2]["price_per_m2"] or 0)))
    output = []
    for score, _area_gap, row in ranked[: min(max(int(limit or 18), 1), 18)]:
        primary = resolve_image_url(row["primary_local_path"], row["primary_img_url"])
        item = format_signal_card_record(row, primary, tier=tier)
        item["detail_url"] = f"/listing/{int(row['id'])}"
        item["match_score"] = score
        output.append(item)
    return output
