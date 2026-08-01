# Homepage Performance Phase 3 Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make signal cards the first useful dynamic content, reduce every settled signal-filter interaction from three immediate API calls to one, and emit canonical query strings that maximize shared cache hits.

**Architecture:** Add a tiny dependency-free UMD helper that can run in both the browser and Node tests. It canonicalizes filter parameters and sequences signal-first work. The existing files retain DOM rendering, AbortController, run IDs, and infinite-scroll behavior; dashboard metadata loads only on tabs that use it, while counts wait until the signal request settles.

**Tech Stack:** Vanilla JavaScript, browser `URLSearchParams`, `AbortController`, `PerformanceObserver`, Node's built-in `node:test`, pytest source/HTML contract tests, Playwright/browser performance trace.

## Global Constraints

- Phase 2 response and cache-key interfaces must be stable before deployment.
- One settled signal filter issues one high-priority `/api/signals` request; counts may follow only after cards are unblocked.
- `/api/dashboard` is not fetched from the active signal tab.
- Debounce remains 200 ms, within the approved 150-250 ms range.
- Obsolete signal/count/dashboard requests are aborted and old responses cannot overwrite the newest filter state.
- Pagination resets on material filter changes and existing listing-ID deduplication remains intact.
- Guest filter locks, visible UI, response shapes, URLs, SEO, saved listings, maps, and other tabs remain unchanged.
- Frontend emits stable parameter and multi-value ordering; server canonicalization remains authoritative.
- Added initial JavaScript must remain below 5 KB uncompressed and add no npm/runtime dependency.
- RUM emits only metric name/value/rating through the already configured GA4 function; no listing, filter, user, cookie, phone, or URL data.
- Write failing Node/pytest tests before each implementation change.

---

## File Structure

| File | Responsibility |
|---|---|
| `static/js/main/filter_runtime.js` | Pure canonical query and signal-first orchestration, browser + CommonJS export |
| `static/js/main/filters.js` | DOM filter collection, signal-first application flow, deferred counts, dashboard-only tabs |
| `static/js/main/signals.js` | Canonical page query, request sequencing, first-card performance marks |
| `static/js/main/core.js` | Remove obsolete global signal-version state only after all references are gone |
| `static/js/main/web_vitals.js` | Lightweight native LCP/CLS/INP observation and GA4 emission |
| `static/js/main/boot.js` | Preserve one initial `applyFilters()` boot path |
| `templates/index.html` | Load new helpers before consumers and bump deterministic asset versions |
| `tests/js/filter_runtime.test.cjs` | Pure Node tests for ordering, deduplication, and signal-first sequencing |
| `tests/test_refactor_structure.py` | Script order and no-dashboard-on-signal regression assertions |
| `tests/test_traffic_seo_aio.py` | Preserve total-free signal request and public funnel behavior |

## Task 1: Add a Pure Canonical Filter Runtime

**Files:**
- Create: `static/js/main/filter_runtime.js`
- Create: `tests/js/filter_runtime.test.cjs`
- Modify: `templates/index.html:1426-1433`
- Modify: `tests/test_refactor_structure.py`

**Interfaces:**
- Produces: `window.RadarFilterRuntime.canonicalize(input) -> string`
- Produces: `window.RadarFilterRuntime.runSignalFirst(loadSignals, scheduleCounts, shouldSchedule) -> Promise`
- Produces identical CommonJS exports for Node tests

- [ ] **Step 1: Write failing Node tests**

```javascript
const test = require('node:test');
const assert = require('node:assert/strict');
const runtime = require('../../static/js/main/filter_runtime.js');

test('canonicalize sorts keys and deduplicates order-insensitive filters', () => {
  const params = new URLSearchParams();
  params.append('ward', 'Tan An');
  params.append('source', 'guland');
  params.append('ward', 'Hiep An');
  params.append('source', 'facebook');
  params.append('ward', 'Tan An');
  params.set('page', '1');

  assert.equal(
    runtime.canonicalize(params),
    'page=1&source=facebook&source=guland&ward=Hiep+An&ward=Tan+An',
  );
});

test('canonicalize keeps range tokens stable and drops client sigv', () => {
  const params = new URLSearchParams('sigv=12&price_range=5%3A&price_range=%3A1&mos_min=10');
  assert.equal(
    runtime.canonicalize(params),
    'mos_min=10&price_range=%3A1&price_range=5%3A',
  );
});

test('runSignalFirst schedules counts only after signal settles', async () => {
  const events = [];
  let release;
  const signal = new Promise((resolve) => { release = resolve; });
  const running = runtime.runSignalFirst(
    () => { events.push('signals-start'); return signal; },
    () => events.push('counts'),
  );

  await Promise.resolve();
  assert.deepEqual(events, ['signals-start']);
  release('ok');
  assert.equal(await running, 'ok');
  assert.deepEqual(events, ['signals-start', 'counts']);
});

test('runSignalFirst still schedules counts after a signal error', async () => {
  const events = [];
  await assert.rejects(
    runtime.runSignalFirst(
      () => Promise.reject(new Error('signal failed')),
      () => events.push('counts'),
    ),
    /signal failed/,
  );
  assert.deepEqual(events, ['counts']);
});

test('runSignalFirst suppresses counts for a superseded filter snapshot', async () => {
  const events = [];
  await runtime.runSignalFirst(
    () => Promise.resolve('aborted-old-run'),
    () => events.push('counts'),
    () => false,
  );
  assert.deepEqual(events, []);
});
```

- [ ] **Step 2: Run and confirm RED**

```powershell
node --test tests\js\filter_runtime.test.cjs
```

Expected: FAIL because the helper file does not exist.

- [ ] **Step 3: Implement the UMD helper**

```javascript
(function initRadarFilterRuntime(root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.RadarFilterRuntime = api;
})(typeof window !== 'undefined' ? window : globalThis, function buildRuntime() {
  'use strict';

  const MULTI_KEYS = new Set([
    'ward', 'ward[]', 'source', 'source[]', 'prop_type', 'prop_type[]',
    'price_range', 'area_range',
  ]);
  const DROP_KEYS = new Set(['sigv']);

  function canonicalize(input) {
    const source = input instanceof URLSearchParams
      ? input
      : new URLSearchParams(String(input || ''));
    const grouped = new Map();
    for (const [rawKey, rawValue] of source.entries()) {
      const key = String(rawKey || '').trim();
      if (!key || DROP_KEYS.has(key)) continue;
      const value = String(rawValue || '').trim();
      if (!grouped.has(key)) grouped.set(key, []);
      grouped.get(key).push(value);
    }

    const output = new URLSearchParams();
    for (const key of Array.from(grouped.keys()).sort()) {
      const values = grouped.get(key);
      const normalized = MULTI_KEYS.has(key)
        ? Array.from(new Set(values.filter(Boolean))).sort()
        : [values[values.length - 1]];
      for (const value of normalized) output.append(key, value);
    }
    return output.toString();
  }

  async function runSignalFirst(loadSignals, scheduleCounts, shouldSchedule = () => true) {
    try {
      return await loadSignals();
    } finally {
      if (shouldSchedule()) scheduleCounts();
    }
  }

  return Object.freeze({ canonicalize, runSignalFirst });
});
```

- [ ] **Step 4: Load the helper before filters/signals**

Add immediately after `core.js` and before `filters.js`:

```html
<script src="{{ url_for('static', filename='js/main/filter_runtime.js') }}?v=homepage-perf-20260801"></script>
```

Update the structure test to assert `filter_runtime.js` occurs before both `filters.js` and `signals.js`.

- [ ] **Step 5: Run Node, HTML, and syntax tests**

```powershell
node --test tests\js\filter_runtime.test.cjs
node --check static\js\main\filter_runtime.js
& $py -X utf8 -m pytest tests\test_refactor_structure.py -q
```

- [ ] **Step 6: Commit**

```powershell
git add static/js/main/filter_runtime.js templates/index.html tests/js/filter_runtime.test.cjs tests/test_refactor_structure.py
git commit -m "feat: add canonical filter runtime"
```

## Task 2: Make the Signal Feed the Only Immediate Filter Request

**Files:**
- Modify: `static/js/main/filters.js:65-310`
- Modify: `static/js/main/signals.js:267-283`
- Modify: `static/js/main/signals.js:794-850`
- Modify: `static/js/main/core.js:320-340`
- Modify: `tests/js/filter_runtime.test.cjs`
- Modify: `tests/test_refactor_structure.py`
- Modify: `tests/test_traffic_seo_aio.py`

**Interfaces:**
- Consumes: `RadarFilterRuntime.canonicalize()` and `runSignalFirst()`
- Produces: `deferCountsRefresh(useCache=False)`
- Preserves: `applyFilters()`, `scheduleApplyFilters()`, `loadSignals()`, `refreshCounts()`, `refreshDashboardMeta()` global names used by markup/modules

- [ ] **Step 1: Write failing source-contract tests**

Replace the old dashboard-deferral assertions with exact behavior:

```python
def test_signal_filter_flow_loads_cards_before_counts_without_dashboard():
    filters_js = _read("static/js/main/filters.js")
    start = filters_js.index("function applyFilters()")
    end = filters_js.index("\nfunction ", start + 1)
    apply_block = filters_js[start:end]

    assert "RadarFilterRuntime.runSignalFirst" in apply_block
    assert "loadSignals(1, { reset: true })" in apply_block
    assert "currentFilters === filterSnapshot" in apply_block
    assert "deferCountsRefresh(false)" in apply_block
    signal_branch = apply_block.split("if (tab === 'signals')", 1)[1].split("} else", 1)[0]
    assert "refreshDashboardMeta" not in signal_branch
    assert "refreshCounts(false);" not in signal_branch
```

Add assertions that `signalQuery()` calls `canonicalize()`, contains `include_total=0`, and no longer writes `sigv`.

- [ ] **Step 2: Run and confirm RED**

```powershell
& $py -X utf8 -m pytest tests\test_refactor_structure.py tests\test_traffic_seo_aio.py -q
```

- [ ] **Step 3: Canonicalize the base filter query**

At the end of `getFilterQuery()` replace `return params.toString()` with:

```javascript
return window.RadarFilterRuntime.canonicalize(params);
```

The DOM collection behavior stays unchanged. The helper sorts and deduplicates after all command-bar fields are added.

- [ ] **Step 4: Canonicalize signal pagination and remove client-only version noise**

Implement:

```javascript
function signalQuery(page) {
  const params = new URLSearchParams(currentFilters);
  params.set('sort', signalSort);
  params.set('page', String(page));
  params.set('limit', String(SIGNAL_PAGE_SIZE));
  params.set('include_total', '0');
  return window.RadarFilterRuntime.canonicalize(params);
}
```

Remove `signalsVersion` global state and the dashboard assignment after verifying no remaining reference with:

```powershell
rg -n "signalsVersion|sigv" static\js\main templates tests
```

Expected after edits: no runtime references.

- [ ] **Step 5: Defer counts until signal completion**

Add:

```javascript
function deferCountsRefresh(useCache = false) {
  const run = () => refreshCounts(useCache);
  if (typeof window.requestIdleCallback === 'function') {
    window.requestIdleCallback(run, { timeout: 1200 });
  } else {
    setTimeout(run, 100);
  }
}
```

Replace `applyFilters()` with this control flow while retaining existing market/insights/all-tab loads:

```javascript
function applyFilters() {
  currentFilters = getFilterQuery();
  const filterSnapshot = currentFilters;
  currentPageNo = 1;
  listingsHasMore = false;
  const tab = activeTabId();

  if (tab === 'signals') {
    window.RadarFilterRuntime.runSignalFirst(
      () => loadSignals(1, { reset: true }),
      () => deferCountsRefresh(false),
      () => currentFilters === filterSnapshot,
    ).catch((err) => {
      if (err && err.name !== 'AbortError') console.error(err);
    });
  } else {
    refreshCounts(false);
    refreshDashboardMeta(false);
  }

  if (tab === 'market') {
    ensureDashboardScript('market')
      .then(() => {
        loadMarketIndicators(false);
        loadMarketCharts(false);
        loadTrendData(false);
      })
      .catch((err) => console.error(err));
  }
  if (tab === 'insights') loadInsights(false);
  if (tab === 'all') {
    ensureDashboardScript('listings')
      .then(() => { initializeListingsUi(); loadListings(1); })
      .catch((err) => console.error(err));
  }
}
```

Delete `deferDashboardMetaRefresh()` after confirming it has no caller. Keep `refreshDashboardMeta()` for non-signal tabs.

- [ ] **Step 6: Preserve abort and response-order behavior**

Do not remove:

- `requestControllers[scope].abort()` in `fetchJSONCached()`;
- `signalRunSeq` increment on reset;
- `if (runId !== signalRunSeq) return` before render;
- `signalRenderSeq` chunk cancellation;
- `renderedSignalIds` reset/deduplication;
- pagination reset to page 1.

Extend the Node test with two `runSignalFirst()` calls resolving out of order. The superseded snapshot must not schedule counts; the current snapshot schedules exactly once. Retain the existing run-ID contract test proving only the newest payload can render.

- [ ] **Step 7: Run JS, source-contract, and API behavior tests**

```powershell
node --test tests\js\filter_runtime.test.cjs
node --check static\js\main\filter_runtime.js
node --check static\js\main\filters.js
node --check static\js\main\signals.js
node --check static\js\main\core.js
& $py -X utf8 -m pytest `
  tests\test_refactor_structure.py `
  tests\test_traffic_seo_aio.py `
  tests\test_guest_visibility.py `
  tests\test_source_policy.py -q
```

- [ ] **Step 8: Commit**

```powershell
git add static/js/main/filter_runtime.js static/js/main/filters.js static/js/main/signals.js static/js/main/core.js tests/js/filter_runtime.test.cjs tests/test_refactor_structure.py tests/test_traffic_seo_aio.py
git commit -m "perf: make signal filters load cards first"
```

## Task 3: Add Lightweight Core Web Vitals and First-Card Measurement

**Files:**
- Create: `static/js/main/web_vitals.js`
- Modify: `static/js/main/signals.js`
- Modify: `templates/index.html`
- Create: `tests/js/web_vitals.test.cjs`
- Modify: `tests/test_refactor_structure.py`

**Interfaces:**
- Produces GA4 event: `web_vital` with `metric_name`, rounded `metric_value`, and `metric_rating`
- Produces performance measure: `radar-first-signal-cards`
- Does not add an application API or database write

- [ ] **Step 1: Write failing pure rating tests**

```javascript
const test = require('node:test');
const assert = require('node:assert/strict');
const vitals = require('../../static/js/main/web_vitals.js');

test('rates approved Core Web Vitals thresholds', () => {
  assert.equal(vitals.rate('LCP', 2500), 'good');
  assert.equal(vitals.rate('LCP', 2501), 'needs-improvement');
  assert.equal(vitals.rate('INP', 200), 'good');
  assert.equal(vitals.rate('CLS', 0.1), 'good');
  assert.equal(vitals.rate('CLS', 0.26), 'poor');
});
```

- [ ] **Step 2: Run and confirm RED**

```powershell
node --test tests\js\web_vitals.test.cjs
```

- [ ] **Step 3: Implement native observers with no PII**

Use the same UMD pattern as `filter_runtime.js`. Export `rate(name, value)`. In browsers:

- observe `largest-contentful-paint` and retain the latest entry;
- accumulate layout shifts where `hadRecentInput` is false;
- observe `event` entries with `durationThreshold: 40` and retain the largest entry with a nonzero `interactionId` as INP;
- on `visibilitychange` to hidden, call `window.gtag('event', 'web_vital', {metric_name, metric_value, metric_rating, non_interaction: true})` only when `gtag` exists;
- send each metric once per page;
- do not include page URL in the custom event payload, filters, listing IDs, user IDs, cookies, or free-form text.

Exact thresholds:

```javascript
const THRESHOLDS = Object.freeze({
  LCP: [2500, 4000],
  INP: [200, 500],
  CLS: [0.1, 0.25],
});
```

- [ ] **Step 4: Measure first useful signal cards**

At the start of a reset load:

```javascript
if (reset && window.performance && performance.mark) {
  performance.mark('radar-signals-request-start');
}
```

Immediately after the first reset render inserts cards:

```javascript
if (reset && window.performance && performance.mark && performance.measure) {
  performance.mark('radar-first-signal-cards-rendered');
  performance.measure(
    'radar-first-signal-cards',
    'radar-signals-request-start',
    'radar-first-signal-cards-rendered',
  );
}
```

- [ ] **Step 5: Load after core and before boot**

```html
<script src="{{ url_for('static', filename='js/main/web_vitals.js') }}?v=homepage-perf-20260801"></script>
```

The helper must be below all visible HTML and must not block card rendering with any network fetch.

- [ ] **Step 6: Enforce the size budget and run tests**

```powershell
node --test tests\js\web_vitals.test.cjs tests\js\filter_runtime.test.cjs
node --check static\js\main\web_vitals.js
$bytes = (Get-Item -LiteralPath static\js\main\web_vitals.js).Length + (Get-Item -LiteralPath static\js\main\filter_runtime.js).Length
if ($bytes -gt 5120) { throw "New performance JS exceeds 5 KB uncompressed" }
& $py -X utf8 -m pytest tests\test_refactor_structure.py tests\test_traffic_seo_aio.py -q
```

- [ ] **Step 7: Commit**

```powershell
git add static/js/main/web_vitals.js static/js/main/signals.js templates/index.html tests/js/web_vitals.test.cjs tests/test_refactor_structure.py
git commit -m "perf: measure web vitals and first signal cards"
```

## Task 4: Browser Verification, Documentation, and Phase Gate

**Files:**
- Modify: `docs/architecture.md`
- Modify: `docs/dev_commands.md`
- Modify: `docs/operations.md`
- Modify: `AGENTS.md`
- Test: Node/pytest plus rendered browser traces

**Interfaces:**
- Produces: browser evidence for initial load, filter, pagination, authenticated bypass, and mobile layout
- Produces: documented query canonicalization and request-order contract

- [ ] **Step 1: Run the complete Phase 3 code verification**

```powershell
node --test tests\js\filter_runtime.test.cjs tests\js\web_vitals.test.cjs
node --check static\js\main\filter_runtime.js
node --check static\js\main\web_vitals.js
node --check static\js\main\filters.js
node --check static\js\main\signals.js
node --check static\js\main\core.js
node --check static\js\main\boot.js
& $py -X utf8 -m pytest `
  tests\test_refactor_structure.py `
  tests\test_traffic_seo_aio.py `
  tests\test_market_data_performance.py `
  tests\test_guest_visibility.py `
  tests\test_source_policy.py `
  tests\test_security_hardening.py -q
git diff --check
```

- [ ] **Step 2: Verify request order in a real browser**

For desktop and a 390x844 mobile viewport:

1. clear browser network log and navigate to `/` as guest;
2. confirm `/api/signals` is the first dynamic dashboard request;
3. confirm cards render before `/api/counts` completes;
4. change ward/source/property/MOS filters rapidly, then settle;
5. confirm canceled requests show aborted and only the newest response updates cards;
6. confirm no `/api/dashboard` request occurs while the signal tab remains active;
7. switch to Market and confirm dashboard/market requests still load correctly;
8. scroll for page 2 and confirm no duplicate listing IDs;
9. log in and repeat one filter to prove visible tier behavior and private response headers.

- [ ] **Step 3: Capture before/after performance evidence**

Record a browser performance trace and network waterfall under the same viewport/network profile as baseline. Report HTML TTFB, first signal API duration, `radar-first-signal-cards`, LCP, INP interaction sample, CLS, request count, and compressed transfer size.

- [ ] **Step 4: Update agent/operator docs**

Document:

- `filter_runtime.js` ownership and Node test command;
- canonical multi-value/key ordering;
- signal-first then count behavior;
- dashboard metadata only for non-signal tabs;
- abort/run-ID/dedup invariants;
- Core Web Vitals and first-card measurement names;
- browser verification checklist.

- [ ] **Step 5: Commit docs**

```powershell
git add AGENTS.md docs/architecture.md docs/dev_commands.md docs/operations.md
git commit -m "docs: document signal-first frontend performance"
```

- [ ] **Step 6: Apply the Phase 3 gate**

Pass only when:

- one settled signal filter has one immediate signal request;
- cards are not blocked by counts/dashboard;
- request cancellation and newest-response-wins are visibly proven;
- no filter/tab/saved-listing/map regression is observed;
- LCP/INP/CLS meet the approved thresholds in the controlled trace, or any remaining external bottleneck is measured and assigned to Phase 4;
- new performance JavaScript remains <= 5 KB uncompressed.

If cards or tier behavior regress, revert this phase's frontend commits without disabling the already-correct read model/cache backend.
