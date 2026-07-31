"""
Signal Lifecycle Tracking — Feedback loop từ thị trường thực.

Logic giá trị:
  - Signal bị xóa nhanh (<72h) = deal đã khớp → proof-of-signal
  - Signal sống dai (>14 ngày) = tin ảo/giá lỗi/seller không reply → noise
  - Segment "hot" (nhiều fast-delisted) → thị trường đang sôi → alert kế tiếp nên đẩy mạnh

Scalable:
  - mark_seen() được gọi SAU MỖI crawl → không phụ thuộc pipeline cụ thể
  - sweep_delisted() idempotent → chạy CLI hoặc cron tùy ý
  - segment_velocity() trả dict → feed vào ValuationEngine hoặc dashboard dễ dàng
"""
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Literal

logger = logging.getLogger(__name__)

# Listing không được thấy lại trong X giờ → mark delisted
STALE_HOURS_BEFORE_DELIST = 48
# Biến mất trước Y giờ từ lúc đăng → "likely sold" (market-validated signal)
FAST_DELIST_HOURS         = 72
# Lookback mặc định cho segment velocity
VELOCITY_WINDOW_DAYS      = 30


@dataclass(frozen=True)
class SourceCheckResult:
    listing_id: int
    outcome: Literal["active", "removed", "unreachable"]
    source_status: Literal["unknown", "active", "inactive", "unreachable"]
    consecutive_missing: int
    became_inactive: bool


def _event_time(value: datetime | None) -> datetime:
    return value or datetime.now().astimezone()


def mark_source_seen(
    conn: Any,
    source: str,
    urls: Iterable[str],
    seen_at: datetime | None = None,
) -> int:
    """Mark discovered source URLs active without changing their first sighting."""
    unique_urls = list(dict.fromkeys(url for url in urls if url))
    if not unique_urls:
        return 0
    timestamp = _event_time(seen_at).isoformat()
    touched = 0
    for offset in range(0, len(unique_urls), 500):
        chunk = unique_urls[offset:offset + 500]
        placeholders = ",".join("?" * len(chunk))
        cur = conn.execute(
            f"""
            UPDATE listings
            SET last_seen_at=CAST(? AS TEXT),
                first_seen_at=COALESCE(first_seen_at, CAST(? AS TEXT)),
                source_status='active',
                source_status_reason='seen_in_results',
                last_source_check_at=?,
                consecutive_missing=0,
                is_active=1,
                probably_sold=0,
                sold_at=NULL,
                delisted_at=NULL
            WHERE source=? AND url IN ({placeholders})
            """,
            (timestamp, timestamp, timestamp, source, *chunk),
        )
        touched += cur.rowcount or 0
    return touched


def record_source_check(
    conn: Any,
    listing_id: int,
    outcome: Literal["active", "removed", "unreachable"],
    reason: str,
    checked_at: datetime | None = None,
) -> SourceCheckResult:
    """Apply one explicit source check using a two-removal inactive threshold."""
    if outcome not in {"active", "removed", "unreachable"}:
        raise ValueError(f"Unsupported source check outcome: {outcome}")

    row = conn.execute(
        """
        SELECT id, COALESCE(consecutive_missing, 0) AS consecutive_missing,
               COALESCE(source_status, 'unknown') AS source_status
        FROM listings
        WHERE id=?
        FOR UPDATE
        """,
        (int(listing_id),),
    ).fetchone()
    if not row:
        raise LookupError(f"Listing {listing_id} does not exist")

    timestamp = _event_time(checked_at).isoformat()
    bounded_reason = str(reason or "")[:200]
    previous_status = row["source_status"]
    if outcome == "removed":
        consecutive_missing = int(row["consecutive_missing"] or 0) + 1
        source_status = "inactive" if consecutive_missing >= 2 else "unknown"
    elif outcome == "unreachable":
        consecutive_missing = 0
        source_status = "unreachable"
    else:
        consecutive_missing = 0
        source_status = "active"

    became_inactive = source_status == "inactive" and previous_status != "inactive"
    is_visible = source_status != "inactive"
    conn.execute(
        """
        UPDATE listings
        SET source_status=?,
            source_status_reason=?,
            last_source_check_at=?,
            consecutive_missing=?,
            is_active=?,
            probably_sold=?,
            delisted_at=CASE
                WHEN ?='inactive' THEN COALESCE(delisted_at, CAST(? AS TEXT))
                ELSE NULL
            END,
            sold_at=CASE
                WHEN ?='inactive' THEN COALESCE(sold_at, CAST(? AS TEXT))
                ELSE NULL
            END,
            last_seen_at=CASE
                WHEN ?='active' THEN CAST(? AS TEXT)
                ELSE last_seen_at
            END
        WHERE id=?
        """,
        (
            source_status,
            bounded_reason,
            timestamp,
            consecutive_missing,
            1 if is_visible else 0,
            0 if is_visible else 1,
            source_status,
            timestamp,
            source_status,
            timestamp,
            source_status,
            timestamp,
            int(listing_id),
        ),
    )
    return SourceCheckResult(
        listing_id=int(listing_id),
        outcome=outcome,
        source_status=source_status,
        consecutive_missing=consecutive_missing,
        became_inactive=became_inactive,
    )


def mark_seen(conn: Any, urls: Iterable[str]) -> int:
    """
    Gọi ngay sau mỗi crawl run — update last_seen_at cho các URL vừa crawl.
    Auto-reactivate nếu listing từng bị delisted nhưng xuất hiện lại (seller repost).
    """
    urls = [u for u in urls if u]
    if not urls:
        return 0
    now = datetime.now().isoformat(timespec='seconds')

    # Chunk keeps updates reasonably small for DB parameter/lock pressure.
    touched = 0
    for i in range(0, len(urls), 500):
        chunk = urls[i:i + 500]
        ph    = ",".join("?" * len(chunk))
        cur   = conn.execute(f"""
            UPDATE listings
               SET last_seen_at  = ?,
                   first_seen_at = COALESCE(first_seen_at, ?),
                   is_active     = 1,
                   delisted_at   = NULL
             WHERE url IN ({ph})
        """, (now, now, *chunk))
        touched += cur.rowcount or 0
    logger.info(f"lifecycle.mark_seen: {touched} listings updated last_seen")
    return touched


def sweep_delisted(conn: Any,
                   stale_hours: int = STALE_HOURS_BEFORE_DELIST) -> List[Dict]:
    """
    Finalize lifecycle metrics only after explicit source evidence marked inactive.

    ``stale_hours`` remains accepted for compatibility but elapsed time alone
    never changes source or visibility state.
    """
    rows = conn.execute("""
        SELECT id, url, title, area, ward, property_type,
               price_ty, area_m2, price_per_m2,
               first_seen_at, last_seen_at, last_source_check_at,
               delisted_at, lifecycle_hours
          FROM listings
         WHERE source_status = 'inactive'
           AND (lifecycle_hours IS NULL OR delisted_at IS NULL)
    """).fetchall()

    delisted: List[Dict] = []
    for r in rows:
        first = r["first_seen_at"] or r["last_seen_at"]
        last = r["last_source_check_at"] or r["last_seen_at"] or first
        try:
            first_dt = datetime.fromisoformat(first) if isinstance(first, str) else first
            last_dt = datetime.fromisoformat(last) if isinstance(last, str) else last
            hours_alive = (last_dt - first_dt).total_seconds() / 3600
        except Exception:
            hours_alive = 0.0

        conn.execute("""
            UPDATE listings
               SET delisted_at     = COALESCE(delisted_at, CAST(? AS TEXT)),
                   lifecycle_hours = ?
             WHERE id = ?
        """, (_event_time(None).isoformat(), int(hours_alive), r["id"]))

        d = dict(r)
        d["hours_alive"] = round(hours_alive, 1)
        d["likely_sold"] = hours_alive < FAST_DELIST_HOURS  # proof-of-market
        delisted.append(d)

    fast = sum(1 for d in delisted if d["likely_sold"])
    if delisted:
        logger.info(f"lifecycle.sweep: {len(delisted)} delisted ({fast} likely sold)")
    return delisted


def get_delisted_signals(conn: Any, hours: int = 72) -> List[Dict]:
    """
    Signal đã là MOS signal + vừa bị delisted < `hours` → alert thứ cấp giá trị cao.
    "Signal này vừa biến mất sau Xh → khả năng cao đã giao dịch, cùng khu còn N signal".
    """
    cutoff = (datetime.now() - timedelta(hours=hours)).isoformat(timespec='seconds')
    rows = conn.execute("""
        SELECT l.id, l.url, l.title, l.area, l.ward, l.property_type,
               l.price_ty, l.price_per_m2, l.area_m2,
               l.first_seen_at, l.delisted_at, l.lifecycle_hours,
               v.mos_pct, v.fair_ppm2, v.signal_score
          FROM listings l
          JOIN valuation_results v ON v.listing_id = l.id
         WHERE l.is_active   = 0
           AND l.delisted_at >= ?
           AND v.is_signal   = 1
         ORDER BY l.lifecycle_hours ASC
    """, (cutoff,)).fetchall()
    return [dict(r) for r in rows]


def segment_velocity(conn: Any,
                     days: int = VELOCITY_WINDOW_DAYS) -> List[Dict]:
    """
    Tốc độ 'burn' signal theo (area, property_type) trong N ngày gần nhất.
    fast_sold_ratio cao → thị trường sôi động → signal mới cần ưu tiên alert.
    """
    cutoff = (datetime.now() - timedelta(days=days)).isoformat(timespec='seconds')
    rows = conn.execute("""
        SELECT area,
               property_type,
               COUNT(*)                                              AS n_delisted,
               AVG(lifecycle_hours) / 24.0                           AS avg_days_alive,
               SUM(CASE WHEN lifecycle_hours < ? THEN 1 ELSE 0 END)  AS fast_sold
          FROM listings
         WHERE is_active   = 0
           AND delisted_at >= ?
         GROUP BY area, property_type
    """, (FAST_DELIST_HOURS, cutoff)).fetchall()

    result = []
    for r in rows:
        d = dict(r)
        n = d.get("n_delisted") or 0
        d["fast_sold_ratio"] = round((d.get("fast_sold") or 0) / n, 3) if n else 0.0
        # Hot score: 0-1, dùng để boost alert priority ở segment này
        d["hot_score"] = round(min(1.0, d["fast_sold_ratio"] * (n / 10)), 3)
        result.append(d)
    return result


def backfill_first_seen(conn: Any) -> int:
    """
    One-shot: populate first_seen_at từ crawled_at cho DB cũ (migration giá trị cao).
    Idempotent — chỉ update khi NULL.
    """
    cur = conn.execute("""
        UPDATE listings
           SET first_seen_at = COALESCE(first_seen_at, crawled_at),
               last_seen_at  = COALESCE(last_seen_at,  crawled_at)
         WHERE first_seen_at IS NULL OR last_seen_at IS NULL
    """)
    n = cur.rowcount or 0
    if n:
        logger.info(f"lifecycle.backfill: {n} listings initialized first/last_seen_at")
    return n
