from contextlib import contextmanager
import uuid

import pytest

from db import connection
from db.public_dataset_versions import get_dataset_versions
from db.schema import init_schema


@pytest.fixture(autouse=True)
def initialized_schema():
    connection.close_all()
    init_schema()
    yield
    connection.close_all()


def test_signal_read_model_schema_and_indexes_exist():
    with connection.get_conn() as conn:
        table = conn.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema='public'
              AND table_name='signal_card_read_model'
            """
        ).fetchone()
        indexes = {
            row["indexname"]
            for row in conn.execute(
                """
                SELECT indexname
                FROM pg_indexes
                WHERE schemaname='public'
                  AND tablename='signal_card_read_model'
                """
            ).fetchall()
        }
        columns = {
            row["column_name"]
            for row in conn.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema='public'
                  AND table_name='signal_card_read_model'
                """
            ).fetchall()
        }
        versions = get_dataset_versions(
            conn, ("signals", "listings", "market")
        )

    assert table["table_name"] == "signal_card_read_model"
    assert {
        "idx_signal_card_public_newest",
        "idx_signal_card_public_filter",
        "idx_signal_card_public_mos",
        "idx_signal_card_all_public_newest",
        "idx_signal_card_all_public_filter",
        "idx_signal_card_all_public_drop",
    } <= indexes
    assert {"listing_price_per_m2", "listing_is_signal"} <= columns
    assert set(versions) == {"signals", "listings", "market"}


def test_signal_card_select_sql_emits_boolean_storage_values():
    from services.signal_read_model import _select_sql

    sql, params = _select_sql(None)

    assert "THEN TRUE ELSE FALSE" in sql
    assert "COALESCE(l.has_so, 0)::boolean AS has_so" in sql
    assert params == ()


def test_refresh_keeps_incomplete_public_listing_but_not_as_signal():
    from services.signal_read_model import refresh_signal_card_read_model

    token = uuid.uuid4().hex
    with connection.get_conn() as conn:
        cursor = conn.execute(
            """
            INSERT INTO listings(
                source, source_id, url, title, description,
                source_status, ward, price_ty, price_per_m2, area_m2
            )
            VALUES (?, ?, ?, ?, '', 'active', NULL, 2.5, 12.5, NULL)
            RETURNING id
            """,
            (
                "facebook",
                f"read-model-incomplete-{token}",
                f"https://example.invalid/read-model-incomplete-{token}",
                "Incomplete public row",
            ),
        )
        listing_id = int(cursor.lastrowid)
        result = refresh_signal_card_read_model(
            conn, listing_ids=(listing_id,)
        )
        projected = conn.execute(
            """
            SELECT listing_id, listing_price_per_m2,
                   listing_is_signal, is_actionable
            FROM signal_card_read_model
            WHERE listing_id=?
            """,
            (listing_id,),
        ).fetchone()
        conn.execute("DELETE FROM listings WHERE id=?", (listing_id,))

    assert set(result.versions) >= {"signals", "listings"}
    assert projected["listing_id"] == listing_id
    assert projected["listing_price_per_m2"] == 12.5
    assert projected["listing_is_signal"] is False
    assert projected["is_actionable"] is False


def test_full_refresh_bumps_version_after_final_insert(monkeypatch):
    from services import signal_read_model

    events = []

    class _Cursor:
        rowcount = 0

    class _Connection:
        def execute(self, sql, params=None):
            events.append(("sql", sql, params))
            return _Cursor()

    monkeypatch.setattr(
        signal_read_model,
        "_select_sql",
        lambda _ids: ("SELECT 1 AS listing_id", ()),
    )
    monkeypatch.setattr(
        signal_read_model,
        "_insert_staged_rows",
        lambda _conn: events.append(("insert",)) or 3,
    )
    monkeypatch.setattr(
        signal_read_model,
        "bump_dataset_versions",
        lambda _conn, names: events.append(("bump", names))
        or {"signals": 8, "listings": 5},
    )

    result = signal_read_model.refresh_signal_card_read_model(
        _Connection(),
        listing_ids=None,
    )

    insert_position = events.index(("insert",))
    bump_position = events.index(("bump", ("signals", "listings")))
    assert insert_position < bump_position
    assert result.mode == "full"
    assert result.affected_rows == 3
    assert result.versions == {"signals": 8, "listings": 5}


def test_failed_full_refresh_keeps_previous_rows_and_version(monkeypatch):
    from services import signal_read_model

    with connection.get_conn() as conn:
        before_rows = [
            row["listing_id"]
            for row in conn.execute(
                "SELECT listing_id FROM signal_card_read_model ORDER BY listing_id"
            ).fetchall()
        ]
        before_version = get_dataset_versions(conn, ("signals",))["signals"]

    monkeypatch.setattr(
        signal_read_model,
        "_insert_staged_rows",
        lambda _conn: (_ for _ in ()).throw(RuntimeError("refresh failed")),
    )
    with pytest.raises(RuntimeError, match="refresh failed"):
        with connection.get_conn() as conn:
            signal_read_model.refresh_signal_card_read_model(
                conn,
                listing_ids=None,
            )

    with connection.get_conn() as conn:
        after_rows = [
            row["listing_id"]
            for row in conn.execute(
                "SELECT listing_id FROM signal_card_read_model ORDER BY listing_id"
            ).fetchall()
        ]
        after_version = get_dataset_versions(conn, ("signals",))["signals"]

    assert after_rows == before_rows
    assert after_version == before_version


def test_empty_refresh_is_noop_without_version_bump():
    from services.signal_read_model import refresh_signal_card_read_model

    with connection.get_conn() as conn:
        before = get_dataset_versions(conn, ("signals", "listings"))
        result = refresh_signal_card_read_model(conn, listing_ids=())
        after = get_dataset_versions(conn, ("signals", "listings"))

    assert result.mode == "noop"
    assert result.affected_rows == 0
    assert after == before
    assert result.versions == before


def test_more_than_five_hundred_ids_uses_full_refresh(monkeypatch):
    from services import signal_read_model

    selected = []

    class _Cursor:
        rowcount = 0

    class _Connection:
        def execute(self, _sql, _params=None):
            return _Cursor()

    monkeypatch.setattr(
        signal_read_model,
        "_select_sql",
        lambda ids: selected.append(ids) or ("SELECT 1 AS listing_id", ()),
    )
    monkeypatch.setattr(signal_read_model, "_insert_staged_rows", lambda _conn: 0)
    monkeypatch.setattr(
        signal_read_model,
        "bump_dataset_versions",
        lambda _conn, _names: {"signals": 1, "listings": 1},
    )

    result = signal_read_model.refresh_signal_card_read_model(
        _Connection(),
        listing_ids=tuple(range(1, 502)),
    )

    assert selected == [None]
    assert result.mode == "full"


def test_analyze_public_read_tables_uses_fixed_allowlist():
    from services.signal_read_model import (
        PUBLIC_READ_TABLES,
        analyze_public_read_tables,
    )

    statements = []

    class _Connection:
        def execute(self, sql, params=None):
            statements.append((sql, params))

    analyze_public_read_tables(_Connection())

    assert statements == [("ANALYZE " + ", ".join(PUBLIC_READ_TABLES), None)]
    assert "signal_card_read_model" in PUBLIC_READ_TABLES


def test_count_signals_from_read_model_reuses_public_feed_filters():
    from services import signal_read_model

    class _Cursor:
        def fetchone(self):
            return {"signals": 7}

    class _Connection:
        def __init__(self):
            self.queries = []

        def execute(self, sql, params=None):
            self.queries.append((sql, params))
            return _Cursor()

    conn = _Connection()
    result = signal_read_model.count_signals_from_read_model(
        conn,
        sources=["facebook"],
        wards=["Tan An"],
        mos_min=10,
        date_range="3m",
        tier="guest",
    )

    assert result == 7
    assert len(conn.queries) == 1
    query, params = conn.queries[0]
    assert "SELECT COUNT(*) AS signals" in query
    assert "FROM signal_card_read_model rm" in query
    assert "latest_valuation" not in query
    assert "facebook" in params
    assert "Tan An" in params
    assert "-3 months" in params
    assert 10.0 in params


def test_read_model_query_is_bounded_and_sets_local_timeout(monkeypatch):
    from services import signal_read_model

    class _Cursor:
        def fetchall(self):
            return []

    class _Connection:
        def __init__(self):
            self.queries = []
            self.closed = False

        def execute(self, sql, params=None):
            self.queries.append((sql, params))
            return _Cursor()

        def close(self):
            self.closed = True

    conn = _Connection()
    monkeypatch.setenv("RADAR_SIGNAL_QUERY_TIMEOUT_MS", "2400")
    monkeypatch.setattr(
        signal_read_model,
        "_open_read_conn",
        lambda _db_path=None: conn,
    )

    payload = signal_read_model.load_signals_from_read_model(
        None,
        sources=["facebook"],
        wards=["Tan An"],
        include_total=False,
    )

    assert conn.queries[0] == (
        "SELECT set_config('statement_timeout', ?, true)",
        ("2400ms",),
    )
    query, params = conn.queries[1]
    assert "FROM signal_card_read_model rm" in query
    assert "COUNT(*) OVER()" not in query
    assert params[-2:] == [31, 0]
    assert payload == {
        "signals": [],
        "page": 1,
        "limit": 30,
        "has_more": False,
        "sort": "newest",
        "tier": "guest",
    }
    assert conn.closed is True


def test_read_model_newest_sort_preserves_legacy_guland_text_order(monkeypatch):
    from services import signal_read_model

    class _Cursor:
        def fetchall(self):
            return []

    class _Connection:
        def __init__(self):
            self.queries = []

        def execute(self, sql, params=None):
            self.queries.append((sql, params))
            return _Cursor()

        def close(self):
            return None

    conn = _Connection()
    monkeypatch.setattr(
        signal_read_model,
        "_open_read_conn",
        lambda _db_path=None: conn,
    )

    signal_read_model.load_signals_from_read_model(
        None,
        sources=["guland"],
        include_total=False,
    )

    query = " ".join(conn.queries[1][0].split())
    expected_order = (
        "CASE WHEN rm.source = 'guland' THEN "
        "COALESCE(CAST(rm.price_updated_at AS TEXT), "
        "rm.first_seen_at, rm.crawled_at) ELSE "
        "COALESCE(rm.posted_at, rm.crawled_at) END) DESC, "
        "rm.listing_id DESC"
    )
    assert expected_order in query
    assert "rm.activity_at DESC" not in query


PARITY_CASES = (
    {},
    {"sources": ["facebook"]},
    {"sources": ["guland"]},
    {"wards": ["Tan An"]},
    {"prop_types": ["dat_nen"]},
    {"mos_min": 20},
    {"only_drops": True},
    {"sort": "mos_desc"},
    {"sort": "score_desc"},
    {"page": 2, "limit": 12, "include_total": False},
)


@pytest.fixture(scope="module")
def populated_signal_read_model():
    from services.signal_read_model import refresh_signal_card_read_model

    connection.close_all()
    init_schema()
    with connection.get_conn() as conn:
        result = refresh_signal_card_read_model(conn, listing_ids=None)
    connection.close_all()
    assert result.mode == "full"
    return result


@pytest.mark.parametrize("case", PARITY_CASES)
@pytest.mark.parametrize("tier", ("guest", "free", "vip", "admin"))
def test_read_model_payload_matches_legacy(
    populated_signal_read_model,
    case,
    tier,
):
    from services.market_data import _load_signals_legacy
    from services.signal_read_model import load_signals_from_read_model

    kwargs = {"tier": tier, **case}
    legacy = _load_signals_legacy(None, **kwargs)
    read_model = load_signals_from_read_model(None, **kwargs)

    assert read_model == legacy


def test_full_reprocess_publishes_after_dedup_and_market(monkeypatch):
    from analytics import lifecycle, market_trend
    from cleansing import dedup, reprocess

    events = []

    class _Connection:
        def execute(self, _sql, _params=None):
            return None

    @contextmanager
    def fake_get_conn():
        yield _Connection()

    monkeypatch.setattr(reprocess, "get_conn", fake_get_conn)
    monkeypatch.setattr(
        reprocess,
        "reprocess_listings",
        lambda **_kwargs: {
            "processed_ids": [11],
            "new": 1,
            "updated": 0,
            "skipped": 0,
        },
    )
    monkeypatch.setattr(
        reprocess,
        "reprocess_valuation",
        lambda **_kwargs: events.append("valuation")
        or {"total": 1, "signals": 1, "outliers": 0},
    )
    monkeypatch.setattr(
        reprocess,
        "_run_listing_map_backfill",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(reprocess, "populate_content_hashes", lambda _conn: 0)
    monkeypatch.setattr(lifecycle, "backfill_first_seen", lambda _conn: None)
    monkeypatch.setattr(lifecycle, "sweep_delisted", lambda _conn: [])
    monkeypatch.setattr(market_trend, "detect_price_drops", lambda _conn: 0)
    monkeypatch.setattr(market_trend, "compute_weekly_trend", lambda _conn: None)
    monkeypatch.setattr(market_trend, "compute_monthly_trend", lambda _conn: None)
    monkeypatch.setattr(market_trend, "compute_daily_trend", lambda _conn: None)
    monkeypatch.setattr(
        dedup,
        "flag_duplicates_in_db",
        lambda _conn: {"dup_groups": 0, "flagged": 0, "unique_lots": 1},
    )
    monkeypatch.setattr(
        reprocess,
        "publish_public_data",
        lambda **kwargs: events.append(("publish", kwargs))
        or {"status": "ok"},
    )

    result = reprocess._run_full_reprocess(full=False)

    assert events[-1] == (
        "publish",
        {
            "listing_ids": (11,),
            "market_changed": True,
            "strict": False,
        },
    )
    assert result["public_read_model"] == {"status": "ok"}


def test_publication_failure_is_returned_unless_strict(monkeypatch):
    from services import public_data_publish

    @contextmanager
    def failing_conn():
        raise RuntimeError("refresh unavailable")
        yield

    monkeypatch.setattr(public_data_publish, "get_conn", failing_conn)

    result = public_data_publish.publish_public_data(
        listing_ids=(11,),
        strict=False,
    )

    assert result == {"status": "error", "error": "refresh unavailable"}
    with pytest.raises(RuntimeError, match="refresh unavailable"):
        public_data_publish.publish_public_data(
            listing_ids=(11,),
            strict=True,
        )


def test_version_is_published_only_after_database_context_exits(
    monkeypatch,
):
    from services import public_data_publish
    from services.signal_read_model import SignalReadModelRefresh

    events = []

    @contextmanager
    def committed_connection():
        events.append("db-enter")
        yield object()
        events.append("db-exit-commit")

    monkeypatch.setenv("RADAR_PUBLIC_CACHE_ENABLED", "1")
    monkeypatch.setattr(public_data_publish, "get_conn", committed_connection)
    monkeypatch.setattr(
        public_data_publish,
        "refresh_signal_card_read_model",
        lambda *args, **kwargs: SignalReadModelRefresh(
            mode="incremental",
            affected_rows=1,
            versions={"signals": 9},
            duration_ms=1.0,
        ),
    )
    monkeypatch.setattr(
        public_data_publish,
        "publish_dataset_versions",
        lambda versions: events.append(("redis", versions)),
        raising=False,
    )
    monkeypatch.setattr(
        public_data_publish,
        "prewarm_configured_routes",
        lambda: events.append("prewarm") or {"succeeded": 1},
        raising=False,
    )

    result = public_data_publish.publish_public_data(
        listing_ids=(), strict=True
    )

    assert events == [
        "db-enter",
        "db-exit-commit",
        ("redis", {"signals": 9}),
        "prewarm",
    ]
    assert result["status"] == "ok"


def test_post_commit_cache_failure_does_not_relabel_database_success(
    monkeypatch,
):
    from services import public_data_publish
    from services.signal_read_model import SignalReadModelRefresh

    @contextmanager
    def committed_connection():
        yield object()

    monkeypatch.setenv("RADAR_PUBLIC_CACHE_ENABLED", "1")
    monkeypatch.setattr(public_data_publish, "get_conn", committed_connection)
    monkeypatch.setattr(
        public_data_publish,
        "refresh_signal_card_read_model",
        lambda *args, **kwargs: SignalReadModelRefresh(
            mode="incremental",
            affected_rows=1,
            versions={"signals": 10},
            duration_ms=1.0,
        ),
    )
    monkeypatch.setattr(
        public_data_publish,
        "publish_dataset_versions",
        lambda versions: (_ for _ in ()).throw(RuntimeError("redis down")),
        raising=False,
    )
    monkeypatch.setattr(
        public_data_publish,
        "prewarm_configured_routes",
        lambda: (_ for _ in ()).throw(RuntimeError("http down")),
        raising=False,
    )

    result = public_data_publish.publish_public_data(
        listing_ids=(), strict=True
    )

    assert result["status"] == "ok"
    assert result["cache"]["version_mirror"]["status"] == "error"
    assert result["cache"]["prewarm"]["status"] == "error"
