"""Raw listing repository helpers."""
from dataclasses import dataclass
import hashlib
import json
from typing import Any, Literal, Mapping, Optional

from db.connection import get_conn

# ─── RAW layer ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RawInsertResult:
    status: Literal["inserted", "duplicate"]
    raw_id: int | None


def canonical_raw_json(raw_data: Mapping[str, Any]) -> tuple[str, str]:
    """Return deterministic JSON plus its SHA-256 content identity."""
    payload = json.dumps(
        dict(raw_data),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return payload, digest


def _parse_raw_json(value: object) -> dict:
    if isinstance(value, Mapping):
        return dict(value)
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _changed_fields(previous: Mapping[str, Any], current: Mapping[str, Any]) -> list[str]:
    missing = object()
    keys = set(previous) | set(current)
    return sorted(
        key
        for key in keys
        if previous.get(key, missing) != current.get(key, missing)
    )


def _append_raw_revision(
    conn,
    row: Mapping[str, Any],
    raw_data: Mapping[str, Any],
    *,
    change_kind: str,
    crawl_run_id: Optional[int],
    changed_fields: list[str],
) -> None:
    payload, digest = canonical_raw_json(raw_data)
    latest = conn.execute(
        """
        SELECT revision_no
        FROM raw_listing_revisions
        WHERE raw_listing_id=?
        ORDER BY revision_no DESC
        LIMIT 1
        """,
        (int(row["id"]),),
    ).fetchone()
    revision_no = int(latest["revision_no"] or 0) + 1 if latest else 1
    conn.execute(
        """
        INSERT INTO raw_listing_revisions (
            raw_listing_id, revision_no, source, source_id, url,
            raw_json, content_hash, changed_fields, change_kind, crawl_run_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            int(row["id"]),
            revision_no,
            str(row["source"]),
            row["source_id"],
            str(row["url"]),
            payload,
            digest,
            json.dumps(changed_fields, ensure_ascii=False),
            change_kind,
            crawl_run_id,
        ),
    )


def _seed_legacy_revision(conn, row: Mapping[str, Any]) -> None:
    existing = conn.execute(
        """
        SELECT revision_no
        FROM raw_listing_revisions
        WHERE raw_listing_id=?
        ORDER BY revision_no DESC
        LIMIT 1
        """,
        (int(row["id"]),),
    ).fetchone()
    if existing:
        return
    _append_raw_revision(
        conn,
        row,
        _parse_raw_json(row["raw_json"]),
        change_kind="legacy_seed",
        crawl_run_id=row["crawl_run_id"],
        changed_fields=[],
    )


def _update_raw_listing_payload(
    conn,
    raw_id: int,
    raw_data: Mapping[str, Any],
    *,
    change_kind: str,
    crawl_run_id: Optional[int],
) -> bool:
    row = conn.execute(
        """
        SELECT id, source, source_id, url, raw_json, crawl_run_id
        FROM raw_listings
        WHERE id=?
        FOR UPDATE
        """,
        (int(raw_id),),
    ).fetchone()
    if not row:
        raise LookupError(f"Raw listing not found: {raw_id}")

    _seed_legacy_revision(conn, row)
    previous = _parse_raw_json(row["raw_json"])
    _, previous_hash = canonical_raw_json(previous)
    _, current_hash = canonical_raw_json(raw_data)
    if previous_hash == current_hash:
        return False

    effective_run_id = crawl_run_id if crawl_run_id is not None else row["crawl_run_id"]
    _append_raw_revision(
        conn,
        row,
        raw_data,
        change_kind=change_kind,
        crawl_run_id=effective_run_id,
        changed_fields=_changed_fields(previous, raw_data),
    )
    conn.execute(
        """
        UPDATE raw_listings
        SET raw_json=?,
            crawled_at=datetime('now'),
            crawl_run_id=?
        WHERE id=?
        """,
        (
            json.dumps(dict(raw_data), ensure_ascii=False),
            effective_run_id,
            int(raw_id),
        ),
    )
    return True


def update_raw_listing_payload(
    raw_id: int,
    raw_data: Mapping[str, Any],
    *,
    change_kind: str,
    crawl_run_id: Optional[int] = None,
    conn=None,
) -> bool:
    """Persist one distinct state and append its ordered raw revision."""
    if conn is not None:
        return _update_raw_listing_payload(
            conn,
            raw_id,
            raw_data,
            change_kind=change_kind,
            crawl_run_id=crawl_run_id,
        )
    with get_conn() as managed_conn:
        return _update_raw_listing_payload(
            managed_conn,
            raw_id,
            raw_data,
            change_kind=change_kind,
            crawl_run_id=crawl_run_id,
        )


def get_raw_listing_revisions(raw_id: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT revision_no, source, source_id, url, raw_json,
                   content_hash, changed_fields, change_kind,
                   crawl_run_id, observed_at
            FROM raw_listing_revisions
            WHERE raw_listing_id=?
            ORDER BY revision_no
            """,
            (int(raw_id),),
        ).fetchall()
    revisions: list[dict] = []
    for source_row in rows:
        row = dict(source_row.items())
        row["raw_json"] = _parse_raw_json(row.get("raw_json"))
        changed = row.get("changed_fields")
        if isinstance(changed, str):
            try:
                changed = json.loads(changed)
            except (TypeError, ValueError, json.JSONDecodeError):
                changed = []
        row["changed_fields"] = list(changed or [])
        revisions.append(row)
    return revisions


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
            _append_raw_revision(
                conn,
                {
                    "id": int(cur.lastrowid),
                    "source": source,
                    "source_id": source_id,
                    "url": url,
                },
                raw_data,
                change_kind="initial",
                crawl_run_id=crawl_run_id,
                changed_fields=[],
            )
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
    *,
    change_kind: str = "source_refresh",
) -> int:
    """Refresh one existing source identity without inserting a second row."""
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT id
            FROM raw_listings
            WHERE source=? AND url=?
            """,
            (source, url),
        ).fetchone()
        if not row:
            raise LookupError(f"Raw listing not found for {source}: {url}")
        raw_id = int(row["id"])
        _update_raw_listing_payload(
            conn,
            raw_id,
            raw_data,
            change_kind=change_kind,
            crawl_run_id=crawl_run_id,
        )
        return raw_id


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


