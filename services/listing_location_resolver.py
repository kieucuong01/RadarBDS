from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import unicodedata
from typing import Mapping

from config.listing_map import (
    LISTING_MAP_BOUNDS,
    LISTING_MAP_ROAD_REGISTRY_PATH,
    LISTING_MAP_WARD_REGISTRY_PATH,
)


_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalize_location_token(value: str) -> str:
    folded = unicodedata.normalize("NFD", str(value or "").strip().lower())
    ascii_text = "".join(
        character
        for character in folded.replace("đ", "d")
        if unicodedata.category(character) != "Mn"
    )
    return " ".join(_NON_ALNUM.sub(" ", ascii_text).split())


def normalize_road_token(value: str) -> str:
    normalized = normalize_location_token(value)
    normalized = re.sub(r"(?<=[a-z])(?=\d)|(?<=\d)(?=[a-z])", " ", normalized)
    normalized = " ".join(normalized.split())
    if re.match(r"^duong (?:dx|d|db|dh|dt|ql|n|ng|ni|na|nb) \d", normalized):
        normalized = normalized.removeprefix("duong ")
    normalized = re.sub(
        r"^(?P<prefix>(?:dx|d|db|dh|dt|ql|n|ng|ni|na|nb)\s+)0+(?=\d)",
        r"\g<prefix>",
        normalized,
    )
    normalized = re.sub(r"^(duong so\s+)0+(?=\d)", r"\1", normalized)
    return normalized


def _slug(value: str) -> str:
    return normalize_location_token(value).replace(" ", "-")


def _value(listing: Mapping, key: str, default=None):
    try:
        return listing.get(key, default)
    except AttributeError:
        try:
            return listing[key]
        except (KeyError, TypeError):
            return default


def _canonical_city(listing: Mapping) -> str:
    raw_city = str(_value(listing, "city", "") or "").strip()
    ward = str(_value(listing, "ward", "") or "").strip()
    try:
        from services.market_data import CITY_MAP, get_city_for_ward

        normalized_city = normalize_location_token(raw_city)
        for city in CITY_MAP:
            if normalize_location_token(city) == normalized_city:
                return city
        inferred = get_city_for_ward(ward)
        if inferred:
            return inferred
    except ImportError:
        pass
    return raw_city.upper()


def _float(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def _inside_service_bounds(lat: float, lng: float) -> bool:
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return False
    (south, west), (north, east) = LISTING_MAP_BOUNDS
    return south <= lat <= north and west <= lng <= east


def _source_point(listing: Mapping) -> tuple[float, float] | None:
    lat = _float(_value(listing, "source_lat"))
    lng = _float(_value(listing, "source_lng"))
    if lat is None or lng is None or not _inside_service_bounds(lat, lng):
        return None
    return lat, lng


def listing_location_signature(listing: Mapping) -> str:
    source_point = _source_point(listing)
    if source_point is not None:
        raw = f"exact|{source_point[0]:.7f}|{source_point[1]:.7f}"
    else:
        raw = "|".join(
            (
                normalize_location_token(_canonical_city(listing)),
                normalize_location_token(_value(listing, "ward", "")),
                normalize_road_token(_value(listing, "road_name", "")),
            )
        )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class LocationRegistry:
    resolver_version: str
    roads: Mapping[tuple[str, str, str], Mapping[str, object]]
    wards: Mapping[tuple[str, str], Mapping[str, object]]


@dataclass(frozen=True)
class ResolvedLocation:
    listing_id: int
    lat: float
    lng: float
    precision: str
    location_key: str
    location_label: str
    source: str
    resolver_version: str
    signature: str


def _resolved_from_entry(
    *,
    listing_id: int,
    precision: str,
    location_key: str,
    entry: Mapping[str, object],
    resolver_version: str,
    signature: str,
) -> ResolvedLocation | None:
    lat = _float(entry.get("lat"))
    lng = _float(entry.get("lng"))
    if lat is None or lng is None or not _inside_service_bounds(lat, lng):
        return None
    return ResolvedLocation(
        listing_id=listing_id,
        lat=lat,
        lng=lng,
        precision=precision,
        location_key=location_key,
        location_label=str(entry.get("label") or ""),
        source=str(entry.get("source") or "OpenStreetMap"),
        resolver_version=resolver_version,
        signature=signature,
    )


def resolve_listing_location(
    listing: Mapping,
    registry: LocationRegistry,
) -> ResolvedLocation | None:
    try:
        listing_id = int(_value(listing, "id"))
    except (TypeError, ValueError):
        return None

    signature = listing_location_signature(listing)
    source_point = _source_point(listing)
    if source_point is not None:
        return ResolvedLocation(
            listing_id=listing_id,
            lat=source_point[0],
            lng=source_point[1],
            precision="exact",
            location_key=f"exact:{listing_id}",
            location_label="Vị trí chính xác từ tin rao",
            source=str(_value(listing, "source", "") or "Tin rao"),
            resolver_version=registry.resolver_version,
            signature=signature,
        )

    city = _canonical_city(listing)
    ward = normalize_location_token(_value(listing, "ward", ""))
    road = normalize_road_token(_value(listing, "road_name", ""))
    if not city or not ward:
        return None

    if road:
        entry = registry.roads.get((city, ward, road))
        if entry:
            resolved = _resolved_from_entry(
                listing_id=listing_id,
                precision="road",
                location_key=f"road:{_slug(city)}:{_slug(ward)}:{_slug(road)}",
                entry=entry,
                resolver_version=registry.resolver_version,
                signature=signature,
            )
            if resolved:
                return resolved

    entry = registry.wards.get((city, ward))
    if not entry:
        return None
    return _resolved_from_entry(
        listing_id=listing_id,
        precision="ward",
        location_key=f"ward:{_slug(city)}:{_slug(ward)}",
        entry=entry,
        resolver_version=registry.resolver_version,
        signature=signature,
    )


def load_location_registry(
    *,
    ward_path: Path = LISTING_MAP_WARD_REGISTRY_PATH,
    road_path: Path = LISTING_MAP_ROAD_REGISTRY_PATH,
) -> LocationRegistry:
    ward_payload = json.loads(ward_path.read_text(encoding="utf-8"))
    road_payload = json.loads(road_path.read_text(encoding="utf-8"))
    ward_version = str(ward_payload.get("resolver_version") or "")
    road_version = str(road_payload.get("resolver_version") or "")
    if not ward_version or ward_version != road_version:
        raise ValueError("listing location registry versions do not match")

    wards = {
        (
            str(item["city"]),
            str(item["normalized_ward"]),
        ): item
        for item in ward_payload.get("wards") or []
    }
    roads = {
        (
            str(item["city"]),
            str(item["normalized_ward"]),
            str(item["normalized_road"]),
        ): item
        for item in road_payload.get("roads") or []
    }
    return LocationRegistry(ward_version, roads, wards)
