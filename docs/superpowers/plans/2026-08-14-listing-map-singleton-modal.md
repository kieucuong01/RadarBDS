# Listing Maps Singleton Modal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Open the existing signal-detail modal directly when an exact or road Maps marker represents exactly one listing, while preserving the list flow for every other marker.

**Architecture:** Keep the existing summary and `/api/map-listing-items` request contract. Pure helpers determine eligibility and validate the returned item. The guarded `selectGroup` response opens `openListingFromMap` only after it confirms one valid listing; all other responses retain the current item-list or item-error state.

**Tech Stack:** Vanilla JavaScript, Leaflet 1.9.4, existing signal-detail modal, pytest/Node contract tests, in-app Browser smoke testing.

## Global Constraints

- Direct modal opening applies only to `exact` and `road` groups whose normalized `listing_count` is exactly `1`.
- `landmark` and `ward` groups always retain the list flow, including when they have one listing.
- Keep `/api/map-listing-items`, `AbortController`, `itemSequence`, `openListingFromMap`, and existing signal-modal history behavior; do not add endpoints, navigation, schema, cache, registry or CSS changes.
- An eligible singleton keeps the directory panel/mobile sheet visible while the request is pending; it only shows a list or error when fallback is needed.
- Stale responses must never open a modal. Closing the modal must preserve Maps filters, viewport and base layer.
- Update only the Maps JavaScript asset version in `templates/index.html`.

---

## File Structure

- `static/js/main/listing_map.js`: singleton-decision helpers and the group-selection branch.
- `tests/test_listing_map_js.py`: pure decision matrix and modal-adapter regression tests.
- `tests/test_listing_map_ui.py`: source-flow and JavaScript cache-version contracts.
- `templates/index.html`: JavaScript asset cache-bust token.

### Task 1: Define and test singleton decision boundaries

**Files:**

- Modify: `static/js/main/listing_map.js:2113-2128, module export object`
- Test: `tests/test_listing_map_js.py`

**Interfaces:**

- Consumes: `group.precision`, `group.listing_count`, and API payload `{items: Array<object>}`.
- Produces: `isDirectModalGroup(group) -> boolean` and `singletonModalItem(group, payload) -> object|null`.

- [ ] **Step 1: Write the failing tests**

Add after the existing `openListingFromMap` tests in `tests/test_listing_map_js.py`:

```python
def test_direct_modal_group_is_limited_to_single_exact_and_road_markers():
    assert _run_node("mapApi.isDirectModalGroup({precision:'exact',listing_count:1})") is True
    assert _run_node("mapApi.isDirectModalGroup({precision:'road',listing_count:1})") is True
    assert _run_node("mapApi.isDirectModalGroup({precision:'landmark',listing_count:1})") is False
    assert _run_node("mapApi.isDirectModalGroup({precision:'ward',listing_count:1})") is False
    assert _run_node("mapApi.isDirectModalGroup({precision:'road',listing_count:2})") is False
    assert _run_node("mapApi.isDirectModalGroup({precision:'exact',listing_count:'1'})") is True


def test_singleton_modal_item_requires_one_valid_item_from_an_eligible_group():
    assert _run_node(
        "mapApi.singletonModalItem({precision:'road',listing_count:1},"
        "{items:[{id:42,title:'NE8'}]}).id"
    ) == 42
    assert _run_node(
        "mapApi.singletonModalItem({precision:'exact',listing_count:1},"
        "{items:[{id:0,title:'Thiếu mã'}]})"
    ) is None
    assert _run_node(
        "mapApi.singletonModalItem({precision:'road',listing_count:1},{items:[]})"
    ) is None
    assert _run_node(
        "mapApi.singletonModalItem({precision:'road',listing_count:1},"
        "{items:[{id:42},{id:43}]})"
    ) is None
    assert _run_node(
        "mapApi.singletonModalItem({precision:'ward',listing_count:1},"
        "{items:[{id:42}]})"
    ) is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $py -X utf8 -m pytest `
  tests\test_listing_map_js.py::test_direct_modal_group_is_limited_to_single_exact_and_road_markers `
  tests\test_listing_map_js.py::test_singleton_modal_item_requires_one_valid_item_from_an_eligible_group -q
```

Expected: FAIL because the new exported helpers do not exist.

- [ ] **Step 3: Implement the pure helpers and export them**

Add immediately before `openListingFromMap` in `static/js/main/listing_map.js`:

```javascript
function isDirectModalGroup(group) {
  if (!group || safeCount(group.listing_count) !== 1) return false;
  return group.precision === "exact" || group.precision === "road";
}

function singletonModalItem(group, payload) {
  if (!isDirectModalGroup(group)) return null;
  var items = payload && Array.isArray(payload.items) ? payload.items : [];
  if (items.length !== 1 || !validListingId(items[0])) return null;
  return items[0];
}
```

Export both names beside `openListingFromMap`:

```javascript
isDirectModalGroup: isDirectModalGroup,
singletonModalItem: singletonModalItem,
```

- [ ] **Step 4: Run focused tests to verify they pass**

Run:

```powershell
& $py -X utf8 -m pytest `
  tests\test_listing_map_js.py::test_direct_modal_group_is_limited_to_single_exact_and_road_markers `
  tests\test_listing_map_js.py::test_singleton_modal_item_requires_one_valid_item_from_an_eligible_group `
  tests\test_listing_map_js.py::test_listing_map_item_click_opens_existing_modal_without_navigation `
  tests\test_listing_map_js.py::test_listing_map_item_click_ignores_missing_ids_without_navigation -q
```

Expected: PASS. The existing adapter test confirms the feature uses the detail modal without navigation.

- [ ] **Step 5: Commit Task 1**

```powershell
git add static/js/main/listing_map.js tests/test_listing_map_js.py
git commit -m "test: define singleton map modal decision"
```

### Task 2: Branch the guarded group-selection response into the existing modal

**Files:**

- Modify: `static/js/main/listing_map.js:2382-2413`
- Modify: `templates/index.html:106`
- Test: `tests/test_listing_map_ui.py`

**Interfaces:**

- Consumes: `isDirectModalGroup`, `singletonModalItem`, `openListingFromMap`, `itemSequence`, and current panel render functions.
- Produces: direct modal opening after a current valid singleton response; normal item-list/error rendering otherwise.

- [ ] **Step 1: Write the failing select-flow and asset-version tests**

Add to `tests/test_listing_map_ui.py`:

```python
def test_listing_map_select_group_opens_only_confirmed_exact_or_road_singleton():
    script = Path("static/js/main/listing_map.js").read_text(encoding="utf-8")
    select_source = script.split("function selectGroup(group)", 1)[1].split(
        "function renderSummary", 1
    )[0]

    assert "var directModalGroup = isDirectModalGroup(group);" in select_source
    assert "if (!directModalGroup) {" in select_source
    assert 'setPanelView("items-loading", group);' in select_source
    assert "var directItem = singletonModalItem(group, payload);" in select_source
    assert "if (directItem && openListingFromMap(root, directItem)) return;" in select_source
    assert 'setPanelView("items", group, payload);' in select_source
    assert 'setPanelView("items-error", group);' in select_source
    assert "if (!state.open || sequence !== itemSequence) return;" in select_source


def test_listing_map_assets_use_singleton_modal_cache_version():
    template = Path("templates/index.html").read_text(encoding="utf-8")

    assert template.count("listing-map-singleton-modal-20260814") == 1
    assert "listing-map-touch-target-20260814" in template
```

- [ ] **Step 2: Run the contract tests to verify they fail**

Run:

```powershell
& $py -X utf8 -m pytest `
  tests\test_listing_map_ui.py::test_listing_map_select_group_opens_only_confirmed_exact_or_road_singleton `
  tests\test_listing_map_ui.py::test_listing_map_assets_use_singleton_modal_cache_version -q
```

Expected: FAIL because `selectGroup` always opens the list and the JavaScript cache token is absent.

- [ ] **Step 3: Implement the response branch**

At the start of `selectGroup`, immediately after `state.selectedGroup = group`, add:

```javascript
var directModalGroup = isDirectModalGroup(group);
if (!directModalGroup) {
  setMobileSheetExpanded(true);
  setPanelView("items-loading", group);
}
```

Remove the current unconditional calls to `setMobileSheetExpanded(true)` and `setPanelView("items-loading", group)`; retain current URL construction, tracking, abort controller and sequence handling.

Inside the existing fulfilled `fetchJson` callback, directly after the current sequence guard, add:

```javascript
var directItem = singletonModalItem(group, payload);
if (directItem && openListingFromMap(root, directItem)) return;
if (directModalGroup && (!payload || !Array.isArray(payload.items)
  || payload.items.length === 0)) {
  setPanelView("items-error", group);
  return;
}
setPanelView("items", group, payload);
```

Keep the current `catch` block. A stale summary that returns two or more items falls through to the normal list; a missing ID or unavailable modal integration also falls through to the list.

- [ ] **Step 4: Cache-bust only changed JavaScript**

Change the `RADAR_ASSETS.listingMap` token in `templates/index.html` to:

```text
listing-map-singleton-modal-20260814
```

Do not change the CSS token.

- [ ] **Step 5: Run focused verification**

Run:

```powershell
& $py -X utf8 -m pytest tests\test_listing_map_js.py tests\test_listing_map_ui.py tests\test_listing_map_service.py tests\test_listing_map_api.py -q
node --check static\js\main\listing_map.js
git diff --check
```

Expected: all pytest tests pass; Node and diff checks exit 0.

- [ ] **Step 6: Commit Task 2**

```powershell
git add static/js/main/listing_map.js templates/index.html tests/test_listing_map_ui.py
git commit -m "feat: open singleton map markers in detail modal"
```

### Task 3: Browser regression and release proof

**Files:**

- No source changes expected.
- Verify: local Maps UI, Git state, production checkout, public APIs and browser behavior.

**Interfaces:**

- Consumes: implementation commits from Tasks 1 and 2.
- Produces: verified desktop/mobile interactions and production release evidence.

- [ ] **Step 1: Start and verify a local production-shaped app**

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
$server = Start-Process $py -ArgumentList "-X", "utf8", "app.py" -WorkingDirectory (Get-Location).Path -WindowStyle Hidden -PassThru
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

- [ ] **Step 2: Browser-test direct and retained flows**

Use the in-app Browser skill at 1440x900 and 390x844:

1. Open a Signals or All listing view and choose `Xem trên Maps`.
2. Select a known one-listing exact marker; verify signal detail opens immediately with no item-list panel first.
3. Close the modal; verify Maps remains open at the same center, zoom, filters and base layer.
4. Repeat with a one-listing road marker.
5. Select a one-listing landmark or ward marker and verify its item list opens.
6. Select a multi-listing marker and verify its item list opens.
7. Open a singleton modal then use browser Back once; verify only the modal closes and Maps remains open without navigating to `/listing/<id>`.

Expected: exact/road singleton markers open the modal; landmark/ward and multi-listing markers open the list; all close/back behavior preserves Maps state.

- [ ] **Step 3: Stop the local process and run the release gate**

```powershell
Stop-Process -Id $server.Id
& $py -X utf8 -m pytest tests\test_listing_map_js.py tests\test_listing_map_ui.py tests\test_listing_map_service.py tests\test_listing_map_api.py -q
node --check static\js\main\listing_map.js
git diff --check
git status --short
```

Expected: all checks pass, feature diff is clean, and the pre-existing untracked `.playwright-cli/` directory is untouched.

- [ ] **Step 4: Push, deploy and smoke production**

```powershell
git push origin main
.\scripts\deploy_production.ps1
Invoke-WebRequest -UseBasicParsing "https://radarbds.vn/api/map-listings?mode=signals"
Invoke-WebRequest -UseBasicParsing "https://radarbds.vn/api/map-listings?mode=all&complete=1"
Invoke-WebRequest -UseBasicParsing "https://radarbds.vn/?verify=listing-map-singleton-modal-20260814"
```

Expected: local, origin and production checkout resolve to the same new SHA; `radar-bds` is active; all three public requests return HTTP 200. In a fresh production browser session, repeat Step 2 and confirm the loaded Maps JavaScript URL contains `listing-map-singleton-modal-20260814`.

- [ ] **Step 5: Record delivery evidence**

Report focused test, syntax, browser, API, service and SHA results separately. State that the existing public modal was reused and admin editing was unchanged.
