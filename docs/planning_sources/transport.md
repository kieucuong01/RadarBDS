# Transport: metro plus official GIS corridors and ring roads

Checked 2026-10-29. Public Metro source:
https://guland.vn/soi-quy-hoach/tp-ho-chi-minh

The Metro control advertises
`https://s3.hn-1.cloud.cmctelecom.vn/guland7/metro-hcm-3/{z}/{x}/{y}.png`
with native maximum 19. Actual 256 px images verified native 12, 17, 18, 19;
9–11 unavailable. Native 12 is downsampled for overview. The old yellow
`hcm-road-2` raster is removed from the catalogue and client URL allowlist.
Metro remains a reference raster for old HCM; individual approval or progress
is not inferred from colours.

Official source: https://gisxaydung.tphcm.gov.vn/tracuuttqh

Its visible Giao thông hiện trạng group contains Đường hành lang, Đường Vành đai
and Đường hiện trạng trong đô thị. The public guest handshake in PublicGIS
gives read access to the following verified services (no browser token copied):

- `/arcgis/rest/services/HCM/GiaoThongHienTrang/FeatureServer/1`: 11 corridor lines.
- `/arcgis/rest/services/HCM/GiaoThongHienTrang/FeatureServer/2`: 16 ring-road/highway
  features, including Vành đai 3/4, Bến Lức–Long Thành, Biên Hòa–Vũng Tàu, QL51.
- `/arcgis/rest/services/HCM/HTKT_QHCTP/FeatureServer/14`: city-plan road network.
  A bounded keyset scan of all 3,509 names identified three VĐ2 features under
  the source's spelling “Vành đài 2-Bao gồm: ...”, plus 43 constituent corridor
  sections for VĐ1. Only these 46 features are captured from this network.

The urban existing-road layer 3 has 1,250 features and no separately named
Vành đai 1/2. Do not publish its entire street mesh as the requested main roads.
The official HCM press-centre description links the VĐ1 corridor to Phạm Văn
Đồng, Bạch Đằng/Hồng Hà/Trường Sơn/Hoàng Văn Thụ, Bảy Hiền–Thoại Ngọc Hầu–
Hương Lộ 2 and the inner-ring section toward Nguyễn Văn Linh:
https://ttbc-hcm.gov.vn/xe-khong-dat-chuan-vao-vung-han-che-khi-thai-tp-hcm-co-the-nhan-phat-den-400-000-dong-1020119.html

**VĐ1 is a curated collection of corresponding named GIS sections, not a
verified complete or closed alignment.** Some source features describe broad
combined corridors (including Hồng Lạc); preserve their full original names
and status. Do not claim an exact, continuous VĐ1 alignment from this set.
VĐ2 is likewise shown only where the GIS names it; do not bridge missing sections.
No route gaps are connected, and no new vertices or straight-line routes are
invented. `source_status` retains Hiện trạng / Quy hoạch mở rộng / Quy hoạch mở mới.
The GIS service name alone is not a construction-progress assertion.

Re-capture intentionally with:
`python -m scripts.capture_planning_transport`

The curated 73-feature, ~321 KB public road asset is
`static/data/planning_transport_roads.geojson`. It contains only road geometry,
source service/layer/object IDs, names and source status, with WGS84 coordinates
requested from GIS. It contains no parcel/owner/contact fields or credentials.
Existing coordinates remain unchanged. Roads use a viewport-filtered Leaflet
vector layer, requested only when transport is enabled and reused from memory
after loading. Invalid data and late responses after hiding fail closed.
Source reads happen offline during capture, never on a public map request.

The single QH Giao thông toggle combines GIS vectors with Metro at 100% initially.
Subsequent toggles retain the chosen visibility. Both stay above ordinary
planning rasters and below parcels/markers, with no pointer interception.
Ordinary Maps keeps QH SDĐ 2030 at 65% on satellite. Direct entry:
`/?tab=all&map=1&planning=transport&region=hcm-legacy`.
