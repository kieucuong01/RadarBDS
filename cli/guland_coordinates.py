"""CLI adapter for the dry-run-first Guland coordinate backfill."""
import json

from services.guland_coordinate_backfill import (
    run_guland_coordinate_backfill,
)


def cmd_guland_coordinate_backfill(args):
    result = run_guland_coordinate_backfill(
        apply=bool(getattr(args, "apply", False)),
        rollback_run=str(getattr(args, "rollback_run", "") or ""),
    )
    print(json.dumps(
        result,
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    ))
    return result
