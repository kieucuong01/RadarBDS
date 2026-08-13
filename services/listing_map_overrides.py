"""Admin-verified map location overrides kept outside derived map data."""
from __future__ import annotations

import math
import re
from datetime import date, datetime
from decimal import Decimal
from urllib.parse import parse_qs, unquote, urlparse

from config.listing_map import LISTING_MAP_BOUNDS
from db.connection import get_conn


VALID_VERIFICATION_SOURCES = frozenset({
    "seller_confirmed",
    "site_visit",
    "google_maps",
    "document",
    "other",
})
GROUP_PRECISIONS = frozenset({"road", "landmark", "ward"})
_COORDINATE_PAIR_RE = re.compile(
    r"^\s*(?P<lat>-?\d{1,2}(?:\.\d+)?)\s*[,;]\s*"
    r"(?P<lng>-?\d{1,3}(?:\.\d+)?)\s*$"
)
_GOOGLE_AT_RE = re.compile(
    r"@(?P<lat>-?\d{1,2}(?:\.\d+)?),"
    r"(?P<lng>-?\d{1,3}(?:\.\d+)?)(?:,|$)"
)


class MapLocationOverrideError(ValueError):
    def __init__(self, code: str, status: int = 400):
        super().__init__(code)
        self.code = code
        self.status = status


def _row_dict(row) -> dict | None:
    if row is None:
        return None
    values = dict(row.items()) if hasattr(row, "items") else dict(row)
    for key, value in values.items():
        if isinstance(value, (date, datetime)):
            values[key] = value.isoformat()
        elif isinstance(value, Decimal):
            values[key] = float(value)
    return values


def _valid_point(lat: float, lng: float) -> bool:
    if not math.isfinite(lat) or not math.isfinite(lng):
        return False
    (south, west), (north, east) = LISTING_MAP_BOUNDS
    return south <= lat <= north and west <= lng <= east


def _is_google_host(host: str) -> bool:
    host = host.lower().split(":", 1)[0].rstrip(".")
    return (
        host == "google.com"
        or host.endswith(".google.com")
        or host == "goo.gl"
        or host.endswith(".goo.gl")
    )


def parse_coordinate_input(value: str) -> tuple[float, float]:
    """Parse a direct pair or a non-shortened Google Maps URL."""
    text = unquote(str(value or "").strip())
    direct = _COORDINATE_PAIR_RE.fullmatch(text)
    if direct:
        return float(direct.group("lat")), float(direct.group("lng"))

    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not _is_google_host(
        parsed.hostname or ""
    ):
        raise MapLocationOverrideError("coordinate_not_found")

    at_match = _GOOGLE_AT_RE.search(text)
    if at_match:
        return float(at_match.group("lat")), float(at_match.group("lng"))

    query = parse_qs(parsed.query)
    for key in ("query", "q", "ll"):
        for item in query.get(key, ()):
            match = _COORDINATE_PAIR_RE.fullmatch(unquote(item))
            if match:
                return float(match.group("lat")), float(match.group("lng"))
    raise MapLocationOverrideError("coordinate_not_found")


def validate_override_payload(payload: dict | None) -> dict:
    payload = payload if isinstance(payload, dict) else {}
    coordinate_input = str(payload.get("coordinate_input") or "").strip()
    parsed_point = parse_coordinate_input(coordinate_input) if coordinate_input else None
    try:
        lat = float(payload.get("lat"))
        lng = float(payload.get("lng"))
    except (TypeError, ValueError):
        if parsed_point is None:
            raise MapLocationOverrideError("invalid_coordinates") from None
        lat, lng = parsed_point
    if parsed_point is not None and (
        abs(lat - parsed_point[0]) > 0.000001
        or abs(lng - parsed_point[1]) > 0.000001
    ):
        raise MapLocationOverrideError("coordinate_mismatch")
    if not _valid_point(lat, lng):
        raise MapLocationOverrideError("coordinate_out_of_bounds")

    verification_source = str(
        payload.get("verification_source") or ""
    ).strip().lower()
    if verification_source not in VALID_VERIFICATION_SOURCES:
        raise MapLocationOverrideError("invalid_verification_source")
    note = str(payload.get("note") or "").strip()
    if not note:
        raise MapLocationOverrideError("note_required")
    note = note[:500]

    evidence_url = str(payload.get("evidence_url") or "").strip()[:1000]
    if evidence_url:
        parsed_url = urlparse(evidence_url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise MapLocationOverrideError("invalid_evidence_url")
    return {
        "lat": round(lat, 7),
        "lng": round(lng, 7),
        "verification_source": verification_source,
        "note": note,
        "evidence_url": evidence_url,
    }


def _load_group_override(conn, location_key: str) -> dict | None:
    return _row_dict(conn.execute(
        """
        SELECT location_key, lat, lng, verification_source, note,
               evidence_url, updated_by, active, created_at, updated_at
        FROM listing_map_group_overrides
        WHERE location_key = ?
        """,
        (location_key,),
    ).fetchone())


def _load_listing_override(conn, listing_id: int) -> dict | None:
    return _row_dict(conn.execute(
        """
        SELECT listing_id, lat, lng, verification_source, note,
               evidence_url, updated_by, active, created_at, updated_at
        FROM listing_map_listing_overrides
        WHERE listing_id = ?
        """,
        (listing_id,),
    ).fetchone())


def load_override_state(
    *,
    location_key: str = "",
    listing_id: int | None = None,
) -> dict:
    with get_conn() as conn:
        return {
            "group": (
                _load_group_override(conn, location_key)
                if location_key
                else None
            ),
            "listing": (
                _load_listing_override(conn, int(listing_id))
                if listing_id is not None
                else None
            ),
        }


def save_group_override(
    location_key: str,
    payload: dict,
    *,
    actor: str,
    audit_writer,
) -> dict:
    location_key = str(location_key or "").strip()
    if not location_key or len(location_key) > 240:
        raise MapLocationOverrideError("invalid_location_key")
    values = validate_override_payload(payload)
    with get_conn() as conn:
        target = conn.execute(
            """
            SELECT location_key, location_precision, location_label
            FROM listing_map_locations
            WHERE location_key = ?
            LIMIT 1
            """,
            (location_key,),
        ).fetchone()
        if not target:
            raise MapLocationOverrideError("location_not_found", 404)
        precision = str(target["location_precision"] or "")
        if precision not in GROUP_PRECISIONS:
            raise MapLocationOverrideError("invalid_group_precision")
        before = _load_group_override(conn, location_key)
        conn.execute(
            """
            INSERT INTO listing_map_group_overrides (
                location_key, lat, lng, verification_source, note,
                evidence_url, updated_by, active, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, TRUE, NOW(), NOW())
            ON CONFLICT (location_key) DO UPDATE SET
                lat=EXCLUDED.lat,
                lng=EXCLUDED.lng,
                verification_source=EXCLUDED.verification_source,
                note=EXCLUDED.note,
                evidence_url=EXCLUDED.evidence_url,
                updated_by=EXCLUDED.updated_by,
                active=TRUE,
                updated_at=NOW()
            """,
            (
                location_key,
                values["lat"],
                values["lng"],
                values["verification_source"],
                values["note"],
                values["evidence_url"],
                actor,
            ),
        )
        after = _load_group_override(conn, location_key) or {}
        audit_writer(
            conn,
            "map_location_group_override_upsert",
            "listing_map_group_override",
            None,
            before=before,
            after=after,
            reason=values["note"],
        )
    return after


def save_listing_override(
    listing_id: int,
    payload: dict,
    *,
    actor: str,
    audit_writer,
) -> dict:
    try:
        listing_id = int(listing_id)
    except (TypeError, ValueError):
        raise MapLocationOverrideError("invalid_listing_id") from None
    if listing_id <= 0:
        raise MapLocationOverrideError("invalid_listing_id")
    values = validate_override_payload(payload)
    with get_conn() as conn:
        listing = conn.execute(
            """
            SELECT id, title, ward, road_name
            FROM listings
            WHERE id = ?
            """,
            (listing_id,),
        ).fetchone()
        if not listing:
            raise MapLocationOverrideError("listing_not_found", 404)
        before = _load_listing_override(conn, listing_id)
        conn.execute(
            """
            INSERT INTO listing_map_listing_overrides (
                listing_id, lat, lng, verification_source, note,
                evidence_url, updated_by, active, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, TRUE, NOW(), NOW())
            ON CONFLICT (listing_id) DO UPDATE SET
                lat=EXCLUDED.lat,
                lng=EXCLUDED.lng,
                verification_source=EXCLUDED.verification_source,
                note=EXCLUDED.note,
                evidence_url=EXCLUDED.evidence_url,
                updated_by=EXCLUDED.updated_by,
                active=TRUE,
                updated_at=NOW()
            """,
            (
                listing_id,
                values["lat"],
                values["lng"],
                values["verification_source"],
                values["note"],
                values["evidence_url"],
                actor,
            ),
        )
        after = _load_listing_override(conn, listing_id) or {}
        audit_writer(
            conn,
            "map_location_listing_override_upsert",
            "listing_map_listing_override",
            listing_id,
            before=before,
            after=after,
            reason=values["note"],
        )
    return after


def reset_group_override(
    location_key: str,
    *,
    actor: str,
    audit_writer,
) -> dict:
    with get_conn() as conn:
        before = _load_group_override(conn, location_key)
        if not before or not before.get("active"):
            raise MapLocationOverrideError("override_not_found", 404)
        conn.execute(
            """
            UPDATE listing_map_group_overrides
            SET active=FALSE, updated_by=?, updated_at=NOW()
            WHERE location_key=?
            """,
            (actor, location_key),
        )
        after = _load_group_override(conn, location_key) or {}
        audit_writer(
            conn,
            "map_location_group_override_reset",
            "listing_map_group_override",
            None,
            before=before,
            after=after,
            reason="reset_to_automatic",
        )
    return after


def reset_listing_override(
    listing_id: int,
    *,
    actor: str,
    audit_writer,
) -> dict:
    listing_id = int(listing_id)
    with get_conn() as conn:
        before = _load_listing_override(conn, listing_id)
        if not before or not before.get("active"):
            raise MapLocationOverrideError("override_not_found", 404)
        conn.execute(
            """
            UPDATE listing_map_listing_overrides
            SET active=FALSE, updated_by=?, updated_at=NOW()
            WHERE listing_id=?
            """,
            (actor, listing_id),
        )
        after = _load_listing_override(conn, listing_id) or {}
        audit_writer(
            conn,
            "map_location_listing_override_reset",
            "listing_map_listing_override",
            listing_id,
            before=before,
            after=after,
            reason="reset_to_automatic",
        )
    return after
