# Listing Planning Overlays Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add independently toggleable, source-verified land-use and construction-planning overlays for Thủ Dầu Một and Bến Cát to the listing-map workspace, then complete the production release.

**Architecture:** Curate four official planning documents outside runtime, georeference them reproducibly into versioned same-origin WebP overlays, and validate a strict manifest before the UI can expose them. The existing listing-map module loads the manifest lazily, renders Leaflet image overlays with opacity/legend/source controls, and keeps listing markers functional when one planning layer fails.

**Tech Stack:** Python 3.12, OpenCV 4.10, NumPy 1.26, Pillow 12.3, Flask/Jinja, vanilla JavaScript, Leaflet 1.9.4, pytest, Node contract tests, Python Playwright.

## Global Constraints

- This plan depends on every local gate in `docs/superpowers/plans/2026-07-29-listing-map-core.md`.
- The release contains exactly four approved artifacts:
  - land-use planning for Thủ Dầu Một;
  - land-use planning for Bến Cát;
  - construction planning for Thủ Dầu Một;
  - construction planning for Bến Cát.
- `Construction planning` means the latest verified in-force general or zoning plan that covers the supported area; a planning task, consultation file, meeting draft, or unapproved adjustment is not accepted.
- Prefer the publishing municipality, former Bình Dương provincial portal, or the responsible Hồ Chí Minh City planning authority.
- Do not use a commercial planning site as geometry source.
- Do not proxy a protected ArcGIS token, copy a session token, or depend on an undocumented authenticated endpoint.
- If publication terms do not allow hosting a derived raster, obtain written permission before release; an accessible URL is not permission by itself.
- Every artifact records the exact decision, approval date, effective period, scale, official URL, source hash, artifact hash, bounds, control points, RMSE, attribution, and legend.
- Use at least six well-distributed control points per artifact.
- Maximum RMSE is the smaller of 25 metres and half the printed planning-line width at the document scale.
- Warp outside pixels to transparent nodata; do not erase white areas inside the source map.
- Planning overlays are off by default and never produce an automatic legal conclusion about a listing.
- Land-use and construction controls are independent; opacity, legend, source, approval decision, effective period, and disclaimer remain visible while a layer is active.
- One failed artifact does not disable listing markers, base layers, or the other verified artifacts.
- Source domains, manifest IDs, categories, local artifact paths, and hashes are allowlisted and validated; the browser cannot provide arbitrary URLs or paths.
- No release, push, or deploy occurs unless all four real artifacts pass source, hash, georeference, and rendered-alignment gates.

---

## File Map

| File | Responsibility |
|---|---|
| `docs/planning_sources/listing-map-planning-source-audit.md` | Human-readable authority, approval, currency, and reuse-right evidence |
| `config/listing_planning.py` | Exact IDs, categories, areas, allowed hosts, bounds, and manifest validator |
| `config/listing_planning_sources.json` | Accepted source metadata and deterministic build inputs |
| `config/listing_planning_controls/*.csv` | Pixel-to-WGS84 control points for each accepted map |
| `scripts/build_listing_planning_artifacts.py` | Homography fit, Web Mercator warp, RMSE, legend export, hashes, and manifest |
| `scripts/validate_listing_planning_manifest.py` | CI/operator validation of the real manifest and artifacts |
| `requirements-dev.txt` | Explicit local-only PDF rasterizer dependency |
| `static/maps/listing-planning/manifest.json` | Four-layer public manifest |
| `static/maps/listing-planning/*.webp` | Versioned overlays and legends |
| `templates/partials/listing_map_workspace.html` | Planning controls, legend, source, and disclaimer hooks |
| `templates/index.html` | Lazy manifest URL configuration |
| `static/js/main/listing_map.js` | Manifest fetch, layer lifecycle, opacity, error isolation, and safe analytics |
| `static/css/main/listing_map.css` | Planning control/legend responsive styling |
| `tests/test_listing_planning_manifest.py` | Pure manifest and source policy tests |
| `tests/test_listing_planning_builder.py` | Synthetic georeference tests |
| `tests/test_listing_planning_assets.py` | Real four-artifact release gate |
| `tests/test_listing_planning_js.py` | Browser/CommonJS overlay-state contracts |
| `scripts/verify_listing_map_production.py` | Desktop/mobile public-production flow |
| `docs/dev_commands.md` | Artifact build, validation, and public smoke commands |
| `docs/operations.md` | Production schema/backfill and map smoke sequence |

---

### Task 1: Official-source audit and strict manifest contract

**Files:**
- Create: `docs/planning_sources/listing-map-planning-source-audit.md`
- Create: `config/listing_planning.py`
- Create: `tests/test_listing_planning_manifest.py`

**Interfaces:**
- Produces: `REQUIRED_PLANNING_LAYER_IDS`, `ALLOWED_PLANNING_SOURCE_HOSTS`, and `SUPPORTED_PLANNING_AREAS`.
- Produces: `validate_planning_manifest(payload: Mapping, static_root: Path, *, verify_files: bool = True) -> tuple[dict, ...]`.
- Produces: a source audit with one accepted evidence row per required artifact.

- [ ] **Step 1: Write failing manifest tests**

Define the required IDs:

```python
REQUIRED_PLANNING_LAYER_IDS = (
    "land-use-thu-dau-mot",
    "land-use-ben-cat",
    "construction-thu-dau-mot",
    "construction-ben-cat",
)
```

Use temporary files with real SHA-256 hashes and assert valid fixtures pass.
The tested top-level contract is
`{"version": "2026-07-29-v1", "layers": [four records]}`.
Assert each of these fails with a specific `ValueError`:

- missing/duplicate/extra ID;
- category outside `land_use|construction`;
- unsupported area;
- non-HTTPS source;
- source host outside the allowlist;
- source path or legend path outside `/static/maps/listing-planning/`;
- malformed or mismatching SHA-256;
- missing approval decision/date/effective period/scale;
- fewer than six control points;
- negative RMSE or RMSE above tolerance;
- inverted/out-of-service-area bounds;
- missing overlay or legend;
- file hash mismatch.

- [ ] **Step 2: Run the manifest test and verify RED**

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $py -X utf8 -m pytest tests\test_listing_planning_manifest.py -q
```

Expected: import failure because `config.listing_planning` does not exist.

- [ ] **Step 3: Implement constants and validator**

Allow only:

```python
ALLOWED_PLANNING_SOURCE_HOSTS = frozenset({
    "qhkt.hochiminhcity.gov.vn",
    "www.qhkt.hochiminhcity.gov.vn",
    "gisxaydung.tphcm.gov.vn",
    "bencat.binhduong.gov.vn",
    "thudaumot.binhduong.gov.vn",
    "www.binhduong.gov.vn",
    "congbao.binhduong.gov.vn",
    "s3.hcm-1.cloud.cmctelecom.vn",
})
```

The validator parses ISO dates with `date.fromisoformat`, resolves public paths
under the supplied `static_root`, compares hashes with `hmac.compare_digest`,
and calculates:

```python
line_tolerance_m = map_scale * line_width_mm / 2000.0
allowed_rmse_m = min(25.0, line_tolerance_m)
```

It returns records in `REQUIRED_PLANNING_LAYER_IDS` order and never mutates the
input.

- [ ] **Step 4: Run validator tests and verify GREEN**

```powershell
& $py -X utf8 -m pytest tests\test_listing_planning_manifest.py -q
& $py -X utf8 -m py_compile config\listing_planning.py
```

Expected: all contract failures are covered.

- [ ] **Step 5: Audit official source candidates**

Start with these official publications:

- Hồ Chí Minh City Sở Quy hoạch–Kiến trúc guide:
  `https://qhkt.hochiminhcity.gov.vn/tai-lieu-hop/huong-dan-gisxaydung-3627.html`
- Official merged planning portal:
  `https://gisxaydung.tphcm.gov.vn/tracuuttqh`
- Bến Cát land-use publication:
  `https://bencat.binhduong.gov.vn/cong-khai-thong-tin/quy-hoach-su-dung-dat-den-nam-2030-thi-xa-ben-cat`
- Bến Cát construction/general-plan publication:
  `https://bencat.binhduong.gov.vn/cong-khai-thong-tin/quy-hoach-chung-thi-xa-ben-cat-den-nam-2040`

For each required artifact, record:

| Evidence | Acceptance rule |
|---|---|
| Publishing authority | Municipality, former province, or current HCMC planning authority |
| Exact approval decision | Number, issuer, and signed approval date visible in the document |
| Plan status | In force for the supported former-area geography |
| Map sheet | Published scale and complete legend are present |
| Currency | Later approved adjustment checked and either incorporated or ruled out |
| Public access | Stable official page plus attachment or documented public GIS layer |
| Reuse | Terms permit derived-raster hosting with attribution, or written permission is retained |
| Integrity | Source download SHA-256 recorded |

Reject every file whose only official location is under
`/van-ban-du-thao/`, every consultation/meeting page without an approved
decision, and every protected-token GIS request.

- [ ] **Step 6: Write the source audit**

The audit contains exactly four artifact rows with status `accepted` only when
all evidence above is present. It also has a rejected-candidate appendix naming
the reason, including draft Thủ Dầu Một documents and the 2024/2025 Bến Cát
adjustment-in-progress notices when no later approval is attached.

If any artifact lacks an accepted source or reuse right, mark the audit
`release_blocked`, stop this plan after committing the audit/validator, and
report the missing authority/permission. Do not substitute another website or
continue to public artifacts.

- [ ] **Step 7: Commit audit and contract**

```powershell
git add docs/planning_sources/listing-map-planning-source-audit.md config/listing_planning.py tests/test_listing_planning_manifest.py
git diff --cached --check
git commit -m "docs: audit listing planning layer sources"
```

---

### Task 2: Reproducible georeference builder

**Files:**
- Create: `scripts/build_listing_planning_artifacts.py`
- Create: `scripts/validate_listing_planning_manifest.py`
- Modify: `requirements-dev.txt`
- Create: `tests/test_listing_planning_builder.py`
- Modify: `docs/dev_commands.md`

**Interfaces:**
- Produces: `ControlPoint(pixel_x: float, pixel_y: float, lat: float, lng: float)`.
- Produces: `read_control_points(path: Path) -> tuple[ControlPoint, ...]`.
- Produces: `fit_web_mercator_homography(points) -> numpy.ndarray`.
- Produces: `calculate_rmse_m(points, matrix) -> float`.
- Produces: `warp_planning_raster(source_path, points, output_path, *, max_dimension=4096) -> RasterBuild`.
- Produces: `build_planning_artifacts(config_path: Path, output_dir: Path) -> Path`.

- [ ] **Step 1: Generate a synthetic source map in the test and write failing builder tests**

Use Pillow inside the test to write a deterministic 200x200 RGBA grid image to
pytest's `tmp_path`, including labeled intersections at the eight control
pixels. Write the matching CSV to the same temporary directory:

```csv
pixel_x,pixel_y,lat,lng,label
20,20,11.0200,106.6200,north-west
180,20,11.0200,106.7000,north-east
20,180,10.9400,106.6200,south-west
180,180,10.9400,106.7000,south-east
100,20,11.0200,106.6600,north-mid
100,180,10.9400,106.6600,south-mid
20,100,10.9800,106.6200,west-mid
180,100,10.9800,106.7000,east-mid
```

This keeps binary test fixtures out of git while exercising the real image
decoder and CSV reader.

Assert:

- CSV requires unique labels and at least six points;
- points must cover all four image quadrants;
- duplicate source pixels or coordinates fail;
- homography round-trips control points;
- RMSE for the exact fixture is below 1 metre;
- a moved control point breaches tolerance;
- output is WebP RGBA, north-up, at most 4096 pixels on either dimension;
- pixels outside the warped source quadrilateral are transparent;
- two builds produce identical bytes and hashes;
- no output/manifest file remains after a validation failure.

- [ ] **Step 2: Run builder tests and verify RED**

```powershell
& $py -X utf8 -m pytest tests\test_listing_planning_builder.py -q
```

Expected: import failure because the builder does not exist.

- [ ] **Step 3: Implement coordinate transforms and RMSE**

Pin `pypdfium2==5.12.1` in `requirements-dev.txt`. Render the configured PDF
page at 300 DPI with pypdfium2 before passing an RGBA NumPy array to OpenCV.
Image source files bypass PDF rendering.

Use Web Mercator:

```python
EARTH_RADIUS_M = 6378137.0


def web_mercator_xy(lat: float, lng: float) -> tuple[float, float]:
    clipped = max(min(float(lat), 85.05112878), -85.05112878)
    x = EARTH_RADIUS_M * math.radians(float(lng))
    y = EARTH_RADIUS_M * math.log(
        math.tan(math.pi / 4.0 + math.radians(clipped) / 2.0)
    )
    return x, y
```

Fit with
`cv2.findHomography(source_points, mercator_points, method=0)`. Project each source control point,
convert the prediction back to WGS84, and calculate haversine metres against the
target point. Reject a singular matrix or any non-finite value.

- [ ] **Step 4: Implement raster warp and manifest generation**

Define the build result:

```python
@dataclass(frozen=True)
class RasterBuild:
    artifact_path: Path
    legend_path: Path
    bounds: tuple[tuple[float, float], tuple[float, float]]
    width: int
    height: int
    control_point_count: int
    rms_error_m: float
    artifact_sha256: str
    legend_sha256: str
```

Project the four source corners through the homography, derive Web Mercator
bounds, prepend the scale/translation matrix needed for output pixels, and call
`cv2.warpPerspective` with a transparent four-channel border. Keep all source
pixels opaque; only outside nodata is transparent.

Export:

- overlay WebP with `lossless=True`;
- legend crop WebP from explicit source-pixel bounds;
- WGS84 south-west/north-east bounds;
- control-point count, RMSE, line-width tolerance, dimensions, and both hashes.

Write all artifacts to a temporary directory. Validate the complete four-record
manifest with `validate_planning_manifest` before atomically replacing public
files.

- [ ] **Step 5: Implement the standalone validator**

The command:

```powershell
& $py -X utf8 scripts\validate_listing_planning_manifest.py `
  --manifest static\maps\listing-planning\manifest.json `
  --static-root static
```

prints one safe line per layer with ID, dimensions, RMSE, allowed RMSE, and hash
prefix. It never prints cookies, tokens, local source file contents, or raw
control-point coordinates.

- [ ] **Step 6: Run builder tests and verify GREEN**

```powershell
& $py -X utf8 -m pytest tests\test_listing_planning_builder.py tests\test_listing_planning_manifest.py -q
& $py -X utf8 -m py_compile scripts\build_listing_planning_artifacts.py scripts\validate_listing_planning_manifest.py
```

Expected: synthetic fit, failure, atomicity, and manifest tests pass.

- [ ] **Step 7: Document exact build commands**

Add:

```powershell
& $py -X utf8 scripts\build_listing_planning_artifacts.py `
  --config config\listing_planning_sources.json `
  --output-dir static\maps\listing-planning
& $py -X utf8 scripts\validate_listing_planning_manifest.py `
  --manifest static\maps\listing-planning\manifest.json `
  --static-root static
```

State that source PDFs/images stay under `.local/listing-planning/sources/` and
are neither committed nor printed.

- [ ] **Step 8: Commit builder and tests**

```powershell
git add scripts/build_listing_planning_artifacts.py scripts/validate_listing_planning_manifest.py requirements-dev.txt tests/test_listing_planning_builder.py docs/dev_commands.md
git diff --cached --check
git commit -m "feat: build verified planning overlays"
```

---

### Task 3: Curate and gate the four real artifacts

**Files:**
- Create: `config/listing_planning_sources.json`
- Create: `config/listing_planning_controls/land-use-thu-dau-mot.csv`
- Create: `config/listing_planning_controls/land-use-ben-cat.csv`
- Create: `config/listing_planning_controls/construction-thu-dau-mot.csv`
- Create: `config/listing_planning_controls/construction-ben-cat.csv`
- Create: `static/maps/listing-planning/manifest.json`
- Create: `static/maps/listing-planning/land-use-thu-dau-mot-v1.webp`
- Create: `static/maps/listing-planning/land-use-thu-dau-mot-v1-legend.webp`
- Create: `static/maps/listing-planning/land-use-ben-cat-v1.webp`
- Create: `static/maps/listing-planning/land-use-ben-cat-v1-legend.webp`
- Create: `static/maps/listing-planning/construction-thu-dau-mot-v1.webp`
- Create: `static/maps/listing-planning/construction-thu-dau-mot-v1-legend.webp`
- Create: `static/maps/listing-planning/construction-ben-cat-v1.webp`
- Create: `static/maps/listing-planning/construction-ben-cat-v1-legend.webp`
- Create: `tests/test_listing_planning_assets.py`

**Interfaces:**
- Consumes only sources accepted in Task 1.
- Produces exactly four manifest entries and eight versioned WebP files.
- Produces a hard release-gate test over real files.

- [ ] **Step 1: Write the real-asset gate before generating files**

The test loads the committed manifest through the production validator and
asserts:

```python
assert tuple(item["id"] for item in layers) == REQUIRED_PLANNING_LAYER_IDS
assert {item["category"] for item in layers} == {"land_use", "construction"}
assert {item["area"] for item in layers} == {"Thủ Dầu Một", "Bến Cát"}
assert all(item["control_point_count"] >= 6 for item in layers)
assert all(item["rms_error_m"] <= item["allowed_rmse_m"] for item in layers)
```

Open every overlay and legend with Pillow; require WebP, nonzero dimensions,
RGBA overlay data, at least one transparent outside pixel, at least one opaque
map pixel, and exact file hashes.

- [ ] **Step 2: Run the real-asset test and verify RED**

```powershell
& $py -X utf8 -m pytest tests\test_listing_planning_assets.py -q
```

Expected: missing production manifest/artifacts.

- [ ] **Step 3: Download accepted originals into ignored storage**

```powershell
New-Item -ItemType Directory -Force -Path ".local\listing-planning\sources" | Out-Null
```

Download each exact attachment from the accepted source audit into that
directory. Calculate:

```powershell
Get-FileHash -Algorithm SHA256 -LiteralPath ".local\listing-planning\sources\land-use-thu-dau-mot.pdf"
Get-FileHash -Algorithm SHA256 -LiteralPath ".local\listing-planning\sources\land-use-ben-cat.pdf"
Get-FileHash -Algorithm SHA256 -LiteralPath ".local\listing-planning\sources\construction-thu-dau-mot.pdf"
Get-FileHash -Algorithm SHA256 -LiteralPath ".local\listing-planning\sources\construction-ben-cat.pdf"
```

Copy only hash values into `config/listing_planning_sources.json`; do not
commit originals.

- [ ] **Step 4: Record exact build metadata and control points**

Each source-config record contains the exact required layer ID/category/area,
the ignored local source filename, zero-based map-sheet page, accepted official
source URL, control-point CSV path, stable `-v1.webp` overlay/legend filenames,
decision metadata, source hash, scale, measured printed line width, source
download date, legend pixel bounds, and attribution copied from the accepted
document. The builder rejects a missing field. Use at least eight
well-distributed control points when the sheet has enough recognizable
intersections.

- [ ] **Step 5: Build and validate all artifacts**

```powershell
& $py -X utf8 scripts\build_listing_planning_artifacts.py `
  --config config\listing_planning_sources.json `
  --output-dir static\maps\listing-planning
& $py -X utf8 scripts\validate_listing_planning_manifest.py `
  --manifest static\maps\listing-planning\manifest.json `
  --static-root static
& $py -X utf8 -m pytest tests\test_listing_planning_assets.py -q
```

Expected: exactly four entries and eight files pass hashes and RMSE.

- [ ] **Step 6: Visually inspect georeference alignment**

For each overlay, inspect at least:

- one north-west control landmark;
- one north-east control landmark;
- one central road/intersection;
- one south-west control landmark;
- one south-east control landmark;
- one recognizable boundary not used as a control point.

Compare against OpenStreetMap and satellite base layers at useful zoom.
Record pass/fail and measured residuals in the source audit. A visually shifted
non-control landmark fails even when numeric RMSE passes.

- [ ] **Step 7: Re-run the release gate and commit artifacts**

```powershell
& $py -X utf8 -m pytest tests\test_listing_planning_manifest.py tests\test_listing_planning_builder.py tests\test_listing_planning_assets.py -q
git add docs/planning_sources/listing-map-planning-source-audit.md config/listing_planning_sources.json config/listing_planning_controls static/maps/listing-planning tests/test_listing_planning_assets.py
git diff --cached --check
git commit -m "data: add verified listing planning overlays"
```

Expected: only accepted metadata, controls, derived WebP files, manifest, tests,
and audit are committed; original source documents remain ignored.

---

### Task 4: Planning controls in the listing-map workspace

**Files:**
- Modify: `templates/partials/listing_map_workspace.html`
- Modify: `templates/index.html` in lazy map configuration
- Modify: `static/js/main/listing_map.js`
- Modify: `static/css/main/listing_map.css`
- Create: `tests/test_listing_planning_js.py`
- Modify: `tests/test_listing_map_ui.py`

**Interfaces:**
- Produces CommonJS/browser helpers: `validatePlanningManifestShape`,
  `planningLayerState`, `planningOpacity`, and `safePlanningTrackingContext`.
- Consumes: `/static/maps/listing-planning/manifest.json`.
- Adds DOM hooks: `listingMapPlanningControls`, `listingMapPlanningLegend`,
  `listingMapPlanningSource`, and `listingMapPlanningDisclaimer`.

- [ ] **Step 1: Write failing JavaScript and DOM tests**

Assert:

```javascript
mapApi.planningOpacity(-1) === 0
mapApi.planningOpacity(0.55) === 0.55
mapApi.planningOpacity(2) === 1
```

Test manifest shape rejects an extra ID, external artifact URL, bad category,
bad bounds, or missing attribution. Test state transitions:

- both categories start off;
- enabling land use does not enable construction;
- opacity applies to active planning overlays only;
- disabling a category removes its overlays;
- one failed artifact records an error without clearing markers or other
  overlays;
- safe tracking contains only action, layer ID/category, area, and state.

DOM tests require two labeled switches, one opacity input, legend image,
official-source link, approval/effective-period text, and visible disclaimer.

- [ ] **Step 2: Run JS/UI tests and verify RED**

```powershell
& $py -X utf8 -m pytest tests\test_listing_planning_js.py tests\test_listing_map_ui.py -q
```

Expected: planning helpers and controls are missing.

- [ ] **Step 3: Add lazy manifest config and semantic controls**

Add:

```javascript
window.RADAR_LISTING_PLANNING_MANIFEST =
  "{{ url_for('static', filename='maps/listing-planning/manifest.json') }}?v=listing-planning-20260729";
```

Controls use Vietnamese labels:

- `Quy hoạch sử dụng đất`;
- `Quy hoạch xây dựng`;
- `Độ mờ lớp quy hoạch`;
- `Tắt lớp quy hoạch`;
- disclaimer `Lớp tham khảo theo hồ sơ công bố; không thay thế xác nhận pháp lý cho từng thửa đất.`

All switches expose `aria-pressed`; the range input has an associated label and
current percentage.

- [ ] **Step 4: Fetch and validate the manifest lazily**

Fetch only after the map opens. Require `response.ok`, same-origin manifest,
exact required IDs, same-origin artifact/legend paths, and allowed metadata.
Keep a successful manifest in memory for the page lifetime. Retry a failed
manifest only after explicit user action.

Do not accept any tile, artifact, manifest, source domain, or filesystem path
from query parameters or `data-*` attributes.

- [ ] **Step 5: Render independent Leaflet image overlays**

Create one `L.imageOverlay` per active manifest item:

```javascript
const overlay = L.imageOverlay(
  item.artifact_path,
  item.bounds,
  {
    opacity: state.opacity,
    interactive: false,
    className: `listing-planning-layer listing-planning-${item.category}`
  }
);
```

Add both area artifacts for the selected category; Leaflet naturally shows the
ones intersecting the viewport. Keep planning panes below listing markers and
above base tiles. Toggle and opacity changes do not refetch the map summary.

- [ ] **Step 6: Render legend, source, approval, and partial errors**

When one layer is active, show its legend and metadata. When two area artifacts
for the same category are visible, show area tabs in the legend panel. Official
source links use `target="_blank"` and `rel="noopener noreferrer"`.

An image `error` event marks only that artifact unavailable, removes it from
the map, and exposes retry/source controls. Existing markers, selected group,
other planning layer, and base layer remain unchanged.

- [ ] **Step 7: Add safe analytics**

Allowlist:

- `listing_map_planning_toggled`;
- `listing_map_planning_opacity_changed`;
- `listing_map_planning_source_opened`.

Payload contains only mode, layer ID/category, area, enabled boolean, and
rounded opacity. Do not send coordinates, filter keywords, location labels,
listing IDs, contact data, or source attachment URLs.

- [ ] **Step 8: Run focused tests and syntax checks**

```powershell
& $py -X utf8 -m pytest tests\test_listing_planning_js.py tests\test_listing_map_js.py tests\test_listing_map_ui.py tests\test_listing_planning_assets.py -q
node --check static\js\main\listing_map.js
git diff --check
```

Expected: planning controls, manifest validation, partial failure, and safe
analytics tests pass.

- [ ] **Step 9: Commit planning UI**

```powershell
git add templates/partials/listing_map_workspace.html templates/index.html static/js/main/listing_map.js static/css/main/listing_map.css tests/test_listing_planning_js.py tests/test_listing_map_ui.py
git diff --cached --check
git commit -m "feat: add verified planning layers to listing map"
```

---

### Task 5: End-to-end release gate and production verifier

**Files:**
- Create: `scripts/verify_listing_map_production.py`
- Modify: `docs/dev_commands.md`
- Modify: `docs/operations.md`
- Modify only a feature file when verification exposes a real defect

**Interfaces:**
- Produces: `verify_listing_map(base_url: str, output_dir: Path) -> dict`.
- Produces a nonzero process exit when a required public flow or planning layer
  fails.

- [ ] **Step 1: Write the production verifier against a local base URL**

Use Python Playwright. For desktop 1440×900 and mobile 390×844:

- open `/?tab=signals`;
- capture active filters and feed total;
- click `Xem trên Maps`;
- wait for Leaflet canvas and map summary;
- assert total parity and mapped/unmapped invariants;
- switch street/satellite;
- select a road/ward group and assert items appear;
- enable land use and construction independently;
- assert four manifest IDs can be activated;
- assert legend, decision, effective period, source, and disclaimer;
- close through button, Escape, and Browser Back in separate runs;
- assert tab, filter values, scroll position, and focused launcher restore;
- repeat on `/?tab=all` with `Tin đủ thông tin`;
- assert no horizontal overflow and no uncaught page error.

Screenshots and JSON evidence go only to
`.local/listing-map-verification/`.

- [ ] **Step 2: Add verifier safety assertions**

Intercept both map endpoint responses and recursively reject keys:

```python
FORBIDDEN_MAP_KEYS = {
    "url",
    "source_url",
    "phone",
    "contact_phone",
    "seller_name",
    "description",
    "images",
}
```

Planning manifest `source_url` is allowed only in the manifest response, not in
listing API responses. Reject browser requests to an unapproved source host or
to a protected ArcGIS token endpoint.

- [ ] **Step 3: Run the verifier locally**

```powershell
& $py -X utf8 scripts\verify_listing_map_production.py `
  --base-url "http://127.0.0.1:5000" `
  --output-dir ".local\listing-map-verification\local"
```

Expected: both viewports and tabs pass, both planning categories work, all four
artifacts load, and no forbidden listing key is observed.

- [ ] **Step 4: Run the full targeted suite**

```powershell
& $py -X utf8 -m pytest `
  tests\test_listing_map_query_scope.py `
  tests\test_listing_map_schema.py `
  tests\test_listing_location_registry.py `
  tests\test_listing_location_resolver.py `
  tests\test_listing_location_backfill.py `
  tests\test_listing_map_service.py `
  tests\test_listing_map_api.py `
  tests\test_listing_map_ui.py `
  tests\test_listing_map_js.py `
  tests\test_listing_planning_manifest.py `
  tests\test_listing_planning_builder.py `
  tests\test_listing_planning_assets.py `
  tests\test_listing_planning_js.py `
  tests\test_market_data_trust.py `
  tests\test_market_data_performance.py `
  tests\test_guest_visibility.py `
  tests\test_security_hardening.py -q
```

Expected: all selected tests pass.

- [ ] **Step 5: Run syntax and repository checks**

```powershell
& $py -X utf8 -m py_compile app.py routes\market_api.py services\market_data.py services\listing_map.py services\listing_location_resolver.py services\listing_location_backfill.py db\schema.py db\listing_map_locations.py cli\map_locations.py cleansing\reprocess.py radar.py config\listing_planning.py scripts\build_listing_location_registry.py scripts\build_listing_planning_artifacts.py scripts\validate_listing_planning_manifest.py scripts\verify_listing_map_production.py
node --check static\js\main\core.js
node --check static\js\main\listings.js
node --check static\js\main\listing_map.js
git diff --check
git status --short
```

Expected: clean syntax and only intentional feature/doc paths.

- [ ] **Step 6: Measure local budgets**

Repeat cold/warm timing for both map modes, gzip the response body locally to
measure compressed size, and inspect the real PostgreSQL `EXPLAIN (ANALYZE,
BUFFERS)` plan. The build fails if any approved budget is exceeded; do not cap
results or omit unmapped listings.

- [ ] **Step 7: Commit verifier and runbook**

```powershell
git add scripts/verify_listing_map_production.py docs/dev_commands.md docs/operations.md
git diff --cached --check
git commit -m "test: verify listing map production release"
```

---

### Task 6: Commit, push, deploy, backfill, and public proof

**Files:**
- No new feature files unless a verified production defect requires a narrow fix

**Interfaces:**
- Consumes all Plan 1 and Plan 2 commits.
- Produces deployed schema, production location rows, public map behavior, and
  four public planning layers.

- [ ] **Step 1: Review and integrate the feature branch**

Use `superpowers:requesting-code-review` and
`superpowers:verification-before-completion`. Resolve only actionable findings.
Then use `superpowers:finishing-a-development-branch` to integrate the clean
feature branch into the current upstream `main`.

Verify:

```powershell
git status --short --branch
git log --oneline origin/main..main
git diff origin/main...main --check
```

Expected: clean `main`, intentional commits only, and no unrelated dirty path.

- [ ] **Step 2: Push the exact verified main**

```powershell
git push origin main
```

Expected: push succeeds and `git rev-parse main` equals
`git rev-parse origin/main`.

- [ ] **Step 3: Deploy through the documented wrapper**

```powershell
.\scripts\deploy_production.ps1
```

Expected: VPS fast-forwards to the pushed commit, service restarts, and existing
dashboard/signals smoke checks pass. If the wrapper reports unexpected dirty
VPS files, stop and report exact paths; do not reset them.

- [ ] **Step 4: Apply and prove the production schema**

```powershell
$key = "$env:USERPROFILE\.ssh\radar_bds_deploy_rsa"
$hostName = "deploy@103.90.226.230"
ssh -i $key $hostName "set -a; . /etc/radar-bds/radar.env; set +a; cd /opt/radar-bds/current && /opt/radar-bds/.venv/bin/python -X utf8 -c 'from db.schema import init_schema; init_schema()'"
ssh -i $key $hostName 'set -a; . /etc/radar-bds/radar.env; set +a; psql "$DATABASE_URL" -tAc "SELECT to_regclass(''public.listing_map_locations'') IS NOT NULL"'
```

Expected: the final command prints `True`. If schema initialization logs
insufficient privilege and the table is absent, block release and request an
owner-role migration; do not report the feature live.

- [ ] **Step 5: Run and prove the production location backfill**

```powershell
ssh -i $key $hostName "set -a; . /etc/radar-bds/radar.env; set +a; cd /opt/radar-bds/current && /opt/radar-bds/.venv/bin/python -X utf8 radar.py map-locations --full"
ssh -i $key $hostName "set -a; . /etc/radar-bds/radar.env; set +a; cd /opt/radar-bds/current && /opt/radar-bds/.venv/bin/python -X utf8 radar.py map-locations --dry-run"
```

Expected: first run reports counts whose invariants hold; dry-run reports no
pending insert/update/delete. This is a derived backfill, not a full listing
reprocess.

- [ ] **Step 6: Smoke public APIs and artifacts**

```powershell
$public = "https://radarbds.vn"
$signalsMap = Invoke-RestMethod "$public/api/map-listings?mode=signals"
$allMap = Invoke-RestMethod "$public/api/map-listings?mode=all"
$manifest = Invoke-RestMethod "$public/static/maps/listing-planning/manifest.json"
$signalsMap.summary
$allMap.summary
$manifest.layers | Select-Object id,category,area,rms_error_m
```

Assert in PowerShell:

```powershell
if ($signalsMap.summary.mapped + $signalsMap.summary.unmapped_count -ne $signalsMap.summary.total) { throw "signals invariant failed" }
if ($allMap.summary.mapped + $allMap.summary.unmapped_count -ne $allMap.summary.total) { throw "all invariant failed" }
if ($manifest.layers.Count -ne 4) { throw "planning layer count failed" }
```

Fetch every overlay and legend with `Invoke-WebRequest`; require HTTP 200,
`image/webp`, nonzero length, and long-lived static cache headers.

- [ ] **Step 7: Measure production API timings**

Run one cold and five warm requests for both modes. Record milliseconds and
response bytes. Confirm cold at most 2.5 seconds and warm p95 at most 1.0
second. If a budget fails, keep the deployment marked incomplete and inspect
the production query plan.

- [ ] **Step 8: Run public desktop/mobile verification**

```powershell
& $py -X utf8 scripts\verify_listing_map_production.py `
  --base-url "https://radarbds.vn" `
  --output-dir ".local\listing-map-verification\production"
```

Expected: Săn Deal, Tin rao, state restoration, bottom-center launcher, group
items, both base layers, both planning categories, all four artifacts, source
metadata, disclaimer, safe responses, and both viewports pass.

- [ ] **Step 9: Verify deployed commit and service health**

```powershell
$localCommit = git rev-parse HEAD
$remoteCommit = ssh -i $key $hostName "cd /opt/radar-bds/current && git rev-parse HEAD"
if ($localCommit.Trim() -ne $remoteCommit.Trim()) { throw "deployed commit mismatch" }
ssh -i $key $hostName "systemctl is-active radar-bds.service"
Invoke-WebRequest -UseBasicParsing "$public/api/dashboard" | Select-Object StatusCode
Invoke-WebRequest -UseBasicParsing "$public/api/signals?page=1&limit=3" | Select-Object StatusCode
```

Expected: commit hashes match, service is `active`, and both legacy endpoints
return 200.

- [ ] **Step 10: Record the final evidence**

The closeout separates:

- local automated and browser checks;
- local/production PostgreSQL schema and backfill counts;
- four-source decisions, hashes, RMSE, and reuse evidence;
- pushed/deployed commit;
- public API timing/payload results;
- public desktop/mobile behavior.

Only after every item passes may the feature be described as released to
production.
