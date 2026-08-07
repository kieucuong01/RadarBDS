from services.listing_map_context import extract_map_location_context


def test_direct_numbered_and_dx_roads_normalize_without_touching_proximity():
    cases = {
        "Đất Đường 88 khu TĐC Phú Chánh D": "duong so 88",
        "Mặt tiền ĐX-096 Hiệp An": "dx 96",
        "Đường Dx 092 thông": "dx 92",
        "Đường số 35 _ TĐC Phú Chánh B": "duong so 35",
    }

    for text, expected in cases.items():
        context = extract_map_location_context(text, "")
        assert context.direct_road == expected
        assert context.nearby_road == ""
        assert context.relation == "on"


def test_proximity_relations_are_map_only_and_keep_distance():
    near = extract_map_location_context(
        "Bán đất Tân An",
        "Cách đường DX120 khoảng 100m, khu dân cư đông",
    )
    alley = extract_map_location_context(
        "Nhà 1 sẹc Huỳnh Thị Hiếu",
        "ô tô tới nhà",
    )

    assert (near.nearby_road, near.relation, near.distance_m) == (
        "dx 120",
        "near",
        100.0,
    )
    assert (alley.nearby_road, alley.relation) == (
        "huynh thi hieu",
        "alley",
    )


def test_named_road_keeps_phuong_when_it_is_part_of_street_name():
    context = extract_map_location_context(
        "Bán đất đường Nguyễn Tri Phương phường Chánh Nghĩa",
        "",
    )

    assert context.direct_road == "nguyen tri phuong"


def test_alley_parser_ignores_non_road_marketing_phrases():
    context = extract_map_location_context(
        "Nhà hẻm căn rẻ nhất P Hiệp An Thủ Dầu Một",
        "",
    )

    assert context.nearby_road == ""
    assert context.relation == ""


def test_road_width_is_not_treated_as_numbered_road():
    context = extract_map_location_context(
        "1 sẹc đường 5m khu Mỹ Phước 3",
        "",
    )

    assert context.nearby_road == ""


def test_landmark_aliases_normalize_to_one_identity():
    values = [
        "TĐC Phú Chánh C",
        "TDC Phu Chanh C",
        "tái định cư Phú Chánh C",
    ]

    assert {
        extract_map_location_context(value, "").landmark
        for value in values
    } == {"tdc phu chanh c"}


def test_stored_road_does_not_turn_a_nearby_reference_into_frontage():
    context = extract_map_location_context(
        "Bán đất Tân An",
        "Sát đường DX120",
        stored_road_name="DX120",
    )

    assert context.direct_road == ""
    assert context.nearby_road == "dx 120"
    assert context.relation == "near"
