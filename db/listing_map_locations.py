"""Repository helpers for deterministic, derived listing map locations."""
from __future__ import annotations

import json
import math
from collections.abc import Sequence

from db.connection import get_conn
from services.listing_location_resolver import ResolvedLocation


def _row_dict(row) -> dict:
    if hasattr(row, "items"):
        return dict(row.items())
    return dict(row)


def _source_coordinates(row: dict) -> tuple[float | None, float | None]:
    if str(row.get("source") or "") != "guland":
        return None, None
    try:
        raw = json.loads(row.get("raw_json") or "{}")
        lat = float(raw["source_lat"])
        lng = float(raw["source_lng"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None, None
    if not math.isfinite(lat) or not math.isfinite(lng):
        return None, None
    return lat, lng


def iter_location_candidates(
    listing_ids: Sequence[int] | None = None,
) -> list[dict]:
    """Load only inputs and existing fingerprints needed by the resolver."""
    params: list[int] = []
    where_parts = [
        "COALESCE(l.probably_sold, 0) = 0",
        "COALESCE(l.is_blacklisted, 0) = 0",
        "COALESCE(l.review_hidden, 0) = 0",
    ]
    if listing_ids is not None:
        params = sorted({int(item) for item in listing_ids})
        if not params:
            return []
        placeholders = ",".join("?" for _ in params)
        where_parts.append(f"l.id IN ({placeholders})")
    where_sql = "WHERE " + " AND ".join(where_parts)

    with get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT l.id,
                   l.title,
                   l.description,
                   l.ward,
                   l.road_name,
                   l.source,
                   r.raw_json,
                   ml.resolver_version AS existing_resolver_version,
                   ml.listing_location_signature AS existing_signature
            FROM listings l
            LEFT JOIN raw_listings r
              ON r.id = l.raw_id
            LEFT JOIN listing_map_locations ml
              ON ml.listing_id = l.id
            {where_sql}
            ORDER BY l.id
            """,
            params,
        ).fetchall()
    candidates = []
    for source_row in rows:
        row = _row_dict(source_row)
        row["source_lat"], row["source_lng"] = _source_coordinates(row)
        candidates.append(row)
    return candidates


def load_ward_fallback_listings(wards: Sequence[str]) -> list[dict]:
    """Load private text only for an in-process aggregate ward audit."""
    selected = sorted(
        {
            str(ward or "").strip()
            for ward in wards
            if str(ward or "").strip()
        }
    )
    if not selected:
        return []
    placeholders = ",".join("?" for _ in selected)
    with get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT l.id, l.title, l.description, l.road_name
            FROM listings l
            INNER JOIN listing_map_locations ml
              ON ml.listing_id = l.id
            WHERE l.ward IN ({placeholders})
              AND ml.location_precision = 'ward'
              AND COALESCE(l.probably_sold, 0) = 0
              AND COALESCE(l.is_blacklisted, 0) = 0
              AND COALESCE(l.review_hidden, 0) = 0
            ORDER BY l.id
            """,
            selected,
        ).fetchall()
    return [_row_dict(row) for row in rows]


def upsert_listing_map_locations(
    rows: Sequence[ResolvedLocation],
) -> int:
    """Insert or replace changed derived rows in one transaction."""
    rows = list(rows)
    if not rows:
        return 0
    values = [
        (
            row.listing_id,
            row.lat,
            row.lng,
            row.precision,
            row.location_key,
            row.location_label,
            row.source,
            row.resolver_version,
            row.signature,
            getattr(row, "accuracy_radius_m", None),
            getattr(row, "relation", ""),
            getattr(row, "reference_road", ""),
            getattr(row, "landmark_key", ""),
            getattr(row, "resolution_status", "resolved"),
            getattr(row, "resolution_reason", ""),
        )
        for row in rows
    ]
    with get_conn() as conn:
        conn.executemany(
            """
            INSERT INTO listing_map_locations (
                listing_id,
                lat,
                lng,
                location_precision,
                location_key,
                location_label,
                source,
                resolver_version,
                listing_location_signature,
                accuracy_radius_m,
                relation,
                reference_road,
                landmark_key,
                resolution_status,
                resolution_reason,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NOW())
            ON CONFLICT (listing_id) DO UPDATE SET
                lat=EXCLUDED.lat,
                lng=EXCLUDED.lng,
                location_precision=EXCLUDED.location_precision,
                location_key=EXCLUDED.location_key,
                location_label=EXCLUDED.location_label,
                source=EXCLUDED.source,
                resolver_version=EXCLUDED.resolver_version,
                listing_location_signature=EXCLUDED.listing_location_signature,
                accuracy_radius_m=EXCLUDED.accuracy_radius_m,
                relation=EXCLUDED.relation,
                reference_road=EXCLUDED.reference_road,
                landmark_key=EXCLUDED.landmark_key,
                resolution_status=EXCLUDED.resolution_status,
                resolution_reason=EXCLUDED.resolution_reason,
                updated_at=NOW()
            """,
            values,
        )
    return len(rows)


def delete_listing_map_locations(listing_ids: Sequence[int]) -> int:
    ids = sorted({int(item) for item in listing_ids})
    if not ids:
        return 0
    placeholders = ",".join("?" for _ in ids)
    with get_conn() as conn:
        cursor = conn.execute(
            f"""
            DELETE FROM listing_map_locations
            WHERE listing_id IN ({placeholders})
            """,
            ids,
        )
        return max(int(cursor.rowcount), 0)


def delete_stale_listing_map_locations(
    active_listing_ids: Sequence[int],
) -> int:
    ids = sorted({int(item) for item in active_listing_ids})
    with get_conn() as conn:
        if ids:
            placeholders = ",".join("?" for _ in ids)
            cursor = conn.execute(
                f"""
                DELETE FROM listing_map_locations
                WHERE listing_id NOT IN ({placeholders})
                """,
                ids,
            )
        else:
            cursor = conn.execute("DELETE FROM listing_map_locations")
        return max(int(cursor.rowcount), 0)
