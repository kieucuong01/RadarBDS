# REA 6.8.0: thử phân tích Guland Biên Hòa

Ngày 02/11/2026, theo yêu cầu cài và áp dụng REA cho bài toán ranh Đồng Nai cũ.

## Cài đặt thực tế

- npm `rea-agents@6.8.0`, MIT, repo `morluto/rea`.
- Node hệ thống 24.19.0 không đạt engines; cài `node@24.22.1` riêng.
- Thư mục: `C:/Users/ASUS/AppData/Local/Temp/radar-rea-tools/`.
- Node thực tế `v24.22.1`; CLI `--help` chạy thành công, nhận diện REA 6.8.0.
- Chưa đăng ký MCP hay thay đổi cấu hình Codex; CLI đã đủ cho phép thử.
  Thư mục Temp có thể bị hệ thống dọn; không phải dependency production.

Gọi CLI bằng Node tuyệt đối:

```powershell
$reaRoot = 'C:/Users/ASUS/AppData/Local/Temp/radar-rea-tools'
& "$reaRoot/node_modules/node/bin/node.exe" "$reaRoot/node_modules/rea-agents/scripts/rea.mjs" --help
```

## Phép thử đã chạy

Chrome riêng không đăng nhập, profile trong thư mục công cụ; CDP loopback
port 9337. Không sao chép cookie/storage từ Chrome cá nhân. Origin chỉ
`https://guland.vn`, trang `/soi-quy-hoach/dong-nai/thanh-pho-bien-hoa`.

REA `list-browser-targets`, `analyze-web-bundle`, `inspect-web-page` (UI/JSON
shapes), và một lần inspect lấy script sources đã chạy thành công. Không có
mutation vào website, không gọi API tải hàng loạt, không vượt HTTP 403.

Ignored evidence:

- `.local/rea-targets.json`
- `.local/rea-guland-bundle.json`
- `.local/rea-guland-page.json`
- `.local/rea-guland-sources.json`

## Phát hiện và giới hạn

REA phân tích 63 script, 0 parse failures, 336770 AST nodes, nhưng completeness
vẫn **partial**. Đợt inspect khác thấy 59 script; đây là hai cửa sổ quan sát,
không chứng minh source inventory cố định. Bundle evidence khoảng 75 KB.

Các endpoint candidate tự động gồm nhiều false positive từ Select2
`options.get(...)`, không phải HTTP request. Không dùng chúng làm API registry.

Đối chiếu script inline lớn đã capture: `$.ajax` POST tới
`https://guland.vn/get-bound-2` với `marker_lat`, `marker_lng`, `area`, `shape`,
`force_remap_id`, `force_hcm_bddc_id`, `province_id`. Luồng thành công đọc
`response.points` để dựng ranh chọn. Đây là bằng chứng tĩnh về lookup điểm/shape,
**không phải** bằng chứng trả nhiều polygon trong bbox. `shape` không tự chứng
minh API xuất hàng loạt; chưa thử và không sửa tham số để suy ra khả năng đó.

Không thấy `vectorGrid` trong script inline đã đối chiếu; nhiều lớp nền/QH/
giao thông là `L.tileLayer` PNG. Không thể suy từ đó mọi ranh đều raster hoặc
không có nguồn vector khác. Cần quan sát network lúc pan/zoom/click để kết luận.

Đợt passive network một giây không có request, `prior_activity_available=false`:
trang đã tải trước khi bật quan sát. **Không có runtime proof** của request
polygon hay batch endpoint trong đợt này. Không lấy kết quả tĩnh làm số liệu tải.

## Kết luận áp dụng

REA đã cài và chạy thật, hữu ích để thu script có provenance, lần call-site và
thu hẹp luồng cần quan sát. Chưa tìm được phương án batch miễn phí cho Biên Hòa;
chưa thay đổi 3 mẫu polygon đã thu hoặc provider/live Maps. Bước tiếp theo là
capture network trong lúc thực hiện một pan/zoom/click UI, xác định payload thực
tế; chỉ viết collector theo vùng nếu nguồn thực sự hỗ trợ và cho phép dùng.
