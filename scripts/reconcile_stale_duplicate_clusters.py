"""Safely split stale Facebook duplicate clusters using the current dedup rules."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cleansing.dedup import reconcile_existing_facebook_duplicate_clusters
from db.connection import connect
from services.public_data_publish import publish_public_data

PUBLISH_BATCH_SIZE = 400


def _publish_changed_ids(changed_ids: list[int]) -> list[dict]:
    reports = []
    for start in range(0, len(changed_ids), PUBLISH_BATCH_SIZE):
        batch = tuple(changed_ids[start:start + PUBLISH_BATCH_SIZE])
        reports.append(publish_public_data(
            listing_ids=batch,
            strict=True,
        ))
    return reports


def reconcile(*, apply: bool, max_clusters: int | None = None) -> dict:
    conn = connect()
    try:
        stats = reconcile_existing_facebook_duplicate_clusters(
            conn,
            apply=apply,
            max_clusters=max_clusters,
        )
        if apply:
            conn.commit()
        else:
            conn.rollback()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    if apply and stats["changed_ids"]:
        stats["public_read_model"] = _publish_changed_ids(stats["changed_ids"])
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reconcile stale Facebook duplicate clusters; dry-run by default."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write the reconciled duplicate links and refresh public read models.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Inspect only this many duplicate clusters; unavailable with --apply.",
    )
    args = parser.parse_args()
    if args.apply and args.limit:
        parser.error("--limit is only available for dry-run")
    stats = reconcile(apply=args.apply, max_clusters=args.limit)
    report = {
        **stats,
        "changed_ids_count": len(stats["changed_ids"]),
    }
    report.pop("changed_ids")
    print(json.dumps(
        report,
        ensure_ascii=False,
        indent=2,
    ))


if __name__ == "__main__":
    main()
