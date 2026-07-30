"""CLI adapter for dry-run-first Guland image backfill."""
import json

from services.guland_image_backfill import run_guland_image_backfill


def cmd_guland_image_backfill(args):
    result = run_guland_image_backfill(
        apply=bool(getattr(args, "apply", False)),
        limit=int(getattr(args, "limit", 50)),
        recover_live_missing=bool(getattr(args, "recover_live_missing", True)),
        download_recovered=bool(getattr(args, "download_recovered", True)),
        include_inactive=bool(getattr(args, "include_inactive", False)),
    )
    print(json.dumps(
        result,
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    ))
    return result
