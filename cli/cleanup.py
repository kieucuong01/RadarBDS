"""DB cleanup: prune stale rows + orphan image files.

Dry-run by default — call with apply=True to actually delete. FK cascade
in the schema removes listing_images / price_history / valuation_results
when a listings row is deleted (see db/schema.py ON DELETE CASCADE).
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import TypedDict

from db.connection import DB_PATH, get_conn

logger = logging.getLogger(__name__)

DEFAULT_SOLD_DAYS = 90
DEFAULT_RAW_DAYS = 60
DEFAULT_NOTIF_DAYS = 180

IMAGES_DIR = Path(__file__).parent.parent / "data" / "images"


class CleanupStats(TypedDict):
    sold_listings: int
    orphan_raw: int
    old_notifications: int
    orphan_image_files: int
    bytes_freed: int


def _sold_listing_ids(conn, days: int) -> list[int]:
    rows = conn.execute(
        "SELECT id FROM listings WHERE probably_sold = 1 "
        "AND datetime(COALESCE(last_seen_at, crawled_at)) < datetime('now', ?)",
        (f"-{days} days",),
    ).fetchall()
    return [r["id"] for r in rows]


def _orphan_raw_ids(conn, days: int) -> list[int]:
    rows = conn.execute(
        "SELECT r.id FROM raw_listings r "
        "LEFT JOIN listings l ON l.raw_id = r.id "
        "WHERE l.id IS NULL "
        "AND datetime(r.crawled_at) < datetime('now', ?)",
        (f"-{days} days",),
    ).fetchall()
    return [r["id"] for r in rows]


def _old_notification_count(conn, days: int) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM notification_log "
        "WHERE datetime(sent_at) < datetime('now', ?)",
        (f"-{days} days",),
    ).fetchone()
    return int(row["n"])


def _scan_orphan_images(conn) -> list[Path]:
    if not IMAGES_DIR.exists():
        return []
    rows = conn.execute(
        "SELECT local_path FROM listing_images "
        "WHERE local_path IS NOT NULL AND local_path != 'NOT_FOUND'"
    ).fetchall()
    known = {Path(r["local_path"]).name for r in rows if r["local_path"]}
    return [p for p in IMAGES_DIR.iterdir() if p.is_file() and p.name not in known]


def _vacuum() -> None:
    # VACUUM cannot run inside a transaction. Open a dedicated autocommit
    # connection so the per-thread cached one (which always starts an
    # implicit transaction on first execute) doesn't block it.
    conn = sqlite3.connect(str(DB_PATH), isolation_level=None, timeout=30)
    try:
        conn.execute("VACUUM")
    finally:
        conn.close()


def run_cleanup(
    apply: bool = False,
    sold_days: int = DEFAULT_SOLD_DAYS,
    raw_days: int = DEFAULT_RAW_DAYS,
    notif_days: int = DEFAULT_NOTIF_DAYS,
    vacuum: bool = True,
) -> CleanupStats:
    with get_conn() as conn:
        sold_ids = _sold_listing_ids(conn, sold_days)
        raw_ids = _orphan_raw_ids(conn, raw_days)
        n_notif = _old_notification_count(conn, notif_days)
        orphan_files = _scan_orphan_images(conn)
        bytes_freed = sum(p.stat().st_size for p in orphan_files)

        stats: CleanupStats = {
            "sold_listings": len(sold_ids),
            "orphan_raw": len(raw_ids),
            "old_notifications": n_notif,
            "orphan_image_files": len(orphan_files),
            "bytes_freed": bytes_freed,
        }

        if not apply:
            logger.info(f"[db-cleanup DRY RUN] {stats}")
            return stats

        if sold_ids:
            conn.executemany(
                "DELETE FROM listings WHERE id = ?",
                [(i,) for i in sold_ids],
            )
        if raw_ids:
            conn.executemany(
                "DELETE FROM raw_listings WHERE id = ?",
                [(i,) for i in raw_ids],
            )
        if n_notif:
            conn.execute(
                "DELETE FROM notification_log "
                "WHERE datetime(sent_at) < datetime('now', ?)",
                (f"-{notif_days} days",),
            )
        for p in orphan_files:
            try:
                p.unlink()
            except OSError as e:
                logger.warning(f"[db-cleanup] unlink failed {p}: {e}")

    if vacuum:
        _vacuum()
    logger.info(f"[db-cleanup APPLIED] {stats}")
    return stats
