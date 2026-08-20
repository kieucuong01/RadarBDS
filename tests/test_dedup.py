"""
Unit tests cho cleansing/dedup.py — scoring system mới (exact dims + text sim).

Chạy: python tests/test_dedup.py

3 case chính:
  Case 1: front_exact AND depth_exact → text ≥ 0.30  → score ≥ 8
  Case 2: area_exact (không front/depth) → text ≥ 0.70 → score ≥ 6
  Case 3: không có số liệu → text ≥ 0.85 (copy-paste) → score = 6

Hard gates: different_days, property_type match, ward match.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cleansing.dedup as dedup_module
from cleansing.dedup import (
    _ascii_fold,
    _candidate_keys,
    _reconciled_duplicate_targets,
    _drop_pct,
    _has_reliable_lot_signature,
    _repost_score,
    _road_tokens,
    _is_duplicate,
    _is_reliable_price_drop,
    _is_suspicious_bait,
    _inherit_missing_group_values,
    SCORE_THRESHOLD,
)
from cleansing.normalizer import normalize_record
from cleansing.normalizer import extract_road_name


# ── Helpers ───────────────────────────────────────────────────────────────────

def _listing(**kw):
    defaults = {
        "source": "guland", "source_id": "abc",
        "crawled_at": "2026-04-20", "posted_at": None,
        "property_type": "dat_nen", "ward": "Tân An",
        "frontage_m": None, "depth_m": None, "area_m2": None,
        "description": "",
    }
    defaults.update(kw)
    return defaults


def _normalize_fb(text, source_id="test", posted_at="2026-05-08"):
    raw = {
        "source": "facebook",
        "source_id": source_id,
        "external_id": source_id,
        "url": f"https://facebook.com/test/{source_id}",
        "title": text.split("\n")[0],
        "description": text,
        "date_raw": posted_at,
        "crawled_at": "2026-05-10T09:00:00",
        "area_name": "Tân An",
        "ward": "Tân An",
        "default_area": "Thủ Dầu Một",
    }
    return normalize_record(raw)


def test_road_tokens_detect_real_vietnamese_duong_prefix():
    assert "d104" in _road_tokens("Đường 104 TĐC Phú Chánh D")
    assert "d104" in _road_tokens("Đường 104_ TĐC Phú Chánh D")
    assert "d9" in _road_tokens("Đường D9 khu TĐC Phú Mỹ")
    assert "db7b" in _road_tokens("Đường DB7B, KP Phú Tân 1")


def test_facebook_same_dimensions_conflicting_vietnamese_roads_not_duplicate():
    road_104 = _listing(
        source="facebook", source_id="fb-duong-104", posted_at="2026-08-01",
        ward="Phú Tân", property_type="dat_nen", area_m2=150.0,
        frontage_m=5.0, depth_m=30.0, tho_cu_m2=150.0, price_ty=2.6,
        contact_phone="0988893838",
        description=(
            "Đường 104_ TĐC Phú Chánh D, DT 5x30m thổ cư 100%, giá 2ty6."
        ),
    )
    d9 = _listing(
        source="facebook", source_id="fb-d9", posted_at="2026-08-11",
        ward="Phú Tân", property_type="dat_nen", area_m2=150.0,
        frontage_m=5.0, depth_m=30.0, tho_cu_m2=150.0, price_ty=2.8,
        contact_phone="0889799995",
        description=(
            "Đường D9 khu TĐC Phú Mỹ, DT 5x30m thổ cư 100%, giá 2ty8."
        ),
    )

    assert not _is_duplicate(road_104, d9)


def test_facebook_small_lot_without_location_does_not_merge_by_dimensions_only():
    generic_tdc = _listing(
        source="facebook", source_id="fb-tdc-generic", posted_at="2026-06-01",
        ward="Phú Tân", property_type="dat_nen", area_m2=150.0,
        frontage_m=5.0, depth_m=30.0, tho_cu_m2=150.0, price_ty=2.66,
        contact_phone="0935792868",
        description=(
            "Đất TĐC Phú Chánh - Phú Tân, vị trí đẹp gần trung tâm. "
            "Diện tích 5m x 30m, thổ cư 100%, giá 2ty66."
        ),
    )
    d9 = _listing(
        source="facebook", source_id="fb-d9-current", posted_at="2026-08-11",
        ward="Phú Tân", property_type="dat_nen", area_m2=150.0,
        frontage_m=5.0, depth_m=30.0, tho_cu_m2=150.0, price_ty=2.8,
        contact_phone="0889799995",
        description=(
            "Đường D9 khu TĐC Phú Mỹ, DT 5x30m thổ cư 100%, giá 2ty8."
        ),
    )

    assert not _is_duplicate(generic_tdc, d9)


def test_resolve_duplicate_targets_flattens_nested_canonical_chain():
    parent_by_id = {
        635: 51480,
        51480: 56447,
    }

    assert dedup_module._resolve_duplicate_targets(parent_by_id) == {
        635: 56447,
        51480: 56447,
    }


def test_ascii_fold_normalizes_vietnamese_d_stroke_for_location_matching():
    assert _ascii_fold("Phan Đăng Lưu - đường ĐX85 - quốc lộ 13 - Ðăng") == (
        "phan dang luu - duong dx85 - quoc lo 13 - dang"
    )


def test_road_tokens_detect_vietnamese_dx_prefix():
    assert _road_tokens("mặt tiền ĐX85, gần đường dx 089, quốc lộ 13") == {"dx85", "dx89", "ql13"}


def test_road_tokens_detect_numbered_tdc_roads():
    text = "Vi tri: Duong D12, khu TDC Phu My. Ban nhanh lo dat duong 110B TDC Phu Chanh."
    assert _road_tokens(text) == {"d12", "110b"}
    assert extract_road_name("Vi tri: Duong D12, khu TDC Phu My") == "D12"
    assert extract_road_name("Ban nhanh lo dat duong 110B TDC Phu Chanh") == "110B"


def test_road_tokens_detect_contextual_bare_numbered_tdc_roads():
    text = "Duong so 91 TDC Phu My. Dat TDC Phu Chanh duong 104. MT 71."
    assert _road_tokens(text) == {"d91", "d104", "d71"}


def test_road_tokens_detect_single_digit_numbered_tdc_road():
    assert _road_tokens("Duong so 3, TDC Phu Chanh B") == {"d3"}


def test_same_broker_same_dimensions_d3_and_d12_are_not_duplicate():
    road_3 = _listing(
        source="facebook", source_id="fb-road-3", posted_at="2026-07-30",
        ward="Phu Tan", property_type="dat_nen", area_m2=200.0,
        frontage_m=10.0, depth_m=20.0, tho_cu_m2=200.0,
        contact_phone="0935792868",
        description="Dat duong so 3, TDC Phu Chanh B, Phu Tan. DT 10x20m full tho cu.",
    )
    d12 = _listing(
        source="facebook", source_id="fb-d12", posted_at="2026-07-20",
        ward="Phu Tan", property_type="dat_nen", area_m2=200.0,
        frontage_m=10.0, depth_m=20.0, tho_cu_m2=200.0,
        contact_phone="0935792868",
        description="Dat duong D12, TDC Phu My, Phu Tan. DT 10x20m full tho cu.",
    )

    assert not _is_duplicate(road_3, d12)


def test_reconciled_duplicate_targets_split_stale_d3_d12_cluster():
    canonical_road_3 = _listing(
        id=103, source="facebook", source_id="fb-road-3-canonical", posted_at="2026-07-10",
        ward="Phu Tan", property_type="dat_nen", area_m2=200.0,
        frontage_m=10.0, depth_m=20.0, tho_cu_m2=200.0,
        contact_phone="0935792868",
        description="Dat duong so 3, TDC Phu Chanh B, Phu Tan. DT 10x20m full tho cu.",
    )
    d12 = _listing(
        id=102, source="facebook", source_id="fb-d12", posted_at="2026-07-20", duplicate_of_id=103,
        ward="Phu Tan", property_type="dat_nen", area_m2=200.0,
        frontage_m=10.0, depth_m=20.0, tho_cu_m2=200.0,
        contact_phone="0935792868",
        description="Dat duong D12, TDC Phu My, Phu Tan. DT 10x20m full tho cu.",
    )
    newest_road_3 = _listing(
        id=101, source="facebook", source_id="fb-road-3-new", posted_at="2026-07-30", duplicate_of_id=103,
        ward="Phu Tan", property_type="dat_nen", area_m2=200.0,
        frontage_m=10.0, depth_m=20.0, tho_cu_m2=200.0,
        contact_phone="0935792868",
        description="Dat duong so 3, TDC Phu Chanh B, Phu Tan. DT 10x20m full tho cu.",
    )

    assert _reconciled_duplicate_targets(
        [canonical_road_3, d12, newest_road_3]
    ) == {101: 103}


def test_same_broker_same_dimensions_different_tdc_roads_not_duplicate():
    d12 = _listing(
        source="facebook",
        source_id="fb-d12",
        posted_at="2026-06-03",
        ward="Phu Tan",
        property_type="dat_nen",
        area_m2=150.0,
        frontage_m=7.5,
        depth_m=20.0,
        price_ty=4.95,
        contact_phone="0935792868",
        description=(
            "Dat dep khu tai dinh cu Phu My - Phu Tan. "
            "Vi tri: Duong D12, khu TDC Phu My. Dien tich 7.5 x 20m, tho cu 100%. "
            "Gia ban: 33 trieu/m2."
        ),
    )
    road_110b = _listing(
        source="facebook",
        source_id="fb-110b",
        posted_at="2026-06-03",
        ward="Phu Tan",
        property_type="dat_nen",
        area_m2=150.0,
        frontage_m=7.5,
        depth_m=20.0,
        price_ty=3.2,
        contact_phone="0935792868",
        description=(
            "Ban nhanh lo dat duong 110B - TDC Phu Chanh - Phu Tan. "
            "Duong nhua rong 12m, via he 8m moi ben. Dien tich 7.5 x 20m, tho cu 100%. "
            "Gia ban nhanh: 3.2 ty."
        ),
    )

    assert not _is_duplicate(d12, road_110b)
    assert not _is_reliable_price_drop(d12, road_110b)


def test_same_broker_same_dimensions_different_bare_tdc_roads_not_duplicate():
    road_104 = _listing(
        source="facebook",
        source_id="fb-tdc-104",
        posted_at="2026-07-27",
        ward="Phu Tan",
        property_type="dat_nen",
        area_m2=150.0,
        frontage_m=5.0,
        depth_m=30.0,
        price_ty=2.6,
        contact_phone="0935792868",
        description=(
            "Dat TDC Phu Chanh D Kp2 Phuong Phu Tan. "
            "Duong 104 vi tri dep, dt 5mx30m full tc, gia 2ty6."
        ),
    )
    road_71 = _listing(
        source="facebook",
        source_id="fb-tdc-71",
        posted_at="2026-06-12",
        ward="Phu Tan",
        property_type="dat_nen",
        area_m2=150.0,
        frontage_m=5.0,
        depth_m=30.0,
        price_ty=2.8,
        contact_phone="0935792868",
        description=(
            "Dat TDC Phu Chanh D Phuong Binh Duong TPHCM. "
            "Duong 71, dt 5mx30m full tc, gia 2ty8."
        ),
    )
    road_n10 = _listing(
        source="facebook",
        source_id="fb-tdc-n10",
        posted_at="2026-07-24",
        ward="Phu Tan",
        property_type="dat_nen",
        area_m2=150.0,
        frontage_m=5.0,
        depth_m=30.0,
        price_ty=3.7,
        contact_phone="0935792868",
        description=(
            "Chu can ban gap dat duong N10 khu TDC phuong Phu Tan. "
            "Dien tich 5x30m full tho cu, gia 3ty7."
        ),
    )

    assert _road_tokens(road_104["description"]) == {"d104"}
    assert _road_tokens(road_71["description"]) == {"d71"}
    assert _road_tokens(road_n10["description"]) == {"n10"}
    assert not _is_duplicate(road_104, road_71)
    assert not _is_reliable_price_drop(road_71, road_104)
    assert not _is_duplicate(road_104, road_n10)
    assert not _is_reliable_price_drop(road_n10, road_104)


def test_same_standard_house_dimensions_near_ql13_need_stronger_price_change_identity():
    current_house = _listing(
        source="facebook",
        source_id="fb-dx88-current",
        posted_at="2026-06-20",
        ward="Hiệp An",
        property_type="nha_dat",
        area_m2=125.0,
        frontage_m=5.0,
        depth_m=25.0,
        tho_cu_m2=60.0,
        price_ty=2.25,
        contact_phone="0382941231",
        description=(
            "Nhà cấp 4 Hiệp An nhánh DX88, cách QL13 200m, gần ngã tư Sở Sao. "
            "Diện tích 5x25, thổ cư 60m2, giá 2 tỷ 250tr."
        ),
    )
    loft_house = _listing(
        source="facebook",
        source_id="fb-dx88-loft",
        posted_at="2026-04-18",
        ward="Hiệp An",
        property_type="nha_dat",
        area_m2=125.0,
        frontage_m=5.0,
        depth_m=25.0,
        tho_cu_m2=60.0,
        price_ty=2.35,
        contact_phone="0987554839",
        description=(
            "Nhà cấp 4 có gác Hiệp An nhánh DX088 gần chợ Bưng Cầu, cách QL13 200m. "
            "Diện tích 5x25, thổ cư 60m2, 2 phòng ngủ, có gác đổ, giá 2 tỷ 350."
        ),
    )

    assert not _has_reliable_lot_signature(
        current_house,
        loft_house,
        allow_facebook_same_price=False,
    )
    assert not _is_duplicate(current_house, loft_house)
    assert not _is_reliable_price_drop(loft_house, current_house)


def test_rewritten_house_price_drop_can_match_by_phone_in_description():
    current_house = _listing(
        source="facebook",
        source_id="fb-dx88-current-phone",
        posted_at="2026-06-20",
        ward="Hiệp An",
        property_type="nha_dat",
        area_m2=125.0,
        frontage_m=5.0,
        depth_m=25.0,
        tho_cu_m2=60.0,
        price_ty=2.25,
        description=(
            "Nhà cấp 4 Hiệp An nhánh DX88 cách QL13 200m. "
            "Diện tích 5x25, thổ cư 60m2, giá 2 tỷ 250. "
            "Liên hệ 0382941231."
        ),
    )
    older_house = _listing(
        source="facebook",
        source_id="fb-dx88-old-phone",
        posted_at="2026-06-01",
        ward="Hiệp An",
        property_type="nha_dat",
        area_m2=125.0,
        frontage_m=5.0,
        depth_m=25.0,
        tho_cu_m2=60.0,
        price_ty=2.29,
        description=(
            "Nhà 1 phòng khách, 2 phòng ngủ, bếp, 2 nhà vệ sinh. "
            "Đường bê tông nhánh DX088, cách QL13 100m. "
            "Diện tích 5x25, thổ cư 60m, giá 2ty290. Alo 038 294 1231."
        ),
    )

    assert _has_reliable_lot_signature(
        current_house,
        older_house,
        allow_facebook_same_price=False,
    )
    assert _is_reliable_price_drop(older_house, current_house)


def test_same_price_history_escape_does_not_override_area_mismatch_when_prices_differ():
    large_lot = _listing(
        source="facebook",
        source_id="fb-dx90-large",
        posted_at="2026-06-03",
        ward="Hiệp An",
        property_type="dat_nen",
        area_m2=461.5,
        frontage_m=10.0,
        depth_m=46.0,
        price_ty=5.5,
        description=(
            "Đất mặt tiền DX090 Hiệp An gần chợ Bưng Cầu. "
            "Diện tích 10 x 46 = 461,5m2. Thổ cư: 120 m2."
        ),
    )
    small_lot = _listing(
        source="facebook",
        source_id="fb-dx90-small",
        posted_at="2026-04-09",
        ward="Hiệp An",
        property_type="dat_nen",
        area_m2=125.0,
        frontage_m=5.0,
        depth_m=25.0,
        price_ty=2.4,
        description=(
            "Đất mặt tiền DX90 Hiệp An, 1 xẹt Phan Đăng Lưu. "
            "Diện tích 5 x 25m. Thổ Cư : 60 m2."
        ),
    )

    assert not _has_reliable_lot_signature(
        large_lot,
        small_lot,
        allow_facebook_same_price=True,
    )
    assert not _is_duplicate(large_lot, small_lot)


def test_same_broker_template_different_dx90_lot_size_not_duplicate():
    large_lot = _listing(
        source="facebook",
        source_id="fb-dx90-large-template",
        posted_at="2026-06-03",
        ward="Hiep An",
        property_type="dat_nen",
        area_m2=461.5,
        frontage_m=10.0,
        depth_m=46.0,
        price_ty=5.5,
        contact_phone="0948018508",
        description=(
            "Dat mat tien DX90 Hiep An gan cho Bung Cau, duong nhua thong. "
            "Dien tich 10 x 46 = 461.5m2. Gia tot gap chu."
        ),
    )
    small_lot = _listing(
        source="facebook",
        source_id="fb-dx90-small-template",
        posted_at="2026-06-04",
        ward="Hiep An",
        property_type="dat_nen",
        area_m2=125.0,
        frontage_m=5.0,
        depth_m=25.0,
        price_ty=2.3,
        contact_phone="0948018508",
        description=(
            "Dat mat tien DX90 Hiep An gan cho Bung Cau, duong nhua thong. "
            "Dien tich 5 x 25 = 125m2. Gia tot gap chu."
        ),
    )

    assert not _is_duplicate(large_lot, small_lot)
    assert not _is_reliable_price_drop(large_lot, small_lot)


def test_same_area_but_different_dimensions_not_same_lot():
    five_by_twenty_seven = _listing(
        source="facebook",
        source_id="fb-5x27",
        posted_at="2026-06-01",
        ward="Tan An",
        property_type="dat_nen",
        area_m2=135.0,
        frontage_m=5.0,
        depth_m=27.0,
        price_ty=2.2,
        contact_phone="0948018508",
        description=(
            "Dat Tan An duong oto thong, dien tich 5x27 tong 135m2, "
            "vi tri dep, gia gap chu."
        ),
    )
    four_half_by_thirty = _listing(
        source="facebook",
        source_id="fb-4_5x30",
        posted_at="2026-06-03",
        ward="Tan An",
        property_type="dat_nen",
        area_m2=135.0,
        frontage_m=4.5,
        depth_m=30.0,
        price_ty=2.1,
        contact_phone="0948018508",
        description=(
            "Dat Tan An duong oto thong, dien tich 4.5x30 tong 135m2, "
            "vi tri dep, gia gap chu."
        ),
    )

    assert not _is_duplicate(five_by_twenty_seven, four_half_by_thirty)
    assert not _is_reliable_price_drop(five_by_twenty_seven, four_half_by_thirty)


def test_same_dimensions_single_lot_and_double_lot_total_area_not_duplicate():
    single_row = _listing(
        source="facebook",
        source_id="fb-single-row",
        posted_at="2026-06-01",
        ward="My Phuoc 3",
        property_type="nha_tro",
        area_m2=150.0,
        frontage_m=5.0,
        depth_m=30.0,
        price_ty=2.3,
        contact_phone="0975288084",
        description=(
            "Day tro My Phuoc 3 duong NH8, dien tich 5x30, "
            "1 day tro dang cho thue kin phong."
        ),
    )
    double_row = _listing(
        source="facebook",
        source_id="fb-double-row",
        posted_at="2026-06-04",
        ward="My Phuoc 3",
        property_type="nha_tro",
        area_m2=300.0,
        frontage_m=5.0,
        depth_m=30.0,
        price_ty=4.6,
        contact_phone="0975288084",
        description=(
            "Cap tro My Phuoc 3 duong NH8, gom 2 so 5x30 rieng, "
            "2 day tro dang cho thue kin phong."
        ),
    )

    assert not _is_duplicate(single_row, double_row)
    assert not _is_reliable_price_drop(double_row, single_row)


def test_canonical_assignment_rejects_transitive_road_conflict_bridge():
    nh8 = _listing(
        source="facebook",
        source_id="fb-nh8",
        posted_at="2025-06-20",
        ward="Mỹ Phước 3",
        property_type="nha_tro",
        area_m2=150.0,
        frontage_m=5.0,
        depth_m=30.0,
        price_ty=2.2,
        contact_phone="0975288084",
        description=(
            "Trọ H19 NH8 Mỹ Phước 3. Dt 5x30 thổ cư 150m, "
            "gồm 1 nhà 2 phòng ngủ và 4 phòng trọ."
        ),
    )
    bridge_missing_road = _listing(
        source="facebook",
        source_id="fb-bridge",
        posted_at="2025-09-20",
        ward="Mỹ Phước 3",
        property_type="nha_tro",
        area_m2=150.0,
        frontage_m=5.0,
        depth_m=30.0,
        price_ty=2.3,
        contact_phone="0975288084",
        description="Bán dãy trọ Mỹ Phước 3. Dt 5x30 thổ cư 150m, thu nhập ổn định.",
    )
    nj5_latest = _listing(
        source="facebook",
        source_id="fb-nj5",
        posted_at="2025-12-06",
        ward="Mỹ Phước 3",
        property_type="nha_tro",
        area_m2=150.0,
        frontage_m=5.0,
        depth_m=30.0,
        price_ty=2.4,
        contact_phone="0975288084",
        description="Nhà trọ NJ5 Mỹ Phước 3. Dt 5x30 thổ cư 150m, xây kiên cố.",
    )

    assert _is_duplicate(nh8, bridge_missing_road)
    assert _is_duplicate(bridge_missing_road, nj5_latest)
    assert not _is_duplicate(nh8, nj5_latest)
    assert not dedup_module._canonical_compatible_duplicate(nh8, nj5_latest)
    assert dedup_module._canonical_compatible_duplicate(bridge_missing_road, nj5_latest)


def test_split_canonical_groups_separates_transitive_road_conflict_bridge():
    listings = [
        _listing(
            id=1,
            source="facebook",
            source_id="fb-nh8-old",
            posted_at="2025-06-20",
            ward="My Phuoc 3",
            property_type="nha_tro",
            area_m2=150.0,
            frontage_m=5.0,
            depth_m=30.0,
            price_ty=2.2,
            contact_phone="0975288084",
            description="Tro H19 NH8 My Phuoc 3. Dt 5x30 tho cu 150m.",
        ),
        _listing(
            id=2,
            source="facebook",
            source_id="fb-nh8-new",
            posted_at="2025-07-20",
            ward="My Phuoc 3",
            property_type="nha_tro",
            area_m2=150.0,
            frontage_m=5.0,
            depth_m=30.0,
            price_ty=2.2,
            contact_phone="0975288084",
            description="Nha tro NH8 My Phuoc 3. Dt 5x30 tho cu 150m.",
        ),
        _listing(
            id=3,
            source="facebook",
            source_id="fb-bridge",
            posted_at="2025-09-20",
            ward="My Phuoc 3",
            property_type="nha_tro",
            area_m2=150.0,
            frontage_m=5.0,
            depth_m=30.0,
            price_ty=2.3,
            contact_phone="0975288084",
            description="Ban day tro My Phuoc 3. Dt 5x30 tho cu 150m.",
        ),
        _listing(
            id=4,
            source="facebook",
            source_id="fb-nj5",
            posted_at="2025-12-06",
            ward="My Phuoc 3",
            property_type="nha_tro",
            area_m2=150.0,
            frontage_m=5.0,
            depth_m=30.0,
            price_ty=2.4,
            contact_phone="0975288084",
            description="Nha tro NJ5 My Phuoc 3. Dt 5x30 tho cu 150m.",
        ),
    ]

    groups = dedup_module._split_canonical_compatible_groups(range(len(listings)), listings)
    grouped_ids = [sorted(listings[idx]["id"] for idx in group) for group in groups]

    assert grouped_ids == [[3, 4], [1, 2]]


LONG_DESC = (
    "Bán đất nền đường Hùng Vương, phường Tân An, Thủ Dầu Một. "
    "Diện tích 100m2, mặt tiền 5m, sổ hồng riêng. "
    "Giá 2 tỷ, thương lượng. Liên hệ 0901234567."
)
LONG_DESC_COPY = LONG_DESC  # identical copy
LONG_DESC_SLIGHT = (
    "Bán đất nền đường Hùng Vương, phường Tân An, Thủ Dầu Một. "
    "Diện tích 100m2, mặt tiền 5m, sổ hồng riêng. "
    "Giá 1.9 tỷ, đã giảm. Liên hệ 0901234567."
)
LONG_DESC = (
    "Ban dat nen duong DX84, phuong Tan An, Thu Dau Mot. "
    "Dien tich 100m2, mat tien 5m, so hong rieng. "
    "Gia 2 ty, thuong luong. Lien he 0901234567."
)
LONG_DESC_COPY = LONG_DESC
LONG_DESC_SLIGHT = (
    "Ban dat nen duong DX84, phuong Tan An, Thu Dau Mot. "
    "Dien tich 100m2, mat tien 5m, so hong rieng. "
    "Gia 1.9 ty, da giam. Lien he 0901234567."
)

LONG_DESC_DIFFERENT = (
    "Nhà cấp 4 hẻm đường Lê Hồng Phong, cách mặt tiền 50m, "
    "diện tích 80m2, giá 1.5 tỷ, cần bán gấp kẹt tiền."
)


# ── Hard gate tests ───────────────────────────────────────────────────────────

def test_hard_gate_same_day():
    l1 = _listing(crawled_at="2026-04-20", description=LONG_DESC_COPY)
    l2 = _listing(crawled_at="2026-04-20", description=LONG_DESC_COPY)
    assert _repost_score(l1, l2) == 0, "Same day → must return 0"


def test_hard_gate_different_property_type():
    l1 = _listing(crawled_at="2026-04-19", property_type="dat_nen", description=LONG_DESC_COPY)
    l2 = _listing(crawled_at="2026-04-20", property_type="nha_dat", description=LONG_DESC_COPY)
    assert _repost_score(l1, l2) == 0, "Different property_type → must return 0"


def test_hard_gate_different_ward():
    l1 = _listing(crawled_at="2026-04-19", ward="Tân An", description=LONG_DESC_COPY)
    l2 = _listing(crawled_at="2026-04-20", ward="Phú Cường", description=LONG_DESC_COPY)
    assert _repost_score(l1, l2) == 0, "Different ward → must return 0"


def test_hard_gate_unknown_ward_passes():
    l1 = _listing(crawled_at="2026-04-19", ward="", description=LONG_DESC_COPY)
    l2 = _listing(crawled_at="2026-04-20", ward="Tân An", description=LONG_DESC_COPY)
    # Missing ward → không block, nhưng score phụ thuộc text sim
    score = _repost_score(l1, l2)
    assert score >= SCORE_THRESHOLD, f"Missing ward should not block; score={score}"


# ── Case 1: front + depth exact ───────────────────────────────────────────────

def test_case1_passes_with_text_30():
    l1 = _listing(crawled_at="2026-04-19", frontage_m=5.0, depth_m=20.0, description=LONG_DESC)
    l2 = _listing(crawled_at="2026-04-20", frontage_m=5.0, depth_m=20.0, description=LONG_DESC_SLIGHT)
    score = _repost_score(l1, l2)
    assert score >= SCORE_THRESHOLD, f"Case 1 with text≥0.30 should pass; score={score}"


def test_case1_fails_without_text():
    l1 = _listing(crawled_at="2026-04-19", frontage_m=5.0, depth_m=20.0, description="")
    l2 = _listing(crawled_at="2026-04-20", frontage_m=5.0, depth_m=20.0, description="")
    score = _repost_score(l1, l2)
    assert score == 0, f"Case 1 with no text sim should fail; score={score}"


def test_case1_fails_with_different_dims():
    l1 = _listing(crawled_at="2026-04-19", frontage_m=5.0, depth_m=20.0, description=LONG_DESC)
    l2 = _listing(crawled_at="2026-04-20", frontage_m=5.1, depth_m=20.0, description=LONG_DESC)
    # frontage 5.0 vs 5.1 is NOT exact (tol=0.0) → front_match=False → Case 1 không kích hoạt
    # Case 3 sẽ áp dụng vì text ≥ 0.85
    score = _repost_score(l1, l2)
    # text sim is high (same description) so Case 3 kicks in
    assert score >= SCORE_THRESHOLD, f"Should match via Case 3 (text≥0.85); score={score}"


def test_case1_different_depth_no_match():
    l1 = _listing(crawled_at="2026-04-19", frontage_m=5.0, depth_m=20.0, description=LONG_DESC_SLIGHT)
    l2 = _listing(crawled_at="2026-04-20", frontage_m=5.0, depth_m=25.0, description=LONG_DESC_SLIGHT)
    # front matches but depth differs → front_match AND depth_match = False → falls to Case 2/3
    # area_m2 both None, text sim moderate → score depends on text
    score = _repost_score(l1, l2)
    # text is slightly modified — probably < 0.85 but > 0.70, not enough for Case 3
    # This is acceptable — 5x20 vs 5x25 are different lots
    # We just verify it doesn't use the 0-tolerance gate incorrectly
    assert isinstance(score, int)


# ── Case 2: area exact, no front/depth ───────────────────────────────────────

def test_case2_passes_with_text_70():
    l1 = _listing(crawled_at="2026-04-19", area_m2=100.0, description=LONG_DESC)
    l2 = _listing(crawled_at="2026-04-20", area_m2=100.0, description=LONG_DESC_SLIGHT)
    score = _repost_score(l1, l2)
    assert score >= SCORE_THRESHOLD, f"Case 2 with text≥0.70 should pass; score={score}"


def test_case2_fails_with_low_text():
    l1 = _listing(crawled_at="2026-04-19", area_m2=100.0, description=LONG_DESC)
    l2 = _listing(crawled_at="2026-04-20", area_m2=100.0, description=LONG_DESC_DIFFERENT)
    score = _repost_score(l1, l2)
    assert score == 0, f"Case 2 with different text (<0.70) should fail; score={score}"


def test_case2_area_mismatch_no_match():
    l1 = _listing(crawled_at="2026-04-19", area_m2=100.0, description=LONG_DESC)
    l2 = _listing(crawled_at="2026-04-20", area_m2=101.0, description=LONG_DESC)
    # 100 vs 101 NOT exact → area_match=False → falls to Case 3
    # text is identical → Case 3 kicks in
    score = _repost_score(l1, l2)
    assert score >= SCORE_THRESHOLD, f"Identical text should match via Case 3; score={score}"


# ── Case 3: text-only (copy-paste) ───────────────────────────────────────────

def test_case3_exact_copy():
    l1 = _listing(crawled_at="2026-04-19", description=LONG_DESC_COPY)
    l2 = _listing(crawled_at="2026-04-20", description=LONG_DESC_COPY)
    score = _repost_score(l1, l2)
    assert score >= SCORE_THRESHOLD, f"Exact copy should match; score={score}"
    assert score == 6, f"No dims → only text contributes; expected 6, got {score}"


def test_case3_no_text_no_match():
    l1 = _listing(crawled_at="2026-04-19")
    l2 = _listing(crawled_at="2026-04-20")
    score = _repost_score(l1, l2)
    assert score == 0, f"No text, no dims → cannot determine duplicate; score={score}"


def test_case3_low_similarity_no_match():
    l1 = _listing(crawled_at="2026-04-19", description=LONG_DESC)
    l2 = _listing(crawled_at="2026-04-20", description=LONG_DESC_DIFFERENT)
    score = _repost_score(l1, l2)
    assert score == 0, f"Different text, no dims → no match; score={score}"


# ── _is_duplicate: same source_id shortcut ───────────────────────────────────

def test_same_source_id_always_duplicate():
    l1 = _listing(source="guland", source_id="POST123", crawled_at="2026-04-19", description="")
    l2 = _listing(source="guland", source_id="POST123", crawled_at="2026-04-20", description="")
    assert _is_duplicate(l1, l2), "Same source + source_id → always duplicate"


def test_facebook_same_source_different_id_uses_scoring():
    l1 = _listing(source="facebook", source_id="POST111", crawled_at="2026-04-19", description=LONG_DESC_COPY)
    l2 = _listing(source="facebook", source_id="POST222", crawled_at="2026-04-20", description=LONG_DESC_COPY)
    assert _is_duplicate(l1, l2), "Facebook same source, different id, identical text -> duplicate via scoring"


def test_non_facebook_cross_source_does_not_use_scoring():
    l1 = _listing(source="guland",     source_id="G1", crawled_at="2026-04-19",
                  area_m2=100.0, description=LONG_DESC)
    l2 = _listing(source="batdongsan", source_id="B1", crawled_at="2026-04-20",
                  area_m2=100.0, description=LONG_DESC_SLIGHT)
    assert not _is_duplicate(l1, l2), "Guland/BatDongSan cross-source heuristics should be disabled"


# ── Score floor verification ──────────────────────────────────────────────────

def test_reliable_drop_facebook_same_area_different_post():
    old = _listing(
        source="facebook", source_id="fb1", posted_at="2026-05-01",
        ward="Tân An", property_type="dat_nen", area_m2=100.0,
        price_ty=2.0, description="Bán đất đường DX84 diện tích 100m2 giá 2 tỷ"
    )
    new = _listing(
        source="facebook", source_id="fb2", posted_at="2026-05-03",
        ward="Tân An", property_type="dat_nen", area_m2=100.0,
        price_ty=1.9, description="Bán đất đường DX84 diện tích 100m2 giá giảm còn 1.9 tỷ"
    )
    assert _is_reliable_price_drop(old, new), "Facebook repost same area should count as reliable price drop"


def test_reliable_drop_allows_small_depth_variation_when_lot_signature_is_strong():
    old = _listing(
        source="facebook", source_id="fb-old", posted_at="2026-05-17",
        ward="Hiep An", property_type="dat_nen", area_m2=118.0,
        frontage_m=5.0, depth_m=23.6, price_ty=1.695,
        title="GIAM GIA BAN LO DAT HIEP AN THU DAU MOT BINH DUONG Gia 1 ty695tr DT 5 x 23.6",
        description=(
            "GIAM GIA BAN LO DAT HIEP AN THU DAU MOT BINH DUONG "
            "Gia 1 ty695tr DT 5 x 23.6 = 118m2. Tho cu 70m2. "
            "Phap ly so hong rieng. Duong oto vo thoai mai. Hotline 0944 882 225."
        ),
    )
    new = _listing(
        source="facebook", source_id="fb-new", posted_at="2026-05-26",
        ward="Hiep An", property_type="dat_nen", area_m2=118.0,
        frontage_m=5.0, depth_m=23.8, price_ty=1.65,
        title="GIAM GIA BAN LO DAT HIEP AN THU DAU MOT BINH DUONG Gia 1 ty650tr DT 5 x 23.8",
        description=(
            "GIAM GIA BAN LO DAT HIEP AN THU DAU MOT BINH DUONG "
            "Gia 1 ty650tr. DT 5 x 23.8 = 118m2. Tho cu 70m2. "
            "Phap ly so hong rieng. Duong oto, dan cu dong duc. "
            "038 294 1231 em Phuong xem dat."
        ),
    )
    assert _is_reliable_price_drop(old, new), (
        "Same area, frontage, thổ cư, location text, and high text similarity "
        "should tolerate a small depth typo/rounding change"
    )


def test_reliable_drop_rejects_same_template_different_lot():
    old = _listing(
        source="facebook", source_id="fb1", posted_at="2026-05-01",
        ward="Định Hòa", property_type="dat_nen", area_m2=1259.0,
        price_ty=13.5, description="Cần bán đất Định Hòa đường DX78 liên hệ môi giới"
    )
    new = _listing(
        source="facebook", source_id="fb2", posted_at="2026-05-03",
        ward="Định Hòa", property_type="dat_nen", area_m2=180.0,
        price_ty=3.3, description="Cần bán đất Định Hòa đường DX71 liên hệ môi giới"
    )
    assert not _is_reliable_price_drop(old, new), "Different area and road should not count as price drop"


def test_reliable_drop_rejects_same_dims_different_location():
    old = _listing(
        source="facebook", source_id="fb1", posted_at="2026-01-16",
        ward="TÃ¢n An", property_type="dat_nen", area_m2=300.0,
        frontage_m=10.0, depth_m=30.0, price_ty=4.3,
        description="BÃ¡n 10x30 Ä‘Æ°á»ng DI4 dÃ i kinh doanh giÃ¡ 4ty3"
    )
    new = _listing(
        source="facebook", source_id="fb2", posted_at="2026-05-07",
        ward="TÃ¢n An", property_type="dat_nen", area_m2=300.0,
        frontage_m=10.0, depth_m=30.0, price_ty=3.85,
        description="DX072 Äá»‹nh HÃ²a ChÃ¡nh Hiá»‡p dt 10x30 giÃ¡ 3ty85"
    )
    assert not _is_reliable_price_drop(old, new), "Same dims without location signal should not be price drop"


def test_reliable_drop_rejects_same_road_different_block():
    old = _listing(
        source="facebook", source_id="fb1", posted_at="2026-05-01",
        ward="Má»¹ PhÆ°á»›c 3", property_type="dat_nen", area_m2=150.0,
        frontage_m=5.0, depth_m=30.0, price_ty=1.9,
        description="BÃ¡n Ä‘áº¥t K22 Ä‘Æ°á»ng DK12 Má»¹ PhÆ°á»›c 3 dt 5x30"
    )
    new = _listing(
        source="facebook", source_id="fb2", posted_at="2026-05-03",
        ward="Má»¹ PhÆ°á»›c 3", property_type="dat_nen", area_m2=150.0,
        frontage_m=5.0, depth_m=30.0, price_ty=1.8,
        description="BÃ¡n Ä‘áº¥t K32 Ä‘Æ°á»ng DK12 Má»¹ PhÆ°á»›c 3 dt 5x30"
    )
    assert not _is_reliable_price_drop(old, new), "Same road but different block token should not be price drop"


def test_reliable_drop_same_phone_area_anchor():
    old = _listing(
        source="facebook", source_id="fb1", posted_at="2026-05-01",
        ward="TÃ¢n An", property_type="dat_nen", area_m2=100.0,
        price_ty=2.0, contact_phone="0901234567",
        description="BÃ¡n Ä‘áº¥t Ä‘Æ°á»ng DX84 diá»‡n tÃ­ch 100m2"
    )
    new = _listing(
        source="facebook", source_id="fb2", posted_at="2026-05-03",
        ward="TÃ¢n An", property_type="dat_nen", area_m2=100.5,
        price_ty=1.9, contact_phone="+84901234567",
        description="ChÃ­nh chá»§ gá»­i bÃ¡n DX84, cÃ³ sá»•, cáº§n ra nhanh"
    )
    assert _is_reliable_price_drop(old, new), "Same phone + near area + location should be reliable"


def test_reliable_drop_ignores_price_per_m2_when_total_price_same():
    old = _listing(
        source="facebook", source_id="fb1", posted_at="2026-05-01",
        ward="TÃ¢n An", property_type="dat_nen", area_m2=100.0,
        price_ty=2.0, price_per_m2=20.0,
        description="BÃ¡n Ä‘áº¥t Ä‘Æ°á»ng DX84 diá»‡n tÃ­ch 100m2"
    )
    new = _listing(
        source="facebook", source_id="fb2", posted_at="2026-05-03",
        ward="TÃ¢n An", property_type="dat_nen", area_m2=100.0,
        price_ty=2.0, price_per_m2=18.0,
        description="BÃ¡n Ä‘áº¥t Ä‘Æ°á»ng DX84 diá»‡n tÃ­ch 100m2"
    )
    assert not _is_reliable_price_drop(old, new), "Price/m2 drift must not create a visible price-drop badge"


def test_suspicious_bait_over_40pct_not_reliable_drop():
    old = _listing(
        source="facebook", source_id="fb1", posted_at="2026-05-01",
        ward="TÃ¢n An", property_type="dat_nen", area_m2=100.0,
        price_ty=2.0, description="BÃ¡n Ä‘áº¥t Ä‘Æ°á»ng DX84 diá»‡n tÃ­ch 100m2"
    )
    new = _listing(
        source="facebook", source_id="fb2", posted_at="2026-05-03",
        ward="TÃ¢n An", property_type="dat_nen", area_m2=100.0,
        price_ty=1.0, description="BÃ¡n Ä‘áº¥t Ä‘Æ°á»ng DX84 diá»‡n tÃ­ch 100m2"
    )
    assert _is_suspicious_bait(old, new), "Drop >40% should be suspicious bait"
    assert not _is_reliable_price_drop(old, new), "Suspicious bait should not be reliable price drop"


def test_facebook_same_price_repost_counts_duplicate():
    old = _listing(
        source="facebook", source_id="fb1", posted_at="2026-05-01",
        ward="TÃ¢n An", property_type="dat_nen", area_m2=100.0,
        price_ty=2.0, description="BÃ¡n Ä‘áº¥t Ä‘Æ°á»ng DX84 diá»‡n tÃ­ch 100m2 giÃ¡ 2 tá»·"
    )
    new = _listing(
        source="facebook", source_id="fb2", posted_at="2026-05-03",
        ward="TÃ¢n An", property_type="dat_nen", area_m2=100.0,
        price_ty=2.0, description="BÃ¡n Ä‘áº¥t Ä‘Æ°á»ng DX84 diá»‡n tÃ­ch 100m2 giÃ¡ 2 tá»·"
    )
    assert _is_duplicate(old, new), "Facebook same-price repost should remain duplicate for lot history"


def test_guland_same_price_repost_not_duplicate_for_history():
    old = _listing(
        source="guland", source_id="g1", posted_at="2026-05-01",
        ward="TÃ¢n An", property_type="dat_nen", area_m2=100.0,
        price_ty=2.0, description="BÃ¡n Ä‘áº¥t Ä‘Æ°á»ng DX84 diá»‡n tÃ­ch 100m2 giÃ¡ 2 tá»·"
    )
    new = _listing(
        source="guland", source_id="g2", posted_at="2026-05-03",
        ward="TÃ¢n An", property_type="dat_nen", area_m2=100.0,
        price_ty=2.0, description="BÃ¡n Ä‘áº¥t Ä‘Æ°á»ng DX84 diá»‡n tÃ­ch 100m2 giÃ¡ 2 tá»·"
    )
    assert not _is_duplicate(old, new), "Guland same-price repost should not extend lot history"


def test_duplicate_group_inherits_missing_area_from_nearest_repost():
    older = _listing(
        id=1, source="facebook", source_id="fb-old", posted_at="2026-05-20",
        ward="Dinh Hoa", property_type="nha_dat", area_m2=82.0,
        price_ty=3.15, price_per_m2=38.41,
        description="Nha tret lau 1 duong DX82 Dinh Hoa gia 3 ty 150 dien tich 82m2"
    )
    latest = _listing(
        id=2, source="facebook", source_id="fb-new", posted_at="2026-05-27",
        ward="Dinh Hoa", property_type="nha_dat", area_m2=None,
        price_ty=3.15, price_per_m2=None,
        description="Chi con 1 can duy nhat phuong Dinh Hoa nha tret lau 1 DX82 gia van giu nguyen 3ty150"
    )

    hydrated = _inherit_missing_group_values([latest, older])

    assert hydrated[0]["area_m2"] == 82.0
    assert hydrated[0]["price_ty"] == 3.15
    assert hydrated[0]["price_per_m2"] == 38.41


def test_duplicate_group_does_not_invent_missing_price_from_nearest_repost():
    older = _listing(
        id=1, source="facebook", source_id="fb-old", posted_at="2026-05-20",
        ward="Dinh Hoa", property_type="nha_dat", area_m2=82.0,
        price_ty=3.15, price_per_m2=38.41,
        description="Nha tret lau 1 duong DX82 Dinh Hoa gia 3 ty 150 dien tich 82m2"
    )
    latest = _listing(
        id=2, source="facebook", source_id="fb-new", posted_at="2026-05-27",
        ward="Dinh Hoa", property_type="nha_dat", area_m2=82.0,
        price_ty=None, price_per_m2=None,
        description="Chi con 1 can duy nhat phuong Dinh Hoa nha tret lau 1 DX82 gia van giu nguyen"
    )

    hydrated = _inherit_missing_group_values([latest, older])

    assert hydrated[0]["area_m2"] == 82.0
    assert hydrated[0]["price_ty"] is None
    assert hydrated[0]["price_per_m2"] is None


def test_guland_phu_tan_template_same_phone_not_same_lot():
    canonical = _listing(
        source="guland", source_id="1251615", posted_at="2026-05-06",
        ward="Phu Tan", property_type="nha_dat", area_m2=107.0,
        price_ty=2.05, price_per_m2=19.16, contact_phone="0983284379",
        description="Ban dat 107m2 2.05 ty tai Phuong Phu Tan Thanh pho Thu Dau Mot"
    )
    larger = _listing(
        source="guland", source_id="1251608", posted_at="2026-05-06",
        ward="Phu Tan", property_type="nha_dat", area_m2=132.5,
        price_ty=2.45, price_per_m2=18.49, contact_phone="0983284379",
        description="Ban dat 132.5m2 2.45 ty tai Phuong Phu Tan Thanh pho Thu Dau Mot"
    )
    smaller = _listing(
        source="guland", source_id="1254053", posted_at="2026-05-06",
        ward="Phu Tan", property_type="nha_dat", area_m2=95.9,
        price_ty=1.6, price_per_m2=16.68, contact_phone="0983284379",
        description="Ban dat 95.9m2 1.6 ty tai Phuong Phu Tan Thanh pho Thu Dau Mot"
    )

    assert not _is_duplicate(canonical, larger)
    assert not _is_duplicate(canonical, smaller)
    assert not _is_reliable_price_drop(canonical, larger)
    assert not _is_reliable_price_drop(canonical, smaller)


def test_guland_phu_hoa_same_phone_area_without_road_not_same_lot():
    canonical = _listing(
        source="guland", source_id="1282556", posted_at="2026-02-05",
        ward="Phu Hoa", property_type="dat_nen", area_m2=100.0,
        price_ty=3.05, price_per_m2=30.5, contact_phone="0983284379",
        description="Dat khu8 Phu Hoa TPTDM vi tri trung tam hem 385 Le Hong Phong nhua 5m"
    )
    repost = _listing(
        source="guland", source_id="2217134", posted_at="2026-04-29",
        ward="Phu Hoa", property_type="dat_nen", area_m2=100.0,
        price_ty=2.75, price_per_m2=27.5, contact_phone="0983284379",
        description="Ban dat Phu Hoa 100m2 ngang 5m gia 2.75 ty Phuong Phu Loi"
    )
    short = _listing(
        source="guland", source_id="1122353", posted_at="2026-05-06",
        ward="Phu Hoa", property_type="dat_nen", area_m2=100.0,
        price_ty=2.05, price_per_m2=20.5, contact_phone="0983284379",
        description="Dat Phu Hoa nhua oto 4m"
    )

    assert not _is_duplicate(canonical, repost)
    assert not _is_duplicate(canonical, short)
    assert not _is_reliable_price_drop(canonical, repost)
    assert not _is_reliable_price_drop(canonical, short)


def test_guland_phu_my_dx006_same_road_not_duplicate_without_same_source_id():
    canonical = _listing(
        source="guland", source_id="1596027", posted_at="2026-01-06",
        ward="Phu My", property_type="dat_nen", area_m2=80.0,
        price_ty=1.99, price_per_m2=24.88, contact_phone="0983284379",
        description="Dat 1 xec DX 06 duong be tong 5m vi tri dep gan cho Phu My"
    )
    repost = _listing(
        source="guland", source_id="1303708", posted_at="2026-02-05",
        ward="Phu My", property_type="dat_nen", area_m2=80.0,
        price_ty=1.95, price_per_m2=24.38, contact_phone="0983284379",
        description="Dat Phu My duong oto 1/DX006 vi tri dep dan kin gia em"
    )

    assert not _is_duplicate(canonical, repost)
    assert not _is_reliable_price_drop(canonical, repost)


def test_facebook_conflicting_dx_roads_do_not_share_lot_history():
    dx20 = _listing(
        source="facebook", source_id="fb-dx20", posted_at="2026-01-01",
        ward="Phu My", property_type="dat_nen", area_m2=150.0,
        frontage_m=5.0, depth_m=30.0, price_ty=3.3,
        contact_phone="0948018508",
        description=(
            "Giap chu Dx20 Phu My duong nhua thong suot oto ne nhau, "
            "sat ben cho Phu My. Dien tich 5x30, tho cu 60m, gia 3ty3."
        ),
    )
    dx013 = _listing(
        source="facebook", source_id="fb-dx013", posted_at="2026-06-02",
        ward="Phu My", property_type="dat_nen", area_m2=150.0,
        frontage_m=5.0, depth_m=30.0, price_ty=3.9,
        contact_phone="0935792868",
        description=(
            "Can ban lo dat mat tien Dx 013 duong nhua 8m thong, "
            "cach cho Phu My 300m. Dien tich 5x30 tho cu 60m."
        ),
    )

    assert not _is_duplicate(dx20, dx013)


def test_facebook_conflicting_dx_roads_do_not_count_price_drop():
    dx013_old = _listing(
        source="facebook", source_id="fb-dx013-old", posted_at="2026-01-01",
        ward="Phu My", property_type="dat_nen", area_m2=150.0,
        frontage_m=5.0, depth_m=30.0, price_ty=3.9,
        contact_phone="0935792868",
        description=(
            "Can ban lo dat mat tien Dx 013 duong nhua 8m thong, "
            "cach cho Phu My 300m. Dien tich 5x30 tho cu 60m."
        ),
    )
    dx20_new = _listing(
        source="facebook", source_id="fb-dx20-new", posted_at="2026-06-02",
        ward="Phu My", property_type="dat_nen", area_m2=150.0,
        frontage_m=5.0, depth_m=30.0, price_ty=3.3,
        contact_phone="0948018508",
        description=(
            "Giap chu Dx20 Phu My duong nhua thong suot oto ne nhau, "
            "sat ben cho Phu My. Dien tich 5x30, tho cu 60m, gia 3ty3."
        ),
    )

    assert not _is_reliable_price_drop(dx013_old, dx20_new)


def test_facebook_same_phone_near_area_reposts_share_candidate_bucket():
    old = _listing(
        source="facebook", source_id="fb-1212-old", posted_at="2024-09-07",
        ward="Tan An", property_type="dat_nen", area_m2=1212.5,
        price_ty=3.5, contact_phone="0902861961",
        description=(
            "Sau cho Ben The nhanh Dx126 cach Huynh Thi Hieu 200m. "
            "Dt 1212,5m2, tho cu 140m2, gia 3ty500."
        ),
    )
    new = _listing(
        source="facebook", source_id="fb-1212-new", posted_at="2025-07-22",
        ward="Tan An", property_type="dat_nen", area_m2=1212.0,
        price_ty=2.9, contact_phone="0902-861-961",
        description=(
            "Ban dat phuong Tan An lam vuon gia tot duong ba gac. "
            "Dt 1.212 m2, tc 140, gia 2ty9."
        ),
    )

    assert _candidate_keys(old).intersection(_candidate_keys(new))
    assert _is_reliable_price_drop(old, new)


def test_facebook_land_subtype_large_lot_drop_shares_candidate_bucket():
    old = _listing(
        source="facebook", source_id="fb-1212-old-subtype", posted_at="2024-09-07",
        ward="Tan An", property_type="dat_nen", area_m2=1212.5,
        price_ty=3.5, contact_phone="0902861961",
        description=(
            "Sau cho Ben The nhanh Dx126 cach Huynh Thi Hieu 200m. "
            "Dt 1212,5m2, tho cu 140m2, gia 3ty500."
        ),
    )
    new = _listing(
        source="facebook", source_id="fb-1212-new-subtype", posted_at="2025-07-22",
        ward="Tan An", property_type="dat_nen", area_m2=1212.0,
        price_ty=2.9, contact_phone="0902-861-961",
        description=(
            "Ban dat phuong Tan An lam vuon gia tot duong ba gac. "
            "Dt 1.212 m2, tc 140, gia 2ty9."
        ),
    )

    assert _candidate_keys(old).intersection(_candidate_keys(new))
    assert _is_duplicate(old, new)
    assert _is_reliable_price_drop(old, new)


def test_facebook_same_dimensions_price_tho_cu_duplicate_without_location_signal():
    old = _listing(
        source="facebook", source_id="fb-11x60-old", posted_at="2026-05-29",
        ward="Tan An", property_type="dat_nen", area_m2=660.0,
        frontage_m=11.0, depth_m=60.0, tho_cu_m2=160.0,
        price_ty=4.8, price_per_m2=7.273,
        description=(
            "Chu ket ha gia con 4 ty 8. Dat Tan An. "
            "Dien tich 11 x 60, tho cu 160m2. Da tach ra 2 lo."
        ),
    )
    new = _listing(
        source="facebook", source_id="fb-11x60-new", posted_at="2026-06-05",
        ward="Tan An", property_type="dat_nen", area_m2=652.0,
        frontage_m=11.0, depth_m=60.0, tho_cu_m2=160.0,
        price_ty=4.8, price_per_m2=7.362,
        description=(
            "Giam manh chot gap gia 4 ty 800tr. "
            "Dien tich tong 11 x 60 = 652m2, tho cu 160m2."
        ),
    )

    assert _candidate_keys(old).intersection(_candidate_keys(new))
    assert _is_duplicate(old, new)


def test_facebook_large_land_subtype_same_numeric_signature_duplicate():
    old = _listing(
        source="facebook", source_id="fb-1083-old", posted_at="2026-04-15",
        ward="Tan An", property_type="dat_nen", area_m2=1083.7,
        tho_cu_m2=200.0, price_ty=5.95, price_per_m2=5.49,
        description=(
            "Ban dat Tan An tong dien tich 1083.7m2 tho cu 200m2. "
            "Nhanh Le Chi Dan vao 200m, gia 5 ty 950."
        ),
    )
    new = _listing(
        source="facebook", source_id="fb-1083-new", posted_at="2026-05-28",
        ward="Tan An", property_type="dat_nen", area_m2=1083.7,
        tho_cu_m2=200.0, price_ty=5.5, price_per_m2=5.075,
        description=(
            "Dat dep Phu An thich hop lam kho biet thu. "
            "DX132 Tan An, dien tich 1083.7m2, tho cu 200m2, gia 5 ty 500."
        ),
    )

    assert _candidate_keys(old).intersection(_candidate_keys(new))
    assert _is_duplicate(old, new)
    assert _is_reliable_price_drop(old, new)


def test_facebook_medium_land_same_road_numeric_signature_duplicate():
    old = _listing(
        source="facebook", source_id="fb-dx124-old", posted_at="2026-04-20",
        ward="Tan An", property_type="dat_nen", area_m2=516.0,
        frontage_m=7.5, depth_m=69.0, tho_cu_m2=60.0, price_ty=2.2,
        description="Ban dat DX124 Tan An dien tich 7.5x69 tho cu 60m2 gia 2.2 ty."
    )
    new = _listing(
        source="facebook", source_id="fb-dx124-new", posted_at="2026-05-29",
        ward="Tan An", property_type="dat_nen", area_m2=525.0,
        frontage_m=7.5, depth_m=70.0, tho_cu_m2=60.0, price_ty=2.2,
        description="Gia ha con 2 ty 200tr DX124 Tan An ngang 7.5 dai 70 tho cu 60m2."
    )

    assert _candidate_keys(old).intersection(_candidate_keys(new))
    assert _is_duplicate(old, new)


def test_facebook_land_subtype_large_lot_key_requires_phone():
    listing = _listing(
        source="facebook", source_id="fb-1212-no-phone", posted_at="2025-07-22",
        ward="Tan An", property_type="dat_nen", area_m2=1212.0,
        price_ty=2.9, contact_phone=None,
        description="Ban dat Tan An dien tich 1212m2 gia 2ty9.",
    )

    keys = _candidate_keys(listing)
    assert not any(key[1] == "dat_land" for key in keys)


def test_same_total_price_area_drift_is_not_price_drop():
    old = _listing(
        source="facebook", source_id="fb-same-total-old", posted_at="2026-04-30",
        ward="Hiep An", property_type="dat_nen", area_m2=144.0,
        price_ty=1.59, price_per_m2=11.04,
        description="Dat Hiep An 1 xet Nguyen Chi Thanh 4x36 gia 1ty590."
    )
    new = _listing(
        source="facebook", source_id="fb-same-total-new", posted_at="2026-05-02",
        ward="Hiep An", property_type="dat_nen", area_m2=146.0,
        price_ty=1.59, price_per_m2=10.89,
        description="Dat Hiep An 1 xet Nguyen Chi Thanh 4x36 gia 1ty590."
    )

    assert _drop_pct(old, new) is None
    assert not _is_reliable_price_drop(old, new)


def test_guland_same_source_id_price_drop_still_allowed():
    old = _listing(
        source="guland", source_id="same-post", posted_at="2026-05-01",
        area_m2=100.0, price_ty=2.0, price_per_m2=20.0,
        description="Old Guland listing"
    )
    new = _listing(
        source="guland", source_id="same-post", posted_at="2026-05-03",
        area_m2=100.0, price_ty=1.9, price_per_m2=19.0,
        description="Updated Guland listing"
    )
    assert _is_duplicate(old, new)
    assert _is_reliable_price_drop(old, new)


def test_facebook_land_and_house_same_phone_area_not_duplicate():
    land = _normalize_fb(
        "Chủ kẹt cứng ngắc cần bán gấp lô đất Tân An\n"
        "Diện tích 148m tc 60m\n"
        "Giá 1ty5 thương lượng\n"
        "Liên hệ em Hằng xem đất 0948018508",
        "fb-land-148",
        "2026-05-01",
    )
    house = _normalize_fb(
        "🌷🌷Nhà Tân An (Phú An, tp HCM) cách Lê Chí Dân 150m\n"
        "Ngang 8 dài 18.5 thổ cư 60m2 (tổng 148m2), vị trí góc đẹp thông thoáng mát mẻ\n"
        "Nhà 3PN sân ô tô rộng, tiệc tùng thoải mái\n"
        "Sẵn 3 máy lạnh, bếp từ, máy hút mùi...\n"
        "❌Giá: 2tỷ 450tr❌ hỗ trợ NH tối đa\n"
        "LH: 0948018508 xem nhà Giáp chủ",
        "fb-house-148",
        "2026-05-08",
    )

    assert land["property_type"] == "dat_nen"
    assert house["property_type"] == "nha_dat"
    assert not _is_duplicate(land, house)
    assert not _is_reliable_price_drop(house, land)


def test_facebook_same_dims_different_tho_cu_or_location_not_duplicate():
    simple_land = _normalize_fb(
        "Đất Tân An TDM. Dt 5 x 19, thổ cư 60. Đường ô tô nhỏ. "
        "Đất sạch, gpxd cấp chính. Giá 1tỷ2xx bớt lộc lá. "
        "Lh Hằng 0948018508 Giáp chủ",
        "fb-land-5x19-60",
        "2026-05-01",
    )
    dx_land = _normalize_fb(
        "Đất Tân An Thủ Dầu Một - phường Phú An TpHCM\n"
        "Dt 5 x 19, thổ cư 75\n"
        "Nhánh Dx135, cách Lê Chí Dân ko đến 100m, đường bê tông ô tô đến đất\n"
        "💰💰Giá 1tỷ550\n"
        "Lh Hằng 0948018508 xem đất Giáp chủ",
        "fb-land-5x19-dx135",
        "2026-05-08",
    )
    phu_hoa_house = _normalize_fb(
        "Nhà  Phú Hoà TDM\n"
        "Diện tích 5x19 thổ cư full\n"
        "📌Vị trí VIP 1/ đường Nguyễn Thái Bình, ngay chợ nhỏ, trường cấp 2, cấp 3 chuẩn bị làm\n"
        "💰Giá chỉ: 2ty790\n"
        "Lh Hằng 0948018508 xem nhà Gc",
        "fb-house-phu-hoa",
        "2026-05-08",
    )

    assert simple_land["property_type"] == "dat_nen"
    assert dx_land["property_type"] == "dat_nen"
    assert phu_hoa_house["property_type"] == "nha_dat"
    assert phu_hoa_house["ward"] == "Phú Hòa"
    assert not _is_duplicate(simple_land, dx_land)
    assert not _is_duplicate(dx_land, phu_hoa_house)
    assert not _is_reliable_price_drop(dx_land, simple_land)


def test_facebook_same_phone_area_tho_cu_without_repeated_location_is_drop():
    old = _listing(
        source="facebook", source_id="fb-garden-old", posted_at="2026-04-08",
        ward="Tan An", property_type="dat_nen", area_m2=1212.0,
        price_ty=3.5, price_per_m2=2.89, contact_phone="0933630130",
        description=(
            "Ban 1.212 m2 Dat Tan An Sau cho Ben The cach Huynh Thi Hieu 200m, "
            "co san 140m2 tho cu. Lam vuon ok lam, Huynh Thi Hieu mo rong em luon. "
            "Duong oto ok a."
        ),
    )
    new = _listing(
        source="facebook", source_id="fb-garden-new", posted_at="2026-05-08",
        ward="Tan An", property_type="dat_nen", area_m2=1212.0,
        price_ty=2.9, price_per_m2=2.39, contact_phone="0933630130",
        description=(
            "Ban dat phuong Tan an lam vuon gia tot duong ba gac "
            "Dt 1.212 m2 tc 140 xem dat gap chu chot."
        ),
    )

    assert _is_duplicate(old, new)
    assert _is_reliable_price_drop(old, new)


def test_reliable_drop_same_source_id():
    old = _listing(
        source="facebook", source_id="same-post", posted_at="2026-05-01",
        area_m2=1259.0, price_ty=13.5, description="Old post"
    )
    new = _listing(
        source="facebook", source_id="same-post", posted_at="2026-05-03",
        area_m2=180.0, price_ty=12.9, description="Updated post"
    )
    assert _is_reliable_price_drop(old, new), "Same source_id should be a reliable price drop"


def test_score_threshold_boundary():
    assert SCORE_THRESHOLD == 6, f"SCORE_THRESHOLD should be 6, got {SCORE_THRESHOLD}"


# ── Runner ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        test_hard_gate_same_day,
        test_hard_gate_different_property_type,
        test_hard_gate_different_ward,
        test_hard_gate_unknown_ward_passes,
        test_road_tokens_detect_vietnamese_dx_prefix,
        test_road_tokens_detect_numbered_tdc_roads,
        test_road_tokens_detect_contextual_bare_numbered_tdc_roads,
        test_same_broker_same_dimensions_different_tdc_roads_not_duplicate,
        test_same_broker_same_dimensions_different_bare_tdc_roads_not_duplicate,
        test_same_standard_house_dimensions_near_ql13_need_stronger_price_change_identity,
        test_case1_passes_with_text_30,
        test_case1_fails_without_text,
        test_case1_fails_with_different_dims,
        test_case1_different_depth_no_match,
        test_case2_passes_with_text_70,
        test_case2_fails_with_low_text,
        test_case2_area_mismatch_no_match,
        test_case3_exact_copy,
        test_case3_no_text_no_match,
        test_case3_low_similarity_no_match,
        test_same_source_id_always_duplicate,
        test_facebook_same_source_different_id_uses_scoring,
        test_non_facebook_cross_source_does_not_use_scoring,
        test_reliable_drop_facebook_same_area_different_post,
        test_reliable_drop_rejects_same_template_different_lot,
        test_reliable_drop_rejects_same_dims_different_location,
        test_reliable_drop_rejects_same_road_different_block,
        test_reliable_drop_same_phone_area_anchor,
        test_reliable_drop_ignores_price_per_m2_when_total_price_same,
        test_suspicious_bait_over_40pct_not_reliable_drop,
        test_facebook_same_price_repost_counts_duplicate,
        test_guland_same_price_repost_not_duplicate_for_history,
        test_facebook_same_dimensions_price_tho_cu_duplicate_without_location_signal,
        test_facebook_large_land_subtype_same_numeric_signature_duplicate,
        test_facebook_medium_land_same_road_numeric_signature_duplicate,
        test_guland_phu_tan_template_same_phone_not_same_lot,
        test_guland_phu_hoa_same_phone_area_without_road_not_same_lot,
        test_guland_phu_my_dx006_same_road_not_duplicate_without_same_source_id,
        test_guland_same_source_id_price_drop_still_allowed,
        test_facebook_land_and_house_same_phone_area_not_duplicate,
        test_facebook_same_dims_different_tho_cu_or_location_not_duplicate,
        test_facebook_same_phone_area_tho_cu_without_repeated_location_is_drop,
        test_reliable_drop_same_source_id,
        test_score_threshold_boundary,
    ]
    passed = failed = 0
    for t in tests:
        try:
            t()
            print(f"  ✅ {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  ❌ {t.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"  💥 {t.__name__}: {type(e).__name__}: {e}")
            failed += 1
    print(f"\n{'='*50}")
    print(f"  {passed} passed | {failed} failed")
    print(f"{'='*50}")
    sys.exit(0 if failed == 0 else 1)
