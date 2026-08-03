"""Shared helpers for separating model signals from actionable signals."""
import math


DEFAULT_SIGNAL_MOS_MIN_PCT = 15.0
MOS_FILTER_MIN_PCT = 0.0
MOS_FILTER_MAX_PCT = 70.0
_MOS_FILTER_TIERS = frozenset({"vip", "admin"})


def effective_signal_mos_min(
    tier: str,
    requested_value=None,
    *,
    was_explicit: bool | None = None,
) -> float:
    """Return the user-facing MOS floor for one signal request."""
    if str(tier or "guest").strip().lower() not in _MOS_FILTER_TIERS:
        return DEFAULT_SIGNAL_MOS_MIN_PCT

    explicit = requested_value is not None if was_explicit is None else bool(was_explicit)
    if not explicit:
        return DEFAULT_SIGNAL_MOS_MIN_PCT

    try:
        value = float(requested_value)
    except (TypeError, ValueError):
        return DEFAULT_SIGNAL_MOS_MIN_PCT
    if not math.isfinite(value):
        return DEFAULT_SIGNAL_MOS_MIN_PCT
    return min(max(value, MOS_FILTER_MIN_PCT), MOS_FILTER_MAX_PCT)

ACTIONABLE_SUPPRESS_FLAGS = frozenset({
    "too_low_absolute_price",
    "missing_area_evidence",
    "area_dimension_conflict",
    "price_area_inconsistent",
    "unreprocessable_source_payload",
    "ambiguous_price_text",
    "source_category_conflict",
    "multi_lot_listing",
    "extreme_guland_ppm2",
    "suspicious_bait",
    "review_bad_valuation",
    "review_bad_extraction",
})

LATEST_VALUATION_CTE = """
latest_valuation AS MATERIALIZED (
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
    return not (flags & ACTIONABLE_SUPPRESS_FLAGS)


def actionable_signal_sql(alias: str = "v") -> str:
    flags_expr = f"COALESCE({alias}.source_quality_flags,'')"
    parts = [
        f"COALESCE({alias}.is_signal,0)=1",
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
