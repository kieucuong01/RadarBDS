# Signal Detail Production Regression Repair Design

**Date:** 2026-07-29

**Status:** Approved in conversation; written-spec review pending

**Surfaces:**

- dashboard signal modal opened from `Săn Deal`;
- dashboard signal modal opened from `Tin rao`;
- standalone `/listing/<id>` page.

## Goal

Repair the production regressions in the signal-detail experience without
replacing the existing modal, changing listing-data rules, or introducing a
second card/map implementation.

The repaired release must:

1. render the `Vị trí BĐS` map in the dashboard modal after detail hydration;
2. share only the canonical internal `/listing/<id>` URL;
3. render modal and standalone comparables with the shared `Săn Deal` signal
   card;
4. give missing and broken comparable images a consistent default image;
5. remove inherited link underlines from comparable cards;
6. make carousel navigation clearly visible;
7. keep price-history source links on one line;
8. add an in-map fullscreen control.

## Production Evidence And Root Causes

The production behavior was reproduced on listing `63537` from both dashboard
tabs and on `/listing/63537`.

### Dashboard modal

- The map section had a valid 260-pixel canvas but no Leaflet children and no
  location copy.
- The API returned a valid `ward`-precision `map_location`.
- Comparable elements had the legacy `sm-comp-row` class instead of the shared
  `scard signal-shared-card` template.
- The dashboard still advertised
  `modal.js?v=favorite-listings-20260715`, although the new modal behavior was
  committed later.

The primary modal regression is stale asset identity: browsers can keep the
old modal implementation because the modal asset version was never advanced.
The new location-map, signal-card, and carousel modules cannot help when the
cached modal orchestration never calls them.

The finalized `_openSignalFromData` flow also updates only
`#signalModal.dataset.listingId`. The nested `[data-listing-actions]` element
remains initialized with an empty listing ID, so the share controller cannot
construct its canonical URL.

### Standalone listing detail

- Comparable cards already use the shared renderer, proving the renderer and
  comparable payload are available.
- Because `openMode: "link"` creates an `<a class="scard">`, the page's default
  anchor decoration is inherited by all card text.
- Missing images render the empty-media copy, while broken remote images have
  no runtime fallback.
- Carousel arrows are small and remain in a header that can scroll out of
  view; the bottom dots are too subtle to communicate navigation.
- `.ph-lot-link` was measured at about 18 pixels while its content required
  about 31 pixels, and `white-space` was `normal`; this forces `Tin gốc` onto
  two lines.
- The Leaflet map is present, but no fullscreen control is registered.

## Chosen Approach

Use a narrow shared-component repair.

Do not:

- redirect dashboard card clicks away from the modal;
- create separate modal-only card markup;
- duplicate the standalone detail template inside the modal;
- change comparable ranking, valuation, redaction, map-location resolution,
  or database schema;
- add a new map vendor or fullscreen dependency.

This approach fixes the shared orchestration and presentation boundaries while
preserving the current backend contracts.

## Design

### 1. Asset identity and cache invalidation

Advance the cache-busting version for every changed signal-detail asset:

- dashboard `RADAR_ASSETS.modal`;
- `detail_location_map.js`;
- `signal_card.js`;
- `comparable_carousel.js`;
- `listing_detail_actions.js` when its contract changes;
- `modal.css`;
- `cards.css`.

Use the same release token on the dashboard and `/listing/<id>` for a shared
asset. This ensures both surfaces load the same implementation after deploy
and prevents an older cached modal from orchestrating newer modules.

Structure tests must assert the new modal asset token so a future modal change
cannot ship under the obsolete July 15 identity.

### 2. Modal detail orchestration

Keep one `_openSignalFromData` path for both `Săn Deal` and `Tin rao`.

On every modal open:

1. validate and store the listing ID on `#signalModal`;
2. synchronize that ID to `[data-listing-actions]`;
3. reset or unmount the previous location map;
4. show loading states for detail, history, and comparables;
5. hydrate `/api/listing/<id>`;
6. mount `RadarDetailLocationMap` from `map_location`;
7. mount `RadarComparableCarousel` from `/api/history/<id>`;
8. preserve the existing history-state and close behavior.

Async results must verify that the modal still displays the same listing
before modifying the DOM. Opening another card quickly must not allow an older
map or comparable response to overwrite the current listing.

When map data is unavailable, keep the honest no-location message. Do not
invent a fallback coordinate.

### 3. Canonical sharing

The action controller resolves the current listing ID at click time, not only
at page initialization.

Resolution order:

1. action-root `data-listing-id`;
2. nearest signal modal/page container `data-listing-id`;
3. configured `getListingId` callback when supplied.

Only a positive safe integer is accepted. The shared URL is always:

```text
<current public origin>/listing/<id>
```

Copy and Facebook use that same value. Dashboard query parameters, original
listing URLs, and `<link rel="canonical">` from `/` are never used.

The Facebook target remains:

```text
https://www.facebook.com/sharer/sharer.php?u=<encoded canonical listing URL>
```

### 4. Shared comparable card media and link styling

`RadarSignalCard.render` remains the only comparable-card renderer.

For media:

- always render an image element;
- use the listing thumbnail when present;
- use the standard Radar default image when no thumbnail exists;
- replace a remote image with the same default when `error` fires;
- remove the error handler after fallback to prevent loops;
- keep a stable aspect ratio to avoid layout shift.

The empty-media overlay may retain a short `Chưa có ảnh` label, but it must sit
over the default image rather than an unstyled blank panel.

For linked cards:

- `.scard` and its normal states use `text-decoration: none`;
- nested title, price, and chip text do not inherit link underlines;
- keyboard focus remains visible;
- hover does not reintroduce an underline.

The modal carousel uses `openMode: "modal"` and the standalone carousel uses
`openMode: "link"`.

### 5. Carousel visibility

Keep the current paging contract:

- desktop: six cards, three columns by two rows;
- tablet: four cards, two columns by two rows;
- mobile: one card.

Improve controls without adding a carousel library:

- previous/next buttons are at least 44 by 44 pixels;
- buttons use a solid high-contrast surface and clear disabled state;
- status reads `Trang n / N`;
- the control bar remains visually attached to the comparable heading;
- bottom dots are larger, with a high-contrast active indicator;
- keyboard arrows and touch swipe remain supported;
- no horizontal page scrollbar is introduced.

The controls stay hidden when there is only one page.

### 6. Compact price-history rows

Keep the existing timeline content and ordering.

On desktop:

- date and timeline label remain grouped in `.ph-main`;
- price, change, and `Tin gốc` occupy max-content columns;
- `Tin gốc` uses `white-space: nowrap` and a minimum intrinsic width;
- the grid may give more width to `.ph-main`, but must not push the source link
  to a second line.

On narrow screens, the source link may move to a dedicated grid position, but
its two words still remain on one line.

### 7. Fullscreen map control

Add a small Leaflet-style control inside the map, labelled
`Toàn màn hình bản đồ`.

Behavior:

- use the browser Fullscreen API on the map canvas when supported;
- call `map.invalidateSize()` after entering or exiting fullscreen;
- update `aria-pressed` and the accessible label;
- allow `Escape` through the browser's native fullscreen behavior;
- prevent the control click from dragging or zooming the map;
- if the Fullscreen API is unavailable, keep the normal map and do not show a
  broken control.

The same adapter serves the modal and `/listing/<id>`.

## Error Handling

- A failed map vendor load keeps the accuracy copy and shows the existing retry
  action.
- A missing or invalid listing ID disables share with
  `Không tạo được liên kết.` rather than sharing `/` or a source URL.
- A failed comparable image silently switches once to the default image.
- An empty comparable list keeps the existing honest empty state.
- Existing report submission behavior is unchanged.

## Test Strategy

### Automated regression tests

Add failing tests before production changes for:

1. dashboard modal asset identity is newer than the obsolete July 15 token;
2. both card entry flows use the same `_openSignalFromData` orchestration;
3. modal action-root ID synchronization;
4. canonical copy and Facebook URLs equal `/listing/<id>`;
5. modal location hydration calls the shared map adapter;
6. modal comparables mount through `RadarComparableCarousel` and
   `RadarSignalCard`;
7. shared cards render a default image for missing media;
8. image errors invoke the one-time fallback;
9. linked `.scard` elements have no underline;
10. carousel controls expose the larger/status UI while retaining page sizes;
11. `Tin gốc` remains nowrap in desktop and mobile CSS;
12. the fullscreen control enters/exits fullscreen and invalidates map size.

Run the existing signal-detail, listing-detail-map, comparable-carousel,
listing-actions, signal-card, refactor-structure, and listing-map tests.

### Rendered QA

Production-equivalent browser QA covers:

- desktop modal opened from `Săn Deal`;
- desktop modal opened from `Tin rao`;
- desktop `/listing/<id>`;
- one mobile viewport for modal and standalone detail;
- map marker and fullscreen enter/exit;
- share menu, copied canonical URL, and Facebook sharer URL;
- comparable card class, fallback image, no underline, next/previous controls;
- `Tin gốc` staying on one line;
- console warnings/errors before and after interaction.

No real bad-listing report is submitted during QA.

## Release And Rollback

The release remains a normal code-only production deploy. No database
migration or env change is required.

Release evidence must include:

- local regression tests and JavaScript syntax checks;
- pushed commit and production HEAD equality;
- active `radar-bds.service`;
- internal dashboard/signals/detail smoke;
- public dashboard and `/listing/<id>` HTTP 200;
- browser evidence from both dashboard tabs and standalone detail;
- public asset URLs carrying the new release token.

If the standard VPS Git remote alias fails, use the validated git-bundle
fallback with the existing dirty-worktree guard and rollback trap.

Rollback restores the previous code commit and restarts the service. The
existing `LISTING_REPORT_HASH_SECRET` remains unchanged.
