# Listing Map Official GIS Link Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a safe official-GIS CTA to the existing listing-map workspace and release the core map without hosted planning overlays.

**Architecture:** Render one constant external anchor in the semantic map partial and use the existing allowlisted analytics helper for a mode-only click event. Keep the planning overlay manifest, raster builder, and layer controls absent; update the audit to distinguish the approved link-only release from the still-blocked overlay release.

**Tech Stack:** Flask/Jinja, vanilla JavaScript, CSS, pytest, Node syntax checks, Playwright/browser smoke, PostgreSQL backfill, PowerShell production deploy.

## Global Constraints

- Official GIS URL is exactly `https://gisxaydung.tphcm.gov.vn/tracuuttqh`.
- The link uses `target="_blank"` and `rel="noopener noreferrer"`.
- Do not append coordinates, filters, keywords, listing IDs, or location labels.
- Do not fetch, proxy, iframe, or scrape the official GIS portal.
- Do not add a planning manifest, raster asset, legend, toggle, or undocumented GIS API.
- The local planning-overlay audit remains `release_blocked`.
- The link-only scope is user-approved and may be released after the core map gates pass.
- Production release includes schema initialization, derived map-location backfill, public API checks, desktop/mobile UI checks, and deployed-commit proof.

---

### Task 1: Official GIS CTA

**Files:**
- Modify: `tests/test_listing_map_ui.py`
- Modify: `tests/test_listing_map_js.py`
- Modify: `templates/partials/listing_map_workspace.html`
- Modify: `static/css/main/listing_map.css`
- Modify: `static/js/main/listing_map.js`

**Interfaces:**
- Consumes: existing `emitTrack(eventName, context)` and map `state.snapshot.mode`.
- Produces: DOM hook `listingMapOfficialGisLink` and event `listing_map_official_gis_opened`.

- [ ] **Step 1: Write failing DOM and JavaScript tests**

Require the exact official URL, `target="_blank"`,
`rel="noopener noreferrer"`, link-only disclaimer, and no planning-overlay DOM
hooks. Require the click event name and assert the tracking context contains
only `mode`.

- [ ] **Step 2: Run tests and verify RED**

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $py -X utf8 -m pytest tests\test_listing_map_ui.py tests\test_listing_map_js.py -q
```

Expected: failures for the missing CTA and event binding.

- [ ] **Step 3: Add minimal semantic markup and responsive styles**

Add a planning callout to the workspace header with:

```html
<a id="listingMapOfficialGisLink"
   href="https://gisxaydung.tphcm.gov.vn/tracuuttqh"
   target="_blank" rel="noopener noreferrer">
  Mở GIS quy hoạch chính thức
</a>
```

Keep the callout compact on desktop and stacked below the title on mobile.

- [ ] **Step 4: Add safe click tracking**

Bind the anchor once in `bind()` and emit:

```javascript
emitTrack("listing_map_official_gis_opened", {
  mode: state.snapshot && state.snapshot.mode
});
```

Do not include the URL or listing/location state.

- [ ] **Step 5: Run focused tests and syntax checks**

```powershell
& $py -X utf8 -m pytest tests\test_listing_map_ui.py tests\test_listing_map_js.py -q
node --check static\js\main\listing_map.js
git diff --check
```

Expected: all pass.

### Task 2: Audit Status And Documentation

**Files:**
- Modify: `docs/planning_sources/listing-map-planning-source-audit.md`

**Interfaces:**
- Produces: separate `official_gis_link_only` release status while preserving
  `release_blocked` for self-hosted overlays.

- [ ] **Step 1: Update the audit**

Record the user's approval date, exact official URL, no-deep-link policy, and
the fact that this scope override permits the core map release but does not
accept any of the four missing artifacts.

- [ ] **Step 2: Run documentation checks and commit**

```powershell
git diff --check
git add tests/test_listing_map_ui.py tests/test_listing_map_js.py templates/partials/listing_map_workspace.html static/css/main/listing_map.css static/js/main/listing_map.js docs/planning_sources/listing-map-planning-source-audit.md
git commit -m "feat: link listing map to official planning GIS"
```

### Task 3: Verification And Production Release

**Files:**
- Modify only when verification exposes a feature-owned defect.

**Interfaces:**
- Consumes: the complete `codex/listing-maps-planning` branch.
- Produces: pushed `main`, deployed schema, location backfill, and public proof.

- [ ] **Step 1: Run targeted feature tests and syntax checks**

Run all listing-map query, schema, registry, resolver, backfill, API, UI,
JavaScript, planning-manifest, trust, performance, and security tests that do
not require unavailable local credentials.

- [ ] **Step 2: Browser-smoke the local rendered UI**

Verify Săn Deal and Tin Rao on desktop/mobile: bottom-center launcher, map open
and close, visible official-GIS CTA, exact external URL/protections, no
horizontal overflow, and no planning layer controls.

- [ ] **Step 3: Fetch/rebase and re-run gates**

Fetch `origin`, rebase the feature branch onto the current `origin/main`, then
repeat Task 3 Steps 1–2. Stop on conflicts or failures.

- [ ] **Step 4: Integrate and push**

Fast-forward local `main` to the verified feature branch and push
`origin/main`. Do not force-push.

- [ ] **Step 5: Deploy and initialize production**

Run `scripts/deploy_production.ps1`, initialize the schema through the
production environment, then run:

```bash
/opt/radar-bds/.venv/bin/python -X utf8 radar.py map-locations --full
/opt/radar-bds/.venv/bin/python -X utf8 radar.py map-locations --dry-run
```

The dry run must report no pending insert/update/delete.

- [ ] **Step 6: Verify public production**

Confirm `/api/dashboard`, `/api/signals`, both map endpoints, mapped/unmapped
invariants, deployed commit equality, active service, public CTA URL/security,
desktop/mobile layout, and link-only absence of planning overlay artifacts or
controls.
