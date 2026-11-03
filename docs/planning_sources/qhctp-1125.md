# QHCTP theo QĐ 1125 — TP.HCM cũ

Kiểm ngày 2026-11-03, trạng thái: local đã chạy ảnh GIS thật; chưa deploy.

Nguồn công khai: https://gisxaydung.tphcm.gov.vn/tracuuttqh.
Nhóm menu GIS `QHCTP_QD1125` / `QHCTP_QD1125_SDD` ánh xạ 17 lớp sử dụng đất
2–18 của `/arcgis/rest/services/HCM/TongHopChuyenDe_QHCTPHCM/MapServer`.
Đã đối chiếu metadata MapServer/FeatureServer và từng lớp menu. Không dùng
SuDungDat_QHC_HCM, QH Chi tiết Bình Dương, hoặc lớp dự thảo 100 năm thay thế.

`services/planning_tiles.py` xuất PNG32 256×256, Web Mercator EPSG3857,
`layers=show:2,...,18`, `transparent=true`. Kiểm width/height/extent đúng ô XYZ
trước khi nhận ảnh; ảnh phải qua validate_png. Dùng guest handshake công khai
PublicGIS, token chỉ ở RAM server, không trả trình duyệt/ghi log/audit/cache.
ArcGIS có thể trả lỗi token bằng HTTP200; lỗi 401/498/499 làm phiên hết hạn để
lượt tải sau xin lại. Không đọc dữ liệu tài khoản hay cookie người dùng.

Tái dùng gateway/cache native: 4 cold reads/process, queue hữu hạn, single-flight,
PNG cache 24h với giới hạn entries/bytes có sẵn. Bốn session khách độc lập tránh
chia sẻ requests.Session giữa các thread. Cache key có tên service và nhóm 2–18;
không thể dùng nhầm ảnh từ theme khác. Audit ghi render_method export-sdd-2-18.
Đây là ảnh export theo ô, không phải tile pyramid native do nguồn công bố.

Theme `qhctp_1125`, dock **QHCTP (QĐ 1125)**. Catalog ghi coverage_provinces
chỉ `hcm`, area hcm-legacy; chọn Bình Dương/BRVT không có nút này. Bounds chữ
nhật chỉ là cửa sổ tải, không phải polygon địa giới hoặc cam kết nguồn phủ kín.
Client dùng createReference scheduler4, cancel on unload/zoom/remove, không tải
vector toàn thành phố. Link chia sẻ giữ được theme. Độ hiển thị mặc định100%,
SDĐ2030 60%; QH Chi tiết ẩn ở dock/menu/rail, adapter cũ giữ để tương thích.

Kiểm chứng ảnh thật qua chính gateway: Q1 zoom12/16/18, Thủ Đức zoom15,
Củ Chi zoom15 đều256×256, alpha có nội dung và extent đúng. Đây là mẫu kiểm,
không khẳng định toàn bộ thửa/khu vực có dữ liệu hoặc xác nhận pháp lý.
Chrome1100px/390px trên local5055: ảnh thật,100%, bật/tắt/bật và đổi Bình Dương
ẩn nút, không page error. Python kiểm extent sai bị từ chối, source cố định,
nhóm lớp cố định; JS kiểm source allowlist, phạm vi tỉnh, opacity, vòng bật/tắt.

Evidence ignored `.local/qd1125-{MapServer,FeatureServer}.json`,
`.local/qd1125-live-verification.json`, `.local/qd1125-local-{1100,390}.png`.
Ngày kiểm tra, GET metadata không có guest header bị timeout; guest handshake
trả200. Không quy timeout đó thành kết luận dịch vụ không tồn tại.
