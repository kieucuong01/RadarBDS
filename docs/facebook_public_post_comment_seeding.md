# Facebook public-post comment seeding (@rb)

## Mục tiêu và phạm vi hiện tại

Tìm bài Facebook public hoặc bài trong group nhìn thấy được có thảo luận thật về bất động sản, bổ sung comment hữu ích bằng identity **Tiny Sudo** và dẫn người đọc tới bộ lọc deal phù hợp trên `radarbds.vn`.

Phạm vi đang bật chỉ gồm 14 phường thuộc **Thủ Dầu Một**: Tân An, Hiệp An, Tương Bình Hiệp, Định Hòa, Chánh Mỹ, Phú Mỹ, Phú Cường, Phú Hòa, Phú Lợi, Hiệp Thành, Chánh Nghĩa, Phú Tân, Phú Thọ và Hòa Phú.

Không seed bài chỉ nói chung “Thủ Dầu Một”. Không seed Dĩ An, Thuận An, Bến Cát, Tân Uyên hoặc thành phố khác. Chỉ mở thêm thành phố khi anh Cường ra lệnh; khi đó phải cập nhật đồng thời `deal_coverage`, query theo phường, test, deep-link live và prepare-only.

## Gate bắt buộc

Một bài chỉ được chọn khi đồng thời thỏa:

1. URL là permalink bài viết xác minh được: `/posts/`, `/reel/`, `/videos/` hoặc `/groups/<id>/posts/<id>`/`/groups/<id>/permalink/<id>`; cấm Search URL, profile URL, private/inaccessible content và legacy `permalink.php`/`photo.php`.
2. Nội dung thật sự liên quan bất động sản, nhắc rõ một phường đang bật và có ngữ cảnh Thủ Dầu Một/TDM. Loại các ngữ cảnh thành phố khác và tên mơ hồ như “Phú Mỹ Hưng, Quận 7”.
3. Mới trong 72 giờ, tối thiểu 10 reactions, 3 comments và 15 tổng tương tác.
4. Không phải quảng cáo/tin bán hàng; comment đang mở.
5. Tác giả không nằm trong broker watchlist DB `facebook_crawl_profiles`; kiểm tra lại ngay trước browser action.
6. Chưa dùng cùng post; tác giả cooldown 30 ngày, topic+location cooldown 14 ngày.
7. Landing URL có `city=THỦ DẦU MỘT`, đúng `ward`, `date_range=3m`, `mos_min=10` và UTM; `source.location` phải trùng ward trong link.
8. `/api/counts` trả ít nhất 1 `stats.hot` ngay trước comment. Trang rỗng hoặc lỗi API phải fail closed.

Không hạ gate chỉ để có comment. `no_eligible_public_post` là kết quả hợp lệ.

## Nội dung comment

- Tối đa 500 ký tự, trung lập và có ích: cách so giá/m², kiểm tra ngày đăng, vị trí, quy hoạch, pháp lý và giá thực tế.
- Đúng **một** URL HTTPS trên host chính xác `radarbds.vn`; URL trong queue phải trùng URL trong comment.
- Có `utm_source=facebook`, `utm_medium=comment`, `utm_campaign=public_post_seeding`.
- Không fake testimonial, không thúc giục chốt, không cam kết lợi nhuận và không coi tín hiệu thuật toán là bảo đảm.

## Identity, state và xác minh

1. Discovery/prepare/publish chuyển sang **Tiny Sudo** và xác minh menu có `Switch to Radar BDS`.
2. `prepare` chỉ điền comment, chụp evidence, xóa sạch editor và xác minh editor rỗng.
3. Trước `publish`, executor atomically ghi reservation `pending`; process crash vẫn chặn lần chạy trùng.
4. Browser chỉ thành công khi thấy comment mới render bền vững, có permalink `comment_id=`/`reply_comment_id=` và đã restore Radar BDS. Executor sau đó đổi đúng reservation thành `published`; lỗi browser đổi thành `failed`.
5. Executor là nơi duy nhất ghi state publish. Scheduler đọc và xác minh `state_action`, không ghi lần hai.
6. Mọi nhánh browser đều restore **Radar BDS** trong `finally`; xác minh menu có `Switch to Tiny Sudo`.
7. Dừng ngay khi gặp CAPTCHA, checkpoint, restriction hoặc rate limit.

## File và lệnh vận hành

- Config: `config/social_group_comment_targets.json`
- Discovery/scoring/scheduler: `scripts/radar_group_comment_seed.py` (giữ tên legacy)
- Browser executor/state owner: `scripts/browser_use_group_comment.py` (giữ tên legacy)
- Tests: `tests/test_radar_group_comment_seed.py`
- State: `/opt/radar-bds/var/social_queue/public-post-comment/state.json`
- Queue: `/opt/radar-bds/var/social_queue/public-post-comment/queue/`
- Evidence: `/home/hermesops/radar-browser-use/artifacts/public-post-comment-seeding/`

```bash
# Discovery thật, không publish
scripts/radar_group_comment_seed.py --dry-run

# Prepare queue: điền rồi xóa, không đăng
scripts/browser_use_group_comment.py --queue /path/to/queue.json --mode prepare

# Publish queue đã qua toàn bộ gate; executor tự ghi state hai pha
scripts/browser_use_group_comment.py --queue /path/to/queue.json --mode publish --yes

# Test
PYTHONPYCACHEPREFIX=/home/hermesops/.cache/hermes-pyc \
  python3 -m unittest tests.test_radar_group_comment_seed -v
```

Hermes cron `@rb Facebook comment seeding 3/day` chạy 10:30 / 15:30 / 20:30 hằng ngày qua `radar_public_post_comment_scheduler.sh`. Code giữ cap tối đa 3 comment/ngày và 21 comment/7 ngày; mỗi run chỉ xoay một số query theo target để tránh timeout. Không có bài phù hợp hoặc Facebook discovery timeout thì stdout rỗng và không gửi thông báo.
