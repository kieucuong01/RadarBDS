# Rà soát giá trị nhà đầu tư cá nhân — 05/10/2026

## Kết luận

Ưu tiên 80/20: làm cho các deal được ưu tiên có số liệu đúng, bằng chứng dễ hiểu và có thể xác minh/liên hệ được. Nền tảng đã có nhiều tính năng; phần đáng đầu tư tiếp theo là chất lượng quyết định và phản hồi từ thực tế.

Đề xuất tập trung một vài cụm Thủ Dầu Một/Bến Cát có dữ liệu và người hỗ trợ xác minh tốt. Chọn cụm sau khi có số liệu hiện tại; chưa có cơ sở chọn phường thắng cuộc hay ước lượng ROI.

## Phạm vi và giới hạn bằng chứng

- Checkout: `978056f0d882284a5f797840f4dfc9378f98a50f`. Rà soát tài liệu, cấu trúc, các luồng crawl/chuẩn hóa/định giá/chất lượng, feed/detail/comparables, lifecycle, lead CRM, watchlist, tracking và đọc chọn lọc Radar Ask/checkout/CI.
- Graphify CLI lỗi `uv trampoline failed to canonicalize script path`. Đã dùng traversal graph JSON để xác định quan hệ; graph cũ tại `bf712404d9ce0a24fe32e5671cf281905daf6892`, không dùng làm bằng chứng runtime hiện tại. Đối chiếu các kết luận quan trọng bằng source.
- Đã mở homepage và detail #79846 bằng trình duyệt public, đọc nguyên văn và dữ liệu hiển thị. Đây là smoke phạm vi hẹp, không phải kiểm tra toàn bộ mobile/auth/production.
- 142 test Python về valuation/trace/signal quality/data trust/comparables qua; 132 test extractor/listing reports/Radar Ask evaluation qua. 10 test JavaScript về scope/filter/card/comparables/detail actions qua.
- Nhóm 132 test ban đầu gặp 4 lỗi setup vì quyền thư mục temp Windows; chạy lại bằng thư mục temp riêng được phép ghi và qua toàn bộ. Không coi lỗi setup đó là lỗi sản phẩm.
- `data-trust-audit --json --limit 50` chưa xác minh được: kết nối local `127.0.0.1:15432/radar_bds` timeout, `checks=[]`. Không có số liệu freshness/parity/coverage DB hiện tại và không audit DB production.
- Chưa chạy full suite, kiểm thử thanh toán thật, provider AI thật, cảnh báo Telegram thật, tải production hay khôi phục backup. Không kết luận các luồng này thành công hoặc hỏng từ lần rà soát này.
- Không sửa code, không sửa dữ liệu, không deploy. Chỉ thêm tài liệu này.

## Những gì nên giữ

1. Pipeline xác định, Facebook chính/Guland phụ, dedup và giá lịch sử có quy tắc rõ.
2. Cổng actionable signal và ngưỡng MOS public 15%; có cảnh báo mẫu mỏng.
3. Feed compact, thumbnail, read model, cache theo tier, pool giới hạn và chống phản hồi cũ trên browser.
4. Bản đồ có nhãn độ chính xác: detail #79846 ghi rõ marker theo đường, không phải đúng thửa.
5. Có comparables, memo, favorites, watchlist, báo xấu và CRM. Nên hoàn thiện các luồng này thay vì xây lại.

## Phát hiện chính

### A. Bất nhất diện tích ở signal đang hiển thị — đã quan sát live, tái hiện local

https://radarbds.vn/listing/79846 ghi nguyên văn `DT 5.5x30 tc 60m tdt 148 m`, nhưng feed/detail dùng 165 m², giá rao 1,9 tỷ và khoảng 11,5 triệu/m². Không thể xác nhận diện tích thật nếu chưa đối chiếu giấy tờ. Nếu dùng 148 m² thì riêng giá/m² là khoảng 12,84 triệu; phải chạy lại định giá mới biết MOS đúng, không sửa MOS bằng tỷ lệ thủ công.

Tái hiện trong bộ nhớ: `declared_total_area()` chưa nhận chuỗi này; `extract_area()` nhận 148. Tuy nhiên `normalize_record()` với structured area 165 giữ 165 và ghi provenance `source_structured`. Vì vậy chỉ bổ sung regex chưa chắc đủ: cần kiểm tra thứ tự ưu tiên và xung đột structured/text.

Nguồn: `cleansing/extraction_integrity.py:91`, `cleansing/normalizer.py:589`, `cleansing/feature_extractor.py:2160`. Kết quả tái hiện không chứng minh toàn bộ lịch sử nhập của bản ghi production.

### B. Giá tham khảo đang dễ được hiểu mạnh hơn bằng chứng

Feed ghi `THỰC TẾ` cho giá rao và hiển thị hai định giá thành khoảng. `signal_card.js:112` ghép giá của model old/new; đây không phải khoảng tin cậy thống kê đã được hiệu chỉnh. Detail mẫu hiển thị khoảng theo thứ tự ngược với feed.

Model học từ tin rao; chưa tìm thấy đánh giá giữ riêng tập theo thời gian hoặc theo lô trong các module định giá đã rà soát. Test tính toán đúng không chứng minh giá giao dịch hay tỷ lệ deal thực sự đáng mua.

Đề xuất đổi `THỰC TẾ` thành `GIÁ RAO`; giải thích `Rẻ hơn X%` là so với giá tham khảo của mô hình. Hai model cần nhãn rõ hoặc chọn một model public bằng đánh giá; không trình bày độ chênh hai model như độ chắc chắn.

### C. Tình trạng nguồn và giao dịch cần tách rõ

`analytics/lifecycle.py` có source check active/removed/unreachable, nhưng logic velocity và mô tả còn dùng tin biến mất nhanh để suy ra likely sold/fast sold. Không thấy lại hoặc gỡ tin có thể do nhiều nguyên nhân. Chỉ nên trình bày như chỉ báo vòng đời tin, chưa phải thanh khoản/giao dịch xác nhận.

Quy tắc `has_so` mặc định true cũng không tương đương pháp lý được xác minh. Giữ riêng thông tin người đăng, suy luận parser và xác minh có bằng chứng.

### D. Đã có điểm bắt đầu cho vòng phản hồi, cần hoàn thiện vận hành

`services/admin_leads.py:15` có `new/called/viewing/deposit/cancelled`; `:241` có cập nhật và audit trạng thái. Không cần xây CRM mới. Nên bổ sung người phụ trách, hạn xử lý, lý do mất cơ hội, kết quả xác nhận giá/vị trí/còn bán và thời điểm xác nhận.

Tracking đã có events và phân biệt nguồn/lead; cần đo kết quả trên lead thật, không cộng view/click/submit/row thành một số lead. Chưa có bằng chứng từ lần rà soát này về tỷ lệ chuyển đổi hay tốc độ phản hồi production.

### E. Comparables và memo cần gần quyết định hơn

`services/listing_comparables.py:40` đã so cùng phường, loại tài sản và khoảng diện tích. Bộ lọc còn bám giá của chính tin mục tiêu, chấp nhận road tier null và không thấy giới hạn tuổi tin hay đối chiếu thổ cư trực tiếp ở truy vấn này. Tin mục tiêu sai/rẻ bất thường có thể kéo lệch nhóm được hiển thị. Đây là rủi ro thiết kế, chưa đo mức lệch trên DB hiện tại.

`services/advisory_memo.py:169` có giá gợi ý từ các hệ số cố định. Nên trình bày là kịch bản có giả định, gắn với comps và dữ liệu xác nhận, thay vì làm người dùng hiểu đó là giá chốt đã được chứng minh.

## Thứ tự 80/20 đề xuất

| Ưu tiên | Việc cần làm | Giá trị | Tiêu chí hoàn thành |
|---|---|---|---|
| 1 | QC các signal đầu feed và lead đang được hỏi; sửa xung đột giá/diện tích/thổ cư/vị trí | Giảm cuộc gọi và chuyến đi vì dữ liệu sai | Review tối đa 20–30 deal ưu tiên mỗi đợt; có nhãn đúng/sai/chưa xác minh; regression cho các lỗi mới; sửa dữ liệu có phạm vi rồi kiểm tra lại feed/detail/counts |
| 2 | Hộp bằng chứng ngắn ngay trên detail | Người dùng biết vì sao đáng xem và còn thiếu gì | Hiện giá rao, mẫu/thời gian định giá, 3–5 comps cùng phân khúc, nguồn/provenance, độ chính xác vị trí, tình trạng pháp lý và lần xác minh gần nhất |
| 3 | Khép vòng ráp mối qua CRM sẵn có | Biến signal thành cuộc gọi và xem đất hữu ích | Lead có người phụ trách, hạn phản hồi, kết quả xác minh và lý do đóng; đo từ lead → liên lạc được → xem đất → đặt cọc |
| 4 | Chọn model public bằng benchmark và phản hồi người thật | Tránh ưu tiên MOS cao vì mô hình lệch | Tập kiểm tra không lẫn cùng lô vào train/test; chia theo thời gian/khu/loại; đo lỗi giá rao riêng với độ chính xác top-deal được người thật xác minh |
| 5 | Shortlist và thông báo theo nhu cầu trên favorites/watchlist sẵn có | Tiết kiệm việc phải mở app và lọc lại | Theo ngân sách/khu/loại; cập nhật giảm giá hoặc trạng thái có ý nghĩa; chống lặp; đo người quay lại và deal được mở/xác minh |

Mức 20–30 deal và 3–5 comps là giới hạn công việc đề xuất, không phải số liệu hiện tại hay cam kết tác động. Hạn phản hồi phải phù hợp năng lực thực tế, có thể bắt đầu bằng SLA trong ngày làm việc rồi đo.

## Lộ trình ngắn

- Đợt 1: đo chất lượng top-deal, xử lý case diện tích, sửa nhãn giá/định giá, đưa việc xác minh còn bán vào xử lý lead.
- Đợt 2: hộp bằng chứng, cải thiện comps, hoàn thiện trạng thái CRM và báo cáo kết quả.
- Đợt 3: benchmark model, shortlist/watchlist; lấy phản hồi 5–10 người dùng đúng phân khúc trước khi mở rộng.

Đây là thứ tự triển khai, chưa phải dự toán thời gian cố định. Phải có DB/runtime baseline trước khi xác định khối lượng sửa dữ liệu.

## Chưa ưu tiên

- Mở rộng địa bàn hoặc số lượng tin trước khi đo chất lượng cụm đang phục vụ.
- Thêm chỉ báo, dashboard, chatbot/LLM mới; Radar Ask hiện đã có validator/evaluation, nên chứng minh hữu ích trên câu hỏi thật trước.
- OCR/pháp lý tự động quy mô lớn; bắt đầu checklist và xác minh có người cho deal được quan tâm.
- Tăng hạ tầng hay refactor lớn chỉ để gọn code. Bảo toàn contract cache/redaction và thực hiện kiểm tra vận hành định kỳ; bằng chứng tải cũ không thay cho kiểm tra hiện tại.
- Tăng nội dung SEO chung chung. Dùng trang khu vực/báo cáo hiện có dẫn vào đúng bộ lọc, đo lead có kết quả.

## Chỉ số nên dùng

Chỉ số chính: số deal mỗi tuần được người dùng/người xử lý xác nhận còn bán, đúng thông tin trọng yếu và đáng đi xem. Đây là chỉ số đề xuất, cần định nghĩa rõ người xác nhận và bằng chứng.

Theo dõi thêm: lỗi trọng yếu trên top-deal; phần trăm lead liên hệ được; thời gian phản hồi; tỷ lệ xem đất trên lead đủ điều kiện; người quay lại; lý do bỏ deal. Luôn công bố tử số/mẫu số/thời gian/khu vực, không suy hiệu quả từ tổng tin hoặc tổng bài viết.

## Bảo trì cần làm cùng lúc, không thành dự án lớn

- Khôi phục khả năng audit local/test DB rồi chạy data-trust/parity. Production audit riêng theo runbook; không coi timeout local là sự cố production.
- Sửa tài liệu mâu thuẫn: `docs/agent_playbook.md` còn nói mặc định PostgreSQL 18/5432, trong khi AGENTS/dev_commands dùng portable 17/15432; product_rules còn ghi dashboard refresh trên Signals path trái contract AGENTS/filter_runtime.
- Refresh graph sau thay đổi code; graph tháng 8 không bao phủ đủ các module mới.
- Theo dõi crawl lag, lead pending, lỗi alert, cache/private response và kiểm tra restore backup theo quy trình hiện có.
