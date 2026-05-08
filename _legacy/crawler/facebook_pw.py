"""
Facebook Playwright Crawler — STUB (chưa implement)

Nguồn: trang cá nhân môi giới + hội nhóm BĐS

Thách thức:
- Cần login (FACEBOOK_EMAIL / FACEBOOK_PASSWORD trong .env)
- Facebook chặn automation mạnh → cần stealth cao, random delay
- Nội dung dynamic, cần scroll để load thêm
- Cần xử lý 2FA nếu có

TODO:
1. Login flow với session cookie caching
2. Crawl group timeline: scroll + extract posts
3. Crawl profile timeline của list môi giới
4. NLP extract: giá, diện tích, địa chỉ từ post text tự do
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from crawler.base_crawler import BaseCrawler

# Điền vào .env:
# FACEBOOK_EMAIL=your@email.com
# FACEBOOK_PASSWORD=yourpassword
# FACEBOOK_GROUPS=https://www.facebook.com/groups/xxx,https://...

FACEBOOK_GROUPS = [
    # "https://www.facebook.com/groups/batdongsanbinhduong",
]
FACEBOOK_PROFILES = [
    # "https://www.facebook.com/profile.php?id=xxx",  # môi giới A
]


class FacebookCrawler(BaseCrawler):
    SOURCE_NAME = "facebook"
    TARGET_URLS = FACEBOOK_GROUPS + FACEBOOK_PROFILES

    def crawl_full(self, page, base_url: str) -> int:
        raise NotImplementedError(
            "Facebook crawler chưa implement.\n"
            "Cần: FACEBOOK_EMAIL + FACEBOOK_PASSWORD trong .env"
        )

    def crawl_incremental(self, page, base_url: str) -> int:
        raise NotImplementedError("Facebook crawler chưa implement")
