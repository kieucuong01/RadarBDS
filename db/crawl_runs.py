"""Crawl run repository helpers."""
from datetime import datetime
from typing import Literal, Mapping, Optional

from db.connection import get_conn
# ─── Crawl runs ───────────────────────────────────────────────────────────────

VALID_CRAWL_STATUSES = {"running", "done", "partial", "error"}


def derive_crawl_status(
    stats: Mapping,
    *,
    fatal: bool = False,
) -> Literal["done", "partial", "error"]:
    if fatal:
        return "error"
    return "partial" if int(stats.get("errors", 0) or 0) > 0 else "done"

def start_crawl_run(source: str, area: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO crawl_runs (source, area) VALUES (?, ?)", (source, area)
        )
        return cur.lastrowid


def finish_crawl_run(run_id: int, stats: dict,
                     status: str = "done", error_msg: str = None) -> None:
    if status not in VALID_CRAWL_STATUSES:
        raise ValueError(f"Invalid crawl status: {status}")
    with get_conn() as conn:
        conn.execute("""
            UPDATE crawl_runs SET
                finished_at     = datetime('now'),
                n_fetched       = :n_fetched,
                n_new           = :n_new,
                n_updated       = :n_updated,
                n_price_dropped = :n_price_dropped,
                n_skipped       = :n_skipped,
                status          = :status,
                error_msg       = :error_msg
            WHERE id = :id
        """, {
            "id":              run_id,
            "n_fetched":       stats.get("fetched", 0),
            "n_new":           stats.get("new", 0),
            "n_updated":       stats.get("updated", 0),
            "n_price_dropped": stats.get("price_dropped", 0),
            "n_skipped":       stats.get("skipped", 0),
            "status":          status,
            "error_msg":       error_msg,
        })


# ─── Crawl progress checkpointing ────────────────────────────────────────────

def get_incomplete_run(source: str) -> Optional[dict]:
    """Find the most recent incomplete run for a source (status='running')."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, started_at FROM crawl_runs WHERE source=? AND status='running' ORDER BY id DESC LIMIT 1",
            (source,),
        ).fetchone()
        if not row:
            return None
        completed = {
            r["target_url"]
            for r in conn.execute(
                "SELECT target_url FROM crawl_run_progress WHERE run_id=? AND status='done'",
                (row["id"],),
            ).fetchall()
        }
        return {"run_id": row["id"], "started_at": row["started_at"], "completed_urls": completed}


def mark_url_done(run_id: int, target_url: str, n_new: int) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO crawl_run_progress (run_id, target_url, status, n_new, completed_at)
               VALUES (?, ?, 'done', ?, datetime('now'))
               ON CONFLICT(run_id, target_url) DO UPDATE SET status='done', n_new=?, completed_at=datetime('now')""",
            (run_id, target_url, n_new, n_new),
        )


def mark_url_error(run_id: int, target_url: str, error_msg: str) -> None:
    bounded_error = str(error_msg or "")[:500]
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO crawl_run_progress
                (run_id, target_url, status, n_new, error_msg, completed_at)
            VALUES (?, ?, 'error', 0, ?, datetime('now'))
            ON CONFLICT(run_id, target_url) DO UPDATE SET
                status='error',
                n_new=0,
                error_msg=?,
                completed_at=datetime('now')
            """,
            (run_id, target_url, bounded_error, bounded_error),
        )


def load_recent_crawl_runs(conn, limit: int) -> list[dict]:
    rows = conn.execute(
        """
        SELECT id, source, area, started_at, finished_at, status,
               n_new, n_skipped, n_fetched, error_msg
        FROM crawl_runs
        ORDER BY id DESC
        LIMIT ?
        """,
        (max(1, int(limit)),),
    ).fetchall()
    return [dict(row) for row in rows]


def summarize_recent_crawl_runs(conn, days: int = 7) -> list[dict]:
    rows = conn.execute(
        """
        SELECT source,
               COUNT(*) AS runs,
               SUM(COALESCE(n_new, 0)) AS total_new,
               SUM(CASE WHEN status='partial' THEN 1 ELSE 0 END) AS partial_runs,
               SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) AS error_runs,
               SUM(
                   CASE
                       WHEN status IN ('partial', 'error')
                            OR COALESCE(error_msg, '') <> ''
                       THEN 1 ELSE 0
                   END
               ) AS runs_with_errors
        FROM crawl_runs
        WHERE NULLIF(started_at, '')::timestamptz
              >= CURRENT_TIMESTAMP - (? * INTERVAL '1 day')
        GROUP BY source
        ORDER BY source
        """,
        (max(1, int(days)),),
    ).fetchall()
    return [dict(row) for row in rows]


def mark_missing_listings(source: str, seen_urls: set) -> int:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, url, consecutive_missing FROM listings WHERE source=? AND probably_sold=0",
            (source,)
        ).fetchall()
        sold_count = 0
        for row in rows:
            if row["url"] not in seen_urls:
                n = row["consecutive_missing"] + 1
                sold = 1 if n >= 3 else 0
                sold_at = datetime.now().isoformat() if sold and n == 3 else None
                if sold:
                    sold_count += 1
                conn.execute(
                    "UPDATE listings SET consecutive_missing=?, probably_sold=?, sold_at=COALESCE(sold_at,?) WHERE id=?",
                    (n, sold, sold_at, row["id"])
                )
    return sold_count



