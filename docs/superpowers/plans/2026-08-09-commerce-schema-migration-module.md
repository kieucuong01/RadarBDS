# Commerce Schema Migration Module Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract the digital-product commerce migration from `db/schema.py` into a domain-owned module without changing SQL, execution order, transaction behavior, or existing import compatibility.

**Architecture:** `db/migrations/commerce.py` will own the commerce migration and its private identity/constraint helpers. `db/schema.py` remains the initialization facade and imports the domain function under the existing `_migrate_digital_product_order_schema` name, so `_run_migrations()` and current callers remain unchanged.

**Tech Stack:** Python 3.12, PostgreSQL DDL, pytest, Graphify.

## Global Constraints

- Do not rewrite `db/schema.py` or split another migration domain in this change.
- Do not change commerce SQL text, statement order, constraints, indexes, defaults, repair policy, or failure messages.
- Do not add a migration framework or dependency.
- Preserve `db.schema.init_schema()`, `db.schema.SCHEMA_SQL`, and `db.schema._migrate_digital_product_order_schema`.
- The domain module must not open, commit, or roll back database connections.
- Do not apply migrations or reprocess production data as part of this refactor.
- Preserve unrelated working-tree files, including `.playwright-cli/`.

---

## File Structure

- Create `db/migrations/__init__.py`: side-effect-free package marker.
- Create `db/migrations/commerce.py`: owns the commerce migration and its two private helpers.
- Modify `db/schema.py`: imports the domain migration as the compatibility alias and removes the moved implementations.
- Modify `tests/test_digital_product_order_schema.py`: proves module ownership, aliasing, and connection-boundary behavior.

### Task 1: Lock the Domain Boundary With Failing Tests

**Files:**
- Modify: `tests/test_digital_product_order_schema.py:125`

**Interfaces:**
- Consumes: existing `db.schema._migrate_digital_product_order_schema(conn)`.
- Produces: `db.migrations.commerce.migrate_digital_product_order_schema(conn)` and an identity-preserving compatibility alias.

- [ ] **Step 1: Add the failing module-ownership tests**

Add after `_commerce_migration_sql()`:

```python
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
```

- [ ] **Step 2: Run the first test and verify the intended failure**

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $py -X utf8 -m pytest tests\test_digital_product_order_schema.py::test_schema_exposes_commerce_domain_migration_as_compatibility_alias -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'db.migrations'`.

- [ ] **Step 3: Run the full file and confirm only the new boundary tests fail**

```powershell
& $py -X utf8 -m pytest tests\test_digital_product_order_schema.py -q
```

Expected: existing commerce tests pass; only the two new imports fail.

### Task 2: Extract the Commerce Migration Module

**Files:**
- Create: `db/migrations/__init__.py`
- Create: `db/migrations/commerce.py`
- Modify: `db/schema.py:1-10`
- Modify: `db/schema.py:2073-2505`

**Interfaces:**
- Consumes: caller-owned `conn` exposing `execute(sql, params=None)`.
- Produces: `migrate_digital_product_order_schema(conn: Any) -> None`.
- Preserves: `db.schema._migrate_digital_product_order_schema` as the same function object.

- [ ] **Step 1: Create the side-effect-free package**

Create `db/migrations/__init__.py`:

```python
"""Domain-owned PostgreSQL schema migrations."""
```

- [ ] **Step 2: Create the domain module**

Create `db/migrations/commerce.py` with:

```python
"""Idempotent PostgreSQL migrations for digital-product commerce."""
from typing import Any
```

Move the existing body of
`db.schema._migrate_digital_product_order_schema` into that function without
editing SQL or statement order. Move the existing helpers into the same module
without semantic edits. Rename only the top-level definition from
`_migrate_digital_product_order_schema(conn: Any) -> None` to
`migrate_digital_product_order_schema(conn: Any) -> None`. Preserve the exact
signatures of `_repair_digital_product_identity` and
`_add_commerce_constraint`.

The top-level migration continues calling those local private helpers. The
module contains no `get_conn`, `commit`, or `rollback` call.

- [ ] **Step 3: Replace the old implementation with the compatibility import**

Add to `db/schema.py` imports:

```python
from db.migrations.commerce import (
    migrate_digital_product_order_schema as _migrate_digital_product_order_schema,
)
```

Delete only the definitions `_migrate_digital_product_order_schema`,
`_repair_digital_product_identity`, and `_add_commerce_constraint` from
`db/schema.py`. Leave `_run_migrations()` unchanged.

- [ ] **Step 4: Run the two boundary tests**

```powershell
& $py -X utf8 -m pytest `
  tests\test_digital_product_order_schema.py::test_schema_exposes_commerce_domain_migration_as_compatibility_alias `
  tests\test_digital_product_order_schema.py::test_commerce_domain_migration_uses_only_the_supplied_connection -q
```

Expected: PASS.

- [ ] **Step 5: Run the complete commerce schema test file**

```powershell
& $py -X utf8 -m pytest tests\test_digital_product_order_schema.py -q
```

Expected: PASS, including PostgreSQL-backed tests when the configured test DB is available.

- [ ] **Step 6: Verify structural completeness**

```powershell
rg -n "^def (_migrate_digital_product_order_schema|_repair_digital_product_identity|_add_commerce_constraint)" db\schema.py
rg -n "^def (migrate_digital_product_order_schema|_repair_digital_product_identity|_add_commerce_constraint)" db\migrations\commerce.py
rg -n "get_conn|\.commit\(|\.rollback\(" db\migrations\commerce.py
```

Expected: the first and third commands return no matches; the second returns exactly three definitions.

- [ ] **Step 7: Commit the extraction**

```powershell
git add -- db\migrations\__init__.py db\migrations\commerce.py db\schema.py tests\test_digital_product_order_schema.py
git diff --cached --check
git commit -m "refactor: extract commerce schema migration"
```

### Task 3: Verify Schema Initialization Compatibility

**Files:**
- Verify: `db/schema.py`
- Verify: `db/migrations/commerce.py`
- Verify: `tests/test_schema_init_permissions.py`
- Verify: `tests/test_digital_product_order_schema.py`

**Interfaces:**
- Consumes: Task 2's compatibility alias and unchanged `_run_migrations()`.
- Produces: evidence that initialization, permissions fallback, and SQL behavior remain intact.

- [ ] **Step 1: Compile affected modules**

```powershell
& $py -X utf8 -m py_compile db\schema.py db\migrations\__init__.py db\migrations\commerce.py
```

Expected: exit code 0 with no output.

- [ ] **Step 2: Run focused schema regressions**

```powershell
& $py -X utf8 -m pytest `
  tests\test_digital_product_order_schema.py `
  tests\test_schema_init_permissions.py `
  tests\test_public_dataset_versions.py `
  tests\test_listing_map_schema.py `
  tests\test_admin_jobs.py `
  tests\test_facebook_profiles_db.py -q
```

Expected: PASS. Existing documented deprecation warnings are acceptable; new failures or warnings are not.

- [ ] **Step 3: Run the broader database/schema suite**

```powershell
$env:DATABASE_URL = 'postgresql://postgres@127.0.0.1:15432/radar_bds'
$env:RADAR_TEST_DATABASE_URL = 'postgresql://postgres@127.0.0.1:15432/radar_bds_test'
& $py -X utf8 -m pytest tests --ignore=tests\test_guland.py --ignore=tests\sanity_test.py -q
```

Expected: PASS with only already-known warnings. If port 15432 is unavailable,
start local PostgreSQL with `scripts/local_postgres.ps1 start`; never substitute
production.

- [ ] **Step 4: Refresh Graphify evidence**

```powershell
graphify update .
graphify path "migrate_digital_product_order_schema" "init_schema"
```

Expected: the path crosses `db/migrations/commerce.py` and `db/schema.py`, with
no import cycle reported. Do not commit `graphify-out/`.

- [ ] **Step 5: Inspect final scope**

```powershell
git status --short --branch
git diff HEAD^ --stat
git diff HEAD^ -- db\schema.py db\migrations\commerce.py tests\test_digital_product_order_schema.py
```

Expected: only intended code/test paths are committed; `.playwright-cli/` remains untouched.
