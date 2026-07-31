"""CLI adapter for bounded Guland historical reconciliation."""
from __future__ import annotations

import json

from services.guland_historical_reconciliation import (
    reconcile_guland_candidates,
)


def cmd_guland_reconcile(args) -> dict:
    stats = reconcile_guland_candidates(
        limit=args.limit,
        apply=bool(args.apply),
    )
    print(json.dumps(stats, ensure_ascii=False, sort_keys=True))
    return stats
