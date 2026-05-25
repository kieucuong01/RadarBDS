"""Remove consecutive unchanged price snapshots from price_history.

The table should record price changes, not every crawl sighting. This script is
idempotent: it keeps the first snapshot for each listing and any later snapshot
where price_ty or price_per_m2 changes.
"""
import argparse
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from db.connection import connect


def _same_value(a, b) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return abs(float(a) - float(b)) < 0.000001


def find_duplicate_snapshot_ids(conn: Any) -> list[int]:
    rows = conn.execute("""
        SELECT id, listing_id, price_ty, price_per_m2
        FROM price_history
        ORDER BY listing_id ASC, recorded_at ASC, id ASC
    """).fetchall()

    duplicate_ids = []
    last_by_listing = {}
    for row in rows:
        listing_id = row["listing_id"]
        previous = last_by_listing.get(listing_id)
        current = (row["price_ty"], row["price_per_m2"])
        if previous and _same_value(current[0], previous[0]) and _same_value(current[1], previous[1]):
            duplicate_ids.append(row["id"])
            continue
        last_by_listing[listing_id] = current
    return duplicate_ids


def cleanup_price_history(dry_run: bool = False) -> int:
    conn = connect()
    try:
        duplicate_ids = find_duplicate_snapshot_ids(conn)
        if dry_run or not duplicate_ids:
            return len(duplicate_ids)

        for start in range(0, len(duplicate_ids), 900):
            chunk = duplicate_ids[start:start + 900]
            placeholders = ",".join("?" for _ in chunk)
            conn.execute(f"DELETE FROM price_history WHERE id IN ({placeholders})", chunk)
        conn.commit()
        return len(duplicate_ids)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Clean unchanged price_history snapshots.")
    parser.add_argument(
        "--db",
        default=None,
        help="Deprecated; runtime uses DATABASE_URL.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Count rows without deleting")
    args = parser.parse_args()

    deleted = cleanup_price_history(dry_run=args.dry_run)
    action = "Would delete" if args.dry_run else "Deleted"
    print(f"{action} {deleted} unchanged price_history snapshots")


if __name__ == "__main__":
    main()
