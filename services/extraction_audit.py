"""Read-only extraction audit helpers for admin signal QC."""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any, Mapping

from cleansing.extraction_integrity import declared_total_area, severe_geometry_conflict
from cleansing.feature_extractor import (
    classify_property_type,
    extract_area,
    extract_dimensions,
    extract_price,
    extract_road_type,
    extract_road_tier,
    extract_road_width,
    extract_tho_cu,
)
from cleansing.normalizer import extract_road_name, match_ward
from config.location_aliases import resolve_post_merger_location


FIELD_WEIGHTS = {
    "price_ty": 5,
    "area_m2": 5,
    "ward": 4,
    "property_type": 4,
    "frontage_m": 3,
    "depth_m": 3,
    "road_width_m": 3,
    "road_type": 2,
    "road_tier": 3,
    "road_name": 2,
    "tho_cu_m2": 3,
}


DEFAULT_MANUAL_QC_PATH = Path(".local/llm-review/manual_findings.md")


def audit_listing_extraction(listing: Mapping[str, Any]) -> dict[str, Any]:
    """Compare stored extraction against high-confidence evidence in text."""
    title = str(_get(listing, "title") or "")
    description = str(_get(listing, "description") or "")
    text = " ".join(part for part in (title, description) if part).strip()
    findings: list[dict[str, Any]] = []

    price_candidates = _price_candidates(title, description)
    expected_price = _expected_price(title, description, price_candidates)
    actual_price = _to_float(_get(listing, "price_ty"))
    if expected_price is not None:
        if actual_price is None or not any(
            _close_number(actual_price, p, rel=0.08, abs_tol=0.05)
            for p in price_candidates
        ):
            findings.append(_finding(
                "price_ty",
                actual_price,
                expected_price,
                "Text contains a clear asking price that differs from stored price.",
                _evidence_for_number(text, expected_price, ("ty", "ti", "trieu", "tr")),
            ))

    declared_area = declared_total_area(text)
    expected_area = declared_area or extract_area(text)
    actual_area = _to_float(_get(listing, "area_m2"))
    dimensions = extract_dimensions(text)
    frontage = _to_float(dimensions.get("frontage_m"))
    depth = _to_float(dimensions.get("depth_m"))
    if expected_area is not None:
        if actual_area is None:
            findings.append(_finding(
                "area_m2",
                actual_area,
                expected_area,
                "Text contains a clear area/dimension but stored area is missing.",
                _evidence_for_number(text, expected_area, ("m2", "mÂ²", "mv", "x")),
            ))
        elif not _close_number(actual_area, expected_area, rel=0.05, abs_tol=2.0):
            dimension_area = frontage * depth if frontage and depth else None
            expected_is_dimension = bool(
                declared_area is None
                and dimension_area is not None
                and _close_number(expected_area, dimension_area, rel=0.03, abs_tol=2.0)
            )
            should_report = (
                not expected_is_dimension
                or severe_geometry_conflict(text, actual_area, frontage, depth)
            )
            if should_report:
                findings.append(_finding(
                    "area_m2",
                    actual_area,
                    expected_area,
                    "Text contains a clear area/dimension that differs from stored area.",
                    _evidence_for_number(text, expected_area, ("m2", "m²", "mv", "x")),
                ))

    for field, expected in (("frontage_m", frontage), ("depth_m", depth)):
        actual = _to_float(_get(listing, field))
        if expected is not None and (
            actual is None
            or not _close_number(actual, expected, rel=0.12, abs_tol=0.5)
        ):
            findings.append(_finding(
                field,
                actual,
                expected,
                "Text contains a clear lot dimension that differs from stored data.",
                _evidence_for_number(text, expected, ("m", "x")),
            ))

    location = resolve_post_merger_location(
        title,
        description,
        intended_city=str(
            _get(listing, "city") or _get(listing, "default_area") or ""
        ) or None,
    )
    if location.has_strong_old_ward:
        expected_ward = location.ward
    elif location.new_ward:
        expected_ward = None
    else:
        expected_ward = match_ward(title, description)
    actual_ward = _get(listing, "ward")
    if expected_ward and (
        not actual_ward or not _ward_compatible(str(actual_ward), expected_ward)
    ):
        findings.append(_finding(
            "ward",
            actual_ward,
            expected_ward,
            "Text has stronger ward/sub-zone evidence than the stored ward.",
            _evidence_for_words(text, expected_ward),
        ))

    expected_road_tier = extract_road_tier(title, description)
    actual_road_tier = _to_int(_get(listing, "road_tier"))
    if expected_road_tier and actual_road_tier != expected_road_tier:
        findings.append(_finding(
            "road_tier",
            actual_road_tier,
            expected_road_tier,
            "Text road-access evidence maps to a different road tier.",
            _road_evidence(text),
        ))

    expected_road_width = extract_road_width(text)
    actual_road_width = _to_float(_get(listing, "road_width_m"))
    if expected_road_width is not None and (
        actual_road_width is None
        or not _close_number(actual_road_width, expected_road_width, rel=0.15, abs_tol=1.0)
    ):
        findings.append(_finding(
            "road_width_m",
            actual_road_width,
            expected_road_width,
            "Text contains a clear road width that differs from stored data.",
            _road_evidence(text),
        ))

    expected_road_type = extract_road_type(text)
    actual_road_type = str(_get(listing, "road_type") or "").strip()
    if expected_road_type != "unknown" and not _road_type_compatible(
        actual_road_type,
        expected_road_type,
    ):
        findings.append(_finding(
            "road_type",
            actual_road_type or None,
            expected_road_type,
            "Text contains a clear road-surface/access type that differs from stored data.",
            _road_evidence(text),
        ))

    expected_road_name = extract_road_name(text)
    actual_road_name = str(_get(listing, "road_name") or "").strip()
    if expected_road_name and _fold(expected_road_name) != _fold(actual_road_name):
        findings.append(_finding(
            "road_name",
            actual_road_name or None,
            expected_road_name,
            "Text mentions a named road/code not stored on the listing.",
            _evidence_for_words(text, expected_road_name),
        ))

    expected_tho_cu = extract_tho_cu(text, expected_area or actual_area)
    expected_tho_cu_m2 = _to_float(expected_tho_cu.get("tho_cu_m2"))
    actual_tho_cu_m2 = _to_float(_get(listing, "tho_cu_m2"))
    if expected_tho_cu_m2 is not None:
        if actual_tho_cu_m2 is None or not _close_number(
            actual_tho_cu_m2,
            expected_tho_cu_m2,
            rel=0.08,
            abs_tol=3.0,
        ):
            findings.append(_finding(
                "tho_cu_m2",
                actual_tho_cu_m2,
                expected_tho_cu_m2,
                "Text has explicit residential-land evidence different from stored thổ cư.",
                _evidence_for_number(text, expected_tho_cu_m2, ("tc", "tho", "odt")),
            ))

    expected_property = classify_property_type(
        title,
        description,
        expected_area or actual_area,
        tho_cu_m2=expected_tho_cu_m2 or actual_tho_cu_m2,
        price_per_m2=_to_float(_get(listing, "price_per_m2")),
    )
    actual_property = _get(listing, "property_type")
    if expected_property and expected_property != actual_property:
        findings.append(_finding(
            "property_type",
            actual_property,
            expected_property,
            "Current classifier reads the property type differently from stored value.",
            _property_evidence(text),
        ))

    score = sum(FIELD_WEIGHTS.get(item["field"], 1) for item in findings)
    return {
        "score": score,
        "fields": [item["field"] for item in findings],
        "findings": findings,
    }


def load_manual_extraction_qc(path: str | Path | None = None) -> dict[int, dict[str, Any]]:
    """Load manual LLM QC findings from the local markdown report, if present."""
    report_path = Path(path) if path else DEFAULT_MANUAL_QC_PATH
    if not report_path.exists():
        return {}

    findings_by_id: dict[int, dict[str, Any]] = {}
    for line in report_path.read_text(encoding="utf-8").splitlines():
        parsed = _parse_manual_qc_row(line)
        if not parsed:
            continue
        listing_id, fields, issue, reason = parsed
        audit = findings_by_id.setdefault(
            listing_id,
            {"source": "manual_llm", "score": 0, "fields": [], "findings": []},
        )
        for field in fields:
            if field not in audit["fields"]:
                audit["fields"].append(field)
            audit["score"] += FIELD_WEIGHTS.get(field, 1)
            audit["findings"].append(_finding(
                field,
                None,
                issue,
                reason,
                "Manual LLM review of listing text",
            ))
    return findings_by_id


def merge_extraction_audits(*audits: Mapping[str, Any] | None) -> dict[str, Any]:
    merged: dict[str, Any] = {"score": 0, "fields": [], "findings": []}
    sources: list[str] = []
    for audit in audits:
        if not audit:
            continue
        source = audit.get("source")
        if source and source not in sources:
            sources.append(str(source))
        merged["score"] += int(audit.get("score") or 0)
        for field in audit.get("fields") or []:
            if field not in merged["fields"]:
                merged["fields"].append(field)
        merged["findings"].extend(list(audit.get("findings") or []))
    if sources:
        merged["source"] = ",".join(sources)
    return merged


def _parse_manual_qc_row(line: str) -> tuple[int, list[str], str, str] | None:
    if not re.match(r"^\|\s*\d+\s*\|", line or ""):
        return None
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    if len(cells) < 4:
        return None
    try:
        listing_id = int(cells[0])
    except ValueError:
        return None
    fields = [field.strip() for field in cells[1].split(",") if field.strip()]
    if not fields:
        return None
    return listing_id, fields, cells[2], cells[3]


def _price_candidates(title: str, description: str) -> list[float]:
    values = [
        extract_price(title),
        extract_price(description),
        extract_price(" ".join(part for part in (title, description) if part)),
    ]
    candidates: list[float] = []
    for value in values:
        if value is None:
            continue
        if not any(_close_number(value, existing, rel=0.01, abs_tol=0.01) for existing in candidates):
            candidates.append(value)
    return candidates


def _expected_price(title: str, description: str, candidates: list[float] | None = None) -> float | None:
    if candidates:
        return candidates[-1]
    title_price = extract_price(title)
    desc_price = extract_price(description)
    if title_price is None:
        return desc_price
    if desc_price and desc_price > title_price * 1.15:
        return desc_price
    return title_price


def _ward_compatible(actual: str, expected: str) -> bool:
    actual_folded = _fold(actual)
    expected_folded = _fold(expected)
    if actual_folded == expected_folded:
        return True
    compatible_pairs = {
        ("tan an", "phu an"),
        ("tan dinh", "hoa loi"),
        ("my phuoc 3", "chanh phu hoa"),
        ("my phuoc", "chanh phu hoa"),
    }
    return (actual_folded, expected_folded) in compatible_pairs


def _road_type_compatible(actual: str, expected: str) -> bool:
    aliases = {
        "nhua": "duong_nhua",
        "duong nhua": "duong_nhua",
        "betong": "be_tong",
        "be tong": "be_tong",
    }
    actual_folded = _fold(actual).replace("_", " ")
    expected_folded = _fold(expected).replace("_", " ")
    actual_canonical = aliases.get(actual_folded, actual_folded.replace(" ", "_"))
    expected_canonical = aliases.get(expected_folded, expected_folded.replace(" ", "_"))
    return bool(actual_canonical) and actual_canonical == expected_canonical


def _finding(field: str, actual: Any, expected: Any, reason: str, evidence: str) -> dict[str, Any]:
    return {
        "field": field,
        "actual": _round_value(actual),
        "expected": _round_value(expected),
        "reason": reason,
        "evidence": evidence,
    }


def _get(row: Mapping[str, Any], key: str, default: Any = None) -> Any:
    try:
        return row.get(key, default)  # type: ignore[attr-defined]
    except AttributeError:
        try:
            return row[key]  # type: ignore[index]
        except Exception:
            return default


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _close_number(actual: float, expected: float, *, rel: float, abs_tol: float) -> bool:
    return abs(actual - expected) <= max(abs_tol, abs(expected) * rel)


def _round_value(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 3)
    return value


def _fold(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "")
    value = value.replace("Đ", "D").replace("đ", "d")
    return "".join(
        char for char in unicodedata.normalize("NFD", value)
        if unicodedata.category(char) != "Mn"
    ).casefold().strip()


def _evidence_for_number(text: str, value: float, units: tuple[str, ...]) -> str:
    folded = _fold(text)
    value_tokens = _number_tokens(value)
    unit_pattern = "|".join(re.escape(unit) for unit in units)
    for token in value_tokens:
        pattern = rf".{{0,35}}\b{re.escape(token)}\s*(?:{unit_pattern})?.{{0,35}}"
        match = re.search(pattern, folded, re.IGNORECASE)
        if match:
            return match.group(0).strip()
    return _snippet(text)


def _number_tokens(value: float) -> list[str]:
    tokens = {str(int(value)) if float(value).is_integer() else f"{value:g}"}
    tokens.add(f"{value:.1f}".rstrip("0").rstrip("."))
    tokens.add(f"{value:.2f}".rstrip("0").rstrip("."))
    return sorted(tokens, key=len, reverse=True)


def _evidence_for_words(text: str, value: str) -> str:
    folded = _fold(text)
    target = _fold(value)
    if target:
        match = re.search(rf".{{0,35}}{re.escape(target)}.{{0,35}}", folded, re.IGNORECASE)
        if match:
            return match.group(0).strip()
    return _snippet(text)


def _road_evidence(text: str) -> str:
    folded = _fold(text)
    match = re.search(
        r".{0,35}\b(?:mat tien|mtkd|duong|hem|nhua|be tong|oto|o to|ba gac|xe may|dx|dj|dl|tc)\b.{0,35}",
        folded,
        re.IGNORECASE,
    )
    return match.group(0).strip() if match else _snippet(text)


def _property_evidence(text: str) -> str:
    folded = _fold(text)
    match = re.search(
        r".{0,35}\b(?:dat|nha|tro|phong tro|day tro|can ho|noxh|vuon)\b.{0,35}",
        folded,
        re.IGNORECASE,
    )
    return match.group(0).strip() if match else _snippet(text)


def _snippet(text: str, limit: int = 90) -> str:
    clean = re.sub(r"\s+", " ", text or "").strip()
    return clean[:limit]
