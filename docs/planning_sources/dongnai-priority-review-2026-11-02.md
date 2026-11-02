# Đồng Nai cũ — đợt xử lý theo ưu tiên 02/11/2026

## Phạm vi và kết quả

Người dùng yêu cầu xem Đồng Nai còn cần gì thì thực hiện, sau hồ sơ 13 thị trường.
Phạm vi là **Đồng Nai cũ**; giữ nguyên Bình Phước cũ và các địa bàn khác. Kiểm
HEAD local `0249024cae7c5e62ab4d2a4e8a7114853177c830`, cấu hình đang có và nguồn
công khai. Không khởi động collector Guland, không thêm dependency, không chuyển
QH xây dựng/SDĐ2030 thành phân khu để bù nguồn thiếu.

**Đã sửa:** manifest lớp `dong-nai-expanded-land-use-2030-reference` trước ghi
notice riêng “Bình Phước cũ”, mặc dù hai tỉnh cũ dùng chung source. Nay ghi rõ
Đồng Nai và Bình Phước cũ, tải theo tỉnh cũ đang chọn và giới hạn phép kiểm.
Giữ ID/template/coverage windows/native zoom/cache/opacity cũ, nên không thêm
request và không thay giới hạn tải ảnh. Không sửa `tile_size` logic 256 chỉ vì
ảnh SDĐ2030 gốc có kích thước 512×512; hai giá trị có vai trò khác nhau.

## Kiểm hai lớp đang có

44 request ảnh, concurrency tối đa 4, tại trung điểm bbox của 11 khung huyện
tham khảo, hai theme × hai mức zoom 12/16. Mọi mẫu HTTP 200, PNG có alpha khác
0; SDĐ2030 512×512, xây dựng 256×256. Trung điểm bbox không chứng minh điểm ở
trong polygon huyện, và alpha dương tính không chứng minh đúng pháp lý/đủ phủ.

| Khung huyện/thành phố cũ | SDĐ2030 z12/z16 | Xây dựng z12/z16 |
| --- | --- | --- |
| Biên Hòa | Có ảnh / Có ảnh | Có ảnh / Có ảnh |
| Long Khánh | Có ảnh / Có ảnh | Có ảnh / Có ảnh |
| Long Thành | Có ảnh / Có ảnh | Có ảnh / Có ảnh |
| Nhơn Trạch | Có ảnh / Có ảnh | Có ảnh / Có ảnh |
| Trảng Bom | Có ảnh / Có ảnh | Có ảnh / Có ảnh |
| Vĩnh Cửu | Có ảnh / Có ảnh | Có ảnh / Có ảnh |
| Thống Nhất | Có ảnh / Có ảnh | Có ảnh / Có ảnh |
| Cẩm Mỹ | Có ảnh / Có ảnh | Có ảnh / Có ảnh |
| Xuân Lộc | Có ảnh / Có ảnh | Có ảnh / Có ảnh |
| Định Quán | Có ảnh / Có ảnh | Có ảnh / Có ảnh |
| Tân Phú | Có ảnh / Có ảnh | Có ảnh / Có ảnh |

Đã xem trực tiếp sáu ảnh z16 tại Biên Hòa/Long Thành/Nhơn Trạch cho cả hai theme:
có vùng màu quy hoạch, đường/thủy hệ; lớp 2030 có mã sử dụng đất. Đây không phải
kiểm chồng khớp đường/thửa hoặc xác nhận hiệu lực hồ sơ. Đường dẫn xây dựng có
chuỗi `binh-phuoc--qhxd`, nhưng không tự đổi URL theo tên folder: registry trước
đã lấy đúng control trang Đồng Nai và mẫu đợt này có ảnh tại các window Đồng Nai.

Nguồn mẫu, tọa độ, kích thước, bytes, SHA-256 và giới hạn được giữ trong
[bằng chứng JSON](dongnai-review-2026-11-02.json). Ảnh/diagnostic runtime nằm
trong `.local/dongnai-review-20261102/` (ignored), không đưa raster vào Git.

## Ranh thửa: chưa có nguồn dùng được cho Đồng Nai cũ

- `https://datdai.stnmt.dongnai.gov.vn/`: HTTP 200, nội dung **“Hệ thống đang
  bảo trì”**. Status 200 không phải cổng tra cứu đã hoạt động.
- `https://gis.dongnai.gov.vn/arcgis/rest/services/NenDiaChinh/MapServer/1/query`:
  query chỉ đếm, `MaQuanHuyen IN ('731','732','734','735','736','737','738',
  '739','740','741','742')`, trả **count=0**. Đây là phép kiểm source cụ thể,
  không kết luận tất cả GIS Đồng Nai không có thửa.
- Group/count của layer hành chính `/NenDiaChinh/MapServer/3/query` chỉ trả
  mã huyện **688–698**, tương ứng phạm vi Bình Phước cũ của adapter hiện có.
  Không tải tên chủ đất, giấy chứng nhận hoặc địa chỉ cá nhân.
- Rà directory công khai ở bốn folder `QuyHoachPhanKhu`, `QHCT`, `SuDungDat`,
  `QH_CD`: có các service quy hoạch/hạ tầng, nhưng tên folder không chứng minh
  chúng có lớp thửa hoặc phủ Đồng Nai cũ. Không thêm chúng vào catalog chỉ vì tên.
- `https://gis3d.binhphuoc.gov.vn/` lỗi xác minh chứng chỉ trong Python; không
  tắt TLS, không dùng relay. Không dùng cổng 3D làm bằng chứng cadastre cũ.

Các công bố chính thức tìm được vẫn dẫn ứng dụng DNAILIS; chưa xác minh được
API polygon Đồng Nai cũ công khai phù hợp để tích hợp. Có ứng dụng tra cứu không
đồng nghĩa có quyền/API để RadarBDS tự sao chép toàn bộ dữ liệu.

## Phân khu, QH chung, chi tiết còn thiếu

Cấu hình local chưa có source đúng theme cho ba lớp này tại Đồng Nai cũ. Audit
Guland trước có các đồ án QH khác, nhưng người dùng đã yêu cầu bỏ việc ghép
QH khác vào phân khu tổng do chồng chéo; tiếp tục giữ quyết định đó.

Đợt kiểm mới: trang `https://guland.vn/soi-quy-hoach/dong-nai` trả HTTP 403 khi
đọc trực tiếp. Công cụ CUA trả **“Local browser use is disabled in Work settings”**.
Vì vậy chưa kiểm lại được control hiện hành bằng Chrome, không gọi audit cũ là
bằng chứng nguồn chưa thay đổi. Không lặp lại đường truy cập bị chặn hoặc đoán URL.

Nguồn tham chiếu chính thức để mở lại:

- [Sở Xây dựng giới thiệu GIS, 09/12/2025](https://sxd.dongnai.gov.vn/vi/news/Chuyen-doi-so/gioi-thieu-he-thong-thong-tin-dia-ly-gis-12559.html):
  mô tả hệ thống và chia sẻ theo phân quyền; hình minh họa có Bình Phước,
  không chứng minh đã phủ Đồng Nai cũ bằng API công khai.
- [Sở NN&MT dẫn DNAILIS](https://snnmt.dongnai.gov.vn/EN/NewsEvents/Detail/10264):
  dùng để tìm kênh chính thức, không suy ra endpoint polygon chưa quan sát.

## Việc tiếp tục theo thứ tự

1. Khi cổng địa chính hết bảo trì: lấy mẫu polygon+ID của Biên Hòa, Long Thành,
   Nhơn Trạch; kiểm CRS, tờ/thửa, holes/multipart và membership. Chỉ sau đó mới
   tạo adapter đúng phạm vi và namespace; không tái dùng ID Bình Phước.
2. Khi Chrome khả dụng: rà control phân khu tổng/chung/chi tiết của trang tỉnh
   cũ; chỉ bổ sung khi đúng theme, có ảnh đúng vị trí và exact source rules.
   Không tự ghép lại QH khác. Nếu chỉ có PDF thì giữ PDF, không giả nguồn GIS.
3. Ranh Guland cần thu thập riêng: giữ `deferred_guland`, không crawl từng thửa
   trong đợt GIS này. Không lấy nét raster hoặc địa giới thay polygon gốc.
4. Sau khi có nguồn thật: kiểm các công cụ dùng chung, nhập tọa độ/CRS địa phương,
   popup/đo cạnh, chi tiết GIS theo yêu cầu, mobile và share URL. Nguồn chưa có
   thì không thể đánh dấu các chức năng tra thửa Đồng Nai đã hoàn tất.

## Kiểm chứng thay đổi

19 test qua: `test_planning_landuse_2030.py`, `test_planning_landuse_areas.py`,
`test_planning_national_2030.py`, `test_dongnai_parcels.py`. Không thêm test riêng
chỉ để kiểm câu copy; các test đang có kiểm template, phạm vi hai tỉnh, cách ly
registry và adapter. Không chạy load test/DB migration cho thay đổi metadata này.
Chưa kiểm rendered browser do CUA bị tắt; chưa commit/push/deploy trong đợt này.
