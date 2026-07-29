# Listing Map Official GIS Link Design

**Status:** Approved by the user on 2026-07-29
**Release mode:** `official_gis_link_only`

## Goal

Release the listing-map feature while planning raster overlays remain blocked by
source and reuse-right gates. The map workspace gives users a clear path to the
official Hồ Chí Minh City construction-planning GIS without copying, proxying,
or deep-linking undocumented planning data.

## Chosen UX

The full-screen listing-map header contains one compact planning callout:

- label: `Quy hoạch sử dụng đất & xây dựng`;
- action: `Mở GIS quy hoạch chính thức`;
- destination:
  `https://gisxaydung.tphcm.gov.vn/tracuuttqh`;
- supporting copy: the official portal opens in a new tab and the user should
  search by the listing address or road;
- disclaimer: the external planning information is for reference and does not
  replace parcel-level legal confirmation.

The anchor uses `target="_blank"` and `rel="noopener noreferrer"`. It stays in
the dialog focus order and is visible on desktop and mobile. No planning switch,
legend, local WebP, or public planning manifest is exposed.

## Data And Security

The destination is a compile-time constant in the server-rendered partial. The
browser does not accept a GIS URL from a query parameter, response payload,
`data-*` attribute, or listing field.

The external request receives no Radar BDS coordinates, filters, keywords,
listing IDs, location labels, contact data, or authentication state. Radar BDS
does not fetch or proxy the GIS page.

The click emits `listing_map_official_gis_opened` through the existing safe
tracking path. Its context contains only the current map mode (`signals|all`);
the outbound URL is not included.

## Failure And Accessibility

Because the destination is an external portal, Radar BDS cannot guarantee its
availability. The callout identifies it as an external tab and leaves the
listing map fully usable if the destination is unavailable.

The anchor has a visible focus state, an accessible label, and a text external
indicator rather than relying on an icon alone. Responsive CSS stacks the
callout copy and action without horizontal overflow.

## Testing And Release

DOM tests require the exact HTTPS official host, external-tab protections,
disclaimer, and the absence of planning-overlay hooks. JavaScript tests require
the safe event name and forbid location data in the tracking context. Browser
smoke covers both supported tabs and desktop/mobile layouts.

This user-approved link-only mode supersedes the four-artifact overlay gate for
this release only. The overlay audit remains `release_blocked`; adding hosted
planning layers later still requires all four official artifacts and reuse
rights.
