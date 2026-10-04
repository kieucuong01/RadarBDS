"""Admin crawl and data-quality service helpers.

These functions keep DB-heavy admin summaries out of ``app.py`` while allowing
the Flask layer to inject patchable callbacks for tests.
"""
from __future__ import annotations

import json
import hashlib
import logging
import os
import platform
import re
import subprocess
import tempfile
from collections import Counter, defaultdict
from itertools import combinations
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import parse_qs, urlsplit

from db.connection import get_conn
from services.signal_quality import (
    LATEST_VALUATION_CTE,
    actionable_listing_sql,
    actionable_signal_sql,
    split_quality_flags,
)

logger = logging.getLogger(__name__)
FACEBOOK_PROFILE_SAMPLE_LIMIT = max(5, min(200, int(os.getenv("RADAR_FACEBOOK_PROFILE_SAMPLE_LIMIT", "100"))))


def clamp_int(value, default: int, min_value: int, max_value: int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = default
    return max(min_value, min(max_value, n))


def normalize_crawl_every_days(value) -> int:
    try:
        cadence = int(value)
    except (TypeError, ValueError):
        return 1
    return cadence if cadence in {1, 3, 7} else 1


def read_facebook_profile_config(path: Path) -> list[dict]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    profiles: list[dict] = []
    if isinstance(data, dict):
        iterable = ((city, items) for city, items in data.items())
    elif isinstance(data, list):
        iterable = ((None, data),)
    else:
        iterable = ()
    for city, items in iterable:
        for item in items or []:
            if isinstance(item, str):
                raw = {"url": item}
            elif isinstance(item, dict):
                raw = dict(item)
            else:
                continue
            url = (raw.get("url") or "").strip()
            if not url:
                continue
            tier = clamp_int(raw.get("daily_limit", raw.get("tier")), 20, 1, 500)
            profiles.append({
                "city": (raw.get("city") or city or "").strip(),
                "url": url,
                "broker_name": (raw.get("broker_name") or "").strip(),
                "tier": tier,
                "daily_limit": tier,
                "range_days": clamp_int(raw.get("range_days"), 7, 1, 60),
                "crawl_every_days": normalize_crawl_every_days(raw.get("crawl_every_days")),
                "active": raw.get("active", True) is not False,
            })
    return normalize_facebook_profiles(profiles)


def write_facebook_profile_config(path: Path, profiles: list[dict]) -> list[dict]:
    cleaned = normalize_facebook_profiles(profiles)
    grouped: dict[str, list[dict]] = {}
    for item in cleaned:
        output = dict(item)
        city = output.pop("city") or "Bình Dương"
        grouped.setdefault(city, []).append(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(grouped, ensure_ascii=False, indent=2) + "\n"
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
            newline="\n",
        ) as handle:
            temp_path = Path(handle.name)
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path and temp_path.exists():
            temp_path.unlink()
    return read_facebook_profile_config(path)


def facebook_profile_lookup(url: str, profiles: Iterable[dict]) -> dict | None:
    normalized = normalize_facebook_profile_url(url)
    for profile in profiles:
        if normalize_facebook_profile_url(profile.get("url")) == normalized:
            return profile
    return None


def empty_facebook_profile_stat() -> dict:
    return {
        "raw_count": 0,
        "stats_status": "ok",
        "latest_received_at": None,
        "last_crawl": None,
        "last_successful_crawl_at": None,
        "crawl_history_status": "ok",
        "latest_crawled_at": None,
        "activity": {
            "posts_7d": 0,
            "posts_14d": 0,
            "posts_30d": 0,
            "active_days_30d": 0,
            "avg_posts_per_active_day_14d": 0.0,
            "avg_posts_per_day_30d": 0.0,
            "avg_posts_per_week_30d": 0.0,
            "recommended_daily_limit": 10,
            "recommended_weekly_limit": 30,
            "cadence_label": "Chưa có dữ liệu",
            "cadence_tier": "muted",
            "confidence": "low",
            "dated_posts": 0,
            "undated_posts": 0,
        },
        "data_quality": {
            "score": None,
            "status": "empty",
            "label": "Chưa đủ mẫu",
            "tier": "muted",
            "sample_size": 0,
            "price_pct": 0.0,
            "area_pct": 0.0,
            "ward_pct": 0.0,
            "property_type_pct": 0.0,
            "image_pct": 0.0,
            "description_pct": 0.0,
            "serious_flag_pct": 0.0,
            "reasons": ["Chưa đủ dữ liệu để đánh giá"],
        },
    }


def parse_crawl_datetime(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if not text:
            return None
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            try:
                dt = datetime.strptime(text[:19], "%Y-%m-%d %H:%M:%S")
            except ValueError:
                return None
    if dt.tzinfo:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def raw_has_images(raw: dict) -> bool:
    candidates = [
        raw.get("imgs"),
        raw.get("images"),
        raw.get("image_urls"),
        raw.get("img_urls"),
        raw.get("photos"),
    ]
    apify_raw = raw.get("_apify_raw")
    if isinstance(apify_raw, dict):
        candidates.extend([
            apify_raw.get("imgs"),
            apify_raw.get("images"),
            apify_raw.get("image_urls"),
            apify_raw.get("photos"),
        ])
    for value in candidates:
        if isinstance(value, list) and any(str(item or "").strip() for item in value):
            return True
        if isinstance(value, str) and value.strip():
            return True
    return False


def present_text(*values) -> bool:
    return any(str(value or "").strip() for value in values)


def pct(part: int, total: int) -> float:
    return round((part / total) * 100, 1) if total else 0.0


def facebook_profile_activity(rows: list[dict]) -> dict:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    dated: list[datetime] = []
    for item in rows:
        raw = item.get("raw") or {}
        dt = parse_crawl_datetime(item.get("posted_at") or raw.get("date_raw"))
        if dt and dt <= now:
            dated.append(dt)
    posts_7d = sum(1 for dt in dated if dt >= now - timedelta(days=7))
    posts_14d = sum(1 for dt in dated if dt >= now - timedelta(days=14))
    posts_30d = sum(1 for dt in dated if dt >= now - timedelta(days=30))
    business_tz = timezone(timedelta(hours=7))
    days_14 = {dt.replace(tzinfo=timezone.utc).astimezone(business_tz).date() for dt in dated if dt >= now - timedelta(days=14)}
    days_30 = {dt.replace(tzinfo=timezone.utc).astimezone(business_tz).date() for dt in dated if dt >= now - timedelta(days=30)}
    active_days_14d = len(days_14)
    active_days_30d = len(days_30)
    avg_active_14d = round(posts_14d / active_days_14d, 1) if active_days_14d else 0.0
    avg_day_30d = round(posts_30d / 30, 1) if posts_30d else 0.0
    avg_week_30d = round(posts_30d / 30 * 7, 1) if posts_30d else 0.0
    recommended_daily = max(10, min(120, int(round(max(avg_active_14d, avg_day_30d) * 1.35 + 5))))
    recommended_weekly = max(30, min(500, int(round(avg_week_30d * 1.25 + 10))))
    if not dated:
        label, tier, confidence = "Chưa có dữ liệu", "muted", "low"
    elif posts_30d == 0:
        label, tier, confidence = "Ít hoạt động", "muted", "low"
    elif active_days_30d >= 18 or avg_active_14d >= 12:
        label, tier, confidence = "Nhịp cao", "strong", "high"
    elif active_days_30d >= 8 or posts_30d >= 20:
        label, tier, confidence = "Ổn định", "good", "medium"
    else:
        label, tier, confidence = "Rải rác", "warn", "medium"
    return {
        "posts_7d": posts_7d,
        "posts_14d": posts_14d,
        "posts_30d": posts_30d,
        "active_days_30d": active_days_30d,
        "avg_posts_per_active_day_14d": avg_active_14d,
        "avg_posts_per_day_30d": avg_day_30d,
        "avg_posts_per_week_30d": avg_week_30d,
        "recommended_daily_limit": recommended_daily,
        "recommended_weekly_limit": recommended_weekly,
        "cadence_label": label,
        "cadence_tier": tier,
        "confidence": confidence,
        "dated_posts": len(dated),
        "undated_posts": len(rows) - len(dated),
    }


def facebook_profile_data_quality(rows: list[dict]) -> dict:
    serious_flags = {
        "parsed_discount_as_price",
        "too_low_absolute_price",
        "down_payment_as_price",
        "area_dimension_conflict",
        "source_category_conflict",
        "missing_area_evidence",
        "ambiguous_price_text",
        "multi_lot_listing",
    }
    counters = Counter()
    sample = 0
    for item in rows:
        raw = item.get("raw") or {}
        text = " ".join(str(x or "") for x in [
            item.get("title"),
            item.get("description"),
            raw.get("title"),
            raw.get("description"),
            raw.get("text"),
            raw.get("post_text"),
        ]).strip()
        sample += 1
        if (item.get("price_ty") or 0) > 0 or present_text(raw.get("price"), raw.get("price_ty"), raw.get("price_text")):
            counters["price"] += 1
        if (item.get("area_m2") or 0) > 0 or present_text(raw.get("area"), raw.get("area_m2"), raw.get("area_text")):
            counters["area"] += 1
        if present_text(item.get("ward"), raw.get("ward"), raw.get("area"), raw.get("location")):
            counters["ward"] += 1
        if present_text(item.get("property_type"), raw.get("property_type"), raw.get("category")):
            counters["property_type"] += 1
        if item.get("image_count", 0) > 0 or raw_has_images(raw):
            counters["image"] += 1
        if len(text) >= 80:
            counters["description"] += 1
        flags = set(split_quality_flags(item.get("source_quality_flags") or ""))
        if flags & serious_flags:
            counters["serious_flags"] += 1
    if sample < 5:
        return {
            "score": None,
            "status": "insufficient" if sample else "empty",
            "label": "Chưa đủ mẫu",
            "tier": "muted",
            "sample_size": sample,
            "price_pct": pct(counters["price"], sample),
            "area_pct": pct(counters["area"], sample),
            "ward_pct": pct(counters["ward"], sample),
            "property_type_pct": pct(counters["property_type"], sample),
            "image_pct": pct(counters["image"], sample),
            "description_pct": pct(counters["description"], sample),
            "serious_flag_pct": pct(counters["serious_flags"], sample),
            "reasons": ["Cần thêm bài đã crawl để đánh giá chắc hơn"],
        }
    price_pct = pct(counters["price"], sample)
    area_pct = pct(counters["area"], sample)
    ward_pct = pct(counters["ward"], sample)
    property_pct = pct(counters["property_type"], sample)
    image_pct = pct(counters["image"], sample)
    description_pct = pct(counters["description"], sample)
    serious_pct = pct(counters["serious_flags"], sample)
    score = round(
        price_pct * 0.24
        + area_pct * 0.24
        + ward_pct * 0.18
        + property_pct * 0.10
        + image_pct * 0.12
        + description_pct * 0.12
        - serious_pct * 0.35
    )
    score = max(0, min(100, int(score)))
    if score >= 82:
        label, tier = "Dữ liệu sạch", "strong"
    elif score >= 68:
        label, tier = "Dữ liệu ổn", "good"
    elif score >= 52:
        label, tier = "Thiếu thông tin", "warn"
    else:
        label, tier = "Khó parse", "danger"
    reasons = []
    if price_pct < 80:
        reasons.append("hay thiếu giá")
    if area_pct < 80:
        reasons.append("hay thiếu diện tích")
    if ward_pct < 75:
        reasons.append("thiếu khu vực/phường")
    if image_pct < 60:
        reasons.append("ít ảnh")
    if serious_pct >= 15:
        reasons.append("nhiều lỗi parse giá/diện tích")
    if not reasons:
        reasons.append("đủ trường chính, dễ parse")
    return {
        "score": score,
        "status": "ready",
        "label": label,
        "tier": tier,
        "sample_size": sample,
        "price_pct": price_pct,
        "area_pct": area_pct,
        "ward_pct": ward_pct,
        "property_type_pct": property_pct,
        "image_pct": image_pct,
        "description_pct": description_pct,
        "serious_flag_pct": serious_pct,
        "reasons": reasons[:3],
    }


def _facebook_profile_key_sql(expression: str) -> str:
    """Match canonical profile roots, including numeric profile.php identities."""
    return rf"""LOWER(CASE
        WHEN {expression} ~* '^https://(www[.]|m[.])?facebook[.]com/profile[.]php[?]'
        THEN 'https://www.facebook.com/profile.php?id=' || SUBSTRING({expression} FROM '[?&]id=([0-9]+)')
        ELSE REGEXP_REPLACE({expression},
            '^https://(www[.]|m[.])?facebook[.]com/([^/?#]+).*$',
            'https://www.facebook.com/\2', 'i') END)"""


def facebook_profile_stats(profile_urls: list[str], conn_factory=get_conn) -> dict:
    """Keep lifetime metadata separate from bounded per-broker quality samples."""
    stats = {url: empty_facebook_profile_stat() for url in profile_urls}
    urls_by_key = defaultdict(list)
    for url in profile_urls:
        key = normalize_facebook_profile_url(url).lower()
        if key:
            urls_by_key[key].append(url)
    if not urls_by_key:
        return stats
    keys = list(urls_by_key)
    profile_key_sql = _facebook_profile_key_sql("source_url")
    grouped = {key: [] for key in keys}
    raw_id_keys = {}
    try:
        with conn_factory() as conn:
            history = conn.execute("""
                WITH source_profiles AS MATERIALIZED (
                    SELECT r.id, r.crawled_at, fields.date_raw AS posted_at,
                           COALESCE(NULLIF(fields._apify_raw ->> 'inputUrl', ''),
                                    NULLIF(fields.profile_url, '')) AS source_url
                    FROM raw_listings r
                    CROSS JOIN LATERAL JSON_TO_RECORD(r.raw_json::json)
                        AS fields(profile_url TEXT, date_raw TEXT, _apify_raw JSON)
                    WHERE r.source = 'facebook'
                ), profile_raw AS MATERIALIZED (
                    SELECT id, crawled_at, posted_at, """ + profile_key_sql + """ AS profile_url
                    FROM source_profiles
                )
                SELECT profile_url, COUNT(*) AS raw_count,
                       MAX(crawled_at) AS latest_received_at,
                       (ARRAY_AGG(id ORDER BY crawled_at DESC, id DESC))[1:?] AS sample_raw_ids,
                       ARRAY_AGG(posted_at) AS posted_dates
                FROM profile_raw WHERE profile_url = ANY(?)
                GROUP BY profile_url
            """, (FACEBOOK_PROFILE_SAMPLE_LIMIT, keys)).fetchall()
            for row in history:
                key = row["profile_url"]
                raw_id_keys.update({rid: key for rid in row["sample_raw_ids"]})
                activity = facebook_profile_activity([
                    {"posted_at": value} for value in row["posted_dates"]
                ])
                for url in urls_by_key[key]:
                    stats[url].update({
                        "raw_count": int(row["raw_count"]),
                        "latest_received_at": row["latest_received_at"],
                        # Compatibility for legacy admin surfaces and duplicate ranking.
                        "latest_crawled_at": row["latest_received_at"],
                        "activity": activity,
                    })
            rows = []
            if raw_id_keys:
                rows = conn.execute("""
                    WITH recent_raw AS MATERIALIZED (
                        SELECT r.id, JSONB_STRIP_NULLS(TO_JSONB(fields)) AS raw_json, r.crawled_at
                        FROM raw_listings r
                        CROSS JOIN LATERAL JSON_TO_RECORD(r.raw_json::json) AS fields(
                            title TEXT, description TEXT, text TEXT, post_text TEXT,
                            price TEXT, price_ty TEXT, price_text TEXT, area TEXT,
                            area_m2 TEXT, area_text TEXT, ward TEXT, location TEXT,
                            property_type TEXT, category TEXT, imgs JSON, images JSON,
                            image_urls JSON, img_urls JSON, photos JSON)
                        WHERE r.id = ANY(?)
                    ), recent_listing AS MATERIALIZED (
                        SELECT r.id AS raw_id, r.raw_json, r.crawled_at, l.id AS listing_id,
                               l.title, l.description, l.price_ty, l.area_m2, l.ward, l.property_type
                        FROM recent_raw r LEFT JOIN listings l ON l.raw_id = r.id
                    ), image_counts AS MATERIALIZED (
                        SELECT img.listing_id, COUNT(*) AS image_count
                        FROM listing_images img JOIN recent_listing rl ON rl.listing_id = img.listing_id
                        GROUP BY img.listing_id
                    ), latest_quality AS MATERIALIZED (
                        SELECT DISTINCT ON (v.listing_id) v.listing_id, v.source_quality_flags
                        FROM valuation_results v JOIN recent_listing rl ON rl.listing_id = v.listing_id
                        ORDER BY v.listing_id, v.id DESC
                    )
                    SELECT rl.*, COALESCE(img.image_count, 0) AS image_count, q.source_quality_flags
                    FROM recent_listing rl
                    LEFT JOIN image_counts img ON img.listing_id = rl.listing_id
                    LEFT JOIN latest_quality q ON q.listing_id = rl.listing_id
                """, (list(raw_id_keys),)).fetchall()
            for row in rows:
                item = dict(row.items())
                raw = item.pop("raw_json") or {}
                item["raw"] = raw if isinstance(raw, dict) else json.loads(raw)
                grouped[raw_id_keys[item["raw_id"]]].append(item)
    except Exception as exc:
        logger.warning("Facebook profile statistics unavailable: %s", type(exc).__name__)
        for stat in stats.values():
            stat["stats_status"] = "unavailable"
            stat["data_quality"].update({"status": "unavailable", "label": "Thống kê lỗi"})
        return stats
    for key, items in grouped.items():
        processed = [item for item in items if item["listing_id"] is not None]
        quality = facebook_profile_data_quality(processed)
        quality["unprocessed_count"] = len(items) - len(processed)
        if items and len(processed) < 5 and quality["unprocessed_count"]:
            quality.update({"status": "pending", "label": "Chưa xử lý đủ mẫu",
                            "reasons": ["Còn bài chưa chuẩn hóa trong mẫu đánh giá"]})
        sample_dates = [parse_crawl_datetime(item["crawled_at"]) for item in items]
        latest = max((value for value in sample_dates if value), default=None)
        quality["latest_sample_at"] = latest.isoformat() + "Z" if latest else None
        quality["is_stale"] = bool(latest and latest < datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=30))
        for url in urls_by_key[key]:
            stats[url]["data_quality"] = quality
    # Job-history failure must not discard otherwise valid listing statistics.
    try:
        with conn_factory() as conn:
            run_key_sql = _facebook_profile_key_sql("profile_url")
            runs = conn.execute("""
                WITH runs AS (
                    SELECT profile_url, status, started_at, finished_at,
                           CASE WHEN COALESCE(stats -> 'crawl' ->> 'crawl_partial', 'false') = 'true'
                                THEN 'partial' ELSE status END AS result
                    FROM admin_jobs WHERE kind = 'facebook_crawl' AND started_at IS NOT NULL
                    UNION ALL
                    SELECT p.target_url, p.status, NULLIF(c.started_at, '')::timestamptz,
                           NULLIF(p.completed_at, '')::timestamptz, p.status
                    FROM crawl_run_progress p JOIN crawl_runs c ON c.id = p.run_id
                    WHERE c.source = 'facebook' AND p.status IN ('done', 'error')
                ), normalized AS (
                    SELECT """ + run_key_sql + """ AS profile_key, result AS status,
                           started_at, finished_at FROM runs
                )
                SELECT DISTINCT ON (profile_key) profile_key, status, started_at, finished_at,
                       MAX(started_at) FILTER (WHERE status IN ('done', 'succeeded'))
                           OVER (PARTITION BY profile_key) AS last_successful_crawl_at
                FROM normalized WHERE profile_key = ANY(?)
                ORDER BY profile_key, started_at DESC
            """, (keys,)).fetchall()
            for row in runs:
                crawl = {name: row[name] for name in ("status", "started_at", "finished_at")}
                for url in urls_by_key[row["profile_key"]]:
                    stats[url]["last_crawl"] = crawl
                    stats[url]["last_successful_crawl_at"] = row["last_successful_crawl_at"]
    except Exception as exc:
        logger.warning("Facebook profile crawl history unavailable: %s", type(exc).__name__)
        for stat in stats.values():
            stat["crawl_history_status"] = "unavailable"
    return stats


_FACEBOOK_PROFILE_RESERVED_PATHS = frozenset({
    "about",
    "ads",
    "business",
    "events",
    "groups",
    "help",
    "login",
    "marketplace",
    "pages",
    "photo",
    "photos",
    "reel",
    "reels",
    "share",
    "story.php",
    "watch",
})


def normalize_facebook_profile_url(value) -> str:
    """Return one canonical HTTPS Facebook profile root or an empty string."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    if raw.lower().startswith(("facebook.com/", "www.facebook.com/", "m.facebook.com/")):
        raw = f"https://{raw}"
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return ""
    hostname = (parsed.hostname or "").lower()
    if parsed.scheme.lower() != "https" or hostname not in {
        "facebook.com",
        "www.facebook.com",
        "m.facebook.com",
    }:
        return ""
    segments = [segment for segment in parsed.path.split("/") if segment]
    if not segments:
        return ""
    first = segments[0].strip()
    if not first:
        return ""
    if first.casefold() == "profile.php":
        profile_id = (parse_qs(parsed.query).get("id") or [""])[0].strip()
        if not profile_id.isdigit():
            return ""
        return f"https://www.facebook.com/profile.php?id={profile_id}"
    if first.casefold() in _FACEBOOK_PROFILE_RESERVED_PATHS:
        return ""
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", first):
        return ""
    return f"https://www.facebook.com/{first}"


def normalize_facebook_profiles(profiles) -> list[dict]:
    """Normalize and deduplicate an untrusted profile collection."""
    if not isinstance(profiles, list):
        return []
    normalized: list[dict] = []
    seen: set[str] = set()
    for raw in profiles:
        if not isinstance(raw, dict):
            continue
        url = normalize_facebook_profile_url(raw.get("url"))
        if not url or url in seen:
            continue
        seen.add(url)
        daily_limit = clamp_int(raw.get("daily_limit", raw.get("tier")), 20, 1, 500)
        normalized.append({
            "city": str(raw.get("city") or "Bình Dương").strip()[:100],
            "url": url,
            "broker_name": str(raw.get("broker_name") or "").strip()[:160],
            "tier": daily_limit,
            "daily_limit": daily_limit,
            "range_days": clamp_int(raw.get("range_days"), 7, 1, 60),
            "crawl_every_days": normalize_crawl_every_days(raw.get("crawl_every_days")),
            "active": raw.get("active", True) is not False,
        })
    return normalized


def facebook_profile_revision(profiles: list[dict]) -> str:
    """Hash normalized semantic content, independent of ordering/key layout."""
    normalized = normalize_facebook_profiles(profiles)
    ordered = sorted(normalized, key=lambda item: item["url"])
    payload = json.dumps(
        ordered,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def facebook_profile_due_metadata(
    profile: dict,
    stat: dict,
    *,
    today: date | None = None,
) -> dict:
    """Expose the same stable cadence buckets used by the scheduled crawler."""
    from crawler.facebook_apify import facebook_crawl_today, profile_due_on

    current_day = today or facebook_crawl_today()
    cadence = normalize_crawl_every_days(profile.get("crawl_every_days"))
    next_due = current_day
    for offset in range(cadence):
        candidate = current_day + timedelta(days=offset)
        if profile_due_on(profile, candidate):
            next_due = candidate
            break
    return {
        "due_today": profile_due_on(profile, current_day),
        "next_due_date": next_due.isoformat(),
    }


def paginate_facebook_duplicate_analysis(
    analysis: dict,
    *,
    actionable: bool = True,
    city: str = "",
    limit: int = 20,
    offset: int = 0,
) -> dict:
    comparisons = list((analysis or {}).get("comparisons") or [])
    actionable_items = [
        item for item in comparisons
        if item.get("recommended_crawl_every_days") in {3, 7}
    ]
    filtered = actionable_items if actionable else comparisons
    clean_city = str(city or "").strip().casefold()
    if clean_city:
        filtered = [
            item for item in filtered
            if str(item.get("city") or "").strip().casefold() == clean_city
        ]
    safe_limit = clamp_int(limit, 20, 1, 50)
    safe_offset = max(0, int(offset or 0))
    return {
        "total": len(comparisons),
        "actionable": len(actionable_items),
        "filtered": len(filtered),
        "limit": safe_limit,
        "offset": safe_offset,
        "items": filtered[safe_offset:safe_offset + safe_limit],
    }


def facebook_crawl_overview(
    *,
    schedule_status_fn: Callable[[], dict],
    crawl_ops_summary_fn: Callable[[], dict],
    active_job_fn: Callable[[], dict | None],
    recent_jobs_fn: Callable[[int], list[dict]],
    apify_tokens_fn: Callable[[], list[dict]],
    profile_stats_fn=None,
    duplicate_analysis_fn=None,
) -> dict:
    """Build the light initial payload without profile or duplicate queries."""
    schedule = schedule_status_fn() or {}
    ops = crawl_ops_summary_fn() or {}
    active_job = active_job_fn()
    recent_jobs = recent_jobs_fn(1) or []
    tokens = apify_tokens_fn() or []
    enabled_tokens = [
        token for token in tokens
        if token.get("active", token.get("enabled", True))
    ]
    problems = []
    if not schedule.get("installed"):
        problems.append({
            "code": "schedule_missing",
            "label": "Lịch crawl chưa hoạt động",
        })
    for source_error in ops.get("source_errors") or []:
        problems.append({
            "code": "source_error",
            "label": f"Nguồn {source_error.get('source') or 'không rõ'} đang lỗi",
        })
    for blocker in ops.get("lock_blockers") or []:
        problems.append({
            "code": "lock_blocker",
            "label": f"Tác vụ {blocker.get('name') or 'không rõ'} đang giữ khóa",
        })
    if not enabled_tokens:
        problems.append({
            "code": "apify_unavailable",
            "label": "Không có Apify token khả dụng",
        })
    last_run = ops.get("last_run")
    return {
        "schedule": schedule,
        "last_facebook_run": (
            last_run if last_run and last_run.get("source") == "facebook" else None
        ),
        "latest_job": recent_jobs[0] if recent_jobs else None,
        "active_job": active_job,
        "apify": {
            "enabled_tokens": len(enabled_tokens),
            "total_tokens": len(tokens),
        },
        "problems": problems,
    }


def build_facebook_duplicate_analysis(
    profiles: list[dict],
    stats: dict,
    rows: list[dict],
) -> dict:
    configured: dict[str, dict] = {}
    ordered_urls: list[str] = []
    for profile in profiles:
        url = normalize_facebook_profile_url(profile.get("url"))
        if not url or url in configured:
            continue
        configured[url] = {**profile, "url": url}
        ordered_urls.append(url)

    clusters: dict[str, set] = defaultdict(set)
    for row in rows:
        url = normalize_facebook_profile_url(row.get("profile_url"))
        cluster_id = row.get("cluster_id")
        if url in configured and cluster_id is not None:
            clusters[url].add(cluster_id)

    totals = {url: len(clusters[url]) for url in ordered_urls}
    normalized_stats = {normalize_facebook_profile_url(url): value for url, value in stats.items()}

    def quality_score(url: str):
        return ((normalized_stats.get(url) or {}).get("data_quality") or {}).get("score")

    def broker_rank(url: str, shared: int) -> tuple:
        score = quality_score(url)
        latest = parse_crawl_datetime((normalized_stats.get(url) or {}).get("latest_crawled_at"))
        return (
            float(score) if score is not None else -1.0,
            totals[url] - shared,
            latest or datetime.min,
        )

    comparisons_out = []
    for url_a, url_b in combinations(ordered_urls, 2):
        profile_a = configured[url_a]
        profile_b = configured[url_b]
        city_a = str(profile_a.get("city") or "").strip()
        city_b = str(profile_b.get("city") or "").strip()
        if not city_a or city_a.casefold() != city_b.casefold():
            continue
        if totals[url_a] < 10 or totals[url_b] < 10:
            continue
        shared = len(clusters[url_a] & clusters[url_b])
        if shared < 5:
            continue

        overlap_a = pct(shared, totals[url_a])
        overlap_b = pct(shared, totals[url_b])
        keep_url, reduce_url = (url_a, url_b)
        if broker_rank(url_b, shared) > broker_rank(url_a, shared):
            keep_url, reduce_url = url_b, url_a
        reduce_overlap = overlap_a if reduce_url == url_a else overlap_b
        recommended_days = 7 if reduce_overlap >= 70 else 3 if reduce_overlap >= 50 else None
        comparisons_out.append({
            "city": city_a,
            "broker_a_url": url_a,
            "broker_a_name": profile_a.get("broker_name") or url_a,
            "broker_a_total_lots": totals[url_a],
            "broker_a_overlap_pct": overlap_a,
            "broker_a_quality_score": quality_score(url_a),
            "broker_b_url": url_b,
            "broker_b_name": profile_b.get("broker_name") or url_b,
            "broker_b_total_lots": totals[url_b],
            "broker_b_overlap_pct": overlap_b,
            "broker_b_quality_score": quality_score(url_b),
            "shared_lots": shared,
            "keep_url": keep_url,
            "reduce_url": reduce_url,
            "recommended_crawl_every_days": recommended_days,
        })

    def reduced_overlap(item: dict) -> float:
        if item["reduce_url"] == item["broker_a_url"]:
            return item["broker_a_overlap_pct"]
        return item["broker_b_overlap_pct"]

    comparisons_out.sort(
        key=lambda item: (reduced_overlap(item), item["shared_lots"]),
        reverse=True,
    )
    by_profile = {}
    for item in comparisons_out:
        for url, other_url, overlap in (
            (item["broker_a_url"], item["broker_b_url"], item["broker_a_overlap_pct"]),
            (item["broker_b_url"], item["broker_a_url"], item["broker_b_overlap_pct"]),
        ):
            current = by_profile.get(url)
            if current and (current["overlap_pct"], current["shared_lots"]) >= (overlap, item["shared_lots"]):
                continue
            by_profile[url] = {**item, "other_url": other_url, "overlap_pct": overlap}
    return {"comparisons": comparisons_out, "by_profile": by_profile}


def facebook_profile_duplicate_analysis(profiles: list[dict], stats: dict, conn_factory=get_conn) -> dict:
    profiles_by_city: Counter[str] = Counter()
    for profile in profiles:
        city = str(profile.get("city") or "").strip().casefold()
        if city and profile.get("url"):
            profiles_by_city[city] += 1
    if not any(count >= 2 for count in profiles_by_city.values()):
        return {"comparisons": [], "by_profile": {}}

    cutoff_iso = (datetime.now(timezone.utc) - timedelta(days=90)).replace(tzinfo=None).isoformat(timespec="seconds")
    try:
        with conn_factory() as conn:
            fetched = conn.execute("""
                SELECT COALESCE(l.duplicate_of_id, l.id) AS cluster_id,
                       COALESCE(NULLIF(r.raw_json::jsonb ->> 'profile_url', ''),
                                NULLIF(r.raw_json::jsonb -> '_apify_raw' ->> 'inputUrl', '')) AS profile_url
                FROM listings l
                JOIN raw_listings r ON r.id = l.raw_id
                WHERE l.source = 'facebook'
                  AND (
                      l.crawled_at >= ?
                      OR ((l.crawled_at IS NULL OR l.crawled_at = '') AND r.crawled_at >= ?)
                  )
            """, (cutoff_iso, cutoff_iso)).fetchall()
        rows = [
            {"cluster_id": row["cluster_id"], "profile_url": row["profile_url"]}
            for row in fetched
        ]
    except Exception:
        return {"comparisons": [], "by_profile": {}}
    return build_facebook_duplicate_analysis(profiles, stats, rows)


def missing_image_summary(conn, source: str | None = None) -> dict:
    where_sql = ""
    params = []
    if source:
        where_sql = "WHERE l.source = ?"
        params.append(source)
    row = conn.execute("""
        SELECT
            COUNT(*) AS total_image_refs,
            COALESCE(SUM(CASE WHEN li.local_path IS NULL OR li.local_path = '' THEN 1 ELSE 0 END), 0) AS missing_image_refs,
            COALESCE(SUM(CASE WHEN li.local_path IS NOT NULL AND li.local_path != '' THEN 1 ELSE 0 END), 0) AS downloaded_image_refs,
            COUNT(DISTINCT li.listing_id) AS listings_with_images,
            COUNT(DISTINCT CASE WHEN li.local_path IS NULL OR li.local_path = '' THEN li.listing_id END) AS listings_with_missing_images,
            COUNT(DISTINCT CASE WHEN li.local_path IS NOT NULL AND li.local_path != '' THEN li.listing_id END) AS listings_with_downloaded_images
        FROM listing_images li
        JOIN listings l ON l.id = li.listing_id
        {where_sql}
    """.format(where_sql=where_sql), params).fetchone()
    total = int(row["total_image_refs"] or 0)
    missing = int(row["missing_image_refs"] or 0)
    return {
        "total_image_refs": total,
        "missing_image_refs": missing,
        "downloaded_image_refs": int(row["downloaded_image_refs"] or 0),
        "listings_with_images": int(row["listings_with_images"] or 0),
        "listings_with_missing_images": int(row["listings_with_missing_images"] or 0),
        "listings_with_downloaded_images": int(row["listings_with_downloaded_images"] or 0),
        "missing_pct": round((missing / total) * 100, 1) if total else 0.0,
    }


def facebook_missing_image_summary(conn) -> dict:
    return missing_image_summary(conn, source="facebook")


def facebook_crawl_summary(
    *,
    conn_factory=get_conn,
    jobs: dict[str, dict],
    job_order: list[str],
    lock,
    public_job_fn: Callable[[dict | None], dict | None],
    crawl_ops_summary_fn: Callable[[], dict],
) -> dict:
    try:
        with conn_factory() as conn:
            missing_images = facebook_missing_image_summary(conn)
            pending = missing_images["missing_image_refs"]
            listings = conn.execute("SELECT COUNT(*) AS n FROM listings WHERE source='facebook'").fetchone()["n"]
    except Exception:
        pending = 0
        listings = 0
        missing_images = {
            "total_image_refs": 0,
            "missing_image_refs": 0,
            "downloaded_image_refs": 0,
            "listings_with_images": 0,
            "listings_with_missing_images": 0,
            "listings_with_downloaded_images": 0,
            "missing_pct": 0.0,
        }
    with lock:
        active = next(
            (jobs[jid] for jid in job_order if jobs[jid].get("status") in {"queued", "running"}),
            None,
        )
    return {
        "pending_images": pending,
        "missing_images": missing_images,
        "facebook_listings": listings,
        "active_job": public_job_fn(active) if active else None,
        "ops": crawl_ops_summary_fn(),
    }


def daily_crawl_schedule_status(
    *,
    system_fn: Callable[[], str] = platform.system,
    run_fn: Callable = subprocess.run,
) -> dict:
    system_name = system_fn()
    if system_name == "Linux":
        return systemd_crawl_timer_status(run_fn=run_fn)

    task_name = "RadarBDS_DailyCrawl"
    status = {
        "task_name": task_name,
        "installed": False,
        "state": "missing",
        "next_run_time": "",
        "last_run_time": "",
        "last_result": "",
        "run_time": "",
        "task_to_run": "",
        "error": "",
    }
    if system_name != "Windows":
        status["error"] = "schedule_status_unsupported_platform"
        return status
    try:
        result = run_fn(
            ["schtasks", "/query", "/tn", task_name, "/fo", "LIST", "/v"],
            capture_output=True,
            text=True,
            timeout=8,
        )
    except Exception as exc:
        status["error"] = str(exc)
        return status
    if result.returncode != 0:
        status["error"] = (result.stderr or result.stdout or "").strip()[:240]
        return status
    fields = parse_schtasks_list(result.stdout)
    status.update({
        "installed": True,
        "state": fields.get("Status") or fields.get("Scheduled Task State") or "installed",
        "next_run_time": fields.get("Next Run Time", ""),
        "last_run_time": fields.get("Last Run Time", ""),
        "last_result": fields.get("Last Result", ""),
        "task_to_run": fields.get("Task To Run", ""),
        "run_time": extract_task_run_time(fields.get("Next Run Time", "")),
        "error": "",
    })
    return status


def systemd_crawl_timer_status(*, run_fn: Callable = subprocess.run) -> dict:
    timer_name = "radar-bds-crawl.timer"
    status = {
        "task_name": timer_name,
        "installed": False,
        "state": "missing",
        "next_run_time": "",
        "last_run_time": "",
        "last_result": "",
        "run_time": "",
        "task_to_run": "radar-bds-crawl.service",
        "error": "",
        "service_state": "",
        "service_result": "",
        "service_exit_code": "",
        "service_failed": False,
        "service_last_finished_at": "",
        "service_log_hint": "logs/crawl-daily.log",
    }
    try:
        result = run_fn(
            [
                "systemctl",
                "show",
                timer_name,
                "--no-page",
                "--property=LoadState,ActiveState,SubState,Unit,NextElapseUSecRealtime,LastTriggerUSec",
            ],
            capture_output=True,
            text=True,
            timeout=8,
        )
    except Exception as exc:
        status["error"] = str(exc)
        return status

    if result.returncode != 0:
        status["error"] = (result.stderr or result.stdout or "").strip()[:240]
        return status

    fields = parse_key_value_lines(result.stdout)
    if fields.get("LoadState") != "loaded":
        status["error"] = fields.get("LoadState") or "not-loaded"
        return status

    active = fields.get("ActiveState") or "loaded"
    sub = fields.get("SubState") or ""
    status.update({
        "installed": True,
        "state": f"{active}/{sub}" if sub else active,
        "next_run_time": fields.get("NextElapseUSecRealtime", ""),
        "last_run_time": fields.get("LastTriggerUSec", ""),
        "task_to_run": fields.get("Unit") or status["task_to_run"],
        "run_time": extract_task_run_time(fields.get("NextElapseUSecRealtime", "")),
        "error": "",
    })
    status.update(systemd_crawl_service_status(status["task_to_run"], run_fn=run_fn))

    try:
        cat = run_fn(
            ["systemctl", "cat", timer_name, "--no-pager"],
            capture_output=True,
            text=True,
            timeout=8,
        )
        if cat.returncode == 0:
            run_time = extract_systemd_on_calendar_run_time(cat.stdout)
            if run_time:
                status["run_time"] = run_time
    except Exception:
        pass
    return status


def systemd_crawl_service_status(service_name: str, *, run_fn: Callable = subprocess.run) -> dict:
    base = {
        "service_state": "",
        "service_result": "",
        "service_exit_code": "",
        "service_failed": False,
        "service_last_finished_at": "",
        "service_log_hint": "logs/crawl-daily.log",
    }
    service = (service_name or "radar-bds-crawl.service").strip() or "radar-bds-crawl.service"
    try:
        result = run_fn(
            [
                "systemctl",
                "show",
                service,
                "--no-page",
                "--property=LoadState,ActiveState,SubState,Result,ExecMainStatus,InactiveExitTimestamp",
            ],
            capture_output=True,
            text=True,
            timeout=8,
        )
    except Exception as exc:
        base["service_result"] = f"status_error:{str(exc)[:120]}"
        return base

    if result.returncode != 0:
        err = (result.stderr or result.stdout or "").strip()[:160]
        base["service_result"] = f"status_error:{err}" if err else "status_error"
        return base

    fields = parse_key_value_lines(result.stdout)
    active = fields.get("ActiveState") or ""
    sub = fields.get("SubState") or ""
    service_state = f"{active}/{sub}" if active and sub else active or sub
    service_result = fields.get("Result") or ""
    exit_code = fields.get("ExecMainStatus") or ""
    failed = (
        active == "failed"
        or sub == "failed"
        or service_result not in ("", "success")
        or exit_code not in ("", "0")
    )
    base.update({
        "service_state": service_state,
        "service_result": service_result,
        "service_exit_code": exit_code,
        "service_failed": failed,
        "service_last_finished_at": fields.get("InactiveExitTimestamp", ""),
    })
    return base


def parse_schtasks_list(output: str) -> dict:
    fields: dict[str, str] = {}
    for line in (output or "").splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        fields[key.strip()] = value.strip()
    return fields


def parse_key_value_lines(output: str) -> dict:
    fields: dict[str, str] = {}
    for line in (output or "").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        fields[key.strip()] = value.strip()
    return fields


def extract_systemd_on_calendar_run_time(output: str) -> str:
    for line in (output or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or not line.startswith("OnCalendar="):
            continue
        run_time = extract_task_run_time(line.split("=", 1)[1])
        if run_time:
            return run_time
    return ""


def extract_task_run_time(value: str) -> str:
    value = (value or "").strip()
    for fmt in ("%m/%d/%Y %I:%M:%S %p", "%d/%m/%Y %I:%M:%S %p", "%m/%d/%Y %H:%M:%S", "%d/%m/%Y %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt).strftime("%H:%M")
        except ValueError:
            continue
    match = re.search(r"\b(\d{1,2}):(\d{2})(?::\d{2})?\s*(AM|PM)?\b", value, flags=re.I)
    if not match:
        return ""
    hour = int(match.group(1))
    minute = int(match.group(2))
    suffix = (match.group(3) or "").upper()
    if suffix == "PM" and hour != 12:
        hour += 12
    elif suffix == "AM" and hour == 12:
        hour = 0
    return f"{hour:02d}:{minute:02d}"


def parse_crawl_dt(value: str):
    value = (value or "").strip().replace("Z", "+00:00")
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        try:
            dt = datetime.strptime(value[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def active_radar_lock_blockers(conn_factory=get_conn) -> list[dict]:
    from db.connection import _lock_id

    names = ("crawl-incremental", "crawl-full", "crawl-facebook", "reprocess", "download-images")
    blockers: list[dict] = []
    try:
        with conn_factory() as conn:
            for name in names:
                lock_id = _lock_id(name)
                row = conn.execute("SELECT pg_try_advisory_lock(?) AS locked", (lock_id,)).fetchone()
                locked = bool(row["locked"]) if row else False
                if locked:
                    conn.execute("SELECT pg_advisory_unlock(?)", (lock_id,))
                else:
                    blockers.append({"name": name, "pid": None, "state": "locked", "age_seconds": None})
    except Exception as exc:
        return [{"name": "lock-check", "pid": None, "state": "error", "age_seconds": None, "error": str(exc)[:160]}]
    return blockers


def crawl_ops_summary(
    *,
    conn_factory=get_conn,
    schedule_status_fn: Callable[[], dict] = daily_crawl_schedule_status,
    active_lock_blockers_fn: Callable[[], list[dict]] = active_radar_lock_blockers,
) -> dict:
    schedule = schedule_status_fn()
    blockers = active_lock_blockers_fn()
    empty = {
        "schedule": schedule,
        "last_run": None,
        "last_24h": {"runs": 0, "fetched": 0, "new": 0, "updated": 0, "skipped": 0},
        "signal_count": 0,
        "source_errors": [],
        "lock_blockers": blockers,
    }
    try:
        with conn_factory() as conn:
            last_rows = conn.execute(
                """
                SELECT id, source, area, started_at, finished_at, status,
                       COALESCE(n_fetched,0) AS n_fetched,
                       COALESCE(n_new,0) AS n_new,
                       COALESCE(n_updated,0) AS n_updated,
                       COALESCE(n_skipped,0) AS n_skipped,
                       COALESCE(error_msg,'') AS error_msg
                FROM crawl_runs
                ORDER BY id DESC
                LIMIT 12
                """
            ).fetchall()
            signal_row = conn.execute(
                "SELECT COUNT(*) AS n FROM valuation_results WHERE is_signal=1"
            ).fetchone()
    except Exception as exc:
        empty["source_errors"] = [{"source": "ops", "status": "error", "error_msg": str(exc)[:180]}]
        return empty
    if signal_row:
        empty["signal_count"] = signal_row["n"] or 0
    if not last_rows:
        return empty
    last = last_rows[0]
    empty["last_run"] = crawl_run_public(last)
    latest_dt = parse_crawl_dt(last["started_at"])
    if latest_dt:
        recent = []
        for row in last_rows:
            dt = parse_crawl_dt(row["started_at"])
            if not dt:
                continue
            delta = (latest_dt - dt).total_seconds()
            if 0 <= delta <= 15 * 60:
                recent.append(row)
        if not recent:
            recent = [last]
    else:
        recent = [last]
    empty["last_24h"] = {
        "runs": len(recent),
        "fetched": sum((r["n_fetched"] or 0) for r in recent),
        "new": sum((r["n_new"] or 0) for r in recent),
        "updated": sum((r["n_updated"] or 0) for r in recent),
        "skipped": sum((r["n_skipped"] or 0) for r in recent),
    }
    errors = [
        crawl_run_public(r)
        for r in last_rows
        if (r["status"] or "") == "error" or (r["n_fetched"] or 0) == 0 or (r["error_msg"] or "")
    ]
    empty["source_errors"] = errors[:6]
    return empty


def crawl_run_public(row) -> dict:
    return {
        "id": row["id"],
        "source": row["source"] or "",
        "area": row["area"] or "",
        "started_at": row["started_at"] or "",
        "finished_at": row["finished_at"] or "",
        "status": row["status"] or "",
        "fetched": row["n_fetched"] or 0,
        "new": row["n_new"] or 0,
        "updated": row["n_updated"] or 0,
        "skipped": row["n_skipped"] or 0,
        "error_msg": row["error_msg"] or "",
    }


def apify_tokens_public() -> list[dict]:
    from crawler.apify_token_pool import list_tokens_public

    return list_tokens_public()


def int_metric(value) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def apify_pool_summary(tokens: list[dict] | None = None, token_loader: Callable[[], list[dict]] = apify_tokens_public) -> dict:
    tokens = list(tokens if tokens is not None else token_loader())
    active_tokens = [t for t in tokens if t.get("active") is not False]
    total_quota = sum(int_metric(t.get("monthly_quota")) for t in active_tokens)
    used_this_month = sum(int_metric(t.get("used_this_month")) for t in active_tokens)
    total_remaining = sum(int_metric(t.get("remaining")) for t in active_tokens)
    low_tokens = [
        {
            "id": t.get("id") or "",
            "label": t.get("label") or "",
            "remaining": int_metric(t.get("remaining")),
            "last_error": t.get("last_error") or "",
        }
        for t in active_tokens
        if int_metric(t.get("remaining")) <= 100 or t.get("last_error")
    ]
    return {
        "tokens": tokens,
        "total_tokens": len(tokens),
        "active_tokens": len(active_tokens),
        "monthly_quota": total_quota,
        "used_this_month": used_this_month,
        "total_remaining": total_remaining,
        "usage_pct": round((used_this_month / total_quota) * 100, 1) if total_quota else 0.0,
        "low_tokens": low_tokens,
    }


def suppressed_signal_quality_summary(conn) -> dict:
    listing_condition = actionable_listing_sql("l")
    signal_condition = actionable_signal_sql("v")
    rows = conn.execute(f"""
        WITH {LATEST_VALUATION_CTE}
        SELECT l.id, l.title, l.source, l.ward,
               COALESCE(v.mos_pct,0) AS mos_pct,
               COALESCE(v.signal_score,0) AS signal_score,
               COALESCE(v.source_quality_recheck,0) AS source_quality_recheck,
               COALESCE(v.source_quality_flags,'') AS source_quality_flags
        FROM listings l
        JOIN latest_valuation v ON v.listing_id = l.id
        WHERE {listing_condition}
          AND COALESCE(v.is_signal,0)=1
          AND NOT ({signal_condition})
        ORDER BY COALESCE(v.signal_score,0) DESC, COALESCE(v.mos_pct,0) DESC, l.id DESC
        LIMIT 5000
    """).fetchall()
    by_flag: Counter[str] = Counter()
    by_source: Counter[str] = Counter()
    samples: list[dict] = []
    for row in rows:
        source = row["source"] or "unknown"
        by_source[source] += 1
        flags = split_quality_flags(row["source_quality_flags"])
        if not flags and row["source_quality_recheck"]:
            flags = {"source_quality_recheck"}
        for flag in sorted(flags):
            if flag == "low_segment_confidence":
                continue
            by_flag[flag] += 1
        if len(samples) < 8:
            samples.append({
                "id": row["id"],
                "title": row["title"] or "",
                "source": source,
                "ward": row["ward"] or "",
                "mos_pct": row["mos_pct"] or 0,
                "signal_score": row["signal_score"] or 0,
                "source_quality_flags": row["source_quality_flags"] or "",
            })
    return {
        "total": len(rows),
        "by_flag": [{"flag": flag, "count": count} for flag, count in by_flag.most_common()],
        "by_source": [{"source": source, "count": count} for source, count in by_source.most_common()],
        "samples": samples,
    }


def data_quality_summary(
    *,
    conn_factory=get_conn,
    apify_tokens_fn: Callable[[], list[dict]] = apify_tokens_public,
    crawl_ops_summary_fn: Callable[[], dict],
) -> dict:
    try:
        apify_tokens = apify_tokens_fn()
    except Exception as exc:
        apify_tokens = []
        apify_error = str(exc)[:180]
    else:
        apify_error = ""

    missing_images = {
        "total_image_refs": 0,
        "missing_image_refs": 0,
        "downloaded_image_refs": 0,
        "listings_with_images": 0,
        "listings_with_missing_images": 0,
        "listings_with_downloaded_images": 0,
        "missing_pct": 0.0,
    }
    suppressed = {"total": 0, "by_flag": [], "by_source": [], "samples": []}
    try:
        with conn_factory() as conn:
            missing_images = missing_image_summary(conn)
            suppressed = suppressed_signal_quality_summary(conn)
    except Exception as exc:
        suppressed = {
            "total": 0,
            "by_flag": [],
            "by_source": [],
            "samples": [],
            "error": str(exc)[:180],
        }

    ops = crawl_ops_summary_fn()
    crawl_health = {
        "schedule": ops.get("schedule") or {},
        "last_run": ops.get("last_run"),
        "last_24h": ops.get("last_24h") or {},
        "source_errors": ops.get("source_errors") or [],
        "lock_blockers": ops.get("lock_blockers") or [],
    }
    return {
        "missing_images": missing_images,
        "apify_pool": {
            **apify_pool_summary(apify_tokens, token_loader=apify_tokens_fn),
            "error": apify_error,
        },
        "crawl_health": crawl_health,
        "suppressed_signals": suppressed,
    }
