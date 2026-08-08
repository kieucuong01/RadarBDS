from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOCAL_POSTGRES = ROOT / "scripts" / "local_postgres.ps1"
DEV_PREFLIGHT = ROOT / "scripts" / "dev_preflight.ps1"


def test_local_postgres_bootstrap_ensures_dev_and_test_databases():
    source = LOCAL_POSTGRES.read_text(encoding="utf-8")

    assert '@("radar_bds", "radar_bds_test")' in source
    assert "SELECT 1 FROM pg_database WHERE datname" in source
    assert "createdb.exe" in source


def test_local_postgres_start_checks_readiness_before_starting():
    source = LOCAL_POSTGRES.read_text(encoding="utf-8")

    assert source.index("pg_isready.exe") < source.index("pg_ctl.exe")
    assert "ReadyTimeoutSeconds" in source


def test_local_postgres_never_drops_or_reinitializes_existing_data():
    source = LOCAL_POSTGRES.read_text(encoding="utf-8").lower()

    assert "dropdb" not in source
    assert "remove-item" not in source
    assert "initdb.exe" in source
    assert "if (!(test-path $datadir))" in source


def test_preflight_masks_credentials_and_requires_distinct_test_database():
    source = DEV_PREFLIGHT.read_text(encoding="utf-8")

    assert "System.UriBuilder" in source
    assert "RADAR_TEST_DATABASE_URL" in source
    assert "database name must contain test" in source.lower()
    assert "development and test databases must be distinct" in source.lower()
    safe_target = source[
        source.index("function Get-SafeDatabaseTarget"):
        source.index("function Test-DatabaseConnection")
    ]
    assert "UserInfo" not in safe_target
    assert "Password" not in safe_target
    assert "AbsoluteUri" not in safe_target


def test_preflight_has_json_and_explicit_start_modes():
    source = DEV_PREFLIGHT.read_text(encoding="utf-8")

    assert "[switch] $Json" in source
    assert "[switch] $StartLocalPostgres" in source
    assert "ConvertTo-Json" in source
    assert "scripts\\local_postgres.ps1" in source
    assert "127.0.0.1" in source
    assert "15432" in source


def test_preflight_has_stable_failure_classes_and_never_echoes_database_urls():
    source = DEV_PREFLIGHT.read_text(encoding="utf-8")

    assert "$ExitCodeConfiguration = 10" in source
    assert "$ExitCodeRuntime = 20" in source
    assert "$ExitCodeDependency = 30" in source
    assert "Write-Output $DatabaseUrl" not in source
    assert "Write-Host $DatabaseUrl" not in source
