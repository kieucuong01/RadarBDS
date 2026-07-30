param(
    [Parameter(Mandatory = $true)]
    [string] $Message,
    [string[]] $Path = @(),
    [switch] $All,
    [string] $Branch = "main",
    [string] $Remote = "origin",
    [string] $HostName = "103.90.226.230",
    [string] $User = "deploy",
    [string] $KeyPath = "$env:USERPROFILE\.ssh\radar_bds_deploy_rsa",
    [string] $RemotePath = "/opt/radar-bds/current"
)

$ErrorActionPreference = "Stop"

function Run($exe, [string[]] $argv) {
    & $exe @argv
    if ($LASTEXITCODE -ne 0) {
        throw "$exe failed with exit code $LASTEXITCODE"
    }
}

function Git([string[]] $argv) {
    Run "git.exe" $argv
}

if ($All -and $Path.Count -gt 0) {
    throw "Use either -All or -Path, not both."
}
if (-not $All -and $Path.Count -eq 0) {
    throw "Refusing to guess files. Use -All or pass -Path file1,file2."
}
if (-not (Test-Path $KeyPath)) {
    throw "SSH key not found: $KeyPath"
}

$currentBranch = (& git.exe branch --show-current).Trim()
if ($LASTEXITCODE -ne 0) { throw "git branch failed" }
if ($currentBranch -ne $Branch) {
    throw "Current branch is '$currentBranch', expected '$Branch'."
}

if ($All) {
    Git @("add", "-A")
} else {
    Git (@("add", "--") + $Path)
}

$staged = (& git.exe diff --cached --name-only)
if ($LASTEXITCODE -ne 0) { throw "git diff --cached failed" }
if (-not $staged) {
    throw "No staged changes to commit."
}

Git @("commit", "-m", $Message)
Git @("push", $Remote, $Branch)

try {
    & (Join-Path $PSScriptRoot "deploy_production.ps1") -HostName $HostName -User $User -KeyPath $KeyPath -RemotePath $RemotePath -Branch $Branch
    if ($LASTEXITCODE -ne 0) {
        throw "deploy_production.ps1 failed with exit code $LASTEXITCODE"
    }
    exit 0
} catch {
    Write-Warning "Standard deploy failed; falling back to git bundle deploy. $($_.Exception.Message)"
}

$short = (& git.exe rev-parse --short HEAD).Trim()
if ($LASTEXITCODE -ne 0) { throw "git rev-parse failed" }
$localDir = Join-Path (Get-Location) ".local"
New-Item -ItemType Directory -Force -Path $localDir | Out-Null
$bundlePath = Join-Path $localDir "radar-bds-main-$short.bundle"
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$remoteBundle = "/tmp/radar-bds-main-$short-$stamp.bundle"
$remoteScript = "/tmp/radar-bds-bundle-deploy-$short-$stamp.sh"
$localScript = Join-Path $env:TEMP "radar-bds-bundle-deploy-$short-$stamp.sh"
$sshTarget = "$User@$HostName"
$sshArgs = @("-i", $KeyPath, "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", $sshTarget)

Git @("bundle", "create", $bundlePath, $Branch)
Run "scp" @("-i", $KeyPath, "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", $bundlePath, "${sshTarget}:$remoteBundle")

$script = @"
set -e
cd "$RemotePath"

before_commit=`$(git rev-parse HEAD)
before=`$(git rev-parse --short HEAD)
raw_backup="/tmp/radar-bds-raw-backup-before-$short-$stamp.json"
stash_ref=""
deploy_started="0"

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
  legacy_profile_backup="/tmp/radar-bds-facebook-profiles-before-db-only-$short-$stamp.json"
  cp -f data/facebook_profiles.json "`$legacy_profile_backup" 2>/dev/null || true
  if git ls-files --error-unmatch data/facebook_profiles.json >/dev/null 2>&1; then
    git checkout -- data/facebook_profiles.json >/dev/null 2>&1 || true
  else
    rm -f -- data/facebook_profiles.json
  fi
  echo "legacy Facebook profile JSON removed before DB-only deploy; backup: `$legacy_profile_backup"
fi

dirty_files=`$(git status --porcelain | awk '{print `$2}' | grep -Ev '^(data/raw_backup.json)`$' || true)
if [ -n "`$dirty_files" ]; then
  echo "Unexpected dirty production files:"
  echo "`$dirty_files"
  exit 2
fi

cp -f data/raw_backup.json "`$raw_backup" 2>/dev/null || true
deploy_started="1"
git fetch "$remoteBundle" "$Branch"
git reset --hard FETCH_HEAD

if [ -f "`$raw_backup" ]; then
  mkdir -p data
  cp -f "`$raw_backup" data/raw_backup.json
fi
set -a
. /etc/radar-bds/radar.env
set +a

/opt/radar-bds/.venv/bin/python -X utf8 -m pip install -r requirements.txt
/opt/radar-bds/.venv/bin/python -X utf8 -m py_compile app.py routes/public.py services/market_data.py services/image_assets.py
/opt/radar-bds/.venv/bin/python -X utf8 -c "from db.schema import init_schema; init_schema()"
sudo systemctl restart radar-bds.service
sudo systemctl is-active radar-bds.service

smoke_service

curl -fsS "http://127.0.0.1:5000/api/dashboard?cache_refresh=1" >/dev/null
after=`$(git rev-parse --short HEAD)
echo "deployed `$before -> `$after"
"@

try {
    $script = $script -replace "`r`n?", "`n"
    [System.IO.File]::WriteAllText($localScript, $script, [System.Text.UTF8Encoding]::new($false))
    Run "scp" @("-i", $KeyPath, "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", $localScript, "${sshTarget}:$remoteScript")
    Run "ssh" ($sshArgs + @("bash '$remoteScript'"))
} finally {
    if (Test-Path $localScript) {
        Remove-Item -LiteralPath $localScript -Force
    }
    & ssh @sshArgs "rm -f '$remoteScript' '$remoteBundle'" | Out-Null
}
