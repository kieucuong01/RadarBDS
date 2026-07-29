"""CLI entrypoint for deterministic listing map-location backfill."""
from __future__ import annotations

import json

from db.listing_location_coverage import load_listing_location_coverage
from services.listing_location_backfill import backfill_listing_locations


def cmd_map_locations(args):
    stats = backfill_listing_locations(
        full=bool(args.full),
        dry_run=bool(args.dry_run),
    )
    print(json.dumps(stats, ensure_ascii=False, sort_keys=True))
    return stats


_COVERAGE_STATUSES = ("ambiguous", "not_found", "invalid")
_PUBLIC_FIELDS = (
    "candidate_key",
    "city",
    "ward",
    "road_candidate",
    "landmark_candidate",
    "relation",
    "status",
    "affected_listing_count",
    "sample_listing_ids",
    "resolution_note",
)


def cmd_map_location_coverage(args):
    selected = str(getattr(args, "status", "unresolved") or "unresolved")
    statuses = (
        list(_COVERAGE_STATUSES)
        if selected == "unresolved"
        else [selected]
    )
    limit = min(max(int(getattr(args, "limit", 100)), 1), 1000)
    loaded = []
    for status in statuses:
        loaded.extend(load_listing_location_coverage(status, limit))
    loaded.sort(
        key=lambda row: (
            -int(row.get("affected_listing_count") or 0),
            str(row.get("candidate_key") or ""),
        )
    )
    items = [
        {field: row.get(field) for field in _PUBLIC_FIELDS}
        for row in loaded[:limit]
    ]
    payload = {
        "status": statuses,
        "total_candidates": len(items),
        "affected_listings": sum(
            int(item.get("affected_listing_count") or 0) for item in items
        ),
        "items": items,
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str))
    return payload
