from __future__ import annotations

import os
import json
import logging
import mimetypes
import platform
import subprocess
import statistics
import re
import time
import urllib.request
import threading
from copy import deepcopy
from functools import wraps
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4
from flask import Flask, render_template, request, jsonify, send_from_directory, Response, make_response, abort, redirect
from config import database_sqlite as db_mod
from db.connection import connect, get_conn
from db.moderation import normalize_phone
from config.settings import (
    LEGAL_IMAGE_EVIDENCE_ENABLED,
    PUBLIC_BASE_URL,
    GOOGLE_ANALYTICS_ID,
    GOOGLE_SEARCH_CONSOLE_VERIFICATION,
    SITE_DESCRIPTION,
    SITE_KEYWORDS,
    SITE_NAME,
    SITE_OG_IMAGE,
    SITE_TITLE,
)
from config.seo_pages import SEO_PAGES

mimetypes.add_type("image/webp", ".webp")

# Import the extracted services
from services.market_data import load_counts, load_data, load_dashboard_summary, load_signals, load_trend_data, load_listing_detail, load_market_indicators, get_base_filters, get_city_for_ward, CITY_MAP, _days_ago, resolve_image_url, _range_filters, redact_for_tier, normalize_search_keyword, keyword_search_filter, group_price_drop_filter_sql, signal_badge_metadata, normalize_date_range, listing_date_range_filter
from services.signal_quality import (
    LATEST_VALUATION_CTE,
    actionable_listing_sql,
    actionable_signal_sql,
    split_quality_flags,
)
from services.advisory_memo import build_admin_valuation_workflow_markdown
from services import admin_leads, admin_quality, admin_users

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


@app.context_processor
def inject_google_site_tags():
    host = (request.host or "").split(":", 1)[0].strip("[]").lower()
    local_host = host in {"localhost", "127.0.0.1", "::1"}
    analytics_id = GOOGLE_ANALYTICS_ID
    if local_host and os.getenv("RADAR_ENABLE_LOCAL_ANALYTICS", "").lower() not in {"1", "true", "yes", "on"}:
        analytics_id = ""
    return {
        "GOOGLE_ANALYTICS_ID": analytics_id,
        "GOOGLE_SEARCH_CONSOLE_VERIFICATION": GOOGLE_SEARCH_CONSOLE_VERIFICATION,
    }


@app.after_request
def add_api_cache_headers(response):
    if request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


LEAD_STATUSES = admin_leads.LEAD_STATUSES
POSITIVE_REVIEW_VERDICTS = {"good", "correct", "cheap_real"}
HARD_HIDE_REVIEW_VERDICTS = {"bad", "spam", "sold", "fake_price"}
SOFT_HIDE_REVIEW_VERDICTS = {"bad_data", "fair", "overpriced", "cannot_price"}
ADMIN_CONTROL_ROOM_PANEL_SLUGS = {
    "crm": "crm",
    "quality": "data-quality",
    "crawl": "facebook-crawl",
    "training": "ai-training",
    "infra": "infrastructure",
    "users": "users",
}
ADMIN_CONTROL_ROOM_SLUG_TO_PANEL = {
    slug: panel for panel, slug in ADMIN_CONTROL_ROOM_PANEL_SLUGS.items()
}
HIDE_REVIEW_VERDICTS = HARD_HIDE_REVIEW_VERDICTS | SOFT_HIDE_REVIEW_VERDICTS
VALUATION_VERDICTS = {"cheap_real", "fair", "overpriced", "fake_price", "cannot_price"}
EXTRACTION_RECHECK_VERDICTS = {"wrong_ward", "wrong_road", "wrong_property_type", "wrong_price", "wrong_area"}
TRAINING_VERDICTS = POSITIVE_REVIEW_VERDICTS | HIDE_REVIEW_VERDICTS | {"maybe"}
INFRA_KINDS = {"timeline", "policy"}
INFRA_STATUS = {"done", "in_progress", "planned"}
INFRA_SEVERITY = {"critical", "warning", "info"}
FACEBOOK_PROFILE_PATH = Path(__file__).resolve().parent / "data" / "facebook_profiles.json"
FACEBOOK_MANUAL_CRAWL_MAX_LIMIT = 950
FACEBOOK_CRAWL_JOBS: dict[str, dict] = {}
FACEBOOK_CRAWL_JOB_ORDER: list[str] = []
FACEBOOK_CRAWL_LOCK = threading.Lock()


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _insights_enabled() -> bool:
    return _env_flag("RADAR_INSIGHTS_ENABLED", False)


def _image_order_sql(prefix: str = "") -> str:
    col = f"{prefix}." if prefix else ""
    if LEGAL_IMAGE_EVIDENCE_ENABLED:
        return f"CASE WHEN {col}img_type='so_hong' THEN 0 ELSE 1 END, {col}img_order, {col}id"
    return f"{col}img_order, {col}id"


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


def _clamp_int(value, default: int, min_value: int, max_value: int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = default
    return max(min_value, min(max_value, n))


def _read_facebook_profile_config() -> list[dict]:
    return admin_quality.read_facebook_profile_config(FACEBOOK_PROFILE_PATH)


def _write_facebook_profile_config(profiles: list[dict]) -> list[dict]:
    return admin_quality.write_facebook_profile_config(FACEBOOK_PROFILE_PATH, profiles)


def _facebook_profile_lookup(url: str) -> dict | None:
    return admin_quality.facebook_profile_lookup(url, _read_facebook_profile_config())


def _facebook_profile_stats(profile_urls: list[str]) -> dict:
    return admin_quality.facebook_profile_stats(profile_urls, conn_factory=get_conn)


def _missing_image_summary(conn, source: str | None = None) -> dict:
    return admin_quality.missing_image_summary(conn, source=source)


def _facebook_missing_image_summary(conn) -> dict:
    return admin_quality.facebook_missing_image_summary(conn)


def _facebook_crawl_summary() -> dict:
    return admin_quality.facebook_crawl_summary(
        conn_factory=get_conn,
        jobs=FACEBOOK_CRAWL_JOBS,
        job_order=FACEBOOK_CRAWL_JOB_ORDER,
        lock=FACEBOOK_CRAWL_LOCK,
        public_job_fn=_public_crawl_job,
        crawl_ops_summary_fn=_crawl_ops_summary,
    )


def _daily_crawl_schedule_status() -> dict:
    return admin_quality.daily_crawl_schedule_status(
        system_fn=platform.system,
        run_fn=subprocess.run,
    )


def _active_radar_lock_blockers() -> list[dict]:
    return admin_quality.active_radar_lock_blockers(conn_factory=get_conn)


def _crawl_ops_summary() -> dict:
    return admin_quality.crawl_ops_summary(
        conn_factory=get_conn,
        schedule_status_fn=_daily_crawl_schedule_status,
        active_lock_blockers_fn=_active_radar_lock_blockers,
    )


def _apify_tokens_public() -> list[dict]:
    return admin_quality.apify_tokens_public()


def _data_quality_summary() -> dict:
    return admin_quality.data_quality_summary(
        conn_factory=get_conn,
        apify_tokens_fn=_apify_tokens_public,
        crawl_ops_summary_fn=_crawl_ops_summary,
    )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_iso(timespec: str = "seconds") -> str:
    return _utc_now().replace(tzinfo=None).isoformat(timespec=timespec)


def _utc_iso_z(timespec: str = "seconds") -> str:
    return _utc_now().isoformat(timespec=timespec).replace("+00:00", "Z")


def _append_crawl_log(job: dict, message: str) -> None:
    entry = f"{_utc_iso_z()} {message}"
    with FACEBOOK_CRAWL_LOCK:
        job.setdefault("logs", []).append(entry)
        job["logs"] = job["logs"][-120:]


def _set_crawl_progress(job: dict, pct: int, stage: str | None = None, label: str | None = None) -> None:
    with FACEBOOK_CRAWL_LOCK:
        job["progress_pct"] = _clamp_int(pct, 0, 0, 100)
        if stage:
            job["stage"] = stage
        if label:
            job["progress_label"] = label


def _public_crawl_job(job: dict | None) -> dict | None:
    if not job:
        return None
    return {
        "id": job.get("id"),
        "status": job.get("status"),
        "stage": job.get("stage"),
        "mode": job.get("mode"),
        "profile_url": job.get("profile_url"),
        "broker_name": job.get("broker_name"),
        "limit": job.get("limit"),
        "days": job.get("days"),
        "download_images": job.get("download_images"),
        "started_at": job.get("started_at"),
        "finished_at": job.get("finished_at"),
        "progress_pct": job.get("progress_pct", 0),
        "progress_label": job.get("progress_label") or job.get("stage"),
        "stats": job.get("stats") or {},
        "error": job.get("error"),
        "logs": job.get("logs") or [],
    }


def _run_admin_facebook_crawl_job(job_id: str) -> None:
    from db.connection import advisory_lock
    from cli.crawlers import _facebook_crawl_to_raw, _clean_broker_images_after_download
    from cleansing.reprocess import run_full_reprocess
    from cleansing.download_images import download_images

    with FACEBOOK_CRAWL_LOCK:
        job = FACEBOOK_CRAWL_JOBS[job_id]
        job["status"] = "running"
        job["started_at"] = _utc_iso_z()
        job["progress_pct"] = 3
        job["progress_label"] = "Đang chuẩn bị crawl"
    try:
        profile = {
            "url": job["profile_url"],
            "tier": job["limit"],
            "broker_name": job.get("broker_name") or None,
            "default_area": job.get("city") or None,
        }
        crawl_mode = "incremental" if job["mode"] == "daily" else "full"
        max_age_days = job["days"] if job["mode"] == "range" else None
        with advisory_lock("admin-facebook-crawl"):
            _set_crawl_progress(job, 8, "crawl", "Đang gọi Apify")
            _append_crawl_log(job, f"Crawl {job['mode']} | limit={job['limit']} | url={job['profile_url']}")

            def _crawl_progress(stage, done, total, stats):
                if stage != "import_raw":
                    return
                pct = 10
                if total:
                    pct = 10 + int((done / total) * 23)
                _set_crawl_progress(
                    job,
                    pct,
                    "import_raw",
                    f"Đang nhập raw {done}/{total} từ Apify",
                )
                if done and (done == total or done % 50 == 0):
                    _append_crawl_log(
                        job,
                        "Nhập raw: "
                        f"{done}/{total} | imported={stats.get('inserted', 0)}, "
                        f"refreshed={stats.get('refreshed_images', 0)}, "
                        f"skipped={stats.get('skipped', 0)}, "
                        f"irrelevant={stats.get('irrelevant', 0)}, "
                        f"out_of_area={stats.get('out_of_area', 0)}",
                    )

            crawl_stats = _facebook_crawl_to_raw(
                mode=crawl_mode,
                limit_override=job["limit"],
                profiles=[profile],
                max_age_days=max_age_days,
                progress_callback=_crawl_progress,
            ) or {}
            job.setdefault("stats", {})["crawl"] = crawl_stats
            _set_crawl_progress(job, 35, "crawl", "Đã lấy dữ liệu từ Facebook")
            _append_crawl_log(
                job,
                "Crawl xong: "
                f"fetched={crawl_stats.get('fetched', 0)}, "
                f"imported={crawl_stats.get('inserted', 0)}, "
                f"refreshed={crawl_stats.get('refreshed_images', 0)}, "
                f"skipped={crawl_stats.get('skipped', 0)}, "
                f"irrelevant={crawl_stats.get('irrelevant', 0)}, "
                f"out_of_area={crawl_stats.get('out_of_area', 0)}, "
                f"range_filtered={crawl_stats.get('range_filtered', 0)}",
            )

            if crawl_stats.get("inserted", 0) > 0 or crawl_stats.get("refreshed_images", 0) > 0:
                _set_crawl_progress(job, 42, "reprocess", "Đang reprocess listing")
                changed_raw_ids = []
                changed_raw_ids.extend(crawl_stats.get("inserted_raw_ids") or [])
                changed_raw_ids.extend(crawl_stats.get("refreshed_raw_ids") or [])
                changed_raw_ids = list(dict.fromkeys(changed_raw_ids))
                reprocess_kwargs = {"source": "facebook", "full": False}
                if changed_raw_ids:
                    reprocess_kwargs["raw_ids"] = changed_raw_ids
                    _append_crawl_log(job, f"Reprocess {len(changed_raw_ids)} raw vua crawl/refresh.")
                reprocess_stats = run_full_reprocess(**reprocess_kwargs)
                job["stats"]["reprocess"] = reprocess_stats
                processed_ids = reprocess_stats.get("listings", {}).get("processed_ids") or []
                listing_reprocess = reprocess_stats.get("listings", {})
                _set_crawl_progress(job, 70, "reprocess", "Đã reprocess xong")
                _append_crawl_log(
                    job,
                    "Reprocess xong: "
                    f"processed={len(processed_ids)}, "
                    f"new={listing_reprocess.get('new', 0)}, "
                    f"updated={listing_reprocess.get('updated', 0)}, "
                    f"skipped={listing_reprocess.get('skipped', 0)}",
                )

                if job.get("download_images"):
                    _set_crawl_progress(job, 75, "download_images", "Đang tải ảnh")

                    def _download_progress(done, total, success):
                        if total:
                            pct = 75 + int((done / total) * 19)
                            _set_crawl_progress(
                                job,
                                pct,
                                "download_images",
                                f"Đang tải ảnh {done}/{total} (ok {success})",
                            )

                    downloaded = download_images(
                        limit=max(200, min(3000, job["limit"] * 12)),
                        listing_ids=processed_ids,
                        progress_callback=_download_progress,
                    )
                    job["stats"]["downloaded_images"] = downloaded
                    _set_crawl_progress(job, 94, "download_images", "Đã tải ảnh xong")
                    _append_crawl_log(job, f"Tải ảnh xong: {downloaded} ảnh")
                    try:
                        _set_crawl_progress(job, 96, "cleanup", "Đang dọn ảnh môi giới")
                        _clean_broker_images_after_download(source="facebook", limit=max(200, job["limit"] * 12))
                    except Exception as exc:
                        _append_crawl_log(job, f"Clean ảnh môi giới lỗi nhẹ: {exc}")
                else:
                    _set_crawl_progress(job, 95, "reprocess", "Bỏ qua tải ảnh")
            else:
                _set_crawl_progress(job, 95, "crawl", "Không có bài mới")
                _append_crawl_log(job, "Không có bài mới hoặc ảnh mới, bỏ qua reprocess.")

        with FACEBOOK_CRAWL_LOCK:
            job["status"] = "succeeded"
            job["stage"] = "done"
            job["progress_pct"] = 100
            job["progress_label"] = "Hoàn tất"
            job["finished_at"] = _utc_iso_z()
    except Exception as exc:
        logger.exception("Admin Facebook crawl job failed")
        _append_crawl_log(job, f"Lỗi: {exc}")
        with FACEBOOK_CRAWL_LOCK:
            job["status"] = "failed"
            job["stage"] = "failed"
            job["progress_label"] = "Lỗi khi crawl"
            job["error"] = str(exc)
            job["finished_at"] = _utc_iso_z()


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
        if exp and exp < _utc_iso():
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
        "SHOW_INSIGHTS": _insights_enabled(),
    }


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


def api_auth_logout():
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token:
        u = current_user()
        delete_session(token)
        if u:
            log_audit(u["id"], u.get("tier"), "logout")
    resp = make_response(jsonify({"ok": True}))
    return _clear_session_cookie(resp)


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


@require_tier("free")
def api_list_watchlists():
    u = current_user()
    with db_mod.get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM user_watchlists WHERE user_id=? ORDER BY id DESC", (u["id"],)
        ).fetchall()
    return jsonify({"ok": True, "items": [_serialize_watchlist(r) for r in rows]})


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


@require_tier("free")
def api_telegram_start():
    u = current_user()
    bot_username = os.getenv("TELEGRAM_BOT_USERNAME", "").strip().lstrip("@")
    if not bot_username:
        return jsonify({"ok": False, "error": "bot_not_configured"}), 500
    token = _secrets.token_urlsafe(16)
    expires = (_utc_now() + timedelta(minutes=10)).replace(tzinfo=None).isoformat(timespec="seconds")
    with db_mod.get_conn() as conn:
        conn.execute(
            "UPDATE users SET telegram_link_token=?, telegram_link_expires_at=? WHERE id=?",
            (token, expires, u["id"]),
        )
    deep_link = f"https://t.me/{bot_username}?start={token}"
    return jsonify({"ok": True, "url": deep_link, "expires_at": expires})


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

    now_iso = _utc_iso()
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

def _public_url(path="/"):
    path = "/" + str(path or "/").lstrip("/")
    return f"{PUBLIC_BASE_URL}{path}"


def _site_meta(path="/", *, title=None, description=None, keywords=None):
    canonical_url = _public_url(path)
    return {
        "name": SITE_NAME,
        "title": title or SITE_TITLE,
        "description": description or SITE_DESCRIPTION,
        "keywords": keywords or SITE_KEYWORDS,
        "canonical_url": canonical_url,
        "og_url": canonical_url,
        "og_image": SITE_OG_IMAGE,
    }


def serve_local_image(filename):
    return send_from_directory(_DATA_IMAGES_DIR, filename)


def index():
    page = dict(SEO_PAGES["binh-duong"])
    page["path"] = "/"
    site_meta = _site_meta(
        "/",
        title=page["title"],
        description=page["description"],
        keywords=page["keywords"],
    )
    return render_template("seo_landing.html", page=page, site_meta=site_meta)


def dashboard():
    return render_template('index.html', wards_by_city=CITY_MAP, site_meta=_site_meta("/dashboard"))


def redirect_legacy_binh_duong():
    return redirect("/", code=301)


def seo_landing_page(slug):
    page = SEO_PAGES.get(slug)
    if not page:
        abort(404)
    site_meta = _site_meta(
        page["path"],
        title=page["title"],
        description=page["description"],
        keywords=page["keywords"],
    )
    return render_template("seo_landing.html", page=page, site_meta=site_meta)


def robots_txt():
    body = f"""User-agent: *
Allow: /

Sitemap: {_public_url('/sitemap.xml')}
"""
    return Response(body, mimetype="text/plain; charset=utf-8")


def sitemap_xml():
    seo_urls = "\n".join(
        f"""  <url>
    <loc>{_public_url(page["path"])}</loc>
    <changefreq>daily</changefreq>
    <priority>0.8</priority>
  </url>"""
        for slug, page in SEO_PAGES.items()
        if slug != "binh-duong"
    )
    body = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>{_public_url('/')}</loc>
    <changefreq>hourly</changefreq>
    <priority>1.0</priority>
  </url>
{seo_urls}
</urlset>
"""
    return Response(body, mimetype="application/xml; charset=utf-8")


_DASHBOARD_CACHE = {}
_DASHBOARD_CACHE_MAX_ITEMS = 96
_DASHBOARD_CACHE_TTL_SECONDS = float(os.getenv("RADAR_DASHBOARD_CACHE_TTL_SECONDS", "120"))
_SIGNAL_CACHE = {}
_SIGNAL_CACHE_MAX_ITEMS = 256
_SIGNAL_CACHE_TTL_SECONDS = float(os.getenv("RADAR_SIGNAL_CACHE_TTL_SECONDS", "60"))


def clear_dashboard_cache():
    _DASHBOARD_CACHE.clear()


def clear_signal_cache():
    _SIGNAL_CACHE.clear()


def _cached_dashboard_payload(key, loader, now=None, ttl_seconds=None, force_refresh=False):
    ttl = _DASHBOARD_CACHE_TTL_SECONDS if ttl_seconds is None else ttl_seconds
    if ttl <= 0:
        return loader()

    now = time.monotonic() if now is None else now
    entry = _DASHBOARD_CACHE.get(key)
    if not force_refresh and entry and now - entry["ts"] <= ttl:
        return deepcopy(entry["payload"])

    payload = loader()
    _DASHBOARD_CACHE[key] = {"ts": now, "payload": deepcopy(payload)}
    if len(_DASHBOARD_CACHE) > _DASHBOARD_CACHE_MAX_ITEMS:
        oldest_key = min(_DASHBOARD_CACHE, key=lambda k: _DASHBOARD_CACHE[k]["ts"])
        _DASHBOARD_CACHE.pop(oldest_key, None)
    return payload


def _cached_signal_payload(key, loader, now=None, ttl_seconds=None):
    ttl = _SIGNAL_CACHE_TTL_SECONDS if ttl_seconds is None else ttl_seconds
    if ttl <= 0:
        return loader()

    now = time.monotonic() if now is None else now
    entry = _SIGNAL_CACHE.get(key)
    if entry and now - entry["ts"] <= ttl:
        return deepcopy(entry["payload"])

    payload = loader()
    _SIGNAL_CACHE[key] = {"ts": now, "payload": deepcopy(payload)}
    if len(_SIGNAL_CACHE) > _SIGNAL_CACHE_MAX_ITEMS:
        oldest_key = min(_SIGNAL_CACHE, key=lambda k: _SIGNAL_CACHE[k]["ts"])
        _SIGNAL_CACHE.pop(oldest_key, None)
    return payload


def _dashboard_cache_refresh_requested(req) -> bool:
    if req.args.get("cache_refresh") != "1":
        return False
    remote_addr = (req.remote_addr or "").strip()
    if remote_addr in {"127.0.0.1", "::1", "localhost"}:
        return True
    try:
        return current_tier() == "admin"
    except Exception:
        return False


def _get_signals_version(db_path: str) -> str:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT COALESCE(
                MAX(v),
                '1970-01-01T00:00:00'
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


def _db_handle():
    """Placeholder argument for older service signatures; runtime uses DATABASE_URL."""
    return None


def _request_range_filters(req):
    def _parse(name):
        try:
            value = req.args.get(name, 0)
            return float(value) if value not in (None, "") else 0
        except (TypeError, ValueError):
            return 0

    return _parse("area_min"), _parse("area_max"), _parse("price_min"), _parse("price_max")


def _request_range_list(req, name):
    ranges = []
    for token in req.args.getlist(name):
        text = str(token or "").strip()
        if not text:
            continue
        if ":" in text:
            raw_min, raw_max = text.split(":", 1)
        elif "-" in text:
            raw_min, raw_max = text.split("-", 1)
        else:
            raw_min, raw_max = text, ""
        try:
            low = float(raw_min) if raw_min.strip() else 0
            high = float(raw_max) if raw_max.strip() else 0
        except (TypeError, ValueError):
            continue
        if low <= 0 and high <= 0:
            continue
        if low > 0 and high > 0 and low > high:
            low, high = high, low
        ranges.append((low, high))
    return ranges


def _request_range_filter_kwargs(req):
    area_min, area_max, price_min, price_max = _request_range_filters(req)
    return {
        "area_min": area_min,
        "area_max": area_max,
        "price_min": price_min,
        "price_max": price_max,
        "area_ranges": _request_range_list(req, "area_range"),
        "price_ranges": _request_range_list(req, "price_range"),
    }


def _request_keyword(req) -> str:
    return normalize_search_keyword(req.args.get("q") or req.args.get("keyword") or "")


def _request_date_range(req) -> str:
    return normalize_date_range(req.args.get("date_range") or req.args.get("time_range"), default="3m") or "3m"


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
    now = datetime.now()
    if dt.date() == now.date():
        return "hôm nay"
    if dt > now:
        days_until = max(1, (dt.date() - now.date()).days)
        return f"{days_until} ngày tới"
    days = (now.date() - dt.date()).days
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

@rate_limit("dashboard", limits={"guest": 1200, "free": 2400, "vip": None, "admin": None})
def api_dashboard():
    active_city, wards, sources, prop_types, only_drops, trend_period, mos_min = get_base_filters(request)
    range_kwargs = _request_range_filter_kwargs(request)
    keyword = _request_keyword(request)
    date_range = _request_date_range(request)
    area_min = range_kwargs["area_min"]
    area_max = range_kwargs["area_max"]
    price_min = range_kwargs["price_min"]
    price_max = range_kwargs["price_max"]
    if not wards and active_city in CITY_MAP:
        wards = CITY_MAP[active_city]
    db_path = _db_handle()
    include_trend = request.args.get("include_trend") == "1"
    # Load data without fetching all listings to save time/memory
    tier = current_tier()
    cache_key = (
        tier,
        active_city,
        tuple(wards or ()),
        tuple(sources or ()),
        tuple(prop_types or ()),
        bool(only_drops),
        trend_period,
        int(mos_min or 0),
        float(area_min or 0),
        float(area_max or 0),
        float(price_min or 0),
        float(price_max or 0),
        tuple(range_kwargs["area_ranges"]),
        tuple(range_kwargs["price_ranges"]),
        keyword,
        date_range,
        bool(include_trend),
    )

    def _load_dashboard_payload():
        data = load_dashboard_summary(
            db_path,
            sources=sources,
            wards=wards,
            prop_types=prop_types,
            only_drops=only_drops,
            trend_period=trend_period,
            include_trend=include_trend,
            mos_min=mos_min,
            tier=tier,
            keyword=keyword,
            date_range=date_range,
            **range_kwargs,
        )
        return {
            "stats": data["stats"],
            "market": data["market"],
            "trend_data": data["trend_data"],
            "signals_version": _get_signals_version(db_path),
            "all_wards": data["all_wards"],
            "all_sources": data["all_sources"] if tier == "admin" else sources,
            "wards_by_city": data["wards_by_city"],
            "active_city": active_city,
            "active_wards": wards,
            "active_sources": sources,
            "active_props": prop_types,
            "trend_period": trend_period,
            "tier": tier,
        }

    return jsonify(_cached_dashboard_payload(
        cache_key,
        _load_dashboard_payload,
        force_refresh=_dashboard_cache_refresh_requested(request),
    ))

@rate_limit("dashboard", limits={"guest": 1200, "free": 2400, "vip": None, "admin": None})
def api_counts():
    active_city, wards, sources, prop_types, only_drops, trend_period, mos_min = get_base_filters(request)
    range_kwargs = _request_range_filter_kwargs(request)
    keyword = _request_keyword(request)
    date_range = _request_date_range(request)
    if not wards and active_city in CITY_MAP:
        wards = CITY_MAP[active_city]
    return jsonify({
        "stats": load_counts(
            _db_handle(),
            sources=sources,
            wards=wards,
            prop_types=prop_types,
            only_drops=only_drops,
            mos_min=mos_min,
            keyword=keyword,
            date_range=date_range,
            **range_kwargs,
        ),
        "active_city": active_city,
        "active_wards": wards,
        "active_sources": sources,
        "active_props": prop_types,
        "trend_period": trend_period,
        "tier": current_tier(),
    })

def api_signals():
    active_city, wards, sources, prop_types, only_drops, trend_period, mos_min = get_base_filters(request)
    range_kwargs = _request_range_filter_kwargs(request)
    keyword = _request_keyword(request)
    date_range = _request_date_range(request)
    if not wards and active_city in CITY_MAP:
        wards = CITY_MAP[active_city]
    try:
        page = int(request.args.get("page", 1))
        limit = int(request.args.get("limit", 30))
    except ValueError:
        page, limit = 1, 30
    sort = request.args.get("sort", "newest")
    include_total = request.args.get("include_total") != "0"
    db_path = _db_handle()
    tier = current_tier()
    cache_key = (
        tier,
        active_city,
        tuple(wards or ()),
        tuple(sources or ()),
        tuple(prop_types or ()),
        bool(only_drops),
        int(mos_min or 0),
        float(range_kwargs["area_min"] or 0),
        float(range_kwargs["area_max"] or 0),
        float(range_kwargs["price_min"] or 0),
        float(range_kwargs["price_max"] or 0),
        tuple(range_kwargs["area_ranges"]),
        tuple(range_kwargs["price_ranges"]),
        keyword,
        date_range,
        sort,
        page,
        limit,
        bool(include_total),
    )

    def _load_signal_payload():
        return load_signals(
            db_path,
            sources=sources,
            wards=wards,
            prop_types=prop_types,
            only_drops=only_drops,
            mos_min=mos_min,
            sort=sort,
            page=page,
            limit=limit,
            tier=tier,
            keyword=keyword,
            include_total=include_total,
            date_range=date_range,
            **range_kwargs,
        )

    if tier == "admin":
        return jsonify(_load_signal_payload())
    return jsonify(_cached_signal_payload(cache_key, _load_signal_payload))

def api_trends():
    active_city, wards, sources, prop_types, only_drops, trend_period, mos_min = get_base_filters(request)
    range_kwargs = _request_range_filter_kwargs(request)
    if not wards and active_city in CITY_MAP:
        wards = CITY_MAP[active_city]
    db_path = _db_handle()
    return jsonify({
        "trend_data": load_trend_data(db_path, sources, wards, prop_types, only_drops, trend_period, **range_kwargs),
        "trend_period": trend_period
    })


def api_insights():
    if not _insights_enabled():
        return jsonify({
            "enabled": False,
            "timeline": [],
            "policy_alerts": [],
            "counts": {
                "projects": 0,
                "alerts": 0,
            },
        })

    db_path = _db_handle()
    conn = connect(db_path)
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

def api_heatmap():
    active_city, wards, sources, prop_types, only_drops, trend_period, mos_min = get_base_filters(request)
    range_kwargs = _request_range_filter_kwargs(request)
    db_path = _db_handle()
    conn = connect(db_path)
    
    where_parts = [
        "l.probably_sold = 0",
        "COALESCE(l.is_blacklisted,0)=0",
        "COALESCE(l.review_hidden,0)=0",
        "l.price_per_m2 > 0",
        "l.price_per_m2 < 1000"
    ]
    if only_drops:
        where_parts.append(group_price_drop_filter_sql("l."))
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
    range_clauses, range_params = _range_filters(prefix="l.", **range_kwargs)
    where_parts.extend(range_clauses)
    params.extend(range_params)
    where_sql = " AND ".join(where_parts)
    
    # Market fields use all valid listings; opportunity fields use signal deals only.
    signal_condition = actionable_signal_sql("v")
    query = f"""
        WITH {LATEST_VALUATION_CTE}
        SELECT l.ward,
               l.price_per_m2,
               l.price_ty,
               l.area_m2,
               v.fair_ppm2,
               v.mos_pct,
               CASE WHEN {signal_condition} THEN 1 ELSE 0 END as is_signal,
               COALESCE(v.is_outlier, 0) as is_outlier
        FROM listings l
        LEFT JOIN latest_valuation v ON l.id = v.listing_id
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


@require_tier('vip')
def api_market_indicators():
    active_city, wards, sources, prop_types, only_drops, trend_period, mos_min = get_base_filters(request)
    range_kwargs = _request_range_filter_kwargs(request)
    if not wards and active_city in CITY_MAP:
        wards = CITY_MAP[active_city]
    db_path = _db_handle()
    return jsonify(load_market_indicators(
        db_path,
        sources=sources,
        wards=wards,
        prop_types=prop_types,
        **range_kwargs,
    ))

@rate_limit("listings")
def api_listings():
    active_city, wards, sources, prop_types, only_drops, trend_period, mos_min = get_base_filters(request)
    range_kwargs = _request_range_filter_kwargs(request)
    keyword = _request_keyword(request)
    date_range = _request_date_range(request)
    if not wards and active_city in CITY_MAP:
        wards = CITY_MAP[active_city]
    try:
        page = int(request.args.get("page", 1))
        limit = int(request.args.get("limit", 50))
    except ValueError:
        page, limit = 1, 50
    offset = (page - 1) * limit
    
    db_path = _db_handle()
    conn = connect(db_path)
    
    where_parts = ["l.probably_sold = 0", "COALESCE(l.is_blacklisted,0)=0", "COALESCE(l.review_hidden,0)=0"]
    if only_drops:
        where_parts.append(group_price_drop_filter_sql("l."))
    else:
        where_parts.append("l.possibly_duplicate = 0")
    params = []
    
    if wards:
        where_parts.append(f"l.ward IN ({','.join(['?']*len(wards))})")
        params.extend(wards)
    if sources:
        where_parts.append(f"l.source IN ({','.join(['?']*len(sources))})")
        params.extend(sources)
    if prop_types:
        where_parts.append(f"l.property_type IN ({','.join(['?']*len(prop_types))})")
        params.extend(prop_types)
    range_clauses, range_params = _range_filters(prefix="l.", **range_kwargs)
    where_parts.extend(range_clauses)
    params.extend(range_params)
    search_clauses, search_params = keyword_search_filter(keyword, prefix="l.")
    where_parts.extend(search_clauses)
    params.extend(search_params)
    date_clauses, date_params = listing_date_range_filter(date_range, prefix="l.")
    where_parts.extend(date_clauses)
    params.extend(date_params)
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
    signal_condition = actionable_signal_sql("v")
    query = f"""
        WITH {LATEST_VALUATION_CTE}
        SELECT l.*, v.is_signal, v.mos_pct, v.fair_ppm2, v.signal_score,
               CASE WHEN {signal_condition} THEN 1 ELSE 0 END AS actionable_signal,
               {fresh_flag}
        FROM listings l
        LEFT JOIN latest_valuation v ON l.id = v.listing_id
        WHERE {where_sql}
        ORDER BY {order_expr} {sort_dir} NULLS LAST
        LIMIT ? OFFSET ?
    """
    query_params = list(params)
    query_params.extend([limit, offset])
    rows = conn.execute(query, query_params).fetchall()
    
    count_query = f"SELECT COUNT(*) FROM listings l WHERE {where_sql}"
    total = conn.execute(count_query, params).fetchone()[0]
    
    listing_ids = [r['id'] for r in rows]
    from collections import defaultdict
    img_map = defaultdict(list)
    related_drop_map = {}
    if listing_ids:
        placeholders = ",".join("?" * len(listing_ids))
        img_rows = conn.execute(f"""
            SELECT listing_id, local_path, img_url
            FROM listing_images
            WHERE listing_id IN ({placeholders})
            ORDER BY listing_id, {_image_order_sql()}
        """, listing_ids).fetchall()
        for r in img_rows:
            url = resolve_image_url(r[1], r[2])
            if url:
                img_map[r[0]].append(url)
        drop_rows = conn.execute(f"""
            SELECT drop_child.duplicate_of_id AS listing_id,
                   MAX(drop_child.price_ty) AS first_price
            FROM listings drop_child
            JOIN listings parent ON parent.id = drop_child.duplicate_of_id
            WHERE drop_child.duplicate_of_id IN ({placeholders})
              AND COALESCE(drop_child.probably_sold,0)=0
              AND COALESCE(drop_child.is_blacklisted,0)=0
              AND COALESCE(drop_child.review_hidden,0)=0
              AND drop_child.price_ty IS NOT NULL
              AND parent.price_ty IS NOT NULL
              AND drop_child.price_ty > parent.price_ty * 1.01
              AND parent.price_ty >= drop_child.price_ty * 0.60
            GROUP BY drop_child.duplicate_of_id
        """, listing_ids).fetchall()
        related_drop_map = {r["listing_id"]: r["first_price"] for r in drop_rows}
        
    conn.close()

    listings = []
    for r in rows:
        badge_meta = signal_badge_metadata(r)
        related_first = related_drop_map.get(r["id"])
        price_ty = r["price_ty"]
        price_first_ty = r["price_first_ty"]
        price_dropped = _valid_price_drop_values(price_ty, price_first_ty)
        drop_pct = r["price_drop_pct"] if price_dropped else None
        if related_first is not None and price_ty:
            price_dropped = True
            drop_pct = round(((related_first - price_ty) / related_first * 100), 2)
            price_first_ty = related_first
        listings.append(redact_for_tier({
            "id": r['id'], "title": r['title'], "description": r['description'] or "",
            "price_ty": price_ty, "area_m2": r['area_m2'],
            "frontage_m": r['frontage_m'], "depth_m": r['depth_m'],
            "price_per_m2": round(r['price_per_m2'], 1) if r['price_per_m2'] else None, "prop_type": r['property_type'],
            "prop_type_label": badge_meta["property_type_label"],
            "road_tier": r['road_tier'], "road_type": r['road_type'],
            "road_width_m": badge_meta["road_width_m"],
            "road_label": badge_meta["road_label"],
            "street_label": badge_meta["street_label"],
            "tho_cu_m2": badge_meta["tho_cu_m2"],
            "tho_cu_ratio": badge_meta["tho_cu_ratio"],
            "tho_cu_label": badge_meta["tho_cu_label"],
            "ward": r['ward'], "url": r['url'], "is_signal": bool(r['actionable_signal']), "mos_pct": round(r['mos_pct'], 1) if r['mos_pct'] else 0,
            "fair_ppm2": round(r['fair_ppm2'], 1) if r['fair_ppm2'] else None,
            "days_ago": _days_ago(r['posted_at'] or r['crawled_at']), "is_hot": bool(r['is_hot']), "price_dropped": price_dropped,
            "suspicious_bait": bool(r['suspicious_bait']),
            "drop_pct": drop_pct, "price_first_ty": price_first_ty, "duplicate_of_id": r['duplicate_of_id'],
            "source": r['source'], "imgs": img_map.get(r['id'], []),
            "is_fresh_locked": bool(r['is_fresh_locked']),
        }, tier))
    return jsonify({
        "listings": listings,
        "total": total,
        "page": page,
        "limit": limit,
        "pages": (total + limit - 1) // limit if limit > 0 else 1,
        "has_more": page * limit < total,
        "tier": tier,
    })

def listing_detail(listing_id):
    db_path = _db_handle()
    tier = current_tier()
    data = load_listing_detail(db_path, listing_id, tier=tier)
    if not data:
        return "Listing not found", 404
    
    l = data["listing"]
    imgs = data["images"]
    history_json = json.dumps(data["history"], ensure_ascii=False)
    desc_html = l.get('description', '').replace('\n', '<br>') if l.get('description') else 'Không có mô tả.'
    
    # Advisory note is temporarily hidden from listing detail pages.
    memo = None

    return render_template('listing_detail.html', l=l, imgs=imgs, history_json=history_json, desc_html=desc_html, memo=memo)

def api_listing_detail(listing_id):
    db_path = _db_handle()
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
        "frontage_m": l.get("frontage_m"),
        "depth_m": l.get("depth_m"),
        "actual_ppm2": round(l["price_per_m2"], 1) if l["price_per_m2"] else None,
        "fair_ppm2": round(l["fair_ppm2"], 1) if l["fair_ppm2"] else None,
        "mos_pct": round(l["mos_pct"], 1) if l["mos_pct"] else 0,
        "ward": l["ward"],
        "property_type": l["property_type"],
        "property_type_label": l.get("property_type_label"),
        "road_type": l["road_type"],
        "road_width_m": l.get("road_width_m"),
        "road_label": l.get("road_label"),
        "street_label": l.get("street_label"),
        "tho_cu_m2": l.get("tho_cu_m2"),
        "tho_cu_ratio": l.get("tho_cu_ratio"),
        "tho_cu_label": l.get("tho_cu_label"),
        "source": l["source"],
        "url": l["url"],
        "road_tier": l["road_tier"] or 0,
        "has_so": None if l["has_so"] is None else bool(l["has_so"]),
        "price_dropped": bool(l["price_dropped"]),
        "drop_pct": l["price_drop_pct"],
        "price_first_ty": l["price_first_ty"],
        "duplicate_of_id": l["duplicate_of_id"],
        "signal_score": l["signal_score"] or 0,
        "trust_tier": l.get("trust_tier") or "candidate_signal",
        "trust_score": l.get("trust_score") or 0,
        "legal_status": l.get("legal_status") or "unverified",
        "legal_flags": l.get("legal_flags") or "",
        "legal_verification": data.get("legal_verification") or {},
        "days_ago": _days_ago(l["posted_at"] or l["crawled_at"]),
        "imgs": data["images"],
        "tier": data.get("tier"),
    })

def api_listing_memo(listing_id):
    tier = current_tier()
    if tier == "guest":
        return jsonify({"locked": True, "reason": "login_required"}), 403
    if tier not in ("vip", "admin"):
        return jsonify({"locked": True, "reason": "vip_required"}), 403

    with db_mod.get_conn() as conn:
        listing = conn.execute(
            """
            SELECT id
              FROM listings
             WHERE id = ?
               AND COALESCE(is_blacklisted,0) = 0
               AND COALESCE(review_hidden,0) = 0
            """,
            (listing_id,),
        ).fetchone()
        if not listing:
            return jsonify({"error": "not found"}), 404

        memo = conn.execute(
            """
            SELECT id, created_at, updated_at, actor, verdict, confidence,
                   reasoning, red_flags, needs_map_check, model, memo_markdown
              FROM ai_deal_review
             WHERE listing_id = ?
               AND NULLIF(TRIM(COALESCE(memo_markdown,'')), '') IS NOT NULL
               AND COALESCE(model,'') NOT LIKE 'claude-code-advisory-%'
               AND memo_markdown NOT LIKE '# Investment Memo%'
               AND memo_markdown NOT LIKE '%## Verdict%'
             ORDER BY created_at DESC, id DESC
             LIMIT 1
            """,
            (listing_id,),
        ).fetchone()

    if not memo:
        return jsonify({
            "listing_id": listing_id,
            "pending": True,
            "tier": tier,
            "message": "Chưa có ghi chú cố vấn cho thương vụ này.",
        })

    try:
        red_flags = json.loads(memo["red_flags"]) if memo["red_flags"] else []
    except Exception:
        red_flags = []

    return jsonify({
        "listing_id": listing_id,
        "pending": False,
        "tier": tier,
        "review_id": memo["id"],
        "created_at": memo["created_at"],
        "updated_at": memo["updated_at"],
        "actor": memo["actor"],
        "verdict": memo["verdict"],
        "confidence": memo["confidence"],
        "reasoning": memo["reasoning"],
        "red_flags": red_flags,
        "needs_map_check": bool(memo["needs_map_check"]),
        "model": memo["model"],
        "memo_markdown": memo["memo_markdown"],
        **(
            {"admin_valuation_workflow_markdown": _admin_valuation_workflow_markdown(listing_id)}
            if tier == "admin"
            else {}
        ),
    })


def _fmt_memo_num(value, suffix="", digits=1):
    if value is None:
        return "NULL"
    try:
        n = float(value)
    except (TypeError, ValueError):
        return str(value)
    if abs(n - round(n)) < 0.05:
        text = str(int(round(n)))
    else:
        text = f"{n:.{digits}f}".rstrip("0").rstrip(".")
    return f"{text}{suffix}"


def _admin_valuation_workflow_markdown(listing_id):
    with db_mod.get_conn() as conn:
        row = conn.execute(
            """
            SELECT l.id, l.source, l.title, l.ward, l.property_type, l.price_ty,
                   l.area_m2, l.price_per_m2, l.road_tier, l.has_so, l.is_hot,
                   l.price_dropped, l.price_drop_pct, l.tho_cu_m2,
                   l.tho_cu_ratio, l.frontage_m, l.depth_m, l.road_type,
                   l.price_first_ty, l.suspicious_bait, l.description,
                   v.fair_ppm2, v.actual_ppm2, v.mos_pct, v.is_signal,
                   v.signal_score, v.segment, v.n_segment, v.source_quality_flags,
                   v.source_quality_recheck, v.trust_tier, v.trust_score,
                   v.legal_status, v.legal_flags
              FROM listings l
              LEFT JOIN valuation_results v
                ON v.id = (SELECT id FROM valuation_results
                            WHERE listing_id = l.id
                            ORDER BY computed_at DESC, id DESC
                            LIMIT 1)
             WHERE l.id = ?
            """,
            (listing_id,),
        ).fetchone()
    if not row:
        return ""
    return build_admin_valuation_workflow_markdown(row)

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
            SELECT updated_at, price_ty, ward, area_m2, property_type, road_tier,
                   price_per_m2, title, url
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
            item = {'date': (r[0] or '')[:10], 'price_ty': price_ty}
            if tier == "admin" and curr and curr["url"]:
                item["url"] = curr["url"]
            history.append(item)
            last_price = price_ty
            has_last = True

        if curr and curr["price_ty"]:
            current_price = curr["price_ty"]
            if not history or not _same_price_value(history[-1]['price_ty'], current_price):
                item = {
                    'date': (curr["updated_at"] or '')[:10],
                    'price_ty': current_price,
                    'is_current': True,
                }
                if tier == "admin" and curr["url"]:
                    item["url"] = curr["url"]
                history.append(item)

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
            comp_where = [
                "ward = ?",
                "id != ?",
                "price_ty > 0",
                "probably_sold = 0",
                "COALESCE(is_blacklisted,0)=0",
                "COALESCE(review_hidden,0)=0",
                "possibly_duplicate = 0",
            ]
            comp_params = [ward, listing_id]
            if prop_type:
                comp_where.append("property_type = ?")
                comp_params.append(prop_type)
            comp_where.append("area_m2 BETWEEN ? AND ?")
            comp_params.extend([area_min, area_max])
            if curr_ppm2 > 0:
                comp_where.append("COALESCE(price_per_m2, 0) BETWEEN ? AND ?")
                comp_params.extend([ppm2_min, ppm2_max])
            if road_tier is not None:
                comp_where.append("(road_tier IS NULL OR ABS(road_tier - ?) <= 1)")
                comp_params.append(road_tier)
            comp_params.extend([area, curr_ppm2])

            comp_rows = conn.execute(f"""
                SELECT id, title, description, url, ward, price_ty, area_m2, frontage_m, depth_m,
                       price_per_m2, property_type, road_tier, road_type, road_width_m,
                       tho_cu_m2, tho_cu_ratio,
                       COALESCE(posted_at, crawled_at) as dt
                FROM listings
                WHERE {" AND ".join(comp_where)}
                ORDER BY ABS(area_m2 - ?) ASC,
                         ABS(COALESCE(price_per_m2, 0) - ?) ASC,
                         COALESCE(posted_at, crawled_at) DESC
                LIMIT 20
            """, comp_params).fetchall()
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

                badge_meta = signal_badge_metadata(c)
                ranked.append({
                    'id': c["id"],
                    'title': (c["title"] or '')[:80],
                    'url': (c["url"] or "") if tier == "admin" else "",
                    'detail_url': f"/listing/{c['id']}",
                    'price_ty': c["price_ty"],
                    'area_m2': c["area_m2"],
                    'frontage_m': c["frontage_m"],
                    'depth_m': c["depth_m"],
                    'price_per_m2': c["price_per_m2"],
                    'ward': c["ward"],
                    'property_type': c["property_type"],
                    'property_type_label': badge_meta["property_type_label"],
                    'road_tier': c["road_tier"],
                    'road_type': c["road_type"],
                    'road_width_m': badge_meta["road_width_m"],
                    'road_label': badge_meta["road_label"],
                    'street_label': badge_meta["street_label"],
                    'tho_cu_m2': badge_meta["tho_cu_m2"],
                    'tho_cu_ratio': badge_meta["tho_cu_ratio"],
                    'tho_cu_label': badge_meta["tho_cu_label"],
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
    try:
        has_road_name = bool(conn.execute(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema='public'
              AND table_name='listings'
              AND column_name='road_name'
            """
        ).fetchone())
    except Exception:
        has_road_name = False
    road_name_select = "road_name" if has_road_name else "NULL AS road_name"

    row = conn.execute(f"""
        SELECT id, source, source_id, url, title, description, ward, property_type,
               area_m2, price_ty, price_per_m2, frontage_m, depth_m, {road_name_select}, contact_phone,
               has_so, price_first_ty, price_dropped, price_drop_pct, duplicate_of_id,
               posted_at, crawled_at, updated_at
        FROM listings
        WHERE id = ?
    """, (listing_id,)).fetchone()
    if not row:
        return []

    from cleansing.dedup import (
        _combined_text,
        _has_reliable_lot_signature,
        _road_token_conflict,
    )

    anchor = dict(row)
    canonical_id = row["duplicate_of_id"] or row["id"]
    rows = conn.execute(f"""
        SELECT id, source, source_id, url, title, description, ward, property_type,
               area_m2, price_ty, price_per_m2, frontage_m, depth_m, {road_name_select}, contact_phone,
               has_so, price_first_ty, price_dropped, price_drop_pct,
               possibly_duplicate, duplicate_of_id,
               posted_at, crawled_at, updated_at,
               COALESCE(posted_at, crawled_at, updated_at) AS dt
        FROM listings
        WHERE id = ? OR duplicate_of_id = ?
        ORDER BY COALESCE(posted_at, crawled_at, updated_at) ASC, id ASC
    """, (canonical_id, canonical_id)).fetchall()

    lot_history = []
    first_price = None
    for r in rows:
        candidate = dict(r)
        source = (r["source"] or "").lower()
        is_anchor = r["id"] == listing_id or r["id"] == canonical_id
        is_price_drop = bool(r["price_dropped"])
        anchor_text = _combined_text(anchor)
        candidate_text = _combined_text(candidate)
        road_conflict = _road_token_conflict(anchor_text, candidate_text)
        same_lot = _has_reliable_lot_signature(
            anchor,
            candidate,
            allow_facebook_same_price=True,
        )
        compatible_price_drop = False
        if is_price_drop and not road_conflict:
            anchor_ward = (anchor.get("ward") or "").strip()
            candidate_ward = (candidate.get("ward") or "").strip()
            anchor_type = anchor.get("property_type")
            candidate_type = candidate.get("property_type")
            anchor_area = anchor.get("area_m2") or 0
            candidate_area = candidate.get("area_m2") or 0
            same_segment = (
                (not anchor_ward or not candidate_ward or anchor_ward == candidate_ward)
                and (not anchor_type or not candidate_type or anchor_type == candidate_type)
            )
            area_compatible = (
                not anchor_area
                or not candidate_area
                or (
                    abs(float(anchor_area) - float(candidate_area))
                    / max(float(anchor_area), float(candidate_area))
                    <= 0.05
                )
            )
            compatible_price_drop = same_segment and area_compatible
        linked_price_drop = _linked_lot_history_price_drop(anchor, candidate, canonical_id, road_conflict)

        if r["id"] != listing_id and not (same_lot or compatible_price_drop or linked_price_drop):
            continue

        include_same_price_repost = source == "facebook"
        if not (is_anchor or is_price_drop or include_same_price_repost or linked_price_drop):
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


def _linked_lot_history_price_drop(anchor, candidate, canonical_id, road_conflict):
    if road_conflict:
        return False
    if candidate.get("id") == anchor.get("id"):
        return False
    if candidate.get("duplicate_of_id") != canonical_id and candidate.get("id") != canonical_id:
        return False
    if not anchor.get("price_dropped"):
        return False

    anchor_price = _to_float(anchor.get("price_ty"))
    candidate_price = _to_float(candidate.get("price_ty"))
    first_price = _to_float(anchor.get("price_first_ty"))
    if not anchor_price or not candidate_price or candidate_price <= anchor_price * 1.01:
        return False
    if first_price and not _same_price_value(first_price, candidate_price):
        return False

    anchor_ward = (anchor.get("ward") or "").strip()
    candidate_ward = (candidate.get("ward") or "").strip()
    if anchor_ward and candidate_ward and anchor_ward != candidate_ward:
        return False
    if not _lot_history_property_type_compatible(anchor.get("property_type"), candidate.get("property_type")):
        return False
    return _lot_history_area_compatible(anchor.get("area_m2"), candidate.get("area_m2"))


def _lot_history_property_type_compatible(anchor_type, candidate_type):
    if not anchor_type or not candidate_type or anchor_type == candidate_type:
        return True
    pair = {anchor_type, candidate_type}
    return (
        pair.issubset({"dat_nen", "dat_vuon"})
        or pair.issubset({"nha_dat", "nha_tro"})
    )


def _lot_history_area_compatible(anchor_area, candidate_area, max_gap=0.05):
    anchor_area = _to_float(anchor_area)
    candidate_area = _to_float(candidate_area)
    if not anchor_area or not candidate_area:
        return True
    return abs(anchor_area - candidate_area) / max(anchor_area, candidate_area) <= max_gap


def _to_float(value):
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _valid_price_drop_values(price_ty, price_first_ty):
    price = _to_float(price_ty)
    first_price = _to_float(price_first_ty)
    return bool(
        price
        and first_price
        and price < first_price * 0.99
        and price >= first_price * 0.60
    )


def _same_price_value(a, b):
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return abs(float(a) - float(b)) < 0.000001


@rate_limit("lead_capture", limits={"guest": 10, "free": 30, "vip": 120, "admin": None})
def api_create_lead():
    payload, status = admin_leads.create_lead(
        request.get_json(silent=True) or {},
        tier=current_tier(),
        user=current_user(),
        audit_log_fn=log_audit,
    )
    return jsonify(payload), status


@rate_limit("lead_capture", limits={"guest": 10, "free": 30, "vip": 120, "admin": None})
def api_create_guest_lead():
    payload, status = admin_leads.create_guest_lead(
        request.get_json(silent=True) or {},
        tier=current_tier(),
        user=current_user(),
        audit_log_fn=log_audit,
    )
    return jsonify(payload), status


def admin_control_room(panel_slug=None):
    is_admin = _admin_request_authorized()
    initial_panel = "crm"
    if panel_slug:
        initial_panel = ADMIN_CONTROL_ROOM_SLUG_TO_PANEL.get(panel_slug)
        if not initial_panel:
            abort(404)
    return render_template(
        "admin_control_room.html",
        admin_login_required=not is_admin,
        admin_initial_panel=initial_panel,
        admin_initial_panel_slug=ADMIN_CONTROL_ROOM_PANEL_SLUGS[initial_panel],
        admin_panel_slugs=ADMIN_CONTROL_ROOM_PANEL_SLUGS,
    )


@require_admin_auth
def admin_api_facebook_crawl_config():
    if request.method == "GET":
        profiles = _read_facebook_profile_config()
        stats = _facebook_profile_stats([p["url"] for p in profiles])
        for profile in profiles:
            profile.update(stats.get(profile["url"], {}))
        return jsonify({
            "profiles": profiles,
            "summary": _facebook_crawl_summary(),
            "apify_tokens": _apify_tokens_public(),
        })

    payload = request.get_json(silent=True) or {}
    profiles = payload.get("profiles") or []
    saved = _write_facebook_profile_config(profiles)
    stats = _facebook_profile_stats([p["url"] for p in saved])
    for profile in saved:
        profile.update(stats.get(profile["url"], {}))
    return jsonify({
        "ok": True,
        "profiles": saved,
        "summary": _facebook_crawl_summary(),
        "apify_tokens": _apify_tokens_public(),
    })


@require_admin_auth
def admin_api_facebook_crawl_tokens(token_id=None):
    from crawler.apify_token_pool import delete_token, reset_token_usage, upsert_token

    if request.method == "GET":
        return jsonify({"tokens": _apify_tokens_public()})
    if request.method == "POST":
        payload = request.get_json(silent=True) or {}
        try:
            tokens = upsert_token(payload)
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        return jsonify({"ok": True, "tokens": tokens})
    if request.method == "DELETE":
        if not token_id:
            return jsonify({"ok": False, "error": "token_id_required"}), 400
        return jsonify({"ok": delete_token(token_id), "tokens": _apify_tokens_public()})
    if request.method == "PATCH":
        if not token_id:
            return jsonify({"ok": False, "error": "token_id_required"}), 400
        action = (request.get_json(silent=True) or {}).get("action")
        if action == "reset_usage":
            return jsonify({"ok": reset_token_usage(token_id), "tokens": _apify_tokens_public()})
        return jsonify({"ok": False, "error": "invalid_action"}), 400
    return jsonify({"ok": False, "error": "method_not_allowed"}), 405


@require_admin_auth
def admin_api_facebook_crawl_run():
    payload = request.get_json(silent=True) or {}
    url = (payload.get("url") or payload.get("profile_url") or "").strip()
    if not url.startswith("https://www.facebook.com/"):
        return jsonify({"ok": False, "error": "invalid_profile_url"}), 400
    mode = (payload.get("mode") or "daily").strip().lower()
    if mode not in {"first", "daily", "range"}:
        return jsonify({"ok": False, "error": "invalid_mode"}), 400

    with FACEBOOK_CRAWL_LOCK:
        active = next(
            (FACEBOOK_CRAWL_JOBS[jid] for jid in FACEBOOK_CRAWL_JOB_ORDER
             if FACEBOOK_CRAWL_JOBS[jid].get("status") in {"queued", "running"}),
            None,
        )
        if active:
            return jsonify({"ok": False, "error": "crawl_already_running", "job": _public_crawl_job(active)}), 409

    configured = _facebook_profile_lookup(url) or {}
    limit_default = 330 if mode == "first" else configured.get("daily_limit", 30)
    limit = _clamp_int(payload.get("limit"), limit_default, 1, FACEBOOK_MANUAL_CRAWL_MAX_LIMIT)
    days = _clamp_int(payload.get("days"), configured.get("range_days", 7), 1, 60)
    job = {
        "id": uuid4().hex[:12],
        "status": "queued",
        "stage": "queued",
        "mode": mode,
        "profile_url": url,
        "broker_name": (payload.get("broker_name") or configured.get("broker_name") or "").strip(),
        "city": (payload.get("city") or configured.get("city") or "").strip(),
        "limit": limit,
        "days": days,
        "download_images": payload.get("download_images", True) is not False,
        "created_at": _utc_iso_z(),
        "started_at": None,
        "finished_at": None,
        "progress_pct": 0,
        "progress_label": "Đang chờ chạy",
        "stats": {},
        "logs": [],
    }
    with FACEBOOK_CRAWL_LOCK:
        FACEBOOK_CRAWL_JOBS[job["id"]] = job
        FACEBOOK_CRAWL_JOB_ORDER.insert(0, job["id"])
        del FACEBOOK_CRAWL_JOB_ORDER[20:]
    thread = threading.Thread(target=_run_admin_facebook_crawl_job, args=(job["id"],), daemon=True)
    thread.start()
    return jsonify({"ok": True, "job": _public_crawl_job(job)})


@require_admin_auth
def admin_api_facebook_crawl_jobs(job_id=None):
    with FACEBOOK_CRAWL_LOCK:
        if job_id:
            job = FACEBOOK_CRAWL_JOBS.get(job_id)
            if not job:
                return jsonify({"ok": False, "error": "not_found"}), 404
            return jsonify({"job": _public_crawl_job(job)})
        jobs = [_public_crawl_job(FACEBOOK_CRAWL_JOBS[jid]) for jid in FACEBOOK_CRAWL_JOB_ORDER]
    return jsonify({"jobs": jobs})


@require_admin_auth
def admin_api_leads():
    return jsonify(admin_leads.list_leads(
        status=(request.args.get("status") or "").strip(),
        q=(request.args.get("q") or "").strip(),
    ))


@require_admin_auth
def admin_api_leads_export():
    csv_body = admin_leads.export_leads_csv(
        status=(request.args.get("status") or "").strip(),
        q=(request.args.get("q") or "").strip(),
    )
    return Response(
        csv_body,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=radarbds_leads.csv"},
    )


@require_admin_auth
def admin_api_update_lead_status(lead_id):
    payload = request.get_json(silent=True) or {}
    result, status = admin_leads.update_lead_status(
        lead_id,
        (payload.get("status") or "").strip(),
        audit_writer=_write_admin_audit,
    )
    return jsonify(result), status


@require_admin_auth
def admin_api_delete_lead(lead_id):
    result, status = admin_leads.delete_lead(lead_id, audit_writer=_write_admin_audit)
    return jsonify(result), status


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
        signal_condition = actionable_signal_sql("v")
        where = ["COALESCE(l.probably_sold,0)=0", "COALESCE(l.is_blacklisted,0)=0", signal_condition, "COALESCE(v.mos_pct,0) BETWEEN ? AND ?"]
        params = [mos_min, mos_max]
        if ward:
            where.append("l.ward = ?")
            params.append(ward)
        if source:
            where.append("l.source = ?")
            params.append(source)
        rows = conn.execute(f"""
            WITH {LATEST_VALUATION_CTE}
            SELECT l.id, l.title, l.url, l.ward, l.source, l.price_ty, l.area_m2,
                   l.property_type, l.price_dropped, l.possibly_duplicate,
                   COALESCE(v.mos_pct,0) AS mos_pct, COALESCE(v.signal_score,0) AS signal_score,
                   f.verdict, f.created_at AS feedback_at
            FROM listings l
            JOIN latest_valuation v ON v.listing_id = l.id
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


@require_admin_auth
def admin_api_data_quality_summary():
    return jsonify(_data_quality_summary())


@require_admin_auth
def admin_api_ai_training_feedback():
    payload = request.get_json(silent=True) or {}
    try:
        listing_id = int(payload.get("listing_id") or 0)
    except (TypeError, ValueError):
        listing_id = 0
    if listing_id <= 0:
        return jsonify({"ok": False, "error": "invalid_listing_id"}), 400
    extraction_verdict = (payload.get("extraction_verdict") or "all_correct").strip()
    if extraction_verdict != "all_correct":
        return jsonify({"ok": False, "error": "valuation_feedback_only"}), 400
    payload["extraction_verdict"] = "all_correct"
    with db_mod.get_conn() as conn:
        try:
            result = _save_ai_training_feedback(conn, listing_id, payload)
        except ValueError:
            return jsonify({"ok": False, "error": "invalid_verdict"}), 400
    return jsonify({"ok": True, **result})


@require_admin_auth
def admin_api_ai_training_items():
    return _admin_review_items_response(allowed_queues=("main",), default_queue="main")


@require_admin_auth
def admin_api_data_quality_items():
    return _admin_review_items_response(
        allowed_queues=("recheck", "source_qc", "legal_qc"),
        default_queue="source_qc",
    )


def _admin_review_items_response(*, allowed_queues, default_queue):
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
    queue = (request.args.get("queue") or default_queue).strip()
    if queue not in allowed_queues:
        queue = default_queue
    model_signal_condition = "COALESCE(v.is_signal,0)=1"
    signal_condition = actionable_signal_sql("v")
    listing_condition = actionable_listing_sql("l")
    effective_legal_status_sql = "COALESCE(NULLIF(lv.status, 'unverified'), v.legal_status, lv.status, 'unverified')"

    where = [
        "COALESCE(l.probably_sold,0)=0",
        "COALESCE(l.is_blacklisted,0)=0",
    ]
    params = []
    if queue == "recheck":
        where.append(model_signal_condition)
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
            "COALESCE(v.source_quality_recheck,0)=1",
        ])
    elif queue == "needs_valuation":
        where.extend([
            model_signal_condition,
            "COALESCE(f.extraction_verdict,'all_correct') = 'all_correct'",
            "(f.verdict = 'bad_data' OR f.valuation_verdict = 'bad_data')",
        ])
    elif queue == "legal_qc":
        where.extend([
            model_signal_condition,
            "COALESCE(l.review_hidden,0)=0",
            f"""(
                {effective_legal_status_sql} IN ('unverified')
                OR (
                    f.verdict = 'bad_data'
                    AND f.extraction_verdict IN ('wrong_road','wrong_area','wrong_ward')
                )
            )""",
        ])
    else:
        where.append(signal_condition)
        where.append(listing_condition)
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
          CASE {legal_status}
            WHEN 'unverified' THEN 0
            ELSE 5
          END ASC,
          COALESCE(v.trust_score,0) ASC,
          COALESCE(v.signal_score,0) DESC
        """.format(legal_status=effective_legal_status_sql) if queue == "legal_qc"
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
            LEFT JOIN legal_verifications lv ON lv.listing_id = l.id
    """

    with db_mod.get_conn() as conn:
        rows = conn.execute(f"""
            WITH {LATEST_VALUATION_CTE}
            SELECT l.id, l.title, l.url, l.source, l.ward, l.property_type,
                   l.price_ty, l.price_per_m2, l.area_m2, l.frontage_m, l.depth_m, l.road_tier,
                   l.road_type, l.has_so, l.description,
                   COALESCE(l.posted_at, l.first_seen_at, l.crawled_at) AS posted_display,
                   v.mos_pct, v.signal_score, v.fair_ppm2, v.actual_ppm2,
                   v.segment, v.n_segment, v.source_quality_flags, v.source_quality_recheck,
                   COALESCE(v.trust_tier, lv.trust_tier, 'candidate_signal') AS trust_tier,
                   COALESCE(v.trust_score, lv.confidence_score, 0) AS trust_score,
                   {effective_legal_status_sql} AS legal_status,
                   COALESCE(v.legal_flags, lv.conflict_flags, '') AS legal_flags,
                   lv.confidence_score AS legal_confidence_score,
                   lv.thua_so AS legal_thua_so,
                   lv.to_ban_do AS legal_to_ban_do,
                   lv.legal_area_m2, lv.legal_residential_m2,
                   lv.legal_address, lv.legal_ward,
                   lv.legal_road_text, lv.legal_road_code,
                   lv.road_match_status,
                   f.verdict AS feedback_verdict,
                   f.extraction_verdict, f.valuation_verdict, f.reason_tags,
                   r.verdict AS ai_verdict, r.confidence AS ai_confidence,
                   r.reasoning AS ai_reasoning, r.red_flags AS ai_red_flags,
                   r.needs_map_check AS ai_needs_map_check
            FROM listings l
            JOIN latest_valuation v ON v.listing_id = l.id
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
            WITH {LATEST_VALUATION_CTE}
            SELECT COUNT(*) c
            FROM listings l
            JOIN latest_valuation v ON v.listing_id = l.id
            {feedback_join}
            WHERE {where_sql} AND f.id IS NULL
        """, params).fetchone()["c"]

        total = conn.execute(f"""
            WITH {LATEST_VALUATION_CTE}
            SELECT COUNT(*) c
            FROM listings l
            JOIN latest_valuation v ON v.listing_id = l.id
            {feedback_join}
            WHERE {where_sql}
        """, params).fetchone()["c"]
        if queue == "recheck":
            pending = total
        if queue in ("source_qc", "needs_valuation", "legal_qc"):
            pending = total

        ward_where = [
            "COALESCE(l.probably_sold,0)=0",
            "COALESCE(l.is_blacklisted,0)=0",
            "l.ward IS NOT NULL",
            "l.ward <> ''",
        ]
        ward_params = []
        if queue == "recheck":
            ward_where.append(model_signal_condition)
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
                "COALESCE(v.source_quality_recheck,0)=1",
            ])
        elif queue == "needs_valuation":
            ward_where.extend([
                model_signal_condition,
                "COALESCE(f.extraction_verdict,'all_correct') = 'all_correct'",
                "(f.verdict = 'bad_data' OR f.valuation_verdict = 'bad_data')",
            ])
        elif queue == "legal_qc":
            ward_where.extend([
                model_signal_condition,
                "COALESCE(l.review_hidden,0)=0",
                f"""(
                    {effective_legal_status_sql} IN ('unverified')
                    OR (
                        f.verdict = 'bad_data'
                        AND f.extraction_verdict IN ('wrong_road','wrong_area','wrong_ward')
                    )
                )""",
            ])
        else:
            ward_where.append(signal_condition)
            ward_where.append(listing_condition)

        ward_rows = conn.execute(f"""
            WITH {LATEST_VALUATION_CTE}
            SELECT DISTINCT l.ward
            FROM listings l
            JOIN latest_valuation v ON v.listing_id = l.id
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
                f"WHERE listing_id=? ORDER BY {_image_order_sql()}",
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
            d["is_needs_valuation"] = queue == "needs_valuation"
            d["is_legal_qc"] = queue == "legal_qc"
            d["legal_summary"] = {
                "status": d.get("legal_status") or "unverified",
                "trust_tier": d.get("trust_tier") or "candidate_signal",
                "trust_score": d.get("trust_score") or 0,
                "confidence_score": d.get("legal_confidence_score") or d.get("trust_score") or 0,
                "flags": d.get("legal_flags") or "",
                "thua_so": d.get("legal_thua_so"),
                "to_ban_do": d.get("legal_to_ban_do"),
                "legal_area_m2": d.get("legal_area_m2"),
                "legal_residential_m2": d.get("legal_residential_m2"),
                "legal_ward": d.get("legal_ward"),
                "legal_road_text": d.get("legal_road_text"),
                "legal_road_code": d.get("legal_road_code"),
                "road_match_status": d.get("road_match_status"),
                "legal_address": d.get("legal_address"),
            }
            missing = []
            for key, label in (("ward", "phuong"), ("property_type", "loai_hinh"), ("area_m2", "dien_tich"), ("road_tier", "duong")):
                if d.get(key) in (None, "", 0):
                    missing.append(label)
            d["explain"] = {
                "mos_pct": d.get("mos_pct"),
                "signal_score": d.get("signal_score"),
                "trust_tier": d.get("trust_tier"),
                "trust_score": d.get("trust_score"),
                "legal_status": d.get("legal_status"),
                "legal_flags": d.get("legal_flags"),
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
            else "Legal QC" if queue == "legal_qc"
            else "Cần phân loại valuation" if queue == "needs_valuation"
            else "Review mới"
        ),
    })


@require_admin_auth
def admin_api_legal_verification():
    payload = request.get_json(silent=True) or {}
    try:
        listing_id = int(payload.get("listing_id") or 0)
    except (TypeError, ValueError):
        listing_id = 0
    if listing_id <= 0:
        return jsonify({"ok": False, "error": "invalid_listing_id"}), 400

    with db_mod.get_conn() as conn:
        listing = conn.execute(
            """
            SELECT id, title, description, ward, area_m2, road_type,
                   tho_cu_m2, tho_cu_ratio
              FROM listings
             WHERE id=?
            """,
            (listing_id,),
        ).fetchone()
        if not listing:
            return jsonify({"ok": False, "error": "not_found"}), 404

        existing = conn.execute(
            "SELECT * FROM legal_verifications WHERE listing_id=?",
            (listing_id,),
        ).fetchone()
        latest_doc = None
        if LEGAL_IMAGE_EVIDENCE_ENABLED:
            latest_doc = conn.execute(
                """
                SELECT id
                  FROM listing_images
                 WHERE listing_id=? AND img_type='so_hong'
                 ORDER BY img_order, id
                 LIMIT 1
                """,
                (listing_id,),
            ).fetchone()

        legal_fields = dict(existing) if existing else {}
        if not LEGAL_IMAGE_EVIDENCE_ENABLED:
            legal_fields.pop("document_image_id", None)
        if latest_doc:
            legal_fields.setdefault("document_image_id", latest_doc["id"])
        for key in (
            "thua_so", "to_ban_do", "legal_area_m2", "legal_residential_m2",
            "legal_address", "legal_ward", "legal_road_text", "legal_road_code",
        ):
            if key in payload:
                legal_fields[key] = payload.get(key) or None
        status = (payload.get("status") or "").strip() or None

        from cleansing.legal_verification import (
            LEGAL_STATUSES,
            conflict_flags_text,
            upsert_legal_verification,
            verify_legal_listing,
        )

        admin_status = status if status in LEGAL_STATUSES else None
        result = verify_legal_listing(
            listing,
            legal_fields,
            has_legal_doc=bool(LEGAL_IMAGE_EVIDENCE_ENABLED and legal_fields.get("document_image_id")),
            admin_status=admin_status,
        )
        upsert_legal_verification(
            conn,
            result,
            verified_by=None,
        )
        flags_text = conflict_flags_text(result["conflict_flags"])
        conn.execute(
            """
            UPDATE valuation_results
               SET legal_status=?,
                   trust_tier=?,
                   trust_score=?,
                   legal_flags=?
             WHERE id = (
                SELECT id FROM valuation_results
                 WHERE listing_id=?
                 ORDER BY computed_at DESC, id DESC
                 LIMIT 1
             )
            """,
            (
                result["status"],
                result["trust_tier"],
                result["confidence_score"],
                flags_text,
                listing_id,
            ),
        )
    return jsonify({"ok": True, "legal_summary": {**result, "conflict_flags": flags_text}})


@require_admin_auth
def admin_api_ai_training_disagreements():
    """Read-only: nơi nhãn người (f) và verdict Claude (r) xung đột bucket.

    Lọc CHẶT — chỉ hiện khi cả hai phía đã có nhãn latest VÀ bucket ngược nhau;
    `maybe` / `insufficient_info` (NEUTRAL) tự loại. Chỉ surfacing, KHÔNG ghi.
    """
    with db_mod.get_conn() as conn:
        rows = conn.execute("""
            WITH latest_valuation AS (
                SELECT DISTINCT ON (vr.listing_id) vr.*
                FROM valuation_results vr
                ORDER BY vr.listing_id, vr.computed_at DESC, vr.id DESC
            )
            SELECT l.id, l.title, l.url, l.ward, l.price_ty, l.area_m2,
                   v.mos_pct, v.signal_score,
                   f.verdict AS human_verdict, f.created_at AS human_at,
                   r.verdict AS ai_verdict, r.confidence AS ai_confidence,
                   r.reasoning AS ai_reasoning, r.red_flags AS ai_red_flags,
                   r.needs_map_check AS ai_needs_map_check
            FROM listings l
            JOIN latest_valuation v ON v.listing_id = l.id
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


@require_admin_auth
def admin_api_qc_duplicates():
    ambiguous_duplicate_sql = """
              AND (
                   l.source <> 'facebook'
                OR c.source <> 'facebook'
                OR COALESCE(l.ward,'') = ''
                OR COALESCE(c.ward,'') = ''
                OR l.ward <> c.ward
                OR COALESCE(l.property_type,'') = ''
                OR COALESCE(c.property_type,'') = ''
                OR l.property_type <> c.property_type
                OR COALESCE(l.area_m2,0) <= 0
                OR COALESCE(c.area_m2,0) <= 0
                OR ABS(l.area_m2 - c.area_m2) >
                   CASE
                     WHEN l.area_m2 < c.area_m2
                     THEN CASE WHEN l.area_m2 * 0.03 > 3.0 THEN l.area_m2 * 0.03 ELSE 3.0 END
                     ELSE CASE WHEN c.area_m2 * 0.03 > 3.0 THEN c.area_m2 * 0.03 ELSE 3.0 END
                   END
                OR (
                    l.frontage_m IS NOT NULL
                    AND c.frontage_m IS NOT NULL
                    AND ABS(l.frontage_m - c.frontage_m) > 0.35
                )
                OR (
                    l.depth_m IS NOT NULL
                    AND c.depth_m IS NOT NULL
                    AND ABS(l.depth_m - c.depth_m) > 0.8
                )
              )
    """
    with db_mod.get_conn() as conn:
        road_name_select_l = "l.road_name" if _has_listing_column(conn, "road_name") else "NULL"
        road_name_select_c = "c.road_name" if _has_listing_column(conn, "road_name") else "NULL"
        rows = conn.execute(f"""
            SELECT l.id, l.title, l.url, l.source, l.source_id, l.ward, l.property_type, l.price_ty, l.area_m2,
                   l.frontage_m, l.depth_m, l.tho_cu_m2, l.contact_phone,
                   l.description, COALESCE(l.posted_at, l.crawled_at, l.updated_at) AS dt,
                   l.duplicate_of_id, c.title AS canonical_title, c.url AS canonical_url,
                   {road_name_select_l} AS road_name,
                   c.source AS canonical_source, c.source_id AS canonical_source_id, c.ward AS canonical_ward,
                   c.property_type AS canonical_property_type,
                   c.price_ty AS canonical_price_ty, c.area_m2 AS canonical_area_m2,
                   c.frontage_m AS canonical_frontage_m, c.depth_m AS canonical_depth_m,
                   c.tho_cu_m2 AS canonical_tho_cu_m2, c.contact_phone AS canonical_contact_phone,
                   {road_name_select_c} AS canonical_road_name, c.description AS canonical_description,
                   COALESCE(c.posted_at, c.crawled_at, c.updated_at) AS canonical_dt,
                   li.local_path AS img_local, li.img_url AS img_url,
                   ci.local_path AS canonical_img_local, ci.img_url AS canonical_img_url
            FROM listings l
            JOIN listings c ON c.id = l.duplicate_of_id
            LEFT JOIN listing_images li ON li.id = (
                SELECT id FROM listing_images WHERE listing_id = l.id ORDER BY {_image_order_sql()} LIMIT 1
            )
            LEFT JOIN listing_images ci ON ci.id = (
                SELECT id FROM listing_images WHERE listing_id = c.id ORDER BY {_image_order_sql()} LIMIT 1
            )
            WHERE COALESCE(l.probably_sold,0)=0
              AND COALESCE(l.is_blacklisted,0)=0
              AND l.possibly_duplicate=1
              AND NOT (
                l.source = c.source
                AND (
                     (COALESCE(l.source_id,'') <> '' AND l.source_id = c.source_id)
                  OR (COALESCE(l.url,'') <> '' AND l.url = c.url)
                )
              )
              {ambiguous_duplicate_sql}
            ORDER BY l.updated_at DESC
            LIMIT 500
        """).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            if _admin_same_listing_identity(item):
                continue
            if _admin_should_auto_merge_duplicate_pair(item):
                continue
            if _admin_should_auto_split_duplicate_pair(item):
                continue
            if _admin_should_hide_safe_duplicate_review_pair(item):
                continue
            items.append(_admin_duplicate_qc_item(row))
        existing_pairs = {(item["id"], item["duplicate_of_id"]) for item in items}
        if len(items) < 500:
            items.extend(_admin_suspected_duplicate_items(conn, existing_pairs, 500 - len(items)))
    return jsonify({"items": items})


def _admin_duplicate_qc_item(row, *, suspected: bool = False) -> dict:
    item = dict(row)
    item["detail_url"] = f"/listing/{item['id']}"
    item["canonical_detail_url"] = f"/listing/{item['duplicate_of_id']}"
    item["image"] = resolve_image_url(item.pop("img_local"), item.pop("img_url"))
    item["canonical_image"] = resolve_image_url(item.pop("canonical_img_local"), item.pop("canonical_img_url"))
    item["description_excerpt"] = (item.get("description") or "")[:260]
    item["canonical_description_excerpt"] = (item.get("canonical_description") or "")[:260]
    item["suspected_duplicate"] = bool(suspected)
    reasons = _duplicate_qc_reasons(item)
    item["qc_reasons"] = (["Nghi ngờ cùng lô"] + reasons) if suspected else reasons
    for key in ("contact_phone", "canonical_contact_phone"):
        item.pop(key, None)
    return item


def _admin_same_listing_identity(item: dict) -> bool:
    source = (item.get("source") or "").strip()
    canonical_source = (item.get("canonical_source") or "").strip()
    if not source or source != canonical_source:
        return False

    source_id = (item.get("source_id") or "").strip()
    canonical_source_id = (item.get("canonical_source_id") or "").strip()
    if source_id and canonical_source_id and source_id == canonical_source_id:
        return True

    url = (item.get("url") or "").strip().rstrip("/")
    canonical_url = (item.get("canonical_url") or "").strip().rstrip("/")
    return bool(url and canonical_url and url == canonical_url)


def _has_listing_column(conn, column_name: str) -> bool:
    try:
        return bool(conn.execute(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema='public'
              AND table_name='listings'
              AND column_name=?
            """,
            (column_name,),
        ).fetchone())
    except Exception:
        return False


def _admin_listing_from_duplicate_item(item: dict, *, canonical: bool = False) -> dict:
    prefix = "canonical_" if canonical else ""
    return {
        "id": item.get("duplicate_of_id") if canonical else item.get("id"),
        "source": item.get(f"{prefix}source"),
        "source_id": item.get(f"{prefix}source_id"),
        "title": item.get(f"{prefix}title"),
        "description": item.get(f"{prefix}description"),
        "ward": item.get(f"{prefix}ward"),
        "property_type": item.get(f"{prefix}property_type"),
        "area_m2": item.get(f"{prefix}area_m2"),
        "frontage_m": item.get(f"{prefix}frontage_m"),
        "depth_m": item.get(f"{prefix}depth_m"),
        "road_name": item.get(f"{prefix}road_name"),
        "contact_phone": item.get(f"{prefix}contact_phone"),
        "price_ty": item.get(f"{prefix}price_ty"),
        "price_per_m2": item.get(f"{prefix}price_per_m2"),
        "tho_cu_m2": item.get(f"{prefix}tho_cu_m2"),
        "posted_at": item.get(f"{prefix}dt"),
        "crawled_at": item.get(f"{prefix}dt"),
    }


def _admin_near_value(a, b, *, abs_tol: float, rel_tol: float) -> bool:
    a_num = _safe_float(a)
    b_num = _safe_float(b)
    if a_num is None or b_num is None or a_num <= 0 or b_num <= 0:
        return False
    return abs(a_num - b_num) <= max(abs_tol, min(a_num, b_num) * rel_tol)


def _admin_phone_tail(value) -> str:
    digits = re.sub(r"\D", "", value or "")
    return digits[-9:] if len(digits) >= 9 else ""


def _admin_distinctive_area(value) -> bool:
    area = _safe_float(value)
    if area is None or area <= 0:
        return False
    rounded = round(area)
    if abs(area - rounded) > 0.05:
        return True
    if rounded <= 0:
        return False
    # Common template lot sizes should not be treated as unique identifiers.
    if rounded % 50 == 0:
        return False
    if area <= 400 and rounded % 25 == 0:
        return False
    return True


def _admin_road_conflict(item: dict) -> bool:
    try:
        from cleansing.dedup import _combined_text, _road_tokens
    except Exception:
        return False

    listing = _admin_listing_from_duplicate_item(item)
    canonical = _admin_listing_from_duplicate_item(item, canonical=True)
    roads_a = _road_tokens(_combined_text(listing))
    roads_b = _road_tokens(_combined_text(canonical))
    if roads_a and roads_b:
        return not bool(roads_a.intersection(roads_b))

    road_name_a = (listing.get("road_name") or "").strip().casefold()
    road_name_b = (canonical.get("road_name") or "").strip().casefold()
    return bool(road_name_a and road_name_b and road_name_a != road_name_b)


def _admin_should_auto_split_duplicate_pair(item: dict) -> bool:
    if _admin_same_listing_identity(item):
        return False
    if item.get("source") != "facebook" or item.get("canonical_source") != "facebook":
        return False
    return _admin_road_conflict(item)


def _admin_should_auto_merge_duplicate_pair(item: dict) -> bool:
    if _admin_same_listing_identity(item):
        return False
    if item.get("source") != "facebook" or item.get("canonical_source") != "facebook":
        return False

    ward = (item.get("ward") or "").strip()
    canonical_ward = (item.get("canonical_ward") or "").strip()
    both_wards_missing = not ward and not canonical_ward
    one_ward_missing = bool(ward) != bool(canonical_ward)
    if ward and canonical_ward and ward != canonical_ward:
        return False
    if (item.get("property_type") or "") != (item.get("canonical_property_type") or ""):
        return False

    area_a = _safe_float(item.get("area_m2"))
    area_b = _safe_float(item.get("canonical_area_m2"))
    both_areas_missing = (area_a is None or area_a <= 0) and (area_b is None or area_b <= 0)
    area_match = _admin_near_value(area_a, area_b, abs_tol=1.0, rel_tol=0.005)
    distinctive_area_match = area_match and (_admin_distinctive_area(area_a) or _admin_distinctive_area(area_b))
    if not area_match and not both_areas_missing:
        return False
    if one_ward_missing and not distinctive_area_match:
        return False

    tc_a = _safe_float(item.get("tho_cu_m2"))
    tc_b = _safe_float(item.get("canonical_tho_cu_m2"))
    if (tc_a is None) != (tc_b is None):
        return False
    if tc_a is not None and not _admin_near_value(tc_a, tc_b, abs_tol=1.0, rel_tol=0.01):
        return False

    try:
        from cleansing.dedup import _combined_text, _road_tokens, _text_similarity
    except Exception:
        return False

    listing = _admin_listing_from_duplicate_item(item)
    canonical = _admin_listing_from_duplicate_item(item, canonical=True)
    roads_a = _road_tokens(_combined_text(listing))
    roads_b = _road_tokens(_combined_text(canonical))
    road_name_a = (listing.get("road_name") or "").strip().casefold()
    road_name_b = (canonical.get("road_name") or "").strip().casefold()
    shared_road = bool(roads_a and roads_b and roads_a.intersection(roads_b))
    same_road_name = bool(road_name_a and road_name_b and road_name_a == road_name_b)
    road_conflict = bool((roads_a and roads_b and not shared_road) or (road_name_a and road_name_b and not same_road_name))

    frontage_match = _admin_near_value(item.get("frontage_m"), item.get("canonical_frontage_m"), abs_tol=0.1, rel_tol=0.005)
    depth_match = _admin_near_value(item.get("depth_m"), item.get("canonical_depth_m"), abs_tol=0.3, rel_tol=0.005)
    dims_match = frontage_match and depth_match
    text_sim = _text_similarity(_combined_text(listing), _combined_text(canonical))
    phone_a = _admin_phone_tail(item.get("contact_phone"))
    phone_b = _admin_phone_tail(item.get("canonical_contact_phone"))
    same_phone = bool(phone_a and phone_a == phone_b)

    if road_conflict:
        return False

    if both_areas_missing:
        if not same_phone:
            return False
        return text_sim >= 0.86

    if distinctive_area_match and text_sim >= 0.86:
        return True

    if distinctive_area_match and text_sim >= 0.82:
        return bool(
            same_phone
            or dims_match
            or shared_road
            or same_road_name
            or (ward and canonical_ward and ward == canonical_ward)
        )

    if both_wards_missing:
        return bool(dims_match and (text_sim >= 0.88 or same_phone))

    if not shared_road and not same_road_name:
        return False

    if dims_match and (text_sim >= 0.55 or same_phone):
        return True
    return bool(text_sim >= 0.92 and (dims_match or same_phone))


def _admin_should_hide_safe_duplicate_review_pair(item: dict) -> bool:
    if _admin_same_listing_identity(item):
        return False
    if item.get("source") != "facebook" or item.get("canonical_source") != "facebook":
        return False
    if (item.get("property_type") or "") != (item.get("canonical_property_type") or ""):
        return False

    ward = (item.get("ward") or "").strip()
    canonical_ward = (item.get("canonical_ward") or "").strip()
    same_ward = bool(ward and canonical_ward and ward == canonical_ward)
    both_wards_missing = not ward and not canonical_ward
    if ward and canonical_ward and ward != canonical_ward:
        return False

    try:
        from cleansing.dedup import _combined_text, _road_tokens, _text_similarity
    except Exception:
        return False

    listing = _admin_listing_from_duplicate_item(item)
    canonical = _admin_listing_from_duplicate_item(item, canonical=True)
    text_a = _combined_text(listing)
    text_b = _combined_text(canonical)
    roads_a = _road_tokens(text_a)
    roads_b = _road_tokens(text_b)
    road_name_a = (listing.get("road_name") or "").strip().casefold()
    road_name_b = (canonical.get("road_name") or "").strip().casefold()
    shared_road = bool(roads_a and roads_b and roads_a.intersection(roads_b))
    same_road_name = bool(road_name_a and road_name_b and road_name_a == road_name_b)
    road_conflict = bool((roads_a and roads_b and not shared_road) or (road_name_a and road_name_b and not same_road_name))
    if road_conflict:
        return False

    text_sim = _text_similarity(text_a, text_b)
    area_a = _safe_float(item.get("area_m2"))
    area_b = _safe_float(item.get("canonical_area_m2"))
    both_areas_missing = (area_a is None or area_a <= 0) and (area_b is None or area_b <= 0)
    area_match_1pct = _admin_near_value(area_a, area_b, abs_tol=1.0, rel_tol=0.01)
    area_match_3pct = _admin_near_value(area_a, area_b, abs_tol=3.0, rel_tol=0.03)
    distinctive_area_match = area_match_3pct and (_admin_distinctive_area(area_a) or _admin_distinctive_area(area_b))
    relaxed_frontage_match = _admin_near_value(item.get("frontage_m"), item.get("canonical_frontage_m"), abs_tol=0.35, rel_tol=0.01)
    relaxed_depth_match = _admin_near_value(item.get("depth_m"), item.get("canonical_depth_m"), abs_tol=1.05, rel_tol=0.01)
    relaxed_dims_match = relaxed_frontage_match and relaxed_depth_match
    same_road = shared_road or same_road_name

    if both_areas_missing:
        if same_ward and text_sim >= 0.90:
            return True
        if same_road and text_sim >= 0.88:
            return True
        return False

    if same_ward and same_road and area_match_1pct and relaxed_dims_match:
        return True

    if both_wards_missing and distinctive_area_match and text_sim >= 0.80:
        return True

    if both_wards_missing and same_road and area_match_1pct and relaxed_dims_match and text_sim >= 0.70:
        return True

    return False


def _admin_apply_auto_duplicate_merge(conn, listing_id: int, target_id: int) -> None:
    note = "admin_qc_auto_merge_near_identical"
    existing = conn.execute(
        """
        SELECT 1
        FROM dedup_overrides
        WHERE action='merge'
          AND listing_id=?
          AND target_listing_id=?
          AND active=1
          AND COALESCE(note,'')=?
        LIMIT 1
        """,
        (listing_id, target_id, note),
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE listings SET possibly_duplicate=1, duplicate_of_id=? WHERE id=?",
            (target_id, listing_id),
        )
        return

    before = conn.execute(
        "SELECT id, possibly_duplicate, duplicate_of_id FROM listings WHERE id=?",
        (listing_id,),
    ).fetchone()
    conn.execute("""
        INSERT INTO dedup_overrides (action, listing_id, target_listing_id, note, active, updated_at)
        VALUES ('merge', ?, ?, ?, 1, datetime('now'))
    """, (listing_id, target_id, note))
    conn.execute(
        "UPDATE listings SET possibly_duplicate=1, duplicate_of_id=? WHERE id=?",
        (target_id, listing_id),
    )
    _write_admin_audit(
        conn,
        "dedup_auto_merge",
        "listing",
        listing_id,
        before=dict(before) if before else None,
        after={"id": listing_id, "possibly_duplicate": 1, "duplicate_of_id": target_id},
        reason=note,
    )


def _admin_apply_auto_duplicate_split(conn, listing_id: int, target_id: int) -> None:
    note = "admin_qc_auto_split_road_conflict"
    existing = conn.execute(
        """
        SELECT 1
        FROM dedup_overrides
        WHERE action='split'
          AND listing_id=?
          AND target_listing_id=?
          AND active=1
          AND COALESCE(note,'')=?
        LIMIT 1
        """,
        (listing_id, target_id, note),
    ).fetchone()
    if existing:
        conn.execute("UPDATE listings SET possibly_duplicate=0, duplicate_of_id=NULL WHERE id=?", (listing_id,))
        return

    before = conn.execute(
        "SELECT id, possibly_duplicate, duplicate_of_id FROM listings WHERE id=?",
        (listing_id,),
    ).fetchone()
    conn.execute("""
        INSERT INTO dedup_overrides (action, listing_id, target_listing_id, note, active, updated_at)
        VALUES ('split', ?, ?, ?, 1, datetime('now'))
    """, (listing_id, target_id, note))
    conn.execute("UPDATE listings SET possibly_duplicate=0, duplicate_of_id=NULL WHERE id=?", (listing_id,))
    _write_admin_audit(
        conn,
        "dedup_auto_split",
        "listing",
        listing_id,
        before=dict(before) if before else None,
        after={"id": listing_id, "possibly_duplicate": 0, "duplicate_of_id": None},
        reason=note,
    )


def _admin_is_suspected_duplicate_pair(item: dict) -> bool:
    if _admin_same_listing_identity(item):
        return False

    try:
        from cleansing.dedup import _has_reliable_lot_signature
    except Exception:
        return False

    listing = _admin_listing_from_duplicate_item(item)
    canonical = _admin_listing_from_duplicate_item(item, canonical=True)
    return _has_reliable_lot_signature(
        listing,
        canonical,
        allow_facebook_same_price=True,
    )


def _admin_suspected_duplicate_items(conn, existing_pairs: set[tuple[int, int]], limit: int) -> list[dict]:
    if limit <= 0:
        return []

    try:
        from cleansing.dedup import _combined_text, _road_tokens
    except Exception:
        return []

    road_name_select_l = "l.road_name" if _has_listing_column(conn, "road_name") else "NULL"
    road_name_select_c = "c.road_name" if _has_listing_column(conn, "road_name") else "NULL"
    candidate_rows = conn.execute(f"""
        SELECT id, source, source_id, url, title, description, area, ward, property_type,
               price_ty, price_per_m2, area_m2, frontage_m, depth_m,
               tho_cu_m2, {road_name_select_l} AS road_name, contact_phone,
               COALESCE(posted_at, crawled_at, updated_at) AS dt
        FROM listings l
        WHERE COALESCE(probably_sold,0)=0
          AND COALESCE(is_blacklisted,0)=0
          AND COALESCE(possibly_duplicate,0)=0
          AND duplicate_of_id IS NULL
          AND source='facebook'
          AND area_m2 IS NOT NULL
          AND area_m2 > 0
          AND property_type IN ('dat_nen','dat_vuon','nha_dat','nha_tro')
        ORDER BY COALESCE(updated_at, crawled_at, posted_at, '') DESC
        LIMIT 8000
    """).fetchall()
    split_rows = conn.execute("""
        SELECT listing_id, target_listing_id
        FROM dedup_overrides
        WHERE active=1
          AND action='split'
          AND listing_id IS NOT NULL
          AND target_listing_id IS NOT NULL
    """).fetchall()
    split_pairs = {
        tuple(sorted((int(r["listing_id"]), int(r["target_listing_id"]))))
        for r in split_rows
    }

    def compatible_type(a: str, b: str) -> bool:
        return a == b or {a, b}.issubset({"dat_nen", "dat_vuon"})

    from collections import defaultdict

    phone_pat = re.compile(r"(?:0|\+84)\d[\d\s.()-]{7,14}\d")

    def text_phone_tail(row: dict) -> str:
        text = f"{row.get('contact_phone') or ''} {row.get('title') or ''} {row.get('description') or ''}"
        for match in phone_pat.finditer(text):
            digits = re.sub(r"\D", "", match.group(0))
            if len(digits) >= 9:
                return digits[-9:]
        return ""

    buckets = defaultdict(list)
    for row in candidate_rows:
        d = dict(row)
        area = _safe_float(d.get("area_m2"))
        if not area:
            continue
        ward = (d.get("ward") or "").strip()
        prop = d.get("property_type") or ""
        type_keys = ["dat_land"] if prop in {"dat_nen", "dat_vuon"} else [prop]
        area_bucket = int(round(area / 10.0))
        d["_road_tokens"] = _road_tokens(_combined_text(d))
        d["_phone_tail"] = text_phone_tail(d)
        for type_key in type_keys:
            for token in d["_road_tokens"]:
                buckets[("road", token, type_key, area_bucket)].append(d)
            if d["_phone_tail"] and area >= 300:
                buckets[("phone_area", d["_phone_tail"], type_key, area_bucket)].append(d)

    pair_ids = []
    seen = set(existing_pairs)
    for bucket_rows in buckets.values():
        if len(bucket_rows) < 2:
            continue
        for idx, first in enumerate(bucket_rows):
            for second in bucket_rows[idx + 1:]:
                if first["id"] == second["id"]:
                    continue
                if not compatible_type(first.get("property_type"), second.get("property_type")):
                    continue
                area_a = _safe_float(first.get("area_m2"))
                area_b = _safe_float(second.get("area_m2"))
                if not area_a or not area_b:
                    continue
                if abs(area_a - area_b) > max(3.0, min(area_a, area_b) * 0.01):
                    continue
                if first.get("ward") and second.get("ward") and first.get("ward") != second.get("ward"):
                    continue
                first_roads = first.get("_road_tokens") or set()
                second_roads = second.get("_road_tokens") or set()
                shared_road = bool(first_roads and second_roads and first_roads.intersection(second_roads))
                same_phone = bool(first.get("_phone_tail") and first.get("_phone_tail") == second.get("_phone_tail"))
                if first_roads and second_roads and not shared_road:
                    continue
                if not shared_road and not same_phone:
                    continue
                older, newer = sorted(
                    (first, second),
                    key=lambda x: ((x.get("dt") or ""), int(x.get("id") or 0)),
                )
                pair = (older["id"], newer["id"])
                if pair in seen:
                    continue
                if tuple(sorted(pair)) in split_pairs:
                    continue
                item_probe = {
                    "id": older["id"],
                    "source": older.get("source"),
                    "source_id": older.get("source_id"),
                    "url": older.get("url"),
                    "title": older.get("title"),
                    "description": older.get("description"),
                    "ward": older.get("ward"),
                    "property_type": older.get("property_type"),
                    "area_m2": older.get("area_m2"),
                    "frontage_m": older.get("frontage_m"),
                    "depth_m": older.get("depth_m"),
                    "tho_cu_m2": older.get("tho_cu_m2"),
                    "road_name": older.get("road_name"),
                    "contact_phone": older.get("contact_phone"),
                    "price_ty": older.get("price_ty"),
                    "price_per_m2": older.get("price_per_m2"),
                    "dt": older.get("dt"),
                    "duplicate_of_id": newer["id"],
                    "canonical_source": newer.get("source"),
                    "canonical_source_id": newer.get("source_id"),
                    "canonical_url": newer.get("url"),
                    "canonical_title": newer.get("title"),
                    "canonical_description": newer.get("description"),
                    "canonical_ward": newer.get("ward"),
                    "canonical_property_type": newer.get("property_type"),
                    "canonical_area_m2": newer.get("area_m2"),
                    "canonical_frontage_m": newer.get("frontage_m"),
                    "canonical_depth_m": newer.get("depth_m"),
                    "canonical_tho_cu_m2": newer.get("tho_cu_m2"),
                    "canonical_road_name": newer.get("road_name"),
                    "canonical_contact_phone": newer.get("contact_phone"),
                    "canonical_price_ty": newer.get("price_ty"),
                    "canonical_price_per_m2": newer.get("price_per_m2"),
                    "canonical_dt": newer.get("dt"),
                }
                if not _admin_is_suspected_duplicate_pair(item_probe):
                    continue
                seen.add(pair)
                if _admin_should_auto_merge_duplicate_pair(item_probe):
                    continue
                pair_ids.append(pair)
                if len(pair_ids) >= limit:
                    break
            if len(pair_ids) >= limit:
                break
        if len(pair_ids) >= limit:
            break

    items = []
    for listing_id, target_id in pair_ids:
        row = conn.execute(f"""
        SELECT l.id, l.title, l.url, l.source, l.source_id, l.ward, l.property_type,
               l.price_ty, l.price_per_m2, l.area_m2, l.frontage_m, l.depth_m,
               l.tho_cu_m2, {road_name_select_l} AS road_name, l.contact_phone,
               l.description, COALESCE(l.posted_at, l.crawled_at, l.updated_at) AS dt,
               c.id AS duplicate_of_id, c.title AS canonical_title, c.url AS canonical_url,
               c.source AS canonical_source, c.source_id AS canonical_source_id,
               c.ward AS canonical_ward, c.property_type AS canonical_property_type,
               c.price_ty AS canonical_price_ty, c.price_per_m2 AS canonical_price_per_m2,
               c.area_m2 AS canonical_area_m2, c.frontage_m AS canonical_frontage_m,
               c.depth_m AS canonical_depth_m, c.tho_cu_m2 AS canonical_tho_cu_m2,
               {road_name_select_c} AS canonical_road_name,
               c.contact_phone AS canonical_contact_phone,
               c.description AS canonical_description,
               COALESCE(c.posted_at, c.crawled_at, c.updated_at) AS canonical_dt,
               li.local_path AS img_local, li.img_url AS img_url,
               ci.local_path AS canonical_img_local, ci.img_url AS canonical_img_url
        FROM listings l
        JOIN listings c ON c.id = ?
        LEFT JOIN listing_images li ON li.id = (
            SELECT id FROM listing_images WHERE listing_id = l.id ORDER BY {_image_order_sql()} LIMIT 1
        )
        LEFT JOIN listing_images ci ON ci.id = (
            SELECT id FROM listing_images WHERE listing_id = c.id ORDER BY {_image_order_sql()} LIMIT 1
        )
        WHERE l.id = ?
        """, (target_id, listing_id)).fetchone()
        if row:
            items.append(_admin_duplicate_qc_item(row, suspected=True))
    return items


def _duplicate_qc_reasons(item: dict) -> list[str]:
    reasons = []
    if item.get("source") != "facebook" or item.get("canonical_source") != "facebook":
        reasons.append("Khác hoặc không phải nguồn Facebook")
    if not item.get("ward") or not item.get("canonical_ward"):
        reasons.append("Thiếu phường")
    elif item.get("ward") != item.get("canonical_ward"):
        reasons.append("Khác phường")
    if not item.get("property_type") or not item.get("canonical_property_type"):
        reasons.append("Thiếu loại hình")
    elif item.get("property_type") != item.get("canonical_property_type"):
        reasons.append("Khác loại hình")

    area_a = _safe_float(item.get("area_m2"))
    area_b = _safe_float(item.get("canonical_area_m2"))
    if not area_a or not area_b:
        reasons.append("Thiếu diện tích")
    else:
        area_tolerance = max(3.0, min(area_a, area_b) * 0.03)
        if abs(area_a - area_b) > area_tolerance:
            reasons.append("Diện tích lệch")

    frontage_a = _safe_float(item.get("frontage_m"))
    frontage_b = _safe_float(item.get("canonical_frontage_m"))
    if frontage_a and frontage_b and abs(frontage_a - frontage_b) > 0.35:
        reasons.append("Ngang lệch")

    depth_a = _safe_float(item.get("depth_m"))
    depth_b = _safe_float(item.get("canonical_depth_m"))
    if depth_a and depth_b and abs(depth_a - depth_b) > 0.8:
        reasons.append("Dài lệch")

    return reasons or ["Cần kiểm tra thủ công"]


def _safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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
@require_admin_auth
def admin_api_users():
    return jsonify(admin_users.list_users(
        tier_filter=(request.args.get("tier") or "").strip(),
        q=(request.args.get("q") or "").strip(),
        effective_tier_fn=_effective_tier_from_user,
    ))


@require_admin_auth
def admin_api_delete_user(user_id):
    actor = current_user() or {}
    result, status = admin_users.delete_user(
        user_id,
        actor_id=actor.get("id"),
        audit_writer=_write_admin_audit,
    )
    return jsonify(result), status


@require_admin_auth
def admin_api_grant_vip(user_id):
    payload = request.get_json(silent=True) or {}
    result, status = admin_users.grant_vip(
        user_id,
        payload.get("days"),
        audit_writer=_write_admin_audit,
        log_audit_fn=log_audit,
    )
    return jsonify(result), status


@require_admin_auth
def admin_api_revoke_vip(user_id):
    result, status = admin_users.revoke_vip(
        user_id,
        audit_writer=_write_admin_audit,
        log_audit_fn=log_audit,
    )
    return jsonify(result), status


@require_admin_auth
def admin_api_ban_user(user_id):
    payload = request.get_json(silent=True) or {}
    result, status = admin_users.set_banned(
        user_id,
        bool(payload.get("banned", True)),
        audit_writer=_write_admin_audit,
    )
    return jsonify(result), status


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

def api_chat():
    return jsonify({
        "response": "Tính năng chat AI đã được tắt. Hệ thống hiện chỉ dùng dữ liệu parser và định giá nội bộ.",
        "disabled": True,
    }), 410

from routes import register_blueprints

register_blueprints(app)


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
            CREATE INDEX IF NOT EXISTS idx_listings_duplicate_of_id
            ON listings(duplicate_of_id)
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
            CREATE INDEX IF NOT EXISTS idx_images_listing_legal_order
            ON listing_images(
                listing_id,
                (CASE WHEN img_type = 'so_hong' THEN 0 ELSE 1 END),
                img_order,
                id
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_valuation_signal_score
            ON valuation_results(is_signal, signal_score DESC, mos_pct DESC)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_valuation_listing_computed
            ON valuation_results(listing_id, computed_at DESC, id DESC)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_valuation_signal_trust_score
            ON valuation_results(
                (CASE COALESCE(trust_tier, 'candidate_signal')
                    WHEN 'has_legal_doc' THEN 0
                    ELSE 1
                 END),
                trust_score DESC,
                signal_score DESC,
                mos_pct DESC,
                listing_id
            )
            WHERE is_signal = 1
        """)
        conn.commit()

if __name__ == "__main__":
    ensure_perf_indexes()
    app.run(
        host=os.getenv("FLASK_HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "5000")),
        debug=_env_flag("FLASK_DEBUG", False),
    )
