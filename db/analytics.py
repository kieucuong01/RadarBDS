"""Analytics repository helpers."""
from typing import Optional

from db.connection import get_conn
# ─── Analytics ────────────────────────────────────────────────────────────────

def save_valuation_result(listing_id: int, result: dict,
                          crawl_run_id: Optional[int] = None) -> None:
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO valuation_results
                (listing_id, crawl_run_id, fair_ppm2, actual_ppm2, mos_pct,
                 is_signal, is_outlier, outlier_direction, outlier_sigma,
                 segment, n_segment, signal_score, road_tier)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            listing_id, crawl_run_id,
            result.get("fair_ppm2"),
            result.get("actual_ppm2"),
            result.get("mos_pct"),
            int(result.get("is_signal", False)),
            int(result.get("is_outlier", False)),
            result.get("outlier_direction"),
            result.get("outlier_sigma"),
            result.get("segment"),
            result.get("n_segment"),
            result.get("signal_score"),
            result.get("road_tier", 0),
        ))



