"""Focused persistence helpers for validated Guland source coordinates."""
from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from db.connection import get_conn
from services.market_data import get_city_for_ward


_COORDINATE_KEYS = (
    "source_lat",
    "source_lng",
    "source_coordinate_url",
    "source_coordinate_provider",
    "source_coordinate_captured_at",
)


class GulandCoordinateRepositoryError(ValueError):
    """Raised when a targeted raw row cannot be safely merged or restored."""


@dataclass(frozen=True)
class GulandCoordinateTarget:
    listing_id: int
    raw_id: int
    url: str
    source_id: str
    ward: str
    city: str
    context_text: str
    existing_coordinate_fields: Mapping[str, object]
    existing_map_precision: str
    raw_json_valid: bool


@dataclass(frozen=True)
class GulandCoordinateUpdate:
    raw_id: int
    listing_id: int
    fields: Mapping[str, object]


def _row_dict(row) -> dict:
    if hasattr(row, "items"):
        return dict(row.items())
    return dict(row)


def _parse_raw_json(value: object) -> dict:
    if isinstance(value, Mapping):
        raw = dict(value)
    else:
        try:
            raw = json.loads(str(value or ""))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise GulandCoordinateRepositoryError("malformed raw_json") from exc
    if not isinstance(raw, dict):
        raise GulandCoordinateRepositoryError("raw_json is not an object")
    return raw


def _coordinate_subset(raw: Mapping[str, object]) -> dict[str, object]:
    return {key: raw.get(key) for key in _COORDINATE_KEYS}


def _merge_fields(
    existing: dict,
    fields: Mapping[str, object],
) -> tuple[dict, bool]:
    previous = _coordinate_subset(existing)
    candidate = {key: fields.get(key) for key in _COORDINATE_KEYS}
    stable_keys = tuple(
        key
        for key in _COORDINATE_KEYS
        if key != "source_coordinate_captured_at"
    )
    if all(previous[key] == candidate[key] for key in stable_keys):
        candidate["source_coordinate_captured_at"] = previous[
            "source_coordinate_captured_at"
        ]
    if previous == candidate:
        return existing, False
    merged = dict(existing)
    for key in _COORDINATE_KEYS:
        if candidate[key] is None:
            merged.pop(key, None)
        else:
            merged[key] = candidate[key]
    return merged, True


def _restore_fields(
    current: dict,
    snapshot: Mapping[str, object],
) -> tuple[dict, bool]:
    restored = dict(current)
    for key in _COORDINATE_KEYS:
        value = snapshot.get(key)
        if value is None:
            restored.pop(key, None)
        else:
            restored[key] = value
    return restored, restored != current


def load_active_guland_coordinate_targets(
    *,
    conn_factory: Callable = get_conn,
) -> list[GulandCoordinateTarget]:
    with conn_factory() as conn:
        rows = conn.execute(
            """
            SELECT l.id AS listing_id,
                   l.raw_id,
                   l.url,
                   r.source_id,
                   l.ward,
                   l.title,
                   l.description,
                   r.raw_json,
                   ml.location_precision AS existing_map_precision
            FROM listings l
            JOIN raw_listings r ON r.id = l.raw_id
            LEFT JOIN listing_map_locations ml ON ml.listing_id = l.id
            WHERE l.source = 'guland'
              AND COALESCE(l.probably_sold, 0) = 0
              AND COALESCE(l.is_blacklisted, 0) = 0
              AND COALESCE(l.review_hidden, 0) = 0
              AND COALESCE(l.possibly_duplicate, 0) = 0
            ORDER BY l.id
            """
        ).fetchall()

    targets: list[GulandCoordinateTarget] = []
    for source_row in rows:
        row = _row_dict(source_row)
        raw_json_valid = True
        try:
            raw = _parse_raw_json(row.get("raw_json"))
        except GulandCoordinateRepositoryError:
            raw = {}
            raw_json_valid = False
        ward = str(row.get("ward") or "").strip()
        context_text = " ".join(filter(None, (
            str(row.get("title") or "").strip(),
            str(row.get("description") or "").strip(),
            str(raw.get("address") or "").strip(),
        )))
        targets.append(GulandCoordinateTarget(
            listing_id=int(row["listing_id"]),
            raw_id=int(row["raw_id"]),
            url=str(row.get("url") or ""),
            source_id=str(row.get("source_id") or ""),
            ward=ward,
            city=get_city_for_ward(ward),
            context_text=context_text,
            existing_coordinate_fields=(
                _coordinate_subset(raw) if raw_json_valid else {}
            ),
            existing_map_precision=str(
                row.get("existing_map_precision") or ""
            ),
            raw_json_valid=raw_json_valid,
        ))
    return targets


def merge_raw_coordinate_updates(
    updates: Sequence[GulandCoordinateUpdate],
    *,
    conn_factory: Callable = get_conn,
) -> list[int]:
    changed_listing_ids: set[int] = set()
    with conn_factory() as conn:
        for update in updates:
            row = conn.execute(
                """
                SELECT id, raw_json
                FROM raw_listings
                WHERE id = ? AND source = 'guland'
                """,
                (int(update.raw_id),),
            ).fetchall()
            if not row:
                raise GulandCoordinateRepositoryError(
                    f"missing Guland raw row {update.raw_id}"
                )
            raw = _parse_raw_json(_row_dict(row[0]).get("raw_json"))
            merged, changed = _merge_fields(raw, update.fields)
            if not changed:
                continue
            conn.execute(
                """
                UPDATE raw_listings
                SET raw_json = ?
                WHERE id = ? AND source = 'guland'
                """,
                (
                    json.dumps(merged, ensure_ascii=False),
                    int(update.raw_id),
                ),
            )
            changed_listing_ids.add(int(update.listing_id))
    return sorted(changed_listing_ids)


def snapshot_raw_coordinate_fields(
    raw_ids: Sequence[int],
    *,
    conn_factory: Callable = get_conn,
) -> list[dict[str, object]]:
    ids = sorted({int(raw_id) for raw_id in raw_ids})
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    with conn_factory() as conn:
        rows = conn.execute(
            f"""
            SELECT r.id AS raw_id,
                   l.id AS listing_id,
                   r.raw_json
            FROM raw_listings r
            JOIN listings l ON l.raw_id = r.id
            WHERE r.source = 'guland'
              AND r.id IN ({placeholders})
            ORDER BY r.id, l.id
            """,
            ids,
        ).fetchall()
    snapshots: list[dict[str, object]] = []
    for source_row in rows:
        row = _row_dict(source_row)
        raw = _parse_raw_json(row.get("raw_json"))
        snapshots.append({
            "raw_id": int(row["raw_id"]),
            "listing_id": int(row["listing_id"]),
            **_coordinate_subset(raw),
        })
    return snapshots


def restore_raw_coordinate_snapshot(
    rows: Sequence[Mapping[str, object]],
    *,
    conn_factory: Callable = get_conn,
) -> list[int]:
    changed_listing_ids: set[int] = set()
    with conn_factory() as conn:
        for snapshot in rows:
            raw_id = int(snapshot["raw_id"])
            listing_id = int(snapshot["listing_id"])
            current_rows = conn.execute(
                """
                SELECT id, raw_json
                FROM raw_listings
                WHERE id = ? AND source = 'guland'
                """,
                (raw_id,),
            ).fetchall()
            if not current_rows:
                raise GulandCoordinateRepositoryError(
                    f"missing Guland raw row {raw_id}"
                )
            current = _parse_raw_json(
                _row_dict(current_rows[0]).get("raw_json")
            )
            restored, changed = _restore_fields(current, snapshot)
            if not changed:
                continue
            conn.execute(
                """
                UPDATE raw_listings
                SET raw_json = ?
                WHERE id = ? AND source = 'guland'
                """,
                (json.dumps(restored, ensure_ascii=False), raw_id),
            )
            changed_listing_ids.add(listing_id)
    return sorted(changed_listing_ids)
