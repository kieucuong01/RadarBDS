"""
Smoke tests — feature_extractor (critical path).
Chạy: python -m pytest tests/ -v
Hoặc:  python tests/test_feature_extractor.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cleansing.feature_extractor import (
    extract_price, extract_area, extract_dimensions,
    extract_tho_cu, extract_road_tier, extract_legal,
    classify_property_type, extract_road_type,
)
from cleansing.normalizer import normalize_record


def test_extract_price():
    # Tỷ cases
    assert extract_price("12,5 tỷ") == 12.5
    assert extract_price("1.69 tỷ") == 1.69
    assert extract_price("1,69 tỷ") == 1.69
    assert extract_price("3 tỷ") == 3.0
    # Tỷ + lẻ
    assert extract_price("1 tỷ 2") == 1.2
    assert extract_price("2 tỷ 550") == 2.55
    assert extract_price("2t45") == 2.45
    assert extract_price("2t450") == 2.45
    assert extract_price("2t450tr") == 2.45
    assert extract_price("nhà 2 tầng") is None
    # Triệu
    assert extract_price("880 triệu") == 0.88
    assert extract_price("1.500 triệu") == 1.5
    # Edge cases
    assert extract_price("80 triệu") is None        # < 100 triệu: reject
    assert extract_price("giá thỏa thuận") is None
    assert extract_price("") is None


def test_extract_area():
    assert extract_area("1.826 m²") == 1826.0
    assert extract_area("110m2") == 110.0
    assert extract_area("DT: 5x18 = 90m²") == 90.0
    assert extract_area("2.546,3 m²") == 2546.3
    # Kích thước → diện tích
    assert extract_area("4x20m") == 80.0
    # Loại thổ cư khỏi area parse
    assert extract_area("DT 500m², thổ cư 100m²") == 500.0


def test_extract_dimensions():
    d = extract_dimensions("ngang 22.5m sâu 82m")
    assert d["frontage_m"] == 22.5
    assert d["depth_m"] == 82.0

    d = extract_dimensions("4x34")
    assert d["frontage_m"] == 4.0
    assert d["depth_m"] == 34.0


def test_extract_tho_cu():
    r = extract_tho_cu("300m² thổ cư", 500)
    assert r["tho_cu_m2"] == 300
    assert abs(r["tho_cu_ratio"] - 0.6) < 0.01

    r = extract_tho_cu("full thổ cư", 100)
    assert r["tho_cu_ratio"] == 1.0


def test_extract_road_tier():
    # Tier 1 — đường tên trong whitelist + MT
    assert extract_road_tier("Mặt tiền đường Lê Chí Dân") == 1
    # Tier 2 — DX
    assert extract_road_tier("Đường DX117 Tân An") == 2
    # Tier 2 — nhựa không hẻm
    assert extract_road_tier("Đường nhựa rộng 6m") == 2
    # Tier 3 — hẻm ≥5m
    assert extract_road_tier("Hẻm bê tông 6m", "") == 3
    # Tier 3 — hẻm 3-5m can fit a car.
    assert extract_road_tier("hẻm 4m", "") == 3
    # Tier 4 — hẻm <3m is motorbike-only.
    assert extract_road_tier("hẻm 2m", "") == 4
    # Tier 0 — unknown
    assert extract_road_tier("đất đẹp giá tốt", "") == 0


def test_extract_road_tier_new_patterns():
    # Mặt tiền đơn độc (không có tên đường whitelist) → Tier 2
    assert extract_road_tier("Bán đất mặt tiền 72m² Phường Phú An") == 2
    # Đường xe tải / xe hơi → Tier 3
    assert extract_road_tier("Bán đất 130m², đường xe tải, gần chợ") == 3
    assert extract_road_tier("Đường xe hơi vào tận nhà") == 3
    # Biến thể "ôtô" liền, "oto" không dấu → Tier 3
    assert extract_road_tier("Hẻm ôtô thông 5m") == 3
    assert extract_road_tier("Oto vào đến cửa") == 3
    # MTKD / kinh doanh → Tier 2
    assert extract_road_tier("Bán nhà MTKD Phường Phú An") == 2
    assert extract_road_tier("Mặt tiền kinh doanh sầm uất") == 2
    # Đê bao sông → Tier 2
    assert extract_road_tier("Đất mặt tiền đê bao sông Sài Gòn") == 2
    # Lộ giới 8m → Tier 2
    assert extract_road_tier("Lộ giới 8m phường Tân An") == 2
    # "ngang Xm" = chiều rộng lô đất KHÔNG phải đường → không nâng tier
    assert extract_road_tier("Đất 4482m² ngang 78m giá 9 tỷ") == 0


def test_extract_road_tier_data_quality_patterns():
    # "sân xe hơi" alone is parking/yard, not road access.
    assert extract_road_tier("Nhà có sân xe hơi rộng, gần chợ") == 0
    # But a separate road-auto signal in the same listing must still count.
    assert extract_road_tier("Nhà có sân xe hơi", "Đường xe hơi, dân đông kín") == 3
    assert extract_road_tier("Bán đất đường oto thổ cư 100%") == 3
    # Small access signals.
    assert extract_road_tier("Bán đất đường ba gác Tân An") == 4
    assert extract_road_tier("Hẻm xe máy sát chợ") == 4
    # Broker typo: "đường 4m2" means road width 4m in this context.
    assert extract_road_tier("Rẻ nhất Tân An, đường 4m2 hiện sổ") == 3
    # Through-road with no width/type is usable evidence but not a main road.
    assert extract_road_tier("Nhà đẹp", "Đường thông tứ hướng, khu dân cư đông") == 3
    # Mỹ Phước grid street codes in description should be picked up, not only title.
    assert extract_road_tier("Bán nhà Mỹ Phước 3", "đường DJ6 gần trường") == 2
    assert extract_road_tier("Bán nhà Mỹ Phước 1", "đường TC 1A") == 2


def test_extract_road_type_small_access_patterns():
    assert extract_road_type("Ban dat duong ba gac Tan An") == "hem_ba_gac"
    assert extract_road_type("Hem xe may sat cho") == "hem_xe_may"
    assert extract_road_type("Duong oto vao tan dat") == "hem_xe_hoi"


def test_normalizer_uses_structured_address_for_road_tier():
    rec = normalize_record({
        "source": "guland",
        "external_id": "addr-road-tier",
        "url": "https://guland.vn/post/addr-road-tier",
        "title": "Bán đất 100m² Phường Phú Tân",
        "description": "",
        "address": "Đường DB6, Phường Phú Tân, Thủ Dầu Một, Bình Dương",
        "ward": "Phú Tân",
        "area_m2": 100,
        "price_ty": 2.0,
    })
    assert rec is not None
    assert rec["road_tier"] == 2


def test_normalizer_prefers_text_ward_over_legacy_phu_an_raw():
    rec = normalize_record({
        "source": "guland",
        "external_id": "legacy-phu-an-raw",
        "url": "https://guland.vn/post/nha-phu-an-legacy",
        "title": "Cần bán nhà phường Hiệp An - TDM",
        "description": "Cần bán căn nhà tại phường Hiệp An, Thủ Dầu Một Bình Dương.",
        "address": "Phú An, Thủ Dầu Một, Bình Dương",
        "ward": "Phú An",
        "area_m2": 57.1,
        "price_ty": 1.45,
    })
    assert rec is not None
    assert rec["ward"] == "Hiệp An"


def test_normalizer_prefers_explicit_title_area_when_source_area_conflicts():
    rec = normalize_record({
        "source": "guland",
        "external_id": "bad-source-area",
        "url": "https://guland.vn/post/bad-source-area",
        "title": "Bán đất 225m² 2.65 tỷ tại Phường Phú Mỹ Thành phố Thủ Dầu Một",
        "description": "Mặt tiền dx 057 phú mỹ 2 lô liền kề 4,5x25 60 mtc",
        "address": "Phường Phú Mỹ, Thủ Dầu Một",
        "ward": "Phú Mỹ",
        "area_m2": 739.0,
        "price_ty": 2.65,
    })
    assert rec is not None
    assert rec["area_m2"] == 225.0
    assert round(rec["price_per_m2"], 2) == 11.78


def test_normalizer_maps_ben_cat_khu_l_grid_codes_to_my_phuoc_3():
    rec = normalize_record({
        "source": "facebook",
        "external_id": "wrong-ward-khu-l",
        "url": "https://www.facebook.com/khuyen.vu.86/posts/khu-l",
        "default_area": "Bến Cát",
        "title": "Bán nhanh 5m khu L sát góc DL12 hướng bắc",
        "description": "DT 5*30 thổ cư 150m. Sát chợ, sát trường cấp 2, sát QL13. Giá 1 tỷ 6x",
        "area_m2": 150,
        "price_ty": 1.6,
    })

    assert rec is not None
    assert rec["ward"] == "Mỹ Phước 3"
    assert rec["area"] == "Mỹ Phước 3"


def test_normalizer_maps_viet_duc_landmark_to_thoi_hoa():
    rec = normalize_record({
        "source": "facebook",
        "external_id": "wrong-ward-vgu",
        "url": "https://www.facebook.com/khuyen.vu.86/posts/vgu",
        "default_area": "Bến Cát",
        "title": "Nhà gác lửng ngay khu đại học Việt Đức",
        "description": "DT 5x30, sân xe hơi, 5 phòng ngủ, giá chỉ 1 tỷ 9xx",
        "area_m2": 150,
        "price_ty": 1.9,
    })

    assert rec is not None
    assert rec["ward"] == "Thới Hòa"
    assert rec["area"] == "Thới Hòa"


def test_normalizer_does_not_fallback_ben_cat_profile_to_tan_an():
    rec = normalize_record({
        "source": "facebook",
        "external_id": "wrong-ward-generic-ben-cat",
        "url": "https://www.facebook.com/khuyen.vu.86/posts/generic-ben-cat",
        "default_area": "Bến Cát",
        "title": "Bến Cát TPHCM tổng diện tích 1102m2 có 200 thổ cư",
        "description": "Giá 3 tỷ 6 thương lượng, liên hệ xem đất",
        "area_m2": 1102,
        "price_ty": 3.6,
    })

    assert rec is not None
    assert rec["ward"] is None
    assert rec["area"] == "Bến Cát"


def test_normalizer_marks_long_nguyen_as_outside_focus_area():
    rec = normalize_record({
        "source": "facebook",
        "external_id": "wrong-ward-long-nguyen",
        "url": "https://www.facebook.com/khuyen.vu.86/posts/long-nguyen",
        "default_area": "Bến Cát",
        "title": "Phường Long Nguyên TPHCM, đất 20x37 có thổ cư",
        "description": "Chủ kẹt tiền bán rẻ lô đất, giá 3 tỷ 2",
        "area_m2": 740,
        "price_ty": 3.2,
    })

    assert rec is not None
    assert rec["ward"] is None
    assert rec["area"] == "Other"


def test_normalizer_keeps_unknown_location_out_of_known_ward_segments():
    rec = normalize_record({
        "source": "facebook",
        "external_id": "unknown-location",
        "url": "https://www.facebook.com/hang.pk.90/posts/unknown-location",
        "title": "Mặt tiền Đại lộ Bình Dương giảm giá bán nhanh",
        "description": "DT 5x30 thổ cư 150m, giá 2 tỷ 5",
        "area_m2": 150,
        "price_ty": 2.5,
    })

    assert rec is not None
    assert rec["ward"] is None
    assert rec["area"] == "Unknown"


def test_extract_legal():
    r = extract_legal("đã có SHR chính chủ")
    assert r["has_so"] is True
    assert r["has_shr"] is True

    r = extract_legal("dat giay tay vi bang")
    assert r["no_so"] is True
    assert r["has_so"] is False

    r = extract_legal("dat dang lam so")
    assert r["no_so"] is True
    assert r["has_so"] is False

    r = extract_legal("đất chưa có sổ")
    assert r["no_so"] is True

    r = extract_legal("sổ hồng riêng từng lô")
    assert r["has_so"] is True


def test_classify_property_type():
    # Hard vườn
    assert classify_property_type("Đất vườn Tân An", "cây ăn trái", 2000) == "dat_vuon"
    # Hard nhà
    assert classify_property_type("Bán nhà 3 tầng", "nhà 3 tầng có sân thượng") == "nha_dat"
    # Area >=500m² no nhà → vườn
    assert classify_property_type("Đất Tân An giá tốt", "đất đẹp", 800) == "dat_vuon"
    # Default dat_nen
    assert classify_property_type("Đất nền Tân An", "đất phân lô kdc", 100) == "dat_nen"
    # Broker service boilerplate is not proof of an existing house on the lot.
    assert classify_property_type(
        "Bán đất 95m² 1.75 tỷ tại Phường Tân An Thành phố Thủ Dầu Một",
        "Hotline: 0986694438. Ký Gửi - Mua Bán: Bất Động Sản. Xây Dựng Nhà Ở Trọn Gói.",
        95,
        price_per_m2=18.42,
    ) == "dat_nen"
    # "Phù hợp xây/phòng trọ đầu tư" is potential use, not an existing rental block.
    assert classify_property_type(
        "Lô đất đẹp - phù hợp xây nhà vườn, phòng trọ đầu tư",
        "Diện tích 6,5 x 50 = 315m², thổ cư 90m², xung quanh toàn nhà lầu",
        315,
        tho_cu_m2=90,
        price_per_m2=8.73,
    ) == "dat_nen"
    assert classify_property_type(
        "Đất đẹp thổ cư 5x25m sát mặt tiền Nguyễn Chí Thanh",
        "Vị trí đẹp, phù hợp để xây nhà ở, đầu tư, hoặc kinh doanh.",
        125,
        tho_cu_m2=82,
        price_per_m2=16.0,
    ) == "dat_nen"
    # Actual rental assets should still be classified as nha_tro.
    assert classify_property_type("Bán dãy trọ đang cho thuê", "12 phòng trọ, thu nhập ổn định") == "nha_tro"
    # Nhà ở xã hội / NOXH Becamex là thị trường căn hộ đặc thù, không phải nhà đất.
    assert classify_property_type(
        "Bán nhà ở xã hội Becamex Định Hòa block A",
        "Căn 30m2, sổ hồng riêng, giá tốt",
        30,
        price_per_m2=25.0,
        url_hint="nha",
    ) == "nha_o_xa_hoi"
    assert classify_property_type(
        "Cần bán NOXH Becamex Định Hòa",
        "Nhà xã hội Becamex gần KCN, căn hộ tầng 5",
        30,
        price_per_m2=22.0,
    ) == "nha_o_xa_hoi"
    assert classify_property_type(
        "Becamex Định Hòa, lầu 3, sổ hồng 465 triệu",
        "Thuê được 2 triệu/tháng, toàn quốc mua được",
        38,
        price_per_m2=12.2,
    ) == "nha_o_xa_hoi"
    # Landmark gần nhà xã hội vẫn có thể là đất, không được gom nhầm.
    assert classify_property_type(
        "Bán đất gần nhà ở xã hội Becamex Định Hòa",
        "Lô đất thổ cư 5x20 đường nhựa",
        100,
        price_per_m2=18.0,
    ) == "dat_nen"
    assert classify_property_type(
        "Bán lô đất góc 2 mặt tiền kế bên tòa nhà Becamex",
        "Đất thổ cư, xây biệt thự được",
        214,
        price_per_m2=90.0,
    ) == "dat_nen"


if __name__ == "__main__":
    # Chạy tay khi không có pytest
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS {t.__name__}")
        except AssertionError as e:
            print(f"  FAIL {t.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"  ERROR {t.__name__}: {e}")
            failed += 1
    print(f"\n{'OK' if failed == 0 else 'FAILED'}: {len(tests)-failed}/{len(tests)} passed")
    sys.exit(0 if failed == 0 else 1)
