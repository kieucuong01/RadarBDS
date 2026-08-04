"""Deterministic foundation validation for Radar Ask answer envelopes."""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from pydantic import ValidationError

from .contracts import (
    AnswerEnvelope,
    AskDepth,
    AskVerdict,
    EvidenceBundle,
    EvidenceItem,
    SourceCard,
)


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


class AnswerValidationError(RuntimeError):
    """Raised when an answer is not safe and grounded enough to return."""


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFD", value.lower()).replace("đ", "d")
    return "".join(char for char in normalized if unicodedata.category(char) != "Mn")


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
        cards.append(
            SourceCard(
                evidence_id=evidence_id,
                title=f"{item.source_kind.value}: {item.source_ref}",
                source_kind=item.source_kind,
                source_ref=item.source_ref,
                as_of=item.as_of,
                href=None,
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

    return parsed.model_copy(update={"source_cards": _source_cards(by_id, referenced)})
