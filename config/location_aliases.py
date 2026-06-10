"""Post-merger location resolver for TDM and Ben Cat broker text.

The resolver separates the new administrative ward name from the old
micro-market ward used by valuation. A broad new ward is only context; it is
not enough evidence to assign a canonical valuation ward.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata


def _ascii_fold(text: str) -> str:
    folded = "".join(
        c for c in unicodedata.normalize("NFD", text or "")
        if unicodedata.category(c) != "Mn"
    ).lower()
    return folded.replace("đ", "d").replace("Đ", "d")


def _norm(text: str) -> str:
    folded = _ascii_fold(text)
    folded = re.sub(r"[._,;:/()\-]+", " ", folded)
    return re.sub(r"\s+", " ", folded).strip()


@dataclass(frozen=True)
class LocationAliasResult:
    new_ward: str | None = None
    ward: str | None = None
    evidence_type: str | None = None
    evidence: str | None = None
    confidence: str = "none"

    @property
    def has_strong_old_ward(self) -> bool:
        return bool(self.ward and self.confidence == "strong")

    @property
    def has_weak_old_ward(self) -> bool:
        return bool(self.ward and self.confidence == "weak")

    @property
    def is_broad_new_ward_only(self) -> bool:
        return bool(self.new_ward and not self.ward and self.evidence_type == "new_ward_only")

    def blocks_broad_ward_match(self, ward: str | None) -> bool:
        if not ward or not self.is_broad_new_ward_only:
            return False
        return _ascii_fold(ward) == _ascii_fold(self.new_ward)


# Official focus-zone merger components. These names are context only unless
# another rule below finds old-ward/KP/landmark evidence.
NEW_WARD_COMPONENTS: dict[str, tuple[str, ...]] = {
    "Thủ Dầu Một": ("Phú Cường", "Phú Thọ", "Chánh Nghĩa", "Hiệp Thành", "Chánh Mỹ"),
    "Phú Lợi": ("Phú Hòa", "Phú Lợi", "Hiệp Thành"),
    "Chánh Hiệp": ("Định Hòa", "Tương Bình Hiệp", "Hiệp An", "Chánh Mỹ"),
    "Bình Dương": ("Phú Mỹ", "Hòa Phú", "Phú Tân", "Phú Chánh"),
    "Hòa Lợi": ("Tân Định", "Hòa Lợi"),
    "Phú An": ("Tân An", "Phú An", "Hiệp An"),
    "Long Nguyên": ("An Điền", "Long Nguyên", "Mỹ Phước"),
    "Bến Cát": ("Tân Hưng", "Lai Hưng", "Mỹ Phước"),
    "Chánh Phú Hòa": ("Chánh Phú Hòa", "Hưng Hòa"),
    "Thới Hòa": ("Thới Hòa",),
}


_NEW_WARD_PATTERNS = {
    ward: tuple(_norm(alias) for alias in aliases)
    for ward, aliases in {
        "Thủ Dầu Một": ("thủ dầu một", "thu dau mot"),
        "Phú Lợi": ("phú lợi", "phu loi"),
        "Chánh Hiệp": ("chánh hiệp", "chanh hiep"),
        "Bình Dương": ("bình dương", "binh duong"),
        "Hòa Lợi": ("hòa lợi", "hoà lợi", "hoa loi"),
        "Phú An": ("phú an", "phu an"),
        "Long Nguyên": ("long nguyên", "long nguyen"),
        "Bến Cát": ("bến cát", "ben cat"),
        "Chánh Phú Hòa": ("chánh phú hòa", "chánh phú hoà", "chanh phu hoa"),
        "Thới Hòa": ("thới hòa", "thới hoà", "thoi hoa"),
    }.items()
}


_KHU_PHO_RULES: tuple[tuple[str, str, str], ...] = (
    ("Phú Mỹ", r"\b(?:kp|khu\s+pho)\s*phu\s+my(?:\s*[1-8])?\b", "khu_pho_phu_my"),
    ("Hòa Phú", r"\b(?:kp|khu\s+pho)\s*hoa\s+phu(?:\s*[1-5])?\b", "khu_pho_hoa_phu"),
    ("Phú Tân", r"\b(?:kp|khu\s+pho)\s*phu\s+tan(?:\s*[1-3])?\b", "khu_pho_phu_tan"),
    ("Phú Chánh", r"\b(?:kp|khu\s+pho)\s*phu\s+chanh\b", "khu_pho_phu_chanh"),
    ("Phú Chánh", r"\b(?:kp|khu\s+pho)\s*phu\s+bung\b", "khu_pho_phu_bung"),
    ("Phú Chánh", r"\b(?:kp|khu\s+pho)\s*phu\s+trung\b", "khu_pho_phu_trung"),
    ("Phú Chánh", r"\b(?:kp|khu\s+pho)\s*chanh\s+long\b", "khu_pho_chanh_long"),
    ("Tân Định", r"\b(?:kp|khu\s+pho)\s*[1-4]\s*tan\s+dinh\b", "khu_pho_tan_dinh"),
    ("Tân Định", r"\btan\s+dinh\s+cu\b", "old_ward_tan_dinh"),
    ("Hòa Lợi", r"\b(?:kp|khu\s+pho)\s*(?:[1-5]\s*)?hoa\s+loi\b", "khu_pho_hoa_loi"),
    ("Hòa Lợi", r"\bhoa\s+loi\s+cu\b", "old_ward_hoa_loi"),
)


_OLD_WARD_PHRASE_RULES: tuple[tuple[str, str, str], ...] = (
    ("Phú Mỹ", r"\bphu\s+my\s+(?:cu|truoc\s+sap\s+nhap)\b", "old_ward_phu_my"),
    ("Hòa Phú", r"\bhoa\s+phu\s+(?:cu|truoc\s+sap\s+nhap)\b", "old_ward_hoa_phu"),
    ("Phú Tân", r"\bphu\s+tan\s+(?:cu|truoc\s+sap\s+nhap)\b", "old_ward_phu_tan"),
    ("Phú Chánh", r"\bphu\s+chanh\s+(?:cu|truoc\s+sap\s+nhap)\b", "old_ward_phu_chanh"),
    ("Định Hòa", r"\bdinh\s+hoa\s+(?:cu|truoc\s+sap\s+nhap)\b", "old_ward_dinh_hoa"),
    ("Tương Bình Hiệp", r"\btuong\s+binh\s+hiep\s+(?:cu|truoc\s+sap\s+nhap)\b", "old_ward_tuong_binh_hiep"),
    ("Tân Định", r"\btan\s+dinh\s+(?:cu|truoc\s+sap\s+nhap)\b", "old_ward_tan_dinh"),
    ("Hòa Lợi", r"\bhoa\s+loi\s+(?:cu|truoc\s+sap\s+nhap)\b", "old_ward_hoa_loi"),
)


def detect_new_ward(*texts: str) -> str | None:
    normalized = _norm(" ".join(t for t in texts if t))
    if not normalized:
        return None

    for new_ward, aliases in _NEW_WARD_PATTERNS.items():
        for alias in aliases:
            if not alias:
                continue
            phuong_pattern = rf"\b(?:phuong|p)\s*{re.escape(alias)}\b"
            if re.search(phuong_pattern, normalized):
                return new_ward
            hcm_after_pattern = (
                rf"\b{re.escape(alias)}\b\s*(?:tp\s*)?"
                rf"(?:hcm|ho\s+chi\s+minh|sai\s+gon)\b"
            )
            if re.search(hcm_after_pattern, normalized):
                return new_ward
    return None


def _match_strong_old_ward(normalized: str) -> tuple[str, str, str] | None:
    for ward, pattern, evidence in _KHU_PHO_RULES:
        if re.search(pattern, normalized):
            return ward, "khu_pho", evidence
    for ward, pattern, evidence in _OLD_WARD_PHRASE_RULES:
        if re.search(pattern, normalized):
            return ward, "old_ward_phrase", evidence
    return None


def _match_weak_road_landmark(normalized: str, new_ward: str | None) -> tuple[str, str, str] | None:
    if new_ward != "Chánh Hiệp":
        return None
    if re.search(r"\bdx\s*0?7[12]\b", normalized):
        return "Định Hòa", "road_landmark", "dx071_dx072_chanh_hiep"
    return None


def resolve_post_merger_location(
    *texts: str,
    intended_city: str | None = None,
) -> LocationAliasResult:
    """Resolve post-merger address evidence without treating new wards as truth."""
    normalized = _norm(" ".join(t for t in texts if t))
    if intended_city:
        normalized = f"{normalized} {_norm(intended_city)}".strip()
    new_ward = detect_new_ward(*texts)

    strong = _match_strong_old_ward(normalized)
    if strong:
        ward, evidence_type, evidence = strong
        return LocationAliasResult(
            new_ward=new_ward,
            ward=ward,
            evidence_type=evidence_type,
            evidence=evidence,
            confidence="strong",
        )

    weak = _match_weak_road_landmark(normalized, new_ward)
    if weak:
        ward, evidence_type, evidence = weak
        return LocationAliasResult(
            new_ward=new_ward,
            ward=ward,
            evidence_type=evidence_type,
            evidence=evidence,
            confidence="weak",
        )

    if new_ward:
        return LocationAliasResult(
            new_ward=new_ward,
            evidence_type="new_ward_only",
            evidence="broad_new_ward",
            confidence="context",
        )

    return LocationAliasResult()
