import os
import re
from pathlib import Path

import pytest

from config.settings import get_digital_product_commerce_settings
from db.connection import _add_returning_id
from db.schema import SCHEMA_SQL


COMMERCE_ENV_KEYS = (
    "PAYOS_CLIENT_ID",
    "PAYOS_API_KEY",
    "PAYOS_CHECKSUM_KEY",
    "DIGITAL_PRODUCT_COOKIE_SECRET",
    "DIGITAL_PRODUCT_STORAGE_DIR",
    "DIGITAL_PRODUCT_SALES_ENABLED",
)


def _clear_commerce_env(monkeypatch):
    for key in COMMERCE_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def _set_ready_commerce_env(monkeypatch, storage_dir):
    monkeypatch.setenv("DIGITAL_PRODUCT_SALES_ENABLED", "1")
    monkeypatch.setenv("DIGITAL_PRODUCT_STORAGE_DIR", str(storage_dir))
    monkeypatch.setenv("PAYOS_CLIENT_ID", " client ")
    monkeypatch.setenv("PAYOS_API_KEY", " api ")
    monkeypatch.setenv("PAYOS_CHECKSUM_KEY", " checksum ")
    monkeypatch.setenv("DIGITAL_PRODUCT_COOKIE_SECRET", f" {'x' * 64} ")


def test_commerce_settings_default_to_sales_disabled(monkeypatch):
    _clear_commerce_env(monkeypatch)

    settings = get_digital_product_commerce_settings()

    assert settings.sales_enabled is False
    assert settings.ready_for_checkout is False


def test_enabled_sales_require_all_secrets_and_absolute_storage(monkeypatch, tmp_path):
    _clear_commerce_env(monkeypatch)
    _set_ready_commerce_env(monkeypatch, tmp_path)

    settings = get_digital_product_commerce_settings()

    assert settings.ready_for_checkout is True
    assert settings.payos_client_id == "client"
    assert settings.payos_api_key == "api"
    assert settings.payos_checksum_key == "checksum"
    assert settings.cookie_secret == "x" * 64


def test_enabled_sales_fail_closed_for_relative_storage(monkeypatch):
    _clear_commerce_env(monkeypatch)
    _set_ready_commerce_env(monkeypatch, "relative/products")

    assert get_digital_product_commerce_settings().ready_for_checkout is False


def test_enabled_sales_fail_closed_for_short_cookie_secret(monkeypatch, tmp_path):
    _clear_commerce_env(monkeypatch)
    _set_ready_commerce_env(monkeypatch, tmp_path)
    monkeypatch.setenv("DIGITAL_PRODUCT_COOKIE_SECRET", "x" * 63)

    assert get_digital_product_commerce_settings().ready_for_checkout is False


@pytest.mark.parametrize(
    "storage_dir",
    (
        Path(__file__).resolve().parents[1],
        Path(__file__).resolve().parents[1] / "static",
        Path(__file__).resolve().parents[1]
        / "static"
        / ".."
        / "protected-products",
    ),
)
def test_enabled_sales_fail_closed_for_storage_inside_project(
    monkeypatch, storage_dir
):
    _clear_commerce_env(monkeypatch)
    _set_ready_commerce_env(monkeypatch, storage_dir)

    assert get_digital_product_commerce_settings().ready_for_checkout is False


def test_storage_path_is_resolved_before_project_boundary_check(monkeypatch):
    _clear_commerce_env(monkeypatch)
    project_root = Path(__file__).resolve().parents[1]
    traversing_path = project_root.parent / project_root.name / "static" / ".."
    _set_ready_commerce_env(monkeypatch, traversing_path)

    settings = get_digital_product_commerce_settings()

    assert settings.storage_dir == project_root
    assert settings.ready_for_checkout is False


def test_enabled_sales_fail_closed_for_storage_in_common_git_repo(monkeypatch):
    _clear_commerce_env(monkeypatch)
    project_root = Path(__file__).resolve().parents[1]
    repository_root = next(
        (
            candidate
            for candidate in (project_root, *project_root.parents)
            if (candidate / ".git").is_dir()
        ),
        None,
    )
    if repository_root is None or repository_root == project_root:
        pytest.skip("checkout is not a linked worktree")
    _set_ready_commerce_env(monkeypatch, repository_root / "protected-products")

    assert get_digital_product_commerce_settings().ready_for_checkout is False


@pytest.mark.skipif(os.name != "nt", reason="Windows drive semantics")
def test_external_storage_on_another_windows_drive_is_not_treated_as_repo_child(
    monkeypatch,
):
    _clear_commerce_env(monkeypatch)
    project_drive = Path(__file__).resolve().drive.upper()
    external_drive = "Y:" if project_drive == "Z:" else "Z:"
    external_path = Path(f"{external_drive}/radar-bds-products")
    _set_ready_commerce_env(monkeypatch, external_path)

    assert get_digital_product_commerce_settings().ready_for_checkout is True


def test_commerce_settings_repr_redacts_secret_values(monkeypatch, tmp_path):
    _clear_commerce_env(monkeypatch)
    _set_ready_commerce_env(monkeypatch, tmp_path)

    settings_repr = repr(get_digital_product_commerce_settings())

    assert "api" not in settings_repr
    assert "checksum" not in settings_repr
    assert "x" * 64 not in settings_repr


class _RecordingConn:
    def __init__(self):
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append(sql)


def _commerce_migration_sql():
    import db.schema as schema

    conn = _RecordingConn()
    schema._migrate_digital_product_order_schema(conn)
    return "\n".join(conn.executed)


def test_schema_exposes_commerce_domain_migration_as_compatibility_alias():
    import db.schema as schema
    from db.migrations.commerce import migrate_digital_product_order_schema

    assert (
        schema._migrate_digital_product_order_schema
        is migrate_digital_product_order_schema
    )


def test_commerce_domain_migration_uses_only_the_supplied_connection():
    from db.migrations.commerce import migrate_digital_product_order_schema

    conn = _RecordingConn()
    migrate_digital_product_order_schema(conn)

    assert conn.executed
    assert any(
        "CREATE TABLE IF NOT EXISTS digital_product_orders" in sql
        for sql in conn.executed
    )


def test_order_schema_contains_security_and_expiry_fields():
    migration_sql = _commerce_migration_sql()

    for column in (
        "public_id",
        "recovery_token_hash",
        "expected_amount",
        "payos_order_code",
        "payment_expires_at",
        "download_expires_at",
        "download_count",
    ):
        assert column in migration_sql
    assert "email" not in migration_sql
    assert "phone" not in migration_sql


def test_order_schema_uses_postgres_identity_and_timezone_aware_dates():
    migration_sql = _commerce_migration_sql()

    assert migration_sql.count(
        "ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY"
    ) == 2
    assert migration_sql.count("ALTER COLUMN id SET NOT NULL") == 2
    assert "TIMESTAMP " not in migration_sql
    assert migration_sql.count("TIMESTAMPTZ") >= 7


def test_order_status_constraint_is_closed():
    migration_sql = _commerce_migration_sql()
    match = re.search(
        r"CHECK\s*\(\s*status\s+IN\s*\((.*?)\)\s*\)",
        migration_sql,
        re.S | re.I,
    )

    assert match is not None
    assert set(re.findall(r"'([^']+)'", match.group(1))) == {
        "pending",
        "paid",
        "expired",
        "cancelled",
        "payment_review",
    }


def test_order_schema_indexes_status_expiry_and_event_foreign_key():
    migration_sql = _commerce_migration_sql()

    assert (
        "CREATE INDEX IF NOT EXISTS idx_digital_product_orders_status_expiry"
        in migration_sql
    )
    assert (
        "ON digital_product_orders(status, payment_expires_at)"
        in migration_sql
    )
    assert (
        "CREATE INDEX IF NOT EXISTS idx_digital_product_order_events_order_id"
        in migration_sql
    )
    assert "ON digital_product_order_events(order_id)" in migration_sql


def test_base_schema_does_not_create_commerce_fk_or_indexes_before_migrations():
    assert "digital_product_order_events_order_id_fkey" not in SCHEMA_SQL
    assert "idx_digital_product_orders_status_expiry" not in SCHEMA_SQL
    assert "idx_digital_product_order_events_order_id" not in SCHEMA_SQL


def test_order_insert_adapter_returns_generated_ids():
    for table_name in ("digital_product_orders", "digital_product_order_events"):
        sql = _add_returning_id(f"INSERT INTO {table_name} (created_at) VALUES (?)")
        assert sql.endswith("RETURNING id")


def test_order_migrations_are_forward_only_and_postgres_idempotent(monkeypatch):
    import db.schema as schema

    class FakeResult:
        def fetchone(self):
            return None

    class FakeConn:
        def __init__(self):
            self.executed = []

        def execute(self, sql, params=None):
            self.executed.append(sql)
            return FakeResult()

    conn = FakeConn()
    monkeypatch.setattr(schema, "_table_columns", lambda _conn, _table: set())
    for helper_name in (
        "_drop_legacy_feedback",
        "_normalize_ai_training_feedback_labels",
        "_migrate_legal_verifications",
        "_migrate_notification_log",
        "_migrate_user_favorite_listings",
        "_migrate_property_type_aliases",
    ):
        monkeypatch.setattr(schema, helper_name, lambda _conn: None)

    schema._run_migrations(conn)
    migration_sql = "\n".join(conn.executed)

    for table_name in ("digital_product_orders", "digital_product_order_events"):
        assert f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS" in migration_sql
    assert "ADD CONSTRAINT IF NOT EXISTS" not in migration_sql.upper()


def test_partial_order_table_migrations_restore_primary_keys():
    migration_sql = _commerce_migration_sql()

    assert (
        "ADD CONSTRAINT digital_product_orders_pkey PRIMARY KEY (id)"
        in migration_sql
    )
    assert (
        "ADD CONSTRAINT digital_product_order_events_pkey PRIMARY KEY (id)"
        in migration_sql
    )


def test_primary_key_guard_rejects_a_non_id_primary_key():
    migration_sql = _commerce_migration_sql()

    assert migration_sql.count("primary key must be id") == 2
    assert migration_sql.count("FROM pg_attribute") == 2
    assert "array_length(conkey, 1) = 1" in migration_sql


def test_id_repair_is_catalog_guarded_backfilled_and_sequence_safe():
    migration_sql = _commerce_migration_sql()

    assert "information_schema.columns" in migration_sql
    assert "is_identity" in migration_sql
    assert "column_default" in migration_sql
    assert migration_sql.count(
        "ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY"
    ) == 2
    assert migration_sql.count("pg_get_serial_sequence") == 2
    assert migration_sql.count("setval") == 2
    assert migration_sql.count("MAX(id)") >= 2
    assert "WHERE id IS NULL" in migration_sql

    for table_name in ("digital_product_orders", "digital_product_order_events"):
        backfill = migration_sql.index(f"UPDATE {table_name}")
        not_null = migration_sql.index(
            f"ALTER TABLE {table_name}\n"
            "                ALTER COLUMN id SET NOT NULL"
        )
        identity = migration_sql.index(
            f"ALTER TABLE {table_name}\n"
            "                    ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY"
        )
        sequence_advance = migration_sql.index(
            "PERFORM setval(", identity
        )
        primary_key = migration_sql.index(
            f"ADD CONSTRAINT {table_name}_pkey PRIMARY KEY (id)"
        )
        assert backfill < not_null < identity < sequence_advance < primary_key


def test_event_repair_fails_clearly_before_fk_or_index_when_order_id_is_unknown():
    migration_sql = _commerce_migration_sql()

    validation = migration_sql.index(
        "digital_product_order_events migration blocked"
    )
    foreign_key = migration_sql.index(
        "ADD CONSTRAINT digital_product_order_events_order_id_fkey"
    )
    event_index = migration_sql.index(
        "CREATE INDEX IF NOT EXISTS idx_digital_product_order_events_order_id"
    )
    assert "order_id IS NULL" in migration_sql
    assert validation < foreign_key < event_index


def test_partial_order_backfill_marks_incomplete_rows_for_review_before_defaults():
    migration_sql = _commerce_migration_sql()

    assert "ADD COLUMN IF NOT EXISTS status TEXT DEFAULT" not in migration_sql
    update = migration_sql.index("UPDATE digital_product_orders")
    status_default = migration_sql.index(
        "ALTER TABLE digital_product_orders "
        "ALTER COLUMN status SET DEFAULT 'pending'"
    )
    assert "'payment_review'" in migration_sql[update:status_default]
    assert update < status_default


class _CommerceSchemaStateMachine:
    def __init__(self, tables=None, null_ids=None):
        self.tables = {
            name: {
                "columns": set(state.get("columns", set())),
                "identity": bool(state.get("identity", False)),
                "id_not_null": bool(state.get("id_not_null", False)),
                "primary_key": bool(state.get("primary_key", False)),
                "foreign_key": bool(state.get("foreign_key", False)),
            }
            for name, state in (tables or {}).items()
        }
        self.null_ids = set(null_ids or ())
        self.executed = []

    def execute(self, sql, params=None):
        normalized = " ".join(sql.split())
        self.executed.append(sql)

        create_match = re.search(
            r"CREATE TABLE IF NOT EXISTS (digital_product_orders|digital_product_order_events)",
            normalized,
        )
        if create_match:
            table_name = create_match.group(1)
            if (
                table_name == "digital_product_order_events"
                and not self.tables.get("digital_product_orders", {}).get(
                    "primary_key"
                )
            ):
                raise AssertionError("events table attempted before order PK repair")
            self.tables.setdefault(
                table_name,
                {
                    "columns": set(),
                    "identity": False,
                    "id_not_null": False,
                    "primary_key": False,
                    "foreign_key": False,
                },
            )

        column_match = re.search(
            r"ALTER TABLE (digital_product_orders|digital_product_order_events) "
            r"ADD COLUMN IF NOT EXISTS ([a-z_]+)",
            normalized,
        )
        if column_match:
            table_name, column_name = column_match.groups()
            if table_name not in self.tables:
                raise AssertionError(f"column attempted before {table_name} exists")
            self.tables[table_name]["columns"].add(column_name)

        for table_name in ("digital_product_orders", "digital_product_order_events"):
            if f"UPDATE {table_name}" in normalized and "WHERE id IS NULL" in normalized:
                self.null_ids.discard(table_name)
            not_null_marker = (
                f"ALTER TABLE {table_name} ALTER COLUMN id SET NOT NULL"
            )
            identity_marker = (
                f"ALTER TABLE {table_name} "
                "ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY"
            )
            not_null_position = normalized.find(not_null_marker)
            identity_position = normalized.find(identity_marker)
            if (
                not_null_position >= 0
                and (
                    identity_position < 0
                    or not_null_position < identity_position
                )
            ):
                if table_name in self.null_ids:
                    raise AssertionError("NOT NULL attempted before ID backfill")
                self.tables[table_name]["id_not_null"] = True
            if identity_position >= 0:
                state = self.tables[table_name]
                if "id" not in state["columns"] or table_name in self.null_ids:
                    raise AssertionError("identity attempted before ID backfill")
                if not state["id_not_null"]:
                    raise AssertionError("identity attempted while ID is nullable")
                state["identity"] = True
            if f"ADD CONSTRAINT {table_name}_pkey PRIMARY KEY (id)" in normalized:
                state = self.tables[table_name]
                if not state["identity"] or table_name in self.null_ids:
                    raise AssertionError("PK attempted before identity repair")
                state["primary_key"] = True

        if "ADD CONSTRAINT digital_product_order_events_order_id_fkey" in normalized:
            orders = self.tables["digital_product_orders"]
            events = self.tables["digital_product_order_events"]
            if not orders["primary_key"] or "order_id" not in events["columns"]:
                raise AssertionError("FK attempted before referenced PK/column")
            events["foreign_key"] = True

        if "idx_digital_product_orders_status_expiry" in normalized:
            columns = self.tables["digital_product_orders"]["columns"]
            if not {"status", "payment_expires_at"} <= columns:
                raise AssertionError("order index attempted before required columns")
        if "idx_digital_product_order_events_order_id" in normalized:
            events = self.tables["digital_product_order_events"]
            if "order_id" not in events["columns"] or not events["foreign_key"]:
                raise AssertionError("event index attempted before FK repair")


def test_greenfield_migration_repairs_keys_before_fk_and_indexes():
    import db.schema as schema

    conn = _CommerceSchemaStateMachine()

    schema._migrate_digital_product_order_schema(conn)

    assert conn.tables["digital_product_orders"]["primary_key"] is True
    assert conn.tables["digital_product_order_events"]["primary_key"] is True
    assert conn.tables["digital_product_order_events"]["foreign_key"] is True


def test_partial_tables_with_null_order_ids_are_repaired_before_dependencies():
    import db.schema as schema

    conn = _CommerceSchemaStateMachine(
        tables={
            "digital_product_orders": {"columns": {"id"}},
            "digital_product_order_events": {"columns": {"id"}},
        },
        null_ids={"digital_product_orders"},
    )

    schema._migrate_digital_product_order_schema(conn)

    assert conn.tables["digital_product_orders"]["identity"] is True
    assert conn.tables["digital_product_orders"]["primary_key"] is True
    assert conn.tables["digital_product_order_events"]["primary_key"] is True
