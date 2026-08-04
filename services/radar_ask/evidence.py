"""Evidence construction, deduplication, tier filtering, and provider sanitization."""
from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

from .contracts import (
    EvidenceBundle,
    EvidenceConflict,
    EvidenceItem,
    RetrievalQuality,
)


TIER_ORDER = {"free": 0, "vip": 1, "admin": 2}
PHONE_PATTERN = re.compile(r"(?<!\d)(?:\+?84|0)(?:[\s.()-]*\d){8,10}(?!\d)")
URL_PATTERN = re.compile(r"(?i)\b(?:https?://|www\.)[^\s\"'<>]+")
SAFE_PROVIDER_SOURCE_REF_PATTERN = re.compile(
    r"^knowledge:[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
PRIVATE_KEYS = frozenset(
    {
        "phone",
        "contact_phone",
        "seller_phone",
        "seller_name",
        "url",
        "source_url",
        "original_url",
        "database_url",
        "raw_sql",
        "sql",
        "raw_json",
        "password",
        "secret",
        "token",
        "session_id",
        "user_id",
        "listing_id",
        "db_id",
    }
)


def stable_evidence_id(kind: str, source_ref: str, dataset_version: str) -> str:
    canonical = f"{kind.strip().lower()}|{source_ref.strip()}|{dataset_version.strip()}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:20]


def _private_key(value: object) -> bool:
    normalized = str(value).strip().lower()
    return normalized in PRIVATE_KEYS or normalized.startswith("internal_")


def _sanitize_text(value: str) -> str:
    redacted = URL_PATTERN.sub("[REDACTED]", value)
    return PHONE_PATTERN.sub("[REDACTED]", redacted)


def redact_evidence_text(value: str) -> str:
    """Remove embedded phone and URL tokens from user-visible evidence text."""
    return _sanitize_text(value)


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, str):
        return _sanitize_text(value)
    if isinstance(value, Mapping):
        return {
            str(key): _sanitize_value(item)
            for key, item in value.items()
            if not _private_key(key)
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize_value(item) for item in value]
    return value


def _provider_source_ref(source_ref: str) -> str:
    if SAFE_PROVIDER_SOURCE_REF_PATTERN.fullmatch(source_ref.strip()):
        return source_ref.strip().lower()
    parsed = urlparse(source_ref)
    if parsed.scheme or parsed.netloc or URL_PATTERN.search(source_ref):
        return "external-source:redacted"
    return _sanitize_text(source_ref)


class EvidenceBuilder:
    def __init__(self, *, question_snapshot: str, row_limit: int = 50):
        if not 1 <= int(row_limit) <= 50:
            raise ValueError("evidence row limit must be between 1 and 50")
        self.question_snapshot = " ".join(question_snapshot.split())
        if not self.question_snapshot or len(self.question_snapshot) > 2_000:
            raise ValueError("question snapshot is invalid")
        self.row_limit = int(row_limit)
        self._items: dict[str, EvidenceItem] = {}
        self._conflicts: list[EvidenceConflict] = []
        self._warnings: list[str] = []
        self._resolved_entities: dict[str, Any] = {}
        self._calculations: dict[str, Any] = {}
        self._missing: list[str] = []
        self._needs_clarification = False
        self._clarification_candidates: list[str] = []

    def add(self, item: EvidenceItem) -> "EvidenceBuilder":
        existing = self._items.get(item.evidence_id)
        if existing is not None:
            if existing != item and not any(
                conflict.evidence_ids == [item.evidence_id, item.evidence_id]
                for conflict in self._conflicts
            ):
                self._conflicts.append(
                    EvidenceConflict(
                        evidence_ids=[item.evidence_id, item.evidence_id],
                        reason="same stable evidence ID has conflicting payloads",
                    )
                )
            return self
        if len(self._items) >= self.row_limit:
            if "evidence_row_limit_reached" not in self._warnings:
                self._warnings.append("evidence_row_limit_reached")
            return self
        self._items[item.evidence_id] = item
        return self

    def resolve(self, **entities: Any) -> "EvidenceBuilder":
        self._resolved_entities.update(entities)
        return self

    def calculate(self, **values: Any) -> "EvidenceBuilder":
        self._calculations.update(values)
        return self

    def warn(self, warning: str) -> "EvidenceBuilder":
        normalized = " ".join(warning.split())
        if normalized and normalized not in self._warnings and len(self._warnings) < 20:
            self._warnings.append(normalized[:512])
        return self

    def missing(self, requirement: str) -> "EvidenceBuilder":
        normalized = " ".join(requirement.split())
        if normalized and normalized not in self._missing and len(self._missing) < 20:
            self._missing.append(normalized[:512])
        return self

    def clarify(self, candidates: list[str]) -> "EvidenceBuilder":
        self._needs_clarification = True
        self._clarification_candidates = list(dict.fromkeys(candidates))[:10]
        return self

    def build(self) -> EvidenceBundle:
        if self._conflicts:
            quality = RetrievalQuality.CONFLICTED
        elif self._missing and not self._items:
            quality = RetrievalQuality.INSUFFICIENT
        else:
            quality = RetrievalQuality.SUFFICIENT
        return EvidenceBundle(
            question_snapshot=self.question_snapshot,
            resolved_entities=self._resolved_entities,
            items=list(self._items.values()),
            calculations=self._calculations,
            conflicts=self._conflicts,
            warnings=self._warnings,
            missing_requirements=self._missing,
            retrieval_quality=quality,
            needs_clarification=self._needs_clarification,
            clarification_candidates=self._clarification_candidates,
        )


def build_provider_bundle(bundle: EvidenceBundle, *, tier: str) -> EvidenceBundle:
    """Return a second, provider-safe copy; never mutate server-side evidence."""
    if tier not in TIER_ORDER:
        raise ValueError("provider evidence tier is invalid")
    retained = [
        item
        for item in bundle.items
        if TIER_ORDER[item.min_tier] <= TIER_ORDER[tier]
    ]
    retained_ids = {item.evidence_id for item in retained}
    safe_items = [
        item.model_copy(
            update={
                "source_ref": _provider_source_ref(item.source_ref),
                "value": _sanitize_value(item.value),
                "provenance": _sanitize_value(item.provenance),
                "parent_evidence_ids": [
                    evidence_id
                    for evidence_id in item.parent_evidence_ids
                    if evidence_id in retained_ids
                ],
            }
        )
        for item in retained
    ]
    safe_conflicts = [
        conflict
        for conflict in bundle.conflicts
        if set(conflict.evidence_ids) <= retained_ids
    ]
    quality = bundle.retrieval_quality
    if bundle.items and not safe_items:
        quality = RetrievalQuality.INSUFFICIENT
    return bundle.model_copy(
        update={
            "question_snapshot": _sanitize_text(bundle.question_snapshot),
            "resolved_entities": _sanitize_value(bundle.resolved_entities),
            "items": safe_items,
            "calculations": _sanitize_value(bundle.calculations),
            "conflicts": safe_conflicts,
            "retrieval_quality": quality,
        }
    )
