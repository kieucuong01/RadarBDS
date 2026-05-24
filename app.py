from __future__ import annotations

import os
import json
import csv
import io
import sqlite3
import logging
import statistics
import re
import urllib.request
from functools import wraps
from datetime import datetime, timedelta
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_from_directory, Response, make_response
from config import database_sqlite as db_mod
from db.moderation import normalize_phone

# Import the extracted services
from services.market_data import load_data, load_signals, load_trend_data, load_listing_detail, load_market_indicators, get_base_filters, get_city_for_ward, CITY_MAP, _days_ago, resolve_image_url, _range_filters, redact_for_tier
from services.investment_memo import load_investment_memo
from services.ai_bot import AIBot

# RBAC (4-tier auth)
from auth.core import (
    SESSION_COOKIE_NAME,
    SESSION_TTL_DAYS,
    authenticate,
    create_session,
    create_user,
    current_tier,
    current_user,
    delete_session,
    identifier_exists,
    log_audit,
    normalize_identifier,
    rate_limit,
    require_tier,
)

app = Flask(__name__)
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
LEAD_STATUSES = {"new", "called", "viewing", "deposit", "cancelled"}
POSITIVE_REVIEW_VERDICTS = {"good", "correct", "cheap_real"}
HARD_HIDE_REVIEW_VERDICTS = {"bad", "spam", "sold", "fake_price"}
SOFT_HIDE_REVIEW_VERDICTS = {"bad_data", "fair", "overpriced", "cannot_price"}
HIDE_REVIEW_VERDICTS = HARD_HIDE_REVIEW_VERDICTS | SOFT_HIDE_REVIEW_VERDICTS
VALUATION_VERDICTS = {"cheap_real", "fair", "overpriced", "fake_price", "cannot_price"}
EXTRACTION_RECHECK_VERDICTS = {"wrong_ward", "wrong_road", "wrong_property_type", "wrong_price", "wrong_area"}
TRAINING_VERDICTS = POSITIVE_REVIEW_VERDICTS | HIDE_REVIEW_VERDICTS | {"maybe"}
INFRA_KINDS = {"timeline", "policy"}
INFRA_STATUS = {"done", "in_progress", "planned"}
INFRA_SEVERITY = {"critical", "warning", "info"}


def _admin_credentials():
    return (os.getenv("ADMIN_BASIC_USER", "").strip(), os.getenv("ADMIN_BASIC_PASS", "").strip())


def _basic_admin_authorized():
    auth = request.authorization
    user, pwd = _admin_credentials()
    return bool(auth and user and pwd and auth.username == user and auth.password == pwd)


def _admin_request_authorized():
    return current_tier() == "admin" or _basic_admin_authorized()


def _admin_forbidden():
    if request.path.startswith("/admin/api/"):
        return jsonify({"ok": False, "error": "admin_required"}), 403
    return Response("Admin required", 403)


def require_admin_auth(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if _admin_request_authorized():
            return fn(*args, **kwargs)

        return _admin_forbidden()
    return wrapper


# ═══════════════════════════════════════════════════════════════════════════
# RBAC: session cookie helpers + /api/auth/* endpoints
# ═══════════════════════════════════════════════════════════════════════════
def _cookie_kwargs():
    """HttpOnly + SameSite=Lax; Secure only when request is HTTPS (prod)."""
    return dict(
        httponly=True,
        samesite="Lax",
        secure=request.is_secure,
        max_age=SESSION_TTL_DAYS * 86400,
        path="/",
    )


def _set_session_cookie(resp, token: str):
    resp.set_cookie(SESSION_COOKIE_NAME, token, **_cookie_kwargs())
    return resp


def _clear_session_cookie(resp):
    resp.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return resp


def _client_ip() -> str:
    return request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip()


def _effective_tier_from_user(user: dict) -> str:
    """Compute tier from raw user row, applying VIP expiry — does NOT touch session cookie."""
    if not user:
        return "guest"
    tier = user.get("tier") or "free"
    if tier == "vip":
        exp = user.get("vip_expires_at")
        if exp and exp < datetime.utcnow().isoformat(timespec="seconds"):
            return "free"
    return tier


def _user_public(user: dict) -> dict:
    """Strip sensitive fields before returning user to client."""
    if not user:
        return {}
    return {
        "id": user.get("id"),
        "identifier_type": user.get("identifier_type"),
        "display_name": user.get("display_name"),
        "email": user.get("email"),
        "phone": user.get("phone"),
        "tier": _effective_tier_from_user(user),
        "vip_expires_at": user.get("vip_expires_at"),
        "telegram_linked": bool(user.get("telegram_chat_id")),
        "notify_email": bool(user.get("notify_email", 1)),
        "notify_telegram": bool(user.get("notify_telegram", 1)),
    }


@app.context_processor
def inject_user_tier():
    """Expose USER_TIER + USER to all Jinja templates."""
    u = current_user()
    return {
        "USER_TIER": current_tier(),
        "USER": _user_public(u) if u else None,
    }


@app.route("/api/auth/check", methods=["POST"])
@rate_limit("auth_check", limits={"guest": 60, "free": 120, "vip": 300, "admin": None})
def api_auth_check():
    """Step 1 of unified login flow: detect identifier + whether user exists."""
    payload = request.get_json(silent=True) or {}
    raw = (payload.get("identifier") or "").strip()
    norm = normalize_identifier(raw)
    if not norm:
        return jsonify({"ok": False, "error": "invalid_identifier"}), 400
    ident, ident_type = norm
    # Tạm thời chỉ hỗ trợ đăng ký/đăng nhập bằng SĐT
    if ident_type == "email":
        return jsonify({"ok": False, "error": "phone_only"}), 400
    return jsonify({
        "ok": True,
        "identifier": ident,
        "type": ident_type,
        "exists": identifier_exists(ident),
    })


@app.route("/api/auth/register", methods=["POST"])
@rate_limit("auth_register", limits={"guest": 20, "free": 30, "vip": 60, "admin": None})
def api_auth_register():
    payload = request.get_json(silent=True) or {}
    raw = (payload.get("identifier") or "").strip()
    pwd = payload.get("password") or ""
    name = (payload.get("display_name") or "").strip()[:80] or None

    norm = normalize_identifier(raw)
    if not norm:
        return jsonify({"ok": False, "error": "invalid_identifier"}), 400
    if len(pwd) < 6:
        return jsonify({"ok": False, "error": "password_too_short"}), 400
    ident, ident_type = norm
    # Tạm thời chỉ hỗ trợ đăng ký bằng SĐT
    if ident_type == "email":
        return jsonify({"ok": False, "error": "phone_only"}), 400

    if identifier_exists(ident):
        return jsonify({"ok": False, "error": "already_registered"}), 409

    try:
        user = create_user(ident, ident_type, pwd, display_name=name)
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 409

    token = create_session(user["id"], user_agent=request.headers.get("User-Agent", ""), ip=_client_ip())
    log_audit(user["id"], user["tier"], "signup_completed", context={"type": ident_type})
    resp = make_response(jsonify({"ok": True, "user": _user_public(user)}))
    return _set_session_cookie(resp, token)


@app.route("/api/auth/login", methods=["POST"])
@rate_limit("auth_login", limits={"guest": 30, "free": 60, "vip": 120, "admin": None})
def api_auth_login():
    payload = request.get_json(silent=True) or {}
    raw = (payload.get("identifier") or "").strip()
    pwd = payload.get("password") or ""

    norm = normalize_identifier(raw)
    if not norm:
        return jsonify({"ok": False, "error": "invalid_identifier"}), 400
    ident, _ = norm

    user = authenticate(ident, pwd)
    if not user:
        log_audit(None, "guest", "login_failed", context={"identifier_masked": ident[:4] + "***"})
        return jsonify({"ok": False, "error": "invalid_credentials"}), 401

    token = create_session(user["id"], user_agent=request.headers.get("User-Agent", ""), ip=_client_ip())
    log_audit(user["id"], user["tier"], "login")
    resp = make_response(jsonify({"ok": True, "user": _user_public(user)}))
    return _set_session_cookie(resp, token)


@app.route("/api/auth/logout", methods=["POST"])
def api_auth_logout():
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token:
        u = current_user()
        delete_session(token)
        if u:
            log_audit(u["id"], u.get("tier"), "logout")
    resp = make_response(jsonify({"ok": True}))
    return _clear_session_cookie(resp)


@app.route("/api/auth/me", methods=["GET"])
def api_auth_me():
    u = current_user()
    return jsonify({
        "ok": True,
        "tier": current_tier(),
        "user": _user_public(u) if u else None,
    })


# ═══════════════════════════════════════════════════════════════════════════
# Watchlists (logged-in users — VIP gets push, Free gets stored for upsell)
# ═══════════════════════════════════════════════════════════════════════════
def _serialize_watchlist(row: dict) -> dict:
    d = dict(row)
    for k in ("wards", "prop_types"):
        v = d.get(k)
        if isinstance(v, str) and v:
            try:
                d[k] = json.loads(v)
            except json.JSONDecodeError:
                d[k] = []
        elif v is None:
            d[k] = []
    d["active"] = bool(d.get("active", 1))
    d["notify_telegram"] = bool(d.get("notify_telegram", 1))
    d["notify_email"] = bool(d.get("notify_email", 1))
    return d


def _validate_watchlist_payload(payload: dict) -> tuple[dict, str | None]:
    name = (payload.get("name") or "").strip()[:120]
    if not name:
        return {}, "name_required"
    wards = payload.get("wards") or []
    prop_types = payload.get("prop_types") or []
    if not isinstance(wards, list) or not isinstance(prop_types, list):
        return {}, "invalid_array"

    def _opt_num(key):
        v = payload.get(key)
        if v in (None, "", "null"):
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    def _opt_int(key, default=0):
        v = payload.get(key)
        if v in (None, "", "null"):
            return default
        try:
            return int(v)
        except (TypeError, ValueError):
            return default

    out = {
        "name": name,
        "wards": json.dumps(wards, ensure_ascii=False),
        "prop_types": json.dumps(prop_types, ensure_ascii=False),
        "mos_min": _opt_int("mos_min", 0),
        "price_max_ty": _opt_num("price_max_ty"),
        "price_min_ty": _opt_num("price_min_ty"),
        "area_min": _opt_num("area_min"),
        "area_max": _opt_num("area_max"),
        "notify_telegram": 1 if payload.get("notify_telegram", True) else 0,
        "notify_email": 1 if payload.get("notify_email", True) else 0,
        "active": 1 if payload.get("active", True) else 0,
    }
    return out, None


@app.route("/api/watchlists", methods=["GET"])
@require_tier("free")
def api_list_watchlists():
    u = current_user()
    with db_mod.get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM user_watchlists WHERE user_id=? ORDER BY id DESC", (u["id"],)
        ).fetchall()
    return jsonify({"ok": True, "items": [_serialize_watchlist(r) for r in rows]})


@app.route("/api/watchlists", methods=["POST"])
@require_tier("free")
def api_create_watchlist():
    u = current_user()
    payload = request.get_json(silent=True) or {}
    data, err = _validate_watchlist_payload(payload)
    if err:
        return jsonify({"ok": False, "error": err}), 400
    with db_mod.get_conn() as conn:
        cur = conn.execute("""
            INSERT INTO user_watchlists
              (user_id, name, wards, prop_types, mos_min, price_max_ty, price_min_ty,
               area_min, area_max, notify_telegram, notify_email, active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            u["id"], data["name"], data["wards"], data["prop_types"], data["mos_min"],
            data["price_max_ty"], data["price_min_ty"], data["area_min"], data["area_max"],
            data["notify_telegram"], data["notify_email"], data["active"],
        ))
        wid = cur.lastrowid
        row = conn.execute("SELECT * FROM user_watchlists WHERE id=?", (wid,)).fetchone()
    log_audit(user_id=u["id"], tier=current_tier(), action="watchlist_create",
              context={"id": wid, "name": data["name"]})
    return jsonify({"ok": True, "item": _serialize_watchlist(row)})


@app.route("/api/watchlists/<int:wid>", methods=["PATCH"])
@require_tier("free")
def api_update_watchlist(wid):
    u = current_user()
    payload = request.get_json(silent=True) or {}
    data, err = _validate_watchlist_payload(payload)
    if err:
        return jsonify({"ok": False, "error": err}), 400
    with db_mod.get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM user_watchlists WHERE id=? AND user_id=?", (wid, u["id"])
        ).fetchone()
        if not row:
            return jsonify({"ok": False, "error": "not_found"}), 404
        conn.execute("""
            UPDATE user_watchlists SET
              name=?, wards=?, prop_types=?, mos_min=?, price_max_ty=?, price_min_ty=?,
              area_min=?, area_max=?, notify_telegram=?, notify_email=?, active=?,
              updated_at=datetime('now')
            WHERE id=? AND user_id=?
        """, (
            data["name"], data["wards"], data["prop_types"], data["mos_min"],
            data["price_max_ty"], data["price_min_ty"], data["area_min"], data["area_max"],
            data["notify_telegram"], data["notify_email"], data["active"],
            wid, u["id"],
        ))
        row = conn.execute("SELECT * FROM user_watchlists WHERE id=?", (wid,)).fetchone()
    return jsonify({"ok": True, "item": _serialize_watchlist(row)})


# ─────────────────────────────────────────────────────────────────────────────
# Telegram bind: deep-link token → /start <token> → bot webhook updates chat_id
# ─────────────────────────────────────────────────────────────────────────────
import secrets as _secrets


@app.route("/api/auth/telegram/start", methods=["POST"])
@require_tier("free")
def api_telegram_start():
    u = current_user()
    bot_username = os.getenv("TELEGRAM_BOT_USERNAME", "").strip().lstrip("@")
    if not bot_username:
        return jsonify({"ok": False, "error": "bot_not_configured"}), 500
    token = _secrets.token_urlsafe(16)
    expires = (datetime.utcnow() + timedelta(minutes=10)).isoformat(timespec="seconds")
    with db_mod.get_conn() as conn:
        conn.execute(
            "UPDATE users SET telegram_link_token=?, telegram_link_expires_at=? WHERE id=?",
            (token, expires, u["id"]),
        )
    deep_link = f"https://t.me/{bot_username}?start={token}"
    return jsonify({"ok": True, "url": deep_link, "expires_at": expires})


@app.route("/api/auth/telegram/unbind", methods=["POST"])
@require_tier("free")
def api_telegram_unbind():
    u = current_user()
    with db_mod.get_conn() as conn:
        conn.execute(
            "UPDATE users SET telegram_chat_id=NULL, telegram_link_token=NULL, "
            "telegram_link_expires_at=NULL WHERE id=?", (u["id"],),
        )
    return jsonify({"ok": True})


def _telegram_api(method: str, payload: dict | None = None) -> dict:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        return {"ok": False, "error": "missing_token"}
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=12) as resp:
        return json.loads(resp.read().decode("utf-8"))


@app.route("/api/auth/telegram/sync", methods=["POST"])
@require_tier("free")
def api_telegram_sync():
    """Local-dev fallback: poll Telegram updates and bind current user's /start token.

    Production should use webhook. This keeps localhost usable when Telegram
    cannot call back into 127.0.0.1.
    """
    u = current_user()
    if not u:
        return jsonify({"ok": False, "error": "login_required"}), 401
    if u.get("telegram_chat_id"):
        return jsonify({"ok": True, "linked": True})

    user_token = ""
    with db_mod.get_conn() as conn:
        row = conn.execute(
            "SELECT telegram_link_token FROM users WHERE id=?",
            (u["id"],),
        ).fetchone()
        user_token = (row["telegram_link_token"] if row else "") or ""
    if not user_token:
        return jsonify({"ok": True, "linked": False, "error": "no_active_token"})

    try:
        data = _telegram_api("getUpdates")
    except Exception as e:
        return jsonify({"ok": False, "error": "telegram_unreachable", "detail": str(e)[:160]}), 502

    if not data.get("ok"):
        return jsonify({"ok": False, "error": data.get("description") or "telegram_error"}), 502

    chat_id = None
    for upd in data.get("result", []):
        msg = upd.get("message") or upd.get("edited_message") or {}
        text = (msg.get("text") or "").strip()
        chat = msg.get("chat") or {}
        if text == f"/start {user_token}" and chat.get("id"):
            chat_id = str(chat["id"])
            break

    if not chat_id:
        return jsonify({"ok": True, "linked": False})

    with db_mod.get_conn() as conn:
        conn.execute(
            "UPDATE users SET telegram_chat_id=?, telegram_link_token=NULL, "
            "telegram_link_expires_at=NULL WHERE id=?",
            (chat_id, u["id"]),
        )
    try:
        from alerts.telegram import send_message_to
        send_message_to(chat_id, "Da ket noi tai khoan RadarBDS. Ban se nhan thong bao deal khop khu vuc quan tam.")
    except Exception:
        pass
    return jsonify({"ok": True, "linked": True})


@app.route("/api/auth/telegram/webhook", methods=["POST"])
def api_telegram_webhook():
    """Receive Telegram bot updates. Match `/start <token>` → bind chat_id.

    Secret query param `?secret=<TELEGRAM_WEBHOOK_SECRET>` for crude auth.
    """
    secret_env = (os.getenv("TELEGRAM_WEBHOOK_SECRET") or "").strip()
    if secret_env and request.args.get("secret") != secret_env:
        return jsonify({"ok": False, "error": "forbidden"}), 403

    update = request.get_json(silent=True) or {}
    msg = update.get("message") or update.get("edited_message") or {}
    text = (msg.get("text") or "").strip()
    chat = msg.get("chat") or {}
    chat_id = chat.get("id")
    if not chat_id or not text.startswith("/start"):
        return jsonify({"ok": True, "ignored": True})

    parts = text.split(maxsplit=1)
    token = parts[1].strip() if len(parts) == 2 else ""
    if not token:
        try:
            from alerts.telegram import send_message_to
            send_message_to(str(chat_id), "Vui lòng mở RadarBDS → Kết nối Telegram để lấy link.")
        except Exception:
            pass
        return jsonify({"ok": True})

    now_iso = datetime.utcnow().isoformat(timespec="seconds")
    with db_mod.get_conn() as conn:
        row = conn.execute(
            "SELECT id, display_name FROM users WHERE telegram_link_token=? "
            "AND (telegram_link_expires_at IS NULL OR telegram_link_expires_at > ?)",
            (token, now_iso),
        ).fetchone()
        if not row:
            try:
                from alerts.telegram import send_message_to
                send_message_to(str(chat_id), "❌ Token hết hạn hoặc không hợp lệ. Hãy lấy link mới trên RadarBDS.")
            except Exception:
                pass
            return jsonify({"ok": True, "matched": False})
        user_id = row["id"]
        conn.execute(
            "UPDATE users SET telegram_chat_id=?, telegram_link_token=NULL, "
            "telegram_link_expires_at=NULL WHERE id=?",
            (str(chat_id), user_id),
        )
    try:
        from alerts.telegram import send_message_to
        send_message_to(
            str(chat_id),
            f"✅ Đã kết nối tài khoản RadarBDS. Bạn sẽ nhận thông báo deal khẩn cấp từ giờ."
        )
    except Exception:
        pass
    try:
        log_audit(user_id=user_id, tier=None, action="telegram_linked",
                  context={"chat_id": str(chat_id)})
    except Exception:
        pass
    return jsonify({"ok": True, "matched": True, "user_id": user_id})


# ─────────────────────────────────────────────────────────────────────────────
# Conversion tracking (/api/track) — open to guests, used to measure funnel
# ─────────────────────────────────────────────────────────────────────────────
ALLOWED_TRACK_ACTIONS = {
    "teaser_hit_12",
    "locked_tab_click",
    "locked_fresh_click",
    "locked_filter_click",
    "vip_cta_click",
    "cta_signup",
    "cta_vip",
    "modal_open",
}


@app.route("/api/track", methods=["POST"])
@rate_limit("track", limits={"guest": 120, "free": 600, "vip": None, "admin": None})
def api_track():
    payload = request.get_json(silent=True) or {}
    action = (payload.get("action") or "").strip()[:60]
    if action not in ALLOWED_TRACK_ACTIONS:
        return jsonify({"ok": False, "error": "invalid_action"}), 400
    listing_id = payload.get("listing_id")
    try:
        listing_id = int(listing_id) if listing_id not in (None, "") else None
    except (TypeError, ValueError):
        listing_id = None
    ctx = payload.get("context") or {}
    if not isinstance(ctx, dict):
        ctx = {"raw": str(ctx)[:200]}
    u = current_user()
    try:
        log_audit(
            user_id=u["id"] if u else None,
            tier=current_tier(),
            action=action,
            listing_id=listing_id,
            context=ctx,
        )
    except Exception:
        pass
    return jsonify({"ok": True})


@app.route("/api/watchlists/<int:wid>", methods=["DELETE"])
@require_tier("free")
def api_delete_watchlist(wid):
    u = current_user()
    with db_mod.get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM user_watchlists WHERE id=? AND user_id=?", (wid, u["id"])
        )
    if not cur.rowcount:
        return jsonify({"ok": False, "error": "not_found"}), 404
    return jsonify({"ok": True})


# Serve local downloaded images (data/images/<filename>)
_DATA_IMAGES_DIR = Path(__file__).parent / "data" / "images"

@app.route("/data/images/<path:filename>")
def serve_local_image(filename):
    return send_from_directory(_DATA_IMAGES_DIR, filename)

@app.route("/")
def index():
    return render_template('index.html', wards_by_city=CITY_MAP)

def _get_signals_version(db_path: str) -> str:
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            """
            SELECT COALESCE(
                MAX(v),
                '0'
            ) AS v
            FROM (
                SELECT datetime(review_hidden_at) AS v
                  FROM listings
                 WHERE review_hidden_at IS NOT NULL
                UNION ALL
                SELECT datetime(updated_at) AS v
                  FROM listings
                 WHERE updated_at IS NOT NULL
            )
            """
        ).fetchone()
        return str(row[0] if row and row[0] is not None else "0")
    finally:
        conn.close()


def _request_range_filters(req):
    def _parse(name):
        try:
            value = req.args.get(name, 0)
            return float(value) if value not in (None, "") else 0
        except (TypeError, ValueError):
            return 0

    return _parse("area_min"), _parse("area_max"), _parse("price_min"), _parse("price_max")


def _safe_date(value):
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text[:19], fmt)
        except Exception:
            continue
    return None


def _relative_time_label(value):
    dt = _safe_date(value)
    if not dt:
        return ""
    days = (datetime.now() - dt).days
    if days <= 0:
        return "hôm nay"
    if days == 1:
        return "1 ngày trước"
    return f"{days} ngày trước"


def _listing_cluster_ids(conn, listing_id: int) -> set[int]:
    row = conn.execute(
        "SELECT id, duplicate_of_id FROM listings WHERE id=?",
        (listing_id,),
    ).fetchone()
    cluster_ids = {int(listing_id)}
    if not row:
        return cluster_ids

    canonical_id = row["duplicate_of_id"] if row["duplicate_of_id"] else row["id"]
    cluster_ids.add(int(canonical_id))
    dup_rows = conn.execute(
        "SELECT id FROM listings WHERE duplicate_of_id=?",
        (canonical_id,),
    ).fetchall()
    cluster_ids.update(int(r["id"]) for r in dup_rows)
    return cluster_ids


def _set_review_visibility(conn, listing_id: int, verdict: str) -> None:
    cluster_ids = _listing_cluster_ids(conn, listing_id)
    placeholders = ",".join("?" for _ in cluster_ids)
    cluster_params = list(cluster_ids)
    if verdict in HIDE_REVIEW_VERDICTS:
        conn.execute(
            f"""
            UPDATE listings
               SET review_hidden = 1,
                   review_hidden_at = datetime('now'),
                   review_hidden_reason = ?,
                   updated_at = datetime('now')
             WHERE id IN ({placeholders})
            """,
            [verdict] + cluster_params,
        )
    elif verdict in POSITIVE_REVIEW_VERDICTS:
        conn.execute(
            f"""
            UPDATE listings
               SET review_hidden = 0,
                   review_hidden_at = NULL,
                   review_hidden_reason = NULL,
                   updated_at = datetime('now')
             WHERE id IN ({placeholders})
            """,
            cluster_params,
        )


def _normalize_valuation_verdict(value) -> str:
    val = (value or "").strip()
    aliases = {
        "good": "cheap_real",
        "correct": "cheap_real",
        "too_high": "overpriced",
        "too_low": "cheap_real",
        "bad": "cannot_price",
        "bad_data": "cannot_price",
        "na": "cannot_price",
    }
    return aliases.get(val, val)


def _derive_training_verdict(payload: dict):
    extraction_verdict = (payload.get("extraction_verdict") or "").strip()[:80] or None
    raw_valuation = payload.get("valuation_verdict")
    valuation_verdict = _normalize_valuation_verdict(raw_valuation)[:80] or None
    raw_verdict = (payload.get("verdict") or "").strip()
    reason_tags = payload.get("reason_tags") or []
    if isinstance(reason_tags, str):
        reason_tags = [reason_tags]
    if raw_valuation and valuation_verdict not in VALUATION_VERDICTS:
        raise ValueError("invalid_verdict")

    if extraction_verdict and extraction_verdict != "all_correct":
        if raw_verdict in HARD_HIDE_REVIEW_VERDICTS:
            verdict = raw_verdict
        elif valuation_verdict == "fake_price" or "fake_price" in reason_tags:
            verdict = "fake_price"
        else:
            verdict = "bad_data"
        if valuation_verdict not in VALUATION_VERDICTS:
            valuation_verdict = "cannot_price"
        return verdict, extraction_verdict, valuation_verdict

    if valuation_verdict in VALUATION_VERDICTS:
        return valuation_verdict, extraction_verdict or "all_correct", valuation_verdict

    normalized_verdict = _normalize_valuation_verdict(raw_verdict)
    if normalized_verdict in VALUATION_VERDICTS:
        return normalized_verdict, extraction_verdict or "all_correct", normalized_verdict

    verdict = raw_verdict or "maybe"
    if verdict not in TRAINING_VERDICTS:
        raise ValueError("invalid_verdict")
    return verdict, extraction_verdict, valuation_verdict


def _admin_actor() -> str:
    user = current_user()
    if user:
        return (
            user.get("identifier")
            or user.get("phone")
            or user.get("email")
            or f"user:{user.get('id')}"
        )
    auth = request.authorization
    return auth.username if auth and auth.username else "admin"


def _write_admin_audit(conn, action: str, entity_type: str, entity_id,
                       before=None, after=None, reason=None) -> None:
    conn.execute(
        """
        INSERT INTO admin_audit_log
          (actor, action, entity_type, entity_id, before_json, after_json, reason)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            _admin_actor(),
            action,
            entity_type,
            entity_id,
            json.dumps(before, ensure_ascii=False) if before is not None else None,
            json.dumps(after, ensure_ascii=False) if after is not None else None,
            reason,
        ),
    )


def _save_ai_training_feedback(conn, listing_id: int, payload: dict) -> dict:
    verdict, extraction_verdict, valuation_verdict = _derive_training_verdict(payload)
    if verdict not in TRAINING_VERDICTS:
        raise ValueError("invalid_verdict")

    reason_code = (payload.get("reason_code") or "").strip()[:80] or None
    reason_text = (payload.get("reason_text") or payload.get("reason") or "").strip()[:500] or None
    reason_tags = payload.get("reason_tags") or []
    if isinstance(reason_tags, str):
        reason_tags = [reason_tags]

    before = conn.execute(
        "SELECT id, review_hidden, review_hidden_reason FROM listings WHERE id=?",
        (listing_id,),
    ).fetchone()
    cur = conn.execute(
        """
        INSERT INTO ai_training_feedback
          (listing_id, actor, verdict, extraction_verdict, valuation_verdict,
           reason_code, reason_text, reason_tags, note, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        """,
        (
            listing_id,
            _admin_actor(),
            verdict,
            extraction_verdict,
            valuation_verdict,
            reason_code,
            reason_text,
            json.dumps(reason_tags, ensure_ascii=False),
            (payload.get("note") or "").strip()[:500] or None,
        ),
    )
    _set_review_visibility(conn, listing_id, verdict)
    after = conn.execute(
        "SELECT id, review_hidden, review_hidden_reason FROM listings WHERE id=?",
        (listing_id,),
    ).fetchone()
    audit_after = dict(after) if after else {"id": listing_id}
    audit_after.update({
        "feedback_id": cur.lastrowid,
        "verdict": verdict,
        "extraction_verdict": extraction_verdict,
        "valuation_verdict": valuation_verdict,
        "reason_code": reason_code,
        "reason_text": reason_text,
    })
    _write_admin_audit(
        conn,
        "ai_training_feedback",
        "listing",
        listing_id,
        before=dict(before) if before else None,
        after=audit_after,
        reason=reason_text or reason_code or verdict,
    )
    return {
        "feedback_id": cur.lastrowid,
        "verdict": verdict,
        "extraction_verdict": extraction_verdict,
        "valuation_verdict": valuation_verdict,
    }


def _clean_infra_payload(payload):
    kind = (payload.get("kind") or "").strip()
    if kind not in INFRA_KINDS:
        raise ValueError("invalid_kind")

    title = (payload.get("title") or "").strip()[:220]
    if not title:
        raise ValueError("missing_title")

    status_tag = (payload.get("status_tag") or "").strip()
    if status_tag and status_tag not in INFRA_STATUS:
        raise ValueError("invalid_status")

    severity = (payload.get("severity") or "").strip()
    if severity and severity not in INFRA_SEVERITY:
        raise ValueError("invalid_severity")

    event_date = (payload.get("event_date") or "").strip()[:19] or None
    if event_date and not _safe_date(event_date):
        raise ValueError("invalid_event_date")

    progress_pct = payload.get("progress_pct")
    if progress_pct in ("", None):
        progress_pct = None
    else:
        try:
            progress_pct = float(progress_pct)
        except (TypeError, ValueError):
            raise ValueError("invalid_progress")
        progress_pct = max(0.0, min(100.0, progress_pct))

    try:
        sort_order = int(payload.get("sort_order", 0) or 0)
    except (TypeError, ValueError):
        sort_order = 0

    return {
        "kind": kind,
        "title": title,
        "subtitle": (payload.get("subtitle") or "").strip()[:220] or None,
        "summary": (payload.get("summary") or "").strip()[:1000] or None,
        "ward": (payload.get("ward") or "").strip()[:120] or None,
        "road_ref": (payload.get("road_ref") or "").strip()[:160] or None,
        "project_code": (payload.get("project_code") or "").strip()[:60] or None,
        "milestone_label": (payload.get("milestone_label") or "").strip()[:80] or None,
        "progress_pct": progress_pct,
        "status_tag": status_tag or None,
        "severity": severity or None,
        "event_date": event_date,
        "source_url": (payload.get("source_url") or "").strip()[:500] or None,
        "sort_order": sort_order,
    }

@app.route("/api/dashboard")
@rate_limit("dashboard", limits={"guest": 1200, "free": 2400, "vip": None, "admin": None})
def api_dashboard():
    active_city, wards, sources, prop_types, only_drops, trend_period, mos_min = get_base_filters(request)
    area_min, area_max, price_min, price_max = _request_range_filters(request)
    if not wards and active_city in CITY_MAP:
        wards = CITY_MAP[active_city]
    db_path = str(db_mod.DB_PATH.resolve())
    include_trend = request.args.get("include_trend") == "1"
    # Load data without fetching all listings to save time/memory
    tier = current_tier()
    data = load_data(db_path, sources, wards, prop_types, only_drops, trend_period, skip_listings=True, include_trend=include_trend, mos_min=mos_min, include_signals=False, area_min=area_min, area_max=area_max, price_min=price_min, price_max=price_max, tier=tier)
    
    return jsonify({
        "stats": data["stats"],
        "market": data["market"],
        "trend_data": data["trend_data"],
        "signals_version": _get_signals_version(db_path),
        "all_wards": data["all_wards"],
        "all_sources": data["all_sources"],
        "wards_by_city": data["wards_by_city"],
        "active_city": active_city,
        "active_wards": wards,
        "active_sources": sources,
        "active_props": prop_types,
        "trend_period": trend_period,
        "tier": tier,
    })

@app.route("/api/signals")
def api_signals():
    active_city, wards, sources, prop_types, only_drops, trend_period, mos_min = get_base_filters(request)
    area_min, area_max, price_min, price_max = _request_range_filters(request)
    if not wards and active_city in CITY_MAP:
        wards = CITY_MAP[active_city]
    try:
        page = int(request.args.get("page", 1))
        limit = int(request.args.get("limit", 30))
    except ValueError:
        page, limit = 1, 30
    sort = request.args.get("sort", "newest")
    db_path = str(db_mod.DB_PATH.resolve())
    tier = current_tier()
    return jsonify(load_signals(
        db_path,
        sources=sources,
        wards=wards,
        prop_types=prop_types,
        only_drops=only_drops,
        mos_min=mos_min,
        sort=sort,
        page=page,
        limit=limit,
        area_min=area_min,
        area_max=area_max,
        price_min=price_min,
        price_max=price_max,
        tier=tier,
    ))

@app.route("/api/trends")
def api_trends():
    active_city, wards, sources, prop_types, only_drops, trend_period, mos_min = get_base_filters(request)
    area_min, area_max, price_min, price_max = _request_range_filters(request)
    if not wards and active_city in CITY_MAP:
        wards = CITY_MAP[active_city]
    db_path = str(db_mod.DB_PATH.resolve())
    return jsonify({
        "trend_data": load_trend_data(db_path, sources, wards, prop_types, only_drops, trend_period, area_min=area_min, area_max=area_max, price_min=price_min, price_max=price_max),
        "trend_period": trend_period
    })


@app.route("/api/insights")
def api_insights():
    db_path = str(db_mod.DB_PATH.resolve())
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        timeline_rows = conn.execute("""
            SELECT id, kind, title, subtitle, summary, ward, road_ref, project_code,
                   milestone_label, progress_pct, status_tag, severity, event_date,
                   source_url, sort_order, updated_at
            FROM infra_entries
            WHERE active = 1 AND kind = 'timeline'
            ORDER BY sort_order ASC, COALESCE(event_date, updated_at) DESC, id DESC
            LIMIT 100
        """).fetchall()
        policy_rows = conn.execute("""
            SELECT id, kind, title, subtitle, summary, ward, road_ref, project_code,
                   milestone_label, progress_pct, status_tag, severity, event_date,
                   source_url, sort_order, updated_at
            FROM infra_entries
            WHERE active = 1 AND kind = 'policy'
            ORDER BY
              CASE severity
                WHEN 'critical' THEN 1
                WHEN 'warning' THEN 2
                ELSE 3
              END ASC,
              sort_order ASC,
              COALESCE(event_date, updated_at) DESC,
              id DESC
            LIMIT 100
        """).fetchall()
    finally:
        conn.close()

    def _map_row(row):
        x = dict(row)
        x["relative_time"] = _relative_time_label(x.get("event_date") or x.get("updated_at"))
        return x

    return jsonify({
        "timeline": [_map_row(r) for r in timeline_rows],
        "policy_alerts": [_map_row(r) for r in policy_rows],
        "counts": {
            "projects": len(timeline_rows),
            "alerts": len(policy_rows),
        }
    })

@app.route('/api/heatmap')
def api_heatmap():
    active_city, wards, sources, prop_types, only_drops, trend_period, mos_min = get_base_filters(request)
    area_min, area_max, price_min, price_max = _request_range_filters(request)
    db_path = str(db_mod.DB_PATH.resolve())
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    where_parts = [
        "l.probably_sold = 0",
        "COALESCE(l.is_blacklisted,0)=0",
        "COALESCE(l.review_hidden,0)=0",
        "l.price_per_m2 > 0",
        "l.price_per_m2 < 1000"
    ]
    if only_drops:
        where_parts.append("l.price_dropped = 1")
    else:
        where_parts.append("l.possibly_duplicate = 0")
    params = []
    
    # Filter by city if no specific wards selected
    if not wards and active_city and active_city in CITY_MAP:
        wards = CITY_MAP[active_city]

    if wards:
        where_parts.append(f"l.ward IN ({','.join(['?']*len(wards))})")
        params.extend(wards)
    if sources:
        where_parts.append(f"l.source IN ({','.join(['?']*len(sources))})")
        params.extend(sources)
    if prop_types:
        where_parts.append(f"l.property_type IN ({','.join(['?']*len(prop_types))})")
        params.extend(prop_types)
    range_clauses, range_params = _range_filters(area_min, area_max, price_min, price_max, prefix="l.")
    where_parts.extend(range_clauses)
    params.extend(range_params)
    where_sql = " AND ".join(where_parts)
    
    # Market fields use all valid listings; opportunity fields use signal deals only.
    query = f"""
        SELECT l.ward,
               l.price_per_m2,
               l.price_ty,
               l.area_m2,
               v.fair_ppm2,
               v.mos_pct,
               COALESCE(v.is_signal, 0) as is_signal,
               COALESCE(v.is_outlier, 0) as is_outlier
        FROM listings l
        LEFT JOIN valuation_results v ON l.id = v.listing_id
        WHERE {where_sql}
          AND l.ward IS NOT NULL
          AND l.ward != 'unknown'
          AND COALESCE(v.is_outlier, 0) = 0
    """
    rows = conn.execute(query, params).fetchall()
    conn.close()

    grouped = {}
    for r in rows:
        ward = r["ward"]
        item = grouped.setdefault(ward, {
            "prices": [],
            "price_tys": [],
            "fair_tys": [],
            "signal_mos": []
        })
        item["prices"].append(r["price_per_m2"])
        if r["price_ty"]:
            item["price_tys"].append(r["price_ty"])
        if r["fair_ppm2"] and r["area_m2"]:
            item["fair_tys"].append(r["fair_ppm2"] * r["area_m2"] / 1000)
        if r["is_signal"] == 1 and r["mos_pct"] and r["mos_pct"] > 0:
            item["signal_mos"].append(r["mos_pct"])

    heatmap_data = []
    for ward, g in grouped.items():
        total_count = len(g["prices"])
        deal_count = len(g["signal_mos"])
        median_mos = round(statistics.median(g["signal_mos"]), 1) if g["signal_mos"] else 0
        avg_signal_mos = round(sum(g["signal_mos"]) / deal_count, 1) if deal_count else 0
        signal_rate = round((deal_count / total_count) * 100, 1) if total_count else 0
        heatmap_data.append({
            "ward": ward,
            "total_count": total_count,
            "deal_count": deal_count,
            "median_mos": median_mos,
            "avg_signal_mos": avg_signal_mos,
            "signal_rate": signal_rate,
            "count": deal_count,
            "avg_price": round(sum(g["prices"]) / total_count, 1) if total_count else 0,
            "avg_mos": median_mos,
            "avg_price_ty": round(sum(g["price_tys"]) / len(g["price_tys"]), 2) if g["price_tys"] else 0,
            "avg_fair_ty": round(sum(g["fair_tys"]) / len(g["fair_tys"]), 2) if g["fair_tys"] else 0
        })

    heatmap_data.sort(key=lambda x: (x["deal_count"], x["median_mos"]), reverse=True)
    return jsonify(heatmap_data)


@app.route('/api/market-indicators')
@require_tier('vip')
def api_market_indicators():
    active_city, wards, sources, prop_types, only_drops, trend_period, mos_min = get_base_filters(request)
    area_min, area_max, price_min, price_max = _request_range_filters(request)
    if not wards and active_city in CITY_MAP:
        wards = CITY_MAP[active_city]
    db_path = str(db_mod.DB_PATH.resolve())
    return jsonify(load_market_indicators(
        db_path,
        sources=sources,
        wards=wards,
        prop_types=prop_types,
        area_min=area_min,
        area_max=area_max,
        price_min=price_min,
        price_max=price_max,
    ))

@app.route('/api/listings')
@rate_limit("listings")
def api_listings():
    active_city, wards, sources, prop_types, only_drops, trend_period, mos_min = get_base_filters(request)
    area_min, area_max, price_min, price_max = _request_range_filters(request)
    if not wards and active_city in CITY_MAP:
        wards = CITY_MAP[active_city]
    try:
        page = int(request.args.get("page", 1))
        limit = int(request.args.get("limit", 50))
    except ValueError:
        page, limit = 1, 50
    offset = (page - 1) * limit
    
    db_path = str(db_mod.DB_PATH.resolve())
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    where_parts = ["probably_sold = 0", "COALESCE(is_blacklisted,0)=0", "COALESCE(review_hidden,0)=0"]
    if only_drops:
        where_parts.append("price_dropped = 1")
    else:
        where_parts.append("possibly_duplicate = 0")
    params = []
    
    if wards:
        where_parts.append(f"ward IN ({','.join(['?']*len(wards))})")
        params.extend(wards)
    if sources:
        where_parts.append(f"source IN ({','.join(['?']*len(sources))})")
        params.extend(sources)
    if prop_types:
        where_parts.append(f"property_type IN ({','.join(['?']*len(prop_types))})")
        params.extend(prop_types)
    range_clauses, range_params = _range_filters(area_min, area_max, price_min, price_max)
    where_parts.extend(range_clauses)
    params.extend(range_params)
    where_sql = " AND ".join(where_parts)

    sort_col_map = {
        "area": "l.area_m2", "price": "l.price_ty", "price_m2": "l.price_per_m2",
        "fair": "v.fair_ppm2", "date": "COALESCE(l.posted_at, l.crawled_at)",
        "ward": "l.ward", "prop_type": "l.property_type",
    }
    # Default sort = newest first (date DESC). Client can override.
    sort_by = request.args.get("sort_by", "date")
    default_dir = "desc" if sort_by == "date" else "asc"
    sort_dir = "DESC" if request.args.get("sort_dir", default_dir).lower() == "desc" else "ASC"
    order_expr = sort_col_map.get(sort_by, "COALESCE(l.posted_at, l.crawled_at)")

    tier = current_tier()
    fresh_flag = "0 AS is_fresh_locked"
    query = f"""
        SELECT l.*, v.is_signal, v.mos_pct, v.fair_ppm2, v.signal_score,
               {fresh_flag}
        FROM listings l
        LEFT JOIN valuation_results v ON l.id = v.listing_id
        WHERE {where_sql}
        ORDER BY {order_expr} {sort_dir} NULLS LAST
        LIMIT ? OFFSET ?
    """
    query_params = list(params)
    query_params.extend([limit, offset])
    rows = conn.execute(query, query_params).fetchall()
    
    count_query = f"SELECT COUNT(*) FROM listings WHERE {where_sql}"
    total = conn.execute(count_query, params).fetchone()[0]
    
    listing_ids = [r['id'] for r in rows]
    from collections import defaultdict
    img_map = defaultdict(list)
    if listing_ids:
        placeholders = ",".join("?" * len(listing_ids))
        img_rows = conn.execute(f"""
            SELECT listing_id, local_path, img_url
            FROM listing_images
            WHERE listing_id IN ({placeholders})
            ORDER BY listing_id, img_order
        """, listing_ids).fetchall()
        for r in img_rows:
            url = resolve_image_url(r[1], r[2])
            if url:
                img_map[r[0]].append(url)
        
    conn.close()

    listings = [redact_for_tier({
        "id": r['id'], "title": r['title'], "description": r['description'] or "",
        "price_ty": r['price_ty'], "area_m2": r['area_m2'],
        "price_per_m2": round(r['price_per_m2'], 1) if r['price_per_m2'] else None, "prop_type": r['property_type'],
        "ward": r['ward'], "url": r['url'], "is_signal": bool(r['is_signal']), "mos_pct": round(r['mos_pct'], 1) if r['mos_pct'] else 0,
        "fair_ppm2": round(r['fair_ppm2'], 1) if r['fair_ppm2'] else None,
        "days_ago": _days_ago(r['posted_at'] or r['crawled_at']), "is_hot": bool(r['is_hot']), "price_dropped": bool(r['price_dropped']),
        "suspicious_bait": bool(r['suspicious_bait']),
        "drop_pct": r['price_drop_pct'], "price_first_ty": r['price_first_ty'], "duplicate_of_id": r['duplicate_of_id'],
        "source": r['source'], "imgs": img_map.get(r['id'], []),
        "is_fresh_locked": bool(r['is_fresh_locked']),
    }, tier) for r in rows]
    return jsonify({
        "listings": listings,
        "total": total,
        "page": page,
        "limit": limit,
        "pages": (total + limit - 1) // limit if limit > 0 else 1,
        "has_more": page * limit < total,
        "tier": tier,
    })

@app.route('/listing/<int:listing_id>')
def listing_detail(listing_id):
    db_path = str(db_mod.DB_PATH.resolve())
    tier = current_tier()
    data = load_listing_detail(db_path, listing_id, tier=tier)
    if not data:
        return "Listing not found", 404
    
    l = data["listing"]
    imgs = data["images"]
    history_json = json.dumps(data["history"], ensure_ascii=False)
    desc_html = l.get('description', '').replace('\n', '<br>') if l.get('description') else 'Không có mô tả.'
    
    memo = {"locked": True, "reason": "login_required"} if tier == "guest" else load_investment_memo(db_path, listing_id, tier=tier)

    return render_template('listing_detail.html', l=l, imgs=imgs, history_json=history_json, desc_html=desc_html, memo=memo)

@app.route('/api/listing/<int:listing_id>')
def api_listing_detail(listing_id):
    db_path = str(db_mod.DB_PATH.resolve())
    data = load_listing_detail(db_path, listing_id, tier=current_tier())
    if not data:
        return jsonify({"error": "not found"}), 404

    l = data["listing"]
    return jsonify({
        "id": l["id"],
        "title": l["title"],
        "description": l["description"] or "",
        "price_ty": l["price_ty"],
        "area_m2": l["area_m2"],
        "actual_ppm2": round(l["price_per_m2"], 1) if l["price_per_m2"] else None,
        "fair_ppm2": round(l["fair_ppm2"], 1) if l["fair_ppm2"] else None,
        "mos_pct": round(l["mos_pct"], 1) if l["mos_pct"] else 0,
        "ward": l["ward"],
        "property_type": l["property_type"],
        "road_type": l["road_type"],
        "source": l["source"],
        "url": l["url"],
        "road_tier": l["road_tier"] or 0,
        "has_so": None if l["has_so"] is None else bool(l["has_so"]),
        "price_dropped": bool(l["price_dropped"]),
        "drop_pct": l["price_drop_pct"],
        "price_first_ty": l["price_first_ty"],
        "duplicate_of_id": l["duplicate_of_id"],
        "signal_score": l["signal_score"] or 0,
        "days_ago": _days_ago(l["posted_at"] or l["crawled_at"]),
        "imgs": data["images"],
        "tier": data.get("tier"),
    })

@app.route('/api/listing/<int:listing_id>/memo')
def api_listing_memo(listing_id):
    tier = current_tier()
    if tier == "guest":
        return jsonify({"locked": True, "reason": "login_required"}), 403

    db_path = str(db_mod.DB_PATH.resolve())
    memo = load_investment_memo(db_path, listing_id, tier=tier)
    if not memo:
        return jsonify({"error": "not found"}), 404
    return jsonify(memo)

@app.route('/api/history/<int:listing_id>')
def get_price_history(listing_id):
    tier = current_tier()
    with db_mod.get_conn() as conn:
        rows = conn.execute("""
            SELECT recorded_at, price_ty, price_per_m2
            FROM price_history
            WHERE listing_id = ?
            ORDER BY recorded_at ASC, id ASC
        """, (listing_id,)).fetchall()
        curr = conn.execute("""
            SELECT updated_at, price_ty, ward, area_m2, property_type, road_tier, price_per_m2, title
            FROM listings
            WHERE id = ?
        """, (listing_id,)).fetchone()
        history = []
        last_price = None
        has_last = False
        for r in rows:
            price_ty = r[1]
            same_as_last = has_last and _same_price_value(price_ty, last_price)
            if same_as_last:
                continue
            history.append({'date': (r[0] or '')[:10], 'price_ty': price_ty})
            last_price = price_ty
            has_last = True

        if curr and curr["price_ty"]:
            current_price = curr["price_ty"]
            if not history or not _same_price_value(history[-1]['price_ty'], current_price):
                history.append({'date': (curr["updated_at"] or '')[:10], 'price_ty': current_price})

        comps = []
        if curr and curr["ward"]:
            ward = curr["ward"]
            area = curr["area_m2"] or 0
            prop_type = curr["property_type"]
            road_tier = curr["road_tier"]
            curr_ppm2 = curr["price_per_m2"] or 0
            curr_title_tokens = _title_tokens(curr["title"])
            area_min = max(1, area * 0.75) if area else 1
            area_max = area * 1.30 if area else 20000
            ppm2_min = curr_ppm2 * 0.55 if curr_ppm2 else 0
            ppm2_max = curr_ppm2 * 1.45 if curr_ppm2 else 999999
            comp_rows = conn.execute("""
                SELECT id, title, url, price_ty, area_m2, price_per_m2, property_type, road_tier,
                       COALESCE(posted_at, crawled_at) as dt
                FROM listings
                WHERE ward = ? AND id != ? AND price_ty > 0 AND probably_sold = 0
                  AND COALESCE(is_blacklisted,0)=0
                  AND COALESCE(review_hidden,0)=0
                  AND possibly_duplicate = 0
                  AND (? IS NULL OR property_type = ?)
                  AND area_m2 BETWEEN ? AND ?
                  AND (
                    ? <= 0
                    OR COALESCE(price_per_m2, 0) BETWEEN ? AND ?
                  )
                  AND (
                    ? IS NULL
                    OR road_tier IS NULL
                    OR ABS(road_tier - ?) <= 1
                  )
                ORDER BY ABS(area_m2 - ?) ASC,
                         ABS(COALESCE(price_per_m2, 0) - ?) ASC,
                         COALESCE(posted_at, crawled_at) DESC
                LIMIT 20
            """, (
                ward, listing_id,
                prop_type, prop_type,
                area_min, area_max,
                curr_ppm2, ppm2_min, ppm2_max,
                road_tier, road_tier,
                area, curr_ppm2
            )).fetchall()
            ranked = []
            for c in comp_rows:
                area_gap_pct = 0.0
                if area and c["area_m2"]:
                    area_gap_pct = abs(c["area_m2"] - area) / area
                ppm2_gap_pct = 0.0
                if curr_ppm2 and c["price_per_m2"]:
                    ppm2_gap_pct = abs(c["price_per_m2"] - curr_ppm2) / curr_ppm2
                road_gap = 0
                if road_tier is not None and c["road_tier"] is not None:
                    road_gap = abs(c["road_tier"] - road_tier)
                text_sim = _jaccard(curr_title_tokens, _title_tokens(c["title"]))

                # Weighted score: area+ppm2 are strongest, then road tier and title similarity.
                score = 100.0
                score -= min(45.0, area_gap_pct * 100 * 0.55)
                score -= min(30.0, ppm2_gap_pct * 100 * 0.30)
                score -= min(12.0, road_gap * 6.0)
                score += min(12.0, text_sim * 12.0)
                score = round(max(0.0, min(99.0, score)), 1)

                ranked.append({
                    'id': c["id"],
                    'title': (c["title"] or '')[:80],
                    'url': (c["url"] or "") if tier == "admin" else "",
                    'detail_url': f"/listing/{c['id']}",
                    'price_ty': c["price_ty"],
                    'area_m2': c["area_m2"],
                    'price_per_m2': c["price_per_m2"],
                    'property_type': c["property_type"],
                    'date': (c["dt"] or '')[:7],
                    'area_gap_pct': round(area_gap_pct * 100, 1),
                    'match_score': score,
                })

            ranked.sort(key=lambda x: (-x["match_score"], x["area_gap_pct"], -(x["price_per_m2"] or 0)))
            comps = ranked[:6]

        lot_history = _get_lot_history(conn, listing_id, tier=tier)
        # History is open for all tiers (decision 2026-05-15) — price/lot
        # timelines are not commission-sensitive, and they're a key conversion
        # driver. SĐT/URL commission protection is handled elsewhere.
        return jsonify({'history': history, 'lot_history': lot_history, 'comps': comps, 'tier': tier})


def _get_lot_history(conn, listing_id, tier: str = "guest"):
    row = conn.execute("""
        SELECT id, duplicate_of_id
        FROM listings
        WHERE id = ?
    """, (listing_id,)).fetchone()
    if not row:
        return []

    canonical_id = row["duplicate_of_id"] or row["id"]
    rows = conn.execute("""
        SELECT id, source, url, title, price_ty, price_first_ty, price_dropped,
               price_drop_pct, possibly_duplicate, duplicate_of_id,
               COALESCE(posted_at, crawled_at, updated_at) AS dt
        FROM listings
        WHERE id = ? OR duplicate_of_id = ?
        ORDER BY COALESCE(posted_at, crawled_at, updated_at) ASC, id ASC
    """, (canonical_id, canonical_id)).fetchall()

    lot_history = []
    first_price = None
    for r in rows:
        source = (r["source"] or "").lower()
        is_anchor = r["id"] == listing_id or r["id"] == canonical_id
        is_price_drop = bool(r["price_dropped"])
        include_same_price_repost = source == "facebook"
        if not (is_anchor or is_price_drop or include_same_price_repost):
            continue

        price = r["price_ty"]
        if first_price is None and price:
            first_price = price
        change_pct = None
        if first_price and price and not _same_price_value(first_price, price):
            change_pct = round((price - first_price) / first_price * 100, 2)

        lot_history.append({
            "id": r["id"],
            "date": (r["dt"] or "")[:10],
            "source": r["source"],
            "url": r["url"] if tier == "admin" else "",
            "detail_url": f"/listing/{r['id']}",
            "title": (r["title"] or "")[:80],
            "price_ty": price,
            "change_pct": change_pct,
            "price_dropped": is_price_drop,
            "drop_pct": r["price_drop_pct"],
            "is_current": r["id"] == listing_id,
            "is_canonical": r["id"] == canonical_id,
        })

    return lot_history

def _resolve_lead_ack_email(conn, user_id: int | None, guest_email: str | None) -> str | None:
    if guest_email and "@" in guest_email:
        return guest_email
    if user_id:
        row = conn.execute("SELECT email FROM users WHERE id=?", (user_id,)).fetchone()
        if row and row["email"] and "@" in (row["email"] or ""):
            return row["email"]
    return None


def _send_lead_ack_safe(conn, lead_id: int, listing_id, user_id: int | None,
                        guest_name: str | None, guest_email: str | None) -> None:
    """Send lead acknowledgement email; mark notify_email_sent_at. Never raises."""
    try:
        from alerts.email import send_lead_ack
        to_email = _resolve_lead_ack_email(conn, user_id, guest_email)
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
    except Exception as e:
        logger.warning(f"lead ack email failed lead_id={lead_id}: {e}")


def _same_price_value(a, b):
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return abs(float(a) - float(b)) < 0.000001


@app.route("/api/leads", methods=["POST"])
@rate_limit("lead_capture", limits={"guest": 10, "free": 30, "vip": 120, "admin": None})
def api_create_lead():
    payload = request.get_json(silent=True) or {}
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
        return jsonify({"ok": False, "error": "invalid_phone"}), 400

    tier = current_tier()
    u = current_user()
    user_id = u["id"] if u else None
    # VIP/admin → escalate to urgent regardless of client flag
    if tier in ("vip", "admin"):
        urgency = "urgent"

    with db_mod.get_conn() as conn:
        if listing_id is not None:
            row = conn.execute("SELECT id, url FROM listings WHERE id=?", (listing_id,)).fetchone()
            if not row:
                return jsonify({"ok": False, "error": "listing_not_found"}), 404
            listing_url = listing_url or row["url"] or ""

        cur = conn.execute("""
            INSERT INTO lead_captures (listing_id, listing_url, zalo_phone, source_context, note, status,
                                       user_id, tier, urgency)
            VALUES (?, ?, ?, ?, ?, 'new', ?, ?, ?)
        """, (listing_id, listing_url, phone_norm, source_context, note, user_id, tier, urgency))
        lead_id = cur.lastrowid
        _send_lead_ack_safe(conn, lead_id, listing_id, user_id, None, None)

    log_audit(
        user_id=user_id, tier=tier, action="lead_capture",
        listing_id=listing_id,
        context={"urgency": urgency, "source_context": source_context},
    )
    return jsonify({"ok": True, "lead_id": lead_id})


@app.route("/api/lead-capture-guest", methods=["POST"])
@rate_limit("lead_capture", limits={"guest": 10, "free": 30, "vip": 120, "admin": None})
def api_create_guest_lead():
    """Matchmaking request from guest/free/vip. Captures phone and default request note.

    Accepts logged-in users too (admin can still see who clicked the guest form).
    """
    payload = request.get_json(silent=True) or {}
    listing_id = payload.get("listing_id")
    contact_raw = (payload.get("contact") or "").strip()
    note = (payload.get("note") or "").strip()[:500]
    context_ctx = (payload.get("context") or "card_signal").strip()[:50]

    norm = normalize_identifier(contact_raw)
    if not norm or norm[1] != "phone":
        return jsonify({"ok": False, "error": "invalid_phone"}), 400
    ident, ident_type = norm

    tier = current_tier()
    u = current_user()
    user_id = u["id"] if u else None
    urgency = "urgent" if tier in ("vip", "admin") else ("standard" if tier == "free" else "guest")

    listing_url = (payload.get("listing_url") or "").strip()[:500]
    with db_mod.get_conn() as conn:
        if listing_id is not None:
            row = conn.execute("SELECT id, url FROM listings WHERE id=?", (listing_id,)).fetchone()
            if not row:
                return jsonify({"ok": False, "error": "listing_not_found"}), 404
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
            listing_id, listing_url, ident, context_ctx,
            note,
            user_id, tier, urgency, None, None,
        ))
        lead_id = cur.lastrowid
        _send_lead_ack_safe(conn, lead_id, listing_id, user_id, None, None)

    log_audit(
        user_id=user_id, tier=tier, action="lead_capture_guest",
        listing_id=listing_id,
        context={"contact_type": ident_type, "urgency": urgency, "source_context": context_ctx},
    )
    return jsonify({"ok": True, "lead_id": lead_id})


@app.route("/admin/control-room")
def admin_control_room():
    is_admin = _admin_request_authorized()
    return render_template("admin_control_room.html", admin_login_required=not is_admin)


@app.route("/admin/api/leads")
@require_admin_auth
def admin_api_leads():
    status = (request.args.get("status") or "").strip()
    q = (request.args.get("q") or "").strip()
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
    return jsonify({
        "items": [dict(r) for r in rows],
        "summary": {
            "total": total,
            "new": summary.get("new", 0),
            "called": summary.get("called", 0),
            "viewing": summary.get("viewing", 0),
            "deposit": summary.get("deposit", 0),
            "cancelled": summary.get("cancelled", 0),
        }
    })


@app.route("/admin/api/leads/export.csv")
@require_admin_auth
def admin_api_leads_export():
    status = (request.args.get("status") or "").strip()
    q = (request.args.get("q") or "").strip()
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
    for r in rows:
        writer.writerow([r["created_at"], r["zalo_phone"], r["listing_id"], r["listing_title"], r["listing_ward"], r["listing_url"], r["source_context"], r["status"], r["note"]])
    return Response(
        "\ufeff" + out.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=radarbds_leads.csv"},
    )


@app.route("/admin/api/leads/<int:lead_id>/status", methods=["PATCH"])
@require_admin_auth
def admin_api_update_lead_status(lead_id):
    payload = request.get_json(silent=True) or {}
    status = (payload.get("status") or "").strip()
    if status not in LEAD_STATUSES:
        return jsonify({"ok": False, "error": "invalid_status"}), 400
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
            _write_admin_audit(
                conn,
                "lead_status_update",
                "lead",
                lead_id,
                before=dict(before) if before else None,
                after={"id": lead_id, "status": status},
                reason=status,
            )
    return jsonify({"ok": cur.rowcount > 0})


@app.route("/admin/api/infra", methods=["GET", "POST"])
@require_admin_auth
def admin_api_infra():
    if request.method == "GET":
        kind = (request.args.get("kind") or "").strip()
        only_active = request.args.get("active", "1") != "0"
        where = []
        params = []
        if kind:
            if kind not in INFRA_KINDS:
                return jsonify({"ok": False, "error": "invalid_kind"}), 400
            where.append("kind = ?")
            params.append(kind)
        if only_active:
            where.append("active = 1")
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        with db_mod.get_conn() as conn:
            rows = conn.execute(f"""
                SELECT id, created_at, updated_at, kind, title, subtitle, summary,
                       ward, road_ref, project_code, milestone_label, progress_pct,
                       status_tag, severity, event_date, source_url, sort_order, active
                FROM infra_entries
                {where_sql}
                ORDER BY kind ASC, sort_order ASC, COALESCE(event_date, updated_at) DESC, id DESC
                LIMIT 500
            """, params).fetchall()
        items = []
        for r in rows:
            x = dict(r)
            x["relative_time"] = _relative_time_label(x.get("event_date") or x.get("updated_at"))
            items.append(x)
        return jsonify({"items": items})

    payload = request.get_json(silent=True) or {}
    try:
        clean = _clean_infra_payload(payload)
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400

    try:
        entry_id = int(payload.get("id") or 0)
    except (TypeError, ValueError):
        entry_id = 0

    with db_mod.get_conn() as conn:
        if entry_id > 0:
            before = conn.execute("""
                SELECT id, kind, title, subtitle, summary, ward, road_ref, project_code,
                       milestone_label, progress_pct, status_tag, severity, event_date,
                       source_url, sort_order, active
                FROM infra_entries
                WHERE id = ?
            """, (entry_id,)).fetchone()
            if not before:
                return jsonify({"ok": False, "error": "not_found"}), 404
            conn.execute("""
                UPDATE infra_entries
                SET kind=?, title=?, subtitle=?, summary=?, ward=?, road_ref=?, project_code=?,
                    milestone_label=?, progress_pct=?, status_tag=?, severity=?, event_date=?,
                    source_url=?, sort_order=?, active=1, updated_at=datetime('now')
                WHERE id=?
            """, (
                clean["kind"], clean["title"], clean["subtitle"], clean["summary"], clean["ward"],
                clean["road_ref"], clean["project_code"], clean["milestone_label"], clean["progress_pct"],
                clean["status_tag"], clean["severity"], clean["event_date"], clean["source_url"],
                clean["sort_order"], entry_id
            ))
            _write_admin_audit(
                conn,
                "infra_update",
                "infra_entry",
                entry_id,
                before=dict(before),
                after={"id": entry_id, **clean, "active": 1},
                reason=clean["kind"],
            )
            return jsonify({"ok": True, "id": entry_id, "mode": "update"})

        cur = conn.execute("""
            INSERT INTO infra_entries (
                kind, title, subtitle, summary, ward, road_ref, project_code,
                milestone_label, progress_pct, status_tag, severity, event_date,
                source_url, sort_order, active, created_by, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, datetime('now'))
        """, (
            clean["kind"], clean["title"], clean["subtitle"], clean["summary"], clean["ward"],
            clean["road_ref"], clean["project_code"], clean["milestone_label"], clean["progress_pct"],
            clean["status_tag"], clean["severity"], clean["event_date"], clean["source_url"],
            clean["sort_order"], _admin_actor()
        ))
        new_id = cur.lastrowid
        _write_admin_audit(
            conn,
            "infra_create",
            "infra_entry",
            new_id,
            before=None,
            after={"id": new_id, **clean, "active": 1},
            reason=clean["kind"],
        )
    return jsonify({"ok": True, "id": new_id, "mode": "create"})


@app.route("/admin/api/infra/<int:entry_id>", methods=["DELETE", "PATCH"])
@require_admin_auth
def admin_api_infra_item(entry_id):
    if request.method == "DELETE":
        with db_mod.get_conn() as conn:
            before = conn.execute(
                "SELECT id, active, kind, title FROM infra_entries WHERE id=?",
                (entry_id,),
            ).fetchone()
            if not before:
                return jsonify({"ok": False, "error": "not_found"}), 404
            conn.execute(
                "UPDATE infra_entries SET active=0, updated_at=datetime('now') WHERE id=?",
                (entry_id,),
            )
            _write_admin_audit(
                conn,
                "infra_deactivate",
                "infra_entry",
                entry_id,
                before=dict(before),
                after={"id": entry_id, "active": 0},
                reason="deactivate",
            )
        return jsonify({"ok": True})

    payload = request.get_json(silent=True) or {}
    active = payload.get("active")
    if active is None:
        return jsonify({"ok": False, "error": "missing_active"}), 400
    active_val = 1 if bool(active) else 0
    with db_mod.get_conn() as conn:
        before = conn.execute(
            "SELECT id, active, kind, title FROM infra_entries WHERE id=?",
            (entry_id,),
        ).fetchone()
        if not before:
            return jsonify({"ok": False, "error": "not_found"}), 404
        conn.execute(
            "UPDATE infra_entries SET active=?, updated_at=datetime('now') WHERE id=?",
            (active_val, entry_id),
        )
        _write_admin_audit(
            conn,
            "infra_toggle",
            "infra_entry",
            entry_id,
            before=dict(before),
            after={"id": entry_id, "active": active_val},
            reason="toggle",
        )
    return jsonify({"ok": True, "active": active_val})


@app.route("/admin/api/qc/signals")
@require_admin_auth
def admin_api_qc_signals():
    try:
        mos_min = float(request.args.get("mos_min", 0))
        mos_max = float(request.args.get("mos_max", 1000))
    except ValueError:
        mos_min, mos_max = 0, 1000
    ward = (request.args.get("ward") or "").strip()
    source = (request.args.get("source") or "").strip()
    with db_mod.get_conn() as conn:
        where = ["COALESCE(l.probably_sold,0)=0", "COALESCE(l.is_blacklisted,0)=0", "v.is_signal=1", "COALESCE(v.mos_pct,0) BETWEEN ? AND ?"]
        params = [mos_min, mos_max]
        if ward:
            where.append("l.ward = ?")
            params.append(ward)
        if source:
            where.append("l.source = ?")
            params.append(source)
        rows = conn.execute(f"""
            SELECT l.id, l.title, l.url, l.ward, l.source, l.price_ty, l.area_m2,
                   l.property_type, l.price_dropped, l.possibly_duplicate,
                   COALESCE(v.mos_pct,0) AS mos_pct, COALESCE(v.signal_score,0) AS signal_score,
                   f.verdict, f.created_at AS feedback_at
            FROM listings l
            JOIN valuation_results v ON v.listing_id = l.id
            LEFT JOIN ai_training_feedback f ON f.id = (
                SELECT id FROM ai_training_feedback af
                WHERE af.listing_id = l.id
                ORDER BY af.created_at DESC
                LIMIT 1
            )
            WHERE {" AND ".join(where)}
            ORDER BY COALESCE(v.signal_score,0) DESC, COALESCE(v.mos_pct,0) DESC
            LIMIT 500
        """, params).fetchall()
    return jsonify({"items": [dict(r) for r in rows]})


@app.route("/admin/api/ai-training/feedback", methods=["POST"])
@require_admin_auth
def admin_api_ai_training_feedback():
    payload = request.get_json(silent=True) or {}
    try:
        listing_id = int(payload.get("listing_id") or 0)
    except (TypeError, ValueError):
        listing_id = 0
    if listing_id <= 0:
        return jsonify({"ok": False, "error": "invalid_listing_id"}), 400
    with db_mod.get_conn() as conn:
        try:
            result = _save_ai_training_feedback(conn, listing_id, payload)
        except ValueError:
            return jsonify({"ok": False, "error": "invalid_verdict"}), 400
    return jsonify({"ok": True, **result})


@app.route("/admin/api/ai-training/items")
@require_admin_auth
def admin_api_ai_training_items():
    try:
        limit = min(max(int(request.args.get("limit", 50)), 1), 200)
    except ValueError:
        limit = 50
    try:
        offset = max(int(request.args.get("offset", 0)), 0)
    except ValueError:
        offset = 0
    ward = (request.args.get("ward") or "").strip()
    city = (request.args.get("city") or "").strip()
    try:
        mos_min = float(request.args.get("mos_min") or 0)
    except ValueError:
        mos_min = 0.0
    sort = (request.args.get("sort") or "default").strip()
    queue = (request.args.get("queue") or "main").strip()
    if queue not in ("main", "recheck", "source_qc"):
        queue = "main"

    where = [
        "COALESCE(l.probably_sold,0)=0",
        "COALESCE(l.is_blacklisted,0)=0",
    ]
    params = []
    if queue == "recheck":
        where.append("v.is_signal = 1")
        extraction_placeholders = ",".join("?" for _ in EXTRACTION_RECHECK_VERDICTS)
        where.extend([
            "COALESCE(l.review_hidden,0)=1",
            "f.verdict = 'bad_data'",
            f"f.extraction_verdict IN ({extraction_placeholders})",
        ])
        params.extend(sorted(EXTRACTION_RECHECK_VERDICTS))
    elif queue == "source_qc":
        where.extend([
            "COALESCE(l.review_hidden,0)=0",
            "l.source = 'guland'",
            "COALESCE(v.source_quality_recheck,0)=1",
        ])
    else:
        where.append("v.is_signal = 1")
        where.append("COALESCE(l.review_hidden,0)=0")
    if ward:
        where.append("l.ward = ?")
        params.append(ward)
    elif city and city in CITY_MAP:
        city_wards = CITY_MAP[city]
        placeholders = ",".join("?" * len(city_wards))
        where.append(f"l.ward IN ({placeholders})")
        params.extend(city_wards)
    if mos_min > 0:
        where.append("COALESCE(v.mos_pct,0) >= ?")
        params.append(mos_min)
    where_sql = " AND ".join(where)

    order_map = {
        "newest": "COALESCE(l.posted_at, l.first_seen_at, l.crawled_at) DESC",
        "cheapest": "COALESCE(NULLIF(l.price_ty,0), 1e9) ASC",
        "mos": "COALESCE(v.mos_pct,0) DESC",
        "score": "COALESCE(v.signal_score,0) DESC",
    }
    order_sql = (
        order_map[sort] + ", COALESCE(v.signal_score,0) DESC"
        if sort in order_map
        else """
          CASE WHEN f.id IS NULL THEN 0 ELSE 1 END ASC,
          (CASE WHEN l.area_m2 IS NULL OR l.ward IS NULL OR l.property_type IS NULL OR l.road_tier IS NULL THEN 20 ELSE 0 END) DESC,
          COALESCE(v.mos_pct,0) DESC,
          COALESCE(v.signal_score,0) DESC
        """
    )
    feedback_join = """
            LEFT JOIN ai_training_feedback f ON f.id = (
                SELECT id FROM ai_training_feedback
                WHERE listing_id = l.id
                ORDER BY created_at DESC
                LIMIT 1
            )
    """

    with db_mod.get_conn() as conn:
        rows = conn.execute(f"""
            SELECT l.id, l.title, l.url, l.source, l.ward, l.property_type,
                   l.price_ty, l.price_per_m2, l.area_m2, l.frontage_m, l.depth_m, l.road_tier,
                   l.road_type, l.has_so, l.description,
                   COALESCE(l.posted_at, l.first_seen_at, l.crawled_at) AS posted_display,
                   v.mos_pct, v.signal_score, v.fair_ppm2, v.actual_ppm2,
                   v.segment, v.n_segment, v.source_quality_flags, v.source_quality_recheck,
                   f.verdict AS feedback_verdict,
                   f.extraction_verdict, f.valuation_verdict, f.reason_tags,
                   r.verdict AS ai_verdict, r.confidence AS ai_confidence,
                   r.reasoning AS ai_reasoning, r.red_flags AS ai_red_flags,
                   r.needs_map_check AS ai_needs_map_check
            FROM listings l
            JOIN valuation_results v ON v.listing_id = l.id
            {feedback_join}
            LEFT JOIN ai_deal_review r ON r.id = (
                SELECT id FROM ai_deal_review
                WHERE listing_id = l.id
                ORDER BY created_at DESC
                LIMIT 1
            )
            WHERE {where_sql}
            ORDER BY {order_sql}
            LIMIT ? OFFSET ?
        """, params + [limit, offset]).fetchall()

        pending = conn.execute(f"""
            SELECT COUNT(*) c
            FROM listings l
            JOIN valuation_results v ON v.listing_id = l.id
            {feedback_join}
            WHERE {where_sql} AND f.id IS NULL
        """, params).fetchone()["c"]

        total = conn.execute(f"""
            SELECT COUNT(*) c
            FROM listings l
            JOIN valuation_results v ON v.listing_id = l.id
            {feedback_join}
            WHERE {where_sql}
        """, params).fetchone()["c"]
        if queue == "recheck":
            pending = total
        if queue == "source_qc":
            pending = total

        ward_where = [
            "COALESCE(l.probably_sold,0)=0",
            "COALESCE(l.is_blacklisted,0)=0",
            "l.ward IS NOT NULL",
            "l.ward <> ''",
        ]
        ward_params = []
        if queue == "recheck":
            ward_where.append("v.is_signal = 1")
            extraction_placeholders = ",".join("?" for _ in EXTRACTION_RECHECK_VERDICTS)
            ward_where.extend([
                "COALESCE(l.review_hidden,0)=1",
                "f.verdict = 'bad_data'",
                f"f.extraction_verdict IN ({extraction_placeholders})",
            ])
            ward_params.extend(sorted(EXTRACTION_RECHECK_VERDICTS))
        elif queue == "source_qc":
            ward_where.extend([
                "COALESCE(l.review_hidden,0)=0",
                "l.source = 'guland'",
                "COALESCE(v.source_quality_recheck,0)=1",
            ])
        else:
            ward_where.append("v.is_signal = 1")
            ward_where.append("COALESCE(l.review_hidden,0)=0")

        ward_rows = conn.execute(f"""
            SELECT DISTINCT l.ward
            FROM listings l
            JOIN valuation_results v ON v.listing_id = l.id
            {feedback_join}
            WHERE {" AND ".join(ward_where)}
            ORDER BY l.ward
        """, ward_params).fetchall()
        wards = [w["ward"] for w in ward_rows]
        ward_cities = {c: [ww for ww in ws if ww in wards] for c, ws in CITY_MAP.items()}
        ward_cities = {c: ws for c, ws in ward_cities.items() if ws}

        items = []
        for r in rows:
            d = dict(r)
            fair_ty = None
            if d.get("fair_ppm2") and d.get("area_m2"):
                fair_ty = round(float(d["fair_ppm2"]) * float(d["area_m2"]) / 1000, 2)
            d["fair_ty"] = fair_ty
            actual_ppm2 = d.get("actual_ppm2") or d.get("price_per_m2")
            if not actual_ppm2 and d.get("price_ty") and d.get("area_m2"):
                actual_ppm2 = float(d["price_ty"]) * 1000 / float(d["area_m2"])
            if actual_ppm2:
                d["actual_ppm2"] = round(float(actual_ppm2), 1)
            if d.get("price_per_m2"):
                d["price_per_m2"] = round(float(d["price_per_m2"]), 1)
            if d.get("fair_ppm2"):
                d["fair_ppm2"] = round(float(d["fair_ppm2"]), 1)
            imgs = conn.execute(
                "SELECT local_path, img_url FROM listing_images "
                "WHERE listing_id=? ORDER BY img_order",
                (d["id"],),
            ).fetchall()
            gallery = []
            for im in imgs:
                u = resolve_image_url(im["local_path"], im["img_url"])
                if u:
                    gallery.append(u)
            d["images"] = gallery
            d["image"] = gallery[0] if gallery else resolve_image_url("", "")
            d["detail_url"] = f"/listing/{d['id']}"
            d["is_recheck"] = queue == "recheck"
            d["is_source_qc"] = queue == "source_qc"
            missing = []
            for key, label in (("ward", "phuong"), ("property_type", "loai_hinh"), ("area_m2", "dien_tich"), ("road_tier", "duong")):
                if d.get(key) in (None, "", 0):
                    missing.append(label)
            d["explain"] = {
                "mos_pct": d.get("mos_pct"),
                "signal_score": d.get("signal_score"),
                "segment": d.get("segment"),
                "n_segment": d.get("n_segment"),
                "fair_ty": fair_ty,
                "actual_ty": d.get("price_ty"),
                "missing_fields": missing,
            }
            items.append(d)
    return jsonify({
        "items": items,
        "pending": pending,
        "total": total,
        "offset": offset,
        "has_more": (offset + len(items)) < total,
        "wards": wards,
        "ward_cities": ward_cities,
        "queue": queue,
        "queue_label": (
            "Recheck sau fix" if queue == "recheck"
            else "Guland QC" if queue == "source_qc"
            else "Review mới"
        ),
    })


@app.route("/admin/api/ai-training/disagreements")
@require_admin_auth
def admin_api_ai_training_disagreements():
    """Read-only: nơi nhãn người (f) và verdict Claude (r) xung đột bucket.

    Lọc CHẶT — chỉ hiện khi cả hai phía đã có nhãn latest VÀ bucket ngược nhau;
    `maybe` / `insufficient_info` (NEUTRAL) tự loại. Chỉ surfacing, KHÔNG ghi.
    """
    with db_mod.get_conn() as conn:
        rows = conn.execute("""
            SELECT l.id, l.title, l.url, l.ward, l.price_ty, l.area_m2,
                   v.mos_pct, v.signal_score,
                   f.verdict AS human_verdict, f.created_at AS human_at,
                   r.verdict AS ai_verdict, r.confidence AS ai_confidence,
                   r.reasoning AS ai_reasoning, r.red_flags AS ai_red_flags,
                   r.needs_map_check AS ai_needs_map_check
            FROM listings l
            JOIN valuation_results v ON v.listing_id = l.id
            JOIN ai_training_feedback f ON f.id = (
                SELECT id FROM ai_training_feedback
                WHERE listing_id = l.id ORDER BY created_at DESC LIMIT 1
            )
            JOIN ai_deal_review r ON r.id = (
                SELECT id FROM ai_deal_review
                WHERE listing_id = l.id ORDER BY created_at DESC LIMIT 1
            )
            WHERE (
                   (f.verdict IN ('good','correct','cheap_real')
                        AND r.verdict IN ('suspect','not_cheap'))
                OR (f.verdict IN ('bad','spam','sold','fake_price','bad_data','fair','overpriced','cannot_price')
                        AND r.verdict = 'cheap_real')
            )
            ORDER BY COALESCE(r.confidence,0) DESC, v.signal_score DESC
        """).fetchall()
    return jsonify({"items": [dict(r) for r in rows]})


@app.route("/admin/api/qc/duplicates")
@require_admin_auth
def admin_api_qc_duplicates():
    with db_mod.get_conn() as conn:
        rows = conn.execute("""
            SELECT l.id, l.title, l.url, l.source, l.ward, l.property_type, l.price_ty, l.area_m2,
                   l.frontage_m, l.depth_m, l.description, COALESCE(l.posted_at, l.crawled_at, l.updated_at) AS dt,
                   l.duplicate_of_id, c.title AS canonical_title, c.url AS canonical_url,
                   c.source AS canonical_source, c.ward AS canonical_ward,
                   c.property_type AS canonical_property_type,
                   c.price_ty AS canonical_price_ty, c.area_m2 AS canonical_area_m2,
                   c.frontage_m AS canonical_frontage_m, c.depth_m AS canonical_depth_m,
                   c.description AS canonical_description,
                   COALESCE(c.posted_at, c.crawled_at, c.updated_at) AS canonical_dt,
                   li.local_path AS img_local, li.img_url AS img_url,
                   ci.local_path AS canonical_img_local, ci.img_url AS canonical_img_url
            FROM listings l
            JOIN listings c ON c.id = l.duplicate_of_id
            LEFT JOIN listing_images li ON li.id = (
                SELECT id FROM listing_images WHERE listing_id = l.id ORDER BY img_order LIMIT 1
            )
            LEFT JOIN listing_images ci ON ci.id = (
                SELECT id FROM listing_images WHERE listing_id = c.id ORDER BY img_order LIMIT 1
            )
            WHERE COALESCE(l.probably_sold,0)=0
              AND COALESCE(l.is_blacklisted,0)=0
              AND l.possibly_duplicate=1
            ORDER BY l.updated_at DESC
            LIMIT 500
        """).fetchall()
    items = []
    for r in rows:
        item = dict(r)
        item["detail_url"] = f"/listing/{item['id']}"
        item["canonical_detail_url"] = f"/listing/{item['duplicate_of_id']}"
        item["image"] = resolve_image_url(item.pop("img_local"), item.pop("img_url"))
        item["canonical_image"] = resolve_image_url(item.pop("canonical_img_local"), item.pop("canonical_img_url"))
        item["description_excerpt"] = (item.get("description") or "")[:260]
        item["canonical_description_excerpt"] = (item.get("canonical_description") or "")[:260]
        items.append(item)
    return jsonify({"items": items})


@app.route("/admin/api/qc/duplicates/merge", methods=["POST"])
@require_admin_auth
def admin_api_qc_duplicates_merge():
    payload = request.get_json(silent=True) or {}
    listing_id = int(payload.get("listing_id") or 0)
    target_id = int(payload.get("target_listing_id") or 0)
    note = (payload.get("note") or "").strip()[:500]
    if not listing_id or not target_id or listing_id == target_id:
        return jsonify({"ok": False, "error": "invalid_ids"}), 400
    with db_mod.get_conn() as conn:
        before = conn.execute(
            "SELECT id, possibly_duplicate, duplicate_of_id FROM listings WHERE id=?",
            (listing_id,),
        ).fetchone()
        conn.execute("""
            INSERT INTO dedup_overrides (action, listing_id, target_listing_id, note, active, updated_at)
            VALUES ('merge', ?, ?, ?, 1, datetime('now'))
        """, (listing_id, target_id, note or None))
        conn.execute(
            "UPDATE listings SET possibly_duplicate=1, duplicate_of_id=? WHERE id=?",
            (target_id, listing_id),
        )
        _write_admin_audit(
            conn,
            "dedup_merge",
            "listing",
            listing_id,
            before=dict(before) if before else None,
            after={"id": listing_id, "possibly_duplicate": 1, "duplicate_of_id": target_id},
            reason=note or "merge",
        )
    return jsonify({"ok": True})


@app.route("/admin/api/qc/duplicates/split", methods=["POST"])
@require_admin_auth
def admin_api_qc_duplicates_split():
    payload = request.get_json(silent=True) or {}
    listing_id = int(payload.get("listing_id") or 0)
    target_id = int(payload.get("target_listing_id") or 0)
    note = (payload.get("note") or "").strip()[:500]
    if not listing_id or not target_id or listing_id == target_id:
        return jsonify({"ok": False, "error": "invalid_ids"}), 400
    with db_mod.get_conn() as conn:
        before = conn.execute(
            "SELECT id, possibly_duplicate, duplicate_of_id FROM listings WHERE id=?",
            (listing_id,),
        ).fetchone()
        conn.execute("""
            INSERT INTO dedup_overrides (action, listing_id, target_listing_id, note, active, updated_at)
            VALUES ('split', ?, ?, ?, 1, datetime('now'))
        """, (listing_id, target_id, note or None))
        conn.execute("UPDATE listings SET possibly_duplicate=0, duplicate_of_id=NULL WHERE id=?", (listing_id,))
        _write_admin_audit(
            conn,
            "dedup_split",
            "listing",
            listing_id,
            before=dict(before) if before else None,
            after={"id": listing_id, "possibly_duplicate": 0, "duplicate_of_id": None},
            reason=note or "split",
        )
    return jsonify({"ok": True})


@app.route("/admin/api/blacklist", methods=["GET", "POST", "DELETE"])
@require_admin_auth
def admin_api_blacklist():
    if request.method == "GET":
        with db_mod.get_conn() as conn:
            rows = conn.execute("""
                SELECT id, phone_norm, reason, active, created_at, updated_at
                FROM broker_blacklist
                ORDER BY updated_at DESC
            """).fetchall()
        return jsonify({"items": [dict(r) for r in rows]})

    payload = request.get_json(silent=True) or {}
    if request.method == "POST":
        raw_phone = (payload.get("phone") or "").strip()
        phone_norm = normalize_phone(raw_phone)
        reason = (payload.get("reason") or "").strip()[:500]
        if not phone_norm or len(phone_norm) < 9:
            return jsonify({"ok": False, "error": "invalid_phone"}), 400
        with db_mod.get_conn() as conn:
            before = conn.execute(
                "SELECT phone_norm, active, reason FROM broker_blacklist WHERE phone_norm=?",
                (phone_norm,),
            ).fetchone()
            conn.execute("""
                INSERT INTO broker_blacklist (phone_norm, reason, active, updated_at)
                VALUES (?, ?, 1, datetime('now'))
                ON CONFLICT(phone_norm) DO UPDATE SET
                    reason=excluded.reason,
                    active=1,
                    updated_at=datetime('now')
            """, (phone_norm, reason or None))
            # hide old rows immediately
            conn.execute("""
                UPDATE listings
                SET is_blacklisted=1, blacklisted_at=datetime('now'), blacklist_phone_norm=?
                WHERE substr(replace(replace(replace(replace(replace(COALESCE(contact_phone,''), ' ', ''), '.', ''), '-', ''), '(', ''), ')', ''), -9) = ?
            """, (phone_norm, phone_norm))
            _write_admin_audit(
                conn,
                "blacklist_activate",
                "phone",
                None,
                before=dict(before) if before else None,
                after={"phone_norm": phone_norm, "active": 1, "reason": reason or None},
                reason=reason or "blacklist",
            )
        return jsonify({"ok": True})

    # DELETE (deactivate)
    phone_norm = normalize_phone((payload.get("phone") or "").strip())
    if not phone_norm:
        return jsonify({"ok": False, "error": "invalid_phone"}), 400
    with db_mod.get_conn() as conn:
        before = conn.execute(
            "SELECT phone_norm, active, reason FROM broker_blacklist WHERE phone_norm=?",
            (phone_norm,),
        ).fetchone()
        conn.execute("UPDATE broker_blacklist SET active=0, updated_at=datetime('now') WHERE phone_norm=?", (phone_norm,))
        _write_admin_audit(
            conn,
            "blacklist_deactivate",
            "phone",
            None,
            before=dict(before) if before else None,
            after={"phone_norm": phone_norm, "active": 0},
            reason="deactivate",
        )
    return jsonify({"ok": True})


@app.route("/admin/api/audit")
@require_admin_auth
def admin_api_audit():
    entity_type = (request.args.get("entity_type") or "").strip()
    entity_id = request.args.get("entity_id")
    where = []
    params = []
    if entity_type:
        where.append("entity_type = ?")
        params.append(entity_type)
    if entity_id:
        try:
            params.append(int(entity_id))
            where.append("entity_id = ?")
        except ValueError:
            return jsonify({"ok": False, "error": "invalid_entity_id"}), 400
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    with db_mod.get_conn() as conn:
        rows = conn.execute(f"""
            SELECT id, created_at, actor, action, entity_type, entity_id,
                   before_json, after_json, reason
            FROM admin_audit_log
            {where_sql}
            ORDER BY created_at DESC, id DESC
            LIMIT 200
        """, params).fetchall()
    return jsonify({"items": [dict(r) for r in rows]})


# ═══════════════════════════════════════════════════════════════════════════
# Admin: User management (grant/revoke VIP, ban)
# ═══════════════════════════════════════════════════════════════════════════
def _user_admin_row(row):
    if not row:
        return None
    d = dict(row)
    # Compute effective tier (VIP can be expired)
    eff = _effective_tier_from_user(d)
    d["effective_tier"] = eff
    # Strip password_hash, telegram_link_token (sensitive)
    d.pop("password_hash", None)
    d.pop("telegram_link_token", None)
    d.pop("telegram_link_expires_at", None)
    d["telegram_linked"] = bool(d.pop("telegram_chat_id", None))
    return d


@app.route("/admin/api/users")
@require_admin_auth
def admin_api_users():
    tier_filter = (request.args.get("tier") or "").strip()
    q = (request.args.get("q") or "").strip()
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
    summary = {r["tier"]: r["n"] for r in summary_rows}
    return jsonify({
        "items": [_user_admin_row(r) for r in rows],
        "summary": {
            "total": sum(summary.values()) + banned,
            "free": summary.get("free", 0),
            "vip": summary.get("vip", 0),
            "admin": summary.get("admin", 0),
            "banned": banned,
        },
    })


@app.route("/admin/api/users/<int:user_id>/grant-vip", methods=["POST"])
@require_admin_auth
def admin_api_grant_vip(user_id):
    payload = request.get_json(silent=True) or {}
    try:
        days = int(payload.get("days") or 30)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "invalid_days"}), 400
    if days <= 0 or days > 3650:
        return jsonify({"ok": False, "error": "invalid_days"}), 400
    with db_mod.get_conn() as conn:
        before = conn.execute(
            "SELECT id, tier, vip_expires_at FROM users WHERE id=?", (user_id,)
        ).fetchone()
        if not before:
            return jsonify({"ok": False, "error": "not_found"}), 404
        # Extend from max(now, current vip_expires_at) so stacking days works
        now_iso = datetime.utcnow().isoformat(timespec="seconds")
        cur_exp = before["vip_expires_at"]
        base_iso = cur_exp if (cur_exp and cur_exp > now_iso) else now_iso
        try:
            base_dt = datetime.fromisoformat(base_iso)
        except ValueError:
            base_dt = datetime.utcnow()
        new_exp = (base_dt + timedelta(days=days)).isoformat(timespec="seconds")
        conn.execute(
            "UPDATE users SET tier='vip', vip_expires_at=? WHERE id=?",
            (new_exp, user_id),
        )
        _write_admin_audit(
            conn, "user_grant_vip", "user", user_id,
            before=dict(before),
            after={"id": user_id, "tier": "vip", "vip_expires_at": new_exp},
            reason=f"+{days}d",
        )
    try:
        log_audit(user_id=user_id, tier="vip", action="vip_granted",
                  context={"days": days, "vip_expires_at": new_exp})
    except Exception:
        pass
    return jsonify({"ok": True, "vip_expires_at": new_exp, "tier": "vip"})


@app.route("/admin/api/users/<int:user_id>/revoke", methods=["POST"])
@require_admin_auth
def admin_api_revoke_vip(user_id):
    with db_mod.get_conn() as conn:
        before = conn.execute(
            "SELECT id, tier, vip_expires_at FROM users WHERE id=?", (user_id,)
        ).fetchone()
        if not before:
            return jsonify({"ok": False, "error": "not_found"}), 404
        conn.execute(
            "UPDATE users SET tier='free', vip_expires_at=NULL WHERE id=?",
            (user_id,),
        )
        _write_admin_audit(
            conn, "user_revoke_vip", "user", user_id,
            before=dict(before),
            after={"id": user_id, "tier": "free", "vip_expires_at": None},
        )
    try:
        log_audit(user_id=user_id, tier="free", action="vip_revoked")
    except Exception:
        pass
    return jsonify({"ok": True, "tier": "free"})


@app.route("/admin/api/users/<int:user_id>/ban", methods=["POST"])
@require_admin_auth
def admin_api_ban_user(user_id):
    payload = request.get_json(silent=True) or {}
    banned = 1 if payload.get("banned", True) else 0
    with db_mod.get_conn() as conn:
        before = conn.execute(
            "SELECT id, is_banned FROM users WHERE id=?", (user_id,)
        ).fetchone()
        if not before:
            return jsonify({"ok": False, "error": "not_found"}), 404
        conn.execute("UPDATE users SET is_banned=? WHERE id=?", (banned, user_id))
        if banned:
            # Kill all active sessions
            conn.execute("DELETE FROM user_sessions WHERE user_id=?", (user_id,))
        _write_admin_audit(
            conn, "user_ban" if banned else "user_unban", "user", user_id,
            before=dict(before), after={"id": user_id, "is_banned": banned},
        )
    return jsonify({"ok": True, "is_banned": bool(banned)})


def _title_tokens(text):
    if not text:
        return set()
    norm = re.sub(r"[^a-z0-9\s]", " ", str(text).lower())
    toks = [t for t in norm.split() if len(t) > 2]
    return set(toks)


def _jaccard(a, b):
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    if union == 0:
        return 0.0
    return inter / union

@app.route('/api/chat', methods=['POST'])
def api_chat():
    data = request.json
    message = data.get("message")
    history = data.get("history", [])
    
    if not message:
        return jsonify({"error": "No message provided"}), 400
        
    db_path = str(db_mod.DB_PATH.resolve())
    bot = AIBot(db_path)
    response = bot.chat(message, history)
    
    return jsonify({"response": response})

def ensure_perf_indexes():
    db_mod.init_schema()
    with db_mod.get_conn() as conn:
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_listings_filter_fast
            ON listings(ward, source, property_type, probably_sold, possibly_duplicate)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_listings_blacklist
            ON listings(is_blacklisted, blacklist_phone_norm, probably_sold)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_listings_ward_ppm2
            ON listings(ward, price_per_m2)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_images_listing_order
            ON listing_images(listing_id, img_order)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_valuation_signal_score
            ON valuation_results(is_signal, signal_score DESC, mos_pct DESC)
        """)
        conn.commit()

if __name__ == "__main__":
    ensure_perf_indexes()
    app.run(host="127.0.0.1", port=5000, debug=True)
