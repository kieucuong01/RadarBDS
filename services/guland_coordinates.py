from __future__ import annotations

import math
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from config.listing_map import LISTING_MAP_BOUNDS
from services.listing_location_auto_registry import (
    point_is_in_legacy_compatibility_zone,
    point_is_in_scoped_ward,
)


_POST_ID_RE = re.compile(r"-(?P<post_id>\d+)(?:\.html)?$")


@dataclass(frozen=True)
class GulandCoordinateDecision:
    status: str
    reason: str = ""
    lat: float | None = None
    lng: float | None = None
    sanitized_url: str = ""


def normalize_guland_post_url(value: str) -> tuple[str, str] | None:
    try:
        parsed = urlsplit(str(value or "").strip())
        hostname = parsed.hostname
    except ValueError:
        return None
    if (
        parsed.scheme != "https"
        or hostname not in {"guland.vn", "www.guland.vn"}
        or not parsed.path.startswith("/post/")
    ):
        return None
    path = parsed.path.rstrip("/")
    match = _POST_ID_RE.search(path)
    if match is None:
        return None
    return f"https://guland.vn{path}", match.group("post_id")


def guland_identity_matches(
    card_url: str,
    target_url: str,
    card_post_id: str,
    target_source_id: str,
) -> bool:
    card = normalize_guland_post_url(card_url)
    target = normalize_guland_post_url(target_url)
    if card is None or target is None or card[0] != target[0]:
        return False
    card_id = str(card_post_id or card[1])
    target_id = str(target_source_id or target[1])
    return not card_id or not target_id or card_id == target_id


def _inside_service_bounds(lat: float, lng: float) -> bool:
    (south, west), (north, east) = LISTING_MAP_BOUNDS
    return south <= lat <= north and west <= lng <= east


def evaluate_guland_coordinate_url(
    source_url: str,
    *,
    city: str,
    ward: str,
    context_text: str = "",
) -> GulandCoordinateDecision:
    value = str(source_url or "").strip()
    if not value:
        return GulandCoordinateDecision("missing", "missing_coordinate_url")
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
    except ValueError:
        return GulandCoordinateDecision("invalid", "invalid_coordinate_url")
    if (
        parsed.scheme != "https"
        or hostname != "www.google.com"
        or parsed.path.rstrip("/") != "/maps/search"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        return GulandCoordinateDecision("invalid", "invalid_coordinate_url")
    params = parse_qs(parsed.query, keep_blank_values=True)
    if params.get("api") != ["1"] or len(params.get("query", [])) != 1:
        return GulandCoordinateDecision("invalid", "missing_coordinate_pair")
    parts = [part.strip() for part in params["query"][0].split(",")]
    if len(parts) != 2:
        return GulandCoordinateDecision("invalid", "missing_coordinate_pair")
    try:
        lat, lng = (float(parts[0]), float(parts[1]))
    except ValueError:
        return GulandCoordinateDecision("invalid", "invalid_number")
    if not math.isfinite(lat) or not math.isfinite(lng):
        return GulandCoordinateDecision("invalid", "invalid_number")
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return GulandCoordinateDecision("invalid", "invalid_lat_lng_order")
    if not _inside_service_bounds(lat, lng):
        return GulandCoordinateDecision("invalid", "outside_service_bounds")
    if not str(ward or "").strip():
        return GulandCoordinateDecision("invalid", "missing_canonical_ward")
    if not (
        point_is_in_scoped_ward(city, ward, lat, lng)
        or point_is_in_legacy_compatibility_zone(
            city,
            ward,
            lat,
            lng,
            context_text,
        )
    ):
        return GulandCoordinateDecision("invalid", "outside_canonical_ward")
    query = f"{lat:.7f},{lng:.7f}"
    sanitized = urlunsplit((
        "https",
        "www.google.com",
        "/maps/search/",
        urlencode({"api": "1", "query": query}),
        "",
    ))
    return GulandCoordinateDecision(
        "valid",
        lat=lat,
        lng=lng,
        sanitized_url=sanitized,
    )


def raw_coordinate_fields(
    decision: GulandCoordinateDecision,
    captured_at: str,
) -> dict[str, object]:
    if decision.status != "valid" or decision.lat is None or decision.lng is None:
        return {}
    return {
        "source_lat": decision.lat,
        "source_lng": decision.lng,
        "source_coordinate_url": decision.sanitized_url,
        "source_coordinate_provider": "guland_directions",
        "source_coordinate_captured_at": str(captured_at),
    }
