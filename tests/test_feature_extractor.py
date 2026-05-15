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
    classify_property_type,
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


def test_extract_legal():
    r = extract_legal("đã có SHR chính chủ")
    assert r["has_so"] is True
    assert r["has_shr"] is True

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
