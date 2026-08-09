# Commerce Schema Migration Module Design

## Context

`db/schema.py` currently owns the base schema, schema initialization policy, and
all idempotent migrations. The file has grown to roughly 2,700 lines. The
commerce migration for `digital_product_orders` and
`digital_product_order_events`, including identity repair and constraint
creation, is a large self-contained block with dedicated regression coverage.

This change is a narrow P2 coupling reduction. It does not redesign the schema
system or introduce a migration framework.

## Goals

- Move commerce-specific migration logic into a domain-owned module.
- Preserve the public `db.schema.init_schema()` and `db.schema.SCHEMA_SQL`
  interfaces.
- Preserve the exact commerce SQL, execution order, transaction boundaries,
  and fail-closed validation behavior.
- Keep existing internal imports of
  `db.schema._migrate_digital_product_order_schema` working during the gradual
  migration split.
- Add a repeatable module pattern for later domain-by-domain extraction.

## Non-Goals

- Rewriting `db/schema.py` or splitting every migration in one change.
- Changing table or column definitions, constraints, indexes, defaults, or data
  repair policy.
- Introducing Alembic or another schema migration dependency.
- Applying or reprocessing production data as part of this refactor.
- Moving the base commerce table placeholders into `SCHEMA_SQL`.

## Approaches Considered

### 1. Domain module with a compatibility facade (selected)

Create `db/migrations/commerce.py` and move the commerce migration plus its two
private helpers into it. `db/schema.py` imports the domain migration under its
existing private name and continues to call it from the same place in
`_run_migrations()`.

This removes the complete commerce dependency cluster while preserving current
call sites and test seams. It is the smallest change that produces a real
domain boundary.

### 2. Move only the top-level migration function

Leave identity repair and constraint helpers in `db/schema.py` and inject or
import them from the new module. This reduces line count but keeps bidirectional
coupling and makes the commerce module harder to understand independently.

### 3. Split all schema migrations at once

Create modules for every domain and replace the whole migration dispatcher in
one change. This would reduce `db/schema.py` faster, but it expands regression
risk across permissions, read models, Radar Ask, auth, crawl, and public
content. It is outside the agreed incremental P2 scope.

## Architecture

Create the package and module:

```text
db/
  migrations/
    __init__.py
    commerce.py
  schema.py
```

`db/migrations/commerce.py` owns:

```python
def migrate_digital_product_order_schema(conn: Any) -> None: ...
def _repair_digital_product_identity(conn: Any, table_name: str) -> None: ...
def _add_commerce_constraint(
    conn: Any,
    table_name: str,
    constraint_name: str,
    definition: str,
    *,
    primary_key: bool = False,
) -> None: ...
```

`db/schema.py` retains a compatibility alias:

```python
from db.migrations.commerce import (
    migrate_digital_product_order_schema as _migrate_digital_product_order_schema,
)
```

`_run_migrations(conn)` continues to invoke
`_migrate_digital_product_order_schema(conn)` at its existing position. No
other domain imports the private helpers.

## Data and Control Flow

The control flow remains:

```text
init_schema()
  -> execute SCHEMA_SQL
  -> _run_migrations(conn)
  -> db.schema compatibility alias
  -> db.migrations.commerce.migrate_digital_product_order_schema(conn)
```

The commerce migration still repairs the order table before creating the event
table, then validates and creates primary keys before foreign keys and indexes.
All statements run on the connection supplied by `init_schema()`; the new
module does not open, commit, or roll back connections.

## Error Handling and Safety

- Existing PostgreSQL validation exceptions remain unchanged, including
  duplicate IDs, duplicate public IDs or order codes, invalid identity state,
  missing or orphan event order IDs, and conflicting primary keys.
- The commerce module must not catch migration exceptions. Failures propagate
  to `init_schema()` exactly as before.
- The module must not call `commit()`, `rollback()`, `get_conn()`, or execute
  migration work at import time.
- SQL text and statement order are copied without semantic edits.
- The base `SCHEMA_SQL` continues not to create commerce foreign keys or
  performance indexes before the repair migration runs.

## Compatibility

Production and CLI entry points continue to use `db.schema.init_schema()`.
Existing tests or internal tools importing the private compatibility name from
`db.schema` continue to work. New tests should import the public domain function
from `db.migrations.commerce` when testing module ownership directly.

The compatibility alias can be removed only in a later explicitly scoped
cleanup after repository-wide call sites have moved.

## Testing

The implementation will use test-driven extraction:

1. Add an ownership/delegation test proving `db.schema` exposes the domain
   migration as its compatibility alias.
2. Run that test before the module exists to verify the intended failure.
3. Move the unchanged migration and helpers into the new module.
4. Run `tests/test_digital_product_order_schema.py` to cover SQL shape,
   fail-closed repairs, idempotency, and PostgreSQL execution behavior.
5. Run `tests/test_schema_init_permissions.py` to cover initialization and
   limited-owner behavior.
6. Compile the affected modules and run the broader schema-related regression
   set before completion.

## Success Criteria

- Commerce migration implementation and helpers no longer live in
  `db/schema.py`.
- `db.schema.init_schema()`, `db.schema.SCHEMA_SQL`, and the compatibility
  migration name behave as before.
- Generated commerce migration SQL and execution ordering remain equivalent.
- Focused commerce, permission, and schema tests pass.
- No unrelated migrations, runtime services, application routes, or production
  data are changed.
