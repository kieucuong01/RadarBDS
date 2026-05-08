"""
Crawler cho BatDongSan.com.vn
Sử dụng API nội bộ của trang (reverse-engineered từ network requests)
"""
import logging
import re
from typing import List, Dict, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from crawler.base import BaseCrawler
from config.settings import WATCH_AREAS

logger = logging.getLogger(__name__)

# BatDongSan API endpoint (reverse-engineered)
BDS_API_BASE    = "https://batdongsan.com.vn"
BDS_SEARCH_API  = "https://batdongsan.com.vn/nha-dat-ban"
BDS_SEARCH_RENT = "https://batdongsan.com.vn/nha-dat-thue"

# Mapping tên khu vực → slug URL trên BDS
AREA_URL_MAP = {
    "Tân An":       "ban-nha-dat-tan-an-long-an",
    "Mỹ Phước":     "ban-nha-dat-my-phuoc-binh-duong",
    "Phước Long":   "ban-nha-dat-phuoc-long-binh-phuoc",
    "Thủ Dầu Một":  "ban-nha-dat-thu-dau-mot-binh-duong",
}
AREA_RENT_MAP = {
    "Tân An":       "thue-nha-dat-tan-an-long-an",
    "Mỹ Phước":     "thue-nha-dat-my-phuoc-binh-duong",
    "Phước Long":   "thue-nha-dat-phuoc-long-binh-phuoc",
    "Thủ Dầu Một":  "thue-nha-dat-thu-dau-mot-binh-duong",
}

MAX_PAGES = 20  # Số trang tối đa mỗi lần crawl


class BatDongSanCrawler(BaseCrawler):
    source_name = "batdongsan"

    def _get_page_listing_urls(self, slug: str, page: int) -> List[str]:
        """Lấy danh sách URL listing từ 1 trang kết quả tìm kiếm."""
        url = f"{BDS_API_BASE}/{slug}/p{page}" if page > 1 else f"{BDS_API_BASE}/{slug}"
        html = self.fetch(url)
        if not html:
            return []
        soup = BeautifulSoup(html, "lxml")
        urls = []
        for tag in soup.select("a.js__product-link-for-product-id"):
            href = tag.get("href", "")
            if href:
                full_url = urljoin(BDS_API_BASE, href)
                if full_url not in urls:
                    urls.append(full_url)
        # Fallback selector
        if not urls:
            for tag in soup.select(".re__card-info a[href]"):
                href = tag.get("href", "")
                if "/pr" in href:
                    full_url = urljoin(BDS_API_BASE, href)
                    if full_url not in urls:
                        urls.append(full_url)
        return urls

    def get_listing_urls(self, area_config: dict) -> List[str]:
        area_name = area_config["name"]
        all_urls  = []
        for slug_map in [AREA_URL_MAP, AREA_RENT_MAP]:
            slug = slug_map.get(area_name)
            if not slug:
                continue
            for page in range(1, MAX_PAGES + 1):
                page_urls = self._get_page_listing_urls(slug, page)
                if not page_urls:
                    break
                new = [u for u in page_urls if u not in all_urls]
                all_urls.extend(new)
                self.logger.info(f"  {slug} page {page}: +{len(new)} URLs (total {len(all_urls)})")
                self.polite_sleep()
        return all_urls

    def parse_listing(self, url: str) -> Optional[Dict]:
        html = self.fetch(url)
        if not html:
            return None
        try:
            soup = BeautifulSoup(html, "lxml")

            # Title
            title_tag = soup.select_one("h1.re__pr-title") or soup.select_one("h1")
            title = title_tag.get_text(strip=True) if title_tag else ""

            # Description
            desc_tag = soup.select_one(".re__section-body.re__detail-content")
            description = desc_tag.get_text(" ", strip=True) if desc_tag else ""

            # Price
            price_total = None
            price_per_m2 = None
            price_tag = soup.select_one(".re__pr-short-info-item .title:contains('Mức giá') + .value") or \
                        soup.select_one("span.re__pr-short-info-item__value")
            # Try structured data
            for item in soup.select(".re__pr-short-info-item"):
                label = item.select_one(".title")
                value = item.select_one(".value")
                if not label or not value:
                    continue
                lbl = label.get_text(strip=True).lower()
                val = value.get_text(strip=True)
                if "giá" in lbl:
                    price_total = _parse_price_vnd(val)
                if "m2" in lbl or "/m²" in lbl:
                    price_per_m2 = _parse_price_per_m2(val)

            # Area m2
            area_m2 = None
            for item in soup.select(".re__pr-short-info-item"):
                label = item.select_one(".title")
                value = item.select_one(".value")
                if not label or not value:
                    continue
                if "diện tích" in label.get_text(strip=True).lower():
                    area_m2 = _parse_area(value.get_text(strip=True))

            # Address
            addr_tag = soup.select_one(".re__pr-short-description span") or \
                       soup.select_one("span.re__pr-short-info-item__value")
            address = addr_tag.get_text(strip=True) if addr_tag else ""

            # Contact
            phone = _extract_phone(html)
            contact_tag = soup.select_one(".re__contact-name")
            contact_name = contact_tag.get_text(strip=True) if contact_tag else ""

            # Property type
            prop_type = _infer_property_type(title, description)
            tx_type   = "thue" if "/thue-" in url or "nha-dat-thue" in url else "ban"

            # External ID
            ext_id_match = re.search(r"/pr(\d+)", url)
            ext_id = ext_id_match.group(1) if ext_id_match else None

            # Image URLs
            img_urls = _extract_image_urls(soup)

            return {
                "external_id":      ext_id,
                "source_id":        ext_id,
                "url":              url,
                "title":            title,
                "description":      description[:2000],
                "raw_area_text":    address,
                "price_ty":         price_total,
                "price_per_m2":     price_per_m2,
                "area_m2":          area_m2,
                "property_type":    prop_type,
                "tx_type":          tx_type,
                "transaction_type": tx_type,
                "contact_phone":    phone,
                "seller_name":      contact_name,
                "img_urls":         img_urls,
            }
        except Exception as e:
            self.logger.error(f"Parse error [{url}]: {e}")
            return None


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _parse_price_vnd(text: str) -> Optional[float]:
    """Chuyển chuỗi giá thành tỷ VND. VD: '2.5 tỷ' → 2.5, '500 triệu' → 0.5"""
    text = text.lower().replace(",", ".").strip()
    try:
        if "tỷ" in text:
            num = re.search(r"[\d.]+", text)
            return float(num.group()) if num else None
        if "triệu" in text:
            num = re.search(r"[\d.]+", text)
            return float(num.group()) / 1000 if num else None
    except Exception:
        pass
    return None


def _parse_price_per_m2(text: str) -> Optional[float]:
    """Chuyển giá/m2 thành triệu VND/m2."""
    text = text.lower().replace(",", ".").strip()
    try:
        if "triệu" in text:
            num = re.search(r"[\d.]+", text)
            return float(num.group()) if num else None
        if "tỷ" in text:
            num = re.search(r"[\d.]+", text)
            return float(num.group()) * 1000 if num else None
    except Exception:
        pass
    return None


def _parse_area(text: str) -> Optional[float]:
    """Trích diện tích m2. VD: '120 m²' → 120.0"""
    text = text.replace(",", ".").strip()
    num = re.search(r"[\d.]+", text)
    try:
        return float(num.group()) if num else None
    except Exception:
        return None


def _extract_phone(html: str) -> Optional[str]:
    patterns = [
        r"(?<!\d)(0[3-9]\d{8})(?!\d)",
        r"(?<!\d)(84[3-9]\d{8})(?!\d)",
    ]
    for pat in patterns:
        match = re.search(pat, html)
        if match:
            return match.group(1)
    return None


def _extract_image_urls(soup) -> List[str]:
    """Trích danh sách URL ảnh từ trang listing BatDongSan."""
    urls = []
    seen = set()

    # Selector chính: gallery thumbnails
    for img in soup.select(".re__media-carousel img, .js__pr-media-carousel img"):
        src = img.get("data-src") or img.get("src") or ""
        if src and src.startswith("http") and src not in seen:
            # Lấy URL full size (thay thumbnail suffix)
            src = src.replace("_thumb", "").replace("_150x", "").replace("_220x", "")
            seen.add(src)
            urls.append(src)

    # Fallback: data-original trong lazy-load
    if not urls:
        for img in soup.select("img[data-original]"):
            src = img.get("data-original", "")
            if src and src.startswith("http") and src not in seen:
                seen.add(src)
                urls.append(src)

    return urls[:20]  # Tối đa 20 ảnh/listing


def _infer_property_type(title: str, desc: str) -> str:
    text = (title + " " + desc).lower()
    if any(k in text for k in ["đất nền", "lô đất", "đất thổ", "đất ở"]):
        return "dat_nen"
    if any(k in text for k in ["nhà phố", "nhà mặt tiền", "nhà mặt phố"]):
        return "nha_pho"
    if any(k in text for k in ["phòng trọ", "nhà trọ", "dãy trọ", "khu trọ"]):
        return "nha_tro"
    if any(k in text for k in ["căn hộ", "chung cư", "apartment"]):
        return "can_ho"
    if any(k in text for k in ["nhà xưởng", "kho xưởng", "xưởng sản xuất"]):
        return "nha_xuong"
    return "khac"
