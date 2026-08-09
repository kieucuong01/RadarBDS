import pytest

from db import connection
from db.schema import init_schema
from services.data_trust_audit import AuditCheck, run_data_trust_audit


TRACKED_TABLES = (
    "raw_listings",
    "listings",
    "valuation_results",
    "signal_card_read_model",
    "listing_map_locations",
    "source_publishers",
)


class TrackingConnection:
    def __init__(self, wrapped):
        self.wrapped = wrapped
        self.rollback_calls = 0
        self.close_calls = 0

    def __getattr__(self, name):
        return getattr(self.wrapped, name)

    def rollback(self):
        self.rollback_calls += 1
        return self.wrapped.rollback()

    def close(self):
        self.close_calls += 1
        return self.wrapped.close()


@pytest.fixture(autouse=True)
def initialized_test_schema(monkeypatch):
    monkeypatch.setenv("RADAR_SIGNAL_READ_MODEL_ENABLED", "0")
    monkeypatch.setenv("RADAR_LISTING_READ_MODEL_ENABLED", "0")
    monkeypatch.setenv("RADAR_PUBLIC_CACHE_ENABLED", "0")
    connection.close_all()
    init_schema()
    yield
    connection.close_all()


def _database_snapshot():
    conn = connection.connect()
    try:
        versions = [
            (str(row["dataset_name"]), int(row["version"]), str(row["updated_at"]))
            for row in conn.execute(
                """
                SELECT dataset_name, version, updated_at
                FROM public_dataset_versions
                ORDER BY dataset_name
                """
            ).fetchall()
        ]
        counts = {
            table: int(
                conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
            )
            for table in TRACKED_TABLES
        }
        tables = [
            str(row["table_name"])
            for row in conn.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema='public'
                ORDER BY table_name
                """
            ).fetchall()
        ]
        indexes = [
            str(row["indexname"])
            for row in conn.execute(
                """
                SELECT indexname
                FROM pg_indexes
                WHERE schemaname='public'
                ORDER BY indexname
                """
            ).fetchall()
        ]
        return {
            "versions": versions,
            "counts": counts,
            "tables": tables,
            "indexes": indexes,
        }
    finally:
        conn.rollback()
        conn.close()


def test_real_postgres_rejects_write_inside_verified_read_only_transaction():
    import psycopg

    observed = {}
    tracking = TrackingConnection(connection.connect())

    def probe(conn):
        observed["state"] = conn.execute(
            "SHOW transaction_read_only"
        ).fetchone()[0]
        conn.execute("SAVEPOINT data_trust_write_probe")
        try:
            conn.execute(
                "UPDATE public_dataset_versions SET version=version WHERE FALSE"
            )
        except psycopg.errors.ReadOnlySqlTransaction:
            observed["write_rejected"] = True
            conn.execute("ROLLBACK TO SAVEPOINT data_trust_write_probe")
        else:  # pragma: no cover - PostgreSQL must reject this
            observed["write_rejected"] = False
        conn.execute("RELEASE SAVEPOINT data_trust_write_probe")
        return AuditCheck(
            "postgres_read_only_probe",
            "pass" if observed["write_rejected"] else "fail",
            (
                "write_rejected"
                if observed["write_rejected"]
                else "write_was_not_rejected"
            ),
            {"transaction_read_only": observed["state"] == "on"},
        )

    before = _database_snapshot()
    report = run_data_trust_audit(
        connection_factory=lambda: tracking,
        checks=(probe,),
        limit=5,
    )
    after = _database_snapshot()

    assert report["overall_status"] == "pass"
    assert observed == {"state": "on", "write_rejected": True}
    assert tracking.rollback_calls == 1
    assert tracking.close_calls == 1
    assert after == before


@pytest.mark.parametrize("deep", [False, True])
def test_real_default_and_deep_audits_preserve_all_tracked_state(deep):
    before = _database_snapshot()

    report = run_data_trust_audit(deep=deep, limit=3)

    after = _database_snapshot()
    assert report["overall_status"] in {"pass", "warn", "fail"}
    assert report["overall_status"] != "unverified"
    assert any(
        check["name"] == "transaction_read_only"
        and check["status"] == "pass"
        for check in report["checks"]
    )
    expected_deep_status = "pass" if deep else "skipped"
    assert any(
        check["name"] == "deep_signal_read_model"
        and check["status"] in ({"pass", "fail"} if deep else {expected_deep_status})
        for check in report["checks"]
    )
    assert after == before
