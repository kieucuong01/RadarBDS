import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path

from services.market_data import load_market_indicators


def _shift_month(d, delta):
    month_idx = d.year * 12 + (d.month - 1) + delta
    return date(month_idx // 12, month_idx % 12 + 1, 1)


def _create_db(path):
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE listings (
            id INTEGER PRIMARY KEY,
            source TEXT,
            ward TEXT,
            property_type TEXT,
            price_ty REAL,
            area_m2 REAL,
            probably_sold INTEGER DEFAULT 0,
            is_blacklisted INTEGER DEFAULT 0,
            review_hidden INTEGER DEFAULT 0,
            duplicate_of_id INTEGER,
            price_dropped INTEGER DEFAULT 0,
            suspicious_bait INTEGER DEFAULT 0,
            posted_at TEXT,
            crawled_at TEXT
        )
    """)
    conn.commit()
    return conn


def _insert_listing(conn, listing_id, ward, posted_at, duplicate_of_id=None,
                    price_dropped=0, suspicious_bait=0):
    conn.execute("""
        INSERT INTO listings (
            id, source, ward, property_type, price_ty, area_m2,
            probably_sold, is_blacklisted, review_hidden, duplicate_of_id,
            price_dropped, suspicious_bait, posted_at, crawled_at
        )
        VALUES (?, 'facebook', ?, 'dat_nen', 2.0, 100.0, 0, 0, 0, ?, ?, ?, ?, ?)
    """, (
        listing_id,
        ward,
        duplicate_of_id,
        price_dropped,
        suspicious_bait,
        posted_at,
        posted_at,
    ))


class MarketIndicatorTest(unittest.TestCase):
    def _with_db(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db_path = Path(tmp.name) / "radar_test.db"
        return db_path, _create_db(db_path)

    def test_distress_ratio_counts_deduped_lots_with_reliable_price_drop(self):
        db_path, conn = self._with_db()
        today = date.today().replace(day=1).isoformat()
        _insert_listing(conn, 1, "Tan Dinh", today)
        _insert_listing(conn, 2, "Tan Dinh", today, duplicate_of_id=1, price_dropped=1)
        _insert_listing(conn, 3, "Tan Dinh", today)
        _insert_listing(conn, 4, "Tan Dinh", today, price_dropped=1, suspicious_bait=1)
        conn.commit()
        conn.close()

        data = load_market_indicators(str(db_path), wards=["Tan Dinh"])
        row = next(x for x in data["distress_ratio"] if x["ward"] == "Tan Dinh")

        self.assertEqual(row["total_count"], 3)
        self.assertEqual(row["distress_count"], 1)
        self.assertEqual(row["ratio_pct"], 33.3)

    def test_supply_anomaly_uses_current_month_vs_previous_three_month_average(self):
        db_path, conn = self._with_db()
        current = date.today().replace(day=1)
        prev_1 = _shift_month(current, -1)
        prev_2 = _shift_month(current, -2)
        prev_3 = _shift_month(current, -3)

        _insert_listing(conn, 10, "An Tay", prev_1.isoformat())
        _insert_listing(conn, 11, "An Tay", current.isoformat(), duplicate_of_id=10)
        _insert_listing(conn, 12, "An Tay", prev_2.isoformat())
        _insert_listing(conn, 13, "An Tay", prev_3.isoformat())
        _insert_listing(conn, 14, "An Tay", current.isoformat())
        _insert_listing(conn, 15, "An Tay", current.isoformat())
        _insert_listing(conn, 16, "An Tay", current.isoformat())
        conn.commit()
        conn.close()

        data = load_market_indicators(str(db_path), wards=["An Tay"])
        row = next(x for x in data["supply_anomaly"] if x["ward"] == "An Tay")

        self.assertEqual(row["current_count"], 3)
        self.assertEqual(row["prev_avg"], 1.0)
        self.assertEqual(row["growth_x"], 3.0)
        self.assertEqual(row["level_key"], "danger")


if __name__ == "__main__":
    unittest.main()
