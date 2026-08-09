from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "quality-gates.yml"


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


def test_quality_workflow_is_pr_main_only_and_production_safe():
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "pull_request:" in text
    assert text.count("branches: [main]") == 2
    assert "postgres:17" in text
    assert "python-version: '3.12'" in text
    assert "node-version: '24'" in text
    assert "permissions:\n  contents: read" in text
    assert "deploy_production" not in text
    assert "radarbds.vn" not in text
    assert "capacity" not in text.lower()
    assert "RADAR_TEST_DATABASE_URL" in text
    assert "radar_bds_test" in text


def test_quality_workflow_runs_all_repository_owned_gates():
    text = WORKFLOW.read_text(encoding="utf-8")

    for command in (
        "python -m pip check",
        "python -m pip_audit -r requirements.txt",
        "python scripts/check_tracked_secrets.py",
        'python -c "from db.schema import init_schema; init_schema()"',
        "python -m pytest tests --ignore=tests/test_guland.py --ignore=tests/sanity_test.py",
        "node --test tests/js/*.cjs tests/js/test_*.js",
    ):
        assert command in text
    assert "RADAR_TEST_DATABASE_URL: postgresql://postgres:postgres@localhost:5432/radar_bds_test" in text
    assert "DATABASE_URL: postgresql://postgres:postgres@localhost:5432/radar_bds_test" in text


def test_quality_workflow_pins_actions_to_full_commit_shas():
    import re

    text = WORKFLOW.read_text(encoding="utf-8")
    action_refs = re.findall(r"uses:\s+(actions/[^@\s]+)@([^\s#]+)", text)

    assert {name for name, _ref in action_refs} == {
        "actions/checkout",
        "actions/setup-python",
        "actions/setup-node",
    }
    assert all(re.fullmatch(r"[0-9a-f]{40}", ref) for _name, ref in action_refs)
