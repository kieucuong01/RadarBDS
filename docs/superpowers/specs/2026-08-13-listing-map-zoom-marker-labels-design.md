# Listing Maps closer zoom and compact marker labels

Date: 2026-08-13
Status: approved design

## Goal

Make the listing Maps workspace open one zoom level closer on desktop and
mobile, and expose useful compact information above every mapped group without
turning the map into a wall of overlapping text.

## Scope

This change affects the shared Maps workspace used by both Săn Deal and Tin
rao. It changes only client-side map framing and marker labels. It does not
change map-location resolution, grouping, listing filters, API contracts, or
the item modal.

## Initial map framing

After Leaflet fits the returned marker bounds, Maps increases the resulting
zoom by one level on both desktop and mobile. The result remains capped at zoom
16. Empty map results retain the current Bình Dương fallback view.

The closer view intentionally may place the most peripheral markers just
outside the initial viewport. Panning and zooming remain available.

## Marker label rules

The label model is selected from `precision` and `listing_count`:

| Precision | Count | Label |
|---|---:|---|
| `exact` | any | Compact price, area, and price per m² when the data is valid |
| `road` | 1 | Same compact price label as an exact marker |
| `road` | 2+ | Compact count badge such as `3 tin` |
| `landmark` | any | Compact count badge |
| `ward` | any | Compact count badge |

Price labels become eligible at zoom 13. They use two rows:

1. `<price> tỷ · <area>m²`
2. `<price-per-m²>tr/m²`

If price, area, or price per m² cannot be derived safely, an exact marker or
single-listing road marker has no price label. It does not fall back to a count
badge because the count is already implied to be one.

Count badges remain visible at all supported zoom levels. They show only the
number of listings and the word `tin`; names remain available through the
existing tooltip and directory.

## Density and collision handling

Price labels reuse the existing collision suppression so overlapping labels
are omitted deterministically. Count badges are materially smaller than price
labels and use their own compact rectangle. All visible label rectangles share
one collision set, preventing price labels and count badges from covering each
other.

Priority order is:

1. exact price labels;
2. single-listing road price labels;
3. road count badges;
4. landmark count badges;
5. ward count badges.

This preserves the most precise and decision-useful information when space is
limited.

## Styling

Price labels retain two rows but use a narrower box, smaller font, reduced
padding, and tighter line height. Count badges use a pill-shaped white surface
with the marker precision color, small text, and no secondary row.

The labels are non-interactive and do not replace the underlying accessible
circle marker or its keyboard behavior.

## Testing

JavaScript unit tests cover:

- exact price labels at zoom 13;
- single-listing road price labels at zoom 13;
- multi-listing road count badges;
- landmark and ward count badges;
- invalid single-listing price data;
- label priority and collision rectangles;
- one-level closer initial zoom with the zoom-16 cap.

Existing Maps workspace tests, syntax checks, and browser verification cover
both desktop and mobile layouts and both Săn Deal and Tin rao modes.
