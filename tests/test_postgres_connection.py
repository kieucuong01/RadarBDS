from contextlib import contextmanager

import pytest

from db import connection
from db.connection import PgRow, adapt_sql


class _PoolRawConnection:
    def __init__(self):
        self.commit_calls = 0
        self.rollback_calls = 0
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def cursor(self):
        return _PoolCursor(self)

    def commit(self):
        self.commit_calls += 1

    def rollback(self):
        self.rollback_calls += 1


class _PoolCursor:
    rowcount = 1
    description = ()

    def __init__(self, raw):
        self.raw = raw

    def execute(self, sql, params=None):
        self.raw.executed.append((sql, params))

    def close(self):
        pass


class _Pool:
    def __init__(self):
        self.raw = _PoolRawConnection()
        self.timeouts = []
        self.returned = []

    def getconn(self, *, timeout):
        self.timeouts.append(timeout)
        return self.raw

    def putconn(self, raw):
        self.returned.append(raw)


class _TimeoutPool:
    def getconn(self, *, timeout):
        raise connection.PoolTimeout("pool exhausted")


def test_get_conn_returns_connection_to_pool_after_commit(monkeypatch):
    fake_pool = _Pool()
    monkeypatch.setattr(connection, "_get_pool", lambda: fake_pool)

    with connection.get_conn() as conn:
        conn.execute("SELECT 1")

    assert fake_pool.raw.commit_calls == 1
    assert fake_pool.raw.rollback_calls == 0
    assert fake_pool.returned == [fake_pool.raw]
    assert len(fake_pool.timeouts) == 1
    assert isinstance(fake_pool.timeouts[0], float)


def test_get_conn_rolls_back_and_returns_connection_on_error(monkeypatch):
    fake_pool = _Pool()
    monkeypatch.setattr(connection, "_get_pool", lambda: fake_pool)

    with pytest.raises(RuntimeError, match="boom"):
        with connection.get_conn():
            raise RuntimeError("boom")

    assert fake_pool.raw.commit_calls == 0
    assert fake_pool.raw.rollback_calls == 1
    assert fake_pool.returned == [fake_pool.raw]


def test_pool_timeout_becomes_database_pool_busy(monkeypatch):
    monkeypatch.setattr(connection, "_get_pool", lambda: _TimeoutPool())

    with pytest.raises(connection.DatabasePoolBusy, match="saturated"):
        with connection.get_conn():
            pass


def test_test_process_requires_explicit_test_database(monkeypatch):
    monkeypatch.delenv("RADAR_TEST_DATABASE_URL", raising=False)
    monkeypatch.setattr(connection, "_is_test_process", lambda: True)

    with pytest.raises(connection.DatabaseConfigurationError, match="RADAR_TEST_DATABASE_URL"):
        connection._database_url()


def test_test_database_name_must_contain_test(monkeypatch):
    monkeypatch.setenv(
        "RADAR_TEST_DATABASE_URL",
        "postgresql://radar@127.0.0.1:5432/radar_bds",
    )
    monkeypatch.setattr(connection, "_is_test_process", lambda: True)

    with pytest.raises(connection.DatabaseConfigurationError, match="database name"):
        connection._database_url()


class _AdvisoryLockConnection:
    def __init__(self, locked):
        self.locked = locked
        self.calls = []

    def execute(self, sql, params=()):
        self.calls.append((sql, params))
        if "pg_try_advisory_lock" in sql:
            return _AdvisoryLockResult({"locked": self.locked})
        if "pg_advisory_lock" in sql:
            return _AdvisoryLockResult({"locked": None})
        return _AdvisoryLockResult(None)


class _AdvisoryLockResult:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row


def _install_advisory_connection(monkeypatch, conn):
    @contextmanager
    def fake_get_conn():
        yield conn

    monkeypatch.setattr(connection, "get_conn", fake_get_conn)


def test_nonblocking_advisory_lock_raises_specific_runtime_subclass_when_busy(
    monkeypatch,
):
    conn = _AdvisoryLockConnection(locked=False)
    _install_advisory_connection(monkeypatch, conn)

    with pytest.raises(RuntimeError) as exc_info:
        with connection.advisory_lock("checkout", wait=False):
            raise AssertionError("busy lock must not enter critical section")

    assert type(exc_info.value) is connection.AdvisoryLockBusy
    assert [sql for sql, _params in conn.calls] == [
        "SELECT pg_try_advisory_lock(?) AS locked"
    ]


def test_blocking_advisory_lock_treats_return_from_void_function_as_acquired(
    monkeypatch,
):
    conn = _AdvisoryLockConnection(locked=None)
    _install_advisory_connection(monkeypatch, conn)

    with connection.advisory_lock("checkout", wait=True):
        pass

    assert [sql for sql, _params in conn.calls] == [
        "SELECT pg_advisory_lock(?) AS locked",
        "SELECT pg_advisory_unlock(?)",
    ]


def test_adapt_sql_translates_insert_or_ignore_and_placeholders():
    sql, params = adapt_sql(
        "INSERT OR IGNORE INTO raw_listings (source, url, raw_json) VALUES (?, ?, ?)",
        ("facebook", "https://x.test/1", "{}"),
    )

    assert "INSERT INTO raw_listings" in sql
    assert "ON CONFLICT (source, url) DO NOTHING" in sql
    assert "VALUES (%s, %s, %s)" in sql
    assert params == ("facebook", "https://x.test/1", "{}")


def test_adapt_sql_translates_common_datetime_expressions():
    sql, params = adapt_sql(
        """
        SELECT strftime('%Y-%m', COALESCE(posted_at, crawled_at)) AS month_key
        FROM listings
        WHERE datetime(COALESCE(crawled_at, '1970-01-01')) >= datetime('now', ?)
          AND datetime(started_at) >= datetime(?)
        """,
        ("-30 days", "2026-05-01"),
    )

    assert "to_char(COALESCE(posted_at, crawled_at)::timestamp, 'YYYY-MM')" in sql
    assert "(COALESCE(crawled_at, '1970-01-01'))::timestamp >= (CURRENT_TIMESTAMP + (%s::interval))" in sql
    assert "(started_at)::timestamp >= (%s::timestamp)" in sql
    assert params == ("-30 days", "2026-05-01")


def test_adapt_sql_translates_named_parameters():
    sql, params = adapt_sql(
        "UPDATE listings SET updated_at=datetime('now') WHERE id=:id",
        {"id": 42},
    )

    assert "updated_at=CURRENT_TIMESTAMP::text" in sql
    assert "id=%(id)s" in sql
    assert params == {"id": 42}


def test_adapt_sql_escapes_literal_percent_when_parameters_are_present():
    sql, params = adapt_sql(
        "SELECT 1 FROM listing_images WHERE img_url LIKE '%fbcdn.net%' AND listing_id=?",
        (123,),
    )

    assert "LIKE '%%fbcdn.net%%'" in sql
    assert "listing_id=%s" in sql
    assert params == (123,)


def test_pg_row_supports_sqlite_row_access_patterns():
    row = PgRow((123, "Tan An"), ("id", "ward"))

    assert row[0] == 123
    assert row["id"] == 123
    assert row["ward"] == "Tan An"
    assert dict(row) == {"id": 123, "ward": "Tan An"}
    assert row.get("missing", "fallback") == "fallback"
