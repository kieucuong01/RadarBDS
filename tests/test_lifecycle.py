"""Smoke test — lifecycle tracking (in-memory sqlite, không đụng DB thật)."""
import sys
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analytics.lifecycle import (
    mark_seen, sweep_delisted, segment_velocity,
    STALE_HOURS_BEFORE_DELIST, FAST_DELIST_HOURS,
)


def _fresh_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE listings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT UNIQUE, title TEXT, area TEXT, ward TEXT,
            property_type TEXT, price_ty REAL, area_m2 REAL, price_per_m2 REAL,
            first_seen_at TEXT, last_seen_at TEXT, delisted_at TEXT,
            is_active INTEGER DEFAULT 1, lifecycle_hours INTEGER,
            crawled_at TEXT
        );
    """)
    return conn


def _insert(conn, url, first_seen, last_seen, area="Tân An", ptype="dat_nen"):
    conn.execute("""INSERT INTO listings(url, title, area, property_type,
                      first_seen_at, last_seen_at, is_active)
                   VALUES(?,?,?,?,?,?,1)""",
                 (url, "t", area, ptype, first_seen, last_seen))


def test_mark_seen_reactivates():
    conn = _fresh_db()
    old = (datetime.now() - timedelta(days=5)).isoformat(timespec='seconds')
    _insert(conn, "u1", old, old)
    conn.execute("UPDATE listings SET is_active=0, delisted_at=?", (old,))

    mark_seen(conn, ["u1"])
    row = conn.execute("SELECT is_active, delisted_at FROM listings WHERE url='u1'").fetchone()
    assert row["is_active"] == 1
    assert row["delisted_at"] is None


def test_sweep_delisted_flags_stale():
    conn = _fresh_db()
    now  = datetime.now()
    old  = (now - timedelta(hours=STALE_HOURS_BEFORE_DELIST + 10)).isoformat(timespec='seconds')
    new  = now.isoformat(timespec='seconds')
    _insert(conn, "stale",  old, old)       # sẽ bị delisted
    _insert(conn, "active", old, new)       # fresh → bỏ qua

    delisted = sweep_delisted(conn)
    urls = {d["url"] for d in delisted}
    assert "stale" in urls
    assert "active" not in urls


def test_likely_sold_flag():
    conn = _fresh_db()
    now   = datetime.now()
    first = (now - timedelta(hours=24)).isoformat(timespec='seconds')   # sống 24h
    last  = (now - timedelta(hours=STALE_HOURS_BEFORE_DELIST + 5)).isoformat(timespec='seconds')
    # ĐIỀU CHỈNH: last_seen phải sau first_seen
    first = (now - timedelta(hours=STALE_HOURS_BEFORE_DELIST + 29)).isoformat(timespec='seconds')
    _insert(conn, "fast_sold", first, last)

    delisted = sweep_delisted(conn)
    assert len(delisted) == 1
    d = delisted[0]
    # sống ~24h < FAST_DELIST_HOURS(72) → likely_sold
    assert d["likely_sold"] is True


def test_segment_velocity_hot_score():
    conn = _fresh_db()
    now  = datetime.now()
    # 5 listings delisted nhanh (<72h) trong Tân An/dat_nen
    for i in range(5):
        first = (now - timedelta(hours=30)).isoformat(timespec='seconds')
        last  = (now - timedelta(hours=10)).isoformat(timespec='seconds')
        _insert(conn, f"f{i}", first, last)
    conn.execute("""UPDATE listings SET is_active=0, delisted_at=?, lifecycle_hours=20""",
                 (now.isoformat(timespec='seconds'),))

    vel = segment_velocity(conn)
    assert len(vel) == 1
    v = vel[0]
    assert v["n_delisted"] == 5
    assert v["fast_sold"]  == 5
    assert v["fast_sold_ratio"] == 1.0
    assert 0.0 <= v["hot_score"] <= 1.0


if __name__ == "__main__":
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS {t.__name__}")
        except AssertionError as e:
            print(f"  FAIL {t.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"  ERROR {t.__name__}: {type(e).__name__}: {e}")
            failed += 1
    print(f"\n{'OK' if failed == 0 else 'FAILED'}: {len(tests)-failed}/{len(tests)} passed")
    sys.exit(0 if failed == 0 else 1)
