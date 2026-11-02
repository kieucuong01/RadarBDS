# Đồng Nai cũ: nguồn góc ranh ngoài GIS công khai

Yêu cầu mới ngày 02/11/2026 cho phép nghiên cứu lại nguồn ngoài GIS cho riêng
Đồng Nai cũ. Không mở collector toàn quốc hoặc tự dùng tài khoản trả phí.

## Mẫu Guland xác minh trực tiếp

Chrome hiện hoạt động. Mở https://guland.vn/soi-quy-hoach/dong-nai bằng phiên
trình duyệt đang đăng nhập sẵn; click một thửa rồi mở **Bảng tọa độ**. Không
copy cookie/token, không gọi lại API bị 403, không vượt giới hạn truy cập.

- Thửa **467**, tờ hiển thị **57**, thông tin cũ ghi tờ **5**, Gia Tân 2,
  Thống Nhất, Đồng Nai cũ. Giữ cả hai số tờ, không tự chọn một làm chuẩn.
- UI trả bảng VN2000 và bảng Google Maps: 8 đỉnh phân biệt + điểm đóng vòng.
- Chép chính xác bảng Google Maps sang GeoJSON (longitude, latitude), kiểm
  Shapely polygon hợp lệ và kín; diện tích geodesic WGS84 **736.7853 m²**,
  gần diện tích nguồn **737 m²**. Đây là nhất quán nội bộ, không xác nhận
  tính pháp lý, ngày đo hoặc độ chính xác độc lập.
- Mẫu ignored: `.local/dongnai-browser-corner-proof.geojson`; script tái kiểm
  `.local/dongnai-browser-corner-proof.py`. Không có chủ đất/GCN/thông tin cá nhân.
- Chưa biết source object ID; chưa đưa vào archive chuẩn hoặc live Maps.
  `scripts/archive_guland_parcels.py` yêu cầu ID nguồn thật: không điền ID giả
  bằng số thửa vì không duy nhất. Chưa gọi chi tiết quy hoạch.
- Không gọi đây là anonymous/free-for-production: phiên Chrome đang đăng nhập,
  thao tác mẫu không hiện yêu cầu mua nhưng hạn mức/quyền gói chưa xác minh.

## Phương án khả thi

1. **Thu thập theo khu vực nhỏ hoặc thửa người dùng quan tâm qua UI được phép**:
   lưu polygon gốc, định danh nguồn, địa bàn cũ/mới, ngày thu thập, phiên bản và
   hash; tra lại từ kho local. Đã chứng minh lấy được tọa độ một thửa, chưa chứng
   minh truy xuất hàng loạt hay phủ tỉnh. Dừng khi nguồn yêu cầu trả phí/chặn.
2. **Nhập file địa chính từ đơn vị đo đạc/chủ dữ liệu cho phép sử dụng**:
   ưu tiên GeoPackage/GeoJSON/SHP hoặc DXF có ranh kín và hệ chiếu xác định.
   Xác minh VN2000, tờ/thửa và địa bàn trước khi nhập. Đây là hướng tránh thao
   tác từng thửa, nhưng chưa tìm được bộ Đồng Nai cũ miễn phí có nguồn rõ.
3. **GMap Cloud**: tài liệu sản phẩm có API trả `geometry_geojson`, nhưng mẫu
   công bố là Đà Nẵng; phạm vi Đồng Nai và chi phí/quyền lưu lại cần nhà cung
   cấp xác nhận. Không dùng demo key làm phụ thuộc production.
4. **Tài Đỗ Map**: UI có xuất tọa độ và tải địa chính nhưng có đăng nhập/gói
   địa bàn/VIP. Chưa xác minh Đồng Nai cũ hoặc quyền xuất cả tỉnh miễn phí.

Nguồn kiểm: https://cloud.gmap.vn/products/parcels/ và https://tdmap.pro.vn/.
Không suy polygon từ màu QH2030/ảnh vệ tinh; các ảnh này không cung cấp góc
ranh địa chính chính xác. Việc lưu/xuất lại dữ liệu quy mô sản phẩm phải xác
minh điều kiện nguồn, không suy quyền tái phân phối từ việc xem được trên UI.

Kết luận: đã có bằng chứng kỹ thuật lấy góc ranh Đồng Nai cũ từ Guland qua
bảng tọa độ, có mẫu local hợp lệ. Chưa có giải pháp tải miễn phí toàn tỉnh được
xác minh, chưa viết/bật adapter production hoặc job thu thập hàng loạt.
