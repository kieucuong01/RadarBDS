# Facebook group comment seeding (@rb)

## Mục tiêu

Trả lời hữu ích cho câu hỏi thật của người mua bất động sản Bình Dương bằng danh tính Page **Radar BDS**. Không giả làm người dùng độc lập, không chen vào tin rao chỉ để kéo traffic và không tự động chèn link.

## Gate bắt buộc

Một bài chỉ được chọn khi đồng thời thỏa:

- nằm trong group có `comment_enabled=true`;
- là câu hỏi ngôi thứ nhất rõ ràng (`cho em/mình hỏi`, `xin/nhờ tư vấn`, `em/mình đang xem...`);
- mới trong 72 giờ;
- liên quan giá, pháp lý hoặc kiểm tra trước khi mua;
- relevance score tối thiểu 7;
- comment đang mở;
- không phải tin bán hàng nặng số điện thoại/`liên hệ`/`bán gấp`/`giá chỉ`;
- chưa comment cùng bài;
- chưa comment cùng tác giả trong 30 ngày;
- chưa comment cùng topic trong cùng group trong 14 ngày.

Nếu không có bài đạt gate, scheduler phải kết thúc im lặng (`no_eligible_post`).

## Chính sách nội dung

- Mở đầu bằng `Radar BDS` để minh bạch danh tính.
- Tập trung checklist kiểm tra, cách so giá/m² và giới hạn của dữ liệu giá rao.
- Auto-comment không có URL. Link chỉ được cân nhắc thủ công sau khi kiểm tra luật group và khi người dùng hỏi nguồn/công cụ trực tiếp.
- Tối đa 700 ký tự; cấm claim như `cam kết lợi nhuận`, `giá thật 100%`, `pháp lý chuẩn 100%`.

## Frequency cap

- Tối đa 1 group action/ngày, dùng chung với group auto-post.
- Tối đa 1 comment/group/tuần.
- Mặc định tối đa 3 comment/tuần trên toàn workflow.

## File chính

- Allowlist: `config/social_group_comment_targets.json`
- Discovery + scoring + scheduler: `scripts/radar_group_comment_seed.py`
- Browser executor: `scripts/browser_use_group_comment.py`
- Test: `tests/test_radar_group_comment_seed.py`
- Runtime state: `/opt/radar-bds/var/social_queue/group-comment/state.json`
- Queue: `/opt/radar-bds/var/social_queue/group-comment/queue/`
- Screenshot: `/home/hermesops/radar-browser-use/artifacts/group-comment-seeding/`

## Lệnh vận hành

```bash
# Chỉ scan/chọn, không publish
scripts/radar_group_comment_seed.py --dry-run

# Prepare một queue: nhập draft, chụp ảnh, bắt buộc xóa draft và verify rỗng
scripts/browser_use_group_comment.py --queue /path/to/queue.json --mode prepare

# Publish queue đã qua relevance gate
scripts/browser_use_group_comment.py --queue /path/to/queue.json --mode publish --yes

# Scheduler production
scripts/radar_group_comment_seed.py --publish
```

## Stop conditions

Executor dừng ngay khi gặp checkpoint/CAPTCHA/restriction/rate-limit, sai group, sai tác giả, sai post needle, comment bị tắt, nhiều hơn một textbox Radar BDS, link trái allowlist hoặc không xác minh được comment sau khi gửi.

## Moderation incident 2026-07-25

Pilot group post vào `Bất Động Sản Bình Dương` bị Facebook tự động từ chối với lý do `Link in post / Post has a link`. Target đó đã bị khóa cho cả auto-post và comment seeding đến khi review luật thủ công lại.
