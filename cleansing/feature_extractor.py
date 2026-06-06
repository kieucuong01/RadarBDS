"""
Feature Extractor — Python thuần, 0 token Claude
Học từ pattern thực tế của BatDongSan, Guland, Facebook

Pattern quan sát từ BatDongSan:
  Line 0: Title (chứa nhiều thông tin nhất)
  Line 1: Giá  → "12,5 tỷ" / "880 triệu" / "Thỏa thuận"
  Line 2: DT   → "1.826 m²"
  Line 3: Giá/m² → "6,85 tr/m²"
  Line 4: Địa chỉ
  Line 5+: Mô tả (ngang/sâu, thổ cư, pháp lý, lộ giới, loại đường...)

Pattern Facebook:
  Free-form text, cần regex aggressive hơn
"""

import re
import logging
import unicodedata
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


def _ascii_fold(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = text.replace("Đ", "D").replace("đ", "d")
    return "".join(
        c for c in unicodedata.normalize("NFD", text)
        if unicodedata.category(c) != "Mn"
    ).lower()


_NON_ASKING_PRICE_PATTERNS = [
    # "Rẻ hơn thị trường 100 triệu" / "thấp hơn 1 tỷ" is a delta, not asking price.
    r'(?:rẻ\s*hơn|re\s*hon|thấp\s*hơn|thap\s*hon)\s*(?:thị\s*trường|thi\s*truong)?\s*[:：\-]?\s*[\d,.]+\s*(?:tỷ|ty|tỉ|triệu|tr|m|k)\b',
    # Down-payment / financing snippets are not total asking price.
    r'(?:đưa\s*trước|dua\s*truoc|trả\s*trước|tra\s*truoc|đặt\s*cọc|dat\s*coc|cọc|coc)\s*[:：\-]?\s*[\d,.]+\s*(?:tỷ|ty|tỉ|triệu|tr|m|k)\b',
    r'(?:vay|ngân\s*hàng|ngan\s*hang|nh)\s*(?:hỗ\s*trợ|ho\s*tro|được|duoc)?\s*[:：\-]?\s*[\d,.]+\s*(?:tỷ|ty|tỉ|triệu|tr|m|k)\b',
    # Contact-only price lines such as "Giá LH 0967..." should not make nearby deltas valid.
    r'(?:giá|gia)\s*(?:lh|liên\s*hệ|lien\s*he|hotline|zalo)\s*[:：\-]?\s*(?:\+?84|0)?[\d\s.\-()]{8,}',
]


def _strip_non_asking_price_phrases(text: str) -> str:
    out = text or ""
    for pattern in _NON_ASKING_PRICE_PATTERNS:
        pattern = pattern.replace("|nh)", r"|\bnh\b)")
        out = re.sub(pattern, " ", out, flags=re.IGNORECASE)
    return out


# ═══════════════════════════════════════════════════════════════════
# 1. GIÁ
# ═══════════════════════════════════════════════════════════════════

def extract_price(text: str) -> Optional[float]:
    """
    Trả về giá theo tỷ VND.
    Patterns thực tế:
      "12,5 tỷ" → 12.5
      "1.69 tỷ" → 1.69
      "880 triệu" → 0.88
      "1 tỷ 2" → 1.2
      "2 tỷ 550" → 2.55
      "2t45" → 2.45
      "1,69 tỷ" → 1.69
      "Thỏa thuận" / "Giá thỏa thuận" → None
    """
    t = unicodedata.normalize("NFKC", text or "").lower().strip()
    # Normalize "tỉ" (biến thể không chuẩn) → "tỷ" để pattern match thống nhất
    t = t.replace('tỉ', 'tỷ')
    t = _strip_non_asking_price_phrases(t)
    t_fold = _ascii_fold(t)

    # GUARD: "1txx" / "2txx" / "1 tỷ xxx" — môi giới ám chỉ "1 tỷ mấy trăm"
    # nhưng KHÔNG xác định → trả None thay vì guess.
    # (user feedback L#675: "1tỷ xxx lấy hết giá tốt" → "1txx k phải 1 tỷ").
    if re.search(r'\d+\s*(?:t|ty|ti)\s*\d*x+\s*(?:tr|trieu)?\b', t_fold, re.IGNORECASE):
        m = re.search(r'\b(\d+)\s*(?:ty|ti)\s*(\d{1,3})x+\s*(?:tr|trieu)?\b', t_fold, re.IGNORECASE)
        if m:
            ty = float(m.group(1).replace(',', '.'))
            rest = float(m.group(2))
            if rest >= 100:
                return round(ty + rest / 1000, 4)
            if rest >= 10:
                return round(ty + rest / 100, 4)
            return round(ty + rest / 10, 4)
        return None
    if re.search(r'\d+\s*(?:t|tỷ|ty|tỉ)\s*\d*x{2,}', t, re.IGNORECASE):
        return None

    # "12,x tỷ" / "12.x ty" is an intentional fuzzy price. Use midpoint
    # 12.5 for valuation while the original text remains visible in details.
    m = re.search(r'\b(\d+)\s*[,\.]\s*x\b\s*(?:ty|ti)\b', t_fold, re.IGNORECASE)
    if m:
        return None

    # Facebook shorthand with price context: "giá tốt 2.600" means 2.6 tỷ.
    # Keep context required so dimensions/areas such as "1.212 m2" are not parsed as price.
    m = re.search(
        r'\b(?:gia|giá|chi|chỉ|ban|bán)\b(?:\s+\w+){0,4}\s+(\d{1,2})[,.](\d{3})(?!\s*m)',
        t_fold,
        re.IGNORECASE,
    )
    if m:
        return round(float(m.group(1)) + float(m.group(2)) / 1000, 4)

    # Loại phrase mô tả mức GIẢM (price drop) khỏi text trước khi parse giá:
    # "hạ 4 tỷ" / "giảm 2 tỷ" / "bớt 500tr" — đó là mức giảm, KHÔNG phải giá.
    # (User: "Giá hạ 4 tỷ chứ k phải giá là 4 tỷ")
    t = re.sub(
        r'(?:hạ|bớt|giảm(?!\s*còn)|giảm\s+mạnh|giảm\s+sâu)\s*(?:giá\s*)?(?:\w+\s+){0,2}[:：\-]?\s*[\d,.]+\s*(?:tỷ|ty|triệu|tr|m|k)\b',
        ' ', t, flags=re.IGNORECASE
    )

    # Loại bỏ giá thỏa thuận
    if any(k in t for k in ['thỏa thuận', 'thương lượng', 'liên hệ', 'inbox', 'giá tốt']):
        # Vẫn thử extract nếu có số cụ thể đi kèm
        pass

    def _parse_ty_rest(ty_str: str, rest: str) -> float:
        """Helper: X tỷ + Y phần lẻ → tỷ (ví dụ 2 + '550' = 2.55, 2 + '8' = 2.8)."""
        ty = float(ty_str.replace(',', '.'))
        v  = float(rest)
        if v >= 100:   return round(ty + v / 1000, 4)
        elif v >= 10:  return round(ty + v / 100,  4)
        else:          return round(ty + v / 10,   4)

    # Broker typo: "2t tỷ 7" means "2 tỷ 7" (2.7), not unknown.
    m = re.search(r'(\d+)\s*t\s*(?:ty|ti)\s*(\d{1,3})(?!\d)', t_fold)
    if m:
        return _parse_ty_rest(m.group(1), m.group(2))

    # Folded Vietnamese: "X ty Y" covers real Unicode "X tỷ Y" even when
    # legacy source literals below are mojibake.
    m = re.search(r'([\d]+[,.]?[\d]*)\s*(?:ty|ti)\s*([\d]+)(?!\d)', t_fold)
    if m:
        return _parse_ty_rest(m.group(1), m.group(2))

    # Pattern unicode: "X tỷ Y" hoặc "XtỷY" (2 tỷ 550=2.55, 1 tỷ 2=1.2, 2tỷ8=2.8)
    m = re.search(r'([\d]+[,.]?[\d]*)\s*tỷ\s*([\d]+)', t)
    if m:
        return _parse_ty_rest(m.group(1), m.group(2))

    # Pattern ASCII "ty" (môi giới FB hay dùng): 1ty8=1.8, 2ty550=2.55, 4ty5=4.5
    m = re.search(r'(\d+)\s*ty\s*(\d+)', t)
    if m:
        return _parse_ty_rest(m.group(1), m.group(2))

    # Folded Vietnamese: "X,Y ty" / "X.Y ty" / "X ty".
    m = re.search(r'([\d]+[,.]\d+)\s*(?:ty|ti)\b', t_fold)
    if m:
        return round(float(m.group(1).replace(',', '.')), 4)
    m = re.search(r'([\d]+)\s*(?:ty|ti)\b', t_fold)
    if m:
        return float(m.group(1))

    # Pattern compact single "t" as tỷ marker: 2t45=2.45, 2t450=2.45, 2t450tr=2.45.
    # Require digits immediately after "t" so normal words like "2 tầng" are ignored.
    m = re.search(r'(\d+)\s*t\s*(\d{1,3})(?:\s*(?:tr|triệu))?(?![\da-zà-ỹ])', t)
    if m:
        return _parse_ty_rest(m.group(1), m.group(2))

    # Pattern: "X,Y tỷ" hoặc "X.Y tỷ"
    m = re.search(r'([\d]+[,.]\d+)\s*tỷ', t)
    if m:
        return round(float(m.group(1).replace(',', '.')), 4)

    # Pattern: "X tỷ" (không có phần lẻ) — unicode
    m = re.search(r'([\d]+)\s*tỷ', t)
    if m:
        return float(m.group(1))

    # Pattern: "Xty" (không có phần lẻ) — ASCII
    m = re.search(r'(\d+)\s*ty\b', t)
    if m:
        return float(m.group(1))

    # Pattern: "XXX triệu" — fix double-assign + missing return khi val<100
    # "1.500 triệu" → 1500 → 1.5 tỷ  |  "880 triệu" → 0.88 tỷ  |  "80 triệu" → None (quá thấp)
    m = re.search(r'([\d]+[,.]?[\d]*)\s*triệu', t)
    if m:
        raw = m.group(1).replace(',', '').replace('.', '')
        try:
            val = float(raw)
            if val >= 100:
                return round(val / 1000, 4)
        except ValueError:
            pass

    return None


_DIM_NUM_RE = r'[\d]+[,.]?[\d]*'
_DIM_PAIR_RE = re.compile(
    rf'(?<![/\d])({_DIM_NUM_RE})\s*m?\s*[x×\*]\s*({_DIM_NUM_RE})\s*m?(?=\b|tc|tho\s*cu)(?!\d)',
    re.IGNORECASE,
)


def _parse_dim_value(raw: str) -> float:
    return float(str(raw).replace(',', '.'))


def _valid_lot_dimensions(frontage_m: float, depth_m: float) -> bool:
    return 2 <= frontage_m <= 50 and 5 <= depth_m <= 500


def _area_from_dimension_pair(match: re.Match) -> Optional[float]:
    frontage_m = _parse_dim_value(match.group(1))
    depth_m = _parse_dim_value(match.group(2))
    if _valid_lot_dimensions(frontage_m, depth_m):
        return round(frontage_m * depth_m, 1)
    return None


def _first_valid_dimension_pair(text: str) -> Optional[tuple[float, float]]:
    for match in _DIM_PAIR_RE.finditer(text):
        frontage_m = _parse_dim_value(match.group(1))
        depth_m = _parse_dim_value(match.group(2))
        if _valid_lot_dimensions(frontage_m, depth_m):
            return frontage_m, depth_m
    return None


def _first_valid_dimension_area(text: str) -> Optional[float]:
    pair = _first_valid_dimension_pair(text)
    if pair is None:
        return None
    frontage_m, depth_m = pair
    return round(frontage_m * depth_m, 1)


# ═══════════════════════════════════════════════════════════════════
# 2. DIỆN TÍCH TỔNG
# ═══════════════════════════════════════════════════════════════════

def extract_area(text: str) -> Optional[float]:
    """
    Trả về m².
    Patterns:
      "1.826 m²" → 1826.0
      "110m2" → 110.0
      "4x20m" → 80.0  (tính diện tích từ kích thước)
      "DT: 5x18 = 90m²" → 90.0
      "124 m²" → 124.0
    Tránh nhầm với thổ cư: luôn loại trừ context "thổ cư / TC" ngay trước số.
    """
    t = unicodedata.normalize("NFKC", text or "").replace('\n', ' ')

    # Bước 0: Loại bỏ phần "thổ cư Xm²" / "TC Xm²" khỏi text trước khi parse
    # để tránh nhầm thổ cư với tổng DT
    t_clean = re.sub(
        r'(?:thổ\s*cư|tc|thổ)\s*[\d]+[,.]?[\d]*\s*(?:m[²2]?|mv)?',
        '', t, flags=re.IGNORECASE
    )
    t_clean = re.sub(
        r'[\d]+[,.]?[\d]*\s*(?:m[²2]?|mv)\s*(?:thổ\s*cư|tho\s*cu|tc)\b',
        '', t_clean, flags=re.IGNORECASE
    )
    t_fold = _ascii_fold(t_clean)

    # Explicit total area beats frontage-depth multiplication when both appear:
    # "15x71m. Tổng 1028m2" should be 1028m², not 1065m².
    m = re.search(r'(?:tong|tong\s*dt|dt\s*tong)[:\s]*([\d]+[,.]?[\d]*)\s*(?:m[²2]?|mv|met\s*vuong)', t_fold, re.IGNORECASE)
    if m:
        val = float(m.group(1).replace(',', '.'))
        if 5 < val < 100000:
            return val

    # Irregular lots often state the measured area after dimensions:
    # "7x38 no hau 9m ~ 309m2" or "9.1 x 30 = 253 met vuong".
    # Trust that declared area over simple frontage-depth multiplication.
    for m in re.finditer(
        r'(?:=|~)\s*([\d]+[,.]?[\d]*)\s*(?:m[²2]?|mv|met\s*vuong)',
        t_fold,
        re.IGNORECASE,
    ):
        context = t_fold[max(0, m.start() - 48):m.start()]
        if re.search(r'(?:[\d]+[,.]?[\d]*\s*[x×\*]\s*[\d]+[,.]?[\d]*|dt|dien\s*tich|tong|ngang)', context):
            val = float(m.group(1).replace(',', '.'))
            if 5 < val < 100000:
                return val

    # "ngang W x dài/sâu D" written in the title should outrank later
    # "thổ cư 60mv" snippets in the description.
    m = re.search(
        r'(?:ngang\s*)?([\d]+[,.]?[\d]*)\s*(?:m\s*)?(?:x\s*)?(?:dai|sau)\s*([\d]+[,.]?[\d]*)',
        t_fold,
        re.IGNORECASE,
    )
    if m:
        w = float(m.group(1).replace(',', '.'))
        d = float(m.group(2).replace(',', '.'))
        if 2 <= w <= 50 and 5 <= d <= 500:
            return round(w * d, 1)

    # Ưu tiên 0: Phát hiện kích thước có m2 ở số đầu (môi giới ghi nhầm)
    # Ví dụ: "9m2 x 12.6m" -> 113.4 m2 thay vì 9.0 m2
    m_bug = re.search(r'\b([\d]+[,.]?[\d]*)\s*m[²2]\s*[x×]\s*([\d]+[,.]?[\d]*)\s*m?\b', t_clean, re.IGNORECASE)
    if m_bug:
        w = float(m_bug.group(1).replace(',', '.'))
        d = float(m_bug.group(2).replace(',', '.'))
        if 2 <= w <= 50 and 5 <= d <= 500:
            return round(w * d, 1)

    # Ưu tiên 1: "= Xm²" sau kích thước "DT: 5x18 = 90m²"
    m = re.search(r'=\s*([\d]+[,.]?[\d]*)\s*m[²2]', t_clean, re.IGNORECASE)
    if m:
        val = float(m.group(1).replace(',', '.'))
        if 5 < val < 100000:
            return val

    # Ưu tiên 2: "DT X m²" / "diện tích X m²"
    m = re.search(r'(?:dt|diện tích|tổng dt)[:\s]*([\d]+[,.]?[\d]*)\s*m[²2]', t_clean, re.IGNORECASE)
    if m:
        raw = m.group(1).replace(',', '.')
        val = float(raw)
        if 5 < val < 100000:
            return val

    # Ưu tiên 2b: "DT X mét" / "diện tích X mét" — FB hay dùng "mét" thay m²
    m = re.search(r'(?:dt|diện tích)[:\s]*([\d]+[,.]?[\d]*)\s*m[eé]t\b', t_clean, re.IGNORECASE)
    if m:
        val = float(m.group(1).replace(',', '.'))
        if 5 < val < 10000:
            return val

    # Ưu tiên 2c: "DT X mv" / "Xmv" — "mv" = mét vuông (FB môi giới dùng)
    m = re.search(r'(?:dt|diện tích)[:\s]*([\d]+[,.]?[\d]*)\s*mv\b', t_clean, re.IGNORECASE)
    if m:
        val = float(m.group(1).replace(',', '.'))
        if 5 < val < 10000:
            return val
    m = re.search(r'\b([\d]+[,.]?[\d]*)\s*mv\b', t_clean, re.IGNORECASE)
    if m:
        val = float(m.group(1).replace(',', '.'))
        if 5 < val < 10000:
            return val

    # Ưu tiên 2d: "Dt W dài D" → W × D (ví dụ "Dt : 4 dài 30" = 120m²)
    m = re.search(r'(?:dt|diện tích)[:\s]*([\d]+[,.]?[\d]*)\s*(?:m\s*)?dài\s*([\d]+[,.]?[\d]*)', t_clean, re.IGNORECASE)
    if m:
        w = float(m.group(1).replace(',', '.'))
        d = float(m.group(2).replace(',', '.'))
        if 2 <= w <= 50 and 5 <= d <= 500:
            return round(w * d, 1)

    # Bare "W dai D" / "W sau D" without "DT" prefix.
    # Example: "4 dài 28 tc 60" -> 112m².
    m = re.search(r'(?<![/\d])([\d]+[,.]?[\d]*)\s*(?:m\s*)?(?:dai|sau)\s*([\d]+[,.]?[\d]*)', t_fold, re.IGNORECASE)
    if m:
        w = float(m.group(1).replace(',', '.'))
        d = float(m.group(2).replace(',', '.'))
        if 2 <= w <= 50 and 5 <= d <= 500:
            return round(w * d, 1)

    # Ưu tiên 2e: "Dt W*D" — dấu * thay cho x (ví dụ "Dt:4,7*21,5" = 101m²)
    m = re.search(r'(?:dt|diện tích)[:\s]*([\d]+[,.]?[\d]*)\s*\*\s*([\d]+[,.]?[\d]*)', t_clean, re.IGNORECASE)
    if m:
        w = float(m.group(1).replace(',', '.'))
        d = float(m.group(2).replace(',', '.'))
        if 2 <= w <= 50 and 5 <= d <= 500:
            return round(w * d, 1)

    # Ưu tiên 2f: "Dt W m x D" — mét sau chiều rộng (ví dụ "Dt 7,9m x 27" = 213m²)
    for m in re.finditer(r'(?:dt|diện tích)[:\s]*([\d]+[,.]?[\d]*)\s*m\s*[x×]\s*([\d]+[,.]?[\d]*)', t_clean, re.IGNORECASE):
        w = float(m.group(1).replace(',', '.'))
        d = float(m.group(2).replace(',', '.'))
        if 2 <= w <= 50 and 5 <= d <= 500:
            return round(w * d, 1)

    # Ưu tiên 2g: "DT Xm" (single m trong context DT, ví dụ "diện tích:334m" hay "DT 68.9m")
    m = re.search(r'(?:dt|diện tích)[:\s]*([\d]+[,.]?[\d]*)\s*m\b(?!²|2)', t_clean, re.IGNORECASE)
    if m:
        val = float(m.group(1).replace(',', '.'))
        if 5 < val < 10000:
            return val

    # Ưu tiên 3: dấu phân cách hàng nghìn kiểu VN:
    #   "1.826 m²"   → 1826   (dấu chấm hàng nghìn)
    #   "2.546,3 m²" → 2546.3 (chấm hàng nghìn + phẩy thập phân)
    m = re.search(r'([\d]{1,3}(?:\.\d{3})+(?:,\d+)?)\s*m[²2]', t_clean, re.IGNORECASE)
    if m:
        raw = m.group(1).replace('.', '').replace(',', '.')
        return float(raw)

    # Ưu tiên 4: tính từ kích thước "DT: 5x20m" hoặc "diện tích: 5 x 20m"
    # (trước khi fallback sang m² tự do, tránh nhầm road_width)
    m = re.search(r'(?:dt|diện tích)[:\s]*([\d]+[,.]?[\d]*)\s*[x×]\s*([\d]+[,.]?[\d]*)', t_clean, re.IGNORECASE)
    if m:
        w = float(m.group(1).replace(',', '.'))
        d = float(m.group(2).replace(',', '.'))
        if 2 <= w <= 50 and 5 <= d <= 500:
            return round(w * d, 1)

    # Bare "Wm x Dm", "W x D", or "W*D" variants.
    # Keep this before the free Xm2 fallback so "9.5m x 29m" is not read as 9.5m2.
    area = _first_valid_dimension_area(t_clean)
    if area is not None:
        return area

    # Facebook shorthand: "5x37tc 60" means 5m x 37m, then 60m2 thổ cư.
    area = _first_valid_dimension_area(t)
    if area is not None and re.search(r'[x×\*]\s*[\d]+[,.]?[\d]*\s*(?:tc|tho\s*cu)', _ascii_fold(t)):
        return area

    # Pattern thông thường "Xm²" — dùng t_clean để loại thổ cư
    m = re.search(r'([\d]+[,.]?[\d]*)\s*m[²2]', t_clean, re.IGNORECASE)
    if m:
        val = float(m.group(1).replace(',', '.'))
        if val > 5 and val < 100000:
            return val

    # Fallback: tính từ kích thước tự do "4x20", "5 x 18"
    return _first_valid_dimension_area(t_clean)


# ═══════════════════════════════════════════════════════════════════
# 3. GIÁ / M²
# ═══════════════════════════════════════════════════════════════════

_MULTI_LOT_LABEL_RE = re.compile(r'\blo\s*(?:so\s*)?\d{1,2}\b', re.IGNORECASE)
_MULTI_LOT_AREA_RE = re.compile(
    r'\b\d{2,5}(?:[,.]\d+)?\s*m2\b|'
    r'\b\d{1,3}(?:[,.]\d+)?\s*[x×]\s*\d{1,3}(?:[,.]\d+)?\s*m?\b',
    re.IGNORECASE,
)
_MULTI_LOT_PRICE_RE = re.compile(
    r'\b\d{1,3}(?:[,.]\d{1,3})?\s*(?:ty|ti)\b|'
    r'\b\d{1,3}\s*t\s*\d{1,3}\b|'
    r'\b\d{3,4}\s*(?:tr|trieu)\b',
    re.IGNORECASE,
)
_MULTI_LOT_COUNT_RE = re.compile(
    r'\b(?:co\s*)?[2-9]\d?\s+lo\s+(?:lien\s+ke|dat|nen)\b|'
    r'\b(?:ban\s+)?le\s+tung\s+lo\b',
    re.IGNORECASE,
)
_MULTI_LOT_PER_LOT_PRICE_RE = re.compile(
    r'\b(?:gia|gia\s+ban)?\s*[:：-]?\s*'
    r'\d{1,3}(?:\s*(?:ty|ti)\s*\d{1,3}|[,.]\d{1,3}\s*(?:ty|ti)|\s*(?:ty|ti))'
    r'\s*/\s*lo\b',
    re.IGNORECASE,
)


def is_multi_lot_listing(title: str, description: str = "") -> bool:
    """Detect posts that advertise multiple lots with separate area/price pairs."""
    text = _ascii_fold(" ".join(part for part in [title, description] if part))
    text = text.replace("đ", "d").replace("Đ", "d")
    if (
        _MULTI_LOT_COUNT_RE.search(text)
        and _MULTI_LOT_AREA_RE.search(text)
        and (_MULTI_LOT_PER_LOT_PRICE_RE.search(text) or _MULTI_LOT_PRICE_RE.search(text))
    ):
        return True

    labels = list(_MULTI_LOT_LABEL_RE.finditer(text))
    if len(labels) < 2:
        return False

    offer_like_chunks = 0
    for idx, match in enumerate(labels):
        next_start = labels[idx + 1].start() if idx + 1 < len(labels) else len(text)
        chunk = text[match.start():next_start]
        if _MULTI_LOT_AREA_RE.search(chunk) and _MULTI_LOT_PRICE_RE.search(chunk):
            offer_like_chunks += 1

    if offer_like_chunks >= 2:
        return True

    return (
        len(_MULTI_LOT_AREA_RE.findall(text)) >= 2
        and len(_MULTI_LOT_PRICE_RE.findall(text)) >= 2
    )


def extract_price_per_m2(text: str) -> Optional[float]:
    """
    Trả về triệu VND/m².
    Patterns:
      "6,85 tr/m²" → 6.85
      "8 tr/m²" → 8.0
      "13,63 tr/m²" → 13.63
      "66tr/1m" → 66.0 (giá/m ngang — khác!)
    """
    t = unicodedata.normalize("NFKC", text or "").lower()

    # tr/m² hoặc triệu/m²
    m = re.search(r'([\d]+[,.]?[\d]*)\s*tr(?:iệu)?[/\s]*m[²2]', t)
    if m:
        return float(m.group(1).replace(',', '.'))

    # Tính lại nếu có giá tổng và diện tích
    return None


# ═══════════════════════════════════════════════════════════════════
# 4. KÍCH THƯỚC (NGANG × SÂU)
# ═══════════════════════════════════════════════════════════════════

def extract_dimensions(text: str) -> Dict[str, Optional[float]]:
    """
    Trả về dict {frontage_m, depth_m}.
    Patterns thực tế:
      "ngang 22.5m sâu 82m"
      "4x34" / "4 x 34"
      "ngang 4m, dài 20m"
      "MT nở hậu 19,5m" → nở hậu (mặt tiền)
      "5x25 (nở hậu)"
      "DT:4x34 =138m2"
    """
    t = unicodedata.normalize("NFKC", text or "").lower().replace('\n', ' ')
    t_fold = _ascii_fold(t)
    result = {'frontage_m': None, 'depth_m': None}

    # "ngang 7m x dài 21m" / "ngang 7m x sâu 21m"
    m = re.search(r'ngang\s*([\d]+[,.]?[\d]*)\s*(?:m\s*)?(?:x\s*)?(?:dai|sau)\s*([\d]+[,.]?[\d]*)', t_fold)
    if m:
        result['frontage_m'] = float(m.group(1).replace(',', '.'))
        result['depth_m'] = float(m.group(2).replace(',', '.'))
        return result

    # "ngang X sâu Y" / "ngang X dài Y"
    m = re.search(r'ngang\s*([\d]+[,.]?[\d]*)\s*(?:m\b)?\s*(?:,|sâu|dài|x)\s*([\d]+[,.]?[\d]*)', t)
    if m:
        result['frontage_m'] = float(m.group(1).replace(',', '.'))
        result['depth_m'] = float(m.group(2).replace(',', '.'))
        return result

    # Bare "W dài D" / "W sâu D" without "ngang" or "DT" prefix.
    m = re.search(r'(?<![/\d])([\d]+[,.]?[\d]*)\s*(?:m\s*)?(?:dai|sau)\s*([\d]+[,.]?[\d]*)', t_fold)
    if m:
        w = float(m.group(1).replace(',', '.'))
        d = float(m.group(2).replace(',', '.'))
        if 2 <= w <= 50 and 5 <= d <= 500:
            result['frontage_m'] = w
            result['depth_m'] = d
            return result

    # "9m2 x 12.6m" is a common broker typo for "9m x 12.6m".
    m = re.search(r'\b([\d]+[,.]?[\d]*)\s*m[²2]\s*[x×]\s*([\d]+[,.]?[\d]*)\s*m?\b', t, re.IGNORECASE)
    if m:
        w = float(m.group(1).replace(',', '.'))
        d = float(m.group(2).replace(',', '.'))
        if 2 <= w <= 50 and 5 <= d <= 500:
            result['frontage_m'] = w
            result['depth_m'] = d
            return result

    # "XxY", "Xm x Ym", or "X*Y" variants.
    pair = _first_valid_dimension_pair(t)
    if pair:
        w, d = pair
        result['frontage_m'] = w
        result['depth_m'] = d
        return result

    # "ngang Xm" / "mặt tiền Xm" / "mt Xm"
    m = re.search(r'(?:ngang|mặt tiền|mt)\s*([\d]+[,.]?[\d]*)\s*m\b', t)
    if m:
        result['frontage_m'] = float(m.group(1).replace(',', '.'))

    return result


# ═══════════════════════════════════════════════════════════════════
# 5. THỔ CƯ
# ═══════════════════════════════════════════════════════════════════

def extract_tho_cu(text: str, total_area: Optional[float] = None) -> Dict[str, Optional[float]]:
    """
    Trả về {tho_cu_m2, tho_cu_ratio}.
    Patterns:
      "300m² thổ cư" → tho_cu_m2=300
      "thổ cư 60m²" → 60
      "TC 35m" → 35
      "TC full" / "full thổ" / "100% thổ cư" → ratio=1.0
      "thổ cư 88m2, đất vườn 50m2"
    """
    t = unicodedata.normalize("NFKC", text or "").lower()
    folded = _ascii_fold(t)
    result = {'tho_cu_m2': None, 'tho_cu_ratio': None}

    if re.search(
        r'(?:'
        r'full\s*tho|tho\s*(?:cu\s*)?full|tc\s*full|'
        r'100(?:[,.]0+)?\s*%\s*(?:tho\s*cu|tho|tc)|'
        r'(?:tho\s*cu|tho|tc)\s*[:：]?\s*100(?:[,.]0+)?\s*%'
        r')',
        folded,
    ):
        result['tho_cu_ratio'] = 1.0
        if total_area:
            result['tho_cu_m2'] = total_area
        return result

    label_matches = []
    for m in re.finditer(
        r'(?:tho\s*cu|tc)\s*[:：]?\s*([\d]+[,.]?[\d]*)(?!\s*%)(?:\s*(m[²2]?|mv))?',
        folded,
    ):
        val = float(m.group(1).replace(',', '.'))
        if 5 <= val <= 10000:
            label_matches.append((bool(m.group(2)), val))
    if label_matches:
        _, val = next((item for item in label_matches if item[0]), label_matches[0])
        result['tho_cu_m2'] = val
        if total_area and total_area > 0:
            result['tho_cu_ratio'] = round(val / total_area, 3)
        return result

    for m in re.finditer(
        r'([\d]+[,.]?[\d]*)\s*(?:m[²2]?|mv)\s*(?:tho\s*cu|tc)\b',
        folded,
        re.IGNORECASE,
    ):
        val = float(m.group(1).replace(',', '.'))
        if 5 <= val <= 10000:
            result['tho_cu_m2'] = val
            if total_area and total_area > 0:
                result['tho_cu_ratio'] = round(val / total_area, 3)
            return result

    for pat in (
        r'(?:tho\s*cu|tc)\s*[:：]?\s*([\d]+[,.]?[\d]*)(?!\s*%)(?:\s*(?:m[²2]?|mv))?',
    ):
        m = re.search(pat, folded)
        if m:
            val = float(m.group(1).replace(',', '.'))
            if 5 <= val <= 10000:
                result['tho_cu_m2'] = val
                if total_area and total_area > 0:
                    result['tho_cu_ratio'] = round(val / total_area, 3)
                return result

    # "full thổ" / "TC full" / "100% thổ cư"
    if re.search(r'(?:full\s*thổ|tc\s*full|100%?\s*thổ)', t):
        result['tho_cu_ratio'] = 1.0
        if total_area:
            result['tho_cu_m2'] = total_area
        return result

    # "Xm² thổ cư" hoặc "thổ cư Xm²" hoặc "TC Xm" hoặc "TC 35m"
    patterns = [
        r'([\d]+[,.]?[\d]*)\s*m[²2]\s*thổ\s*cư',           # "60m² thổ cư"
        r'thổ\s*cư\s*[:：]?\s*([\d]+[,.]?[\d]*)(?:\s*(?:m[²2]?|mv))?',      # "thổ cư 60m²" hoặc "thổ cư 60"
        r'\btc\s*[:：]?\s*([\d]+[,.]?[\d]*)(?:\s*(?:m[²2]?|mv))?',          # "TC 60m²" hoặc "TC 60"
        r'([\d]+[,.]?[\d]*)\s*m\s*(?:tc|thổ\s*cư)\b',       # "35m TC"
    ]
    for pat in patterns:
        m = re.search(pat, t)
        if m:
            val = float(m.group(1).replace(',', '.'))
            if 5 <= val <= 10000:
                result['tho_cu_m2'] = val
                if total_area and total_area > 0:
                    result['tho_cu_ratio'] = round(val / total_area, 3)
                return result

    return result


# ═══════════════════════════════════════════════════════════════════
# 6. LỘ GIỚI ĐƯỜNG (ROAD WIDTH)
# ═══════════════════════════════════════════════════════════════════

def extract_road_width(text: str) -> Optional[float]:
    """
    Trả về lộ giới đường (m).
    Patterns:
      "đường nhựa rộng 7m" → 7.0
      "đường 12m" → 12.0
      "lộ giới 22m" → 22.0
      "đường bê tông 4m" → 4.0
      "đường nhựa lớn 22m thông" → 22.0
    """
    t = text.lower()

    patterns = [
        r'lộ\s*giới\s*([\d]+[,.]?[\d]*)\s*m',
        r'đường\s*(?:nhựa|bê\s*tông|đất|liên\s*xã|nội\s*bộ)?(?:\s*rộng)?\s*([\d]+[,.]?[\d]*)\s*m',
        r'rộng\s*([\d]+[,.]?[\d]*)\s*m\b',
    ]
    for pat in patterns:
        m = re.search(pat, t)
        if m:
            val = float(m.group(1).replace(',', '.'))
            if 2 <= val <= 60:  # lộ giới hợp lý
                return val
    return None


# ═══════════════════════════════════════════════════════════════════
# 7. LOẠI ĐƯỜNG & ROAD TIER
# ═══════════════════════════════════════════════════════════════════

def extract_road_type(text: str) -> str:
    """Trả về canonical road_type."""
    normalized = unicodedata.normalize("NFKC", text or "")
    t = normalized.lower()
    folded = _ascii_fold(normalized)
    if re.search(r'(?:^|\b)(?:dat|nha|ban)?\s*\d+\s*/\s*[a-z]', folded[:500]):
        return 'be_tong'
    if re.search(r'(?:duong|hem|ngo|loi)\s*(?:ba|3)\s*gac|(?:ba|3)\s*gac', folded):
        return 'hem_ba_gac'
    if re.search(r'xe\s*may|hem\s*nho|duong\s*nho\s*hep', folded):
        return 'hem_xe_may'
    if re.search(r'(?:duong|hem)\s*(?:oto|o\s*to|xe\s*hoi)|(?:oto|o\s*to|xe\s*hoi)\s*(?:vao|toi|den|thong)', folded):
        return 'hem_xe_hoi'
    if re.search(r'\b(?:cach|gan)\s+(?:duong\s+)?nhua\b', folded):
        return 'unknown'
    if 'nhựa' in t or 'nhua' in folded or 'asphalt' in folded:
        return 'duong_nhua'
    if 'bê tông' in t or 'be tong' in folded or 'betong' in folded:
        return 'be_tong'
    if 'đường đất' in t or 'duong dat' in folded or 'dat hien huu' in folded:
        return 'duong_dat'
    return 'unknown'


# ── Road Tier ────────────────────────────────────────────────────────
# Tier 1 — Mặt tiền đường có tên (lộ giới phân biệt sau khi có đủ data)
# Tier 2 — Mặt tiền đường DX / đường nhựa
# Tier 3 — Đường hẻm/bê tông ≥5m (ô tô thoải mái) + hẻm default (no width info)
# Tier 4 — Đường hẻm/bê tông 3–5m (ô tô khó)
# Tier 5 — Đường hẻm/bê tông <3m (xe máy)
# 0     — Không rõ (neutral, không điều chỉnh fair value)
# ─────────────────────────────────────────────────────────────────────

# Whitelist đường có tên tại Tân An / Thủ Dầu Một (từ data thực tế)
# Cập nhật thêm khi có thêm data hoặc khi user confirm
# QL13 bị loại trừ: commercial, không so sánh chung với đất ở
_NAMED_ROADS = [
    # --- Tân An / TBH (original 14) ---
    'lê chí dân', 'mạc đĩnh chi', 'phan đăng lưu', 'nguyễn thị hiếu',
    'hồ văn cống', 'huỳnh thị hiếu', 'võ cái', 'nguyễn tri phương',
    'trần văn ơn', 'đinh bộ lĩnh', 'hùng vương', 'trần hưng đạo',
    'lê hồng phong', 'cách mạng tháng 8',
    # --- Mở rộng TDM (from data analysis 2026-05-06) ---
    'phạm ngọc thạch', 'nguyễn chí thanh', 'huỳnh văn luỹ', 'huỳnh văn lũy',
    'nguyễn đức thuận', 'bùi quốc khánh', 'bùi ngọc thu',
    'mỹ phước tân vạn', 'đại lộ bình dương',
    'tạo lực', 'trần ngọc lên', 'thích quảng đức',
    'nguyễn thị minh khai', 'nguyễn văn trỗi', 'võ văn kiệt',
    'lào cai', 'phạm thị tân', 'nguyễn văn linh', 'ngô gia tự',
    'nguyễn hữu cảnh', 'trần bình trọng', 'nguyễn thái bình',
    'nguyễn văn tiết', 'tô vĩnh diện', 'nguyễn bình',
    'yersin', 'bạch đằng', 'lý thường kiệt',
    # --- Bổ sung TDM (2026-05-07) ---
    'lê lợi', 'nguyễn trãi', 'chu văn an', 'nguyễn du', 'phan bội châu',
    'ngô quyền', 'đinh tiên hoàng', 'hoàng văn thụ', 'nguyễn an ninh',
    'trần phú', 'lạc long quân', 'tô hiệu', 'nguyễn thái học',
    # KHÔNG thêm QL13 — commercial, không so sánh chung với đất ở
]

# Regex bê tông/hẻm + số mét
_BT_WIDTH_RE = re.compile(
    r'(?:bê\s*tông|be\s*tong|hẻm|hem|đường\s*hẻm|duong\s*hem|ngõ|ngo)\s*'
    r'(?:(?:xe\s*hơi|ô\s*tô|ôtô|oto|thông|bê\s*tông|be\s*tong|rộng)\s*)?'
    r'(?:rộng\s*)?(\d+(?:[,.]\d+)?)\s*m\b',
    re.IGNORECASE
)

# Regex lộ giới đường — bắt "lộ giới 8m", "lộ 6m", "đường nhựa 6m", "MT 30m", "mặt tiền 6m"
# Logic giá trị: dùng để infer Tier 2 khi có width mặt đường rõ ràng
_ROAD_WIDTH_RE = re.compile(
    r'(?:lộ(?:\s*giới)?|lo(?:\s*gioi)?|mặt\s*tiền|mat\s*tien|\bmt\b|'
    r'đường(?:\s*(?:nhựa|bê\s*tông))?|duong(?:\s*(?:nhua|be\s*tong))?)'
    r'\s*(?:rộng\s*)?(\d+(?:[,.]\d+)?)\s*m\b',
    re.IGNORECASE
)

# Broker typo: "đường 4m2" often means road width 4m, not 4m² area.
_ROAD_WIDTH_M2_TYPO_RE = re.compile(
    r'(?:đường|duong|hẻm|hem|ngõ|ngo|lộ|lo)\s*(?:rộng\s*)?(\d+(?:[,.]\d+)?)\s*m2\b',
    re.IGNORECASE,
)

# Chuẩn hóa biến thể ô tô (thiếu dấu, liền chữ)
_AUTO_RE = re.compile(r'(?:ô\s*tô|ôtô|oto|xe\s*hơi|xe\s*tải)', re.IGNORECASE)
_AUTO_ROAD_RE = re.compile(
    r'(?:đường|duong|hẻm|hem|ngõ|ngo|lối|loi)\s*[^,.;\n]{0,25}'
    r'(?:ô\s*tô|ôtô|oto|xe\s*hơi|xe\s*tải)|'
    r'(?:ô\s*tô|ôtô|oto|xe\s*hơi|xe\s*tải)\s*[^,.;\n]{0,25}'
    r'(?:vào|tới|đến|ra\s*vào|thông)\s*(?:đất|nhà|cửa)?',
    re.IGNORECASE,
)

# DX road pattern
_DX_RE = re.compile(r'\bdx\s*\d{2,3}\b', re.IGNORECASE)

# Chỉ dấu "không phải mặt tiền chính" — áp cho cả DX và đường nhựa.
# (User feedback: "nhánh DX là tier 3", "gần DX65 chứ k phải thuộc DX65",
#                 "1 xẹt đường nhựa thuộc tier 3", "cách DX 30m")
# Tín hiệu "nhánh/xẹt/xẹc" — chắc chắn không phải mặt đường chính (vị trí bất kỳ)
# xẹc/xẹt = variant cách viết của "1 block off" trong BĐS miền Nam
_NHANH_XEET_RE = re.compile(
    r'\bnhánh\b|\bnhanh\s+(?:\d+|đường|duong|dx\d*|hẻm|hem)\b|\bx[ẹe][ct]\b|1\s*x[ẹe][ct]',
    re.IGNORECASE,
)
# Tín hiệu "gần/cách" — chỉ có ý nghĩa khi nằm TRƯỚC DX/đường.
# "gần DX65" = không trên DX → tier 3. "DX25 gần chợ" = trên DX, gần chợ → tier 2.
_GAN_CACH_RE = re.compile(r'\bg[ầa]n\b|\bc[áa]ch\b', re.IGNORECASE)

# "Sân ô tô / chỗ đậu ô tô" = vị trí đậu xe TRONG nhà, KHÔNG phải đường vào.
# (User feedback: "sân ô tô chứ không phải đường ô tô")
_SAN_AUTO_RE = re.compile(
    r'sân\s*(?:ô\s*tô|ôtô|oto|xe\s*hơi)|chỗ\s*(?:đậu|đỗ)\s*(?:ô\s*tô|ôtô|oto|xe\s*hơi)',
    re.IGNORECASE,
)

# Hẻm/đường quá nhỏ: ba gác/xe máy.
_SMALL_ACCESS_RE = re.compile(
    r'(?:đường|duong|hẻm|hem|ngõ|ngo|lối|loi)\s*(?:xe\s*)?(?:ba|3)\s*gác|'
    r'(?:xe\s*)?(?:ba|3)\s*gác\s*(?:vào|tới|đến|ra\s*vào)?|'
    r'(?:xe\s*máy|xe\s*may|hẻm\s*nhỏ|hem\s*nho|đường\s*nhỏ\s*hẹp|duong\s*nho\s*hep)',
    re.IGNORECASE,
)

# Có đường/hẻm thông nhưng không rõ bề rộng/chất liệu: xem như hẻm/đường nội bộ cần kiểm tra.
_ROAD_THONG_RE = re.compile(
    r'(?:đường|duong|hẻm|hem|ngõ|ngo)\s+thông(?:\s+(?:tứ|tu|4)\s+hướng|\s+dài)?',
    re.IGNORECASE,
)

# Tín hiệu mặt tiền — dùng raw pattern để \b là word boundary (không phải backspace)
_MT_RE = re.compile(r'mặt tiền|mat tien|mặt phố|mat pho|mặt đường|mat duong|\bmt\b', re.IGNORECASE)

# "Mặt lộ" / "tiếp giáp đường" — Tier 2 signals bị thiếu trong cascade cũ
_MAT_LO_RE = re.compile(
    r'mặt\s*lộ|mat\s*lo|tiếp\s*giáp\s*đường|tiep\s*giap\s*duong|'
    r'sát\s*đường\s*(?:lớn|chính|nhựa)|sat\s*duong\s*(?:lon|chinh|nhua)',
    re.IGNORECASE,
)

# "Đường số X" — đường địa phương đánh số (Bình Dương), thường là Tier 2
_DUONG_SO_RE = re.compile(r'(?:đường|duong)\s*(?:số|so)\s*\d+', re.IGNORECASE)

# Mỹ Phước/KCN grid road codes that brokers often write as "đường TC 1A", "đường DB6".
_MP_CODED_ROAD_RE = re.compile(
    r'(?:đường|duong)\s+(?:tc|db|dh|dha|da|dl|dj|ni|ng|nh|ne|de|na)\s*[\da-z]+\b',
    re.IGNORECASE,
)

_HEM_RE = re.compile(r'\b(?:hẻm|hem|hẽm|ngõ|ngo)\b', re.IGNORECASE)


def extract_road_tier(title: str, description: str = '') -> int:
    """
    Phân loại đường thành 4 tier cho mục đích định giá.

    Returns:
        0 — không rõ (neutral, treat như Tier 2 — không apply multiplier)
        1 — Mặt tiền đường có tên (Lê Chí Dân, Nguyễn Thị Hiếu...) — 2x DX
        2 — Đường DX / đường nhựa — baseline (= median)
        3 — Hẻm bê tông xe hơi vào được (>3m)
        4 — Hẻm xe máy (<3m)

    Calibration (từ user):
        Đường tên ≥ 2× đường DX
        Đường nhựa/DX ≥ 2× hẻm base
        Ngưỡng phân biệt: 3m (xe hơi vào được hay không)
        QL13 → KHÔNG phân Tier 1 (commercial, bỏ qua)

    Cascade (ưu tiên từ trên xuống):
        1. Tên đường whitelist + mặt tiền → Tier 1
        2. DX (bất kể MT hay không) → Tier 2
        3. Mặt tiền đường nhựa (không hẻm context) → Tier 2
        4. Đường nhựa thông thường (không hẻm context) → Tier 2
        5. Parse width "bê tông/hẻm Xm": ≥3m → Tier 3, <3m → Tier 4
        6. Keyword ô tô/xe tải không có width → Tier 3
        7. Keyword hẻm/ngõ không có width → Tier 3 (default xe hơi vào được)
        8. Xe máy / hẻm nhỏ → Tier 4
        9. Không có tín hiệu → 0 (neutral)
    """
    text = unicodedata.normalize("NFKC", title + ' ' + (description or '')).lower()
    title_lower = unicodedata.normalize("NFKC", title or "").lower()
    text_fold = _ascii_fold(text)
    title_fold = _ascii_fold(title_lower)
    has_mt   = bool(_MT_RE.search(text))
    has_hem  = bool(_HEM_RE.search(text))
    has_auto = bool(_AUTO_RE.search(text))
    has_auto_road = bool(_AUTO_ROAD_RE.search(text))
    # Loại false positive: "sân ô tô" / "chỗ đậu ô tô" là chỗ đậu xe trong nhà.
    # Nếu cùng tin có "đường/hẻm oto" riêng thì vẫn giữ tín hiệu đường.
    if has_auto and _SAN_AUTO_RE.search(text) and not has_auto_road:
        has_auto = False
    has_nhua = 'nhựa' in text or 'nhua' in text_fold
    # Logic giá trị: "kinh doanh"/"mtkd" = mặt tiền kinh doanh = đường lớn → Tier 2
    has_kd   = any(kw in text_fold for kw in ['mtkd', 'mt kd', 'kinh doanh', 'mt kinh doanh'])

    # --- Title-specific signals (title authoritative, desc can mention "hẻm" as nearby) ---
    has_mt_title = bool(_MT_RE.search(title_lower))
    has_kd_title = any(kw in title_fold for kw in ['mtkd', 'mt kd', 'kinh doanh'])
    has_hem_title = bool(_HEM_RE.search(title_lower))
    # "nhánh / xẹt / xẹc / N/" trong title = ngõ nhánh, không phải mặt tiền chính
    # N/ = ký hiệu hẻm số N (VD: "2/ Huỳnh Văn Luỹ" = hẻm thứ 2 đường Huỳnh Văn Luỹ)
    has_nhanh_title = bool(re.search(
        r'\bnhánh\b|\bnhanh\s+(?:\d+|đường|duong|dx\d*|hẻm|hem)\b|\bx[ẹe][ct]\b|1\s*x[ẹe][ct]|\b\d+\s*/',
        title_lower, re.IGNORECASE,
    ) or re.search(
        r'\bnhanh\s+(?:\d+|duong|dx\d*|hem)\b|\bx[ee][ct]\b|1\s*x[ee][ct]|\b\d+\s*/',
        title_fold, re.IGNORECASE,
    ))

    # Pre-extract road width (mặt đường) — dùng trong nhiều nhánh logic.
    # "đường 3m" / "đường nhựa 3m" / "lộ giới 8m" → road_width = 3.0 / 8.0
    # Chỉ skip khi TITLE nói hẻm — desc có thể đề cập hẻm gần đó
    road_width = None
    _m_w = _ROAD_WIDTH_RE.search(text) or _ROAD_WIDTH_M2_TYPO_RE.search(text)
    if _m_w and not has_hem_title:
        try:
            _w = float(_m_w.group(1).replace(',', '.'))
            if 1 <= _w <= 60 and not (_m_w.re is _ROAD_WIDTH_M2_TYPO_RE and _w > 12):
                road_width = _w
        except (ValueError, IndexError):
            pass

    # Pre-check nhánh/xẹt trong toàn text — chỉ dấu "đường nhánh" mạnh.
    # "nhánh 114" / "1 xẹt Huỳnh Thị Hiếu" → nên là Tier 3 dù không có width / DX.
    has_nhanh_strong = bool(
        _NHANH_XEET_RE.search(text)
        or re.search(r'(?:^|\D)\d+\s*/\s*[a-z]', text_fold, re.IGNORECASE)
    )
    near_nhua_only = bool(re.search(r'\b(?:cach|gan)\s+(?:duong\s+)?nhua\b', text_fold))

    # --- Đường quy hoạch Mỹ Phước (config-driven) ---
    from config.area_profiles import detect_subward_from_street
    _mp_sw, _mp_width, _mp_tier = detect_subward_from_street(text)
    if _mp_tier is not None:
        return _mp_tier

    if has_nhanh_strong:
        return 3

    # "Đất 1/ Lê Hồng Phong" is a branch/alley address, even if the broker
    # later writes "mặt tiền kinh doanh nhựa"; treat as concrete car alley.
    if has_nhanh_title:
        return 3

    # --- Tier 1: Mặt tiền đường có tên (whitelist) ---
    # _MT_RE đã fix — \bmt\b bây giờ là word boundary đúng (không phải backspace).
    desc_lower = (description or '').lower()

    # Hẻm trong desc CÓ số đo chiều rộng = đường vào thực của property (không phải landmark nearby).
    # Dùng để chặn Tier 2 gate khi title có "mặt tiền" nhưng desc mô tả "hẻm 4m bê tông".
    _has_hem_road_in_desc = bool(_BT_WIDTH_RE.search(desc_lower))

    # PRIMARY: named road trong TITLE + MT (title hoặc desc) + không hẻm/nhánh trong title
    _road_in_title = any(rd in title_lower for rd in _NAMED_ROADS)
    if _road_in_title and not has_hem_title and not has_nhanh_title:
        # Cần tín hiệu MT — loại "cách Nguyễn Chí Thanh 50m" (proximity, không có MT)
        if has_mt_title or has_kd_title or has_mt or has_kd:
            return 1

    # SECONDARY: named road trong DESC + MT trong TITLE + không hẻm anywhere + không DX
    # Bắt các listing mà agent ghi tên đường trong desc (e.g., "NHÀ MẶT TIỀN – Hồ Văn Cống")
    # Điều kiện chặt hơn PRIMARY để tránh false positive từ landmark mentions.
    if not has_hem and not has_nhanh_strong and not _DX_RE.search(text):
        _road_in_desc = any(rd in desc_lower for rd in _NAMED_ROADS)
        if _road_in_desc and not _road_in_title:
            # MT phải có trong TITLE (không chỉ desc) — loại "gần đường XYZ" trong title
            if has_mt_title or has_kd_title:
                return 1

    # --- DX road: default Tier 2 (mặt tiền DX hoặc khẳng định trên DX). ---
    # Down-grade → Tier 3 khi:
    #   a) "nhánh/xẹt" xuất hiện bất kỳ xung quanh DX
    #   b) "gần/cách" xuất hiện TRƯỚC DX (= listing gần DX, không trên DX)
    #   c) "hẻm" xuất hiện TRƯỚC DX trong chuỗi (= hẻm dẫn đến/gần DX)
    # "DX25 gần chợ" = trên DX, gần chợ → vẫn Tier 2.
    m_dx = _DX_RE.search(text)
    if m_dx:
        s, e = m_dx.span()
        around = text[max(0, s - 25):min(len(text), e + 25)]
        before_dx = text[max(0, s - 25):s]
        hem_before = bool(_HEM_RE.search(before_dx))
        if re.search(r'(?:^|\D)\d+\s*/\s*$', before_dx, re.IGNORECASE):
            return 3
        if (_NHANH_XEET_RE.search(around)          # nhánh/xẹt bất kỳ
                or _GAN_CACH_RE.search(before_dx)   # gần/cách TRƯỚC DX
                or hem_before):                     # hẻm TRƯỚC DX
            return 3
        return 2

    # --- Tier 2: Mặt tiền đường nhựa/kinh doanh ---
    # Block bằng has_hem_title + _has_hem_road_in_desc:
    #   has_hem_title: hẻm trong TITLE → không phải mặt tiền đường lớn
    #   _has_hem_road_in_desc: desc có "hẻm Xm" có số đo → đó là đường vào thực, không phải hẻm lân cận
    if (has_mt or has_kd) and has_nhua and not has_hem_title and not _has_hem_road_in_desc:
        if near_nhua_only:
            return 3
        # Nhánh/xẹt đường nhựa → Tier 3 (user: "1 xẹt đường nhựa thuộc tier 3")
        if has_nhanh_strong:
            return 3
        # Đường nhựa hẹp (<5m): hẻm-sized → Tier 3
        if road_width is not None and road_width < 5:
            return 3
        return 2

    # Logic giá trị: MT/MTKD đơn độc (không hẻm title, không hẻm đo được trong desc) → Tier 2
    if (has_mt or has_kd) and not has_hem_title and not _has_hem_road_in_desc:
        return 2

    # --- Tier 2: Đường nhựa thông thường, không hẻm title ---
    if has_nhua and not has_hem_title and not _has_hem_road_in_desc:
        if near_nhua_only:
            return 3
        # Nhánh/xẹt đường nhựa → Tier 3
        if has_nhanh_strong:
            return 3
        # Đường nhựa hẹp (<5m): hẻm-sized → Tier 3 (user: "Đường nhựa 3m ô tô" = tier 3)
        if road_width is not None and road_width < 5:
            return 3
        return 2

    # --- Tier 2: Signals bổ sung (2026-05-07) ---
    # "Mặt lộ" / "tiếp giáp đường" / "sát đường lớn" — viết tắt/biến thể của mặt tiền
    if _MAT_LO_RE.search(text) and not has_hem_title:
        return 2

    # "Đường nội bộ" / "lộ nội bộ" — đường trong KDC, thường rải nhựa
    if any(kw in text for kw in ['đường nội bộ', 'duong noi bo', 'lộ nội bộ', 'lo noi bo', 'nội khu', 'noi khu']) and not has_hem_title:
        return 2

    # "Đường số X" — đường địa phương đánh số (khác DX), thường là đường nhựa Tier 2
    if _DUONG_SO_RE.search(text) and not has_hem_title:
        return 2

    # "Đường TC 1A" / "đường DB6" — mã đường nội khu Mỹ Phước/KCN, thường là đường quy hoạch.
    if _MP_CODED_ROAD_RE.search(text) and not has_hem_title:
        return 2

    # "Lộ giới" không có số đo cụ thể — vẫn là tín hiệu có đường rõ ràng
    if ('lộ giới' in text or 'lo gioi' in text) and not has_hem_title:
        return 2

    # Logic giá trị: lộ giới/đường có width đo được — width quyết định tier.
    # "đường 6m" / "lộ giới 8m" không hẻm + có chỉ dấu mặt tiền/nhựa → Tier 2.
    # "lộ 6m" / "đường 3m" hoặc "đường 4m bê tông" hoặc "nhánh đường 5m" → Tier 3.
    m_road = _ROAD_WIDTH_RE.search(text) or _ROAD_WIDTH_M2_TYPO_RE.search(text)
    if m_road and not has_hem_title:
        try:
            width = float(m_road.group(1).replace(',', '.'))
            if m_road.re is _ROAD_WIDTH_M2_TYPO_RE and width > 12:
                raise ValueError
            if 3 <= width <= 60:      # sanity — loại "300m²", "1500m"
                # Nhánh / xẹt → Tier 3 (đường nhánh nhỏ)
                if _NHANH_XEET_RE.search(text):
                    return 3
                # Đường bê tông (xe hơi vào được nhưng KHÔNG phải đường nhựa lớn) → Tier 3
                if any(kw in text for kw in ['bê tông', 'be tong']):
                    return 3
                # Width nhỏ và KHÔNG có chỉ dấu mặt tiền/nhựa/KD:
                #   3–5m → Tier 3 (xe hơi vào được)
                #   <3m  → Tier 4 (xe máy)
                # (User: "hẻm bê tông <3m mới là tier 4, 3-5m vẫn là tier 3")
                if width < 5 and not has_mt and not has_kd and not has_nhua:
                    return 4 if width < 3 else 3
                return 2
        except (ValueError, IndexError):
            pass

    # --- Parse chiều rộng bê tông/hẻm ---
    m = _BT_WIDTH_RE.search(text)
    if m:
        width = float(m.group(1).replace(',', '.'))
        if width >= 3:
            return 3   # xe hơi vào được
        return 4       # xe máy <3m

    # Ba gác/xe máy/hẻm nhỏ là đường vào hẹp, phải xét trước fallback hẻm default.
    if _SMALL_ACCESS_RE.search(text):
        return 4

    # Bê tông không có width → Tier 3 (default xe hơi vào được).
    # (User: "bê tông thì tier 3 rồi")
    if any(kw in text for kw in ['bê tông', 'be tong', 'btxm', 'bt xi măng']):
        return 3

    # Có chỉ dấu "nhánh / xẹt / 1/" (không cần DX/nhựa kèm) → Tier 3.
    # has_nhanh_title bắt "1/ Hồ Văn Cống" (hẻm ký hiệu theo kiểu địa chỉ VN)
    # (User: "Nhánh 114, hẻm bê tông là tier 3"; "1 xẹt Huỳnh Thị Hiếu là tier 3")
    if has_nhanh_strong or has_nhanh_title:
        return 3

    # Logic giá trị: ô tô/xe tải vào/tới/đậu — bắt thêm variants thiếu (oto/ôtô/xe hơi)
    if has_auto_road:
        return 3
    if (has_auto_road or has_auto) and any(kw in text for kw in [
        'vào', 'thông', 'đi', 'đậu', 'tới', 'đến', 'ra vào', 'đường', 'hẻm'
    ]):
        return 3

    # Đường/hẻm thông nhưng chưa rõ rộng/chất liệu: không nâng lên tier 2, chỉ ghi nhận là đường nội bộ/hẻm.
    if _ROAD_THONG_RE.search(text):
        return 3

    # --- Hẻm/ngõ không có width → Tier 3 (default hẻm ô tô vào được) ---
    if has_hem:
        return 3

    # Logic giá trị: đê bao / bờ kè / đường tỉnh — đường lớn ven sông/ngoại thị → Tier 2
    if any(kw in text for kw in ['đê bao', 'de bao', 'bờ kè', 'bo ke', 'đường tỉnh', 'duong tinh', 'đường liên xã', 'duong lien xa', 'đường liên huyện', 'duong lien huyen']):
        return 2

    # --- Xe máy / hẻm nhỏ → Tier 4 ---
    if _SMALL_ACCESS_RE.search(text):
        return 4

    return 0   # không rõ → neutral (treat như Tier 2, không điều chỉnh fair value)


# ═══════════════════════════════════════════════════════════════════
# 8. PHÁP LÝ
# ═══════════════════════════════════════════════════════════════════

def extract_legal(text: str) -> Dict[str, Any]:
    """
    Patterns:
      "SHR" / "sổ hồng riêng" → shr=True
      "GCN QSDĐ" / "sổ đỏ" → gcn=True
      "chưa có sổ" → no_so=True
      "đang làm sổ" → dang_lam_so=True
    """
    t = _ascii_fold(text)
    dang_lam_so = bool(re.search(r'dang lam so|dang hoan cong|dang cap(?: so)?|dang ra so|cho so', t))
    pending_so = bool(re.search(r'dang lam so|dang cap so|dang ra so|cho so', t))
    no_so = bool(re.search(
        r'chua co so|chua so|khong co so|khong so|vi bang|giay tay|giay viet tay',
        t,
    ) or pending_so)
    return {
        'has_shr':     bool(re.search(r'\bshr\b|so hong rieng', t)),
        'has_gcn':     bool(re.search(r'gcn|qsdd|so do|giay chung nhan', t)),
        'no_so':       no_so,
        'dang_lam_so': dang_lam_so,
        'has_so':      not no_so,  # default True; False chỉ khi ghi rõ không có sổ
    }


# ═══════════════════════════════════════════════════════════════════
# 9. LOẠI TÀI SẢN
# ═══════════════════════════════════════════════════════════════════
# Slug → broad type ("dat" | "nha" | "chung_cu" | "kho_xuong" | None)
# chốt nhánh trước, content refine trong nhánh (dat_nen vs dat_vuon, nha_dat vs nha_tro).
# Facebook (url_hint=None) đi cascade cũ với bổ sung kho_xuong detection.
#
# Thứ tự pattern matter: chung_cu / kho_xuong khớp TRƯỚC dat/nha vì có substring trùng.
# Ví dụ "ban-kho-nha-xuong-" chứa "-nha-" → nếu match "nha" trước sẽ sai.
_URL_HINT_PATTERNS = [
    # BatDongSan
    (re.compile(r'/ban-can-ho-chung-cu-|/ban-can-ho-'),                                       'chung_cu'),
    (re.compile(r'/ban-kho-nha-xuong-|/ban-nha-xuong-|/ban-kho-xuong-'),                      'kho_xuong'),
    (re.compile(r'/ban-dat-dat-nen-|/ban-dat-vuon-|/ban-dat-nong-nghiep-|/ban-dat-tho-cu-'),  'dat'),
    (re.compile(r'/ban-nha-dat-|/nha-dat-ban-|/ban-nha-rieng-|/ban-nha-mat-pho-|/ban-nha-pho-'), 'nha'),
    # Guland
    (re.compile(r'/mua-ban-can-ho-chung-cu-|/mua-ban-can-ho-|/mua-ban-chung-cu-'),            'chung_cu'),
    (re.compile(r'/mua-ban-kho-nha-xuong-|/mua-ban-nha-xuong-|/mua-ban-kho-xuong-'),          'kho_xuong'),
    (re.compile(r'/mua-ban-dat-tho-cu-|/mua-ban-dat-nen-|/mua-ban-dat-vuon-|/mua-ban-dat-nong-nghiep-'), 'dat'),
    (re.compile(r'/mua-ban-nha-mat-pho-|/mua-ban-nha-rieng-|/mua-ban-nha-pho-|/mua-ban-nha-tro-|/mua-ban-phong-tro-'), 'nha'),
]


def extract_url_hint(url: str) -> Optional[str]:
    """Trả 'dat' | 'nha' | 'chung_cu' | 'kho_xuong' | None.

    Dùng broad type encoded trong slug của BDS / Guland làm constraint cho
    `classify_property_type`. Facebook URLs không match → None → cascade cũ.
    """
    if not url:
        return None
    u = url.lower()
    for pat, hint in _URL_HINT_PATTERNS:
        if pat.search(u):
            return hint
    return None


# ═══════════════════════════════════════════════════════════════════
# 3 loại canonical cho Tân An: dat_vuon | dat_nen | nha_dat
#
# Cascade logic (ưu tiên từ trên xuống):
#   1. Keyword cứng vườn/CLN → dat_vuon
#   2. Keyword cứng nhà/công trình → nha_dat
#   3. area > 1000m² + không có nhà → dat_vuon
#   4. Còn lại → dat_nen (default Tân An)
#
# Source label mapping: normalize nhãn từ Guland/BDS về canonical.
# ═══════════════════════════════════════════════════════════════════

# Map nhãn raw từ nguồn → canonical (trước khi chạy cascade)
_SOURCE_LABEL_MAP = {
    # Guland labels
    'đất vườn':     'dat_vuon',
    'đất nền':      'dat_nen',
    'nhà phố':      'nha_dat',   # Guland dùng "Nhà phố" cho cả nhà đất
    'nhà':          'nha_dat',
    'nhà trọ':      'nha_tro',
    # BatDongSan labels
    'Đất nền':      'dat_nen',
    'Đất vườn':     'dat_vuon',
    'Nhà phố':      'nha_dat',
    'Nhà':          'nha_dat',
    'Nhà trọ':      'nha_tro',
    # Legacy extractor labels
    'dat_nen':      'dat_nen',
    'dat_vuon':     'dat_vuon',
    'nha_dat':      'nha_dat',
    'nha_pho':      'nha_dat',
    'nha_cap4':     'nha_dat',
    'nha':          'nha_dat',
    'nha_tro':      'nha_tro',
    'dat_lon':      'dat_vuon',   # đất lớn → vườn (gần nhất)
    # Kho/nhà xưởng — Guland / BDS
    'nhà kho/nhà xưởng': 'kho_xuong',
    'kho, nhà xưởng':    'kho_xuong',
    'kho nhà xưởng':     'kho_xuong',
    'Nhà xưởng':         'kho_xuong',
    'kho xưởng':         'kho_xuong',
    'nhà xưởng':         'kho_xuong',
    'kho_xuong':         'kho_xuong',
    # Chung cư variants
    'Chung cư':          'chung_cu',
    'Căn hộ':            'chung_cu',
    'chung cư':          'chung_cu',
    'căn hộ':            'chung_cu',
    'chung_cu':          'chung_cu',
}

# Keyword hard → dat_vuon (độ tin cậy cao)
_VUON_KW = [
    'đất vườn', 'đất cln', 'đất cây lâu năm', 'đất nông nghiệp',
    'đất rẫy', 'đất trồng', 'ao vườn', 'vườn cây', 'vườn trái cây',
    'đất ruộng', 'đất lúa', 'đất canh tác', 'cây ăn trái',
    'đê sông', 'đất đê', 'đất bãi',
]

# Keyword hard → nha_dat (có công trình trên đất)
_NHA_KW = [
    'bán nhà', 'cần bán nhà', 'chính chủ bán nhà',
    'nhà cấp 4', 'nhà cp4', 'nhà 1 trệt', 'nhà 2 tầng', 'nhà 3 tầng',
    'nhà mới xây', 'nhà mới', 'nhà ở', 'nhà riêng',
    'phòng ngủ', 'wc', 'nhà vệ sinh', 'nhà bếp', 'bếp ăn',
    'sân thượng', 'trệt lầu', 'diện tích xây dựng',
    'nhà mặt tiền', 'nhà kinh doanh',
    'căn nhà', 'ngôi nhà',
    'biệt thự',
]

# Keyword hard → kho_xuong (tách khỏi _NHA_KW vì giá/m² và logic định giá khác hẳn)
_KHO_XUONG_KW = [
    'nhà xưởng', 'kho xưởng', 'nhà kho', 'bán xưởng', 'cho thuê xưởng',
    'xưởng sản xuất', 'xưởng may', 'xưởng gỗ', 'xưởng cơ khí',
    'kcn ', 'khu công nghiệp', 'cụm công nghiệp',
]

# Chung cư content detection — dùng cho cả url_hint=None override
_CHUNG_CU_RE = re.compile(
    r'\bchung\s*cư\b|\bcăn\s*hộ\b|\bbiconsi\b|\bblock\s*[a-z0-9]+\b',
    re.IGNORECASE,
)


def _strip_nearby_chung_cu_context(text: str) -> str:
    """Remove apartment keywords when they describe a nearby landmark, not the asset."""
    folded = _ascii_fold(text).replace("Ä‘", "d").replace("Ä", "d")
    folded = re.sub(
        r'\b(?:gan|sat|canh|ke|doi\s*dien|cach|duong\s*vao)\b.{0,120}'
        r'\b(?:khu\s*do\s*thi|toa\s*nha|block|chung\s*cu|can\s*ho)\b.{0,80}'
        r'\b(?:block|chung\s*cu|can\s*ho)\b',
        ' ',
        folded,
        flags=re.IGNORECASE,
    )
    folded = re.sub(
        r'\b(?:gan|sat|canh|ke|doi\s*dien|cach|duong\s*vao)\b.{0,80}'
        r'\b(?:block|chung\s*cu|can\s*ho|biconsi)\b',
        ' ',
        folded,
        flags=re.IGNORECASE,
    )
    return folded


def _has_chung_cu_keyword(text: str) -> bool:
    folded = _ascii_fold(text).replace("Ä‘", "d").replace("Ä", "d")
    return bool(_CHUNG_CU_RE.search(text) or re.search(
        r'\bchung\s*cu\b|\bcan\s*ho\b|\bbiconsi\b|\bblock\s*[a-z0-9]+\b',
        folded,
        flags=re.IGNORECASE,
    ))


def _is_social_housing_text(text: str) -> bool:
    """Detect NOXH/Becamex social-housing units, not land near that landmark."""
    t = _ascii_fold(text).replace("đ", "d").replace("Đ", "d")
    has_social_kw = bool(re.search(r'\bnha\s*(?:o\s*)?xa\s*hoi\b|\bnoxh\b', t))
    has_becamex_dinh_hoa = bool(re.search(r'\bbecamex\b.{0,40}\bdinh\s*hoa\b|\bdinh\s*hoa\b.{0,40}\bbecamex\b', t))
    has_unit_kw = bool(re.search(
        r'\bcan\s*ho\b|\bchung\s*cu\b|\bblock\s*[a-z0-9]+\b|'
        r'\btang\s*\d+\b|\blau\s*\d+\b|\b\d+\s*pn\b|\bpk\b|\bwc\b|'
        r'\bthang\s*may\b',
        t,
    ))
    has_land_asset_kw = bool(re.search(r'\bdat\b|\blo\s*dat\b|\bdat\s*nen\b|\btho\s*cu\b', t))
    if has_becamex_dinh_hoa and has_land_asset_kw and not has_social_kw and not has_unit_kw:
        return False
    if not (has_social_kw or has_becamex_dinh_hoa):
        return False

    is_land_near_landmark = bool(re.search(
        r'\b(?:dat|lo\s*dat|dat\s*nen|tho\s*cu)\b.{0,40}'
        r'\b(?:gan|sat|canh|ke|doi\s*dien|cach|duong\s*vao)\b.{0,50}'
        r'\b(?:nha\s*(?:o\s*)?xa\s*hoi|noxh|becamex\b.{0,25}dinh\s*hoa)\b',
        t,
    ))
    if is_land_near_landmark and not has_unit_kw:
        return False
    return True


def _is_kho_xuong_text(text: str) -> bool:
    """True nếu nội dung chỉ rõ kho/nhà xưởng (cho Facebook hoặc URL không rõ)."""
    return any(kw in text for kw in _KHO_XUONG_KW)

# Keyword phủ định nhà (dùng để loại false positive nha_dat)
# 2026-05-05: cũng dùng để CHẶN dat_vuon — nếu có keyword này thì là dat_nen, không phải đất nông nghiệp
_LAND_ONLY_KW = [
    'đất trống', 'không có nhà', 'chưa có nhà', 'đất ở',
    'đất thổ cư', 'đất phân lô', 'đất kdc', 'đất khu dân cư',
    'lô đất', 'đất nền',
    # 2026-05-05: thêm signal mặt tiền / kinh doanh — đất vườn không có
    'mặt tiền', 'mt kinh doanh', 'mt đường',
]

# Ngưỡng diện tích: >= 500m² + không có nhà + không phải DX → dat_vuon
_AREA_VUON_THRESHOLD = 500.0

# Ngưỡng thổ cư: ratio < 5% → dat_vuon (gần như toàn bộ CLN)
_THO_CU_VUON_RATIO = 0.05

# Pattern đường DX (đường nhựa nội thị Bình Dương) → KHÔNG phải đất vườn
# VD: "đường dx117", "dx 121", "dx129"
_DX_ROAD_RE = re.compile(r'\bdx\s*\d{2,3}\b')


def _is_dx_road(text: str) -> bool:
    """True nếu tin rao nằm trên đường DX (đường nhựa nội thị Bình Dương)."""
    return bool(_DX_ROAD_RE.search(text))


# Constants used by both classify_property_type và _classify_dat_only
_PRICE_VUON_MAX = 8.0  # triệu/m² — đất nông nghiệp TDM thực tế 1-6, > 8 chắc chắn đô thị


def _classify_dat_only(
    text: str,
    area_m2: Optional[float],
    tho_cu_m2: Optional[float],
    price_per_m2: Optional[float],
    has_land_only_kw: bool,
    raw_source_label: str,
) -> str:
    """Nhánh khi slug đã chốt là 'dat' — chỉ chọn dat_nen / dat_vuon.

    Bỏ qua nha_kw / strong_house. Vẫn áp các blocker (land_only_kw, price,
    DX road, area threshold) để phân biệt dat_nen vs dat_vuon.
    """
    _price_ok = (price_per_m2 is None or price_per_m2 <= _PRICE_VUON_MAX)

    # 1. Keyword vườn/CLN (blocked by land_only_kw / price)
    if any(kw in text for kw in _VUON_KW) and not has_land_only_kw and _price_ok:
        return 'dat_vuon'

    # 2. Thổ cư < 5% — gần như toàn CLN
    if tho_cu_m2 is not None and area_m2 and area_m2 > 0:
        if (tho_cu_m2 / area_m2) < _THO_CU_VUON_RATIO and not has_land_only_kw:
            return 'dat_vuon'

    # 3. Land-only keyword (lô đất, đất nền, mặt tiền) → dat_nen
    if has_land_only_kw:
        return 'dat_nen'

    # 4. Đường DX → đất nền nội thị
    if _is_dx_road(text):
        return 'dat_nen'

    # 5. Area >= 500m² + không DX → dat_vuon (trừ thổ cư cao / giá cao)
    if area_m2 and area_m2 >= _AREA_VUON_THRESHOLD:
        if tho_cu_m2 is not None and area_m2 > 0 and (tho_cu_m2 / area_m2) >= 0.20:
            return 'dat_nen'
        if price_per_m2 is not None and price_per_m2 > _PRICE_VUON_MAX:
            return 'dat_nen'
        return 'dat_vuon'

    # 6. Source label hint (chỉ accept dat_vuon)
    if _SOURCE_LABEL_MAP.get(raw_source_label) == 'dat_vuon':
        return 'dat_vuon'

    # 7. Default — đất đô thị
    return 'dat_nen'


def _has_source_category_land_override(
    text: str,
    area_m2: Optional[float],
    tho_cu_m2: Optional[float],
    url_hint: Optional[str],
) -> bool:
    apartment_text = _strip_nearby_chung_cu_context(text)
    has_conflicting_category = (
        url_hint in {'chung_cu', 'kho_xuong'}
        or _has_chung_cu_keyword(apartment_text)
        or _is_kho_xuong_text(text)
    )
    if not has_conflicting_category:
        return False

    folded = _ascii_fold(text).replace("Ä‘", "d").replace("Ä", "d")
    has_land_asset = bool(re.search(
        r'\b(?:ban\s+)?(?:lo\s+)?dat\b|'
        r'\blo\s+dat\b|'
        r'\bdat\s+(?:nen|vuon|tho\s*cu|nong\s*nghiep|cln|nhanh?)\b|'
        r'\bchua\s*(?:co\s*)?tho\s*cu\b',
        folded,
    ))
    has_land_scale_or_legal = bool(
        (area_m2 and area_m2 >= 300)
        or tho_cu_m2 is not None
        or re.search(r'\bchua\s*(?:co\s*)?tho\s*cu\b|\bcln\b|\bdat\s*nong\s*nghiep\b', folded)
        or re.search(r'\b\d+(?:[,.]\d+)?\s*[x×]\s*\d+(?:[,.]\d+)?\b', folded)
    )
    has_unit_evidence = bool(re.search(
        r'\bblock\s*[a-z0-9]+\b|\btang\s*\d+\b|\blau\s*\d+\b|'
        r'\b\d+\s*pn\b|\b\d+\s*wc\b|\bthang\s*may\b',
        folded,
    ))
    return has_land_asset and has_land_scale_or_legal and not has_unit_evidence


def _has_no_tho_cu_land(text: str) -> bool:
    folded = _ascii_fold(text).replace("Ä‘", "d").replace("Ä", "d")
    return bool(re.search(r'\bchua\s*(?:co\s*)?tho\s*cu\b', folded))


def classify_property_type(
    title: str,
    description: str,
    area_m2: Optional[float] = None,
    tho_cu_m2: Optional[float] = None,
    raw_source_label: str = '',
    price_per_m2: Optional[float] = None,
    url_hint: Optional[str] = None,
) -> str:
    """
    Phân loại 2 tầng: slug → broad type → content refine.

    `url_hint` ('dat' | 'nha' | 'chung_cu' | 'kho_xuong' | None) chốt nhánh:
      - 'chung_cu' / 'kho_xuong'  → short-circuit return ngay
      - 'dat'                      → chỉ chọn dat_nen / dat_vuon (bỏ qua nhánh nhà)
      - 'nha'                      → chỉ chọn nha_dat / nha_tro (bỏ qua nhánh đất)
      - None (Facebook)            → cascade cũ (đầy đủ keyword logic) + kho_xuong fallback

    Trả về một trong 7 giá trị: dat_vuon | dat_nen | nha_dat | nha_tro | chung_cu | kho_xuong | nha_o_xa_hoi.
    """
    text = (title + ' ' + (description or '')).lower().strip()

    # NOXH/Becamex Định Hòa là thị trường căn hộ đặc thù, không so chung với nhà đất.
    if _is_social_housing_text(text):
        return 'nha_o_xa_hoi'

    source_category_land_override = _has_source_category_land_override(
        text, area_m2, tho_cu_m2, url_hint,
    )
    if source_category_land_override and area_m2 and area_m2 >= _AREA_VUON_THRESHOLD and _has_no_tho_cu_land(text):
        return 'dat_vuon'
    if source_category_land_override:
        return _classify_dat_only(
            text, area_m2, tho_cu_m2, price_per_m2,
            any(kw in text for kw in _LAND_ONLY_KW), raw_source_label,
        )

    # ── Bước 0: url_hint short-circuit cho chung_cu / kho_xuong ──
    if url_hint == 'chung_cu':
        return 'chung_cu'
    if url_hint == 'kho_xuong':
        return 'kho_xuong'

    # ── Content override #1: Chung cư trumps mọi nhánh khi nội dung rõ ràng ──
    # (Áp dụng cho mọi url_hint còn lại — kể cả 'dat' / 'nha' / None)
    if _has_chung_cu_keyword(_strip_nearby_chung_cu_context(text)):
        return 'chung_cu'

    # ── Content override #2: Kho/nhà xưởng — chỉ khi url_hint cho phép ──
    # Không ép sang kho_xuong khi URL nói rõ "đất" (slug=dat).
    if url_hint in (None, 'nha') and _is_kho_xuong_text(text):
        return 'kho_xuong'

    # --- Pre-compute flags TRƯỚC tất cả steps ---
    # 2026-05-05: compute sớm để block false-positive dat_vuon từ step 1 (vuon_kw) và
    # step 3 (thổ cư < 5%). VD: mô tả pháp lý "thổ cư 100m², đất trồng cây 309m²" chứa
    # "đất trồng" (vuon_kw) nhưng cũng có "mặt tiền" (land_only_kw) → thực tế là đất nền.
    has_land_only_kw = any(kw in text for kw in _LAND_ONLY_KW)

    # 2026-05-06: Pre-compute has_house_kw TRƯỚC step 1 để block vuon_kw khi listing
    # có BOTH "đất trồng" (vuon) VÀ "nhà cấp 4"/"phòng ngủ"/"trệt lầu" (nhà).
    # VD: "Nhà trệt lầu... đất trồng cây lâu năm" → step 1 cũ fire vuon, bỏ qua nhà.
    # Strip phrase mô tả TIỀM NĂNG xây — không phải có nhà sẵn:
    #   "có thể xây nhà" / "xây được 2 căn nhà" / "tha hồ xây biệt thự" / "đất để xây nhà"
    # (user feedback L#1164: "đất chứ k phải nhà đất (họ ghi có thể xây nhà)").
    text_for_nha = re.sub(
        r'(?:có\s*thể|có\s*thẻ|sẽ|được|phù\s*hợp|thích\s*hợp|tha\s*hồ|đất\s*để|đất\s*dùng\s*để)'
        r'\s*(?:dùng\s*để\s*)?(?:xây|cất|làm)(?:\s*dựng)?\s*'
        r'(?:\d+\s*)?(?:căn\s*|ngôi\s*)?(?:nhà|biệt\s*thự|villa|nhà\s*xưởng)',
        ' ', text, flags=re.IGNORECASE,
    )
    # Pattern "xây đc/được N căn nhà" / "xây 2 căn nhà" — chủ động phía trước
    text_for_nha = re.sub(
        r'(?:xây|cất|làm)(?:\s*dựng)?\s*(?:đc|được|đk)?\s*\d+\s*(?:căn\s*|ngôi\s*)?(?:nhà|biệt\s*thự|villa)',
        ' ', text_for_nha, flags=re.IGNORECASE,
    )
    text_for_nha_ascii = _ascii_fold(text_for_nha).replace("đ", "d").replace("Đ", "d")
    text_for_nha_ascii = re.sub(
        r'\b(?:gan|sat|canh|ke|doi\s*dien|cach|duong\s*vao)\b.{0,50}'
        r'\bnha\s*(?:o\s*)?xa\s*hoi\b',
        ' ', text_for_nha_ascii, flags=re.IGNORECASE,
    )
    text_for_nha_ascii = re.sub(
        r'\b(?:gan|sat|canh|ke|doi\s*dien|cach|duong\s*vao)\b.{0,50}'
        r'\btoa\s*nha\b',
        ' ', text_for_nha_ascii, flags=re.IGNORECASE,
    )
    text_for_nha_ascii = re.sub(
        r'\b(?:gan|sat|canh|ke|doi\s*dien|cach|duong\s*vao|noi\s*co|khu\s*do\s*thi)\b.{0,140}'
        r'\b(?:nha\s*o\s*lien\s*ke|biet\s*thu|villa)\b',
        ' ', text_for_nha_ascii, flags=re.IGNORECASE,
    )
    text_for_nha_ascii = re.sub(
        r'\b(?:xay|cat|lam)\b.{0,30}\b(?:biet\s*thu|villa|nha)(?:\s*duoc)?\b',
        ' ', text_for_nha_ascii, flags=re.IGNORECASE,
    )
    text_for_nha_ascii = re.sub(
        r'\bxay\s*dung\s*nha\s*o\s*tron\s*goi\b|'
        r'\bky\s*gui\s*-?\s*mua\s*ban\s*bat\s*dong\s*san\b|'
        r'\bho\s*tro\s*khach\s*hang\s*lam\s*so\s*sach\b',
        ' ', text_for_nha_ascii, flags=re.IGNORECASE,
    )
    text_for_nha_ascii = re.sub(
        r'\b(?:phu\s*hop|thich\s*hop|co\s*the|[dđ]at\s*[dđ]e|[dđ]e)'
        r'\s*(?:[dđ]e\s*)?(?:xay|cat|lam)(?:\s*dung)?\s*'
        r'(?:\d+\s*)?(?:can\s*|ngoi\s*)?(?:nha|biet\s*thu|villa|nha\s*xuong)(?:\s*o)?\b',
        ' ', text_for_nha_ascii, flags=re.IGNORECASE,
    )
    text_for_nha_ascii = re.sub(
        r'\b(?:xung\s*quanh|hang\s*xom|khu\s*vuc|sat\s*ben)\b.{0,70}\bnha\s*(?:lau|cap|moi|o)?\b',
        ' ', text_for_nha_ascii, flags=re.IGNORECASE,
    )
    text_ascii = text_for_nha_ascii
    has_house_kw = any(_ascii_fold(kw) in text_for_nha_ascii for kw in _NHA_KW) or bool(re.search(
        r'(^|\n)\s*[^\w\s]*\s*nha\b|'
        r'\bnha\s*(?:tret|lau|cap|moi)\b|'
        r'\btret\s*lau\b|\bgac\s*lung\b|'
        r'\b\d+\s*pn\b|\b\d+\s*wc\b|'
        r'\bphong\s*(?:ngu|khach|tho)\b|'
        r'\bbep\b|\bmay\s*lanh\b|\bsan\s*o\s*to\b|\bsan\s*oto\b',
        text_ascii,
        re.IGNORECASE,
    ))

    # --- Bước 0b: Nhà trọ → nha_tro (tách khỏi nha_dat — rental yield pricing) ---
    text_for_tro = _ascii_fold(text)
    text_for_tro = re.sub(
        r'\b(?:phu\s*hop|thich\s*hop|co\s*the|[dđ]at\s*[dđ]e|[dđ]e\s*xay|xay|lam)'
        r'\b.{0,70}\b(?:nha|phong|day|khu)?\s*tro(?:\s*dau\s*tu)?\b',
        ' ', text_for_tro, flags=re.IGNORECASE,
    )
    if has_land_only_kw:
        text_for_tro = re.sub(r'\bphong\s*tro\s*dau\s*tu\b', ' ', text_for_tro, flags=re.IGNORECASE)
    if re.search(r'nha\s*tro|phong\s*tro|day\s*tro|khu\s*tro|kinh\s*doanh\s*tro', text_for_tro):
        return 'nha_tro'

    # ── url_hint branching ──
    # 'nha': slug đã chốt là nhà — nha_tro đã handled, mặc định nha_dat.
    if url_hint == 'nha':
        return 'nha_dat'

    # 'dat': slug đã chốt là đất — chạy nhánh dat-only (bỏ qua nha_kw, strong_house).
    if url_hint == 'dat':
        return _classify_dat_only(
            text, area_m2, tho_cu_m2, price_per_m2,
            has_land_only_kw, raw_source_label,
        )

    # url_hint = None (Facebook hoặc URL không match) → cascade cũ ↓

    # Chỉ dấu nhà MẠNH: "nhà cấp 4 mới", "N căn nhà đang..."
    # (nhà trọ đã xử lý ở step 0b)
    has_strong_house = bool(re.search(
        r'nhà\s*cấp\s*4\s*(?:mới|đẹp|trên\s*đất)|\d+\s*căn\s*nhà\s*đang',
        text, re.IGNORECASE,
    ))

    # --- Bước 1: Strong house → nha_dat (trước vuon) ---
    if has_strong_house:
        return 'nha_dat'

    # --- Bước 2: Keyword cứng → dat_vuon ---
    # Chỉ fire khi KHÔNG có land_only_kw, house_kw, hoặc giá > 8 tr/m² contradicting.
    # VD 1: "đất trồng cây" + "mặt tiền" → land_only blocks → dat_nen
    # VD 2: "đất trồng cây" + "nhà cấp 4" → house blocks → nha_dat
    # VD 3: "đất trồng cây lâu năm" (pháp lý) + giá 18 tr/m² → price blocks → dat_nen
    # Lý do price block: đất nông nghiệp TDM thực tế 1-6 tr/m². Nếu vuon_kw chỉ xuất
    # hiện trong mô tả pháp lý ("thổ cư X, đất trồng cây Y") mà giá > 8 → chắc chắn
    # đất đô thị có zoning nông nghiệp, không phải đất vườn thuần.
    _price_ok = (price_per_m2 is None or price_per_m2 <= _PRICE_VUON_MAX)
    if any(kw in text for kw in _VUON_KW) and not has_land_only_kw and not has_house_kw and _price_ok:
        return 'dat_vuon'

    # --- Bước 3: Keyword cứng → nha_dat ---
    # 2026-05-06: bỏ "not has_land_only_kw" — nhà luôn thắng đất. VD: "bán nhà 3 tầng
    # lô đất 120m²" → "nhà 3 tầng" (house) + "lô đất" (land_only) → nha_dat, không dat_nen.
    # Phrase "potential build" đã bị strip ở text_for_nha nên false-positive thấp.
    if has_house_kw:
        return 'nha_dat'

    # --- Bước 3: Thổ cư < 5% → dat_vuon (gần như toàn CLN) ---
    # Chỉ áp dụng khi KHÔNG có land_only_kw contradicting. VD: "lô góc 2 mặt tiền" +
    # thổ cư 30/908m² = 3.3% → step 3 cũ gán dat_vuon, nhưng "lô đất"+"mặt tiền" cho thấy
    # đây là đất nền trong khu TĐC giá 60 tr/m². land_only_kw → block → dat_nen (step 4).
    if tho_cu_m2 is not None and area_m2 and area_m2 > 0:
        tho_cu_ratio = tho_cu_m2 / area_m2
        if tho_cu_ratio < _THO_CU_VUON_RATIO and not has_land_only_kw:
            return 'dat_vuon'

    # --- Bước 4: Land-only keyword → dat_nen ---
    # 2026-05-05: compute sớm (trước step 1) và dùng làm blocker cho vuon/thổ cư rules.
    # Listings có "lô đất", "đất nền", "mặt tiền", "đất thổ cư" chắc chắn KHÔNG phải
    # đất nông nghiệp, dù pháp lý ghi "đất trồng cây lâu năm" hay thổ cư < 5%.
    if has_land_only_kw:
        return 'dat_nen'

    # --- Bước 5: Đường DX → chặn vườn, giữ lại dat_nen ---
    on_dx_road = _is_dx_road(text)

    # --- Bước 6: Numeric rule — area >= 500m² + không nhà + không DX → dat_vuon ---
    # 2026-05-05: hạ thổ cư exception từ 80% → 20%. Lý do: thổ cư 54% (500/932m²)
    # rõ ràng KHÔNG phải đất nông nghiệp thuần, nhưng ngưỡng 80% bỏ sót toàn bộ.
    # Thực tế TDM: đất vườn thuần có thổ cư 0-5%, đất hỗn hợp 20%+ là đất ở + vườn phụ.
    # 2026-05-06: thêm price check — đất vườn TDM thực tế 1-6 tr/m². Nếu giá > 8 tr/m²
    # mà không có keyword vuon/CLN nào → gần như chắc chắn là đất đô thị (dat_nen).
    # Áp dụng cho listing title generic "Bán đất XXXm² giá Y tỷ" không có mô tả.
    if area_m2 and area_m2 >= _AREA_VUON_THRESHOLD and not has_house_kw and not on_dx_road:
        if tho_cu_m2 is not None and area_m2 > 0 and (tho_cu_m2 / area_m2) >= 0.20:
            return 'dat_nen'
        if price_per_m2 is not None and price_per_m2 > _PRICE_VUON_MAX:
            return 'dat_nen'
        return 'dat_vuon'

    # NOTE: Đã thử rule "lô >=500m² trên DX → unknown" (loại khỏi regression)
    # nhưng làm mất user-validated good signal (L#1061 "đất mặt tiền dx 516m² giá rẻ
    # là đúng"). Trả về dat_nen như cũ cho lô lớn trên DX, để model tự xử lý qua
    # size_multiplier (line 254-257 valuation.py).

    # --- Bước 7: Source label hint ---
    mapped = _SOURCE_LABEL_MAP.get(raw_source_label, '')
    if mapped in ('dat_vuon', 'nha_dat'):
        return mapped
    if mapped == 'dat_nen':
        return 'dat_nen'

    # --- Bước 8: Default → dat_nen ---
    return 'dat_nen'


def extract_property_type(title: str, description: str) -> str:
    """Legacy wrapper — dùng classify_property_type mới."""
    return classify_property_type(title, description)


# ═══════════════════════════════════════════════════════════════════
# 10. TÍN HIỆU HOT (bán gấp / ngộp)
# ═══════════════════════════════════════════════════════════════════

HOT_SIGNALS = [
    'bán gấp', 'cần bán gấp', 'bán nhanh', 'cắt lỗ', 'ngộp',
    'kẹt tiền', 'cần tiền gấp', 'giảm giá mạnh', 'giảm sâu',
    'bán lỗ', 'thanh lý', 'bán dưới giá thị trường',
]

def extract_is_hot(text: str) -> bool:
    t = text.lower()
    return any(s in t for s in HOT_SIGNALS)


# ═══════════════════════════════════════════════════════════════════
# 11. SĐT
# ═══════════════════════════════════════════════════════════════════

def extract_phone(text: str) -> Optional[str]:
    """Lấy SĐT đầu tiên hợp lệ (Việt Nam)."""
    # Chuẩn hóa: bỏ dấu chấm, gạch ngang giữa số
    t = re.sub(r'(\d)[.\-](\d)', r'\1\2', text)
    m = re.search(r'(0[3-9]\d{8})', t)
    return m.group(1) if m else None


# ═══════════════════════════════════════════════════════════════════
# 12. MASTER EXTRACTOR — gọi tất cả functions trên
# ═══════════════════════════════════════════════════════════════════

def extract_all(title: str, description: str, source_price_str: str = '',
                badge_area_m2: Optional[float] = None,
                badge_ppm2: Optional[float] = None) -> Dict[str, Any]:
    """
    Entry point chính. Truyền vào title + description + chuỗi giá gốc.
    badge_area_m2 / badge_ppm2: giá trị từ structured badge (BDS) — ưu tiên tuyệt đối.
    Trả về dict đầy đủ features.
    """
    full_text = title + '\n' + description

    # Giá — ưu tiên chuỗi giá riêng (từ badge BDS) nếu có
    price_total = extract_price(source_price_str) if source_price_str else None
    if price_total is None:
        title_price = extract_price(title)
        description_price = extract_price(description)
        price_total = title_price
        if price_total is None:
            price_total = description_price
        elif description_price and description_price > price_total * 1.15:
            price_total = description_price

    # Diện tích — badge ưu tiên tuyệt đối, chỉ parse text nếu không có badge
    if badge_area_m2 is not None:
        area_m2 = badge_area_m2
    else:
        area_m2 = extract_area(full_text)

    # Giá/m² — badge ưu tiên tuyệt đối
    if badge_ppm2 is not None:
        ppm2 = badge_ppm2
    else:
        ppm2 = extract_price_per_m2(full_text)
        if ppm2 is None and price_total and area_m2 and area_m2 > 0:
            ppm2 = round(price_total * 1000 / area_m2, 2)  # triệu/m²

    # Kích thước
    dims = extract_dimensions(full_text)

    # Thổ cư
    tho_cu = extract_tho_cu(full_text, area_m2)

    # Legal
    legal = extract_legal(full_text)

    # Loại BĐS
    prop_type = extract_property_type(title, description)

    # Sanity check giá/m² — loại outlier rõ ràng
    if ppm2 and (ppm2 < 0.2 or ppm2 > 300):
        ppm2 = None  # cờ để Haiku review sau

    return {
        # Giá
        'price_total':      price_total,       # tỷ VND
        'price_per_m2':     ppm2,              # triệu/m²
        # Diện tích
        'area_m2':          area_m2,
        'frontage_m':       dims['frontage_m'],
        'depth_m':          dims['depth_m'],
        # Thổ cư
        'tho_cu_m2':        tho_cu['tho_cu_m2'],
        'tho_cu_ratio':     tho_cu['tho_cu_ratio'],
        # Đường
        'road_width_m':     extract_road_width(full_text),
        'road_type':        extract_road_type(full_text),
        # Pháp lý
        'has_so':           legal['has_so'],
        'has_shr':          legal['has_shr'],
        'no_so':            legal['no_so'],
        # Phân loại
        'property_type':    prop_type,
        'tx_type':          'thue' if any(k in full_text.lower() for k in ['cho thuê','cần thuê']) else 'ban',
        # Tín hiệu
        'is_hot':           extract_is_hot(full_text),
        'phone':            extract_phone(full_text),
        # Flag cho Haiku review
        'needs_ai_review':  ppm2 is None or prop_type == 'dat',
    }


# ═══════════════════════════════════════════════════════════════════
# PARSER THEO TỪNG NGUỒN
# ═══════════════════════════════════════════════════════════════════

def parse_batdongsan_card(raw_lines: list) -> Dict[str, Any]:
    """
    Parse card từ BatDongSan.com.vn.
    raw_lines từ .re__card-info innerText:
      [0] Title
      [1] Giá ("12,5 tỷ")
      [2] DT ("1.826 m²")         ← badge — luôn ưu tiên
      [3] Giá/m² ("6,85 tr/m²")  ← badge — luôn ưu tiên
      [4] Địa chỉ
      [5..] Mô tả
    """
    if len(raw_lines) < 2:
        return {}

    title = raw_lines[0]
    price_str = raw_lines[1] if len(raw_lines) > 1 else ''

    # Detect badge lines (DT và giá/m²)
    badge_area_m2   = None
    badge_ppm2      = None
    desc_start      = 2

    for i, line in enumerate(raw_lines[2:], start=2):
        # Kiểm tra tr/m TRƯỚC m² để tránh "13,63 tr/m²" bị nhầm là badge DT
        if 'tr/m' in line.lower():
            badge_ppm2 = extract_price_per_m2(line)
            desc_start = i + 1
        elif 'm²' in line or 'm2' in line.lower():
            badge_area_m2 = extract_area(line)
            desc_start = i + 1
        elif i >= 4:   # Địa chỉ + mô tả bắt đầu từ đây
            break

    description = '\n'.join(raw_lines[desc_start:])

    # Truyền badge vào extract_all để không bị description override
    features = extract_all(title, description, source_price_str=price_str,
                           badge_area_m2=badge_area_m2, badge_ppm2=badge_ppm2)
    return features


def parse_facebook_post(text: str) -> Dict[str, Any]:
    """Parse bài đăng free-form từ Facebook."""
    lines = text.strip().split('\n')
    title = lines[0] if lines else ''
    description = '\n'.join(lines[1:])
    return extract_all(title, description)


def parse_guland_card(raw_text: str) -> Dict[str, Any]:
    """Parse card từ Guland (tương tự free-form)."""
    lines = raw_text.strip().split('\n')
    title = lines[0] if lines else ''
    description = '\n'.join(lines[1:])
    return extract_all(title, description)
