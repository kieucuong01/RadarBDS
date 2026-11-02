# QH xây dựng theo lớp Guland — 2026-11-02

Đây là theme `construction` riêng, không ghép vào phân khu/chung/chi tiết và không
đồng nhất với giấy phép xây dựng. Rà nút **QH xây dựng** trên 63 trang tỉnh cũ qua
Chrome công khai; chỉ đọc `data-url`, `data-type`, không xuất cookie/tài khoản.

- 33 trang có template; 32 địa bàn có mẫu PNG thật tại tọa độ trong window tỉnh
  và được đăng ký. 30 trang không thấy control riêng ở lần kiểm này.
- Đắk Nông có control nhưng trùng template Đắk Lắk; giữ ngoài registry dù một
  tile overview có màu, vì chưa đủ bằng chứng tách đúng địa bàn.
- Đồng Nai và Bình Phước có tên thư mục nguồn chéo; giữ theo control quan sát
  của từng trang và mẫu có ảnh tại đúng window tỉnh cũ, không suy tên thư mục.
- Hưng Yên có đồ án Văn Giang, Bình Định có Quy Nhơn, Gia Lai có Pleiku, Nghệ An
  có Vinh, Sơn La/Thái Nguyên/Thanh Hóa có đồ án đô thị. Nhãn tỉnh là cửa chọn,
  không chứng nhận dữ liệu phủ kín tỉnh hoặc có hiệu lực pháp lý.

`config/planning_construction.json` chứa 32 descriptors, `planning_construction_audit.json`
chứa đủ 63 trạng thái, control URL và mẫu HTTP/PNG/hash/toạ độ. Bounds là window
điều hướng tỉnh cũ, không phải footprint polygon pháp lý. Native min/max zoom chỉ
lấy từ các mức có mẫu ảnh; vùng trống/zoom chưa lấy mẫu vẫn có thể trống. Không
hạ minNativeZoom để gọi ô không tồn tại, không fan-out ghép các đồ án QH khác.
Một số nguồn chỉ có mẫu ở zoom12 nên overzoom sẽ mờ; chưa làm pyramid mới.

Rule chính xác được inject thành `RADAR_CONSTRUCTION_SOURCE_RULES`, merge với
partition rules chỉ khi validate catalog. Giữ nguyên tập PARTITION_SOURCE_RULES.
Kiểm theme/source/URL/coverage/manifest trước mount, không nới wildcard host.
Dùng renderer XYZ và queue4/abort/LRU có sẵn; tải duy nhất tỉnh chọn + vùng nhìn.
Lớp mặc định tắt, khi bật opacity35%, độc lập với theme khác; URL share nhận
`planning=construction`. Giữ attribution nguồn. Không thay dữ liệu tin rao/ranh.

Kiểm chứng local: 143 JavaScript tests; Python source/wiring/UI regressions;
`node tests/planning_overlay_runtime.cjs` đạt. Chrome render Bình Dương có ảnh,
35%, không console warning/error; đổi Hà Nội ẩn nút xây dựng, giữ tin rao ẩn.
Chưa kiểm hết mọi tile/tỉnh/mức zoom hay tính pháp lý của hồ sơ.

Release: code + hai config JSON, version catalog `construction-20261102` và
JS/style version tương ứng; không cần chuyển ảnh runtime (nguồn XYZ trực tiếp).
Đọc config/audit khi bổ sung tỉnh; chỉ kích hoạt sau control + ảnh thật đúng vùng.
Rollback bằng commit trước; các lớp nguồn và cache ranh cũ không đổi.
