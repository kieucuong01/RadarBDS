"""Idempotent orchestration for derived listing map locations."""
from __future__ import annotations

from collections.abc import Sequence

from db.listing_map_locations import (
    delete_listing_map_locations,
    delete_stale_listing_map_locations,
    iter_location_candidates,
    upsert_listing_map_locations,
)
from services.listing_location_resolver import (
    load_location_registry,
    resolve_listing_location,
)
from services.market_data import get_city_for_ward


def backfill_listing_locations(
    listing_ids: Sequence[int] | None = None,
    *,
    full: bool = False,
    dry_run: bool = False,
) -> dict[str, int]:
    """Resolve changed rows and keep the derived table synchronized."""
    registry = load_location_registry()
    candidates = iter_location_candidates(None if full else listing_ids)
    stats = {
        "scanned": len(candidates),
        "exact": 0,
        "road": 0,
        "ward": 0,
        "unmapped": 0,
        "inserted": 0,
        "updated": 0,
        "unchanged": 0,
        "deleted": 0,
    }
    changed = []
    newly_unmapped = []

    for candidate in candidates:
        listing = dict(candidate)
        listing["city"] = get_city_for_ward(
            str(listing.get("ward") or "").strip()
        )
        resolved = resolve_listing_location(listing, registry)
        existing_signature = str(
            candidate.get("existing_signature") or ""
        )
        existing_version = str(
            candidate.get("existing_resolver_version") or ""
        )
        has_existing = bool(existing_signature or existing_version)
        if resolved is None:
            stats["unmapped"] += 1
            if has_existing:
                newly_unmapped.append(int(candidate["id"]))
            continue

        stats[resolved.precision] += 1
        if (
            existing_signature == resolved.signature
            and existing_version == resolved.resolver_version
        ):
            stats["unchanged"] += 1
            continue
        if has_existing:
            stats["updated"] += 1
        else:
            stats["inserted"] += 1
        changed.append(resolved)

    if dry_run:
        return stats

    if changed:
        upsert_listing_map_locations(changed)
    if newly_unmapped:
        stats["deleted"] += delete_listing_map_locations(newly_unmapped)
    if full:
        stats["deleted"] += delete_stale_listing_map_locations(
            [int(candidate["id"]) for candidate in candidates]
        )
    return stats
