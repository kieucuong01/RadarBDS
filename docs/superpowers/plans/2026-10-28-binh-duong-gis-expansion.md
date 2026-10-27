# Binh Duong GIS Expansion Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement task by task.

**Goal:** Complete planning layers and parcels for all missing historic wards/communes of Thuận An, Dĩ An, Tân Uyên, Bắc Tân Uyên, Bàu Bàng, Dầu Tiếng, Phú Giáo, retaining Bến Cát and Thủ Dầu Một and replacing enlarged general-plan snapshots with clear native zoom tiles.

**Architecture:** Retain the loopback pilot, GIS/PDF inspector, map controls and viewport loaders. Expand the verified administrative catalogue to 91 units, resume bounded ward captures, atomically publish a complete spatial index. Add a bounded cached gateway for the official GIS native XYZ grids and render native tiles for both GIS planning families; preserve existing drawings for comparison.

**Spec:** The active thread goal, including its explicit general-plan clarity requirement and full geographic scope.

**Confirmed boundary:** Bình Dương cũ only, all 91 historic wards/communes in
its nine districts/cities. Do not expand the catalogue to other parts of the
merged Hồ Chí Minh City. The user also authorizes checking public Guland maps
for missing source content alongside the official public GIS.

## Constraints and review focus

- No invented geometry, planning content, current legal validity, classification or source colours.
- Official public source and ward/district codes; owner/contact data excluded.
- Administrative polygon bounds are navigation references only, not cadastral masks.
- Tokens stay in memory for parcel API. Public ArcGIS images use no Authorization header.
- Requests, geographic bounds, concurrency and cache storage remain bounded; cancellation and newest-view semantics stay intact.
- Keep the previous complete index until all 91 captures validate.
- Native service metadata/grid, source pixels and rendered zoom behaviour must substantiate clarity; image upscaling is not a substitute.
- Audit every administrative unit's parcel coverage and both planning collections. Missing source coverage remains incomplete and must be investigated.

## Tasks

- [x] Inspect current worktree and classify previous turn as progress: UI/search changes and passing checks are present; broader geographic goal remains active.
- [x] Verify official administrative catalogue and source parcel counts: 91 units in 9 districts, 1,142,483 source records, all counts positive.
- [x] Expand region config, navigation framing and capture scope; run meaningful tests and start resumable capture.
- [x] Implement validated native tile gateway and frontend rendering; preserve PDF/static alternatives and existing lifecycle checks.
- [x] Complete 91 ward captures and atomic spatial index; verify counts, exclusions, scoped searches and planning lookups by ward.
- [ ] Audit planning imagery/source coverage across all 91 units; resolve actual gaps using official source evidence.
- [x] Verify clear general planning at multiple zooms and real parcel interactions across all named districts; record artifacts and full-scope completion audit.

## Source evidence

Official admin catalogue and metadata captured under ignored `.local/planning-expansion/` on 2026-10-28. Native map service tileInfo is Web Mercator, 256 × 256, levels 0–23. Source cached QHC/QHPK tiles returned PNG at zooms 15 and 19. Discovery captures are evidence of capabilities, not proof of all-unit coverage or legal currency.

Fresh checks: 155 focused tests pass (two standalone browser tests deselected).
In-app browser QHC checks at zooms 19 and 20 show 256-pixel source tiles at their
native CSS size with no old overview image overlays, including after toggling.
The official app's live menu confirms the selected base services. A further
official native-grid service, `QHXD_SDD_2025_QHPK_V3`, supplies many rural commune
plans omitted by the main cache. The combined collection has objects assigned to
88 of 91 units. Lai Uyên, Tân Bình (Bắc Tân Uyên) and Tân Thành remain without
assigned partition/commune-general objects in the checked services; their general
plans and parcels work. This external data gap remains explicit, not a claim of
91-unit partition coverage.

The completed local index reconciles 1,142,040 accepted + 443 excluded = 1,142,483
source records, including all ID hashes and SQLite/RTree integrity. All 91 local
HTTP viewport/search/sample workflows and all 91 live GIS sample lookups succeed.
The local sample/viewport/search chain had median 48 ms, p95 73 ms, max 113 ms in
this run, excluding GIS lookup (median 433 ms, p95 1,854 ms, max 2,709 ms). These
are local samples, not production load claims. Native HTTP image checks across 91
centres succeed for both collections, with 86 nonempty partition centre tiles
and 91 nonempty general tiles; centre samples do not prove full-area coverage.

Actual browser searches cover all seven newly added districts, with source plan
types retained (including commune general plans). QHC native zooms 19/20 were
checked at both Thủ Dầu Một and Bến Cát. Changing opacity retains identical tile
URLs and applies the expected layer opacity. Mobile 390px has no horizontal
overflow; viewport override was reset. Browser console error list is empty.
Screenshots: `planning-bau-bang-parcel.png`, `planning-expanded-mobile.png`,
`planning-general-native-zoom20.png`, `planning-ben-cat-general-native.png` in the
thread visualization output folder. See `docs/planning_sources/binh-duong-native-gis.md`.

## Whole-area follow-up — 2026-10-28

The previous goal turn made verified progress: the 91-unit index, native tile
gateway, source supplements and real browser/API checks are present. This turn
revalidated the live 5055 server's 91 areas and 1,142,040 geometries before
continuing the unresolved source-coverage requirement.

A 172-tile zoom-13 diagnostic across all 91 administrative reference polygons
found a general-plan gap around Tân Vĩnh Hiệp missed by centre-only samples.
`QHXD_SDD_2025_QHCDT` has the same verified native grid and fills that gap. Both
families now share the bounded supplement path, with primary opaque pixels kept
unchanged and service-specific cache namespaces. Four source grids are required
before enabling native routes. No image is enlarged and no type is substituted.

The approximate reference-content ratio in Tân Vĩnh Hiệp increases from 86.65%
to 99.81%; province-wide general content increases from 99.70% to 99.85%. These
are diagnostic raster ratios, not legal/cadastral coverage. Real parcel 250119
(Tân Vĩnh Hiệp, sheet 18 / parcel 1693, 1,033 m²) has transparent original primary
pixels and opaque combined pixels at zooms 15, 18 and 20, all 256 × 256. Its two
source records require an explicit UI choice. A browser search and live GIS
lookup exercise that case. Artifact: `planning-tan-vinh-hiep-general-fixed.png`.

156 focused tests pass (two standalone browser cases deselected); the parameterized
supplement regression verifies both families and unchanged source dimensions.
The refreshed local server uses the four verified grids and complete 91-unit
index. There is no production rollout in this goal turn.

The source-coverage task remains open. Geometry-based checks find neighbouring-code
polygons at the edges of Lai Uyên, Tân Bình and Tân Thành, so zero assigned code
counts must not be described as complete geographical absence. Three additional
composite GIS services still return no assigned partition groups for those codes.
The whole-area diagnostic also exposes limited partition content in the towns
of Dầu Tiếng and Phước Vĩnh. Direct source exports at Thạnh Hội do not fill its
remaining gap, so it is not remedied by silently enlarging or substituting a map.
An optional user question requests any additional GIS source for these urban
areas while existing general planning and parcel workflows remain usable.

The user subsequently authorized the official public GIS or Guland and confirmed
the boundary as Bình Dương cũ only. A fresh public Guland check found transparent
HTTP-200 partition tiles in Phước Vĩnh and unavailable zoom-17 samples in Lai
Uyên/Dầu Tiếng. A wider 42-tile comparison of all six gap reference areas did not
verify substantial new plan content beyond the official source. The application
does not claim complete partition coverage or introduce an unverified substitute.
See the source document's public Guland comparison for the exact evidence.

Further rendered QA reproduced a genuine basemap regression: 12 loaded street
images at zoom 17, then zero at zoom 20, while native GIS images at zoom 20 were
present. The two base providers had `maxZoom: 19`; the new native GIS layer raised
the viewer limit to 23. Base providers now keep their native-19 images visible
through 23 using Leaflet's native zoom clamp. GIS images remain native per zoom.
Actual zoom-20 checks show loaded street and satellite images, and hiding GIS
retains identical street URLs/rectangles (no zoom jump). Before/after artifacts:
`planning-base-high-zoom-before.png`, `planning-base-high-zoom-after.png`,
`planning-satellite-high-zoom-after.png`. Both JS and CSS use the refreshed shared
asset version. The final combined suite passes 157 tests, with the same two
standalone browser cases deselected in favour of actual in-app browser checks.
