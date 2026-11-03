# Vị trí và chọn khu vực Maps

Ngày 2026-11-03. Nút định vị ở bên trái bộ chọn khu vực trên header gọi
`RadarListingMap.locateArea()`: dùng quyền Geolocation của trình duyệt, hiện
loading, đặt marker và chọn tỉnh/huyện cũ theo vị trí. Nút định vị Leaflet cũ
vẫn chỉ di chuyển camera. Từ chối quyền hoặc lỗi định vị giữ khu vực hiện tại.

Chỉ lối vào **Bản đồ quy hoạch** truyền `locateArea:true`; link điều hướng dùng
`map=1&planning=land_use_2030&locate=1`. Tin rao/Săn Deal mở Maps không truyền
cờ này, giữ vùng bộ lọc. Link chia sẻ có camera trong hash không tự định vị,
kể cả có cờ locate. Cờ locate bị loại khỏi link chia sẻ và bộ lọc. Chọn rõ một
khu vực ở form trang quy hoạch cũng không tự thay bằng vị trí người dùng.

`POST /api/planning/locate-area.json` nhận đúng hai số latitude/longitude,
body tối đa1024B, không cookie, không cache; response `private, no-store`.
`services/planning_area_location.py` dùng snapshot polygon xã cũ đã có ở
`static/data/admin_vn_legacy`, lọc bounds rồi Shapely covers (có xét lỗ), khớp
huyện với registry `config/planning_landuse_areas.json`. Không gọi reverse
geocoding bên ngoài hay lưu tọa độ vào DB. Camera vẫn nằm trong link Maps theo
chức năng chia sẻ hiện có. Không đưa body tọa độ vào log/analytics.

Snapshot là dữ liệu tham khảo đã đơn giản hóa, không xác nhận hành chính/pháp
lý. Nếu không khớp hoặc nhiều tỉnh cùng khớp, không tự đổi khu vực. Huyện mơ
hồ chỉ chọn tỉnh. Snapshot HCM cũ còn quận2/9 được gộp về TP.Thủ Đức trong
registry. Người dùng đổi khu vực hoặc đóng Maps sẽ hủy request đang chờ để
phản hồi cũ không kéo bản đồ trở lại.

Kiểm thử: Python polygon có lỗ, ba vị trí thực, validation/private headers;
JS không auto-locate Tin rao/Săn Deal và shared view. Chrome giả lập GPS kiểm
header, tự mở quy hoạch, từ chối quyền, màn hình1100/390px. Đây không phải phép
đo GPS hoặc thử trên điện thoại vật lý.
