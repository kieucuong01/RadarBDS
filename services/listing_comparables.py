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
from services.comparison_evidence import add_comparison_evidence, comparison_summary


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


def load_listing_comparison(conn, listing_id: int, tier: str, limit: int = 18) -> dict:
    current = conn.execute(
        """
        SELECT id, source, source_id, title, ward, area_m2, property_type, tx_type, road_tier, price_per_m2,
               tho_cu_m2, duplicate_of_id
        FROM listings
        WHERE id = ?
        """,
        (listing_id,),
    ).fetchone()
    if (not current or current["ward"] in (None, "", "unknown") or current["property_type"] in (None, "", "unknown")
            or not current["area_m2"] or current["area_m2"] <= 0 or current.get("tx_type") != "ban"):
        return {"comps": [], "comparison_summary": comparison_summary(None, [])}

    area = float(current["area_m2"])
    display_fair = _display_fair_sql("v", "sv")
    display_mos = _display_mos_sql(
        "v",
        "sv",
        "COALESCE(v.actual_ppm2, sv.actual_ppm2, l.price_per_m2)",
    )

    where = [
        "l.id NOT IN (?, ?)",
        "l.duplicate_of_id IS NULL",
        "l.tx_type = 'ban'",
        "l.price_per_m2 > 0",
        "COALESCE(l.suspicious_bait,0)=0",
        "COALESCE(l.extraction_quality_flags,'') !~ 'ambiguous_price_text|multi_lot_listing|area_dimension_conflict'",
        "l.ward = ?",
        "l.property_type = ?",
        "l.price_ty > 0",
        "l.area_m2 BETWEEN ? AND ?",
        "COALESCE(l.probably_sold,0)=0",
        "COALESCE(l.is_blacklisted,0)=0",
        "COALESCE(l.review_hidden,0)=0",
        "COALESCE(l.possibly_duplicate,0)=0",
    ]
    params: list[object] = [
        listing_id, current.get("duplicate_of_id") or listing_id, current["ward"],
        current["property_type"], area * 0.75, area * 1.30,
    ]
    if tier != "admin":
        where.append("l.source <> 'guland'")
    if current.get("source_id"):
        where.append("(l.source, l.source_id) IS DISTINCT FROM (?, ?)")
        params.extend([current["source"], current["source_id"]])

    rows = conn.execute(
        f"""
        WITH {LATEST_VALUATION_CTE},
             {LATEST_SHADOW_VALUATION_CTE}
        SELECT l.id, l.title, l.description, l.url, l.ward, l.price_ty,
               l.area_m2, l.frontage_m, l.depth_m, l.price_per_m2,
               l.property_type, l.road_tier, l.road_name, l.road_type,
               l.road_width_m, l.tho_cu_m2, l.tho_cu_ratio,
               l.posted_at, l.crawled_at, l.last_seen_at, l.source, l.is_hot,
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
        ORDER BY CASE WHEN l.road_tier = ? AND l.road_tier > 0 THEN 0 ELSE 1 END,
                 ABS(l.area_m2 - ?) ASC,
                 COALESCE(l.last_seen_at, l.crawled_at) DESC NULLS LAST, l.id DESC
        LIMIT 40
        """,
        params + [current["road_tier"], area],
    ).fetchall()

    current_tokens = _title_tokens(current["title"])
    ranked = []
    for row in rows:
        candidate_area = float(row["area_m2"] or 0)
        area_gap = abs(candidate_area - area) / area if area and candidate_area else 0.0
        road_gap = 0
        if current["road_tier"]:
            road_gap = abs(row["road_tier"] - current["road_tier"]) if row["road_tier"] else 2
        score = 100.0
        score -= min(45.0, area_gap * 55.0)
        score -= min(12.0, road_gap * 6.0)
        score += min(12.0, _jaccard(current_tokens, _title_tokens(row["title"])) * 12.0)
        ranked.append((round(max(0.0, min(99.0, score)), 1), area_gap, row))

    ranked.sort(key=lambda item: (-item[0], item[1]))
    output = []
    for score, _area_gap, row in ranked[: min(max(int(limit or 18), 1), 18)]:
        primary = resolve_image_url(row["primary_local_path"], row["primary_img_url"])
        item = format_signal_card_record(row, primary, tier=tier)
        item["detail_url"] = f"/listing/{int(row['id'])}"
        item["match_score"] = score
        output.append(add_comparison_evidence(
            item, row, area=area, road_tier=current["road_tier"], tho_cu=current.get("tho_cu_m2"),
        ))
    return {"comps": output, "comparison_summary": comparison_summary(current["price_per_m2"], output)}


def load_listing_comparables(conn, listing_id: int, tier: str, limit: int = 18) -> list[dict]:
    return load_listing_comparison(conn, listing_id, tier, limit)["comps"]
