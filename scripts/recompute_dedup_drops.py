"""Recompute duplicate flags and reliable repost price drops for an SQLite DB."""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cleansing.dedup import flag_duplicates_in_db
from db.connection import DB_PATH


def recompute(db_path: Path) -> dict:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        stats = flag_duplicates_in_db(conn)
        conn.commit()
        return stats
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Recompute dedup and repost price-drop flags.")
    parser.add_argument(
        "--db",
        default=None,
        help="Path to radar_bds.db (default: data/radar_bds.db; honors RADAR_DB_PATH).",
    )
    args = parser.parse_args()

    db_path = Path(args.db).expanduser().resolve() if args.db else Path(DB_PATH)
    stats = recompute(db_path)
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
