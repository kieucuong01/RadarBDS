import inspect

from services.listing_location_resolver import (
    LocationRegistry,
    listing_location_signature,
    normalize_location_token,
    normalize_road_token,
    resolve_listing_location,
)


def _registry():
    return LocationRegistry(
        resolver_version="osm-test-v1",
        roads={
            ("THỦ DẦU MỘT", "phu loi", "dx 43"): {
                "lat": 10.981,
                "lng": 106.689,
                "label": "Theo tên đường ĐX 43, Phú Lợi",
                "source": "OpenStreetMap",
            }
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


def test_valid_source_coordinate_wins_over_road_and_ward():
    resolved = resolve_listing_location(
        {
            "id": 77,
            "city": "THỦ DẦU MỘT",
            "ward": "Phú Lợi",
            "road_name": "ĐX 43",
            "source_lat": 10.991,
            "source_lng": 106.701,
            "source": "facebook",
        },
        _registry(),
    )

    assert resolved is not None
    assert resolved.listing_id == 77
    assert resolved.precision == "exact"
    assert resolved.location_key == "exact:77"
    assert (resolved.lat, resolved.lng) == (10.991, 106.701)


def test_road_punctuation_variants_resolve_to_one_deterministic_point():
    locations = []
    for road_name in ("ĐX-43", "ĐX 43", "đx.43", "DX43", "Đường ĐX 43"):
        locations.append(
            resolve_listing_location(
                {
                    "id": 10,
                    "city": "THỦ DẦU MỘT",
                    "ward": "Phú Lợi",
                    "road_name": road_name,
                },
                _registry(),
            )
        )

    assert {item.precision for item in locations} == {"road"}
    assert {(item.lat, item.lng) for item in locations} == {(10.981, 106.689)}
    assert {item.location_key for item in locations} == {
        "road:thu-dau-mot:phu-loi:dx-43"
    }
    assert len({item.signature for item in locations}) == 1


def test_road_never_matches_across_wards_and_unknown_road_uses_ward_center():
    wrong_ward = resolve_listing_location(
        {
            "id": 11,
            "city": "THỦ DẦU MỘT",
            "ward": "Phú Hòa",
            "road_name": "ĐX 43",
        },
        _registry(),
    )
    unknown_road = resolve_listing_location(
        {
            "id": 12,
            "city": "THỦ DẦU MỘT",
            "ward": "Phú Lợi",
            "road_name": "Đường chưa có",
        },
        _registry(),
    )

    assert wrong_ward is None
    assert unknown_road is not None
    assert unknown_road.precision == "ward"
    assert unknown_road.location_key == "ward:thu-dau-mot:phu-loi"


def test_unknown_ward_is_unmapped():
    assert (
        resolve_listing_location(
            {
                "id": 13,
                "city": "THỦ DẦU MỘT",
                "ward": "Không rõ",
                "road_name": "ĐX 43",
            },
            _registry(),
        )
        is None
    )


def test_signature_and_coordinates_are_stable_without_randomness():
    listing = {
        "id": 14,
        "city": "THỦ DẦU MỘT",
        "ward": "Phú Lợi",
        "road_name": "ĐX 43",
    }

    first = resolve_listing_location(listing, _registry())
    second = resolve_listing_location(dict(listing), _registry())

    assert first == second
    assert listing_location_signature(listing) == listing_location_signature(
        dict(listing)
    )
    assert "import random" not in inspect.getsource(resolve_listing_location)
    assert normalize_location_token(" ĐX.  43 ") == "dx 43"
    assert normalize_road_token("DX143") == "dx 143"
    assert normalize_road_token("Đường ĐX 143") == "dx 143"


def test_out_of_service_source_coordinates_fall_back_instead_of_becoming_exact():
    resolved = resolve_listing_location(
        {
            "id": 15,
            "city": "THỦ DẦU MỘT",
            "ward": "Phú Lợi",
            "road_name": "ĐX 43",
            "source_lat": 20.0,
            "source_lng": 105.0,
        },
        _registry(),
    )

    assert resolved is not None
    assert resolved.precision == "road"
