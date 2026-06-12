from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_signal_badge_metadata_formats_optional_property_badges():
    from services.market_data import signal_badge_metadata

    meta = signal_badge_metadata({
        "title": "Bán nhà mặt tiền Hồ Văn Cống, Phú Lợi",
        "description": "DT ngang 9m tc80m tổng 215m2, đường nhựa 5m thông.",
        "property_type": "nha_dat",
        "area_m2": 215,
        "road_tier": 2,
        "road_type": "duong_nhua",
        "road_width_m": None,
        "tho_cu_m2": None,
        "tho_cu_ratio": None,
    })

    assert meta["property_type_label"] == "Nhà đất"
    assert meta["tho_cu_m2"] == 80.0
    assert meta["tho_cu_label"] == "TC 80 m²"
    assert meta["road_width_m"] == 5.0
    assert meta["road_label"] == "Đường nhựa 5m"
    assert meta["street_label"] == "Mặt tiền Hồ Văn Cống"


def test_signal_badge_metadata_formats_dx_branch_and_hides_missing_optionals():
    from services.market_data import signal_badge_metadata

    branch = signal_badge_metadata({
        "title": "Đất nhánh DX127 phường Phú Hòa",
        "description": "Hẻm ô tô 4m, sổ sẵn.",
        "property_type": "dat_nen",
        "area_m2": 96,
        "road_tier": 3,
        "road_type": "hem_xe_hoi",
    })
    sparse = signal_badge_metadata({
        "title": "Bán đất Chánh Nghĩa",
        "description": "",
        "area_m2": 90,
        "road_tier": 3,
        "property_type": None,
    })

    assert branch["property_type_label"] == "Đất nền"
    assert branch["road_label"] == "Hẻm xe hơi 4m"
    assert branch["street_label"] == "Nhánh DX127"
    assert branch["tho_cu_m2"] is None
    assert branch["tho_cu_label"] is None

    assert sparse["property_type_label"] is None
    assert sparse["street_label"] is None
    assert sparse["tho_cu_m2"] is None
    assert sparse["road_label"] == "Hẻm xe hơi"


def test_signal_badge_metadata_prefers_stored_road_name_over_nearby_arterial():
    from services.market_data import signal_badge_metadata

    meta = signal_badge_metadata({
        "title": "Dat dinh hoa DX73 sat duong My Phuoc Tan Van",
        "description": "Duong nhua thong, phuong Chanh Hiep. Dt 5x28 TC 75m.",
        "property_type": "dat_nen",
        "area_m2": 140,
        "road_name": "DX73",
        "road_tier": 2,
        "road_type": "duong_nhua",
        "tho_cu_m2": 75,
    })

    assert meta["street_label"] == "\u0110\u01b0\u1eddng DX73"


def test_signal_badge_metadata_does_not_treat_tho_cu_or_distance_as_road_code():
    from services.market_data import signal_badge_metadata

    tc_only = signal_badge_metadata({
        "title": "Bán đất 6.5x19 tc80m",
        "description": "Hẻm xe hơi, thổ cư 80m2.",
        "area_m2": 103,
        "road_tier": 3,
        "property_type": "dat_nen",
    })
    distance = signal_badge_metadata({
        "title": "Đất nhánh Nguyễn Chí Thanh",
        "description": "Đường nhựa ô tô 1 xẹt Nguyễn Chí Thanh vào 50m, hẻm xe hơi.",
        "area_m2": 120,
        "road_tier": 3,
        "property_type": "dat_nen",
    })

    assert tc_only["street_label"] is None
    assert tc_only["road_label"] == "Hẻm xe hơi"
    assert tc_only["tho_cu_label"] == "TC 80 m²"

    assert distance["street_label"] == "Nhánh Nguyễn Chí Thanh"
    assert distance["road_width_m"] is None
    assert distance["road_label"] == "Hẻm xe hơi"


def test_signal_badge_metadata_corrects_legacy_full_tho_cu_percent():
    from services.market_data import signal_badge_metadata

    meta = signal_badge_metadata({
        "title": "B\u00e1n nh\u00e0 KDC Hi\u1ec7p Th\u00e0nh",
        "description": "DT 5x15 = 75m2, Th\u1ed5 c\u01b0 100%, nh\u00e0 2PN.",
        "property_type": "nha_dat",
        "area_m2": 75,
        "road_tier": 3,
        "tho_cu_m2": 100,
        "tho_cu_ratio": 1.333,
    })

    assert meta["tho_cu_m2"] == 75.0
    assert meta["tho_cu_ratio"] == 1.0
    assert meta["tho_cu_label"] == "TC 75 m²"


def test_signal_badge_metadata_prefers_label_value_over_legacy_title_area_value():
    from services.market_data import signal_badge_metadata

    meta = signal_badge_metadata({
        "title": "B\u00e1n Nh\u00e0 ri\u00eang 108m\u00b2 th\u1ed5 c\u01b0 60m\u00b2 gi\u00e1 3.6 t\u1ef7",
        "description": "Nh\u00e0 3 t\u1ea5m li\u1ec1n k\u1ec1, s\u1ed5 h\u1ed3ng ri\u00eang.",
        "property_type": "nha_dat",
        "area_m2": 80,
        "road_tier": 3,
        "tho_cu_m2": 108,
        "tho_cu_ratio": 1.35,
    })

    assert meta["tho_cu_m2"] == 60.0
    assert meta["tho_cu_ratio"] == 0.75
    assert meta["tho_cu_label"] == "TC 60 m²"


def test_signal_badge_metadata_prefers_complete_unit_match_over_truncated_legacy_value():
    from services.market_data import signal_badge_metadata

    meta = signal_badge_metadata({
        "title": "Di\u1ec7n t\u00edch 72m2 th\u1ed5 c\u01b0 6",
        "description": "Di\u1ec7n t\u00edch 72m2 th\u1ed5 c\u01b0 60m2, nh\u00e0 1 tr\u1ec7t 1 l\u1eedng.",
        "property_type": "nha_dat",
        "area_m2": 72,
        "road_tier": 3,
        "tho_cu_m2": 6,
        "tho_cu_ratio": 0.083,
    })

    assert meta["tho_cu_m2"] == 60.0
    assert meta["tho_cu_ratio"] == 0.833
    assert meta["tho_cu_label"] == "TC 60 m²"


def test_signal_badge_metadata_uses_strict_tho_cu_parser_for_compact_tc():
    from services.market_data import signal_badge_metadata

    full_tc = signal_badge_metadata({
        "title": "T\u00e2n \u0110\u1ecbnh dt. 10 x 24tc fun \u0111\u01b0\u1eddng b\u00ea t\u00f4ng",
        "description": "Ch\u1ee7 b\u00e1n nhanh 2ty200.",
        "property_type": "dat_nen",
        "area_m2": 240,
        "road_tier": 3,
        "tho_cu_m2": None,
        "tho_cu_ratio": None,
    })
    compact_value = signal_badge_metadata({
        "title": "T\u00e2n \u0110\u1ecbnh dt 5x37tc.75m gi\u00e1 1ty390",
        "description": "",
        "property_type": "dat_nen",
        "area_m2": 185,
        "road_tier": 3,
        "tho_cu_m2": None,
        "tho_cu_ratio": None,
    })

    assert full_tc["tho_cu_m2"] == 240.0
    assert full_tc["tho_cu_ratio"] == 1.0
    assert full_tc["tho_cu_label"] == "TC 240 m²"
    assert compact_value["tho_cu_m2"] == 75.0
    assert compact_value["tho_cu_ratio"] == 0.405
    assert compact_value["tho_cu_label"] == "TC 75 m²"
