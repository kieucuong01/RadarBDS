import json
import math
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest

from services.data_trust_audit import (
    AuditCheck,
    EXTRACTION_FIELDS,
    MAP_PRECISIONS,
    PUBLISHER_CLASSES,
    REQUIRED_COLUMNS,
    REQUIRED_INDEXES,
    REQUIRED_TABLES,
    SAFE_DEEP_DIAGNOSTIC_KEYS,
    _check_deep_read_models,
    _check_dataset_versions,
    _check_extraction_quality,
    _check_map_coverage,
    _check_pipeline_counts,
    _check_pipeline_invariants,
    _check_public_signal_parity,
    _check_publisher_policy,
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


class AuditFixtureConnection(RecordingConnection):
    def __init__(self, responses):
        super().__init__()
        self.responses = responses

    def execute(self, sql, params=None):
        normalized = " ".join(sql.split())
        if normalized in {
            "BEGIN",
            "SET TRANSACTION READ ONLY",
            "SHOW transaction_read_only",
        } or normalized.startswith("SELECT set_config"):
            return super().execute(sql, params)
        self.statements.append((normalized, params))
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


def _version_connection(rows):
    return FixtureConnection([("FROM public_dataset_versions", rows)])


@pytest.mark.parametrize(
    ("flags", "required"),
    [
        ({}, {"signals": False, "listings": False, "market": False}),
        (
            {"RADAR_SIGNAL_READ_MODEL_ENABLED": "1"},
            {"signals": True, "listings": True, "market": False},
        ),
        (
            {
                "RADAR_SIGNAL_READ_MODEL_ENABLED": "1",
                "RADAR_LISTING_READ_MODEL_ENABLED": "0",
                "RADAR_PUBLIC_CACHE_ENABLED": "1",
            },
            {"signals": True, "listings": False, "market": True},
        ),
    ],
)
def test_dataset_version_requirement_follows_feature_flags(monkeypatch, flags, required):
    for name in (
        "RADAR_SIGNAL_READ_MODEL_ENABLED",
        "RADAR_LISTING_READ_MODEL_ENABLED",
        "RADAR_PUBLIC_CACHE_ENABLED",
    ):
        monkeypatch.delenv(name, raising=False)
    for name, value in flags.items():
        monkeypatch.setenv(name, value)
    rows = [
        {
            "dataset_name": name,
            "version": 4,
            "updated_at": "2026-08-08T00:00:00Z",
        }
        for name in ("signals", "listings", "market")
    ]

    checks = {
        check.measurements["dataset"]: check
        for check in _check_dataset_versions(_version_connection(rows))
    }

    assert {name: check.measurements["required"] for name, check in checks.items()} == required
    for name, check in checks.items():
        assert check.status == ("pass" if required[name] else "skipped")


@pytest.mark.parametrize("required_dataset", ["signals", "listings", "market"])
def test_required_dataset_version_must_be_present_and_positive(
    monkeypatch, required_dataset
):
    monkeypatch.setenv("RADAR_SIGNAL_READ_MODEL_ENABLED", "1")
    monkeypatch.setenv("RADAR_LISTING_READ_MODEL_ENABLED", "1")
    monkeypatch.setenv("RADAR_PUBLIC_CACHE_ENABLED", "1")
    rows = [
        {"dataset_name": name, "version": 2, "updated_at": None}
        for name in ("signals", "listings", "market")
        if name != required_dataset
    ]

    checks = {
        check.measurements["dataset"]: check
        for check in _check_dataset_versions(_version_connection(rows))
    }

    assert checks[required_dataset].status == "fail"
    assert checks[required_dataset].reason == "dataset_version_missing"
    assert checks[required_dataset].measurements["version"] == 0


def test_public_signal_parity_compares_counts_only(monkeypatch):
    connection = FixtureConnection(
        [("FROM signal_card_read_model", {"raw_public_guest": 7})]
    )
    calls = []

    def fake_public_count(conn, **kwargs):
        calls.append((conn, kwargs))
        return 7

    monkeypatch.setattr(
        "services.data_trust_audit.count_signals_from_read_model",
        fake_public_count,
    )

    check = _check_public_signal_parity(connection)

    assert check.status == "pass"
    assert check.measurements == {"raw_public_guest": 7, "public_guest": 7}
    assert calls == [(connection, {"tier": "guest"})]
    sql, params = connection.queries[0]
    assert "COALESCE(mos_pct,0) >= ?" in sql
    assert "NOT possibly_duplicate" in sql
    assert "source = ANY(?)" in sql
    assert params == (15.0, ["facebook", "guland"])


def test_public_signal_parity_mismatch_fails(monkeypatch):
    connection = FixtureConnection(
        [("FROM signal_card_read_model", {"raw_public_guest": 7})]
    )
    monkeypatch.setattr(
        "services.data_trust_audit.count_signals_from_read_model",
        lambda conn, **kwargs: 6,
    )

    check = _check_public_signal_parity(connection)

    assert check.status == "fail"
    assert check.reason == "public_signal_count_mismatch"


def _map_row(**updates):
    row = {
        "candidates": 10,
        "mapped": 8,
        "exact_count": 2,
        "road_count": 2,
        "landmark_count": 1,
        "nearby_count": 1,
        "ward_count": 2,
        "invalid_precision": 0,
    }
    row.update(updates)
    return row


def test_map_coverage_reports_fixed_precision_buckets():
    check = _check_map_coverage(
        FixtureConnection([("AS candidates", _map_row())])
    )

    assert check.status == "pass"
    assert check.measurements == {
        "candidates": 10,
        "mapped": 8,
        "unmapped": 2,
        "precision": {
            "exact": 2,
            "road": 2,
            "landmark": 1,
            "nearby": 1,
            "ward": 2,
        },
        "invalid_precision": 0,
    }


@pytest.mark.parametrize(
    "updates",
    [
        {"mapped": 11},
        {"exact_count": 3},
        {"invalid_precision": 1},
    ],
)
def test_map_coverage_contradictions_fail(updates):
    check = _check_map_coverage(
        FixtureConnection([("AS candidates", _map_row(**updates))])
    )

    assert check.status == "fail"
    assert check.reason == "map_coverage_contradiction"


def test_no_map_candidates_is_explicitly_skipped():
    check = _check_map_coverage(
        FixtureConnection([("AS candidates", _map_row(candidates=0, mapped=0, exact_count=0, road_count=0, landmark_count=0, nearby_count=0, ward_count=0))])
    )

    assert check.status == "skipped"
    assert check.reason == "no_map_candidates"


def _publisher_row(**updates):
    row = {
        "total_publishers": 8,
        "stored_unknown": 1,
        "stored_low_manual": 3,
        "stored_high_activity": 2,
        "stored_automated_repost": 2,
        "effective_unknown": 1,
        "effective_low_manual": 4,
        "effective_high_activity": 1,
        "effective_automated_repost": 2,
        "invalid_class": 0,
        "invalid_override": 0,
        "invalid_effective": 0,
    }
    row.update(updates)
    return row


def test_publisher_policy_returns_class_counts_without_identities():
    check = _check_publisher_policy(
        FixtureConnection([("AS total_publishers", _publisher_row())])
    )

    assert check.status == "pass"
    assert set(check.measurements["stored_counts"]) == set(PUBLISHER_CLASSES)
    assert set(check.measurements["effective_counts"]) == set(PUBLISHER_CLASSES)
    rendered = json.dumps(check.as_dict())
    assert "publisher_key" not in rendered
    assert "display_name" not in rendered


@pytest.mark.parametrize(
    "updates",
    [
        {"invalid_class": 1},
        {"invalid_override": 1},
        {"invalid_effective": 1},
    ],
)
def test_invalid_publisher_policy_fails(updates):
    check = _check_publisher_policy(
        FixtureConnection([("AS total_publishers", _publisher_row(**updates))])
    )

    assert check.status == "fail"
    assert check.reason == "publisher_policy_invalid"


def test_no_guland_publishers_is_explicitly_skipped():
    check = _check_publisher_policy(
        FixtureConnection(
            [("AS total_publishers", _publisher_row(total_publishers=0))]
        )
    )

    assert check.status == "skipped"
    assert check.reason == "no_guland_publishers"


def test_extraction_quality_is_bounded_ordered_and_never_returns_samples():
    row = {"inspected": 3, **{f"{field}_flagged": 1 for field in EXTRACTION_FIELDS}}
    row["price_ty_flagged"] = 9
    connection = FixtureConnection([("AS inspected", row)])

    check = _check_extraction_quality(connection)

    assert check.status == "warn"
    assert check.measurements["inspected"] == 3
    assert list(check.measurements["flagged_counts"]) == list(EXTRACTION_FIELDS)
    assert check.measurements["flagged_counts"]["price_ty"] == 3
    assert connection.queries[0][1] == (10_000,)
    assert "ORDER BY l.id DESC" in connection.queries[0][0]
    assert "title" not in connection.queries[0][0].lower()
    assert "description" not in connection.queries[0][0].lower()
    assert "sample" not in json.dumps(check.as_dict()).lower()


def test_complete_serialized_report_drops_ignored_pii_sentinels(monkeypatch):
    sentinels = (
        "https://secret.example/listing?token=publisher-secret",
        "0900123456",
        "person@example.test",
        "203.0.113.42",
        "PrivateBrowser/99.0",
        "publisher-secret-key",
    )
    version_rows = [
        {
            "dataset_name": name,
            "version": 1,
            "updated_at": "2026-08-08T00:00:00Z",
            "ignored_url": sentinels[0],
        }
        for name in ("signals", "listings", "market")
    ]
    responses = [
        ("FROM public_dataset_versions", version_rows),
        ("AS raw_public_guest", {"raw_public_guest": 2, "ignored_phone": sentinels[1]}),
        ("AS candidates", _map_row()),
        ("AS total_publishers", _publisher_row(ignored_email=sentinels[2])),
        (
            "AS inspected",
            {
                "inspected": 2,
                **{f"{field}_flagged": 0 for field in EXTRACTION_FIELDS},
                "ignored_ip": sentinels[3],
                "ignored_user_agent": sentinels[4],
                "ignored_publisher_key": sentinels[5],
            },
        ),
    ]
    connection = AuditFixtureConnection(responses)
    monkeypatch.setattr(
        "services.data_trust_audit.count_signals_from_read_model",
        lambda conn, **kwargs: 2,
    )

    def safe_checks(conn):
        return [
            *_check_dataset_versions(conn),
            _check_public_signal_parity(conn),
            _check_map_coverage(conn),
            _check_publisher_policy(conn),
            _check_extraction_quality(conn),
        ]

    report = _run(connection, checks=(safe_checks,))
    rendered = json.dumps(report)

    for sentinel in sentinels:
        assert sentinel not in rendered

    forbidden_keys = {
        "url",
        "phone",
        "email",
        "ip",
        "user_agent",
        "title",
        "description",
        "publisher_key",
        "raw_json",
        "sample",
    }

    def walk_keys(value):
        if isinstance(value, dict):
            for key, nested in value.items():
                yield key
                yield from walk_keys(nested)
        elif isinstance(value, list):
            for nested in value:
                yield from walk_keys(nested)

    assert forbidden_keys.isdisjoint(key.lower() for key in walk_keys(report))


def _read_scope(conn):
    @contextmanager
    def manager():
        yield conn

    return manager()


def test_deep_false_never_calls_compare_functions(monkeypatch):
    import cli.system as system

    def forbidden(*_args, **_kwargs):
        raise AssertionError("deep comparison must stay lazy")

    monkeypatch.setattr(system, "compare_signal_read_model", forbidden)
    monkeypatch.setattr(system, "compare_listing_read_model", forbidden)

    checks = _check_deep_read_models(object(), deep=False, limit=20)

    assert [check.status for check in checks] == ["skipped", "skipped"]
    assert all(check.reason == "deep_not_requested" for check in checks)


def test_deep_comparisons_share_verified_connection(monkeypatch):
    import cli.system as system
    from services import market_data

    audit_conn = object()
    observed = []

    def compare_signal(limit):
        with market_data._read_conn() as conn:
            observed.append(("signals", conn, limit))
        return {
            "status": "ok",
            "compared_cases": 3,
            "difference_count": 0,
            "differences": [],
        }

    def compare_listing(limit):
        with market_data._read_conn() as conn:
            observed.append(("listings", conn, limit))
        return {
            "status": "ok",
            "compared_cases": 4,
            "difference_count": 0,
            "differences": [],
        }

    monkeypatch.setattr(system, "compare_signal_read_model", compare_signal)
    monkeypatch.setattr(system, "compare_listing_read_model", compare_listing)

    with market_data.use_read_connection_factory(lambda: _read_scope(audit_conn)):
        checks = _check_deep_read_models(audit_conn, deep=True, limit=7)

    assert observed == [
        ("signals", audit_conn, 7),
        ("listings", audit_conn, 7),
    ]
    assert [check.status for check in checks] == ["pass", "pass"]


def test_deep_mismatch_keeps_only_bounded_safe_diagnostics(monkeypatch):
    import cli.system as system

    differences = [
        {
            "case": "default",
            "tier": "guest",
            "legacy_count": 4,
            "read_model_count": 3,
            "legacy_only_ids": [9, 8, 7, 6],
            "read_model_only_ids": [5, 4, 3, 2],
            "order_mismatch": True,
            "field_names": ["price_ty", "ward", "title"],
            "metadata_fields": ["total", "pages", "has_more"],
            "url": "https://private.example/secret",
        },
        {
            "case": "facebook",
            "tier": "free",
            "legacy_count": 2,
            "read_model_count": 1,
            "legacy_only_ids": [11],
            "read_model_only_ids": [],
            "order_mismatch": False,
            "field_names": ["mos_pct"],
        },
        {"case": "third", "tier": "vip", "legacy_only_ids": [99]},
    ]
    monkeypatch.setattr(
        system,
        "compare_signal_read_model",
        lambda limit: {
            "status": "mismatch",
            "compared_cases": 36,
            "difference_count": 3,
            "differences": differences,
            "raw_rows": [{"phone": "0900123456"}],
        },
    )
    monkeypatch.setattr(
        system,
        "compare_listing_read_model",
        lambda limit: {
            "status": "ok",
            "compared_cases": 72,
            "difference_count": 0,
            "differences": [],
        },
    )

    checks = _check_deep_read_models(object(), deep=True, limit=2)
    signal_check = checks[0]
    rendered = json.dumps(signal_check.as_dict())

    assert signal_check.status == "fail"
    assert signal_check.reason == "read_model_mismatch"
    assert len(signal_check.measurements["differences"]) == 2
    first = signal_check.measurements["differences"][0]
    assert set(first) <= SAFE_DEEP_DIAGNOSTIC_KEYS
    assert first["legacy_only_ids"] == [9, 8]
    assert first["read_model_only_ids"] == [5, 4]
    assert first["field_names"] == ["price_ty", "ward"]
    assert "private.example" not in rendered
    assert "0900123456" not in rendered


def _production_audit_responses(now):
    tables = [{"table_name": name} for name in sorted(REQUIRED_TABLES)]
    columns = [
        {"table_name": table, "column_name": column}
        for table, names in REQUIRED_COLUMNS.items()
        for column in sorted(names)
    ]
    indexes = [{"indexname": name} for name in sorted(REQUIRED_INDEXES)]
    freshness = [
        {"source": "facebook", "latest_finished_at": now - timedelta(hours=1)},
        {"source": "guland", "latest_finished_at": now - timedelta(hours=2)},
    ]
    counts = _pipeline_connection().responses[0][1]
    invariants = _pipeline_connection().responses[1][1]
    versions = [
        {
            "dataset_name": name,
            "version": 1,
            "updated_at": now,
        }
        for name in ("signals", "listings", "market")
    ]
    extraction = {
        "inspected": 2,
        **{f"{field}_flagged": 0 for field in EXTRACTION_FIELDS},
    }
    return [
        ("FROM information_schema.tables", tables),
        ("FROM information_schema.columns", columns),
        ("FROM pg_indexes", indexes),
        ("FROM crawl_runs", freshness),
        ("AS raw_rows", counts),
        ("AS invalid_price", invariants),
        ("FROM public_dataset_versions", versions),
        ("AS raw_public_guest", {"raw_public_guest": 2}),
        ("AS candidates", _map_row()),
        ("AS total_publishers", _publisher_row()),
        ("AS inspected", extraction),
    ]


@pytest.mark.parametrize("deep", [False, True])
def test_default_and_deep_audits_have_no_mutation_path(monkeypatch, deep):
    import cli.system as system
    import db.schema as schema
    import services.public_data_publish as public_data_publish
    import services.public_prewarm as public_prewarm
    import services.signal_read_model as signal_read_model

    def forbidden(*_args, **_kwargs):
        raise AssertionError("audit attempted a mutation entry point")

    for module, name in (
        (schema, "init_schema"),
        (system, "init_schema"),
        (public_data_publish, "publish_public_data"),
        (signal_read_model, "refresh_signal_card_read_model"),
        (public_prewarm, "prewarm_public_routes"),
        (public_prewarm, "prewarm_configured_routes"),
    ):
        monkeypatch.setattr(module, name, forbidden)

    observed_connections = []

    def compare_report(limit):
        from services import market_data

        with market_data._read_conn() as conn:
            observed_connections.append(conn)
        return {
            "status": "ok",
            "compared_cases": 1,
            "difference_count": 0,
            "differences": [],
        }

    monkeypatch.setattr(system, "compare_signal_read_model", compare_report)
    monkeypatch.setattr(system, "compare_listing_read_model", compare_report)
    monkeypatch.setattr(
        "services.data_trust_audit.count_signals_from_read_model",
        lambda conn, **kwargs: 2,
    )
    now = datetime(2026, 8, 8, 12, tzinfo=timezone.utc)
    connection = AuditFixtureConnection(_production_audit_responses(now))

    report = _run(connection, deep=deep, limit=3, now=now)

    assert report["overall_status"] == "pass"
    assert len(observed_connections) == (2 if deep else 0)
    assert all(conn is connection for conn in observed_connections)
    forbidden_sql = {
        "INSERT",
        "UPDATE",
        "DELETE",
        "ALTER",
        "CREATE",
        "DROP",
        "TRUNCATE",
        "REFRESH",
        "VACUUM",
        "CALL",
    }
    for sql, _params in connection.statements:
        first_word = sql.lstrip().split(maxsplit=1)[0].upper()
        assert first_word not in forbidden_sql
