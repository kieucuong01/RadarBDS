import json
from pathlib import Path

import pytest
from shapely.geometry import Polygon, shape


ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {
    "thuan-an": {
        "legacy": "legacy-10-wards.geojson",
        "current": "current-5-wards.geojson",
        "legacy_count": 10,
        "current_count": 5,
        "derived": {"Vĩnh Phú"},
    },
    "di-an": {
        "legacy": "legacy-7-wards.geojson",
        "current": "current-3-wards.geojson",
        "legacy_count": 7,
        "current_count": 3,
        "derived": {"An Bình"},
    },
    "ben-cat": {
        "legacy": "legacy-8-units.geojson",
        "current": "current-6-wards.geojson",
        "legacy_count": 8,
        "current_count": 6,
        "derived": set(),
    },
}


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("city_slug", EXPECTED)
def test_checked_city_boundary_snapshots_have_exact_valid_taxonomy(city_slug):
    expected = EXPECTED[city_slug]
    legacy = _read(
        ROOT / "static" / "maps" / city_slug / expected["legacy"]
    )
    current = _read(
        ROOT / "static" / "maps" / city_slug / expected["current"]
    )

    assert len(legacy["features"]) == expected["legacy_count"]
    assert len(current["features"]) == expected["current_count"]
    assert len(
        {feature["properties"]["slug"] for feature in legacy["features"]}
    ) == expected["legacy_count"]
    assert len(
        {feature["properties"]["slug"] for feature in current["features"]}
    ) == expected["current_count"]
    assert all(
        shape(feature["geometry"]).is_valid
        and shape(feature["geometry"]).geom_type in {"Polygon", "MultiPolygon"}
        for feature in (*legacy["features"], *current["features"])
    )


@pytest.mark.parametrize("city_slug", EXPECTED)
def test_only_declared_city_boundaries_are_marked_as_derived(city_slug):
    expected = EXPECTED[city_slug]
    payload = _read(
        ROOT / "static" / "maps" / city_slug / expected["legacy"]
    )

    derived = {
        feature["properties"]["name"]
        for feature in payload["features"]
        if feature["properties"]["boundary_source"] == "derived_boundary"
    }

    assert derived == expected["derived"]
    for feature in payload["features"]:
        properties = feature["properties"]
        if properties["name"] in expected["derived"]:
            assert properties["boundary_confidence"] == "derived_reference"
            assert properties["derived_from"]
        else:
            assert properties["boundary_confidence"] == "source_snapshot"
            assert properties["source_id"].startswith("FID:")


def test_ben_cat_legacy_snapshot_keeps_phu_an_as_commune():
    payload = _read(
        ROOT / "static/maps/ben-cat/legacy-8-units.geojson"
    )
    phu_an = next(
        feature
        for feature in payload["features"]
        if feature["properties"]["name"] == "Phú An"
    )

    assert phu_an["properties"]["unit_type"] == "Xã cũ"


def test_residual_builder_keeps_meaningful_pieces_and_rejects_overlap():
    from scripts.build_city_map_boundaries import derive_residual_boundary

    target = Polygon([(0, 0), (4, 0), (4, 2), (0, 2)])
    sourced = Polygon([(0, 0), (3, 0), (3, 2), (0, 2)])

    derived = derive_residual_boundary(
        target,
        (sourced,),
        context="missing unit",
    )

    assert derived.equals(Polygon([(3, 0), (4, 0), (4, 2), (3, 2)]))
    assert derived.intersection(sourced).area == pytest.approx(0)


def test_residual_builder_discards_disconnected_boundary_mismatch_sliver():
    from scripts.build_city_map_boundaries import derive_residual_boundary

    target = Polygon([(0, 0), (10, 0), (10, 2), (0, 2)])
    sourced = Polygon([(2, 0), (9, 0), (9, 2), (2, 2)])

    derived = derive_residual_boundary(
        target,
        (sourced,),
        context="missing unit with mismatch",
    )

    assert derived.equals(Polygon([(0, 0), (2, 0), (2, 2), (0, 2)]))


def test_builder_rejects_unknown_city_before_fetching_sources():
    from scripts.build_city_map_boundaries import build_city_boundaries

    with pytest.raises(KeyError):
        build_city_boundaries("../../../windows", [])
