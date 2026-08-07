from cleansing.normalizer import match_ward, normalize_record


def _raw(text: str) -> dict:
    return {
        "source": "facebook",
        "title": text,
        "description": text,
        "url": "https://www.facebook.com/test/posts/1",
        "price_ty": 2.5,
        "area_m2": 60,
    }


def test_match_ward_thuan_an_legacy_wards():
    assert match_ward("Bán đất đường An Phú 36, Thuận An, Bình Dương cũ") == "An Phú"
    assert match_ward("Tái định cư An Thạnh gần ngã tư Hòa Lân, Quốc lộ 13") == "An Thạnh"
    assert match_ward("Đất phường Bình Hoà, TP HCM") == "Bình Hòa"
    assert match_ward("KDC Thuận Giao, Tp Thuận An") == "Thuận Giao"


def test_match_ward_di_an_legacy_wards():
    assert match_ward("Bán đất Tân Đông Hiệp Dĩ An Bình Dương") == "Tân Đông Hiệp"
    assert match_ward("Nhà gần BigC Dĩ An, sổ hồng riêng") == "Dĩ An"
    assert match_ward("Đất Đông Hòa gần làng đại học") == "Đông Hòa"


def test_normalize_record_keeps_thuan_an_ward_for_public_city_filter():
    rec = normalize_record(_raw("Bán đất đường An Phú 36, Thuận An, Bình Dương cũ. DT 64m2 giá 2 tỷ 6"))
    assert rec["ward"] == "An Phú"
    assert rec["area"] == "An Phú"


def test_normalize_record_keeps_di_an_ward_for_public_city_filter():
    rec = normalize_record(_raw("Bán đất Tân Đông Hiệp, Dĩ An, Bình Dương. DT 80m2 giá 3 tỷ"))
    assert rec["ward"] == "Tân Đông Hiệp"
    assert rec["area"] == "Tân Đông Hiệp"



def test_match_ward_tan_uyen_legacy_wards():
    assert match_ward("Bán đất Uyên Hưng Tân Uyên m2 giá tỷ sổ riêng") == "Uyên Hưng"
    assert match_ward("Đất Tân Phước Khánh gần chợ Tân Phước Khánh") == "Tân Phước Khánh"
    assert match_ward("Bán đất Thái Hòa, Tân Uyên, Bình Dương cũ") == "Thái Hòa"
    assert match_ward("Đất Bạch Đằng cù lao Tân Uyên giá diện tích") == "Bạch Đằng"


def test_normalize_record_keeps_tan_uyen_ward_for_public_city_filter():
    rec = normalize_record(_raw("Bán đất Uyên Hưng Tân Uyên, DT 100m2 giá 3 tỷ"))
    assert rec["ward"] == "Uyên Hưng"
    assert rec["area"] == "Uyên Hưng"
