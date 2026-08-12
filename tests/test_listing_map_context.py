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


def test_area_abbreviation_dt_is_not_treated_as_provincial_road_width():
    context = extract_map_location_context(
        "Nhà Tân An",
        "DT 5 x 20 thổ cư 60m, đường bê tông 5m thông",
    )

    assert context.direct_road == ""
    assert context.nearby_road == ""
    assert context.relation == ""


def test_alley_distance_before_named_road_is_extracted():
    context = extract_map_location_context(
        "Hiệp An TDM hạ giá",
        "Dat 1 xec 50m Nguyen Chi Thanh ngay nga tu Vo Cai",
    )

    assert context.nearby_road == "nguyen chi thanh"
    assert context.relation == "alley"
    assert context.distance_m == 50.0


def test_slash_alley_before_named_road_is_extracted():
    context = extract_map_location_context(
        "Đất Tân An",
        "2/ Mac Dinh Chi doi dien truong THCS Tran Binh Trong",
    )

    assert context.nearby_road == "mac dinh chi"
    assert context.relation == "alley"


def test_nearby_named_road_stops_before_distance_suffix():
    context = extract_map_location_context(
        "Bán đất Tân An",
        "cách Huỳnh Thị Hiếu 150m, đường bê tông 3,5m",
    )

    assert context.nearby_road == "huynh thi hieu"
    assert context.relation == "near"
    assert context.distance_m == 150.0


def test_ql13_alias_resolves_to_dai_lo_binh_duong():
    context = extract_map_location_context(
        "Bán nhà Hiệp An",
        "1 sẹt quốc lộ 13 gần trạm thu phí suối giữa",
    )

    assert context.nearby_road == "dai lo binh duong"
    assert context.relation == "alley"


def test_dai_lo_binh_duong_after_slash_alley_is_extracted():
    context = extract_map_location_context(
        "Nhà Định Hoà",
        "1/ Đại Lộ Bình Dương 150m Chủ Hạ 100tr Bán Nhanh",
    )

    assert context.nearby_road == "dai lo binh duong"
    assert context.relation == "alley"
    assert context.distance_m == 150.0


def test_road_candidate_stops_before_vao_distance_suffix():
    context = extract_map_location_context(
        "Bán đất Tân An",
        "Vị trí Nhánh Huỳnh thị Hiếu vào 200m.",
    )

    assert context.nearby_road == "huynh thi hieu"
    assert context.distance_m == 200.0


def test_road_candidate_stops_before_chi_distance_without_breaking_name():
    context = extract_map_location_context(
        "Bán đất Tân An",
        "cách Phan Đăng Lưu chỉ 100m, gần Ngã Tư Võ Cái",
    )

    assert context.nearby_road == "phan dang luu"
    assert context.distance_m == 100.0


def test_road_candidate_stops_before_kdc_and_ward_suffixes():
    context = extract_map_location_context(
        "Bán nhà mặt tiền Hoàng Hoa Thám KDC Phúc Đạt, Phú Lợi",
        "",
    )

    assert context.direct_road == "hoang hoa tham"


def test_road_candidate_drops_following_ward_city_suffix():
    context = extract_map_location_context(
        "Bán mặt tiền Hồ Văn Cống Tương Bình Hiệp TDM",
        "Nay là phường Chánh Hiệp TPHCM",
    )

    assert context.direct_road == "ho van cong"


def test_le_chi_dan_name_is_not_cut_at_chi():
    context = extract_map_location_context(
        "Bán nhà",
        "1 sẹc Lê Chí Dân chỉ 80m",
    )

    assert context.nearby_road == "le chi dan"
    assert context.distance_m == 80.0
