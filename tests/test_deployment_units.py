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
    assert "--timeout 45" in text
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
    assert (
        "proxy_cache_use_stale error timeout invalid_header http_500 http_502 "
        "http_503 http_504 updating;"
    ) in include
    assert "proxy_read_timeout 45s;" in include
    assert "proxy_hide_header X-Radar-Public-Cache;" in include
    assert "inactive=24h" in global_cache
    assert "add_header X-Radar-Edge-Cache $upstream_cache_status always;" in site
    assert 'add_header X-Content-Type-Options "nosniff" always;' in site
    assert site.count("backlog=8192") == 1
    assert "listen 443 ssl http2 backlog=8192;" in site
    for route in (
        "= /",
        "= /api/signals",
        "= /api/listings",
        "= /api/counts",
        "= /api/dashboard",
    ):
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
    assert "set -Eeuo pipefail" in text
    assert "redis-server --test-memory 2" in text
    assert "redis-server /etc/redis/redis.conf --test-memory 2" not in text
    assert 'redis-cli -s "$socket" PING' in text
    assert 'redis-cli -s "$socket" SHUTDOWN NOSAVE' in text
    assert "--force-confmiss" in text
    assert "systemctl reload nginx" in text
    assert "systemctl restart radar-bds.service" in text


def test_normal_deploy_requires_explicit_performance_infra_opt_in():
    text = Path("scripts/deploy_production.ps1").read_text("utf-8")

    assert "[switch] $InstallPerformanceInfra = $false" in text
    assert 'install_performance_infra="$InstallPerformanceInfraFlag"' in text
    assert "scripts/install_performance_infra.sh install" in text
    assert 'if [ "`$install_performance_infra" = "1" ]' in text
    assert 'scripts/install_performance_infra.sh rollback "`$performance_backup"' in text
    assert "curl -fsS --max-time 45" in text


def test_public_cache_verifier_checks_hit_bypass_and_redaction():
    text = Path("scripts/verify_public_cache.ps1").read_text("utf-8")

    assert "X-Radar-Edge-Cache" in text
    assert "radar_session=cache-bypass-probe" in text
    assert "Bearer cache-bypass-probe" in text
    assert '"source_url"' in text
    assert '"phone"' in text
    assert "Set-Cookie" in text
    assert "[switch] $RequireCdn" in text
    assert "CF-Cache-Status" in text
    assert "CF-Ray" in text
    assert "Cloudflare HIT" in text
    assert "Cache HIT was not observed" in text
    assert "ConvertFrom-Json -Depth" not in text
    assert (
        '"/api/listings?date_range=3m&sort_by=date&sort_dir=desc'
        '&page=1&limit=50"'
    ) in text


def test_k6_public_load_script_has_safe_scenarios_and_thresholds():
    text = Path("scripts/load/radar_public_load.js").read_text("utf-8")

    assert "SCENARIO" in text
    assert "default" in text and "mixed" in text
    assert "http.batch" in text
    assert "http_req_failed" in text
    assert "p(95)<1000" in text
    assert "p(99)<2000" in text
    assert "Accept-Encoding" in text and "gzip" in text
    assert "X-Radar-Edge-Cache" in text
    assert "REQUIRE_CDN" in text
    assert "CF-Cache-Status" in text
    assert "radar_cdn_hit" in text
    assert "radar_cdn_bypass" in text
    assert "radar_cdn_unknown" in text
    assert "radar_session" not in text
    assert "Authorization" not in text
    assert "/api/listings?" in text
    assert "listings body shape is valid" in text


def test_k6_mixed_prewarm_has_a_bounded_setup_window():
    text = Path("scripts/load/radar_public_load.js").read_text("utf-8")
    workflow = Path(
        ".github/workflows/_radar-distributed-load-stage.yml"
    ).read_text("utf-8")
    commands = Path("docs/dev_commands.md").read_text("utf-8")

    assert "setupTimeout: '5m'" in text
    assert "VU_START_EPOCH" in text
    assert "radar_vu_started_at_ms" in text
    assert "vu_start_epoch=$((start_epoch + 60))" in workflow
    assert "vu_start_epoch=$((start_epoch + 240))" in workflow
    assert "VU_START_EPOCH" in workflow
    assert "-DurationMinutes 60" in commands


def test_reusable_distributed_load_stage_is_pinned_synchronized_and_fail_closed():
    text = Path(
        ".github/workflows/_radar-distributed-load-stage.yml"
    ).read_text("utf-8")

    assert "workflow_call:" in text
    assert "shards_json:" in text
    assert "fromJSON(inputs.shards_json)" in text
    assert "date +%s" in text
    assert "+ 120" in text
    assert "late_by" in text
    assert '"$late_by" -gt 10' in text
    assert "grafana/k6/releases/download/v2.1.0" in text
    assert (
        "295d961ebfca306f295f1133068dcd403a8171c87f387928f5f30b0fbcff858a"
        in text
    )
    assert "11bd71901bbe5b1630ceea73d27597364c9af683" in text
    assert "ea165f8d65b6e75b540449e92b4886f43607fa02" in text
    assert "d3f86a106a0bac45b974a628896c90dbdf5c8093" in text
    assert "--summary-export" in text
    assert "p(99)" in text
    assert "REQUIRE_CDN: \"1\"" in text
    assert '"require_cdn": True' in text
    assert "--require-cdn" in text
    assert "aggregate_k6_shards.py" in text
    assert "if: always()" in text
    assert "contents: read" in text
    assert "id-token" not in text


def test_distributed_capacity_caller_is_serial_fixed_target_and_non_overlapping():
    text = Path(
        ".github/workflows/radar-distributed-capacity.yml"
    ).read_text("utf-8")

    assert "capacity-test/approved-20260801" in text
    assert "confirmation:" in text
    assert "radarbds.vn" in text
    assert "group: radar-production-capacity" in text
    assert "cancel-in-progress: false" in text
    assert "BASE_URL" not in text
    assert "contents: read" in text
    expected = [
        "default_100",
        "mixed_100",
        "default_500",
        "mixed_500",
        "default_1000",
        "mixed_1000",
        "default_5000",
    ]
    positions = [text.index(f"  {name}:") for name in expected]
    assert positions == sorted(positions)
    assert "shards_json: '[0,1,2,3,4]'" in text
    assert "vus_per_shard: 1000" in text
    assert "needs: mixed_1000" in text
    assert text.count("uses: ./.github/workflows/_radar-distributed-load-stage.yml") == 7


def test_capacity_observer_is_status_only_and_enforces_host_abort_thresholds():
    sample = Path(
        "scripts/load/production_capacity_sample.sh"
    ).read_text("utf-8")
    observer = Path(
        "scripts/load/observe_production_capacity.ps1"
    ).read_text("utf-8")

    for token in (
        "systemctl is-active",
        "ListenOverflows",
        "ListenDrops",
        "used_memory",
        "evicted_keys",
        "rejected_connections",
        "pg_stat_activity",
        "legacy_latest_valuation",
        "oldest_active_seconds",
        "map_read_model",
        "vmstat",
    ):
        assert token in sample
    assert "query ~ '^[[:space:]]*WITH[[:space:]]+latest_valuation" in sample
    assert "query LIKE 'WITH latest_valuation AS MATERIALIZED%'" not in sample
    assert "source /etc/radar-bds/radar.env" not in sample
    assert "$DB_CONNECTIONS_MAX = 12" in observer
    assert "$REDIS_MEMORY_MAX = 268435456" in observer
    assert "$CPU_MAX = 90" in observer
    assert "$MEMORY_AVAILABLE_MIN_KB = 524288" in observer
    assert "$SWAP_IO_MAX = 1024" in observer
    assert "memory available" in observer
    assert "swap I/O exceeded" in observer
    assert "ABORT" in observer
    assert "host-samples.jsonl" in observer
    assert "response.body" not in observer.lower()
    assert "Remove-Item" not in observer


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
