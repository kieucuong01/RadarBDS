# Facebook Crawl Operational Clarity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild Facebook Crawl Overview and Brokers as a compact, professional operations console while preserving crawl and profile-management behavior.

**Architecture:** Keep the focused Jinja template and `RadarFacebookCrawlAdmin` controller. Restructure only the two view surfaces, add a Facebook Crawl-scoped CSS token/layout layer, and retain every JavaScript-rendered DOM ID and API route. Use native `<details>` for broker filter disclosure so no extra client state machine is introduced.

**Tech Stack:** Flask/Jinja, vanilla JavaScript, scoped CSS, Node built-in test runner, pytest.

## Global Constraints

- Do not change backend APIs, PostgreSQL schema, crawl scheduling, Apify quota behavior, duplicate-analysis logic, or authentication.
- Overview fetches only `/admin/api/facebook-crawl/overview`; it must not load profiles or duplicates on initial render.
- Brokers retains explicit-save drafts, `profile_revision_conflict` recovery, `removeProfileFromDraft()` semantics, safe Facebook links, and destructive-action confirmation.
- Preserve every existing `crawlOverview*`, `crawlBroker*`, drawer, duplicate, and unsaved-draft ID used by `static/js/admin/facebook-crawl.js`.
- Use scoped light/dark tokens, visible focus, 44px controls, color-plus-text statuses, current drawer focus behavior, and `prefers-reduced-motion`.
- Preserve `.playwright-cli/`; stage only files named in each task.

---

### Task 1: Create the red visual-contract tests

**Files:**
- Modify: `tests/js/test_facebook_crawl_admin.js`
- Modify: `tests/test_admin_growth_ui.py`

**Interfaces:**
- Consumes: `buildOverviewViewModel()`, `buildBrokerRosterViewModel()`, `create()`, and existing template IDs.
- Produces: source contracts for the operation shell, Overview grid, Broker filter disclosure, scoped tokens, mobile rows, and CSS cache key.

- [ ] **Step 1: Add failing template and CSS assertions**

```python
for marker in ('crawl-ops-context', 'crawl-overview-command-grid',
               'crawl-broker-filter-details', 'crawl-broker-summary-rail'):
    assert marker in template
for marker in ('--crawl-bg:', '--crawl-primary:', '.crawl-ops-context',
               '.crawl-broker-filter-details', 'prefers-reduced-motion: reduce'):
    assert marker in css
```

- [ ] **Step 2: Retain behavioral source assertions in the Node test**

```js
assert.match(source, /function setOverviewLoading/);
assert.match(source, /crawlOverviewCommand/);
assert.match(source, /crawlBrokerWorkbench/);
assert.match(source, /aria-busy/);
```

- [ ] **Step 3: Prove the new contracts are red**

```powershell
node --test tests/js/test_facebook_crawl_admin.js
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -X utf8 -m pytest tests/test_admin_growth_ui.py -q
```

Expected: only the new structure/token assertions fail. Do not commit a red baseline.

### Task 2: Rebuild the semantic template hierarchy without breaking controller hooks

**Files:**
- Modify: `templates/admin_control_room.html:400-585`
- Test: `tests/test_admin_growth_ui.py`

**Interfaces:**
- Consumes: existing `data-crawl-view`, `data-crawl-view-panel`, every controller ID, and `admin_icon()`.
- Produces: shared Overview context, health-first command grid, native Broker filter disclosure, continuous summary rail, and cache-busted CSS reference.

- [ ] **Step 1: Add the shared Overview context strip**

```html
<div class="crawl-ops-context" role="status" aria-live="polite">
  <span class="crawl-ops-context-label">Vận hành Facebook</span>
  <span id="crawlOverviewStatus" class="crawl-inline-status">Đang tải tổng quan</span>
</div>
```

Keep that ID unique; `setOverviewLoading()` continues to update it.

- [ ] **Step 2: Change Overview structure, not behavior**

```html
<div id="crawlOverviewCommand" class="crawl-overview-command-grid" aria-busy="true">
  <section id="crawlOverviewHealth" class="surface crawl-health-panel state-loading">…</section>
  <section class="surface crawl-attention-panel">…</section>
  <aside class="crawl-resource-rail" aria-label="Tài nguyên và hoạt động">…</aside>
</div>
```

Keep `crawlOverviewRunBtn` as the first primary action and `crawlOverviewBrokersBtn` as the secondary action. Preserve health, problem, resource, and error IDs.

- [ ] **Step 3: Make only advanced Broker selects collapsible**

```html
<details id="crawlBrokerFilterDetails" class="crawl-broker-filter-details">
  <summary><span>Bộ lọc nâng cao</span><span id="crawlBrokerFilterCount">0 đang áp dụng</span></summary>
  <div class="crawl-filter-rail">…existing select labels…</div>
</details>
```

Leave search and `crawlBrokerResetBtn` outside the closed details; retain every select ID, table, conflict banner, duplicate workspace, and drawer.

- [ ] **Step 4: Turn the existing broker `<dl>` into the continuous summary rail**

Add `crawl-broker-summary-rail` while retaining `crawlBrokerTotal`, `crawlBrokerActive`, `crawlBrokerDue`, and `crawlBrokerAttention`.

- [ ] **Step 5: Bump the affected CSS asset and run the green template test**

Set the CSS cache key to `admin-v56-facebook-crawl-ops-clarity`, update the old expectation, then run:

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -X utf8 -m pytest tests/test_admin_growth_ui.py::test_facebook_crawl_admin_is_task_first_and_loads_focused_module -q
```

Expected: PASS.

### Task 3: Add the Operations Console token layer and Overview styling

**Files:**
- Modify: `static/css/admin.css:3329-3755`
- Test: `tests/test_admin_growth_ui.py`

**Interfaces:**
- Consumes: `.facebook-crawl-shell`, existing theme selector, `.surface`, and Task 2 classes.
- Produces: semantic light/dark colors, a predictable layer scale, compact health/action hierarchy, stable loading feedback, and accessibility motion/focus rules.

- [ ] **Step 1: Add scoped tokens**

```css
.facebook-crawl-shell {
  --crawl-bg: #0b1220; --crawl-surface: #121c2d; --crawl-surface-strong: #17243a;
  --crawl-border: rgba(148,163,184,.22); --crawl-text: #f8fafc; --crawl-muted: #a7b4c8;
  --crawl-primary: #14b8a6; --crawl-success: #34d399; --crawl-warning: #fbbf24;
  --crawl-danger: #fb7185; --crawl-ring: #5eead4; --crawl-radius: 12px;
  --crawl-z-context: 10; --crawl-z-drawer: 40; --crawl-z-modal: 50;
}
```

Add matching light-theme values through the existing theme mechanism; consume token names in every new Facebook Crawl rule.

- [ ] **Step 2: Implement health-first Overview layout and stable loading**

```css
.crawl-overview-command-grid { display:grid; grid-template-columns:minmax(0,1.45fr) minmax(18rem,.9fr); gap:16px; }
.crawl-ops-context { min-height:36px; }
.crawl-health-panel { border-inline-start:4px solid var(--crawl-primary); }
.crawl-health-panel[data-health="critical"] { border-inline-start-color:var(--crawl-danger); }
```

Stack the grid at `max-width: 1024px`. Loading may change opacity/background but must not animate dimensions or create layout shift.

- [ ] **Step 3: Add focus and reduced-motion rules**

```css
.facebook-crawl-shell :is(button,input,select,summary):focus-visible { outline:3px solid var(--crawl-ring); outline-offset:2px; }
@media (prefers-reduced-motion: reduce) {
  .facebook-crawl-shell *, .facebook-crawl-shell *::before, .facebook-crawl-shell *::after { scroll-behavior:auto; transition-duration:.01ms; animation-duration:.01ms; }
}
```

- [ ] **Step 4: Run the green Overview regression and commit**

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -X utf8 -m pytest tests/test_admin_growth_ui.py -q
git add templates/admin_control_room.html static/css/admin.css tests/test_admin_growth_ui.py tests/js/test_facebook_crawl_admin.js
git commit -m "feat: refine facebook crawl operations console"
```

Expected: pytest exits 0 and the commit contains only Task 1-3 files.

### Task 4: Rebuild Brokers as a compact responsive roster

**Files:**
- Modify: `static/css/admin.css:existing crawl-broker rules`
- Modify: `templates/admin_control_room.html:Broker filter/table region only if needed`
- Test: `tests/test_admin_growth_ui.py`
- Test: `tests/js/test_facebook_crawl_admin.js`

**Interfaces:**
- Consumes: `buildBrokerRosterViewModel()`, broker state helpers, safe links, table `data-label` cells, duplicate IDs, drawer IDs, and Task 2 details element.
- Produces: continuous summary rail, readable filter disclosure, compact table scan order, label/value mobile rows, and non-overlapping drawer/scrim layers.

- [ ] **Step 1: Add failing Broker responsive/layer contracts**

```python
assert 'crawl-broker-summary-rail' in template
assert 'crawl-broker-filter-details' in template
assert '.crawl-broker-table td[data-label]::before' in css
assert 'min-height: 44px' in css
assert '--crawl-z-drawer' in css
```

Keep existing no-`innerHTML`, safe URL, explicit-delete, and drawer-viewport checks.

- [ ] **Step 2: Style the rail, details summary, and table density**

```css
.crawl-broker-summary-rail { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); border:1px solid var(--crawl-border); border-radius:var(--crawl-radius); overflow:clip; }
.crawl-broker-filter-details > summary { min-height:44px; cursor:pointer; }
.crawl-broker-table :is(th,td) { padding:12px 14px; }
.crawl-broker-actions { white-space:nowrap; }
```

Use text plus labeled badges for every state. Preserve edit/run/delete labels and existing safe link rendering.

- [ ] **Step 3: Add mobile ordering and tokenized drawer layers**

```css
@media (max-width:760px) {
  .crawl-broker-summary-rail { grid-template-columns:repeat(2,minmax(0,1fr)); }
  .crawl-broker-table thead { display:none; }
  .crawl-broker-table td[data-label]::before { content:attr(data-label); }
  .crawl-drawer-backdrop { z-index:var(--crawl-z-drawer); }
  .crawl-broker-drawer { z-index:var(--crawl-z-modal); }
}
```

Do not introduce fixed content width or horizontal document overflow.

- [ ] **Step 4: Run green Broker checks and commit**

```powershell
node --check static/js/admin/facebook-crawl.js
node --test tests/js/test_facebook_crawl_admin.js
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -X utf8 -m pytest tests/test_admin_growth_ui.py -q
git add templates/admin_control_room.html static/css/admin.css tests/test_admin_growth_ui.py tests/js/test_facebook_crawl_admin.js
git commit -m "feat: streamline facebook crawl broker roster"
```

Expected: all checks exit 0; controller behavior remains intact because IDs are preserved.

### Task 5: Verify rendered behavior and release-ready assets

**Files:**
- Verify: `templates/admin_control_room.html`
- Verify: `static/css/admin.css`
- Verify: `static/js/admin/facebook-crawl.js`
- Verify: `tests/js/test_facebook_crawl_admin.js`
- Verify: `tests/test_admin_growth_ui.py`

**Interfaces:**
- Consumes: completed markup, CSS, controller, and existing admin session.
- Produces: desktop/mobile evidence, focused regression, cache-key proof, and honest reporting of authentication or full-suite limitations.

- [ ] **Step 1: Run the focused regression matrix**

```powershell
node --check static/js/admin/facebook-crawl.js
node --test tests/js/test_facebook_crawl_admin.js
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -X utf8 -m pytest tests/test_admin_growth_ui.py tests/test_facebook_crawl_admin_api.py -q
git diff --check
```

Expected: all commands exit 0. A full-suite timeout is unverified, never a pass.

- [ ] **Step 2: QA both deep links at 1440px and 375px**

```text
/admin/facebook-crawl?view=overview
/admin/facebook-crawl?view=brokers
```

Verify no horizontal overflow, one obvious primary action, visible focus, Overview loading/error/healthy/attention states, Broker filter disclosure, draft/save/conflict state, drawer Escape/backdrop/focus return, explicit edit/run/delete controls, and reduced-motion behavior. Use an authenticated admin session if available; otherwise report the auth gate.

- [ ] **Step 3: Confirm served cache key and commit only corrections**

Verify `admin-v56-facebook-crawl-ops-clarity` in the rendered template. If QA finds a correction, stage only changed UI/test files and commit `fix: polish facebook crawl responsive states`; otherwise do not create an empty commit.

## Spec Coverage Review

- Shared shell, semantic tokens, accessibility, touch targets, reduced motion, and responsive layout: Tasks 2-4.
- Overview health/action hierarchy, resource snapshot, loading/error behavior, and light endpoint contract: Tasks 1-3 and 5.
- Broker roster, progressive filters, draft safety, table/drawer/duplicate preservation, and mobile layout: Tasks 1, 2, 4, and 5.
- No-backend-change constraint, focused regression, browser validation, cache busting, and honest reporting: Global Constraints and Task 5.
