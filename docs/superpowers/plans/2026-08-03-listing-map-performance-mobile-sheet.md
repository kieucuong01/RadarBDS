# Listing Maps Performance and Mobile Sheet Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make homepage Maps responsive for the full `Săn Deal` and `Tin rao` datasets, cap initial directory DOM at 100 locations, and ensure a selected mobile listing is fully visible above the device safe area.

**Architecture:** Keep the existing Maps APIs and Leaflet Canvas layer, but replace duplicate responsive rendering with one cached view rendered into the active panel. Progressively disclose directory groups in batches of 100 and create markers in animation-frame batches guarded by a render generation. On mobile, hide page-level navigation while the modal Maps tool is open and use an explicit collapsed/expanded sheet state that expands on marker selection.

**Tech Stack:** Vanilla JavaScript, Leaflet 1.9.4 Canvas renderer, Flask/Jinja templates, CSS dynamic viewport and safe-area primitives, pytest source/Node contract tests, Playwright CLI production browser measurement, PowerShell deployment tooling.

## Global Constraints

- Preserve the current `/api/map-listings` and `/api/map-listing-items` request and response contracts.
- Preserve `mode=signals` actionable-signal behavior, `mode=all` visibility behavior, all active filters, tier redaction, and the shared listing modal.
- Keep every valid location from the summary payload available as a marker; do not add server-side viewport filtering or marker clustering.
- Render only `#listingMapPanel` above 760 px or `#listingMapMobileSheet` at or below 760 px.
- Render at most 100 location buttons initially and append at most 100 per `Xem thêm` action.
- Yield marker and directory work so no Maps-attributable main-thread task exceeds 50 ms.
- Keep the summary request count at one per Maps open, including viewport/orientation changes.
- Hide `.mobile-bottom-nav` and `.floating-actions` only while Maps is open at mobile widths.
- Keep pinch zoom enabled, respect `env(safe-area-inset-*)`, provide 44x44 px controls, and honor `prefers-reduced-motion`.
- Preserve Maps close, Escape, browser Back, focus restoration, and listing-modal behavior.
- Write a failing test before each implementation change, confirm RED, implement the smallest change, confirm GREEN, and create focused commits.
- Do not claim the UI change alone proves 5,000 simultaneous cold Maps requests; production capacity claims require the existing controlled cache/load-test gates.

---

## File Structure

| File | Responsibility |
|---|---|
| `static/js/main/listing_map.js` | Active responsive view, directory disclosure, marker batching/cancellation, mobile sheet state, and current Maps behavior |
| `static/css/main/listing_map.css` | Responsive sheet geometry, safe-area handling, mobile navigation suppression, 44 px controls, and reduced motion |
| `templates/partials/listing_map_workspace.html` | Stable mobile-sheet state/label hooks without duplicating listing content |
| `templates/index.html` | Cache-bust the Maps JS and CSS together |
| `tests/test_listing_map_js.py` | Pure pagination/batch helpers plus JavaScript behavior contracts |
| `tests/test_listing_map_ui.py` | Rendered template, CSS, cache-key, responsive state, and accessibility contracts |
| `docs/operations.md` | Production commit, measurements, service/API evidence, and rollback handoff |
| `docs/superpowers/specs/2026-08-03-listing-map-performance-mobile-sheet-design.md` | Approved design status and immutable design intent |

## Task 1: Active Responsive View and 100-Location Disclosure

**Files:**
- Modify: `static/js/main/listing_map.js:13-38, 308-352, 464-527, 633-805, 843-949, 1000-1032`
- Modify: `tests/test_listing_map_js.py`
- Modify: `tests/test_listing_map_ui.py:150-190`

**Interfaces:**
- Produces: `DIRECTORY_BATCH_SIZE = 100`
- Produces: `DIRECTORY_FRAME_CHUNK_SIZE = 25`
- Produces: `activePanelId(isMobile: boolean) -> "listingMapMobileSheet" | "listingMapPanel"`
- Produces: `directoryWindow(total: number, requestedVisible: number) -> {visible, nextVisible, remaining}`
- Produces: internal `setPanelView(kind, group, payload)` and `renderActiveView()`
- Produces: internal `cancelDirectoryRender()`, `scheduleDirectoryChunk(callback)`, and `appendDirectoryGroups(list, groups)`
- Stores: `state.panelView`, `state.directoryVisibleCount`, `state.directoryGeneration`, `state.directoryFrameId`, `state.mediaQuery`, and `state.mediaQueryHandler`
- Removes: `panelTargets()` as a rendering primitive

- [ ] **Step 1: Add failing pure-helper and source-contract tests**

Append to `tests/test_listing_map_js.py`:

```python
def test_active_panel_and_directory_window_contracts():
    assert _run_node("mapApi.activePanelId(false)") == "listingMapPanel"
    assert _run_node("mapApi.activePanelId(true)") == "listingMapMobileSheet"
    assert _run_node("mapApi.directoryWindow(1837,0)") == {
        "visible": 100,
        "nextVisible": 200,
        "remaining": 1737,
    }
    assert _run_node("mapApi.directoryWindow(1837,100)") == {
        "visible": 100,
        "nextVisible": 200,
        "remaining": 1737,
    }
    assert _run_node("mapApi.directoryWindow(1837,1800)") == {
        "visible": 1800,
        "nextVisible": 1837,
        "remaining": 37,
    }
    assert _run_node("mapApi.directoryWindow(42,0)") == {
        "visible": 42,
        "nextVisible": 42,
        "remaining": 0,
    }


def test_listing_map_renders_one_responsive_panel_and_reuses_cached_view():
    source = MAP_SCRIPT.read_text(encoding="utf-8")

    assert "function activePanelId(isMobile)" in source
    assert "function activePanel()" in source
    assert "function renderActiveView()" in source
    assert "function appendDirectoryGroups(list, groups)" in source
    assert 'matchMedia("(max-width: 760px)")' in source
    assert 'addEventListener("change", state.mediaQueryHandler)' in source
    assert "function panelTargets()" not in source
    assert "DIRECTORY_BATCH_SIZE = 100" in source
    assert "DIRECTORY_FRAME_CHUNK_SIZE = 25" in source
    assert '"Xem thêm " + page.remaining + " vị trí"' in source
```

Update `test_workspace_js_has_history_focus_abort_and_honest_group_contracts()` in `tests/test_listing_map_ui.py` to require `renderActiveView()` and remove any assertion that depends on both responsive panels receiving content.

- [ ] **Step 2: Run the new tests and confirm RED**

```powershell
& $py -X utf8 -m pytest `
  tests\test_listing_map_js.py::test_active_panel_and_directory_window_contracts `
  tests\test_listing_map_js.py::test_listing_map_renders_one_responsive_panel_and_reuses_cached_view `
  -q
```

Expected: FAIL because the helpers, responsive media state, and one-panel renderer do not exist and `panelTargets()` still exists.

- [ ] **Step 3: Add pure responsive and disclosure helpers**

Near the existing constants in `static/js/main/listing_map.js`, add:

```javascript
  var DIRECTORY_BATCH_SIZE = 100;
  var DIRECTORY_FRAME_CHUNK_SIZE = 25;
  var MOBILE_MEDIA_QUERY = "(max-width: 760px)";

  function activePanelId(isMobile) {
    return isMobile ? "listingMapMobileSheet" : "listingMapPanel";
  }

  function directoryWindow(total, requestedVisible) {
    var safeTotal = safeCount(total);
    var requested = safeCount(requestedVisible);
    var visible = Math.min(
      safeTotal,
      Math.max(requested || DIRECTORY_BATCH_SIZE, DIRECTORY_BATCH_SIZE)
    );
    var nextVisible = Math.min(safeTotal, visible + DIRECTORY_BATCH_SIZE);
    return {
      visible: visible,
      nextVisible: nextVisible,
      remaining: Math.max(safeTotal - visible, 0)
    };
  }
```

Export both helpers from the returned API object.

- [ ] **Step 4: Replace two-panel loops with a cached active view**

Extend `state` with:

```javascript
    panelView: { kind: "directory", group: null, payload: null },
    directoryVisibleCount: DIRECTORY_BATCH_SIZE,
    directoryGeneration: 0,
    directoryFrameId: null,
    mediaQuery: null,
    mediaQueryHandler: null
```

Replace `panelTargets()` with:

```javascript
  function isMobileViewport() {
    return Boolean(state.mediaQuery && state.mediaQuery.matches);
  }

  function activePanel() {
    return element(activePanelId(isMobileViewport()));
  }

  function inactivePanel() {
    return element(activePanelId(!isMobileViewport()));
  }

  function setPanelView(kind, group, payload) {
    state.panelView = {
      kind: kind,
      group: group || null,
      payload: payload || null
    };
    renderActiveView();
  }
```

Refactor the existing directory, items, loading, summary-error, and item-error renderers to accept one explicit `target`. `renderActiveView()` must clear the inactive panel and render exactly one of these cached states into the active panel:

```javascript
  function renderActiveView() {
    var target = activePanel();
    clearElement(inactivePanel());
    if (!target) return;
    var view = state.panelView || { kind: "directory" };
    if (view.kind === "items") {
      renderItemsInto(target, view.group, view.payload || { items: [] });
      return;
    }
    if (view.kind === "items-loading") {
      renderItemsLoadingInto(target, view.group);
      return;
    }
    if (view.kind === "items-error") {
      renderItemsErrorInto(target, view.group);
      return;
    }
    if (view.kind === "summary-error") {
      renderSummaryErrorInto(target);
      return;
    }
    renderGroupDirectoryInto(target, state.summary || {
      summary: {}, locations: []
    });
  }
```

`selectGroup()` must set `items-loading`, `items`, or `items-error` through `setPanelView()`. `requestSummary()` must set `summary-error` through the same path. The directory back action must set `directory` without issuing a summary request.

- [ ] **Step 5: Render only the current directory slice and append 100**

In `renderGroupDirectoryInto(target, payload)`, replace the all-locations loop with:

```javascript
    var locations = payload.locations || [];
    var page = directoryWindow(
      locations.length,
      state.directoryVisibleCount
    );
    appendDirectoryGroups(list, locations.slice(0, page.visible));

    if (page.remaining > 0) {
      var more = create(
        "button",
        "listing-map-show-more",
        "Xem thêm " + page.remaining + " vị trí"
      );
      more.type = "button";
      more.addEventListener("click", function () {
        state.directoryVisibleCount = page.nextVisible;
        renderActiveView();
      });
      shell.appendChild(more);
    }
```

Add the cooperative directory renderer before `renderGroupDirectoryInto()`:

```javascript
  function cancelDirectoryRender() {
    state.directoryGeneration += 1;
    if (state.directoryFrameId !== null) {
      if (typeof root.cancelAnimationFrame === "function") {
        root.cancelAnimationFrame(state.directoryFrameId);
      } else {
        root.clearTimeout(state.directoryFrameId);
      }
    }
    state.directoryFrameId = null;
  }

  function scheduleDirectoryChunk(callback) {
    if (typeof root.requestAnimationFrame === "function") {
      state.directoryFrameId = root.requestAnimationFrame(callback);
      return;
    }
    state.directoryFrameId = root.setTimeout(callback, 0);
  }

  function appendDirectoryGroups(list, groups) {
    cancelDirectoryRender();
    var generation = state.directoryGeneration;
    var index = 0;

    function appendChunk() {
      if (!state.open || generation !== state.directoryGeneration) return;
      var end = Math.min(index + DIRECTORY_FRAME_CHUNK_SIZE, groups.length);
      var fragment = root.document.createDocumentFragment();
      for (; index < end; index += 1) {
        fragment.appendChild(groupButton(groups[index]));
      }
      list.appendChild(fragment);
      if (index < groups.length) {
        scheduleDirectoryChunk(appendChunk);
      } else {
        state.directoryFrameId = null;
      }
    }

    appendChunk();
  }
```

Call `cancelDirectoryRender()` before clearing/replacing the active view and from `close()`. The label deliberately reports the total remaining locations while each click advances by at most 100. Preserve the active panel scroll position around `renderActiveView()` for `Xem thêm`, and reset `directoryVisibleCount` to 100 only in `open()`.

- [ ] **Step 6: Bind responsive changes without refetching**

In `bind(doc, win)`:

```javascript
    state.mediaQuery = win.matchMedia(MOBILE_MEDIA_QUERY);
    state.mediaQueryHandler = function () {
      if (!state.open) return;
      renderActiveView();
      root.setTimeout(function () {
        if (state.map) state.map.invalidateSize();
      }, 0);
    };
    state.mediaQuery.addEventListener("change", state.mediaQueryHandler);
```

Initialize `panelView` and `directoryVisibleCount` in `open()`. In `close()`, clear both panel elements explicitly, but never render into both. No resize handler may call `requestSummary()`.

- [ ] **Step 7: Run focused tests and commit**

```powershell
& $py -X utf8 -m pytest tests\test_listing_map_js.py tests\test_listing_map_ui.py -q
node --check static\js\main\listing_map.js
git diff --check
git add static/js/main/listing_map.js tests/test_listing_map_js.py tests/test_listing_map_ui.py
git commit -m "perf(maps): bound responsive directory rendering"
```

Expected: all focused tests PASS; the source contains no `panelTargets()` and no all-location append into both panels.

## Task 2: Batched Marker Rendering with Generation Cancellation

**Files:**
- Modify: `static/js/main/listing_map.js:17-38, 545-589, 767-805, 883-905, 1015-1032`
- Modify: `tests/test_listing_map_js.py`

**Interfaces:**
- Produces: `MARKER_BATCH_SIZE = 200`
- Produces: `markerBatchRanges(total: number, batchSize: number) -> Array<[start, end]>`
- Produces: internal `cancelMarkerRender()`, `scheduleMarkerBatch(callback)`, and `renderMarkerBatch(context)`
- Stores: `state.markerGeneration`, `state.markerFrameId`, and `state.markerRenderCount`
- Consumes: existing `selectGroup(group)`, `markerStyle(precision)`, and Leaflet `state.markerLayer`

- [ ] **Step 1: Add failing marker-range and cancellation contract tests**

Append to `tests/test_listing_map_js.py`:

```python
def test_marker_batches_cover_every_location_without_overlap():
    assert _run_node("mapApi.markerBatchRanges(0,200)") == []
    assert _run_node("mapApi.markerBatchRanges(450,200)") == [
        [0, 200],
        [200, 400],
        [400, 450],
    ]


def test_marker_render_is_frame_batched_and_generation_guarded():
    source = MAP_SCRIPT.read_text(encoding="utf-8")

    assert "MARKER_BATCH_SIZE = 200" in source
    assert "function cancelMarkerRender()" in source
    assert "function scheduleMarkerBatch(callback)" in source
    assert "function renderMarkerBatch(context)" in source
    assert "context.generation !== state.markerGeneration" in source
    assert "scheduleMarkerBatch(function ()" in source
    assert "cancelMarkerRender();" in source
```

- [ ] **Step 2: Run the tests and confirm RED**

```powershell
& $py -X utf8 -m pytest `
  tests\test_listing_map_js.py::test_marker_batches_cover_every_location_without_overlap `
  tests\test_listing_map_js.py::test_marker_render_is_frame_batched_and_generation_guarded `
  -q
```

Expected: FAIL because marker construction is still one synchronous `forEach` and there is no generation/frame cancellation.

- [ ] **Step 3: Add marker batching helpers and exports**

Near the constants:

```javascript
  var MARKER_BATCH_SIZE = 200;

  function markerBatchRanges(total, batchSize) {
    var safeTotal = safeCount(total);
    var safeBatch = Math.max(safeCount(batchSize) || MARKER_BATCH_SIZE, 1);
    var ranges = [];
    for (var start = 0; start < safeTotal; start += safeBatch) {
      ranges.push([start, Math.min(start + safeBatch, safeTotal)]);
    }
    return ranges;
  }
```

Export `markerBatchRanges` for Node tests.

- [ ] **Step 4: Implement cancellable animation-frame marker batches**

Extend `state`:

```javascript
    markerGeneration: 0,
    markerFrameId: null,
    markerRenderCount: 0
```

Add:

```javascript
  function cancelMarkerRender() {
    state.markerGeneration += 1;
    if (state.markerFrameId !== null) {
      if (typeof root.cancelAnimationFrame === "function") {
        root.cancelAnimationFrame(state.markerFrameId);
      } else {
        root.clearTimeout(state.markerFrameId);
      }
    }
    state.markerFrameId = null;
    state.markerRenderCount = 0;
  }

  function scheduleMarkerBatch(callback) {
    if (typeof root.requestAnimationFrame === "function") {
      state.markerFrameId = root.requestAnimationFrame(callback);
      return;
    }
    state.markerFrameId = root.setTimeout(callback, 0);
  }
```

Refactor marker construction into `addMarker(group)`. `renderMarkers(payload)` must cancel older work, clear layers, compute valid locations and full bounds before installing markers, fit bounds once, then start:

```javascript
  function renderMarkerBatch(context) {
    if (
      !state.open
      || context.generation !== state.markerGeneration
      || !state.markerLayer
    ) return;

    var end = Math.min(
      context.index + MARKER_BATCH_SIZE,
      context.groups.length
    );
    for (; context.index < end; context.index += 1) {
      addMarker(context.groups[context.index]);
    }
    state.markerRenderCount = context.index;

    if (context.index < context.groups.length) {
      setStatus(
        "Đang hiển thị " + context.index + "/"
          + context.groups.length + " vị trí...",
        true
      );
      scheduleMarkerBatch(function () {
        renderMarkerBatch(context);
      });
      return;
    }
    state.markerFrameId = null;
    setSummaryStatus(state.summary);
  }
```

The generation used in `context` must be captured after cancellation. Call `cancelMarkerRender()` in `close()` before removing the map. A stale frame must never add a marker to a new Leaflet instance.

- [ ] **Step 5: Run focused tests and commit**

```powershell
& $py -X utf8 -m pytest tests\test_listing_map_js.py tests\test_listing_map_ui.py -q
node --check static\js\main\listing_map.js
git diff --check
git add static/js/main/listing_map.js tests/test_listing_map_js.py
git commit -m "perf(maps): batch marker rendering by frame"
```

Expected: tests PASS and `renderMarkers()` no longer synchronously installs every location in one loop.

## Task 3: Mobile Sheet States, Safe Areas, and Navigation Suppression

**Files:**
- Modify: `templates/partials/listing_map_workspace.html:41-42`
- Modify: `static/js/main/listing_map.js:464-527, 633-765, 843-905`
- Modify: `static/css/main/listing_map.css:91-103, 163-165, 199-340, 383-488`
- Modify: `templates/index.html:99-113`
- Modify: `tests/test_listing_map_ui.py:11-53, 150-202`
- Modify: `tests/test_listing_map_js.py`

**Interfaces:**
- Produces: `setMobileSheetExpanded(expanded: boolean)`
- Produces: internal `appendSheetToggle(shell, expanded, label)`
- Stores: `state.sheetExpanded`
- Adds: `data-state="collapsed"` to `#listingMapMobileSheet`
- Adds CSS classes: `.listing-map-sheet-handle`, `.listing-map-sheet-toggle`, `.listing-map-show-more`, `.is-expanded`
- Changes both Maps asset keys to `listing-map-progressive-sheet-20260803`

- [ ] **Step 1: Add failing rendered HTML, JS, CSS, and cache-key tests**

Update `test_dashboard_renders_lazy_accessible_map_launcher_and_workspace()`:

```python
    assert 'id="listingMapMobileSheet"' in html
    assert 'data-state="collapsed"' in html
    assert html.count("listing-map-progressive-sheet-20260803") == 2
```

Add to `tests/test_listing_map_ui.py`:

```python
def test_mobile_map_sheet_owns_the_viewport_without_bottom_nav_overlap():
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    styles = (root / "static/css/main/listing_map.css").read_text(
        encoding="utf-8"
    )

    assert "body.listing-map-open .mobile-bottom-nav" in styles
    assert "body.listing-map-open .floating-actions" in styles
    assert "display: none !important;" in styles
    assert "height: 100dvh;" in styles
    assert "max(8px, env(safe-area-inset-bottom))" in styles
    assert ".listing-map-mobile-sheet.is-expanded" in styles
    assert "min(62dvh, 560px)" in styles
    assert ".listing-map-sheet-toggle" in styles
    assert "min-height: 44px" in styles
    assert "transition: none" in styles


def test_mobile_sheet_has_explicit_accessible_state_controls():
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    script = (root / "static/js/main/listing_map.js").read_text(
        encoding="utf-8"
    )

    assert "function setMobileSheetExpanded(expanded)" in script
    assert 'sheet.dataset.state = next ? "expanded" : "collapsed"' in script
    assert 'toggle.setAttribute("aria-expanded", next ? "true" : "false")' in script
    assert '"Xem danh sách vị trí"' in script
    assert '"Thu gọn"' in script
    assert "target.scrollTop = 0" in script
```

- [ ] **Step 2: Run the tests and confirm RED**

```powershell
& $py -X utf8 -m pytest `
  tests\test_listing_map_ui.py::test_dashboard_renders_lazy_accessible_map_launcher_and_workspace `
  tests\test_listing_map_ui.py::test_mobile_map_sheet_owns_the_viewport_without_bottom_nav_overlap `
  tests\test_listing_map_ui.py::test_mobile_sheet_has_explicit_accessible_state_controls `
  -q
```

Expected: FAIL because the old sheet has no state, remains behind the 71 px bottom navigation, and still uses the old asset key.

- [ ] **Step 3: Add the stable sheet state hook**

Change the partial to:

```html
  <div id="listingMapMobileSheet" class="listing-map-mobile-sheet"
    data-state="collapsed"
    aria-label="Danh sách lô đất trên thiết bị di động"></div>
```

Do not add a second static listing container or duplicate listing markup.

- [ ] **Step 4: Add explicit sheet-state behavior**

Extend state with `sheetExpanded: false`. Add:

```javascript
  function setMobileSheetExpanded(expanded) {
    var next = Boolean(expanded);
    var sheet = element("listingMapMobileSheet");
    state.sheetExpanded = next;
    if (!sheet) return;
    sheet.classList.toggle("is-expanded", next);
    sheet.dataset.state = next ? "expanded" : "collapsed";
    Array.prototype.forEach.call(
      sheet.querySelectorAll("[data-listing-map-sheet-toggle]"),
      function (toggle) {
        toggle.setAttribute("aria-expanded", next ? "true" : "false");
        toggle.textContent = next ? "Thu gọn" : "Xem danh sách vị trí";
      }
    );
  }
```

The directory renderer must prepend a decorative handle and an explicit toggle when its target is the mobile sheet:

```javascript
    var handle = create("div", "listing-map-sheet-handle");
    handle.setAttribute("aria-hidden", "true");
    shell.appendChild(handle);
    var toggle = create(
      "button",
      "listing-map-sheet-toggle",
      state.sheetExpanded ? "Thu gọn" : "Xem danh sách vị trí"
    );
    toggle.type = "button";
    toggle.dataset.listingMapSheetToggle = "true";
    toggle.setAttribute(
      "aria-expanded",
      state.sheetExpanded ? "true" : "false"
    );
    toggle.addEventListener("click", function () {
      setMobileSheetExpanded(!state.sheetExpanded);
    });
```

For selected items/loading/error views, add `Thu gọn` and retain `← Tất cả vị trí`. `selectGroup()` must call `setMobileSheetExpanded(true)` before rendering loading state. Every mobile selected-view renderer must set `target.scrollTop = 0` after replacing content. The directory back action keeps the expanded state so the user can immediately choose another location.

In `open()`, reset the state with `setMobileSheetExpanded(false)`. In `close()`, also reset it after hiding the workspace. On a breakpoint change, expand automatically only when the cached view is items/loading/error; otherwise preserve the directory choice.

- [ ] **Step 5: Replace mobile geometry and suppress page-level controls**

Inside `@media (max-width: 760px)` add:

```css
  body.listing-map-open .mobile-bottom-nav,
  body.listing-map-open .floating-actions {
    display: none !important;
  }

  .listing-map-workspace {
    height: 100vh;
    height: 100dvh;
    padding-bottom: 0;
  }

  .listing-map-mobile-sheet {
    right: 8px;
    bottom: max(8px, env(safe-area-inset-bottom));
    left: 8px;
    height: clamp(120px, 18dvh, 156px);
    max-height: calc(100dvh - 112px);
    overflow-y: auto;
    transition: height 0.2s ease, transform 0.2s ease,
      opacity 0.2s ease;
  }

  .listing-map-mobile-sheet.is-expanded {
    height: min(62dvh, 560px);
  }

  .listing-map-mobile-sheet:not(.is-expanded) .listing-map-group-list,
  .listing-map-mobile-sheet:not(.is-expanded) .listing-map-show-more,
  .listing-map-mobile-sheet:not(.is-expanded) .listing-map-directory-title {
    display: none;
  }
```

Add 44 px control styling and a non-interactive handle:

```css
.listing-map-sheet-toggle,
.listing-map-show-more {
  width: 100%;
  min-height: 44px;
  border: 1px solid var(--border, #e2e8f0);
  border-radius: 12px;
  background: var(--card, #fff);
  color: var(--text, #0f172a);
  font: inherit;
  font-weight: 800;
  cursor: pointer;
  touch-action: manipulation;
}

.listing-map-sheet-handle {
  width: 42px;
  height: 4px;
  margin: 0 auto 8px;
  border-radius: 999px;
  background: var(--border, #cbd5e1);
}
```

Raise `.listing-map-back` from 38 px to 44 px. In the reduced-motion media query set the sheet transition to none:

```css
  .listing-map-mobile-sheet {
    transition: none;
  }
```

- [ ] **Step 6: Cache-bust both Maps assets and make the test exact**

Change both keys in `templates/index.html` to:

```text
listing-map-progressive-sheet-20260803
```

Update the existing old-key assertion so the new key must occur exactly twice.

- [ ] **Step 7: Run focused tests and commit**

```powershell
& $py -X utf8 -m pytest tests\test_listing_map_js.py tests\test_listing_map_ui.py -q
node --check static\js\main\listing_map.js
git diff --check
git add templates/partials/listing_map_workspace.html static/js/main/listing_map.js static/css/main/listing_map.css templates/index.html tests/test_listing_map_js.py tests/test_listing_map_ui.py
git commit -m "fix(maps): redesign mobile selected listing sheet"
```

Expected: focused tests PASS, both asset keys match, and source contracts show bottom navigation suppression, safe-area geometry, explicit controls, and reduced motion.

## Task 4: Regression, Browser Performance, and Interaction Verification

**Files:**
- Modify if a regression test is needed: `tests/test_listing_map_js.py`
- Modify if a regression test is needed: `tests/test_listing_map_ui.py`
- Do not modify API/service files unless a failing unchanged contract proves an existing regression in the scoped Maps UI work

**Interfaces:**
- Verifies: one summary request per open, all marker layers installed, at most 100 initial location buttons, no inactive-panel directory, no mobile overlap, and existing modal/history behavior
- Produces: browser evidence for Task 5 documentation and release gate

- [ ] **Step 1: Run the complete focused automated gate**

```powershell
& $py -X utf8 -m pytest `
  tests\test_listing_map_js.py `
  tests\test_listing_map_ui.py `
  tests\test_listing_map_api.py `
  tests\test_listing_map_service.py `
  -q
node --check static\js\main\listing_map.js
git diff --check
```

Expected: all commands PASS. If a regression fails, add the smallest failing test that reproduces it before changing implementation, then rerun this entire gate.

- [ ] **Step 2: Restart local Flask and verify desktop behavior**

Use the repository's Python 3.12 and current `.env.local`:

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $py -X utf8 app.py
```

With Playwright CLI, verify on a 1440x900 viewport for both tabs:

- one `/api/map-listings` request per open;
- the visible directory contains at most 100 `.listing-map-group-button` elements;
- the hidden mobile sheet contains no generated directory or item nodes;
- `Xem thêm` increases button count by at most 100;
- all response locations eventually correspond to marker-layer entries;
- marker/directory selection loads the group and opens the existing listing modal;
- Escape and browser Back close Maps and restore focus.

- [ ] **Step 3: Verify mobile layout at 390x844 and 375x667**

For both `Săn Deal` and `Tin rao`, record bounding boxes for `.listing-map-mobile-sheet`, `.mobile-bottom-nav`, the first `.listing-map-item-card`, and the viewport.

Required assertions:

```javascript
const nav = document.querySelector('.mobile-bottom-nav');
const sheet = document.querySelector('.listing-map-mobile-sheet');
const card = sheet.querySelector('.listing-map-item-card');
const sheetRect = sheet.getBoundingClientRect();
const cardRect = card.getBoundingClientRect();
const navHidden = getComputedStyle(nav).display === 'none';
const firstCardVisible = cardRect.top >= sheetRect.top
  && cardRect.bottom <= sheetRect.bottom;
const noHorizontalOverflow = document.documentElement.scrollWidth
  === document.documentElement.clientWidth;
({ navHidden, firstCardVisible, noHorizontalOverflow,
   sheetRect: sheetRect.toJSON(), cardRect: cardRect.toJSON() });
```

Expected: all three booleans are `true`; sheet state becomes `expanded` after marker selection; explicit `Thu gọn` and `Tất cả vị trí` controls work; pinch zoom is not disabled.

- [ ] **Step 4: Measure render work and network counts**

Install a `PerformanceObserver` for `longtask` before opening Maps, click the launcher, wait until marker completion, and record Maps-attributable tasks between summary response end and final completion. Also count summary requests by pathname.

Required outcomes:

- warm-CDN launcher-to-usable-map <= 1.2 seconds;
- no Maps marker/directory long task > 50 ms;
- initial group-button count <= 100;
- summary request count = 1;
- every valid payload location is eventually installed;
- no new Maps application console errors.

- [ ] **Step 5: Commit any test-backed regression repair separately**

If Steps 2-4 reveal a defect, follow RED/GREEN and use:

```powershell
git add static/js/main/listing_map.js static/css/main/listing_map.css templates/partials/listing_map_workspace.html tests/test_listing_map_js.py tests/test_listing_map_ui.py
git commit -m "test(maps): cover responsive render regression"
```

If no code or test changes were required, do not create an empty commit.

## Task 5: Review, Rebase, Deploy, and Durable Operations Handoff

**Files:**
- Modify: `docs/operations.md`
- Modify only if review finds a scoped issue: files from Tasks 1-4

**Interfaces:**
- Consumes: approved design, focused commits, automated gate, and browser measurements
- Produces: current `origin/main`, deployed `radar-bds.service`, public proof, and an exact rollback/evidence record

- [ ] **Step 1: Perform a fresh scoped diff review**

Review from the pre-implementation base through HEAD:

```powershell
git log --oneline --decorate -8
git diff 79c7d21..HEAD -- static/js/main/listing_map.js static/css/main/listing_map.css templates/partials/listing_map_workspace.html templates/index.html tests/test_listing_map_js.py tests/test_listing_map_ui.py docs/superpowers docs/operations.md
git status --short
```

Check specifically for stale generation callbacks, duplicate responsive DOM, an unintended second summary fetch, broken history/focus behavior, mobile controls below 44 px, unsafe private-field rendering, or non-Maps files staged accidentally.

- [ ] **Step 2: Run verification before the final documentation commit**

```powershell
& $py -X utf8 -m pytest `
  tests\test_listing_map_js.py `
  tests\test_listing_map_ui.py `
  tests\test_listing_map_api.py `
  tests\test_listing_map_service.py `
  -q
node --check static\js\main\listing_map.js
git diff --check
```

Expected: all commands PASS with fresh output.

- [ ] **Step 3: Record exact local evidence and rollback in operations docs**

Add a dated `Listing Maps progressive rendering and mobile sheet` subsection to `docs/operations.md`. Use the exact results captured in Task 4 and include these labels in order:

```markdown
- Scope: `Săn Deal` and `Tin rao` homepage Maps.
- Automated gate: focused pytest count, Node syntax result, and diff-check result.
- Desktop evidence: viewport, summary request count, initial/after-more button counts, final marker count, longest Maps task, and launcher-to-usable time.
- Mobile evidence: 390x844 and 375x667 sheet/card bounds, bottom-navigation display, horizontal overflow, and selected sheet state.
- Asset key: `listing-map-progressive-sheet-20260803` for JS and CSS.
- Rollback: revert the scoped Maps commit(s), redeploy, and do not alter PostgreSQL/Redis/crawler/user data.
```

Commit only the approved status and durable handoff:

```powershell
git add docs/operations.md docs/superpowers/specs/2026-08-03-listing-map-performance-mobile-sheet-design.md docs/superpowers/plans/2026-08-03-listing-map-performance-mobile-sheet.md
git commit -m "docs(maps): record progressive render verification"
```

- [ ] **Step 4: Fetch, rebase, and rerun the gate**

```powershell
git fetch origin
git rebase origin/main
& $py -X utf8 -m pytest tests\test_listing_map_js.py tests\test_listing_map_ui.py tests\test_listing_map_api.py tests\test_listing_map_service.py -q
node --check static\js\main\listing_map.js
git diff --check
```

Expected: rebase completes without overwriting unrelated remote work and the focused gate remains green.

- [ ] **Step 5: Push and deploy production**

```powershell
git push origin HEAD:main
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\deploy_production.ps1
```

Expected: the VPS fast-forwards to the pushed commit, `/opt/radar-bds/current` points at it, `radar-bds.service` is active, and deploy smoke succeeds.

- [ ] **Step 6: Repeat public production proof**

On `https://radarbds.vn`, repeat Task 4 Steps 2-4 against a fresh browser session. Also verify:

```text
/robots.txt
/sitemap.xml
/api/dashboard
/api/signals?page=1&limit=3
/api/listings?date_range=3m&sort_by=date&sort_dir=desc&page=1&limit=3
```

Required: public HTTP 200s, matching deployed asset key, one Maps summary request per open, <=100 initial directory buttons, completed markers, zero mobile overlap, fully visible first card, and no new Maps application console errors.

- [ ] **Step 7: Amend the operations evidence only with verified production facts**

If production values differ materially from local results, update the same dated subsection with the exact public values, amend the documentation commit, rebase if `origin/main` advanced, push, and redeploy only when the amended commit changes rendered/runtime files. Never describe local-only evidence as production proof.
