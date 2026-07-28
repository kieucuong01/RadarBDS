# Bản đồ Bình Dương Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a free, indexable `/ban-do-binh-duong` page with an interactive former/current administrative-layer switch and filtered Radar BDS dashboard CTAs.

**Architecture:** Keep public content in a dedicated Python registry, commit two generated static GeoJSON snapshots, render all essential content server-side, and progressively enhance the map with a focused JavaScript module. Reuse the shared SEO shell, tracking partial, Leaflet dependency pattern, sitemap, and `llms.txt` surfaces.

**Tech Stack:** Flask 3.1, Jinja, vanilla JavaScript, Leaflet 1.9.4, static GeoJSON, CSS, pytest, Node-based JavaScript contract tests, Playwright browser QA.

## Global Constraints

- Route is exactly `/ban-do-binh-duong`.
- Former Bình Dương with 9 district-level units is the default layer.
- The alternate layer contains exactly 36 wards/communes effective in 2025.
- The page is free; do not add payments, downloads, PayOS, gated files, a database, an API, or a CMS.
- Do not copy the reference site's prose, images, ads, products, or code.
- Use existing Radar BDS colors, typography, shared public header/footer, and filtered-dashboard funnel.
- Do not create future city/ward routes before those pages exist.
- Geometry is reference data, not legal/cadastral evidence; show visible source and due-diligence caveats.
- Keep all controls keyboard accessible and at least 44 × 44 CSS pixels.
- Preserve useful server-rendered content and links when JavaScript, Leaflet, or GeoJSON loading fails.
- Do not send coordinates, raw text, or PII to analytics.

---

### Task 1: Administrative registry and reproducible GeoJSON snapshots

**Files:**
- Create: `config/binh_duong_map.py`
- Create: `scripts/build_binh_duong_map_data.py`
- Create: `static/maps/binh-duong/legacy-districts.geojson`
- Create: `static/maps/binh-duong/current-36-wards.geojson`
- Create: `tests/test_binh_duong_map_page.py`
- Create: `tests/test_binh_duong_map_data_builder.py`

**Interfaces:**
- Produces: `BINH_DUONG_MAP_PAGE`, `BINH_DUONG_LEGACY_AREAS`, `BINH_DUONG_CURRENT_AREAS`, `BINH_DUONG_MAP_UPDATED_AT`, and `build_map_files(output_dir: Path, http_get: Callable)`.
- Produces: two GeoJSON `FeatureCollection` files whose `properties.slug` sets match the registry exactly.
- Consumes: geoBoundaries ADM2 simplified GeoJSON and the 36 pinned OpenStreetMap relation IDs documented in the registry.

- [ ] **Step 1: Write registry contract tests**

Add tests that hand-check:

```python
assert len(BINH_DUONG_LEGACY_AREAS) == 9
assert len({item["slug"] for item in BINH_DUONG_LEGACY_AREAS}) == 9
assert len(BINH_DUONG_CURRENT_AREAS) == 36
assert len({item["slug"] for item in BINH_DUONG_CURRENT_AREAS}) == 36
assert sum(item["unit_type"] == "Phường" for item in BINH_DUONG_CURRENT_AREAS) == 24
assert sum(item["unit_type"] == "Xã" for item in BINH_DUONG_CURRENT_AREAS) == 12
assert all(item["dashboard_href"].startswith("/?tab=signals") for item in all_areas)
```

The production break caught is a missing/duplicate administrative unit or an unsafe external dashboard URL.

- [ ] **Step 2: Run the registry test and verify RED**

Run:

```powershell
python -X utf8 -m pytest tests\test_binh_duong_map_page.py -q
```

Expected: import failure because `config.binh_duong_map` does not exist.

- [ ] **Step 3: Implement the registry**

Create the page metadata and literal 9/36 area lists. Pin these 36 OSM relation IDs:

```text
3870770, 8448992, 13420411, 13470504, 13470503, 13470501,
13470588, 13470506, 8448188, 13455517, 10590955, 13455518,
13477612, 13477595, 13477596, 15044270, 13477633, 13477632,
13477543, 13477544, 13477425, 13477545, 13477540, 13477634,
15071235, 15071230, 15350067, 15350008, 15350042, 15350010,
15044265, 15044266, 15328437, 15328441, 15328440, 15328433
```

Each area contains the stable fields specified in the design document.

- [ ] **Step 4: Run the registry test and verify GREEN**

Run the same pytest command. Expected: registry tests pass while route tests still fail because the route is not implemented.

- [ ] **Step 5: Write data-builder tests**

Use literal in-memory fixtures for:

- the 9 expected geoBoundaries feature names;
- 36 Nominatim lookup results with unique `osm_id` and polygon geometry;
- one missing relation;
- one duplicate relation;
- one point geometry;
- one geometry outside the former Bình Dương extent.

Assert that valid fixtures produce exact registry slug sets and each invalid fixture raises `ValueError`.

- [ ] **Step 6: Run builder tests and verify RED**

Run:

```powershell
python -X utf8 -m pytest tests\test_binh_duong_map_data_builder.py -q
```

Expected: import failure because the builder does not exist.

- [ ] **Step 7: Implement the builder**

Implement pure normalization/validation functions plus:

```python
def build_map_files(
    output_dir: Path,
    http_get: Callable[[str], dict] = _http_get_json,
) -> tuple[Path, Path]:
    ...
```

The real HTTP adapter sends an explicit Radar BDS user agent, uses request timeouts, downloads geoBoundaries once, and performs one Nominatim lookup request for the pinned IDs. The function writes deterministic UTF-8 JSON with stable feature order and fails before writing if validation is incomplete.

- [ ] **Step 8: Run builder tests and verify GREEN**

Run the builder test file. Expected: all valid/invalid fixture branches pass.

- [ ] **Step 9: Generate and validate snapshots**

Run:

```powershell
python -X utf8 -m scripts.build_binh_duong_map_data
python -X utf8 -m json.tool static\maps\binh-duong\legacy-districts.geojson > $null
python -X utf8 -m json.tool static\maps\binh-duong\current-36-wards.geojson > $null
```

Then run both Task 1 test files and confirm exact 9/36 matches.

---

### Task 2: Flask route, server-rendered content, schema, and discovery surfaces

**Files:**
- Modify: `app.py`
- Modify: `routes/public.py`
- Create: `templates/binh_duong_map.html`
- Modify: `templates/planning_hub.html`
- Modify: `templates/partials/seo_footer.html`
- Modify: `tests/test_binh_duong_map_page.py`
- Modify: `tests/test_public_seo.py`
- Modify: `tests/test_public_content_hubs.py`

**Interfaces:**
- Consumes: the registry and two static GeoJSON paths from Task 1.
- Produces: `binh_duong_map_page()` and `_binh_duong_map_schema(page, legacy_areas, current_areas)`.
- Produces: a server-rendered page with all content, directories, sources, FAQ, and dashboard URLs available without JavaScript.

- [ ] **Step 1: Write route/template/schema tests**

Test `GET /ban-do-binh-duong` for:

- status 200;
- one H1 containing “Bản đồ Bình Dương”;
- canonical `https://radarbds.vn/ban-do-binh-duong`;
- default legacy layer control with `aria-pressed="true"`;
- current layer control;
- exactly 9 legacy directory items and 36 current directory items;
- both GeoJSON URLs in data attributes;
- visible source attribution and legal-data caveat;
- no public copy containing `SEO/AIO`, `map-first`, `card`, `CTA`, or `detail`;
- filtered dashboard links;
- shared tracking partial.

Parse JSON-LD and assert:

- `WebPage`, `Dataset`, `ItemList`, `BreadcrumbList`, and `FAQPage` exist;
- `ItemList` has exactly 9 unique URLs or fragment identifiers;
- two `Dataset` objects exist and their `isBasedOn` values match visible sources.

- [ ] **Step 2: Run route tests and verify RED**

Run:

```powershell
python -X utf8 -m pytest tests\test_binh_duong_map_page.py -q
```

Expected: 404 for the new route.

- [ ] **Step 3: Implement route and template**

Add the public blueprint route, import the registry in `app.py`, build breadcrumbs/local links, set the Radar OG image, and render `templates/binh_duong_map.html`.

The template must contain:

- shared public header/footer;
- hero and overview facts;
- map controls and fallback;
- selected-area panel;
- 9 legacy and 36 current server-rendered directory items;
- interpretation, related links, FAQ, sources, disclaimer, and final dashboard CTA;
- Leaflet CSS/JS with the already-correct SRI hashes from the planning detail template;
- dedicated CSS and JavaScript asset cache keys.

- [ ] **Step 4: Implement schema and active navigation**

Add `_binh_duong_map_schema(...)`, set `active_nav="quy-hoach"`, and make `_active_public_nav("/ban-do-binh-duong")` return `quy-hoach`.

- [ ] **Step 5: Run route tests and verify GREEN**

Run the page test file. Expected: route and schema tests pass.

- [ ] **Step 6: Write discovery tests**

Assert:

- sitemap includes the route once with `lastmod`;
- `llms.txt` includes the route once;
- the planning hub and shared footer link to the route;
- no future city/ward page link is emitted.

- [ ] **Step 7: Run discovery tests and verify RED**

Run targeted public SEO/content-hub tests. Expected: new discovery assertions fail.

- [ ] **Step 8: Implement discovery links**

Add the route to `sitemap_xml()`, `llms_txt()`, planning hub related content, and shared footer. Keep the canonical base route independent of fragments.

- [ ] **Step 9: Run discovery tests and verify GREEN**

Run:

```powershell
python -X utf8 -m pytest tests\test_binh_duong_map_page.py tests\test_public_content_hubs.py tests\test_public_seo.py -k "binh_duong_map or planning or sitemap or llms" -q
```

Expected: all selected tests pass.

---

### Task 3: Layer state, map selection, fallbacks, and analytics

**Files:**
- Create: `static/js/binh_duong_map.js`
- Create: `tests/test_binh_duong_map_js.py`
- Modify: `app.py`
- Modify: `templates/binh_duong_map.html`

**Interfaces:**
- Consumes: map root data attributes, JSON-encoded server registry, Leaflet global, and two GeoJSON URLs.
- Produces: exported CommonJS/browser helpers `parseMapHash`, `formatMapHash`, `normalizeLayer`, `buildTrackingContext`, and `filterFeatureCollection`.
- Produces: two allowlisted actions `binh_duong_map_layer_selected` and `binh_duong_map_area_selected`.

- [ ] **Step 1: Write JavaScript behavior tests**

Use Node to exercise real exported helpers:

```javascript
assert.deepEqual(parseMapHash('#layer-current/area-binh-duong'), {
  layer: 'current',
  areaSlug: 'binh-duong'
});
assert.deepEqual(parseMapHash('#broken'), {
  layer: 'legacy',
  areaSlug: null
});
assert.equal(formatMapHash('legacy', 'thu-dau-mot'), '#layer-legacy/area-thu-dau-mot');
```

Also test unknown slugs, malformed encoding, exact tracking properties, and feature filtering.

- [ ] **Step 2: Run JavaScript tests and verify RED**

Run:

```powershell
python -X utf8 -m pytest tests\test_binh_duong_map_js.py -q
```

Expected: script/import failure because the JavaScript module does not exist.

- [ ] **Step 3: Implement pure helpers**

Add a UMD-style module consistent with existing public JavaScript tests. Do not read the DOM in helper functions.

- [ ] **Step 4: Run helper tests and verify GREEN**

Run the JS test file. Expected: all helper contracts pass.

- [ ] **Step 5: Write integration-contract tests**

Assert the rendered template contains stable hooks for:

- root, controls, canvas, selected panel, status, fallback, retry, and area buttons;
- `aria-pressed`, `aria-live`, and `hidden` defaults;
- no raw-coordinate analytics attributes;
- tracking allowlist entries.

- [ ] **Step 6: Run integration tests and verify RED**

Run the page test file. Expected: missing hook/allowlist assertions fail.

- [ ] **Step 7: Implement DOM behavior**

On `DOMContentLoaded`:

1. parse the current hash;
2. fetch both GeoJSON snapshots in parallel;
3. initialize Leaflet only after data validation;
4. render the requested layer;
5. synchronize controls, directory buttons, polygon styles, status, and selected panel;
6. update the fragment for user actions;
7. restore state on `hashchange`;
8. expose a retry action after load failure;
9. keep interactions working when analytics is unavailable.

Do not emit events during initial hash restoration. Emit one action per explicit user layer/area choice.

- [ ] **Step 8: Add tracking actions and verify GREEN**

Add the two allowlist values in `app.py`, run the integration and JS tests, and confirm no PII/raw coordinates are included.

---

### Task 4: Responsive visual system and accessibility

**Files:**
- Create: `static/css/binh_duong_map.css`
- Modify: `templates/binh_duong_map.html`
- Modify: `tests/test_binh_duong_map_page.py`

**Interfaces:**
- Consumes: existing SEO CSS variables/classes and the stable template hooks from Tasks 2–3.
- Produces: desktop/tablet/mobile map layouts without changing shared typography or loading new fonts.

- [ ] **Step 1: Add structural accessibility assertions**

Test:

- sequential H1/H2/H3 structure;
- button semantics instead of fake tabs;
- explicit accessible labels;
- no icon-only unlabeled actions;
- width/height reservation for non-map images;
- source links use safe external-link attributes.

- [ ] **Step 2: Run assertions and verify RED**

Run the page test file. Expected: CSS/template accessibility contract is incomplete.

- [ ] **Step 3: Implement dedicated page CSS**

Use existing teal/blue tokens and add:

- two-column desktop hero;
- overview definition-grid/table;
- 2:1 desktop map/panel layout;
- 620 px desktop and 430 px mobile map sizes;
- full-width two-button layer switch;
- compact directories;
- selected and focus-visible states;
- 44 px minimum controls;
- sticky-offset handling;
- reduced-motion override;
- no mobile horizontal overflow;
- optional mobile sticky dashboard CTA with reserved bottom padding.

- [ ] **Step 4: Run template tests and syntax checks**

Run page tests, `node --check static\js\binh_duong_map.js`, and `git diff --check`.

- [ ] **Step 5: Run UI/UX validation search**

Run:

```powershell
python "C:\Users\ASUS\.codex\skills\ui-ux-pro-max\scripts\search.py" "interactive map accessibility z-index loading responsive" --domain ux
```

Review the implementation against touch, focus, overflow, loading, and reduced-motion guidance.

---

### Task 5: Full verification and browser QA

**Files:**
- Modify only if a failing test exposes a scoped defect.

**Interfaces:**
- Consumes: the complete page.
- Produces: local verification evidence; no production deployment is part of this task unless separately requested.

- [ ] **Step 1: Run static and targeted checks**

```powershell
python -X utf8 -m py_compile app.py config\binh_duong_map.py scripts\build_binh_duong_map_data.py
node --check static\js\binh_duong_map.js
python -X utf8 -m pytest tests\test_binh_duong_map_page.py tests\test_binh_duong_map_data_builder.py tests\test_binh_duong_map_js.py tests\test_planning_pages.py tests\test_planning_hub_js.py tests\test_public_content_hubs.py -q
python -X utf8 -m pytest tests\test_public_seo.py -k "binh_duong_map or planning or sitemap or llms" -q
git diff --check
```

- [ ] **Step 2: Start the local Flask app**

Use the workspace Python interpreter and existing local environment. Do not print `.env` values.

- [ ] **Step 3: Browser QA at four widths**

At 375, 768, 1024, and 1440 px verify:

- HTTP 200 and one visible H1;
- no horizontal overflow;
- minimum control size 44 px;
- legacy default;
- current switch;
- polygon and directory selection parity;
- fragment, Back, Forward, invalid-fragment fallback;
- map failure fallback by blocking one GeoJSON request;
- sticky-header offset;
- rendered JSON-LD;
- zero console errors.

- [ ] **Step 4: Inspect rendered SEO output**

Confirm canonical, title, description, source links, due-diligence caveat, sitemap `lastmod`, `llms.txt`, and internal links.

- [ ] **Step 5: Review scope and worktree**

Run `git status --short` and `git diff --stat`. Confirm only the files named in this plan changed and preserve unrelated user work.

- [ ] **Step 6: Finalize without deployment**

Report completed files, tests, browser evidence, and any known external-data caveat. Do not push or deploy unless the user explicitly asks for the release chain.
