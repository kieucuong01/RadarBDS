import sqlite3

from analytics.market_trend import compute_daily_trend, compute_monthly_trend, compute_weekly_trend


def test_compute_weekly_trend_skips_rows_without_area_or_property_type():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE listings (
            id INTEGER PRIMARY KEY,
            area TEXT,
            property_type TEXT,
            price_per_m2 REAL,
            probably_sold INTEGER DEFAULT 0,
            updated_at TEXT,
            crawled_at TEXT,
            price_dropped INTEGER DEFAULT 0
        );
        CREATE TABLE market_weekly (
            week TEXT,
            area TEXT NOT NULL,
            property_type TEXT NOT NULL,
            median_ppm2 REAL,
            avg_ppm2 REAL,
            n_listings INTEGER,
            n_new INTEGER,
            n_dropped INTEGER,
            computed_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(week, area, property_type)
        );
        """
    )
    rows = [
        (1, None, "dat_nen", 12.0, "2026-05-26T10:00:00", "2026-05-26T10:00:00"),
        (2, "", "dat_nen", 13.0, "2026-05-26T10:00:00", "2026-05-26T10:00:00"),
        (3, "Bến Cát", None, 14.0, "2026-05-26T10:00:00", "2026-05-26T10:00:00"),
        (4, "Bến Cát", "dat_nen", 10.0, "2026-05-26T10:00:00", "2026-05-26T10:00:00"),
        (5, "Bến Cát", "dat_nen", 11.0, "2026-05-26T11:00:00", "2026-05-26T11:00:00"),
    ]
    conn.executemany(
        """
        INSERT INTO listings (id, area, property_type, price_per_m2, updated_at, crawled_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        rows,
    )

    stats = compute_weekly_trend(conn, week="2026-W22")

    assert len(stats) == 1
    assert stats[0]["area"] == "Bến Cát"
    assert stats[0]["property_type"] == "dat_nen"
    assert stats[0]["n_listings"] == 2


def test_compute_monthly_trend_skips_rows_without_area_or_property_type():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE listings (
            id INTEGER PRIMARY KEY,
            area TEXT,
            property_type TEXT,
            price_per_m2 REAL,
            probably_sold INTEGER DEFAULT 0,
            posted_at TEXT,
            crawled_at TEXT
        );
        CREATE TABLE market_weekly (
            week TEXT,
            area TEXT NOT NULL,
            property_type TEXT NOT NULL,
            median_ppm2 REAL,
            avg_ppm2 REAL,
            n_listings INTEGER,
            computed_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(week, area, property_type)
        );
        """
    )
    rows = [
        (1, None, "dat_nen", 20.0, None, "2026-05-26T10:00:00"),
        (2, None, "dat_nen", 21.0, None, "2026-05-26T11:00:00"),
        (3, "Ben Cat", "", 19.0, None, "2026-05-26T12:00:00"),
        (4, "Ben Cat", "dat_nen", 10.0, None, "2026-05-26T13:00:00"),
        (5, "Ben Cat", "dat_nen", 12.0, None, "2026-05-26T14:00:00"),
    ]
    conn.executemany(
        """
        INSERT INTO listings (id, area, property_type, price_per_m2, posted_at, crawled_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        rows,
    )

    compute_monthly_trend(conn)

    stats = conn.execute("SELECT week, area, property_type, n_listings FROM market_weekly").fetchall()
    assert len(stats) == 1
    assert dict(stats[0]) == {
        "week": "M-2026-05",
        "area": "Ben Cat",
        "property_type": "dat_nen",
        "n_listings": 2,
    }


def test_compute_daily_trend_skips_rows_without_area_or_property_type():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE listings (
            id INTEGER PRIMARY KEY,
            area TEXT,
            property_type TEXT,
            price_per_m2 REAL,
            probably_sold INTEGER DEFAULT 0,
            posted_at TEXT,
            crawled_at TEXT
        );
        CREATE TABLE market_weekly (
            week TEXT,
            area TEXT NOT NULL,
            property_type TEXT NOT NULL,
            median_ppm2 REAL,
            avg_ppm2 REAL,
            n_listings INTEGER,
            computed_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(week, area, property_type)
        );
        """
    )
    rows = [
        (1, None, "dat_nen", 20.0, None, "2026-05-26T10:00:00"),
        (2, None, "dat_nen", 21.0, None, "2026-05-26T11:00:00"),
        (3, "Ben Cat", None, 19.0, None, "2026-05-26T12:00:00"),
        (4, "Ben Cat", "dat_nen", 10.0, None, "2026-05-26T13:00:00"),
        (5, "Ben Cat", "dat_nen", 12.0, None, "2026-05-26T14:00:00"),
    ]
    conn.executemany(
        """
        INSERT INTO listings (id, area, property_type, price_per_m2, posted_at, crawled_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        rows,
    )

    compute_daily_trend(conn)

    stats = conn.execute("SELECT week, area, property_type, n_listings FROM market_weekly").fetchall()
    assert len(stats) == 1
    assert dict(stats[0]) == {
        "week": "D-2026-05-26",
        "area": "Ben Cat",
        "property_type": "dat_nen",
        "n_listings": 2,
    }
