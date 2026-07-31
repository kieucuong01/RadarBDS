import json
import uuid
from datetime import date, datetime

import pytest

from db import connection
from db.guland_publishers import (
    publisher_sort_rank_sql,
    publisher_visibility_sql,
    record_seen_guland_cards,
    recompute_publisher,
    record_listing_observation,
    set_publisher_override,
    sync_listing_publisher,
)
from db.schema import init_schema
from services.guland_publisher_activity import validated_raw_publisher_fields


@pytest.fixture()
def publisher_listing():
    token = uuid.uuid4().hex
    url = f"https://repository-{token}.test/guland"
    publisher_key = ""
    connection.close_all()
    init_schema()
    with connection.get_conn() as conn:
        listing_id = conn.execute(
            """
            INSERT INTO listings (source, source_id, url, title, is_active)
            VALUES ('guland', ?, ?, 'Publisher repository test', 1)
            """,
            (f"guland-{token}", url),
        ).lastrowid

    try:
        yield listing_id, token
    finally:
        with connection.get_conn() as conn:
            rows = conn.execute(
                "SELECT publisher_id FROM listing_publishers WHERE listing_id=?",
                (listing_id,),
            ).fetchall()
            publisher_ids = [row["publisher_id"] for row in rows if row["publisher_id"]]
            conn.execute("DELETE FROM listings WHERE id=?", (listing_id,))
            for publisher_id in publisher_ids:
                conn.execute(
                    "DELETE FROM source_publishers WHERE id=?",
                    (publisher_id,),
                )
            conn.execute(
                """
                DELETE FROM admin_audit_log
                WHERE entity_type='guland_publisher'
                  AND actor=?
                """,
                (f"admin:{token}",),
            )
        connection.close_all()


def _identified_raw(token: str) -> dict[str, object]:
    return validated_raw_publisher_fields(
        {
            "publisher_source_id": f"member-{token}",
            "publisher_name": "Test Publisher",
        },
        secret="repository-test-secret-" + ("x" * 40),
    )


def test_schema_creates_all_publisher_tables(publisher_listing):
    with connection.get_conn() as conn:
        tables = {
            row["table_name"]
            for row in conn.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema='public'
                  AND table_name IN (
                      'source_publishers',
                      'listing_publishers',
                      'publisher_listing_observations',
                      'publisher_activity_daily'
                  )
                """
            ).fetchall()
        }

    assert tables == {
        "source_publishers",
        "listing_publishers",
        "publisher_listing_observations",
        "publisher_activity_daily",
    }


def test_sync_is_idempotent_and_unknown_is_fail_open(publisher_listing):
    listing_id, token = publisher_listing
    raw = _identified_raw(token)

    with connection.get_conn() as conn:
        first_id = sync_listing_publisher(conn, listing_id, raw)
        second_id = sync_listing_publisher(conn, listing_id, raw)
        publisher_count = conn.execute(
            "SELECT COUNT(*) AS n FROM source_publishers WHERE id=?",
            (first_id,),
        ).fetchone()["n"]
        link_count = conn.execute(
            "SELECT COUNT(*) AS n FROM listing_publishers WHERE listing_id=?",
            (listing_id,),
        ).fetchone()["n"]

    assert first_id == second_id
    assert publisher_count == 1
    assert link_count == 1

    with connection.get_conn() as conn:
        unknown_id = sync_listing_publisher(
            conn,
            listing_id,
            {
                "publisher_identity_status": "unknown",
                "publisher_identity_type": "unknown",
                "publisher_identity_confidence": "low",
                "publisher_identity_reason": "no_reliable_identity",
            },
        )
        link = conn.execute(
            """
            SELECT publisher_id, identity_status
            FROM listing_publishers WHERE listing_id=?
            """,
            (listing_id,),
        ).fetchone()

    assert unknown_id is None
    assert link["publisher_id"] is None
    assert link["identity_status"] == "unknown"


def test_legacy_raw_without_publisher_fields_is_fail_open(publisher_listing):
    listing_id, _token = publisher_listing

    with connection.get_conn() as conn:
        publisher_id = sync_listing_publisher(conn, listing_id, {})
        link = conn.execute(
            """
            SELECT publisher_id, identity_status, evidence_type,
                   identity_confidence
            FROM listing_publishers
            WHERE listing_id=?
            """,
            (listing_id,),
        ).fetchone()

    assert publisher_id is None
    assert link["publisher_id"] is None
    assert link["identity_status"] == "unknown"
    assert link["evidence_type"] == "unknown"
    assert link["identity_confidence"] == "low"


def test_observations_are_idempotent_and_recompute_exact_threshold(
    publisher_listing,
):
    listing_id, token = publisher_listing
    with connection.get_conn() as conn:
        publisher_id = sync_listing_publisher(
            conn,
            listing_id,
            _identified_raw(token),
        )
        conn.execute(
            """
            UPDATE source_publishers
            SET last_seen_at='2020-01-01T00:00:00+00:00'
            WHERE id=?
            """,
            (publisher_id,),
        )
        for _ in range(2):
            record_listing_observation(
                conn,
                listing_id,
                date(2026, 7, 31),
                is_new=True,
                source_date_changed=True,
                near_duplicate_count=10,
                repeated_template=True,
            )
        daily = conn.execute(
            """
            SELECT new_listing_count, seen_listing_count, bump_count,
                   near_duplicate_count, repeated_template_count
            FROM publisher_activity_daily
            WHERE publisher_id=? AND activity_date=?
            """,
            (publisher_id, date(2026, 7, 31)),
        ).fetchone()
        classification = recompute_publisher(
            conn,
            publisher_id,
            date(2026, 7, 31),
        )
        last_seen_at = conn.execute(
            "SELECT last_seen_at FROM source_publishers WHERE id=?",
            (publisher_id,),
        ).fetchone()["last_seen_at"]

    assert dict(daily.items()) == {
        "new_listing_count": 1,
        "seen_listing_count": 1,
        "bump_count": 1,
        "near_duplicate_count": 10,
        "repeated_template_count": 1,
    }
    assert classification.activity_class == "automated_repost"
    assert last_seen_at.year > 2020


def test_override_is_audited_and_returns_effective_class(publisher_listing):
    listing_id, token = publisher_listing
    actor = f"admin:{token}"
    with connection.get_conn() as conn:
        publisher_id = sync_listing_publisher(
            conn,
            listing_id,
            _identified_raw(token),
        )
        conn.execute(
            """
            UPDATE source_publishers
            SET activity_class='automated_repost',
                activity_reason='test_threshold'
            WHERE id=?
            """,
            (publisher_id,),
        )
        updated = set_publisher_override(
            conn,
            publisher_id,
            "allow_manual",
            actor=actor,
        )
        audit = conn.execute(
            """
            SELECT before_json, after_json
            FROM admin_audit_log
            WHERE entity_type='guland_publisher'
              AND entity_id=?
              AND actor=?
            ORDER BY id DESC LIMIT 1
            """,
            (publisher_id, actor),
        ).fetchone()

    assert updated["effective_class"] == "low_manual"
    assert json.loads(audit["before_json"])["manual_override"] == ""
    assert json.loads(audit["after_json"])["manual_override"] == "allow_manual"

    with connection.get_conn() as conn:
        with pytest.raises(ValueError, match="invalid publisher override"):
            set_publisher_override(
                conn,
                publisher_id,
                "spam",
                actor=actor,
            )


def test_visibility_and_rank_sql_share_the_publisher_link_contract():
    visibility = publisher_visibility_sql("candidate", False)
    rank = publisher_sort_rank_sql("candidate")

    assert "candidate.source <> 'guland'" in visibility
    assert "lp.listing_id = candidate.id" in visibility
    assert "NOT EXISTS" in visibility
    assert publisher_visibility_sql("candidate", True) == "1=1"
    assert "allow_manual" in rank
    assert "automated_repost" in rank


def test_seen_card_bump_is_idempotent_and_does_not_change_listing_dates(
    publisher_listing,
):
    listing_id, token = publisher_listing
    raw_id = None
    try:
        raw_data = {
            "url": f"https://guland.vn/post/seen-{token}",
            "date_raw": "1 ngày trước",
            **_identified_raw(token),
        }
        with connection.get_conn() as conn:
            raw_id = conn.execute(
                """
                INSERT INTO raw_listings (source, source_id, url, raw_json)
                VALUES ('guland', ?, ?, ?)
                """,
                (
                    f"seen-{token}",
                    raw_data["url"],
                    json.dumps(raw_data),
                ),
            ).lastrowid
            conn.execute(
                """
                UPDATE listings
                SET raw_id=?, url=?, first_seen_at='2026-07-01T08:00:00+07:00',
                    posted_at='2026-07-01'
                WHERE id=?
                """,
                (raw_id, raw_data["url"], listing_id),
            )
            publisher_id = sync_listing_publisher(
                conn,
                listing_id,
                raw_data,
            )
            first = record_seen_guland_cards(
                conn,
                [{"url": raw_data["url"], "date_raw": "Hôm nay"}],
                datetime.fromisoformat("2026-07-31T10:00:00+07:00"),
            )
            second = record_seen_guland_cards(
                conn,
                [{"url": raw_data["url"], "date_raw": "Hôm nay"}],
                datetime.fromisoformat("2026-07-31T11:00:00+07:00"),
            )
            daily = conn.execute(
                """
                SELECT seen_listing_count, bump_count
                FROM publisher_activity_daily
                WHERE publisher_id=? AND activity_date='2026-07-31'
                """,
                (publisher_id,),
            ).fetchone()
            listing = conn.execute(
                """
                SELECT first_seen_at, posted_at
                FROM listings WHERE id=?
                """,
                (listing_id,),
            ).fetchone()
            revision = conn.execute(
                """
                SELECT change_kind
                FROM raw_listing_revisions
                WHERE raw_listing_id=?
                ORDER BY revision_no DESC LIMIT 1
                """,
                (raw_id,),
            ).fetchone()

        assert first["changed_raw_ids"] == [raw_id]
        assert second["changed_raw_ids"] == []
        assert daily["seen_listing_count"] == 1
        assert daily["bump_count"] == 1
        assert listing["first_seen_at"] == "2026-07-01T08:00:00+07:00"
        assert listing["posted_at"] == "2026-07-01"
        assert revision["change_kind"] == "guland_source_bump"
    finally:
        if raw_id:
            with connection.get_conn() as conn:
                conn.execute(
                    "UPDATE listings SET raw_id=NULL WHERE id=?",
                    (listing_id,),
                )
                conn.execute("DELETE FROM raw_listings WHERE id=?", (raw_id,))


def test_first_card_date_capture_is_baseline_not_a_bump(publisher_listing):
    listing_id, token = publisher_listing
    raw_id = None
    try:
        raw_data = {
            "url": f"https://guland.vn/post/baseline-{token}",
            **_identified_raw(token),
        }
        with connection.get_conn() as conn:
            raw_id = conn.execute(
                """
                INSERT INTO raw_listings (source, source_id, url, raw_json)
                VALUES ('guland', ?, ?, ?)
                """,
                (
                    f"baseline-{token}",
                    raw_data["url"],
                    json.dumps(raw_data),
                ),
            ).lastrowid
            conn.execute(
                "UPDATE listings SET raw_id=?, url=? WHERE id=?",
                (raw_id, raw_data["url"], listing_id),
            )
            publisher_id = sync_listing_publisher(
                conn,
                listing_id,
                raw_data,
            )
            baseline = record_seen_guland_cards(
                conn,
                [{"url": raw_data["url"], "date_raw": "1 ngày trước"}],
                datetime.fromisoformat("2026-07-31T09:00:00+07:00"),
            )
            natural_progression = record_seen_guland_cards(
                conn,
                [{"url": raw_data["url"], "date_raw": "2 ngày trước"}],
                datetime.fromisoformat("2026-08-01T09:00:00+07:00"),
            )
            bumped = record_seen_guland_cards(
                conn,
                [{"url": raw_data["url"], "date_raw": "Hôm nay"}],
                datetime.fromisoformat("2026-08-01T10:00:00+07:00"),
            )
            daily = conn.execute(
                """
                SELECT bump_count
                FROM publisher_activity_daily
                WHERE publisher_id=? AND activity_date='2026-08-01'
                """,
                (publisher_id,),
            ).fetchone()
            revisions = conn.execute(
                """
                SELECT change_kind
                FROM raw_listing_revisions
                WHERE raw_listing_id=?
                ORDER BY revision_no
                """,
                (raw_id,),
            ).fetchall()

        assert baseline["changed_raw_ids"] == [raw_id]
        assert baseline["bumps"] == 0
        assert natural_progression["changed_raw_ids"] == []
        assert natural_progression["bumps"] == 0
        assert bumped["changed_raw_ids"] == [raw_id]
        assert bumped["bumps"] == 1
        assert daily["bump_count"] == 1
        assert [row["change_kind"] for row in revisions][-2:] == [
            "guland_card_date_baseline",
            "guland_source_bump",
        ]
    finally:
        if raw_id:
            with connection.get_conn() as conn:
                conn.execute(
                    "UPDATE listings SET raw_id=NULL WHERE id=?",
                    (listing_id,),
                )
                conn.execute("DELETE FROM raw_listings WHERE id=?", (raw_id,))
