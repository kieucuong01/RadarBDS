"""
Market Trend Analytics
- detect_price_drops(): kiểm tra và cập nhật flag price_dropped cho tất cả listings
- compute_weekly_trend(): tính median/avg ppm2 theo tuần → market_weekly table
- get_trend_chart_data(): lấy data để vẽ line chart trên dashboard
"""
import logging
import sqlite3
import statistics
from datetime import datetime, timedelta
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


# ─── Price Drop Detection ──────────────────────────────────────────────────────

def detect_price_drops(conn: sqlite3.Connection) -> int:
    """
    So sánh price_ty hiện tại với price_first_ty của mỗi listing.
    Update price_dropped + price_drop_pct.
    Trả về số listing vừa được phát hiện giảm giá.
    """
    rows = conn.execute("""
        SELECT id, price_ty, price_first_ty, price_dropped
        FROM listings
        WHERE price_ty IS NOT NULL
          AND price_first_ty IS NOT NULL
          AND probably_sold = 0
    """).fetchall()

    # BUG FIX: Row object, support cả name-access; không commit tay (context manager lo)
    count = 0
    for row in rows:
        lid             = row["id"]
        current         = row["price_ty"]
        first           = row["price_first_ty"]
        already_dropped = row["price_dropped"]
        if current and first and current < first * 0.99:
            drop_pct = round((first - current) / first * 100, 2)
            conn.execute("""
                UPDATE listings
                SET price_dropped  = 1,
                    price_drop_pct = ?
                WHERE id = ?
            """, (drop_pct, lid))
            if not already_dropped:
                count += 1
                logger.info(f"Price drop detected listing_id={lid}: {first:.2f}→{current:.2f} ty (-{drop_pct}%)")

    if count:
        logger.info(f"detect_price_drops: {count} new price drops found")
    return count


# ─── Weekly Trend ─────────────────────────────────────────────────────────────

def _get_iso_week(dt: datetime) -> str:
    """Trả về string 'YYYY-WNN', VD '2025-W15'."""
    year, week, _ = dt.isocalendar()
    return f"{year}-W{week:02d}"


def compute_weekly_trend(conn: sqlite3.Connection,
                         week: Optional[str] = None) -> List[Dict]:
    """
    Tính median/avg ppm2 cho tuần hiện tại (hoặc tuần chỉ định).
    Ghi vào market_weekly table.
    Trả về list stats vừa ghi.
    """
    if week is None:
        week = _get_iso_week(datetime.now())

    # Lấy listings được crawl trong tuần này
    # Dùng updated_at để track (mỗi lần crawl sẽ update)
    week_start = _week_to_date(week)
    week_end   = week_start + timedelta(days=7)

    rows = conn.execute("""
        SELECT area, property_type, price_per_m2
        FROM listings
        WHERE price_per_m2 IS NOT NULL
          AND price_per_m2 > 0
          AND probably_sold = 0
          AND updated_at >= ?
          AND updated_at <  ?
    """, (week_start.isoformat(), week_end.isoformat())).fetchall()

    if not rows:
        # Fallback: lấy tất cả listings active (không chỉ tuần này)
        rows = conn.execute("""
            SELECT area, property_type, price_per_m2
            FROM listings
            WHERE price_per_m2 IS NOT NULL
              AND price_per_m2 > 0
              AND probably_sold = 0
        """).fetchall()

    # Group by (area, property_type)
    groups: Dict[tuple, List[float]] = {}
    for row in rows:
        key = (row[0], row[1])  # (area, property_type)
        groups.setdefault(key, []).append(row[2])

    # Đếm tin mới trong tuần
    new_counts = {}
    new_rows = conn.execute("""
        SELECT area, property_type, COUNT(*) as cnt
        FROM listings
        WHERE crawled_at >= ? AND crawled_at < ?
        GROUP BY area, property_type
    """, (week_start.isoformat(), week_end.isoformat())).fetchall()
    for r in new_rows:
        new_counts[(r[0], r[1])] = r[2]

    # Đếm listings bị drop giá trong tuần
    drop_counts = {}
    drop_rows = conn.execute("""
        SELECT area, property_type, COUNT(*) as cnt
        FROM listings
        WHERE price_dropped = 1
          AND updated_at >= ? AND updated_at < ?
        GROUP BY area, property_type
    """, (week_start.isoformat(), week_end.isoformat())).fetchall()
    for r in drop_rows:
        drop_counts[(r[0], r[1])] = r[2]

    results = []
    for (area, prop_type), prices in groups.items():
        if len(prices) < 2:
            continue

        median_ppm2 = statistics.median(prices)
        avg_ppm2    = statistics.mean(prices)

        stat = {
            "week":          week,
            "area":          area,
            "property_type": prop_type,
            "median_ppm2":   round(median_ppm2, 3),
            "avg_ppm2":      round(avg_ppm2, 3),
            "n_listings":    len(prices),
            "n_new":         new_counts.get((area, prop_type), 0),
            "n_dropped":     drop_counts.get((area, prop_type), 0),
        }

        conn.execute("""
            INSERT INTO market_weekly
                (week, area, property_type, median_ppm2, avg_ppm2, n_listings, n_new, n_dropped)
            VALUES (:week, :area, :property_type, :median_ppm2, :avg_ppm2, :n_listings, :n_new, :n_dropped)
            ON CONFLICT(week, area, property_type) DO UPDATE SET
                median_ppm2 = excluded.median_ppm2,
                avg_ppm2    = excluded.avg_ppm2,
                n_listings  = excluded.n_listings,
                n_new       = excluded.n_new,
                n_dropped   = excluded.n_dropped,
                computed_at = datetime('now')
        """, stat)

        results.append(stat)
        logger.debug(f"  market_weekly [{week}] {area}/{prop_type}: median={median_ppm2:.1f} n={len(prices)}")

    # Không commit tay — get_conn() context manager lo việc này
    logger.info(f"compute_weekly_trend [{week}]: {len(results)} segments updated")
    return results


def _week_to_date(week_str: str) -> datetime:
    """Chuyển 'YYYY-WNN' → datetime đầu tuần (Monday)."""
    year, week_num = week_str.split("-W")
    return datetime.fromisocalendar(int(year), int(week_num), 1)


# ─── Chart data ───────────────────────────────────────────────────────────────

def get_trend_chart_data(conn: sqlite3.Connection,
                         area: str,
                         property_type: str,
                         last_n_weeks: int = 12) -> List[Dict]:
    """
    Lấy dữ liệu line chart xu hướng giá cho dashboard.
    Trả về list [{'week': '2025-W10', 'median_ppm2': 10.5, 'n_listings': 45}, ...]
    """
    rows = conn.execute("""
        SELECT week, median_ppm2, avg_ppm2, n_listings, n_new, n_dropped
        FROM market_weekly
        WHERE area = ? AND property_type = ?
        ORDER BY week DESC
        LIMIT ?
    """, (area, property_type, last_n_weeks)).fetchall()

    return [dict(r) for r in reversed(rows)]


def get_market_summary(conn: sqlite3.Connection) -> List[Dict]:
    """
    Tóm tắt thị trường: mỗi (area, property_type) lấy tuần gần nhất.
    So sánh với tuần trước để tính direction (up/down/flat).
    """
    rows = conn.execute("""
        SELECT w1.area, w1.property_type, w1.week, w1.median_ppm2, w1.n_listings,
               w2.median_ppm2 AS prev_median
        FROM market_weekly w1
        LEFT JOIN market_weekly w2
            ON w1.area = w2.area
            AND w1.property_type = w2.property_type
            AND w2.week < w1.week
        WHERE w1.week = (
            SELECT MAX(week) FROM market_weekly mw
            WHERE mw.area = w1.area AND mw.property_type = w1.property_type
        )
        ORDER BY w1.area, w1.property_type
    """).fetchall()

    result = []
    for row in rows:
        d = dict(row)
        prev = d.get("prev_median")
        curr = d.get("median_ppm2")
        if prev and curr:
            change_pct = round((curr - prev) / prev * 100, 2)
            d["change_pct"] = change_pct
            d["direction"]  = "up" if change_pct > 1 else ("down" if change_pct < -1 else "flat")
        else:
            d["change_pct"] = None
            d["direction"]  = "unknown"
        result.append(d)

def compute_monthly_trend(conn: sqlite3.Connection):
    """
    Tính toán median ppm2 theo tháng cho tất cả dữ liệu lịch sử.
    """
    logger.info("Đang tính toán xu hướng giá theo tháng...")
    rows = conn.execute("""
        SELECT 
            strftime('%Y-%m', COALESCE(posted_at, crawled_at)) as month,
            area,
            property_type,
            price_per_m2
        FROM listings
        WHERE price_per_m2 IS NOT NULL 
          AND COALESCE(posted_at, crawled_at) IS NOT NULL
          AND probably_sold = 0
    """).fetchall()
    
    groups = {}
    for row in rows:
        month, area, ptype, ppm2 = row
        if not month: continue
        key = (month, area, ptype)
        groups.setdefault(key, []).append(ppm2)
        
    for (month, area, ptype), prices in groups.items():
        if len(prices) < 2: continue
        median = statistics.median(prices)
        avg = statistics.mean(prices)
        
        # Tái sử dụng bảng market_weekly nhưng dùng field week để chứa chuỗi 'YYYY-MM'
        month_key = f"M-{month}"
        conn.execute("""
            INSERT INTO market_weekly
                (week, area, property_type, median_ppm2, avg_ppm2, n_listings)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(week, area, property_type) DO UPDATE SET
                median_ppm2 = excluded.median_ppm2,
                avg_ppm2 = excluded.avg_ppm2,
                n_listings = excluded.n_listings
        """, (month_key, area, ptype, round(median, 2), round(avg, 2), len(prices)))
        
    logger.info(f"Đã cập nhật xu hướng tháng cho {len(groups)} phân khúc.")

def compute_daily_trend(conn: sqlite3.Connection):
    """
    Tính toán median ppm2 theo ngày cho tất cả dữ liệu lịch sử.
    """
    logger.info("Đang tính toán xu hướng giá theo ngày...")
    rows = conn.execute("""
        SELECT 
            strftime('%Y-%m-%d', COALESCE(posted_at, crawled_at)) as day,
            area,
            property_type,
            price_per_m2
        FROM listings
        WHERE price_per_m2 IS NOT NULL 
          AND COALESCE(posted_at, crawled_at) IS NOT NULL
          AND probably_sold = 0
    """).fetchall()
    
    groups = {}
    for row in rows:
        day, area, ptype, ppm2 = row
        if not day: continue
        key = (day, area, ptype)
        groups.setdefault(key, []).append(ppm2)
        
    for (day, area, ptype), prices in groups.items():
        if len(prices) < 2: continue
        median = statistics.median(prices)
        avg = statistics.mean(prices)
        
        day_key = f"D-{day}"
        conn.execute("""
            INSERT INTO market_weekly
                (week, area, property_type, median_ppm2, avg_ppm2, n_listings)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(week, area, property_type) DO UPDATE SET
                median_ppm2 = excluded.median_ppm2,
                avg_ppm2 = excluded.avg_ppm2,
                n_listings = excluded.n_listings
        """, (day_key, area, ptype, round(median, 2), round(avg, 2), len(prices)))
        
    logger.info(f"Đã cập nhật xu hướng ngày cho {len(groups)} phân khúc.")

if __name__ == "__main__":
    from config.database_sqlite import get_conn
    with get_conn() as conn:
        compute_monthly_trend(conn)
        compute_daily_trend(conn)
