param(
    [string] $Remote = "root@103.90.226.230",
    [string] $KeyPath = ".local\deploy\radar_deploy_oldkey_asus_ed25519",
    [string] $RemoteEnvFile = "/etc/radar-bds/radar.env",
    [string] $RemoteImageDir = "/opt/radar-bds/current/data/images",
    [string] $LocalDb = "radar_bds",
    [string] $LocalUser = "postgres",
    [string] $LocalHost = "127.0.0.1",
    [int] $LocalPort = 5432,
    [switch] $SyncImages,
    [switch] $SkipRestore
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$PgBin = Join-Path $Root "tools\postgresql-17.10\pgsql\bin"
$BackupDir = Join-Path $Root ".local\prod-sync"
$ImageRoot = Join-Path $Root "data\images"
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"

function Invoke-Checked {
    param(
        [string] $Label,
        [scriptblock] $Command
    )

    Write-Host "==> $Label"
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed with exit code $LASTEXITCODE"
    }
}

function Require-File {
    param([string] $Path)
    if (!(Test-Path -LiteralPath $Path)) {
        throw "Missing required file: $Path"
    }
}

Require-File (Join-Path $PgBin "pg_dump.exe")
Require-File (Join-Path $PgBin "pg_restore.exe")
Require-File (Join-Path $PgBin "psql.exe")
Require-File (Join-Path $PgBin "dropdb.exe")
Require-File (Join-Path $PgBin "createdb.exe")
Require-File (Join-Path $PgBin "pg_isready.exe")

$ResolvedKey = Join-Path $Root $KeyPath
Require-File $ResolvedKey

New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
New-Item -ItemType Directory -Force -Path $ImageRoot | Out-Null

$SshArgs = @(
    "-i", $ResolvedKey,
    "-o", "BatchMode=yes",
    "-o", "StrictHostKeyChecking=accept-new",
    $Remote
)
$ScpArgs = @(
    "-i", $ResolvedKey,
    "-o", "BatchMode=yes",
    "-o", "StrictHostKeyChecking=accept-new"
)

$LocalReady = $false
& (Join-Path $PgBin "pg_isready.exe") -h $LocalHost -p $LocalPort -U $LocalUser | Out-Null
if ($LASTEXITCODE -eq 0) {
    $LocalReady = $true
}

if ($LocalReady) {
    Write-Host "==> Local PostgreSQL is already running"
}
else {
    Invoke-Checked "Start local PostgreSQL" {
        & (Join-Path $Root "scripts\local_postgres.ps1") start
    }
}

$RemoteDump = "/tmp/radar_bds_prod_$Stamp.dump"
$LocalProdDump = Join-Path $BackupDir "prod_radar_bds_$Stamp.dump"
$LocalBeforeDump = Join-Path $BackupDir "local_before_prod_sync_$Stamp.dump"

$RemoteDumpCmd = "set -e; tmp=`$(mktemp); tr -d '\r' < '$RemoteEnvFile' > `"`$tmp`"; . `"`$tmp`"; rm -f `"`$tmp`"; pg_dump --format=custom `"`$DATABASE_URL`" > '$RemoteDump'"
Invoke-Checked "Create production DB dump on VPS" {
    & ssh @SshArgs $RemoteDumpCmd
}

try {
    Invoke-Checked "Download production DB dump" {
        & scp @ScpArgs "${Remote}:$RemoteDump" $LocalProdDump
    }
}
finally {
    & ssh @SshArgs "rm -f '$RemoteDump'" | Out-Null
}

if ($SkipRestore) {
    Write-Host "SkipRestore is set. Production dump saved at: $LocalProdDump"
}
else {
    Invoke-Checked "Backup current local DB before restore" {
        & (Join-Path $PgBin "pg_dump.exe") `
            -h $LocalHost `
            -p $LocalPort `
            -U $LocalUser `
            --format=custom `
            --file $LocalBeforeDump `
            $LocalDb
    }

    Invoke-Checked "Terminate local DB sessions" {
        & (Join-Path $PgBin "psql.exe") `
            -h $LocalHost `
            -p $LocalPort `
            -U $LocalUser `
            -d postgres `
            -v ON_ERROR_STOP=1 `
            -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$LocalDb' AND pid <> pg_backend_pid();"
    }

    Invoke-Checked "Recreate local DB" {
        & (Join-Path $PgBin "dropdb.exe") `
            -h $LocalHost `
            -p $LocalPort `
            -U $LocalUser `
            --if-exists `
            $LocalDb
        & (Join-Path $PgBin "createdb.exe") `
            -h $LocalHost `
            -p $LocalPort `
            -U $LocalUser `
            $LocalDb
    }

    Invoke-Checked "Restore production DB into local DB" {
        & (Join-Path $PgBin "pg_restore.exe") `
            -h $LocalHost `
            -p $LocalPort `
            -U $LocalUser `
            -d $LocalDb `
            --no-owner `
            --no-privileges `
            --role $LocalUser `
            $LocalProdDump
    }

    Write-Host "Local DB restored from production."
    Write-Host "Local backup before restore: $LocalBeforeDump"
}

if ($SyncImages) {
    $RemoteImageList = Join-Path $BackupDir "remote-images-$Stamp.txt"
    $LocalImageList = Join-Path $BackupDir "local-images-$Stamp.txt"
    $MissingImageList = Join-Path $BackupDir "missing-images-from-prod-$Stamp.txt"
    $RemoteImageArchive = "/tmp/radar_bds_images_$Stamp.tgz"
    $LocalImageArchive = Join-Path $BackupDir "prod-images-$Stamp.tgz"

    Write-Host "==> Compare production images with local images"
    & ssh @SshArgs "cd '$RemoteImageDir' && find . -type f | sed 's#^\./##'" |
        Set-Content -LiteralPath $RemoteImageList -Encoding ascii

    Get-ChildItem -LiteralPath $ImageRoot -Recurse -File |
        ForEach-Object { $_.FullName.Substring($ImageRoot.Length + 1).Replace('\', '/') } |
        Sort-Object |
        Set-Content -LiteralPath $LocalImageList -Encoding ascii

    $LocalImages = New-Object "System.Collections.Generic.HashSet[string]"
    Get-Content -LiteralPath $LocalImageList | ForEach-Object {
        if (![string]::IsNullOrWhiteSpace($_)) {
            [void] $LocalImages.Add($_.Trim())
        }
    }

    $Missing = New-Object "System.Collections.Generic.List[string]"
    Get-Content -LiteralPath $RemoteImageList | ForEach-Object {
        $Rel = $_.Trim()
        if ($Rel -and !$LocalImages.Contains($Rel)) {
            $Missing.Add($Rel)
        }
    }
    $MissingText = ""
    if ($Missing.Count -gt 0) {
        $MissingText = ($Missing -join "`n") + "`n"
    }
    [System.IO.File]::WriteAllText($MissingImageList, $MissingText, [System.Text.Encoding]::ASCII)

    if ($Missing.Count -eq 0) {
        Write-Host "No production images are missing locally."
    }
    else {
        Write-Host "Production images missing locally: $($Missing.Count)"
        $RemoteMissingList = "/tmp/radar_bds_missing_images_$Stamp.txt"
        Invoke-Checked "Upload missing image list to VPS" {
            & scp @ScpArgs $MissingImageList "${Remote}:$RemoteMissingList"
        }

        try {
            Invoke-Checked "Pack missing production images on VPS" {
                & ssh @SshArgs "set -e; cd '$RemoteImageDir'; tar -czf '$RemoteImageArchive' -T '$RemoteMissingList'"
            }
            Invoke-Checked "Download missing production images" {
                & scp @ScpArgs "${Remote}:$RemoteImageArchive" $LocalImageArchive
            }
        }
        finally {
            & ssh @SshArgs "rm -f '$RemoteMissingList' '$RemoteImageArchive'" | Out-Null
        }

        Invoke-Checked "Extract production images locally" {
            & tar -C $ImageRoot -xzf $LocalImageArchive
        }
        Write-Host "Images synced from production."
    }
}

Write-Host "Production-to-local sync complete."
