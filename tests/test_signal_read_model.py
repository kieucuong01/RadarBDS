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
        versions = get_dataset_versions(conn, ("signals", "market"))

    assert table["table_name"] == "signal_card_read_model"
    assert {
        "idx_signal_card_public_newest",
        "idx_signal_card_public_filter",
        "idx_signal_card_public_mos",
    } <= indexes
    assert set(versions) == {"signals", "market"}


def test_signal_card_select_sql_emits_boolean_storage_values():
    from services.signal_read_model import _select_sql

    sql, params = _select_sql(None)

    assert "THEN TRUE ELSE FALSE" in sql
    assert "COALESCE(l.has_so, 0)::boolean AS has_so" in sql
    assert params == ()


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
        or {"signals": 8},
    )

    result = signal_read_model.refresh_signal_card_read_model(
        _Connection(),
        listing_ids=None,
    )

    insert_position = events.index(("insert",))
    bump_position = events.index(("bump", ("signals",)))
    assert insert_position < bump_position
    assert result.mode == "full"
    assert result.affected_rows == 3
    assert result.versions == {"signals": 8}


def test_failed_full_refresh_keeps_previous_rows_and_version(monkeypatch):
    from services import signal_read_model

    with connection.get_conn() as conn:
        before_rows = conn.execute(
            "SELECT listing_id FROM signal_card_read_model ORDER BY listing_id"
        ).fetchall()
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
        after_rows = conn.execute(
            "SELECT listing_id FROM signal_card_read_model ORDER BY listing_id"
        ).fetchall()
        after_version = get_dataset_versions(conn, ("signals",))["signals"]

    assert after_rows == before_rows
    assert after_version == before_version


def test_empty_refresh_is_noop_without_version_bump():
    from services.signal_read_model import refresh_signal_card_read_model

    with connection.get_conn() as conn:
        before = get_dataset_versions(conn, ("signals",))["signals"]
        result = refresh_signal_card_read_model(conn, listing_ids=())
        after = get_dataset_versions(conn, ("signals",))["signals"]

    assert result.mode == "noop"
    assert result.affected_rows == 0
    assert after == before


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
        lambda _conn, _names: {"signals": 1},
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
