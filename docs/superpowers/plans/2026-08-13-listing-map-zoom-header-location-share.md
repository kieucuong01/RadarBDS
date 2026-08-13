# Listing Maps Zoom, Compact Header, Location, and Share Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Open Listing Maps at zoom 14 with a one-row header, verified singleton-road price labels, in-map current-location and sharing controls, and share URLs that restore the same filtered Maps state.

**Architecture:** Keep Listing Maps as the existing lazy-loaded Leaflet workspace. Add pure URL, zoom, and geolocation-state helpers to `listing_map.js` for Node tests, then mount small Leaflet controls that own only browser interactions. Let `boot.js` consume the `map=1` launch flag after filter/tab hydration, while `listing_map.js` distinguishes normal pushed history from initial shared-link history.

**Tech Stack:** Flask/Jinja, vanilla JavaScript (UMD/CommonJS-testable module), Leaflet 1.9.4, CSS, pytest, Node.js, Chrome/Playwright browser verification.

## Global Constraints

- Initial map zoom is `min(max(fitted zoom + 1, 14), 16)`; markers outside the opening viewport are intentionally allowed.
- Price-label eligibility remains zoom 13 and collision avoidance remains active.
- A singleton `Theo đường` marker shows the existing two-row price/area/price-per-m² label only when all required values are valid.
- `Theo đường` multi-listing, `Theo khu vực`, and `Theo phường` markers show counts only.
- Keep all four legends visible on desktop and mobile: `Chính xác`, `Theo đường`, `Theo khu vực`, `Theo phường`.
- `Vị trí của tôi` and `Chia sẻ` stay inside the Leaflet map, below the native `+` / `−` control in that order.
- GPS coordinates and accuracy never leave browser memory and never enter analytics, APIs, storage, or share URLs.
- Share URLs preserve the active `signals`/`all` tab and public filters, add `map=1`, and omit location/viewport/selection state.
- A shared-link open does not push duplicate history; closing removes only `map=1` and preserves tab/filter state.
- Do not change backend endpoints, database schema, geocoding, registry, marker grouping, or listing modal behavior.
- Preserve untracked `.playwright-cli/` and unrelated working-tree changes.

---

## File Structure

- Modify `static/js/main/listing_map.js`: pure zoom/share/geolocation helpers, precision marker-label hook, Leaflet controls, browser interaction, cleanup, and shared-open history behavior.
- Modify `static/js/main/boot.js`: parse `map=1` separately, exclude it from API filters, activate the requested map-compatible tab, then open the lazy Maps workspace.
- Modify `templates/partials/listing_map_workspace.html`: replace the three-line header with one semantic compact title/legend row.
- Modify `static/css/main/listing_map.css`: compact responsive header, visible mobile legend, Leaflet action buttons, location dot/accuracy circle, and in-map feedback.
- Modify `templates/index.html`: bump Listing Maps JS/CSS cache keys.
- Modify `tests/test_listing_map_js.py`: pure contracts for zoom 14, share URLs, geolocation errors/zoom, precision label class, and shared history URL cleanup.
- Modify `tests/test_listing_map_ui.py`: template/CSS/assets/boot integration contracts and targeted headless browser smoke coverage.

---

### Task 1: Zoom 14 and Precision-specific Singleton-road Labels

**Files:**
- Modify: `tests/test_listing_map_js.py:174-257`
- Modify: `static/js/main/listing_map.js:12-27, 243-286, 319-327, 1007-1018`

**Interfaces:**
- Consumes: existing `markerLabelModel(group, zoom)` and `closerInitialZoom(fittedZoom)`.
- Produces: `markerLabelClassName(group, model) -> string`, exported for tests; `INITIAL_MAP_MIN_ZOOM = 14`.

- [ ] **Step 1: Write failing tests for zoom 14 and road-label identity**

Update the zoom expectations and add the class contract:

```python
def test_closer_initial_zoom_opens_at_fourteen_with_cap():
    assert _run_node("mapApi.closerInitialZoom(8)") == 14
    assert _run_node("mapApi.closerInitialZoom(12)") == 14
    assert _run_node("mapApi.closerInitialZoom(13)") == 14
    assert _run_node("mapApi.closerInitialZoom(14)") == 15
    assert _run_node("mapApi.closerInitialZoom(15)") == 16
    assert _run_node("mapApi.closerInitialZoom(16)") == 16
    assert _run_node("mapApi.closerInitialZoom('broken')") == 14


def test_marker_label_class_identifies_singleton_road_price():
    result = _run_node(
        "(function(){const group={precision:'road',listing_count:1,"
        "price_ty:1.8,area_m2:100,price_per_m2:18};"
        "const model=mapApi.markerLabelModel(group,14);"
        "return mapApi.markerLabelClassName(group,model);})()"
    )
    assert result == (
        "listing-map-marker-label listing-map-marker-label-price "
        "listing-map-marker-label-precision-road"
    )
```

- [ ] **Step 2: Run the focused tests and confirm RED**

Run:

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $py -X utf8 -m pytest tests\test_listing_map_js.py -k "closer_initial_zoom or marker_label_class" -q
```

Expected: zoom assertions still return 13 and `markerLabelClassName` is not exported.

- [ ] **Step 3: Implement the minimum zoom and CSS-class helper**

In `listing_map.js`:

```javascript
var INITIAL_MAP_MIN_ZOOM = 14;

function markerLabelClassName(group, model) {
  var precision = group && group.precision === "nearby"
    ? "road"
    : String((group && group.precision) || "");
  return "listing-map-marker-label listing-map-marker-label-"
    + model.kind + " listing-map-marker-label-precision-" + precision;
}
```

Use `markerLabelClassName(group, model)` as the `L.divIcon` class name and export the helper. Do not change `PRICE_LABEL_MIN_ZOOM = 13` or `markerLabelModel` formatting.

- [ ] **Step 4: Run marker/zoom tests and confirm GREEN**

Run:

```powershell
& $py -X utf8 -m pytest tests\test_listing_map_js.py -k "marker_label or closer_initial_zoom" -q
node --check static\js\main\listing_map.js
```

Expected: all selected tests pass and Node syntax check exits 0.

- [ ] **Step 5: Commit Task 1**

```powershell
git add -- static/js/main/listing_map.js tests/test_listing_map_js.py
git commit -m "feat: open listing maps at zoom fourteen"
```

---

### Task 2: One-row Accessible Header with Persistent Mobile Legend

**Files:**
- Modify: `tests/test_listing_map_ui.py:28-70, 211-243`
- Modify: `templates/partials/listing_map_workspace.html:13-33`
- Modify: `static/css/main/listing_map.css:12-79, 488-503`

**Interfaces:**
- Consumes: the existing dialog `aria-labelledby="listingMapTitle"` and four precision classes.
- Produces: `.listing-map-head-main`, `.listing-map-title-detail`, and a non-wrapping `.listing-map-precision-legend` that remains visible at `max-width: 760px`.

- [ ] **Step 1: Write failing template and CSS tests**

Change the dashboard assertions to require:

```python
assert 'aria-labelledby="listingMapTitle"' in html
assert 'aria-describedby="listingMapDescription"' not in html
assert 'id="listingMapDescription"' not in html
assert 'class="listing-map-head-main"' in html
assert 'class="listing-map-title-detail"' in html
assert "Radar BĐS Maps" in html
for label in ("Chính xác", "Theo đường", "Theo khu vực", "Theo phường"):
    assert label in html
```

Add a CSS source assertion that the mobile block no longer places `.listing-map-precision-legend` in a `display: none` selector and includes `overflow-x: auto` and `flex-wrap: nowrap` for the legend.

- [ ] **Step 2: Run UI tests and confirm RED**

Run:

```powershell
& $py -X utf8 -m pytest tests\test_listing_map_ui.py -k "dashboard_renders or workspace_css" -q
```

Expected: stale description and hidden mobile legend assertions fail.

- [ ] **Step 3: Replace the header markup**

Use this semantic shape in `listing_map_workspace.html`:

```html
<section id="listingMapWorkspace" class="listing-map-workspace" hidden
  role="dialog" aria-modal="true" aria-labelledby="listingMapTitle">
  <header class="listing-map-workspace-head">
    <div class="listing-map-head-main">
      <h2 id="listingMapTitle">
        Radar BĐS Maps
        <span class="listing-map-title-detail">· Xem lô đất trên bản đồ</span>
      </h2>
      <div class="listing-map-precision-legend" aria-label="Chú giải độ chính xác vị trí">
        <!-- retain the existing four precision spans and Vietnamese labels -->
      </div>
    </div>
    <!-- retain listingMapClose unchanged -->
  </header>
```

Delete the eyebrow and description. Retain exact/road/landmark/ward legend markup unchanged.

- [ ] **Step 4: Implement compact responsive CSS**

Use a compact grid header:

```css
.listing-map-workspace-head {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  padding: 7px 12px;
}

.listing-map-head-main {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 14px;
}

.listing-map-precision-legend {
  flex: 1 1 auto;
  flex-wrap: nowrap;
  min-width: 0;
  margin: 0;
  overflow-x: auto;
  white-space: nowrap;
  scrollbar-width: none;
}
```

At `max-width: 760px`, hide `.listing-map-title-detail` only, keep the legend visible, reduce gaps/type/padding, and keep the close button at least 40×40 CSS pixels.

- [ ] **Step 5: Run UI tests and confirm GREEN**

Run:

```powershell
& $py -X utf8 -m pytest tests\test_listing_map_ui.py -k "dashboard_renders or workspace_css" -q
```

Expected: selected tests pass.

- [ ] **Step 6: Commit Task 2**

```powershell
git add -- templates/partials/listing_map_workspace.html static/css/main/listing_map.css tests/test_listing_map_ui.py
git commit -m "feat: compact listing map header"
```

---

### Task 3: In-map Current-location Control

**Files:**
- Modify: `tests/test_listing_map_js.py`
- Modify: `tests/test_listing_map_ui.py:171-230`
- Modify: `static/js/main/listing_map.js:27-59, 319-385, 698-750, 1513-1590, 1667-1690`
- Modify: `static/css/main/listing_map.css`

**Interfaces:**
- Consumes: Leaflet `L.Control`, `L.circleMarker`, `L.circle`, `state.map`, and browser `navigator.geolocation.getCurrentPosition`.
- Produces: `locationTargetZoom(currentZoom) -> number`, `geolocationErrorMessage(error) -> string`, `isCurrentLocationCallback(requestId, activeRequestId, isOpen, hasMap) -> boolean`, `mountMapActionControls(L)`, and `clearUserLocation()`.

- [ ] **Step 1: Write failing pure-helper tests**

Add:

```python
def test_current_location_zoom_never_zooms_out():
    assert _run_node("mapApi.locationTargetZoom(14)") == 16
    assert _run_node("mapApi.locationTargetZoom(16)") == 16
    assert _run_node("mapApi.locationTargetZoom(18)") == 18
    assert _run_node("mapApi.locationTargetZoom('broken')") == 16


def test_geolocation_errors_use_concise_vietnamese_copy():
    assert _run_node("mapApi.geolocationErrorMessage({code:1})") == "Bạn chưa cấp quyền vị trí."
    assert _run_node("mapApi.geolocationErrorMessage({code:2})") == "Không xác định được vị trí."
    assert _run_node("mapApi.geolocationErrorMessage({code:3})") == "Định vị quá thời gian, hãy thử lại."
    assert _run_node("mapApi.geolocationErrorMessage({code:99})") == "Không thể định vị lúc này."


def test_stale_or_closed_location_callbacks_are_rejected():
    assert _run_node("mapApi.isCurrentLocationCallback(4,4,true,true)") is True
    assert _run_node("mapApi.isCurrentLocationCallback(3,4,true,true)") is False
    assert _run_node("mapApi.isCurrentLocationCallback(4,4,false,true)") is False
    assert _run_node("mapApi.isCurrentLocationCallback(4,4,true,false)") is False
```

Update the UI source guard from a blanket `root.L.circle(` ban to require the accuracy-circle code and assert that `addMarker(group)` still creates listing markers only through `root.L.circleMarker`.

- [ ] **Step 2: Run geolocation tests and confirm RED**

Run:

```powershell
& $py -X utf8 -m pytest tests\test_listing_map_js.py -k "location or geolocation" -q
& $py -X utf8 -m pytest tests\test_listing_map_ui.py -k "history_focus_abort" -q
```

Expected: helpers are missing and the old circle guard conflicts with the new requirement.

- [ ] **Step 3: Add state and pure geolocation helpers**

Extend state with:

```javascript
userLocationMarker: null,
userAccuracyCircle: null,
locationButton: null,
locationRequestId: 0,
mapFeedbackTimer: null,
mapFeedbackElement: null
```

Implement the tested helpers exactly. `locationTargetZoom` returns `Math.max(validCurrentZoom || 0, 16)`.

- [ ] **Step 4: Add Leaflet control markup and request behavior**

Create one `L.Control.extend` at `position: "topleft"` whose container has two buttons. In this task, wire only the first button:

```javascript
button.type = "button";
button.className = "listing-map-control-button listing-map-locate-button";
button.title = "Vị trí của tôi";
button.setAttribute("aria-label", "Vị trí của tôi");
button.innerHTML = '<span aria-hidden="true">⌖</span>';
```

Disable click/scroll propagation through Leaflet utilities. On click:

```javascript
root.navigator.geolocation.getCurrentPosition(onSuccess, onError, {
  enableHighAccuracy: true,
  timeout: 10000,
  maximumAge: 0
});
```

Use an incremented request ID. Success validates finite latitude/longitude, replaces the existing blue `L.circleMarker`, replaces the translucent `L.circle` using normalized accuracy, calls `setView([lat, lng], locationTargetZoom(state.map.getZoom()))`, and restores the button. Error displays the tested message and restores the button. Both callbacks must first call `isCurrentLocationCallback`.

- [ ] **Step 5: Add map feedback and cleanup**

Mount a polite `.listing-map-feedback` element inside the control container. `showMapFeedback(message, kind)` clears its previous timer, sets text/state, and hides it after 2500 ms.

`clearUserLocation()` increments `locationRequestId`, removes both layers if the map exists, nulls their state, clears the timer, and removes the feedback element reference. Call it before `state.map.remove()` in `close()` and before replacing an existing map in `initMap()`.

- [ ] **Step 6: Style control, position dot, accuracy circle, and feedback**

Add Leaflet-compatible 34×34 buttons, a two-button vertical stack, visible focus/disabled states, blue location marker styling, translucent accuracy fill, and a compact feedback bubble that expands to the right without blocking the zoom control.

- [ ] **Step 7: Run Task 3 tests and confirm GREEN**

Run:

```powershell
& $py -X utf8 -m pytest tests\test_listing_map_js.py -k "location or geolocation" -q
& $py -X utf8 -m pytest tests\test_listing_map_ui.py -k "history_focus_abort or workspace_css" -q
node --check static\js\main\listing_map.js
```

Expected: all selected tests pass.

- [ ] **Step 8: Commit Task 3**

```powershell
git add -- static/js/main/listing_map.js static/css/main/listing_map.css tests/test_listing_map_js.py tests/test_listing_map_ui.py
git commit -m "feat: add listing map location control"
```

---

### Task 4: Share URL, Shared Startup, and History Preservation

**Files:**
- Modify: `tests/test_listing_map_js.py`
- Modify: `tests/test_listing_map_ui.py`
- Modify: `static/js/main/listing_map.js:140-190, 698-750, 1470-1590, 1667-1690`
- Modify: `static/js/main/boot.js:55-150`
- Modify: `static/js/main/core.js:190-216`

**Interfaces:**
- Consumes: `snapshot = {mode: "signals"|"all", query: string}`, `getListingMapFilterSnapshot()`, `warmListingMapAssets()`, and the Task 3 two-button Leaflet control.
- Produces: `buildMapShareUrl(snapshot, currentHref) -> string|null`, `urlWithoutMapFlag(currentHref) -> string`, `open(snapshot, {initialSharedOpen:true})`, and `lazyOpenListingMap({initialSharedOpen:true})`.

- [ ] **Step 1: Write failing share-URL and URL-cleanup tests**

Add:

```python
def test_share_url_preserves_tab_and_repeated_filters_without_private_state():
    url = _run_node(
        "mapApi.buildMapShareUrl({mode:'all',query:"
        "'city=D%C4%A8+AN&ward=T%C3%A2n+%C4%90%C3%B4ng+Hi%E1%BB%87p&"
        "ward=B%C3%ACnh+An&prop_type=dat_nen&page=2&limit=50&lat=11.1'},"
        "'https://radarbds.vn/?utm_source=test#section')"
    )
    assert url.startswith("https://radarbds.vn/?")
    assert "tab=all" in url and "map=1" in url
    assert url.count("ward=") == 2
    assert "prop_type=dat_nen" in url
    for forbidden in ("page=", "limit=", "lat=", "lng=", "accuracy=", "zoom=", "location_key="):
        assert forbidden not in url
    assert "#" not in url


def test_removing_map_flag_preserves_dashboard_state():
    result = _run_node(
        "mapApi.urlWithoutMapFlag('https://radarbds.vn/?tab=signals&ward=Ph%C3%BA+T%C3%A2n&map=1')"
    )
    assert result == "https://radarbds.vn/?tab=signals&ward=Ph%C3%BA+T%C3%A2n"
```

- [ ] **Step 2: Write failing boot integration tests**

In `test_listing_map_ui.py`, assert source contracts:

```python
assert "const shouldOpenListingMap = searchParams.get('map') === '1';" in boot
assert "searchParams.delete('map');" in boot
assert "initialSharedOpen: true" in boot
assert "async function lazyOpenListingMap(options = {})" in core
assert "window.RadarListingMap.open(snapshot, options)" in core
```

Also assert the map script contains `root.history.replaceState` for shared close and still contains the existing normal `pushState`/`back()` path.

- [ ] **Step 3: Run Task 4 tests and confirm RED**

Run:

```powershell
& $py -X utf8 -m pytest tests\test_listing_map_js.py -k "share_url or removing_map" -q
& $py -X utf8 -m pytest tests\test_listing_map_ui.py -k "startup or history" -q
```

Expected: URL helpers and boot contracts are absent.

- [ ] **Step 4: Implement safe share URL helpers**

In `listing_map.js`, implement:

```javascript
var SHARE_EXCLUDED_PARAMS = [
  "page", "limit", "include_total", "sort_by", "sort_dir",
  "location_key", "lat", "lng", "accuracy", "zoom", "center",
  "marker", "selected"
];

function buildMapShareUrl(snapshot, currentHref) {
  var safe = normalizedSnapshot(snapshot);
  if (!safe) return null;
  var url = new URL(currentHref);
  var params = new URLSearchParams(safe.query);
  SHARE_EXCLUDED_PARAMS.forEach(function (key) { params.delete(key); });
  params.set("tab", safe.mode);
  params.set("map", "1");
  url.search = params.toString();
  url.hash = "";
  return url.toString();
}

function urlWithoutMapFlag(currentHref) {
  var url = new URL(currentHref);
  url.searchParams.delete("map");
  return url.toString();
}
```

Export both helpers.

- [ ] **Step 5: Wire the share control with native-share and clipboard fallback**

Wire the second Task 3 button with `title`/`aria-label` `Chia sẻ`. Build the URL from `state.snapshot` and `root.location.href`.

```javascript
if (root.navigator.share) {
  root.navigator.share({ title: "Radar BĐS Maps", url: shareUrl })
    .catch(function (error) {
      if (!error || error.name !== "AbortError") showMapFeedback("Không thể chia sẻ, hãy thử lại.", "error");
    });
  return;
}
copyShareUrl(shareUrl).then(function () {
  showMapFeedback("Đã sao chép", "success");
}).catch(function () {
  showMapFeedback("Không thể sao chép, hãy thử lại.", "error");
});
```

`copyShareUrl` first uses `navigator.clipboard.writeText`; its fallback appends a readonly off-screen textarea, selects it, calls `document.execCommand("copy")`, and removes it in `finally`.

- [ ] **Step 6: Pass shared-open options through the lazy loader**

Change `core.js` to:

```javascript
async function lazyOpenListingMap(options = {}) {
  const snapshot = getListingMapFilterSnapshot();
  if (!snapshot) return;
  await warmListingMapAssets();
  return window.RadarListingMap.open(snapshot, options);
}
```

Keep normal launcher calls with no options.

- [ ] **Step 7: Parse `map=1` before API filter construction and open after hydration**

In `boot.js`, immediately after constructing `searchParams`:

```javascript
const shouldOpenListingMap = searchParams.get('map') === '1';
searchParams.delete('map');
```

Retain `tab` long enough to select the initial tab, then remove it from filter queries as today. After the filter application and tab scheduling logic, schedule a single async opener only when `initialTab` is `signals` or `all`:

```javascript
if (shouldOpenListingMap && ['signals', 'all'].includes(initialTab)) {
  window.setTimeout(async () => {
    if (initialTab !== 'signals') switchTab(initialTab, null);
    await window.openListingMap({ initialSharedOpen: true });
  }, 0);
}
```

Avoid the existing separate `requestAnimationFrame` tab switch in this branch so the map snapshot cannot capture the wrong tab.

- [ ] **Step 8: Implement shared-open history state**

Extend state with `initialSharedOpen: false`. In `open()`:

```javascript
state.initialSharedOpen = Boolean(options.initialSharedOpen);
if (!options.fromPopstate && !state.initialSharedOpen) {
  root.history.pushState({ radarListingMap: true }, "", root.location.href);
  state.historyPushed = true;
}
```

In `close()`, capture the flag before clearing state. If shared-open and not a popstate/replace close, call:

```javascript
root.history.replaceState(
  root.history.state,
  "",
  urlWithoutMapFlag(root.location.href)
);
```

Do not call `history.back()` in that branch. Reset `initialSharedOpen` during cleanup. Normal dashboard open/close retains its current `pushState` then `back()` contract.

- [ ] **Step 9: Run Task 4 tests and confirm GREEN**

Run:

```powershell
& $py -X utf8 -m pytest tests\test_listing_map_js.py -k "share_url or removing_map or popstate" -q
& $py -X utf8 -m pytest tests\test_listing_map_ui.py -k "startup or history or launcher_contract" -q
node --check static\js\main\listing_map.js
node --check static\js\main\boot.js
node --check static\js\main\core.js
```

Expected: selected tests and all syntax checks pass.

- [ ] **Step 10: Commit Task 4**

```powershell
git add -- static/js/main/listing_map.js static/js/main/boot.js static/js/main/core.js tests/test_listing_map_js.py tests/test_listing_map_ui.py
git commit -m "feat: share filtered listing map views"
```

---

### Task 5: Asset Version, Full Regression, Browser Verification, and Production Release

**Files:**
- Modify: `templates/index.html:106,113`
- Modify: `tests/test_listing_map_ui.py:65-68, 238-243`
- Verify only: all files from Tasks 1-4

**Interfaces:**
- Consumes: completed UI/JS/CSS feature and standard `scripts/deploy_production.ps1` workflow.
- Produces: cache-busted production assets and documented local/production evidence.

- [ ] **Step 1: Write the failing asset-key assertions**

Replace the previous key checks with:

```python
assert html.count("listing-map-location-share-20260813") == 2
assert "listing-map-price-zoom-20260813" not in html
assert "listing-map-compact-labels-20260813" not in html
```

- [ ] **Step 2: Run the asset test and confirm RED**

Run:

```powershell
& $py -X utf8 -m pytest tests\test_listing_map_ui.py -k "dashboard_renders or cache_busting" -q
```

Expected: old keys are still rendered.

- [ ] **Step 3: Bump both asset keys**

In `templates/index.html`, use `listing-map-location-share-20260813` for both `listingMap` JS and CSS URLs.

- [ ] **Step 4: Run the complete focused suite**

Run:

```powershell
node --check static\js\main\listing_map.js
node --check static\js\main\boot.js
node --check static\js\main\core.js
& $py -X utf8 -m pytest tests\test_listing_map_js.py tests\test_listing_map_ui.py tests\test_listing_map_service.py tests\test_listing_map_api.py tests\test_listing_map_context.py -q
git diff --check
```

Expected: syntax checks exit 0, all focused tests pass, and `git diff --check` reports no whitespace errors.

- [ ] **Step 5: Start and verify the local application**

Use the documented local Python and PostgreSQL configuration. Start `app.py` only if no verified listener is already serving the current checkout, then verify:

```powershell
Invoke-WebRequest http://127.0.0.1:5000/ -UseBasicParsing | Select-Object StatusCode
```

Expected: HTTP 200 from the current checkout.

- [ ] **Step 6: Verify desktop browser behavior**

At a desktop viewport, exercise Săn Deal and Tin rao separately. Record evidence that:

- initial Leaflet zoom is 14 or closer;
- header is one row and all four legends are visible;
- controls are under `+`/`−` in locate-then-share order;
- a known `.listing-map-marker-label-precision-road.listing-map-marker-label-price` contains two rows with price/area and price/m²;
- stubbed geolocation success adds exactly one dot and one accuracy circle, then recenters at zoom 16 or closer;
- denied geolocation displays `Bạn chưa cấp quyền vị trí.` without closing Maps;
- share/copy URL contains the active tab, filters, and `map=1`, but no coordinates.

- [ ] **Step 7: Verify mobile browser behavior**

At approximately 390×844 CSS pixels, repeat Săn Deal and Tin rao checks and verify:

- `Radar BĐS Maps`, all four horizontally scrollable legends, and close button remain visible;
- header does not wrap into a tall block;
- locate/share controls remain tappable and do not overlap the mobile sheet;
- shared URL opens Maps with the correct tab/filter snapshot;
- closing Maps removes `map=1` and leaves the same dashboard tab/filters;
- opening and closing a listing modal returns to the same Maps workspace.

- [ ] **Step 8: Commit the asset bump and any browser-test-only fixes**

```powershell
git add -- templates/index.html tests/test_listing_map_ui.py
git commit -m "test: verify listing map location and sharing"
```

- [ ] **Step 9: Run verification-before-completion and inspect scope**

Run:

```powershell
git status --short --branch
git diff origin/main...HEAD --stat
git log --oneline origin/main..HEAD
```

Confirm only the spec, plan, named source files, and focused tests are committed. Confirm `.playwright-cli/` remains untracked and unstaged.

- [ ] **Step 10: Push main and deploy production**

```powershell
git push origin main
.\scripts\deploy_production.ps1
```

Expected: remote `main` advances to the local HEAD; deployment reports the service active and the standard public smoke checks pass. Report optional privileged systemd steps separately if they are skipped.

- [ ] **Step 11: Verify production independently**

Verify all of the following as separate evidence:

- `git rev-parse HEAD` equals `git rev-parse origin/main`;
- `https://radarbds.vn/` returns HTTP 200 and references `listing-map-location-share-20260813`;
- the versioned JS and CSS URLs return HTTP 200;
- production desktop and mobile reproduce the local zoom/header/control/share/history behavior;
- current-location denial does not break Maps; use a browser geolocation override for deterministic success rather than exposing a real personal position.

If any production UI check serves stale assets, verify origin and a unique-query public request before declaring a code regression.
