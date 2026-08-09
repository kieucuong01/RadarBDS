"""Idempotent PostgreSQL migrations for digital-product commerce."""
from typing import Any


def migrate_digital_product_order_schema(conn: Any) -> None:
    """Build or repair commerce tables before adding dependent objects."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS digital_product_orders (id BIGINT)"
    )
    order_columns = (
        "id BIGINT",
        "public_id TEXT",
        "product_slug TEXT",
        "product_version TEXT",
        "expected_amount INTEGER",
        "currency TEXT",
        "payos_order_code BIGINT",
        "payment_link_id TEXT",
        "checkout_url TEXT",
        "qr_code TEXT",
        "status TEXT",
        "recovery_token_hash TEXT",
        "paid_amount INTEGER",
        "payment_reference TEXT",
        "status_reason TEXT",
        "created_at TIMESTAMPTZ",
        "updated_at TIMESTAMPTZ",
        "payment_expires_at TIMESTAMPTZ",
        "paid_at TIMESTAMPTZ",
        "download_expires_at TIMESTAMPTZ",
        "download_count INTEGER",
        "last_download_at TIMESTAMPTZ",
        "last_checked_at TIMESTAMPTZ",
    )
    for column_sql in order_columns:
        conn.execute(
            "ALTER TABLE digital_product_orders "
            f"ADD COLUMN IF NOT EXISTS {column_sql}"
        )

    _repair_digital_product_identity(conn, "digital_product_orders")
    conn.execute("""
        UPDATE digital_product_orders
           SET public_id = CASE
                   WHEN NULLIF(BTRIM(public_id), '') IS NULL
                   THEN '__migration_review_order_' || id::text
                   ELSE BTRIM(public_id)
               END,
               product_slug = COALESCE(NULLIF(BTRIM(product_slug), ''), 'migration-review'),
               product_version = COALESCE(NULLIF(BTRIM(product_version), ''), '0'),
               expected_amount = CASE
                   WHEN expected_amount IS NULL OR expected_amount <= 0 THEN 1
                   ELSE expected_amount
               END,
               currency = 'VND',
               payos_order_code = COALESCE(payos_order_code, id),
               status = CASE
                   WHEN NULLIF(BTRIM(public_id), '') IS NULL
                     OR NULLIF(BTRIM(product_slug), '') IS NULL
                     OR NULLIF(BTRIM(product_version), '') IS NULL
                     OR expected_amount IS NULL
                     OR expected_amount <= 0
                     OR currency IS DISTINCT FROM 'VND'
                     OR payos_order_code IS NULL
                     OR payment_expires_at IS NULL
                   THEN 'payment_review'
                   WHEN status IN ('pending', 'paid', 'expired', 'cancelled', 'payment_review')
                   THEN status
                   ELSE 'payment_review'
               END,
               created_at = COALESCE(created_at, CURRENT_TIMESTAMP),
               updated_at = COALESCE(updated_at, CURRENT_TIMESTAMP),
               payment_expires_at = COALESCE(payment_expires_at, CURRENT_TIMESTAMP),
               download_count = GREATEST(COALESCE(download_count, 0), 0)
    """)
    for column_name, default_sql in (
        ("currency", "'VND'"),
        ("status", "'pending'"),
        ("created_at", "CURRENT_TIMESTAMP"),
        ("updated_at", "CURRENT_TIMESTAMP"),
        ("download_count", "0"),
    ):
        conn.execute(
            "ALTER TABLE digital_product_orders "
            f"ALTER COLUMN {column_name} SET DEFAULT {default_sql}"
        )
    conn.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT public_id
                  FROM digital_product_orders
                 GROUP BY public_id
                HAVING COUNT(*) > 1
            ) THEN
                RAISE EXCEPTION
                    'digital_product_orders migration blocked: duplicate public_id';
            END IF;
            IF EXISTS (
                SELECT payos_order_code
                  FROM digital_product_orders
                 GROUP BY payos_order_code
                HAVING COUNT(*) > 1
            ) THEN
                RAISE EXCEPTION
                    'digital_product_orders migration blocked: duplicate payos_order_code';
            END IF;
        END $$;
    """)
    for column_name in (
        "public_id",
        "product_slug",
        "product_version",
        "expected_amount",
        "currency",
        "payos_order_code",
        "status",
        "created_at",
        "updated_at",
        "payment_expires_at",
        "download_count",
    ):
        conn.execute(
            "ALTER TABLE digital_product_orders "
            f"ALTER COLUMN {column_name} SET NOT NULL"
        )

    _add_commerce_constraint(
        conn,
        "digital_product_orders",
        "digital_product_orders_pkey",
        "PRIMARY KEY (id)",
        primary_key=True,
    )
    for constraint_name, definition in (
        ("digital_product_orders_public_id_key", "UNIQUE (public_id)"),
        (
            "digital_product_orders_expected_amount_check",
            "CHECK (expected_amount > 0)",
        ),
        (
            "digital_product_orders_currency_check",
            "CHECK (currency = 'VND')",
        ),
        (
            "digital_product_orders_payos_order_code_key",
            "UNIQUE (payos_order_code)",
        ),
        (
            "digital_product_orders_payment_link_id_key",
            "UNIQUE (payment_link_id)",
        ),
        (
            "digital_product_orders_status_check",
            "CHECK (status IN ('pending', 'paid', 'expired', 'cancelled', 'payment_review'))",
        ),
        (
            "digital_product_orders_download_count_check",
            "CHECK (download_count >= 0)",
        ),
    ):
        _add_commerce_constraint(
            conn,
            "digital_product_orders",
            constraint_name,
            definition,
        )

    # The referenced order PK is repaired before the event table can exist.
    conn.execute(
        "CREATE TABLE IF NOT EXISTS digital_product_order_events (id BIGINT)"
    )
    event_columns = (
        "id BIGINT",
        "order_id BIGINT",
        "event_type TEXT",
        "external_reference TEXT",
        "payload_hash TEXT",
        "created_at TIMESTAMPTZ",
    )
    for column_sql in event_columns:
        conn.execute(
            "ALTER TABLE digital_product_order_events "
            f"ADD COLUMN IF NOT EXISTS {column_sql}"
        )

    _repair_digital_product_identity(conn, "digital_product_order_events")
    conn.execute("""
        UPDATE digital_product_order_events
           SET event_type = COALESCE(NULLIF(BTRIM(event_type), ''), 'migration_review'),
               external_reference = COALESCE(external_reference, ''),
               payload_hash = COALESCE(payload_hash, ''),
               created_at = COALESCE(created_at, CURRENT_TIMESTAMP)
    """)
    for column_name, default_sql in (
        ("external_reference", "''"),
        ("payload_hash", "''"),
        ("created_at", "CURRENT_TIMESTAMP"),
    ):
        conn.execute(
            "ALTER TABLE digital_product_order_events "
            f"ALTER COLUMN {column_name} SET DEFAULT {default_sql}"
        )
    conn.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                  FROM digital_product_order_events
                 WHERE order_id IS NULL
            ) THEN
                RAISE EXCEPTION
                    'digital_product_order_events migration blocked: order_id is unknown';
            END IF;
            IF EXISTS (
                SELECT 1
                  FROM digital_product_order_events event
                  LEFT JOIN digital_product_orders orders
                    ON orders.id = event.order_id
                 WHERE orders.id IS NULL
            ) THEN
                RAISE EXCEPTION
                    'digital_product_order_events migration blocked: orphan order_id';
            END IF;
        END $$;
    """)
    for column_name in (
        "order_id",
        "event_type",
        "external_reference",
        "payload_hash",
        "created_at",
    ):
        conn.execute(
            "ALTER TABLE digital_product_order_events "
            f"ALTER COLUMN {column_name} SET NOT NULL"
        )

    _add_commerce_constraint(
        conn,
        "digital_product_order_events",
        "digital_product_order_events_pkey",
        "PRIMARY KEY (id)",
        primary_key=True,
    )
    _add_commerce_constraint(
        conn,
        "digital_product_order_events",
        "digital_product_order_events_order_id_fkey",
        "FOREIGN KEY (order_id) REFERENCES digital_product_orders(id)",
    )
    _add_commerce_constraint(
        conn,
        "digital_product_order_events",
        "digital_product_order_events_order_event_reference_key",
        "UNIQUE (order_id, event_type, external_reference)",
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_digital_product_orders_status_expiry "
        "ON digital_product_orders(status, payment_expires_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_digital_product_order_events_order_id "
        "ON digital_product_order_events(order_id)"
    )


def _repair_digital_product_identity(conn: Any, table_name: str) -> None:
    conn.execute(
        f"""
        DO $$
        DECLARE
            id_data_type TEXT;
            identity_state TEXT;
            identity_generation_state TEXT;
            default_expr TEXT;
            sequence_name TEXT;
            max_id BIGINT;
            missing_count BIGINT;
        BEGIN
            SELECT data_type, is_identity, identity_generation, column_default
              INTO id_data_type, identity_state, identity_generation_state, default_expr
              FROM information_schema.columns
             WHERE table_schema = 'public'
               AND table_name = '{table_name}'
               AND column_name = 'id';

            IF id_data_type NOT IN ('smallint', 'integer', 'bigint') THEN
                RAISE EXCEPTION
                    '{table_name} migration blocked: id must be an integer type';
            END IF;
            IF id_data_type <> 'bigint' THEN
                ALTER TABLE {table_name}
                    ALTER COLUMN id TYPE BIGINT USING id::bigint;
            END IF;
            IF EXISTS (
                SELECT id
                  FROM {table_name}
                 WHERE id IS NOT NULL
                 GROUP BY id
                HAVING COUNT(*) > 1
            ) THEN
                RAISE EXCEPTION
                    '{table_name} migration blocked: duplicate id';
            END IF;

            SELECT GREATEST(COALESCE(MAX(id), 0), 0),
                   COUNT(*) FILTER (WHERE id IS NULL)
              INTO max_id, missing_count
              FROM {table_name};
            IF max_id > 9223372036854775807 - missing_count THEN
                RAISE EXCEPTION
                    '{table_name} migration blocked: id range exhausted';
            END IF;
            WITH numbered AS (
                SELECT ctid, ROW_NUMBER() OVER (ORDER BY ctid) AS offset
                  FROM {table_name}
                 WHERE id IS NULL
            )
            UPDATE {table_name} AS target
               SET id = max_id + numbered.offset
              FROM numbered
             WHERE target.ctid = numbered.ctid;

            ALTER TABLE {table_name}
                ALTER COLUMN id SET NOT NULL;

            IF identity_state <> 'YES' THEN
                IF default_expr IS NOT NULL THEN
                    RAISE EXCEPTION
                        '{table_name} migration blocked: non-identity id default requires manual review';
                END IF;
                ALTER TABLE {table_name}
                    ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY;
            ELSIF identity_generation_state <> 'BY DEFAULT' THEN
                ALTER TABLE {table_name}
                    ALTER COLUMN id SET GENERATED BY DEFAULT;
            END IF;

            SELECT pg_get_serial_sequence('public.{table_name}', 'id')
              INTO sequence_name;
            IF sequence_name IS NULL THEN
                RAISE EXCEPTION
                    '{table_name} migration blocked: identity sequence is unavailable';
            END IF;
            SELECT GREATEST(COALESCE(MAX(id), 0), 0)
              INTO max_id
              FROM {table_name};
            PERFORM setval(
                sequence_name::regclass,
                GREATEST(max_id, 1),
                max_id > 0
            );
        END $$;
        """
    )


def _add_commerce_constraint(
    conn: Any,
    table_name: str,
    constraint_name: str,
    definition: str,
    *,
    primary_key: bool = False,
) -> None:
    if primary_key:
        conn.execute(
            f"""
            DO $$
            DECLARE
                id_attribute SMALLINT;
            BEGIN
                SELECT attnum
                  INTO id_attribute
                  FROM pg_attribute
                 WHERE attrelid = 'public.{table_name}'::regclass
                   AND attname = 'id'
                   AND attnum > 0
                   AND NOT attisdropped;
                IF id_attribute IS NULL THEN
                    RAISE EXCEPTION
                        '{table_name} migration blocked: id column is unavailable';
                END IF;
                IF EXISTS (
                    SELECT 1
                      FROM pg_constraint
                     WHERE contype = 'p'
                       AND conrelid = 'public.{table_name}'::regclass
                ) AND NOT EXISTS (
                    SELECT 1
                      FROM pg_constraint
                     WHERE contype = 'p'
                       AND conrelid = 'public.{table_name}'::regclass
                       AND array_length(conkey, 1) = 1
                       AND conkey[1] = id_attribute
                ) THEN
                    RAISE EXCEPTION
                        '{table_name} migration blocked: primary key must be id';
                END IF;
                IF NOT EXISTS (
                    SELECT 1
                      FROM pg_constraint
                     WHERE contype = 'p'
                       AND conrelid = 'public.{table_name}'::regclass
                       AND array_length(conkey, 1) = 1
                       AND conkey[1] = id_attribute
                ) THEN
                    ALTER TABLE {table_name}
                    ADD CONSTRAINT {constraint_name} {definition};
                END IF;
            END $$;
            """
        )
        return

    existence_check = (
        f"conname = '{constraint_name}'"
    )
    conn.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                  FROM pg_constraint
                 WHERE {existence_check}
                   AND conrelid = 'public.{table_name}'::regclass
            ) THEN
                ALTER TABLE {table_name}
                ADD CONSTRAINT {constraint_name} {definition};
            END IF;
        END $$;
        """
    )
