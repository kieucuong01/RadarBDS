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
