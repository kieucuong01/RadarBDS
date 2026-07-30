"""Raw listing repository helpers."""
from dataclasses import dataclass
import json
from typing import Literal, Optional

from db.connection import get_conn

# ─── RAW layer ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RawInsertResult:
    status: Literal["inserted", "duplicate"]
    raw_id: int | None

def get_raw_urls(source: str) -> set:
    """Lấy set URL đã có trong raw_listings — dùng để skip khi crawl lại."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT url FROM raw_listings WHERE source = ?", (source,)
        ).fetchall()
    return {r[0] for r in rows}


def insert_raw_result(
    source: str,
    source_id: Optional[str],
    url: str,
    raw_data: dict,
    crawl_run_id: Optional[int] = None,
) -> RawInsertResult:
    """Insert one raw record and distinguish conflicts from write failures."""
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO raw_listings
                (source, source_id, url, raw_json, crawl_run_id)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(source, url) DO NOTHING
            """,
            (
                source,
                source_id,
                url,
                json.dumps(raw_data, ensure_ascii=False),
                crawl_run_id,
            ),
        )
        if cur.lastrowid:
            return RawInsertResult("inserted", cur.lastrowid)
        return RawInsertResult("duplicate", None)


def insert_raw(source: str, source_id: Optional[str], url: str,
               raw_data: dict, crawl_run_id: Optional[int] = None) -> Optional[int]:
    """
    Lưu raw record. UNIQUE(source, url) → bỏ qua nếu đã có.
    Trả về raw_id hoặc None nếu đã tồn tại.
    """
    return insert_raw_result(
        source,
        source_id,
        url,
        raw_data,
        crawl_run_id,
    ).raw_id


def refresh_raw_listing(
    source: str,
    url: str,
    raw_data: dict,
    crawl_run_id: Optional[int] = None,
) -> int:
    """Refresh one existing source identity without inserting a second row."""
    with get_conn() as conn:
        cur = conn.execute(
            """
            UPDATE raw_listings
            SET raw_json=?,
                crawled_at=datetime('now'),
                crawl_run_id=?
            WHERE source=? AND url=?
            RETURNING id
            """,
            (
                json.dumps(raw_data, ensure_ascii=False),
                crawl_run_id,
                source,
                url,
            ),
        )
        if not cur.lastrowid:
            raise LookupError(f"Raw listing not found for {source}: {url}")
        return int(cur.lastrowid)


def get_raw_for_reprocess(source: Optional[str] = None,
                          since: Optional[str] = None,
                          incremental: bool = False,
                          raw_ids: Optional[list] = None) -> list:
    """
    Lấy raw records để reprocess.
    source: filter theo nguồn. since: ISO date string 'YYYY-MM-DD'.
    incremental: Nếu True, chỉ lấy các raw_listings chưa từng được normalize (raw_id chưa có trong bảng listings).
    """
    params = []
    if raw_ids is not None:
        ids = [int(x) for x in raw_ids if x]
        if not ids:
            return []
        placeholders = ",".join(["?"] * len(ids))
        query = f"SELECT id, source, source_id, url, raw_json, crawled_at FROM raw_listings WHERE id IN ({placeholders})"
        params = ids
    elif incremental:
        query = """
            SELECT r.id, r.source, r.source_id, r.url, r.raw_json, r.crawled_at 
            FROM raw_listings r
            LEFT JOIN listings l ON r.id = l.raw_id
            WHERE l.raw_id IS NULL
        """
    else:
        query = "SELECT id, source, source_id, url, raw_json, crawled_at FROM raw_listings WHERE 1=1"
    if source:
        query += " AND r.source = ?" if incremental else " AND source = ?"
        params.append(source)
    if since:
        query += " AND r.crawled_at >= ?" if incremental else " AND crawled_at >= ?"
        params.append(since)
    query += " ORDER BY r.crawled_at ASC" if incremental else " ORDER BY crawled_at ASC"

    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]



# ─── Helpers ──────────────────────────────────────────────────────────────────

def get_existing_source_ids(source: str) -> set:
    """Lấy source_ids đã có trong raw_listings (dùng incremental)."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT source_id FROM raw_listings WHERE source=? AND source_id IS NOT NULL",
            (source,)
        ).fetchall()
    return {r[0] for r in rows}


