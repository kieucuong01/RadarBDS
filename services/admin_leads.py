"""Lead capture and admin CRM service helpers."""
from __future__ import annotations

import csv
import io
import logging
from typing import Callable

from config import database_sqlite as db_mod
from auth.core import normalize_identifier
from db.moderation import normalize_phone

logger = logging.getLogger(__name__)

LEAD_STATUSES = {"new", "called", "viewing", "deposit", "cancelled"}


def resolve_lead_ack_email(conn, user_id: int | None, guest_email: str | None) -> str | None:
    if guest_email and "@" in guest_email:
        return guest_email
    if user_id:
        row = conn.execute("SELECT email FROM users WHERE id=?", (user_id,)).fetchone()
        if row and row["email"] and "@" in (row["email"] or ""):
            return row["email"]
    return None


def send_lead_ack_safe(
    conn,
    lead_id: int,
    listing_id,
    user_id: int | None,
    guest_name: str | None,
    guest_email: str | None,
) -> None:
    """Send lead acknowledgement email; mark notify_email_sent_at. Never raises."""
    try:
        from alerts.email import send_lead_ack

        to_email = resolve_lead_ack_email(conn, user_id, guest_email)
        if not to_email:
            return
        listing_title = None
        if listing_id is not None:
            row = conn.execute("SELECT title FROM listings WHERE id=?", (listing_id,)).fetchone()
            listing_title = row["title"] if row else None
        if send_lead_ack(to_email, guest_name, listing_title, listing_id):
            conn.execute(
                "UPDATE lead_captures SET notify_email_sent_at=datetime('now') WHERE id=?",
                (lead_id,),
            )
    except Exception as exc:
        logger.warning("lead ack email failed lead_id=%s: %s", lead_id, exc)


def create_lead(payload: dict, *, tier: str, user: dict | None, audit_log_fn: Callable) -> tuple[dict, int]:
    listing_id = payload.get("listing_id")
    listing_url = (payload.get("listing_url") or "").strip()
    source_context = (payload.get("source_context") or "signal").strip()[:50]
    note = (payload.get("note") or "").strip()[:500]
    phone_raw = (payload.get("zalo_phone") or "").strip()
    phone_norm = normalize_phone(phone_raw)
    urgency = (payload.get("urgency") or "standard").strip()[:20]
    if urgency not in ("standard", "urgent"):
        urgency = "standard"

    if not phone_norm or len(phone_norm) < 9:
        return {"ok": False, "error": "invalid_phone"}, 400

    user_id = user["id"] if user else None
    if tier in ("vip", "admin"):
        urgency = "urgent"

    with db_mod.get_conn() as conn:
        if listing_id is not None:
            row = conn.execute("SELECT id, url FROM listings WHERE id=?", (listing_id,)).fetchone()
            if not row:
                return {"ok": False, "error": "listing_not_found"}, 404
            listing_url = listing_url or row["url"] or ""

        cur = conn.execute("""
            INSERT INTO lead_captures (listing_id, listing_url, zalo_phone, source_context, note, status,
                                       user_id, tier, urgency)
            VALUES (?, ?, ?, ?, ?, 'new', ?, ?, ?)
        """, (listing_id, listing_url, phone_norm, source_context, note, user_id, tier, urgency))
        lead_id = cur.lastrowid
        send_lead_ack_safe(conn, lead_id, listing_id, user_id, None, None)

    audit_log_fn(
        user_id=user_id,
        tier=tier,
        action="lead_capture",
        listing_id=listing_id,
        context={"urgency": urgency, "source_context": source_context},
    )
    return {"ok": True, "lead_id": lead_id}, 200


def create_guest_lead(payload: dict, *, tier: str, user: dict | None, audit_log_fn: Callable) -> tuple[dict, int]:
    listing_id = payload.get("listing_id")
    contact_raw = (payload.get("contact") or "").strip()
    note = (payload.get("note") or "").strip()[:500]
    context_ctx = (payload.get("context") or "card_signal").strip()[:50]

    norm = normalize_identifier(contact_raw)
    if not norm or norm[1] != "phone":
        return {"ok": False, "error": "invalid_phone"}, 400
    ident, ident_type = norm

    user_id = user["id"] if user else None
    urgency = "urgent" if tier in ("vip", "admin") else ("standard" if tier == "free" else "guest")

    listing_url = (payload.get("listing_url") or "").strip()[:500]
    with db_mod.get_conn() as conn:
        if listing_id is not None:
            row = conn.execute("SELECT id, url FROM listings WHERE id=?", (listing_id,)).fetchone()
            if not row:
                return {"ok": False, "error": "listing_not_found"}, 404
            listing_url = row["url"] or ""

        if not note:
            lot_ref = f"#{listing_id}" if listing_id is not None else "này"
            note = f"Tôi quan tâm lô {lot_ref}, hãy gửi thêm thông tin."
        if tier in ("vip", "admin") and "1-1" not in note:
            note = f"{note} Tôi muốn được tư vấn và phân tích 1-1 với chuyên gia."

        cur = conn.execute("""
            INSERT INTO lead_captures (
                listing_id, listing_url, zalo_phone, source_context, note, status,
                user_id, tier, urgency, guest_name, guest_email
            ) VALUES (?, ?, ?, ?, ?, 'new', ?, ?, ?, ?, ?)
        """, (
            listing_id,
            listing_url,
            ident,
            context_ctx,
            note,
            user_id,
            tier,
            urgency,
            None,
            None,
        ))
        lead_id = cur.lastrowid
        send_lead_ack_safe(conn, lead_id, listing_id, user_id, None, None)

    audit_log_fn(
        user_id=user_id,
        tier=tier,
        action="lead_capture_guest",
        listing_id=listing_id,
        context={"contact_type": ident_type, "urgency": urgency, "source_context": context_ctx},
    )
    return {"ok": True, "lead_id": lead_id}, 200


def _lead_filter(status: str, q: str) -> tuple[str, list]:
    where = []
    params = []
    if status in LEAD_STATUSES:
        where.append("lc.status = ?")
        params.append(status)
    if q:
        like = f"%{q}%"
        where.append("""(
            lc.zalo_phone LIKE ?
            OR CAST(lc.listing_id AS TEXT) LIKE ?
            OR COALESCE(l.title, '') LIKE ?
            OR COALESCE(l.ward, '') LIKE ?
            OR COALESCE(lc.listing_url, '') LIKE ?
        )""")
        params.extend([like, like, like, like, like])
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    return where_sql, params


def list_leads(status: str = "", q: str = "") -> dict:
    where_sql, params = _lead_filter(status, q)
    with db_mod.get_conn() as conn:
        rows = conn.execute(f"""
            SELECT lc.id, lc.created_at, lc.updated_at, lc.listing_id, lc.listing_url,
                   lc.zalo_phone, lc.source_context, lc.note, lc.status,
                   l.title AS listing_title, l.ward AS listing_ward, l.price_ty AS listing_price_ty
            FROM lead_captures lc
            LEFT JOIN listings l ON l.id = lc.listing_id
            {where_sql}
            ORDER BY lc.created_at DESC
            LIMIT 500
        """, params).fetchall()
        summary_rows = conn.execute("""
            SELECT status, COUNT(*) AS n
            FROM lead_captures
            GROUP BY status
        """).fetchall()
    summary = {r["status"]: r["n"] for r in summary_rows}
    total = sum(summary.values())
    return {
        "items": [dict(r) for r in rows],
        "summary": {
            "total": total,
            "new": summary.get("new", 0),
            "called": summary.get("called", 0),
            "viewing": summary.get("viewing", 0),
            "deposit": summary.get("deposit", 0),
            "cancelled": summary.get("cancelled", 0),
        },
    }


def export_leads_csv(status: str = "", q: str = "") -> str:
    where_sql, params = _lead_filter(status, q)
    with db_mod.get_conn() as conn:
        rows = conn.execute(f"""
            SELECT lc.created_at, lc.zalo_phone, lc.listing_id, lc.listing_url,
                   COALESCE(l.title, '') AS listing_title,
                   COALESCE(l.ward, '') AS listing_ward,
                   lc.source_context, lc.status, COALESCE(lc.note, '') AS note
            FROM lead_captures lc
            LEFT JOIN listings l ON l.id = lc.listing_id
            {where_sql}
            ORDER BY lc.created_at DESC
        """, params).fetchall()
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["created_at", "zalo_phone", "listing_id", "listing_title", "ward", "listing_url", "source_context", "status", "note"])
    for row in rows:
        writer.writerow([
            row["created_at"],
            row["zalo_phone"],
            row["listing_id"],
            row["listing_title"],
            row["listing_ward"],
            row["listing_url"],
            row["source_context"],
            row["status"],
            row["note"],
        ])
    return "\ufeff" + out.getvalue()


def update_lead_status(lead_id: int, status: str, *, audit_writer: Callable) -> tuple[dict, int]:
    if status not in LEAD_STATUSES:
        return {"ok": False, "error": "invalid_status"}, 400
    with db_mod.get_conn() as conn:
        before = conn.execute(
            "SELECT id, status FROM lead_captures WHERE id=?",
            (lead_id,),
        ).fetchone()
        cur = conn.execute("""
            UPDATE lead_captures
            SET status=?, updated_at=datetime('now')
            WHERE id=?
        """, (status, lead_id))
        if cur.rowcount:
            audit_writer(
                conn,
                "lead_status_update",
                "lead",
                lead_id,
                before=dict(before) if before else None,
                after={"id": lead_id, "status": status},
                reason=status,
            )
    return {"ok": cur.rowcount > 0}, 200


def delete_lead(lead_id: int, *, audit_writer: Callable) -> tuple[dict, int]:
    with db_mod.get_conn() as conn:
        before = conn.execute(
            """
            SELECT id, created_at, updated_at, listing_id, listing_url, user_id,
                   zalo_phone, source_context, note, status
            FROM lead_captures
            WHERE id=?
            """,
            (lead_id,),
        ).fetchone()
        if not before:
            return {"ok": False, "error": "not_found"}, 404
        conn.execute("DELETE FROM lead_captures WHERE id=?", (lead_id,))
        audit_writer(
            conn,
            "lead_delete",
            "lead",
            lead_id,
            before=dict(before),
            after=None,
            reason="admin_delete",
        )
    return {"ok": True, "id": lead_id}, 200
