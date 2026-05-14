"""RBAC core: identifier normalize, password hash, sessions, tier gates, audit log.

All DB writes go through `db.connection.get_conn` (WAL + foreign keys ON).
Tier check happens on EVERY request via `current_tier()`; VIP auto-downgrades when
`vip_expires_at` passes — no cron needed.
"""
from __future__ import annotations

import json
import logging
import re
import secrets
from datetime import datetime, timedelta
from functools import wraps
from typing import Any

import bcrypt
from flask import g, jsonify, request

from db.connection import get_conn

logger = logging.getLogger(__name__)

SESSION_COOKIE_NAME = "radar_session"
SESSION_TTL_DAYS = 30
VIP_TRIAL_HOURS = 24  # auto-grant 1 day VIP when registering with phone
TIER_ORDER = {"guest": 0, "free": 1, "vip": 2, "admin": 3}

PHONE_RE = re.compile(r"^0\d{9,10}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ─────────────────────────────────────────────────────────────────────────────
# Identifier + password
# ─────────────────────────────────────────────────────────────────────────────
def normalize_identifier(raw: str) -> tuple[str, str] | None:
    """Return `(normalized, 'phone'|'email')` or None if invalid.

    Phone: any leading 0 / +84 / 84 → canonical `0xxxxxxxxx`.
    Email: lowercased, stripped.
    """
    if not raw:
        return None
    s = raw.strip().lower()
    if EMAIL_RE.match(s):
        return s, "email"
    digits = re.sub(r"\D", "", s)
    if digits.startswith("84"):
        digits = "0" + digits[2:]
    if PHONE_RE.match(digits):
        return digits, "phone"
    return None


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, AttributeError):
        return False


# ─────────────────────────────────────────────────────────────────────────────
# User CRUD
# ─────────────────────────────────────────────────────────────────────────────
def identifier_exists(identifier: str) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM users WHERE identifier=? LIMIT 1", (identifier,)
        ).fetchone()
    return row is not None


def create_user(
    identifier: str,
    identifier_type: str,
    password: str,
    display_name: str | None = None,
) -> dict[str, Any]:
    """Insert user. If `identifier_type=='phone'`, auto-grant 1-day VIP trial.

    Returns user row as dict. Raises ValueError if identifier already exists.
    """
    now = datetime.utcnow().isoformat(timespec="seconds")
    email = identifier if identifier_type == "email" else None
    phone = identifier if identifier_type == "phone" else None
    tier = "vip" if identifier_type == "phone" else "free"
    vip_expires_at = (
        (datetime.utcnow() + timedelta(hours=VIP_TRIAL_HOURS)).isoformat(timespec="seconds")
        if identifier_type == "phone"
        else None
    )
    pwd_hash = hash_password(password)
    with get_conn() as conn:
        try:
            cur = conn.execute(
                """
                INSERT INTO users (
                    identifier, identifier_type, email, phone,
                    password_hash, display_name, tier, vip_expires_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    identifier,
                    identifier_type,
                    email,
                    phone,
                    pwd_hash,
                    display_name,
                    tier,
                    vip_expires_at,
                    now,
                ),
            )
        except Exception as e:
            raise ValueError(f"identifier_taken: {e}") from e
        user_id = cur.lastrowid
        row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()

    user_dict = dict(row)
    log_audit(
        user_id=user_id,
        tier=tier,
        action="register",
        context={"identifier_type": identifier_type, "trial": tier == "vip"},
    )
    if tier == "vip":
        log_audit(
            user_id=user_id,
            tier="vip",
            action="register_phone_trial_granted",
            context={"hours": VIP_TRIAL_HOURS},
        )
    return user_dict


def authenticate(identifier: str, password: str) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE identifier=? AND is_banned=0", (identifier,)
        ).fetchone()
    if not row:
        return None
    if not verify_password(password, row["password_hash"]):
        return None
    return dict(row)


# ─────────────────────────────────────────────────────────────────────────────
# Sessions
# ─────────────────────────────────────────────────────────────────────────────
def create_session(user_id: int, user_agent: str | None = None, ip: str | None = None) -> str:
    token = secrets.token_urlsafe(32)
    expires_at = (datetime.utcnow() + timedelta(days=SESSION_TTL_DAYS)).isoformat(timespec="seconds")
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO user_sessions (token, user_id, expires_at, user_agent, ip)
            VALUES (?, ?, ?, ?, ?)
            """,
            (token, user_id, expires_at, user_agent, ip),
        )
        conn.execute(
            "UPDATE users SET last_login_at=? WHERE id=?",
            (datetime.utcnow().isoformat(timespec="seconds"), user_id),
        )
    return token


def get_session(token: str) -> dict[str, Any] | None:
    if not token:
        return None
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT u.*, s.token AS session_token, s.expires_at AS session_expires_at
              FROM user_sessions s
              JOIN users u ON u.id = s.user_id
             WHERE s.token = ?
               AND s.expires_at > datetime('now')
               AND u.is_banned = 0
            """,
            (token,),
        ).fetchone()
    if not row:
        return None
    return dict(row)


def delete_session(token: str) -> None:
    if not token:
        return
    with get_conn() as conn:
        conn.execute("DELETE FROM user_sessions WHERE token=?", (token,))


# ─────────────────────────────────────────────────────────────────────────────
# Tier resolution (per-request)
# ─────────────────────────────────────────────────────────────────────────────
def current_user() -> dict[str, Any] | None:
    """Return user dict bound to current request, or None for guest. Cached on `g`."""
    if hasattr(g, "_radar_user"):
        return g._radar_user
    token = request.cookies.get(SESSION_COOKIE_NAME)
    user = get_session(token) if token else None
    g._radar_user = user
    return user


def current_tier() -> str:
    """Resolve current tier with auto-downgrade if VIP expired."""
    u = current_user()
    if not u:
        return "guest"
    tier = u.get("tier") or "free"
    if tier == "vip":
        exp = u.get("vip_expires_at")
        if exp and exp < datetime.utcnow().isoformat(timespec="seconds"):
            # downgrade in DB so future requests see free
            try:
                with get_conn() as conn:
                    conn.execute(
                        "UPDATE users SET tier='free' WHERE id=? AND tier='vip'",
                        (u["id"],),
                    )
            except Exception as e:
                logger.warning(f"VIP downgrade failed for user {u.get('id')}: {e}")
            u["tier"] = "free"
            tier = "free"
    return tier


def require_tier(min_tier: str):
    """Decorator: 403 if `current_tier() < min_tier`."""
    if min_tier not in TIER_ORDER:
        raise ValueError(f"unknown tier: {min_tier}")

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            tier = current_tier()
            if TIER_ORDER[tier] < TIER_ORDER[min_tier]:
                return (
                    jsonify({"error": "tier_required", "required": min_tier, "current": tier}),
                    403,
                )
            return fn(*args, **kwargs)

        return wrapper

    return deco


# ─────────────────────────────────────────────────────────────────────────────
# VIP grant / revoke (admin)
# ─────────────────────────────────────────────────────────────────────────────
def grant_vip(user_id: int, days: int, actor_user_id: int | None = None) -> dict[str, Any] | None:
    new_expires = (datetime.utcnow() + timedelta(days=days)).isoformat(timespec="seconds")
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET tier='vip', vip_expires_at=? WHERE id=?",
            (new_expires, user_id),
        )
        row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    log_audit(
        user_id=actor_user_id,
        tier="admin",
        action="vip_granted",
        context={"target_user_id": user_id, "days": days, "expires_at": new_expires},
    )
    return dict(row) if row else None


def revoke_vip(user_id: int, actor_user_id: int | None = None) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET tier='free', vip_expires_at=NULL WHERE id=?",
            (user_id,),
        )
    log_audit(
        user_id=actor_user_id,
        tier="admin",
        action="vip_revoked",
        context={"target_user_id": user_id},
    )


# ─────────────────────────────────────────────────────────────────────────────
# Audit log
# ─────────────────────────────────────────────────────────────────────────────
def log_audit(
    user_id: int | None,
    tier: str | None,
    action: str,
    listing_id: int | None = None,
    context: dict | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
) -> None:
    """Insert audit row. Safe to call inside request or background job."""
    try:
        ctx_json = json.dumps(context, ensure_ascii=False) if context else None
        # Try to enrich ip/ua from request when caller didn't pass them
        if request and (ip is None or user_agent is None):
            try:
                if ip is None:
                    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "")
                if user_agent is None:
                    user_agent = request.headers.get("User-Agent", "")
            except Exception:
                pass
        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO user_audit_log
                    (user_id, tier, action, listing_id, context, ip, user_agent)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (user_id, tier, action, listing_id, ctx_json, ip, user_agent),
            )
    except Exception as e:
        logger.warning(f"audit log failed action={action}: {e}")
