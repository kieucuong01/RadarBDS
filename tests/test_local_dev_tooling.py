from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOCAL_POSTGRES = ROOT / "scripts" / "local_postgres.ps1"


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
