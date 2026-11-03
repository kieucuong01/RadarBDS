# Mobile Maps safe layout — 2026-11-03

Requested follow-up to the GA4/GSC/default-layer release:

- All new Maps entries default to satellite. Explicit shared views retain their
  base, center and zoom.
- Planning-only openings (listings hidden) keep the selected area's center and
  zoom two levels closer, bounded at 14–16 for city/ward frames. Whole-province
  land-use openings move one level closer with a cap of 14. Listing browsing
  retains the existing area frame; switching visibility does not reframe Maps.
- On phones, the full-width white header begins at the top edge and includes
  the safe-area inset. Shared CSS variables place the toolbar and Leaflet
  controls below it. Base-layer control stays on the right, zoom on the left,
  and loading occupies the space between those controls below the toolbar.
- The listing-count status sits above the layer dock including bottom safe
  area. Concurrent listing loading yields to the planning activity indicator.
  Popovers open below their own toolbar, and the short-screen rail stays compact.

Verification: existing headless layout tests cover 327×709 and 390×844 with
top/bottom safe-area equivalents, plus 320×568. Assertions check full-width white
header, vertical ordering, loader clearance from base/zoom, count/dock clearance
and opacity rail bounds. JS tests check satellite defaults, closer hidden-listing
frames and shared-view behavior. Shared asset versions are updated together.

The user-supplied screenshot is the reference for the reported overlaps. Local
browser control is disabled in Work settings, so manual Safari/device testing
and interactive final screenshots remain unverified. This does not change user
browser settings. Preserve the existing QH SDĐ 2030 default and ranh-thửa-off state.
