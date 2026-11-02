# Xử lý các điểm chất lượng lớp — 02/11/2026

Tiếp nối audit13 tỉnh theo yêu cầu người dùng. Không đổi source/template/theme
hoặc native zoom để lấp vùng không có ảnh. Các kết quả trước được giữ làm lịch sử.

## Nguyên nhân và sửa

1. Audit cũ so sánh HTTP status với số200, nhưng audit phân khu lưu chuỗi
   `"200"`. Vì vậy bỏ qua tất cả điểm phân khu từng có ảnh, rồi lấy tâm window.
   Chuẩn hóa so sánh cả số/chuỗi; chỉ chọn điểm thành công nằm trong layer.
2. Nhiều window bao biển/đảo, tâm layer không phải điểm ảnh quy hoạch. Dùng
   focus đã cấu hình nếu nằm trong layer; nếu không thì fallback tâm riêng
   layer. Côn Đảo không dùng focus BRVT đất liền. Không sửa window nguồn để
   giả định phủ kín. Test giữ chuỗi200, loại403/khác địa bàn và tách đảo.
3. Kiểm source GIS trực tiếp bị timeout từ Windows. Kiểm **composite public
   thực tế từ VPS**: PK/C/CT đều HTTP200, PNG256, alpha khác rỗng tại tile
   z14/x13044/y7687. PK/C đầy alpha, CT bbox `[82,76,256,256]`. VPS SHA
   `b59294a6`; đây là kiểm3 ô ở vùng Bình Dương, không phải toàn HCM/BRVT.
4. UI overzoom: `planning_overlay.js` bổ sung dòng “Một số lớp đang phóng lớn
   từ ảnh gốc; phóng gần hơn không tăng độ chi tiết.” khi có lớp vượt native
   max. Cảnh báo tự hết khi quay lại zoom gốc. Giữ được thao tác phóng gần,
   không tạo ảnh giả nét; test xác nhận xuất hiện và biến mất.

## Kết quả kiểm lại

**32 layer–province entries, 63 mẫu zoom gần/xa:63 ảnh hợp lệ,0 lỗi,0 ảnh
alpha rỗng.** Phân khu Khánh Hòa/Quảng Ninh/Đà Nẵng đều có ảnh ở điểm đã
kiểm đúng. SDĐ2030 Hải Phòng/Khánh Hòa/Đà Nẵng có ảnh ở focus trong phạm vi.
BRVT/Côn Đảo được lấy mẫu riêng. Không nhận xét source-wide từ tile không
tồn tại ở vị trí khác.

[JSON kiểm lại](priority-13-layer-quality-resolved-2026-11-02.json) giữ từng
point/zoom/URL/SHA256/status và3 composite public. Ảnh runtime tại
`.local/quality-fix-final-20261102/`. Phép kiểm không bypass403, không thử
proxy/host khác hoặc copy cookie. Không thay nguồn Guland/GIS đang chạy.

Các lớp max native12/14 giữ overzoom để người dùng đọc bản đã có. Không build
pyramid mới: hiện chưa có lỗi mất ảnh nguồn tại mẫu đúng điểm cần khắc phục.
Không giả lập QH chung/chi tiết cho tỉnh thiếu dữ liệu trong registry.

## Xác minh và giới hạn

Audit script,3 Python kiểm audit/asset và runtime overlay đều qua; các bộ
exact theme/source/province trước đó giữ nguyên. Asset version hiện local
`mobile-profile-20261102` chứa cả sửa hiệu năng từ task trước và cảnh báo mới.
Chưa commit/push/deploy các thay đổi local này.

Chưa duyệt toàn bộ control Guland live, tile vùng biên, hồ sơ phê duyệt hoặc
chú giải mọi đồ án. PNG có alpha không chứng minh nội dung đúng/đủ ở mọi thửa.
Chưa kiểm giao diện thật13 tỉnh; kết quả3 composite public là ảnh thực đã lấy
và giải mã trên VPS, không phải rendered-browser proof hoặc phủ kín toàn vùng.
