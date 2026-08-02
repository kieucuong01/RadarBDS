param(
    [Parameter(Mandatory = $true)]
    [string] $EvidenceDir,
    [int] $DurationMinutes = 30,
    [int] $IntervalSeconds = 10,
    [string] $HostName = "103.90.226.230",
    [string] $User = "deploy",
    [string] $KeyPath = "$env:USERPROFILE\.ssh\radar_bds_deploy_rsa"
)

$ErrorActionPreference = "Stop"
$DB_CONNECTIONS_MAX = 12
$REDIS_MEMORY_MAX = 268435456
$CPU_MAX = 90
$MEMORY_AVAILABLE_MIN_KB = 524288
$SWAP_IO_MAX = 1024

if ($DurationMinutes -lt 1 -or $DurationMinutes -gt 60) {
    throw "DurationMinutes must be between 1 and 60"
}
if ($IntervalSeconds -lt 5 -or $IntervalSeconds -gt 60) {
    throw "IntervalSeconds must be between 5 and 60"
}
if (-not (Test-Path -LiteralPath $KeyPath -PathType Leaf)) {
    throw "SSH key not found: $KeyPath"
}

$repoRoot = [IO.Path]::GetFullPath((git rev-parse --show-toplevel).Trim())
$resolvedEvidence = [IO.Path]::GetFullPath($EvidenceDir)
if ($resolvedEvidence.StartsWith($repoRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw "EvidenceDir must stay outside the repository"
}
if (-not (Test-Path -LiteralPath $resolvedEvidence)) {
    $null = New-Item -ItemType Directory -Path $resolvedEvidence
}
$samplesPath = Join-Path $resolvedEvidence "host-samples.jsonl"
$summaryPath = Join-Path $resolvedEvidence "observer-summary.json"
if ((Test-Path -LiteralPath $samplesPath) -or (Test-Path -LiteralPath $summaryPath)) {
    throw "Evidence output already exists: $resolvedEvidence"
}

$sshTarget = "$User@$HostName"
$sshArgs = @(
    "-i", $KeyPath,
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=15",
    $sshTarget
)
$remoteCommand = "cd /opt/radar-bds/current && bash scripts/load/production_capacity_sample.sh"
$sampleLimit = [Math]::Ceiling(($DurationMinutes * 60) / $IntervalSeconds)
$baseline = $null
$sampleCount = 0
$cpuHighCount = 0
$swapActiveCount = 0
$aborted = $false
$abortReasons = [Collections.Generic.List[string]]::new()
$startedAt = [DateTime]::UtcNow

try {
    for ($index = 0; $index -lt $sampleLimit; $index++) {
        $raw = (& ssh @sshArgs $remoteCommand 2>&1) -join "`n"
        if ($LASTEXITCODE -ne 0) {
            throw "Remote sampler failed with exit code ${LASTEXITCODE}: $raw"
        }
        $sample = $raw | ConvertFrom-Json
        if ($null -eq $baseline) {
            $baseline = $sample
        }
        Add-Content -LiteralPath $samplesPath -Value (
            $sample | ConvertTo-Json -Compress -Depth 8
        ) -Encoding utf8
        $sampleCount++

        foreach ($service in @("nginx", "radar", "redis", "postgresql")) {
            if ($sample.services.$service -ne "active") {
                $abortReasons.Add("service $service is $($sample.services.$service)")
            }
        }
        if ([int]$sample.postgresql.connections -gt $DB_CONNECTIONS_MAX) {
            $abortReasons.Add(
                "DB connections $($sample.postgresql.connections) exceed $DB_CONNECTIONS_MAX"
            )
        }
        if ([int64]$sample.redis.used_memory -gt $REDIS_MEMORY_MAX) {
            $abortReasons.Add(
                "Redis memory $($sample.redis.used_memory) exceeds $REDIS_MEMORY_MAX"
            )
        }
        if ([int64]$sample.redis.rejected_connections -gt 0) {
            $abortReasons.Add(
                "Redis rejected_connections=$($sample.redis.rejected_connections)"
            )
        }
        if ([int64]$sample.tcp.ListenOverflows -gt [int64]$baseline.tcp.ListenOverflows) {
            $abortReasons.Add(
                "ListenOverflows increased from $($baseline.tcp.ListenOverflows) to $($sample.tcp.ListenOverflows)"
            )
        }
        if ([int64]$sample.tcp.ListenDrops -gt [int64]$baseline.tcp.ListenDrops) {
            $abortReasons.Add(
                "ListenDrops increased from $($baseline.tcp.ListenDrops) to $($sample.tcp.ListenDrops)"
            )
        }

        if ([int64]$sample.host.memory_available_kb -lt $MEMORY_AVAILABLE_MIN_KB) {
            $abortReasons.Add(
                "memory available $($sample.host.memory_available_kb) KB is below $MEMORY_AVAILABLE_MIN_KB KB"
            )
        }

        $swapIo = (
            [int]$sample.host.swap_in + [int]$sample.host.swap_out
        )
        if ($swapIo -ge $SWAP_IO_MAX) {
            $swapActiveCount++
        }
        else {
            $swapActiveCount = 0
        }
        if ($swapActiveCount -ge 3) {
            $abortReasons.Add(
                "swap I/O exceeded $SWAP_IO_MAX KB/s for three samples"
            )
        }

        if ([int]$sample.host.cpu_percent -gt $CPU_MAX) {
            $cpuHighCount++
        }
        else {
            $cpuHighCount = 0
        }
        if ($cpuHighCount -ge 6) {
            $abortReasons.Add("CPU exceeded $CPU_MAX percent for six samples")
        }
        if ([int]$sample.recent_errors.nginx -gt 0 -or [int]$sample.recent_errors.radar -gt 0) {
            $abortReasons.Add(
                "recent service errors nginx=$($sample.recent_errors.nginx) radar=$($sample.recent_errors.radar)"
            )
        }
        foreach ($service in @("nginx", "radar", "redis")) {
            if ([int]$sample.restarts.$service -gt [int]$baseline.restarts.$service) {
                $abortReasons.Add(
                    "$service restart count increased from $($baseline.restarts.$service) to $($sample.restarts.$service)"
                )
            }
        }

        Write-Output (
            "sample={0} cpu={1}% tcp={2} db={3}/{4} redis={5}MB" -f
            $sample.captured_at,
            $sample.host.cpu_percent,
            $sample.tcp.established,
            $sample.postgresql.active,
            $sample.postgresql.connections,
            [Math]::Round(([double]$sample.redis.used_memory / 1MB), 2)
        )
        if ($abortReasons.Count -gt 0) {
            $aborted = $true
            Write-Error ("ABORT: " + ($abortReasons -join "; "))
        }

        if ($index + 1 -lt $sampleLimit) {
            Start-Sleep -Seconds $IntervalSeconds
        }
    }
}
catch {
    $aborted = $true
    if ($abortReasons.Count -eq 0) {
        $abortReasons.Add($_.Exception.Message)
    }
}
finally {
    $summary = [ordered]@{
        status = if ($aborted) { "ABORT" } else { "completed" }
        started_at = $startedAt.ToString("o")
        finished_at = [DateTime]::UtcNow.ToString("o")
        sample_count = $sampleCount
        evidence_dir = $resolvedEvidence
        abort_reasons = @($abortReasons)
    }
    $summary | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $summaryPath -Encoding utf8
}

if ($aborted) {
    Write-Output "observer_status=ABORT"
    exit 1
}
Write-Output "observer_status=completed"
