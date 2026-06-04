"""Detect reposts of the same property and reliable repost price drops."""

import logging
import re
import unicodedata
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any, Optional

logger = logging.getLogger(__name__)

SCORE_THRESHOLD = 6

_PRICE_PAT = re.compile(
    r"\d[\d.,]*\s*(?:tỷ|ty|t|triệu|tr|m)",
    re.IGNORECASE | re.UNICODE,
)
_PHONE_PAT = re.compile(r"(?:0|\+84)\d{8,10}")
_ROAD_TOKEN_PAT = re.compile(
    r"\b(?:dx|dj|dh|dl|ql|tl|ni|nj|dk|nk|nl|nh)\s*0*(\d{1,4})\b",
    re.IGNORECASE,
)
_BLOCK_TOKEN_PAT = re.compile(
    r"\b(?:k|l|g|h|ne)\s*0*(\d{1,3})\b",
    re.IGNORECASE,
)
_LOCATION_WORD_PAT = re.compile(
    r"\b(?:tuong|hiep|dinh|chanh|hoa|loi|cuong|my|phu|cat|ben|thoi|tay|dong)\b",
    re.IGNORECASE,
)
_NAMED_LOCATION_PAT = re.compile(
    r"\b(?:le\s+chi\s+dan|nguyen\s+thai\s+binh|phan\s+dang\s+luu|"
    r"huynh\s+thi\s+hieu|ben\s+the|so\s+ga|cho\s+nho|cho\s+phu\s+my)\b",
    re.IGNORECASE,
)


def _strip_noise(text: str) -> str:
    text = _PRICE_PAT.sub(" ", text)
    text = _PHONE_PAT.sub(" ", text)
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip().lower()


def _ascii_fold(text: str) -> str:
    text = (text or "").translate(str.maketrans({
        "đ": "d",
        "Đ": "D",
        "Ð": "D",
        "ð": "d",
    }))
    folded = "".join(
        c for c in unicodedata.normalize("NFD", text)
        if unicodedata.category(c) != "Mn"
    )
    return folded.replace("đ", "d").replace("Đ", "D").lower()


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
    text = _ascii_fold(text)
    tokens = set()
    for m in re.finditer(r"\bquoc\s*lo\s*0*(\d{1,4})\b", text, re.IGNORECASE):
        tokens.add(f"ql{int(m.group(1))}")
    for m in _ROAD_TOKEN_PAT.finditer(text):
        raw = re.sub(r"\s+", "", m.group(0))
        prefix = re.match(r"[a-z]+", raw).group(0)
        tokens.add(f"{prefix}{int(m.group(1))}")
    return tokens


def _road_token_conflict(text1: Optional[str], text2: Optional[str]) -> bool:
    roads1 = _road_tokens(text1)
    roads2 = _road_tokens(text2)
    return bool(roads1 and roads2 and not roads1.intersection(roads2))


def _block_tokens(text: Optional[str]) -> set[str]:
    if not text:
        return set()
    tokens = set()
    for m in _BLOCK_TOKEN_PAT.finditer(text.lower()):
        raw = re.sub(r"\s+", "", m.group(0).lower())
        prefix = re.match(r"[a-z]+", raw).group(0)
        tokens.add(f"{prefix}{int(m.group(1))}")
    return tokens


def _location_words(text: Optional[str]) -> set[str]:
    if not text:
        return set()
    text = _ascii_fold(_strip_noise(text))
    return {m.group(0).lower() for m in _LOCATION_WORD_PAT.finditer(text)}


def _named_location_tokens(text: Optional[str]) -> set[str]:
    if not text:
        return set()
    text = _ascii_fold(_strip_noise(text))
    return {re.sub(r"\s+", " ", m.group(0).lower()) for m in _NAMED_LOCATION_PAT.finditer(text)}


def _house_text_signal(listing: dict) -> bool:
    text = _ascii_fold(_combined_text(listing))
    return bool(re.search(
        r"(^|\n)\s*[^\w\s]*\s*nha\b|"
        r"\bnha\s*(?:tret|lau|cap|moi)\b|"
        r"\btret\s*lau\b|\bgac\s*lung\b|"
        r"\b\d+\s*pn\b|\b\d+\s*wc\b|"
        r"\bphong\s*(?:ngu|khach|tho)\b|"
        r"\bbep\b|\bmay\s*lanh\b|\bsan\s*o\s*to\b|\bsan\s*oto\b",
        text,
        re.IGNORECASE,
    ))


def _land_only_text_signal(listing: dict) -> bool:
    text = _ascii_fold(_combined_text(listing))
    return bool(re.search(
        r"\blo\s+dat\b|\bdat\s+(?:tan|phu|hiep|dinh|chanh|tdm|thu)\b|"
        r"\bdat\s+(?:sach|trong|nen|tho\s*cu)\b|\bxem\s+dat\b",
        text,
        re.IGNORECASE,
    ))


def _property_text_conflict(l1: dict, l2: dict) -> bool:
    h1, h2 = _house_text_signal(l1), _house_text_signal(l2)
    d1, d2 = _land_only_text_signal(l1), _land_only_text_signal(l2)
    return bool((h1 and d2 and not h2) or (h2 and d1 and not h1))


def _tho_cu_m2(listing: dict) -> Optional[float]:
    text = _ascii_fold(_combined_text(listing))
    area = listing.get("area_m2")
    if area and re.search(r"\b(?:tho\s*cu|tc)\s*full\b|\bfull\s*(?:tho\s*cu|tc)\b", text):
        return float(area)

    patterns = [
        r"\b(?:tho\s*cu|tho\s*san|tc)\s*([\d]+(?:[.,]\d+)?)\s*m?",
        r"([\d]+(?:[.,]\d+)?)\s*m(?:2)?\s*(?:tho\s*cu|tc)\b",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if not m:
            continue
        try:
            value = float(m.group(1).replace(",", "."))
        except ValueError:
            continue
        if 5 <= value <= 10000:
            return value
    return None


def _lot_attribute_conflict(l1: dict, l2: dict) -> bool:
    tc1 = _tho_cu_m2(l1)
    tc2 = _tho_cu_m2(l2)
    if tc1 is not None and tc2 is not None:
        if abs(tc1 - tc2) > max(5.0, max(tc1, tc2) * 0.05):
            return True

    text1 = _combined_text(l1)
    text2 = _combined_text(l2)
    if _road_token_conflict(text1, text2):
        return True

    roads1 = _road_tokens(text1)
    roads2 = _road_tokens(text2)
    loc1 = roads1 | _named_location_tokens(text1)
    loc2 = roads2 | _named_location_tokens(text2)
    if loc1 and loc2 and not loc1.intersection(loc2):
        return True

    return False


def _same_tho_cu(l1: dict, l2: dict) -> bool:
    tc1 = _tho_cu_m2(l1)
    tc2 = _tho_cu_m2(l2)
    return bool(tc1 is not None and tc2 is not None and _near(tc1, tc2, 0.01))


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
    return bool(
        pt1 and pt2 and pt1 == pt2
        and w1 and w2 and w1 == w2
        and not _property_text_conflict(l1, l2)
    )


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


def _same_source(l1: dict, l2: dict, source: str) -> bool:
    return (l1.get("source") or "").lower() == source and (l2.get("source") or "").lower() == source


def _facebook_pair(l1: dict, l2: dict) -> bool:
    return _same_source(l1, l2, "facebook")


def _phone_value(listing: dict) -> str:
    return re.sub(r"\D", "", listing.get("contact_phone") or "")


def _same_phone(l1: dict, l2: dict) -> bool:
    p1 = _phone_value(l1)
    p2 = _phone_value(l2)
    return bool(len(p1) >= 9 and len(p2) >= 9 and p1[-9:] == p2[-9:])


def _different_days(l1: dict, l2: dict) -> bool:
    d1 = (l1.get("posted_at") or l1.get("crawled_at") or "")[:10]
    d2 = (l2.get("posted_at") or l2.get("crawled_at") or "")[:10]
    if not d1 or not d2:
        return True
    return d1 != d2


def _location_signal(l1: dict, l2: dict) -> bool:
    text1 = _combined_text(l1)
    text2 = _combined_text(l2)
    if _road_token_conflict(text1, text2):
        return False

    roads1 = _road_tokens(text1)
    roads2 = _road_tokens(text2)
    named1 = _named_location_tokens(text1)
    named2 = _named_location_tokens(text2)
    location1 = roads1 | named1
    location2 = roads2 | named2
    if location1 or location2:
        if not location1.intersection(location2):
            return False
        blocks1 = _block_tokens(text1)
        blocks2 = _block_tokens(text2)
        if blocks1 and blocks2:
            return bool(blocks1.intersection(blocks2))
        return True

    words1 = _location_words(text1)
    words2 = _location_words(text2)
    shared_words = words1.intersection(words2)
    if len(shared_words) >= 3:
        return True

    desc1 = l1.get("description") or text1
    desc2 = l2.get("description") or text2
    return max(_text_similarity(text1, text2), _text_similarity(desc1, desc2)) >= 0.80


def _has_reliable_lot_signature(l1: dict, l2: dict, *, allow_facebook_same_price: bool = False) -> bool:
    """Strong evidence that reposts are the same lot, not just the same broker template."""
    if _same_source_id(l1, l2):
        return True

    if not _facebook_pair(l1, l2):
        return False

    if not _same_required_segment(l1, l2):
        return False

    if _lot_attribute_conflict(l1, l2):
        return False

    area_match = _near(l1.get("area_m2"), l2.get("area_m2"), 0.01)
    if _same_phone(l1, l2) and area_match and _same_tho_cu(l1, l2):
        return True

    has_location = _location_signal(l1, l2)
    if not has_location:
        return False

    front_depth_match = (
        _near(l1.get("frontage_m"), l2.get("frontage_m"), 0.0)
        and _near(l1.get("depth_m"), l2.get("depth_m"), 0.0)
    )
    if front_depth_match:
        return True

    text_sim = _text_similarity(_combined_text(l1), _combined_text(l2))

    if (
        area_match
        and _near(l1.get("frontage_m"), l2.get("frontage_m"), 0.0)
        and _same_tho_cu(l1, l2)
        and text_sim >= 0.80
    ):
        return True

    if _same_phone(l1, l2) and (area_match or text_sim >= 0.70):
        return True

    if area_match:
        if text_sim >= 0.88:
            return True
        if allow_facebook_same_price and _same_source(l1, l2, "facebook"):
            return True

    if has_location and text_sim >= 0.88:
        return True

    return (
        allow_facebook_same_price
        and area_match
        and _same_source(l1, l2, "facebook")
        and has_location
    )


def _drop_pct(older: dict, newer: dict) -> Optional[float]:
    """Calculate price drop % from older (higher) to newer (lower) listing."""
    older_price = older.get("price_ty") or 0
    newer_price = newer.get("price_ty") or 0
    if older_price > 0 and newer_price > 0 and newer_price < older_price * 0.99:
        return round((older_price - newer_price) / older_price * 100, 2)

    older_ppm2 = older.get("price_per_m2") or 0
    newer_ppm2 = newer.get("price_per_m2") or 0
    if older_ppm2 > 0 and newer_ppm2 > 0 and newer_ppm2 < older_ppm2 * 0.99:
        return round((older_ppm2 - newer_ppm2) / older_ppm2 * 100, 2)

    return None


def _is_suspicious_bait(older: dict, newer: dict) -> bool:
    drop_pct = _drop_pct(older, newer)
    return bool(drop_pct is not None and drop_pct > 40.0)


def _is_reliable_price_drop(older: dict, newer: dict) -> bool:
    older_time = older.get("posted_at") or older.get("crawled_at") or ""
    newer_time = newer.get("posted_at") or newer.get("crawled_at") or ""
    drop_pct = _drop_pct(older, newer)

    return bool(
        drop_pct is not None
        and drop_pct <= 40.0
        and newer_time >= older_time
        and _has_reliable_lot_signature(older, newer)
    )


def _is_same_lot_repost(l1: dict, l2: dict) -> bool:
    if not _facebook_pair(l1, l2):
        return False

    same_price = _same_price_for_dedup(l1.get("price_ty"), l2.get("price_ty"))
    allow_facebook_same_price = same_price
    return _has_reliable_lot_signature(
        l1, l2, allow_facebook_same_price=allow_facebook_same_price
    )


def _same_price_for_dedup(a: Optional[float], b: Optional[float]) -> bool:
    if a is None or b is None or a <= 0 or b <= 0:
        return False
    return abs(float(a) - float(b)) / max(float(a), float(b)) <= 0.005


def _candidate_keys(listing: dict) -> set[tuple]:
    ward = (listing.get("ward") or "").strip()
    prop_type = listing.get("property_type") or ""
    base = (ward, prop_type)
    keys = set()

    source = listing.get("source") or ""
    source_id = (listing.get("source_id") or "").strip()
    if source and source_id:
        keys.add(base + ("source_id", source, source_id))

    if source.lower() != "facebook":
        return keys

    text = _combined_text(listing)
    for token in _road_tokens(text):
        keys.add(base + ("road", token))

    area = listing.get("area_m2")
    if area and area > 0:
        keys.add(base + ("area", round(float(area), 1)))
        phone = _phone_value(listing)
        if phone and float(area) >= 300:
            area_bucket = int(round(float(area) / 10.0))
            keys.add(base + ("phone_large_area", phone[-9:], area_bucket))

    frontage = listing.get("frontage_m")
    depth = listing.get("depth_m")
    if frontage and depth and frontage > 0 and depth > 0:
        keys.add(base + ("dims", round(float(frontage), 2), round(float(depth), 2)))

    stripped = _strip_noise(text)
    if len(stripped) >= 40:
        keys.add(base + ("text", " ".join(stripped.split()[:12])))

    return keys


def _repost_score(l1: dict, l2: dict) -> int:
    if not _different_days(l1, l2):
        return 0

    pt1, pt2 = l1.get("property_type"), l2.get("property_type")
    if pt1 and pt2 and pt1 != pt2:
        return 0

    if not _same_ward(l1, l2):
        return 0

    if _property_text_conflict(l1, l2) or _lot_attribute_conflict(l1, l2):
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

    if not _location_signal(l1, l2):
        return 0

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
    if not _facebook_pair(l1, l2):
        return False
    if _same_price_for_dedup(l1.get("price_ty"), l2.get("price_ty")) and not _same_source(l1, l2, "facebook"):
        return False
    if _is_same_lot_repost(l1, l2):
        return True
    return _repost_score(l1, l2) >= SCORE_THRESHOLD


def _has_value(value) -> bool:
    return value not in (None, "", 0, 0.0)


def _row_date(row: dict):
    value = (row.get("posted_at") or row.get("crawled_at") or "")[:10]
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _nearest_field_value(rows: list[dict], target_idx: int, field: str):
    target_dt = _row_date(rows[target_idx])
    candidates = []
    for idx, row in enumerate(rows):
        if idx == target_idx or not _has_value(row.get(field)):
            continue
        row_dt = _row_date(row)
        if target_dt and row_dt:
            distance = abs((target_dt - row_dt).days)
        else:
            distance = abs(target_idx - idx)
        newer_bias = -(row_dt.timestamp() if row_dt else 0)
        candidates.append((distance, newer_bias, idx, row.get(field)))
    if not candidates:
        return None
    candidates.sort()
    return candidates[0][3]


def _inherit_missing_group_values(rows: list[dict]) -> list[dict]:
    hydrated = [dict(row) for row in rows]
    for idx, row in enumerate(hydrated):
        for field in ("price_ty", "area_m2"):
            if not _has_value(row.get(field)):
                inherited = _nearest_field_value(hydrated, idx, field)
                if _has_value(inherited):
                    row[field] = inherited

        if not _has_value(row.get("price_per_m2")):
            inherited_ppm2 = _nearest_field_value(hydrated, idx, "price_per_m2")
            if _has_value(inherited_ppm2):
                row["price_per_m2"] = inherited_ppm2

        if not _has_value(row.get("price_per_m2")) and _has_value(row.get("price_ty")) and _has_value(row.get("area_m2")):
            row["price_per_m2"] = round(float(row["price_ty"]) * 1000 / float(row["area_m2"]), 2)

    return hydrated


def _reconcile_price_first_from_history(conn: Any) -> None:
    """Recover first asking price from the earliest same-URL history snapshot."""
    conn.execute("""
        WITH first_history AS (
            SELECT DISTINCT ON (listing_id)
                   listing_id,
                   price_ty AS first_price
            FROM price_history
            WHERE price_ty IS NOT NULL
              AND price_ty > 0
            ORDER BY listing_id, recorded_at ASC, id ASC
        )
        UPDATE listings l
        SET price_first_ty = fh.first_price
        FROM first_history fh
        WHERE l.id = fh.listing_id
          AND COALESCE(l.probably_sold,0) = 0
          AND fh.first_price IS NOT NULL
          AND fh.first_price > 0
          AND (
                l.price_first_ty IS NULL
             OR ABS(l.price_first_ty - fh.first_price) > 0.000001
          )
    """)
    conn.execute("""
        UPDATE listings
        SET price_dropped = CASE
                WHEN price_first_ty IS NOT NULL
                 AND price_ty IS NOT NULL
                 AND price_ty < price_first_ty * 0.99
                 AND price_ty >= price_first_ty * 0.60
                THEN 1 ELSE 0 END,
            price_drop_pct = CASE
                WHEN price_first_ty IS NOT NULL
                 AND price_ty IS NOT NULL
                 AND price_ty < price_first_ty * 0.99
                 AND price_ty >= price_first_ty * 0.60
                THEN ROUND(((price_first_ty - price_ty) / price_first_ty * 100)::numeric, 2)
                ELSE NULL END,
            suspicious_bait = CASE
                WHEN price_first_ty IS NOT NULL
                 AND price_ty IS NOT NULL
                 AND price_ty < price_first_ty * 0.60
                THEN 1 ELSE 0 END
        WHERE probably_sold = 0
    """)


def flag_duplicates_in_db(conn: Any) -> dict:
    """Flag duplicate reposts and reliable repost price drops."""
    existing_cols = {
        r["column_name"]
        for r in conn.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema='public' AND table_name='listings'
            """
        ).fetchall()
    }
    if "suspicious_bait" not in existing_cols:
        conn.execute("ALTER TABLE listings ADD COLUMN suspicious_bait INTEGER DEFAULT 0")

    _reconcile_price_first_from_history(conn)

    conn.execute("""
        UPDATE listings
        SET price_dropped = CASE
                WHEN price_first_ty IS NOT NULL
                 AND price_ty IS NOT NULL
                 AND price_ty < price_first_ty * 0.99
                 AND price_ty >= price_first_ty * 0.60
                THEN 1 ELSE 0 END,
            price_drop_pct = CASE
                WHEN price_first_ty IS NOT NULL
                 AND price_ty IS NOT NULL
                 AND price_ty < price_first_ty * 0.99
                 AND price_ty >= price_first_ty * 0.60
                THEN ROUND(((price_first_ty - price_ty) / price_first_ty * 100)::numeric, 2)
                ELSE NULL END,
            suspicious_bait = CASE
                WHEN price_first_ty IS NOT NULL
                 AND price_ty IS NOT NULL
                 AND price_ty < price_first_ty * 0.60
                THEN 1 ELSE 0 END
        WHERE probably_sold = 0
    """)
    conn.execute("""
        UPDATE listings
        SET price_dropped = 0,
            price_drop_pct = NULL,
            price_first_ty = price_ty,
            suspicious_bait = 0
        WHERE duplicate_of_id IS NOT NULL
          AND (price_dropped = 1 OR suspicious_bait = 1)
    """)
    conn.execute("UPDATE listings SET possibly_duplicate=0, duplicate_of_id=NULL")

    rows = conn.execute("""
        SELECT id, source, source_id, url, title, area, ward,
               property_type, area_m2, price_ty, price_per_m2, crawled_at, posted_at,
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
        for key in _candidate_keys(listing):
            buckets[key].append(i)

    seen_pairs = set()
    for indices in buckets.values():
        if len(indices) < 2:
            continue
        for idx_i in range(len(indices)):
            for idx_j in range(idx_i + 1, len(indices)):
                i, j = indices[idx_i], indices[idx_j]
                pair = (i, j) if i < j else (j, i)
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                if _is_duplicate(listings[i], listings[j]):
                    union(i, j)

    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)

    dup_groups = {k: v for k, v in groups.items() if len(v) >= 2}
    flagged = 0
    price_drops_detected = 0
    inherited_fields = 0

    for group_indices in dup_groups.values():
        hydrated_rows = _inherit_missing_group_values([listings[i] for i in group_indices])
        for idx, hydrated in zip(group_indices, hydrated_rows):
            original = listings[idx]
            updates = {}
            for field in ("price_ty", "area_m2", "price_per_m2"):
                if not _has_value(original.get(field)) and _has_value(hydrated.get(field)):
                    updates[field] = hydrated[field]
                    original[field] = hydrated[field]
            if updates:
                conn.execute(
                    """
                    UPDATE listings SET
                        price_ty = CASE WHEN price_ty IS NULL OR price_ty = 0 THEN ? ELSE price_ty END,
                        area_m2 = CASE WHEN area_m2 IS NULL OR area_m2 = 0 THEN ? ELSE area_m2 END,
                        price_per_m2 = CASE WHEN price_per_m2 IS NULL OR price_per_m2 = 0 THEN ? ELSE price_per_m2 END
                    WHERE id = ?
                    """,
                    (
                        updates.get("price_ty"),
                        updates.get("area_m2"),
                        updates.get("price_per_m2"),
                        original["id"],
                    ),
                )
                inherited_fields += len(updates)

        canonical_idx = max(
            group_indices,
            key=lambda i: (listings[i].get("posted_at") or listings[i].get("crawled_at") or ""),
        )
        canonical = listings[canonical_idx]
        canonical_id = canonical["id"]
        canonical_price = canonical.get("price_ty")

        # Find the oldest listing in group to determine original price
        oldest_idx = min(
            group_indices,
            key=lambda i: (listings[i].get("posted_at") or listings[i].get("crawled_at") or ""),
        )
        oldest = listings[oldest_idx]
        oldest_price = oldest.get("price_ty")

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

        # Check price drop: compare oldest vs canonical (newest)
        if _is_suspicious_bait(oldest, canonical) and _has_reliable_lot_signature(oldest, canonical):
            conn.execute("""
                UPDATE listings SET
                    price_dropped   = 0,
                    price_drop_pct  = NULL,
                    price_first_ty  = ?,
                    suspicious_bait = 1
                WHERE id = ?
            """, (oldest_price, canonical_id))
            logger.info(
                f"Suspicious bait via repost: listing_id={canonical_id} "
                f"oldest_price={oldest_price} canonical_price={canonical_price}"
            )
        elif _is_reliable_price_drop(oldest, canonical):
            drop_pct = _drop_pct(oldest, canonical)
            conn.execute("""
                UPDATE listings SET
                    price_dropped  = 1,
                    price_drop_pct = ?,
                    price_first_ty = ?,
                    suspicious_bait = 0
                WHERE id = ?
            """, (drop_pct, oldest_price, canonical_id))
            price_drops_detected += 1
            logger.info(
                f"Price drop via repost: listing_id={canonical_id} "
                f"{oldest_price}->{canonical_price}ty (-{drop_pct}%)"
            )

    _apply_dedup_overrides(conn)

    stats = {
        "total": n,
        "dup_groups": len(dup_groups),
        "flagged": flagged,
        "unique_lots": n - flagged,
        "price_drops": price_drops_detected,
        "inherited_fields": inherited_fields,
    }
    logger.info(
        f"Dedup: {n} listings -> {len(dup_groups)} groups -> "
        f"{flagged} flagged -> {n - flagged} unique lots -> "
        f"{price_drops_detected} price drops detected -> "
        f"{inherited_fields} missing fields inherited"
    )
    return stats


def _apply_dedup_overrides(conn: Any) -> None:
    try:
        rows = conn.execute("""
            SELECT action, listing_id, target_listing_id
            FROM dedup_overrides
            WHERE active = 1
            ORDER BY updated_at ASC, id ASC
        """).fetchall()
    except Exception:
        return
    for r in rows:
        action = (r["action"] or "").strip().lower()
        lid = r["listing_id"]
        tid = r["target_listing_id"]
        if not lid or not tid or lid == tid:
            continue
        if action == "merge":
            conn.execute(
                "UPDATE listings SET possibly_duplicate=1, duplicate_of_id=? WHERE id=?",
                (tid, lid),
            )
        elif action == "split":
            conn.execute(
                "UPDATE listings SET possibly_duplicate=0, duplicate_of_id=NULL WHERE id IN (?, ?)",
                (lid, tid),
            )


def get_dedup_stats(conn: Any) -> dict:
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
