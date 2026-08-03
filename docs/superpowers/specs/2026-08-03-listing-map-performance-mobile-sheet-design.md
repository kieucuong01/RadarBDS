# Listing Maps Performance and Mobile Sheet Design

**Date:** 2026-08-03

**Status:** Conversational design approved by the user on 2026-08-03; pending written-spec review

**Scope:** Homepage `Xem trên Maps` for both `Săn Deal` and `Tin rao`, including browser rendering, the responsive location directory, marker-to-listing interaction, mobile safe areas, tests, rollout, and production verification

## 1. Problem and Evidence

The Maps API is no longer the dominant delay. Production measurement of the larger `Tin rao` map showed that `/api/map-listings?...mode=all` completed in roughly 560-768 ms and transferred about 38 KB compressed, but the browser then synchronously created a very large duplicated location directory.

Measured production state before this change:

| Surface | Observed result |
|---|---:|
| Map listings | 7,783 |
| Grouped locations | 1,837 |
| Rendered location buttons | 3,674 |
| Total document nodes after render | about 22,920 |
| Desktop directory nodes | about 9,204 |
| Mobile directory nodes | about 9,204 |
| Marker-render long task | about 74 ms |
| Directory-render long task | about 243 ms |

The duplication occurs because `panelTargets()` returns both the desktop panel and the mobile sheet. `renderGroupDirectory()` then renders every location into both targets even though CSS displays only one of them.

The mobile marker flow has a second defect. At a rendered 390x844 viewport:

| Element | Measured result |
|---|---:|
| Fixed homepage bottom navigation | 71 px high; top at 773 px |
| Maps mobile sheet | bottom at 836 px |
| Sheet/navigation overlap | 63 px |
| First selected listing card | top 711 px; bottom 823 px |
| Portion of first card hidden by navigation | about 50 px |

The Maps workspace sets `body.listing-map-open`, but unlike the listing modal it does not hide the fixed homepage navigation. The navigation has `z-index: 998`, above the Maps workspace and mobile sheet, so it visibly covers selected listing content.

## 2. Goals and Success Criteria

Make the existing full-dataset Maps experience responsive without changing its data, filtering, authorization, or listing-detail behavior.

Release criteria:

- Keep all locations and markers from the current API response available on the map; do not replace them with zoom-dependent server filtering in this release.
- Make the map usable within 1.2 seconds after a warm-CDN launcher click on the production test connection for both `Săn Deal` and `Tin rao`.
- Do not block the main thread for more than 50 ms while building markers or the location directory after the API response.
- Render the location directory only in the active responsive surface.
- Initially render at most 100 location buttons; reveal further locations in batches of 100 through `Xem thêm`.
- On mobile, tapping a marker must reveal the selected group and a fully visible first listing card without overlap from the global bottom navigation.
- At 390x844 and 375px-wide viewports, the selected sheet must remain inside the visual viewport and respect the device safe area.
- Preserve filters, map bounds, item selection, the existing listing modal, browser Back, Escape/close behavior, and focus restoration.
- Preserve one summary request per Maps open. Resizing must not issue a second API request.

This browser optimization reduces CPU, memory, and interaction delay for every client. It does not by itself prove that 5,000 simultaneous Maps cache misses can be served by the origin; that capacity remains governed by the separately designed read model, shared caches, Nginx/Cloudflare behavior, and controlled load-test gates.

## 3. Chosen Design

### 3.1 Render only the active responsive directory

Replace the always-two-target rendering contract with one active target:

- desktop above 760 px uses `#listingMapPanel`;
- mobile at or below 760 px uses `#listingMapMobileSheet`;
- the inactive target is cleared and receives no directory or listing-card nodes;
- a `matchMedia` change re-renders the cached current view into the new active target without refetching data;
- loading, empty, error, summary, directory, and selected-group states all use the same active-target rule.

The implementation retains the latest successful summary payload and current selected group so a real orientation/viewport change can reconstruct the correct visible state. Each open receives a generation token. Delayed rendering from a closed, reopened, or superseded map must stop when its token is no longer current.

### 3.2 Bound directory work with progressive disclosure

The directory keeps the API's current stable location order but does not create all buttons at once.

- Initial visible count: 100 locations.
- `Xem thêm 100 vị trí` appends the next 100.
- The final action uses the remaining count in its label.
- Each append uses a `DocumentFragment` and yields between batches when the frame budget is exhausted.
- Returning from a selected group restores the prior directory position and visible-count state for the same Maps open.
- Closing and reopening Maps resets the directory to the first 100 locations.

The summary still reports the complete mapped/unmapped counts. `Xem thêm` controls only directory DOM creation; it never changes which markers exist or which results count toward the summary.

### 3.3 Preserve every marker while yielding to the browser

Continue using Leaflet Canvas (`preferCanvas: true`) and the existing marker style and click behavior. The payload retains all map locations.

Marker creation becomes cooperative:

1. calculate complete bounds from the payload;
2. create markers in bounded batches, yielding through `requestAnimationFrame` between batches;
3. keep the map pannable after the first batch rather than waiting for every marker;
4. show lightweight progress until all markers are installed;
5. stop immediately if the map is closed or a newer render generation starts.

This is progressive client rendering, not marker omission or geographic clustering. All markers from the response become available within the same open operation, while no single batch owns the main thread long enough to freeze taps or scrolling.

### 3.4 Mobile Maps becomes a self-contained full-screen tool

While `body.listing-map-open` is active at mobile widths:

- hide `.mobile-bottom-nav` and `.floating-actions`;
- keep the Maps close button visible and at least 44x44 px;
- use dynamic viewport units with a safe fallback;
- pad the sheet bottom by at least `env(safe-area-inset-bottom)`;
- do not disable browser pinch zoom.

The global bottom navigation belongs to the page behind the modal Maps tool. Hiding it removes the measured 63 px collision, prevents accidental tab changes through an `aria-modal` surface, and recovers more map/sheet space than offsetting the sheet above the navigation.

### 3.5 Two-state mobile sheet

The mobile sheet has explicit `collapsed` and `expanded` states.

**Collapsed state**

- prioritizes the visible map;
- shows a compact sheet header, summary, and a clear `Xem danh sách vị trí` action;
- does not make a long nested directory the default mobile scroll surface;
- uses a decorative handle only; dragging is not required.

**Expanded state**

- opens to approximately 58-62 dynamic viewport height, capped so the Maps header and a useful portion of the map remain visible;
- opens automatically when a marker or directory location is selected;
- resets the sheet scroll position so the group heading and first listing card are visible;
- provides explicit `Thu gọn` and `Tất cả vị trí` controls;
- expands when the user chooses `Xem danh sách vị trí`;
- keeps the current 20-item group response limit and card appearance.

The first release intentionally avoids swipe-to-drag behavior. Explicit buttons are more predictable, accessible, and less likely to conflict with map panning or nested scrolling.

The state change uses a short transform/opacity transition, disabled under `prefers-reduced-motion: reduce`. The expand/collapse control exposes `aria-expanded`. Selection updates an appropriate live status; pointer marker taps do not unexpectedly steal keyboard focus. Keyboard selection from the directory moves focus into the selected group heading or its back control.

### 3.6 Existing API and product behavior remain unchanged

No Maps API response shape, SQL predicate, tier rule, valuation rule, or redaction behavior changes in this release.

- `mode=signals` continues to use the actionable signal rules and active filters.
- `mode=all` continues to use all-listings visibility rules and active filters.
- Marker selection continues to fetch the compact group-items endpoint.
- Selecting a listing continues to open the existing shared listing modal.
- Guest/Free/VIP/admin field visibility remains unchanged.
- No new crawler, reprocess, extraction, valuation, SEO, or URL behavior is introduced.

## 4. Alternatives Considered

### 4.1 Keep the global mobile bottom navigation and offset the sheet

This would fix direct overlap by adding roughly 71 px plus safe-area spacing to the sheet bottom. It wastes a large part of a small viewport, leaves page-level navigation interactive behind a modal tool, and forces every sheet-height calculation to depend on another component. It is not selected.

### 4.2 Replace the mobile sheet with a full-screen listing takeover

This maximizes card readability but hides the map immediately after marker selection, removing the spatial context that makes the feature useful. It is a larger behavioral change and is not selected.

### 4.3 Add server-side viewport filtering or marker clustering now

This can reduce payload and marker count further, but it changes API semantics, map navigation, caching keys, and result discoverability. Current measurements show duplicated directory DOM is the dominant browser cost, so clustering is deferred until post-release evidence proves it is necessary.

### 4.4 Only remove the duplicate inactive directory

Rendering 1,837 directory entries once would halve the node count, but a synchronous list of that size would still create a noticeable long task and memory cost. Active-only rendering must be combined with 100-item disclosure and batched marker work.

## 5. State, Error, and Cancellation Rules

- Opening Maps creates a new generation, clears stale selection, starts one summary fetch, and shows a cancellable loading state.
- Closing Maps aborts summary/group requests, cancels pending marker/directory batches, removes the Leaflet instance, clears active and inactive targets, restores page focus, and removes the open body class.
- Selecting a group aborts an older group-items request before starting a new one.
- A late response or animation-frame callback must verify the current generation and selected group before mutating DOM.
- A summary failure leaves the Maps shell closable and shows one retry action in the active panel.
- A group-items failure preserves the map and selected marker context, shows a retry/back action, and does not return to a blank sheet.
- A resize/orientation change uses cached payload/state and must not reset the current selection or directory progress.
- Browser Back closes Maps before navigating away, preserving the existing history contract.

## 6. Accessibility and Mobile Interaction Requirements

- All visible controls have an accessible name and a minimum 44x44 px touch target.
- Expand/collapse state is represented programmatically with `aria-expanded`.
- The sheet has a labeled heading for directory and selected-group states.
- Loading and completion changes use the existing status/live-region behavior without announcing every marker batch.
- Focus remains trapped/restored according to the existing modal contract.
- `Escape`, Maps close, and browser Back remain equivalent close paths.
- Reduced-motion users receive no sheet animation.
- The map and sheet must not introduce horizontal page overflow at 375px or 390px.
- Safe-area padding is applied without disabling user zoom.

## 7. Test-Driven Implementation Requirements

Automated tests must be added first and must fail against the current implementation for the expected reasons.

Required coverage:

- active-target selection returns exactly one responsive panel;
- inactive desktop/mobile target is cleared and receives no generated directory nodes;
- initial directory slice contains at most 100 locations;
- each `Xem thêm` action advances by at most 100 and reports the correct remaining count;
- viewport changes reuse cached summary/selection state and do not call the summary endpoint again;
- marker batching preserves every location and stops for a stale generation;
- close aborts requests and pending batch work;
- marker/directory selection expands the mobile sheet and resets its scroll position;
- mobile open state hides bottom navigation and floating actions;
- mobile selected sheet includes explicit collapse/back controls, safe-area padding, reduced-motion handling, and 44 px targets;
- existing mode validation, filter propagation, history, focus restoration, asset warmup, listing modal opening, and Canvas preference remain passing;
- Maps CSS/JS asset keys are cache-busted together.

## 8. Verification and Release Gates

Local verification:

1. Run focused Maps JS/UI/API/service tests and the relevant homepage regression tests.
2. Run `node --check static/js/main/listing_map.js` and `git diff --check`.
3. Start/restart Flask so rendered asset cache keys are current.
4. Browser-test `Săn Deal` and `Tin rao` on desktop.
5. Browser-test both modes at 390x844 and 375px mobile widths.
6. Verify marker selection, directory selection, `Xem thêm`, expand/collapse, Back, Escape, modal opening, resize/orientation behavior, and a clean application console.

Measured browser gates after the large `Tin rao` summary loads:

- no more than 100 `.listing-map-group-button` elements before `Xem thêm`;
- no full directory duplicated into a hidden responsive target;
- no rendering long task above 50 ms attributable to Maps marker/directory construction;
- mobile bottom navigation and floating actions are not displayed while Maps is open;
- sheet/navigation overlap is 0 px;
- first selected listing card is fully visible within the expanded sheet viewport;
- all response locations are eventually represented by Leaflet marker layers;
- the summary request count remains one per open.

Production release:

1. Commit only scoped source, tests, documentation, and asset-version changes.
2. Fetch and rebase onto current `origin/main`; rerun focused checks.
3. Push and deploy with the standard Radar BDS production script.
4. Confirm `/opt/radar-bds/current`, active `radar-bds.service`, and public API smoke.
5. Repeat desktop and 390x844 production browser verification on both `Săn Deal` and `Tin rao`.
6. Record the deployed commit, DOM counts, long-task results, mobile overlap, API timing, service state, and rollback procedure in the performance/operations documentation for later agents.

## 9. Rollback

Rollback is source-only and data-preserving:

1. revert the Maps JS/CSS/template and asset-version commit;
2. redeploy and restart the service;
3. verify the previous Maps summary, marker selection, listing modal, and both tabs;
4. do not alter PostgreSQL, Redis data, crawler state, listings, valuations, or user data.

If only the new mobile sheet styling is defective, the smallest safe rollback is to remove the new sheet-state rules while retaining active-only directory rendering and the 100-location disclosure. If marker batching is defective, revert it independently while retaining the directory and mobile overlap fixes.
