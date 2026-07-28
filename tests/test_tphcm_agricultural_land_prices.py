import json
from decimal import Decimal
from pathlib import Path

import pytest

from services.tphcm_agricultural_land_prices import (
    AgriculturalValidationError,
    calculate_agricultural_land_price,
    resolve_agricultural_zone,
)


@pytest.mark.parametrize(
    ("area_name", "expected_zone"),
    [
        ("PHƯỜNG SÀI GÒN", 1),
        ("phường Phú Nhuận", 1),
        ("PHƯỜNG THỦ DẦU MỘT", 2),
        ("PHƯỜNG PHƯỚC THẮNG", 2),
        ("XÃ CỦ CHI", 3),
        ("PHƯỜNG BẾN CÁT", 3),
        ("XÃ PHÚ BÌNH MỸ", 3),
        ("XÃ BÀU BÀNG", 4),
        ("ĐẶC KHU CÔN ĐẢO", 4),
    ],
)
def test_official_area_names_resolve_to_their_article_3_zone(
    area_name,
    expected_zone,
):
    assert resolve_agricultural_zone(area_name) == expected_zone


def test_every_searchable_administrative_area_has_an_agricultural_zone():
    data = json.loads(
        Path("static/data/tphcm_land_prices_2026.json").read_text(
            encoding="utf-8"
        )
    )
    areas = {row["area"] for row in data["rows"]}
    unresolved = {
        area
        for area in areas
        if area != "KHU CÔNG NGHỆ CAO"
        and resolve_agricultural_zone(area) is None
    }

    assert unresolved == set()
    assert resolve_agricultural_zone("KHU CÔNG NGHỆ CAO") is None


@pytest.mark.parametrize(
    ("zone_area", "position", "annual_vnd", "perennial_vnd"),
    [
        ("PHƯỜNG SÀI GÒN", 1, 1_200_000, 1_440_000),
        ("PHƯỜNG SÀI GÒN", 2, 960_000, 1_150_000),
        ("PHƯỜNG SÀI GÒN", 3, 770_000, 920_000),
        ("PHƯỜNG THỦ DẦU MỘT", 1, 1_000_000, 1_200_000),
        ("PHƯỜNG THỦ DẦU MỘT", 2, 800_000, 960_000),
        ("PHƯỜNG THỦ DẦU MỘT", 3, 640_000, 770_000),
        ("XÃ CỦ CHI", 1, 700_000, 840_000),
        ("XÃ CỦ CHI", 2, 560_000, 670_000),
        ("XÃ CỦ CHI", 3, 450_000, 540_000),
        ("XÃ BÀU BÀNG", 1, 480_000, 580_000),
        ("XÃ BÀU BÀNG", 2, 380_000, 460_000),
        ("XÃ BÀU BÀNG", 3, 300_000, 370_000),
    ],
)
def test_official_annual_and_perennial_price_tables(
    zone_area,
    position,
    annual_vnd,
    perennial_vnd,
):
    annual = calculate_agricultural_land_price(
        area_name=zone_area,
        land_type="annual",
        position=position,
        area_m2=100,
        residential_position_1_price_vnd=1_000_000,
    )
    perennial = calculate_agricultural_land_price(
        area_name=zone_area,
        land_type="perennial",
        position=position,
        area_m2=100,
        residential_position_1_price_vnd=1_000_000,
    )

    assert annual["normal_unit_price"] == annual_vnd
    assert perennial["normal_unit_price"] == perennial_vnd


@pytest.mark.parametrize(
    ("land_type", "expected_unit_price"),
    [
        ("production_forest", 700_000),
        ("protected_special_forest", 560_000),
        ("aquaculture", 700_000),
        ("salt", 560_000),
    ],
)
def test_derived_agricultural_types_use_the_official_formula(
    land_type,
    expected_unit_price,
):
    result = calculate_agricultural_land_price(
        area_name="XÃ CỦ CHI",
        land_type=land_type,
        position=1,
        area_m2=100,
        residential_position_1_price_vnd=10_000_000,
    )

    assert result["unit_price"] == expected_unit_price
    assert result["total_value"] == expected_unit_price * 100


def test_livestock_price_is_capped_by_residential_price_at_same_position():
    uncapped = calculate_agricultural_land_price(
        area_name="XÃ CỦ CHI",
        land_type="concentrated_livestock",
        position=2,
        area_m2=100,
        residential_position_1_price_vnd=10_000_000,
    )
    capped = calculate_agricultural_land_price(
        area_name="XÃ CỦ CHI",
        land_type="concentrated_livestock",
        position=2,
        area_m2=100,
        residential_position_1_price_vnd=1_000_000,
    )

    assert uncapped["unit_price"] == 1_005_000
    assert uncapped["cap_applied"] is False
    assert capped["unit_price"] == 500_000
    assert capped["cap_applied"] is True


@pytest.mark.parametrize(
    ("land_type", "position", "expected_unit_price"),
    [
        ("perennial", 1, 68_720_000),
        ("perennial", 2, 54_976_000),
        ("perennial", 3, 43_980_800),
        ("annual", 1, 54_976_000),
        ("aquaculture", 2, 43_980_800),
    ],
)
def test_article_5_8_applies_automatically_inside_a_ward(
    land_type,
    position,
    expected_unit_price,
):
    result = calculate_agricultural_land_price(
        area_name="PHƯỜNG SÀI GÒN",
        land_type=land_type,
        position=position,
        area_m2=100,
        residential_position_1_price_vnd=687_200_000,
    )

    assert result["pricing_mode"] == "article_5_8"
    assert result["special_context"]["administrative_ward"] is True
    assert result["unit_price"] == expected_unit_price
    assert result["floor_applied"] is False


def test_article_5_8_on_a_commune_requires_user_context():
    normal = calculate_agricultural_land_price(
        area_name="XÃ CỦ CHI",
        land_type="perennial",
        position=1,
        area_m2=100,
        residential_position_1_price_vnd=20_000_000,
    )
    special = calculate_agricultural_land_price(
        area_name="XÃ CỦ CHI",
        land_type="perennial",
        position=1,
        area_m2=100,
        residential_position_1_price_vnd=20_000_000,
        in_residential_area=True,
    )

    assert normal["pricing_mode"] == "normal_table"
    assert normal["unit_price"] == 840_000
    assert special["pricing_mode"] == "article_5_8"
    assert special["unit_price"] == 2_000_000


def test_article_5_8_never_drops_below_the_normal_table():
    result = calculate_agricultural_land_price(
        area_name="XÃ CỦ CHI",
        land_type="perennial",
        position=1,
        area_m2=100,
        residential_position_1_price_vnd=1_000_000,
        same_parcel_has_house=True,
    )

    assert result["special_unit_price"] == 100_000
    assert result["normal_unit_price"] == 840_000
    assert result["unit_price"] == 840_000
    assert result["floor_applied"] is True


def test_article_5_8_does_not_change_forest_livestock_or_salt_formula():
    result = calculate_agricultural_land_price(
        area_name="PHƯỜNG SÀI GÒN",
        land_type="salt",
        position=1,
        area_m2=100,
        residential_position_1_price_vnd=687_200_000,
    )

    assert result["pricing_mode"] == "normal_table"
    assert result["special_unit_price"] is None
    assert result["unit_price"] == 960_000


def test_other_agricultural_requires_manual_review_and_has_no_total():
    result = calculate_agricultural_land_price(
        area_name="XÃ CỦ CHI",
        land_type="other_agricultural",
        position=1,
        area_m2=100,
        residential_position_1_price_vnd=10_000_000,
    )

    assert result["manual_review_required"] is True
    assert result["unit_price"] is None
    assert result["total_value"] is None


@pytest.mark.parametrize(
    ("kwargs", "field"),
    [
        ({"area_name": "KHU CÔNG NGHỆ CAO"}, "agricultural.zone"),
        ({"land_type": "forged"}, "agricultural.land_type"),
        ({"position": 4}, "agricultural.position"),
        ({"area_m2": "NaN"}, "agricultural_area_m2"),
    ],
)
def test_agricultural_calculation_rejects_untrusted_values(kwargs, field):
    values = {
        "area_name": "XÃ CỦ CHI",
        "land_type": "annual",
        "position": 1,
        "area_m2": 100,
        "residential_position_1_price_vnd": 10_000_000,
    }
    values.update(kwargs)

    with pytest.raises(AgriculturalValidationError) as exc_info:
        calculate_agricultural_land_price(**values)

    assert field in exc_info.value.field_errors


def test_calculation_keeps_decimal_area_without_float_drift():
    result = calculate_agricultural_land_price(
        area_name="XÃ CỦ CHI",
        land_type="annual",
        position=1,
        area_m2="0.01",
        residential_position_1_price_vnd=10_000_000,
    )

    assert result["area_m2"] == Decimal("0.01")
    assert result["total_value"] == 7_000
