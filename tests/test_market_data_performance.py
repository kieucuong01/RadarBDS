from contextlib import contextmanager


class _FakeCursor:
    def __init__(self, row=None, rows=None):
        self._row = row
        self._rows = rows or []

    def fetchone(self):
        return self._row

    def fetchall(self):
        return self._rows


class _FakeReadConnection:
    def __init__(self):
        self.queries = []
        self.closed = False

    def execute(self, sql, params=None):
        self.queries.append((sql, params))
        if "COUNT(*)" in sql:
            return _FakeCursor(row=(0,))
        return _FakeCursor(rows=[])

    def close(self):
        self.closed = True
        raise AssertionError("market data reads should not close the shared connection")


def test_load_signals_uses_shared_connection_scope(monkeypatch):
    import services.market_data as market_data

    conn = _FakeReadConnection()

    @contextmanager
    def fake_read_conn(_db_path=None):
        yield conn

    def fail_fresh_connect(_db_path=None):
        raise AssertionError("load_signals opened a fresh connection")

    monkeypatch.setattr(market_data, "connect", fail_fresh_connect, raising=False)
    monkeypatch.setattr(market_data, "_read_conn", fake_read_conn, raising=False)

    result = market_data.load_signals(None, sources=["facebook"], wards=["Tan An"], tier="admin")

    assert result["total"] == 0
    assert result["signals"] == []
    assert conn.closed is False
    assert len(conn.queries) == 1
    assert "COUNT(*) OVER()" in conn.queries[0][0]
    assert "LEFT JOIN LATERAL" in conn.queries[0][0]


def test_load_counts_uses_compact_shared_connection_scope(monkeypatch):
    import services.market_data as market_data

    class _CountsConnection:
        def __init__(self):
            self.queries = []
            self.closed = False

        def execute(self, sql, params=None):
            self.queries.append((sql, params))
            return _FakeCursor(row={
                "total": 12,
                "hot": 1,
                "new_recent_days_7": 2,
                "price_drops": 4,
            })

        def close(self):
            self.closed = True
            raise AssertionError("market count reads should not close the shared connection")

    conn = _CountsConnection()

    @contextmanager
    def fake_read_conn(_db_path=None):
        yield conn

    def fail_fresh_connect(_db_path=None):
        raise AssertionError("load_counts opened a fresh connection")

    monkeypatch.setattr(market_data, "connect", fail_fresh_connect, raising=False)
    monkeypatch.setattr(market_data, "_read_conn", fake_read_conn, raising=False)

    result = market_data.load_counts(None, sources=["facebook"], wards=["Tan An"])

    assert result["total"] == 12
    assert result["new_recent_days_7"] == 2
    assert conn.closed is False
    assert len(conn.queries) == 1
    assert "FROM listings" in conn.queries[0][0]
    assert "latest_valuation" not in conn.queries[0][0]
    assert "listing_images" not in conn.queries[0][0]
    assert "LEFT JOIN LATERAL" not in conn.queries[0][0]


def test_dashboard_cache_reuses_loader_until_ttl_expires():
    import app as radar_app

    radar_app.clear_dashboard_cache()
    calls = {"n": 0}

    def loader():
        calls["n"] += 1
        return {"stats": {"calls": calls["n"]}}

    first = radar_app._cached_dashboard_payload(("same", "filters"), loader, now=100.0, ttl_seconds=30)
    second = radar_app._cached_dashboard_payload(("same", "filters"), loader, now=120.0, ttl_seconds=30)
    expired = radar_app._cached_dashboard_payload(("same", "filters"), loader, now=131.0, ttl_seconds=30)

    assert first == {"stats": {"calls": 1}}
    assert second == first
    assert expired == {"stats": {"calls": 2}}
    assert calls["n"] == 2


def test_schema_defines_feed_performance_indexes():
    from db.schema import SCHEMA_SQL

    assert "idx_valuation_signal_trust_score" in SCHEMA_SQL
    assert "trust_score DESC" in SCHEMA_SQL
    assert "signal_score DESC" in SCHEMA_SQL
    assert "idx_images_listing_legal_order" in SCHEMA_SQL


def test_dashboard_guest_rate_limit_uses_memory_without_db(monkeypatch):
    from flask import Flask
    import auth.core as auth

    auth.clear_rate_limit_cache()
    db_calls = {"n": 0}

    def fail_get_conn():
        db_calls["n"] += 1
        raise AssertionError("dashboard guest rate limit should not hit the database")

    monkeypatch.setattr(auth, "get_conn", fail_get_conn)

    flask_app = Flask(__name__)

    @auth.rate_limit("dashboard", limits={"guest": 2})
    def view():
        return {"ok": True}

    with flask_app.test_request_context("/", environ_base={"REMOTE_ADDR": "1.2.3.4"}):
        assert view() == {"ok": True}
        assert view() == {"ok": True}
        limited = view()

    assert db_calls["n"] == 0
    assert limited[1] == 429
