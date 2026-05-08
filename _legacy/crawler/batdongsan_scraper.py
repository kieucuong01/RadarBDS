"""
BatDongSan.com.vn crawler — cào listing + detail page, lấy description đầy đủ.

Yêu cầu: pip install cloudscraper beautifulsoup4

Usage:
    python -m crawler.batdongsan_scraper
    python -m crawler.batdongsan_scraper --workers 3 --max-pages 20

Sau khi chạy xong:
    python radar.py delete-batdongsan -y
    python radar.py import-batdongsan --file data/bds_fresh.json
    python radar.py reprocess
    python radar.py export-raw
"""

import argparse
import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

try:
    import cloudscraper
    from bs4 import BeautifulSoup
except ImportError:
    raise SystemExit("Thiếu thư viện: pip install cloudscraper beautifulsoup4")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ── Cấu hình ─────────────────────────────────────────────────────────────────
BASE_URL  = "https://batdongsan.com.vn"
DEFAULT_OUT = str(Path(__file__).parent.parent / "data" / "bds_fresh.json")

# Danh sách trang tìm kiếm cho dự án (Tân An + Phú An, Thủ Dầu Một, Bình Dương)
SEARCH_SLUGS = [
    # Phường Tân An, TP Thủ Dầu Một, Bình Dương (mua bán)
    "ban-dat-phuong-tan-an_1",           # đất Tân An (chính)
    "ban-dat-phuong-phu-an_1",           # đất Phú An (thuộc Tân An cũ)
    "ban-dat-duong-dx-122-phuong-tan-an_1-163",  # đường DX122
    "ban-nha-phuong-tan-an_1",           # nhà đất Tân An
    # Mở rộng sau: Thuận An, Dĩ An...
]

MAX_PAGES  = 20     # trang tối đa mỗi slug
DELAY_S    = 0.5    # delay giữa requests
MAX_EMPTY  = 2      # dừng sau N trang liên tiếp không có listing mới


# ── Scraper factory ──────────────────────────────────────────────────────────
def _make_scraper():
    return cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "mobile": False}
    )


# ── Parse helpers ─────────────────────────────────────────────────────────────

def _text(el) -> str:
    return el.get_text(" ", strip=True) if el else ""


def parse_price_ty(raw: str) -> Optional[float]:
    if not raw:
        return None
    s = raw.lower().replace(",", ".")
    try:
        # Remove non-numeric except dot
        num_str = re.sub(r"[^\d.]", "", s.split("t")[0].strip())
        num = float(num_str) if num_str else None
        if num is None:
            return None
        if any(x in s for x in ["tỷ", "ty", "tỉ"]):
            return round(num, 3)
        if any(x in s for x in ["triệu", "tr "]):
            return round(num / 1000, 3)
    except Exception:
        pass
    return None


def parse_area_m2(raw: str) -> Optional[float]:
    if not raw:
        return None
    try:
        num = re.sub(r"[^\d.]", "", raw.replace(",", "."))
        return float(num) if num else None
    except Exception:
        return None


def parse_post_date(raw: str) -> str:
    now = datetime.now()
    if not raw:
        return now.strftime("%Y-%m-%d")
    s = raw.lower().strip()
    try:
        if any(kw in s for kw in ["hôm nay", "giờ", "phút", "vừa", "giây"]):
            return now.strftime("%Y-%m-%d")
        if "hôm qua" in s:
            return (now - timedelta(days=1)).strftime("%Y-%m-%d")
        m = re.search(r"(\d+)\s*ngày", s)
        if m:
            return (now - timedelta(days=int(m.group(1)))).strftime("%Y-%m-%d")
        m = re.search(r"(\d+)\s*tuần", s)
        if m:
            return (now - timedelta(weeks=int(m.group(1)))).strftime("%Y-%m-%d")
        m = re.search(r"(\d+)\s*tháng", s)
        if m:
            return (now - timedelta(days=int(m.group(1)) * 30)).strftime("%Y-%m-%d")
        m = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})", s)
        if m:
            d, mo, y = m.groups()
            if len(y) == 2: y = "20" + y
            return f"{y}-{int(mo):02d}-{int(d):02d}"
    except Exception:
        pass
    return now.strftime("%Y-%m-%d")


# ── Listing page parsing ──────────────────────────────────────────────────────

def parse_listing_page(html: str, slug: str) -> list[dict]:
    """
    Trích xuất card từ 1 trang kết quả BDS.
    Selector theo bds_scraper.py (file tham khảo).
    """
    soup = BeautifulSoup(html, "html.parser")
    results = []

    cards = soup.select("div.js__card")
    for card in cards:
        # Bỏ qua quảng cáo (theo bds_scraper.py cũ)
        if "re__card-full-ads" in card.get("class", []):
            continue
        try:
            # URL — theo bds_scraper.py: a.js__product-link
            link = (card.select_one("a.js__product-link")
                    or card.select_one("a.js__product-link-for-product-id"))
            if not link:
                continue
            href = link.get("href", "")
            if not href:
                continue
            url = href if href.startswith("http") else BASE_URL + href

            # Title — theo bds_scraper.py: span.pr-title.js__card-title
            title_el = (card.select_one("span.pr-title.js__card-title")
                        or card.select_one("span.pr-title")
                        or card.select_one("h3.re__card-title"))
            title = _text(title_el)

            # Giá — span.re__card-config-price
            price_el  = card.select_one("span.re__card-config-price")
            price_raw = _text(price_el)

            # Diện tích — span.re__card-config-area
            area_el  = card.select_one("span.re__card-config-area")
            area_raw = _text(area_el)

            # Giá/m²
            pm2_el  = card.select_one("span.re__card-config-price_per_m2")
            pm2_raw = _text(pm2_el)

            # Ngày đăng — theo bds_scraper.py: published-info | published-at | tooltip-time
            date_el = card.find(
                "span", class_=re.compile(r"published-info|published-at|tooltip-time")
            )
            date_raw = (date_el.get("aria-label") or _text(date_el)) if date_el else ""

            # Địa chỉ
            addr_el = (card.select_one("div.re__card-location span:last-child")
                       or card.select_one("span.re__card-location__value"))
            address = _text(addr_el)

            # Property type từ slug
            prop_raw = "nha_dat" if slug.startswith("ban-nha") else "dat_nen"

            results.append({
                "url":       url,
                "title":     title,
                "price_raw": price_raw,
                "area_raw":  area_raw,
                "pm2_raw":   pm2_raw,
                "date_raw":  date_raw,
                "address":   address,
                "prop_raw":  prop_raw,
            })
        except Exception as e:
            logger.debug(f"Card parse error: {e}")

    return results


def has_next_page(html: str) -> bool:
    soup = BeautifulSoup(html, "html.parser")
    # Nút "Trang sau" / next page
    next_btn = soup.select_one("a[title='Trang sau']") or soup.select_one(".re__pagination-next")
    if next_btn and next_btn.get("href"):
        return True
    # Fallback: kiểm tra có card không
    return bool(soup.select("div.js__card"))


# ── Detail page parsing ───────────────────────────────────────────────────────

def parse_detail_page(html: str, url: str) -> dict:
    """Trích xuất description + structured info từ trang chi tiết BDS."""
    soup = BeautifulSoup(html, "html.parser")
    result = {"url": url}

    # Title
    title_el = (soup.select_one("h1.re__pr-title")
                or soup.select_one("h1[itemprop='name']")
                or soup.select_one("h1"))
    result["title_detail"] = _text(title_el)

    # Description — nhiều selector khả năng
    desc = ""
    for sel in [
        "div.re__section-body.js__section-body",
        "div[id='pr__description'] .re__section-body",
        "div.re__pr-description",
        "div.js__pr-description",
        "div[class*='description'] p",
        "div.re__section-body",
    ]:
        el = soup.select_one(sel)
        if el:
            candidate = el.get_text("\n", strip=True)
            if len(candidate) > len(desc):
                desc = candidate
    result["description"] = desc[:4000]

    # Thông tin BĐS từ bảng summary (diện tích, mặt tiền, đường, pháp lý...)
    info = {}
    for row in soup.select("div.re__pr-short-info-item, div[class*='short-info'] div"):
        spans = row.select("span")
        if len(spans) >= 2:
            key = _text(spans[0]).lower()
            val = _text(spans[1])
            info[key] = val
    result["info"] = info

    # Lấy các trường quan trọng từ info
    def _get(*keys):
        for k in keys:
            for ik, iv in info.items():
                if k in ik:
                    return iv
        return ""

    result["road_type_raw"]     = _get("đường", "hẻm", "loại đường")
    result["frontage_raw"]      = _get("mặt tiền", "ngang")
    result["depth_raw"]         = _get("chiều sâu", "sâu")
    result["legal_raw"]         = _get("pháp lý", "sổ")
    result["road_width_raw"]    = _get("đường vào", "đường/hẻm", "rộng")
    result["property_type_raw"] = _get("loại bất động sản", "loại nhà", "loại đất", "loại bds")

    # Địa chỉ đầy đủ
    addr_el = (soup.select_one("span.re__pr-short-description__pr-address")
               or soup.select_one("div.re__pr-short-description span[itemprop='address']")
               or soup.select_one("span[itemprop='address']"))
    result["address"] = _text(addr_el)

    # Contact phone (thường ẩn, lấy từ data attribute)
    phone = ""
    for el in soup.select("[data-phone], [data-mobile]"):
        phone = el.get("data-phone") or el.get("data-mobile") or ""
        if phone:
            break
    result["contact_phone"] = phone

    # Ảnh
    imgs = []
    for img in soup.select("img[src*='staticpage.vn'], img[src*='batdongsan']"):
        src = img.get("src", "")
        if src and src.startswith("http"):
            imgs.append(src)
    result["imgs"] = list(dict.fromkeys(imgs))[:10]  # dedup, max 10

    return result


# ── Crawl listing pages ───────────────────────────────────────────────────────

def crawl_slug(slug: str, max_pages: int, scraper) -> list[dict]:
    """Crawl tất cả trang listing cho 1 slug."""
    all_cards = []
    seen_urls = set()
    empty_streak = 0

    for page in range(1, max_pages + 1):
        url = f"{BASE_URL}/{slug}" if page == 1 else f"{BASE_URL}/{slug}/p{page}"
        try:
            resp = scraper.get(url, timeout=20)
            if resp.status_code == 404:
                break
            html = resp.text
        except Exception as e:
            logger.warning(f"[{slug}] page={page} fetch error: {e}")
            break

        cards = parse_listing_page(html, slug)
        new_cards = [c for c in cards if c["url"] not in seen_urls]
        for c in new_cards:
            seen_urls.add(c["url"])
        all_cards.extend(new_cards)

        logger.info(f"[{slug}] page {page}: {len(new_cards)} new (total={len(all_cards)})")

        if not new_cards:
            empty_streak += 1
            if empty_streak >= MAX_EMPTY:
                break
        else:
            empty_streak = 0

        time.sleep(DELAY_S)

    return all_cards


def crawl_all_listings(slugs: list[str], max_pages: int) -> list[dict]:
    scraper = _make_scraper()
    all_cards = []
    seen_urls = set()

    for slug in slugs:
        cards = crawl_slug(slug, max_pages, scraper)
        new = [c for c in cards if c["url"] not in seen_urls]
        for c in new:
            seen_urls.add(c["url"])
        all_cards.extend(new)
        logger.info(f"Slug {slug}: {len(new)} listings")
        time.sleep(DELAY_S * 2)

    return all_cards


# ── Crawl detail pages ────────────────────────────────────────────────────────

def crawl_detail(card: dict, scraper) -> dict:
    url = card["url"]
    try:
        resp = scraper.get(url, timeout=20)
        detail = parse_detail_page(resp.text, url)
    except Exception as e:
        logger.warning(f"Detail error {url}: {e}")
        detail = {"url": url}

    merged = {**card}
    merged["title"]          = card.get("title") or detail.get("title_detail", "")
    merged["description"]    = detail.get("description", "")
    merged["road_type_raw"]  = detail.get("road_type_raw", "")
    merged["frontage_raw"]   = detail.get("frontage_raw", "")
    merged["depth_raw"]      = detail.get("depth_raw", "")
    merged["legal_raw"]      = detail.get("legal_raw", "")
    merged["road_width_raw"] = detail.get("road_width_raw", "")
    merged["contact_phone"]  = detail.get("contact_phone", "")
    merged["imgs"]           = detail.get("imgs", [])
    if not merged.get("address"):
        merged["address"] = detail.get("address", "")
    if detail.get("property_type_raw"):
        merged["prop_raw"] = detail["property_type_raw"]

    return merged


def crawl_details_parallel(cards: list[dict], workers: int = 3) -> list[dict]:
    results = [None] * len(cards)
    scrapers = [_make_scraper() for _ in range(workers)]

    def _worker(idx_card):
        idx, card = idx_card
        scraper = scrapers[idx % workers]
        time.sleep(DELAY_S * (idx % workers + 1))
        return idx, crawl_detail(card, scraper)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(_worker, (i, c)): i for i, c in enumerate(cards)}
        done = 0
        for fut in as_completed(futures):
            try:
                idx, merged = fut.result()
                results[idx] = merged
            except Exception as e:
                idx = futures[fut]
                results[idx] = cards[idx]
                logger.warning(f"Worker error idx={idx}: {e}")
            done += 1
            if done % 10 == 0 or done == len(cards):
                logger.info(f"Detail pages: {done}/{len(cards)} done")

    return [r for r in results if r is not None]


# ── Build import record ───────────────────────────────────────────────────────

def _map_road_type(raw: str) -> str:
    s = raw.lower()
    if "nhựa" in s:      return "nhua"
    if "bê tông" in s:   return "be_tong"
    if "đất" in s:       return "dat"
    if "hẻm" in s:       return "hem"
    return "unknown"


def _map_has_so(raw: str) -> int:
    s = raw.lower()
    if any(x in s for x in ["sổ hồng", "sổ đỏ", "có sổ", "full sổ"]): return 1
    if any(x in s for x in ["chưa có", "không có", "giấy tay"]):        return 0
    return 0


def _parse_frontage(raw: str) -> Optional[float]:
    if not raw: return None
    try:
        return float(re.sub(r"[^\d.]", "", raw))
    except: return None


def build_import_record(merged: dict) -> dict:
    price_ty = parse_price_ty(merged.get("price_raw", ""))
    area_m2  = parse_area_m2(merged.get("area_raw", ""))
    pm2_raw  = merged.get("pm2_raw", "")
    pm2      = parse_price_ty(pm2_raw)  # pm2 cũng dạng "X triệu/m²"
    if not pm2:
        try:
            num = re.sub(r"[^\d.]", "", pm2_raw)
            pm2 = float(num) if num else None
        except: pass
    if not pm2 and price_ty and area_m2 and area_m2 > 0:
        pm2 = round(price_ty * 1e9 / area_m2 / 1e6, 2)

    url = merged.get("url", "")

    # Ward detection từ URL + address
    addr_lower = (merged.get("address", "") + url).lower()
    ward = "Phú An" if "phu-an" in addr_lower or "phú an" in addr_lower else "Tân An"

    # Lấy post ID từ URL (prXXXXX)
    m = re.search(r"pr(\d+)", url)
    post_id = m.group(1) if m else ""

    return {
        "url":               url,
        "post_id":           post_id,
        "title":             merged.get("title", ""),
        "description":       merged.get("description", ""),
        "price_ty":          price_ty,
        "area_m2":           area_m2,
        "price_per_m2":      pm2,
        "area_name":         "Tân An",
        "ward":              ward,
        "address":           merged.get("address", ""),
        "property_type_raw": merged.get("prop_raw", ""),
        "road_type_raw":     merged.get("road_type_raw", ""),
        "frontage_raw":      merged.get("frontage_raw", ""),
        "depth_raw":         merged.get("depth_raw", ""),
        "legal_raw":         merged.get("legal_raw", ""),
        "contact_phone":     merged.get("contact_phone", ""),
        "imgs":              merged.get("imgs", []),
        "post_date":         parse_post_date(merged.get("date_raw", "")),
        "tx_type":           "ban",
        "province":          "Bình Dương",
        "district":          "Thủ Dầu Một",
        "_source":           "batdongsan",
    }


# ── Main ─────────────────────────────────────────────────────────────────────

def run(slugs: list[str], out_path: str, workers: int = 3, max_pages: int = MAX_PAGES):
    logger.info("=== BatDongSan crawler start ===")
    logger.info(f"Slugs  : {slugs}")
    logger.info(f"Output : {out_path}")
    logger.info(f"Workers: {workers} | Max pages/slug: {max_pages}")

    logger.info("Bước 1: Crawl listing pages...")
    cards = crawl_all_listings(slugs, max_pages)
    logger.info(f"  → {len(cards)} listings found")

    if not cards:
        logger.error("Không có listing — kiểm tra URL hoặc kết nối mạng.")
        return

    logger.info(f"Bước 2: Crawl {len(cards)} detail pages (workers={workers})...")
    merged = crawl_details_parallel(cards, workers=workers)

    records = [build_import_record(c) for c in merged if c.get("url")]

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    has_desc = sum(1 for r in records if r.get("description"))
    logger.info("=== Crawl done ===")
    logger.info(f"  Total   : {len(records)}")
    logger.info(f"  Has desc: {has_desc}/{len(records)}")
    logger.info(f"  Saved   : {out_path}")
    logger.info("")
    logger.info("Bước tiếp theo:")
    logger.info("  python radar.py delete-batdongsan -y")
    logger.info(f"  python radar.py import-batdongsan --file {out_path}")
    logger.info("  python radar.py reprocess")
    logger.info("  python radar.py export-raw")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="BatDongSan scraper cho Radar BDS")
    parser.add_argument("--out",       default=DEFAULT_OUT, help="Output JSON path")
    parser.add_argument("--workers",   type=int, default=3, help="Số threads crawl detail")
    parser.add_argument("--max-pages", type=int, default=MAX_PAGES, help="Max trang/slug")
    parser.add_argument("--slugs",     nargs="+", default=SEARCH_SLUGS,
                        help="Danh sách slug BDS (không cần domain)")
    args = parser.parse_args()
    run(slugs=args.slugs, out_path=args.out, workers=args.workers, max_pages=args.max_pages)
