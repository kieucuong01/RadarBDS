import shutil
import subprocess
from pathlib import Path


def test_guland_secondary_systemd_timer_runs_after_primary_daily_crawl():
    base = Path("deployment/ubuntu24")
    service = (base / "radar-bds-guland-crawl.service").read_text(encoding="utf-8")
    timer = (base / "radar-bds-guland-crawl.timer").read_text(encoding="utf-8")

    assert "radar.py crawl-daily --source guland --no-alert" in service
    assert "/run/radar-bds/crawl.lock" in service
    assert "OnCalendar=*-*-* 22:30:00" in timer
    assert "Unit=radar-bds-guland-crawl.service" in timer


def test_deploy_script_installs_guland_cron_fallback_when_systemd_install_is_restricted():
    script = Path("scripts/deploy_production.ps1").read_text(encoding="utf-8")

    assert "sudo -n install" in script
    assert "command -v crontab" in script
    assert "radar.py crawl-daily --source guland --no-alert" in script
    assert "15 23 * * *" in script
    assert "/run/lock/radar-bds-guland-crawl.lock" in script
    assert "crontab -" in script


def test_deploy_script_can_archive_known_temp_blockers_before_failing():
    script = Path("scripts/deploy_production.ps1").read_text(encoding="utf-8")

    assert "[switch] $ArchiveKnownTempFiles = $true" in script
    assert 'known_temp_archive="/tmp/radar-bds-deploy-known-temp-' in script
    assert '"_radar_audit.py"' in script
    assert '"scripts/radar_report.py"' in script
    assert 'rm -f -- "`$path"' in script
    assert "Unexpected dirty production files:" in script


def test_deploy_remote_script_succeeds_when_no_known_temp_archive_was_created():
    script = Path("scripts/deploy_production.ps1").read_text(encoding="utf-8")
    tail_marker = 'echo "deployed `$before -> `$after"\n'
    remote_tail = script.split(tail_marker, maxsplit=1)[1].split('\n"@', maxsplit=1)[0]
    remote_tail = remote_tail.replace("`$", "$")

    git_bash = Path("C:/Program Files/Git/bin/bash.exe")
    bash = str(git_bash) if git_bash.exists() else shutil.which("bash")
    assert bash is not None

    completed = subprocess.run(
        [bash, "-c", f'set -e\nknown_temp_archive=""\n{remote_tail}'],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


def test_live_seo_article_verifier_checks_canonical_and_sitemap():
    script = Path("scripts/verify_live_seo_article.ps1").read_text(encoding="utf-8")

    assert 'Invoke-WebRequest -UseBasicParsing -Uri $Url' in script
    assert 'Canonical tag missing' in script
    assert 'Article URL missing from sitemap' in script
    assert "RequireWatchlistIntent" in script
