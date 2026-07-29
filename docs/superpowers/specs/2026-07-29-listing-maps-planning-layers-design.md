# Listing Maps And Planning Layers Design Specification

**Date:** 2026-07-29

**Status:** Design approved in conversation; written spec review pending
**Surface:** Main dashboard tabs `Săn Deal` and `Tin rao`

## Goal

Add a full-screen Leaflet map workspace to the main Radar BDS dashboard. A
fixed, bottom-center `Xem trên Maps` button on the active `Săn Deal` or
`Tin rao` tab opens every listing that matches the current tab filters,
including results beyond the currently loaded page.

The map must:

1. represent every matching listing;
2. label whether a point is exact, road-level, or ward-level;
3. preserve the existing filters, tier rules, and redaction boundaries;
4. provide verified land-use-planning and construction-planning overlays for
   Thủ Dầu Một and Bến Cát;
5. return the user to the unchanged dashboard state when closed.

## Approved Product Decisions

- Use Leaflet with the existing OpenStreetMap street base and existing Esri
  imagery option. Do not add Google Maps Platform, an API key, or Google
  billing.
- The map represents all records matching the current filters, not only rows
  or cards already rendered in the browser.
- Include every property type allowed by the current filters. Do not force a
  land-only filter.
- The workspace opens full-screen inside the dashboard rather than navigating
  to a separate route.
- Listings without exact coordinates resolve to a road-level point; listings
  without a usable road resolve to a canonical ward center.
- A listing without a usable city/ward is counted as unmapped and is not placed
  at an invented location.
- Planning overlays cover Thủ Dầu Một and Bến Cát only in the first release.
- Official/public planning sources are researched and curated by the project.
- The floating map button is fixed at the bottom center of the viewport.

## Scope

### Included

- One fixed `Xem trên Maps` button shared by the two supported tabs.
- A full-screen in-dashboard map workspace with desktop side panel and mobile
  bottom sheet.
- A dedicated compact map API for `signals` and `all` modes.
- A separate derived listing-location table and deterministic backfill.
- Offline OpenStreetMap road-center resolution for current listings.
- Canonical ward-center fallback.
- Server-side location grouping and lazy item pagination.
- Exact/road/ward/unmapped coverage counts.
- Two independently toggleable planning overlay categories:
  - land-use planning;
  - construction planning.
- Four verified planning artifacts:
  - land-use planning for Thủ Dầu Một;
  - land-use planning for Bến Cát;
  - construction planning for Thủ Dầu Một;
  - construction planning for Bến Cát.
- Planning source manifest, attribution, legend, effective-period display, and
  document hashes.
- Existing tier/source enforcement, contact redaction, analytics allowlisting,
  automated tests, browser verification, and production release verification.

### Excluded

- Google Maps, Google Geocoding, or unofficial Google tile URLs.
- Parcel boundaries, cadastral matching, parcel-number lookup, or legal
  certification.
- Automatic claims that a listing is residential land, affected by planning,
  or legally buildable.
- Planning overlays outside Thủ Dầu Một and Bến Cát.
- Runtime geocoding against Nominatim or another public geocoder.
- Protected GIS token reuse, anonymous-token scraping, or proxying a
  government portal's authenticated ArcGIS services.
- External LLM calls in crawl, reprocess, location resolution, or map APIs.
- A separate SEO map page or changes to `/ban-do-binh-duong`.
- Unrelated crawler, valuation, deduplication, or planning-page refactors.

## System Architecture

The feature is isolated into four units:

1. **Location resolution**
   deterministically derives map points without changing canonical listing
   fields.
2. **Map read model**
   applies existing filters and trust rules, joins derived locations, groups
   colocated approximate listings, and returns compact map payloads.
3. **Dashboard map workspace**
   owns the fixed launcher, Leaflet lifecycle, clusters, panels, accessibility,
   and dashboard-state preservation.
4. **Planning artifact pipeline**
   verifies official documents, georeferences approved map sheets offline, and
   publishes versioned static overlays with a machine-readable manifest.

The feature must not add map data to `/api/dashboard`, `/api/signals`, or
`/api/listings`.

## Location Data Model

Create a PostgreSQL table through `db/schema.py` and the normal migration
registry:

```sql
CREATE TABLE listing_map_locations (
    listing_id BIGINT PRIMARY KEY REFERENCES listings(id) ON DELETE CASCADE,
    lat DOUBLE PRECISION NOT NULL CHECK (lat BETWEEN -90 AND 90),
    lng DOUBLE PRECISION NOT NULL CHECK (lng BETWEEN -180 AND 180),
    location_precision TEXT NOT NULL
        CHECK (location_precision IN ('exact', 'road', 'ward')),
    location_key TEXT NOT NULL,
    location_label TEXT NOT NULL,
    source TEXT NOT NULL,
    resolver_version TEXT NOT NULL,
    listing_location_signature TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_listing_map_locations_precision
    ON listing_map_locations(location_precision);

CREATE INDEX idx_listing_map_locations_point
    ON listing_map_locations(lat, lng);

CREATE INDEX idx_listing_map_locations_key
    ON listing_map_locations(location_key);
```

`listing_location_signature` is a stable hash of the normalized location inputs
used for that row: source-provided coordinates when present, otherwise
`area + ward + road_name`. The backfill skips a row only when both the
signature and `resolver_version` are unchanged.

Derived coordinates must never be written to `listings`, because a road center
or ward center is not the parcel's actual position.

The API exposes `location_precision` as the shorter `precision` field; the
database name stays explicit and avoids overloading the SQL type modifier.

## Deterministic Location Resolution

Resolution order is fixed:

1. A source-provided, validated coordinate becomes `precision=exact`.
2. A match on normalized `area + ward + road_name` becomes `precision=road`.
3. A match on the canonical old ward becomes `precision=ward`.
4. Otherwise the listing is unmapped.

Current listings have no coordinate columns, so the initial backfill uses
steps 2–4. The data model supports exact points later without weakening the
current accuracy labels.

### Road registry

Build a versioned road-location registry from an offline OpenStreetMap extract
for the Thủ Dầu Một and Bến Cát coverage boundaries. Runtime requests do not
call Overpass, Nominatim, or any third-party geocoder.

For each named road:

- normalize Vietnamese accents, road-code punctuation, abbreviations, and
  whitespace using one shared resolver;
- intersect the road geometry with the canonical ward boundary where
  possible;
- store a representative point on the clipped line, not an arbitrary polygon
  centroid;
- preserve the OSM object identifiers, extract date, attribution, and
  resolver version;
- keep separate keys for same-named roads in different wards or cities.

Multiple listings resolved to one road share one honest road point. The UI uses
grouping and spidering/list pagination instead of introducing fake coordinate
offsets.

### Ward registry

Use the existing canonical old-ward interpretation used by valuation and
listing filters. Post-merger names do not silently replace the canonical ward
when location evidence is ambiguous.

Ward fallback points come from verified ward geometry and are visibly labeled
`Tâm phường`.

### Backfill lifecycle

Add a deterministic CLI command that:

- accepts an optional listing-id scope;
- processes only rows whose signature/version changed unless `--force` is
  supplied;
- reports exact, road, ward, unmapped, inserted, updated, and unchanged counts;
- commits in bounded batches;
- invalidates map caches after a successful commit.

Crawl/reprocess may call the scoped resolver after canonical listing writes.
It must not make remote requests and must not add external LLM verification.

## Map API

### Summary endpoint

Add:

```text
GET /api/map-listings
```

Accepted mode:

- `mode=signals`
- `mode=all`

The endpoint consumes the same active filter contract as the corresponding
dashboard tab, including city, ward, source, property type, price, area, date,
keyword, completeness, MOS, and price-drop controls where applicable.
Unknown parameters are ignored or rejected consistently with the existing
market APIs.

Server rules take priority over client input:

- guest source policy remains enforced;
- `signals` uses latest valuation plus the existing actionable-signal and
  display-MOS rules;
- `all` uses the Tin rao visibility and date-range rules;
- non-admin users remain redacted.

Example response shape:

```json
{
  "mode": "signals",
  "summary": {
    "total": 428,
    "mapped": 421,
    "exact_count": 0,
    "road_count": 356,
    "ward_count": 65,
    "unmapped_count": 7,
    "location_groups": 118
  },
  "locations": [
    {
      "location_key": "road:thu-dau-mot:phu-loi:dx-43",
      "lat": 10.992,
      "lng": 106.676,
      "precision": "road",
      "location_label": "Theo tên đường ĐX 43, Phú Lợi",
      "listing_count": 8,
      "signal_count": 8,
      "property_counts": {
        "dat_vuon": 6,
        "nha_dat": 2
      },
      "best_mos_pct": 28.4
    }
  ],
  "location_version": "osm-2026-07-29-v1"
}
```

The numeric example illustrates the contract only; tests use isolated fixture
rows and production values come from PostgreSQL.

An exact point uses a per-listing location key. Road and ward points group all
matching listings at that honest approximate location.

The invariant is:

```text
mapped + unmapped_count = total
exact_count + road_count + ward_count = mapped
```

### Group-items endpoint

Add:

```text
GET /api/map-listing-items
```

Required inputs:

- the same `mode` and filter snapshot;
- `location_key`;
- `page`;
- bounded `limit`.

The server re-applies all filters and tier rules. It does not trust the
location key as authorization. The response uses the compact card fields
needed by the side panel and does not include source URL, phone, a long
description, or full image arrays.

### Payload and cache boundaries

- The summary endpoint returns no full descriptions or image arrays.
- Map payloads are cached for a short TTL by tier, mode, normalized filter
  tuple, and resolver version.
- Crawl, reprocess, listing-location backfill, and dependent QC changes
  invalidate the affected keys.
- Stale client requests are abortable and cannot overwrite a newer map state.

## Dashboard Launcher

Add one shared fixed launcher outside the tab content:

```text
[map-pin icon] Xem trên Maps
```

Visibility rules:

- visible only when the active tab is `signals` or `all`;
- `signals` opens `mode=signals`;
- `all` opens `mode=all`;
- hidden on market, insights, tools, and other tabs;
- hidden while the map workspace, sidebar, tools sheet, chat, or a blocking
  modal is open.

Position rules:

- fixed to the viewport's horizontal center;
- desktop bottom offset: 28 CSS pixels;
- mobile/tablet bottom offset: mobile bottom-navigation height plus 12 CSS
  pixels plus `env(safe-area-inset-bottom)`;
- minimum target height: 48 CSS pixels;
- tab content receives enough bottom padding that the launcher cannot cover
  the last card or table row.

The launcher sits above page content but below sheets/modals. It is removed
from pointer and focus order when hidden.

## Full-Screen Map Workspace

Opening the launcher:

- snapshots the active tab, normalized filters, loaded-list state, scroll
  position, and launcher focus;
- pushes a same-URL history state so Android/iOS browser Back can close the
  map without navigating away;
- locks dashboard body scrolling;
- lazy-loads map-only dependencies and the map payload.

Closing by the close button, `Escape`, or Back:

- aborts pending requests;
- removes map-only listeners;
- unlocks scrolling;
- returns to the same tab, filters, loaded cards/rows, and scroll position;
- restores focus to the launcher.

### Layout

Desktop:

- full viewport overlay;
- header with mode title, total count, filter chips, accuracy summary, and
  close button;
- map occupies the primary area;
- a right-side panel displays a selected location group and paginated items.

Mobile/tablet:

- full viewport map;
- compact top bar;
- a selected marker opens an accessible bottom sheet;
- the sheet can be closed without closing the map;
- safe-area insets are respected.

### Marker behavior

- Cluster click zooms toward its members.
- At maximum useful zoom, colocated markers use the cluster/list panel rather
  than fake offsets.
- A road or ward group opens a paginated list of all matching items.
- A compact item shows price, area, property type, canonical ward, relative
  age, MOS for signal mode, and location precision.
- `Xem chi tiết` reuses the existing listing-detail modal above the map.
- Closing listing detail returns focus and state to the selected map item.

Marker and legend styling distinguishes:

- signal versus ordinary listing context;
- property type;
- exact, road, and ward precision.

Color is not the only distinction; icons, shapes, text labels, and accessible
names carry the same meaning.

## Base Map

Reuse the proven base-layer contract from the existing Bình Dương map:

- OpenStreetMap street layer;
- Esri World Imagery satellite layer.

Do not introduce unofficial Google tile endpoints. Preserve required
OpenStreetMap and Esri attribution. A base-layer failure must not remove the
listing group list.

## Planning Overlays

### Required layer set

The release requires four verified artifacts:

| Category | Area | Required state |
|---|---|---|
| Land-use planning | Thủ Dầu Một | Published, georeferenced, manifested |
| Land-use planning | Bến Cát | Published, georeferenced, manifested |
| Construction planning | Thủ Dầu Một | Published, georeferenced, manifested |
| Construction planning | Bến Cát | Published, georeferenced, manifested |

`Construction planning` means the latest in-force general or zoning plan that
has been formally approved for the represented area. A draft task, proposal,
or consultation map must not be labeled as approved planning.

### Source policy

- Prefer the publishing municipality, former Bình Dương provincial portal,
  or the responsible Hồ Chí Minh City planning authority.
- Record the approval decision and effective period from the source document.
- Do not use commercial planning sites as geometry sources.
- Do not proxy protected ArcGIS tokens or depend on an undocumented anonymous
  session token.
- If the official publication terms do not permit hosting a derived raster,
  obtain permission before release. A source link alone does not authorize
  republishing.
- If an in-force official map cannot be verified or georeferenced within the
  stated tolerance, that artifact fails the release gate; it is not replaced
  with an invented layer.

### Manifest

Each planning artifact records the following required fields. The build rejects
a manifest with a missing field, an unparseable date or URL, an invalid hash, or
bounds outside the supported service area.

| Field | Required value |
|---|---|
| `id` | Stable unique slug for category and administrative area |
| `category` | `land_use` or `construction` |
| `area` | Canonical supported-area name |
| `display_title` | Title shown in the layer control |
| `approval_decision` | Exact decision number and issuing authority |
| `approval_date` | ISO 8601 calendar date copied from the decision |
| `effective_period` | Exact effective period stated by the source |
| `map_scale` | Positive integer denominator from the published map |
| `source_url` | Public official document or map URL |
| `source_downloaded_at` | ISO 8601 calendar date |
| `source_sha256` | SHA-256 of the downloaded original |
| `artifact_path` | Versioned same-origin raster path |
| `artifact_sha256` | SHA-256 of the published raster |
| `bounds` | WGS84 south-west and north-east coordinate pairs |
| `control_point_count` | Integer of at least six |
| `rms_error_m` | Measured non-negative RMSE in metres |
| `attribution` | Publishing authority, document title, and decision number |
| `legend_path` | Versioned same-origin legend image path |

The production manifest carries only exact values obtained during source
curation. Draft values cannot satisfy the release gate.

### Georeferencing

- Use at least six well-distributed control points visible in the approved map
  and a trusted geographic reference.
- Warp to a north-up WGS84 raster with transparent nodata.
- The maximum permitted RMSE is:

```text
max(10 metres, map-scale denominator / 1000 metres)
```

Examples:

- 1:25,000 map: maximum 25 metres;
- 1:10,000 map: maximum 10 metres.

- Record control points, command/tool version, source hash, output hash, bounds,
  and measured RMSE.
- Fail generation when the source hash, approval metadata, bounds, alpha
  channel, dimensions, or RMSE contract fails.

### Map controls

Both overlays are off by default:

- checkbox: `Quy hoạch sử dụng đất`;
- checkbox: `Quy hoạch xây dựng`;
- shared or per-layer opacity control;
- layer turned on most recently is rendered above the other.

The visible legend includes:

- exact plan name and level;
- represented period;
- approval decision/date;
- publishing authority;
- accuracy disclaimer;
- `Mở nguồn chính thức`.

Outside Thủ Dầu Một and Bến Cát, show:

```text
Chưa có lớp quy hoạch đã kiểm chứng cho khu vực này.
```

The UI must not infer parcel land-use status from a road/ward-level listing
marker. Planning overlays are for visual comparison and due-diligence
navigation only.

## Error Handling

### Location and API errors

- A listing missing canonical city/ward is unmapped.
- Missing location rows remain visible in the summary count.
- A map-summary failure shows a retry action without altering the dashboard.
- A group-items failure preserves the selected group and offers a focused
  retry.
- Closing the map cancels pending requests.
- A response for an older filter snapshot is discarded.

### Map dependency and base-layer errors

- Leaflet unavailable: show an accessible error with retry and keep the close
  action usable.
- Marker-cluster dependency unavailable: fall back to grouped point markers
  and the list panel.
- One base layer unavailable: allow switching to the other.
- Both base layers unavailable: retain the group list and show map-canvas
  recovery guidance.

### Planning errors

- One failed planning artifact does not disable listing markers or the other
  planning artifact.
- A failed layer shows its own error and retry state.
- A manifest/hash mismatch blocks the invalid layer instead of displaying it.
- Source metadata and disclaimers remain available when the overlay image
  itself fails.

## Security And Privacy

- All map APIs use the existing session and tier system.
- Guest/Free/VIP responses must not contain original URL, source URL, contact
  phone, or unredacted contact text.
- Source policy is server-enforced.
- `signals` mode cannot bypass actionable-signal filtering.
- Validate and allowlist mode, sort, pagination, location key, and filter
  values.
- Never accept a tile URL, planning artifact URL, filesystem path, SQL
  fragment, or source domain from the client.
- Planning source domains are allowlisted in the build pipeline.
- Browser-visible exact coordinates are returned only when the listing source
  legitimately provided them and the row passed normal visibility rules.
- No coordinates, raw keyword, phone, email, IP, or contact text are sent to
  analytics.

## Performance Budgets

Measure the current filtered-tab and API timings before implementation.

Budgets for the default production filter:

- warm `/api/map-listings` p95: at most 1.0 second;
- cold `/api/map-listings`: at most 2.5 seconds;
- compressed summary payload: at most 750 KB;
- map-only JavaScript/CSS must not load before launcher activation;
- one summary request per open/filter snapshot;
- group items load only after group selection;
- no full description or full image array in map responses.

If the full dataset exceeds the initial payload budget, retain complete
representation by server grouping; do not silently cap or drop matching
listings.

Indexes and SQL must be measured against the actual PostgreSQL query plan
before introducing wider schema or cache changes.

## Accessibility

- Launcher target is at least 48 CSS pixels high.
- Launcher and workspace have visible keyboard focus.
- Workspace uses dialog semantics and an accessible name.
- Focus is trapped while the workspace is open.
- `Escape` closes listing detail first, then the map workspace.
- Dynamic count/error text uses polite live regions.
- Side panel and mobile bottom sheet are keyboard reachable.
- Marker interactions have an equivalent grouped-list path.
- Precision is communicated in text, not only marker color.
- Reduced-motion preference disables nonessential map-panel transitions.
- All fixed controls respect mobile safe areas.

## Analytics

Allowlist:

- `listing_map_opened`;
- `listing_map_closed`;
- `listing_map_location_opened`;
- `listing_map_layer_toggled`;
- `listing_map_retry`.

Permitted context:

- `mode`;
- planning layer id;
- location precision;
- mapped/unmapped counts;
- coarse UI surface such as `desktop_panel` or `mobile_sheet`.

Do not send coordinates, raw filters, keyword text, listing title, phone,
email, URL, or other personally identifying data.

## Testing

### Location resolver

- exact coordinates take precedence over road and ward;
- road takes precedence over ward;
- same-named roads do not cross city/ward keys;
- Vietnamese road-code punctuation normalizes consistently;
- unknown road falls back to the canonical ward;
- unknown ward becomes unmapped;
- unchanged signature/version skips writes;
- changed location inputs update the derived row;
- no deterministic or random coordinate jitter is added.

### API

- `signals` matches the existing actionable signal set for identical filters;
- `all` matches the Tin rao set for identical filters;
- source/tier enforcement remains server-side;
- non-admin map payloads contain no URL or phone;
- every supported filter has parity tests;
- summary invariants hold;
- all matching rows are represented in location counts or unmapped count;
- group pagination re-applies all filters and visibility rules;
- invalid mode, location key, and pagination are rejected;
- cache invalidation follows crawl, reprocess, and location backfill.

### Planning artifacts

- exactly four required artifact ids exist;
- official-source domains pass the allowlist;
- approval metadata and effective periods are nonempty;
- source and artifact hashes match;
- bounds intersect the intended area and not an unrelated province;
- at least six control points are recorded;
- RMSE meets the scale-derived threshold;
- raster/legend files exist, decode, and preserve transparency;
- drafts cannot be marked approved.

### Frontend contracts

- launcher is visible only on `signals` and `all`;
- launcher mode follows the active tab;
- launcher is fixed bottom-center;
- mobile offset clears the existing bottom navigation;
- blocking overlays hide the launcher;
- open/close preserves tab, filter, scroll, loaded-list state, and focus;
- old requests cannot overwrite new state;
- cluster/group/item flows work;
- planning toggles and opacity state work independently;
- partial base/planning failures preserve remaining functionality.

### Browser verification

At 375, 768, 1024, and 1440 CSS pixels:

- no horizontal overflow;
- launcher stays bottom-center and does not cover the last result;
- launcher clears the mobile bottom navigation and safe area;
- map opens from both tabs with matching totals;
- current filters remain unchanged;
- cluster, grouped list, pagination, and detail modal work;
- mobile bottom sheet and desktop side panel work;
- both planning layers align with recognizable roads/boundaries within the
  documented tolerance;
- closing returns to the exact prior dashboard state;
- keyboard and touch flows work;
- no console errors or duplicate requests occur.

## Release And Production Proof

Implementation is not complete after a local build or an HTTP 200.

Required release chain:

1. capture pre-change API/filter timings;
2. use test-first red/green cycles for each behavior;
3. run focused resolver, API, template, JavaScript, and planning-artifact tests;
4. run Python compilation and JavaScript syntax checks for touched files;
5. run relevant existing market/filter/RBAC regression suites;
6. run responsive local browser verification;
7. run `git diff --check` and review the exact staged paths;
8. commit only the feature paths;
9. push `main`;
10. deploy with the documented Radar BDS production wrapper;
11. verify the deployed commit and service health;
12. measure production map API timings;
13. run production browser flows on both supported tabs;
14. verify filter totals, marker coverage, four real planning artifacts,
    attribution, and non-admin redaction.

The production closeout must separate:

- local automated verification;
- PostgreSQL/backfill evidence;
- deployed service/commit evidence;
- public browser behavior;
- planning source/artifact evidence.

## Completion Criteria

The feature is complete only when:

- the fixed launcher is bottom-center and behaves correctly on both supported
  tabs;
- the map represents every matching result through exact points, honest
  approximate groups, or the visible unmapped count;
- road/ward precision is never presented as an exact parcel location;
- all four planning artifacts pass source, hash, georeference, and display
  gates;
- existing tier/source/redaction rules remain intact;
- required local and production verification passes;
- commit, push, deploy, and public-production proof are recorded.
