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


def test_bare_alley_number_is_not_treated_as_numbered_road():
    context = extract_map_location_context(
        "Bán nhà hẻm 385 khu 8 Phú Hòa TDM",
        "",
    )

    assert context.nearby_road == ""
    assert context.direct_road == ""


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
