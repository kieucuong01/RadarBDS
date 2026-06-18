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
    classify_property_type, extract_road_type, is_multi_lot_listing,
    extract_price_per_m2, parse_facebook_post,
)
from cleansing.normalizer import normalize_record, match_ward, extract_road_name
from services.market_data import _format_price_label


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
    assert extract_price("Giá 2t tỷ 7") == 2.7
    assert extract_price("giá tốt 2.600") == 2.6
    assert extract_price("nhà 2 tầng") is None
    # Triệu
    assert extract_price("880 triệu") == 0.88
    assert extract_price("1.500 triệu") == 1.5
    # Edge cases
    assert extract_price("80 triệu") is None        # < 100 triệu: reject
    assert extract_price("giá thỏa thuận") is None
    assert extract_price("") is None
    assert extract_price("Gia 12,x ty") is None
    assert extract_price("Gia con : 4\U0001d42d\u1ef7390\U0001d42d\U0001d42b") == 4.39
    assert extract_price("B\u00e1n nhanh gi\u1ea3m gi\u00e1: 200 tri\u1ec7u trong tu\u1ea7n nh\u00e0") is None
    assert extract_price("*** Gi\u00e1: 2 t\u1ef7 6; C\u00f3 h\u1ed7 tr\u1ee3 Ng\u00e2n h\u00e0ng.") == 2.6
    assert extract_price("Rẻ hơn thị trường 100 triệu, lô đất DL12 Mỹ Phước 3") is None
    assert extract_price("Chủ thở oxy giảm sâu 150 triệu rồi quý vị mua dùm") is None
    assert extract_price("Đưa trước 500 triệu còn lại ngân hàng hỗ trợ trả góp") is None
    assert extract_price("Giá LH 0967 936 939, rẻ hơn thị trường 100 triệu") is None


def test_extract_price_handles_real_unicode_ty_patterns():
    assert extract_price("Gi\u00e1 b\u00e1n nhanh: 3,2 t\u1ef7") == 3.2
    assert extract_price("Gi\u00e1 2 t\u1ef7 550") == 2.55
    assert extract_price("B\u00e1n \u0111\u1ea5t 3 t\u1ef7") == 3.0
    assert extract_price("Nh\u00e0 ng\u1ed9p gi\u00e1 2ty1x") == 2.1
    assert extract_price("M\u1eb7t ti\u1ec1n gi\u00e1 1ty3xxtr") == 1.3
    assert extract_price("gi\u00e1 ch\u1ec9 1ty3xxlh 0986694832 v\u00e0o vi\u1ec7c") == 1.3
    assert extract_price("Ch\u1ee7 b\u00e1n gi\u00e1 1ty350tr, sau \u0111\u00f3 ghi gia 1ty3xx") == 1.35
    assert extract_price("Gi\u00e1 2txx") is None
    assert extract_price("Gi\u00e1 3ty**") is None
    assert extract_price("Gi\u00e1 3t\u1ef7**") is None
    assert extract_price("_______\\\\\\_2ty** ( ** nhỏ xíu, Ngay Chủ )") is None
    assert extract_price("Gi\u00e1 3 t\u1ef7 xx") is None
    assert extract_price("Gi\u00e1 3t5x") == 3.5
    assert extract_price("Gi\u00e1 3ty5*") == 3.5
    assert extract_price("Gi\u00e1 3 t\u1ef7 5 *") == 3.5
    assert extract_price("Gi\u00e1 12.x t\u1ef7") is None
    assert extract_price("NH ho tro 500tr") is None
    assert extract_price("MT Th\u00edch Qu\u1ea3ng \u0110\u1ee9c gi\u1ea3m 2t\u1ef7 c\u00f2n 14t\u1ef7") == 14.0
    assert extract_price("Gi\u1ea3m 400 tri\u1ec7u gi\u00e1 4,2 t\u1ef7 ch\u1ec9 c\u00f2n 3,8 t\u1ef7") == 3.8


def test_extract_price_ignores_interior_value_when_asking_price_is_vague():
    assert extract_price("Gi\u00e1 thi\u1ec7n ch\u00ed, full n\u1ed9i th\u1ea5t cao c\u1ea5p h\u01a1n 1 t\u1ef7") is None
    assert extract_price("Full n\u1ed9i th\u1ea5t h\u01a1n 1 t\u1ef7, gi\u00e1 g\u1eb7p ch\u1ee7 th\u01b0\u01a1ng l\u01b0\u1ee3ng") is None
    assert extract_price("N\u1ed9i th\u1ea5t tr\u1ecb gi\u00e1 800 tri\u1ec7u, gi\u00e1 b\u00e1n 5,2 t\u1ef7") == 5.2


def test_extract_price_per_m2_handles_per_meter_shorthand():
    assert extract_price_per_m2("10Tri\u1ec7u/m. R\u1eba QU\u00c1 R\u1eba") == 10
    assert extract_price_per_m2("Gi\u00e1 9,5 tr/m, di\u1ec7n t\u00edch 5x30") == 9.5


def test_price_label_marks_tens_level_approximate_prices():
    assert _format_price_label("M\u1eb7t ti\u1ec1n gi\u00e1 1ty3xxtr") == "~1.3 t\u1ef7"
    assert _format_price_label("Nh\u00e0 ng\u1ed9p gi\u00e1 2ty1x") == "~2.1 t\u1ef7"
    assert _format_price_label("Gi\u00e1 3t5x") == "~3.5 t\u1ef7"
    assert _format_price_label("Gi\u00e1 3ty5*") == "~3.5 t\u1ef7"
    assert _format_price_label("Gi\u00e1 12.x t\u1ef7") is None
    assert _format_price_label("Gi\u00e1 3ty**") is None


def test_normalize_facebook_ambiguous_masked_price_clears_structured_price():
    rec = normalize_record({
        "source": "facebook",
        "external_id": "masked-price",
        "url": "https://facebook.test/masked-price",
        "title": "Hang dep gia chi 3ty**",
        "description": "DT 5x30 mat tien D8, gia chi 3ty** ngay chu",
        "price_ty": 3.0,
        "price_per_m2": 20.0,
        "area_m2": 150.0,
    })

    assert rec["price_ty"] is None
    assert rec["price_per_m2"] is None
    assert rec["area_m2"] == 150.0
    assert rec["_clear_stale_measurements"] is True


def test_extract_area():
    assert extract_area("1.826 m²") == 1826.0
    assert extract_area("110m2") == 110.0
    assert extract_area("DT: 5x18 = 90m²") == 90.0
    assert extract_area("2.546,3 m²") == 2546.3
    # Kích thước → diện tích
    assert extract_area("4x20m") == 80.0
    assert extract_area("Diện tích: 5 x 25m. Thổ Cư : 60 m2") == 125.0
    # Loại thổ cư khỏi area parse
    assert extract_area("DT 500m², thổ cư 100m²") == 500.0
    assert extract_area("Đất P hiệp an\n1/ Nguyễn chí Thanh\n4 dài 28 tc 60") == 112.0
    assert extract_area("ngang 7m x dai 21m. Tho cu 60mv.") == 147.0
    assert extract_area("Di\u1ec7n t\u00edch 15x71m. T\u1ed5ng 1028m2 ch\u01b0a th\u1ed5 c\u01b0.") == 1028.0
    assert extract_area("DT 9.5m x 29m") == 275.5
    assert extract_area("7,5m x 29") == 217.5
    assert extract_area("5,5*27,5") == 151.2
    assert extract_area("6 * 12.4") == 74.4
    assert extract_area("Hòa lợi 5x37tc 60 đường nhựa thông giá 1ty500") == 185.0
    assert extract_area("dt 6x65tc60 đường nhựa 7,5m") == 390.0
    assert extract_area("Ch\u1ec9 ghi ngang 9m") is None


def test_extract_area_prefers_explicit_reported_area_for_irregular_lots():
    assert extract_area("Di\u1ec7n t\u00edch : 7x38m n\u1edf h\u1eadu 9m ~ 309m2 th\u1ed5 c\u01b0 100m2") == 309.0
    assert extract_area("9.1 x 30 = 253 m\u00e9t vu\u00f4ng n\u1edf h\u1eadu 11 ch\u01b0a th\u1ed5 c\u01b0") == 253.0
    assert extract_area("Di\u1ec7n t\u00edch 10 x 69, c\u00f3 400mv th\u1ed5 c\u01b0") == 690.0


def test_extract_area_ignores_floor_or_usable_area_when_land_area_missing():
    assert extract_area("Nhà 1 trệt 2 lầu, tổng diện tích sàn 319m2, 5 phòng ngủ") is None
    assert extract_area("Diện tích xây dựng 180m2 sàn, nhà Phú Lợi") is None
    assert extract_area("Sổ 48m2, diện tích sử dụng 60m2") == 48.0


def test_extract_area_skips_truncated_invalid_dimension_before_full_description():
    text = (
        "\u0110\u1ea5t \u0110\u1ecbnh Ho\u00e0 nh\u00e1nh Dx71\n"
        "Di\u1ec7n t\u00edch : 5,24m x 2\n"
        "\u0110\u1ea5t \u0110\u1ecbnh Ho\u00e0 nh\u00e1nh Dx71\n"
        "Di\u1ec7n t\u00edch : 5,24m x 29m, th\u1ed5 c\u01b0 60m."
    )
    assert extract_area(text) == 152.0


def test_detect_multi_lot_listing():
    assert is_multi_lot_listing(
        "L\u00f4 1-300m2-2,15t\u1ef7/ L\u00f4 2-483,7m2-2,55t\u1ef7",
        (
            "L\u00f4 1-300m2-2,15t\u1ef7\n"
            "L\u00f4 2-483,7m2-2,55t\u1ef7\n"
            "15 ng\u00e0y c\u00f3 s\u1ed5.ch\u01b0a th\u1ed5 c\u01b0 h\u1ed7 tr\u1ee3 l\u00ean tho\u1ea3i m\u00e1i"
        ),
    )
    assert not is_multi_lot_listing(
        "B\u00e1n 1 l\u00f4 \u0111\u1ea5t 300m2 gi\u00e1 2,15 t\u1ef7",
        "S\u1ed5 s\u1eb5n, th\u01b0\u01a1ng l\u01b0\u1ee3ng ch\u00ednh ch\u1ee7.",
    )
    assert is_multi_lot_listing(
        "\u0110\u1ea5t t\u00e1i \u0111\u1ecbnh c\u01b0 Ch\u00e1nh M\u1ef9",
        (
            "C\u00f3 3 l\u00f4 li\u1ec1n k\u1ec1; 15x20; TC 100%. "
            "Di\u1ec7n t\u00edch m\u1ed7i l\u00f4: 5x20; th\u1ed5 c\u01b0 100%. "
            "Gi\u00e1: 2 t\u1ef7 650 / l\u00f4. C\u00f3 b\u00e1n l\u1ebb t\u1eebng l\u00f4."
        ),
    )


def test_extract_dimensions():
    d = extract_dimensions("ngang 22.5m sâu 82m")
    assert d["frontage_m"] == 22.5
    assert d["depth_m"] == 82.0

    d = extract_dimensions("4x34")
    assert d["frontage_m"] == 4.0
    assert d["depth_m"] == 34.0

    d = extract_dimensions("Đất P hiệp an 1/ Nguyễn chí Thanh 4 dài 28 tc 60")
    assert d["frontage_m"] == 4.0
    assert d["depth_m"] == 28.0
    d = extract_dimensions("ngang 7m x dai 21m. Tho cu 60mv.")
    assert d["frontage_m"] == 7.0
    assert d["depth_m"] == 21.0

    d = extract_dimensions("DT 9.5m x 29m")
    assert d["frontage_m"] == 9.5
    assert d["depth_m"] == 29.0
    d = extract_dimensions("7,5m x 29")
    assert d["frontage_m"] == 7.5
    assert d["depth_m"] == 29.0
    d = extract_dimensions("5,5*27,5")
    assert d["frontage_m"] == 5.5
    assert d["depth_m"] == 27.5
    d = extract_dimensions("6 * 12.4")
    assert d["frontage_m"] == 6.0
    assert d["depth_m"] == 12.4
    d = extract_dimensions("Hòa lợi 5x37tc 60 đường nhựa thông giá 1ty500")
    assert d["frontage_m"] == 5.0
    assert d["depth_m"] == 37.0
    d = extract_dimensions("dt 6x65tc60 đường nhựa 7,5m")
    assert d["frontage_m"] == 6.0
    assert d["depth_m"] == 65.0
    d = extract_dimensions("Ch\u1ec9 hi\u1ec3n th\u1ecb ngang 9m")
    assert d["frontage_m"] == 9.0
    assert d["depth_m"] is None


def test_extract_dimensions_handles_m2_typo_after_frontage():
    d = extract_dimensions("DT: 9m2 x 12,6m th\u1ed5 c\u01b0 60m2")
    assert d["frontage_m"] == 9.0
    assert d["depth_m"] == 12.6


def test_extract_area_and_dimensions_handle_compact_decimal_frontage():
    text = "Đất Chánh nghĩa gần chợ TDM 1/ Nguyễn Tri Phương. Dt 5m7x22m thổ cư 80m."
    assert extract_area(text) == 125.4
    dims = extract_dimensions(text)
    assert dims["frontage_m"] == 5.7
    assert dims["depth_m"] == 22.0


def test_extract_dimensions_keeps_bare_ngang_value_before_no_hau_phrase():
    dims = extract_dimensions("Đất chánh mỹ ngang 13 nở hậu tdt 432m2 thổ cư 25m2")
    assert dims["frontage_m"] == 13.0
    assert dims["depth_m"] is None


def test_extract_area_and_dimensions_skip_truncated_dimension_prefix():
    text = (
        "Dat mat tien DX90 Hiep An\n"
        "Dien tich: 5 x 2\n"
        "Dat mat tien DX90 Hiep An\n"
        "Dien tich: 5 x 25m. Tho cu : 60 m2"
    )

    assert extract_area(text) == 125.0
    dims = extract_dimensions(text)
    assert dims["frontage_m"] == 5.0
    assert dims["depth_m"] == 25.0


def test_extract_tho_cu():
    r = extract_tho_cu("300m² thổ cư", 500)
    assert r["tho_cu_m2"] == 300
    assert abs(r["tho_cu_ratio"] - 0.6) < 0.01

    r = extract_tho_cu("full thổ cư", 100)
    assert r["tho_cu_ratio"] == 1.0


def test_extract_tho_cu_percent_means_full_area_not_100m2():
    samples = [
        "DT 5x15 = 75m2, th\u1ed5 c\u01b0 100%",
        "DT 5x15 = 75m2, Th\u1ed5 c\u01b0: 100 %",
        "DT 5x15 = 75m2, TC 100%",
        "DT 5x15 = 75m2, 100% th\u1ed5 c\u01b0",
    ]
    for text in samples:
        r = extract_tho_cu(text, 75)
        assert r["tho_cu_m2"] == 75
        assert r["tho_cu_ratio"] == 1.0


def test_extract_tho_cu_prefers_value_after_label_when_title_has_total_area():
    samples = [
        ("B\u00e1n Nh\u00e0 ri\u00eang 108m\u00b2 th\u1ed5 c\u01b0 60m\u00b2 gi\u00e1 3.6 t\u1ef7", 108, 60),
        ("B\u00e1n Nh\u00e0 ri\u00eang 145m2 th\u1ed5 c\u01b0 100m2 gi\u00e1 7.6 t\u1ef7", 145, 100),
    ]
    for text, total_area, expected in samples:
        r = extract_tho_cu(text, total_area)
        assert r["tho_cu_m2"] == expected
        assert round(r["tho_cu_ratio"], 3) == round(expected / total_area, 3)


def test_extract_tho_cu_prefers_complete_unit_match_over_truncated_title():
    text = (
        "Di\u1ec7n t\u00edch 72m2 th\u1ed5 c\u01b0 6 | "
        "Di\u1ec7n t\u00edch 72m2 th\u1ed5 c\u01b0 60m2, nh\u00e0 1 tr\u1ec7t 1 l\u1eedng"
    )
    r = extract_tho_cu(text, 72)
    assert r["tho_cu_m2"] == 60
    assert round(r["tho_cu_ratio"], 3) == 0.833


def test_extract_tho_cu_handles_value_before_label_with_mv_unit():
    r = extract_tho_cu("Di\u1ec7n t\u00edch 10 x 69, c\u00f3 400mv th\u1ed5 c\u01b0", 690)
    assert r["tho_cu_m2"] == 400
    assert round(r["tho_cu_ratio"], 3) == 0.58


def test_extract_tho_cu_handles_facebook_broker_shorthand_from_signal_audit():
    samples = [
        ("Di\u1ec7n t\u00edch 5.6x39, 188m2 (100tc)", 188, 100),
        ("13 x109 c\u00f3 300 tc M\u1ef9 ph\u01b0\u1edbc 1", 1417, 300),
        ("Dt 120mv, th\u1ed5 s\u1eb5n 80", 120, 80),
        ("Dt 120mv, th\u1ed5 s\u1eb5n 80. \u0110\u01b0\u1eddng nh\u1ef1a \u00f4 t\u00f4", 120, 80),
        ("Dt 5,24 x 29, th\u1ed5 60", 152, 60),
        ("Dt 4,5m x 26m, c\u00f3 60m2 odt", 117, 60),
        ("Di\u1ec7n t\u00edch 5x30m. Th\u1ed5 c\u01b0 . 100%", 150, 150),
        ("dt 4x25tc fun \u0111\u01b0\u1eddng b\u00ea t\u00f4ng", 100, 100),
        ("dt. 10 x 24tc fun, \u0111\u01b0\u1eddng b\u00ea t\u00f4ng", 240, 240),
        ("dt 5x37tc.75m gi\u00e1 1ty390", 185, 75),
        ("dt 5x30 th\u1ed5 c\u01b0. S\u00e1t ch\u1ee3", 150, 150),
        ("dt 5x50 th\u1ed5 c\u01b0 m\u1ed7i l\u00f4 60m", 250, 60),
    ]

    for text, total_area, expected in samples:
        r = extract_tho_cu(text, total_area)
        assert r["tho_cu_m2"] == expected
        assert round(r["tho_cu_ratio"], 3) == round(expected / total_area, 3)


def test_extract_tho_cu_does_not_read_dimension_depth_as_tc_value():
    assert extract_tho_cu("dt 5x37tc 60m", 185)["tho_cu_m2"] == 60
    assert extract_tho_cu("dt 5x37tc.75m", 185)["tho_cu_m2"] == 75
    assert extract_tho_cu("\u0111\u01b0\u1eddng TC 1A M\u1ef9 Ph\u01b0\u1edbc", 150)["tho_cu_m2"] is None
    assert extract_tho_cu("6x31 ch\u01b0a th\u1ed5 c\u01b0", 186)["tho_cu_m2"] is None
    assert extract_tho_cu("Tổng diện tích sàn 319m2, nhà 5 phòng ngủ", 319)["tho_cu_m2"] is None
    assert extract_tho_cu("Nhà gồm 1 phòng khách, 1 phòng thờ, 5 phòng ngủ", None)["tho_cu_m2"] is None


def test_extract_tho_cu_treats_land_label_before_dimensions_as_full_lot():
    samples = [
        ("B\u00e1n \u0111\u1ea5t th\u1ed5 c\u01b0 6 x 31 \u0111\u01b0\u1eddng nh\u1ef1a", 186),
        ("L\u00f4 \u0111\u1ea5t th\u1ed5 c\u01b0 6m x 31m, s\u1ed5 ri\u00eang", 186),
        ("\u0110\u1ea5t th\u1ed5 c\u01b0 5 x 20 gi\u00e1 t\u1ed1t", 100),
    ]
    for text, total_area in samples:
        r = extract_tho_cu(text, total_area)
        assert r["tho_cu_m2"] == total_area
        assert r["tho_cu_ratio"] == 1.0


def test_normalizer_parses_bare_width_dai_depth_and_tho_cu():
    rec = normalize_record({
        "source": "facebook",
        "external_id": "hiep-an-nguyen-chi-thanh-bare-dims",
        "url": "https://www.facebook.com/example/posts/hiep-an-nguyen-chi-thanh-bare-dims",
        "default_area": "Thủ Dầu Một",
        "title": "Đất P hiệp an Tp thủ dầu một Bình dương",
        "description": "1/ Nguyễn chí Thanh\n4 dài 28 tc 60\nGiá 1 tỷ 380 /lô",
    })

    assert rec is not None
    assert rec["ward"] == "Hiệp An"
    assert rec["area_m2"] == 112.0
    assert rec["frontage_m"] == 4.0
    assert rec["depth_m"] == 28.0
    assert rec["tho_cu_m2"] == 60.0
    assert rec["price_ty"] == 1.38
    assert round(rec["price_per_m2"], 2) == 12.32


def test_normalizer_overrides_truncated_structured_price_from_full_text():
    rec = normalize_record({
        "source": "facebook",
        "external_id": "tan-dinh-truncated-title-price",
        "url": "https://www.facebook.com/example/posts/tan-dinh-truncated-title-price",
        "default_area": "B\u1ebfn C\u00e1t",
        "title": "Kp2 t\u00e2n \u0111\u1ecbnh 5,20 x41 TC 60m \u0111\u01b0\u1eddng 7m gi\u00e1 1ty",
        "description": "Kp2 t\u00e2n \u0111\u1ecbnh 5,20 x41 TC 60m \u0111\u01b0\u1eddng 7m gi\u00e1 1ty900 gi\u00e1 bao \u00eam",
        "price_ty": 1.0,
        "area_m2": 213.2,
    })

    assert rec is not None
    assert rec["price_ty"] == 1.9
    assert rec["area_m2"] == 213.2


def test_normalizer_overrides_structured_area_when_it_is_tho_cu_not_total_area():
    rec = normalize_record({
        "source": "facebook",
        "external_id": "tan-dinh-area-is-tho-cu",
        "url": "https://www.facebook.com/example/posts/tan-dinh-area-is-tho-cu",
        "default_area": "B\u1ebfn C\u00e1t",
        "title": "Nh\u00e0 c\u1ea5p 4 khu 3 T\u00e2n \u0111\u1ecbnh DT 9 x 15 th\u1ed5 c\u01b0 100m gi\u00e1 1 t\u1ef7 7xx",
        "description": "Tr\u00ean \u0111\u1ea5t c\u00f3 2 c\u0103n nh\u00e0, m\u1eb7t ti\u1ec1n \u0111\u01b0\u1eddng nh\u1ef1a, s\u1ed5 th\u1ec3 hi\u1ec7n \u0111\u01b0\u1eddng.",
        "price_ty": 1.7,
        "area_m2": 100.0,
    })

    assert rec is not None
    assert rec["area_m2"] == 135.0
    assert rec["tho_cu_m2"] == 100.0


def test_normalizer_prefers_reported_total_area_over_dimension_product():
    rec = normalize_record({
        "source": "facebook",
        "external_id": "phu-cuong-irregular-reported-area",
        "url": "https://www.facebook.com/example/posts/phu-cuong-irregular-reported-area",
        "default_area": "Th\u1ee7 D\u1ea7u M\u1ed9t",
        "title": "Ng\u1ed9p C\u1ea7n Ra G\u1ea5p. Nh\u00e0 c\u1ea5p 4 s\u00e2n v\u01b0\u1eddn.",
        "description": "Di\u1ec7n t\u00edch : 7x38m n\u1edf h\u1eadu 9m ~ 309m2 th\u1ed5 c\u01b0 100m2. Gi\u00e1 4t\u1ef79.",
        "price_ty": 4.9,
        "area_m2": 266.0,
    })

    assert rec is not None
    assert rec["area_m2"] == 309.0
    assert rec["frontage_m"] == 7.0
    assert rec["depth_m"] == 38.0
    assert rec["tho_cu_m2"] == 100.0

    rec = normalize_record({
        "source": "facebook",
        "external_id": "phu-cuong-irregular-reported-area-missing-structured-area",
        "url": "https://www.facebook.com/example/posts/phu-cuong-irregular-reported-area-missing-structured-area",
        "default_area": "Th\u1ee7 D\u1ea7u M\u1ed9t",
        "title": "Ng\u1ed9p C\u1ea7n Ra G\u1ea5p. Nh\u00e0 c\u1ea5p 4 s\u00e2n v\u01b0\u1eddn.",
        "description": "Di\u1ec7n t\u00edch : 7x38m n\u1edf h\u1eadu 9m ~ 309m2 th\u1ed5 c\u01b0 100m2. Gi\u00e1 4t\u1ef79.",
        "price_ty": 4.9,
    })

    assert rec is not None
    assert rec["area_m2"] == 309.0
    assert rec["frontage_m"] == 7.0
    assert rec["depth_m"] == 38.0
    assert rec["tho_cu_m2"] == 100.0

    rec = normalize_record({
        "source": "facebook",
        "external_id": "hiep-thanh-reported-area",
        "url": "https://www.facebook.com/example/posts/hiep-thanh-reported-area",
        "default_area": "Th\u1ee7 D\u1ea7u M\u1ed9t",
        "title": "\u0110\u1ed1i di\u1ec7n KDC Hi\u1ec7p Th\u00e0nh 3",
        "description": "Gi\u00e1 2 t\u1ef7 550 c\u00f2n th\u01b0\u01a1ng l\u01b0\u1ee3ng ( DT : 4x28 = 96m2 ).",
        "price_ty": 2.55,
        "area_m2": 112.0,
    })

    assert rec is not None
    assert rec["area_m2"] == 96.0
    assert rec["frontage_m"] == 4.0
    assert rec["depth_m"] == 28.0


def test_normalizer_parses_dimensions_even_when_area_is_structured():
    rec = normalize_record({
        "source": "facebook",
        "external_id": "structured-area-with-frontage-only",
        "url": "https://www.facebook.com/example/posts/structured-area-with-frontage-only",
        "default_area": "Th\u1ee7 D\u1ea7u M\u1ed9t",
        "title": "\u0110\u1ea5t Hi\u1ec7p An ngang 9m",
        "description": "Di\u1ec7n t\u00edch 215m2, gi\u00e1 4t390tr, \u0111\u01b0\u1eddng nh\u1ef1a.",
        "area_m2": 215.0,
    })

    assert rec is not None
    assert rec["area_m2"] == 215.0
    assert rec["frontage_m"] == 9.0
    assert rec["depth_m"] == 23.9
    assert rec["price_ty"] == 4.39
    assert round(rec["price_per_m2"], 2) == 20.42


def test_normalizer_prefers_dimension_area_over_residential_area():
    rec = normalize_record({
        "source": "facebook",
        "external_id": "structured-area-is-tho-cu",
        "url": "https://www.facebook.com/example/posts/structured-area-is-tho-cu",
        "default_area": "Thủ Dầu Một",
        "title": "Đất Hiệp An đường DX89 giá tốt",
        "description": (
            "Diện tích : 5,8 x 26,6. Thổ cư : 100mv. "
            "Đường nhựa thông, giá tốt: 2ty390."
        ),
        "area_m2": 100.0,
    })

    assert rec is not None
    assert rec["area_m2"] == 154.3
    assert rec["frontage_m"] == 5.8
    assert rec["depth_m"] == 26.6
    assert rec["tho_cu_m2"] == 100.0
    assert round(rec["price_per_m2"], 2) == 15.49


def test_normalizer_parses_user_reported_facebook_edge_cases():
    branch_land = normalize_record({
        "source": "facebook",
        "external_id": "branch-le-hong-phong-12x",
        "url": "https://www.facebook.com/example/posts/branch-le-hong-phong-12x",
        "default_area": "Th\u1ee7 D\u1ea7u M\u1ed9t",
        "title": "\u0110\u1ea5t 1/ L\u00ea H\u1ed3ng Phong g\u1ea7n kdc Ph\u00fa Ho\u00e0.",
        "description": (
            "M\u1eb7t ti\u1ec1n Kinh doanh nh\u1ef1a 6m th\u00f4ng,\n"
            "DT 11x73 cln, l\u00ean th\u1ed5 c\u01b0 OK\n"
            "Gi\u00e1 12,x t\u1ef7."
        ),
    })
    assert branch_land is not None
    assert branch_land["price_ty"] is None
    assert branch_land["area_m2"] == 803.0
    assert branch_land["frontage_m"] == 11.0
    assert branch_land["depth_m"] == 73.0
    assert branch_land["road_type"] == "be_tong"
    assert branch_land["road_tier"] == 3

    bold_price_house = normalize_record({
        "source": "facebook",
        "external_id": "bold-price-phu-loi",
        "url": "https://www.facebook.com/example/posts/bold-price-phu-loi",
        "default_area": "Th\u1ee7 D\u1ea7u M\u1ed9t",
        "title": "\U0001f340\U0001d406\U0001d422\u1ea3\U0001d426 :100\U0001d42d\U0001d42b - \U0001d406\U0001d422\U0001d41a\u0301 \U0001d41c\U0001d428\u0300\U0001d427 : 4\U0001d42d\u1ef7390\U0001d42d\U0001d42b",
        "description": (
            "B\u00e1n Nh\u00e0 - Khu 6 - Ph\u00fa L\u1ee3i\n"
            "DT:ngang 9m  tc80m (t\u1ed5ng 215m2. )\n"
            "Nh\u00e0 s\u00e2n \u00f4 t\u00f4, \u0111\u01b0\u1eddng nh\u1ef1a 5m th\u00f4ng"
        ),
    })
    assert bold_price_house is not None
    assert bold_price_house["price_ty"] == 4.39
    assert bold_price_house["area_m2"] == 215.0
    assert bold_price_house["frontage_m"] == 9.0
    assert bold_price_house["tho_cu_m2"] == 80.0

    title_dimensions = normalize_record({
        "source": "facebook",
        "external_id": "tan-an-title-dimensions",
        "url": "https://www.facebook.com/example/posts/tan-an-title-dimensions",
        "default_area": "Th\u1ee7 D\u1ea7u M\u1ed9t",
        "title": "B\u00e1n nhanh nh\u00e0 T\u00e2n An Th\u1ee7 D\u1ea7u M\u1ed9t B\u00ecnh D\u01b0\u01a1ng ngang 7m x d\u00e0i 21m.",
        "description": "Th\u1ed5 c\u01b0 60mv. Mt \u0111\u01b0\u1eddng betong Oto th\u00f4ng. Gi\u00e1 r\u1ebb: 2ty550tr.",
    })
    assert title_dimensions is not None
    assert title_dimensions["price_ty"] == 2.55
    assert title_dimensions["area_m2"] == 147.0
    assert title_dimensions["frontage_m"] == 7.0
    assert title_dimensions["depth_m"] == 21.0
    assert title_dimensions["tho_cu_m2"] == 60.0

    price_after_discount = normalize_record({
        "source": "facebook",
        "external_id": "phu-cuong-discount-200-not-price",
        "url": "https://www.facebook.com/example/posts/phu-cuong-discount-200-not-price",
        "default_area": "Th\u1ee7 D\u1ea7u M\u1ed9t",
        "title": "B\u00e1n nhanh gi\u1ea3m gi\u00e1: 200 tri\u1ec7u trong tu\u1ea7n nh\u00e0; TRUNG T\u00c2M PH\u00da C\u01af\u1edcNG TP.TDM C\u1ee6",
        "description": (
            "Nh\u00e0 3 m\u1eb7t ti\u1ec1n th\u00f4ng tho\u00e1ng; S\u1ed1: 238/18, Th\u00edch Qu\u1ea3ng \u0110\u1ee9c, Ph\u00fa C\u01b0\u1eddng, TDM, BD; "
            "Nh\u00e0: c\u1ea5p 4; Di\u1ec7n t\u00edch: 49 M2, Th\u1ed5 c\u01b0: 49 M2; "
            "*** Gi\u00e1: 2 t\u1ef7 6; C\u00f3 h\u1ed7 tr\u1ee3 Ng\u00e2n h\u00e0ng."
        ),
    })
    assert price_after_discount is not None
    assert price_after_discount["ward"] == "Ph\u00fa C\u01b0\u1eddng"
    assert price_after_discount["price_ty"] == 2.6
    assert price_after_discount["area_m2"] == 49.0
    assert round(price_after_discount["price_per_m2"], 2) == 53.06
    assert price_after_discount["property_type"] == "nha_dat"

    dx072_large_land = normalize_record({
        "source": "facebook",
        "external_id": "dx072-large-land-not-house",
        "url": "https://www.facebook.com/example/posts/dx072-large-land-not-house",
        "default_area": "Th\u1ee7 D\u1ea7u M\u1ed9t",
        "title": "H\u01a1n 1000m2 \u0111\u1ea5t m\u1eb7t ti\u1ec1n DX072 \u0110\u1ecbnh H\u00f2a Th\u1ee7 D\u1ea7u M\u1ed9t B\u00ecnh D\u01b0\u01a1ng m\u00e0 gi\u00e1 ch\u1ec9 5,9 t\u1ef7",
        "description": (
            "Di\u1ec7n t\u00edch 15x71m. T\u1ed5ng 1028m2 ch\u01b0a th\u1ed5 c\u01b0. "
            "X\u00e2y c\u00e1i bi\u1ec7t th\u1ef1 s\u00e2n v\u01b0\u1eddn l\u00e0 h\u1ebft \u00fd. Gi\u00e1 ch\u1ec9 5,9 t\u1ef7 c\u00f2n tl"
        ),
    })
    assert dx072_large_land is not None
    assert dx072_large_land["ward"] == "\u0110\u1ecbnh H\u00f2a"
    assert dx072_large_land["price_ty"] == 5.9
    assert dx072_large_land["area_m2"] == 1028.0
    assert round(dx072_large_land["price_per_m2"], 2) == 5.74
    assert dx072_large_land["frontage_m"] == 15.0
    assert dx072_large_land["depth_m"] == 71.0
    assert dx072_large_land["property_type"] == "dat_nen"

    ppm2_price_land = normalize_record({
        "source": "facebook",
        "external_id": "chanh-my-price-per-meter",
        "url": "https://www.facebook.com/example/posts/chanh-my-price-per-meter",
        "default_area": "Th\u1ee7 D\u1ea7u M\u1ed9t",
        "title": "10Tri\u1ec7u/m. R\u1eba QU\u00c1 R\u1eba",
        "description": "B\u00e1n \u0111\u1ea5t Ch\u00e1nh M\u1ef9. Di\u1ec7n t\u00edch: 10x46 th\u1ed5 c\u01b0 150m. \u0110\u01b0\u1eddng 5m nh\u1ef1a.",
    })
    assert ppm2_price_land is not None
    assert ppm2_price_land["area_m2"] == 460.0
    assert ppm2_price_land["price_per_m2"] == 10.0
    assert ppm2_price_land["price_ty"] == 4.6


def test_normalizer_does_not_treat_discount_or_down_payment_as_asking_price():
    discount = normalize_record({
        "source": "facebook",
        "external_id": "discount-not-price",
        "url": "https://www.facebook.com/example/posts/discount-not-price",
        "default_area": "Bến Cát",
        "title": "Rẻ hơn thị trường 100 triệu. Lô đất kế bên đường DL12 khu L Mỹ Phước 3",
        "description": "Diện tích 5x30m, sổ sẵn, phí 2% cho anh em môi giới",
    })
    assert discount is not None
    assert discount["ward"] == "Mỹ Phước 3"
    assert discount["area_m2"] == 150.0
    assert discount["price_ty"] is None
    assert discount["price_per_m2"] is None

    down_payment = normalize_record({
        "source": "facebook",
        "external_id": "down-payment-not-price",
        "url": "https://www.facebook.com/example/posts/down-payment-not-price",
        "default_area": "Bến Cát",
        "title": "Đưa trước 500 triệu còn lại ngân hàng Vietcombank Mỹ Phước hỗ trợ trả góp",
        "description": "Nhà tại Mỹ Phước, diện tích 66m2, sổ riêng",
    })
    assert down_payment is not None
    assert down_payment["price_ty"] is None
    assert down_payment["price_per_m2"] is None


def test_extract_road_tier():
    # Tier 1 — đường tên trong whitelist + MT
    assert extract_road_tier("Mặt tiền đường Lê Chí Dân") == 1
    # Tier 2 — DX
    assert extract_road_tier("Đường DX117 Tân An") == 2
    # Tier 3 - unnamed asphalt road is not enough evidence for tier 2.
    assert extract_road_tier("Đường nhựa rộng 6m") == 3
    assert extract_road_tier("Đường nhựa 5m thông") == 3
    # Tier 3 — hẻm ≥5m
    assert extract_road_tier("Hẻm bê tông 6m", "") == 3
    # Tier 3 — hẻm 3-5m can fit a car.
    assert extract_road_tier("hẻm 4m", "") == 3
    # Tier 4 — hẻm <3m is motorbike-only.
    assert extract_road_tier("hẻm 2m", "") == 4
    # Tier 0 — unknown
    assert extract_road_tier("đất đẹp giá tốt", "") == 0


def test_extract_road_tier_new_patterns():
    # Generic frontage without a clear road name/code is not tier 1/2 evidence.
    assert extract_road_tier("Bán đất mặt tiền 72m² Phường Phú An") == 3
    # Đường xe tải / xe hơi → Tier 3
    assert extract_road_tier("Bán đất 130m², đường xe tải, gần chợ") == 3
    assert extract_road_tier("Đường xe hơi vào tận nhà") == 3
    # Biến thể "ôtô" liền, "oto" không dấu → Tier 3
    assert extract_road_tier("Hẻm ôtô thông 5m") == 3
    assert extract_road_tier("Oto vào đến cửa") == 3
    # MTKD / kinh doanh without a clear road name/code remains tier 3.
    assert extract_road_tier("Bán nhà MTKD Phường Phú An") == 3
    assert extract_road_tier("Mặt tiền kinh doanh sầm uất") == 3
    # Generic road class without a clear street name/code remains tier 3.
    assert extract_road_tier("Đất mặt tiền đê bao sông Sài Gòn") == 3
    # Width-only road evidence is tier 3 unless a clear road name/code is present.
    assert extract_road_tier("Lộ giới 8m phường Tân An") == 3
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
    assert extract_road_tier(
        "Bán đất Hiệp An",
        "Cách Đường Bùi Ngọc Thu 50 mét thôi. Đường xe ba gác DT 5 x 28 thổ cư 110 mét",
    ) == 4
    assert extract_road_tier(
        "Bán Đất Tặng nhà Cấp 4 Hiệp An",
        "Cách Đường Bùi Ngọc Thu 50 mét thôi . Đường xe ba gác "
        "DT 5 x 28 thổ cư 110 mét Giá 1 tỷ 6 còn bớt",
    ) == 4
    assert extract_road_tier(
        "Nhà trệt lửng Định Hòa, nhanh dx67",
        "Đường xe hơi tới nhà. Sân xe hơi, phòng khách, bếp",
    ) == 3
    assert extract_road_tier(
        "Bán đất Tân An. Thủ Dầu Một. Bình Dương Mt đường nhựa 5,5m thông, lề đường 2,2m",
        "gần trường đào tạo lái xe, trường học Trần Bình Trọng. Dt 5,5x45=247m2.",
    ) == 3
    assert extract_road_tier(
        "Chủ hạ giá bán nhanh lô đất KP4 Tân Định",
        "đường nhựa thông giá 1ty8",
    ) == 3
    assert extract_road_tier(
        "📣chốt nhanh mới kịp\n"
        "🌷🌷 Bán Đất Tặng nhà Cấp 4 Hiệp An Thủ Dầu Một nay là phường Chánh Hiệp TpHCM . C",
        "📣chốt nhanh mới kịp\n"
        "🌷🌷 Bán Đất Tặng nhà Cấp 4 Hiệp An Thủ Dầu Một nay là phường Chánh Hiệp TpHCM . "
        "Cách Đường Bùi Ngọc Thu 50 mét thôi . Đường xe ba gác \n"
        "DT 5 x 28 thổ cư 110 mét \n"
        "💰💰Giá 1 tỷ 6 còn bớt\n"
        "Lh Hằng 0948018508 xem nhà GC",
    ) == 4
    assert extract_road_tier("Hẻm xe máy sát chợ") == 4
    # Broker typo: "đường 4m2" means road width 4m in this context.
    assert extract_road_tier("Rẻ nhất Tân An, đường 4m2 hiện sổ") == 3
    # "1/" before a DX road in the description is a branch/alley address,
    # even when the line also says car access.
    assert extract_road_tier(
        "GIAM GIA BAN LE",
        "phuong dinh hoa\n1/ Dx 072 duong Oto\nDt : 4 dai 30",
    ) == 3
    assert extract_road_tier(
        "Nha Phu Hoa vi tri VIP",
        "1/ duong Nguyen Thai Binh, ngay cho nho, gia 2ty790",
    ) == 3
    assert extract_road_tier(
        "Ban dat tang nha trung tam Chanh Nghia",
        "Gan Duong Lo Chen. Duong oto vao toi nha.",
    ) == 3
    assert extract_road_tier(
        "Nha ngop Tuong Binh Hiep",
        "cach nhua 20m thoi, nha dep, gia 2ty1x",
    ) == 3
    assert extract_road_tier(
        "Dat Chanh Nghia trung tam Thu Dau Mot. 1 sec",
        "1 sec 30 thang 4 vao. Duong nhua thong dep kinh doanh buon ban tot.",
    ) == 3
    assert extract_road_tier(
        "Đất Chánh Nghĩa trung tâm Thủ Dầu Một. 1 sẹc",
        "1 sẹc 30 tháng 4 vào. Đường nhựa thông đẹp kinh doanh buôn bán tốt.",
    ) == 3
    # Through-road with no width/type is usable evidence but not a main road.
    assert extract_road_tier("Nhà đẹp", "Đường thông tứ hướng, khu dân cư đông") == 3
    # Mỹ Phước grid street codes in description should be picked up, not only title.
    assert extract_road_tier("Bán nhà Mỹ Phước 3", "đường DJ6 gần trường") == 2
    assert extract_road_tier("Bán nhà Mỹ Phước 1", "đường TC 1A") == 2


def test_extract_road_tier_signal_audit_edge_cases():
    assert extract_road_tier(
        "Bán Đất Mặt Tiền Dx44 Phú Mỹ. Gần quán 2Nù . Phạm Ngọc Thạch. Hiệp Thành 3.",
        "Dt 193m thổ cư 100%. Đường Nhựa 8m thông.",
    ) == 2
    assert extract_road_tier(
        "Chủ bán lô đất kp3 tân định",
        "5x40 TC 50m đường bê tông, đất có 2 mặt đường trước sau",
    ) == 3


def test_extract_road_type_small_access_patterns():
    assert extract_road_type("Ban dat duong ba gac Tan An") == "hem_ba_gac"
    assert extract_road_type("Hem xe may sat cho") == "hem_xe_may"
    assert extract_road_type("Duong oto vao tan dat") == "hem_xe_hoi"
    assert extract_road_type(("GIAM GIA BAN LE " * 12) + "1/ Dx 072 duong Oto") == "be_tong"
    assert extract_road_type("Nha dep cach nhua 20m thoi") == "unknown"


def test_extract_road_name_ignores_proximity_but_keeps_actual_roads():
    assert extract_road_name("Nhà khu 1 Tân Định. Cách QL14 chỉ 70m") is None
    assert extract_road_name("Sát QL13 và QL14, dân cư đông đúc") is None
    assert extract_road_name("Mặt tiền QL13 kinh doanh tốt") == "QL13"
    assert extract_road_name("Nhà nhánh Nguyễn Đức Thuận, đường ô tô 4m") == "Nguyen Duc Thuan"
    assert extract_road_name("Nhà 1/ hẻm 232 Nguyễn Đức Thuận, Hiệp Thành") == "Hem 232 Nguyen Duc Thuan"
    assert extract_road_name("Đất MT Đường Số 76 – Thành phố mới") == "Duong So 76"
    assert extract_road_name("Đường DB12 _ Khu Đô Thị Mới") == "DB12"
    assert extract_road_name("Mặt Tiền Đường 5C TĐC Định Hoà") == "5C"
    assert extract_road_type("5x41tc 80m đường đất 4m chuẩn bị lên nhựa") == "duong_dat"


def test_extract_road_name_captures_named_alley_without_house_number():
    assert extract_road_name("Nh\u00e0 h\u1ebbm B\u00f9i Qu\u1ed1c Kh\u00e1nh, \u0111\u01b0\u1eddng xe h\u01a1i") == "Bui Quoc Khanh"
    assert extract_road_name("H\u1ebbm Hu\u1ef3nh V\u0103n L\u0169y, l\u00f4 g\u00f3c 2 m\u1eb7t ti\u1ec1n") == "Huynh Van Luy"


def test_extract_road_name_keeps_nhanh_dx_codes():
    assert extract_road_name("\u0110\u1ea5t \u0110\u1ecbnh H\u00f2a nh\u00e1nh DX72 d\u00e2n c\u01b0 \u0111\u00f4ng") == "DX72"
    assert extract_road_name("Nh\u00e0 c\u1ea5p 4 Hi\u1ec7p An nh\u00e1nh dx088 \u0111\u01b0\u1eddng b\u00ea t\u00f4ng 3,7m") == "DX88"


def test_classify_property_type_ignores_potential_use_apartment_words():
    title = "Chu gui ban gap sieu pham duong DB12"
    description = (
        "DT: 6,6x30m full tho cu. "
        "Phu hop lam toa nha van phong, cong ty, khach san, "
        "can ho dich vu, nha nghi, biet thu."
    )

    assert classify_property_type(title, description, 198.0, 198.0) == "dat_nen"


def test_parse_facebook_post_ignores_floor_area_and_bedroom_counts_from_manual_qc():
    floor_area = parse_facebook_post(
        "Ban nha trung tam Thu Dau Mot gia 3,8 ty\n"
        "Nha thiet ke 1 tret 3 lau, tong dien tich san 319m2, "
        "gom 1 phong khach, 5 phong ngu, 4wc."
    )
    construction_area = parse_facebook_post(
        "Nha tret 2 lau Phu Loi ngang 7m\n"
        "Dien tich xay dung 180m2 san. Nha gom 4 phong ngu, 3wc."
    )

    assert floor_area["area_m2"] is None
    assert floor_area["tho_cu_m2"] is None
    assert construction_area["area_m2"] is None


def test_match_ward_maps_hiep_thanh_kdc_landmarks_to_parent_old_ward():
    assert match_ward("Gần KDC Hiệp Thành 3", intended_city="Thủ Dầu Một") == "Hiệp Thành"
    assert match_ward("ĐỐI DIỆN KDC HIỆP THÀNH 3", intended_city="Thủ Dầu Một") == "Hiệp Thành"
    assert match_ward("Gần Hiệp Thành 3", intended_city="Thủ Dầu Một") == "Hiệp Thành"
    assert match_ward("Đối diện KDC K8 Hiệp Thành", intended_city="Thủ Dầu Một") == "Hiệp Thành"
    assert (
        match_ward(
            "Nhà Phú Mỹ, nhánh Phạm Ngọc Thạch, gần KDC Hiệp Thành 3",
            intended_city="Thủ Dầu Một",
        )
        == "Phú Mỹ"
    )


def test_normalizer_keeps_hiep_thanh_kdc_landmark_as_parent_old_ward():
    rec = normalize_record({
        "source": "facebook",
        "external_id": "hiep-thanh-kdc-old-ward",
        "url": "https://facebook.com/posts/hiep-thanh-kdc-old-ward",
        "title": "Bán nhà đối diện KDC K8 Hiệp Thành",
        "description": "Ngang 4m dài 25m, thổ cư 80m2, giá 4 tỷ 5.",
        "default_area": "Thủ Dầu Một",
    })

    assert rec is not None
    assert rec["ward"] == "Hiệp Thành"
    assert rec["area"] == "Hiệp Thành"


def test_normalizer_prefers_explicit_old_ward_over_hiep_thanh_kdc_landmark():
    rec = normalize_record({
        "source": "facebook",
        "external_id": "phu-my-near-hiep-thanh-3",
        "url": "https://facebook.com/posts/phu-my-near-hiep-thanh-3",
        "title": "Nhà Phú Mỹ, nhánh Phạm Ngọc Thạch, gần KDC Hiệp Thành 3",
        "description": "Diện tích 5x20, thổ cư 60m2, giá 2 tỷ 5.",
        "default_area": "Thủ Dầu Một",
    })

    assert rec is not None
    assert rec["ward"] == "Phú Mỹ"
    assert rec["area"] == "Phú Mỹ"


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


def test_match_ward_prefers_tuong_binh_hiep_before_hiep_thanh_collision():
    tuong_binh_hiep = "T\u01b0\u01a1ng B\u00ecnh Hi\u1ec7p"
    title = (
        "B\u00e1n \u0111\u1ea5t 593m\u00b2 2.28 t\u1ef7 t\u1ea1i Ph\u01b0\u1eddng "
        "T\u01b0\u01a1ng B\u00ecnh Hi\u1ec7p Th\u00e0nh ph\u1ed1 Th\u1ee7 D\u1ea7u M\u1ed9t"
    )

    assert match_ward(title, intended_city="Th\u1ee7 D\u1ea7u M\u1ed9t") == tuong_binh_hiep
    assert (
        match_ward(
            "Ban dat tai Phuong Tuong Binh Hiep Thanh pho Thu Dau Mot",
            intended_city="Th\u1ee7 D\u1ea7u M\u1ed9t",
        )
        == tuong_binh_hiep
    )

    rec = normalize_record({
        "source": "guland",
        "external_id": "tuong-binh-hiep-hiep-thanh-collision",
        "url": "https://guland.vn/post/phuong-tuong-binh-hiep-thanh-pho-thu-dau-mot",
        "title": title,
        "description": "B\u00e1n l\u00f4 \u0111\u1ea5t ph\u01b0\u1eddng t\u01b0\u01a1ng b\u00ecnh hi\u1ec7p TPTDM. M\u1eb7t ti\u1ec1n DX149.",
        "address": (
            "Ph\u01b0\u1eddng Ch\u00e1nh Hi\u1ec7p, TP. H\u1ed3 Ch\u00ed Minh (M\u1edbi)\n"
            "Ph\u01b0\u1eddng T\u01b0\u01a1ng B\u00ecnh Hi\u1ec7p, Th\u00e0nh ph\u1ed1 Th\u1ee7 D\u1ea7u M\u1ed9t, B\u00ecnh D\u01b0\u01a1ng"
        ),
        "ward": tuong_binh_hiep,
        "area_m2": 593,
        "price_ty": 2.28,
    })
    assert rec is not None
    assert rec["ward"] == tuong_binh_hiep
    assert rec["area"] == tuong_binh_hiep


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


def test_normalizer_uses_explicit_ward_even_when_profile_city_is_wrong():
    hoa_loi = normalize_record({
        "source": "facebook",
        "external_id": "wrong-profile-hoa-loi",
        "url": "https://www.facebook.com/example/posts/hoa-loi",
        "default_area": "Thủ Dầu Một",
        "title": "P Hòa Lợi TP HCM, DT 6,2x22m thổ cư 60m2",
        "description": "Giá 1ty, đường nhựa kinh doanh.",
    })
    assert hoa_loi is not None
    assert hoa_loi["ward"] == "Hòa Lợi"

    tan_dinh = normalize_record({
        "source": "facebook",
        "external_id": "wrong-profile-tan-dinh",
        "url": "https://www.facebook.com/example/posts/tan-dinh",
        "default_area": "Thủ Dầu Một",
        "title": "Đất Tân Định gần Đại Nam 5x20m",
        "description": "Thổ cư 75m2, giá 1ty6.",
    })
    assert tan_dinh is not None
    assert tan_dinh["ward"] == "Tân Định"

    dinh_hoa = normalize_record({
        "source": "facebook",
        "external_id": "wrong-profile-dinh-hoa",
        "url": "https://www.facebook.com/example/posts/dinh-hoa",
        "default_area": "Bến Cát",
        "title": "Nhà cấp 4 Định Hòa kế bên trường tiểu học",
        "description": "DT 7x17 thổ cư 60m, giá 1 tỷ 780.",
    })
    assert dinh_hoa is not None
    assert dinh_hoa["ward"] == "Định Hòa"


def test_normalizer_prefers_reported_total_area_over_dimension_product_for_all_sources():
    rec = normalize_record({
        "source": "guland",
        "external_id": "reported-area-wins",
        "url": "https://guland.vn/post/reported-area-wins",
        "title": "Đất Phú Hoà nhựa oto 4m",
        "description": "Dt 6*21=100m (tc 60m2) Tây Nam",
        "ward": "Phú Hòa",
        "area_m2": 100.0,
        "price_ty": 2.05,
    })
    assert rec is not None
    assert rec["area_m2"] == 100.0
    assert rec["frontage_m"] == 6.0
    assert rec["depth_m"] == 21.0

    rec2 = normalize_record({
        "source": "guland",
        "external_id": "reported-area-from-text",
        "url": "https://guland.vn/post/reported-area-from-text",
        "title": "Nhà 1 trệt 2 lầu",
        "description": "Dt 11,7*18,6=165m (tc 124,7m2) Tây Bắc",
        "ward": "Phú Hòa",
        "area_m2": 217.6,
        "price_ty": 5.55,
    })
    assert rec2 is not None
    assert rec2["area_m2"] == 165.0
    assert rec2["property_type"] == "nha_dat"


def test_normalizer_does_not_let_generic_source_road_type_override_alley_text():
    rec = normalize_record({
        "source": "guland",
        "external_id": "raw-road-type-too-broad",
        "url": "https://guland.vn/post/raw-road-type-too-broad",
        "title": "Đất Chánh Nghĩa 100m2",
        "description": "Hẻm Bùi Quốc Khánh. Đường ô tô. Diện tích 5x20 thổ cư 80m.",
        "address": "Phường Chánh Nghĩa, Thủ Dầu Một",
        "road_type_raw": "Đường nhựa",
        "ward": "Chánh Nghĩa",
        "area_m2": 100.0,
        "price_ty": 1.9,
    })
    assert rec is not None
    assert rec["road_tier"] == 3


def _post_merger_location_record(title, description="", default_area="Thủ Dầu Một"):
    return normalize_record({
        "source": "facebook",
        "external_id": f"post-merger-{abs(hash(title))}",
        "url": f"https://www.facebook.com/broker/posts/{abs(hash(title))}",
        "default_area": default_area,
        "title": title,
        "description": description or "DT 5x30 thổ cư 150m, giá 2 tỷ 5",
        "area_m2": 150,
        "price_ty": 2.5,
    })


def test_normalizer_uses_khu_pho_evidence_inside_new_binh_duong_ward():
    cases = [
        ("KP.Phú Mỹ P.Bình Dương TP HCM", "Phú Mỹ"),
        ("KP Hòa Phú 2, P.Bình Dương TP HCM", "Hòa Phú"),
        ("KP Phú Tân 1, P.Bình Dương", "Phú Tân"),
        ("KP Phú Bưng, P.Bình Dương", "Phú Chánh"),
        ("KP Phú Trung, P.Bình Dương", "Phú Chánh"),
        ("KP Chánh Long, P.Bình Dương", "Phú Chánh"),
    ]

    for title, expected_ward in cases:
        rec = _post_merger_location_record(title)
        assert rec is not None
        assert rec["ward"] == expected_ward
        assert rec["area"] == expected_ward


def test_normalizer_keeps_broad_new_binh_duong_ward_out_of_old_segments():
    rec = _post_merger_location_record("P.Bình Dương TP HCM")

    assert rec is not None
    assert rec["ward"] is None
    assert rec["area"] == "Thủ Dầu Một"


def test_normalizer_prefers_old_tan_dinh_evidence_over_new_hoa_loi_ward():
    rec = _post_merger_location_record(
        "KP2 Tân Định cũ nay thuộc phường Hòa Lợi TPHCM",
        default_area="Bến Cát",
    )

    assert rec is not None
    assert rec["ward"] == "Tân Định"
    assert rec["area"] == "Tân Định"


def test_normalizer_uses_hoa_loi_khu_pho_evidence_under_new_hoa_loi_ward():
    rec = _post_merger_location_record(
        "KP3 Hòa Lợi TPHCM",
        default_area="Bến Cát",
    )

    assert rec is not None
    assert rec["ward"] == "Hòa Lợi"
    assert rec["area"] == "Hòa Lợi"


def test_normalizer_maps_tdc_phu_chanh_to_old_phu_tan_segment():
    cases = [
        ("Duong so 110B TDC Phu Chanh D, KP Phu Tan, P Binh Duong TP HCM", "Ph\u00fa T\u00e2n"),
        ("Duong so 3 TDC Phu Chanh B, KP Hoa Phu, P Binh Duong TP HCM", "Ph\u00fa T\u00e2n"),
        ("KP Phu Nghi, P Hoa Loi TP HCM, gan nga 3 Phu Hoa", "H\u00f2a L\u1ee3i"),
    ]

    for title, expected_ward in cases:
        rec = _post_merger_location_record(title, default_area="B\u1ebfn C\u00e1t")
        assert rec is not None
        assert rec["ward"] == expected_ward
        assert rec["area"] == expected_ward


def test_normalizer_keeps_broad_new_chanh_hiep_ward_out_of_old_segments():
    rec = _post_merger_location_record("Chánh Hiệp TPHCM")

    assert rec is not None
    assert rec["ward"] is None
    assert rec["area"] == "Thủ Dầu Một"


def test_normalizer_uses_dx071_dx072_chanh_hiep_as_dinh_hoa_weak_evidence():
    rec = _post_merger_location_record("Đất đường DX071 phường Chánh Hiệp TPHCM")

    assert rec is not None
    assert rec["ward"] == "Định Hòa"
    assert rec["area"] == "Định Hòa"

    stronger_old_ward = _post_merger_location_record(
        "Đất Tương Bình Hiệp phường Chánh Hiệp TPHCM đường DX072",
    )
    assert stronger_old_ward is not None
    assert stronger_old_ward["ward"] == "Tương Bình Hiệp"
    assert stronger_old_ward["area"] == "Tương Bình Hiệp"


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
    dinh_hoa_large_land_title = "B\u00e1n \u0111\u1ea5t \u0110\u1ecbnh Ho\u00e0 th\u00edch h\u1ee3p x\u00e2y dinh th\u1ef1 bi\u1ec7t th\u1ef1 v\u01b0\u1eddn, kinh doanh"
    dinh_hoa_large_land_desc = (
        "B\u00e1n \u0111\u1ea5t \u0110\u1ecbnh Ho\u00e0 th\u00edch h\u1ee3p x\u00e2y dinh th\u1ef1 bi\u1ec7t th\u1ef1 v\u01b0\u1eddn, "
        "kinh doanh c\u0103n h\u1ed9 cao c\u1ea5p. Di\u1ec7n t\u00edch 1.750 m\u00b2. "
        "B\u00e1n \u0111\u1ea5t nh\u00e1nh \u0110X 70 \u0110\u1ecbnh Ho\u00e0. DT 70 x 25 ch\u01b0a th\u1ed5 c\u01b0."
    )
    assert classify_property_type(
        dinh_hoa_large_land_title,
        dinh_hoa_large_land_desc,
        1750,
        price_per_m2=8.57,
        url_hint="chung_cu",
    ) == "dat_nen"
    assert classify_property_type(
        dinh_hoa_large_land_title,
        dinh_hoa_large_land_desc,
        1750,
        price_per_m2=8.57,
    ) == "dat_nen"

    # Hard vườn
    assert classify_property_type("Đất vườn Tân An", "cây ăn trái", 2000) == "dat_nen"
    # Hard nhà
    assert classify_property_type("Bán nhà 3 tầng", "nhà 3 tầng có sân thượng") == "nha_dat"
    # Area >=500m² no nhà → vườn
    assert classify_property_type("Đất Tân An giá tốt", "đất đẹp", 800) == "dat_nen"
    # Default dat_nen
    assert classify_property_type("Đất nền Tân An", "đất phân lô kdc", 100) == "dat_nen"
    # Broker service boilerplate is not proof of an existing house on the lot.
    assert classify_property_type(
        "Bán đất 95m² 1.75 tỷ tại Phường Tân An Thành phố Thủ Dầu Một",
        "Hotline: 0986694438. Ký Gửi - Mua Bán: Bất Động Sản. Xây Dựng Nhà Ở Trọn Gói.",
        95,
        price_per_m2=18.42,
    ) == "dat_nen"
    fast_sale_title = (
        "\U0001f525\U0001f525@Giảm giá bán nhanh . Hàng Hiếm Giá rẻ a e ơi \n\n"
        "Đất Định Hoà Nhánh DX72 Dân Cư Đông\n"
        "- Giá : 1ty5 b"
    )
    fast_sale_desc = (
        "\U0001f525\U0001f525@Giảm giá bán nhanh . Hàng Hiếm Giá rẻ a e ơi \n\n"
        "Đất Định Hoà Nhánh DX72 Dân Cư Đông\n"
        "- Giá : 1ty5 bớt lộc \n"
        "- Dien tich : 4 * 30 = 120m2 , thổ cư : 60m2 đường bê tông 4m oto chạy vi vu\n"
        "- Mua xây nhà ở đẹp\n"
        "Lh 0987554839 xem đất Gc"
    )
    assert classify_property_type(
        fast_sale_title,
        fast_sale_desc,
        120,
        tho_cu_m2=60,
        price_per_m2=12.5,
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
    assert classify_property_type(
        "\u0110\u1ea5t thu\u1ed9c T\u00e1i \u0110\u1ecbnh C\u01b0 Ch\u00e1nh M\u1ef9, Th\u1ee7 D\u1ea7u M\u1ed9t",
        (
            "\u0110\u1ed1i di\u1ec7n khu \u0111\u00f4 th\u1ecb sinh th\u00e1i HUD, n\u01a1i c\u00f3 c\u00e1c block chung c\u01b0, "
            "nh\u00e0 \u1edf li\u1ec1n k\u1ec1, bi\u1ec7t th\u1ef1 ven s\u00f4ng. "
            "C\u00f3 3 l\u00f4 li\u1ec1n k\u1ec1; di\u1ec7n t\u00edch m\u1ed7i l\u00f4 5x20; th\u1ed5 c\u01b0 100%."
        ),
        100,
        price_per_m2=26.5,
    ) == "dat_nen"


def test_classify_property_type_treats_land_with_bonus_house_as_land():
    assert classify_property_type(
        "BÁN ĐẤT TẶNG NHÀ - KDC TÂN AN",
        "Diện tích 5x30m, thổ cư 100%, hiện trạng có nhà cấp 4 đang cho thuê",
        150,
        150,
    ) == "dat_nen"
    assert classify_property_type(
        "Bán đất Phú Lợi tặng nhà cấp 4",
        "Đất lô góc 2 mặt tiền, giá rẻ ngang đất",
        120,
        60,
    ) == "dat_nen"
    assert classify_property_type(
        "Bán lô đất tặng GPXD",
        "Đất nền xây tự do, tặng giấy phép xây dựng 1 trệt 2 lầu",
        100,
        100,
    ) == "dat_nen"
    assert classify_property_type(
        "Bán nhà cấp 4 Hiệp An",
        "Nhà có 2 phòng ngủ, bếp, sân ô tô",
        80,
        60,
    ) == "nha_dat"


def test_classify_property_type_does_not_confuse_nha_trong_with_nha_tro():
    assert classify_property_type(
        "Nhà trong KDC Hiệp Thành 1",
        "Công năng nhà gồm phòng khách, bếp, 2 phòng ngủ. Diện tích 5x15, thổ cư full.",
        75,
        75,
    ) == "nha_dat"


def test_classify_property_type_treats_xem_nha_listing_as_house():
    assert classify_property_type(
        "Giảm bán nhanh mặt tiền đường nhựa nhà Phú Mỹ",
        "Đường nhựa 6m thông tứ hướng, diện tích 5x28 thổ cư 100%, đang vay ngân hàng, lh xem nhà.",
        140,
        140,
        price_per_m2=22.14,
    ) == "nha_dat"


def test_classify_property_type_ignores_buildability_storey_phrase_for_land():
    assert classify_property_type(
        "\u0110\u1ea5t \u0111\u01b0\u1eddng N1 khu H\u01b0ng Ph\u00e1t An \u0110i\u1ec1n",
        "Di\u1ec7n t\u00edch 5x16 th\u1ed5 c\u01b0 full. X\u00e2y d\u1ef1ng 1 tr\u1ec7t 1 l\u1ea7u, h\u1ea1 t\u1ea7ng ho\u00e0n thi\u1ec7n, d\u00e2n c\u01b0 v\u00e0 nh\u00e0 \u1edf xung quanh \u0111\u00f4ng.",
        80,
        80,
        price_per_m2=13.75,
    ) == "dat_nen"


def test_classify_property_type_keeps_land_when_house_words_are_only_context_ascii():
    assert classify_property_type(
        "Dat Phu Hoa, Thu Dau Mot",
        "Duong nhua 6m thong, vi tri toan nha lau, biet thu. Co 2 lo dong gia, dien tich 4x19 tho cu 60.",
        76,
        60,
        price_per_m2=36.18,
    ) == "dat_nen"
    assert classify_property_type(
        "DAT HEM HUYNH VAN LUY - CACH HVL 30M - GIA 2 TY 999",
        "Dien tich 5.5x24m - TC 60m2. Dat vuong vuc, khu dan cu hien huu, khong quy hoach, thich hop xay nha o, biet thu mini hoac dau tu lau dai.",
        132,
        60,
        price_per_m2=22.72,
    ) == "dat_nen"
    assert classify_property_type(
        "DAT DX95 - VI TRI DEP KINH DOANH - GIA 1 TY 9XX",
        "Dien tich 7.1x15m - TC 50m2. Vi tri dep, de thiet ke nha o, cua hang hoac van phong nho. #DatKinhDoanh #DatThoCu #BinhDuong",
        106.5,
        50,
        price_per_m2=17.84,
    ) == "dat_nen"


def test_classify_property_type_merges_garden_land_into_land():
    assert classify_property_type(
        "Bán đất vườn Tân An 1200m2",
        "Đất cây lâu năm, chưa có thổ cư, đường xe hơi.",
        1200,
        0,
        price_per_m2=5.0,
    ) == "dat_nen"
    assert classify_property_type(
        "Bán đất CLN diện tích lớn",
        "Đất nông nghiệp 2000m2 phù hợp làm nhà vườn.",
        2000,
        None,
        price_per_m2=4.5,
        raw_source_label="dat_vuon",
        url_hint="dat",
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
