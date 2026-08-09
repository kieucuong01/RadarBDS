"""Read-only growth metrics for the admin dashboard."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from config import database_sqlite as db_mod
from services.admin_marketing import build_marketing_source_view
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


def _storage_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")


def _counts_by_source(rows, sources) -> dict:
    counts = {source: 0 for source in sources}
    for row in rows:
        source = row["source"]
        if source in counts:
            counts[source] = int(row["n"] or 0)
    return counts


def _count_value(row) -> int:
    return int(row["n"] or 0) if row else 0


def _summary(events, start, end, previous, sources=(), source_breakdown=False, overall=None, source_overall=None):
    current_events = _in(events, start, end)
    previous_events = _in(events, previous, start)
    current = len(current_events)
    previous_count = len(previous_events)
    result = {
        "current": current,
        "previous": previous_count,
        "delta_pct": None if previous_count == 0 else round((current - previous_count) * 100 / previous_count, 1),
        "overall": len(events) if overall is None else int(overall or 0),
    }
    if source_breakdown:
        source_overall = source_overall or {}
        result["by_source"] = {
            source: {
                "current": sum(event["source"] == source for event in current_events),
                "previous": sum(event["source"] == source for event in previous_events),
                "overall": int(source_overall.get(source, 0)),
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
    start_iso = _storage_iso(start)
    previous_iso = _storage_iso(previous)
    end_iso = _storage_iso(end)

    with db_mod.get_conn() as conn:
        raw = conn.execute(
            f"""SELECT crawled_at AS event_at, source
                FROM raw_listings
                WHERE source IN ({marks})
                  AND crawled_at >= ?
                  AND crawled_at < ?""",
            sources + (previous_iso, end_iso),
        ).fetchall()
        raw_overall = _counts_by_source(conn.execute(
            f"""SELECT source, COUNT(*) AS n
                FROM raw_listings
                WHERE source IN ({marks})
                GROUP BY source""",
            sources,
        ).fetchall(), sources)
        raw_total = sum(raw_overall.values())

        listing_event_expr = "COALESCE(first_seen_at, crawled_at)"
        listings = conn.execute(
            f"""SELECT {listing_event_expr} AS event_at, source, duplicate_of_id
                FROM listings
                WHERE source IN ({marks})
                  AND {listing_event_expr} >= ?
                  AND {listing_event_expr} < ?""",
            sources + (previous_iso, end_iso),
        ).fetchall()
        unique_overall = _counts_by_source(conn.execute(
            f"""SELECT source, COUNT(*) AS n
                FROM listings
                WHERE source IN ({marks})
                  AND duplicate_of_id IS NULL
                GROUP BY source""",
            sources,
        ).fetchall(), sources)

        signal_event_expr = "COALESCE(l.first_seen_at, l.crawled_at)"
        signals = conn.execute(
            f"""WITH {LATEST_VALUATION_CTE}
                SELECT {signal_event_expr} AS event_at, l.source
                FROM listings l JOIN latest_valuation v ON v.listing_id=l.id
                WHERE l.source IN ({marks})
                  AND {actionable_signal_sql("v")}
                  AND {actionable_listing_sql("l")}
                  AND {signal_event_expr} >= ?
                  AND {signal_event_expr} < ?""",
            sources + (previous_iso, end_iso),
        ).fetchall()
        signals_overall = _counts_by_source(conn.execute(
            f"""WITH {LATEST_VALUATION_CTE}
                SELECT l.source, COUNT(*) AS n
                FROM listings l JOIN latest_valuation v ON v.listing_id=l.id
                WHERE l.source IN ({marks})
                  AND {actionable_signal_sql("v")}
                  AND {actionable_listing_sql("l")}
                GROUP BY l.source""",
            sources,
        ).fetchall(), sources)

        drop_events_cte = f"""WITH first_prices AS (
                    SELECT l.id, l.source, COALESCE(l.price_first_ty,
                        (SELECT ph0.price_ty FROM price_history ph0
                         WHERE ph0.listing_id=l.id AND ph0.price_ty>0
                         ORDER BY ph0.recorded_at, ph0.id LIMIT 1)) AS first_price
                    FROM listings l WHERE l.source IN ({marks})
                ),
                drop_events AS (
                    SELECT fp.id, fp.source, MIN(ph.recorded_at) AS event_at
                    FROM first_prices fp JOIN price_history ph ON ph.listing_id=fp.id
                    WHERE fp.first_price>0 AND ph.price_ty>0
                      AND (fp.first_price-ph.price_ty)/fp.first_price BETWEEN 0.01 AND 0.40
                    GROUP BY fp.id, fp.source
                )"""
        drops = conn.execute(
            f"""{drop_events_cte}
                SELECT source, event_at
                FROM drop_events
                WHERE event_at >= ?
                  AND event_at < ?""",
            sources + (previous_iso, end_iso),
        ).fetchall()
        drops_overall = _counts_by_source(conn.execute(
            f"""{drop_events_cte}
                SELECT source, COUNT(*) AS n
                FROM drop_events
                GROUP BY source""",
            sources,
        ).fetchall(), sources)

        signups = conn.execute(
            """SELECT created_at AS event_at
               FROM users
               WHERE created_at >= ?
                 AND created_at < ?""",
            (previous_iso, end_iso),
        ).fetchall()
        signups_total = _count_value(conn.execute("SELECT COUNT(*) AS n FROM users").fetchone())

        leads = conn.execute(
            """SELECT lc.created_at AS event_at, l.source, lc.status
               FROM lead_captures lc LEFT JOIN listings l ON l.id=lc.listing_id
               WHERE lc.created_at >= ?
                 AND lc.created_at < ?
                 AND (l.source IN ({marks}) OR l.source IS NULL)""".format(marks=marks),
            (previous_iso, end_iso) + sources,
        ).fetchall()
        leads_overall = _counts_by_source(conn.execute(
            f"""SELECT l.source, COUNT(*) AS n
                FROM lead_captures lc JOIN listings l ON l.id=lc.listing_id
                WHERE l.source IN ({marks})
                GROUP BY l.source""",
            sources,
        ).fetchall(), sources)

        active = _count_value(conn.execute(
            """SELECT COUNT(DISTINCT ual.user_id) AS n
               FROM user_audit_log ual
               JOIN users u ON u.id=ual.user_id
               WHERE COALESCE(u.tier,'')!='admin'
                 AND ual.created_at >= ?
                 AND ual.created_at < ?""",
            (start_iso, end_iso),
        ).fetchone())

        processed = _count_value(conn.execute(
            f"""SELECT COUNT(*) AS n
                FROM listings
                WHERE source IN ({marks})
                  AND {listing_event_expr} >= ?
                  AND {listing_event_expr} < ?""",
            sources + (start_iso, end_iso),
        ).fetchone())
        selected_lead_counts = conn.execute(
            """SELECT COUNT(*) AS n,
                      SUM(CASE WHEN LOWER(COALESCE(lc.status,'')) IN ('deposit','deposited') THEN 1 ELSE 0 END) AS deposits
               FROM lead_captures lc JOIN listings l ON l.id=lc.listing_id
               WHERE l.source IN ({marks})
                 AND lc.created_at >= ?
                 AND lc.created_at < ?""".format(marks=marks),
            sources + (start_iso, end_iso),
        ).fetchone()
        marketing = build_marketing_source_view(
            conn,
            start=start,
            end=end,
            previous=previous,
        )

    raw_events = [_event(row) for row in raw]
    listing_events = [_event(row) for row in listings]
    unique_events = [_event(row) for row in listings if row["duplicate_of_id"] is None]
    signal_events = [_event(row) for row in signals]
    drop_events = [_event(row) for row in drops]
    signup_events = [_event(row) for row in signups]
    lead_events = [_event(row) for row in leads if row["source"] in sources]
    unattributed = [_event(row) for row in leads if row["source"] is None]

    summary = {
        "crawled": _summary(raw_events, start, end, previous, sources, True, raw_total, raw_overall),
        "signals": _summary(signal_events, start, end, previous, sources, True, sum(signals_overall.values()), signals_overall),
        "price_drops": _summary(drop_events, start, end, previous, sources, True, sum(drops_overall.values()), drops_overall),
        "unique_lots": _summary(unique_events, start, end, previous, sources, True, sum(unique_overall.values()), unique_overall),
        "signups": _summary(signup_events, start, end, previous, overall=signups_total),
        "leads": _summary(lead_events, start, end, previous, sources, True, sum(leads_overall.values()), leads_overall),
    }
    summary["leads"]["unattributed_current"] = len(_in(unattributed, start, end))
    summary["leads"]["unattributed_previous"] = len(_in(unattributed, previous, start))

    selected_lead_count = _count_value(selected_lead_counts)
    deposits = int(selected_lead_counts["deposits"] or 0) if selected_lead_counts else 0
    pct = lambda numerator, denominator: round(numerator * 100 / denominator, 1) if denominator else None
    ratios = {
        "signal_yield_pct": pct(summary["signals"]["current"], processed),
        "unique_lot_yield_pct": pct(summary["unique_lots"]["current"], processed),
        "active_users": active,
        "lead_to_deposit_pct": pct(deposits, selected_lead_count),
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
        "marketing": marketing,
    }

