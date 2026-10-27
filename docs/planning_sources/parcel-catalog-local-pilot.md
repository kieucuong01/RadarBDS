# Parcel catalogue local pilot

**2026-10-28 expansion:** the local index now covers all 91 historic units in nine
districts. The original 22-ward capture below is retained as its earlier checkpoint.
Current totals, native planning tiles and source limits are documented in
[Bình Dương native GIS](binh-duong-native-gis.md).

Extends the Tân An experiment to all 14 historic wards of Thủ Dầu Một and all
8 historic wards of Bến Cát. Parcel functionality remains opt-in on the loopback
runner at port 5055; normal Flask and production do not install its routes.

## Capture and spatial index

```
python -X utf8 scripts/build_planning_parcels.py
python -X utf8 scripts/run_planning_pilot.py
```

The builder resumes verified, unchanged-count snapshots. Use `--refresh` for a
fresh capture or `--index-only` to rebuild the index from completed captures.
Restart the local runner after replacing the index. Files remain ignored under
`.local/planning-parcels/`; no GIS captures, SQLite files or credentials belong in Git.

Ward/district codes in `config/planning_parcels.py` were verified against the
official GIS public administrative catalogue, including district 718 and 721.
Names describe historic administrative units; no current-name inference is made.

On 2026-10-27 the native ArcGIS query returned service errors, while the official
app's `/rest/thua-dat/query` adapter worked. That adapter silently caps identifiers
and ignores offset/order pagination. The capture therefore splits disjoint
`OBJECTID < pivot` / `OBJECTID >= pivot` predicates until every segment returns
exactly its independently checked count. Segment IDs must be unique, disjoint,
positive integers and add up to the original ward count. Geometry batches use
explicit `OBJECTID IN (...)` predicates and validate exact returned membership,
ward, district and CRS. The final source count must still agree.

Only OBJECTID, sheet, parcel, source area and administrative codes are requested.
There are no owner, address, phone or contact fields. The official public guest
handshake stays in process memory. Existing endpoint allowlists, bounded responses,
timeouts, planning lookup cache and concurrency limits remain in place.

Source vertices are retained; polygons are not repaired, relocated or simplified.
Invalid rings, self-intersections, missing geometry and coordinates outside the
supported Bình Dương window are excluded with per-ID reasons. Accepted/excluded
counts, capture timestamp, ID-set hash and file hash accompany every ward capture.
Overlapping source IDs remain distinct; this experiment cannot infer cadastral
revisions or legal supersession. Source geometry can change between captures.

Once every ward passes, the builder creates a read-only SQLite RTree **spatial
asset index**, then atomically replaces the previous complete index. This is not
an application/canonical database change. Startup reads only 22 metadata records;
viewport queries read matching feature rows rather than all 322,890 polygons.
Temporary build failure preserves the previous complete index.

## Coverage on 2026-10-27

| City | Ward | Accepted | Excluded |
|---|---|---:|---:|
| Thủ Dầu Một | Hiệp Thành | 15,021 | 5 |
| Thủ Dầu Một | Phú Lợi | 10,966 | 22 |
| Thủ Dầu Một | Phú Cường | 7,644 | 4 |
| Thủ Dầu Một | Phú Hòa | 15,615 | 9 |
| Thủ Dầu Một | Phú Thọ | 13,979 | 10 |
| Thủ Dầu Một | Chánh Nghĩa | 12,212 | 7 |
| Thủ Dầu Một | Định Hòa | 11,640 | 3 |
| Thủ Dầu Một | Hòa Phú | 9,283 | 3 |
| Thủ Dầu Một | Phú Mỹ | 12,815 | 1 |
| Thủ Dầu Một | Phú Tân | 11,382 | 2 |
| Thủ Dầu Một | Tân An | 16,107 | 81 |
| Thủ Dầu Một | Hiệp An | 8,934 | 4 |
| Thủ Dầu Một | Tương Bình Hiệp | 8,622 | 18 |
| Thủ Dầu Một | Chánh Mỹ | 9,453 | 105 |
| Bến Cát | Mỹ Phước | 19,623 | 3 |
| Bến Cát | Chánh Phú Hòa | 17,161 | 0 |
| Bến Cát | An Điền | 15,381 | 4 |
| Bến Cát | An Tây | 16,278 | 0 |
| Bến Cát | Thới Hòa | 41,524 | 1 |
| Bến Cát | Hòa Lợi | 13,342 | 2 |
| Bến Cát | Tân Định | 21,055 | 0 |
| Bến Cát | Phú An | 14,853 | 0 |
| **Total** | **22 wards** | **322,890** | **284** |

## Interaction and source limits

No ward checkboxes are required. At zoom 17+, the parcel layer queries the visible
bbox with cancellation and newest-response checks. It renders at most 1,500
matching parcels and asks users to zoom further if capped. Existing geometry stays
visible during the next request, then swaps in one update. Below zoom 17, fine
boundaries are removed while planning overlays and listings keep loading by view.

“Xem thửa mẫu” fetches one sample from the nearest ward and frames it; it does not
download all geometry or filter out other wards. Existing navigation centres help
choose the sample without changing any source geometry. The retained Tân An sample
is OBJECTID 33013. Selection shows the selected record's own ward/city and checks
ID/area membership before querying `/thong-tin-quy-hoach/dnm`.

Both returned planning families, source decisions, intersection areas and raw
indicators retain the original pilot's display rules. Empty/error responses do
not mean “no planning”. The live response may differ from the raster edition.
See [Tân An source limits](tan-an-parcel-pilot.md) and
[Maps viewport loading](maps-viewport-loading.md).

## Verification

- 22/22 ward captures reconcile accepted + excluded = source count; every geometry
  batch has exact source IDs and the final RTree has unique global parcel IDs.
- Actual local HTTP viewport and sample endpoints return the right ward's sample
  for 22/22 wards. Representative viewport + sample requests took 17–64 ms combined
  on this machine; the largest viewport response in those samples was 241,557 bytes.
  This is a local sample, not a production concurrency or end-to-end browser budget.
- Live GIS lookups for all 22 samples returned both partition and general planning;
  source request times were 317–805 ms in that run. These results confirm source
  availability for the samples, not every parcel's coverage or legal effect.
- 147 focused tests passed. Two standalone browser tests were deselected; their
  affected mobile layout was inspected through the in-app browser at 390 × 844,
  plus a mobile-to-desktop transition at 1280 × 900. The canvas now keeps a relative
  containing block on desktop so layers cannot spill into the listing rail.
- Actual polygon clicks in Tân An and Mỹ Phước update the selected sheet/parcel
  and fetch the corresponding planning details. Mobile selection stays above the
  bottom info panel without horizontal overflow. The browser console was checked
  separately from the automated suite.

## Map controls update — 2026-10-28

The map now groups **Khu vực / Tờ-thửa / Lớp bản đồ** in one toolbar. Area selection
frames the map through the existing initial-bounds endpoint; it does not mutate
dashboard filters or prevent viewport discovery. Independent partition/general
buttons and a parcel-boundary button sit in the quick dock. The opacity control
keeps per-layer values, changes existing Leaflet image opacity without rebuilding
images, and stays available alongside parcel information. On narrow layouts it
becomes a horizontal control above the selected parcel.

The spatial asset builder adds the `parcel_lookup` expression index on area,
trimmed source sheet and trimmed source parcel. `GET /local-planning/parcels/search.json`
requires all three bounded values and returns at most 20 matches with an explicit
count/truncation flag. It matches exact source strings: e.g. Tân An's retained
sample is sheet `1713`, parcel `4686`; those source values are not reinterpreted.
Duplicate pairs produce a choice of results, not an automatic first-record pick.
The original single-file fallback still supports map clicks; the search control
appears only for the indexed catalogue.

Search results frame and highlight a verified parcel, then use the existing GIS
lookup. Closing details or manually moving the map cancels stale work. The compact
card shows source area, historic location and intersection rows; indicators and
decision metadata expand on demand. Chips use a neutral interface colour because
the lookup supplies no authoritative zoning colour. No land-use classifications,
percentages, build approvals, new administrative names or source colours are inferred.

Fresh verification: 148 focused tests passed, with two standalone browser tests
deselected in favour of in-app browser checks. Actual area navigation, exact
search, polygon clicks and opacity input were exercised; layouts were inspected
at 390 × 844, 900 × 720 and 1280 × 900. The two real local search examples took
about 12–16 ms and returned less than 1 KB each; this excludes the subsequent
live GIS planning lookup. Existing viewport loading and GIS/PDF choices remain.
