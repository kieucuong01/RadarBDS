import pytest

from cleansing.extraction_integrity import (
    geometry_difference_ratio,
    is_irregular_geometry,
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
