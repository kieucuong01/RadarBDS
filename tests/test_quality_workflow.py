from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_scanner_reports_rule_and_location_without_secret(tmp_path):
    from scripts.check_tracked_secrets import render_findings, scan_paths

    target = tmp_path / "leak.txt"
    secret = "ghp_" + "a" * 36
    target.write_text(f"token={secret}\n", encoding="utf-8")

    findings = scan_paths([target])
    rendered = render_findings(findings)

    assert len(findings) == 1
    assert findings[0].rule == "github_pat"
    assert findings[0].line == 1
    assert secret not in rendered
    assert "leak.txt:1:github_pat" in rendered
    assert not hasattr(findings[0], "matched_value")


def test_scanner_ignores_documented_placeholders_and_binary_files(tmp_path):
    from scripts.check_tracked_secrets import scan_paths

    placeholder = tmp_path / ".env.example"
    placeholder.write_text(
        "DATABASE_URL=postgresql://user:<password>@localhost/db\n"
        "DEEPSEEK_API_KEY=your-api-key-here\n",
        encoding="utf-8",
    )
    binary = tmp_path / "asset.bin"
    binary.write_bytes(b"\x00ghp_" + b"a" * 36)

    assert scan_paths([placeholder, binary]) == []


@pytest.mark.parametrize(
    ("rule", "value"),
    [
        ("private_key", "-----BEGIN " + "PRIVATE KEY-----"),
        ("github_fine_grained_pat", "github_pat_" + "a" * 30),
        ("aws_access_key_id", "AKIA" + "A" * 16),
        ("slack_token", "xoxb-" + "a" * 24),
        ("google_api_key", "AIza" + "a" * 35),
    ],
)
def test_scanner_detects_high_confidence_formats_without_rendering_values(
    tmp_path,
    rule,
    value,
):
    from scripts.check_tracked_secrets import render_findings, scan_paths

    target = tmp_path / f"{rule}.txt"
    target.write_text(value, encoding="utf-8")

    findings = scan_paths([target])

    assert [finding.rule for finding in findings] == [rule]
    assert value not in render_findings(findings)


def test_development_dependencies_pin_pip_audit():
    requirements = (ROOT / "requirements-dev.txt").read_text(encoding="utf-8")

    assert "pytest==8.4.2" in requirements
    assert "pip-audit==2.10.1" in requirements
