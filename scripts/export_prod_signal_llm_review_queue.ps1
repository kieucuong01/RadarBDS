param(
    [string] $HostName = "103.90.226.230",
    [string] $User = "deploy",
    [string] $KeyPath = "$env:USERPROFILE\.ssh\radar_bds_deploy_rsa",
    [string] $RemotePath = "/opt/radar-bds/current",
    [string] $Since = "",
    [int] $Days = 1,
    [int] $Limit = 0,
    [ValidateSet("review_at_asc", "signal_desc")]
    [string] $Sort = "review_at_asc",
    [switch] $CommitState
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$LocalOutputDir = Join-Path $Root ".local\llm-review\raw"
New-Item -ItemType Directory -Force -Path $LocalOutputDir | Out-Null

if (-not (Test-Path $KeyPath)) {
    throw "SSH key not found: $KeyPath"
}

$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$RemoteOutput = "/tmp/signal-llm-qc-$Stamp.jsonl"
$LocalOutput = Join-Path $LocalOutputDir "signal-llm-qc-$Stamp.jsonl"

$sshTarget = "$User@$HostName"
$sshArgs = @(
    "-i", $KeyPath,
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=15",
    $sshTarget
)
$scpArgs = @(
    "-i", $KeyPath,
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=15"
)

$SinceEscaped = $Since.Replace('"', '\"')
$CommitFlag = if ($CommitState) { "--commit-state" } else { "" }
$LimitFlag = if ($Limit -gt 0) { "--limit $Limit" } else { "" }

$remoteScript = @"
set -e
cd "$RemotePath"

cmd=(/opt/radar-bds/.venv/bin/python -X utf8 scripts/export_signal_llm_review_queue.py --format jsonl --sort "$Sort" --output "$RemoteOutput")
if [ -n "$SinceEscaped" ]; then
  cmd+=(--since "$SinceEscaped")
else
  cmd+=(--days "$Days")
fi
if [ -n "$LimitFlag" ]; then
  cmd+=($LimitFlag)
fi
if [ -n "$CommitFlag" ]; then
  cmd+=($CommitFlag)
fi

"\${cmd[@]}"
"@

try {
    $remoteScript | ssh @sshArgs "bash -s"
    & scp @scpArgs "${sshTarget}:$RemoteOutput" $LocalOutput
    if ($LASTEXITCODE -ne 0) {
        throw "Download failed with exit code $LASTEXITCODE"
    }
}
finally {
    & ssh @sshArgs "rm -f '$RemoteOutput'" | Out-Null
}

Write-Host "Local queue: $LocalOutput"
