"""VIP push: notify VIP users about new listings matching their watchlist.

Triggered after each crawl (crawl-daily / crawl-all). Sends one Telegram digest
per matched VIP user + 1 batched email per user (avoid inbox spam).

Anti-spam: every push is logged to `notification_log` with the listing price
at push time. A user is re-alerted for the same listing only when the current
price has dropped at least SIGNAL_REALERT_THRESHOLD_PCT compared to the last
notification — see `_should_skip_notify` below.

Usage:
    from cli.notify import push_new_listings_to_vip
    push_new_listings_to_vip(since='2026-05-14T12:00:00')
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Iterable

from db.connection import get_conn
from config.settings import LEGAL_IMAGE_EVIDENCE_ENABLED, SIGNAL_REALERT_THRESHOLD_PCT
from services.signal_quality import (
    LATEST_VALUATION_CTE,
    actionable_listing_sql,
    actionable_signal_sql,
)

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_iso(timespec: str = "seconds") -> str:
    return _utc_now().replace(tzinfo=None).isoformat(timespec=timespec)


def _parse_json_list(v) -> list:
    if not v:
        return []
    if isinstance(v, list):
        return v
    try:
        d = json.loads(v)
        return d if isinstance(d, list) else []
    except Exception:
        return []


def _listing_matches(listing: dict, watchlist: dict) -> bool:
    wards = _parse_json_list(watchlist.get("wards"))
    if wards and listing.get("ward") not in wards:
        return False
    prop_types = _parse_json_list(watchlist.get("prop_types"))
    if prop_types and listing.get("property_type") not in prop_types:
        return False
    mos_min = watchlist.get("mos_min") or 0
    if mos_min and (listing.get("mos_pct") or 0) < mos_min:
        return False
    pmax = watchlist.get("price_max_ty")
    if pmax is not None and (listing.get("price_ty") or 0) > pmax:
        return False
    pmin = watchlist.get("price_min_ty")
    if pmin is not None and (listing.get("price_ty") or 0) < pmin:
        return False
    amin = watchlist.get("area_min")
    if amin is not None and (listing.get("area_m2") or 0) < amin:
        return False
    amax = watchlist.get("area_max")
    if amax is not None and (listing.get("area_m2") or 0) > amax:
        return False
    return True


def _last_notification(conn, user_id: int, listing_id: int) -> dict | None:
    row = conn.execute(
        "SELECT id, channel, notified_price_ty, sent_at FROM notification_log "
        "WHERE user_id=? AND listing_id=? "
        "ORDER BY datetime(sent_at) DESC, id DESC LIMIT 1",
        (user_id, listing_id),
    ).fetchone()
    return dict(row) if row else None


def _should_skip_notify(
    conn, user_id: int, listing_id: int,
    current_price, threshold_pct: float,
) -> tuple[bool, float | None]:
    """Return (skip, prev_price).

    - No prior row → (False, None): first push.
    - Prior row with notified_price_ty IS NULL → (True, None): legacy row,
      preserve pre-TTL behavior (don't spam).
    - current_price missing/invalid or prev <= 0 → (True, prev): can't reason.
    - drop_pct < threshold → (True, prev): skip.
    - drop_pct >= threshold → (False, prev): re-alert.
    """
    last = _last_notification(conn, user_id, listing_id)
    if last is None:
        return False, None
    prev = last.get("notified_price_ty")
    if prev is None:
        return True, None
    if current_price is None:
        return True, prev
    try:
        cur = float(current_price)
        prev_f = float(prev)
    except (TypeError, ValueError):
        return True, prev
    if prev_f <= 0 or cur <= 0:
        return True, prev
    drop_pct = (prev_f - cur) / prev_f * 100.0
    return (drop_pct < threshold_pct), prev_f


def _log_notify(conn, user_id: int, listing_id: int, channel: str, price_ty) -> None:
    conn.execute(
        "INSERT INTO notification_log (user_id, listing_id, channel, notified_price_ty) "
        "VALUES (?, ?, ?, ?)",
        (user_id, listing_id, channel, price_ty),
    )


def _fetch_new_signals(conn, since: str) -> list[dict]:
    """Listings first seen since timestamp, signal=1 only."""
    signal_condition = actionable_signal_sql("v")
    listing_condition = actionable_listing_sql("l")
    order_sql = (
        """CASE COALESCE(v.trust_tier, 'candidate_signal')
                    WHEN 'has_legal_doc' THEN 0
                    ELSE 1
                 END ASC,
                 COALESCE(v.trust_score, 0) DESC,
                 datetime(COALESCE(l.first_seen_at, l.crawled_at, l.posted_at)) DESC"""
        if LEGAL_IMAGE_EVIDENCE_ENABLED
        else "datetime(COALESCE(l.first_seen_at, l.crawled_at, l.posted_at)) DESC"
    )
    rows = conn.execute(
        f"""
        WITH {LATEST_VALUATION_CTE}
        SELECT l.id, l.title, l.ward, l.property_type, l.price_ty, l.area_m2, l.url,
               COALESCE(v.mos_pct, 0) AS mos_pct,
               COALESCE(v.trust_tier, 'candidate_signal') AS trust_tier,
               COALESCE(v.trust_score, 0) AS trust_score,
               COALESCE(v.legal_status, 'unverified') AS legal_status,
               COALESCE(l.posted_at, l.crawled_at, l.first_seen_at) AS posted_at
        FROM listings l
        JOIN latest_valuation v ON v.listing_id = l.id
        WHERE {signal_condition}
          AND datetime(COALESCE(l.first_seen_at, l.crawled_at, l.posted_at)) >= datetime(?)
          AND {listing_condition}
        ORDER BY {order_sql}
        LIMIT 500
        """,
        (since,),
    ).fetchall()
    return [dict(r) for r in rows]


def _fetch_active_vip_users_with_watchlists(conn) -> list[dict]:
    """Effective VIP users + their active watchlists. VIP expiry already filtered."""
    now = _utc_iso()
    rows = conn.execute(
        """
        SELECT u.id, u.display_name, u.email, u.telegram_chat_id,
               u.notify_email AS u_notify_email, u.notify_telegram AS u_notify_telegram,
               w.id AS w_id, w.name AS w_name, w.wards, w.prop_types,
               w.mos_min, w.price_max_ty, w.price_min_ty, w.area_min, w.area_max,
               w.notify_email AS w_notify_email, w.notify_telegram AS w_notify_telegram
        FROM users u
        JOIN user_watchlists w ON w.user_id = u.id
        WHERE u.is_banned = 0
          AND u.tier = 'vip'
          AND (u.vip_expires_at IS NULL OR u.vip_expires_at > ?)
          AND w.active = 1
        """,
        (now,),
    ).fetchall()
    return [dict(r) for r in rows]


def push_new_listings_to_vip(since: str | None = None) -> dict:
    """Main entry. Returns stats dict.

    `since`: ISO timestamp. If None, use last hour.
    """
    if not since:
        since = (_utc_now() - timedelta(hours=1)).replace(tzinfo=None).isoformat(timespec="seconds")

    stats = {"telegram_sent": 0, "email_users": 0, "matched_users": 0, "since": since}
    try:
        with get_conn() as conn:
            signals = _fetch_new_signals(conn, since)
            if not signals:
                logger.info(f"[vip-push] no new signals since {since}")
                return stats

            wl_rows = _fetch_active_vip_users_with_watchlists(conn)
            if not wl_rows:
                logger.info("[vip-push] no VIP users with active watchlists")
                return stats

            # Group: user_id → list of matched listings (deduped)
            user_matches: dict[int, dict] = {}
            for wl in wl_rows:
                uid = wl["id"]
                for listing in signals:
                    skip, prev_price = _should_skip_notify(
                        conn, uid, listing["id"], listing.get("price_ty"),
                        SIGNAL_REALERT_THRESHOLD_PCT,
                    )
                    if skip:
                        continue
                    if not _listing_matches(listing, wl):
                        continue
                    bucket = user_matches.setdefault(uid, {
                        "user": {
                            "id": uid,
                            "name": wl.get("display_name"),
                            "email": wl.get("email"),
                            "telegram_chat_id": wl.get("telegram_chat_id"),
                            "notify_email": bool(wl.get("u_notify_email", 1)),
                            "notify_telegram": bool(wl.get("u_notify_telegram", 1)),
                        },
                        "listings": [],
                        "seen": set(),
                        "watchlists": set(),
                        "wl_notify_email": False,
                        "wl_notify_telegram": False,
                    })
                    # OR-combine watchlist channel preferences (any matching wl can drive channel)
                    if wl.get("w_notify_email"): bucket["wl_notify_email"] = True
                    if wl.get("w_notify_telegram"): bucket["wl_notify_telegram"] = True
                    if wl.get("w_name"): bucket["watchlists"].add(wl["w_name"])
                    if listing["id"] in bucket["seen"]:
                        continue
                    bucket["seen"].add(listing["id"])
                    # Shallow copy so the per-user re-alert flag doesn't leak
                    # across users sharing the same `signals` dict.
                    entry = dict(listing)
                    entry["_prev_notified_price_ty"] = prev_price
                    bucket["listings"].append(entry)

            if not user_matches:
                logger.info(f"[vip-push] no matches across {len(wl_rows)} watchlists")
                return stats

            stats["matched_users"] = len(user_matches)

            # Send Telegram (one compact digest/user) + Email (batch)
            from alerts.telegram import send_watchlist_digest
            from alerts.email import send_listing_alert
            from config.settings import DASHBOARD_BASE_URL

            for uid, bucket in user_matches.items():
                user = bucket["user"]
                listings = bucket["listings"]
                tg_enabled = user["notify_telegram"] and bucket["wl_notify_telegram"] and user["telegram_chat_id"]
                em_enabled = user["notify_email"] and bucket["wl_notify_email"] and user["email"]

                if tg_enabled:
                    watchlist_names = sorted(bucket.get("watchlists") or [])
                    if send_watchlist_digest(user["telegram_chat_id"], listings, base_url=DASHBOARD_BASE_URL,
                                             watchlist_names=watchlist_names):
                        sent_count = min(len(listings), 6)
                        stats["telegram_sent"] += sent_count
                        for listing in listings[:sent_count]:
                            _log_notify(conn, uid, listing["id"], "telegram", listing.get("price_ty"))

                if em_enabled and listings:
                    if send_listing_alert(user["email"], user["name"], listings):
                        stats["email_users"] += 1
                        # Log first 10 as email-channel (matches email body cap)
                        for listing in listings[:10]:
                            _log_notify(conn, uid, listing["id"], "email", listing.get("price_ty"))

                # Update watchlist last_notified_at for all touched watchlists
                conn.execute(
                    "UPDATE user_watchlists SET last_notified_at=datetime('now') "
                    "WHERE user_id=? AND active=1",
                    (uid,),
                )

    except Exception as e:
        logger.exception(f"[vip-push] failed: {e}")
    logger.info(f"[vip-push] done: {stats}")
    return stats
