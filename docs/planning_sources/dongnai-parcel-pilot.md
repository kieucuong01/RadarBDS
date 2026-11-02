# Dong Nai public cadastral pilot

**2026-11-02 priority recheck:** [old Đồng Nai review](dongnai-priority-review-2026-11-02.md)
reconfirmed maintenance at the historic land portal and count=0 for all eleven
historic Đồng Nai district codes in this parcel service. The current provider
remains former Bình Phước; existing 2030/construction raster samples were checked
separately and the misleading shared-source notice was corrected.

Verified 2026-10-31. Scope: former Binh Phuoc within new Dong Nai. **Former
Dong Nai cadastre has not been integrated.** This is progress toward the national
parcel goal, not nationwide or province-wide completeness certification.

## Public source

**2026-11-02 update:** the former-Bình-Phước source-ID acquisition is complete.
Optional verified local spatial snapshots now support viewport cells, original
corners and indexed sheet/parcel lookup without repeated GIS boundary queries.
See [free acquisition and local index](free-parcel-acquisition.md#bình-phước-completed-capture-and-optional-local-maps-index--2026-11-02)
for counters, strict locality reconciliation, activation, rollback and limits.
Former Đồng Nai and detailed-planning offline coverage are still separate work.

- Portal: https://gis.dongnai.gov.vn/
- Portal bundle also remains available through the old Binh Phuoc HTTP portal.
  Its configuration now points to Dong Nai. The old HTTPS hostname failed
  certificate validation; no certificate checks were bypassed.
- Anonymous app configuration:
  `https://gis.dongnai.gov.vn:82/auth/appinfo/D84927C4-E682-EA11-80CF-97CC0449692F/anonymous`
- Parcel service: `/arcgis/rest/services/NenDiaChinh/MapServer/1`
- Administrative references: same MapServer, layer 3.
- Query requires no account, cookie, copied token or guest credential.
- Count-only query returned **618668** source records. This is not a count of
  independently validated or currently displayed polygons.
- A count-only query for former Bien Hoa district (`MaQuanHuyen='731'`) returned
  zero; that tested old Dong Nai district is not supplied by this layer.
- The old Dong Nai land portal `https://datdai.stnmt.dongnai.gov.vn/` currently
  returns HTTP 200 containing only `Hệ thống đang bảo trì`.

## Reference and geometry handling

The source administrative layer returns 111 historical references. Three ward
codes are reused across different districts. Preserve the original source code
and use `bp-{district}-{ward}` as the public area key, so duplicate codes cannot
cross-match in search. The 111 references do not assert cadastral completeness.

Administrative polygons were requested at four decimal places and their bounds
padded by .0002 degrees for navigation only. Parcel coordinates are requested in
WGS84 without rounding, simplification, vertex repair or a local CRS guess.
ArcGIS performs the source projection from BP_VN2000 to EPSG:4326.

Public object IDs are `1000000000000 + source OBJECTID`. This prevents collisions
with the existing HCM catalogue. Only source OBJECTIDs are sent back to Dong Nai.
Dong Nai IDs are never sent to the HCM planning-intersection API.

Parcel requests use only `OBJECTID,SoTo,SoThua,DienTich,MaPhuongXa,MaQuanHuyen`
plus geometry. Planning requests use an explicit allowlist of zone IDs, project
and functional-zone names, land-use codes and building indicators. Owner,
address, certificate and contact fields are not requested or returned.

The adapter shares existing ring validity, source membership, exact-search,
viewport-intersection, concurrency, cache and response-size guards. It uses one
fixed HTTPS query endpoints, rejects redirects, retains TLS verification, loads at zoom
17+ and limits each source response to 1000 features and 10 MB. Upstream errors
are not silently converted into empty/not-found responses.

## User behavior

- Tờ/thửa > Tỉnh/TP > **Bình Phước (cũ) · Đồng Nai**, then historical district/ward.
- Faint boundaries load only within the current viewport.
- Search and map clicks show the source sheet, parcel, area and provenance.
- Planning-intersection lookup queries the public detailed-planning layer
  `/arcgis/rest/services/QHCT/QHCT_SDD/FeatureServer/0/query` and public general
  planning `/arcgis/rest/services/SuDungDat/ThongTinQuyHoachSDD_Cache/MapServer/6/query` using the accepted
  parcel polygon. Read-only POST avoids IIS URL-length errors for long rings.
  Intersect exact unsimplified source geometry with Shapely and calculate square
  metres geodesically on WGS84 using pinned `pyproj==3.7.2`. Source cadastral area
  remains unchanged. Geometry holes and disconnected pieces are retained.
- Results include detailed-plan name, individual functional zones, intersection
  areas and available building indicators. The union of intersections determines
  each plan's area; overlapping records are not blindly summed into that total.
- General planning's combined spatial+geometry query timed out. Fetch the
  intersecting source IDs first, then retrieve their exact unsimplified geometry
  by ID and verify complete batch membership. A failed layer does not suppress
  available layers; return explicit unavailable-layer warnings. If every layer
  fails, return an error. Partial results have a 15-second cache rather than the
  normal five-minute complete-result cache.
- The UI limits this lookup to detailed and general urban planning. Public
  partition queries timed out and are not enabled. Land-use-2030 raster is not queried here.
  Existing overlays remain independent; no planning status is inferred from a
  raster colour. A failed/incomplete query is an error, not "no planning".
- Existing HCM behaviour and marker priority remain in the shared renderer.

## Verification

- Live exact source query and adapter: Tân Bình, Đồng Xoài, sheet 10 / parcel 281,
  source ID 49268, source area 31.5 m². One exact result returned.
- Live adapter viewport `106.8872,11.5296,106.8875,11.5299`: 15 accepted features.
- Initial rendered desktop: province/district/ward search opened that parcel with
  source attribution. The subsequent information fix adds detailed planning.
- Local rendered mobile 390x844: clicking another polygon opened sheet 10 /
  parcel 199, source area 4000.8 m².
- Live detailed-planning lookup for parcel 199: project "Khu đô thị mới - công
  viên trung tâm Đồng Xoài", 16 intersecting source zones, union area 4001.11 m²,
  measured source lookup about 1.81 seconds in one direct run (not a load test).
- User screenshot regression, Tân Bình sheet 9 / parcel 34 (source ID 49841):
  no detailed-plan result, but a real general-plan intersection with source
  object 15675, code OLK, 3303.32 m². Display label "Đất nhà ở liên kế xây mới"
  comes from the source's `DMMucDichSuDungDat` field domain, saved separately in
  `config/planning_dongnai_land_codes.json`. Do not infer it from raster colour.
- Focused Python suite after the information fix: 44 tests passed, covering the new adapter and the existing
  live/catalogue/parcel/production-route contracts. Browser JS runtime check and
  JS syntax check passed.
- Release candidate 2026-11-01: user authorized commit/push/deploy all completed
  Maps work. 65 focused Python checks plus parcel JS runtime passed before commit.
  Production SHA and verification must be checked separately after deployment.

## Corner-boundary feasibility follow-up — 2026-11-02

User reauthorized research for all new Dong Nai, including former Dong Nai,
with Guland as a possible polygon source. This is research, not expanded coverage.

- The existing corner/OCR tool is geographic rather than HCM-only. WGS84 works
  across both former provinces; VN-2000 options already include TM-3 107°45′
  for former Dong Nai and 106°15′ for former Binh Phuoc. The projection must
  match the document; never infer it solely from the new provincial name.
- Current synthetic four-corner self-checks passed through `coordinate_outline`
  for both regional projection options. This proves software compatibility,
  not cadastral calibration or new source availability.
- The logged-out Guland capture dated 2026-10-30 contains a former Dong Nai
  sample (parcel 891 / sheet 57): 78 lat/lng vertices including closure.
  The current corner validator accepts it as 77 distinct corners and computes
  approximately 19,375.8 m² geodesically. This is a saved sample, not a fresh
  source read or a guarantee of survey area, accuracy or provincial coverage.
- Prior observed point service was POST `https://guland.vn/get-bound-2`;
  direct anonymous access returned 403 during that survey. Today an ordinary
  HTTP GET of the Dong Nai map also returned 403. Browser inspection is blocked
  by Work settings, so fresh point-response and viewport geometry checks remain
  undone. No challenge bypass, copied session or embedded credentials were used.
- Former Dong Nai land portal still returned HTTP 200 with maintenance HTML.
  One known former Binh Phuoc GIS polygon query timed out at 30 seconds today;
  retain existing working adapter and retry/error guards, do not infer empty
  coverage from that transient failure.

If fresh public browser inspection becomes available, verify several former
Dong Nai districts and zoom levels, exact geometry CRS/identifiers, point versus
viewport access, response limits and a stable permitted server access path.
Only integrate after that access path works. Reuse shared parcel cells,
original-geometry lookup and explicit planning-detail actions; never trace PNG
boundaries to fabricate survey corners. Keep old snapshots diagnostic-only.

Evidence is ignored under `.local/dongnai-corners-research/` and the existing
`.local/external-parcels-20261030/`; no raw source bundle or parcel assets added
by this follow-up. No runtime code changed or production deployment performed.

## Guland browser collection verified — 2026-11-02

Chrome control became available after the user's connection/settings refresh.
The ordinary signed-in browser UI returned HTTP 200 from `get-bound-2` after
actual map clicks on both historic province pages. This is not proof of a
stable anonymous server API. No cookie, CSRF token or browser session was
exported or embedded in RadarBDS.

Six fresh, valid parcel polygons are archived locally in the ignored spatial
asset `data/planning/guland-parcels.sqlite`:

| Historic area | Source ID | Sheet / parcel shown | Distinct corners | Planning sections |
| --- | --- | --- | --- | --- |
| Gia Tân 2, Thống Nhất, Đồng Nai | 77549917 | 63 / 115 (old sheet 11) | 5 | Not provided |
| Gia Tân 2, Thống Nhất, Đồng Nai | 77549952 | 63 / 153 (old sheet 11) | 8 | Not provided |
| Gia Tân 1, Thống Nhất, Đồng Nai | 78139813 | 63 / 714 | 7 | Not provided |
| Tân Hưng, Hớn Quản, Bình Phước | 85155898 | 118 / 16 | 32 | 1 section / 4 land-use rows |
| Tân Hưng, Hớn Quản, Bình Phước | 85156524 | 118 / 60 | 15 | 1 section / 1 land-use row |
| Tân Hưng, Hớn Quản, Bình Phước | 85156950 | 119 / 20 | 12 | 1 section / 3 land-use rows |

The three Bình Phước planning sections are labelled **Quy hoạch xây dựng** by
Guland. Preserve that label; do not rename it to detailed 1/500, partition or
general planning without source evidence. The stored rows contain source area
text and the land-use label. They do not contain planning-zone polygons or an
independently verified decision/version. Both provinces currently return source
province code 75, so the old locality links, not that merged code, identify the
historic province. New and old sheet/parcel titles are retained separately.

`scripts/archive_guland_parcels.py` validates sanitized captures, keeps exact
WGS84 vertices, computes a separate geodesic measurement and stores immutable,
content-addressed snapshots in SQLite. Identical imports are skipped. A later
`not_provided` capture cannot overwrite a prior planning snapshot. Source
area/land-use facts remain separate from planning sections and measurements.
Raw source HTML, owner/certificate/contact fields and arbitrary extra fields
are rejected. This archive is independent of the official GIS catalogue and
its numeric IDs; its feature namespace is `guland:<historic-province>:<id>`.

Capture procedure for an authorized browser session:

1. Observe `Network.responseReceived` through the supported browser CDP tool,
   perform an ordinary map click, and read only its successful `get-bound-2`
   response. Do not invoke hidden app functions or reuse browser credentials
   in terminal requests.
2. Select only status, source ID, source admin codes and lat/lng points.
   Read current `#pin-info` titles/locality links and `.type-info` rows.
   Match the response's sheet/parcel identity to the current popup before
   saving, so late responses cannot mix a polygon with another parcel's facts.
3. Planning sections are `.text-row` elements with a `.text-tle` beginning
   Quy hoạch / Định hướng / Kế hoạch; each `.text-col` provides the source area
   text (`.text-col__lbl`) and label (`.text-col__txt`). Other rows, particularly
   owner rows, are not captured. Expansion only revealed existing response
   content on these samples; it was not a separate GIS planning query.
4. Save only the schema accepted by `feature_from_capture`, then import:

```powershell
& $py -X utf8 scripts/archive_guland_parcels.py <sanitized-capture.json>
& $py -X utf8 -m pytest tests/test_archive_guland_parcels.py -q
```

The CLI defaults to the ignored archive above. Input files are capped at 2 MB;
the whole batch validates before any database write. Database integrity and a
second import yielding zero new snapshots were checked on all six real captures.
The archive retains capture time, source, original titles, land-use facts and
available planning rows. `not_provided` does not mean no planning; archived
results must display their capture date rather than claim to be current GIS.

**Limits:** this is a six-parcel collection pilot, not complete coverage of
either former province and not yet connected to RadarBDS's public parcel UI.
Observed viewport boundaries were PNG tiles, while true polygons arrived per
click. No bulk vector/list endpoint was verified. The new administrative-area
selector requested VIP; that locked selector was not used. The public historic
Bình Phước map page and its normal point clicks remained usable. No VIP feature,
login challenge or paid-data restriction was bypassed.

Fresh sanitized captures, the import summary and a planning screenshot are under
`.local/dongnai-corners-research/`. The archive and raw data stay out of Git.
No production deploy or change to existing official GIS parcel lookup is part
of this pilot.
