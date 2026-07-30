from datetime import datetime
import uuid

from analytics.lifecycle import (
    mark_source_seen,
    record_source_check,
    sweep_delisted,
)
from db.connection import get_conn
from db.schema import init_schema


NOW = datetime.fromisoformat("2026-07-30T12:00:00+07:00")
FIRST_SEEN = "2026-07-01T08:00:00+07:00"


def _seed_guland(conn, token: str) -> dict:
    url = f"https://guland.vn/post/source-lifecycle-{token}"
    raw_id = conn.execute(
        """
        INSERT INTO raw_listings (source, source_id, url, raw_json)
        VALUES ('guland', ?, ?, '{}')
        """,
        (token, url),
    ).lastrowid
    listing_id = conn.execute(
        """
        INSERT INTO listings (
            raw_id, source, source_id, url, title, price_ty, area_m2,
            first_seen_at, last_seen_at, is_active, consecutive_missing
        )
        VALUES (?, 'guland', ?, ?, 'Lifecycle test', 2.5, 100,
                ?, ?, 1, 0)
        """,
        (raw_id, token, url, FIRST_SEEN, FIRST_SEEN),
    ).lastrowid
    return {
        "id": listing_id,
        "raw_id": raw_id,
        "url": url,
        "first_seen_at": FIRST_SEEN,
    }


def _load_listing(conn, listing_id: int) -> dict:
    row = conn.execute(
        """
        SELECT first_seen_at, last_seen_at, source_status,
               source_status_reason, consecutive_missing, is_active,
               delisted_at, last_source_check_at
        FROM listings
        WHERE id=?
        """,
        (listing_id,),
    ).fetchone()
    return dict(row)


def _with_seeded_guland(test_fn):
    init_schema()
    token = uuid.uuid4().hex
    with get_conn() as conn:
        seeded = _seed_guland(conn, token)
    try:
        test_fn(seeded)
    finally:
        with get_conn() as conn:
            conn.execute("DELETE FROM listings WHERE id=?", (seeded["id"],))
            conn.execute("DELETE FROM raw_listings WHERE id=?", (seeded["raw_id"],))


def test_mark_source_seen_preserves_first_seen():
    def check(seeded):
        with get_conn() as conn:
            mark_source_seen(
                conn,
                "guland",
                [seeded["url"]],
                seen_at=NOW,
            )
            row = _load_listing(conn, seeded["id"])

        assert row["first_seen_at"] == seeded["first_seen_at"]
        assert row["last_seen_at"].startswith("2026-07-30")
        assert row["source_status"] == "active"
        assert row["source_status_reason"] == "seen_in_results"

    _with_seeded_guland(check)


def test_two_explicit_removals_are_required():
    def check(seeded):
        with get_conn() as conn:
            first = record_source_check(
                conn,
                seeded["id"],
                "removed",
                "http_not_found",
                checked_at=NOW,
            )
        with get_conn() as conn:
            second = record_source_check(
                conn,
                seeded["id"],
                "removed",
                "explicit_removed",
                checked_at=NOW,
            )

        assert first.source_status == "unknown"
        assert first.consecutive_missing == 1
        assert second.source_status == "inactive"
        assert second.consecutive_missing == 2

    _with_seeded_guland(check)


def test_unreachable_does_not_increment_missing():
    def check(seeded):
        with get_conn() as conn:
            conn.execute(
                "UPDATE listings SET consecutive_missing=1 WHERE id=?",
                (seeded["id"],),
            )
            result = record_source_check(
                conn,
                seeded["id"],
                "unreachable",
                "timeout",
                checked_at=NOW,
            )
            row = _load_listing(conn, seeded["id"])

        assert result.source_status == "unreachable"
        assert result.consecutive_missing == 0
        assert row["is_active"] == 1

    _with_seeded_guland(check)


def test_elapsed_time_alone_never_marks_source_inactive():
    def check(seeded):
        with get_conn() as conn:
            conn.execute(
                """
                UPDATE listings
                SET last_seen_at='2025-01-01T00:00:00+07:00',
                    source_status='active'
                WHERE id=?
                """,
                (seeded["id"],),
            )
            assert sweep_delisted(conn, stale_hours=1) == []
            row = _load_listing(conn, seeded["id"])

        assert row["source_status"] == "active"
        assert row["is_active"] == 1
        assert row["delisted_at"] is None

    _with_seeded_guland(check)
