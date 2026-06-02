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

$remoteScript = @"
set -e
cd "$RemotePath"

before=`$(git rev-parse --short HEAD)
stash_ref=""
dirty_files=`$(git status --porcelain | awk '{print `$2}' | grep -v '^data/facebook_profiles.json`$' || true)

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

after=`$(git rev-parse --short HEAD)
echo "deployed `$before -> `$after"
"@

$remoteScript | ssh @sshArgs "bash -s"
