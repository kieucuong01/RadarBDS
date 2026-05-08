"""
BaseCrawler — Abstract base cho tất cả nguồn BĐS.

Thiết kế:
- Playwright stealth headless (bypass Cloudflare, JS rendering)
- Ghi thẳng vào raw_listings, không qua file JSON trung gian
- Hai chế độ: full (lần đầu) và incremental (hàng ngày)
- Subclass chỉ cần implement: crawl_full() / crawl_incremental()
"""
import json
import logging
import re
import sys
from abc import ABC, abstractmethod
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

logger = logging.getLogger(__name__)

# ── Stealth init script (inject vào mỗi page) ─────────────────────────────
_STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
Object.defineProperty(navigator, 'languages', {get: () => ['vi-VN', 'vi', 'en-US', 'en']});
window.chrome = {runtime: {}};
"""


class BaseCrawler(ABC):
    """
    Abstract crawler. Subclass phải định nghĩa:
        SOURCE_NAME : str          — tên nguồn ('guland', 'batdongsan', ...)
        TARGET_URLS : list[str]    — danh sách URL cần crawl

    Và implement:
        crawl_full(page, base_url) -> int        — full crawl 1 URL
        crawl_incremental(page, base_url) -> int — chỉ crawl tin hôm nay
    """

    SOURCE_NAME: str = ""
    TARGET_URLS: list = []

    def __init__(self):
        self.logger = logging.getLogger(f"crawler.{self.SOURCE_NAME or self.__class__.__name__}")
        self._stats = {"new": 0, "skipped": 0, "errors": 0}

    # ── Playwright lifecycle ───────────────────────────────────────────────

    def _launch(self, playwright, headless: bool = True):
        """Khởi động browser stealth, trả về (browser, context)."""
        browser = playwright.chromium.launch(
            headless=headless,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--disable-extensions",
                "--disable-plugins-discovery",
            ],
        )
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/123.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
            locale="vi-VN",
            timezone_id="Asia/Ho_Chi_Minh",
            ignore_https_errors=True,
        )
        ctx.add_init_script(_STEALTH_JS)
        return browser, ctx

    def run(self, mode: str = "full", headless: bool = True) -> dict:
        """
        Entry point.
        mode: 'full' | 'incremental'
        Trả về stats dict: {new, skipped, errors}
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise SystemExit(
                "Playwright chưa cài:\n"
                "  pip install playwright\n"
                "  playwright install chromium"
            )

        self._stats = {"new": 0, "skipped": 0, "errors": 0}

        with sync_playwright() as pw:
            browser, ctx = self._launch(pw, headless=headless)
            page = ctx.new_page()
            page.set_default_timeout(30_000)

            for url in self.TARGET_URLS:
                self.logger.info(f"[{self.SOURCE_NAME}] {mode} crawl: {url}")
                try:
                    if mode == "full":
                        n = self.crawl_full(page, url)
                    else:
                        n = self.crawl_incremental(page, url)
                    self.logger.info(
                        f"[{self.SOURCE_NAME}] {url} → {n} new records"
                    )
                except Exception as e:
                    self.logger.error(f"[{self.SOURCE_NAME}] Error on {url}: {e}", exc_info=True)
                    self._stats["errors"] += 1

            browser.close()

        self.logger.info(
            f"[{self.SOURCE_NAME}] Done — "
            f"new={self._stats['new']} skipped={self._stats['skipped']} errors={self._stats['errors']}"
        )
        return dict(self._stats)

    # ── Abstract methods ───────────────────────────────────────────────────

    @abstractmethod
    def crawl_full(self, page, base_url: str) -> int:
        """Full crawl tất cả trang listing. Trả về số record mới."""
        pass

    @abstractmethod
    def crawl_incremental(self, page, base_url: str) -> int:
        """Chỉ crawl tin đăng hôm nay/hôm qua. Trả về số record mới."""
        pass

    # ── DB helpers ─────────────────────────────────────────────────────────

    def upsert_raw(self, url: str, raw_data: dict) -> bool:
        """
        Ghi vào raw_listings.
        Return True nếu là record mới, False nếu đã tồn tại.
        """
        from config.database_sqlite import get_conn

        source_id = str(raw_data.get("post_id") or raw_data.get("source_id") or "")
        raw_json = json.dumps(raw_data, ensure_ascii=False)

        try:
            with get_conn() as conn:
                existing = conn.execute(
                    "SELECT id FROM raw_listings WHERE source=? AND url=?",
                    (self.SOURCE_NAME, url),
                ).fetchone()
                if existing:
                    self._stats["skipped"] += 1
                    return False
                conn.execute(
                    """INSERT INTO raw_listings (source, source_id, url, raw_json, crawled_at)
                       VALUES (?, ?, ?, ?, datetime('now'))""",
                    (self.SOURCE_NAME, source_id, url, raw_json),
                )
            self._stats["new"] += 1
            return True
        except Exception as e:
            self.logger.error(f"upsert_raw error url={url}: {e}")
            self._stats["errors"] += 1
            return False

    def url_exists(self, url: str) -> bool:
        """Kiểm tra URL đã có trong DB chưa."""
        from config.database_sqlite import get_conn
        with get_conn() as conn:
            return conn.execute(
                "SELECT 1 FROM raw_listings WHERE source=? AND url=?",
                (self.SOURCE_NAME, url),
            ).fetchone() is not None

    # ── Date helpers ───────────────────────────────────────────────────────

    def is_recent(self, date_raw: str) -> bool:
        """True nếu tin đăng hôm nay hoặc hôm qua."""
        s = (date_raw or "").lower().strip()
        if not s:
            return True  # không có date → coi là mới
        if any(kw in s for kw in ["hôm nay", "vừa", "giờ trước", "phút trước", "giây"]):
            return True
        if "hôm qua" in s:
            return True
        m = re.search(r"(\d+)\s*ngày", s)
        if m and int(m.group(1)) <= 1:
            return True
        return False

    def is_old(self, date_raw: str) -> bool:
        """True nếu tin đăng rõ ràng cũ hơn hôm qua."""
        s = (date_raw or "").lower().strip()
        if not s:
            return False
        m = re.search(r"(\d+)\s*ngày", s)
        if m and int(m.group(1)) > 1:
            return True
        if re.search(r"\d+\s*(tuần|tháng|năm)", s):
            return True
        return False

    # ── Parse helpers ──────────────────────────────────────────────────────

    @staticmethod
    def parse_price_ty(raw: str) -> Optional[float]:
        if not raw:
            return None
        s = raw.lower().replace(",", ".")
        try:
            num_str = re.sub(r"[^\d.]", "", s.split("t")[0].strip())
            num = float(num_str) if num_str else None
            if num is None:
                return None
            if any(k in s for k in ["tỷ", "ty", "tỉ"]):
                return round(num, 3)
            if any(k in s for k in ["triệu", "tr"]):
                return round(num / 1000, 3)
        except Exception:
            pass
        return None

    @staticmethod
    def parse_area_m2(raw: str) -> Optional[float]:
        if not raw:
            return None
        try:
            num = re.sub(r"[^\d.]", "", raw.replace(",", "."))
            return float(num) if num else None
        except Exception:
            return None

    @staticmethod
    def parse_ppm2(raw: str) -> Optional[float]:
        if not raw:
            return None
        try:
            num = re.sub(r"[^\d.]", "", raw.replace(",", ".").split("t")[0].strip())
            return float(num) if num else None
        except Exception:
            return None
