"""Processed listing repository helpers."""
import logging
from datetime import datetime
from typing import Optional

from db.connection import get_conn

logger = logging.getLogger(__name__)
# ─── PROCESSED layer ──────────────────────────────────────────────────────────

def _same_price_snapshot(a: Optional[float], b: Optional[float]) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return abs(float(a) - float(b)) < 0.000001


def _should_insert_price_history(conn, listing_id: int,
                                 price_ty: Optional[float],
                                 price_per_m2: Optional[float]) -> bool:
    if price_ty is None and price_per_m2 is None:
        return False

    latest = conn.execute("""
        SELECT price_ty, price_per_m2
        FROM price_history
        WHERE listing_id = ?
        ORDER BY recorded_at DESC, id DESC
        LIMIT 1
    """, (listing_id,)).fetchone()
    if latest is None:
        return True

    return not (
        _same_price_snapshot(price_ty, latest["price_ty"])
        and _same_price_snapshot(price_per_m2, latest["price_per_m2"])
    )


def upsert_listing(rec: dict, crawl_run_id: Optional[int] = None) -> tuple:
    """
    Insert or update listing từ normalized record.
    Returns (listing_id, is_new).
    """
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id, price_ty, price_first_ty, price_dropped, suspicious_bait FROM listings WHERE url = ?",
            (rec["url"],)
        ).fetchone()

        now = datetime.now().isoformat()

        if existing is None:
            # Logic giá trị: set first_seen_at=last_seen_at=now cho lifecycle tracking
            cur = conn.execute("""
                INSERT INTO listings (
                    raw_id, source, source_id, url, title, description,
                    area, ward, raw_area_text, price_ty, price_per_m2, area_m2,
                    property_type, tx_type, frontage_m, depth_m,
                    road_type, road_tier, tho_cu_m2, tho_cu_ratio, has_so, is_hot, contact_phone, seller_name,
                    price_first_ty, crawled_at, updated_at,
                    first_seen_at, last_seen_at, is_active, posted_at
                ) VALUES (
                    :raw_id, :source, :source_id, :url, :title, :description,
                    :area, :ward, :raw_area_text, :price_ty, :price_per_m2, :area_m2,
                    :property_type, :tx_type, :frontage_m, :depth_m,
                    :road_type, :road_tier, :tho_cu_m2, :tho_cu_ratio, :has_so, :is_hot, :contact_phone, :seller_name,
                    :price_ty, :crawled_at, :updated_at,
                    :crawled_at, :crawled_at, 1, :posted_at
                )
            """, {
                "raw_id":       rec.get("raw_id"),
                "source":       rec["source"],
                "source_id":    rec.get("source_id", ""),
                "url":          rec["url"],
                "title":        rec.get("title", ""),
                "description":  rec.get("description", ""),
                "area":         rec.get("area", ""),
                "ward":         rec.get("ward") or rec.get("area") or None,
                "raw_area_text": rec.get("raw_area_text", ""),
                "price_ty":     rec.get("price_ty"),
                "price_per_m2": rec.get("price_per_m2"),
                "area_m2":      rec.get("area_m2"),
                "property_type": rec.get("property_type", "khac"),
                "tx_type":      rec.get("tx_type", "ban"),
                "frontage_m":   rec.get("frontage_m"),
                "depth_m":      rec.get("depth_m"),
                "road_type":    rec.get("road_type", "unknown"),
                "road_tier":    int(rec.get("road_tier", 0)),
                "tho_cu_m2":    rec.get("tho_cu_m2"),
                "tho_cu_ratio": rec.get("tho_cu_ratio"),
                "has_so":       int(rec.get("has_so", True)),
                "is_hot":       int(rec.get("is_hot", False)),
                "contact_phone": rec.get("contact_phone"),
                "seller_name":  rec.get("seller_name"),
                "crawled_at":   now,
                "updated_at":   now,
                "posted_at":    rec.get("post_date"),
            })
            listing_id = cur.lastrowid

            if _should_insert_price_history(conn, listing_id, rec.get("price_ty"), rec.get("price_per_m2")):
                conn.execute(
                    "INSERT INTO price_history (listing_id, price_ty, price_per_m2, crawl_run_id) VALUES (?,?,?,?)",
                    (listing_id, rec.get("price_ty"), rec.get("price_per_m2"), crawl_run_id)
                )
            return listing_id, True

        else:
            listing_id  = existing["id"]
            first_price = existing["price_first_ty"] or existing["price_ty"]
            new_price   = rec.get("price_ty")
            price_dropped  = existing["price_dropped"]
            price_drop_pct = None
            suspicious_bait = existing["suspicious_bait"] if "suspicious_bait" in existing.keys() else 0

            if new_price and first_price and new_price < first_price * 0.99:
                drop_pct = round((first_price - new_price) / first_price * 100, 2)
                if drop_pct > 40.0:
                    price_dropped = 0
                    price_drop_pct = None
                    suspicious_bait = 1
                else:
                    price_dropped = 1
                    price_drop_pct = drop_pct
                    suspicious_bait = 0

            conn.execute("""
                UPDATE listings SET
                    title               = :title,
                    price_ty            = :price_ty,
                    price_per_m2        = :price_per_m2,
                    area_m2             = :area_m2,
                    property_type       = :property_type,
                    area                = :area,
                    road_tier           = CASE WHEN llm_verified = 1 THEN road_tier
                                               WHEN :road_tier > 0 THEN :road_tier
                                               ELSE 0 END,
                    road_type           = :road_type,
                    tho_cu_m2           = :tho_cu_m2,
                    tho_cu_ratio        = :tho_cu_ratio,
                    ward                = :ward,                 -- cho phép NULL overwrite (re-normalize có thể loại ward sai khi text chứa địa danh non-TDM)
                    has_so              = :has_so,
                    is_hot              = :is_hot,
                    price_dropped       = :price_dropped,
                    price_drop_pct      = :price_drop_pct,
                    suspicious_bait     = :suspicious_bait,
                    consecutive_missing = 0,
                    updated_at          = :updated_at,
                    last_seen_at        = :updated_at,
                    first_seen_at       = COALESCE(first_seen_at, :updated_at),
                    is_active           = 1,
                    delisted_at         = NULL,
                    posted_at           = COALESCE(posted_at, :posted_at)
                WHERE id = :id
            """, {
                "id":            listing_id,
                "title":         rec.get("title", ""),
                "price_ty":      new_price,
                "price_per_m2":  rec.get("price_per_m2"),
                "area_m2":       rec.get("area_m2"),
                "property_type": rec.get("property_type", "dat_nen"),
                "area":          rec.get("area", ""),
                "road_tier":     int(rec.get("road_tier", 0)),
                "road_type":     rec.get("road_type") or "unknown",
                "tho_cu_m2":     rec.get("tho_cu_m2"),
                "tho_cu_ratio":  rec.get("tho_cu_ratio"),
                "ward":          rec.get("ward") or None,
                "has_so":        int(rec.get("has_so", True)),
                "is_hot":        int(rec.get("is_hot", False)),
                "price_dropped": price_dropped,
                "price_drop_pct": price_drop_pct,
                "suspicious_bait": suspicious_bait,
                "updated_at":    now,
                "posted_at":     rec.get("post_date"),
            })

            if _should_insert_price_history(conn, listing_id, new_price, rec.get("price_per_m2")):
                conn.execute(
                    "INSERT INTO price_history (listing_id, price_ty, price_per_m2, crawl_run_id) VALUES (?,?,?,?)",
                    (listing_id, new_price, rec.get("price_per_m2"), crawl_run_id)
                )
            return listing_id, False


def update_listing_outlier(listing_id: int, is_outlier: bool,
                           direction: Optional[str], sigma: Optional[float]) -> None:
    """Cập nhật outlier flag sau khi chạy valuation."""
    with get_conn() as conn:
        conn.execute("""
            UPDATE listings SET
                is_outlier        = ?,
                outlier_direction = ?,
                outlier_sigma     = ?
            WHERE id = ?
        """, (int(is_outlier), direction, sigma, listing_id))


def insert_images(listing_id: int, img_urls: list) -> None:
    with get_conn() as conn:
        for order, url in enumerate(img_urls):
            img_type = _classify_image_type(url, order)
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO listing_images (listing_id, img_url, img_order, img_type) VALUES (?,?,?,?)",
                    (listing_id, url, order, img_type)
                )
            except Exception as e:
                logger.warning(f"Image insert skip: {e}")


def _classify_image_type(url: str, order: int) -> str:
    url_lower = url.lower()
    if any(k in url_lower for k in ["so-hong", "sohong", "so-do", "sodo", "gcn", "qsd", "giay-chung-nhan"]):
        return "so_hong"
    if any(k in url_lower for k in ["aerial", "drone", "satellite"]):
        return "aerial"
    return "cover" if order == 0 else "unknown"



