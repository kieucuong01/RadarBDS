"""Reprocess Facebook raw rows whose asking price is intentionally masked."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cleansing.feature_extractor import has_ambiguous_masked_price
from cleansing.reprocess import reprocess_listings, reprocess_valuation
from db.connection import connect
from services.public_data_publish import publish_public_data


def ambiguous_raw_ids() -> list[int]:
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT id, raw_json FROM raw_listings WHERE source='facebook' ORDER BY id"
        ).fetchall()
    finally:
        conn.close()

    raw_ids: list[int] = []
    for row in rows:
        try:
            payload = json.loads(row["raw_json"] or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        text = "\n".join(
            str(payload.get(field) or "")
            for field in ("title", "description")
        )
        if has_ambiguous_masked_price(text):
            raw_ids.append(int(row["id"]))
    return raw_ids


def reconcile(*, apply: bool) -> dict:
    raw_ids = ambiguous_raw_ids()
    stats: dict = {
        "raw_ids_count": len(raw_ids),
    }
    if not apply or not raw_ids:
        return stats

    listing_stats = reprocess_listings(raw_ids=raw_ids)
    processed_ids = tuple(dict.fromkeys(listing_stats.get("processed_ids") or []))
    stats["listings"] = listing_stats
    stats["valuation"] = reprocess_valuation(
        incremental_ids=list(processed_ids)
    )
    if processed_ids:
        stats["public_read_model"] = publish_public_data(
            listing_ids=processed_ids,
            strict=True,
        )
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reprocess ambiguous Facebook prices; dry-run by default."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Reprocess rows, recalculate valuations, and refresh public read models.",
    )
    args = parser.parse_args()
    print(json.dumps(reconcile(apply=args.apply), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
