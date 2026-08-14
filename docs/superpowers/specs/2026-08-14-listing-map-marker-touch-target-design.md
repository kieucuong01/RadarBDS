# Listing Maps Marker Touch Target Design

**Date:** 2026-08-14  
**Status:** Approved for planning

## Goal

Make listing markers easier to see at close zoom and easier to select at every
zoom level. A user can open a location group by clicking or tapping either the
visible marker or its visible price/count label.

## Current behavior

- Listing locations use Leaflet `circleMarker` objects for the colored dots.
- Price and count labels are separate Leaflet `DivIcon` markers.
- Labels are currently non-interactive and CSS disables their pointer events.
- Marker radii remain fixed while zoom changes.
- Label visibility and collision avoidance are recalculated after zoom or pan.

## Approved behavior

### Marker sizing

Use the existing precision hierarchy as the base size:

- Exact and road: radius 6.
- Landmark: radius 7.
- Ward: radius 8.

Apply a small progressive close-zoom bonus:

- Zoom 14–15: no bonus.
- Zoom 16–17: radius +1.
- Zoom 18–19: radius +2.

Recalculate visible marker radii on `zoomend`. Colors, borders and the relative
size hierarchy between precision types remain unchanged.

### Unified selection area

- Keep the colored marker clickable with its current keyboard behavior.
- Make every rendered price/count label interactive.
- Clicking or tapping a label invokes the same group-selection path as clicking
  its colored marker.
- Show a pointer cursor on interactive labels.
- Do not create a separate invisible hit circle; the selectable area is the
  union of the colored marker and the visible label.
- A label hidden by collision avoidance adds no invisible interception area.

### Interaction constraints

- Label interaction must not propagate into an unrelated map click.
- Map pan and zoom behavior remains unchanged.
- Selecting a label opens the existing item panel or mobile bottom sheet; it
  does not introduce a new modal or navigation path.
- Existing admin marker-edit behavior is outside this change.

## Implementation boundaries

- Update `static/js/main/listing_map.js` to calculate zoom-aware radii, refresh
  marker sizes on zoom, and bind label selection.
- Update `static/css/main/listing_map.css` to allow pointer interaction and show
  the appropriate cursor on rendered labels.
- Update the Maps JS/CSS asset version in `templates/index.html` so production
  clients receive the new behavior immediately.
- Do not change API contracts, database schema, registry data, marker grouping,
  label content, collision rules or default map zoom.

## Verification

- Unit-test radius values at zoom 14, 16 and 18 for every precision hierarchy.
- Contract-test that rendered labels are interactive and use the same selection
  path as colored markers.
- Preserve existing compact label and marker hierarchy tests.
- Run `node --check`, focused Maps pytest and `git diff --check`.
- Browser-test production-shaped desktop and mobile viewports:
  - marker sizes increase progressively at close zoom;
  - clicking the colored marker opens its group;
  - clicking the price/count label opens the same group;
  - panning and zooming remain usable;
  - labels hidden by collision do not block the map.

## Acceptance criteria

- At zoom 16–17 each marker radius is exactly one pixel larger than its base.
- At zoom 18–19 each marker radius is exactly two pixels larger than its base.
- Every visible price/count label is a working click/touch target for its group.
- Existing precision colors, hierarchy, label density and map navigation remain
  unchanged.
