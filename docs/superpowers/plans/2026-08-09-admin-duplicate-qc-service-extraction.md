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
- Create `tests/test_admin_duplicate_qc_service.py`: service import side-effect test.
- Modify `app.py`: import the service and reduce the four duplicate-QC handlers to transport/transaction/cache adapters.
- Modify `tests/test_admin_control_room.py`: real service behavior and route
  error-mapping characterization tests while retaining the existing
  database-backed route suite.

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

- [ ] **Step 1: Add failing import-side-effect and real GET service tests**

Create `tests/test_admin_duplicate_qc_service.py` with a subprocess test that
exercises the real import boundary:

```python
import subprocess
import sys


def test_admin_duplicate_qc_import_does_not_load_flask_transport():
    script = """
import sys
import services.admin_duplicate_qc
assert "app" not in sys.modules
assert not any(name == "flask" or name.startswith("flask.") for name in sys.modules)
"""
    completed = subprocess.run(
        [sys.executable, "-X", "utf8", "-c", script],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
```

Add these methods to `AdminControlRoomGateTest` in
`tests/test_admin_control_room.py` immediately before the first existing
duplicate queue test:

```python
def test_duplicate_service_loads_real_review_payload(self):
    from db.connection import get_conn
    from services import admin_duplicate_qc

    canonical_id, duplicate_id = self._insert_review_duplicate_pair(
        area_old=100.0,
        area_new=112.0,
    )
    with get_conn() as conn:
        payload = admin_duplicate_qc.load_duplicate_review_payload(conn)

    pairs = {(item["id"], item["duplicate_of_id"]) for item in payload["items"]}
    self.assertIn((duplicate_id, canonical_id), pairs)
    self.assertTrue(payload["groups"])


def test_duplicate_service_hides_near_identical_pair_without_writing(self):
    from db.connection import get_conn
    from services import admin_duplicate_qc

    listing_id, target_id = self._insert_near_identical_dx132_pair()
    with get_conn() as conn:
        payload = admin_duplicate_qc.load_duplicate_review_payload(conn)

    pairs = {(item["id"], item["duplicate_of_id"]) for item in payload["items"]}
    self.assertNotIn((listing_id, target_id), pairs)
    with get_conn() as conn:
        listing = conn.execute(
            "SELECT possibly_duplicate, duplicate_of_id FROM listings WHERE id=?",
            (listing_id,),
        ).fetchone()
        override_count = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM dedup_overrides
            WHERE listing_id=? AND target_listing_id=? AND active=1
            """,
            (listing_id, target_id),
        ).fetchone()["count"]

    self.assertEqual(listing["possibly_duplicate"], 0)
    self.assertIsNone(listing["duplicate_of_id"])
    self.assertEqual(override_count, 0)
```

- [ ] **Step 2: Run the new tests and observe RED**

Run:

```powershell
$env:RADAR_TEST_DATABASE_URL='postgresql://postgres@127.0.0.1:15432/radar_bds_test'
$py="$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $py -X utf8 -m pytest tests\test_admin_duplicate_qc_service.py::test_admin_duplicate_qc_import_does_not_load_flask_transport tests\test_admin_control_room.py::AdminControlRoomGateTest::test_duplicate_service_loads_real_review_payload tests\test_admin_control_room.py::AdminControlRoomGateTest::test_duplicate_service_hides_near_identical_pair_without_writing -q
```

Expected: FAIL because `services.admin_duplicate_qc` does not exist. The
subprocess returns a `ModuleNotFoundError`, and the two database tests fail on
the same missing service import. A database/setup failure is not the expected
RED.

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
& $py -X utf8 -m pytest tests\test_admin_duplicate_qc_service.py tests\test_admin_control_room.py -k "import_does_not_load_flask_transport or duplicate_service or duplicate_queue or duplicate_review_ui" -q
```

Expected: PASS, including queue grouping, hidden-safe-pair rules, suspected
pairs, the existing no-write behavior, and the new direct service contract.

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

- [ ] **Step 1: Add failing real service mutation tests**

Add these methods beside the existing duplicate mutation tests:

```python
def test_duplicate_service_merge_updates_listing_override_and_audit(self):
    import app as app_module
    from db.connection import get_conn
    from services import admin_duplicate_qc

    canonical_id, duplicate_id = self._insert_review_duplicate_pair(
        area_old=100.0,
        area_new=112.0,
    )
    with get_conn() as conn:
        result = admin_duplicate_qc.merge_duplicate(
            conn,
            listing_id=duplicate_id,
            target_id=canonical_id,
            note="service_pair_merge",
            audit_writer=app_module._write_admin_audit,
        )

    self.assertEqual(result, {"ok": True})
    with get_conn() as conn:
        listing = conn.execute(
            "SELECT possibly_duplicate, duplicate_of_id FROM listings WHERE id=?",
            (duplicate_id,),
        ).fetchone()
        override_count = conn.execute(
            """
            SELECT COUNT(*) AS count FROM dedup_overrides
            WHERE action='merge' AND listing_id=? AND target_listing_id=?
              AND note='service_pair_merge' AND active=1
            """,
            (duplicate_id, canonical_id),
        ).fetchone()["count"]
        audit_count = conn.execute(
            """
            SELECT COUNT(*) AS count FROM admin_audit_log
            WHERE action='dedup_merge' AND entity_type='listing' AND entity_id=?
            """,
            (duplicate_id,),
        ).fetchone()["count"]

    self.assertEqual((listing["possibly_duplicate"], listing["duplicate_of_id"]), (1, canonical_id))
    self.assertEqual(override_count, 1)
    self.assertEqual(audit_count, 1)


def test_duplicate_service_split_clears_pointer_and_writes_override(self):
    import app as app_module
    from db.connection import get_conn
    from services import admin_duplicate_qc

    canonical_id, duplicate_id = self._insert_review_duplicate_pair()
    with get_conn() as conn:
        result = admin_duplicate_qc.split_duplicate(
            conn,
            listing_id=duplicate_id,
            target_id=canonical_id,
            note="service_split",
            audit_writer=app_module._write_admin_audit,
        )

    self.assertEqual(result, {"ok": True})
    with get_conn() as conn:
        listing = conn.execute(
            "SELECT possibly_duplicate, duplicate_of_id FROM listings WHERE id=?",
            (duplicate_id,),
        ).fetchone()
        override_count = conn.execute(
            """
            SELECT COUNT(*) AS count FROM dedup_overrides
            WHERE action='split' AND listing_id=? AND target_listing_id=?
              AND note='service_split' AND active=1
            """,
            (duplicate_id, canonical_id),
        ).fetchone()["count"]

    self.assertEqual((listing["possibly_duplicate"], listing["duplicate_of_id"]), (0, None))
    self.assertEqual(override_count, 1)


def test_duplicate_service_bulk_merge_rejects_nonmember(self):
    import app as app_module
    from db.connection import get_conn
    from services import admin_duplicate_qc

    canonical_id, child_ids = self._insert_review_duplicate_cluster()
    with self.assertRaises(admin_duplicate_qc.DuplicateQcError) as raised:
        with get_conn() as conn:
            admin_duplicate_qc.merge_duplicate_group(
                conn,
                target_id=canonical_id,
                listing_ids=[child_ids[0], 999999999],
                note="invalid_group",
                audit_writer=app_module._write_admin_audit,
            )

    self.assertEqual(raised.exception.code, "not_in_duplicate_review_group")


def test_duplicate_bulk_merge_route_preserves_nonmember_error(self):
    self._login_as_admin()
    canonical_id, child_ids = self._insert_review_duplicate_cluster()

    response = self.client.post(
        "/admin/api/qc/duplicates/merge-bulk",
        json={
            "target_listing_id": canonical_id,
            "listing_ids": [child_ids[0], 999999999],
        },
    )

    self.assertEqual(response.status_code, 400)
    self.assertEqual(
        response.get_json(),
        {"ok": False, "error": "not_in_duplicate_review_group"},
    )
```

- [ ] **Step 2: Run the new mutation tests and observe RED**

Run:

```powershell
$env:RADAR_TEST_DATABASE_URL='postgresql://postgres@127.0.0.1:15432/radar_bds_test'
$py="$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $py -X utf8 -m pytest tests\test_admin_control_room.py::AdminControlRoomGateTest::test_duplicate_bulk_merge_route_preserves_nonmember_error -q
& $py -X utf8 -m pytest tests\test_admin_control_room.py::AdminControlRoomGateTest::test_duplicate_service_merge_updates_listing_override_and_audit tests\test_admin_control_room.py::AdminControlRoomGateTest::test_duplicate_service_split_clears_pointer_and_writes_override tests\test_admin_control_room.py::AdminControlRoomGateTest::test_duplicate_service_bulk_merge_rejects_nonmember -q
```

Expected: the first command passes as characterization of the current route.
The second command fails because the service does not expose the three mutation
functions. Each service test exercises the desired contract against the real
database and real audit writer; no route or service mock is involved.

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
& $py -X utf8 -m pytest tests\test_admin_control_room.py -k "duplicate_bulk_merge or duplicate_merge or duplicate_pair_disappears or duplicate_group_disappears or after_admin_split or duplicate_service_merge or duplicate_service_split or duplicate_service_bulk_merge_rejects_nonmember" -q
```

Expected: PASS for direct service behavior, route validation mapping, pair and bulk writes,
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

**Interfaces:**
- Consumes: the four service entry points completed in Tasks 1 and 2.
- Produces: `app.py` containing only the four duplicate route adapters and none
  of the moved or dead business helpers.

- [ ] **Step 1: Establish a GREEN behavioral baseline before cleanup**

Run the real service and route characterization tests before deleting any code:

```powershell
$env:RADAR_TEST_DATABASE_URL='postgresql://postgres@127.0.0.1:15432/radar_bds_test'
$py="$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $py -X utf8 -m pytest tests\test_admin_duplicate_qc_service.py tests\test_admin_control_room.py -k "duplicate" -q
```

Expected: PASS. This is the REFACTOR checkpoint of the TDD cycles from Tasks 1
and 2; helper deletion must keep the same behavior tests green.

- [ ] **Step 2: Delete only the now-unused helper definitions**

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

- [ ] **Step 3: Prove there are no old calls or compatibility aliases**

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

- [ ] **Step 4: Run duplicate and full admin tests after cleanup**

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

- [ ] **Step 5: Commit the legacy-helper removal**

```powershell
git add app.py
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
