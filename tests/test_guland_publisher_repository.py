import json
import uuid
from datetime import date, datetime, timedelta, timezone

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


def test_override_refreshes_linked_read_model_rows_atomically(
    publisher_listing,
    monkeypatch,
):
    from services import signal_read_model

    listing_id, token = publisher_listing
    calls = []
    with connection.get_conn() as conn:
        publisher_id = sync_listing_publisher(
            conn,
            listing_id,
            _identified_raw(token),
        )
        monkeypatch.setattr(
            signal_read_model,
            "refresh_signal_card_read_model",
            lambda refresh_conn, **kwargs: calls.append(
                (refresh_conn, kwargs)
            )
            or signal_read_model.SignalReadModelRefresh(
                "incremental",
                1,
                {"signals": 9},
                1.5,
            ),
        )

        updated = set_publisher_override(
            conn,
            publisher_id,
            "allow_manual",
            actor=f"admin:{token}",
        )

    assert calls == [
        (
            calls[0][0],
            {"listing_ids": (listing_id,), "market_changed": False},
        )
    ]
    assert updated["public_read_model"]["versions"] == {"signals": 9}


def test_joined_publisher_visibility_is_fail_open_for_unknown_identity():
    from db.guland_publishers import publisher_visibility_from_join_sql

    sql = publisher_visibility_from_join_sql("l", "feed_sp")
    assert "COALESCE" in sql
    assert "<> 'hide_high_activity'" in sql
    assert 'activity_class' not in sql


def test_seen_card_bump_is_idempotent_and_does_not_change_listing_dates(
    publisher_listing,
):
    listing_id, token = publisher_listing
    raw_id = None
    try:
        raw_data = {
            "url": f"https://guland.vn/post/seen-{token}",
            "date_raw": "1 ngày trước",
            "price_ty": 2.5,
            **_identified_raw(token),
        }
        with connection.get_conn() as conn:
            raw_id = conn.execute(
                """
                INSERT INTO raw_listings (
                    source, source_id, url, raw_json, crawled_at
                )
                VALUES (
                    'guland', ?, ?, ?, '2026-07-31T10:00:00+07:00'
                )
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
                [{"url": raw_data["url"], "date_raw": "Hôm nay", "price_ty": 2.5}],
                datetime.fromisoformat("2026-07-31T10:00:00+07:00"),
            )
            second = record_seen_guland_cards(
                conn,
                [{"url": raw_data["url"], "date_raw": "Hôm nay", "price_ty": 2.5}],
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
            "price_ty": 2.5,
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
                [{"url": raw_data["url"], "date_raw": "1 ngày trước", "price_ty": 2.5}],
                datetime.fromisoformat("2026-07-31T09:00:00+07:00"),
            )
            natural_progression = record_seen_guland_cards(
                conn,
                [{"url": raw_data["url"], "date_raw": "2 ngày trước", "price_ty": 2.5}],
                datetime.fromisoformat("2026-08-01T09:00:00+07:00"),
            )
            bumped = record_seen_guland_cards(
                conn,
                [{"url": raw_data["url"], "date_raw": "Hôm nay", "price_ty": 2.5}],
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


@pytest.mark.parametrize("source,klass,metrics,override,expected", [
    ("facebook", "unknown", {}, "", True),
    ("guland", "unknown", {}, "", True),
    ("guland", "low_manual", {}, "", True),
    ("guland", "low_manual", {"reported_other_listings": 6}, "", True),
    ("guland", "low_manual", {"reported_other_listings": 24}, "", True),
    ("guland", "low_manual", {"reported_other_listings": 1065, "observation_span_days": 0, "observed_days_30d": 1}, "", True),
    ("guland", "low_manual", {"observation_span_days": 14, "observed_days_30d": 3}, "", True),
    ("guland", "high_activity", {"observation_span_days": 30, "observed_days_30d": 20}, "", True),
    ("guland", "automated_repost", {}, "", True),
    ("guland", "unknown", {}, "allow_manual", True),
    ("guland", "low_manual", {"observation_span_days": 14, "observed_days_30d": 3}, "hide_high_activity", False),
])
def test_signal_trust_policy_and_projection_agree(publisher_listing, source, klass, metrics, override, expected):
    from db.guland_publishers import publisher_signal_eligibility_sql, publisher_signal_eligibility_from_join_sql
    from services.signal_read_model import refresh_signal_card_read_model
    listing_id, token = publisher_listing
    with connection.get_conn() as conn:
        publisher_id = sync_listing_publisher(conn, listing_id, _identified_raw(token))
        conn.execute("UPDATE listings SET source=?, price_updated_at=NOW() WHERE id=?", (source, listing_id))
        conn.execute("UPDATE source_publishers SET activity_class=?, metrics_json=?, manual_override=? WHERE id=?", (klass, json.dumps(metrics), override, publisher_id))
        row = conn.execute(f"""
            SELECT ({publisher_signal_eligibility_sql('l')}) AS legacy,
                   ({publisher_signal_eligibility_from_join_sql('l', 'sp')}) AS joined,
                   ({publisher_visibility_sql('l')}) AS visible
            FROM listings l
            LEFT JOIN listing_publishers lp ON lp.listing_id=l.id
            LEFT JOIN source_publishers sp ON sp.id=lp.publisher_id
            WHERE l.id=?
        """, (listing_id,)).fetchone()
        refresh_signal_card_read_model(conn, listing_ids=(listing_id,), market_changed=False)
        projected = conn.execute("SELECT publisher_signal_eligible FROM signal_card_read_model WHERE listing_id=?", (listing_id,)).fetchone()
    assert row['legacy'] is expected
    assert row['joined'] is expected
    assert projected['publisher_signal_eligible'] is expected
    if klass == 'unknown' and not override:
        assert row['visible'] is True  # retained for inspection, not promoted


def test_small_portfolio_survives_recompute_and_old_replay(publisher_listing):
    listing_id, token = publisher_listing
    now = datetime.now(timezone.utc)
    with connection.get_conn() as conn:
        raw = {**_identified_raw(token), 'publisher_other_listing_count': 6, 'publisher_identity_checked_at': now.isoformat()}
        publisher_id = sync_listing_publisher(conn, listing_id, raw, observed_at=now)
        assert recompute_publisher(conn, publisher_id, now.date()).activity_class == 'low_manual'
        old = {**raw, 'publisher_other_listing_count': 468, 'publisher_identity_checked_at': (now-timedelta(days=5)).isoformat()}
        sync_listing_publisher(conn, listing_id, old, observed_at=now)
        assert recompute_publisher(conn, publisher_id, now.date()).activity_class == 'low_manual'
        row = conn.execute('SELECT metrics_json FROM source_publishers WHERE id=?', (publisher_id,)).fetchone()
        assert row['metrics_json']['reported_other_listings'] == 6


def test_repeated_unchanged_bumps_block_only_that_listing_until_real_price_edit(publisher_listing):
    from db.guland_publishers import publisher_signal_eligibility_sql, publisher_signal_eligibility_from_join_sql
    listing_id, token = publisher_listing
    now = datetime.now(timezone.utc)
    with connection.get_conn() as conn:
        raw = {**_identified_raw(token), 'publisher_other_listing_count': 6}
        publisher_id = sync_listing_publisher(conn, listing_id, raw, observed_at=now)
        for delta in (3, 2, 1):
            observed = now-timedelta(days=delta)
            record_listing_observation(conn, listing_id, observed.date(), is_new=False, source_date_changed=True, observed_at=observed)
        assert recompute_publisher(conn, publisher_id, now.date()).activity_class == 'low_manual'
        sql = f"SELECT ({publisher_signal_eligibility_sql('l')}) a, ({publisher_signal_eligibility_from_join_sql('l','sp')}) b FROM listings l JOIN listing_publishers lp ON lp.listing_id=l.id JOIN source_publishers sp ON sp.id=lp.publisher_id WHERE l.id=?"
        row = conn.execute(sql, (listing_id,)).fetchone()
        assert row['a'] is False and row['b'] is False
        conn.execute('UPDATE listings SET price_updated_at=? WHERE id=?', (now, listing_id))
        row = conn.execute(sql, (listing_id,)).fetchone()
        assert row['a'] is True and row['b'] is True


def test_later_sighting_cannot_move_same_day_old_bump_after_price_edit(publisher_listing):
    from db.guland_publishers import publisher_signal_eligibility_sql
    listing_id, token = publisher_listing
    now = datetime.now(timezone.utc)
    edited = (now-timedelta(days=3)).replace(hour=12, minute=0, second=0, microsecond=0)
    with connection.get_conn() as conn:
        publisher_id = sync_listing_publisher(conn, listing_id, {**_identified_raw(token), 'publisher_other_listing_count': 6})
        for observed in (edited-timedelta(hours=1), edited+timedelta(days=1), edited+timedelta(days=2)):
            record_listing_observation(conn, listing_id, observed.date(), is_new=False, source_date_changed=True, observed_at=observed)
        record_listing_observation(conn, listing_id, edited.date(), is_new=False, source_date_changed=False, observed_at=edited+timedelta(hours=2))
        conn.execute('UPDATE listings SET price_updated_at=? WHERE id=?', (edited, listing_id))
        recompute_publisher(conn, publisher_id, now.date())
        assert conn.execute(f'SELECT ({publisher_signal_eligibility_sql("l")}) eligible FROM listings l WHERE id=?', (listing_id,)).fetchone()['eligible'] is True


def test_unidentified_listing_keeps_its_own_repost_evidence_without_null_projection(publisher_listing):
    from db.guland_publishers import publisher_signal_eligibility_sql, publisher_signal_eligibility_from_join_sql
    from services.signal_read_model import refresh_signal_card_read_model
    listing_id, token = publisher_listing
    now = datetime.now(timezone.utc)
    with connection.get_conn() as conn:
        sync_listing_publisher(conn, listing_id, _identified_raw(token))
        for delta in (3,2,1):
            seen=now-timedelta(days=delta)
            record_listing_observation(conn,listing_id,seen.date(),is_new=False,source_date_changed=True,observed_at=seen)
        sync_listing_publisher(conn,listing_id,{'publisher_identity_status':'unknown','publisher_identity_type':'unknown','publisher_identity_confidence':'low'})
        row=conn.execute(f"SELECT ({publisher_signal_eligibility_sql('l')}) legacy, ({publisher_signal_eligibility_from_join_sql('l','sp')}) joined FROM listings l LEFT JOIN listing_publishers lp ON lp.listing_id=l.id LEFT JOIN source_publishers sp ON sp.id=lp.publisher_id WHERE l.id=?",(listing_id,)).fetchone()
        assert row['legacy'] is False and row['joined'] is False
        refresh_signal_card_read_model(conn,listing_ids=(listing_id,))


def test_backfilled_post_dates_do_not_manufacture_observation_history(publisher_listing):
    listing_id, token = publisher_listing
    with connection.get_conn() as conn:
        publisher_id = sync_listing_publisher(conn, listing_id, _identified_raw(token))
        for day in (date(2026, 7, 1), date(2026, 7, 15), date(2026, 7, 31)):
            record_listing_observation(conn, listing_id, day, is_new=False, source_date_changed=False)
        classification = recompute_publisher(conn, publisher_id, date.today())
        metrics = conn.execute("SELECT metrics_json FROM source_publishers WHERE id=?", (publisher_id,)).fetchone()['metrics_json']
    assert classification.activity_class == 'unknown'
    assert metrics['observed_days_30d'] == 1
    assert metrics['observation_span_days'] == 0


def test_three_actual_observation_days_mature_publisher(publisher_listing):
    listing_id, token = publisher_listing
    now = datetime.now(timezone.utc)
    with connection.get_conn() as conn:
        publisher_id = sync_listing_publisher(conn, listing_id, _identified_raw(token))
        for delta in (14, 7, 0):
            observed = now - timedelta(days=delta)
            record_listing_observation(conn, listing_id, observed.date(), is_new=False,
                                       source_date_changed=False, observed_at=observed)
        result = recompute_publisher(conn, publisher_id, now.date())
    assert result.activity_class == 'low_manual'


def test_established_publisher_keeps_maturity_after_a_quiet_month(publisher_listing):
    listing_id, token = publisher_listing
    now = datetime.now(timezone.utc)
    with connection.get_conn() as conn:
        publisher_id = sync_listing_publisher(conn, listing_id, _identified_raw(token))
        for delta in (60, 2, 1, 0):
            observed = now - timedelta(days=delta)
            record_listing_observation(conn, listing_id, observed.date(), is_new=False,
                                       source_date_changed=False, observed_at=observed)
        result = recompute_publisher(conn, publisher_id, now.date())
    assert result.activity_class == 'low_manual'


def test_observation_preserves_source_seen_time_during_replay(publisher_listing):
    listing_id, token = publisher_listing
    observed = datetime.fromisoformat('2026-07-31T10:00:00+07:00')
    with connection.get_conn() as conn:
        publisher_id = sync_listing_publisher(conn, listing_id, _identified_raw(token), observed_at=observed)
        record_listing_observation(conn, listing_id, observed.date(), is_new=True,
                                   source_date_changed=False, observed_at=observed)
        last_seen = conn.execute('SELECT last_seen_at FROM source_publishers WHERE id=?', (publisher_id,)).fetchone()['last_seen_at']
    assert last_seen == observed


@pytest.mark.parametrize('source,trusted', [('facebook', False), ('guland', False), ('guland', True)])
def test_promotion_matches_feed_counts_maps_and_vip(publisher_listing, monkeypatch, source, trusted):
    from services import market_data, signal_read_model
    from services.listing_map import MapFilters, _filtered_sql, _base_cte
    from cli.notify import _fetch_new_signals
    listing_id, token = publisher_listing
    ward = f'TrustWard{token}'
    with connection.get_conn() as conn:
        if source == 'guland':
            publisher_id = sync_listing_publisher(conn, listing_id, _identified_raw(token))
            metrics = {'observation_span_days': 14, 'observed_days_30d': 3} if trusted else {}
            conn.execute("UPDATE source_publishers SET activity_class=?, metrics_json=? WHERE id=?",
                         ('low_manual' if trusted else 'unknown', json.dumps(metrics), publisher_id))
            if not trusted:
                now=datetime.now(timezone.utc)
                for delta in (3,2,1):
                    seen=now-timedelta(days=delta)
                    record_listing_observation(conn,listing_id,seen.date(),is_new=False,source_date_changed=True,observed_at=seen)
        conn.execute("""UPDATE listings SET source=?, ward=?, price_ty=2, price_per_m2=20,
            area_m2=100, probably_sold=0, possibly_duplicate=0, source_status='active',
            first_seen_at='2099-01-15', crawled_at='2099-01-15' WHERE id=?""", (source, ward, listing_id))
        conn.execute("INSERT INTO valuation_results(listing_id, is_signal, actual_ppm2, fair_ppm2, mos_pct) VALUES (?, 1, 20, 30, 33.33)", (listing_id,))
        signal_read_model.refresh_signal_card_read_model(conn, listing_ids=(listing_id,), market_changed=False)
    expected_ids = [listing_id] if source == 'facebook' or trusted else []
    kwargs = dict(sources=[source], wards=[ward], date_range='all', tier='guest')
    legacy = market_data._load_signals_legacy(None, **kwargs)
    projected = signal_read_model.load_signals_from_read_model(None, **kwargs)
    assert [row['id'] for row in legacy['signals']] == expected_ids
    assert [row['id'] for row in projected['signals']] == expected_ids
    with connection.get_conn() as conn:
        for enabled in ('0', '1'):
            monkeypatch.setenv('RADAR_SIGNAL_READ_MODEL_ENABLED', enabled)
            assert market_data.count_filtered_signals(conn, **kwargs) == len(expected_ids)
            sql, params = _filtered_sql('signals', MapFilters(sources=(source,), wards=(ward,), date_range='all'), use_read_model=enabled == '1')
            rows = conn.execute(_base_cte(sql, use_read_model=enabled == '1') + ' SELECT id FROM filtered', params).fetchall()
            assert [row['id'] for row in rows] == expected_ids
        vip_ids = [row['id'] for row in _fetch_new_signals(conn, '2099-01-01') if row['ward'] == ward]
    assert vip_ids == expected_ids


def test_trust_impact_report_is_private_and_read_only(publisher_listing):
    from scripts.audit_guland_publisher_trust import build_report
    listing_id, _token = publisher_listing
    with connection.get_conn() as conn:
        conn.execute('SET TRANSACTION READ ONLY')
        report = build_report(conn, sample_limit=2)
    assert report['policy']['repeated_listing_bump_dates_required'] == 3
    assert 'no publisher count/history gate' in report['policy']['basis']
    assert 'url' not in json.dumps(report)
    assert 'publisher_key' not in json.dumps(report)


def test_failed_reclassification_publication_rolls_back_policy(publisher_listing, monkeypatch):
    from scripts import audit_guland_publisher_trust as audit
    listing_id, token = publisher_listing
    with connection.get_conn() as conn:
        publisher_id = sync_listing_publisher(conn, listing_id, _identified_raw(token))
        conn.execute("UPDATE source_publishers SET activity_class='low_manual' WHERE id=?", (publisher_id,))
    def fail_refresh(*args, **kwargs):
        raise RuntimeError('projection failed')
    monkeypatch.setattr(audit, 'refresh_signal_card_read_model', fail_refresh)
    with pytest.raises(RuntimeError, match='projection failed'):
        with connection.get_conn() as conn:
            audit.apply_reclassification(conn)
    with connection.get_conn() as conn:
        stored = conn.execute('SELECT activity_class FROM source_publishers WHERE id=?', (publisher_id,)).fetchone()
    assert stored['activity_class'] == 'low_manual'
