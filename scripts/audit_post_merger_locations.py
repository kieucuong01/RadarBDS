"""Read-only audit for post-merger TDM/Ben Cat location parsing.

Prints raw/listing rows where a new administrative ward appears but the
canonical valuation ward is missing or conflicts with stronger old-area
evidence from KP/old-ward/road rules.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from config.location_aliases import NEW_WARD_COMPONENTS, resolve_post_merger_location
from db.connection import connect


SEARCH_TERMS = (
    "TPHCM",
    "TP HCM",
    "Hồ Chí Minh",
    "Bình Dương",
    "Chánh Hiệp",
    "Hòa Lợi",
    "Hoà Lợi",
    "Phú Lợi",
    "Phú An",
    "Bến Cát",
    "Long Nguyên",
    "Chánh Phú Hòa",
    "khu phố",
    "KP",
)


def _loads(raw_json: Any) -> dict[str, Any]:
    if isinstance(raw_json, dict):
        return raw_json
    if not raw_json:
        return {}
    try:
        return json.loads(raw_json)
    except (TypeError, ValueError):
        return {}


def _component_match(ward: str | None, components: tuple[str, ...]) -> bool:
    if not ward:
        return False
    return any(ward == comp or ward.startswith(f"{comp} ") for comp in components)


def _audit_status(current_ward: str | None, new_ward: str, inferred_ward: str | None) -> str | None:
    if inferred_ward:
        if current_ward == inferred_ward:
            return None
        return "conflict_inferred" if current_ward else "missing_inferred"
    if not current_ward:
        return "missing_broad_new"
    if current_ward == new_ward:
        return "broad_new_mapped"
    components = NEW_WARD_COMPONENTS.get(new_ward, ())
    if components and not _component_match(current_ward, components):
        return "outside_new_components"
    return None


def _candidate_rows(limit: int, source: str | None) -> list[dict[str, Any]]:
    clauses = ["(" + " OR ".join(["r.raw_json ILIKE ?"] * len(SEARCH_TERMS)) + ")"]
    params: list[Any] = [f"%{term}%" for term in SEARCH_TERMS]
    if source:
        clauses.append("r.source = ?")
        params.append(source)
    params.append(limit)

    sql = f"""
        SELECT
            r.id AS raw_id,
            r.source,
            r.source_id,
            r.url,
            r.raw_json,
            l.id AS listing_id,
            l.ward AS current_ward,
            l.area AS current_area
        FROM raw_listings r
        LEFT JOIN listings l ON l.raw_id = r.id
        WHERE {" AND ".join(clauses)}
        ORDER BY r.crawled_at DESC, r.id DESC
        LIMIT ?
    """
    conn = connect()
    try:
        return [dict(row.items()) for row in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def run_audit(limit: int, samples_per_group: int, source: str | None) -> int:
    groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    scanned = 0
    matched = 0

    for row in _candidate_rows(limit, source):
        scanned += 1
        raw = _loads(row.get("raw_json"))
        title = raw.get("title") or ""
        description = raw.get("description") or ""
        address = raw.get("address") or ""
        url = raw.get("url") or row.get("url") or ""
        intended_city = raw.get("default_area") or raw.get("area_name") or raw.get("area")

        result = resolve_post_merger_location(
            title,
            description,
            address,
            url,
            intended_city=intended_city,
        )
        if not result.new_ward:
            continue

        current_ward = row.get("current_ward")
        status = _audit_status(current_ward, result.new_ward, result.ward)
        if not status:
            continue

        matched += 1
        key = (
            result.new_ward,
            result.ward or "-",
            status,
            result.evidence or result.evidence_type or "-",
        )
        groups[key].append({
            "raw_id": row.get("raw_id"),
            "listing_id": row.get("listing_id"),
            "source": row.get("source"),
            "current_ward": current_ward,
            "current_area": row.get("current_area"),
            "title": title[:160],
            "url": url,
        })

    print("Post-merger location audit (read only)")
    print(f"Scanned candidate rows: {scanned}")
    print(f"Rows needing review: {matched}")
    print()

    for key, rows in sorted(groups.items(), key=lambda item: len(item[1]), reverse=True):
        new_ward, inferred_ward, status, evidence = key
        print(
            f"{len(rows):4} | new_ward={new_ward} | inferred={inferred_ward} "
            f"| status={status} | evidence={evidence}"
        )
        for sample in rows[:samples_per_group]:
            print(
                "     "
                f"raw={sample['raw_id']} listing={sample['listing_id']} "
                f"source={sample['source']} current={sample['current_ward']} "
                f"area={sample['current_area']} title={sample['title']}"
            )
        print()

    return matched


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit post-merger location resolver candidates.")
    parser.add_argument("--limit", type=int, default=1000, help="Max raw rows to scan")
    parser.add_argument("--samples", type=int, default=3, help="Samples to print per group")
    parser.add_argument("--source", default=None, help="Optional raw_listings.source filter")
    args = parser.parse_args()

    run_audit(limit=args.limit, samples_per_group=args.samples, source=args.source)


if __name__ == "__main__":
    main()
