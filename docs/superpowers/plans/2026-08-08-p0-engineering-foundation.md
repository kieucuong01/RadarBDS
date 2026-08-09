# P0 Engineering Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the documented local PostgreSQL runtime reproducible and idempotent, restore a green CI-safe baseline, and add a normal PR/main quality workflow with no production side effects.

**Architecture:** Keep the Windows bootstrap and preflight in focused PowerShell scripts, validate their contracts from Python tests, and use an ephemeral PostgreSQL 17 service in GitHub Actions. Repair the eight reproduced baseline failures according to current product behavior before making CI blocking.

**Tech Stack:** PowerShell 7/Windows PowerShell 5.1, Python 3.12, pytest 8.4.2, PostgreSQL 17, Node.js 24, GitHub Actions, pip-audit

## Global Constraints

- Local development on this machine uses portable PostgreSQL 17 at `127.0.0.1:15432`; PostgreSQL 18 at `5432` is a distinct optional instance.
- The development database is `radar_bds`; the test database is `radar_bds_test`; a test database name must contain `test`.
- Never print connection passwords, API keys, phone numbers, emails, source URLs, IP addresses, user-agents, or raw listing descriptions.
- Normal CI must not call production, live crawlers, deployment scripts, capacity workflows, or external application services.
- Preserve `.playwright-cli/` and all unrelated work.
- Python runtime floor is 3.12; CI Node major version is 24; CI PostgreSQL major version is 17.
- Capacity workflows remain separate and require their existing explicit production gate.

---

## File Structure

- Modify `scripts/local_postgres.ps1`: idempotent portable cluster/bootstrap owner.
- Create `scripts/dev_preflight.ps1`: read-only developer environment diagnostics and masked JSON/text output.
- Create `scripts/check_tracked_secrets.py`: high-confidence tracked-file scanner that emits rule/path/line only.
- Modify `requirements-dev.txt`: pin CI-only pytest and pip-audit dependencies.
- Create `.github/workflows/quality-gates.yml`: ordinary PR/main CI.
- Create `tests/test_local_dev_tooling.py`: PowerShell/bootstrap/preflight contracts.
- Create `tests/test_quality_workflow.py`: workflow, dependency, and secret-scanner contracts.
- Modify the eight currently failing test modules only where their fixtures/assertions are stale or unscoped.
- Modify `AGENTS.md`, `docs/architecture.md`, `docs/dev_commands.md`, and `.env.example`: reconcile current runtime and command truth.

### Task 1: Repair the eight reproduced baseline failures

**Files:**
- Modify: `tests/test_db_cleanup.py:222`
- Modify: `tests/test_digital_product_checkout.py:1772`
- Modify: `tests/test_thu_dau_mot_map_product_page.py:415`
- Modify: `tests/test_digital_product_order_schema.py:239`
- Modify: `tests/test_radar_ask_performance.py:177`
- Modify: `tests/test_radar_ask_retention.py:28-330`

**Interfaces:**
- Consumes: existing cleanup clock behavior, checkout form action `/ban-do-thu-dau-mot/checkout`, lead form action `/api/leads`, `RadarAskSettings`, and fixture-owned Radar Ask UUIDs.
- Produces: eight independently green regression tests without changing intended production behavior.

- [ ] **Step 1: Freeze the cleanup window in the test instead of using a date that ages**

Replace the fixed recent/old values with dates derived from a frozen `now` passed to cleanup, or patch the cleanup clock if the command already exposes one. The assertion must retain this shape:

```python
now = datetime(2026, 8, 8, 12, 0, 0)
old_at = (now - timedelta(days=91)).isoformat()
recent_at = (now - timedelta(days=89)).isoformat()
```

- [ ] **Step 2: Narrow digital-product assertions to the checkout form**

Use action-specific assertions so the valid SEO lead form remains present:

```python
assert html.count('action="/ban-do-thu-dau-mot/checkout"') == 1
assert html.count('<form class="map-product-checkout') == 1
assert 'name="amount"' not in html
```

For disabled sales:

```python
assert 'action="/ban-do-thu-dau-mot/checkout"' not in html
assert 'action="/api/leads"' in html
```

- [ ] **Step 3: Make the migration fake implement the current query contract**

Return a cursor-like object for `_table_exists()` while keeping executed SQL visible:

```python
class FakeResult:
    def fetchone(self):
        return None

class FakeConn:
    def execute(self, sql, params=None):
        self.executed.append(sql)
        return FakeResult()
```

- [ ] **Step 4: Diagnose the Radar Ask 503 before changing assertions**

Run:

```powershell
& $py -X utf8 -m pytest tests\test_radar_ask_performance.py::test_fast_request_has_zero_provider_calls_and_bounded_work -vv --showlocals
```

Inspect `response.get_json()` and the exception path. Preserve the intended `200` fast and `202` queued contracts. Install all route gates in `_client_for()` explicitly, including the same-site write gate and the feature/tier settings used by `routes/radar_ask_api.py`; do not accept `503` in the test.

- [ ] **Step 5: Scope Radar Ask retention counts to fixture-owned rows**

Record the created run/usage IDs and count only those IDs:

```python
markers = ",".join("?" for _ in retained_usage)
row = conn.execute(
    f"SELECT COUNT(*) AS count FROM radar_ask_usage_attempts WHERE usage_id IN ({markers})",
    retained_usage,
).fetchone()
assert row["count"] == 13
```

For tool/evidence cleanup, query by the deleted run ID rather than requiring the entire shared table to be empty.

- [ ] **Step 6: Run all eight tests and verify they pass**

```powershell
& $py -X utf8 -m pytest `
  tests\test_db_cleanup.py::DbCleanupTest::test_sold_listings_older_than_90d_deleted `
  tests\test_digital_product_checkout.py::test_sellable_product_page_uses_post_forms_without_client_price `
  tests\test_digital_product_order_schema.py::test_order_migrations_are_forward_only_and_postgres_idempotent `
  tests\test_radar_ask_performance.py::test_fast_request_has_zero_provider_calls_and_bounded_work `
  tests\test_radar_ask_performance.py::test_deep_submit_enqueues_without_inline_tool_or_provider_execution `
  tests\test_radar_ask_retention.py::test_content_cutoff_cascades_expired_terminal_history_and_preserves_active_content `
  tests\test_radar_ask_retention.py::test_dry_run_mutates_nothing_and_usage_keeps_13_month_buckets_but_purges_14th `
  tests\test_thu_dau_mot_map_product_page.py::test_product_page_is_indexable_but_checkout_is_disabled_without_sales_flag `
  -q
```

Expected: `8 passed`.

- [ ] **Step 7: Commit the baseline repairs**

```powershell
git add tests/test_db_cleanup.py tests/test_digital_product_checkout.py tests/test_digital_product_order_schema.py tests/test_radar_ask_performance.py tests/test_radar_ask_retention.py tests/test_thu_dau_mot_map_product_page.py
git commit -m "test: restore green PostgreSQL baseline"
```

### Task 2: Make portable PostgreSQL bootstrap idempotent

**Files:**
- Create: `tests/test_local_dev_tooling.py`
- Modify: `scripts/local_postgres.ps1`

**Interfaces:**
- Consumes: actions `start|stop|status`, default port `15432`, tracked portable binaries, `.local/postgres-data`.
- Produces: repeated `start` exit `0`, guaranteed `radar_bds` and `radar_bds_test`, bounded readiness wait.

- [ ] **Step 1: Write failing static and behavior-contract tests**

```python
def test_local_postgres_bootstrap_ensures_dev_and_test_databases():
    source = (ROOT / "scripts" / "local_postgres.ps1").read_text(encoding="utf-8")
    assert '@("radar_bds", "radar_bds_test")' in source
    assert "SELECT 1 FROM pg_database WHERE datname" in source
    assert "createdb.exe" in source

def test_local_postgres_start_checks_readiness_before_starting():
    source = (ROOT / "scripts" / "local_postgres.ps1").read_text(encoding="utf-8")
    assert source.index("pg_isready.exe") < source.index("pg_ctl.exe")
    assert "ReadyTimeoutSeconds" in source
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `& $py -X utf8 -m pytest tests\test_local_dev_tooling.py -q`

Expected: failures for missing database loop and readiness timeout.

- [ ] **Step 3: Implement idempotent bootstrap**

Use explicit helpers:

```powershell
function Test-PgReady {
    & (Join-Path $PgBin "pg_isready.exe") -h 127.0.0.1 -p $Port -U postgres *> $null
    return $LASTEXITCODE -eq 0
}

function Ensure-Database([string] $Name) {
    $exists = & (Join-Path $PgBin "psql.exe") -h 127.0.0.1 -p $Port -U postgres -d postgres -tAc `
        "SELECT 1 FROM pg_database WHERE datname='$Name'"
    if (($exists | Out-String).Trim() -ne "1") {
        & (Join-Path $PgBin "createdb.exe") -h 127.0.0.1 -p $Port -U postgres $Name
        if ($LASTEXITCODE -ne 0) { throw "Could not create local database $Name" }
    }
}
```

Validate database names against `^[a-z][a-z0-9_]{0,62}$` before interpolation. Start only when `Test-PgReady` is false, poll for at most `ReadyTimeoutSeconds`, then ensure both databases.

- [ ] **Step 4: Run tests and real repeated-start verification**

```powershell
& $py -X utf8 -m pytest tests\test_local_dev_tooling.py -q
.\scripts\local_postgres.ps1 start
.\scripts\local_postgres.ps1 start
.\scripts\local_postgres.ps1 status
```

Expected: tests pass; all three commands exit `0`.

- [ ] **Step 5: Commit bootstrap changes**

```powershell
git add scripts/local_postgres.ps1 tests/test_local_dev_tooling.py
git commit -m "fix: make local PostgreSQL bootstrap idempotent"
```

### Task 3: Add masked developer preflight

**Files:**
- Modify: `tests/test_local_dev_tooling.py`
- Create: `scripts/dev_preflight.ps1`

**Interfaces:**
- Consumes: `DATABASE_URL`, `RADAR_TEST_DATABASE_URL`, documented Python 3.12, Node 24, optional `-StartLocalPostgres`.
- Produces: text or JSON report with `ok`, `python`, `node`, `development_database`, `test_database`, `checks`, and safe exit codes.

- [ ] **Step 1: Write failing preflight contract tests**

```python
def test_preflight_masks_credentials_and_requires_distinct_test_database():
    source = (ROOT / "scripts" / "dev_preflight.ps1").read_text(encoding="utf-8")
    assert "System.UriBuilder" in source
    assert "RADAR_TEST_DATABASE_URL" in source
    assert "database name must contain test" in source
    safe_target = source[source.index("function Get-SafeDatabaseTarget"):source.index("function Test-DatabaseConnection")]
    assert "UserInfo" not in safe_target
    assert "Password" not in safe_target
    assert "AbsoluteUri" not in safe_target

def test_preflight_has_json_and_explicit_start_modes():
    source = (ROOT / "scripts" / "dev_preflight.ps1").read_text(encoding="utf-8")
    assert "[switch] $Json" in source
    assert "[switch] $StartLocalPostgres" in source
    assert "ConvertTo-Json" in source
```

- [ ] **Step 2: Run tests and verify RED**

Run: `& $py -X utf8 -m pytest tests\test_local_dev_tooling.py -q`

- [ ] **Step 3: Implement URL masking and checks**

The report database object must be created only from parsed safe fields:

```powershell
function Get-SafeDatabaseTarget([string] $Value) {
    $uri = [Uri]$Value
    $database = $uri.AbsolutePath.TrimStart('/')
    return [ordered]@{
        scheme = $uri.Scheme
        host = $uri.Host
        port = $uri.Port
        database = $database
    }
}
```

Use `psql -tAc "SELECT 1"` for both configured targets without echoing the URI. Exit `10` for configuration, `20` for runtime, and `30` for dependency failure. `-StartLocalPostgres` may invoke only `scripts/local_postgres.ps1 start` when the configured host/port are `127.0.0.1:15432`.

- [ ] **Step 4: Run tests and real JSON smoke**

```powershell
& $py -X utf8 -m pytest tests\test_local_dev_tooling.py -q
.\scripts\dev_preflight.ps1 -Json
```

Parse the JSON and verify it includes database names but no username, password, or full URI.

- [ ] **Step 5: Commit preflight**

```powershell
git add scripts/dev_preflight.ps1 tests/test_local_dev_tooling.py
git commit -m "feat: add reproducible developer preflight"
```

### Task 4: Add repository-owned dependency and secret gates

**Files:**
- Modify: `requirements-dev.txt`
- Create: `scripts/check_tracked_secrets.py`
- Create: `tests/test_quality_workflow.py`

**Interfaces:**
- Consumes: paths returned by `git ls-files`, high-confidence token formats.
- Produces: `scan_paths(paths: Iterable[Path]) -> list[Finding]`; CLI exit `1` only for findings and prints `path:line:rule` without matched values.

- [ ] **Step 1: Write failing scanner tests**

```python
def test_scanner_reports_rule_and_location_without_secret(tmp_path):
    target = tmp_path / "leak.txt"
    target.write_text("token=ghp_" + "a" * 36, encoding="utf-8")
    findings = scan_paths([target])
    assert findings[0].rule == "github_pat"
    rendered = render_findings(findings)
    assert "ghp_" not in rendered
    assert "leak.txt:1:github_pat" in rendered

def test_scanner_ignores_documented_placeholders(tmp_path):
    target = tmp_path / ".env.example"
    target.write_text("DATABASE_URL=postgresql://user:<password>@localhost/db", encoding="utf-8")
    assert scan_paths([target]) == []
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `& $py -X utf8 -m pytest tests\test_quality_workflow.py -q`

- [ ] **Step 3: Implement high-confidence scanning**

Use a frozen dataclass and named regular expressions for PEM private-key headers, GitHub classic/fine-grained tokens, AWS access-key IDs, Slack tokens, and Google API keys. Do not add a generic `secret=` matcher that would flag test fixtures. Decode text with UTF-8 replacement, skip files containing NUL bytes, and never retain the matched text in `Finding`.

- [ ] **Step 4: Pin and verify development dependencies**

Add `pip-audit` to `requirements-dev.txt` beside the existing pytest pin. Install both requirement files, run `python -m pip check`, then run `python -m pip_audit -r requirements.txt`. Any advisory must be resolved by upgrading the affected direct pin or documented with an exact advisory ID and expiry; do not use a blanket ignore.

- [ ] **Step 5: Run scanner tests and scan tracked files**

```powershell
& $py -X utf8 -m pytest tests\test_quality_workflow.py -q
& $py -X utf8 scripts\check_tracked_secrets.py
```

Expected: tests pass and tracked scan exits `0`.

- [ ] **Step 6: Commit dependency and secret gates**

```powershell
git add requirements-dev.txt scripts/check_tracked_secrets.py tests/test_quality_workflow.py
git commit -m "build: add dependency and tracked-secret gates"
```

### Task 5: Add normal PR/main CI

**Files:**
- Modify: `tests/test_quality_workflow.py`
- Create: `.github/workflows/quality-gates.yml`

**Interfaces:**
- Consumes: `requirements.txt`, `requirements-dev.txt`, PostgreSQL test guard, all `tests/js/*.cjs` and `tests/js/test_*.js` files.
- Produces: one ordinary quality workflow on `pull_request` and pushes to `main`.

- [ ] **Step 1: Write failing workflow contract tests**

```python
def test_quality_workflow_is_pr_main_only_and_production_safe():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "pull_request:" in text
    assert "branches: [main]" in text
    assert "postgres:17" in text
    assert "python-version: '3.12'" in text
    assert "node-version: '24'" in text
    assert "deploy_production" not in text
    assert "radarbds.vn" not in text
    assert "RADAR_TEST_DATABASE_URL" in text
```

- [ ] **Step 2: Run workflow tests and verify RED**

Run: `& $py -X utf8 -m pytest tests\test_quality_workflow.py -q`

- [ ] **Step 3: Implement the workflow**

Use `permissions: contents: read`, branch-scoped concurrency with `cancel-in-progress: true`, a healthy PostgreSQL 17 service, Python/Node setup, and these gates in order:

```yaml
- run: python -m pip install -r requirements.txt -r requirements-dev.txt
- run: python -m pip check
- run: python -m pip_audit -r requirements.txt
- run: python scripts/check_tracked_secrets.py
- run: python -m py_compile app.py radar.py db/connection.py db/schema.py services/admin_growth.py
- run: python -c "from db.schema import init_schema; init_schema()"
- run: python -m pytest tests --ignore=tests/test_guland.py --ignore=tests/sanity_test.py
- run: node --test tests/js/*.cjs tests/js/test_*.js
```

Set both database environment variables to the dedicated CI test database; do not define production credentials.

- [ ] **Step 4: Run tests and validate YAML shape**

Run `tests/test_quality_workflow.py`, parse the workflow with Python YAML support already available through project dependencies if present, and run all commands locally with the portable test database.

- [ ] **Step 5: Commit CI workflow**

```powershell
git add .github/workflows/quality-gates.yml tests/test_quality_workflow.py
git commit -m "ci: add normal PostgreSQL quality gates"
```

### Task 6: Reconcile runtime documentation and run the P0 gate

**Files:**
- Modify: `AGENTS.md:65-76`
- Modify: `docs/architecture.md:20-27,102-116`
- Modify: `docs/dev_commands.md:14-55,632-638`
- Modify: `.env.example:1-20`
- Modify: `tests/test_local_dev_tooling.py`

**Interfaces:**
- Consumes: verified local bootstrap/preflight behavior and current Cloudflare production evidence in `docs/operations.md`.
- Produces: one non-contradictory current-state contract and exact local/CI commands.

- [ ] **Step 1: Write a failing documentation consistency test**

```python
def test_runtime_docs_agree_on_local_postgres_and_cloudflare():
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    architecture = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
    commands = (ROOT / "docs" / "dev_commands.md").read_text(encoding="utf-8")
    for text in (agents, architecture, commands):
        assert "127.0.0.1:15432" in text
    assert "Cloudflare is now the active public edge" in agents
    assert "normally uses installed PostgreSQL 18" not in architecture
```

- [ ] **Step 2: Run the test and verify RED**

Run: `& $py -X utf8 -m pytest tests\test_local_dev_tooling.py -q`

- [ ] **Step 3: Update current-state docs without rewriting history**

State that Cloudflare is active, cite `docs/operations.md` as the detailed truth, preserve the proven 1,000 mixed/5,000 common-key boundary, and distinguish port `5432`. Document:

```powershell
.\scripts\local_postgres.ps1 start
.\scripts\dev_preflight.ps1
.\scripts\dev_preflight.ps1 -Json
& $py -X utf8 -m pytest tests --ignore=tests\test_guland.py --ignore=tests\sanity_test.py
node --test tests/js/*.cjs tests/js/test_*.js
```

- [ ] **Step 4: Run focused and full P0 verification**

```powershell
& $py -X utf8 -m pytest tests\test_local_dev_tooling.py tests\test_quality_workflow.py -q
& $py -X utf8 -m pytest tests --ignore=tests\test_guland.py --ignore=tests\sanity_test.py
node --test tests/js/*.cjs tests/js/test_*.js
git diff --check
```

Expected: all commands exit `0`; no production request is made.

- [ ] **Step 5: Commit documentation and P0 completion evidence**

```powershell
git add AGENTS.md docs/architecture.md docs/dev_commands.md .env.example tests/test_local_dev_tooling.py
git commit -m "docs: align local and production runtime truth"
```
