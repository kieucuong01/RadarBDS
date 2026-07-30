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
from services.signal_quality import ACTIONABLE_SUPPRESS_FLAGS

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
DEFAULT_BASELINE_SOURCES = ("facebook",)
PRIMARY_BASELINE_MIN_CANONICAL_N = 35
SUPPLEMENTAL_BASELINE_SOURCE = "guland"
SUPPLEMENTAL_BASELINE_WEIGHT = 0.40
SUPPLEMENTAL_GULAND_OLD_POST_DAYS = 14
SUPPLEMENTAL_LARGE_LOT_AREA_M2 = 1000.0

FAIR_FLOOR_RATIO = 0.70
EXPECTED_NEGOTIATION_RATIO = 0.95

RIDGE_LAMBDA = 1.0
TIER3_MAX_OF_TIER2 = 0.80
# NOTE 2026-05-05: CV_MULTIPLIER đã bị loại — xem mos_threshold() comment.

SIZE_DISCOUNT_ALPHA = {
    'dat_nen':  0.60,
    'nha_dat':  0.50,
    'nha_tro':  0.40,
}
SIZE_DISCOUNT_CAP   = (0.65, 1.20)
DEEP_LOT_MODEL_RISK_RATIO = 12.0
LOT_SHAPE_PROP_TYPES = {'dat_nen', 'nha_dat', 'nha_tro'}

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
MAIN_MODEL_VERSION = "road_tier_hierarchical_v1"
MIN_ROAD_BUCKET_SAMPLES = 8
SHRINKAGE_PRIOR_N = 12
ROAD_BUCKET_FALLBACK_MULTIPLIER = {
    1: 1.15,
    2: 1.00,
    3: 0.85,
    4: 0.65,
}

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
    posted_at:      Optional[date] = None
    url:            str = ''
    contact_phone:  str = ''
    title:          str = ''
    description:    str = ''
    source:         str = ''
    duplicate_of_id: Optional[int] = None
    exclude_from_baseline: bool = False
    baseline_weight: float = 1.0
    source_quality_flags:  Tuple[str, ...] = field(default_factory=tuple)
    review_recheck_candidate: bool = False
    positive_feedback: bool = False
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
        source_weight = float(getattr(l, "baseline_weight", 1.0) or 1.0)
        weights.append(math.exp(-max(age, 0) / TIME_DECAY_DAYS) * max(source_weight, 0.01))
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


def _road_bucket(road_tier: Optional[int]) -> int:
    tier = int(road_tier or 0)
    if tier == 1:
        return 1
    if tier == 2:
        return 2
    if tier == 3:
        return 3
    if tier >= 4:
        return 4
    return 3


def _weighted_center(items: List[Listing]) -> float:
    prices = np.array([float(item.price_per_m2) for item in items], dtype=float)
    weights = np.array([
        max(float(getattr(item, "baseline_weight", 1.0) or 1.0), 0.01)
        for item in items
    ], dtype=float)
    return float(np.average(prices, weights=weights))


def _main_area_adjustment(area_m2: Optional[float], ref_area_m2: Optional[float]) -> float:
    if not area_m2 or not ref_area_m2 or area_m2 <= 0 or ref_area_m2 <= 0:
        return 1.0
    ratio = float(area_m2) / float(ref_area_m2)
    if ratio <= 0.7:
        return 1.05
    if ratio <= 1.5:
        return 1.0
    if ratio <= 3.0:
        return 0.90
    if ratio <= 6.0:
        return 0.80
    return 0.65


def _lot_shape_adjustment(
    frontage_m: Optional[float],
    depth_m: Optional[float],
) -> Tuple[float, Tuple[str, ...], Dict[str, Optional[float]]]:
    audit = {
        "frontage_m": round(float(frontage_m), 2) if frontage_m else None,
        "depth_m": round(float(depth_m), 2) if depth_m else None,
        "depth_ratio": None,
        "shape_adjustment": 1.0,
    }
    if not frontage_m or not depth_m:
        return 1.0, (), audit
    frontage = float(frontage_m)
    depth = float(depth_m)
    if frontage <= 0 or depth <= 0 or frontage < 2 or frontage > 50 or depth < 5 or depth > 500:
        return 1.0, (), audit

    ratio = depth / frontage
    audit["depth_ratio"] = round(ratio, 2)
    if ratio <= 4.5:
        factor = 1.0
    elif ratio <= 6.5:
        factor = 0.95
    elif ratio <= 8.5:
        factor = 0.88
    elif ratio <= DEEP_LOT_MODEL_RISK_RATIO:
        factor = 0.78
    else:
        factor = 0.68
    audit["shape_adjustment"] = factor
    flags = ("deep_lot_model_risk",) if ratio >= DEEP_LOT_MODEL_RISK_RATIO else ()
    return factor, flags, audit

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
            if eff_tier == 3:
                tier2_x_list = [1.0, log_area, 0.0, 0.0, 0.0]
                for w in self.wards_in_model:
                    tier2_x_list.append(1.0 if listing.ward == w else 0.0)
                tier2_fair = float(np.array(tier2_x_list) @ self.beta)
                if tier2_fair and tier2_fair > 0:
                    base_fair = min(base_fair, tier2_fair * TIER3_MAX_OF_TIER2)
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
        if prop_type in LOT_SHAPE_PROP_TYPES:
            shape_factor, _, _ = _lot_shape_adjustment(listing.frontage_m, listing.depth_m)
            base_fair *= shape_factor
        
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


class RoadTierSegmentModel:
    """Main valuation segment model using road buckets, not regression."""

    def __init__(self, segment_key: Tuple[str, str, str], fallback_level: str = "exact"):
        self.segment_key = segment_key
        self.fallback_level = fallback_level
        self.beta = None
        self.median_ppm2 = 0.0
        self.mean_ppm2 = 0.0
        self.std_ppm2 = 0.0
        self.std_ppm2_core = 0.0
        self.ref_area_m2 = 0.0
        self.n_samples = 0
        self.fitted = False
        self.bucket_medians: Dict[int, float] = {}
        self.bucket_counts: Dict[int, int] = {}

    def fit(self, listings: List[Listing]):
        if not listings:
            return
        today = date.today()
        deduped = []
        seen_urls = set()
        for listing in sorted(listings, key=lambda x: x.crawled_at or date.min, reverse=True):
            if listing.crawled_at and (today - listing.crawled_at).days > 180:
                continue
            if listing.url and listing.url not in seen_urls:
                seen_urls.add(listing.url)
                deduped.append(listing)
            elif not listing.url:
                deduped.append(listing)

        known = [
            listing for listing in deduped
            if listing.price_per_m2 and listing.area_m2 and listing.area_m2 > 0
            and (listing.road_tier or 0) > 0
        ]
        if len(known) < 3:
            return

        ppm2 = np.array([listing.price_per_m2 for listing in known], dtype=float)
        mean, std = float(np.mean(ppm2)), float(np.std(ppm2))
        if std > 0:
            known = [
                listing for listing in known
                if mean - 2 * std <= listing.price_per_m2 <= mean + 2 * std
            ]
        if len(known) >= 3:
            ppm2 = np.array([listing.price_per_m2 for listing in known], dtype=float)
            mean, std = float(np.mean(ppm2)), float(np.std(ppm2))
            if std > 0:
                known = [
                    listing for listing in known
                    if mean - 2 * std <= listing.price_per_m2 <= mean + 2 * std
                ]
        if len(known) < 3:
            return

        values = [float(listing.price_per_m2) for listing in known]
        self.n_samples = len(known)
        self.median_ppm2 = _weighted_center(known)
        self.mean_ppm2 = float(np.mean(values))
        self.std_ppm2 = float(np.std(values))
        self.std_ppm2_core = self.std_ppm2
        areas = [float(listing.area_m2) for listing in known if listing.area_m2 and listing.area_m2 > 0]
        self.ref_area_m2 = float(np.median(areas)) if areas else 100.0

        by_bucket: Dict[int, List[float]] = {}
        bucket_items: Dict[int, List[Listing]] = {}
        for listing in known:
            bucket = _road_bucket(listing.road_tier)
            by_bucket.setdefault(bucket, []).append(float(listing.price_per_m2))
            bucket_items.setdefault(bucket, []).append(listing)
        for bucket, prices in by_bucket.items():
            self.bucket_counts[bucket] = len(prices)
            self.bucket_medians[bucket] = _weighted_center(bucket_items[bucket])
        self._enforce_monotonic_road_buckets()
        self.fitted = True

    def _enforce_monotonic_road_buckets(self):
        if 3 in self.bucket_medians and 4 in self.bucket_medians:
            self.bucket_medians[3] = max(self.bucket_medians[3], self.bucket_medians[4] / 0.75)
        if 2 in self.bucket_medians and 4 in self.bucket_medians and 3 not in self.bucket_medians:
            self.bucket_medians[2] = max(self.bucket_medians[2], self.bucket_medians[4] / (0.85 * 0.75))
        if 2 in self.bucket_medians and 3 in self.bucket_medians:
            self.bucket_medians[2] = max(self.bucket_medians[2], self.bucket_medians[3] / 0.85)
        if 1 in self.bucket_medians and 2 in self.bucket_medians:
            self.bucket_medians[1] = max(self.bucket_medians[1], self.bucket_medians[2] * 1.15)

    def bucket_base_ppm2(
        self,
        listing: Listing,
        min_samples: int = MIN_ROAD_BUCKET_SAMPLES,
    ) -> Tuple[Optional[float], str, int]:
        bucket = _road_bucket(listing.road_tier)
        count = self.bucket_counts.get(bucket, 0)
        if count >= min_samples and bucket in self.bucket_medians:
            return self.bucket_medians[bucket], f"road_bucket_{bucket}", count
        return None, f"road_bucket_{bucket}_sparse", count

    def sparse_bucket_base_ppm2(self, listing: Listing) -> Tuple[Optional[float], str, int]:
        bucket = _road_bucket(listing.road_tier)
        count = self.bucket_counts.get(bucket, 0)
        if count > 0 and bucket in self.bucket_medians:
            return self.bucket_medians[bucket], f"road_bucket_{bucket}_sparse", count
        return None, f"road_bucket_{bucket}_missing", 0

    def fallback_base_ppm2(self, listing: Listing) -> Tuple[Optional[float], str, int]:
        if not self.median_ppm2:
            return None, "missing", 0
        bucket = _road_bucket(listing.road_tier)
        multiplier = ROAD_BUCKET_FALLBACK_MULTIPLIER.get(bucket, 1.0)
        count = self.bucket_counts.get(bucket, 0)
        return self.median_ppm2 * multiplier, f"segment_median_adjusted_bucket_{bucket}", count

    def predict_fair_ppm2(self, listing: Listing, base_override: Optional[float] = None) -> Optional[float]:
        if not self.fitted:
            return None
        base_fair = base_override
        if base_fair is None:
            base_fair, _, _ = self.bucket_base_ppm2(listing)
        if base_fair is None:
            base_fair, _, _ = self.fallback_base_ppm2(listing)
        if not base_fair or base_fair <= 0:
            return None

        if self.segment_key[1] in SIZE_DISCOUNT_ALPHA:
            base_fair *= _main_area_adjustment(listing.area_m2, self.ref_area_m2)
        if self.segment_key[1] in LOT_SHAPE_PROP_TYPES:
            shape_factor, _, _ = _lot_shape_adjustment(listing.frontage_m, listing.depth_m)
            base_fair *= shape_factor

        feat = extract_regex_features(f"{listing.title} {listing.description}")
        if feat.get('is_corner'): base_fair *= 1.10
        if feat.get('is_nở_hậu'): base_fair *= 1.05
        if feat.get('is_thắt_hậu'): base_fair *= 0.90
        if feat.get('is_đường_đâm'): base_fair *= 0.85
        if feat.get('near_grave'): base_fair *= 0.80

        if not _effective_has_so(listing):
            base_fair *= 0.75
        base_fair *= EXPECTED_NEGOTIATION_RATIO
        return round(base_fair, 2) if base_fair > 0 else None

    def confidence_level(self):
        if self.n_samples >= 45:
            return 'high'
        return 'medium' if self.n_samples >= MIN_RELIABLE_N_FOR_SIGNAL else 'low'

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

    def _cluster_key(self, l):
        from config.market_clusters import cluster_for_ward
        cluster = cluster_for_ward(l.ward)
        if cluster:
            return (f"market_cluster:{cluster.cluster_id}", l.property_type, l.tx_type)
        return None

    def _dedupe_training_lots(self, listings: List[Listing]) -> List[Listing]:
        lots: Dict[int, Listing] = {}
        for listing in listings:
            lot_id = getattr(listing, "duplicate_of_id", None) or listing.id
            if not lot_id:
                lots[id(listing)] = listing
                continue
            current = lots.get(lot_id)
            if current is None:
                lots[lot_id] = listing
                continue
            # Prefer the canonical row when it is present; otherwise keep the
            # latest available duplicate in the group.
            if listing.id == lot_id and current.id != lot_id:
                lots[lot_id] = listing
                continue
            if current.id != lot_id and (listing.crawled_at or date.min) > (current.crawled_at or date.min):
                lots[lot_id] = listing
        return list(lots.values())

    def _is_primary_baseline_source(self, listing: Listing) -> bool:
        source = (getattr(listing, "source", "") or "").strip().lower()
        return not self._baseline_sources or not source or source in self._baseline_sources

    def _is_strict_supplemental_baseline(self, listing: Listing) -> bool:
        source = (getattr(listing, "source", "") or "").strip().lower()
        if source != SUPPLEMENTAL_BASELINE_SOURCE:
            return False
        if getattr(listing, "exclude_from_baseline", False) or _source_flags(listing):
            return False
        if not listing.ward or listing.ward == "unknown":
            return False
        if not listing.price_total or not listing.price_per_m2 or not listing.area_m2:
            return False
        if listing.area_m2 >= SUPPLEMENTAL_LARGE_LOT_AREA_M2:
            if (listing.road_tier or 0) <= 0:
                return False
        posted = getattr(listing, "posted_at", None)
        crawled = getattr(listing, "crawled_at", None)
        if posted and crawled and (crawled - posted).days >= SUPPLEMENTAL_GULAND_OLD_POST_DAYS:
            return False
        return True

    def _add_training_listing(self, groups, cluster_groups, parent_groups, fallback_groups, listing: Listing):
        from config.area_profiles import ALL_SUBWARDS
        groups[self._key(listing)].append(listing)
        cluster_key = self._cluster_key(listing)
        if cluster_key:
            cluster_groups[cluster_key].append(listing)
        fallback_groups[self._fallback_key(listing)].append(listing)
        parent = ALL_SUBWARDS.get(listing.ward)
        if parent:
            parent_groups[(parent, listing.property_type, listing.tx_type)].append(listing)

    def _combine_primary_and_supplemental(self, primary_groups, supplemental_groups):
        combined = {}
        for key in set(primary_groups) | set(supplemental_groups):
            primary = primary_groups.get(key, [])
            if len(primary) < PRIMARY_BASELINE_MIN_CANONICAL_N:
                listings = primary + supplemental_groups.get(key, [])
            else:
                listings = primary
            if listings:
                combined[key] = listings
        return combined

    def fit(self, listings, conn=None):
        from collections import defaultdict
        listings = self._dedupe_training_lots(listings)
        primary_segs = defaultdict(list)
        primary_cluster_segs = defaultdict(list)
        primary_fallback_segs = defaultdict(list)
        primary_parent_segs = defaultdict(list)
        supplemental_segs = defaultdict(list)
        supplemental_cluster_segs = defaultdict(list)
        supplemental_fallback_segs = defaultdict(list)
        supplemental_parent_segs = defaultdict(list)
        for l in listings:
            if l.property_type in SPECIAL_MARKET_SKIP_TYPES:
                continue  # chưa đủ data — skip segment build
            if getattr(l, "exclude_from_baseline", False) or _source_flags(l):
                continue
            if not (l.price_per_m2 and l.area_m2):
                continue
            if self._is_primary_baseline_source(l):
                l.baseline_weight = 1.0
                self._add_training_listing(
                    primary_segs, primary_cluster_segs, primary_parent_segs, primary_fallback_segs, l
                )
            elif self._is_strict_supplemental_baseline(l):
                l.baseline_weight = SUPPLEMENTAL_BASELINE_WEIGHT
                self._add_training_listing(
                    supplemental_segs, supplemental_cluster_segs, supplemental_parent_segs, supplemental_fallback_segs, l
                )
        segs = self._combine_primary_and_supplemental(primary_segs, supplemental_segs)
        cluster_segs = self._combine_primary_and_supplemental(
            primary_cluster_segs, supplemental_cluster_segs
        )
        parent_segs = self._combine_primary_and_supplemental(
            primary_parent_segs, supplemental_parent_segs
        )
        fallback_segs = self._combine_primary_and_supplemental(
            primary_fallback_segs, supplemental_fallback_segs
        )
        for k, ls in segs.items():
            m = RoadTierSegmentModel(k, fallback_level="exact")
            m.fit(ls)
            self._models[k] = m
        for k, ls in cluster_segs.items():
            m = RoadTierSegmentModel(k, fallback_level=k[0])
            m.fit(ls)
            self._models[k] = m
        # Parent ward aggregate (e.g. "Mỹ Phước" from MP1+MP2+MP3+MP4 + generic)
        for k, ls in parent_segs.items():
            existing = segs.get(k, [])
            combined = existing + ls
            m = RoadTierSegmentModel(k, fallback_level="parent")
            m.fit(combined)
            self._models[k] = m
        # SELECTED_REGION: fallback cho ward=null/unknown
        for k, ls in fallback_segs.items():
            m = RoadTierSegmentModel(k, fallback_level="region")
            m.fit(ls)
            self._models[k] = m

    def _candidate_models(self, listing: Listing) -> List[RoadTierSegmentModel]:
        keys = [self._key(listing), self._cluster_key(listing), self._parent_ward_key(listing), self._fallback_key(listing)]
        models = []
        seen = set()
        for key in keys:
            if not key or key in seen:
                continue
            seen.add(key)
            model = self._models.get(key)
            if model and model.fitted:
                models.append(model)
        return models

    def _select_pricing_basis(
        self,
        listing: Listing,
    ) -> Optional[Tuple[RoadTierSegmentModel, float, str, int]]:
        candidates = self._candidate_models(listing)
        if not candidates:
            return None

        exact = candidates[0]
        exact_base, exact_basis, exact_count = exact.bucket_base_ppm2(listing)
        if exact_base is not None:
            return exact, exact_base, f"{exact.fallback_level}:{exact_basis}", exact_count

        sparse_base, sparse_basis, sparse_count = exact.sparse_bucket_base_ppm2(listing)
        for model in candidates[1:]:
            broad_base, broad_basis, broad_count = model.bucket_base_ppm2(listing)
            if broad_base is None:
                continue
            if sparse_base is not None and sparse_count > 0:
                weight = sparse_count / (sparse_count + SHRINKAGE_PRIOR_N)
                blended = sparse_base * weight + broad_base * (1.0 - weight)
                basis = (
                    f"shrink:{exact.fallback_level}:{sparse_basis}:n={sparse_count}"
                    f"+{model.fallback_level}:{broad_basis}:n={broad_count}"
                )
                return model, blended, basis, broad_count
            return model, broad_base, f"{model.fallback_level}:{broad_basis}", broad_count

        if sparse_base is not None and sparse_count > 0:
            return exact, sparse_base, f"{exact.fallback_level}:{sparse_basis}", sparse_count

        for model in candidates:
            fallback_base, fallback_basis, fallback_count = model.fallback_base_ppm2(listing)
            if fallback_base is not None:
                return model, fallback_base, f"{model.fallback_level}:{fallback_basis}", fallback_count
        return None

    def valuate(self, listing: Listing) -> Optional[ValuationResult]:
        # Special markets: giá/m² và logic định giá khác đất/nhà, chưa đủ data để
        # build segment regression riêng → skip valuation. Tin vẫn hiển thị nhưng
        # không có fair_value/MOS. Khi đủ data (n≥30) sẽ build model riêng.
        if listing.property_type in SPECIAL_MARKET_SKIP_TYPES:
            return None
        if not (listing.price_total and listing.price_per_m2 and listing.area_m2):
            return None
        selection = self._select_pricing_basis(listing)
        if not selection or not listing.price_per_m2:
            return None
        m, base_ppm2, price_basis, basis_count = selection
        fair = m.predict_fair_ppm2(listing, base_override=base_ppm2)
        if not fair: return None
        actual = listing.price_per_m2
        discount = (fair - actual) / fair
        base_threshold = m.mos_threshold()
        provisional_score = compute_signal_score(listing, discount * 100)
        quality_flags = set(_source_flags(listing))
        if (listing.road_tier or 0) <= 0:
            quality_flags.add("low_road_confidence")
        model_signal = discount >= base_threshold
        if (
            m.n_samples < MIN_RELIABLE_N_FOR_SIGNAL
            and not listing.review_recheck_candidate
            and not listing.positive_feedback
        ):
            quality_flags.add("low_segment_confidence")
        source_quality_recheck = bool(
            model_signal and (quality_flags & ACTIONABLE_SUPPRESS_FLAGS)
        )
        is_sig = model_signal
        # Tin có ward=NULL/unknown → KHÔNG signal: hoặc nằm ngoài TDM (bị blacklist),
        # hoặc địa chỉ không xác định → không đáng tin để so segment.
        # (Vẫn lưu valuation result để audit nhưng is_signal=False)
        if not listing.ward or listing.ward == 'unknown':
            is_sig = False
        # Gate signal khi mẫu so sánh quá yếu (segment dưới ngưỡng regression-fit).
        # Khi n_samples < MIN_RELIABLE_N_FOR_SIGNAL, fair_value đã rơi về median fallback —
        # không đủ tin cậy để gắn cờ signal dù MOS lớn. Vẫn lưu valuation_result để audit.
        if _has_legal_conflict(listing):
            is_sig = False
        sigma = (actual - m.mean_ppm2) / m.std_ppm2 if m.std_ppm2 else 0
        
        # HARD OUTLIER CHECK: Tân An / Tương Bình Hiệp / Định Hòa giá > 100tr/m2 là cực kỳ vô lý
        # (Chủ yếu do lỗi parsing diện tích hoặc tin rác)
        is_hard_outlier = False
        if listing.ward in ["Tân An", "Tương Bình Hiệp", "Định Hòa", "Hiệp An"] and actual > 100:
            is_hard_outlier = True

        note = [
            f"model={MAIN_MODEL_VERSION}",
            f"basis={price_basis}",
            f"basis_n={basis_count}",
        ]
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
            source_quality_flags=tuple(sorted(quality_flags)),
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
