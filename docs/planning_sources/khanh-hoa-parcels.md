# Ranh thửa GIS Khánh Hòa cũ — tích hợp local 2026-11-02

Phạm vi: phần Khánh Hòa cũ có dữ liệu trong GIS chính thức, không tự bao gồm
Ninh Thuận hay Trường Sa. Đây là provider **live theo vùng nhìn**, không phải
snapshot toàn tỉnh hoặc chứng nhận toàn bộ ranh hiện hành.

## Nguồn và tham chiếu

- Portal: https://gis.khanhhoa.gov.vn/public/8192/
- Service: https://gis.khanhhoa.gov.vn/arcgis/rest/services/Base/DiaChinh/MapServer
- Layer 8: `ThuaDat_region`, Polygon, `Map,Query,Data`, maxRecordCount 1000.
- Query: `/arcgis/rest/services/Base/DiaChinh/MapServer/8/query`.
- Count kiểm ngày 2026-11-02: **971792**. Không đồng nghĩa số polygon hợp lệ.
- Mẫu geometry được source project về `outSR=4326`, không làm tròn/simplify/sửa
  ring gốc. WKT nguồn mang tên VN2000KhanhHoaMui3, central meridian 108.25,
  nhưng datum trong WKT khai GCS WGS1984. Giữ đúng response source; không đoán
  thêm phép hiệu chỉnh datum hoặc bảo đảm độ chính xác khảo sát độc lập.

`scripts/capture_khanh_hoa_parcel_areas.py` lấy distinct các trường mã/tên xã và
huyện, đối chiếu mã/tên huyện với selector công khai của chính portal.
139 tổ hợp nguồn → **134 area references**, loại 5 tổ hợp null hoặc tên huyện
mâu thuẫn mã. Đây là 5 tổ hợp metadata, không phải chỉ 5 thửa bị loại.
`config/planning_khanh_hoa_parcel_areas.json` giữ các tổ hợp loại và lý do thể
hiện qua giá trị nguồn, không suy đoán alias. Các thửa không khớp mã/tên đã
xác minh được tính vào `excluded_count`, không gán sang xã khác.

Bounds/center của từng xã dùng **window điều hướng huyện cũ** trong registry
2030 (`bounds_kind=historic_district_navigation_window`). Đó không phải polygon
xã hay mặt nạ ranh địa chính. Request luôn bị giới hạn bởi bbox hiện tại.
Tên xã và tên huyện nguồn được giữ để kiểm membership; city label có tiền tố
Thành phố/Thị xã/Huyện theo selector chính thức. Không tự suy loại Phường/Xã
từ tên không có tiền tố.

## Adapter và dữ liệu công khai

`services/planning_khanh_hoa_parcels.py` dùng `LiveParcels` với field mapping:

| Thuộc tính chuẩn | Trường nguồn |
| --- | --- |
| source object ID | `OBJECTID` |
| sheet | `So_To` |
| parcel | `So_Thua` |
| source area | `Dien_Tich` |
| ward/district | `MaXa`, `MaHuyen` |
| membership names | `TenPhuong`, `TenHuyen` |

Không request `Chu_SD1/2`, địa chỉ, giấy chứng nhận hay `*`. `MaHuyen` có khoảng
trắng cuối trong dữ liệu nguồn: giữ literal gốc trong filter nhưng chuẩn hóa mã
khi định danh. Public ID = **2,000,000,000,000 + OBJECTID**, area ID =
`kh-{district}-{ward}`. Chỉ ID nguồn được gửi về GIS Khánh Hòa; không dùng ID
Khánh Hòa để gọi HCM/Bình Phước. Namespace HCM và Bình Phước giữ nguyên.

Các endpoint đã có `/api/planning/parcels/*` được dùng lại. Renderer thêm lựa
chọn “Khánh Hòa (cũ)” trong Tờ/thửa; basic popup dùng đúng nguồn GIS Khánh Hòa.
Tìm theo WGS84, sheet/parcel, lấy thửa mẫu và xem ranh gần đều qua adapter.
**Chưa thêm hệ chiếu VN-2000 TM-3 108°15′ riêng cho Khánh Hòa**; công cụ WGS84
và các hệ chiếu được allowlist khác vẫn có giới hạn cũ. Không nói VN-2000 theo
hồ sơ Khánh Hòa đã được xác minh từ việc ArcGIS trả WGS84.

Chi tiết quy hoạch Khánh Hòa chưa tích hợp. Khi người dùng yêu cầu chi tiết,
route trả `planning_available=false`, `plans=[]`, đúng source/parcel và thời
điểm; UI giải thích có ranh nhưng chưa có tra giao quy hoạch. Không gọi HCM và
không dùng mảng rỗng để kết luận không có quy hoạch.

## Hiệu năng, cache và lỗi

- Zoom tối thiểu 17, fixed cells/Canvas/viewport/cancellation như các nguồn cũ.
- Một truy vấn nguồn/provider mỗi worker, không xếp hàng vô hạn; source cache
  tối đa 32 entries / 8 MB / 5 phút; timeout (4,12), cap 10 MB, không redirect.
- Tối đa 1000 bản ghi/query theo nguồn; `truncated` yêu cầu thu hẹp vùng xem,
  không khẳng định đã hiển thị mọi thửa trong ô dày đặc.
- Shared cell cache/lease và original geometry cache dùng cơ chế sẵn có. Chỉ
  display được simplify; đo cạnh/diện tích dùng original cache.
- `RegionalParcels.revision` tham gia cell release hash cùng snapshot digest,
  tránh ô rỗng cũ bị giữ sau khi thêm tỉnh. Snapshot HCM/Bình Phước không phải
  chờ GIS Khánh Hòa; route theo actual reference window, không theo bbox chồng
  lấn giữa các loại quy hoạch.
- Source status/error, CRS sai, source bỏ qua filter, duplicate ID, geometry
  sai và unknown membership giữ guard có sẵn. Lỗi nguồn không biến thành “không
  có thửa”. Không fallback sang Guland.

## Bằng chứng thực tế và kiểm tra

Mẫu thật thành công ở đủ 8 huyện/thị/thành phố, mỗi nơi có sample, exact-search,
point-covered-by-original và viewport intersection:

| District | Địa bàn | Source OBJECTID | Tờ / thửa |
| --- | --- | --- | --- |
| 568 | Nha Trang | 942759 | 1 / 1 |
| 569 | Cam Ranh | 169227 | 1 / 3 |
| 570 | Cam Lâm | 57609 | 45 / 69 |
| 571 | Vạn Ninh | 756130 | 57 / 40 |
| 572 | Ninh Hòa | 402819 | 73 / 21 |
| 573 | Khánh Vĩnh | 784746 | 37 / 256 |
| 574 | Diên Khánh | 301891 | 1 / 6 |
| 575 | Khánh Sơn | 823492 | 1 / 1 |

HTTP localhost 5055 cũng kiểm đủ 8 exact-search; một live cell Nha Trang có 91
features, original + coordinate lookup HTTP 200; detailed response báo rõ chưa
hỗ trợ. Các lần exact-search HTTP riêng lẻ khoảng 0.53–1.00 giây trong mẫu đó;
không phải phân vị hoặc bằng chứng tải đồng thời. Chẩn đoán:
`.local/priority-gis-20261102/kh-live-adapter-proof.json`, `kh-http-proof.json`.

115 kiểm tra Python đạt, 3 kiểm tra render/browser được bỏ chọn; runtime JS chọn
tỉnh/đổi xã/hủy request đạt. Chrome trong phiên báo local browser use disabled,
nên chưa xác minh rendered desktop/mobile và chưa deploy production.

Khi release cần đúng code + file config, restart, recheck config/cell/original/
search/source link và bản trình duyệt. Không cần chuyển kho 971792 thửa vì
adapter này là live, không phải bulk download. Muốn rollback provider thì quay
lại commit trước cùng JS/template version; giữ nguyên snapshot HCM/Bình Phước.
