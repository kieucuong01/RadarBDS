"""
Guland Playwright Crawler — v2

Cải tiến:
  - Phase 1: Click "Xem thêm" liên tục (đúng với UI Guland, không dùng ?page=N)
  - Phase 2: Batch fetch detail pages bằng JS Promise.all (10 concurrent)
             → nhanh hơn sequential navigation ~8-10x

Full crawl  : python crawler/guland_pw.py --mode full
Incremental : python crawler/guland_pw.py --mode incremental
"""
import logging
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from crawler.base_crawler import BaseCrawler

logger = logging.getLogger(__name__)

BATCH_SIZE  = 5     # số detail pages fetch song song
BTN_WAIT_MS = 3000  # ms đợi sau khi click "Xem thêm"
MAX_CLICKS  = 50    # tăng giới hạn an toàn để cào nhiều phường

# JS extract toàn bộ cards từ DOM hiện tại
_JS_EXTRACT_CARDS = """
() => [...document.querySelectorAll('.c-sdb-card')].map(card => {
    const links = card.querySelectorAll('a[href*="/post/"]');
    const a = links.length > 1 ? links[1] : links[0];
    if (!a) return null;
    const titleEl = card.querySelector('.c-sdb-card__tle');
    const priceEl = card.querySelector('.sdb-inf-data.data-color-1.data-size-xl b');
    const infBs   = card.querySelectorAll('.sdb-inf-data.data-size-lg b');
    const dateEl  = card.querySelector('.profile-info__stl, .sdb-time, [class*="time"]');
    const imgs    = [...card.querySelectorAll('img')].map(i => i.getAttribute('data-src') || i.src).filter(s => s && s.startsWith('http') && !s.includes('logo') && !s.includes('avatar'));
    const postId  = a.href.match(/(\\d+)(?:\\.html)?$/)?.[1] || '';
    return {
        url:       a.href,
        post_id:   postId,
        title:     (titleEl || a).textContent.trim(),
        price_raw: priceEl?.textContent.trim() || '',
        area_raw:  infBs[0]?.textContent.trim() || '',
        pm2_raw:   infBs[1]?.textContent.trim() || '',
        date_raw:  dateEl?.textContent.trim() || '',
        imgs,
    };
}).filter(Boolean)
"""

# JS batch fetch detail pages (Promise.all — chạy trong Guland context)
_JS_BATCH_DETAIL = """
async (urls) => {
    const results = await Promise.all(urls.map(async url => {
        try {
            const r   = await fetch(url);
            const html = await r.text();
            const doc  = new DOMParser().parseFromString(html, 'text/html');

            const getText = sel => doc.querySelector(sel)?.textContent.trim() || '';
            const infoRow = getText('.dtl-inf__row');

            const extract = (...keys) => {
                for (const k of keys) {
                    const m = infoRow.match(new RegExp(k + '[\\\\s\\\\-:]+([^\\n]+?)(?=\\\\s{2,}|$)', 'i'));
                    if (m) return m[1].trim();
                }
                return '';
            };

            const phoneEl = doc.querySelector('[href^="tel:"]');
            const imgs    = [...doc.querySelectorAll('img')]
                                .map(i => i.getAttribute('data-src') || i.getAttribute('src'))
                                .filter(s => s && s.startsWith('http') && !s.includes('logo') && !s.includes('avatar'));

            return {
                url,
                description:       getText('.dtl-inf__dsr'),
                address:           getText('.dtl-stl__row, .dtl-adr'),
                property_type_raw: extract('Loại BĐS', 'Loại bds'),
                road_type_raw:     extract('Loại đường', 'Đường'),
                road_width_raw:    extract('Đường.hẻm vào rộng', 'Chiều rộng'),
                location_type_raw: extract('Vị trí'),
                legal_raw:         extract('Pháp lý'),
                contact_phone:     phoneEl ? phoneEl.href.replace('tel:', '') : '',
                detail_imgs:       imgs,
            };
        } catch(e) {
            return { url, error: e.message };
        }
    }));
    return results;
}
"""


class GulandCrawler(BaseCrawler):
    SOURCE_NAME = "guland"
    TARGET_URLS = [
        "https://guland.vn/mua-ban-bat-dong-san-phuong-tan-an-thanh-pho-thu-dau-mot-binh-duong",
        "https://guland.vn/mua-ban-bat-dong-san-phuong-tuong-binh-hiep-thanh-pho-thu-dau-mot-binh-duong",
        "https://guland.vn/mua-ban-bat-dong-san-phuong-hiep-an-thanh-pho-thu-dau-mot-binh-duong",
        "https://guland.vn/mua-ban-bat-dong-san-phuong-phu-my-thanh-pho-thu-dau-mot-binh-duong",
        "https://guland.vn/mua-ban-bat-dong-san-phuong-phu-tan-thanh-pho-thu-dau-mot-binh-duong",
        "https://guland.vn/mua-ban-bat-dong-san-phuong-chanh-my-thanh-pho-thu-dau-mot-binh-duong",
        "https://guland.vn/mua-ban-bat-dong-san-phuong-dinh-hoa-thanh-pho-thu-dau-mot-binh-duong",
        "https://guland.vn/mua-ban-bat-dong-san-phuong-chanh-nghia-thanh-pho-thu-dau-mot-binh-duong",
        "https://guland.vn/mua-ban-bat-dong-san-phuong-phu-tho-thanh-pho-thu-dau-mot-binh-duong",
        "https://guland.vn/mua-ban-bat-dong-san-phuong-phu-hoa-thanh-pho-thu-dau-mot-binh-duong",
        "https://guland.vn/mua-ban-bat-dong-san-phuong-phu-cuong-thanh-pho-thu-dau-mot-binh-duong",
        "https://guland.vn/mua-ban-bat-dong-san-phuong-hiep-thanh-thanh-pho-thu-dau-mot-binh-duong",
        "https://guland.vn/mua-ban-bat-dong-san-phuong-phu-loi-thanh-pho-thu-dau-mot-binh-duong"
    ]

    WARD_MAP = {
        "tan-an": "Tân An",
        "tuong-binh-hiep": "Tương Bình Hiệp",
        "hiep-an": "Hiệp An",
        "phu-my": "Phú Mỹ",
        "phu-tan": "Phú Tân",
        "chanh-my": "Chánh Mỹ",
        "dinh-hoa": "Định Hòa",
        "chanh-nghia": "Chánh Nghĩa",
        "phu-tho": "Phú Thọ",
        "phu-hoa": "Phú Hòa",
        "phu-cuong": "Phú Cường",
        "hiep-thanh": "Hiệp Thành",
        "phu-loi": "Phú Lợi"
    }

    # ── Phase 1: Scroll hết cards bằng click "Xem thêm" ──────────────────

    def _scroll_all_cards(self, page, base_url: str, incremental: bool = False) -> list:
        """
        Load toàn bộ listing cards bằng cách click "Xem thêm".
        incremental=True: dừng sớm khi gặp tin cũ.
        """
        page.goto(base_url, wait_until="domcontentloaded", timeout=30_000)
        try:
            page.wait_for_selector(".c-sdb-card", timeout=15_000)
        except Exception:
            self.logger.warning("Không tìm thấy .c-sdb-card")
            return []

        for click_num in range(MAX_CLICKS + 1):
            # Đọc cards hiện tại
            cards = page.evaluate(_JS_EXTRACT_CARDS) or []

            # Incremental: kiểm tra tin cũ
            if incremental and cards:
                old_cards = [c for c in cards if self.is_old(c.get("date_raw", ""))]
                if old_cards:
                    self.logger.info(
                        f"  Incremental: gặp {len(old_cards)} tin cũ → dừng scroll"
                    )
                    break

            # Kiểm tra nút "Xem thêm"
            btn_visible = page.evaluate("""
                () => {
                    const btn = document.querySelector('#btn-load-more');
                    if (!btn) return false;
                    // Visible nếu không có d-none và display không phải none
                    if (btn.classList.contains('d-none')) return false;
                    return btn.offsetParent !== null;
                }
            """)

            if not btn_visible:
                self.logger.info(f"  Không còn nút 'Xem thêm' sau {click_num} lần click")
                break

            # Click button
            prev_count = len(cards)
            page.click("#btn-load-more")
            page.wait_for_timeout(BTN_WAIT_MS)

            new_cards = page.evaluate(_JS_EXTRACT_CARDS) or []
            self.logger.info(
                f"  Click {click_num+1}: {prev_count} → {len(new_cards)} cards "
                f"(+{len(new_cards)-prev_count})"
            )

            # Không có cards mới → trang hết dữ liệu
            if len(new_cards) <= prev_count:
                self.logger.info("  Không có cards mới sau click → dừng")
                break

        # Trả về cards cuối cùng
        final_cards = page.evaluate(_JS_EXTRACT_CARDS) or []
        self.logger.info(f"  Tổng: {len(final_cards)} cards")
        return [c for c in final_cards if c and c.get("url")]

    # ── Phase 2: Batch fetch detail pages ─────────────────────────────────

    def _fetch_details_batch(self, page, urls: list) -> dict:
        """
        Fetch N detail pages song song bằng JS Promise.all.
        Trả về dict {url: detail_dict}.
        """
        url_to_detail = {}
        total = len(urls)

        for i in range(0, total, BATCH_SIZE):
            batch = urls[i:i + BATCH_SIZE]
            try:
                results = page.evaluate(_JS_BATCH_DETAIL, batch)
                for r in (results or []):
                    if r and r.get("url"):
                        url_to_detail[r["url"]] = r
            except Exception as e:
                self.logger.warning(f"Batch fetch error (batch {i//BATCH_SIZE+1}): {e}")
            done = min(i + BATCH_SIZE, total)
            self.logger.info(f"  Detail batch: {done}/{total}")
            time.sleep(0.3)

        return url_to_detail

    # ── Build record ───────────────────────────────────────────────────────

    def _build_record(self, card: dict, detail: dict) -> dict:
        url = card["url"]
        
        # Suy luận phường từ URL Guland (thường có dạng .../phuong-ten-phuong-...)
        m_ward = re.search(r'phuong-([a-z0-9-]+)-thanh-pho', url)
        ward_slug = m_ward.group(1) if m_ward else ""
        ward_display = self.WARD_MAP.get(ward_slug, ward_slug.replace('-', ' ').title())

        price_ty = self.parse_price_ty(card.get("price_raw", ""))
        area_m2  = self.parse_area_m2(card.get("area_raw", ""))
        ppm2     = self.parse_ppm2(card.get("pm2_raw", ""))
        if not ppm2 and price_ty and area_m2 and area_m2 > 0:
            ppm2 = round(price_ty * 1e9 / area_m2 / 1e6, 2)

        return {
            "url":               url,
            "post_id":           card.get("post_id", ""),
            "title":             card.get("title", ""),
            "description":       detail.get("description", ""),
            "address":           detail.get("address", ""),
            "price_ty":          price_ty,
            "area_m2":           area_m2,
            "price_per_m2":      ppm2,
            "area_name":         ward_display or "TDM",
            "ward":              ward_display,
            "property_type_raw": detail.get("property_type_raw", ""),
            "road_type_raw":     detail.get("road_type_raw", ""),
            "road_width_raw":    detail.get("road_width_raw", ""),
            "location_type_raw": detail.get("location_type_raw", ""),
            "legal_raw":         detail.get("legal_raw", ""),
            "contact_phone":     detail.get("contact_phone", ""),
            "imgs":              detail.get("detail_imgs", []) or card.get("imgs", []),
            "date_raw":          card.get("date_raw", ""),
            "tx_type":           "ban",
            "province":          "Bình Dương",
            "district":          "Thủ Dầu Một",
            "source":            self.SOURCE_NAME,
        }

    # ── Core crawl ─────────────────────────────────────────────────────────

    def _run_crawl(self, page, base_url: str, incremental: bool) -> int:
        # Phase 1: Scroll/load tất cả cards
        self.logger.info(f"Phase 1 — scroll cards ({'incremental' if incremental else 'full'})")
        all_cards = self._scroll_all_cards(page, base_url, incremental=incremental)

        # Filter chỉ lấy URL mới chưa có trong DB
        new_cards = [c for c in all_cards if not self.url_exists(c["url"])]
        self.logger.info(
            f"Phase 1 done: {len(all_cards)} total | "
            f"{len(new_cards)} mới | {len(all_cards)-len(new_cards)} đã có trong DB"
        )

        if not new_cards:
            return 0

        # Phase 2: Batch fetch detail pages (chỉ cho URL mới)
        self.logger.info(f"Phase 2 — batch fetch {len(new_cards)} detail pages (batch={BATCH_SIZE})")
        new_urls = [c["url"] for c in new_cards]
        url_to_detail = self._fetch_details_batch(page, new_urls)

        # Upsert vào DB
        count = 0
        for card in new_cards:
            detail = url_to_detail.get(card["url"], {})
            record = self._build_record(card, detail)
            if self.upsert_raw(card["url"], record):
                count += 1
                self.logger.info(
                    f"  + {record['title'][:50]} | "
                    f"{record['price_ty']}ty {record['area_m2']}m²"
                )

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
    stats = GulandCrawler().run(mode=args.mode, headless=not args.visible)
    print(f"\nDone: {stats}")
