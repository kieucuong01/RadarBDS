"""Raw listing repository helpers."""
import json
import logging
from typing import Optional

from db.connection import get_conn
from db.moderation import normalize_phone

logger = logging.getLogger(__name__)
# ─── RAW layer ────────────────────────────────────────────────────────────────

def get_raw_urls(source: str) -> set:
    """Lấy set URL đã có trong raw_listings — dùng để skip khi crawl lại."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT url FROM raw_listings WHERE source = ?", (source,)
        ).fetchall()
    return {r[0] for r in rows}


def insert_raw(source: str, source_id: Optional[str], url: str,
               raw_data: dict, crawl_run_id: Optional[int] = None) -> Optional[int]:
    """
    Lưu raw record. UNIQUE(source, url) → bỏ qua nếu đã có.
    Trả về raw_id hoặc None nếu đã tồn tại.
    """
    with get_conn() as conn:
        try:
            phone_norm = normalize_phone(raw_data.get("contact_phone"))
            if phone_norm:
                blocked = conn.execute(
                    "SELECT 1 FROM broker_blacklist WHERE active=1 AND phone_norm=?",
                    (phone_norm,),
                ).fetchone()
                if blocked:
                    return None
            cur = conn.execute(
                """INSERT OR IGNORE INTO raw_listings
                   (source, source_id, url, raw_json, crawl_run_id)
                   VALUES (?, ?, ?, ?, ?)""",
                (source, source_id, url,
                 json.dumps(raw_data, ensure_ascii=False), crawl_run_id)
            )
            return cur.lastrowid if cur.lastrowid else None
        except Exception as e:
            logger.error(f"insert_raw error [{url}]: {e}")
            return None


def get_raw_for_reprocess(source: Optional[str] = None,
                          since: Optional[str] = None,
                          incremental: bool = False) -> list:
    """
    Lấy raw records để reprocess.
    source: filter theo nguồn. since: ISO date string 'YYYY-MM-DD'.
    incremental: Nếu True, chỉ lấy các raw_listings chưa từng được normalize (raw_id chưa có trong bảng listings).
    """
    if incremental:
        query = """
            SELECT r.id, r.source, r.source_id, r.url, r.raw_json, r.crawled_at 
            FROM raw_listings r
            LEFT JOIN listings l ON r.id = l.raw_id
            WHERE l.raw_id IS NULL
        """
    else:
        query = "SELECT id, source, source_id, url, raw_json, crawled_at FROM raw_listings WHERE 1=1"
        
    params = []
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


