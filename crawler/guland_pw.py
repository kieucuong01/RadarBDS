"""
Guland Playwright Crawler — v2

Cải tiến:
  - Phase 1: Click "Xem thêm" liên tục (đúng với UI Guland, không dùng ?page=N)
  - Phase 2: Batch fetch detail pages bằng JS Promise.all (10 concurrent)
             → nhanh hơn sequential navigation ~8-10x

Full crawl  : python crawler/guland_pw.py --mode full
Incremental : python crawler/guland_pw.py --mode incremental
"""
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent.parent))
from crawler.base_crawler import BaseCrawler
from analytics.lifecycle import mark_source_seen, record_source_check
from db.connection import get_conn
from services.guland_reconciliation import (
    ExistingGulandSnapshot,
    canonical_price_vnd,
    plan_guland_cards,
)
from services.guland_coordinates import (
    evaluate_guland_coordinate_url,
    raw_coordinate_fields,
)
from services.market_data import get_city_for_ward

logger = logging.getLogger(__name__)

BATCH_SIZE  = 5     # số detail pages fetch song song
BTN_WAIT_MS = 3000  # ms đợi sau khi click "Xem thêm"
MAX_CLICKS  = 50    # tăng giới hạn an toàn để cào nhiều phường

GULAND_SOURCES_FILE = Path(__file__).parent.parent / "data" / "guland_sources.json"
GULAND_URL_PREFIX   = "https://guland.vn/"
DEFAULT_CRAWL_FOR_DAYS = 7

_CSS_URL_RE = re.compile(r"""url\(["']?([^"')]+)["']?\)""", re.IGNORECASE)
_GULAND_IMAGE_EXT_RE = re.compile(r"\.(?:jpe?g|png|webp)(?:$|\?)", re.IGNORECASE)
_GULAND_PI_IMAGE_RE = re.compile(
    r"/(?:detail|listing)/(pi-\d+)-\d+\.(?:jpe?g|png|webp)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DetailClassification:
    outcome: str
    reason: str


def classify_detail_result(detail: dict | None) -> DetailClassification:
    detail = detail or {}
    if detail.get("error"):
        return DetailClassification("unreachable", str(detail["error"])[:200])

    try:
        http_status = int(detail.get("http_status") or 0)
    except (TypeError, ValueError):
        http_status = 0
    page_status = str(detail.get("page_status") or "").lower()
    if http_status in {404, 410} or page_status == "removed":
        return DetailClassification("removed", page_status or f"http_{http_status}")
    if page_status == "live" and 200 <= http_status < 400:
        return DetailClassification("active", "live_detail")
    return DetailClassification(
        "unreachable",
        page_status or (f"http_{http_status}" if http_status else "invalid_response"),
    )


def extract_guland_post_id(post_url: str) -> str:
    """Extract the numeric post id from a Guland /post/...-<id> URL."""
    parsed = urlparse(str(post_url or ""))
    path = parsed.path.rstrip("/")
    match = re.search(r"-(\d+)(?:\.html)?$", path)
    if match:
        return match.group(1)
    match = re.search(r"/post/(\d+)(?:\.html)?$", path)
    return match.group(1) if match else ""


def _clean_guland_image_candidate(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    match = _CSS_URL_RE.fullmatch(text)
    if match:
        text = match.group(1).strip()
    return text.strip("\"'")


def _guland_image_dedupe_key(url: str) -> str:
    parsed = urlparse(url)
    match = _GULAND_PI_IMAGE_RE.search(parsed.path)
    if match:
        post_match = re.search(r"/posts/(\d+)/", parsed.path)
        return f"post:{post_match.group(1) if post_match else ''}:{match.group(1).lower()}"
    return url


def extract_guland_image_urls_from_dom_candidates(post_url: str, candidates: list) -> list[str]:
    """Filter mixed Guland DOM candidates to real images for one post.

    Guland detail pages often put listing photos in CSS background-image on
    divs while img src is only a 1x1 lazy placeholder. The post-id filter is
    required because the same page also includes related listing photos.
    """
    post_id = extract_guland_post_id(post_url)
    if not post_id:
        return []

    accepted: list[str] = []
    seen: set[str] = set()
    for candidate in candidates or []:
        url = _clean_guland_image_candidate(candidate)
        if not url or not url.startswith(("http://", "https://")):
            continue
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        path = parsed.path
        if host not in {"bizcdn.guland.vn", "datacdn.guland.vn"}:
            continue
        if not _GULAND_IMAGE_EXT_RE.search(path):
            continue
        if f"/posts/{post_id}/" not in path and f"/data/{post_id}/" not in path:
            continue
        if any(bad in path.lower() for bad in ("/users/", "avatar", "logo", "profile")):
            continue
        key = _guland_image_dedupe_key(url)
        if key in seen:
            continue
        seen.add(key)
        accepted.append(url)
    return accepted


def _default_guland_urls(slug: str) -> list:
    """4 URL types/ward: đất thổ cư, nhà mặt phố, chung cư, kho xưởng."""
    return [
        f"mua-ban-dat-tho-cu-{slug}",
        f"mua-ban-nha-mat-pho-mat-tien-{slug}",
        f"mua-ban-can-ho-chung-cu-{slug}",
        f"mua-ban-kho-nha-xuong-{slug}",
    ]

# JS extract toàn bộ cards từ DOM hiện tại
_JS_EXTRACT_CARDS = """
() => {
  const listingImages = (root, postId) => {
    if (!postId) return [];
    const badParent = [
      '.profile-info',
      '[class*="avatar"]',
      '[class*="author"]',
      '[class*="broker"]',
      '[class*="contact"]',
      '[class*="member"]',
      '[class*="profile"]',
      '[class*="seller"]',
      '[class*="user"]'
    ].join(',');
    const badAsset = /(avatar|author|broker|contact|logo|member|profile|seller|placeholder|no-image)/i;
    const imageExt = /\\.(?:jpe?g|png|webp)(?:$|\\?)/i;
    const cssUrls = (value) => [...String(value || '').matchAll(/url\\(["']?([^"')]+)["']?\\)/g)].map(m => m[1]);
    const keyFor = (url) => {
      const m = String(url || '').match(/\\/(?:detail|listing)\\/(pi-\\d+)-\\d+\\.(?:jpe?g|png|webp)/i);
      return m ? `pi:${m[1].toLowerCase()}` : url;
    };
    const seen = new Set();
    const out = [];
    const push = (src, label) => {
      let s = String(src || '').trim().replace(/^url\\(["']?/, '').replace(/["']?\\)$/, '');
      if (!s || !s.startsWith('http')) return;
      if (badAsset.test(s) || badAsset.test(label || '')) return;
      if (!/(?:bizcdn|datacdn)\\.guland\\.vn/i.test(s)) return;
      if (!imageExt.test(s)) return;
      if (!s.includes(`/posts/${postId}/`) && !s.includes(`/data/${postId}/`)) return;
      const key = keyFor(s);
      if (seen.has(key)) return;
      seen.add(key);
      out.push(s);
    };
    [...root.querySelectorAll('img')]
      .filter(i => !i.closest(badParent))
      .forEach(i => {
        const label = [i.getAttribute('alt'), i.getAttribute('title'), i.className, i.parentElement?.className].join(' ');
        if (badAsset.test(label)) return;
        const w = parseInt(i.getAttribute('width') || i.naturalWidth || i.width || '0', 10);
        const h = parseInt(i.getAttribute('height') || i.naturalHeight || i.height || '0', 10);
        if (w && h && Math.max(w, h) < 120 && !i.getAttribute('data-original')) return;
        [
          i.getAttribute('data-original'),
          i.getAttribute('data-src'),
          i.getAttribute('data-lazy'),
          i.currentSrc,
          i.getAttribute('src'),
          i.getAttribute('srcset')
        ].forEach(value => String(value || '').split(/\\s*,\\s*|\\s+/).forEach(src => push(src, label)));
      });
    [...root.querySelectorAll('*')].forEach(el => {
      const label = [el.className, el.getAttribute('aria-label'), el.getAttribute('title')].join(' ');
      [
        el.getAttribute('style'),
        el.getAttribute('data-bg'),
        el.getAttribute('data-background'),
        el.getAttribute('data-original')
      ].forEach(value => cssUrls(value).forEach(src => push(src, label)));
      try {
        cssUrls(getComputedStyle(el).backgroundImage).forEach(src => push(src, label));
      } catch (_e) {}
    });
    return out;
  };

  return [...document.querySelectorAll('.c-sdb-card')].map(card => {
    const links = card.querySelectorAll('a[href*="/post/"]');
    const a = links.length > 1 ? links[1] : links[0];
    if (!a) return null;
    const titleEl = card.querySelector('.c-sdb-card__tle');
    const priceEl = card.querySelector('.sdb-inf-data.data-color-1.data-size-xl b');
    const infBs   = card.querySelectorAll('.sdb-inf-data.data-size-lg b');
    const dateEl  = card.querySelector('.profile-info__stl, .sdb-time, [class*="time"]');
    const postId  = a.href.match(/(\\d+)(?:\\.html)?$/)?.[1] || '';
    const imgs    = listingImages(card, postId);
    const coordinateLink = [...card.querySelectorAll(
      'a[href^="https://www.google.com/maps/search/"]'
    )].find(link => {
      const text = (link.textContent || '').trim().toLowerCase();
      return text.includes('chỉ đường') || link.href.includes('api=1');
    });
    return {
        url:       a.href,
        post_id:   postId,
        title:     (titleEl || a).textContent.trim(),
        price_raw: priceEl?.textContent.trim() || '',
        area_raw:  infBs[0]?.textContent.trim() || '',
        pm2_raw:   infBs[1]?.textContent.trim() || '',
        date_raw:  dateEl?.textContent.trim() || '',
        source_coordinate_url: coordinateLink?.href || '',
        imgs,
    };
  }).filter(Boolean);
}
"""

# JS batch fetch detail pages (Promise.all — chạy trong Guland context)
_JS_BATCH_DETAIL = """
async (urls) => {
    const listingImages = (root, postId, html) => {
        if (!postId) return [];
        const badParent = [
            '.profile-info',
            '[class*="avatar"]',
            '[class*="author"]',
            '[class*="broker"]',
            '[class*="contact"]',
            '[class*="member"]',
            '[class*="profile"]',
            '[class*="seller"]',
            '[class*="user"]'
        ].join(',');
        const badAsset = /(avatar|author|broker|contact|logo|member|profile|seller|placeholder|no-image)/i;
        const imageExt = /\\.(?:jpe?g|png|webp)(?:$|\\?)/i;
        const cssUrls = (value) => [...String(value || '').matchAll(/url\\(["']?([^"')]+)["']?\\)/g)].map(m => m[1]);
        const keyFor = (url) => {
            const m = String(url || '').match(/\\/(?:detail|listing)\\/(pi-\\d+)-\\d+\\.(?:jpe?g|png|webp)/i);
            return m ? `pi:${m[1].toLowerCase()}` : url;
        };
        const seen = new Set();
        const out = [];
        const push = (src, label) => {
            let s = String(src || '').trim().replace(/^url\\(["']?/, '').replace(/["']?\\)$/, '');
            if (!s || !s.startsWith('http')) return;
            if (badAsset.test(s) || badAsset.test(label || '')) return;
            if (!/(?:bizcdn|datacdn)\\.guland\\.vn/i.test(s)) return;
            if (!imageExt.test(s)) return;
            if (!s.includes(`/posts/${postId}/`) && !s.includes(`/data/${postId}/`)) return;
            const key = keyFor(s);
            if (seen.has(key)) return;
            seen.add(key);
            out.push(s);
        };
        [...root.querySelectorAll('img')]
            .filter(i => !i.closest(badParent))
            .forEach(i => {
                const label = [i.getAttribute('alt'), i.getAttribute('title'), i.className, i.parentElement?.className].join(' ');
                if (badAsset.test(label)) return;
                const w = parseInt(i.getAttribute('width') || i.naturalWidth || i.width || '0', 10);
                const h = parseInt(i.getAttribute('height') || i.naturalHeight || i.height || '0', 10);
                if (w && h && Math.max(w, h) < 120 && !i.getAttribute('data-original')) return;
                [
                    i.getAttribute('data-original'),
                    i.getAttribute('data-src'),
                    i.getAttribute('data-lazy'),
                    i.getAttribute('src'),
                    i.getAttribute('srcset')
                ].forEach(value => String(value || '').split(/\\s*,\\s*|\\s+/).forEach(src => push(src, label)));
            });
        [...root.querySelectorAll('*')].forEach(el => {
            const label = [el.className, el.getAttribute('aria-label'), el.getAttribute('title')].join(' ');
            [
                el.getAttribute('style'),
                el.getAttribute('data-bg'),
                el.getAttribute('data-background'),
                el.getAttribute('data-original')
            ].forEach(value => cssUrls(value).forEach(src => push(src, label)));
        });
        [...String(html || '').matchAll(/https?:\\/\\/(?:bizcdn|datacdn)\\.guland\\.vn[^"'\\)\\s\\\\]+/gi)]
            .forEach(match => push(match[0], 'html'));
        return out;
    };

    const results = await Promise.all(urls.map(async url => {
        try {
            const r   = await fetch(url);
            const html = await r.text();
            const doc  = new DOMParser().parseFromString(html, 'text/html');
            const postId = (url.match(/-(\\d+)(?:\\.html)?\\/?$/) || [])[1] || '';
            const responsePath = (() => {
                try { return new URL(r.url || url).pathname.toLowerCase(); }
                catch (_e) { return ''; }
            })();

            const getText = sel => doc.querySelector(sel)?.textContent.trim() || '';
            const infoRow = getText('.dtl-inf__row');
            const bodyText = (doc.body?.textContent || '').replace(/\\s+/g, ' ').trim();
            const removedText = /tin.*(?:đã|bị).*(?:gỡ|xóa)|tin.*không.*tồn tại/i.test(bodyText);
            const explicitlyRemoved = [404, 410].includes(r.status)
                || responsePath.includes('/khong-tim-thay')
                || removedText;
            const identityPresent = Boolean(
                postId && (
                    doc.querySelector('.dtl-inf__dsr, .dtl-inf__row, .dtl-stl__row, .dtl-adr')
                    || doc.querySelector(`a[href*="/post/"][href*="${postId}"]`)
                )
            );
            const detailPriceEl = doc.querySelector(
                'meta[itemprop="price"], [itemprop="price"], .dtl-inf__prc, .dtl-inf__price, .dtl-prc'
            );
            const detailPriceRaw = detailPriceEl?.getAttribute?.('content')
                || detailPriceEl?.textContent?.trim()
                || '';
            const pageStatus = explicitlyRemoved
                ? 'removed'
                : (r.ok && identityPresent ? 'live' : 'unreachable');

            const extract = (...keys) => {
                for (const k of keys) {
                    const m = infoRow.match(new RegExp(k + '[\\\\s\\\\-:]+([^\\n]+?)(?=\\\\s{2,}|$)', 'i'));
                    if (m) return m[1].trim();
                }
                return '';
            };

            const phoneEl = doc.querySelector('[href^="tel:"]');
            const imgs    = listingImages(doc, postId, html);

            return {
                url,
                http_status:      r.status,
                page_status:      pageStatus,
                detail_price_raw: detailPriceRaw,
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
            return {
                url,
                http_status: null,
                page_status: 'unreachable',
                detail_price_raw: '',
                error: e.message
            };
        }
    }));
    return results;
}
"""


class GulandCrawler(BaseCrawler):
    SOURCE_NAME = "guland"

    # Fallback nếu thiếu/lỗi data/guland_sources.json
    _FALLBACK_WARDS = [
        ("Tân An",          "phuong-tan-an-thanh-pho-thu-dau-mot-binh-duong"),
        ("Tương Bình Hiệp", "phuong-tuong-binh-hiep-thanh-pho-thu-dau-mot-binh-duong"),
        ("Hiệp An",         "phuong-hiep-an-thanh-pho-thu-dau-mot-binh-duong"),
        ("Phú Mỹ",          "phuong-phu-my-thanh-pho-thu-dau-mot-binh-duong"),
        ("Phú Tân",         "phuong-phu-tan-thanh-pho-thu-dau-mot-binh-duong"),
        ("Chánh Mỹ",        "phuong-chanh-my-thanh-pho-thu-dau-mot-binh-duong"),
        ("Định Hòa",        "phuong-dinh-hoa-thanh-pho-thu-dau-mot-binh-duong"),
        ("Chánh Nghĩa",     "phuong-chanh-nghia-thanh-pho-thu-dau-mot-binh-duong"),
        ("Phú Thọ",         "phuong-phu-tho-thanh-pho-thu-dau-mot-binh-duong"),
        ("Phú Hòa",         "phuong-phu-hoa-thanh-pho-thu-dau-mot-binh-duong"),
        ("Phú Cường",       "phuong-phu-cuong-thanh-pho-thu-dau-mot-binh-duong"),
        ("Hiệp Thành",      "phuong-hiep-thanh-thanh-pho-thu-dau-mot-binh-duong"),
        ("Phú Lợi",         "phuong-phu-loi-thanh-pho-thu-dau-mot-binh-duong"),
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        wards, days = self._load_sources_config()
        self.TARGET_URLS = []
        self.WARD_MAP    = {}
        for w in wards:
            urls = w.get("urls") or _default_guland_urls(w["slug"])
            self.WARD_MAP[self._slug_to_ward_key(w["slug"])] = w["name"]
            for u in urls:
                self.TARGET_URLS.append(GULAND_URL_PREFIX + u)
        self.crawl_for_days = days
        logger.info(
            f"[guland] Loaded {len(wards)} wards = {len(self.TARGET_URLS)} URLs "
            f"| crawl_for_days={days}"
        )

    @staticmethod
    def _slug_to_ward_key(slug: str) -> str:
        """phuong-tan-an-thanh-pho-... → 'tan-an' (key cũ trong WARD_MAP)."""
        # bỏ prefix 'phuong-' và phần sau 'thanh-pho-...'
        s = slug
        if s.startswith("phuong-"):
            s = s[len("phuong-"):]
        idx = s.find("-thanh-pho-")
        if idx > 0:
            s = s[:idx]
        return s

    @classmethod
    def _load_sources_config(cls):
        try:
            data = json.loads(GULAND_SOURCES_FILE.read_text(encoding="utf-8"))
            wards = data.get("wards") or []
            days  = int(data.get("crawl_for_days") or DEFAULT_CRAWL_FOR_DAYS)
            wards = [w for w in wards if w.get("slug") and w.get("name")]
            if wards:
                return wards, days
            logger.warning(f"[guland] {GULAND_SOURCES_FILE.name}: wards rỗng → dùng fallback")
        except FileNotFoundError:
            logger.warning(f"[guland] Không thấy {GULAND_SOURCES_FILE.name} → dùng fallback")
        except Exception as e:
            logger.warning(f"[guland] Lỗi parse {GULAND_SOURCES_FILE.name}: {e} → dùng fallback")
        wards = [{"name": n, "slug": s} for n, s in cls._FALLBACK_WARDS]
        return wards, DEFAULT_CRAWL_FOR_DAYS

    def is_old(self, date_raw: str) -> bool:
        """Override: dừng load-more khi gặp tin cũ hơn crawl_for_days ngày."""
        s = (date_raw or "").lower().strip()
        if not s:
            return False
        m = re.search(r"(\d+)\s*ngày", s)
        if m and int(m.group(1)) > getattr(self, "crawl_for_days", DEFAULT_CRAWL_FOR_DAYS):
            return True
        if re.search(r"\d+\s*(tuần|tháng|năm)", s):
            # tuần >= 1 ~7 ngày — nếu crawl_for_days < 7 thì coi là cũ; ngược lại
            # vẫn để regex chính xác qua match trên 'tuần'.
            tweek = re.search(r"(\d+)\s*tuần", s)
            if tweek:
                if int(tweek.group(1)) * 7 > getattr(self, "crawl_for_days", DEFAULT_CRAWL_FOR_DAYS):
                    return True
            else:
                return True
        return False

    # ── Phase 1: Scroll hết cards bằng click "Xem thêm" ──────────────────

    def _scroll_all_cards(self, page, base_url: str, incremental: bool = False) -> list:
        """
        Load toàn bộ listing cards bằng cách click "Xem thêm".
        incremental=True: dừng sớm khi gặp tin cũ.
        """
        try:
            self._retry(
                lambda: page.goto(base_url, wait_until="domcontentloaded", timeout=30_000),
                max_retries=2, base_delay=3.0, label=f"goto {base_url}"
            )
            page.wait_for_selector(".c-sdb-card", timeout=15_000)
        except Exception:
            self.logger.warning(f"Không tìm thấy .c-sdb-card trên {base_url}")
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
                results = self._retry(
                    lambda b=batch: page.evaluate(_JS_BATCH_DETAIL, b),
                    max_retries=2, base_delay=1.0, label=f"batch {i//BATCH_SIZE+1}"
                )
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

        # The configured list URL carries the canonical ward context. The
        # individual /post/ URL does not reliably contain it.
        ward_source_url = str(card.get("source_list_url") or "")
        m_ward = re.search(
            r"phuong-([a-z0-9-]+)-thanh-pho",
            ward_source_url,
        )
        ward_slug = m_ward.group(1) if m_ward else ""
        ward_display = self.WARD_MAP.get(
            ward_slug,
            ward_slug.replace("-", " ").title(),
        )

        price_ty = self.parse_price_ty(card.get("price_raw", ""))
        area_m2  = self.parse_area_m2(card.get("area_raw", ""))
        ppm2     = self.parse_ppm2(card.get("pm2_raw", ""))
        if not ppm2 and price_ty and area_m2 and area_m2 > 0:
            ppm2 = round(price_ty * 1e9 / area_m2 / 1e6, 2)

        record = {
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
        city = get_city_for_ward(ward_display)
        context_text = " ".join(filter(None, (
            record["title"],
            record["description"],
            record["address"],
        )))
        decision = evaluate_guland_coordinate_url(
            card.get("source_coordinate_url", ""),
            city=city,
            ward=ward_display,
            context_text=context_text,
        )
        if decision.status == "valid":
            captured_at = datetime.now(
                ZoneInfo("Asia/Ho_Chi_Minh")
            ).isoformat()
            record.update(raw_coordinate_fields(decision, captured_at))
        elif decision.status == "invalid":
            self.logger.warning(
                "Rejected Guland coordinate post_id=%s reason=%s",
                record["post_id"],
                decision.reason,
            )
        return record

    # ── Core crawl ─────────────────────────────────────────────────────────

    def _ensure_reconciliation_stats(self) -> None:
        defaults = {
            "fetched": 0,
            "new": 0,
            "existing": 0,
            "unchanged": 0,
            "updated": 0,
            "invalid_price": 0,
            "skipped": 0,
            "errors": 0,
            "error_details": [],
            "inserted_raw_ids": [],
            "refreshed_raw_ids": [],
        }
        for key, value in defaults.items():
            if key not in self._stats:
                self._stats[key] = list(value) if isinstance(value, list) else value

    def _load_existing_snapshots(
        self,
        urls: list[str],
    ) -> dict[str, ExistingGulandSnapshot]:
        unique_urls = list(dict.fromkeys(url for url in urls if url))
        if not unique_urls:
            return {}
        snapshots: dict[str, ExistingGulandSnapshot] = {}
        with get_conn() as conn:
            for offset in range(0, len(unique_urls), 500):
                chunk = unique_urls[offset:offset + 500]
                placeholders = ",".join("?" * len(chunk))
                rows = conn.execute(
                    f"""
                    SELECT r.id AS raw_id, l.id AS listing_id, r.url,
                           r.source_id, l.price_ty, l.first_seen_at,
                           COALESCE(l.source_status, 'unknown') AS source_status
                    FROM raw_listings r
                    JOIN listings l ON l.raw_id=r.id
                    WHERE r.source='guland' AND r.url IN ({placeholders})
                    """,
                    tuple(chunk),
                ).fetchall()
                for row in rows:
                    snapshots[row["url"]] = ExistingGulandSnapshot(
                        raw_id=int(row["raw_id"]),
                        listing_id=int(row["listing_id"]),
                        url=row["url"],
                        source_id=row["source_id"],
                        price_ty=row["price_ty"],
                        first_seen_at=row["first_seen_at"],
                        source_status=row["source_status"],
                    )
        return snapshots

    def _mark_seen_urls(self, urls: list[str]) -> int:
        with get_conn() as conn:
            return mark_source_seen(conn, self.SOURCE_NAME, urls)

    def _insert_new_record(self, card: dict, record: dict) -> int | None:
        if not self.upsert_raw(card["url"], record):
            return None
        result = getattr(self, "_last_raw_insert_result", None)
        return int(result.raw_id) if result and result.raw_id else None

    def _refresh_changed_record(
        self,
        snapshot: ExistingGulandSnapshot,
        record: dict,
    ) -> int:
        with get_conn() as conn:
            cur = conn.execute(
                """
                UPDATE raw_listings
                SET raw_json=?, crawled_at=datetime('now'), crawl_run_id=?
                WHERE id=? AND source='guland' AND url=?
                """,
                (
                    json.dumps(record, ensure_ascii=False),
                    getattr(self, "_crawl_run_id", None),
                    snapshot.raw_id,
                    snapshot.url,
                ),
            )
            if cur.rowcount != 1:
                raise LookupError(f"Guland raw listing not found: {snapshot.raw_id}")
        return snapshot.raw_id

    def _track_reconciliation_error(
        self,
        url: str,
        message: str,
        error_type: str,
    ) -> None:
        self._track_error(url, ValueError(message), error_type=error_type)

    def _load_verification_candidates(
        self,
        limit: int,
    ) -> list[ExistingGulandSnapshot]:
        if limit <= 0:
            return []
        with get_conn() as conn:
            rows = conn.execute(
                """
                SELECT r.id AS raw_id, l.id AS listing_id, l.url, l.source_id,
                       l.price_ty, l.first_seen_at,
                       COALESCE(l.source_status, 'unknown') AS source_status
                FROM listings l
                JOIN raw_listings r ON r.id=l.raw_id
                WHERE l.source='guland'
                  AND COALESCE(l.source_status, 'unknown') <> 'inactive'
                  AND COALESCE(l.probably_sold, 0)=0
                  AND COALESCE(l.review_hidden, 0)=0
                  AND COALESCE(l.possibly_duplicate, 0)=0
                  AND l.price_ty > 0
                  AND l.area_m2 > 0
                ORDER BY
                  CASE COALESCE(l.source_status,'unknown')
                    WHEN 'unknown' THEN 0 ELSE 1
                  END,
                  l.last_source_check_at NULLS FIRST,
                  l.id
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
        return [
            ExistingGulandSnapshot(
                raw_id=int(row["raw_id"]),
                listing_id=int(row["listing_id"]),
                url=row["url"],
                source_id=row["source_id"],
                price_ty=row["price_ty"],
                first_seen_at=row["first_seen_at"],
                source_status=row["source_status"],
            )
            for row in rows
        ]

    def _record_source_outcome(
        self,
        snapshot: ExistingGulandSnapshot,
        outcome: str,
        reason: str,
    ):
        with get_conn() as conn:
            return record_source_check(
                conn,
                snapshot.listing_id,
                outcome,
                reason,
            )

    def _refresh_verified_price(
        self,
        snapshot: ExistingGulandSnapshot,
        detail: dict,
        price_ty: float,
    ) -> int:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT raw_json FROM raw_listings WHERE id=? AND source='guland'",
                (snapshot.raw_id,),
            ).fetchone()
        if not row:
            raise LookupError(f"Guland raw listing not found: {snapshot.raw_id}")
        try:
            record = json.loads(row["raw_json"] or "{}")
        except (TypeError, ValueError):
            record = {}
        record["price_ty"] = price_ty
        for key in (
            "description",
            "address",
            "property_type_raw",
            "road_type_raw",
            "road_width_raw",
            "location_type_raw",
            "legal_raw",
            "contact_phone",
            "detail_imgs",
        ):
            if detail.get(key) not in (None, "", []):
                target_key = "imgs" if key == "detail_imgs" else key
                record[target_key] = detail[key]
        return self._refresh_changed_record(snapshot, record)

    def _verify_stale_listings(self, page, limit: int) -> dict:
        candidates = self._load_verification_candidates(limit)
        stats = {
            "scanned": len(candidates),
            "active": 0,
            "removed": 0,
            "unreachable": 0,
            "updated": 0,
            "invalid_prices": 0,
            "refreshed_raw_ids": [],
        }
        if not candidates:
            return stats

        details = self._fetch_details_batch(
            page,
            [snapshot.url for snapshot in candidates],
        )
        for snapshot in candidates:
            detail = details.get(snapshot.url, {})
            classification = classify_detail_result(detail)
            stats[classification.outcome] += 1
            self._record_source_outcome(
                snapshot,
                classification.outcome,
                classification.reason,
            )
            if classification.outcome != "active":
                continue

            detail_price_ty = self.parse_price_ty(
                detail.get("detail_price_raw", "")
            )
            detail_price = canonical_price_vnd(detail_price_ty)
            if detail_price is None:
                stats["invalid_prices"] += 1
                continue
            if detail_price == canonical_price_vnd(snapshot.price_ty):
                continue

            raw_id = self._refresh_verified_price(
                snapshot,
                detail,
                detail_price_ty,
            )
            stats["updated"] += 1
            stats["refreshed_raw_ids"].append(raw_id)
        return stats

    def after_targets(self, page, run_id: int) -> None:
        try:
            configured = int(os.getenv("GULAND_STATUS_VERIFY_LIMIT", "50"))
        except ValueError:
            configured = 50
        limit = max(0, min(200, configured))
        if limit == 0:
            return
        stats = self._verify_stale_listings(page, limit)
        self._ensure_reconciliation_stats()
        if isinstance(stats, dict):
            self._stats["updated"] += int(stats.get("updated", 0) or 0)
            self._stats["refreshed_raw_ids"].extend(
                stats.get("refreshed_raw_ids") or []
            )
        self.logger.info(
            "[guland] source verification=%s",
            json.dumps(stats, ensure_ascii=False),
        )

    def _run_crawl(self, page, base_url: str, incremental: bool) -> int:
        self._ensure_reconciliation_stats()
        new_before = int(self._stats.get("new", 0) or 0)
        self.logger.info(f"Phase 1 — scroll cards ({'incremental' if incremental else 'full'})")
        all_cards = self._scroll_all_cards(page, base_url, incremental=incremental)
        for card in all_cards:
            card.setdefault("source_list_url", base_url)
            card["price_ty"] = self.parse_price_ty(card.get("price_raw", ""))
        self._stats["fetched"] = self._stats.get("fetched", 0) + len(all_cards)

        snapshots = self._load_existing_snapshots(
            [card["url"] for card in all_cards]
        )
        plan = plan_guland_cards(all_cards, snapshots)
        discovered_existing_urls = [
            card["url"] for card in all_cards if card["url"] in snapshots
        ]
        if discovered_existing_urls:
            self._mark_seen_urls(discovered_existing_urls)
        self._stats["existing"] += len(discovered_existing_urls)
        self._stats["unchanged"] += len(plan.unchanged_cards)
        self._stats["invalid_price"] += len(plan.invalid_price_cards)
        self._stats["skipped"] += (
            len(plan.unchanged_cards) + len(plan.invalid_price_cards)
        )

        detail_cards = [*plan.new_cards, *plan.changed_cards]
        self.logger.info(
            f"Phase 1 done: {len(all_cards)} total | "
            f"{len(plan.new_cards)} mới | "
            f"{len(plan.changed_cards)} đổi giá | "
            f"{len(plan.unchanged_cards)} không đổi | "
            f"{len(plan.invalid_price_cards)} giá không hợp lệ"
        )

        if not detail_cards:
            return 0

        self.logger.info(
            f"Phase 2 — batch fetch {len(detail_cards)} detail pages "
            f"(batch={BATCH_SIZE})"
        )
        url_to_detail = self._fetch_details_batch(
            page,
            [card["url"] for card in detail_cards],
        )

        for card in plan.new_cards:
            detail = url_to_detail.get(card["url"], {})
            classification = classify_detail_result(detail)
            if classification.outcome != "active":
                self._track_reconciliation_error(
                    card["url"],
                    classification.reason,
                    f"new_detail_{classification.outcome}",
                )
                continue
            detail_price = self.parse_price_ty(detail.get("detail_price_raw", ""))
            if canonical_price_vnd(card.get("price_ty")) is None and detail_price:
                card["price_ty"] = detail_price
                card["price_raw"] = detail.get("detail_price_raw", "")
            record = self._build_record(card, detail)
            raw_id = self._insert_new_record(card, record)
            if raw_id:
                self._stats["inserted_raw_ids"].append(raw_id)
                self.logger.info(
                    f"  + {record['title'][:50]} | "
                    f"{record['price_ty']}ty {record['area_m2']}m²"
                )

        for card in plan.changed_cards:
            detail = url_to_detail.get(card["url"], {})
            classification = classify_detail_result(detail)
            if classification.outcome != "active":
                self._track_reconciliation_error(
                    card["url"],
                    classification.reason,
                    f"changed_detail_{classification.outcome}",
                )
                continue

            card_price = canonical_price_vnd(card.get("price_ty"))
            detail_price = canonical_price_vnd(
                self.parse_price_ty(detail.get("detail_price_raw", ""))
            )
            if detail_price is None or detail_price != card_price:
                self._track_reconciliation_error(
                    card["url"],
                    "card/detail price mismatch",
                    "price_confirmation_failed",
                )
                continue

            snapshot = snapshots[card["url"]]
            record = self._build_record(card, detail)
            raw_id = self._refresh_changed_record(snapshot, record)
            self._stats["updated"] += 1
            self._stats["refreshed_raw_ids"].append(raw_id)

        return int(self._stats.get("new", 0) or 0) - new_before

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
