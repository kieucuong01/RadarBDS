"""
Dedup — phát hiện cùng 1 bất động sản xuất hiện nhiều lần (same-source hoặc cross-source).

Cả 2 luồng dùng cùng scoring system:

Hard gates (bắt buộc):
  - Đăng khác ngày              : tránh match bài cùng phiên crawl
  - property_type giống nhau    : dat_nen ≠ nha_dat (nếu cả 2 đã biết)
  - ward giống nhau             : (nếu cả 2 đã biết)

Scoring (không dùng SĐT):
  - Mặt tiền chính xác (tol=0)  : +4đ
  - Chiều sâu chính xác (tol=0) : +3đ
  - Diện tích chính xác (tol=0) : +2đ
  - Text sim ≥ 0.85             : +6đ  (copy-paste nguyên bài)
  - Text sim ≥ 0.70             : +4đ
  - Text sim ≥ 0.50             : +2đ
  - Text sim ≥ 0.30             : +1đ
  ────────────────────────────────
  Cần tổng ≥ 6đ (SCORE_THRESHOLD)

3 case quyết định:
  Case 1: front_exact + depth_exact → cần text ≥ 0.30  (min 8đ)
  Case 2: area_exact (thiếu front/depth) → cần text ≥ 0.70  (min 6đ)
  Case 3: không có số liệu → cần text ≥ 0.85  (copy-paste, 6đ)
"""

import logging
import re
import sqlite3
from difflib import SequenceMatcher
from typing import Optional

logger = logging.getLogger(__name__)


# ── Text helpers ──────────────────────────────────────────────────────────────

_PRICE_PAT = re.compile(
    r'\d[\d.,]*\s*(?:tỷ|ty|t|triệu|tr|m)',
    re.IGNORECASE | re.UNICODE
)
_PHONE_PAT = re.compile(r'(?:0|\+84)\d{8,10}')


def _strip_noise(text: str) -> str:
    """Xoá giá, SĐT, emoji, ký tự đặc biệt → so sánh nội dung thuần."""
    text = _PRICE_PAT.sub(' ', text)
    text = _PHONE_PAT.sub(' ', text)
    text = re.sub(r'[^\w\sàáảãạăắặẳẵặâấầẩẫậèéẻẽẹêếềểễệìíỉĩịòóỏõọôốồổỗộơớờởỡợùúủũụưứừửữựỳýỷỹỵđ]', ' ', text, flags=re.UNICODE)
    text = re.sub(r'\s+', ' ', text).strip().lower()
    return text


def _text_similarity(t1: Optional[str], t2: Optional[str]) -> float:
    """Cosine-like similarity của description sau khi bỏ giá & SĐT. 0.0–1.0."""
    if not t1 or not t2:
        return 0.0
    s1 = _strip_noise(t1)
    s2 = _strip_noise(t2)
    if not s1 or not s2:
        return 0.0
    # SequenceMatcher trên 500 ký tự đầu để giới hạn thời gian
    return SequenceMatcher(None, s1[:500], s2[:500]).ratio()


# ── Numeric helpers ───────────────────────────────────────────────────────────

def _near(a: Optional[float], b: Optional[float], tol: float) -> bool:
    if a is None or b is None or a <= 0 or b <= 0:
        return False
    return abs(a - b) / max(a, b) <= tol


def _same_ward(l1: dict, l2: dict) -> bool:
    w1 = (l1.get("ward") or l1.get("area") or "").lower().strip()
    w2 = (l2.get("ward") or l2.get("area") or "").lower().strip()
    if not w1 or not w2:
        return True  # thiếu thông tin → không chặn
    return w1 == w2



def _different_days(l1: dict, l2: dict) -> bool:
    """True nếu 2 listing được đăng/crawl vào ngày khác nhau."""
    # Ưu tiên posted_at (ngày đăng FB), fallback sang crawled_at
    d1 = (l1.get("posted_at") or l1.get("crawled_at") or "")[:10]
    d2 = (l2.get("posted_at") or l2.get("crawled_at") or "")[:10]
    if not d1 or not d2:
        return True  # không rõ → cho qua
    return d1 != d2


# ── Scoring ───────────────────────────────────────────────────────────────────

SCORE_THRESHOLD = 6   # tổng điểm tối thiểu để kết luận repost


def _repost_score(l1: dict, l2: dict) -> int:
    """
    Tính điểm "khả năng là cùng 1 BĐS".
    Dùng cho cả same-source và cross-source.
    Trả về tổng điểm (0 = không match, ≥ SCORE_THRESHOLD = duplicate).
    """
    # ── Hard gates ────────────────────────────────────────────────────────────
    if not _different_days(l1, l2):
        return 0

    pt1, pt2 = l1.get("property_type"), l2.get("property_type")
    if pt1 and pt2 and pt1 != pt2:
        return 0

    w1 = (l1.get("ward") or "").strip()
    w2 = (l2.get("ward") or "").strip()
    if w1 and w2 and w1 != w2:
        return 0

    # ── Structural scoring (exact — tol=0.0) ─────────────────────────────────
    score = 0

    front_match = _near(l1.get("frontage_m"), l2.get("frontage_m"), 0.0)
    depth_match = _near(l1.get("depth_m"),    l2.get("depth_m"),    0.0)
    area_match  = _near(l1.get("area_m2"),    l2.get("area_m2"),    0.0)

    if front_match: score += 4
    if depth_match: score += 3
    if area_match:  score += 2

    # ── Text similarity scoring (tăng trọng số) ───────────────────────────────
    sim = _text_similarity(l1.get("description"), l2.get("description"))

    if   sim >= 0.85: score += 6
    elif sim >= 0.70: score += 4
    elif sim >= 0.50: score += 2
    elif sim >= 0.30: score += 1

    # ── Case quyết định ───────────────────────────────────────────────────────
    # Case 1: kích thước chính xác (ngang + sâu) → chỉ cần text tương đối
    if front_match and depth_match:
        return score if sim >= 0.30 else 0

    # Case 2: chỉ có diện tích (không có ngang/sâu) → cần text giống nhiều
    if area_match:
        return score if sim >= 0.70 else 0

    # Case 3: không có số liệu → phải là copy-paste gần như nguyên xi
    if sim >= 0.85:
        return score

    return 0


def _is_duplicate(l1: dict, l2: dict) -> bool:
    """
    True nếu 2 listing có thể là cùng 1 BĐS.
    Same-source và cross-source dùng chung scoring.
    """
    # Cùng source_id (non-empty) → repost chắc chắn (chỉ áp dụng same-source)
    if l1["source"] == l2["source"]:
        sid1 = (l1.get("source_id") or "").strip()
        sid2 = (l2.get("source_id") or "").strip()
        if sid1 and sid2 and sid1 == sid2:
            return True

    return _repost_score(l1, l2) >= SCORE_THRESHOLD


# ── DB-level flagging ─────────────────────────────────────────────────────────

def flag_duplicates_in_db(conn: sqlite3.Connection) -> dict:
    """
    Quét listings, gắn possibly_duplicate + duplicate_of_id.
    Canonical = listing crawled sớm nhất (= giá gốc đầu tiên).
    Trả về stats dict.
    """
    conn.execute("UPDATE listings SET possibly_duplicate=0, duplicate_of_id=NULL")

    rows = conn.execute("""
        SELECT id, source, source_id, url, area, ward,
               property_type, area_m2, price_ty, crawled_at, posted_at,
               frontage_m, depth_m, contact_phone, has_so, description
        FROM listings
        WHERE probably_sold = 0
        ORDER BY crawled_at ASC
    """).fetchall()

    listings = [dict(r) for r in rows]
    n = len(listings)

    # Union-Find
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        pa, pb = find(a), find(b)
        if pa != pb:
            parent[pa] = pb

    # Optimized comparison using groups (ward, property_type)
    # Vì _is_duplicate sẽ trả về 0 nếu ward hoặc property_type khác nhau
    from collections import defaultdict
    buckets = defaultdict(list)
    for i, l in enumerate(listings):
        w = (l.get("ward") or "").strip()
        pt = l.get("property_type") or ""
        buckets[(w, pt)].append(i)

    for (w, pt), indices in buckets.items():
        if len(indices) < 2:
            continue
        # Chỉ so sánh nội bộ trong bucket
        for idx_i in range(len(indices)):
            for idx_j in range(idx_i + 1, len(indices)):
                i, j = indices[idx_i], indices[idx_j]
                if _is_duplicate(listings[i], listings[j]):
                    union(i, j)

    # Gom groups
    groups: dict[int, list[int]] = {}
    for i in range(n):
        root = find(i)
        groups.setdefault(root, []).append(i)

    dup_groups = {k: v for k, v in groups.items() if len(v) >= 2}
    flagged = 0
    price_drops_detected = 0

    for group_indices in dup_groups.values():
        # Canonical = listing crawled/đăng sớm nhất → đây là giá gốc
        canonical_idx = min(
            group_indices,
            key=lambda i: (listings[i].get("posted_at") or listings[i].get("crawled_at") or "")
        )
        canonical_id    = listings[canonical_idx]["id"]
        canonical_price = listings[canonical_idx].get("price_ty")

        for idx in group_indices:
            if idx == canonical_idx:
                continue
            dup_id = listings[idx]["id"]

            conn.execute(
                "UPDATE listings SET possibly_duplicate=1, duplicate_of_id=? WHERE id=?",
                (canonical_id, dup_id)
            )
            flagged += 1

            # ── Phát hiện giảm giá trong nhóm trùng ──────────────────────
            dup_price = listings[idx].get("price_ty")
            dup_time  = listings[idx].get("posted_at") or listings[idx].get("crawled_at") or ""
            can_time  = listings[canonical_idx].get("posted_at") or listings[canonical_idx].get("crawled_at") or ""

            if (
                canonical_price and dup_price
                and dup_price < canonical_price * 0.99
                and dup_time >= can_time  # bài mới hơn giá thấp hơn
            ):
                drop_pct = round((canonical_price - dup_price) / canonical_price * 100, 2)
                conn.execute("""
                    UPDATE listings SET
                        price_dropped  = 1,
                        price_drop_pct = ?,
                        price_first_ty = COALESCE(price_first_ty, ?)
                    WHERE id = ?
                """, (drop_pct, canonical_price, dup_id))
                price_drops_detected += 1
                logger.info(
                    f"Price drop via repost: listing_id={dup_id} "
                    f"{canonical_price:.2f}→{dup_price:.2f}ty (-{drop_pct}%)"
                )

    stats = {
        "total":        n,
        "dup_groups":   len(dup_groups),
        "flagged":      flagged,
        "unique_lots":  n - flagged,
        "price_drops":  price_drops_detected,
    }
    logger.info(
        f"Dedup: {n} listings → {len(dup_groups)} groups → "
        f"{flagged} flagged → {n - flagged} unique lots → "
        f"{price_drops_detected} price drops detected"
    )
    return stats


# ── Query helpers ─────────────────────────────────────────────────────────────

def get_dedup_stats(conn: sqlite3.Connection) -> dict:
    """Đọc stats từ flags đã lưu — không re-scan."""
    total = conn.execute(
        "SELECT COUNT(*) FROM listings WHERE probably_sold=0"
    ).fetchone()[0]
    flagged = conn.execute(
        "SELECT COUNT(*) FROM listings WHERE probably_sold=0 AND possibly_duplicate=1"
    ).fetchone()[0]
    cross = conn.execute("""
        SELECT COUNT(*) FROM listings l
        WHERE l.possibly_duplicate=1 AND l.probably_sold=0
          AND EXISTS (
              SELECT 1 FROM listings c
              WHERE c.id = l.duplicate_of_id AND c.source != l.source
          )
    """).fetchone()[0]
    return {
        "total_listings": total,
        "flagged":        flagged,
        "cross_source":   cross,
        "same_source":    flagged - cross,
        "unique_lots":    total - flagged,
    }
