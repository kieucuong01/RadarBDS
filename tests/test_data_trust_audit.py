import json
import math
from datetime import datetime, timedelta, timezone

import pytest

from services.data_trust_audit import (
    AuditCheck,
    REQUIRED_COLUMNS,
    REQUIRED_INDEXES,
    REQUIRED_TABLES,
    _check_pipeline_counts,
    _check_pipeline_invariants,
    _check_schema_contract,
    _check_source_freshness,
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


class FixtureConnection:
    def __init__(self, responses):
        self.responses = responses
        self.queries = []

    def execute(self, sql, params=None):
        normalized = " ".join(sql.split())
        self.queries.append((normalized, params))
        for marker, rows in self.responses:
            if marker in normalized:
                if isinstance(rows, list):
                    return FixtureResult(rows)
                return FixtureResult([rows])
        raise AssertionError(f"unexpected query: {normalized}")


class FixtureResult:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


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


def _complete_schema_connection(*, missing_table=None, missing_column=None, missing_index=None):
    tables = sorted(REQUIRED_TABLES - ({missing_table} if missing_table else set()))
    columns = [
        {"table_name": table, "column_name": column}
        for table, names in REQUIRED_COLUMNS.items()
        for column in sorted(names)
        if f"{table}.{column}" != missing_column
    ]
    indexes = sorted(REQUIRED_INDEXES - ({missing_index} if missing_index else set()))
    return FixtureConnection(
        [
            ("FROM information_schema.tables", [{"table_name": name} for name in tables]),
            ("FROM information_schema.columns", columns),
            ("FROM pg_indexes", [{"indexname": name} for name in indexes]),
        ]
    )


def test_schema_contract_passes_with_all_required_metadata():
    check = _check_schema_contract(_complete_schema_connection())

    assert check.status == "pass"
    assert check.reason == "schema_contract_ready"
    assert check.measurements == {
        "required_tables": len(REQUIRED_TABLES),
        "required_columns": sum(map(len, REQUIRED_COLUMNS.values())),
        "required_indexes": len(REQUIRED_INDEXES),
        "missing_tables": [],
        "missing_columns": [],
        "missing_indexes": [],
    }


def test_schema_contract_fails_with_names_only_for_missing_metadata():
    connection = _complete_schema_connection(
        missing_table="listing_publishers",
        missing_column="listings.price_ty",
        missing_index="idx_signal_card_public_filter",
    )

    check = _check_schema_contract(connection)

    assert check.status == "fail"
    assert check.reason == "schema_contract_missing"
    assert check.measurements["missing_tables"] == ["listing_publishers"]
    assert check.measurements["missing_columns"] == ["listings.price_ty"]
    assert check.measurements["missing_indexes"] == [
        "idx_signal_card_public_filter"
    ]
    assert all("SELECT" not in value for value in json.dumps(check.as_dict()).split())


@pytest.mark.parametrize(
    ("source", "age_hours", "expected_status", "expected_reason"),
    [
        ("facebook", 36, "pass", "source_fresh"),
        ("facebook", 36.1, "warn", "source_stale_warning"),
        ("facebook", 72, "warn", "source_stale_warning"),
        ("facebook", 72.1, "fail", "source_stale_failure"),
        ("guland", 96, "pass", "source_fresh"),
        ("guland", 96.1, "warn", "source_stale_warning"),
        ("guland", 168, "warn", "source_stale_warning"),
        ("guland", 168.1, "fail", "source_stale_failure"),
    ],
)
def test_source_freshness_boundaries(source, age_hours, expected_status, expected_reason):
    now = datetime(2026, 8, 8, 12, tzinfo=timezone.utc)
    rows = [
        {"source": "facebook", "latest_finished_at": now - timedelta(hours=1)},
        {"source": "guland", "latest_finished_at": now - timedelta(hours=1)},
        {"source": "batdongsan", "latest_finished_at": now},
    ]
    for row in rows:
        if row["source"] == source:
            row["latest_finished_at"] = now - timedelta(hours=age_hours)
    connection = FixtureConnection([("FROM crawl_runs", rows)])

    checks = {check.name: check for check in _check_source_freshness(connection, now)}
    check = checks[f"source_freshness_{source}"]

    assert check.status == expected_status
    assert check.reason == expected_reason
    assert set(checks) == {
        "source_freshness_facebook",
        "source_freshness_guland",
    }
    assert "batdongsan" not in connection.queries[0][0].lower()


def test_missing_source_freshness_distinguishes_primary_and_secondary():
    connection = FixtureConnection([("FROM crawl_runs", [])])

    checks = {
        check.name: check
        for check in _check_source_freshness(
            connection,
            datetime(2026, 8, 8, tzinfo=timezone.utc),
        )
    }

    assert checks["source_freshness_facebook"].status == "fail"
    assert checks["source_freshness_facebook"].reason == "source_never_completed"
    assert checks["source_freshness_guland"].status == "warn"
    assert (
        checks["source_freshness_guland"].reason
        == "source_never_completed_secondary"
    )


def test_invalid_required_source_timestamp_fails_closed():
    connection = FixtureConnection(
        [
            (
                "FROM crawl_runs",
                [
                    {"source": "facebook", "latest_finished_at": "not-a-time"},
                    {
                        "source": "guland",
                        "latest_finished_at": "2026-08-08T00:00:00Z",
                    },
                ],
            )
        ]
    )

    checks = {
        check.name: check
        for check in _check_source_freshness(
            connection,
            datetime(2026, 8, 8, 12, tzinfo=timezone.utc),
        )
    }

    assert checks["source_freshness_facebook"].status == "fail"
    assert checks["source_freshness_facebook"].reason == "source_timestamp_invalid"


def _pipeline_connection(counts=None, violations=None):
    default_counts = {
        "raw_rows": 100,
        "canonical_listings": 80,
        "active_visible_base": 70,
        "latest_valuations": 60,
        "actionable_signals": 10,
        "read_model_base_cards": 70,
        "read_model_actionable_cards": 10,
    }
    default_counts.update(counts or {})
    default_violations = {
        "actionable_rows": 10,
        "invalid_price": 0,
        "invalid_area": 0,
        "invalid_actual_ppm2": 0,
        "suppressed_source_status": 0,
        "hidden_or_suppressed_listing": 0,
        "non_actionable_quality": 0,
    }
    default_violations.update(violations or {})
    return FixtureConnection(
        [
            ("AS raw_rows", default_counts),
            ("AS invalid_price", default_violations),
        ]
    )


def test_pipeline_counts_reuse_current_actionable_sql_contracts():
    connection = _pipeline_connection()

    check = _check_pipeline_counts(connection)

    assert check.status == "pass"
    assert check.reason == "pipeline_counts_consistent"
    assert check.measurements["actionable_signals"] == 10
    sql = connection.queries[0][0]
    assert "latest_valuation AS MATERIALIZED" in sql
    assert "review_bad_extraction" in sql
    assert "review_hidden" in sql


def test_empty_dataset_is_warning_not_false_success():
    check = _check_pipeline_counts(
        _pipeline_connection(
            counts={key: 0 for key in _pipeline_connection().responses[0][1]}
        )
    )

    assert check.status == "warn"
    assert check.reason == "empty_dataset"


def test_pipeline_count_contradiction_is_failure():
    check = _check_pipeline_counts(
        _pipeline_connection(
            counts={"latest_valuations": 4, "actionable_signals": 5}
        )
    )

    assert check.status == "fail"
    assert check.reason == "pipeline_count_contradiction"


@pytest.mark.parametrize(
    "field",
    [
        "invalid_price",
        "invalid_area",
        "invalid_actual_ppm2",
        "suppressed_source_status",
        "hidden_or_suppressed_listing",
        "non_actionable_quality",
    ],
)
def test_actionable_pipeline_invariant_violation_fails(field):
    connection = _pipeline_connection(violations={field: 1})

    check = _check_pipeline_invariants(connection)

    assert check.status == "fail"
    assert check.reason == "pipeline_invariant_violation"
    assert check.measurements["violations"][field] == 1
    sql = connection.queries[0][0]
    assert "latest_valuation AS MATERIALIZED" in sql
    assert "review_bad_extraction" in sql
    assert "review_hidden" in sql
