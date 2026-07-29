"""Persistence for unresolved and resolved map-location candidates."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import json

from db.connection import get_conn


_VALID_STATUSES = frozenset({"resolved", "ambiguous", "not_found", "invalid"})
_MAX_SAMPLE_IDS = 10
_MAX_LOAD_LIMIT = 1000


@dataclass(frozen=True)
class CoverageRow:
    candidate_key: str
    city: str
    ward: str = ""
    road_candidate: str = ""
    landmark_candidate: str = ""
    relation: str = ""
    status: str = "not_found"
    affected_listing_count: int = 0
    sample_listing_ids: tuple[int, ...] = ()
    resolution_note: str = ""


def _bounded_text(value: object, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _validated_status(value: str, *, allow_empty: bool = False) -> str:
    status = str(value or "").strip().lower()
    if allow_empty and not status:
        return ""
    if status not in _VALID_STATUSES:
        raise ValueError(f"invalid map coverage status: {value!r}")
    return status


def _sample_json(values: Sequence[int]) -> str:
    sample_ids = sorted({int(value) for value in values if int(value) > 0})
    return json.dumps(sample_ids[:_MAX_SAMPLE_IDS])


def upsert_listing_location_coverage(rows: Sequence[CoverageRow]) -> int:
    """Upsert bounded aggregate candidates without exposing listing content."""
    prepared = []
    for row in rows:
        candidate_key = _bounded_text(row.candidate_key, 240)
        city = _bounded_text(row.city, 120)
        if not candidate_key or not city:
            raise ValueError("candidate_key and city are required")
        status = _validated_status(row.status)
        prepared.append(
            (
                candidate_key,
                city,
                _bounded_text(row.ward, 120),
                _bounded_text(row.road_candidate, 160),
                _bounded_text(row.landmark_candidate, 160),
                _bounded_text(row.relation, 24),
                status,
                max(int(row.affected_listing_count), 0),
                _sample_json(row.sample_listing_ids),
                _bounded_text(row.resolution_note, 500),
            )
        )

    if not prepared:
        return 0
    prepared.sort(key=lambda item: item[0])
    with get_conn() as conn:
        conn.executemany(
            """
            INSERT INTO listing_map_location_coverage (
                candidate_key,
                city,
                ward,
                road_candidate,
                landmark_candidate,
                relation,
                status,
                affected_listing_count,
                sample_listing_ids,
                resolution_note
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?::jsonb, ?)
            ON CONFLICT (candidate_key) DO UPDATE SET
                city=EXCLUDED.city,
                ward=EXCLUDED.ward,
                road_candidate=EXCLUDED.road_candidate,
                landmark_candidate=EXCLUDED.landmark_candidate,
                relation=EXCLUDED.relation,
                status=EXCLUDED.status,
                affected_listing_count=EXCLUDED.affected_listing_count,
                sample_listing_ids=EXCLUDED.sample_listing_ids,
                first_seen_at=listing_map_location_coverage.first_seen_at,
                last_seen_at=NOW(),
                resolution_note=EXCLUDED.resolution_note
            """,
            prepared,
        )
    return len(prepared)


def load_listing_location_coverage(
    status: str = "",
    limit: int = 100,
) -> list[dict]:
    """Load a bounded deterministic coverage queue for internal operations."""
    selected_status = _validated_status(status, allow_empty=True)
    bounded_limit = min(max(int(limit), 1), _MAX_LOAD_LIMIT)
    where_sql = ""
    params: list[object] = []
    if selected_status:
        where_sql = "WHERE status = ?"
        params.append(selected_status)
    params.append(bounded_limit)

    with get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT candidate_key,
                   city,
                   ward,
                   road_candidate,
                   landmark_candidate,
                   relation,
                   status,
                   affected_listing_count,
                   sample_listing_ids,
                   first_seen_at,
                   last_seen_at,
                   resolution_note
            FROM listing_map_location_coverage
            {where_sql}
            ORDER BY affected_listing_count DESC, candidate_key
            LIMIT ?
            """,
            params,
        ).fetchall()
    return [dict(row.items()) if hasattr(row, "items") else dict(row) for row in rows]
