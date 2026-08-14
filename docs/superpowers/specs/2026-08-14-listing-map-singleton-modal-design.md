# Listing Maps Singleton Modal Design

**Date:** 2026-08-14  
**Status:** Approved design, pending written-spec review

## Goal

Reduce one unnecessary interaction when a Maps marker represents exactly one
listing. Selecting an eligible singleton marker opens the existing signal-detail
modal immediately instead of first showing a one-item list.

## Approved scope

Direct modal opening applies only when both conditions are true:

- The marker precision is `exact` or `road`.
- The marker contains exactly one listing.

It does not apply to `landmark` or `ward` markers, even when they contain one
listing. Those markers retain the current item-list panel or mobile bottom sheet
because the user explicitly wants area and ward locations to remain grouped
views. Every marker containing two or more listings also retains the list flow.

The behavior is identical in the `signals` and `all` Maps modes.

## Interaction flow

### Eligible singleton marker

1. The user selects either the marker dot or its visible label.
2. Maps calls the existing `/api/map-listing-items` endpoint for the selected
   group with page 1 and the existing bounded page size.
3. While the request is pending, Maps keeps the current location-directory view
   visible. It does not replace the desktop side panel or expand the mobile
   bottom sheet with a loading or one-item list state.
4. If the response contains exactly one item, Maps passes that item to the
   existing `openListingModal` integration.
5. The standard signal-detail modal opens over the current Maps screen.

The implementation must reuse the existing modal, history handling, tier
redaction and listing-detail rendering. It must not create a second modal or
navigate to `/listing/<id>`.

### Non-eligible marker

Road or exact groups with more than one listing, plus every landmark or ward
group, keep the current loading, list, pagination and error states without
behavioral changes.

## Consistency and fallback rules

The summary marker count is an optimization hint, not final authority. The
items response determines the action after the request completes:

- If an eligible summary group returns exactly one valid item, open the modal.
- If it returns more than one item because data changed after the summary was
  loaded, fall back to the normal item list using that response.
- If it returns no usable item, show the existing item error state rather than
  opening an empty modal.
- If the modal integration is unavailable or rejects the item, fall back to the
  existing item list so the listing remains accessible.
- A newer marker selection cancels or supersedes the older request through the
  existing abort-controller and sequence guards. A stale response must never
  open a modal for a marker that is no longer selected.

## Maps state and modal history

- Opening the modal must not close or rebuild the Maps overlay.
- Closing the modal returns to the same Maps mode, filters, selected wards,
  center, zoom and base layer.
- The singleton path uses the same signal-modal history marker and back-button
  behavior as opening a listing from the current map item list.
- The selected marker may remain the logical selection, but the singleton path
  must not replace the directory with a redundant one-item list before or after
  the modal closes.

## Implementation boundaries

- Add a small predicate in `static/js/main/listing_map.js` for the exact rule:
  normalized `listing_count === 1` and precision is `exact` or `road`.
- Branch inside the existing group-selection request flow; reuse the current
  items endpoint, request cancellation, response guards and
  `openListingFromMap` adapter.
- Preserve the existing list rendering path as the fallback and as the default
  for every non-eligible marker.
- Update the Maps JavaScript asset version in `templates/index.html` so clients
  receive the behavior after deployment.
- No API, database, cache, registry, CSS, marker grouping or modal contract
  changes are required.
- Admin location-editing tools are unchanged. This feature only changes the
  default click outcome for eligible public marker groups.

## Verification

Add focused JavaScript contract tests covering:

- `exact` plus one listing opens the existing modal directly.
- `road` plus one listing opens the existing modal directly.
- `landmark` plus one listing still renders the item list.
- `ward` plus one listing still renders the item list.
- Any precision plus multiple listings still renders the item list.
- A stale singleton summary whose API response contains multiple items falls
  back to the list.
- Empty, failed and modal-unavailable cases remain recoverable through the
  existing error or list UI.
- A superseded response cannot open a stale listing modal.

Run `node --check` for the changed JavaScript, the focused Maps pytest suite and
`git diff --check`. Browser-test desktop and mobile Maps to confirm direct modal
opening, unchanged landmark/ward lists, and preservation of viewport and filter
state after closing the modal.

## Acceptance criteria

- Selecting a one-listing exact or road marker opens signal detail in one click
  or tap with no intermediate item list.
- Selecting a one-listing landmark or ward marker still opens its item list.
- All multi-listing markers retain their current list behavior.
- Closing the modal leaves the user on Maps with the previous viewport, filters
  and base layer intact.
- A stale count or failed modal integration never hides otherwise accessible
  listings.
