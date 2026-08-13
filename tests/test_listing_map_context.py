import pytest

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


def test_landmark_name_stops_before_listing_copy_and_road_reference():
    tdc = extract_map_location_context(
        "Nhà 1 trệt 1 lầu khu TĐC Phú Mỹ giá 2.9 tỷ",
        "Vị trí đẹp ngay đầu đường D10",
    )
    kdc = extract_map_location_context(
        "Đất KDC Hiệp Thành 1 gần đường Nguyễn Văn Trỗi",
        "Diện tích 80m2",
    )

    assert tdc.landmark == "tdc phu my"
    assert kdc.landmark == "kdc hiep thanh 1"


def test_landmark_name_stops_before_newline_marketing_copy():
    context = extract_map_location_context(
        "Nhà TĐC Định Hòa",
        "Hàng hiếm giá tốt, diện tích 5x20m",
    )

    assert context.landmark == "tdc dinh hoa"


def test_landmark_name_stops_before_repeated_place_and_road_abbreviation():
    repeated = extract_map_location_context(
        "Nhà TĐC Phú Mỹ khu TĐC ngay nhánh Đồng Cây Viết",
        "",
    )
    road_suffix = extract_map_location_context(
        "Đất KDC Hiệp Phát 2 ĐG Nguyễn Đức Thuận",
        "",
    )

    assert repeated.landmark == "tdc phu my"
    assert road_suffix.landmark == "kdc hiep phat 2"


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


def test_tan_an_school_and_dimensions_are_not_roads():
    school = extract_map_location_context(
        "Gan truong THCS Tran Binh Trong",
        "",
    )
    area = extract_map_location_context("Dat dep", "DT: 100m2")
    large_area = extract_map_location_context("Dat dep", "DT 2062m2")
    surface = extract_map_location_context("Duong DX nhua 5m", "")
    implausible_number = extract_map_location_context("Duong so 1350", "")

    assert school.direct_road == ""
    assert school.nearby_road == ""
    assert area.direct_road == ""
    assert large_area.direct_road == ""
    assert surface.direct_road == ""
    assert implausible_number.direct_road == ""


def test_explicit_binh_duong_provincial_road_remains_a_road():
    context = extract_map_location_context("Mat tien duong DT 741", "")

    assert context.direct_road == "dt 741"


def test_tan_an_landmark_stops_before_city_copy():
    context = extract_map_location_context(
        "TDC Tan An Thu Dau Mot Binh Duong",
        "",
    )

    assert context.landmark == "tdc tan an"


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


def test_phu_tan_nguyen_van_linh_keeps_canonical_road_before_tl2_alias():
    context = extract_map_location_context(
        "Sieu pham mat tien duong Nguyen Van Linh (TL2) TDC Phu Chanh C",
        "",
    )

    assert context.direct_road == "nguyen van linh"
    assert context.landmark == "tdc phu chanh c"
    assert context.relation == "on"


def test_chanh_nghia_common_road_aliases_are_canonicalized():
    cases = {
        "Dat 1 xec CMT8 chi 30m": "cach mang thang tam",
        "Nha 1/ Bui Quoc Khanh hem da bao": "bui quoc khanh",
        "Dat 1/ Phan Dinh Giot ke ben KDC Chanh Nghia": "phan dinh giot",
        "Ban nha nhanh Ngo Gia Tu Chanh Nghia": "ngo gia tu",
    }

    for text, expected in cases.items():
        context = extract_map_location_context(text, "")
        assert (context.direct_road or context.nearby_road) == expected


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


def test_alley_number_before_named_road_uses_named_road_not_alley_number():
    context = extract_map_location_context(
        "Nhà nhánh 385 Lê Hồng Phong khu 8 Phú Hoà",
        "2/hẻm 385, cách đường Lê Hồng Phong 100m",
    )

    assert context.nearby_road == "le hong phong"


def test_road_30_4_is_not_treated_as_duong_so_30():
    context = extract_map_location_context(
        "Bán đất 1/ đường 30/4 Phú Hoà cách 20m",
        "",
    )

    assert context.nearby_road == "duong so 30 thang 4"


def test_phu_tho_repeated_duong_prefix_keeps_full_30_4_road_name():
    context = extract_map_location_context(
        "Nha sau mat tien duong duong 30/04 thong Le Hong Phong",
        "",
    )

    assert context.direct_road == "duong so 30 thang 4"


def test_hoa_phu_da7_road_code_is_extracted_from_listing_copy():
    context = extract_map_location_context(
        "Mat tien duong DA7 khu do thi moi Hoa Phu",
        "",
    )

    assert context.direct_road == "da 7"


def test_hoa_phu_dong_khoi_stored_road_is_recognized():
    context = extract_map_location_context(
        "Mat tien Dong Khoi can nha 3 mat tien",
        "",
        "Dong Khoi",
    )

    assert context.direct_road == "dong khoi"


def test_stored_road_name_is_cleaned_like_extracted_road_text():
    context = extract_map_location_context(
        "Bán mặt tiền Hồ Văn Cống Tương Bình Hiệp TDM",
        "",
        "Ho Van Cong Tuong Binh Hiep Tdm",
    )

    assert context.direct_road == "ho van cong"


def test_stored_ql13_alias_becomes_dai_lo_binh_duong():
    context = extract_map_location_context(
        "Bán nhà Hiệp Thành",
        "",
        "QL13",
    )

    assert context.direct_road == "dai lo binh duong"


def test_alley_number_with_named_road_uses_named_road_not_numbered_road():
    context = extract_map_location_context(
        "Bán nhà 1 xẹc hẻm 269 đường Nguyễn Thị Minh Khai khu 9 Phú Hoà",
        "",
    )

    assert context.nearby_road == "nguyen thi minh khai"


def test_verified_phu_hoa_alley_number_is_treated_as_numbered_road():
    context = extract_map_location_context(
        "Bán nhà hẻm 385 khu 8 Phú Hòa TDM",
        "",
    )

    assert context.nearby_road == "duong so 385"
    assert context.relation == "alley"


def test_explicit_near_road_wins_after_bare_alley_number():
    context = extract_map_location_context(
        "Lô góc hẻm 453, cách đường Lê Hồng Phong 90m Phú Hòa",
        "",
    )

    assert context.nearby_road == "le hong phong"


def test_known_phu_hoa_road_name_stops_before_house_words():
    context = extract_map_location_context(
        "Bán nhà Lê Hồng Phong nhà 1 trệt 2 lầu Phú Hòa",
        "",
    )

    assert context.direct_road == "le hong phong"


def test_stored_non_road_marketing_phrase_is_ignored():
    context = extract_map_location_context(
        "Nhà Phú Hòa gần chợ",
        "",
        "Lam Moi Kip Nhe Khach",
    )

    assert context.direct_road == ""


def test_known_phu_my_road_name_stops_before_distance_words():
    context = extract_map_location_context(
        "Đất Phú Mỹ 1 xẹc Huỳnh Văn Lũy 30 mét",
        "",
    )

    assert context.nearby_road == "huynh van luy"


def test_known_phu_my_direct_road_stops_before_dimensions():
    context = extract_map_location_context(
        "Mặt tiền đường Hùng Vương 10x32 Đường Hùng Vương, Phường Phú Mỹ",
        "",
    )

    assert context.direct_road == "hung vuong"


def test_known_phu_my_stored_road_name_stops_before_marketing_words():
    context = extract_map_location_context(
        "Nhà Phú Mỹ",
        "",
        "Hung Vuong cua ngo chinh",
    )

    assert context.direct_road == "hung vuong"


def test_known_phu_loi_nearby_road_stops_before_distance_words():
    context = extract_map_location_context(
        "Nhà Phú Lợi cách đường Nguyễn Bình 50 mét diện nhà 3 tầng",
        "",
    )

    assert context.nearby_road == "nguyen binh"


def test_known_phu_loi_direct_road_stops_before_extra_words():
    context = extract_map_location_context(
        "Nhà mặt tiền Hồ Văn Cống mới xây phù hợp định cư lâu dài",
        "",
    )

    assert context.direct_road == "ho van cong"


def test_tuong_binh_hiep_common_street_typos_map_to_known_roads():
    ho_van_cong = extract_map_location_context(
        "Dat Tuong Binh Hiep cach Ho Van Con 80m",
        "",
    )
    nguyen_chi_thanh = extract_map_location_context(
        "Dat Tuong Binh Hiep sat Nguyen Chi Than",
        "",
    )
    le_van_tach = extract_map_location_context(
        "Mat tien Le Van Tach P Tuong Binh Hiep",
        "",
    )

    assert ho_van_cong.nearby_road == "ho van cong"
    assert nguyen_chi_thanh.nearby_road == "nguyen chi thanh"
    assert le_van_tach.direct_road == "le van tach"


def test_chanh_my_known_roads_drop_marketing_and_area_suffixes():
    nguyen_van_long = extract_map_location_context(
        "Mat tien Nguyen Van Long KP 5 Chanh Loc",
        "",
    )
    huynh_van_cu = extract_map_location_context(
        "Dat Huynh Van Cu vua o vua dau tu",
        "",
    )

    assert nguyen_van_long.direct_road == "nguyen van long"
    assert huynh_van_cu.direct_road == "huynh van cu"


def test_chanh_my_nguyen_van_cu_stops_marketing_suffix():
    direct = extract_map_location_context(
        "Mặt tiền Nguyễn Văn Cừ đại lộ huyết mạch kết nối trung tâm",
        "",
    )
    alley = extract_map_location_context(
        "Nhà Chánh Mỹ 1 sẹc Nguyễn Văn Cừ kề bên khu đô thị",
        "",
    )

    assert direct.direct_road == "nguyen van cu"
    assert alley.nearby_road == "nguyen van cu"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Đất TĐC Chánh Mỹ đối diện khu chung cư", "tdc chanh my"),
        ("Khu đô thị Chánh Mỹ cầu Phú Cường phố đi bộ", "khu do thi chanh my"),
        ("Nhà gần Chợ Chánh Mỹ đường nhựa 5m", "cho chanh my"),
        ("Đất cách Phố đi bộ Bạch Đằng 300m", "pho di bo bach dang"),
    ],
)
def test_chanh_my_named_landmarks_are_bounded(text, expected):
    context = extract_map_location_context(text, "")

    assert context.landmark == expected


@pytest.mark.parametrize(
    "text",
    [
        "Đất TĐC Phú Mỹ KP1 Phú Tân kinh doanh tốt",
        "Đất TĐC Phú Mỹ 5x20 full thổ cư",
        "Nhà khu tái định cư Phú Mỹ khu phố 1",
    ],
)
def test_phu_my_resettlement_landmark_stops_listing_suffixes(text):
    assert extract_map_location_context(text, "").landmark == "tdc phu my"


@pytest.mark.parametrize(
    "text",
    [
        "Nhà Phú Mỹ khu dân cư nhà lầu đông kín giáp khu chợ",
        "Nhà Phú Mỹ khu dân cư an ninh yên tĩnh",
    ],
)
def test_phu_my_generic_neighborhood_copy_is_not_a_landmark(text):
    assert extract_map_location_context(text, "").landmark == ""


@pytest.mark.parametrize(
    ("text", "expected_road", "expected_relation"),
    [
        ("Nhà sẹc Huỳnh Văn Cù gần cầu Phú Cường", "huynh van cu", "alley"),
        ("Nhà xẹc phố Bạch Đằng ngay chợ", "bach dang", "alley"),
        ("Mặt tiền Nguyễn Văn Bé, nhà 1 trệt", "nguyen van be", "on"),
        ("Gần Lý Thường Kiệt mua hết giá tốt", "ly thuong kiet", "near"),
        ("1/ đường Ngô Quyền, hẻm xe hơi", "ngo quyen", "alley"),
        ("1/ Thích Quảng Đức, hỗ trợ vay", "thich quang duc", "alley"),
    ],
)
def test_phu_cuong_named_roads_stop_before_listing_copy(
    text, expected_road, expected_relation
):
    context = extract_map_location_context(text, "")
    assert (context.direct_road or context.nearby_road) == expected_road
    assert context.relation == expected_relation


def test_phu_cuong_interior_finish_copy_is_not_a_landmark():
    context = extract_map_location_context(
        "KDC hoàn thiện nội thất gỗ cao cấp chủ để lại toàn bộ",
        "",
    )
    assert context.landmark == ""


def test_phu_hoa_near_school_copy_does_not_invent_road_one():
    context = extract_map_location_context(
        "Nhà gần trường THCS Phú Hòa, thiết kế 1 trệt 1 lầu",
        "",
    )
    assert context.nearby_road == ""


def test_phu_hoa_explicit_nearby_numbered_road_is_kept():
    context = extract_map_location_context("Đất gần đường số 1 Phú Hòa", "")
    assert context.nearby_road == "duong so 1"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Nhà hẻm 385 Phú Hòa", "duong so 385"),
        ("Nhà hẻm 453 Phú Hòa gần bác sĩ Điền", "duong so 453"),
        (
            "Nhanh lẹ kịp khách iu, nhà xẹt đường 30/4 Phú Hòa",
            "duong so 30 thang 4",
        ),
    ],
)
def test_phu_hoa_alley_identifiers_beat_marketing_copy(text, expected):
    context = extract_map_location_context(text, "")
    assert context.nearby_road == expected
    assert context.relation == "alley"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Nhà hẻm 109 NTMK khu 9 Phú Hòa", "nguyen thi minh khai"),
        ("Đất đường Lê Hồng Phong hẻm 249", "le hong phong"),
        ("Nhà 1 xẹt 30/4 cách đường chính 50m", "duong so 30 thang 4"),
    ],
)
def test_phu_hoa_numbered_alley_prefers_explicit_parent_road(text, expected):
    context = extract_map_location_context(text, "")
    assert context.nearby_road == expected
    assert context.relation == "alley"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "Đất Phú Hòa nhựa 4m thông hẻm 167 qua hẻm 189 "
            "Nguyễn Thị Minh Khai, DT 5x26m",
            "nguyen thi minh khai",
        ),
        (
            "Đất Phú Hòa MT nhựa lớn, 10 mấy tr/m2; vị trí 1 xẹt "
            "Lê Hồng Phong cách 200m",
            "le hong phong",
        ),
    ],
)
def test_phu_hoa_named_parent_road_beats_area_and_price_numbers(text, expected):
    context = extract_map_location_context(text, "")
    assert context.nearby_road == expected
    assert context.relation == "alley"


@pytest.mark.parametrize(
    ("title", "description", "expected"),
    [
        (
            "Đất Phú Lợi thông ra đường Huỳn",
            "Đất Phú Lợi thông ra đường Huỳnh Văn Lũy, cạnh Chợ Đình",
            "huynh van luy",
        ),
        (
            "Đất hẻm 182 Lê Hồng",
            "Đất hẻm 182 Lê Hồng Phong, cách LHP 30m",
            "le hong phong",
        ),
        (
            "Nhà MT Nguyễn Thị Minh",
            "Nhà MT Nguyễn Thị Minh Khai mới hoàn công",
            "nguyen thi minh khai",
        ),
        (
            "Đất cách đường HVL 30 mét",
            "Hẻm 275 Huỳnh Văn Lũy",
            "huynh van luy",
        ),
        (
            "Nhà hẻm 109 Nguyễn Thái",
            "Nhà hẻm 109 Nguyễn Thái Bình nhựa 8m",
            "nguyen thai binh",
        ),
    ],
)
def test_phu_loi_truncated_titles_defer_to_complete_road_names(
    title, description, expected
):
    context = extract_map_location_context(title, description)
    assert (context.direct_road or context.nearby_road) == expected
    assert context.relation in {"on", "near", "alley"}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Nhà KDC Phú Hòa 1 full nội thất", "kdc phu hoa 1"),
        ("Nhà KDC Phú Hòa 2 khu dân cư hiện hữu", "kdc phu hoa 2"),
        ("Nhà KDC Hoàng Nam 2 Phú Hòa", "kdc hoang nam 2"),
    ],
)
def test_phu_hoa_landmarks_stop_before_listing_suffixes(text, expected):
    assert extract_map_location_context(text, "").landmark == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Nhà KDC Hiệp Thành 1 nội thất xịn, sổ vào ở ngay", "kdc hiep thanh 1"),
        ("Nhà KDC Hiệp Thành II giảm 450 triệu", "kdc hiep thanh 2"),
        ("Đất KDC HT3 xây dựng tự do", "kdc hiep thanh 3"),
        ("Nhà KDC K8 Hiệp Thành mái thái kiên cố", "kdc k8 thanh le"),
        ("Nhà KDC Hiệp Phát 1 thiết kế 2PN 2WC", "kdc hiep phat 1"),
    ],
)
def test_hiep_thanh_landmarks_drop_listing_copy_and_zone_variants(text, expected):
    assert extract_map_location_context(text, "").landmark == expected


def test_direct_frontage_road_beats_a_nearby_reference_road():
    context = extract_map_location_context(
        "Nha MT 30/4 noi dai",
        "Gan Vo Minh Duc - Co.opmart, duong thong ven song Bach Dang",
    )

    assert context.direct_road == "duong so 30 thang 4"
    assert context.nearby_road == "vo minh duc"
    assert context.relation == "near"


def test_direct_numbered_road_is_not_replaced_by_marketing_copy_relations():
    context = extract_map_location_context(
        "Ban nha duong so 3 Chanh Nghia",
        "Thiet ke dang nha o, ket cau chuan khach san",
        stored_road_name="Duong So 3",
    )

    assert context.direct_road == "duong so 3"
    assert context.nearby_road == ""


def test_generic_paved_road_width_does_not_become_numbered_road():
    context = extract_map_location_context(
        "Hem thong Thich Quang Duc - Ngo Gia Tu",
        "Duong nhua 2 xe hoi ne nhau, ke KDC Chanh Nghia",
    )

    assert context.direct_road == "thich quang duc"
    assert context.direct_road != "duong so 2"


@pytest.mark.parametrize(
    "text",
    [
        "Mat tien duong nhua 6,5m thong thoang, cach Le Chi Dan 200m",
        "Duong nhua 4.5 met, cach Nguyen Duc Canh vai buoc chan",
        "Duong be tong 3,5m, cach Phan Dang Luu 100m",
    ],
)
def test_decimal_road_width_is_not_a_numbered_road(text):
    context = extract_map_location_context("Dat dep", text)

    assert context.direct_road == ""
    assert not context.nearby_road.startswith("duong so")


@pytest.mark.parametrize(
    ("text", "expected_nearby"),
    [
        (
            "Cach Bui Quoc Khanh co may chuc met. "
            "Duong 2 xe hoi ra vo thoai mai",
            "bui quoc khanh",
        ),
        (
            "Cach Le Hong Phong 100m. Duong 5m 2 xe hoi ne nhau",
            "le hong phong",
        ),
        (
            "Mat tien duong 4 m + sat duong lon Le Hong Phong",
            "le hong phong",
        ),
    ],
)
def test_vehicle_count_and_road_width_do_not_become_numbered_roads(
    text, expected_nearby
):
    context = extract_map_location_context("Dat trung tam", text)

    assert context.direct_road == ""
    assert context.nearby_road == expected_nearby


def test_area_after_generic_boulevard_does_not_hide_named_boulevard():
    context = extract_map_location_context(
        "Can ban dat mat tien dai lo 463.3m² tho cu 416m²",
        "Vi tri: Dai Lo Binh Duong. Dien tich: 15 x 28m.",
    )

    assert context.direct_road == "dai lo binh duong"


def test_decimal_frontage_does_not_override_cmt8_alley():
    context = extract_map_location_context(
        "Ban nha Chanh Nghia 1/ C",
        "Ban nha 1/ Cach Mang Thang 8 cach 30m. "
        "Dien tich 104m2. Mat tien 9.5m.",
    )

    assert context.direct_road == ""
    assert context.nearby_road == "cach mang thang tam"
    assert context.relation == "alley"


def test_numbered_road_before_ward_name_keeps_the_numbered_road():
    context = extract_map_location_context(
        "Mat tien duong 51 Phu Tan Thu Dau Mot cu",
        "Duong 51 phuong Phu Tan, sat Nguyen Van Linh.",
    )

    assert context.direct_road == "duong so 51"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "1 xet Le Chi Dan, gan cau Ba Co - pho di bo Bach Dang",
            "le chi dan",
        ),
        (
            "1/ Nguyen Duc Thuan, duong nhua gan 5m. Ho tro bank tet ga",
            "nguyen duc thuan",
        ),
        (
            "1 xet Nguyen Chi Thanh. Cach duong nhua lon tam 50m",
            "nguyen chi thanh",
        ),
        (
            "1/ duong Nguyen Binh cach 20m. "
            "Thich hop lam nha vuon bao dep",
            "nguyen binh",
        ),
    ],
)
def test_named_alley_road_beats_later_non_location_copy(text, expected):
    context = extract_map_location_context("Nha trung tam", text)

    assert context.nearby_road == expected
    assert context.relation == "alley"


def test_ql13_without_space_before_number_uses_canonical_road():
    context = extract_map_location_context(
        "Duong Quoc Lo13 lo goc khong tru chi gioi",
        "",
    )

    assert context.direct_road == "dai lo binh duong"


def test_direct_ntmk_beats_later_dt743_reference():
    context = extract_map_location_context(
        "Dat mat tien NTMK dang cho thue",
        "Duong DT743 thong QL13",
    )

    assert context.direct_road == "nguyen thi minh khai"


def test_address_number_before_dai_lo_bd_beats_nearby_ring_road():
    context = extract_map_location_context(
        "Ban can ho Happy One 26 Dai Lo BD",
        "Doi dien Metro, ke duong Vanh Dai 3 dang thi cong",
    )

    assert context.direct_road == "dai lo binh duong"
    assert context.nearby_road == "vanh dai 3"


def test_fast_connection_copy_is_not_treated_as_an_alley():
    context = extract_map_location_context(
        "Nha mat tien Ho Van Cong",
        "Ket noi nhanh Quoc Lo 13 - Dai Lo Binh Duong - TP HCM",
    )

    assert context.direct_road == "ho van cong"
    assert context.nearby_road == ""
    assert context.relation == "on"


@pytest.mark.parametrize(
    ("text", "expected", "relation"),
    [
        ("Hem duong Lao Cai Nha Moi 90% xay dung tret lau", "lao cai", "alley"),
        ("Cach duong Lao Cai may chuc met thoi", "lao cai", "near"),
        ("1/ bui quoc khach. Duong be tong 6m", "bui quoc khanh", "alley"),
        ("Thong ra Phan Di Dat Chanh Nghia, sau do la Phan Dinh Giot", "phan dinh giot", "near"),
    ],
)
def test_chanh_nghia_noisy_parent_roads_normalize_to_registry_names(
    text, expected, relation
):
    context = extract_map_location_context("Dat Chanh Nghia", text)

    assert context.nearby_road == expected
    assert context.relation == relation


def test_cmt8_is_recognized_before_false_sat_tran_relation():
    context = extract_map_location_context(
        "Nha moi 2 mat thoang CMT8",
        "Ba tang op gach sat tran, moi xay 2023, hoan cong du",
    )

    assert context.direct_road == "cach mang thang tam"
    assert context.nearby_road == ""


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Nha KDC Chanh Nghia noi that full go do", "kdc chanh nghia"),
        ("Dat sat KDC Chanh Nghi trung tam", "kdc chanh nghia"),
    ],
)
def test_chanh_nghia_landmark_suffixes_use_one_canonical_key(text, expected):
    assert extract_map_location_context(text, "").landmark == expected


def test_tan_an_common_road_phrases_map_to_known_roads():
    nguyen_chi_thanh = extract_map_location_context(
        "Dat Tan An cach duong lon Nguyen Chi Thanh",
        "",
    )
    huynh_thi_hieu = extract_map_location_context(
        "Dat Tan An cach Huynh Thi H nha tret lung",
        "",
    )
    phan_dang_luu = extract_map_location_context(
        "Dat Tan An cach Phan Dang Luu 60 met",
        "",
    )
    le_chi_dan = extract_map_location_context(
        "Nha Tan An 1 sec Le Chi",
        "",
    )

    assert nguyen_chi_thanh.nearby_road == "nguyen chi thanh"
    assert huynh_thi_hieu.nearby_road == "huynh thi hieu"
    assert phan_dang_luu.nearby_road == "phan dang luu"
    assert le_chi_dan.nearby_road == "le chi dan"


def test_tan_an_truncated_known_road_names_are_recovered():
    huynh_thi_hieu = extract_map_location_context(
        "Nha Tan An cach Huynh Thi",
        "Vi tri cach Huynh Thi Hieu 50m",
    )
    phan_dang_luu = extract_map_location_context(
        "Nha mat tien Phan Dang L nha mat tien",
        "Vi tri mat tien Phan Dang Luu gan nga tu Vo Cai",
    )

    assert huynh_thi_hieu.nearby_road == "huynh thi hieu"
    assert phan_dang_luu.direct_road == "phan dang luu"


def test_tan_an_marketing_and_listing_codes_are_not_roads():
    construction = extract_map_location_context(
        "Nha pho lien ke dang thi cong tai phuong Tan An",
        "",
    )
    generic_large_road = extract_map_location_context(
        "Nha hem cach duong lon vao 50m",
        "",
    )
    listing_code = extract_map_location_context(
        "Nha dat Tan An D713",
        "To 10 thua 558",
        stored_road_name="D713",
    )
    one_minute = extract_map_location_context(
        "Mat tien Bui Ngoc Thu",
        "Cach quoc lo 1 phut",
    )

    assert construction.direct_road == ""
    assert construction.nearby_road == ""
    assert generic_large_road.direct_road == ""
    assert generic_large_road.nearby_road == ""
    assert listing_code.direct_road == ""
    assert one_minute.nearby_road == ""


def test_phu_tho_known_roads_drop_suffixes_and_aliases():
    nguyen_huu_canh = extract_map_location_context(
        "Mat tien Nguyen Huu Canh P Phu Tho",
        "",
    )
    phan_boi_chau = extract_map_location_context(
        "Dat Phan Boi Chau Thu Dau Mot can ho",
        "",
    )
    tran_binh_trong = extract_map_location_context(
        "Nha 1 sec Tran Binh Trong canh cafe",
        "",
    )
    dai_lo_binh_duong = extract_map_location_context(
        "Dat Phu Tho cach DL Binh Duong 100m",
        "",
    )

    assert nguyen_huu_canh.direct_road == "nguyen huu canh"
    assert phan_boi_chau.direct_road == "phan boi chau"
    assert tran_binh_trong.nearby_road == "tran binh trong"
    assert dai_lo_binh_duong.nearby_road == "dai lo binh duong"


def test_hiep_an_common_short_road_phrases_map_to_known_roads():
    bui_ngoc_thu = extract_map_location_context(
        "Dat Hiep An cach Bui Ngoc Thu xec",
        "",
    )
    nguyen_chi_thanh = extract_map_location_context(
        "Nha Hiep An 1 sec Nguyen Chi T dat",
        "",
    )
    le_chi_dan = extract_map_location_context(
        "Dat Hiep An 1 sec Le Ch",
        "",
    )
    dai_lo_binh_duong = extract_map_location_context(
        "Dat Hiep An cach Quoc Lo 13 thuan tien ket noi",
        "",
    )

    assert bui_ngoc_thu.nearby_road == "bui ngoc thu"
    assert nguyen_chi_thanh.nearby_road == "nguyen chi thanh"
    assert le_chi_dan.nearby_road == "le chi dan"
    assert dai_lo_binh_duong.nearby_road == "dai lo binh duong"


def test_hiep_an_known_roads_stop_before_marketing_copy():
    nguyen_duc_canh = extract_map_location_context(
        "Dat Hiep An cach Nguyen Duc Canh 100m ke nha 3 tang",
        "",
    )
    huynh_thi_chau = extract_map_location_context(
        "Mat tien Huynh Thi Chau sam uat con thich hop kinh doanh",
        "",
    )

    assert nguyen_duc_canh.nearby_road == "nguyen duc canh"
    assert nguyen_duc_canh.distance_m == 100.0
    assert huynh_thi_chau.direct_road == "huynh thi chau"


def test_hiep_an_false_person_phrases_do_not_hide_later_known_roads():
    phan_dang_luu = extract_map_location_context(
        "Dat Hiep An gan phan giap chu nha dep",
        "Cach Phan Dang Luu 50m",
    )
    bui_ngoc_thu = extract_map_location_context(
        "Dat Hiep An cach vo nha 7 met",
        "Sat Bui Ngoc Thu 80m",
    )
    le_chi_dan = extract_map_location_context(
        "Dat Hiep An gan ly tuong phan dau dat chua cho de",
        "Cach Le Chi Dan 70m",
    )

    assert phan_dang_luu.nearby_road == "phan dang luu"
    assert bui_ngoc_thu.nearby_road == "bui ngoc thu"
    assert le_chi_dan.nearby_road == "le chi dan"


@pytest.mark.parametrize(
    ("misleading_phrase", "real_road", "expected"),
    [
        ("gan phan nha moi", "Phan Dang Luu", "phan dang luu"),
        ("cach vo thoai mai", "Bui Ngoc Thu", "bui ngoc thu"),
        ("gan le c dat", "Le Chi Dan", "le chi dan"),
        ("gan nguyen ch hang ngop", "Nguyen Chi Thanh", "nguyen chi thanh"),
        ("cach nguyen chi dat", "Nguyen Chi Thanh", "nguyen chi thanh"),
        ("gan ngo truoc nha", "Nguyen Duc Canh", "nguyen duc canh"),
    ],
)
def test_hiep_an_more_false_relation_phrases_defer_to_real_road(
    misleading_phrase, real_road, expected
):
    context = extract_map_location_context(
        f"Dat Hiep An {misleading_phrase}",
        f"Cach {real_road} 70m",
    )

    assert context.nearby_road == expected


def test_hiep_an_road_width_and_dense_neighborhood_are_not_locations():
    road_width = extract_map_location_context(
        "Mat tien DX 6 met thong tum lum nha 1 tret 1 lau",
        "",
    )
    dense_neighborhood = extract_map_location_context(
        "Nha Hiep An khu dan cu dong duc an ninh",
        "",
    )
    existing_neighborhood = extract_map_location_context(
        "Dat Hiep An KDC hien huu dan o kin",
        "",
    )
    stable_neighborhood = extract_map_location_context(
        "Nha Hiep An khu dan cu on dinh",
        "",
    )

    assert road_width.direct_road == ""
    assert road_width.nearby_road == ""
    assert dense_neighborhood.landmark == ""
    assert existing_neighborhood.landmark == ""
    assert stable_neighborhood.landmark == ""


@pytest.mark.parametrize(
    ("misleading_phrase", "real_road", "expected"),
    [
        ("mot sec lo lu", "Le Chi Dan", "le chi dan"),
        ("gan ho va dat dep phuong", "Ho Van Cong", "ho van cong"),
        ("mot sec le dat", "Le Chi Dan", "le chi dan"),
        ("gan phan Ho Van Cong Thu Dau Mot", "Ho Van Cong", "ho van cong"),
        ("mat tien Ho Van Long 1 tret 1 lau", "Nguyen Chi Thanh", "nguyen chi thanh"),
    ],
)
def test_tuong_binh_hiep_false_phrases_defer_to_known_roads(
    misleading_phrase, real_road, expected
):
    context = extract_map_location_context(
        f"Dat Tuong Binh Hiep {misleading_phrase}",
        f"Cach {real_road} 70m",
    )

    assert context.nearby_road == expected or context.direct_road == expected


def test_tuong_binh_hiep_named_landmark_stops_marketing_copy():
    named = extract_map_location_context(
        "Dat TDC Tuong Binh Hiep dong dan cu",
        "",
    )
    generic = extract_map_location_context(
        "Nha KDC an ninh yen tinh hang xom than thien",
        "",
    )

    assert named.landmark == "tdc tuong binh hiep"
    assert generic.landmark == ""


def test_dinh_hoa_known_roads_stop_before_marketing_copy():
    vo_van_kiet = extract_map_location_context(
        "Dat Dinh Hoa cach Vo Van Kiet vai chuc met",
        "",
    )
    nguyen_van_thanh = extract_map_location_context(
        "Mat tien Nguyen Van Thanh Vo Van Kiet My Phuoc",
        "",
    )

    assert vo_van_kiet.nearby_road == "vo van kiet"
    assert nguyen_van_thanh.direct_road == "nguyen van thanh"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Dat TDC Dinh Hoa lien ke khu hanh chinh va TTTM", "tdc dinh hoa"),
        ("Dat TDC Dinh Hoa Hoa Phu", "tdc dinh hoa"),
        ("Dat TDC P Dinh Hoa khu nha o", "tdc dinh hoa"),
        ("Dat TDC Thanh Le khu BV 1500 giuong", "tdc thanh le"),
    ],
)
def test_dinh_hoa_named_landmarks_drop_marketing_and_legacy_suffixes(
    text, expected
):
    context = extract_map_location_context(text, "")

    assert context.landmark == expected


def test_dinh_hoa_generic_kdc_dong_is_not_a_landmark():
    generic = extract_map_location_context("Dat Dinh Hoa KDC dong", "")
    real = extract_map_location_context("Dat TDC Dong Hoa", "")

    assert generic.landmark == ""
    assert real.landmark == "tdc dong hoa"


def test_dinh_hoa_short_road_aliases_map_to_existing_registry_roads():
    mptv = extract_map_location_context("Dat Dinh Hoa cach MPTV 100m", "")
    tran_ngoc_len = extract_map_location_context(
        "Dat Dinh Hoa cach Tran Ngoc Lien 80m",
        "",
    )

    assert mptv.nearby_road == "my phuoc tan van"
    assert tran_ngoc_len.nearby_road == "tran ngoc len"


def test_dinh_hoa_false_relation_phrases_defer_to_real_road():
    vo_van_kiet = extract_map_location_context(
        "Dat Dinh Hoa gan vo va mat tien nhua",
        "Cach Vo Van Kiet 60m",
    )
    dx84 = extract_map_location_context(
        "Dat Dinh Hoa gan do khong ro",
        "Cach DX84 70m",
    )

    assert vo_van_kiet.nearby_road == "vo van kiet"
    assert dx84.nearby_road == "dx 84"


@pytest.mark.parametrize(
    "text",
    [
        "Dat Dinh Hoa KDC o kin",
        "Dat Dinh Hoa KDC van phong truong hoc",
        "Dat Dinh Hoa du an xay dung nha o",
        "Dat Dinh Hoa du an abc nao do",
    ],
)
def test_dinh_hoa_generic_marketing_phrases_are_not_landmarks(text):
    assert extract_map_location_context(text, "").landmark == ""


def test_dinh_hoa_becamex_landmark_stops_inventory_suffix():
    context = extract_map_location_context(
        "Du an Becamex Dinh Hoa tong 11.500 can ho",
        "",
    )

    assert context.landmark == "du an becamex dinh hoa"


def test_phu_cuong_common_road_phrases_map_to_known_roads():
    nguyen_an_ninh = extract_map_location_context(
        "Mat tien Nguyen An Ninh Phu Cuong",
        "",
    )
    yersin = extract_map_location_context(
        "Nha Phu Cuong Nhanh duong 1/ duong Yesin sau lung The Gioi Di Dong",
        "",
    )
    huynh_van_cu = extract_map_location_context(
        "Dat Phu Cuong cach Huynh Van Cu 50m",
        "",
    )

    assert nguyen_an_ninh.direct_road == "nguyen an ninh"
    assert yersin.nearby_road == "bac si yersin"
    assert huynh_van_cu.nearby_road == "huynh van cu"


def test_hiep_thanh_pham_ngoc_short_name_maps_to_pham_ngoc_thach():
    context = extract_map_location_context(
        "Đất Hiệp Thành cách Phạm Ngọc vòng xoay 500m",
        "",
    )

    assert context.nearby_road == "pham ngoc thach"


def test_hiep_thanh_abbreviated_d_prefix_uses_named_road():
    context = extract_map_location_context(
        "Nhà Hiệp Thành 1/ Đ.Nguyễn Bình gần vòng xoay",
        "",
    )

    assert context.nearby_road == "nguyen binh"


def test_hiep_thanh_dai_lo_bd_alias_maps_to_dai_lo_binh_duong():
    context = extract_map_location_context(
        "Nhà Hiệp Thành sát Đại lộ BD, gần siêu thị",
        "",
    )

    assert context.nearby_road == "dai lo binh duong"


@pytest.mark.parametrize(
    ("title", "stored_road_name"),
    [
        ("Mặt tiền đường Phú An 024, vị trí đẹp", ""),
        ("Đường vô thoải mái, xung quanh nhiều công ty", "Phú An 024"),
    ],
)
def test_extract_context_recognizes_phu_an_numbered_local_road(
    title, stored_road_name
):
    context = extract_map_location_context(title, "", stored_road_name)

    assert context.direct_road == "phu an 024"
    assert context.relation == "on"


@pytest.mark.parametrize(
    ("text", "expected_direct", "expected_nearby", "expected_landmark"),
    [
        ("Mặt tiền DT7A gần vòng xoay An Điền", "dt 7 a", "", ""),
        ("Đất gần đường vành 4, 10x27m", "", "vanh dai 4", ""),
        ("Bán nhà KDC Rạch Bắp An Điền, Bến Cát", "", "", "kdc rach bap"),
        ("Mặt tiền đường An Điền 99 nhà vườn", "an dien 99", "", ""),
    ],
)
def test_extract_context_normalizes_an_dien_road_and_landmark_variants(
    text, expected_direct, expected_nearby, expected_landmark
):
    context = extract_map_location_context(text, "")

    assert context.direct_road == expected_direct
    assert context.nearby_road == expected_nearby
    assert context.landmark == expected_landmark


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Mặt tiền NJ17 Mỹ Phước 3", "nj 17"),
        ("Mặt tiền DJ5 Mỹ Phước 3", "dj 5"),
        ("Mặt tiền NK4 Mỹ Phước 3", "nk 4"),
        ("Mặt tiền NH15 Mỹ Phước 3", "nh 15"),
        ("Mặt tiền NA7 Mỹ Phước 3", "na 7"),
        ("Mặt tiền DK12 Mỹ Phước 3", "dk 12"),
    ],
)
def test_extract_context_recognizes_my_phuoc_3_industrial_grid_codes(
    text, expected
):
    context = extract_map_location_context(text, "")

    assert context.direct_road == expected
    assert context.relation == "on"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Lo I1 duong DI1 My Phuoc 3", "di 1"),
        ("Day tro F18 duong DF5 My Phuoc 3", "df 5"),
        ("Lo G34 duong NG3A My Phuoc 3", "ng 3 a"),
        ("Mat tien DG2 khu G My Phuoc 3", "dg 2"),
        ("Nha H27 duong XH4 My Phuoc 3", "xh 4"),
        ("Day tro K45 duong KK4A My Phuoc 3", "kk 4 a"),
    ],
)
def test_extract_context_recognizes_second_pass_my_phuoc_3_grid_codes(
    text, expected
):
    context = extract_map_location_context(text, "")

    assert context.direct_road == expected
    assert context.relation == "on"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Bán đất Khu đô thị Mỹ Phước 3 Bến Cát", "khu do thi my phuoc 3"),
        ("Nhà KDC Mỹ Phước 3 sầm uất tiện ích đầy đủ", "kdc my phuoc 3"),
        ("Đất TĐC Mỹ Phước III khu phố 3B", "tdc my phuoc 3"),
    ],
)
def test_extract_context_clips_my_phuoc_3_landmark_trailing_ad_copy(
    text, expected
):
    context = extract_map_location_context(text, "")

    assert context.landmark == expected


def test_extract_context_recognizes_tan_dinh_numbered_local_road():
    context = extract_map_location_context(
        "Cần bán đất khu 1 Tân Định",
        "Có 35m mặt tiền Tân Định 028 nối dài",
        "Tân Định 028",
    )

    assert context.direct_road == "tan dinh 028"
    assert context.relation == "on"


def test_extract_context_clips_hoa_loi_road_width_copy():
    context = extract_map_location_context(
        "Bán đất mặt tiền Phạm Hùng rộng 20m Hòa Lợi",
        "",
        "",
    )

    assert context.direct_road == "pham hung"


def test_extract_context_clips_quoc_lo_14_trailing_landmark_copy():
    context = extract_map_location_context(
        "Bán đất mặt tiền Quốc lộ 14 và chợ Chánh Lưu LH ngay",
        "",
        "",
    )

    assert context.direct_road == "ql 14"
