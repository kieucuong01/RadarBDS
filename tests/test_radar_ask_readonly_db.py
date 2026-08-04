from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from secrets import token_urlsafe
import subprocess
import sys
from urllib.parse import quote, urlsplit, urlunsplit

import psycopg
import pytest

from db import connection
from db.radar_ask_connection import (
    RadarAskDatabaseConfigurationError,
    close_radar_ask_pool,
    get_radar_ask_read_conn,
    get_radar_ask_read_pool,
)
from db.schema import init_schema
from scripts.configure_radar_ask_db_role import (
    FOUNDATION_SAFE_VIEWS,
    KNOWLEDGE_SAFE_VIEWS,
    apply_configuration,
    check_configuration,
)
from services.radar_ask.config import RadarAskSettings


def _role_url(admin_url: str, *, role: str, password: str) -> str:
    parsed = urlsplit(admin_url)
    host = parsed.hostname or "127.0.0.1"
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    port = f":{parsed.port}" if parsed.port else ""
    netloc = f"{quote(role, safe='')}:{quote(password, safe='')}@{host}{port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


@pytest.fixture(scope="module")
def readonly_environment():
    test_url = connection._database_url()
    password = token_urlsafe(32)
    connection.close_all()
    init_schema()
    payload = {
        "source": "Nghị quyết kiểm thử",
        "source_url": "https://congbao.hochiminhcity.gov.vn/test/radar-ask",
        "data_as_of": "2026-01-01",
        "unit": "1.000 đồng/m²",
        "rows": [
            {
                "area": "PHƯỜNG SÀI GÒN",
                "appendix": "Phụ lục II",
                "stt": "1",
                "street": "ĐỒNG KHỞI",
                "from": "TRỌN ĐƯỜNG",
                "to": "",
                "residential": 687_200,
                "commerce_service": 481_000,
                "production_business": 412_300,
                "page": 20,
                "search": "phuong sai gon dong khoi tron duong",
            }
        ],
    }
    with psycopg.connect(test_url) as admin_conn:
        apply_configuration(
            admin_conn,
            password=password,
            phase="foundation",
            official_payload=payload,
        )

    settings = replace(
        RadarAskSettings.from_env(),
        enabled=True,
        database_url=_role_url(test_url, role="radar_ask_ro", password=password),
        db_pool_max=1,
        statement_timeout_ms=100,
    )
    yield test_url, settings
    close_radar_ask_pool()
    connection.close_all()


@pytest.fixture(autouse=True)
def isolated_readonly_pool():
    close_radar_ask_pool()
    yield
    close_radar_ask_pool()


def test_foundation_role_manifest_is_exact_and_has_no_write_grants(readonly_environment):
    test_url, _settings = readonly_environment
    with psycopg.connect(test_url) as admin_conn:
        report = check_configuration(admin_conn, phase="foundation")

    assert report.ok, report.violations
    assert report.read_relations == frozenset(FOUNDATION_SAFE_VIEWS)
    assert report.write_relations == frozenset()
    assert report.unexpected_relations == frozenset()


def test_check_rejects_unexpected_view_owner_base_table_grant(readonly_environment):
    test_url, _settings = readonly_environment
    with psycopg.connect(test_url) as admin_conn:
        with admin_conn.transaction(force_rollback=True):
            admin_conn.execute(
                "GRANT SELECT (id) ON public.digital_product_orders TO radar_ask_view_owner"
            )

            report = check_configuration(admin_conn, phase="foundation")

            assert not report.ok
            assert any("view owner" in violation for violation in report.violations)

            apply_configuration(
                admin_conn,
                password=token_urlsafe(32),
                phase="foundation",
                official_payload={"rows": []},
            )
            repaired = check_configuration(admin_conn, phase="foundation")
            assert repaired.ok, repaired.violations


def test_check_and_apply_remove_roles_that_can_assume_view_owner(readonly_environment):
    test_url, _settings = readonly_environment
    with psycopg.connect(test_url) as admin_conn:
        with admin_conn.transaction(force_rollback=True):
            admin_conn.execute("CREATE ROLE radar_ask_membership_probe NOLOGIN")
            admin_conn.execute(
                "GRANT radar_ask_view_owner TO radar_ask_membership_probe"
            )

            report = check_configuration(admin_conn, phase="foundation")
            assert not report.ok
            assert any("membership" in violation for violation in report.violations)

            apply_configuration(
                admin_conn,
                password=token_urlsafe(32),
                phase="foundation",
                official_payload={"rows": []},
            )
            repaired = check_configuration(admin_conn, phase="foundation")
            assert repaired.ok, repaired.violations


def test_read_role_can_select_only_safe_views_not_sensitive_tables(readonly_environment):
    _test_url, settings = readonly_environment
    with get_radar_ask_read_conn(settings=settings) as conn:
        row = conn.execute(
            "SELECT listing_id FROM public.radar_ask_v_listings LIMIT 1"
        ).fetchone()
        assert row is None or isinstance(row[0], int)
        official = conn.execute(
            "SELECT street FROM public.radar_ask_v_official_land_prices LIMIT 1"
        ).fetchone()
        assert official == ("ĐỒNG KHỞI",)

    for forbidden_sql in (
        "SELECT identifier FROM public.users LIMIT 1",
        "SELECT raw_json FROM public.raw_listings LIMIT 1",
        "SELECT * FROM public.radar_ask_sessions LIMIT 1",
        "SELECT * FROM public.digital_product_orders LIMIT 1",
        "SELECT * FROM public.listings LIMIT 1",
    ):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with get_radar_ask_read_conn(settings=settings) as conn:
                conn.execute(forbidden_sql).fetchall()


def test_safe_listing_and_signal_views_exclude_sensitive_columns(readonly_environment):
    test_url, _settings = readonly_environment
    with psycopg.connect(test_url) as admin_conn:
        rows = admin_conn.execute(
            """
            SELECT table_name, column_name
            FROM information_schema.columns
            WHERE table_schema='public'
              AND table_name IN ('radar_ask_v_listings', 'radar_ask_v_signal_cards')
            """
        ).fetchall()
    columns = {(table_name, column_name) for table_name, column_name in rows}
    forbidden = {
        "url",
        "description",
        "contact_phone",
        "seller_name",
        "raw_id",
        "raw_json",
    }

    assert not {column for _table, column in columns}.intersection(forbidden)
    assert ("radar_ask_v_listings", "listing_id") in columns
    assert ("radar_ask_v_signal_cards", "listing_id") in columns


def test_read_context_starts_read_only_and_enforces_statement_timeout(readonly_environment):
    _test_url, settings = readonly_environment
    with get_radar_ask_read_conn(settings=settings) as conn:
        assert conn.execute("SHOW transaction_read_only").fetchone() == ("on",)
        assert conn.execute("SHOW statement_timeout").fetchone() == ("100ms",)

    with pytest.raises(psycopg.errors.QueryCanceled):
        with get_radar_ask_read_conn(settings=settings) as conn:
            conn.execute("SELECT pg_sleep(0.25)").fetchone()


def test_read_role_cannot_write_or_create_objects(readonly_environment):
    _test_url, settings = readonly_environment
    for forbidden_sql in (
        "UPDATE public.radar_ask_v_listings SET title='x'",
        "DELETE FROM public.radar_ask_official_land_price_rows",
        "CREATE TABLE public.radar_ask_escape(id integer)",
    ):
        with pytest.raises(
            (
                psycopg.errors.ReadOnlySqlTransaction,
                psycopg.errors.InsufficientPrivilege,
                psycopg.errors.ObjectNotInPrerequisiteState,
            )
        ):
            with get_radar_ask_read_conn(settings=settings) as conn:
                conn.execute(forbidden_sql)


def test_pool_is_lazy_separate_and_bounded_to_configured_max(readonly_environment):
    _test_url, settings = readonly_environment
    pool = get_radar_ask_read_pool(settings=settings)

    assert pool.min_size == 0
    assert pool.max_size == 1
    assert pool.get_stats().get("pool_size", 0) == 0
    with get_radar_ask_read_conn(settings=settings):
        pass
    with get_radar_ask_read_conn(settings=settings):
        pass
    stats = pool.get_stats()
    assert stats["pool_size"] <= 1
    assert stats["pool_available"] <= 1


def test_pool_rejects_injected_admin_database_settings(readonly_environment):
    test_url, settings = readonly_environment
    unsafe = replace(settings, database_url=test_url)

    with pytest.raises(RadarAskDatabaseConfigurationError, match="radar_ask_ro"):
        get_radar_ask_read_pool(settings=unsafe)


def test_enabled_feature_requires_a_valid_dedicated_postgres_url(monkeypatch):
    monkeypatch.setenv("RADAR_ASK_ENABLED", "1")
    monkeypatch.setenv("RADAR_ASK_DATABASE_URL", "")
    with pytest.raises(ValueError, match="RADAR_ASK_DATABASE_URL is required"):
        RadarAskSettings.from_env()

    monkeypatch.setenv("RADAR_ASK_DATABASE_URL", "https://database.example.test/radar")
    with pytest.raises(ValueError, match="PostgreSQL URL"):
        RadarAskSettings.from_env()


def test_knowledge_phase_adds_only_curated_seventh_view(readonly_environment):
    test_url, _settings = readonly_environment
    password = token_urlsafe(32)
    with psycopg.connect(test_url) as admin_conn:
        with admin_conn.transaction(force_rollback=True):
            admin_conn.execute(
                """
                CREATE TABLE public.knowledge_sources (
                    id UUID PRIMARY KEY,
                    slug TEXT NOT NULL,
                    title TEXT NOT NULL,
                    canonical_url TEXT NOT NULL,
                    trust_class TEXT NOT NULL,
                    jurisdiction TEXT NOT NULL
                )
                """
            )
            admin_conn.execute(
                """
                CREATE TABLE public.knowledge_documents (
                    id UUID PRIMARY KEY,
                    source_id UUID NOT NULL REFERENCES public.knowledge_sources(id),
                    title TEXT NOT NULL,
                    version TEXT NOT NULL,
                    published_at DATE,
                    effective_from DATE,
                    effective_to DATE
                )
                """
            )
            admin_conn.execute(
                """
                CREATE TABLE public.knowledge_chunks (
                    id UUID PRIMARY KEY,
                    document_id UUID NOT NULL REFERENCES public.knowledge_documents(id),
                    chunk_index INTEGER NOT NULL,
                    chunk_text TEXT NOT NULL
                )
                """
            )
            apply_configuration(
                admin_conn,
                password=password,
                phase="knowledge",
                official_payload={"rows": []},
            )
            report = check_configuration(admin_conn, phase="knowledge")

            assert report.ok, report.violations
            assert report.read_relations == frozenset(KNOWLEDGE_SAFE_VIEWS)
            assert report.write_relations == frozenset()


def test_foundation_reapply_revokes_knowledge_base_column_grants(readonly_environment):
    test_url, _settings = readonly_environment
    password = token_urlsafe(32)
    with psycopg.connect(test_url) as admin_conn:
        with admin_conn.transaction(force_rollback=True):
            admin_conn.execute(
                """
                CREATE TABLE public.knowledge_sources (
                    id UUID PRIMARY KEY, slug TEXT, title TEXT,
                    canonical_url TEXT, trust_class TEXT, jurisdiction TEXT
                )
                """
            )
            admin_conn.execute(
                """
                CREATE TABLE public.knowledge_documents (
                    id UUID PRIMARY KEY, source_id UUID, title TEXT, version TEXT,
                    published_at DATE, effective_from DATE, effective_to DATE
                )
                """
            )
            admin_conn.execute(
                """
                CREATE TABLE public.knowledge_chunks (
                    id UUID PRIMARY KEY, document_id UUID,
                    chunk_index INTEGER, chunk_text TEXT
                )
                """
            )
            apply_configuration(
                admin_conn,
                password=password,
                phase="knowledge",
                official_payload={"rows": []},
            )
            assert admin_conn.execute(
                """
                SELECT has_column_privilege(
                    'radar_ask_view_owner',
                    'public.knowledge_chunks',
                    'chunk_text',
                    'SELECT'
                )
                """
            ).fetchone()[0]

            apply_configuration(
                admin_conn,
                password=password,
                phase="foundation",
                official_payload={"rows": []},
            )
            can_still_read = admin_conn.execute(
                """
                SELECT has_column_privilege(
                    'radar_ask_view_owner',
                    'public.knowledge_chunks',
                    'chunk_text',
                    'SELECT'
                )
                """
            ).fetchone()[0]
            report = check_configuration(admin_conn, phase="foundation")

            assert can_still_read is False
            assert report.ok, report.violations


def test_official_price_reapply_replaces_stale_snapshot_rows(readonly_environment):
    test_url, _settings = readonly_environment
    password = token_urlsafe(32)
    payload = {
        "source": "Nghị quyết đồng bộ kiểm thử",
        "source_url": "https://congbao.hochiminhcity.gov.vn/test/radar-ask-sync",
        "data_as_of": "2026-01-01",
        "unit": "1.000 đồng/m²",
        "rows": [
            {
                "area": "PHƯỜNG SÀI GÒN",
                "street": "ĐỒNG KHỞI",
                "from": "TRỌN ĐƯỜNG",
                "to": "",
                "residential": 100,
                "commerce_service": 70,
                "production_business": 60,
            }
        ],
    }
    corrected = {
        **payload,
        "rows": [{**payload["rows"][0], "residential": 110}],
    }
    with psycopg.connect(test_url) as admin_conn:
        with admin_conn.transaction(force_rollback=True):
            apply_configuration(
                admin_conn,
                password=password,
                phase="foundation",
                official_payload=payload,
            )
            apply_configuration(
                admin_conn,
                password=password,
                phase="foundation",
                official_payload=corrected,
            )
            rows = admin_conn.execute(
                """
                SELECT residential
                FROM public.radar_ask_official_land_price_rows
                WHERE source_url=%s
                """,
                (payload["source_url"],),
            ).fetchall()

            assert rows == [(110,)]


def test_foundation_does_not_create_fake_knowledge_view(readonly_environment):
    test_url, _settings = readonly_environment
    with psycopg.connect(test_url) as admin_conn:
        relation = admin_conn.execute(
            "SELECT to_regclass('public.radar_ask_v_knowledge_chunks')"
        ).fetchone()[0]
        report = check_configuration(admin_conn, phase="knowledge")

    assert relation is None
    assert not report.ok


def test_role_script_contains_no_embedded_password_literal():
    source = Path("scripts/configure_radar_ask_db_role.py").read_text(encoding="utf-8")

    assert "RADAR_ASK_DB_PASSWORD" in source
    assert "PASSWORD '" not in source


def test_role_script_runs_directly_from_repo_root():
    result = subprocess.run(
        [
            sys.executable,
            "-X",
            "utf8",
            "scripts/configure_radar_ask_db_role.py",
            "--help",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "foundation" in result.stdout
