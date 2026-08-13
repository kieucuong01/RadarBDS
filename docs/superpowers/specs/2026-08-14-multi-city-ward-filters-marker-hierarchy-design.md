# Multi-city Ward Filters and Map Marker Hierarchy Design

## Mục tiêu

1. Làm thứ bậc marker trên Maps dễ phân biệt bằng cả kích thước và màu sắc.
2. Cho phép người dùng chọn đồng thời nhiều phường thuộc nhiều thành phố, ví dụ Tân An (Thủ Dầu Một) và Mỹ Phước (Bến Cát), mà không mất lựa chọn khi chuyển tab thành phố.
3. Giữ nguyên contract API công khai dựa trên tham số `ward` lặp lại, giữ luồng signals-first và không làm phát sinh request theo từng marker hay từng phường.

## Marker Maps

Kích thước và màu hiệu lực:

| Độ chính xác | Bán kính | Viền | Màu viền | Màu nền |
|---|---:|---:|---|---|
| Chính xác (`exact`) | 6px | 2px | `#047857` | `#10b981` |
| Theo đường (`road`) | 6px | 2px | `#3730a3` | `#6366f1` |
| Theo khu vực/địa danh (`landmark`) | 7px | 2px | `#be123c` | `#fb7185` |
| Theo phường (`ward`) | 8px | 2px | `#b45309` | `#f59e0b` |

Màu trong chú giải phải khớp marker. Nhãn giá, diện tích, giá/m² và số tin không đổi kích thước hoặc quy tắc xuất hiện.

## Mô hình chọn khu vực

### Trạng thái giao diện

- Các nút thành phố là tab điều hướng danh sách phường, không còn đại diện duy nhất cho toàn bộ phạm vi lọc.
- Trạng thái chọn được lưu dưới dạng tập phường theo thành phố:

```js
{
  version: 2,
  activeCity: "BẾN CÁT",
  selections: {
    "THỦ DẦU MỘT": ["Tân An"],
    "BẾN CÁT": ["Mỹ Phước"]
  },
  mode: "custom"
}
```

- Chuyển tab thành phố chỉ thay danh sách đang hiển thị; không xóa lựa chọn của thành phố khác.
- Mỗi tab thành phố hiển thị badge số phường đang chọn tại thành phố đó. Tab không có lựa chọn không hiện badge.
- Dòng tổng kết hiển thị tổng số phường và số thành phố có lựa chọn, ví dụ `2 phường · 2 thành phố`.
- `Chọn tất cả` chỉ thêm toàn bộ phường của tab đang mở.
- `Bỏ chọn` chỉ xóa toàn bộ phường của tab đang mở.
- Tìm kiếm phường chỉ lọc danh sách của tab đang mở và không làm thay đổi lựa chọn.

### URL và request

- Phạm vi tùy chỉnh tiếp tục serialize thành tham số `ward` lặp lại:

```text
?ward=Tân+An&ward=Mỹ+Phước
```

- Khi các phường được chọn thuộc từ hai thành phố trở lên, không gửi `city` để tránh biểu diễn sai rằng toàn bộ phạm vi thuộc một thành phố.
- Khi phạm vi chỉ có một thành phố, có thể giữ `city=<thành phố>` để URL dễ đọc và tương thích deep link cũ.
- Khi người dùng chọn toàn bộ một thành phố và không chọn phường ở thành phố khác, URL có thể dùng `city=<thành phố>` mà không cần liệt kê tất cả phường.
- Khi không có phường nào được chọn, gửi `ward_mode=none`; không tự rơi về toàn bộ thành phố đang mở.
- Tất cả surface Săn Deal, Tin Rao, Counts, Dashboard, Market và Maps dùng cùng chuỗi query canonical.
- `ward` vẫn là multi-key được sắp xếp và loại trùng bởi `RadarFilterRuntime.canonicalize()`, nên cache key ổn định bất kể thứ tự người dùng chọn.

CITY_MAP hiện không có tên phường trùng giữa các thành phố. Backend hiện đã lọc theo danh sách `ward`, vì vậy V1 không thêm contract ghép cặp city/ward. Nếu CITY_MAP sau này có tên trùng, cần nâng API bằng khóa khu vực ghép cặp trước khi đưa phường trùng vào bộ lọc công khai.

## Tương thích trạng thái cũ

- Đổi khóa lưu thành payload version 2 nhưng vẫn đọc được `radar_area_scope_v1` version 1.
- State version 1 `city_all` được chuyển thành lựa chọn toàn bộ thành phố tương ứng.
- State version 1 `custom` được chuyển thành `selections[city] = wards`.
- Sau lần lưu thành công đầu tiên, ghi state version 2; không xóa state cũ trước khi việc chuyển đổi hợp lệ.
- Deep link cũ có một `city` và nhiều `ward` vẫn hoạt động.
- Deep link có nhiều `ward` thuộc nhiều thành phố được suy ra thành nhiều nhóm selection, thay vì chỉ kiểm tra tất cả ward theo thành phố đầu tiên.

## Bộ chọn khu vực ban đầu

- Draft của chooser dùng cùng mô hình version 2 với sidebar.
- Chuyển tab trong chooser không xóa draft ở thành phố khác.
- Nút áp dụng dùng toàn bộ selections; label tổng kết dùng số phường và số thành phố.
- Preset/toàn thành phố cũ vẫn tạo phạm vi một thành phố và thay thế draft hiện tại, đúng với hành vi preset rõ ràng.
- Đóng chooser không được âm thầm thay phạm vi đa thành phố đang có bằng toàn bộ thành phố tab hiện tại.

## Backend và cache

- Không đổi chữ ký public API và không thêm truy vấn DB mới.
- `get_base_filters()` tiếp tục đọc toàn bộ `ward`; `active_city` chỉ là metadata/fallback khi không có danh sách phường.
- Không mở rộng `CITY_MAP[active_city]` khi request đã có ít nhất một `ward`.
- Public cache tiếp tục dùng danh sách ward canonical và dataset version hiện tại.
- Luồng Signals giữ nguyên: một request `/api/signals` ngay sau filter ổn định, Counts chỉ chạy sau khi Signals hoàn tất, Dashboard không chạy trên nhánh Signals.

## Trợ năng và responsive

- Badge số lượng trên tab không làm giảm vùng bấm dưới 44px ở mobile.
- Checkbox và label phường tiếp tục điều khiển được bằng bàn phím.
- Tab thành phố cập nhật `aria-pressed`; summary thay đổi trong vùng có `aria-live` hiện có hoặc vùng status tương đương.
- Sidebar desktop và sheet mobile dùng cùng state, không có hai nguồn dữ liệu lựa chọn riêng.

## Kiểm thử

### Marker

- Exact và road cùng radius 6.
- Landmark radius 7, màu rose và khác exact.
- Ward radius 8.
- Chú giải dùng đúng màu landmark mới.
- Nhãn giá/count giữ nguyên contract.

### Bộ lọc

- Chọn Tân An, chuyển sang Bến Cát, chọn Mỹ Phước: cả hai vẫn selected và query có hai `ward`.
- Chọn tất cả/Bỏ chọn chỉ tác động tab đang mở.
- Badge từng thành phố và tổng kết toàn cục đúng.
- Multi-city query không chứa `city`; single-city query vẫn tương thích.
- `ward_mode=none` chỉ xuất hiện khi toàn bộ selections rỗng.
- Reload URL và reload từ localStorage phục hồi đúng selections.
- State version 1 `city_all` và `custom` chuyển sang version 2 đúng.
- Area chooser không làm mất selection đa thành phố.
- Maps nhận đúng cùng filter snapshot với feed.
- Không có request thừa hoặc stale response ghi đè khi đổi lựa chọn nhanh.

## Phát hành

- Cập nhật version asset JS/CSS để Cloudflare và trình duyệt nhận giao diện mới.
- Chạy test JS state/filter, test template/UI, Maps tests và các contract signals-first/cache liên quan.
- Browser smoke desktop và mobile với Tân An + Mỹ Phước, sau đó xác nhận URL, feed, count và Maps.
- Commit đúng file trong phạm vi, giữ nguyên `.playwright-cli/` không liên quan, push `main`, deploy và xác minh SHA/service/HTTP/CDN riêng biệt.
