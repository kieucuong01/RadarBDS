# General planning coverage and native tile transport

Verified 2026-10-28. This supersedes the older Bình Dương-only general-plan
display window. The native `urban_general` layer now shares the TP.HCM expanded
window with partition and detailed planning, including Côn Đảo. A display window
is not a claim that every point has a current or legally effective plan.

## Sources and coverage checks

Both public services use the verified 256px XYZ Web Mercator grid:

- [Primary general planning](https://api-gisxaydung.tphcm.gov.vn/arcm/rest/services/HCM/SuDungDat_QHC_HCM/MapServer)
- [Supplementary general planning](https://api-gisxaydung.tphcm.gov.vn/arcm/rest/services/HCM/QHXD_SDD_2025_QHCDT/MapServer)

The primary is drawn above the supplement, exactly as in the existing gateway.
Neither partition nor land-use-2030 pixels are substituted for general planning.
Scale and legal currency remain unverified; do not label all these sources
uniformly 1/10,000.

At zoom 15, valid PNG tiles from both services were checked at 20 sample points:
Thủ Dầu Một, Bến Cát, Dĩ An, Thuận An, Quận 1, Quận 7, Thủ Đức, Thủ Thiêm,
Củ Chi, Hóc Môn, Nhà Bè, Cần Giờ, Vũng Tàu, Bà Rịa, Phú Mỹ, Long Điền,
Đất Đỏ, Châu Đức, Xuyên Mộc and Côn Sơn. The supplement had nontransparent
content at all 20; coverage of each sampled tile was 100% for the mainland
samples except Vũng Tàu (99.93%), and 97.24% for Côn Sơn. The primary was
transparent in some southern/suburban HCM samples, making the supplement
necessary. These samples do not prove continuous or administrative completeness.
Local raw observations are in ignored `.local/planning-expansion/general-speed/`.

## Loading and caching

`planning_native_tiles.js` composes the two public source images into one canvas
per visible tile. Leaflet applies the chosen opacity once to that composite.
This avoids routing every pan/zoom image through the application and lets the
browser reuse the sources' observed `Cache-Control: max-age=86400` responses.
Source templates are allowlisted by exact host, service family and XYZ path.
No canvas pixel reading, export, credentials or CORS workaround is used.

Loading remains viewport-only: settled zoom/pan updates, one tile buffer and
no whole-city preload. A shared queue allows four active tiles across all three
official layers (at most eight source images); timeout starts when a queued tile
actually begins. Tile removal cancels queued and detached image requests and ignores
late callbacks. Direct source errors, wrong dimensions or an 8-second timeout
use the existing same-origin gateway; its browser fallback has a 15-second
timeout so loading cannot remain pending indefinitely. Sources can still be
slow or unavailable, and the UI retains its existing error/source notices.

The fallback disk cache grows from 128 to 512 entries with an additional 64 MB
PNG-plus-audit-file cap. Cache reads do not renew the existing 24-hour freshness
limit. Shared-process locking, four-request upstream gate, metadata/grid
verification and `/api/planning/` private/no-store headers are unchanged.
PDF/image alternatives, source credits and listing-filter behavior are retained.

## Performance evidence and verification

A controlled four-concurrent-request comparison used the same 12 tile cells
(three official themes, four cells each). The application gateway took 24.06 s
wall time with 11 successful PNG responses and one connection error. Direct
access fetched all 24 constituent source images successfully in 5.30 s. This is
transport evidence for that run, not a production latency percentile or capacity
guarantee. An earlier 12-tile gateway run took 21.14 s initially and 10.83 s
repeated despite all files being present in the VPS disk cache.

Browser verification confirms actual canvas composition at 35% opacity without
console errors. Runtime tests cover source completion order, gateway fallback,
wrong image size, both timeouts, unload cancellation and stale callbacks.
Python checks cover expanded general bounds, source identity and cache byte and
entry caps. Public cache privacy regression checks remain part of validation.
