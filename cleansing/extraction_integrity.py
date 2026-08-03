from __future__ import annotations

import re
import unicodedata


REGULAR_GEOMETRY_SEVERE_RATIO = 0.40
IRREGULAR_GEOMETRY_SEVERE_RATIO = 0.60

_IRREGULAR_CUES = (
    "xeo",
    "xeo hau",
    "no hau",
    "thop hau",
    "that hau",
    "hinh thang",
    "tam giac",
    "hai mat tien",
)


def _number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fold(text: str) -> str:
    folded = unicodedata.normalize("NFD", text or "")
    folded = "".join(ch for ch in folded if unicodedata.category(ch) != "Mn")
    folded = folded.lower().replace("đ", "d")
    return re.sub(r"\s+", " ", folded).strip()


def geometry_difference_ratio(reported_area, frontage_m, depth_m):
    area, frontage, depth = map(_number, (reported_area, frontage_m, depth_m))
    if area is None or frontage is None or depth is None:
        return None
    if area <= 0 or not (2 <= frontage <= 50 and 5 <= depth <= 500):
        return None
    rectangular_area = frontage * depth
    return abs(area - rectangular_area) / max(area, rectangular_area)


def is_irregular_geometry(text: str, *, dimension_pair_count: int = 1) -> bool:
    folded = _fold(text)
    repeated_sides = (
        len(re.findall(r"\bngang\b", folded)) > 1
        or len(re.findall(r"\b(?:dai|sau)\b", folded)) > 1
    )
    return (
        dimension_pair_count > 1
        or repeated_sides
        or any(cue in folded for cue in _IRREGULAR_CUES)
    )


def severe_geometry_conflict(
    text,
    reported_area,
    frontage_m,
    depth_m,
    *,
    dimension_pair_count=1,
):
    ratio = geometry_difference_ratio(reported_area, frontage_m, depth_m)
    if ratio is None:
        return False
    threshold = (
        IRREGULAR_GEOMETRY_SEVERE_RATIO
        if is_irregular_geometry(text, dimension_pair_count=dimension_pair_count)
        else REGULAR_GEOMETRY_SEVERE_RATIO
    )
    return ratio > threshold
