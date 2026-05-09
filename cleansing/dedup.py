"""Detect reposts of the same property and reliable repost price drops."""

import logging
import re
import sqlite3
from difflib import SequenceMatcher
from typing import Optional

logger = logging.getLogger(__name__)

SCORE_THRESHOLD = 6

_PRICE_PAT = re.compile(
    r"\d[\d.,]*\s*(?:tỷ|ty|t|triệu|tr|m)",
    re.IGNORECASE | re.UNICODE,
)
_PHONE_PAT = re.compile(r"(?:0|\+84)\d{8,10}")
_ROAD_TOKEN_PAT = re.compile(
    r"\b(?:dx|dj|dt|dh|dl|ql|tl|ni|nj)\s*0*(\d{1,4})\b",
    re.IGNORECASE,
)


def _strip_noise(text: str) -> str:
    text = _PRICE_PAT.sub(" ", text)
    text = _PHONE_PAT.sub(" ", text)
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip().lower()


def _text_similarity(t1: Optional[str], t2: Optional[str]) -> float:
    if not t1 or not t2:
        return 0.0
    s1 = _strip_noise(t1)
    s2 = _strip_noise(t2)
    if not s1 or not s2:
        return 0.0
    return SequenceMatcher(None, s1[:500], s2[:500]).ratio()


def _combined_text(listing: dict) -> str:
    return f"{listing.get('title') or ''} {listing.get('description') or ''}"


def _road_tokens(text: Optional[str]) -> set[str]:
    if not text:
        return set()
    tokens = set()
    for m in _ROAD_TOKEN_PAT.finditer(text.lower()):
        raw = re.sub(r"\s+", "", m.group(0).lower())
        prefix = re.match(r"[a-z]+", raw).group(0)
        tokens.add(f"{prefix}{int(m.group(1))}")
    return tokens


def _same_source_id(l1: dict, l2: dict) -> bool:
    if l1.get("source") != l2.get("source"):
        return False
    sid1 = (l1.get("source_id") or "").strip()
    sid2 = (l2.get("source_id") or "").strip()
    return bool(sid1 and sid2 and sid1 == sid2)


def _same_required_segment(l1: dict, l2: dict) -> bool:
    pt1, pt2 = l1.get("property_type"), l2.get("property_type")
    w1 = (l1.get("ward") or "").strip()
    w2 = (l2.get("ward") or "").strip()
    return bool(pt1 and pt2 and pt1 == pt2 and w1 and w2 and w1 == w2)


def _near(a: Optional[float], b: Optional[float], tol: float) -> bool:
    if a is None or b is None or a <= 0 or b <= 0:
        return False
    return abs(a - b) / max(a, b) <= tol


def _same_ward(l1: dict, l2: dict) -> bool:
    w1 = (l1.get("ward") or l1.get("area") or "").lower().strip()
    w2 = (l2.get("ward") or l2.get("area") or "").lower().strip()
    if not w1 or not w2:
        return True
    return w1 == w2


def _different_days(l1: dict, l2: dict) -> bool:
    d1 = (l1.get("posted_at") or l1.get("crawled_at") or "")[:10]
    d2 = (l2.get("posted_at") or l2.get("crawled_at") or "")[:10]
    if not d1 or not d2:
        return True
    return d1 != d2


def _has_reliable_lot_signature(l1: dict, l2: dict) -> bool:
    """Strong evidence that reposts are the same lot, not just the same broker template."""
    if _same_source_id(l1, l2):
        return True

    if not _same_required_segment(l1, l2):
        return False

    front_depth_match = (
        _near(l1.get("frontage_m"), l2.get("frontage_m"), 0.0)
        and _near(l1.get("depth_m"), l2.get("depth_m"), 0.0)
    )
    if front_depth_match:
        return True

    area_match = _near(l1.get("area_m2"), l2.get("area_m2"), 0.01)
    if area_match:
        return True

    roads1 = _road_tokens(_combined_text(l1))
    roads2 = _road_tokens(_combined_text(l2))
    if roads1 and roads2 and roads1.intersection(roads2):
        return _near(l1.get("area_m2"), l2.get("area_m2"), 0.10)

    return False


def _is_reliable_price_drop(canonical: dict, candidate: dict) -> bool:
    canonical_price = canonical.get("price_ty")
    candidate_price = candidate.get("price_ty")
    can_time = canonical.get("posted_at") or canonical.get("crawled_at") or ""
    cand_time = candidate.get("posted_at") or candidate.get("crawled_at") or ""

    return bool(
        canonical_price
        and candidate_price
        and candidate_price < canonical_price * 0.99
        and cand_time >= can_time
        and _has_reliable_lot_signature(canonical, candidate)
    )


def _repost_score(l1: dict, l2: dict) -> int:
    if not _different_days(l1, l2):
        return 0

    pt1, pt2 = l1.get("property_type"), l2.get("property_type")
    if pt1 and pt2 and pt1 != pt2:
        return 0

    if not _same_ward(l1, l2):
        return 0

    front_match = _near(l1.get("frontage_m"), l2.get("frontage_m"), 0.0)
    depth_match = _near(l1.get("depth_m"), l2.get("depth_m"), 0.0)
    area_match = _near(l1.get("area_m2"), l2.get("area_m2"), 0.0)

    score = 0
    if front_match:
        score += 4
    if depth_match:
        score += 3
    if area_match:
        score += 2

    sim = _text_similarity(l1.get("description"), l2.get("description"))
    if sim >= 0.85:
        score += 6
    elif sim >= 0.70:
        score += 4
    elif sim >= 0.50:
        score += 2
    elif sim >= 0.30:
        score += 1

    if front_match and depth_match:
        return score if sim >= 0.30 else 0
    if area_match:
        return score if sim >= 0.70 else 0
    if sim >= 0.85:
        return score
    return 0


def _is_duplicate(l1: dict, l2: dict) -> bool:
    if _same_source_id(l1, l2):
        return True
    return _repost_score(l1, l2) >= SCORE_THRESHOLD


def flag_duplicates_in_db(conn: sqlite3.Connection) -> dict:
    """Flag duplicate reposts and reliable repost price drops."""
    conn.execute("""
        UPDATE listings
        SET price_dropped = CASE
                WHEN price_first_ty IS NOT NULL
                 AND price_ty IS NOT NULL
                 AND price_ty < price_first_ty * 0.99
                THEN 1 ELSE 0 END,
            price_drop_pct = CASE
                WHEN price_first_ty IS NOT NULL
                 AND price_ty IS NOT NULL
                 AND price_ty < price_first_ty * 0.99
                THEN ROUND((price_first_ty - price_ty) / price_first_ty * 100, 2)
                ELSE NULL END
        WHERE duplicate_of_id IS NOT NULL
          AND price_dropped = 1
    """)
    conn.execute("UPDATE listings SET possibly_duplicate=0, duplicate_of_id=NULL")

    rows = conn.execute("""
        SELECT id, source, source_id, url, title, area, ward,
               property_type, area_m2, price_ty, crawled_at, posted_at,
               frontage_m, depth_m, contact_phone, has_so, description
        FROM listings
        WHERE probably_sold = 0
        ORDER BY crawled_at ASC
    """).fetchall()

    listings = [dict(r) for r in rows]
    n = len(listings)
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

    from collections import defaultdict

    buckets = defaultdict(list)
    for i, listing in enumerate(listings):
        ward = (listing.get("ward") or "").strip()
        prop_type = listing.get("property_type") or ""
        buckets[(ward, prop_type)].append(i)

    for indices in buckets.values():
        if len(indices) < 2:
            continue
        for idx_i in range(len(indices)):
            for idx_j in range(idx_i + 1, len(indices)):
                i, j = indices[idx_i], indices[idx_j]
                if _is_duplicate(listings[i], listings[j]):
                    union(i, j)

    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)

    dup_groups = {k: v for k, v in groups.items() if len(v) >= 2}
    flagged = 0
    price_drops_detected = 0

    for group_indices in dup_groups.values():
        canonical_idx = min(
            group_indices,
            key=lambda i: (listings[i].get("posted_at") or listings[i].get("crawled_at") or ""),
        )
        canonical = listings[canonical_idx]
        canonical_id = canonical["id"]
        canonical_price = canonical.get("price_ty")

        for idx in group_indices:
            if idx == canonical_idx:
                continue

            dup = listings[idx]
            dup_id = dup["id"]
            conn.execute(
                "UPDATE listings SET possibly_duplicate=1, duplicate_of_id=? WHERE id=?",
                (canonical_id, dup_id),
            )
            flagged += 1

            if _is_reliable_price_drop(canonical, dup):
                dup_price = dup.get("price_ty")
                drop_pct = round((canonical_price - dup_price) / canonical_price * 100, 2)
                conn.execute("""
                    UPDATE listings SET
                        price_dropped  = 1,
                        price_drop_pct = ?,
                        price_first_ty = ?
                    WHERE id = ?
                """, (drop_pct, canonical_price, dup_id))
                price_drops_detected += 1
                logger.info(
                    f"Price drop via repost: listing_id={dup_id} "
                    f"{canonical_price:.2f}->{dup_price:.2f}ty (-{drop_pct}%)"
                )

    stats = {
        "total": n,
        "dup_groups": len(dup_groups),
        "flagged": flagged,
        "unique_lots": n - flagged,
        "price_drops": price_drops_detected,
    }
    logger.info(
        f"Dedup: {n} listings -> {len(dup_groups)} groups -> "
        f"{flagged} flagged -> {n - flagged} unique lots -> "
        f"{price_drops_detected} price drops detected"
    )
    return stats


def get_dedup_stats(conn: sqlite3.Connection) -> dict:
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
        "flagged": flagged,
        "cross_source": cross,
        "same_source": flagged - cross,
        "unique_lots": total - flagged,
    }
