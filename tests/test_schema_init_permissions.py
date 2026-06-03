from contextlib import contextmanager

import pytest


class _FakeCursor:
    def __init__(self, rows=None):
        self._rows = rows or []

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _FakeConn:
    def __init__(self, existing_tables):
        self.existing_tables = set(existing_tables)
        self.rolled_back = False

    def execute(self, sql, params=None):
        if "CREATE TABLE IF NOT EXISTS schema_migrations" in sql:
            return _FakeCursor()
        if "information_schema.tables" in sql:
            return _FakeCursor([{"exists": 1}] if params and params[0] in self.existing_tables else [])
        return _FakeCursor()

    def executescript(self, _script):
        raise RuntimeError("must be owner of table raw_listings")

    def rollback(self):
        self.rolled_back = True


@contextmanager
def _fake_get_conn(conn):
    yield conn


def test_init_schema_skips_ddl_when_existing_schema_lacks_owner(monkeypatch):
    import db.schema as schema

    conn = _FakeConn({"raw_listings", "listings", "valuation_results", "crawl_runs"})
    monkeypatch.setattr(schema, "get_conn", lambda: _fake_get_conn(conn))

    schema.init_schema()

    assert conn.rolled_back


def test_init_schema_still_raises_when_core_schema_missing(monkeypatch):
    import db.schema as schema

    conn = _FakeConn({"raw_listings"})
    monkeypatch.setattr(schema, "get_conn", lambda: _fake_get_conn(conn))

    with pytest.raises(RuntimeError, match="must be owner"):
        schema.init_schema()
