"""Deterministic intent parsing for the public RadarBDS assistant.

This module intentionally does not call an LLM. It extracts the small set of
investor-facing intents that the assistant can safely fulfill with internal
data and existing UI actions.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

from services.market_data import CITY_MAP


DEFAULT_SUGGESTED_QUESTIONS = [
    "Tìm deal theo ngân sách",
    "Hôm nay có gì đáng xem?",
    "Tạo bộ lọc săn deal",
    "So sánh Tân An và Chánh Nghĩa",
    "Checklist đi xem đất",
    "Giải thích MOS",
]


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    return "".join(ch for ch in normalized if not unicodedata.combining(ch)).lower()


def _contains_any(text: str, needles: list[str]) -> bool:
    return any(n in text for n in needles)


_WARD_ALIASES: list[tuple[str, str]] = []
for _city, _wards in CITY_MAP.items():
    for _ward in _wards:
        _WARD_ALIASES.append((_fold(_ward), _ward))

_EXTRA_WARD_ALIASES = {
    "tan an": "Tân An",
    "chanh nghia": "Chánh Nghĩa",
    "chanh my": "Chánh Mỹ",
    "hiep an": "Hiệp An",
    "dinh hoa": "Định Hòa",
    "tuong binh hiep": "Tương Bình Hiệp",
    "phu my": "Phú Mỹ",
    "phu hoa": "Phú Hòa",
    "my phuoc": "Mỹ Phước",
    "my phuoc 1": "Mỹ Phước 1",
    "my phuoc 2": "Mỹ Phước 2",
    "my phuoc 3": "Mỹ Phước 3",
}
for _alias, _ward in _EXTRA_WARD_ALIASES.items():
    _WARD_ALIASES.append((_alias, _ward))


def detect_wards(text_folded: str) -> list[str]:
    seen: set[str] = set()
    wards: list[str] = []
    for alias, ward in sorted(_WARD_ALIASES, key=lambda item: len(item[0]), reverse=True):
        if alias and re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", text_folded):
            if ward not in seen:
                wards.append(ward)
                seen.add(ward)
    return wards[:5]


def _parse_price_ty(text_folded: str) -> float | None:
    patterns = [
        r"(?:duoi|toi da|max|tam|khoang|ngan sach|co)\s*(\d+(?:[,.]\d+)?)\s*(?:ty|ti)\b",
        r"(\d+(?:[,.]\d+)?)\s*(?:ty|ti)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text_folded)
        if match:
            try:
                value = float(match.group(1).replace(",", "."))
            except ValueError:
                continue
            if 0.1 <= value <= 500:
                return value
    return None


def _parse_mos(text_folded: str) -> int | None:
    match = re.search(r"(?:mos|re hon|bien an toan)\s*(?:>=|tren|hon|toi thieu)?\s*(\d{1,2})\s*%?", text_folded)
    if not match:
        match = re.search(r"(\d{1,2})\s*%\s*(?:mos|re hon|bien an toan)", text_folded)
    if not match:
        return None
    value = int(match.group(1))
    return max(0, min(70, value - value % 5))


def _detect_property_types(text_folded: str) -> list[str]:
    prop_types: list[str] = []
    if re.search(r"\b(dat nen|dat tho cu|lo dat|dat o|dat vuon|vuon|mau|sao)\b", text_folded):
        prop_types.append("dat_nen")
    if re.search(r"\b(nha dat|nha pho|nha rieng|nha cap)\b", text_folded):
        prop_types.append("nha_dat")
    if re.search(r"\b(chung cu|can ho|apartment)\b", text_folded):
        prop_types.append("chung_cu")
    if re.search(r"\b(nha tro|phong tro|day tro)\b", text_folded):
        prop_types.append("nha_tro")
    return prop_types or (["dat_nen"] if "dat" in text_folded and "nha" not in text_folded else [])


def _filter_from_entities(entities: dict[str, Any]) -> dict[str, Any]:
    filt: dict[str, Any] = {}
    wards = entities.get("wards") or []
    prop_types = entities.get("prop_types") or []
    if wards:
        filt["ward"] = wards
    if prop_types:
        filt["property_type"] = prop_types
    if entities.get("price_max_ty") is not None:
        filt["price_max"] = entities["price_max_ty"]
    if entities.get("price_min_ty") is not None:
        filt["price_min"] = entities["price_min_ty"]
    if entities.get("mos_min") is not None:
        filt["mos_min"] = entities["mos_min"]
    elif entities.get("only_drops") or wards or prop_types or entities.get("price_max_ty") is not None:
        filt["mos_min"] = 10
    if entities.get("only_drops"):
        filt["only_drops"] = True
    return filt


def parse_assistant_intent(message: str) -> dict[str, Any]:
    raw = (message or "").strip()
    text = _fold(raw)
    entities: dict[str, Any] = {
        "wards": detect_wards(text),
        "prop_types": _detect_property_types(text),
        "price_max_ty": _parse_price_ty(text),
        "mos_min": _parse_mos(text),
        "only_drops": _contains_any(text, ["giam gia", "rot gia", "ha gia", "co giam", "price drop"]),
    }

    listing_match = re.search(r"\b(?:tin|ma|id|listing)\s*#?\s*(\d{4,7})\b", text)
    if listing_match and _contains_any(text, ["dang mua", "co nen", "rui ro", "gia", "mua khong", "phan tich"]):
        entities["listing_id"] = int(listing_match.group(1))
        return {
            "intent": "listing_specific_redirect",
            "entities": entities,
            "filter": {},
            "confidence": 0.95,
        }

    if _contains_any(text, ["checklist", "can kiem tra", "di xem can gi"]):
        return {"intent": "viewing_checklist", "entities": entities, "filter": {}, "confidence": 0.88}

    if _contains_any(text, ["de lai zalo", "lien he", "di xem", "xem dat", "rap moi", "co ai ho tro"]):
        return {"intent": "lead_intent", "entities": entities, "filter": {}, "confidence": 0.9}

    wants_watchlist = _contains_any(text, ["watchlist", "luu bo loc", "luu loc", "bao tin", "thong bao"])
    if wants_watchlist:
        filt = _filter_from_entities(entities)
        if not filt.get("mos_min"):
            filt["mos_min"] = 15
        return {"intent": "watchlist_create", "entities": entities, "filter": filt, "confidence": 0.88}

    if _contains_any(text, ["so sanh", "khac giua", "khu nao hon"]):
        return {
            "intent": "compare_areas",
            "entities": entities,
            "filter": _filter_from_entities(entities),
            "confidence": 0.82,
        }

    if _contains_any(text, ["hom nay", "dang xem", "thi truong", "tong quan", "deal nao"]) or re.search(r"\bco gi\b", text):
        return {
            "intent": "market_summary",
            "entities": entities,
            "filter": _filter_from_entities(entities),
            "confidence": 0.82,
        }

    wants_metric_explain = _contains_any(text, ["giai thich", "la gi", "nghia la gi", "model cu", "model moi", "road tier"])
    has_filter_entities = bool(_filter_from_entities(entities))
    if _contains_any(text, ["mos", "model cu", "model moi", "road tier", "co giam gia", "re hon"]) and (
        wants_metric_explain or not has_filter_entities
    ):
        return {"intent": "explain_metric", "entities": entities, "filter": {}, "confidence": 0.86}

    if _contains_any(text, ["chien luoc", "luot song", "giu dai han", "tich san", "thanh khoan", "nen san"]):
        return {
            "intent": "investment_strategy",
            "entities": entities,
            "filter": _filter_from_entities(entities),
            "confidence": 0.82,
        }

    filt = _filter_from_entities(entities)
    if filt or _contains_any(text, ["tim", "loc", "san", "ngan sach", "duoi", "toi da"]):
        return {"intent": "build_filter", "entities": entities, "filter": filt, "confidence": 0.8}

    return {"intent": "help", "entities": entities, "filter": {}, "confidence": 0.55}
