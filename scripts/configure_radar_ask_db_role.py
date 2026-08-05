"""Create and audit the fail-closed PostgreSQL boundary for Radar Ask.

Run with an owner connection. The evidence role receives SELECT on an exact
safe-view manifest and never receives privileges on application base tables.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import urlparse

import psycopg
from psycopg import sql

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import config.settings  # noqa: F401  # load project env files
from services.tphcm_land_prices import land_price_row_key


READ_ROLE = "radar_ask_ro"
VIEW_OWNER_ROLE = "radar_ask_view_owner"
FOUNDATION_SAFE_VIEWS = (
    "radar_ask_v_listings",
    "radar_ask_v_valuations",
    "radar_ask_v_price_history",
    "radar_ask_v_lot_history",
    "radar_ask_v_signal_cards",
    "radar_ask_v_official_land_prices",
)
KNOWLEDGE_SAFE_VIEWS = (*FOUNDATION_SAFE_VIEWS, "radar_ask_v_knowledge_chunks")
OFFICIAL_DATA_PATH = (
    PROJECT_ROOT
    / "static"
    / "data"
    / "tphcm_land_prices_2026.json"
)
OFFICIAL_SOURCE_HOSTS = frozenset({"congbao.hochiminhcity.gov.vn"})
OPTIONAL_VECTOR_FUNCTIONS = (
    (
        "radar_ask_vector_readiness",
        "",
        "public.radar_ask_vector_readiness()",
    ),
    (
        "radar_ask_semantic_search",
        "vector, text, integer",
        "public.radar_ask_semantic_search(vector,text,integer)",
    ),
)


BASE_COLUMN_GRANTS: dict[str, tuple[str, ...]] = {
    "listings": (
        "id",
        "source",
        "title",
        "area",
        "price_ty",
        "price_per_m2",
        "area_m2",
        "property_type",
        "frontage_m",
        "depth_m",
        "road_name",
        "road_width_m",
        "road_type",
        "road_tier",
        "tho_cu_m2",
        "tho_cu_ratio",
        "has_so",
        "price_dropped",
        "price_drop_pct",
        "price_first_ty",
        "possibly_duplicate",
        "duplicate_of_id",
        "first_seen_at",
        "last_seen_at",
        "posted_at",
        "crawled_at",
        "is_active",
        "probably_sold",
        "review_hidden",
        "is_blacklisted",
        "suspicious_bait",
        "extraction_quality_flags",
        "measurement_provenance",
    ),
    "valuation_results": (
        "id",
        "model_run_id",
        "listing_id",
        "fair_ppm2",
        "actual_ppm2",
        "mos_pct",
        "is_signal",
        "signal_score",
        "segment",
        "n_segment",
        "source_quality_flags",
        "source_quality_recheck",
        "legal_status",
        "trust_tier",
        "trust_score",
        "legal_flags",
        "valuation_trace",
        "computed_at",
    ),
    "price_history": (
        "id",
        "listing_id",
        "price_ty",
        "price_per_m2",
        "recorded_at",
    ),
    "signal_card_read_model": (
        "listing_id",
        "title",
        "source",
        "source_status",
        "ward",
        "property_type",
        "area_m2",
        "frontage_m",
        "depth_m",
        "price_ty",
        "listing_price_per_m2",
        "actual_ppm2",
        "fair_ppm2",
        "mos_pct",
        "signal_score",
        "is_actionable",
        "listing_is_signal",
        "is_hot",
        "possibly_duplicate",
        "price_dropped",
        "price_drop_pct",
        "price_first_ty",
        "suspicious_bait",
        "activity_at",
        "posted_at",
        "first_seen_at",
        "price_updated_at",
        "road_name",
        "road_type",
        "road_width_m",
        "road_tier",
        "tho_cu_m2",
        "tho_cu_ratio",
        "has_so",
        "trust_tier",
        "trust_score",
        "legal_status",
        "legal_flags",
        "source_quality_flags",
        "source_quality_recheck",
        "publisher_visible_public",
        "refreshed_at",
    ),
    "radar_ask_official_land_price_rows": (
        "row_key",
        "area",
        "appendix",
        "stt",
        "street",
        "segment_from",
        "segment_to",
        "residential",
        "commerce_service",
        "production_business",
        "page",
        "search_text",
        "source_title",
        "source_url",
        "data_as_of",
        "unit",
    ),
}

KNOWLEDGE_COLUMN_GRANTS: dict[str, tuple[str, ...]] = {
    "knowledge_sources": (
        "id",
        "slug",
        "title",
        "canonical_url",
        "trust_class",
        "jurisdiction",
        "active",
    ),
    "knowledge_documents": (
        "id",
        "source_id",
        "title",
        "version",
        "published_at",
        "effective_from",
        "effective_to",
        "imported_at",
    ),
    "knowledge_chunks": (
        "id",
        "document_id",
        "chunk_index",
        "chunk_text",
        "normalized_text",
        "token_count",
        "content_sha256",
        "search_vector",
    ),
}


FOUNDATION_VIEW_SQL: tuple[str, ...] = (
    """
    CREATE OR REPLACE VIEW public.radar_ask_v_listings
    WITH (security_barrier=true, security_invoker=false) AS
    SELECT
        l.id::bigint AS listing_id,
        l.source,
        l.title,
        l.area AS ward,
        l.price_ty,
        l.price_per_m2,
        l.area_m2,
        l.property_type,
        l.frontage_m,
        l.depth_m,
        l.road_name,
        l.road_width_m,
        l.road_type,
        l.tho_cu_m2,
        l.tho_cu_ratio,
        (l.has_so = 1) AS has_so,
        (l.price_dropped = 1) AS price_dropped,
        l.price_drop_pct,
        l.price_first_ty,
        (l.possibly_duplicate = 1) AS possibly_duplicate,
        l.duplicate_of_id::bigint AS duplicate_of_id,
        l.first_seen_at,
        l.last_seen_at,
        l.posted_at,
        l.crawled_at,
        (l.is_active = 1) AS is_active,
        (l.probably_sold = 1) AS probably_sold,
        l.measurement_provenance,
        l.extraction_quality_flags,
        (l.suspicious_bait = 1) AS suspicious_bait,
        (
            COALESCE(l.review_hidden, 0) = 0
            AND COALESCE(l.is_blacklisted, 0) = 0
            AND COALESCE(l.probably_sold, 0) = 0
            AND COALESCE(l.is_active, 1) = 1
            AND COALESCE(s.publisher_visible_public, TRUE)
        ) AS public_visible
        , l.road_tier
    FROM public.listings l
    LEFT JOIN public.signal_card_read_model s ON s.listing_id = l.id
    """,
    """
    CREATE OR REPLACE VIEW public.radar_ask_v_valuations
    WITH (security_barrier=true, security_invoker=false) AS
    SELECT
        v.id::bigint AS valuation_id,
        v.model_run_id::bigint AS model_run_id,
        v.listing_id::bigint AS listing_id,
        v.fair_ppm2,
        v.actual_ppm2,
        v.mos_pct,
        (v.is_signal = 1) AS is_signal,
        v.signal_score,
        v.segment,
        v.n_segment,
        v.source_quality_flags,
        (v.source_quality_recheck = 1) AS source_quality_recheck,
        v.legal_status,
        v.trust_tier,
        v.trust_score,
        v.legal_flags,
        v.computed_at,
        v.valuation_trace
    FROM public.valuation_results v
    """,
    """
    CREATE OR REPLACE VIEW public.radar_ask_v_price_history
    WITH (security_barrier=true, security_invoker=false) AS
    SELECT
        h.id::bigint AS price_history_id,
        h.listing_id::bigint AS listing_id,
        h.price_ty,
        h.price_per_m2,
        h.recorded_at
    FROM public.price_history h
    """,
    """
    CREATE OR REPLACE VIEW public.radar_ask_v_lot_history
    WITH (security_barrier=true, security_invoker=false) AS
    SELECT
        l.id::bigint AS listing_id,
        COALESCE(l.duplicate_of_id, l.id)::bigint AS canonical_lot_id,
        l.source,
        l.title,
        l.area AS ward,
        l.road_name,
        l.property_type,
        l.area_m2,
        l.frontage_m,
        l.depth_m,
        l.price_ty,
        l.price_per_m2,
        l.price_first_ty,
        l.first_seen_at,
        l.last_seen_at,
        l.posted_at,
        l.crawled_at,
        (l.is_active = 1) AS is_active
    FROM public.listings l
    """,
    """
    CREATE OR REPLACE VIEW public.radar_ask_v_signal_cards
    WITH (security_barrier=true, security_invoker=false) AS
    SELECT
        s.listing_id,
        s.title,
        s.source,
        s.source_status,
        s.ward,
        s.property_type,
        s.area_m2,
        s.frontage_m,
        s.depth_m,
        s.price_ty,
        s.listing_price_per_m2,
        s.actual_ppm2,
        s.fair_ppm2,
        s.mos_pct,
        s.signal_score,
        s.is_actionable,
        s.listing_is_signal,
        s.is_hot,
        s.possibly_duplicate,
        s.price_dropped,
        s.price_drop_pct,
        s.price_first_ty,
        s.suspicious_bait,
        s.activity_at,
        s.posted_at,
        s.first_seen_at,
        s.price_updated_at,
        s.road_name,
        s.road_type,
        s.road_width_m,
        s.road_tier,
        s.tho_cu_m2,
        s.tho_cu_ratio,
        s.has_so,
        s.trust_tier,
        s.trust_score,
        s.legal_status,
        s.legal_flags,
        s.source_quality_flags,
        s.source_quality_recheck,
        s.publisher_visible_public,
        s.refreshed_at
    FROM public.signal_card_read_model s
    """,
    """
    CREATE OR REPLACE VIEW public.radar_ask_v_official_land_prices
    WITH (security_barrier=true, security_invoker=false) AS
    SELECT
        p.row_key,
        p.area,
        p.appendix,
        p.stt,
        p.street,
        p.segment_from,
        p.segment_to,
        p.residential,
        p.commerce_service,
        p.production_business,
        p.page,
        p.search_text,
        p.source_title,
        p.source_url,
        p.data_as_of,
        p.unit
    FROM public.radar_ask_official_land_price_rows p
    """,
)

KNOWLEDGE_VIEW_SQL = """
CREATE OR REPLACE VIEW public.radar_ask_v_knowledge_chunks
WITH (security_barrier=true, security_invoker=false) AS
SELECT
    c.id AS chunk_id,
    c.document_id,
    c.chunk_index,
    c.chunk_text,
    c.normalized_text,
    c.token_count,
    c.content_sha256 AS chunk_content_sha256,
    c.search_vector,
    d.title AS document_title,
    d.version,
    d.published_at,
    d.effective_from,
    d.effective_to,
    TRUE AS is_current,
    d.imported_at,
    s.slug AS source_slug,
    s.title AS source_title,
    s.canonical_url AS source_url,
    s.trust_class,
    s.jurisdiction
FROM public.knowledge_chunks c
JOIN public.knowledge_documents d ON d.id=c.document_id
JOIN public.knowledge_sources s ON s.id=d.source_id
WHERE s.active
  AND (d.effective_from IS NULL OR d.effective_from<=CURRENT_DATE)
  AND (d.effective_to IS NULL OR d.effective_to>=CURRENT_DATE)
  AND NOT EXISTS (
      SELECT 1
      FROM public.knowledge_documents newer
      WHERE newer.source_id=d.source_id
        AND (newer.effective_from IS NULL OR newer.effective_from<=CURRENT_DATE)
        AND (newer.effective_to IS NULL OR newer.effective_to>=CURRENT_DATE)
        AND (
            COALESCE(newer.effective_from, DATE '-infinity')
                > COALESCE(d.effective_from, DATE '-infinity')
            OR (
                COALESCE(newer.effective_from, DATE '-infinity')
                    = COALESCE(d.effective_from, DATE '-infinity')
                AND newer.imported_at>d.imported_at
            )
            OR (
                COALESCE(newer.effective_from, DATE '-infinity')
                    = COALESCE(d.effective_from, DATE '-infinity')
                AND newer.imported_at=d.imported_at
                AND newer.id::text>d.id::text
            )
        )
  )
"""


@dataclass(frozen=True)
class RoleCheckReport:
    phase: str
    read_relations: frozenset[str]
    write_relations: frozenset[str]
    unexpected_relations: frozenset[str]
    violations: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.violations


def _validate_phase(phase: str) -> str:
    if phase not in {"foundation", "knowledge"}:
        raise ValueError("phase must be foundation or knowledge")
    return phase


def _ensure_role(
    conn: psycopg.Connection,
    *,
    role: str,
    login: bool,
    password: str | None = None,
) -> None:
    exists = conn.execute(
        "SELECT 1 FROM pg_roles WHERE rolname=%s",
        (role,),
    ).fetchone()
    role_ident = sql.Identifier(role)
    login_sql = sql.SQL("LOGIN") if login else sql.SQL("NOLOGIN")
    if exists is None:
        command = sql.SQL(
            "CREATE ROLE {} {} NOINHERIT NOSUPERUSER NOCREATEDB "
            "NOCREATEROLE NOREPLICATION"
        ).format(role_ident, login_sql)
        if login:
            command += sql.SQL(" PASSWORD {}").format(sql.Literal(password))
        conn.execute(command)
    else:
        command = sql.SQL(
            "ALTER ROLE {} WITH {} NOINHERIT NOSUPERUSER NOCREATEDB "
            "NOCREATEROLE NOREPLICATION"
        ).format(role_ident, login_sql)
        if login:
            command += sql.SQL(" PASSWORD {}").format(sql.Literal(password))
        conn.execute(command)


def _revoke_memberships(conn: psycopg.Connection, role: str) -> None:
    memberships = conn.execute(
        """
        SELECT parent.rolname, member.rolname
        FROM pg_auth_members membership
        JOIN pg_roles parent ON parent.oid=membership.roleid
        JOIN pg_roles member ON member.oid=membership.member
        WHERE member.rolname=%s OR parent.rolname=%s
        """,
        (role, role),
    ).fetchall()
    for parent, member in memberships:
        conn.execute(
            sql.SQL("REVOKE {} FROM {}").format(
                sql.Identifier(parent),
                sql.Identifier(member),
            )
        )


def _create_official_table(conn: psycopg.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS public.radar_ask_official_land_price_rows (
            row_key TEXT PRIMARY KEY,
            area TEXT NOT NULL,
            appendix TEXT NOT NULL DEFAULT '',
            stt TEXT NOT NULL DEFAULT '',
            street TEXT NOT NULL,
            segment_from TEXT NOT NULL DEFAULT '',
            segment_to TEXT NOT NULL DEFAULT '',
            residential NUMERIC(14, 2),
            commerce_service NUMERIC(14, 2),
            production_business NUMERIC(14, 2),
            page INTEGER,
            search_text TEXT NOT NULL DEFAULT '',
            source_title TEXT NOT NULL,
            source_url TEXT NOT NULL,
            data_as_of DATE NOT NULL,
            unit TEXT NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CHECK (residential IS NULL OR residential >= 0),
            CHECK (commerce_service IS NULL OR commerce_service >= 0),
            CHECK (production_business IS NULL OR production_business >= 0)
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_radar_ask_official_land_price_search
        ON public.radar_ask_official_land_price_rows(area, street)
        """
    )


def _validated_official_rows(payload: Mapping[str, Any]) -> list[tuple[Any, ...]]:
    raw_rows = payload.get("rows", [])
    if not isinstance(raw_rows, list) or len(raw_rows) > 100_000:
        raise ValueError("official land-price rows must be a bounded list")
    if not raw_rows:
        return []
    source_title = str(payload.get("source") or "").strip()
    source_url = str(payload.get("source_url") or "").strip()
    source_parsed = urlparse(source_url)
    if (
        not source_title
        or source_parsed.scheme != "https"
        or (source_parsed.hostname or "").lower() not in OFFICIAL_SOURCE_HOSTS
        or source_parsed.username
        or source_parsed.password
    ):
        raise ValueError("official land-price source is not on the curated HTTPS allowlist")
    try:
        data_as_of = date.fromisoformat(str(payload.get("data_as_of") or ""))
    except ValueError as exc:
        raise ValueError("official land-price data_as_of must be an ISO date") from exc
    unit = str(payload.get("unit") or "").strip()
    if not unit:
        raise ValueError("official land-price unit is required")

    normalized: list[tuple[Any, ...]] = []
    for row in raw_rows:
        if not isinstance(row, Mapping):
            raise ValueError("official land-price row must be an object")
        street = str(row.get("street") or "").strip()
        area = str(row.get("area") or "").strip()
        if not street or not area:
            raise ValueError("official land-price row requires area and street")
        prices = []
        for field in ("residential", "commerce_service", "production_business"):
            value = row.get(field)
            if value is not None and (not isinstance(value, (int, float)) or value < 0):
                raise ValueError(f"official land-price {field} must be non-negative")
            prices.append(value)
        normalized.append(
            (
                land_price_row_key(row),
                area,
                str(row.get("appendix") or ""),
                str(row.get("stt") or ""),
                street,
                str(row.get("from") or ""),
                str(row.get("to") or ""),
                *prices,
                row.get("page"),
                str(row.get("search") or ""),
                source_title,
                source_url,
                data_as_of,
                unit,
            )
        )
    return normalized


def _sync_official_rows(
    conn: psycopg.Connection,
    payload: Mapping[str, Any] | None,
) -> None:
    if payload is None:
        return
    rows = _validated_official_rows(payload)
    if not rows:
        return
    # The checked-in file is one complete official snapshot. Row identity also
    # includes the published prices, so replace transactionally to prevent a
    # corrected price from leaving its previous row queryable.
    conn.execute("DELETE FROM public.radar_ask_official_land_price_rows")
    with conn.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO public.radar_ask_official_land_price_rows (
                row_key, area, appendix, stt, street, segment_from, segment_to,
                residential, commerce_service, production_business, page,
                search_text, source_title, source_url, data_as_of, unit
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (row_key) DO UPDATE SET
                area=EXCLUDED.area,
                appendix=EXCLUDED.appendix,
                stt=EXCLUDED.stt,
                street=EXCLUDED.street,
                segment_from=EXCLUDED.segment_from,
                segment_to=EXCLUDED.segment_to,
                residential=EXCLUDED.residential,
                commerce_service=EXCLUDED.commerce_service,
                production_business=EXCLUDED.production_business,
                page=EXCLUDED.page,
                search_text=EXCLUDED.search_text,
                source_title=EXCLUDED.source_title,
                source_url=EXCLUDED.source_url,
                data_as_of=EXCLUDED.data_as_of,
                unit=EXCLUDED.unit,
                updated_at=NOW()
            """,
            rows,
        )


def _grant_columns(
    conn: psycopg.Connection,
    grants: Mapping[str, Iterable[str]],
) -> None:
    for table, columns in grants.items():
        conn.execute(
            sql.SQL("REVOKE ALL PRIVILEGES ON TABLE public.{} FROM {}").format(
                sql.Identifier(table),
                sql.Identifier(VIEW_OWNER_ROLE),
            )
        )
        conn.execute(
            sql.SQL("GRANT SELECT ({}) ON TABLE public.{} TO {}").format(
                sql.SQL(", ").join(sql.Identifier(column) for column in columns),
                sql.Identifier(table),
                sql.Identifier(VIEW_OWNER_ROLE),
            )
        )


def _create_views_as_owner(
    conn: psycopg.Connection,
    *,
    phase: str,
) -> None:
    conn.execute(
        sql.SQL("GRANT CREATE ON SCHEMA public TO {}").format(
            sql.Identifier(VIEW_OWNER_ROLE)
        )
    )
    conn.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(VIEW_OWNER_ROLE)))
    try:
        for statement in FOUNDATION_VIEW_SQL:
            conn.execute(statement)
        if phase == "knowledge":
            conn.execute(KNOWLEDGE_VIEW_SQL)
    finally:
        conn.execute("RESET ROLE")
        conn.execute(
            sql.SQL("REVOKE CREATE ON SCHEMA public FROM {}").format(
                sql.Identifier(VIEW_OWNER_ROLE)
            )
        )


def _configure_optional_vector_execute(conn: psycopg.Connection, *, phase: str) -> None:
    """Keep optional SECURITY DEFINER functions aligned with the active phase."""
    for function_name, argument_types, signature in OPTIONAL_VECTOR_FUNCTIONS:
        exists = conn.execute(
            """
            SELECT EXISTS (
                SELECT 1
                FROM pg_proc procedure
                JOIN pg_namespace namespace ON namespace.oid=procedure.pronamespace
                WHERE namespace.nspname='public'
                  AND procedure.proname=%s
                  AND oidvectortypes(procedure.proargtypes)=%s
            )
            """,
            (function_name, argument_types),
        ).fetchone()[0]
        if not exists:
            continue
        conn.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        conn.execute(
            sql.SQL(f"REVOKE ALL ON FUNCTION {signature} FROM {{}}").format(
                sql.Identifier(READ_ROLE)
            )
        )
        if phase == "knowledge":
            conn.execute(
                sql.SQL(f"GRANT EXECUTE ON FUNCTION {signature} TO {{}}").format(
                    sql.Identifier(READ_ROLE)
                )
            )


def apply_configuration(
    conn: psycopg.Connection,
    *,
    password: str,
    phase: str = "foundation",
    official_payload: Mapping[str, Any] | None = None,
    statement_timeout_ms: int = 2_000,
) -> None:
    """Apply roles, safe relations, and exact grants in the caller transaction."""
    phase = _validate_phase(phase)
    if not password or len(password) < 24:
        raise ValueError("RADAR_ASK_DB_PASSWORD must contain at least 24 characters")
    if not 100 <= int(statement_timeout_ms) <= 10_000:
        raise ValueError("statement timeout must be between 100 and 10000 milliseconds")

    _ensure_role(conn, role=VIEW_OWNER_ROLE, login=False)
    _ensure_role(conn, role=READ_ROLE, login=True, password=password)
    _revoke_memberships(conn, VIEW_OWNER_ROLE)
    _revoke_memberships(conn, READ_ROLE)
    conn.execute(
        sql.SQL("ALTER ROLE {} SET default_transaction_read_only TO on").format(
            sql.Identifier(READ_ROLE)
        )
    )
    conn.execute(
        sql.SQL("ALTER ROLE {} SET statement_timeout TO {}").format(
            sql.Identifier(READ_ROLE),
            sql.Literal(f"{int(statement_timeout_ms)}ms"),
        )
    )

    database_name = conn.execute("SELECT current_database()").fetchone()[0]
    conn.execute(
        sql.SQL("REVOKE ALL PRIVILEGES ON DATABASE {} FROM {}").format(
            sql.Identifier(database_name),
            sql.Identifier(READ_ROLE),
        )
    )
    conn.execute(
        sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
            sql.Identifier(database_name),
            sql.Identifier(READ_ROLE),
        )
    )
    for role in (READ_ROLE, VIEW_OWNER_ROLE):
        conn.execute(
            sql.SQL("REVOKE ALL ON SCHEMA public FROM {}").format(sql.Identifier(role))
        )
        conn.execute(
            sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(role))
        )

    _create_official_table(conn)
    _sync_official_rows(conn, official_payload)

    conn.execute(
        sql.SQL("REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM {}").format(
            sql.Identifier(READ_ROLE)
        )
    )
    conn.execute(
        sql.SQL("REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM {}").format(
            sql.Identifier(VIEW_OWNER_ROLE)
        )
    )
    all_grants = dict(BASE_COLUMN_GRANTS)
    if phase == "knowledge":
        all_grants.update(KNOWLEDGE_COLUMN_GRANTS)
    _grant_columns(conn, all_grants)
    _create_views_as_owner(conn, phase=phase)

    safe_views = KNOWLEDGE_SAFE_VIEWS if phase == "knowledge" else FOUNDATION_SAFE_VIEWS
    conn.execute(
        sql.SQL("REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM {}").format(
            sql.Identifier(READ_ROLE)
        )
    )
    for view in safe_views:
        conn.execute(
            sql.SQL("GRANT SELECT ON TABLE public.{} TO {}").format(
                sql.Identifier(view),
                sql.Identifier(READ_ROLE),
            )
        )
    _configure_optional_vector_execute(conn, phase=phase)


def _effective_relation_privileges(
    conn: psycopg.Connection,
    *,
    role: str,
) -> tuple[frozenset[str], frozenset[str]]:
    rows = conn.execute(
        """
        SELECT c.relname, privilege.name
        FROM pg_class c
        JOIN pg_namespace n ON n.oid=c.relnamespace
        CROSS JOIN (
            VALUES ('SELECT'), ('INSERT'), ('UPDATE'), ('DELETE'),
                   ('TRUNCATE'), ('REFERENCES'), ('TRIGGER')
        ) AS privilege(name)
        WHERE n.nspname='public'
          AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
          AND has_table_privilege(%s, c.oid, privilege.name)
        """,
        (role,),
    ).fetchall()
    reads = frozenset(relation for relation, privilege in rows if privilege == "SELECT")
    writes = frozenset(relation for relation, privilege in rows if privilege != "SELECT")
    return reads, writes


def _effective_column_privileges(
    conn: psycopg.Connection,
    *,
    role: str,
    excluded_owner_role: str,
) -> frozenset[tuple[str, str, str]]:
    """Return effective column grants without information_schema visibility gaps.

    ``information_schema.column_privileges`` only exposes grants visible to the
    current connection role. Production applies the manifest as ``postgres``
    but audits it through ``radar_app``, so use PostgreSQL's effective privilege
    function against catalog OIDs instead.
    """
    rows = conn.execute(
        """
        SELECT relation.relname, attribute.attname, privilege.name
        FROM pg_class relation
        JOIN pg_namespace namespace ON namespace.oid=relation.relnamespace
        JOIN pg_roles owner_role ON owner_role.rolname=%s
        JOIN pg_attribute attribute
          ON attribute.attrelid=relation.oid
         AND attribute.attnum>0
         AND NOT attribute.attisdropped
        CROSS JOIN (
            VALUES ('SELECT'), ('INSERT'), ('UPDATE'), ('REFERENCES')
        ) AS privilege(name)
        WHERE namespace.nspname='public'
          AND relation.relkind IN ('r', 'p', 'v', 'm', 'f')
          AND relation.relowner <> owner_role.oid
          AND has_column_privilege(
              %s,
              relation.oid,
              attribute.attnum,
              privilege.name
          )
        """,
        (excluded_owner_role, role),
    ).fetchall()
    return frozenset((relation, column, privilege) for relation, column, privilege in rows)


def check_configuration(
    conn: psycopg.Connection,
    *,
    phase: str = "foundation",
) -> RoleCheckReport:
    """Return an exact effective-privilege audit for both isolated roles."""
    phase = _validate_phase(phase)
    expected_views = frozenset(
        KNOWLEDGE_SAFE_VIEWS if phase == "knowledge" else FOUNDATION_SAFE_VIEWS
    )
    violations: list[str] = []

    attributes = {
        row[0]: row[1:]
        for row in conn.execute(
            """
            SELECT rolname, rolcanlogin, rolsuper, rolcreatedb,
                   rolcreaterole, rolreplication, rolinherit
            FROM pg_roles
            WHERE rolname IN (%s, %s)
            """,
            (READ_ROLE, VIEW_OWNER_ROLE),
        ).fetchall()
    }
    if set(attributes) != {READ_ROLE, VIEW_OWNER_ROLE}:
        violations.append("required roles are missing")
    else:
        if attributes[READ_ROLE] != (True, False, False, False, False, False):
            violations.append("read role attributes are not hardened")
        if attributes[VIEW_OWNER_ROLE] != (False, False, False, False, False, False):
            violations.append("view-owner role attributes are not hardened")

    memberships = conn.execute(
        """
        SELECT member.rolname, parent.rolname
        FROM pg_auth_members membership
        JOIN pg_roles member ON member.oid=membership.member
        JOIN pg_roles parent ON parent.oid=membership.roleid
        WHERE member.rolname IN (%s, %s)
           OR parent.rolname IN (%s, %s)
        """,
        (READ_ROLE, VIEW_OWNER_ROLE, READ_ROLE, VIEW_OWNER_ROLE),
    ).fetchall()
    if memberships:
        violations.append("isolated roles have unexpected memberships")

    read_relations, write_relations = _effective_relation_privileges(
        conn,
        role=READ_ROLE,
    )
    unexpected = (read_relations - expected_views) | write_relations
    missing = expected_views - read_relations
    if missing:
        violations.append("safe-view SELECT grants are incomplete")
    if unexpected:
        violations.append("read role has unexpected relation privileges")

    view_rows = conn.execute(
        """
        SELECT c.relname, owner.rolname,
               COALESCE((c.reloptions @> ARRAY['security_invoker=true']), false)
        FROM pg_class c
        JOIN pg_namespace n ON n.oid=c.relnamespace
        JOIN pg_roles owner ON owner.oid=c.relowner
        WHERE n.nspname='public' AND c.relname=ANY(%s::text[])
        """,
        (sorted(expected_views),),
    ).fetchall()
    if {row[0] for row in view_rows} != expected_views:
        violations.append("safe-view manifest is missing relations")
    if any(owner != VIEW_OWNER_ROLE or security_invoker for _view, owner, security_invoker in view_rows):
        violations.append("safe views are not owner-evaluated by the dedicated role")

    schema_usage, schema_create = conn.execute(
        """
        SELECT has_schema_privilege(%s, 'public', 'USAGE'),
               has_schema_privilege(%s, 'public', 'CREATE')
        """,
        (READ_ROLE, READ_ROLE),
    ).fetchone()
    if not schema_usage or schema_create:
        violations.append("read role schema privileges are unsafe")

    owner_base_privileges = conn.execute(
        """
        SELECT c.relname, privilege.name
        FROM pg_class c
        JOIN pg_namespace n ON n.oid=c.relnamespace
        JOIN pg_roles owner_role ON owner_role.rolname=%s
        CROSS JOIN (
            VALUES ('SELECT'), ('INSERT'), ('UPDATE'), ('DELETE'),
                   ('TRUNCATE'), ('REFERENCES'), ('TRIGGER')
        ) AS privilege(name)
        WHERE n.nspname='public'
          AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
          AND c.relowner <> owner_role.oid
          AND has_table_privilege(%s, c.oid, privilege.name)
        """,
        (VIEW_OWNER_ROLE, VIEW_OWNER_ROLE),
    ).fetchall()
    if owner_base_privileges:
        violations.append("view owner has unexpected base-table privileges")

    expected_owner_grants = dict(BASE_COLUMN_GRANTS)
    if phase == "knowledge":
        expected_owner_grants.update(KNOWLEDGE_COLUMN_GRANTS)
    expected_owner_columns = {
        (table, column, "SELECT")
        for table, columns in expected_owner_grants.items()
        for column in columns
    }
    actual_owner_columns = _effective_column_privileges(
        conn,
        role=VIEW_OWNER_ROLE,
        excluded_owner_role=VIEW_OWNER_ROLE,
    )
    if actual_owner_columns != expected_owner_columns:
        violations.append("view owner column grants differ from the exact manifest")

    sensitive_columns = (
        ("listings", "url"),
        ("listings", "description"),
        ("listings", "contact_phone"),
        ("listings", "seller_name"),
        ("raw_listings", "raw_json"),
        ("users", "password_hash"),
    )
    for table, column in sensitive_columns:
        can_read = conn.execute(
            "SELECT has_column_privilege(%s, %s, %s, 'SELECT')",
            (VIEW_OWNER_ROLE, f"public.{table}", column),
        ).fetchone()[0]
        if can_read:
            violations.append(f"view owner can read sensitive column {table}.{column}")

    for function_name, argument_types, _signature in OPTIONAL_VECTOR_FUNCTIONS:
        rows = conn.execute(
            """
            SELECT procedure.oid,
                   has_function_privilege(%s, procedure.oid, 'EXECUTE'),
                   EXISTS (
                       SELECT 1
                       FROM aclexplode(
                           COALESCE(
                               procedure.proacl,
                               acldefault('f', procedure.proowner)
                           )
                       ) privilege
                       WHERE privilege.grantee=0
                         AND privilege.privilege_type='EXECUTE'
                   )
            FROM pg_proc procedure
            JOIN pg_namespace namespace ON namespace.oid=procedure.pronamespace
            WHERE namespace.nspname='public'
              AND procedure.proname=%s
              AND oidvectortypes(procedure.proargtypes)=%s
            """,
            (READ_ROLE, function_name, argument_types),
        ).fetchall()
        for _oid, read_can_execute, public_can_execute in rows:
            if public_can_execute:
                violations.append(
                    f"optional vector function {function_name} is executable by PUBLIC"
                )
            if bool(read_can_execute) != (phase == "knowledge"):
                violations.append(
                    f"optional vector function {function_name} execute grant differs from phase"
                )

    return RoleCheckReport(
        phase=phase,
        read_relations=read_relations,
        write_relations=write_relations,
        unexpected_relations=frozenset(unexpected),
        violations=tuple(violations),
    )


def load_official_payload(path: Path = OFFICIAL_DATA_PATH) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("official land-price file must contain an object")
    return payload


def _owner_database_url() -> str:
    value = os.getenv("DATABASE_URL", "").strip()
    if not value:
        raise ValueError("DATABASE_URL owner connection is required")
    parsed = urlparse(value)
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise ValueError("DATABASE_URL must be PostgreSQL")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "apply"))
    parser.add_argument("--phase", choices=("foundation", "knowledge"), default="foundation")
    args = parser.parse_args(argv)

    with psycopg.connect(_owner_database_url()) as conn:
        if args.action == "apply":
            password = os.getenv("RADAR_ASK_DB_PASSWORD", "")
            apply_configuration(
                conn,
                password=password,
                phase=args.phase,
                official_payload=load_official_payload(),
                statement_timeout_ms=int(
                    os.getenv("RADAR_ASK_STATEMENT_TIMEOUT_MS", "2000")
                ),
            )
        report = check_configuration(conn, phase=args.phase)
        if not report.ok:
            conn.rollback()
            print("Radar Ask database isolation check failed")
            for violation in report.violations:
                print(f"- {violation}")
            return 1
        print(
            "Radar Ask database isolation check passed: "
            + ", ".join(sorted(report.read_relations))
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
