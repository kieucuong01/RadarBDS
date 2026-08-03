import json
from contextlib import contextmanager
from types import SimpleNamespace

import services.extraction_integrity_report as report_service
from services.extraction_integrity_report import (
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
