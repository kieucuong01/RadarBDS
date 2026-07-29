"""CLI entrypoint for deterministic listing map-location backfill."""
from __future__ import annotations

import json

from services.listing_location_backfill import backfill_listing_locations


def cmd_map_locations(args):
    stats = backfill_listing_locations(
        full=bool(args.full),
        dry_run=bool(args.dry_run),
    )
    print(json.dumps(stats, ensure_ascii=False, sort_keys=True))
    return stats
