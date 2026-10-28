# Detailed planning GIS layer

Verified on 2026-10-28 against the public construction GIS:
https://gisxaydung.tphcm.gov.vn/tracuuttqh.

The primary service is `HCM/SuDungDat_QHCT_HCM/MapServer`, whose layers are
`QHCT` and `Quy hoạch chi tiết - Sử dụng đất`. The supplement is
`HCM/QHXD_SDD_2025_QHCT/MapServer`, with a `Quy hoạch chi tiết - Sử dụng đất`
layer. These are distinct from the partition and urban-general collections.
No blanket 1/500 scale or current legal effect is asserted.

Both public `/arcm/rest/services/` metadata responses were checked with the
existing XYZ grid validator: 256px cells, Web Mercator origin and native levels
8–23. The small service-identity/grid captures ship in
`config/planning_gis_metadata/detailed*.json`. Runtime checks their service name,
exact source URL and grid. The four old metadata files and 965 MB read-only
parcel asset remain untouched. No asset upload or DB migration is required.

The gateway composites the two detailed services on the same native grid,
keeping primary pixels above the supplement, using the existing concurrency,
single-flight, shared disk limit, private headers and request budgets. It never
uses partition or general-plan pixels to fill a missing detailed plan.

## Bounded source samples

At zoom 15, all ten sample requests returned valid 256px PNGs. Nontransparent
tile areas were: Tân An 1.869%, Mỹ Phước 8.740%, Thới Hòa 52.061%, Hòa Phú
52.287%. The Quận 1, Thủ Thiêm, Thủ Đức, Vũng Tàu, Bà Rịa and Côn Sơn sample
tiles were transparent. These samples establish neither whole-region coverage
nor absence of a detailed plan at other locations or scales.

`detailed` uses the expanded HCM display window, independently of the other
themes. The new Chi tiết toggle starts off, at 35% when enabled. Its opacity,
source selection and tile lifecycle use the existing controls. Mobile controls
wrap to keep all map-type buttons reachable.

## Source-label cleanup

The requested branding cleanup removes the commercial provider name from map
controls, inspection labels, notices and land-use attribution text. The 2030
source remains internally `guland`/`guland_reference`, with its original URLs
and a generic “Nguồn dữ liệu QH 2030” link. It is never relabeled official GIS.
Source pixels are not altered, and provenance remains inspectable. Historical
source audit documents retain the actual provider name.

Rollback is the previous code commit. The parcel release is unchanged.
