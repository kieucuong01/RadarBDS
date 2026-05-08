"""
Base crawler class — shared logic cho tất cả sources
"""
import logging
import random
import time
from abc import ABC, abstractmethod
from typing import List, Dict, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config.settings import (
    CRAWLER_DELAY_MIN, CRAWLER_DELAY_MAX,
    CRAWLER_RETRY_MAX, CRAWLER_TIMEOUT, USER_AGENTS
)

logger = logging.getLogger(__name__)


def make_session() -> requests.Session:
    """Tạo requests.Session với retry + random User-Agent."""
    session = requests.Session()
    retry = Retry(
        total=CRAWLER_RETRY_MAX,
        backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({
        "User-Agent": random.choice(USER_AGENTS),
        "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    })
    return session


class BaseCrawler(ABC):
    """Abstract base crawler."""

    source_name: str = "base"

    def __init__(self):
        self.session = make_session()
        self.logger  = logging.getLogger(self.__class__.__name__)

    def polite_sleep(self) -> None:
        time.sleep(random.uniform(CRAWLER_DELAY_MIN, CRAWLER_DELAY_MAX))

    def fetch(self, url: str, params: dict = None, json: bool = False) -> Optional[any]:
        try:
            resp = self.session.get(url, params=params, timeout=CRAWLER_TIMEOUT)
            resp.raise_for_status()
            return resp.json() if json else resp.text
        except requests.exceptions.HTTPError as e:
            self.logger.warning(f"HTTP {e.response.status_code} for {url}")
        except requests.exceptions.ConnectionError:
            self.logger.warning(f"Connection error: {url}")
        except requests.exceptions.Timeout:
            self.logger.warning(f"Timeout: {url}")
        except Exception as e:
            self.logger.error(f"Unexpected fetch error [{url}]: {e}")
        return None

    @abstractmethod
    def get_listing_urls(self, area_config: dict) -> List[str]:
        """Trả về danh sách URL của từng tin đăng trong khu vực."""
        ...

    @abstractmethod
    def parse_listing(self, url: str) -> Optional[Dict]:
        """Parse một trang tin đăng, trả về dict hoặc None nếu lỗi."""
        ...

    def crawl_area(self, area_config: dict,
                   existing_raw_urls: set = None,
                   crawl_run_id: int = None) -> List[Dict]:
        """
        Crawl toàn bộ tin trong một khu vực.
        - Lưu RAW vào raw_listings trước (source of truth)
        - Skip URL đã có trong raw_listings (incremental)
        - Trả về list raw dicts (để caller normalize + upsert listings)
        """
        from config.database_sqlite import insert_raw

        results  = []
        urls     = self.get_listing_urls(area_config)
        skip_set = existing_raw_urls or set()
        self.logger.info(f"[{self.source_name}] {area_config['name']}: {len(urls)} URLs | skip={len(skip_set)}")

        skipped = 0
        for url in urls:
            try:
                if url in skip_set:
                    skipped += 1
                    continue

                data = self.parse_listing(url)
                if data:
                    data["source"]    = self.source_name
                    data["area_name"] = area_config["name"]

                    # ── Lưu RAW ngay lập tức, trước khi normalize ──
                    sid    = str(data.get("external_id") or data.get("source_id") or "")
                    raw_id = insert_raw(
                        source       = self.source_name,
                        source_id    = sid or None,
                        url          = url,
                        raw_data     = data,
                        crawl_run_id = crawl_run_id,
                    )
                    data["raw_id"] = raw_id
                    results.append(data)
            except Exception as e:
                self.logger.error(f"Error parsing {url}: {e}")
            self.polite_sleep()

        if skipped:
            self.logger.info(f"[{self.source_name}] Incremental skip: {skipped} URLs đã có trong raw")
        return results
