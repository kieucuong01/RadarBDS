# DEPRECATED — Facebook group comment seeding

Workflow comment trong Facebook group đã bị vô hiệu hóa. Không dùng tài liệu hoặc hành vi cũ để đăng/comment vào `/groups/`.

Quy trình hiện hành là **public-post-only**, dùng identity Tiny Sudo và hiện chỉ bật cho các phường thuộc Thủ Dầu Một:

- Tài liệu: [`facebook_public_post_comment_seeding.md`](facebook_public_post_comment_seeding.md)
- Config: `config/social_group_comment_targets.json` (tên file legacy)
- Discovery: `scripts/radar_group_comment_seed.py` (tên file legacy)
- Executor: `scripts/browser_use_group_comment.py` (tên file legacy)

Việc giữ tên file legacy chỉ để tương thích scheduler; không phải quyền tái bật group target.
