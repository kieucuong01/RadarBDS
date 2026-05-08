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
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


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
      "1,69 tỷ" → 1.69
      "Thỏa thuận" / "Giá thỏa thuận" → None
    """
    t = text.lower().strip()
    # Normalize "tỉ" (biến thể không chuẩn) → "tỷ" để pattern match thống nhất
    t = t.replace('tỉ', 'tỷ')

    # GUARD: "1txx" / "2txx" / "1 tỷ xxx" — môi giới ám chỉ "1 tỷ mấy trăm"
    # nhưng KHÔNG xác định → trả None thay vì guess.
    # (user feedback L#675: "1tỷ xxx lấy hết giá tốt" → "1txx k phải 1 tỷ").
    if re.search(r'\d+\s*(?:t|tỷ|ty|tỉ)\s*x{2,}', t, re.IGNORECASE):
        return None

    # Loại phrase mô tả mức GIẢM (price drop) khỏi text trước khi parse giá:
    # "hạ 4 tỷ" / "giảm 2 tỷ" / "bớt 500tr" — đó là mức giảm, KHÔNG phải giá.
    # (User: "Giá hạ 4 tỷ chứ k phải giá là 4 tỷ")
    t = re.sub(
        r'(?:hạ|giảm|giảm\s*mạnh|bớt)\s*(?:giá\s*)?[\d,.]+\s*(?:tỷ|ty|triệu|tr|m|k)\b',
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

    # Pattern unicode: "X tỷ Y" hoặc "XtỷY" (2 tỷ 550=2.55, 1 tỷ 2=1.2, 2tỷ8=2.8)
    m = re.search(r'([\d]+[,.]?[\d]*)\s*tỷ\s*([\d]+)', t)
    if m:
        return _parse_ty_rest(m.group(1), m.group(2))

    # Pattern ASCII "ty" (môi giới FB hay dùng): 1ty8=1.8, 2ty550=2.55, 4ty5=4.5
    m = re.search(r'(\d+)\s*ty\s*(\d+)', t)
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
    t = text.replace('\n', ' ')

    # Bước 0: Loại bỏ phần "thổ cư Xm²" / "TC Xm²" khỏi text trước khi parse
    # để tránh nhầm thổ cư với tổng DT
    t_clean = re.sub(
        r'(?:thổ\s*cư|tc|thổ)\s*[\d]+[,.]?[\d]*\s*m[²2]?',
        '', t, flags=re.IGNORECASE
    )

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

    # Ưu tiên 2e: "Dt W*D" — dấu * thay cho x (ví dụ "Dt:4,7*21,5" = 101m²)
    m = re.search(r'(?:dt|diện tích)[:\s]*([\d]+[,.]?[\d]*)\s*\*\s*([\d]+[,.]?[\d]*)', t_clean, re.IGNORECASE)
    if m:
        w = float(m.group(1).replace(',', '.'))
        d = float(m.group(2).replace(',', '.'))
        if 2 <= w <= 50 and 5 <= d <= 500:
            return round(w * d, 1)

    # Ưu tiên 2f: "Dt W m x D" — mét sau chiều rộng (ví dụ "Dt 7,9m x 27" = 213m²)
    m = re.search(r'(?:dt|diện tích)[:\s]*([\d]+[,.]?[\d]*)\s*m\s*[x×]\s*([\d]+[,.]?[\d]*)', t_clean, re.IGNORECASE)
    if m:
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

    # Pattern thông thường "Xm²" — dùng t_clean để loại thổ cư
    m = re.search(r'([\d]+[,.]?[\d]*)\s*m[²2]', t_clean, re.IGNORECASE)
    if m:
        val = float(m.group(1).replace(',', '.'))
        if val > 5 and val < 100000:
            return val

    # Fallback: tính từ kích thước tự do "4x20", "5 x 18"
    m = re.search(r'(?<![/\d])([\d]+[,.]?[\d]*)\s*[x×]\s*([\d]+[,.]?[\d]*)\s*m?(?!\d)', t_clean, re.IGNORECASE)
    if m:
        w = float(m.group(1).replace(',', '.'))
        d = float(m.group(2).replace(',', '.'))
        if 2 <= w <= 50 and 5 <= d <= 500:
            return round(w * d, 1)

    return None


# ═══════════════════════════════════════════════════════════════════
# 3. GIÁ / M²
# ═══════════════════════════════════════════════════════════════════

def extract_price_per_m2(text: str) -> Optional[float]:
    """
    Trả về triệu VND/m².
    Patterns:
      "6,85 tr/m²" → 6.85
      "8 tr/m²" → 8.0
      "13,63 tr/m²" → 13.63
      "66tr/1m" → 66.0 (giá/m ngang — khác!)
    """
    t = text.lower()

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
    t = text.lower().replace('\n', ' ')
    result = {'frontage_m': None, 'depth_m': None}

    # "ngang X sâu Y" / "ngang X dài Y"
    m = re.search(r'ngang\s*([\d]+[,.]?[\d]*)\s*(?:m\b)?\s*(?:,|sâu|dài|x)\s*([\d]+[,.]?[\d]*)', t)
    if m:
        result['frontage_m'] = float(m.group(1).replace(',', '.'))
        result['depth_m'] = float(m.group(2).replace(',', '.'))
        return result

    # "XxY" hoặc "X x Y" hoặc "X x Ym" — phổ biến nhất
    m = re.search(r'(?<![/\d])([\d]+[,.]?[\d]*)\s*[x×]\s*([\d]+[,.]?[\d]*)\s*m?(?!\d)', t)
    if m:
        w = float(m.group(1).replace(',', '.'))
        d = float(m.group(2).replace(',', '.'))
        if 2 <= w <= 50 and 5 <= d <= 500:
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
    t = text.lower()
    result = {'tho_cu_m2': None, 'tho_cu_ratio': None}

    # "full thổ" / "TC full" / "100% thổ cư"
    if re.search(r'(?:full\s*thổ|tc\s*full|100%?\s*thổ)', t):
        result['tho_cu_ratio'] = 1.0
        if total_area:
            result['tho_cu_m2'] = total_area
        return result

    # "Xm² thổ cư" hoặc "thổ cư Xm²" hoặc "TC Xm" hoặc "TC 35m"
    patterns = [
        r'([\d]+[,.]?[\d]*)\s*m[²2]\s*thổ\s*cư',           # "60m² thổ cư"
        r'thổ\s*cư\s*([\d]+[,.]?[\d]*)\s*m[²2]?',           # "thổ cư 60m²"
        r'\btc\s*([\d]+[,.]?[\d]*)\s*m[²2]?',               # "TC 60m²" hoặc "TC 60"
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
    """Trả về canonical: 'duong_nhua' | 'be_tong' | 'duong_dat' | 'unknown'"""
    t = text.lower()
    if 'nhựa' in t or 'asphalt' in t:
        return 'duong_nhua'
    if 'bê tông' in t or 'be tong' in t:
        return 'be_tong'
    if 'đường đất' in t or 'đất hiện hữu' in t:
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
    r'(?:bê\s*tông|hẻm|đường\s*hẻm|ngõ)\s*'
    r'(?:rộng\s*)?(\d+(?:[,.]\d+)?)\s*m\b',
    re.IGNORECASE
)

# Regex lộ giới đường — bắt "lộ giới 8m", "lộ 6m", "đường nhựa 6m", "MT 30m", "mặt tiền 6m"
# Logic giá trị: dùng để infer Tier 2 khi có width mặt đường rõ ràng
_ROAD_WIDTH_RE = re.compile(
    r'(?:lộ(?:\s*giới)?|mặt\s*tiền|\bmt\b|đường(?:\s*(?:nhựa|bê\s*tông))?)\s*(?:rộng\s*)?(\d+(?:[,.]\d+)?)\s*m\b',
    re.IGNORECASE
)

# Chuẩn hóa biến thể ô tô (thiếu dấu, liền chữ)
_AUTO_RE = re.compile(r'(?:ô\s*tô|ôtô|oto|xe\s*hơi|xe\s*tải)', re.IGNORECASE)

# DX road pattern
_DX_RE = re.compile(r'\bdx\s*\d{2,3}\b', re.IGNORECASE)

# Chỉ dấu "không phải mặt tiền chính" — áp cho cả DX và đường nhựa.
# (User feedback: "nhánh DX là tier 3", "gần DX65 chứ k phải thuộc DX65",
#                 "1 xẹt đường nhựa thuộc tier 3", "cách DX 30m")
# Tín hiệu "nhánh/xẹt/xẹc" — chắc chắn không phải mặt đường chính (vị trí bất kỳ)
# xẹc/xẹt = variant cách viết của "1 block off" trong BĐS miền Nam
_NHANH_XEET_RE = re.compile(
    r'\bnh[áa]nh\b|\bx[ẹe][ct]\b|1\s*x[ẹe][ct]',
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

# Tín hiệu mặt tiền — dùng raw pattern để \b là word boundary (không phải backspace)
_MT_RE = re.compile(r'mặt tiền|mặt phố|mặt đường|\bmt\b', re.IGNORECASE)

# "Mặt lộ" / "tiếp giáp đường" — Tier 2 signals bị thiếu trong cascade cũ
_MAT_LO_RE = re.compile(
    r'mặt\s*lộ|tiếp\s*giáp\s*đường|sát\s*đường\s*(?:lớn|chính|nhựa)',
    re.IGNORECASE,
)

# "Đường số X" — đường địa phương đánh số (Bình Dương), thường là Tier 2
_DUONG_SO_RE = re.compile(r'đường\s*số\s*\d+', re.IGNORECASE)


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
    text = (title + ' ' + (description or '')).lower()
    title_lower = title.lower()
    has_mt   = bool(_MT_RE.search(text))
    has_hem  = any(kw in text for kw in ['hẻm', 'ngõ', 'hẽm', 'trong hẻm'])
    has_auto = bool(_AUTO_RE.search(text))
    # Loại false positive: "sân ô tô" / "chỗ đậu ô tô" — đó là vị trí đậu xe, không phải đường vào
    if has_auto and _SAN_AUTO_RE.search(text):
        has_auto = False
    # Logic giá trị: "kinh doanh"/"mtkd" = mặt tiền kinh doanh = đường lớn → Tier 2
    has_kd   = any(kw in text for kw in ['mtkd', 'mt kd', 'kinh doanh', 'mt kinh doanh'])

    # --- Title-specific signals (title authoritative, desc can mention "hẻm" as nearby) ---
    has_mt_title = bool(_MT_RE.search(title_lower))
    has_kd_title = any(kw in title_lower for kw in ['mtkd', 'mt kd', 'kinh doanh'])
    has_hem_title = any(kw in title_lower for kw in ['hẻm', 'ngõ', 'hẽm', 'trong hẻm'])
    # "nhánh / xẹt / xẹc / N/" trong title = ngõ nhánh, không phải mặt tiền chính
    # N/ = ký hiệu hẻm số N (VD: "2/ Huỳnh Văn Luỹ" = hẻm thứ 2 đường Huỳnh Văn Luỹ)
    has_nhanh_title = bool(re.search(
        r'\bnh[áa]nh\b|\bx[ẹe][ct]\b|1\s*x[ẹe][ct]|\b\d+\s*/',
        title_lower, re.IGNORECASE,
    ))

    # Pre-extract road width (mặt đường) — dùng trong nhiều nhánh logic.
    # "đường 3m" / "đường nhựa 3m" / "lộ giới 8m" → road_width = 3.0 / 8.0
    # Chỉ skip khi TITLE nói hẻm — desc có thể đề cập hẻm gần đó
    road_width = None
    _m_w = _ROAD_WIDTH_RE.search(text)
    if _m_w and not has_hem_title:
        try:
            _w = float(_m_w.group(1).replace(',', '.'))
            if 1 <= _w <= 60:
                road_width = _w
        except (ValueError, IndexError):
            pass

    # Pre-check nhánh/xẹt trong toàn text — chỉ dấu "đường nhánh" mạnh.
    # "nhánh 114" / "1 xẹt Huỳnh Thị Hiếu" → nên là Tier 3 dù không có width / DX.
    has_nhanh_strong = bool(_NHANH_XEET_RE.search(text))

    # --- Đường quy hoạch Mỹ Phước (config-driven) ---
    from config.area_profiles import detect_subward_from_street
    _mp_sw, _mp_width, _mp_tier = detect_subward_from_street(title_lower)
    if _mp_tier is not None:
        return _mp_tier

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
        hem_before = any(kw in before_dx for kw in ['hẻm', 'hẽm', 'ngõ'])
        if (_NHANH_XEET_RE.search(around)          # nhánh/xẹt bất kỳ
                or _GAN_CACH_RE.search(before_dx)   # gần/cách TRƯỚC DX
                or hem_before):                     # hẻm TRƯỚC DX
            return 3
        return 2

    # --- Tier 2: Mặt tiền đường nhựa/kinh doanh ---
    # Block bằng has_hem_title + _has_hem_road_in_desc:
    #   has_hem_title: hẻm trong TITLE → không phải mặt tiền đường lớn
    #   _has_hem_road_in_desc: desc có "hẻm Xm" có số đo → đó là đường vào thực, không phải hẻm lân cận
    if (has_mt or has_kd) and 'nhựa' in text and not has_hem_title and not _has_hem_road_in_desc:
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
    if 'nhựa' in text and not has_hem_title and not _has_hem_road_in_desc:
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
    if any(kw in text for kw in ['đường nội bộ', 'lộ nội bộ', 'nội khu']) and not has_hem_title:
        return 2

    # "Đường số X" — đường địa phương đánh số (khác DX), thường là đường nhựa Tier 2
    if _DUONG_SO_RE.search(text) and not has_hem_title:
        return 2

    # "Lộ giới" không có số đo cụ thể — vẫn là tín hiệu có đường rõ ràng
    if 'lộ giới' in text and not has_hem_title:
        return 2

    # Logic giá trị: lộ giới/đường có width đo được — width quyết định tier.
    # "đường 6m" / "lộ giới 8m" không hẻm + có chỉ dấu mặt tiền/nhựa → Tier 2.
    # "lộ 6m" / "đường 3m" hoặc "đường 4m bê tông" hoặc "nhánh đường 5m" → Tier 3.
    m_road = _ROAD_WIDTH_RE.search(text)
    if m_road and not has_hem_title:
        try:
            width = float(m_road.group(1).replace(',', '.'))
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
                if width < 5 and not has_mt and not has_kd and 'nhựa' not in text:
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
    if has_auto and any(kw in text for kw in [
        'vào', 'thông', 'đi', 'đậu', 'tới', 'đến', 'ra vào', 'đường', 'hẻm'
    ]):
        return 3

    # --- Hẻm/ngõ không có width → Tier 3 (default hẻm ô tô vào được) ---
    if has_hem:
        return 3

    # Logic giá trị: đê bao / bờ kè / đường tỉnh — đường lớn ven sông/ngoại thị → Tier 2
    if any(kw in text for kw in ['đê bao', 'bờ kè', 'đường tỉnh', 'đường liên xã', 'đường liên huyện']):
        return 2

    # --- Xe máy / hẻm nhỏ → Tier 4 ---
    if any(kw in text for kw in ['xe máy', 'hẻm nhỏ', 'đường nhỏ hẹp']):
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
    t = text.lower()
    no_so = bool(re.search(
        r'chưa có sổ|chưa sổ|không có sổ|không sổ|đất chưa|vi bằng|giấy tay|giấy viết tay',
        t,
    ))
    return {
        'has_shr':     bool(re.search(r'\bshr\b|sổ hồng riêng', t)),
        'has_gcn':     bool(re.search(r'gcn|qsdđ|sổ đỏ|giấy chứng nhận', t)),
        'no_so':       no_so,
        'dang_lam_so': bool(re.search(r'đang làm sổ|đang hoàn công|đang cấp', t)),
        'has_so':      not no_so,  # default True; False chỉ khi ghi rõ không có sổ
    }


# ═══════════════════════════════════════════════════════════════════
# 9. LOẠI TÀI SẢN
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
    # 2026-05-05: thêm công trình/xưởng — chắc chắn không phải đất vườn
    'nhà xưởng', 'xưởng sản xuất', 'bán xưởng',
    'biệt thự',
]

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


def classify_property_type(
    title: str,
    description: str,
    area_m2: Optional[float] = None,
    tho_cu_m2: Optional[float] = None,
    raw_source_label: str = '',
    price_per_m2: Optional[float] = None,
) -> str:
    """
    Phân loại tài sản: dat_vuon | dat_nen | nha_dat | nha_tro | chung_cu.

    Cascade (ưu tiên từ trên xuống):
      0.  Chung cư/căn hộ               → chung_cu  (tách khỏi segment đất)
      0b. Nhà trọ/phòng trọ/dãy trọ     → nha_tro   (tách khỏi nha_dat — rental yield pricing)
      1.  Strong house (nhà cấp 4 mới)  → nha_dat   (unmistakable)
      2.  Keyword cứng vườn/CLN          → dat_vuon  (blocked by land/house kw)
      3.  Keyword cứng nhà/công trình    → nha_dat   (+ biệt thự/xưởng)
      4.  Thổ cư < 5% tổng diện tích    → dat_vuon  (blocked by land kw)
      5.  Land-only keyword (lô đất, mặt tiền...) → dat_nen
      6.  Đường DX                       → chặn vườn, đẩy về dat_nen
      7.  area >= 500m² + không có nhà   → dat_vuon  (numeric)
          Ngoại lệ: thổ cư >= 20% HOẶC giá > 8 tr/m² → dat_nen
      8.  Source label hint              → dat_vuon / nha_dat / dat_nen
      9.  Default                        → dat_nen

    Args:
        title: tiêu đề tin rao
        description: mô tả / excerpt (c-sdb-card__exc hoặc BDS full text)
        area_m2: tổng diện tích (m²)
        tho_cu_m2: diện tích thổ cư parse được (m²)
        raw_source_label: nhãn gốc từ Guland/BDS
        price_per_m2: giá trên m² (triệu/m²), dùng để chặn false-positive dat_vuon

    Returns:
        'dat_vuon' | 'dat_nen' | 'nha_dat'
    """
    text = (title + ' ' + (description or '')).lower().strip()

    # --- Bước 0: Loại chung cư/căn hộ ra khỏi valuation đất ---
    # Chung cư có giá/m² hoàn toàn khác đất nền → trả 'chung_cu' (không khớp segment dat_*)
    # → tin sẽ KHÔNG được fed vào regression đất nền/đất vườn/nhà đất.
    if re.search(r'\bchung\s*cư\b|\bcăn\s*hộ\b|\bbiconsi\b|\bblock\s*[a-z0-9]+\b', text, re.IGNORECASE):
        return 'chung_cu'

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
    has_house_kw = any(kw in text_for_nha for kw in _NHA_KW)

    # --- Bước 0b: Nhà trọ → nha_tro (tách khỏi nha_dat — rental yield pricing) ---
    if re.search(r'nhà\s*trọ|phòng\s*trọ|dãy\s*trọ|khu\s*trọ|kinh\s*doanh\s*trọ', text):
        return 'nha_tro'

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
    _PRICE_VUON_MAX = 8.0  # triệu/m²
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
        price_total = extract_price(title)
    if price_total is None:
        price_total = extract_price(description)

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
