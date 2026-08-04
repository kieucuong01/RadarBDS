"""Separately bounded, read-only PostgreSQL access for Radar Ask evidence."""
from __future__ import annotations

import atexit
import threading
from contextlib import contextmanager
from typing import Iterator
from urllib.parse import urlparse

import psycopg
from psycopg_pool import ConnectionPool, PoolTimeout

from services.radar_ask.config import RadarAskSettings


class RadarAskDatabaseConfigurationError(RuntimeError):
    """Raised when the isolated evidence database is not configured safely."""


class RadarAskDatabasePoolBusy(RuntimeError):
    """Raised when the separately bounded evidence pool is saturated."""


_pool: ConnectionPool | None = None
_pool_fingerprint: tuple[str, int, float] | None = None
_pool_lock = threading.Lock()


def _configure_connection(conn: psycopg.Connection) -> None:
    conn.execute("SET TIME ZONE 'Asia/Bangkok'")
    conn.commit()


def get_radar_ask_read_pool(
    *, settings: RadarAskSettings | None = None
) -> ConnectionPool:
    """Return the lazy evidence pool without creating an initial connection."""
    global _pool, _pool_fingerprint
    resolved = settings or RadarAskSettings.from_env()
    if not resolved.database_url:
        raise RadarAskDatabaseConfigurationError(
            "Radar Ask read-only database is not configured"
        )
    parsed = urlparse(resolved.database_url)
    if (
        parsed.scheme not in {"postgres", "postgresql"}
        or not parsed.hostname
        or not parsed.path.strip("/")
        or parsed.username != "radar_ask_ro"
    ):
        raise RadarAskDatabaseConfigurationError(
            "Radar Ask evidence pool must use a PostgreSQL URL for radar_ask_ro"
        )
    fingerprint = (
        resolved.database_url,
        resolved.db_pool_max,
        resolved.db_pool_timeout_seconds,
    )
    if _pool is not None:
        if _pool_fingerprint != fingerprint:
            raise RadarAskDatabaseConfigurationError(
                "Radar Ask database settings changed while its pool is active"
            )
        return _pool

    with _pool_lock:
        if _pool is None:
            _pool = ConnectionPool(
                conninfo=resolved.database_url,
                min_size=0,
                max_size=resolved.db_pool_max,
                timeout=resolved.db_pool_timeout_seconds,
                max_idle=300.0,
                max_lifetime=1_800.0,
                configure=_configure_connection,
                open=False,
                name="radar-ask-readonly",
            )
            _pool_fingerprint = fingerprint
            _pool.open(wait=False)
    assert _pool is not None
    return _pool


@contextmanager
def get_radar_ask_read_conn(
    *, settings: RadarAskSettings | None = None
) -> Iterator[psycopg.Connection]:
    """Yield one transaction-scoped, read-only evidence connection."""
    resolved = settings or RadarAskSettings.from_env()
    pool = get_radar_ask_read_pool(settings=resolved)
    try:
        with pool.connection(timeout=resolved.db_pool_timeout_seconds) as conn:
            with conn.transaction():
                conn.execute("SET TRANSACTION READ ONLY")
                conn.execute(
                    "SELECT set_config('statement_timeout', %s, true)",
                    (str(resolved.statement_timeout_ms),),
                )
                yield conn
    except PoolTimeout as exc:
        raise RadarAskDatabasePoolBusy(
            "Radar Ask evidence database is temporarily busy"
        ) from exc


def close_radar_ask_pool() -> None:
    """Close and forget the evidence pool without touching the app write pool."""
    global _pool, _pool_fingerprint
    with _pool_lock:
        pool, _pool = _pool, None
        _pool_fingerprint = None
    if pool is not None:
        pool.close(timeout=5.0)


atexit.register(close_radar_ask_pool)
