# Browser-agent Signal Semantics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the existing dashboard signal journey reliably understandable to browser-based AI agents and assistive technology: agents can identify the active task tab, wait for the signal result region, distinguish errors from results, and find a canonical detail link for each signal.

**Architecture:** Keep the current visual design, filtering logic, request order, caching, and modal behavior. Add explicit ARIA state to the existing dashboard controls and panels, synchronize that state in the current tab switcher, label the signal-result region, and replace the modal signal card’s simulated button container with a semantic article containing a real detail link and separate native action controls.

**Tech Stack:** Jinja/HTML, vanilla JavaScript, CSS, Node.js assertion tests, Python 3.12/pytest static-contract tests, optional local browser smoke test.

## Global Constraints

- This plan changes browser semantics only. It does not add an agent API, write action, login flow, watchlist, lead submission, phone number, or original listing URL.
- Preserve the Signals-tab invariant: one settled filter triggers exactly one immediate `/api/signals` request; `/api/counts` remains deferred until that request settles; `/api/dashboard` does not run on this path.
- Preserve request cancellation and newest-response-wins as one set: `requestControllers[scope].abort()`, `signalRunSeq`, `signalRenderSeq`, `renderedSignalIds`, and page-1 reset.
- Preserve `RadarSignalCard.render()` as the shared primary renderer and keep the fallback renderer consistent.
- Do not turn the mixed desktop header into an ARIA `tablist`; it also contains the Công cụ disclosure. Use explicit button state and controlled-panel relationships instead.
- Do not put `aria-live` on the full card grid, because announcing every rendered card would be noisy. Use `aria-busy` on the region and `role="status"` only on compact loading/error messages.
- Do not visually redesign cards or navigation. Add only the styles needed for the native title link and focus indication.
- Keep `.playwright-cli/` and unrelated dirty files untouched. Stage only the files named in the current task.

---

## Task 1: Give dashboard tabs and signal results stable machine-readable state

**Files:**

- Modify: `templates/index.html`
- Modify: `static/js/main/core.js`
- Modify: `static/js/main/signals.js`
- Modify: `tests/test_public_header_navigation.py`

**Interfaces:**

- Consumes: existing `data-tab-target`, `.tab-content`, `switchTab(tabId, btn)`, `signalsGrid`, and `setSignalLoadingUI()` contracts.
- Produces: `aria-controls` and synchronized `aria-pressed` on every desktop/mobile task-tab button.
- Produces: synchronized `aria-hidden` on `#tab-signals`, `#tab-all`, `#tab-market`, and optional `#tab-insights`.
- Produces: a named `role="region"` for signal results with `aria-busy` state.
- Produces: compact `role="status"` signal error messages.
- Preserves: tab IDs, CSS active classes, `switchTab()` async loading branches, and all network sequencing.

- [ ] Extend `test_dashboard_tools_link_to_new_public_hubs_without_replacing_task_tabs()` or add a neighboring test in `tests/test_public_header_navigation.py` with these failing semantic assertions:

```python
def test_dashboard_task_tabs_and_signal_results_expose_agent_readable_state():
    markup = DASHBOARD.read_text(encoding="utf-8")
    core_script = DASHBOARD_JS.read_text(encoding="utf-8")
    signal_script = Path("static/js/main/signals.js").read_text(encoding="utf-8")

    for tab_id in ("signals", "all", "market", "insights"):
        assert markup.count(f'aria-controls="tab-{tab_id}"') == 2

    assert markup.count('data-tab-target="signals"') == 2
    assert markup.count('data-tab-target="signals" aria-controls="tab-signals" aria-pressed="true"') == 2
    for tab_id in ("all", "market", "insights"):
        assert markup.count(
            f'data-tab-target="{tab_id}" aria-controls="tab-{tab_id}" aria-pressed="false"'
        ) == 2

    assert 'id="tab-signals" class="tab-content active" aria-hidden="false"' in markup
    for tab_id in ("all", "market", "insights"):
        assert f'id="tab-{tab_id}" class="tab-content" aria-hidden="true"' in markup

    assert (
        'id="signalsGrid" role="region" '
        'aria-label="Danh sách signal phù hợp" aria-busy="true"'
    ) in markup
    assert "function syncDashboardTabState(tabId)" in core_script
    assert "control.setAttribute('aria-pressed', isActive ? 'true' : 'false')" in core_script
    assert "panel.setAttribute('aria-hidden', isActive ? 'false' : 'true')" in core_script
    assert "syncDashboardTabState(tabId);" in core_script
    assert 'role="status"' in signal_script
```

If `SHOW_INSIGHTS` can be false at render time, these assertions remain static template-contract checks and intentionally verify both conditional controls exist in source.

- [ ] Run the focused test and confirm it fails on the missing semantic attributes/helper:

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $py -X utf8 -m pytest tests\test_public_header_navigation.py -q
```

- [ ] Update the four desktop task-tab buttons and four mobile task-tab buttons in `templates/index.html`. Preserve their labels, icons, click handlers, and classes; add `type="button"` where the desktop control lacks it and use this exact state pattern:

```html
<button type="button" class="nav-link active"
  data-tab-target="signals" aria-controls="tab-signals" aria-pressed="true"
  onclick="switchTab('signals', this)">

<button type="button" class="nav-link"
  data-tab-target="all" aria-controls="tab-all" aria-pressed="false"
  onclick="switchTab('all', this)">
```

Apply the same `aria-controls`/`aria-pressed` mapping to `market`, conditional `insights`, and each `.bottom-nav-item`. The initial Signals controls are `true`; every other task-tab control is `false`.

- [ ] Add initial panel visibility semantics without changing class order or adding the HTML `hidden` attribute:

```html
<div id="tab-signals" class="tab-content active" aria-hidden="false">
<div id="tab-market" class="tab-content" aria-hidden="true">
<div id="tab-insights" class="tab-content" aria-hidden="true">
<div id="tab-all" class="tab-content" aria-hidden="true">
```

- [ ] Name the result region and mark the server-rendered empty grid as initially busy because the first load renders skeletons:

```html
<div class="cards-grid" id="signalsGrid" role="region"
  aria-label="Danh sách signal phù hợp" aria-busy="true">
  <!-- Rendered via JS -->
</div>
```

- [ ] Add this helper immediately before `switchTab()` in `static/js/main/core.js`:

```javascript
function syncDashboardTabState(tabId) {
  document.querySelectorAll('[data-tab-target]').forEach((control) => {
    const isActive = control.dataset.tabTarget === tabId;
    control.setAttribute('aria-pressed', isActive ? 'true' : 'false');
  });
  document.querySelectorAll('.tab-content').forEach((panel) => {
    const isActive = panel.id === `tab-${tabId}`;
    panel.setAttribute('aria-hidden', isActive ? 'false' : 'true');
  });
}
```

- [ ] In `switchTab(tabId, btn)`, call `syncDashboardTabState(tabId);` after the target tab is found and receives `.active`, before updating the mobile title or starting any tab-specific async load:

```javascript
  const tab = document.getElementById(`tab-${tabId}`);
  if (!tab) return;
  tab.classList.add('active');
  syncDashboardTabState(tabId);
```

Do not change the existing class toggling or any `loadMarket*`, `loadInsights`, `loadListings`, or Signals branches.

- [ ] Change only the inner error container produced by `renderSignalError()` in `static/js/main/signals.js`:

```javascript
  grid.innerHTML = `
    <div role="status" style="grid-column: 1/-1; padding: 48px 20px; text-align: center; border: 1px dashed var(--border); border-radius: 16px; margin-top: 20px; color: var(--text-muted);">
      ${message}
    </div>
  `;
```

Keep `setSignalLoadingUI()` as the owner of `signalsGrid` and `tab-signals` `aria-busy` updates.

- [ ] Run syntax and focused tests:

```powershell
node --check static\js\main\core.js
node --check static\js\main\signals.js
& $py -X utf8 -m pytest tests\test_public_header_navigation.py -q
```

- [ ] Commit only the tab/result semantics:

```powershell
git add -- templates/index.html static/js/main/core.js static/js/main/signals.js tests/test_public_header_navigation.py
git commit -m "fix: expose dashboard signal state semantically"
```

---

## Task 2: Replace simulated modal-card buttons with articles and canonical detail links

**Files:**

- Modify: `static/js/main/signal_card.js`
- Modify: `static/js/main/signals.js`
- Modify: `static/css/main/cards.css`
- Modify: `tests/js/test_signal_card.js`

**Interfaces:**

- Consumes: existing `detailHref(item)`, modal handler names (`openSignal`, `openListingModal`), `.scard` datasets, favorite button, and contact CTA.
- Produces: modal-mode `<article class="scard ...">` card container.
- Produces: a native `<a class="sc-title sc-title-link" href="/listing/<id>">` canonical detail action inside every modal-mode card.
- Preserves: link-mode comparable cards as a single outer `<a>`, card background click opening the current modal, favorite behavior, contact behavior, data attributes, redaction, analytics contexts, badges, and rendering output outside the wrapper/title structure.
- Removes: `role="button"`, `tabindex="0"`, and keydown simulation from modal-mode card containers.

- [ ] Change the modal-feed expectations first in `tests/js/test_signal_card.js`:

```javascript
const feed = api.render(item, {
  context: 'signal',
  openMode: 'modal',
  showFavorite: true,
  showContact: true,
});
assert.match(feed, /<article class="scard[^>]*signal-shared-card/);
assert.match(feed, /class="sc-title sc-title-link"/);
assert.match(feed, /href="\/listing\/42"/);
assert.doesNotMatch(feed, /role="button"/);
assert.doesNotMatch(feed, /tabindex="0"/);
assert.doesNotMatch(feed, /onkeydown=/);
assert.match(feed, /favorite-btn/);
assert.match(feed, /RÃ¡p má»‘i/);
```

Retain all comparable, missing-image, date-reason, valuation, and quality-badge assertions already in the test.

- [ ] Add static fallback-renderer assertions at the bottom of the same test:

```javascript
assert.match(signalsSource, /<article class="scard/);
assert.match(signalsSource, /class="sc-title sc-title-link"/);
assert.doesNotMatch(
  signalsSource,
  /<div class="scard[^`]*role="button" tabindex="0"/
);
```

- [ ] Run the Node test and confirm it fails on the current simulated-button markup:

```powershell
node tests\js\test_signal_card.js
```

- [ ] In `static/js/main/signal_card.js`, replace only the wrapper construction inside `render()` with:

```javascript
    var wrapperOpen = openMode === 'link'
      ? '<a class="scard signal-shared-card ' + (newListing ? 'is-new-signal' : '') + '" href="' + href + '"'
      : `<article class="scard signal-shared-card ${newListing ? 'is-new-signal' : ''}" onclick="${handler}(this)"`;
    var wrapperClose = openMode === 'link' ? '</a>' : '</article>';
```

The existing return expression still appends `data-*` attributes and the card `aria-label` before closing the opening tag. Do not change those attributes.

- [ ] In the same function, build a mode-specific title immediately before the final return:

```javascript
    var titleText = esc(item.title || '-');
    var titleHtml = openMode === 'modal'
      ? `<a class="sc-title sc-title-link" href="${href}" title="${esc(item.title || '')}" onclick="event.preventDefault();event.stopPropagation();${handler}(this.closest('.scard'))">${titleText}</a>`
      : `<div class="sc-title" title="${esc(item.title || '')}">${titleText}</div>`;
```

Replace only this current fragment:

```javascript
'<div class="sc-body"><div class="sc-title" title="' + esc(item.title || '') + '">' + esc(item.title || '-') + '</div>'
```

with:

```javascript
'<div class="sc-body">' + titleHtml
```

This preserves the outer-link structure for comparable cards and prevents nested links there. Modal-mode title activation keeps the current modal experience while exposing a real canonical `href` to browser agents and standard link discovery.

- [ ] Mirror the same semantic structure in the fallback branch of `renderSignalDealCard()` in `static/js/main/signals.js`. After `safeTitle` is computed, define:

```javascript
  const detailHref = x.detail_href || x.detail_url || `/listing/${encodeURIComponent(x.id)}`;
```

Replace the fallback opening/closing container and title with:

```javascript
  <article class="scard ${newCardClass} ${cardContext === 'all' ? 'listing-grid-card' : ''}"
    aria-label="${escHtml(cardLabel)}" onclick="${openHandler}(this)" ${dataAttr}>
    ${mediaHtml}
    <div class="sc-body">
      <a class="sc-title sc-title-link" href="${escHtml(detailHref)}" title="${safeTitle}"
        onclick="event.preventDefault();event.stopPropagation();${openHandler}(this.closest('.scard'))">${safeTitle || '-'}</a>
```

and close with `</article>`. Remove the fallback wrapper’s `role="button"`, `tabindex="0"`, and `onkeydown` attributes. Do not touch the existing `.sc-actions`, favorite, or contact CTA markup.

- [ ] Add these narrow styles immediately after `.sc-title` in `static/css/main/cards.css`:

```css
.sc-title-link,
.sc-title-link:visited,
.sc-title-link:hover {
  color: var(--text);
  text-decoration: none;
}

.sc-title-link:focus-visible {
  border-radius: 4px;
  outline: 3px solid var(--primary);
  outline-offset: 3px;
}
```

Do not remove the existing `.scard:focus-visible` rule because link-mode comparable cards still focus the outer card anchor.

- [ ] Run the card test and JavaScript syntax checks:

```powershell
node tests\js\test_signal_card.js
node --check static\js\main\signal_card.js
node --check static\js\main\signals.js
```

- [ ] Commit only the card-structure changes:

```powershell
git add -- static/js/main/signal_card.js static/js/main/signals.js static/css/main/cards.css tests/js/test_signal_card.js
git commit -m "fix: expose canonical signal detail links"
```

---

## Task 3: Verify the signal journey without changing its network behavior

**Files:**

- Verify: `templates/index.html`
- Verify: `static/js/main/core.js`
- Verify: `static/js/main/signals.js`
- Verify: `static/js/main/signal_card.js`
- Verify: `static/css/main/cards.css`
- Verify: `tests/test_public_header_navigation.py`
- Verify: `tests/js/test_signal_card.js`
- Verify: `tests/test_public_cache_headers.py`

**Interfaces:**

- Verifies task-tab state, result-region state, valid card interaction hierarchy, canonical detail links, and unchanged Guest API privacy/caching.
- Verifies source-level request-sequencing invariants remain present.
- Does not prove a production deployment or production browser state.

- [ ] Run all touched JavaScript syntax checks and unit tests:

```powershell
node --check static\js\main\core.js
node --check static\js\main\signals.js
node --check static\js\main\signal_card.js
node tests\js\test_signal_card.js
```

- [ ] Run the focused Python tests:

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $py -X utf8 -m pytest tests\test_public_header_navigation.py tests\test_public_cache_headers.py -q
```

- [ ] Prove the request-sequencing and cancellation symbols were not removed:

```powershell
rg -n "requestControllers\[scope\]\.abort|signalRunSeq|signalRenderSeq|renderedSignalIds" static\js\main\core.js static\js\main\signals.js
rg -n "loadSignals\(|scheduleCounts\(|shouldSchedule\(" static\js\main\filter_runtime.js
```

Confirm the source still performs a single immediate signal load, defers counts until it settles, rejects stale run/render sequences, and resets rendered IDs on page 1. If the evidence is ambiguous, inspect the surrounding functions; do not rewrite them as part of this task.

- [ ] Inspect the final DOM templates emitted by both card renderers:

```powershell
rg -n "<article class=|sc-title sc-title-link|role=\"button\"|tabindex=\"0\"|onkeydown=" static\js\main\signal_card.js static\js\main\signals.js
```

Expected result: modal card branches contain article/title-link markup; the removed simulated-button signature is absent. Any remaining `role="button"` elsewhere must be reviewed by context rather than deleted broadly.

- [ ] If the local PostgreSQL service and ignored environment overrides are already available, run an optional rendered smoke test without changing data:

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $py -X utf8 app.py
```

Using the browser-testing skill, open `http://127.0.0.1:5000/` and verify:

1. Săn Deal controls expose `aria-pressed="true"`; the Signals panel exposes `aria-hidden="false"`.
2. Switching to Tin rao changes both desktop/mobile corresponding controls and panel visibility semantics.
3. Returning to Săn Deal triggers the same network sequence as before; no duplicate `/api/signals` request appears for one settled filter.
4. `#signalsGrid` transitions from `aria-busy="true"` to `false` after results settle.
5. Each rendered card is an article with a named title link to `/listing/<id>` plus separate favorite/contact actions.
6. Keyboard focus reaches the title link, favorite button, and contact action in logical order.

If local runtime is unavailable, report browser smoke as unverified; do not infer success from unit tests.

- [ ] Inspect scope before handoff:

```powershell
git status --short
git diff --check
git diff --stat
```

- [ ] If verification required a correction, rerun the full focused suite and commit only that correction; otherwise do not create an empty commit:

```powershell
git add -- templates/index.html static/js/main/core.js static/js/main/signals.js static/js/main/signal_card.js static/css/main/cards.css tests/test_public_header_navigation.py tests/js/test_signal_card.js
git commit -m "test: verify browser-agent signal semantics"
```

---

## Production Verification Boundary

After review, merge, push, and the normal Radar BDS deployment chain, verify the deployed commit separately:

1. Record the deployed SHA and compare it with the pushed SHA.
2. Open the public homepage as a signed-out Guest and inspect the accessibility tree for tab button state, controlled panels, the named signal-result region, and article/title-link structure.
3. Capture the network log for one settled filter change and prove there is one immediate `/api/signals` request, followed only after settlement by `/api/counts`; no `/api/dashboard` request should appear on that Signals path.
4. Open at least one canonical `/listing/<id>` href from a signal title and verify the public detail page loads without exposing phone, seller, or original source URL to Guest.
5. Confirm mobile and desktop tab controls remain synchronized after switching.
6. Treat local tests, deployed SHA, public HTTP, network behavior, and browser semantics as separate evidence; none substitutes for the others.
