"""Privacy-safe audit helpers for listings resolved only to ward centers."""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
import re

from services.listing_location_resolver import (
    LocationRegistry,
    normalize_location_token,
    normalize_road_token,
)


_SHORT_NUMBERED_ROAD_RE = re.compile(
    r"^(?:d|da|db|dc|n|na|r|x|c)\s+\d{1,3}[a-z]?$"
)
_ROAD_CONTEXT_RE = re.compile(
    r"(?:\bduong|\bmat tien|\bmt|\bhem|\bkdc|\btdc)\s*(?:so\s*)?$"
)


def _entry_canonical(entry: Mapping, fallback: str) -> str:
    return normalize_road_token(entry.get("normalized_road") or fallback)


def _has_road_context(text: str, start: int) -> bool:
    return bool(_ROAD_CONTEXT_RE.search(text[max(0, start - 24) : start]))


def _alias_pattern(alias: str) -> str:
    short_numbered = _SHORT_NUMBERED_ROAD_RE.fullmatch(alias)
    if short_numbered:
        prefix, number = alias.rsplit(" ", 1)
        return rf"{re.escape(prefix)}\s*{re.escape(number)}"
    return re.escape(alias)


def _aggregate(
    matches: Mapping[str, set[int]],
    *,
    include_sample_ids: bool,
) -> list[dict]:
    rows = []
    for candidate, listing_ids in matches.items():
        row = {
            "candidate": candidate,
            "affected_listing_count": len(listing_ids),
        }
        if include_sample_ids:
            row["sample_listing_ids"] = sorted(listing_ids)[:10]
        rows.append(row)
    return sorted(
        rows,
        key=lambda row: (
            -row["affected_listing_count"],
            row["candidate"],
        ),
    )


def audit_ward_fallbacks(
    listings: Sequence[Mapping],
    registry: LocationRegistry,
    *,
    city: str,
    ward: str,
    include_sample_ids: bool = True,
) -> dict:
    normalized_ward = normalize_location_token(ward)
    aliases: dict[str, set[str]] = defaultdict(set)
    alias_is_resolvable: dict[str, bool] = {}
    for (entry_city, entry_ward, raw_alias), entries in registry.roads.items():
        if entry_city != city or entry_ward != normalized_ward:
            continue
        alias = normalize_road_token(raw_alias)
        if not alias:
            continue
        aggregate_count = sum(
            1 for entry in entries if bool(entry.get("aggregate"))
        )
        alias_is_resolvable[alias] = (
            len(entries) == 1 or aggregate_count == 1
        )
        for entry in entries:
            aliases[alias].add(_entry_canonical(entry, alias))

    ordered_aliases = sorted(aliases, key=lambda item: (-len(item), item))
    known_matches: dict[str, set[int]] = defaultdict(set)
    ambiguous_matches: dict[str, set[int]] = defaultdict(set)
    for listing in listings:
        text = normalize_location_token(
            " ".join(
                str(listing.get(key) or "")
                for key in ("title", "description")
            )
        )
        listing_id = int(listing.get("id") or 0)
        if listing_id <= 0 or not text:
            continue
        for alias in ordered_aliases:
            match = re.search(
                rf"(?<![a-z0-9]){_alias_pattern(alias)}(?![a-z0-9])",
                text,
            )
            if not match:
                continue
            if _SHORT_NUMBERED_ROAD_RE.fullmatch(alias) and not _has_road_context(
                text,
                match.start(),
            ):
                continue
            canonicals = aliases[alias]
            if len(canonicals) == 1 and alias_is_resolvable.get(alias, False):
                known_matches[next(iter(canonicals))].add(listing_id)
            else:
                ambiguous_matches[alias].add(listing_id)
            break

    return {
        "known_registry_missed": _aggregate(
            known_matches,
            include_sample_ids=include_sample_ids,
        ),
        "ambiguous_registry_matches": _aggregate(
            ambiguous_matches,
            include_sample_ids=include_sample_ids,
        ),
    }
