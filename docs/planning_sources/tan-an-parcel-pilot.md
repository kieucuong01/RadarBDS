# Tân An parcel pilot

Local experiment requested after the GIS overlay release. Production remains unchanged.
The current runner prefers the [22-ward spatial catalogue](parcel-catalog-local-pilot.md)
when available and retains this single-ward snapshot as a fallback. The source and
measurements below record the original Tân An experiment.
Run `python -X utf8 scripts/build_tan_an_parcels.py` to capture boundaries, then
`python -X utf8 scripts/run_planning_pilot.py` on loopback port 5055.
No new dependencies, DB migrations, private accounts, owner data, or committed raster/vector captures.

## Source and scope

- Official app: https://gisxaydung.tphcm.gov.vn/tracuuttqh
- Native parcel query: https://api-gisxaydung.tphcm.gov.vn/arcgis/rest/services/HCM/RanhThuaDat/MapServer/0/query
- Lookup used by that app: `POST https://api-gisxaydung.tphcm.gov.vn/thong-tin-quy-hoach/dnm` with a verified parcel OBJECTID.
- Historic Tân An ward code 25765, district Thủ Dầu Một 718. The current administrative name is not inferred.
- Use the official app's anonymous Socket.IO guest-token flow. Tokens remain only in process memory, are never printed or stored in captures, and expire/refresh normally. No account login or copied browser credential is used.
- Source count: 16,188 records. The native query returns all identifiers; the generic REST query silently caps identifiers and ignores offset/order fields. Fetch native IDs in explicit batches of 500 and verify every ID, ward code, district code, CRS and count.
- Snapshot: 16,107 valid polygons. Excluded 71 records with invalid rings/out-of-area coordinates and 10 self-intersecting polygons. Some source rows tagged Tân An transform near 102.53 E, 3.16 N. Do not move or repair them. Exclusions are recorded in ignored `.local/planning-parcels-tan-an/excluded.json` and their count is displayed in the pilot.
- Ring nesting retains disconnected polygons, holes and islands without simplifying vertices. Records with distinct source IDs are retained; this pilot does not decide which source editions supersede overlapping records.

## Interaction

Maps adds a separate “Ranh thửa · Tân An” panel. Show boundaries at zoom 17+ only,
query the local spatial index for the current viewport, and cap each view at 1,500
features. A truncated view explicitly asks the user to zoom further. Both “Đến Tân An”
and “Xem thửa mẫu” are available. Selecting a polygon highlights its source geometry
and requests planning details for exactly that snapshot ID. Ignore stale responses
when selections or map views change, cancel requests on toggle/close/unload.

The info panel shows raw source sheet/parcel strings, source parcel area, each
returned plan, decisions/dates/scales, land-use functions and intersection areas.
Keep build indicators verbatim, including unusual strings such as `0-05`; do not
reinterpret them as approval limits. Missing indicators stay “Chưa có dữ liệu”.
Source parcel area and the GIS intersection area are separate; percentages and
legal conclusions are not inferred. An empty/failed lookup cannot mean “no planning”.
The live lookup may reflect a different source revision from the raster overlay.

Example verified against the source app and API: OBJECTID 33013, source sheet `1713`,
parcel `4686`, source area 1,711 m²; QHPK Tân An 1271/QĐ-UBND dated 01/11/2012,
GIS intersection about 1,748.99 m². QHC response also includes road and residential
parts, with decision 106/QĐ-UBND dated 18/02/2024. These are source-returned labels,
not independently verified legal-document identities or current legal effect.

## Boundaries and verification

Parcel routes are installed only by the opt-in local runner. They inherit its
loopback/Host/proxy-header guards and `private, no-store` / `noindex` policy. Normal
Flask/production HTML does not load the parcel scripts. Parcel IDs must exist in
the accepted snapshot; clients cannot choose remote URLs or arbitrary SQL. Fixed
upstream endpoints, bounded response sizes, timeouts, two in-flight lookup slots,
a five-minute/128-entry cache and field allowlists constrain the experiment.
No owner, phone, address or personal fields are requested or returned.

Focused automated coverage: polygon holes/islands, response field allowlists,
endpoint allowlist, bbox bounds, loopback/Host isolation, wrong-ID rejection,
cache reuse and upstream failure. Browser QA additionally checks actual polygon
clicks, zoom/toggle/source interactions and mobile layout.

The listing-summary response preserves a view changed after its request began,
so a late initial listing response cannot reset a parcel selection to city zoom.
On mobile, selection fits above a bottom info panel; the deal sheet is temporarily
hidden while that panel is open. Failed live lookups expose an explicit retry.
