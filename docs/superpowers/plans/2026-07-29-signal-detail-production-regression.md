# Signal Detail Production Regression Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore the requested signal-detail behavior in both dashboard modal entry paths and `/listing/<id>`, then ship and verify the narrow frontend repair on production.

**Architecture:** Keep the current Flask templates and backend APIs. Repair the shared frontend boundary by forcing a single release identity, synchronizing modal listing state, resolving share IDs at click time, and extending the existing `RadarSignalCard`, `RadarComparableCarousel`, and `RadarDetailLocationMap` adapters. Both modal and standalone detail continue to consume the same modules; no second renderer, map provider, database field, or API response shape is introduced.

**Tech Stack:** Flask/Jinja templates, browser JavaScript modules exposed through `window`, Node contract tests, pytest structure/UI tests, CSS, Leaflet, native Fullscreen API, PowerShell release scripts, systemd/Nginx production.

## Global Constraints

- Work only in `.worktrees/signal-detail-ux`; preserve the divergent main checkout and unrelated user changes.
- Use `apply_patch` for source edits and stage only the files named by this plan.
- Follow red-green-refactor for every behavior change: add the focused assertion, run it and observe the expected failure, then implement the smallest repair.
- Keep both dashboard tabs on the same `_openSignalFromData` modal path.
- Keep `RadarSignalCard.render` as the only comparable-card template.
- Keep desktop comparable pagination at six cards, arranged as three columns by two rows; tablet remains four; mobile remains one.
- Share only `<public-origin>/listing/<positive-id>`. Never share the dashboard query URL, the source listing URL, or `/`.
- Do not change report submission behavior and do not submit a real bad-listing report during QA.
- Do not modify database schema, listing data, valuation, comparable ranking, map-location resolution, environment files, or `LISTING_REPORT_HASH_SECRET`.
- This is a UI-only release; do not run a production reprocess.
- Use one cache token, `signal-detail-regression-20260729`, for every shared asset changed in this repair.
- Run Browser-driven rendered QA before declaring local or production completion.
- Release completion requires commit/push/deploy identity, active service, endpoint smoke, and rendered production evidence.

---

## Task 1: Lock the release identity and modal orchestration contract

**Files:**

- Modify: `tests/test_signal_detail_ui.py`
- Modify: `templates/index.html`
- Modify: `templates/listing_detail.html`
- Modify: `static/js/main/modal.js`

### Test-first steps

- [ ] Add `test_signal_detail_assets_share_current_release_identity` to `tests/test_signal_detail_ui.py`.

  The test reads both templates and requires the new release token on:

  ```python
  shared_assets = (
      "detail_location_map.js",
      "signal_card.js",
      "comparable_carousel.js",
      "listing_detail_actions.js",
  )
  for asset in shared_assets:
      needle = asset + "') }}?v=signal-detail-regression-20260729"
      assert needle in modal
      assert needle in detail
  assert "modal.js') }}?v=signal-detail-regression-20260729" in modal
  assert "favorite-listings-20260715" not in modal[
      modal.index("window.RADAR_ASSETS"):modal.index("window.RADAR_STYLES")
  ]
  ```

  Use direct substring assertions matching the actual Jinja source; do not render the template for this static contract.

- [ ] Extend the modal structure test to require all of these orchestration markers in `static/js/main/modal.js`:

  ```python
  assert "actions.dataset.listingId = listingId" in module
  assert "RadarDetailLocationMap.unmount" in module
  assert "modal.dataset.listingId !== listingId" in module
  assert "RadarComparableCarousel" in module
  ```

- [ ] Run the focused test and confirm red:

  ```powershell
  $py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
  & $py -X utf8 -m pytest tests\test_signal_detail_ui.py -q
  ```

  Expected failure: obsolete modal token and missing modal action-root synchronization.

### Minimal implementation

- [ ] In `templates/index.html`, change `window.RADAR_ASSETS.modal` to:

  ```jinja2
  modal: "{{ url_for('static', filename='js/main/modal.js') }}?v=signal-detail-regression-20260729",
  ```

- [ ] In both templates, apply `?v=signal-detail-regression-20260729` to the four shared JavaScript modules.

- [ ] Apply the same token to the `modal.css` and `cards.css` URL variables in both templates. Do not alter unrelated asset tokens.

- [ ] At the start of `_openSignalFromData`, validate the ID once and synchronize both state holders:

  ```javascript
  const listingId = String(Number(d.id));
  if (!/^[1-9]\d*$/.test(listingId)) return;
  modal.dataset.listingId = listingId;
  const actions = modal.querySelector('[data-listing-actions]');
  if (actions) actions.dataset.listingId = listingId;
  const locationSection = modal.querySelector('[data-detail-location]');
  if (locationSection && window.RadarDetailLocationMap) {
    window.RadarDetailLocationMap.unmount(locationSection);
  }
  ```

  Use `listingId` instead of `d.id` for detail/history/memo requests and modal-state guards.

- [ ] Preserve the existing `hydrateSignalDetail` and `loadSignalHistory` adapters. Confirm their async result handlers compare the current `modal.dataset.listingId` before mounting map/history/comparables.

- [ ] Run the focused test again and confirm green.

- [ ] Run JavaScript syntax:

  ```powershell
  node --check static\js\main\modal.js
  ```

- [ ] Commit:

  ```powershell
  git add tests/test_signal_detail_ui.py templates/index.html templates/listing_detail.html static/js/main/modal.js
  git commit -m "fix: refresh signal modal detail runtime"
  ```

---

## Task 2: Resolve canonical share links from current modal state

**Files:**

- Modify: `tests/js/test_listing_detail_actions.js`
- Modify: `static/js/main/listing_detail_actions.js`
- Verify: `static/js/main/modal.js`

### Test-first steps

- [ ] Add pure ID-resolution assertions:

  ```javascript
  assert.equal(api.resolveListingId('42', '99', '100'), 42);
  assert.equal(api.resolveListingId('', '99', '100'), 99);
  assert.equal(api.resolveListingId('', '', '100'), 100);
  assert.equal(api.resolveListingId('bad', '', 0), null);
  ```

- [ ] Add an assertion proving both share targets derive from the same canonical listing URL:

  ```javascript
  const canonical = api.canonicalListingUrl(
    'https://radarbds.vn/?signal=42',
    api.resolveListingId('', '42', null),
  );
  assert.equal(canonical, 'https://radarbds.vn/listing/42');
  assert.equal(
    api.facebookShareUrl(canonical),
    'https://www.facebook.com/sharer/sharer.php?u=https%3A%2F%2Fradarbds.vn%2Flisting%2F42',
  );
  ```

- [ ] Run and confirm red:

  ```powershell
  node tests\js\test_listing_detail_actions.js
  ```

  Expected failure: `resolveListingId` is not exported.

### Minimal implementation

- [ ] Add a pure resolver:

  ```javascript
  function resolveListingId(primary, container, configured) {
    return positiveInteger(primary)
      || positiveInteger(container)
      || positiveInteger(configured)
      || null;
  }
  ```

- [ ] In `bindShare`, resolve the listing ID at click time:

  ```javascript
  function listingId() {
    const container = root.closest('[data-listing-id]');
    const configured = typeof config.getListingId === 'function'
      ? config.getListingId()
      : null;
    return resolveListingId(
      root.dataset.listingId,
      container && container.dataset.listingId,
      configured,
    );
  }
  ```

- [ ] Keep `canonicalListingUrl` protocol validation and positive-integer validation unchanged.

- [ ] Keep the existing failure copy `Không tạo được liên kết.` when no valid ID can be resolved.

- [ ] Export `resolveListingId`, run the Node contract test, and confirm green.

- [ ] Run syntax:

  ```powershell
  node --check static\js\main\listing_detail_actions.js
  ```

- [ ] Commit:

  ```powershell
  git add tests/js/test_listing_detail_actions.js static/js/main/listing_detail_actions.js
  git commit -m "fix: share canonical listing links"
  ```

---

## Task 3: Give every shared comparable card resilient media and clean link styling

**Files:**

- Modify: `tests/js/test_signal_card.js`
- Modify: `tests/test_signal_detail_ui.py`
- Modify: `static/js/main/signal_card.js`
- Modify: `static/css/main/cards.css`

### Test-first steps

- [ ] Add missing-image assertions:

  ```javascript
  const withoutImage = api.render({ ...item, primary_img: '', imgs: [] }, {
    context: 'comparable',
    openMode: 'link',
    showFavorite: false,
    showContact: false,
  });
  assert.match(withoutImage, /<img[^>]+class="sc-img/);
  assert.match(withoutImage, /data-default-image="true"/);
  assert.match(withoutImage, /Chưa có ảnh/);
  ```

- [ ] Add broken-image fallback assertions:

  ```javascript
  assert.match(comparable, /onerror="RadarSignalCard\.useFallbackImage\(this\)"/);
  assert.match(api.defaultImage(), /^data:image\/svg\+xml/);
  const fakeImage = { onerror: () => {}, src: '/bad.jpg', dataset: {}, classList: { add() {} } };
  api.useFallbackImage(fakeImage);
  assert.equal(fakeImage.onerror, null);
  assert.equal(fakeImage.src, api.defaultImage());
  ```

- [ ] Add CSS contract assertions in `tests/test_signal_detail_ui.py`:

  ```python
  assert ".scard," in cards
  assert "text-decoration: none" in cards
  assert ".scard:focus-visible" in cards
  ```

- [ ] Run and confirm red:

  ```powershell
  node tests\js\test_signal_card.js
  & $py -X utf8 -m pytest tests\test_signal_detail_ui.py -q
  ```

### Minimal implementation

- [ ] Define one self-contained SVG data URI inside `signal_card.js`. It must use Radar-neutral colors, contain no external request, and remain valid in HTML attributes after escaping.

- [ ] Add:

  ```javascript
  function defaultImage() {
    return DEFAULT_IMAGE;
  }

  function useFallbackImage(image) {
    if (!image) return;
    image.onerror = null;
    image.src = DEFAULT_IMAGE;
    image.dataset.defaultImage = 'true';
    if (image.classList) image.classList.add('is-default');
  }
  ```

- [ ] Always render the `.sc-img` element. Use the default image when `primary_img`/`imgs[0]` is absent, set `data-default-image`, and wire the one-time `onerror` handler for remote images.

- [ ] Preserve the stable media aspect ratio and keep `Chưa có ảnh` only for the default state.

- [ ] Add card-link styling:

  ```css
  .scard,
  .scard:visited,
  .scard:hover {
    color: inherit;
    text-decoration: none;
  }

  .scard:focus-visible {
    outline: 3px solid rgba(99, 102, 241, 0.55);
    outline-offset: 3px;
  }
  ```

- [ ] Export the two media helpers, run both red tests again, and confirm green.

- [ ] Run syntax:

  ```powershell
  node --check static\js\main\signal_card.js
  ```

- [ ] Commit:

  ```powershell
  git add tests/js/test_signal_card.js tests/test_signal_detail_ui.py static/js/main/signal_card.js static/css/main/cards.css
  git commit -m "fix: harden comparable card media"
  ```

---

## Task 4: Clarify carousel controls and compact price-history links

**Files:**

- Modify: `tests/js/test_comparable_carousel.js`
- Modify: `tests/test_signal_detail_ui.py`
- Modify: `static/js/main/comparable_carousel.js`
- Modify: `static/css/main/modal.css`

### Test-first steps

- [ ] Add status-label assertions:

  ```javascript
  assert.equal(api.statusLabel(0, 3), 'Trang 1 / 3');
  assert.equal(api.statusLabel(2, 3), 'Trang 3 / 3');
  assert.equal(api.statusLabel(0, 0), '');
  ```

- [ ] Add CSS contract assertions:

  ```python
  assert "min-width: 44px" in modal_css
  assert "min-height: 44px" in modal_css
  lot_link_rule = modal_css[modal_css.index(".sm-price-history .ph-lot-link"):]
  assert "white-space: nowrap" in lot_link_rule
  assert "min-width: max-content" in lot_link_rule
  ```

- [ ] Run and confirm red:

  ```powershell
  node tests\js\test_comparable_carousel.js
  & $py -X utf8 -m pytest tests\test_signal_detail_ui.py -q
  ```

### Minimal implementation

- [ ] Add and export:

  ```javascript
  function statusLabel(page, total) {
    const count = Math.max(0, Number(total) || 0);
    return count ? `Trang ${clampPage(page, count) + 1} / ${count}` : '';
  }
  ```

- [ ] Use `statusLabel(currentPage, pages.length)` in `update()`. Keep page sizes, keyboard arrows, swipe threshold, page clamping, and hidden single-page controls unchanged.

- [ ] Make previous/next buttons at least 44 by 44 pixels with solid contrast, visible border/shadow, clear hover/focus, and muted disabled state.

- [ ] Make the active carousel dot at least 10 pixels in its minor dimension and clearly higher contrast than inactive dots.

- [ ] Keep status and arrows visually grouped with the section heading at desktop and mobile widths.

- [ ] Update desktop history grid source column to `max-content` and add:

  ```css
  .sm-price-history .ph-lot-link {
    min-width: max-content;
    white-space: nowrap;
  }
  ```

- [ ] Ensure mobile rules do not override `white-space: nowrap`.

- [ ] Run both focused tests and syntax check:

  ```powershell
  node --check static\js\main\comparable_carousel.js
  node tests\js\test_comparable_carousel.js
  & $py -X utf8 -m pytest tests\test_signal_detail_ui.py -q
  ```

- [ ] Commit:

  ```powershell
  git add tests/js/test_comparable_carousel.js tests/test_signal_detail_ui.py static/js/main/comparable_carousel.js static/css/main/modal.css
  git commit -m "fix: clarify comparable and history controls"
  ```

---

## Task 5: Add the native fullscreen map control

**Files:**

- Modify: `tests/js/test_detail_location_map.js`
- Modify: `tests/test_signal_detail_ui.py`
- Modify: `static/js/main/detail_location_map.js`
- Modify: `static/css/main/modal.css`

### Test-first steps

- [ ] Add pure Fullscreen API tests with fakes:

  ```javascript
  (async () => {
    let entered = 0;
    let exited = 0;
    const canvas = { requestFullscreen: async () => { entered += 1; } };
    const doc = { fullscreenElement: null, exitFullscreen: async () => { exited += 1; } };
    assert.equal(api.fullscreenAvailable(canvas, doc), true);
    assert.equal(await api.toggleFullscreen(canvas, doc), true);
    assert.equal(entered, 1);

    doc.fullscreenElement = canvas;
    assert.equal(await api.toggleFullscreen(canvas, doc), false);
    assert.equal(exited, 1);
    assert.equal(api.fullscreenAvailable({}, doc), false);
  })();
  ```

- [ ] Extend Python structure assertions:

  ```python
  assert "data-map-fullscreen" in module
  assert "Toàn màn hình bản đồ" in module
  assert "fullscreenchange" in module
  assert ":fullscreen" in css
  ```

- [ ] Run and confirm red:

  ```powershell
  node tests\js\test_detail_location_map.js
  & $py -X utf8 -m pytest tests\test_signal_detail_ui.py -q
  ```

### Minimal implementation

- [ ] Add:

  ```javascript
  function fullscreenAvailable(canvas, doc) {
    return Boolean(
      canvas
      && typeof canvas.requestFullscreen === 'function'
      && doc
      && typeof doc.exitFullscreen === 'function'
    );
  }

  async function toggleFullscreen(canvas, doc) {
    if (!fullscreenAvailable(canvas, doc)) return null;
    if (doc.fullscreenElement === canvas) {
      await doc.exitFullscreen();
      return false;
    }
    await canvas.requestFullscreen();
    return true;
  }
  ```

- [ ] Register a Leaflet-style control only when fullscreen is supported. The control button must:

  - include `data-map-fullscreen`;
  - start with `aria-label="Toàn màn hình bản đồ"` and `aria-pressed="false"`;
  - stop click and double-click propagation through Leaflet DOM helpers;
  - call `toggleFullscreen(canvas, canvas.ownerDocument)`;
  - switch its label to `Thoát toàn màn hình bản đồ` while active.

- [ ] On `fullscreenchange`, update accessibility state and schedule `map.invalidateSize()` after the browser has resized the canvas.

- [ ] Store the fullscreen listener cleanup with the mounted map/section and remove it in `unmount` before removing the map.

- [ ] Add fullscreen layout rules:

  ```css
  .sm-location-map:fullscreen {
    width: 100vw;
    height: 100vh;
    border-radius: 0;
    background: #0f172a;
  }
  ```

  Style the in-map control as a high-contrast 44-pixel target without obscuring layer controls.

- [ ] Export the pure helpers, run both focused tests, and confirm green.

- [ ] Run syntax:

  ```powershell
  node --check static\js\main\detail_location_map.js
  ```

- [ ] Commit:

  ```powershell
  git add tests/js/test_detail_location_map.js tests/test_signal_detail_ui.py static/js/main/detail_location_map.js static/css/main/modal.css
  git commit -m "feat: add fullscreen listing map control"
  ```

---

## Task 6: Run focused automated verification

**Files:**

- Verify only; repair failures in the owning task's files.

- [ ] Run all signal-detail JavaScript contract tests:

  ```powershell
  node tests\js\test_detail_location_map.js
  node tests\js\test_listing_detail_actions.js
  node tests\js\test_signal_card.js
  node tests\js\test_comparable_carousel.js
  ```

  Expected: four contract/renderer success messages and exit code 0.

- [ ] Run syntax on every touched JavaScript file:

  ```powershell
  node --check static\js\main\modal.js
  node --check static\js\main\detail_location_map.js
  node --check static\js\main\listing_detail_actions.js
  node --check static\js\main\signal_card.js
  node --check static\js\main\comparable_carousel.js
  ```

- [ ] Run focused Python UI/map/comparable tests:

  ```powershell
  $py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
  & $py -X utf8 -m pytest `
    tests\test_signal_detail_ui.py `
    tests\test_refactor_structure.py `
    tests\test_listing_detail_map.py `
    tests\test_listing_comparables.py `
    tests\test_listing_map_api.py `
    tests\test_listing_map_context.py `
    tests\test_listing_map_schema.py `
    tests\test_listing_map_service.py `
    tests\test_listing_map_ui.py -q
  ```

- [ ] Run whitespace/scope checks:

  ```powershell
  git diff --check
  git status --short
  git diff --stat origin/main...HEAD
  ```

- [ ] If a test fails, return to the owning task, add the missing focused regression where necessary, make the smallest correction, and rerun the full Task 6 matrix.

---

## Task 7: Verify the rendered local experience

**Files:**

- Verify only; no production mutation.

- [ ] Confirm the installed local PostgreSQL service is running without printing `.env`:

  ```powershell
  Get-Service postgresql-x64-18
  ```

- [ ] Start the Flask app with Python 3.12 in the feature worktree.

- [ ] Use the Browser skill against `http://127.0.0.1:5000` at a desktop viewport and verify:

  - `Săn Deal` card opens the modal;
  - `Tin rao` card opens the same modal path;
  - each modal map has Leaflet children and a visible marker/precision copy;
  - modal comparable cards use `scard signal-shared-card`;
  - copy share writes `http://127.0.0.1:5000/listing/<id>`;
  - Facebook target contains the encoded same canonical path;
  - `/listing/<id>` comparable card text is not underlined;
  - missing/broken comparable images show the default SVG;
  - carousel controls read `Trang n / N`, are clearly visible, and advance pages;
  - every visible `Tin gốc` remains one line;
  - fullscreen enters and exits, and the map remains correctly sized.

- [ ] Repeat modal and standalone checks at a mobile viewport. Confirm there is no horizontal document overflow and carousel page size is one.

- [ ] Inspect console errors/warnings after map, share, carousel, and fullscreen interactions.

- [ ] Do not submit a real report. Only verify that the report dialog still opens and closes.

- [ ] Stop the local app cleanly.

---

## Task 8: Finalize, push, and deploy the narrow release

**Files:**

- Stage only:
  - `docs/superpowers/specs/2026-07-29-signal-detail-production-regression-design.md`
  - `docs/superpowers/plans/2026-07-29-signal-detail-production-regression.md`
  - `templates/index.html`
  - `templates/listing_detail.html`
  - `static/js/main/modal.js`
  - `static/js/main/detail_location_map.js`
  - `static/js/main/listing_detail_actions.js`
  - `static/js/main/signal_card.js`
  - `static/js/main/comparable_carousel.js`
  - `static/css/main/modal.css`
  - `static/css/main/cards.css`
  - `tests/test_signal_detail_ui.py`
  - `tests/js/test_detail_location_map.js`
  - `tests/js/test_listing_detail_actions.js`
  - `tests/js/test_signal_card.js`
  - `tests/js/test_comparable_carousel.js`

- [ ] Fetch `origin` and compare `HEAD`, `origin/main`, and the feature branch. If `origin/main` advanced, rebase only after confirming the worktree is clean and preserve all unrelated changes.

- [ ] Run the entire Task 6 matrix once more after any rebase.

- [ ] Review the staged patch:

  ```powershell
  git diff --cached --check
  git diff --cached --stat
  git status --short --branch
  ```

- [ ] Create one final integration commit only if verification produced uncommitted fixes:

  ```powershell
  git commit -m "fix: repair signal detail production regressions"
  ```

- [ ] Push the verified feature HEAD to `origin/main`:

  ```powershell
  git push origin HEAD:main
  ```

- [ ] Run the standard deployment:

  ```powershell
  .\scripts\deploy_production.ps1
  ```

- [ ] If the VPS Git alias cannot resolve, do not retry the same broken path. Use the documented `ship_production.ps1`/git-bundle fallback with its dirty-worktree guard and rollback trap.

- [ ] Do not run schema initialization beyond what the deploy wrapper already guards, and do not run `radar.py reprocess`.

---

## Task 9: Prove the production result

**Files:**

- Verify only.

- [ ] Verify release identity:

  - local pushed commit equals `origin/main`;
  - VPS `/opt/radar-bds/current` HEAD equals the same commit;
  - `radar-bds.service` is active.

- [ ] Verify internal and public HTTP:

  ```text
  GET http://127.0.0.1:5000/api/dashboard
  GET http://127.0.0.1:5000/api/signals?page=1&limit=3
  GET http://127.0.0.1:5000/api/listing/63537
  GET https://radarbds.vn/
  GET https://radarbds.vn/listing/63537
  ```

  Expected: all return 200 and the listing API still includes valid `map_location`.

- [ ] Inspect production HTML and confirm every changed asset URL carries `v=signal-detail-regression-20260729`.

- [ ] Use Browser production QA at desktop:

  1. open listing modal from `Săn Deal`;
  2. assert map Leaflet children, shared comparable-card classes, and canonical copy/Facebook targets;
  3. close modal, open from `Tin rao`, and repeat the same assertions;
  4. open `/listing/63537`;
  5. assert computed `text-decoration-line: none` for comparable anchors;
  6. assert every comparable image has non-zero rendered/natural dimensions or the default SVG source;
  7. advance next/previous and confirm `Trang n / N`;
  8. assert each `.ph-lot-link` has `scrollWidth <= clientWidth + 1`;
  9. enter/exit map fullscreen and confirm Leaflet tiles/marker remain laid out.

- [ ] Repeat the essential modal, standalone, carousel, and no-overflow checks at a mobile viewport.

- [ ] Inspect console logs after all interactions; record only relevant warnings/errors.

- [ ] Do not click the final Facebook confirmation and do not submit a report.

- [ ] Record final evidence in the handoff:

  - deployed commit SHA;
  - test counts/commands;
  - production service and HTTP results;
  - both modal entry paths;
  - canonical share URL shape;
  - map/fullscreen result;
  - comparable card/fallback/slider result;
  - history nowrap result;
  - explicit confirmation that env, DB, and `LISTING_REPORT_HASH_SECRET` were unchanged.
