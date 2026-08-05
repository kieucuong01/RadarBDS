"""Deterministic, privacy-safe destinations for Radar Ask source cards."""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlencode, urlparse

from .contracts import SourceKind


DIRECT_LISTING_REF = re.compile(r"^radar-(?:listing|signal):(\d+)(?::|$)")
LOT_LISTING_REF = re.compile(r"^radar-lot:\d+:listing:(\d+)(?::|$)")
WARD_MARKET_REF = re.compile(r"^ward-market:(.+):(\d+)d$")
BUDGET_AREA_REF = re.compile(r"^budget-area:(.+):([^:]+)$")
PRICE_DROP_AREA_REF = re.compile(r"^price-drop-area:(.+):(\d+)d$")
ROAD_MARKET_REF = re.compile(
    r"^road-market:([^:]+):(.+):(exact_road|ward_road_tier_fallback):(\d+)d$"
)
FRIENDLY_KIND_TITLES = {
    SourceKind.LISTING: "Tin Radar BDS",
    SourceKind.VALUATION: "Định giá Radar BDS",
    SourceKind.COMPARABLE: "Tin so sánh Radar BDS",
    SourceKind.PRICE_HISTORY: "Lịch sử giá Radar BDS",
    SourceKind.LOT_HISTORY: "Lịch sử lô Radar BDS",
    SourceKind.MARKET_STAT: "Thống kê thị trường Radar BDS",
    SourceKind.OFFICIAL_PRICE: "Bảng giá đất chính thức",
    SourceKind.OFFICIAL_DOCUMENT: "Nguồn chính thức",
    SourceKind.RADAR_METHOD: "Phương pháp Radar BDS",
    SourceKind.EDITORIAL: "Tài liệu tham khảo Radar BDS",
}


def _source_kind(value: SourceKind | str) -> SourceKind:
    return value if isinstance(value, SourceKind) else SourceKind(value)


def _listing_id(source_ref: str, value: Any) -> int | None:
    for pattern in (DIRECT_LISTING_REF, LOT_LISTING_REF):
        match = pattern.match(source_ref)
        if match:
            listing_id = int(match.group(1))
            return listing_id if listing_id > 0 else None
    if isinstance(value, Mapping):
        listing_ref = value.get("listing_ref")
        if isinstance(listing_ref, str):
            match = DIRECT_LISTING_REF.match(listing_ref)
            if match:
                listing_id = int(match.group(1))
                return listing_id if listing_id > 0 else None
    return None


def _date_range(days: int) -> str:
    if days <= 7:
        return "1w"
    if days <= 31:
        return "1m"
    if days <= 92:
        return "3m"
    if days <= 183:
        return "6m"
    if days <= 366:
        return "1y"
    return "all"


def _safe_official_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
    ):
        return None
    return value


def _official_title(value: Any) -> str | None:
    if not isinstance(value, Mapping):
        return None
    for key in ("source_title", "document_title"):
        candidate = value.get(key)
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()[:160]
    return None


def source_card_details(
    *,
    source_kind: SourceKind | str,
    source_ref: str,
    value: Any = None,
    provenance: Mapping[str, str] | None = None,
    existing_title: str | None = None,
) -> tuple[str, str | None]:
    """Return a human label and URL derived only from trusted server metadata."""
    kind = _source_kind(source_kind)
    listing_id = _listing_id(source_ref, value)
    if listing_id is not None:
        if kind is SourceKind.VALUATION:
            title = f"Định giá Radar · tin #{listing_id}"
        elif kind is SourceKind.COMPARABLE:
            title = f"Tin so sánh Radar #{listing_id}"
        elif kind is SourceKind.PRICE_HISTORY:
            title = f"Lịch sử giá · tin #{listing_id}"
        elif kind is SourceKind.LOT_HISTORY:
            title = f"Lịch sử lô · tin #{listing_id}"
        else:
            title = f"Tin Radar #{listing_id}"
        return title, f"/listing/{listing_id}"

    market_match = WARD_MARKET_REF.match(source_ref)
    if kind is SourceKind.MARKET_STAT and market_match:
        ward = market_match.group(1).strip()
        days = int(market_match.group(2))
        if ward and days > 0:
            query = urlencode(
                (("tab", "all"), ("ward", ward), ("date_range", _date_range(days)))
            )
            return f"Thị trường {ward} · {days} ngày", f"/?{query}"

    budget_match = BUDGET_AREA_REF.match(source_ref)
    if kind is SourceKind.MARKET_STAT and budget_match:
        ward = budget_match.group(1).strip()
        if ward:
            query = urlencode((('tab', 'all'), ('ward', ward)))
            return f"Tin phù hợp ngân sách · {ward}", f"/?{query}"

    price_drop_match = PRICE_DROP_AREA_REF.match(source_ref)
    if kind is SourceKind.MARKET_STAT and price_drop_match:
        ward = price_drop_match.group(1).strip()
        days = int(price_drop_match.group(2))
        if ward and days > 0:
            query = urlencode(
                (
                    ("tab", "signals"),
                    ("ward", ward),
                    ("date_range", _date_range(days)),
                )
            )
            return f"Tín hiệu giảm giá · {ward} · {days} ngày", f"/?{query}"

    road_match = ROAD_MARKET_REF.match(source_ref)
    if kind is SourceKind.MARKET_STAT and road_match:
        ward = road_match.group(1).strip()
        road = road_match.group(2).strip()
        scope = road_match.group(3)
        days = int(road_match.group(4))
        if road and days > 0:
            query_parts = [("tab", "all")]
            if ward and ward != "unknown":
                query_parts.append(("ward", ward))
            query_parts.extend((("q", road), ("date_range", _date_range(days))))
            query = urlencode(query_parts)
            prefix = "Giá chào" if scope == "exact_road" else "Mẫu giá tham chiếu"
            title_scope = f" · {ward}" if ward and ward != "unknown" else ""
            return f"{prefix} {road}{title_scope} · {days} ngày", f"/?{query}"

    if kind is SourceKind.OFFICIAL_DOCUMENT:
        source_title = _official_title(value)
        title = "Nguồn chính thức"
        if source_title:
            title = f"{title} · {source_title}"
        href = _safe_official_url((provenance or {}).get("source_url"))
        return title, href

    generated_title = f"{kind.value}: {source_ref}"
    if existing_title and existing_title != generated_title:
        return existing_title, None
    return FRIENDLY_KIND_TITLES[kind], None
