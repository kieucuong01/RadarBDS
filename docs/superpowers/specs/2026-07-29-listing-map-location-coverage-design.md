# Listing Map Location Coverage Pipeline

**Date:** 2026-07-29

**Status:** Written for user review

**Scope:** All current and future listings shown in the Săn Deal and Tin Rao map

## Problem

The first listing-map release uses a deterministic, versioned registry with 110
curated roads. The fallback is honest, but road coverage is too low:

- production currently has 2,870 road-level derived locations;
- 15,889 listings fall back to a ward center;
- the active public Tin Rao map has 2,276 listings, of which 1,928 are
  ward-level;
- the active public Săn Deal map has 294 listings, of which 239 are ward-level;
- current listings contain no source coordinates, so there are no exact points.

Listings such as DX092, DX096, DX120, Đường số 35/37 at TĐC Phú Chánh B,
Đường 88 at TĐC Phú Chánh D, and Đường 11B at TĐC Định Hòa demonstrate the
problem, but the solution must cover the complete dataset rather than a fixed
example list.

Two separate gaps cause the low coverage:

1. the road registry is a hand-selected subset instead of a generated
   gazetteer of all available roads;
2. the resolver reads only canonical `ward` and stored `road_name`, while useful
   map context also appears in the description as nearby roads, TĐC/KDC names,
   project names, and distance phrases.

The existing canonical extraction rules deliberately ignore road names in
phrases such as “cách đường”, “gần đường”, and “sát đường” because those roads
must not be treated as the listing's frontage road for valuation or dedup.
Maps needs a separate derived interpretation instead of weakening that rule.

## Goals

1. Remove the 110-road manual coverage ceiling.
2. Detect every usable direct-road, nearby-road, and landmark reference in
   active listing text.
3. Resolve references from a complete offline road/landmark gazetteer where
   evidence is sufficient.
4. Make every unresolved or ambiguous reference observable in a coverage
   queue; never silently lose a detected location reference.
5. Display approximate locations honestly and visibly.
6. Keep map resolution separate from valuation, dedup, and canonical listing
   fields.
7. Make registry refresh and full backfill deterministic, testable, and
   repeatable.

## Non-goals

- Claiming a parcel-exact position without source coordinates.
- Writing inferred map roads or landmarks into `listings.road_name`,
  `listings.ward`, or other valuation inputs.
- Live geocoding from a public API during map requests, crawl, or reprocess.
- Calling an external LLM for location extraction or verification.
- Inventing random marker offsets to make overlapping listings appear precise.
- Treating a nearby road as the listing's frontage road.
- Automatically accepting an ambiguous road or landmark candidate.

## Location Semantics

The final derived location supports five visible precision classes:

| Precision | Meaning | UI |
|---|---|---|
| `exact` | Source provides a validated coordinate | Solid exact pin |
| `road` | Listing is on a verified road segment | Indigo road marker |
| `landmark` | Verified TĐC/KDC/project area is known but parcel/road is not | Teal area marker |
| `nearby` | Listing is near, one turn from, or a stated distance from a verified road/landmark | Dashed circle and approximate label |
| `ward` | Only the canonical ward is usable | Amber ward marker |

`unmapped` remains a summary state, not a stored precision. It applies when no
supported city/ward, road, landmark, or exact coordinate can be resolved.

Location labels must state the evidence, for example:

- `Theo đường ĐX 096, Hiệp An`;
- `Theo khu TĐC Phú Chánh D`;
- `Vị trí gần ĐX 120, cách khoảng 100 m`;
- `Theo trung tâm phường Tân An`.

Only `exact` may use copy such as “vị trí chính xác”.

## Architecture

### 1. Generated offline gazetteer

Replace the hand-selected road source list with a builder that consumes a
pinned OpenStreetMap/Overpass extract for the supported coverage area.

The extract includes:

- every `highway` way with a usable `name` or `ref`;
- administrative or verified old-ward polygons used by the product;
- named residential areas, projects, quarters, and places that may represent
  TĐC/KDC/project landmarks.

The builder:

1. normalizes names and codes with the shared location normalizer;
2. merges connected OSM ways with the same normalized road identity;
3. intersects road geometry with canonical old-ward polygons;
4. creates a separate entry for each road/ward intersection;
5. stores a representative point on the intersected road geometry;
6. records geometry extent so an honest approximation radius can be derived;
7. preserves OSM IDs, source URL, extract timestamp, hashes, and resolver
   version;
8. rejects geometries outside the supported bounds;
9. rejects same-key duplicates unless a deterministic merge is possible.

There is no hand-maintained allowlist limiting how many OSM roads are emitted.
Curated overrides remain additive and are used only when OSM is missing,
misnamed, or spatially ambiguous.

Generated artifacts:

```text
static/maps/listing-locations/
  manifest.json
  ward-centers.json
  road-centers.json
  landmark-centers.json
```

The manifest contains counts and hashes for every artifact plus counts of
resolved, ambiguous, rejected, and curated records.

### 2. Curated local overrides and aliases

`config/listing_map_location_overrides.json` contains reviewable exceptions:

- road aliases such as `DX096`, `DX96`, `ĐX 096`;
- numbered-road variants such as `Đường 88` and `Đường số 88`;
- TĐC/TDC/tái định cư aliases;
- KDC/khu dân cư/project aliases;
- verified points, polygons, or radii for local roads and landmarks not
  represented in OSM;
- ward and landmark scoping needed to disambiguate common road numbers.

Every coordinate-bearing override must include:

- a human-readable source;
- an HTTPS source URL or a checked-in official artifact reference;
- the date verified;
- a precision type;
- an explicit radius when only an approximate point is available.

An override without provenance fails the registry build. A common road number
cannot be globally aliased; it must be scoped by city and ward, and by landmark
when needed.

### 3. Map-only context extractor

Create a dedicated, deterministic extractor for Maps. It consumes title,
description, canonical ward, and stored road name, but it never modifies
canonical listing fields.

It produces:

```text
direct_road
nearby_road
landmark
relation
distance_m
evidence_text
```

Supported relation classes:

- `on`: mặt tiền, đường, nằm trên, tiếp giáp;
- `alley`: hẻm, nhánh, một sẹc/xẹt, `1/`;
- `near`: gần, cách, sát, kế, cạnh, ra đường, thông ra;
- `landmark_only`: usable landmark with no usable road.

The extractor recognizes normalized forms of:

- `TĐC`, `TDC`, `tái định cư`;
- `KDC`, `khu dân cư`;
- `khu đô thị`, `dự án`, `khu phố`;
- coded roads such as DX/ĐX, D, DB, DH, DL, NL, N and numbered internal roads;
- stated metric distance near the reference.

It fixes the current numbered-road parsing defect so `Đường 88` and
`Đường số 88` normalize to one map candidate. Canonical extraction behavior
for proximity phrases stays unchanged.

Map extraction runs during location backfill, not in public API hot paths.

### 4. Deterministic resolver

Resolution order:

1. validated source coordinate → `exact`;
2. direct road intersected with a matched landmark → `road`;
3. direct road uniquely matched within canonical city/ward → `road`;
4. matched landmark with verified geometry/point → `landmark`;
5. nearby/alley road intersected with a landmark → `nearby`;
6. nearby/alley road uniquely matched within city/ward → `nearby`;
7. canonical ward center → `ward`;
8. otherwise → `unmapped`.

Guards:

- A normalized road matching multiple candidates in the same city/ward is
  `ambiguous` unless landmark context resolves it.
- A road/landmark conflict does not silently choose one; it enters the coverage
  queue.
- An old canonical ward remains the filter/valuation ward. Landmark evidence
  may locate the map point across a post-merger or broker-text mismatch, but the
  derived row records that mismatch for review.
- A nearby relation can never be stored as `road`.
- The resolver does not use randomness.

For `nearby`, `accuracy_radius_m` is derived from:

- stated distance when present;
- landmark geometry extent;
- the road segment extent inside the matched landmark or ward;
- a documented minimum uncertainty radius.

The UI must not show a radius smaller than the available evidence supports.

### 5. Derived storage

Extend `listing_map_locations` additively:

```text
location_precision
location_key
location_label
lat
lng
accuracy_radius_m
relation
reference_road
landmark_key
resolution_status
resolution_reason
resolver_version
listing_location_signature
updated_at
```

Allowed stored precision values become:

```text
exact, road, landmark, nearby, ward
```

`resolution_status` is one of:

```text
resolved, ambiguous, not_found, invalid
```

Any row with a valid stored precision and coordinates is rendered. An
ambiguous or not-found detected reference may still produce an honest ward
fallback; its non-resolved status/reason is retained for the coverage queue and
must not suppress that fallback marker.

The signature includes canonical ward, stored road name, normalized map context
inputs, and source coordinates. A resolver-version change forces a full
re-evaluation.

### 6. Coverage queue and audit

Add a derived coverage table or equivalent persisted audit model keyed by the
normalized candidate:

```text
city
ward
road_candidate
landmark_candidate
relation
status
affected_listing_count
sample_listing_ids
first_seen_at
last_seen_at
resolution_note
```

The post-crawl scoped backfill updates counts. A full audit command rebuilds
them from current listings.

Required CLI:

```powershell
python radar.py map-location-coverage
python radar.py map-location-coverage --status unresolved
python radar.py map-locations --full --dry-run
python radar.py map-locations --full
```

The report sorts unresolved candidates by affected active-listing count. It
separates:

- missing from the gazetteer;
- ambiguous duplicate names;
- road/landmark conflicts;
- unsupported location;
- invalid or insufficient text.

This makes new coverage gaps observable immediately instead of discovering
them from user reports.

An admin-only “Map Coverage” queue may expose the same read model after the
core pipeline is verified. The CLI and persisted audit are required for this
release; an admin editing UI is not required.

### 7. Map API and UI

Summary and item APIs remain compact and tier-safe. They add only:

```text
precision
accuracy_radius_m
relation
location_label
```

No description, evidence text, URL, phone number, source coordinate, or
provenance URL is exposed through public map APIs.

The map:

- renders exact/road/landmark/ward groups as visibly distinct markers;
- renders `nearby` as a dashed translucent circle plus a center marker;
- shows “Vị trí gần đúng” for `nearby`;
- shows location precision in the selected-group panel;
- keeps server grouping and pagination;
- does not apply client-side jitter;
- preserves the current modal-over-map and close-state behavior.

The summary reports:

```text
exact_count
road_count
landmark_count
nearby_count
ward_count
unmapped_count
```

The invariant becomes:

```text
exact + road + landmark + nearby + ward = mapped
mapped + unmapped = total
```

## Continuous Lifecycle

### After crawl/reprocess

1. Resolve newly written listing IDs.
2. Update candidate coverage counts.
3. Preserve unresolved evidence for audit.
4. Invalidate map caches only after successful derived writes.

### Registry refresh

Registry refresh is an explicit offline/release operation:

1. fetch or provide a pinned OSM extract;
2. build candidate artifacts;
3. validate bounds, identities, provenance, and hashes;
4. compare coverage against the current production-derived candidate report;
5. review ambiguous and curated changes;
6. commit the artifacts and resolver-version bump;
7. deploy;
8. run a full production location backfill.

Public map requests never call Overpass, Nominatim, Google, or another
geocoder.

## Example Acceptance Cases

The following production listings are regression fixtures:

| Listing | Expected result |
|---|---|
| `63565` | Road-level Đường số 35 scoped to TĐC Phú Chánh B |
| `63566` | Road-level Đường số 37 scoped to TĐC Phú Chánh B |
| `63436` | TĐC Phú Chánh D landmark, or road-level Đường 88 only when the road is verified |
| `63432` | Road-level DX120 when a verified registry entry exists; otherwise a visibly approximate landmark fallback |
| `63514` | Road-level DX096 |
| `63425` | Road-level DX092 |
| `62260` | TĐC Định Hòa landmark, or road-level 11B only when verified |

Additional regression cases cover:

- `cách DX120 100m`;
- `1 sẹc đường Huỳnh Thị Hiếu`;
- `sát đường ĐX 092`;
- landmark-only `TĐC Phú Chánh C`;
- landmark-only `KDC ...`;
- duplicate `Đường số 35` candidates in different landmarks;
- road/ward conflict;
- listing with no usable road or landmark.

## Coverage Acceptance Criteria

The release is complete when:

1. The road gazetteer builder emits every valid named/ref road from the pinned
   supported-area extract; there is no manual road-count ceiling.
2. Every detected road/landmark candidate is classified as resolved,
   ambiguous, not found, or invalid.
3. No listing with a resolvable direct road or landmark remains silently at
   ward precision.
4. Every ambiguous/not-found candidate appears in the coverage report with
   affected counts and sample IDs.
5. All example acceptance cases produce the expected honest precision.
6. Existing filter parity, redaction, modal overlay, history, accessibility,
   and map-close behavior remain intact.
7. Public API invariants hold for both Săn Deal and Tin Rao.
8. Production smoke verifies counts, examples, circle rendering, modal
   behavior, and zero browser console errors.

No target percentage is used to hide uncertainty. Ward-only listings are
allowed only when the input truly lacks a resolvable road/landmark or when an
explicit unresolved status explains the fallback.

## Testing

Implementation follows TDD and includes:

- normalizer tests for road-code and numbered-road variants;
- map-context tests for direct/near/alley/landmark/distance relations;
- gazetteer-builder tests for complete extraction, ward intersection,
  deterministic hashes, ambiguity, bounds, and provenance;
- resolver tests for precedence, conflict handling, radii, and signatures;
- backfill tests for scoped/full/dry-run behavior and coverage queue updates;
- migration tests for additive columns and allowed precision values;
- API tests for new counts and strict redaction;
- JavaScript tests for nearby circles and precision copy;
- rendered desktop/mobile tests for visibility and interaction;
- production read-only audits before backfill and production smoke after
  deploy.

## Performance

- Public map APIs continue to read only derived locations and compact listing
  fields.
- Title/description parsing occurs only in the backfill pipeline.
- Gazetteer artifacts are loaded once per process and indexed by normalized
  city/ward/road/landmark keys.
- Coverage aggregation is performed after derived writes, not per map request.
- Existing map caches continue to key on resolver version and data version.

## Security and Privacy

- Public APIs do not expose listing descriptions, evidence excerpts, original
  URLs, phone numbers, or provenance URLs.
- Coverage samples are admin/CLI only.
- No provider key or protected GIS token is required.
- No external network call occurs in a public request, crawl, or reprocess.

## Rollout and Rollback

Rollout:

1. add schema migrations and compatibility reads;
2. add the map-only extractor and generated gazetteer builder;
3. build and validate the complete registry;
4. run a read-only coverage audit against a production snapshot;
5. implement resolver/backfill/API/UI changes;
6. run focused and regression tests;
7. commit and push;
8. deploy code and artifacts;
9. run the full production map-location backfill;
10. verify public Maps for both tabs and the regression listing IDs.

Rollback:

- derived location data remains separate from canonical listings;
- deploy the previous code/registry version;
- rerun the previous resolver's full backfill;
- no valuation, dedup, listing, or human-review fields require restoration.
