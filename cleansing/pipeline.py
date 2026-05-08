"""
Data Cleansing & Normalization Pipeline
- Dedup, chuẩn hóa, tính giá/m2, ghi vào PostgreSQL
"""
import logging
import re
from typing import List, Dict, Optional
from datetime import datetime

from config.settings import WATCH_AREAS, ALERT_KEYWORDS
from config.database import get_conn

logger = logging.getLogger(__name__)


def resolve_area_id(area_name: str) -> Optional[int]:
    """Lấy area_id từ DB theo tên khu vực."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM areas WHERE name = %s", (area_name,))
            row = cur.fetchone()
            return row[0] if row else None


def _match_area(raw_text: str) -> Optional[str]:
    """So khớp raw địa chỉ với khu vực theo dõi."""
    if not raw_text:
        return None
    text = raw_text.lower()
    for area in WATCH_AREAS:
        if any(kw in text for kw in area["keywords"]):
            return area["name"]
    return None


def _extract_keywords(title: str, description: str) -> List[str]:
    """Trích các keyword quan trọng từ title + description."""
    text = (title + " " + description).lower()
    found = []
    for kw in ALERT_KEYWORDS:
        if kw in text:
            found.append(kw)
    return found


def _is_hot(title: str, description: str) -> bool:
    """Phát hiện tin ngộp / bán gấp."""
    hot_signals = ["cắt lỗ", "ngộp", "bán gấp", "bán nhanh", "kẹt tiền", "cần tiền gấp", "giảm giá mạnh"]
    text = (title + " " + description).lower()
    return any(s in text for s in hot_signals)


def _normalize_record(raw: Dict) -> Optional[Dict]:
    """Chuẩn hóa một record thô thành record sẵn sàng lưu DB."""
    try:
        title       = (raw.get("title") or "").strip()
        description = (raw.get("description") or "").strip()
        url         = (raw.get("url") or "").strip()

        if not url or not title:
            return None

        # Xác định khu vực
        area_name = raw.get("area_name") or _match_area(raw.get("raw_area_text", ""))
        area_id   = resolve_area_id(area_name) if area_name else None

        # Giá
        price_total  = raw.get("price_total")
        area_m2      = raw.get("area_m2")
        price_per_m2 = raw.get("price_per_m2")

        if price_total and area_m2 and area_m2 > 0 and not price_per_m2:
            price_per_m2 = round((price_total * 1_000) / area_m2, 3)  # triệu/m2

        # Sanity check giá
        if price_per_m2 and (price_per_m2 < 0.1 or price_per_m2 > 500_000):
            price_per_m2 = None
        if price_total and (price_total < 0.001 or price_total > 10_000):
            price_total = None

        keywords = _extract_keywords(title, description)
        is_hot   = _is_hot(title, description)

        return {
            "source":           raw.get("source", "unknown"),
            "external_id":      raw.get("external_id"),
            "url":              url,
            "title":            title[:500],
            "description":      description[:4000],
            "area_id":          area_id,
            "raw_area_text":    (raw.get("raw_area_text") or area_name or "")[:200],
            "price_total":      price_total,
            "price_per_m2":     price_per_m2,
            "area_m2":          area_m2,
            "property_type":    raw.get("property_type", "khac"),
            "transaction_type": raw.get("transaction_type", "ban"),
            "contact_phone":    (raw.get("contact_phone") or "")[:50] or None,
            "seller_name":      (raw.get("seller_name") or "")[:200] or None,
            "keywords":         keywords,
            "is_hot":           is_hot,
            "raw_json":         _safe_json(raw),
        }
    except Exception as e:
        logger.error(f"Normalize error: {e} | raw={raw.get('url', '')}")
        return None


def _safe_json(d: dict) -> dict:
    """Loại bỏ các field không serializable."""
    import json
    try:
        json.dumps(d)
        return d
    except Exception:
        return {k: str(v) for k, v in d.items()}


UPSERT_SQL = """
INSERT INTO listings (
    source, external_id, url, title, description,
    area_id, raw_area_text, price_total, price_per_m2, area_m2,
    property_type, transaction_type, contact_phone, seller_name,
    keywords, is_hot, raw_json
) VALUES (
    %(source)s, %(external_id)s, %(url)s, %(title)s, %(description)s,
    %(area_id)s, %(raw_area_text)s, %(price_total)s, %(price_per_m2)s, %(area_m2)s,
    %(property_type)s, %(transaction_type)s, %(contact_phone)s, %(seller_name)s,
    %(keywords)s, %(is_hot)s, %(raw_json)s::jsonb
)
ON CONFLICT (url) DO UPDATE SET
    title           = EXCLUDED.title,
    price_total     = EXCLUDED.price_total,
    price_per_m2    = EXCLUDED.price_per_m2,
    area_m2         = EXCLUDED.area_m2,
    keywords        = EXCLUDED.keywords,
    is_hot          = EXCLUDED.is_hot,
    updated_at      = NOW()
RETURNING id, (xmax = 0) AS is_new;
"""

PRICE_HISTORY_SQL = """
INSERT INTO price_history (listing_id, price_total, price_per_m2)
VALUES (%s, %s, %s)
"""


def save_records(records: List[Dict]) -> Dict[str, int]:
    """Lưu list records vào DB. Trả về stats."""
    inserted = updated = skipped = 0

    with get_conn() as conn:
        with conn.cursor() as cur:
            for rec in records:
                try:
                    import json
                    rec["raw_json"] = json.dumps(rec["raw_json"])
                    cur.execute(UPSERT_SQL, rec)
                    row = cur.fetchone()
                    if row:
                        listing_id, is_new = row
                        if is_new:
                            inserted += 1
                        else:
                            updated += 1
                            # Ghi lịch sử giá nếu có thay đổi
                            if rec["price_total"] or rec["price_per_m2"]:
                                cur.execute(PRICE_HISTORY_SQL,
                                            (listing_id, rec["price_total"], rec["price_per_m2"]))
                except Exception as e:
                    logger.error(f"DB save error [{rec.get('url', '')}]: {e}")
                    skipped += 1

    logger.info(f"Save done: {inserted} new, {updated} updated, {skipped} skipped")
    return {"inserted": inserted, "updated": updated, "skipped": skipped}


def run_pipeline(raw_records: List[Dict]) -> Dict[str, int]:
    """Entry point: chuẩn hóa → dedup → lưu DB."""
    normalized = []
    seen_urls  = set()
    for raw in raw_records:
        rec = _normalize_record(raw)
        if rec and rec["url"] not in seen_urls:
            seen_urls.add(rec["url"])
            normalized.append(rec)

    logger.info(f"Pipeline: {len(raw_records)} raw → {len(normalized)} normalized")
    return save_records(normalized)
