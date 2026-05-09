"""Recompute duplicate flags and reliable repost price drops for an SQLite DB."""

import argparse
import json
import sqlite3
from pathlib import Path

from cleansing.dedup import flag_duplicates_in_db


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
    parser.add_argument("--db", required=True, help="Path to radar_bds.db")
    args = parser.parse_args()

    stats = recompute(Path(args.db).expanduser().resolve())
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
