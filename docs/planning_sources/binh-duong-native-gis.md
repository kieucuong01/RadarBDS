# Bình Dương historic area expansion — local pilot

This extends the existing Maps/parcel pilot to 91 historic wards and communes in
nine districts. Run `scripts/run_planning_pilot.py` on loopback port 5055 for
the private preview. The opt-in production extension below publishes the verified
asset through separate public routes after the release gates pass.

## Production activation

The user explicitly requested commit/push/deploy on 2026-10-28. The runtime
extension is opt-in with `RADAR_PLANNING_LIVE_ENABLED=1`; `RADAR_PLANNING_MAP_ENABLED=0`
still disables all public planning. The local runner is never installed publicly.
Public routes use `/api/planning/`, the existing viewport/search/GIS validators,
and a read-only SQLite asset containing only source parcel identifiers, sheet,
number, area and geometry, without owner/contact fields. Previous PDF/drawing
assets and source inspection remain available; old GIS snapshots are inspection
alternatives rather than duplicate default overlays.

Build `scripts/prepare_planning_live_release.py` locally. It writes a tracked
`config/planning_live_release.json` and an ignored archive containing only
`parcels.sqlite` plus four validated native-grid metadata files. Transfer and
extract it under ignored `data/planning/<release>/`; validate archive members
against the manifest before extraction, retain the previous complete release,
and run `python scripts/prepare_planning_live_release.py --verify` before enabling.
That check streams all hashes, reconciles exactly 91 historic area codes and
counts, and checks SQLite/RTree integrity. Startup checks grid hashes, asset
sizes and area metadata without rehashing the large index in every worker.
Make released assets read-only to the service account; give it write access
only to `data/planning/tile-cache/`.

The public native cache shares a POSIX write/prune lock between workers and
retains at most 128 tiles (at most 2 MB PNG each), with 24-hour source freshness.
Per-worker upstream concurrency and flight queues remain bounded. Requests also
have bounded process-memory budgets by IP: 9,000 tile, 1,800 parcel/navigation,
and 120 upstream planning lookups/hour per worker. This is backpressure for
the initial release, not evidence of production concurrency capacity. All
planning API responses remain private/no-store and never carry the public
dashboard cache marker. No token is persisted or exposed.

Rollback: set `RADAR_PLANNING_LIVE_ENABLED=0` and restart `radar-bds.service`.
The previous validated static GIS/PDF release resumes; keep runtime asset
directories for recovery. Source gaps documented below remain gaps after deployment.

The user-confirmed scope is **Bình Dương cũ only**: Thủ Dầu Một (14), Bến Cát
(8), Thuận An (10), Dĩ An (7), Tân Uyên (12), Bắc Tân Uyên (10), Bàu Bàng (7),
Dầu Tiếng (12) and Phú Giáo (11). The total is 91 historic wards/communes.
Use their historic district/ward codes for capture, navigation and coverage
audits. The official GIS is now hosted by Hồ Chí Minh City; that hostname does
not expand this pilot to the rest of the merged city or former Bà Rịa–Vũng Tàu.

## Planning imagery

The official public application is <https://gisxaydung.tphcm.gov.vn/tracuuttqh>.
Its public menu (`/sys/menuaxigis`, observed 2026-10-28) selects these base layers:

| Map family | Primary service under `/arcm/rest/services/HCM/` | Supplement on the same grid |
| --- | --- | --- |
| Partition / commune general planning | `SuDungDat_QHPK_HCM_V2/MapServer` | `QHXD_SDD_2025_QHPK_V3/MapServer` |
| Urban general planning | `SuDungDat_QHC_HCM/MapServer` | `QHXD_SDD_2025_QHCDT/MapServer` |

`scripts/prepare_planning_tiles.py` verifies all four tile grids before enabling the
gateway. They use Web Mercator, a 256 × 256 XYZ grid and native zoom levels through
23. Opaque primary tiles retain their exact source PNG bytes. It does not enlarge the old
district overview images. A source 404 may use a 256 × 256 export only after the
source confirms the identical grid extent and spatial reference.

The main partition cache omits many rural plans present in the source's other
public services. A full-area check also found a general-planning gap around Tân
Vĩnh Hiệp that a centre-only check missed. Both families use the supplements above
on their identical verified native grids. An opaque primary tile is returned unchanged.
For a transparent primary tile it returns the supplement, or composites the
primary over the supplement at the same pixel coordinates. There is no resizing,
reprojection in this code, or replacement of source classes. One resulting tile
keeps opacity consistent. Cache paths include service names so older source tiles
cannot silently survive a source change.

The browser loads visible tiles and a one-tile buffer, retains the provider while
panning/zooming, and changes opacity without downloading again. The gateway caps
upstream concurrency at four, deduplicates in-flight keys, retries one transient
transport failure and retains at most 4,096 tiles for up to 24 hours. These are
local pilot limits, not production load evidence. Previous GIS snapshots stay in
the source inspector; PDFs/drawings remain selectable.

Both basemap providers retain native level-19 raster tiles through viewer zoom 23
using Leaflet's `maxNativeZoom: 19` and `maxZoom: 23`. Previously their `maxZoom: 19`
removed the base at zoom 20 while GIS layers kept the viewer open through 23;
hiding GIS could also change the viewer's zoom limit. The basemap is intentionally
enlarged above its native limit; planning tiles still use their actual zoom grid.
This distinction follows [Leaflet's native zoom contract](https://leafletjs.com/reference.html#gridlayer-maxnativezoom).
Actual browser checks at zoom 20 retain loaded native-19 street and satellite
images. Street image URLs and screen rectangles remain identical when hiding GIS.
JS/CSS share the refreshed `maps-native-base-20261028` cache version.

## Source coverage audit

Centre-tile checks at zoom 15 returned nonempty general-planning imagery for all
91 navigation samples. This does not prove complete coverage of each polygon.
Partition counts were queried separately for main layers 1 and 2 and the
supplement, with exact historic district/ward codes. The main-layer sums reconcile
with independent district counts.

| Historic district | Units | Main cache | Supplement | Combined objects assigned to units |
| --- | ---: | ---: | ---: | ---: |
| Thủ Dầu Một | 14 | 14 | 14 | 14 |
| Bến Cát | 8 | 8 | 8 | 8 |
| Thuận An | 10 | 10 | 10 | 10 |
| Dĩ An | 7 | 7 | 7 | 7 |
| Tân Uyên | 12 | 7 | 12 | 12 |
| Dầu Tiếng | 12 | 1 | 11 | 12 |
| Bàu Bàng | 7 | 0 | 6 | 6 |
| Phú Giáo | 11 | 0 | 11 | 11 |
| Bắc Tân Uyên | 10 | 0 | 8 | 8 |
| **Total** | **91** | **47** | **87** | **88** |

The supplement adds rural commune general plans and other source objects omitted
by the main cache. Lai Uyên, Tân Bình (Bắc Tân Uyên) and Tân Thành have no assigned
partition/commune-general objects in either source. Their urban general planning
still loads in its own family. Native HTTP checks return nonempty combined
partition imagery at 86 of 91 centre samples and general imagery at all 91, with
zero transport errors. This difference from code counts reflects partial coverage
and navigation samples; it is not filled by extrapolation.

A subsequent diagnostic fetched all 172 native tiles at zoom 13 that intersect
the 91 historic administrative reference windows, for both families. Raster masks
derived from those reference polygons measured source-content presence, not legal
or cadastral coverage. The combined partition ratio was approximately 92.37%;
general planning increased from 99.70% to 99.85% after adding its supplement.
There were no completely empty reference areas, but this is **not** evidence of
complete partition plans in every area. Low partition ratios at the Dầu Tiếng
town, Phước Vĩnh, Lai Uyên, Tân Bình and Tân Thành reflect substantial source gaps;
general planning remains a separate family.

For Tân Vĩnh Hiệp the same reference diagnostic increased from 86.65% to 99.81%.
The real parcel `250119` (sheet `18`, parcel `1693`, source area 1,033 m²) has a
representative point that was transparent in the primary general-planning source
at zooms 15, 18 and 20. It is opaque in the combined result at all three zooms;
all images remain 256 × 256. The exact lookup has two source records, and the UI
requires choosing the intended 1,033 m² record rather than guessing the first.

The three units without assigned partition codes were additionally checked by
geometry: all source IDs in each bounding window were reconciled and fetched,
then compared with the administrative references in the source WKT. The full
partition service has 80, 37 and 78 polygons respectively intersecting more than
100 m² of those reference areas, all assigned to neighbouring codes. This proves
why zero code counts cannot establish a geographically empty area. It neither
reassigns those polygons nor clips the displayed map. Further composite services
`QHXD_2025_V1`, `V2` and `V3` returned no partition groups assigned to these three
codes. The two published legacy Bình Dương portal addresses could not be reached
from this host during the check; this does not establish permanent retirement.

General planning is not substituted for missing partition objects. A blank tile
or an empty parcel intersection is not a
conclusion about whether a plan exists or its legal effect.

### Public Guland comparison — 2026-10-28

The user authorized Guland as an alternative source. Its public historic Tân
Bình page exposes separate `qhpk` and `qhc` tile templates under
`https://s3.hn-1.cloud.cmctelecom.vn/guland9/qh-binh-duong/`. The visible
partition control is `bd-qhpk-layer`; generic `data-type` values are reused by
other plan types and must not determine classification. The page displays
512-pixel source images in 256-pixel XYZ cells with maximum native zoom 17.
It also lists land-use-2030, draft, detailed and construction layers; none is
silently substituted for the requested partition family.

A bounded 80-tile check at zoom 17 covered five points near each of six gap
areas plus Tân An/Mỹ Phước controls, for both families. All ten control
partition images contained pixels. All five Phước Vĩnh partition responses
were HTTP 200 **but fully transparent**. The Lai Uyên and Dầu Tiếng partition
samples returned 403; those remain unavailable, not evidence of absence.
Tân Bình had one nonempty partition sample, one transparent and three 403;
Tân Thành had one transparent and four 403. Thạnh Hội had five nonempty
samples. General-plan samples were nonempty for all eight areas.

A separate 42-tile, zoom-13 comparison used administrative reference masks
across all six gap areas. Guland content occupied slightly less of each
reference area than the official combined service. Pixels present only in
Guland occupied about 0.10–0.38% of each reference area; edge/rasterization
differences are not verified additional plans. This does not fill the large
partition gaps or establish every location's source availability. No Guland
layer has been added to the application on the strength of HTTP success alone.
Ignored evidence: `guland-public-sample-audit.json` and
`guland-gap-reference-comparison.json` under `.local/planning-expansion/`.
The observed public page is
<https://guland.vn/soi-quy-hoach/binh-duong/huyen-bac-tan-uyen/xa-tan-binh>.

Rural general-plan intersections can have source scales such as 1/5,000 or
1/25,000. Do not label every general-plan record 1/10,000. Parcel cards retain each
source plan's name, family, scale, decision, intersection area and raw indicators.

Ignored audit captures live under `.local/planning-expansion/`: administrative
source responses, `native-centre-audit.json`, `partition-ward-counts.json`,
`partition-district-counts.json` and the parcel audit. No guest token is persisted.
Additional evidence: `full-reference-raster-audit.json`,
`three-town-native-reference-audit.json`,
`three-town-composite-services-probe.json`, `legacy-portal-probe.json`,
`qhc-tan-vinh-hiep-compare.json` and `qhc-gap-proof-parcel.json`.

## Navigation and parcels

`config/planning_regions.json` contains all 91 source codes and reference
navigation windows. Reproduce it from captured `districts.json` and `wards.json`
with `scripts/build_planning_regions.py`. The checked-in windows serve navigation
only; separate source-content diagnostics also use administrative reference
polygons. Neither clips rendered planning layers or moves parcel vertices.

`scripts/build_planning_parcels.py` resumes complete ward captures after checking
their live source count and snapshot hash. It keeps the previous complete spatial
index until the entire replacement validates. Each ward verifies exact disjoint
source IDs, accepted/excluded reconciliation, source geometry and area membership.
The SQLite index stores all supported areas; the browser still receives only a
bounded viewport or exact area/sheet/parcel matches. See the
[parcel interaction contract](parcel-catalog-local-pilot.md).

The 2026-10-28 source census has 1,142,483 parcel records across 91 units. The
published local index contains 1,142,040 accepted geometries and excludes 443:
228 invalid polygons and 215 invalid rings or coordinates outside the supported
region. All 91 captures reconcile accepted/excluded IDs and their recorded ID
hashes; the SQLite and RTree counts reconcile and integrity checks pass.

Local HTTP viewport, exact sheet/parcel search and live GIS planning lookup were
checked for one real sample in each of all 91 units: all succeeded, and all 91
planning lookups returned plans. These are sample checks, not every parcel's
planning coverage. Invalid source geometries remain excluded with reasons; they
are never silently repaired.
Available imagery, source code counts and successful sample lookups do not certify
full planning coverage or current cadastral/legal accuracy.

Fresh verification after the general-plan supplement and basemap fix: 157 focused Maps tests
pass; two standalone browser cases remain replaced by the in-app browser checks.
The shared supplement test checks both families, opaque primary pixels, correct
source-family selection and unchanged tile dimensions. The separate exact-byte
cache test remains valid for an opaque source tile. No production rollout or
production concurrency result is claimed.
