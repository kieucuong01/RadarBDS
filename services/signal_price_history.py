"""Price evidence for one page of Săn Deal cards."""

from datetime import date
from math import isfinite

from cleansing.dedup import _has_reliable_lot_signature
from db.listings import _same_price_snapshot


_LOT_FIELDS = (
    "source", "source_id", "title", "description", "road_name", "ward",
    "property_type", "area_m2", "frontage_m", "depth_m", "tho_cu_m2",
    "contact_phone", "price_ty", "posted_at",
)
_LOT_COLUMNS = ", ".join(_LOT_FIELDS)


def _day(value):
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _comparison(kind, before, now, observed_day):
    pct = (now - before) / before * 100
    if not isfinite(pct) or pct < -40:
        return {"kind": "uncertain"}
    return {
        "kind": kind, "previous_price_ty": before,
        "change_pct": round(pct, 2), "date": observed_day.isoformat(),
    }


def _price_evidence(anchor, snapshots, reposts):
    current = anchor["price_ty"]
    if not current or current <= 0 or not isfinite(current):
        return None
    # Changing the unit price can create a snapshot with the same total.
    # A snapshot records an observation, never a separate post.
    observed_day = None
    if snapshots and not _same_price_snapshot(snapshots[0]["price_ty"], current):
        return None
    for snapshot in snapshots:
        price = snapshot["price_ty"]
        day = _day(snapshot["recorded_at"])
        if not day or not price or price <= 0 or not isfinite(price):
            return None
        if not _same_price_snapshot(price, current):
            return _comparison("same_post", price, current, observed_day)
        observed_day = day

    posted = _day(anchor["posted_at"])
    latest_repost = None
    for older in reposts:
        prior_day = _day(older["posted_at"])
        if not posted or not prior_day or prior_day >= posted:
            continue
        if latest_repost and prior_day < latest_repost[0]:
            break
        previous = older["price_ty"]
        if not previous or previous <= 0 or not isfinite(previous):
            continue
        equal = _same_price_snapshot(current, previous)
        if _has_reliable_lot_signature(anchor, older, allow_facebook_same_price=equal):
            if latest_repost and not _same_price_snapshot(latest_repost[1], previous):
                return {"kind": "uncertain"}
            latest_repost = (prior_day, previous)
    if latest_repost:
        return _comparison("repost", latest_repost[1], current, posted)
    if len(snapshots) > 1:
        return {"kind": "same_price"}
    return None


def load_card_price_history(conn, cards, tier):
    prices = {
        row["id"]: row["price_ty"] for row in cards
        if row["source"] == "facebook" or tier == "admin"
    }
    if not prices:
        return {}
    # Limit history work to the returned page. Keep identifiers, broker data
    # and text used for lot matching strictly inside the service.
    rows = conn.execute(f"""
        SELECT l.id, {", ".join("l." + name for name in _LOT_FIELDS)},
               snap.items AS snapshots, repost.items AS reposts
        FROM listings l
        LEFT JOIN LATERAL (
            SELECT json_agg(s ORDER BY s.recorded_at DESC, s.id DESC) AS items
            FROM (
                SELECT id, recorded_at, price_ty FROM price_history
                WHERE listing_id = l.id ORDER BY recorded_at DESC, id DESC LIMIT 8
            ) s
        ) snap ON TRUE
        LEFT JOIN LATERAL (
            SELECT json_agg(p ORDER BY p.posted_at DESC, p.id DESC) AS items
            FROM (
                SELECT id, {_LOT_COLUMNS} FROM listings old
                WHERE old.duplicate_of_id = l.id AND l.source = 'facebook'
                  AND old.source = l.source AND old.source_id <> l.source_id
                  AND old.source_id <> '' AND l.source_id <> ''
                  AND old.posted_at < l.posted_at
                  AND (old.price_updated_at IS NULL OR
                       CAST(old.price_updated_at AT TIME ZONE 'Asia/Ho_Chi_Minh' AS date)::text < LEFT(l.posted_at, 10))
                  AND COALESCE(old.review_hidden, 0) = 0 AND COALESCE(old.is_blacklisted, 0) = 0
                  AND COALESCE(old.probably_sold, 0) = 0 AND COALESCE(old.suspicious_bait, 0) = 0
                  AND COALESCE(old.extraction_quality_flags, '') !~ 'ambiguous_price_text|multi_lot_listing'
                ORDER BY old.posted_at DESC, old.id DESC LIMIT 8
            ) p
        ) repost ON TRUE
        WHERE l.id = ANY(?) AND (l.source = 'facebook' OR ?)
          AND COALESCE(l.review_hidden, 0) = 0 AND COALESCE(l.is_blacklisted, 0) = 0
          AND COALESCE(l.suspicious_bait, 0) = 0
          AND COALESCE(l.extraction_quality_flags, '') !~ 'ambiguous_price_text|multi_lot_listing'
    """, (list(prices), tier == "admin")).fetchall()
    evidence = {}
    for row in rows:
        if _same_price_snapshot(prices[row["id"]], row["price_ty"]):
            evidence[row["id"]] = _price_evidence(row, row["snapshots"] or [], row["reposts"] or [])
    return evidence
