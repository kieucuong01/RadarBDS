"""PostgreSQL connection management for Radar BDS.

Runtime code is Postgres-only. SQLite is only used by the one-time migration
script that copies the legacy ``data/radar_bds.db`` into PostgreSQL.
"""
from __future__ import annotations

import logging
import os
import re
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

logger = logging.getLogger(__name__)

# Ensure .env at repo root is loaded even when entrypoints don't import settings.
try:  # pragma: no cover
    import config.settings as _settings  # noqa: F401
except Exception:
    pass

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
LEGACY_SQLITE_PATH = DATA_DIR / "radar_bds.db"

# Compatibility for older callers that used DB_PATH to find data/images.
# The PostgreSQL connection layer never opens this file.
DB_PATH = LEGACY_SQLITE_PATH

_local = threading.local()

ID_TABLES = {
    "admin_audit_log",
    "assistant_feedback",
    "assistant_messages",
    "assistant_sessions",
    "ai_deal_review",
    "ai_training_feedback",
    "broker_blacklist",
    "crawl_run_progress",
    "crawl_runs",
    "dedup_overrides",
    "digital_product_order_events",
    "digital_product_orders",
    "infra_entries",
    "lead_captures",
    "listing_images",
    "listings",
    "market_weekly",
    "notification_log",
    "price_history",
    "raw_listings",
    "user_audit_log",
    "user_favorite_listings",
    "user_watchlists",
    "users",
    "valuation_results",
    "valuation_model_runs",
    "valuation_shadow_results",
}


class DatabaseConfigurationError(RuntimeError):
    """Raised when PostgreSQL runtime configuration is missing or unusable."""


class AdvisoryLockBusy(RuntimeError):
    """Raised when a non-blocking PostgreSQL advisory lock is already held."""


class PgRow:
    """Small sqlite3.Row-compatible wrapper around a PostgreSQL tuple row."""

    __slots__ = ("_values", "_index")

    def __init__(self, values: Sequence[Any], columns: Sequence[str]):
        self._values = tuple(values)
        self._index = {name: i for i, name in enumerate(columns)}

    def __getitem__(self, key: int | str) -> Any:
        if isinstance(key, int):
            return self._values[key]
        return self._values[self._index[key]]

    def __iter__(self) -> Iterator[Any]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __contains__(self, key: object) -> bool:
        return key in self._index

    def keys(self) -> list[str]:
        return list(self._index.keys())

    def items(self):
        return ((k, self[k]) for k in self.keys())

    def get(self, key: str, default: Any = None) -> Any:
        return self[key] if key in self._index else default


class PgCursor:
    """Cursor wrapper that exposes the subset of sqlite3.Cursor we use."""

    def __init__(self, cursor):
        self._cursor = cursor
        self.lastrowid: int | None = None
        self.rowcount: int = -1

    def execute(self, sql: str, params: Any = None):
        sql, params = adapt_sql(sql, params)
        sql = _add_returning_id(sql)
        self._cursor.execute(sql, params)
        self.rowcount = self._cursor.rowcount
        self.lastrowid = None
        if _has_returning_id(sql):
            row = self._cursor.fetchone()
            if row:
                self.lastrowid = row[0]
        return self

    def executemany(self, sql: str, params_seq: Iterable[Any]):
        sql, _ = adapt_sql(sql, None, has_params=True)
        self._cursor.executemany(sql, list(params_seq))
        self.rowcount = self._cursor.rowcount
        self.lastrowid = None
        return self

    def fetchone(self):
        row = self._cursor.fetchone()
        return self._wrap(row) if row is not None else None

    def fetchall(self):
        return [self._wrap(row) for row in self._cursor.fetchall()]

    def __iter__(self):
        for row in self._cursor:
            yield self._wrap(row)

    def close(self) -> None:
        self._cursor.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

    def _wrap(self, row):
        if row is None:
            return None
        columns = [d.name for d in self._cursor.description or []]
        return PgRow(row, columns)


class PgConnection:
    """Connection wrapper with sqlite-like helpers used across the app."""

    def __init__(self, raw):
        self._raw = raw

    def execute(self, sql: str, params: Any = None) -> PgCursor:
        cur = PgCursor(self._raw.cursor())
        return cur.execute(sql, params)

    def executemany(self, sql: str, params_seq: Iterable[Any]) -> PgCursor:
        cur = PgCursor(self._raw.cursor())
        return cur.executemany(sql, params_seq)

    def executescript(self, script: str) -> None:
        for statement in _split_sql_script(script):
            sql = adapt_sql(statement, None)[0]
            with self._raw.cursor() as cur:
                cur.execute(sql)

    def cursor(self) -> PgCursor:
        return PgCursor(self._raw.cursor())

    def commit(self) -> None:
        self._raw.commit()

    def rollback(self) -> None:
        self._raw.rollback()

    def close(self) -> None:
        self._raw.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type:
            self.rollback()
        else:
            self.commit()
        self.close()
        return False


def _database_url() -> str:
    url = (os.getenv("RADAR_TEST_DATABASE_URL") or os.getenv("DATABASE_URL") or "").strip()
    if not url:
        raise DatabaseConfigurationError(
            "DATABASE_URL is required. Put a Supabase Direct or Session Pooler "
            "Postgres URL in .env. See .env.example."
        )
    return url


def connect(_unused_path: str | None = None) -> PgConnection:
    """Open a fresh PostgreSQL connection.

    The optional path argument exists only so older call sites can keep their
    shape while the runtime ignores SQLite paths.
    """
    url = _database_url()
    try:
        import psycopg
    except ImportError as exc:  # pragma: no cover - depends on local env
        raise DatabaseConfigurationError(
            "psycopg is required for PostgreSQL runtime. Install requirements.txt."
        ) from exc

    raw = psycopg.connect(url)
    raw.execute("SET TIME ZONE 'Asia/Bangkok'")
    raw.commit()
    return PgConnection(raw)


def _get_connection() -> PgConnection:
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = connect()
        logger.info("PostgreSQL connection initialized")
    return _local.conn


@contextmanager
def get_conn():
    conn = _get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def close_all() -> None:
    if hasattr(_local, "conn") and _local.conn:
        _local.conn.close()
        _local.conn = None


@contextmanager
def advisory_lock(name: str, wait: bool = False):
    """Process-safe job lock using PostgreSQL advisory locks."""
    with get_conn() as conn:
        lock_id = _lock_id(name)
        fn = "pg_advisory_lock" if wait else "pg_try_advisory_lock"
        row = conn.execute(f"SELECT {fn}(?) AS locked", (lock_id,)).fetchone()
        if not wait and not (bool(row["locked"]) if row else False):
            raise AdvisoryLockBusy(
                f"Another Radar BDS job is already running: {name}"
            )
        try:
            yield
        finally:
            conn.execute("SELECT pg_advisory_unlock(?)", (lock_id,))


def _lock_id(name: str) -> int:
    import hashlib

    digest = hashlib.sha256(f"radar-bds:{name}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


def adapt_sql(sql: str, params: Any = None, *, has_params: bool | None = None) -> tuple[str, Any]:
    """Translate the SQLite-flavored SQL still present in call sites."""
    if has_params is None:
        has_params = params is not None
    sql = _strip_sqlite_comments(sql)
    sql = _translate_schema_sql(sql)
    sql = _translate_time_sql(sql)
    sql = _translate_conflict_sql(sql)
    sql = _translate_placeholders(sql, escape_percent=has_params)
    if isinstance(params, Mapping):
        sql = re.sub(r"(?<!:):([A-Za-z_][A-Za-z0-9_]*)", r"%(\1)s", sql)
    if params is None:
        return sql, None
    if isinstance(params, Mapping):
        return sql, dict(params)
    if isinstance(params, tuple):
        return sql, params
    if isinstance(params, list):
        return sql, tuple(params)
    return sql, params


def _strip_sqlite_comments(sql: str) -> str:
    return "\n".join(line for line in sql.splitlines() if not line.strip().startswith("--"))


def _translate_schema_sql(sql: str) -> str:
    sql = re.sub(
        r"\bINTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT\b",
        "INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY",
        sql,
        flags=re.I,
    )
    sql = re.sub(r"\bREAL\b", "DOUBLE PRECISION", sql, flags=re.I)
    sql = sql.replace("DEFAULT (datetime('now'))", "DEFAULT (CURRENT_TIMESTAMP::text)")
    return sql


def _translate_time_sql(sql: str) -> str:
    sql = re.sub(
        r"datetime\('now',\s*\?\)",
        "(CURRENT_TIMESTAMP + (?::interval))",
        sql,
        flags=re.I,
    )
    sql = re.sub(
        r"datetime\('now',\s*'([^']+)'\)",
        r"(CURRENT_TIMESTAMP + INTERVAL '\1')",
        sql,
        flags=re.I,
    )
    replacements = {
        "datetime('now')": "CURRENT_TIMESTAMP::text",
        "julianday('now')": "EXTRACT(EPOCH FROM CURRENT_TIMESTAMP) / 86400.0",
    }
    for old, new in replacements.items():
        sql = sql.replace(old, new)
    sql = re.sub(
        r"julianday\(substr\(COALESCE\(([^)]+)\),1,10\)\)",
        r"EXTRACT(EPOCH FROM COALESCE(\1)::timestamp) / 86400.0",
        sql,
        flags=re.I,
    )
    sql = re.sub(
        r"strftime\('%Y-%m-%d',\s*COALESCE\(([^)]+)\)\)",
        r"to_char(COALESCE(\1)::timestamp, 'YYYY-MM-DD')",
        sql,
        flags=re.I,
    )
    sql = re.sub(
        r"strftime\('%Y-%m',\s*COALESCE\(([^)]+)\)\)",
        r"to_char(COALESCE(\1)::timestamp, 'YYYY-MM')",
        sql,
        flags=re.I,
    )
    sql = re.sub(
        r"strftime\('%Y-W%W',\s*COALESCE\(([^)]+)\)\)",
        r"to_char(COALESCE(\1)::timestamp, 'IYYY-\"W\"IW')",
        sql,
        flags=re.I,
    )
    sql = re.sub(
        r"strftime\('%Y-%m',\s*([A-Za-z_][A-Za-z0-9_]*)\)",
        r"to_char(\1::timestamp, 'YYYY-MM')",
        sql,
        flags=re.I,
    )
    sql = re.sub(
        r"\bdate\(substr\(COALESCE\(([^)]+)\),\s*1,\s*10\)\)",
        r"substring(COALESCE(\1) from 1 for 10)::date",
        sql,
        flags=re.I,
    )
    sql = re.sub(r"\bdate\(substr\(([^,]+),\s*1,\s*10\)\)", r"substring(\1 from 1 for 10)::date", sql, flags=re.I)
    sql = re.sub(r"datetime\(\?\)", "(?::timestamp)", sql, flags=re.I)
    sql = re.sub(
        r"datetime\(COALESCE\(([^)]+)\)\)",
        r"(COALESCE(\1))::timestamp",
        sql,
        flags=re.I,
    )
    sql = re.sub(
        r"datetime\(([A-Za-z_][A-Za-z0-9_.]*)\)",
        r"(\1)::timestamp",
        sql,
        flags=re.I,
    )
    return sql


def _translate_conflict_sql(sql: str) -> str:
    sql = re.sub(
        r"INSERT\s+OR\s+IGNORE\s+INTO",
        "INSERT INTO",
        sql,
        flags=re.I,
    )
    if re.search(r"INSERT\s+INTO", sql, flags=re.I) and " OR IGNORE " in sql.upper():
        sql = sql.replace(" OR IGNORE ", " ")
    if re.search(r"INSERT\s+INTO", sql, flags=re.I) and "ON CONFLICT" not in sql.upper():
        table = _insert_table(sql)
        conflict = _default_conflict_target(table)
        if conflict:
            sql = f"{sql.rstrip()} ON CONFLICT {conflict} DO NOTHING"
    return sql


def _default_conflict_target(table: str | None) -> str | None:
    return {
        "raw_listings": "(source, url)",
        "listing_images": "(listing_id, img_url)",
    }.get(table or "")


def _translate_placeholders(sql: str, *, escape_percent: bool = False) -> str:
    out: list[str] = []
    in_single = False
    in_double = False
    i = 0
    while i < len(sql):
        ch = sql[i]
        if ch == "'" and not in_double:
            in_single = not in_single
            out.append(ch)
        elif ch == '"' and not in_single:
            in_double = not in_double
            out.append(ch)
        elif ch == "?" and not in_single and not in_double:
            out.append("%s")
        elif ch == "%" and escape_percent:
            out.append("%%")
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def _add_returning_id(sql: str) -> str:
    if "RETURNING" in sql.upper():
        return sql
    table = _insert_table(sql)
    if table in ID_TABLES:
        return f"{sql.rstrip()} RETURNING id"
    return sql


def _has_returning_id(sql: str) -> bool:
    return bool(re.search(r"\bRETURNING\s+id\b", sql, flags=re.I))


def _insert_table(sql: str) -> str | None:
    m = re.match(r"\s*INSERT\s+INTO\s+\"?([A-Za-z_][A-Za-z0-9_]*)\"?", sql, flags=re.I)
    return m.group(1) if m else None


def _split_sql_script(script: str) -> list[str]:
    statements: list[str] = []
    buf: list[str] = []
    in_single = False
    in_double = False
    in_line_comment = False
    prev = ""
    for ch in script:
        if in_line_comment:
            if ch in "\r\n":
                in_line_comment = False
                buf.append(ch)
            prev = ch
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "-" and prev == "-" and not in_single and not in_double:
            if buf:
                buf.pop()
            in_line_comment = True
            prev = ch
            continue
        if ch == ";" and not in_single and not in_double:
            stmt = "".join(buf).strip()
            if stmt:
                statements.append(stmt)
            buf = []
        else:
            buf.append(ch)
        prev = ch
    tail = "".join(buf).strip()
    if tail:
        statements.append(tail)
    return statements
