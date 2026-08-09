# Admin Duplicate QC Service Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract the admin duplicate-QC workflow from `app.py` into a transport-agnostic service while preserving every route, payload, SQL predicate, transaction, audit event, cache action, and duplicate-policy decision.

**Architecture:** `app.py` remains the Flask/auth/request/connection/cache adapter. `services/admin_duplicate_qc.py` receives the active database connection and the existing audit writer, owns queue loading plus merge/split behavior, and returns plain dictionaries or a stable `DuplicateQcError`. The extraction is staged as GET delegation, mutation delegation, then deletion of the unused legacy helpers.

**Tech Stack:** Python 3.12, Flask, PostgreSQL-compatible `db.connection` scopes, pytest/unittest, Graphify 0.9.26.

## Global Constraints

- Design source: `docs/superpowers/specs/2026-08-09-admin-duplicate-qc-service-design.md` at commit `000f39f`.
- This is an extraction only; do not change duplicate heuristics, thresholds, source policy, SQL predicates, response fields, ordering, status codes, or audit action names.
- Preserve the existing GET-side safe-pair suppression without adding writes,
  overrides, or audit records.
- `app.py` remains the sole owner of Flask request parsing, `jsonify()`, `db_mod.get_conn()` scopes, cache loading, and post-commit cache clearing.
- `services/admin_duplicate_qc.py` must not import `app`, Flask, `request`, `jsonify`, route modules, or the admin response cache.
- The service receives the active connection and never opens, commits, or closes a connection itself.
- Keep `_admin_review_items_response()`, schema migrations, SEO articles, routes, frontend code, and database schema out of scope.
- Do not add dependencies or commit `graphify-out/`.
- Preserve unrelated user work and stage only files named by each task.

## File Structure

- Create `services/admin_duplicate_qc.py`: duplicate review queries, payload
  shaping, suppression heuristics, canonical hydration, and explicit merge/split
  mutations.
- Create `tests/test_admin_duplicate_qc_service.py`: service import-boundary and final extraction-boundary tests.
- Modify `app.py`: import the service and reduce the four duplicate-QC handlers to transport/transaction/cache adapters.
- Modify `tests/test_admin_control_room.py`: route delegation, error mapping, and cache-clearing regression tests while retaining the existing database-backed characterization suite.

---

### Task 1: Extract the duplicate review GET workflow

**Files:**
- Create: `services/admin_duplicate_qc.py`
- Create: `tests/test_admin_duplicate_qc_service.py`
- Modify: `app.py:103-133`
- Modify: `app.py:7019-7915`
- Modify: `tests/test_admin_control_room.py:910-990`

**Interfaces:**
- Consumes: the active DB connection, `LEGAL_IMAGE_EVIDENCE_ENABLED`, `services.image_assets.resolve_image_url`, and existing private dedup helpers from `cleansing.dedup`.
- Produces: `DuplicateQcError(code: str)` and `load_duplicate_review_payload(conn) -> dict` returning exactly `{"items": list[dict], "groups": list[dict]}`.

- [ ] **Step 1: Add failing import-boundary and GET-delegation tests**

Create `tests/test_admin_duplicate_qc_service.py` with the transport-boundary test:

```python
import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SERVICE_PATH = ROOT / "services" / "admin_duplicate_qc.py"


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_admin_duplicate_qc_service_has_no_transport_imports():
    assert SERVICE_PATH.exists()
    imports = _imported_modules(SERVICE_PATH)
    assert "app" not in imports
    assert not any(name == "flask" or name.startswith("flask.") for name in imports)
    assert not any(name == "routes" or name.startswith("routes.") for name in imports)
```

Add this method to `AdminControlRoomGateTest` in
`tests/test_admin_control_room.py` immediately before the first existing
duplicate queue test:

```python
def test_data_quality_duplicate_queue_delegates_to_service(self):
    import app as app_module

    self._login_as_admin()
    expected = {"items": [{"id": 77, "title": "service-sentinel"}], "groups": []}
    with mock.patch.object(
        app_module.admin_duplicate_qc,
        "load_duplicate_review_payload",
        return_value=expected,
    ) as loader:
        response = self.client.get("/admin/api/qc/duplicates")

    self.assertEqual(response.status_code, 200)
    self.assertEqual(response.get_json(), expected)
    loader.assert_called_once()
    args, kwargs = loader.call_args
    self.assertEqual(len(args), 1)
    self.assertEqual(kwargs, {})
```

- [ ] **Step 2: Run the new tests and observe RED**

Run:

```powershell
$env:RADAR_TEST_DATABASE_URL='postgresql://postgres@127.0.0.1:15432/radar_bds_test'
$py="$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $py -X utf8 -m pytest tests\test_admin_duplicate_qc_service.py::test_admin_duplicate_qc_service_has_no_transport_imports tests\test_admin_control_room.py::AdminControlRoomGateTest::test_data_quality_duplicate_queue_delegates_to_service -q
```

Expected: FAIL because `services/admin_duplicate_qc.py` and
`app_module.admin_duplicate_qc` do not exist. A database/auth/setup failure is
not the expected RED.

- [ ] **Step 3: Create the service module and transplant the GET dependency graph**

Create the module header and public contract:

```python
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Callable

from cleansing.dedup import (
    _combined_text,
    _has_reliable_lot_signature,
    _road_tokens,
    _text_similarity,
)
from config.settings import LEGAL_IMAGE_EVIDENCE_ENABLED
from services.image_assets import resolve_image_url


AuditWriter = Callable[..., None]


class DuplicateQcError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _image_order_sql(prefix: str = "") -> str:
    col = f"{prefix}." if prefix else ""
    if LEGAL_IMAGE_EVIDENCE_ENABLED:
        return f"CASE WHEN {col}img_type='so_hong' THEN 0 ELSE 1 END, {col}img_order, {col}id"
    return f"{col}img_order, {col}id"


def load_duplicate_review_payload(conn) -> dict:
    items = _admin_duplicate_review_items(conn)
    return {"items": items, "groups": _admin_duplicate_review_groups(items)}
```

Copy the current bodies of these functions from `app.py` into the service,
retaining their names as private implementation details:

```text
_admin_duplicate_review_items
_admin_duplicate_qc_item
_admin_duplicate_member_from_item
_admin_duplicate_review_groups
_admin_same_listing_identity
_has_listing_column
_admin_listing_from_duplicate_item
_admin_near_value
_admin_phone_tail
_admin_distinctive_area
_admin_road_conflict
_admin_should_auto_split_duplicate_pair
_admin_should_auto_merge_duplicate_pair
_admin_should_hide_safe_duplicate_review_pair
_admin_is_suspected_duplicate_pair
_admin_suspected_duplicate_items
_duplicate_qc_reasons
_safe_float
```

Keep the GET helper signatures and call graph unchanged. In particular,
`_admin_should_auto_merge_duplicate_pair()` and
`_admin_should_auto_split_duplicate_pair()` remain suppression predicates that
cause `continue`; they do not perform writes.

Do not copy `_admin_apply_auto_duplicate_merge()` or
`_admin_apply_auto_duplicate_split()` into the service. `rg` proves that the
current source defines but never calls them. Task 3 deletes those dead helpers
from `app.py` so this extraction cannot accidentally activate them.

Keep the existing SQL, conditional branches, thresholds, and return values
byte-for-byte equivalent. Remove the moved functions' local imports only when
the same symbols are present in the module header.

Leave the legacy helpers in `app.py` during Tasks 1 and 2 because the existing
bulk-merge handler still calls them until Task 2. Task 3 removes the dead copy.

- [ ] **Step 4: Delegate the GET route to the service**

Add the module import near the existing admin service imports:

```python
from services import admin_duplicate_qc
```

Replace only the loader body in `admin_api_qc_duplicates()`:

```python
@require_admin_auth
def admin_api_qc_duplicates():
    def _load_payload():
        with db_mod.get_conn() as conn:
            return admin_duplicate_qc.load_duplicate_review_payload(conn)

    return jsonify(
        _cached_admin_read_payload(
            "duplicates",
            "review",
            _load_payload,
            ttl_seconds=15,
        )
    )
```

- [ ] **Step 5: Run focused GET and policy regression tests**

Run:

```powershell
$env:RADAR_TEST_DATABASE_URL='postgresql://postgres@127.0.0.1:15432/radar_bds_test'
$py="$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $py -X utf8 -m pytest tests\test_admin_duplicate_qc_service.py tests\test_admin_control_room.py -k "transport_imports or duplicate_queue or duplicate_review_ui" -q
```

Expected: PASS, including queue grouping, hidden-safe-pair rules, suspected
pairs, the existing no-write behavior, and the new delegation sentinel.

- [ ] **Step 6: Compile and inspect the bounded diff**

Run:

```powershell
$py="$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $py -X utf8 -m py_compile app.py services\admin_duplicate_qc.py
git diff --check
git diff --stat -- app.py services/admin_duplicate_qc.py tests/test_admin_duplicate_qc_service.py tests/test_admin_control_room.py
```

Expected: compile and whitespace checks exit `0`; no schema, route, frontend,
or unrelated file appears.

- [ ] **Step 7: Commit the GET extraction**

```powershell
git add app.py services/admin_duplicate_qc.py tests/test_admin_duplicate_qc_service.py tests/test_admin_control_room.py
git commit -m "refactor: extract admin duplicate review service"
```

---

### Task 2: Delegate explicit merge and split mutations

**Files:**
- Modify: `services/admin_duplicate_qc.py`
- Modify: `app.py:7919-8042`
- Modify: `tests/test_admin_control_room.py:991-1142`

**Interfaces:**
- Consumes: `DuplicateQcError`, the active connection, and the injected audit writer from Task 1.
- Produces: `merge_duplicate(conn, *, listing_id: int, target_id: int, note: str, audit_writer: AuditWriter) -> dict`, `merge_duplicate_group(conn, *, target_id: int, listing_ids: list[int], note: str, audit_writer: AuditWriter) -> dict`, and `split_duplicate(conn, *, listing_id: int, target_id: int, note: str, audit_writer: AuditWriter) -> dict` with the exact response keys defined in the design.

- [ ] **Step 1: Add failing mutation delegation and error-mapping tests**

Add these methods beside the existing duplicate mutation tests:

```python
def test_duplicate_merge_and_split_routes_delegate_and_clear_caches(self):
    import app as app_module

    self._login_as_admin()
    cases = [
        (
            "/admin/api/qc/duplicates/merge",
            "merge_duplicate",
            {"listing_id": 91, "target_listing_id": 90, "note": "pair"},
        ),
        (
            "/admin/api/qc/duplicates/split",
            "split_duplicate",
            {"listing_id": 91, "target_listing_id": 90, "note": "split"},
        ),
    ]
    for path, function_name, payload in cases:
        app_module.clear_admin_read_cache()
        with self.subTest(path=path), mock.patch.object(
            app_module.admin_duplicate_qc,
            function_name,
            return_value={"ok": True},
        ) as operation, mock.patch.object(
            app_module,
            "clear_admin_read_cache",
        ) as clear_cache:
            response = self.client.post(path, json=payload)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"ok": True})
        operation.assert_called_once()
        _, kwargs = operation.call_args
        self.assertEqual(kwargs["listing_id"], 91)
        self.assertEqual(kwargs["target_id"], 90)
        self.assertEqual(kwargs["note"], payload["note"])
        self.assertIs(kwargs["audit_writer"], app_module._write_admin_audit)
        self.assertEqual(
            [call.args[0] for call in clear_cache.call_args_list],
            ["duplicates", "data_quality_summary", "qc_signals"],
        )


def test_duplicate_bulk_merge_maps_service_validation_error(self):
    import app as app_module

    self._login_as_admin()
    error = app_module.admin_duplicate_qc.DuplicateQcError(
        "not_in_duplicate_review_group"
    )
    with mock.patch.object(
        app_module.admin_duplicate_qc,
        "merge_duplicate_group",
        side_effect=error,
    ) as operation:
        response = self.client.post(
            "/admin/api/qc/duplicates/merge-bulk",
            json={"target_listing_id": 90, "listing_ids": [91, 92]},
        )

    self.assertEqual(response.status_code, 400)
    self.assertEqual(
        response.get_json(),
        {"ok": False, "error": "not_in_duplicate_review_group"},
    )
    operation.assert_called_once()
```

- [ ] **Step 2: Run the new mutation tests and observe RED**

Run:

```powershell
$env:RADAR_TEST_DATABASE_URL='postgresql://postgres@127.0.0.1:15432/radar_bds_test'
$py="$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $py -X utf8 -m pytest tests\test_admin_control_room.py::AdminControlRoomGateTest::test_duplicate_merge_and_split_routes_delegate_and_clear_caches tests\test_admin_control_room.py::AdminControlRoomGateTest::test_duplicate_bulk_merge_maps_service_validation_error -q
```

Expected: FAIL because the service does not expose the mutation functions and
the routes still execute their inline implementations.

- [ ] **Step 3: Implement the three mutation entry points**

Move `_hydrate_duplicate_canonical()` from `app.py` into the service unchanged.
Add the three public functions using the current route bodies:

```python
def merge_duplicate(
    conn,
    *,
    listing_id: int,
    target_id: int,
    note: str,
    audit_writer: AuditWriter,
) -> dict:
    before = conn.execute(
        "SELECT id, possibly_duplicate, duplicate_of_id FROM listings WHERE id=?",
        (listing_id,),
    ).fetchone()
    conn.execute(
        """
        INSERT INTO dedup_overrides (
            action, listing_id, target_listing_id, note, active, updated_at
        ) VALUES ('merge', ?, ?, ?, 1, datetime('now'))
        """,
        (listing_id, target_id, note or None),
    )
    conn.execute(
        "UPDATE listings SET possibly_duplicate=1, duplicate_of_id=? WHERE id=?",
        (target_id, listing_id),
    )
    _hydrate_duplicate_canonical(conn, target_id, [listing_id])
    audit_writer(
        conn,
        "dedup_merge",
        "listing",
        listing_id,
        before=dict(before) if before else None,
        after={"id": listing_id, "possibly_duplicate": 1, "duplicate_of_id": target_id},
        reason=note or "merge",
    )
    return {"ok": True}


def merge_duplicate_group(
    conn,
    *,
    target_id: int,
    listing_ids: list[int],
    note: str,
    audit_writer: AuditWriter,
) -> dict:
    review = load_duplicate_review_payload(conn)
    group = None
    for candidate in review["groups"]:
        member_ids = {
            int(member["id"])
            for member in candidate.get("members") or []
            if member.get("id")
        }
        if target_id in member_ids and set(listing_ids).issubset(member_ids):
            group = candidate
            break
    if not group:
        raise DuplicateQcError("not_in_duplicate_review_group")

    merged = 0
    for listing_id in listing_ids:
        before = conn.execute(
            "SELECT id, possibly_duplicate, duplicate_of_id FROM listings WHERE id=?",
            (listing_id,),
        ).fetchone()
        if not before:
            continue
        conn.execute(
            """
            INSERT INTO dedup_overrides (
                action, listing_id, target_listing_id, note, active, updated_at
            ) VALUES ('merge', ?, ?, ?, 1, datetime('now'))
            """,
            (listing_id, target_id, note or None),
        )
        conn.execute(
            "UPDATE listings SET possibly_duplicate=1, duplicate_of_id=? WHERE id=?",
            (target_id, listing_id),
        )
        audit_writer(
            conn,
            "dedup_bulk_merge",
            "listing",
            listing_id,
            before=dict(before),
            after={
                "id": listing_id,
                "possibly_duplicate": 1,
                "duplicate_of_id": target_id,
            },
            reason=note or "bulk_merge",
        )
        merged += 1
    _hydrate_duplicate_canonical(conn, target_id, listing_ids)
    return {
        "ok": True,
        "merged": merged,
        "target_listing_id": target_id,
        "listing_ids": listing_ids,
    }


def split_duplicate(
    conn,
    *,
    listing_id: int,
    target_id: int,
    note: str,
    audit_writer: AuditWriter,
) -> dict:
    before = conn.execute(
        "SELECT id, possibly_duplicate, duplicate_of_id FROM listings WHERE id=?",
        (listing_id,),
    ).fetchone()
    conn.execute(
        """
        INSERT INTO dedup_overrides (
            action, listing_id, target_listing_id, note, active, updated_at
        ) VALUES ('split', ?, ?, ?, 1, datetime('now'))
        """,
        (listing_id, target_id, note or None),
    )
    conn.execute(
        "UPDATE listings SET possibly_duplicate=0, duplicate_of_id=NULL WHERE id=?",
        (listing_id,),
    )
    audit_writer(
        conn,
        "dedup_split",
        "listing",
        listing_id,
        before=dict(before) if before else None,
        after={"id": listing_id, "possibly_duplicate": 0, "duplicate_of_id": None},
        reason=note or "split",
    )
    return {"ok": True}
```

Use these bodies exactly, together with the unchanged
`_hydrate_duplicate_canonical()` body from `app.py:7844-7915`. Do not create new
SQL or change the order of writes. The returned dictionaries are the only new
layer.

- [ ] **Step 4: Replace the three POST handler bodies with service calls**

Keep request parsing and basic ID validation as-is. Each valid handler uses the
existing connection scope:

```python
with db_mod.get_conn() as conn:
    result = admin_duplicate_qc.merge_duplicate(
        conn,
        listing_id=listing_id,
        target_id=target_id,
        note=note,
        audit_writer=_write_admin_audit,
    )
```

Use the corresponding `merge_duplicate_group()` and `split_duplicate()` calls
in the other handlers. For bulk merge only, map the service error after the
connection scope rolls back:

```python
try:
    with db_mod.get_conn() as conn:
        result = admin_duplicate_qc.merge_duplicate_group(
            conn,
            target_id=target_id,
            listing_ids=listing_ids,
            note=note,
            audit_writer=_write_admin_audit,
        )
except admin_duplicate_qc.DuplicateQcError as exc:
    return jsonify({"ok": False, "error": exc.code}), 400
```

After a successful connection scope, keep these exact calls in all three
handlers and then return `jsonify(result)`:

```python
clear_admin_read_cache("duplicates")
clear_admin_read_cache("data_quality_summary")
clear_admin_read_cache("qc_signals")
```

- [ ] **Step 5: Run focused mutation and characterization tests**

Run:

```powershell
$env:RADAR_TEST_DATABASE_URL='postgresql://postgres@127.0.0.1:15432/radar_bds_test'
$py="$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $py -X utf8 -m pytest tests\test_admin_control_room.py -k "duplicate_bulk_merge or duplicate_merge or duplicate_pair_disappears or duplicate_group_disappears or after_admin_split or delegates_and_clear_caches or maps_service_validation_error" -q
```

Expected: PASS for delegation, validation mapping, pair and bulk writes,
canonical hydration, queue disappearance, split override, audit, and cache
clearing behavior.

- [ ] **Step 6: Run the whole duplicate-QC regression group**

```powershell
$env:RADAR_TEST_DATABASE_URL='postgresql://postgres@127.0.0.1:15432/radar_bds_test'
$py="$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $py -X utf8 -m pytest tests\test_admin_duplicate_qc_service.py tests\test_admin_control_room.py -k "duplicate" -q
& $py -X utf8 -m py_compile app.py services\admin_duplicate_qc.py
git diff --check
```

Expected: all selected tests pass and both static checks exit `0`.

- [ ] **Step 7: Commit the mutation delegation**

```powershell
git add app.py services/admin_duplicate_qc.py tests/test_admin_control_room.py
git commit -m "refactor: delegate admin duplicate qc mutations"
```

---

### Task 3: Remove the dead duplicate-QC implementation from `app.py`

**Files:**
- Modify: `app.py:7029-7915`
- Modify: `tests/test_admin_duplicate_qc_service.py`

**Interfaces:**
- Consumes: the four service entry points completed in Tasks 1 and 2.
- Produces: an enforced source boundary where `app.py` contains only the four duplicate route adapters and none of the moved business helpers.

- [ ] **Step 1: Add a failing source-boundary regression test**

Append this test to `tests/test_admin_duplicate_qc_service.py`:

```python
def test_app_contains_no_legacy_duplicate_qc_helpers():
    tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
    definitions = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    moved_helpers = {
        "_admin_duplicate_review_items",
        "_admin_duplicate_qc_item",
        "_admin_duplicate_member_from_item",
        "_admin_duplicate_review_groups",
        "_admin_same_listing_identity",
        "_has_listing_column",
        "_admin_listing_from_duplicate_item",
        "_admin_near_value",
        "_admin_phone_tail",
        "_admin_distinctive_area",
        "_admin_road_conflict",
        "_admin_should_auto_split_duplicate_pair",
        "_admin_should_auto_merge_duplicate_pair",
        "_admin_should_hide_safe_duplicate_review_pair",
        "_admin_apply_auto_duplicate_merge",
        "_admin_apply_auto_duplicate_split",
        "_admin_is_suspected_duplicate_pair",
        "_admin_suspected_duplicate_items",
        "_duplicate_qc_reasons",
        "_safe_float",
        "_hydrate_duplicate_canonical",
    }
    assert definitions.isdisjoint(moved_helpers)
```

- [ ] **Step 2: Run the boundary test and observe RED**

Run:

```powershell
$py="$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $py -X utf8 -m pytest tests\test_admin_duplicate_qc_service.py::test_app_contains_no_legacy_duplicate_qc_helpers -q
```

Expected: FAIL and list the helper definitions still retained temporarily in
`app.py`.

- [ ] **Step 3: Delete only the now-unused helper definitions**

Remove the old function definitions listed by the test from `app.py`. Preserve:

```text
admin_api_qc_duplicates
admin_api_qc_duplicates_merge
admin_api_qc_duplicates_merge_bulk
admin_api_qc_duplicates_split
_image_order_sql
_admin_review_items_response
```

Do not remove `_image_order_sql`; the generic admin review query outside this
subproject still calls it near the current line 6787.

- [ ] **Step 4: Prove there are no old calls or compatibility aliases**

Run:

```powershell
rg -n "def (_admin_duplicate_review_items|_admin_duplicate_qc_item|_admin_duplicate_member_from_item|_admin_duplicate_review_groups|_admin_same_listing_identity|_has_listing_column|_admin_listing_from_duplicate_item|_admin_near_value|_admin_phone_tail|_admin_distinctive_area|_admin_road_conflict|_admin_should_auto_split_duplicate_pair|_admin_should_auto_merge_duplicate_pair|_admin_should_hide_safe_duplicate_review_pair|_admin_apply_auto_duplicate_merge|_admin_apply_auto_duplicate_split|_admin_is_suspected_duplicate_pair|_admin_suspected_duplicate_items|_duplicate_qc_reasons|_safe_float|_hydrate_duplicate_canonical)" app.py
```

Expected: no matches and exit `1` from `rg`. Then measure the extraction against
the approved-spec commit:

```powershell
$baseline=(git show 000f39f:app.py | Measure-Object -Line).Lines
$current=(Get-Content app.py | Measure-Object -Line).Lines
"baseline=$baseline current=$current removed=$($baseline-$current)"
```

Expected: approximately `850-900` lines removed from `app.py`. A result outside
that range requires diff inspection; do not delete unrelated code to meet the
number.

- [ ] **Step 5: Run boundary, duplicate, and full admin tests**

Run:

```powershell
$env:RADAR_TEST_DATABASE_URL='postgresql://postgres@127.0.0.1:15432/radar_bds_test'
$py="$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $py -X utf8 -m pytest tests\test_admin_duplicate_qc_service.py -q
& $py -X utf8 -m pytest tests\test_admin_control_room.py -k "duplicate" -q
& $py -X utf8 -m pytest tests\test_admin_control_room.py -q
& $py -X utf8 -m py_compile app.py services\admin_duplicate_qc.py
git diff --check
```

Expected: all tests and static checks pass. Warnings that already exist are not
new failures, but record any new warning introduced by this extraction.

- [ ] **Step 6: Commit the legacy-helper removal**

```powershell
git add app.py tests/test_admin_duplicate_qc_service.py
git commit -m "refactor: remove duplicate qc helpers from app"
```

---

### Task 4: Verify the final tree and refresh architecture evidence

**Files:**
- Verify: `app.py`
- Verify: `services/admin_duplicate_qc.py`
- Verify: `tests/test_admin_duplicate_qc_service.py`
- Verify: `tests/test_admin_control_room.py`
- Generated but uncommitted: `graphify-out/*`

**Interfaces:**
- Consumes: the completed service boundary from Tasks 1-3.
- Produces: fresh full-suite, import-boundary, line-reduction, Graphify, and clean-worktree evidence for handoff.

- [ ] **Step 1: Run fresh focused and full regression gates**

Run:

```powershell
$env:DATABASE_URL='postgresql://postgres@127.0.0.1:15432/radar_bds'
$env:RADAR_TEST_DATABASE_URL='postgresql://postgres@127.0.0.1:15432/radar_bds_test'
$py="$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $py -X utf8 -m pytest tests\test_admin_duplicate_qc_service.py tests\test_admin_control_room.py -q
& $py -X utf8 -m pytest tests --ignore=tests\test_guland.py --ignore=tests\sanity_test.py -q
```

Expected: both commands exit `0`. A timeout is unverified, not success; rerun
with a larger command timeout rather than reducing the test matrix.

- [ ] **Step 2: Run compile, import, diff, and scope checks**

```powershell
$py="$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $py -X utf8 -m py_compile app.py services\admin_duplicate_qc.py
& $py -X utf8 -c "import app; import services.admin_duplicate_qc"
git diff 000f39f..HEAD --check
git diff 000f39f..HEAD --stat
git status --short
```

Expected: compile/import/diff checks exit `0`; the committed scope contains only
the service, app adapters, two test files, and this plan. The worktree is clean
before Graphify refresh.

- [ ] **Step 3: Refresh Graphify without committing generated output**

The normal command is:

```powershell
graphify update .
```

On this machine the outer uv trampoline currently fails to canonicalize its
script path, so use the verified entry point instead:

```powershell
& 'C:\Users\ASUS\AppData\Roaming\uv\tools\graphifyy\Scripts\graphify.exe' update .
```

Expected: Graphify rebuilds `graph.json` and `GRAPH_REPORT.md` successfully. It
may skip HTML because the graph exceeds 5,000 nodes. Run:

```powershell
git status --short
```

Expected: generated Graphify output remains ignored and the worktree stays
clean. Do not add `graphify-out/`.

- [ ] **Step 4: Review final evidence and commit history**

```powershell
git diff 000f39f..HEAD -- app.py services/admin_duplicate_qc.py tests/test_admin_duplicate_qc_service.py tests/test_admin_control_room.py
git log --oneline -5
git status --short
```

Review the diff against every acceptance criterion in the design. Expected:
three focused implementation commits after the plan commit, no unrelated
changes, and a clean worktree. Do not merge, push, or deploy without the user's
separate integration choice.
