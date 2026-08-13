# Listing Maps Zoom, Compact Header, Location, and Share Design

## Goal

Give Săn Deal and Tin rao a denser map-first workspace that opens at zoom 14, preserves the four precision legends, exposes the user's current position inside the map, and creates a shareable URL that reopens the same filtered Maps view.

## Scope

This design changes the shared Listing Maps workspace on desktop and mobile:

- initial map zoom;
- compact workspace header;
- singleton-road price-label verification;
- an in-map `Vị trí của tôi` control;
- an in-map `Chia sẻ` control;
- shared-link startup and history behavior.

It does not change geocoding, the road/area registry, marker grouping, listing modal behavior, map APIs, or the definition of the four location precision levels.

## Initial Map View

The map continues to derive its center from the complete filtered location bounds. After `fitBounds`, the initial zoom is:

```text
initial zoom = min(max(fitted zoom + 1, 14), 16)
```

This intentionally allows markers outside the initial viewport. Users can still pan and zoom out. Empty datasets retain the existing Bình Dương fallback center, but open at zoom 14.

Price labels remain eligible from zoom 13. Opening at zoom 14 therefore makes eligible labels available immediately while retaining the existing collision-avoidance behavior.

## Marker Labels

Existing exact-position labels remain unchanged: two compact rows showing price and area on the first row, then price per square metre on the second row.

A `Theo đường` group containing exactly one listing uses the same two-row price label when valid price, area, and price-per-square-metre values are present. A road group with multiple listings continues to show its listing count. `Theo khu vực` and `Theo phường` continue to show counts only.

The marker label element receives a precision-specific CSS class so focused browser checks can distinguish a singleton-road price label from an exact-position label without altering visible content.

## Compact Header

The current eyebrow, large title, and description become one semantic title row:

```text
Radar BĐS Maps · Xem lô đất trên bản đồ   Chính xác  Theo đường  Theo khu vực  Theo phường   [Đóng]
```

- The title remains a single `h2` for the dialog label.
- The explanatory paragraph is removed, together with the obsolete `aria-describedby` reference.
- All four precision legends remain visible on desktop and mobile.
- Desktop uses one compact horizontal row.
- Mobile hides only the title suffix `· Xem lô đất trên bản đồ`; `Radar BĐS Maps`, the four legends, and the close button remain visible.
- The mobile legend is single-line and horizontally scrollable when necessary instead of wrapping and taking map height.
- The existing status row remains unchanged.

## In-map Controls

A Leaflet control stack is added to the map's top-left corner after the native zoom control. Its vertical order is:

1. native `+` / `−` zoom control;
2. `Vị trí của tôi` icon button;
3. `Chia sẻ` icon button.

Both buttons use Leaflet-compatible dimensions and styling, keyboard-focus states, `type="button"`, tooltips, and Vietnamese `aria-label` values. They stay inside the map on desktop and mobile and must not cover the side panel.

### Vị trí của tôi

Location access begins only when the user presses the control.

- Use `navigator.geolocation.getCurrentPosition` with high accuracy requested, a finite timeout, and no forced cached result.
- While waiting, disable repeated requests and expose a loading state.
- On success, draw one blue position dot plus a translucent accuracy circle, then pan to the coordinates and set the zoom to at least 16 without zooming out from a closer current zoom.
- Pressing the control again requests a fresh position and recenters the map; it updates the existing layers rather than adding duplicates.
- Permission denied, unavailable position, timeout, and unsupported browser states show a concise message inside the map and restore the button state.
- The coordinates and accuracy remain in browser memory only. They are not sent to Radar BĐS APIs, analytics, the share URL, or persistent storage.
- Closing Maps removes the position layers and invalidates late geolocation callbacks so they cannot mutate a destroyed map.

The accuracy circle is exclusively a user-location aid. Listing markers continue not to use approximate geographic regions.

### Chia sẻ

The share button builds a public URL from the filter snapshot captured when Maps opened.

- Preserve the active dataset tab (`signals` or `all`) and every current user-facing filter, including repeated parameters such as wards and property types.
- Add `map=1` so the receiving page opens Listing Maps automatically.
- Remove API-only paging or map-directory parameters if present.
- Do not include the current GPS coordinates, accuracy, selected marker/group, map center, or zoom.
- Use `navigator.share` when available. If it is unavailable, copy the URL to the clipboard and show `Đã sao chép` inside the map.
- Treat a user-cancelled native share as a neutral outcome. Clipboard/share failures show a concise retry message.

## Shared-link Startup and History

The dashboard boot process reads `map=1` separately from user-facing filters and removes it before constructing API filter queries.

Automatic opening is allowed only for `tab=signals` and `tab=all`. The page first hydrates the URL filters and activates the requested tab, then opens Maps using the normal current-filter snapshot.

The initial shared-link open does not push a duplicate browser-history entry. While that Maps workspace is open:

- closing it removes only `map=1` from the current URL with `replaceState`;
- the active tab and filters remain in the URL and in the dashboard;
- the user stays on the same dashboard state instead of being sent to the homepage;
- a normal Maps open from the dashboard retains the current push/back behavior.

This requires an explicit initial/shared-open option rather than reusing `fromPopstate`, so Back-button semantics remain unambiguous.

## Implementation Boundaries

Expected changes are limited to:

- `templates/partials/listing_map_workspace.html` for the compact semantic header;
- Listing Maps CSS for the compact header, mobile legend, controls, location layers, and in-map feedback;
- `static/js/main/listing_map.js` for zoom 14, controls, geolocation, URL sharing, cleanup, and shared-open history mode;
- `static/js/main/boot.js` for parsing `map=1` and opening Maps after tab/filter hydration;
- the focused Listing Maps tests;
- Listing Maps JS/CSS asset-version keys.

No backend endpoint or database migration is required.

## Verification

### Automated

- Zoom helper: fitted zooms below 14 open at 14; higher fitted zooms retain the `+1`, capped at 16; invalid input falls back to 14.
- Marker model: exact and singleton-road groups with complete values produce the compact price label at zoom 14; multi-listing road and all area/ward groups produce count labels.
- Share URL: preserves tab and repeated filters, adds `map=1`, and never contains latitude, longitude, accuracy, marker, or viewport state.
- Shared startup: `map=1` is not sent as an API filter and opens only Săn Deal/Tin rao.
- History: shared-link open skips `pushState`; close removes `map=1` without losing filters. Normal open/close keeps the existing push/back contract.
- Geolocation helpers: success zoom is at least 16, user-facing error mapping is stable, stale callbacks are ignored, and cleanup removes the location layers.
- Update the existing source guard that forbids `L.circle`: permit one accuracy circle owned by user location while continuing to prove listing markers do not create circles.
- HTML/CSS checks: one labelled dialog title, no stale description reference, all four legends remain present and are not hidden by the mobile media rule.

### Browser

Verify both Săn Deal and Tin rao on desktop and a mobile viewport:

- Maps opens at zoom 14 or closer and the canvas fills the available workspace.
- The compact header remains one row; mobile keeps all four legends available without increasing header height through wrapping.
- A known singleton-road listing displays price, area, and price/m² in two compact rows at the initial zoom.
- The controls appear directly below `+` / `−` in the required order.
- A stubbed successful geolocation shows the blue dot/accuracy circle and recenters at zoom 16 or closer.
- Denied geolocation leaves Maps usable and displays the concise error.
- Share creates a URL with the active filters; opening that URL restores the correct tab, filters, and Maps workspace.
- Closing Maps from the shared URL preserves the dashboard tab/filter state.
- Opening a listing modal from Maps and closing it still returns to the same Maps state.

## Release

Bump both Listing Maps JS and CSS asset versions. Run the focused tests and syntax checks, then push and deploy through the standard production script. Production evidence must distinguish pushed SHA, service state, public HTML/assets returning HTTP 200, and desktop/mobile browser behavior.
