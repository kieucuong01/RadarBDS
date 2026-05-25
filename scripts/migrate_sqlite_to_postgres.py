"""One-time migration from legacy SQLite to PostgreSQL.

Usage:
    python -X utf8 scripts/migrate_sqlite_to_postgres.py \
        --sqlite data/radar_bds.db \
        --database-url postgresql://radar_app:...@127.0.0.1:5432/radar_bds \
        --truncate
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path
from typing import Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config.settings as _settings  # noqa: F401 - load .env before argparse defaults


TABLE_ORDER = [
    "raw_listings",
    "listings",
    "listing_images",
    "price_history",
    "crawl_runs",
    "crawl_run_progress",
    "market_weekly",
    "valuation_results",
    "users",
    "lead_captures",
    "dedup_overrides",
    "broker_blacklist",
    "admin_audit_log",
    "ai_training_feedback",
    "ai_deal_review",
    "infra_entries",
    "user_sessions",
    "user_watchlists",
    "user_audit_log",
    "rate_limits",
    "notification_log",
]


ID_TABLES = [t for t in TABLE_ORDER if t not in {"user_sessions", "rate_limits"}]

SQLITE_WHERE = {
    "listings": "raw_id IS NULL OR raw_id IN (SELECT id FROM raw_listings)",
    "listing_images": "listing_id IN (SELECT id FROM listings)",
    "price_history": "listing_id IN (SELECT id FROM listings)",
    "valuation_results": "listing_id IN (SELECT id FROM listings)",
    "lead_captures": "listing_id IS NULL OR listing_id IN (SELECT id FROM listings)",
    "dedup_overrides": (
        "listing_id IN (SELECT id FROM listings) "
        "AND target_listing_id IN (SELECT id FROM listings)"
    ),
    "ai_training_feedback": "listing_id IN (SELECT id FROM listings)",
    "ai_deal_review": "listing_id IN (SELECT id FROM listings)",
    "user_sessions": "user_id IN (SELECT id FROM users)",
    "user_watchlists": "user_id IN (SELECT id FROM users)",
    "user_audit_log": "user_id IS NULL OR user_id IN (SELECT id FROM users)",
    "notification_log": (
        "user_id IN (SELECT id FROM users) "
        "AND listing_id IN (SELECT id FROM listings)"
    ),
}


def sqlite_tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {r[0] for r in rows}


def sqlite_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]


def pg_columns(conn, table: str) -> list[str]:
    rows = conn.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema='public' AND table_name=?
        ORDER BY ordinal_position
        """,
        (table,),
    ).fetchall()
    return [r["column_name"] for r in rows]


def chunks(items: list[sqlite3.Row], size: int = 500) -> Iterable[list[sqlite3.Row]]:
    for i in range(0, len(items), size):
        yield items[i:i + size]


def truncate_postgres(conn) -> None:
    tables = ", ".join(TABLE_ORDER)
    conn.execute(f"TRUNCATE {tables} RESTART IDENTITY CASCADE")


def copy_table(sqlite_conn: sqlite3.Connection, pg_conn, table: str) -> tuple[int, int, int]:
    sqlite_cols = sqlite_columns(sqlite_conn, table)
    pg_cols = pg_columns(pg_conn, table)
    cols = [c for c in sqlite_cols if c in pg_cols]
    if not cols:
        return 0, 0, 0

    total_rows = sqlite_conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    where_sql = SQLITE_WHERE.get(table)
    query = f"SELECT {', '.join(cols)} FROM {table}"
    if where_sql:
        query += f" WHERE {where_sql}"
    query += " ORDER BY rowid"
    source_rows = sqlite_conn.execute(query).fetchall()
    if not source_rows:
        return total_rows, 0, total_rows

    placeholders = ", ".join("?" for _ in cols)
    col_sql = ", ".join(cols)
    conflict = "id" if "id" in cols else ("token" if table == "user_sessions" else "key")
    update_cols = [c for c in cols if c != conflict]
    if update_cols:
        update_sql = ", ".join(f"{c}=EXCLUDED.{c}" for c in update_cols)
        suffix = f"ON CONFLICT ({conflict}) DO UPDATE SET {update_sql}"
    else:
        suffix = f"ON CONFLICT ({conflict}) DO NOTHING"
    insert_sql = f"INSERT INTO {table} ({col_sql}) VALUES ({placeholders}) {suffix}"

    copied = 0
    for batch in chunks(source_rows):
        pg_conn.executemany(insert_sql, [tuple(row[c] for c in cols) for row in batch])
        copied += len(batch)
    return total_rows, copied, total_rows - len(source_rows)


def reset_sequences(conn) -> None:
    for table in ID_TABLES:
        conn.execute(
            """
            SELECT setval(
                pg_get_serial_sequence(?, 'id'),
                COALESCE((SELECT MAX(id) FROM %s), 1),
                (SELECT MAX(id) FROM %s) IS NOT NULL
            )
            """ % (table, table),
            (table,),
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate Radar BDS SQLite DB to PostgreSQL")
    parser.add_argument("--sqlite", default="data/radar_bds.db", help="Legacy SQLite DB path")
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"), help="Target PostgreSQL DATABASE_URL")
    parser.add_argument("--truncate", action="store_true", help="Truncate target tables before copying")
    args = parser.parse_args()

    sqlite_path = Path(args.sqlite).expanduser().resolve()
    if not sqlite_path.exists():
        raise SystemExit(f"SQLite DB not found: {sqlite_path}")
    if not args.database_url:
        raise SystemExit("Missing --database-url or DATABASE_URL")

    os.environ["DATABASE_URL"] = args.database_url

    from db.connection import close_all, connect
    from db.schema import init_schema

    init_schema()
    close_all()

    sqlite_conn = sqlite3.connect(str(sqlite_path))
    sqlite_conn.row_factory = sqlite3.Row
    source_tables = sqlite_tables(sqlite_conn)

    pg_conn = connect()
    try:
        if args.truncate:
            truncate_postgres(pg_conn)
            pg_conn.commit()

        print(f"Source SQLite: {sqlite_path}")
        print("table,sqlite_rows,copied,skipped,postgres_rows")
        for table in TABLE_ORDER:
            if table not in source_tables:
                continue
            sqlite_n, copied, skipped = copy_table(sqlite_conn, pg_conn, table)
            pg_conn.commit()
            pg_n = pg_conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
            print(f"{table},{sqlite_n},{copied},{skipped},{pg_n}")
        reset_sequences(pg_conn)
        pg_conn.commit()
    finally:
        sqlite_conn.close()
        pg_conn.close()


if __name__ == "__main__":
    main()
