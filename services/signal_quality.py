"""Shared helpers for separating model signals from actionable signals."""

ACTIONABLE_SUPPRESS_FLAGS = frozenset({
    "parsed_discount_as_price",
    "down_payment_as_price",
    "too_low_absolute_price",
    "large_lot_model_risk",
    "test_artifact",
    "area_dimension_conflict",
    "source_category_conflict",
    "multi_lot_listing",
    "guland_weak_signal",
    "guland_user_facing_risk",
    "old_guland_post",
    "extreme_guland_ppm2",
    "suspicious_bait",
    "guland_cluster_flood",
    "review_bad_valuation",
    "review_bad_extraction",
})

NON_BLOCKING_RECHECK_FLAGS = frozenset({
    "low_segment_confidence",
})


LATEST_VALUATION_CTE = """
latest_valuation AS (
    SELECT DISTINCT ON (vr.listing_id) vr.*
    FROM valuation_results vr
    ORDER BY vr.listing_id, vr.computed_at DESC, vr.id DESC
)
"""


def split_quality_flags(value) -> set[str]:
    if not value:
        return set()
    if isinstance(value, (list, tuple, set, frozenset)):
        return {str(v).strip() for v in value if str(v).strip()}
    return {part.strip() for part in str(value).split(",") if part.strip()}


def _row_value(row, key, default=None):
    if isinstance(row, dict):
        return row.get(key, default)
    try:
        return row[key]
    except Exception:
        return getattr(row, key, default)


def is_actionable_signal(row) -> bool:
    if not bool(_row_value(row, "is_signal", False)):
        return False
    flags = split_quality_flags(_row_value(row, "source_quality_flags", ""))
    if bool(_row_value(row, "source_quality_recheck", False)) and not (
        flags and flags <= NON_BLOCKING_RECHECK_FLAGS
    ):
        return False
    return not (flags & ACTIONABLE_SUPPRESS_FLAGS)


def actionable_signal_sql(alias: str = "v") -> str:
    flags_expr = f"COALESCE({alias}.source_quality_flags,'')"
    parts = [
        f"COALESCE({alias}.is_signal,0)=1",
        (
            f"(COALESCE({alias}.source_quality_recheck,0)=0 OR "
            f"({flags_expr} LIKE '%low_segment_confidence%'))"
        ),
    ]
    for flag in sorted(ACTIONABLE_SUPPRESS_FLAGS):
        parts.append(f"{flags_expr} NOT LIKE '%{flag}%'")
    return " AND ".join(parts)


def actionable_listing_sql(alias: str = "l", *, allow_price_drops: bool = False) -> str:
    parts = [
        f"COALESCE({alias}.probably_sold,0)=0",
        f"COALESCE({alias}.is_blacklisted,0)=0",
        f"COALESCE({alias}.review_hidden,0)=0",
    ]
    if allow_price_drops:
        parts.append(
            f"(COALESCE({alias}.possibly_duplicate,0)=0 OR COALESCE({alias}.price_dropped,0)=1)"
        )
    else:
        parts.append(f"COALESCE({alias}.possibly_duplicate,0)=0")
    return " AND ".join(parts)
