# Listing Maps Marker Touch Target Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enlarge listing markers progressively at close zoom and let users open a location group by clicking or tapping either its colored marker or its visible price/count label.

**Architecture:** Keep the existing Leaflet `circleMarker` and collision-filtered `DivIcon` label layers. Add a pure zoom-aware radius helper plus a `zoomend` refresh for existing circles, then make only rendered labels interactive and route their clicks through the existing `selectGroup(group)` path.

**Tech Stack:** Vanilla JavaScript, Leaflet 1.9.4, CSS, pytest contract tests, Node syntax checking, Playwright/Chrome browser smoke.

## Global Constraints

- Base radii remain exact/road 6, landmark 7 and ward 8.
- Zoom 14–15 adds 0, zoom 16–17 adds 1 and zoom 18–19 adds 2.
- Colors, border weights, marker hierarchy, label content, label collision rules and default zoom remain unchanged.
- The selectable area is the union of the colored marker and each visible label; do not add an invisible hit circle.
- A collision-hidden label must not intercept map interaction.
- Label selection must use the existing group panel/bottom-sheet flow and must not add navigation or a modal.
- Admin marker editing, APIs, database schema and location registry data are out of scope.

---

## File Structure

- `static/js/main/listing_map.js`: calculate radius by precision/zoom, refresh existing circle radii, and bind label clicks to group selection.
- `static/css/main/listing_map.css`: enable pointer interaction and a pointer cursor on rendered labels.
- `templates/index.html`: cache-bust both Maps JS and CSS with one shared version token.
- `tests/test_listing_map_js.py`: unit-test the zoom radius function.
- `tests/test_listing_map_ui.py`: enforce label interaction, zoom refresh, CSS and cache-bust contracts.

---

### Task 1: Progressive marker sizing

**Files:**
- Modify: `static/js/main/listing_map.js:17-27,915-950,1238-1243,1945-1974,2685-2705`
- Test: `tests/test_listing_map_js.py:365-383`
- Test: `tests/test_listing_map_ui.py:228-246`

**Interfaces:**
- Consumes: `precision` values `exact|road|landmark|ward` and Leaflet map zoom numbers.
- Produces: `markerRadius(precision, zoom) -> number`; `markerStyle(precision, zoom) -> object`; internal `refreshMarkerRadii() -> void`.

- [ ] **Step 1: Write the failing radius unit test**

Replace the fixed-radius test with explicit base and close-zoom assertions:

```python
def test_map_marker_radius_grows_progressively_at_close_zoom():
    assert _run_node("mapApi.markerRadius('exact',14)") == 6
    assert _run_node("mapApi.markerRadius('road',15)") == 6
    assert _run_node("mapApi.markerRadius('landmark',14)") == 7
    assert _run_node("mapApi.markerRadius('ward',14)") == 8

    assert _run_node("mapApi.markerRadius('exact',16)") == 7
    assert _run_node("mapApi.markerRadius('road',17)") == 7
    assert _run_node("mapApi.markerRadius('landmark',16)") == 8
    assert _run_node("mapApi.markerRadius('ward',17)") == 9

    assert _run_node("mapApi.markerRadius('exact',18)") == 8
    assert _run_node("mapApi.markerRadius('road',19)") == 8
    assert _run_node("mapApi.markerRadius('landmark',18)") == 9
    assert _run_node("mapApi.markerRadius('ward',19)") == 10

    assert _run_node("mapApi.markerStyle('exact',18).radius") == 8
    assert _run_node("mapApi.markerStyle('ward',16).weight") == 2
```

- [ ] **Step 2: Write the failing zoom-refresh contract test**

Add this source-level contract to `tests/test_listing_map_ui.py`:

```python
def test_listing_map_refreshes_existing_marker_radii_after_zoom():
    script = Path("static/js/main/listing_map.js").read_text(encoding="utf-8")
    refresh_source = script.split(
        "function refreshMarkerRadii()", 1
    )[1].split("function activateBaseLayer", 1)[0]
    add_marker_source = script.split("function addMarker(group)", 1)[1].split(
        "function setSummaryStatus", 1
    )[0]

    assert "state.markerLayer.eachLayer" in refresh_source
    assert "layer.setRadius(markerRadius(layer._radarPrecision, zoom))" in refresh_source
    assert 'state.map.on("zoomend", function () {' in script
    assert "refreshMarkerRadii();" in script
    assert "marker._radarPrecision = group.precision;" in add_marker_source
```

- [ ] **Step 3: Run the two tests and verify RED**

Run:

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $py -X utf8 -m pytest `
  tests\test_listing_map_js.py::test_map_marker_radius_grows_progressively_at_close_zoom `
  tests\test_listing_map_ui.py::test_listing_map_refreshes_existing_marker_radii_after_zoom -q
```

Expected: FAIL because `markerRadius` is not exported/defined and `refreshMarkerRadii` is absent.

- [ ] **Step 4: Implement the pure radius helper and use it in marker styles**

Add near the marker constants:

```javascript
var CLOSE_MARKER_MEDIUM_ZOOM = 16;
var CLOSE_MARKER_HIGH_ZOOM = 18;
```

Add before `markerStyle`:

```javascript
function markerRadius(precision, zoom) {
  var base = precision === "landmark" ? 7 : (precision === "ward" ? 8 : 6);
  var safeZoom = finiteNumber(zoom);
  var bonus = safeZoom !== null && safeZoom >= CLOSE_MARKER_HIGH_ZOOM
    ? 2
    : (safeZoom !== null && safeZoom >= CLOSE_MARKER_MEDIUM_ZOOM ? 1 : 0);
  return base + bonus;
}
```

Change `markerStyle` to accept `zoom` and use the helper for every precision:

```javascript
function markerStyle(precision, zoom) {
  var radius = markerRadius(precision, zoom);
  // Preserve the current color, weight, fillColor and fillOpacity branches.
  // Each branch returns `radius: radius`.
}
```

Export `markerRadius` beside `markerStyle` in the module return object.

- [ ] **Step 5: Refresh existing circle radii on zoom**

Add before `activateBaseLayer`:

```javascript
function refreshMarkerRadii() {
  if (!state.map || !state.markerLayer) return;
  var zoom = state.map.getZoom();
  state.markerLayer.eachLayer(function (layer) {
    if (!layer || typeof layer.setRadius !== "function") return;
    layer.setRadius(markerRadius(layer._radarPrecision, zoom));
  });
}
```

In `addMarker`, pass the current zoom and retain the precision on the layer:

```javascript
var marker = root.L.circleMarker(
  [lat, lng],
  markerStyle(group.precision, state.map && state.map.getZoom())
);
marker._radarPrecision = group.precision;
```

Replace the combined map event registration with:

```javascript
state.map.on("zoomend", function () {
  refreshMarkerRadii();
  scheduleMarkerLabelRefresh();
});
state.map.on("moveend", scheduleMarkerLabelRefresh);
```

- [ ] **Step 6: Run focused and regression tests**

Run:

```powershell
& $py -X utf8 -m pytest tests\test_listing_map_js.py tests\test_listing_map_ui.py -q
```

Expected: PASS, including the existing precision color/hierarchy assertions.

- [ ] **Step 7: Commit Task 1**

```powershell
git add static/js/main/listing_map.js tests/test_listing_map_js.py tests/test_listing_map_ui.py
git commit -m "ui: scale map markers at close zoom"
```

---

### Task 2: Make rendered labels click and touch targets

**Files:**
- Modify: `static/js/main/listing_map.js:1878-1928`
- Modify: `static/css/main/listing_map.css:232-243`
- Modify: `templates/index.html:106,113`
- Test: `tests/test_listing_map_ui.py:255-310`

**Interfaces:**
- Consumes: existing `selectGroup(group)` and collision-approved label candidates.
- Produces: an interactive Leaflet label marker whose click/tap invokes `selectGroup(group)` without bubbling to an unrelated map click.

- [ ] **Step 1: Write the failing label interaction contract test**

Add to `tests/test_listing_map_ui.py`:

```python
def test_rendered_map_labels_are_clickable_group_targets():
    script = Path("static/js/main/listing_map.js").read_text(encoding="utf-8")
    styles = Path("static/css/main/listing_map.css").read_text(encoding="utf-8")
    refresh_source = script.split("function refreshMarkerLabels()", 1)[1].split(
        "function scheduleMarkerLabelRefresh", 1
    )[0]

    assert "var labelMarker = root.L.marker" in refresh_source
    assert "interactive: true" in refresh_source
    assert "keyboard: false" in refresh_source
    assert "bubblingMouseEvents: false" in refresh_source
    assert 'labelMarker.on("click", function () {' in refresh_source
    assert "selectGroup(group);" in refresh_source
    assert re.search(
        r"\.listing-map-marker-label\s*\{[^}]*pointer-events:\s*auto",
        styles,
        re.S,
    )
    assert re.search(
        r"\.listing-map-marker-label\s*\{[^}]*cursor:\s*pointer",
        styles,
        re.S,
    )
```

- [ ] **Step 2: Update both rendered-HTML and source asset-version assertions**

In `test_dashboard_renders_lazy_accessible_map_launcher_and_workspace` and
`test_listing_map_assets_use_current_location_share_cache_version`, replace:

```python
assert template.count("listing-map-marker-hierarchy-20260814") == 2
```

with:

```python
assert template.count("listing-map-touch-target-20260814") == 2
assert "listing-map-marker-hierarchy-20260814" not in template
```

Use `html.count(...)` and `not in html` in the rendered-dashboard test, matching
its existing variable name.

- [ ] **Step 3: Run the tests and verify RED**

Run:

```powershell
& $py -X utf8 -m pytest `
  tests\test_listing_map_ui.py::test_rendered_map_labels_are_clickable_group_targets `
  tests\test_listing_map_ui.py::test_dashboard_renders_lazy_accessible_map_launcher_and_workspace `
  tests\test_listing_map_ui.py::test_listing_map_assets_use_current_location_share_cache_version -q
```

Expected: FAIL because label markers are still non-interactive, CSS still disables pointer events, and the asset token is unchanged.

- [ ] **Step 4: Make only rendered labels interactive**

In `refreshMarkerLabels`, replace the anonymous non-interactive marker creation with:

```javascript
var labelMarker = root.L.marker([lat, lng], {
  interactive: true,
  keyboard: false,
  bubblingMouseEvents: false,
  zIndexOffset: 1000,
  icon: root.L.divIcon({
    className: markerLabelClassName(group, model),
    html: markerLabelHtml(model),
    iconSize: [model.width, model.height],
    iconAnchor: [model.width / 2, model.anchorY]
  })
});
labelMarker.on("click", function () {
  selectGroup(group);
});
labelMarker.addTo(state.markerLabelLayer);
```

This attaches no handler for collision-rejected labels because no Leaflet marker
is created for those candidates.

- [ ] **Step 5: Enable label pointer interaction without changing label dimensions**

In `.listing-map-marker-label`, replace `pointer-events: none` and add the cursor:

```css
pointer-events: auto;
cursor: pointer;
```

Do not alter the 92x30 price label, 44x18 count label, fonts, anchors or collision gap.

- [ ] **Step 6: Cache-bust Maps JS and CSS together**

Change both `RADAR_ASSETS.listingMap` and `RADAR_STYLES.listingMap` in
`templates/index.html` to:

```text
listing-map-touch-target-20260814
```

- [ ] **Step 7: Run focused Maps verification**

Run:

```powershell
& $py -X utf8 -m pytest `
  tests\test_listing_map_js.py `
  tests\test_listing_map_ui.py `
  tests\test_listing_map_service.py `
  tests\test_listing_map_api.py -q
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -X utf8 -m py_compile app.py services\listing_map.py
node --check static\js\main\listing_map.js
git diff --check
```

Expected: all pytest tests PASS; py_compile, Node and diff checks exit 0.

- [ ] **Step 8: Browser-test desktop and mobile before release**

Start the production-shaped local app with the configured `.env.local` and
verify the listener before opening Chrome/Playwright:

```powershell
$server = Start-Process $py `
  -ArgumentList "-X", "utf8", "app.py" `
  -WorkingDirectory (Get-Location).Path `
  -WindowStyle Hidden `
  -PassThru
for ($attempt = 0; $attempt -lt 30; $attempt++) {
  try {
    $health = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:5000/"
    if ($health.StatusCode -eq 200) { break }
  } catch {}
  Start-Sleep -Milliseconds 500
}
if (-not $health -or $health.StatusCode -ne 200) {
  Stop-Process -Id $server.Id -ErrorAction SilentlyContinue
  throw "Local Radar BDS did not become healthy"
}
```

Use Chrome/Playwright at 1440x900 and 390x844. For each viewport:

1. Open the Signals tab and click `Xem trên Maps`.
2. At zoom 14, record an exact/road marker diameter.
3. At zoom 16 and 18, confirm its radius increases by one and two pixels.
4. Click the colored marker and confirm the group items view opens.
5. Return to the map directory, click the visible price/count label, and confirm
   the same group items view opens.
6. Pan across an area where labels collide and confirm the map remains draggable.
7. Close Maps and confirm the Signals tab and viewport state remain intact.

Expected: both viewports meet all seven checks with no console error.

After the browser checks, stop only the process started above:

```powershell
Stop-Process -Id $server.Id
```

- [ ] **Step 9: Commit Task 2**

```powershell
git add static/js/main/listing_map.js static/css/main/listing_map.css templates/index.html tests/test_listing_map_ui.py
git commit -m "ui: make map labels easier to tap"
```

---

### Task 3: Release and production proof

**Files:**
- No source changes expected.
- Verify: Git state, production checkout, service, Maps APIs and rendered browser behavior.

**Interfaces:**
- Consumes: the two implementation commits from Tasks 1 and 2.
- Produces: pushed `main`, deployed production SHA, HTTP/API/browser evidence.

- [ ] **Step 1: Re-run the release gate from a clean implementation diff**

```powershell
& $py -X utf8 -m pytest tests\test_listing_map_js.py tests\test_listing_map_ui.py tests\test_listing_map_service.py tests\test_listing_map_api.py -q
node --check static\js\main\listing_map.js
git diff --check
git status --short
```

Expected: checks pass and only the pre-existing untracked `.playwright-cli/`
directory remains outside committed work.

- [ ] **Step 2: Push and deploy**

```powershell
git push origin main
.\scripts\deploy_production.ps1
```

Expected: `origin/main` and `/opt/radar-bds/current` resolve to the same new SHA;
`radar-bds` is active. Optional sudo/systemd installer skips are reported
separately and do not substitute for service verification.

- [ ] **Step 3: Smoke public APIs and browser UI**

Verify:

```powershell
Invoke-WebRequest -UseBasicParsing "https://radarbds.vn/api/map-listings?mode=signals"
Invoke-WebRequest -UseBasicParsing "https://radarbds.vn/api/map-listings?mode=all&complete=1"
Invoke-WebRequest -UseBasicParsing "https://radarbds.vn/?verify=listing-map-touch-target-20260814"
```

Expected: all return HTTP 200. In a fresh public browser session at desktop and
mobile widths, repeat Task 2 Step 8 for zoom 14/16/18 and both marker/label
selection paths. Confirm the loaded JS/CSS URLs contain
`listing-map-touch-target-20260814`.

- [ ] **Step 4: Record final delivery evidence**

Report local, origin and production SHA separately; focused test results; API
HTTP statuses; desktop/mobile marker radius measurements; label-click behavior;
service status; and any optional deploy warnings. Do not claim authenticated
admin behavior was tested because this feature does not modify it.
