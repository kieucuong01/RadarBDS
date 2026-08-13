# Listing Maps Minimum Price Zoom Design

## Goal

Open Listing Maps close enough for price labels to be eligible immediately, even when that means some markers in the filtered dataset start outside the visible map viewport.

## Scope

This is a client-only adjustment to the shared Listing Maps workspace used by Săn Deal and Tin rao on desktop and mobile.

No API, location registry, marker grouping, modal, directory, collision, or label-content behavior changes are included.

## Initial View Rule

The map continues to call `fitBounds` first so Leaflet chooses the center from all mapped locations. The post-fit zoom helper then applies this rule:

```text
initial zoom = min(max(fitted zoom + 1, 13), 16)
```

Consequences:

- fitted zoom below 13 opens at zoom 13;
- fitted zoom 13 opens at zoom 14;
- fitted zoom 14 opens at zoom 15;
- fitted zoom 15 or above opens at zoom 16;
- markers outside the initial viewport are intentionally allowed;
- the user can still pan or zoom out to reach all remaining markers.

The map center remains the center selected from the complete filtered location bounds. Empty datasets retain the existing Bình Dương fallback view.

## Price Label Relationship

Price labels remain eligible from `PRICE_LABEL_MIN_ZOOM = 13`. Enforcing an initial minimum zoom of 13 therefore makes valid price labels available as soon as Maps opens.

Existing collision placement still decides which eligible labels fit without overlap. The change guarantees price-label eligibility, not that every price label can be drawn simultaneously in a crowded viewport.

## Tests

Update the pure JavaScript zoom-helper test to cover:

- fitted zoom 8, 11, and 12 -> initial zoom 13;
- fitted zoom 13 -> initial zoom 14;
- fitted zoom 15 and 16 -> initial zoom 16;
- invalid/non-numeric fitted zoom -> safe minimum zoom 13.

Run the focused Listing Maps JavaScript and UI suites, JavaScript syntax validation, then verify real browser behavior for:

- Săn Deal desktop;
- Tin rao desktop;
- Săn Deal mobile;
- Tin rao mobile.

Browser evidence must confirm the initial Leaflet zoom is at least 13, the map canvas has non-zero dimensions, and compact price labels appear without a manual zoom action when valid price data exists.

## Release

Bump the Listing Maps JavaScript asset version so production clients do not retain the earlier zoom helper. After push and deployment, verify the public HTML and new JavaScript asset return HTTP 200 and repeat the browser checks against production.
