# Signal Modal And Listing Detail UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add trusted listing location maps, full-width comparable signal-card carousels, sharing, and bad-listing reporting to the dashboard signal modal and `/listing/<id>`.

**Architecture:** Extend the existing listing-detail read model with the already-derived map location and enrich the existing comparable query with the compact signal-card fields. Extract browser-only presentation into focused shared modules (`signal_card.js`, `detail_location_map.js`, `listing_detail_actions.js`, and `comparable_carousel.js`) consumed by both surfaces. Keep user reports in a dedicated service/table and expose only a thin public write route plus an admin-only paginated read route.

**Tech Stack:** PostgreSQL 18, Flask 3.1, Python 3.12, Jinja, vanilla JavaScript, Leaflet 1.9.4, OpenStreetMap/Esri layers, pytest 8.4, Node contract tests, in-app Browser plugin.

## Global Constraints

- Implement the approved specification at `docs/superpowers/specs/2026-07-29-signal-listing-detail-ux-design.md`.
- Work only in the isolated `codex/signal-detail-ux` worktree based on current `origin/main`.
- `.sm-left` and `.sm-right` use a desktop 60/40 ratio; comparable content is the final direct child of `.sm-content` and spans both columns.
- `Vị trí BĐS` appears immediately below `Nguyên văn tin rao`.
- Reuse `listing_map_locations`; never invent coordinates or write derived coordinates into `listings`.
- Road/ward points are visibly approximate; a missing location renders no marker.
- Comparable cards use the same renderer and card stylesheet as `Săn deal`.
- Desktop carousel slides contain three columns by two rows; return at most 18 comparable listings.
- Share only the canonical internal `/listing/<validated integer id>` URL.
- Listing reports never write to `ai_training_feedback`, `ai_deal_review`, valuation fields, dedup state, `review_hidden`, or `is_blacklisted`.
- No crawler, parser, valuation-formula, external geocoder, or production-deploy change is in scope.
- Preserve Guest/Free/VIP redaction and the existing Admin raw-source boundary.
- Run every production-code change through a witnessed RED/GREEN test cycle.
- The clean baseline has one unrelated failure in `test_mobile_filter_sheet_scroll_is_isolated_from_signal_tab`; keep it separately reported.

## Threat Model

| Boundary | Abuse case | Required control |
|---|---|---|
| `POST /api/listings/<id>/report` | forged reason or oversized note | strict reason allowlist; trim; 500-character bound; JSON object only |
| report note -> DB -> admin JSON | stored XSS | parameterized insert; JSON/plain-text output; no HTML interpolation |
| guest reporting | spam or flood | per-reporter hourly limit, per-IP daily limit, 24-hour duplicate idempotency |
| reporter identity/IP | PII disclosure | application-secret-backed HMAC; never store raw IP in `listing_reports` |
| public report response | report/user enumeration | generic success/duplicate responses; no hashes, actor identity, or counts |
| admin report read | privilege escalation | server-side `admin_required` check |
| report side effects | malicious mass hiding/training contamination | append-only pending row only; regression tests against protected tables/fields |
| share/Facebook URL | open redirect or source URL leak | derive URL solely from validated integer listing ID and public origin |
| map location | false parcel-accuracy claim | exact/road/ward copy allowlist; no fallback marker |

---

## File Map

| File | Responsibility |
|---|---|
| `services/market_data.py` | Add nullable `map_location` to listing detail |
| `services/listing_comparables.py` | Build redacted, compact comparable signal-card payloads |
| `services/listing_reports.py` | Validate, deduplicate, rate-limit, insert, and list reports |
| `db/schema.py` | Idempotent `listing_reports` schema and indexes |
| `routes/market_api.py` | Public report route registration |
| `routes/admin_api.py` | Admin report-list route registration |
| `app.py` | Thin route handlers and listing-detail serialization |
| `static/js/main/signal_card.js` | Shared Săn deal card renderer |
| `static/js/main/signals.js` | Feed adapter consuming shared renderer |
| `static/js/main/comparable_carousel.js` | Responsive carousel paging and interaction |
| `static/js/main/detail_location_map.js` | Lazy mini-map lifecycle and precision copy |
| `static/js/main/listing_detail_actions.js` | Canonical share menu and report dialog |
| `static/js/main/modal.js` | Modal hydration/adapters only |
| `static/css/main/cards.css` | Existing card visuals plus comparable-context selectors |
| `static/css/main/modal.css` | 60/40 workspace, full-width comparables, map/action/dialog styles |
| `templates/index.html` | Modal structure and shared asset URLs |
| `templates/listing_detail.html` | Standalone structure and shared assets |
| `tests/test_listing_detail_map.py` | Detail map read-model/API contracts |
| `tests/test_listing_comparables.py` | Comparable selection/shape/redaction contracts |
| `tests/test_listing_reports.py` | Report schema/service/API/security contracts |
| `tests/test_signal_detail_ui.py` | Jinja/CSS structural contracts |
| `tests/js/test_signal_card.js` | Shared renderer contract |
| `tests/js/test_comparable_carousel.js` | Carousel behavior contract |
| `tests/js/test_detail_location_map.js` | Map adapter contract |
| `tests/js/test_listing_detail_actions.js` | Share/report browser logic contract |

---

### Task 1: Listing Detail Map Read Model

**Files:**
- Modify: `services/market_data.py` in `load_listing_detail`
- Modify: `app.py` in `api_listing_detail`
- Create: `tests/test_listing_detail_map.py`

**Interfaces:**
- Produces: `load_listing_detail(... )["map_location"] -> dict | None`
- Object fields: `lat`, `lng`, `precision`, `label`, `resolver_version`
- Consumed by: Task 2 templates and `RadarDetailLocationMap`

- [ ] **Step 1: Write failing service/API tests**

Insert an isolated listing plus `listing_map_locations` row and assert:

```python
detail = market_data.load_listing_detail(None, listing_id, tier="guest")
assert detail["map_location"] == {
    "lat": 10.992,
    "lng": 106.676,
    "precision": "road",
    "label": "Theo tên đường ĐX 43, Phú Lợi",
    "resolver_version": "osm-2026-07-29-v1",
}
assert client.get(f"/api/listing/{listing_id}").get_json()["map_location"]["precision"] == "road"
```

Add a second listing without a location row and assert both service and API
return `map_location is None`. Repeat the fixture with `exact` and `ward` to
prove the precision field is passed through unchanged.

- [ ] **Step 2: Run RED**

```powershell
& $py -X utf8 -m pytest tests\test_listing_detail_map.py -q
```

Expected: `KeyError: 'map_location'` or API field missing.

- [ ] **Step 3: Implement the read-model join**

In `load_listing_detail`, select the derived location through a
`LEFT JOIN listing_map_locations ml ON ml.listing_id = l.id`, aliasing fields
as `map_lat`, `map_lng`, `map_precision`, `map_label`, and
`map_resolver_version`. Pop those aliases from the public listing dictionary
before redaction and shape:

```python
map_lat = listing_dict.pop("map_lat", None)
map_lng = listing_dict.pop("map_lng", None)
map_precision = listing_dict.pop("map_precision", None)
map_label = listing_dict.pop("map_label", None)
map_resolver_version = listing_dict.pop("map_resolver_version", None)
map_location = None
if map_precision in {"exact", "road", "ward"} and map_lat is not None and map_lng is not None:
    map_location = {
        "lat": float(map_lat),
        "lng": float(map_lng),
        "precision": map_precision,
        "label": str(map_label or ""),
        "resolver_version": str(map_resolver_version or ""),
    }
```

Return it beside `listing`, `images`, and `history`. Add
`"map_location": data.get("map_location")` to `api_listing_detail`.

- [ ] **Step 4: Run GREEN and syntax checks**

```powershell
& $py -X utf8 -m pytest tests\test_listing_detail_map.py tests\test_listing_map_api.py -q
& $py -X utf8 -m py_compile services\market_data.py app.py
```

- [ ] **Step 5: Commit**

```powershell
git add services/market_data.py app.py tests/test_listing_detail_map.py
git commit -m "feat: expose trusted listing detail locations"
```

---

### Task 2: Shared Lazy Detail Map

**Files:**
- Create: `static/js/main/detail_location_map.js`
- Modify: `static/css/main/modal.css`
- Modify: `templates/index.html`
- Modify: `templates/listing_detail.html`
- Modify: `static/js/main/modal.js`
- Create: `tests/js/test_detail_location_map.js`
- Create: `tests/test_signal_detail_ui.py`

**Interfaces:**
- Consumes: Task 1 `map_location`
- Produces: `RadarDetailLocationMap.mount({root, location, vendor, initialLayer})`
- Produces: `RadarDetailLocationMap.unmount(root)`

- [ ] **Step 1: Write failing Node and template tests**

The Node test requires the module and asserts:

```javascript
assert.equal(api.precisionCopy('exact').title, 'Vị trí chính xác');
assert.match(api.precisionCopy('road').note, /ước tính|tên đường/i);
assert.match(api.precisionCopy('ward').note, /tâm phường/i);
assert.equal(api.normalizeLocation({lat: 200, lng: 106, precision: 'road'}), null);
assert.equal(api.normalizeLocation(null), null);
```

The template test asserts both surfaces contain a `Vị trí BĐS` section directly
after description, a map canvas, precision status, retry action, and the
`detail_location_map.js` asset.

- [ ] **Step 2: Run RED**

```powershell
node tests\js\test_detail_location_map.js
& $py -X utf8 -m pytest tests\test_signal_detail_ui.py -q
```

Expected: missing module and missing location section assertions.

- [ ] **Step 3: Implement the focused adapter**

Use a UMD wrapper. `normalizeLocation` accepts only finite in-range
coordinates and `exact|road|ward`. `mount`:

1. renders the precision title/note before loading Leaflet;
2. uses the existing `window.RADAR_MAP_VENDOR` URLs and integrity attributes;
3. reuses an already-loaded `window.L`;
4. creates OSM and Esri layers with existing attribution;
5. places one marker and fits a fixed neighborhood zoom;
6. shows retry without discarding the precision copy on vendor/tile failure;
7. calls `invalidateSize()` after the modal becomes visible.

`unmount` removes the Leaflet instance and listeners. It never creates a
marker for a null location.

- [ ] **Step 4: Add both DOM surfaces**

Place:

```html
<section class="sm-section sm-location-section" data-detail-location>
  <div class="sm-section-label">Vị trí BĐS</div>
  <div class="sm-location-copy" data-location-copy></div>
  <div class="sm-location-map" data-location-map aria-label="Bản đồ vị trí bất động sản"></div>
  <button type="button" data-location-retry hidden>Thử tải lại bản đồ</button>
</section>
```

immediately after description. Standalone initialization consumes
`data["map_location"]`; modal hydration consumes API `map_location`.

- [ ] **Step 5: Run GREEN**

```powershell
node tests\js\test_detail_location_map.js
& $py -X utf8 -m pytest tests\test_signal_detail_ui.py tests\test_listing_detail_map.py -q
node --check static\js\main\detail_location_map.js
node --check static\js\main\modal.js
```

- [ ] **Step 6: Commit**

```powershell
git add static/js/main/detail_location_map.js static/js/main/modal.js static/css/main/modal.css templates/index.html templates/listing_detail.html tests/js/test_detail_location_map.js tests/test_signal_detail_ui.py
git commit -m "feat: add trusted maps to listing details"
```

---

### Task 3: Comparable Payload And Shared Signal Renderer

**Files:**
- Create: `services/listing_comparables.py`
- Modify: `app.py` in `get_price_history`
- Create: `static/js/main/signal_card.js`
- Modify: `static/js/main/signals.js`
- Modify: `static/js/main/listings.js`
- Modify: `templates/index.html`
- Modify: `templates/listing_detail.html`
- Create: `tests/test_listing_comparables.py`
- Create: `tests/js/test_signal_card.js`
- Modify: `tests/test_refactor_structure.py`

**Interfaces:**
- Produces: `load_listing_comparables(conn, listing_id, tier, limit=18) -> list[dict]`
- Produces: `RadarSignalCard.render(item, options) -> str`
- Options: `context`, `openMode`, `showFavorite`, `showContact`, `priorityImage`
- Consumed by: dashboard feeds and Task 4 carousel

- [ ] **Step 1: Write failing comparable service tests**

Create current and candidate listings plus latest valuation/image fixtures.
Assert the service:

```python
items = load_listing_comparables(conn, current_id, "guest", limit=18)
assert current_id not in {item["id"] for item in items}
assert len(items) <= 18
assert items[0]["detail_url"] == f"/listing/{items[0]['id']}"
assert items[0]["imgs"]
assert "fair_ppm2_display" in items[0]
assert "mos_pct_display" in items[0]
assert "url" not in str(items[0])
assert "phone" not in str(items[0]).lower()
```

Add sold, blacklisted, hidden, duplicate, wrong-ward, wrong-type, and 19 valid
fixtures to prove exclusion and cap behavior. Assert Admin retains the current
raw-source data boundary while `detail_url` remains internal.

- [ ] **Step 2: Run backend RED**

```powershell
& $py -X utf8 -m pytest tests\test_listing_comparables.py -q
```

Expected: import failure for `services.listing_comparables`.

- [ ] **Step 3: Implement the service**

Move the current comparable selection/ranking out of `get_price_history`.
Reuse `LATEST_VALUATION_CTE`, `LATEST_SHADOW_VALUATION_CTE`,
`signal_badge_metadata`, `resolve_image_url`, and `redact_for_tier`.
Fetch at most 40 guarded candidates, rank with the existing area/unit-price/
road/title score, then serialize at most `min(max(limit, 1), 18)`.

`get_price_history` delegates:

```python
comps = load_listing_comparables(conn, listing_id, tier=tier, limit=18)
```

- [ ] **Step 4: Write failing shared-renderer tests**

Load `signal_card.js` in Node and assert one fixture contains the existing
`.signal-card`, media, MOS, actual/fair price, meta chips, quality badge, and
internal detail target. Assert comparable options omit favorite/contact
actions. Update structure tests to require `signals.js` and `listings.js` to
call `RadarSignalCard.render`.

- [ ] **Step 5: Run renderer RED**

```powershell
node tests\js\test_signal_card.js
& $py -X utf8 -m pytest tests\test_refactor_structure.py -q
```

Expected: missing module/API and old inline renderer assertions.

- [ ] **Step 6: Extract the renderer without visual changes**

Move pure formatting/render helpers required by `renderSignalDealCard` into
the UMD module and expose `render`. Keep feed-specific click/action callbacks
as options. Replace feed/listing calls with the shared module. Load
`signal_card.js` before `signals.js` on the dashboard and on the standalone
detail page; add `cards.css` to standalone.

- [ ] **Step 7: Run GREEN**

```powershell
& $py -X utf8 -m pytest tests\test_listing_comparables.py tests\test_refactor_structure.py -q
node tests\js\test_signal_card.js
node --check static\js\main\signal_card.js
node --check static\js\main\signals.js
node --check static\js\main\listings.js
```

- [ ] **Step 8: Commit**

```powershell
git add services/listing_comparables.py app.py static/js/main/signal_card.js static/js/main/signals.js static/js/main/listings.js templates/index.html templates/listing_detail.html tests/test_listing_comparables.py tests/js/test_signal_card.js tests/test_refactor_structure.py
git commit -m "refactor: share signal cards with listing comparables"
```

---

### Task 4: Full-Width Comparable Carousel And 60/40 Layout

**Files:**
- Create: `static/js/main/comparable_carousel.js`
- Modify: `static/js/main/modal.js`
- Modify: `static/css/main/modal.css`
- Modify: `templates/index.html`
- Modify: `templates/listing_detail.html`
- Create: `tests/js/test_comparable_carousel.js`
- Modify: `tests/test_signal_detail_ui.py`

**Interfaces:**
- Consumes: `RadarSignalCard.render` and comparable payload
- Produces: `RadarComparableCarousel.mount(root, items, options)`
- Options: `desktopPageSize=6`, `tabletPageSize=4`, `mobilePageSize=1`, `openItem`

- [ ] **Step 1: Write failing contract tests**

Assert:

```javascript
assert.deepEqual(api.paginate(items(13), 6).map(x => x.length), [6, 6, 1]);
assert.deepEqual(api.paginate(items(9), 4).map(x => x.length), [4, 4, 1]);
assert.deepEqual(api.paginate(items(3), 1).map(x => x.length), [1, 1, 1]);
```

Use a small fake DOM to verify previous/next clamping, active slide
`aria-hidden=false`, inactive cards `tabindex=-1`, arrow-key navigation, swipe
threshold, and omission of controls for one slide.

Template/CSS tests assert:

- comparables are a direct child after `.sm-right`;
- `grid-column: 1 / -1`;
- `grid-template-columns: minmax(0, 3fr) minmax(0, 2fr)`;
- desktop slide grid is three columns;
- the old comparable mobile tab is absent.

- [ ] **Step 2: Run RED**

```powershell
node tests\js\test_comparable_carousel.js
& $py -X utf8 -m pytest tests\test_signal_detail_ui.py -q
```

- [ ] **Step 3: Implement carousel and restructure templates**

Render one `.sm-comparable-slide` per page. The active slide is visible and
focusable; other slides are `hidden`/`aria-hidden=true`. Add previous/next,
`aria-live` status, dots, keydown, touchstart/touchend, reduced-motion CSS,
and cleanup. Modal comparable click reuses `openSignal` with the internal
listing ID; standalone click assigns `/listing/<id>` to `location.href`.

Move the comparable section after `.sm-right` in both templates. Remove the
old current-listing baseline and compact-row renderer.

- [ ] **Step 4: Run GREEN**

```powershell
node tests\js\test_comparable_carousel.js
& $py -X utf8 -m pytest tests\test_signal_detail_ui.py tests\test_listing_comparables.py -q
node --check static\js\main\comparable_carousel.js
node --check static\js\main\modal.js
```

- [ ] **Step 5: Commit**

```powershell
git add static/js/main/comparable_carousel.js static/js/main/modal.js static/css/main/modal.css templates/index.html templates/listing_detail.html tests/js/test_comparable_carousel.js tests/test_signal_detail_ui.py
git commit -m "feat: add full-width comparable card carousel"
```

---

### Task 5: Canonical Share Action

**Files:**
- Create: `static/js/main/listing_detail_actions.js`
- Modify: `app.py` tracking allowlist/context shaping
- Modify: `static/css/main/modal.css`
- Modify: `templates/index.html`
- Modify: `templates/listing_detail.html`
- Create: `tests/js/test_listing_detail_actions.js`
- Modify: `tests/test_signal_detail_ui.py`
- Modify: `tests/test_security_hardening.py`

**Interfaces:**
- Produces: `RadarListingDetailActions.canonicalListingUrl(origin, id)`
- Produces: `bindShare(root, {listingId, origin, track})`
- Task 7 adds `bindReport`

- [ ] **Step 1: Write failing canonical/share tests**

Assert valid integer IDs produce `https://radarbds.vn/listing/42`, while zero,
negative, decimal, and non-numeric IDs return null. Assert Facebook produces:

```text
https://www.facebook.com/sharer/sharer.php?u=<encoded canonical URL>
```

Test clipboard success, selection fallback, outside-click close, `Escape`,
focus restoration, and no source/title/description value in the share URL.

- [ ] **Step 2: Run RED**

```powershell
node tests\js\test_listing_detail_actions.js
```

- [ ] **Step 3: Implement and integrate**

Add a share trigger/menu to both action bars. Use `textContent` for status.
Open Facebook with `noopener,noreferrer`; if popup creation returns null,
retain the menu and show copy guidance. Add `listing_share` to
`ALLOWED_TRACK_ACTIONS`; shape its context to only `surface=modal|detail` and
`method=copy|facebook`, and retain the validated listing ID already supported
by `/api/track`.

- [ ] **Step 4: Run GREEN**

```powershell
node tests\js\test_listing_detail_actions.js
& $py -X utf8 -m pytest tests\test_signal_detail_ui.py tests\test_security_hardening.py -q
node --check static\js\main\listing_detail_actions.js
```

- [ ] **Step 5: Commit**

```powershell
git add app.py static/js/main/listing_detail_actions.js static/css/main/modal.css templates/index.html templates/listing_detail.html tests/js/test_listing_detail_actions.js tests/test_signal_detail_ui.py tests/test_security_hardening.py
git commit -m "feat: add safe listing share actions"
```

---

### Task 6: Bad Listing Report Backend

**Files:**
- Modify: `db/schema.py`
- Create: `services/listing_reports.py`
- Modify: `routes/market_api.py`
- Modify: `routes/admin_api.py`
- Modify: `app.py`
- Create: `tests/test_listing_reports.py`

**Interfaces:**
- Produces: `submit_listing_report(listing_id, payload, actor, request_meta, secret, now=None) -> ReportResult`
- Produces: `list_listing_reports(status, page, limit) -> dict`
- Public route: `POST /api/listings/<int:listing_id>/report`
- Admin route: `GET /admin/api/listing-reports`

- [ ] **Step 1: Write failing schema and abuse-case tests**

Assert schema contains `listing_reports`, status/reason checks, FK, pending
index, reporter/time index, and IP/time index. API tests prove:

- guest and signed-in valid submission returns 201;
- a repeated report in 24 hours returns 200 with `duplicate=true`;
- invalid reason, non-object JSON, and note over 500 characters return 400;
- missing/hidden/blacklisted listing returns 404;
- sixth hourly reporter submission and 21st daily IP submission return 429;
- raw IP is absent from the row and response;
- note is returned only through admin JSON as inert text;
- non-admin admin-route request returns 403;
- report submission leaves protected tables/fields unchanged.

- [ ] **Step 2: Run RED**

```powershell
& $py -X utf8 -m pytest tests\test_listing_reports.py -q
```

Expected: table/service/route missing.

- [ ] **Step 3: Add idempotent schema**

Add `listing_reports` to `SCHEMA_SQL` and a focused
`_migrate_listing_reports(conn)` called from `_run_migrations` and the
limited-DDL recovery path. Use PostgreSQL-compatible constraints and indexes.
Do not add triggers or foreign writes.

- [ ] **Step 4: Implement the service**

Define:

```python
REPORT_REASONS = frozenset({
    "sold_or_unavailable",
    "wrong_price_or_area",
    "duplicate",
    "wrong_location",
    "spam_or_scam",
    "other",
})
```

Use `hmac.new(secret_bytes, normalized_value, hashlib.sha256).hexdigest()` for
`reporter_key_hash` and `ip_hash`. Logged-in reporter key is `user:<id>`;
guest key is `guest:<ip>|<bounded user agent>`. Query all limits with
parameters. Insert only after validation, visibility, duplicate, and rate
checks pass.

- [ ] **Step 5: Add thin routes**

The public route:

1. calls `reject_cross_site_session_request()`;
2. requires `request.is_json`;
3. bounds `request.content_length` to 4 KiB;
4. passes `current_user`, `current_tier`, `client_ip_from_request`, User-Agent,
   and `app.secret_key` to the service;
5. returns generic JSON codes without hashes or internals.

The admin route uses the existing `admin_required` decorator/helper, validates
`pending|reviewed|dismissed`, and clamps limit to 100.

- [ ] **Step 6: Run GREEN and security checks**

```powershell
& $py -X utf8 -m pytest tests\test_listing_reports.py tests\test_security_hardening.py -q
& $py -X utf8 -m py_compile services\listing_reports.py db\schema.py app.py routes\market_api.py routes\admin_api.py
git diff | Select-String -Pattern 'password|secret|api_key|token' -CaseSensitive:$false
```

- [ ] **Step 7: Commit**

```powershell
git add db/schema.py services/listing_reports.py routes/market_api.py routes/admin_api.py app.py tests/test_listing_reports.py
git commit -m "feat: add protected bad listing reports"
```

---

### Task 7: Report Dialog On Both Detail Surfaces

**Files:**
- Modify: `static/js/main/listing_detail_actions.js`
- Modify: `static/css/main/modal.css`
- Modify: `templates/index.html`
- Modify: `templates/listing_detail.html`
- Modify: `tests/js/test_listing_detail_actions.js`
- Modify: `tests/test_signal_detail_ui.py`

**Interfaces:**
- Consumes: Task 6 public report API
- Produces: `bindReport(root, {listingId, fetch, onTrack})`

- [ ] **Step 1: Extend failing Node/UI tests**

Assert the dialog:

- requires one allowlisted reason;
- trims note and blocks 501 characters before fetch;
- posts only `{reason, note}`;
- preserves form state after network/429/500 errors;
- treats `duplicate=true` as success;
- renders response copy with `textContent`;
- traps focus, closes on `Escape`, and restores trigger focus.

Template tests assert the button/dialog exists on both surfaces and every
reason value matches backend `REPORT_REASONS`.

- [ ] **Step 2: Run RED**

```powershell
node tests\js\test_listing_detail_actions.js
& $py -X utf8 -m pytest tests\test_signal_detail_ui.py -q
```

- [ ] **Step 3: Implement dialog lifecycle**

Use one reusable dialog instance per page. The modal passes its current
listing ID each time it opens. Disable only the submit button during request.
Map API codes to concise Vietnamese copy; do not display raw server errors.
Close after success announcement and reset only after the next open.

- [ ] **Step 4: Run GREEN**

```powershell
node tests\js\test_listing_detail_actions.js
& $py -X utf8 -m pytest tests\test_signal_detail_ui.py tests\test_listing_reports.py -q
node --check static\js\main\listing_detail_actions.js
```

- [ ] **Step 5: Commit**

```powershell
git add static/js/main/listing_detail_actions.js static/css/main/modal.css templates/index.html templates/listing_detail.html tests/js/test_listing_detail_actions.js tests/test_signal_detail_ui.py
git commit -m "feat: add bad listing report dialog"
```

---

### Task 8: Integrated Regression And Browser QA

**Files:**
- Modify only files required by defects found in verification
- Modify: `docs/dev_commands.md` with focused commands if new commands are not discoverable

**Interfaces:**
- Verifies all earlier interfaces together

- [ ] **Step 1: Run focused automated suite**

```powershell
& $py -X utf8 -m pytest tests\test_listing_detail_map.py tests\test_listing_comparables.py tests\test_listing_reports.py tests\test_signal_detail_ui.py tests\test_listing_map_api.py tests\test_guest_visibility.py tests\test_security_hardening.py -q
node tests\js\test_signal_card.js
node tests\js\test_comparable_carousel.js
node tests\js\test_detail_location_map.js
node tests\js\test_listing_detail_actions.js
```

- [ ] **Step 2: Run syntax and repository checks**

```powershell
& $py -X utf8 -m py_compile app.py services\market_data.py services\listing_comparables.py services\listing_reports.py db\schema.py
node --check static\js\main\signal_card.js
node --check static\js\main\comparable_carousel.js
node --check static\js\main\detail_location_map.js
node --check static\js\main\listing_detail_actions.js
node --check static\js\main\modal.js
git diff --check
```

Run the full `tests/test_refactor_structure.py` and report the known clean
baseline asset-version failure separately if it remains identical.

- [ ] **Step 3: Start the local app**

Use the documented Python 3.12 interpreter and the worktree `.env` routing.
If `.env` is intentionally absent in the worktree, point the process at the
ignored main-checkout `.env` without copying or printing it.

```powershell
& $py -X utf8 app.py
```

- [ ] **Step 4: Run Browser plugin desktop flow**

The flow under test is:

```text
/ signals tab -> open a signal -> inspect description/map -> inspect comparable
carousel -> share/copy -> open report dialog -> submit -> open /listing/<id>
-> repeat the same checks.
```

At 1440×1000 verify page identity, nonblank DOM, no framework overlay, console
health, 60/40 column measurements, map precision copy and marker, comparable
section order, three columns by two rows, slide navigation, internal
comparable navigation, share Facebook URL, copy state, report validation and
success/duplicate state. Capture modal and standalone screenshots.

- [ ] **Step 5: Run Browser plugin mobile flow**

At 390×844 and 375×812 verify single-column order, no horizontal document
overflow, map controls, one-card swipe carousel, accessible action wrapping,
share menu, report focus trap/restoration, and no fixed-bar content overlap.
Capture one representative mobile screenshot per surface.

- [ ] **Step 6: Fix verified defects test-first**

For every defect, add or strengthen the smallest failing automated test,
witness RED, patch the owning file, and rerun GREEN before repeating the
Browser interaction.

- [ ] **Step 7: Final full verification**

Rerun Step 1 and Step 2 fresh. Review:

```powershell
git status --short
git diff --stat origin/main...HEAD
git diff --name-only origin/main...HEAD
git log --oneline origin/main..HEAD
```

Confirm no `.env`, runtime data, screenshots, reports, traces, or unrelated
files are staged.

- [ ] **Step 8: Commit verification fixes/docs**

```powershell
git add -- docs/dev_commands.md
git commit -m "test: verify signal listing detail UX"
```

Run this only if `docs/dev_commands.md` changed. Defect fixes are committed in
the owning task immediately after their RED/GREEN cycle; omit this final
commit if verification produces no documentation change.
