param(
    [Parameter(Mandatory = $true)]
    [string] $InputPath,
    [string] $HostName = "103.90.226.230",
    [string] $User = "deploy",
    [string] $KeyPath = "$env:USERPROFILE\.ssh\radar_bds_deploy_rsa",
    [string] $RemotePath = "/opt/radar-bds/current",
    [string] $Actor = "codex",
    [string] $Model = "",
    [switch] $Revalue
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$ResolvedInput = Resolve-Path -LiteralPath $InputPath
if (-not $ResolvedInput) {
    throw "Input file not found: $InputPath"
}
if (-not (Test-Path $KeyPath)) {
    throw "SSH key not found: $KeyPath"
}

$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$RemoteInput = "/tmp/signal-llm-qc-results-$Stamp.jsonl"
$RemoteScriptPath = "/tmp/radar-bds-apply-queue-$Stamp.sh"
$LocalScriptPath = Join-Path $env:TEMP "radar-bds-apply-queue-$Stamp.sh"
$ModelArg = if ($Model) { $Model } else { "manual-llm-signal-qc-$((Get-Date).ToString('yyyyMMdd'))" }
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

& scp @scpArgs $ResolvedInput "${sshTarget}:$RemoteInput"
if ($LASTEXITCODE -ne 0) {
    throw "Upload failed with exit code $LASTEXITCODE"
}

$RevalueFlag = if ($Revalue) { "--revalue" } else { "" }
$remoteScript = @"
set -e
set -a
. /etc/radar-bds/radar.env
set +a
cd "$RemotePath"
/opt/radar-bds/.venv/bin/python -X utf8 scripts/apply_llm_extraction_results.py "$RemoteInput" --apply --actor "$Actor" --model "$ModelArg" $RevalueFlag
"@

try {
    [System.IO.File]::WriteAllText($LocalScriptPath, $remoteScript, [System.Text.UTF8Encoding]::new($false))
    & scp @scpArgs $LocalScriptPath "${sshTarget}:$RemoteScriptPath"
    if ($LASTEXITCODE -ne 0) {
        throw "Remote script upload failed with exit code $LASTEXITCODE"
    }
    & ssh @sshArgs "bash '$RemoteScriptPath'"
    if ($LASTEXITCODE -ne 0) {
        throw "Remote apply failed with exit code $LASTEXITCODE"
    }
}
finally {
    if (Test-Path $LocalScriptPath) {
        Remove-Item -LiteralPath $LocalScriptPath -Force
    }
    & ssh @sshArgs "rm -f '$RemoteInput' '$RemoteScriptPath'" | Out-Null
}
