import json
import math

import pytest

from services.data_trust_audit import (
    AuditCheck,
    mask_database_target,
    run_data_trust_audit,
)


class FakeCursor:
    def __init__(self, row=None):
        self._row = row

    def fetchone(self):
        return self._row


class RecordingConnection:
    def __init__(self, *, read_only_state="on", execute_error=None):
        self.read_only_state = read_only_state
        self.execute_error = execute_error
        self.statements = []
        self.rollback_calls = 0
        self.close_calls = 0

    def execute(self, sql, params=None):
        normalized = " ".join(sql.split())
        self.statements.append((normalized, params))
        if self.execute_error is not None and normalized == "BEGIN":
            raise self.execute_error
        if normalized == "SHOW transaction_read_only":
            return FakeCursor((self.read_only_state,))
        return FakeCursor()

    def rollback(self):
        self.rollback_calls += 1

    def close(self):
        self.close_calls += 1


@pytest.fixture(autouse=True)
def configured_test_target(monkeypatch):
    monkeypatch.setenv(
        "RADAR_TEST_DATABASE_URL",
        "postgresql://private-user:private-pass@db.example.test:5432/"
        "radar_test?sslmode=require",
    )


def _run(fake, **kwargs):
    return run_data_trust_audit(
        connection_factory=lambda: fake,
        **kwargs,
    )


def test_mask_database_target_never_returns_credentials_or_query():
    masked = mask_database_target(
        "postgresql://private-user:private-pass@db.example.test:5432/"
        "radar?sslmode=require"
    )

    assert masked == {
        "scheme": "postgresql",
        "host": "db.example.test",
        "port": 5432,
        "database": "radar",
    }
    assert "private" not in json.dumps(masked)
    assert "sslmode" not in json.dumps(masked)


def test_audit_check_serializes_only_stable_safe_fields():
    rendered = AuditCheck(
        name="source_freshness_facebook",
        status="warn",
        reason="source_stale_warning",
        measurements={"age_hours": 40.0},
        threshold={"pass_hours": 36, "fail_hours": 72},
    ).as_dict()

    assert set(rendered) == {
        "name",
        "status",
        "reason",
        "measurements",
        "threshold",
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("name", "Bad Name"),
        ("reason", "bad/reason"),
        ("status", "unknown"),
    ],
)
def test_audit_check_rejects_unstable_identifiers(field, value):
    values = {
        "name": "safe_name",
        "status": "pass",
        "reason": "safe_reason",
        "measurements": {},
    }
    values[field] = value
    with pytest.raises(ValueError):
        AuditCheck(**values)


@pytest.mark.parametrize("unsafe", [math.inf, math.nan, object(), "x" * 257])
def test_audit_check_rejects_unsafe_measurements(unsafe):
    with pytest.raises((TypeError, ValueError)):
        AuditCheck(
            name="safe_name",
            status="pass",
            reason="safe_reason",
            measurements={"value": unsafe},
        )


def test_transaction_is_verified_before_domain_checks_and_always_cleaned_up():
    fake = RecordingConnection()
    observed = []

    def probe(conn):
        observed.append(conn)
        return AuditCheck("probe", "pass", "probe_ok", {"count": 1})

    report = _run(fake, checks=(probe,), limit=5, statement_timeout_ms=3_500)

    assert [statement for statement, _ in fake.statements[:4]] == [
        "BEGIN",
        "SET TRANSACTION READ ONLY",
        "SELECT set_config('statement_timeout', ?, true)",
        "SHOW transaction_read_only",
    ]
    assert fake.statements[2][1] == ("3500ms",)
    assert observed == [fake]
    assert report["overall_status"] == "pass"
    assert fake.rollback_calls == 1
    assert fake.close_calls == 1


def test_read_only_verification_fails_closed_before_domain_checks():
    fake = RecordingConnection(read_only_state="off")
    observed = []

    report = _run(fake, checks=(lambda conn: observed.append(conn),))

    assert observed == []
    assert report["overall_status"] == "unverified"
    assert report["reason"] == "read_only_state_unverified"
    assert fake.rollback_calls == 1
    assert fake.close_calls == 1


def test_check_exception_is_masked_and_cleanup_still_runs():
    fake = RecordingConnection()

    def broken(_conn):
        raise RuntimeError("password=private-pass token=secret")

    report = _run(fake, checks=(broken,))
    rendered = json.dumps(report)

    assert report["overall_status"] == "unverified"
    assert report["reason"] == "audit_execution_error"
    assert "private-pass" not in rendered
    assert "secret" not in rendered
    assert fake.rollback_calls == 1
    assert fake.close_calls == 1


def test_timeout_like_exception_is_unverified_without_raw_error():
    QueryCanceled = type("QueryCanceled", (RuntimeError,), {})
    fake = RecordingConnection(execute_error=QueryCanceled("token=secret"))

    report = _run(fake)

    assert report["overall_status"] == "unverified"
    assert report["reason"] == "statement_timeout"
    assert "secret" not in json.dumps(report)
    assert fake.rollback_calls == 1
    assert fake.close_calls == 1


def test_keyboard_interrupt_is_reraised_after_cleanup():
    fake = RecordingConnection()

    def interrupted(_conn):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        _run(fake, checks=(interrupted,))

    assert fake.rollback_calls == 1
    assert fake.close_calls == 1


def test_bounds_and_top_level_status_are_deterministic():
    fake = RecordingConnection()

    def checks(_conn):
        return [
            AuditCheck("pass_check", "pass", "ok", {}),
            AuditCheck("warning_check", "warn", "warning", {}),
        ]

    report = _run(
        fake,
        checks=(checks,),
        limit=50_000,
        statement_timeout_ms=50,
    )

    assert report["overall_status"] == "warn"
    assert report["limit"] == 1_000
    assert report["duration_ms"] >= 0
    assert report["target"]["host"] == "db.example.test"
    assert fake.statements[2][1] == ("1000ms",)
