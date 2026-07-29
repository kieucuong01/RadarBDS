"""Repository helpers for deterministic, derived listing map locations."""
from __future__ import annotations

from collections.abc import Sequence

from db.connection import get_conn
from services.listing_location_resolver import ResolvedLocation


def _row_dict(row) -> dict:
    if hasattr(row, "items"):
        return dict(row.items())
    return dict(row)


def iter_location_candidates(
    listing_ids: Sequence[int] | None = None,
) -> list[dict]:
    """Load only inputs and existing fingerprints needed by the resolver."""
    params: list[int] = []
    where_sql = ""
    if listing_ids is not None:
        params = sorted({int(item) for item in listing_ids})
        if not params:
            return []
        placeholders = ",".join("?" for _ in params)
        where_sql = f"WHERE l.id IN ({placeholders})"

    with get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT l.id,
                   l.ward,
                   l.road_name,
                   NULL::DOUBLE PRECISION AS source_lat,
                   NULL::DOUBLE PRECISION AS source_lng,
                   ml.resolver_version AS existing_resolver_version,
                   ml.listing_location_signature AS existing_signature
            FROM listings l
            LEFT JOIN listing_map_locations ml
              ON ml.listing_id = l.id
            {where_sql}
            ORDER BY l.id
            """,
            params,
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
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NOW())
            ON CONFLICT (listing_id) DO UPDATE SET
                lat=EXCLUDED.lat,
                lng=EXCLUDED.lng,
                location_precision=EXCLUDED.location_precision,
                location_key=EXCLUDED.location_key,
                location_label=EXCLUDED.location_label,
                source=EXCLUDED.source,
                resolver_version=EXCLUDED.resolver_version,
                listing_location_signature=EXCLUDED.listing_location_signature,
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
