# Handoff: Hermes SEO Radar BDS hằng ngày

Ngày cập nhật: 15/10/2026 · Múi giờ: Asia/Bangkok (UTC+7).

## Kiểm tra release từ 16/10/2026

Người dùng đã yêu cầu commit, push và deploy phần tích hợp. Trạng thái local-only
bên dưới mô tả lần bàn giao ngày 15/10, không thay cho trạng thái release hiện tại.
Hermes phải kiểm tra SHA đang chạy, file code và URL live theo cổng sẵn sàng.
Sau release được kiểm chứng, dùng tài liệu trong repo production; snapshot ngày
15/10 có thể được đối chiếu với `release_verified.json` cùng thư mục.

Release này bảo toàn bốn chỉnh sửa social riêng trên VPS. Hai file workflow/test
trùng release được ghép và test trước; hai file browser/image giữ nội dung gốc.
Bản sao, checksum, patch và bản ghép nằm ở
`/var/tmp/radar-hot-topics-preserve-20261016/`. Không xóa bản sao hoặc áp lại
nguyên file cũ lên code mới. Production có override news-first và
`reader_cta_mode=source_only`; khi có yêu cầu bảo trì social tiếp theo, đọc diff
thực tế thay vì coi nhánh Git sạch là toàn bộ hành vi đang chạy.

## Trạng thái bàn giao

- Người dùng sẽ dùng Hermes trên VPS để vận hành SEO hằng ngày.
- Chiến lược đã thống nhất: một sự kiện/ý định đọc → một bài web chính → các bản video/Facebook cùng nguồn.
- Phần tích hợp Chủ đề nóng đã làm và kiểm tra local: 4 bài pilot; Bà Điểm có YouTube Short và post Facebook cùng sự kiện; 105 test web/SEO, 36 test social Linux đã qua.
- Tại thời điểm bàn giao, thay đổi còn ở nhánh local `codex/hot-topic-articles`, chưa commit/push/deploy. Handoff này không phải bằng chứng tính năng đã chạy production.
- VPS đang có thay đổi riêng ở `scripts/browser_use_page_post.py`, `scripts/rb_gemini_page_image.py`, `scripts/rb_page_news_workflow.py`, `tests/test_rb_page_news_workflow.py`. Kiểm tra lại trước triển khai; không ghi đè, reset hoặc stash cả repo.
- Việc lưu handoff không tạo cron mới, không đổi prompt/lịch cron hiện có và không đăng bài social.

## Tài liệu cần đọc

1. `AGENTS.md`, `docs/README.md`.
2. `docs/daily_seo_publisher.md` — runbook xuất bản hằng ngày.
3. `docs/radar_bds_hot_topics_content_strategy.md` — chiến lược tin nguồn/video/social.
4. `docs/social/news-workflow.md` — hợp đồng nguồn, bằng chứng và queue news.
5. `docs/radar_bds_90_day_seo_roadmap.md` — cụm nội dung và bài dữ liệu.
6. `docs/operations.md` khi cần release/rollback.

Bản handoff độc lập trên VPS nằm tại `/var/tmp/radar-bds-seo-handoff/2026-10-15/`.
Đây là vùng snapshot bàn giao; repo đã phát hành mới là nơi lưu quy trình lâu dài. Các tài liệu ở đó là snapshot; sau khi release thành công, ưu tiên tài liệu trong
checkout tương ứng với SHA thực tế đã deploy.

## Cổng sẵn sàng trước lần chạy đầu

Kiểm tra checkout và SHA, file `config/seo_hot_topic_articles.py`,
`services/news_editorial.py`, metadata section/event/source trong context helper,
và bài pilot trên web thực tế. Có file local hoặc HTTP 200 của một trang khác
không đủ chứng minh tính năng đã deploy.

Nếu code mới chưa được phát hành, báo `LOCAL_ONLY_RELEASE_PENDING` kèm các file
còn thiếu. Không tự dựng lại chức năng, bỏ cổng nguồn hoặc sửa trực tiếp production
để né bước release. Các tác vụ SEO cũ độc lập vẫn theo runbook cũ nếu được giao.

## Luồng mỗi ngày

### 1. Đối chiếu trạng thái

- Kiểm tra cờ STOP, sức khỏe web, SHA deploy, git status, lịch sử bài và sitemap.
- Đọc inventory bài, queue nguồn và lịch sử post/video đã xác minh. State bất nhất
  thì hòa giải trước; không suy từ file render thành đã đăng.
- Giữ lịch hiện hành. Định hướng là 1 bài SEO mới/ngày nếu không có blocker thật,
  đạt cổng chất lượng và không trùng ý định; bài Chủ đề nóng dùng slot này, không
  cộng thêm một quota mới. Không tạo bài yếu để đủ số lượng.

Context dữ liệu (lệnh có sẵn, chạy đúng tài khoản/quyền theo runbook):

```bash
sudo -u radar /opt/radar-bds/.venv/bin/python \
  /opt/radar-bds/current/scripts/radar_daily_seo_context.py --days 14 --limit 8
```

Discovery tin nguồn có sẵn, chạy trong checkout làm việc, lưu output ngoài Git:

```bash
/opt/radar-bds/.venv/bin/python scripts/rb_page_news_discovery.py \
  --out /path/to/writable-runtime/news-report.json --limit 12
/opt/radar-bds/.venv/bin/python scripts/rb_page_news_workflow.py plan \
  --report /path/to/writable-runtime/news-report.json
```

`/path/to/writable-runtime` là chỗ phải thay bằng thư mục runtime được tài khoản
Hermes phép ghi; không dùng nguyên placeholder. Bước discovery/plan không đăng bài.

### 2. Chọn một sự kiện hoặc bài dữ liệu phù hợp

- Ưu tiên tin liên quan Bình Dương, Thủ Dầu Một, Bến Cát/Mỹ Phước; tin liên vùng
  ghi đúng địa bàn, không tự gán ảnh hưởng tới từng phường.
- Tái sử dụng nguồn đã chọn làm short/post nếu có góc đọc sâu hữu ích.
- Kiểm tra trùng theo event key, URL nguồn đã bỏ tracking, chủ đề và ý định đọc.
  Cùng một tin được nhiều báo đăng không tạo nhiều bài Radar.
- Nếu đã có bài cùng ý định, cập nhật/link lại bài đó; chọn sự kiện khác cho slot
  bài mới. Refresh có giá trị nhưng không giả thành một URL mới.
- Chọn theo rubric phù hợp: bài dữ liệu dùng roadmap; news dùng chiến lược Chủ đề
  nóng. Ngưỡng đề xuất ≥75/100 và cổng nguồn bắt buộc; điểm không bù được thiếu nguồn.

### 3. Kiểm chứng và viết

Đọc `docs/news_editorial_quality.md`: dùng content-strategy, copywriting,
copy-editing và seo-audit của project. Bản explainer phải có phân tích cụ thể,
bảng/ví dụ áp dụng và hình có ích được ghi nguồn. Không chỉ kéo dài tin báo;
ảnh AI phải có caption minh họa, không thành ảnh dự án hay hiện trường.

- Đọc nguồn gốc và ghi ngày nguồn, ngày sự kiện, ngày biên tập riêng.
- Khẳng định trọng yếu về phê duyệt/quy hoạch/pháp lý/khởi công/tài chính cần nguồn
  chính thức hỗ trợ. Thiếu thì bỏ khẳng định chưa kiểm chứng hoặc giữ nháp.
- Bài phải có giá trị thêm: bối cảnh, phạm vi, mốc, câu hỏi người mua và điều chưa
  thể kết luận. Không chỉ diễn đạt lại tin báo.
- Số liệu Radar chỉ lấy production có phạm vi, thời điểm, loại tài sản và mẫu.
  Giá rao không phải giá giao dịch. Không ép bảng giá vào bài thiếu dữ liệu.
- Không biến tin hạ tầng thành bảo đảm tăng giá, pháp lý hoặc lợi nhuận.
- Lưu bài news trong `config/seo_hot_topic_articles.py`; dùng đủ cấu trúc bài hiện
  có và metadata `news` trong `docs/daily_seo_publisher.md`.
- Dùng event key ổn định theo sự kiện; thêm nguồn không đổi event key. `news.status`
  là `draft` tới khi đã biên tập đủ; `published` chỉ làm công khai sau release.

### 4. Kiểm tra và xuất bản web

- Làm trong checkout làm việc, giữ nguyên các file không thuộc nhiệm vụ.
- Chạy test tập trung nội dung/hub/sitemap và syntax cho file đã sửa. Test social
  dùng Linux vì khóa file `fcntl`; không gọi browser publish để “test”.
- Commit/push các file được chọn và release bằng luồng deploy/rollback được cho
  phép trong operations. Không sửa trực tiếp checkout live để thay quy trình.
- Kiểm chứng URL bài và Chủ đề nóng: HTTP, nội dung render, nguồn/ngày/trạng thái,
  canonical, breadcrumb, NewsArticle/Article, sitemap và CTA đúng phạm vi.
- Tin ngoài chưa có bài Radar vẫn dẫn báo gốc; khi có bài, thẻ chính mở bài Radar
  và giữ link nguồn. Bài news không rơi vào kho Tin từ dữ liệu Radar.

### 5. Nối video và Facebook

Kênh người dùng xác nhận:

- YouTube: https://www.youtube.com/@radarbds-vn — danh sách Shorts tại `/shorts`.
- Facebook Reels: https://www.facebook.com/radarbdsvn/reels/.
- Facebook Page: https://www.facebook.com/radarbdsvn/.

Đối chiếu tiêu đề, nội dung/mô tả, nguồn và thời điểm của từng video/post với
sự kiện trước khi lưu permalink. Không gắn link trang kênh thay permalink video,
không đoán ID và không đánh dấu `verified: true` từ một bản nháp hoặc file MP4.
Video minh họa phải giữ chú thích minh họa, không thành ảnh hiện trường.

Với nội dung mới: web đã kiểm chứng → prepare queue → kiểm tra caption/nguồn/ảnh
→ approve stamp → publisher hiện hành nếu chế độ đăng đã được bật cho nhiệm vụ.
Nguồn lead khớp bài news thì workflow chọn bài đó làm đích đọc. Bài news được
loại khỏi bộ chọn mặc định của lane dữ liệu để tránh đăng trùng hoặc né review.

Với nội dung đã đăng: bổ sung permalink vào bài web; không tự repost, sửa post,
comment hoặc mô tả video cũ chỉ vì vừa có bài web. Thay đổi queue đã duyệt phải
duyệt lại. Website thành công nhưng Facebook/video lỗi phải ghi trạng thái riêng.

Pilot xác minh đủ nguồn/web/video/post:
`/tin-tuc/nha-o-xa-hoi-ba-diem-192-ha-chap-thuan-chua-mo-ban`
↔ YouTube https://www.youtube.com/shorts/NUM8QP8VsPM
↔ Facebook https://www.facebook.com/radarbdsvn/posts/pfbid02WXW4hHVhwT6wirc5Ypxb8Z5FijobD55M7sif8nm1HLzDnszugc9RbzrQKBNC8fGXl

### 6. Ghi state và báo cáo

Ghi ngày UTC+7, event key, URL nguồn, URL bài, SHA commit/deploy, từng trạng thái
web/social/video, permalink có bằng chứng và kết quả kiểm tra. Dùng các history
hiện có theo runbook; logs, nguồn thô và assets ở runtime ngoài Git.

Chưa có số liệu GSC/GA4 hoặc API lỗi nghĩa là chưa có dữ liệu; không ghi 0 hay tự
gán tăng trưởng. Báo gọn: bài/URL, lý do chọn, bằng chứng, SHA, kiểm chứng, media,
blocker. Không báo “đã SEO xong” chỉ vì tạo file hoặc gửi lệnh đăng.

## Prompt khởi động

Dùng `hermes_daily_seo_prompt.txt` cùng thư mục handoff. Đây là prompt để anh giao
cho Hermes, không phải xác nhận một cron mới đã được tạo hoặc bật.
