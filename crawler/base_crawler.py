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
import os
import random
import re
import sys
import time
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


def _normalize_playwright_browser_path_env() -> None:
    value = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if not value:
        return
    cleaned = value.strip()
    if cleaned != value:
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = cleaned
        logger.warning("Normalized PLAYWRIGHT_BROWSERS_PATH containing surrounding whitespace")


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
        self._stats = {"fetched": 0, "new": 0, "skipped": 0, "errors": 0, "error_details": []}

    # ── User-Agent pool ─────────────────────────────────────────────────────

    _UA_POOL = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Safari/605.1.15",
    ]

    # ── Playwright lifecycle ───────────────────────────────────────────────

    def _launch(self, playwright, headless: bool = True):
        """Khởi động browser stealth, trả về (browser, context)."""
        _normalize_playwright_browser_path_env()
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
        ua = random.choice(self._UA_POOL)
        self.logger.info(f"UA: {ua[:60]}...")
        ctx = browser.new_context(
            user_agent=ua,
            viewport={"width": 1280, "height": 800},
            locale="vi-VN",
            timezone_id="Asia/Ho_Chi_Minh",
            ignore_https_errors=True,
        )
        ctx.add_init_script(_STEALTH_JS)
        return browser, ctx

    # ── Retry helper ──────────────────────────────────────────────────────

    def _retry(self, fn, max_retries: int = 3, base_delay: float = 2.0, label: str = ""):
        """Execute fn() with exponential backoff + jitter. Returns result or raises last exception."""
        last_exc = None
        for attempt in range(max_retries + 1):
            try:
                return fn()
            except Exception as e:
                last_exc = e
                if attempt < max_retries:
                    delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
                    self.logger.warning(
                        f"Retry {attempt+1}/{max_retries} {label}: {e.__class__.__name__}: {e} "
                        f"(wait {delay:.1f}s)"
                    )
                    time.sleep(delay)
        raise last_exc

    # ── Record validation ─────────────────────────────────────────────────

    def _validate_record(self, raw_data: dict) -> Optional[str]:
        """Validate raw record before insert. Returns error message if invalid, None if OK."""
        url = raw_data.get("url", "")
        if not url or not url.startswith("http"):
            return f"invalid url: {url!r}"
        title = raw_data.get("title", "")
        if len(title) < 5:
            return f"title too short: {title!r}"
        price = raw_data.get("price_ty")
        if price is not None and (price <= 0 or price > 10000):
            return f"price out of range: {price}"
        area = raw_data.get("area_m2")
        if area is not None and (area <= 0 or area > 100000):
            return f"area out of range: {area}"
        return None

    def _track_error(self, url: str, error: Exception, error_type: str = "unknown") -> None:
        """Log và track error với classification."""
        self._stats["errors"] += 1
        self._stats["error_details"].append({
            "url": url,
            "error_type": error_type,
            "error_msg": str(error)[:200],
        })

    def run(self, mode: str = "full", headless: bool = True) -> dict:
        """
        Entry point.
        mode: 'full' | 'incremental'
        Trả về stats dict: {new, skipped, errors}
        """
        _normalize_playwright_browser_path_env()
        from db.crawl_runs import (
            derive_crawl_status,
            finish_crawl_run,
            get_incomplete_run,
            mark_url_done,
            mark_url_error,
            start_crawl_run,
        )

        self._stats = {
            "fetched": 0,
            "new": 0,
            "updated": 0,
            "skipped": 0,
            "errors": 0,
            "error_details": [],
        }

        # Check for incomplete run to resume
        incomplete = get_incomplete_run(self.SOURCE_NAME)
        if incomplete:
            run_id = incomplete["run_id"]
            completed_urls = incomplete["completed_urls"]
            self.logger.info(
                f"[{self.SOURCE_NAME}] Resuming run #{run_id} "
                f"({len(completed_urls)}/{len(self.TARGET_URLS)} URLs done)"
            )
        else:
            run_id = start_crawl_run(self.SOURCE_NAME, "TDM")
            completed_urls = set()
        self._crawl_run_id = run_id
        fatal_error = None
        try:
            try:
                from playwright.sync_api import sync_playwright
            except ImportError as exc:
                raise SystemExit(
                    "Playwright chưa cài:\n"
                    "  pip install playwright\n"
                    "  playwright install chromium"
                ) from exc

            with sync_playwright() as pw:
                browser, ctx = self._launch(pw, headless=headless)
                self._ctx = ctx
                page = ctx.new_page()
                page.set_default_timeout(30_000)

                for url in self.TARGET_URLS:
                    if url in completed_urls:
                        self.logger.info(f"[{self.SOURCE_NAME}] Skip (already done): {url}")
                        continue

                    self.logger.info(f"[{self.SOURCE_NAME}] {mode} crawl: {url}")
                    before = {
                        key: int(self._stats.get(key, 0) or 0)
                        for key in (
                            "fetched",
                            "existing",
                            "new",
                            "updated",
                            "invalid_price",
                            "errors",
                        )
                    }
                    try:
                        if mode == "full":
                            n = self.crawl_full(page, url)
                        else:
                            n = self.crawl_incremental(page, url)
                        mark_url_done(run_id, url, n)
                    except Exception as exc:
                        self.logger.error(
                            f"[{self.SOURCE_NAME}] Error on {url}: {exc}",
                            exc_info=True,
                        )
                        self._track_error(url, exc, error_type="crawl_exception")
                        mark_url_error(run_id, url, str(exc))
                    finally:
                        counters = {
                            "url": url[:500],
                            "fetched": int(self._stats.get("fetched", 0) or 0)
                            - before["fetched"],
                            "existing": int(self._stats.get("existing", 0) or 0)
                            - before["existing"],
                            "new": int(self._stats.get("new", 0) or 0)
                            - before["new"],
                            "changed": int(self._stats.get("updated", 0) or 0)
                            - before["updated"],
                            "invalid": int(self._stats.get("invalid_price", 0) or 0)
                            - before["invalid_price"],
                            "errors": int(self._stats.get("errors", 0) or 0)
                            - before["errors"],
                        }
                        self.logger.info(
                            "[%s] target=%s",
                            self.SOURCE_NAME,
                            json.dumps(counters, ensure_ascii=False),
                        )

                browser.close()
        except BaseException as exc:
            fatal_error = exc
            if not self._stats["error_details"] or (
                self._stats["error_details"][-1].get("error_msg") != str(exc)[:200]
            ):
                self._track_error(
                    f"{self.SOURCE_NAME}:run",
                    exc,
                    error_type="fatal",
                )
            raise
        finally:
            error_msg = None
            if self._stats["error_details"]:
                error_msg = json.dumps(
                    self._stats["error_details"][:20],
                    ensure_ascii=False,
                )[:2000]
            finish_crawl_run(
                run_id,
                self._stats,
                status=derive_crawl_status(
                    self._stats,
                    fatal=fatal_error is not None,
                ),
                error_msg=error_msg,
            )

        self.logger.info(
            f"[{self.SOURCE_NAME}] Done — "
            f"fetched={self._stats['fetched']} new={self._stats['new']} "
            f"skipped={self._stats['skipped']} errors={self._stats['errors']}"
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
        validation_err = self._validate_record(raw_data)
        if validation_err:
            self.logger.warning(f"Validation failed for {url}: {validation_err}")
            self._stats["skipped"] += 1
            return False

        from db.connection import get_conn
        from db.moderation import normalize_phone
        from db.raw_listings import insert_raw_result

        source_id = str(raw_data.get("post_id") or raw_data.get("source_id") or "")
        phone_norm = normalize_phone(raw_data.get("contact_phone"))

        if phone_norm:
            with get_conn() as conn:
                blocked = conn.execute(
                    "SELECT 1 FROM broker_blacklist WHERE active=1 AND phone_norm=?",
                    (phone_norm,),
                ).fetchone()
                if blocked:
                    self._stats["skipped"] += 1
                    return False

        result = insert_raw_result(
            self.SOURCE_NAME,
            source_id,
            url,
            raw_data,
            getattr(self, "_crawl_run_id", None),
        )
        if result.status == "inserted":
            self._stats["new"] += 1
            return True

        self._stats["skipped"] += 1
        return False

    def url_exists(self, url: str) -> bool:
        """Kiểm tra URL đã có trong DB chưa."""
        from db.connection import get_conn
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
