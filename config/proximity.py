"""Ward-level proximity scoring for signal ranking.

This is intentionally coarse: current listings do not have reliable lat/lng, so
we use ward/sub-ward level market knowledge only. The score boosts ranking; it
does not change fair value or MOS.
"""

import unicodedata

from config.area_profiles import ALL_SUBWARDS


def _key(value: str) -> str:
    text = unicodedata.normalize("NFD", value or "")
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return " ".join(text.lower().split())


# 0-5 boost for proximity to recurring investment drivers:
# TDM center/QL13, amenity hubs (schools/hospitals/admin center), and KCN/VSIP
# access. Values are deliberately capped and coarse because ward centroids are
# the most reliable location layer currently available.
WARD_PROXIMITY_SCORES = {
    # Thu Dau Mot core and QL13/amenity-heavy wards.
    "Phú Cường": 5,
    "Chánh Nghĩa": 5,
    "Phú Hòa": 4,
    "Phú Lợi": 4,
    "Hiệp Thành": 4,
    "Tương Bình Hiệp": 4,
    "Hiệp An": 3,
    "Định Hòa": 3,
    "Chánh Mỹ": 3,
    "Phú Mỹ": 3,
    "Phú Thọ": 3,
    "Tân An": 2,
    "Phú Tân": 2,

    # Hiep Thanh sub-zones inherit the parent proximity unless a better manual
    # score is known.
    "Hiệp Thành 1": 4,
    "Hiệp Thành 2": 4,
    "Hiệp Thành 3": 4,
    "KDC K8 Hiệp Thành": 4,

    # Ben Cat / My Phuoc industrial and VSIP-facing markets.
    "Mỹ Phước": 4,
    "Mỹ Phước 1": 4,
    "Mỹ Phước 2": 4,
    "Mỹ Phước 3": 5,
    "Mỹ Phước 4": 4,
    "Hòa Lợi": 4,
    "Chánh Phú Hòa": 4,
    "Thới Hòa": 3,
    "Tân Định": 3,
    "An Tây": 3,
    "An Điền": 3,
    "Phú An": 2,
}

_SCORES_BY_KEY = {_key(k): int(v) for k, v in WARD_PROXIMITY_SCORES.items()}


def proximity_score_for_ward(ward: str) -> int:
    """Return a bounded 0-5 ward-level location boost."""
    k = _key(ward)
    if not k or k == "unknown":
        return 0
    if k in _SCORES_BY_KEY:
        return _SCORES_BY_KEY[k]

    parent = ALL_SUBWARDS.get(ward)
    if parent:
        return _SCORES_BY_KEY.get(_key(parent), 0)
    return 0
