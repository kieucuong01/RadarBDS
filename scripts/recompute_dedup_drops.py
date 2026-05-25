"""Recompute duplicate flags and reliable repost price drops."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cleansing.dedup import flag_duplicates_in_db
from db.connection import connect


def recompute() -> dict:
    conn = connect()
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
        help="Deprecated; runtime uses DATABASE_URL.",
    )
    args = parser.parse_args()

    stats = recompute()
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
