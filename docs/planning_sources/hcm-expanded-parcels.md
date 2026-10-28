# On-demand parcels across expanded HCM

Source audited on 2026-10-28: [public construction GIS](https://gisxaydung.tphcm.gov.vn/tracuuttqh).
This extends cadastral parcels, separately from the partition raster rollout.

## Available source and observed gaps

The public `HCM/RanhThuaDat/MapServer/0` service has assigned parcel records in
all 22 historic HCM districts (including Thủ Đức), Bà Rịa district 748, and the
nine historic Bình Dương districts. Grouped counts returned no assigned records
for the other historic Bà Rịa–Vũng Tàu districts. The alternate `HCM/ThuaDat`
service did not add parcels at the tested Vũng Tàu point. These observations do
not establish that land has no parcel or no planning.

There are 422 distinct historical ward references in the public administrative
response: 91 Bình Dương, 320 HCM and 11 Bà Rịa. They are navigation windows and
search identifiers, not proof that every location in each window has parcels.
`scripts/build_expanded_parcel_areas.py` reproducibly transforms the captured
public WKT administrative geometry to small WGS84 bounding windows. It never
publishes administrative geometry as cadastral parcel geometry. The immutable
91-ward Bình Dương index and its release manifest are unchanged.

Read-only integration checks (viewport ±0.001 degrees):

| Center | Accepted source parcels | Invalid source polygons excluded |
|---|---:|---:|
| Quận 1, 10.7758 / 106.7009 | 90 | 0 |
| Thủ Đức, 10.85 / 106.76 | 479 | 18 |
| Củ Chi, 10.972 / 106.493 | 58 | 0 |
| Bà Rịa, 10.496 / 107.168 | 454 | 1 |
| Vũng Tàu, 10.353 / 107.084 | 0 | 0 |

Phú Mỹ, Xuyên Mộc and Côn Sơn were also checked: the public service returned
zero records at the sample points. Full coverage of those regions is not
claimed. The former BRVT GIS URL and Guland public map could not be retrieved
by the web tool during this audit; no licensed or authenticated data was copied.

Planning lookup succeeded for Quận 1 object 2821079 (two plans) and Bà Rịa
object 1173234 (one plan). Exact sheet/parcel queries returned each object in
its source ward: 26740 / 40 / 74 and 26551 / 19 / 100 respectively.

## Runtime bounds, provenance and privacy

- Keep the fast read-only Bình Dương SQLite asset. Query expanded parcels only
  on demand, at zoom 17+, in a geographic viewport no wider/taller than 0.05°.
- Native ArcGIS uses an envelope and WGS84 output, capped at 1,000 source rows.
  Its intermittent 400/non-JSON responses fall back to the same public source's
  `/rest/thua-dat/query` adapter, with identical validation. Native retries are
  paused for 60 seconds after failure. Never infer absence from a service error.
- Only request OBJECTID, SoTo, SoThua, DienTich, MaPhuongXa, MaQuanHuyen and
  geometry. Owner names, identity numbers, addresses and contacts are neither
  requested nor passed into the cache or HTTP response.
- Verify source coordinate system, object IDs, administrative membership,
  exact search fields, finite closed rings and polygon validity. Exclude invalid
  source polygons individually without repair or invented vertices. Filter
  projected-envelope edge extras by actual geographic intersection; fail if
  the source returns only outside-view polygons.
- One upstream query at a time per worker; excess concurrent misses return 503
  without a queue. Cache sanitized encoded JSON only, for five minutes, at most
  32 entries and 8 MB per worker. Browser collections are capped at 1,500 total
  parcels including the local catalogue; dense views ask the user to zoom in.
- Existing per-IP planning limits and private/no-store policy remain active.
  No DB migration or multi-GB parcel snapshot is needed. Roll back to the
  previous commit to restore the former 91-ward-only parcel behavior.

The UI keeps faint unselected borders and listing markers above parcel paths.
Search and Khu vực use historic names explicitly; no unverified new-ward
crosswalk is invented. Source gaps and service errors have distinct messages.
