param(
    [ValidateSet("start", "stop", "status")]
    [string] $Action = "start"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$PgBin = Join-Path $Root "tools\postgresql-17.10\pgsql\bin"
$DataDir = Join-Path $Root ".local\postgres-data"
$LogFile = Join-Path $Root ".local\postgres.log"
$Port = 5432

if (!(Test-Path (Join-Path $PgBin "pg_ctl.exe"))) {
    throw "Portable PostgreSQL is missing at $PgBin"
}

New-Item -ItemType Directory -Force -Path (Join-Path $Root ".local") | Out-Null

if ($Action -eq "start") {
    if (!(Test-Path $DataDir)) {
        & (Join-Path $PgBin "initdb.exe") -D $DataDir -U postgres --auth=trust --encoding=UTF8 --locale=C
    }
    & (Join-Path $PgBin "pg_ctl.exe") -D $DataDir -l $LogFile -o "-h 127.0.0.1 -p $Port" start
    & (Join-Path $PgBin "createdb.exe") -h 127.0.0.1 -p $Port -U postgres radar_bds 2>$null
    & (Join-Path $PgBin "pg_isready.exe") -h 127.0.0.1 -p $Port -U postgres
    exit $LASTEXITCODE
}

if ($Action -eq "stop") {
    & (Join-Path $PgBin "pg_ctl.exe") -D $DataDir stop -m fast
    exit $LASTEXITCODE
}

& (Join-Path $PgBin "pg_isready.exe") -h 127.0.0.1 -p $Port -U postgres
