import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_verify_legal_listing_ignores_ocr_fields_and_marks_document_only():
    from cleansing.legal_verification import verify_legal_listing

    listing = {
        "id": 1,
        "title": "Ban dat Tan An duong DX 042",
        "description": "Dat 121m2, tc 80m2, duong DX 042",
        "ward": "Tan An",
        "area_m2": 121.0,
        "road_type": "duong DX 042",
    }
    legal = {
        "document_image_id": 10,
        "thua_so": "123",
        "to_ban_do": "45",
        "legal_area_m2": 121.2,
        "legal_residential_m2": 80.0,
        "legal_ward": "Tan An",
        "legal_road_text": "tiep giap duong DX 042",
        "legal_road_code": "dx42",
        "ocr_text": "Dien tich 121,2 m2\nDat o ODT 80 m2\nDuong DX 042",
    }

    result = verify_legal_listing(listing, legal, has_legal_doc=True)

    assert result["status"] == "has_document"
    assert result["trust_tier"] == "has_legal_doc"
    assert result["road_match_status"] == "not_checked"
    assert result["confidence_score"] >= 50
    assert result["conflict_flags"] == []


def test_verify_legal_listing_ignores_stale_area_and_road_conflict_fields():
    from cleansing.legal_verification import verify_legal_listing

    listing = {
        "id": 2,
        "title": "Ban dat Tan An mat tien DT 744",
        "description": "Dat 121m2 duong DT 744",
        "ward": "Tan An",
        "area_m2": 121.0,
        "road_type": "duong DT 744",
    }
    legal = {
        "document_image_id": 11,
        "legal_area_m2": 160.0,
        "legal_ward": "Tan An",
        "legal_road_text": "tiep giap duong DX 042",
        "legal_road_code": "dx42",
        "ocr_text": "Dien tich 160 m2\nDuong DX 042",
    }

    result = verify_legal_listing(listing, legal, has_legal_doc=True)

    assert result["status"] == "has_document"
    assert result["trust_tier"] == "has_legal_doc"
    assert result["road_match_status"] == "not_checked"
    assert result["conflict_flags"] == []
    assert result["confidence_score"] >= 50


def test_verify_legal_listing_ignores_stale_missing_road_fields():
    from cleansing.legal_verification import verify_legal_listing

    listing = {
        "id": 3,
        "title": "Ban dat Tan An duong DX 042",
        "description": "Dat 121m2 duong DX 042",
        "ward": "Tan An",
        "area_m2": 121.0,
        "road_type": "duong DX 042",
    }
    legal = {
        "document_image_id": 12,
        "legal_area_m2": 121.0,
        "legal_ward": "Tan An",
        "ocr_text": "Dien tich 121 m2\nDia chi Tan An",
    }

    result = verify_legal_listing(listing, legal, has_legal_doc=True)

    assert result["status"] == "has_document"
    assert result["trust_tier"] == "has_legal_doc"
    assert result["road_match_status"] == "not_checked"
    assert result["conflict_flags"] == []


def test_refresh_legal_verifications_does_not_parse_ocr_text(monkeypatch):
    from contextlib import contextmanager

    import cleansing.legal_verification as legal_verification

    class FakeCursor:
        def fetchall(self):
            return [{
                "id": 99,
                "title": "Ban dat co so",
                "description": "Tin co OCR cu nhung tam tat doc OCR",
                "ward": "Tan An",
                "area_m2": 121.0,
                "road_type": "duong DX 042",
                "tho_cu_m2": None,
                "tho_cu_ratio": None,
                "document_image_id": 77,
                "ocr_text": "Dien tich 999 m2\nDuong sai",
            }]

    class FakeConn:
        def execute(self, _sql, _params=None):
            return FakeCursor()

    @contextmanager
    def fake_get_conn():
        yield FakeConn()

    monkeypatch.setattr(legal_verification, "get_conn", fake_get_conn)

    stats = legal_verification.refresh_legal_verifications(apply=False, limit=1)

    assert stats["statuses"] == {"has_document": 1}
    assert stats["trust_tiers"] == {"has_legal_doc": 1}


def test_latest_legal_image_sql_excludes_not_found_images():
    from cleansing.legal_verification import _latest_legal_image_sql

    sql = _latest_legal_image_sql()

    assert "local_path" in sql
    assert "NOT_FOUND" in sql


def test_admin_verified_status_does_not_create_verified_tier_while_ocr_disabled():
    from cleansing.legal_verification import verify_legal_listing

    listing = {
        "id": 4,
        "title": "Ban dat Tan An",
        "description": "Dat co so hong",
        "ward": "Tan An",
        "area_m2": 121.0,
        "road_type": "",
    }

    result = verify_legal_listing(
        listing,
        {"document_image_id": 13},
        has_legal_doc=True,
        admin_status="verified",
    )

    assert result["status"] == "has_document"
    assert result["trust_tier"] == "has_legal_doc"
    assert result["confidence_score"] >= 50
