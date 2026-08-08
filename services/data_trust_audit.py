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
from services.market_data import use_read_connection_factory


_IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9_]{0,79}$")
_STATUSES = frozenset({"pass", "warn", "fail", "skipped"})
_MAX_SAFE_STRING_LENGTH = 256
_MAX_COLLECTION_ITEMS = 1_000


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


def _default_checks(_conn) -> tuple[AuditCheck, ...]:
    return ()


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
                registry = tuple(checks) if checks is not None else (_default_checks,)
                with use_read_connection_factory(
                    lambda: _shared_connection_scope(conn)
                ):
                    for check in registry:
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
