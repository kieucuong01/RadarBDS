import pytest

from cleansing.extraction_integrity import (
    declared_total_area,
    geometry_difference_ratio,
    has_declared_total_area,
    is_irregular_geometry,
    reconcile_measurements,
    severe_geometry_conflict,
)


@pytest.mark.parametrize(
    "reported,frontage,depth,expected",
    [
        (100.0, 5.0, 20.0, 0.0),
        (100.0, 5.0, 30.0, pytest.approx(1 / 3)),
        (150.0, 5.0, 20.0, pytest.approx(1 / 3)),
    ],
)
def test_geometry_difference_is_symmetric(reported, frontage, depth, expected):
    assert geometry_difference_ratio(reported, frontage, depth) == expected


def test_regular_geometry_suppresses_only_above_forty_percent():
    assert not severe_geometry_conflict("Đất vuông đẹp", 100, 5, 33.333)
    assert severe_geometry_conflict("Đất vuông đẹp", 100, 5, 34)


@pytest.mark.parametrize("cue", ["lô xéo hậu", "đất nở hậu", "hình thang", "thắt hậu"])
def test_irregular_geometry_suppresses_only_above_sixty_percent(cue):
    assert is_irregular_geometry(cue)
    assert not severe_geometry_conflict(cue, 100, 5, 50)
    assert severe_geometry_conflict(cue, 100, 5, 51)


def test_multiple_dimension_pairs_use_irregular_threshold():
    assert not severe_geometry_conflict(
        "ngang trước 5m ngang sau 7m",
        100,
        5,
        50,
        dimension_pair_count=2,
    )


def test_bare_listing_area_is_a_declared_total_but_tho_cu_is_not():
    assert has_declared_total_area("Bán đất 225m² giá 2,65 tỷ")
    assert not has_declared_total_area("Đất thổ cư 60m², ngang 5 dài 20")


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Diện tích 100m2, ngang 5 dài 20", 100.0),
        ("Diện tích 15x71m. Tổng 1028m2", 1028.0),
        ("Diện tích 7x38m nở hậu 9m ~ 309m2", 309.0),
        ("DT 11x73 đất CLN", None),
    ],
)
def test_declared_total_area_ignores_dimension_components(text, expected):
    assert declared_total_area(text) == expected


def test_explicit_total_replaces_structured_residential_area():
    result = reconcile_measurements(
        text="DT 85m2, thổ cư 60m2, giá 1,7 tỷ",
        structured_price_ty=1.7,
        structured_area_m2=60,
        source_price_per_m2=20,
        parsed_price_ty=1.7,
        parsed_area_m2=85,
        parsed_tho_cu_m2=60,
        frontage_m=None,
        depth_m=None,
        parsed_area_is_declared_total=True,
        ambiguous_price=False,
        multi_lot=False,
    )
    assert result.area_m2 == 85
    assert result.tho_cu_m2 == 60
    assert result.price_per_m2 == 20
    assert result.repairs == ("structured_area_was_residential_area",)


def test_explicit_area_is_not_overwritten_by_dimensions_at_thirty_percent():
    result = reconcile_measurements(
        text="Diện tích 100m2, ngang 5 dài 28.5",
        structured_price_ty=2,
        structured_area_m2=100,
        source_price_per_m2=14,
        parsed_price_ty=2,
        parsed_area_m2=100,
        parsed_tho_cu_m2=None,
        frontage_m=5,
        depth_m=28.5,
        parsed_area_is_declared_total=True,
        ambiguous_price=False,
        multi_lot=False,
    )
    assert result.area_m2 == 100
    assert result.price_per_m2 == 20
    assert result.flags == ()


def test_irregular_missing_area_is_not_inferred_from_dimensions():
    result = reconcile_measurements(
        text="Lô xéo hậu ngang 5 dài 30 giá 2 tỷ",
        structured_price_ty=2,
        structured_area_m2=None,
        source_price_per_m2=None,
        parsed_price_ty=2,
        parsed_area_m2=150,
        parsed_tho_cu_m2=None,
        frontage_m=5,
        depth_m=30,
        parsed_area_is_declared_total=False,
        ambiguous_price=False,
        multi_lot=False,
    )
    assert result.area_m2 is None
    assert result.price_per_m2 is None


def test_unverified_structured_ppm_conflict_fails_closed_but_recomputes_ppm():
    result = reconcile_measurements(
        text="Bán đất giá tốt",
        structured_price_ty=2,
        structured_area_m2=100,
        source_price_per_m2=10,
        parsed_price_ty=None,
        parsed_area_m2=None,
        parsed_tho_cu_m2=None,
        frontage_m=None,
        depth_m=None,
        parsed_area_is_declared_total=False,
        ambiguous_price=False,
        multi_lot=False,
    )
    assert result.price_per_m2 == 20
    assert "price_area_inconsistent" in result.flags
