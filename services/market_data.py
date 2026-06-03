from datetime import datetime, date
from collections import defaultdict
from contextlib import contextmanager
import re
import unicodedata

from config.settings import LEGAL_IMAGE_EVIDENCE_ENABLED
from db.connection import get_conn
from services.image_assets import resolve_image_url
from services.signal_quality import LATEST_VALUATION_CTE, actionable_signal_sql

# ─────────────────────────────────────────────────────────────────────────────
# Tier-aware masking (server-side). Address + tên đường KHÔNG che (decision 2026-05-14)
# ─────────────────────────────────────────────────────────────────────────────
TIER_ORDER = {"guest": 0, "free": 1, "vip": 2, "admin": 3}
DEFAULT_VISIBLE_SOURCES = ("facebook",)
ADMIN_SOURCE_OPTIONS = ("facebook", "guland", "batdongsan", "muaban")
_PHONE_TEXT_RE = re.compile(
    r"(?<!\d)(?:\+?84|0)(?:[\s.\-()]?\d){9,10}(?!\d)"
)
_CONTACT_CUE_RE = re.compile(
    r"(?:"
    r"☎|📞|"
    r"\b(?:lh|lien\s*he|li[eê]n\s*h[eệ]|hotline|call|zalo|sdt|sđt|dt|đt|"
    r"em|anh|chi|chị|gap|gặp)\b"
    r")",
    re.I,
)
_PHONE_REDACTION = "Liên hệ tư vấn"


def normalize_sources_for_tier(sources=None, tier: str = "guest"):
    if tier != "admin":
        return list(DEFAULT_VISIBLE_SOURCES)

    allowed = set(ADMIN_SOURCE_OPTIONS)
    normalized = []
    for source in sources or []:
        value = (source or "").strip().lower()
        if value and value in allowed and value not in normalized:
            normalized.append(value)
    return normalized or list(DEFAULT_VISIBLE_SOURCES)


def fresh_lock_hours_for(tier: str) -> int:
    """Fresh listings are visible to every tier; kept for older callers."""
    return 0


def _redact_embedded_phones(text):
    if not isinstance(text, str) or not text:
        return text

    out_lines = []
    previous_cta = False
    for line in text.splitlines():
        phone_match = _PHONE_TEXT_RE.search(line)
        if not phone_match:
            out_lines.append(line)
            previous_cta = False
            continue

        prefix = line[:phone_match.start()]
        cue_match = None
        for match in _CONTACT_CUE_RE.finditer(prefix):
            cue_match = match

        if cue_match:
            before = prefix[:cue_match.start()].rstrip(" -–—:,.|")
            replacement = f"{before}\n{_PHONE_REDACTION}" if before else _PHONE_REDACTION
        elif len(line.strip()) <= 140:
            replacement = _PHONE_REDACTION
        else:
            replacement = _PHONE_TEXT_RE.sub(_PHONE_REDACTION, line)

        for part in replacement.splitlines():
            is_cta = part.strip() == _PHONE_REDACTION
            if is_cta and previous_cta:
                continue
            out_lines.append(part)
            previous_cta = is_cta

    return "\n".join(out_lines)


def redact_for_tier(record, tier: str):
    """Return a tier-safe copy of a listing dict.

    - admin: untouched.
    - others: seller/contact/url fields forced to None and embedded phone
      numbers in public listing text are masked.
    """
    if record is None:
        return None
    if tier == "admin":
        return dict(record)
    out = dict(record)
    for key in ("contact_phone", "seller_name", "url", "source_url"):
        if key in out:
            out[key] = None

    for key in ("title", "description"):
        if key in out:
            out[key] = _redact_embedded_phones(out[key])

    return out


def apply_guest_truncation(records, tier: str, limit: int = 12):
    """Deprecated no-op: Guest can browse the full deal feed."""
    return records


def _fresh_lock_sql(alias: str = "l", delay_hours: int = 24) -> str:
    """Compatibility SQL fragment; fresh lock is disabled."""
    return "0 AS is_fresh_locked"

CITY_MAP = {
    "THỦ DẦU MỘT": ["Tân An", "Hiệp An", "Tương Bình Hiệp", "Định Hòa", "Chánh Mỹ", "Phú Mỹ", "Phú Cường", "Phú Hòa", "Phú Lợi", "Hiệp Thành", "Chánh Nghĩa", "Phú Tân", "Hòa Phú"],
    "BẾN CÁT": ["Phú An", "An Tây", "An Điền", "Thới Hòa", "Mỹ Phước", "Mỹ Phước 1", "Mỹ Phước 2", "Mỹ Phước 3", "Mỹ Phước 4", "Chánh Phú Hòa", "Tân Định", "Hòa Lợi"],
    "THUẬN AN": ["An Phú", "An Thạnh", "Bình Chuẩn", "Bình Hòa", "Bình Nhâm", "Hưng Định", "Lái Thiêu", "Thuận Giao", "Vĩnh Phú", "An Sơn"],
    "DĨ AN": ["An Bình", "Bình An", "Bình Thắng", "Dĩ An", "Đông Hòa", "Tân Bình", "Tân Đông Hiệp"],
    "TÂN UYÊN": ["Hội Nghĩa", "Khánh Bình", "Phú Chánh", "Tân Hiệp", "Tân Phước Khánh", "Tân Vĩnh Hiệp", "Thạnh Hội", "Thạnh Phước", "Uyên Hưng", "Vĩnh Tân"]
}

def get_city_for_ward(ward: str) -> str:
    for city, wards in CITY_MAP.items():
        if ward in wards:
            return city
    return "Khác"

def _days_ago(crawled_at: str) -> int:
    try:
        if crawled_at:
            d = date.fromisoformat(crawled_at[:10])
            return (date.today() - d).days
        return None
    except Exception:
        return None


_VIET_SEARCH_FROM = (
    "áàảãạăắằẳẵặâấầẩẫậ"
    "đ"
    "éèẻẽẹêếềểễệ"
    "íìỉĩị"
    "óòỏõọôốồổỗộơớờởỡợ"
    "úùủũụưứừửữự"
    "ýỳỷỹỵ"
)
_VIET_SEARCH_TO = (
    "aaaaaaaaaaaaaaaaa"
    "d"
    "eeeeeeeeeee"
    "iiiii"
    "ooooooooooooooooo"
    "uuuuuuuuuuu"
    "yyyyy"
)


def normalize_search_keyword(value) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    return text[:80]


def _search_terms(keyword):
    folded = _ascii_fold(normalize_search_keyword(keyword))
    return [t for t in re.split(r"\s+", folded) if t][:6]


def _search_text_expr(prefix=""):
    col = lambda name: f"{prefix}{name}" if prefix else name
    parts = [
        col("title"),
        col("description"),
        col("ward"),
        col("road_type"),
        col("property_type"),
        col("source"),
        col("url"),
    ]
    combined = " || ' ' || ".join(f"COALESCE({part}, '')" for part in parts)
    return f"translate(LOWER({combined}), '{_VIET_SEARCH_FROM}', '{_VIET_SEARCH_TO}')"


def keyword_search_filter(keyword, prefix=""):
    terms = _search_terms(keyword)
    if not terms:
        return [], []
    expr = _search_text_expr(prefix)
    clauses = [f"{expr} LIKE ?" for _ in terms]
    params = [f"%{term}%" for term in terms]
    return clauses, params


def _build_filters(sources=None, wards=None, prop_types=None, only_drops=False, prefix="", area_min=0, area_max=0, price_min=0, price_max=0, area_ranges=None, price_ranges=None, keyword=""):
    if not sources:
        sources = list(DEFAULT_VISIBLE_SOURCES)

    # Common filters. Normal views hide duplicates; drop-only views show reliable
    # repost drops even when the lower-price repost is marked duplicate.
    col = lambda name: f"{prefix}{name}" if prefix else name
    where_parts = [
        f"{col('probably_sold')} = 0",
        f"COALESCE({col('is_blacklisted')},0)=0",
        f"COALESCE({col('review_hidden')},0)=0",
    ]
    if only_drops:
        where_parts.append(f"{col('price_dropped')} = 1")
    else:
        where_parts.append(f"{col('possibly_duplicate')} = 0")
    params = []

    if wards:
        where_parts.append(f"{col('ward')} IN ({','.join(['?']*len(wards))})")
        params.extend(wards)

    if sources:
        where_parts.append(f"{col('source')} IN ({','.join(['?']*len(sources))})")
        params.extend(sources)

    if prop_types:
        where_parts.append(f"{col('property_type')} IN ({','.join(['?']*len(prop_types))})")
        params.extend(prop_types)

    range_clauses, range_params = _range_filters(
        area_min,
        area_max,
        price_min,
        price_max,
        prefix,
        area_ranges=area_ranges,
        price_ranges=price_ranges,
    )
    where_parts.extend(range_clauses)
    params.extend(range_params)
    search_clauses, search_params = keyword_search_filter(keyword, prefix)
    where_parts.extend(search_clauses)
    params.extend(search_params)

    return " AND ".join(where_parts), params


def _normalize_ranges(ranges):
    normalized = []
    for item in ranges or []:
        if isinstance(item, dict):
            raw_min, raw_max = item.get("min"), item.get("max")
        else:
            try:
                raw_min, raw_max = item
            except (TypeError, ValueError):
                continue
        try:
            low = float(raw_min) if raw_min not in (None, "") else 0
            high = float(raw_max) if raw_max not in (None, "") else 0
        except (TypeError, ValueError):
            continue
        if low <= 0 and high <= 0:
            continue
        if low > 0 and high > 0 and low > high:
            low, high = high, low
        normalized.append((low, high))
    return normalized


def _append_range_group(clauses, params, column, ranges):
    range_parts = []
    for low, high in _normalize_ranges(ranges):
        if low > 0 and high > 0:
            range_parts.append(f"({column} >= ? AND {column} <= ?)")
            params.extend([low, high])
        elif low > 0:
            range_parts.append(f"{column} >= ?")
            params.append(low)
        elif high > 0:
            range_parts.append(f"{column} <= ?")
            params.append(high)
    if range_parts:
        clauses.append("(" + " OR ".join(range_parts) + ")")
        return True
    return False


def _range_filters(area_min=0, area_max=0, price_min=0, price_max=0, prefix="", area_ranges=None, price_ranges=None):
    col = lambda name: f"{prefix}{name}" if prefix else name
    clauses = []
    params = []
    has_area_ranges = _append_range_group(clauses, params, col('area_m2'), area_ranges)
    if not has_area_ranges and area_min and area_min > 0:
        clauses.append(f"{col('area_m2')} >= ?")
        params.append(area_min)
    if not has_area_ranges and area_max and area_max > 0:
        clauses.append(f"{col('area_m2')} <= ?")
        params.append(area_max)
    has_price_ranges = _append_range_group(clauses, params, col('price_ty'), price_ranges)
    if not has_price_ranges and price_min and price_min > 0:
        clauses.append(f"{col('price_ty')} >= ?")
        params.append(price_min)
    if not has_price_ranges and price_max and price_max > 0:
        clauses.append(f"{col('price_ty')} <= ?")
        params.append(price_max)
    return clauses, params


def _mos_filter(mos_min=0):
    mos_condition = ""
    mos_params = []
    if mos_min > 0:
        mos_condition = " AND v.mos_pct >= ?"
        mos_params = [mos_min]
    return mos_condition, mos_params


def _signal_sort_sql(sort_key: str) -> str:
    if LEGAL_IMAGE_EVIDENCE_ENABLED:
        trust_rank = (
            "CASE COALESCE(v.trust_tier, 'candidate_signal') "
            "WHEN 'has_legal_doc' THEN 0 "
            "ELSE 1 END ASC, COALESCE(v.trust_score, 0) DESC"
        )
    else:
        trust_rank = "0"
    sort_map = {
        "newest": "COALESCE(l.posted_at, l.crawled_at) DESC, l.id DESC",
        "price_m2_asc": "v.actual_ppm2 IS NULL, v.actual_ppm2 ASC, l.id DESC",
        "price_asc": "l.price_ty IS NULL, l.price_ty ASC, l.id DESC",
        "mos_desc": "v.mos_pct IS NULL, v.mos_pct DESC, l.id DESC",
        "score_desc": f"{trust_rank}, COALESCE(v.signal_score, 0) DESC, v.mos_pct DESC",
    }
    return sort_map.get(sort_key or "newest", sort_map["newest"])


LEGAL_IMAGE_ORDER_SQL = (
    "CASE WHEN img_type = 'so_hong' THEN 0 ELSE 1 END, img_order, id"
    if LEGAL_IMAGE_EVIDENCE_ENABLED
    else "img_order, id"
)
LEGAL_DOC_IMAGE_SELECT_SQL = (
    """EXISTS (
                   SELECT 1
                   FROM listing_images legal_img
                   WHERE legal_img.listing_id = l.id
                     AND legal_img.img_type = 'so_hong'
               )"""
    if LEGAL_IMAGE_EVIDENCE_ENABLED
    else "0"
)


@contextmanager
def _read_conn(_db_path=None):
    """Reuse the per-thread PostgreSQL connection for hot read models."""
    with get_conn() as conn:
        yield conn


class _ScopedReadConnection:
    def __init__(self, ctx):
        self._ctx = ctx
        self._conn = ctx.__enter__()
        self._closed = False

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def close(self):
        if not self._closed:
            self._ctx.__exit__(None, None, None)
            self._closed = True


def _open_read_conn(db_path=None):
    return _ScopedReadConnection(_read_conn(db_path))


def _primary_images(conn, listing_ids):
    if not listing_ids:
        return {}
    placeholders = ",".join("?" * len(listing_ids))
    rows = conn.execute(f"""
        SELECT listing_id, local_path, img_url
        FROM listing_images
        WHERE listing_id IN ({placeholders})
        ORDER BY listing_id, {LEGAL_IMAGE_ORDER_SQL}
    """, listing_ids).fetchall()
    img_map = {}
    for r in rows:
        if r[0] in img_map:
            continue
        url = resolve_image_url(r[1], r[2], prefer_thumb=True)
        if url:
            img_map[r[0]] = url
    return img_map


def _row_get(r, key, default=None):
    """Safe getter that works for both sqlite3.Row and dict."""
    try:
        val = r[key]
    except (IndexError, KeyError):
        return default
    return default if val is None else val


_NO_SO_RE = re.compile(
    r"\b("
    r"chua\s+co\s+so|chua\s+so|khong\s+co\s+so|khong\s+so|"
    r"vi\s+bang|giay\s+(?:viet\s+)?tay|"
    r"dang\s+lam\s+so|dang\s+cap\s+so|dang\s+ra\s+so|cho\s+so"
    r")\b",
    re.I,
)


def _ascii_fold(text: str) -> str:
    text = (text or "").replace("Đ", "D").replace("đ", "d")
    return "".join(
        c for c in unicodedata.normalize("NFD", text)
        if unicodedata.category(c) != "Mn"
    ).lower()


def _format_has_so(r):
    raw = _row_get(r, "has_so", None)
    if raw is None:
        return True
    if bool(raw):
        return True
    text = " ".join(str(_row_get(r, key, "") or "") for key in ("title", "description", "road_type"))
    return not bool(_NO_SO_RE.search(_ascii_fold(text)))


def _format_price_label(*texts):
    folded = _ascii_fold(" ".join(str(t or "") for t in texts))
    m = re.search(r'\b(\d+)\s*[,\.]\s*x\b\s*(?:ty|ti)\b', folded, re.I)
    if m:
        return f"khoảng {m.group(1)}.x tỷ"
    return None


def _format_signal_row(r, primary_img=None, tier: str = "guest"):
    fair_ppm2 = round(r['fair_ppm2'], 1) if r['fair_ppm2'] else None
    record = {
        "id": r['id'],
        "title": r['title'],
        "mos_pct": round(r['mos_pct'], 1) if r['mos_pct'] else 0,
        "actual_ppm2": round(r['actual_ppm2'], 1) if r['actual_ppm2'] else 0,
        "fair_ppm2": fair_ppm2,
        "area_m2": r['area_m2'],
        "frontage_m": _row_get(r, "frontage_m"),
        "depth_m": _row_get(r, "depth_m"),
        "price_ty": r['price_ty'],
        "price_label": _format_price_label(r['title']),
        "prop_type": r['property_type'],
        "is_hot": bool(r['is_hot']),
        "price_dropped": bool(r['price_dropped']),
        "suspicious_bait": bool(r['suspicious_bait']),
        "drop_pct": r['price_drop_pct'],
        "price_first_ty": r['price_first_ty'],
        "duplicate_of_id": r['duplicate_of_id'],
        "url": r['url'],
        "days_ago": _days_ago(r['posted_at'] or r['crawled_at']),
        "ward": r['ward'],
        "signal_score": r['signal_score'],
        "trust_tier": _row_get(r, "trust_tier", "candidate_signal"),
        "trust_score": _row_get(r, "trust_score", 0),
        "legal_status": _row_get(r, "legal_status", "unverified"),
        "legal_flags": _row_get(r, "legal_flags", "") or "",
        "source_quality_flags": _row_get(r, "source_quality_flags", "") or "",
        "source_quality_recheck": bool(_row_get(r, "source_quality_recheck", 0)),
        "has_legal_doc_image": bool(LEGAL_IMAGE_EVIDENCE_ENABLED and _row_get(r, "has_legal_doc_image", 0)),
        "primary_img": primary_img or "",
        "image_count": int(_row_get(r, "image_count", 0) or 0),
        "source": r['source'],
        "road_tier": r['road_tier'] or 0,
        "has_so": _format_has_so(r),
        "is_fresh_locked": bool(_row_get(r, 'is_fresh_locked', 0)),
    }
    return redact_for_tier(record, tier)


def load_signals(db_path, sources=None, wards=None, prop_types=None, only_drops=False, mos_min=0, sort='newest', page=1, limit=30, area_min=0, area_max=0, price_min=0, price_max=0, tier='guest', delay_hours=None, area_ranges=None, price_ranges=None, keyword=""):
    # Guest tier: ignore "below valuation" (mos_min) and "only price-drops" filters.
    # Guest still sees the full deal feed; original URLs/phones stay redacted.
    if tier == "guest":
        mos_min = 0
        only_drops = False
    conn = _open_read_conn(db_path)
    where_sql, params = _build_filters(
        sources,
        wards,
        prop_types,
        only_drops,
        prefix="l.",
        area_min=area_min,
        area_max=area_max,
        price_min=price_min,
        price_max=price_max,
        area_ranges=area_ranges,
        price_ranges=price_ranges,
        keyword=keyword,
    )
    mos_condition, mos_params = _mos_filter(mos_min)
    signal_condition = actionable_signal_sql("v")
    page = max(int(page or 1), 1)
    limit = min(max(int(limit or 30), 1), 100)
    offset = (page - 1) * limit
    order_sql = _signal_sort_sql(sort)
    lock_hours = delay_hours if delay_hours is not None else fresh_lock_hours_for(tier)
    fresh_flag = _fresh_lock_sql("l", lock_hours) if lock_hours > 0 else "0 AS is_fresh_locked"

    rows = conn.execute(f"""
        WITH {LATEST_VALUATION_CTE}
        SELECT COUNT(*) OVER() AS total_count,
               v.mos_pct, v.actual_ppm2, v.fair_ppm2, v.is_signal,
               l.id, l.title, l.source, l.area_m2, l.frontage_m, l.depth_m, l.price_ty,
               l.property_type, l.is_hot, l.price_dropped, l.price_drop_pct, l.suspicious_bait,
               l.price_first_ty, l.duplicate_of_id,
               l.url, l.crawled_at, l.posted_at, l.ward, l.road_tier, l.has_so,
               COALESCE(v.signal_score, 0) as signal_score,
               COALESCE(v.trust_tier, 'candidate_signal') as trust_tier,
               COALESCE(v.trust_score, 0) as trust_score,
               COALESCE(v.legal_status, 'unverified') as legal_status,
               COALESCE(v.legal_flags, '') as legal_flags,
               COALESCE(v.source_quality_flags, '') AS source_quality_flags,
               COALESCE(v.source_quality_recheck, 0) AS source_quality_recheck,
               {LEGAL_DOC_IMAGE_SELECT_SQL} AS has_legal_doc_image,
               primary_img.local_path AS primary_local_path,
               primary_img.img_url AS primary_img_url,
               COALESCE(img_count.image_count, 0) AS image_count,
               {fresh_flag}
        FROM latest_valuation v
        JOIN listings l ON v.listing_id = l.id
        LEFT JOIN LATERAL (
            SELECT li.local_path, li.img_url
            FROM listing_images li
            WHERE li.listing_id = l.id
            ORDER BY {LEGAL_IMAGE_ORDER_SQL.replace('img_type', 'li.img_type').replace('img_order', 'li.img_order').replace(', id', ', li.id')}
            LIMIT 1
        ) primary_img ON TRUE
        LEFT JOIN LATERAL (
            SELECT CAST(COUNT(*) AS INTEGER) AS image_count
            FROM listing_images li
            WHERE li.listing_id = l.id
        ) img_count ON TRUE
        WHERE {signal_condition} AND {where_sql}{mos_condition}
        ORDER BY {order_sql}
        LIMIT ? OFFSET ?
    """, params + mos_params + [limit, offset]).fetchall()

    conn.close()

    total = int(_row_get(rows[0], "total_count", 0)) if rows else 0
    signals = [
        _format_signal_row(
            r,
            resolve_image_url(
                _row_get(r, "primary_local_path"),
                _row_get(r, "primary_img_url"),
                prefer_thumb=True,
            ),
            tier=tier,
        )
        for r in rows
    ]
    signals = apply_guest_truncation(signals, tier, limit=12)

    return {
        "signals": signals,
        "total": total,
        "page": page,
        "limit": limit,
        "pages": (total + limit - 1) // limit if limit else 1,
        "has_more": page * limit < total,
        "sort": sort or "newest",
        "tier": tier,
    }


def load_data(db_path, sources=None, wards=None, prop_types=None, only_drops=False, trend_period='day', skip_listings=False, include_trend=True, mos_min=0, include_signals=True, area_min=0, area_max=0, price_min=0, price_max=0, tier='guest', delay_hours=0, area_ranges=None, price_ranges=None, keyword=""):
    conn = _open_read_conn(db_path)

    where_sql, params = _build_filters(
        sources,
        wards,
        prop_types,
        only_drops,
        area_min=area_min,
        area_max=area_max,
        price_min=price_min,
        price_max=price_max,
        area_ranges=area_ranges,
        price_ranges=price_ranges,
        keyword=keyword,
    )
    mos_condition, mos_params = _mos_filter(mos_min)
    signal_condition = actionable_signal_sql("v")
    fresh_flag = _fresh_lock_sql("l", delay_hours)

    # 1. Stats
    stats = conn.execute(f"""
        WITH filtered AS (SELECT * FROM listings WHERE {where_sql}),
             {LATEST_VALUATION_CTE}
        SELECT
            (SELECT COUNT(*) FROM filtered) as total,
            (SELECT COUNT(*) FROM filtered l JOIN latest_valuation v ON l.id = v.listing_id WHERE {signal_condition}{mos_condition}) as signals,
            (SELECT COUNT(*) FROM filtered WHERE is_hot = 1) as hot,
            (SELECT COUNT(*) FROM filtered WHERE (
                COALESCE(posted_at, crawled_at) IS NOT NULL
                AND julianday('now') - julianday(substr(COALESCE(posted_at, crawled_at),1,10)) <= 7
            )) as new_recent_days_7,

            (SELECT COUNT(*) FROM filtered WHERE price_dropped = 1) as price_drops

    """, params + mos_params).fetchone()

    sig_rows = []
    if include_signals:
        sig_query = f"""
            WITH {LATEST_VALUATION_CTE}
            SELECT v.mos_pct, v.actual_ppm2, v.fair_ppm2, v.is_signal,
                   l.id, l.title, l.source, l.area_m2, l.frontage_m, l.depth_m, l.price_ty,
                   l.property_type, l.is_hot, l.price_dropped, l.price_drop_pct, l.suspicious_bait,
                   l.price_first_ty, l.duplicate_of_id,
                   l.url, l.crawled_at, l.posted_at, l.ward, l.road_tier, l.has_so,
                   COALESCE(v.signal_score, 0) as signal_score,
                   COALESCE(v.trust_tier, 'candidate_signal') as trust_tier,
                   COALESCE(v.trust_score, 0) as trust_score,
                   COALESCE(v.legal_status, 'unverified') as legal_status,
                   COALESCE(v.legal_flags, '') as legal_flags,
                   COALESCE(v.source_quality_flags, '') AS source_quality_flags,
                   COALESCE(v.source_quality_recheck, 0) AS source_quality_recheck,
                   {fresh_flag}
            FROM latest_valuation v
            JOIN listings l ON v.listing_id = l.id
            WHERE {signal_condition} AND {where_sql}{mos_condition}
            ORDER BY {_signal_sort_sql('score_desc')}
        """
        sig_rows = conn.execute(sig_query, params + mos_params).fetchall()

    # 3. All Listings
    all_rows = []
    if not skip_listings:
        all_query = f"""
            WITH {LATEST_VALUATION_CTE}
            SELECT l.*, v.is_signal, v.mos_pct, v.fair_ppm2, v.signal_score,
                   COALESCE(v.trust_tier, 'candidate_signal') AS trust_tier,
                   COALESCE(v.trust_score, 0) AS trust_score,
                   COALESCE(v.legal_status, 'unverified') AS legal_status,
                   COALESCE(v.legal_flags, '') AS legal_flags,
                   {fresh_flag}
            FROM listings l
            LEFT JOIN latest_valuation v ON l.id = v.listing_id
            WHERE {where_sql}
            ORDER BY l.price_per_m2 ASC
        """
        all_rows = conn.execute(all_query, params).fetchall()

    # 4. Images
    listing_ids = [r['id'] for r in sig_rows]
    if not skip_listings:
        listing_ids.extend([r['id'] for r in all_rows])
    
    listing_ids = list(set(listing_ids))
    img_rows = []
    if listing_ids:
        placeholders = ",".join("?" * len(listing_ids))
        img_rows = conn.execute(f"""
            SELECT listing_id, local_path, img_url
            FROM listing_images
            WHERE listing_id IN ({placeholders})
            ORDER BY listing_id, {LEGAL_IMAGE_ORDER_SQL}
        """, listing_ids).fetchall()
    img_map = defaultdict(list)
    for r in img_rows:
        url = resolve_image_url(r[1], r[2])
        if url:
            img_map[r[0]].append(url)

    # 5. Market Pulse (Median per Type) - filtered
    market = []
    summary_rows = conn.execute(f"""
        SELECT property_type, AVG(price_per_m2) as mean_ppm2, COUNT(*) as n_samples
        FROM listings
        WHERE is_outlier = 0 AND {where_sql}
        GROUP BY property_type
        HAVING COUNT(*) >= 1
    """, params).fetchall()
    type_label = {'dat_nen': 'Đất nền', 'dat_vuon': 'Đất vườn', 'nha_dat': 'Nhà đất', 'nha_tro': 'Nhà trọ', 'chung_cu': 'Chung cư'}
    for s in summary_rows:
        if s['mean_ppm2'] is None:
            continue
        market.append({
            'type': s['property_type'],
            'label': type_label.get(s['property_type'], s['property_type']),
            'median': round(s['mean_ppm2'], 1),
            'n': s['n_samples']
        })

    # 6. Trend (DYNAMIC) — Tuân theo tất cả bộ lọc (Source, Ward, PropType)
    trend_data = {}
    target_wards = wards if wards else ["Tân An", "Hiệp An", "Tương Bình Hiệp", "Định Hòa", "Chánh Mỹ"]
    
    if trend_period == 'month':
        date_fmt = "strftime('%Y-%m', COALESCE(posted_at, crawled_at))"
        prefix = 'M-'
    elif trend_period == 'day':
        date_fmt = "strftime('%Y-%m-%d', COALESCE(posted_at, crawled_at))"
        prefix = 'D-'
    else: # week
        date_fmt = "strftime('%Y-W%W', COALESCE(posted_at, crawled_at))"
        prefix = ''

    trend_query = f"""
        SELECT 
            '{prefix}' || {date_fmt} as time_key,
            ward,
            price_per_m2
        FROM listings
        WHERE {where_sql} 
          AND price_per_m2 IS NOT NULL 
          AND price_per_m2 > 0
          AND is_outlier = 0
        ORDER BY time_key ASC
    """
    
    if include_trend:
        trend_rows = conn.execute(trend_query, params).fetchall()
    else:
        trend_rows = []
    
    # Group by ward -> time_key -> list of prices -> median
    import statistics
    
    grouped_trend = defaultdict(lambda: defaultdict(list))
    for r in trend_rows:
        if r['ward'] in target_wards:
            grouped_trend[r['ward']][r['time_key']].append(r['price_per_m2'])
            
    for w, time_map in grouped_trend.items():
        ward_points = []
        for t_key, prices in sorted(time_map.items()):
            if len(prices) >= 2: # Require at least 2 samples to reduce noise/jumping
                ward_points.append({
                    'week': t_key,
                    'median_ppm2': round(statistics.median(prices), 2)
                })
        if ward_points:
            trend_data[w] = ward_points

    all_wards = [r[0] for r in conn.execute("SELECT DISTINCT ward FROM listings WHERE ward IS NOT NULL").fetchall()]
    all_sources = [r[0] for r in conn.execute("SELECT DISTINCT source FROM listings").fetchall()]
    conn.close()

    # 7. Grouped Wards for UI
    wards_by_city = {city: list(wards) for city, wards in CITY_MAP.items()}

    signals_out = [_format_signal_row(r, (img_map.get(r['id']) or [""])[0], tier=tier) for r in sig_rows]
    signals_out = apply_guest_truncation(signals_out, tier, limit=12)

    all_listings_out = [
        redact_for_tier({
            "id": r['id'], "title": r['title'], "description": r['description'] or "",
            "price_ty": r['price_ty'], "area_m2": r['area_m2'],
            "price_label": _format_price_label(r['title'], r['description']),
            "price_per_m2": round(r['price_per_m2'], 1) if r['price_per_m2'] else None, "prop_type": r['property_type'],
            "ward": r['ward'], "url": r['url'], "is_signal": bool(r['is_signal']), "mos_pct": round(r['mos_pct'], 1) if r['mos_pct'] else 0,
            "fair_ppm2": round(r['fair_ppm2'], 1) if r['fair_ppm2'] else None,
            "days_ago": _days_ago(r['posted_at'] or r['crawled_at']), "is_hot": bool(r['is_hot']), "price_dropped": bool(r['price_dropped']),
            "suspicious_bait": bool(r['suspicious_bait']),
            "drop_pct": r['price_drop_pct'], "price_first_ty": r['price_first_ty'], "duplicate_of_id": r['duplicate_of_id'],
            "source": r['source'], "imgs": img_map.get(r['id'], []),
            "trust_tier": _row_get(r, "trust_tier", "candidate_signal"),
            "trust_score": _row_get(r, "trust_score", 0),
            "legal_status": _row_get(r, "legal_status", "unverified"),
            "legal_flags": _row_get(r, "legal_flags", "") or "",
            "is_fresh_locked": bool(_row_get(r, 'is_fresh_locked', 0)),
        }, tier)
        for r in all_rows
    ]
    all_listings_out = apply_guest_truncation(all_listings_out, tier, limit=12)

    return {
        "stats": dict(stats),
        "signals": signals_out,
        "all_listings": all_listings_out,
        "market": market,
        "trend_data": trend_data,
        "all_wards": all_wards,
        "all_sources": all_sources,
        "wards_by_city": wards_by_city,
        "tier": tier,
    }


def load_counts(db_path, sources=None, wards=None, prop_types=None, only_drops=False, mos_min=0, area_min=0, area_max=0, price_min=0, price_max=0, area_ranges=None, price_ranges=None, keyword=""):
    conn = _open_read_conn(db_path)
    where_sql, params = _build_filters(
        sources,
        wards,
        prop_types,
        only_drops,
        area_min=area_min,
        area_max=area_max,
        price_min=price_min,
        price_max=price_max,
        area_ranges=area_ranges,
        price_ranges=price_ranges,
        keyword=keyword,
    )

    row = conn.execute(f"""
        WITH filtered AS (
            SELECT id, is_hot, posted_at, crawled_at, price_dropped
            FROM listings
            WHERE {where_sql}
        )
        SELECT
            (SELECT COUNT(*) FROM filtered) AS total,
            (SELECT COUNT(*) FROM filtered WHERE is_hot = 1) AS hot,
            (SELECT COUNT(*) FROM filtered WHERE (
                COALESCE(posted_at, crawled_at) IS NOT NULL
                AND julianday('now') - julianday(substr(COALESCE(posted_at, crawled_at),1,10)) <= 7
            )) AS new_recent_days_7,
            (SELECT COUNT(*) FROM filtered WHERE price_dropped = 1) AS price_drops
    """, params).fetchone()
    conn.close()

    return dict(row) if row else {
        "total": 0,
        "hot": 0,
        "new_recent_days_7": 0,
        "price_drops": 0,
    }

def load_trend_data(db_path, sources=None, wards=None, prop_types=None, only_drops=False, trend_period='day', area_min=0, area_max=0, price_min=0, price_max=0, area_ranges=None, price_ranges=None):
    if not sources:
        sources = list(DEFAULT_VISIBLE_SOURCES)

    conn = _open_read_conn(db_path)

    where_parts = ["probably_sold = 0", "COALESCE(is_blacklisted,0)=0", "COALESCE(review_hidden,0)=0"]
    if only_drops:
        where_parts.append("price_dropped = 1")
    else:
        where_parts.append("possibly_duplicate = 0")
    params = []

    if wards:
        where_parts.append(f"ward IN ({','.join(['?']*len(wards))})")
        params.extend(wards)
    if sources:
        where_parts.append(f"source IN ({','.join(['?']*len(sources))})")
        params.extend(sources)
    if prop_types:
        where_parts.append(f"property_type IN ({','.join(['?']*len(prop_types))})")
        params.extend(prop_types)
    range_clauses, range_params = _range_filters(
        area_min,
        area_max,
        price_min,
        price_max,
        area_ranges=area_ranges,
        price_ranges=price_ranges,
    )
    where_parts.extend(range_clauses)
    params.extend(range_params)
    where_sql = " AND ".join(where_parts)
    target_wards = wards if wards else ["Tân An", "Hiệp An", "Tương Bình Hiệp", "Định Hòa", "Chánh Mỹ"]

    if trend_period == 'month':
        date_fmt = "strftime('%Y-%m', COALESCE(posted_at, crawled_at))"
        prefix = 'M-'
    elif trend_period == 'day':
        date_fmt = "strftime('%Y-%m-%d', COALESCE(posted_at, crawled_at))"
        prefix = 'D-'
    else:
        date_fmt = "strftime('%Y-W%W', COALESCE(posted_at, crawled_at))"
        prefix = ''

    trend_rows = conn.execute(f"""
        SELECT
            '{prefix}' || {date_fmt} as time_key,
            ward,
            price_per_m2
        FROM listings
        WHERE {where_sql}
          AND price_per_m2 IS NOT NULL
          AND price_per_m2 > 0
          AND is_outlier = 0
        ORDER BY time_key ASC
    """, params).fetchall()
    conn.close()

    from collections import defaultdict
    import statistics

    grouped_trend = defaultdict(lambda: defaultdict(list))
    for r in trend_rows:
        if r['ward'] in target_wards:
            grouped_trend[r['ward']][r['time_key']].append(r['price_per_m2'])

    trend_data = {}
    for w, time_map in grouped_trend.items():
        ward_points = []
        for t_key, prices in sorted(time_map.items()):
            if len(prices) >= 2:
                ward_points.append({
                    'week': t_key,
                    'median_ppm2': round(statistics.median(prices), 2)
                })
        if ward_points:
            trend_data[w] = ward_points

    return trend_data


def _shift_month(d: date, delta: int) -> date:
    month_idx = d.year * 12 + (d.month - 1) + delta
    return date(month_idx // 12, month_idx % 12 + 1, 1)


def _market_indicator_filters(sources=None, wards=None, prop_types=None, prefix="",
                              area_min=0, area_max=0, price_min=0, price_max=0,
                              area_ranges=None, price_ranges=None):
    if not sources:
        sources = list(DEFAULT_VISIBLE_SOURCES)

    col = lambda name: f"{prefix}{name}" if prefix else name
    where_parts = [
        f"{col('probably_sold')} = 0",
        f"COALESCE({col('is_blacklisted')},0)=0",
        f"COALESCE({col('review_hidden')},0)=0",
    ]
    params = []

    if wards:
        where_parts.append(f"{col('ward')} IN ({','.join(['?']*len(wards))})")
        params.extend(wards)
    if sources:
        where_parts.append(f"{col('source')} IN ({','.join(['?']*len(sources))})")
        params.extend(sources)
    if prop_types:
        where_parts.append(f"{col('property_type')} IN ({','.join(['?']*len(prop_types))})")
        params.extend(prop_types)

    range_clauses, range_params = _range_filters(
        area_min,
        area_max,
        price_min,
        price_max,
        prefix,
        area_ranges=area_ranges,
        price_ranges=price_ranges,
    )
    where_parts.extend(range_clauses)
    params.extend(range_params)
    return " AND ".join(where_parts), params


def _distress_verdict(ratio_pct: float) -> tuple[str, str, str]:
    if ratio_pct >= 35:
        return "danger", "Vùng ép giá mạnh", "Ưu tiên kiểm tra deal, có dư địa trả giá sâu."
    if ratio_pct >= 25:
        return "warning", "Áp lực bán cao", "Đưa vào watchlist và so sánh pháp lý từng lô."
    if ratio_pct >= 10:
        return "watch", "Cần theo dõi", "Chưa vội xuống tiền, chờ thêm tín hiệu giảm."
    return "normal", "Bình thường", "Giữ kỷ luật giá, chưa có áp lực bán diện rộng."


def _supply_verdict(current_count: int, prev_avg: float):
    delta = current_count - prev_avg
    growth_pct = None
    growth_x = None
    if prev_avg > 0:
        growth_x = current_count / prev_avg
        growth_pct = ((current_count - prev_avg) / prev_avg) * 100

    if (prev_avg == 0 and current_count >= 10) or (growth_x is not None and growth_x >= 3) or delta >= 15:
        return "danger", "Nguồn cung bất thường", "Có dấu hiệu bán ồ ạt, nên ép biên an toàn mạnh.", growth_pct, growth_x
    if (prev_avg == 0 and current_count >= 5) or (growth_x is not None and growth_x >= 1.75) or delta >= 5:
        return "warning", "Nguồn cung tăng nhanh", "Theo dõi tin quy hoạch và thanh khoản khu vực.", growth_pct, growth_x
    return "normal", "Nhịp cung ổn định", "Chưa thấy áp lực nguồn cung đột biến.", growth_pct, growth_x


def load_market_indicators(db_path, sources=None, wards=None, prop_types=None,
                           area_min=0, area_max=0, price_min=0, price_max=0,
                           area_ranges=None, price_ranges=None):
    conn = _open_read_conn(db_path)
    where_sql, params = _market_indicator_filters(
        sources=sources,
        wards=wards,
        prop_types=prop_types,
        prefix="l.",
        area_min=area_min,
        area_max=area_max,
        price_min=price_min,
        price_max=price_max,
        area_ranges=area_ranges,
        price_ranges=price_ranges,
    )

    lot_cte = f"""
        WITH filtered AS (
            SELECT
                COALESCE(l.duplicate_of_id, l.id) AS canonical_id,
                l.ward,
                COALESCE(l.price_dropped, 0) AS price_dropped,
                COALESCE(l.suspicious_bait, 0) AS suspicious_bait,
                date(substr(COALESCE(l.posted_at, l.crawled_at), 1, 10)) AS listed_date
            FROM listings l
            WHERE {where_sql}
              AND l.ward IS NOT NULL
              AND TRIM(l.ward) != ''
              AND LOWER(l.ward) != 'unknown'
        ),
        lots AS (
            SELECT
                canonical_id,
                ward,
                MIN(listed_date) AS first_listed_date,
                MAX(CASE WHEN price_dropped = 1 AND suspicious_bait = 0 THEN 1 ELSE 0 END) AS has_price_drop
            FROM filtered
            GROUP BY canonical_id, ward
        )
    """

    distress_rows = conn.execute(f"""
        {lot_cte}
        SELECT
            ward,
            COUNT(*) AS total_count,
            SUM(has_price_drop) AS distress_count
        FROM lots
        GROUP BY ward
        HAVING COUNT(*) > 0
    """, params).fetchall()

    today = date.today()
    current_start = date(today.year, today.month, 1)
    next_start = _shift_month(current_start, 1)
    prev_months = [_shift_month(current_start, -i) for i in (1, 2, 3)]
    prev_keys = [m.strftime("%Y-%m") for m in prev_months]
    window_start = _shift_month(current_start, -3)

    supply_rows = conn.execute(f"""
        {lot_cte}
        SELECT
            ward,
            strftime('%Y-%m', first_listed_date) AS month_key,
            COUNT(*) AS new_count
        FROM lots
        WHERE first_listed_date >= ?
          AND first_listed_date < ?
        GROUP BY ward, month_key
    """, params + [window_start.isoformat(), next_start.isoformat()]).fetchall()
    conn.close()

    distress = []
    for row in distress_rows:
        total = int(row["total_count"] or 0)
        distress_count = int(row["distress_count"] or 0)
        ratio_pct = round((distress_count / total) * 100, 1) if total else 0
        level_key, level, action = _distress_verdict(ratio_pct)
        distress.append({
            "ward": row["ward"],
            "total_count": total,
            "distress_count": distress_count,
            "ratio_pct": ratio_pct,
            "level_key": level_key,
            "level": level,
            "action": action,
        })
    distress.sort(key=lambda x: (x["ratio_pct"], x["distress_count"], x["total_count"]), reverse=True)

    supply_by_ward = defaultdict(lambda: defaultdict(int))
    for row in supply_rows:
        supply_by_ward[row["ward"]][row["month_key"]] = int(row["new_count"] or 0)

    supply = []
    level_rank = {"danger": 3, "warning": 2, "normal": 1}
    for ward, month_counts in supply_by_ward.items():
        current_count = int(month_counts.get(current_start.strftime("%Y-%m"), 0))
        prev_counts = [int(month_counts.get(k, 0)) for k in prev_keys]
        prev_avg = round(sum(prev_counts) / 3, 1)
        level_key, level, action, growth_pct, growth_x = _supply_verdict(current_count, prev_avg)
        supply.append({
            "ward": ward,
            "current_count": current_count,
            "prev_avg": prev_avg,
            "prev_counts": prev_counts,
            "delta": round(current_count - prev_avg, 1),
            "growth_pct": round(growth_pct, 1) if growth_pct is not None else None,
            "growth_x": round(growth_x, 1) if growth_x is not None else None,
            "level_key": level_key,
            "level": level,
            "action": action,
        })
    supply.sort(key=lambda x: (level_rank.get(x["level_key"], 0), x["delta"], x["current_count"]), reverse=True)

    return {
        "distress_ratio": distress[:30],
        "supply_anomaly": supply[:30],
        "summary": {
            "current_month": current_start.strftime("%Y-%m"),
            "previous_months": prev_keys,
            "distress_hotspots": sum(1 for x in distress if x["ratio_pct"] >= 25),
            "supply_hotspots": sum(1 for x in supply if x["level_key"] in ("danger", "warning")),
            "wards_scanned": len({x["ward"] for x in distress} | {x["ward"] for x in supply}),
        }
    }

def load_listing_detail(db_path, listing_id, tier: str = "guest", delay_hours=None):
    conn = _open_read_conn(db_path)
    lock_hours = delay_hours if delay_hours is not None else fresh_lock_hours_for(tier)
    fresh_flag = _fresh_lock_sql("l", lock_hours) if lock_hours > 0 else "0 AS is_fresh_locked"
    listing = conn.execute(f"""
        WITH {LATEST_VALUATION_CTE}
        SELECT l.*, v.is_signal, v.mos_pct, v.fair_ppm2, v.signal_score,
               COALESCE(v.trust_tier, 'candidate_signal') AS trust_tier,
               COALESCE(v.trust_score, 0) AS trust_score,
               COALESCE(v.legal_status, 'unverified') AS legal_status,
               COALESCE(v.legal_flags, '') AS legal_flags,
               lv.status AS legal_verification_status,
               lv.confidence_score AS legal_confidence_score,
               lv.thua_so AS legal_thua_so,
               lv.to_ban_do AS legal_to_ban_do,
               lv.legal_area_m2,
               lv.legal_residential_m2,
               lv.legal_address,
               lv.legal_ward,
               lv.legal_road_text,
               lv.legal_road_code,
               lv.road_match_status,
               lv.conflict_flags AS legal_conflict_flags,
               {fresh_flag}
        FROM listings l
        LEFT JOIN latest_valuation v ON l.id = v.listing_id
        LEFT JOIN legal_verifications lv ON lv.listing_id = l.id
        WHERE l.id = ?
          AND COALESCE(l.is_blacklisted,0)=0
          AND COALESCE(l.review_hidden,0)=0
    """, (listing_id,)).fetchone()
    if not listing:
        return None

    images = [
        url for url in (
            resolve_image_url(r[0], r[1])
            for r in conn.execute(f"""
                SELECT local_path, img_url
                FROM listing_images
                WHERE listing_id = ?
                ORDER BY {LEGAL_IMAGE_ORDER_SQL}
            """, (listing_id,)).fetchall()
        )
        if url
    ]
    history = [{'date': (r['recorded_at'] or '')[:10], 'price_ty': r['price_ty']} for r in conn.execute("SELECT recorded_at, price_ty FROM price_history WHERE listing_id = ? ORDER BY recorded_at ASC", (listing_id,)).fetchall()]
    conn.close()

    listing_dict = dict(listing)
    listing_dict["is_fresh_locked"] = bool(listing_dict.get("is_fresh_locked"))
    listing_dict["has_so"] = _format_has_so(listing_dict)
    listing_dict = redact_for_tier(listing_dict, tier)
    legal_verification = {
        "status": listing_dict.get("legal_verification_status") or listing_dict.get("legal_status") or "unverified",
        "trust_tier": listing_dict.get("trust_tier") or "candidate_signal",
        "trust_score": listing_dict.get("trust_score") or 0,
        "confidence_score": listing_dict.get("legal_confidence_score") or 0,
        "thua_so": listing_dict.get("legal_thua_so") or listing_dict.get("thua_so"),
        "to_ban_do": listing_dict.get("legal_to_ban_do") or listing_dict.get("to_ban_do"),
        "legal_area_m2": listing_dict.get("legal_area_m2"),
        "legal_residential_m2": listing_dict.get("legal_residential_m2"),
        "legal_address": listing_dict.get("legal_address"),
        "legal_ward": listing_dict.get("legal_ward"),
        "legal_road_text": listing_dict.get("legal_road_text"),
        "legal_road_code": listing_dict.get("legal_road_code"),
        "road_match_status": listing_dict.get("road_match_status"),
        "conflict_flags": listing_dict.get("legal_conflict_flags") or listing_dict.get("legal_flags") or "",
    }

    return {
        "listing": listing_dict,
        "legal_verification": legal_verification,
        "images": images,
        "history": history,
        "tier": tier,
    }

def get_base_filters(req):
    active_city = req.args.get("city")
    wards = req.args.getlist("ward[]") or req.args.getlist("ward")
    sources = req.args.getlist("source[]") or req.args.getlist("source")
    prop_types = req.args.getlist("prop_type[]") or req.args.getlist("prop_type")
    if req.args.get("ward_mode") == "none":
        wards = ["__NO_WARD_SELECTED__"]
    only_drops = req.args.get("only_drops") == "1"
    trend_period = req.args.get("trend_period", "day")
    try:
        mos_min = int(req.args.get("mos_min", 0))
    except (ValueError, TypeError):
        mos_min = 0

    tier = "guest"

    # Guest tier cannot use commission-sensitive filters (mos_min, only_drops).
    try:
        from auth.core import current_tier as _current_tier
        tier = _current_tier()
        if tier == "guest":
            mos_min = 0
            only_drops = False
    except Exception:
        pass

    sources = normalize_sources_for_tier(sources, tier)

    if not active_city and wards:
        active_city = get_city_for_ward(wards[0])
    if not active_city:
        active_city = "THỦ DẦU MỘT"

    return active_city, wards, sources, prop_types, only_drops, trend_period, mos_min
