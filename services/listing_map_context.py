from __future__ import annotations

from dataclasses import dataclass
import re

from services.listing_location_resolver import (
    normalize_location_token,
    normalize_road_token,
)


@dataclass(frozen=True)
class MapLocationContext:
    direct_road: str = ""
    nearby_road: str = ""
    landmark: str = ""
    relation: str = ""
    distance_m: float | None = None
    evidence_text: str = ""


_DISTANCE_RE = re.compile(
    r"\b(?:cach|gan|khoang)?\s*(\d{1,4}(?:[.,]\d+)?)\s*m\b",
    re.IGNORECASE,
)
_NEAR_PREFIX_RE = re.compile(
    r"\b(?:cach|gan|sat|ke|canh|doi dien|ra|thong ra|noi ra)\s+"
    r"(?:duong\s+)?",
    re.IGNORECASE,
)
_ALLEY_PREFIX_RE = re.compile(
    r"\b(?:1\s*(?:x|s)(?:ec|et)|mot\s*(?:x|s)(?:ec|et)|nhanh|hem)\s+"
    r"(?:duong\s+)?",
    re.IGNORECASE,
)
_DIRECT_PREFIX_RE = re.compile(
    r"\b(?:mat tien|mtkd|mt|duong)\s+",
    re.IGNORECASE,
)
_ROAD_CODE_RE = re.compile(
    r"^(?P<prefix>dx|db|dh|dt|dl|tl|ql|nl|ni|n|d)\s*"
    r"[-./_]?\s*0*(?P<number>\d{1,4})(?P<suffix>[a-z]?)\b",
    re.IGNORECASE,
)
_NUMBERED_ROAD_RE = re.compile(
    r"^(?:duong\s+)?(?:so\s+)?0*(?P<number>\d{1,4})"
    r"(?P<suffix>[a-z]?)\b",
    re.IGNORECASE,
)
_LANDMARK_RE = re.compile(
    r"\b(?P<kind>tdc|tai dinh cu|kdc|khu dan cu|khu do thi|du an)\s+"
    r"(?P<name>[a-z0-9][a-z0-9\s-]{0,100})",
    re.IGNORECASE,
)
_ROAD_STOP_RE = re.compile(
    r"\b(?:khoang|chi|tam|khu|phuong|xa|thi tran|thanh pho|tp|"
    r"dan cu|o to|xe hoi|duong nhua|duong be tong|duong dat|"
    r"gia|dien tich|dt|ban|can ban|thong|gan|sat|cach)\b",
    re.IGNORECASE,
)
_LANDMARK_STOP_RE = re.compile(
    r"\b(?:phuong|xa|thi tran|thanh pho|tp|gia|dien tich|dt|"
    r"ban|can ban|mat tien|hem|duong|so do|tho cu|ngang|dai|"
    r"khu dan cu dong|dan cu dong)\b",
    re.IGNORECASE,
)
_NON_ROAD_NAMES = {
    "be tong",
    "dat",
    "nhua",
    "oto",
    "o to",
    "xe hoi",
}
_ROAD_NAME_HINT_RE = re.compile(
    r"^(?:"
    r"dx|d|db|dh|dt|dl|tl|ql|nl|ni|n|duong so|"
    r"nguyen|tran|le|ly|pham|phan|huynh|vo|dang|do|ngo|bui|"
    r"hoang|ton duc|cach mang|hung vuong|dien bien|quoc lo|"
    r"my phuoc|phu loi|phu tan"
    r")\b",
    re.IGNORECASE,
)


def _bounded_evidence(title: str, description: str) -> str:
    evidence = " — ".join(
        part.strip() for part in (title or "", description or "") if part.strip()
    )
    return evidence[:180]


def _distance(text: str) -> float | None:
    match = _DISTANCE_RE.search(text)
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", "."))
    except ValueError:
        return None


def _cut_at_stop(value: str, stop_re: re.Pattern[str]) -> str:
    match = stop_re.search(value)
    if match:
        value = value[: match.start()]
    return " ".join(value.strip(" -_,.;:").split())


def _normalize_road_candidate(value: str) -> str:
    candidate = " ".join(value.strip().split())
    if candidate.startswith("nguyen tri phuong"):
        return normalize_road_token("nguyen tri phuong")

    code_match = _ROAD_CODE_RE.match(candidate)
    if code_match:
        if code_match.group("suffix").lower() == "m":
            return ""
        raw = (
            f"{code_match.group('prefix')} "
            f"{int(code_match.group('number'))}{code_match.group('suffix')}"
        )
        return normalize_road_token(raw)

    number_match = _NUMBERED_ROAD_RE.match(candidate)
    if number_match:
        if number_match.group("suffix").lower() == "m":
            return ""
        return (
            f"duong so {int(number_match.group('number'))}"
            f"{number_match.group('suffix').lower()}"
        )

    candidate = _cut_at_stop(candidate, _ROAD_STOP_RE)
    words = candidate.split()
    if not words:
        return ""
    candidate = " ".join(words[:8])
    if candidate in _NON_ROAD_NAMES or len(candidate) < 3:
        return ""
    return normalize_road_token(candidate)


def _looks_like_road_name(road: str) -> bool:
    if not road:
        return False
    if _ROAD_NAME_HINT_RE.match(road):
        return len(road.split()) >= 2 or re.match(r"^(?:dx|d|db|dh|dt|dl|tl|ql|nl|ni|n)\s+\d", road)
    return False


def _road_after(text: str, start: int) -> str:
    return _normalize_road_candidate(text[start : start + 100])


def _relation_road(
    text: str,
    prefix_re: re.Pattern[str],
) -> tuple[str, re.Match[str] | None]:
    for match in prefix_re.finditer(text):
        road = _road_after(text, match.end())
        has_explicit_road_word = "duong" in match.group(0).lower()
        if road and (has_explicit_road_word or _looks_like_road_name(road)):
            return road, match
    return "", None


def _direct_road(text: str) -> str:
    for match in _DIRECT_PREFIX_RE.finditer(text):
        prefix_context = text[max(0, match.start() - 20) : match.start()]
        if re.search(
            r"\b(?:cach|gan|sat|ke|canh|ra|thong ra|noi ra)\s*$",
            prefix_context,
        ):
            continue
        road = _road_after(text, match.end())
        if road:
            return road

    code_match = re.search(
        r"\b(?:dx|db|dh|dt|dl|tl|ql|nl|ni)\s*[-./_]?\s*0*\d{1,4}[a-z]?\b",
        text,
    )
    if code_match:
        prefix_context = text[max(0, code_match.start() - 28) : code_match.start()]
        if not re.search(
            r"\b(?:cach|gan|sat|ke|canh|ra|thong ra|noi ra|nhanh|hem|"
            r"1 xec|1 xet|1 sec|1 set)\s+(?:duong\s+)?$",
            prefix_context,
        ):
            return _normalize_road_candidate(code_match.group(0))
    return ""


def _landmark(text: str) -> str:
    match = _LANDMARK_RE.search(text)
    if not match:
        return ""
    name = _cut_at_stop(match.group("name"), _LANDMARK_STOP_RE)
    if not name:
        return ""
    kind = match.group("kind").lower()
    if kind == "tai dinh cu":
        kind = "tdc"
    elif kind == "khu dan cu":
        kind = "kdc"
    return normalize_location_token(f"{kind} {name}")


def extract_map_location_context(
    title: str,
    description: str,
    stored_road_name: str = "",
) -> MapLocationContext:
    """Extract map-only location clues without mutating canonical listing data."""
    folded = normalize_location_token(
        " ".join(part for part in (title or "", description or "") if part)
    )
    evidence = _bounded_evidence(title, description)
    landmark = _landmark(folded)

    alley_road, _ = _relation_road(folded, _ALLEY_PREFIX_RE)
    if alley_road:
        return MapLocationContext(
            nearby_road=alley_road,
            landmark=landmark,
            relation="alley",
            distance_m=_distance(folded),
            evidence_text=evidence,
        )

    nearby_road, _ = _relation_road(folded, _NEAR_PREFIX_RE)
    if nearby_road:
        return MapLocationContext(
            nearby_road=nearby_road,
            landmark=landmark,
            relation="near",
            distance_m=_distance(folded),
            evidence_text=evidence,
        )

    direct_road = _direct_road(folded)
    if not direct_road and stored_road_name:
        direct_road = normalize_road_token(stored_road_name)

    return MapLocationContext(
        direct_road=direct_road,
        landmark=landmark,
        relation="on" if direct_road else ("at" if landmark else ""),
        evidence_text=evidence,
    )
