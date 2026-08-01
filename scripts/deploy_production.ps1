param(
    [string] $HostName = "103.90.226.230",
    [string] $User = "deploy",
    [string] $KeyPath = "$env:USERPROFILE\.ssh\radar_bds_deploy_rsa",
    [string] $RemotePath = "/opt/radar-bds/current",
    [string] $Branch = "main",
    [switch] $ArchiveKnownTempFiles = $true,
    [switch] $InstallPerformanceInfra = $false
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $KeyPath)) {
    throw "SSH key not found: $KeyPath"
}

$sshTarget = "$User@$HostName"
$sshArgs = @(
    "-i", $KeyPath,
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=15",
    $sshTarget
)
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$ArchiveKnownTempFilesFlag = if ($ArchiveKnownTempFiles) { "1" } else { "0" }
$InstallPerformanceInfraFlag = if ($InstallPerformanceInfra) { "1" } else { "0" }
$RemoteScriptPath = "/tmp/radar-bds-deploy-$Stamp.sh"
$LocalScriptPath = Join-Path $env:TEMP "radar-bds-deploy-$Stamp.sh"

$remoteScript = @"
set -e
cd "$RemotePath"

before_commit=`$(git rev-parse HEAD)
before=`$(git rev-parse --short HEAD)
stash_ref=""
deploy_started="0"
raw_backup="/tmp/radar-bds-raw-backup-before-$Stamp.json"
archive_known_temp_files="$ArchiveKnownTempFilesFlag"
install_performance_infra="$InstallPerformanceInfraFlag"
performance_backup=""
known_temp_archive=""
known_temp_files=(
  "_check_cols2.py"
  "_check_db.py"
  "_cols.py"
  "_radar_audit.py"
  "_radar_audit2.py"
  "_radar_audit3.py"
  "_radar_chain.py"
  "_radar_double.py"
  "_radar_exact.py"
  "_radar_final.py"
  "_radar_final_report.py"
  "_radar_lots.py"
  "_radar_report_check.py"
  "_radar_report_check2.py"
  "_radar_today.py"
  "_radar_today2.py"
  "scripts/radar_daily_report.py"
  "scripts/radar_full_report.py"
  "scripts/radar_report.py"
)

smoke_service() {
  for url in "http://127.0.0.1:5000/api/dashboard" "http://127.0.0.1:5000/api/signals?page=1&limit=3"; do
    for attempt in `$(seq 1 20); do
      if curl -fsS "`$url" >/dev/null 2>&1; then
        break
      fi
      if [ "`$attempt" -eq 20 ]; then
        echo "smoke failed: `$url"
        return 1
      fi
      sleep 1
    done
  done
}

rollback_to_before() {
  status=`$?
  trap - ERR
  if [ "`$deploy_started" = "1" ]; then
    echo "deploy failed; rolling back to `$before"
    if [ -n "`$performance_backup" ] && [ -f scripts/install_performance_infra.sh ]; then
      sudo -n bash scripts/install_performance_infra.sh rollback "`$performance_backup" || true
      performance_backup=""
    fi
    git reset --hard "`$before_commit" >/dev/null || true
    if [ -f "`$raw_backup" ]; then
      mkdir -p data
      cp -f "`$raw_backup" data/raw_backup.json || true
    fi
    if [ -n "`$stash_ref" ]; then
      git stash pop >/dev/null || true
      stash_ref=""
    fi
    sudo systemctl restart radar-bds.service || true
    if smoke_service; then
      echo "rollback smoke passed"
    else
      echo "rollback smoke failed"
    fi
  fi
  exit "`$status"
}
trap 'rollback_to_before' ERR

if [ -e data/facebook_profiles.json ]; then
  legacy_profile_backup="/tmp/radar-bds-facebook-profiles-before-db-only-$Stamp.json"
  cp -f data/facebook_profiles.json "`$legacy_profile_backup" 2>/dev/null || true
  if git ls-files --error-unmatch data/facebook_profiles.json >/dev/null 2>&1; then
    git checkout -- data/facebook_profiles.json >/dev/null 2>&1 || true
  else
    rm -f -- data/facebook_profiles.json
  fi
  echo "legacy Facebook profile JSON removed before DB-only deploy; backup: `$legacy_profile_backup"
fi

dirty_files=`$(git status --porcelain | awk '{print `$2}' | grep -Ev '^(data/raw_backup.json)`$' || true)

if [ -n "`$dirty_files" ] && [ "`$archive_known_temp_files" = "1" ]; then
  known_dirty=""
  unknown_dirty=""
  while IFS= read -r path; do
    [ -z "`$path" ] && continue
    match=0
    for known in "`${known_temp_files[@]}"; do
      if [ "`$path" = "`$known" ]; then
        match=1
        break
      fi
    done
    if [ "`$match" -eq 1 ]; then
      known_dirty="`${known_dirty}`$path
"
    else
      unknown_dirty="`${unknown_dirty}`$path
"
    fi
  done <<EOF_DIRTY
`$dirty_files
EOF_DIRTY

  if [ -n "`$known_dirty" ] && [ -z "`$unknown_dirty" ]; then
    known_temp_archive="/tmp/radar-bds-deploy-known-temp-$Stamp.tgz"
    printf '%s' "`$known_dirty" | tar -czf "`$known_temp_archive" -T -
    while IFS= read -r path; do
      [ -z "`$path" ] && continue
      rm -f -- "`$path"
    done <<EOF_KNOWN
`$known_dirty
EOF_KNOWN
    echo "archived known temporary deploy blockers to `$known_temp_archive"
    dirty_files=`$(git status --porcelain | awk '{print `$2}' | grep -Ev '^(data/raw_backup.json)`$' || true)
  fi
fi

if [ -n "`$dirty_files" ]; then
  echo "Unexpected dirty production files:"
  echo "`$dirty_files"
  exit 2
fi

cp -f data/raw_backup.json "`$raw_backup" 2>/dev/null || true
deploy_started="1"
git fetch origin "$Branch"
git pull --ff-only origin "$Branch"

if [ -f "`$raw_backup" ]; then
  mkdir -p data
  cp -f "`$raw_backup" data/raw_backup.json
fi
if [ "`$install_performance_infra" = "1" ]; then
  install_output=`$(sudo -n bash scripts/install_performance_infra.sh install)
  printf '%s\n' "`$install_output"
  performance_backup=`$(printf '%s\n' "`$install_output" | sed -n 's/^PERFORMANCE_BACKUP_DIR=//p' | tail -n 1)
  if [ -z "`$performance_backup" ]; then
    echo "performance installer did not report its backup directory"
    false
  fi
fi
/opt/radar-bds/.venv/bin/python -X utf8 -m pip install -r requirements.txt
/opt/radar-bds/.venv/bin/python -X utf8 -m py_compile app.py services/market_data.py services/image_assets.py services/public_content.py cli/public_content.py
if sudo -n -u radar true 2>/dev/null; then
  sudo -n -u radar bash -lc 'set -a; source /etc/radar-bds/radar.env; set +a; /opt/radar-bds/.venv/bin/python -X utf8 -c "from db.schema import init_schema; init_schema()"'
else
  echo "skipped manual schema init (sudo -u radar requires password); public content schema is lazily initialized by the app"
fi
if [ -f deployment/ubuntu24/radar-bds-guland-crawl.service ] && [ -f deployment/ubuntu24/radar-bds-guland-crawl.timer ]; then
  if sudo -n install -m 0644 deployment/ubuntu24/radar-bds-guland-crawl.service /etc/systemd/system/radar-bds-guland-crawl.service \
    && sudo -n install -m 0644 deployment/ubuntu24/radar-bds-guland-crawl.timer /etc/systemd/system/radar-bds-guland-crawl.timer; then
    sudo systemctl daemon-reload
    sudo systemctl enable --now radar-bds-guland-crawl.timer
  else
    echo "skipped installing Guland systemd units (sudo install requires password)"
    if command -v crontab >/dev/null 2>&1; then
      CRON_CMD='15 23 * * * cd /opt/radar-bds/current && /usr/bin/flock -n /run/lock/radar-bds-guland-crawl.lock /opt/radar-bds/.venv/bin/python -X utf8 radar.py crawl-daily --source guland --no-alert >> /opt/radar-bds/current/logs/guland-crawl.log 2>&1'
      (crontab -l 2>/dev/null | grep -v 'radar.py crawl-daily --source guland'; echo "$CRON_CMD") | crontab -
      echo "installed deploy-user cron fallback for Guland crawl at 23:15"
    else
      echo "no crontab command available; keep/install radar-bds-guland-crawl.timer manually with root"
    fi
  fi
fi
if [ -f deployment/ubuntu24/radar-bds-public-content.service ] && [ -f deployment/ubuntu24/radar-bds-public-content.timer ]; then
  if sudo -n install -m 0644 deployment/ubuntu24/radar-bds-public-content.service /etc/systemd/system/radar-bds-public-content.service \
    && sudo -n install -m 0644 deployment/ubuntu24/radar-bds-public-content.timer /etc/systemd/system/radar-bds-public-content.timer; then
    sudo systemctl daemon-reload
    sudo systemctl enable --now radar-bds-public-content.timer
  else
    echo "skipped installing public-content systemd units (sudo install requires password)"
    echo "install the public-content systemd units manually; no deploy-user cron fallback is created because /etc/radar-bds/radar.env is readable only by root:radar"
  fi
fi
sudo systemctl restart radar-bds.service
sudo systemctl is-active radar-bds.service

smoke_service

for url in \
  "http://127.0.0.1:5000/api/dashboard?cache_refresh=1" \
  "http://127.0.0.1:5000/api/dashboard" \
  "http://127.0.0.1:5000/api/dashboard" \
  "http://127.0.0.1:5000/api/dashboard"; do
  curl -fsS --max-time 30 "`$url" >/dev/null
done

after=`$(git rev-parse --short HEAD)
echo "deployed `$before -> `$after"
if [ -n "`$known_temp_archive" ]; then
  echo "known temp archive: `$known_temp_archive"
fi
"@

try {
    $remoteScript = $remoteScript -replace "`r`n?", "`n"
    [System.IO.File]::WriteAllText($LocalScriptPath, $remoteScript, [System.Text.UTF8Encoding]::new($false))
    & scp -i $KeyPath -o BatchMode=yes -o ConnectTimeout=15 $LocalScriptPath "${sshTarget}:$RemoteScriptPath"
    if ($LASTEXITCODE -ne 0) {
        throw "Remote script upload failed with exit code $LASTEXITCODE"
    }
    & ssh @sshArgs "bash '$RemoteScriptPath'"
    if ($LASTEXITCODE -ne 0) {
        throw "Remote deploy failed with exit code $LASTEXITCODE"
    }
}
finally {
    if (Test-Path $LocalScriptPath) {
        Remove-Item -LiteralPath $LocalScriptPath -Force
    }
    & ssh @sshArgs "rm -f '$RemoteScriptPath'" | Out-Null
}
