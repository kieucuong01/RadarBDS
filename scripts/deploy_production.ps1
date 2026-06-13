param(
    [string] $HostName = "103.90.226.230",
    [string] $User = "deploy",
    [string] $KeyPath = "$env:USERPROFILE\.ssh\radar_bds_deploy_rsa",
    [string] $RemotePath = "/opt/radar-bds/current",
    [string] $Branch = "main"
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
$RemoteScriptPath = "/tmp/radar-bds-deploy-$Stamp.sh"
$LocalScriptPath = Join-Path $env:TEMP "radar-bds-deploy-$Stamp.sh"

$remoteScript = @"
set -e
cd "$RemotePath"

before=`$(git rev-parse --short HEAD)
stash_ref=""
dirty_files=`$(git status --porcelain | awk '{print `$2}' | grep -Ev '^(data/facebook_profiles.json|data/raw_backup.json)`$' || true)

if [ -n "`$dirty_files" ]; then
  echo "Unexpected dirty production files:"
  echo "`$dirty_files"
  exit 2
fi

if ! git diff --quiet -- data/facebook_profiles.json; then
  git stash push -m "preserve production facebook profiles before deploy" -- data/facebook_profiles.json >/dev/null
  stash_ref="1"
fi

git fetch origin "$Branch"
git pull --ff-only origin "$Branch"

if [ -n "`$stash_ref" ]; then
  git stash pop >/dev/null
fi

/opt/radar-bds/.venv/bin/python -X utf8 -m py_compile app.py services/market_data.py services/image_assets.py
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
sudo systemctl restart radar-bds.service
sudo systemctl is-active radar-bds.service

for url in "http://127.0.0.1:5000/api/dashboard" "http://127.0.0.1:5000/api/signals?page=1&limit=3"; do
  for attempt in `$(seq 1 20); do
    if curl -fsS "`$url" >/dev/null 2>&1; then
      break
    fi
    if [ "`$attempt" -eq 20 ]; then
      echo "smoke failed: `$url"
      exit 1
    fi
    sleep 1
  done
done

for url in \
  "http://127.0.0.1:5000/api/dashboard?cache_refresh=1" \
  "http://127.0.0.1:5000/api/dashboard" \
  "http://127.0.0.1:5000/api/dashboard" \
  "http://127.0.0.1:5000/api/dashboard"; do
  curl -fsS --max-time 30 "`$url" >/dev/null
done

after=`$(git rev-parse --short HEAD)
echo "deployed `$before -> `$after"
"@

try {
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
