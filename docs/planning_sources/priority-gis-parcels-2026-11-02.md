# Rà GIS ranh thửa: địa bàn ưu tiên 3–10

Ngày kiểm: **2026-11-02**, theo địa bàn **cũ**. Yêu cầu người dùng: hoàn thiện
ranh ở nơi có GIS hoạt động; nếu cần tra Guland thì **ghi lại, làm sau**.
Đợt này không thu thập thửa mới từ Guland, không mở tỉnh ngoài danh sách.

“GIS có trang chủ” khác “GIS trả polygon địa chính sử dụng được”. Chỉ kích hoạt
khi mẫu thật có hình học gốc hợp lệ, định danh thửa và đúng địa bàn; không lấy
polygon quy hoạch/địa giới hành chính làm ranh thửa. Không kết luận một tỉnh
không có GIS chỉ vì các cổng đã kiểm đang lỗi.

## Kết quả và điều kiện tiếp tục

| Ưu tiên | Địa bàn cũ | Trạng thái GIS ranh ngày kiểm | Việc đã làm / bước mở lại |
| --- | --- | --- | --- |
| 3 | Hà Nội | `blocked_tls`: [cổng chính thức](https://quyhoach.hanoi.gov.vn/) và [API công bố](https://apiquyhoach.hanoi.gov.vn/) báo chứng chỉ hết hạn; `qhkhsdd.hanoi.gov.vn/datdai` cũng lỗi TLS. Xác nhận bằng cả Python và curl/Schannel vẫn bật xác minh. `quyhoach.hanoi.vn` là trang dịch vụ khác có gói tài khoản, không đồng nhất với cổng `.gov.vn`. | Chưa thêm provider. Kiểm lại khi cổng/API được gia hạn chứng chỉ và có endpoint polygon+ID công khai. Mẫu Guland Hà Nội cũ chưa xác minh định danh địa chính: `deferred_guland`. |
| 4 | Đồng Nai | `blocked_maintenance`: [cổng đất đai Đồng Nai cũ](https://datdai.stnmt.dongnai.gov.vn/) HTTP 200 nhưng nội dung “Hệ thống đang bảo trì”. Nguồn GIS Đồng Nai đang dùng cho Bình Phước cũ trả count=0 với huyện Biên Hòa cũ 731. Đây là một phép kiểm huyện, không chứng minh mọi nguồn Đồng Nai cũ đều không có dữ liệu. | Giữ 18 tham chiếu cũ đã lưu, không chạy collector Guland. Chờ cổng địa chính cũ hoạt động hoặc nguồn GIS công khai mới được xác minh; không gán snapshot Bình Phước sang Đồng Nai cũ. |
| 5 | Long An | `blocked_geometry`: [GIS Tây Ninh](https://gis.tayninh.gov.vn/) mở được; [WFS](https://geo.tayninh.gov.vn/geoserver/wfs?service=WFS&version=2.0.0&request=GetFeature&typeNames=cite:thuadat_chauthanh4326&resultType=hits) trả `numberMatched=101154` cho `cite:thuadat_chauthanh4326` (Châu Thành, Long An cũ). Nhưng GetFeature JSON/GML, mẫu 1–3 thửa, có/không bbox, chỉ trường an toàn, vẫn HTTP 500; thử POST XML WFS 2.0 trả HTTP 404. Timestamp do WFS trả là 2026-06-19; không gọi đây là tổng cập nhật toàn tỉnh tháng 11. | Chưa đăng ký adapter. Kiểm lại GetFeature khi nguồn sửa lỗi; schema/count không đủ để bật ranh. Nguồn `quyhoach-gis.tayninh.gov.vn` được mô tả cho Tây Ninh cũ, không suy sang Long An. Guland: `deferred_guland`. |
| 6 | Hưng Yên | `unverified_historic_scope`: [GIS data Hưng Yên](https://gisdata.hungyen.gov.vn/quyhoachv4.aspx?orgcode=thaibinhcsdl) mở được bằng curl với TLS chuẩn hệ điều hành; Python gặp lỗi chuỗi issuer, không phải kết luận nguồn hết hạn. CSDL `thaibinhcsdl` là đầu mối Thái Bình cũ, chưa chứng minh ranh Hưng Yên cũ. [App Viettel](https://play.google.com/store/apps/details?id=com.viettel.gis.hyn&hl=vi) mô tả đồ án quy hoạch, chưa có endpoint polygon địa chính Hưng Yên cũ được xác minh. | Chưa thêm provider. Cần nguồn/DB đúng Hưng Yên cũ, polygon và số tờ/thửa thật; không đưa Thái Bình vào thay thế. Guland: `deferred_guland`. |
| 7 | Hải Phòng | `unverified_geometry`: [cổng đất đai công bố trước đây](https://hph.mplis.gov.vn/og/) hiện HTTP 404, root HTTP 200 là trang VBDLIS mặc định. [Cổng quy hoạch](https://quyhoach.haiphong.gov.vn/) mở được nhưng chưa xác minh API polygon địa chính; website quy hoạch không tự chứng minh có ranh thửa. | Chưa thêm provider. Theo dõi route đất đai mới từ cơ quan chủ quản hoặc API địa chính được phép dùng, tách Hải Phòng cũ/Hải Dương. Guland: `deferred_guland`. |
| 8 | Khánh Hòa | **`verified_local`**: [GIS tỉnh](https://gis.khanhhoa.gov.vn/public/8192/) và [lớp ThuaDat_region](https://gis.khanhhoa.gov.vn/arcgis/rest/services/Base/DiaChinh/MapServer/8?f=pjson) hoạt động không cần tài khoản. Count nguồn **971.792**, mẫu polygon gốc WGS84 có số tờ/thửa/diện tích. | Đã tích hợp live viewport/cells, tìm tờ/thửa, tra WGS84, cache original, popup/đo cạnh dùng chung, chọn Khánh Hòa cũ. 134 tham chiếu xã/phường thuộc 8 huyện/thị/thành phố; mẫu thật của cả 8 đã kiểm. Không có Trường Sa/Ninh Thuận trong phạm vi đã tích hợp. Xem [doc kỹ thuật](khanh-hoa-parcels.md). Chưa deploy. |
| 9 | Đà Nẵng | `blocked_upstream`: [GIS portal](https://gisportal.danang.gov.vn/sxd/) HTTP 200 là iframe sang [thông tin quy hoạch](https://thongtinquyhoach.danang.gov.vn/), trang đích timeout qua hai lượt đọc thường; [ArcGIS services](https://gisportal.danang.gov.vn/server/rest/services?f=json) HTTP 503. Cổng thành phố từng công bố chức năng thửa, nhưng đợt này chưa lấy được polygon thật. | Chưa thêm provider. Kiểm lại khi portal/ArcGIS phục hồi; không suy lỗi mạng là không có thửa. Guland: `deferred_guland`. |
| 10 | Lâm Đồng | `blocked_tls`: [cổng quy hoạch](https://quyhoach.lamdong.gov.vn/) và nguồn được dẫn `https://gis.dalat.vn:8088/arcgis/rest/services` đều bị Schannel xác nhận `SEC_E_CERT_EXPIRED`; HTTPS cổng thông thường cũng lỗi. Chưa xác minh lớp địa chính/độ phủ gốc qua kết nối hợp lệ. | Chưa thêm provider. Chờ chứng chỉ hợp lệ hoặc bộ dữ liệu GIS được phép chia sẻ có provenance; giữ scope Lâm Đồng cũ. Guland: `deferred_guland`. |

## Giới hạn và bằng chứng

- Khánh Hòa là **một provider ranh mới được bật local**, không phải đã hoàn tất
  mọi lớp quy hoạch của tỉnh. Count 971.792 là số bản ghi nguồn, không phải số
  polygon đã tải/kiểm hết. Mẫu kiểm thành công không chứng nhận phủ kín 134 xã.
- Các đầu mối từ website tổng hợp chỉ được dùng để tìm URL rồi kiểm trực tiếp
  cổng chính thức. Không dùng proxy/bản cache của bên thứ ba để vượt chứng chỉ
  hết hạn, không tắt TLS, không lấy cookie/token, không dùng gói trả phí.
- Các truy vấn thửa chỉ yêu cầu số tờ/thửa, diện tích, mã/tên hành chính và hình
  học. Không yêu cầu, lưu hoặc public chủ đất, địa chỉ chủ đất hay giấy tờ.
- Chẩn đoán local (ignored): `.local/priority-gis-20261102/`. Kết quả landing/TLS,
  schema, metadata, kiểm WFS, mẫu Khánh Hòa an toàn và HTTP proof được giữ ở đó.
  Không commit các bundle/HTML tải từ nguồn hoặc dữ liệu runtime.
- Code/metadata của provider được lưu trong Git; trạng thái VPS/edge và rendered
  browser **chưa xác minh**. Chrome báo local browser use disabled; không gọi
  kết quả API/runtime JS là kiểm chứng giao diện bằng trình duyệt.

## Cách lần sau tiếp tục

1. Đọc [sổ ưu tiên](maps-priority-markets.md), rồi đọc hàng tương ứng ở trên.
2. Với nguồn blocked, kiểm lại đúng điều kiện đang chặn trước khi viết adapter.
   Giữ ngày và trạng thái cũ, thêm bằng chứng mới; không đoán nguồn hết lỗi.
3. Chỉ đổi sang `verified_local` sau polygon + ID + search/point/viewport thật,
   allowlist field/CRS/namespace và kiểm bounded cache. Ghi vùng thiếu rõ.
4. Chỉ xử lý phần `deferred_guland` khi người dùng yêu cầu làm đợt Guland sau.
   Đợt GIS hiện tại không tự khởi động thu thập từng thửa Guland.
