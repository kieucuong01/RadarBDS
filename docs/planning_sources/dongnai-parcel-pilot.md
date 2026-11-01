# Dong Nai public cadastral pilot

Verified 2026-10-31. Scope: former Binh Phuoc within new Dong Nai. **Former
Dong Nai cadastre has not been integrated.** This is progress toward the national
parcel goal, not nationwide or province-wide completeness certification.

## Public source

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
