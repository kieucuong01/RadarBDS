from __future__ import annotations

import configparser
import json
import os
from pathlib import Path
import subprocess
import sys

from services.radar_ask.contracts import ProviderResponse, ProviderUsage, ToolCall


ROOT = Path(__file__).resolve().parents[1]


def _unit(name: str) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str
    with (ROOT / "deployment" / "ubuntu24" / name).open(encoding="utf-8") as handle:
        parser.read_file(handle)
    return parser


def test_worker_unit_is_bounded_hardened_and_not_implicitly_enabled():
    unit = _unit("radar-ask-worker.service")
    service = unit["Service"]

    assert service["User"] == "radar"
    assert service["Group"] == "radar"
    assert service["WorkingDirectory"] == "/opt/radar-bds/current"
    assert service["EnvironmentFile"] == "/etc/radar-bds/radar.env"
    assert "RADAR_ASK_DB_POOL_MAX=2" in service["Environment"]
    assert "RADAR_ASK_WORKER_CONCURRENCY=2" in service["Environment"]
    assert service["ExecStart"].endswith("radar.py radar-ask-worker")
    assert service["Restart"] == "on-failure"
    assert service["TimeoutStopSec"] == "75"
    assert service["NoNewPrivileges"] == "true"
    assert service["PrivateTmp"] == "true"
    assert service["ProtectSystem"] == "strict"
    assert service["ProtectHome"] == "true"
    assert service["ReadWritePaths"] == "/run/radar-bds"
    # An install makes the unit available; only the rollout operator enables it.
    assert unit["Install"]["WantedBy"] == "multi-user.target"


def test_retention_units_run_daily_with_catch_up_and_hardening():
    service = _unit("radar-ask-retention.service")["Service"]
    timer = _unit("radar-ask-retention.timer")

    assert service["Type"] == "oneshot"
    assert service["User"] == "radar"
    assert service["WorkingDirectory"] == "/opt/radar-bds/current"
    assert service["EnvironmentFile"] == "/etc/radar-bds/radar.env"
    assert service["ExecStart"].endswith("radar.py radar-ask-retention")
    assert service["NoNewPrivileges"] == "true"
    assert service["PrivateTmp"] == "true"
    assert service["ProtectSystem"] == "strict"
    assert service["ProtectHome"] == "true"
    assert timer["Timer"]["OnCalendar"].startswith("*-*-*")
    assert timer["Timer"]["Persistent"] == "true"
    assert timer["Timer"]["RandomizedDelaySec"] == "30m"
    assert timer["Install"]["WantedBy"] == "timers.target"


def test_provider_smoke_refuses_before_any_live_call_without_confirmation(tmp_path):
    output = tmp_path / "must-not-exist.json"
    marker = "super-secret-provider-key"
    env = {**os.environ, "DEEPSEEK_API_KEY": marker}
    result = subprocess.run(
        [
            sys.executable,
            "-X",
            "utf8",
            str(ROOT / "scripts" / "radar_ask_provider_smoke.py"),
            "--output",
            str(output),
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == 2
    assert "--confirm-live-cost" in result.stderr
    assert marker not in result.stdout + result.stderr
    assert not output.exists()


def test_provider_smoke_report_is_structural_and_content_free():
    from scripts.radar_ask_provider_smoke import build_sanitized_report

    secret = "PRIVATE_PROVIDER_CONTENT_MUST_NOT_PERSIST"
    usage = ProviderUsage(
        input_tokens=11,
        output_tokens=7,
        cache_hit_input_tokens=3,
        cache_miss_input_tokens=8,
    )
    report = build_sanitized_report(
        flash_model="deepseek-v4-flash",
        pro_model="deepseek-v4-pro",
        flash=ProviderResponse(
            content=json.dumps({"ok": True, "private": secret}),
            json_value={"ok": True, "private": secret},
            usage=usage,
            finish_reason="stop",
        ),
        tool=ProviderResponse(
            content=None,
            tool_calls=[
                ToolCall(call_id="call-1", name="release_probe", arguments={"secret": secret})
            ],
            reasoning_content=secret,
            usage=usage,
            finish_reason="tool_calls",
        ),
        continuation=ProviderResponse(
            content=secret,
            reasoning_content=secret,
            usage=usage,
            finish_reason="stop",
        ),
    )

    encoded = json.dumps(report, sort_keys=True)
    assert secret not in encoded
    assert set(report) == {"schema_version", "checked_at", "pricing_version", "probes", "total"}
    assert report["probes"]["flash"]["json_object"] is True
    assert report["probes"]["pro"]["tool_call"] is True
    assert report["probes"]["pro"]["continuation"] is True
    assert report["total"]["estimated_cost_usd"] != "0.000000"


def test_production_verifier_config_check_exposes_required_gates_and_capacity():
    script = ROOT / "scripts" / "verify_radar_ask_production.ps1"
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            "-ConfigCheck",
            "-ExpectedSha",
            "a" * 40,
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["assistantReadCapacity"] == 5
    assert payload["authenticatedSmoke"] is False
    assert set(payload["requiredGates"]) == {
        "auth-private-cache",
        "budget-thresholds",
        "connection-headroom",
        "deployed-sha",
        "feature-and-tiers",
        "legacy-endpoint-absent",
        "public-health",
        "read-only-grants",
        "redaction",
        "schema",
        "service-and-timer",
        "valuation-trace-coverage",
    }


def test_production_verifier_authenticated_smoke_is_explicit_and_secret_safe(tmp_path):
    script = ROOT / "scripts" / "verify_radar_ask_production.ps1"
    secret = "private-admin-password"
    credential = tmp_path / "admin.json"
    credential.write_text(
        json.dumps({"identifier": "admin@example.test", "password": secret}),
        encoding="utf-8",
    )
    base = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script),
        "-ConfigCheck",
        "-ExpectedSha",
        "a" * 40,
        "-ExpectedFeatureState",
        "on",
        "-RunAuthenticatedSmoke",
    ]

    unconfirmed = subprocess.run(
        [*base, "-AuthCredentialPath", str(credential)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert unconfirmed.returncode != 0
    assert "ConfirmLiveCost" in unconfirmed.stderr
    assert secret not in unconfirmed.stdout + unconfirmed.stderr

    missing = subprocess.run(
        [*base, "-ConfirmLiveCost"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert missing.returncode != 0
    assert "AuthCredentialPath" in missing.stderr

    checked = subprocess.run(
        [
            *base,
            "-ConfirmLiveCost",
            "-AuthCredentialPath",
            str(credential),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert checked.returncode == 0, checked.stderr
    assert json.loads(checked.stdout)["authenticatedSmoke"] is True
    assert secret not in checked.stdout + checked.stderr


def test_install_and_deploy_never_enable_or_start_feature_off_worker():
    installer = (ROOT / "scripts" / "install_radar_ask_services.sh").read_text(
        encoding="utf-8"
    )
    deploy = (ROOT / "scripts" / "deploy_production.ps1").read_text(encoding="utf-8")

    assert "systemctl enable --now radar-ask-retention.timer" in installer
    assert "systemctl enable --now radar-ask-worker.service" not in installer
    assert "systemctl start radar-ask-worker.service" not in installer
    assert "RADAR_ASK_ENABLED=1" not in installer
    assert "reprocess --full" not in installer
    assert "radar_ask_vector_migration" not in installer
    assert "assistant_sessions" not in installer

    assert "install_radar_ask_services.sh install" in deploy
    assert "-m compileall -q services/radar_ask" in deploy
    assert "systemctl is-active --quiet radar-ask-worker.service" in deploy
    assert "systemctl try-restart radar-ask-worker.service" in deploy
    assert "systemctl enable --now radar-ask-worker.service" not in deploy
    assert "RADAR_ASK_ENABLED=1" not in deploy
    assert "reprocess --full" not in deploy
    assert "assistant_sessions" not in deploy


def test_production_verifier_reads_private_env_as_radar_and_proves_worker_is_installed():
    verifier = (ROOT / "scripts" / "verify_radar_ask_production.ps1").read_text(
        encoding="utf-8"
    )

    assert "systemctl cat radar-ask-worker.service >/dev/null" in verifier
    assert "sudo -n -u radar" in verifier
    assert "source /etc/radar-bds/radar.env" in verifier
    assert "[[ ! -r /etc/radar-bds/radar.env ]]" not in verifier
    assert '[[ "$feature_on" -eq 1 && -z "${DEEPSEEK_API_KEY:-}" ]]' in verifier
    assert 'echo "$DEEPSEEK_API_KEY"' not in verifier
    assert "RADAR_ASK_ROUTER_MODEL:-deepseek-v4-flash" in verifier
    assert "RADAR_ASK_FREE_MODEL:-deepseek-v4-flash" in verifier
    assert "RADAR_ASK_SMART_MODEL:-deepseek-v4-pro" in verifier
    assert "deepseek-chat" not in verifier
    assert "deepseek-reasoner" not in verifier
    assert "/api/auth/login" in verifier
    assert "requested_depth" in verifier
    assert "api/radar-ask/runs/$deep_run_id" in verifier
