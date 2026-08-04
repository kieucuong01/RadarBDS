"""Deterministic valuation trace, comparable, and sample-quality evidence."""
from __future__ import annotations

import json
import math
import statistics
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from services.signal_quality import ACTIONABLE_SUPPRESS_FLAGS

from ..config import RadarAskSettings
from ..contracts import EvidenceItem, SourceKind
from ..evidence import EvidenceBuilder, stable_evidence_id
from ..registry import (
    ComparableArgs,
    ExplainValuationArgs,
    SampleQualityArgs,
    ToolContext,
)
from .entities import _as_of, _read_context, _row_dict


DETERMINISTIC_QUALITY_BLOCKERS = frozenset(ACTIONABLE_SUPPRESS_FLAGS) | frozenset(
    {
        "approximate_price_text",
        "missing_price_evidence",
        "invalid_price_per_m2",
        "invalid_area",
        "exclude_from_baseline",
    }
)
CONFIDENCE_WARNING_FLAGS = frozenset(
    {
        "low_segment_confidence",
        "low_road_confidence",
        "sparse_segment",
        "fallback_segment",
    }
)

VALUATION_LISTING_COLUMNS = """
    listing_id, title, source, ward, road_name, road_tier, property_type,
    price_ty, price_per_m2, area_m2, frontage_m, depth_m, has_so,
    possibly_duplicate, suspicious_bait, extraction_quality_flags,
    measurement_provenance, public_visible, crawled_at, last_seen_at
"""

LATEST_VALUATION_COLUMNS = """
    valuation_id, model_run_id, listing_id, fair_ppm2, actual_ppm2,
    mos_pct, is_signal, signal_score, segment, n_segment,
    source_quality_flags, source_quality_recheck, legal_status,
    trust_tier, trust_score, legal_flags, computed_at, valuation_trace
"""


def _settings() -> RadarAskSettings:
    return RadarAskSettings.from_env()


def _configure_timeout(conn, settings: RadarAskSettings | None = None) -> None:
    current = settings or _settings()
    conn.execute(
        "SELECT set_config('statement_timeout', %s, true)",
        (f"{current.statement_timeout_ms}ms",),
    )


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _flags(value: Any) -> list[str]:
    if isinstance(value, (list, tuple, set, frozenset)):
        candidates = value
    else:
        candidates = str(value or "").split(",")
    return sorted(
        {
            str(candidate).strip()
            for candidate in candidates
            if str(candidate).strip()
        }
    )[:20]


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        parsed = dict(value)
    else:
        try:
            parsed = json.loads(value or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
    return parsed if isinstance(parsed, dict) else {}


def _safe_measurement_provenance(value: Any) -> dict[str, str]:
    allowed = {"area_m2", "frontage_m", "depth_m", "tho_cu_m2", "road_width_m"}
    return {
        str(key): str(item)
        for key, item in _json_object(value).items()
        if str(key) in allowed
    }


def _public_trace(trace: Mapping[str, Any]) -> dict[str, Any]:
    """Keep the persisted arithmetic while converting DB IDs to public refs."""
    safe = dict(trace)
    comparable_ids = safe.pop("comparable_listing_ids", [])
    if isinstance(comparable_ids, (list, tuple)):
        safe["comparable_listing_refs"] = [
            f"radar-listing:{int(value)}"
            for value in comparable_ids[:20]
            if str(value).isdigit() and int(value) > 0
        ]
    return safe


def _fetch_listing(conn, listing_id: int, *, tier: str) -> dict[str, Any] | None:
    cursor = conn.execute(
        f"""
        /* radar_ask:valuation_listing */
        SELECT {VALUATION_LISTING_COLUMNS}
        FROM public.radar_ask_v_listings
        WHERE listing_id=%s
        LIMIT 1
        """,
        (listing_id,),
    )
    raw = cursor.fetchone()
    if raw is None:
        return None
    row = _row_dict(cursor, raw)
    if tier != "admin" and not bool(row.get("public_visible")):
        return None
    return row


def _fetch_latest_valuation(conn, listing_id: int) -> dict[str, Any] | None:
    cursor = conn.execute(
        f"""
        /* radar_ask:latest_valuation */
        SELECT {LATEST_VALUATION_COLUMNS}
        FROM public.radar_ask_v_valuations
        WHERE listing_id=%s
        ORDER BY computed_at DESC, valuation_id DESC
        LIMIT 1
        """,
        (listing_id,),
    )
    raw = cursor.fetchone()
    return _row_dict(cursor, raw) if raw is not None else None


def _missing_listing(question: str):
    return (
        EvidenceBuilder(question_snapshot=question)
        .missing("listing_not_found_or_not_visible")
        .build()
    )


def _market_row_eligible(row: Mapping[str, Any], *, tier: str) -> bool:
    if tier != "admin" and not bool(row.get("public_visible", True)):
        return False
    if bool(row.get("possibly_duplicate")) or row.get("duplicate_of_id"):
        return False
    if bool(row.get("suspicious_bait")):
        return False
    flags = set(_flags(row.get("extraction_quality_flags")))
    flags.update(_flags(row.get("source_quality_flags")))
    if flags & DETERMINISTIC_QUALITY_BLOCKERS:
        return False
    ppm2 = _number(row.get("price_per_m2"))
    area = _number(row.get("area_m2"))
    return bool(ppm2 and 0 < ppm2 < 1_000 and area and area > 0)


def _listing_quality_sql(alias: str = "") -> str:
    """Server-controlled SQL predicates applied before each bounded LIMIT."""
    prefix = f"{alias}." if alias else ""
    parts = [
        f"NOT COALESCE({prefix}possibly_duplicate,FALSE)",
        f"{prefix}duplicate_of_id IS NULL",
        f"NOT COALESCE({prefix}suspicious_bait,FALSE)",
        f"COALESCE({prefix}price_per_m2,0)>0",
        f"COALESCE({prefix}price_per_m2,0)<1000",
        f"COALESCE({prefix}area_m2,0)>0",
    ]
    parts.extend(
        f"COALESCE({prefix}extraction_quality_flags,'') NOT LIKE '%%{flag}%%'"
        for flag in sorted(DETERMINISTIC_QUALITY_BLOCKERS)
    )
    return " AND ".join(parts)


def _valuation_quality_sql(alias: str = "v") -> str:
    prefix = f"{alias}." if alias else ""
    return " AND ".join(
        f"COALESCE({prefix}source_quality_flags,'') NOT LIKE '%%{flag}%%'"
        for flag in sorted(DETERMINISTIC_QUALITY_BLOCKERS)
    )


def _percentile(values: list[float], ratio: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("percentile requires values")
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * ratio
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _asking_statistics(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    values = [
        value
        for row in rows
        if (value := _number(row.get("price_per_m2"))) is not None
    ]
    if not values:
        return {}
    return {
        "sample_count": len(values),
        "median_asking_ppm2_million": round(statistics.median(values), 2),
        "p25_asking_ppm2_million": round(_percentile(values, 0.25), 2),
        "p75_asking_ppm2_million": round(_percentile(values, 0.75), 2),
        "min_asking_ppm2_million": round(min(values), 2),
        "max_asking_ppm2_million": round(max(values), 2),
    }


def _valuation_item(
    listing: Mapping[str, Any],
    valuation: Mapping[str, Any],
    *,
    include_trace: bool,
) -> EvidenceItem:
    computed_at = _as_of(valuation.get("computed_at"))
    valuation_id = int(valuation.get("valuation_id") or 0)
    version = f"valuation:{valuation_id}:{computed_at.isoformat(timespec='seconds')}"
    trace = _json_object(valuation.get("valuation_trace"))
    fair_ppm2 = _number(valuation.get("fair_ppm2"))
    area_m2 = _number(listing.get("area_m2"))
    fair_total_ty = None
    if trace and _number(trace.get("final_fair_total")) is not None:
        fair_total_ty = round(float(trace["final_fair_total"]) / 1_000, 3)
    elif include_trace and fair_ppm2 is not None and area_m2 is not None:
        fair_total_ty = round(fair_ppm2 * area_m2 / 1_000, 3)
    value: dict[str, Any] = {
        "listing_ref": f"radar-listing:{int(listing['listing_id'])}",
        "asking_price_ty": _number(listing.get("price_ty")),
        "asking_price_per_m2_million": _number(listing.get("price_per_m2")),
        "fair_price_per_m2_million": fair_ppm2,
        "fair_total_ty": fair_total_ty,
        "mos_pct": _number(valuation.get("mos_pct")),
        "area_m2": area_m2,
        "frontage_m": _number(listing.get("frontage_m")),
        "depth_m": _number(listing.get("depth_m")),
        "measurement_provenance": _safe_measurement_provenance(
            listing.get("measurement_provenance")
        ),
        "sample_count": int(valuation.get("n_segment") or 0),
        "legal_status": valuation.get("legal_status") or "unverified",
        "trust_tier": valuation.get("trust_tier") or "candidate_signal",
    }
    if include_trace:
        value["trace"] = _public_trace(trace)
    return EvidenceItem(
        evidence_id=stable_evidence_id(
            "valuation", f"radar-valuation:{valuation_id}", version
        ),
        source_kind=SourceKind.VALUATION,
        source_ref=f"radar-valuation:{valuation_id}",
        value=value,
        unit="million_vnd_per_m2",
        calculation_method="persisted_deterministic_valuation_trace"
        if include_trace
        else "stored_valuation_snapshot_without_historical_trace",
        as_of=computed_at,
        dataset_version=version,
        model_version=str(trace.get("model_version") or "legacy_unknown"),
        sample_size=int(valuation.get("n_segment") or 0),
        provenance={
            "method": "latest_valuation_ordered_by_computed_at_and_id",
            "listing_id": str(listing["listing_id"]),
        },
        quality_flags=_flags(valuation.get("source_quality_flags")),
    )


def explain_valuation(*, args: ExplainValuationArgs, context: ToolContext):
    question = f"explain valuation {args.listing_id}"
    settings = _settings()
    with _read_context(context) as conn:
        _configure_timeout(conn, settings)
        listing = _fetch_listing(conn, args.listing_id, tier=context.ask.tier)
        if listing is None:
            return _missing_listing(question)
        valuation = _fetch_latest_valuation(conn, args.listing_id)
    if valuation is None:
        return (
            EvidenceBuilder(question_snapshot=question)
            .resolve(listing_ref=f"radar-listing:{args.listing_id}")
            .missing("valuation_not_found")
            .build()
        )

    trace = _json_object(valuation.get("valuation_trace"))
    builder = (
        EvidenceBuilder(question_snapshot=question, row_limit=settings.evidence_row_limit)
        .resolve(listing_ref=f"radar-listing:{args.listing_id}")
        .warn("asking_price_not_transaction_price")
        .warn("fair_value_is_model_estimate_not_transaction_price")
        .add(_valuation_item(listing, valuation, include_trace=bool(trace)))
    )
    if not trace:
        return (
            builder.warn("legacy_valuation_trace_unavailable")
            .missing("historical_valuation_trace")
            .build()
        )

    comparable_limit = min(5, settings.evidence_row_limit - 1)
    if comparable_limit >= 3:
        comparable_bundle = find_comparables(
            args=ComparableArgs(
                listing_id=args.listing_id,
                limit=comparable_limit,
                window_days=180,
            ),
            context=context,
        )
        for item in comparable_bundle.items:
            builder.add(item)
        if not comparable_bundle.items:
            builder.warn("valuation_comparables_not_currently_available")
        else:
            builder.warn("current_comparables_may_differ_from_historical_trace_inputs")
    return builder.calculate(
        trace_version=int(trace.get("trace_version") or 0),
        sample_count=int(trace.get("sample_count") or valuation.get("n_segment") or 0),
        comparable_count=len(trace.get("comparable_listing_ids") or []),
    ).build()


def _fetch_comparable_rows(
    conn,
    target: Mapping[str, Any],
    *,
    window_days: int,
    row_limit: int,
    tier: str = "free",
) -> list[dict[str, Any]]:
    visibility_sql = "" if tier == "admin" else "AND l.public_visible"
    cursor = conn.execute(
        f"""
        /* radar_ask:comparables */
        SELECT l.listing_id, l.title, l.source, l.ward, l.road_name,
               l.road_tier, l.property_type, l.price_ty, l.price_per_m2,
               l.area_m2, l.frontage_m, l.depth_m, l.has_so,
               l.possibly_duplicate, l.duplicate_of_id, l.suspicious_bait,
               l.extraction_quality_flags, l.public_visible,
               l.crawled_at, l.last_seen_at,
               v.valuation_id, v.fair_ppm2, v.mos_pct,
               v.source_quality_flags,
               v.computed_at AS valuation_computed_at
        FROM public.radar_ask_v_listings l
        LEFT JOIN LATERAL (
            SELECT valuation_id, fair_ppm2, mos_pct, source_quality_flags,
                   computed_at
            FROM public.radar_ask_v_valuations candidate_v
            WHERE candidate_v.listing_id=l.listing_id
            ORDER BY computed_at DESC, valuation_id DESC
            LIMIT 1
        ) v ON TRUE
        WHERE l.listing_id<>%s
          AND l.ward=%s
          AND l.property_type=%s
          {visibility_sql}
          AND {_listing_quality_sql('l')}
          AND {_valuation_quality_sql('v')}
          AND COALESCE(l.last_seen_at, l.crawled_at)::timestamptz
              >= NOW() - (%s * INTERVAL '1 day')
        ORDER BY
          CASE WHEN LOWER(COALESCE(l.road_name,''))=LOWER(%s) THEN 0 ELSE 1 END,
          CASE WHEN COALESCE(l.road_tier,0)=%s THEN 0 ELSE 1 END,
          ABS(COALESCE(l.area_m2,0)-%s),
          COALESCE(l.last_seen_at,l.crawled_at) DESC,
          l.listing_id DESC
        LIMIT %s
        """,
        (
            int(target["listing_id"]),
            target.get("ward"),
            target.get("property_type"),
            window_days,
            target.get("road_name") or "",
            int(target.get("road_tier") or 0),
            _number(target.get("area_m2")) or 0,
            row_limit,
        ),
    )
    return [_row_dict(cursor, raw) for raw in cursor.fetchall()]


def find_comparables(*, args: ComparableArgs, context: ToolContext):
    question = f"comparables {args.listing_id}"
    settings = _settings()
    query_limit = min(settings.evidence_row_limit, max(args.limit * 4, args.limit))
    with _read_context(context) as conn:
        _configure_timeout(conn, settings)
        target = _fetch_listing(conn, args.listing_id, tier=context.ask.tier)
        if target is None:
            return _missing_listing(question)
        raw_rows = _fetch_comparable_rows(
            conn,
            target,
            window_days=args.window_days,
            row_limit=query_limit,
            tier=context.ask.tier,
        )
    evidence_limit = min(args.limit, settings.evidence_row_limit)
    eligible = [
        row for row in raw_rows if _market_row_eligible(row, tier=context.ask.tier)
    ][:evidence_limit]
    if not eligible:
        return (
            EvidenceBuilder(question_snapshot=question)
            .resolve(listing_ref=f"radar-listing:{args.listing_id}")
            .missing("eligible_comparables_not_found")
            .build()
        )

    builder = (
        EvidenceBuilder(question_snapshot=question, row_limit=evidence_limit)
        .resolve(
            listing_ref=f"radar-listing:{args.listing_id}",
            ward=target.get("ward"),
            road=target.get("road_name"),
        )
        .warn("comparable_prices_are_asking_prices_not_transactions")
    )
    for row in eligible:
        listing_id = int(row["listing_id"])
        listing_as_of = _as_of(row.get("last_seen_at") or row.get("crawled_at"))
        valuation_as_of = (
            _as_of(row.get("valuation_computed_at"))
            if row.get("valuation_computed_at")
            else None
        )
        as_of = min(listing_as_of, valuation_as_of) if valuation_as_of else listing_as_of
        version = (
            f"listing-comparable:{listing_as_of.isoformat(timespec='seconds')}:"
            f"valuation:{valuation_as_of.isoformat(timespec='seconds') if valuation_as_of else 'none'}"
        )
        source_ref = f"radar-listing:{listing_id}:comparable"
        builder.add(
            EvidenceItem(
                evidence_id=stable_evidence_id("comparable", source_ref, version),
                source_kind=SourceKind.COMPARABLE,
                source_ref=source_ref,
                value={
                    "listing_ref": f"radar-listing:{listing_id}",
                    "ward": row.get("ward"),
                    "road_name": row.get("road_name"),
                    "road_tier": int(row.get("road_tier") or 0),
                    "property_type": row.get("property_type"),
                    "asking_price_ty": _number(row.get("price_ty")),
                    "asking_price_per_m2_million": _number(row.get("price_per_m2")),
                    "fair_price_per_m2_million": _number(row.get("fair_ppm2")),
                    "mos_pct": _number(row.get("mos_pct")),
                    "area_m2": _number(row.get("area_m2")),
                    "frontage_m": _number(row.get("frontage_m")),
                    "depth_m": _number(row.get("depth_m")),
                    "listing_as_of": listing_as_of.isoformat(),
                    "valuation_as_of": valuation_as_of.isoformat()
                    if valuation_as_of
                    else None,
                },
                unit="million_vnd_per_m2",
                calculation_method="bounded_similarity_order_from_safe_views",
                as_of=as_of,
                dataset_version=version,
                provenance={"method": "ward_type_road_area_recency_similarity"},
                quality_flags=_flags(row.get("source_quality_flags")),
            )
        )
    stats = _asking_statistics(eligible)
    return builder.calculate(
        metric="asking_price_per_m2",
        window_days=args.window_days,
        **stats,
    ).build()


def check_sample_quality(*, args: SampleQualityArgs, context: ToolContext):
    question = f"valuation sample quality {args.listing_id}"
    settings = _settings()
    with _read_context(context) as conn:
        _configure_timeout(conn, settings)
        listing = _fetch_listing(conn, args.listing_id, tier=context.ask.tier)
        if listing is None:
            return _missing_listing(question)
        valuation = _fetch_latest_valuation(conn, args.listing_id)
    if valuation is None:
        return (
            EvidenceBuilder(question_snapshot=question)
            .missing("valuation_not_found")
            .build()
        )

    trace = _json_object(valuation.get("valuation_trace"))
    sample_count = int(trace.get("sample_count") or valuation.get("n_segment") or 0)
    all_flags = set(_flags(valuation.get("source_quality_flags")))
    all_flags.update(_flags(trace.get("quality_flags")))
    blocking = sorted(all_flags & DETERMINISTIC_QUALITY_BLOCKERS)
    warnings = sorted(all_flags & CONFIDENCE_WARNING_FLAGS)
    fallback_reason = trace.get("fallback_reason")
    if fallback_reason:
        warnings.append("valuation_fallback_used")

    if blocking or sample_count < 3:
        quality = "unusable"
    elif sample_count < 5 or warnings:
        quality = "usable_with_caution"
    else:
        quality = "sufficient"

    builder = (
        EvidenceBuilder(question_snapshot=question)
        .resolve(listing_ref=f"radar-listing:{args.listing_id}")
        .add(_valuation_item(listing, valuation, include_trace=bool(trace)))
        .calculate(
            quality=quality,
            sample_count=sample_count,
            blocking_flags=blocking,
            warning_flags=sorted(set(warnings)),
            fallback_reason=fallback_reason,
        )
    )
    for warning in sorted(set(warnings)):
        builder.warn(warning)
    if blocking:
        builder.warn("deterministic_quality_blockers_present")
    if sample_count < 3:
        builder.warn("insufficient_sample_count")
    return builder.build()
