# Listing Maps Automatic Registry Design

**Date:** 2026-07-29  
**Status:** Approved direction; written spec awaiting final review  
**Scope:** Radar BDS listing Maps for the Săn Deal and Tin Rao tabs

## Context

The current listing-map resolver deliberately treats phrases such as
`cách đường X`, `sát đường X`, and `1 sẹc đường X` as `nearby` locations.
Those listings receive a separate location key, a dashed uncertainty circle,
and a separate map counter. The product decision has changed: these listings
must now be grouped into the marker for road X while retaining their
nearby/alley relationship as internal metadata.

The current registry is generated mainly from named OpenStreetMap roads.
It contains 1,669 road entries but only two resolved landmark entries. Local
places such as TĐC Phú Chánh B can be extracted from listing text, but the
registry has an alias without a landmark coordinate. A listing that mentions
only that landmark therefore falls back to the ward center.

Google Maps currently resolves `Khu tái định cư Phú Chánh B` to a public place
result at `11.058782, 106.7015151`. This proves that browser-assisted research
can discover useful suggestions. It does not prove that every result is safe
to accept automatically.

The user has selected a free-data workflow and explicitly authorized automatic
registry updates without per-entry approval.

## Product Decisions

1. Listings that reference a nearby or alley road are grouped into that road's
   marker when the road can be resolved.
2. The `listing-map-official-gis` block is removed completely from the Maps
   workspace.
3. Google Maps is accessed through a browser only as an offline suggestion
   source. No paid Google API is used.
4. High-confidence suggestions update the generated auto-registry without
   human approval.
5. Ambiguous, conflicting, or low-confidence suggestions are quarantined and
   continue to use the existing honest fallback. Automatic updates must never
   guess a coordinate.
6. Browser-derived map data remains separate from canonical listing fields and
   valuation inputs.

## Goals

- Eliminate the separate `nearby` visual group and uncertainty circle.
- Group `near`, `adjacent`, and `alley` references by the referenced road.
- Resolve high-impact missing roads and landmarks automatically.
- Make the automatic workflow deterministic after browser evidence is
  captured.
- Preserve provenance, confidence, and a complete audit trail.
- Keep the public map compact and truthful.
- Allow a full commit, push, deploy, and production backfill to run without
  waiting for per-candidate approval when all release gates pass.

## Non-Goals

- Do not write inferred roads or coordinates into `listings.road_name`,
  `listings.ward`, or valuation fields.
- Do not browse Google Maps during public API requests, crawl processing, or
  page rendering.
- Do not accept a result merely because Google Maps returned something.
- Do not automate CAPTCHA solving, login bypasses, or high-volume scraping.
- Do not overwrite existing curated entries when a new suggestion conflicts
  with them.
- Do not restore embedded planning/GIS layers.

## User-Facing Map Behavior

### Nearby and alley references

When a listing says `cách đường X`, `sát đường X`, `gần đường X`,
`1 sẹc đường X`, or an equivalent supported phrase:

- the context extractor still records `relation=near` or `relation=alley`;
- the resolver matches X against the road registry;
- a successful match stores `location_precision=road`;
- the location key is the same road key used by direct-road listings;
- the listing is counted under `Theo đường`;
- no radius circle is rendered;
- the item payload may expose a compact relation label, but the group must not
  imply that the property has frontage on X.

If X cannot be resolved, the resolver must not fabricate a road marker. It
uses a resolved landmark or ward fallback and writes the missing road into the
coverage queue.

The database may continue accepting the legacy `nearby` precision for backward
compatibility, but the new resolver must stop emitting it. A full backfill
removes legacy `nearby` rows from active map results.

### Official GIS block

Remove:

- the `listing-map-official-gis` template block;
- its responsive and theme CSS;
- the `listingMapOfficialGisLink` JavaScript binding;
- the `listing_map_official_gis_opened` analytics event;
- tests that require the block or event.

No replacement promotional block is added.

### Precision legend and counters

The active public precision set becomes:

- exact;
- road;
- landmark;
- ward.

The summary invariant becomes:

```text
exact + road + landmark + ward = mapped
```

For one compatibility release, production responses keep
`nearby_count: 0`. The UI ignores that field and does not render a nearby
counter. Removing the field entirely is outside this change.

## Automatic Browser-Assisted Registry

### Components

1. **Coverage queue**
   - Existing unresolved coverage rows remain the source of work.
   - Candidates are sorted by affected listing count.
   - Roads and landmarks are processed separately.

2. **Browser research runner**
   - Processes one unique normalized candidate at a time.
   - Builds a query from candidate name, ward, city, and optional landmark.
   - Opens Google Maps through the controlled browser.
   - Captures only the selected result needed for validation:
     result title, visible address, stable public result URL, latitude,
     longitude, query text, and checked time.
   - Uses bounded pacing and stops on CAPTCHA, consent, account, or blocking
     interstitials.

3. **Confidence evaluator**
   - Scores the captured result using deterministic gates.
   - Produces `accepted`, `quarantined`, or `not_found`.
   - Does not modify the registry directly.

4. **Generated auto-overrides**
   - Accepted suggestions are written to
     `config/listing_map_location_auto_overrides.json`.
   - Manual overrides remain in
     `config/listing_map_location_overrides.json`.
   - The registry builder merges manual overrides first, then non-conflicting
     accepted auto-overrides.
   - Generated entries are stable and reproducible without reopening a
     browser.

5. **Release runner**
   - Rebuilds registry artifacts.
   - Runs validation and regression tests.
   - Performs a dry-run backfill and checks coverage deltas.
   - Automatically commits, pushes, deploys, and applies the full backfill only
     if every release gate passes.

### Auto-override evidence

Each accepted entry stores these required fields:

| Field | Meaning |
|---|---|
| `candidate_type` | `road` or `landmark` |
| `city`, `ward`, `canonical`, `aliases` | Scoped normalized identity |
| `lat`, `lng`, `accuracy_radius_m` | Accepted derived map point and internal uncertainty |
| `source` | `Google Maps browser suggestion` |
| `source_url` | Complete public Google Maps result URL captured by the browser |
| `result_title`, `result_address`, `query` | Evidence used by the confidence evaluator |
| `confidence` | Deterministic score from `0` to `1` |
| `checked_at` | UTC timestamp of the browser check |
| `evidence_hash` | SHA-256 of canonical JSON for the evidence fields |

For the first TĐC Phú Chánh B research candidate, the browser observed:

- title: `Khu tái định cư Phú Chánh B`;
- coordinates: `11.058782, 106.7015151`;
- address context: `Đ. Số 55, Khu TĐC Phú Chánh B`;
- public result URL:
  `https://www.google.com/maps/place/Khu+t%C3%A1i+%C4%91%E1%BB%8Bnh+c%C6%B0+Ph%C3%BA+Ch%C3%A1nh+B/@11.058782,106.7015151,17z/data=!3m1!4b1!4m6!3m5!1s0x3174cfc3c87ff1b1:0x62a06002cd918551!8m2!3d11.058782!4d106.7015151!16s%2Fg%2F11ggg3n5ns`.

This observation is not active registry data until the automatic evaluator
calculates its score and all acceptance gates pass.

### Automatic acceptance gates

A candidate is auto-accepted only when all applicable hard gates pass:

1. Exactly one selected Google Maps result is present.
2. The normalized result title contains the full canonical candidate or a
   configured full alias. Token-fragment matches are insufficient.
3. The result URL exposes valid coordinates inside Radar BDS service bounds.
4. The visible address or result context matches the requested city and either:
   - matches the canonical ward/legacy ward alias; or
   - passes an explicit post-merger/legacy-boundary compatibility rule.
5. The point is not an implausible spatial outlier from the requested ward or
   a matched landmark cluster.
6. The suggestion does not conflict with a manual override.
7. Duplicate names in materially different locations are not collapsed.
8. Required provenance fields are complete.
9. The computed confidence is at least `0.90`.

Additional road gates:

- the full normalized road token must match;
- numbered roads must include ward or landmark context;
- a common road number cannot be accepted globally;
- a road result that resolves only to a neighborhood or business is rejected.

Additional landmark gates:

- the result type and address must describe the requested TĐC/KDC/project;
- a landmark point may be accepted separately even when related road entries
  are far from its centroid;
- the automatic updater must not move or relabel those roads solely to make
  them agree with the landmark point.

### Quarantine rules

A candidate is quarantined without updating the active registry when:

- multiple plausible results exist;
- only a partial name match is available;
- city or ward evidence conflicts;
- the coordinate is outside service bounds;
- the result is a business/person rather than the requested road or area;
- a CAPTCHA, login requirement, or anti-automation block appears;
- the browser page shape does not provide the required evidence;
- an accepted entry would overwrite a manual override;
- a large spatial conflict cannot be explained by a supported landmark or
  legacy-boundary rule.

Quarantined candidates retain their current landmark/ward fallback and remain
visible in the coverage report. They do not require user approval, but they
also do not auto-release.

## Registry Merge and Versioning

The registry builder loads:

1. generated named OSM roads and landmarks;
2. existing manual aliases and curated entries;
3. accepted browser auto-overrides.

Precedence:

```text
manual override > accepted auto-override > generated OSM entry
```

Auto-overrides cannot delete manual entries. A conflict is a build failure or
quarantine outcome, never last-write-wins.

Every accepted change increments the resolver/registry content version through
artifact hashes. Browser evidence is captured once; deterministic rebuilds use
the saved JSON rather than querying Google again.

Accepted entries are rechecked after 180 days when they still affect active
listings. A transient lookup failure does not delete an existing entry. Removal
requires repeated evidence that the place moved, disappeared, or was
misidentified.

## Automatic Run and Release Gates

The browser research run is an operator/agent maintenance workflow, not a VPS
request-time dependency. It can run on a schedule or on demand.

Suggested initial limits:

- process up to 50 unique high-impact candidates per run;
- one Google Maps query at a time;
- stop the batch when the browser is blocked or the page contract changes;
- do not retry a blocked candidate repeatedly in the same run.

An automatic release is allowed only when:

- registry build is deterministic;
- all map-focused tests pass;
- no accepted point is outside service bounds;
- no manual override conflict exists;
- dry-run backfill invariants hold;
- mapped precision counts sum correctly;
- the number of ward fallbacks does not increase unexpectedly;
- the number of resolved roads/landmarks improves or remains unchanged;
- public redaction tests pass;
- production smoke and modal-state tests pass after deploy.

If a release gate fails, the run stops before commit/push/deploy and records the
failure. This is a safety failure, not a request for user approval.

## TĐC Phú Chánh B First Slice

The first automatic research slice includes:

- TĐC Phú Chánh B;
- TĐC Phú Chánh C;
- TĐC Phú Chánh D;
- TĐC Định Hòa;
- numbered roads scoped to those landmarks;
- the highest-impact unresolved DX/ĐX roads.

For TĐC Phú Chánh B, the current Google Maps result is treated as a candidate
landmark centroid. Existing Đường 35/37 overrides remain separate. After
acceptance and backfill:

- a listing that mentions only TĐC Phú Chánh B groups at the landmark marker;
- a listing that mentions Đường 35 or 37 groups at the corresponding road
  marker;
- a listing that says `cách/sát/1 sẹc Đường 35` groups into the Đường 35
  marker while retaining its relation metadata.

## Error Handling and Observability

Each run records:

- candidates attempted, accepted, quarantined, and not found;
- affected listing counts before and after;
- browser block/CAPTCHA/page-contract failures;
- accepted evidence hashes and registry hashes;
- dry-run and applied backfill totals;
- commit, push, deploy, and production smoke results.

No full listing description, phone, source URL, browser cookie, or private
session data is written to the evidence file.

## Testing

### Context and resolver

- nearby and alley phrases still extract the referenced road and relation;
- resolvable nearby/alley roads return `precision=road`;
- direct and nearby references to the same road share one location key;
- unresolved nearby roads remain in coverage and do not create fake road
  markers;
- nearby relation metadata does not mutate canonical road fields.

### Browser evidence and confidence

- exact landmark title/address/coordinate passes;
- partial title, business result, wrong ward, multiple results, or invalid URL
  quarantines;
- common numbered roads require ward/landmark scope;
- manual override conflicts quarantine;
- evidence serialization is deterministic and secret-free.

### Registry

- manual precedence is enforced;
- accepted auto-overrides merge reproducibly;
- ambiguous entries do not enter active artifacts;
- TĐC Phú Chánh B landmark-only and road-scoped examples resolve correctly.

### API and UI

- no active `nearby` groups or circles;
- nearby-derived listings count under road;
- GIS block and tracking event are absent;
- modal opening/closing preserves map and selected group state;
- location payloads remain redacted for guest/free/VIP users.

### Release

- full backfill removes legacy active nearby rows;
- summary invariants hold;
- both Săn Deal and Tin Rao Maps render on desktop and mobile;
- production browser console has no map-related errors.

## Rollout

1. Implement nearby-to-road grouping and remove the GIS block.
2. Add auto-override schema, confidence evaluator, and deterministic merge.
3. Add browser research runbook/runner contract and tests.
4. Process the initial TĐC slice.
5. Rebuild registry and run a full dry-run backfill.
6. Commit, push, deploy, and apply the full production backfill automatically
   if all gates pass.
7. Process the top 200 remaining high-impact candidates in bounded batches.
8. Continue scheduled maintenance batches for new unresolved candidates.

## Acceptance Criteria

1. Resolved `cách/sát/1 sẹc đường X` listings share road X's marker.
2. No active nearby circle, badge, counter, or separate group remains.
3. `listing-map-official-gis` and its tracking code are absent.
4. Landmark-only TĐC Phú Chánh B listings no longer fall to ward center after
   the candidate passes automatic gates.
5. Automatic high-confidence registry updates require no user approval.
6. Ambiguous or conflicting candidates never receive fabricated coordinates.
7. Registry artifacts remain deterministic and fully auditable.
8. Automatic release stops safely on any validation or production-smoke
   failure.
