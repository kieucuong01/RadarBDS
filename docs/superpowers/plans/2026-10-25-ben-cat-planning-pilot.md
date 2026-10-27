# Bến Cát Planning Pilot Implementation Plan

> Execute inline using superpowers:executing-plans. Scope is a local pilot.

**Goal:** Display the real Thới Hòa zoning map over the existing listing Maps,
with toggle and opacity controls, on a loopback-only preview.

**Architecture:** Offline PDF/reference processing produces an ignored raster
and manifest. A local runner serves only fixed pilot assets, injects a pilot
template flag, and mounts a separate Leaflet control on the existing map.

**Tech Stack:** Flask, vanilla JS, Leaflet, pypdfium2, NumPy/OpenCV, pyproj.

**Spec:** `docs/superpowers/specs/2026-10-25-ben-cat-planning-pilot.md`.

## Global constraints

- Local only; no production source-policy changes or dataset writes.
- No secret/session/token extraction; source files are publicly downloadable.
- No source PDF or generated raster committed to Git.
- Controls must work on desktop/mobile and not intercept listing clicks.

## Tasks

- [x] Acquire PDF and geographic reference; identify page, source provenance,
  boundary mask and control/check points; build reproducible local artifacts.
- [x] Test local route isolation, allowlisted filenames, missing artifacts,
  manifest validation and failed image loads; implement runner and overlay module.
- [x] Add opt-in mount to `listing_map.js` and conditional assets in `index.html`.
- [x] Run focused tests, existing Maps contracts, JS syntax, desktop/mobile
  browser checks, and inspect alignment at multiple locations.

## Review focus

- Missing/corrupt raster must leave base maps and markers functional.
- Closing/reopening Maps must not apply a delayed manifest to an old map.
- Local artifacts must not become public via the normal Flask entry point.
- A good fit residual is not independent geographic accuracy.
- Unverified source currency/reuse must remain visible, not relabeled approved.

## Execution ledger

- Source folder linked from Bến Cát publication has malformed `usp` suffix;
  canonical public folder opens without authentication.
- Original file ID: `12OJDgFVXtPZkXh2DGk5XzEeRAwbCEbiv`, 101010377 bytes,
  SHA-256 `9a7c8e9e4112f706ba1ddab9fb0024a456ac0f8e0b8184089187bfe466031151`.
- Work on `codex/ben-cat-planning-pilot`; unrelated untracked folders preserved.
- Artifacts built reproducibly from six fit and three withheld check points;
  fit RMSE 23.6 m, check RMSE 37.2 m and max 53.6 m. This is not a production
  accuracy pass. Geographic reference is OSM, not cadastral survey.
- Node runtime checks cover load error/retry, opacity, teardown, aborted and
  late manifest responses. Browser verified desktop/mobile and street/satellite.
- Final review: fresh reviewer identified the startup preflight preventing base
  Maps from opening without a raster. Added regression, observed failure, removed
  startup preflight, then passed. Reviewer hit account usage limit before finishing
  remaining review; author inspected remaining changes. No complete independent
  review is claimed.
- Browser regression found mobile canvas height 0: Leaflet's inline relative
  positioning overrode absolute CSS. Mobile rule now overrides it; browser verified
  763 px canvas at 390x844. Existing browser-test fixture now includes inline style.
  Browser interactions ran through CUA; five unrelated/standalone browser or DB UI
  tests were excluded from the focused pytest run.
- No matching local listings in the selected filters, so real marker clicks remain
  unverified. Existing Maps JS contract suite passed.
- Ruling: keep the pilot local despite its measured alignment error, unverified
  currency and public reuse rights, as approved by the user; do not use it for
  parcel decisions. Treating it as authoritative would risk incorrect land-use
  conclusions. Production approval gates remain unchanged.
- Run instructions, source provenance and limits:
  `docs/planning_sources/ben-cat-local-pilot.md`.
- Final focused verification: 79 pytest cases passed, 5 excluded as noted above;
  both JavaScript syntax checks and `git diff --check` passed. Live HTTP privacy
  and allowlist checks passed. Preview remains on localhost:5055.
- Graphify query was used for initial structure. Post-change update extracted
  110 code files but did not finish graph generation after several minutes;
  stopped the update. The installed 0.9.26 package reported a mismatch with the
  0.9.54 skill. No refreshed graph is claimed; source/tests supplied final evidence.

## Follow-up: toggle/zoom regression and additional 1:2,000 plans

- User reproduced: first mount zooms correctly; off/on then zoom breaks.
- Browser captured Leaflet `_animateZoom` with null `getZoomScale`. Root cause:
  clearing all layer listeners before `removeLayer` removed Leaflet's own
  remove-event cleanup. The detached image retained zoom hooks on the map.
- Watched new Node regression fail with a detached layer receiving zoom, then
  passed after changing cleanup order. Catalog/selection tests retain this gate.
- Added Tân Định overlay with six manual OSM controls and three withheld checks:
  fit RMSE 15.4 m; check RMSE 25.1 m, max 31.1 m. Original hash and exact points
  live in `config/ben_cat_planning_tan_dinh.json`.
- Downloaded and rendered official Hòa Lợi / Chánh Phú Hòa QH01 sheets. Their
  attempted feature matches were not reliable enough to assign coordinates.
  Ruling: expose original source-sheet previews, label them without an overlay,
  and leave overlay controls disabled — an unverified warp could mislocate land.
- Catalog contains eight historic areas. Mỹ Phước / An Tây / Phú An source links
  return 404; An Điền's public folder contains the decision but no map.
- A real static request exposed immutable caching from app hooks overriding the
  runner's privacy hook. New failing regression confirmed the ordering problem;
  runner's final hook now executes last. Actual catalog and JS verified private,
  no-store after restarting only this preview's processes.
- Final verification: 82 tests passed, 5 excluded; JS/Python syntax and diff check
  passed. Fresh reviewer reported no important findings. Desktop and 390x844
  browser verification passed; viewport overrides were reset afterwards.
- This follow-up remains local; no commit/push/deploy. Source limitations and
  run commands are documented in `docs/planning_sources/ben-cat-local-pilot.md`.

## Completion of remaining six areas, 27 October 2026

- Catalog now contains eight usable overlays. Hòa Lợi and Chánh Phú Hòa were
  manually aligned against actual OSM road intersections, replacing the rejected
  feature matches. Six controls plus three withheld checks per manual layer.
  Max check errors: Hòa Lợi 24.1 m, Chánh Phú Hòa 10.7 m, An Tây 8.9 m,
  Phú An 19.3 m, An Điền 85.7 m. Northern/river fringes remain unverified.
- The parallel-agent skill was applied for independent source/georeference
  tasks and a final read-only review; shared UI/runner changes stayed with the
  parent. Final reviewer found no actionable correctness issues in the native
  GIS builder, optional legend, selection lifecycle, or eight local manifests.
  Reviewer did not independently repeat browser rendering.
- Mỹ Phước uses a public official GIS raster snapshot captured 26 October,
  preserving the native EPSG:3857 pixel grid. The official plan outline export
  uses SoQD_DC 2913 and the same grid. The builder validates hashes, outline
  closure, extent/size agreement and a coarse area reference before clipping.
  No fabricated fit-error number; original GIS link supplies the legend.
- An Điền / An Tây / Phú An images come from primary consultant A.A.P. The
  selector, attribution and notices distinguish them from stamped published
  maps. An Điền's approval fields are blank and its error is around 100 m;
  it is suitable only for regional exploration in this local experiment.
- 90 focused tests pass; two standalone-browser tests are excluded because
  browser interaction uses CUA. Node lifecycle regression, Python/JS syntax and
  whitespace checks pass. Actual local HTTP confirms all eight overlays return
  200; native missing legend and unallowlisted sources return 404; static and
  catalog responses remain private/no-store and foreign Hosts are rejected.
- Browser checked every layer loaded, one image after source changes, off/on
  followed by zoom, opacity and native-coordinate metadata without undefined
  values. Preview server restarted with the complete catalog on localhost:5055.
- No production release, commit, or push. Existing production gates unchanged.

## Multi-select follow-up, 27 October 2026

- User requested simultaneous ward/city selection. Replace exclusive overlay
  selection with ward checkboxes grouped by city. City checkbox selects ready
  members and reflects partial selection. Current real catalog remains Bến Cát.
- Keep source inspection independent of visible layers. One common opacity and
  master visibility switch; fitting uses the union of selected extents. Failed
  layers can be retried without removing their neighbours. Keep stable z-order.
- Added a failing Node regression for city-wide multi-selection before changes;
  tests now cover two synthetic cities, partial membership, bounds union, common
  opacity, individual failure/retry, master off/on and detached zoom cleanup.
- 90 focused pytest cases pass, 2 standalone-browser cases excluded. Syntax and
  whitespace checks pass; desktop CUA verified 8 -> 6 -> 0 -> 6 layers and opacity
  0.4 on all six. No production release or unrelated modifications.

## GIS-primary themes and selectable document sources, 27 October 2026

User clarified two distinct themes: partition planning and district land-use
planning (QHSDĐ/KHSDĐ, not the coloured land-use layer inside QHPK). GIS is the
default source for each theme; retain the existing document-derived overlays
and original links as an alternative source. Do not warp the original PDF to
match a potentially different GIS edition or label QHPK as district QHSDĐ.

Implementation scope:

1. Verify/capture native partition GIS for the eight wards, keeping source
   hashes, exact pixel grid, official plan outlines and capture date.
2. Independently locate the district land-use GIS/document source. If a real
   usable source cannot be verified, show that fact and keep its toggle disabled.
   Never substitute QHPK, an unrelated year, or commercial imagery silently.
3. Catalog records identify theme, source and area; retain current documents.
   Shared ward/city selection drives both themes. Each theme has its own toggle,
   GIS/document source choice and opacity. Switching one source preserves the
   other theme. Master off/on and bounds fitting remain available.
4. Test source reconciliation, unsupported/missing sources, isolated failure,
   multi-area lifecycle, opacity by theme and stale image callbacks; then verify
   the rendered local Maps on desktop/mobile. No production release requested.

Result and remaining external dependency:

- Implemented independent theme/source/opacity controls, GIS defaults, retained
  original document artifacts and source links. Catalog has 18 records; source
  switching never silently substitutes document imagery under the GIS label.
- Partition GIS: verified cached Mỹ Phước remains available, seven wards still
  lack new verified captures because public metadata/export/tile requests timed
  out with zero bytes. Native builder and identity/outline/hash gates prepared;
  all-eight-ward GIS synchronization has NOT been achieved.
- District QHSDĐ2030 and KHSDĐ2025 official linked maps currently404. Public GIS
  menu has no verified separate district source; legacy portals fail DNS. Found
  historical KHSDĐ2023 document in an official Drive folder, previewed only:
  approval blocks blank, no verified native CRS, no overlay/current-plan claim.
- 98 focused pytest cases pass, two standalone-browser tests excluded. Review
  caught fixed partition-scale text on district preview and a district-only
  selection dependency; regression tests failed before fixes and now pass.
- Browser desktop verified GIS 1 -> document 7 -> GIS 1, opacity retained at 0.4,
  theme off/on then zoom without detached handlers, historical document-only
  preview and unavailable district source without affecting partition. No live
  district overlay is claimed; its runtime independence uses synthetic tests.
- Final mobile CSS 390x844 verified the same source switch, master toggle and
  zoom with no console errors; viewport reset. Local preview still runs on5055.

## Recovery: all eight partition GIS layers captured, 27 October 2026

- Root found that Python requests with the public portal Origin/Referer returns
  valid metadata and PNG immediately while prior curl calls time out. Replaced
  the downloader after failing regressions; reject empty/non-PNG/error JSON and
  stop on401/403. No authentication tokens extracted or denied endpoints bypassed.
- Public attribute-query endpoints are unavailable; identity uses the official
  ward/decision publication cross-check plus public-render filters on decision
  number and the exact signing date. A wrong-date control returns empty alpha.
  One SQL expression was rejected by the WAF; it was not retried or obfuscated.
  Supported ordinary date predicates worked and all eight outlines validated.
- Captured native rasters and official closed outlines at2400x2400 on each
  server-confirmed pixel grid, staged before promotion. Every ward has source
  PNGs, exact request URLs, capture hashes, mask, manifest and alignment audit.
  Correct publication URL preserved perward rather than one city-ward page.
- Catalog now marks all eight partition/GIS records ready, captured2026-10-27.
  Original PDF/document artifacts untouched. API confirms eight GIS image200s.
- 100 focused tests pass, two standalone-browser cases excluded; JS/Python
  syntax and whitespace checks pass. Desktop browser verified eight loaded GIS
  images, PDF7 -> GIS8, off/on then zoom with no console errors. Mobile verified
  six selected layers back to eight and canvas390x763 at CSS390x844; overrides
  reset. No new independent review claimed because subagent quota was exhausted.
- District land-use GIS remains a separate unresolved external dependency:
  public DNS confirms NXDOMAIN for both old portals; official2030PDF still404.
  Do not describe partition completion as completion of the district layer.
- Still local only; no commit, push, deployment or scheduled task created.


## User scope change: urban general plan replaces district land-use, 27 October 2026

- Removed both district land-use records from the visible catalog. The historical
  ignored research is preserved. Theme is now `urban_general`, labelled1/10.000;
  all eight GIS partition layers and seven PDF/image alternatives are unchanged.
- Independent official-source research verified QĐ1573/QĐ-UBND01/07/2022,
  Bến Cát2040, map schedule1/10.000 (PDFp17§15.b), plus2025 partial amendments.
- Captured the public GIS menu's actual QHC service `SuDungDat_QHC_HCM`,
 2400×2400 EPSG3857,27/10/2026. RGB preserved in lossless WebP. QHC boundary
  query was WAF-rejected; no alternate syntax attempted to bypass it. Display
  uses a hash-pinned union of eight verified native partition footprints,
  explicitly not a verified general-plan boundary. Cannot attest the raster's
  legal decision version or inclusion of2025 amendments; visible notice retained.
- New builder checks service identity, capture/mask hashes, native pixel grids,
  city-area plausibility, missing coverage and edge clipping. Ward builder guards
  are unchanged. Catalog17 rows,9 GIS-ready plus7 document overlays.
- Local API verifies new image200, correct1/10000 metadata and old district404.
  Browser verifies9 loaded GIS images, partitionPDF7+generalGIS1, separate opacity,
  source switching and general off/on then zoom. No production release requested.
