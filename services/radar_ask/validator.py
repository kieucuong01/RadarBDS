"""Deterministic foundation validation for Radar Ask answer envelopes."""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import ValidationError

from .contracts import (
    AnswerEnvelope,
    AskDepth,
    AskVerdict,
    EvidenceBundle,
    EvidenceItem,
    RetrievalQuality,
    SourceCard,
    SourceKind,
)
from .source_links import source_card_details


PHONE_PATTERN = re.compile(r"(?<!\d)(?:\+?84|0)(?:[\s.()-]*\d){8,10}(?!\d)")
URL_PATTERN = re.compile(r"(?i)(?:https?://|www\.|(?:guland|batdongsan)\.\S+)")
NUMERIC_PATTERN = re.compile(r"\d")
TIER_ORDER = {"free": 0, "vip": 1, "admin": 2}
FORBIDDEN_ADVISOR_PHRASES = (
    "mua ngay",
    "xuong tien ngay",
    "chac chan tang gia",
    "cam ket loi nhuan",
    "khong the lo",
    "bao dam sinh loi",
)
DOCUMENT_REFERENCE_PATTERN = re.compile(
    r"(?i)(?<![0-9A-ZĐ])\d{1,4}/\d{4}/[A-ZĐ-]{2,40}(?![0-9A-ZĐ])"
)
MATERIAL_NUMBER_PATTERN = re.compile(
    r"(?<!\d)(\d+(?:[.,]\d+)?)\s*"
    r"(trieu(?:\s+dong)?\s*/\s*m[2²]|trieu(?:\s+dong)?|ty|%|m[2²]|"
    r"tin(?:\s+hieu)?|lo|phuong|khu|nguon|mau|can|deal|lan)(?![a-z])"
)
TIME_SENSITIVE_SOURCE_KINDS = frozenset(
    {
        SourceKind.LISTING,
        SourceKind.VALUATION,
        SourceKind.COMPARABLE,
        SourceKind.PRICE_HISTORY,
        SourceKind.LOT_HISTORY,
        SourceKind.MARKET_STAT,
    }
)
SOURCE_ONLY_ANSWERS = frozenset(
    {
        "vui long xem cac nguon ben duoi de biet chi tiet",
        "vui long xem nguon ben duoi de biet chi tiet",
        "mo cac nguon ben duoi de kiem tra chi tiet",
        "mo nguon ben duoi de kiem tra chi tiet",
        "xem cac nguon ben duoi de biet chi tiet",
        "xem nguon ben duoi de biet chi tiet",
    }
)


class AnswerValidationError(RuntimeError):
    """Raised when an answer is not safe and grounded enough to return."""


@dataclass(frozen=True)
class EvidenceAssessment:
    """Deterministic retrieval grade used before answer synthesis."""

    grade: RetrievalQuality
    missing_requirements: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFD", value.lower()).replace("đ", "d")
    return "".join(char for char in normalized if unicodedata.category(char) != "Mn")


def _is_source_only_answer(value: str) -> bool:
    folded = _fold(value)
    normalized = re.sub(r"[^a-z0-9]+", " ", folded).strip()
    if normalized in SOURCE_ONLY_ANSWERS:
        return True
    return (
        normalized.startswith("radar da tong hop du lieu hien co")
        and "nguon ben duoi" in normalized
        and ("kiem tra chi tiet" in normalized or "biet chi tiet" in normalized)
    )


def _answer_text_values(answer: AnswerEnvelope) -> Iterable[str]:
    yield answer.direct_answer
    for claim in answer.claims:
        yield claim.text
        if claim.unit:
            yield claim.unit
    for metric in answer.key_metrics:
        yield metric.label
        yield str(metric.value)
        if metric.unit:
            yield metric.unit
    for optional in (answer.favorable_thesis, answer.counter_thesis):
        if optional:
            yield optional
    yield from answer.risks
    yield from answer.confidence_reasons
    yield from answer.next_verification_steps
    yield from answer.suggested_followups
    for card in answer.source_cards:
        yield card.title
        yield card.source_ref
        if card.href:
            yield card.href


def _unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


def _is_stale(
    item: EvidenceItem,
    *,
    now: datetime,
    required_freshness_hours: int | None,
) -> bool:
    if required_freshness_hours is None or item.source_kind not in TIME_SENSITIVE_SOURCE_KINDS:
        return False
    reference = now if now.tzinfo is not None and now.utcoffset() is not None else now.replace(tzinfo=timezone.utc)
    as_of = item.as_of
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        as_of = as_of.replace(tzinfo=timezone.utc)
    return (reference.astimezone(timezone.utc) - as_of.astimezone(timezone.utc)).total_seconds() > (
        required_freshness_hours * 3_600
    )


def _is_road_market_item(item: EvidenceItem) -> bool:
    if item.source_kind is not SourceKind.MARKET_STAT:
        return False
    if item.source_ref.startswith("road-market:"):
        return True
    return isinstance(item.value, Mapping) and "market_scope" in item.value


def grade_evidence(
    bundles: Sequence[EvidenceBundle],
    *,
    now: datetime,
    required_freshness_hours: int | None = None,
    tier: str | None = None,
) -> EvidenceAssessment:
    """Grade evidence without delegating policy decisions to the model."""
    if tier is not None:
        _validated_items(bundles, tier=tier)
    items = [item for bundle in bundles for item in bundle.items]
    missing = [requirement for bundle in bundles for requirement in bundle.missing_requirements]
    warnings = [warning for bundle in bundles for warning in bundle.warnings]

    if any(bundle.conflicts for bundle in bundles) or any(
        bundle.retrieval_quality is RetrievalQuality.CONFLICTED for bundle in bundles
    ):
        missing.append("conflicting_evidence_requires_review")
        return EvidenceAssessment(
            grade=RetrievalQuality.CONFLICTED,
            missing_requirements=_unique(missing),
            warnings=_unique(warnings),
        )
    if any(bundle.needs_clarification for bundle in bundles):
        missing.append("entity_clarification_required")
        return EvidenceAssessment(
            grade=RetrievalQuality.INSUFFICIENT,
            missing_requirements=_unique(missing),
            warnings=_unique(warnings),
        )
    if not items or any(
        bundle.retrieval_quality is RetrievalQuality.INSUFFICIENT for bundle in bundles
    ):
        if not missing:
            missing.append("reliable_evidence_not_found")
        return EvidenceAssessment(
            grade=RetrievalQuality.INSUFFICIENT,
            missing_requirements=_unique(missing),
            warnings=_unique(warnings),
        )

    repair = any(bundle.retrieval_quality is RetrievalQuality.REPAIR for bundle in bundles)
    if missing:
        repair = True
    if any(
        _is_stale(
            item,
            now=now,
            required_freshness_hours=required_freshness_hours,
        )
        for item in items
    ):
        repair = True
        missing.append("fresh_evidence_required")
    if any(
        _is_road_market_item(item)
        and (item.sample_size is None or item.sample_size < 3)
        for item in items
    ):
        repair = True
        missing.append("minimum_three_road_listings_required")

    return EvidenceAssessment(
        grade=RetrievalQuality.REPAIR if repair else RetrievalQuality.SUFFICIENT,
        missing_requirements=_unique(missing),
        warnings=_unique(warnings),
    )


def _decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _canonical_unit(unit: str | None) -> tuple[str | None, Decimal]:
    if not unit:
        return None, Decimal("1")
    folded = _fold(unit).replace("²", "2").replace(" ", "")
    aliases = {
        "tin": ("count", Decimal("1")),
        "listing": ("count", Decimal("1")),
        "count": ("count", Decimal("1")),
        "%": ("percent", Decimal("1")),
        "pct": ("percent", Decimal("1")),
        "percent": ("percent", Decimal("1")),
        "m2": ("square_metre", Decimal("1")),
        "million_vnd_per_m2": ("million_vnd_per_m2", Decimal("1")),
        "trieu/m2": ("million_vnd_per_m2", Decimal("1")),
        "trieuvnd/m2": ("million_vnd_per_m2", Decimal("1")),
        "vnd/m2": ("million_vnd_per_m2", Decimal("0.000001")),
        "thousand_vnd_per_m2": ("million_vnd_per_m2", Decimal("0.001")),
        "nghinvnd/m2": ("million_vnd_per_m2", Decimal("0.001")),
        "ty": ("billion_vnd", Decimal("1")),
        "billion_vnd": ("billion_vnd", Decimal("1")),
        "million_vnd": ("billion_vnd", Decimal("0.001")),
    }
    return aliases.get(folded, (folded, Decimal("1")))


def _unit_from_key(key: str, fallback: str | None) -> str | None:
    folded = _fold(key)
    if "thousand_vnd_per_m2" in folded:
        return "thousand_vnd_per_m2"
    if "ppm2" in folded or "per_m2_million" in folded:
        return "million_vnd_per_m2"
    if folded.endswith("_ty") or "total_ty" in folded:
        return "billion_vnd"
    if folded.endswith("_pct") or "percent" in folded:
        return "percent"
    if folded.endswith("_m2") or "area_m2" in folded:
        return "m2"
    if "count" in folded or "sample_size" in folded:
        return "count"
    return fallback if not key else None


def _semantic_from_key(key: str) -> str | None:
    folded = _fold(key)
    if "official" in folded:
        return "official"
    if "asking" in folded or "listing_price" in folded:
        return "asking"
    if "fair" in folded:
        return "fair"
    if "transaction" in folded or "closed_sale" in folded:
        return "transaction"
    return None


def _item_default_semantics(item: EvidenceItem) -> set[str]:
    if item.source_kind is SourceKind.OFFICIAL_PRICE:
        return {"official"}
    if item.source_kind is SourceKind.OFFICIAL_DOCUMENT:
        return {"official_document"}
    if item.source_kind in {SourceKind.LISTING, SourceKind.COMPARABLE, SourceKind.PRICE_HISTORY}:
        return {"asking"}
    if item.source_kind is SourceKind.VALUATION:
        return {"fair", "asking"}
    if item.source_kind is SourceKind.MARKET_STAT:
        return {"asking"}
    return set()


def _value_numeric_candidates(
    value: Any,
    *,
    fallback_unit: str | None,
) -> list[tuple[Decimal, str | None, str | None]]:
    candidates: list[tuple[Decimal, str | None, str | None]] = []

    def walk(nested_value: Any, *, key: str = "") -> None:
        if isinstance(nested_value, Mapping):
            for nested_key, nested in nested_value.items():
                walk(nested, key=str(nested_key))
            return
        if isinstance(nested_value, (list, tuple)):
            for nested in nested_value:
                walk(nested, key=key)
            return
        number = _decimal(nested_value)
        if number is None:
            return
        unit_name, scale = _canonical_unit(_unit_from_key(key, fallback_unit))
        candidates.append((number * scale, unit_name, _semantic_from_key(key)))

    walk(value)
    return candidates


def _numeric_candidates(item: EvidenceItem) -> list[tuple[Decimal, str | None, str | None]]:
    candidates = _value_numeric_candidates(item.value, fallback_unit=item.unit)
    defaults = _item_default_semantics(item)
    if len(defaults) != 1:
        return candidates
    default = next(iter(defaults))
    return [
        (value, unit, semantic or default)
        for value, unit, semantic in candidates
    ]


def _calculation_candidates(
    bundles: Sequence[EvidenceBundle],
) -> dict[str, list[tuple[Decimal, str | None, str | None]]]:
    result: dict[str, list[tuple[Decimal, str | None, str | None]]] = {}
    for bundle in bundles:
        candidates = _value_numeric_candidates(bundle.calculations, fallback_unit=None)
        for item in bundle.items:
            result.setdefault(item.evidence_id, []).extend(candidates)
    return result


def _numeric_matches(expected: Decimal, actual: Decimal, unit: str | None) -> bool:
    if unit == "count":
        return expected == actual
    tolerance = max(Decimal("0.01"), abs(expected) * Decimal("0.005"))
    return abs(expected - actual) <= tolerance


def _expected_price_semantic(text: str) -> str | None:
    folded = _fold(text)
    official_markers = ("bang gia dat", "gia nha nuoc", "gia chinh thuc")
    non_equivalence = ("khong phai", "khong duoc xem la", "khac voi")
    if any(marker in folded for marker in official_markers) and any(
        marker in folded for marker in non_equivalence
    ):
        return "official"
    if any(marker in folded for marker in ("gia giao dich", "gia da ban", "giao dich thuc te")):
        return "transaction"
    if any(marker in folded for marker in ("gia thi truong", "thi truong hien tai")):
        return "market"
    if any(marker in folded for marker in ("gia rao", "gia chao ban", "gia dang tin")):
        return "asking"
    if any(marker in folded for marker in ("fair value", "gia hop ly", "gia radar")):
        return "fair"
    if any(marker in folded for marker in official_markers):
        return "official"
    return None


def _allowed_price_semantics(expected: str) -> set[str]:
    return {
        "official": {"official", "official_document"},
        "asking": {"asking"},
        "fair": {"fair"},
        "transaction": {"transaction"},
        "market": {"transaction"},
    }[expected]


def _validate_price_semantics(
    claim_text: str,
    cited: Sequence[EvidenceItem],
) -> str | None:
    expected = _expected_price_semantic(claim_text)
    if expected is None:
        return None
    available: set[str] = set()
    for item in cited:
        available.update(_item_default_semantics(item))
        available.update(
            semantic
            for _number, _unit, semantic in _numeric_candidates(item)
            if semantic is not None
        )
    allowed = _allowed_price_semantics(expected)
    if not available.intersection(allowed):
        raise AnswerValidationError("claim confuses official, fair, asking, or transaction price semantics")
    return expected


def _validate_document_reference(claim_text: str, cited: Sequence[EvidenceItem]) -> None:
    references = {match.group(0).upper() for match in DOCUMENT_REFERENCE_PATTERN.finditer(claim_text)}
    if not references:
        return
    official = [
        item for item in cited if item.source_kind in {SourceKind.OFFICIAL_DOCUMENT, SourceKind.OFFICIAL_PRICE}
    ]
    searchable = "\n".join(
        str(item.model_dump(mode="json")) for item in official
    ).upper()
    if not official or not references.issubset(set(DOCUMENT_REFERENCE_PATTERN.findall(searchable))):
        raise AnswerValidationError("claim cites an official document not present in the exact evidence chunk")


def _material_numbers(text: str) -> list[tuple[Decimal, str | None]]:
    folded = _fold(text)
    values: list[tuple[Decimal, str | None]] = []
    for raw_number, raw_unit in MATERIAL_NUMBER_PATTERN.findall(folded):
        number = _decimal(raw_number.replace(",", "."))
        if number is None:
            continue
        unit = raw_unit.replace(" ", "")
        if unit.startswith("trieu"):
            normalized_unit = (
                "million_vnd_per_m2" if "/m" in unit else "million_vnd"
            )
        elif unit == "ty":
            normalized_unit = "billion_vnd"
        elif unit == "%":
            normalized_unit = "percent"
        elif unit.startswith("m"):
            normalized_unit = "m2"
        else:
            normalized_unit = "count"
        values.append((number, normalized_unit))
    return values


def _validate_numeric_support(
    expected_values: Iterable[tuple[Decimal, str | None]],
    candidates: Sequence[tuple[Decimal, str | None, str | None]],
    *,
    expected_semantic: str | None = None,
) -> None:
    usable = list(candidates)
    if expected_semantic is not None:
        allowed = _allowed_price_semantics(expected_semantic)
        usable = [
            candidate for candidate in candidates if candidate[2] in allowed
        ]
    for raw_expected, raw_unit in expected_values:
        expected_unit, expected_scale = _canonical_unit(raw_unit)
        expected = raw_expected * expected_scale
        if expected_unit is not None and not any(
            unit == expected_unit for _value, unit, _semantic in usable
        ):
            raise AnswerValidationError("numeric claim unit is not supported by cited evidence")
        if not any(
            (expected_unit is None or unit == expected_unit)
            and _numeric_matches(expected, value, expected_unit)
            for value, unit, _semantic in usable
        ):
            raise AnswerValidationError("numeric claim does not match cited evidence")


def _validate_claim_grounding(
    claim,
    by_id: Mapping[str, EvidenceItem],
    calculation_by_id: Mapping[str, Sequence[tuple[Decimal, str | None, str | None]]],
) -> None:
    cited = [by_id[evidence_id] for evidence_id in claim.evidence_ids]
    expected_semantic = _validate_price_semantics(claim.text, cited)
    _validate_document_reference(claim.text, cited)
    expected_values = _material_numbers(claim.text)
    if claim.numeric_value is not None:
        expected_values.append((claim.numeric_value, claim.unit))
    if not expected_values:
        return
    candidates = [candidate for item in cited for candidate in _numeric_candidates(item)]
    for evidence_id in claim.evidence_ids:
        candidates.extend(calculation_by_id.get(evidence_id, ()))
    _validate_numeric_support(
        expected_values,
        candidates,
        expected_semantic=expected_semantic,
    )


def _validated_items(
    bundles: Sequence[EvidenceBundle],
    *,
    tier: str,
) -> dict[str, EvidenceItem]:
    if tier not in TIER_ORDER:
        raise AnswerValidationError("authenticated tier is invalid")
    by_id: dict[str, EvidenceItem] = {}
    for bundle in bundles:
        for item in bundle.items:
            if item.evidence_id in by_id:
                raise AnswerValidationError("evidence IDs must be unique")
            if TIER_ORDER[item.min_tier] > TIER_ORDER[tier]:
                raise AnswerValidationError("answer evidence exceeds the current tier")
            by_id[item.evidence_id] = item
    return by_id


def _validate_reference_ids(answer: AnswerEnvelope, by_id: Mapping[str, EvidenceItem]) -> set[str]:
    referenced: set[str] = set()
    for claim in answer.claims:
        if claim.material and not claim.evidence_ids:
            raise AnswerValidationError("material claims require evidence")
        if (claim.numeric_value is not None or NUMERIC_PATTERN.search(claim.text)) and not claim.evidence_ids:
            raise AnswerValidationError("numeric claims require evidence")
        referenced.update(claim.evidence_ids)
    for metric in answer.key_metrics:
        if not metric.evidence_ids:
            raise AnswerValidationError("key metrics require evidence")
        referenced.update(metric.evidence_ids)
    referenced.update(card.evidence_id for card in answer.source_cards)

    unknown = referenced - set(by_id)
    if unknown:
        raise AnswerValidationError("answer references unknown evidence")
    if NUMERIC_PATTERN.search(answer.direct_answer) and not any(
        claim.evidence_ids for claim in answer.claims
    ):
        raise AnswerValidationError("numeric direct answers require cited claims")
    return referenced


def _source_cards(
    by_id: Mapping[str, EvidenceItem],
    referenced: set[str],
) -> list[SourceCard]:
    selected = referenced or set(by_id)
    cards: list[SourceCard] = []
    for evidence_id, item in by_id.items():
        if evidence_id not in selected:
            continue
        title, href = source_card_details(
            source_kind=item.source_kind,
            source_ref=item.source_ref,
            value=item.value,
            provenance=item.provenance,
        )
        cards.append(
            SourceCard(
                evidence_id=evidence_id,
                title=title,
                source_kind=item.source_kind,
                source_ref=item.source_ref,
                as_of=item.as_of,
                href=href,
            )
        )
        if len(cards) == 20:
            break
    return cards


def validate_answer(
    answer: AnswerEnvelope | Mapping[str, Any],
    evidence: Sequence[EvidenceBundle],
    *,
    tier: str,
    expected_depth: AskDepth,
    now: datetime | None = None,
    required_freshness_hours: int | None = None,
) -> AnswerEnvelope:
    """Validate grounding, language, tier safety, and canonical citations."""
    try:
        parsed = answer if isinstance(answer, AnswerEnvelope) else AnswerEnvelope.model_validate(answer)
    except (ValidationError, TypeError, ValueError) as exc:
        raise AnswerValidationError("answer envelope is invalid") from exc

    if parsed.depth is not expected_depth:
        raise AnswerValidationError("answer depth does not match the approved route")
    if parsed.answered and parsed.verdict is None:
        raise AnswerValidationError("answered responses require an approved verdict")
    if not parsed.answered and parsed.verdict is not AskVerdict.INSUFFICIENT:
        raise AnswerValidationError("unanswered responses must be grounded insufficient conclusions")
    if parsed.answered and _is_source_only_answer(parsed.direct_answer):
        raise AnswerValidationError("answer does not directly answer the question")

    folded = _fold("\n".join(_answer_text_values(parsed)))
    if any(phrase in folded for phrase in FORBIDDEN_ADVISOR_PHRASES):
        raise AnswerValidationError("answer uses prohibited investment instructions")
    if tier in {"free", "vip"}:
        raw_text = "\n".join(_answer_text_values(parsed))
        if PHONE_PATTERN.search(raw_text) or URL_PATTERN.search(raw_text):
            raise AnswerValidationError("answer contains redacted source data")

    by_id = _validated_items(evidence, tier=tier)
    referenced = _validate_reference_ids(parsed, by_id)
    if parsed.answered and not by_id:
        raise AnswerValidationError("answered responses require evidence")
    calculation_by_id = _calculation_candidates(evidence)
    for claim in parsed.claims:
        _validate_claim_grounding(claim, by_id, calculation_by_id)
    for metric in parsed.key_metrics:
        number = _decimal(metric.value)
        if number is None:
            continue
        candidates = [
            candidate
            for evidence_id in metric.evidence_ids
            for candidate in _numeric_candidates(by_id[evidence_id])
        ]
        for evidence_id in metric.evidence_ids:
            candidates.extend(calculation_by_id.get(evidence_id, ()))
        _validate_numeric_support([(number, metric.unit)], candidates)
    grounding_ids = set(
        evidence_id
        for claim in parsed.claims
        for evidence_id in claim.evidence_ids
    )
    grounding_ids.update(
        evidence_id
        for metric in parsed.key_metrics
        for evidence_id in metric.evidence_ids
    )
    grounding_items = [by_id[evidence_id] for evidence_id in grounding_ids]
    direct_semantic = _validate_price_semantics(parsed.direct_answer, grounding_items)
    _validate_document_reference(parsed.direct_answer, grounding_items)
    direct_numbers = _material_numbers(parsed.direct_answer)
    if direct_numbers:
        candidates = [
            candidate
            for evidence_id in grounding_ids
            for candidate in _numeric_candidates(by_id[evidence_id])
        ]
        for evidence_id in grounding_ids:
            candidates.extend(calculation_by_id.get(evidence_id, ()))
        _validate_numeric_support(
            direct_numbers,
            candidates,
            expected_semantic=direct_semantic,
        )

    freshness_reference = now or parsed.as_of
    stale_referenced = [
        evidence_id
        for evidence_id in referenced
        if _is_stale(
            by_id[evidence_id],
            now=freshness_reference,
            required_freshness_hours=required_freshness_hours,
        )
    ]
    if stale_referenced:
        raise AnswerValidationError("material claim cites stale evidence")

    return parsed.model_copy(update={"source_cards": _source_cards(by_id, referenced)})
