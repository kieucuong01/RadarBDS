# Signal Modal And Listing Detail UX Design

**Date:** 2026-07-29

**Status:** Approved in conversation; written-spec review pending

**Surfaces:**

- signal-detail modal on the dashboard;
- standalone `/listing/<id>` detail page.

## Goal

Bring the signal modal and standalone listing-detail page into one consistent
detail experience:

1. show the listing on the existing Radar BDS map directly below the original
   listing text;
2. move comparable listings to the bottom of the complete detail workspace;
3. render comparable listings with the same card component as the `Săn deal`
   tab;
4. use a 60/40 primary desktop layout;
5. add safe internal sharing;
6. let users report a bad listing through a real, reviewable workflow.

The change must preserve the existing tier redaction, actionable-signal,
location-precision, and human-label boundaries.

## Approved Layout

### Primary detail columns

On desktop, `.sm-content` remains the detail workspace and uses two primary
columns:

- `.sm-left`: 60%;
- `.sm-right`: 40%.

Implement the ratio as `minmax(0, 3fr) minmax(0, 2fr)`.
Existing mobile breakpoints continue to collapse the primary columns to one
column.

Grow the modal from its current 960-pixel maximum to
`min(1240px, calc(100vw - 32px))` on desktop. At widths below the existing
mobile breakpoint it remains a full-viewport detail surface.

### Location section

Add a `Vị trí BĐS` section immediately after the `Nguyên văn tin rao` section
on both surfaces. It remains inside `.sm-left`, because it is part of the
primary listing narrative.

The section contains:

- a lazy Leaflet map using the same OpenStreetMap street and Esri satellite
  layers as the dashboard listing map;
- one marker for the current listing;
- an accuracy label and explanatory copy;
- a street/satellite layer control;
- a useful empty state when no verified derived location is available.

### Comparable section

`So sánh lô tương tự` becomes a direct child of `.sm-content`, after both
`.sm-left` and `.sm-right`. It must not be nested in `.sm-left` or
`.sm-right`.

On desktop the section spans both columns with `grid-column: 1 / -1`, making it
the final content block in the modal and standalone detail card.

The mobile `So sánh` tab is removed because the comparable section is no
longer a column panel. Users reach it by normal vertical scrolling. The
description, history, and advisory tabs keep their current behavior where
applicable.

## Listing Location Contract

Use the implemented listing-map runtime on `origin/main`; do not invent a
second geocoder or write approximate coordinates to `listings`.

Extend the existing listing-detail read model with a nullable
`map_location` object sourced from `listing_map_locations`:

```json
{
  "lat": 10.992,
  "lng": 106.676,
  "precision": "road",
  "label": "Theo tên đường ĐX 43, Phú Lợi",
  "resolver_version": "osm-2026-07-29-v1"
}
```

Allowed precision values remain:

- `exact`: source-provided exact point;
- `road`: deterministic road representative point;
- `ward`: canonical ward center.

The UI must describe road and ward points as approximate. It must not say that
an approximate marker is the parcel position. When `map_location` is null,
show `Chưa xác định được vị trí đủ tin cậy để hiển thị trên bản đồ.` and do not
place a fallback marker.

Both `/api/listing/<id>` and the server-rendered `/listing/<id>` page consume
the same read-model field. Coordinates are already part of the public listing
map contract, but no phone, original URL, contact text, or description is
added to map analytics.

Leaflet and map CSS remain lazy on the dashboard modal. The standalone page
loads the location-map adapter only when a non-null map location exists. The
adapter reuses the existing Radar map vendor configuration and base-layer
contract.

## Comparable Signal Cards

### Shared renderer

Extract or expose one reusable signal-card renderer from the current
`Săn deal` implementation. The dashboard signal feed, modal comparables, and
standalone detail comparables must call that same renderer rather than copy
its HTML.

The comparable adapter disables actions that do not belong in this section,
such as Save and `Ráp mối`, but preserves the normal signal-card presentation:

- thumbnail or standard fallback;
- new-listing, MOS, price-drop, and quality-warning badges;
- title;
- asking price and asking price per square metre;
- fair price and fair price per square metre;
- ward, area/dimensions, road/street, property type, and residential-land
  chips;
- relative age.

The currently viewed listing is not repeated as a comparable card.

### Comparable payload

Extend the existing history/comparable read model to return the compact fields
required by the shared signal-card renderer. Comparable rows use latest
valuation data and the existing image-resolution helper. They remain:

- in the same canonical ward;
- the same property type when known;
- within the current area, unit-price, and road-tier similarity guards;
- not blacklisted, sold, hidden, or known duplicates;
- ranked by the existing comparable score.

Return at most 18 comparable listings. Non-admin payloads expose only internal
`/listing/<id>` detail links and remain redacted. Admin may retain the existing
raw-source boundary, but comparable-card UI always navigates internally.

### Carousel behavior

Comparable cards are paged into a carousel:

- desktop: six cards per slide, arranged as three columns by two rows;
- tablet: four cards per slide, arranged as two columns by two rows;
- mobile: one card per slide.

Only the active slide is presented to assistive technology and keyboard
navigation. Previous/next buttons, slide status, dots, keyboard arrow keys,
and touch swipe are available when there is more than one slide. Controls are
omitted for a single slide.

The carousel does not create a permanent horizontal page scrollbar. Card
height may vary naturally within a slide; content must not be clipped merely
to make rows equal.

Interaction:

- inside the dashboard modal, selecting a comparable opens that listing in the
  existing modal flow without exposing the source URL;
- on `/listing/<id>`, selecting a comparable navigates in the same tab to its
  internal detail route.

## Share Action

Add a `Chia sẻ` button to the action area on both surfaces. It opens a small
accessible menu with:

- `Sao chép liên kết`;
- `Chia sẻ Facebook`.

The canonical shared URL is always:

```text
<public origin>/listing/<validated integer id>
```

It must not use `listing.url`, a Facebook source URL, query parameters from the
current dashboard, or contact data.

Copy uses the Clipboard API when available and a safe selection fallback
otherwise. The UI announces success or failure without replacing the button's
accessible name.

Facebook opens the official sharer URL in a new, isolated window using the
encoded canonical listing URL. Tracking records only action type, page
context, and listing ID; it does not record title, description, coordinates,
price, phone, or source URL.

The menu closes on outside click, `Escape`, item selection, and parent
modal/page teardown. Focus returns to the trigger.

## Bad Listing Report

### User experience

Add a secondary `Báo xấu tin đăng` button to both surfaces. It opens one shared
accessible dialog with a required reason:

- `Đã bán hoặc không còn`;
- `Sai giá hoặc diện tích`;
- `Tin trùng`;
- `Thông tin vị trí sai`;
- `Spam hoặc có dấu hiệu lừa đảo`;
- `Lý do khác`.

An optional note accepts at most 500 Unicode characters. The dialog shows
submitting, success, duplicate, rate-limited, validation-error, and retry
states. A successful report closes the dialog after announcing that Radar BDS
will review it.

Guests and signed-in users may report. The UI never promises that a report
will immediately hide or remove a listing.

### Storage and API

Add a dedicated append-only `listing_reports` table. Do not write reports to
`ai_training_feedback`, `ai_deal_review`, or valuation fields.

Minimum fields:

```text
id
listing_id
user_id nullable
tier
reason
note nullable
status pending|reviewed|dismissed
reporter_key_hash
ip_hash
user_agent
created_at
reviewed_at nullable
reviewed_by nullable
resolution_note nullable
```

`reporter_key_hash` and `ip_hash` use an application-secret-backed hash; raw IP
addresses are not stored in `listing_reports`.

Add:

```text
POST /api/listings/<id>/report
```

The endpoint:

- verifies that the visible listing exists;
- accepts only the allowlisted reason values;
- trims and bounds the optional note;
- accepts JSON only and rejects a present `Origin` header that does not match
  the public application origin;
- rate-limits by reporter key and IP hash;
- treats the same listing/reporter/reason within 24 hours as a duplicate
  success rather than creating another row;
- creates a `pending` report without altering listing visibility, quality
  flags, valuation, or training labels.

Rate limits are five new reports per reporter key per rolling hour and 20 new
reports per IP hash per rolling day. A duplicate within the 24-hour
idempotency window returns the existing success response and does not consume
another allowance.

Operational review is intentionally separated from automatic data actions.
The first release exposes pending reports through:

```text
GET /admin/api/listing-reports?status=pending&page=<n>&limit=<bounded>
```

The response includes report ID, listing ID, reason, note, created time, and
status. It does not add automatic hide, merge, or reprocess actions.

## Accessibility And Responsive Rules

- Every new button has a minimum 44-pixel effective target.
- Map controls, carousel controls, share menu, and report dialog are fully
  keyboard operable.
- Focus is trapped in the report dialog and restored on close.
- Visible focus styles work in light and dark themes.
- Reduced-motion users do not receive animated carousel transitions.
- The modal and standalone page have no horizontal document overflow at
  desktop, tablet, 390-pixel, and 375-pixel widths.
- The standalone mobile fixed action bar wraps or groups secondary actions so
  it does not cover content or shrink labels below usability.

## Error And Empty States

- Missing map location: show the explicit trust-preserving empty state and no
  marker.
- Leaflet or tiles unavailable: keep the location label visible and offer one
  focused retry.
- No comparable listings: show `Chưa có lô tương tự phù hợp.`
- Comparable request failure: keep the rest of the detail view usable and
  offer retry.
- Broken comparable image: use the standard signal-card placeholder.
- Clipboard failure: retain the menu and show manual-copy guidance.
- Facebook popup blocked: keep the canonical URL available for copying.
- Report request failure: preserve the chosen reason and note for retry.

## Security And Data Boundaries

- Guest, Free, and VIP detail/map/comparable responses remain redacted.
- Internal comparable and share links always use validated integer listing
  IDs.
- Report notes are stored and rendered as plain text.
- Public APIs never expose reporter identity, hashes, report notes, or report
  counts.
- Reporting cannot mutate `review_hidden`, `is_blacklisted`, dedup state,
  valuation results, `ai_training_feedback`, or `ai_deal_review`.
- Map analytics keep the existing coordinate and listing-ID restrictions;
  detail-map events use only precision and page context.

## Verification

Follow test-driven development for each behavior.

### Backend

- schema tests for `listing_reports`, indexes, and idempotent migrations;
- listing-detail service/API tests for exact, road, ward, and missing
  `map_location`;
- comparable tests for full compact signal-card shape, redaction, valuation
  fields, images, exclusion rules, ranking, and the 18-item limit;
- report API tests for valid guest/member reports, invalid reasons, note
  bounds, nonexistent/hidden listings, duplicate idempotency, rate limiting,
  raw-IP non-storage, and no writes to protected label/visibility tables.

### JavaScript contracts

- one shared signal renderer serves feed and comparable contexts;
- carousel page sizes, controls, keyboard behavior, swipe threshold, and
  active-slide semantics;
- canonical share URL, clipboard fallback, and encoded Facebook sharer URL;
- report dialog validation, preserved retry state, and safe text rendering;
- detail map precision copy, empty state, and lazy vendor loading.

### Rendered browser QA

Use the in-app Browser plugin against the local app:

1. open a real signal modal with a derived map location and at least seven
   comparable listings;
2. verify 60/40 columns, map placement, precision copy, three-by-two comparable
   slide, next/previous navigation, internal comparable navigation, share
   menu, copy confirmation, Facebook URL, and report submission state;
3. repeat the corresponding checks on `/listing/<id>`;
4. repeat layout, map, carousel swipe, share, report-dialog, overflow, and
   focus checks at 390 and 375 pixels;
5. inspect console warnings/errors and capture desktop and mobile screenshots.

The pre-existing `test_mobile_filter_sheet_scroll_is_isolated_from_signal_tab`
asset-version assertion failed on clean `origin/main` before this work. It is
outside this feature and must be reported separately rather than silently
counted as a regression.

## Implementation Boundary

Included:

- the two detail surfaces;
- shared signal-card extraction needed to prevent UI drift;
- listing-detail map read/adapters;
- comparable payload and carousel;
- share UI;
- bad-listing report storage, public write endpoint, and minimal admin read
  access;
- focused tests and rendered QA.

Excluded:

- changes to valuation formulas or actionable-signal rules;
- new external geocoding;
- writes of derived coordinates into `listings`;
- automatic listing hiding, deduplication, reprocessing, or training labels
  from user reports;
- broad Admin Control Room redesign;
- crawler or source-parser changes;
- production deploy unless separately requested.
