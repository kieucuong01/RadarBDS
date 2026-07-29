"""Deterministic aggregation for map-location coverage issues."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from collections.abc import Sequence

from services.listing_location_resolver import (
    ResolutionIssue,
    normalize_location_token,
    normalize_road_token,
)


@dataclass(frozen=True)
class CoverageRow:
    candidate_key: str
    city: str
    ward: str = ""
    road_candidate: str = ""
    landmark_candidate: str = ""
    relation: str = ""
    status: str = "not_found"
    affected_listing_count: int = 0
    sample_listing_ids: tuple[int, ...] = ()
    resolution_note: str = ""


def aggregate_coverage_issues(
    issues: Sequence[ResolutionIssue],
) -> list[CoverageRow]:
    """Group equivalent unresolved candidates without retaining listing text."""
    grouped: dict[tuple[str, ...], dict[str, object]] = {}
    for issue in issues:
        city = normalize_location_token(issue.city)
        ward = normalize_location_token(issue.ward)
        road = normalize_road_token(issue.road_candidate)
        landmark = normalize_location_token(issue.landmark_candidate)
        relation = normalize_location_token(issue.relation)
        status = str(issue.status or "").strip().lower()
        identity = (city, ward, road, landmark, relation, status)
        bucket = grouped.setdefault(
            identity,
            {
                "city": str(issue.city or "").strip(),
                "ward": str(issue.ward or "").strip(),
                "road": road,
                "landmark": landmark,
                "relation": relation,
                "status": status,
                "ids": set(),
                "notes": set(),
            },
        )
        if issue.listing_id > 0:
            bucket["ids"].add(int(issue.listing_id))
        if issue.resolution_note:
            bucket["notes"].add(str(issue.resolution_note).strip())

    rows = []
    for identity, bucket in grouped.items():
        raw_key = "|".join(identity)
        sample_ids = tuple(sorted(bucket["ids"])[:10])
        rows.append(
            CoverageRow(
                candidate_key=hashlib.sha256(raw_key.encode("utf-8")).hexdigest(),
                city=bucket["city"],
                ward=bucket["ward"],
                road_candidate=bucket["road"],
                landmark_candidate=bucket["landmark"],
                relation=bucket["relation"],
                status=bucket["status"],
                affected_listing_count=len(bucket["ids"]),
                sample_listing_ids=sample_ids,
                resolution_note=";".join(sorted(bucket["notes"])),
            )
        )
    return sorted(
        rows,
        key=lambda row: (-row.affected_listing_count, row.candidate_key),
    )
