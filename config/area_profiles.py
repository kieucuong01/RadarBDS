"""
Area Profiles — config-driven cho từng khu vực.

Mỗi khu vực (TDM, Bến Cát/Mỹ Phước, ...) có profile riêng:
  - sub_wards: danh sách sub-ward (dùng cho mid-level fallback valuation)
  - street_patterns: regex → (sub_ward, road_width_m) — xác định khu vực từ tên đường
  - standard_lots: area_m2 → (frontage, depth) — suy luận kích thước lô chuẩn
  - parent_ward: ward cha để aggregate fallback khi sub-ward < 15 mẫu

Mở rộng: thêm profile mới cho Thuận An, Dĩ An, ... chỉ cần thêm entry.
"""
import re
from typing import Dict, List, Optional, Tuple

# ── Mỹ Phước (Bến Cát) ─────────────────────────────────────────────────────
# Quy hoạch kiểu Singapore, đường bàn cờ.
# Hệ thống tên đường:
#   N = Bắc-Nam, D = Đông-Tây
#   MP3 nội khu: N/D + zone_letter(G,H,I,J,K,L,F) + số  → lộ giới 8m
#   MP3 trục chính: N/D + E + số                         → lộ giới 16-25m
#   MP4: N/D + A + số                                    → lộ giới 8m
#   MP1/2: N/D + số (không zone letter)                   → lộ giới 8m

_MP3_ZONES = "GHIJKLF"

_MP_STREET_PATTERNS = [
    # (regex, sub_ward, road_width_m, road_tier)
    # MP3 trục chính: NE3, DE2 → 16-25m, tier 1 (mặt tiền đường lớn quy hoạch)
    (re.compile(r'\b[ND]E\d+\b', re.IGNORECASE),
     "Mỹ Phước 3", 16.0, 1),
    # MP3 nội khu: NG2, DJ4, DG3 → 8m, tier 2
    (re.compile(r'\b[ND][' + _MP3_ZONES + r']\d+\b', re.IGNORECASE),
     "Mỹ Phước 3", 8.0, 2),
    # MP4: NA5, DA3 → 8m, tier 2
    (re.compile(r'\b[ND]A\d+\b', re.IGNORECASE),
     "Mỹ Phước 4", 8.0, 2),
    # MP1/2: N1, D6, N12 (chỉ N/D + số, không zone letter)
    # Không phân biệt được MP1 vs MP2 → sub_ward = None
    (re.compile(r'\b(?:đường\s+)?[ND]\d{1,2}\b', re.IGNORECASE),
     None, 8.0, 2),
]

_MP_STANDARD_LOTS: Dict[float, Tuple[float, float]] = {
    150.0: (5.0, 30.0),
    100.0: (5.0, 20.0),
    80.0:  (4.0, 20.0),
    300.0: (10.0, 30.0),   # biệt thự MP3
}

_MP_SUBWARDS = {"Mỹ Phước 1", "Mỹ Phước 2", "Mỹ Phước 3", "Mỹ Phước 4"}

# Kích thước lô phổ biến cho dat_nen VN (Bình Dương) — dùng khi ward không thuộc profile riêng
# tolerance ±5m² vì đất tự nhiên ít đồng nhất hơn MP quy hoạch
_GENERAL_DAT_NEN_LOTS: Dict[float, Tuple[float, float]] = {
    80.0:  (4.0, 20.0),
    100.0: (5.0, 20.0),
    125.0: (5.0, 25.0),
    150.0: (5.0, 30.0),
    200.0: (5.0, 40.0),
    300.0: (10.0, 30.0),
}

MY_PHUOC_PROFILE = {
    "parent_ward": "Mỹ Phước",
    "sub_wards": _MP_SUBWARDS,
    "street_patterns": _MP_STREET_PATTERNS,
    "standard_lots": _MP_STANDARD_LOTS,
    "lot_tolerance_m2": 1.0,
}


# ── Public API ──────────────────────────────────────────────────────────────

# Registry: parent_ward → profile
AREA_PROFILES: Dict[str, dict] = {
    "Mỹ Phước": MY_PHUOC_PROFILE,
}

# Flat set of all sub-wards across all profiles (for valuation fallback)
ALL_SUBWARDS: Dict[str, str] = {}  # sub_ward → parent_ward
for _profile in AREA_PROFILES.values():
    for _sw in _profile["sub_wards"]:
        ALL_SUBWARDS[_sw] = _profile["parent_ward"]


def detect_subward_from_street(text: str) -> Tuple[Optional[str], Optional[float], Optional[int]]:
    """Detect sub-ward, road width, road tier from street name patterns.

    Returns: (sub_ward, road_width_m, road_tier) — any field can be None.
    """
    if not text:
        return None, None, None
    for profile in AREA_PROFILES.values():
        for pattern, sub_ward, width, tier in profile["street_patterns"]:
            if pattern.search(text):
                return sub_ward, width, tier
    return None, None, None


# ── City filter cho Facebook posts ─────────────────────────────────────────
# Mặc định INSERT mọi post. Chỉ SKIP khi post ghi RÕ tên TP/khu KHÁC với
# profile_city (broker thường không ghi city — chỉ ghi phường/đường/landmark).
#
# LƯU Ý 2026-05: Bình Dương đã sáp nhập vào TP HCM. Broker có thể ghi địa chỉ
# mới "TP HCM / Sài Gòn" cho tin TDM/Bến Cát → KHÔNG đưa HCM/Sài Gòn vào list
# skip. Chỉ skip khi post nêu rõ quận/huyện/tỉnh khác địa bàn quan tâm.
OTHER_CITY_KEYWORDS = [
    # Các huyện/khu khác trong BD cũ (giờ thuộc HCM) — vẫn skip nếu profile là TDM
    "tân uyên", "dĩ an", "thuận an", "bến cát", "bàu bàng",
    "phú giáo", "dầu tiếng",
    # Các tỉnh/TP khác hoàn toàn
    "hà nội", "đà nẵng", "đồng nai", "biên hòa",
    "long an", "tây ninh", "vũng tàu", "cần thơ",
    "bình phước", "đồng xoài",
    "thủ dầu một", "tdm",
]

# Keyword của chính city profile — loại khỏi check để không tự skip nhầm.
CITY_OWN_KEYWORDS = {
    "Thủ Dầu Một": ["thủ dầu một", "tdm"],
    "Bến Cát":     ["bến cát"],
}


def post_mentions_other_city(text: str, profile_city: Optional[str]) -> bool:
    """True nếu text chứa keyword TP khác với profile_city.

    - Post không có text (ảnh thuần) → False (không skip).
    - profile_city rỗng → False (không có baseline để so sánh).
    """
    if not text or not profile_city:
        return False
    txt = text.lower()
    own = set(k.lower() for k in CITY_OWN_KEYWORDS.get(profile_city, []))
    for kw in OTHER_CITY_KEYWORDS:
        if kw in own:
            continue
        if kw in txt:
            return True
    return False


def infer_standard_lot(area_m2: Optional[float], ward: Optional[str]) -> Tuple[Optional[float], Optional[float]]:
    """Infer frontage/depth for standard lot sizes in configured areas.

    Returns: (frontage_m, depth_m) or (None, None).
    """
    if not area_m2 or not ward:
        return None, None
    for profile in AREA_PROFILES.values():
        parent = profile["parent_ward"]
        if not (ward == parent or ward in profile["sub_wards"]):
            continue
        tol = profile.get("lot_tolerance_m2", 1.0)
        for std_area, (f, d) in profile["standard_lots"].items():
            if abs(area_m2 - std_area) <= tol:
                return f, d
    return None, None
