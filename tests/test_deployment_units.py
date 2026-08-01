import re
import shutil
import subprocess
from pathlib import Path


def test_redis_profile_is_loopback_cache_only_and_memory_bounded():
    text = Path("deployment/ubuntu24/redis-radar-bds.conf").read_text("utf-8")

    assert "bind 127.0.0.1 -::1" in text
    assert "protected-mode yes" in text
    assert 'save ""' in text
    assert "appendonly no" in text
    assert "maxmemory 256mb" in text
    assert "maxmemory-policy allkeys-lru" in text
    assert "maxclients 256" in text
    assert "tcp-keepalive 60" in text


def test_web_service_has_bounded_gunicorn_capacity():
    text = Path("deployment/ubuntu24/radar-bds.service").read_text("utf-8")

    assert "After=network-online.target postgresql.service redis-server.service" in text
    assert "--workers 3" in text
    assert "--threads 4" in text
    assert "--timeout 30" in text
    assert "--graceful-timeout 30" in text
    assert "--keep-alive 5" in text
    assert "--max-requests 2000" in text
    assert "--max-requests-jitter 200" in text
    assert "LimitNOFILE=65536" in text


def test_nginx_public_cache_requires_no_session_and_app_opt_in():
    global_cache = Path(
        "deployment/ubuntu24/nginx-radar-bds-cache.conf"
    ).read_text("utf-8")
    include = Path(
        "deployment/ubuntu24/nginx-radar-public-cache.inc"
    ).read_text("utf-8")
    site = Path("deployment/ubuntu24/nginx-radar-bds.conf").read_text("utf-8")

    assert 'map $http_cookie $radar_has_session' in global_cache
    assert r'~*(^|;\s*)radar_session=' in global_cache
    assert r'"~*(^|;\s*)radar_session=" 1;' in global_cache
    assert 'map $upstream_http_x_radar_public_cache $radar_app_public' in global_cache
    assert "proxy_cache radar_public;" in include
    assert "proxy_cache_bypass $radar_has_session $http_authorization;" in include
    assert (
        "proxy_no_cache $radar_has_session $http_authorization "
        "$radar_not_app_public $upstream_http_set_cookie;"
    ) in include
    assert "proxy_cache_valid 200 15s;" in include
    assert "proxy_cache_lock on;" in include
    assert "proxy_hide_header X-Radar-Public-Cache;" in include
    assert "add_header X-Radar-Edge-Cache $upstream_cache_status always;" in site
    assert 'add_header X-Content-Type-Options "nosniff" always;' in site
    for route in ("= /", "= /api/signals", "= /api/counts", "= /api/dashboard"):
        assert f"location {route}" in site
    assert "ssl_certificate" in site


def test_connection_queue_profile_is_narrow_and_explicit():
    text = Path(
        "deployment/ubuntu24/60-radar-bds-connections.conf"
    ).read_text("utf-8")

    assert text.splitlines() == [
        "net.core.somaxconn=8192",
        "net.ipv4.tcp_max_syn_backlog=8192",
    ]


def test_performance_installer_validates_before_activation_and_has_rollback():
    text = Path("scripts/install_performance_infra.sh").read_text("utf-8")

    assert 'case "$1" in' in text
    assert "install)" in text
    assert "rollback)" in text
    assert "/var/backups/radar-bds-performance" in text
    assert "nginx -t" in text
    assert "systemd-analyze verify" in text
    assert "redis-server --test-memory 2" in text
    assert "systemctl reload nginx" in text
    assert "systemctl restart radar-bds.service" in text


def test_normal_deploy_requires_explicit_performance_infra_opt_in():
    text = Path("scripts/deploy_production.ps1").read_text("utf-8")

    assert "[switch] $InstallPerformanceInfra = $false" in text
    assert 'install_performance_infra="$InstallPerformanceInfraFlag"' in text
    assert "scripts/install_performance_infra.sh install" in text
    assert 'if [ "`$install_performance_infra" = "1" ]' in text
    assert 'scripts/install_performance_infra.sh rollback "`$performance_backup"' in text


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


def test_deploy_script_initializes_public_content_schema_and_installs_daily_sync():
    script = Path("scripts/deploy_production.ps1").read_text(encoding="utf-8")
    service = Path(
        "deployment/ubuntu24/radar-bds-public-content.service"
    ).read_text(encoding="utf-8")

    assert 'from db.schema import init_schema; init_schema()' in script
    assert "sudo -n -u radar true" in script
    assert "public content schema is lazily initialized by the app" in script
    assert "radar-bds-public-content.service" in script
    assert "radar-bds-public-content.timer" in script
    assert "sudo systemctl enable --now radar-bds-public-content.timer" in script
    assert "radar.py public-content-sync --kind all" in service
    assert (
        "set -a; source /etc/radar-bds/radar.env; set +a; "
        "/opt/radar-bds/.venv/bin/python -X utf8 -c"
    ) in script
    assert "PUBLIC_CONTENT_CRON=" not in script
    assert "install the public-content systemd units manually" in script
    public_content_block = script.split(
        "if [ -f deployment/ubuntu24/radar-bds-public-content.service",
        1,
    )[1].split("sudo systemctl restart radar-bds.service", 1)[0]
    assert "crontab" not in public_content_block
    assert not re.search(r"^\s*false\s*$", public_content_block, re.M)


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
