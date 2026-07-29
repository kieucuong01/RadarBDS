"""CLI entrypoint for deterministic listing map-location backfill."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import tempfile
from collections import Counter
from urllib.parse import urlencode

from config.listing_map import (
    LISTING_MAP_AUTO_OVERRIDE_PATH,
    LISTING_MAP_OVERRIDE_PATH,
)
from db.listing_location_coverage import load_listing_location_coverage
from services.listing_location_auto_registry import (
    BrowserLocationEvidence,
    evaluate_browser_evidence,
    point_is_in_scoped_ward,
)
from services.listing_location_backfill import backfill_listing_locations
from services.listing_location_resolver import (
    normalize_location_token,
    normalize_road_token,
)


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


def _slug(value: str) -> str:
    return normalize_location_token(value).replace(" ", "-")


def _candidate_location_key(
    candidate_type: str,
    city: str,
    ward: str,
    canonical: str,
    *,
    landmark: str = "",
) -> str:
    normalized = (
        normalize_road_token(canonical)
        if candidate_type == "road"
        else normalize_location_token(canonical)
    )
    key = (
        f"{candidate_type}:{_slug(city)}:{_slug(ward)}:{_slug(normalized)}"
    )
    if candidate_type == "road" and landmark:
        key += f":{_slug(landmark)}"
    return key


def _candidate_aliases(candidate_type: str, canonical: str) -> list[str]:
    if candidate_type != "landmark":
        return []
    normalized = normalize_location_token(canonical)
    if normalized.startswith("tdc "):
        return [f"khu tai dinh cu {normalized.removeprefix('tdc ')}"]
    if normalized.startswith("kdc "):
        return [f"khu dan cu {normalized.removeprefix('kdc ')}"]
    return []


_ROAD_COPY_TOKENS = frozenset({
    "ban",
    "can",
    "dat",
    "dien",
    "gia",
    "lau",
    "lien",
    "ngang",
    "ngu",
    "nha",
    "phong",
    "tho",
    "tich",
    "tret",
    "trieu",
    "ty",
    "toilet",
    "wc",
})
_GENERIC_ROAD_COPY = frozenset({
    "duong nhua",
    "gan cho",
    "hem rong",
    "mat tien",
})
_NUMBERED_ROAD_RE = re.compile(
    r"^(?:duong so|dx|d|db|dh|dt|ql|n|ng|ni|na|nb)\s+\d+[a-z]?$"
)


def _candidate_is_researchable(
    candidate_type: str,
    canonical: str,
) -> bool:
    normalized = (
        normalize_road_token(canonical)
        if candidate_type == "road"
        else normalize_location_token(canonical)
    )
    tokens = normalized.split()
    if not normalized or len(normalized) > 100 or len(tokens) > 8:
        return False
    if candidate_type == "landmark":
        return normalized.startswith((
            "kdc ",
            "khu dan cu ",
            "khu tai dinh cu ",
            "tdc ",
        ))
    if (
        normalized in _GENERIC_ROAD_COPY
        or _ROAD_COPY_TOKENS.intersection(tokens)
    ):
        return False
    if any(character.isdigit() for character in normalized):
        return bool(_NUMBERED_ROAD_RE.fullmatch(normalized))
    return len(tokens) >= 2 and all(token.isalpha() for token in tokens)


def _research_items_for_row(row: dict, selected_type: str) -> list[dict]:
    city = str(row.get("city") or "").strip()
    ward = str(row.get("ward") or "").strip()
    road = normalize_road_token(row.get("road_candidate") or "")
    landmark = normalize_location_token(
        row.get("landmark_candidate") or ""
    )
    if not city or not ward:
        return []

    types = []
    if (
        road
        and selected_type in {"all", "road"}
        and _candidate_is_researchable("road", road)
    ):
        types.append(("road", road))
    if (
        landmark
        and selected_type in {"all", "landmark"}
        and _candidate_is_researchable("landmark", landmark)
    ):
        types.append(("landmark", landmark))

    items = []
    for candidate_type, canonical in types:
        query_parts = [canonical]
        if candidate_type == "road" and landmark:
            query_parts.append(landmark)
        query_parts.extend([ward, city])
        query = ", ".join(value for value in query_parts if value)
        items.append({
            "affected_listing_count": max(
                int(row.get("affected_listing_count") or 0),
                0,
            ),
            "aliases": _candidate_aliases(candidate_type, canonical),
            "candidate_key": _candidate_location_key(
                candidate_type,
                city,
                ward,
                canonical,
                landmark=landmark,
            ),
            "candidate_type": candidate_type,
            "canonical": canonical,
            "city": city,
            "query": query,
            "resolution_note": str(
                row.get("resolution_note") or ""
            )[:500],
            "search_url": (
                "https://www.google.com/maps/search/?"
                + urlencode({"api": "1", "query": query})
            ),
            "status": str(row.get("status") or ""),
            "ward": ward,
        })
        if candidate_type == "road" and landmark:
            items[-1]["landmark_scope"] = landmark
    return items


def cmd_map_location_research_queue(args):
    limit = min(max(int(getattr(args, "limit", 50)), 1), 50)
    selected_type = str(
        getattr(args, "candidate_type", "all") or "all"
    ).lower()
    if selected_type not in {"all", "road", "landmark"}:
        raise ValueError("invalid candidate type")

    merged = {}
    filtered = set()
    for status in _COVERAGE_STATUSES:
        for row in load_listing_location_coverage(status, 1000):
            city = str(row.get("city") or "").strip()
            ward = str(row.get("ward") or "").strip()
            road = normalize_road_token(row.get("road_candidate") or "")
            landmark = normalize_location_token(
                row.get("landmark_candidate") or ""
            )
            for candidate_type, canonical in (
                ("road", road),
                ("landmark", landmark),
            ):
                if (
                    canonical
                    and selected_type in {"all", candidate_type}
                    and not _candidate_is_researchable(
                        candidate_type,
                        canonical,
                    )
                ):
                    filtered.add(
                        _candidate_location_key(
                            candidate_type,
                            city,
                            ward,
                            canonical,
                            landmark=(
                                landmark if candidate_type == "road" else ""
                            ),
                        )
                    )
            for item in _research_items_for_row(row, selected_type):
                key = item["candidate_key"]
                previous = merged.get(key)
                if previous is None:
                    merged[key] = item
                    continue
                previous["affected_listing_count"] += item[
                    "affected_listing_count"
                ]
    ranked_items = sorted(
        merged.values(),
        key=lambda item: (
            -item["affected_listing_count"],
            item["candidate_key"],
        ),
    )
    items = ranked_items[:limit]
    payload = {
        "candidate_type": selected_type,
        "filtered_candidates": len(filtered),
        "total_candidates": len(ranked_items),
        "returned_candidates": len(items),
        "items": items,
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return payload


def load_manual_override_keys() -> frozenset[str]:
    payload = json.loads(
        LISTING_MAP_OVERRIDE_PATH.read_text(encoding="utf-8")
    )
    keys = set()
    for row in payload.get("roads") or ():
        city = str(row.get("city") or "").strip()
        ward = str(row.get("ward") or "").strip()
        road = str(row.get("road_name") or "").strip()
        if not city or not ward or not road:
            continue
        keys.add(_candidate_location_key("road", city, ward, road))
        for landmark in row.get("landmark_keys") or ():
            keys.add(
                _candidate_location_key(
                    "road",
                    city,
                    ward,
                    road,
                    landmark=normalize_location_token(landmark),
                )
            )
    for row in payload.get("landmarks") or ():
        city = str(row.get("city") or "").strip()
        ward = str(row.get("ward") or "").strip()
        landmark = str(row.get("landmark_name") or "").strip()
        if city and ward and landmark:
            keys.add(
                _candidate_location_key(
                    "landmark",
                    city,
                    ward,
                    landmark,
                )
            )
    return frozenset(keys)


def _bounded_evidence_payload(path: Path) -> dict:
    path = Path(path)
    if not path.is_file():
        raise ValueError("evidence input file does not exist")
    if path.stat().st_size > 1_000_000:
        raise ValueError("evidence input exceeds 1 MB")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("evidence input is not valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("evidence input root must be an object")
    items = payload.get("items")
    if not isinstance(items, list):
        raise ValueError("evidence items must be a list")
    if len(items) > 50:
        raise ValueError("evidence input accepts at most 50 items")
    return payload


def _atomic_write_json(path: Path, payload: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        text=True,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(
            descriptor,
            "w",
            encoding="utf-8",
            newline="\n",
        ) as handle:
            handle.write(
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def cmd_map_location_ingest_evidence(args):
    payload = _bounded_evidence_payload(Path(args.input))
    manual_keys = load_manual_override_keys()
    evidences = [
        BrowserLocationEvidence.from_mapping(raw_item)
        for raw_item in payload["items"]
    ]
    key_counts = Counter(
        evidence.candidate_key for evidence in evidences
    )
    auto_payload = json.loads(
        LISTING_MAP_AUTO_OVERRIDE_PATH.read_text(encoding="utf-8")
    )
    existing = auto_payload.get("entries")
    if not isinstance(existing, list):
        raise ValueError("auto override entries must be a list")
    by_key = {}
    for entry in existing:
        if not isinstance(entry, dict):
            raise ValueError("auto override entry must be an object")
        key = str(entry.get("candidate_key") or "")
        if not key:
            raise ValueError("auto override candidate_key is required")
        if key in by_key:
            raise ValueError("duplicate stored auto override candidate_key")
        by_key[key] = entry

    accepted = []
    quarantined = 0
    for evidence in evidences:
        if key_counts[evidence.candidate_key] > 1:
            quarantined += 1
            continue
        decision = evaluate_browser_evidence(
            evidence,
            manual_keys=manual_keys,
            ward_contains=point_is_in_scoped_ward,
        )
        if decision.status != "accepted" or decision.override is None:
            quarantined += 1
            continue
        current = by_key.get(evidence.candidate_key)
        if current is not None:
            try:
                current_coordinates = (
                    float(current["lat"]),
                    float(current["lng"]),
                )
                suggested_coordinates = (
                    float(decision.override["lat"]),
                    float(decision.override["lng"]),
                )
            except (KeyError, TypeError, ValueError):
                raise ValueError(
                    "stored auto override coordinates are invalid"
                ) from None
            if any(
                abs(stored - suggested) > 0.0000001
                for stored, suggested in zip(
                    current_coordinates,
                    suggested_coordinates,
                    strict=True,
                )
            ):
                quarantined += 1
                continue
        accepted.append(dict(decision.override))

    result = {
        "attempted": len(evidences),
        "accepted": len(accepted),
        "quarantined": quarantined,
        "applied": 0,
    }
    if bool(getattr(args, "apply", False)) and accepted:
        changed = 0
        for entry in accepted:
            key = str(entry["candidate_key"])
            if by_key.get(key) != entry:
                by_key[key] = entry
                changed += 1
        auto_payload["entries"] = [
            by_key[key] for key in sorted(by_key)
        ]
        if changed:
            _atomic_write_json(
                LISTING_MAP_AUTO_OVERRIDE_PATH,
                auto_payload,
            )
        result["applied"] = changed
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return result
