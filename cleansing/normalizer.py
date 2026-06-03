"""
Data normalization helpers — không phụ thuộc database.
Tách ra từ pipeline.py để main.py có thể import mà không cần PostgreSQL.
"""
import hashlib
import json
import logging
import re
import unicodedata
from typing import List, Dict, Optional

from config.settings import WATCH_AREAS, ALERT_KEYWORDS
from config.area_profiles import detect_subward_from_street, infer_standard_lot
from cleansing.feature_extractor import (
    classify_property_type, extract_tho_cu, extract_road_tier,
    extract_legal, extract_phone, extract_road_type, parse_facebook_post,
    extract_area, extract_url_hint,
)  # extract_legal đã có sẵn — dùng cho has_so detection

logger = logging.getLogger(__name__)


def _ascii_fold(text: str) -> str:
    folded = "".join(
        c for c in unicodedata.normalize("NFD", text or "")
        if unicodedata.category(c) != "Mn"
    ).lower()
    return folded.replace("đ", "d")

_CAP_TRO_RE = re.compile(
    r'cặp\s*trọ|hai\s*dãy\s*trọ|2\s*dãy\s*trọ|cặp\s*nhà\s*trọ|cặp\s*dãy', re.IGNORECASE
)
# Nếu text nói "cặp trọ" nhưng giá < ngưỡng này → seller đang quote giá 1 dãy (150m²)
_NHA_TRO_CAP_PRICE_THRESHOLD = 2.5  # tỷ

def _infer_nha_tro_area(title: str, description: str, price_ty: Optional[float]) -> float:
    """Suy luận diện tích cho nhà trọ khi thiếu area_m2.
    - "cặp trọ" / "2 dãy" → 300m² (trừ khi giá thấp → seller quote 1 dãy → 150m²)
    - Default → 150m² (1 dãy chuẩn)
    """
    text = f"{title} {description}"
    if _CAP_TRO_RE.search(text):
        if price_ty and price_ty < _NHA_TRO_CAP_PRICE_THRESHOLD:
            return 150.0  # "cặp trọ" nhưng giá chỉ bằng 1 dãy → đang quote giá 1 dãy
        return 300.0
    return 150.0

HOT_SIGNALS = [
    "cắt lỗ", "ngộp", "bán gấp", "bán nhanh", "kẹt tiền",
    "cần tiền gấp", "giảm giá mạnh", "giảm sốc", "bán lỗ",
]


def compute_content_hash(ward: Optional[str], property_type: Optional[str],
                         price_ty: Optional[float], area_m2: Optional[float],
                         title: Optional[str]) -> Optional[str]:
    """Hash định danh 1 lô (chống repost cùng nội dung khác URL).
    Trả None nếu thiếu trường tối thiểu (ward + price + area)."""
    if not ward or not price_ty or not area_m2:
        return None
    norm_title = re.sub(r"\s+", " ", (title or "").lower().strip())[:80]
    key = f"{ward}|{property_type or ''}|{round(float(price_ty),2)}|{round(float(area_m2),1)}|{norm_title}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


_ROAD_TYPE_MAP = {
    "nhua":  "duong_nhua",
    "dat":   "duong_dat",
}

def _norm_road_type(v: str) -> str:
    """Chuẩn hóa road_type về canonical form để thống nhất với Groq output."""
    return _ROAD_TYPE_MAP.get(v or "unknown", v or "unknown")


# Logic giá trị: chuẩn hóa tx_type để không split segment — "Bán"/"bán"/"ban" là 1 thị trường
def _norm_tx_type(v) -> str:
    s = (str(v or "")).strip().lower()
    if s in ("ban", "bán", "sell", "for-sale"):   return "ban"
    if s in ("thue", "thuê", "rent", "for-rent"): return "thue"
    return "ban"


def _float_or_none(value) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _infer_depth_from_area_frontage(area_m2, frontage_m) -> Optional[float]:
    area = _float_or_none(area_m2)
    frontage = _float_or_none(frontage_m)
    if area is None or frontage is None or frontage <= 0:
        return None
    depth = area / frontage
    if 2 <= frontage <= 50 and 5 <= depth <= 500:
        return round(depth, 1)
    return None


def match_area(raw_text: str) -> Optional[str]:
    if not raw_text:
        return None
    text = raw_text.lower()
    for area in WATCH_AREAS:
        if any(kw in text for kw in area["keywords"]):
            return area["name"]
    return None


# Địa danh ngoài khu vực quan tâm (không thuộc TDM, Bến Cát) — nếu xuất hiện trong text, ward = None.
_OUTSIDE_KEYWORDS = [
    # Bàu Bàng
    "bàu bàng", "bau-bang",
    "lai hưng", "lai-hung",
    "tân hưng", "tan-hung",
    # Tân Uyên / Bắc Tân Uyên
    "tân uyên", "tan-uyen",
    "uyên hưng", "uyen-hung",
    "tân vĩnh hiệp", "tan-vinh-hiep",
    # Dầu Tiếng
    "dầu tiếng", "dau-tieng",
    # Bàu Bàng/ngoài focus sau sáp nhập, hay bị rơi nhầm vào Bến Cát/Tân An
    "long nguyên", "long-nguyen", "long nguyen",
]

# Danh sách ward phổ biến tại Thủ Dầu Một để parse từ title/url
# Đầy đủ: Chánh Mỹ, Chánh Nghĩa, Hiệp An, Hiệp Thành, Phú Cường, Phú Hòa,
# Phú Lợi, Phú Mỹ, Phú Tân, Phú Thọ, Tân An (gộp Phú An sau sáp nhập), Tương Bình Hiệp, Định Hòa
_WARD_KEYWORDS = {
    # Thủ Dầu Một
    "Tân An":           ["tân an", "tan-an", "tanan", "phú an mới", "phu-an-moi", "phu an moi"],
    "Hiệp An":          ["hiệp an", "hiep-an"],
    "Hiệp Thành":       ["hiệp thành", "hiep-thanh"],
    "Phú Hòa":          ["phú hòa", "phu-hoa"],
    "Phú Lợi":          ["phú lợi", "phu-loi"],
    "Phú Mỹ":           ["phú mỹ", "phu-my"],
    "Phú Cường":        ["phú cường", "phu-cuong"],
    "Phú Tân":          ["phú tân", "phu-tan"],
    "Phú Thọ":          ["phú thọ", "phu-tho"],
    "Chánh Mỹ":         ["chánh mỹ", "chanh-my"],
    "Chánh Nghĩa":      ["chánh nghĩa", "chanh-nghia"],
    "Định Hòa":         ["định hòa", "dinh-hoa"],
    "Tương Bình Hiệp":  ["tương bình hiệp", "tuong-binh-hiep"],
    
    # Bến Cát — Mỹ Phước sub-wards (specific trước generic để match đúng)
    "Mỹ Phước 1":      ["mỹ phước 1", "my-phuoc-1", "myphuoc1", "mp1"],
    "Mỹ Phước 2":      ["mỹ phước 2", "my-phuoc-2", "myphuoc2", "mp2"],
    "Mỹ Phước 3":      ["mỹ phước 3", "my-phuoc-3", "myphuoc3", "mp3"],
    "Mỹ Phước 4":      ["mỹ phước 4", "my-phuoc-4", "myphuoc4", "mp4"],
    "Mỹ Phước":        ["mỹ phước", "my-phuoc", "myphuoc"],
    # Bến Cát — các phường khác
    "An Điền":          ["an điền", "an-dien", "andien"],
    "An Tây":           ["an tây", "an-tay", "antay"],
    "Chánh Phú Hòa":    ["chánh phú hòa", "chánh phú hoà", "chanh-phu-hoa"],
    "Hòa Lợi":          ["hòa lợi", "hoà lợi", "hoa-loi", "hoaloi"],
    "Tân Định":         ["tân định", "tan-dinh", "tandinh"],
    "Thới Hòa":         ["thới hòa", "thới hoà", "thoi-hoa", "thoihoa"],
    "Phú An":           ["phú an", "phu-an", "phuan"],
}

_CITY_WARDS = {
    "Thủ Dầu Một": [
        "Tân An", "Hiệp An", "Hiệp Thành", "Phú Hòa", "Phú Lợi", "Phú Mỹ", 
        "Phú Cường", "Phú Tân", "Phú Thọ", "Chánh Mỹ", "Chánh Nghĩa", 
        "Định Hòa", "Tương Bình Hiệp"
    ],
    "Bến Cát": [
        "An Điền", "An Tây", "Chánh Phú Hòa", "Hòa Lợi",
        "Mỹ Phước", "Mỹ Phước 1", "Mỹ Phước 2", "Mỹ Phước 3", "Mỹ Phước 4",
        "Tân Định", "Thới Hòa", "Phú An"
    ]
}


def _is_intended_city(intended_city: Optional[str], city_name: str) -> bool:
    return _ascii_fold(intended_city or "") == _ascii_fold(city_name)


def _has_ben_cat_context(text: str, intended_city: Optional[str]) -> bool:
    folded = _ascii_fold(text)
    return _is_intended_city(intended_city, "Bến Cát") or "ben cat" in folded


def _ward_keyword_items(intended_city: Optional[str] = None):
    items = []
    allowed_wards = _CITY_WARDS.get(intended_city) if intended_city else None
    for ward, keywords in _WARD_KEYWORDS.items():
        if allowed_wards and ward not in allowed_wards:
            continue
        for keyword in keywords:
            items.append((ward, str(keyword).lower()))

    return sorted(
        items,
        key=lambda item: len(_ascii_fold(item[1])),
        reverse=True,
    )


def _keyword_in_text(text: str, keyword: str) -> bool:
    keyword = (keyword or "").strip().lower()
    if not keyword:
        return False
    if " " in keyword:
        return re.search(r"(?<!\w)" + re.escape(keyword) + r"(?!\w)", text) is not None
    return keyword in text


def _match_ben_cat_landmark_ward(text: str) -> Optional[str]:
    folded = _ascii_fold(text)

    # Review wrong_ward: khu L / DL / NL / DH... là lưới Mỹ Phước 3.
    if (
        re.search(r"\bkhu\s*l\b", folded)
        or re.search(r"\b[dn][ghijklf]\d{1,2}[a-z]?\b", folded)
    ):
        return "Mỹ Phước 3"

    # Review wrong_ward: ĐH/Đại học Việt Đức nằm ở Thới Hòa.
    if re.search(r"\b(?:dai\s*hoc|dh|truong)\s+viet\s+duc\b", folded):
        return "Thới Hòa"

    # Chà Vi là landmark trong khu Mỹ Phước; giữ ở parent ward khi thiếu MP1/2/3/4.
    if re.search(r"\b(?:ben\s+)?cha\s+vi\b", folded):
        return "Mỹ Phước"

    return None


def match_area_helper(text: str) -> Optional[str]:
    text = str(text).lower()
    # Chặn địa danh ngoài khu vực trước
    if any(kw in text for kw in _OUTSIDE_KEYWORDS):
        return None
    # Ưu tiên các ward cụ thể trong _WARD_KEYWORDS
    for ward_name, keyword in _ward_keyword_items():
        if _keyword_in_text(text, keyword):
            return ward_name

    return None


def parse_post_date(date_raw: str, crawled_at: str) -> str:
    from datetime import datetime, timedelta
    import re
    
    if not date_raw:
        return crawled_at[:10] if crawled_at else datetime.now().strftime("%Y-%m-%d")
        
    date_str = str(date_raw).lower().split('\n')[0].strip()
    
    try:
        base_dt = datetime.fromisoformat(crawled_at) if crawled_at else datetime.now()
    except:
        base_dt = datetime.now()
        
    # If it's already an ISO timestamp from batdongsan
    m_iso = re.search(r'(\d{4}-\d{2}-\d{2})', date_str)
    if m_iso:
        return m_iso.group(1)
        
    # Relative dates
    if "hôm nay" in date_str or "vừa xong" in date_str:
        return base_dt.strftime("%Y-%m-%d")
    if "hôm qua" in date_str:
        return (base_dt - timedelta(days=1)).strftime("%Y-%m-%d")
        
    m = re.search(r'(\d+)\s*(phút|giờ|ngày|tuần|tháng|năm)', date_str)
    if m:
        val = int(m.group(1))
        unit = m.group(2)
        if unit == 'phút' or unit == 'giờ':
            pass # Same day
        elif unit == 'ngày':
            base_dt -= timedelta(days=val)
        elif unit == 'tuần':
            base_dt -= timedelta(weeks=val)
        elif unit == 'tháng':
            base_dt -= timedelta(days=val*30)
        elif unit == 'năm':
            base_dt -= timedelta(days=val*365)
        return base_dt.strftime("%Y-%m-%d")
        
    return base_dt.strftime("%Y-%m-%d")


def match_ward(*texts: str, intended_city: Optional[str] = None) -> Optional[str]:
    """Phát hiện ward từ nhiều nguồn text (title, desc, address, url).

    Check từng source RIÊNG theo thứ tự ưu tiên (title → desc → address → url)
    để tránh keyword collision khi address chứa ward khác với title.
    VD: title='P. Hiệp An' + address='P. Phú An, TP.HCM (Mới)' — nếu gộp blob
    thì 'Phú An' (mapped → Tân An do sáp nhập) fire trước 'Hiệp An'. Tách ra thì
    title match Hiệp An trước → đúng.

    Blacklist (Bến Cát, Bàu Bàng...) vẫn check trên TOÀN BỘ blob — 1 mention
    địa danh ngoài TDM đủ để loại tin.
    """
    blob = " ".join(t for t in texts if t).lower()
    if not blob:
        return None
    # Chặn tin từ huyện khác (Bàu Bàng, Tân Uyên, Dầu Tiếng, ...)
    if any(kw in blob for kw in _OUTSIDE_KEYWORDS):
        return None
    ward_keywords = _ward_keyword_items(intended_city)
    # Check từng source riêng, ưu tiên title > desc > address > url
    for text in texts:
        if not text:
            continue
        text_lower = text.lower()
        # Loại bỏ các tên đường dễ gây nhầm lẫn trước khi match
        text_lower = re.sub(r'mỹ phước\s*[-–]?\s*tân vạn', '', text_lower)
        text_lower = text_lower.replace('mp-tv', '').replace('mptv', '')

        if _has_ben_cat_context(blob, intended_city):
            landmark_ward = _match_ben_cat_landmark_ward(text_lower)
            if landmark_ward:
                return landmark_ward
        
        for ward, keyword in ward_keywords:
            if _keyword_in_text(text_lower, keyword):
                return ward

        text_ascii = _ascii_fold(text_lower)
        for ward, keyword in ward_keywords:
            if _keyword_in_text(text_ascii, _ascii_fold(keyword)):
                return ward
    return None

def extract_keywords(title: str, description: str) -> List[str]:
    text = (title + " " + description).lower()
    return [kw for kw in ALERT_KEYWORDS if kw in text]


def is_hot(title: str, description: str) -> bool:
    text = (title + " " + description).lower()
    return any(s in text for s in HOT_SIGNALS)


def safe_json(d: dict) -> str:
    try:
        return json.dumps(d, ensure_ascii=False)
    except Exception:
        return json.dumps({k: str(v) for k, v in d.items()}, ensure_ascii=False)


def normalize_record(raw: Dict) -> Optional[Dict]:
    """
    Chuẩn hóa một record thô → dict sẵn sàng lưu SQLite.
    Không cần kết nối DB.
    """
    try:
        title       = (raw.get("title") or "").strip()
        description = (raw.get("description") or "").strip()
        url         = (raw.get("url") or "").strip()

        if not url or not title:
            return None

        intended_city = raw.get("default_area")

        # Khu vực (area dùng cho segment analytics). default_area là city/profile,
        # không phải ward; không fallback về Tân An khi chưa bắt được ward rõ.
        area_name = (raw.get("area_name") or raw.get("area") or
                     match_area(raw.get("raw_area_text", "")))
        if not area_name and intended_city in _CITY_WARDS:
            area_name = intended_city

        # Override logic cho Guland/BDS để tránh nhập nhằng Phú An
        source_name = raw.get("source", "")
        raw_ward = (raw.get("ward") or "").lower()
        url_lower = url.lower()
        raw_addr = (raw.get("address") or "").lower()
        
        ward_from_text = None
        
        if source_name != "facebook":
            if "thu-dau-mot" in url_lower or "thủ dầu một" in raw_addr:
                intended_city = "Thủ Dầu Một"
            elif "ben-cat" in url_lower or "bến cát" in raw_addr:
                intended_city = "Bến Cát"

            # Text rao ghi rõ ward phải thắng raw/cache ward từ nguồn.
            # VD raw_url/raw_ward còn "Phú An" cũ, nhưng title/desc nói "Hiệp An".
            content_ward = match_ward(
                raw.get("title", ""), raw.get("description", ""),
                intended_city=intended_city,
            )
            if content_ward and content_ward != "Tân An":
                ward_from_text = content_ward

            # Tin từ web chuyên trang có phân mục rõ ràng
            if not ward_from_text and (
                "phu-an" in url_lower or "phú an" in raw_ward or "phú an" in raw_addr
            ):
                if intended_city == "Thủ Dầu Một":
                    ward_from_text = "Tân An" # Phú An TDM cũ -> nay là Tân An
                elif intended_city == "Bến Cát":
                    ward_from_text = "Phú An" # Phú An Bến Cát
        
        if not ward_from_text:
            ward_from_text = match_ward(
                raw.get("title", ""), raw.get("description", ""),
                raw.get("address", ""), url,
                intended_city=intended_city
            )
        
        if ward_from_text:
            ward_final = ward_from_text
            # Nếu đã tìm được Ward chính xác, ta đồng bộ area_name theo Ward để analytics chuẩn
            area_name = ward_from_text
        else:
            # Không match được ward. Kiểm tra xem có phải vì blacklist không.
            _blob = f"{raw.get('title','')} {raw.get('description','')} {raw.get('address','')} {url}".lower()
            if any(kw in _blob for kw in _OUTSIDE_KEYWORDS):
                ward_final = None              # tin huyện khác — KHÔNG fallback area_name
                area_name  = "Other"           # Phân loại ra ngoài TDM
            else:
                # Không có signal địa danh nào → trust cached ward từ source, cuối cùng là area_name
                cached_ward = (raw.get("ward") or "").strip()
                if cached_ward:
                    ward_final = cached_ward
                    area_name = cached_ward
                else:
                    ward_final = None
                    if not area_name and intended_city in _CITY_WARDS:
                        area_name = intended_city
                    if not area_name:
                        area_name = "Unknown"

        # Giá — hỗ trợ cả price_ty (SQLite) và price_total (legacy)
        price_ty     = raw.get("price_ty") or raw.get("price_total")
        area_m2      = raw.get("area_m2")
        price_per_m2 = raw.get("price_per_m2")

        # Fix BDS structured area: "1.826" → 1826 (dấu chấm hàng nghìn kiểu VN)
        # BDS serializes 1826m² as 1.826 trong JSON → Python reads as float 1.826
        if area_m2 and isinstance(area_m2, float) and area_m2 < 10:
            import re as _re2
            if _re2.match(r'^\d{1,2}\.\d{3}$', f'{area_m2:.3f}'):
                area_m2 = round(area_m2 * 1000)
                price_per_m2 = None  # buộc tính lại từ price_ty / area_m2 mới

        # Source structured area can be stale/wrong. If title has an explicit area
        # that is wildly different, trust title because it is the visible listing fact.
        title_area_m2 = extract_area(title)
        if area_m2 and title_area_m2 and 10 < title_area_m2 < 100000:
            bigger = max(float(area_m2), float(title_area_m2))
            smaller = min(float(area_m2), float(title_area_m2))
            if smaller > 0 and bigger / smaller >= 1.8:
                area_m2 = title_area_m2
                price_per_m2 = None

        # Fallback: trích xuất từ text khi nguồn không có structured fields (Facebook posts).
        # Vẫn parse khi thiếu dimensions, kể cả area structured đã có sẵn.
        _fb_parsed: dict = {}
        if (
            price_ty is None
            or area_m2 is None
            or price_per_m2 is None
            or raw.get("frontage_m") is None
            or raw.get("depth_m") is None
            or raw.get("road_width_m") is None
        ):
            _parse_text = "\n".join(part for part in [title, description] if part)
            _fb_parsed = parse_facebook_post(_parse_text) or {}
            if price_ty is None:
                price_ty = _fb_parsed.get("price_total")
            if area_m2 is None:
                area_m2 = _fb_parsed.get("area_m2") or None
            if price_per_m2 is None:
                if price_ty and area_m2:
                    price_per_m2 = None  # tính lại từ area cuối cùng ở block dưới
                else:
                    price_per_m2 = _fb_parsed.get("price_per_m2")

        if price_ty and area_m2 and area_m2 > 0 and not price_per_m2:
            price_per_m2 = round((price_ty * 1_000) / area_m2, 3)

        # Sanity check
        if price_per_m2 and (price_per_m2 < 0.1 or price_per_m2 > 500_000):
            price_per_m2 = None
        if price_ty and (price_ty < 0.001 or price_ty > 10_000):
            price_ty = None

        hot = is_hot(title, description)

        # Phân loại tài sản + road tier
        road_text_extra = " ".join(filter(None, [
            str(raw.get("address") or ""),
            str(raw.get("road_type_raw") or ""),
            str(raw.get("road_name") or ""),
        ]))
        full_text   = title + ' ' + description
        road_text   = " ".join(filter(None, [description, road_text_extra]))
        tho_cu_info = extract_tho_cu(full_text, area_m2)
        raw_label   = str(raw.get("property_type", ""))
        url_hint    = extract_url_hint(url)
        prop_type   = classify_property_type(
            title       = title,
            description = description,
            area_m2     = area_m2,
            tho_cu_m2   = tho_cu_info.get('tho_cu_m2'),
            raw_source_label = raw_label,
            price_per_m2 = price_per_m2,
            url_hint    = url_hint,
        )
        road_tier = extract_road_tier(title, road_text)

        # Nha_tro: fill area_m2 mặc định khi thiếu (sau classify để biết prop_type)
        if prop_type == 'nha_tro' and not area_m2:
            area_m2 = _infer_nha_tro_area(title, description, price_ty)
            if price_ty and not price_per_m2:
                price_per_m2 = round((price_ty * 1_000) / area_m2, 3)

        # Street name → upgrade sub-ward + fill road_width_m (config-driven)
        # Scope detection to ward_final's profile via parent_filter — tránh
        # pattern HT3 nhặt nhầm trong tin Mỹ Phước, hoặc ngược lại.
        full_text_for_street = " ".join(filter(None, [title, description, road_text_extra]))
        _st_sw, _st_width, _st_tier = detect_subward_from_street(
            full_text_for_street,
            parent_filter=ward_final,
        )
        if _st_sw and ward_final in ("Mỹ Phước", "Hiệp Thành"):
            ward_final = _st_sw
            area_name = _st_sw
        if not road_tier and _st_tier is not None:
            road_tier = _st_tier

        # Pháp lý: default = có sổ. Flip về 0 chỉ khi text rõ ràng nói "vi bằng / giấy tay / chưa sổ"
        # (extract_legal regex: chưa có sổ|chưa sổ|không có sổ|không sổ|vi bằng|giấy tay|đang làm sổ)
        _legal = extract_legal(full_text)
        has_so_final = 0 if _legal.get("no_so") else 1

        # Re-extract phone nếu raw không có (Guland detail page có thể miss)
        contact_phone = (raw.get("contact_phone") or "").strip() or extract_phone(full_text) or ""

        # Lot inference cho khu vực quy hoạch bàn cờ (Mỹ Phước)
        _raw_front = raw.get("frontage_m") or _fb_parsed.get("frontage_m")
        _raw_depth = raw.get("depth_m") or _fb_parsed.get("depth_m")
        if _raw_front and not _raw_depth:
            _raw_depth = _infer_depth_from_area_frontage(area_m2, _raw_front)
        _inf_front, _inf_depth = (None, None)
        if not _raw_front and not _raw_depth:
            _inf_front, _inf_depth = infer_standard_lot(area_m2, ward_final)

        return {
            "source":        raw.get("source", "unknown"),
            "source_id":     str(raw.get("external_id") or raw.get("source_id") or ""),
            "url":           url,
            "title":         title[:500],
            "description":   description[:4000],
            "area":          area_name,
            "ward":          ward_final,
            "raw_area_text": (raw.get("raw_area_text") or area_name or "")[:200],
            "price_ty":      price_ty,
            "price_per_m2":  price_per_m2,
            "area_m2":       area_m2,
            "property_type": prop_type,
            "tx_type":       _norm_tx_type(raw.get("tx_type") or raw.get("transaction_type")),
            "frontage_m":    _raw_front or _inf_front,
            "depth_m":       _raw_depth or _inf_depth,
            "road_width_m":  raw.get("road_width_m") or _fb_parsed.get("road_width_m")
                             or _st_width,
            "road_type":     _norm_road_type(raw.get("road_type") or
                             extract_road_type(" ".join(filter(None, [
                                 title, description, road_text_extra
                             ])))),
            "road_tier":     road_tier,
            "tho_cu_m2":     tho_cu_info.get("tho_cu_m2"),
            "tho_cu_ratio":  tho_cu_info.get("tho_cu_ratio"),
            "has_so":        has_so_final,
            "is_hot":        int(hot),
            "contact_phone": (contact_phone[:50] or None),
            "seller_name":   (raw.get("seller_name") or "")[:200] or None,
            "post_date":     parse_post_date(raw.get("date_raw", ""), raw.get("crawled_at", "")),
            "img_urls":      raw.get("imgs") or raw.get("img_urls") or [],
            "raw_json":      raw,
        }
    except Exception as e:
        logger.error(f"Normalize error: {e} | url={raw.get('url', '')}")
        return None
