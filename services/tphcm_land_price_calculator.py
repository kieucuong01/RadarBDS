from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Mapping

from services.tphcm_agricultural_land_prices import (
    AgriculturalValidationError,
    calculate_agricultural_land_price,
)


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


def calculate_mixed_land_price(
    base_prices_thousand: Mapping[str, object],
    *,
    area_name: object,
    land_area_m2: object,
    frontage_m: object,
    depth_m: object,
    residential_area_m2: object,
    agricultural_area_m2: object,
    residential_geometry: Mapping[str, object],
    location: Mapping[str, object],
    agricultural: Mapping[str, object],
) -> dict[str, object]:
    total_area = _positive_decimal(
        land_area_m2,
        "land_area_m2",
        maximum="1000000",
    )
    parcel_frontage = _positive_decimal(
        frontage_m,
        "frontage_m",
        maximum="10000",
    )
    parcel_depth = _positive_decimal(
        depth_m,
        "depth_m",
        maximum="10000",
    )
    residential_area = _positive_decimal(
        residential_area_m2,
        "residential_area_m2",
        maximum="1000000",
    )
    agricultural_area = _positive_decimal(
        agricultural_area_m2,
        "agricultural_area_m2",
        maximum="1000000",
    )
    split_difference = abs(
        total_area - residential_area - agricultural_area
    )
    if split_difference > Decimal("0.01"):
        raise CalculationValidationError(
            {
                "agricultural_area_m2": (
                    "Tổng diện tích đất ở và đất nông nghiệp phải khớp "
                    "diện tích toàn thửa (sai số tối đa 0,01 m²)."
                )
            }
        )

    use_custom = residential_geometry.get("use_custom", False)
    if not isinstance(use_custom, bool):
        raise CalculationValidationError(
            {
                "residential_geometry.use_custom": (
                    "Lựa chọn hình thể phần đất ở không hợp lệ."
                )
            }
        )
    if use_custom:
        residential_frontage = residential_geometry.get("frontage_m")
        residential_depth = residential_geometry.get("depth_m")
        assumption = "custom_geometry"
    else:
        residential_frontage = parcel_frontage
        residential_depth = residential_area / parcel_frontage
        assumption = "front_strip"

    try:
        residential_result = calculate_land_price(
            base_prices_thousand,
            land_area_m2=residential_area,
            frontage_m=residential_frontage,
            depth_m=residential_depth,
            location=location,
        )
    except CalculationValidationError as exc:
        renamed_errors = {
            (
                f"residential_geometry.{field}"
                if use_custom and field in {"frontage_m", "depth_m"}
                else field
            ): message
            for field, message in exc.field_errors.items()
        }
        raise CalculationValidationError(renamed_errors) from None

    raw_residential_base = base_prices_thousand.get("residential")
    try:
        residential_base_vnd = Decimal(str(raw_residential_base)) * Decimal(
            "1000"
        )
    except (InvalidOperation, ValueError):
        residential_base_vnd = Decimal("0")
    if (
        not residential_base_vnd.is_finite()
        or residential_base_vnd <= 0
    ):
        raise CalculationValidationError(
            {
                "row_key": (
                    "Dòng bảng giá đã chọn không có đơn giá đất ở để tính "
                    "thửa hỗn hợp."
                )
            }
        )

    try:
        agricultural_result = calculate_agricultural_land_price(
            area_name=area_name,
            land_type=agricultural.get("land_type"),
            position=agricultural.get("position"),
            area_m2=agricultural_area,
            residential_position_1_price_vnd=residential_base_vnd,
            in_residential_area=(
                agricultural.get("in_residential_area") is True
            ),
            same_parcel_has_house=(
                agricultural.get("same_parcel_has_house") is True
            ),
        )
    except AgriculturalValidationError as exc:
        raise CalculationValidationError(exc.field_errors) from None

    residential_value = residential_result["values"]["residential"]
    warnings = []
    for warning in residential_result["warnings"]:
        if warning.get("code") == "geometry_mismatch":
            warnings.append(
                {
                    **warning,
                    "code": "residential_geometry_mismatch",
                    "message": (
                        "Hình thể riêng của phần đất ở lệch hơn 10% so với "
                        "diện tích đất ở. Kết quả phân dải là ước tính."
                    ),
                }
            )
        else:
            warnings.append(warning)

    parcel_rectangular_area = parcel_frontage * parcel_depth
    parcel_mismatch = (
        abs(total_area - parcel_rectangular_area) / parcel_rectangular_area
        > Decimal("0.10")
    )
    if parcel_mismatch:
        warnings.append(
            {
                "code": "parcel_geometry_mismatch",
                "message": (
                    "Diện tích toàn thửa lệch hơn 10% so với ngang × dài. "
                    "Hãy đối chiếu hình thể trên hồ sơ địa chính."
                ),
            }
        )
    if assumption == "front_strip":
        warnings.append(
            {
                "code": "residential_front_strip_assumption",
                "message": (
                    "Công cụ đang giả định phần đất ở nằm gần lối tiếp giáp "
                    "nhất. Có thể nhập hình thể riêng nếu sơ đồ địa chính khác."
                ),
            }
        )

    agricultural_total = agricultural_result["total_value"]
    residential_total = residential_value["total_value"]
    combined_total = (
        residential_total + agricultural_total
        if residential_total is not None and agricultural_total is not None
        else None
    )

    return {
        "parcel_mode": "mixed",
        "position": residential_result["position"],
        "geometry": {
            "legal_area_m2": total_area,
            "frontage_m": parcel_frontage,
            "depth_m": parcel_depth,
            "rectangular_area_m2": parcel_rectangular_area,
            "mismatch_warning": parcel_mismatch,
        },
        "mixed_use": {
            "total_area_m2": total_area,
            "split_difference_m2": split_difference,
            "residential": {
                "area_m2": residential_area,
                "assumption": assumption,
                "geometry": residential_result["geometry"],
                **residential_value,
            },
            "agricultural": agricultural_result,
            "total_value": combined_total,
        },
        "warnings": warnings,
    }
