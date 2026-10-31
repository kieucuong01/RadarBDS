# HCM post-2025 administrative overlay

Reference requested by the user:
https://diaocthongthai.com/ban-do-tp-hcm-new-2025/

The public page identifies GIS Sở QH-KT as its boundary source and presents
168 units. Its public iframe uses OpenStreetMap as the base with a separately
processed administrative overlay. The rendering asset uses encrypted payloads;
GeoJSON/KML downloads are paid products, not an open raw-data endpoint. No
payload was decrypted and no paid download was obtained. The user explicitly
approved official GIS as the fallback when the ready-made source cannot be used.
Radar therefore reuses its OSM base and independently captures the same public
GIS source, rather than labelling GIS data as the publisher's processed shapes.

Verified 2026-10-29 via the public guest handshake:
`https://api-gisxaydung.tphcm.gov.vn/arcgis/rest/services/HCM/HanhChinhXa/FeatureServer/0`

The count and full geometry query returned exactly 168 distinct administrative
codes: 113 wards, 54 communes and Đặc khu Côn Đảo. Source names are retained,
including decomposed Unicode in Phường Hòa Hưng. Source geometry is WGS84 and
valid; holes and offshore islands remain. Do not replace these shapes with
old-district parcel/filter boundaries or infer an administrative split.

Capture deliberately with `python -m scripts.capture_administrative_boundaries`.
The curated public assets contain only code, source object ID, name, former
province, bounds, label point, colour and geometry. Full ward geometry keeps
source coordinates. Labels are inside the largest polygon; neighbouring
intersecting polygons get different palette entries. No owner/contact fields
or credentials are captured.

`static/data/admin_hcm_2025/overview.json` is below 1 MB uncompressed. Overview
geometry uses projected simplification with a checked 10 m display-distance
bound, then 7-decimal coordinate rounding. At zoom 13 and above the client
loads individual original ward files only for the current viewport, with at
most four requests in flight. Pending queues follow the newest viewport.
Validated data is cached for toggling/panning; hidden late responses never
restore a layer. Invalid visible detail fails closed. Full detail files total
about 7 MB but are never all requested for a province-level overview. Bump the
version query in the manifest and module when recapturing published assets.

The independent Địa giới toggle starts off on ordinary Maps and at 100% when
selected, with light 17% polygon fills and source names. Its vectors and labels
are below parcel/listing panes and do not intercept clicks. Labels are culled
when crowded. Enabling it selects the existing OSM street base; other planning
entries retain their satellite default. Users can still choose satellite.

Direct entry:
`/?tab=all&map=1&planning=administrative&region=hcm-expanded`

The mainland and Côn Đảo are included in the full-view bounds, so the first
province-wide view is broad. Enabling the layer on an existing filtered map
keeps that viewport. This is a reference display, not a certified boundary
record or a replacement for official administrative documentation.

## Đồng Nai mới (2025)

- 95 xã/phường gồm Đồng Nai và Bình Phước cũ, dữ liệu tham khảo từ [Vietnamese Provinces Database](https://github.com/thanglequoc/vietnamese-provinces-database), giấy phép MIT giữ tại `static/data/admin_dongnai_2025/LICENSE.txt`.
- Chốt bản nguồn `8b78ba5118715e1fa81769286724db79346abf52`; đối chiếu SHA-1 Git blob của 95 file trước khi nhập. Nguồn tổng hợp tham chiếu bản đồ sắp xếp hành chính `sapnhap.bando.com.vn`, không phải hồ sơ địa giới pháp lý được chứng thực.
- Giữ nguyên tọa độ ranh nguồn, chỉ loại thuộc tính không dùng. Tổng quan giản lược tối đa 10 m (Hausdorff), khoảng 1,4 MB JSON; chi tiết 95 đơn vị tổng khoảng 8,5 MB, chỉ tải đơn vị giao vùng nhìn từ zoom 13, tối đa 4 yêu cầu đồng thời. Cache tách riêng HCM/Đồng Nai.
- Trong Khu vực chọn Đồng Nai hoặc Bình Phước (địa danh cũ), bật Địa giới. Một lớp phủ toàn bộ tỉnh mới; bộ lọc nguồn vẫn theo tỉnh cũ như QH SDĐ 2030.
- Tái tạo từ thư mục nguồn đã tải: `python -m scripts.capture_dongnai_administrative --source <folder>`; thư mục cần danh sách GitHub `github-wards-dir.json`, commit `github-commit.json`, 95 GeoJSON gốc và `SOURCE-LICENSE.txt`. Không tải dữ liệu từ trình duyệt người dùng.

## Đóng bảng điều khiển

`pointerdown` capture trên document đóng Khu vực, Tờ/thửa, Lớp bản đồ khi chạm/click ra ngoài; thao tác vào trường nhập bên trong giữ bảng mở. Bảng Bộ lọc chỉ đóng khi đang mở dạng drawer trên Maps và click ngoài sidebar/nút mở; giữ cơ chế cập nhật kích thước Leaflet sau khi đóng. Listener popover được tháo khi hủy overlay; drawer dùng listener chung một lần và kiểm tra Maps đang mở.
