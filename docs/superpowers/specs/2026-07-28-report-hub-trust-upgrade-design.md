# Thiết kế nâng cấp trust-first cho `/bao-cao`

Ngày: 2026-07-28  
Trạng thái: Đã duyệt qua audit và yêu cầu “fix tuần tự”  
Phạm vi: hub `/bao-cao`, trang báo cáo tháng/phường, pipeline tạo snapshot báo cáo, form nhận tin và analytics liên quan

## 1. Mục tiêu

Nâng cấp cụm báo cáo để các số liệu phản ánh đúng hợp đồng dữ liệu hiện hành của Radar BDS, người đọc hiểu rõ phạm vi và thời điểm dữ liệu, còn các hành động chuyển đổi không làm lộ dữ liệu nhạy cảm. Giao diện phải dễ dùng trên mobile, có đường dẫn sớm sang dữ liệu đang hoạt động và có khả năng đo funnel mà không gửi PII.

Đợt này không thêm bản đồ, xuất PDF, lưu báo cáo cá nhân, mở rộng địa bàn hay thay đổi công thức định giá.

## 2. Vấn đề đã xác nhận

- Pipeline báo cáo đang đếm repost/duplicate như tin độc lập và dùng cờ legacy `is_hot`/`price_dropped` thay cho quality gate của sản phẩm.
- Median và các card “dưới giá” chưa cùng một hợp đồng canonical/quality/actionable với dashboard.
- Hub ghi phạm vi rộng hơn dữ liệu thực tế; Bến Cát chưa có báo cáo nhưng vẫn trông như một bộ lọc khả dụng.
- Bộ lọc không giữ trạng thái trên URL, chưa có kỳ báo cáo, card có nhiều điểm tab trùng nhau.
- CTA sang dashboard theo phường nằm quá sâu; người đọc dễ nhầm snapshot lịch sử với deal đang hoạt động.
- Chart thiếu mô tả thay thế; ảnh card ở cuối trang tải eager; card mobile quá dài; input 15.2px có nguy cơ iOS zoom.
- Form nhận tin không có `method`/`action`, nên khi JavaScript lỗi trình duyệt có thể gửi số điện thoại bằng GET.
- Analytics hiện chưa phân biệt rõ mở báo cáo, dùng bộ lọc, mở dashboard và mở listing.

## 3. Hợp đồng dữ liệu

### 3.1 Ba lớp số liệu

Mỗi snapshot báo cáo phải phân biệt:

1. `raw_listing_count`: số tin Facebook thu thập trong kỳ sau khi loại nguồn bị ẩn/blacklist.
2. `basis_count`: số mẫu canonical đủ chất lượng dùng tính thống kê.
3. `actionable_signal_count`: số mẫu vượt quality gate và signal gate hiện hành.

Không dùng một nhãn “tổng tin” cho cả ba khái niệm.

### 3.2 Mẫu canonical đủ chất lượng

Một hàng được dùng cho median, phân bố loại hình và nguồn cung hợp lệ khi:

- `source = 'facebook'`;
- nằm trong kỳ và đúng phạm vi;
- không bị ẩn hoặc blacklist;
- `duplicate_of_id IS NULL`;
- không có `possibly_duplicate`;
- không có `is_outlier`;
- không có `probably_sold`;
- có dữ liệu cần thiết cho chỉ số đang tính.

Các điều kiện phải được tập trung trong một service dùng chung, không sao chép rải rác giữa hai script.

### 3.3 Signal và card nổi bật

- Join đúng latest valuation bằng `LATEST_VALUATION_CTE`.
- Dùng `services.signal_quality.actionable_signal_sql()` và `actionable_listing_sql()`.
- Card nổi bật chỉ lấy canonical lot, đủ quality, đang actionable và sắp xếp theo MOS giảm dần, độ mới giảm dần.
- Không dùng riêng `is_hot`, `price_dropped` hoặc `mos_pct >= 5` để quyết định nội dung user-facing.
- Mọi link card đi qua `/listing/<id>`; template không nhận URL gốc hay số điện thoại.

### 3.4 Snapshot và minh bạch

Snapshot lưu:

- kỳ dữ liệu;
- ngày xuất bản/cập nhật;
- `raw_listing_count`, `basis_count`, `actionable_signal_count`;
- version hợp đồng dữ liệu;
- mô tả phương pháp bằng tiếng Việt, không có chuỗi debug.

Báo cáo đã xuất bản là snapshot theo thời điểm tạo, không tự đổi theo DB live. Trang phải nói rõ điều này và CTA sang dashboard phải ghi rõ đó là dữ liệu đang hoạt động.

## 4. Thiết kế backend

Tạo `services/monthly_report_data.py` làm boundary duy nhất cho:

- câu SQL base raw;
- câu SQL canonical quality;
- latest valuation/actionable signal;
- thống kê theo phường/loại hình/tháng;
- danh sách featured listing.

Hai script `generate_monthly_report.py` và `enhance_monthly_report_rich.py` chỉ định dạng payload từ service này. Service nhận connection và tham số ngày/phạm vi để có thể unit test bằng fixture.

Nếu dữ liệu thiếu trường cần tính, chỉ số đó trả `None`/không hiển thị; không nội suy hoặc gắn nhãn “0” gây hiểu nhầm.

## 5. Form lead fail-closed

Form có:

- `method="post"`;
- `action="/api/leads"`;
- hidden `return_path` chỉ chứa path nội bộ hiện tại;
- native `required`, `autocomplete="tel"`, `inputmode="tel"`.

Endpoint nhận cả JSON và form-encoded. JSON giữ response hiện hành. Form-encoded:

- dùng chung validation/service tạo lead;
- xác minh `return_path` là relative path bắt đầu bằng `/`, không bắt đầu `//`, không chứa scheme;
- redirect về path an toàn với `lead=success` hoặc `lead=error`, tuyệt đối không đưa số điện thoại/note vào URL;
- không log payload PII trong analytics.

JavaScript tiếp tục nâng cấp trải nghiệm bằng fetch, nhưng khi script lỗi form vẫn POST an toàn.

## 6. Hub `/bao-cao`

### 6.1 Phạm vi

- Tiêu đề/copy nói đúng phạm vi báo cáo hiện có.
- Thành phố có `count = 0` hiển thị “Sắp có” và không hoạt động như bộ lọc.
- Không ám chỉ đã phủ toàn Bình Dương khi mới có Thủ Dầu Một.

### 6.2 Bộ lọc

Các filter:

- địa bàn;
- phường;
- kỳ báo cáo;
- tìm kiếm.

Trạng thái đồng bộ vào query string bằng `history.replaceState`, phục hồi khi load và `popstate`. Chỉ dùng giá trị enum/slug/kỳ hợp lệ; analytics không gửi chuỗi tìm kiếm tự do.

### 6.3 Card và bàn phím

- Một card chỉ có một link tab chính.
- Thumbnail/decorative affordance không tạo tab stop trùng.
- Nút địa bàn dùng `aria-pressed`; nút không có dữ liệu dùng `disabled` và nhãn “Sắp có”.
- Báo cáo mới nhất không bị lặp lại trong danh sách archive.

## 7. Trang chi tiết báo cáo

- Thêm CTA gần hero: “Xem deal đang hoạt động tại [phường]”, URL gồm ward/city/date range/MOS phù hợp.
- CTA ghi rõ dashboard là dữ liệu hiện tại, báo cáo là snapshot lịch sử.
- Các chart có `role="img"` và `aria-label` mô tả; phần số liệu đã có bảng vẫn được giữ làm fallback. Chart không có bảng phải có tóm tắt text từ dữ liệu snapshot.
- Ảnh card featured dùng `loading="lazy"` và kích thước cố định để tránh layout shift.
- Mobile rút gọn spacing/chiều cao card, font control tối thiểu 16px, target tương tác tối thiểu 44px, không horizontal overflow.
- `published_at`/`data_as_of` dùng `<time datetime="...">`.

## 8. Analytics an toàn

Thêm các event:

- `report_filter_used`;
- `report_open`;
- `report_dashboard_click`;
- `report_listing_click`.

Context chỉ nhận các giá trị không nhạy cảm và có tập hữu hạn: `city`, `ward_slug`, `period`, `source_surface`, `listing_id`. Không gửi search query, số điện thoại, note, tiêu đề tin, URL gốc hoặc UTM có thể chứa PII trong các event mới.

Giữ các event cũ để không làm gãy dashboard tăng trưởng, nhưng CTA mới phải dùng event cụ thể.

## 9. Kiểm thử chấp nhận

### Logic/API

- Duplicate, `possibly_duplicate`, outlier, sold và hidden không vào `basis_count`.
- `raw_listing_count` vẫn phản ánh volume thu thập sau source visibility gate.
- Signal/featured phải đi qua latest valuation và actionable gate.
- Featured không có phone/original URL và link chỉ là `/listing/<id>`.
- Form fallback POST không bao giờ đặt phone vào URL; open redirect bị chặn.

### UI/UX

- Hub copy đúng coverage, filter kỳ hoạt động và URL phục hồi đúng.
- Một report card có một tab stop; city button có state accessible.
- CTA dashboard xuất hiện gần đầu trang và nói rõ dữ liệu hiện tại.
- Canvas có accessible name; ảnh cuối trang lazy.
- Viewport 375px và 390px không tràn ngang; form không iOS zoom.

### Phát hành

- Chạy targeted pytest, Python compile, JavaScript syntax.
- Regenerate báo cáo tháng 06/2026 bằng pipeline mới.
- Browser smoke guest trên desktop/mobile.
- Commit đúng scope, push, deploy production.
- Xác minh live `/bao-cao`, một báo cáo phường, lead form markup, CTA, redaction và event allowlist.

## 10. Rollback

Code và snapshot report nằm trong git nên rollback bằng commit trước. Không có migration schema. Nếu regenerate thất bại, giữ snapshot tốt gần nhất; không publish dữ liệu nửa chừng.
