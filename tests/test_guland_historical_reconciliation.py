from __future__ import annotations

from unittest.mock import Mock
import json
import uuid

import pytest


CONFIRMED_CHANGED_URL = "https://guland.vn/post/changed-101"
REMOVED_URL = "https://guland.vn/post/removed-202"


def _fake_reconciliation_dependencies(monkeypatch):
    import services.guland_historical_reconciliation as service
    from analytics.lifecycle import SourceCheckResult

    candidates = [
        service.HistoricalGulandCandidate(
            raw_id=11,
            listing_id=101,
            url=CONFIRMED_CHANGED_URL,
            source_id="101",
            price_ty=2.5,
            first_seen_at="2026-07-01 08:00:00",
            source_status="active",
            consecutive_missing=0,
            raw_data={"url": CONFIRMED_CHANGED_URL, "price_ty": 2.5},
        ),
        service.HistoricalGulandCandidate(
            raw_id=22,
            listing_id=202,
            url=REMOVED_URL,
            source_id="202",
            price_ty=3.0,
            first_seen_at="2026-07-02 08:00:00",
            source_status="unknown",
            consecutive_missing=1,
            raw_data={"url": REMOVED_URL, "price_ty": 3.0},
        ),
    ]
    details = {
        CONFIRMED_CHANGED_URL: {
            "url": CONFIRMED_CHANGED_URL,
            "http_status": 200,
            "page_status": "live",
            "detail_price_raw": "2,7 tỷ",
            "description": "Giá mới đã xác nhận",
        },
        REMOVED_URL: {
            "url": REMOVED_URL,
            "http_status": 404,
            "page_status": "removed",
            "detail_price_raw": "",
        },
    }
    raw_refresh = Mock(return_value=11)
    lifecycle = Mock(
        side_effect=[
            SourceCheckResult(101, "active", "active", 0, False),
            SourceCheckResult(202, "removed", "inactive", 2, True),
        ]
    )
    reprocess = Mock(return_value={"listings": {"processed_ids": [101]}})
    backfill = Mock(return_value={"first_seen": 1, "price_updated": 1})

    monkeypatch.setattr(service, "load_guland_candidates", lambda limit: candidates[:limit])
    monkeypatch.setattr(service, "fetch_guland_details", lambda rows: details)
    monkeypatch.setattr(service, "refresh_raw_listing", raw_refresh)
    monkeypatch.setattr(service, "apply_source_check", lifecycle)
    monkeypatch.setattr(service, "run_targeted_reprocess", reprocess)
    monkeypatch.setattr(service, "backfill_guland_history_metadata", backfill)
    return {
        "raw_refresh": raw_refresh,
        "lifecycle": lifecycle,
        "reprocess": reprocess,
        "backfill": backfill,
    }


def test_reconcile_default_is_dry_run(monkeypatch):
    from services.guland_historical_reconciliation import (
        reconcile_guland_candidates,
    )

    spies = _fake_reconciliation_dependencies(monkeypatch)
    stats = reconcile_guland_candidates(limit=20, apply=False)

    assert stats["apply"] is False
    assert stats["scanned"] <= 20
    assert stats["price_changes"] == 1
    assert stats["inactive_confirmed"] == 1
    assert spies["raw_refresh"].call_count == 0
    assert spies["lifecycle"].call_count == 0
    assert spies["reprocess"].call_count == 0
    assert spies["backfill"].call_count == 0


def test_reconcile_apply_updates_only_confirmed_changes(monkeypatch):
    from services.guland_historical_reconciliation import (
        reconcile_guland_candidates,
    )

    spies = _fake_reconciliation_dependencies(monkeypatch)
    stats = reconcile_guland_candidates(limit=20, apply=True)

    assert stats["price_changes"] == 1
    assert stats["inactive_confirmed"] == 1
    assert stats["changed_listing_ids"] == [101]
    assert spies["raw_refresh"].call_args.args[1] == CONFIRMED_CHANGED_URL
    spies["reprocess"].assert_called_once_with([11])
    spies["backfill"].assert_called_once_with()


def test_history_metadata_backfill_uses_crawled_at_and_latest_distinct_change():
    from db.connection import get_conn
    from db.schema import init_schema
    from services.guland_historical_reconciliation import (
        backfill_guland_history_metadata,
    )

    init_schema()
    token = uuid.uuid4().hex
    url = f"https://guland-history-{token}.test/post/1"
    listing_id = None
    try:
        with get_conn() as conn:
            raw_id = conn.execute(
                """
                INSERT INTO raw_listings (source, source_id, url, raw_json, crawled_at)
                VALUES ('guland', ?, ?, ?, '2026-07-01 08:00:00')
                """,
                (token, url, json.dumps({"url": url})),
            ).lastrowid
            listing_id = conn.execute(
                """
                INSERT INTO listings (
                    raw_id, source, source_id, url, title, area_m2,
                    price_ty, price_per_m2, first_seen_at, crawled_at
                ) VALUES (
                    ?, 'guland', ?, ?, 'Historical backfill', 100,
                    2.4, 24, NULL, '2026-07-01 08:00:00'
                )
                """,
                (raw_id, token, url),
            ).lastrowid
            for price, recorded_at in (
                (2.5, "2026-07-01 08:00:00"),
                (2.5, "2026-07-05 09:00:00"),
                (2.7, "2026-07-10 10:00:00"),
                (2.4, "2026-07-20 11:00:00"),
            ):
                conn.execute(
                    """
                    INSERT INTO price_history (listing_id, price_ty, recorded_at)
                    VALUES (?, ?, ?)
                    """,
                    (listing_id, price, recorded_at),
                )

        stats = backfill_guland_history_metadata()

        with get_conn() as conn:
            row = conn.execute(
                """
                SELECT first_seen_at, price_updated_at
                FROM listings WHERE id=?
                """,
                (listing_id,),
            ).fetchone()
        assert row["first_seen_at"] == "2026-07-01 08:00:00"
        assert str(row["price_updated_at"]).startswith("2026-07-20 11:00:00")
        assert stats["first_seen"] >= 1
        assert stats["price_updated"] >= 1
    finally:
        if listing_id is not None:
            with get_conn() as conn:
                conn.execute(
                    "DELETE FROM price_history WHERE listing_id=?",
                    (listing_id,),
                )
                conn.execute("DELETE FROM listings WHERE id=?", (listing_id,))
                conn.execute(
                    "DELETE FROM raw_listings WHERE source='guland' AND url=?",
                    (url,),
                )


@pytest.mark.parametrize("limit", [-1, 0, 201, 1000])
def test_reconcile_rejects_unbounded_limits(limit):
    from services.guland_historical_reconciliation import (
        reconcile_guland_candidates,
    )

    with pytest.raises(ValueError):
        reconcile_guland_candidates(limit=limit, apply=False)


def test_cli_defaults_to_dry_run():
    from radar import _parse_args, build_parser

    args = _parse_args(
        build_parser(),
        ["guland-reconcile", "--limit", "20"],
    )
    assert args.cmd == "guland-reconcile"
    assert args.limit == 20
    assert args.apply is False
