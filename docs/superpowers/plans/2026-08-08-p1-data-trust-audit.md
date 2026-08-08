# P1 Read-Only Data Trust Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one bounded, machine-readable operator command that proves its PostgreSQL transaction is read-only before checking Radar BDS schema, source freshness, pipeline invariants, public read models, map coverage, publisher policy, and extraction quality without exposing credentials or PII.

**Architecture:** Open one fresh PostgreSQL connection, start and verify a read-only transaction with a local statement timeout, run composable checks through that same connection, and always roll back and close. A scoped `ContextVar` read-connection override lets existing default/deep public-feed comparisons reuse the verified transaction without changing normal request behavior.

**Tech Stack:** Python 3.12, PostgreSQL 17, psycopg 3, argparse, pytest 8.4.2

## Global Constraints

- This plan starts after P0 and the P1 marketing workstream pass their focused gates.
- `radar.py data-trust-audit [--json] [--deep] [--limit 200]` must never call `init_schema()`, reprocess, refresh, publish, prewarm, acquire a write-oriented advisory lock, or bump a dataset version.
- Every domain query runs only after `SHOW transaction_read_only` returns `on` in the same transaction and connection.
- A statement timeout, connection/configuration error, unverifiable read-only state, missing required schema, broken invariant, or required parity mismatch is never reported as success.
- The command opens a fresh connection; it does not borrow the application pool.
- The command always rolls back and closes, including on success, failure, timeout, keyboard interruption, and deep-compare mismatch.
- Output may contain counts, bounded IDs already allowed by existing compare diagnostics, field names, reason codes, thresholds, and timestamps. It must not contain usernames, passwords, query parameters, URLs, titles, descriptions, phones, emails, IPs, user-agents, publisher keys, raw JSON, or row samples.
- Facebook is primary; Guland is secondary; BatDongSan freshness is never required.
- The audit does not authorize an automatic repair, refresh, reprocess, delete, relabel, or feature-flag change.
- Local verification uses `radar_bds_test`; a production run, credential rotation, deploy, or service restart needs separate explicit authorization.

---

## File Structure

- Modify `services/market_data.py`: scoped read-connection factory override used only when an explicit context manager is active.
- Create `tests/test_read_connection_override.py`: normal-path and scoped-override isolation tests.
- Create `services/data_trust_audit.py`: result model, masking, transaction enforcement, check registry, orchestration, and exit classification.
- Create `tests/test_data_trust_audit.py`: unit tests for every status boundary, timeout, masking, PII safety, and no-write contracts.
- Create `tests/test_data_trust_audit_postgres.py`: real PostgreSQL transaction/read-only/rollback integration tests.
- Create `cli/data_trust.py`: CLI rendering and exit codes.
- Modify `radar.py`: parser registration and dispatch only.
- Create `tests/test_data_trust_cli.py`: parser, JSON/text, bounds, and exit-code tests.
- Modify `docs/operations.md`: safe local/production execution, evidence boundaries, and non-remediation rule.
- Modify `docs/dev_commands.md`: exact local test and command examples.

### Task 1: Add a scoped read-connection override

**Files:**
- Modify: `services/market_data.py:1-35,791-816`
- Create: `tests/test_read_connection_override.py`

**Interfaces:**
- Produces: `use_read_connection_factory(factory: Callable[[], ContextManager]) -> ContextManager[None]`.
- Changes: `_read_conn()` checks a task-local override before using `get_conn()`.
- Preserves: default Flask/service reads continue using the bounded application pool.

- [ ] **Step 1: Write failing override-isolation tests**

```python
def test_read_conn_uses_scoped_factory_and_restores_default(monkeypatch):
    default_conn = object()
    audit_conn = object()
    monkeypatch.setattr(market_data, "get_conn", lambda: scope(default_conn))

    with market_data.use_read_connection_factory(lambda: scope(audit_conn)):
        with market_data._read_conn() as conn:
            assert conn is audit_conn

    with market_data._read_conn() as conn:
        assert conn is default_conn
```

Add nested-context and exception-reset tests. Add a test proving `_open_read_conn(...).close()` exits only the supplied scope and does not call `audit_conn.close()`.

- [ ] **Step 2: Run the tests and verify RED**

Run: `& $py -X utf8 -m pytest tests\test_read_connection_override.py -q`

- [ ] **Step 3: Implement the task-local override**

Use `contextvars.ContextVar`, not a process-global mutable variable:

```python
_READ_CONNECTION_FACTORY = ContextVar(
    "radar_read_connection_factory",
    default=None,
)

@contextmanager
def use_read_connection_factory(factory):
    token = _READ_CONNECTION_FACTORY.set(factory)
    try:
        yield
    finally:
        _READ_CONNECTION_FACTORY.reset(token)
```

In `_read_conn`, enter the override factory when present; otherwise retain the exact existing `get_conn()` path. Do not change `_ScopedReadConnection` behavior or any loader signature.

- [ ] **Step 4: Run focused and loader regressions**

```powershell
& $py -X utf8 -m pytest tests\test_read_connection_override.py tests\test_signal_read_model.py tests\test_listing_feed.py -q
```

- [ ] **Step 5: Commit the connection seam**

```powershell
git add services/market_data.py tests/test_read_connection_override.py
git commit -m "refactor: scope read connections for audit reuse"
```

### Task 2: Define the audit result model, masking, and transaction shell

**Files:**
- Create: `services/data_trust_audit.py`
- Create: `tests/test_data_trust_audit.py`

**Interfaces:**
- Produces: `AuditCheck(name, status, reason, measurements, threshold=None, source_timestamp=None)`.
- Produces: `mask_database_target(url: str) -> dict[str, object]`.
- Produces: `run_data_trust_audit(*, deep: bool = False, limit: int = 200, statement_timeout_ms: int = 15_000, connection_factory=connect, now: datetime | None = None) -> dict[str, object]`.
- Guarantees: one fresh connection, verified read-only transaction, bounded timeout, unconditional rollback/close.

- [ ] **Step 1: Write failing result and mask tests**

```python
def test_mask_database_target_never_returns_credentials_or_query():
    masked = mask_database_target(
        "postgresql://private-user:private-pass@db.example.test:5432/radar?sslmode=require"
    )
    assert masked == {
        "scheme": "postgresql",
        "host": "db.example.test",
        "port": 5432,
        "database": "radar",
    }
    assert "private" not in json.dumps(masked)

def test_audit_check_serializes_only_stable_safe_fields():
    rendered = AuditCheck(
        name="source_freshness_facebook",
        status="warn",
        reason="source_stale_warning",
        measurements={"age_hours": 40.0},
        threshold={"pass_hours": 36, "fail_hours": 72},
    ).as_dict()
    assert set(rendered) == {
        "name", "status", "reason", "measurements", "threshold"
    }
```

Validate names/reasons against `^[a-z][a-z0-9_]{0,79}$`, statuses against `pass|warn|fail|skipped`, and measurements recursively as only null/bool/finite number/safe short string/list/dict.

- [ ] **Step 2: Write failing transaction-order and cleanup tests**

Use a recording fake connection and assert exact order:

```python
assert statements[:4] == [
    "BEGIN",
    "SET TRANSACTION READ ONLY",
    "SELECT set_config('statement_timeout', ?, true)",
    "SHOW transaction_read_only",
]
assert fake.rollback_calls == 1
assert fake.close_calls == 1
```

Repeat for a check exception, a timeout-like exception, and `KeyboardInterrupt`. Assert no domain check runs if read-only verification returns anything except `on`.

- [ ] **Step 3: Run tests and verify RED**

Run: `& $py -X utf8 -m pytest tests\test_data_trust_audit.py -q`

- [ ] **Step 4: Implement the transaction shell**

Use `db.connection.connect`, which opens a fresh connection. Read the configured URL only to build the masked target and never place the full URL in the result or log. Execute:

```python
conn.execute("BEGIN")
conn.execute("SET TRANSACTION READ ONLY")
conn.execute(
    "SELECT set_config('statement_timeout', ?, true)",
    (f"{bounded_timeout_ms}ms",),
)
state = conn.execute("SHOW transaction_read_only").fetchone()[0]
```

Clamp timeout to `1_000..60_000` ms and limit to `1..1_000`. Enter `use_read_connection_factory(lambda: shared_scope(conn))` only after `state == "on"`. In `finally`, call rollback then close, each guarded so one cleanup error does not skip the other. Never commit.

- [ ] **Step 5: Implement fail-closed top-level status**

Return:

```python
{
    "overall_status": "pass" | "warn" | "fail" | "unverified",
    "target": masked_target,
    "generated_at": utc_iso,
    "duration_ms": non_negative_int,
    "deep": bool,
    "limit": bounded_limit,
    "checks": [check.as_dict(), ...],
}
```

Any check `fail` makes `overall_status=fail`; warnings with no failures make `warn`; all pass/skipped makes `pass`. Configuration, connection, read-only verification, or unexpected execution errors return `unverified` with a safe stable reason code and no raw exception text.

- [ ] **Step 6: Run unit tests and commit**

```powershell
& $py -X utf8 -m pytest tests\test_data_trust_audit.py tests\test_read_connection_override.py -q
git add services/data_trust_audit.py tests/test_data_trust_audit.py
git commit -m "feat: enforce read-only data audit transactions"
```

### Task 3: Implement schema, source, and pipeline invariant checks

**Files:**
- Modify: `services/data_trust_audit.py`
- Modify: `tests/test_data_trust_audit.py`

**Interfaces:**
- Each check consumes the already verified connection and returns one or more `AuditCheck` objects.
- Default checks select aggregates/metadata only; they never return row samples.

- [ ] **Step 1: Write failing schema-contract tests**

Use fixture metadata to verify required tables, columns, and indexes. Required tables are:

```python
REQUIRED_TABLES = frozenset({
    "raw_listings", "listings", "valuation_results", "crawl_runs",
    "public_dataset_versions", "signal_card_read_model",
    "listing_map_locations", "source_publishers", "listing_publishers",
})
```

Require the columns used by the audit and public contract, including `listings.price_ty`, `listings.area_m2`, `listings.extraction_quality_flags`, `valuation_results.listing_id`, `signal_card_read_model.is_actionable`, `signal_card_read_model.publisher_visible_public`, `listing_map_locations.location_precision`, and `source_publishers.activity_class`. Require `idx_raw_source_crawled`, `idx_listings_source_first_seen`, `idx_valuation_listing_computed`, and `idx_signal_card_public_filter`. Missing required metadata is `fail/schema_contract_missing` with names only.

- [ ] **Step 2: Write failing source-freshness tests**

Query the latest successful `crawl_runs.finished_at` for statuses in the explicit set `done|success|completed`. With a fixed `now`, assert:

- Facebook: pass at age `<=36h`, warn at `>36h and <=72h`, fail beyond `72h`, fail when absent;
- Guland: pass at age `<=96h`, warn at `>96h and <=168h`, fail beyond `168h`, warn when absent;
- BatDongSan is not queried or returned as required freshness.

Return only source, age hours, latest safe timestamp, and threshold.

- [ ] **Step 3: Write failing count and invariant tests**

Assert measurements cover:

- raw rows;
- canonical listings (`duplicate_of_id IS NULL`);
- active visible-base listings;
- latest valuations via `LATEST_VALUATION_CTE`;
- actionable signals via `actionable_signal_sql("v")` and `actionable_listing_sql("l")`;
- read-model base cards and `is_actionable` cards.

Add invariant failure cases for actionable rows with `price_ty <= 0`, `area_m2 <= 0`, `actual_ppm2 <= 0`, suppressed listing status, hidden/review flags, or a non-actionable current quality condition. Return only counts by invariant name.

- [ ] **Step 4: Implement metadata and freshness checks**

Query `information_schema.tables`, `information_schema.columns`, and `pg_indexes` using fixed schema/name parameters. Query crawl freshness grouped by `source`, never selecting `area` or `error_msg`. Parse timestamps defensively as UTC-aware; an invalid required source timestamp is `fail/source_timestamp_invalid`.

- [ ] **Step 5: Implement aggregate pipeline checks**

Reuse `LATEST_VALUATION_CTE`, `actionable_signal_sql`, and `actionable_listing_sql` rather than duplicating signal rules. Use `COUNT(*)`/`COUNT(DISTINCT ...)` only. Distinguish an empty but structurally valid development/test database (`warn/empty_dataset`) from contradictions such as actionable count greater than latest-valuation count (`fail/pipeline_count_contradiction`).

- [ ] **Step 6: Run unit tests and commit**

```powershell
& $py -X utf8 -m pytest tests\test_data_trust_audit.py -q
git add services/data_trust_audit.py tests/test_data_trust_audit.py
git commit -m "feat: audit source freshness and pipeline invariants"
```

### Task 4: Implement versions, public parity, map, publisher, and extraction checks

**Files:**
- Modify: `services/data_trust_audit.py`
- Modify: `tests/test_data_trust_audit.py`

**Interfaces:**
- Consumes: environment feature flags and aggregate metadata from public read-model tables.
- Produces: safe pass/warn/fail/skipped checks for each remaining trust boundary.

- [ ] **Step 1: Write failing durable-version tests**

Cover the explicit flag contract:

- `signals` must be present and positive when `RADAR_SIGNAL_READ_MODEL_ENABLED=1`;
- `listings` must be present and positive when signal read model is enabled and `RADAR_LISTING_READ_MODEL_ENABLED` is not `0`;
- `market` must be present and positive when `RADAR_PUBLIC_CACHE_ENABLED=1`;
- missing/nonpositive required versions fail;
- disabled optional versions are measured and `skipped`, not silently declared ready.

Only return dataset names, integer versions, required booleans, and safe updated timestamps.

- [ ] **Step 2: Write failing default public parity tests**

Inside the scoped connection override, compare:

```python
raw_actionable = conn.execute(
    "SELECT COUNT(*) AS n FROM signal_card_read_model "
    "WHERE is_actionable AND publisher_visible_public"
).fetchone()["n"]
public_count = count_signals_from_read_model(tier="guest")
```

Equality passes; mismatch fails with both counts only. A required table missing or query timeout is a failure/unverified boundary, never zero-parity success.

- [ ] **Step 3: Write failing map and publisher-policy tests**

Map output includes listing candidate count, mapped/unmapped counts, and fixed buckets `exact|road|landmark|nearby|ward`. Assert `mapped + unmapped == candidates` and the precision bucket sum equals mapped count. Invalid precision or contradictory totals fail.

Publisher output contains counts only for `unknown|low_manual|high_activity|automated_repost`, plus invalid class count. Any invalid stored/effective policy value fails. Do not select or return publisher keys, names, reasons, metrics JSON, or identities.

- [ ] **Step 4: Write failing extraction-quality tests**

Aggregate bounded flagged counts by the known fields `price_ty`, `area_m2`, `ward`, `road_name`, `property_type`, `frontage_m`, `depth_m`, and `tho_cu_m2` from stable flags/provenance columns. Cap each numeric result at the total inspected count and cap the inspected window at the latest `10_000` canonical listings. Return no listing IDs or samples in the default audit.

- [ ] **Step 5: Implement the remaining checks**

Use fixed SQL, parameterized values, and deterministic output ordering. Treat missing optional publisher rows as `skipped/no_guland_publishers`; zero map candidates as `skipped/no_map_candidates`; contradictory data as `fail`. Reuse the same verified connection for `count_signals_from_read_model()` through the scoped override.

- [ ] **Step 6: Add serialized-output safety tests**

Seed sentinel strings resembling a URL, phone, email, IP, user-agent, and publisher key in ignored columns. Serialize the complete report and assert every sentinel is absent. Assert no output key contains `url`, `phone`, `email`, `ip`, `user_agent`, `title`, `description`, `publisher_key`, `raw_json`, or `sample`.

- [ ] **Step 7: Run unit tests and commit**

```powershell
& $py -X utf8 -m pytest tests\test_data_trust_audit.py -q
git add services/data_trust_audit.py tests/test_data_trust_audit.py
git commit -m "feat: audit public data trust boundaries"
```

### Task 5: Add deep read-model comparisons without initialization or refresh

**Files:**
- Modify: `services/data_trust_audit.py`
- Modify: `tests/test_data_trust_audit.py`
- Modify: `tests/test_read_connection_override.py`

**Interfaces:**
- Consumes: `cli.system.compare_signal_read_model(limit)` and `compare_listing_read_model(limit)`.
- Produces: `deep_signal_read_model` and `deep_listing_read_model` checks.
- Guarantees: both existing comparison functions use the same verified read-only connection through the scoped override.

- [ ] **Step 1: Write failing deep-mode tests**

Patch both compare functions to inspect `_read_conn()` and assert it yields the verified audit connection. Assert `deep=False` never imports/calls them. For `deep=True`, zero differences pass and any mismatch fails while retaining only the existing safe keys:

```python
SAFE_DEEP_DIAGNOSTIC_KEYS = frozenset({
    "case", "tier", "legacy_count", "read_model_count",
    "legacy_only_ids", "read_model_only_ids", "order_mismatch",
    "field_names", "metadata_fields",
})
```

Bound each difference list and each ID list to `limit`.

- [ ] **Step 2: Add explicit mutation-tripwire tests**

Monkeypatch `db.schema.init_schema`, `services.public_data_publish.publish_public_data`, `services.signal_read_model.refresh_signal_card_read_model`, and prewarm entry points to raise immediately if called. Run default and deep audits and assert none are invoked. Inspect executed SQL and reject statements beginning with `INSERT`, `UPDATE`, `DELETE`, `ALTER`, `CREATE`, `DROP`, `TRUNCATE`, `REFRESH`, `VACUUM`, or `CALL` after normalization.

- [ ] **Step 3: Run tests and verify RED**

Run: `& $py -X utf8 -m pytest tests\test_data_trust_audit.py tests\test_read_connection_override.py -q`

- [ ] **Step 4: Implement deep checks inside the verified scope**

Lazy-import the comparison functions only when `deep=True`. Convert `status=ok` to `pass/read_model_match` and `status=mismatch` to `fail/read_model_mismatch`. Retain aggregate case counts, difference count, and bounded safe diagnostics; drop all unknown keys defensively.

- [ ] **Step 5: Run focused tests and existing compare tests**

```powershell
& $py -X utf8 -m pytest tests\test_data_trust_audit.py tests\test_read_connection_override.py tests\test_signal_read_model.py tests\test_listing_feed.py -q
```

- [ ] **Step 6: Commit deep comparison support**

```powershell
git add services/data_trust_audit.py tests/test_data_trust_audit.py tests/test_read_connection_override.py
git commit -m "feat: compare read models inside read-only audit"
```

### Task 6: Add the CLI, stable exit codes, and safe rendering

**Files:**
- Create: `cli/data_trust.py`
- Modify: `radar.py:108-183,485-505`
- Create: `tests/test_data_trust_cli.py`

**Interfaces:**
- Adds: `data-trust-audit --json --deep --limit 200`.
- Exit `0`: overall `pass` or `warn` and no failed/unverified check.
- Exit `1`: one or more verified data-trust checks failed.
- Exit `2`: configuration, connection, timeout, read-only state, or audit execution could not be verified.

- [ ] **Step 1: Write failing parser and dispatch tests**

Assert default `limit=200`, `deep=False`, `as_json=False`; valid bounds are `1..1000`; `0`, `1001`, and non-integers are parser errors. Assert dispatch calls only `cmd_data_trust_audit(args)` and never `cmd_signal_read_model` or `init_schema`.

- [ ] **Step 2: Write failing renderer/exit tests**

Patch `run_data_trust_audit()` with pass/warn/fail/unverified reports. In JSON mode, assert `json.loads(stdout)` equals the report and stderr is empty. In text mode, assert stable one-line check summaries and masked target fields. Seed a password/token in a fake exception and assert neither stream includes it.

- [ ] **Step 3: Run CLI tests and verify RED**

Run: `& $py -X utf8 -m pytest tests\test_data_trust_cli.py -q`

- [ ] **Step 4: Implement focused CLI ownership**

Keep rendering and exit mapping in `cli/data_trust.py`. The service returns data and never prints. `cmd_data_trust_audit` prints exactly one JSON document for `--json`; text output uses safe result fields only. Raise `SystemExit(code)` for `1` or `2`, and return normally for `0`.

- [ ] **Step 5: Register the command in `radar.py`**

Reuse `_bounded_signal_compare_limit` or rename it to a generic bounded audit/compare limit helper. Do not add `--refresh`, output-path, database-URL, or remediation flags.

- [ ] **Step 6: Run CLI tests and help smoke**

```powershell
& $py -X utf8 -m pytest tests\test_data_trust_cli.py -q
& $py -X utf8 radar.py data-trust-audit --help
```

- [ ] **Step 7: Commit the CLI**

```powershell
git add cli/data_trust.py radar.py tests/test_data_trust_cli.py
git commit -m "feat: add data trust audit command"
```

### Task 7: Prove read-only behavior against PostgreSQL

**Files:**
- Create: `tests/test_data_trust_audit_postgres.py`
- Modify: `services/data_trust_audit.py`

**Interfaces:**
- Uses: dedicated `RADAR_TEST_DATABASE_URL` only.
- Proves: transaction state is read-only, mutation is rejected, committed data/version state is unchanged, and cleanup occurs.

- [ ] **Step 1: Write the real integration test**

Initialize the test schema before starting the audit test, snapshot:

- `public_dataset_versions` rows;
- counts for `raw_listings`, `listings`, `valuation_results`, `signal_card_read_model`, `listing_map_locations`, and `source_publishers`.

Use an injected probe check that executes `SHOW transaction_read_only` and records `on`, then attempts a harmless write inside a savepoint and asserts PostgreSQL rejects it with `ReadOnlySqlTransaction`. Roll back the failed savepoint/transaction through the audit cleanup path.

- [ ] **Step 2: Run the integration test and verify RED or the missing hook**

```powershell
$env:DATABASE_URL='postgresql://postgres@127.0.0.1:15432/radar_bds'
$env:RADAR_TEST_DATABASE_URL='postgresql://postgres@127.0.0.1:15432/radar_bds_test'
& $py -X utf8 -m pytest tests\test_data_trust_audit_postgres.py -q
```

- [ ] **Step 3: Add a private test-only check injection seam if required**

Allow `run_data_trust_audit(..., checks=None)` where `None` selects the frozen production registry. Reject externally supplied check callables from the CLI. Keep the seam keyword-only and document it as test-only.

- [ ] **Step 4: Assert before/after database equality**

After audit cleanup, open a separate connection and assert every snapshot count/version equals its original value. Also assert no schema table/index was added. Run both default and `deep=True` on the real test database with a small limit.

- [ ] **Step 5: Run unit plus integration tests and commit**

```powershell
& $py -X utf8 -m pytest tests\test_data_trust_audit.py tests\test_data_trust_cli.py tests\test_data_trust_audit_postgres.py -q
git add services/data_trust_audit.py tests/test_data_trust_audit_postgres.py
git commit -m "test: prove data audit is PostgreSQL read only"
```

### Task 8: Document operations and run the P1 data-trust gate

**Files:**
- Modify: `docs/operations.md`
- Modify: `docs/dev_commands.md`
- Modify: `tests/test_data_trust_cli.py`

**Interfaces:**
- Documents: local test usage, authorized production sequence, JSON retention outside git, exit meanings, and evidence boundaries.
- Produces: verified local implementation only; it does not perform a production release.

- [ ] **Step 1: Add failing documentation-contract tests**

Assert both docs contain the command, exit codes `0|1|2`, `SET TRANSACTION READ ONLY`, statement timeout, no automatic remediation, and the instruction to store production JSON outside the repository. Assert production docs require deployed SHA and service verification before audit execution.

- [ ] **Step 2: Update operational documentation**

Document:

```powershell
& $py -X utf8 radar.py data-trust-audit --json
& $py -X utf8 radar.py data-trust-audit --json --deep --limit 200
```

Explain that redirecting production JSON is an operator action to an ignored/outside-git path, a timeout is unverified, warnings are visible but exit zero, failures exit one, and environment/execution uncertainty exits two. State that the local credential previously exposed during audit preparation must be rotated before an authorized production release, without printing or reproducing it.

- [ ] **Step 3: Run the complete data-trust regression set**

```powershell
& $py -X utf8 -m pytest tests\test_read_connection_override.py tests\test_data_trust_audit.py tests\test_data_trust_cli.py tests\test_data_trust_audit_postgres.py tests\test_signal_read_model.py tests\test_listing_feed.py -q
& $py -X utf8 radar.py data-trust-audit --json --limit 20
git diff --check
```

Expected locally: tests pass; the live local audit may be `pass`, `warn`, or verified `fail` depending on fixture/data freshness, but it must parse as JSON, prove read-only, contain no credential/PII, and return the documented exit code. A verified local data warning/failure is evidence, not permission to modify data.

- [ ] **Step 4: Run the full branch gate**

```powershell
& $py -X utf8 -m py_compile app.py radar.py db\connection.py db\schema.py services\admin_growth.py services\admin_marketing.py services\marketing_tracking.py services\data_trust_audit.py cli\data_trust.py
& $py -X utf8 -m pytest tests --ignore=tests\test_guland.py --ignore=tests\sanity_test.py
node --test tests/js/*.cjs tests/js/test_*.js
node --check static\js\admin.js
git diff --check
```

- [ ] **Step 5: Commit docs and local completion evidence**

```powershell
git add docs/operations.md docs/dev_commands.md tests/test_data_trust_cli.py
git commit -m "docs: define read-only data audit operations"
```

- [ ] **Step 6: Stop before production actions**

Report the verified branch state and ask for separate authorization before credential rotation, push/deploy, service restart, VPS audit execution, public cache/redaction smoke, or browser verification. Do not describe local success as production completion.
