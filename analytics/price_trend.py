"""
Price Trend Tracker (Tầng 3c)

Phân tích lịch sử giá từ price_history table.
Chưa có multi-crawl data → cấu trúc sẵn, dùng ngay khi crawl thêm.

Functions:
    get_price_history(listing_id)     → list lịch sử giá
    get_price_trend_summary(listing_id) → dict tóm tắt xu hướng
    get_most_dropped_listings(n)      → top N tin giảm giá nhiều nhất
"""

import logging
from typing import List, Dict, Optional

from db.connection import get_conn

logger = logging.getLogger(__name__)


def get_price_history(listing_id: int) -> List[Dict]:
    """
    Trả về lịch sử giá của một listing, sắp xếp từ cũ đến mới.
    Mỗi entry: {price_ty, price_per_m2, recorded_at, crawl_run_id}
    """
    try:
        with get_conn() as conn:
            rows = conn.execute("""
                SELECT price_ty, price_per_m2, recorded_at, crawl_run_id
                FROM price_history
                WHERE listing_id = ?
                ORDER BY recorded_at ASC
            """, (listing_id,)).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"get_price_history error listing_id={listing_id}: {e}")
        return []


def get_price_trend_summary(listing_id: int) -> Dict:
    """
    Tóm tắt xu hướng giá cho một listing.

    Returns dict:
        n_records       : số điểm dữ liệu
        first_price_ty  : giá đầu tiên (tỷ)
        latest_price_ty : giá mới nhất (tỷ)
        total_drop_pct  : % giảm từ đầu đến cuối (dương = giảm)
        n_drops         : số lần giảm giá
        n_increases     : số lần tăng giá
        days_on_market  : số ngày từ lần đầu đến lần cuối
        trend           : 'falling' | 'stable' | 'rising' | 'single'
    """
    history = get_price_history(listing_id)

    if not history:
        return {"n_records": 0, "trend": "no_data"}

    if len(history) == 1:
        return {
            "n_records": 1,
            "first_price_ty": history[0]["price_ty"],
            "latest_price_ty": history[0]["price_ty"],
            "total_drop_pct": 0.0,
            "n_drops": 0,
            "n_increases": 0,
            "days_on_market": 0,
            "trend": "single",
        }

    prices = [h["price_ty"] for h in history if h["price_ty"]]
    if len(prices) < 2:
        return {"n_records": len(history), "trend": "no_data"}

    first_price  = prices[0]
    latest_price = prices[-1]

    # Đếm số lần tăng/giảm
    n_drops     = sum(1 for i in range(1, len(prices)) if prices[i] < prices[i-1])
    n_increases = sum(1 for i in range(1, len(prices)) if prices[i] > prices[i-1])

    # % thay đổi tổng (dương = giảm)
    total_change_pct = 0.0
    if first_price and first_price > 0:
        total_change_pct = round((first_price - latest_price) / first_price * 100, 1)

    # Số ngày trên thị trường
    try:
        from datetime import datetime
        t0 = datetime.fromisoformat(history[0]["recorded_at"][:19])
        t1 = datetime.fromisoformat(history[-1]["recorded_at"][:19])
        days_on_market = (t1 - t0).days
    except Exception:
        days_on_market = 0

    # Xu hướng
    if n_drops > n_increases:
        trend = "falling"
    elif n_increases > n_drops:
        trend = "rising"
    else:
        trend = "stable"

    return {
        "n_records":       len(prices),
        "first_price_ty":  round(first_price, 3),
        "latest_price_ty": round(latest_price, 3),
        "total_drop_pct":  total_change_pct,
        "n_drops":         n_drops,
        "n_increases":     n_increases,
        "days_on_market":  days_on_market,
        "trend":           trend,
    }


def get_most_dropped_listings(n: int = 20) -> List[Dict]:
    """
    Lấy N tin có % giảm giá nhiều nhất từ giá gốc.
    Chỉ tính listing có ít nhất 2 điểm dữ liệu.

    Returns list of dict: {listing_id, title, url, first_price_ty, latest_price_ty,
                           drop_pct, n_drops, days_on_market}
    """
    try:
        with get_conn() as conn:
            rows = conn.execute("""
                SELECT
                    ph.listing_id,
                    l.title,
                    l.url,
                    l.price_ty        AS current_price_ty,
                    l.price_first_ty  AS first_price_ty,
                    l.price_dropped,
                    ROUND(((l.price_first_ty - l.price_ty) / l.price_first_ty * 100)::numeric, 1) AS drop_pct,
                    COUNT(ph.id)      AS n_snapshots
                FROM listings l
                JOIN price_history ph ON ph.listing_id = l.id
                WHERE l.price_first_ty IS NOT NULL
                  AND l.price_first_ty > 0
                  AND l.price_ty < l.price_first_ty
                GROUP BY ph.listing_id, l.id
                HAVING COUNT(ph.id) >= 1
                ORDER BY drop_pct DESC
                LIMIT ?
            """, (n,)).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"get_most_dropped_listings error: {e}")
        return []


def get_trend_stats() -> Dict:
    """
    Thống kê tổng quan price trend cho dashboard.
    Returns: {total_tracked, n_dropped, n_risen, avg_drop_pct_of_dropped}
    """
    try:
        with get_conn() as conn:
            total = conn.execute(
                "SELECT COUNT(DISTINCT listing_id) FROM price_history"
            ).fetchone()[0]

            n_dropped = conn.execute(
                "SELECT COUNT(*) FROM listings WHERE price_dropped=1"
            ).fetchone()[0]

            avg_drop = conn.execute("""
                SELECT AVG((price_first_ty - price_ty) / price_first_ty * 100)
                FROM listings
                WHERE price_dropped=1 AND price_first_ty > 0
            """).fetchone()[0]

        return {
            "total_tracked": total,
            "n_dropped": n_dropped,
            "avg_drop_pct": round(avg_drop or 0, 1),
        }
    except Exception as e:
        logger.error(f"get_trend_stats error: {e}")
        return {}
