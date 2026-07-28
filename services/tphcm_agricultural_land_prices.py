from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


AGRICULTURAL_LAND_TYPES = (
    "perennial",
    "annual",
    "aquaculture",
    "production_forest",
    "protected_special_forest",
    "concentrated_livestock",
    "salt",
    "other_agricultural",
)

AGRICULTURAL_LAND_TYPE_LABELS = {
    "perennial": "Đất trồng cây lâu năm",
    "annual": "Đất trồng lúa/cây hàng năm",
    "aquaculture": "Đất nuôi trồng thủy sản",
    "production_forest": "Đất rừng sản xuất",
    "protected_special_forest": "Đất rừng phòng hộ/đặc dụng",
    "concentrated_livestock": "Đất chăn nuôi tập trung",
    "salt": "Đất làm muối",
    "other_agricultural": "Đất nông nghiệp khác",
}

_ZONE_AREAS = {
    1: {
        "PHƯỜNG SÀI GÒN",
        "PHƯỜNG TÂN ĐỊNH",
        "PHƯỜNG BẾN THÀNH",
        "PHƯỜNG CẦU ÔNG LÃNH",
        "PHƯỜNG BÀN CỜ",
        "PHƯỜNG XUÂN HÒA",
        "PHƯỜNG NHIÊU LỘC",
        "PHƯỜNG XÓM CHIẾU",
        "PHƯỜNG KHÁNH HỘI",
        "PHƯỜNG VĨNH HỘI",
        "PHƯỜNG CHỢ QUÁN",
        "PHƯỜNG AN ĐÔNG",
        "PHƯỜNG CHỢ LỚN",
        "PHƯỜNG BÌNH TÂY",
        "PHƯỜNG BÌNH TIÊN",
        "PHƯỜNG BÌNH PHÚ",
        "PHƯỜNG PHÚ LÂM",
        "PHƯỜNG DIÊN HỒNG",
        "PHƯỜNG VƯỜN LÀI",
        "PHƯỜNG HÒA HƯNG",
        "PHƯỜNG MINH PHỤNG",
        "PHƯỜNG BÌNH THỚI",
        "PHƯỜNG HÒA BÌNH",
        "PHƯỜNG PHÚ THỌ",
        "PHƯỜNG GIA ĐỊNH",
        "PHƯỜNG BÌNH THẠNH",
        "PHƯỜNG BÌNH LỢI TRUNG",
        "PHƯỜNG THẠNH MỸ TÂY",
        "PHƯỜNG BÌNH QUỚI",
        "PHƯỜNG ĐỨC NHUẬN",
        "PHƯỜNG CẦU KIỆU",
        "PHƯỜNG PHÚ NHUẬN",
    },
    2: {
        "PHƯỜNG TÂN THUẬN",
        "PHƯỜNG PHÚ THUẬN",
        "PHƯỜNG TÂN MỸ",
        "PHƯỜNG TÂN HƯNG",
        "PHƯỜNG CHÁNH HƯNG",
        "PHƯỜNG PHÚ ĐỊNH",
        "PHƯỜNG BÌNH ĐÔNG",
        "PHƯỜNG ĐÔNG HƯNG THUẬN",
        "PHƯỜNG TRUNG MỸ TÂY",
        "PHƯỜNG TÂN THỚI HIỆP",
        "PHƯỜNG THỚI AN",
        "PHƯỜNG AN PHÚ ĐÔNG",
        "PHƯỜNG TÂN SƠN HÒA",
        "PHƯỜNG TÂN SƠN NHẤT",
        "PHƯỜNG TÂN HÒA",
        "PHƯỜNG BẢY HIỀN",
        "PHƯỜNG TÂN BÌNH",
        "PHƯỜNG TÂN SƠN",
        "PHƯỜNG TÂY THẠNH",
        "PHƯỜNG TÂN SƠN NHÌ",
        "PHƯỜNG PHÚ THỌ HÒA",
        "PHƯỜNG TÂN PHÚ",
        "PHƯỜNG PHÚ THẠNH",
        "PHƯỜNG AN LẠC",
        "PHƯỜNG BÌNH TÂN",
        "PHƯỜNG TÂN TẠO",
        "PHƯỜNG BÌNH TRỊ ĐÔNG",
        "PHƯỜNG BÌNH HƯNG HÒA",
        "PHƯỜNG HẠNH THÔNG",
        "PHƯỜNG AN NHƠN",
        "PHƯỜNG GÒ VẤP",
        "PHƯỜNG AN HỘI ĐÔNG",
        "PHƯỜNG THÔNG TÂY HỘI",
        "PHƯỜNG AN HỘI TÂY",
        "PHƯỜNG AN KHÁNH",
        "PHƯỜNG BÌNH TRƯNG",
        "PHƯỜNG CÁT LÁI",
        "PHƯỜNG PHƯỚC LONG",
        "PHƯỜNG TĂNG NHƠN PHÚ",
        "PHƯỜNG LONG BÌNH",
        "PHƯỜNG LONG PHƯỚC",
        "PHƯỜNG LONG TRƯỜNG",
        "PHƯỜNG HIỆP BÌNH",
        "PHƯỜNG LINH XUÂN",
        "PHƯỜNG THỦ ĐỨC",
        "PHƯỜNG TAM BÌNH",
        "PHƯỜNG THỦ DẦU MỘT",
        "PHƯỜNG PHÚ LỢI",
        "PHƯỜNG CHÁNH HIỆP",
        "PHƯỜNG BÌNH DƯƠNG",
        "PHƯỜNG AN PHÚ",
        "PHƯỜNG BÌNH HÒA",
        "PHƯỜNG LÁI THIÊU",
        "PHƯỜNG THUẬN AN",
        "PHƯỜNG THUẬN GIAO",
        "PHƯỜNG ĐÔNG HÒA",
        "PHƯỜNG DĨ AN",
        "PHƯỜNG TÂN ĐÔNG HIỆP",
        "PHƯỜNG RẠCH DỪA",
        "PHƯỜNG TAM THẮNG",
        "PHƯỜNG VŨNG TÀU",
        "PHƯỜNG PHƯỚC THẮNG",
    },
    3: {
        "XÃ VĨNH LỘC",
        "XÃ TÂN VĨNH LỘC",
        "XÃ BÌNH LỢI",
        "XÃ TÂN NHỰT",
        "XÃ BÌNH CHÁNH",
        "XÃ HƯNG LONG",
        "XÃ BÌNH HƯNG",
        "XÃ CỦ CHI",
        "XÃ TÂN AN HỘI",
        "XÃ THÁI MỸ",
        "XÃ AN NHƠN TÂY",
        "XÃ NHUẬN ĐỨC",
        "XÃ PHÚ HÒA ĐÔNG",
        "XÃ BÌNH MỸ",
        "XÃ PHÚ BÌNH MỸ",
        "XÃ ĐÔNG THẠNH",
        "XÃ HÓC MÔN",
        "XÃ XUÂN THỚI SƠN",
        "XÃ BÀ ĐIỂM",
        "XÃ NHÀ BÈ",
        "XÃ HIỆP PHƯỚC",
        "XÃ CẦN GIỜ",
        "XÃ THẠNH AN",
        "XÃ BÌNH KHÁNH",
        "XÃ AN THỚI ĐÔNG",
        "PHƯỜNG TÂN HIỆP",
        "PHƯỜNG TÂN KHÁNH",
        "PHƯỜNG TÂN UYÊN",
        "PHƯỜNG BÌNH CƠ",
        "PHƯỜNG VĨNH TÂN",
        "PHƯỜNG CHÁNH PHÚ HÒA",
        "PHƯỜNG PHÚ AN",
        "PHƯỜNG HÒA LỢI",
        "PHƯỜNG BẾN CÁT",
        "PHƯỜNG LONG NGUYÊN",
        "PHƯỜNG TÂY NAM",
        "PHƯỜNG THỚI HÒA",
        "PHƯỜNG BÀ RỊA",
        "PHƯỜNG TAM LONG",
        "PHƯỜNG LONG HƯƠNG",
        "PHƯỜNG TÂN HẢI",
        "PHƯỜNG TÂN PHƯỚC",
        "PHƯỜNG TÂN THÀNH",
        "PHƯỜNG PHÚ MỸ",
    },
    4: {
        "XÃ BÀU BÀNG",
        "XÃ TRỪ VĂN THỐ",
        "XÃ THƯỜNG TÂN",
        "XÃ BẮC TÂN UYÊN",
        "XÃ PHƯỚC HÒA",
        "XÃ PHÚ GIÁO",
        "XÃ PHƯỚC THÀNH",
        "XÃ AN LONG",
        "XÃ THANH AN",
        "XÃ DẦU TIẾNG",
        "XÃ LONG HÒA",
        "XÃ MINH THẠNH",
        "XÃ NGÃI GIAO",
        "XÃ KIM LONG",
        "XÃ CHÂU ĐỨC",
        "XÃ XUÂN SƠN",
        "XÃ NGHĨA THÀNH",
        "XÃ BÌNH GIÃ",
        "XÃ ĐẤT ĐỎ",
        "XÃ LONG ĐIỀN",
        "XÃ PHƯỚC HẢI",
        "XÃ LONG HẢI",
        "XÃ HỒ TRÀM",
        "XÃ XUYÊN MỘC",
        "XÃ HÒA HIỆP",
        "XÃ HÒA HỘI",
        "XÃ BÌNH CHÂU",
        "XÃ BÀU LÂM",
        "ĐẶC KHU CÔN ĐẢO",
        "XÃ LONG SƠN",
        "XÃ CHÂU PHA",
    },
}

_ANNUAL_PRICES_VND = {
    1: {1: 1_200_000, 2: 960_000, 3: 770_000},
    2: {1: 1_000_000, 2: 800_000, 3: 640_000},
    3: {1: 700_000, 2: 560_000, 3: 450_000},
    4: {1: 480_000, 2: 380_000, 3: 300_000},
}

_PERENNIAL_PRICES_VND = {
    1: {1: 1_440_000, 2: 1_150_000, 3: 920_000},
    2: {1: 1_200_000, 2: 960_000, 3: 770_000},
    3: {1: 840_000, 2: 670_000, 3: 540_000},
    4: {1: 580_000, 2: 460_000, 3: 370_000},
}

_RESIDENTIAL_POSITION_FACTORS = {
    1: Decimal("1.00"),
    2: Decimal("0.50"),
    3: Decimal("0.40"),
}


class AgriculturalValidationError(ValueError):
    def __init__(self, field_errors: dict[str, str]):
        super().__init__("Invalid agricultural land-price input")
        self.field_errors = field_errors


def _normalise(value: object) -> str:
    text = unicodedata.normalize("NFD", str(value or "").strip().lower())
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = text.replace("đ", "d")
    return re.sub(r"\s+", " ", text)


_NORMALISED_ZONE_AREAS = {
    zone: {_normalise(area) for area in areas}
    for zone, areas in _ZONE_AREAS.items()
}


def resolve_agricultural_zone(area_name: object) -> int | None:
    key = _normalise(area_name)
    for zone, areas in _NORMALISED_ZONE_AREAS.items():
        if key in areas:
            return zone
    return None


def _positive_decimal(value: object, field: str, *, maximum: str) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise AgriculturalValidationError(
            {field: "Giá trị phải là một số hợp lệ."}
        ) from None
    if not number.is_finite() or number <= 0:
        raise AgriculturalValidationError({field: "Giá trị phải lớn hơn 0."})
    if number > Decimal(maximum):
        raise AgriculturalValidationError(
            {field: f"Giá trị không được vượt quá {maximum}."}
        )
    return number


def _whole_vnd(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _normal_unit_price(
    zone: int,
    position: int,
    land_type: str,
    residential_position_1_price_vnd: object,
) -> tuple[Decimal, bool, int | None]:
    annual = Decimal(_ANNUAL_PRICES_VND[zone][position])
    perennial = Decimal(_PERENNIAL_PRICES_VND[zone][position])
    if land_type == "annual":
        return annual, False, None
    if land_type == "perennial":
        return perennial, False, None
    if land_type in {"aquaculture", "production_forest"}:
        return annual, False, None
    if land_type == "protected_special_forest":
        return annual * Decimal("0.80"), False, None
    if land_type == "salt":
        return annual * Decimal("0.80"), False, None
    if land_type == "concentrated_livestock":
        residential_vt1 = _positive_decimal(
            residential_position_1_price_vnd,
            "agricultural.residential_base_price",
            maximum="10000000000",
        )
        cap = residential_vt1 * _RESIDENTIAL_POSITION_FACTORS[position]
        candidate = perennial * Decimal("1.50")
        return min(candidate, cap), candidate > cap, _whole_vnd(cap)
    raise AgriculturalValidationError(
        {"agricultural.land_type": "Loại đất nông nghiệp không hợp lệ."}
    )


def calculate_agricultural_land_price(
    *,
    area_name: object,
    land_type: object,
    position: object,
    area_m2: object,
    residential_position_1_price_vnd: object,
    in_residential_area: bool = False,
    same_parcel_has_house: bool = False,
) -> dict[str, object]:
    zone = resolve_agricultural_zone(area_name)
    if zone is None:
        raise AgriculturalValidationError(
            {
                "agricultural.zone": (
                    "Không xác định được vùng đất nông nghiệp từ phường/xã "
                    "đã chọn."
                )
            }
        )

    land_type_key = str(land_type or "")
    if land_type_key not in AGRICULTURAL_LAND_TYPES:
        raise AgriculturalValidationError(
            {"agricultural.land_type": "Loại đất nông nghiệp không hợp lệ."}
        )
    if isinstance(position, bool):
        position_number = 0
    else:
        try:
            position_number = int(position)
        except (TypeError, ValueError):
            position_number = 0
    if position_number not in {1, 2, 3} or str(position).strip() not in {
        "1",
        "2",
        "3",
    }:
        raise AgriculturalValidationError(
            {"agricultural.position": "Vị trí nông nghiệp phải từ 1 đến 3."}
        )

    area = _positive_decimal(
        area_m2,
        "agricultural_area_m2",
        maximum="1000000",
    )
    administrative_ward = _normalise(area_name).startswith("phuong ")
    special_context = {
        "administrative_ward": administrative_ward,
        "in_residential_area": in_residential_area is True,
        "same_parcel_has_house": same_parcel_has_house is True,
    }

    if land_type_key == "other_agricultural":
        return {
            "area_m2": area,
            "land_type": land_type_key,
            "land_type_label": AGRICULTURAL_LAND_TYPE_LABELS[land_type_key],
            "zone": zone,
            "position": position_number,
            "pricing_mode": "manual_review",
            "normal_unit_price": None,
            "special_unit_price": None,
            "unit_price": None,
            "total_value": None,
            "floor_applied": False,
            "cap_applied": False,
            "residential_cap_unit_price": None,
            "manual_review_required": True,
            "special_context": special_context,
            "formula": [
                "Đất nông nghiệp khác phải theo loại đất liền kề hoặc loại "
                "đất trước khi chuyển mục đích."
            ],
        }

    normal_price, cap_applied, residential_cap = _normal_unit_price(
        zone,
        position_number,
        land_type_key,
        residential_position_1_price_vnd,
    )
    special_applicable = land_type_key in {
        "perennial",
        "annual",
        "aquaculture",
    } and any(special_context.values())
    special_price: Decimal | None = None
    floor_applied = False
    pricing_mode = "normal_table"
    final_price = normal_price
    formula = [
        f"Giá bảng thường vùng {zone}, vị trí {position_number}: "
        f"{_whole_vnd(normal_price):,} đồng/m²."
    ]

    if special_applicable:
        residential_vt1 = _positive_decimal(
            residential_position_1_price_vnd,
            "agricultural.residential_base_price",
            maximum="10000000000",
        )
        special_perennial = residential_vt1 * Decimal("0.10")
        if position_number >= 2:
            special_perennial *= Decimal("0.80")
        if position_number >= 3:
            special_perennial *= Decimal("0.80")
        special_price = special_perennial
        if land_type_key in {"annual", "aquaculture"}:
            special_price *= Decimal("0.80")
        floor_applied = special_price < normal_price
        final_price = max(special_price, normal_price)
        pricing_mode = "article_5_8"
        formula.append(
            "Áp dụng khoản 8 Điều 5 và lấy không thấp hơn giá bảng thường."
        )
    elif land_type_key == "production_forest":
        formula.append("Rừng sản xuất bằng giá đất cây hàng năm.")
    elif land_type_key == "protected_special_forest":
        formula.append(
            "Rừng phòng hộ/đặc dụng bằng 80% giá rừng sản xuất."
        )
    elif land_type_key == "aquaculture":
        formula.append("Nuôi trồng thủy sản bằng giá đất cây hàng năm.")
    elif land_type_key == "concentrated_livestock":
        formula.append(
            "Chăn nuôi tập trung bằng 150% giá cây lâu năm và không vượt "
            "giá đất ở cùng vị trí."
        )
    elif land_type_key == "salt":
        formula.append("Đất làm muối bằng 80% giá đất cây hàng năm.")

    return {
        "area_m2": area,
        "land_type": land_type_key,
        "land_type_label": AGRICULTURAL_LAND_TYPE_LABELS[land_type_key],
        "zone": zone,
        "position": position_number,
        "pricing_mode": pricing_mode,
        "normal_unit_price": _whole_vnd(normal_price),
        "special_unit_price": (
            _whole_vnd(special_price) if special_price is not None else None
        ),
        "unit_price": _whole_vnd(final_price),
        "total_value": _whole_vnd(final_price * area),
        "floor_applied": floor_applied,
        "cap_applied": cap_applied,
        "residential_cap_unit_price": residential_cap,
        "manual_review_required": False,
        "special_context": special_context,
        "formula": formula,
    }
