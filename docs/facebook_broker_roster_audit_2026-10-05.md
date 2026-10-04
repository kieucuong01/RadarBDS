# Kiểm tra danh sách môi giới Facebook — 2026-10-05

## Phạm vi và bằng chứng

- Trang production: https://radarbds.vn/admin/facebook-crawl?view=brokers, đọc bằng phiên admin đang mở và làm mới màn hình.
- Production revision: `978056f0d882284a5f797840f4dfc9378f98a50f`.
- Kiểm tra lúc khoảng 04:00 ngày 05/10/2026, UTC+7.
- DB: SELECT trong giao dịch read-only, statement timeout 15 giây. Không crawl thêm, không sửa dữ liệu, cấu hình hoặc triển khai.
- Graphify xác nhận luồng `facebook_profile_stats()` → `facebook_profile_data_quality()` / `facebook_profile_activity()`; kết luận quan trọng được đối chiếu source và DB production.
- Roster có 47 môi giới, 45 đang bật. 11 dòng hiện Chưa đủ mẫu; 9 dòng có đủ dữ liệu lịch sử, 2 dòng thực sự có dưới 5 bài.

## P1 — Tập mẫu toàn nguồn làm mất thống kê từng môi giới

`services/admin_quality.py:365` lấy 3.000 raw Facebook mới nhất toàn nguồn, rồi mới lọc profile. `facebook_profile_data_quality()` trả Chưa đủ mẫu nếu có dưới 5 dòng.

DB có 30.667 raw Facebook. Cửa sổ 3.000 bài hiện bắt đầu ở `2026-09-21 11:06:06.520127+07`. Môi giới có dữ liệu cũ hoặc ít bài mới bị mất mẫu dù lịch sử vẫn còn đầy đủ.

| Môi giới | Raw lịch sử | Mẫu đang tính | Mẫu kiểm chứng riêng | Điểm tính lại |
|---|---:|---:|---:|---:|
| Hoàng Mỹ Bđs | 332 | 0 | 100 | 97 |
| Nhà Đất Dĩ An | 325 | 0 | 100 | 97 |
| Vu Nguyen | 179 | 1 | 100 | 93 |
| Nhà Đất Ngọc Huyền | 248 | 0 | 100 | 86 |
| Phan Gia Bảo Hưng | 20 | 2 | 20 | 95 |
| My bds Thanh | 501 | 0 | 100 | 92 |
| Đinh Lương | 230 | 0 | 100 | 90 |
| Đỗ Phương | 2.018 | 0 | 100 | 88 |
| Đàm Hạ | 244 | 2 | 100 | 91 |
| Phương Cúc, đã tắt | 1 | 0 | 1 | Chưa đủ mẫu |
| Thao Pham, đã tắt | 4 | 0 | 4 | Chưa đủ mẫu |

Điểm kiểm chứng dùng cùng công thức hiện hành trên tối đa 100 raw mới nhất **riêng từng môi giới** và dữ liệu listing/valuation/ảnh liên quan. Đây là kiểm chứng lỗi chọn mẫu, không phải điểm mới đã được lưu, cũng không chứng minh nguồn đang hoạt động gần đây.

Hướng sửa: tách aggregate lịch sử (tổng bài, thời điểm lưu bài mới nhất) khỏi mẫu chất lượng có giới hạn theo từng profile. Chỉ join listing/ảnh/valuation sau khi giới hạn mẫu. Chọn giới hạn, cách lấy mẫu và index theo EXPLAIN/đo thời gian; không chỉ tăng giới hạn toàn nguồn hoặc bỏ mọi giới hạn. Khi dùng dữ liệu cũ phải ghi rõ ngày mẫu gần nhất.

## P1 — Lần crawl cuối không phải lịch sử chạy crawler

`services/admin_quality.py:451` lấy timestamp của raw trong cửa sổ trên. `static/js/admin/facebook-crawl.js:855` biến null thành Chưa crawl.

Ngay cả khi sửa cửa sổ, raw timestamp chỉ thể hiện lần lưu/cập nhật bài. Một lần chạy không có bài mới, toàn bài trùng, không trả bài hoặc lỗi không được thể hiện đúng qua timestamp này. Ví dụ Hoàng Mỹ có 332 bài, raw mới nhất 08/09, nhưng UI đang ghi Chưa crawl.

Hướng sửa: hiển thị riêng lần thử crawl gần nhất + kết quả, lần thành công gần nhất, và lần nhận bài mới nhất. Manual job có `admin_jobs`; daily batch cần ghi kết quả từng profile. Dữ liệu legacy không có log thì ghi rõ có lịch sử bài nhưng chưa có lịch sử lần chạy, không suy luận Chưa crawl.

## P2 — Chất lượng thiếu giải thích và cảnh báo

`static/js/admin/facebook-crawl.js:187` gộp mọi score null thành Chưa đủ mẫu; bảng chỉ hiển thị nhãn và điểm, bỏ qua sample_size và reasons.

- Hiển thị N mẫu, thời điểm mẫu, tổng bài lịch sử và lý do.
- Tách chưa có dữ liệu, dưới 5 mẫu, mẫu cũ, chưa xử lý và lỗi thống kê.
- `services/admin_quality.py:438` nuốt lỗi DB và trả thống kê rỗng: lỗi truy vấn có thể trông giống Chưa crawl. Cần log lỗi và trạng thái thống kê không khả dụng. Đây là rủi ro từ code, chưa có bằng chứng lỗi DB trong lần kiểm tra này.
- Nhãn Dữ liệu sạch phản ánh độ đầy đủ trường hơn là không có lỗi. Mẫu riêng của Đỗ Phương vẫn đạt 88/100 dù 22% dòng có cờ parse nghiêm trọng. Nên giữ cảnh báo riêng hoặc đổi cách gọi nhãn; không coi điểm cao là chứng nhận chất lượng tất cả bài.

## P2 — Nhịp đăng đang đo nhịp nhập dữ liệu

`services/admin_quality.py:212` dùng crawled_at cho posts_7d/14d/30d và active_days. Một lần crawl đầu nhập hàng trăm bài cũ có thể thành Nhịp cao, dù bài được đăng ở nhiều thời điểm trước đó.

Hướng sửa: dùng posted_at/date_raw đã parse cho nhịp đăng; dữ liệu không có ngày đăng phải hiển thị độ phủ/thiếu dữ liệu. Nếu giữ metric hiện tại thì đổi tên thành bài thu thập để tránh hiểu sai. Production có date_raw trong cả 3.000 raw đang lấy mẫu.

## P2 — Trạng thái vận hành và ngày địa phương

- `static/js/admin/facebook-crawl.js:267`: Cần chú ý = đang bật và (đến lịch OR điểm thấp/không có điểm). Vì vậy số 40 hiện tại không có nghĩa 40 nguồn lỗi. Tách Đến lịch khỏi Có vấn đề; nguồn không đủ mẫu có thể là một nhóm riêng.
- `services/admin_quality.py:577` và `crawler/facebook_apify.py:68` dùng ngày UTC. Lúc kiểm tra đã là 05/10 UTC+7 nhưng UTC còn 04/10; sau làm mới vẫn thấy Đến lịch hôm nay 2026-10-04. Cần một timezone nghiệp vụ thống nhất giữa UI và scheduled crawler.
- `static/js/admin/facebook-crawl.js:834` ghi daily_limit là bài/ngày dù lịch 3 hoặc 7 ngày/lần. Crawler dùng giới hạn mỗi lần; nên ghi tối đa N bài/lần. range_days chỉ được áp dụng khi chạy mode range, nên kế hoạch không nên ngụ ý daily luôn lấy đúng số ngày này.

## Rủi ro job từ source, chưa chứng minh incident

`cli/crawlers.py` trả crawl_partial/errors khi thiếu quota và có profile chưa được thử. `app.py:741` vẫn gọi reporter.succeed sau khi nhận crawl_stats, không tách trạng thái partial. Nên hiển thị hoàn tất một phần, số profile chưa chạy và lý do; dữ liệu đã nhập vẫn được giữ nguyên.

## Thứ tự đề xuất và kiểm chứng khi sửa

1. Sửa chọn mẫu theo môi giới và metadata lịch sử; hiển thị số mẫu + freshness. Không cần crawl lại 9 nguồn chỉ để chữa lỗi nhãn.
2. Tách kết quả từng lần chạy, lỗi thống kê và cảnh báo parse.
3. Sửa metric ngày đăng, ngày nghiệp vụ, bộ đếm chú ý và wording giới hạn.

Kiểm chứng cần có: nguồn có hơn 5 bài cũ vẫn có điểm khi nguồn khác nhập thêm 3.000 bài; nguồn có 1–4 bài vẫn thiếu mẫu; lần chạy không có bài mới vẫn cập nhật lịch sử chạy; lỗi DB không biến thành Chưa crawl; full crawl bài cũ không làm tăng nhịp đăng hôm nay; ca 00:00–07:00 UTC+7; chi phí truy vấn bị giới hạn trước các join ảnh/valuation. Giữ auth admin và phạm vi cache hiện hành.

## Bản sửa local sau kiểm tra

Đã triển khai bản sửa trong workspace, chưa commit/push/deploy. Các số dòng ở phần chẩn đoán phía trên tham chiếu revision production ban đầu.

- Tách tổng bài lịch sử khỏi mẫu chất lượng; lấy tối đa 100 raw mới nhất riêng từng profile (cấu hình được trong khoảng 5–200). Chỉ join listing, ảnh và valuation trên tập mẫu này. Profile số, mobile URL và nguồn actor input được đối chiếu về cùng danh tính.
- Chỉ chấm điểm bài đã chuẩn hóa; hiển thị riêng chưa có bài, thiếu mẫu, đang chờ xử lý và lỗi thống kê. Hiển thị số mẫu/tổng bài, ngày mẫu, mẫu cũ hơn 30 ngày và cờ parse nghiêm trọng. Điểm cao có từ 15% cờ nghiêm trọng trở lên hiện Cần kiểm tra lỗi parse.
- Đọc lịch sử từ `admin_jobs` và `crawl_run_progress`; ghi kết quả từng profile đã thực sự được thử, kể cả lần thành công không nhập bài mới. Profile chưa được thử do hết quota không được ghi như đã crawl. Dữ liệu legacy không có log hiện Chưa có log lần chạy cùng thời điểm nhận bài gần nhất.
- Đo nhịp đăng bằng ngày đăng bài; bài thiếu ngày không dùng ngày import thay thế. Ngày lịch crawl thống nhất UTC+7. Cần chú ý tách khỏi Đến lịch; giới hạn ghi bài/lần, cửa sổ ngày ghi rõ chỉ cho chế độ range.
- Job thiếu quota hiện Hoàn tất một phần; roster được tải lại sau khi job kết thúc. Giữ nguyên schema terminal status của job để tương thích.

## Kiểm chứng bản sửa

- Chạy trực tiếp hàm sửa trên DB production trong giao dịch read-only, không ghi file code hay dữ liệu lên VPS: 47 profile thống kê thành công, cả 9 trường hợp thiếu mẫu sai được giải quyết; chỉ Phương Cúc (1 bài) và Thao Pham (4 bài) vẫn thiếu mẫu đúng. Không cần crawl lại để khôi phục điểm của 9 nguồn này.
- Chi phí lần đo cuối khoảng 6,043 giây cho 47 profile/30.667 raw, gồm đọc lịch sử và mẫu. Đây là truy vấn chưa có cache; cần theo dõi độ trễ khi triển khai và khi dữ liệu tăng. Bản sửa không thêm index/migration.
- 147 test Python liên quan pass trên PostgreSQL test, gồm ca 3.100 bài mới của nguồn khác không xóa mẫu cũ, mẫu giới hạn riêng nguồn, bài chưa chuẩn hóa, ngày UTC+7, lịch sử crawl 0 bài và lỗi an toàn. Hai bộ test JavaScript pass; Python compile, JavaScript syntax và `git diff --check` pass.
- Full suite không thu thập được trên Windows vì `tests/test_rb_gemini_page_image.py` và `tests/test_rb_page_news_workflow.py` phụ thuộc `fcntl`. Chưa có kết quả full suite Ubuntu/CI cho bản sửa này.
- Preview local dùng snapshot thống kê production đã kiểm chứng tìm kiếm, số mẫu/lịch sử và cảnh báo Đỗ Phương (100 mẫu/2.018 bài, 88 điểm, 22% cờ parse), hiển thị ngày Việt Nam và bộ đếm Cần chú ý tách khỏi Đến lịch. Không có console warning/error trong phiên kiểm tra. Phân tích trùng nguồn trong preview dùng fixture rỗng và không phải bằng chứng runtime của tính năng đó.

Giới hạn: không thể tái dựng các lần daily crawl cũ không có log theo profile; lịch sử đầy đủ hơn sẽ được ghi từ lần chạy tiếp theo sau deploy. Chưa xác nhận endpoint/giao diện production đã dùng bản sửa.
