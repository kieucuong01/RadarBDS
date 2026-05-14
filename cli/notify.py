"""VIP push: notify VIP users about new listings matching their watchlist.

Triggered after each crawl (crawl-daily / crawl-all). Sends Telegram card per
match (real-time feel) + 1 batched email per user (avoid inbox spam).

Anti-spam: log every push to `user_audit_log` with action='notify_vip_listing'
and listing_id; skip if already pushed to this user.

Usage:
    from cli.notify import push_new_listings_to_vip
    push_new_listings_to_vip(since='2026-05-14T12:00:00')
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Iterable

from db.connection import get_conn

logger = logging.getLogger(__name__)


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


def _already_notified(conn, user_id: int, listing_id: int) -> bool:
    row = conn.execute(
        "SELECT id FROM user_audit_log "
        "WHERE user_id=? AND action='notify_vip_listing' AND listing_id=? LIMIT 1",
        (user_id, listing_id),
    ).fetchone()
    return row is not None


def _log_notify(conn, user_id: int, listing_id: int, channel: str) -> None:
    conn.execute(
        "INSERT INTO user_audit_log (user_id, tier, action, listing_id, context) "
        "VALUES (?, 'vip', 'notify_vip_listing', ?, ?)",
        (user_id, listing_id, json.dumps({"channel": channel})),
    )


def _fetch_new_signals(conn, since: str) -> list[dict]:
    """Listings crawled or posted since timestamp, signal=1 only."""
    rows = conn.execute(
        """
        SELECT l.id, l.title, l.ward, l.property_type, l.price_ty, l.area_m2, l.url,
               COALESCE(v.mos_pct, 0) AS mos_pct,
               COALESCE(l.posted_at, l.crawled_at) AS posted_at
        FROM listings l
        LEFT JOIN valuation_results v ON v.listing_id = l.id
        WHERE COALESCE(v.is_signal, 0) = 1
          AND datetime(COALESCE(l.posted_at, l.crawled_at)) >= datetime(?)
          AND COALESCE(l.review_hidden, 0) = 0
        ORDER BY datetime(COALESCE(l.posted_at, l.crawled_at)) DESC
        LIMIT 500
        """,
        (since,),
    ).fetchall()
    return [dict(r) for r in rows]


def _fetch_active_vip_users_with_watchlists(conn) -> list[dict]:
    """Effective VIP users + their active watchlists. VIP expiry already filtered."""
    now = datetime.utcnow().isoformat(timespec="seconds")
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
        from datetime import timedelta
        since = (datetime.utcnow() - timedelta(hours=1)).isoformat(timespec="seconds")

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
                    if _already_notified(conn, uid, listing["id"]):
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
                        "wl_notify_email": False,
                        "wl_notify_telegram": False,
                    })
                    # OR-combine watchlist channel preferences (any matching wl can drive channel)
                    if wl.get("w_notify_email"): bucket["wl_notify_email"] = True
                    if wl.get("w_notify_telegram"): bucket["wl_notify_telegram"] = True
                    if listing["id"] in bucket["seen"]:
                        continue
                    bucket["seen"].add(listing["id"])
                    bucket["listings"].append(listing)

            if not user_matches:
                logger.info(f"[vip-push] no matches across {len(wl_rows)} watchlists")
                return stats

            stats["matched_users"] = len(user_matches)

            # Send Telegram (per listing) + Email (batch)
            from alerts.telegram import send_listing_card
            from alerts.email import send_listing_alert

            for uid, bucket in user_matches.items():
                user = bucket["user"]
                listings = bucket["listings"]
                tg_enabled = user["notify_telegram"] and bucket["wl_notify_telegram"] and user["telegram_chat_id"]
                em_enabled = user["notify_email"] and bucket["wl_notify_email"] and user["email"]

                if tg_enabled:
                    for listing in listings[:5]:  # cap 5 cards/user/run
                        if send_listing_card(user["telegram_chat_id"], listing):
                            stats["telegram_sent"] += 1
                            _log_notify(conn, uid, listing["id"], "telegram")

                if em_enabled and listings:
                    if send_listing_alert(user["email"], user["name"], listings):
                        stats["email_users"] += 1
                        # Log first 10 as email-channel (matches email body cap)
                        for listing in listings[:10]:
                            _log_notify(conn, uid, listing["id"], "email")

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
