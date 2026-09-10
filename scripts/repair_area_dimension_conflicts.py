"""Repair listings whose structured area conflicts with labeled dimensions.

The command is dry-run by default. It re-normalizes raw source payloads first,
then optionally runs the deterministic listing and valuation refresh for only
the affected raw rows, followed by price-history and public-read-model updates.
"""

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cleansing.normalizer import normalize_record
from cleansing.reprocess import reprocess_listings, reprocess_valuation
from db.connection import advisory_lock, get_conn
from services.public_data_publish import publish_public_data


def _parse_listing_ids(raw: str | None) -> list[int]:
    if not raw:
        return []
    ids: list[int] = []
    for value in raw.split(","):
        try:
            listing_id = int(value.strip())
        except (TypeError, ValueError):
            continue
        if listing_id > 0:
            ids.append(listing_id)
    return list(dict.fromkeys(ids))


def _raw_payload(row) -> dict:
    value = row["raw_json"]
    if isinstance(value, Mapping):
        payload = dict(value)
    else:
        try:
            payload = json.loads(value or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            payload = {}
    if not isinstance(payload, dict):
        return {}

    payload.setdefault("source", row["source"])
    payload.setdefault("external_id", row["source_id"])
    payload.setdefault("url", row["raw_url"])
    return payload


def _area_changed(current, repaired) -> bool:
    if current is None or repaired is None:
        return False
    return abs(float(current) - float(repaired)) > max(1.0, abs(float(current)) * 0.05)


def _value_changed(current, repaired) -> bool:
    if current is None or repaired is None:
        return False
    return abs(float(current) - float(repaired)) > max(0.1, abs(float(current)) * 0.05)


def find_candidates(*, listing_ids: list[int], limit: int) -> list[dict]:
    with get_conn() as conn:
        params: list[int] = []
        where = """
            l.area_m2 >= 500
            OR v.actual_ppm2 IS NULL
            OR (
                v.actual_ppm2 > 0
                AND l.price_per_m2 > 0
                AND ABS(v.actual_ppm2 - l.price_per_m2) >
                    GREATEST(0.1, ABS(v.actual_ppm2) * 0.05)
            )
        """
        if listing_ids:
            placeholders = ",".join("?" for _ in listing_ids)
            where = f"l.id IN ({placeholders})"
            params.extend(listing_ids)
        params.append(limit)
        rows = conn.execute(
            f"""
            SELECT l.id AS listing_id, l.raw_id, l.area_m2 AS current_area_m2,
                   l.price_per_m2 AS current_price_per_m2,
                   v.actual_ppm2 AS current_valuation_actual_ppm2,
                   r.source, r.source_id, r.url AS raw_url, r.raw_json
            FROM listings l
            JOIN raw_listings r ON r.id = l.raw_id
            LEFT JOIN valuation_results v ON v.id = (
                SELECT vv.id
                FROM valuation_results vv
                WHERE vv.listing_id = l.id
                ORDER BY vv.computed_at DESC, vv.id DESC
                LIMIT 1
            )
            WHERE {where}
            ORDER BY l.id
            LIMIT ?
            """,
            tuple(params),
        ).fetchall()

    candidates: list[dict] = []
    for row in rows:
        raw = _raw_payload(row)
        if not raw:
            continue
        normalized = normalize_record(raw)
        if not normalized:
            continue
        area_changed = _area_changed(
            row["current_area_m2"], normalized.get("area_m2")
        )
        valuation_changed = _value_changed(
            row["current_valuation_actual_ppm2"], normalized.get("price_per_m2")
        )
        if not (listing_ids or area_changed or valuation_changed):
            continue
        candidates.append(
            {
                "listing_id": int(row["listing_id"]),
                "raw_id": int(row["raw_id"]),
                "source": row["source"],
                "title": (raw.get("title") or "")[:160],
                "current_area_m2": row["current_area_m2"],
                "repaired_area_m2": normalized.get("area_m2"),
                "current_price_per_m2": row["current_price_per_m2"],
                "current_valuation_actual_ppm2": row["current_valuation_actual_ppm2"],
                "repaired_price_per_m2": normalized.get("price_per_m2"),
                "price_ty": normalized.get("price_ty"),
                "measurement_provenance": normalized.get("measurement_provenance") or {},
                "repairs": list(normalized.get("_integrity_repairs") or ()),
                "quality_flags": normalized.get("extraction_quality_flags") or "",
            }
        )
    return candidates


def _refresh_price_history(conn, listing_ids: list[int]) -> int:
    if not listing_ids:
        return 0
    placeholders = ",".join("?" for _ in listing_ids)
    cursor = conn.execute(
        f"""
        UPDATE price_history ph
        SET price_per_m2 = ROUND((ph.price_ty * 1000.0 / l.area_m2)::numeric, 3)
        FROM listings l
        WHERE ph.listing_id = l.id
          AND ph.listing_id IN ({placeholders})
          AND ph.price_ty > 0
          AND l.area_m2 > 0
        """,
        tuple(listing_ids),
    )
    return max(0, int(cursor.rowcount or 0))


def repair(*, apply: bool, listing_ids: list[int], limit: int) -> dict:
    candidates = find_candidates(listing_ids=listing_ids, limit=limit)
    result: dict = {
        "dry_run": not apply,
        "candidate_count": len(candidates),
        "candidates": candidates,
    }
    if not apply or not candidates:
        return result

    raw_ids = [candidate["raw_id"] for candidate in candidates]
    with advisory_lock("reprocess"):
        listing_stats = reprocess_listings(raw_ids=raw_ids)
        processed_ids = list(
            dict.fromkeys(listing_stats.get("processed_ids") or [])
        )
        result["listings"] = listing_stats
        result["valuation"] = reprocess_valuation(
            incremental_ids=tuple(processed_ids)
        )
        with get_conn() as conn:
            result["price_history_rows_updated"] = _refresh_price_history(
                conn, processed_ids
            )
    result["processed_listing_ids"] = processed_ids

    if processed_ids:
        result["public_read_model"] = publish_public_data(
            listing_ids=tuple(processed_ids),
            strict=True,
        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Find and repair structured-area/dimension conflicts; dry-run by default."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Reprocess affected rows and refresh valuation/history/public read models.",
    )
    parser.add_argument(
        "--listing-ids",
        help="Comma-separated listing IDs to inspect; omit to scan listings with area >= 500m2.",
    )
    parser.add_argument("--limit", type=int, default=2000)
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("--limit must be positive")
    result = repair(
        apply=args.apply,
        listing_ids=_parse_listing_ids(args.listing_ids),
        limit=args.limit,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
