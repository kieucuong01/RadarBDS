"""Audit/apply repair for stale Facebook compact-price history.

Dry-run by default:
    python scripts/repair_facebook_compact_price_history.py --limit 50

Apply after reviewing the dry-run:
    python scripts/repair_facebook_compact_price_history.py --apply
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config.settings  # noqa: F401
from db.connection import get_conn
from services.facebook_price_repair import repair_facebook_compact_prices


def _parse_listing_ids(raw: str) -> list[int]:
    if not raw.strip():
        return []
    out: list[int] = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        out.append(int(item))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Repair stale Facebook compact-price listing/history rows."
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--listing-ids",
        default="",
        help="Comma-separated listing IDs for a targeted audit/apply.",
    )
    args = parser.parse_args(argv)

    listing_ids = _parse_listing_ids(args.listing_ids)
    with get_conn() as conn:
        summary = repair_facebook_compact_prices(
            conn,
            apply=args.apply,
            listing_ids=listing_ids or None,
            limit=args.limit,
        )
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
