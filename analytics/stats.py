"""
Analytics: tính toán area_stats theo ngày
- Median / avg / min / max giá/m2
- Gross Rental Yield
"""
import logging
from datetime import date

from config.database import get_conn

logger = logging.getLogger(__name__)

UPDATE_STATS_SQL = """
INSERT INTO area_stats (
    area_id, stat_date,
    avg_price_per_m2, median_price_per_m2,
    min_price_per_m2, max_price_per_m2,
    listing_count, gross_rental_yield
)
SELECT
    l.area_id,
    CURRENT_DATE,
    ROUND(AVG(l.price_per_m2)::numeric, 3),
    ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY l.price_per_m2)::numeric, 3),
    ROUND(MIN(l.price_per_m2)::numeric, 3),
    ROUND(MAX(l.price_per_m2)::numeric, 3),
    COUNT(*),
    -- Gross Rental Yield = (avg_rent_per_m2 * 12) / (avg_sale_price_per_m2 * 1_000_000) * 100
    CASE
        WHEN AVG(CASE WHEN l.transaction_type='ban'  THEN l.price_per_m2 END) > 0
         AND AVG(CASE WHEN l.transaction_type='thue' THEN l.price_per_m2 END) > 0
        THEN ROUND(
            ((AVG(CASE WHEN l.transaction_type='thue' THEN l.price_per_m2 END) * 12
             / (AVG(CASE WHEN l.transaction_type='ban' THEN l.price_per_m2 END) * 1000)
            ) * 100)::numeric, 2
        )
        ELSE NULL
    END
FROM listings l
WHERE l.area_id IS NOT NULL
  AND l.price_per_m2 IS NOT NULL
  AND l.price_per_m2 BETWEEN 0.5 AND 200000
  AND l.crawled_at >= NOW() - INTERVAL '30 days'
GROUP BY l.area_id
ON CONFLICT (area_id, stat_date) DO UPDATE SET
    avg_price_per_m2    = EXCLUDED.avg_price_per_m2,
    median_price_per_m2 = EXCLUDED.median_price_per_m2,
    min_price_per_m2    = EXCLUDED.min_price_per_m2,
    max_price_per_m2    = EXCLUDED.max_price_per_m2,
    listing_count       = EXCLUDED.listing_count,
    gross_rental_yield  = EXCLUDED.gross_rental_yield;
"""


def compute_daily_stats() -> None:
    """Tính và lưu stats hàng ngày cho tất cả khu vực."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(UPDATE_STATS_SQL)
    logger.info(f"area_stats updated for {date.today()}")


def get_area_trend(area_name: str, days: int = 30) -> list:
    """Lấy trend giá của một khu vực trong N ngày gần nhất."""
    sql = """
    SELECT s.stat_date, s.median_price_per_m2, s.listing_count, s.gross_rental_yield
    FROM area_stats s
    JOIN areas a ON a.id = s.area_id
    WHERE a.name = %s
      AND s.stat_date >= CURRENT_DATE - %s
    ORDER BY s.stat_date ASC
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (area_name, days))
            return cur.fetchall()
