"""Source-backed parser learning; no raw queue, contacts, or DB access."""

import pytest

from cleansing.feature_extractor import classify_property_type, extract_dimensions, parse_facebook_post
from config.location_aliases import resolve_post_merger_location
from cleansing.normalizer import extract_road_name, normalize_record


# Exact redacted excerpt: 20261020-150022:83150:frontage_m.
FRONTAGE_EXCERPT = "Diện tích 109m2 thổ cư 100m ngang 8m8 dài 13,6m"


def test_reviewed_83150_compact_frontage_before_labeled_depth():
    assert extract_dimensions(FRONTAGE_EXCERPT) == {
        "frontage_m": 8.8,
        "depth_m": 13.6,
    }


def test_facebook_parser_preserves_reviewed_compact_frontage():
    parsed = parse_facebook_post(FRONTAGE_EXCERPT)
    assert parsed["frontage_m"] == 8.8
    assert parsed["depth_m"] == 13.6
    assert parsed["area_m2"] == 109.0


def test_normalizer_preserves_reviewed_compact_frontage():
    record = normalize_record({
        "source": "facebook",
        "url": "https://example.invalid/synthetic-extraction-83150",
        "title": FRONTAGE_EXCERPT,
        "description": "",
    })
    assert record is not None
    assert record["frontage_m"] == 8.8
    assert record["depth_m"] == 13.6
    assert record["area_m2"] == 109.0


@pytest.mark.parametrize("text, frontage, depth", [
    ("ngang 5m40 dài 18m", 5.4, 18.0),
    ("NGANG 8M8 SÂU 13,6M", 8.8, 13.6),
    ("ngang 8m08 dai 13.6m", 8.08, 13.6),
])
def test_labeled_compact_frontage_variants(text, frontage, depth):
    assert extract_dimensions(text) == {
        "frontage_m": frontage,
        "depth_m": depth,
    }


@pytest.mark.parametrize("text", [
    "ngang 8m2 dài 13,6m",
    "ngang 8m² dài 13,6m",
])
def test_square_meter_marker_is_not_a_compact_decimal_frontage(text):
    # These unit-bearing near misses do not establish an 8.2m frontage.
    assert extract_dimensions(text)["frontage_m"] != 8.2


@pytest.mark.parametrize("text, frontage, depth", [
    ("Diện tích 109m2 thổ cư 100m", None, None),
    ("đường nhựa rộng 8m8", None, None),
    ("ngang 8m, dài 13,6m", 8.0, 13.6),
    ("ngang 8,8m dài 13,6m", 8.8, 13.6),
    ("DT 9m2 x 12,6m", 9.0, 12.6),
    ("ngang 8m²", None, None),
    ("ngang 8m8abc", None, None),
])
def test_compact_frontage_does_not_reinterpret_near_misses(text, frontage, depth):
    assert extract_dimensions(text) == {
        "frontage_m": frontage,
        "depth_m": depth,
    }


# Four reviewed road-name cases; 83111/83103 are identical excerpts, not
# independent source patterns. Synthetic controls below are not extra listings.
ROAD_CASES = [
    (83111, "Đất mặt tiền DT7A (Hùng Vương) gần vòng xoay An Điền", "DT7A"),
    (83103, "Đất mặt tiền DT7A (Hùng Vương) gần vòng xoay An Điền", "DT7A"),
    (83142, "MẶT TIỀN LÊ HỒNG PHONG PHÚ LỢI", "Le Hong Phong"),
    (83114, "trục chính đường Hồng Hà; Đường nhựa 6m thông từ DT744 xuống DH609", "Hong Ha"),
]


@pytest.mark.parametrize("listing_id,text,expected", ROAD_CASES)
def test_reviewed_road_name_cases(listing_id, text, expected):
    assert extract_road_name(text) == expected


@pytest.mark.parametrize("listing_id,text,expected", ROAD_CASES)
def test_reviewed_road_cases_through_normalization(listing_id, text, expected):
    record = normalize_record({
        "source": "facebook", "url": "https://example.invalid/unit-road-case",
        "title": text, "description": "",
    })
    assert record is not None and record["road_name"] == expected


@pytest.mark.parametrize("text,expected", [
    ("Mặt tiền ĐT744, đường nhựa 12m", "DT744"),
    ("Mặt tiền đường ĐT7A", "DT7A"),
    ("Nhánh DT7A, đường bê tông", "DT7A"),
    ("Mặt tiền dt 007a", "DT7A"),
    ("DT 160 m2 thổ cư", None),
    ("Diện tích DT 160 giá 2 tỷ", None),
    ("Đất gần đường ĐT7A", None),
    ("Đất cách DT744 100m", None),
    ("Mặt tiền DT7ABC", None),
    ("Mặt tiền DH609, cách đường DT744 50m", "DH609"),
    ("Nhà mặt tiền DX072, gần DT7A", "DX72"),
])
def test_provincial_road_codes_do_not_become_areas_or_nearby_roads(text,expected):
    assert extract_road_name(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("Mặt tiền Lê Hồng Phong Phú Lợi chủ đang kẹt tiền cần bán gấp", "Le Hong Phong"),
    ("Mặt tiền Nguyễn Chí Thanh Hiệp An", "Nguyen Chi Thanh"),
    ("Nhà đường Bùi Ngọc Thu Tân An", "Bui Ngoc Thu"),
    ("Đường Nguyễn Tri Phương Chánh Nghĩa", "Nguyen Tri Phuong"),
    ("Đường Phú Lợi", "Phu Loi"),
    ("Đường Phú Lợi Phú Hòa", "Phu Loi Phu Hoa"),
    ("Đường Lê Hồng Phong nối dài", "Le Hong Phong Noi Dai"),
    ("Hẻm 232 Nguyễn Đức Thuận Hiệp Thành", "Hem 232 Nguyen Duc Thuan"),
    ("Gần đường Lê Hồng Phong Phú Lợi", None),
])
def test_known_street_locality_boundary_preserves_unknown_street_names(text,expected):
    assert extract_road_name(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("Trục chính đường Hồng Hà; thông từ ĐT744 xuống ĐH609", "Hong Ha"),
    ("Mặt tiền đường Hồng Hà; thông từ ĐT744 xuống ĐH609", "Hong Ha"),
    ("Đường nhựa 6m thông từ DT744 xuống DH609", None),
    ("Gần đường Hồng Hà; đường thông từ DT744 xuống DH609", None),
    ("Mặt tiền DH609; đường thông từ DT744 xuống DH609", "DH609"),
    ("Mặt tiền ĐT744; thông xuống DH609", "DT744"),
    ("Đường Bùi Quốc Khánh; gần QL13", "Bui Quoc Khanh"),
    ("Cách QL13 50m; mặt tiền đường Hồng Hà", "Hong Ha"),
])
def test_connection_endpoints_are_not_fronting_streets(text,expected):
    assert extract_road_name(text) == expected


@pytest.mark.parametrize("text", [
    "thanh lý đất thành phố mới Thủ Dầu Một; Diện tích: 160m² thổ cư",
    "Duy nhất 1 lô ... 5x23 ... Có 80m thổ cư",
])
def test_reviewed_property_excerpts_already_parse_as_land(text):
    # Excerpt-only controls, NOT proof that the full original raw record is fixed.
    record=normalize_record({"source":"facebook", "url":"https://example.invalid/control", "title":text,"description":""})
    assert record is not None and record["property_type"]=="dat_nen"


# Supplemented from the existing offline review queue, exact selected IDs only.
# Reduced, PII-free fixtures preserve the actual triggering language omitted
# from the initial excerpt; synthetic variants below are not extra real cases.
REMAINING_PROPERTY_CASES = [
    (83249, "guland", "Thanh lý đất tp. thủ dầu một cho vay 80% giá trị",
     "Thấp hơn cả chung cư - ngân hàng thanh lý đất thành phố mới Thủ Dầu Một. Diện tích: 160m² thổ cư"),
    (83155, "facebook", "Duy nhất 1 lô rẻ nhát Tân An 1/ Mạc Đĩnh Chi cách 100m giá 1.33tỷ - 5x23 đường oto",
     "Có 80m thổ cư. Xem nhà ngay"),
]


@pytest.mark.parametrize("listing_id,source,title,description", REMAINING_PROPERTY_CASES)
def test_remaining_reviewed_property_cases_classify_as_land(listing_id,source,title,description):
    assert classify_property_type(title,description,160 if listing_id==83249 else 115,80)=="dat_nen"


@pytest.mark.parametrize("listing_id,source,title,description", REMAINING_PROPERTY_CASES)
def test_remaining_reviewed_property_cases_normalize_as_land(listing_id,source,title,description):
    record=normalize_record({"source":source,"url":"https://example.invalid/case","title":title,"description":description})
    assert record is not None and record["property_type"]=="dat_nen"


@pytest.mark.parametrize("title,description,expected", [
    ("Thanh lý đất thổ cư", "Giá thấp hơn cả chung cư, DT 160m2", "dat_nen"),
    ("Thanh lý đất thổ cư", "Giá rẻ hơn căn hộ, DT 160m2", "dat_nen"),
    ("Thanh ly dat", "Gia thap hon chung cu. DT 160m2", "dat_nen"),
    ("Căn hộ chung cư 2PN", "Giá thấp hơn cả chung cư bên cạnh", "chung_cu"),
    ("Bán căn hộ 2PN", "Giá rẻ hơn đất nền", "chung_cu"),
    ("Bán chung cư", "Giá rẻ hơn căn hộ bên cạnh, có thang máy", "chung_cu"),
    ("Thanh lý đất", "Giá thấp hơn cả chung cư; có căn hộ 2PN đang cho thuê", "chung_cu"),
    ("Bán nhà cấp 4", "Giá rẻ hơn cả chung cư, 2 phòng ngủ, bếp", "nha_dat"),
])
def test_comparison_targets_do_not_replace_actual_asset_type(title,description,expected):
    assert classify_property_type(title,description,160,None)==expected


@pytest.mark.parametrize("title,description,expected", [
    ("Duy nhất 1 lô 5x23 Tân An", "Có 80m thổ cư. Xem nhà ngay", "dat_nen"),
    ("Bán đất nền 5x20", "Liên hệ xem nhà ngay", "dat_nen"),
    ("Ban lo 5x20", "Lien he xem nha ngay", "dat_nen"),
    ("Giảm bán nhanh mặt tiền đường nhựa nhà Phú Mỹ", "LH xem nhà", "nha_dat"),
    ("Chính chủ bán nhà", "Liên hệ xem nhà ngay", "nha_dat"),
    ("Bán đất có nhà cấp 4", "Liên hệ xem nhà ngay", "nha_dat"),
    ("Duy nhất 1 lô 5x23", "Nhà mới, 3PN 2WC. Xem nhà ngay", "nha_dat"),
    ("Bán căn hộ chung cư", "Xem nhà ngay", "chung_cu"),
])
def test_land_viewing_cta_does_not_remove_real_house_evidence(title,description,expected):
    assert classify_property_type(title,description,115,80)==expected


AN_DIEN_REVIEWED_ADDRESS = "An Điền - Bình Dương cũ ( Phường Long Nguyên - TP.HCM )"


def test_reviewed_an_dien_old_address_is_strong_not_new_ward_guess():
    result=resolve_post_merger_location("NHÀ AN ĐIỀN MỚI ĐẸP",AN_DIEN_REVIEWED_ADDRESS,intended_city="Bến Cát")
    assert result.ward=="An Điền" and result.new_ward=="Long Nguyên"
    assert result.has_strong_old_ward


def test_reviewed_an_dien_survives_broad_new_ward_outside_keyword():
    record=normalize_record({"source":"facebook","url":"https://example.invalid/case","default_area":"Bến Cát",
                            "title":"NHÀ AN ĐIỀN MỚI ĐẸP","description":AN_DIEN_REVIEWED_ADDRESS})
    assert record is not None and record["ward"]=="An Điền" and record["area"]=="An Điền"


@pytest.mark.parametrize("text", [
    "An Điền cũ nay là phường Long Nguyên TP.HCM",
    "An Dien Binh Duong cu, phuong Long Nguyen TP HCM",
    "An Điền - Bình Dương cũ nay thuộc phường Long Nguyên",
])
def test_explicit_old_an_dien_mapping_variants(text):
    assert resolve_post_merger_location(text).has_strong_old_ward
    record=normalize_record({"source":"facebook","url":"https://example.invalid/case","title":"Nhà","description":text})
    assert record is not None and record["ward"]=="An Điền"


@pytest.mark.parametrize("text", [
    "Phường Long Nguyên TP.HCM",
    "Long Nguyên, đất 20x37 có thổ cư",
    "Phường Long Nguyên, gần An Điền cũ",
    "Phường Long Nguyên, cách 2km đến An Điền cũ",
    "Gần An Điền - Bình Dương cũ (Phường Long Nguyên TP.HCM)",
])
def test_broad_new_ward_or_nearby_an_dien_does_not_manufacture_old_ward(text):
    result=resolve_post_merger_location(text)
    assert not result.has_strong_old_ward
    record=normalize_record({"source":"facebook","url":"https://example.invalid/case","default_area":"Bến Cát",
                            "title":"Bán đất","description":text})
    assert record is not None and record["ward"] is None and record["area"]=="Other"


@pytest.mark.parametrize("text,expected", [
    ("CHÁNH HIỆP\nNHÀ MẶT TIỀN DX072\nVị trí: DX072 thông MPTV, Quốc lộ 13", "DX72"),
    ("Nhà mặt tiền DX072, vị trí thông MPTV, Quốc lộ 13", "DX72"),
    ("Quốc lộ 13, nhà mặt tiền DX072", "DX72"),
    ("Mặt tiền QL13, gần DX072", "QL13"),
    ("Gần nhà mặt tiền DX072, cách QL13 50m", None),
    ("Giá cho lô mặt tiền đẹp\nMẶT TIỀN Bùi Ngọc Thu", "Bui Ngoc Thu"),
    ("Mặt Tiền Nguyễn Chí Thanh Tân An Thủ Dầu Một (P Phú An Tp HCM)", "Nguyen Chi Thanh"),
    ("Hẻm 232 Nguyễn Đức Thuận (Hiệp Thành)", "Hem 232 Nguyen Duc Thuan"),
    ("Đất 2 mặt tiền tân phước khánh\nDt 15x25 thổ cư 150m", None),
    ("Đất hai mặt tiền Phú Lợi", None),
    ("Đất 2 mặt tiền đường Phú Lợi", "Phu Loi"),
    ("Mặt tiền đường Tân Phước Khánh", "Tan Phuoc Khanh"),
])
def test_review19_fronting_road_and_locality_cases(text,expected):
    assert extract_road_name(text)==expected


@pytest.mark.parametrize("listing_id,title", [
    (82948,"Nhà tại Phú An"),
    (82949,"Lô đất hẻm Thanh Bình Phú An"),
])
def test_review19_old_phu_an_has_ben_cat_profile_evidence(listing_id,title):
    description="Phú An - Bình Dương cũ (Phường Phú An - TP.HCM)"
    result=resolve_post_merger_location(title,description,intended_city="Bến Cát")
    assert result.ward=="Phú An" and result.has_strong_old_ward
    record=normalize_record({"source":"facebook","url":"https://example.invalid/case","default_area":"Bến Cát",
                            "title":title,"description":description})
    assert record is not None and record["ward"]=="Phú An"


@pytest.mark.parametrize("description,profile", [
    ("Phường Phú An TP.HCM","Bến Cát"),
    ("Gần Phú An - Bình Dương cũ (Phường Phú An TP.HCM)","Bến Cát"),
    ("Phú An - Bình Dương cũ (Phường Phú An TP.HCM)",None),
])
def test_old_phu_an_needs_real_location_and_city_evidence(description,profile):
    assert not resolve_post_merger_location("Bán đất",description,intended_city=profile).has_strong_old_ward


def test_review19_dx072_uses_old_canonical_ward_not_broad_review_label():
    # Signal's historical Chánh Hiệp override is NOT canonical ground truth.
    record=normalize_record({"source":"facebook","url":"https://example.invalid/case","default_area":"Thủ Dầu Một",
                            "title":"🧨 CHÁNH HIỆP 🧨\nNHÀ MẶT TIỀN DX072","description":"DX072 thông MPTV, Quốc lộ 13"})
    assert record is not None and record["ward"]=="Định Hòa" and record["road_name"]=="DX72"


@pytest.mark.parametrize("title,description", [
    ("CHÁNH HIỆP","Nhà mặt tiền Lê Văn Tách"),
    ("Nhà vườn Mặt tiền Lê Văn Tách. P Chánh Hiệp - TP Hồ Chí Minh",""),
    ("Gần Chánh Hiệp","Đất mặt tiền DX072"),
])
def test_unknown_old_ward_is_not_replaced_with_new_admin_ward(title,description):
    record=normalize_record({"source":"facebook","url":"https://example.invalid/case","default_area":"Thủ Dầu Một",
                            "title":title,"description":description})
    assert record is not None and record["ward"] is None


# 20261022-150007:83537:{frontage_m,depth_m}; 83563:frontage_m.
# Two independent source phrases, not two copies of the same listing.
REVIEW22_DIMENSION_CASES = [
    (83537, "Diện tích: 185m²; Ngang 8,53 × dài 22m", 8.53, 22.0, 185.0),
    (83563, "Dt : 339m thổ cư 184m ( ngang 11)", 11.0, None, 339.0),
]


@pytest.mark.parametrize("listing_id,text,frontage,depth,area", REVIEW22_DIMENSION_CASES)
def test_review22_explicit_dimension_phrases(listing_id, text, frontage, depth, area):
    assert extract_dimensions(text) == {"frontage_m": frontage, "depth_m": depth}


@pytest.mark.parametrize("listing_id,text,frontage,depth,area", REVIEW22_DIMENSION_CASES)
def test_review22_dimensions_preserve_declared_area_through_normalization(listing_id, text, frontage, depth, area):
    record = normalize_record({
        "source": "facebook", "url": "https://example.invalid/dimension-control",
        "title": text, "description": "",
    })
    assert record is not None
    assert record["frontage_m"] == frontage
    assert record["measurement_provenance"]["frontage_m"] == "source_text"
    assert record["area_m2"] == area
    assert record["measurement_provenance"]["area_m2"] == "declared_text"
    if depth is not None:
        assert record["depth_m"] == depth
        assert record["measurement_provenance"]["depth_m"] == "source_text"
    else:
        # Existing display-only inference remains separate from extracted text.
        # The source does NOT declare a depth; do not mark a quotient source_text.
        assert record["depth_m"] == round(area / frontage, 1)
        assert record["measurement_provenance"]["depth_m"] == "derived_area_frontage"
        assert record["tho_cu_m2"] == 184.0


@pytest.mark.parametrize("text,expected", [
    ("ngang 8,53 × dài 22m", {"frontage_m": 8.53, "depth_m": 22.0}),
    ("NGANG 8.53M × SÂU 22M", {"frontage_m": 8.53, "depth_m": 22.0}),
    ("ngang 8,53 x dài 22m", {"frontage_m": 8.53, "depth_m": 22.0}),
    ("ngang 8,53 dài 22m", {"frontage_m": 8.53, "depth_m": 22.0}),
    ("DT 185m2 (ngang 8,53)", {"frontage_m": 8.53, "depth_m": None}),
    ("DT 339m2 ( NGANG 11 )", {"frontage_m": 11.0, "depth_m": None}),
    ("(ngang 11m)", {"frontage_m": 11.0, "depth_m": None}),
    ("ngang 11m", {"frontage_m": 11.0, "depth_m": None}),
])
def test_review22_labeled_dimension_separator_and_parenthesis_controls(text, expected):
    assert extract_dimensions(text) == expected


@pytest.mark.parametrize("text", [
    "(ngang 11%)", "(ngang 11m2)", "(ngang 11m²)",
    "(ngang 11abc)", "(ngang 11,5abc)", "(ngang 11 phòng)",
    "(ngang 110)", "(ngang 1)", "đường ngang 11 lô đất",
    "(đường ngang 11)", "diện tích 185m², đường rộng 11m",
    "ngang 8,53 × đường dài 22m",
])
def test_review22_unitless_frontage_requires_unambiguous_dimension_context(text):
    assert extract_dimensions(text) == {"frontage_m": None, "depth_m": None}


# Seven independent exact-ID source patterns from the 22/24 October snapshots.
# Short supplemental clauses retain the parser trigger; no raw descriptions/PII.
REVIEW24_ROAD_CASES = [
    (83455, "guland", "BÁN GẤP NHÀ CẤP 4 MẶT TIỀN PHAN ĐĂNG LƯU – HIỆP AN",
     "Chợ Bưng Cầu, QL13: 400m", "", "Phan Dang Luu"),
    (83648, "guland", "Bán nhà", "Kết nối thuận tiện với Quốc lộ 13",
     "Đường Hồ Văn Cống, Phường Tương Bình Hiệp", "Ho Van Cong"),
    (83458, "guland", "Bán nhà Chánh Nghĩa Bình Dương", "Chủ cần bán căn nhà p. Chánh Nghĩa",
     "", None),
    (83320, "facebook", "bán nhà gác lửng và 6 phòng trọ mặt tiền Nguyễn hữu Cảnh _gần chợ Búng",
     "", "", "Nguyen Huu Canh"),
    (84029, "facebook", "2ty3 giảm chỉ còn 1ty5x thôi  nhanh mới kịp",
     "2ty3 giảm chỉ còn 1ty5x thôi  nhanh mới kịp\nĐất Phú Mỹ ngang 7 dài 15", "", None),
    (84003, "facebook", "TÂN PHƯỚC KHÁNH 07– NHÀ ĐẸP",
     "Khách thiện chí, nhanh gọn bớt lộc may; Đường 6m thông thoáng", "", None),
    (83998, "facebook", "BÁN NHÀ LÁI THIÊU ĐƯỜNG XE OTO",
     "BÁN NHÀ LÁI THIÊU ĐƯỜNG XE OTO\nDt 120m2 Nhà lầu trệt 4 phòng ngủ", "", None),
]


@pytest.mark.parametrize("listing_id,source,title,description,address,expected", REVIEW24_ROAD_CASES)
def test_review24_road_name_source_fragments(listing_id, source, title, description, address, expected):
    assert extract_road_name(" ".join((title, description, address))) == expected


@pytest.mark.parametrize("listing_id,source,title,description,address,expected", REVIEW24_ROAD_CASES)
def test_review24_road_name_full_normalization(listing_id, source, title, description, address, expected):
    record = normalize_record({"source": source, "url": "https://example.invalid/road-control",
                               "title": title, "description": description, "address": address})
    assert record is not None and record["road_name"] == expected


@pytest.mark.parametrize("text,expected", [
    ("Đường Phan Đăng Lưu Phường Hiệp An Thành phố Thủ Dầu Một Bình Dương", "Phan Dang Luu"),
    ("QL13: 400m; Mặt tiền Phan Đăng Lưu", "Phan Dang Luu"),
    ("Quốc lộ 13: 400m; Đường Hồ Văn Cống", "Ho Van Cong"),
    ("Kết nối thuận tiện với QL13; Đường Hồ Văn Cống", "Ho Van Cong"),
    ("Kết nối với Quốc lộ 13", None),
    ("Đất cách QL13: 400m", None),
    ("Mặt tiền QL13; diện tích 400m2", "QL13"),
    ("Mặt tiền Quốc lộ 13, đường rộng 20m", "QL13"),
    ("Nhánh Nguyễn Đức Thuận, đường ô tô 4m", "Nguyen Duc Thuan"),
    ("Nhanh Nguyen Duc Thuan, duong o to 4m", "Nguyen Duc Thuan"),
    ("Đường xe ô tô", None),
    ("Đường xe oto vào tận nhà", None),
    ("Nhanh gọn bớt lộc; đường Nguyễn Tri Phương", "Nguyen Tri Phuong"),
    ("Chủ cần bán nhà mặt tiền đường Nguyễn Hữu Cảnh_gần chợ", "Nguyen Huu Canh"),
    ("Gần đường Nguyễn Hữu Cảnh_gần chợ", None),
    ("Mặt tiền đường Lê Hồng Phong nối dài_gần chợ", "Le Hong Phong Noi Dai"),
    ("Đường Phú Lợi Phú Hòa", "Phu Loi Phu Hoa"),
])
def test_review24_road_prose_proximity_and_real_street_controls(text, expected):
    assert extract_road_name(text) == expected


# Five reviewed records, three independent measurement phrases (two repost pairs).
REVIEW25_DECLARED_AREA_CASES = [
    (84125, "DT 5,8x20,8m – 130m²; NỞ HẬU 7M", 130.0, 5.8, 20.8),
    (83877, "DT 5,8x20,8m – 130m²", 130.0, 5.8, 20.8),
    (84056, "DT: 6x146m, 866 m2 có 100 m2 thổ cư, 2 mặt tiền đường", 866.0, 6.0, 146.0),
    (83842, "DT: 6x146m, 866 m2 có 100 m2 thổ cư", 866.0, 6.0, 146.0),
    (83865, "DT: 5x30,9 : 153m2 : TC: 75m2", 153.0, 5.0, 30.9),
]


@pytest.mark.parametrize("listing_id,text,area,frontage,depth", REVIEW25_DECLARED_AREA_CASES)
@pytest.mark.parametrize("text_field", ["title", "description"])
def test_review25_declared_area_after_dimensions(listing_id, text, area, frontage, depth, text_field):
    record = normalize_record({"source": "facebook", "url": "https://example.invalid/area-control",
                               "title": "Bán đất", text_field: text, "price_ty": 3.0})
    assert record is not None
    assert record["area_m2"] == area
    assert record["frontage_m"] == frontage
    assert record["depth_m"] == depth
    assert record["measurement_provenance"]["area_m2"] == "declared_text"
    assert record["price_per_m2"] == round(3000 / area, 3)


@pytest.mark.parametrize("text,expected", [
    ("Diện tích: 5,8 × 20,8m — 130 m²", 130.0),
    ("DT: 5.8m*20.8m, 130mv", 130.0),
    ("DT: 5x20 : 96 mét vuông", 96.0),
    ("DT: 5x20m - 96 m2", 96.0),
    ("DT: 5x20m = 96 m2", 96.0),
    ("DT: 5x20m; Tổng 96 m2", 96.0),
    ("DT: 5x20m (96 m2)", 96.0),
    ("DT: 5x20m", 100.0),
    ("DT: 5x20m, 60m2 thổ cư", 100.0),
    ("DT: 5x20m, 60m2 TC", 100.0),
    ("DT: 5x20m, 60m2 ODT", 100.0),
    ("DT: 5x20m, 160m2 sàn", 100.0),
    ("DT: 5x20m, 160m2 sử dụng", 100.0),
    ("DT: 5x20m, 160m2 xây dựng", 100.0),
    ("DT: 5x20m, thổ cư 60m2", 100.0),
    ("DT: 5x20m, đường rộng 6m", 100.0),
    ("DT: 5x20m, cách chợ 96m", 100.0),
    ("DT: 5x20m, 96m", 100.0),
    ("DT: 5x20m, 96m2 x 2 lô", 100.0),
    ("DT: 5x20m, 96m2abc", 100.0),
    ("DT: 5x20m, 100000m2", 100.0),
    # Unselected differential controls: these change provenance only, not area.
    ("Diện tích: 5×24m – 120m², full thổ cư", 120.0),
    ("DT: 5 x 22, 110m2, TC: 80m2", 110.0),
    ("DT: 5x46m, 100 m2 thổ c", 230.0),
])
def test_review25_post_dimension_total_requires_land_area_context(text, expected):
    record = normalize_record({"source": "facebook", "url": "https://example.invalid/area-control",
                               "title": "Bán đất", "description": text})
    assert record is not None and record["area_m2"] == expected
    if text in ("Diện tích: 5×24m – 120m², full thổ cư", "DT: 5 x 22, 110m2, TC: 80m2"):
        assert record["measurement_provenance"]["area_m2"] == "declared_text"


def test_review25_truncated_title_residential_unit_does_not_override_land_dimensions():
    # Exact cause-bearing clauses from historical #83103, not a new reviewed fix.
    record = normalize_record({"source": "facebook", "url": "https://example.invalid/area-control",
                               "title": "DT: 5x46m, 100 m2 thổ c",
                               "description": "DT: 5x46m, 100 m2 thổ cư."})
    assert record is not None and record["area_m2"] == 230.0
    assert record["tho_cu_m2"] == 100.0
    assert record["measurement_provenance"]["area_m2"] == "derived_dimensions"


def test_review25_explicit_total_replaces_structured_rectangular_estimate():
    record = normalize_record({"source": "facebook", "url": "https://example.invalid/area-control",
                               "title": "Bán đất", "description": "DT 5,8x20,8m – 130m²",
                               "area_m2": 120.6})
    assert record is not None and record["area_m2"] == 130.0
    assert record["measurement_provenance"]["area_m2"] == "declared_text"


# Four reviewed field-cases, TWO independent patterns: each pair is a repost.
REVIEW27_PROPERTY_CONTEXT_CASES = [
    (84188, "CÓ NGAY CĂN TRỌ CHO THUÊ", "Trọ xây kiêng cố, chắc chắn bao gồm 1 kiot và 7 phòng trọ", "nha_tro"),
    (84407, "CÓ NGAY CĂN TRỌ CHO THUÊ", "Trọ xây kiêng cố, chắc chắn bao gồm 1 kiot và 7 phòng trọ", "nha_tro"),
    (84120, "Cần bán gấp đất góc mặt tiền đường Vành Đai", "DT: 292m², 2 mặt tiền; Thích hợp xây căn hộ dịch vụ, nhà ở, kinh doanh…", "dat_nen"),
    (84608, "Cần bán gấp đất góc mặt tiền đường Vành Đai", "DT: 292m², 2 mặt tiền; Thích hợp xây căn hộ dịch vụ, nhà ở, kinh doanh…", "dat_nen"),
]


@pytest.mark.parametrize("listing_id,title,description,expected", REVIEW27_PROPERTY_CONTEXT_CASES)
def test_review27_existing_rental_vs_future_building_use(listing_id, title, description, expected):
    assert classify_property_type(title, description, 292, 100) == expected


@pytest.mark.parametrize("listing_id,title,description,expected", REVIEW27_PROPERTY_CONTEXT_CASES)
def test_review27_property_context_full_normalization(listing_id, title, description, expected):
    record = normalize_record({"source": "facebook", "url": "https://example.invalid/property-control",
                               "title": title, "description": description})
    assert record is not None and record["property_type"] == expected


@pytest.mark.parametrize("title,description,expected", [
    ("Bán đất", "Thích hợp xây căn trọ cho thuê", "dat_nen"),
    ("Bán đất", "Có thể xây căn trọ, thu nhập dự kiến", "dat_nen"),
    ("Bán đất", "Thích hợp xây căn hộ dịch vụ, nhà ở, kinh doanh", "dat_nen"),
    ("Bán đất", "Phù hợp xây căn hộ dịch vụ, nhà ở", "dat_nen"),
    ("Bán đất", "Thích hợp xây căn hộ dịch vụ. Nhà ở hiện hữu 3PN, 2WC", "nha_dat"),
    ("Bán đất", "Thích hợp xây căn hộ dịch vụ, nhà ở 3PN hiện hữu", "nha_dat"),
    ("Bán căn hộ dịch vụ", "Nhà ở, kinh doanh, đang cho thuê", "chung_cu"),
    ("Bán nhà cấp 4", "Phù hợp xây căn hộ dịch vụ, nhà ở, kinh doanh", "nha_dat"),
    ("Bán căn trọ đang cho thuê", "1 kiot, thu nhập hàng tháng", "nha_tro"),
    ("Bán căn trọ", "Trọ xây kiên cố bao gồm 1 kiot và 7 phòng trọ", "nha_tro"),
    ("Bán nhà", "Nhà trong khu dân cư, 2PN", "nha_dat"),
    ("Bán dãy trọ", "12 phòng trọ đang cho thuê", "nha_tro"),
])
def test_review27_property_context_controls(title, description, expected):
    assert classify_property_type(title, description, 292, 100) == expected


# Two independent reviewed price patterns, not duplicate repost evidence.
REVIEW29_PRICE_CASES = [
    (85002, "GIẢM 1 tỷ 200tr MỘT Siêu phẩm nhà phố có HOÀN CÔNG; Giá Chỉ Còn 6tỷ 600 triệu làm việc chủ (Giá cũ 7tỷ8)", 6.6),
    (84608, "Giá bán gấp: 8 ,5 ty", 8.5),
]


@pytest.mark.parametrize("listing_id,text,expected", REVIEW29_PRICE_CASES)
def test_review29_source_backed_asking_prices(listing_id, text, expected):
    assert parse_facebook_post(text)["price_total"] == expected


@pytest.mark.parametrize("listing_id,text,expected", REVIEW29_PRICE_CASES)
def test_review29_asking_price_full_normalization(listing_id, text, expected):
    record = normalize_record({"source": "facebook", "url": "https://example.invalid/price-control",
                               "title": "Bán nhà đất", "description": text, "area_m2": 100.0})
    assert record is not None and record["price_ty"] == expected
    assert record["price_per_m2"] == round(expected * 1000 / 100.0, 3)


@pytest.mark.parametrize("text,expected", [
    ("Giảm 1 tỷ 200tr", None),
    ("Giam gia 1ty200tr; gia chi con 6ty600tr", 6.6),
    ("Hạ 1 tỷ 200 triệu; giá bán 6 tỷ 600", 6.6),
    ("Bớt 1 tỷ 200; giá 6 tỷ 600", 6.6),
    ("Giảm còn 1ty350tr, mô tả còn 1ty3xx", 1.35),
    ("Giảm 400 triệu giá 4,2 tỷ chỉ còn 3,8 tỷ", 3.8),
    ("Giá 1 tỷ 200tr", 1.2),
    ("Giảm giá, bán 1 tỷ 200tr", 1.2),
    ("Giảm 1 tỷ 200tr; giá thỏa thuận", None),
    ("Giảm còn 1 tỷ 200tr", 1.2),
    ("Giá 8 ,5 tỷ", 8.5),
    ("Giá 8, 5 ty", 8.5),
    ("Giá 8 . 5 ti", 8.5),
    ("Giá 8 , 05 tỷ", 8.05),
    ("Giá 8,5 tỷ", 8.5),
    ("DT 8 ,5m; Giá 3 tỷ", 3.0),
    ("Giá >1 ,5 tỷ", None),
    ("Giá 8 ,x tỷ", None),
])
def test_review29_price_grammar_controls(text, expected):
    assert parse_facebook_post(text)["price_total"] == expected


# Two independent residential-label spellings, not repost evidence.
# Newline after the phun label is preserved from the exact-ID offline snapshot:
# excerpt-only text ending at the label can accidentally pass a bare-full rule.
REVIEW31_RESIDENTIAL_CASES = [
    (85253, "Diện tích 245m2 tcư 68.6m2\nĐường nhựa 12m", 245.0, 68.6, 0.28),
    (85053, "Diện tích 5 x 30 tổng 150m phun thổ cư\n- Giá 2 tỷ 9", 150.0, 150.0, 1.0),
]


@pytest.mark.parametrize("listing_id,text,area,residential,ratio", REVIEW31_RESIDENTIAL_CASES)
def test_review31_residential_spelling_parser(listing_id, text, area, residential, ratio):
    parsed = parse_facebook_post(text)
    assert parsed["tho_cu_m2"] == residential
    assert parsed["tho_cu_ratio"] == ratio
    assert parsed["area_m2"] == area


@pytest.mark.parametrize("listing_id,text,area,residential,ratio", REVIEW31_RESIDENTIAL_CASES)
def test_review31_residential_spelling_full_normalization(listing_id, text, area, residential, ratio):
    record = normalize_record({"source": "facebook", "url": "https://example.invalid/residential-control",
                               "title": "Bán đất", "description": text})
    assert record is not None
    assert record["tho_cu_m2"] == residential
    assert record["tho_cu_ratio"] == ratio
    assert record["area_m2"] == area
    assert record["measurement_provenance"]["tho_cu_m2"] == "source_text"


@pytest.mark.parametrize("text,area,residential,ratio", [
    ("TCƯ 68,6m2", 245.0, 68.6, 0.28),
    ("tcu 68.6m2", 245.0, 68.6, 0.28),
    ("68.6m2 tcư", 245.0, 68.6, 0.28),
    ("không tcư 68.6m2", 245.0, None, None),
    ("chưa tcư 68.6m2", 245.0, None, None),
    ("tcuong 68.6m2", 245.0, None, None),
    ("PHUN THỔ CƯ\nGiá 2 tỷ 9", 150.0, 150.0, 1.0),
    ("phun tho cu\nGia 2 ty 9", 150.0, 150.0, 1.0),
    ("không phun thổ cư", 150.0, None, None),
    ("chưa phun thổ cư", 150.0, None, None),
    ("phun thuốc; thổ cư 60m2", 150.0, 60.0, 0.4),
    ("phun thổ cư", None, None, None),
    ("thổ cư 68.6m2", 245.0, 68.6, 0.28),
    ("tc 60m2", 150.0, 60.0, 0.4),
    ("full thổ cư", 150.0, 150.0, 1.0),
    ("150m2 đất vườn", 150.0, None, None),
])
def test_review31_residential_spelling_controls(text, area, residential, ratio):
    from cleansing.feature_extractor import extract_tho_cu

    assert extract_tho_cu(text, area) == {"tho_cu_m2": residential, "tho_cu_ratio": ratio}


# Four reviewed records, TWO independent patterns (each pair is a repost).
# Exact cause-bearing, PII-free fragments from the bound offline snapshots.
REVIEW_NOV01_AREA_SUFFIX_CASES = [
    (85527, "Dt: 21,5 x 117👉2517m2. CLN", 2517.0, 21.5, 117.0),
    (85432, "Dt: 21,5 x 117👉2517m2. CLN", 2517.0, 21.5, 117.0),
    (85590, "Dt 5 * 32; 147m; Tc 60m", 147.0, 5.0, 32.0),
    (85364, "Dt 5 * 32; 147m; Tc 60m", 147.0, 5.0, 32.0),
]


@pytest.mark.parametrize("listing_id,text,area,frontage,depth", REVIEW_NOV01_AREA_SUFFIX_CASES)
@pytest.mark.parametrize("text_field", ["title", "description"])
@pytest.mark.parametrize("structured_area", [False, True])
def test_review_nov01_declared_area_suffix_wins_over_rectangle(
        listing_id, text, area, frontage, depth, text_field, structured_area):
    raw = {"source": "facebook", "url": "https://example.invalid/area-suffix-control",
           "title": "Bán đất", text_field: text, "price_ty": 3.0}
    if structured_area:
        raw["area_m2"] = round(frontage * depth, 1)
    record = normalize_record(raw)
    assert record is not None
    assert record["area_m2"] == area
    assert record["frontage_m"] == frontage
    assert record["depth_m"] == depth
    assert record["price_per_m2"] == round(3000 / area, 3)
    assert record["measurement_provenance"]["area_m2"] == "declared_text"
    if area == 147.0:
        assert record["tho_cu_m2"] == 60.0
        assert record["tho_cu_ratio"] == round(60 / 147, 3)


@pytest.mark.parametrize("text,expected", [
    ("DT 5 x 32👉147m²", 147.0),
    ("DIỆN TÍCH 5 x 32; 147m; TC 60m", 147.0),
    ("DT 5 x 32; 147mv", 147.0),
    ("DT 5 x 32; 147 mét vuông", 147.0),
    ("DT 5 x 32; 147m", 147.0),
    ("DT 5 x 32; 147,5m; TC 60m", 147.5),
    ("DT 5 x 32; TC 60m", 160.0),
    ("DT 5 x 32👉60m2 thổ cư", 160.0),
    ("DT 5 x 32; 60m2 TC", 160.0),
    ("DT 5 x 32; 60m2 ODT", 160.0),
    ("DT 5 x 32; 147m2 sàn", 160.0),
    ("DT 5 x 32👉147m2 sử dụng", 160.0),
    ("DT 5 x 32; 147m2 xây dựng", 160.0),
    ("DT 5 x 32; 147m ngang", 160.0),
    ("DT 5 x 32; 147m3", 160.0),
    # Existing m2-as-frontage typo policy selects the later 6 x 20 pair;
    # this must not be reinterpreted as a declared total of 6 square meters.
    ("DT 5 x 32; 6m2 x 20m", 120.0),
    ("Đường 5 x 32; 147m", 160.0),
    ("DT 5 x 32; đường rộng 12m", 160.0),
    ("DT 5 x 32; cách chợ 147m", 160.0),
    ("DT 5 x 32, 147m2", 147.0),
    ("DT 5 x 32 = 147m2", 147.0),
    ("DT 5 x 32 (147m2)", 147.0),
])
def test_review_nov01_area_suffix_controls(text, expected):
    record = normalize_record({"source": "facebook", "url": "https://example.invalid/area-suffix-control",
                               "title": "Bán đất", "description": text})
    assert record is not None and record["area_m2"] == expected


# Two independent reviewed phrases, not duplicated repost evidence.
REVIEW_NOV02_FUTURE_ASPHALT = [
    (85676, "Đường 7m thông chuẩn bị rải nhựa"),
    (85725, "Đường sắp đổ nhựa nhựa 6m, dân cư đông"),
]


@pytest.mark.parametrize("listing_id,text", REVIEW_NOV02_FUTURE_ASPHALT)
def test_review_nov02_future_asphalt_is_not_existing_surface(listing_id, text):
    from cleansing.feature_extractor import extract_road_type

    assert extract_road_type(text) == "unknown"


@pytest.mark.parametrize("listing_id,text", REVIEW_NOV02_FUTURE_ASPHALT)
@pytest.mark.parametrize("text_field", ["title", "description"])
def test_review_nov02_future_asphalt_full_normalization(listing_id, text, text_field):
    record = normalize_record({"source": "facebook", "url": "https://example.invalid/road-control",
                               "title": "Bán đất", "area_m2": 100.0, "price_ty": 2.0,
                               text_field: text})
    assert record is not None
    assert record["road_type"] == "unknown"
    assert record["area_m2"] == 100.0
    assert record["price_ty"] == 2.0


@pytest.mark.parametrize("text,expected", [
    ("Duong 7m thong chuan bi rai nhua", "unknown"),
    ("Đường chuẩn bị đổ nhựa", "unknown"),
    ("Đường sắp rải nhựa 6m", "unknown"),
    ("Đường SẮP ĐỔ NHỰA NHỰA 6m", "unknown"),
    ("Đường sắp đổ asphalt", "unknown"),
    ("Đường đã rải nhựa 7m", "duong_nhua"),
    ("Đường vừa đổ nhựa 6m", "duong_nhua"),
    ("Đường nhựa 6m, sắp xây nhà", "duong_nhua"),
    ("Đường nhựa hiện hữu; đường khác sắp đổ nhựa", "duong_nhua"),
    ("Đường sắp đổ nhựa; đường nhựa hiện hữu", "duong_nhua"),
    ("Đường bê tông 7m thông chuẩn bị rải nhựa", "be_tong"),
    ("Đường đất 7m chuẩn bị rải nhựa", "duong_dat"),
    ("Đường sắp mở; đường nhựa thông 6m", "duong_nhua"),
    ("Đường 7m thông; chuẩn bị xây nhà. Đường nhựa", "duong_nhua"),
    ("Đường nhựa 6m gần chợ", "duong_nhua"),
    ("Cách đường nhựa 100m", "unknown"),
])
def test_review_nov02_future_asphalt_controls(text, expected):
    from cleansing.feature_extractor import extract_road_type

    assert extract_road_type(text) == expected


# Source-backed non-road usages: Bình Dương, nghỉ dưỡng, bán nhanh,
# đèn đường and accessibility descriptions are not street names.
# 85898/85711/85705 share a repost pattern, not independent evidence.
REVIEW_NOV03_NON_ROAD_NAMES = [
    (85813, "An Tây Bến Cát Bình Dương giáp ranh KCN Rạch Bắp", "", None),
    (85840, "đường bê tông ô tô tới đất, điện nước đèn đường tới đất", "", None),
    (85898, "nhà vườn nghỉ dưỡng hoặc đầu tư lâu dài", "", None),
    (85841, "Nhà cấp 4 Chánh Mỹ Thủ Dầu Một Bình Dương Vị trí gần trường Nguyễn Văn Cừ , Cầu Phú Cường , đường bê tông 4m", "", None),
    (85711, "nhà vườn nghỉ dưỡng hoặc đầu tư lâu dài", "", None),
    (85705, "nhà vườn nghỉ dưỡng hoặc đầu tư lâu dài", "", None),
    (85788, "Thủ Dầu Một Bình Dương Đất Chánh Mỹ cũ", "", None),
    (85792, "Đất Phú Cường sát bên Huỳnh Văn Cù gần cầu Phú Cường; đường xe ba gác", "", None),
    (85666, "Thủ Dầu Một Bình Dương Vị trí\n\nNhà nằm trong khu dân cư", "Đường Hồ Văn Cống, Phường Tương Bình Hiệp", "Ho Van Cong"),
    (85667, "Thủ Dầu Một Bình Dương Ngân hàng VIB thanh lý bán đấu giá", "", None),
    (85573, "GIẢM GIÁ BÁN NHANH LÔ ĐẤT; Đường bê tông 4,5m ô tô", "", None),
    (85527, "Vườn nghỉ dưỡng Phú An, P. Phú An; Đất mặt tiền đường đất xe ô tô", "", None),
]


@pytest.mark.parametrize("listing_id,text,address,expected", REVIEW_NOV03_NON_ROAD_NAMES)
def test_review_nov03_non_road_phrases_do_not_name_a_street(listing_id, text, address, expected):
    assert extract_road_name(" ".join(filter(None, [text, address]))) == expected


@pytest.mark.parametrize("listing_id,text,address,expected", REVIEW_NOV03_NON_ROAD_NAMES)
def test_review_nov03_non_road_phrases_full_normalization(listing_id, text, address, expected):
    record = normalize_record({
        "source": "facebook", "url": "https://example.invalid/non-road-phrase-control",
        "title": text, "address": address, "area_m2": 100.0, "price_ty": 2.0,
    })
    assert record is not None
    assert record["road_name"] == expected
    assert record["area_m2"] == 100.0
    assert record["price_ty"] == 2.0


@pytest.mark.parametrize("text,expected", [
    ("Binh   Duong Vi tri gan cho; Duong be tong", None),
    ("NHA VUON NGHI DUONG HOAC DAU TU LAU DAI", None),
    ("Dien nuoc den duong toi dat", None),
    ("Ban nhanh lo dat gia re", None),
    ("Đường xe ba gác", None),
    ("Đường xe 3 gác", None),
    ("Đường đất xe ô tô", None),
    ("Đường tới đất", None),
    ("Đường Dương Quảng Hàm", "Duong Quang Ham"),
    ("Đường Bình Dương", "Binh Duong"),
    ("Mặt tiền đường Bình Dương", "Binh Duong"),
    ("Đường Đất Đỏ", "Dat Do"),
    ("Đường Lò Đất", "Lo Dat"),
    ("Nhánh Hồ Văn Cống", "Ho Van Cong"),
    ("Bình Dương Đường Hồ Văn Cống", "Ho Van Cong"),
    ("Bán nhanh nhánh Hồ Văn Cống", "Ho Van Cong"),
    ("Bán nhanh; Đường Nguyễn Văn Trỗi", "Nguyen Van Troi"),
    ("Nghỉ dưỡng; Mặt tiền đường Hồ Văn Cống", "Ho Van Cong"),
    ("Đèn đường; Hẻm 232 Nguyễn Đức Thuận", "Hem 232 Nguyen Duc Thuan"),
    ("Bình Dương; cách đường Hồ Văn Cống 100m", None),
    ("Bình Dương; mặt tiền DX072, gần QL13", "DX72"),
])
def test_review_nov03_non_road_phrase_controls(text, expected):
    assert extract_road_name(text) == expected


@pytest.mark.parametrize("description,expected", [
    ("Đất Phú Cường sát bên Huỳnh Văn Cù gần cầu Phú Cường; đường xe ba gác", None),
    ("Mặt tiền đường Huỳnh Văn Cù", "Huynh Van Cu"),
    ("Bán đất thổ cư", "Huynh Van Cu"),
    ("Gần đường Huỳnh Văn Cù; mặt tiền đường Huỳnh Văn Cù", "Huynh Van Cu"),
])
def test_review_nov03_nearby_road_is_not_promoted_from_source_address(description, expected):
    # Full 85792 replay exposes a structured address naming the nearby road.
    record = normalize_record({
        "source": "guland", "url": "https://example.invalid/nearby-address-control",
        "title": "Bán đất", "description": description,
        "address": "Đường Huỳnh Văn Cù, Phường Thủ Dầu Một, TP. HCM\nĐường Huỳnh Văn Cù, Phường Phú Cường, Thành phố Thủ Dầu Một",
    })
    assert record is not None
    assert record["road_name"] == expected


@pytest.mark.parametrize("listing_id,text", [
    (83427, "Vị trí đẹp có đèn đường ban đêm"),
    (84620, "biệt thự sân vườn nghỉ dưỡng bao đẹp Khu biệt thự"),
    (84711, "GIẢM GIÁ BÁN NHANH LÔ ĐẤT"),
    (84911, "An Tây Bến Cát Bình Dương giáp ranh KCN Rạch Bắp"),
    (84913, "GIẢM GIÁ BÁN NHANH LÔ ĐẤT"),
    (86003, "Đất Phú Cường sát bên Huỳnh Văn Cù gần cầu Phú Cường; đường xe ba gác"),
    (85432, "Vườn nghỉ dưỡng Phú An, P. Phú An; Đất mặt tiền đường đất xe ô tô"),
])
def test_review_nov03_offline_collateral_non_road_phrases(listing_id, text):
    assert extract_road_name(text) is None


def test_review_nov03_85786_source_address_does_not_promote_a_road_30m_away():
    record = normalize_record({
        "source": "guland", "url": "https://example.invalid/nearby-85786-control",
        "title": "đường oto sát bên Hồ Văn Cống cách chỉ 30m",
        "description": "giá 2ty550 TL cách hồ văn cống 30m",
        "address": "Đường Hồ Văn Cống, Phường Chánh Hiệp, TP. HCM\nĐường Hồ Văn Cống, Phường Tương Bình Hiệp, Thành phố Thủ Dầu Một",
    })
    assert record is not None
    assert record["road_name"] is None


@pytest.mark.parametrize("text,expected", [
    # Redacted source clauses from 85782/85649, 85511, 85450 and 85023.
    ("Mặt tiền Nguyễn Văn Trỗi thông ra Đại Lộ Bình Dương", "Nguyen Van Troi"),
    ("Đất Mặt Tiền Đường lớn.", None),
    ("Phú Lợi nhánh Nguyễn Bình đường nhựa thông", "Nguyen Binh"),
    ("ĐẤT MẶT TIỀN ĐƯỜNG ĐX-008, PHƯỜNG PHÚ MỸ", "DX8"),
    ("Đường Nguyễn Văn Trỗi thông tới chợ", "Nguyen Van Troi"),
    ("Đường Nguyễn Văn Trỗi nối ra đại lộ", "Nguyen Van Troi"),
    ("Đường Dương Quảng Hàm", "Duong Quang Ham"),
    ("Đường Bình Dương", "Binh Duong"),
    ("Đường Nguyễn Bình", "Nguyen Binh"),
    ("Bình Dương Đường Hồ Văn Cống", "Ho Van Cong"),
    ("Gần đường ĐX-008", None),
    ("Mặt tiền ĐT-7A", "DT7A"),
    ("Đường DT-160m2", None),
    ("Đường Lớn Nguyễn Văn Trỗi", None),
])
def test_review_nov04_road_names_preserve_boundaries_and_hyphenated_codes(text, expected):
    assert extract_road_name(text) == expected
    record = normalize_record({
        "source": "facebook", "url": "https://example.invalid/road-nov04",
        "title": text, "price_ty": 2.0, "area_m2": 100.0,
    })
    assert record is not None and record["road_name"] == expected


# 2026-11-04 road_type: independent source patterns 85840 and 85788.
# The latter needs the exact locality/title boundary absent from its issue excerpt.
NOV04_ROAD_SURFACE_CASES = [
    (85840, "đường bê tông ô tô tới đất", "be_tong"),
    (85788, "Chánh Mỹ Thành phố Thủ Dầu Một Bình Dương Đất Chánh Mỹ cũ; Đường nhựa thông; Cách chợ Chánh Mỹ 300m", "duong_nhua"),
]


@pytest.mark.parametrize("listing_id,text,expected", NOV04_ROAD_SURFACE_CASES)
def test_review_nov04_explicit_road_surface_wins_false_access_or_locality(listing_id, text, expected):
    from cleansing.feature_extractor import extract_road_type
    assert extract_road_type(text) == expected
    record = normalize_record({
        "source": "facebook", "url": "https://example.invalid/road-surface-nov04",
        "title": text, "description": "", "price_ty": 2.0, "area_m2": 100.0,
    })
    assert record is not None and record["road_type"] == expected


@pytest.mark.parametrize("text,expected", [
    ("Bình Dương đất Chánh Mỹ", "unknown"),
    ("BINH DUONG DAT CHANH MY; duong nhua thong", "duong_nhua"),
    ("Bình Dương Đất mặt tiền đường đất 4m", "duong_dat"),
    ("đường đất 4m chuẩn bị rải nhựa", "duong_dat"),
    ("Đường bê tông 4m ô tô vào tận đất", "be_tong"),
    ("Đường bê tông, xe hơi vào tận đất", "be_tong"),
    ("duong betong o to toi dat", "be_tong"),
    ("Đường ô tô tới đất", "hem_xe_hoi"),
    ("Hẻm xe hơi; đường bê tông", "hem_xe_hoi"),
    ("Tường bê tông; ô tô tới đất", "hem_xe_hoi"),
    ("Gần đường bê tông; ô tô tới đất", "hem_xe_hoi"),
    ("Cách đường bê tông 30m; ô tô tới đất", "hem_xe_hoi"),
    ("Đường bê tông, hẻm xe máy", "hem_xe_may"),
    ("Đường bê tông xe ba gác", "hem_ba_gac"),
    ("Đường nhựa thông", "duong_nhua"),
    ("Đường bê tông", "be_tong"),
    ("Mặt tiền kinh doanh đường nhựa", "mat_tien_kinh_doanh"),
])
def test_review_nov04_road_surface_negative_near_miss_and_positive_controls(text, expected):
    from cleansing.feature_extractor import extract_road_type
    assert extract_road_type(text) == expected


# Differential cohort: every additional changed record has explicit concrete
# access-road evidence. 83941/84229, 84075/84347 and 85898/85711/85705
# are repost families, not independent confirmations.
@pytest.mark.parametrize("listing_id,text", [
    (83701, "duong be tong 4m, o to vao tan noi"),
    (83941, "duong be tong 5m o to toi dat"),
    (84229, "duong be tong 5m o to toi dat"),
    (84075, "duong be tong 4,5m o to toi nha"),
    (84347, "duong be tong 4,5m o to toi nha"),
    (85898, "duong be tong, xe hoi vao tan dat, di lai vi vu thoai mai"),
    (85711, "duong be tong, xe hoi vao tan dat, di lai vi vu thoai mai"),
    (85705, "duong be tong, xe hoi vao tan dat, di lai vi vu thoai mai"),
])
def test_review_nov04_road_surface_differential_source_controls(listing_id, text):
    from cleansing.feature_extractor import extract_road_type
    assert extract_road_type(text) == "be_tong"
    record = normalize_record({
        "source": "facebook", "url": "https://example.invalid/concrete-surface-cohort",
        "title": text, "description": "", "price_ty": 2.0, "area_m2": 100.0,
    })
    assert record is not None and record["road_type"] == "be_tong"


# 2026-11-05: exact PII-free measurement fragments from 86216, 85902, 86003.
@pytest.mark.parametrize("text,expected", [
    ("Diện tích: 20m x 60m tổng 1.275m²_ thổ cư 460m2", 1275.0),
    ("Diện tích 4.5x 26.5. thổ cư 70m. Tổng diện tích sổ hồng  118m2", 118.0),
    ("DT 132m2; tổng diện tích 132.3m2 , thổ cư 90m2", 132.3),
])
def test_review_nov05_explicit_land_total_beats_dimensions_or_rounded_label(text, expected):
    from cleansing.feature_extractor import extract_area
    assert extract_area(text) == expected
    assert parse_facebook_post(text)["area_m2"] == expected


@pytest.mark.parametrize("title,description,structured,expected", [
    ("BÁN BIỆT THỰ 1.275M²_ HIỆP THÀNH",
     "Diện tích: 20m x 60m tổng 1.275m²_ thổ cư 460m2. Giá 9,4triệu/m.",
     {}, 1275.0),
    ("Diện tích 4.5x 26.5. thổ cư 70m. Tổng",
     "Diện tích 4.5x 26.5. thổ cư 70m. Tổng diện tích sổ hồng  118m2",
     {}, 118.0),
    ("DT 132m2", "tổng diện tích 132.3m2 , thổ cư 90m2; Giá chủ cần bán giảm còn 1,6tỷ",
     {"area_m2": 132.0, "price_ty": 1.6, "price_per_m2": 12.12}, 132.3),
])
def test_review_nov05_normalizer_uses_explicit_land_total(title, description, structured, expected):
    record = normalize_record({
        "source": "facebook", "url": "https://example.invalid/declared-land-total",
        "title": title, "description": description, **structured,
    })
    assert record is not None
    assert record["area_m2"] == expected
    assert record["measurement_provenance"]["area_m2"] == "declared_text"


def test_review_nov05_unit_asking_price_uses_final_land_total_86216():
    record = normalize_record({
        "source": "facebook", "url": "https://example.invalid/declared-total-unit-price",
        "title": "BÁN BIỆT THỰ 1.275M²_ HIỆP THÀNH",
        "description": "Diện tích: 20m x 60m tổng 1.275m²_ thổ cư 460m2. Giá 9,4triệu/m.",
    })
    assert record is not None
    assert record["price_ty"] == pytest.approx(11.985)
    assert record["price_per_m2"] == 9.4
    assert record["frontage_m"] == 20.0
    assert record["depth_m"] == 60.0
    assert record["tho_cu_m2"] == 460.0


@pytest.mark.parametrize("text,expected", [
    ("DT 5x20; tổng diện tích sổ hồng 98m2", 98.0),
    ("DT 5x20; TỔNG DIỆN TÍCH SỔ HỒNG: 98M²", 98.0),
    ("DT 5x20; tong dien tich so hong 98m2", 98.0),
    ("DT 5x20; tổng 98m2_ thổ cư 60m2", 98.0),
    ("DT 5x20; tổng diện tích sàn 240m2", 100.0),
    ("DT 5x20; tổng diện tích xây dựng 80m2", 100.0),
    ("DT 5x20; tổng diện tích sử dụng 240m2", 100.0),
    ("DT 5x20; tổng thổ cư 60m2", 100.0),
    ("DT 5x20; đường bê tông 6m", 100.0),
    ("DT 5x20; tổng diện tích sổ hồng 5m x 20m", 100.0),
    ("DT 5x20; tổng diện tích sổ hồng 98m2abc", 100.0),
    ("DT 5x20; tổng diện tích sổ hồng 0m2", 100.0),
    ("DT 5x20; tổng diện tích sổ hồng 100000m2", 100.0),
    ("DT 5x20; tổng 98m2 thổ cư", 100.0),
    ("DT 5x20; tổng 98m2 sàn", 100.0),
    ("DT 5x20; tổng dt 98m2", 98.0),
    ("DT 5x20; tổng diện tích 98,5m2", 98.5),
])
def test_review_nov05_total_land_area_positive_negative_near_miss_controls(text, expected):
    from cleansing.feature_extractor import extract_explicit_land_total
    # This gate recognizes only an explicit LAND total, not every old fallback.
    # Missing title made the original normalization fixture invalid; the new
    # helper's near-miss contract must not test unrelated pre-existing fallbacks.
    assert extract_explicit_land_total(text) == (None if expected == 100.0 else expected)


@pytest.mark.parametrize("title,description,structured,area,price,ppm,ratio", [
    ("BÁN BIỆT THỰ 1.275M²_ HIỆP THÀNH",
     "Diện tích: 20m x 60m tổng 1.275m²_ thổ cư 460m2. Giá 9,4triệu/m.",
     {}, 1275.0, 11.985, 9.4, 0.361),
    ("Diện tích 4.5x 26.5. thổ cư 70m. Tổng",
     "Diện tích 4.5x 26.5. thổ cư 70m. Tổng diện tích sổ hồng  118m2",
     {"price_ty": 2.45}, 118.0, 2.45, 20.763, 0.593),
    ("DT 132m2", "tổng diện tích 132.3m2 , thổ cư 90m2; Giá chủ cần bán giảm còn 1,6tỷ",
     {"area_m2": 132.0, "price_ty": 1.6, "price_per_m2": 12.12}, 132.3, 1.6, 12.094, 0.680),
])
def test_review_nov05_land_total_dependent_values_stay_consistent(title, description, structured, area, price, ppm, ratio):
    record = normalize_record({
        "source": "facebook", "url": "https://example.invalid/land-total-dependent-values",
        "title": title, "description": description, **structured,
    })
    assert record is not None
    assert record["area_m2"] == area
    assert record["price_ty"] == pytest.approx(price)
    assert record["price_per_m2"] == pytest.approx(ppm)
    assert record["tho_cu_ratio"] == pytest.approx(ratio)


@pytest.mark.parametrize("text,expected", [
    ("DT 5x20; tổng diện tích sổ hồng 98m2", 98.0),
    ("DT 5x20; tổng diện tích sàn 240m2", 100.0),
    ("DT 5x20; tổng diện tích xây dựng 80m2", 100.0),
    ("DT 5x20; tổng diện tích sử dụng 240m2", 100.0),
    ("DT 5x20; tổng thổ cư 60m2", 100.0),
    ("DT 5x20; đường bê tông 6m", 100.0),
])
def test_review_nov05_land_total_full_normalization_controls(text, expected):
    record = normalize_record({
        "source": "facebook", "url": "https://example.invalid/land-total-full-controls",
        "title": "Bán đất", "description": text,
    })
    assert record is not None and record["area_m2"] == expected


# 2026-11-06: two distinct source patterns, not duplicate repost evidence.
NOV06_EXPLICIT_ASPHALT_CASES = [
    (86035, "Đất Tân Định gần Trường Thỏ Ngọc. 1/đường Babanxi Cầu Mắm; Đường nhựa 6m", "be_tong"),
    (86343, "Bán đất Chánh Mỹ. Thủ Dầu Một. Đường nhựa xe oto thông", "hem_xe_hoi"),
]


@pytest.mark.parametrize("listing_id,text,before", NOV06_EXPLICIT_ASPHALT_CASES)
def test_review_nov06_explicit_asphalt_beats_weak_access_in_parser(listing_id, text, before):
    from cleansing.feature_extractor import extract_road_type
    assert extract_road_type(text) == "duong_nhua"
    assert parse_facebook_post(text)["road_type"] == "duong_nhua"


@pytest.mark.parametrize("listing_id,text,before", NOV06_EXPLICIT_ASPHALT_CASES)
@pytest.mark.parametrize("placement", ["title", "description", "repeated"])
def test_review_nov06_explicit_asphalt_full_normalization(listing_id, text, before, placement):
    raw = {
        "source": "facebook", "url": "https://example.invalid/asphalt-evidence-control",
        "title": "Bán đất", "description": "", "default_area": "Thủ Dầu Một",
        "price_ty": 2.0, "area_m2": 100.0,
    }
    if placement == "repeated":
        raw.update(title=text, description=text)
    else:
        raw[placement] = text
    record = normalize_record(raw)
    assert record is not None
    assert record["road_type"] == "duong_nhua"
    assert record["area_m2"] == 100.0
    assert record["price_ty"] == 2.0
    assert record["price_per_m2"] == 20.0
    assert record["road_tier"] == 3  # Surface evidence does not promote road tier.
    assert record["ward"] == ("Tân Định" if listing_id == 86035 else "Chánh Mỹ")


@pytest.mark.parametrize("text,expected", [
    ("1/đường Babanxi; đường nhựa 6m", "duong_nhua"),
    ("1/DX072; DUONG NHUA 6M", "duong_nhua"),
    ("Đường nhựa 6m ô tô vào tận đất", "duong_nhua"),
    ("DUONG NHUA XE HOI THONG", "duong_nhua"),
    ("Đường ô tô tới đất; đường nhựa 6m", "duong_nhua"),
    ("Đường bê tông ô tô tới đất", "be_tong"),
    ("1/DX072 đường oto", "be_tong"),
    ("1/đường Babanxi; gần đường nhựa 6m", "be_tong"),
    ("1/đường Babanxi; cách đường nhựa 30m", "be_tong"),
    ("1/đường Babanxi; sát đường nhựa 6m", "be_tong"),
    ("1/đường Babanxi; đường sắp đổ nhựa", "be_tong"),
    ("1/đường Babanxi; mái nhựa", "be_tong"),
    ("Đường ô tô tới đất", "hem_xe_hoi"),
    ("Đường ô tô tới đất; gần đường nhựa 6m", "hem_xe_hoi"),
    ("Đường ô tô tới đất; cách đường nhựa 30m", "hem_xe_hoi"),
    ("Đường ô tô tới đất; sát đường nhựa 6m", "hem_xe_hoi"),
    ("Đường ô tô tới đất; đường sắp đổ nhựa", "hem_xe_hoi"),
    ("Đường ô tô tới đất; mái nhựa", "hem_xe_hoi"),
    ("Hẻm xe hơi; đường nhựa 6m", "hem_xe_hoi"),
    ("Đường nhựa; hẻm ô tô", "hem_xe_hoi"),
    ("Đường nhựa; hẻm xe máy", "hem_xe_may"),
    ("Đường nhựa xe ba gác", "hem_ba_gac"),
    ("Mặt tiền kinh doanh đường nhựa", "mat_tien_kinh_doanh"),
    ("Đường nhựa thông", "duong_nhua"),
    ("Đường đất 4m chuẩn bị lên nhựa", "duong_dat"),
    ("Đường bê tông 6m", "be_tong"),
])
def test_review_nov06_explicit_asphalt_controls(text, expected):
    from cleansing.feature_extractor import extract_road_type
    assert extract_road_type(text) == expected
    record = normalize_record({
        "source": "facebook", "url": "https://example.invalid/asphalt-near-miss-control",
        "title": "Bán đất", "description": text, "price_ty": 2.0, "area_m2": 100.0,
    })
    assert record is not None and record["road_type"] == expected
    assert record["area_m2"] == 100.0 and record["price_ty"] == 2.0


# Synthetic frontage/access-road scope controls; no contact/source identifiers.
@pytest.mark.parametrize("text,expected", [
    ("1/DX072; đường nhựa 6m xe ô tô thông", "duong_nhua"),
    ("ĐƯỜNG NHỰA 6M, Ô TÔ VÀO TẬN ĐẤT", "duong_nhua"),
    ("1/DX072; đường bê tông 4m; đường nhựa lớn bên ngoài", "be_tong"),
    ("Đường bê tông ô tô tới đất; đường nhựa lớn bên ngoài", "be_tong"),
    ("Đường ô tô tới đất; từ đường nhựa đi vào 30m", "hem_xe_hoi"),
    ("Đường ô tô tới đất; ra đường nhựa 30m", "hem_xe_hoi"),
    ("1/DX072; nhánh đường nhựa", "be_tong"),
    ("1/DX072; đường vào gần đường nhựa", "be_tong"),
    ("1/DX072; kế bên đường nhựa", "be_tong"),
    ("Đường ô tô tới đất; sát bên đường nhựa", "hem_xe_hoi"),
    ("1/đường nhựa 6m", "be_tong"),
    ("Đường ô tô tới đất; đường nhựa cách 30m", "hem_xe_hoi"),
    ("1/DX072; dự kiến đường nhựa 6m", "be_tong"),
    ("Đường ô tô tới đất; đường nhựa dự kiến 6m", "hem_xe_hoi"),
    ("1/DX072; đường nhựa; hẻm xe máy", "be_tong"),
    ("1/DX072; đường nhựa; hẻm ô tô", "be_tong"),
    ("1/DX072; đường đất hiện hữu, đường nhựa quy hoạch", "be_tong"),
    ("Đường ô tô tới đất; đường nhựa quy hoạch", "hem_xe_hoi"),
])
def test_review_nov18_asphalt_frontage_scope_controls(text, expected):
    from cleansing.feature_extractor import extract_road_type
    assert extract_road_type(text) == expected
    assert parse_facebook_post(text)["road_type"] == expected
    record = normalize_record({
        "url": "synthetic-asphalt-frontage-control",
        "source": "facebook", "title": "Bán đất", "description": text,
        "price_ty": 2.0, "area_m2": 100.0,
    })
    assert record is not None and record["road_type"] == expected
    assert record["price_ty"] == 2.0 and record["area_m2"] == 100.0


@pytest.mark.parametrize("placement", ["title", "description", "repeated"])
def test_review_nov18_clean_85405_explicit_frontage_replay(placement):
    # Offline differential: historical "ok" review missed this surface/access mix.
    text = "ĐƯỜNG NHỰA 4M. Trước đất nhựa 4m, xe hơi vào tận nơi."
    raw = {
        "source": "facebook", "url": "synthetic-clean-frontage-control",
        "title": "Bán đất", "description": "", "price_ty": 2.0, "area_m2": 100.0,
    }
    if placement == "repeated":
        raw.update(title=text, description=text)
    else:
        raw[placement] = text
    record = normalize_record(raw)
    assert record is not None and record["road_type"] == "duong_nhua"
    assert record["price_ty"] == 2.0 and record["area_m2"] == 100.0
    assert record["price_per_m2"] == 20.0


@pytest.mark.parametrize("text,expected", [
    ("1/DX072; cách mặt tiền đường nhựa 30m", "be_tong"),
    ("Đường ô tô tới đất; gần trục đường nhựa 6m", "hem_xe_hoi"),
    ("Đường ô tô tới đất; đường nhựa lớn cách đất 30m", "hem_xe_hoi"),
])
def test_review_nov18_asphalt_main_road_distance_controls(text, expected):
    from cleansing.feature_extractor import extract_road_type
    assert extract_road_type(text) == expected
    record = normalize_record({
        "source": "facebook", "url": "synthetic-main-road-distance-control",
        "title": "Bán đất", "description": text, "price_ty": 2.0, "area_m2": 100.0,
    })
    assert record is not None and record["road_type"] == expected


# Reviewed 20261120/21: 88811/88661 repeat one CTA pattern, not independent
# evidence. 88737 includes the whole short candidate chain from its offline
# snapshot: rejecting only the first false name exposes the later candidates.
NOV21_NON_NAME_CASES = [
    (88811, "Nhanh tay còn kịp .\nBán nhà 1ty8 tại trung tâm Thành Phố mới Bình Dương"),
    (88661, "Nhanh tay còn kịp .\nBán nhà 1ty8 tại trung tâm Thành Phố mới Bình Dương"),
    (88737, "Bán lỗ luôn nhanh thì còn\nDT 7x13=81 m2 tc fun\n"
     "Đường xe tải vào tận nơi, đèn đường điên nước đầy đủ\n"
     "Giá 1 tỷ 100 triệu (nhanh gọn có bớt)"),
    (88676, "đường đất rộng 8m, đường thông vô kho lúa\n"
     "Gần nhiều công ty, đường sắp lên nhựa."),
    (88442, "Đường đất xe oto 4m cách ngã tư Phú Thứ chỉ hơn 400m.\n"
     "Đất mặt tiền rạch phù hợp làm nhà vườn nghỉ dưỡng."),
]


@pytest.mark.parametrize("listing_id,text", NOV21_NON_NAME_CASES)
def test_review_nov21_descriptions_are_not_road_names(listing_id, text):
    assert extract_road_name(text) is None


@pytest.mark.parametrize("placement", ["title", "description", "repeated"])
@pytest.mark.parametrize("listing_id,text", NOV21_NON_NAME_CASES)
def test_review_nov21_non_name_chain_through_normalization(listing_id, text, placement):
    raw = {
        "source": "facebook", "url": "synthetic-nov21-road-non-name",
        "title": "Bán đất", "description": "", "price_ty": 2.0, "area_m2": 100.0,
    }
    if placement == "repeated":
        raw.update(title=text, description=text)
    else:
        raw[placement] = text
    record = normalize_record(raw)
    assert record is not None and record["road_name"] is None


@pytest.mark.parametrize("text,expected", [
    ("Nhanh tay còn kịp", None),
    ("Bán lỗ nhanh thì còn", None),
    ("Giá 1 tỷ 100 triệu (nhanh gọn có bớt)", None),
    ("Đường xe tải vào tận nơi", None),
    ("Đường sắp lên nhựa", None),
    ("Mặt tiền rạch phù hợp làm nhà vườn", None),
    # Near misses: branch-road labels and real street names must survive.
    ("Nhánh Tây Côn", "Tay Con"),
    ("Nhánh Thi Sách", "Thi Sach"),
    ("Đường Rạch Bùng Binh", "Rach Bung Binh"),
    ("Đường Xe Tải", "Xe Tai"),
    ("Đường Bình Dương", "Binh Duong"),
    ("Nhánh đường Hồng Hà", "Hong Ha"),
    ("Đường Nguyễn Bình đường nhựa", "Nguyen Binh"),
    ("Nhanh tay còn kịp. Mặt tiền đường Hồng Hà", "Hong Ha"),
    ("Đường sắp lên nhựa. Mặt tiền DX072", "DX72"),
    ("Mặt tiền rạch phù hợp làm nhà vườn. Đường Hồng Hà", "Hong Ha"),
    ("Đường Hồng Hà. Nhanh gọn có bớt", "Hong Ha"),
])
def test_review_nov21_non_name_boundaries_preserve_named_roads(text, expected):
    assert extract_road_name(text) == expected


# 20261122 non-asking-price batch: duplicate 89043/88874 is one pattern.
NON_ASKING_NOV22_CASES = [
    (89043, "Rồi lô 750 triệu đã bay màu\n còn lại 850 triệu . Chỉ cần sẵn 250 triệu mua được", 0.85),
    (88874, "Rồi lô 750 triệu đã bay màu\n còn lại 850 triệu . Chỉ cần sẵn 250 triệu mua được", 0.85),
    (89023, "Mua 2ty bán 950tr để sửa lý công việc\nBạn nhờ bán lô đất bằng giá đang vay gan hàng", 0.95),
    (88737, "Chủ vừa mua 1.2 tỉ cần mua lô lớn hơn\nGiá 1 tỷ 100 triệu (nhanh gọn có bớt)", 1.1),
]


@pytest.mark.parametrize("listing_id,text,expected", NON_ASKING_NOV22_CASES)
def test_nov22_non_asking_amounts_before_current_price(listing_id, text, expected):
    from cleansing.feature_extractor import extract_price
    assert extract_price(text) == expected


@pytest.mark.parametrize("listing_id,text,expected", NON_ASKING_NOV22_CASES)
def test_nov22_non_asking_amounts_through_facebook_title(listing_id, text, expected):
    # Facebook's visible title may duplicate the full post or end at first line.
    assert parse_facebook_post(text)["price_total"] == expected


@pytest.mark.parametrize("listing_id,text,expected", NON_ASKING_NOV22_CASES)
def test_nov22_non_asking_amounts_through_normalization(listing_id, text, expected):
    title = text.split("\n", 1)[0]
    record = normalize_record({
        "source": "facebook", "url": "https://example.invalid/non-asking-price",
        "title": title, "description": text,
    })
    assert record is not None and record["price_ty"] == expected


@pytest.mark.parametrize("text,expected", [
    ("Chủ đã mua 2 tỷ, nay bán 950 triệu", 0.95),
    ("Chu vua mua 1.2 ty\nGia 1 ty 100 trieu", 1.1),
    ("MUA 2TỶ BÁN 950TR", 0.95),
    ("Mua 2 tỷ 500 triệu bán 950 triệu", 0.95),
    ("Mua 850 triệu bán 950 triệu", 0.95),
    ("Lo 750 trieu da bay mau\ncon lai 850 trieu", 0.85),
    ("Lô 750 triệu đã bán, lô còn lại giá 850 triệu", 0.85),
    ("Nền 750 triệu bán rồi; còn lại 850 triệu", 0.85),
    ("Căn 2 tỷ 500 triệu đã bán; căn còn lại 950 triệu", 0.95),
    ("Lô 750 triệu đã bán", None),
    ("Chủ vừa mua 1.2 tỷ", None),
    ("Mua 2 tỷ bán 950 triệu; trả trước 250 triệu", 0.95),
])
def test_nov22_explicit_historical_and_sold_price_variants(text, expected):
    from cleansing.feature_extractor import extract_price
    assert extract_price(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("Lô 750 triệu đang bán, còn lại 850 triệu", 0.75),
    ("Lô 750 triệu chưa bán; còn lại 850 triệu", 0.75),
    ("Lô 750 triệu bán nhanh", 0.75),
    ("Mua 2 tỷ", 2.0),
    ("Cần mua 2 tỷ, bán kính 950m", 2.0),
    ("Mua 2 tỷ, bán hàng thuận tiện", 2.0),
    ("Giá 2 tỷ; chủ vừa mua xe 950 triệu", 2.0),
    ("Giá 750 triệu, lô bên cạnh đã bán 850 triệu", 0.75),
    ("Giá 750 triệu, đã bán nhiều lô", 0.75),
    ("Giá 7 tỷ 2", 7.2),
    ("Giá 1 tỷ 100 triệu", 1.1),
    ("Giá 850 triệu, trả trước 250 triệu", 0.85),
    ("Giảm còn 1 tỷ 100 triệu", 1.1),
    ("Lô 750 triệu sắp bay màu", 0.75),
])
def test_nov22_non_asking_price_near_misses_keep_current_offer(text, expected):
    from cleansing.feature_extractor import extract_price
    assert extract_price(text) == expected


# Two independent reviewed road-name patterns, not repost evidence.
ROAD_NOV23_CASES = [
    (89167, "từ 3ty6 giảm còn 2ty8 nhanh mới còn ạ\nNgộp Bank - Rẻ Nhất Khu\n"
     "Bán Đất Tặng Nhà C4 Mặt Tiền Phan Bội Châu P Thủ Dầu Một Tp HCM", "Phan Boi Chau"),
    (88781, "Bán Đất 150m2 có sẵn 150 m2 thổ cư giá 2.9 tỷ tại Đường DC 82 "
     "Phường Phú Tân Thành phố Thủ Dầu Một Bình Dương", "DC82"),
]


@pytest.mark.parametrize("listing_id,text,expected", ROAD_NOV23_CASES)
def test_nov23_reviewed_street_not_sale_cta_or_missing_code(listing_id, text, expected):
    assert extract_road_name(text) == expected


@pytest.mark.parametrize("listing_id,text,expected", ROAD_NOV23_CASES)
def test_nov23_reviewed_street_through_full_normalization(listing_id, text, expected):
    record = normalize_record({
        "source": "facebook", "url": "https://example.invalid/road-nov23",
        "title": text.split("\n", 1)[0], "description": text,
    })
    assert record is not None and record["road_name"] == expected


@pytest.mark.parametrize("text,expected", [
    ("nhanh mới còn ạ", None),
    ("nhanh moi con a\nMặt tiền Phan Bội Châu", "Phan Boi Chau"),
    ("NHANH MỚI CÒN Ạ\nĐường Lê Hồng Phong", "Le Hong Phong"),
    ("Nhanh mới còn ạ\nGần đường Phan Bội Châu", None),
    ("Nhánh Hồng Hà", "Hong Ha"),
    ("Nhánh Mới Phú Lợi", "Moi Phu Loi"),
    ("Đường Mới Phú Lợi", "Moi Phu Loi"),
    ("Mặt tiền Phan Bội Châu P Thủ Dầu Một Tp HCM", "Phan Boi Chau"),
    ("Nhánh Phan Bội Châu", "Phan Boi Chau"),
])
def test_nov23_sale_cta_boundary_preserves_real_branch_names(text, expected):
    assert extract_road_name(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("Đường DC82", "DC82"),
    ("Mặt tiền DC 82", "DC82"),
    ("MT đường dc-0082", "DC82"),
    ("Nhánh DC 82", "DC82"),
    ("Gần đường DC82", None),
    ("Cách DC 82 50m", None),
    ("Đường thông từ DC82 xuống ĐH609", None),
    ("DC82: 400m", None),
    ("DC82", None),
    ("Lô DC82 diện tích 150m2", None),
    ("DC 82m2", None),
    ("Mặt tiền DC82abc", None),
    ("Đường DC 82m2", None),
    ("Đường Hồng Hà; gần DC82", "Hong Ha"),
    ("Mặt tiền D12; gần đường DC82", "D12"),
    ("Đường ĐT7A", "DT7A"),
    ("Nhánh DH609", "DH609"),
])
def test_nov23_dc_code_requires_road_label_not_proximity_or_lot_code(text, expected):
    assert extract_road_name(text) == expected


# 20261122-150048:89070:price_ty; #88625 is the same repost pattern,
# not independent evidence. The source title is a prefix cut at #7tỷ.
NOV24_PRICE_DESCRIPTION = (
    "600m2 đất trung tâm Hiệp Thành ( Phú Lợi , Tp HCM mới ) "
    "đường nhựa 6m thông luôn mà giá chỉ có  #7tỷ2 . Chỉ có #7tỷ2 thôi\n"
    "Tính ra chỉ #12tr/m2"
)
NOV24_PRICE_TITLE = NOV24_PRICE_DESCRIPTION.split("2 . Chỉ có", 1)[0]


def test_nov24_reviewed_89070_truncated_title_preserves_complete_price():
    from cleansing.feature_extractor import extract_all

    assert NOV24_PRICE_TITLE.endswith("#7tỷ")
    assert extract_all(NOV24_PRICE_TITLE, NOV24_PRICE_DESCRIPTION)["price_total"] == 7.2


def test_nov24_reviewed_89070_full_normalization_repairs_dependent_unit_price():
    record = normalize_record({
        "source": "facebook", "url": "https://example.invalid/nov24-price",
        "title": NOV24_PRICE_TITLE, "description": NOV24_PRICE_DESCRIPTION,
    })
    assert record is not None
    assert record["price_ty"] == 7.2
    assert record["area_m2"] == 600
    assert record["price_per_m2"] == 12


@pytest.mark.parametrize("title,description,expected", [
    ("Đất giá #7tỷ", "Đất giá #7tỷ2 . Chỉ có #7tỷ2 thôi", 7.2),
    ("DAT GIA #7TY", "DAT GIA #7TY2 . CHI CO #7TY2 THOI", 7.2),
    ("Đất giá 7tỉ", "Đất giá 7tỉ2 chốt", 7.2),
    ("Đất giá 7ty", "Đất giá 7ty25 chốt", 7.25),
    ("Đất giá 7ty", "Đất giá 7ty250tr chốt", 7.25),
    ("Đất giá 7 tỷ", "Đất giá 7 tỷ05 chốt", 7.05),
    ("Đất giá 7 tỷ", "Đất giá 7 tỷ0 chốt", 7.0),
    ("  Đất giá #7tỷ  ", " Đất giá #7tỷ2 chốt", 7.2),
    # Different surrounding content or a distinct amount is not truncation.
    ("Đất giá 7 tỷ", "Giá 7 tỷ 2", 7.0),
    ("Đất giá 7 tỷ", "Đất giá 7 tỷ. Nay giá 7 tỷ 2", 7.0),
    ("Đất giá 7 tỷ", "Đất giá 7 tỷ 2 phòng ngủ. Giá 7 tỷ 2", 7.0),
    ("Đất giá 7 tỷ", "Đất giá 7 tỷ2m2. Giá 7 tỷ 2", 7.0),
    ("Đất giá 7 tỷ", "Đất giá 7 tỷ2 m2. Giá 7 tỷ 2", 7.0),
    ("Đất giá 7 tỷ", "Đất giá 7 tỷ2xx", 7.0),
    ("Đất giá 7 tỷ", "Đất giá 7 tỷ2abc. Giá 7 tỷ 2", 7.0),
    ("Đất giá 7 tỷ", "Đất giá 7 tỷ2500 chốt", 7.0),
    ("Đất giá 7 tỷ", "Đất giá 7 tỷ. Chỉ có 8 tỷ", 7.0),
    ("Đất giá 7 tỷ", "Đất giá 7 tỷ. Chỉ có 9 tỷ", 7.0),
    ("Đất giá 7 tỷ", "Giá 9 tỷ", 9.0),
    ("Đất giá 7 tỷ", "Đất giá 7 tỷ", 7.0),
    ("Đất giá 7.2 tỷ", "Đất giá 7.2 tỷ5 chốt", 7.2),
    ("Đất giá 7 tỷ", "", 7.0),
    ("", "Đất giá 7 tỷ 2", 7.2),
])
def test_nov24_compact_price_continuation_requires_exact_prefix(title, description, expected):
    from cleansing.feature_extractor import extract_all

    assert extract_all(title, description)["price_total"] == expected


def test_nov24_complete_price_does_not_override_explicit_source_badge():
    from cleansing.feature_extractor import extract_all

    assert extract_all(
        NOV24_PRICE_TITLE, NOV24_PRICE_DESCRIPTION, source_price_str="7 tỷ",
    )["price_total"] == 7.0
