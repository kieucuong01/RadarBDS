from contextlib import contextmanager

import pytest

from services import market_data


def _scope(conn, exits=None):
    @contextmanager
    def manager():
        try:
            yield conn
        finally:
            if exits is not None:
                exits.append(conn)

    return manager()


def test_read_conn_uses_scoped_factory_and_restores_default(monkeypatch):
    default_conn = object()
    audit_conn = object()
    monkeypatch.setattr(market_data, "get_conn", lambda: _scope(default_conn))

    with market_data.use_read_connection_factory(lambda: _scope(audit_conn)):
        with market_data._read_conn() as conn:
            assert conn is audit_conn

    with market_data._read_conn() as conn:
        assert conn is default_conn


def test_read_conn_nested_override_restores_outer_factory(monkeypatch):
    default_conn = object()
    outer_conn = object()
    inner_conn = object()
    monkeypatch.setattr(market_data, "get_conn", lambda: _scope(default_conn))

    with market_data.use_read_connection_factory(lambda: _scope(outer_conn)):
        with market_data._read_conn() as conn:
            assert conn is outer_conn
        with market_data.use_read_connection_factory(lambda: _scope(inner_conn)):
            with market_data._read_conn() as conn:
                assert conn is inner_conn
        with market_data._read_conn() as conn:
            assert conn is outer_conn

    with market_data._read_conn() as conn:
        assert conn is default_conn


def test_read_conn_override_resets_after_exception(monkeypatch):
    default_conn = object()
    audit_conn = object()
    monkeypatch.setattr(market_data, "get_conn", lambda: _scope(default_conn))

    with pytest.raises(RuntimeError, match="audit failed"):
        with market_data.use_read_connection_factory(lambda: _scope(audit_conn)):
            with market_data._read_conn() as conn:
                assert conn is audit_conn
                raise RuntimeError("audit failed")

    with market_data._read_conn() as conn:
        assert conn is default_conn


def test_open_read_conn_close_exits_supplied_scope_without_closing_connection():
    class AuditConnection:
        def __init__(self):
            self.close_calls = 0

        def close(self):
            self.close_calls += 1

    audit_conn = AuditConnection()
    exits = []

    with market_data.use_read_connection_factory(
        lambda: _scope(audit_conn, exits=exits)
    ):
        wrapped = market_data._open_read_conn()
        assert wrapped._conn is audit_conn
        wrapped.close()
        wrapped.close()

    assert exits == [audit_conn]
    assert audit_conn.close_calls == 0
