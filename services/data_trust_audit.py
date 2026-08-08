"""Bounded, fail-closed, read-only data trust auditing."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import math
import re
import time
from typing import Callable, ContextManager, Iterable, Mapping
from urllib.parse import unquote, urlsplit

from db import connection as db_connection
from db.connection import DatabaseConfigurationError, connect
from services.market_data import (
    _signal_listing_data_sql,
    use_read_connection_factory,
)
from services.signal_quality import (
    LATEST_VALUATION_CTE,
    actionable_listing_sql,
    actionable_signal_sql,
)


_IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9_]{0,79}$")
_STATUSES = frozenset({"pass", "warn", "fail", "skipped"})
_MAX_SAFE_STRING_LENGTH = 256
_MAX_COLLECTION_ITEMS = 1_000

REQUIRED_TABLES = frozenset(
    {
        "raw_listings",
        "listings",
        "valuation_results",
        "crawl_runs",
        "public_dataset_versions",
        "signal_card_read_model",
        "listing_map_locations",
        "source_publishers",
        "listing_publishers",
    }
)
REQUIRED_COLUMNS = {
    "raw_listings": frozenset({"id", "source", "crawled_at"}),
    "listings": frozenset(
        {
            "id",
            "source",
            "price_ty",
            "price_per_m2",
            "area_m2",
            "ward",
            "extraction_quality_flags",
            "measurement_provenance",
            "duplicate_of_id",
            "possibly_duplicate",
            "is_active",
            "probably_sold",
            "is_blacklisted",
            "review_hidden",
            "source_status",
            "first_seen_at",
        }
    ),
    "valuation_results": frozenset(
        {
            "id",
            "listing_id",
            "actual_ppm2",
            "is_signal",
            "source_quality_flags",
            "computed_at",
        }
    ),
    "crawl_runs": frozenset({"source", "status", "finished_at"}),
    "public_dataset_versions": frozenset(
        {"dataset_name", "version", "updated_at"}
    ),
    "signal_card_read_model": frozenset(
        {
            "listing_id",
            "price_ty",
            "area_m2",
            "actual_ppm2",
            "is_actionable",
            "publisher_visible_public",
        }
    ),
    "listing_map_locations": frozenset(
        {"listing_id", "location_precision", "resolution_status"}
    ),
    "source_publishers": frozenset(
        {"id", "source", "activity_class", "manual_override"}
    ),
    "listing_publishers": frozenset({"listing_id", "publisher_id"}),
}
REQUIRED_INDEXES = frozenset(
    {
        "idx_raw_source_crawled",
        "idx_listings_source_first_seen",
        "idx_valuation_listing_computed",
        "idx_signal_card_public_filter",
    }
)

_SOURCE_FRESHNESS_THRESHOLDS = {
    "facebook": {"pass_hours": 36, "fail_hours": 72},
    "guland": {"pass_hours": 96, "fail_hours": 168},
}
_SUCCESSFUL_CRAWL_STATUSES = ("done", "success", "completed")


def _safe_value(value, *, path="measurements"):
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} must contain only finite numbers")
        return value
    if isinstance(value, str):
        if len(value) > _MAX_SAFE_STRING_LENGTH:
            raise ValueError(f"{path} string is too long")
        if any(ord(char) < 32 for char in value):
            raise ValueError(f"{path} string contains control characters")
        return value
    if isinstance(value, Mapping):
        if len(value) > _MAX_COLLECTION_ITEMS:
            raise ValueError(f"{path} contains too many items")
        rendered = {}
        for key, nested in value.items():
            if not isinstance(key, str) or not _IDENTIFIER_RE.fullmatch(key):
                raise ValueError(f"{path} contains an unsafe key")
            rendered[key] = _safe_value(nested, path=f"{path}.{key}")
        return rendered
    if isinstance(value, (list, tuple)):
        if len(value) > _MAX_COLLECTION_ITEMS:
            raise ValueError(f"{path} contains too many items")
        return [
            _safe_value(nested, path=f"{path}[{index}]")
            for index, nested in enumerate(value)
        ]
    raise TypeError(f"{path} contains an unsupported value")


def _validate_identifier(value: str, field: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER_RE.fullmatch(value):
        raise ValueError(f"{field} must be a stable lowercase identifier")
    return value


@dataclass(frozen=True)
class AuditCheck:
    name: str
    status: str
    reason: str
    measurements: Mapping[str, object]
    threshold: Mapping[str, object] | None = None
    source_timestamp: str | None = None

    def __post_init__(self):
        _validate_identifier(self.name, "name")
        _validate_identifier(self.reason, "reason")
        if self.status not in _STATUSES:
            raise ValueError("status must be pass, warn, fail, or skipped")
        object.__setattr__(
            self,
            "measurements",
            _safe_value(self.measurements, path="measurements"),
        )
        if self.threshold is not None:
            object.__setattr__(
                self,
                "threshold",
                _safe_value(self.threshold, path="threshold"),
            )
        if self.source_timestamp is not None:
            object.__setattr__(
                self,
                "source_timestamp",
                _safe_value(self.source_timestamp, path="source_timestamp"),
            )

    def as_dict(self) -> dict[str, object]:
        result = {
            "name": self.name,
            "status": self.status,
            "reason": self.reason,
            "measurements": dict(self.measurements),
        }
        if self.threshold is not None:
            result["threshold"] = dict(self.threshold)
        if self.source_timestamp is not None:
            result["source_timestamp"] = self.source_timestamp
        return result


def mask_database_target(url: str) -> dict[str, object]:
    """Return only non-secret connection coordinates."""
    parsed = urlsplit((url or "").strip())
    try:
        port = parsed.port
    except ValueError:
        port = None
    database = unquote(parsed.path.rsplit("/", 1)[-1]) if parsed.path else ""
    return {
        "scheme": parsed.scheme,
        "host": parsed.hostname or "",
        "port": port,
        "database": database,
    }


@contextmanager
def _shared_connection_scope(conn):
    yield conn


def _row_value(row, key, default=None):
    if row is None:
        return default
    if isinstance(row, Mapping):
        return row.get(key, default)
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return default


def _bounded_count(row, key) -> int:
    value = int(_row_value(row, key, 0) or 0)
    if value < 0:
        raise ValueError("aggregate counts cannot be negative")
    return value


def _check_schema_contract(conn) -> AuditCheck:
    table_rows = conn.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema=? AND table_name = ANY(?)
        ORDER BY table_name
        """,
        ("public", sorted(REQUIRED_TABLES)),
    ).fetchall()
    column_rows = conn.execute(
        """
        SELECT table_name, column_name
        FROM information_schema.columns
        WHERE table_schema=? AND table_name = ANY(?)
        ORDER BY table_name, column_name
        """,
        ("public", sorted(REQUIRED_TABLES)),
    ).fetchall()
    index_rows = conn.execute(
        """
        SELECT indexname
        FROM pg_indexes
        WHERE schemaname=? AND indexname = ANY(?)
        ORDER BY indexname
        """,
        ("public", sorted(REQUIRED_INDEXES)),
    ).fetchall()

    present_tables = {
        str(_row_value(row, "table_name", "")) for row in table_rows
    }
    present_columns = {
        (
            str(_row_value(row, "table_name", "")),
            str(_row_value(row, "column_name", "")),
        )
        for row in column_rows
    }
    present_indexes = {
        str(_row_value(row, "indexname", "")) for row in index_rows
    }
    missing_tables = sorted(REQUIRED_TABLES - present_tables)
    missing_columns = sorted(
        f"{table}.{column}"
        for table, required in REQUIRED_COLUMNS.items()
        for column in required
        if (table, column) not in present_columns
    )
    missing_indexes = sorted(REQUIRED_INDEXES - present_indexes)
    missing = bool(missing_tables or missing_columns or missing_indexes)
    return AuditCheck(
        "schema_contract",
        "fail" if missing else "pass",
        "schema_contract_missing" if missing else "schema_contract_ready",
        {
            "required_tables": len(REQUIRED_TABLES),
            "required_columns": sum(map(len, REQUIRED_COLUMNS.values())),
            "required_indexes": len(REQUIRED_INDEXES),
            "missing_tables": missing_tables,
            "missing_columns": missing_columns,
            "missing_indexes": missing_indexes,
        },
    )


def _parse_timestamp(value) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        text = value.strip()
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _check_source_freshness(conn, now: datetime) -> tuple[AuditCheck, ...]:
    rows = conn.execute(
        """
        SELECT LOWER(source) AS source,
               MAX(finished_at) AS latest_finished_at
        FROM crawl_runs
        WHERE LOWER(source) = ANY(?)
          AND LOWER(status) = ANY(?)
        GROUP BY LOWER(source)
        ORDER BY LOWER(source)
        """,
        (
            sorted(_SOURCE_FRESHNESS_THRESHOLDS),
            list(_SUCCESSFUL_CRAWL_STATUSES),
        ),
    ).fetchall()
    latest_by_source = {
        str(_row_value(row, "source", "")).lower(): _row_value(
            row, "latest_finished_at"
        )
        for row in rows
        if str(_row_value(row, "source", "")).lower()
        in _SOURCE_FRESHNESS_THRESHOLDS
    }

    current = _utc_now(now)
    checks = []
    for source in ("facebook", "guland"):
        threshold = _SOURCE_FRESHNESS_THRESHOLDS[source]
        raw_timestamp = latest_by_source.get(source)
        if raw_timestamp is None:
            is_primary = source == "facebook"
            checks.append(
                AuditCheck(
                    f"source_freshness_{source}",
                    "fail" if is_primary else "warn",
                    (
                        "source_never_completed"
                        if is_primary
                        else "source_never_completed_secondary"
                    ),
                    {"source": source, "age_hours": None},
                    threshold=threshold,
                )
            )
            continue

        parsed = _parse_timestamp(raw_timestamp)
        if parsed is None:
            checks.append(
                AuditCheck(
                    f"source_freshness_{source}",
                    "fail",
                    "source_timestamp_invalid",
                    {"source": source, "age_hours": None},
                    threshold=threshold,
                )
            )
            continue

        age_hours = max(0.0, (current - parsed).total_seconds() / 3600.0)
        if age_hours <= threshold["pass_hours"]:
            status, reason = "pass", "source_fresh"
        elif age_hours <= threshold["fail_hours"]:
            status, reason = "warn", "source_stale_warning"
        else:
            status, reason = "fail", "source_stale_failure"
        checks.append(
            AuditCheck(
                f"source_freshness_{source}",
                status,
                reason,
                {"source": source, "age_hours": round(age_hours, 2)},
                threshold=threshold,
                source_timestamp=parsed.isoformat().replace("+00:00", "Z"),
            )
        )
    return tuple(checks)


def _check_pipeline_counts(conn) -> AuditCheck:
    visible_base = " AND ".join(
        [
            "COALESCE(l.is_active,1)=1",
            "COALESCE(l.probably_sold,0)=0",
            "COALESCE(l.is_blacklisted,0)=0",
            "COALESCE(l.review_hidden,0)=0",
            "COALESCE(l.source_status,'unknown') <> 'inactive'",
        ]
    )
    actionable = " AND ".join(
        [
            visible_base,
            "l.duplicate_of_id IS NULL",
            f"({actionable_listing_sql('l')})",
            f"({_signal_listing_data_sql('l')})",
            f"({actionable_signal_sql('v')})",
        ]
    )
    row = conn.execute(
        f"""
        WITH {LATEST_VALUATION_CTE}
        SELECT
            (SELECT COUNT(*) FROM raw_listings) AS raw_rows,
            (SELECT COUNT(*) FROM listings l
             WHERE l.duplicate_of_id IS NULL) AS canonical_listings,
            (SELECT COUNT(*) FROM listings l
             WHERE {visible_base}) AS active_visible_base,
            (SELECT COUNT(*) FROM latest_valuation) AS latest_valuations,
            (SELECT COUNT(*) FROM listings l
             JOIN latest_valuation v ON v.listing_id=l.id
             WHERE {actionable}) AS actionable_signals,
            (SELECT COUNT(*) FROM signal_card_read_model)
                AS read_model_base_cards,
            (SELECT COUNT(*) FROM signal_card_read_model
             WHERE is_actionable) AS read_model_actionable_cards
        """
    ).fetchone()
    keys = (
        "raw_rows",
        "canonical_listings",
        "active_visible_base",
        "latest_valuations",
        "actionable_signals",
        "read_model_base_cards",
        "read_model_actionable_cards",
    )
    counts = {key: _bounded_count(row, key) for key in keys}
    contradictory = (
        counts["actionable_signals"] > counts["latest_valuations"]
        or counts["actionable_signals"] > counts["active_visible_base"]
        or counts["read_model_actionable_cards"]
        > counts["read_model_base_cards"]
    )
    if contradictory:
        status, reason = "fail", "pipeline_count_contradiction"
    elif counts["raw_rows"] == 0 and counts["canonical_listings"] == 0:
        status, reason = "warn", "empty_dataset"
    else:
        status, reason = "pass", "pipeline_counts_consistent"
    return AuditCheck("pipeline_counts", status, reason, counts)


def _check_pipeline_invariants(conn) -> AuditCheck:
    current_quality = " AND ".join(
        [
            f"({actionable_signal_sql('v')})",
            f"({_signal_listing_data_sql('l')})",
        ]
    )
    listing_visible = " AND ".join(
        [
            f"({actionable_listing_sql('l')})",
            "l.duplicate_of_id IS NULL",
            "COALESCE(l.is_active,1)=1",
        ]
    )
    row = conn.execute(
        f"""
        WITH {LATEST_VALUATION_CTE}
        SELECT
            COUNT(*) AS actionable_rows,
            COUNT(*) FILTER (
                WHERE rm.price_ty IS NULL OR rm.price_ty <= 0
            ) AS invalid_price,
            COUNT(*) FILTER (
                WHERE rm.area_m2 IS NULL OR rm.area_m2 <= 0
            ) AS invalid_area,
            COUNT(*) FILTER (
                WHERE rm.actual_ppm2 IS NULL OR rm.actual_ppm2 <= 0
            ) AS invalid_actual_ppm2,
            COUNT(*) FILTER (
                WHERE COALESCE(l.source_status,'unknown')='inactive'
                   OR COALESCE(l.is_active,1)=0
                   OR COALESCE(l.probably_sold,0)=1
            ) AS suppressed_source_status,
            COUNT(*) FILTER (
                WHERE NOT ({listing_visible})
                   OR COALESCE(l.is_blacklisted,0)=1
                   OR COALESCE(l.review_hidden,0)=1
            ) AS hidden_or_suppressed_listing,
            COUNT(*) FILTER (
                WHERE NOT ({current_quality})
            ) AS non_actionable_quality
        FROM signal_card_read_model rm
        JOIN listings l ON l.id=rm.listing_id
        LEFT JOIN latest_valuation v ON v.listing_id=l.id
        WHERE rm.is_actionable
        """
    ).fetchone()
    violation_keys = (
        "invalid_price",
        "invalid_area",
        "invalid_actual_ppm2",
        "suppressed_source_status",
        "hidden_or_suppressed_listing",
        "non_actionable_quality",
    )
    violations = {key: _bounded_count(row, key) for key in violation_keys}
    failed = any(violations.values())
    return AuditCheck(
        "pipeline_invariants",
        "fail" if failed else "pass",
        "pipeline_invariant_violation" if failed else "pipeline_invariants_hold",
        {
            "actionable_rows": _bounded_count(row, "actionable_rows"),
            "violations": violations,
        },
    )


def _run_default_checks(conn, *, now: datetime, limit: int, deep: bool):
    del limit, deep
    schema = _check_schema_contract(conn)
    checks = [schema]
    if schema.status == "fail":
        return checks
    checks.extend(_check_source_freshness(conn, now))
    checks.append(_check_pipeline_counts(conn))
    checks.append(_check_pipeline_invariants(conn))
    return checks


def _flatten_checks(value) -> Iterable[AuditCheck]:
    if isinstance(value, AuditCheck):
        yield value
        return
    if isinstance(value, Iterable):
        for item in value:
            if not isinstance(item, AuditCheck):
                raise TypeError("audit checks must return AuditCheck values")
            yield item
        return
    raise TypeError("audit check returned an unsupported value")


def _looks_like_timeout(exc: BaseException) -> bool:
    names = " ".join(cls.__name__.lower() for cls in type(exc).__mro__)
    return "timeout" in names or "querycanceled" in names or "querycancelled" in names


def _overall_status(checks: list[AuditCheck]) -> str:
    if any(check.status == "fail" for check in checks):
        return "fail"
    if any(check.status == "warn" for check in checks):
        return "warn"
    return "pass"


def _utc_now(value: datetime | None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)


def run_data_trust_audit(
    *,
    deep: bool = False,
    limit: int = 200,
    statement_timeout_ms: int = 15_000,
    connection_factory: Callable[[], object] = connect,
    now: datetime | None = None,
    checks: Iterable[Callable[[object], object]] | None = None,
) -> dict[str, object]:
    """Run checks inside one verified read-only PostgreSQL transaction.

    ``checks`` is an injection seam for tests. Production callers leave it as
    ``None`` so only the frozen internal registry is used.
    """
    started = time.perf_counter()
    bounded_limit = min(max(int(limit), 1), 1_000)
    bounded_timeout = min(max(int(statement_timeout_ms), 1_000), 60_000)
    generated_at = _utc_now(now).isoformat().replace("+00:00", "Z")
    conn = None
    collected: list[AuditCheck] = []
    failure_reason = None
    interrupted = None

    try:
        configured_url = db_connection._database_url()
        target = mask_database_target(configured_url)
    except BaseException as exc:
        if isinstance(exc, KeyboardInterrupt):
            raise
        target = {"scheme": "", "host": "", "port": None, "database": ""}
        failure_reason = "database_configuration_error"
    else:
        try:
            conn = connection_factory()
            conn.execute("BEGIN")
            conn.execute("SET TRANSACTION READ ONLY")
            conn.execute(
                "SELECT set_config('statement_timeout', ?, true)",
                (f"{bounded_timeout}ms",),
            )
            state_row = conn.execute("SHOW transaction_read_only").fetchone()
            state = state_row[0] if state_row is not None else None
            if str(state).lower() != "on":
                failure_reason = "read_only_state_unverified"
            else:
                collected.append(
                    AuditCheck(
                        "transaction_read_only",
                        "pass",
                        "read_only_verified",
                        {"statement_timeout_ms": bounded_timeout},
                    )
                )
                with use_read_connection_factory(
                    lambda: _shared_connection_scope(conn)
                ):
                    if checks is None:
                        collected.extend(
                            _flatten_checks(
                                _run_default_checks(
                                    conn,
                                    now=_utc_now(now),
                                    limit=bounded_limit,
                                    deep=bool(deep),
                                )
                            )
                        )
                    else:
                        for check in tuple(checks):
                            collected.extend(_flatten_checks(check(conn)))
        except KeyboardInterrupt as exc:
            interrupted = exc
        except BaseException as exc:
            if _looks_like_timeout(exc):
                failure_reason = "statement_timeout"
            elif isinstance(exc, DatabaseConfigurationError):
                failure_reason = "database_configuration_error"
            elif conn is None:
                failure_reason = "database_connection_error"
            else:
                failure_reason = "audit_execution_error"
        finally:
            cleanup_failed = False
            if conn is not None:
                try:
                    conn.rollback()
                except BaseException:
                    cleanup_failed = True
                try:
                    conn.close()
                except BaseException:
                    cleanup_failed = True
            if cleanup_failed and failure_reason is None and interrupted is None:
                failure_reason = "cleanup_error"

    if interrupted is not None:
        raise interrupted

    duration_ms = max(0, int((time.perf_counter() - started) * 1_000))
    report: dict[str, object] = {
        "overall_status": (
            "unverified" if failure_reason is not None else _overall_status(collected)
        ),
        "target": target,
        "generated_at": generated_at,
        "duration_ms": duration_ms,
        "deep": bool(deep),
        "limit": bounded_limit,
        "checks": [check.as_dict() for check in collected],
    }
    if failure_reason is not None:
        report["reason"] = failure_reason
    return report
