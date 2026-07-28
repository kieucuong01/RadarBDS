from __future__ import annotations

import json

import pytest

from config.binh_duong_map import (
    BINH_DUONG_CURRENT_AREAS,
    BINH_DUONG_LEGACY_AREAS,
)
from scripts.build_binh_duong_map_data import (
    build_map_files,
    normalize_current_features,
    normalize_legacy_features,
)


def _polygon(x: float = 106.6, y: float = 11.0) -> dict:
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [x, y],
                [x + 0.01, y],
                [x + 0.01, y + 0.01],
                [x, y + 0.01],
                [x, y],
            ]
        ],
    }


def _legacy_payload() -> dict:
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"shapeName": area["source_name"]},
                "geometry": _polygon(106.5 + index * 0.01, 10.9),
            }
            for index, area in enumerate(BINH_DUONG_LEGACY_AREAS)
        ],
    }


def _current_payload() -> list[dict]:
    return [
        {
            "osm_type": "relation",
            "osm_id": area["osm_relation_id"],
            "name": f"{area['unit_type']} {area['name']}",
            "category": "boundary",
            "type": "administrative",
            "display_name": (
                f"{area['unit_type']} {area['name']}, {area['group']}, "
                "Thành phố Hồ Chí Minh, Việt Nam"
            ),
            "lat": "11.05",
            "lon": "106.70",
            "geojson": _polygon(106.6 + index * 0.001, 11.0),
        }
        for index, area in enumerate(BINH_DUONG_CURRENT_AREAS)
    ]


def test_normalizers_emit_exact_registry_order_and_public_properties():
    legacy = normalize_legacy_features(_legacy_payload())
    current = normalize_current_features(_current_payload())

    assert [feature["properties"]["slug"] for feature in legacy["features"]] == [
        area["slug"] for area in BINH_DUONG_LEGACY_AREAS
    ]
    assert [feature["properties"]["slug"] for feature in current["features"]] == [
        area["slug"] for area in BINH_DUONG_CURRENT_AREAS
    ]
    assert {feature["properties"]["layer"] for feature in legacy["features"]} == {"legacy"}
    assert {feature["properties"]["layer"] for feature in current["features"]} == {"current"}
    assert all(feature["properties"]["source"] == "geoBoundaries" for feature in legacy["features"])
    assert all(feature["properties"]["source"] == "OpenStreetMap" for feature in current["features"])


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda rows: rows.pop(), "missing OpenStreetMap relations"),
        (lambda rows: rows.append(dict(rows[0])), "duplicate OpenStreetMap relation"),
        (
            lambda rows: rows[0].update({"geojson": {"type": "Point", "coordinates": [106.7, 11.0]}}),
            "polygon geometry",
        ),
        (lambda rows: rows[0].update({"lat": "20.0", "lon": "105.0"}), "outside Bình Dương"),
        (lambda rows: rows[0].update({"display_name": "Phường khác, Việt Nam"}), "name mismatch"),
    ],
)
def test_current_normalizer_rejects_incomplete_or_untrusted_geometry(mutate, message):
    rows = _current_payload()
    mutate(rows)

    with pytest.raises(ValueError, match=message):
        normalize_current_features(rows)


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"category": "place"}, "administrative boundary"),
        ({"type": "suburb"}, "administrative boundary"),
        (
            {
                "name": "Phường khác",
                "display_name": "Phường khác, Đông Hòa, Thành phố Hồ Chí Minh, Việt Nam",
            },
            "name mismatch",
        ),
    ],
)
def test_current_normalizer_rejects_wrong_boundary_identity(updates, message):
    rows = _current_payload()
    rows[0].update(updates)

    with pytest.raises(ValueError, match=message):
        normalize_current_features(rows)


def test_legacy_normalizer_rejects_missing_or_non_polygon_features():
    missing = _legacy_payload()
    missing["features"].pop()
    with pytest.raises(ValueError, match="missing geoBoundaries features"):
        normalize_legacy_features(missing)

    invalid_geometry = _legacy_payload()
    invalid_geometry["features"][0]["geometry"] = {
        "type": "Point",
        "coordinates": [106.7, 11.0],
    }
    with pytest.raises(ValueError, match="polygon geometry"):
        normalize_legacy_features(invalid_geometry)


def test_legacy_normalizer_selects_same_name_feature_inside_binh_duong_bounds():
    payload = _legacy_payload()
    tan_uyen = next(
        feature
        for feature in payload["features"]
        if feature["properties"]["shapeName"] == "Tan Uyen"
    )
    payload["features"].insert(
        0,
        {
            "type": "Feature",
            "properties": {"shapeName": "Tan Uyen"},
            "geometry": _polygon(103.6, 22.0),
        },
    )

    normalized = normalize_legacy_features(payload)

    selected = next(
        feature
        for feature in normalized["features"]
        if feature["properties"]["slug"] == "tan-uyen"
    )
    assert selected["geometry"] == tan_uyen["geometry"]


def test_build_map_files_writes_both_snapshots_only_after_validation(tmp_path):
    metadata_url = "https://www.geoboundaries.org/api/current/gbOpen/VNM/ADM2/"
    geometry_url = "https://example.test/adm2.geojson"
    calls: list[str] = []

    def fake_http_get(url: str):
        calls.append(url)
        if url == metadata_url:
            return {"simplifiedGeometryGeoJSON": geometry_url}
        if url == geometry_url:
            return _legacy_payload()
        if "nominatim.openstreetmap.org/lookup" in url:
            return _current_payload()
        raise AssertionError(f"unexpected URL: {url}")

    legacy_path, current_path = build_map_files(tmp_path, http_get=fake_http_get)

    assert calls[:2] == [metadata_url, geometry_url]
    assert "osm_ids=R3870770" in calls[2]
    assert legacy_path.name == "legacy-districts.geojson"
    assert current_path.name == "current-36-wards.geojson"
    assert len(json.loads(legacy_path.read_text(encoding="utf-8"))["features"]) == 9
    assert len(json.loads(current_path.read_text(encoding="utf-8"))["features"]) == 36


def test_build_map_files_does_not_leave_partial_files_on_validation_failure(tmp_path):
    def fake_http_get(url: str):
        if "api/current" in url:
            return {"simplifiedGeometryGeoJSON": "https://example.test/adm2.geojson"}
        if url.endswith("adm2.geojson"):
            return _legacy_payload()
        rows = _current_payload()
        rows.pop()
        return rows

    with pytest.raises(ValueError, match="missing OpenStreetMap relations"):
        build_map_files(tmp_path, http_get=fake_http_get)

    assert not (tmp_path / "legacy-districts.geojson").exists()
    assert not (tmp_path / "current-36-wards.geojson").exists()
