"""Read-only extraction-to-valuation integrity comparison."""
from __future__ import annotations

import json
import math
from collections import Counter
from datetime import date, datetime
from typing import Any, Iterable, Mapping

from analytics.valuation import (
    DEFAULT_BASELINE_SOURCES,
    TRAINING_WINDOW_LIMIT,
    SPECIAL_MARKET_SKIP_TYPES,
    SUPPLEMENTAL_BASELINE_SOURCE,
    SUPPLEMENTAL_GULAND_OLD_POST_DAYS,
    SUPPLEMENTAL_LARGE_LOT_AREA_M2,
    Listing,
    ValuationEngine,
)
from cleansing.normalizer import normalize_record
from cleansing.reprocess import _source_quality_flags
from db.connection import get_conn
from services.signal_quality import (
    ACTIONABLE_SUPPRESS_FLAGS,
    is_actionable_signal,
    split_quality_flags,
)


_MEASUREMENT_FIELDS = ("price_ty", "area_m2", "tho_cu_m2", "price_per_m2")


def build_integrity_report(limit: int | None = None) -> dict[str, Any]:
    """Compare current rows with deterministic re-normalization without writes."""
    params: list[Any] = []
    limit_clause = ""
    if limit is not None:
        bounded_limit = max(int(limit), 0)
        limit_clause = "LIMIT ?"
        params.append(bounded_limit)

    sql = f"""
        WITH latest_main AS MATERIALIZED (
            SELECT DISTINCT ON (listing_id)
                   id, listing_id, is_signal, mos_pct, source_quality_flags
            FROM valuation_results
            ORDER BY listing_id, computed_at DESC, id DESC
        ), latest_shadow AS MATERIALIZED (
            SELECT DISTINCT ON (listing_id)
                   id, listing_id, mos_pct
            FROM valuation_shadow_results
            ORDER BY listing_id, computed_at DESC, id DESC
        )
        SELECT
            l.id AS listing_id,
            l.raw_id,
            l.source,
            l.source_id,
            l.url,
            l.title,
            l.description,
            l.ward,
            l.property_type,
            l.tx_type,
            l.price_ty,
            l.area_m2,
            l.tho_cu_m2,
            l.price_per_m2,
            l.frontage_m,
            l.depth_m,
            l.road_tier,
            l.crawled_at,
            l.posted_at,
            l.suspicious_bait,
            l.probably_sold,
            l.is_blacklisted,
            l.review_hidden,
            l.duplicate_of_id,
            COALESCE(to_jsonb(l)->>'extraction_quality_flags', '')
                AS extraction_quality_flags,
            r.raw_json,
            r.source AS raw_source,
            r.source_id AS raw_source_id,
            r.url AS raw_url,
            r.crawled_at AS raw_crawled_at,
            CASE
              WHEN l.raw_id IS NULL THEN NULL
              WHEN r.id IS NOT NULL
               AND NULLIF(BTRIM(COALESCE((r.raw_json::jsonb)->>'title','')), '') IS NOT NULL
               AND NULLIF(BTRIM(COALESCE((r.raw_json::jsonb)->>'url', r.url, '')), '') IS NOT NULL
              THEN 1 ELSE 0
            END AS source_payload_reprocessable,
            m.id AS main_id,
            m.is_signal AS main_is_signal,
            m.mos_pct AS main_mos,
            m.source_quality_flags AS main_flags,
            s.id AS shadow_id,
            s.mos_pct AS shadow_mos,
            f.verdict AS feedback_verdict,
            f.extraction_verdict AS feedback_extraction_verdict,
            f.valuation_verdict AS feedback_valuation_verdict
        FROM listings l
        LEFT JOIN raw_listings r ON r.id=l.raw_id
        LEFT JOIN latest_main m ON m.listing_id=l.id
        LEFT JOIN latest_shadow s ON s.listing_id=l.id
        LEFT JOIN ai_training_feedback f ON f.id = (
            SELECT id FROM ai_training_feedback
            WHERE listing_id = l.id
            ORDER BY created_at DESC
            LIMIT 1
        )
        ORDER BY l.id
        {limit_clause}
    """
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()

    comparisons = [_compare_row(row) for row in rows]
    _resolve_training_membership(comparisons)
    return summarize_integrity_changes(comparisons)


def _compare_row(row) -> dict[str, Any]:
    current = _SafeRow({key: row[key] for key in row.keys()})
    raw_data = _json_object(current.get("raw_json"))
    raw_data.update({
        "raw_id": current.get("raw_id"),
        "source": current.get("raw_source") or current.get("source"),
        "source_id": current.get("raw_source_id") or current.get("source_id") or "",
        "external_id": current.get("raw_source_id") or current.get("source_id") or "",
        "url": current.get("raw_url") or current.get("url") or "",
        "crawled_at": current.get("raw_crawled_at") or "",
    })
    normalized = normalize_record(raw_data)

    current_quality_flags = set(_source_quality_flags(current))
    main_flags = split_quality_flags(current.get("main_flags"))
    old_flags = main_flags if current.get("main_id") is not None else current_quality_flags

    normalization_failed = current.get("raw_id") is not None and normalized is None
    normalized = normalized or {
        field: current.get(field) for field in _MEASUREMENT_FIELDS
    }
    new_record = _SafeRow(dict(current))
    new_record.update(normalized)
    new_quality_flags = set(_source_quality_flags(new_record))
    new_flags = set(new_quality_flags)

    is_signal = bool(current.get("main_is_signal"))
    old_actionable = is_actionable_signal({
        "is_signal": is_signal,
        "source_quality_flags": sorted(old_flags),
    })
    new_actionable = bool(
        _has_valuation_measurements(normalized)
        and is_actionable_signal({
            "is_signal": is_signal,
            "source_quality_flags": sorted(new_flags),
        })
    )

    changes = {}
    for field in _MEASUREMENT_FIELDS:
        old_value = _number(current.get(field))
        new_value = _number(normalized.get(field))
        if _values_differ(old_value, new_value):
            changes[field] = [old_value, new_value]

    training_before = _training_eligible(current, old_flags)
    training_after = _training_eligible(new_record, new_quality_flags)
    invariant_ok = (
        not new_actionable
        or (not normalization_failed and _canonical_ppm_invariant(normalized))
    )
    return {
        "listing_id": int(current["listing_id"]),
        "changes": changes,
        "repairs": list(normalized.get("_integrity_repairs") or ()),
        "old_flags": sorted(old_flags),
        "new_flags": sorted(new_flags),
        "is_signal": is_signal,
        "old_actionable": old_actionable,
        "new_actionable": new_actionable,
        "training_before": training_before,
        "training_after": training_after,
        "invariant_ok": invariant_ok,
        "main_present": current.get("main_id") is not None,
        "shadow_present": current.get("shadow_id") is not None,
        "main_mos": _number(current.get("main_mos")),
        "shadow_mos": _number(current.get("shadow_mos")),
        "normalization_failed": normalization_failed,
        "_training_context": {
            "before": dict(current),
            "after": dict(new_record),
        },
    }


def summarize_integrity_changes(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    rows = list(rows)
    field_changes: Counter[str] = Counter()
    repair_reasons: Counter[str] = Counter()
    suppressing_flags: Counter[str] = Counter()
    actionable = {"current": 0, "newly_suppressed": 0, "restored": 0}
    training_membership = {"added": 0, "removed": 0}
    models = {"main_count": 0, "shadow_count": 0, "mos_delta_ge_20": 0}
    invariant_violations_remaining = 0
    changed_samples: list[dict[str, Any]] = []

    for row in rows:
        changes = dict(row.get("changes") or {})
        field_changes.update(changes.keys())
        repair_reasons.update(str(reason) for reason in row.get("repairs") or ())

        new_flags = {
            str(flag).strip()
            for flag in row.get("new_flags") or ()
            if str(flag).strip()
        }
        suppressing_flags.update(new_flags & ACTIONABLE_SUPPRESS_FLAGS)

        old_actionable = bool(row.get("old_actionable"))
        new_actionable = bool(row.get("new_actionable"))
        actionable["current"] += int(old_actionable)
        actionable["newly_suppressed"] += int(old_actionable and not new_actionable)
        actionable["restored"] += int(not old_actionable and new_actionable)

        training_before = bool(row.get("training_before"))
        training_after = bool(row.get("training_after"))
        training_membership["added"] += int(not training_before and training_after)
        training_membership["removed"] += int(training_before and not training_after)

        main_present = bool(row.get("main_present", row.get("main_mos") is not None))
        shadow_present = bool(row.get("shadow_present", row.get("shadow_mos") is not None))
        models["main_count"] += int(main_present)
        models["shadow_count"] += int(shadow_present)
        main_mos = _number(row.get("main_mos"))
        shadow_mos = _number(row.get("shadow_mos"))
        large_mos_delta = bool(
            main_mos is not None
            and shadow_mos is not None
            and abs(main_mos - shadow_mos) >= 20.0
        )
        models["mos_delta_ge_20"] += int(large_mos_delta)

        invariant_ok = bool(row.get("invariant_ok", False))
        invariant_violations_remaining += int(not invariant_ok)

        is_changed = bool(
            changes
            or row.get("repairs")
            or set(row.get("old_flags") or ()) != new_flags
            or old_actionable != new_actionable
            or training_before != training_after
            or not invariant_ok
            or large_mos_delta
        )
        if is_changed:
            changed_samples.append(dict(row))

    changed_samples.sort(key=_sample_sort_key)
    return {
        "scanned": len(rows),
        "field_changes": dict(sorted(field_changes.items())),
        "repair_reasons": dict(sorted(repair_reasons.items())),
        "suppressing_flags": dict(sorted(suppressing_flags.items())),
        "actionable": actionable,
        "training_membership": training_membership,
        "models": models,
        "invariant_violations_remaining": invariant_violations_remaining,
        "samples": changed_samples[:50],
    }


class _SafeRow(dict):
    def __missing__(self, _key):
        return None


def _json_object(value) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}
    return dict(parsed) if isinstance(parsed, Mapping) else {}


def _training_eligible(row: Mapping[str, Any], flags: set[str]) -> bool:
    if (
        flags
        or (_number(row.get("price_per_m2")) or 0) <= 0
        or (_number(row.get("area_m2")) or 0) <= 0
        or _truthy_db_flag(row.get("probably_sold"))
        or _truthy_db_flag(row.get("is_blacklisted"))
        or _truthy_db_flag(row.get("review_hidden"))
        or row.get("duplicate_of_id") is not None
        or str(row.get("property_type") or "") in SPECIAL_MARKET_SKIP_TYPES
    ):
        return False

    source = str(row.get("source") or "").strip().lower()
    baseline_sources = {str(item).strip().lower() for item in DEFAULT_BASELINE_SOURCES}
    if not source or source in baseline_sources:
        return True
    if source != SUPPLEMENTAL_BASELINE_SOURCE:
        return False

    ward = str(row.get("ward") or "").strip().lower()
    price_ty = _number(row.get("price_ty")) or 0
    area_m2 = _number(row.get("area_m2")) or 0
    road_tier = _number(row.get("road_tier")) or 0
    if not ward or ward == "unknown" or price_ty <= 0:
        return False
    if area_m2 >= SUPPLEMENTAL_LARGE_LOT_AREA_M2 and road_tier <= 0:
        return False

    posted = _date_value(row.get("posted_at"))
    crawled = _date_value(row.get("crawled_at"))
    return not (
        posted
        and crawled
        and (crawled - posted).days >= SUPPLEMENTAL_GULAND_OLD_POST_DAYS
    )


def _resolve_training_membership(
    comparisons: list[dict[str, Any]],
) -> None:
    """Apply the engine's window, lot dedup, and source policy to report rows."""
    for phase, flag_key, result_key in (
        ("before", "old_flags", "training_before"),
        ("after", "new_flags", "training_after"),
    ):
        candidates = []
        for comparison in comparisons:
            context = comparison.get("_training_context") or {}
            record = _SafeRow(dict(context.get(phase) or {}))
            if _training_window_candidate(record):
                candidates.append((comparison, record))
        candidates.sort(
            key=lambda item: int(item[0].get("listing_id") or 0),
            reverse=True,
        )
        candidates = candidates[:TRAINING_WINDOW_LIMIT]
        listings = [
            _training_listing(
                record,
                set(comparison.get(flag_key) or ()),
            )
            for comparison, record in candidates
        ]
        member_ids = ValuationEngine().training_member_ids(listings)
        for comparison in comparisons:
            comparison[result_key] = int(comparison["listing_id"]) in member_ids

    for comparison in comparisons:
        comparison.pop("_training_context", None)


def _training_window_candidate(row: Mapping[str, Any]) -> bool:
    return bool(
        (_number(row.get("price_per_m2")) or 0) > 0
        and not _truthy_db_flag(row.get("probably_sold"))
        and not _truthy_db_flag(row.get("is_blacklisted"))
        and not _truthy_db_flag(row.get("review_hidden"))
    )


def _training_listing(
    row: Mapping[str, Any],
    flags: set[str],
) -> Listing:
    listing_id = int(row.get("listing_id") or row.get("id") or 0)
    duplicate_of_id = row.get("duplicate_of_id")
    return Listing(
        id=listing_id,
        area=str(row.get("area") or row.get("ward") or "unknown"),
        ward=str(row.get("ward") or "unknown"),
        property_type=str(row.get("property_type") or "khac"),
        tx_type=str(row.get("tx_type") or "ban"),
        price_per_m2=float(_number(row.get("price_per_m2")) or 0),
        price_total=float(_number(row.get("price_ty")) or 0),
        area_m2=float(_number(row.get("area_m2")) or 0),
        road_tier=int(_number(row.get("road_tier")) or 0),
        crawled_at=_date_value(row.get("crawled_at")),
        posted_at=_date_value(row.get("posted_at")),
        source=str(row.get("source") or ""),
        duplicate_of_id=(
            int(duplicate_of_id) if duplicate_of_id is not None else None
        ),
        exclude_from_baseline=bool(flags),
        source_quality_flags=tuple(sorted(flags)),
    )


def _truthy_db_flag(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _date_value(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _canonical_ppm_invariant(row: Mapping[str, Any]) -> bool:
    price_ty = _number(row.get("price_ty"))
    area_m2 = _number(row.get("area_m2"))
    price_per_m2 = _number(row.get("price_per_m2"))
    if price_ty is None or area_m2 is None or price_per_m2 is None:
        return True
    if price_ty <= 0 or area_m2 <= 0 or price_per_m2 <= 0:
        return False
    canonical = price_ty * 1000 / area_m2
    return math.isclose(canonical, price_per_m2, rel_tol=0.01, abs_tol=0.01)


def _has_valuation_measurements(row: Mapping[str, Any]) -> bool:
    return all(
        (_number(row.get(field)) or 0) > 0
        for field in ("price_ty", "area_m2", "price_per_m2")
    )


def _values_differ(old_value: float | None, new_value: float | None) -> bool:
    if old_value is None or new_value is None:
        return old_value is not new_value
    return not math.isclose(old_value, new_value, rel_tol=0.0001, abs_tol=0.001)


def _number(value) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _listing_sort_key(value) -> tuple[int, str]:
    try:
        return (0, f"{int(value):020d}")
    except (TypeError, ValueError):
        return (1, str(value or ""))


def _sample_sort_key(row: Mapping[str, Any]):
    old_actionable = bool(row.get("old_actionable"))
    new_actionable = bool(row.get("new_actionable"))
    training_before = bool(row.get("training_before"))
    training_after = bool(row.get("training_after"))
    old_flags = set(row.get("old_flags") or ())
    new_flags = set(row.get("new_flags") or ())
    main_mos = _number(row.get("main_mos"))
    shadow_mos = _number(row.get("shadow_mos"))
    if not bool(row.get("invariant_ok", False)):
        priority = 0
    elif old_actionable != new_actionable:
        priority = 1
    elif row.get("changes"):
        priority = 2
    elif training_before != training_after:
        priority = 3
    elif old_flags != new_flags:
        priority = 4
    elif (
        main_mos is not None
        and shadow_mos is not None
        and abs(main_mos - shadow_mos) >= 20.0
    ):
        priority = 5
    else:
        priority = 6
    return (priority, *_listing_sort_key(row.get("listing_id")))
