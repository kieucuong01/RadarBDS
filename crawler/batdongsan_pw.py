"""
BatDongSan.com.vn Playwright Crawler — v2

Findings:
  - SSR page, không có JSON API riêng
  - Mỗi slug tối đa ~20 listings, pagination: /p2, /p3...
  - fetch() bị service worker chặn → dùng page.goto() cho detail
  - Selector thực tế: .js__card | a (first link) | .re__card-config-price/area

Tối ưu tốc độ:
  - Phase 1: collect tất cả URLs (navigate listing pages, nhanh)
  - Phase 2: chỉ fetch detail cho URL MỚI chưa có trong DB
  - Parallel: 3 browser pages chạy song song cho detail fetch

Full crawl  : python crawler/batdongsan_pw.py --mode full
Incremental : python crawler/batdongsan_pw.py --mode incremental
"""
import json
import logging
import queue
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from crawler.base_crawler import BaseCrawler

logger = logging.getLogger(__name__)

BASE = "https://batdongsan.com.vn"

BDS_SOURCES_FILE = Path(__file__).parent.parent / "data" / "batdongsan_sources.json"
DEFAULT_BDS_CRAWL_FOR_DAYS = 7

# Fallback nếu thiếu/lỗi data/batdongsan_sources.json
_FALLBACK_WARDS = [
    {"name": "Tân An",          "slug": "tan-an",
     "urls": ["ban-dat-dat-nen-phuong-tan-an_1",
              "ban-nha-dat-phuong-tan-an_1",
              "ban-can-ho-chung-cu-phuong-tan-an_1",
              "ban-kho-nha-xuong-phuong-tan-an_1"]},
    {"name": "Tương Bình Hiệp", "slug": "tuong-binh-hiep"},
    {"name": "Hiệp An",         "slug": "hiep-an"},
    {"name": "Chánh Mỹ",        "slug": "chanh-my"},
    {"name": "Phú Mỹ",          "slug": "phu-my"},
    {"name": "Phú Tân",         "slug": "phu-tan"},
    {"name": "Chánh Nghĩa",     "slug": "chanh-nghia"},
    {"name": "Định Hòa",        "slug": "dinh-hoa"},
    {"name": "Phú Thọ",         "slug": "phu-tho"},
    {"name": "Phú Hòa",         "slug": "phu-hoa"},
    {"name": "Phú Cường",       "slug": "phu-cuong",
     "urls": ["ban-dat-dat-nen-phuong-phu-cuong-1",
              "nha-dat-ban-phuong-phu-cuong-1",
              "ban-can-ho-chung-cu-phuong-phu-cuong-1",
              "ban-kho-nha-xuong-phuong-phu-cuong-1"]},
    {"name": "Hiệp Thành",      "slug": "hiep-thanh"},
    {"name": "Phú Lợi",         "slug": "phu-loi"},
]


def _default_bds_urls(slug: str) -> list:
    return [
        f"ban-dat-dat-nen-phuong-{slug}",
        f"ban-nha-dat-phuong-{slug}",
        f"ban-can-ho-chung-cu-phuong-{slug}",
        f"ban-kho-nha-xuong-phuong-{slug}",
    ]


def _load_bds_config():
    try:
        data = json.loads(BDS_SOURCES_FILE.read_text(encoding="utf-8"))
        wards = data.get("wards") or []
        wards = [w for w in wards if w.get("slug") and w.get("name")]
        days  = int(data.get("crawl_for_days") or DEFAULT_BDS_CRAWL_FOR_DAYS)
        if wards:
            return wards, days
        logger.warning(f"[bds] {BDS_SOURCES_FILE.name} thiếu wards → fallback")
    except FileNotFoundError:
        logger.warning(f"[bds] Không thấy {BDS_SOURCES_FILE.name} → fallback")
    except Exception as e:
        logger.warning(f"[bds] Lỗi parse {BDS_SOURCES_FILE.name}: {e} → fallback")
    return list(_FALLBACK_WARDS), DEFAULT_BDS_CRAWL_FOR_DAYS


_BDS_WARDS, _BDS_DAYS = _load_bds_config()

# Build SEARCH_SLUGS + lookup map (url_slug -> ward_name)
SEARCH_SLUGS = []
BDS_URL_TO_WARD = {}
BDS_WARD_MAP = {}
for _w in _BDS_WARDS:
    _urls = _w.get("urls") or _default_bds_urls(_w["slug"])
    BDS_WARD_MAP[_w["slug"]] = _w["name"]
    for _u in _urls:
        SEARCH_SLUGS.append(_u)
        BDS_URL_TO_WARD[_u] = _w["name"]

DETAIL_WORKERS  = 3    # số pages song song khi fetch detail
SLUG_DELAY_S    = 30   # delay giữa các slug để tránh Cloudflare rate-limit
PAGE_DELAY_S    = 10   # delay giữa các listing pages trong 1 slug

# Thư mục debug khi crawler báo "No cards" (lưu HTML + screenshot lần đầu)
_DEBUG_DIR = Path(__file__).parent.parent / "logs" / "bds_no_cards"
_DEBUG_SAVED = set()  # set of slug_url đã save HTML lần đầu


def _looks_like_challenge(html: str, title: str) -> bool:
    """Detect Cloudflare/anti-bot challenge bằng cả title và body."""
    t = (title or "").lower()
    if "just a moment" in t or "cloudflare" in t or "attention required" in t:
        return True
    h = (html or "").lower()
    return any(s in h for s in (
        "cf-mitigated", "challenge-platform", "cf_chl_opt",
        "cf-browser-verification", "checking your browser",
    ))


def _save_no_cards_debug(page, url: str, logger) -> None:
    """Lần đầu gặp 'no cards' cho URL: save HTML + screenshot để inspect."""
    if url in _DEBUG_SAVED:
        return
    _DEBUG_SAVED.add(url)
    try:
        _DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        slug = url.rsplit("/", 1)[-1].replace("?", "_").replace("/", "_")[:80] or "root"
        (_DEBUG_DIR / f"{slug}.html").write_text(page.content(), encoding="utf-8")
        page.screenshot(path=str(_DEBUG_DIR / f"{slug}.png"), full_page=False)
        logger.warning(f"[bds] saved debug HTML+PNG: {_DEBUG_DIR / slug}.*")
    except Exception as e:
        logger.warning(f"[bds] save debug failed for {url}: {e}")


def _parse_ward_from_slug(slug_url: str) -> str:
    """Extract ward name from BDS slug URL.
    Ưu tiên lookup chính xác trong BDS_URL_TO_WARD; fallback regex hỗ trợ cả `_N` và `-N` suffix.
    """
    path = slug_url.split("/")[-1]
    if path in BDS_URL_TO_WARD:
        return BDS_URL_TO_WARD[path]
    m = re.search(r"phuong-([a-z0-9-]+?)(?:[_-]\d+)?$", path)
    if m:
        return BDS_WARD_MAP.get(m.group(1), m.group(1).replace("-", " ").title())
    return ""


class BatDongSanCrawler(BaseCrawler):
    SOURCE_NAME = "batdongsan"
    TARGET_URLS = [f"{BASE}/{slug}" for slug in SEARCH_SLUGS]

    def is_old(self, date_raw: str) -> bool:
        """Override: dừng pagination khi gặp tin cũ hơn crawl_for_days ngày."""
        s = (date_raw or "").lower().strip()
        if not s:
            return False
        m = re.search(r"(\d+)\s*ngày", s)
        if m and int(m.group(1)) > getattr(self, "crawl_for_days", DEFAULT_BDS_CRAWL_FOR_DAYS):
            return True
        tweek = re.search(r"(\d+)\s*tuần", s)
        if tweek:
            if int(tweek.group(1)) * 7 > getattr(self, "crawl_for_days", DEFAULT_BDS_CRAWL_FOR_DAYS):
                return True
            return False
        if re.search(r"\d+\s*(tháng|năm)", s):
            return True
        return False

    # ── Phase 1: Collect listing cards ────────────────────────────────────

    def _get_cards_on_page(self, page, url: str) -> list:
        """Navigate listing page, extract cards. Trả về list dict."""
        max_cf_retries = 2
        for attempt in range(max_cf_retries + 1):
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                page.wait_for_selector(".js__card", timeout=25_000)
                break  # success
            except Exception as e:
                page_title = ""
                page_html = ""
                try:
                    page_title = page.title()
                    page_html  = page.content()
                except Exception:
                    pass
                if _looks_like_challenge(page_html, page_title):
                    if attempt < max_cf_retries:
                        wait_s = 15 * (attempt + 1)
                        self.logger.warning(f"Cloudflare block {url}, retry {attempt+1}/{max_cf_retries} sau {wait_s}s...")
                        time.sleep(wait_s)
                        continue
                    self.logger.warning(f"Cloudflare block {url}: vẫn bị block sau {max_cf_retries} retries")
                    _save_no_cards_debug(page, url, self.logger)
                else:
                    # Page render OK nhưng không có .js__card → empty thật hoặc DOM thay đổi
                    self.logger.info(f"No cards (empty or slow): {url}")
                    _save_no_cards_debug(page, url, self.logger)
                return []

        try:
            return page.evaluate("""
            () => [...document.querySelectorAll('.js__card')].map(card => {
                const a = card.querySelector('a');
                const url = a?.href || '';
                if (!url || !url.includes('batdongsan.com.vn')) return null;

                const srcId = url.match(/pr(\\d+)/)?.[1] || '';
                const title = card.querySelector('.pr-title, .js__card-title')?.textContent?.trim() || '';
                const price = card.querySelector('.re__card-config-price')?.textContent?.trim() || '';
                const area  = card.querySelector('.re__card-config-area')?.textContent?.trim() || '';
                const date  = card.querySelector('.re__card-published-info')?.textContent?.trim() || '';
                const img   = card.querySelector('img[src*="batdongsan"]')?.src || card.querySelector('img')?.src || '';

                return { url, source_id: srcId, title, price_raw: price, area_raw: area, date_raw: date, img };
            }).filter(c => c && c.url)
            """) or []
        except Exception as e:
            self.logger.warning(f"Card extract error: {e}")
            return []

    def _collect_all_urls(self, page, base_url: str, incremental: bool) -> list:
        """Duyệt qua tất cả trang listing, trả về list cards."""
        all_cards = []
        seen = set()

        for page_num in range(1, 21):
            url = base_url if page_num == 1 else f"{base_url}/p{page_num}"
            self.logger.info(f"  Listing page {page_num}: {url}")

            cards = self._get_cards_on_page(page, url)
            if not cards:
                self.logger.info(f"  → 0 cards, dừng")
                break

            new = [c for c in cards if c["url"] not in seen]
            seen.update(c["url"] for c in new)
            all_cards.extend(new)
            self.logger.info(f"  → {len(new)} cards (total={len(all_cards)})")

            # Incremental: dừng khi gặp tin cũ
            if incremental:
                old = [c for c in new if self.is_old(c.get("date_raw", ""))]
                if old:
                    self.logger.info(f"  Incremental: gặp tin cũ → dừng")
                    break

            # Không có trang tiếp (chỉ 1 trang)
            if len(cards) < 20:
                break

            time.sleep(PAGE_DELAY_S)

        return all_cards

    # ── Phase 2: Detail page ───────────────────────────────────────────────

    def _fetch_detail(self, page, url: str) -> dict:
        """Navigate tới detail page, extract data."""
        try:
            self._retry(
                lambda: page.goto(url, wait_until="domcontentloaded", timeout=25_000),
                max_retries=2, base_delay=2.0, label=f"detail {url}"
            )
            try:
                page.wait_for_selector(".re__pr-short-description, .re__section-description", timeout=8_000)
            except Exception:
                pass  # tiếp tục dù timeout

            return page.evaluate("""
            () => {
                const getText = sel => document.querySelector(sel)?.textContent?.trim() || '';

                // Description
                const desc = getText('.re__section-description .re__detail-content')
                          || getText('.re__section-description');

                // Address
                const addr = getText('.re__pr-short-description');

                // Phone
                const phoneEl = document.querySelector('[href^="tel:"]');
                const phone   = phoneEl ? phoneEl.href.replace('tel:', '') : '';

                // Specs table
                const specs = {};
                document.querySelectorAll('.re__pr-specs-content-item').forEach(item => {
                    const label = item.querySelector('.re__pr-specs-content-item-title')?.textContent?.trim() || '';
                    const val   = item.querySelector('.re__pr-specs-content-item-value')?.textContent?.trim() || '';
                    if (label) specs[label] = val;
                });

                // Price / area từ detail (backup)
                const priceDetail = getText('.re__pr-price .re__pr-price-value');
                const areaDetail  = specs['Diện tích'] || '';

                // Media slider images (ảnh nét từ trang chi tiết)
                const imgs = [...document.querySelectorAll('.re__media-slider img[src], .re__media-thumb-slider img[src], .re__media-thumb-item img[src]')]
                                .map(img => img.src)
                                .filter(src => src && src.startsWith('http') && !src.includes('avatar') && !src.includes('logo'));

                return {
                    description:      desc,
                    address:          addr,
                    contact_phone:    phone,
                    legal_raw:        specs['Pháp lý'] || specs['Giấy tờ pháp lý'] || '',
                    road_type_raw:    specs['Đường vào'] || specs['Loại đường'] || '',
                    frontage_raw:     specs['Mặt tiền'] || '',
                    price_raw_detail: priceDetail,
                    area_raw_detail:  areaDetail,
                    detail_imgs:      imgs,
                };
            }
            """)
        except Exception as e:
            self.logger.warning(f"Detail error {url}: {e}")
            return {}

    # ── Build record ───────────────────────────────────────────────────────

    def _build_record(self, card: dict, detail: dict, ward_name: str = "") -> dict:
        price_raw = card.get("price_raw") or detail.get("price_raw_detail", "")
        area_raw  = card.get("area_raw")  or detail.get("area_raw_detail", "")

        price_ty = self.parse_price_ty(price_raw)
        area_m2  = self.parse_area_m2(area_raw)
        ppm2     = None
        if price_ty and area_m2 and area_m2 > 0:
            ppm2 = round(price_ty * 1e9 / area_m2 / 1e6, 2)

        return {
            "url":           card["url"],
            "source_id":     card.get("source_id", ""),
            "title":         card.get("title", ""),
            "description":   detail.get("description", ""),
            "address":       detail.get("address", ""),
            "price_ty":      price_ty,
            "area_m2":       area_m2,
            "price_per_m2":  ppm2,
            "area_name":     ward_name or "",
            "road_type_raw": detail.get("road_type_raw", ""),
            "legal_raw":     detail.get("legal_raw", ""),
            "frontage_raw":  detail.get("frontage_raw", ""),
            "contact_phone": detail.get("contact_phone", ""),
            "date_raw":      card.get("date_raw", ""),
            "imgs":          detail.get("detail_imgs", []) or ([card.get("img")] if card.get("img") else []),
            "tx_type":       "ban",
            "province":      "Bình Dương",
            "district":      "Thủ Dầu Một",
            "source":        self.SOURCE_NAME,
        }

    # ── Core crawl ─────────────────────────────────────────────────────────

    def __init__(self):
        super().__init__()
        self._slug_count = 0
        self.crawl_for_days = _BDS_DAYS
        logger.info(
            f"[bds] Loaded {len(_BDS_WARDS)} wards = {len(SEARCH_SLUGS)} slugs "
            f"| crawl_for_days={_BDS_DAYS}"
        )

    def _run_crawl(self, page, base_url: str, incremental: bool) -> int:
        # Delay giữa các slug (trừ slug đầu tiên)
        self._slug_count += 1
        if self._slug_count > 1:
            self.logger.info(f"  Waiting {SLUG_DELAY_S}s trước slug tiếp theo (chống rate-limit)...")
            time.sleep(SLUG_DELAY_S)

        # Parse ward từ slug URL
        ward_name = _parse_ward_from_slug(base_url)

        # Phase 1: collect tất cả listing cards
        self.logger.info(f"Phase 1 — collect cards từ {base_url} (ward={ward_name})")
        all_cards = self._collect_all_urls(page, base_url, incremental=incremental)

        # Lọc chỉ URL mới
        new_cards = [c for c in all_cards if not self.url_exists(c["url"])]
        self.logger.info(
            f"Phase 1 done: {len(all_cards)} total | "
            f"{len(new_cards)} mới | {len(all_cards)-len(new_cards)} đã có"
        )

        if not new_cards:
            return 0

        # Phase 2: fetch detail — parallel nếu có ctx, fallback sequential
        n_workers = min(DETAIL_WORKERS, len(new_cards))
        ctx = getattr(self, "_ctx", None)

        if ctx and n_workers > 1:
            return self._fetch_details_parallel(ctx, new_cards, ward_name, n_workers)
        else:
            return self._fetch_details_sequential(page, new_cards, ward_name)

    def _fetch_details_sequential(self, page, cards: list, ward_name: str) -> int:
        """Fallback: fetch detail tuần tự."""
        self.logger.info(f"Phase 2 — fetch {len(cards)} detail pages (sequential)")
        count = 0
        for i, card in enumerate(cards):
            detail = self._fetch_detail(page, card["url"])
            record = self._build_record(card, detail, ward_name=ward_name)
            if self.upsert_raw(card["url"], record):
                count += 1
                self.logger.info(
                    f"  [{i+1}/{len(cards)}] + {record['title'][:50]} | "
                    f"{record['price_ty']}ty {record['area_m2']}m²"
                )
            time.sleep(0.4)
        return count

    def _fetch_details_parallel(self, ctx, cards: list, ward_name: str, n_workers: int) -> int:
        """Fetch detail pages song song bằng ThreadPoolExecutor."""
        self.logger.info(
            f"Phase 2 — fetch {len(cards)} detail pages ({n_workers} workers)"
        )

        page_pool = queue.Queue()
        pages = []
        for _ in range(n_workers):
            p = ctx.new_page()
            p.set_default_timeout(30_000)
            pages.append(p)
            page_pool.put(p)

        count = 0
        done_count = 0

        def _worker(card):
            worker_page = page_pool.get()
            try:
                detail = self._fetch_detail(worker_page, card["url"])
                return card, detail
            finally:
                time.sleep(0.4)
                page_pool.put(worker_page)

        try:
            with ThreadPoolExecutor(max_workers=n_workers) as pool:
                futures = {pool.submit(_worker, card): card for card in cards}
                for future in as_completed(futures):
                    done_count += 1
                    try:
                        card, detail = future.result()
                        record = self._build_record(card, detail, ward_name=ward_name)
                        if self.upsert_raw(card["url"], record):
                            count += 1
                            self.logger.info(
                                f"  [{done_count}/{len(cards)}] + {record['title'][:50]} | "
                                f"{record['price_ty']}ty {record['area_m2']}m²"
                            )
                    except Exception as e:
                        self.logger.warning(f"  Detail worker error: {e}")
                        self._stats["errors"] += 1
        finally:
            for p in pages:
                try:
                    p.close()
                except Exception:
                    pass

        return count

    def crawl_full(self, page, base_url: str) -> int:
        return self._run_crawl(page, base_url, incremental=False)

    def crawl_incremental(self, page, base_url: str) -> int:
        return self._run_crawl(page, base_url, incremental=True)


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["full", "incremental"], default="full")
    p.add_argument("--visible", action="store_true")
    args = p.parse_args()
    stats = BatDongSanCrawler().run(mode=args.mode, headless=not args.visible)
    print(f"\nDone: {stats}")
