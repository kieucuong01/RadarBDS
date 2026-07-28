from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Iterable, Mapping


IDENTITY_FIELDS = (
    "area",
    "street",
    "from",
    "to",
    "residential",
    "commerce_service",
    "production_business",
)


def land_price_row_key(row: Mapping[str, object]) -> str:
    identity = "\x1f".join(
        str(row.get(field) or "") for field in IDENTITY_FIELDS
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]


def find_land_price_row(rows: Iterable[dict], row_key: str) -> dict | None:
    if not row_key:
        return None
    return next(
        (row for row in rows if land_price_row_key(row) == row_key),
        None,
    )


def search_key(value: str) -> str:
    text = unicodedata.normalize("NFD", str(value or "").lower())
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = text.replace("đ", "d")
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _match_metadata(row: dict, query_key: str) -> tuple[int, str] | None:
    if not query_key:
        return 0, "area"

    street_key = search_key(row.get("street", ""))
    endpoint_key = search_key(f"{row.get('from', '')} {row.get('to', '')}")
    words = query_key.split()
    if street_key == query_key:
        return 0, "exact_street"
    if street_key.startswith(query_key):
        return 1, "street_prefix"
    if all(word in street_key for word in words):
        return 2, "street_contains"
    if all(word in endpoint_key for word in words):
        return 3, "segment_endpoint"

    haystack = row.get("search") or search_key(
        " ".join(
            str(row.get(field) or "")
            for field in ("area", "street", "from", "to")
        )
    )
    if all(word in haystack for word in words):
        return 4, "related"
    return None


def search_land_prices(
    rows: list[dict],
    *,
    query: str,
    area: str,
    page: int,
    limit: int,
) -> dict:
    query_key = search_key(query)
    area_words = search_key(area).split()
    ranked: list[tuple[int, str, str, int, dict]] = []
    seen: set[tuple] = set()

    for index, row in enumerate(rows):
        row_area_key = search_key(row.get("area", ""))
        if area_words and not all(word in row_area_key for word in area_words):
            continue

        metadata = _match_metadata(row, query_key)
        if metadata is None:
            continue
        rank, match_type = metadata

        identity = tuple(row.get(field) for field in IDENTITY_FIELDS)
        if identity in seen:
            continue
        seen.add(identity)

        item = dict(row)
        item["match_type"] = match_type
        item["row_key"] = land_price_row_key(row)
        ranked.append(
            (
                rank,
                search_key(row.get("street", "")),
                row_area_key,
                index,
                item,
            )
        )

    ranked.sort(key=lambda match: match[:4])
    total = len(ranked)
    total_pages = max(1, (total + limit - 1) // limit)
    page = max(1, min(page, total_pages))
    start = (page - 1) * limit
    items = [match[4] for match in ranked[start : start + limit]]
    return {
        "items": items,
        "total": total,
        "page": page,
        "limit": limit,
        "has_more": start + limit < total,
    }
