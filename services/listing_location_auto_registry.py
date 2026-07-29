"""Validate bounded browser evidence for automatic map registry suggestions."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
import hashlib
import json
import math
import re
from typing import Callable, Mapping
from urllib.parse import urlparse

from config.listing_map import (
    LISTING_MAP_AUTO_ACCEPT_THRESHOLD,
    LISTING_MAP_BOUNDS,
    LISTING_MAP_LEGACY_COMPATIBILITY_ZONES,
    LISTING_MAP_WARD_BOUNDARY_PATHS,
)
from shapely.geometry import Point, shape
from shapely.validation import make_valid
from services.listing_location_resolver import normalize_location_token


_GOOGLE_MAPS_HOSTS = frozenset({
    "google.com",
    "maps.google.com",
    "www.google.com",
})
_AT_COORDINATES_RE = re.compile(
    r"/@(?P<lat>-?\d+(?:\.\d+)?),(?P<lng>-?\d+(?:\.\d+)?)"
)
_DATA_COORDINATES_RE = re.compile(
    r"!3d(?P<lat>-?\d+(?:\.\d+)?).*?!4d(?P<lng>-?\d+(?:\.\d+)?)"
)
_CANDIDATE_KEY_RE = re.compile(
    r"^(?:road|landmark):[a-z0-9][a-z0-9:-]{2,239}$"
)
_HEX_64_RE = re.compile(r"^[a-f0-9]{64}$")
_ROAD_RESULT_TYPES = frozenset({"road", "route", "street"})
_LANDMARK_RESULT_TYPES = frozenset({
    "housing complex",
    "housing development",
    "neighborhood",
    "place",
    "residential area",
})


def _bounded_text(
    data: Mapping[str, object],
    field: str,
    *,
    maximum: int,
) -> str:
    value = data.get(field)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{field} must be text")
    value = value.strip()
    if len(value) > maximum:
        raise ValueError(f"{field} is too long")
    return value


@dataclass(frozen=True)
class BrowserLocationEvidence:
    candidate_key: str
    candidate_type: str
    city: str
    ward: str
    canonical: str
    aliases: tuple[str, ...]
    query: str
    result_title: str
    result_address: str
    result_type: str
    source_url: str
    unique_result: bool
    checked_at: str

    @classmethod
    def from_mapping(
        cls,
        data: Mapping[str, object],
    ) -> "BrowserLocationEvidence":
        if not isinstance(data, Mapping):
            raise ValueError("evidence item must be an object")
        candidate_type = _bounded_text(
            data,
            "candidate_type",
            maximum=16,
        ).lower()
        if candidate_type not in {"road", "landmark"}:
            raise ValueError("candidate_type must be road or landmark")

        raw_aliases = data.get("aliases") or ()
        if (
            isinstance(raw_aliases, (str, bytes))
            or not isinstance(raw_aliases, (list, tuple))
            or len(raw_aliases) > 20
        ):
            raise ValueError("aliases must be a list with at most 20 items")
        aliases = []
        for value in raw_aliases:
            if not isinstance(value, str):
                raise ValueError("aliases must contain text")
            value = value.strip()
            if not value or len(value) > 160:
                raise ValueError("aliases contain an invalid value")
            aliases.append(value)

        unique_result = data.get("unique_result")
        if not isinstance(unique_result, bool):
            raise ValueError("unique_result must be a boolean")

        evidence = cls(
            candidate_key=_bounded_text(
                data,
                "candidate_key",
                maximum=240,
            ),
            candidate_type=candidate_type,
            city=_bounded_text(data, "city", maximum=80),
            ward=_bounded_text(data, "ward", maximum=80),
            canonical=_bounded_text(data, "canonical", maximum=160),
            aliases=tuple(aliases),
            query=_bounded_text(data, "query", maximum=400),
            result_title=_bounded_text(
                data,
                "result_title",
                maximum=300,
            ),
            result_address=_bounded_text(
                data,
                "result_address",
                maximum=500,
            ),
            result_type=_bounded_text(
                data,
                "result_type",
                maximum=80,
            ),
            source_url=_bounded_text(
                data,
                "source_url",
                maximum=4096,
            ),
            unique_result=unique_result,
            checked_at=_bounded_text(
                data,
                "checked_at",
                maximum=40,
            ),
        )
        if (
            evidence.candidate_key
            and (
                not _CANDIDATE_KEY_RE.fullmatch(evidence.candidate_key)
                or not evidence.candidate_key.startswith(
                    f"{candidate_type}:"
                )
            )
        ):
            raise ValueError("candidate_key is invalid")
        return evidence


@dataclass(frozen=True)
class AutoRegistryDecision:
    status: str
    confidence: float
    reasons: tuple[str, ...]
    override: Mapping[str, object] | None


def _inside_service_bounds(lat: float, lng: float) -> bool:
    (south, west), (north, east) = LISTING_MAP_BOUNDS
    return south <= lat <= north and west <= lng <= east


@lru_cache(maxsize=1)
def _ward_boundaries() -> Mapping[tuple[str, str], object]:
    boundaries = {}
    for path in LISTING_MAP_WARD_BOUNDARY_PATHS:
        payload = json.loads(path.read_text(encoding="utf-8"))
        city = str(payload.get("city") or "").strip()
        if not city:
            path_token = normalize_location_token(path.stem)
            if "thu dau mot" in path_token:
                city = "THỦ DẦU MỘT"
            elif "ben cat" in path_token:
                city = "BẾN CÁT"
        if not city:
            raise ValueError(f"ward boundary city is missing for {path}")
        for feature in payload.get("features") or ():
            properties = feature.get("properties") or {}
            ward = str(properties.get("name") or "").strip()
            geometry_payload = feature.get("geometry")
            if not ward or not geometry_payload:
                raise ValueError(f"invalid ward boundary in {path}")
            geometry = shape(geometry_payload)
            if not geometry.is_valid:
                geometry = make_valid(geometry)
            if geometry.is_empty:
                raise ValueError(f"empty ward boundary for {ward}")
            key = (
                normalize_location_token(city),
                normalize_location_token(ward),
            )
            if key in boundaries:
                raise ValueError(f"duplicate ward boundary for {city}/{ward}")
            boundaries[key] = geometry
    return boundaries


def point_is_in_scoped_ward(
    city: str,
    ward: str,
    lat: float,
    lng: float,
) -> bool:
    if not _inside_service_bounds(float(lat), float(lng)):
        return False
    boundary = _ward_boundaries().get((
        normalize_location_token(city),
        normalize_location_token(ward),
    ))
    return bool(boundary and boundary.covers(Point(float(lng), float(lat))))


def legacy_compatibility_reason(
    evidence: BrowserLocationEvidence,
    lat: float,
    lng: float,
) -> str:
    normalized_city = normalize_location_token(evidence.city)
    normalized_ward = normalize_location_token(evidence.ward)
    normalized_context = normalize_location_token(
        " ".join((
            evidence.canonical,
            evidence.query,
            evidence.result_address,
        ))
    )
    normalized_address = normalize_location_token(evidence.result_address)
    for zone in LISTING_MAP_LEGACY_COMPATIBILITY_ZONES:
        token = normalize_location_token(zone["landmark_token"])
        if (
            normalized_city != normalize_location_token(zone["city"])
            or normalized_ward != normalize_location_token(zone["ward"])
            or token not in normalized_context
            or token not in normalized_address
        ):
            continue
        (south, west), (north, east) = zone["bounds"]
        if south <= lat <= north and west <= lng <= east:
            return str(zone["reason"])
    return ""


def parse_google_maps_coordinates(url: str) -> tuple[float, float] | None:
    """Return bounded public Google Maps coordinates without fetching the URL."""
    try:
        parsed = urlparse(str(url or "").strip())
    except ValueError:
        return None
    if parsed.scheme != "https" or parsed.hostname not in _GOOGLE_MAPS_HOSTS:
        return None
    target = parsed.path
    if parsed.query:
        target += f"?{parsed.query}"
    for pattern in (_DATA_COORDINATES_RE, _AT_COORDINATES_RE):
        match = pattern.search(target)
        if not match:
            continue
        try:
            lat = float(match.group("lat"))
            lng = float(match.group("lng"))
        except (TypeError, ValueError):
            continue
        if (
            math.isfinite(lat)
            and math.isfinite(lng)
            and _inside_service_bounds(lat, lng)
        ):
            return lat, lng
    return None


def canonical_evidence_hash(evidence: BrowserLocationEvidence) -> str:
    payload = {
        "aliases": sorted(evidence.aliases),
        "candidate_key": evidence.candidate_key,
        "candidate_type": evidence.candidate_type,
        "canonical": evidence.canonical,
        "checked_at": evidence.checked_at,
        "city": evidence.city,
        "query": evidence.query,
        "result_address": evidence.result_address,
        "result_title": evidence.result_title,
        "result_type": evidence.result_type,
        "source_url": evidence.source_url,
        "unique_result": evidence.unique_result,
        "ward": evidence.ward,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _contains_normalized(haystack: str, needle: str) -> bool:
    normalized_haystack = normalize_location_token(haystack)
    normalized_needle = normalize_location_token(needle)
    if not normalized_needle:
        return False
    return f" {normalized_needle} " in f" {normalized_haystack} "


def _valid_checked_at(value: str) -> bool:
    if not value:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _complete_evidence(evidence: BrowserLocationEvidence) -> bool:
    required = (
        evidence.candidate_key,
        evidence.city,
        evidence.ward,
        evidence.canonical,
        evidence.query,
        evidence.result_title,
        evidence.result_address,
        evidence.result_type,
        evidence.source_url,
    )
    return all(required) and _valid_checked_at(evidence.checked_at)


def _title_matches(evidence: BrowserLocationEvidence) -> bool:
    title = normalize_location_token(evidence.result_title)
    accepted = {
        normalize_location_token(value)
        for value in (evidence.canonical, *evidence.aliases)
        if normalize_location_token(value)
    }
    return bool(title and title in accepted)


def _result_type_matches(evidence: BrowserLocationEvidence) -> bool:
    normalized = normalize_location_token(evidence.result_type)
    allowed = (
        _ROAD_RESULT_TYPES
        if evidence.candidate_type == "road"
        else _LANDMARK_RESULT_TYPES
    )
    return normalized in allowed


def _candidate_identity_matches(evidence: BrowserLocationEvidence) -> bool:
    slug = lambda value: normalize_location_token(value).replace(" ", "-")
    expected = (
        f"{evidence.candidate_type}:"
        f"{slug(evidence.city)}:"
        f"{slug(evidence.ward)}:"
        f"{slug(evidence.canonical)}"
    )
    return (
        evidence.candidate_key == expected
        or evidence.candidate_key.startswith(f"{expected}:")
    )


def evaluate_browser_evidence(
    evidence: BrowserLocationEvidence,
    *,
    manual_keys: frozenset[str] | set[str],
    ward_contains: Callable[[str, str, float, float], bool],
) -> AutoRegistryDecision:
    """Quarantine any observation that does not pass every deterministic gate."""
    reasons = []
    if not evidence.unique_result:
        reasons.append("multiple_or_unselected_result")
    if not _complete_evidence(evidence):
        reasons.append("missing_evidence")

    coordinates = parse_google_maps_coordinates(evidence.source_url)
    if coordinates is None:
        reasons.append("invalid_source_url")
    if not _title_matches(evidence):
        reasons.append("title_mismatch")
    if not _result_type_matches(evidence):
        reasons.append("invalid_result_type")
    if not _candidate_identity_matches(evidence):
        reasons.append("candidate_identity_mismatch")

    ward_inside = False
    if coordinates is not None:
        try:
            ward_inside = bool(
                ward_contains(
                    evidence.city,
                    evidence.ward,
                    coordinates[0],
                    coordinates[1],
                )
            )
        except Exception:
            ward_inside = False
    address_has_ward = _contains_normalized(
        evidence.result_address,
        evidence.ward,
    )
    compatibility_reason = (
        legacy_compatibility_reason(
            evidence,
            coordinates[0],
            coordinates[1],
        )
        if coordinates is not None
        else ""
    )
    if not ward_inside and not address_has_ward and not compatibility_reason:
        reasons.append("ward_mismatch")

    base_candidate_key = ":".join(evidence.candidate_key.split(":")[:4])
    if (
        evidence.candidate_key in manual_keys
        or base_candidate_key in manual_keys
    ):
        reasons.append("manual_override_conflict")

    if evidence.candidate_type == "road":
        canonical = normalize_location_token(evidence.canonical)
        is_numbered = bool(re.search(r"\b\d+\b", canonical))
        has_scoped_key = evidence.candidate_key.count(":") >= 4
        if (
            is_numbered
            and not ward_inside
            and not address_has_ward
            and not has_scoped_key
        ):
            reasons.append("numbered_road_missing_scope")

    if reasons:
        return AutoRegistryDecision(
            status="quarantined",
            confidence=0.0,
            reasons=tuple(dict.fromkeys(reasons)),
            override=None,
        )

    confidence = round(0.50 + 0.20 + 0.15 + 0.10 + 0.05, 2)
    if confidence < LISTING_MAP_AUTO_ACCEPT_THRESHOLD:
        return AutoRegistryDecision(
            status="quarantined",
            confidence=confidence,
            reasons=("confidence_below_threshold",),
            override=None,
        )

    lat, lng = coordinates
    override = {
        "accuracy_radius_m": (
            90.0 if evidence.candidate_type == "road" else 140.0
        ),
        "aliases": sorted(set(evidence.aliases)),
        "candidate_key": evidence.candidate_key,
        "candidate_type": evidence.candidate_type,
        "canonical": evidence.canonical,
        "checked_at": evidence.checked_at,
        "city": evidence.city,
        "confidence": confidence,
        "evidence_hash": canonical_evidence_hash(evidence),
        "lat": lat,
        "lng": lng,
        "query": evidence.query,
        "result_address": evidence.result_address,
        "result_title": evidence.result_title,
        "result_type": evidence.result_type,
        "source": "Google Maps browser suggestion",
        "source_url": evidence.source_url,
        "status": "accepted",
        "unique_result": evidence.unique_result,
        "ward": evidence.ward,
    }
    if compatibility_reason:
        override["allow_boundary_mismatch"] = True
        override["boundary_mismatch_reason"] = compatibility_reason
    assert _HEX_64_RE.fullmatch(str(override["evidence_hash"]))
    return AutoRegistryDecision(
        status="accepted",
        confidence=confidence,
        reasons=(),
        override=override,
    )
