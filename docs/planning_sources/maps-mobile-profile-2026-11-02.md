# Maps: Chrome mobile profile, 02/11/2026

Không có ADB được tìm thấy trong PATH; không xác minh được điện thoại thật
kết nối. Kết quả dưới đây là **desktop Chrome headless mô phỏng mobile**, không
phải FPS/INP/RAM trên Android/iPhone. Áp dụng performance-optimization: đo trước,
chỉ sửa điểm có bằng chứng, đo lại; không chạy load test production.

## Phương pháp

Local app port 5055; viewport 390×844, touch/mobile, CPU throttling 4×.
Playwright dùng Chrome cài sẵn. Đóng onboarding và mở Maps bằng hàm ứng dụng.
Bật SDĐ2030/chung/phân khu, 6 pan/zoom, đổi Đồng Nai → Bình Phước → Bình Dương,
8 toggle SDĐ2030, chờ ổn định và forced GC cuối lượt. Không throttle network;
nguồn ảnh live và browser cache khiến các lượt không tương đương tải lạnh.
Chỉ zoom vùng tổng quan, **chưa stress ranh thửa zoom17+** hoặc vệ tinh.

Lưu ignored tại `.local/maps-mobile-profile/`: JSON request/failure/resource,
heap+DOM snapshots, CPU profile, screenshot; script `.local/maps-mobile-profile.py`.
Không chứa cookie/body API hoặc dữ liệu chủ đất. Các URL request đã bỏ query.
`tile_images` đếm `.leaflet-tile` (có cả canvas), không chỉ ảnh raster.

## Kết quả quan sát

| Lượt | Request events | Failed | Long tasks >50ms | Max long task | Frame intervals >50ms | JS heap sau GC |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Baseline đầu | 380 | 29 | 53 | 1242ms | 94 | 6.34MB |
| Baseline có CPU profiler | 365 | 14 | 27 | 1174ms | 56 | 6.47MB |
| Sau sửa, có CPU profiler | 352 | 18 | 51 | 1108ms | 101 | 6.45MB |

MB là 1 triệu byte, chỉ JS used heap, không phải tổng RAM/GPU/decoded image.
Frame intervals từ requestAnimationFrame gồm khởi tạo trang và hoạt động test;
không phải tỷ lệ dropped frames hoặc INP thật. Các lượt chưa chứng minh FPS tốt
hơn: long-task/frame counts có biến động mạnh và cả overhead automation.

Baseline đầu: 15 `ERR_ABORTED`, 14 `ERR_BLOCKED_BY_ORB`. Abort có thể là hủy
hợp lệ; ORB là lỗi ảnh GIS, không tính là hủy thành công. Phép đo chưa phân tích
body/status tại source nên không kết luận nguyên nhân server/CORS. Một URL
được request lại sau toggle/quay về tỉnh không tự chứng minh tải lại qua mạng:
cần tách cache hit và byte thật; transferSize=0 ở cross-origin không chứng minh
cache vì có thể thiếu Timing-Allow-Origin. Không suy giảm byte từ số requests.

Cả hai lượt CPU: tile count 24 → 45 (multi) → 32 (pan/zoom) → 24 (về BD),
vẫn 24 sau toggles. DOM 1921 ban đầu, 1928 cuối, 4 annotation overlays cuối.
Chưa thấy tăng tích lũy trong vòng thử ngắn; chưa chứng minh không leak lâu dài.

## Sửa đã làm local

1. `planning_overlay.js`: menu từng tìm ID bằng `catalog.find` cho mỗi option,
   thành O(n²) mỗi lần cập nhật. Tạo Map ID một lần sau normalize catalog rồi
   dùng cho menu và lựa chọn hồ sơ. CPU self-samples tại callback tìm/cập nhật
   option: khoảng 219ms baseline → 37ms sau sửa trong kịch bản này. Không coi
   đây là benchmark ổn định hoặc mức tăng tốc toàn Maps.
2. `listing_map.js`: bỏ `history.replaceState` khi URL bằng URL hiện tại.
   Test chứng minh duplicate event không ghi history và vẫn giữ modal state.
   Chi phí replaceState trong CPU samples vẫn dao động, chưa đo giảm thực tế.
3. Bump JS/CSS asset version `mobile-profile-20261102`; giữ cặp asset đồng bộ.

Chưa deploy. Không đổi độ nét/nguồn ảnh/toggle mặc định hoặc cache privacy.

## Bước tiếp theo cần đo

- Điện thoại Android/iPhone thật: cùng vị trí, độ zoom và network, đo cold/warm
  riêng; đánh dấu từng phase để tách bootstrap khỏi pan/zoom.
- Stress zoom17+ với ranh và nhiều lớp; chạy 10–15 phút, nhiều chu kỳ và kiểm
  heap sau GC/DOM/decoded image, cache eviction, detached nodes.
- Quan sát request/response thực tế của các ảnh GIS ORB và fallback; không đổi
  routing gateway chỉ dựa lỗi của local khác cấu hình production.
- So byte thực và peak concurrent requests; phần này chưa đo được từ tổng event.
