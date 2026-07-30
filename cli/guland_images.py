"""CLI adapter for dry-run-first Guland image backfill."""
import json

from services.guland_image_backfill import run_guland_image_backfill


def cmd_guland_image_backfill(args):
    result = run_guland_image_backfill(
        apply=bool(getattr(args, "apply", False)),
        recover_live_missing=bool(getattr(args, "recover_live_missing", True)),
        download_recovered=bool(getattr(args, "download_recovered", True)),
    )
    print(json.dumps(
        result,
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    ))
    return result
