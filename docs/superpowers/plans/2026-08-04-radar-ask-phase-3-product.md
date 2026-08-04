# Hỏi Radar BĐS Phase 3 — Product Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the authenticated Hỏi Radar BĐS product: synchronous Fast/Standard questions, queued Deep Research, owned 90-day history, deletion and feedback, a full research workspace, contextual drawer, and Admin cost/quality visibility.

**Architecture:** A dedicated Flask blueprint maps authenticated HTTP requests to the Phase 1 orchestrator. Fast/Standard work stays bounded in the request; Deep work is leased from PostgreSQL by a separate worker. The browser renders typed JSON through safe DOM APIs, keeps simple answers compact, and progressively reveals evidence and deep analysis. All routes are private/no-store.

**Tech Stack:** Flask 3.1, PostgreSQL/psycopg 3, Redis 5, vanilla JavaScript modules, HTML/CSS, pytest, Node test runner.

---

## Phase Boundary

Phases 1 and 2 must be green and their interfaces stable. Keep `RADAR_ASK_ENABLED=0` by default. This phase permanently removes the legacy assistant code/route/UI/tests before any deployment, but leaves its dormant database tables for the Phase 4 destructive gate.

## File Map

| File | Responsibility |
|---|---|
| `routes/radar_ask_api.py` | Authenticated question, polling, history, deletion, and feedback endpoints |
| `routes/public.py` | Authenticated `/hoi-radar-bds` page route |
| `routes/admin_api.py` | Admin-only aggregate metrics endpoint |
| `app.py` | Register the new blueprint/page and remove legacy `/api/chat` delegate/import |
| `services/radar_ask/service.py` | HTTP-facing application service and response mapping |
| `services/radar_ask/worker.py` | PostgreSQL lease/execute/recover worker loop |
| `services/radar_ask/retention.py` | 90-day raw-content purge and 13-month aggregate purge |
| `services/radar_ask/repository.py` | Queue lease, owned pagination/deletion, feedback, and metrics queries |
| `radar.py` | Add `radar-ask-worker` and `radar-ask-retention` CLI commands |
| `templates/radar_ask.html` | Full research workspace |
| `static/js/radar_ask.js` | Submit/poll/history/delete/feedback/render behavior |
| `static/css/radar_ask.css` | Responsive accessible workspace and drawer styling |
| `templates/index.html` | Contextual launcher and drawer shell; remove legacy chat DOM |
| `static/js/main/auth_cta.js` | Remove old assistant behavior and call new drawer API |
| `static/js/main/core.js` | Remove legacy chat globals/state |
| `static/css/main/leads_chat.css` | Remove legacy chat selectors; keep unrelated lead styles |
| `templates/admin_control_room.html` | Radar Ask aggregate status panel |
| `static/js/admin.js` | Load/render aggregate metrics without content |
| `static/css/admin.css` | Admin metrics layout |
| `tests/test_radar_ask_api.py` | Auth, request, history, deletion, feedback, cache headers |
| `tests/test_radar_ask_worker.py` | Queue lease/recovery and isolated execution |
| `tests/test_radar_ask_retention.py` | Retention/deletion tests |
| `tests/js/radar_ask.test.cjs` | Safe rendering and UI state tests |
| `tests/test_radar_ask_ui.py` | Template/assets/context entry-point structure |
| `tests/test_radar_ask_admin.py` | Metrics authorization/aggregation tests |

## HTTP Response Contract

```json
{
  "run_id": "0f1c2465-8ce1-4d64-9965-f73f27f61885",
  "session_id": "ac60991d-8794-4a91-b69e-e6a152fbd5af",
  "status": "completed",
  "answer": {
    "answered": true,
    "depth": "fast",
    "verdict": null,
    "direct_answer": "Phú Mỹ đang có mức chào bán trung vị thấp hơn Định Hòa trong mẫu 90 ngày.",
    "claims": [],
    "key_metrics": [],
    "risks": [],
    "next_checks": [],
    "source_cards": [],
    "as_of": "2026-08-04T10:00:00+07:00",
    "dataset_version": "signals:7"
  },
  "quota": {"answered_today": 1, "daily_limit": 5, "remaining": 4},
  "cost_state": "normal"
}
```

Queued Deep runs return the same top-level shape with `status="queued"`, `answer=null`, and HTTP 202. Failures expose stable user-safe error codes only.

## Task 1: Add Authenticated Radar Ask API and Owned History

**Files:**

- Create: `services/radar_ask/service.py`
- Create: `routes/radar_ask_api.py`
- Modify: `routes/public.py`
- Modify: `app.py`
- Modify: `services/radar_ask/repository.py`
- Create: `tests/test_radar_ask_api.py`
- Modify: `tests/test_public_cache_headers.py`

**Interfaces:** Exposes every `/api/radar-ask/*` endpoint in the master plan and authenticated `GET /hoi-radar-bds`. Consumes `current_user()`, `current_tier()`, `reject_cross_site_session_request()`, repository ownership methods, and `run_question()`.

- [ ] **Step 1: Write failing route/auth/ownership tests.**

Cover feature-off 404, guest 401 with login action, Free/VIP/Admin access, invalid/oversized JSON 400, CSRF/cross-site rejection on writes, idempotency key handling, Fast 200, Deep 202, quota/budget errors, polling ownership, session pagination, title update, delete-one/delete-all, feedback ownership, no content leakage on cross-user IDs, and `Cache-Control: private, no-store` with no `X-Radar-Public-Cache`.

```python
def test_guest_cannot_open_or_ask(client, monkeypatch):
    monkeypatch.setenv("RADAR_ASK_ENABLED", "1")
    assert client.get("/hoi-radar-bds").status_code == 401
    response = client.post("/api/radar-ask/questions", json={"question": "Giá Phú Mỹ?"})
    assert response.status_code == 401
    assert response.get_json()["error"]["code"] == "login_required"


def test_cross_user_run_is_not_disclosed(auth_clients, seeded_runs):
    response = auth_clients.free.get(f"/api/radar-ask/runs/{seeded_runs.vip_run_id}")
    assert response.status_code == 404
    assert response.headers["Cache-Control"] == "private, no-store"
```

- [ ] **Step 2: Run tests and confirm routes are missing.**

```powershell
& $py -X utf8 -m pytest tests\test_radar_ask_api.py tests\test_public_cache_headers.py -q
```

Expected: 404/import failures for new routes.

- [ ] **Step 3: Implement thin authenticated routes.**

Register a dedicated blueprint. Resolve authenticated identity/tier server-side; never accept them from JSON. Call `reject_cross_site_session_request()` before every POST/PATCH/DELETE. Parse with `AskQuestionRequest.model_validate()`. Return a single error shape:

```python
def api_error(code: str, message: str, status: int, retry_after: int | None = None):
    body = {"error": {"code": code, "message": message}}
    if retry_after is not None:
        body["error"]["retry_after_seconds"] = retry_after
    response = jsonify(body)
    response.status_code = status
    response.headers["Cache-Control"] = "private, no-store"
    return response
```

Use 401 login-required, 403 admin/tier denial, 404 owner-scoped absence/feature off, 409 idempotency/state conflict, 429 daily/burst, 503 provider/worker unavailable, and 507 `monthly_budget_hard_stop`. Never put exception text, SQL, prompts, or provider payloads in responses.

Session list is keyset paginated by `(updated_at, id)` and capped at 50. Message list is capped at 100 per page. Deletion returns 204 and audit logs only IDs/counts, not content.

- [ ] **Step 4: Run route tests.**

```powershell
& $py -X utf8 -m pytest tests\test_radar_ask_api.py tests\test_public_cache_headers.py tests\test_security_hardening.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit API.**

```powershell
git add -- services/radar_ask/service.py routes/radar_ask_api.py routes/public.py app.py services/radar_ask/repository.py tests/test_radar_ask_api.py tests/test_public_cache_headers.py
git commit -m "feat: add authenticated Radar Ask API"
```

## Task 2: Add the PostgreSQL Deep Research Worker

**Files:**

- Create: `services/radar_ask/worker.py`
- Modify: `services/radar_ask/repository.py`
- Modify: `services/radar_ask/orchestrator.py`
- Modify: `radar.py`
- Create: `tests/test_radar_ask_worker.py`

**Interfaces:** Adds `lease_next_run()`, `renew_lease()`, `complete_leased_run()`, `fail_leased_run()`, `recover_expired_leases()`, and CLI `radar.py radar-ask-worker`. Only `AskDepth.DEEP` is queued.

- [ ] **Step 1: Write failing lease, recovery, and isolation tests.**

Test two workers never lease the same run, ordering by `available_at/created_at`, worker token ownership, lease renewal, expired lease recovery, maximum two attempts, graceful SIGTERM, feature-off refusal, hard-budget-stop refusal before provider call, and public request returning 202 without calling the provider.

```python
def test_two_workers_cannot_lease_same_run(worker_repo, queued_run):
    first = worker_repo.lease_next_run(worker_id="w1", lease_seconds=90)
    second = worker_repo.lease_next_run(worker_id="w2", lease_seconds=90)
    assert first.id == queued_run.id
    assert second is None


def test_deep_request_only_enqueues(api_client, provider_spy):
    response = api_client.post("/api/radar-ask/questions", json={"question": "Phân tích sâu lô 123", "requested_depth": "deep"})
    assert response.status_code == 202
    assert response.get_json()["status"] == "queued"
    assert provider_spy.call_count == 0
```

- [ ] **Step 2: Run worker tests and confirm missing worker behavior.**

```powershell
& $py -X utf8 -m pytest tests\test_radar_ask_worker.py tests\test_radar_ask_api.py -q
```

Expected: worker import/lease failures.

- [ ] **Step 3: Implement a bounded lease loop.**

Lease with one transaction:

```sql
WITH candidate AS (
    SELECT id
    FROM radar_ask_runs
    WHERE status = 'queued' AND available_at <= NOW()
    ORDER BY available_at, created_at
    FOR UPDATE SKIP LOCKED
    LIMIT 1
)
UPDATE radar_ask_runs r
SET status = 'running', worker_id = %(worker_id)s,
    lease_until = NOW() + (%(lease_seconds)s || ' seconds')::interval,
    attempt_count = attempt_count + 1, started_at = COALESCE(started_at, NOW())
FROM candidate
WHERE r.id = candidate.id
RETURNING r.*;
```

Worker concurrency remains process-level 2 from `RADAR_ASK_WORKER_CONCURRENCY`; each run has a 60-second Deep provider timeout and bounded tool/repair calls. On retryable failure, requeue with fixed bounded backoff of 10 then 30 seconds; after two attempts, mark failed and release reservations. On SIGTERM, stop leasing, finish or cancel within the service stop timeout, and never abandon money/question reservations.

- [ ] **Step 4: Run concurrency tests three times.**

```powershell
1..3 | ForEach-Object { & $py -X utf8 -m pytest tests\test_radar_ask_worker.py -q }
```

Expected: all runs pass without duplicate execution.

- [ ] **Step 5: Commit worker.**

```powershell
git add -- services/radar_ask/worker.py services/radar_ask/repository.py services/radar_ask/orchestrator.py radar.py tests/test_radar_ask_worker.py
git commit -m "feat: add Radar Ask deep research worker"
```

## Task 3: Enforce 90-Day Raw-Content Retention

**Files:**

- Create: `services/radar_ask/retention.py`
- Modify: `services/radar_ask/repository.py`
- Modify: `radar.py`
- Create: `tests/test_radar_ask_retention.py`

**Interfaces:** Adds CLI `radar.py radar-ask-retention [--dry-run]`, `purge_expired_content()`, and `purge_expired_usage()`. Phase 4 adds the timer.

- [ ] **Step 1: Write failing cutoff/idempotency tests.**

Use a fixed Asia/Bangkok clock. Prove 89-day content remains, content older than 90 days is deleted in bounded batches, sessions with no messages are removed, associated tool/evidence/feedback rows cascade, active/queued runs are preserved, content-free aggregates remain 13 months, 14-month aggregates purge, dry-run changes nothing, and rerun is idempotent.

- [ ] **Step 2: Run tests and confirm retention code is missing.**

```powershell
& $py -X utf8 -m pytest tests\test_radar_ask_retention.py -q
```

Expected: retention import/CLI failure.

- [ ] **Step 3: Implement bounded purge transactions.**

Select at most 500 terminal run/session IDs per transaction using explicit cutoffs. Delete raw messages, run inputs/outputs, tool arguments/results, evidence payloads, and feedback text through ownership/cascade relationships. Usage aggregates contain only date/month, tier/model, token/cost/count/outcome totals and may remain 13 months. Log counts and cutoff only.

- [ ] **Step 4: Run tests and CLI dry-run.**

```powershell
& $py -X utf8 -m pytest tests\test_radar_ask_retention.py -q
& $py -X utf8 radar.py radar-ask-retention --dry-run
```

Expected: tests pass; dry-run prints counts without mutations.

- [ ] **Step 5: Commit retention.**

```powershell
git add -- services/radar_ask/retention.py services/radar_ask/repository.py radar.py tests/test_radar_ask_retention.py
git commit -m "feat: enforce Radar Ask data retention"
```

## Task 4: Build the Full Research Workspace

**Files:**

- Create: `templates/radar_ask.html`
- Create: `static/js/radar_ask.js`
- Create: `static/css/radar_ask.css`
- Create: `tests/js/radar_ask.test.cjs`
- Create: `tests/test_radar_ask_ui.py`

**Interfaces:** Uses the Phase 3 API only. Exposes `window.RadarAsk.open(options)` and ES/CommonJS-testable pure render/state helpers without adding a frontend framework.

- [ ] **Step 1: Write failing DOM/state/template tests.**

Test authenticated bootstrap, quota label, example questions, Enter-to-submit/Shift+Enter newline, one pending submit, 200 answer, 202 poll with bounded backoff, retryable failure, hard budget stop, session navigation, delete confirmation, feedback, compact Fast rendering, progressive Deep sections, citations/source cards, `khong_du_du_lieu`, keyboard focus, ARIA live status, and malicious HTML rendered as text.

```javascript
test('renders model text as text, never executable HTML', () => {
  const root = fakeRoot();
  renderAnswer(root, completedAnswer({ direct_answer: '<img src=x onerror=alert(1)>' }));
  assert.equal(root.querySelector('[data-direct-answer]').textContent, '<img src=x onerror=alert(1)>');
  assert.equal(root.querySelectorAll('img').length, 0);
});

test('fast answer keeps deep sections collapsed', () => {
  const root = fakeRoot();
  renderAnswer(root, completedAnswer({ depth: 'fast' }));
  assert.equal(root.querySelector('[data-deep-details]').hidden, true);
});
```

- [ ] **Step 2: Run tests and confirm assets/template are missing.**

```powershell
node --test tests\js\radar_ask.test.cjs
& $py -X utf8 -m pytest tests\test_radar_ask_ui.py -q
```

Expected: module/template failures.

- [ ] **Step 3: Implement the workspace and safe renderer.**

Page layout: history rail, conversation column, sticky composer, quota/depth status, and evidence drawer. On 390px, history becomes an off-canvas sheet and the composer remains above the visual viewport. Use `<button>`, `<dialog>` or accessible sheet semantics, visible focus, 16px minimum input font, and reduced-motion support.

Fast answers show direct answer, 2–4 metrics, as-of time, and compact sources. Standard/Deep may show thesis/counter-thesis, risks, confidence, valuation trace, comparables, next checks, and exact source cards behind disclosure controls. Use `textContent`, DOM element creation, validated same-origin paths, and safe external links with `rel="noopener noreferrer"`; never use provider text in `innerHTML`.

Poll queued runs at 1, 2, 3, then 5-second intervals, stop after the server-declared terminal state or 2 minutes, and allow manual refresh without resubmitting the question.

- [ ] **Step 4: Run UI tests and JavaScript syntax check.**

```powershell
node --check static\js\radar_ask.js
node --test tests\js\radar_ask.test.cjs
& $py -X utf8 -m pytest tests\test_radar_ask_ui.py tests\test_radar_ask_api.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit the workspace.**

```powershell
git add -- templates/radar_ask.html static/js/radar_ask.js static/css/radar_ask.css tests/js/radar_ask.test.cjs tests/test_radar_ask_ui.py
git commit -m "feat: add Radar Ask research workspace"
```

## Task 5: Add the Contextual Drawer and Permanently Remove Legacy Assistant Code

**Files:**

- Modify: `templates/index.html`
- Modify: `static/js/main/auth_cta.js`
- Modify: `static/js/main/core.js`
- Modify: `static/css/main/leads_chat.css`
- Modify: `tests/test_refactor_structure.py`
- Modify: `tests/test_radar_ask_ui.py`
- Delete: `services/radar_assistant.py`
- Delete: `services/assistant_intents.py`
- Delete: `services/assistant_tools.py`
- Delete: `tests/test_radar_assistant.py`
- Modify: `routes/market_api.py`
- Modify: `app.py`

**Interfaces:** Adds contextual launcher payload `{listing_id, ward, road, question}` to `RadarAsk.open()`. Removes `/api/chat`, `toggleChat`, old chat globals/DOM/styles, old services, and old tests. Does not drop database tables.

- [ ] **Step 1: Change structural tests so they fail while legacy code remains.**

```python
def test_legacy_radar_assistant_is_absent(repo_root):
    forbidden = [
        "services/radar_assistant.py",
        "services/assistant_intents.py",
        "services/assistant_tools.py",
        "tests/test_radar_assistant.py",
    ]
    assert all(not (repo_root / path).exists() for path in forbidden)
    source = (repo_root / "app.py").read_text(encoding="utf-8")
    assert "build_assistant_response" not in source
    assert '"/api/chat"' not in source


def test_homepage_exposes_new_contextual_launcher(home_html):
    assert "data-radar-ask-open" in home_html
    assert "chatWindow" not in home_html
    assert "toggleChat" not in home_html
```

- [ ] **Step 2: Run tests and confirm legacy-removal assertions fail.**

```powershell
& $py -X utf8 -m pytest tests\test_refactor_structure.py tests\test_radar_ask_ui.py -q
```

Expected: old files, route, globals, or DOM are still found.

- [ ] **Step 3: Implement new entry points and delete old code permanently.**

Add a logged-in floating “Hỏi Radar BĐS” launcher and contextual actions on listing/signal views. Guests see a login CTA and cannot create a question. Context only supplies server-resolvable IDs and suggested text; the backend still verifies visibility/ownership.

Remove the legacy import/route delegate from `app.py` and `routes/market_api.py`; delete the three old service files and old test file with `apply_patch`; remove old HTML and JavaScript state/functions/exports; remove only assistant selectors from `leads_chat.css`, preserving unrelated lead UI. Do not archive or copy legacy code elsewhere.

- [ ] **Step 4: Prove no runtime reference remains.**

```powershell
rg -n "build_assistant_response|assistant_intents|assistant_tools|/api/chat|toggleChat|chatWindow|chatMessages|chatInput" app.py routes services templates static tests
```

Expected: exit code 1 with no matches, except migration/table names intentionally retained in `db/schema.py` and `db/connection.py` when searched separately.

- [ ] **Step 5: Run combined backend/frontend tests.**

```powershell
node --check static\js\radar_ask.js
node --check static\js\main\auth_cta.js
node --check static\js\main\core.js
node --test tests\js\radar_ask.test.cjs
& $py -X utf8 -m pytest tests\test_refactor_structure.py tests\test_radar_ask_ui.py tests\test_radar_ask_api.py tests\test_security_hardening.py -q
```

Expected: all tests pass; old endpoint returns 404.

- [ ] **Step 6: Commit removal and contextual UI.**

```powershell
git add -A -- app.py routes/market_api.py templates/index.html static/js/main/auth_cta.js static/js/main/core.js static/css/main/leads_chat.css services/radar_assistant.py services/assistant_intents.py services/assistant_tools.py tests/test_radar_assistant.py tests/test_refactor_structure.py tests/test_radar_ask_ui.py
git commit -m "refactor: replace legacy Radar Assistant UI"
```

## Task 6: Add Admin Usage, Cost, and Quality Observability

**Files:**

- Modify: `services/radar_ask/repository.py`
- Modify: `routes/admin_api.py`
- Modify: `templates/admin_control_room.html`
- Modify: `static/js/admin.js`
- Modify: `static/css/admin.css`
- Create: `tests/test_radar_ask_admin.py`

**Interfaces:** Adds `GET /admin/api/radar-ask/metrics` for aggregate counts only. It never returns question, answer, evidence, tool arguments/results, session title, phone, URL, or user PII.

- [ ] **Step 1: Write failing authorization and aggregate tests.**

Cover guest/free/vip denial, Admin success, current-month actual/reserved/projected cost, $20 warning/$50 hard state, questions by tier/model/depth/outcome, p50/p95 latency, provider/validation/insufficient rates, token/cache-hit totals, queue depth/oldest age, and feedback totals. Assert serialized output excludes raw-content field names and seeded secret strings.

- [ ] **Step 2: Run tests and confirm endpoint is absent.**

```powershell
& $py -X utf8 -m pytest tests\test_radar_ask_admin.py -q
```

Expected: 404 or missing metrics query.

- [ ] **Step 3: Implement aggregate query and panel.**

Use bounded date windows (today, 7 days, current month) and server-side grouped SQL over usage/run metadata. Admin UI shows a warning banner at USD 20 and a locked banner at USD 50, plus queue/provider/validation health. Escape all labels and render with DOM APIs.

- [ ] **Step 4: Run Admin and regression tests.**

```powershell
node --check static\js\admin.js
& $py -X utf8 -m pytest tests\test_radar_ask_admin.py tests\test_admin_control_room.py tests\test_radar_ask_api.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit observability.**

```powershell
git add -- services/radar_ask/repository.py routes/admin_api.py templates/admin_control_room.html static/js/admin.js static/css/admin.css tests/test_radar_ask_admin.py
git commit -m "feat: add Radar Ask admin observability"
```

## Phase 3 Stop/Go Gate

- [ ] Guest cannot open the page or submit; Free/VIP/Admin use server-derived tiers.
- [ ] Every assistant/page response is private/no-store and absent from public cache namespaces.
- [ ] Cross-user read/update/delete/feedback attempts do not disclose existence.
- [ ] Deep requests return 202 before any provider call and two workers never share a lease.
- [ ] Retention dry-run and purge behavior meet 90-day/13-month rules.
- [ ] Simple answers stay compact; deep evidence is progressively disclosed.
- [ ] 390px static/UI tests prove 16px composer, accessible focus, and no horizontal overflow.
- [ ] Legacy service files, endpoint, UI, JavaScript state, and tests are absent without archive.
- [ ] Four legacy database tables still exist and remain dormant until Phase 4.
- [ ] Admin metrics contain aggregates only and reflect cost warning/hard-stop states.
- [ ] Record the committed SHA; keep the production feature flag off.
