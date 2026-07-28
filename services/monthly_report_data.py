"""Canonical, quality-gated read model for monthly public reports."""
from __future__ import annotations

from typing import Any, Callable

from services.signal_quality import (
    LATEST_VALUATION_CTE,
    actionable_listing_sql,
    actionable_signal_sql,
)


WARD_ALIASES = {
    "Tân An": "Tan An",
    "Hiệp An": "Hiep An",
    "Tương Bình Hiệp": "Tuong Binh Hiep",
    "Định Hòa": "Dinh Hoa",
    "Chánh Mỹ": "Chanh My",
    "Phú Mỹ": "Phu My",
    "Phú Cường": "Phu Cuong",
    "Phú Hòa": "Phu Hoa",
    "Phú Lợi": "Phu Loi",
    "Hiệp Thành": "Hiep Thanh",
    "Chánh Nghĩa": "Chanh Nghia",
    "Phú Tân": "Phu Tan",
    "Hòa Phú": "Hoa Phu",
}

PROPERTY_TYPES = ("dat_nen", "nha_dat", "nha_tro", "kho_xuong", "chung_cu")
DATA_CONTRACT_VERSION = "canonical-quality-actionable-v1"


def raw_listing_sql(alias: str = "l") -> str:
    """Visibility/source gate for raw crawl-volume counts.

    Reposts deliberately remain in this volume metric.
    """
    return " AND ".join(
        (
            f"{alias}.source = 'facebook'",
            f"COALESCE({alias}.is_blacklisted,0)=0",
            f"COALESCE({alias}.review_hidden,0)=0",
        )
    )


def canonical_quality_listing_sql(alias: str = "l") -> str:
    """Canonical baseline used by all price and supply statistics."""
    return " AND ".join(
        (
            raw_listing_sql(alias),
            f"{alias}.duplicate_of_id IS NULL",
            f"COALESCE({alias}.possibly_duplicate,0)=0",
            f"COALESCE({alias}.is_outlier,0)=0",
            f"COALESCE({alias}.probably_sold,0)=0",
        )
    )


def _ward_filter(alias: str, ward: str) -> tuple[str, list[str]]:
    values = [ward]
    alias_value = WARD_ALIASES.get(ward)
    if alias_value and alias_value not in values:
        values.append(alias_value)
    clause = "(" + " OR ".join(f"{alias}.ward = ?" for _ in values) + ")"
    return clause, values


def _period_filter(alias: str) -> str:
    return (
        f"{alias}.crawled_at IS NOT NULL "
        f"AND {alias}.crawled_at::timestamp >= ? "
        f"AND {alias}.crawled_at::timestamp < ?"
    )


def _scoped_where(
    ward: str,
    month_start: str,
    month_end: str,
    *,
    canonical: bool,
    alias: str = "l",
) -> tuple[str, list[Any]]:
    ward_sql, ward_params = _ward_filter(alias, ward)
    quality_sql = (
        canonical_quality_listing_sql(alias) if canonical else raw_listing_sql(alias)
    )
    return (
        f"{ward_sql} AND {quality_sql} AND {_period_filter(alias)}",
        [*ward_params, month_start, month_end],
    )


def actionable_count_query(
    ward: str,
    month_start: str,
    month_end: str,
    *,
    property_type: str | None = None,
) -> tuple[str, list[Any]]:
    where_sql, params = _scoped_where(
        ward,
        month_start,
        month_end,
        canonical=True,
    )
    type_sql = ""
    if property_type:
        type_sql = " AND l.property_type = ?"
        params.append(property_type)
    sql = f"""
WITH {LATEST_VALUATION_CTE}
SELECT COUNT(DISTINCT l.id)
FROM listings l
JOIN latest_valuation v ON v.listing_id = l.id
WHERE {where_sql}
  AND {actionable_listing_sql("l")}
  AND {actionable_signal_sql("v")}
  {type_sql}
"""
    return sql, params


def featured_records_query(
    ward: str,
    month_start: str,
    month_end: str,
    *,
    limit: int = 6,
) -> tuple[str, list[Any]]:
    where_sql, params = _scoped_where(
        ward,
        month_start,
        month_end,
        canonical=True,
    )
    sql = f"""
WITH {LATEST_VALUATION_CTE},
first_image AS (
    SELECT DISTINCT ON (listing_id) listing_id, local_path, img_url
    FROM listing_images
    ORDER BY listing_id, img_order NULLS LAST, id
)
SELECT l.id, l.title, l.property_type, l.price_ty, l.price_per_m2, l.area_m2,
       l.has_so, l.crawled_at, v.mos_pct, v.fair_ppm2, v.signal_score,
       img.local_path, img.img_url
FROM listings l
JOIN latest_valuation v ON v.listing_id = l.id
LEFT JOIN first_image img ON img.listing_id = l.id
WHERE {where_sql}
  AND {actionable_listing_sql("l")}
  AND {actionable_signal_sql("v")}
  AND l.property_type IN ('dat_nen', 'nha_dat')
  AND l.price_per_m2 IS NOT NULL AND l.price_per_m2 > 0 AND l.price_per_m2 < 500
  AND l.price_ty IS NOT NULL AND l.price_ty > 0 AND l.price_ty < 50
  AND l.area_m2 IS NOT NULL AND l.area_m2 >= 40 AND l.area_m2 <= 1000
  AND v.mos_pct IS NOT NULL
ORDER BY v.mos_pct DESC, v.signal_score DESC NULLS LAST, l.crawled_at DESC, l.id DESC
LIMIT ?
"""
    return sql, [*params, max(1, min(int(limit), 50))]


def _row_dict(row: Any, columns: tuple[str, ...]) -> dict:
    if hasattr(row, "keys"):
        return {key: row[key] for key in row.keys()}
    return dict(zip(columns, row))


def shape_featured_record(
    row: Any,
    *,
    image_resolver: Callable[..., str | None],
) -> dict:
    columns = (
        "id",
        "title",
        "property_type",
        "price_ty",
        "price_per_m2",
        "area_m2",
        "has_so",
        "crawled_at",
        "mos_pct",
        "fair_ppm2",
        "signal_score",
        "local_path",
        "img_url",
    )
    record = _row_dict(row, columns)
    listing_id = int(record["id"])
    return {
        "id": listing_id,
        "href": f"/listing/{listing_id}",
        "title": record.get("title"),
        "property_type": record.get("property_type"),
        "price_ty": record.get("price_ty"),
        "price_per_m2": record.get("price_per_m2"),
        "area_m2": record.get("area_m2"),
        "has_so": record.get("has_so"),
        "crawled_at": record.get("crawled_at"),
        "mos_pct": float(record["mos_pct"]),
        "fair_ppm2": record.get("fair_ppm2"),
        "signal_score": record.get("signal_score"),
        "image": image_resolver(
            record.get("local_path"),
            record.get("img_url"),
            prefer_thumb=True,
        ),
    }


def query_featured_records(
    conn,
    ward: str,
    month_start: str,
    month_end: str,
    *,
    image_resolver: Callable[..., str | None],
    limit: int = 6,
) -> list[dict]:
    sql, params = featured_records_query(
        ward,
        month_start,
        month_end,
        limit=limit,
    )
    rows = conn.execute(sql, params).fetchall()
    return [
        shape_featured_record(row, image_resolver=image_resolver)
        for row in rows
    ]


def _scalar(conn, sql: str, params: list[Any]) -> Any:
    row = conn.execute(sql, params).fetchone()
    return row[0] if row else None


def query_ward_stats(conn, ward: str, month_start: str, month_end: str) -> dict:
    """Return backward-compatible stats with explicit raw/basis/actionable counts."""
    raw_where, raw_params = _scoped_where(
        ward,
        month_start,
        month_end,
        canonical=False,
    )
    basis_where, basis_params = _scoped_where(
        ward,
        month_start,
        month_end,
        canonical=True,
    )
    raw_count = int(
        _scalar(conn, f"SELECT COUNT(*) FROM listings l WHERE {raw_where}", raw_params)
        or 0
    )
    basis_count = int(
        _scalar(
            conn,
            f"SELECT COUNT(*) FROM listings l WHERE {basis_where}",
            basis_params,
        )
        or 0
    )
    signal_sql, signal_params = actionable_count_query(
        ward,
        month_start,
        month_end,
    )
    actionable_count = int(_scalar(conn, signal_sql, signal_params) or 0)
    hot_count = int(
        _scalar(
            conn,
            f"SELECT COUNT(*) FROM listings l WHERE {basis_where} "
            "AND COALESCE(l.is_hot,0)=1",
            basis_params,
        )
        or 0
    )
    dropped_count = int(
        _scalar(
            conn,
            f"SELECT COUNT(*) FROM listings l WHERE {basis_where} "
            "AND COALESCE(l.price_dropped,0)=1",
            basis_params,
        )
        or 0
    )

    by_type: dict[str, dict] = {}
    for property_type in PROPERTY_TYPES:
        type_params = [*basis_params, property_type]
        row = conn.execute(
            f"""
SELECT COUNT(*) AS n,
       PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY l.price_per_m2::numeric)
           FILTER (WHERE l.price_per_m2::numeric > 0 AND l.price_per_m2::numeric < 500)
           AS median_m2,
       PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY l.price_ty::numeric)
           FILTER (WHERE l.price_ty::numeric > 0 AND l.price_ty::numeric < 50)
           AS median_ty,
       COUNT(*) FILTER (WHERE COALESCE(l.price_dropped,0)=1) AS dropped
FROM listings l
WHERE {basis_where}
  AND l.property_type = ?
  AND l.price_per_m2::numeric > 0
  AND l.price_per_m2::numeric < 500
""",
            type_params,
        ).fetchone()
        count = int(row[0] or 0) if row else 0
        if not count:
            continue
        type_signal_sql, type_signal_params = actionable_count_query(
            ward,
            month_start,
            month_end,
            property_type=property_type,
        )
        by_type[property_type] = {
            "count": count,
            "median_m2": round(float(row[1]), 1) if row[1] is not None else None,
            "median_ty": round(float(row[2]), 2) if row[2] is not None else None,
            "dropped": int(row[3] or 0),
            "signals": int(
                _scalar(conn, type_signal_sql, type_signal_params) or 0
            ),
        }

    return {
        "raw_total": raw_count,
        "basis_count": basis_count,
        "actionable_signal_count": actionable_count,
        "data_contract_version": DATA_CONTRACT_VERSION,
        # Compatibility for report formatting while copy migrates to explicit labels.
        "total": basis_count,
        "signals": actionable_count,
        "hot": hot_count,
        "dropped": dropped_count,
        "month_new": basis_count,
        "month_signals": actionable_count,
        "by_type": by_type,
    }
