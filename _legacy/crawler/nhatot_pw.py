"""
NhaTot.com Playwright Crawler — STUB (chưa implement)

TODO:
- Target URLs: https://www.nhatot.com/mua-ban-bat-dong-san/binh-duong/thu-dau-mot
- Selectors: inspect nhatot.com listing structure
- Pagination: scroll-based hoặc ?page=N (cần kiểm tra)
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from crawler.base_crawler import BaseCrawler


class NhaTotCrawler(BaseCrawler):
    SOURCE_NAME = "nhatot"
    TARGET_URLS = [
        # "https://www.nhatot.com/mua-ban-bat-dong-san/binh-duong/thu-dau-mot",
    ]

    def crawl_full(self, page, base_url: str) -> int:
        raise NotImplementedError("NhaTot crawler chưa implement")

    def crawl_incremental(self, page, base_url: str) -> int:
        raise NotImplementedError("NhaTot crawler chưa implement")
