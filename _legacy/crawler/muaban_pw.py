"""
MuaBan.net Playwright Crawler — STUB (chưa implement)

TODO:
- Target URLs: https://muaban.net/bat-dong-san/binh-duong
- Selectors: inspect muaban.net listing structure
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from crawler.base_crawler import BaseCrawler


class MuaBanCrawler(BaseCrawler):
    SOURCE_NAME = "muaban"
    TARGET_URLS = []

    def crawl_full(self, page, base_url: str) -> int:
        raise NotImplementedError("MuaBan crawler chưa implement")

    def crawl_incremental(self, page, base_url: str) -> int:
        raise NotImplementedError("MuaBan crawler chưa implement")
