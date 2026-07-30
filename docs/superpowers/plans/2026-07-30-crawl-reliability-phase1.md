# Crawl Reliability Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make PostgreSQL tests isolated, raw inserts unambiguous, crawl-run statuses truthful, and `crawl-health` reliable before changing Guland reconciliation behavior.

**Architecture:** Add a fail-closed PostgreSQL test URL guard, introduce a typed raw-insert result while retaining the legacy wrapper, centralize crawl status derivation, and move health queries into the crawl-run repository. Base and Facebook crawlers consume the same result/status contracts, while ops alerts treat partial runs as unhealthy.

**Tech Stack:** Python 3.12, PostgreSQL 18, psycopg 3, Flask, pytest/unittest, PowerShell.

## Global Constraints

- Runtime remains PostgreSQL-only through `DATABASE_URL`.
- Tests that open a database must use `RADAR_TEST_DATABASE_URL`; its database name must contain `test`.
- Do not print or commit database URLs, passwords, Apify tokens, phone numbers, or raw third-party payloads.
- Facebook remains the primary crawler and Guland remains the secondary crawler.
- BatDongSan remains disabled.
- Operational database errors must propagate; duplicates and validation skips remain non-fatal.
- A run is `done` only when it has zero operational errors.
- Preserve current guest/free/VIP redaction and notification behavior.

---

### Task 1: Fail-Closed PostgreSQL Test Database Selection

**Files:**
- Modify: `db/connection.py:207-234`
- Modify: `tests/test_postgres_connection.py`
- Modify: `tests/test_price_history.py:42-65`
- Modify: `tests/test_source_policy.py:14-45`
- Modify: `tests/test_drop_filter.py:13-38`
- Modify: `tests/test_lot_history.py:13-34`
- Modify: `docs/dev_commands.md:11-19`

**Interfaces:**
- Produces: `db.connection._is_test_process() -> bool`
- Produces: `db.connection._validate_test_database_url(url: str) -> str`
- Consumes: `RADAR_TEST_DATABASE_URL` for tests and `DATABASE_URL` for normal runtime.

- [x] **Step 1: Write failing URL-selection tests**

Add tests that prove pytest cannot fall back to the application database:

```python
def test_test_process_requires_explicit_test_database(monkeypatch):
    monkeypatch.delenv("RADAR_TEST_DATABASE_URL", raising=False)
    monkeypatch.setattr(connection, "_is_test_process", lambda: True)
    with pytest.raises(connection.DatabaseConfigurationError, match="RADAR_TEST_DATABASE_URL"):
        connection._database_url()


def test_test_database_name_must_contain_test(monkeypatch):
    monkeypatch.setenv(
        "RADAR_TEST_DATABASE_URL",
        "postgresql://radar:secret@127.0.0.1:5432/radar_bds",
    )
    monkeypatch.setattr(connection, "_is_test_process", lambda: True)
    with pytest.raises(connection.DatabaseConfigurationError, match="database name"):
        connection._database_url()
```

- [x] **Step 2: Run the tests and confirm the old fallback fails**

Run:

```powershell
& $py -X utf8 -m pytest tests\test_postgres_connection.py -q
```

Expected: the new tests fail because `_is_test_process` and the database-name guard do not exist.

- [x] **Step 3: Implement the fail-closed selector**

Use `urllib.parse.urlparse` and keep runtime behavior unchanged:

```python
def _is_test_process() -> bool:
    return "pytest" in sys.modules or bool(os.getenv("PYTEST_CURRENT_TEST"))


def _validate_test_database_url(url: str) -> str:
    db_name = urlparse(url).path.rsplit("/", 1)[-1].lower()
    if "test" not in db_name:
        raise DatabaseConfigurationError(
            "RADAR_TEST_DATABASE_URL database name must contain 'test'"
        )
    return url


def _database_url() -> str:
    test_url = (os.getenv("RADAR_TEST_DATABASE_URL") or "").strip()
    if _is_test_process():
        if not test_url:
            raise DatabaseConfigurationError(
                "RADAR_TEST_DATABASE_URL is required while running tests"
            )
        return _validate_test_database_url(test_url)
    url = (os.getenv("DATABASE_URL") or "").strip()
    if not url:
        raise DatabaseConfigurationError("DATABASE_URL is required")
    return url
```

- [x] **Step 4: Remove ineffective SQLite `DB_PATH` setup from focused integration tests**

Delete `TemporaryDirectory`, `DB_PATH` patching, and related teardown in the four focused files. Retain their UUID URL/user tokens and deterministic PostgreSQL cleanup. Do not change their assertions.

- [x] **Step 5: Document the exact test invocation**

Add this invocation after setting `RADAR_TEST_DATABASE_URL` in the local shell
or secret manager; do not put its value in the repository:

```powershell
if (-not $env:RADAR_TEST_DATABASE_URL) { throw "Set RADAR_TEST_DATABASE_URL to the local radar_bds_test database" }
& $py -X utf8 -m pytest tests\test_postgres_connection.py tests\test_price_history.py -q
```

State explicitly that the password stays local and the database name must contain `test`.

- [x] **Step 6: Run focused PostgreSQL tests**

Run:

```powershell
& $py -X utf8 -m pytest tests\test_postgres_connection.py tests\test_price_history.py tests\test_source_policy.py tests\test_drop_filter.py tests\test_lot_history.py -q
```

Expected: all selected tests pass against `radar_bds_test`; the normal `radar_bds` database receives no test rows.

- [x] **Step 7: Commit test isolation**

```powershell
git add db/connection.py tests/test_postgres_connection.py tests/test_price_history.py tests/test_source_policy.py tests/test_drop_filter.py tests/test_lot_history.py docs/dev_commands.md
git commit -m "test: isolate postgres integration database"
```

### Task 2: Typed Raw Insert Results and Propagated Database Errors

**Files:**
- Modify: `db/raw_listings.py:1-54`
- Modify: `db/sqlite.py:12-38`
- Modify: `crawler/base_crawler.py:228-278`
- Modify: `cli/crawlers.py:1-240`
- Create: `tests/test_raw_insert_results.py`
- Modify: `tests/test_daily_crawl_limits.py:119-174`

**Interfaces:**
- Produces: `RawInsertResult(status: Literal["inserted", "duplicate"], raw_id: int | None)`
- Produces: `insert_raw_result(source, source_id, url, raw_data, crawl_run_id=None) -> RawInsertResult`
- Retains: `insert_raw(source: str, source_id: str | None, url: str, raw_data:
  dict, crawl_run_id: int | None = None) -> int | None` as a compatibility
  wrapper that propagates operational errors.

- [x] **Step 1: Write failing repository tests**

Use a UUID URL and delete it in `finally`:

```python
def test_insert_raw_result_distinguishes_insert_and_duplicate():
    unique_url = f"https://guland.vn/post/raw-result-{uuid.uuid4().hex}-901"
    try:
        first = insert_raw_result("guland", "901", unique_url, {"url": unique_url})
        second = insert_raw_result("guland", "901", unique_url, {"url": unique_url})
        assert first.status == "inserted"
        assert first.raw_id
        assert second == RawInsertResult(status="duplicate", raw_id=None)
    finally:
        with get_conn() as conn:
            conn.execute(
                "DELETE FROM raw_listings WHERE source='guland' AND url=?",
                (unique_url,),
            )


def test_insert_raw_result_propagates_database_failure(monkeypatch):
    @contextmanager
    def broken_context():
        raise RuntimeError("database unavailable")
        yield

    monkeypatch.setattr(raw_listings, "get_conn", broken_context)
    with pytest.raises(RuntimeError, match="database unavailable"):
        insert_raw_result("guland", "902", "https://guland.vn/post/x-902", {"url": "x"})
```

- [x] **Step 2: Verify RED**

Run:

```powershell
& $py -X utf8 -m pytest tests\test_raw_insert_results.py -q
```

Expected: import failure for `RawInsertResult`/`insert_raw_result`.

- [x] **Step 3: Implement one-query insert classification**

Use a parameterized PostgreSQL conflict clause:

```python
@dataclass(frozen=True)
class RawInsertResult:
    status: Literal["inserted", "duplicate"]
    raw_id: int | None


def insert_raw_result(
    source: str,
    source_id: str | None,
    url: str,
    raw_data: dict,
    crawl_run_id: int | None = None,
) -> RawInsertResult:
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO raw_listings
                (source, source_id, url, raw_json, crawl_run_id)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(source, url) DO NOTHING
            """,
            (source, source_id, url, json.dumps(raw_data, ensure_ascii=False), crawl_run_id),
        )
        if cur.lastrowid:
            return RawInsertResult("inserted", cur.lastrowid)
        return RawInsertResult("duplicate", None)
```

Do not catch `Exception` in this repository. Keep phone blacklist checks at caller boundaries where they can be reported as classified skips.

- [x] **Step 4: Route Facebook and BaseCrawler through the typed API**

Facebook branches on `result.status`; it refreshes images only for `duplicate`. `BaseCrawler.upsert_raw()` increments `new` only for `inserted`, increments `skipped` only for `duplicate`/validation/blacklist, and lets operational errors reach its target-level exception handling.

- [x] **Step 5: Verify GREEN and Facebook compatibility**

Run:

```powershell
& $py -X utf8 -m pytest tests\test_raw_insert_results.py tests\test_daily_crawl_limits.py tests\test_facebook_image_refresh.py -q
```

Expected: all pass; a simulated insert error is not counted as a duplicate.

- [x] **Step 6: Commit raw insert contracts**

```powershell
git add db/raw_listings.py db/sqlite.py crawler/base_crawler.py cli/crawlers.py tests/test_raw_insert_results.py tests/test_daily_crawl_limits.py
git commit -m "fix: distinguish raw duplicates from write failures"
```

### Task 3: Truthful Crawl Run and Target Statuses

**Files:**
- Modify: `db/crawl_runs.py:1-72`
- Modify: `db/schema.py:230-252`
- Modify: `crawler/base_crawler.py:147-218`
- Modify: `alerts/ops.py:30-70`
- Create: `tests/test_crawl_run_status.py`
- Modify: `tests/test_ops_alert.py`
- Modify: `tests/test_guland_crawler_stats.py`

**Interfaces:**
- Produces: `derive_crawl_status(stats: Mapping, fatal: bool = False) -> Literal["done", "partial", "error"]`
- Produces: `mark_url_error(run_id: int, target_url: str, error_msg: str) -> None`
- Base crawler stats retain `fetched`, `new`, `updated`, `skipped`, `errors`, and `error_details`.

- [x] **Step 1: Write failing status tests**

```python
@pytest.mark.parametrize(
    ("stats", "fatal", "expected"),
    [
        ({"fetched": 10, "errors": 0}, False, "done"),
        ({"fetched": 10, "errors": 1}, False, "partial"),
        ({"fetched": 0, "errors": 1}, True, "error"),
    ],
)
def test_derive_crawl_status(stats, fatal, expected):
    assert derive_crawl_status(stats, fatal=fatal) == expected


def test_ops_alert_marks_partial_unhealthy():
    unhealthy, msg = summarize_crawl_health([
        {"source": "guland", "status": "partial", "n_fetched": 40,
         "n_new": 2, "error_msg": "one ward failed"}
    ])
    assert unhealthy
    assert "PARTIAL" in msg
```

- [x] **Step 2: Verify RED**

Run:

```powershell
& $py -X utf8 -m pytest tests\test_crawl_run_status.py tests\test_ops_alert.py -q
```

Expected: missing helper and partial-alert assertion failure.

- [x] **Step 3: Implement status derivation and failed-target checkpointing**

Add:

```python
VALID_CRAWL_STATUSES = {"running", "done", "partial", "error"}


def derive_crawl_status(stats, *, fatal=False):
    if fatal:
        return "error"
    return "partial" if int(stats.get("errors", 0) or 0) > 0 else "done"
```

`mark_url_error()` stores `status='error'`, a bounded 500-character error, and
completion time in `crawl_run_progress`. Add
`crawl_run_progress.error_msg TEXT NOT NULL DEFAULT ''` idempotently in
`db/schema.py`; never store HTML or connection strings.

- [x] **Step 4: Make BaseCrawler finish exactly once**

Wrap Playwright import/launch/target loop/browser close in one `try/except/finally`:

- target failures call `_track_error()` and `mark_url_error()`;
- successful targets call `mark_url_done()`;
- recoverable target failures finish the run `partial`;
- setup/browser/database failures finish `error` and re-raise;
- `finish_crawl_run()` executes exactly once.

Log one bounded JSON counter object per target with URL, fetched, existing,
new, changed, invalid, and error counts.

- [x] **Step 5: Verify GREEN**

Run:

```powershell
& $py -X utf8 -m pytest tests\test_crawl_run_status.py tests\test_ops_alert.py tests\test_guland_crawler_stats.py tests\test_base_crawler_env.py -q
```

Expected: all pass; partial target failure is visible to health/alerts.

- [x] **Step 6: Commit crawl status handling**

```powershell
git add db/crawl_runs.py db/schema.py crawler/base_crawler.py alerts/ops.py tests/test_crawl_run_status.py tests/test_ops_alert.py tests/test_guland_crawler_stats.py
git commit -m "fix: report partial crawler failures"
```

### Task 4: PostgreSQL-Safe Crawl Health Queries

**Files:**
- Modify: `db/crawl_runs.py`
- Modify: `cli/queries.py:340-406`
- Modify: `cli/crawlers.py:482-506`
- Create: `tests/test_crawl_health.py`

**Interfaces:**
- Produces: `load_recent_crawl_runs(conn, limit: int) -> list[dict]`
- Produces: `summarize_recent_crawl_runs(conn, days: int = 7) -> list[dict]`
- Consumes: text-backed `crawl_runs.started_at`, explicitly cast to `TIMESTAMPTZ`.

- [x] **Step 1: Write a failing PostgreSQL health test**

Seed one `done` and one `partial` run with text timestamps, then call both repository functions:

```python
def test_weekly_health_casts_text_timestamps():
    area = f"health-test-{uuid.uuid4().hex}"
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO crawl_runs
                (source, area, status, n_fetched, n_new, error_msg, started_at)
            VALUES
                ('guland', ?, 'done', 10, 2, '', CURRENT_TIMESTAMP::text),
                ('guland', ?, 'partial', 8, 1, 'one target failed', CURRENT_TIMESTAMP::text)
            """,
            (area, area),
        )
        try:
            rows = summarize_recent_crawl_runs(conn, days=7)
            by_source = {row["source"]: row for row in rows}
            assert by_source["guland"]["partial_runs"] >= 1
            assert by_source["guland"]["runs_with_errors"] >= 1
        finally:
            conn.execute("DELETE FROM crawl_runs WHERE area=?", (area,))
```

- [x] **Step 2: Verify RED against the current query**

Run:

```powershell
& $py -X utf8 -m pytest tests\test_crawl_health.py -q
```

Expected: PostgreSQL type error or missing repository function.

- [x] **Step 3: Implement PostgreSQL timestamp queries**

Use:

```sql
WHERE NULLIF(started_at, '')::timestamptz
      >= CURRENT_TIMESTAMP - (? * INTERVAL '1 day')
```

Summary columns include total runs, total new, `partial_runs`, `error_runs`, and
`runs_with_errors`. `cli/queries.py` only formats repository results.

- [x] **Step 4: Reuse the same timestamp semantics in daily ops lookup**

Replace SQLite-style `datetime(started_at) >= datetime(?)` with:

```sql
NULLIF(started_at, '')::timestamptz >= ?::timestamptz
```

- [x] **Step 5: Verify health command and alert tests**

Run:

```powershell
& $py -X utf8 -m pytest tests\test_crawl_health.py tests\test_ops_alert.py tests\test_daily_crawl_limits.py -q
& $py -X utf8 radar.py crawl-health --limit 5
```

Expected: command exits 0 and weekly summary distinguishes partial/error runs.

- [x] **Step 6: Commit health repair**

```powershell
git add db/crawl_runs.py cli/queries.py cli/crawlers.py tests/test_crawl_health.py
git commit -m "fix: make crawl health postgres safe"
```

### Task 5: Reliability Plan Verification Gate

**Files:**
- Verify only; update this plan's checkboxes during execution.

**Interfaces:**
- Produces: a stable foundation for `2026-07-30-guland-source-reconciliation.md`.

- [ ] **Step 1: Compile touched Python**

```powershell
& $py -X utf8 -m py_compile db\connection.py db\raw_listings.py db\crawl_runs.py crawler\base_crawler.py cli\crawlers.py cli\queries.py alerts\ops.py
```

- [ ] **Step 2: Run the reliability suite**

```powershell
& $py -X utf8 -m pytest tests\test_postgres_connection.py tests\test_raw_insert_results.py tests\test_crawl_run_status.py tests\test_crawl_health.py tests\test_ops_alert.py tests\test_daily_crawl_limits.py tests\test_guland_crawler_stats.py -q
```

- [ ] **Step 3: Confirm no secret or unrelated diff**

```powershell
git diff --check
git status --short
git diff --cached -- . ':!*.log' ':!data/*'
```

Expected: no `.env`, database dump, log, raw backup, image asset, or unrelated user file is staged.

- [ ] **Step 4: Record the foundation commit**

```powershell
git add docs/superpowers/plans/2026-07-30-crawl-reliability-phase1.md
git commit -m "chore: verify crawl reliability foundation"
```
