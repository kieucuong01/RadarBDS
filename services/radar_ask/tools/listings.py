"""Tier-safe listing facts, asking-price history, and canonical-lot history."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from ..contracts import EvidenceItem, SourceKind
from ..evidence import EvidenceBuilder, redact_evidence_text, stable_evidence_id
from ..registry import HistoryArgs, ListingFactsArgs, ToolContext
from .entities import _as_of, _read_context, _row_dict


LISTING_COLUMNS = """
    listing_id, source, title, ward, price_ty, price_per_m2, area_m2,
    property_type, frontage_m, depth_m, road_name, road_width_m,
    road_type, road_tier, tho_cu_m2, tho_cu_ratio, has_so,
    price_dropped, price_drop_pct, price_first_ty, possibly_duplicate,
    duplicate_of_id, measurement_provenance, extraction_quality_flags,
    suspicious_bait, public_visible, first_seen_at, last_seen_at,
    posted_at, crawled_at, is_active, probably_sold
"""


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _flags(value: Any) -> list[str]:
    if isinstance(value, (list, tuple)):
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


def _provenance(value: Any) -> dict[str, str]:
    if isinstance(value, dict):
        parsed = value
    else:
        try:
            parsed = json.loads(value or "{}")
        except (TypeError, ValueError):
            parsed = {}
    if not isinstance(parsed, dict):
        return {}
    return {
        str(key): str(item)
        for key, item in parsed.items()
        if str(key) in {"area_m2", "frontage_m", "depth_m", "tho_cu_m2", "road_width_m"}
    }


def _fetch_listing(listing_id: int, context: ToolContext) -> dict[str, Any] | None:
    with _read_context(context) as conn:
        cursor = conn.execute(
            f"""
            SELECT {LISTING_COLUMNS}
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
    if context.ask.tier != "admin" and not bool(row.get("public_visible")):
        return None
    return row


def _missing(question: str):
    return (
        EvidenceBuilder(question_snapshot=question)
        .missing("listing_not_found_or_not_visible")
        .build()
    )


def _listing_version(row: dict[str, Any]) -> tuple[datetime, str]:
    as_of = _as_of(row.get("last_seen_at") or row.get("crawled_at"))
    return as_of, f"listings:{as_of.isoformat(timespec='seconds')}"


def get_listing_facts(*, args: ListingFactsArgs, context: ToolContext):
    question = f"listing facts {args.listing_id}"
    row = _fetch_listing(args.listing_id, context)
    if row is None:
        return _missing(question)
    as_of, version = _listing_version(row)
    public_ref = f"radar-listing:{args.listing_id}"
    quality_flags = _flags(row.get("extraction_quality_flags"))
    if row.get("suspicious_bait"):
        quality_flags.append("suspicious_bait")
    facts = {
        "listing_ref": public_ref,
        "title": redact_evidence_text(str(row.get("title") or "")),
        "source": row.get("source") or "unknown",
        "ward": row.get("ward") or "unknown",
        "property_type": row.get("property_type") or "khac",
        "asking_price_ty": _number(row.get("price_ty")),
        "asking_price_per_m2_million": _number(row.get("price_per_m2")),
        "area_m2": _number(row.get("area_m2")),
        "frontage_m": _number(row.get("frontage_m")),
        "depth_m": _number(row.get("depth_m")),
        "road_name": row.get("road_name"),
        "road_width_m": _number(row.get("road_width_m")),
        "road_type": row.get("road_type"),
        "road_tier": int(row.get("road_tier") or 0),
        "tho_cu_m2": _number(row.get("tho_cu_m2")),
        "tho_cu_ratio": _number(row.get("tho_cu_ratio")),
        "has_so": bool(row.get("has_so")),
        "price_dropped": bool(row.get("price_dropped")),
        "price_drop_pct": _number(row.get("price_drop_pct")),
        "first_asking_price_ty": _number(row.get("price_first_ty")),
        "possibly_duplicate": bool(row.get("possibly_duplicate")),
        "measurement_provenance": _provenance(row.get("measurement_provenance")),
        "quality_flags": quality_flags,
    }
    item = EvidenceItem(
        evidence_id=stable_evidence_id("listing", public_ref, version),
        source_kind=SourceKind.LISTING,
        source_ref=public_ref,
        value=facts,
        as_of=as_of,
        dataset_version=version,
        quality_flags=quality_flags,
        provenance={"listing_id": str(args.listing_id), "method": "safe_listing_view"},
    )
    return (
        EvidenceBuilder(question_snapshot=question)
        .resolve(listing_ref=public_ref, ward=row.get("ward"))
        .warn("asking_price_not_transaction_price")
        .add(item)
        .build()
    )


def get_price_history(*, args: HistoryArgs, context: ToolContext):
    question = f"price history {args.listing_id}"
    root = _fetch_listing(args.listing_id, context)
    if root is None:
        return _missing(question)
    with _read_context(context) as conn:
        cursor = conn.execute(
            """
            SELECT price_history_id, listing_id, price_ty, price_per_m2, recorded_at
            FROM (
                SELECT price_history_id, listing_id, price_ty, price_per_m2, recorded_at
                FROM public.radar_ask_v_price_history
                WHERE listing_id=%s
                ORDER BY recorded_at DESC, price_history_id DESC
                LIMIT %s
            ) recent
            ORDER BY recorded_at, price_history_id
            """,
            (args.listing_id, args.limit),
        )
        raw_rows = cursor.fetchall()
    rows = sorted(
        (_row_dict(cursor, raw) for raw in raw_rows),
        key=lambda row: (_as_of(row.get("recorded_at")), int(row.get("price_history_id") or 0)),
    )
    if not rows:
        return (
            EvidenceBuilder(question_snapshot=question)
            .resolve(listing_ref=f"radar-listing:{args.listing_id}")
            .missing("price_history_not_found")
            .build()
        )
    builder = (
        EvidenceBuilder(question_snapshot=question, row_limit=args.limit)
        .resolve(listing_ref=f"radar-listing:{args.listing_id}")
        .warn("asking_price_not_transaction_price")
    )
    for row in rows:
        observed_at = _as_of(row.get("recorded_at"))
        version = f"price-history:{observed_at.isoformat(timespec='seconds')}"
        source_ref = (
            f"radar-listing:{args.listing_id}:asking-price:"
            f"{observed_at.isoformat(timespec='seconds')}"
        )
        builder.add(
            EvidenceItem(
                evidence_id=stable_evidence_id("price_history", source_ref, version),
                source_kind=SourceKind.PRICE_HISTORY,
                source_ref=source_ref,
                value={
                    "listing_ref": f"radar-listing:{args.listing_id}",
                    "asking_price_ty": _number(row.get("price_ty")),
                    "asking_price_per_m2_million": _number(row.get("price_per_m2")),
                    "observed_at": observed_at.isoformat(),
                },
                as_of=observed_at,
                dataset_version=version,
                provenance={"method": "bounded_price_history_view"},
            )
        )
    return builder.build()


def get_lot_history(*, args: HistoryArgs, context: ToolContext):
    question = f"lot history {args.listing_id}"
    root = _fetch_listing(args.listing_id, context)
    if root is None:
        return _missing(question)
    canonical_id = int(root.get("duplicate_of_id") or args.listing_id)
    with _read_context(context) as conn:
        cursor = conn.execute(
            """
            SELECT h.listing_id, h.canonical_lot_id, h.source, h.title, h.ward,
                   h.road_name, h.property_type, h.area_m2, h.frontage_m,
                   h.depth_m, h.price_ty, h.price_per_m2, h.price_first_ty,
                   h.first_seen_at, h.last_seen_at, h.posted_at, h.crawled_at,
                   h.is_active, l.public_visible
            FROM public.radar_ask_v_lot_history h
            JOIN public.radar_ask_v_listings l ON l.listing_id=h.listing_id
            WHERE h.canonical_lot_id=%s
              AND (%s OR l.public_visible)
            ORDER BY h.first_seen_at, h.crawled_at, h.listing_id
            LIMIT %s
            """,
            (canonical_id, context.ask.tier == "admin", args.limit),
        )
        raw_rows = cursor.fetchall()
    rows = sorted(
        (_row_dict(cursor, raw) for raw in raw_rows),
        key=lambda row: (
            _as_of(row.get("first_seen_at") or row.get("crawled_at")),
            int(row.get("listing_id") or 0),
        ),
    )
    if not rows:
        return (
            EvidenceBuilder(question_snapshot=question)
            .resolve(listing_ref=f"radar-listing:{args.listing_id}")
            .missing("lot_history_not_found")
            .build()
        )
    builder = (
        EvidenceBuilder(question_snapshot=question, row_limit=args.limit)
        .resolve(
            listing_ref=f"radar-listing:{args.listing_id}",
            canonical_lot_ref=f"radar-lot:{canonical_id}",
        )
        .warn("lot_identity_uses_stored_source_specific_dedup_policy")
    )
    for row in rows:
        listing_id = int(row["listing_id"])
        observed_at = _as_of(row.get("last_seen_at") or row.get("crawled_at"))
        version = f"lot-history:{observed_at.isoformat(timespec='seconds')}"
        source_ref = f"radar-lot:{canonical_id}:listing:{listing_id}"
        builder.add(
            EvidenceItem(
                evidence_id=stable_evidence_id("lot_history", source_ref, version),
                source_kind=SourceKind.LOT_HISTORY,
                source_ref=source_ref,
                value={
                    "listing_ref": f"radar-listing:{listing_id}",
                    "source": row.get("source") or "unknown",
                    "title": redact_evidence_text(str(row.get("title") or "")),
                    "ward": row.get("ward"),
                    "road_name": row.get("road_name"),
                    "property_type": row.get("property_type"),
                    "area_m2": _number(row.get("area_m2")),
                    "frontage_m": _number(row.get("frontage_m")),
                    "depth_m": _number(row.get("depth_m")),
                    "asking_price_ty": _number(row.get("price_ty")),
                    "asking_price_per_m2_million": _number(row.get("price_per_m2")),
                    "first_asking_price_ty": _number(row.get("price_first_ty")),
                    "first_seen_at": _as_of(row.get("first_seen_at")).isoformat(),
                    "last_seen_at": observed_at.isoformat(),
                    "is_active": bool(row.get("is_active")),
                },
                as_of=observed_at,
                dataset_version=version,
                provenance={"method": "stored_canonical_lot_identity"},
            )
        )
    return builder.calculate(observation_count=len(rows)).build()
