"""Read-only growth metrics for the admin dashboard."""
from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from config import database_sqlite as db_mod
from services.signal_quality import (
    LATEST_VALUATION_CTE,
    actionable_listing_sql,
    actionable_signal_sql,
)

LOCAL_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
VALID_PERIODS = {"day", "week", "month", "year"}


def _period_bounds(period: str, anchor: date):
    if period == "day":
        start = anchor
        end = start + timedelta(days=1)
        previous = start - timedelta(days=1)
        bucket = "hour"
    elif period == "week":
        start = anchor - timedelta(days=anchor.weekday())
        end = start + timedelta(days=7)
        previous = start - timedelta(days=7)
        bucket = "day"
    elif period == "month":
        start = anchor.replace(day=1)
        end = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        previous = (start - timedelta(days=1)).replace(day=1)
        bucket = "day"
    else:
        start = anchor.replace(month=1, day=1)
        end = start.replace(year=start.year + 1)
        previous = start.replace(year=start.year - 1)
        bucket = "month"
    return (
        datetime.combine(start, time.min, LOCAL_TZ),
        datetime.combine(end, time.min, LOCAL_TZ),
        datetime.combine(previous, time.min, LOCAL_TZ),
        bucket,
    )


def _local(value):
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(LOCAL_TZ)


def _event(row, field="event_at"):
    return {"at": _local(row[field]), "source": row.get("source"), "status": row.get("status")}


def _in(events, start, end):
    return [event for event in events if event["at"] and start <= event["at"] < end]


def _summary(events, start, end, previous, sources=(), source_breakdown=False):
    current_events = _in(events, start, end)
    previous_events = _in(events, previous, start)
    current = len(current_events)
    previous_count = len(previous_events)
    result = {
        "current": current,
        "previous": previous_count,
        "delta_pct": None if previous_count == 0 else round((current - previous_count) * 100 / previous_count, 1),
        "overall": len(events),
    }
    if source_breakdown:
        result["by_source"] = {
            source: {
                "current": sum(event["source"] == source for event in current_events),
                "previous": sum(event["source"] == source for event in previous_events),
                "overall": sum(event["source"] == source for event in events),
            }
            for source in sources
        }
    return result


def _buckets(start, end, bucket):
    cursor = start
    rows = []
    while cursor < end:
        if bucket == "hour":
            next_cursor = cursor + timedelta(hours=1)
            label = cursor.strftime("%H:00")
        elif bucket == "day":
            next_cursor = cursor + timedelta(days=1)
            label = cursor.strftime("%d/%m")
        else:
            year = cursor.year + (1 if cursor.month == 12 else 0)
            month = 1 if cursor.month == 12 else cursor.month + 1
            next_cursor = cursor.replace(year=year, month=month)
            label = f"Th?ng {cursor.month}"
        rows.append((cursor, next_cursor, label))
        cursor = next_cursor
    return rows


def _count(events, start, end, source=None):
    return sum(
        start <= event["at"] < end and (source is None or event["source"] == source)
        for event in events
        if event["at"]
    )


def get_growth_dashboard(period: str, anchor: date, include_guland: bool = False):
    if period not in VALID_PERIODS:
        raise ValueError("invalid_period")
    sources = ("facebook", "guland") if include_guland else ("facebook",)
    marks = ",".join("?" for _ in sources)
    start, end, previous, bucket = _period_bounds(period, anchor)

    # ponytail: aggregate these small admin datasets in Python while the corpus is
    # ~17k rows; move bucketing into SQL only after measured endpoint latency warrants it.
    with db_mod.get_conn() as conn:
        raw = conn.execute(
            f"SELECT crawled_at AS event_at, source FROM raw_listings WHERE source IN ({marks})",
            sources,
        ).fetchall()
        listings = conn.execute(
            f"""SELECT COALESCE(first_seen_at, crawled_at) AS event_at, source, duplicate_of_id
                FROM listings WHERE source IN ({marks})""",
            sources,
        ).fetchall()
        signals = conn.execute(
            f"""WITH {LATEST_VALUATION_CTE}
                SELECT COALESCE(l.first_seen_at, l.crawled_at) AS event_at, l.source
                FROM listings l JOIN latest_valuation v ON v.listing_id=l.id
                WHERE l.source IN ({marks})
                  AND {actionable_signal_sql("v")}
                  AND {actionable_listing_sql("l")}""",
            sources,
        ).fetchall()
        drops = conn.execute(
            f"""WITH first_prices AS (
                    SELECT l.id, l.source, COALESCE(l.price_first_ty,
                        (SELECT ph0.price_ty FROM price_history ph0
                         WHERE ph0.listing_id=l.id AND ph0.price_ty>0
                         ORDER BY ph0.recorded_at, ph0.id LIMIT 1)) AS first_price
                    FROM listings l WHERE l.source IN ({marks})
                )
                SELECT fp.source, MIN(ph.recorded_at) AS event_at
                FROM first_prices fp JOIN price_history ph ON ph.listing_id=fp.id
                WHERE fp.first_price>0 AND ph.price_ty>0
                  AND (fp.first_price-ph.price_ty)/fp.first_price BETWEEN 0.01 AND 0.40
                GROUP BY fp.id, fp.source""",
            sources,
        ).fetchall()
        signups = conn.execute("SELECT created_at AS event_at FROM users").fetchall()
        leads = conn.execute(
            """SELECT lc.created_at AS event_at, l.source, lc.status
               FROM lead_captures lc LEFT JOIN listings l ON l.id=lc.listing_id"""
        ).fetchall()
        active_rows = conn.execute(
            """SELECT ual.user_id, ual.created_at AS event_at FROM user_audit_log ual
               JOIN users u ON u.id=ual.user_id WHERE COALESCE(u.tier,'')!='admin'"""
        ).fetchall()

    raw_events = [_event(row) for row in raw]
    listing_events = [_event(row) for row in listings]
    unique_events = [_event(row) for row in listings if row["duplicate_of_id"] is None]
    signal_events = [_event(row) for row in signals]
    drop_events = [_event(row) for row in drops]
    signup_events = [_event(row) for row in signups]
    lead_events = [_event(row) for row in leads if row["source"] in sources]
    unattributed = [_event(row) for row in leads if row["source"] is None]
    active = len({row["user_id"] for row in active_rows if start <= _local(row["event_at"]) < end})

    summary = {
        "crawled": _summary(raw_events, start, end, previous, sources, True),
        "signals": _summary(signal_events, start, end, previous, sources, True),
        "price_drops": _summary(drop_events, start, end, previous, sources, True),
        "unique_lots": _summary(unique_events, start, end, previous, sources, True),
        "signups": _summary(signup_events, start, end, previous),
        "leads": _summary(lead_events, start, end, previous, sources, True),
    }
    summary["leads"]["unattributed_current"] = len(_in(unattributed, start, end))
    summary["leads"]["unattributed_previous"] = len(_in(unattributed, previous, start))

    processed = len(_in(listing_events, start, end))
    selected_leads = _in(lead_events, start, end)
    deposits = sum((event["status"] or "").lower() in {"deposit", "deposited"} for event in selected_leads)
    pct = lambda numerator, denominator: round(numerator * 100 / denominator, 1) if denominator else None
    ratios = {
        "signal_yield_pct": pct(summary["signals"]["current"], processed),
        "unique_lot_yield_pct": pct(summary["unique_lots"]["current"], processed),
        "active_users": active,
        "lead_to_deposit_pct": pct(deposits, len(selected_leads)),
    }

    series = []
    for left, right, label in _buckets(start, end, bucket):
        row = {
            "key": left.isoformat(),
            "label": label,
            "crawled": _count(raw_events, left, right),
            "signals": _count(signal_events, left, right),
            "unique_lots": _count(unique_events, left, right),
            "price_drops": _count(drop_events, left, right),
            "signups": _count(signup_events, left, right),
            "leads": _count(lead_events, left, right),
        }
        row["by_source"] = {
            source: {
                "crawled": _count(raw_events, left, right, source),
                "signals": _count(signal_events, left, right, source),
                "unique_lots": _count(unique_events, left, right, source),
                "price_drops": _count(drop_events, left, right, source),
                "leads": _count(lead_events, left, right, source),
            }
            for source in sources
        }
        series.append(row)

    return {
        "filters": {"period": period, "anchor": anchor.isoformat(), "sources": list(sources), "include_guland": include_guland},
        "range": {
            "current_start": start.isoformat(), "current_end": end.isoformat(),
            "previous_start": previous.isoformat(), "previous_end": start.isoformat(),
            "timezone": "Asia/Ho_Chi_Minh", "bucket": bucket,
        },
        "summary": summary,
        "ratios": ratios,
        "series": series,
    }

