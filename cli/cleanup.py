"""DB cleanup: prune stale rows + orphan image files.

Dry-run by default — call with apply=True to actually delete. FK cascade
in the schema removes listing_images / price_history / valuation_results
when a listings row is deleted (see db/schema.py ON DELETE CASCADE).
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TypedDict

from db.connection import connect, get_conn

logger = logging.getLogger(__name__)

DEFAULT_SOLD_DAYS = 90
DEFAULT_RAW_DAYS = 60
DEFAULT_NOTIF_DAYS = 180

IMAGES_DIR = Path(__file__).parent.parent / "data" / "images"


class CleanupStats(TypedDict):
    sold_listings: int
    unpriceable_listings: int
    unpriceable_raw: int
    orphan_raw: int
    old_notifications: int
    orphan_image_files: int
    bytes_freed: int


def _prefix_param(prefix: str | None) -> str | None:
    return f"{prefix}%" if prefix else None


def _sold_listing_ids(conn, days: int, listing_url_prefix: str | None = None) -> list[int]:
    where = [
        "probably_sold = 1",
        "datetime(COALESCE(last_seen_at, crawled_at)) < datetime('now', ?)",
    ]
    params = [f"-{days} days"]
    if listing_url_prefix:
        where.append("url LIKE ?")
        params.append(_prefix_param(listing_url_prefix))
    rows = conn.execute(
        f"SELECT id FROM listings WHERE {' AND '.join(where)}",
        params,
    ).fetchall()
    return [r["id"] for r in rows]


def _orphan_raw_ids(conn, days: int, raw_url_prefix: str | None = None) -> list[int]:
    where = [
        "l.id IS NULL",
        "datetime(r.crawled_at) < datetime('now', ?)",
    ]
    params = [f"-{days} days"]
    if raw_url_prefix:
        where.append("r.url LIKE ?")
        params.append(_prefix_param(raw_url_prefix))
    rows = conn.execute(
        "SELECT r.id FROM raw_listings r "
        "LEFT JOIN listings l ON l.raw_id = r.id "
        f"WHERE {' AND '.join(where)}",
        params,
    ).fetchall()
    return [r["id"] for r in rows]


def _unpriceable_listing_rows(conn, listing_url_prefix: str | None = None) -> list[dict]:
    where = ["(price_ty IS NULL OR price_ty <= 0 OR area_m2 IS NULL OR area_m2 <= 0)"]
    params = []
    if listing_url_prefix:
        where.append("url LIKE ?")
        params.append(_prefix_param(listing_url_prefix))
    rows = conn.execute(
        f"""
        SELECT id, raw_id
          FROM listings
         WHERE {" AND ".join(where)}
        """,
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def _old_notification_filter(
    days: int,
    listing_url_prefix: str | None = None,
    user_identifier_prefix: str | None = None,
) -> tuple[str, list[str]]:
    joins = []
    where = ["datetime(n.sent_at) < datetime('now', ?)"]
    params = [f"-{days} days"]
    if listing_url_prefix:
        joins.append("JOIN listings l ON l.id = n.listing_id")
        where.append("l.url LIKE ?")
        params.append(_prefix_param(listing_url_prefix))
    if user_identifier_prefix:
        joins.append("JOIN users u ON u.id = n.user_id")
        where.append("u.identifier LIKE ?")
        params.append(_prefix_param(user_identifier_prefix))
    sql = f"FROM notification_log n {' '.join(joins)} WHERE {' AND '.join(where)}"
    return sql, params


def _old_notification_count(
    conn,
    days: int,
    listing_url_prefix: str | None = None,
    user_identifier_prefix: str | None = None,
) -> int:
    filter_sql, params = _old_notification_filter(days, listing_url_prefix, user_identifier_prefix)
    row = conn.execute(
        f"SELECT COUNT(*) AS n {filter_sql}",
        params,
    ).fetchone()
    return int(row["n"])


def _delete_old_notifications(
    conn,
    days: int,
    listing_url_prefix: str | None = None,
    user_identifier_prefix: str | None = None,
) -> None:
    filter_sql, params = _old_notification_filter(days, listing_url_prefix, user_identifier_prefix)
    conn.execute(
        f"DELETE FROM notification_log WHERE id IN (SELECT n.id {filter_sql})",
        params,
    )


def _scan_orphan_images(conn, listing_url_prefix: str | None = None) -> list[Path]:
    if not IMAGES_DIR.exists():
        return []
    if listing_url_prefix:
        rows = conn.execute(
            """
            SELECT li.local_path
              FROM listing_images li
              JOIN listings l ON l.id = li.listing_id
             WHERE li.local_path IS NOT NULL
               AND li.local_path != 'NOT_FOUND'
               AND l.url LIKE ?
            """,
            (_prefix_param(listing_url_prefix),),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT local_path FROM listing_images "
            "WHERE local_path IS NOT NULL AND local_path != 'NOT_FOUND'"
        ).fetchall()
    known = {Path(r["local_path"]).name for r in rows if r["local_path"]}
    return [p for p in IMAGES_DIR.iterdir() if p.is_file() and p.name not in known]


def _vacuum() -> None:
    # PostgreSQL has autovacuum; this manual pass is a best-effort maintenance
    # command for explicit cleanup runs.
    conn = connect()
    try:
        conn._raw.autocommit = True
        conn.execute("VACUUM ANALYZE")
    finally:
        conn.close()


def run_cleanup(
    apply: bool = False,
    sold_days: int = DEFAULT_SOLD_DAYS,
    raw_days: int = DEFAULT_RAW_DAYS,
    notif_days: int = DEFAULT_NOTIF_DAYS,
    vacuum: bool = True,
    listing_url_prefix: str | None = None,
    raw_url_prefix: str | None = None,
    user_identifier_prefix: str | None = None,
) -> CleanupStats:
    with get_conn() as conn:
        sold_ids = _sold_listing_ids(conn, sold_days, listing_url_prefix)
        unpriceable_rows = _unpriceable_listing_rows(conn, listing_url_prefix)
        unpriceable_ids = [int(r["id"]) for r in unpriceable_rows]
        unpriceable_raw_ids = sorted({
            int(r["raw_id"]) for r in unpriceable_rows
            if r.get("raw_id") not in (None, "")
        })
        raw_ids = _orphan_raw_ids(conn, raw_days, raw_url_prefix)
        n_notif = _old_notification_count(
            conn,
            notif_days,
            listing_url_prefix=listing_url_prefix,
            user_identifier_prefix=user_identifier_prefix,
        )
        orphan_files = _scan_orphan_images(conn, listing_url_prefix)
        bytes_freed = sum(p.stat().st_size for p in orphan_files)

        stats: CleanupStats = {
            "sold_listings": len(sold_ids),
            "unpriceable_listings": len(unpriceable_ids),
            "unpriceable_raw": len(unpriceable_raw_ids),
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
        if unpriceable_ids:
            conn.executemany(
                "DELETE FROM listings WHERE id = ?",
                [(i,) for i in unpriceable_ids],
            )
        if unpriceable_raw_ids:
            conn.executemany(
                """
                DELETE FROM raw_listings r
                 WHERE r.id = ?
                   AND NOT EXISTS (
                        SELECT 1 FROM listings l WHERE l.raw_id = r.id
                   )
                """,
                [(i,) for i in unpriceable_raw_ids],
            )
        if raw_ids:
            conn.executemany(
                "DELETE FROM raw_listings WHERE id = ?",
                [(i,) for i in raw_ids],
            )
        if n_notif:
            _delete_old_notifications(
                conn,
                notif_days,
                listing_url_prefix=listing_url_prefix,
                user_identifier_prefix=user_identifier_prefix,
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
