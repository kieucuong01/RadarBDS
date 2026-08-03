from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


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


@dataclass(frozen=True)
class MeasurementIntegrity:
    price_ty: float | None
    area_m2: float | None
    tho_cu_m2: float | None
    price_per_m2: float | None
    flags: tuple[str, ...] = ()
    repairs: tuple[str, ...] = ()


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


_AREA_NUMBER = r"(\d+(?:[,.]\d+)?)"
_AREA_UNIT = r"(?:m[²2]|mv|met vuong)"
_EXPLICIT_AREA_UNIT = r"(?:m(?:[²2])?|mv|met vuong)"
_NOT_DIMENSION_TAIL = r"(?!\s*[x×*]\s*\d)"


def parse_area_number(value) -> float | None:
    """Parse VN area notation while preserving comma/dot decimal values."""
    raw = str(value or "").strip().replace(" ", "")
    if not raw:
        return None
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?", raw):
        raw = raw.replace(".", "").replace(",", ".")
    else:
        raw = raw.replace(",", ".")
    try:
        area = float(raw)
    except (TypeError, ValueError):
        return None
    return area if 0 < area < 100_000 else None


def _area_number(value: str) -> float | None:
    return parse_area_number(value)


def declared_total_area(text: str) -> float | None:
    folded = _fold(text)
    folded = re.sub(r"(?<=\d)\s*([,.])\s*(?=\d)", r"\1", folded)
    direct_patterns = (
        rf"\b(?:(?<!be )(?<!be-)tong(?:\s+(?:dt|dien tich))?|dt\s+tong)"
        rf"\s*[:=\-]?\s*"
        rf"{_AREA_NUMBER}\s*{_EXPLICIT_AREA_UNIT}\b{_NOT_DIMENSION_TAIL}",
        rf"\b(?:dt(?:\s+dat)?|dien tich(?:\s+dat)?)\s*[:=\-]?\s*"
        rf"{_AREA_NUMBER}\s*{_EXPLICIT_AREA_UNIT}\b{_NOT_DIMENSION_TAIL}",
        rf"\b(?:ban\s+)?(?:dat|lo|nha)(?:\s+nen)?\s+"
        rf"{_AREA_NUMBER}\s*{_AREA_UNIT}\b{_NOT_DIMENSION_TAIL}",
    )
    for pattern in direct_patterns:
        match = re.search(pattern, folded)
        if match:
            return _area_number(match.group(1))

    for match in re.finditer(
        rf"(?:=|~)\s*{_AREA_NUMBER}\s*{_EXPLICIT_AREA_UNIT}\b",
        folded,
    ):
        context = folded[max(0, match.start() - 48):match.start()]
        if re.search(
            r"(?:\d+(?:[,.]\d+)?\s*[x×*]\s*\d+(?:[,.]\d+)?|"
            r"dt|dien tich|(?<!be )(?<!be-)tong|ngang)",
            context,
        ):
            return _area_number(match.group(1))

    for match in re.finditer(
        rf"\(\s*{_AREA_NUMBER}\s*{_EXPLICIT_AREA_UNIT}\s*\)",
        folded,
    ):
        context = folded[max(0, match.start() - 48):match.start()]
        if re.search(
            r"\d+(?:[,.]\d+)?\s*m?[²2]?\s*[x×*]\s*"
            r"\d+(?:[,.]\d+)?\s*m?\s*$",
            context,
        ):
            return _area_number(match.group(1))
    return None


def has_declared_total_area(text: str) -> bool:
    return declared_total_area(text) is not None


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
    def distinct_values(pattern: str) -> set[float]:
        values = set()
        for raw in re.findall(pattern, folded):
            try:
                values.add(round(float(raw.replace(",", ".")), 3))
            except (TypeError, ValueError):
                continue
        return values

    frontage_values = distinct_values(
        r"\bngang(?:\s+(?:truoc|sau))?\s*[:=\-]?\s*(\d+(?:[,.]\d+)?)"
    )
    depth_values = distinct_values(
        r"\b(?:dai|sau)\s*[:=\-]?\s*(\d+(?:[,.]\d+)?)"
    )
    pair_values = set()
    for frontage, depth in re.findall(
            r"(?<!\d)(\d+(?:[,.]\d+)?)\s*m?[²2]?\s*[x×*]\s*"
            r"(\d+(?:[,.]\d+)?)",
            folded,
    ):
        frontage_value = float(frontage.replace(",", "."))
        depth_value = float(depth.replace(",", "."))
        if 2 <= frontage_value <= 50 and 5 <= depth_value <= 500:
            pair_values.add((round(frontage_value, 3), round(depth_value, 3)))
    repeated_sides = (
        len(frontage_values) > 1
        or len(depth_values) > 1
        or len(pair_values) > 1
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


def reconcile_measurements(
    *,
    text,
    structured_price_ty,
    structured_area_m2,
    source_price_per_m2,
    parsed_price_ty,
    parsed_area_m2,
    parsed_tho_cu_m2,
    frontage_m,
    depth_m,
    parsed_area_is_declared_total,
    ambiguous_price,
    multi_lot,
) -> MeasurementIntegrity:
    price = _number(structured_price_ty)
    parsed_price = _number(parsed_price_ty)
    area = _number(structured_area_m2)
    parsed_area = _number(parsed_area_m2)
    tho_cu = _number(parsed_tho_cu_m2)
    source_ppm = _number(source_price_per_m2)
    flags: list[str] = []
    repairs: list[str] = []

    if ambiguous_price:
        price = None
    elif parsed_price and (
        price is None or abs(parsed_price - price) / max(parsed_price, price) > 0.15
    ):
        price = parsed_price
        repairs.append("clear_text_price")

    structured_is_tho_cu = (
        area is not None
        and tho_cu is not None
        and abs(area - tho_cu) <= max(1.0, tho_cu * 0.03)
    )
    if parsed_area_is_declared_total and parsed_area:
        if structured_is_tho_cu and parsed_area > area:
            repairs.append("structured_area_was_residential_area")
        area = parsed_area
    elif (
        structured_is_tho_cu
        and parsed_area
        and parsed_area > area * 1.10
        and not multi_lot
        and not is_irregular_geometry(text)
    ):
        area = parsed_area
        repairs.append("structured_area_was_residential_area")
    elif (
        area is None
        and parsed_area
        and not multi_lot
        and not is_irregular_geometry(text)
    ):
        area = parsed_area
        repairs.append("area_from_dimensions")

    if severe_geometry_conflict(text, area, frontage_m, depth_m):
        flags.append("area_dimension_conflict")

    if price is None and not ambiguous_price and source_ppm and area and not multi_lot:
        price = round(source_ppm * area / 1000, 4)
        repairs.append("price_from_unit_price")

    derived_ppm = round(price * 1000 / area, 3) if price and area and area > 0 else None
    if derived_ppm and source_ppm:
        mismatch = abs(derived_ppm - source_ppm) / max(derived_ppm, source_ppm)
        has_text_support = bool(parsed_price and (parsed_area_is_declared_total or parsed_area))
        if mismatch > 0.20 and not has_text_support:
            flags.append("price_area_inconsistent")

    return MeasurementIntegrity(
        price_ty=price,
        area_m2=area,
        tho_cu_m2=tho_cu,
        price_per_m2=derived_ppm,
        flags=tuple(sorted(set(flags))),
        repairs=tuple(repairs),
    )
