"""
Valuation Engine — Python thuần, 0 token Claude
- Outlier removal (±2σ per segment)
- Multiple Regression: price_per_m2 ~ features
- Fair value estimation
- MOS threshold signal generation
"""

import logging
import math
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Tuple
from datetime import datetime, date
import numpy as np
import re
import unicodedata

from config.proximity import proximity_score_for_ward

logger = logging.getLogger(__name__)

# ── Cấu hình ────────────────────────────────────────────────────────────────
MOS_THRESHOLD_HIGH   = 0.20
MOS_THRESHOLD_MEDIUM = 0.25
MOS_THRESHOLD_LOW    = 0.35

MIN_SAMPLES     = 15
# Ngưỡng tin cậy n_samples để PHÁT signal (khác MIN_SAMPLES — ngưỡng build segment).
# Segment < ngưỡng này → fair_value tính bằng median fallback, KHÔNG đủ tin cậy để gắn cờ
# is_signal dù MOS cao. Giữ giá trị bằng MIN_SAMPLES để semantic rõ "regression-fit-only".
MIN_RELIABLE_N_FOR_SIGNAL = 15
OUTLIER_SIGMA   = 2.0
TIME_DECAY_DAYS = 90
GULAND_SIGNAL_EXTRA_MOS = 0.08
GULAND_STRONG_SIGNAL_SCORE = 55
SOURCE_SIGNAL_SUPPRESS_FLAGS = {
    "old_guland_post",
    "extreme_guland_ppm2",
    "suspicious_bait",
    "guland_cluster_flood",
}
DEFAULT_BASELINE_SOURCES = ("facebook",)

FAIR_FLOOR_RATIO = 0.70
EXPECTED_NEGOTIATION_RATIO = 0.95

RIDGE_LAMBDA = 1.0
# NOTE 2026-05-05: CV_MULTIPLIER đã bị loại — xem mos_threshold() comment.

SIZE_DISCOUNT_ALPHA = {
    'dat_nen':  0.60,
    'nha_dat':  0.50,
    'nha_tro':  0.40,
}
SIZE_DISCOUNT_CAP   = (0.65, 1.20)

# Multipliers chỉ dùng làm fallback khi dùng Median
# tier-0 (unknown) → 0.50 như tier-3: tin không đọc được tier thường là hẻm
ROAD_TIER_MULTIPLIER = {
    0: 0.50,
    1: 2.00,
    2: 1.00,
    3: 0.50,
    4: 0.40,
}
_ROAD_TIER_PROP_TYPES = {'dat_nen', 'nha_dat', 'nha_tro'}
SPECIAL_MARKET_SKIP_TYPES = {'kho_xuong', 'nha_o_xa_hoi'}

# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class Listing:
    id:             int
    area:           str
    property_type:  str
    tx_type:        str
    price_per_m2:   float
    price_total:    float
    area_m2:        float
    ward:           str = 'unknown'
    frontage_m:     Optional[float] = None
    depth_m:        Optional[float] = None
    tho_cu_m2:      Optional[float] = None
    tho_cu_ratio:   Optional[float] = None
    road_type:      str = 'unknown'
    road_tier:      int = 0
    has_so:         bool = True
    is_hot:         bool = False
    price_dropped:  bool = False
    crawled_at:     Optional[date] = None
    url:            str = ''
    contact_phone:  str = ''
    title:          str = ''
    description:    str = ''
    source:         str = ''
    exclude_from_baseline: bool = False
    source_quality_flags:  Tuple[str, ...] = field(default_factory=tuple)
    review_recheck_candidate: bool = False
    legal_status:   str = 'unverified'
    trust_tier:     str = 'candidate_signal'
    trust_score:    int = 0
    legal_flags:    Tuple[str, ...] = field(default_factory=tuple)

def extract_regex_features(text: str) -> Dict[str, bool]:
    if not text: return {}
    text = text.lower()
    return {
        'is_corner': bool(re.search(r'lô góc|2 mặt tiền|góc 2 mặt', text)),
        'is_nở_hậu': bool(re.search(r'nở hậu', text)),
        'is_thắt_hậu': bool(re.search(r'thắt hậu|tóp hậu', text)),
        'is_đường_đâm': bool(re.search(r'đường đâm|đâm đường|đâm hông', text)),
        'near_grave': bool(re.search(r'nghĩa trang|mồ mả|gần mộ', text)),
    }

@dataclass
class ValuationResult:
    listing_id:      int
    area:            str
    property_type:   str
    price_per_m2_actual:  float
    price_per_m2_fair:    float
    discount_pct:         float
    is_signal:            bool
    confidence:           str
    segment_n:            int
    signal_score:         int  = 0
    is_outlier:           bool = False
    outlier_direction:    str  = ''
    outlier_sigma:        float = 0.0
    note:                 str  = ''
    source_quality_flags: Tuple[str, ...] = field(default_factory=tuple)
    source_quality_recheck: bool = False
    legal_status:         str = 'unverified'
    trust_tier:           str = 'candidate_signal'
    trust_score:          int = 0
    legal_flags:          Tuple[str, ...] = field(default_factory=tuple)

# ── Helpers ──────────────────────────────────────────────────────────────────

def compute_signal_score(listing: 'Listing', mos_pct: float) -> int:
    """Signal score 0–100. Re-weighted 2026-04-27 theo user feedback:
      - MOS dominant (cap 65, ×0.65) — đây là tín hiệu chính, đáng nặng nhất
      - price_dropped tăng x1.5 (10→15) — confirmed signal mạnh (phát hiện qua dedup)
      - is_hot giữ 10 — 'cắt lỗ/ngộp/bán gấp' tin cậy vừa phải (broker hay nhập)
      - area + giá ngưỡng giảm 10→5 mỗi cái — yếu tố phụ, giảm noise nhỏ lẻ
      - LOẠI frontage_m ≥ 4 — đã có trong regression (feature trực tiếp), tránh double count
      - Ngưỡng giá nâng 3→4 tỷ — TDM 2026 deal lớn hơn, 3 tỷ đã quá hẹp
    Tổng max = 65 + 5 + 5 + 10 + 15 = 100.
    """
    score = 0
    mos_pts = min(65, round(mos_pct * 0.65))
    score += mos_pts
    area = listing.area_m2 or 0
    if 50 <= area <= 200: score += 5
    price_ty = listing.price_total or 0
    if 0 < price_ty < 4.0: score += 5
    if listing.is_hot: score += 10
    if getattr(listing, 'price_dropped', False): score += 15
    score += proximity_score_for_ward(getattr(listing, 'ward', ''))
    return min(100, score)


def _source_flags(listing: 'Listing') -> set:
    return set(getattr(listing, "source_quality_flags", ()) or ())


def _legal_flags(listing: 'Listing') -> set:
    return set(getattr(listing, "legal_flags", ()) or ())


def _has_legal_conflict(listing: 'Listing') -> bool:
    if (getattr(listing, "legal_status", "") or "") == "conflict":
        return True
    return bool(_legal_flags(listing) & {"area_mismatch", "ward_mismatch", "road_conflict", "tho_cu_mismatch"})


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


def _has_explicit_no_so(listing: 'Listing') -> bool:
    text = " ".join(
        str(getattr(listing, field, "") or "")
        for field in ("title", "description", "road_type")
    )
    return bool(_NO_SO_RE.search(_ascii_fold(text)))


def _effective_has_so(listing: 'Listing') -> bool:
    if getattr(listing, "has_so", True):
        return True
    return not _has_explicit_no_so(listing)


def _is_guland(listing: 'Listing') -> bool:
    return (getattr(listing, "source", "") or "").lower() == "guland"


def _passes_source_signal_gate(listing: 'Listing', discount: float,
                               base_threshold: float, score: int) -> bool:
    if not _is_guland(listing):
        return discount >= base_threshold
    if _source_flags(listing) & SOURCE_SIGNAL_SUPPRESS_FLAGS:
        return False
    return (
        discount >= base_threshold + GULAND_SIGNAL_EXTRA_MOS
        or (discount >= base_threshold and score >= GULAND_STRONG_SIGNAL_SCORE)
    )

def remove_outliers(values: List[float], sigma: float = OUTLIER_SIGMA) -> Tuple[List[float], float, float]:
    if len(values) < 3:
        return values, float(np.mean(values)), float(np.std(values))
    arr  = np.array(values, dtype=float)
    mean = np.mean(arr)
    std  = np.std(arr)
    if std == 0: return values, mean, std
    mask = np.abs(arr - mean) <= sigma * std
    cleaned = arr[mask].tolist()
    if cleaned:
        clean_arr = np.array(cleaned)
        return cleaned, float(np.mean(clean_arr)), float(np.std(clean_arr))
    return values, mean, std

def build_feature_matrix(listings: List[Listing], ward_list: Optional[List[str]] = None) -> Tuple[np.ndarray, np.ndarray, List[str]]:
    # NOTE 2026-05-05 — Refactor lần 3:
    #   Loại tiếp frontage_m (fill rate 4% → 96% default 5.0 → noise, β=+0.5)
    #   và tho_cu_ratio (không tồn tại trong DB → 100% default 0.5 → β≈0).
    #   Chỉ giữ features có data thật: log_area (100%), tier dummies (~62%).
    #   Lịch sử loại: road_width_m (lần 1), road_nhua/road_betong (lần 2).
    feature_names = [
        'intercept', 'log_area_m2',
        'tier_1', 'tier_3', 'tier_4'
    ]
    wards_in_model = []
    if ward_list and len(ward_list) > 1:
        wards_in_model = sorted(ward_list)[1:]
        for w in wards_in_model: feature_names.append(f"ward_{w}")

    X_rows, y_vals = [], []
    for l in listings:
        if not l.price_per_m2 or not l.area_m2 or l.area_m2 <= 0: continue
        log_area = math.log(max(l.area_m2, 1))
        t1 = 1.0 if l.road_tier == 1 else 0.0
        t3 = 1.0 if l.road_tier == 3 else 0.0
        t4 = 1.0 if l.road_tier == 4 else 0.0
        row = [1.0, log_area, t1, t3, t4]
        for w in wards_in_model: row.append(1.0 if l.ward == w else 0.0)
        X_rows.append(row)
        y_vals.append(l.price_per_m2)
    return np.array(X_rows, dtype=float), np.array(y_vals, dtype=float), feature_names

def compute_time_weights(listings: List[Listing], today: Optional[date] = None) -> np.ndarray:
    today = today or date.today()
    weights = []
    for l in listings:
        age = (today - l.crawled_at).days if l.crawled_at else 90
        weights.append(math.exp(-max(age, 0) / TIME_DECAY_DAYS))
    return np.array(weights, dtype=float)

def weighted_ols(X: np.ndarray, y: np.ndarray, w: np.ndarray, ridge: float = RIDGE_LAMBDA) -> Optional[np.ndarray]:
    try:
        W = np.diag(w)
        XtW = X.T @ W
        XtWX = XtW @ X
        reg = np.eye(XtWX.shape[0]) * ridge
        reg[0, 0] = 0.0
        return np.linalg.solve(XtWX + reg, XtW @ y)
    except Exception: return None

# ── Core Models ──────────────────────────────────────────────────────────────

class SegmentModel:
    def __init__(self, segment_key: Tuple[str, str, str]):
        self.segment_key = segment_key
        self.beta = None
        self.median_ppm2 = 0
        self.mean_ppm2 = 0
        self.std_ppm2 = 0
        self.std_ppm2_core = 0
        self.ref_area_m2 = 0
        self.n_samples = 0
        self.fitted = False
        self.wards_in_model = []

    def fit(self, listings: List[Listing]):
        if not listings: return
        today = date.today()
        deduped = []
        seen_urls = set()
        for l in sorted(listings, key=lambda x: x.crawled_at or date.min, reverse=True):
            if l.crawled_at and (today - l.crawled_at).days > 180: continue
            if l.url and l.url not in seen_urls:
                seen_urls.add(l.url), deduped.append(l)
            elif not l.url: deduped.append(l)
        listings = deduped
        # NOTE: Đã thử Path B (loại tier=0 khỏi baseline) nhưng làm bad signals
        # tăng (16→17) và total signals tăng (133→154) — vì tier=0 mix cả tin đắt
        # và tin rẻ, removing chúng đẩy median lên → nhiều "deal" giả tạo hơn.
        ppm2_vals = [l.price_per_m2 for l in listings if l.price_per_m2]
        if len(ppm2_vals) < 3: return
        self.median_ppm2 = float(np.median(ppm2_vals))
        self.mean_ppm2 = float(np.mean(ppm2_vals))
        self.std_ppm2 = float(np.std(ppm2_vals))
        area_vals = [l.area_m2 for l in listings if l.area_m2 and l.area_m2 > 0]
        self.ref_area_m2 = float(np.median(area_vals)) if area_vals else 100
        # 2-pass outlier removal (NOTE 2026-05-05): 1-pass giữ lại giá 555+ tr/m²
        # (parse lỗi) vì extreme outliers kéo mean+std lên. 2-pass: re-compute
        # mean/std sau pass 1 → loại thêm moderate outliers → max ~81 tr/m².
        lo, hi = self.mean_ppm2 - 2*self.std_ppm2, self.mean_ppm2 + 2*self.std_ppm2
        core = [l for l in listings if l.price_per_m2 and lo <= l.price_per_m2 <= hi]
        if len(core) >= 3:
            ppm2_p1 = np.array([l.price_per_m2 for l in core])
            m2, s2 = float(np.mean(ppm2_p1)), float(np.std(ppm2_p1))
            if s2 > 0:
                lo2, hi2 = m2 - 2*s2, m2 + 2*s2
                core = [l for l in core if lo2 <= l.price_per_m2 <= hi2]
        # NOTE 2026-04-27: tier_0 = "không xác định cấp đường" (~33% data) — KHÔNG
        # tham gia training vì sẽ pollute baseline (regression treat unknown ≡
        # tier_2 nhựa baseline → bias hệ số). Tin tier_0 vẫn được predict bình
        # thường qua beta hoặc median fallback — chỉ không được dùng để fit.
        core = [l for l in core if (l.road_tier or 0) > 0]
        self.n_samples = len(core)
        self.std_ppm2_core = float(np.std([l.price_per_m2 for l in core])) if len(core) > 1 else self.std_ppm2
        self.wards_in_model = sorted(list(set(l.ward for l in core if l.ward)))[1:]
        if self.n_samples >= MIN_SAMPLES:
            X, y, _ = build_feature_matrix(core, list(set(l.ward for l in core if l.ward)))
            w = compute_time_weights(core)
            self.beta = weighted_ols(X, y, w)
        self.fitted = True

    def predict_fair_ppm2(self, listing: Listing) -> Optional[float]:
        if not self.fitted: return None
        uses_regression = self.beta is not None
        if self.beta is not None:
            log_area = math.log(max(listing.area_m2 or 1, 1))
            # tier-0 unknown → encode như tier-3 (hẻm mặc định)
            eff_tier = listing.road_tier if listing.road_tier else 3
            t1, t3, t4 = (1.0 if eff_tier == i else 0.0 for i in (1, 3, 4))
            x_list = [1.0, log_area, t1, t3, t4]
            for w in self.wards_in_model: x_list.append(1.0 if listing.ward == w else 0.0)
            base_fair = float(np.array(x_list) @ self.beta)
        else:
            base_fair = self.median_ppm2
            if self.segment_key[1] in _ROAD_TIER_PROP_TYPES:
                base_fair *= ROAD_TIER_MULTIPLIER.get(listing.road_tier or 0, 1.0)
        
        if not base_fair or base_fair <= 0: return None
        
        # Adjustments
        prop_type = self.segment_key[1]
        alpha = SIZE_DISCOUNT_ALPHA.get(prop_type)
        if not uses_regression and alpha and listing.area_m2 and self.ref_area_m2:
            cap_min, cap_max = SIZE_DISCOUNT_CAP
            mult = max(cap_min, min(cap_max, (self.ref_area_m2 / listing.area_m2) ** alpha))
            base_fair *= mult
        
        # Regex
        feat = extract_regex_features(f"{listing.title} {listing.description}")
        if feat.get('is_corner'): base_fair *= 1.10
        if feat.get('is_nở_hậu'): base_fair *= 1.05
        if feat.get('is_thắt_hậu'): base_fair *= 0.90
        if feat.get('is_đường_đâm'): base_fair *= 0.85
        if feat.get('near_grave'): base_fair *= 0.80
        
        if not _effective_has_so(listing): base_fair *= 0.75
        base_fair *= EXPECTED_NEGOTIATION_RATIO
        return round(base_fair, 2) if base_fair > 0 else None

    def confidence_level(self):
        if self.n_samples >= 45 and self.beta is not None: return 'high'
        return 'medium' if self.n_samples >= 15 else 'low'

    def mos_threshold(self):
        from config.settings import SIGNAL_MOS_THRESHOLD
        return SIGNAL_MOS_THRESHOLD

def get_segment_priors(conn) -> Dict[str, int]:
    """Legacy hook kept as no-op; Admin Control Room feedback is the source of truth."""
    return {}


class ValuationEngine:
    def __init__(self, baseline_sources=None):
        self._models = {}
        self._baseline_sources = tuple(
            str(s).strip().lower()
            for s in (baseline_sources or DEFAULT_BASELINE_SOURCES)
            if str(s).strip()
        )

    def _key(self, l):
        return (l.ward or "SELECTED_REGION", l.property_type, l.tx_type)

    def _fallback_key(self, l):
        return ("SELECTED_REGION", l.property_type, l.tx_type)

    def _parent_ward_key(self, l):
        """Mid-level fallback: sub-ward → parent ward (e.g. Mỹ Phước 3 → Mỹ Phước)."""
        from config.area_profiles import ALL_SUBWARDS
        parent = ALL_SUBWARDS.get(l.ward)
        if parent:
            return (parent, l.property_type, l.tx_type)
        return None

    def fit(self, listings, conn=None):
        from collections import defaultdict
        from config.area_profiles import ALL_SUBWARDS
        segs          = defaultdict(list)
        fallback_segs = defaultdict(list)
        parent_segs   = defaultdict(list)   # aggregate sub-ward → parent
        for l in listings:
            if l.property_type in SPECIAL_MARKET_SKIP_TYPES:
                continue  # chưa đủ data — skip segment build
            if getattr(l, "exclude_from_baseline", False) or _source_flags(l):
                continue
            source = (getattr(l, "source", "") or "").strip().lower()
            if self._baseline_sources and source and source not in self._baseline_sources:
                continue
            if l.price_per_m2 and l.area_m2:
                segs[self._key(l)].append(l)
                fallback_segs[self._fallback_key(l)].append(l)
                parent = ALL_SUBWARDS.get(l.ward)
                if parent:
                    parent_segs[(parent, l.property_type, l.tx_type)].append(l)
        for k, ls in segs.items():
            m = SegmentModel(k)
            m.fit(ls)
            self._models[k] = m
        # Parent ward aggregate (e.g. "Mỹ Phước" from MP1+MP2+MP3+MP4 + generic)
        for k, ls in parent_segs.items():
            existing = segs.get(k, [])
            combined = existing + ls
            m = SegmentModel(k)
            m.fit(combined)
            self._models[k] = m
        # SELECTED_REGION: fallback cho ward=null/unknown
        for k, ls in fallback_segs.items():
            m = SegmentModel(k)
            m.fit(ls)
            self._models[k] = m

    def valuate(self, listing: Listing) -> Optional[ValuationResult]:
        # Special markets: giá/m² và logic định giá khác đất/nhà, chưa đủ data để
        # build segment regression riêng → skip valuation. Tin vẫn hiển thị nhưng
        # không có fair_value/MOS. Khi đủ data (n≥30) sẽ build model riêng.
        if listing.property_type in SPECIAL_MARKET_SKIP_TYPES:
            return None
        m = self._models.get(self._key(listing))
        if not m or not m.fitted:
            pk = self._parent_ward_key(listing)
            if pk:
                m = self._models.get(pk)
            if not m or not m.fitted:
                m = self._models.get(self._fallback_key(listing))
        if not m or not m.fitted or not listing.price_per_m2: return None
        fair = m.predict_fair_ppm2(listing)
        if not fair: return None
        actual = listing.price_per_m2
        discount = (fair - actual) / fair
        base_threshold = m.mos_threshold()
        provisional_score = compute_signal_score(listing, discount * 100)
        quality_flags = tuple(sorted(_source_flags(listing)))
        source_quality_recheck = bool(
            _is_guland(listing)
            and (set(quality_flags) & SOURCE_SIGNAL_SUPPRESS_FLAGS)
            and discount >= base_threshold
        )
        is_sig = _passes_source_signal_gate(listing, discount, base_threshold, provisional_score)
        # Tin có ward=NULL/unknown → KHÔNG signal: hoặc nằm ngoài TDM (bị blacklist),
        # hoặc địa chỉ không xác định → không đáng tin để so segment.
        # (Vẫn lưu valuation result để audit nhưng is_signal=False)
        if not listing.ward or listing.ward == 'unknown':
            is_sig = False
        # Gate signal khi mẫu so sánh quá yếu (segment dưới ngưỡng regression-fit).
        # Khi n_samples < MIN_RELIABLE_N_FOR_SIGNAL, fair_value đã rơi về median fallback —
        # không đủ tin cậy để gắn cờ signal dù MOS lớn. Vẫn lưu valuation_result để audit.
        if m.n_samples < MIN_RELIABLE_N_FOR_SIGNAL and not listing.review_recheck_candidate:
            is_sig = False
        if _has_legal_conflict(listing):
            is_sig = False
        sigma = (actual - m.mean_ppm2) / m.std_ppm2 if m.std_ppm2 else 0
        
        # HARD OUTLIER CHECK: Tân An / Tương Bình Hiệp / Định Hòa giá > 100tr/m2 là cực kỳ vô lý
        # (Chủ yếu do lỗi parsing diện tích hoặc tin rác)
        is_hard_outlier = False
        if listing.ward in ["Tân An", "Tương Bình Hiệp", "Định Hòa", "Hiệp An"] and actual > 100:
            is_hard_outlier = True

        note = []
        if listing.is_hot: note.append("🔴 Tin ngộp")
        if not _effective_has_so(listing): note.append("⚠️ Chưa sổ")
        if is_sig: note.append(f"✅ MOS {discount:.0%}")

        if source_quality_recheck:
            note.append("source_qc")
        if _has_legal_conflict(listing):
            note.append("legal_conflict")

        score = provisional_score if is_sig else 0

        return ValuationResult(
            listing_id=listing.id, area=listing.area, property_type=listing.property_type,
            price_per_m2_actual=round(actual, 2), price_per_m2_fair=round(fair, 2),
            discount_pct=round(discount*100, 1), is_signal=is_sig, confidence=m.confidence_level(),
            segment_n=m.n_samples, signal_score=score,
            is_outlier=abs(sigma)>2 or is_hard_outlier, 
            outlier_direction='low' if sigma<-2 else ('high' if (sigma>2 or is_hard_outlier) else ''),
            outlier_sigma=round(max(abs(sigma), 5.0 if is_hard_outlier else 0), 2), 
            note=' | '.join(note),
            source_quality_flags=quality_flags,
            source_quality_recheck=source_quality_recheck,
            legal_status=getattr(listing, "legal_status", "unverified") or "unverified",
            trust_tier=getattr(listing, "trust_tier", "candidate_signal") or "candidate_signal",
            trust_score=int(getattr(listing, "trust_score", 0) or 0),
            legal_flags=tuple(sorted(_legal_flags(listing))),
        )

    def valuate_batch(self, listings: List[Listing]) -> List[ValuationResult]:
        results = []
        for l in listings:
            r = self.valuate(l)
            if r: results.append(r)
        return results

    def get_segment_stats(self) -> List[Dict]:
        stats = []
        for key, model in self._models.items():
            if model.fitted and model.mean_ppm2:
                stats.append({
                    'area': key[0], 'property_type': key[1], 'tx_type': key[2],
                    'mean_ppm2': round(model.mean_ppm2, 2),
                    'std_ppm2': round(model.std_ppm2 or 0, 2),
                    'n_samples': model.n_samples,
                    'confidence': model.confidence_level(),
                    'has_regression': model.beta is not None,
                })
        return sorted(stats, key=lambda x: (x['area'], x['property_type']))
