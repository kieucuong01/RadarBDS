from pathlib import Path

import pytest


def test_canonical_quality_clause_excludes_reposts_and_invalid_rows():
    from services.monthly_report_data import canonical_quality_listing_sql

    clause = canonical_quality_listing_sql("l")

    assert "l.duplicate_of_id IS NULL" in clause
    assert "COALESCE(l.possibly_duplicate,0)=0" in clause
    assert "COALESCE(l.is_outlier,0)=0" in clause
    assert "COALESCE(l.probably_sold,0)=0" in clause
    assert "COALESCE(l.is_blacklisted,0)=0" in clause
    assert "COALESCE(l.review_hidden,0)=0" in clause


def test_raw_volume_clause_keeps_reposts_but_respects_source_visibility():
    from services.monthly_report_data import raw_listing_sql

    clause = raw_listing_sql("l")

    assert "l.source = 'facebook'" in clause
    assert "COALESCE(l.is_blacklisted,0)=0" in clause
    assert "COALESCE(l.review_hidden,0)=0" in clause
    assert "duplicate_of_id" not in clause
    assert "possibly_duplicate" not in clause


def test_actionable_query_uses_latest_valuation_and_shared_quality_contract():
    from services.monthly_report_data import actionable_count_query

    sql, params = actionable_count_query(
        "Phú Tân",
        "2026-06-01",
        "2026-07-01",
    )

    assert "latest_valuation AS MATERIALIZED" in sql
    assert "JOIN latest_valuation v ON v.listing_id = l.id" in sql
    assert "COALESCE(v.is_signal,0)=1" in sql
    assert "source_quality_recheck" in sql
    assert "review_bad_extraction" in sql
    assert "l.duplicate_of_id IS NULL" in sql
    assert params[-2:] == ["2026-06-01", "2026-07-01"]


def test_featured_query_is_canonical_actionable_and_never_selects_contact_fields():
    from services.monthly_report_data import featured_records_query

    sql, params = featured_records_query(
        "Phú Tân",
        "2026-06-01",
        "2026-07-01",
        limit=6,
    )

    lowered = sql.lower()
    assert "latest_valuation as materialized" in lowered
    assert "l.duplicate_of_id is null" in lowered
    assert "coalesce(v.is_signal,0)=1" in lowered
    assert "order by v.mos_pct desc" in lowered
    assert "limit ?" in lowered
    assert params[-1] == 6
    assert "contact_phone" not in lowered
    assert " l.url" not in lowered


def test_report_scripts_delegate_to_shared_data_service_without_legacy_signal_gate():
    generator = Path("scripts/generate_monthly_report.py").read_text(encoding="utf-8")
    enhancer = Path("scripts/enhance_monthly_report_rich.py").read_text(encoding="utf-8")

    assert "from services.monthly_report_data import" in generator
    assert "from services.monthly_report_data import" in enhancer
    assert "is_hot = 1 OR price_dropped = 1" not in generator
    assert "WITH latest_v AS" not in enhancer
    assert "mos_pct >= 5" not in enhancer


def test_report_snapshots_expose_raw_basis_actionable_contract_in_user_copy():
    generator = Path("scripts/generate_monthly_report.py").read_text(encoding="utf-8")
    enhancer = Path("scripts/enhance_monthly_report_rich.py").read_text(encoding="utf-8")

    for source in (generator, enhancer):
        assert '"raw_listing_count"' in source
        assert '"basis_count"' in source
        assert '"actionable_signal_count"' in source
        assert '"data_contract_version"' in source
        assert "Mẫu hợp lệ" in source
        assert "Tín hiệu = is_hot=1 hoặc price_dropped=1." not in source
        assert "hot + giảm giá" not in source


def test_featured_record_shaping_only_exposes_internal_detail_href():
    from services.monthly_report_data import shape_featured_record

    item = shape_featured_record(
        {
            "id": 42,
            "title": "Lô đất cần bán, Zalo 0901 222 333",
            "property_type": "dat_nen",
            "price_ty": 2.1,
            "price_per_m2": 21,
            "area_m2": 100,
            "has_so": 1,
            "mos_pct": 18,
            "fair_ppm2": 25,
            "signal_score": 80,
            "local_path": None,
            "img_url": None,
        },
        image_resolver=lambda *_args, **_kwargs: "/static/img/placeholder.webp",
    )

    assert item["href"] == "/listing/42"
    assert "url" not in item
    assert "phone" not in item
    assert "0901" not in item["title"]
    assert item["mos_pct"] == pytest.approx(18)
