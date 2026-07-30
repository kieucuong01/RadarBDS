from services.guland_coordinates import (
    evaluate_guland_coordinate_url,
    guland_identity_matches,
    normalize_guland_post_url,
    raw_coordinate_fields,
)


VALID_MAP_URL = (
    "https://www.google.com/maps/search/"
    "?api=1&query=11.028099613958%2C106.6206724626"
)


def test_valid_guland_direction_url_is_sanitized_and_accepted(monkeypatch):
    monkeypatch.setattr(
        "services.guland_coordinates.point_is_in_scoped_ward",
        lambda city, ward, lat, lng: True,
    )
    decision = evaluate_guland_coordinate_url(
        VALID_MAP_URL,
        city="THỦ DẦU MỘT",
        ward="Tân An",
    )

    assert decision.status == "valid"
    assert decision.reason == ""
    assert decision.lat == 11.028099613958
    assert decision.lng == 106.6206724626
    assert decision.sanitized_url == (
        "https://www.google.com/maps/search/"
        "?api=1&query=11.0280996%2C106.6206725"
    )


def test_invalid_latitude_is_rejected_without_decimal_repair(monkeypatch):
    monkeypatch.setattr(
        "services.guland_coordinates.point_is_in_scoped_ward",
        lambda city, ward, lat, lng: True,
    )
    decision = evaluate_guland_coordinate_url(
        "https://www.google.com/maps/search/"
        "?api=1&query=110.99336%2C106.655556689",
        city="THỦ DẦU MỘT",
        ward="Tân An",
    )

    assert decision.status == "invalid"
    assert decision.reason == "invalid_lat_lng_order"
    assert decision.lat is None
    assert decision.lng is None


def test_wrong_ward_is_rejected(monkeypatch):
    monkeypatch.setattr(
        "services.guland_coordinates.point_is_in_scoped_ward",
        lambda city, ward, lat, lng: False,
    )
    monkeypatch.setattr(
        "services.guland_coordinates.point_is_in_legacy_compatibility_zone",
        lambda city, ward, lat, lng, context_text: False,
    )
    decision = evaluate_guland_coordinate_url(
        VALID_MAP_URL,
        city="THỦ DẦU MỘT",
        ward="Phú Lợi",
    )

    assert decision.status == "invalid"
    assert decision.reason == "outside_canonical_ward"


def test_noncanonical_google_map_port_is_rejected():
    decision = evaluate_guland_coordinate_url(
        "https://www.google.com:444/maps/search/"
        "?api=1&query=11.0280996%2C106.6206725",
        city="THỦ DẦU MỘT",
        ward="Tân An",
    )

    assert decision.status == "invalid"
    assert decision.reason == "invalid_coordinate_url"


def test_guland_identity_requires_url_match_and_no_post_id_conflict():
    assert guland_identity_matches(
        "https://guland.vn/post/dat-tan-an-1231140?ref=home",
        "https://www.guland.vn/post/dat-tan-an-1231140/",
        "1231140",
        "1231140",
    )
    assert not guland_identity_matches(
        "https://guland.vn/post/dat-tan-an-1231140",
        "https://guland.vn/post/dat-khac-9999999",
        "1231140",
        "9999999",
    )
    assert not guland_identity_matches(
        "https://guland.vn/post/dat-tan-an-1231140",
        "https://guland.vn/post/dat-tan-an-1231140",
        "9999999",
        "9999999",
    )
    assert normalize_guland_post_url("https://example.com/post/a-1") is None
    assert normalize_guland_post_url(
        "https://guland.vn:444/post/dat-tan-an-1231140"
    ) is None


def test_raw_fields_require_valid_decision_and_keep_stable_names(monkeypatch):
    monkeypatch.setattr(
        "services.guland_coordinates.point_is_in_scoped_ward",
        lambda city, ward, lat, lng: True,
    )
    decision = evaluate_guland_coordinate_url(
        VALID_MAP_URL,
        city="THỦ DẦU MỘT",
        ward="Tân An",
    )

    assert raw_coordinate_fields(
        decision,
        "2026-07-30T12:34:56+07:00",
    ) == {
        "source_lat": 11.028099613958,
        "source_lng": 106.6206724626,
        "source_coordinate_url": (
            "https://www.google.com/maps/search/"
            "?api=1&query=11.0280996%2C106.6206725"
        ),
        "source_coordinate_provider": "guland_directions",
        "source_coordinate_captured_at": "2026-07-30T12:34:56+07:00",
    }
