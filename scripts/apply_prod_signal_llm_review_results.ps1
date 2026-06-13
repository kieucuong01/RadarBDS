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
cd "$RemotePath"
/opt/radar-bds/.venv/bin/python -X utf8 scripts/apply_llm_extraction_results.py "$RemoteInput" --apply --actor "$Actor" --model "$ModelArg" $RevalueFlag
"@

try {
    $remoteScript | ssh @sshArgs "bash -s"
}
finally {
    & ssh @sshArgs "rm -f '$RemoteInput'" | Out-Null
}
