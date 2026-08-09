"""Bounded, PII-free marketing-source aggregation for the admin dashboard."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit

from config.settings import PUBLIC_BASE_URL
from services.marketing_tracking import (
    CHANNELS,
    MARKETING_TRACK_ACTIONS,
    sanitize_marketing_context,
)


_AUDIT_ROW_CAP = 20_000
_LEAD_ROW_CAP = 5_000
_VIEW_ACTIONS = frozenset({"seo_landing_viewed", "report_viewed"})
_CHANNEL_ORDER = (
    "organic",
    "social",
    "ai",
    "direct_unknown",
    "legacy_unknown",
)
_CAMPAIGN_FIELDS = ("utm_source", "utm_medium", "utm_campaign")
_MARKETING_SOURCE_PREFIXES = (
    "ai_",
    "campaign_",
    "landing_",
    "marketing_",
    "report_",
    "seo_",
    "social_",
)
_LEAD_STATUSES = frozenset(
    {"new", "called", "viewing", "deposit", "deposited", "cancelled"}
)


def _safe_context(value: object) -> dict[str, object]:
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _as_utc(value: object) -> datetime | None:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _storage_iso(value: datetime) -> str:
    normalized = _as_utc(value)
    if normalized is None:
        raise ValueError("marketing bounds must be datetimes")
    return normalized.replace(tzinfo=None).isoformat(timespec="seconds")


def _period_key(
    value: object,
    *,
    start: datetime,
    end: datetime,
    previous: datetime,
) -> str | None:
    at = _as_utc(value)
    if at is None:
        return None
    start_utc = _as_utc(start)
    end_utc = _as_utc(end)
    previous_utc = _as_utc(previous)
    if start_utc is None or end_utc is None or previous_utc is None:
        return None
    if start_utc <= at < end_utc:
        return "current"
    if previous_utc <= at < start_utc:
        return "previous"
    return None


def _campaign_key(
    context: dict[str, object],
) -> tuple[str, str, str] | None:
    values = tuple(str(context.get(field) or "") for field in _CAMPAIGN_FIELDS)
    return values if any(values) else None


def _public_hosts() -> frozenset[str]:
    configured = (urlsplit(PUBLIC_BASE_URL).hostname or "radarbds.vn").lower()
    bare = configured[4:] if configured.startswith("www.") else configured
    return frozenset({bare, f"www.{bare}"})


def _lead_url_attribution(value: object) -> dict[str, str]:
    if not isinstance(value, str) or not value.strip():
        return {}
    candidate = value.strip()
    try:
        parsed = urlsplit(candidate)
    except ValueError:
        return {}
    if parsed.username or parsed.password:
        return {}
    if parsed.scheme or parsed.netloc:
        if (
            parsed.scheme.lower() not in {"http", "https"}
            or not parsed.hostname
            or parsed.hostname.lower() not in _public_hosts()
        ):
            return {}
    elif not candidate.startswith("/") or candidate.startswith("//"):
        return {}

    query = parse_qs(parsed.query, keep_blank_values=False)
    context: dict[str, object] = {"page_path": parsed.path or "/"}
    for field in (*_CAMPAIGN_FIELDS, "utm_content", "utm_term"):
        values = query.get(field)
        if values:
            context[field] = values[0]
    safe = sanitize_marketing_context("lead_capture_submit", context)
    return {key: str(value) for key, value in safe.items()}


def _marketing_source_context(value: object) -> str | None:
    safe = sanitize_marketing_context(
        "lead_capture_submit",
        {"source_context": value},
    )
    source_context = str(safe.get("source_context") or "")
    if source_context.startswith(_MARKETING_SOURCE_PREFIXES):
        return source_context
    return None


def _lead_status(value: object) -> str:
    status = str(value or "").strip().lower()
    return status if status in _LEAD_STATUSES else "other"


def _new_landing_stats() -> dict[str, int]:
    return {
        "current_views": 0,
        "previous_views": 0,
        "direct_lead_events": 0,
        "direct_lead_rows": 0,
    }


def _new_campaign_stats() -> dict[str, int]:
    return {
        "current_views": 0,
        "previous_views": 0,
        "cta_clicks": 0,
        "direct_lead_events": 0,
        "direct_lead_rows": 0,
    }


def _increment_period(stats: dict[str, int], prefix: str, period: str) -> None:
    stats[f"{period}_{prefix}"] += 1


def build_marketing_source_view(
    conn,
    *,
    start: datetime,
    end: datetime,
    previous: datetime,
    limit: int = 20,
) -> dict[str, object]:
    """Aggregate direct first-party evidence without reconstructing user journeys."""
    display_limit = min(max(int(limit), 1), 100)
    previous_iso = _storage_iso(previous)
    end_iso = _storage_iso(end)
    actions = tuple(sorted(MARKETING_TRACK_ACTIONS))
    marks = ",".join("?" for _ in actions)

    audit_rows = conn.execute(
        f"""SELECT action, context, created_at
            FROM user_audit_log
            WHERE action IN ({marks})
              AND created_at >= ?
              AND created_at < ?
            ORDER BY created_at ASC
            LIMIT {_AUDIT_ROW_CAP}""",
        actions + (previous_iso, end_iso),
    ).fetchall()
    lead_rows = conn.execute(
        f"""SELECT created_at, listing_url, source_context, status
            FROM lead_captures
            WHERE created_at >= ?
              AND created_at < ?
            ORDER BY created_at ASC
            LIMIT {_LEAD_ROW_CAP}""",
        (previous_iso, end_iso),
    ).fetchall()

    channel_counts = {
        channel: {"current": 0, "previous": 0}
        for channel in _CHANNEL_ORDER
    }
    landing_stats: defaultdict[str, dict[str, int]] = defaultdict(
        _new_landing_stats
    )
    campaign_stats: defaultdict[tuple[str, str, str], dict[str, int]] = (
        defaultdict(_new_campaign_stats)
    )
    cta_stats: defaultdict[tuple[str, str], dict[str, int]] = defaultdict(
        lambda: {"current": 0, "previous": 0}
    )
    direct = {
        "lead_events_current": 0,
        "lead_events_previous": 0,
        "lead_rows_current": 0,
        "lead_rows_previous": 0,
    }
    unattributed = {
        "lead_events_current": 0,
        "lead_events_previous": 0,
        "lead_rows_current": 0,
        "lead_rows_previous": 0,
    }
    direct_statuses = {
        "current": defaultdict(int),
        "previous": defaultdict(int),
    }
    canonical_times: list[datetime] = []
    stable_views = 0
    legacy_views = 0

    for row in audit_rows:
        action = str(row.get("action") or "")
        period = _period_key(
            row.get("created_at"),
            start=start,
            end=end,
            previous=previous,
        )
        if period is None:
            continue
        context = sanitize_marketing_context(
            action,
            _safe_context(row.get("context")),
        )

        if action in _VIEW_ACTIONS:
            channel = str(context.get("channel") or "")
            if channel in CHANNELS:
                stable_views += 1
            else:
                channel = "legacy_unknown"
                legacy_views += 1
            channel_counts[channel][period] += 1
            at = _as_utc(row.get("created_at"))
            if at is not None:
                canonical_times.append(at)
            path = str(context.get("path") or context.get("page_path") or "")
            if path:
                _increment_period(landing_stats[path], "views", period)
            campaign = _campaign_key(context)
            if campaign is not None:
                _increment_period(campaign_stats[campaign], "views", period)
            continue

        if action == "cta_clicked":
            name = str(
                context.get("cta_name")
                or context.get("location")
                or context.get("source_surface")
                or ""
            )
            destination = str(context.get("destination") or "")
            if not name and not destination:
                continue
            name = name or "unknown"
            destination = destination or "unknown"
            cta_stats[(name, destination)][period] += 1
            campaign = _campaign_key(context)
            if campaign is not None and period == "current":
                campaign_stats[campaign]["cta_clicks"] += 1
            continue

        if action == "lead_capture_submit":
            path = str(context.get("page_path") or context.get("path") or "")
            campaign = _campaign_key(context)
            directly_attributed = bool(path or campaign)
            target = direct if directly_attributed else unattributed
            target[f"lead_events_{period}"] += 1
            if directly_attributed and period == "current":
                if path:
                    landing_stats[path]["direct_lead_events"] += 1
                if campaign is not None:
                    campaign_stats[campaign]["direct_lead_events"] += 1

    for row in lead_rows:
        period = _period_key(
            row.get("created_at"),
            start=start,
            end=end,
            previous=previous,
        )
        if period is None:
            continue
        attribution = _lead_url_attribution(row.get("listing_url"))
        source_context = row.get("source_context")
        if not attribution and isinstance(source_context, str):
            attribution = _lead_url_attribution(source_context)
        marketing_source = _marketing_source_context(source_context)
        path = str(attribution.get("page_path") or "")
        campaign = _campaign_key(attribution)
        directly_attributed = bool(path or campaign or marketing_source)
        target = direct if directly_attributed else unattributed
        target[f"lead_rows_{period}"] += 1
        if directly_attributed:
            direct_statuses[period][_lead_status(row.get("status"))] += 1
            if period == "current":
                if path:
                    landing_stats[path]["direct_lead_rows"] += 1
                if campaign is not None:
                    campaign_stats[campaign]["direct_lead_rows"] += 1

    channels = [
        {
            "channel": channel,
            "current_views": channel_counts[channel]["current"],
            "previous_views": channel_counts[channel]["previous"],
        }
        for channel in _CHANNEL_ORDER
    ]
    landing_pages = [
        {"path": path, **stats}
        for path, stats in sorted(
            landing_stats.items(),
            key=lambda item: (-item[1]["current_views"], item[0]),
        )[:display_limit]
    ]
    campaigns = [
        {
            "utm_source": campaign[0],
            "utm_medium": campaign[1],
            "utm_campaign": campaign[2],
            **stats,
        }
        for campaign, stats in sorted(
            campaign_stats.items(),
            key=lambda item: (
                -item[1]["current_views"],
                -item[1]["cta_clicks"],
                item[0],
            ),
        )[:display_limit]
    ]
    cta_targets = [
        {
            "cta_name": key[0],
            "destination": key[1],
            "current_clicks": counts["current"],
            "previous_clicks": counts["previous"],
        }
        for key, counts in sorted(
            cta_stats.items(),
            key=lambda item: (-item[1]["current"], item[0]),
        )[:display_limit]
    ]

    direct["lead_statuses_current"] = dict(
        sorted(direct_statuses["current"].items())
    )
    direct["lead_statuses_previous"] = dict(
        sorted(direct_statuses["previous"].items())
    )
    event_count = stable_views + legacy_views
    return {
        "coverage": {
            "event_count": event_count,
            "with_stable_channel": stable_views,
            "without_stable_channel": legacy_views,
            "audit_rows_scanned": len(audit_rows),
            "lead_rows_scanned": len(lead_rows),
            "first_event_at": (
                min(canonical_times).isoformat() if canonical_times else None
            ),
            "last_event_at": (
                max(canonical_times).isoformat() if canonical_times else None
            ),
            "truncated": (
                len(audit_rows) >= _AUDIT_ROW_CAP
                or len(lead_rows) >= _LEAD_ROW_CAP
            ),
        },
        "channels": channels,
        "landing_pages": landing_pages,
        "campaigns": campaigns,
        "cta_targets": cta_targets,
        "directly_attributed": direct,
        "unattributed": unattributed,
    }
