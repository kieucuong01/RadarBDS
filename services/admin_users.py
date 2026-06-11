"""Admin user management service helpers."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable

from config import database_sqlite as db_mod


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_iso(timespec: str = "seconds") -> str:
    return utc_now().replace(tzinfo=None).isoformat(timespec=timespec)


def user_admin_row(row, *, effective_tier_fn: Callable[[dict], str]):
    if not row:
        return None
    data = dict(row)
    data["effective_tier"] = effective_tier_fn(data)
    data.pop("password_hash", None)
    data.pop("telegram_link_token", None)
    data.pop("telegram_link_expires_at", None)
    data["telegram_linked"] = bool(data.pop("telegram_chat_id", None))
    return data


def list_users(
    *,
    tier_filter: str = "",
    q: str = "",
    effective_tier_fn: Callable[[dict], str],
) -> dict:
    where = []
    params = []
    if tier_filter in ("free", "vip", "admin"):
        where.append("tier = ?")
        params.append(tier_filter)
    if q:
        like = f"%{q}%"
        where.append("(identifier LIKE ? OR display_name LIKE ? OR email LIKE ? OR phone LIKE ?)")
        params.extend([like, like, like, like])
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    with db_mod.get_conn() as conn:
        rows = conn.execute(f"""
            SELECT id, identifier, identifier_type, email, phone, display_name,
                   tier, vip_expires_at, telegram_chat_id, notify_email, notify_telegram,
                   created_at, last_login_at, is_banned,
                   COALESCE(wc.watchlist_count, 0) AS watchlist_count
            FROM users u
            LEFT JOIN (
                SELECT user_id, COUNT(*) AS watchlist_count
                FROM user_watchlists
                GROUP BY user_id
            ) wc ON wc.user_id = u.id
            {where_sql}
            ORDER BY created_at DESC
            LIMIT 500
        """, params).fetchall()
        summary_rows = conn.execute("""
            SELECT tier, COUNT(*) AS n FROM users WHERE is_banned=0 GROUP BY tier
        """).fetchall()
        banned = conn.execute("SELECT COUNT(*) FROM users WHERE is_banned=1").fetchone()[0]
    summary = {row["tier"]: row["n"] for row in summary_rows}
    return {
        "items": [user_admin_row(row, effective_tier_fn=effective_tier_fn) for row in rows],
        "summary": {
            "total": sum(summary.values()) + banned,
            "free": summary.get("free", 0),
            "vip": summary.get("vip", 0),
            "admin": summary.get("admin", 0),
            "banned": banned,
        },
    }


def delete_user(user_id: int, *, actor_id: int | None, audit_writer: Callable) -> tuple[dict, int]:
    if actor_id == user_id:
        return {"ok": False, "error": "cannot_delete_self"}, 400

    with db_mod.get_conn() as conn:
        before = conn.execute(
            """
            SELECT id, identifier, identifier_type, email, phone, display_name,
                   tier, vip_expires_at, created_at, last_login_at, is_banned
            FROM users
            WHERE id=?
            """,
            (user_id,),
        ).fetchone()
        if not before:
            return {"ok": False, "error": "not_found"}, 404
        before_dict = dict(before)
        if before_dict.get("tier") == "admin":
            admin_count = conn.execute(
                "SELECT COUNT(*) FROM users WHERE tier='admin'"
            ).fetchone()[0]
            if admin_count <= 1:
                return {"ok": False, "error": "cannot_delete_last_admin"}, 400

        conn.execute("DELETE FROM user_sessions WHERE user_id=?", (user_id,))
        conn.execute("DELETE FROM user_watchlists WHERE user_id=?", (user_id,))
        conn.execute("DELETE FROM notification_log WHERE user_id=?", (user_id,))
        conn.execute(
            "UPDATE lead_captures SET user_id=NULL, updated_at=datetime('now') WHERE user_id=?",
            (user_id,),
        )
        conn.execute("DELETE FROM users WHERE id=?", (user_id,))
        audit_writer(
            conn,
            "user_delete",
            "user",
            user_id,
            before=before_dict,
            after={"id": user_id, "deleted": True},
            reason="admin_delete",
        )
    return {"ok": True, "id": user_id}, 200


def grant_vip(
    user_id: int,
    days_raw,
    *,
    audit_writer: Callable,
    log_audit_fn: Callable,
) -> tuple[dict, int]:
    try:
        days = int(days_raw or 30)
    except (TypeError, ValueError):
        return {"ok": False, "error": "invalid_days"}, 400
    if days <= 0 or days > 3650:
        return {"ok": False, "error": "invalid_days"}, 400
    with db_mod.get_conn() as conn:
        before = conn.execute(
            "SELECT id, tier, vip_expires_at FROM users WHERE id=?", (user_id,)
        ).fetchone()
        if not before:
            return {"ok": False, "error": "not_found"}, 404
        now_iso = utc_iso()
        cur_exp = before["vip_expires_at"]
        base_iso = cur_exp if (cur_exp and cur_exp > now_iso) else now_iso
        try:
            base_dt = datetime.fromisoformat(base_iso)
        except ValueError:
            base_dt = utc_now().replace(tzinfo=None)
        new_exp = (base_dt + timedelta(days=days)).isoformat(timespec="seconds")
        conn.execute(
            "UPDATE users SET tier='vip', vip_expires_at=? WHERE id=?",
            (new_exp, user_id),
        )
        audit_writer(
            conn,
            "user_grant_vip",
            "user",
            user_id,
            before=dict(before),
            after={"id": user_id, "tier": "vip", "vip_expires_at": new_exp},
            reason=f"+{days}d",
        )
    try:
        log_audit_fn(
            user_id=user_id,
            tier="vip",
            action="vip_granted",
            context={"days": days, "vip_expires_at": new_exp},
        )
    except Exception:
        pass
    return {"ok": True, "vip_expires_at": new_exp, "tier": "vip"}, 200


def revoke_vip(user_id: int, *, audit_writer: Callable, log_audit_fn: Callable) -> tuple[dict, int]:
    with db_mod.get_conn() as conn:
        before = conn.execute(
            "SELECT id, tier, vip_expires_at FROM users WHERE id=?", (user_id,)
        ).fetchone()
        if not before:
            return {"ok": False, "error": "not_found"}, 404
        conn.execute(
            "UPDATE users SET tier='free', vip_expires_at=NULL WHERE id=?",
            (user_id,),
        )
        audit_writer(
            conn,
            "user_revoke_vip",
            "user",
            user_id,
            before=dict(before),
            after={"id": user_id, "tier": "free", "vip_expires_at": None},
        )
    try:
        log_audit_fn(user_id=user_id, tier="free", action="vip_revoked")
    except Exception:
        pass
    return {"ok": True, "tier": "free"}, 200


def set_banned(user_id: int, banned: bool, *, audit_writer: Callable) -> tuple[dict, int]:
    banned_int = 1 if banned else 0
    with db_mod.get_conn() as conn:
        before = conn.execute(
            "SELECT id, is_banned FROM users WHERE id=?", (user_id,)
        ).fetchone()
        if not before:
            return {"ok": False, "error": "not_found"}, 404
        conn.execute("UPDATE users SET is_banned=? WHERE id=?", (banned_int, user_id))
        if banned_int:
            conn.execute("DELETE FROM user_sessions WHERE user_id=?", (user_id,))
        audit_writer(
            conn,
            "user_ban" if banned_int else "user_unban",
            "user",
            user_id,
            before=dict(before),
            after={"id": user_id, "is_banned": banned_int},
        )
    return {"ok": True, "is_banned": bool(banned_int)}, 200
