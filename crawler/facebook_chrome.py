"""
Helper: chuyển đổi post thô từ Claude-in-Chrome → record cho insert_raw().
Không dùng Playwright / BaseCrawler — chỉ là data transformer.
"""
import re
from typing import Optional

SOURCE_NAME = "facebook"

BDS_KEYWORDS = ["dat", "nha", "m2", "ty", "trieu", "rao", "so do", "so hong",
                "tho cu", "chinh chu", "nen", "dat nen", "dat vuon",
                "dat", "nha", "m\u00b2", "t\u1ef7", "tri\u1ec7u", "rao", "s\u1ed5",
                "th\u1ed5 c\u01b0", "ch\u00ednh ch\u1ee7", "n\u1ec1n"]

AREA_KEYWORDS = ["t\u00e2n an", "tan an"]

_PHONE_RE = re.compile(
    r"(?<!\d)(0|\+84)(3[2-9]|5[25689]|7[06-9]|8[1-9]|9[0-9])\d{7}(?!\d)"
)


def has_bds_keywords(text: str) -> bool:
    t = text.lower()
    return any(k in t for k in BDS_KEYWORDS)


def has_area_keywords(text: str) -> bool:
    t = text.lower()
    return any(k in t for k in AREA_KEYWORDS)


def is_relevant(text: str) -> bool:
    """Bài đăng có BĐS keywords là lấy — area filter để normalizer/valuation xử lý."""
    return has_bds_keywords(text)


def extract_phone(text: str) -> Optional[str]:
    m = _PHONE_RE.search(text)
    return m.group(0) if m else None


def build_record(post: dict) -> Optional[dict]:
    """
    post: dict từ skill facebook-crawl với các fields:
        url, post_id, text, date_raw, seller_name, profile_url
    Trả về None nếu thiếu url hoặc text rỗng.
    """
    url = (post.get("url") or "").strip()
    text = (post.get("text") or "").strip()
    if not url or not text:
        return None

    return {
        "url":           url,
        "post_id":       post.get("post_id") or "",
        "title":         text[:100],
        "description":   text,
        "contact_phone": extract_phone(text),
        "imgs":          post.get("imgs") or [],
        "date_raw":      post.get("date_raw") or "",
        "tx_type":       "thue" if any(k in text.lower() for k in ["cho thu\u00ea", "c\u1ea7n thu\u00ea"]) else "ban",
        "source":        SOURCE_NAME,
        "seller_name":   post.get("seller_name") or "",
        "profile_url":   post.get("profile_url") or "",
        "default_area":  post.get("default_area"),
    }
