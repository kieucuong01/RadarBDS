# Admin Duplicate QC Service Extraction Design

## Summary

Extract the admin duplicate-quality-control workflow from `app.py` into one
transport-agnostic service module. Keep the existing Flask routes, database
schema, SQL behavior, response payloads, transaction ownership, audit events,
and cache behavior unchanged.

This is an incremental coupling reduction, not a Flask rewrite. Schema
migrations, the generic admin review queue, and the SEO article registry are
separate follow-up projects.

## Problem

The duplicate-QC implementation currently occupies roughly lines 7019-8042 of
`app.py`. Route transport, PostgreSQL reads and writes, review grouping,
duplicate heuristics, canonical hydration, and audit calls are interleaved in
the same module.

That creates three practical costs:

- changes to duplicate matching require editing the main Flask application;
- business behavior is difficult to test without constructing Flask state;
- route ownership is unclear because the existing admin blueprint still
  delegates into a large application module.

The repository already uses `services/` for database-backed application logic
and keeps `routes/` or `app.py` handlers thin. Duplicate QC should follow that
boundary without changing its product behavior.

## Goals

- Create `services/admin_duplicate_qc.py` as the single owner of duplicate-QC
  queries, grouping, suppression heuristics, canonical hydration, and explicit
  merge/split mutations.
- Keep the four Flask handlers as thin transport, transaction, and cache
  adapters.
- Preserve all current response fields, status codes, SQL predicates, audit
  action names, and mutation semantics.
- Preserve the current GET-side safe-pair suppression without introducing
  writes, overrides, or audit events.
- Ensure the service has no Flask or `app.py` dependency and introduces no
  import cycle.
- Remove the moved helper implementations from `app.py` after all callers use
  the service.

## Non-goals

- Do not rewrite or reorganize the rest of `app.py`.
- Do not move `_admin_review_items_response()` or the generic admin review
  queues in this project.
- Do not move routes into `routes/admin_api.py` yet.
- Do not alter duplicate-detection thresholds, text similarity, road matching,
  phone matching, lot signatures, or source-specific policy.
- Do not add schema migrations, columns, indexes, endpoints, or frontend
  changes.
- Do not change admin authentication, cache keys, cache TTLs, or redaction.
- Do not tighten validation beyond the behavior that exists before extraction.

## Chosen Approach

Use a functional service module with explicit connection and audit dependencies.
This gives the duplicate domain a clear owner without introducing a repository
class hierarchy or moving Flask coupling into another route file.

Alternatives rejected for this slice:

1. A dependency-container service class adds lifecycle and mocking boilerplate
   without a current need for service state.
2. Moving all code directly to `routes/admin_api.py` shortens `app.py` but keeps
   transport, SQL, and duplicate policy coupled in one file.

## Architecture

```text
Flask handler in app.py
  -> authenticate and parse request
  -> open db.connection.get_conn() scope
  -> call services.admin_duplicate_qc with the existing connection
  -> service reads PostgreSQL; explicit mutations write and emit injected audit
  -> connection scope commits or rolls back
  -> handler clears admin read caches after a successful mutation
  -> handler converts the plain result to jsonify()
```

The service never opens its own connection and never commits. This preserves
the current transaction boundary and keeps rollback behavior under the existing
`get_conn()` context manager.

## Service Responsibilities

`services/admin_duplicate_qc.py` owns:

- loading the explicit duplicate review queue;
- discovering suspected duplicate pairs;
- suppressing or reconciling safe pairs with the existing rules;
- converting rows into duplicate-QC items and grouped review clusters;
- producing duplicate reason labels and canonical/member payloads;
- hydrating a canonical listing from richer duplicate rows;
- applying explicit pair merge, group merge, and split operations;
- validating that bulk-merge members belong to the same visible review group;
- returning plain Python dictionaries and lists.

`app.py` retains:

- `@require_admin_auth`;
- Flask `request` parsing and `jsonify()`;
- basic transport validation for missing, zero, equal, or malformed IDs;
- the `db_mod.get_conn()` transaction scope;
- the existing admin audit implementation passed as a callback;
- `_cached_admin_read_payload("duplicates", "review", ..., ttl_seconds=15)`;
- clearing `duplicates`, `data_quality_summary`, and `qc_signals` caches after
  successful explicit mutations;
- mapping service validation errors to the current HTTP responses.

## Public Service Interface

The new module exposes these entry points:

```python
def load_duplicate_review_payload(conn) -> dict:
    """Return {'items': [...], 'groups': [...]} using current QC semantics."""


def merge_duplicate(
    conn,
    *,
    listing_id: int,
    target_id: int,
    note: str,
    audit_writer,
) -> dict:
    """Apply the existing pair-merge override and canonical hydration."""


def merge_duplicate_group(
    conn,
    *,
    target_id: int,
    listing_ids: list[int],
    note: str,
    audit_writer,
) -> dict:
    """Validate review-group membership and apply the existing bulk merge."""


def split_duplicate(
    conn,
    *,
    listing_id: int,
    target_id: int,
    note: str,
    audit_writer,
) -> dict:
    """Apply the existing split override and listing update."""
```

The result dictionaries match the current route payloads:

- pair merge and split return `{"ok": True}`;
- bulk merge returns `ok`, `merged`, `target_listing_id`, and `listing_ids`;
- queue loading returns `items` and `groups`.

The module also defines:

```python
class DuplicateQcError(ValueError):
    code: str
```

`merge_duplicate_group()` raises `DuplicateQcError` with code
`not_in_duplicate_review_group` for the current business-validation failure.
The route maps it to the existing `400` JSON response. Basic ID validation
continues to return `{"ok": False, "error": "invalid_ids"}` from the route.

## Dependency Rules

- `services/admin_duplicate_qc.py` must not import `app`, Flask, `request`,
  `jsonify`, the admin response cache, or route modules.
- Stable helpers remain imported from their owning modules, including image
  resolution and existing dedup/text helpers.
- The existing app-local audit writer is injected into the three explicit
  mutation entry points; the GET loader has no audit dependency. The service
  does not relocate the broader admin audit subsystem.
- Internal duplicate-QC helpers become private functions inside the service.
- No compatibility aliases remain in `app.py` after source and test searches
  prove that the old private helpers have no consumers.

## Data and Transaction Semantics

The extraction preserves the following behavior exactly:

- Queue loading is read-only. Safe and near-identical pairs may be hidden by the
  existing predicates, but the GET path does not create overrides, change
  duplicate pointers, or write audit rows.
- `_admin_apply_auto_duplicate_merge()` and
  `_admin_apply_auto_duplicate_split()` have no call sites in the current
  source. They are dead helpers and are deleted rather than activated or copied
  into the service.
- Pair merge inserts a `merge` override, marks the listing as a duplicate,
  hydrates the canonical listing, and emits `dedup_merge`.
- Bulk merge verifies visible review-group membership, inserts one override per
  existing listing, updates duplicate pointers, hydrates the canonical listing,
  and emits `dedup_bulk_merge` per merged listing.
- Split inserts a `split` override, clears the duplicate pointer, and emits
  `dedup_split`.
- Notes remain trimmed by the route and capped at 500 characters.
- A service exception exits the connection scope through rollback and prevents
  post-transaction cache clearing.
- Cache clearing occurs only after the connection scope completes successfully.

## API Compatibility

These endpoints keep their paths and contracts:

- `GET /admin/api/qc/duplicates`
- `POST /admin/api/qc/duplicates/merge`
- `POST /admin/api/qc/duplicates/merge-bulk`
- `POST /admin/api/qc/duplicates/split`

The extraction does not change authentication, JSON keys, ordering, error
codes, HTTP status codes, cache namespace, or cache TTL.

## Migration Sequence

1. Add characterization coverage for service delegation and the import
   boundary while retaining all existing route-level duplicate-QC tests.
2. Create the service module and move queue loading, shaping, grouping,
   suppression heuristics, hydration, and mutation helpers without altering
   their bodies except for explicit dependencies. Delete, rather than move, the
   two uncalled automatic mutation helpers.
3. Switch the GET route to `load_duplicate_review_payload()` and verify the
   complete duplicate queue test group.
4. Switch pair merge, bulk merge, and split routes one at a time and verify the
   relevant mutation tests after each change.
5. Remove the old private helpers from `app.py` after `rg` confirms no remaining
   caller.
6. Refresh Graphify and verify the new service boundary and absence of import
   cycles.

## Testing Strategy

Tests must prove behavior rather than only prove that code moved:

- observe a failing delegation/import-boundary test before implementation;
- keep the existing database-backed route tests as payload, mutation, audit,
  and grouping characterization coverage;
- add focused service tests for plain-result behavior,
  `DuplicateQcError.code`, and the GET path's no-write contract;
- assert that the service source has no Flask or `app.py` import;
- run all duplicate-QC tests in `tests/test_admin_control_room.py`;
- run the entire admin control-room test module;
- run Python compilation and the repository's full regression suite;
- run `git diff --check`;
- refresh Graphify and confirm that no import cycle is introduced.

## Risks and Controls

### Hidden app-local dependencies

The moved helpers currently reference image ordering, image URL resolution,
audit writing, cache clearing, and dedup helpers. Each dependency must either be
imported from its existing owner or passed explicitly. The service must never
resolve this by importing `app.py`.

### Transaction drift

Opening a second connection or clearing caches inside the service could change
commit/rollback ordering. The route remains the sole connection-scope and cache
owner, and service entry points receive the active connection.

### Accidental policy change

Duplicate heuristics contain source-, ward-, area-, road-, phone-, and text-
specific guards. Their expressions and thresholds move unchanged. Policy
cleanup is deferred to a separately reviewed change.

### Oversized replacement module

The new service may remain substantial, but it owns one coherent domain. This
slice prioritizes a stable module boundary. Further internal splitting requires
evidence of a second seam and is not part of this project.

## Acceptance Criteria

- `services/admin_duplicate_qc.py` owns all duplicate-QC business and database
  helpers formerly located between the duplicate routes in `app.py`.
- The four Flask handlers contain only authentication, transport validation,
  connection scoping, service calls, cache handling, error mapping, and JSON
  response construction.
- `app.py` is reduced by approximately 850-900 lines without unrelated edits.
- No endpoint, payload, SQL behavior, audit action, cache behavior, schema, or
  frontend behavior changes.
- Duplicate-QC characterization tests, the full admin control-room suite, and
  the repository regression suite pass.
- Python compilation and `git diff --check` pass.
- Graphify is refreshed and shows no import cycle involving the new service.
