# Listing Maps Minimum Price Zoom Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Listing Maps open at zoom 13 or closer so valid compact price labels are eligible immediately, even when some filtered markers fall outside the initial viewport.

**Architecture:** Preserve the current `fitBounds` center calculation and change only the pure post-fit zoom helper to clamp the result to the inclusive range 13–16. Keep label eligibility, collision placement, marker grouping, APIs, and the empty-dataset fallback unchanged. Cache-bust only the Listing Maps JavaScript asset.

**Tech Stack:** Vanilla JavaScript, Leaflet, Flask/Jinja asset configuration, pytest with Node subprocess tests, Browser Use.

## Global Constraints

- The initial zoom rule is exactly `min(max(fitted zoom + 1, 13), 16)`.
- Apply the same behavior to Săn Deal and Tin rao on desktop and mobile.
- Markers outside the initial viewport are intentionally allowed.
- Keep `PRICE_LABEL_MIN_ZOOM = 13` unchanged.
- Keep the empty-dataset fallback view unchanged.
- Do not change APIs, registry data, marker grouping, modal behavior, label content, or collision priority.
- Preserve unrelated `.playwright-cli/` work.

---

### Task 1: Clamp the post-fit zoom to the price-label threshold

**Files:**
- Modify: `tests/test_listing_map_js.py:249-253`
- Modify: `static/js/main/listing_map.js:27-28,318-322`

**Interfaces:**
- Consumes: `closerInitialZoom(fittedZoom: number | string): number`, called after Leaflet `fitBounds` and exported for Node tests.
- Produces: the same helper signature, returning an integer/number between 13 and 16 inclusive.

- [ ] **Step 1: Replace the zoom-helper expectations with the approved clamp matrix**

Update the test to this behavior:

```python
def test_closer_initial_zoom_reaches_price_label_threshold_with_cap():
    assert _run_node("mapApi.closerInitialZoom(8)") == 13
    assert _run_node("mapApi.closerInitialZoom(11)") == 13
    assert _run_node("mapApi.closerInitialZoom(12)") == 13
    assert _run_node("mapApi.closerInitialZoom(13)") == 14
    assert _run_node("mapApi.closerInitialZoom(15)") == 16
    assert _run_node("mapApi.closerInitialZoom(16)") == 16
    assert _run_node("mapApi.closerInitialZoom('broken')") == 13
```

- [ ] **Step 2: Run the targeted test to verify RED**

Run:

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -X utf8 -m pytest tests\test_listing_map_js.py::test_closer_initial_zoom_reaches_price_label_threshold_with_cap -q
```

Expected: failures for fitted zoom 8, 11, 12, and invalid input because the current helper returns values below 13.

- [ ] **Step 3: Implement the minimum zoom clamp**

Add a named minimum next to the existing maximum:

```javascript
var INITIAL_MAP_MIN_ZOOM = PRICE_LABEL_MIN_ZOOM;
var INITIAL_MAP_MAX_ZOOM = 16;
```

Replace the helper with:

```javascript
function closerInitialZoom(fittedZoom) {
  var zoom = finiteNumber(fittedZoom);
  if (zoom === null) return INITIAL_MAP_MIN_ZOOM;
  return Math.min(
    Math.max(zoom + 1, INITIAL_MAP_MIN_ZOOM),
    INITIAL_MAP_MAX_ZOOM
  );
}
```

Do not modify the `fitBounds`, `setZoom`, or empty fallback call sites.

- [ ] **Step 4: Run the focused JavaScript suite to verify GREEN**

Run:

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -X utf8 -m pytest tests\test_listing_map_js.py -q
node --check static\js\main\listing_map.js
```

Expected: all Listing Maps JavaScript tests pass and Node syntax validation exits 0.

- [ ] **Step 5: Commit the behavior change**

```powershell
git add static/js/main/listing_map.js tests/test_listing_map_js.py
git commit -m "fix: open listing maps at price zoom"
```

### Task 2: Cache-bust, verify, and release

**Files:**
- Modify: `templates/index.html:106`
- Modify: `tests/test_listing_map_ui.py`

**Interfaces:**
- Consumes: Jinja `RadarAssets.js.listingMap` URL used by the lazy Maps loader.
- Produces: a new versioned Listing Maps JavaScript URL containing `listing-map-price-zoom-20260813`.

- [ ] **Step 1: Write the failing asset-version assertion**

Update the Listing Maps asset test so it requires:

```python
assert "listing-map-price-zoom-20260813" in template
assert "listing-map-compact-labels-20260813" in template
```

The compact-label token remains required for CSS; the new price-zoom token is required for JavaScript.

- [ ] **Step 2: Run the targeted UI test to verify RED**

Run:

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -X utf8 -m pytest tests\test_listing_map_ui.py -q
```

Expected: the new JavaScript asset-version assertion fails.

- [ ] **Step 3: Bump only the Listing Maps JavaScript asset version**

Change the JavaScript URL in `templates/index.html` to:

```jinja2
listingMap: "{{ url_for('static', filename='js/main/listing_map.js') }}?v=listing-map-price-zoom-20260813"
```

Keep the Listing Maps CSS version at `listing-map-compact-labels-20260813` because CSS is unchanged.

- [ ] **Step 4: Run the full focused gate**

Run:

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -X utf8 -m pytest tests\test_listing_map_service.py tests\test_listing_map_js.py tests\test_listing_map_ui.py -q
node --check static\js\main\listing_map.js
git diff --check
```

Expected: all focused tests pass, JavaScript syntax is valid, and no whitespace errors are reported.

- [ ] **Step 5: Verify local browser behavior**

Start the local app with `.env` and `.env.local` loaded into the process without printing secrets. With Browser Use, verify Săn Deal and Tin rao at desktop and 390×844 mobile viewports:

- Maps opens with a non-zero canvas;
- the initial Leaflet tile zoom is at least 13;
- at least one valid `.listing-map-marker-label-price` is present without clicking the zoom control;
- compact count labels and modal-over-Maps behavior remain intact.

- [ ] **Step 6: Commit the cache-bust**

```powershell
git add templates/index.html tests/test_listing_map_ui.py
git commit -m "chore: refresh listing map zoom asset"
```

- [ ] **Step 7: Push and deploy**

```powershell
git push origin main
.\scripts\deploy_production.ps1
```

Expected: `origin/main` advances to the local SHA and the deploy script reports the service `active` plus the deployed old/new SHA pair. Report password-gated optional systemd steps separately.

- [ ] **Step 8: Verify production HTTP, API, and browser behavior**

Use a unique query parameter and verify:

- `https://radarbds.vn/` returns HTTP 200 and references `listing-map-price-zoom-20260813`;
- the versioned `listing_map.js` returns HTTP 200 and contains `INITIAL_MAP_MIN_ZOOM`;
- desktop and mobile Săn Deal/Tin rao Maps open at zoom 13 or closer;
- price labels appear without manual zoom;
- opening and closing a listing modal preserves the Maps workspace.

- [ ] **Step 9: Refresh Graphify and clean the isolated worktree**

Run `graphify update .` from the main checkout after the code is merged. Remove only the worktree created for this plan and its merged local feature branch; preserve `.playwright-cli/` and every unrelated worktree.
