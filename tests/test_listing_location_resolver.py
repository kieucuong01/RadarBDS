import inspect
import json

import pytest

from services.listing_location_resolver import (
    LocationRegistry,
    listing_location_signature,
    load_location_registry,
    normalize_location_token,
    normalize_road_token,
    resolve_listing_location,
)
from services.listing_map_context import extract_map_location_context


def _road(*, lat=10.981, lng=106.689, landmark_keys=()):
    return {
        "lat": lat,
        "lng": lng,
        "accuracy_radius_m": 90,
        "label": "Theo tên đường ĐX 43, Phú Lợi",
        "source": "OpenStreetMap",
        "landmark_keys": list(landmark_keys),
    }


def _registry():
    return LocationRegistry(
        resolver_version="osm-test-v2",
        roads={
            ("THỦ DẦU MỘT", "phu loi", "dx 43"): (_road(),),
            ("THỦ DẦU MỘT", "phu loi", "duong so 35"): (
                _road(
                    lat=10.982,
                    lng=106.690,
                    landmark_keys=("tdc phu chanh b",),
                ),
                _road(
                    lat=10.983,
                    lng=106.691,
                    landmark_keys=("tdc phu chanh d",),
                ),
            ),
        },
        landmarks={
            ("THỦ DẦU MỘT", "phu loi", "tdc phu chanh b"): {
                "lat": 10.982,
                "lng": 106.690,
                "accuracy_radius_m": 140,
                "label": "Theo địa danh TĐC Phú Chánh B",
                "source": "OpenStreetMap",
            },
            ("THỦ DẦU MỘT", "phu loi", "tdc phu chanh d"): {
                "lat": 10.983,
                "lng": 106.691,
                "accuracy_radius_m": 140,
                "label": "Theo địa danh TĐC Phú Chánh D",
                "source": "OpenStreetMap",
            },
        },
        wards={
            ("THỦ DẦU MỘT", "phu loi"): {
                "lat": 10.984,
                "lng": 106.684,
                "label": "Theo trung tâm Phú Lợi",
                "source": "OpenStreetMap",
            }
        },
    )


def _resolve(text="", **extra):
    listing = {
        "id": extra.pop("id", 10),
        "city": "THỦ DẦU MỘT",
        "ward": "Phú Lợi",
        "title": text,
        "description": "",
        "road_name": extra.pop("road_name", ""),
        **extra,
    }
    context = extract_map_location_context(
        listing["title"],
        listing["description"],
        listing["road_name"],
    )
    return resolve_listing_location(listing, _registry(), context)


def test_resolution_precedence_exact_road_landmark_nearby_ward():
    exact = _resolve(source_lat=10.991, source_lng=106.701)
    road = _resolve(text="Mặt tiền DX43")
    landmark = _resolve(text="TĐC Phú Chánh D")
    nearby = _resolve(text="Cách DX43 100m")
    ward = _resolve(text="Đất đẹp dân cư đông")

    assert [
        item.location.precision for item in (exact, road, landmark, nearby, ward)
    ] == ["exact", "road", "landmark", "nearby", "ward"]
    assert nearby.location.accuracy_radius_m >= 100
    assert nearby.location.relation == "near"


def test_nearby_relation_stays_approximate_when_landmark_also_matches():
    result = _resolve(
        text="Cách Đường số 35 100m, TĐC Phú Chánh B"
    )

    assert result.location.precision == "nearby"
    assert result.location.relation == "near"
    assert result.location.landmark_key == "tdc phu chanh b"
    assert result.location.accuracy_radius_m >= 100


def test_ambiguous_road_uses_honest_ward_until_landmark_disambiguates():
    ambiguous = _resolve(text="Mặt tiền Đường số 35")
    scoped = _resolve(text="Đường số 35, TĐC Phú Chánh D")

    assert ambiguous.location.precision == "ward"
    assert ambiguous.location.resolution_status == "ambiguous"
    assert ambiguous.issue.status == "ambiguous"
    assert scoped.location.precision == "road"
    assert scoped.location.landmark_key == "tdc phu chanh d"
    assert (scoped.location.lat, scoped.location.lng) == (10.983, 106.691)


def test_road_landmark_conflict_does_not_silently_choose_road():
    registry = _registry()
    registry = LocationRegistry(
        resolver_version=registry.resolver_version,
        roads={
            **registry.roads,
            ("THỦ DẦU MỘT", "phu loi", "dx 43"): (
                _road(landmark_keys=("tdc phu chanh b",)),
            ),
        },
        landmarks=registry.landmarks,
        wards=registry.wards,
    )
    listing = {
        "id": 11,
        "city": "THỦ DẦU MỘT",
        "ward": "Phú Lợi",
        "title": "Mặt tiền DX43, TĐC Phú Chánh D",
        "description": "",
        "road_name": "",
    }
    context = extract_map_location_context(listing["title"], "")

    result = resolve_listing_location(listing, registry, context)

    assert result.location.precision == "ward"
    assert result.location.resolution_reason == "road_landmark_conflict"
    assert result.issue.resolution_note == "road_landmark_conflict"


def test_unique_road_keeps_unmatched_landmark_in_coverage_queue():
    result = _resolve(text="Mặt tiền DX43, TĐC Khu Mới")

    assert result.location.precision == "road"
    assert result.issue.status == "not_found"
    assert result.issue.landmark_candidate == "tdc khu moi"
    assert result.issue.resolution_note == "landmark_not_found"


def test_ambiguous_landmark_uses_honest_ward_and_enters_coverage():
    registry = _registry()
    first = registry.landmarks[
        ("THỦ DẦU MỘT", "phu loi", "tdc phu chanh b")
    ]
    registry = LocationRegistry(
        resolver_version=registry.resolver_version,
        roads=registry.roads,
        landmarks={
            **registry.landmarks,
            ("THỦ DẦU MỘT", "phu loi", "tdc khu moi"): (
                first,
                {**first, "lat": 10.991, "lng": 106.699},
            ),
        },
        wards=registry.wards,
    )
    listing = {
        "id": 16,
        "city": "THỦ DẦU MỘT",
        "ward": "Phú Lợi",
        "title": "TĐC Khu Mới",
        "description": "",
        "road_name": "",
    }
    context = extract_map_location_context(listing["title"], "")

    result = resolve_listing_location(listing, registry, context)

    assert result.location.precision == "ward"
    assert result.location.resolution_status == "ambiguous"
    assert result.issue.status == "ambiguous"
    assert result.issue.resolution_note == "ambiguous_landmark"


def test_valid_source_coordinate_wins_over_road_and_ward():
    result = _resolve(
        id=77,
        road_name="ĐX 43",
        source_lat=10.991,
        source_lng=106.701,
        source="facebook",
    )

    resolved = result.location
    assert resolved.listing_id == 77
    assert resolved.precision == "exact"
    assert resolved.location_key == "exact:77"
    assert (resolved.lat, resolved.lng) == (10.991, 106.701)
    assert result.issue is None


def test_road_punctuation_variants_resolve_to_one_deterministic_point():
    locations = [
        _resolve(road_name=road_name).location
        for road_name in ("ĐX-43", "ĐX 43", "đx.43", "DX043", "Đường ĐX 43")
    ]

    assert {item.precision for item in locations} == {"road"}
    assert {(item.lat, item.lng) for item in locations} == {(10.981, 106.689)}
    assert {item.location_key for item in locations} == {
        "road:thu-dau-mot:phu-loi:dx-43"
    }
    assert len({item.signature for item in locations}) == 1


def test_unknown_road_uses_ward_and_records_not_found_issue():
    result = _resolve(road_name="Đường chưa có")

    assert result.location.precision == "ward"
    assert result.location.resolution_status == "not_found"
    assert result.issue.status == "not_found"
    assert result.issue.road_candidate == "duong chua co"


def test_unknown_ward_returns_issue_without_location():
    listing = {
        "id": 13,
        "city": "THỦ DẦU MỘT",
        "ward": "Không rõ",
        "title": "Mặt tiền DX43",
        "description": "",
        "road_name": "",
    }
    context = extract_map_location_context(listing["title"], "")
    result = resolve_listing_location(listing, _registry(), context)

    assert result.location is None
    assert result.issue.status == "not_found"


def test_signature_and_coordinates_are_stable_without_randomness():
    listing = {
        "id": 14,
        "city": "THỦ DẦU MỘT",
        "ward": "Phú Lợi",
        "road_name": "ĐX 43",
    }
    context = extract_map_location_context("", "", "ĐX 43")

    first = resolve_listing_location(listing, _registry(), context)
    second = resolve_listing_location(dict(listing), _registry(), context)

    assert first == second
    assert listing_location_signature(
        listing, context, "osm-test-v2"
    ) == listing_location_signature(dict(listing), context, "osm-test-v2")
    assert "import random" not in inspect.getsource(resolve_listing_location)
    assert normalize_location_token(" ĐX.  43 ") == "dx 43"
    assert normalize_road_token("DX0143") == "dx 143"
    assert normalize_road_token("Đường ĐX 143") == "dx 143"
    assert normalize_road_token("Đường 88") == "duong so 88"


def test_registry_loader_preserves_road_ambiguity_and_landmark_aliases(tmp_path):
    ward_path = tmp_path / "wards.json"
    road_path = tmp_path / "roads.json"
    landmark_path = tmp_path / "landmarks.json"
    ward_path.write_text(
        json.dumps(
            {
                "resolver_version": "v2",
                "wards": [
                    {
                        "city": "THỦ DẦU MỘT",
                        "normalized_ward": "phu loi",
                        "lat": 10.98,
                        "lng": 106.68,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    road_path.write_text(
        json.dumps(
            {
                "resolver_version": "v2",
                "roads": [
                    {
                        "city": "THỦ DẦU MỘT",
                        "normalized_ward": "phu loi",
                        "normalized_road": "duong so 35",
                        "aliases": ["duong 35"],
                        "lat": 10.98,
                        "lng": 106.68,
                    },
                    {
                        "city": "THỦ DẦU MỘT",
                        "normalized_ward": "phu loi",
                        "normalized_road": "duong so 35",
                        "aliases": ["duong 35"],
                        "lat": 10.99,
                        "lng": 106.69,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    landmark_path.write_text(
        json.dumps(
            {
                "resolver_version": "v2",
                "landmarks": [
                    {
                        "city": "THỦ DẦU MỘT",
                        "normalized_ward": "phu loi",
                        "normalized_landmark": "tdc phu chanh b",
                        "aliases": ["tai dinh cu phu chanh b"],
                        "lat": 10.98,
                        "lng": 106.68,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    registry = load_location_registry(
        ward_path=ward_path,
        road_path=road_path,
        landmark_path=landmark_path,
    )

    assert len(
        registry.roads[("THỦ DẦU MỘT", "phu loi", "duong so 35")]
    ) == 2
    assert (
        "THỦ DẦU MỘT",
        "phu loi",
        "tai dinh cu phu chanh b",
    ) in registry.landmarks


def test_registry_loader_rejects_mismatched_landmark_version(tmp_path):
    for name, content in {
        "wards.json": {"resolver_version": "v2", "wards": []},
        "roads.json": {"resolver_version": "v2", "roads": []},
        "landmarks.json": {"resolver_version": "old", "landmarks": []},
    }.items():
        (tmp_path / name).write_text(json.dumps(content), encoding="utf-8")

    with pytest.raises(ValueError, match="versions do not match"):
        load_location_registry(
            ward_path=tmp_path / "wards.json",
            road_path=tmp_path / "roads.json",
            landmark_path=tmp_path / "landmarks.json",
        )
