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
import logging
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from crawler.base_crawler import BaseCrawler

logger = logging.getLogger(__name__)

BASE = "https://batdongsan.com.vn"

SEARCH_SLUGS = [
    # ban-dat (đất nền)
    "ban-dat-phuong-tan-an_1",
    "ban-dat-phuong-tuong-binh-hiep_1",
    "ban-dat-phuong-hiep-an_1",
    "ban-dat-phuong-chanh-my_1",
    "ban-dat-phuong-phu-my_1",
    "ban-dat-phuong-phu-tan_1",
    "ban-dat-phuong-chanh-nghia_1",
    "ban-dat-phuong-dinh-hoa_1",
    "ban-dat-phuong-phu-tho_1",
    "ban-dat-phuong-phu-hoa_1",
    "ban-dat-phuong-phu-cuong_1",
    "ban-dat-phuong-hiep-thanh_1",
    "ban-dat-phuong-phu-loi_1",
    # ban-nha (nhà ở)
    "ban-nha-phuong-tan-an_1",
    "ban-nha-phuong-tuong-binh-hiep_1",
    "ban-nha-phuong-hiep-an_1",
    "ban-nha-phuong-chanh-my_1",
    "ban-nha-phuong-phu-my_1",
    "ban-nha-phuong-phu-tan_1",
    "ban-nha-phuong-chanh-nghia_1",
    "ban-nha-phuong-dinh-hoa_1",
    "ban-nha-phuong-phu-tho_1",
    "ban-nha-phuong-phu-hoa_1",
    "ban-nha-phuong-phu-cuong_1",
    "ban-nha-phuong-hiep-thanh_1",
    "ban-nha-phuong-phu-loi_1",
]

DETAIL_WORKERS  = 3    # số pages song song khi fetch detail
SLUG_DELAY_S    = 8    # delay giữa các slug để tránh Cloudflare rate-limit
PAGE_DELAY_S    = 3    # delay giữa các listing pages trong 1 slug


class BatDongSanCrawler(BaseCrawler):
    SOURCE_NAME = "batdongsan"
    TARGET_URLS = [f"{BASE}/{slug}" for slug in SEARCH_SLUGS]

    # ── Phase 1: Collect listing cards ────────────────────────────────────

    def _get_cards_on_page(self, page, url: str) -> list:
        """Navigate listing page, extract cards. Trả về list dict."""
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            page.wait_for_selector(".js__card", timeout=20_000)
        except Exception as e:
            # Phân biệt trang rỗng vs Cloudflare block
            page_title = ""
            try:
                page_title = page.title()
            except Exception:
                pass
            if "Just a moment" in page_title or "Cloudflare" in page_title:
                self.logger.warning(f"Cloudflare block {url}: {page_title}")
            else:
                self.logger.info(f"No cards (empty or slow): {url}")
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
            page.goto(url, wait_until="domcontentloaded", timeout=25_000)
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

    def _build_record(self, card: dict, detail: dict) -> dict:
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
            "area_name":     "Tân An",
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

    _slug_count = 0  # đếm số slug đã crawl trong session này

    def _run_crawl(self, page, base_url: str, incremental: bool) -> int:
        # Delay giữa các slug (trừ slug đầu tiên)
        BatDongSanCrawler._slug_count += 1
        if BatDongSanCrawler._slug_count > 1:
            self.logger.info(f"  Waiting {SLUG_DELAY_S}s trước slug tiếp theo (chống rate-limit)...")
            time.sleep(SLUG_DELAY_S)

        # Phase 1: collect tất cả listing cards
        self.logger.info(f"Phase 1 — collect cards từ {base_url}")
        all_cards = self._collect_all_urls(page, base_url, incremental=incremental)

        # Lọc chỉ URL mới
        new_cards = [c for c in all_cards if not self.url_exists(c["url"])]
        self.logger.info(
            f"Phase 1 done: {len(all_cards)} total | "
            f"{len(new_cards)} mới | {len(all_cards)-len(new_cards)} đã có"
        )

        if not new_cards:
            return 0

        # Phase 2: fetch detail cho từng URL mới
        self.logger.info(f"Phase 2 — fetch {len(new_cards)} detail pages")
        count = 0
        for i, card in enumerate(new_cards):
            detail = self._fetch_detail(page, card["url"])
            record = self._build_record(card, detail)
            if self.upsert_raw(card["url"], record):
                count += 1
                self.logger.info(
                    f"  [{i+1}/{len(new_cards)}] + {record['title'][:50]} | "
                    f"{record['price_ty']}ty {record['area_m2']}m²"
                )
            time.sleep(0.4)

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
