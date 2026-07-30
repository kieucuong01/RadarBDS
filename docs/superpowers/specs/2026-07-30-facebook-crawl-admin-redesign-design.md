# Facebook Crawl Admin Reliability And Task-First UX Design

**Date:** 2026-07-30

**Status:** Design direction approved; awaiting written spec review

**Primary surface:** `/admin/facebook-crawl`

**Related APIs:** `/admin/api/facebook-crawl/*`

## Goal

Make the Facebook Crawl admin surface easy to operate and reliable under the
current two-worker Gunicorn deployment.

The redesigned feature must:

1. show crawl health and required operator action before cumulative metrics;
2. separate overview, broker configuration, and manual execution into clear
   task-oriented views;
3. render only actionable duplicate recommendations by default;
4. preserve unsaved broker edits and warn before discarding them;
5. make manual-job state visible from every Gunicorn worker and retain recent
   job history after page reload;
6. load expensive broker statistics and duplicate analysis only when their
   views are opened;
7. keep the current deterministic crawl, normalization, dedup, valuation, and
   notification rules unchanged.

## Production Evidence

The 2026-07-30 production audit found:

- 23 configured and active Facebook profiles;
- 9 top-level statistics;
- 334 controls, including 150 buttons and 161 editable inputs/selects;
- 134 duplicate-comparison cards, but no comparison with an actionable
  3-day or 7-day cadence recommendation;
- a duplicate section about 13,285 pixels tall on desktop and 27,930 pixels
  tall at a 375-pixel mobile viewport;
- a total mobile document height of about 48,324 pixels;
- about 8.25 seconds from reload until the broker rows appeared in one live
  browser measurement;
- no browser console warning or error during the audited load.

Focused baseline verification passed 16 tests across
`tests/test_facebook_broker_governance.py` and
`tests/test_admin_growth_ui.py`.

## Root Causes

### Information hierarchy

The current page gives cumulative totals, health, scheduler details, Apify
quota, broker creation, city filtering, every duplicate comparison, 23 fully
editable broker rows, per-row crawl actions, and manual maintenance the same
visual priority.

The largest section contains no current action. Duplicate analysis includes
every same-city pair with enough shared lots, while a cadence change is offered
only when the reduced broker's directional overlap reaches 50% or 70%.

### Monolithic initial request

`GET /admin/api/facebook-crawl/config` performs broker-stat aggregation,
duplicate analysis, crawl summary work, and Apify token shaping before the
page can render the broker workspace.

The UI then creates all duplicate cards and all editable broker controls in a
single render.

### Process-local jobs

Manual crawl, maintenance, image-backfill, and source-retry jobs use the shared
in-process `FACEBOOK_CRAWL_JOBS` dictionary and lock.

Production runs Gunicorn with two workers. A job can be created in one worker
while a polling request reaches another worker that has no record of it.
Process-local active-job checks also cannot guarantee that only one admin job
is created across workers.

### Draft state is implicit

Broker edits and applied recommendations change only the browser-side
`crawlProfiles` array until `Lưu danh sách` is pressed. The page has no dirty
indicator or discard warning, so refresh, navigation, or reload can silently
lose edits.

## Chosen Approach

Use a task-first admin redesign backed by shared PostgreSQL job state.

Keep the existing Flask/Jinja/vanilla-JavaScript stack and the current admin
visual language. Do not introduce React, a new component framework, a new
queue service, or a new crawler.

The work has two implementation phases inside one feature plan:

1. shared job state and lazy API boundaries;
2. task-first UI, draft protection, and rendered browser verification.

Both phases preserve current public APIs outside the admin namespace and do
not change the Facebook daily timer.

## Component Boundaries

Keep the change focused in these units:

- `db/admin_jobs.py`: PostgreSQL job persistence only;
- `services/admin_jobs.py`: enqueue, active-job policy, progress, heartbeat,
  log bounding, completion, and stale reconciliation;
- `services/admin_quality.py`: overview, broker-stat, due-state, and duplicate
  read models;
- `routes/admin_api.py` and the current `app.py` compatibility implementations:
  thin request validation and response shaping;
- `static/js/admin/facebook-crawl.js`: Facebook Crawl view state, lazy loading,
  draft tracking, and renderers;
- `templates/admin_control_room.html` and focused Facebook Crawl styles:
  semantic shell and responsive presentation.

Do not use this work to refactor unrelated Admin Control Room panels. Shared
toast, theme, navigation, and authentication helpers remain shared.

## Information Architecture

`/admin/facebook-crawl` keeps its canonical path and gains three internal
views:

1. **Tổng quan**
2. **Môi giới**
3. **Chạy & lịch sử**

The selected view is reflected in `?view=overview`, `?view=brokers`, or
`?view=run`. An absent or invalid value resolves to `overview`.

Browser back/forward navigation restores the selected view without reloading
unrelated data. No view exposes more than one primary action.

### Tổng quan

The default view answers:

- Is the scheduled Facebook crawl healthy?
- When did it last run and what did it produce?
- What needs operator attention now?
- Is Apify quota sufficient?

Show four primary cards:

1. daily timer and next run;
2. last Facebook run result;
3. new/imported result of the latest batch;
4. active Apify keys and remaining quota.

Show one `Việc cần xử lý` section beneath the cards. It contains only active
problems:

- failed source runs;
- crawl/reprocess lock blockers;
- missing Facebook images;
- exhausted or failing Apify keys;
- an abandoned manual job.

When there are no problems, show one compact healthy state. Do not render
separate empty cards for source errors and locks.

Move cumulative listing and signal totals to secondary copy or remove them
from this surface. They are not primary crawl-operation decisions and already
belong to other admin views.

### Môi giới

The broker view contains:

- text search by broker name or Facebook URL;
- filters for city, active state, cadence, due state, and data-quality tier;
- a compact broker table;
- a broker add/edit drawer;
- a duplicate-optimization summary.

The compact table columns are:

1. broker and city;
2. enabled state;
3. next due state;
4. daily quota and cadence;
5. data-quality score;
6. last crawl;
7. one action menu.

Do not render broker name, URL, city, daily limit, range, and cadence as
always-visible inputs in every row.

Selecting a row opens a drawer with the editable fields:

- broker name;
- canonical Facebook profile URL;
- city;
- enabled state;
- daily limit;
- range days;
- cadence of 1, 3, or 7 days.

The row action `Chạy` opens `Chạy & lịch sử` with that broker preselected. It
does not start an external crawl immediately.

Each broker payload includes `due_today` and `next_due_date`. Both values are
derived from the existing stable URL-bucket cadence logic used by
`crawler.facebook_apify.profile_due_on`; the admin UI must not invent a second
scheduling rule.

Because the current profile count is small, filtering and sorting can remain
client-side after the broker payload loads. Pagination is not required for
the broker table in this release.

### Duplicate optimization

The broker view starts with one summary:

```text
0 cặp cần đổi chu kỳ · 134 cặp đang theo dõi
```

The numbers are illustrative of the audited snapshot and must come from the
API at runtime.

Default behavior:

- show only comparisons with `recommended_crawl_every_days` equal to 3 or 7;
- cap the first render at 20 items;
- show an honest no-action state when no comparison is actionable;
- preserve the city filter;
- label directional overlap clearly so the operator knows which broker is
  being reduced.

`Xem phân tích đầy đủ` expands a secondary analysis list in pages of 20. It
must not inject all comparisons into the initial DOM.

Applying a recommendation changes the broker draft only. The UI must say
`Đã áp dụng vào bản nháp — chưa lưu` and activate the dirty state.

### Chạy & lịch sử

The run view contains:

- broker selector;
- three Vietnamese mode choices;
- an execution preview;
- current-job progress;
- 20 recent admin jobs.

Mode labels and explanations:

- **Lần đầu:** lấy tối đa số bài đã chọn và chạy full Facebook import;
- **Hàng ngày:** incremental recent-post crawl using the broker's daily limit;
- **Theo khoảng ngày:** full fetch followed by the selected recent-day filter.

Before submission, show:

- broker and city;
- mode;
- post limit;
- range days when applicable;
- whether image download will run;
- whether reprocess will follow.

`Tạo job crawl` is the only primary action. Submission requires confirmation
from the preview. If another admin job is active, the API returns that job and
the UI focuses its progress instead of showing a generic failure.

Reprocess and valuation-only actions move into a collapsed
`Bảo trì nâng cao` section. Each action requires a confirmation that names the
scope and states that it can consume server resources.

## Draft And Save Contract

The broker payload received from the server is the saved baseline.

The client tracks a normalized serialized copy of:

- broker name;
- canonical URL;
- city;
- active;
- daily limit;
- range days;
- cadence.

Any difference activates:

- a visible `Chưa lưu` badge;
- the `Lưu thay đổi` primary action;
- a discard confirmation before changing the admin panel, reloading broker
  data, or leaving the page.

A successful save replaces the baseline and clears the dirty state. A failed
save keeps the draft and the dirty state.

Filtering, sorting, selecting a broker, or opening the duplicate analysis does
not mark the draft dirty.

The save API canonicalizes Facebook URLs by:

- trimming whitespace;
- removing query strings and fragments;
- removing a trailing slash;
- accepting supported `facebook.com` host variants and storing the canonical
  `https://www.facebook.com/<profile>` form;
- rejecting a second profile with the same canonical URL.

`GET /profiles` returns a content revision hash. `POST /profiles` must include
that revision. The server acquires a shared advisory lock, compares the current
revision, and returns HTTP 409 with the latest revision if another save won the
race. A successful write uses a temporary file plus atomic replace so another
worker cannot read a partially written JSON document.

## Shared Admin Job State

### Storage

Add an additive PostgreSQL table named `admin_jobs`.

It stores every async job that currently participates in the shared admin
crawl lock:

- Facebook manual crawl;
- Facebook maintenance;
- missing-image backfill;
- source retry.

Required fields:

- `id`;
- `job_type`;
- `status` (`queued`, `running`, `succeeded`, `failed`);
- `stage`;
- `mode`;
- source/profile/broker/city context;
- limit, days, and image-download options;
- progress percent and progress label;
- JSONB stats;
- JSONB bounded logs;
- safe error text;
- creator identity;
- created, started, heartbeat, updated, and finished timestamps.

Logs remain bounded to the latest 200 entries. Tokens, cookies, passwords,
raw environment values, and full source payloads must never be written to job
logs.

### Single-active-job rule

Enforce one queued or running admin job across the participating job types.

Enqueue uses one PostgreSQL transaction and a database advisory lock:

1. reconcile stale active jobs;
2. check for an existing queued/running job;
3. insert the new job;
4. commit before starting the local runner thread.

If another job exists, return HTTP 409 with its public job payload.

Add a partial unique index over a constant for rows whose status is `queued`
or `running`. This gives the database a final single-active-job guarantee even
if a future caller skips the service lock.

The existing shared runtime locks remain around the actual work as defense in
depth. Manual and scheduled Facebook crawling must both acquire
`crawl-facebook`; reprocess and image-download work retain their existing
shared lock names. Do not create a manual-only lock that permits overlap with
the production timer.

### Heartbeat and abandoned jobs

The runner updates `heartbeat_at` every 15 seconds while active. A lightweight
heartbeat helper is stopped in `finally`.

Any job still queued/running with a heartbeat older than two minutes is marked
failed with the public reason:

```text
Job dừng vì tiến trình máy chủ không còn hoạt động.
```

This makes deploys and worker crashes visible. This release does not resume a
partially completed crawl.

### Repository boundary

Create a focused repository/service boundary for:

- enqueue;
- fetch active;
- update progress;
- append bounded logs;
- finish success/failure;
- list recent jobs;
- reconcile stale jobs.

Routes and job runners must not contain ad hoc SQL. Existing public job payload
fields already consumed by the UI remain unchanged:

- `id`, `status`, `stage`, `mode`;
- `profile_url`, `broker_name`, `limit`, `days`, `download_images`;
- `progress_pct`, `progress_label`;
- `stats`, `error`, `logs`;
- `started_at`, `finished_at`.

New fields such as `job_type`, `created_by`, `created_at`, and `heartbeat_at`
are additive.

## API Boundaries And Lazy Loading

Use these admin-only endpoints:

- `GET /admin/api/facebook-crawl/overview`
- `GET /admin/api/facebook-crawl/profiles`
- `POST /admin/api/facebook-crawl/profiles`
- `GET /admin/api/facebook-crawl/duplicates`
- `GET /admin/api/facebook-crawl/jobs`
- `GET /admin/api/facebook-crawl/jobs/<id>`
- existing `POST /admin/api/facebook-crawl/run`
- existing `POST /admin/api/facebook-crawl/maintenance`
- existing Apify token endpoints.

`duplicates` accepts:

- `city`;
- `actionable=1|0`;
- `limit`, capped at 50;
- `offset`.

It returns:

- total comparison count;
- actionable count;
- filtered count;
- paginated comparisons.

The legacy `GET/POST /admin/api/facebook-crawl/config` remains as a compatibility
adapter for one release but is no longer called by the redesigned UI.

Loading order:

1. render the page shell;
2. load `overview`;
3. load `profiles` only when the broker view opens;
4. load actionable duplicates after profiles;
5. load jobs only when the run view opens or overview reports an active job;
6. load full duplicate analysis only after explicit expansion.

Each view owns its loading, error, empty, and retry state. One failed secondary
request must not blank the whole Facebook Crawl workspace.

## Error Handling

- Overview failure shows a scoped retry action and leaves navigation usable.
- Profile-load failure does not discard an existing dirty draft.
- Save validation errors appear beside the affected drawer field.
- Save conflicts retain the local draft and show how to reload.
- Duplicate-analysis failure leaves broker editing usable.
- Job enqueue failure must not start a runner thread.
- HTTP 409 focuses the already-active job.
- Job polling treats a persisted failed/stale job as a terminal state with a
  recovery message.
- Apify quota/payment errors keep the existing token failover behavior.
- No UI state may imply a job succeeded unless the persisted status is
  `succeeded`.

## Accessibility And Responsive Rules

- Internal view controls expose tab semantics and active state.
- All icon-only actions have accessible names.
- Buttons and controls are at least 44 pixels high on touch layouts.
- Drawer focus moves to its heading on open and returns to the triggering row
  on close.
- Errors use `role="alert"` or an equivalent live region.
- Progress updates use a polite live region without repeatedly stealing focus.
- Status never relies on color alone.
- At 375 pixels there is no horizontal page overflow.
- Mobile uses broker cards derived from the compact table data; it does not
  render ten stacked editable fields per broker by default.
- The save action stays reachable while a dirty broker draft exists.
- Motion respects `prefers-reduced-motion`.

## Performance Requirements

- The default overview must not call broker stats or duplicate analysis.
- The overview server response target is under 500 ms on the current
  production dataset.
- The broker payload target is under 2.5 seconds on the current production
  dataset.
- Duplicate analysis is lazy and renders no more than 20 items per page.
- The initial overview DOM contains no broker rows and no duplicate cards.
- Switching back to a successfully loaded view reuses a 10-second client cache
  until an explicit refresh or mutation invalidates it.
- Browser QA must use targeted ready-state assertions rather than
  `networkidle`.

## Security And Data Boundaries

- Every endpoint remains protected by admin authentication.
- Apify token values remain masked and never enter overview/profile/job
  payloads.
- Job creator identity comes from the authenticated admin session, not a
  client-supplied value.
- Error and log payloads are bounded and scrubbed of secrets.
- Profile configuration remains the source used by the deterministic
  Facebook crawler.
- No external LLM verification or enrichment is added.
- No Facebook profile, listing, signal, dedup, or valuation row is rewritten
  merely by viewing the admin page.

## Test Strategy

### Backend

Add failing tests first for:

1. shared job state visible through two repository/service instances;
2. concurrent enqueue permits exactly one active admin job;
3. stale heartbeat reconciliation marks an abandoned job failed;
4. bounded logs and secret-safe public payloads;
5. successful/failed job completion persists;
6. recent jobs return newest first with a limit of 20;
7. profile URL canonicalization and duplicate rejection;
8. overview excludes expensive broker and duplicate work;
9. duplicate pagination and actionable filtering;
10. legacy config compatibility during the transition;
11. cadence 1/3/7 behavior remains unchanged;
12. cross-city duplicate pairs remain excluded.

### Frontend contracts

Verify:

1. `view` query state and back/forward behavior;
2. overview-first loading;
3. profiles and duplicates load only when needed;
4. no full duplicate list is injected initially;
5. dirty badge, discard protection, failed-save preservation, and clean reset
   after success;
6. row `Chạy` preselects without starting a job;
7. run preview and confirmation;
8. HTTP 409 focuses the active job;
9. advanced maintenance confirmations;
10. Vietnamese labels and scoped loading/error/empty states;
11. JavaScript syntax and updated asset identity.

### Rendered browser QA

Local production-equivalent and live read-only QA cover:

- desktop overview, broker, and run views;
- 375-pixel mobile views;
- keyboard tab order and drawer focus return;
- no horizontal overflow;
- city/search/cadence/due filters;
- actionable-empty duplicate state and paginated expansion;
- dirty-state warning without saving production data;
- persisted recent-job rendering using local test jobs;
- no browser console warning/error.

Live QA must not start a real Apify crawl, reprocess, valuation-only job, or
save a production profile change without separate explicit authorization.

## Release And Rollback

Release in two checkpoints:

1. additive `admin_jobs` schema, repository, worker-safe APIs, and compatibility
   tests;
2. task-first UI, lazy requests, draft protection, asset cache bump, and
   browser QA.

Release evidence must include:

- migration and focused test output;
- JavaScript syntax checks;
- pushed commit and production HEAD equality;
- active `radar-bds.service`;
- two-worker job visibility verification using a safe synthetic/local test,
  not a real production crawl;
- internal admin API smoke;
- public dashboard/signals smoke;
- live read-only desktop/mobile browser evidence;
- served cache-busted admin assets.

Rollback restores the prior code and restarts `radar-bds.service`. The additive
`admin_jobs` table may remain unused; rollback must not delete job history,
Facebook profiles, listings, or crawl data.

## Explicit Non-Goals

- replacing Gunicorn, systemd, PostgreSQL, or the current crawler;
- adding Redis, Celery, or a resumable distributed job queue;
- cancelling or resuming an in-progress crawl;
- changing daily Facebook/Guland scheduling;
- changing parser, normalizer, dedup, valuation, signal, or Telegram rules;
- adding bulk cadence edits in the first release;
- adding broker trend charts or new growth analytics;
- redesigning the rest of the Admin Control Room;
- performing a real production crawl during automated release verification.
