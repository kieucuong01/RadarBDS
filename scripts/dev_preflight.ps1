param(
    [switch] $Json,
    [switch] $StartLocalPostgres
)

$ErrorActionPreference = "Stop"
$ExitCodeConfiguration = 10
$ExitCodeRuntime = 20
$ExitCodeDependency = 30
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Checks = [System.Collections.Generic.List[object]]::new()
$Report = [ordered]@{
    ok = $false
    python = $null
    node = $null
    development_database = $null
    test_database = $null
    checks = @()
}

function Add-Check(
    [string] $Name,
    [bool] $Ok,
    [string] $Detail,
    [string] $Remediation = ""
) {
    $item = [ordered]@{
        name = $Name
        ok = $Ok
        detail = $Detail
    }
    if ($Remediation) {
        $item.remediation = $Remediation
    }
    $Checks.Add($item)
}

function Complete-Preflight([int] $ExitCode) {
    $Report.ok = $ExitCode -eq 0
    $Report.checks = $Checks.ToArray()
    if ($Json) {
        $Report | ConvertTo-Json -Depth 6 -Compress
    }
    else {
        foreach ($item in $Report.checks) {
            $state = if ($item.ok) { "OK" } else { "FAIL" }
            Write-Output "[$state] $($item.name): $($item.detail)"
            if (!$item.ok -and $item.remediation) {
                Write-Output "  Next: $($item.remediation)"
            }
        }
        if ($ExitCode -eq 0) {
            Write-Output "Next: run the focused pytest command from docs/dev_commands.md."
        }
    }
    exit $ExitCode
}

function Import-DotEnvFile([string] $Path, [bool] $Override) {
    if (!(Test-Path -LiteralPath $Path)) {
        return
    }
    foreach ($line in Get-Content -LiteralPath $Path -Encoding UTF8) {
        $trimmed = $line.Trim()
        if (!$trimmed -or $trimmed.StartsWith("#") -or !$trimmed.Contains("=")) {
            continue
        }
        $key, $value = $trimmed.Split("=", 2)
        $key = $key.Trim().TrimStart([char]0xFEFF)
        $value = $value.Trim().Trim('"').Trim("'")
        if (
            $key -match '^[A-Za-z_][A-Za-z0-9_]*$' -and
            ($Override -or !(Test-Path "Env:$key"))
        ) {
            [Environment]::SetEnvironmentVariable($key, $value, "Process")
        }
    }
}

function ConvertTo-DatabaseUri([string] $Value) {
    if (!$Value) {
        throw "missing database configuration"
    }
    $builder = [System.UriBuilder]::new($Value)
    $uri = $builder.Uri
    if ($uri.Scheme -notin @("postgres", "postgresql") -or !$uri.Host) {
        throw "database URL must be PostgreSQL"
    }
    if (!$uri.AbsolutePath.TrimStart('/')) {
        throw "database URL must include a database name"
    }
    return $uri
}

function Get-SafeDatabaseTarget([Uri] $Uri) {
    $port = if ($Uri.Port -gt 0) { $Uri.Port } else { 5432 }
    return [ordered]@{
        scheme = $Uri.Scheme
        host = $Uri.Host
        port = $port
        database = [Uri]::UnescapeDataString($Uri.AbsolutePath.TrimStart('/'))
    }
}

function Test-DatabaseConnection([string] $Psql, [Uri] $Uri) {
    $parts = $Uri.UserInfo.Split(':', 2)
    $databaseUser = if ($parts.Count -gt 0 -and $parts[0]) {
        [Uri]::UnescapeDataString($parts[0])
    }
    else {
        "postgres"
    }
    $databasePassword = if ($parts.Count -gt 1) {
        [Uri]::UnescapeDataString($parts[1])
    }
    else {
        ""
    }
    $database = [Uri]::UnescapeDataString($Uri.AbsolutePath.TrimStart('/'))
    $port = if ($Uri.Port -gt 0) { $Uri.Port } else { 5432 }
    $hadPassword = Test-Path Env:PGPASSWORD
    $previousPassword = $env:PGPASSWORD
    try {
        $env:PGPASSWORD = $databasePassword
        & $Psql -w -h $Uri.Host -p $port -U $databaseUser `
            -d $database -tAc "SELECT 1" *> $null
        return $LASTEXITCODE -eq 0
    }
    catch {
        return $false
    }
    finally {
        if ($hadPassword) {
            $env:PGPASSWORD = $previousPassword
        }
        else {
            Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
        }
    }
}

function Find-Executable([string[]] $Candidates, [string] $CommandName) {
    foreach ($candidate in $Candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
            return $candidate
        }
    }
    $command = Get-Command $CommandName -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }
    return $null
}

Import-DotEnvFile (Join-Path $Root ".env") $false
Import-DotEnvFile (Join-Path $Root ".env.local") $true

$DatabaseUrl = (Get-Item Env:DATABASE_URL -ErrorAction SilentlyContinue).Value
$TestDatabaseUrl = (Get-Item Env:RADAR_TEST_DATABASE_URL -ErrorAction SilentlyContinue).Value
if (!$DatabaseUrl -or !$TestDatabaseUrl) {
    Add-Check "database_configuration" $false `
        "DATABASE_URL and RADAR_TEST_DATABASE_URL are required." `
        "Set both variables in .env.local; use radar_bds and radar_bds_test."
    Complete-Preflight $ExitCodeConfiguration
}

try {
    $DevelopmentUri = ConvertTo-DatabaseUri $DatabaseUrl
    $TestUri = ConvertTo-DatabaseUri $TestDatabaseUrl
}
catch {
    Add-Check "database_configuration" $false `
        "Database configuration is not a valid PostgreSQL target." `
        "Correct DATABASE_URL and RADAR_TEST_DATABASE_URL in .env.local."
    Complete-Preflight $ExitCodeConfiguration
}

$Report.development_database = Get-SafeDatabaseTarget $DevelopmentUri
$Report.test_database = Get-SafeDatabaseTarget $TestUri
$developmentName = $Report.development_database.database.ToLowerInvariant()
$testName = $Report.test_database.database.ToLowerInvariant()
if ($testName -notlike "*test*") {
    Add-Check "test_database_guard" $false `
        "RADAR_TEST_DATABASE_URL database name must contain test." `
        "Point RADAR_TEST_DATABASE_URL at radar_bds_test."
    Complete-Preflight $ExitCodeConfiguration
}
if (
    $DevelopmentUri.Host -eq $TestUri.Host -and
    $Report.development_database.port -eq $Report.test_database.port -and
    $developmentName -eq $testName
) {
    Add-Check "test_database_guard" $false `
        "Development and test databases must be distinct." `
        "Use radar_bds for development and radar_bds_test for tests."
    Complete-Preflight $ExitCodeConfiguration
}
Add-Check "database_configuration" $true "Development and test targets are distinct."

if ($StartLocalPostgres) {
    $localTargets = @($DevelopmentUri, $TestUri) | Where-Object {
        $_.Host -ne "127.0.0.1" -or $_.Port -ne 15432
    }
    if ($localTargets.Count -gt 0) {
        Add-Check "local_postgres_start" $false `
            "Start mode is restricted to 127.0.0.1:15432." `
            "Remove -StartLocalPostgres for non-local targets."
        Complete-Preflight $ExitCodeConfiguration
    }
    $bootstrap = Join-Path $Root "scripts\local_postgres.ps1"
    & $bootstrap start *> $null
    if ($LASTEXITCODE -ne 0) {
        Add-Check "local_postgres_start" $false `
            "Portable PostgreSQL did not reach the ready state." `
            ".\scripts\local_postgres.ps1 status"
        Complete-Preflight $ExitCodeRuntime
    }
    Add-Check "local_postgres_start" $true "Portable PostgreSQL is ready."
}

$Python = Find-Executable @(
    (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe")
    (Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe")
) "python"
$Node = Find-Executable @(
    (Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe")
    (Join-Path $env:ProgramFiles "nodejs\node.exe")
) "node"
$Psql = Find-Executable @(
    (Join-Path $Root "tools\postgresql-17.10\pgsql\bin\psql.exe")
    (Join-Path $env:ProgramFiles "PostgreSQL\18\bin\psql.exe")
) "psql"

if (!$Python -or !$Node -or !$Psql) {
    Add-Check "dependencies" $false `
        "Python, Node.js, and psql are required." `
        "Install Python 3.12, Node.js 24, and PostgreSQL client tools."
    Complete-Preflight $ExitCodeDependency
}

$pythonVersion = (& $Python --version 2>&1 | Out-String).Trim()
$nodeVersion = (& $Node --version 2>&1 | Out-String).Trim()
$Report.python = [ordered]@{
    ok = $pythonVersion -match '^Python 3\.12\.'
    version = $pythonVersion.Replace("Python ", "")
}
$Report.node = [ordered]@{
    ok = $nodeVersion -match '^v24\.'
    version = $nodeVersion.TrimStart('v')
}
if (!$Report.python.ok -or !$Report.node.ok) {
    Add-Check "runtime_versions" $false `
        "Python 3.12 and Node.js 24 are required." `
        "Use the documented Python 3.12 and bundled Node.js 24 runtimes."
    Complete-Preflight $ExitCodeDependency
}
Add-Check "runtime_versions" $true "Python 3.12 and Node.js 24 are available."

$developmentReady = Test-DatabaseConnection $Psql $DevelopmentUri
$testReady = Test-DatabaseConnection $Psql $TestUri
Add-Check "development_database" $developmentReady `
    $(if ($developmentReady) { "Development database accepts SELECT 1." } else { "Development database is unavailable." }) `
    ".\scripts\local_postgres.ps1 start"
Add-Check "test_database" $testReady `
    $(if ($testReady) { "Test database accepts SELECT 1." } else { "Test database is unavailable." }) `
    ".\scripts\local_postgres.ps1 start"
if (!$developmentReady -or !$testReady) {
    Complete-Preflight $ExitCodeRuntime
}

Complete-Preflight 0
