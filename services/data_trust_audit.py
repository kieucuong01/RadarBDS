"""Bounded, fail-closed, read-only data trust auditing."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import math
import os
import re
import time
from typing import Callable, ContextManager, Iterable, Mapping
from urllib.parse import unquote, urlsplit

from db import connection as db_connection
from db.connection import DatabaseConfigurationError, connect
from db.guland_publishers import publisher_effective_class_from_join_sql
from services.market_data import (
    DEFAULT_VISIBLE_SOURCES,
    _signal_listing_data_sql,
    use_read_connection_factory,
)
from services.signal_quality import (
    DEFAULT_SIGNAL_MOS_MIN_PCT,
    LATEST_VALUATION_CTE,
    actionable_listing_sql,
    actionable_signal_sql,
)
from services.signal_read_model import count_signals_from_read_model


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
MAP_PRECISIONS = ("exact", "road", "landmark", "nearby", "ward")
PUBLISHER_CLASSES = (
    "unknown",
    "low_manual",
    "high_activity",
    "automated_repost",
)
EXTRACTION_FIELDS = (
    "price_ty",
    "area_m2",
    "ward",
    "road_name",
    "property_type",
    "frontage_m",
    "depth_m",
    "tho_cu_m2",
)
SAFE_DEEP_DIAGNOSTIC_KEYS = frozenset(
    {
        "case",
        "tier",
        "legacy_count",
        "read_model_count",
        "legacy_only_ids",
        "read_model_only_ids",
        "order_mismatch",
        "field_names",
        "metadata_fields",
    }
)


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


def _feature_flags() -> dict[str, bool]:
    signal_enabled = (
        os.getenv("RADAR_SIGNAL_READ_MODEL_ENABLED", "0").strip() == "1"
    )
    return {
        "signals": signal_enabled,
        "listings": (
            signal_enabled
            and os.getenv("RADAR_LISTING_READ_MODEL_ENABLED", "1").strip()
            != "0"
        ),
        "market": os.getenv("RADAR_PUBLIC_CACHE_ENABLED", "0").strip() == "1",
    }


def _check_dataset_versions(conn) -> tuple[AuditCheck, ...]:
    rows = conn.execute(
        """
        SELECT dataset_name, version, updated_at
        FROM public_dataset_versions
        WHERE dataset_name = ANY(?)
        ORDER BY dataset_name
        """,
        (list(("signals", "listings", "market")),),
    ).fetchall()
    found = {
        str(_row_value(row, "dataset_name", "")): row
        for row in rows
        if str(_row_value(row, "dataset_name", ""))
        in {"signals", "listings", "market"}
    }
    required = _feature_flags()
    checks = []
    for dataset in ("signals", "listings", "market"):
        row = found.get(dataset)
        invalid_version = False
        try:
            version = int(_row_value(row, "version", 0) or 0)
        except (TypeError, ValueError, OverflowError):
            version = 0
            invalid_version = True
        parsed_timestamp = _parse_timestamp(_row_value(row, "updated_at"))
        is_required = required[dataset]
        if invalid_version or version < 0:
            status, reason = "fail", "dataset_version_invalid"
            version = max(version, 0)
        elif is_required and version <= 0:
            status, reason = "fail", "dataset_version_missing"
        elif is_required:
            status, reason = "pass", "dataset_version_ready"
        else:
            status, reason = "skipped", "dataset_version_optional"
        checks.append(
            AuditCheck(
                f"dataset_version_{dataset}",
                status,
                reason,
                {
                    "dataset": dataset,
                    "version": version,
                    "required": is_required,
                },
                source_timestamp=(
                    parsed_timestamp.isoformat().replace("+00:00", "Z")
                    if parsed_timestamp is not None
                    else None
                ),
            )
        )
    return tuple(checks)


def _check_public_signal_parity(conn) -> AuditCheck:
    row = conn.execute(
        """
        SELECT COUNT(*) AS raw_public_guest
        FROM signal_card_read_model rm
        WHERE is_actionable
          AND publisher_visible_public
          AND COALESCE(mos_pct,0) >= ?
          AND NOT possibly_duplicate
          AND source = ANY(?)
        """,
        (float(DEFAULT_SIGNAL_MOS_MIN_PCT), list(DEFAULT_VISIBLE_SOURCES)),
    ).fetchone()
    raw_public_guest = _bounded_count(row, "raw_public_guest")
    public_guest = int(count_signals_from_read_model(conn, tier="guest"))
    if public_guest < 0:
        raise ValueError("public signal count cannot be negative")
    matches = raw_public_guest == public_guest
    return AuditCheck(
        "public_signal_parity",
        "pass" if matches else "fail",
        "public_signal_count_match" if matches else "public_signal_count_mismatch",
        {"raw_public_guest": raw_public_guest, "public_guest": public_guest},
    )


def _check_map_coverage(conn) -> AuditCheck:
    precision_selects = ",\n".join(
        f"""COUNT(*) FILTER (
                WHERE ml.resolution_status='resolved'
                  AND ml.location_precision='{precision}'
            ) AS {precision}_count"""
        for precision in MAP_PRECISIONS
    )
    allowed = ",".join(f"'{precision}'" for precision in MAP_PRECISIONS)
    row = conn.execute(
        f"""
        SELECT
            COUNT(*) AS candidates,
            COUNT(*) FILTER (
                WHERE ml.listing_id IS NOT NULL
                  AND ml.resolution_status='resolved'
                  AND ml.location_precision IN ({allowed})
            ) AS mapped,
            {precision_selects},
            COUNT(*) FILTER (
                WHERE ml.listing_id IS NOT NULL
                  AND ml.resolution_status='resolved'
                  AND (
                    ml.location_precision IS NULL
                    OR ml.location_precision NOT IN ({allowed})
                  )
            ) AS invalid_precision
        FROM listings l
        LEFT JOIN listing_map_locations ml ON ml.listing_id=l.id
        WHERE COALESCE(l.probably_sold,0)=0
          AND COALESCE(l.is_blacklisted,0)=0
          AND COALESCE(l.review_hidden,0)=0
        """
    ).fetchone()
    candidates = _bounded_count(row, "candidates")
    mapped = _bounded_count(row, "mapped")
    invalid_precision = _bounded_count(row, "invalid_precision")
    precision = {
        name: _bounded_count(row, f"{name}_count") for name in MAP_PRECISIONS
    }
    unmapped = max(candidates - mapped, 0)
    measurements = {
        "candidates": candidates,
        "mapped": mapped,
        "unmapped": unmapped,
        "precision": precision,
        "invalid_precision": invalid_precision,
    }
    if candidates == 0:
        return AuditCheck(
            "map_coverage", "skipped", "no_map_candidates", measurements
        )
    contradictory = (
        mapped > candidates
        or mapped + unmapped != candidates
        or sum(precision.values()) != mapped
        or invalid_precision > 0
    )
    return AuditCheck(
        "map_coverage",
        "fail" if contradictory else "pass",
        "map_coverage_contradiction" if contradictory else "map_coverage_consistent",
        measurements,
    )


def _check_publisher_policy(conn) -> AuditCheck:
    effective = publisher_effective_class_from_join_sql("sp")
    stored_counts_sql = ",\n".join(
        f"COUNT(*) FILTER (WHERE sp.activity_class='{name}') AS stored_{name}"
        for name in PUBLISHER_CLASSES
    )
    effective_counts_sql = ",\n".join(
        f"COUNT(*) FILTER (WHERE ({effective})='{name}') AS effective_{name}"
        for name in PUBLISHER_CLASSES
    )
    allowed_classes = ",".join(f"'{name}'" for name in PUBLISHER_CLASSES)
    row = conn.execute(
        f"""
        SELECT
            COUNT(*) AS total_publishers,
            {stored_counts_sql},
            {effective_counts_sql},
            COUNT(*) FILTER (
                WHERE sp.activity_class NOT IN ({allowed_classes})
            ) AS invalid_class,
            COUNT(*) FILTER (
                WHERE sp.manual_override NOT IN ('','allow_manual','hide_high_activity')
                   OR sp.manual_override IS NULL
            ) AS invalid_override,
            COUNT(*) FILTER (
                WHERE ({effective}) NOT IN ({allowed_classes})
            ) AS invalid_effective
        FROM source_publishers sp
        WHERE sp.source='guland'
        """
    ).fetchone()
    total = _bounded_count(row, "total_publishers")
    stored = {
        name: min(_bounded_count(row, f"stored_{name}"), total)
        for name in PUBLISHER_CLASSES
    }
    effective_counts = {
        name: min(_bounded_count(row, f"effective_{name}"), total)
        for name in PUBLISHER_CLASSES
    }
    invalid_class = _bounded_count(row, "invalid_class")
    invalid_override = _bounded_count(row, "invalid_override")
    invalid_effective = _bounded_count(row, "invalid_effective")
    measurements = {
        "total_publishers": total,
        "stored_counts": stored,
        "effective_counts": effective_counts,
        "invalid_class_count": invalid_class,
        "invalid_override_count": invalid_override,
        "invalid_effective_count": invalid_effective,
    }
    if total == 0:
        return AuditCheck(
            "publisher_policy", "skipped", "no_guland_publishers", measurements
        )
    invalid = bool(invalid_class or invalid_override or invalid_effective)
    contradictory = (
        sum(stored.values()) + invalid_class != total
        or sum(effective_counts.values()) + invalid_effective != total
    )
    return AuditCheck(
        "publisher_policy",
        "fail" if invalid or contradictory else "pass",
        (
            "publisher_policy_invalid"
            if invalid
            else "publisher_policy_contradiction"
            if contradictory
            else "publisher_policy_valid"
        ),
        measurements,
    )


def _check_extraction_quality(conn) -> AuditCheck:
    row = conn.execute(
        """
        WITH inspected_rows AS MATERIALIZED (
            SELECT l.id, l.price_ty, l.area_m2, l.ward, l.road_name,
                   l.property_type, l.frontage_m, l.depth_m, l.tho_cu_m2,
                   l.extraction_quality_flags, l.measurement_provenance
            FROM listings l
            WHERE l.duplicate_of_id IS NULL
            ORDER BY l.id DESC
            LIMIT ?
        )
        SELECT
            COUNT(*) AS inspected,
            COUNT(*) FILTER (
                WHERE price_ty IS NULL OR price_ty <= 0
                   OR LOWER(COALESCE(extraction_quality_flags,'')) LIKE '%price%'
            ) AS price_ty_flagged,
            COUNT(*) FILTER (
                WHERE area_m2 IS NULL OR area_m2 <= 0
                   OR LOWER(COALESCE(extraction_quality_flags,'')) LIKE '%area%'
                   OR LOWER(COALESCE(measurement_provenance,''))
                      ~ '"area_m2"[[:space:]]*:[[:space:]]*"unknown"'
            ) AS area_m2_flagged,
            COUNT(*) FILTER (
                WHERE NULLIF(TRIM(COALESCE(ward,'')), '') IS NULL
                   OR LOWER(COALESCE(extraction_quality_flags,'')) LIKE '%ward%'
            ) AS ward_flagged,
            COUNT(*) FILTER (
                WHERE NULLIF(TRIM(COALESCE(road_name,'')), '') IS NULL
                   OR LOWER(COALESCE(extraction_quality_flags,'')) LIKE '%road%'
            ) AS road_name_flagged,
            COUNT(*) FILTER (
                WHERE NULLIF(TRIM(COALESCE(property_type,'')), '') IS NULL
                   OR LOWER(COALESCE(property_type,''))='unknown'
                   OR LOWER(COALESCE(extraction_quality_flags,'')) LIKE '%category%'
                   OR LOWER(COALESCE(extraction_quality_flags,'')) LIKE '%property%'
            ) AS property_type_flagged,
            COUNT(*) FILTER (
                WHERE frontage_m IS NULL OR frontage_m <= 0
                   OR LOWER(COALESCE(extraction_quality_flags,'')) LIKE '%frontage%'
                   OR LOWER(COALESCE(measurement_provenance,''))
                      ~ '"frontage_m"[[:space:]]*:[[:space:]]*"unknown"'
            ) AS frontage_m_flagged,
            COUNT(*) FILTER (
                WHERE depth_m IS NULL OR depth_m <= 0
                   OR LOWER(COALESCE(extraction_quality_flags,'')) LIKE '%depth%'
                   OR LOWER(COALESCE(measurement_provenance,''))
                      ~ '"depth_m"[[:space:]]*:[[:space:]]*"unknown"'
            ) AS depth_m_flagged,
            COUNT(*) FILTER (
                WHERE tho_cu_m2 IS NULL OR tho_cu_m2 < 0
                   OR (area_m2 > 0 AND tho_cu_m2 > area_m2)
                   OR LOWER(COALESCE(extraction_quality_flags,'')) LIKE '%tho_cu%'
                   OR LOWER(COALESCE(measurement_provenance,''))
                      ~ '"tho_cu_m2"[[:space:]]*:[[:space:]]*"unknown"'
            ) AS tho_cu_m2_flagged
        FROM inspected_rows
        """,
        (10_000,),
    ).fetchone()
    inspected = min(_bounded_count(row, "inspected"), 10_000)
    flagged_counts = {
        field: min(_bounded_count(row, f"{field}_flagged"), inspected)
        for field in EXTRACTION_FIELDS
    }
    flagged = any(flagged_counts.values())
    return AuditCheck(
        "extraction_quality",
        "warn" if flagged else "pass",
        "extraction_flags_present" if flagged else "extraction_quality_clean",
        {"inspected": inspected, "flagged_counts": flagged_counts},
        threshold={"inspection_limit": 10_000},
    )


def _deep_token(value) -> str:
    text = str(value or "").strip().lower()
    return text if _IDENTIFIER_RE.fullmatch(text) else "invalid"


def _deep_count(value) -> int:
    try:
        return max(int(value or 0), 0)
    except (TypeError, ValueError, OverflowError):
        return 0


def _deep_ids(value, limit: int) -> list[int]:
    if not isinstance(value, (list, tuple)):
        return []
    result = []
    for item in value:
        try:
            listing_id = int(item)
        except (TypeError, ValueError, OverflowError):
            continue
        if listing_id >= 0:
            result.append(listing_id)
        if len(result) >= limit:
            break
    return result


def _deep_fields(value, limit: int) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [_deep_token(item) for item in value[:limit]]


def _safe_deep_differences(value, limit: int) -> list[dict[str, object]]:
    if not isinstance(value, (list, tuple)):
        return []
    safe = []
    for raw in value[:limit]:
        if not isinstance(raw, Mapping):
            continue
        diagnostic = {}
        for key in (
            "case",
            "tier",
            "legacy_count",
            "read_model_count",
            "legacy_only_ids",
            "read_model_only_ids",
            "order_mismatch",
            "field_names",
            "metadata_fields",
        ):
            if key not in raw:
                continue
            if key in {"case", "tier"}:
                diagnostic[key] = _deep_token(raw[key])
            elif key in {"legacy_count", "read_model_count"}:
                diagnostic[key] = _deep_count(raw[key])
            elif key in {"legacy_only_ids", "read_model_only_ids"}:
                diagnostic[key] = _deep_ids(raw[key], limit)
            elif key == "order_mismatch":
                diagnostic[key] = bool(raw[key])
            else:
                diagnostic[key] = _deep_fields(raw[key], limit)
        safe.append(diagnostic)
    return safe


def _deep_check(name: str, report: Mapping[str, object], limit: int) -> AuditCheck:
    source_status = str(report.get("status") or "").strip().lower()
    if source_status not in {"ok", "mismatch"}:
        raise ValueError("deep comparison returned an unknown status")
    differences = _safe_deep_differences(report.get("differences"), limit)
    difference_count = _deep_count(report.get("difference_count"))
    mismatch = (
        source_status == "mismatch" or difference_count > 0 or bool(differences)
    )
    return AuditCheck(
        name,
        "fail" if mismatch else "pass",
        "read_model_mismatch" if mismatch else "read_model_match",
        {
            "compared_cases": _deep_count(report.get("compared_cases")),
            "difference_count": difference_count,
            "differences": differences,
        },
        threshold={"diagnostic_limit": limit},
    )


def _check_deep_read_models(
    _conn,
    *,
    deep: bool,
    limit: int,
) -> tuple[AuditCheck, AuditCheck]:
    bounded_limit = min(max(int(limit), 1), 1_000)
    if not deep:
        measurements = {"diagnostic_limit": bounded_limit}
        return (
            AuditCheck(
                "deep_signal_read_model",
                "skipped",
                "deep_not_requested",
                measurements,
            ),
            AuditCheck(
                "deep_listing_read_model",
                "skipped",
                "deep_not_requested",
                measurements,
            ),
        )

    from cli.system import compare_listing_read_model, compare_signal_read_model

    signal_report = compare_signal_read_model(bounded_limit)
    listing_report = compare_listing_read_model(bounded_limit)
    return (
        _deep_check("deep_signal_read_model", signal_report, bounded_limit),
        _deep_check("deep_listing_read_model", listing_report, bounded_limit),
    )


def _run_default_checks(conn, *, now: datetime, limit: int, deep: bool):
    schema = _check_schema_contract(conn)
    checks = [schema]
    if schema.status == "fail":
        return checks
    checks.extend(_check_source_freshness(conn, now))
    checks.append(_check_pipeline_counts(conn))
    checks.append(_check_pipeline_invariants(conn))
    checks.extend(_check_dataset_versions(conn))
    checks.append(_check_public_signal_parity(conn))
    checks.append(_check_map_coverage(conn))
    checks.append(_check_publisher_policy(conn))
    checks.append(_check_extraction_quality(conn))
    checks.extend(_check_deep_read_models(conn, deep=deep, limit=limit))
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
