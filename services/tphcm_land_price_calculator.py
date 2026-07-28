from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Mapping


LAND_TYPES = ("residential", "commerce_service", "production_business")


class CalculationValidationError(ValueError):
    def __init__(self, field_errors: dict[str, str]):
        super().__init__("Invalid land-price calculation input")
        self.field_errors = field_errors


def _positive_decimal(value: object, field: str, *, maximum: str) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise CalculationValidationError(
            {field: "Giá trị phải là một số hợp lệ."}
        ) from None
    if not number.is_finite() or number <= 0:
        raise CalculationValidationError({field: "Giá trị phải lớn hơn 0."})
    if number > Decimal(maximum):
        raise CalculationValidationError(
            {field: f"Giá trị không được vượt quá {maximum}."}
        )
    return number


def _non_negative_decimal(value: object, field: str, *, maximum: str) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise CalculationValidationError(
            {field: "Giá trị phải là một số hợp lệ."}
        ) from None
    if not number.is_finite() or number < 0:
        raise CalculationValidationError({field: "Giá trị không được âm."})
    if number > Decimal(maximum):
        raise CalculationValidationError(
            {field: f"Giá trị không được vượt quá {maximum}."}
        )
    return number


def resolve_location(location: Mapping[str, object]) -> dict[str, object]:
    mode = str(location.get("mode") or "standard")
    if mode == "multiple_frontages":
        return {
            "position": 1,
            "label": "Từ hai mặt tiền trở lên",
            "factor": Decimal("1.10"),
            "breakdown": [
                {
                    "code": mode,
                    "label": "Từ hai mặt tiền trở lên",
                    "factor": Decimal("1.10"),
                }
            ],
        }
    if mode == "special_seventy_percent":
        return {
            "position": None,
            "label": "Trường hợp áp dụng 70%",
            "factor": Decimal("0.70"),
            "breakdown": [
                {
                    "code": mode,
                    "label": "Trường hợp đặc biệt 70%",
                    "factor": Decimal("0.70"),
                }
            ],
        }
    if mode != "standard":
        raise CalculationValidationError(
            {"location.mode": "Chế độ vị trí không hợp lệ."}
        )

    access = str(location.get("access") or "")
    if access == "frontage":
        return {
            "position": 1,
            "label": "Vị trí 1",
            "factor": Decimal("1.00"),
            "breakdown": [
                {
                    "code": "position_1",
                    "label": "Vị trí 1",
                    "factor": Decimal("1.00"),
                }
            ],
        }
    if access != "alley":
        raise CalculationValidationError(
            {"location.access": "Hãy chọn mặt tiền hoặc trong hẻm."}
        )

    width = _positive_decimal(
        location.get("alley_min_width_m"),
        "location.alley_min_width_m",
        maximum="100",
    )
    distance = _non_negative_decimal(
        location.get("distance_to_named_road_m"),
        "location.distance_to_named_road_m",
        maximum="10000",
    )
    surface = str(location.get("alley_surface") or "")
    if surface not in {"paved", "dirt"}:
        raise CalculationValidationError(
            {"location.alley_surface": "Hãy chọn mặt hẻm."}
        )

    if width >= Decimal("5"):
        position, factor = 2, Decimal("0.50")
    elif width >= Decimal("3"):
        position, factor = 3, Decimal("0.40")
    else:
        position, factor = 4, Decimal("0.32")

    breakdown = [
        {
            "code": f"position_{position}",
            "label": f"Vị trí {position}",
            "factor": factor,
        }
    ]
    if surface == "dirt":
        factor *= Decimal("0.80")
        breakdown.append(
            {
                "code": "dirt_alley",
                "label": "Hẻm đất",
                "factor": Decimal("0.80"),
            }
        )
    if distance >= Decimal("100"):
        factor *= Decimal("0.90")
        breakdown.append(
            {
                "code": "distance_100m",
                "label": "Cách đường có tên từ 100m",
                "factor": Decimal("0.90"),
            }
        )

    return {
        "position": position,
        "label": f"Vị trí {position}",
        "factor": factor,
        "breakdown": breakdown,
    }


def build_depth_bands(
    land_area_m2: object,
    frontage_m: object,
    depth_m: object,
    land_type: str,
) -> list[dict[str, object]]:
    area = _positive_decimal(
        land_area_m2,
        "land_area_m2",
        maximum="1000000",
    )
    frontage = _positive_decimal(
        frontage_m,
        "frontage_m",
        maximum="10000",
    )
    depth = _positive_decimal(
        depth_m,
        "depth_m",
        maximum="10000",
    )
    if land_type == "residential":
        first_end = frontage * Decimal("5")
        second_end = frontage * Decimal("8")
        factors = (Decimal("1.00"), Decimal("0.80"), Decimal("0.70"))
    elif land_type in {"commerce_service", "production_business"}:
        first_end = frontage * Decimal("2")
        second_end = frontage * Decimal("4")
        factors = (Decimal("1.00"), Decimal("0.60"), Decimal("0.40"))
    else:
        raise ValueError(f"Unsupported land type: {land_type}")

    lengths = (
        min(depth, first_end),
        max(Decimal("0"), min(depth, second_end) - first_end),
        max(Decimal("0"), depth - second_end),
    )
    names = ("front", "middle", "rear")
    return [
        {
            "code": name,
            "area_m2": area * length / depth,
            "factor": factor,
        }
        for name, length, factor in zip(names, lengths, factors)
        if length > 0
    ]


def _whole_vnd(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def calculate_land_price(
    base_prices_thousand: Mapping[str, object],
    *,
    land_area_m2: object,
    frontage_m: object,
    depth_m: object,
    location: Mapping[str, object],
) -> dict[str, object]:
    area = _positive_decimal(
        land_area_m2,
        "land_area_m2",
        maximum="1000000",
    )
    frontage = _positive_decimal(
        frontage_m,
        "frontage_m",
        maximum="10000",
    )
    depth = _positive_decimal(
        depth_m,
        "depth_m",
        maximum="10000",
    )
    location_result = resolve_location(location)
    location_factor = location_result["factor"]
    rectangular_area = frontage * depth
    mismatch_ratio = abs(area - rectangular_area) / rectangular_area
    mismatch_warning = mismatch_ratio > Decimal("0.10")
    warnings = []
    if mismatch_warning:
        warnings.append(
            {
                "code": "geometry_mismatch",
                "message": (
                    "Diện tích giấy tờ lệch hơn 10% so với ngang × dài. "
                    "Kết quả phân dải là ước tính; cần đối chiếu hình thể thửa."
                ),
            }
        )

    values: dict[str, dict[str, object]] = {}
    for land_type in LAND_TYPES:
        raw_base = base_prices_thousand.get(land_type)
        try:
            base_thousand = Decimal(str(raw_base))
        except (InvalidOperation, ValueError):
            base_thousand = Decimal("0")

        if not base_thousand.is_finite() or base_thousand <= 0:
            values[land_type] = {
                "base_unit_price": None,
                "average_unit_price": None,
                "total_value": None,
                "bands": [],
            }
            continue

        base_vnd = base_thousand * Decimal("1000")
        bands = build_depth_bands(area, frontage, depth, land_type)
        total_value = Decimal("0")
        result_bands = []
        for band in bands:
            unit_price = base_vnd * location_factor * band["factor"]
            subtotal = band["area_m2"] * unit_price
            total_value += subtotal
            result_bands.append(
                {
                    **band,
                    "unit_price": _whole_vnd(unit_price),
                    "subtotal": _whole_vnd(subtotal),
                }
            )

        values[land_type] = {
            "base_unit_price": _whole_vnd(base_vnd),
            "average_unit_price": _whole_vnd(total_value / area),
            "total_value": _whole_vnd(total_value),
            "bands": result_bands,
        }

    return {
        "position": location_result,
        "geometry": {
            "legal_area_m2": area,
            "frontage_m": frontage,
            "depth_m": depth,
            "rectangular_area_m2": rectangular_area,
            "mismatch_warning": mismatch_warning,
        },
        "values": values,
        "warnings": warnings,
    }
