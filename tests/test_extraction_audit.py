from services.extraction_audit import audit_listing_extraction
from services.extraction_audit import load_manual_extraction_qc


def _listing(**overrides):
    base = {
        "id": 100,
        "title": "Ban dat Tan An gia 2 ty",
        "description": "DT 5x20 tho cu 100m2 duong nhua 6m",
        "price_ty": 2.0,
        "area_m2": 100.0,
        "ward": "Tan An",
        "property_type": "dat_nen",
        "frontage_m": 5.0,
        "depth_m": 20.0,
        "road_width_m": 6.0,
        "road_tier": 3,
        "road_type": "duong_nhua",
        "road_name": None,
        "tho_cu_m2": 100.0,
        "tho_cu_ratio": 1.0,
        "price_per_m2": 20.0,
    }
    base.update(overrides)
    return base


def _fields(result):
    return {item["field"] for item in result["findings"]}


def test_audit_flags_price_area_and_tho_cu_mismatches():
    result = audit_listing_extraction(_listing(
        title="Ban dat Tan An gia 2 ty",
        description="DT 5x20 tho cu 100m2 duong nhua 6m",
        price_ty=1.2,
        area_m2=50.0,
        tho_cu_m2=60.0,
        tho_cu_ratio=0.63,
    ))

    assert {"price_ty", "area_m2", "tho_cu_m2"} <= _fields(result)
    price = next(item for item in result["findings"] if item["field"] == "price_ty")
    assert price["expected"] == 2.0
    assert price["actual"] == 1.2


def test_audit_flags_clear_measurements_missing_from_storage():
    result = audit_listing_extraction(_listing(
        title="Ban dat Tan An gia 2 ty",
        description="DT 5x20 tho cu 100m2 duong nhua rong 6m",
        price_ty=None,
        area_m2=None,
        frontage_m=None,
        depth_m=None,
        road_width_m=None,
        road_type="unknown",
        tho_cu_m2=None,
        tho_cu_ratio=None,
    ))

    assert {
        "price_ty",
        "area_m2",
        "frontage_m",
        "depth_m",
        "road_width_m",
        "road_type",
        "tho_cu_m2",
    } <= _fields(result)


def test_audit_flags_location_road_and_property_type_mismatches():
    result = audit_listing_extraction(_listing(
        title="Ban day tro My Phuoc 3 duong DJ6",
        description="12 phong tro dang cho thue, DT 10x30, gia 4 ty",
        ward="My Phuoc",
        property_type="dat_nen",
        road_tier=3,
    ))

    assert {"ward", "property_type", "road_tier"} <= _fields(result)
    ward = next(item for item in result["findings"] if item["field"] == "ward")
    assert ward["expected"] == "Mỹ Phước 3"
    assert ward["actual"] == "My Phuoc"


def test_audit_ignores_matching_extraction_with_minor_rounding():
    result = audit_listing_extraction(_listing(
        title="Ban dat Tan An gia 2 ty",
        description="DT 5x20 tho cu 100m2 duong nhua 6m",
        price_ty=2.01,
        area_m2=101.0,
        tho_cu_m2=100.0,
        tho_cu_ratio=0.99,
    ))

    assert result["findings"] == []
    assert result["score"] == 0


def test_audit_uses_irregular_geometry_tolerance():
    result = audit_listing_extraction(_listing(
        description="Lô xéo hậu ngang 5m dài 40m",
        area_m2=100,
    ))

    assert "area_m2" not in _fields(result)


def test_audit_ignores_price_when_stored_value_matches_description_detail():
    result = audit_listing_extraction(_listing(
        title="Dat lo goc gan 300m2 gia chi 2ty",
        description="Dat lo goc gan 300m2 gia chi 2ty250",
        price_ty=2.25,
        area_m2=300.0,
        tho_cu_m2=None,
        tho_cu_ratio=None,
    ))

    assert "price_ty" not in _fields(result)


def test_audit_treats_legacy_phu_an_as_compatible_with_tan_an():
    result = audit_listing_extraction(_listing(
        title="Ban dat 163m2 gia 1.4 ty Phuong Phu An",
        description="Dat tho cu gan Thu Dau Mot",
        ward="Tân An",
        area_m2=163.0,
        price_ty=1.4,
    ))

    assert "ward" not in _fields(result)


def test_audit_treats_legacy_tan_dinh_as_compatible_with_hoa_loi():
    result = audit_listing_extraction(_listing(
        title="Ban dat phuong Hoa Loi gia 2 ty",
        description="Dat gan My Phuoc 3 Ben Cat",
        ward="Tan Dinh",
        price_ty=2.0,
    ))

    assert "ward" not in _fields(result)


def test_audit_does_not_treat_broad_new_ward_as_canonical_old_ward():
    result = audit_listing_extraction(_listing(
        title="Ban dat phuong Binh Duong gia 2 ty",
        description="Dat 5x20 tho cu 100m2 duong nhua 6m",
        ward="Phu Tan",
    ))

    assert "ward" not in _fields(result)


def test_audit_explicit_old_ward_evidence_wins_over_broad_new_ward():
    result = audit_listing_extraction(_listing(
        title="Ban dat phuong Binh Duong gia 2 ty",
        description="Lo 5x20 tai TDC Phu Chanh, tho cu 100m2, duong nhua 6m",
        ward="Phu Chanh",
    ))

    ward = next(item for item in result["findings"] if item["field"] == "ward")
    assert ward["expected"] == "Phú Tân"


def test_load_manual_extraction_qc_parses_llm_markdown_rows(tmp_path):
    report = tmp_path / "manual_findings.md"
    report.write_text(
        """
# Manual LLM Signal Extraction Review

| ID | Fields | Manual expected / issue | Why stored value looks wrong |
|---:|---|---|---|
| 45295 | road_name | QL14 is proximity, not actual road | Text says cach QL14 70m; stored road_name QL14. |
| 53402 | property_type, road_name | Should be dat_nen, not chung_cu; should capture DB12 | Text is land 6.6x30 full tho cu for office/hotel. |
""",
        encoding="utf-8",
    )

    manual_qc = load_manual_extraction_qc(report)

    assert set(manual_qc) == {45295, 53402}
    assert manual_qc[45295]["source"] == "manual_llm"
    assert manual_qc[45295]["fields"] == ["road_name"]
    assert manual_qc[45295]["findings"][0]["field"] == "road_name"
    assert manual_qc[45295]["findings"][0]["expected"] == "QL14 is proximity, not actual road"
    assert manual_qc[53402]["fields"] == ["property_type", "road_name"]
    assert len(manual_qc[53402]["findings"]) == 2
