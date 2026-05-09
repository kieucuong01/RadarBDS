"""Crawl run repository helpers."""
from datetime import datetime

from db.connection import get_conn
# ─── Crawl runs ───────────────────────────────────────────────────────────────

def start_crawl_run(source: str, area: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO crawl_runs (source, area) VALUES (?, ?)", (source, area)
        )
        return cur.lastrowid


def finish_crawl_run(run_id: int, stats: dict,
                     status: str = "done", error_msg: str = None) -> None:
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



