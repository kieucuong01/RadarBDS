param(
    [ValidateSet("start", "stop", "status")]
    [string] $Action = "start",
    [ValidateRange(1024, 65535)]
    [int] $Port = 15432,
    [ValidateRange(1, 120)]
    [int] $ReadyTimeoutSeconds = 30
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$PgBin = Join-Path $Root "tools\postgresql-17.10\pgsql\bin"
$DataDir = Join-Path $Root ".local\postgres-data"
$LogFile = Join-Path $Root ".local\postgres.log"

function Test-PgReady {
    & (Join-Path $PgBin "pg_isready.exe") `
        -h 127.0.0.1 -p $Port -U postgres *> $null
    return $LASTEXITCODE -eq 0
}

function Wait-PgReady {
    $deadline = [DateTime]::UtcNow.AddSeconds($ReadyTimeoutSeconds)
    do {
        if (Test-PgReady) {
            return $true
        }
        Start-Sleep -Milliseconds 250
    } while ([DateTime]::UtcNow -lt $deadline)
    return $false
}

function Ensure-Database([string] $Name) {
    if ($Name -notmatch '^[a-z][a-z0-9_]{0,62}$') {
        throw "Invalid local database name"
    }
    $exists = & (Join-Path $PgBin "psql.exe") `
        -h 127.0.0.1 -p $Port -U postgres -d postgres -tAc `
        "SELECT 1 FROM pg_database WHERE datname='$Name'" 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "Could not inspect local database $Name"
    }
    if (($exists | Out-String).Trim() -ne "1") {
        & (Join-Path $PgBin "createdb.exe") `
            -h 127.0.0.1 -p $Port -U postgres $Name
        if ($LASTEXITCODE -ne 0) {
            throw "Could not create local database $Name"
        }
    }
}

if (!(Test-Path (Join-Path $PgBin "pg_ctl.exe"))) {
    throw "Portable PostgreSQL is missing at $PgBin"
}

New-Item -ItemType Directory -Force -Path (Join-Path $Root ".local") | Out-Null

if ($Action -eq "start") {
    if (!(Test-PgReady)) {
        if (!(Test-Path $DataDir)) {
            & (Join-Path $PgBin "initdb.exe") `
                -D $DataDir -U postgres --auth=trust --encoding=UTF8 --locale=C
            if ($LASTEXITCODE -ne 0) {
                throw "Could not initialize portable PostgreSQL"
            }
        }
        & (Join-Path $PgBin "pg_ctl.exe") `
            -D $DataDir -l $LogFile -o "-h 127.0.0.1 -p $Port" start
        if (!(Wait-PgReady)) {
            throw "Portable PostgreSQL did not become ready within $ReadyTimeoutSeconds seconds"
        }
    }
    $Databases = @("radar_bds", "radar_bds_test")
    foreach ($Database in $Databases) {
        Ensure-Database $Database
    }
    & (Join-Path $PgBin "pg_isready.exe") -h 127.0.0.1 -p $Port -U postgres
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
    exit 0
}

if ($Action -eq "stop") {
    if (!(Test-Path $DataDir)) {
        exit 0
    }
    & (Join-Path $PgBin "pg_ctl.exe") -D $DataDir status *> $null
    if ($LASTEXITCODE -ne 0) {
        exit 0
    }
    & (Join-Path $PgBin "pg_ctl.exe") -D $DataDir stop -m fast
    exit $LASTEXITCODE
}

& (Join-Path $PgBin "pg_isready.exe") -h 127.0.0.1 -p $Port -U postgres
