from __future__ import annotations

import os
import hmac
import json
import logging
import math
import mimetypes
import platform
import subprocess
import statistics
import re
import time
import urllib.request
import urllib.parse
import threading
import unicodedata
from copy import deepcopy
from contextlib import contextmanager
from decimal import Decimal
from functools import wraps
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4


def _load_local_env_file() -> None:
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        return
    allowed_keys = {
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
    }
    try:
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if not key:
                continue
            if not (
                key.startswith("RADAR_IMAGE_")
                or key.startswith("RADAR_S3_")
                or key in allowed_keys
            ):
                continue
            os.environ.setdefault(key, value.strip().strip('"').strip("'"))
    except OSError:
        logging.getLogger(__name__).warning("Unable to load local .env file", exc_info=True)


_load_local_env_file()

from flask import Flask, render_template, request, jsonify, send_from_directory, Response, make_response, abort, redirect
from config import database_sqlite as db_mod
from config.property_types import normalize_property_types
from db import facebook_profiles as db_facebook_profiles
from db.connection import DatabasePoolBusy, connect, get_conn
from db.public_dataset_versions import (
    DATASET_MARKET,
    DATASET_SIGNALS,
    get_dataset_versions,
)
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
    get_digital_product_commerce_settings,
)
from config.seo_articles import KNOWLEDGE_HUB, SEO_ARTICLES
from config.seo_pages import REPORT_HUB, SEO_PAGES
from config.planning_pages import (
    PLANNING_CATEGORY_LABELS,
    PLANNING_HUB,
    PLANNING_PAGES,
    PLANNING_PAGE_LIST,
)
from config.binh_duong_map import (
    BINH_DUONG_CURRENT_AREAS,
    BINH_DUONG_LEGACY_AREAS,
    BINH_DUONG_MAP_PAGE,
)
from config.city_map_products import (
    CITY_MAP_PRODUCTS,
    get_city_map_page,
)
from config.content_hubs import NEWS_HUBS, PLANNING_CATEGORY_PAGES
mimetypes.add_type("image/webp", ".webp")
mimetypes.add_type("application/geo+json; charset=utf-8", ".geojson")

# Import the extracted services
from services.market_data import load_counts, load_dashboard_summary, load_signals, load_trend_data, load_listing_detail, load_market_indicators, get_base_filters, get_city_for_ward, CITY_MAP, _days_ago, resolve_image_url, _range_filters, redact_for_tier, normalize_search_keyword, keyword_search_filter, group_price_drop_filter_sql, signal_badge_metadata, normalize_date_range, listing_date_range_filter, build_listing_filters, listing_activity_at_sql, listing_card_activity
from db.guland_publishers import (
    list_publishers,
    publisher_sort_rank_sql,
    publisher_visibility_sql,
    set_publisher_override,
)
from services.market_data import LATEST_SHADOW_VALUATION_CTE, _display_fair_sql, _display_mos_sql
from services.listing_map import (
    MapFilters,
    clear_listing_map_cache,
    load_listing_map_items,
    load_listing_map_summary,
)
from services.listing_comparables import load_listing_comparables
from services.listing_reports import (
    ListingReportError,
    list_listing_reports,
    submit_listing_report,
)
from services.signal_quality import (
    LATEST_VALUATION_CTE,
    actionable_listing_sql,
    actionable_signal_sql,
    split_quality_flags,
)
from services.advisory_memo import build_admin_valuation_workflow_markdown
from services.radar_assistant import build_assistant_response
from services import admin_growth, admin_leads, admin_quality, admin_users
from services import admin_jobs as admin_job_service
from db.admin_jobs import AdminJobAlreadyActive
from services.valuation_tool import (
    VALUATION_TOOL_CITY_MAP,
    ValuationToolError,
    estimate_property_value,
)
from services.tphcm_land_prices import (
    find_land_price_row,
    land_price_row_key,
    search_land_prices,
)
from services.tphcm_land_price_calculator import (
    CalculationValidationError,
    calculate_land_price,
    calculate_mixed_land_price,
)
from services.digital_products import (
    ProductAvailability,
    get_digital_product,
    get_release_availability,
)
from services.public_content import (
    PostgresPublicContentRepository,
    public_pdf_url,
)
from services.public_cache import (
    CacheResult,
    PublicCacheBusy,
    clear_local_public_cache,
    get_current_dataset_versions,
    get_or_load_public_payload,
)

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
    client_ip_from_request,
    log_audit,
    normalize_identifier,
    rate_limit,
    reject_cross_site_session_request,
    require_tier,
)

app = Flask(__name__)
app.before_request(reject_cross_site_session_request)
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
_public_content_repository = PostgresPublicContentRepository()


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
        # Shared SEO article/report partials use lowercase names. Keep both
        # aliases so every public template family receives the same values.
        "google_analytics_id": analytics_id,
        "google_search_console_verification": GOOGLE_SEARCH_CONSOLE_VERIFICATION,
    }


@app.context_processor
def inject_city_map_products():
    """Expose the canonical city-map registry to shared public templates."""

    city_nav_order = {
        "/ban-do-thu-dau-mot": 0,
        "/ban-do-di-an": 1,
        "/ban-do-thuan-an": 2,
        "/ban-do-ben-cat": 3,
    }
    return {
        "city_map_products": tuple(
            dict(page)
            for page in sorted(
                CITY_MAP_PRODUCTS.values(),
                key=lambda item: city_nav_order.get(item["path"], 99),
            )
        ),
        "planning_category_pages": tuple(
            dict(page) for page in PLANNING_CATEGORY_PAGES.values()
        ),
        "news_hub_pages": tuple(dict(page) for page in NEWS_HUBS.values()),
    }


@app.after_request
def add_response_headers(response):
    if request.path.startswith("/api/"):
        public_cache_classified = (
            request.path in {"/api/signals", "/api/counts", "/api/dashboard"}
            and (
                "X-Radar-Cache" in response.headers
                or response.headers.get("Cache-Control")
                in {"private, no-store", "no-store"}
            )
        )
        if not public_cache_classified:
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
            if request.path.startswith("/api/digital-products/orders/"):
                response.headers["Cache-Control"] = "private, no-store"
    elif any(
        request.path.startswith(f"{page['order_base_path']}/")
        for page in CITY_MAP_PRODUCTS.values()
    ):
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["Pragma"] = "no-cache"
    elif request.path.startswith("/static/") and request.args.get("v"):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net "
        "https://unpkg.com https://www.googletagmanager.com; style-src 'self' 'unsafe-inline' "
        "https://fonts.googleapis.com https://cdn.jsdelivr.net https://unpkg.com; font-src 'self' "
        "https://fonts.gstatic.com data:; img-src 'self' data: blob: https:; connect-src 'self' "
        "https://www.google-analytics.com https://region1.google-analytics.com "
        "https://analytics.google.com https://stats.g.doubleclick.net https://www.google.com "
        "https://www.googletagmanager.com; object-src 'none'; base-uri 'self'; "
        "frame-ancestors 'none'; form-action 'self'"
    )
    return response


LEAD_STATUSES = admin_leads.LEAD_STATUSES
POSITIVE_REVIEW_VERDICTS = {"good", "correct", "cheap_real"}
HARD_HIDE_REVIEW_VERDICTS = {"bad", "spam", "sold", "fake_price"}
SOFT_HIDE_REVIEW_VERDICTS = {"bad_data", "fair", "overpriced", "cannot_price"}
ADMIN_CONTROL_ROOM_PANEL_SLUGS = {
    "crm": "crm",
    "growth": "tang-truong",
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
VALUATION_TOOL_MIN_TIER = "guest"
TRAINING_VERDICTS = POSITIVE_REVIEW_VERDICTS | HIDE_REVIEW_VERDICTS | {"maybe"}
INFRA_KINDS = {"timeline", "policy"}
INFRA_STATUS = {"done", "in_progress", "planned"}
INFRA_SEVERITY = {"critical", "warning", "info"}
FACEBOOK_MANUAL_CRAWL_MAX_LIMIT = 950
ADMIN_READ_CACHE_TTL_SECONDS = float(os.getenv("RADAR_ADMIN_READ_CACHE_TTL_SECONDS", "20"))
ADMIN_READ_CACHE_MAX_ITEMS = 64
_ADMIN_READ_CACHE: dict[tuple, dict] = {}
_ADMIN_READ_CACHE_LOCK = threading.Lock()


def clear_admin_read_cache(scope: str | None = None) -> None:
    with _ADMIN_READ_CACHE_LOCK:
        if scope is None:
            _ADMIN_READ_CACHE.clear()
            return
        stale_scopes = {scope}
        if scope == "data_quality_summary":
            stale_scopes.update({"data_quality_items", "data_quality_item_wards"})
        stale_keys = [key for key in _ADMIN_READ_CACHE if key and key[0] in stale_scopes]
        for key in stale_keys:
            _ADMIN_READ_CACHE.pop(key, None)


def _cached_admin_read_payload(scope: str, key, loader, *, ttl_seconds: float | None = None):
    ttl = ADMIN_READ_CACHE_TTL_SECONDS if ttl_seconds is None else ttl_seconds
    cache_key = (scope, key)
    now = time.time()
    with _ADMIN_READ_CACHE_LOCK:
        entry = _ADMIN_READ_CACHE.get(cache_key)
        if entry and now - entry["ts"] <= ttl:
            return deepcopy(entry["payload"])
    payload = loader()
    with _ADMIN_READ_CACHE_LOCK:
        _ADMIN_READ_CACHE[cache_key] = {"ts": now, "payload": deepcopy(payload)}
        if len(_ADMIN_READ_CACHE) > ADMIN_READ_CACHE_MAX_ITEMS:
            oldest_key = min(_ADMIN_READ_CACHE, key=lambda k: _ADMIN_READ_CACHE[k]["ts"])
            _ADMIN_READ_CACHE.pop(oldest_key, None)
    return payload


def _clear_admin_crawl_data_caches() -> None:
    for scope in (
        "facebook_crawl_config",
        "facebook_crawl_profiles",
        "facebook_crawl_overview",
        "data_quality_summary",
        "growth",
        "duplicates",
        "qc_signals",
    ):
        clear_admin_read_cache(scope)


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
    return bool(
        auth
        and user
        and pwd
        and hmac.compare_digest(auth.username or "", user)
        and hmac.compare_digest(auth.password or "", pwd)
    )


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


def _single_connection_factory(conn):
    @contextmanager
    def _factory():
        yield conn

    return _factory


def _admin_profile_config_actor() -> str:
    user = current_user() or {}
    for key in ("email", "phone", "display_name", "id"):
        value = str(user.get(key) or "").strip()
        if value:
            return value[:200]
    return "admin"


def _read_facebook_profile_config(conn_factory=get_conn) -> list[dict]:
    return db_facebook_profiles.read_profile_config(conn_factory=conn_factory)


def _write_facebook_profile_config(profiles: list[dict], conn_factory=get_conn) -> list[dict]:
    return db_facebook_profiles.write_profile_config(
        profiles,
        conn_factory=conn_factory,
        updated_by=_admin_profile_config_actor(),
    )


def _facebook_profile_lookup(url: str) -> dict | None:
    return admin_quality.facebook_profile_lookup(url, _read_facebook_profile_config())


def _facebook_profile_stats(profile_urls: list[str]) -> dict:
    return admin_quality.facebook_profile_stats(profile_urls, conn_factory=get_conn)


def _facebook_profile_duplicate_analysis(profiles: list[dict], stats: dict) -> dict:
    return admin_quality.facebook_profile_duplicate_analysis(profiles, stats, conn_factory=get_conn)


def _missing_image_summary(conn, source: str | None = None) -> dict:
    return admin_quality.missing_image_summary(conn, source=source)


def _facebook_missing_image_summary(conn) -> dict:
    return admin_quality.facebook_missing_image_summary(conn)


def _facebook_crawl_summary() -> dict:
    active = _active_facebook_crawl_job()
    snapshot_jobs = {active["id"]: active} if active else {}
    snapshot_order = [active["id"]] if active else []
    return admin_quality.facebook_crawl_summary(
        conn_factory=get_conn,
        jobs=snapshot_jobs,
        job_order=snapshot_order,
        lock=threading.Lock(),
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


def _append_crawl_log(reporter: admin_job_service.AdminJobReporter, message: str) -> None:
    reporter.log(message)


def _set_crawl_progress(
    reporter: admin_job_service.AdminJobReporter,
    pct: int,
    stage: str | None = None,
    label: str | None = None,
) -> None:
    reporter.progress(_clamp_int(pct, 0, 0, 100), stage, label)


def _public_crawl_job(job: dict | None) -> dict | None:
    return admin_job_service.public_admin_job(job)


def _active_facebook_crawl_job() -> dict | None:
    admin_job_service.POSTGRES_ADMIN_JOBS.reconcile_stale()
    return admin_job_service.POSTGRES_ADMIN_JOBS.active()


def _enqueue_facebook_crawl_job(job: dict, target) -> dict:
    def _run_and_refresh_admin_cache() -> None:
        try:
            target(job["id"])
        finally:
            _clear_admin_crawl_data_caches()

    return admin_job_service.enqueue_admin_job(
        job,
        lambda _job_id: _run_and_refresh_admin_cache(),
    )


def _run_admin_facebook_crawl_job(job_id: str) -> None:
    from db.connection import advisory_lock
    from cli.crawlers import _facebook_crawl_to_raw, _clean_broker_images_after_download
    from cleansing.reprocess import run_full_reprocess
    from cleansing.download_images import download_images

    job = admin_job_service.POSTGRES_ADMIN_JOBS.get(job_id)
    if not job:
        raise KeyError(job_id)
    reporter = admin_job_service.AdminJobReporter(job_id)
    reporter.start("starting", "Đang chuẩn bị crawl")
    try:
        profile = {
            "url": job["profile_url"],
            "tier": job["limit"],
            "broker_name": job.get("broker_name") or None,
            "default_area": (job.get("context") or {}).get("city") or None,
        }
        crawl_mode = "incremental" if job["mode"] == "daily" else "full"
        max_age_days = job["days"] if job["mode"] == "range" else None
        with advisory_lock("admin-facebook-crawl"):
            _set_crawl_progress(reporter, 8, "crawl", "Đang gọi Apify")
            _append_crawl_log(
                reporter,
                f"Crawl {job['mode']} | limit={job['limit']} | profile={job.get('broker_name') or 'không tên'}",
            )

            def _crawl_progress(stage, done, total, stats):
                if stage != "import_raw":
                    return
                pct = 10
                if total:
                    pct = 10 + int((done / total) * 23)
                _set_crawl_progress(
                    reporter,
                    pct,
                    "import_raw",
                    f"Đang nhập raw {done}/{total} từ Apify",
                )
                if done and (done == total or done % 50 == 0):
                    _append_crawl_log(
                        reporter,
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
            _set_crawl_progress(reporter, 35, "crawl", "Đã lấy dữ liệu từ Facebook")
            _append_crawl_log(
                reporter,
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
                _set_crawl_progress(reporter, 42, "reprocess", "Đang reprocess listing")
                changed_raw_ids = []
                changed_raw_ids.extend(crawl_stats.get("inserted_raw_ids") or [])
                changed_raw_ids.extend(crawl_stats.get("refreshed_raw_ids") or [])
                changed_raw_ids = list(dict.fromkeys(changed_raw_ids))
                reprocess_kwargs = {"source": "facebook", "full": False}
                if changed_raw_ids:
                    reprocess_kwargs["raw_ids"] = changed_raw_ids
                    _append_crawl_log(reporter, f"Reprocess {len(changed_raw_ids)} raw vừa crawl/refresh.")
                reprocess_stats = run_full_reprocess(**reprocess_kwargs)
                job["stats"]["reprocess"] = reprocess_stats
                processed_ids = reprocess_stats.get("listings", {}).get("processed_ids") or []
                listing_reprocess = reprocess_stats.get("listings", {})
                _set_crawl_progress(reporter, 70, "reprocess", "Đã reprocess xong")
                _append_crawl_log(
                    reporter,
                    "Reprocess xong: "
                    f"processed={len(processed_ids)}, "
                    f"new={listing_reprocess.get('new', 0)}, "
                    f"updated={listing_reprocess.get('updated', 0)}, "
                    f"skipped={listing_reprocess.get('skipped', 0)}",
                )

                if job.get("download_images"):
                    _set_crawl_progress(reporter, 75, "download_images", "Đang tải ảnh")

                    def _download_progress(done, total, success):
                        if total:
                            pct = 75 + int((done / total) * 19)
                            _set_crawl_progress(
                                reporter,
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
                    _set_crawl_progress(reporter, 94, "download_images", "Đã tải ảnh xong")
                    _append_crawl_log(reporter, f"Tải ảnh xong: {downloaded} ảnh")
                    try:
                        _set_crawl_progress(reporter, 96, "cleanup", "Đang dọn ảnh môi giới")
                        _clean_broker_images_after_download(source="facebook", limit=max(200, job["limit"] * 12))
                    except Exception as exc:
                        _append_crawl_log(
                            reporter,
                            f"Clean ảnh môi giới lỗi nhẹ: {type(exc).__name__}",
                        )
                else:
                    _set_crawl_progress(reporter, 95, "reprocess", "Bỏ qua tải ảnh")
            else:
                _set_crawl_progress(reporter, 95, "crawl", "Không có bài mới")
                _append_crawl_log(reporter, "Không có bài mới hoặc ảnh mới, bỏ qua reprocess.")

        reporter.succeed(job.get("stats") or {})
    except Exception as exc:
        reporter.fail(exc)


# ═══════════════════════════════════════════════════════════════════════════
# RBAC: session cookie helpers + /api/auth/* endpoints
# ═══════════════════════════════════════════════════════════════════════════
def _run_admin_crawl_maintenance_job(job_id: str) -> None:
    from db.connection import advisory_lock
    from cleansing.reprocess import reprocess_valuation, run_full_reprocess

    job = admin_job_service.POSTGRES_ADMIN_JOBS.get(job_id)
    if not job:
        raise KeyError(job_id)
    reporter = admin_job_service.AdminJobReporter(job_id)
    reporter.start("starting", "Đang chuẩn bị")

    try:
        action = job.get("maintenance_action")
        lock_name = "reprocess" if action == "valuation_only" else "admin-manual-reprocess"
        with advisory_lock(lock_name):
            if action == "valuation_only":
                _set_crawl_progress(reporter, 12, "valuation", "Đang chạy valuation-only")
                _append_crawl_log(reporter, "Valuation-only full rerun bắt đầu.")
                stats = reprocess_valuation(incremental_ids=None)
                job.setdefault("stats", {})["valuation"] = stats
                _append_crawl_log(
                    reporter,
                    "Valuation-only xong: "
                    f"total={stats.get('total', 0)}, "
                    f"signals={stats.get('signals', 0)}, "
                    f"outliers={stats.get('outliers', 0)}",
                )
            else:
                _set_crawl_progress(reporter, 12, "reprocess", "Đang reprocess Facebook")
                _append_crawl_log(reporter, "Manual Facebook reprocess bắt đầu.")
                stats = run_full_reprocess(source="facebook", full=False)
                job.setdefault("stats", {})["reprocess"] = stats
                listing_stats = stats.get("listings", {})
                valuation_stats = stats.get("valuation", {})
                _append_crawl_log(
                    reporter,
                    "Manual reprocess xong: "
                    f"processed={len(listing_stats.get('processed_ids') or [])}, "
                    f"new={listing_stats.get('new', 0)}, "
                    f"updated={listing_stats.get('updated', 0)}, "
                    f"skipped={listing_stats.get('skipped', 0)}, "
                    f"valuated={valuation_stats.get('total', 0)}, "
                    f"signals={valuation_stats.get('signals', 0)}",
                )

        reporter.succeed(job.get("stats") or {})
    except Exception as exc:
        reporter.fail(exc)


def _run_admin_data_quality_image_job(job_id: str) -> None:
    from cleansing.download_images import download_images

    job = admin_job_service.POSTGRES_ADMIN_JOBS.get(job_id)
    if not job:
        raise KeyError(job_id)
    reporter = admin_job_service.AdminJobReporter(job_id)
    reporter.start("starting", "Đang chuẩn bị tải ảnh thiếu")

    try:
        limit = _clamp_int(job.get("limit"), 500, 1, 5000)

        def _download_progress(done, total, success):
            if total:
                _set_crawl_progress(
                    reporter,
                    10 + int((done / total) * 85),
                    "download_images",
                    f"Đang tải ảnh thiếu {done}/{total} (ok {success})",
                )

        _append_crawl_log(reporter, f"Tải ảnh thiếu bắt đầu | limit={limit}")
        downloaded = download_images(limit=limit, progress_callback=_download_progress)
        job.setdefault("stats", {})["downloaded_images"] = downloaded
        _append_crawl_log(reporter, f"Tải ảnh thiếu xong: {downloaded} ảnh")

        reporter.succeed(job.get("stats") or {})
    except Exception as exc:
        reporter.fail(exc)


def _run_admin_source_retry_job(job_id: str) -> None:
    from db.connection import advisory_lock
    from cli.crawlers import _clean_broker_images_after_download, _facebook_crawl_to_raw, _get_crawlers
    from cleansing.download_images import download_images
    from cleansing.reprocess import run_full_reprocess

    job = admin_job_service.POSTGRES_ADMIN_JOBS.get(job_id)
    if not job:
        raise KeyError(job_id)
    reporter = admin_job_service.AdminJobReporter(job_id)
    reporter.start("starting", "Đang chuẩn bị crawl lại nguồn")

    source = (job.get("source") or "").strip().lower()
    try:
        with advisory_lock(f"admin-retry-{source}-crawl"):
            total_new = 0
            if source == "facebook":
                _set_crawl_progress(reporter, 12, "crawl", "Đang crawl lại Facebook")
                stats = _facebook_crawl_to_raw(mode="incremental") or {}
                job.setdefault("stats", {})["crawl"] = stats
                total_new = int(stats.get("inserted", 0) or 0) + int(stats.get("refreshed_images", 0) or 0)
                _append_crawl_log(
                    reporter,
                    "Facebook retry xong: "
                    f"fetched={stats.get('fetched', 0)}, imported={stats.get('inserted', 0)}, "
                    f"refreshed={stats.get('refreshed_images', 0)}, skipped={stats.get('skipped', 0)}",
                )
                changed_raw_ids = list(dict.fromkeys(
                    (stats.get("inserted_raw_ids") or []) + (stats.get("refreshed_raw_ids") or [])
                ))
                reprocess_kwargs = {"source": "facebook", "full": False}
                if changed_raw_ids:
                    reprocess_kwargs["raw_ids"] = changed_raw_ids
            else:
                _set_crawl_progress(reporter, 12, "crawl", f"Đang crawl lại {source}")
                crawlers = _get_crawlers(source)
                source_stats = []
                for crawler in crawlers:
                    stats = crawler.run(mode="incremental", headless=True)
                    source_stats.append(stats)
                    total_new += int(stats.get("new", 0) or 0)
                    _append_crawl_log(
                        reporter,
                        f"{crawler.SOURCE_NAME} retry xong: "
                        f"new={stats.get('new', 0)}, skipped={stats.get('skipped', 0)}, errors={stats.get('errors', 0)}",
                    )
                job.setdefault("stats", {})["crawl"] = {"source": source, "runs": source_stats, "new": total_new}
                reprocess_kwargs = {"source": source, "full": False}

            if total_new > 0:
                _set_crawl_progress(reporter, 55, "reprocess", "Đang reprocess dữ liệu vừa crawl")
                reprocess_stats = run_full_reprocess(**reprocess_kwargs)
                job.setdefault("stats", {})["reprocess"] = reprocess_stats
                processed_ids = reprocess_stats.get("listings", {}).get("processed_ids") or []
                _set_crawl_progress(reporter, 78, "download_images", "Đang tải ảnh sau crawl")
                downloaded = download_images(limit=500, listing_ids=processed_ids or None)
                _clean_broker_images_after_download(source=source, limit=500)
            else:
                _set_crawl_progress(reporter, 78, "download_images", "Không có tin mới, tải backlog ảnh")
                downloaded = download_images(limit=200)
                _clean_broker_images_after_download(source=source, limit=200)
            job.setdefault("stats", {})["downloaded_images"] = downloaded
            _append_crawl_log(reporter, f"Ảnh tải thêm: {downloaded}")

        reporter.succeed(job.get("stats") or {})
    except Exception as exc:
        reporter.fail(exc)


def _cookie_kwargs():
    """HttpOnly + SameSite=Lax; production cookies fail closed to Secure."""
    return dict(
        httponly=True,
        samesite="Lax",
        secure=request.is_secure or PUBLIC_BASE_URL.lower().startswith("https://"),
        max_age=SESSION_TTL_DAYS * 86400,
        path="/",
    )


def _set_session_cookie(resp, token: str):
    resp.set_cookie(SESSION_COOKIE_NAME, token, **_cookie_kwargs())
    return resp


def _clear_session_cookie(resp):
    resp.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return resp


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

    token = create_session(user["id"], user_agent=request.headers.get("User-Agent", ""), ip=client_ip_from_request())
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

    token = create_session(user["id"], user_agent=request.headers.get("User-Agent", ""), ip=client_ip_from_request())
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
    prop_types = normalize_property_types(prop_types)

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
    log_audit(
        user_id=u["id"],
        tier=current_tier(),
        action="watchlist_create",
        context={
            "id": wid,
            "ward_count": len(json.loads(data["wards"] or "[]")),
            "prop_count": len(json.loads(data["prop_types"] or "[]")),
            "notify_telegram": bool(data["notify_telegram"]),
        },
    )
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


@require_tier("free")
def api_list_favorites():
    u = current_user()
    with db_mod.get_conn() as conn:
        rows = conn.execute(
            """
            SELECT listing_id
              FROM user_favorite_listings
             WHERE user_id=?
             ORDER BY created_at DESC, id DESC
            """,
            (u["id"],),
        ).fetchall()
    return jsonify({"ok": True, "listing_ids": [int(r["listing_id"]) for r in rows]})


def _favorite_listing_exists(conn, listing_id: int) -> bool:
    return bool(conn.execute(
        """
        SELECT 1
          FROM listings
         WHERE id=?
           AND COALESCE(is_blacklisted,0)=0
           AND COALESCE(review_hidden,0)=0
        """,
        (listing_id,),
    ).fetchone())


@require_tier("free")
def api_add_favorite(listing_id):
    u = current_user()
    with db_mod.get_conn() as conn:
        if not _favorite_listing_exists(conn, listing_id):
            return jsonify({"ok": False, "error": "not_found"}), 404
        conn.execute(
            """
            INSERT INTO user_favorite_listings (user_id, listing_id)
            VALUES (?, ?)
            ON CONFLICT(user_id, listing_id) DO NOTHING
            """,
            (u["id"], listing_id),
        )
    log_audit(u["id"], current_tier(), "favorite_listing_add", listing_id=listing_id)
    return jsonify({"ok": True, "listing_id": listing_id, "favorite": True})


@require_tier("free")
def api_remove_favorite(listing_id):
    u = current_user()
    with db_mod.get_conn() as conn:
        conn.execute(
            "DELETE FROM user_favorite_listings WHERE user_id=? AND listing_id=?",
            (u["id"], listing_id),
        )
    log_audit(u["id"], current_tier(), "favorite_listing_remove", listing_id=listing_id)
    return jsonify({"ok": True, "listing_id": listing_id, "favorite": False})


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
        send_message_to(chat_id, "Đã kết nối tài khoản RadarBDS. Bạn sẽ nhận thông báo deal khớp khu vực quan tâm.")
    except Exception:
        pass
    try:
        log_audit(
            user_id=u["id"],
            tier=current_tier(),
            action="telegram_linked",
            context={"source": "sync"},
        )
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
                  context={"source": "webhook"})
    except Exception:
        pass
    return jsonify({"ok": True, "matched": True, "user_id": user_id})


# ─────────────────────────────────────────────────────────────────────────────
# Conversion tracking (/api/track) — open to guests, used to measure funnel
# ─────────────────────────────────────────────────────────────────────────────
_CITY_MAP_PRODUCT_TRACK_SUFFIXES = {
    "product_viewed",
    "preview_selected",
    "purchase_clicked",
    "dashboard_clicked",
}
_CITY_MAP_CHECKOUT_TRACK_SUFFIXES = {
    "checkout_created",
    "qr_displayed",
    "payment_confirmed",
    "download_clicked",
}
_PRODUCT_TRACK_ACTIONS = {
    f"{page['tracking_prefix']}_{suffix}"
    for page in CITY_MAP_PRODUCTS.values()
    for suffix in _CITY_MAP_PRODUCT_TRACK_SUFFIXES
}
_CHECKOUT_TRACK_ACTIONS = {
    f"{page['tracking_prefix']}_{suffix}"
    for page in CITY_MAP_PRODUCTS.values()
    for suffix in _CITY_MAP_CHECKOUT_TRACK_SUFFIXES
}
_LISTING_MAP_TRACK_ACTIONS = {
    "listing_map_opened",
    "listing_map_closed",
    "listing_map_base_layer_changed",
    "listing_map_group_selected",
    "listing_map_retry",
}
_CITY_MAP_TRACK_IDENTITIES = tuple(
    {
        "path": page["path"],
        "page_slug": page["page_slug"],
        "product_slug": page["product_slug"],
    }
    for page in CITY_MAP_PRODUCTS.values()
)


ALLOWED_TRACK_ACTIONS = {
    "seo_landing_viewed",
    "report_viewed",
    "report_filter_used",
    "report_open",
    "report_dashboard_click",
    "report_listing_click",
    "social_utm_visit",
    "ai_referral_visit",
    "cta_clicked",
    "lead_capture_submit",
    "teaser_hit_12",
    "locked_tab_click",
    "locked_fresh_click",
    "locked_filter_click",
    "vip_cta_click",
    "cta_signup",
    "cta_vip",
    "lead_vip_click",
    "signup_completed",
    "watchlist_create",
    "telegram_linked",
    "modal_open",
    "listing_share",
    "map_layer_toggled",
    "map_fullscreen_clicked",
    "map_area_cta_clicked",
    "planning_hub_filter_selected",
    "planning_hub_card_clicked",
    "binh_duong_map_layer_selected",
    "binh_duong_map_base_layer_selected",
    "binh_duong_map_area_selected",
    "public_content_filter_used",
    "public_content_card_clicked",
    "public_document_download_clicked",
    "public_header_menu_opened",
    "public_header_item_clicked",
} | _PRODUCT_TRACK_ACTIONS | _CHECKOUT_TRACK_ACTIONS | _LISTING_MAP_TRACK_ACTIONS
_PRODUCT_TRACK_SOURCE_SURFACES = {
    "preview",
    "preview_switch",
    "product_offer",
    "bottom_dashboard",
}


def _safe_product_tracking_context(context) -> dict:
    if not isinstance(context, dict):
        return {}
    safe = {}
    edition = context.get("edition")
    if edition in {"legacy", "current"}:
        safe["edition"] = edition
    source_surface = context.get("source_surface")
    if source_surface in _PRODUCT_TRACK_SOURCE_SURFACES:
        safe["source_surface"] = source_surface
    identity_fields = ("path", "page_slug", "product_slug")
    supplied_identity = {
        key: context.get(key)
        for key in identity_fields
        if key in context
    }
    if supplied_identity:
        matching_identity = next(
            (
                identity
                for identity in _CITY_MAP_TRACK_IDENTITIES
                if all(
                    supplied_identity[key] == identity[key]
                    for key in supplied_identity
                )
            ),
            None,
        )
        if matching_identity is not None:
            safe.update(supplied_identity)
    page_title = context.get("page_title")
    if isinstance(page_title, str) and page_title.strip():
        safe["page_title"] = page_title.strip()[:160]
    return safe


def _safe_checkout_tracking_context(context) -> dict:
    if not isinstance(context, dict):
        return {}
    safe = {}
    product_slugs = {
        page["product_slug"] for page in CITY_MAP_PRODUCTS.values()
    }
    if context.get("product_slug") in product_slugs:
        safe["product_slug"] = context["product_slug"]
    if context.get("product_version") == "1.0":
        safe["product_version"] = "1.0"
    if type(context.get("amount_vnd")) is int and context["amount_vnd"] == 99_000:
        safe["amount_vnd"] = 99_000
    if context.get("order_status") in {
        "pending",
        "paid",
        "expired",
        "cancelled",
        "payment_review",
    }:
        safe["order_status"] = context["order_status"]
    return safe


def _safe_public_content_tracking_context(action: str, context) -> dict:
    if not isinstance(context, dict):
        return {}
    safe = {}
    integer_fields = {
        "query_length": 500,
        "result_count": 10000,
    }
    for key, maximum in integer_fields.items():
        value = context.get(key)
        if type(value) in {int, float}:
            safe[key] = min(max(int(value), 0), maximum)
    text_limits = {
        "facet": 80,
        "path": 180,
        "page_slug": 180,
        "page_title": 160,
        "kind": 40,
        "slug": 180,
        "target": 500,
        "source_surface": 40,
        "group": 40,
    }
    for key, limit in text_limits.items():
        value = context.get(key)
        if isinstance(value, str) and value.strip():
            safe[key] = value.strip()[:limit]
    return safe


def _safe_listing_map_tracking_context(context) -> dict:
    if not isinstance(context, dict):
        return {}
    safe = {}
    if context.get("mode") in {"signals", "all"}:
        safe["mode"] = context["mode"]
    if context.get("precision") in {"exact", "road", "ward"}:
        safe["precision"] = context["precision"]
    for key in (
        "listing_count",
        "mapped_count",
        "unmapped_count",
        "group_count",
    ):
        if key not in context:
            continue
        value = context.get(key)
        if (
            type(value) in {int, float}
            and math.isfinite(value)
            and value >= 0
        ):
            safe[key] = min(int(value + 0.5), 1_000_000)
        else:
            safe[key] = 0
    layer_ids = context.get("layer_ids")
    if isinstance(layer_ids, list):
        safe["layer_ids"] = [
            value
            for value in (str(item) for item in layer_ids)
            if re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", value)
        ][:12]
    if context.get("base_layer_id") in {"street", "satellite"}:
        safe["base_layer_id"] = context["base_layer_id"]
    close_reason = context.get("close_reason")
    if (
        isinstance(close_reason, str)
        and re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", close_reason)
    ):
        safe["close_reason"] = close_reason
    return safe


def _safe_listing_share_tracking_context(context) -> dict:
    if not isinstance(context, dict):
        return {}
    safe = {}
    if context.get("surface") in {"modal", "detail"}:
        safe["surface"] = context["surface"]
    if context.get("method") in {"copy", "facebook"}:
        safe["method"] = context["method"]
    return safe


@rate_limit("track", limits={"guest": 120, "free": 600, "vip": None, "admin": None})
def api_track():
    payload = request.get_json(silent=True) or {}
    action = (payload.get("action") or "").strip()[:60]
    if action not in ALLOWED_TRACK_ACTIONS:
        return jsonify({"ok": False, "error": "invalid_action"}), 400
    is_product_action = action in _PRODUCT_TRACK_ACTIONS
    is_checkout_action = action in _CHECKOUT_TRACK_ACTIONS
    is_listing_map_action = action in _LISTING_MAP_TRACK_ACTIONS
    listing_id = (
        None
        if is_product_action or is_checkout_action or is_listing_map_action
        else payload.get("listing_id")
    )
    try:
        listing_id = int(listing_id) if listing_id not in (None, "") else None
    except (TypeError, ValueError):
        listing_id = None
    ctx = payload.get("context") or {}
    if is_checkout_action:
        ctx = _safe_checkout_tracking_context(ctx)
    elif is_product_action:
        ctx = _safe_product_tracking_context(ctx)
    elif is_listing_map_action:
        ctx = _safe_listing_map_tracking_context(ctx)
    elif action == "listing_share":
        ctx = _safe_listing_share_tracking_context(ctx)
    elif action.startswith("public_"):
        ctx = _safe_public_content_tracking_context(action, ctx)
    elif not isinstance(ctx, dict):
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
_TPHCM_LAND_PRICE_DATA = Path(__file__).parent / "static" / "data" / "tphcm_land_prices_2026.json"
_TPHCM_LAND_PRICE_CACHE = {"mtime": None, "payload": None}

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
        "base_url": PUBLIC_BASE_URL.rstrip("/"),
    }


def _load_tphcm_land_price_data() -> dict:
    mtime = _TPHCM_LAND_PRICE_DATA.stat().st_mtime
    if _TPHCM_LAND_PRICE_CACHE["mtime"] != mtime:
        _TPHCM_LAND_PRICE_CACHE["payload"] = json.loads(_TPHCM_LAND_PRICE_DATA.read_text(encoding="utf-8"))
        _TPHCM_LAND_PRICE_CACHE["mtime"] = mtime
    return _TPHCM_LAND_PRICE_CACHE["payload"]


def _page_breadcrumb_label(page: dict) -> str:
    label = (page.get("breadcrumb_label") or "").strip()
    if label:
        return label

    path = str(page.get("path") or "").strip()
    if path == "/binh-duong":
        return "Nhà đất Bình Dương"
    if path == "/ban-dat-binh-duong":
        return "Bán đất Bình Dương"
    if path == "/san-deal-bds":
        return "Săn deal BĐS"
    if path.startswith("/kien-thuc/"):
        return "Kiến thức BĐS Bình Dương"
    if path.startswith("/bao-cao/"):
        period = ((page.get("report") or {}).get("period") or "").strip()
        return f"Báo cáo {period}" if period else "Báo cáo thị trường"
    if path.startswith("/binh-duong/"):
        map_label = str(page.get("map_label") or "").strip()
        if " / " in map_label:
            return map_label.split(" / ", 1)[-1].strip()

    for key in ("hero_title", "title"):
        value = str(page.get(key) or "").strip()
        if value:
            return value
    return "Radar BDS"


def _page_breadcrumbs(page: dict) -> list[dict]:
    path = "/" + str(page.get("path") or "/").lstrip("/")
    breadcrumbs = [{"name": "Trang chủ", "href": "/"}]

    if path.startswith("/binh-duong/"):
        breadcrumbs.append({"name": "Nhà đất Bình Dương", "href": "/binh-duong"})
    elif path.startswith("/quy-hoach-binh-duong/"):
        breadcrumbs.append({"name": "Bản đồ quy hoạch Bình Dương", "href": "/quy-hoach-binh-duong"})
    elif path.startswith("/kien-thuc/"):
        breadcrumbs.append({"name": "Kiến thức", "href": "/kien-thuc"})
    elif path.startswith("/bao-cao/"):
        breadcrumbs.append({"name": "Báo cáo", "href": "/bao-cao"})

    if path.startswith("/tin-tuc/"):
        breadcrumbs = [
            {"name": "Trang chủ", "href": "/"},
            {"name": "Tin tức", "href": "/tin-tuc"},
        ]
        if path != "/tin-tuc/du-lieu-radarbds":
            breadcrumbs.append(
                {
                    "name": "Tin từ dữ liệu Radar BDS",
                    "href": "/tin-tuc/du-lieu-radarbds",
                }
            )

    current = {"name": _page_breadcrumb_label(page), "href": path}
    if breadcrumbs[-1]["href"] != current["href"]:
        breadcrumbs.append(current)
    else:
        breadcrumbs[-1] = current
    for crumb in breadcrumbs:
        crumb["url"] = _public_url(crumb["href"])
    return breadcrumbs


def serve_local_image(filename):
    is_thumb = str(filename or "").replace("\\", "/").startswith("thumbs/")
    max_age = 30 * 86400 if is_thumb else 7 * 86400
    response = make_response(send_from_directory(_DATA_IMAGES_DIR, filename, max_age=max_age))
    if is_thumb:
        response.headers["Cache-Control"] = "public, max-age=2592000, immutable"
    return response


def index():
    response = make_response(
        render_template(
            'index.html',
            wards_by_city=CITY_MAP,
            site_meta=_site_meta("/"),
            saved_page=False,
        )
    )
    is_anonymous = (
        not request.cookies.get(SESSION_COOKIE_NAME)
        and not request.headers.get("Authorization")
        and "Set-Cookie" not in response.headers
    )
    if is_anonymous:
        response.headers["X-Radar-Public-Cache"] = "1"
        response.headers["Cache-Control"] = _PUBLIC_CACHE_CONTROL
        response.headers["Vary"] = "Cookie"
    else:
        response.headers["Cache-Control"] = "private, no-store"
    return response


def saved_listings_page():
    return render_template(
        'index.html',
        wards_by_city=CITY_MAP,
        saved_page=True,
        site_meta=_site_meta(
            "/bds-da-luu",
            title="BĐS đã lưu | Radar BDS",
            description="Danh sách các lô đất đã lưu trong tài khoản Radar BDS.",
            keywords="BĐS đã lưu, lô đất đã lưu, Radar BDS",
        ),
    )


def valuation_tool_page():
    return render_template(
        "valuation_tool.html",
        wards_by_city=VALUATION_TOOL_CITY_MAP,
        required_tier=VALUATION_TOOL_MIN_TIER,
        active_nav="dinh-gia",
        site_meta=_site_meta(
            "/dinh-gia-bds",
            title="Định giá đất Bình Dương online | Radar BDS",
            description="Công cụ định giá lô đất Bình Dương cho Thủ Dầu Một và Bến Cát, dựa trên dữ liệu tin rao đã chuẩn hóa và mô hình định giá Radar BDS.",
            keywords="định giá đất Bình Dương, định giá bất động sản, giá đất Thủ Dầu Một, giá đất Bến Cát",
        ),
    )


def tphcm_land_price_tool_page():
    data = _load_tphcm_land_price_data()
    areas = sorted({r.get("area", "") for r in data.get("rows", []) if r.get("area")})
    return render_template(
        "tphcm_land_price_tool.html",
        active_nav="bang-gia-dat",
        areas=areas,
        row_count=len(data.get("rows", [])),
        land_price_source=data.get("source"),
        land_price_source_url=data.get("source_url"),
        land_price_data_as_of=data.get("data_as_of"),
        land_price_document_sha256=data.get("document_sha256"),
        site_meta=_site_meta(
            "/bang-gia-dat-tphcm",
            title="Tra cứu bảng giá đất TP.HCM mới 2026 | Radar BDS",
            description="Công cụ tra cứu bảng giá đất TP.HCM mới theo Nghị quyết 87/2025/NQ-HĐND, áp dụng từ ngày 01/01/2026.",
            keywords="bảng giá đất TP.HCM 2026, bảng giá đất TPHCM mới, tra cứu giá đất TP.HCM, Nghị quyết 87/2025/NQ-HĐND",
        ),
    )


def api_tphcm_land_prices():
    data = _load_tphcm_land_price_data()
    rows = data.get("rows", [])
    q = request.args.get("q", "").strip()
    area = request.args.get("area", "").strip()
    if not q and not area:
        return jsonify({"ok": False, "error": "search_required"}), 400

    try:
        limit = max(1, min(int(request.args.get("limit", 50) or 50), 100))
    except ValueError:
        limit = 50
    try:
        page = max(1, min(int(request.args.get("page", 1) or 1), 500))
    except ValueError:
        page = 1

    result = search_land_prices(
        rows,
        query=q,
        area=area,
        page=page,
        limit=limit,
    )

    return jsonify({
        "ok": True,
        **result,
        "source": data.get("source"),
        "source_url": data.get("source_url"),
        "data_as_of": data.get("data_as_of"),
        "document_sha256": data.get("document_sha256"),
        "unit": data.get("unit"),
    })


def _land_price_json_ready(value):
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {
            key: _land_price_json_ready(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_land_price_json_ready(item) for item in value]
    return value


def api_tphcm_land_price_calculate():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({
            "ok": False,
            "error": "validation_error",
            "field_errors": {
                "request": "Dữ liệu gửi lên phải là một JSON object.",
            },
        }), 400
    location = payload.get("location")
    if not isinstance(location, dict):
        return jsonify({
            "ok": False,
            "error": "validation_error",
            "field_errors": {
                "location": "Thông tin vị trí phải là một JSON object.",
            },
        }), 400
    parcel_mode = str(payload.get("parcel_mode") or "single")
    if parcel_mode not in {"single", "mixed"}:
        return jsonify({
            "ok": False,
            "error": "validation_error",
            "field_errors": {
                "parcel_mode": "Loại thửa đất không hợp lệ.",
            },
        }), 400

    residential_geometry = payload.get("residential_geometry")
    agricultural = payload.get("agricultural")
    if parcel_mode == "mixed":
        nested_errors = {}
        if not isinstance(residential_geometry, dict):
            nested_errors["residential_geometry"] = (
                "Hình thể phần đất ở phải là một JSON object."
            )
        if not isinstance(agricultural, dict):
            nested_errors["agricultural"] = (
                "Thông tin đất nông nghiệp phải là một JSON object."
            )
        if nested_errors:
            return jsonify({
                "ok": False,
                "error": "validation_error",
                "field_errors": nested_errors,
            }), 400

        boolean_fields = (
            (residential_geometry, "use_custom", "residential_geometry.use_custom"),
            (agricultural, "in_residential_area", "agricultural.in_residential_area"),
            (
                agricultural,
                "same_parcel_has_house",
                "agricultural.same_parcel_has_house",
            ),
        )
        invalid_booleans = {
            error_field: "Giá trị xác nhận phải là true hoặc false."
            for source, source_field, error_field in boolean_fields
            if source_field in source
            and not isinstance(source.get(source_field), bool)
        }
        if invalid_booleans:
            return jsonify({
                "ok": False,
                "error": "validation_error",
                "field_errors": invalid_booleans,
            }), 400

    data = _load_tphcm_land_price_data()
    row = find_land_price_row(
        data.get("rows", []),
        str(payload.get("row_key") or ""),
    )
    if row is None:
        return jsonify({"ok": False, "error": "row_not_found"}), 404

    try:
        base_prices = {
            "residential": row.get("residential"),
            "commerce_service": row.get("commerce_service"),
            "production_business": row.get("production_business"),
        }
        if parcel_mode == "mixed":
            result = calculate_mixed_land_price(
                base_prices,
                area_name=row.get("area"),
                land_area_m2=payload.get("land_area_m2"),
                frontage_m=payload.get("frontage_m"),
                depth_m=payload.get("depth_m"),
                residential_area_m2=payload.get("residential_area_m2"),
                agricultural_area_m2=payload.get("agricultural_area_m2"),
                residential_geometry=residential_geometry,
                location=location,
                agricultural=agricultural,
            )
        else:
            result = calculate_land_price(
                base_prices,
                land_area_m2=payload.get("land_area_m2"),
                frontage_m=payload.get("frontage_m"),
                depth_m=payload.get("depth_m"),
                location=location,
            )
    except CalculationValidationError as exc:
        return jsonify({
            "ok": False,
            "error": "validation_error",
            "field_errors": exc.field_errors,
        }), 400

    response = {
        "ok": True,
        "row": {
            "row_key": land_price_row_key(row),
            "area": row.get("area"),
            "street": row.get("street"),
            "from": row.get("from"),
            "to": row.get("to"),
        },
        **result,
        "source_url": data.get("source_url"),
        "data_as_of": data.get("data_as_of"),
    }
    return jsonify(_land_price_json_ready(response))


def dashboard():
    return redirect("/", code=301)


def seo_binh_duong_landing():
    page = dict(SEO_PAGES["binh-duong"])
    return _render_public_page(page)


def _breadcrumb_schema(breadcrumbs: list[dict]) -> dict:
    return {
        "@type": "BreadcrumbList",
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": index,
                "name": crumb["name"],
                "item": crumb["url"],
            }
            for index, crumb in enumerate(breadcrumbs, start=1)
        ],
    }


def city_map_product_schema(
    page: dict,
    product,
    availability,
    legacy_areas: list[dict],
    current_areas: list[dict],
) -> dict:
    canonical_url = _public_url(page["path"])
    preview_url = _public_url(page["preview_after"])
    legacy_geojson_url = _public_url(
        page.get("legacy_data_url", page["legacy_geojson_url"])
    )
    current_geojson_url = _public_url(
        page.get("current_data_url", page["current_geojson_url"])
    )

    def area_item_list(name: str, layer: str, areas: list[dict]) -> dict:
        return {
            "@type": "ItemList",
            "@id": f"{canonical_url}#itemlist-{layer}",
            "name": name,
            "itemListOrder": "https://schema.org/ItemListOrderAscending",
            "numberOfItems": len(areas),
            "itemListElement": [
                {
                    "@type": "ListItem",
                    "position": index,
                    "name": area["name"],
                    "url": f"{canonical_url}#layer-{layer}/area-{area['slug']}",
                    "item": {
                        "@type": "Place",
                        "name": area["name"],
                        "additionalType": area.get("unit_type", "Phường"),
                        "description": area.get("summary", ""),
                    },
                }
                for index, area in enumerate(areas, start=1)
            ],
        }

    return {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "WebPage",
                "@id": f"{canonical_url}#webpage",
                "url": canonical_url,
                "name": page["hero_title"],
                "description": page["description"],
                "inLanguage": "vi-VN",
                "dateModified": page["updated_at"],
                "isPartOf": {"@type": "WebSite", "name": SITE_NAME, "url": PUBLIC_BASE_URL},
                "mainEntity": {
                    "@type": "Map",
                    "@id": f"{canonical_url}#interactive-map",
                    "name": f"Bản đồ TP {page['city_name']} tương tác",
                    "description": page["answer_block"],
                },
            },
            {
                "@type": "Product",
                "@id": f"{canonical_url}#product",
                "name": f"Bộ bản đồ TP {page['city_name']}",
                "description": page["description"],
                "image": [preview_url],
                "sku": f"{product.slug}-v{product.version}",
                "brand": {"@type": "Brand", "name": "Radar BDS"},
                "url": canonical_url,
                "offers": {
                    "@type": "Offer",
                    "url": canonical_url,
                    "price": str(product.price_vnd),
                    "priceCurrency": "VND",
                    "availability": (
                        "https://schema.org/InStock"
                        if availability.can_sell
                        else "https://schema.org/OutOfStock"
                    ),
                },
            },
            {
                "@type": "Dataset",
                "@id": (
                    f"{canonical_url}#dataset-legacy-"
                    f"{len(legacy_areas)}-{page['dataset_id_suffix']}"
                ),
                "name": (
                    f"GeoJSON {len(legacy_areas)} {page['legacy_unit_label']} của "
                    f"TP {page['city_name']}"
                ),
                "description": (
                    f"Lớp ranh {len(legacy_areas)} {page['legacy_unit_label']} của "
                    f"TP {page['city_name']} trước năm 2025, dùng để tra cứu "
                    "tham khảo trên Radar BDS."
                ),
                "dateModified": page["updated_at"],
                "spatialCoverage": {
                    "@type": "Place",
                    "name": f"TP {page['city_name']}",
                },
                "license": f"{canonical_url}#license",
                "isBasedOn": [
                    "Stanford Geospatial Center / GADM v2.8 snapshot",
                    *(
                        ["Radar BDS derived boundary review"]
                        if page["derived_legacy_units"]
                        else []
                    ),
                ],
                "distribution": [
                    {
                        "@type": "DataDownload",
                        "encodingFormat": "application/geo+json",
                        "contentUrl": legacy_geojson_url,
                    }
                ],
            },
            {
                "@type": "Dataset",
                "@id": (
                    f"{canonical_url}#dataset-current-"
                    f"{len(current_areas)}-{page['dataset_id_suffix']}"
                ),
                "name": (
                    f"GeoJSON {len(current_areas)} phường hiện tại của "
                    f"TP {page['city_name']}"
                ),
                "description": (
                    f"Lớp ranh {len(current_areas)} phường hiện tại của "
                    f"TP {page['city_name']} sau sắp xếp năm 2025, dùng để "
                    "tra cứu tham khảo trên Radar BDS."
                ),
                "dateModified": page["updated_at"],
                "spatialCoverage": {
                    "@type": "Place",
                    "name": f"TP {page['city_name']}",
                },
                "license": f"{canonical_url}#license",
                "isBasedOn": [
                    "OpenStreetMap contributors",
                    "Radar BDS geometry review",
                ],
                "distribution": [
                    {
                        "@type": "DataDownload",
                        "encodingFormat": "application/geo+json",
                        "contentUrl": current_geojson_url,
                    }
                ],
            },
            area_item_list(
                (
                    f"{len(legacy_areas)} {page['legacy_unit_label']} của "
                    f"TP {page['city_name']}"
                ),
                "legacy",
                legacy_areas,
            ),
            area_item_list(
                (
                    f"{len(current_areas)} phường hiện tại của "
                    f"TP {page['city_name']}"
                ),
                "current",
                current_areas,
            ),
            _breadcrumb_schema(page["breadcrumbs"]),
            {
                "@type": "FAQPage",
                "mainEntity": [
                    {
                        "@type": "Question",
                        "name": item["question"],
                        "acceptedAnswer": {
                            "@type": "Answer",
                            "text": item["answer"],
                        },
                    }
                    for item in page["faq"]
                ],
            },
        ],
    }


def _planning_hub_schema(page: dict, pages: list[dict]) -> dict:
    return {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "CollectionPage",
                "name": page["hero_title"],
                "description": page["description"],
                "url": _public_url(page["path"]),
                "isPartOf": {
                    "@type": "WebSite",
                    "name": "Radar BDS",
                    "url": _public_url("/"),
                },
            },
            {
                "@type": "ItemList",
                "name": "Danh sách bản đồ quy hoạch Bình Dương cũ",
                "itemListElement": [
                    {
                        "@type": "ListItem",
                        "position": index,
                        "name": item["hero_title"],
                        "url": _public_url(item["path"]),
                    }
                    for index, item in enumerate(pages, start=1)
                ],
            },
            _breadcrumb_schema(page["breadcrumbs"]),
        ],
    }


def _planning_category_for_page(page: dict) -> dict:
    category_key = str(page.get("category") or "").strip()
    category_label = PLANNING_CATEGORY_LABELS.get(category_key)
    if not category_label:
        slug = str(page.get("slug") or page.get("path") or "unknown")
        raise ValueError(f"Unknown planning category '{category_key}' for {slug}")
    return {"key": category_key, "label": category_label}


def _planning_detail_schema(page: dict) -> dict:
    source_urls = [source["href"] for source in page.get("source_links", []) if source.get("href")]
    return {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "Article",
                "headline": page["hero_title"],
                "description": page["description"],
                "url": _public_url(page["path"]),
                "datePublished": page["updated_at"],
                "dateModified": page["updated_at"],
                "author": {
                    "@type": "Organization",
                    "name": "Radar BDS",
                    "url": _public_url("/"),
                },
                "publisher": {
                    "@type": "Organization",
                    "name": "Radar BDS",
                    "url": _public_url("/"),
                },
                "mainEntityOfPage": _public_url(page["path"]),
            },
            _breadcrumb_schema(page["breadcrumbs"]),
            {
                "@type": "FAQPage",
                "mainEntity": [
                    {
                        "@type": "Question",
                        "name": item["question"],
                        "acceptedAnswer": {
                            "@type": "Answer",
                            "text": item["answer"],
                        },
                    }
                    for item in page.get("faq", [])
                ],
            },
            {
                "@type": "Dataset",
                "name": page["map_label"],
                "description": page["description"],
                "url": _public_url(page["path"]),
                "dateModified": page["updated_at"],
                "creator": {
                    "@type": "Organization",
                    "name": "Radar BDS",
                    "url": _public_url("/"),
                },
                "spatialCoverage": {
                    "@type": "Place",
                    "name": "Bình Dương cũ",
                },
                "isBasedOn": source_urls,
                "distribution": [
                    {
                        "@type": "DataDownload",
                        "encodingFormat": "application/geo+json",
                        "contentUrl": _public_url(page["geojson_path"]),
                    }
                ],
            },
        ],
    }


def _binh_duong_map_schema(
    page: dict,
    legacy_areas: list[dict],
    current_areas: list[dict],
) -> dict:
    source_urls = [
        source["href"]
        for source in page.get("source_links", [])
        if source.get("href")
    ]
    canonical_url = _public_url(page["path"])
    legacy_dataset_id = f"{canonical_url}#dataset-legacy"
    current_dataset_id = f"{canonical_url}#dataset-current"
    return {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "WebPage",
                "@id": canonical_url,
                "name": page["hero_title"],
                "description": page["description"],
                "url": canonical_url,
                "dateModified": page["updated_at"],
                "mainEntity": [
                    {"@id": legacy_dataset_id},
                    {"@id": current_dataset_id},
                ],
                "isPartOf": {
                    "@type": "WebSite",
                    "name": "Radar BDS",
                    "url": _public_url("/"),
                },
            },
            {
                "@type": "Dataset",
                "@id": legacy_dataset_id,
                "name": "Bản đồ 9 đơn vị cấp huyện Bình Dương cũ",
                "description": (
                    "Ranh tham khảo của 9 thành phố, huyện thuộc tỉnh Bình Dương "
                    "trước sắp xếp hành chính."
                ),
                "spatialCoverage": {"@type": "Place", "name": "Bình Dương cũ"},
                "dateModified": page["updated_at"],
                "isBasedOn": source_urls,
                "distribution": [
                    {
                        "@type": "DataDownload",
                        "encodingFormat": "application/geo+json",
                        "contentUrl": _public_url(page["legacy_geojson_url"]),
                    }
                ],
            },
            {
                "@type": "Dataset",
                "@id": current_dataset_id,
                "name": "Bản đồ 36 phường xã khu vực Bình Dương cũ",
                "description": (
                    "Ranh tham khảo của 36 phường, xã thuộc khu vực Bình Dương cũ "
                    "sau sắp xếp năm 2025."
                ),
                "spatialCoverage": {"@type": "Place", "name": "Bình Dương cũ"},
                "dateModified": page["updated_at"],
                "isBasedOn": source_urls,
                "distribution": [
                    {
                        "@type": "DataDownload",
                        "encodingFormat": "application/geo+json",
                        "contentUrl": _public_url(page["current_geojson_url"]),
                    }
                ],
            },
            {
                "@type": "ItemList",
                "name": "9 đơn vị cấp huyện của Bình Dương cũ",
                "numberOfItems": len(legacy_areas),
                "itemListElement": [
                    {
                        "@type": "ListItem",
                        "position": index,
                        "name": area["name"],
                        "url": (
                            f"{canonical_url}#layer-legacy/area-{area['slug']}"
                        ),
                    }
                    for index, area in enumerate(legacy_areas, start=1)
                ],
            },
            _breadcrumb_schema(page["breadcrumbs"]),
            {
                "@type": "FAQPage",
                "mainEntity": [
                    {
                        "@type": "Question",
                        "name": item["question"],
                        "acceptedAnswer": {
                            "@type": "Answer",
                            "text": item["answer"],
                        },
                    }
                    for item in page.get("faq", [])
                ],
            },
        ],
    }


def planning_hub_page():
    page = dict(PLANNING_HUB)
    pages = []
    category_counts = {}
    for raw_item in PLANNING_PAGE_LIST:
        item = dict(raw_item)
        category = _planning_category_for_page(item)
        item["category"] = category["key"]
        item["category_label"] = category["label"]
        category_counts[category["key"]] = category_counts.get(category["key"], 0) + 1
        pages.append(item)
    available_tabs = []
    for raw_tab in page.get("tabs", []):
        tab = dict(raw_tab)
        tab_id = tab.get("id")
        count = len(pages) if tab_id == "all" else category_counts.get(tab_id, 0)
        if count:
            tab["count"] = count
            available_tabs.append(tab)
    page["tabs"] = available_tabs
    page["total_pages"] = len(pages)
    page["active_category_count"] = len(category_counts)
    page["latest_updated_label"] = max(
        pages,
        key=lambda item: (item.get("updated_at") or "", item.get("slug") or ""),
    ).get("updated_label") if pages else page.get("updated_label")
    trending_pages = [
        dict(PLANNING_PAGES[slug])
        for slug in page.get("trending_slugs", [])
        if slug in PLANNING_PAGES
    ]
    page["breadcrumbs"] = _page_breadcrumbs(page)
    page["local_links"] = page.get("local_links", [])[:3]
    site_meta = _site_meta(
        page["path"],
        title=page["title"],
        description=page["description"],
        keywords=page["keywords"],
    )
    site_meta["og_image"] = _public_url("/static/images/seo/radarbds-og.png")
    return render_template(
        "planning_hub.html",
        page=page,
        pages=pages,
        trending_pages=trending_pages,
        site_meta=site_meta,
        schema_graph=_planning_hub_schema(page, pages),
        active_nav="quy-hoach",
        dashboard_signal_href="/?tab=signals",
    )


def binh_duong_map_page():
    page = deepcopy(BINH_DUONG_MAP_PAGE)
    page["breadcrumbs"] = _page_breadcrumbs(page)
    page["local_links"] = page.get("related_links", [])[:3]

    current_groups = []
    groups_by_name = {}
    for area in BINH_DUONG_CURRENT_AREAS:
        group_name = area["group"]
        if group_name not in groups_by_name:
            group = {"name": group_name, "areas": []}
            groups_by_name[group_name] = group
            current_groups.append(group)
        groups_by_name[group_name]["areas"].append(dict(area))

    site_meta = _site_meta(
        page["path"],
        title=page["title"],
        description=page["description"],
        keywords=page["keywords"],
    )
    site_meta["og_image"] = _public_url("/static/images/seo/radarbds-og.png")
    return render_template(
        "binh_duong_map.html",
        page=page,
        legacy_areas=[dict(area) for area in BINH_DUONG_LEGACY_AREAS],
        current_areas=[dict(area) for area in BINH_DUONG_CURRENT_AREAS],
        current_groups=current_groups,
        site_meta=site_meta,
        schema_graph=_binh_duong_map_schema(
            page,
            BINH_DUONG_LEGACY_AREAS,
            BINH_DUONG_CURRENT_AREAS,
        ),
        active_nav="ban-do-binh-duong",
        dashboard_signal_href="/?tab=signals",
    )


def _map_areas_from_static_geojson(static_url: str) -> list[dict]:
    static_path = Path(__file__).parent / static_url.lstrip("/")
    payload = json.loads(static_path.read_text(encoding="utf-8"))
    areas = []
    for feature in payload.get("features", []):
        properties = feature.get("properties") or {}
        if not properties.get("slug") or not properties.get("name"):
            continue
        areas.append(
            {
                "slug": properties["slug"],
                "name": properties["name"],
                "unit_type": properties.get("unit_type", "Phường"),
                "summary": properties.get("summary", ""),
                "group": properties.get("group", ""),
                "former_units": properties.get("former_units", ""),
                "is_derived_boundary": bool(
                    properties.get("is_derived_boundary")
                    or properties.get("boundary_source") == "derived_boundary"
                ),
                "boundary_confidence": properties.get("boundary_confidence", ""),
                "current_ward_after_2025": properties.get(
                    "current_ward_after_2025",
                    "",
                ),
                "dashboard_href": properties.get(
                    "dashboard_href",
                    "/?tab=signals&city=Th%E1%BB%A7%20D%E1%BA%A7u%20M%E1%BB%99t",
                ),
                "dashboard_label": properties.get(
                    "dashboard_label",
                    "Lọc tin Thủ Dầu Một",
                ),
            }
        )
    return areas


def city_map_geojson(city_slug: str, edition: str):
    try:
        page = get_city_map_page(city_slug)
    except KeyError:
        abort(404)
    source_url = {
        "truoc-sap-nhap": page["legacy_geojson_url"],
        "sau-sap-nhap": page["current_geojson_url"],
    }.get(edition)
    if source_url is None:
        abort(404)
    relative_path = Path(source_url.lstrip("/"))
    expected_parent = Path("static") / "maps" / page["city_slug"]
    if relative_path.parent != expected_parent:
        abort(404)
    static_dir = Path(__file__).parent / expected_parent
    response = make_response(
        send_from_directory(
            static_dir,
            relative_path.name,
            mimetype="application/geo+json",
            max_age=86400,
        )
    )
    response.headers["Content-Type"] = "application/geo+json; charset=utf-8"
    response.headers["Cache-Control"] = "public, max-age=86400"
    return response


def thu_dau_mot_map_geojson(edition: str):
    return city_map_geojson("thu-dau-mot", edition)


def city_map_product_page(city_slug: str):
    try:
        page = get_city_map_page(city_slug)
    except KeyError:
        abort(404)
    page["breadcrumbs"] = _page_breadcrumbs(page)
    page["local_links"] = [dict(link) for link in page["local_links"]]
    legacy_areas = _map_areas_from_static_geojson(page["legacy_geojson_url"])
    current_areas = _map_areas_from_static_geojson(page["current_geojson_url"])
    product = get_digital_product(page["product_slug"])
    commerce_settings = get_digital_product_commerce_settings()
    if (
        commerce_settings.ready_for_checkout
        and commerce_settings.storage_dir is not None
    ):
        availability = get_release_availability(
            product,
            commerce_settings.storage_dir,
            commerce_settings.sales_enabled,
        )
    else:
        availability = ProductAvailability(
            package_valid=False,
            sales_enabled=commerce_settings.sales_enabled,
            can_sell=False,
            reason="configuration_not_ready",
        )
    site_meta = _site_meta(
        page["path"],
        title=page["title"],
        description=page["description"],
        keywords=page["keywords"],
    )
    site_meta["og_image"] = _public_url(page["preview_after"])
    return render_template(
        "thu_dau_mot_map_product.html",
        page=page,
        product=product,
        availability=availability,
        legacy_areas=legacy_areas,
        current_areas=current_areas,
        display_price=f"{product.price_vnd:,}".replace(",", "."),
        site_meta=site_meta,
        schema_graph=city_map_product_schema(
            page,
            product,
            availability,
            legacy_areas,
            current_areas,
        ),
        active_nav="ban-do-binh-duong",
        dashboard_signal_href=page["dashboard_signal_href"],
    )


def thu_dau_mot_map_product_page():
    return city_map_product_page("thu-dau-mot")


def planning_detail_page(slug: str):
    category_page = PLANNING_CATEGORY_PAGES.get((slug or "").strip("/"))
    if category_page:
        page = dict(category_page)
        page["breadcrumbs"] = _page_breadcrumbs(page)
        items = [
            deepcopy(item)
            for item in PLANNING_PAGE_LIST
            if item.get("category") in page["categories"]
        ]
        item_list = [
            {
                "@type": "ListItem",
                "position": index,
                "name": item["hero_title"],
                "url": _public_url(item["path"]),
            }
            for index, item in enumerate(items, start=1)
        ]
        schema_graph = {
            "@context": "https://schema.org",
            "@graph": [
                {
                    "@type": "CollectionPage",
                    "name": page["heading"],
                    "url": _public_url(page["path"]),
                    "description": page["description"],
                },
                {"@type": "ItemList", "itemListElement": item_list},
                _breadcrumb_schema(page["breadcrumbs"]),
            ],
        }
        return render_template(
            "planning_category.html",
            page=page,
            items=items,
            site_meta=_site_meta(
                page["path"],
                title=page["title"],
                description=page["description"],
                keywords=f"{page['heading']}, quy hoạch Bình Dương",
            ),
            schema_graph=schema_graph,
            active_nav="quy-hoach",
        )

    page = PLANNING_PAGES.get((slug or "").strip("/"))
    if not page:
        abort(404)
    page = deepcopy(page)
    page["breadcrumbs"] = _page_breadcrumbs(page)
    page["local_links"] = page.get("related_links", [])[:3]
    site_meta = _site_meta(
        page["path"],
        title=page["title"],
        description=page["description"],
        keywords=page["keywords"],
    )
    site_meta["og_image"] = _public_url("/static/images/seo/radarbds-og.png")
    return render_template(
        "planning_detail.html",
        page=page,
        site_meta=site_meta,
        schema_graph=_planning_detail_schema(page),
        active_nav="quy-hoach",
        dashboard_signal_href=page.get("dashboard_href") or "/?tab=signals",
    )


def _active_public_nav(path: str) -> str:
    if path == "/bang-gia-dat-tphcm":
        return "bang-gia-dat"
    if path == "/dinh-gia-bds":
        return "dinh-gia"
    if path == "/ban-do-binh-duong":
        return "ban-do-binh-duong"
    if path.startswith("/quy-hoach-binh-duong"):
        return "quy-hoach"
    if path == "/ban-dat-binh-duong":
        return "ban-dat"
    if path.startswith("/bao-cao"):
        return "bao-cao"
    if path.startswith("/tin-tuc"):
        return "tin-tuc"
    if path.startswith("/kien-thuc"):
        return "kien-thuc"
    if path == "/san-deal-bds":
        return "san-deal"
    return "binh-duong"


_BANGKOK_TZ = timezone(timedelta(hours=7))
_PRIORITY_TDM_WARDS = {
    "hiep-thanh": "Hiệp Thành",
    "phu-hoa": "Phú Hòa",
    "phu-my": "Phú Mỹ",
    "dinh-hoa": "Định Hòa",
    "phu-loi": "Phú Lợi",
    "tan-an": "Tân An",
    "hiep-an": "Hiệp An",
    "chanh-nghia": "Chánh Nghĩa",
}

_REPORT_TDM_WARDS = {
    "Tân An", "Hiệp An", "Tương Bình Hiệp", "Định Hòa", "Chánh Mỹ", "Phú Mỹ", "Phú Cường",
    "Phú Hòa", "Phú Lợi", "Hiệp Thành", "Chánh Nghĩa", "Phú Tân", "Hòa Phú",
}
_REPORT_BEN_CAT_WARDS = {
    "Bến Cát", "Mỹ Phước", "Mỹ Phước 1", "Mỹ Phước 2", "Mỹ Phước 3", "Mỹ Phước 4",
    "Thới Hòa", "Tân Định", "Chánh Phú Hòa", "Phú An", "An Tây", "An Điền", "Hòa Lợi",
}


def _report_hub_city(scope_label: str, path: str = "") -> tuple[str, str]:
    scope = str(scope_label or "").strip()
    lower = f"{scope} {path}".lower()
    if scope in _REPORT_BEN_CAT_WARDS or "ben-cat" in lower or "bến cát" in lower or "my-phuoc" in lower or "mỹ phước" in lower:
        return ("ben-cat", "Bến Cát")
    return ("tdm", "Thủ Dầu Một")


def _report_hub_thumbnail(page: dict) -> str:
    """Return a report-specific hub thumbnail instead of a random listing photo."""
    path = str(page.get("path") or "")
    slug = path.rstrip("/").split("/")[-1]
    if slug:
        static_rel = f"/static/images/seo/reports/{slug}.webp"
        static_path = Path(__file__).parent / static_rel.lstrip("/")
        if static_path.exists():
            return static_rel

    report = page.get("report") or {}
    explicit = str(report.get("hub_thumbnail") or page.get("hub_thumbnail") or "").strip()
    if explicit:
        return explicit

    for item in report.get("featured_listings") or []:
        image = str(item.get("image") or "").strip()
        if image:
            return image
    return ""


def _report_safe_slug(value: str) -> str:
    normalized = unicodedata.normalize("NFD", str(value or ""))
    ascii_value = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
    return re.sub(r"[^a-z0-9]+", "-", ascii_value.lower()).strip("-")


def _report_primary_metric(page: dict) -> dict:
    metrics = (page.get("report") or {}).get("metrics") or []
    if not metrics:
        return {"label": "Báo cáo", "value": "Dữ liệu"}
    preferred = next((m for m in metrics if "tin" in str(m.get("label", "")).lower()), metrics[0])
    return {"label": preferred.get("label") or "Chỉ số", "value": preferred.get("value") or "—"}


def _decorate_report_hub_pages(reports: list[dict]) -> tuple[list[dict], dict]:
    decorated = []
    city_counts = {"tdm": 0, "ben-cat": 0}
    ward_options: dict[str, dict] = {}
    latest_by_city: dict[str, str] = {}
    periods: dict[str, str] = {}
    for index, report in enumerate(reports, start=1):
        item = dict(report)
        report_body = dict(item.get("report") or {})
        scope = str(item.get("scope_label") or "Thủ Dầu Một")
        city_key, city_label = _report_hub_city(scope, item.get("path", ""))
        city_counts[city_key] = city_counts.get(city_key, 0) + 1
        if city_key not in latest_by_city:
            latest_by_city[city_key] = item.get("path", "")
        year, month = _report_period_key(item)
        period_key = f"{year:04d}-{month:02d}" if year and month else str(report_body.get("period") or "")
        periods.setdefault(period_key, str(report_body.get("period") or period_key))
        item["hub_meta"] = {
            "index": index,
            "city_key": city_key,
            "city_label": city_label,
            "ward_key": _report_safe_slug(scope),
            "scope": scope,
            "period_key": period_key,
            "thumbnail": _report_hub_thumbnail(item),
            "primary_metric": _report_primary_metric(item),
            "search_text": " ".join([
                str(item.get("hero_title") or ""),
                str(item.get("title") or ""),
                str(item.get("description") or ""),
                scope,
                city_label,
                str(report_body.get("period") or ""),
            ]).lower(),
        }
        if scope != "Thủ Dầu Một":
            key = f"{city_key}|{scope}"
            ward_options[key] = {
                "city_key": city_key,
                "city_label": city_label,
                "key": _report_safe_slug(scope),
                "label": scope,
            }
        decorated.append(item)
    hub_filters = {
        "city_counts": city_counts,
        "latest_by_city": latest_by_city,
        "wards": sorted(ward_options.values(), key=lambda w: (w["city_label"], w["label"])),
        "periods": [
            {"key": key, "label": label}
            for key, label in sorted(periods.items(), reverse=True)
        ],
        "total": len(decorated),
    }
    return decorated, hub_filters


def _vi_decimal(value, digits: int = 1) -> str:
    try:
        return f"{float(value):.{digits}f}".replace(".", ",")
    except (TypeError, ValueError):
        return ""


def _report_period_key(page: dict) -> tuple[int, int]:
    """Return (year, month) for monthly report pages; (0, 0) if unknown."""
    report = page.get("report") or {}
    candidates = [str(report.get("period") or ""), str(page.get("path") or "")]
    for value in candidates:
        match = re.search(r"(?:Tháng|thang)[ -]?(\d{1,2})[/-](\d{4})", value, re.I)
        if match:
            return (int(match.group(2)), int(match.group(1)))
    return (0, 0)


def _report_month_end(page: dict):
    year, month = _report_period_key(page)
    if not year or not month:
        return None
    if month == 12:
        next_month = datetime(year + 1, 1, 1).date()
    else:
        next_month = datetime(year, month + 1, 1).date()
    return next_month - timedelta(days=1)


def _report_publish_date(page: dict):
    raw = str((page.get("report") or {}).get("published_at") or "")[:10]
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return None


def _is_publishable_monthly_report(page: dict) -> bool:
    """Monthly reports are public only after the month is closed and generated at/after month-end."""
    if page.get("variant") != "report":
        return True
    month_end = _report_month_end(page)
    published_at = _report_publish_date(page)
    if not month_end or not published_at:
        return False
    today = datetime.now(_BANGKOK_TZ).date()
    return today > month_end and published_at >= month_end


def _published_report_pages() -> list[dict]:
    return [
        dict(item)
        for item in SEO_PAGES.values()
        if item.get("variant") == "report" and _is_publishable_monthly_report(item)
    ]


def _report_sort_key(page: dict) -> tuple[int, int, int, str, str]:
    year, month = _report_period_key(page)
    path = page.get("path", "")
    master_rank = int(path.startswith("/bao-cao/bds-binh-duong-thang-"))
    return (year, month, master_rank, (page.get("report") or {}).get("published_at", ""), path)


def _latest_ward_report(ward_slug: str) -> dict | None:
    prefix = f"/bao-cao/{ward_slug}-thang-"
    candidates = [
        page
        for page in SEO_PAGES.values()
        if page.get("path", "").startswith(prefix)
        and page.get("report")
        and _is_publishable_monthly_report(page)
    ]
    if not candidates:
        return None
    return max(candidates, key=_report_sort_key)


def _build_live_location_snapshot(page: dict) -> dict:
    ward = page["live_ward"]
    now = datetime.now(_BANGKOK_TZ)
    snapshot = {
        "available": False,
        "ward": ward,
        "updated_iso": now.date().isoformat(),
        "updated_label": now.strftime("%d/%m/%Y"),
        "period_label": now.strftime("%m/%Y"),
        "total": 0,
        "signal_count": 0,
        "market_rows": [],
        "signals": [],
        "methodology": [
            "Nguồn dữ liệu: tin rao công khai mà Radar BDS đang theo dõi.",
            "Giá tham khảo trung bình được tính theo loại tài sản từ các mẫu không bị đánh dấu ngoại lệ.",
            "Tín hiệu chỉ là bộ lọc ưu tiên; không thay thế kiểm tra thực địa, quy hoạch và pháp lý.",
        ],
    }
    try:
        summary = get_or_load_public_payload(
            endpoint="dashboard",
            tier="guest",
            versions=_public_dataset_versions(_DASHBOARD_DATASETS),
            query={"wards": [ward], "include_trend": False},
            loader=lambda: load_dashboard_summary(
                _db_handle(),
                wards=[ward],
                tier="guest",
                include_trend=False,
            ),
        ).payload
        signal_payload = get_or_load_public_payload(
            endpoint="signals",
            tier="guest",
            versions=_public_dataset_versions(_SIGNAL_DATASETS),
            query={
                "wards": [ward],
                "page": 1,
                "limit": 5,
                "sort": "newest",
                "include_total": False,
            },
            loader=lambda: _tier_safe_signal_payload(
                load_signals(
                    _db_handle(),
                    wards=[ward],
                    tier="guest",
                    page=1,
                    limit=5,
                    sort="newest",
                    include_total=False,
                ),
                "guest",
            ),
        ).payload
        stats = summary.get("stats") or {}
        market_rows = []
        for row in summary.get("market") or []:
            average = row.get("median")
            average_label = _vi_decimal(average)
            if not average_label:
                continue
            market_rows.append(
                {
                    "label": row.get("label") or row.get("type") or "Khác",
                    "average_label": f"{average_label} tr/m²",
                    "sample_count": int(row.get("n") or 0),
                }
            )
        market_rows.sort(key=lambda row: row["sample_count"], reverse=True)

        signals = []
        for item in (signal_payload.get("signals") or [])[:5]:
            price_label = item.get("price_label")
            if not price_label and item.get("price_ty") is not None:
                price_label = f"{_vi_decimal(item.get('price_ty'))} tỷ"
            area_label = ""
            if item.get("area_m2") is not None:
                area_label = f"{_vi_decimal(item.get('area_m2'))} m²"
            ppm2_label = ""
            if item.get("actual_ppm2"):
                ppm2_label = f"{_vi_decimal(item.get('actual_ppm2'))} tr/m²"
            mos_label = ""
            if item.get("mos_pct") is not None:
                mos_label = f"MOS {_vi_decimal(item.get('mos_pct'))}%"
            signals.append(
                {
                    "id": item.get("id"),
                    "title": item.get("title") or f"Tin tại {ward}",
                    "price_label": price_label or "Liên hệ",
                    "area_label": area_label,
                    "actual_ppm2_label": ppm2_label,
                    "mos_label": mos_label,
                }
            )

        snapshot.update(
            {
                "available": True,
                "total": int(stats.get("total") or 0),
                "signal_count": int(stats.get("signals") or 0),
                "market_rows": market_rows[:5],
                "signals": signals,
            }
        )
    except Exception:
        logger.warning("Unable to render live SEO snapshot for ward %s", ward, exc_info=True)
    return snapshot


def _hydrate_live_location_page(page: dict) -> dict:
    if not page.get("live_ward"):
        return page

    snapshot = _build_live_location_snapshot(page)
    ward = page["live_ward"]
    period = snapshot["period_label"]
    title = f"Giá nhà đất {ward}, Thủ Dầu Một tháng {period}"
    page["title"] = f"{title} | Radar BDS"
    page["hero_title"] = title
    page["hero_badge"] = f"Thủ Dầu Một – Bình Dương cũ · truy vấn {snapshot['updated_label']}"
    page["map_label"] = f"Thủ Dầu Một – Bình Dương cũ / {ward}"
    page["dashboard_href"] = "/?" + urllib.parse.urlencode(
        {"tab": "signals", "ward": ward}
    )
    if snapshot["available"]:
        page["hero_text"] = (
            f"Radar BDS đang theo dõi {snapshot['total']} tin tại {ward} và ghi nhận "
            f"{snapshot['signal_count']} tín hiệu đáng kiểm tra. Trang hiển thị giá tham khảo "
            f"trung bình theo loại tài sản cùng tối đa 5 tín hiệu mới, truy vấn ngày "
            f"{snapshot['updated_label']}. Đây là dữ liệu tin rao; cần xác minh thực địa và pháp lý."
        )
        page["description"] = (
            f"Giá nhà đất {ward}, Thủ Dầu Một tháng {period}: "
            f"{snapshot['total']} tin đang theo dõi, {snapshot['signal_count']} tín hiệu, "
            "giá tham khảo, nguồn dữ liệu và ngày cập nhật."
        )
    else:
        page["hero_text"] = (
            f"Trang dữ liệu {ward}, Thủ Dầu Một – Bình Dương cũ. "
            "Dữ liệu trực tiếp tạm thời chưa khả dụng; vui lòng quay lại sau. "
            "Radar BDS chỉ tổng hợp tin rao tham khảo, không thay thế kiểm tra thực địa và pháp lý."
        )
        page["description"] = (
            f"Trang giá nhà đất {ward}, Thủ Dầu Một với nguồn, phương pháp và dữ liệu cập nhật từ Radar BDS."
        )
    report = _latest_ward_report(page["ward_slug"])
    if report:
        page["latest_report_href"] = report["path"]
        report_period = (report.get("report") or {}).get("period", period)
        page["latest_report_label"] = (
            f"Báo cáo {report_period}"
            if str(report_period).lower().startswith("tháng")
            else f"Báo cáo tháng {report_period}"
        )
    page["live_snapshot"] = snapshot
    return page


def _render_public_page(page: dict):
    page = dict(page)
    page = _hydrate_live_location_page(page)
    if page.get("variant") == "report" and not page.get("scope_label"):
        # Older generated market reports predate `scope_label`, but
        # templates/seo_report.html serializes it into JSON-LD.  Provide a
        # safe runtime fallback so legacy report URLs don't return HTTP 500.
        map_label = str(page.get("map_label") or "")
        if " / " in map_label:
            page["scope_label"] = map_label.split(" / ", 1)[1]
        else:
            page["scope_label"] = "Thủ Dầu Một"
    if page.get("variant") == "report":
        scope = str(page.get("scope_label") or "Thủ Dầu Một")
        city_key, _city_label = _report_hub_city(scope, page.get("path", ""))
        dashboard_params = {
            "tab": "signals",
            "city": "THỦ DẦU MỘT" if city_key == "tdm" else "BẾN CÁT",
            "date_range": "all",
            "mos_min": "10",
        }
        if scope not in {"Thủ Dầu Một", "Bến Cát"}:
            dashboard_params["ward"] = scope
        report_body = page.get("report") or {}
        page["report_data_as_of"] = str(
            report_body.get("data_as_of")
            or report_body.get("published_at")
            or ""
        )
        year, month = _report_period_key(page)
        page["report_dashboard_href"] = "/?" + urllib.parse.urlencode(dashboard_params)
        page["report_dashboard_label"] = (
            f"Xem deal đang hoạt động tại {scope}"
            if scope not in {"Thủ Dầu Một", "Bến Cát"}
            else f"Xem deal đang hoạt động tại {_city_label}"
        )
        page["report_analytics"] = {
            "city": city_key,
            "ward_slug": _report_safe_slug(scope),
            "period": f"{year:04d}-{month:02d}" if year and month else str(report_body.get("period") or ""),
        }
    page["breadcrumbs"] = _page_breadcrumbs(page)
    site_meta = _site_meta(
        page["path"],
        title=page["title"],
        description=page["description"],
        keywords=page["keywords"],
    )
    template = "seo_report.html" if page.get("variant") == "report" else "seo_landing.html"
    return render_template(
        template,
        page=page,
        site_meta=site_meta,
        active_nav=_active_public_nav(page["path"]),
    )


def seo_report_hub_page():
    page = dict(REPORT_HUB)
    page["breadcrumbs"] = _page_breadcrumbs(page)
    reports = sorted(_published_report_pages(), key=_report_sort_key, reverse=True)
    reports, hub_filters = _decorate_report_hub_pages(reports)
    if hub_filters["city_counts"].get("ben-cat", 0) == 0:
        page.update({
            "title": "Báo cáo thị trường BĐS Thủ Dầu Một | Radar BDS",
            "description": "Kho báo cáo thị trường BĐS Thủ Dầu Một theo tháng: mẫu tin hợp lệ, giá trung vị và tín hiệu đáng kiểm tra theo phường.",
            "hero_title": "Báo cáo thị trường BĐS Thủ Dầu Một",
            "hero_text": "Theo dõi các báo cáo tháng đã chốt dữ liệu tại Thủ Dầu Một. Bến Cát sẽ được mở khi có đủ snapshot đạt chuẩn.",
            "scope_label": "Đang phủ 13 phường Thủ Dầu Một",
            "lead_scope_label": "Thủ Dầu Một",
        })
    page["breadcrumbs"] = _page_breadcrumbs(page)
    site_meta = _site_meta(page["path"], title=page["title"], description=page["description"], keywords=page["keywords"])
    return render_template("seo_report_hub.html", page=page, reports=reports, hub_filters=hub_filters, site_meta=site_meta, active_nav="bao-cao")


NEWS_CATEGORY_DEFS = [
    {
        "key": "du-lieu-gia-dat",
        "label": "Giá đất theo phường",
        "description": "Bài dữ liệu giá rao theo từng phường, tách đất nền và nhà đất.",
    },
    {
        "key": "so-sanh-khu-vuc",
        "label": "So sánh khu vực",
        "description": "Bài so sánh phường/khu trong cùng phạm vi dữ liệu để chọn khu cần kiểm tra tiếp.",
    },
    {
        "key": "huong-dan-doc-du-lieu",
        "label": "Hướng dẫn đọc dữ liệu",
        "description": "Giải thích giá trung vị, giá/m², loại hình và cách dùng dữ liệu Radar.",
    },
    {
        "key": "kiem-tra-tin-rao",
        "label": "Kiểm tra tin rao",
        "description": "Checklist đọc tin, giá rao, dấu hiệu đáng kiểm tra và các bước xác minh trước khi liên hệ.",
    },
]
NEWS_CATEGORY_MAP = {item["key"]: item for item in NEWS_CATEGORY_DEFS}


def _news_category_for_article(slug: str, item: dict) -> dict:
    category = item.get("category") or {}
    key = item.get("category_key") or category.get("key")
    title = str(item.get("hero_title") or item.get("title") or "").lower()
    if key and key not in NEWS_CATEGORY_MAP:
        raise ValueError(f"Unknown news category: {key}")
    if not key:
        if slug.startswith("gia-dat-"):
            key = "du-lieu-gia-dat"
        elif "giá rao" in title or "kiểm tra" in title or "giao dịch" in title:
            key = "kiem-tra-tin-rao"
        elif (
            "giá trung vị" in title
            or "cách xem" in title
            or "cách đọc" in title
            or "giá/m²" in title
            or "giá m2" in title
            or "vì sao" in title
        ):
            key = "huong-dan-doc-du-lieu"
        elif "so " in title or "phường nào" in title or "so sánh" in title:
            key = "so-sanh-khu-vuc"
        elif "giá đất" in title:
            key = "du-lieu-gia-dat"
        else:
            key = "huong-dan-doc-du-lieu"
    base = NEWS_CATEGORY_MAP[key]
    return {
        "key": base["key"],
        "label": base["label"],
        "description": base["description"],
    }


def _format_news_date(value: str | None) -> str:
    raw = str(value or "").strip()
    try:
        return datetime.strptime(raw, "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        return raw


def _decorate_news_article(slug: str, item: dict) -> dict:
    decorated = dict(item)
    category = _news_category_for_article(slug, decorated)
    article = decorated.get("article") or {}
    modified_at = str(article.get("modified_at") or article.get("published_at") or "")
    decorated["category"] = category
    decorated["category_key"] = category["key"]
    decorated["category_label"] = category["label"]
    decorated["modified_at"] = modified_at
    decorated["modified_label"] = _format_news_date(modified_at)
    decorated["search_text"] = " ".join(
        str(value or "")
        for value in (
            decorated.get("hero_title"),
            decorated.get("description"),
            decorated.get("scope_label"),
            category["label"],
        )
    )
    return decorated


def _article_category_groups(items: list[dict]) -> tuple[list[dict], list[dict]]:
    categories = []
    groups = []
    for base in NEWS_CATEGORY_DEFS:
        group_items = [item for item in items if item.get("category_key") == base["key"]]
        category = dict(base)
        category["count"] = len(group_items)
        if group_items:
            categories.append(category)
            groups.append({**category, "articles": group_items})
    return categories, groups


def _article_hub_page(*, hub_path: str, article_prefix: str, active_nav: str, title: str | None = None):
    page = dict(KNOWLEDGE_HUB)
    is_news_archive = article_prefix == "/tin-tuc/"
    page["path"] = hub_path
    if title:
        page["title"] = title
    if is_news_archive:
        page["hero_badge"] = "Tin tức BĐS Bình Dương"
        page["hero_title"] = "Tin tức BĐS Bình Dương từ dữ liệu Radar BDS"
        page["hero_text"] = "Phân tích giá rao, so sánh phường và cách kiểm tra tin từ dữ liệu Radar BDS để người mua biết nên mở khu vực nào tiếp theo."
        page["lead_scope_label"] = "Bình Dương"
        page["breadcrumbs"] = [
            {"name": "Trang chủ", "href": "/", "url": _public_url("/")},
            {"name": "Tin tức", "href": "/tin-tuc", "url": _public_url("/tin-tuc")},
            {
                "name": "Tin từ dữ liệu Radar BDS",
                "href": hub_path,
                "url": _public_url(hub_path),
            },
        ]
    else:
        page["breadcrumbs"] = _page_breadcrumbs(page)

    matching = []
    for slug, item in SEO_ARTICLES.items():
        if not str(item.get("path") or "").startswith(article_prefix):
            continue
        decorated = _decorate_news_article(slug, item) if is_news_archive else dict(item)
        matching.append((slug, decorated))
    matching.sort(
        key=lambda pair: (
            (pair[1].get("article") or {}).get("modified_at", ""),
            (pair[1].get("article") or {}).get("published_at", ""),
            pair[0],
        ),
        reverse=True,
    )
    featured_slug = page.get("featured_slug")
    featured = None
    articles = []
    for slug, item in matching:
        if featured is None and (slug == featured_slug or featured_slug not in SEO_ARTICLES):
            featured = item
        else:
            articles.append(item)
    if featured is None and matching:
        featured = matching[0][1]
        articles = [item for _, item in matching[1:]]
    if featured is None:
        # Empty /tin-tuc state before the first daily article: show legacy knowledge
        # content instead of 404, but keep canonical/news hub path for future growth.
        featured = dict(SEO_ARTICLES[KNOWLEDGE_HUB["featured_slug"]])
        articles = sorted(
            (
                dict(item)
                for slug, item in SEO_ARTICLES.items()
                if slug != KNOWLEDGE_HUB["featured_slug"] and str(item.get("path") or "").startswith("/kien-thuc/")
            ),
            key=lambda item: ((item.get("article") or {}).get("modified_at", ""), (item.get("article") or {}).get("published_at", "")),
            reverse=True,
        )
    all_articles = ([featured] if featured else []) + articles
    article_categories, category_groups = _article_category_groups(articles) if is_news_archive else ([], [])
    page["article_count"] = len(all_articles)
    page["category_count"] = len(article_categories)
    latest_modified_at = max(
        (str((item.get("article") or {}).get("modified_at") or "") for item in all_articles),
        default="",
    )
    page["latest_modified_at"] = latest_modified_at
    page["latest_modified_label"] = _format_news_date(latest_modified_at)
    site_meta = _site_meta(page["path"], title=page["title"], description=page["description"], keywords=page["keywords"])
    return render_template(
        "seo_knowledge_hub.html",
        page=page,
        featured=featured,
        articles=articles,
        article_categories=article_categories,
        category_groups=category_groups,
        site_meta=site_meta,
        active_nav=active_nav,
    )


def seo_knowledge_hub_page():
    return _article_hub_page(hub_path="/kien-thuc", article_prefix="/kien-thuc/", active_nav="kien-thuc")


def seo_news_radar_archive_page():
    return _article_hub_page(
        hub_path="/tin-tuc/du-lieu-radarbds",
        article_prefix="/tin-tuc/",
        active_nav="tin-tuc",
        title="Tin tức BĐS Bình Dương | Radar BDS",
    )


def _iso_public_datetime(value) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "")


def _public_date_label(value) -> str:
    if isinstance(value, datetime):
        return value.strftime("%d/%m/%Y")
    raw = str(value or "")
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).strftime("%d/%m/%Y")
    except ValueError:
        return raw


def _decorate_public_content_item(item: dict) -> dict:
    decorated = dict(item)
    decorated["published_iso"] = _iso_public_datetime(item.get("published_at"))
    decorated["published_label"] = _public_date_label(item.get("published_at"))
    decorated["collected_iso"] = _iso_public_datetime(
        item.get("created_at") or item.get("updated_at")
    )
    decorated["collected_label"] = _public_date_label(
        item.get("created_at") or item.get("updated_at")
    )
    decorated["year"] = decorated["published_iso"][:4]
    decorated["detail_url"] = (
        f"/tin-tuc/quyet-dinh-van-ban/{decorated.get('slug', '')}"
        if decorated.get("item_type") == "legal_document"
        else decorated.get("source_url")
    )
    decorated["search_text"] = " ".join(
        str(decorated.get(key) or "")
        for key in (
            "title",
            "summary",
            "source_name",
            "topic",
            "document_number",
            "issuing_authority",
            "document_type",
            "year",
        )
    )
    return decorated


def _public_topic_label(topic: str) -> str:
    normalized = str(topic or "").strip()
    labels = {
        "bat-dong-san-binh-duong": "Bất động sản Bình Dương",
        "ha-tang": "Hạ tầng",
        "quy-hoach": "Quy hoạch",
        "thi-truong": "Thị trường",
    }
    return labels.get(normalized, normalized.replace("-", " ").capitalize())


def _collection_schema(page: dict, items: list[dict]) -> dict:
    return {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "CollectionPage",
                "name": page["heading"],
                "url": _public_url(page["path"]),
                "description": page["description"],
            },
            {
                "@type": "ItemList",
                "itemListElement": [
                    {
                        "@type": "ListItem",
                        "position": index,
                        "name": item.get("title") or item.get("name"),
                        "url": (
                            item.get("url")
                            if str(item.get("url") or "").startswith("http")
                            else _public_url(item.get("url") or "/")
                        ),
                    }
                    for index, item in enumerate(items, start=1)
                ],
            },
            _breadcrumb_schema(page["breadcrumbs"]),
        ],
    }


def seo_news_hub_page():
    page = {
        "path": "/tin-tuc",
        "title": "Tin tức BĐS Bình Dương | Radar BDS",
        "heading": "Trung tâm tin tức BĐS Bình Dương",
        "description": (
            "Theo dõi chủ đề nóng từ nguồn báo chí, phân tích từ dữ liệu Radar BDS "
            "và quyết định, văn bản chính thống."
        ),
        "breadcrumbs": [
            {"name": "Trang chủ", "href": "/", "url": _public_url("/")},
            {"name": "Tin tức", "href": "/tin-tuc", "url": _public_url("/tin-tuc")},
        ],
    }
    sections = []
    for key in ("chu-de-nong", "du-lieu-radarbds", "quyet-dinh-van-ban"):
        section = dict(NEWS_HUBS[key])
        if section["item_type"] == "radar_article":
            section["items"] = [
                {
                    "title": item.get("hero_title"),
                    "summary": item.get("description"),
                    "url": item.get("path"),
                    "source_name": "Radar BDS",
                    "is_external": False,
                }
                for item in sorted(
                    (
                        item
                        for item in SEO_ARTICLES.values()
                        if str(item.get("path") or "").startswith("/tin-tuc/")
                    ),
                    key=lambda item: (
                        (item.get("article") or {}).get("modified_at", ""),
                        item.get("path", ""),
                    ),
                    reverse=True,
                )[:3]
            ]
        else:
            section["items"] = [
                _decorate_public_content_item(item)
                for item in _public_content_repository.list_published(
                    item_type=section["item_type"], limit=3
                )
            ]
            for item in section["items"]:
                item["url"] = (
                    item.get("source_url")
                    if section["item_type"] == "hot_topic"
                    else item.get("detail_url")
                )
                item["is_external"] = section["item_type"] == "hot_topic"
        sections.append(section)
    return render_template(
        "news_portal.html",
        page=page,
        sections=sections,
        site_meta=_site_meta(
            page["path"],
            title=page["title"],
            description=page["description"],
            keywords="tin tức Bình Dương, bất động sản Bình Dương, văn bản quy hoạch",
        ),
        schema_graph=_collection_schema(
            page,
            [
                {"title": section["heading"], "url": section["path"]}
                for section in sections
            ],
        ),
        active_nav="tin-tuc",
    )


def public_content_hub_page(kind: str):
    page = dict(NEWS_HUBS.get(kind) or {})
    if not page or page["item_type"] not in {"hot_topic", "legal_document"}:
        abort(404)
    page["breadcrumbs"] = [
        {"name": "Trang chủ", "href": "/", "url": _public_url("/")},
        {"name": "Tin tức", "href": "/tin-tuc", "url": _public_url("/tin-tuc")},
        {
            "name": page["heading"],
            "href": page["path"],
            "url": _public_url(page["path"]),
        },
    ]
    items = [
        _decorate_public_content_item(item)
        for item in _public_content_repository.list_published(
            item_type=page["item_type"], limit=None
        )
    ]
    facets = sorted(
        {
            str(
                item.get("source_name")
                if page["item_type"] == "hot_topic"
                else item.get("issuing_authority") or item.get("source_name") or ""
            ).strip()
            for item in items
            if (
                item.get("source_name")
                if page["item_type"] == "hot_topic"
                else item.get("issuing_authority") or item.get("source_name")
            )
        }
    )
    topics = sorted(
        (
            {"value": topic, "label": _public_topic_label(topic)}
            for topic in {
                str(item.get("topic") or "").strip()
                for item in items
                if item.get("topic")
            }
        ),
        key=lambda topic: topic["label"],
    )
    return render_template(
        "public_content_hub.html",
        page=page,
        items=items,
        facets=facets,
        topics=topics,
        site_meta=_site_meta(
            page["path"],
            title=page["title"],
            description=page["description"],
            keywords=f"{page['heading']}, Radar BDS",
        ),
        schema_graph=_collection_schema(
            page,
            [
                {
                    "title": item.get("title"),
                    "url": (
                        item.get("source_url")
                        if page["item_type"] == "hot_topic"
                        else item.get("detail_url")
                    ),
                }
                for item in items
            ],
        ),
        active_nav="tin-tuc",
    )


def legal_document_page(slug: str):
    item = _public_content_repository.get_published_by_slug(slug)
    if not item or item.get("item_type") != "legal_document":
        abort(404)
    item = _decorate_public_content_item(item)
    page = {
        "path": f"/tin-tuc/quyet-dinh-van-ban/{slug}",
        "title": f"{item['title']} | Radar BDS",
        "heading": item["title"],
        "description": item.get("summary") or item["title"],
    }
    page["breadcrumbs"] = [
        {"name": "Trang chủ", "href": "/", "url": _public_url("/")},
        {"name": "Tin tức", "href": "/tin-tuc", "url": _public_url("/tin-tuc")},
        {
            "name": "Quyết định & văn bản",
            "href": "/tin-tuc/quyet-dinh-van-ban",
            "url": _public_url("/tin-tuc/quyet-dinh-van-ban"),
        },
        {"name": item["title"], "href": page["path"], "url": _public_url(page["path"])},
    ]
    stable_pdf_path = f"/tai-lieu/van-ban/{slug}.pdf"
    legislation = {
        "@type": "Legislation",
        "name": item["title"],
        "url": _public_url(page["path"]),
        "legislationIdentifier": item.get("document_number"),
        "legislationDate": item.get("published_iso"),
        "legislationJurisdiction": item.get("document_scope"),
        "author": {
            "@type": "GovernmentOrganization",
            "name": item.get("issuing_authority"),
        },
        "encoding": {
            "@type": "MediaObject",
            "contentUrl": _public_url(stable_pdf_path),
            "encodingFormat": "application/pdf",
        },
    }
    return render_template(
        "legal_document.html",
        page=page,
        item=item,
        stable_pdf_path=stable_pdf_path,
        site_meta=_site_meta(
            page["path"],
            title=page["title"],
            description=page["description"],
            keywords=f"{item.get('document_number', '')}, văn bản Bình Dương",
        ),
        schema_graph={
            "@context": "https://schema.org",
            "@graph": [legislation, _breadcrumb_schema(page["breadcrumbs"])],
        },
        active_nav="tin-tuc",
    )


def legal_document_pdf(slug: str):
    item = _public_content_repository.get_published_by_slug(slug)
    if (
        not item
        or item.get("item_type") != "legal_document"
        or not item.get("pdf_object_key")
    ):
        abort(404)
    target = public_pdf_url(item["pdf_object_key"])
    if not target:
        abort(404)
    return redirect(target, code=302)


_LEGACY_KNOWLEDGE_REDIRECTS = {
    "dat-binh-duong-vi-sao-khong-nen-so-gia-toan-tinh-truoc-khi-loc-tin": (
        "/tin-tuc/cach-xem-gia-dat-binh-duong-khong-bi-so-sai"
    ),
    "gia-dat-phu-my-thu-dau-mot-cap-nhat-thang-7-2026": (
        "/tin-tuc/gia-dat-phu-my-hien-bao-nhieu"
    ),
    "gia-dat-thu-dau-mot-theo-phuong-vi-sao-phai-tach-phu-my-hiep-an-chanh-nghia": (
        "/tin-tuc/phuong-nao-thu-dau-mot-gia-dat-con-de-mua"
    ),
}


def seo_knowledge_legacy_redirect(article_slug: str | None = None):
    target = "/tin-tuc"
    if article_slug:
        target = _LEGACY_KNOWLEDGE_REDIRECTS.get(str(article_slug or ""))
        if not target:
            article = SEO_ARTICLES.get(article_slug)
            if not article:
                abort(404)
            article_path = str(article.get("path") or "")
            if article_path.startswith(("/tin-tuc/", "/bao-cao/")):
                target = article_path
            else:
                abort(404)
    query = request.query_string.decode("ascii", errors="ignore")
    if query:
        target = f"{target}?{query}"
    return redirect(target, code=301)


def seo_report_or_article_page(report_slug: str):
    report_key = f"bao-cao/{report_slug}"
    if report_key in SEO_PAGES:
        return seo_landing_page(report_key)
    if report_slug in SEO_ARTICLES:
        page_path = str(SEO_ARTICLES[report_slug].get("path") or "")
        if page_path.startswith("/bao-cao/"):
            return seo_article_page(report_slug)
        if page_path.startswith("/tin-tuc/"):
            query = request.query_string.decode("ascii", errors="ignore")
            target = page_path
            if query:
                target = f"{target}?{query}"
            return redirect(target, code=301)
    match = re.fullmatch(r"([a-z0-9-]+)-thang-\d{2}-\d{4}", report_slug or "")
    if match:
        latest = _latest_ward_report(match.group(1))
        if latest and latest.get("path"):
            return redirect(str(latest["path"]), code=302)
    abort(404)


_LEGACY_NEWS_REDIRECTS = {
    "gia-dat-phu-my-thu-dau-mot-cap-nhat-thang-7-2026": "/tin-tuc/gia-dat-phu-my-hien-bao-nhieu",
    "gia-dat-hiep-an-thu-dau-mot-cap-nhat-thang-7-2026": "/tin-tuc/gia-dat-hiep-an-hien-bao-nhieu",
    "gia-rao-k": "/tin-tuc/gia-rao-khac-gia-giao-dich-the-nao",
}


def seo_news_article_page(slug: str):
    target = _LEGACY_NEWS_REDIRECTS.get(str(slug or ""))
    if target:
        query = request.query_string.decode("ascii", errors="ignore")
        if query:
            target = f"{target}?{query}"
        return redirect(target, code=301)
    if slug in SEO_ARTICLES and str(SEO_ARTICLES[slug].get("path") or "").startswith("/tin-tuc/"):
        return seo_article_page(slug)
    abort(404)


_LEGACY_SEO_REDIRECTS = {
    "binh-duong/di-an": "/binh-duong",
}


def seo_landing_page(slug):
    target = _LEGACY_SEO_REDIRECTS.get(str(slug or ""))
    if target:
        query = request.query_string.decode("ascii", errors="ignore")
        if query:
            target = f"{target}?{query}"
        return redirect(target, code=301)
    page = SEO_PAGES.get(slug)
    if not page:
        abort(404)
    if page.get("variant") == "report" and not _is_publishable_monthly_report(page):
        abort(404)
    return _render_public_page(page)


def seo_tdm_ward_redirect(ward_slug: str):
    if ward_slug not in _PRIORITY_TDM_WARDS:
        abort(404)
    target = f"/binh-duong/phuong-{ward_slug}"
    query = request.query_string.decode("ascii", errors="ignore")
    if query:
        target = f"{target}?{query}"
    return redirect(target, code=301)


def seo_article_page(slug):
    page = SEO_ARTICLES.get(slug)
    if not page:
        abort(404)
    canonical_path = str(page.get("path") or "")
    if canonical_path and request.path.rstrip("/") != canonical_path.rstrip("/"):
        query = request.query_string.decode("ascii", errors="ignore")
        target = canonical_path
        if query:
            target = f"{target}?{query}"
        return redirect(target, code=301)
    page = dict(page)
    page["breadcrumbs"] = _page_breadcrumbs(page)
    site_meta = _site_meta(
        page["path"],
        title=page["title"],
        description=page["description"],
        keywords=page["keywords"],
    )
    return render_template("seo_article.html", page=page, site_meta=site_meta, active_nav=_active_public_nav(page["path"]))


def robots_txt():
    body = f"""User-agent: *
Allow: /

Sitemap: {_public_url('/sitemap.xml')}
"""
    return Response(body, mimetype="text/plain")


def llms_txt():
    ward_lines = "\n".join(
        f"- {name}: {_public_url(f'/binh-duong/phuong-{slug}')}"
        for slug, name in _PRIORITY_TDM_WARDS.items()
    )
    planning_lines = "\n".join(
        f"- {page['breadcrumb_label']}: {_public_url(page['path'])}"
        for page in PLANNING_PAGE_LIST
    )
    city_map_lines = "\n".join(
        f"- Bộ bản đồ TP {page['city_name']}: {_public_url(page['path'])}"
        for page in CITY_MAP_PRODUCTS.values()
    )
    news_hub_lines = "\n".join(
        f"- {page['heading']}: {_public_url(page['path'])}"
        for page in NEWS_HUBS.values()
    )
    planning_category_lines = "\n".join(
        f"- {page['heading']}: {_public_url(page['path'])}"
        for page in PLANNING_CATEGORY_PAGES.values()
    )
    body = f"""# Radar BDS

> Radar BDS tổng hợp và chuẩn hóa dữ liệu tin rao bất động sản Bình Dương để người dùng tham khảo trước khi kiểm tra từng tài sản.

## Phạm vi ưu tiên
- Thủ Dầu Một: {_public_url('/binh-duong/thu-dau-mot')}
{ward_lines}

## Cách đọc dữ liệu
- Số tin là lượng tin rao công khai Radar BDS đang theo dõi trong bộ lọc hiện hành.
- Giá/m² trên trang phường là giá tham khảo từ dữ liệu tin rao, không phải giá giao dịch chính thức.
- Tín hiệu là bộ lọc ưu tiên kiểm tra, không phải khuyến nghị mua.
- Dữ liệu không thay thế kiểm tra thực địa, quy hoạch và pháp lý.

## Trang chính
- Thị trường Bình Dương: {_public_url('/binh-duong')}
- Công cụ định giá đất Bình Dương: {_public_url('/dinh-gia-bds')}
- Tra cứu bảng giá đất TP.HCM 2026: {_public_url('/bang-gia-dat-tphcm')}
- Báo cáo dữ liệu: {_public_url('/bao-cao')}
- Tin tức dữ liệu: {_public_url('/tin-tuc')}
{news_hub_lines}
- Bản đồ Bình Dương: {_public_url('/ban-do-binh-duong')}
{city_map_lines}
- Bản đồ quy hoạch Bình Dương cũ: {_public_url('/quy-hoach-binh-duong')}
{planning_lines}
{planning_category_lines}
- Phương pháp lọc deal: {_public_url('/san-deal-bds')}
"""
    return Response(body, mimetype="text/plain")


def sitemap_xml():
    def render_sitemap_entry(page, *, changefreq, priority, lastmod=""):
        lastmod_markup = f"    <lastmod>{lastmod}</lastmod>\n" if lastmod else ""
        return (
            "  <url>\n"
            f"    <loc>{_public_url(page['path'])}</loc>\n"
            f"{lastmod_markup}"
            f"    <changefreq>{changefreq}</changefreq>\n"
            f"    <priority>{priority}</priority>\n"
            "  </url>"
        )

    unique_pages = []
    seen_paths = set()
    news_lastmod = max(
        (
            str((page.get("article") or {}).get("modified_at") or "")
            for page in SEO_ARTICLES.values()
            if str(page.get("path") or "").startswith("/tin-tuc/")
        ),
        default="",
    )
    published_content_items = _public_content_repository.list_published(
        limit=None
    )
    content_lastmod = {}
    for item in published_content_items:
        item_type = str(item.get("item_type") or "")
        value = _iso_public_datetime(
            item.get("updated_at") or item.get("published_at")
        )[:10]
        if value:
            content_lastmod[item_type] = max(
                content_lastmod.get(item_type, ""),
                value,
            )
    sitemap_news_hubs = []
    for hub in NEWS_HUBS.values():
        sitemap_hub = dict(hub)
        if hub["item_type"] == "radar_article":
            sitemap_hub["updated_at"] = news_lastmod
        else:
            sitemap_hub["updated_at"] = content_lastmod.get(
                hub["item_type"],
                hub.get("updated_at", ""),
            )
        sitemap_news_hubs.append(sitemap_hub)
    news_hub = dict(
        KNOWLEDGE_HUB,
        path="/tin-tuc",
        title="Tin tức BĐS Bình Dương | Radar BDS",
        sitemap_lastmod=max(
            [
                news_lastmod,
                *content_lastmod.values(),
            ]
        ),
    )
    public_document_pages = [
        {
            "path": f"/tin-tuc/quyet-dinh-van-ban/{item['slug']}",
            "updated_at": _iso_public_datetime(item.get("updated_at"))[:10],
        }
        for item in published_content_items
        if item.get("item_type") == "legal_document" and item.get("slug")
    ]
    for page in [
        REPORT_HUB,
        news_hub,
        *sitemap_news_hubs,
        *CITY_MAP_PRODUCTS.values(),
        BINH_DUONG_MAP_PAGE,
        PLANNING_HUB,
        *PLANNING_CATEGORY_PAGES.values(),
        *SEO_PAGES.values(),
        *PLANNING_PAGE_LIST,
        *public_document_pages,
    ]:
        path = page.get("path")
        if not path or path in seen_paths:
            continue
        if page.get("variant") == "report" and not _is_publishable_monthly_report(page):
            continue
        seen_paths.add(path)
        unique_pages.append(page)
    seo_urls = "\n".join(
        render_sitemap_entry(
            page,
            changefreq="daily",
            priority="0.8",
            lastmod=page.get("sitemap_lastmod") or page.get("updated_at") or "",
        )
        for page in unique_pages
    )
    article_urls = "\n".join(
        render_sitemap_entry(
            page,
            changefreq="weekly",
            priority="0.7",
            lastmod=(page.get("article") or {}).get("modified_at") or "",
        )
        for slug, page in SEO_ARTICLES.items()
    )
    body = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>{_public_url('/')}</loc>
    <changefreq>hourly</changefreq>
    <priority>1.0</priority>
  </url>
  <url>
    <loc>{_public_url('/dinh-gia-bds')}</loc>
    <changefreq>daily</changefreq>
    <priority>0.9</priority>
  </url>
  <url>
    <loc>{_public_url('/bang-gia-dat-tphcm')}</loc>
    <changefreq>monthly</changefreq>
    <priority>0.9</priority>
  </url>
{seo_urls}
{article_urls}
</urlset>
"""
    return Response(body, mimetype="application/xml")


_PUBLIC_CACHE_CONTROL = (
    "public, max-age=15, stale-while-revalidate=180, "
    "stale-if-error=180"
)
_SIGNAL_DATASETS = (DATASET_SIGNALS,)
_DASHBOARD_DATASETS = (DATASET_SIGNALS, DATASET_MARKET)
_VALID_SIGNAL_SORTS = frozenset(
    {"newest", "price_m2_asc", "price_asc", "mos_desc", "score_desc"}
)


def _public_cache_enabled() -> bool:
    return os.getenv("RADAR_PUBLIC_CACHE_ENABLED", "0").strip() == "1"


def _public_dataset_versions(names) -> dict[str, int]:
    if not _public_cache_enabled():
        return {name: 0 for name in names}
    try:
        return get_current_dataset_versions(names)
    except Exception:
        logger.exception("Unable to resolve public dataset versions")
        return {name: 0 for name in names}


def _public_json_response(
    result: CacheResult,
    *,
    tier: str,
    dataset_version: int | None = None,
):
    response = jsonify(result.payload)
    response.headers["X-Radar-Cache"] = result.status
    if dataset_version is not None:
        response.headers["X-Radar-Dataset-Version"] = str(int(dataset_version))
    response.headers["Server-Timing"] = (
        f'app_cache;desc="{result.status}", load;dur={result.load_ms:.2f}'
    )
    is_anonymous = (
        tier == "guest"
        and not request.cookies.get(SESSION_COOKIE_NAME)
        and not request.headers.get("Authorization")
    )
    if (
        is_anonymous
        and response.status_code == 200
        and "Set-Cookie" not in response.headers
    ):
        response.headers["X-Radar-Public-Cache"] = "1"
        response.headers["Cache-Control"] = _PUBLIC_CACHE_CONTROL
        response.headers["Vary"] = "Cookie"
        response.headers.pop("Pragma", None)
        response.headers.pop("Expires", None)
    else:
        response.headers["Cache-Control"] = "private, no-store"
        response.headers.pop("X-Radar-Public-Cache", None)
    return response


def _public_busy_response(exc):
    retry_after = int(getattr(exc, "retry_after", 1) or 1)
    response = jsonify(
        {"error": "temporarily_busy", "retry_after": retry_after}
    )
    response.status_code = 503
    response.headers["Retry-After"] = str(retry_after)
    response.headers["Cache-Control"] = "no-store"
    return response


def _bounded_public_filter_values(
    *, wards, sources, prop_types, range_kwargs, keyword
):
    wards = sorted(dict.fromkeys(wards or ()))[:64]
    sources = sorted(dict.fromkeys(sources or ()))[:4]
    prop_types = sorted(dict.fromkeys(prop_types or ()))[:8]
    bounded_ranges = dict(range_kwargs)
    bounded_ranges["area_ranges"] = sorted(
        dict.fromkeys(range_kwargs["area_ranges"])
    )[:12]
    bounded_ranges["price_ranges"] = sorted(
        dict.fromkeys(range_kwargs["price_ranges"])
    )[:12]
    return wards, sources, prop_types, bounded_ranges, keyword[:80]


def _public_filter_query(
    *,
    active_city,
    wards,
    sources,
    prop_types,
    only_drops,
    trend_period,
    mos_min,
    range_kwargs,
    keyword,
    date_range,
    include_guland_high_activity,
    **extra,
):
    return {
        "active_city": active_city,
        "wards": wards,
        "sources": sources,
        "prop_types": prop_types,
        "only_drops": bool(only_drops),
        "trend_period": trend_period,
        "mos_min": int(mos_min or 0),
        "area_min": float(range_kwargs["area_min"] or 0),
        "area_max": float(range_kwargs["area_max"] or 0),
        "price_min": float(range_kwargs["price_min"] or 0),
        "price_max": float(range_kwargs["price_max"] or 0),
        "area_ranges": range_kwargs["area_ranges"],
        "price_ranges": range_kwargs["price_ranges"],
        "keyword": keyword,
        "date_range": date_range,
        "include_guland_high_activity": bool(include_guland_high_activity),
        **extra,
    }


def _tier_safe_signal_payload(payload: dict, tier: str) -> dict:
    safe = dict(payload)
    safe["signals"] = [
        redact_for_tier(signal, tier)
        for signal in (payload.get("signals") or [])
    ]
    return safe


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
    try:
        with get_conn() as conn:
            versions = get_dataset_versions(conn, (DATASET_SIGNALS,))
        return str(versions[DATASET_SIGNALS])
    except Exception:
        # Keep lightweight dashboard reads resilient even if the durable
        # version table is missing or temporarily unavailable.
        return "0"


def _db_handle():
    """Placeholder argument for older service signatures; runtime uses DATABASE_URL."""
    return None


def api_submit_listing_report(listing_id: int):
    if request.content_length is not None and request.content_length > 4096:
        return jsonify({"ok": False, "error": "payload_too_large"}), 413
    if not request.is_json:
        return jsonify({"ok": False, "error": "invalid_payload"}), 400
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "invalid_payload"}), 400
    secret = os.getenv("LISTING_REPORT_HASH_SECRET", "").strip()
    try:
        with get_conn() as conn:
            result = submit_listing_report(
                conn,
                listing_id=listing_id,
                payload=payload,
                actor=current_user(),
                request_meta={
                    "ip": client_ip_from_request(),
                    "user_agent": request.headers.get("User-Agent", ""),
                },
                secret=secret,
            )
    except ListingReportError as exc:
        return jsonify({"ok": False, "error": exc.code}), exc.status
    return jsonify({"ok": True, "duplicate": result.duplicate}), (200 if result.duplicate else 201)


@require_admin_auth
def admin_api_listing_reports():
    status = (request.args.get("status") or "pending").strip()
    page = _clamp_int(request.args.get("page"), 1, 1, 1_000_000)
    limit = _clamp_int(request.args.get("limit"), 50, 1, 100)
    try:
        with get_conn() as conn:
            result = list_listing_reports(
                conn,
                status=status,
                page=page,
                limit=limit,
            )
    except ListingReportError as exc:
        return jsonify({"ok": False, "error": exc.code}), exc.status
    return jsonify({"ok": True, **result})


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


def _include_guland_high_activity(req, tier: str) -> bool:
    return (
        tier == "admin"
        and (req.args.get("hide_guland_reposts") or "1").strip() == "0"
    )


_LISTING_MAP_LOCATION_KEY_RE = re.compile(
    r"^(exact|road|landmark|ward):[a-z0-9:-]+$"
)
_LISTING_MAP_SENSITIVE_KEYS = frozenset({
    "url",
    "phone",
    "contact_phone",
    "description",
    "seller_name",
    "evidence_text",
    "source_url",
})


def _listing_map_filters(req, mode: str) -> MapFilters:
    (
        active_city,
        wards,
        sources,
        prop_types,
        only_drops,
        _trend_period,
        mos_min,
    ) = get_base_filters(req)
    if not wards and active_city in CITY_MAP:
        wards = CITY_MAP[active_city]
    ranges = _request_range_filter_kwargs(req)
    tier = current_tier()
    return MapFilters(
        city=active_city,
        wards=tuple(wards or ()),
        sources=tuple(sources or ()),
        prop_types=tuple(prop_types or ()),
        only_drops=bool(only_drops),
        mos_min=int(mos_min or 0),
        area_min=ranges["area_min"],
        area_max=ranges["area_max"],
        price_min=ranges["price_min"],
        price_max=ranges["price_max"],
        area_ranges=tuple(ranges["area_ranges"]),
        price_ranges=tuple(ranges["price_ranges"]),
        keyword=_request_keyword(req),
        date_range=_request_date_range(req),
        complete_only=(
            mode == "all"
            and (req.args.get("complete") or "").strip().lower()
            in {"1", "true", "yes", "on"}
        ),
        include_guland_high_activity=_include_guland_high_activity(req, tier),
    )


def _safe_listing_map_payload(value, tier: str):
    if isinstance(value, dict):
        safe = {
            key: _safe_listing_map_payload(item, tier)
            for key, item in value.items()
            if key not in _LISTING_MAP_SENSITIVE_KEYS
        }
        return redact_for_tier(safe, tier)
    if isinstance(value, list):
        return [_safe_listing_map_payload(item, tier) for item in value]
    return value


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
    clear_admin_read_cache("audit")


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
    if not wards and active_city in CITY_MAP:
        wards = CITY_MAP[active_city]
    wards, sources, prop_types, range_kwargs, keyword = (
        _bounded_public_filter_values(
            wards=wards,
            sources=sources,
            prop_types=prop_types,
            range_kwargs=range_kwargs,
            keyword=keyword,
        )
    )
    active_city = str(active_city or "")[:80]
    trend_period = trend_period if trend_period in {"day", "week", "month"} else "day"
    db_path = _db_handle()
    include_trend = request.args.get("include_trend") == "1"
    tier = current_tier()
    include_guland_high_activity = _include_guland_high_activity(request, tier)
    versions = _public_dataset_versions(_DASHBOARD_DATASETS)
    cache_query = _public_filter_query(
        active_city=active_city,
        wards=wards,
        sources=sources,
        prop_types=prop_types,
        only_drops=only_drops,
        trend_period=trend_period,
        mos_min=mos_min,
        range_kwargs=range_kwargs,
        keyword=keyword,
        date_range=date_range,
        include_guland_high_activity=include_guland_high_activity,
        include_trend=bool(include_trend),
    )
    force_refresh = _dashboard_cache_refresh_requested(request)
    cache_tier = "admin" if force_refresh else tier

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
            include_guland_high_activity=include_guland_high_activity,
            **range_kwargs,
        )
        return {
            "stats": data["stats"],
            "market": data["market"],
            "trend_data": data["trend_data"],
            "signals_version": (
                str(versions[DATASET_SIGNALS])
                if _public_cache_enabled()
                else _get_signals_version(db_path)
            ),
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

    try:
        result = get_or_load_public_payload(
            endpoint="dashboard",
            tier=cache_tier,
            versions=versions,
            query=cache_query,
            loader=_load_dashboard_payload,
            force_refresh=force_refresh,
        )
    except (PublicCacheBusy, DatabasePoolBusy) as exc:
        return _public_busy_response(exc)
    return _public_json_response(
        result,
        tier=cache_tier,
        dataset_version=versions.get(DATASET_SIGNALS, 0),
    )

@rate_limit("dashboard", limits={"guest": 1200, "free": 2400, "vip": None, "admin": None})
def api_counts():
    active_city, wards, sources, prop_types, only_drops, trend_period, mos_min = get_base_filters(request)
    range_kwargs = _request_range_filter_kwargs(request)
    keyword = _request_keyword(request)
    date_range = _request_date_range(request)
    if not wards and active_city in CITY_MAP:
        wards = CITY_MAP[active_city]
    wards, sources, prop_types, range_kwargs, keyword = (
        _bounded_public_filter_values(
            wards=wards,
            sources=sources,
            prop_types=prop_types,
            range_kwargs=range_kwargs,
            keyword=keyword,
        )
    )
    active_city = str(active_city or "")[:80]
    trend_period = trend_period if trend_period in {"day", "week", "month"} else "day"
    tier = current_tier()
    include_guland_high_activity = _include_guland_high_activity(request, tier)
    versions = _public_dataset_versions(_SIGNAL_DATASETS)
    cache_query = _public_filter_query(
        active_city=active_city,
        wards=wards,
        sources=sources,
        prop_types=prop_types,
        only_drops=only_drops,
        trend_period=trend_period,
        mos_min=mos_min,
        range_kwargs=range_kwargs,
        keyword=keyword,
        date_range=date_range,
        include_guland_high_activity=include_guland_high_activity,
    )
    force_refresh = _dashboard_cache_refresh_requested(request)
    cache_tier = "admin" if force_refresh else tier

    def _load_counts_payload():
        return {
            "stats": load_counts(
                _db_handle(),
                sources=sources,
                wards=wards,
                prop_types=prop_types,
                only_drops=only_drops,
                mos_min=mos_min,
                keyword=keyword,
                tier=tier,
                date_range=date_range,
                include_guland_high_activity=include_guland_high_activity,
                **range_kwargs,
            ),
            "active_city": active_city,
            "active_wards": wards,
            "active_sources": sources,
            "active_props": prop_types,
            "trend_period": trend_period,
            "tier": tier,
        }

    try:
        result = get_or_load_public_payload(
            endpoint="counts",
            tier=cache_tier,
            versions=versions,
            query=cache_query,
            loader=_load_counts_payload,
            force_refresh=force_refresh,
        )
    except (PublicCacheBusy, DatabasePoolBusy) as exc:
        return _public_busy_response(exc)
    return _public_json_response(
        result,
        tier=cache_tier,
        dataset_version=versions.get(DATASET_SIGNALS, 0),
    )

def api_signals():
    active_city, wards, sources, prop_types, only_drops, trend_period, mos_min = get_base_filters(request)
    range_kwargs = _request_range_filter_kwargs(request)
    keyword = _request_keyword(request)
    date_range = _request_date_range(request)
    if not wards and active_city in CITY_MAP:
        wards = CITY_MAP[active_city]
    wards, sources, prop_types, range_kwargs, keyword = (
        _bounded_public_filter_values(
            wards=wards,
            sources=sources,
            prop_types=prop_types,
            range_kwargs=range_kwargs,
            keyword=keyword,
        )
    )
    active_city = str(active_city or "")[:80]
    trend_period = trend_period if trend_period in {"day", "week", "month"} else "day"
    page = _clamp_int(request.args.get("page"), 1, 1, 2_000)
    limit = _clamp_int(request.args.get("limit"), 30, 1, 100)
    sort = request.args.get("sort", "newest")
    if sort not in _VALID_SIGNAL_SORTS:
        sort = "newest"
    include_total = request.args.get("include_total") != "0"
    db_path = _db_handle()
    tier = current_tier()
    include_guland_high_activity = _include_guland_high_activity(request, tier)
    versions = _public_dataset_versions(_SIGNAL_DATASETS)
    cache_query = _public_filter_query(
        active_city=active_city,
        wards=wards,
        sources=sources,
        prop_types=prop_types,
        only_drops=only_drops,
        trend_period=trend_period,
        mos_min=mos_min,
        range_kwargs=range_kwargs,
        keyword=keyword,
        date_range=date_range,
        include_guland_high_activity=include_guland_high_activity,
        sort=sort,
        page=page,
        limit=limit,
        include_total=bool(include_total),
    )
    force_refresh = _dashboard_cache_refresh_requested(request)
    cache_tier = "admin" if force_refresh else tier

    def _load_signal_payload():
        return _tier_safe_signal_payload(
            load_signals(
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
                include_guland_high_activity=include_guland_high_activity,
                **range_kwargs,
            ),
            tier,
        )

    try:
        result = get_or_load_public_payload(
            endpoint="signals",
            tier=cache_tier,
            versions=versions,
            query=cache_query,
            loader=_load_signal_payload,
            force_refresh=force_refresh,
        )
    except (PublicCacheBusy, DatabasePoolBusy) as exc:
        return _public_busy_response(exc)
    return _public_json_response(
        result,
        tier=cache_tier,
        dataset_version=versions.get(DATASET_SIGNALS, 0),
    )

def api_trends():
    active_city, wards, sources, prop_types, only_drops, trend_period, mos_min = get_base_filters(request)
    range_kwargs = _request_range_filter_kwargs(request)
    if not wards and active_city in CITY_MAP:
        wards = CITY_MAP[active_city]
    db_path = _db_handle()
    tier = current_tier()
    include_guland_high_activity = _include_guland_high_activity(request, tier)
    return jsonify({
        "trend_data": load_trend_data(
            db_path,
            sources,
            wards,
            prop_types,
            only_drops,
            trend_period,
            include_guland_high_activity=include_guland_high_activity,
            **range_kwargs,
        ),
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
        "l.price_per_m2 < 1000",
        publisher_visibility_sql(
            "l",
            include_high_activity=_include_guland_high_activity(
                request,
                current_tier(),
            ),
        ),
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
    tier = current_tier()
    return jsonify(load_market_indicators(
        db_path,
        sources=sources,
        wards=wards,
        prop_types=prop_types,
        include_guland_high_activity=_include_guland_high_activity(
            request,
            tier,
        ),
        **range_kwargs,
    ))


@rate_limit("valuation_tool", limits={"guest": 60, "free": 120, "vip": None, "admin": None})
def api_valuation_tool_estimate():
    payload = request.get_json(silent=True) or {}
    try:
        return jsonify(estimate_property_value(payload, tier=current_tier()))
    except ValuationToolError as exc:
        return jsonify({"ok": False, "error": "validation_error", "field": str(exc)}), 422


@rate_limit("listings")
def api_listings():
    active_city, wards, sources, prop_types, only_drops, trend_period, mos_min = get_base_filters(request)
    range_kwargs = _request_range_filter_kwargs(request)
    keyword = _request_keyword(request)
    date_range = _request_date_range(request)
    complete_only = (request.args.get("complete") or "").strip().lower() in {"1", "true", "yes", "on"}
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
    
    tier = current_tier()
    include_guland_high_activity = _include_guland_high_activity(request, tier)
    where_sql, params = build_listing_filters(
        sources=sources,
        wards=wards,
        prop_types=prop_types,
        only_drops=only_drops,
        prefix="l.",
        keyword=keyword,
        date_range=date_range,
        require_complete=complete_only,
        include_guland_high_activity=include_guland_high_activity,
        **range_kwargs,
    )

    actual_expr = "COALESCE(v.actual_ppm2, sv.actual_ppm2, l.price_per_m2)"
    display_fair_expr = _display_fair_sql("v", "sv")
    display_mos_expr = _display_mos_sql("v", "sv", actual_expr)
    old_signal_condition = actionable_signal_sql("v")
    new_signal_condition = actionable_signal_sql("sv")
    signal_condition = f"({old_signal_condition}) AND ({new_signal_condition})"
    sort_col_map = {
        "area": "l.area_m2", "price": "l.price_ty", "price_m2": "l.price_per_m2",
        "fair": f"({display_fair_expr})", "date": listing_activity_at_sql("l"),
        "ward": "l.ward", "prop_type": "l.property_type",
    }
    # Default sort = newest first (date DESC). Client can override.
    sort_by = request.args.get("sort_by", "date")
    default_dir = "desc" if sort_by == "date" else "asc"
    sort_dir = "DESC" if request.args.get("sort_dir", default_dir).lower() == "desc" else "ASC"
    order_expr = sort_col_map.get(sort_by, listing_activity_at_sql("l"))

    fresh_flag = "0 AS is_fresh_locked"
    query = f"""
        WITH {LATEST_VALUATION_CTE},
             {LATEST_SHADOW_VALUATION_CTE}
        SELECT l.*,
               {listing_activity_at_sql("l")} AS activity_at,
               CASE WHEN {signal_condition} THEN 1 ELSE 0 END AS is_signal,
               ({display_mos_expr}) AS mos_pct,
               ({display_fair_expr}) AS fair_ppm2,
               v.fair_ppm2 AS fair_ppm2_old,
               sv.fair_ppm2 AS fair_ppm2_new,
               v.mos_pct AS mos_pct_old,
               sv.mos_pct AS mos_pct_new,
               ({display_fair_expr}) AS fair_ppm2_display,
               ({display_mos_expr}) AS mos_pct_display,
               GREATEST(COALESCE(v.signal_score,0), COALESCE(sv.signal_score,0)) AS signal_score,
               CASE WHEN {signal_condition} THEN 1 ELSE 0 END AS actionable_signal,
               {fresh_flag}
        FROM listings l
        LEFT JOIN latest_valuation v ON l.id = v.listing_id
        LEFT JOIN latest_shadow_valuation sv ON l.id = sv.listing_id
        WHERE {where_sql}
        ORDER BY {publisher_sort_rank_sql('l')} ASC,
                 {order_expr} {sort_dir} NULLS LAST
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
        activity_at, card_date_reason = listing_card_activity(r)
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
            "fair_ppm2_old": round(r["fair_ppm2_old"], 1) if r.get("fair_ppm2_old") else None,
            "fair_ppm2_new": round(r["fair_ppm2_new"], 1) if r.get("fair_ppm2_new") else None,
            "mos_pct_old": round(r["mos_pct_old"], 1) if r.get("mos_pct_old") else 0,
            "mos_pct_new": round(r["mos_pct_new"], 1) if r.get("mos_pct_new") else 0,
            "fair_ppm2_display": round(r["fair_ppm2_display"], 1) if r.get("fair_ppm2_display") else (round(r["fair_ppm2"], 1) if r["fair_ppm2"] else None),
            "mos_pct_display": round(r["mos_pct_display"], 1) if r.get("mos_pct_display") else (round(r["mos_pct"], 1) if r["mos_pct"] else 0),
            "days_ago": _days_ago(activity_at), "card_date_reason": card_date_reason,
            "is_hot": bool(r['is_hot']), "price_dropped": price_dropped,
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


@rate_limit(
    "listing_map",
    limits={"guest": 300, "free": 600, "vip": None, "admin": None},
)
def api_map_listings():
    mode = (request.args.get("mode") or "").strip().lower()
    if mode not in {"signals", "all"}:
        return jsonify({"error": "invalid_mode"}), 400
    tier = current_tier()
    payload = load_listing_map_summary(
        mode=mode,
        tier=tier,
        filters=_listing_map_filters(request, mode),
    )
    return jsonify(_safe_listing_map_payload(payload, tier))


@rate_limit(
    "listing_map",
    limits={"guest": 300, "free": 600, "vip": None, "admin": None},
)
def api_map_listing_items():
    mode = (request.args.get("mode") or "").strip().lower()
    if mode not in {"signals", "all"}:
        return jsonify({"error": "invalid_mode"}), 400
    location_key = (request.args.get("location_key") or "").strip()
    if (
        not location_key
        or len(location_key) > 240
        or not _LISTING_MAP_LOCATION_KEY_RE.fullmatch(location_key)
    ):
        return jsonify({"error": "invalid_location_key"}), 400
    try:
        page = int(request.args.get("page", 1))
        limit = int(request.args.get("limit", 20))
    except (TypeError, ValueError):
        return jsonify({"error": "invalid_pagination"}), 400
    if page < 1 or limit < 1:
        return jsonify({"error": "invalid_pagination"}), 400
    tier = current_tier()
    payload = load_listing_map_items(
        mode=mode,
        tier=tier,
        filters=_listing_map_filters(request, mode),
        location_key=location_key,
        page=page,
        limit=min(limit, 50),
    )
    return jsonify(_safe_listing_map_payload(payload, tier))

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

    return render_template(
        'listing_detail.html',
        l=l,
        imgs=imgs,
        history_json=history_json,
        desc_html=desc_html,
        memo=memo,
        map_location=data.get("map_location"),
    )

def api_listing_detail(listing_id):
    db_path = _db_handle()
    data = load_listing_detail(db_path, listing_id, tier=current_tier())
    if not data:
        return jsonify({"error": "not found"}), 404

    l = data["listing"]
    activity_at, card_date_reason = listing_card_activity(l)
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
        "fair_ppm2_old": round(l["fair_ppm2_old"], 1) if l.get("fair_ppm2_old") else None,
        "fair_ppm2_new": round(l["fair_ppm2_new"], 1) if l.get("fair_ppm2_new") else None,
        "mos_pct_old": round(l["mos_pct_old"], 1) if l.get("mos_pct_old") else 0,
        "mos_pct_new": round(l["mos_pct_new"], 1) if l.get("mos_pct_new") else 0,
        "fair_ppm2_display": round(l["fair_ppm2_display"], 1) if l.get("fair_ppm2_display") else (round(l["fair_ppm2"], 1) if l["fair_ppm2"] else None),
        "mos_pct_display": round(l["mos_pct_display"], 1) if l.get("mos_pct_display") else (round(l["mos_pct"], 1) if l["mos_pct"] else 0),
        "signal_model": l.get("signal_model") or "legacy",
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
        "days_ago": _days_ago(activity_at),
        "card_date_reason": card_date_reason,
        "imgs": data["images"],
        "map_location": data.get("map_location"),
        "tier": data.get("tier"),
    })

def api_listing_memo(listing_id):
    tier = current_tier()
    if tier == "guest":
        return jsonify({"locked": True, "reason": "login_required"}), 403

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
        curr = conn.execute("""
            SELECT source, posted_at, crawled_at, updated_at, price_updated_at,
                   price_ty, ward, area_m2, property_type, road_tier,
                   price_per_m2, title, url
            FROM listings
            WHERE id = ?
        """, (listing_id,)).fetchone()
        cluster_ids = _listing_cluster_ids(conn, listing_id)
        placeholders = ",".join("?" for _ in cluster_ids)
        rows = conn.execute(f"""
            WITH ranked_snapshots AS (
                SELECT ph.id, ph.listing_id, ph.recorded_at, ph.price_ty, ph.price_per_m2,
                       CASE
                           WHEN l.source='guland' THEN ph.recorded_at
                           ELSE COALESCE(
                               NULLIF(l.posted_at, ''),
                               ph.recorded_at,
                               l.crawled_at,
                               l.updated_at
                           )
                       END AS history_date,
                       l.url, l.source,
                       ROW_NUMBER() OVER (
                           PARTITION BY ph.listing_id,
                               CASE
                                   WHEN l.source='guland' THEN CAST(ph.id AS TEXT)
                                   ELSE substr(ph.recorded_at, 1, 10)
                               END
                           ORDER BY ph.recorded_at DESC, ph.id DESC
                       ) AS same_day_rank
                FROM price_history ph
                LEFT JOIN listings l ON l.id = ph.listing_id
                WHERE ph.listing_id IN ({placeholders})
            )
            SELECT listing_id, recorded_at, price_ty, price_per_m2,
                   history_date, url, source
            FROM ranked_snapshots
            WHERE same_day_rank = 1
            ORDER BY history_date ASC, recorded_at ASC, id ASC
        """, list(cluster_ids)).fetchall()
        history = []
        last_price = None
        has_last = False
        for r in rows:
            price_ty = r["price_ty"]
            same_as_last = has_last and _same_price_value(price_ty, last_price)
            if same_as_last:
                continue
            item = {'date': (r["history_date"] or '')[:10], 'price_ty': price_ty}
            if r["source"] == "guland":
                item["recorded_at"] = r["recorded_at"] or ""
            if tier == "admin" and r["url"]:
                item["url"] = r["url"]
            history.append(item)
            last_price = price_ty
            has_last = True

        if curr and curr["price_ty"]:
            current_price = curr["price_ty"]
            if not history or not _same_price_value(history[-1]['price_ty'], current_price):
                item = {
                    'date': (
                        curr["price_updated_at"]
                        or curr["posted_at"]
                        or curr["crawled_at"]
                        or curr["updated_at"]
                        or ''
                    )[:10],
                    'price_ty': current_price,
                    'is_current': True,
                }
                if curr["source"] == "guland":
                    item["recorded_at"] = (
                        curr["price_updated_at"]
                        or curr["crawled_at"]
                        or curr["updated_at"]
                        or ""
                    )
                if tier == "admin" and curr["url"]:
                    item["url"] = curr["url"]
                history.append(item)

        # Shared compact card payload used by both detail surfaces.
        comps = load_listing_comparables(conn, listing_id, tier=tier, limit=18)

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
    return pair.issubset({"nha_dat", "nha_tro"})


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
    is_json_request = request.is_json
    if is_json_request:
        request_payload = request.get_json(silent=True) or {}
        return_path = ""
    else:
        request_payload = request.form.to_dict(flat=True)
        return_path = request_payload.pop("return_path", "")
    payload, status = admin_leads.create_lead(
        request_payload,
        tier=current_tier(),
        user=current_user(),
        audit_log_fn=log_audit,
    )
    if status < 400:
        clear_admin_read_cache("leads")
        clear_admin_read_cache("growth")
    if not is_json_request:
        parsed = urllib.parse.urlsplit(return_path)
        safe_path = parsed.path if (
            not parsed.scheme
            and not parsed.netloc
            and parsed.path.startswith("/")
            and not parsed.path.startswith("//")
            and "\\" not in parsed.path
            and not any(ord(char) < 32 for char in parsed.path)
        ) else "/bao-cao"
        lead_status = "success" if status < 400 and payload.get("ok") else "error"
        return redirect(f"{safe_path}?lead={lead_status}", code=303)
    return jsonify(payload), status


@rate_limit("lead_capture", limits={"guest": 10, "free": 30, "vip": 120, "admin": None})
def api_create_guest_lead():
    payload, status = admin_leads.create_guest_lead(
        request.get_json(silent=True) or {},
        tier=current_tier(),
        user=current_user(),
        audit_log_fn=log_audit,
    )
    if status < 400:
        clear_admin_read_cache("leads")
        clear_admin_read_cache("growth")
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


def _facebook_profiles_payload() -> dict:
    profiles = _read_facebook_profile_config()
    stats = _facebook_profile_stats([profile["url"] for profile in profiles])
    shaped = []
    for profile in profiles:
        item = dict(profile)
        profile_stat = stats.get(profile["url"]) or admin_quality.empty_facebook_profile_stat()
        item.update(profile_stat)
        item.update(admin_quality.facebook_profile_due_metadata(profile, profile_stat))
        shaped.append(item)
    return {
        "profiles": shaped,
        "revision": admin_quality.facebook_profile_revision(profiles),
    }


@require_admin_auth
def admin_api_facebook_crawl_overview():
    payload = admin_quality.facebook_crawl_overview(
        schedule_status_fn=_daily_crawl_schedule_status,
        crawl_ops_summary_fn=_crawl_ops_summary,
        active_job_fn=_active_facebook_crawl_job,
        recent_jobs_fn=lambda limit: [
            _public_crawl_job(job)
            for job in admin_job_service.POSTGRES_ADMIN_JOBS.list(limit=limit)
        ],
        apify_tokens_fn=_apify_tokens_public,
    )
    return jsonify(payload)


@require_admin_auth
def admin_api_facebook_crawl_profiles():
    if request.method == "GET":
        return jsonify(_cached_admin_read_payload(
            "facebook_crawl_profiles",
            "default",
            _facebook_profiles_payload,
            ttl_seconds=10,
        ))

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "invalid_payload"}), 400
    profiles = payload.get("profiles")
    expected_revision = str(payload.get("revision") or "").strip()
    if not isinstance(profiles, list) or not re.fullmatch(r"[0-9a-f]{64}", expected_revision):
        return jsonify({"ok": False, "error": "invalid_profile_payload"}), 400

    with get_conn() as conn:
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtext(?))",
            ("radar-facebook-profile-config",),
        )
        locked_conn_factory = _single_connection_factory(conn)
        current_profiles = _read_facebook_profile_config(conn_factory=locked_conn_factory)
        current_revision = admin_quality.facebook_profile_revision(current_profiles)
        if expected_revision != current_revision:
            return jsonify({
                "ok": False,
                "error": "profile_revision_conflict",
                "revision": current_revision,
                "profiles": current_profiles,
            }), 409
        saved = _write_facebook_profile_config(profiles, conn_factory=locked_conn_factory)

    _clear_admin_crawl_data_caches()
    clear_admin_read_cache("facebook_crawl_profiles")
    response = _facebook_profiles_payload()
    response["ok"] = True
    return jsonify(response)


@require_admin_auth
def admin_api_facebook_crawl_duplicates():
    actionable_raw = (request.args.get("actionable") or "1").strip()
    if actionable_raw not in {"0", "1"}:
        return jsonify({"error": "invalid_actionable"}), 400
    try:
        offset = int(request.args.get("offset") or 0)
    except (TypeError, ValueError):
        return jsonify({"error": "invalid_offset"}), 400
    if offset < 0:
        return jsonify({"error": "invalid_offset"}), 400
    limit = _clamp_int(request.args.get("limit"), 20, 1, 50)
    city = (request.args.get("city") or "").strip()[:100]
    profiles = _read_facebook_profile_config()
    stats = _facebook_profile_stats([profile["url"] for profile in profiles])
    analysis = _facebook_profile_duplicate_analysis(profiles, stats)
    return jsonify(admin_quality.paginate_facebook_duplicate_analysis(
        analysis,
        actionable=actionable_raw == "1",
        city=city,
        limit=limit,
        offset=offset,
    ))


@require_admin_auth
def admin_api_facebook_crawl_config():
    if request.method == "GET":
        def _load_payload():
            profiles = _read_facebook_profile_config()
            stats = _facebook_profile_stats([p["url"] for p in profiles])
            duplicate_analysis = _facebook_profile_duplicate_analysis(profiles, stats)
            for profile in profiles:
                profile.update(stats.get(profile["url"], {}))
                profile["duplicate_overlap"] = duplicate_analysis["by_profile"].get(profile["url"])
            return {
                "profiles": profiles,
                "duplicate_comparisons": duplicate_analysis["comparisons"],
                "summary": _facebook_crawl_summary(),
                "apify_tokens": _apify_tokens_public(),
            }

        return jsonify(_cached_admin_read_payload("facebook_crawl_config", "default", _load_payload, ttl_seconds=10))

    payload = request.get_json(silent=True) or {}
    profiles = payload.get("profiles") or []
    clear_admin_read_cache("facebook_crawl_config")
    saved = _write_facebook_profile_config(profiles)
    stats = _facebook_profile_stats([p["url"] for p in saved])
    duplicate_analysis = _facebook_profile_duplicate_analysis(saved, stats)
    for profile in saved:
        profile.update(stats.get(profile["url"], {}))
        profile["duplicate_overlap"] = duplicate_analysis["by_profile"].get(profile["url"])
    return jsonify({
        "ok": True,
        "profiles": saved,
        "duplicate_comparisons": duplicate_analysis["comparisons"],
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
        clear_admin_read_cache("facebook_crawl_config")
        clear_admin_read_cache("data_quality_summary")
        return jsonify({"ok": True, "tokens": tokens})
    if request.method == "DELETE":
        if not token_id:
            return jsonify({"ok": False, "error": "token_id_required"}), 400
        ok = delete_token(token_id)
        clear_admin_read_cache("facebook_crawl_config")
        clear_admin_read_cache("data_quality_summary")
        return jsonify({"ok": ok, "tokens": _apify_tokens_public()})
    if request.method == "PATCH":
        if not token_id:
            return jsonify({"ok": False, "error": "token_id_required"}), 400
        action = (request.get_json(silent=True) or {}).get("action")
        if action == "reset_usage":
            ok = reset_token_usage(token_id)
            clear_admin_read_cache("facebook_crawl_config")
            clear_admin_read_cache("data_quality_summary")
            return jsonify({"ok": ok, "tokens": _apify_tokens_public()})
        return jsonify({"ok": False, "error": "invalid_action"}), 400
    return jsonify({"ok": False, "error": "method_not_allowed"}), 405


@require_admin_auth
def admin_api_facebook_crawl_run():
    payload = request.get_json(silent=True) or {}
    url = admin_quality.normalize_facebook_profile_url(
        payload.get("url") or payload.get("profile_url")
    )
    if not url:
        return jsonify({"ok": False, "error": "invalid_profile_url"}), 400
    mode = (payload.get("mode") or "daily").strip().lower()
    if mode not in {"first", "daily", "range"}:
        return jsonify({"ok": False, "error": "invalid_mode"}), 400

    active = _active_facebook_crawl_job()
    if active:
        return jsonify({"ok": False, "error": "crawl_already_running", "job": _public_crawl_job(active)}), 409

    configured = _facebook_profile_lookup(url) or {}
    limit_default = 330 if mode == "first" else configured.get("daily_limit", 30)
    limit = _clamp_int(payload.get("limit"), limit_default, 1, FACEBOOK_MANUAL_CRAWL_MAX_LIMIT)
    days = _clamp_int(payload.get("days"), configured.get("range_days", 7), 1, 60)
    job = {
        "id": uuid4().hex[:12],
        "kind": "facebook_crawl",
        "status": "queued",
        "stage": "queued",
        "mode": mode,
        "profile_url": url,
        "broker_name": (payload.get("broker_name") or configured.get("broker_name") or "").strip(),
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
        "context": {
            "city": (payload.get("city") or configured.get("city") or "").strip(),
        },
        "created_by": "admin",
    }
    try:
        created = _enqueue_facebook_crawl_job(job, _run_admin_facebook_crawl_job) or job
    except AdminJobAlreadyActive as exc:
        return jsonify({
            "ok": False,
            "error": "crawl_already_running",
            "job": _public_crawl_job(exc.active_job),
        }), 409
    clear_admin_read_cache("facebook_crawl_config")
    clear_admin_read_cache("data_quality_summary")
    clear_admin_read_cache("growth")
    return jsonify({"ok": True, "job": _public_crawl_job(created)})


@require_admin_auth
def admin_api_facebook_crawl_maintenance():
    payload = request.get_json(silent=True) or {}
    action = (payload.get("action") or "").strip().lower()
    if action not in {"reprocess", "valuation_only"}:
        return jsonify({"ok": False, "error": "invalid_action"}), 400

    active = _active_facebook_crawl_job()
    if active:
        return jsonify({"ok": False, "error": "crawl_already_running", "job": _public_crawl_job(active)}), 409

    label = "valuation-only" if action == "valuation_only" else "manual reprocess"
    job = {
        "id": uuid4().hex[:12],
        "kind": "crawl_maintenance",
        "status": "queued",
        "stage": "queued",
        "mode": label,
        "profile_url": "",
        "broker_name": "Maintenance",
        "limit": None,
        "days": None,
        "download_images": False,
        "maintenance_action": action,
        "created_at": _utc_iso_z(),
        "started_at": None,
        "finished_at": None,
        "progress_pct": 0,
        "progress_label": "Đang chờ chạy",
        "stats": {},
        "logs": [],
        "context": {},
        "created_by": "admin",
    }
    try:
        created = _enqueue_facebook_crawl_job(job, _run_admin_crawl_maintenance_job) or job
    except AdminJobAlreadyActive as exc:
        return jsonify({
            "ok": False,
            "error": "crawl_already_running",
            "job": _public_crawl_job(exc.active_job),
        }), 409
    clear_admin_read_cache("facebook_crawl_config")
    clear_admin_read_cache("data_quality_summary")
    clear_admin_read_cache("growth")
    return jsonify({"ok": True, "job": _public_crawl_job(created)})


@require_admin_auth
def admin_api_facebook_crawl_jobs(job_id=None):
    admin_job_service.POSTGRES_ADMIN_JOBS.reconcile_stale()
    if job_id:
        job = admin_job_service.POSTGRES_ADMIN_JOBS.get(job_id)
        if not job:
            return jsonify({"ok": False, "error": "not_found"}), 404
        return jsonify({"job": _public_crawl_job(job)})
    jobs = admin_job_service.POSTGRES_ADMIN_JOBS.list(limit=20)
    return jsonify({"jobs": [_public_crawl_job(job) for job in jobs]})

@require_admin_auth
def admin_api_growth():
    period = (request.args.get("period") or "day").strip().lower()
    if period not in admin_growth.VALID_PERIODS:
        return jsonify({"error": "invalid_period"}), 400
    anchor_value = (request.args.get("anchor") or datetime.now().date().isoformat()).strip()
    try:
        anchor = datetime.strptime(anchor_value, "%Y-%m-%d").date()
    except ValueError:
        return jsonify({"error": "invalid_anchor"}), 400
    include_value = (request.args.get("include_guland") or "0").strip()
    if include_value not in {"0", "1"}:
        return jsonify({"error": "invalid_include_guland"}), 400
    cache_key = (period, anchor.isoformat(), include_value)
    return jsonify(_cached_admin_read_payload(
        "growth",
        cache_key,
        lambda: admin_growth.get_growth_dashboard(
            period=period,
            anchor=anchor,
            include_guland=include_value == "1",
        ),
        ttl_seconds=30,
    ))


@require_admin_auth
def admin_api_leads():
    status = (request.args.get("status") or "").strip()
    q = (request.args.get("q") or "").strip()
    return jsonify(_cached_admin_read_payload(
        "leads",
        (status, q),
        lambda: admin_leads.list_leads(status=status, q=q),
        ttl_seconds=10,
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
    if status < 400:
        clear_admin_read_cache("leads")
        clear_admin_read_cache("growth")
    return jsonify(result), status


@require_admin_auth
def admin_api_delete_lead(lead_id):
    result, status = admin_leads.delete_lead(lead_id, audit_writer=_write_admin_audit)
    if status < 400:
        clear_admin_read_cache("leads")
        clear_admin_read_cache("growth")
    return jsonify(result), status


@require_admin_auth
def admin_api_infra():
    if request.method == "GET":
        kind = (request.args.get("kind") or "").strip()
        only_active = request.args.get("active", "1") != "0"
        if kind and kind not in INFRA_KINDS:
            return jsonify({"ok": False, "error": "invalid_kind"}), 400

        def _load_infra_payload():
            where = []
            params = []
            if kind:
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
            return {"items": items}

        return jsonify(_cached_admin_read_payload("infra", (kind, only_active), _load_infra_payload, ttl_seconds=10))

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
            clear_admin_read_cache("infra")
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
    clear_admin_read_cache("infra")
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
        clear_admin_read_cache("infra")
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
    clear_admin_read_cache("infra")
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

    def _load_payload():
        with db_mod.get_conn() as conn:
            signal_condition = actionable_signal_sql("v")
            where = [
                "COALESCE(l.probably_sold,0)=0",
                "COALESCE(l.is_blacklisted,0)=0",
                signal_condition,
                "COALESCE(v.mos_pct,0) BETWEEN ? AND ?",
            ]
            params = [mos_min, mos_max]
            if ward:
                where.append("l.ward = ?")
                params.append(ward)
            if source:
                where.append("l.source = ?")
                params.append(source)
            rows = conn.execute(f"""
                WITH {LATEST_VALUATION_CTE},
                latest_feedback AS (
                    SELECT DISTINCT ON (af.listing_id) af.*
                    FROM ai_training_feedback af
                    ORDER BY af.listing_id, af.created_at DESC, af.id DESC
                )
                SELECT l.id, l.title, l.url, l.ward, l.source, l.price_ty, l.area_m2,
                       l.property_type, l.price_dropped, l.possibly_duplicate,
                       COALESCE(v.mos_pct,0) AS mos_pct, COALESCE(v.signal_score,0) AS signal_score,
                       f.verdict, f.created_at AS feedback_at
                FROM listings l
                JOIN latest_valuation v ON v.listing_id = l.id
                LEFT JOIN latest_feedback f ON f.listing_id = l.id
                WHERE {" AND ".join(where)}
                ORDER BY COALESCE(v.signal_score,0) DESC, COALESCE(v.mos_pct,0) DESC
                LIMIT 500
            """, params).fetchall()
        return {"items": [dict(r) for r in rows]}

    return jsonify(_cached_admin_read_payload("qc_signals", (mos_min, mos_max, ward, source), _load_payload, ttl_seconds=15))


@require_admin_auth
def admin_api_data_quality_summary():
    return jsonify(_cached_admin_read_payload(
        "data_quality_summary",
        "default",
        _data_quality_summary,
        ttl_seconds=15,
    ))


@require_admin_auth
def admin_api_data_quality_download_missing_images():
    payload = request.get_json(silent=True) or {}
    active = _active_facebook_crawl_job()
    if active:
        return jsonify({"ok": False, "error": "crawl_already_running", "job": _public_crawl_job(active)}), 409

    limit = _clamp_int(payload.get("limit"), 500, 1, 5000)
    job = {
        "id": uuid4().hex[:12],
        "kind": "missing_image_backfill",
        "status": "queued",
        "stage": "queued",
        "mode": "download missing images",
        "source": "",
        "profile_url": "",
        "broker_name": "Data Quality",
        "limit": limit,
        "days": None,
        "download_images": True,
        "maintenance_action": "download_missing_images",
        "created_at": _utc_iso_z(),
        "started_at": None,
        "finished_at": None,
        "progress_pct": 0,
        "progress_label": "Đang chờ tải ảnh thiếu",
        "stats": {},
        "logs": [],
        "context": {},
        "created_by": "admin",
    }
    try:
        created = _enqueue_facebook_crawl_job(job, _run_admin_data_quality_image_job) or job
    except AdminJobAlreadyActive as exc:
        return jsonify({
            "ok": False,
            "error": "crawl_already_running",
            "job": _public_crawl_job(exc.active_job),
        }), 409
    clear_admin_read_cache("facebook_crawl_config")
    clear_admin_read_cache("data_quality_summary")
    return jsonify({"ok": True, "job": _public_crawl_job(created)})


@require_admin_auth
def admin_api_data_quality_retry_source_crawl():
    payload = request.get_json(silent=True) or {}
    source = (payload.get("source") or "").strip().lower()
    if source not in {"facebook", "guland"}:
        return jsonify({"ok": False, "error": "invalid_source"}), 400

    active = _active_facebook_crawl_job()
    if active:
        return jsonify({"ok": False, "error": "crawl_already_running", "job": _public_crawl_job(active)}), 409

    job = {
        "id": uuid4().hex[:12],
        "kind": "source_retry",
        "status": "queued",
        "stage": "queued",
        "mode": f"retry {source}",
        "source": source,
        "profile_url": "",
        "broker_name": f"Retry {source}",
        "limit": None,
        "days": None,
        "download_images": True,
        "maintenance_action": "retry_source_crawl",
        "created_at": _utc_iso_z(),
        "started_at": None,
        "finished_at": None,
        "progress_pct": 0,
        "progress_label": "Đang chờ crawl lại nguồn",
        "stats": {},
        "logs": [],
        "context": {},
        "created_by": "admin",
    }
    try:
        created = _enqueue_facebook_crawl_job(job, _run_admin_source_retry_job) or job
    except AdminJobAlreadyActive as exc:
        return jsonify({
            "ok": False,
            "error": "crawl_already_running",
            "job": _public_crawl_job(exc.active_job),
        }), 409
    clear_admin_read_cache("facebook_crawl_config")
    clear_admin_read_cache("data_quality_summary")
    clear_admin_read_cache("growth")
    return jsonify({"ok": True, "job": _public_crawl_job(created)})


@require_admin_auth
def admin_api_guland_publishers():
    activity_class = (
        request.args.get("activity_class") or ""
    ).strip().lower()
    limit = _clamp_int(request.args.get("limit"), 50, 1, 200)
    offset = _clamp_int(request.args.get("offset"), 0, 0, 1_000_000)
    try:
        with get_conn() as conn:
            payload = list_publishers(
                conn,
                activity_class=activity_class,
                limit=limit,
                offset=offset,
            )
    except ValueError:
        return jsonify({
            "ok": False,
            "error": "invalid_publisher_activity_class",
        }), 400
    return jsonify({"ok": True, **payload})


@require_admin_auth
def admin_api_guland_publisher_override(publisher_id: int):
    payload = request.get_json(silent=True) or {}
    override = str(payload.get("override") or "").strip()
    if override not in {"", "allow_manual", "hide_high_activity"}:
        return jsonify({
            "ok": False,
            "error": "invalid_publisher_override",
        }), 400
    try:
        with get_conn() as conn:
            result = set_publisher_override(
                conn,
                publisher_id,
                override,
                _admin_profile_config_actor(),
            )
    except ValueError as exc:
        if "not found" in str(exc).lower():
            return jsonify({
                "ok": False,
                "error": "publisher_not_found",
            }), 404
        return jsonify({
            "ok": False,
            "error": "invalid_publisher_override",
        }), 400

    clear_local_public_cache()
    clear_listing_map_cache()
    clear_admin_read_cache("data_quality_summary")
    return jsonify({"ok": True, **result})


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
    clear_admin_read_cache("data_quality_summary")
    clear_admin_read_cache("duplicates")
    clear_admin_read_cache("qc_signals")
    clear_admin_read_cache("training_disagreements")
    return jsonify({"ok": True, **result})


@require_admin_auth
def admin_api_ai_training_items():
    return _admin_review_items_response(allowed_queues=("main",), default_queue="main")


@require_admin_auth
def admin_api_data_quality_items():
    def _load_payload():
        response = _admin_review_items_response(
            allowed_queues=("source_qc", "legal_qc"),
            default_queue="source_qc",
        )
        return response.get_json()

    cache_key = request.query_string.decode("utf-8", "replace") or "default"
    return jsonify(_cached_admin_read_payload("data_quality_items", cache_key, _load_payload, ttl_seconds=8))


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
    if queue == "source_qc":
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
            LEFT JOIN latest_feedback f ON f.listing_id = l.id
            LEFT JOIN legal_verifications lv ON lv.listing_id = l.id
    """
    review_count_cte = f"""
            {LATEST_VALUATION_CTE},
            latest_feedback AS MATERIALIZED (
                SELECT DISTINCT ON (af.listing_id) af.*
                FROM ai_training_feedback af
                ORDER BY af.listing_id, af.created_at DESC, af.id DESC
            )
    """
    review_read_cte = f"""
            {LATEST_VALUATION_CTE},
            latest_feedback AS MATERIALIZED (
                SELECT DISTINCT ON (af.listing_id) af.*
                FROM ai_training_feedback af
                ORDER BY af.listing_id, af.created_at DESC, af.id DESC
            ),
            latest_review AS MATERIALIZED (
                SELECT DISTINCT ON (ar.listing_id) ar.*
                FROM ai_deal_review ar
                ORDER BY ar.listing_id, ar.created_at DESC, ar.id DESC
            )
    """

    with db_mod.get_conn() as conn:
        rows = conn.execute(f"""
            WITH {review_read_cte}
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
            LEFT JOIN latest_review r ON r.listing_id = l.id
            WHERE {where_sql}
            ORDER BY {order_sql}
            LIMIT ? OFFSET ?
        """, params + [limit, offset]).fetchall()

        if queue in ("source_qc", "needs_valuation", "legal_qc"):
            pending = None
        else:
            pending = conn.execute(f"""
                WITH {review_count_cte}
                SELECT COUNT(*) c
                FROM listings l
                JOIN latest_valuation v ON v.listing_id = l.id
                {feedback_join}
                WHERE {where_sql} AND f.id IS NULL
            """, params).fetchone()["c"]

        total = conn.execute(f"""
            WITH {review_count_cte}
            SELECT COUNT(*) c
            FROM listings l
            JOIN latest_valuation v ON v.listing_id = l.id
            {feedback_join}
            WHERE {where_sql}
        """, params).fetchone()["c"]
        if queue in ("source_qc", "needs_valuation", "legal_qc"):
            pending = total

        ward_where = [
            "COALESCE(l.probably_sold,0)=0",
            "COALESCE(l.is_blacklisted,0)=0",
            "l.ward IS NOT NULL",
            "l.ward <> ''",
        ]
        ward_params = []
        if queue == "source_qc":
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

        def _load_ward_payload():
            ward_rows = conn.execute(f"""
                WITH {review_count_cte}
                SELECT DISTINCT l.ward
                FROM listings l
                JOIN latest_valuation v ON v.listing_id = l.id
                {feedback_join}
                WHERE {" AND ".join(ward_where)}
                ORDER BY l.ward
            """, ward_params).fetchall()
            available_wards = [w["ward"] for w in ward_rows]
            available_cities = {c: [ww for ww in ws if ww in available_wards] for c, ws in CITY_MAP.items()}
            available_cities = {c: ws for c, ws in available_cities.items() if ws}
            return {"wards": available_wards, "ward_cities": available_cities}

        ward_payload = _cached_admin_read_payload("data_quality_item_wards", queue, _load_ward_payload, ttl_seconds=60)
        wards = ward_payload["wards"]
        ward_cities = ward_payload["ward_cities"]

        image_urls_by_listing: dict[int, list[str]] = {}
        listing_ids = [r["id"] for r in rows]
        if listing_ids:
            placeholders = ",".join("?" * len(listing_ids))
            image_rows = conn.execute(f"""
                SELECT listing_id, local_path, img_url
                FROM listing_images
                WHERE listing_id IN ({placeholders})
                ORDER BY listing_id, {_image_order_sql()}
            """, listing_ids).fetchall()
            for im in image_rows:
                u = resolve_image_url(im["local_path"], im["img_url"])
                if u:
                    image_urls_by_listing.setdefault(im["listing_id"], []).append(u)

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
            gallery = image_urls_by_listing.get(d["id"], [])
            d["images"] = gallery
            d["image"] = gallery[0] if gallery else resolve_image_url("", "")
            d["detail_url"] = f"/listing/{d['id']}"
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
            "Guland QC" if queue == "source_qc"
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
    clear_admin_read_cache("data_quality_summary")
    clear_admin_read_cache("qc_signals")
    return jsonify({"ok": True, "legal_summary": {**result, "conflict_flags": flags_text}})


@require_admin_auth
def admin_api_ai_training_disagreements():
    """Read-only: nơi nhãn người (f) và verdict Claude (r) xung đột bucket.

    Lọc CHẶT — chỉ hiện khi cả hai phía đã có nhãn latest VÀ bucket ngược nhau;
    `maybe` / `insufficient_info` (NEUTRAL) tự loại. Chỉ surfacing, KHÔNG ghi.
    """
    def _load_payload():
        with db_mod.get_conn() as conn:
            rows = conn.execute("""
                WITH latest_valuation AS (
                    SELECT DISTINCT ON (vr.listing_id) vr.*
                    FROM valuation_results vr
                    ORDER BY vr.listing_id, vr.computed_at DESC, vr.id DESC
                ),
                latest_feedback AS (
                    SELECT DISTINCT ON (f.listing_id) f.*
                    FROM ai_training_feedback f
                    ORDER BY f.listing_id, f.created_at DESC, f.id DESC
                ),
                latest_review AS (
                    SELECT DISTINCT ON (r.listing_id) r.*
                    FROM ai_deal_review r
                    ORDER BY r.listing_id, r.created_at DESC, r.id DESC
                )
                SELECT l.id, l.title, l.url, l.ward, l.price_ty, l.area_m2,
                       v.mos_pct, v.signal_score,
                       f.verdict AS human_verdict, f.created_at AS human_at,
                       r.verdict AS ai_verdict, r.confidence AS ai_confidence,
                       r.reasoning AS ai_reasoning, r.red_flags AS ai_red_flags,
                       r.needs_map_check AS ai_needs_map_check
                FROM listings l
                JOIN latest_valuation v ON v.listing_id = l.id
                JOIN latest_feedback f ON f.listing_id = l.id
                JOIN latest_review r ON r.listing_id = l.id
                WHERE (
                       (f.verdict IN ('good','correct','cheap_real')
                            AND r.verdict IN ('suspect','not_cheap'))
                    OR (f.verdict IN ('bad','spam','sold','fake_price','bad_data','fair','overpriced','cannot_price')
                            AND r.verdict = 'cheap_real')
                )
                ORDER BY COALESCE(r.confidence,0) DESC, v.signal_score DESC
                LIMIT 200
            """).fetchall()
        return {"items": [dict(r) for r in rows]}

    return jsonify(_cached_admin_read_payload("training_disagreements", "default", _load_payload, ttl_seconds=15))


@require_admin_auth
def admin_api_qc_duplicates():
    def _load_payload():
        with db_mod.get_conn() as conn:
            items = _admin_duplicate_review_items(conn)
            groups = _admin_duplicate_review_groups(items)
        return {"items": items, "groups": groups}

    return jsonify(_cached_admin_read_payload("duplicates", "review", _load_payload, ttl_seconds=15))


def _admin_duplicate_review_items(conn) -> list[dict]:
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
          AND NOT EXISTS (
            SELECT 1
            FROM dedup_overrides o
            WHERE o.active=1
              AND o.action='merge'
              AND o.listing_id=l.id
              AND o.target_listing_id=c.id
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
    return items


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


def _admin_duplicate_member_from_item(item: dict, *, canonical: bool = False) -> dict:
    prefix = "canonical_" if canonical else ""
    return {
        "id": item.get("duplicate_of_id") if canonical else item.get("id"),
        "source": item.get(f"{prefix}source"),
        "source_id": item.get(f"{prefix}source_id"),
        "url": item.get(f"{prefix}url"),
        "title": item.get(f"{prefix}title"),
        "ward": item.get(f"{prefix}ward"),
        "property_type": item.get(f"{prefix}property_type"),
        "price_ty": item.get(f"{prefix}price_ty"),
        "area_m2": item.get(f"{prefix}area_m2"),
        "frontage_m": item.get(f"{prefix}frontage_m"),
        "depth_m": item.get(f"{prefix}depth_m"),
        "tho_cu_m2": item.get(f"{prefix}tho_cu_m2"),
        "road_name": item.get(f"{prefix}road_name"),
        "dt": item.get(f"{prefix}dt"),
        "detail_url": item.get("canonical_detail_url") if canonical else item.get("detail_url"),
        "image": item.get("canonical_image") if canonical else item.get("image"),
        "description_excerpt": item.get("canonical_description_excerpt") if canonical else item.get("description_excerpt"),
    }


def _admin_duplicate_review_groups(items: list[dict]) -> list[dict]:
    parent: dict[int, int] = {}

    def find(node: int) -> int:
        parent.setdefault(node, node)
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(a: int, b: int) -> None:
        root_a, root_b = find(a), find(b)
        if root_a != root_b:
            parent[root_a] = root_b

    for item in items:
        try:
            union(int(item["id"]), int(item["duplicate_of_id"]))
        except (KeyError, TypeError, ValueError):
            continue

    components: dict[int, dict] = {}
    for item in items:
        try:
            listing_id = int(item["id"])
            target_id = int(item["duplicate_of_id"])
        except (KeyError, TypeError, ValueError):
            continue
        root = find(listing_id)
        component = components.setdefault(
            root,
            {
                "pairs": [],
                "members": {},
                "incoming": {},
                "qc_reasons": [],
                "suspected_duplicate": False,
                "first_seen": len(components),
            },
        )
        component["pairs"].append(item)
        component["incoming"][target_id] = component["incoming"].get(target_id, 0) + 1
        component["members"][listing_id] = _admin_duplicate_member_from_item(item)
        component["members"][target_id] = _admin_duplicate_member_from_item(item, canonical=True)
        component["suspected_duplicate"] = component["suspected_duplicate"] or bool(item.get("suspected_duplicate"))
        for reason in item.get("qc_reasons") or []:
            if reason not in component["qc_reasons"]:
                component["qc_reasons"].append(reason)

    groups = []
    for component in components.values():
        members_by_id = component["members"]
        if len(members_by_id) < 2:
            continue
        default_target_id = max(
            members_by_id,
            key=lambda member_id: (component["incoming"].get(member_id, 0), member_id),
        )
        members = sorted(
            members_by_id.values(),
            key=lambda member: (member["id"] != default_target_id, -int(member["id"] or 0)),
        )
        member_ids = sorted(int(member["id"]) for member in members if member.get("id"))
        groups.append({
            "group_id": f"dup-{member_ids[0]}-{member_ids[-1]}",
            "default_target_id": default_target_id,
            "member_count": len(members),
            "pair_count": len(component["pairs"]),
            "members": members,
            "pairs": component["pairs"],
            "qc_reasons": component["qc_reasons"],
            "suspected_duplicate": component["suspected_duplicate"],
            "_first_seen": component["first_seen"],
        })

    groups.sort(key=lambda group: (group["_first_seen"], -group["member_count"]))
    for group in groups:
        group.pop("_first_seen", None)
    return groups


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
          AND property_type IN ('dat_nen','nha_dat','nha_tro')
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
        return a == b

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
        type_keys = ["dat_land"] if prop == "dat_nen" else [prop]
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


def _hydrate_duplicate_canonical(conn, target_id: int, listing_ids: list[int]) -> None:
    source_ids = [int(value) for value in listing_ids if value and int(value) != int(target_id)]
    if not target_id or not source_ids:
        return

    fields = [
        "title",
        "description",
        "ward",
        "property_type",
        "area_m2",
        "frontage_m",
        "depth_m",
        "tho_cu_m2",
        "road_name",
        "road_type",
        "road_width_m",
        "price_ty",
        "price_per_m2",
        "price_first_ty",
    ]
    select_fields = ", ".join(fields)
    target = conn.execute(
        f"SELECT id, {select_fields} FROM listings WHERE id=?",
        (target_id,),
    ).fetchone()
    if not target:
        return
    placeholders = ",".join("?" for _ in source_ids)
    sources = conn.execute(
        f"""
        SELECT id, {select_fields}, COALESCE(posted_at, crawled_at, updated_at) AS dt
        FROM listings
        WHERE id IN ({placeholders})
        ORDER BY COALESCE(posted_at, crawled_at, updated_at) DESC, id DESC
        """,
        source_ids,
    ).fetchall()

    def has_value(value):
        if value is None:
            return False
        if isinstance(value, str):
            return bool(value.strip())
        try:
            return float(value) != 0
        except (TypeError, ValueError):
            return True

    updates = {}
    for field in fields:
        if has_value(target[field]):
            continue
        for source in sources:
            value = source[field]
            if has_value(value):
                updates[field] = value
                break

    if "price_per_m2" not in updates and not has_value(target["price_per_m2"]):
        price = updates.get("price_ty", target["price_ty"])
        area = updates.get("area_m2", target["area_m2"])
        if has_value(price) and has_value(area):
            updates["price_per_m2"] = round(float(price) * 1000 / float(area), 3)

    if not updates:
        return
    set_sql = ", ".join(f"{field}=?" for field in updates)
    conn.execute(
        f"UPDATE listings SET {set_sql}, updated_at=datetime('now') WHERE id=?",
        [*updates.values(), target_id],
    )


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
        _hydrate_duplicate_canonical(conn, target_id, [listing_id])
        _write_admin_audit(
            conn,
            "dedup_merge",
            "listing",
            listing_id,
            before=dict(before) if before else None,
            after={"id": listing_id, "possibly_duplicate": 1, "duplicate_of_id": target_id},
            reason=note or "merge",
        )
    clear_admin_read_cache("duplicates")
    clear_admin_read_cache("data_quality_summary")
    clear_admin_read_cache("qc_signals")
    return jsonify({"ok": True})


@require_admin_auth
def admin_api_qc_duplicates_merge_bulk():
    payload = request.get_json(silent=True) or {}
    target_id = int(payload.get("target_listing_id") or 0)
    note = (payload.get("note") or "").strip()[:500]
    try:
        listing_ids = [int(value) for value in (payload.get("listing_ids") or [])]
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "invalid_ids"}), 400
    listing_ids = list(dict.fromkeys([listing_id for listing_id in listing_ids if listing_id and listing_id != target_id]))
    if not target_id or not listing_ids:
        return jsonify({"ok": False, "error": "invalid_ids"}), 400

    with db_mod.get_conn() as conn:
        groups = _admin_duplicate_review_groups(_admin_duplicate_review_items(conn))
        group = None
        for candidate in groups:
            member_ids = {int(member["id"]) for member in candidate.get("members") or [] if member.get("id")}
            if target_id in member_ids and set(listing_ids).issubset(member_ids):
                group = candidate
                break
        if not group:
            return jsonify({"ok": False, "error": "not_in_duplicate_review_group"}), 400

        merged = 0
        for listing_id in listing_ids:
            before = conn.execute(
                "SELECT id, possibly_duplicate, duplicate_of_id FROM listings WHERE id=?",
                (listing_id,),
            ).fetchone()
            if not before:
                continue
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
                "dedup_bulk_merge",
                "listing",
                listing_id,
                before=dict(before) if before else None,
                after={"id": listing_id, "possibly_duplicate": 1, "duplicate_of_id": target_id},
                reason=note or "bulk_merge",
            )
            merged += 1
        _hydrate_duplicate_canonical(conn, target_id, listing_ids)
    clear_admin_read_cache("duplicates")
    clear_admin_read_cache("data_quality_summary")
    clear_admin_read_cache("qc_signals")
    return jsonify({"ok": True, "merged": merged, "target_listing_id": target_id, "listing_ids": listing_ids})


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
    clear_admin_read_cache("duplicates")
    clear_admin_read_cache("data_quality_summary")
    clear_admin_read_cache("qc_signals")
    return jsonify({"ok": True})


@require_admin_auth
def admin_api_blacklist():
    if request.method == "GET":
        def _load_payload():
            with db_mod.get_conn() as conn:
                rows = conn.execute("""
                    SELECT id, phone_norm, reason, active, created_at, updated_at
                    FROM broker_blacklist
                    ORDER BY updated_at DESC
                """).fetchall()
            return {"items": [dict(r) for r in rows]}

        return jsonify(_cached_admin_read_payload("blacklist", "default", _load_payload, ttl_seconds=10))

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
        clear_admin_read_cache("blacklist")
        clear_admin_read_cache("data_quality_summary")
        clear_admin_read_cache("duplicates")
        clear_admin_read_cache("qc_signals")
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
    clear_admin_read_cache("blacklist")
    clear_admin_read_cache("data_quality_summary")
    clear_admin_read_cache("duplicates")
    clear_admin_read_cache("qc_signals")
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

    def _load_payload():
        with db_mod.get_conn() as conn:
            rows = conn.execute(f"""
                SELECT id, created_at, actor, action, entity_type, entity_id,
                       before_json, after_json, reason
                FROM admin_audit_log
                {where_sql}
                ORDER BY created_at DESC, id DESC
                LIMIT 200
            """, params).fetchall()
        return {"items": [dict(r) for r in rows]}

    return jsonify(_cached_admin_read_payload("audit", (entity_type, entity_id or ""), _load_payload, ttl_seconds=10))


# ═══════════════════════════════════════════════════════════════════════════
# Admin: User management (grant/revoke VIP, ban)
# ═══════════════════════════════════════════════════════════════════════════
@require_admin_auth
def admin_api_users():
    tier_filter = (request.args.get("tier") or "").strip()
    q = (request.args.get("q") or "").strip()
    return jsonify(_cached_admin_read_payload(
        "users",
        (tier_filter, q),
        lambda: admin_users.list_users(
            tier_filter=tier_filter,
            q=q,
            effective_tier_fn=_effective_tier_from_user,
        ),
        ttl_seconds=10,
    ))


@require_admin_auth
def admin_api_delete_user(user_id):
    actor = current_user() or {}
    result, status = admin_users.delete_user(
        user_id,
        actor_id=actor.get("id"),
        audit_writer=_write_admin_audit,
    )
    if status < 400:
        clear_admin_read_cache("users")
        clear_admin_read_cache("growth")
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
    if status < 400:
        clear_admin_read_cache("users")
    return jsonify(result), status


@require_admin_auth
def admin_api_revoke_vip(user_id):
    result, status = admin_users.revoke_vip(
        user_id,
        audit_writer=_write_admin_audit,
        log_audit_fn=log_audit,
    )
    if status < 400:
        clear_admin_read_cache("users")
    return jsonify(result), status


@require_admin_auth
def admin_api_ban_user(user_id):
    payload = request.get_json(silent=True) or {}
    result, status = admin_users.set_banned(
        user_id,
        bool(payload.get("banned", True)),
        audit_writer=_write_admin_audit,
    )
    if status < 400:
        clear_admin_read_cache("users")
        clear_admin_read_cache("growth")
    return jsonify(result), status


@rate_limit("assistant_chat", limits={"guest": 40, "free": 160, "vip": 500, "admin": None})
def api_chat():
    payload = request.get_json(silent=True) or {}
    message = (payload.get("message") or "").strip()
    if not message:
        return jsonify({"ok": False, "error": "empty_message"}), 400
    response = build_assistant_response(
        message,
        session_id=payload.get("session_id"),
        page_context=payload.get("page_context") or {},
        current_filters=payload.get("current_filters") or {},
        tier=current_tier(),
        user=current_user(),
    )
    return jsonify(response)

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
