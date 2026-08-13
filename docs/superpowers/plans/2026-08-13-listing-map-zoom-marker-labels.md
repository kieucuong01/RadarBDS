# Listing Maps Closer Zoom and Compact Marker Labels Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make Listing Maps open one zoom level closer and show compact, collision-aware labels for exact, road, landmark, and ward markers according to listing count.

**Architecture:** Keep the existing Leaflet marker grouping and collision pipeline, but generalize the exact-marker label model into a shared marker-label model. Extend the map summary payload so a singleton road group receives the same price fields as a singleton exact group. The client then selects either a two-row price label or a small count badge from precision, listing count, and zoom.

**Tech Stack:** Flask/Python, PostgreSQL SQL projection, vanilla JavaScript, Leaflet, CSS, pytest, Node-based JavaScript tests.

---

### Task 1: Expose price data for singleton road groups

**Files:**
- Modify: `tests/test_listing_map_service.py`
- Modify: `services/listing_map.py`

- [ ] **Step 1: Write the failing service test**

Update the listing-map fixture/assertions so a `road` summary group with `listing_count == 1` carries `price_ty`, `area_m2`, and `price_per_m2`. Assert the generated summary SQL permits both `exact` and `road` precision for singleton price projection.

- [ ] **Step 2: Run the targeted test and confirm RED**

Run:

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -X utf8 -m pytest tests\test_listing_map_service.py -q
```

Expected: failure because serialization and SQL currently expose label price fields only for `exact` precision.

- [ ] **Step 3: Implement the minimal backend change**

In `services/listing_map.py`, change all three conditional summary projections and payload serialization from exact-only to singleton `exact` or `road`. Do not expose price fields for multi-listing road groups, landmarks, or wards.

- [ ] **Step 4: Run the targeted test and confirm GREEN**

Run the same pytest command. Expected: pass.

- [ ] **Step 5: Commit**

```powershell
git add services/listing_map.py tests/test_listing_map_service.py
git commit -m "feat: expose singleton road map prices"
```

### Task 2: Generalize marker labels and move the initial map view closer

**Files:**
- Modify: `tests/test_listing_map_js.py`
- Modify: `static/js/main/listing_map.js`

- [ ] **Step 1: Write failing JavaScript behavior tests**

Cover these pure behaviors:

- exact marker: compact two-row price label from zoom 13;
- singleton road marker: the same price label from zoom 13;
- road marker with multiple listings: compact `<n> tin` badge;
- landmark and ward markers: compact `<n> tin` badge;
- invalid price/area on exact or singleton road: no price label;
- priority order: exact price, singleton-road price, road count, landmark count, ward count;
- one-level-closer initial zoom with a hard cap at 16;
- collision rectangles use the model-specific price/count dimensions.

- [ ] **Step 2: Run the targeted JS tests and confirm RED**

Run:

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -X utf8 -m pytest tests\test_listing_map_js.py -q
```

Expected: new model/zoom helper tests fail because only exact labels at zoom 14 exist.

- [ ] **Step 3: Implement the shared marker-label model**

In `static/js/main/listing_map.js`:

- replace the exact-only model with a shared exported `markerLabelModel(group, zoom)`;
- use `13` as the minimum zoom for price labels;
- produce `line1 = "<price> tỷ · <area>m²"` and `line2 = "<price/m²>tr/m²"`;
- return small count models for multi-listing roads, landmarks, and wards;
- give each model its explicit priority and dimensions;
- sort candidates by priority before collision placement;
- retain one shared collision set and non-interactive label layer;
- keep invalid singleton price labels hidden rather than substituting a count badge.

- [ ] **Step 4: Implement the closer initial framing**

After `fitBounds`, set the zoom to one level closer through an exported pure helper capped at 16. Use the same path for desktop and mobile; preserve the current empty-result fallback.

- [ ] **Step 5: Run targeted JS tests and confirm GREEN**

Run the same JS pytest command. Expected: pass.

- [ ] **Step 6: Commit**

```powershell
git add static/js/main/listing_map.js tests/test_listing_map_js.py
git commit -m "feat: add compact listing map labels"
```

### Task 3: Add compact presentation styles and cache-bust assets

**Files:**
- Modify: `static/css/main/listing_map.css`
- Modify: `templates/index.html`
- Modify: `tests/test_listing_map_ui.py`

- [ ] **Step 1: Write failing UI source assertions**

Assert that the map stylesheet contains separate compact price and count label classes, and that the template references the new Listing Maps asset version.

- [ ] **Step 2: Run the targeted UI test and confirm RED**

Run:

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -X utf8 -m pytest tests\test_listing_map_ui.py -q
```

Expected: failure because the generalized classes/version do not exist yet.

- [ ] **Step 3: Implement compact CSS**

Add a shared label base plus:

- a narrow, small-font, two-row price label;
- a small one-line count pill;
- pointer-events disabled and Vietnamese-safe UTF-8 text rendering;
- dimensions aligned with the JavaScript collision rectangles.

Remove obsolete exact-only rules after confirming no remaining references.

- [ ] **Step 4: Bump Listing Maps JS/CSS asset versions**

Update both template query strings to a shared `20260813` version token so production clients do not retain the old behavior.

- [ ] **Step 5: Run the targeted UI test and confirm GREEN**

Run the same UI pytest command. Expected: pass.

- [ ] **Step 6: Commit**

```powershell
git add static/css/main/listing_map.css templates/index.html tests/test_listing_map_ui.py
git commit -m "style: compact listing map labels"
```

### Task 4: Regression verification and browser proof

**Files:**
- Verify only unless a test exposes a defect.

- [ ] **Step 1: Run the complete Listing Maps suite**

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -X utf8 -m pytest tests\test_listing_map_service.py tests\test_listing_map_js.py tests\test_listing_map_ui.py -q
node --check static\js\main\listing_map.js
```

Expected: all pass and JavaScript syntax is valid.

- [ ] **Step 2: Start or reuse the verified local application**

Use the documented local runtime, confirm the listener and `/` HTTP response before browser checks.

- [ ] **Step 3: Verify desktop behavior in a real browser**

Check both Săn Deal and Tin rao Maps:

- initial view is closer than the previous overview;
- exact and singleton-road price labels appear at overview zoom 13+;
- multi-road, landmark, and ward labels show counts;
- labels remain compact, legible, and collision-aware;
- marker modal opens over Maps and closes back to the unchanged Maps state.

- [ ] **Step 4: Verify mobile behavior in a real browser**

Repeat the key assertions using a mobile viewport, including initial zoom and compact labels.

### Task 5: Release and production verification

**Files:**
- No additional source changes expected.

- [ ] **Step 1: Review scope and Git state**

Confirm only intended committed files are part of this feature and preserve unrelated `.playwright-cli/` work.

- [ ] **Step 2: Push `main`**

```powershell
git push origin main
```

Record the pushed SHA separately from local test evidence.

- [ ] **Step 3: Deploy production**

```powershell
.\scripts\deploy_production.ps1
```

Record deploy/service/cache output; distinguish any privileged optional warning from core deployment success.

- [ ] **Step 4: Verify public production and assets**

Confirm `https://radarbds.vn/` returns HTTP 200 and the HTML references the new versioned JS/CSS assets.

- [ ] **Step 5: Verify production UI in desktop and mobile browser viewports**

Repeat the key marker-label and closer-zoom checks against production for both Săn Deal and Tin rao. Capture screenshots/evidence and report any limitations explicitly.
