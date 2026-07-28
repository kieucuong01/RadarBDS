from decimal import Decimal

import pytest

from services.tphcm_land_price_calculator import (
    build_depth_bands,
    calculate_land_price,
    calculate_mixed_land_price,
    resolve_location,
)


@pytest.mark.parametrize(
    ("width", "position", "factor"),
    [
        ("2.99", 4, Decimal("0.32")),
        ("3", 3, Decimal("0.40")),
        ("4.99", 3, Decimal("0.40")),
        ("5", 2, Decimal("0.50")),
    ],
)
def test_alley_width_boundaries_select_official_position(width, position, factor):
    result = resolve_location(
        {
            "mode": "standard",
            "access": "alley",
            "alley_min_width_m": width,
            "alley_surface": "paved",
            "distance_to_named_road_m": "20",
        }
    )

    assert result["position"] == position
    assert result["factor"] == factor


def test_dirt_and_one_hundred_meter_factors_are_explainable():
    result = resolve_location(
        {
            "mode": "standard",
            "access": "alley",
            "alley_min_width_m": "4",
            "alley_surface": "dirt",
            "distance_to_named_road_m": "100",
        }
    )

    assert result["position"] == 3
    assert result["factor"] == Decimal("0.288")
    assert result["breakdown"] == [
        {"code": "position_3", "label": "Vị trí 3", "factor": Decimal("0.40")},
        {"code": "dirt_alley", "label": "Hẻm đất", "factor": Decimal("0.80")},
        {
            "code": "distance_100m",
            "label": "Cách đường có tên từ 100m",
            "factor": Decimal("0.90"),
        },
    ]


def test_distance_below_one_hundred_meters_is_not_discounted():
    result = resolve_location(
        {
            "mode": "standard",
            "access": "alley",
            "alley_min_width_m": "4",
            "alley_surface": "paved",
            "distance_to_named_road_m": "99.99",
        }
    )

    assert result["factor"] == Decimal("0.40")


@pytest.mark.parametrize(
    ("mode", "factor"),
    [
        ("multiple_frontages", Decimal("1.10")),
        ("special_seventy_percent", Decimal("0.70")),
    ],
)
def test_special_mode_replaces_standard_alley_factors(mode, factor):
    result = resolve_location(
        {
            "mode": mode,
            "access": "alley",
            "alley_min_width_m": "2",
            "alley_surface": "dirt",
            "distance_to_named_road_m": "200",
        }
    )

    assert result["factor"] == factor
    assert len(result["breakdown"]) == 1


def test_residential_depth_bands_use_five_and_eight_frontage_multiples():
    bands = build_depth_bands("500", "5", "100", "residential")

    assert bands == [
        {"code": "front", "area_m2": Decimal("125"), "factor": Decimal("1.00")},
        {"code": "middle", "area_m2": Decimal("75"), "factor": Decimal("0.80")},
        {"code": "rear", "area_m2": Decimal("300"), "factor": Decimal("0.70")},
    ]


def test_commerce_depth_bands_use_two_and_four_frontage_multiples():
    bands = build_depth_bands("500", "5", "100", "commerce_service")

    assert bands == [
        {"code": "front", "area_m2": Decimal("50"), "factor": Decimal("1.00")},
        {"code": "middle", "area_m2": Decimal("50"), "factor": Decimal("0.60")},
        {"code": "rear", "area_m2": Decimal("400"), "factor": Decimal("0.40")},
    ]


def test_calculation_returns_average_and_total_for_each_land_type():
    result = calculate_land_price(
        {
            "residential": 10_000,
            "commerce_service": 6_000,
            "production_business": 4_000,
        },
        land_area_m2="100",
        frontage_m="5",
        depth_m="20",
        location={"mode": "standard", "access": "frontage"},
    )

    assert result["values"]["residential"]["average_unit_price"] == 10_000_000
    assert result["values"]["residential"]["total_value"] == 1_000_000_000
    assert (
        result["values"]["commerce_service"]["average_unit_price"] == 4_800_000
    )
    assert result["values"]["commerce_service"]["total_value"] == 480_000_000
    assert (
        result["values"]["production_business"]["average_unit_price"] == 3_200_000
    )
    assert result["values"]["production_business"]["total_value"] == 320_000_000


def test_geometry_mismatch_over_ten_percent_adds_warning():
    result = calculate_land_price(
        {
            "residential": 10_000,
            "commerce_service": 6_000,
            "production_business": 4_000,
        },
        land_area_m2="130",
        frontage_m="5",
        depth_m="20",
        location={"mode": "standard", "access": "frontage"},
    )

    assert result["geometry"]["mismatch_warning"] is True
    assert result["warnings"][0]["code"] == "geometry_mismatch"
    assert sum(
        band["area_m2"] for band in result["values"]["residential"]["bands"]
    ) == Decimal("130")


def test_mixed_calculation_adds_residential_and_agricultural_values():
    result = calculate_mixed_land_price(
        {
            "residential": 10_000,
            "commerce_service": 6_000,
            "production_business": 4_000,
        },
        area_name="XÃ CỦ CHI",
        land_area_m2="500",
        frontage_m="10",
        depth_m="50",
        residential_area_m2="100",
        agricultural_area_m2="400",
        residential_geometry={"use_custom": False},
        location={"mode": "standard", "access": "frontage"},
        agricultural={
            "land_type": "perennial",
            "position": 1,
            "in_residential_area": False,
            "same_parcel_has_house": False,
        },
    )

    assert result["parcel_mode"] == "mixed"
    assert result["mixed_use"]["residential"]["assumption"] == "front_strip"
    assert result["mixed_use"]["residential"]["geometry"]["frontage_m"] == Decimal(
        "10"
    )
    assert result["mixed_use"]["residential"]["geometry"]["depth_m"] == Decimal(
        "10"
    )
    assert result["mixed_use"]["residential"]["total_value"] == 1_000_000_000
    assert result["mixed_use"]["agricultural"]["unit_price"] == 840_000
    assert result["mixed_use"]["agricultural"]["total_value"] == 336_000_000
    assert result["mixed_use"]["total_value"] == 1_336_000_000


def test_mixed_calculation_accepts_split_within_one_hundredth_square_meter():
    result = calculate_mixed_land_price(
        {"residential": 10_000},
        area_name="XÃ CỦ CHI",
        land_area_m2="100",
        frontage_m="5",
        depth_m="20",
        residential_area_m2="40",
        agricultural_area_m2="59.99",
        residential_geometry={"use_custom": False},
        location={"mode": "standard", "access": "frontage"},
        agricultural={"land_type": "annual", "position": 1},
    )

    assert result["mixed_use"]["split_difference_m2"] == Decimal("0.01")


def test_mixed_calculation_rejects_area_split_outside_tolerance():
    from services.tphcm_land_price_calculator import CalculationValidationError

    with pytest.raises(CalculationValidationError) as exc_info:
        calculate_mixed_land_price(
            {"residential": 10_000},
            area_name="XÃ CỦ CHI",
            land_area_m2="100",
            frontage_m="5",
            depth_m="20",
            residential_area_m2="40",
            agricultural_area_m2="59.98",
            residential_geometry={"use_custom": False},
            location={"mode": "standard", "access": "frontage"},
            agricultural={"land_type": "annual", "position": 1},
        )

    assert "agricultural_area_m2" in exc_info.value.field_errors


def test_custom_residential_geometry_keeps_legal_area_and_warns_on_mismatch():
    result = calculate_mixed_land_price(
        {"residential": 10_000},
        area_name="XÃ CỦ CHI",
        land_area_m2="500",
        frontage_m="10",
        depth_m="50",
        residential_area_m2="100",
        agricultural_area_m2="400",
        residential_geometry={
            "use_custom": True,
            "frontage_m": "5",
            "depth_m": "30",
        },
        location={"mode": "standard", "access": "frontage"},
        agricultural={"land_type": "annual", "position": 1},
    )

    residential = result["mixed_use"]["residential"]
    assert residential["assumption"] == "custom_geometry"
    assert residential["geometry"]["legal_area_m2"] == Decimal("100")
    assert residential["geometry"]["mismatch_warning"] is True
    assert any(
        warning["code"] == "residential_geometry_mismatch"
        for warning in result["warnings"]
    )


def test_other_agricultural_prevents_a_misleading_combined_total():
    result = calculate_mixed_land_price(
        {"residential": 10_000},
        area_name="XÃ CỦ CHI",
        land_area_m2="500",
        frontage_m="10",
        depth_m="50",
        residential_area_m2="100",
        agricultural_area_m2="400",
        residential_geometry={"use_custom": False},
        location={"mode": "standard", "access": "frontage"},
        agricultural={"land_type": "other_agricultural", "position": 1},
    )

    assert result["mixed_use"]["agricultural"]["manual_review_required"] is True
    assert result["mixed_use"]["total_value"] is None
