from datetime import datetime, date, timezone
from collections import defaultdict
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import os
import re
import unicodedata

from cleansing.feature_extractor import _NAMED_ROADS, extract_road_width, extract_tho_cu
from config.property_types import PROPERTY_TYPE_LABELS, normalize_property_types
from config.settings import LEGAL_IMAGE_EVIDENCE_ENABLED
from db.connection import get_conn
from db.guland_publishers import (
    publisher_feed_join_sql,
    publisher_sort_rank_from_join_sql,
    publisher_sort_rank_sql,
    publisher_visibility_from_join_sql,
    publisher_visibility_sql,
)
from services.image_assets import resolve_image_url
from services.signal_quality import (
    DEFAULT_SIGNAL_MOS_MIN_PCT,
    LATEST_VALUATION_CTE,
    actionable_signal_sql,
    effective_signal_mos_min,
)

LATEST_SHADOW_VALUATION_CTE = """
latest_shadow_valuation AS MATERIALIZED (
    SELECT DISTINCT ON (vsr.listing_id)
           vsr.listing_id, vsr.is_signal, vsr.actual_ppm2,
           vsr.fair_ppm2, vsr.mos_pct, vsr.signal_score,
           vsr.trust_tier, vsr.trust_score,
           vsr.legal_status, vsr.legal_flags,
           vsr.source_quality_flags, vsr.source_quality_recheck
    FROM valuation_shadow_results vsr
    ORDER BY vsr.listing_id, vsr.computed_at DESC, vsr.id DESC
)
"""


_READ_CONNECTION_FACTORY = ContextVar(
    "radar_read_connection_factory",
    default=None,
)

RELATED_PRICE_DROP_CTE = """
related_price_drops AS MATERIALIZED (
    SELECT drop_child.duplicate_of_id AS listing_id,
           MAX(drop_child.price_ty) AS first_price
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
    GROUP BY drop_child.duplicate_of_id
)
"""

# ─────────────────────────────────────────────────────────────────────────────
# Tier-aware masking (server-side). Address + tên đường KHÔNG che (decision 2026-05-14)
# ─────────────────────────────────────────────────────────────────────────────
TIER_ORDER = {"guest": 0, "free": 1, "vip": 2, "admin": 3}
DEFAULT_VISIBLE_SOURCES = ("facebook", "guland")
PUBLIC_SOURCE_OPTIONS = frozenset(DEFAULT_VISIBLE_SOURCES)
ADMIN_SOURCE_OPTIONS = DEFAULT_VISIBLE_SOURCES
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


def _max_sql(left: str, right: str) -> str:
    return f"(CASE WHEN ({left}) >= ({right}) THEN ({left}) ELSE ({right}) END)"


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
    allowed = (
        set(ADMIN_SOURCE_OPTIONS)
        if tier == "admin"
        else set(PUBLIC_SOURCE_OPTIONS)
    )
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
    alias = prefix[:-1] if prefix.endswith(".") else prefix
    date_expr = listing_activity_at_sql(alias)
    return [
        f"{date_expr} IS NOT NULL",
        f"CAST({date_expr} AS TIMESTAMP) >= datetime('now', ?)",
    ], [interval]


def listing_activity_at_sql(alias: str = "l") -> str:
    """Public card activity: Guland price change/first seen, Facebook post date."""
    col = lambda name: f"{alias}.{name}" if alias else name
    return (
        f"(CASE WHEN {col('source')} = 'guland' "
        f"THEN COALESCE(CAST({col('price_updated_at')} AS TEXT), "
        f"{col('first_seen_at')}, {col('crawled_at')}) "
        f"ELSE COALESCE({col('posted_at')}, {col('crawled_at')}) END)"
    )


def listing_card_activity(row):
    source = str(_row_get(row, "source", "") or "").lower()
    selected_activity = _row_get(row, "activity_at")
    if source == "guland":
        price_updated_at = _row_get(row, "price_updated_at")
        if price_updated_at:
            return selected_activity or price_updated_at, "price_updated"
        return (
            selected_activity
            or _row_get(row, "first_seen_at")
            or _row_get(row, "crawled_at"),
            "first_seen",
        )
    return (
        selected_activity
        or _row_get(row, "posted_at")
        or _row_get(row, "crawled_at"),
        "posted",
    )


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


CITY_MAP = {
    "THỦ DẦU MỘT": ["Tân An", "Hiệp An", "Tương Bình Hiệp", "Định Hòa", "Chánh Mỹ", "Phú Mỹ", "Phú Cường", "Phú Hòa", "Phú Lợi", "Hiệp Thành", "Chánh Nghĩa", "Phú Tân", "Phú Thọ", "Hòa Phú"],
    "BẾN CÁT": ["Phú An", "An Tây", "An Điền", "Thới Hòa", "Mỹ Phước", "Mỹ Phước 1", "Mỹ Phước 2", "Mỹ Phước 3", "Mỹ Phước 4", "Chánh Phú Hòa", "Tân Định", "Hòa Lợi"],
    "THUẬN AN": ["An Phú", "An Thạnh", "Bình Chuẩn", "Bình Hòa", "Bình Nhâm", "Hưng Định", "Lái Thiêu", "Thuận Giao", "Vĩnh Phú", "An Sơn"],
    "DĨ AN": ["An Bình", "Bình An", "Bình Thắng", "Dĩ An", "Đông Hòa", "Tân Bình", "Tân Đông Hiệp"],
    "TÂN UYÊN": ["Hội Nghĩa", "Khánh Bình", "Phú Chánh", "Tân Hiệp", "Tân Phước Khánh", "Tân Vĩnh Hiệp", "Thạnh Hội", "Thạnh Phước", "Thái Hòa", "Uyên Hưng", "Vĩnh Tân", "Bạch Đằng"]
}

def get_city_for_ward(ward: str) -> str:
    for city, wards in CITY_MAP.items():
        if ward in wards:
            return city
    return "Khác"

def _days_ago(crawled_at) -> int | None:
    try:
        if not crawled_at:
            return None
        if isinstance(crawled_at, datetime):
            d = crawled_at.date()
        elif isinstance(crawled_at, date):
            d = crawled_at
        else:
            d = date.fromisoformat(str(crawled_at)[:10])
        return (date.today() - d).days
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
_ROAD_CODE_RE = re.compile(r"\b(dx|dh|dl|nl|d)\s*[-./_]?\s*(\d{1,3}[a-z]?)\b")
_DIMENSION_RE = re.compile(r"\b(\d{1,3}(?:[.,]\d{1,2})?)\s*([*x×])\s*(\d{1,3}(?:[.,]\d{1,2})?)\b")
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
    return out[:12]


def _normalize_dimension_part(value: str) -> str:
    return str(value or "").replace(",", ".")


def _dimension_variants(value: str):
    if "x" not in value:
        return [value]
    left, right = value.split("x", 1)
    return [f"{left}x{right}", f"{left}*{right}", f"{left}×{right}"]


def _search_tokens(keyword):
    folded = _ascii_fold(normalize_search_keyword(keyword))
    folded = re.sub(r"\s+", " ", folded).strip()
    if not folded:
        return []

    tokens = []
    remainder = folded

    for pattern, repl in (
        (
            _DIMENSION_RE,
            lambda m: tokens.append((
                "dimension",
                f"{_normalize_dimension_part(m.group(1))}x{_normalize_dimension_part(m.group(3))}",
            )) or " ",
        ),
        (_ROAD_CODE_RE, lambda m: tokens.append(("compact", f"{m.group(1)}{m.group(2)}")) or " "),
        (_MY_PHUOC_RE, lambda m: tokens.append(("phrase", f"my phuoc {m.group(1)}")) or " "),
        (_MY_PHUOC_SHORT_RE, lambda m: tokens.append(("phrase", f"my phuoc {m.group(1)}")) or " "),
        (_AREA_CODE_RE, lambda m: tokens.append(("phrase", f"khu {m.group(1)}")) or " "),
    ):
        remainder = pattern.sub(repl, remainder)

    remainder = re.sub(r"[-./_]+", " ", remainder)
    words = [
        word
        for word in re.split(r"[^a-z0-9]+", remainder.strip())
        if word and word not in _GENERIC_SEARCH_WORDS
    ]
    for word in words[:12]:
        if word in {"ty", "ti"}:
            tokens.append(("money_unit", "ty"))
        else:
            tokens.append(("word", word))

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


def _word_search_text_expr(prefix=""):
    expr = _search_text_expr(prefix)
    for separator in (
        "\r",
        "\n",
        "\t",
        "-",
        ".",
        "/",
        "_",
        ",",
        ":",
        ";",
        "(",
        ")",
        "[",
        "]",
        "{",
        "}",
        "*",
        "×",
        "+",
        "=",
        "|",
        "\\",
    ):
        expr = f"REPLACE({expr}, '{separator}', ' ')"
    return f"' ' || {expr} || ' '"


def keyword_search_filter(keyword, prefix=""):
    tokens = _search_tokens(keyword)
    if not tokens:
        return [], []
    phrase_expr = _search_text_expr(prefix)
    compact_expr = _compact_search_text_expr(prefix)
    word_expr = _word_search_text_expr(prefix)
    clauses = []
    params = []
    for mode, value in tokens:
        if mode == "compact":
            clauses.append(f"{compact_expr} LIKE ?")
            params.append(f"%{value}%")
        elif mode == "dimension":
            variants = _dimension_variants(value)
            clauses.append("(" + " OR ".join([f"{compact_expr} LIKE ?"] * len(variants)) + ")")
            params.extend(f"%{variant}%" for variant in variants)
        elif mode == "money_unit":
            clauses.append(f"({word_expr} LIKE ? OR {word_expr} LIKE ?)")
            params.extend(["% ty %", "% ti %"])
        elif mode == "word":
            clauses.append(f"{word_expr} LIKE ?")
            params.append(f"% {value} %")
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


def related_price_drop_join_sql(alias="l", join_alias="related_drop"):
    return (
        f"LEFT JOIN related_price_drops {join_alias} "
        f"ON {join_alias}.listing_id = {alias}.id"
    )


def effective_price_drop_select_sql(
    alias="l",
    lateral_alias="related_drop",
    *,
    boolean_flag=False,
):
    first_price = f"{lateral_alias}.first_price"
    valid_raw_drop = _valid_price_drop_sql(f"{alias}.")
    flag_true = "TRUE" if boolean_flag else "1"
    flag_false = "FALSE" if boolean_flag else "0"
    return f"""
               CASE
                   WHEN {valid_raw_drop} OR {first_price} IS NOT NULL
                   THEN {flag_true} ELSE {flag_false}
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


def build_listing_filters(
    sources=None,
    wards=None,
    prop_types=None,
    only_drops=False,
    prefix="",
    area_min=0,
    area_max=0,
    price_min=0,
    price_max=0,
    area_ranges=None,
    price_ranges=None,
    keyword="",
    date_range=None,
    require_complete=False,
    include_guland_high_activity=False,
    publisher_alias: str | None = None,
):
    if not sources:
        sources = list(DEFAULT_VISIBLE_SOURCES)
    prop_types = normalize_property_types(prop_types)

    # Common filters. Normal views hide duplicates; drop-only views show reliable
    # repost drops even when the lower-price repost is marked duplicate.
    col = lambda name: f"{prefix}{name}" if prefix else name
    listing_alias = prefix[:-1] if prefix.endswith(".") else "listings"
    publisher_visibility = (
        publisher_visibility_from_join_sql(
            listing_alias,
            publisher_alias,
            include_high_activity=include_guland_high_activity,
        )
        if publisher_alias
        else publisher_visibility_sql(
            listing_alias,
            include_high_activity=include_guland_high_activity,
        )
    )
    where_parts = [
        f"{col('probably_sold')} = 0",
        f"COALESCE({col('is_blacklisted')},0)=0",
        f"COALESCE({col('review_hidden')},0)=0",
        f"COALESCE({col('source_status')},'unknown') <> 'inactive'",
        publisher_visibility,
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
    if require_complete:
        where_parts.extend([
            f"NULLIF(TRIM(COALESCE({col('ward')},'')), '') IS NOT NULL",
            f"{col('price_ty')} IS NOT NULL AND {col('price_ty')} > 0",
            f"{col('area_m2')} IS NOT NULL AND {col('area_m2')} > 0",
        ])

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


def _deal_mos_signal_sql(display_mos_expr: str, mos_min: float) -> str:
    """Săn deal mirrors the all-listings visible MOS filter.

    QC flags remain visible as warnings on cards/admin workflows, but they do
    not hide rows that match the user's displayed MOS threshold.
    """
    return f"COALESCE(({display_mos_expr}), 0) >= {float(mos_min)}"


@dataclass(frozen=True)
class DealSql:
    actual_expr: str
    fair_expr: str
    mos_expr: str
    condition: str


def build_deal_sql(mos_min: float) -> DealSql:
    actual = "COALESCE(v.actual_ppm2, sv.actual_ppm2, l.price_per_m2)"
    fair = _display_fair_sql("v", "sv")
    mos = _display_mos_sql("v", "sv", actual)
    minimum = float(
        mos_min if mos_min is not None else DEFAULT_SIGNAL_MOS_MIN_PCT
    )
    condition = (
        f"({actionable_signal_sql('v')}) AND "
        f"({_deal_mos_signal_sql(mos, minimum)})"
    )
    return DealSql(actual, fair, mos, condition)


def _signal_listing_data_sql(alias: str = "l") -> str:
    col = lambda name: f"{alias}.{name}" if alias else name
    return " AND ".join([
        f"NULLIF(TRIM(COALESCE({col('ward')},'')), '') IS NOT NULL",
        f"{col('price_ty')} IS NOT NULL AND {col('price_ty')} > 0",
        f"{col('area_m2')} IS NOT NULL AND {col('area_m2')} > 0",
        f"{col('price_per_m2')} IS NOT NULL AND {col('price_per_m2')} > 0",
    ])


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
        "newest": f"{listing_activity_at_sql('l')} DESC, l.id DESC",
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
def use_read_connection_factory(factory):
    """Temporarily route service reads through a task-local connection scope."""
    token = _READ_CONNECTION_FACTORY.set(factory)
    try:
        yield
    finally:
        _READ_CONNECTION_FACTORY.reset(token)


@contextmanager
def _read_conn(_db_path=None):
    """Reuse the per-thread PostgreSQL connection for hot read models."""
    factory = _READ_CONNECTION_FACTORY.get()
    scope = factory() if factory is not None else get_conn()
    with scope as conn:
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


def _looks_like_lot_frontage_width(r, folded, value, start=None):
    frontage = _as_float(_row_get(r, "frontage_m"))
    width = _as_float(value)
    if frontage is None or width is None or abs(frontage - width) > 0.06:
        return False
    text = folded or ""
    if start is not None:
        text = text[max(0, start - 28):start + 48]
    return bool(re.search(
        r"\b(?:mat\s*tien|ngang|mat\s+ngang)\s*(?:dat\s*)?(?:rong\s*)?"
        r"\d+(?:[,.]\d+)?\s*m\b",
        text,
        re.I,
    ))


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
    if inferred and not _looks_like_lot_frontage_width(r, folded, inferred) and not (distance_context and float(inferred) >= 20):
        return float(inferred)
    for m in _ROAD_WIDTH_FALLBACK_RE.finditer(folded):
        before = folded[max(0, m.start() - 18):m.start()]
        match_text = m.group(0)
        if re.search(r"\b(?:cach|gan|vao)\s*$", before, re.I) or re.search(r"\bvao\s+\d+(?:[,.]\d+)?\s*m\b", match_text, re.I):
            continue
        value = _as_float(m.group(1))
        if _looks_like_lot_frontage_width(r, folded, value, m.start()):
            continue
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
    road_type = str(_row_get(r, "road_type", "") or "")
    if tier == 3 and road_type in {"duong_nhua", "be_tong", "duong_dat"}:
        return ROAD_TYPE_LABELS.get(road_type)
    if tier in ROAD_TIER_LABELS:
        return ROAD_TIER_LABELS[tier]
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


def format_signal_card_record(r, primary_img=None, tier: str = "guest"):
    fair_ppm2 = round(r['fair_ppm2'], 1) if r['fair_ppm2'] else None
    badge_meta = signal_badge_metadata(r)
    activity_at, card_date_reason = listing_card_activity(r)
    record = {
        "id": r['id'],
        "detail_href": f"/listing/{int(r['id'])}",
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
        "days_ago": _days_ago(activity_at),
        "card_date_reason": card_date_reason,
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


_format_signal_row = format_signal_card_record


def _load_signals_legacy(db_path, sources=None, wards=None, prop_types=None, only_drops=False, mos_min=DEFAULT_SIGNAL_MOS_MIN_PCT, sort='newest', page=1, limit=30, area_min=0, area_max=0, price_min=0, price_max=0, tier='guest', area_ranges=None, price_ranges=None, keyword="", include_total=True, date_range=None, include_guland_high_activity=False):
    mos_min = effective_signal_mos_min(tier, mos_min, was_explicit=True)
    # Guest tier cannot use the separate price-drop-only filter.
    if tier == "guest":
        only_drops = False
    conn = _open_read_conn(db_path)
    where_sql, params = build_listing_filters(
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
        include_guland_high_activity=include_guland_high_activity,
        publisher_alias="feed_sp",
    )
    deal = build_deal_sql(mos_min)
    actual_expr = deal.actual_expr
    display_fair_expr = deal.fair_expr
    display_mos_expr = deal.mos_expr
    signal_condition = deal.condition
    page = max(int(page or 1), 1)
    limit = min(max(int(limit or 30), 1), 100)
    offset = (page - 1) * limit
    query_limit = limit if include_total else limit + 1
    order_sql = _signal_sort_sql(sort)
    if sort == "mos_desc":
        order_sql = f"({display_mos_expr}) DESC, l.id DESC"
    elif sort == "score_desc":
        score_expr = _max_sql("COALESCE(v.signal_score,0)", "COALESCE(sv.signal_score,0)")
        order_sql = f"{score_expr} DESC, ({display_mos_expr}) DESC, l.id DESC"
    order_sql = (
        f"{publisher_sort_rank_from_join_sql('l', 'feed_sp')} ASC, "
        f"{order_sql}"
    )
    fresh_flag = "0 AS is_fresh_locked"
    total_select = "COUNT(*) OVER() AS total_count," if include_total else ""

    rows = conn.execute(f"""
        WITH {LATEST_VALUATION_CTE},
             {LATEST_SHADOW_VALUATION_CTE},
             {RELATED_PRICE_DROP_CTE}
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
               'display_mos' AS signal_model,
               l.id, l.title, l.description, l.source, l.area_m2, l.frontage_m, l.depth_m, l.price_ty,
               l.property_type, l.road_name, l.road_type, l.road_width_m, l.tho_cu_m2, l.tho_cu_ratio, l.is_hot,
               {effective_price_drop_select_sql("l", "related_drop")},
               l.suspicious_bait,
               l.duplicate_of_id,
               {listing_activity_at_sql('l')} AS activity_at,
               l.url, l.crawled_at, l.posted_at, l.first_seen_at,
               l.price_updated_at, l.ward, l.road_tier, l.has_so,
                {_max_sql("COALESCE(v.signal_score, 0)", "COALESCE(sv.signal_score, 0)")} as signal_score,
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
        {publisher_feed_join_sql('l', 'feed_lp', 'feed_sp')}
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
        {related_price_drop_join_sql("l", "related_drop")}
        WHERE ({signal_condition}) AND {_signal_listing_data_sql("l")} AND {where_sql}
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


def _signal_read_model_enabled() -> bool:
    return os.getenv("RADAR_SIGNAL_READ_MODEL_ENABLED", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def signal_read_model_enabled() -> bool:
    """Expose the shared rollout gate to adjacent public read services."""
    return _signal_read_model_enabled()


def load_signals_from_read_model(*args, **kwargs):
    from services.signal_read_model import (
        load_signals_from_read_model as read_model_loader,
    )

    return read_model_loader(*args, **kwargs)


def load_signals(*args, **kwargs):
    if _signal_read_model_enabled():
        return load_signals_from_read_model(*args, **kwargs)
    return _load_signals_legacy(*args, **kwargs)


def count_filtered_signals(
    conn,
    *,
    sources=None,
    wards=None,
    prop_types=None,
    only_drops=False,
    mos_min=DEFAULT_SIGNAL_MOS_MIN_PCT,
    area_min=0,
    area_max=0,
    price_min=0,
    price_max=0,
    area_ranges=None,
    price_ranges=None,
    keyword="",
    tier="guest",
    date_range=None,
    include_guland_high_activity=False,
) -> int:
    """Count the exact signal feed using the active read implementation."""
    mos_min = effective_signal_mos_min(tier, mos_min, was_explicit=True)
    if tier == "guest":
        only_drops = False

    if _signal_read_model_enabled():
        from services.signal_read_model import count_signals_from_read_model

        return count_signals_from_read_model(
            conn,
            sources=sources,
            wards=wards,
            prop_types=prop_types,
            only_drops=only_drops,
            mos_min=mos_min,
            area_min=area_min,
            area_max=area_max,
            price_min=price_min,
            price_max=price_max,
            area_ranges=area_ranges,
            price_ranges=price_ranges,
            keyword=keyword,
            tier=tier,
            date_range=date_range,
            include_guland_high_activity=include_guland_high_activity,
        )

    signal_where_sql, signal_params = build_listing_filters(
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
        include_guland_high_activity=include_guland_high_activity,
    )
    signal_condition = build_deal_sql(mos_min).condition
    signal_row = conn.execute(
        f"""
        WITH {LATEST_VALUATION_CTE},
             {LATEST_SHADOW_VALUATION_CTE}
        SELECT COUNT(*) AS signals
        FROM listings l
        LEFT JOIN latest_valuation v ON l.id = v.listing_id
        LEFT JOIN latest_shadow_valuation sv ON l.id = sv.listing_id
        WHERE ({signal_condition})
          AND {_signal_listing_data_sql("l")}
          AND {signal_where_sql}
        """,
        signal_params,
    ).fetchone()
    return int(_row_get(signal_row, "signals", 0) or 0)


def load_dashboard_summary(db_path, sources=None, wards=None, prop_types=None, only_drops=False, trend_period='day', include_trend=False, mos_min=DEFAULT_SIGNAL_MOS_MIN_PCT, area_min=0, area_max=0, price_min=0, price_max=0, area_ranges=None, price_ranges=None, keyword="", tier='guest', date_range=None, include_guland_high_activity=False):
    mos_min = effective_signal_mos_min(tier, mos_min, was_explicit=True)
    if tier == "guest":
        only_drops = False

    conn = _open_read_conn(db_path)
    where_sql, params = build_listing_filters(
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
        include_guland_high_activity=include_guland_high_activity,
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

    stats["signals"] = count_filtered_signals(
        conn,
        sources=sources,
        wards=wards,
        prop_types=prop_types,
        only_drops=only_drops,
        mos_min=mos_min,
        area_min=area_min,
        area_max=area_max,
        price_min=price_min,
        price_max=price_max,
        area_ranges=area_ranges,
        price_ranges=price_ranges,
        keyword=keyword,
        tier=tier,
        date_range=date_range,
        include_guland_high_activity=include_guland_high_activity,
    )

    market = []
    summary_rows = conn.execute(f"""
        SELECT property_type, AVG(price_per_m2) as mean_ppm2, COUNT(*) as n_samples
        FROM listings
        WHERE is_outlier = 0 AND {where_sql}
        GROUP BY property_type
        HAVING COUNT(*) >= 1
    """, params).fetchall()
    for row in summary_rows:
        mean_ppm2 = _row_get(row, "mean_ppm2")
        if mean_ppm2 is None:
            continue
        prop_type = _row_get(row, "property_type")
        market.append({
            "type": prop_type,
            "label": PROPERTY_TYPE_LABELS.get(prop_type, prop_type),
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
            date_range=date_range,
            include_guland_high_activity=include_guland_high_activity,
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


def load_counts(db_path, sources=None, wards=None, prop_types=None, only_drops=False, mos_min=DEFAULT_SIGNAL_MOS_MIN_PCT, area_min=0, area_max=0, price_min=0, price_max=0, area_ranges=None, price_ranges=None, keyword="", tier="guest", date_range=None, include_guland_high_activity=False, listings_version=0):
    mos_min = effective_signal_mos_min(tier, mos_min, was_explicit=True)
    conn = _open_read_conn(db_path)
    from services.listing_feed import (
        listing_read_model_enabled,
        load_listing_counts_from_read_model,
    )

    if listing_read_model_enabled(listings_version):
        stats = load_listing_counts_from_read_model(
            conn,
            sources=sources,
            wards=wards,
            prop_types=prop_types,
            only_drops=only_drops,
            area_min=area_min,
            area_max=area_max,
            price_min=price_min,
            price_max=price_max,
            area_ranges=area_ranges,
            price_ranges=price_ranges,
            keyword=keyword,
            tier=tier,
            date_range=date_range,
            include_guland_high_activity=include_guland_high_activity,
        )
    else:
        where_sql, params = build_listing_filters(
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
            include_guland_high_activity=include_guland_high_activity,
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
        stats = dict(row) if row else {
            "total": 0,
            "hot": 0,
            "new_recent_days_7": 0,
            "price_drops": 0,
        }
    stats["signals"] = count_filtered_signals(
        conn,
        sources=sources,
        wards=wards,
        prop_types=prop_types,
        only_drops=only_drops,
        mos_min=mos_min,
        area_min=area_min,
        area_max=area_max,
        price_min=price_min,
        price_max=price_max,
        area_ranges=area_ranges,
        price_ranges=price_ranges,
        keyword=keyword,
        tier=tier,
        date_range=date_range,
        include_guland_high_activity=include_guland_high_activity,
    )
    conn.close()
    return stats

def load_trend_data(db_path, sources=None, wards=None, prop_types=None, only_drops=False, trend_period='day', area_min=0, area_max=0, price_min=0, price_max=0, area_ranges=None, price_ranges=None, keyword="", date_range=None, include_guland_high_activity=False):
    if not sources:
        sources = list(DEFAULT_VISIBLE_SOURCES)
    prop_types = normalize_property_types(prop_types)

    conn = _open_read_conn(db_path)

    where_parts = [
        "probably_sold = 0",
        "COALESCE(is_blacklisted,0)=0",
        "COALESCE(review_hidden,0)=0",
        publisher_visibility_sql(
            "listings",
            include_high_activity=include_guland_high_activity,
        ),
    ]
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
    date_clauses, date_params = listing_date_range_filter(date_range)
    where_parts.extend(date_clauses)
    params.extend(date_params)
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


def _market_opportunity_rank(row):
    deal_count = float(row.get("deal_count") or 0)
    median_mos = float(row.get("median_mos") or 0)
    signal_rate = float(row.get("signal_rate") or 0)
    return median_mos * 10 + signal_rate + min(deal_count, 20) * 2


def _market_opportunity_rank_label(row, max_deal_count):
    median_mos = float(row.get("median_mos") or 0)
    deal_count = int(row.get("deal_count") or 0)
    if median_mos >= 25:
        return "Bien an toan tot"
    if deal_count > 0 and deal_count == max_deal_count:
        return "Nhieu deal nhat"
    if median_mos >= 15:
        return "Can loc sau"
    return "Theo doi them"


def load_market_opportunities(
    db_path,
    sources=None,
    wards=None,
    prop_types=None,
    only_drops=False,
    mos_min=DEFAULT_SIGNAL_MOS_MIN_PCT,
    area_min=0,
    area_max=0,
    price_min=0,
    price_max=0,
    area_ranges=None,
    price_ranges=None,
    keyword="",
    tier="guest",
    date_range=None,
    include_guland_high_activity=False,
    limit=6,
):
    effective_mos = effective_signal_mos_min(
        tier,
        mos_min,
        was_explicit=mos_min is not None,
    )
    normalized_date_range = normalize_date_range(date_range, default="3m") or "3m"
    normalized_keyword = normalize_search_keyword(keyword)
    where_sql, params = build_listing_filters(
        sources=sources,
        wards=wards,
        prop_types=prop_types,
        only_drops=only_drops,
        prefix="l.",
        area_min=area_min,
        area_max=area_max,
        price_min=price_min,
        price_max=price_max,
        area_ranges=area_ranges,
        price_ranges=price_ranges,
        keyword=normalized_keyword,
        date_range=normalized_date_range,
        include_guland_high_activity=include_guland_high_activity,
    )
    deal_sql = build_deal_sql(effective_mos)
    signal_condition = f"({actionable_signal_sql('v')}) AND COALESCE(({deal_sql.mos_expr}), 0) >= ?"
    query_params = list(params) + [effective_mos]

    query = f"""
        WITH filtered_listings AS MATERIALIZED (
            SELECT
                l.id,
                l.ward,
                l.price_per_m2,
                l.price_ty,
                l.area_m2
            FROM listings l
            WHERE {where_sql}
              AND l.ward IS NOT NULL
              AND TRIM(l.ward) != ''
              AND LOWER(l.ward) != 'unknown'
              AND COALESCE(l.price_per_m2, 0) > 0
              AND COALESCE(l.price_per_m2, 0) < 1000
        ),
        opportunity_rows AS (
            SELECT
                l.ward,
                l.price_per_m2,
                l.price_ty,
                l.area_m2,
                {deal_sql.fair_expr} AS fair_ppm2,
                {deal_sql.mos_expr} AS mos_pct,
                CASE WHEN {signal_condition} THEN 1 ELSE 0 END AS is_signal
            FROM filtered_listings l
            LEFT JOIN LATERAL (
                SELECT vr.*
                FROM valuation_results vr
                WHERE vr.listing_id = l.id
                ORDER BY vr.computed_at DESC, vr.id DESC
                LIMIT 1
            ) v ON TRUE
            LEFT JOIN LATERAL (
                SELECT
                    vsr.listing_id,
                    vsr.is_signal,
                    vsr.actual_ppm2,
                    vsr.fair_ppm2,
                    vsr.mos_pct,
                    vsr.signal_score,
                    vsr.trust_tier,
                    vsr.trust_score,
                    vsr.legal_status,
                    vsr.legal_flags,
                    vsr.source_quality_flags,
                    vsr.source_quality_recheck
                FROM valuation_shadow_results vsr
                WHERE vsr.listing_id = l.id
                ORDER BY vsr.computed_at DESC, vsr.id DESC
                LIMIT 1
            ) sv ON TRUE
            WHERE COALESCE(v.is_outlier, 0) = 0
        )
        SELECT
            ward,
            COUNT(*) AS total_count,
            SUM(is_signal) AS deal_count,
            ROUND(AVG(price_per_m2)::numeric, 1) AS avg_price,
            ROUND((percentile_cont(0.5) WITHIN GROUP (ORDER BY price_per_m2))::numeric, 1) AS median_price,
            ROUND(AVG(price_ty)::numeric, 2) AS avg_price_ty,
            ROUND(AVG(CASE WHEN fair_ppm2 IS NOT NULL AND area_m2 IS NOT NULL THEN fair_ppm2 * area_m2 / 1000 END)::numeric, 2) AS avg_fair_ty,
            COALESCE(ROUND(AVG(CASE WHEN is_signal = 1 AND mos_pct > 0 THEN mos_pct END)::numeric, 1), 0) AS avg_signal_mos,
            COALESCE(ROUND((percentile_cont(0.5) WITHIN GROUP (ORDER BY mos_pct) FILTER (WHERE is_signal = 1 AND mos_pct > 0))::numeric, 1), 0) AS median_mos,
            ROUND((SUM(is_signal)::numeric / NULLIF(COUNT(*), 0)) * 100, 1) AS signal_rate
        FROM opportunity_rows
        GROUP BY ward
        ORDER BY deal_count DESC, median_mos DESC, total_count DESC
    """

    with _read_conn(db_path) as conn:
        raw_rows = conn.execute(query, query_params).fetchall()

    all_rows = []
    for row in raw_rows:
        item = dict(row)
        item["total_count"] = int(item.get("total_count") or 0)
        item["deal_count"] = int(item.get("deal_count") or 0)
        item["count"] = item["deal_count"]
        item["median_mos"] = float(item.get("median_mos") or 0)
        item["avg_signal_mos"] = float(item.get("avg_signal_mos") or 0)
        item["avg_mos"] = item["median_mos"]
        item["signal_rate"] = float(item.get("signal_rate") or 0)
        item["avg_price"] = float(item.get("avg_price") or 0)
        item["median_price"] = float(item.get("median_price") or 0)
        item["avg_price_ty"] = float(item.get("avg_price_ty") or 0)
        item["avg_fair_ty"] = float(item.get("avg_fair_ty") or 0)
        item["opportunity_score"] = round(_market_opportunity_rank(item), 1)
        all_rows.append(item)

    eligible_rows = [row for row in all_rows if row["deal_count"] > 0 and row["median_mos"] > 0]
    eligible_rows.sort(key=_market_opportunity_rank, reverse=True)
    shown_limit = max(1, min(int(limit or 6), 12))
    shown_rows = eligible_rows[:shown_limit]
    max_deal_count = max((row["deal_count"] for row in eligible_rows), default=0)
    for row in shown_rows:
        row["rank_label"] = _market_opportunity_rank_label(row, max_deal_count)

    total_deals = sum(row["deal_count"] for row in all_rows)
    total_listings = sum(row["total_count"] for row in all_rows)
    return {
        "rows": shown_rows,
        "all_rows": all_rows,
        "summary": {
            "total_wards": len(all_rows),
            "eligible_wards": len(eligible_rows),
            "shown_wards": len(shown_rows),
            "total_deals": total_deals,
            "shown_deals": sum(row["deal_count"] for row in shown_rows),
            "total_listings": total_listings,
            "ranking": "risk_adjusted_mos_rate_volume",
        },
        "applied_filters": {
            "sources": normalize_sources_for_tier(sources, tier),
            "wards": list(wards or []),
            "prop_types": normalize_property_types(prop_types),
            "only_drops": bool(only_drops),
            "mos_min": effective_mos,
            "date_range": normalized_date_range,
            "keyword": normalized_keyword,
        },
        "as_of": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }


def _shift_month(d: date, delta: int) -> date:
    month_idx = d.year * 12 + (d.month - 1) + delta
    return date(month_idx // 12, month_idx % 12 + 1, 1)


def _market_indicator_filters(sources=None, wards=None, prop_types=None, prefix="",
                              area_min=0, area_max=0, price_min=0, price_max=0,
                              area_ranges=None, price_ranges=None,
                              only_drops=False, keyword="", date_range=None,
                              include_guland_high_activity=False):
    if not sources:
        sources = list(DEFAULT_VISIBLE_SOURCES)
    prop_types = normalize_property_types(prop_types)

    col = lambda name: f"{prefix}{name}" if prefix else name
    where_parts = [
        f"{col('probably_sold')} = 0",
        f"COALESCE({col('is_blacklisted')},0)=0",
        f"COALESCE({col('review_hidden')},0)=0",
        publisher_visibility_sql(
            prefix[:-1] if prefix.endswith(".") else "listings",
            include_high_activity=include_guland_high_activity,
        ),
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
    if only_drops:
        where_parts.append(group_price_drop_filter_sql(prefix))

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


def _market_sample_confidence(total_count: int) -> str:
    total = int(total_count or 0)
    if total >= 20:
        return "high"
    if total >= 5:
        return "medium"
    if total > 0:
        return "low"
    return "none"


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
                           area_ranges=None, price_ranges=None,
                           only_drops=False, keyword="", date_range=None,
                           mos_min=DEFAULT_SIGNAL_MOS_MIN_PCT, tier="guest",
                           include_guland_high_activity=False):
    effective_mos = effective_signal_mos_min(
        tier,
        mos_min,
        was_explicit=mos_min is not None,
    )
    normalized_date_range = normalize_date_range(date_range, default=None)
    normalized_keyword = normalize_search_keyword(keyword)
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
        only_drops=only_drops,
        keyword=normalized_keyword,
        date_range=normalized_date_range,
        include_guland_high_activity=include_guland_high_activity,
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
                CASE WHEN ({signal_condition}) AND COALESCE(v.mos_pct, 0) >= ? THEN 1 ELSE 0 END AS is_signal
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
    """, [effective_mos] + list(params)).fetchall()
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
            "sample_confidence": _market_sample_confidence(total),
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
            "date_range": normalized_date_range or "all",
            "mos_min": effective_mos,
            "distress_hotspots": sum(1 for x in distress if x["ratio_pct"] >= 25),
            "supply_hotspots": sum(1 for x in supply if x["level_key"] in ("danger", "warning")),
            "area_risk_hotspots": sum(1 for x in area_risk_radar if x["risk_score"] >= 70),
            "wards_scanned": len({x["ward"] for x in distress} | {x["ward"] for x in supply}),
        }
    }

def load_listing_detail(db_path, listing_id, tier: str = "guest"):
    conn = _open_read_conn(db_path)
    fresh_flag = "0 AS is_fresh_locked"
    actual_expr = "COALESCE(v.actual_ppm2, sv.actual_ppm2, l.price_per_m2)"
    display_fair_expr = _display_fair_sql("v", "sv")
    display_mos_expr = _display_mos_sql("v", "sv", actual_expr)
    listing = conn.execute(f"""
        WITH {LATEST_VALUATION_CTE},
             {LATEST_SHADOW_VALUATION_CTE}
        SELECT l.*,
               {listing_activity_at_sql('l')} AS activity_at,
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
               {_max_sql("COALESCE(v.signal_score,0)", "COALESCE(sv.signal_score,0)")} AS signal_score,
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
               CASE
                   WHEN map_listing_override.listing_id IS NOT NULL
                   THEN map_listing_override.lat
                   WHEN map_group_override.location_key IS NOT NULL
                   THEN map_group_override.lat
                   ELSE ml.lat
               END AS map_lat,
               CASE
                   WHEN map_listing_override.listing_id IS NOT NULL
                   THEN map_listing_override.lng
                   WHEN map_group_override.location_key IS NOT NULL
                   THEN map_group_override.lng
                   ELSE ml.lng
               END AS map_lng,
               CASE
                   WHEN map_listing_override.listing_id IS NOT NULL
                   THEN 'exact'
                   ELSE ml.location_precision
               END AS map_precision,
               CASE
                   WHEN map_listing_override.listing_id IS NOT NULL
                   THEN 'Vị trí chính xác do admin xác minh'
                   ELSE ml.location_label
               END AS map_label,
               CASE
                   WHEN map_listing_override.listing_id IS NOT NULL
                   THEN 'admin-override'
                   ELSE ml.resolver_version
               END AS map_resolver_version,
               CASE
                   WHEN map_listing_override.listing_id IS NOT NULL
                   THEN 'listing'
                   WHEN map_group_override.location_key IS NOT NULL
                   THEN 'group'
                   ELSE NULL
               END AS map_manual_override,
               {fresh_flag}
        FROM listings l
        LEFT JOIN latest_valuation v ON l.id = v.listing_id
        LEFT JOIN latest_shadow_valuation sv ON l.id = sv.listing_id
        LEFT JOIN legal_verifications lv ON lv.listing_id = l.id
        LEFT JOIN listing_map_locations ml ON ml.listing_id = l.id
        LEFT JOIN listing_map_listing_overrides map_listing_override
          ON map_listing_override.listing_id = l.id
         AND map_listing_override.active = TRUE
        LEFT JOIN listing_map_group_overrides map_group_override
          ON map_group_override.location_key = ml.location_key
         AND map_group_override.active = TRUE
         AND ml.location_precision IN ('road', 'landmark', 'ward')
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
    map_lat = listing_dict.pop("map_lat", None)
    map_lng = listing_dict.pop("map_lng", None)
    map_precision = listing_dict.pop("map_precision", None)
    map_label = listing_dict.pop("map_label", None)
    map_resolver_version = listing_dict.pop("map_resolver_version", None)
    map_manual_override = listing_dict.pop("map_manual_override", None)
    map_location = None
    if (
        map_precision in {"exact", "road", "landmark", "ward"}
        and map_lat is not None
        and map_lng is not None
    ):
        map_location = {
            "lat": float(map_lat),
            "lng": float(map_lng),
            "precision": map_precision,
            "label": str(map_label or ""),
            "resolver_version": str(map_resolver_version or ""),
        }
        if tier == "admin" and map_manual_override in {"listing", "group"}:
            map_location["manual_override"] = map_manual_override
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
        "map_location": map_location,
        "tier": tier,
    }

def get_base_filters(req):
    active_city = req.args.get("city")
    wards = req.args.getlist("ward[]") or req.args.getlist("ward")
    sources = req.args.getlist("source[]") or req.args.getlist("source")
    prop_types = normalize_property_types(req.args.getlist("prop_type[]") or req.args.getlist("prop_type"))
    if req.args.get("ward_mode") == "none":
        wards = ["__NO_WARD_SELECTED__"]
    only_drops = req.args.get("only_drops") == "1"
    trend_period = req.args.get("trend_period", "day")
    requested_mos = req.args.get("mos_min")
    mos_was_explicit = "mos_min" in req.args
    tier = "guest"

    try:
        from auth.core import current_tier as _current_tier
        tier = _current_tier()
    except Exception:
        pass

    mos_min = effective_signal_mos_min(
        tier,
        requested_mos,
        was_explicit=mos_was_explicit,
    )
    if tier == "guest":
        only_drops = False

    sources = normalize_sources_for_tier(sources, tier)

    if not active_city and wards:
        active_city = get_city_for_ward(wards[0])
    if not active_city:
        active_city = "THỦ DẦU MỘT"

    return active_city, wards, sources, prop_types, only_drops, trend_period, mos_min
