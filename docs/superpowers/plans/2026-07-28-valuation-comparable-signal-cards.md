# Valuation Comparable Signal Cards Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show up to six redacted valuation comparables to every user as full Săn Deal-style cards that open the internal listing detail page, arranged as a 3-column desktop grid.

**Architecture:** Keep valuation selection and ranking in `services/valuation_tool.py`, but shape each selected row through the existing signal-card formatter boundary in `services/market_data.py`. Render the returned compact card contract with a valuation-specific JavaScript adapter that reuses `cards.css`, while the valuation page owns only grid placement, responsive behavior, empty state, and click analytics.

**Tech Stack:** Flask/Jinja, PostgreSQL SQL, Python `unittest`/`pytest`, vanilla JavaScript, Node `node:assert`, existing Radar BDS CSS.

## Global Constraints

- Guest, Free, VIP, and Admin all receive up to six comparable cards; `comparables_locked` is always `false`.
- Guest, Free, and VIP must never receive original URLs, phone numbers, or contact data embedded in titles.
- Admin keeps the existing raw-data boundary, while every card link still uses the internal `/listing/<id>` route.
- Comparables remain canonical lots only, baseline-quality eligible, ranked by same ward/property type, road tier, nearby area, and recency.
- Desktop uses three columns by two rows, tablet uses two columns, and mobile uses one column with no horizontal scrolling.
- Cards reuse Săn Deal visual classes and information hierarchy, but omit Lưu and Ráp mối actions.
- The whole card is a keyboard-focusable semantic link to `/listing/<id>`.
- Analytics payloads must not include listing titles, prices, phone numbers, URLs, or listing IDs.
- Do not add a database migration, map, PDF report, saved valuation history, or changes to the shared valuation formula.

---

### Task 1: Public Six-Comparable API Contract

**Files:**
- Modify: `tests/test_valuation_tool_service.py`
- Modify: `services/market_data.py`
- Modify: `services/valuation_tool.py`

**Interfaces:**
- Consumes: `services.market_data.redact_for_tier(record, tier)` and the existing signal-row formatting rules.
- Produces: `format_signal_card_record(row, primary_img=None, tier="guest") -> dict` and `_load_comparables(target, limit=6, tier="guest") -> list[dict]`.
- API result: `comparables_locked: false` and `comparables: list[dict]` for all tiers.

- [ ] **Step 1: Write the failing all-tier API contract test**

  Replace the old guest-lock assertion with a complete comparable fixture and literal assertions:

  ```python
  def test_all_tiers_get_six_internal_comparable_cards_with_non_admin_redaction(self):
      comparable = {
          "id": 10,
          "title": "Bán đất 0909 123 456",
          "url": "https://facebook.example/listing",
          "contact_phone": "0909123456",
          "detail_href": "/listing/10",
          "price_ty": 1.8,
          "actual_ppm2": 18.0,
          "fair_ppm2": 20.0,
          "mos_pct": 10.0,
          "area_m2": 100,
          "primary_img": "/static/data/images/thumbs/10.webp",
      }
      # Patch the fitted engine and comparable loader, call guest/free/vip/admin,
      # and assert every response is unlocked and contains the comparable.
      # For guest/free/vip assert "0909" and "facebook.example" are absent.
      # For admin assert raw contact data remains.
      # For every tier assert detail_href == "/listing/10".
  ```

  Add a loader-call assertion that each tier requests `limit=6` and passes its tier into `_load_comparables`.

- [ ] **Step 2: Run the focused test and verify RED**

  Run:

  ```powershell
  $py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
  & $py -X utf8 -m pytest tests\test_valuation_tool_service.py -q
  ```

  Expected: FAIL because guest comparables are locked and the loader still defaults to five.

- [ ] **Step 3: Add a public signal-card formatter boundary**

  In `services/market_data.py`, rename the implementation to a public function and keep the private compatibility alias:

  ```python
  def format_signal_card_record(r, primary_img=None, tier: str = "guest"):
      # Existing _format_signal_row body, including redact_for_tier().
      ...

  _format_signal_row = format_signal_card_record
  ```

  Add `detail_href = f"/listing/{int(r['id'])}"` to the returned record. This is an internal path and must remain present after non-admin redaction.

- [ ] **Step 4: Expand the comparable query and shape real card data**

  Change `_load_comparables` to accept `limit=6` and `tier`. Keep the bounded `candidate_listings AS MATERIALIZED` CTE before valuation/image lookups. Select all formatter inputs from the listing plus the newest valuation result:

  ```sql
  latest_valuation AS (
      SELECT v.*,
             ROW_NUMBER() OVER (
                 PARTITION BY v.listing_id
                 ORDER BY v.computed_at DESC, v.id DESC
             ) AS valuation_rank
        FROM valuation_results v
        JOIN candidate_listings c ON c.id = v.listing_id
  )
  ```

  Include price-drop defaults, trust/legal/source-quality fields, and lateral primary-image/image-count lookups. Continue filtering `_baseline_quality_flags(source_quality_flags)` in Python before slicing to `limit`.

  Shape each surviving row with:

  ```python
  format_signal_card_record(
      row,
      resolve_image_url(
          _row_value(row, "primary_local_path"),
          _row_value(row, "primary_img_url"),
          prefer_thumb=True,
      ),
      tier=tier,
  )
  ```

  Preserve canonical-only and hidden/sold/blacklisted exclusions.

- [ ] **Step 5: Unlock comparables for every tier**

  In `estimate_property_value`, always call:

  ```python
  comparables = _load_comparables(target, limit=6, tier=tier)
  ```

  Return `"comparables_locked": False`. Do not apply a second redaction pass because the shared formatter already enforces the tier boundary.

- [ ] **Step 6: Run service tests and verify GREEN**

  Run:

  ```powershell
  & $py -X utf8 -m pytest tests\test_valuation_tool_service.py tests\test_market_data_trust.py -q
  ```

  Expected: all tests pass; non-admin fixtures contain no contact data.

- [ ] **Step 7: Commit the backend contract**

  ```powershell
  git add services/valuation_tool.py services/market_data.py tests/test_valuation_tool_service.py
  git commit -m "Expose six valuation comparable cards"
  ```

---

### Task 2: Valuation Signal-Card Renderer

**Files:**
- Create: `static/js/valuation_comparable_card.js`
- Create: `tests/js/test_valuation_comparable_card.js`

**Interfaces:**
- Consumes: comparable card records produced by `format_signal_card_record`.
- Produces: `window.RadarValuationComparableCard.renderCard(row, index) -> string` and `.renderGrid(rows) -> string`.

- [ ] **Step 1: Write the failing Node behavior test**

  Use `node:assert`, `fs`, and `vm` to execute the browser module with a real `window` object. Assert observable HTML:

  ```javascript
  assert.match(html, /<a[^>]+class="[^"]*scard/);
  assert.match(html, /href="\/listing\/42"/);
  assert.match(html, /sc-img-wrap/);
  assert.match(html, /mos-badge/);
  assert.match(html, /sc-valuation/);
  assert.match(html, /meta-chip/);
  assert.doesNotMatch(html, /<button/);
  assert.doesNotMatch(html, /Ráp mối|Lưu/);
  assert.match(html, /&lt;script&gt;/);
  assert.doesNotMatch(html, /<script>/);
  ```

  Also assert invalid/missing IDs return an empty string, and `renderGrid` caps output at six anchors.

- [ ] **Step 2: Run the Node test and verify RED**

  Run:

  ```powershell
  node tests/js/test_valuation_comparable_card.js
  ```

  Expected: FAIL because `static/js/valuation_comparable_card.js` does not exist.

- [ ] **Step 3: Implement the renderer adapter**

  Create an IIFE that exposes only the two public functions. Use local HTML escaping and numeric formatting. The output must:

  - use `<a class="scard valuation-comparable-card">`;
  - use `row.detail_href` only when it exactly matches `/listing/<row.id>`, otherwise derive the internal path from the validated integer ID;
  - render thumbnail or the existing property placeholder;
  - render MOS/new/source/time/quality badges when fields are present;
  - render title, actual price, fair price, property/area/road/frontage/depth/legal chips;
  - include `data-comparable-position="<1..6>"`;
  - contain no action buttons and no external/source URL.

- [ ] **Step 4: Run renderer tests and syntax checks**

  Run:

  ```powershell
  node tests/js/test_valuation_comparable_card.js
  node --check static/js/valuation_comparable_card.js
  ```

  Expected: both commands exit 0.

- [ ] **Step 5: Commit the renderer**

  ```powershell
  git add static/js/valuation_comparable_card.js tests/js/test_valuation_comparable_card.js
  git commit -m "Add valuation comparable card renderer"
  ```

---

### Task 3: Full-Width Responsive Grid and Page Wiring

**Files:**
- Modify: `templates/valuation_tool.html`
- Modify: `static/js/valuation_tool.js`
- Modify: `static/css/valuation_tool.css`
- Modify: `tests/test_valuation_tool_ui.py`

**Interfaces:**
- Consumes: `window.RadarValuationComparableCard.renderGrid(rows)`.
- Produces: `#comparablesSection` full-width result section and `valuation_comparable_click` analytics event.

- [ ] **Step 1: Write failing rendered-page and interaction contract tests**

  Update the UI test to render the actual Jinja page through Flask test client where possible, then assert:

  ```python
  assert 'id="comparablesSection"' in html
  assert 'id="comparableList"' in html
  assert 'id="comparablesLock"' not in html
  assert 'id="unlockComparablesBtn"' not in html
  assert "css/main/cards.css" in html
  assert "js/valuation_comparable_card.js" in html
  ```

  Extend the Node renderer/wiring test to provide a minimal DOM, call the real rendering path, and verify the list receives card anchors and a click tracks only:

  ```javascript
  {
    position: 1,
    property_type: "dat_nen",
    source: "valuation_result"
  }
  ```

  It must not include listing ID, title, price, URL, or phone.

- [ ] **Step 2: Run UI tests and verify RED**

  Run:

  ```powershell
  & $py -X utf8 -m pytest tests\test_valuation_tool_ui.py -q
  node tests/js/test_valuation_comparable_card.js
  ```

  Expected: FAIL because the lock UI still exists and the new assets/section are not wired.

- [ ] **Step 3: Move comparables below the two-panel workspace**

  In `templates/valuation_tool.html`:

  - remove the gated copy, `#comparablesLock`, and `#unlockComparablesBtn`;
  - add a sibling section inside `.valuation-workspace`:

  ```html
  <section class="tool-panel valuation-comparables-section" id="comparablesSection" hidden>
    <div class="comparables-heading">
      <div>
        <p class="panel-kicker">Dữ liệu đối chiếu</p>
        <h2>Mẫu so sánh cùng phân khúc</h2>
      </div>
      <p>Tối đa 6 lô đã lọc trùng và ẩn thông tin liên hệ.</p>
    </div>
    <div class="valuation-comparable-grid" id="comparableList"></div>
  </section>
  ```

  Load `css/main/cards.css`, then `css/valuation_tool.css`. Load `valuation_comparable_card.js` before `valuation_tool.js`, and bump cache versions.

- [ ] **Step 4: Wire rendering and privacy-safe analytics**

  Replace the compact-row renderer with:

  ```javascript
  list.innerHTML = window.RadarValuationComparableCard.renderGrid(rows);
  section.hidden = false;
  ```

  Hide the section when there are no rows. Remove unlock code and the `comparables_locked` analytics dimension. Add delegated click tracking on the grid using the card's `data-comparable-position`; send only position, property type, and fixed source.

- [ ] **Step 5: Add responsive grid CSS**

  Reuse the signal-card stylesheet variables by mapping them on `.valuation-page`. Add:

  ```css
  .valuation-comparables-section {
    grid-column: 1 / -1;
    padding: 22px;
  }

  .valuation-comparable-grid {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 18px;
  }
  ```

  At the existing tablet breakpoint use two columns; at `max-width: 700px` use one column. Keep cards `min-width: 0`, full-card focus visibility, and no horizontal scrolling.

- [ ] **Step 6: Run UI and syntax verification**

  Run:

  ```powershell
  & $py -X utf8 -m pytest tests\test_valuation_tool_ui.py -q
  node tests/js/test_valuation_comparable_card.js
  node --check static/js/valuation_tool.js
  node --check static/js/valuation_comparable_card.js
  ```

  Expected: all commands exit 0.

- [ ] **Step 7: Commit the page integration**

  ```powershell
  git add templates/valuation_tool.html static/js/valuation_tool.js static/css/valuation_tool.css tests/test_valuation_tool_ui.py
  git commit -m "Render valuation comparables as signal cards"
  ```

---

### Task 4: Regression, Browser Smoke, and Production Release

**Files:**
- Verify only: all changed files
- Release: current `main` branch through `scripts/deploy_production.ps1`

**Interfaces:**
- Consumes: final API and browser UI.
- Produces: verified production release at `https://radarbds.vn/dinh-gia-bds`.

- [ ] **Step 1: Run the full valuation regression set**

  ```powershell
  $py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
  & $py -X utf8 -m pytest tests/test_valuation_tool.py tests/test_valuation_tool_service.py tests/test_valuation_tool_ui.py tests/test_valuation_tool_cache.py -q
  & $py -X utf8 -m py_compile app.py services/valuation_tool.py services/market_data.py
  node --check static/js/valuation_tool.js
  node --check static/js/valuation_comparable_card.js
  node tests/js/test_valuation_comparable_card.js
  ```

  Expected: zero failures and zero syntax errors.

- [ ] **Step 2: Run guest and authenticated API security smokes**

  Verify each non-admin payload contains up to six items, has `comparables_locked=false`, uses only `/listing/<id>` detail links, and contains no phone-like token or original/source URL. Verify admin keeps its current raw-data boundary.

- [ ] **Step 3: Run desktop and mobile browser smoke**

  At desktop width, submit the form and verify six cards display as three columns by two rows. At 390 px and 375 px, verify one column, no horizontal overflow, result focus behavior, image fallback, and successful navigation from a card to `/listing/<id>`.

- [ ] **Step 4: Review the exact diff and working tree**

  ```powershell
  git diff --check
  git status --short
  git log -8 --oneline
  ```

  Confirm only the plan, valuation backend, formatter boundary, valuation assets/template, and related tests are included.

- [ ] **Step 5: Push and deploy production**

  ```powershell
  git push origin main
  .\scripts\deploy_production.ps1
  ```

  If the normal VPS pull cannot resolve the git host, use the repository's existing bundle fallback procedure without changing unrelated production files.

- [ ] **Step 6: Verify live production**

  Confirm:

  - `https://radarbds.vn/dinh-gia-bds` returns 200 and loads the new assets;
  - guest valuation returns `comparables_locked=false` with up to six redacted cards;
  - warm API response remains within the prior hot-request envelope;
  - desktop is three columns, mobile is one column with no overflow;
  - card click opens `/listing/<id>`;
  - `valuation_comparable_click` sends no sensitive fields.
