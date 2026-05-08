"""
Guland crawler — cào listing + detail page, lấy description đầy đủ.

Yêu cầu: pip install cloudscraper beautifulsoup4

Usage:
    python -m crawler.guland_scraper
    python -m crawler.guland_scraper --out data/guland_fresh.json --workers 5
    python -m crawler.guland_scraper --url "https://guland.vn/mua-ban-..." --workers 8

Sau khi chạy xong:
    python radar.py delete-guland          # xóa Guland cũ khỏi DB
    python radar.py import-guland --file data/guland_fresh.json
    python radar.py reprocess
    python radar.py export-raw             # backup
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

DEFAULT_URL = (
    "https://guland.vn/mua-ban-bat-dong-san-phuong-tan-an-"
    "thanh-pho-thu-dau-mot-binh-duong"
)
DEFAULT_OUT = str(Path(__file__).parent.parent / "data" / "guland_fresh.json")
MAX_PAGES   = 50      # giới hạn an toàn
DELAY_S     = 0.3     # delay giữa các request (giây)

# ── Scraper singleton (thread-safe) ──────────────────────────────────────────
def _make_scraper():
    return cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "mobile": False}
    )


# ── Parse helpers ─────────────────────────────────────────────────────────────

def _text(el) -> str:
    return el.get_text(" ", strip=True) if el else ""


def parse_price_ty(raw: str) -> Optional[float]:
    """'6.8 tỷ' → 6.8  |  '850 triệu' → 0.85  |  None nếu không parse được."""
    if not raw:
        return None
    s = raw.lower().replace(",", ".")
    try:
        num_str = re.sub(r"[^\d.]", "", s.split("t")[0].strip())
        num = float(num_str) if num_str else None
        if num is None:
            return None
        if "tỷ" in s or "ty" in s or "tỉ" in s:
            return round(num, 3)
        if "triệu" in s or "tr" in s:
            return round(num / 1000, 3)
    except Exception:
        pass
    return None


def parse_area_m2(raw: str) -> Optional[float]:
    """'234.2m²' → 234.2"""
    if not raw:
        return None
    try:
        num = re.sub(r"[^\d.]", "", raw.replace(",", "."))
        return float(num) if num else None
    except Exception:
        return None


def parse_pm2(raw: str) -> Optional[float]:
    """'29.04 tr /m²' → 29.04  |  '29.04 triệu/m²' → 29.04"""
    if not raw:
        return None
    try:
        num = re.sub(r"[^\d.]", "", raw.replace(",", ".").split("t")[0].strip())
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
            if len(y) == 2:
                y = "20" + y
            return f"{y}-{int(mo):02d}-{int(d):02d}"
    except Exception:
        pass
    return now.strftime("%Y-%m-%d")


# ── Listing page parsing ──────────────────────────────────────────────────────

def parse_listing_cards(html: str) -> list[dict]:
    """Trích xuất danh sách card cơ bản từ trang listing."""
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select(".c-sdb-card")
    results = []
    for card in cards:
        try:
            a_post = card.select_one('a[href*="/post/"]')
            if not a_post:
                continue
            url = a_post["href"]
            if not url.startswith("http"):
                url = "https://guland.vn" + url

            post_id = re.search(r"(\d+)$", url.rstrip("/"))
            post_id = post_id.group(1) if post_id else ""

            title_el = card.select_one(".c-sdb-card__tle")
            title = _text(title_el)

            price_el  = card.select_one(".sdb-inf-data.data-color-1.data-size-xl b")
            price_raw = _text(price_el)

            inf_bs    = card.select(".sdb-inf-data.data-size-lg b")
            area_raw  = _text(inf_bs[0]) if len(inf_bs) > 0 else ""
            pm2_raw   = _text(inf_bs[1]) if len(inf_bs) > 1 else ""

            date_el   = card.select_one(".profile-info__stl, .sdb-time")
            date_raw  = _text(date_el)

            imgs = [
                i["src"] for i in card.select("img[src]")
                if "cdn.guland" in i.get("src", "")
            ]

            results.append({
                "url":       url,
                "post_id":   post_id,
                "title":     title,
                "price_raw": price_raw,
                "area_raw":  area_raw,
                "pm2_raw":   pm2_raw,
                "date_raw":  date_raw,
                "imgs":      imgs,
            })
        except Exception as e:
            logger.debug(f"Card parse error: {e}")
    return results


def has_more_pages(html: str) -> bool:
    """True nếu còn nút 'Xem thêm' hiển thị."""
    soup = BeautifulSoup(html, "html.parser")
    btn = soup.select_one("#btn-load-more")
    if not btn:
        return False
    return "d-none" not in btn.get("class", [])


# ── Detail page parsing ───────────────────────────────────────────────────────

def parse_detail_page(html: str, url: str) -> dict:
    """Trích xuất description + structured info từ trang chi tiết."""
    soup = BeautifulSoup(html, "html.parser")
    result = {"url": url}

    # Title (backup nếu listing card thiếu)
    title_el = soup.select_one(".dtl-tle")
    result["title_detail"] = _text(title_el)

    # Giá / diện tích / pm2 từ detail (backup)
    price_els = soup.select(".dtl-prc__sgl")
    result["price_raw_detail"] = _text(price_els[0]) if price_els else ""
    result["area_raw_detail"]  = _text(price_els[1]) if len(price_els) > 1 else ""
    result["pm2_raw_detail"]   = _text(price_els[2]) if len(price_els) > 2 else ""

    # Địa chỉ
    addr_el = soup.select_one(".dtl-stl__row")
    result["address"] = _text(addr_el)

    # Mã tin
    stl_text = _text(soup.select_one(".dtl-stl"))
    m = re.search(r"Mã tin[:\s]+(\d+)", stl_text)
    result["post_id_detail"] = m.group(1) if m else ""

    # Structured info rows (Loại BĐS, Vị trí, Đường, Pháp lý...)
    row_el = soup.select_one(".dtl-inf__row")
    row_text = _text(row_el) if row_el else ""
    result["info_row"] = row_text

    # Parse từng field từ row
    def _extract_field(row_text, *keys):
        for key in keys:
            m = re.search(rf"{re.escape(key)}\s*[:\-]\s*([^\n]+?)(?=\s+[A-ZÁÀẢÃẠ]|$)", row_text)
            if m:
                return m.group(1).strip()
        return ""

    result["property_type_raw"] = _extract_field(row_text, "Loại BĐS", "Loại bds")
    result["road_type_raw"]     = _extract_field(row_text, "Loại đường", "Đường")
    result["road_width_raw"]    = _extract_field(row_text, "Đường/hẻm vào rộng", "Chiều rộng")
    result["location_type_raw"] = _extract_field(row_text, "Vị trí")
    result["legal_raw"]         = _extract_field(row_text, "Pháp lý")

    # Description tự do
    dsr_el = soup.select_one(".dtl-inf__dsr")
    result["description"] = _text(dsr_el)

    # SĐT liên hệ
    phone_el = soup.select_one(".profile-info__stl, .dtl-prf__phone, [href^='tel:']")
    phone_text = _text(phone_el)
    phones = re.findall(r"0\d[\d*]{8,10}", phone_text)
    result["contact_phone"] = phones[0] if phones else ""

    return result


# ── Main crawl ────────────────────────────────────────────────────────────────

def crawl_listings(base_url: str) -> list[dict]:
    """
    Crawl tất cả trang listing → danh sách card cơ bản.
    Dừng khi hết 'Xem thêm' hoặc không có card.
    """
    scraper = _make_scraper()
    all_cards = []
    seen_urls = set()

    for page in range(1, MAX_PAGES + 1):
        url = base_url if page == 1 else f"{base_url}?page={page}"
        try:
            logger.info(f"Fetching listing page {page}: {url}")
            resp = scraper.get(url, timeout=20)
            logger.info(f"  HTTP {resp.status_code} | size={len(resp.text)} bytes")
            if resp.status_code != 200:
                logger.error(f"  Bad status {resp.status_code}, dừng")
                break
            html = resp.text
        except Exception as e:
            logger.error(f"Listing page={page} fetch error: {e}")
            break

        cards = parse_listing_cards(html)
        new_cards = [c for c in cards if c["url"] not in seen_urls]
        for c in new_cards:
            seen_urls.add(c["url"])
        all_cards.extend(new_cards)

        more = has_more_pages(html)
        logger.info(f"  → {len(new_cards)} new cards (total={len(all_cards)}) | more_pages={more}")

        # Debug: in 1 card đầu để verify selector
        if page == 1 and new_cards:
            c0 = new_cards[0]
            logger.info(f"  Sample card[0]: url={c0['url'][:60]} title={c0['title'][:40]}")
        elif page == 1 and not new_cards:
            # In 500 chars HTML đầu để xem structure
            logger.warning(f"  Không parse được card! HTML preview:\n{html[:500]}")

        if not new_cards or not more:
            break
        time.sleep(DELAY_S)

    return all_cards


def crawl_detail(card: dict, scraper) -> dict:
    """Crawl detail page của 1 listing, merge vào card."""
    url = card["url"]
    try:
        resp = scraper.get(url, timeout=20)
        detail = parse_detail_page(resp.text, url)
    except Exception as e:
        logger.warning(f"Detail fetch error {url}: {e}")
        detail = {"url": url}

    # Merge: card fields ưu tiên trừ khi rỗng
    merged = {**card}
    merged["title"]          = card.get("title") or detail.get("title_detail", "")
    merged["description"]    = detail.get("description", "")
    merged["address"]        = detail.get("address", "")
    merged["post_id"]        = card.get("post_id") or detail.get("post_id_detail", "")
    merged["property_type_raw"] = detail.get("property_type_raw", "")
    merged["road_type_raw"]  = detail.get("road_type_raw", "")
    merged["road_width_raw"] = detail.get("road_width_raw", "")
    merged["location_type_raw"] = detail.get("location_type_raw", "")
    merged["legal_raw"]      = detail.get("legal_raw", "")
    merged["contact_phone"]  = detail.get("contact_phone", "")

    # Backup giá/diện từ detail nếu card thiếu
    if not merged.get("price_raw"):
        merged["price_raw"] = detail.get("price_raw_detail", "")
    if not merged.get("area_raw"):
        merged["area_raw"] = detail.get("area_raw_detail", "")
    if not merged.get("pm2_raw"):
        merged["pm2_raw"] = detail.get("pm2_raw_detail", "")

    return merged


def crawl_details_parallel(cards: list[dict], workers: int = 5) -> list[dict]:
    """Crawl detail pages song song (mỗi thread dùng scraper riêng)."""
    results = [None] * len(cards)
    scrapers = [_make_scraper() for _ in range(workers)]

    def _worker(idx_card):
        idx, card = idx_card
        scraper = scrapers[idx % workers]
        time.sleep(DELAY_S * (idx % workers))  # stagger start
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
            if done % 20 == 0 or done == len(cards):
                logger.info(f"Detail pages: {done}/{len(cards)} done")

    return [r for r in results if r is not None]


def build_import_record(merged: dict) -> dict:
    """Chuyển merged card → format chuẩn cho radar.py import-guland."""
    price_ty  = parse_price_ty(merged.get("price_raw", ""))
    area_m2   = parse_area_m2(merged.get("area_raw", ""))
    pm2       = parse_pm2(merged.get("pm2_raw", ""))
    if not pm2 and price_ty and area_m2 and area_m2 > 0:
        pm2 = round(price_ty * 1e9 / area_m2 / 1e6, 2)

    url = merged.get("url", "")
    slug = url.replace("https://guland.vn/", "")

    # Ward detection
    addr = (merged.get("address", "") + url).lower()
    ward = "Phú An" if "phu-an" in addr or "phú an" in addr else "Tân An"

    return {
        # Dùng format đầy đủ — cmd_import_guland_v2 sẽ đọc
        "url":               url,
        "post_id":           merged.get("post_id", ""),
        "title":             merged.get("title", ""),
        "description":       merged.get("description", ""),
        "price_ty":          price_ty,
        "area_m2":           area_m2,
        "price_per_m2":      pm2,
        "area_name":         "Tân An",
        "ward":              ward,
        "address":           merged.get("address", ""),
        "property_type_raw": merged.get("property_type_raw", ""),
        "road_type_raw":     merged.get("road_type_raw", ""),
        "road_width_raw":    merged.get("road_width_raw", ""),
        "location_type_raw": merged.get("location_type_raw", ""),
        "legal_raw":         merged.get("legal_raw", ""),
        "contact_phone":     merged.get("contact_phone", ""),
        "imgs":              merged.get("imgs", []),
        "post_date":         parse_post_date(merged.get("date_raw", "")),
        "tx_type":           "ban",
        "province":          "Bình Dương",
        "district":          "Thủ Dầu Một",
    }


def run(base_url: str, out_path: str, workers: int = 5):
    logger.info(f"=== Guland crawler start ===")
    logger.info(f"URL   : {base_url}")
    logger.info(f"Output: {out_path}")
    logger.info(f"Workers: {workers}")

    # Bước 1: Crawl listing pages
    logger.info("Bước 1: Crawl listing pages...")
    cards = crawl_listings(base_url)
    logger.info(f"  → {len(cards)} listings found")

    if not cards:
        logger.error("Không có listing nào — kiểm tra URL hoặc kết nối mạng.")
        return

    # Bước 2: Crawl detail pages song song
    logger.info(f"Bước 2: Crawl {len(cards)} detail pages (workers={workers})...")
    merged_cards = crawl_details_parallel(cards, workers=workers)

    # Bước 3: Build import records
    records = [build_import_record(c) for c in merged_cards]
    records = [r for r in records if r.get("url")]  # bỏ record lỗi

    # Lưu file
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    has_desc = sum(1 for r in records if r.get("description"))
    logger.info(f"=== Crawl done ===")
    logger.info(f"  Total  : {len(records)} records")
    logger.info(f"  Has desc: {has_desc}/{len(records)}")
    logger.info(f"  Saved  : {out_path}")
    logger.info(f"")
    logger.info(f"Bước tiếp theo:")
    logger.info(f"  python radar.py delete-guland")
    logger.info(f"  python radar.py import-guland --file {out_path}")
    logger.info(f"  python radar.py reprocess")
    logger.info(f"  python radar.py export-raw")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Guland scraper cho Radar BDS")
    parser.add_argument("--url",     default=DEFAULT_URL,  help="Guland listing URL")
    parser.add_argument("--out",     default=DEFAULT_OUT,  help="Output JSON path")
    parser.add_argument("--workers", type=int, default=5,  help="Số threads crawl detail (default: 5)")
    args = parser.parse_args()
    run(base_url=args.url, out_path=args.out, workers=args.workers)
