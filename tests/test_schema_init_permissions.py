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
        self.rollback_count = 0
        self.commit_count = 0
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append(sql)
        if "CREATE TABLE IF NOT EXISTS schema_migrations" in sql:
            return _FakeCursor()
        if "CREATE TABLE IF NOT EXISTS listing_map_locations" in sql:
            self.existing_tables.add("listing_map_locations")
            return _FakeCursor()
        if "information_schema.tables" in sql:
            return _FakeCursor([{"exists": 1}] if params and params[0] in self.existing_tables else [])
        return _FakeCursor()

    def executescript(self, _script):
        raise RuntimeError("must be owner of table raw_listings")

    def rollback(self):
        self.rolled_back = True
        self.rollback_count += 1

    def commit(self):
        self.commit_count += 1


@contextmanager
def _fake_get_conn(conn):
    yield conn


def test_init_schema_skips_ddl_when_existing_schema_lacks_owner(monkeypatch):
    import db.schema as schema

    conn = _FakeConn(
        {
            "raw_listings",
            "listings",
            "valuation_results",
            "crawl_runs",
            "public_dataset_versions",
            "signal_card_read_model",
        }
    )
    monkeypatch.setattr(schema, "get_conn", lambda: _fake_get_conn(conn))

    schema.init_schema()

    assert conn.rolled_back
    assert any("CREATE TABLE IF NOT EXISTS user_favorite_listings" in sql for sql in conn.executed)
    assert any("CREATE TABLE IF NOT EXISTS listing_map_locations" in sql for sql in conn.executed)
    assert any("CREATE TABLE IF NOT EXISTS admin_jobs" in sql for sql in conn.executed)


def test_init_schema_still_raises_when_core_schema_missing(monkeypatch):
    import db.schema as schema

    conn = _FakeConn({"raw_listings"})
    monkeypatch.setattr(schema, "get_conn", lambda: _fake_get_conn(conn))

    with pytest.raises(RuntimeError, match="must be owner"):
        schema.init_schema()


def test_init_schema_does_not_accept_missing_derived_location_table(monkeypatch):
    import db.schema as schema

    class _NoDerivedTableConnection(_FakeConn):
        def execute(self, sql, params=None):
            if "CREATE TABLE IF NOT EXISTS listing_map_locations" in sql:
                raise RuntimeError("permission denied for schema public")
            return super().execute(sql, params)

    conn = _NoDerivedTableConnection(
        {
            "raw_listings",
            "listings",
            "valuation_results",
            "crawl_runs",
            "public_dataset_versions",
            "signal_card_read_model",
        }
    )
    monkeypatch.setattr(schema, "get_conn", lambda: _fake_get_conn(conn))

    with pytest.raises(RuntimeError, match="listing_map_locations"):
        schema.init_schema()


def test_init_schema_does_not_accept_missing_public_dataset_versions(monkeypatch):
    import db.schema as schema

    class _NoPublicVersionsConnection(_FakeConn):
        def execute(self, sql, params=None):
            if "CREATE TABLE IF NOT EXISTS public_dataset_versions" in sql:
                raise RuntimeError("permission denied for schema public")
            return super().execute(sql, params)

    conn = _NoPublicVersionsConnection(
        {"raw_listings", "listings", "valuation_results", "crawl_runs"}
    )
    monkeypatch.setattr(schema, "get_conn", lambda: _fake_get_conn(conn))

    with pytest.raises(RuntimeError, match="public_dataset_versions"):
        schema.init_schema()


def test_init_schema_does_not_accept_missing_signal_read_model(monkeypatch):
    import db.schema as schema

    class _NoSignalReadModelConnection(_FakeConn):
        def execute(self, sql, params=None):
            if "CREATE TABLE IF NOT EXISTS signal_card_read_model" in sql:
                raise RuntimeError("permission denied for schema public")
            return super().execute(sql, params)

    conn = _NoSignalReadModelConnection(
        {
            "raw_listings",
            "listings",
            "valuation_results",
            "crawl_runs",
            "public_dataset_versions",
        }
    )
    monkeypatch.setattr(schema, "get_conn", lambda: _fake_get_conn(conn))

    with pytest.raises(RuntimeError, match="signal_card_read_model"):
        schema.init_schema()


def test_init_schema_commits_required_tables_before_optional_permission_failure(
    monkeypatch,
):
    import db.schema as schema

    class _LimitedOwnerConnection(_FakeConn):
        def execute(self, sql, params=None):
            if "CREATE TABLE IF NOT EXISTS public_dataset_versions" in sql:
                self.existing_tables.add("public_dataset_versions")
            if "CREATE TABLE IF NOT EXISTS signal_card_read_model" in sql:
                self.existing_tables.add("signal_card_read_model")
            if "CREATE TABLE IF NOT EXISTS admin_jobs" in sql:
                raise RuntimeError("must be owner of table admin_jobs")
            return super().execute(sql, params)

    conn = _LimitedOwnerConnection(
        {"raw_listings", "listings", "valuation_results", "crawl_runs"}
    )
    monkeypatch.setattr(schema, "get_conn", lambda: _fake_get_conn(conn))

    schema.init_schema()

    assert conn.commit_count == 1
    assert conn.rollback_count == 2
    assert "public_dataset_versions" in conn.existing_tables
    assert "signal_card_read_model" in conn.existing_tables


def test_public_read_model_migration_tolerates_optional_reloption_permission():
    import db.schema as schema

    statements = []

    class _CaptureConnection:
        def execute(self, sql, params=None):
            statements.append((sql, params))

    schema._migrate_public_read_model(_CaptureConnection())

    tuning_statements = [
        sql
        for sql, _params in statements
        if "autovacuum_analyze_scale_factor" in sql
    ]
    assert len(tuning_statements) == 7
    assert all("DO $$" in sql for sql in tuning_statements)
    assert all(
        "WHEN insufficient_privilege" in sql
        for sql in tuning_statements
    )
