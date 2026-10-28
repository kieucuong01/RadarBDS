# Maps: viewport loading

## Interaction

Dashboard filters apply to the opening markers, recent cards and grouped details.
The opening map retains the current Tin rao/Săn Deal mode, date window, city/ward,
price/area ranges, keyword, source and other permitted filters. Geographic filters
also frame the initial map. Historic ward bounds are
read from existing checked-in boundary references, with a centre fallback when a
boundary is unavailable. A small `/api/map-initial-bounds` request avoids scanning
listings to determine the opening view. No source GIS request is made at runtime.

Only a real user `dragstart` switches listing scope to independent viewport
exploration with the public three-month window. Zooming, resizing, initial framing,
parcel selection and other programmatic movements preserve the filtered scope.
Existing tier/source/public-visibility and actionable-signal rules apply in both.
“Về vùng đã lọc” restores the active sidebar filters and opening area. Changing a
sidebar filter also returns to filtered scope, cancels stale requests and reframes
the latest area. A late framing response must not undo a subsequent manual drag.
The sidebar stays visible on desktop; the Maps filter button opens the existing
filter sheet on mobile/tablet. Normal Maps is non-modal so keyboard users can
reach the sidebar; focus mode keeps its own focus trap.
For a single selected ward, opening zoom is at least 14: a narrow portrait screen
does not shrink the ward to show unnecessary surrounding city area. Returning to
the opening area uses the same framing and emits one final viewport change.

Only partition planning is on initially. General urban planning is off. Catalogue
entries remain available regardless of city/ward selection, but raster images
are attached only when their native bounds intersect the current view, with a
5% spatial buffer. Panning or zooming out can therefore reveal other wards/cities
without selecting them. Off-screen image layers are removed in Leaflet's correct
remove-then-off order; immutable production URLs retain browser caching. PDF
alternatives and parcel selection keep their existing source and precision limits.

## Requests and limits

- Query after `moveend` settles for 350 ms, not continuously during dragging.
- Abort previous requests and use sequence checks for newer views, mode changes,
  closing/reopening and initial framing. Never refit the map from a late listing
  response.
- Round viewport edges outward to four decimal places for stable bounded keys.
- `scope=filtered` combines bbox with the existing parsed/tier-clamped filters.
  Plain bbox queries retain independent exploration semantics. Summary markers,
  recent cards and grouped details always share the current scope.
- One summary request includes markers and the first 20 recent cards from that
  viewport. There is no separate global `/api/listings` or `/api/signals` request
  for the map's recent rail.
- Apply geographic conditions to effective coordinates **after** listing/group
  manual overrides. Both read-model and legacy paths retain their normal policy.
- Return at most 1,000 grouped positions; show an explicit zoom-in hint if capped.
- Group detail requests retain their location key and current viewport, with the
  existing 50-card page cap and field redaction.
- Validate finite WGS84 bbox values, clip to supported Bình Dương bounds, and include
  bbox in the existing tier/mode/version-aware 128-entry server cache. A viewport
  outside coverage returns an empty result, not listings from the old area.
- No schema changes, GIS token integration, dataset-version bumps or public-edge
  cache eligibility changes are needed. Existing runtime images are unchanged.

## Local verification

For a Tân An opening at a measured 706 × 698 CSS viewport, with browser cache
disabled, the old all-GIS default would load 23 images / 3,942,850 file bytes. The
viewport implementation requested 10 visible/intersecting partition images,
about 1,921,321 HTTP wire bytes, and no general-plan image. This is roughly half
the initial raster transfer in this local scenario; it is not a production timing
or Core Web Vitals claim. Zooming out requested 18 visible layers and one updated
map-data request. More visible area naturally requires more images.

Earlier viewport-only API observations (before the filter-first correction):
initial Tân An bounds ~67 ms; one viewport result with
20 recent cards ~25 KB / 552 ms cold and ~192 ms repeated. A dashboard context
with an impossible keyword and price below one billion still produced viewport
cards (19 of 20 above that old price), including adjacent wards. The old dashboard
filters remain untouched.

Automated checks cover bbox validation/clipping, initial multi-area bounds,
post-override SQL scope, filtered and independent viewport queries, source/tier policy, URL scope,
partition-only defaults, off-screen image exclusion, panning and zoom-out loads,
independent sources/opacity and removed-layer listener cleanup. Browser checks
also inspect real request URLs, visible image counts and card changes.

The filter-first browser check used a Bến Cát price cap of one billion. Opening
and zoom requests retained `city`, `price_max`, date/type filters and
`scope=filtered`, returning zero matching positions in that local snapshot.
A real drag issued a plain bbox query and returned 12 nearby listings, including
prices above the original cap. Editing the sidebar cap to 1.5 immediately
returned to a single filtered summary request. The sidebar stayed visible at
1280px; its mobile sheet was interactive at 390px with no horizontal overflow.
