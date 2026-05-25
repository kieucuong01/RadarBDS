import sys
import unittest
import uuid
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.market_data import load_market_indicators


def _shift_month(d, delta):
    month_idx = d.year * 12 + (d.month - 1) + delta
    return date(month_idx // 12, month_idx % 12 + 1, 1)


class MarketIndicatorTest(unittest.TestCase):
    def setUp(self):
        from db import connection
        from db.schema import init_schema

        self.token = uuid.uuid4().hex
        self.url_prefix = f"https://market-indicator-{self.token}.test"
        self.distress_ward = f"DistressWard{self.token[:8]}"
        self.supply_ward = f"SupplyWard{self.token[:8]}"
        self.listing_ids = []
        connection.close_all()
        init_schema()
        self._delete_test_rows()

    def tearDown(self):
        from db import connection

        self._delete_test_rows()
        connection.close_all()

    def _delete_test_rows(self):
        from db.connection import get_conn

        with get_conn() as conn:
            rows = conn.execute(
                "SELECT id FROM listings WHERE url LIKE ?",
                (f"{self.url_prefix}%",),
            ).fetchall()
            ids = {r["id"] for r in rows}
            ids.update(self.listing_ids)
            if not ids:
                return
            placeholders = ",".join("?" * len(ids))
            params = list(ids)
            conn.execute(f"DELETE FROM price_history WHERE listing_id IN ({placeholders})", params)
            conn.execute(f"DELETE FROM valuation_results WHERE listing_id IN ({placeholders})", params)
            conn.execute(f"DELETE FROM listing_images WHERE listing_id IN ({placeholders})", params)
            conn.execute(f"DELETE FROM legal_verifications WHERE listing_id IN ({placeholders})", params)
            conn.execute(f"DELETE FROM listings WHERE id IN ({placeholders})", params)

    def _insert_listing(self, ward, posted_at, duplicate_of_id=None, price_dropped=0, suspicious_bait=0):
        from db.connection import get_conn

        idx = len(self.listing_ids) + 1
        with get_conn() as conn:
            cur = conn.execute("""
                INSERT INTO listings (
                    source, source_id, url, title, ward, property_type, price_ty, area_m2,
                    probably_sold, is_blacklisted, review_hidden, duplicate_of_id,
                    price_dropped, suspicious_bait, posted_at, crawled_at
                )
                VALUES ('facebook', ?, ?, 'Market indicator listing', ?, 'dat_nen', 2.0, 100.0,
                        0, 0, 0, ?, ?, ?, ?, ?)
            """, (
                f"market-indicator-{self.token}-{idx}",
                f"{self.url_prefix}/{idx}",
                ward,
                duplicate_of_id,
                price_dropped,
                suspicious_bait,
                posted_at,
                posted_at,
            ))
            listing_id = cur.lastrowid
            self.listing_ids.append(listing_id)
            return listing_id

    def test_distress_ratio_counts_deduped_lots_with_reliable_price_drop(self):
        today = date.today().replace(day=1).isoformat()
        canonical = self._insert_listing(self.distress_ward, today)
        self._insert_listing(self.distress_ward, today, duplicate_of_id=canonical, price_dropped=1)
        self._insert_listing(self.distress_ward, today)
        self._insert_listing(self.distress_ward, today, price_dropped=1, suspicious_bait=1)

        data = load_market_indicators(None, wards=[self.distress_ward])
        row = next(x for x in data["distress_ratio"] if x["ward"] == self.distress_ward)

        self.assertEqual(row["total_count"], 3)
        self.assertEqual(row["distress_count"], 1)
        self.assertEqual(row["ratio_pct"], 33.3)

    def test_supply_anomaly_uses_current_month_vs_previous_three_month_average(self):
        current = date.today().replace(day=1)
        prev_1 = _shift_month(current, -1)
        prev_2 = _shift_month(current, -2)
        prev_3 = _shift_month(current, -3)

        previous_canonical = self._insert_listing(self.supply_ward, prev_1.isoformat())
        self._insert_listing(self.supply_ward, current.isoformat(), duplicate_of_id=previous_canonical)
        self._insert_listing(self.supply_ward, prev_2.isoformat())
        self._insert_listing(self.supply_ward, prev_3.isoformat())
        self._insert_listing(self.supply_ward, current.isoformat())
        self._insert_listing(self.supply_ward, current.isoformat())
        self._insert_listing(self.supply_ward, current.isoformat())

        data = load_market_indicators(None, wards=[self.supply_ward])
        row = next(x for x in data["supply_anomaly"] if x["ward"] == self.supply_ward)

        self.assertEqual(row["current_count"], 3)
        self.assertEqual(row["prev_avg"], 1.0)
        self.assertEqual(row["growth_x"], 3.0)
        self.assertEqual(row["level_key"], "danger")


if __name__ == "__main__":
    unittest.main()
