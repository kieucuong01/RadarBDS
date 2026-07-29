"""Isolated user reports for stale, incorrect, duplicate, or unsafe listings."""
from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any


REPORT_REASONS = frozenset(
    {
        "sold_or_unavailable",
        "wrong_price_or_area",
        "duplicate",
        "wrong_location",
        "spam_or_scam",
        "other",
    }
)
REPORT_STATUSES = frozenset({"pending", "reviewed", "dismissed"})


class ListingReportError(ValueError):
    def __init__(self, code: str, status: int):
        super().__init__(code)
        self.code = code
        self.status = status


@dataclass(frozen=True)
class ReportResult:
    report_id: int | None
    created: bool
    duplicate: bool


def _row_value(row: Any, key: str, default=None):
    if row is None:
        return default
    if hasattr(row, "get"):
        return row.get(key, default)
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return default


def _digest(secret: str, value: str) -> str:
    return hmac.new(
        secret.encode("utf-8"),
        value.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _normalized_request(payload: Any) -> tuple[str, str]:
    if not isinstance(payload, dict):
        raise ListingReportError("invalid_payload", 400)
    reason = payload.get("reason")
    reason = reason.strip() if isinstance(reason, str) else ""
    if reason not in REPORT_REASONS:
        raise ListingReportError("invalid_reason", 400)
    note = payload.get("note", "")
    note = note.strip() if isinstance(note, str) else ""
    if len(note) > 500:
        raise ListingReportError("invalid_note", 400)
    return reason, note


def submit_listing_report(
    conn,
    *,
    listing_id: int,
    payload: Any,
    actor: dict | None,
    request_meta: dict,
    secret: str,
    now: datetime | None = None,
) -> ReportResult:
    reason, note = _normalized_request(payload)
    if not isinstance(secret, str) or len(secret) < 8:
        raise ListingReportError("service_unavailable", 503)
    try:
        listing_id = int(listing_id)
    except (TypeError, ValueError):
        raise ListingReportError("listing_not_found", 404) from None
    if listing_id <= 0:
        raise ListingReportError("listing_not_found", 404)

    visible = conn.execute(
        """
        SELECT id
          FROM listings
         WHERE id=?
           AND COALESCE(is_blacklisted, 0)=0
           AND COALESCE(review_hidden, 0)=0
        """,
        (listing_id,),
    ).fetchone()
    if not visible:
        raise ListingReportError("listing_not_found", 404)

    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    ip = str((request_meta or {}).get("ip") or "").strip()[:64] or "unknown"
    user_agent = str((request_meta or {}).get("user_agent") or "").strip()[:200]
    actor_id = actor.get("id") if isinstance(actor, dict) else None
    reporter_identity = (
        f"user:{actor_id}"
        if actor_id is not None
        else f"guest:{ip}|{user_agent}"
    )
    reporter_hash = _digest(secret, reporter_identity)
    ip_hash = _digest(secret, ip)

    duplicate_after = (current_time - timedelta(hours=24)).isoformat()
    duplicate = conn.execute(
        """
        SELECT id
          FROM listing_reports
         WHERE listing_id=? AND reporter_key_hash=? AND created_at>=?
         ORDER BY created_at DESC
         LIMIT 1
        """,
        (listing_id, reporter_hash, duplicate_after),
    ).fetchone()
    if duplicate:
        return ReportResult(
            report_id=_row_value(duplicate, "id"),
            created=False,
            duplicate=True,
        )

    reporter_after = (current_time - timedelta(hours=1)).isoformat()
    reporter_count = conn.execute(
        """
        SELECT COUNT(*) AS count
          FROM listing_reports
         WHERE reporter_key_hash=? AND created_at>=?
        """,
        (reporter_hash, reporter_after),
    ).fetchone()
    if int(_row_value(reporter_count, "count", 0) or 0) >= 5:
        raise ListingReportError("rate_limited", 429)

    ip_after = (current_time - timedelta(days=1)).isoformat()
    ip_count = conn.execute(
        """
        SELECT COUNT(*) AS count
          FROM listing_reports
         WHERE ip_hash=? AND created_at>=?
        """,
        (ip_hash, ip_after),
    ).fetchone()
    if int(_row_value(ip_count, "count", 0) or 0) >= 20:
        raise ListingReportError("rate_limited", 429)

    cursor = conn.execute(
        """
        INSERT INTO listing_reports (
            listing_id, reason, note, reporter_key_hash, ip_hash,
            reporter_user_id, status, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
        """,
        (
            listing_id,
            reason,
            note or None,
            reporter_hash,
            ip_hash,
            actor_id,
            current_time.isoformat(),
        ),
    )
    return ReportResult(
        report_id=getattr(cursor, "lastrowid", None),
        created=True,
        duplicate=False,
    )


def list_listing_reports(conn, *, status: str = "pending", page: int = 1, limit: int = 50) -> dict:
    if status not in REPORT_STATUSES:
        raise ListingReportError("invalid_status", 400)
    page = max(1, int(page))
    limit = min(100, max(1, int(limit)))
    offset = (page - 1) * limit
    total_row = conn.execute(
        "SELECT COUNT(*) AS count FROM listing_reports WHERE status=?",
        (status,),
    ).fetchone()
    rows = conn.execute(
        """
        SELECT
            r.id, r.listing_id, r.reason, r.note, r.status,
            r.reporter_user_id, r.created_at, r.reviewed_at,
            l.title AS listing_title
          FROM listing_reports r
          JOIN listings l ON l.id = r.listing_id
         WHERE r.status=?
         ORDER BY r.created_at DESC, r.id DESC
         LIMIT ? OFFSET ?
        """,
        (status, limit, offset),
    ).fetchall()
    return {
        "items": [dict(row.items()) if hasattr(row, "items") else dict(row) for row in rows],
        "page": page,
        "limit": limit,
        "total": int(_row_value(total_row, "count", 0) or 0),
    }
