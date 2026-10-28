# Partition planning across the expanded Hồ Chí Minh City

The partition tile family now uses a display window covering the former HCM,
Bình Dương and Bà Rịa–Vũng Tàu areas, including Côn Đảo. The browser and native
proxy share that scope. It remains off by default and starts at 35% opacity.
Only visible native XYZ tiles and their small buffer are requested. Existing
source grid validation, concurrency, shared cache cap, private headers and public
rate budgets remain active; no new large runtime asset is required.

Sources are the same official `SuDungDat_QHPK_HCM_V2` primary and
`QHXD_SDD_2025_QHPK_V3` supplement. The source calls this family partition and
commune general planning; it includes `QHNTM` records and is not uniformly 1/2000.
Urban general planning, the parcel index and listing service retain their existing
Bình Dương scope. Drawings/PDFs remain available in the source selector.

The **Khu vực** tool adds direct jumps to the whole new city, former HCM,
former Bình Dương, mainland Bà Rịa–Vũng Tàu, and Côn Đảo. These windows are
navigation aids, not legal administrative boundary polygons. Listing filters are
not modified by these camera movements.

## Source audit — 2026-10-28

Official application: <https://gisxaydung.tphcm.gov.vn/tracuuttqh>.
Official publication describing the integrated three-region portal:
<https://ttbc-hcm.gov.vn/tp-hcm-van-hanh-thu-nghiem-cong-thong-tin-cong-khai-du-lieu-quy-hoach-tren-nen-tang-gis-1021375.html>.

The public guest handshake was used only for read-only ArcGIS JSON queries;
tokens stayed in memory. JSON layer metadata/query uses `/arcgis/rest/services/`;
tiles/root grid metadata use `/arcm/rest/services/`. The latter can return an empty
HTML response for layer/query paths; that is not evidence that GIS is offline.

There were 38 point/tile samples: 31 points intersected source objects and 34
native tiles contained at least one nontransparent pixel. No transport or image
validation errors occurred. These are samples, **not** complete area coverage.
A tile can have a few pixels while its sample point is outside any source plan.
Neither an empty point query nor a transparent tile establishes legal plan status.

The source's stored `fullExtent` and district-code statistics are not sufficient
to infer coverage: the partition extent omits Côn Đảo despite source objects and
native imagery at Côn Sơn, and contains a distant eastward outlier. Explicit
bounded display windows are used instead of trusting that extent. Côn Sơn has
partition imagery; Cỏ Ống and the Bến Đầm sample do not establish full coverage.
Several mainland BRVT samples and the Tân Bình sample are also blank at the exact
point. Do not fill them with urban general planning or label every location covered.

| Sample | Main zones | Main plans | Supplement | Native tile pixels with alpha > 0 |
|---|---:|---:|---:|---:|
| Quận 1 | 1 | 1 | 1 | 99.915% |
| Quận 3 | 1 | 1 | 1 | 100.000% |
| Quận 4 | 0 | 1 | 1 | 100.000% |
| Quận 5 | 0 | 1 | 1 | 100.000% |
| Quận 6 | 0 | 1 | 1 | 99.635% |
| Quận 7 | 1 | 1 | 1 | 96.881% |
| Quận 8 | 1 | 1 | 1 | 100.000% |
| Quận 10 | 1 | 1 | 1 | 100.000% |
| Quận 11 | 0 | 1 | 1 | 100.000% |
| Quận 12 | 1 | 1 | 1 | 87.425% |
| Gò Vấp | 1 | 1 | 1 | 94.666% |
| Tân Bình | 0 | 0 | 0 | 37.941% |
| Tân Phú | 1 | 1 | 1 | 100.000% |
| Bình Thạnh | 0 | 1 | 1 | 98.486% |
| Phú Nhuận | 1 | 2 | 2 | 92.647% |
| Bình Tân | 0 | 1 | 1 | 100.000% |
| Thủ Đức - Linh Chiểu | 1 | 1 | 1 | 100.000% |
| Thủ Đức - Thủ Thiêm | 0 | 1 | 1 | 100.000% |
| Thủ Đức - Long Trường | 1 | 1 | 1 | 100.000% |
| Củ Chi | 0 | 1 | 1 | 100.000% |
| Hóc Môn | 1 | 1 | 1 | 100.000% |
| Bình Chánh | 1 | 1 | 1 | 97.864% |
| Nhà Bè | 1 | 1 | 1 | 93.343% |
| Cần Giờ | 1 | 1 | 1 | 96.849% |
| Vũng Tàu | 0 | 0 | 1 | 99.936% |
| Bà Rịa | 0 | 0 | 0 | 0.668% |
| Phú Mỹ | 1 | 1 | 0 | 44.946% |
| Long Điền | 0 | 0 | 0 | 0.000% |
| Đất Đỏ | 1 | 1 | 0 | 48.686% |
| Châu Đức | 0 | 0 | 0 | 0.000% |
| Xuyên Mộc | 0 | 0 | 0 | 0.000% |
| Côn Sơn | 1 | 1 | 0 | 77.090% |
| Cỏ Ống | 0 | 0 | 0 | 0.000% |
| Bến Đầm | 0 | 0 | 0 | 0.009% |
| Thủ Dầu Một | 0 | 1 | 1 | 99.472% |
| Bến Cát | 0 | 1 | 1 | 100.000% |
| Dĩ An | 0 | 1 | 1 | 100.000% |
| Thuận An | 0 | 1 | 1 | 100.000% |

## Validation and activation

Unit/runtime checks cover expanded partition bounds (mainland and islands),
unchanged general-plan bounds, raster-manifest limits, shared grid/zoom rules,
source/opacity toggles, region navigation without a listing bounds lookup, and
preservation of the historic 91-area parcel release. The normal code deployment
is sufficient; do not rebuild/copy the 965 MB parcel index for this change.
