"""VIP watchlist and opt-in saved-listing updates.

Triggered after each crawl (crawl-daily / crawl-all). Sends one Telegram digest
per matched VIP user + 1 batched email per user (avoid inbox spam).

Successful delivery records the price/source state independently per channel.
Only meaningful price/source changes re-alert. Pending records retain failed
or overflow deliveries without advancing that baseline. A DB lock serializes jobs.

Usage:
    from cli.notify import push_new_listings_to_vip
    push_new_listings_to_vip(since='2026-05-14T12:00:00')
"""
from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timedelta, timezone

from db.connection import get_conn, advisory_lock, AdvisoryLockBusy
from db.guland_publishers import publisher_visibility_sql
from config.settings import LEGAL_IMAGE_EVIDENCE_ENABLED, SIGNAL_REALERT_THRESHOLD_PCT
from services.signal_quality import (
    ACTIONABLE_SUPPRESS_FLAGS,
    LATEST_VALUATION_CTE,
    actionable_listing_sql,
    actionable_signal_sql,
    effective_signal_mos_min,
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
    requested_mos = watchlist.get("mos_min")
    mos_was_explicit = requested_mos not in (None, "", 0, 0.0, "0")
    mos_min = effective_signal_mos_min(
        "vip",
        requested_mos,
        was_explicit=mos_was_explicit,
    )
    if float(listing.get("mos_pct") or 0) < mos_min:
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


def _last_notification(conn, user_id: int, listing_id: int, channel=None, after=None) -> dict | None:
    channel_filter = " AND channel=?" if channel else ""
    after_filter = " AND (sent_at::timestamptz AT TIME ZONE 'UTC') >= ?::timestamp" if after else ""
    params = [user_id, listing_id] + ([channel] if channel else []) + ([after] if after else [])
    row = conn.execute(
        "SELECT id, channel, notified_price_ty, notified_source_status, sent_at FROM notification_log "
        "WHERE user_id=? AND listing_id=? AND COALESCE(event_kind,'') <> 'pending' " + channel_filter + after_filter +
        " ORDER BY id DESC LIMIT 1",
        params,
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
    if not math.isfinite(prev_f) or not math.isfinite(cur) or prev_f <= 0 or cur <= 0:
        return True, prev
    drop_pct = (prev_f - cur) / prev_f * 100.0
    return (drop_pct + 1e-9 < threshold_pct), prev_f


def _log_notify(conn, user_id: int, listing_id: int, channel: str, price_ty, source_status=None, event_kind=None) -> None:
    conn.execute(
        "INSERT INTO notification_log (user_id, listing_id, channel, notified_price_ty, notified_source_status, event_kind, sent_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (user_id, listing_id, channel, price_ty, source_status, event_kind, _utc_now().isoformat(timespec='microseconds')),
    )


def _mark_pending(conn, user_id, listing_id, channel):
    """Retain an undelivered item across crawl windows without consuming dedup."""
    conn.execute("""
        INSERT INTO notification_log(user_id, listing_id, channel, event_kind)
        SELECT ?, ?, ?, 'pending'
        WHERE NOT EXISTS (SELECT 1 FROM notification_log WHERE user_id=? AND listing_id=? AND channel=? AND event_kind='pending')
    """, (user_id, listing_id, channel, user_id, listing_id, channel))


def _fetch_new_signals(conn, since: str, offset: int = 0) -> list[dict]:
    """New signals and previously followed listings, in bounded pages."""
    signal_condition = actionable_signal_sql("v")
    listing_condition = actionable_listing_sql("l")
    quality_condition = ' AND '.join(f"COALESCE(v.source_quality_flags,'') NOT LIKE '%{flag}%'" for flag in sorted(ACTIONABLE_SUPPRESS_FLAGS))
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
        SELECT l.id, l.title, l.ward, l.property_type, l.price_ty, l.area_m2,
               COALESCE(l.source_status, 'unknown') AS source_status,
               CASE WHEN {signal_condition} AND {listing_condition} THEN 1 ELSE 0 END AS alert_signal_eligible,
               CASE WHEN {listing_condition} AND {quality_condition} THEN 1 ELSE 0 END AS alert_listing_eligible,
               COALESCE(v.mos_pct, 0) AS mos_pct,
               COALESCE(v.trust_tier, 'candidate_signal') AS trust_tier,
               COALESCE(v.trust_score, 0) AS trust_score,
               COALESCE(v.legal_status, 'unverified') AS legal_status,
               COALESCE(l.posted_at, l.crawled_at, l.first_seen_at) AS posted_at
        FROM listings l
        LEFT JOIN latest_valuation v ON v.listing_id = l.id
        WHERE COALESCE(l.is_blacklisted,0)=0 AND COALESCE(l.review_hidden,0)=0
          AND {publisher_visibility_sql('l')}
          AND (
            ({signal_condition} AND {listing_condition}
             AND (datetime(COALESCE(l.first_seen_at, l.crawled_at, l.posted_at)) >= datetime(?)
                  OR datetime(l.price_updated_at) >= datetime(?)))
            OR EXISTS (SELECT 1 FROM notification_log n JOIN user_watchlists w ON w.user_id=n.user_id
                       WHERE n.listing_id=l.id AND w.active=1)
            OR EXISTS (SELECT 1 FROM user_favorite_listings f WHERE f.listing_id=l.id AND f.alert_enabled=1)
          )
        ORDER BY {order_sql}, l.id DESC
        LIMIT 500 OFFSET ?
        """,
        (since, since, offset),
    ).fetchall()
    return [dict(r) for r in rows]


def _fetch_active_vip_users_with_watchlists(conn) -> list[dict]:
    """Effective VIP/admin users + their active watchlists."""
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
          AND (
                u.tier = 'admin'
                OR (
                    u.tier = 'vip'
                    AND (u.vip_expires_at IS NULL OR u.vip_expires_at > ?)
                )
              )
          AND w.active = 1
        """,
        (now,),
    ).fetchall()
    return [dict(r) for r in rows]


def _notification_event(listing, previous, *, allow_new=True):
    """Meaningful changes only; source removal never means a confirmed sale."""
    if previous is None:
        return 'new' if allow_new and listing.get('alert_signal_eligible') and listing.get('source_status') not in {'inactive', 'unreachable'} else None
    status = listing.get('source_status') or 'unknown'
    prior_status = previous.get('notified_source_status') or 'unknown'
    if status == 'inactive' and prior_status != 'inactive':
        return 'source_removed'
    if status == 'active' and prior_status == 'inactive':
        return 'source_reappeared'
    eligibility = 'alert_signal_eligible' if allow_new else 'alert_listing_eligible'
    if status in {'inactive', 'unreachable'} or not listing.get(eligibility):
        return None
    try:
        old = float(previous.get('notified_price_ty'))
        new = float(listing.get('price_ty'))
        if not math.isfinite(old) or not math.isfinite(new) or old <= 0 or new <= 0:
            return None
        drop = (old - new) / old * 100
        # Extreme changes need QC; they are not promoted as ordinary discounts.
        if SIGNAL_REALERT_THRESHOLD_PCT <= drop + 1e-9 and drop <= 40:
            return 'price_drop'
    except (TypeError, ValueError, OverflowError):
        pass
    return None


def _fetch_favorite_subscribers(conn):
    return [dict(row) for row in conn.execute("""
        SELECT u.id, u.display_name, u.email, u.telegram_chat_id,
               u.notify_email AS u_notify_email, u.notify_telegram AS u_notify_telegram,
               f.listing_id, f.alert_price_ty, f.alert_source_status, f.alert_enabled_at
        FROM user_favorite_listings f JOIN users u ON u.id=f.user_id
        WHERE f.alert_enabled=1 AND u.is_banned=0
          AND (u.tier='admin' OR (u.tier='vip' AND (u.vip_expires_at IS NULL OR u.vip_expires_at > ?)))
    """, (_utc_iso(),)).fetchall()]


def push_new_listings_to_vip(since: str | None = None) -> dict:
    # All crawl entry points share one DB lock, including separate processes.
    try:
        with advisory_lock('vip-watchlist-notify'):
            return _push_listing_updates(since)
    except AdvisoryLockBusy:
        return {'telegram_sent': 0, 'email_users': 0, 'matched_users': 0, 'since': since, 'skipped': 'job_running'}


def _push_listing_updates(since: str | None = None) -> dict:
    """Main entry. Returns stats dict.

    `since`: ISO timestamp. If None, use last hour.
    """
    if not since:
        since = (_utc_now() - timedelta(hours=1)).replace(tzinfo=None).isoformat(timespec="seconds")

    stats = {"telegram_sent": 0, "email_users": 0, "matched_users": 0, "since": since}
    try:
        with get_conn() as conn:
            signals = []
            offset = 0
            while True:
                page = _fetch_new_signals(conn, since, offset)
                signals.extend(page)
                if len(page) < 500:
                    break
                offset += 500
            if not signals:
                logger.info(f"[vip-push] no new signals since {since}")
                return stats

            wl_rows = _fetch_active_vip_users_with_watchlists(conn)
            favorite_rows = _fetch_favorite_subscribers(conn)

            # Group: user_id → list of matched listings (deduped)
            user_matches: dict[int, dict] = {}
            for wl in wl_rows:
                uid = wl["id"]
                for listing in signals:
                    currently_matches = _listing_matches(listing, wl)
                    if not currently_matches:
                        # Previously delivered listings can leave the signal set
                        # after removal; still report a confirmed source change.
                        previous = _last_notification(conn, uid, listing['id'])
                        if previous is None or listing.get('source_status') not in {'active', 'inactive'}:
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
                        "channels": {},
                        "favorites": {},
                        "current_matches": set(),
                    })
                    if currently_matches:
                        bucket['current_matches'].add(listing['id'])
                    # OR-combine watchlist channel preferences (any matching wl can drive channel)
                    channels = bucket['channels'].setdefault(listing['id'], set())
                    if wl.get("w_notify_email"): channels.add('email')
                    if wl.get("w_notify_telegram"): channels.add('telegram')
                    if wl.get("w_name"): bucket["watchlists"].add(wl["w_name"])
                    if listing["id"] in bucket["seen"]:
                        continue
                    bucket["seen"].add(listing["id"])
                    # Shallow copy so the per-user re-alert flag doesn't leak
                    # across users sharing the same `signals` dict.
                    entry = dict(listing)
                    bucket["listings"].append(entry)

            by_id = {listing['id']: listing for listing in signals}
            for favorite in favorite_rows:
                listing = by_id.get(favorite['listing_id'])
                if listing is None:
                    continue
                uid = favorite['id']
                bucket = user_matches.setdefault(uid, {
                    'user': {'id': uid, 'name': favorite.get('display_name'), 'email': favorite.get('email'),
                             'telegram_chat_id': favorite.get('telegram_chat_id'),
                             'notify_email': bool(favorite.get('u_notify_email')),
                             'notify_telegram': bool(favorite.get('u_notify_telegram'))},
                    'listings': [], 'seen': set(), 'watchlists': set(), 'channels': {}, 'favorites': {}, 'current_matches': set(),
                })
                bucket['favorites'][listing['id']] = favorite
                # Saving is not consent: only alert_enabled rows reach this loop.
                bucket['channels'].setdefault(listing['id'], set()).update({'telegram', 'email'})
                bucket['watchlists'].add('Lô đã lưu')
                if listing['id'] not in bucket['seen']:
                    bucket['seen'].add(listing['id'])
                    bucket['listings'].append(dict(listing))

            if not user_matches:
                logger.info(f"[vip-push] no matches across {len(wl_rows)} watchlists")
                return stats

            # Send Telegram (one compact digest/user) + Email (batch)
            from alerts.telegram import send_watchlist_digest
            from alerts.email import send_listing_alert
            from config.settings import DASHBOARD_BASE_URL

            for uid, bucket in user_matches.items():
                user = bucket["user"]
                matched = False
                for channel, cap in (('telegram', 6), ('email', 10)):
                    if not user[f'notify_{channel}'] or not user['telegram_chat_id' if channel == 'telegram' else 'email']:
                        continue
                    pending = []
                    for listing in bucket['listings']:
                        if channel not in bucket['channels'].get(listing['id'], set()):
                            continue
                        favorite = bucket['favorites'].get(listing['id'])
                        previous = _last_notification(conn, uid, listing['id'], channel,
                                                      favorite.get('alert_enabled_at') if favorite else None)
                        if previous is None and favorite:
                            previous = {'notified_price_ty': favorite.get('alert_price_ty'),
                                        'notified_source_status': favorite.get('alert_source_status')}
                        event = _notification_event(listing, previous, allow_new=not bool(favorite))
                        if not event:
                            continue
                        if not favorite and listing['id'] not in bucket['current_matches'] and event not in {'source_removed', 'source_reappeared'}:
                            continue
                        from services.market_data import redact_for_tier
                        entry = redact_for_tier(dict(listing), 'vip')
                        entry['_notification_event'] = event
                        entry['_prev_notified_price_ty'] = previous.get('notified_price_ty') if previous and event == 'price_drop' else None
                        pending.append(entry)
                    if not pending:
                        continue
                    matched = True
                    # Prioritize important changes before fresh discoveries.
                    pending.sort(key=lambda item: item['_notification_event'] == 'new')
                    shown = pending[:cap]
                    for listing in pending[cap:]:
                        _mark_pending(conn, uid, listing['id'], channel)
                    try:
                        if channel == 'telegram':
                            sent = send_watchlist_digest(user['telegram_chat_id'], shown, base_url=DASHBOARD_BASE_URL,
                                                        watchlist_names=sorted(bucket['watchlists']))
                        else:
                            sent = send_listing_alert(user['email'], user['name'], shown)
                    except Exception:
                        logger.exception('[vip-push] channel delivery failed')
                        sent = False
                    if sent:
                        for listing in shown:
                            _log_notify(conn, uid, listing['id'], channel, listing.get('price_ty'),
                                        listing.get('source_status'), listing['_notification_event'])
                            conn.execute("DELETE FROM notification_log WHERE user_id=? AND listing_id=? AND channel=? AND event_kind='pending'",
                                         (uid, listing['id'], channel))
                        conn.execute("UPDATE user_watchlists SET last_notified_at=datetime('now') WHERE user_id=? AND active=1", (uid,))
                        # Commit each successful channel so a later failure cannot
                        # erase the success and cause the whole digest to repeat.
                        conn.commit()
                        stats['telegram_sent' if channel == 'telegram' else 'email_users'] += len(shown) if channel == 'telegram' else 1
                    else:
                        for listing in shown:
                            _mark_pending(conn, uid, listing['id'], channel)
                        conn.commit()
                if matched:
                    stats['matched_users'] += 1

    except Exception as e:
        stats['failed'] = True
        logger.exception(f"[vip-push] failed: {e}")
    logger.info(f"[vip-push] done: {stats}")
    return stats
