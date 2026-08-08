import json
from types import SimpleNamespace

import pytest


def _report(status="pass", checks=None):
    return {
        "overall_status": status,
        "target": {
            "scheme": "postgresql",
            "host": "db.example.test",
            "port": 5432,
            "database": "radar",
        },
        "generated_at": "2026-08-08T12:00:00Z",
        "duration_ms": 12,
        "deep": False,
        "limit": 200,
        "checks": checks
        if checks is not None
        else [
            {
                "name": "schema_contract",
                "status": "pass",
                "reason": "schema_contract_ready",
                "measurements": {"required_tables": 9},
            }
        ],
    }


def test_data_trust_parser_defaults_and_options():
    import radar

    defaults = radar.build_parser().parse_args(["data-trust-audit"])
    selected = radar.build_parser().parse_args(
        ["data-trust-audit", "--json", "--deep", "--limit", "7"]
    )

    assert defaults.cmd == "data-trust-audit"
    assert defaults.as_json is False
    assert defaults.deep is False
    assert defaults.limit == 200
    assert selected.as_json is True
    assert selected.deep is True
    assert selected.limit == 7


@pytest.mark.parametrize("value", ["0", "1001", "not-an-integer"])
def test_data_trust_parser_rejects_invalid_limit(value):
    import radar

    with pytest.raises(SystemExit):
        radar.build_parser().parse_args(
            ["data-trust-audit", "--limit", value]
        )


def test_data_trust_main_dispatches_only_the_audit_command(monkeypatch):
    import radar

    calls = []
    monkeypatch.setattr(
        radar,
        "cmd_data_trust_audit",
        lambda args: calls.append((args.cmd, args.limit)),
    )
    monkeypatch.setattr(
        radar,
        "cmd_signal_read_model",
        lambda _args: pytest.fail("signal command must not run"),
    )
    monkeypatch.setattr(
        "db.schema.init_schema",
        lambda: pytest.fail("schema initialization must not run"),
    )
    monkeypatch.setattr(
        radar.sys,
        "argv",
        ["radar.py", "data-trust-audit", "--limit", "9"],
    )

    radar.main()

    assert calls == [("data-trust-audit", 9)]


@pytest.mark.parametrize(
    ("status", "expected_exit"),
    [
        ("pass", 0),
        ("warn", 0),
        ("fail", 1),
        ("unverified", 2),
    ],
)
def test_json_renderer_and_exit_codes(monkeypatch, capsys, status, expected_exit):
    from cli import data_trust

    expected = _report(status)
    if status == "unverified":
        expected["reason"] = "database_connection_error"
    monkeypatch.setattr(
        data_trust,
        "run_data_trust_audit",
        lambda **kwargs: expected,
    )
    args = SimpleNamespace(as_json=True, deep=False, limit=200)

    if expected_exit:
        with pytest.raises(SystemExit) as raised:
            data_trust.cmd_data_trust_audit(args)
        assert raised.value.code == expected_exit
    else:
        assert data_trust.cmd_data_trust_audit(args) == expected

    captured = capsys.readouterr()
    assert json.loads(captured.out) == expected
    assert captured.err == ""


def test_failed_or_unverified_check_overrides_inconsistent_top_level(monkeypatch):
    from cli import data_trust

    failed = _report(
        "pass",
        checks=[
            {
                "name": "parity",
                "status": "fail",
                "reason": "mismatch",
                "measurements": {},
            }
        ],
    )
    monkeypatch.setattr(data_trust, "run_data_trust_audit", lambda **kwargs: failed)

    with pytest.raises(SystemExit) as raised:
        data_trust.cmd_data_trust_audit(
            SimpleNamespace(as_json=True, deep=False, limit=200)
        )

    assert raised.value.code == 1


def test_text_renderer_uses_stable_safe_one_line_summaries(monkeypatch, capsys):
    from cli import data_trust

    expected = _report("warn")
    expected["checks"][0]["status"] = "warn"
    expected["checks"][0]["reason"] = "empty_dataset"
    monkeypatch.setattr(data_trust, "run_data_trust_audit", lambda **kwargs: expected)

    data_trust.cmd_data_trust_audit(
        SimpleNamespace(as_json=False, deep=False, limit=200)
    )
    captured = capsys.readouterr()

    lines = captured.out.splitlines()
    assert lines[0].startswith("data_trust overall=warn")
    assert "host=db.example.test" in lines[1]
    assert "database=radar" in lines[1]
    assert lines[2].startswith(
        "check=schema_contract status=warn reason=empty_dataset"
    )
    assert captured.err == ""


def test_unexpected_service_exception_is_masked_from_both_streams(monkeypatch, capsys):
    from cli import data_trust

    def broken(**_kwargs):
        raise RuntimeError("password=private-pass token=secret")

    monkeypatch.setattr(data_trust, "run_data_trust_audit", broken)

    with pytest.raises(SystemExit) as raised:
        data_trust.cmd_data_trust_audit(
            SimpleNamespace(as_json=False, deep=False, limit=200)
        )

    captured = capsys.readouterr()
    assert raised.value.code == 2
    assert "private-pass" not in captured.out
    assert "private-pass" not in captured.err
    assert "secret" not in captured.out
    assert "secret" not in captured.err
    assert "audit_execution_error" in captured.out


def test_data_trust_operations_are_documented_with_fail_closed_boundaries():
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    documents = {
        name: (root / "docs" / name).read_text(encoding="utf-8").lower()
        for name in ("operations.md", "dev_commands.md")
    }
    common_markers = (
        "data-trust-audit",
        "exit 0",
        "exit 1",
        "exit 2",
        "set transaction read only",
        "statement timeout",
        "no automatic remediation",
        "outside the repository",
    )
    for name, document in documents.items():
        for marker in common_markers:
            assert marker in document, f"{name} is missing {marker!r}"

    operations = documents["operations.md"]
    assert "deployed sha" in operations
    assert "systemctl is-active radar-bds.service" in operations
    assert "credential previously exposed" in operations
    assert "rotated before" in operations
