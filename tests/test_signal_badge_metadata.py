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
