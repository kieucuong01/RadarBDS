# Valuation Comparable Signal Cards

## Goal

Replace the compact rows under “Mẫu so sánh cùng phân khúc” on
`/dinh-gia-bds` with cards that use the same visual language and information
hierarchy as the Săn Deal signal cards. A user can open any card directly at
`/listing/{id}`.

## Access and Safety

- Guest, Free, and VIP all receive and see up to six comparable cards.
- The unlock gate is removed. `comparables_locked` remains `false` for API
  compatibility during this release.
- Non-admin responses never contain contact phone numbers, seller details, or
  original source URLs, including values embedded in title or description.
- The only navigation URL exposed to non-admin users is the internal
  `detail_href` in the form `/listing/{id}`.
- Admin keeps the existing data boundary, although the comparable-card UI does
  not display source contact fields.

## Comparable Card Content

Each comparable card contains all applicable information used by the Săn Deal
card:

- primary image or the standard no-image placeholder;
- new-listing, MOS, price-drop, and quality-warning badges;
- listing title;
- actual asking price and actual price per square metre;
- model fair price and fair price per square metre;
- ward, area and dimensions, road tier/name, property type, and residential
  land information;
- relative listing age.

Fields that are missing are omitted or shown using the existing Săn Deal
fallback. The valuation page does not add Save or Ráp mối actions.

## Interaction and Layout

- The entire card is a semantic anchor pointing to `/listing/{id}` and opens in
  the same tab.
- The card has a visible keyboard focus state and a minimum 44px effective
  target.
- The comparable section spans the full tool workspace below the form/result
  row, so signal cards retain their normal readable width.
- Comparable cards use a three-column grid on desktop, two columns on tablet,
  and one column on mobile. Six cards form two complete desktop rows. There is
  no horizontal carousel or horizontal scrolling.
- Clicking a card records `valuation_comparable_click` with only the card
  position, property type, and page context. Listing text, price, phone, and
  source URL are not sent in analytics.

## Implementation Boundary

- Reuse the Săn Deal card class names and shared card stylesheet.
- Add a valuation-specific renderer adapter so the dashboard renderer and its
  modal/action dependencies are not refactored in this release.
- Expand the comparable query/serializer with the existing market-data
  formatting helpers where practical. Comparable selection remains canonical,
  quality-filtered, same-ward/type prioritized, and limited to six.
- Do not change the shared valuation formula, database schema, dashboard signal
  card behavior, favorites, or contact workflow.

## Error and Empty States

- If no eligible comparable remains, show the existing explanatory empty copy.
- A broken or missing image falls back to the standard card placeholder without
  preventing navigation.
- A malformed/missing listing ID is not rendered as a clickable card.

## Verification

- API tests prove guest, Free, and VIP receive the same unlocked comparable
  shape and no non-admin response leaks a phone or source URL.
- Logic tests prove canonical/quality filtering and the six-card limit remain
  intact.
- UI contract tests prove the signal-card classes, detail links, full card
  fields, absence of Save/Ráp mối actions, and analytics event.
- Browser smoke covers guest desktop plus 375px and 390px mobile layouts,
  verifies no horizontal overflow, and follows a card to `/listing/{id}`.
- Existing valuation, market-data trust, Python syntax, and JavaScript syntax
  checks remain green before release.
