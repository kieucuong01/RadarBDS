import pytest

from services.listing_location_auto_registry import (
    BrowserLocationEvidence,
    canonical_evidence_hash,
    evaluate_browser_evidence,
    parse_google_maps_coordinates,
)


PHU_CHANH_B_URL = (
    "https://www.google.com/maps/place/"
    "Khu+t%C3%A1i+%C4%91%E1%BB%8Bnh+c%C6%B0+Ph%C3%BA+Ch%C3%A1nh+B/"
    "@11.058782,106.7015151,17z/data=!3m1!4b1"
    "!4m6!3m5!1s0x3174cfc3c87ff1b1:0x62a06002cd918551"
    "!8m2!3d11.058782!4d106.7015151!16s%2Fg%2F11ggg3n5ns"
)


def _phu_chanh_b_evidence(**changes):
    data = {
        "candidate_key": "landmark:thu-dau-mot:phu-tan:tdc-phu-chanh-b",
        "candidate_type": "landmark",
        "city": "THỦ DẦU MỘT",
        "ward": "Phú Tân",
        "canonical": "TĐC Phú Chánh B",
        "aliases": [
            "TDC Phu Chanh B",
            "Khu tái định cư Phú Chánh B",
        ],
        "query": "TĐC Phú Chánh B, Phú Tân, Thủ Dầu Một",
        "result_title": "Khu tái định cư Phú Chánh B",
        "result_address": "Đ. Số 55, Khu TĐC Phú Chánh B",
        "result_type": "Housing complex",
        "source_url": PHU_CHANH_B_URL,
        "unique_result": True,
        "checked_at": "2026-07-29T16:00:00Z",
    }
    data.update(changes)
    return BrowserLocationEvidence.from_mapping(data)


def test_google_maps_url_parser_accepts_public_place_coordinates():
    assert parse_google_maps_coordinates(PHU_CHANH_B_URL) == (
        11.058782,
        106.7015151,
    )


def test_google_maps_url_parser_rejects_non_google_and_out_of_bounds_urls():
    assert parse_google_maps_coordinates(
        "https://example.com/@11.058782,106.7015151,17z"
    ) is None
    assert parse_google_maps_coordinates(
        "https://www.google.com/maps/@50.0,5.0,17z"
    ) is None


def test_exact_landmark_inside_ward_auto_accepts_at_high_confidence():
    decision = evaluate_browser_evidence(
        _phu_chanh_b_evidence(),
        manual_keys=frozenset(),
        ward_contains=lambda city, ward, lat, lng: True,
    )

    assert decision.status == "accepted"
    assert decision.confidence >= 0.90
    assert decision.reasons == ()
    assert decision.override["lat"] == 11.058782
    assert decision.override["lng"] == 106.7015151
    assert decision.override["candidate_key"].endswith("tdc-phu-chanh-b")
    assert len(decision.override["evidence_hash"]) == 64


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"unique_result": False}, "multiple_or_unselected_result"),
        ({"result_title": "Phú Chánh"}, "title_mismatch"),
        ({"result_type": "Coffee shop"}, "invalid_result_type"),
        ({"source_url": "https://example.com/maps"}, "invalid_source_url"),
        ({"checked_at": ""}, "missing_evidence"),
    ],
)
def test_low_confidence_evidence_is_quarantined(changes, reason):
    decision = evaluate_browser_evidence(
        _phu_chanh_b_evidence(**changes),
        manual_keys=frozenset(),
        ward_contains=lambda city, ward, lat, lng: True,
    )

    assert decision.status == "quarantined"
    assert reason in decision.reasons
    assert decision.override is None


def test_manual_override_conflict_is_quarantined():
    evidence = _phu_chanh_b_evidence()
    decision = evaluate_browser_evidence(
        evidence,
        manual_keys=frozenset({evidence.candidate_key}),
        ward_contains=lambda city, ward, lat, lng: True,
    )

    assert decision.status == "quarantined"
    assert decision.reasons == ("manual_override_conflict",)


def test_candidate_key_cannot_retarget_evidence_to_another_identity():
    decision = evaluate_browser_evidence(
        _phu_chanh_b_evidence(
            candidate_key=(
                "landmark:thu-dau-mot:phu-tan:tdc-dinh-hoa"
            )
        ),
        manual_keys=frozenset(),
        ward_contains=lambda city, ward, lat, lng: True,
    )

    assert decision.status == "quarantined"
    assert "candidate_identity_mismatch" in decision.reasons


def test_point_outside_scoped_ward_without_address_match_is_quarantined():
    decision = evaluate_browser_evidence(
        _phu_chanh_b_evidence(result_address="Đường số 55"),
        manual_keys=frozenset(),
        ward_contains=lambda city, ward, lat, lng: False,
    )

    assert decision.status == "quarantined"
    assert "ward_mismatch" in decision.reasons


def test_phu_chanh_legacy_zone_is_an_explicit_boundary_compatibility():
    decision = evaluate_browser_evidence(
        _phu_chanh_b_evidence(),
        manual_keys=frozenset(),
        ward_contains=lambda city, ward, lat, lng: False,
    )

    assert decision.status == "accepted"
    assert decision.override["allow_boundary_mismatch"] is True
    assert "canonical Phú Tân" in (
        decision.override["boundary_mismatch_reason"]
    )


def test_numbered_road_requires_full_token_and_ward_scope():
    evidence = _phu_chanh_b_evidence(
        candidate_key="road:thu-dau-mot:phu-tan:duong-so-35",
        candidate_type="road",
        canonical="Đường số 35",
        aliases=["Đường 35"],
        result_title="Đường số 35",
        result_address="Phú Tân, Thủ Dầu Một",
        result_type="Road",
    )
    decision = evaluate_browser_evidence(
        evidence,
        manual_keys=frozenset(),
        ward_contains=lambda city, ward, lat, lng: True,
    )

    assert decision.status == "accepted"


def test_evidence_hash_is_stable_when_alias_input_order_changes():
    first = _phu_chanh_b_evidence()
    second = _phu_chanh_b_evidence(aliases=list(reversed(first.aliases)))

    assert canonical_evidence_hash(first) == canonical_evidence_hash(second)


def test_evidence_mapping_rejects_invalid_candidate_type_and_alias_shape():
    with pytest.raises(ValueError, match="candidate_type"):
        _phu_chanh_b_evidence(candidate_type="business")
    with pytest.raises(ValueError, match="aliases"):
        _phu_chanh_b_evidence(aliases="not-a-list")
