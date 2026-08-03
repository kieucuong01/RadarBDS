import json
from contextlib import contextmanager
from types import SimpleNamespace

import services.extraction_integrity_report as report_service
from services.extraction_integrity_report import (
    _compare_row,
    build_integrity_report,
    summarize_integrity_changes,
)


def test_integrity_report_counts_repairs_suppressions_and_actionable_changes():
    report = summarize_integrity_changes([
        {
            "listing_id": 1,
            "changes": {"area_m2": [60, 85], "price_per_m2": [28.333, 20]},
            "repairs": ["structured_area_was_residential_area"],
            "old_flags": [],
            "new_flags": [],
            "is_signal": True,
            "old_actionable": True,
            "new_actionable": True,
            "training_before": True,
            "training_after": True,
            "invariant_ok": True,
        },
        {
            "listing_id": 2,
            "changes": {},
            "repairs": [],
            "old_flags": [],
            "new_flags": ["area_dimension_conflict"],
            "is_signal": True,
            "old_actionable": True,
            "new_actionable": False,
            "training_before": True,
            "training_after": False,
            "invariant_ok": True,
        },
    ])

    assert report["scanned"] == 2
    assert report["field_changes"]["area_m2"] == 1
    assert report["repair_reasons"]["structured_area_was_residential_area"] == 1
    assert report["suppressing_flags"]["area_dimension_conflict"] == 1
    assert report["actionable"]["newly_suppressed"] == 1
    assert report["training_membership"]["removed"] == 1
    assert report["invariant_violations_remaining"] == 0


def test_build_integrity_report_executes_only_one_read_query(monkeypatch):
    statements = []

    class Cursor:
        def fetchall(self):
            return []

    class Connection:
        def execute(self, sql, params=None):
            statements.append((sql, params))
            return Cursor()

    @contextmanager
    def fake_get_conn():
        yield Connection()

    monkeypatch.setattr(report_service, "get_conn", fake_get_conn)

    report = build_integrity_report(limit=25)

    assert report["scanned"] == 0
    assert len(statements) == 1
    statement = statements[0][0].lstrip().upper()
    assert statement.startswith("WITH")
    assert not any(word in statement for word in ("INSERT ", "UPDATE ", "DELETE ", "ALTER ", "CREATE "))


def test_integrity_report_samples_prioritize_measurement_changes():
    rows = [
        {
            "listing_id": listing_id,
            "changes": {},
            "repairs": ["clear_text_price"],
            "old_actionable": False,
            "new_actionable": False,
            "training_before": True,
            "training_after": True,
            "invariant_ok": True,
        }
        for listing_id in range(1, 61)
    ]
    rows.append({
        "listing_id": 100,
        "changes": {"area_m2": [60, 85]},
        "repairs": [],
        "old_actionable": False,
        "new_actionable": False,
        "training_before": True,
        "training_after": True,
        "invariant_ok": True,
    })

    report = summarize_integrity_changes(rows)

    assert len(report["samples"]) == 50
    assert 100 in {sample["listing_id"] for sample in report["samples"]}


def test_integrity_report_cli_parser_and_json_output(monkeypatch, capsys):
    import radar
    from cli import system

    args = radar.build_parser().parse_args([
        "integrity-report",
        "--limit",
        "200",
        "--json",
    ])
    assert args.cmd == "integrity-report"
    assert args.limit == 200
    assert args.as_json is True

    expected = summarize_integrity_changes([])
    monkeypatch.setattr(report_service, "build_integrity_report", lambda limit=None: expected)
    system.cmd_integrity_report(SimpleNamespace(limit=200, as_json=True))

    assert json.loads(capsys.readouterr().out) == expected


def test_integrity_report_keeps_review_flags_after_renormalization(monkeypatch):
    monkeypatch.setattr(report_service, "normalize_record", lambda _raw: {
        "price_ty": 2.0,
        "area_m2": 100.0,
        "tho_cu_m2": None,
        "price_per_m2": 20.0,
        "extraction_quality_flags": "",
    })
    row = {
        "listing_id": 7,
        "raw_id": 17,
        "source": "guland",
        "source_id": "reviewed",
        "url": "https://example.test/reviewed",
        "title": "Bán đất 100m2 giá 2 tỷ",
        "description": "",
        "property_type": "dat_nen",
        "tx_type": "ban",
        "price_ty": 2.0,
        "area_m2": 100.0,
        "tho_cu_m2": None,
        "price_per_m2": 20.0,
        "frontage_m": None,
        "depth_m": None,
        "extraction_quality_flags": "",
        "raw_json": {"title": "Bán đất 100m2 giá 2 tỷ", "url": "https://example.test/reviewed"},
        "raw_source": "guland",
        "raw_source_id": "reviewed",
        "raw_url": "https://example.test/reviewed",
        "raw_crawled_at": "2026-08-03T00:00:00",
        "main_id": 70,
        "main_is_signal": 1,
        "main_flags": "review_bad_extraction",
        "shadow_id": 71,
        "main_mos": 30.0,
        "shadow_mos": 28.0,
        "feedback_verdict": "bad_data",
        "feedback_extraction_verdict": "wrong_area",
        "feedback_valuation_verdict": "",
        "source_payload_reprocessable": 1,
    }

    comparison = _compare_row(SimpleNamespaceRow(row))

    assert "review_bad_extraction" in comparison["new_flags"]
    assert comparison["new_actionable"] is False


def test_integrity_report_suppresses_unreprocessable_source_payload(monkeypatch):
    monkeypatch.setattr(report_service, "normalize_record", lambda _raw: None)
    row = {
        "listing_id": 8,
        "raw_id": 18,
        "source": "facebook",
        "source_id": "legacy",
        "url": "https://example.test/legacy",
        "title": "Legacy row",
        "description": "",
        "property_type": "dat_nen",
        "tx_type": "ban",
        "price_ty": 2.0,
        "area_m2": 100.0,
        "tho_cu_m2": None,
        "price_per_m2": 20.0,
        "extraction_quality_flags": "",
        "raw_json": {},
        "main_id": 80,
        "main_is_signal": 1,
        "main_flags": "",
        "source_payload_reprocessable": 0,
    }

    comparison = _compare_row(SimpleNamespaceRow(row))

    assert comparison["normalization_failed"] is True
    assert "unreprocessable_source_payload" in comparison["new_flags"]
    assert comparison["new_actionable"] is False
    assert comparison["invariant_ok"] is True


def test_integrity_report_does_not_keep_signal_actionable_without_measurements(monkeypatch):
    monkeypatch.setattr(report_service, "normalize_record", lambda _raw: {
        "price_ty": 2.0,
        "area_m2": None,
        "tho_cu_m2": None,
        "price_per_m2": None,
        "extraction_quality_flags": "",
    })
    row = {
        "listing_id": 9,
        "raw_id": 19,
        "source": "facebook",
        "source_id": "irregular-no-total",
        "url": "https://example.test/irregular-no-total",
        "title": "Lô xéo ngang 5 dài 30 giá 2 tỷ",
        "description": "",
        "property_type": "dat_nen",
        "tx_type": "ban",
        "price_ty": 2.0,
        "area_m2": 150.0,
        "tho_cu_m2": None,
        "price_per_m2": 13.333,
        "extraction_quality_flags": "",
        "raw_json": {"title": "Lô xéo ngang 5 dài 30 giá 2 tỷ"},
        "main_id": 90,
        "main_is_signal": 1,
        "main_flags": "",
        "source_payload_reprocessable": 1,
    }

    comparison = _compare_row(SimpleNamespaceRow(row))

    assert comparison["new_actionable"] is False
    assert comparison["invariant_ok"] is True


class SimpleNamespaceRow(dict):
    """Dict row with the keys()/indexing contract returned by the DB adapter."""

    pass
