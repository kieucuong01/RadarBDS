from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import re
import unicodedata
from typing import Mapping, TYPE_CHECKING

from config.listing_map import (
    LISTING_MAP_BOUNDS,
    LISTING_MAP_LANDMARK_REGISTRY_PATH,
    LISTING_MAP_ROAD_REGISTRY_PATH,
    LISTING_MAP_WARD_ALIASES,
    LISTING_MAP_WARD_REGISTRY_PATH,
)

if TYPE_CHECKING:
    from services.listing_map_context import MapLocationContext


_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_TEXT_COORDINATE_RE = re.compile(
    r"\b(?:vị\s*trí|vi\s*tri|tọa\s*độ|toa\s*do)\s*[:=-]?\s*"
    r"(?P<lat>1[01]\.[0-9]{4,8})\s*[,;]\s*"
    r"(?P<lng>106\.[0-9]{4,8})\b",
    re.IGNORECASE,
)
_REGISTRY_SHORT_NUMBERED_ROAD_RE = re.compile(
    r"^(?:d|da|db|dc|n|na|r|x|c)\s+\d{1,3}[a-z]?$"
)
_REGISTRY_ROAD_CONTEXT_RE = re.compile(
    r"(?:\bduong|\bmat tien|\bmt|\bhem|\bkdc|\btdc)\s*(?:so\s*)?$"
)


def normalize_location_token(value: str) -> str:
    raw = (
        str(value or "")
        .strip()
        .replace("Đ", "D")
        .replace("đ", "d")
        .replace("Ð", "D")
        .replace("ð", "d")
    )
    folded = unicodedata.normalize("NFD", raw.lower())
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
    if normalized in {
        "30 4",
        "30 thang 4",
        "duong 30 4",
        "duong 30 thang 4",
        "duong so 30 4",
        "duong so 30 thang 4",
    }:
        return "duong so 30 thang 4"
    bare_number_letter = re.match(r"^(\d{1,4})\s+([a-z])$", normalized)
    if bare_number_letter and bare_number_letter.group(2) != "m":
        normalized = f"duong so {normalized}"
    road_code_prefixes = (
        "dx|da|d|db|de|df|dg|dh|di|dt|ql|kh|ki|kj|kk|n|ng|ni|na|"
        "nb|ne|nf|nh|nj|nk|nl|dj|dk|tc|xe|xh|xj|gs"
    )
    if re.match(rf"^duong (?:{road_code_prefixes}) \d", normalized):
        normalized = normalized.removeprefix("duong ")
    normalized = re.sub(r"^duong (?=\d)", "duong so ", normalized)
    normalized = re.sub(
        rf"^(?P<prefix>(?:{road_code_prefixes})\s+)0+(?=\d)",
        r"\g<prefix>",
        normalized,
    )
    normalized = re.sub(r"^(duong so\s+)0+(?=\d)", r"\1", normalized)
    return normalized


def _slug(value: str) -> str:
    return normalize_location_token(value).replace(" ", "-")


def _road_location_key(
    city: str,
    ward: str,
    road: str,
    landmark: str = "",
) -> str:
    key = f"road:{_slug(city)}:{_slug(ward)}:{_slug(road)}"
    if landmark:
        key += f":{_slug(landmark)}"
    return key


def _entry_road_key(entry: Mapping[str, object], fallback: str) -> str:
    canonical = normalize_road_token(str(entry.get("normalized_road") or ""))
    return canonical or fallback


def _entry_landmark_key(entry: Mapping[str, object], fallback: str) -> str:
    canonical = normalize_location_token(
        str(entry.get("normalized_landmark") or "")
    )
    return canonical or fallback


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
    ward_token = normalize_location_token(ward)
    try:
        from services.market_data import CITY_MAP, get_city_for_ward

        normalized_city = normalize_location_token(raw_city)
        for city in CITY_MAP:
            if normalize_location_token(city) == normalized_city:
                return city
        for (alias_city, alias_ward), _canonical_ward in LISTING_MAP_WARD_ALIASES.items():
            if ward_token == alias_ward:
                return alias_city
        inferred = get_city_for_ward(ward)
        if inferred:
            return inferred
    except ImportError:
        pass
    for (alias_city, alias_ward), _canonical_ward in LISTING_MAP_WARD_ALIASES.items():
        if ward_token == alias_ward:
            return alias_city
    return raw_city.upper()


def _canonical_map_ward(city: str, ward: str) -> str:
    normalized_ward = normalize_location_token(ward)
    return LISTING_MAP_WARD_ALIASES.get((city, normalized_ward), ward)


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
    if lat is not None and lng is not None and _inside_service_bounds(lat, lng):
        return lat, lng
    for key in ("title", "description"):
        match = _TEXT_COORDINATE_RE.search(str(_value(listing, key, "") or ""))
        if not match:
            continue
        lat = _float(match.group("lat"))
        lng = _float(match.group("lng"))
        if lat is not None and lng is not None and _inside_service_bounds(lat, lng):
            return lat, lng
    return None


def listing_location_signature(
    listing: Mapping,
    context: "MapLocationContext | None" = None,
    resolver_version: str = "",
) -> str:
    source_point = _source_point(listing)
    if source_point is not None:
        raw = (
            f"{resolver_version}|exact|"
            f"{source_point[0]:.7f}|{source_point[1]:.7f}"
        )
    else:
        distance = _float(getattr(context, "distance_m", None))
        raw = "|".join(
            (
                resolver_version,
                normalize_location_token(_canonical_city(listing)),
                normalize_location_token(_value(listing, "ward", "")),
                normalize_road_token(_value(listing, "road_name", "")),
                normalize_road_token(getattr(context, "direct_road", "")),
                normalize_road_token(getattr(context, "nearby_road", "")),
                normalize_location_token(getattr(context, "landmark", "")),
                normalize_location_token(getattr(context, "ward_hint", "")),
                normalize_location_token(getattr(context, "relation", "")),
                "" if distance is None else f"{distance:.1f}",
            )
        )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class LocationRegistry:
    resolver_version: str
    roads: Mapping[
        tuple[str, str, str],
        tuple[Mapping[str, object], ...],
    ]
    landmarks: Mapping[
        tuple[str, str, str],
        Mapping[str, object] | tuple[Mapping[str, object], ...],
    ]
    wards: Mapping[tuple[str, str], Mapping[str, object]]
    road_text_aliases: Mapping[
        tuple[str, str],
        Mapping[str, tuple[Mapping[str, object], ...]],
    ] = field(default_factory=dict)


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
    accuracy_radius_m: float | None = None
    relation: str = ""
    reference_road: str = ""
    landmark_key: str = ""
    resolution_status: str = "resolved"
    resolution_reason: str = ""


@dataclass(frozen=True)
class ResolutionIssue:
    listing_id: int
    candidate_key: str
    city: str
    ward: str
    road_candidate: str
    landmark_candidate: str
    relation: str
    status: str
    resolution_note: str


@dataclass(frozen=True)
class LocationResolution:
    location: ResolvedLocation | None
    issue: ResolutionIssue | None


def _resolved_from_entry(
    *,
    listing_id: int,
    precision: str,
    location_key: str,
    entry: Mapping[str, object],
    resolver_version: str,
    signature: str,
    accuracy_radius_m: float | None = None,
    relation: str = "",
    reference_road: str = "",
    landmark_key: str = "",
    resolution_status: str = "resolved",
    resolution_reason: str = "",
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
        accuracy_radius_m=(
            _float(accuracy_radius_m)
            if accuracy_radius_m is not None
            else _float(entry.get("accuracy_radius_m"))
        ),
        relation=relation,
        reference_road=reference_road,
        landmark_key=landmark_key,
        resolution_status=resolution_status,
        resolution_reason=resolution_reason,
    )


def _road_scopes(
    city: str,
    ward: str,
    registry: LocationRegistry,
) -> tuple[str, ...]:
    normalized_ward = normalize_location_token(_canonical_map_ward(city, ward))
    scopes = [normalized_ward]
    ward_entry = registry.wards.get((city, normalized_ward)) or {}
    raw_parents = ward_entry.get("road_scope_parents")
    if isinstance(raw_parents, (list, tuple)):
        parents = raw_parents
    else:
        parents = (
            ward_entry.get("road_scope_parent")
            or ward_entry.get("fallback_parent")
            or "",
        )
    for raw_parent in parents:
        parent = normalize_location_token(raw_parent)
        if parent and parent not in scopes:
            scopes.append(parent)
    return tuple(scopes)


def _unique_registry_road_from_text(
    city: str,
    wards: tuple[str, ...],
    raw_text: str,
    registry: LocationRegistry,
) -> str:
    """Return one resolvable scoped road named in otherwise unparsed text."""
    text = normalize_road_token(raw_text)
    if not text:
        return ""
    normalized_ward_names = {
        normalize_road_token(_canonical_map_ward(city, ward))
        for ward in wards
    }
    matched_canonicals: set[str] = set()
    allowed_scopes = {
        scope
        for ward in wards
        for scope in _road_scopes(city, ward, registry)
    }
    scoped_aliases: dict[str, tuple[Mapping[str, object], ...]] = {}
    for scope in allowed_scopes:
        cached = registry.road_text_aliases.get((city, scope))
        if cached is not None:
            scoped_aliases.update(cached)
            continue
        scoped_aliases.update(
            {
                raw_alias: entries
            for (entry_city, entry_ward, raw_alias), entries in registry.roads.items()
            if entry_city == city and entry_ward == scope
            }
        )
    if not scoped_aliases:
        return ""
    tokens = text.split()
    alias_lengths = {
        len(alias.split()) for alias in scoped_aliases if alias
    }
    text_phrases = {
        " ".join(tokens[index : index + length])
        for length in alias_lengths
        for index in range(0, len(tokens) - length + 1)
    }
    for alias in text_phrases.intersection(scoped_aliases):
        # Some legacy wards share their name with a registry road alias (for
        # example "Tân Định"). A bare ward mention is location context, not
        # enough evidence to promote a listing to road precision.
        if alias in normalized_ward_names:
            continue
        entries = scoped_aliases[alias]
        aggregate_count = sum(
            1 for entry in entries if bool(entry.get("aggregate"))
        )
        if len(entries) != 1 and aggregate_count != 1:
            continue
        if _REGISTRY_SHORT_NUMBERED_ROAD_RE.fullmatch(alias):
            match = re.search(
                rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])",
                text,
            )
            if not match or not _REGISTRY_ROAD_CONTEXT_RE.search(
                text[max(0, match.start() - 24) : match.start()]
            ):
                continue
        canonicals = {
            _entry_road_key(entry, alias) for entry in entries
        }
        if len(canonicals) == 1:
            matched_canonicals.update(canonicals)
    if len(matched_canonicals) == 1:
        return next(iter(matched_canonicals))
    return ""


def _landmark_scopes(
    city: str,
    ward: str,
    registry: LocationRegistry,
) -> tuple[str, ...]:
    """Return explicitly configured subzone scopes without widening roads."""
    normalized_ward = normalize_location_token(_canonical_map_ward(city, ward))
    scopes = [normalized_ward]
    ward_entry = registry.wards.get((city, normalized_ward)) or {}
    raw_parents = ward_entry.get("landmark_scope_parents")
    if isinstance(raw_parents, (list, tuple)):
        parents = raw_parents
    else:
        parents = (ward_entry.get("landmark_scope_parent") or "",)
    for raw_parent in parents:
        parent = normalize_location_token(raw_parent)
        if parent and parent not in scopes:
            scopes.append(parent)
    for road_scope in _road_scopes(city, ward, registry):
        if road_scope not in scopes:
            scopes.append(road_scope)
    return tuple(scopes)


def _match_landmark(
    city: str,
    ward: str,
    normalized_landmark: str,
    registry: LocationRegistry,
) -> Mapping[str, object] | str | None:
    if not normalized_landmark:
        return None
    for scope in _landmark_scopes(city, ward, registry):
        matched = registry.landmarks.get((city, scope, normalized_landmark))
        if isinstance(matched, Mapping):
            return matched
        candidates = tuple(matched or ())
        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            return "ambiguous"
    return None


def _match_road(
    city: str,
    ward: str,
    normalized_road: str,
    landmark_key: str,
    registry: LocationRegistry,
) -> Mapping[str, object] | str | None:
    road_candidates = [normalized_road]
    if normalized_road.startswith("duong "):
        without_prefix = normalized_road.removeprefix("duong ")
        if without_prefix and all(
            token.isalpha() for token in without_prefix.split()
        ):
            road_candidates.append(without_prefix)
    elif normalized_road and all(
        token.isalpha() for token in normalized_road.split()
    ):
        road_candidates.append(f"duong {normalized_road}")

    for scope in _road_scopes(city, ward, registry):
        for road_candidate in road_candidates:
            entries = list(
                registry.roads.get((city, scope, road_candidate), ())
            )
            if not entries:
                continue
            if landmark_key:
                scoped = [
                    item
                    for item in entries
                    if landmark_key
                    in tuple(
                        normalize_location_token(value)
                        for value in (item.get("landmark_keys") or ())
                    )
                ]
                if len(scoped) == 1:
                    return scoped[0]
                if len(scoped) > 1:
                    return "ambiguous"
            if len(entries) == 1:
                return entries[0]
            aggregate_entries = [
                entry for entry in entries if bool(entry.get("aggregate"))
            ]
            if len(aggregate_entries) == 1:
                return aggregate_entries[0]
            return "ambiguous"
    return None


def _lookup_ward_labels(
    city: str,
    stored_ward: str,
    context: "MapLocationContext | None",
    registry: LocationRegistry,
) -> tuple[str, ...]:
    """Prefer an explicit legacy ward clue while retaining stored fallback."""
    labels: list[str] = []
    ward_hint = str(getattr(context, "ward_hint", "") or "").strip()
    if ward_hint:
        canonical_hint = _canonical_map_ward(city, ward_hint)
        hint_key = normalize_location_token(canonical_hint)
        if (city, hint_key) in registry.wards:
            labels.append(canonical_hint)
    if stored_ward not in labels:
        labels.append(stored_ward)
    return tuple(labels)


def _match_landmark_in_wards(
    city: str,
    wards: tuple[str, ...],
    normalized_landmark: str,
    registry: LocationRegistry,
) -> Mapping[str, object] | str | None:
    for ward in wards:
        match = _match_landmark(city, ward, normalized_landmark, registry)
        if match is not None:
            return match
    return None


def _match_road_in_wards(
    city: str,
    wards: tuple[str, ...],
    normalized_road: str,
    landmark_key: str,
    registry: LocationRegistry,
) -> Mapping[str, object] | str | None:
    for ward in wards:
        match = _match_road(
            city,
            ward,
            normalized_road,
            landmark_key,
            registry,
        )
        if match is not None:
            return match
    return None


def _ward_fallback(
    *,
    listing_id: int,
    city: str,
    ward: str,
    registry: LocationRegistry,
    signature: str,
    status: str = "resolved",
    reason: str = "",
) -> ResolvedLocation | None:
    normalized_ward = normalize_location_token(_canonical_map_ward(city, ward))
    entry = registry.wards.get((city, normalized_ward))
    if not entry:
        return None
    fallback_landmark = normalize_location_token(
        str(entry.get("fallback_landmark") or "")
    )
    landmark_match = _match_landmark(
        city,
        ward,
        fallback_landmark,
        registry,
    )
    if isinstance(landmark_match, Mapping):
        canonical_landmark = _entry_landmark_key(
            landmark_match,
            fallback_landmark,
        )
        return _resolved_from_entry(
            listing_id=listing_id,
            precision="landmark",
            location_key=(
                f"landmark:{_slug(city)}:{_slug(normalized_ward)}:"
                f"{_slug(canonical_landmark)}"
            ),
            entry=landmark_match,
            resolver_version=registry.resolver_version,
            signature=signature,
            relation="at",
            landmark_key=canonical_landmark,
            resolution_status=status,
            resolution_reason=reason,
        )
    return _resolved_from_entry(
        listing_id=listing_id,
        precision="ward",
        location_key=f"ward:{_slug(city)}:{_slug(normalized_ward)}",
        entry=entry,
        resolver_version=registry.resolver_version,
        signature=signature,
        resolution_status=status,
        resolution_reason=reason,
    )


def _issue(
    *,
    listing_id: int,
    city: str,
    ward: str,
    road: str,
    landmark: str,
    relation: str,
    status: str,
    reason: str,
) -> ResolutionIssue:
    candidate = road or landmark or normalize_location_token(ward) or "unknown"
    kind = "road" if road else ("landmark" if landmark else "ward")
    return ResolutionIssue(
        listing_id=listing_id,
        candidate_key=f"{kind}:{_slug(city)}:{_slug(ward)}:{_slug(candidate)}",
        city=city,
        ward=ward,
        road_candidate=road,
        landmark_candidate=landmark,
        relation=relation,
        status=status,
        resolution_note=reason,
    )


def _fallback_with_issue(
    *,
    listing_id: int,
    city: str,
    ward: str,
    road: str,
    landmark: str,
    relation: str,
    status: str,
    reason: str,
    registry: LocationRegistry,
    signature: str,
) -> LocationResolution:
    issue = _issue(
        listing_id=listing_id,
        city=city,
        ward=ward,
        road=road,
        landmark=landmark,
        relation=relation,
        status=status,
        reason=reason,
    )
    return LocationResolution(
        location=_ward_fallback(
            listing_id=listing_id,
            city=city,
            ward=ward,
            registry=registry,
            signature=signature,
            status=status,
            reason=reason,
        ),
        issue=issue,
    )


def resolve_listing_location(
    listing: Mapping,
    registry: LocationRegistry,
    context: "MapLocationContext | None" = None,
) -> LocationResolution:
    try:
        listing_id = int(_value(listing, "id"))
    except (TypeError, ValueError):
        return LocationResolution(
            location=None,
            issue=_issue(
                listing_id=0,
                city=_canonical_city(listing),
                ward=str(_value(listing, "ward", "") or ""),
                road="",
                landmark="",
                relation="",
                status="invalid",
                reason="invalid_listing_id",
            ),
        )

    signature = listing_location_signature(
        listing,
        context,
        registry.resolver_version,
    )
    source_point = _source_point(listing)
    if source_point is not None:
        return LocationResolution(
            location=ResolvedLocation(
                listing_id=listing_id,
                lat=source_point[0],
                lng=source_point[1],
                precision="exact",
                location_key=f"exact:{listing_id}",
                location_label="Vị trí chính xác từ tin rao",
                source=str(_value(listing, "source", "") or "Tin rao"),
                resolver_version=registry.resolver_version,
                signature=signature,
                accuracy_radius_m=0.0,
                relation="on",
            ),
            issue=None,
        )

    city = _canonical_city(listing)
    ward_label = str(_value(listing, "ward", "") or "").strip()
    map_ward_label = _canonical_map_ward(city, ward_label)
    ward = normalize_location_token(map_ward_label)
    lookup_ward_labels = _lookup_ward_labels(
        city,
        map_ward_label,
        context,
        registry,
    )
    raw_stored_road = normalize_road_token(_value(listing, "road_name", ""))
    context_stored_road = getattr(context, "stored_road", None)
    validated_stored_roads: list[str] = []
    if context_stored_road is None:
        if raw_stored_road:
            validated_stored_roads.append(raw_stored_road)
    else:
        normalized_context_stored = normalize_road_token(context_stored_road)
        if normalized_context_stored:
            validated_stored_roads.append(normalized_context_stored)
        if (
            raw_stored_road
            and raw_stored_road not in validated_stored_roads
            and isinstance(
                _match_road_in_wards(
                    city,
                    lookup_ward_labels,
                    raw_stored_road,
                    "",
                    registry,
                ),
                Mapping,
            )
        ):
            validated_stored_roads.append(raw_stored_road)
    stored_road = validated_stored_roads[0] if validated_stored_roads else ""
    context_direct_road = normalize_road_token(
        getattr(context, "direct_road", "")
    )
    nearby_road = normalize_road_token(getattr(context, "nearby_road", ""))
    generic_stored_road = stored_road == ward
    if generic_stored_road and context_direct_road == ward:
        context_direct_road = ""
    stored_roads_for_resolution = (
        () if generic_stored_road else tuple(validated_stored_roads)
    )
    direct_roads = tuple(
        dict.fromkeys(
            road
            for road in (*stored_roads_for_resolution, context_direct_road)
            if road and not (nearby_road and generic_stored_road and road == stored_road)
        )
    )
    direct_road = context_direct_road or (
        "" if generic_stored_road else stored_road
    )
    landmark_key = normalize_location_token(getattr(context, "landmark", ""))
    relation = str(getattr(context, "relation", "") or "")
    candidate_road = direct_road or nearby_road
    if not city or not ward:
        return _fallback_with_issue(
            listing_id=listing_id,
            city=city,
            ward=ward_label,
            road=candidate_road,
            landmark=landmark_key,
            relation=relation,
            status="invalid",
            reason="missing_city_or_ward",
            registry=registry,
            signature=signature,
        )

    registry_text_road = ""
    if not direct_roads and not nearby_road and not landmark_key:
        registry_text_road = _unique_registry_road_from_text(
            city,
            lookup_ward_labels,
            " ".join(
                str(_value(listing, key, "") or "")
                for key in ("title", "description")
            ),
            registry,
        )
    if registry_text_road and registry_text_road not in direct_roads:
        direct_roads = (*direct_roads, registry_text_road)

    landmark_match = _match_landmark_in_wards(
        city,
        lookup_ward_labels,
        landmark_key,
        registry,
    )
    landmark_entry = (
        landmark_match if isinstance(landmark_match, Mapping) else None
    )
    landmark_ambiguous = landmark_match == "ambiguous"

    ambiguous_direct_road = ""
    if direct_roads:
        for candidate_direct_road in direct_roads:
            road_entry = _match_road_in_wards(
                city,
                lookup_ward_labels,
                candidate_direct_road,
                landmark_key if landmark_entry else "",
                registry,
            )
            if isinstance(road_entry, Mapping):
                canonical_road = _entry_road_key(road_entry, candidate_direct_road)
                allowed_landmarks = tuple(
                    normalize_location_token(item)
                    for item in (road_entry.get("landmark_keys") or ())
                )
                if (
                    landmark_entry
                    and allowed_landmarks
                    and landmark_key not in allowed_landmarks
                ):
                    return _fallback_with_issue(
                        listing_id=listing_id,
                        city=city,
                        ward=ward_label,
                        road=candidate_direct_road,
                        landmark=landmark_key,
                        relation=relation,
                        status="ambiguous",
                        reason="road_landmark_conflict",
                        registry=registry,
                        signature=signature,
                    )
                resolved = _resolved_from_entry(
                    listing_id=listing_id,
                    precision="road",
                    location_key=_road_location_key(
                        city,
                        ward,
                        canonical_road,
                        landmark_key if landmark_entry else "",
                    ),
                    entry=road_entry,
                    resolver_version=registry.resolver_version,
                    signature=signature,
                    relation="on",
                    reference_road=canonical_road,
                    landmark_key=landmark_key if landmark_entry else "",
                )
                if resolved:
                    issue = None
                    if landmark_ambiguous:
                        issue = _issue(
                            listing_id=listing_id,
                            city=city,
                            ward=ward_label,
                            road=candidate_direct_road,
                            landmark=landmark_key,
                            relation=relation,
                            status="ambiguous",
                            reason="ambiguous_landmark",
                        )
                    elif landmark_key and not landmark_entry:
                        issue = _issue(
                            listing_id=listing_id,
                            city=city,
                            ward=ward_label,
                            road=candidate_direct_road,
                            landmark=landmark_key,
                            relation=relation,
                            status="not_found",
                            reason="landmark_not_found",
                        )
                    return LocationResolution(location=resolved, issue=issue)
                return _fallback_with_issue(
                    listing_id=listing_id,
                    city=city,
                    ward=ward_label,
                    road=candidate_direct_road,
                    landmark=landmark_key,
                    relation=relation,
                    status="invalid",
                    reason="invalid_road_point",
                    registry=registry,
                    signature=signature,
                )
            if road_entry == "ambiguous" and not ambiguous_direct_road:
                ambiguous_direct_road = candidate_direct_road
        if ambiguous_direct_road:
            return _fallback_with_issue(
                listing_id=listing_id,
                city=city,
                ward=ward_label,
                road=ambiguous_direct_road,
                landmark=landmark_key,
                relation=relation,
                status="ambiguous",
                reason="ambiguous_road",
                registry=registry,
                signature=signature,
            )

    if nearby_road:
        road_entry = _match_road_in_wards(
            city,
            lookup_ward_labels,
            nearby_road,
            landmark_key if landmark_entry else "",
            registry,
        )
        if isinstance(road_entry, Mapping):
            canonical_road = _entry_road_key(road_entry, nearby_road)
            resolved = _resolved_from_entry(
                listing_id=listing_id,
                precision="road",
                location_key=_road_location_key(
                    city,
                    ward,
                    canonical_road,
                    landmark_key if landmark_entry else "",
                ),
                entry=road_entry,
                resolver_version=registry.resolver_version,
                signature=signature,
                relation=relation or "near",
                reference_road=canonical_road,
                landmark_key=landmark_key if landmark_entry else "",
            )
            if resolved:
                issue = None
                if landmark_ambiguous:
                    issue = _issue(
                        listing_id=listing_id,
                        city=city,
                        ward=ward_label,
                        road=nearby_road,
                        landmark=landmark_key,
                        relation=relation,
                        status="ambiguous",
                        reason="ambiguous_landmark",
                    )
                elif landmark_key and not landmark_entry:
                    issue = _issue(
                        listing_id=listing_id,
                        city=city,
                        ward=ward_label,
                        road=nearby_road,
                        landmark=landmark_key,
                        relation=relation,
                        status="not_found",
                        reason="landmark_not_found",
                    )
                return LocationResolution(location=resolved, issue=issue)
        status, reason = (
            ("ambiguous", "ambiguous_nearby_road")
            if road_entry == "ambiguous"
            else ("not_found", "nearby_road_not_found")
        )
        if landmark_ambiguous:
            status, reason = "ambiguous", "ambiguous_landmark"
        if landmark_entry:
            canonical_landmark = _entry_landmark_key(
                landmark_entry,
                landmark_key,
            )
            resolved = _resolved_from_entry(
                listing_id=listing_id,
                precision="landmark",
                location_key=(
                    f"landmark:{_slug(city)}:{_slug(ward)}:"
                    f"{_slug(canonical_landmark)}"
                ),
                entry=landmark_entry,
                resolver_version=registry.resolver_version,
                signature=signature,
                relation=relation or "near",
                reference_road=nearby_road,
                landmark_key=canonical_landmark,
                resolution_status=status,
                resolution_reason=reason,
            )
            if resolved:
                return LocationResolution(
                    location=resolved,
                    issue=_issue(
                        listing_id=listing_id,
                        city=city,
                        ward=ward_label,
                        road=nearby_road,
                        landmark=landmark_key,
                        relation=relation,
                        status=status,
                        reason=reason,
                    ),
                )
        return _fallback_with_issue(
            listing_id=listing_id,
            city=city,
            ward=ward_label,
            road=nearby_road,
            landmark=landmark_key,
            relation=relation,
            status=status,
            reason=reason,
            registry=registry,
            signature=signature,
        )

    if landmark_entry:
        canonical_landmark = _entry_landmark_key(
            landmark_entry,
            landmark_key,
        )
        resolved = _resolved_from_entry(
            listing_id=listing_id,
            precision="landmark",
            location_key=(
                f"landmark:{_slug(city)}:{_slug(ward)}:"
                f"{_slug(canonical_landmark)}"
            ),
            entry=landmark_entry,
            resolver_version=registry.resolver_version,
            signature=signature,
            relation="at",
            landmark_key=canonical_landmark,
        )
        if resolved:
            issue = None
            if direct_road:
                issue = _issue(
                    listing_id=listing_id,
                    city=city,
                    ward=ward_label,
                    road=direct_road,
                    landmark=landmark_key,
                    relation=relation,
                    status="not_found",
                    reason="road_not_found",
                )
            return LocationResolution(location=resolved, issue=issue)

    if landmark_ambiguous:
        return _fallback_with_issue(
            listing_id=listing_id,
            city=city,
            ward=ward_label,
            road=direct_road or nearby_road,
            landmark=landmark_key,
            relation=relation,
            status="ambiguous",
            reason="ambiguous_landmark",
            registry=registry,
            signature=signature,
        )

    if direct_road:
        return _fallback_with_issue(
            listing_id=listing_id,
            city=city,
            ward=ward_label,
            road=direct_road,
            landmark=landmark_key,
            relation=relation,
            status="not_found",
            reason="road_not_found",
            registry=registry,
            signature=signature,
        )

    if landmark_key:
        return _fallback_with_issue(
            listing_id=listing_id,
            city=city,
            ward=ward_label,
            road="",
            landmark=landmark_key,
            relation=relation,
            status="not_found",
            reason="landmark_not_found",
            registry=registry,
            signature=signature,
        )

    location = _ward_fallback(
        listing_id=listing_id,
        city=city,
        ward=ward_label,
        registry=registry,
        signature=signature,
    )
    if location:
        return LocationResolution(location=location, issue=None)
    return _fallback_with_issue(
        listing_id=listing_id,
        city=city,
        ward=ward_label,
        road="",
        landmark="",
        relation="",
        status="not_found",
        reason="ward_not_found",
        registry=registry,
        signature=signature,
    )


def load_location_registry(
    *,
    ward_path: Path = LISTING_MAP_WARD_REGISTRY_PATH,
    road_path: Path = LISTING_MAP_ROAD_REGISTRY_PATH,
    landmark_path: Path = LISTING_MAP_LANDMARK_REGISTRY_PATH,
) -> LocationRegistry:
    ward_payload = json.loads(ward_path.read_text(encoding="utf-8"))
    road_payload = json.loads(road_path.read_text(encoding="utf-8"))
    landmark_payload = json.loads(landmark_path.read_text(encoding="utf-8"))
    versions = {
        str(payload.get("resolver_version") or "")
        for payload in (ward_payload, road_payload, landmark_payload)
    }
    if "" in versions or len(versions) != 1:
        raise ValueError("listing location registry versions do not match")
    resolver_version = versions.pop()

    wards = {
        (str(item["city"]), str(item["normalized_ward"])): item
        for item in ward_payload.get("wards") or []
    }
    road_lists: dict[
        tuple[str, str, str],
        list[Mapping[str, object]],
    ] = {}
    for item in road_payload.get("roads") or []:
        aliases = set(item.get("aliases") or ())
        aliases.add(str(item["normalized_road"]))
        normalized_aliases = {
            normalize_road_token(alias) for alias in aliases
        }
        for alias in normalized_aliases:
            key = (
                str(item["city"]),
                str(item["normalized_ward"]),
                alias,
            )
            road_lists.setdefault(key, []).append(item)
    roads = {key: tuple(items) for key, items in road_lists.items()}
    road_text_aliases = {}
    for (city, ward, alias), entries in roads.items():
        road_text_aliases.setdefault((city, ward), {})[alias] = entries

    landmark_lists = {}
    for item in landmark_payload.get("landmarks") or []:
        aliases = set(item.get("aliases") or ())
        aliases.add(str(item["normalized_landmark"]))
        normalized_aliases = {
            normalize_location_token(alias) for alias in aliases
        }
        for alias in normalized_aliases:
            key = (
                str(item["city"]),
                str(item["normalized_ward"]),
                alias,
            )
            landmark_lists.setdefault(key, []).append(item)
    landmarks = {
        key: items[0] if len(items) == 1 else tuple(items)
        for key, items in landmark_lists.items()
    }
    return LocationRegistry(
        resolver_version=resolver_version,
        roads=roads,
        landmarks=landmarks,
        wards=wards,
        road_text_aliases=road_text_aliases,
    )
