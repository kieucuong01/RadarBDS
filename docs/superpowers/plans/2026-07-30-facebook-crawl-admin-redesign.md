# Facebook Crawl Admin Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `/admin/facebook-crawl` task-first and understandable while replacing process-local crawl jobs with PostgreSQL-backed, worker-safe job state.

**Architecture:** Store async admin job state behind a focused repository/service boundary in PostgreSQL, while retaining local daemon threads only as best-effort runners and retaining the existing runtime advisory locks around real crawl/reprocess work. Split the Facebook Crawl admin into overview, broker management, and run/history views that load only their own API payloads; keep `data/facebook_profiles.json` canonical but protect writes with a normalized revision and a PostgreSQL advisory transaction lock.

**Tech Stack:** PostgreSQL 18, Flask 3.1, Python 3.12, Jinja, vanilla JavaScript, CSS, pytest 8.4, Node syntax/contract tests, in-app Browser plugin.

## Global Constraints

- Implement the approved specification at `docs/superpowers/specs/2026-07-30-facebook-crawl-admin-redesign-design.md`.
- Work only in the isolated `codex/facebook-crawl-admin-redesign` worktree based on `origin/main`.
- Facebook remains the primary source; Guland remains secondary; BatDongSan remains disabled.
- Do not add external LLM verification or enrichment to crawl or reprocess.
- `data/facebook_profiles.json` remains the canonical broker configuration file.
- Preserve the existing Admin-only authorization boundary and never return Apify token values or raw secrets.
- Preserve the existing public job response fields: `id`, `status`, `stage`, `mode`, `profile_url`, `broker_name`, `limit`, `days`, `download_images`, `progress_pct`, `progress_label`, `stats`, `error`, `logs`, `started_at`, and `finished_at`.
- PostgreSQL is canonical for shared async job state; process memory is not an authority.
- At most one `queued` or `running` admin crawl/maintenance job may exist.
- Heartbeat active jobs every 15 seconds; reconcile jobs older than 2 minutes as failed with `Job dừng vì tiến trình máy chủ không còn hoạt động.`
- Persist at most 200 log entries per job and expose only a safe, bounded error string.
- Keep the compatibility `/admin/api/facebook-crawl/config` endpoint for one release; the new UI must not call it.
- Initial overview rendering must not fetch broker rows or duplicate comparisons.
- Duplicate pages contain at most 20 rows in the UI and API `limit` is capped at 50.
- Use the query views `overview`, `brokers`, and `run`; no view has more than one primary action.
- A broker-row “Chạy” action only preselects the run form and never starts a crawl.
- Any save conflict caused by a stale profile revision returns HTTP 409 and retains the client draft.
- No React, Celery, Redis, resumable queue, cancel control, scheduler rewrite, parser rewrite, dedup rewrite, valuation rewrite, bulk broker editing, or redesign of other admin panels is in scope.
- Every production-code change must have a witnessed RED/GREEN test cycle.
- Do not push or deploy without separate user authorization.

---

## File Map

| File | Responsibility |
|---|---|
| `db/schema.py` | Idempotent `admin_jobs` table, checks, indexes, and partial unique active-job index |
| `db/admin_jobs.py` | Parameterized repository for enqueue, read, update, heartbeat, stale reconciliation, and bounded logs |
| `services/admin_jobs.py` | Job payload validation, safe serialization, runner state transitions, and heartbeat loop |
| `services/admin_quality.py` | Canonical Facebook URL/profile normalization, profile revision, due metadata, overview shaping, and paginated duplicate shaping |
| `app.py` | Thin authenticated route handlers and existing runner adapters that write through the job service |
| `routes/admin_api.py` | Registers overview, profiles, duplicates, run, maintenance, tokens, and jobs endpoints |
| `templates/admin_control_room.html` | Task-first three-view Facebook Crawl markup |
| `static/js/admin/facebook-crawl.js` | Isolated view routing, lazy fetches, profile draft state, run confirmation, job polling, and maintenance confirmation |
| `static/js/admin.js` | Loads/initializes the focused module and removes legacy Facebook Crawl logic |
| `static/css/admin.css` | Focused task-view, table/drawer, status, history, and responsive styles |
| `tests/test_admin_jobs.py` | Repository/service/schema concurrency, stale, persistence, bounded log, and safe-error contracts |
| `tests/test_facebook_crawl_admin_api.py` | Overview, profile revision, URL normalization, lazy duplicate paging, run/history, and compatibility API contracts |
| `tests/js/test_facebook_crawl_admin.js` | Pure client state/view/draft/confirmation behavior contracts |
| `tests/test_admin_control_room.py` | Existing endpoint/runner and admin page regressions |
| `tests/test_admin_growth_ui.py` | Template, CSS, module asset, copy, and responsive structure contracts |

---

### Task 1: PostgreSQL Admin Job Schema And Repository

**Files:**
- Modify: `db/schema.py` beside other operational tables and `_run_migrations`
- Create: `db/admin_jobs.py`
- Create: `tests/test_admin_jobs.py`
- Modify: `tests/test_schema_init_permissions.py`

**Interfaces:**
- Produces: `create_admin_job(job: dict, *, conn_factory=get_conn, now=None) -> dict`
- Produces: `get_admin_job(job_id: str, *, conn_factory=get_conn) -> dict | None`
- Produces: `list_admin_jobs(limit: int = 20, *, conn_factory=get_conn) -> list[dict]`
- Produces: `get_active_admin_job(*, conn_factory=get_conn) -> dict | None`
- Produces: `update_admin_job(job_id: str, changes: dict, *, conn_factory=get_conn) -> dict`
- Produces: `append_admin_job_log(job_id: str, message: str, *, conn_factory=get_conn, now=None) -> dict`
- Produces: `heartbeat_admin_job(job_id: str, *, conn_factory=get_conn, now=None) -> None`
- Produces: `reconcile_stale_admin_jobs(*, conn_factory=get_conn, now=None, stale_after_seconds=120) -> int`
- Consumed by: Task 2 service and Task 4 routes.

- [ ] **Step 1: Write failing schema and repository tests**

Add tests that create two independent repository calls against the same test database and assert:

```python
created = create_admin_job({
    "id": "job-a",
    "kind": "facebook_crawl",
    "status": "queued",
    "mode": "daily",
    "profile_url": "https://www.facebook.com/broker-a",
    "broker_name": "Broker A",
    "limit": 30,
    "days": 7,
    "download_images": False,
    "created_by": "admin:test",
})
assert get_admin_job("job-a")["id"] == "job-a"
assert list_admin_jobs(limit=20)[0]["id"] == "job-a"
assert get_active_admin_job()["id"] == "job-a"
```

Start two threads behind a barrier and assert exactly one concurrent `create_admin_job` succeeds while the other raises `AdminJobAlreadyActive`. Add tests proving `append_admin_job_log` retains the newest 200 entries, `heartbeat_admin_job` updates `heartbeat_at`, `reconcile_stale_admin_jobs` changes only stale active rows to `failed`, and completed jobs survive a fresh repository call.

- [ ] **Step 2: Run RED**

```powershell
& $py -X utf8 -m pytest tests\test_admin_jobs.py tests\test_schema_init_permissions.py -q
```

Expected: import failure for `db.admin_jobs` and missing `admin_jobs` schema assertions.

- [ ] **Step 3: Add the idempotent schema**

Add `admin_jobs` with:

```sql
CREATE TABLE IF NOT EXISTS admin_jobs (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN (
        'facebook_crawl', 'crawl_maintenance',
        'missing_image_backfill', 'source_retry'
    )),
    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'succeeded', 'failed')),
    stage TEXT NOT NULL DEFAULT 'queued',
    mode TEXT NOT NULL DEFAULT '',
    profile_url TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    broker_name TEXT NOT NULL DEFAULT '',
    item_limit INTEGER,
    days INTEGER,
    download_images BOOLEAN NOT NULL DEFAULT FALSE,
    maintenance_action TEXT NOT NULL DEFAULT '',
    progress_pct INTEGER NOT NULL DEFAULT 0 CHECK (progress_pct BETWEEN 0 AND 100),
    progress_label TEXT NOT NULL DEFAULT '',
    stats JSONB NOT NULL DEFAULT '{}'::jsonb,
    logs JSONB NOT NULL DEFAULT '[]'::jsonb,
    error TEXT,
    context JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    heartbeat_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_admin_jobs_one_active
    ON admin_jobs ((1))
    WHERE status IN ('queued', 'running');
CREATE INDEX IF NOT EXISTS idx_admin_jobs_recent
    ON admin_jobs(created_at DESC, id DESC);
```

Create `_migrate_admin_jobs(conn)` and call it from `_run_migrations` plus the limited-DDL recovery path.

- [ ] **Step 4: Implement repository transactions**

Use only parameterized statements. In `create_admin_job`, open one transaction, execute `SELECT pg_advisory_xact_lock(hashtext('radar-admin-jobs-active'))`, reconcile stale active rows, query an active row, then insert or raise `AdminJobAlreadyActive(active_job)`. Map JSONB/timestamps into the public Python dictionary without leaking connection objects.

- [ ] **Step 5: Run GREEN**

```powershell
& $py -X utf8 -m pytest tests\test_admin_jobs.py tests\test_schema_init_permissions.py -q
& $py -X utf8 -m py_compile db\admin_jobs.py db\schema.py
```

- [ ] **Step 6: Commit**

```powershell
git add -- db/schema.py db/admin_jobs.py tests/test_admin_jobs.py tests/test_schema_init_permissions.py
git commit -m "feat: persist worker-safe admin jobs"
```

---

### Task 2: Shared Job Service And Existing Runner Migration

**Files:**
- Create: `services/admin_jobs.py`
- Modify: `app.py` around Facebook Crawl globals, helpers, and four admin job runners
- Modify: `tests/test_admin_jobs.py`
- Modify: `tests/test_admin_control_room.py`

**Interfaces:**
- Consumes: Task 1 repository functions.
- Produces: `public_admin_job(job: dict | None) -> dict | None`
- Produces: `enqueue_admin_job(job: dict, target: Callable[[str], None], *, repository=db.admin_jobs) -> dict`
- Produces: `AdminJobReporter(job_id, repository=db.admin_jobs)` with `start`, `progress`, `log`, `succeed`, `fail`, `heartbeat`, and `stop_heartbeat`
- Public runner fields remain compatible with `_public_crawl_job`.

- [ ] **Step 1: Write failing service and runner tests**

Assert two service instances see the same active job, a fake runner receives only the persisted job ID after transaction commit, and:

```python
reporter = AdminJobReporter("job-a", repository=fake_repository)
reporter.start("crawl", "Đang gọi Apify")
reporter.progress(35, "crawl", "Đã lấy dữ liệu từ Facebook")
reporter.log("fetched=12 imported=3")
reporter.succeed({"crawl": {"fetched": 12}})
assert public_admin_job(fake_repository.get("job-a"))["status"] == "succeeded"
```

Add a failing runner regression that no longer mutates `FACEBOOK_CRAWL_JOBS`, retains the existing `_facebook_crawl_to_raw` and targeted `raw_ids` behavior, and redacts an exception containing `token=secret-value` to bounded generic error copy.

- [ ] **Step 2: Run RED**

```powershell
& $py -X utf8 -m pytest tests\test_admin_jobs.py tests\test_admin_control_room.py -k "admin_job or crawl_reprocesses_only_refreshed_raw_ids" -q
```

- [ ] **Step 3: Implement service and heartbeat**

`AdminJobReporter.start` sets `status=running`, `started_at`, `heartbeat_at`, and initial progress. Start a daemon heartbeat thread using `Event.wait(15)`; stop it before every terminal write. `log` truncates each message to 1,000 characters and delegates bounded history to the repository. `fail` logs the exception server-side but stores only `Tác vụ thất bại. Xem log máy chủ để kiểm tra chi tiết.` unless the caller provides one of the approved operational messages.

- [ ] **Step 4: Migrate all admin runners**

Remove `FACEBOOK_CRAWL_JOBS`, `FACEBOOK_CRAWL_JOB_ORDER`, and `FACEBOOK_CRAWL_LOCK` as authorities. Fetch job context from PostgreSQL at runner start; replace dictionary mutation with reporter methods. Preserve the runtime `crawl-facebook`, reprocess, image download, and source retry advisory locks already used by the underlying workflows.

- [ ] **Step 5: Run GREEN**

```powershell
& $py -X utf8 -m pytest tests\test_admin_jobs.py tests\test_admin_control_room.py -k "facebook_crawl or admin_job or crawl_reprocesses_only_refreshed_raw_ids" -q
& $py -X utf8 -m py_compile services\admin_jobs.py app.py
```

- [ ] **Step 6: Commit**

```powershell
git add -- services/admin_jobs.py app.py tests/test_admin_jobs.py tests/test_admin_control_room.py
git commit -m "refactor: run admin crawl jobs through PostgreSQL"
```

---

### Task 3: Profile Revisions, Due Metadata, Overview, And Duplicate Paging

**Files:**
- Modify: `services/admin_quality.py`
- Create: `tests/test_facebook_crawl_admin_api.py`
- Modify: `tests/test_facebook_broker_governance.py`

**Interfaces:**
- Produces: `normalize_facebook_profile_url(value: object) -> str`
- Produces: `normalize_facebook_profiles(profiles: object) -> list[dict]`
- Produces: `facebook_profile_revision(profiles: list[dict]) -> str`
- Produces: `facebook_profile_due_metadata(profile: dict, stat: dict, today=None) -> dict`
- Produces: `facebook_crawl_overview(*, ...) -> dict`
- Produces: `paginate_facebook_duplicate_analysis(analysis: dict, *, actionable=True, city="", limit=20, offset=0) -> dict`
- Consumed by: Task 4 APIs and Task 5 UI.

- [ ] **Step 1: Write failing pure-service tests**

Prove URL canonicalization converts `facebook.com/name/`, `https://m.facebook.com/name?ref=x`, and `https://www.facebook.com/name/posts/123` to the configured profile root where valid; rejects non-HTTPS/non-Facebook hosts; deduplicates canonical equivalents; and produces a stable SHA-256 revision independent of JSON key order.

Freeze `today` and assert `facebook_profile_due_metadata` reuses `crawl_every_days` plus latest crawl date to return:

```python
{"due_today": True, "next_due_date": "2026-07-30"}
```

Assert duplicate paging defaults to only `recommended_crawl_every_days in {3, 7}`, filters city before pagination, returns `total`, `actionable`, `filtered`, and at most 20 `items`.

- [ ] **Step 2: Run RED**

```powershell
& $py -X utf8 -m pytest tests\test_facebook_crawl_admin_api.py tests\test_facebook_broker_governance.py -q
```

- [ ] **Step 3: Implement normalization and revision**

Normalize hostname to `www.facebook.com`, remove query/fragment/trailing slash, retain only the profile identifier segment, reject reserved non-profile paths, then sort normalized profile dictionaries by canonical URL before hashing compact UTF-8 JSON with SHA-256.

- [ ] **Step 4: Implement focused read models**

`facebook_crawl_overview` returns only timer/next run, last Facebook run, latest completed batch, active job, problem-only operations flags, and token quota summary. It must not call `facebook_profile_stats` or `facebook_profile_duplicate_analysis`. Duplicate pagination shapes the existing cross-city-guarded analysis without changing its comparison logic.

- [ ] **Step 5: Run GREEN**

```powershell
& $py -X utf8 -m pytest tests\test_facebook_crawl_admin_api.py tests\test_facebook_broker_governance.py -q
& $py -X utf8 -m py_compile services\admin_quality.py
```

- [ ] **Step 6: Commit**

```powershell
git add -- services/admin_quality.py tests/test_facebook_crawl_admin_api.py tests/test_facebook_broker_governance.py
git commit -m "feat: shape focused Facebook Crawl admin data"
```

---

### Task 4: Focused Admin APIs And Conflict-Safe Profile Writes

**Files:**
- Modify: `routes/admin_api.py`
- Modify: `app.py` around Facebook Crawl admin endpoints
- Modify: `tests/test_facebook_crawl_admin_api.py`
- Modify: `tests/test_admin_control_room.py`

**Interfaces:**
- Adds: `GET /admin/api/facebook-crawl/overview`
- Adds: `GET|POST /admin/api/facebook-crawl/profiles`
- Adds: `GET /admin/api/facebook-crawl/duplicates`
- Retains: `GET /admin/api/facebook-crawl/config`
- Retains: `POST /admin/api/facebook-crawl/run`
- Retains: `POST /admin/api/facebook-crawl/maintenance`
- Retains: token and job endpoints.

- [ ] **Step 1: Write failing API tests**

Assert:

- Overview returns the four summary cards, active problems, and active job without invoking patched expensive profile/duplicate loaders.
- Profiles GET returns `profiles` plus `revision`; each row has stats, `due_today`, and `next_due_date`.
- Profiles POST requires JSON object `{profiles, revision}`, canonicalizes URLs, and returns a new revision.
- A second client saving an old revision receives 409 `{error: "profile_revision_conflict", revision, profiles}` and does not overwrite the first save.
- Duplicates validates `actionable=0|1`, clamps `limit` to 50, validates nonnegative `offset`, and returns the paging contract.
- Jobs list reconciles stale rows and returns the newest 20 persisted jobs.
- Run and maintenance return the existing 409 active-job payload when another Gunicorn worker already enqueued one.
- Legacy config still returns its existing fields.

- [ ] **Step 2: Run RED**

```powershell
& $py -X utf8 -m pytest tests\test_facebook_crawl_admin_api.py tests\test_admin_control_room.py -k "facebook_crawl" -q
```

- [ ] **Step 3: Implement revision-locked profile save**

Acquire `pg_advisory_xact_lock(hashtext('radar-facebook-profile-config'))` using `get_conn`, reread and normalize the file under that lock, compare its revision, and return 409 on mismatch. For a valid save, write UTF-8 JSON to a sibling temporary file, flush and close it, atomically replace the canonical path with `os.replace`, then clear only Facebook Crawl admin caches.

- [ ] **Step 4: Implement thin endpoint handlers**

Validate query/body values before service calls. Use `db.admin_jobs.create_admin_job` for run/maintenance; commit before starting the daemon thread. Return `public_admin_job` and never serialize the internal exception, creator identity, context JSON, or token values.

- [ ] **Step 5: Run GREEN and security regression**

```powershell
& $py -X utf8 -m pytest tests\test_facebook_crawl_admin_api.py tests\test_admin_control_room.py tests\test_security_hardening.py -k "facebook_crawl or admin" -q
& $py -X utf8 -m py_compile routes\admin_api.py app.py
```

- [ ] **Step 6: Commit**

```powershell
git add -- routes/admin_api.py app.py tests/test_facebook_crawl_admin_api.py tests/test_admin_control_room.py
git commit -m "feat: add focused Facebook Crawl admin APIs"
```

---

### Task 5: Task-First Template And Client State Module

**Files:**
- Create: `static/js/admin/facebook-crawl.js`
- Modify: `static/js/admin.js`
- Modify: `templates/admin_control_room.html`
- Create: `tests/js/test_facebook_crawl_admin.js`
- Modify: `tests/test_admin_growth_ui.py`
- Modify: `tests/test_admin_control_room.py`

**Interfaces:**
- Produces: `window.RadarFacebookCrawlAdmin.create({root, fetchJSON, confirm, location, beforeUnloadTarget})`
- Pure exports for tests: `normalizeView`, `normalizedProfilesHash`, `isDraftDirty`, `buildRunPreview`, `buildMaintenancePreview`, `nextDuplicateOffset`
- Consumes the Task 4 APIs only.

- [ ] **Step 1: Write failing Node/template tests**

Node tests assert:

```javascript
assert.equal(api.normalizeView('unknown'), 'overview');
assert.equal(api.normalizeView('brokers'), 'brokers');
assert.equal(api.isDraftDirty(baseline, structuredClone(baseline)), false);
assert.equal(api.isDraftDirty(baseline, changed), true);
assert.match(api.buildRunPreview({mode: 'first', limit: 900}), /900/);
```

Use fake `fetchJSON` calls to prove initial overview fetches only `/overview`, entering brokers fetches `/profiles`, actionable duplicates load only after profiles, entering run fetches `/jobs`, broker “Chạy” changes to `?view=run` and preselects without POST, and a 409 save keeps the draft plus conflict state.

Template tests assert three view tabs, one visible primary action per view, an edit drawer, an unsaved badge, a run preview, persisted job history, and collapsed advanced maintenance. Assert the template loads `static/js/admin/facebook-crawl.js` with the asset-version helper.

- [ ] **Step 2: Run RED**

```powershell
node tests\js\test_facebook_crawl_admin.js
& $py -X utf8 -m pytest tests\test_admin_growth_ui.py tests\test_admin_control_room.py -k "facebook_crawl or crawl_panel" -q
```

- [ ] **Step 3: Implement view routing and lazy loading**

Read/write `view` through `URLSearchParams` and `history.replaceState`. Cache overview responses for 10 seconds. Render explicit loading, empty, failure, and healthy states with Vietnamese copy. Keep DOM writes to dynamic user/config values on `textContent`; use attribute setters only after URL validation.

- [ ] **Step 4: Implement profile draft lifecycle**

Clone the GET baseline, compute a normalized client hash, show `Chưa lưu` only when dirty, and enable the sole `Lưu thay đổi` primary action. Confirm before switching view, reloading, or refreshing data while dirty. Failed or 409 saves retain draft values; 409 renders `Dữ liệu đã thay đổi ở nơi khác`, offers reload, and focuses the conflict banner.

- [ ] **Step 5: Implement run/history and maintenance confirmation**

Generate a Vietnamese preview containing broker/mode/limit/date range/image choice. The primary action first opens confirmation; only confirm sends POST. Poll the persisted active job; append/update the newest 20 rows. Maintenance remains collapsed and its confirmation names the exact action and affected scope.

- [ ] **Step 6: Run GREEN**

```powershell
node tests\js\test_facebook_crawl_admin.js
node --check static\js\admin\facebook-crawl.js
node --check static\js\admin.js
& $py -X utf8 -m pytest tests\test_admin_growth_ui.py tests\test_admin_control_room.py -k "facebook_crawl or crawl_panel" -q
```

- [ ] **Step 7: Commit**

```powershell
git add -- static/js/admin/facebook-crawl.js static/js/admin.js templates/admin_control_room.html tests/js/test_facebook_crawl_admin.js tests/test_admin_growth_ui.py tests/test_admin_control_room.py
git commit -m "feat: add task-first Facebook Crawl admin views"
```

---

### Task 6: Broker Table, Lazy Duplicate Actions, And Responsive Styling

**Files:**
- Modify: `static/js/admin/facebook-crawl.js`
- Modify: `static/css/admin.css`
- Modify: `tests/js/test_facebook_crawl_admin.js`
- Modify: `tests/test_admin_growth_ui.py`

**Interfaces:**
- Broker filters: `search`, `city`, `active`, `cadence`, `due`, `quality`
- Duplicate API paging: `actionable`, `city`, `limit=20`, `offset`
- Draft cadence action: duplicate recommendation updates the in-memory profile only.

- [ ] **Step 1: Extend failing client and CSS contracts**

Assert all six broker filters compose without refetching, editing happens in one drawer, close/discard behavior is explicit, and duplicate recommendations apply only to the draft. Assert initial duplicate render is at most 20; `Xem toàn bộ phân tích` switches `actionable=0`; `Xem thêm` advances offset by returned item count.

CSS/template contracts require compact desktop columns, visible focus states, 44px touch targets, status conveyed by text plus color, a mobile card layout below 760px, and no horizontal document overflow selectors.

- [ ] **Step 2: Run RED**

```powershell
node tests\js\test_facebook_crawl_admin.js
& $py -X utf8 -m pytest tests\test_admin_growth_ui.py -q
```

- [ ] **Step 3: Implement broker management**

Render columns for broker/city, enabled, next due, quota/cadence, quality, last crawl, and one menu. Drawer fields are name, canonical URL, city, active, daily limit, range days, and cadence. The row run action closes the menu, switches to run, and fills the profile selector without dispatching a request.

- [ ] **Step 4: Implement duplicate summary and paging**

Show counts first. Render only actionable rows initially and no more than 20. Applying a recommendation updates the matching profile `crawl_every_days`, marks the draft dirty, and leaves persistence to the one broker-view save action.

- [ ] **Step 5: Run GREEN**

```powershell
node tests\js\test_facebook_crawl_admin.js
node --check static\js\admin\facebook-crawl.js
& $py -X utf8 -m pytest tests\test_admin_growth_ui.py -q
git diff --check
```

- [ ] **Step 6: Commit**

```powershell
git add -- static/js/admin/facebook-crawl.js static/css/admin.css tests/js/test_facebook_crawl_admin.js tests/test_admin_growth_ui.py
git commit -m "feat: simplify broker and duplicate management"
```

---

### Task 7: Integrated Regression And Performance Contracts

**Files:**
- Modify only files required by defects found in verification
- Modify: `docs/dev_commands.md` only if the new focused commands are otherwise undiscoverable

**Interfaces:**
- Verifies Tasks 1–6 together.

- [ ] **Step 1: Run focused backend suite**

```powershell
& $py -X utf8 -m pytest tests\test_admin_jobs.py tests\test_facebook_crawl_admin_api.py tests\test_facebook_broker_governance.py tests\test_admin_control_room.py tests\test_admin_growth_ui.py tests\test_security_hardening.py -q
```

- [ ] **Step 2: Run frontend and syntax checks**

```powershell
node tests\js\test_facebook_crawl_admin.js
node --check static\js\admin\facebook-crawl.js
node --check static\js\admin.js
& $py -X utf8 -m py_compile db\schema.py db\admin_jobs.py services\admin_jobs.py services\admin_quality.py routes\admin_api.py app.py
git diff --check
```

- [ ] **Step 3: Verify focused performance contracts**

Patch/spies must prove:

- `/overview` never calls `facebook_profile_stats` or duplicate analysis.
- Initial browser overview makes no profiles/duplicates request.
- Profiles performs one bounded stats query and no duplicate query.
- Duplicate responses never exceed requested/capped size.
- The client cache suppresses a second overview request inside 10 seconds.

Record local response timings for overview and profiles against representative local data. Treat the specification’s `<500ms` overview and `<2.5s` profiles values as targets; investigate query count/payload regressions before changing thresholds.

- [ ] **Step 4: Fix defects test-first**

For each defect, add or strengthen the smallest failing test, witness RED, modify only the owning file, rerun GREEN, and then repeat the integrated suite.

- [ ] **Step 5: Review repository scope**

```powershell
git status --short
git diff --stat origin/main...HEAD
git diff --name-only origin/main...HEAD
git log --oneline origin/main..HEAD
```

Confirm no `.env`, runtime data, screenshots, traces, reports, profile-config mutations, or unrelated files are staged.

- [ ] **Step 6: Commit verification-only changes**

Commit only if verification changed code or discoverability docs:

```powershell
git add -- <explicit verified paths>
git commit -m "test: verify Facebook Crawl admin redesign"
```

---

### Task 8: Local Browser QA

**Files:**
- Modify only files required by browser defects, always after adding an automated regression.

**Interfaces:**
- Verifies the rendered admin workflow without triggering real production side effects.

- [ ] **Step 1: Start a local production-equivalent app**

Use Python 3.12 and the ignored environment source without printing or copying secrets:

```powershell
& $py -X utf8 app.py
```

Log in as Admin through the existing local mechanism. Do not run a real crawl, save production profiles, rotate tokens, or start maintenance.

- [ ] **Step 2: Verify desktop at 1440×1000**

Check:

1. `/admin/facebook-crawl` defaults to `?view=overview`.
2. Four primary cards and only active operational problems are immediately understandable.
3. No broker rows or duplicate cards are in the initial DOM/network payload.
4. Brokers view filters correctly, opens one drawer, shows dirty state, and warns on navigation.
5. Broker “Chạy” preselects the run form without a POST.
6. Run preview explains exact scope before confirmation.
7. History shows persisted jobs and safe failures/logs.
8. Advanced maintenance stays collapsed until requested.
9. Keyboard focus, labels, and menus are usable.
10. Console contains no warning/error caused by the feature.

Capture representative overview, brokers, and run screenshots outside git-tracked paths.

- [ ] **Step 3: Verify mobile at 375×812**

Check single-column overview, broker cards instead of a crushed table, 44px controls, drawer containment, no horizontal document overflow, readable run preview/history, and no fixed/sticky control covering content.

- [ ] **Step 4: Verify stale-save behavior locally**

Using two local authenticated tabs and a temporary test profile file, edit both drafts, save tab A, then save tab B. Confirm tab B receives the conflict banner, retains its unsaved form values, and does not overwrite tab A.

- [ ] **Step 5: Final verification and handoff**

Rerun Task 7 Steps 1–2 fresh after any browser fix. Report separately:

- automated local evidence;
- local browser evidence;
- database migration status;
- production status (not deployed unless separately authorized).

