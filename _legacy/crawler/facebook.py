"""
Facebook Group Scraper — Selenium-based
Crawl tin đăng BĐS từ các group Facebook địa phương
"""
import logging
import re
import time
import random
from typing import List, Dict, Optional

from config.settings import (
    FACEBOOK_EMAIL, FACEBOOK_PASSWORD,
    FACEBOOK_GROUPS, FACEBOOK_SCROLL_TIMES, WATCH_AREAS
)

logger = logging.getLogger(__name__)

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import TimeoutException, NoSuchElementException
    SELENIUM_OK = True
except ImportError:
    SELENIUM_OK = False
    logger.warning("Selenium not installed — Facebook crawler disabled")

# Tất cả keywords cần theo dõi (từ tất cả khu vực)
ALL_AREA_KEYWORDS = []
for area in WATCH_AREAS:
    ALL_AREA_KEYWORDS.extend(area["keywords"])
ALL_AREA_KEYWORDS = list(set(ALL_AREA_KEYWORDS))


def _make_driver(headless: bool = True) -> "webdriver.Chrome":
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--window-size=1366,768")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    opts.add_argument(f"user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      f"AppleWebKit/537.36 (KHTML, like Gecko) "
                      f"Chrome/122.0.0.0 Safari/537.36")
    driver = webdriver.Chrome(options=opts)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    return driver


class FacebookCrawler:
    source_name = "facebook"

    def __init__(self):
        if not SELENIUM_OK:
            raise RuntimeError("Selenium is not installed. Run: pip install selenium")
        self.driver: Optional["webdriver.Chrome"] = None
        self.logged_in = False
        self.logger = logging.getLogger(self.__class__.__name__)

    def _login(self) -> bool:
        if not FACEBOOK_EMAIL or not FACEBOOK_PASSWORD:
            self.logger.error("Facebook credentials not set in env vars")
            return False
        try:
            self.driver.get("https://www.facebook.com/login")
            wait = WebDriverWait(self.driver, 15)

            email_field = wait.until(EC.presence_of_element_located((By.ID, "email")))
            email_field.send_keys(FACEBOOK_EMAIL)

            pass_field  = self.driver.find_element(By.ID, "pass")
            pass_field.send_keys(FACEBOOK_PASSWORD)

            login_btn = self.driver.find_element(By.NAME, "login")
            login_btn.click()

            # Chờ redirect sau login
            time.sleep(random.uniform(4, 7))

            if "checkpoint" in self.driver.current_url:
                self.logger.error("Facebook checkpoint detected — manual verification required")
                return False

            self.logged_in = True
            self.logger.info("Facebook login successful")
            return True
        except Exception as e:
            self.logger.error(f"Facebook login failed: {e}")
            return False

    def _scroll_group(self, group_url: str) -> List[str]:
        """Scroll group page, thu thập text các bài đăng."""
        try:
            self.driver.get(group_url)
            time.sleep(random.uniform(3, 5))
        except Exception as e:
            self.logger.error(f"Cannot open group {group_url}: {e}")
            return []

        posts_text = []
        seen_texts = set()

        for i in range(FACEBOOK_SCROLL_TIMES):
            try:
                # Thu thập các bài đăng hiện tại
                post_elements = self.driver.find_elements(
                    By.CSS_SELECTOR,
                    "div[data-ad-preview='message'], div.x1iorvi4 div[dir='auto']"
                )
                for el in post_elements:
                    try:
                        text = el.text.strip()
                        if len(text) > 50 and text not in seen_texts:
                            seen_texts.add(text)
                            posts_text.append(text)
                    except Exception:
                        pass

                # Scroll xuống
                self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(random.uniform(2.5, 4.5))
                self.logger.debug(f"  Scroll {i+1}/{FACEBOOK_SCROLL_TIMES}: {len(posts_text)} posts")
            except Exception as e:
                self.logger.warning(f"Scroll error on {group_url}: {e}")
                break

        return posts_text

    def _is_relevant_post(self, text: str) -> bool:
        """Kiểm tra post có liên quan đến BĐS trong khu vực không."""
        text_lower = text.lower()
        bds_keywords = [
            "bán đất", "cho thuê", "nhà đất", "lô đất", "đất nền",
            "mặt tiền", "shr", "đất ở", "khu dân cư", "quy hoạch",
            "cần bán", "cần cho thuê", "giá bán", "tỷ", "triệu/m"
        ]
        has_bds   = any(k in text_lower for k in bds_keywords)
        has_area  = any(k in text_lower for k in ALL_AREA_KEYWORDS)
        return has_bds and has_area

    def _parse_post(self, text: str, group_url: str) -> Optional[Dict]:
        """Trích xuất thông tin từ text bài đăng."""
        if not self._is_relevant_post(text):
            return None
        try:
            # Xác định khu vực
            area_name = None
            for area in WATCH_AREAS:
                if any(kw in text.lower() for kw in area["keywords"]):
                    area_name = area["name"]
                    break

            # Trích phone
            phone_match = re.search(r"0[3-9]\d{8}", text)
            phone = phone_match.group() if phone_match else None

            # Trích giá
            price_total  = _extract_price_from_text(text)
            area_m2      = _extract_area_from_text(text)
            price_per_m2 = None
            if price_total and area_m2 and area_m2 > 0:
                price_per_m2 = round((price_total * 1_000) / area_m2, 3)  # triệu/m2

            # Sentiment sơ bộ
            sentiment = _classify_sentiment(text)

            return {
                "source":           "facebook",
                "external_id":      None,
                "url":              group_url,
                "title":            text[:100],
                "description":      text[:2000],
                "area_name":        area_name,
                "raw_area_text":    area_name or "",
                "price_total":      price_total,
                "price_per_m2":     price_per_m2,
                "area_m2":          area_m2,
                "property_type":    _infer_type_from_text(text),
                "transaction_type": "thue" if _is_rental(text) else "ban",
                "contact_phone":    phone,
                "seller_name":      None,
                "sentiment":        sentiment,
            }
        except Exception as e:
            self.logger.error(f"Parse post error: {e}")
            return None

    def crawl_all_groups(self) -> List[Dict]:
        results = []
        self.driver = _make_driver(headless=True)
        try:
            if not self._login():
                return results

            for group_url in FACEBOOK_GROUPS:
                self.logger.info(f"Crawling group: {group_url}")
                try:
                    posts = self._scroll_group(group_url)
                    self.logger.info(f"  Got {len(posts)} raw posts")
                    for text in posts:
                        parsed = self._parse_post(text, group_url)
                        if parsed:
                            results.append(parsed)
                    self.logger.info(f"  → {len([p for p in results])} relevant posts so far")
                    time.sleep(random.uniform(5, 10))
                except Exception as e:
                    self.logger.error(f"Group crawl error [{group_url}]: {e}")
        finally:
            if self.driver:
                self.driver.quit()
        return results


# ─── Text extraction helpers ──────────────────────────────────────────────────

def _extract_price_from_text(text: str) -> Optional[float]:
    """Trả về tỷ VND."""
    text = text.lower()
    # Pattern: 2.5 tỷ, 2,5 tỷ, 2 tỷ 5
    m = re.search(r"([\d,\.]+)\s*tỷ", text)
    if m:
        try:
            return float(m.group(1).replace(",", "."))
        except Exception:
            pass
    # Pattern: 500 triệu
    m = re.search(r"([\d,\.]+)\s*triệu", text)
    if m:
        try:
            return float(m.group(1).replace(",", ".")) / 1000
        except Exception:
            pass
    return None


def _extract_area_from_text(text: str) -> Optional[float]:
    """Trả về m2."""
    m = re.search(r"([\d,\.]+)\s*m[²2]", text, re.IGNORECASE)
    if m:
        try:
            return float(m.group(1).replace(",", "."))
        except Exception:
            pass
    return None


def _is_rental(text: str) -> bool:
    return any(k in text.lower() for k in ["cho thuê", "cần thuê", "giá thuê", "thuê nhà"])


def _infer_type_from_text(text: str) -> str:
    text = text.lower()
    if any(k in text for k in ["đất nền", "lô đất", "đất ở", "đất thổ"]):
        return "dat_nen"
    if any(k in text for k in ["nhà phố", "mặt tiền"]):
        return "nha_pho"
    if any(k in text for k in ["phòng trọ", "nhà trọ", "dãy trọ"]):
        return "nha_tro"
    return "khac"


def _classify_sentiment(text: str) -> str:
    text = text.lower()
    sell_panic = ["cắt lỗ", "bán gấp", "bán nhanh", "kẹt tiền", "ngộp", "bán rẻ", "cần tiền gấp"]
    buy_intent = ["tìm mua", "cần mua", "muốn mua", "tìm lô", "tìm đất", "ai có đất"]
    if any(k in text for k in sell_panic):
        return "sell_panic"
    if any(k in text for k in buy_intent):
        return "buy_intent"
    return "neutral"
