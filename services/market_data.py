from datetime import datetime, date
from collections import defaultdict
from contextlib import contextmanager
import re
import unicodedata

from cleansing.feature_extractor import _NAMED_ROADS, extract_road_width, extract_tho_cu
from config.settings import LEGAL_IMAGE_EVIDENCE_ENABLED
from db.connection import get_conn
from services.image_assets import resolve_image_url
from services.signal_quality import LATEST_VALUATION_CTE, actionable_signal_sql

LATEST_SHADOW_VALUATION_CTE = """
latest_shadow_valuation AS (
    SELECT DISTINCT ON (vsr.listing_id) vsr.*
    FROM valuation_shadow_results vsr
    ORDER BY vsr.listing_id, vsr.computed_at DESC, vsr.id DESC
)
"""

# ─────────────────────────────────────────────────────────────────────────────
# Tier-aware masking (server-side). Address + tên đường KHÔNG che (decision 2026-05-14)
# ─────────────────────────────────────────────────────────────────────────────
TIER_ORDER = {"guest": 0, "free": 1, "vip": 2, "admin": 3}
DEFAULT_VISIBLE_SOURCES = ("facebook",)
ADMIN_SOURCE_OPTIONS = ("facebook", "guland", "batdongsan", "muaban")
DATE_RANGE_OPTIONS = {
    "1w": "-7 days",
    "1m": "-1 months",
    "3m": "-3 months",
    "6m": "-6 months",
    "1y": "-1 years",
    "all": None,
}
DATE_RANGE_ALIASES = {
    "week": "1w",
    "7d": "1w",
    "30d": "1m",
    "month": "1m",
    "90d": "3m",
    "3mo": "3m",
    "6mo": "6m",
    "365d": "1y",
    "year": "1y",
}
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


def normalize_date_range(value: str | None, default: str | None = "3m") -> str | None:
    raw = str(value or default or "").strip().lower()
    if not raw:
        return None
    raw = DATE_RANGE_ALIASES.get(raw, raw)
    return raw if raw in DATE_RANGE_OPTIONS else default


def listing_date_range_filter(date_range: str | None, prefix: str = ""):
    normalized = normalize_date_range(date_range, default=None)
    if not normalized or normalized == "all":
        return [], []
    interval = DATE_RANGE_OPTIONS.get(normalized)
    if not interval:
        return [], []
    col = lambda name: f"{prefix}{name}" if prefix else name
    date_expr = f"COALESCE({col('posted_at')}, {col('crawled_at')})"
    return [
        f"{date_expr} IS NOT NULL",
        f"datetime({date_expr}) >= datetime('now', ?)",
    ], [interval]


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


_GENERIC_SEARCH_WORDS = {
    "duong",
    "gan",
    "khu",
    "lo",
    "nen",
    "dat",
    "nha",
    "mat",
    "tien",
    "phuong",
    "xa",
    "thi",
    "tran",
    "tp",
    "thanh",
    "pho",
}
_ROAD_CODE_RE = re.compile(r"\b(dx|dh|dl|nl)\s*[-./_]?\s*(\d{1,3}[a-z]?)\b")
_MY_PHUOC_RE = re.compile(r"\bmy\s+phuoc\s+([1-4])\b")
_MY_PHUOC_SHORT_RE = re.compile(r"\bmp\s*[-./_]?\s*([1-4])\b")
_AREA_CODE_RE = re.compile(r"\bkhu\s+([a-z]\d?)\b")


def _dedupe_search_tokens(tokens):
    seen = set()
    out = []
    for mode, value in tokens:
        key = (mode, value)
        if value and key not in seen:
            seen.add(key)
            out.append(key)
    return out[:6]


def _search_tokens(keyword):
    folded = _ascii_fold(normalize_search_keyword(keyword))
    folded = re.sub(r"[-./_]+", " ", folded)
    folded = re.sub(r"\s+", " ", folded).strip()
    if not folded:
        return []

    tokens = []
    remainder = folded

    for pattern, repl in (
        (_ROAD_CODE_RE, lambda m: tokens.append(("compact", f"{m.group(1)}{m.group(2)}")) or " "),
        (_MY_PHUOC_RE, lambda m: tokens.append(("phrase", f"my phuoc {m.group(1)}")) or " "),
        (_MY_PHUOC_SHORT_RE, lambda m: tokens.append(("phrase", f"my phuoc {m.group(1)}")) or " "),
        (_AREA_CODE_RE, lambda m: tokens.append(("phrase", f"khu {m.group(1)}")) or " "),
    ):
        remainder = pattern.sub(repl, remainder)

    words = [
        word
        for word in re.split(r"\s+", remainder.strip())
        if word and word not in _GENERIC_SEARCH_WORDS
    ]
    if words:
        tokens.append(("phrase", " ".join(words[:6])))

    return _dedupe_search_tokens(tokens)


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


def _compact_search_text_expr(prefix=""):
    expr = _search_text_expr(prefix)
    for separator in (" ", "-", ".", "/", "_"):
        expr = f"REPLACE({expr}, '{separator}', '')"
    return expr


def keyword_search_filter(keyword, prefix=""):
    tokens = _search_tokens(keyword)
    if not tokens:
        return [], []
    phrase_expr = _search_text_expr(prefix)
    compact_expr = _compact_search_text_expr(prefix)
    clauses = []
    params = []
    for mode, value in tokens:
        if mode == "compact":
            clauses.append(f"{compact_expr} LIKE ?")
        else:
            clauses.append(f"{phrase_expr} LIKE ?")
        params.append(f"%{value}%")
    return clauses, params


def group_price_drop_filter_sql(prefix=""):
    col = lambda name: f"{prefix}{name}" if prefix else name
    return f"""(
        {_valid_price_drop_sql(prefix)}
        OR {col('id')} IN (
            SELECT drop_child.duplicate_of_id
            FROM listings drop_child
            JOIN listings drop_parent ON drop_parent.id = drop_child.duplicate_of_id
            WHERE drop_child.duplicate_of_id IS NOT NULL
              AND COALESCE(drop_child.probably_sold,0)=0
              AND COALESCE(drop_child.is_blacklisted,0)=0
              AND COALESCE(drop_child.review_hidden,0)=0
              AND drop_child.price_ty IS NOT NULL
              AND drop_parent.price_ty IS NOT NULL
              AND drop_child.price_ty > drop_parent.price_ty * 1.01
              AND drop_parent.price_ty >= drop_child.price_ty * 0.60
        )
    )"""


def _valid_price_drop_sql(prefix=""):
    col = lambda name: f"{prefix}{name}" if prefix else name
    return f"""(
        COALESCE({col('price_dropped')},0)=1
        AND {col('price_first_ty')} IS NOT NULL
        AND {col('price_ty')} IS NOT NULL
        AND {col('price_ty')} < {col('price_first_ty')} * 0.99
        AND {col('price_ty')} >= {col('price_first_ty')} * 0.60
    )"""


def related_price_drop_lateral_sql(alias="l", lateral_alias="related_drop"):
    return f"""
        LEFT JOIN LATERAL (
            SELECT MAX(drop_child.price_ty) AS first_price
            FROM listings drop_child
            WHERE drop_child.duplicate_of_id = {alias}.id
              AND COALESCE(drop_child.probably_sold,0)=0
              AND COALESCE(drop_child.is_blacklisted,0)=0
              AND COALESCE(drop_child.review_hidden,0)=0
              AND drop_child.price_ty IS NOT NULL
              AND {alias}.price_ty IS NOT NULL
              AND drop_child.price_ty > {alias}.price_ty * 1.01
              AND {alias}.price_ty >= drop_child.price_ty * 0.60
        ) {lateral_alias} ON TRUE
    """


def effective_price_drop_select_sql(alias="l", lateral_alias="related_drop"):
    first_price = f"{lateral_alias}.first_price"
    valid_raw_drop = _valid_price_drop_sql(f"{alias}.")
    return f"""
               CASE
                   WHEN {valid_raw_drop} OR {first_price} IS NOT NULL
                   THEN 1 ELSE 0
               END AS price_dropped,
               CASE
                   WHEN {valid_raw_drop} THEN {alias}.price_drop_pct
                   WHEN {first_price} IS NOT NULL
                   THEN ROUND((({first_price} - {alias}.price_ty) / {first_price} * 100)::numeric, 2)
                   ELSE NULL
               END AS price_drop_pct,
               CASE
                   WHEN {first_price} IS NOT NULL THEN {first_price}
                   ELSE {alias}.price_first_ty
               END AS price_first_ty"""


def _build_filters(sources=None, wards=None, prop_types=None, only_drops=False, prefix="", area_min=0, area_max=0, price_min=0, price_max=0, area_ranges=None, price_ranges=None, keyword="", date_range=None):
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
        where_parts.append(group_price_drop_filter_sql(prefix))
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
    date_clauses, date_params = listing_date_range_filter(date_range, prefix)
    where_parts.extend(date_clauses)
    params.extend(date_params)

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


def _display_fair_sql(old_alias="v", new_alias="sv") -> str:
    return f"""
        CASE
            WHEN {old_alias}.fair_ppm2 IS NOT NULL
             AND {new_alias}.fair_ppm2 IS NOT NULL
             AND {old_alias}.fair_ppm2 > 0
             AND {new_alias}.fair_ppm2 > 0
                THEN LEAST({old_alias}.fair_ppm2, {new_alias}.fair_ppm2)
            WHEN {new_alias}.fair_ppm2 IS NOT NULL AND {new_alias}.fair_ppm2 > 0
                THEN {new_alias}.fair_ppm2
            ELSE {old_alias}.fair_ppm2
        END
    """


def _display_mos_sql(old_alias="v", new_alias="sv", actual_expr="COALESCE(v.actual_ppm2, sv.actual_ppm2)") -> str:
    fair_expr = _display_fair_sql(old_alias, new_alias)
    return f"""
        CASE
            WHEN ({fair_expr}) IS NOT NULL AND ({fair_expr}) > 0
                THEN ((({fair_expr}) - ({actual_expr})) / ({fair_expr})) * 100.0
            ELSE COALESCE({old_alias}.mos_pct, {new_alias}.mos_pct, 0)
        END
    """


def _conservative_signal_sql(display_mos_expr: str, mos_min: float, old_alias="v", new_alias="sv") -> str:
    legacy_signal_condition = actionable_signal_sql(old_alias)
    shadow_signal_condition = actionable_signal_sql(new_alias)
    return f"""
        ({legacy_signal_condition})
        AND ({shadow_signal_condition})
        AND ({display_mos_expr}) >= {float(mos_min)}
    """


def _signal_sort_sql(sort_key: str) -> str:
    if LEGAL_IMAGE_EVIDENCE_ENABLED:
        trust_rank = (
            "CASE COALESCE(v.trust_tier, 'candidate_signal') "
            "WHEN 'has_legal_doc' THEN 0 "
            "ELSE 1 END ASC, COALESCE(v.trust_score, 0) DESC"
        )
    else:
        trust_rank = ""
    score_sort_parts = [
        part
        for part in (
            trust_rank,
            "COALESCE(v.signal_score, 0) DESC",
            "v.mos_pct DESC",
            "l.id DESC",
        )
        if part
    ]
    sort_map = {
        "newest": "COALESCE(l.posted_at, l.crawled_at) DESC, l.id DESC",
        "price_m2_asc": "v.actual_ppm2 IS NULL, v.actual_ppm2 ASC, l.id DESC",
        "price_asc": "l.price_ty IS NULL, l.price_ty ASC, l.id DESC",
        "mos_desc": "v.mos_pct IS NULL, v.mos_pct DESC, l.id DESC",
        "score_desc": ", ".join(score_sort_parts),
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
    fuzzy_price_suffix = r'(?=\s*(?:tr|trieu|lh|lien|alo|zalo)\b|[^a-z0-9]|$)'
    m = re.search(
        rf'\b(\d+)\s*(?:t|ty|ti)\s*(\d{{1,3}})\s*[x*]+\s*(?:tr|trieu)?{fuzzy_price_suffix}',
        folded,
        re.I,
    )
    if m:
        ty = float(m.group(1).replace(',', '.'))
        rest = float(m.group(2))
        if rest >= 100:
            value = round(ty + rest / 1000, 4)
        elif rest >= 10:
            value = round(ty + rest / 100, 4)
        else:
            value = round(ty + rest / 10, 4)
        label = f"{value:.3f}".rstrip("0").rstrip(".")
        return f"~{label} tỷ"
    if re.search(rf'\b\d+\s*(?:t|ty|ti)\s*[x*]+\s*(?:tr|trieu)?{fuzzy_price_suffix}', folded, re.I):
        return None
    if re.search(r'\b\d+\s*[,\.]\s*x\b\s*(?:ty|ti)\b', folded, re.I):
        return None
    m = re.search(r'\b(\d+)\s*[,\.]\s*x\b\s*(?:ty|ti)\b', folded, re.I)
    if m:
        return f"khoảng {m.group(1)}.x tỷ"
    return None


PROPERTY_TYPE_LABELS = {
    "dat_nen": "Đất nền",
    "dat_vuon": "Đất vườn",
    "nha_dat": "Nhà đất",
    "nha_tro": "Nhà trọ",
    "chung_cu": "Chung cư",
    "nha_o_xa_hoi": "Nhà ở xã hội",
}

ROAD_TIER_LABELS = {
    1: "Mặt tiền",
    2: "Đường nhựa",
    3: "Hẻm xe hơi",
    4: "Hẻm xe máy",
    5: "Hẻm xe máy",
}

ROAD_TYPE_LABELS = {
    "duong_nhua": "Đường nhựa",
    "be_tong": "Bê tông",
    "duong_dat": "Đường đất",
    "hem_xe_hoi": "Hẻm xe hơi",
    "hem_xe_may": "Hẻm xe máy",
    "hem_ba_gac": "Hẻm ba gác",
}

_ROAD_LABEL_CODE_RE = re.compile(
    r"\b(?:dx|dh|dl|db|nl|ng|ni|na|nb|dc)\s*[-./]?\s*\d{1,3}[a-z]?\b",
    re.I,
)
_ROAD_WIDTH_FALLBACK_RE = re.compile(
    r"\b(?:duong|hem|ngo|lo|mat\s*tien|mt|oto|o\s*to|xe\s*hoi)"
    r"[^,.;\n]{0,28}?(\d+(?:[,.]\d+)?)\s*m\b",
    re.I,
)


def _as_float(value):
    if value is None or value == "":
        return None
    try:
        n = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def _format_metric(value, decimals=1):
    n = _as_float(value)
    if n is None:
        return None
    if abs(n - round(n)) < 0.05:
        return str(int(round(n)))
    return f"{n:.{decimals}f}".rstrip("0").rstrip(".")


def _listing_badge_text(r):
    parts = []
    for key in ("title", "description", "legal_road_text", "legal_road_code"):
        val = _row_get(r, key, "")
        if val:
            parts.append(str(val))
    return "\n".join(parts)


def _infer_road_width_m(r, text):
    explicit = _as_float(_row_get(r, "road_width_m"))
    if explicit:
        return explicit
    folded = _ascii_fold(text or "")
    distance_context = re.search(
        r"\b(?:cach|gan|vao)\s+(?:duong|hem|ngo|lo|mat\s*tien)?[^,.;\n]{0,42}?\d+(?:[,.]\d+)?\s*m\b",
        folded,
        re.I,
    )
    inferred = extract_road_width(text or "")
    if inferred and not (distance_context and float(inferred) >= 20):
        return float(inferred)
    for m in _ROAD_WIDTH_FALLBACK_RE.finditer(folded):
        before = folded[max(0, m.start() - 18):m.start()]
        match_text = m.group(0)
        if re.search(r"\b(?:cach|gan|vao)\s*$", before, re.I) or re.search(r"\bvao\s+\d+(?:[,.]\d+)?\s*m\b", match_text, re.I):
            continue
        value = _as_float(m.group(1))
        if value and 2 <= value <= 60:
            return value
    return None


def _infer_tho_cu_m2(r, text):
    explicit = _as_float(_row_get(r, "tho_cu_m2"))
    area = _as_float(_row_get(r, "area_m2"))
    info = extract_tho_cu(text or "", area)
    value = _as_float(info.get("tho_cu_m2"))
    if explicit:
        if value and area and explicit > area * 1.05:
            if value <= area * 1.05 or abs(value - area) <= max(0.1, area * 0.001):
                return value
        if value and explicit < 10 <= value:
            return value
        return explicit
    if value:
        return value
    return None


def _infer_tho_cu_ratio(r, tho_cu_m2):
    explicit = _as_float(_row_get(r, "tho_cu_ratio"))
    area = _as_float(_row_get(r, "area_m2"))
    if explicit and 0 < explicit <= 1.05:
        if area and tho_cu_m2:
            computed = round(tho_cu_m2 / area, 3)
            if abs(explicit - computed) > 0.01:
                return computed
        return explicit
    if area and tho_cu_m2:
        return round(tho_cu_m2 / area, 3)
    return None


def _road_base_label(r):
    tier = int(_as_float(_row_get(r, "road_tier")) or 0)
    if tier in ROAD_TIER_LABELS:
        return ROAD_TIER_LABELS[tier]
    road_type = str(_row_get(r, "road_type", "") or "")
    return ROAD_TYPE_LABELS.get(road_type) or "Chưa rõ"


def _format_road_label(r, road_width_m):
    base = _road_base_label(r)
    width = _format_metric(road_width_m)
    if width and base != "Chưa rõ":
        return f"{base} {width}m"
    return base


def _title_case_road_name(value):
    words = []
    for part in str(value or "").split():
        lower = part.lower()
        code_match = re.fullmatch(r"([a-z]{1,3})(\d{1,3}[a-z]?)", lower)
        if code_match:
            words.append(f"{code_match.group(1).upper()}{code_match.group(2).upper()}")
        elif lower in {"dx", "dh", "dl", "db", "nl", "ng", "ni", "na", "nb", "dc", "ql"}:
            words.append(lower.upper())
        else:
            words.append(lower[:1].upper() + lower[1:])
    return " ".join(words)


def _find_road_name_match(text):
    folded = _ascii_fold(text or "")
    for road in sorted(_NAMED_ROADS, key=len, reverse=True):
        road_folded = _ascii_fold(road)
        if not road_folded:
            continue
        m = re.search(rf"(?<![a-z0-9]){re.escape(road_folded)}(?![a-z0-9])", folded)
        if m:
            return _title_case_road_name(road), m.start(), m.end()

    m = _ROAD_LABEL_CODE_RE.search(folded)
    if m:
        raw = re.sub(r"[\s\-./]+", "", m.group(0)).upper()
        return raw, m.start(), m.end()
    return None, None, None


def _find_stored_road_name_match(road_name, text):
    road = str(road_name or "").strip()
    if not road:
        return None, None, None
    folded_road = _ascii_fold(road)
    tokens = re.findall(r"[a-z]+|\d+[a-z]?", folded_road)
    if not tokens:
        return _title_case_road_name(road), 0, 0

    separator = r"[\s\-./]*" if len(tokens) == 2 and 1 <= len(tokens[0]) <= 3 else r"[\s\-./]+"
    pattern = rf"(?<![a-z0-9]){separator.join(re.escape(token) for token in tokens)}(?![a-z0-9])"
    m = re.search(pattern, _ascii_fold(text or ""))
    if m:
        return _title_case_road_name(road), m.start(), m.end()
    return _title_case_road_name(road), 0, 0


def _street_prefix(folded, start, end, road_tier):
    tier = int(_as_float(road_tier) or 0)
    if tier in (1, 2):
        return "Mặt tiền"
    return "Hẻm"


def _format_street_label(r, text):
    stored_road_name = _row_get(r, "road_name")
    if stored_road_name:
        road_name, start, end = _find_stored_road_name_match(stored_road_name, text)
    else:
        return None
    folded = _ascii_fold(text or "")
    prefix = _street_prefix(folded, start, end, _row_get(r, "road_tier"))
    return f"{prefix} {road_name}"


def signal_badge_metadata(r):
    """Compact location/property labels for signal cards and detail modals."""
    text = _listing_badge_text(r)
    road_width_m = _infer_road_width_m(r, text)
    tho_cu_m2 = _infer_tho_cu_m2(r, text)
    tho_cu_ratio = _infer_tho_cu_ratio(r, tho_cu_m2)
    tho_cu_display = _format_metric(tho_cu_m2)

    prop_type = _row_get(r, "property_type") or _row_get(r, "prop_type")
    return {
        "property_type_label": PROPERTY_TYPE_LABELS.get(prop_type),
        "road_width_m": road_width_m,
        "road_label": _format_road_label(r, road_width_m),
        "street_label": _format_street_label(r, text),
        "tho_cu_m2": tho_cu_m2,
        "tho_cu_ratio": tho_cu_ratio,
        "tho_cu_label": f"TC {tho_cu_display} m²" if tho_cu_display else None,
    }


def _format_signal_row(r, primary_img=None, tier: str = "guest"):
    fair_ppm2 = round(r['fair_ppm2'], 1) if r['fair_ppm2'] else None
    badge_meta = signal_badge_metadata(r)
    record = {
        "id": r['id'],
        "title": r['title'],
        "mos_pct": round(r['mos_pct'], 1) if r['mos_pct'] else 0,
        "actual_ppm2": round(r['actual_ppm2'], 1) if r['actual_ppm2'] else 0,
        "fair_ppm2": fair_ppm2,
        "fair_ppm2_old": round(_row_get(r, "fair_ppm2_old"), 1) if _row_get(r, "fair_ppm2_old") else None,
        "fair_ppm2_new": round(_row_get(r, "fair_ppm2_new"), 1) if _row_get(r, "fair_ppm2_new") else None,
        "mos_pct_old": round(_row_get(r, "mos_pct_old"), 1) if _row_get(r, "mos_pct_old") else 0,
        "mos_pct_new": round(_row_get(r, "mos_pct_new"), 1) if _row_get(r, "mos_pct_new") else 0,
        "fair_ppm2_display": round(_row_get(r, "fair_ppm2_display"), 1) if _row_get(r, "fair_ppm2_display") else fair_ppm2,
        "mos_pct_display": round(_row_get(r, "mos_pct_display"), 1) if _row_get(r, "mos_pct_display") else (round(r['mos_pct'], 1) if r['mos_pct'] else 0),
        "signal_model": _row_get(r, "signal_model", "legacy") or "legacy",
        "area_m2": r['area_m2'],
        "frontage_m": _row_get(r, "frontage_m"),
        "depth_m": _row_get(r, "depth_m"),
        "price_ty": r['price_ty'],
        "price_label": _format_price_label(r['title'], _row_get(r, "description", "")),
        "prop_type": r['property_type'],
        "prop_type_label": badge_meta["property_type_label"],
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
        "road_type": _row_get(r, "road_type"),
        "road_width_m": badge_meta["road_width_m"],
        "road_label": badge_meta["road_label"],
        "street_label": badge_meta["street_label"],
        "tho_cu_m2": badge_meta["tho_cu_m2"],
        "tho_cu_ratio": badge_meta["tho_cu_ratio"],
        "tho_cu_label": badge_meta["tho_cu_label"],
        "has_so": _format_has_so(r),
        "is_fresh_locked": bool(_row_get(r, 'is_fresh_locked', 0)),
    }
    return redact_for_tier(record, tier)


def load_signals(db_path, sources=None, wards=None, prop_types=None, only_drops=False, mos_min=0, sort='newest', page=1, limit=30, area_min=0, area_max=0, price_min=0, price_max=0, tier='guest', delay_hours=None, area_ranges=None, price_ranges=None, keyword="", include_total=True, date_range=None):
    # Guest tier: ignore "below valuation" (mos_min) and "only price-drops" filters.
    # Guest still sees the full deal feed; original URLs/phones stay redacted.
    if tier == "guest":
        mos_min = 10
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
        date_range=date_range,
    )
    actual_expr = "COALESCE(v.actual_ppm2, sv.actual_ppm2, l.price_per_m2)"
    display_fair_expr = _display_fair_sql("v", "sv")
    display_mos_expr = _display_mos_sql("v", "sv", actual_expr)
    effective_mos_min = float(mos_min if mos_min is not None else 10)
    signal_condition = _conservative_signal_sql(display_mos_expr, effective_mos_min)
    page = max(int(page or 1), 1)
    limit = min(max(int(limit or 30), 1), 100)
    offset = (page - 1) * limit
    query_limit = limit if include_total else limit + 1
    order_sql = _signal_sort_sql(sort)
    if sort == "mos_desc":
        order_sql = f"({display_mos_expr}) DESC, l.id DESC"
    elif sort == "score_desc":
        order_sql = f"GREATEST(COALESCE(v.signal_score,0), COALESCE(sv.signal_score,0)) DESC, ({display_mos_expr}) DESC, l.id DESC"
    lock_hours = delay_hours if delay_hours is not None else fresh_lock_hours_for(tier)
    fresh_flag = _fresh_lock_sql("l", lock_hours) if lock_hours > 0 else "0 AS is_fresh_locked"
    total_select = "COUNT(*) OVER() AS total_count," if include_total else ""

    rows = conn.execute(f"""
        WITH {LATEST_VALUATION_CTE},
             {LATEST_SHADOW_VALUATION_CTE}
        SELECT {total_select}
               ({display_mos_expr}) AS mos_pct,
               {actual_expr} AS actual_ppm2,
               ({display_fair_expr}) AS fair_ppm2,
               CASE WHEN ({signal_condition}) THEN 1 ELSE 0 END AS is_signal,
               v.fair_ppm2 AS fair_ppm2_old,
               sv.fair_ppm2 AS fair_ppm2_new,
               v.mos_pct AS mos_pct_old,
               sv.mos_pct AS mos_pct_new,
               ({display_fair_expr}) AS fair_ppm2_display,
               ({display_mos_expr}) AS mos_pct_display,
               CASE
                   WHEN ({signal_condition}) THEN 'both'
                   ELSE 'legacy'
               END AS signal_model,
               l.id, l.title, l.description, l.source, l.area_m2, l.frontage_m, l.depth_m, l.price_ty,
               l.property_type, l.road_name, l.road_type, l.road_width_m, l.tho_cu_m2, l.tho_cu_ratio, l.is_hot,
               {effective_price_drop_select_sql("l", "related_drop")},
               l.suspicious_bait,
               l.duplicate_of_id,
               l.url, l.crawled_at, l.posted_at, l.ward, l.road_tier, l.has_so,
               GREATEST(COALESCE(v.signal_score, 0), COALESCE(sv.signal_score, 0)) as signal_score,
               COALESCE(v.trust_tier, sv.trust_tier, 'candidate_signal') as trust_tier,
               COALESCE(v.trust_score, sv.trust_score, 0) as trust_score,
               COALESCE(v.legal_status, sv.legal_status, 'unverified') as legal_status,
               COALESCE(v.legal_flags, sv.legal_flags, '') as legal_flags,
               COALESCE(v.source_quality_flags, sv.source_quality_flags, '') AS source_quality_flags,
               COALESCE(v.source_quality_recheck, sv.source_quality_recheck, 0) AS source_quality_recheck,
               {LEGAL_DOC_IMAGE_SELECT_SQL} AS has_legal_doc_image,
               primary_img.local_path AS primary_local_path,
               primary_img.img_url AS primary_img_url,
               COALESCE(img_count.image_count, 0) AS image_count,
               {fresh_flag}
        FROM listings l
        LEFT JOIN latest_valuation v ON v.listing_id = l.id
        LEFT JOIN latest_shadow_valuation sv ON sv.listing_id = l.id
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
        {related_price_drop_lateral_sql("l", "related_drop")}
        WHERE ({signal_condition}) AND {where_sql}
        ORDER BY {order_sql}
        LIMIT ? OFFSET ?
    """, params + [query_limit, offset]).fetchall()

    conn.close()

    has_more_without_total = (not include_total) and len(rows) > limit
    if not include_total:
        rows = rows[:limit]
    total = int(_row_get(rows[0], "total_count", 0)) if include_total and rows else 0
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

    payload = {
        "signals": signals,
        "page": page,
        "limit": limit,
        "has_more": has_more_without_total if not include_total else page * limit < total,
        "sort": sort or "newest",
        "tier": tier,
    }
    if include_total:
        payload["total"] = total
        payload["pages"] = (total + limit - 1) // limit if limit else 1
    return payload


def load_data(db_path, sources=None, wards=None, prop_types=None, only_drops=False, trend_period='day', skip_listings=False, include_trend=True, mos_min=0, include_signals=True, area_min=0, area_max=0, price_min=0, price_max=0, tier='guest', delay_hours=0, area_ranges=None, price_ranges=None, keyword="", date_range=None):
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
        date_range=date_range,
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
                   l.id, l.title, l.description, l.source, l.area_m2, l.frontage_m, l.depth_m, l.price_ty,
                   l.property_type, l.road_name, l.road_type, l.road_width_m, l.tho_cu_m2, l.tho_cu_ratio, l.is_hot,
                   {effective_price_drop_select_sql("l", "related_drop")},
                   l.suspicious_bait,
                   l.duplicate_of_id,
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
            {related_price_drop_lateral_sql("l", "related_drop")}
            WHERE {signal_condition} AND {where_sql}{mos_condition}
            ORDER BY {_signal_sort_sql('score_desc')}
        """
        sig_rows = conn.execute(sig_query, params + mos_params).fetchall()

    # 3. All Listings
    all_rows = []
    if not skip_listings:
        all_actual_expr = "COALESCE(v.actual_ppm2, sv.actual_ppm2, l.price_per_m2)"
        all_display_fair_expr = _display_fair_sql("v", "sv")
        all_display_mos_expr = _display_mos_sql("v", "sv", all_actual_expr)
        old_signal_condition = actionable_signal_sql("v")
        new_signal_condition = actionable_signal_sql("sv")
        all_signal_condition = f"({old_signal_condition}) AND ({new_signal_condition})"
        all_query = f"""
            WITH {LATEST_VALUATION_CTE},
                 {LATEST_SHADOW_VALUATION_CTE}
            SELECT l.*,
                   CASE WHEN {all_signal_condition} THEN 1 ELSE 0 END AS is_signal,
                   ({all_display_mos_expr}) AS mos_pct,
                   ({all_display_fair_expr}) AS fair_ppm2,
                   v.fair_ppm2 AS fair_ppm2_old,
                   sv.fair_ppm2 AS fair_ppm2_new,
                   v.mos_pct AS mos_pct_old,
                   sv.mos_pct AS mos_pct_new,
                   ({all_display_fair_expr}) AS fair_ppm2_display,
                   ({all_display_mos_expr}) AS mos_pct_display,
                   GREATEST(COALESCE(v.signal_score,0), COALESCE(sv.signal_score,0)) AS signal_score,
                   COALESCE(v.trust_tier, sv.trust_tier, 'candidate_signal') AS trust_tier,
                   COALESCE(v.trust_score, sv.trust_score, 0) AS trust_score,
                   COALESCE(v.legal_status, sv.legal_status, 'unverified') AS legal_status,
                   COALESCE(v.legal_flags, sv.legal_flags, '') AS legal_flags,
                   {fresh_flag}
            FROM listings l
            LEFT JOIN latest_valuation v ON l.id = v.listing_id
            LEFT JOIN latest_shadow_valuation sv ON l.id = sv.listing_id
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
                    'median_ppm2': round(statistics.median(prices), 2),
                    'sample_count': len(prices)
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
            "fair_ppm2_old": round(_row_get(r, "fair_ppm2_old"), 1) if _row_get(r, "fair_ppm2_old") else None,
            "fair_ppm2_new": round(_row_get(r, "fair_ppm2_new"), 1) if _row_get(r, "fair_ppm2_new") else None,
            "mos_pct_old": round(_row_get(r, "mos_pct_old"), 1) if _row_get(r, "mos_pct_old") else 0,
            "mos_pct_new": round(_row_get(r, "mos_pct_new"), 1) if _row_get(r, "mos_pct_new") else 0,
            "fair_ppm2_display": round(_row_get(r, "fair_ppm2_display"), 1) if _row_get(r, "fair_ppm2_display") else (round(r['fair_ppm2'], 1) if r['fair_ppm2'] else None),
            "mos_pct_display": round(_row_get(r, "mos_pct_display"), 1) if _row_get(r, "mos_pct_display") else (round(r['mos_pct'], 1) if r['mos_pct'] else 0),
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


def load_dashboard_summary(db_path, sources=None, wards=None, prop_types=None, only_drops=False, trend_period='day', include_trend=False, mos_min=0, area_min=0, area_max=0, price_min=0, price_max=0, area_ranges=None, price_ranges=None, keyword="", tier='guest', date_range=None):
    if tier == "guest":
        mos_min = 10
        only_drops = False

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
        date_range=date_range,
    )

    stats_row = conn.execute(f"""
        WITH filtered AS (
            SELECT id, is_hot, posted_at, crawled_at, price_dropped, price_ty, price_first_ty
            FROM listings
            WHERE {where_sql}
        )
        SELECT
            (SELECT COUNT(*) FROM filtered) AS total,
            0 AS signals,
            (SELECT COUNT(*) FROM filtered WHERE is_hot = 1) AS hot,
            (SELECT COUNT(*) FROM filtered WHERE (
                COALESCE(posted_at, crawled_at) IS NOT NULL
                AND julianday('now') - julianday(substr(COALESCE(posted_at, crawled_at),1,10)) <= 7
            )) AS new_recent_days_7,
            (SELECT COUNT(*) FROM filtered WHERE {group_price_drop_filter_sql()}) AS price_drops
    """, params).fetchone()
    stats = dict(stats_row) if stats_row else {
        "total": 0,
        "signals": 0,
        "hot": 0,
        "new_recent_days_7": 0,
        "price_drops": 0,
    }

    signal_where_sql, signal_params = _build_filters(
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
        date_range=date_range,
    )
    actual_expr = "COALESCE(v.actual_ppm2, sv.actual_ppm2, l.price_per_m2)"
    display_mos_expr = _display_mos_sql("v", "sv", actual_expr)
    effective_mos_min = float(mos_min if mos_min is not None else 10)
    signal_condition = _conservative_signal_sql(display_mos_expr, effective_mos_min)
    signal_row = conn.execute(f"""
        WITH {LATEST_VALUATION_CTE},
             {LATEST_SHADOW_VALUATION_CTE}
        SELECT COUNT(*) AS signals
        FROM listings l
        LEFT JOIN latest_valuation v ON l.id = v.listing_id
        LEFT JOIN latest_shadow_valuation sv ON l.id = sv.listing_id
        WHERE ({signal_condition}) AND {signal_where_sql}
    """, signal_params).fetchone()
    stats["signals"] = int(_row_get(signal_row, "signals", 0) or 0)

    market = []
    summary_rows = conn.execute(f"""
        SELECT property_type, AVG(price_per_m2) as mean_ppm2, COUNT(*) as n_samples
        FROM listings
        WHERE is_outlier = 0 AND {where_sql}
        GROUP BY property_type
        HAVING COUNT(*) >= 1
    """, params).fetchall()
    type_label = {'dat_nen': 'Đất nền', 'dat_vuon': 'Đất vườn', 'nha_dat': 'Nhà đất', 'nha_tro': 'Nhà trọ', 'chung_cu': 'Chung cư'}
    for row in summary_rows:
        mean_ppm2 = _row_get(row, "mean_ppm2")
        if mean_ppm2 is None:
            continue
        prop_type = _row_get(row, "property_type")
        market.append({
            "type": prop_type,
            "label": type_label.get(prop_type, prop_type),
            "median": round(mean_ppm2, 1),
            "n": _row_get(row, "n_samples", 0),
        })

    all_wards = [r[0] for r in conn.execute("SELECT DISTINCT ward FROM listings WHERE ward IS NOT NULL").fetchall()]
    all_sources = [r[0] for r in conn.execute("SELECT DISTINCT source FROM listings").fetchall()]
    conn.close()

    trend_data = {}
    if include_trend:
        trend_data = load_trend_data(
            db_path,
            sources=sources,
            wards=wards,
            prop_types=prop_types,
            only_drops=only_drops,
            trend_period=trend_period,
            area_min=area_min,
            area_max=area_max,
            price_min=price_min,
            price_max=price_max,
            area_ranges=area_ranges,
            price_ranges=price_ranges,
            keyword=keyword,
        )

    return {
        "stats": stats,
        "market": market,
        "trend_data": trend_data,
        "all_wards": all_wards,
        "all_sources": all_sources,
        "wards_by_city": {city: list(wards) for city, wards in CITY_MAP.items()},
        "tier": tier,
    }


def load_counts(db_path, sources=None, wards=None, prop_types=None, only_drops=False, mos_min=0, area_min=0, area_max=0, price_min=0, price_max=0, area_ranges=None, price_ranges=None, keyword="", date_range=None):
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
        date_range=date_range,
    )

    row = conn.execute(f"""
        WITH filtered AS (
            SELECT id, is_hot, posted_at, crawled_at,
                   CASE WHEN {group_price_drop_filter_sql()} THEN 1 ELSE 0 END AS price_dropped
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

def load_trend_data(db_path, sources=None, wards=None, prop_types=None, only_drops=False, trend_period='day', area_min=0, area_max=0, price_min=0, price_max=0, area_ranges=None, price_ranges=None, keyword=""):
    if not sources:
        sources = list(DEFAULT_VISIBLE_SOURCES)

    conn = _open_read_conn(db_path)

    where_parts = ["probably_sold = 0", "COALESCE(is_blacklisted,0)=0", "COALESCE(review_hidden,0)=0"]
    if only_drops:
        where_parts.append(group_price_drop_filter_sql())
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
    search_clauses, search_params = keyword_search_filter(keyword)
    where_parts.extend(search_clauses)
    params.extend(search_params)
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
                    'median_ppm2': round(statistics.median(prices), 2),
                    'sample_count': len(prices)
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


def _risk_score_from_indicators(distress_ratio_pct: float, supply_level_key: str, supply_delta: float) -> int:
    distress_component = min(100, max(0, float(distress_ratio_pct or 0)) / 35 * 100)
    supply_base = {
        "danger": 100,
        "warning": 72,
        "watch": 45,
        "normal": 18,
    }.get(supply_level_key or "normal", 18)
    supply_component = max(supply_base, min(100, max(0, float(supply_delta or 0)) * 6))
    return int(round(distress_component * 0.55 + supply_component * 0.45))


def _area_risk_verdict(risk_score: int, median_mos: float, deal_count: int) -> tuple[str, str, str]:
    if risk_score >= 70 and median_mos >= 15 and deal_count > 0:
        return "selloff", "Rẻ vì đang bị xả", "Kiểm tra pháp lý, thanh khoản và lịch sử giảm giá trước khi xuống tiền."
    if risk_score >= 70:
        return "pressure", "Áp lực xả hàng cao", "Theo dõi thêm nguồn cung; chưa nên coi giá rẻ là cơ hội."
    if median_mos >= 20 and deal_count >= 2 and risk_score < 55:
        return "opportunity", "Cơ hội sạch hơn", "Có thể ưu tiên lọc sâu từng deal trong khu này."
    if risk_score >= 45:
        return "watch", "Cần soi kỹ", "Có tín hiệu rẻ nhưng nền cung/giảm giá chưa thật yên tâm."
    return "normal", "Rủi ro thấp", "Giữ kỷ luật giá và đối chiếu từng lô cụ thể."


def _build_area_risk_radar(distress, supply, deal_rows):
    import statistics

    distress_by_ward = {x["ward"]: x for x in distress}
    supply_by_ward = {x["ward"]: x for x in supply}
    deal_stats = defaultdict(lambda: {"total_count": 0, "deal_count": 0, "mos_values": []})

    for row in deal_rows:
        ward = row["ward"]
        if not ward:
            continue
        stats = deal_stats[ward]
        stats["total_count"] += 1
        mos = row["mos_pct"]
        if row["is_signal"] == 1 and mos and mos > 0:
            stats["deal_count"] += 1
            stats["mos_values"].append(float(mos))

    wards = set(distress_by_ward) | set(supply_by_ward) | set(deal_stats)
    radar = []
    for ward in wards:
        distress_row = distress_by_ward.get(ward, {})
        supply_row = supply_by_ward.get(ward, {})
        stats = deal_stats.get(ward, {})
        mos_values = stats.get("mos_values", [])
        median_mos = round(statistics.median(mos_values), 1) if mos_values else 0
        deal_count = int(stats.get("deal_count", 0))
        total_count = int(stats.get("total_count", 0) or distress_row.get("total_count", 0) or 0)
        distress_ratio = float(distress_row.get("ratio_pct", 0) or 0)
        supply_delta = float(supply_row.get("delta", 0) or 0)
        supply_level_key = supply_row.get("level_key", "normal")
        risk_score = _risk_score_from_indicators(distress_ratio, supply_level_key, supply_delta)
        verdict_key, verdict, action = _area_risk_verdict(risk_score, median_mos, deal_count)

        radar.append({
            "ward": ward,
            "risk_score": risk_score,
            "distress_ratio_pct": round(distress_ratio, 1),
            "distress_count": int(distress_row.get("distress_count", 0) or 0),
            "supply_level_key": supply_level_key,
            "supply_delta": round(supply_delta, 1),
            "supply_growth_pct": supply_row.get("growth_pct"),
            "median_mos": median_mos,
            "deal_count": deal_count,
            "total_count": total_count,
            "verdict_key": verdict_key,
            "verdict": verdict,
            "action": action,
        })

    radar.sort(key=lambda x: (x["risk_score"], x["deal_count"], x["median_mos"]), reverse=True)
    return radar[:12]


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

    signal_condition = actionable_signal_sql("v")
    deal_rows = conn.execute(f"""
        WITH {LATEST_VALUATION_CTE},
        risk_deal_rows AS (
            SELECT
                l.ward,
                v.mos_pct,
                CASE WHEN {signal_condition} THEN 1 ELSE 0 END AS is_signal
            FROM listings l
            LEFT JOIN latest_valuation v ON l.id = v.listing_id
            WHERE {where_sql}
              AND l.ward IS NOT NULL
              AND TRIM(l.ward) != ''
              AND LOWER(l.ward) != 'unknown'
              AND COALESCE(l.price_per_m2, 0) > 0
              AND COALESCE(l.price_per_m2, 0) < 1000
              AND COALESCE(v.is_outlier, 0) = 0
        )
        SELECT ward, mos_pct, is_signal
        FROM risk_deal_rows
    """, params).fetchall()
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
    area_risk_radar = _build_area_risk_radar(distress, supply, deal_rows)

    return {
        "distress_ratio": distress[:30],
        "supply_anomaly": supply[:30],
        "area_risk_radar": area_risk_radar,
        "summary": {
            "current_month": current_start.strftime("%Y-%m"),
            "previous_months": prev_keys,
            "distress_hotspots": sum(1 for x in distress if x["ratio_pct"] >= 25),
            "supply_hotspots": sum(1 for x in supply if x["level_key"] in ("danger", "warning")),
            "area_risk_hotspots": sum(1 for x in area_risk_radar if x["risk_score"] >= 70),
            "wards_scanned": len({x["ward"] for x in distress} | {x["ward"] for x in supply}),
        }
    }

def load_listing_detail(db_path, listing_id, tier: str = "guest", delay_hours=None):
    conn = _open_read_conn(db_path)
    lock_hours = delay_hours if delay_hours is not None else fresh_lock_hours_for(tier)
    fresh_flag = _fresh_lock_sql("l", lock_hours) if lock_hours > 0 else "0 AS is_fresh_locked"
    actual_expr = "COALESCE(v.actual_ppm2, sv.actual_ppm2, l.price_per_m2)"
    display_fair_expr = _display_fair_sql("v", "sv")
    display_mos_expr = _display_mos_sql("v", "sv", actual_expr)
    listing = conn.execute(f"""
        WITH {LATEST_VALUATION_CTE},
             {LATEST_SHADOW_VALUATION_CTE}
        SELECT l.*,
               CASE WHEN COALESCE(v.is_signal,0)=1 OR COALESCE(sv.is_signal,0)=1 THEN 1 ELSE 0 END AS is_signal,
               ({display_mos_expr}) AS mos_pct,
               ({display_fair_expr}) AS fair_ppm2,
               v.fair_ppm2 AS fair_ppm2_old,
               sv.fair_ppm2 AS fair_ppm2_new,
               v.mos_pct AS mos_pct_old,
               sv.mos_pct AS mos_pct_new,
               ({display_fair_expr}) AS fair_ppm2_display,
               ({display_mos_expr}) AS mos_pct_display,
               CASE
                   WHEN COALESCE(v.is_signal,0)=1 AND COALESCE(sv.is_signal,0)=1 THEN 'both'
                   WHEN COALESCE(sv.is_signal,0)=1 THEN 'new'
                   ELSE 'legacy'
               END AS signal_model,
               GREATEST(COALESCE(v.signal_score,0), COALESCE(sv.signal_score,0)) AS signal_score,
               COALESCE(v.trust_tier, sv.trust_tier, 'candidate_signal') AS trust_tier,
               COALESCE(v.trust_score, sv.trust_score, 0) AS trust_score,
               COALESCE(v.legal_status, sv.legal_status, 'unverified') AS legal_status,
               COALESCE(v.legal_flags, sv.legal_flags, '') AS legal_flags,
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
        LEFT JOIN latest_shadow_valuation sv ON l.id = sv.listing_id
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
    listing_dict.update(signal_badge_metadata(listing_dict))
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
        mos_min = int(req.args.get("mos_min", 10))
    except (ValueError, TypeError):
        mos_min = 10

    tier = "guest"

    # Guest tier cannot use commission-sensitive filters (mos_min, only_drops).
    try:
        from auth.core import current_tier as _current_tier
        tier = _current_tier()
        if tier == "guest":
            mos_min = 10
            only_drops = False
    except Exception:
        pass

    sources = normalize_sources_for_tier(sources, tier)

    if not active_city and wards:
        active_city = get_city_for_ward(wards[0])
    if not active_city:
        active_city = "THỦ DẦU MỘT"

    return active_city, wards, sources, prop_types, only_drops, trend_period, mos_min
