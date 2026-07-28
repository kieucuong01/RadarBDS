# Bản đồ Bình Dương Design Specification

**Date:** 2026-07-28  
**Status:** Approved for implementation  
**Route:** `/ban-do-binh-duong`

## Goal

Build a free, indexable Bình Dương administrative-map page that follows the useful information architecture of the reference page at `https://diaocthongthai.com/ban-do-binh-duong/`, while using original Radar BDS copy, styling, data, and conversion paths.

The page must help a visitor:

1. understand Bình Dương's former administrative structure;
2. switch to the 36 ward/commune structure effective in 2025;
3. inspect a named area on an interactive map;
4. continue to the most specific available Radar BDS signal filter.

## Scope

### Included

- A new public route at `/ban-do-binh-duong`.
- A server-rendered long-form SEO page.
- An interactive Leaflet map with two selectable data layers:
  - `legacy`: the 9 former district-level units of Bình Dương, selected by default;
  - `current`: the 36 wards/communes associated with the former Bình Dương area after the 2025 reorganization.
- A shareable fragment state:
  - `#layer-legacy`;
  - `#layer-current`;
  - `#layer-legacy/area-<slug>` or `#layer-current/area-<slug>` after selecting an area.
- A map-side information panel with an area name, type, short explanation, legacy/current context, and a filtered-dashboard CTA.
- Server-rendered area lists and summary content that remain useful if JavaScript or the map fails.
- SEO metadata, canonical, sitemap `lastmod`, `llms.txt`, internal links, JSON-LD, analytics hooks, and public-source attribution.
- Responsive behavior at 375, 768, 1024, and 1440 CSS pixels.

### Excluded

- Payments, PDF/SVG/KML sales, checkout, PayOS, and gated downloads.
- Separate SEO pages for each city, district, ward, or commune.
- Parcel boundaries, cadastral data, legal land records, or legal-planning certification.
- A database, CMS, or API for map content.
- Editing the existing five planning detail articles or their GeoJSON.
- Copying the reference site's images, advertising, downloadable products, article text, or source code.

## Information Architecture

The page follows the reference page's useful sequence but removes advertising and download-commerce blocks:

1. Shared SEO header and breadcrumbs.
2. Hero with the H1 “Bản đồ Bình Dương” and a short answer-first introduction.
3. A compact overview table for former province name, region, area, former district-level count, current ward/commune count, and administrative-change note.
4. Interactive map section with:
   - accessible two-button layer switch;
   - result/status text;
   - map canvas;
   - selected-area panel;
   - visible source and accuracy note.
5. Former Bình Dương area directory containing 9 compact cards.
6. Current 36 ward/commune directory grouped by familiar former areas.
7. A concise old-to-new interpretation section for property-search users.
8. Related planning maps and local Radar BDS pages.
9. FAQ, source list, methodology note, due-diligence disclaimer, and final dashboard CTA.
10. Shared SEO footer.

The page must not create links to future city/ward pages before those routes exist. Area cards may use in-page map-selection buttons and dashboard links.

## Data Architecture

### Registry

Create `config/binh_duong_map.py` as the single public-content registry. It will export:

- `BINH_DUONG_MAP_PAGE`: page metadata, overview rows, content sections, sources, FAQ, and related links;
- `BINH_DUONG_LEGACY_AREAS`: exactly 9 dictionaries;
- `BINH_DUONG_CURRENT_AREAS`: exactly 36 dictionaries;
- `BINH_DUONG_MAP_UPDATED_AT`: ISO date;
- `BINH_DUONG_MAP_UPDATED_LABEL`: Vietnamese display date.

Each area dictionary uses this stable shape:

```python
{
    "slug": "thu-dau-mot",
    "name": "Thủ Dầu Một",
    "unit_type": "Thành phố cũ",
    "group": "Thủ Dầu Một",
    "summary": "Trung tâm hành chính và thị trường lõi của Bình Dương cũ.",
    "dashboard_href": "/?tab=signals&city=Thủ%20Dầu%20Một",
    "dashboard_label": "Lọc tin Thủ Dầu Một",
    "osm_relation_id": 8448188,
}
```

The `legacy` slugs and the `current` slugs are unique within their own layer. Current units are grouped under familiar former-market areas so that property users can relate new names to existing search behavior.

### Geometry

Store generated static files under:

- `static/maps/binh-duong/legacy-districts.geojson`;
- `static/maps/binh-duong/current-36-wards.geojson`.

Both files are GeoJSON `FeatureCollection` documents. Every feature must include:

```json
{
  "slug": "thu-dau-mot",
  "name": "Thủ Dầu Một",
  "layer": "legacy",
  "unit_type": "Thành phố cũ",
  "group": "Thủ Dầu Một",
  "dashboard_href": "/?tab=signals&city=Thủ%20Dầu%20Một",
  "source": "geoBoundaries"
}
```

The old layer is derived from the geoBoundaries Viet Nam ADM2 simplified dataset and filtered to the 9 former Bình Dương district-level units. geoBoundaries attribution and represented year must remain visible.

The 2025 layer is built from 36 pinned OpenStreetMap administrative-relation IDs that were individually checked against the official name registry and former Bình Dương extent on 28/07/2026. The generation command uses Nominatim's lookup endpoint instead of repeating name searches, so duplicated names such as An Phú and Tân Hiệp cannot resolve to another part of Hồ Chí Minh City. OpenStreetMap attribution must remain visible. A feature is included only when it is:

- an administrative relation or polygon;
- uniquely matched to the expected name;
- geographically within the former Bình Dương extent;
- a polygon or multipolygon.

Generation must fail instead of silently emitting missing, duplicate, point-only, or out-of-bounds features. The page must call this layer “ranh tham khảo” and state that it does not replace official cadastral or legal documents.

### Progressive Enhancement

HTML contains all overview data, both area directories, sources, FAQ, and dashboard links before JavaScript runs.

JavaScript adds:

- Leaflet map rendering;
- layer switching;
- polygon selection;
- area-button synchronization;
- fragment navigation;
- selected-area panel updates;
- analytics events.

If the GeoJSON request fails, the map section shows a readable error state and recovery button while the directories remain usable.

## Interaction Model

### Layer Switch

- Two normal `<button>` elements use `aria-pressed`.
- Default state is `legacy`.
- Selecting a layer updates the URL fragment without a page reload.
- `hashchange`, Back, and Forward restore the layer and selected area.
- Unknown or malformed fragments fall back to `legacy` with no selected area.

### Area Selection

An area can be selected by:

- clicking its polygon;
- clicking its server-rendered directory button;
- opening a valid area fragment.

Selection:

- visually emphasizes the polygon;
- fits the map to that polygon;
- updates the information panel and `aria-live` status;
- scrolls the map into view only when the user explicitly activates a directory button;
- exposes the most specific existing dashboard filter.

Area selection does not navigate to a future SEO route.

### Dashboard CTA Rules

- Thủ Dầu Một uses `/?tab=signals&city=Thủ%20Dầu%20Một`.
- Bến Cát and Mỹ Phước-related groups use `/?tab=signals&city=Bến%20Cát` where supported.
- Areas without a stable dashboard city mapping use `/?tab=signals`.
- CTA language uses “Lọc tin…” or “Xem tin đang bán…”, not “Signal khu này”.

## Visual Design

Use the existing Radar BDS public-page design tokens, typography, header, footer, teal primary, and blue CTA. Do not load a new font.

### Desktop

- Maximum content width follows the existing SEO shell.
- Hero uses a two-column layout: copy/CTA and a compact fact panel.
- Map section uses a 2:1 layout: map canvas and selected-area panel.
- Map height is approximately 620 px at 1180 px and above.
- Long-form sections use a readable 65–75 character measure.

### Tablet

- Map remains above the selected-area panel.
- The former-area directory uses two columns.
- The current-area directory uses two or three columns depending on available width.

### Mobile

- Hero becomes one column.
- The layer switch becomes a two-column full-width control.
- Map height is approximately 430 px at 375 px.
- The selected-area panel follows the map.
- Directories use compact horizontal rows rather than tall cards.
- A bottom sticky dashboard CTA may appear only after the main hero and must not cover page content.

### Accessibility

- All interactive targets are at least 44 × 44 CSS pixels.
- Keyboard focus is visible.
- Polygon behavior has an equivalent directory-button path.
- The map canvas has an accessible label and adjacent text alternative.
- Dynamic status uses `aria-live="polite"`.
- Color is not the only selected-state indicator.
- Motion is limited to short opacity/transform transitions and respects `prefers-reduced-motion`.
- Heading order is sequential with one H1.

## Public Copy Rules

- Use direct Vietnamese aimed at property buyers and investors.
- Explain “Bình Dương cũ” on first use.
- Do not present a boundary as cadastral or legally determinative.
- Avoid internal terms such as “card”, “CTA”, “map-first”, “SEO/AIO”, or “view-model” in visible copy.
- Do not reuse the reference page's paragraphs or claims.
- Do not publish volatile officeholder names.
- Use `DD/MM/YYYY` for visible dates and ISO 8601 in machine-readable fields.

## SEO and Structured Data

### Metadata

- Canonical: `https://radarbds.vn/ban-do-binh-duong`.
- Title starts with “Bản đồ Bình Dương”.
- Description targets administrative-map and old/new-name comparison intent.
- Open Graph uses `/static/images/seo/radarbds-og.png`.
- Page is indexable and self-canonical.

### Schema

Render one JSON-LD `@graph` containing:

- `WebPage` with `mainEntity`;
- `Dataset` for the two visible administrative-map datasets;
- `ItemList` containing exactly 9 unique former-area items;
- `BreadcrumbList`;
- `FAQPage` matching visible FAQ content.

Schema must not claim official legal authority. `Dataset.isBasedOn` points to the visible geoBoundaries, OpenStreetMap, and official administrative-resolution sources.

### Discovery

- Add the route to `sitemap.xml` with `lastmod` from the registry.
- Add the route to `/llms.txt`.
- Add internal links from:
  - the planning hub;
  - shared SEO footer;
  - relevant map/detail related links where a natural slot exists.
- Do not add nonexistent future city/ward URLs.

## Analytics

Use the existing public tracking partial and allowlist. Add:

- `binh_duong_map_layer_selected`;
- `binh_duong_map_area_selected`.

Existing generic CTA tracking records hero, area-panel, related-link, and bottom dashboard CTA clicks.

Allowed event context:

```json
{
  "layer": "legacy",
  "area_slug": "thu-dau-mot",
  "target": "/?tab=signals&city=Th%E1%BB%A7%20D%E1%BA%A7u%20M%E1%BB%99t"
}
```

Do not send raw search text, coordinates, email, phone, IP, or other PII.

## Error Handling

- Invalid fragment: restore legacy overview.
- Missing selected slug for a valid layer: show the layer with no selection.
- GeoJSON fetch failure: show error text, keep the retry button and all server-rendered links.
- Partial or invalid geometry during generation: fail the build command with a non-zero exit.
- Leaflet unavailable: show the fallback message and keep directories accessible.
- Analytics unavailable: interactions continue without errors.

## Testing

### Python/template

- Route returns 200 with one H1 and self-canonical.
- Registry contains exactly 9 legacy and 36 current unique units.
- All area dashboard URLs are local and valid.
- Both GeoJSON files parse and match registry names/slugs exactly.
- Page includes both layer controls, progressive fallback, sources, disclaimer, and dashboard CTAs.
- Schema graph has unique 9-item `ItemList` and two datasets.
- Sitemap and `llms.txt` contain the route and correct `lastmod`.
- Planning hub and footer link to the new route.
- Tracking actions are allowlisted.

### JavaScript

- Fragment parser accepts both layers and area slugs.
- Invalid fragments fall back to legacy.
- Layer switching updates `aria-pressed`, visible state, and fragment.
- Area selection updates panel data and tracking context.
- Hash changes restore state.
- Fetch/Leaflet failure activates the fallback without hiding HTML directories.

### Browser

At 375, 768, 1024, and 1440 px:

- no horizontal overflow;
- all map/directory controls remain usable;
- touch targets are at least 44 px;
- default layer is the former Bình Dương map;
- switching to the 36-unit layer works;
- selecting a polygon and a directory item produces the same result;
- Back/Forward restore state;
- sticky header does not obscure the map anchor;
- no console errors;
- JSON-LD is present in the rendered DOM.

## Future Extension

The registry's `slug`, `group`, and dashboard mapping become inputs for later city/ward SEO pages. Future routes can be added without changing the map state contract. Until a route is created and tested, this page must keep area names as buttons or dashboard links rather than speculative internal links.
