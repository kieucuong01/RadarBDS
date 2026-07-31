"""CLI adapter for dry-run-first Guland publisher backfill."""

import json

from services.guland_publisher_backfill import run_guland_publisher_backfill


def cmd_guland_publisher_backfill(args):
    result = run_guland_publisher_backfill(
        apply=bool(getattr(args, "apply", False)),
        limit=int(getattr(args, "limit", 100)),
        resume=bool(getattr(args, "resume", True)),
    )
    print(json.dumps(
        result,
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    ))
    return result
