from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from services.admin_marketing import build_marketing_source_view


START = datetime(2026, 8, 8, tzinfo=timezone.utc)
END = START + timedelta(days=1)
PREVIOUS = START - timedelta(days=1)


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _FixtureConnection:
    def __init__(self, audit_rows=(), lead_rows=()):
        self.audit_rows = list(audit_rows)
        self.lead_rows = list(lead_rows)
        self.queries = []

    def execute(self, sql, params=()):
        self.queries.append((sql, tuple(params)))
        if "FROM user_audit_log" in sql:
            return _Rows(self.audit_rows)
        if "FROM lead_captures" in sql:
            return _Rows(self.lead_rows)
        raise AssertionError(f"unexpected SQL: {sql}")


def _audit(action, context, at):
    return {
        "action": action,
        "context": context if isinstance(context, str) else json.dumps(context),
        "created_at": at,
    }


def _lead(at, *, listing_url="", source_context="", status="new"):
    return {
        "created_at": at,
        "listing_url": listing_url,
        "source_context": source_context,
        "status": status,
    }


def _fixture_connection():
    audit_rows = [
        _audit(
            "seo_landing_viewed",
            {
                "path": "/organic",
                "channel": "organic",
                "utm_source": "google",
                "utm_medium": "organic",
                "utm_campaign": "seo",
            },
            PREVIOUS + timedelta(hours=1),
        ),
        _audit(
            "seo_landing_viewed",
            {
                "path": "/organic",
                "channel": "organic",
                "utm_source": "google",
                "utm_medium": "organic",
                "utm_campaign": "seo",
            },
            START + timedelta(hours=1),
        ),
        _audit(
            "seo_landing_viewed",
            {
                "path": "/social",
                "channel": "social",
                "utm_source": "facebook",
                "utm_medium": "social",
                "utm_campaign": "ward_launch",
            },
            START + timedelta(hours=2),
        ),
        _audit(
            "report_viewed",
            {"path": "/ai", "channel": "ai", "ai_source": "chatgpt"},
            START + timedelta(hours=3),
        ),
        _audit(
            "seo_landing_viewed",
            {"path": "/direct", "channel": "direct_unknown"},
            START + timedelta(hours=4),
        ),
        _audit(
            "seo_landing_viewed",
            {
                "path": "/legacy",
                "phone": "0900000000",
                "email": "private@example.test",
            },
            START + timedelta(hours=5),
        ),
        _audit(
            "social_utm_visit",
            {"utm_source": "facebook", "utm_medium": "social"},
            START + timedelta(hours=6),
        ),
        _audit(
            "cta_clicked",
            {
                "cta_name": "signal_contact",
                "destination": "/?tab=signals",
                "utm_source": "facebook",
                "utm_medium": "social",
                "utm_campaign": "ward_launch",
                "user_agent": "private browser",
            },
            START + timedelta(hours=7),
        ),
        _audit(
            "lead_capture_submit",
            {
                "page_path": "/social",
                "utm_source": "facebook",
                "utm_medium": "social",
                "utm_campaign": "ward_launch",
                "note": "private note",
            },
            START + timedelta(hours=8),
        ),
        _audit(
            "lead_capture_submit",
            {"source_context": "seo_report_lead"},
            START + timedelta(hours=9),
        ),
        _audit("cta_clicked", "{malformed-json", START + timedelta(hours=10)),
    ]
    lead_rows = [
        _lead(
            START + timedelta(hours=11),
            listing_url=(
                "https://radarbds.vn/social?utm_source=facebook"
                "&utm_medium=social&utm_campaign=ward_launch"
                "&email=private%40example.test"
            ),
            source_context="seo_report_lead",
            status="new",
        ),
        _lead(
            START + timedelta(hours=12),
            source_context="seo_report_lead",
            status="viewing",
        ),
        _lead(
            START + timedelta(hours=13),
            source_context="card_signal",
            status="deposit",
        ),
        _lead(
            START + timedelta(hours=14),
            listing_url="https://private@example.test/secret?phone=0900000000",
            source_context="unknown",
            status="new",
        ),
        _lead(
            PREVIOUS + timedelta(hours=12),
            listing_url="/organic?utm_source=google&utm_medium=organic&utm_campaign=seo",
            source_context="seo_landing_lead",
            status="called",
        ),
    ]
    return _FixtureConnection(audit_rows, lead_rows)


def test_marketing_aggregation_keeps_channels_and_direct_attribution_truthful():
    view = build_marketing_source_view(
        _fixture_connection(),
        start=START,
        end=END,
        previous=PREVIOUS,
    )

    assert [row["channel"] for row in view["channels"]] == [
        "organic",
        "social",
        "ai",
        "direct_unknown",
        "legacy_unknown",
    ]
    assert [
        (row["current_views"], row["previous_views"])
        for row in view["channels"]
    ] == [(1, 1), (1, 0), (1, 0), (1, 0), (1, 0)]
    assert view["coverage"]["event_count"] == 6
    assert view["coverage"]["with_stable_channel"] == 5
    assert view["coverage"]["without_stable_channel"] == 1
    assert view["coverage"]["truncated"] is False
    assert view["directly_attributed"] == {
        "lead_events_current": 1,
        "lead_events_previous": 0,
        "lead_rows_current": 2,
        "lead_rows_previous": 1,
        "lead_statuses_current": {"new": 1, "viewing": 1},
        "lead_statuses_previous": {"called": 1},
    }
    assert view["unattributed"] == {
        "lead_events_current": 1,
        "lead_events_previous": 0,
        "lead_rows_current": 2,
        "lead_rows_previous": 0,
    }


def test_marketing_aggregation_attributes_landing_campaign_and_cta_without_joining_people():
    view = build_marketing_source_view(
        _fixture_connection(),
        start=START,
        end=END,
        previous=PREVIOUS,
    )

    social = next(row for row in view["landing_pages"] if row["path"] == "/social")
    assert social == {
        "path": "/social",
        "current_views": 1,
        "previous_views": 0,
        "direct_lead_events": 1,
        "direct_lead_rows": 1,
    }
    campaign = next(
        row
        for row in view["campaigns"]
        if row["utm_campaign"] == "ward_launch"
    )
    assert campaign == {
        "utm_source": "facebook",
        "utm_medium": "social",
        "utm_campaign": "ward_launch",
        "current_views": 1,
        "previous_views": 0,
        "cta_clicks": 1,
        "direct_lead_events": 1,
        "direct_lead_rows": 1,
    }
    assert view["cta_targets"] == [
        {
            "cta_name": "signal_contact",
            "destination": "/",
            "current_clicks": 1,
            "previous_clicks": 0,
        }
    ]


def test_marketing_aggregation_never_serializes_seeded_pii_or_raw_urls():
    view = build_marketing_source_view(
        _fixture_connection(),
        start=START,
        end=END,
        previous=PREVIOUS,
    )
    serialized = json.dumps(view, ensure_ascii=False)

    for forbidden in (
        "0900000000",
        "private@example.test",
        "private browser",
        "private note",
        "private@example.test/secret",
        "email=",
        "phone=",
        "user_agent",
        "listing_url",
        "source_context",
    ):
        assert forbidden not in serialized


def test_marketing_queries_are_bounded_and_select_no_pii_columns():
    conn = _fixture_connection()
    build_marketing_source_view(
        conn,
        start=START,
        end=END,
        previous=PREVIOUS,
    )

    assert len(conn.queries) == 2
    audit_sql, audit_params = conn.queries[0]
    lead_sql, lead_params = conn.queries[1]
    for sql in (audit_sql, lead_sql):
        assert "created_at >= ?" in sql
        assert "created_at < ?" in sql
    assert "LIMIT 20000" in audit_sql
    assert "LIMIT 5000" in lead_sql
    assert audit_params[-2:] == lead_params[-2:]
    for forbidden in (" ip", "user_agent", "zalo_phone", "guest_email", " note"):
        assert forbidden not in f" {audit_sql.lower()}"
        assert forbidden not in f" {lead_sql.lower()}"


def test_marketing_display_rows_are_deterministically_limited():
    rows = []
    for index, count in enumerate((1, 4, 2, 5, 3)):
        for offset in range(count):
            rows.append(
                _audit(
                    "seo_landing_viewed",
                    {"path": f"/page-{index}", "channel": "organic"},
                    START + timedelta(minutes=index * 10 + offset),
                )
            )
    view = build_marketing_source_view(
        _FixtureConnection(rows, []),
        start=START,
        end=END,
        previous=PREVIOUS,
        limit=2,
    )

    assert [row["path"] for row in view["landing_pages"]] == [
        "/page-3",
        "/page-1",
    ]
    assert len(view["landing_pages"]) == 2


def test_marketing_coverage_marks_fetch_caps_as_truncated():
    audit_row = _audit(
        "seo_landing_viewed",
        {"path": "/", "channel": "direct_unknown"},
        START,
    )
    lead_row = _lead(START, source_context="card_signal")
    view = build_marketing_source_view(
        _FixtureConnection([audit_row] * 20_000, [lead_row] * 5_000),
        start=START,
        end=END,
        previous=PREVIOUS,
    )

    assert view["coverage"]["audit_rows_scanned"] == 20_000
    assert view["coverage"]["lead_rows_scanned"] == 5_000
    assert view["coverage"]["truncated"] is True
