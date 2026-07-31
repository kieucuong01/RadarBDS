"""Deterministic Guland publisher identity and activity classification."""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
from dataclasses import dataclass
from typing import Mapping
from urllib.parse import urlsplit, urlunsplit

from config.settings import GULAND_PUBLISHER_KEY_SECRET


logger = logging.getLogger(__name__)

_PHONE_DIGITS_RE = re.compile(r"\D+")
_DESCRIPTION_PHONE_RE = re.compile(
    r"(?<!\d)(?:\+?84|0)[\s.\-]*(?:3|5|7|8|9)"
    r"(?:[\s.\-]*\d){8}(?!\d)"
)
_MEMBER_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,160}$")
_KNOWN_GULAND_HOTLINES = frozenset({"0983284379"})
_IDENTIFIED_CONFIDENCE = frozenset({"high", "medium"})
_ACTIVITY_CLASSES = frozenset(
    {"low_manual", "high_activity", "automated_repost", "unknown"}
)


@dataclass(frozen=True)
class PublisherEvidence:
    status: str
    identity_type: str
    confidence: str
    source_id: str = ""
    profile_url: str = ""
    name: str = ""
    phone: str = ""
    reason: str = ""


@dataclass(frozen=True)
class PublisherMetrics:
    new_1d: int = 0
    new_7d: int = 0
    new_30d: int = 0
    max_new_on_day: int = 0
    active_days_30d: int = 0
    bumps_7d: int = 0
    bumps_30d: int = 0
    near_duplicates_max_day: int = 0
    days_ge_15_with_templates_14d: int = 0


@dataclass(frozen=True)
class PublisherClassification:
    activity_class: str
    reason: str


def normalize_vietnam_phone(value: str) -> str:
    """Return a canonical 10-digit Vietnamese mobile number or an empty value."""
    digits = _PHONE_DIGITS_RE.sub("", str(value or ""))
    if digits.startswith("84") and len(digits) == 11:
        digits = f"0{digits[2:]}"
    if len(digits) != 10 or not re.fullmatch(r"0[35789]\d{8}", digits):
        return ""
    return digits


def _canonical_profile_url(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError:
        return ""
    if (
        parsed.scheme.lower() != "https"
        or parsed.username
        or parsed.password
        or (parsed.hostname or "").lower() not in {"guland.vn", "www.guland.vn"}
        or port not in {None, 443}
        or not parsed.path.startswith("/")
    ):
        return ""
    path = re.sub(r"/+", "/", parsed.path).rstrip("/") or "/"
    return urlunsplit(("https", "guland.vn", path, "", ""))


def _member_id(value: object) -> str:
    candidate = str(value or "").strip()
    return candidate if _MEMBER_ID_RE.fullmatch(candidate) else ""


def _description_phone(description: str) -> str:
    for match in _DESCRIPTION_PHONE_RE.finditer(str(description or "")):
        phone = normalize_vietnam_phone(match.group(0))
        if phone and phone not in _KNOWN_GULAND_HOTLINES:
            return phone
    return ""


def validate_publisher_evidence(
    detail: Mapping[str, object],
    description: str,
) -> PublisherEvidence:
    """Select the strongest listing-scoped publisher identity evidence."""
    source_id = _member_id(detail.get("publisher_source_id"))
    profile_url = _canonical_profile_url(detail.get("publisher_profile_url"))
    name = str(detail.get("publisher_name") or "").strip()[:240]
    scoped_phone = ""
    if str(detail.get("publisher_phone_scope") or "").strip() == "listing_contact":
        scoped_phone = normalize_vietnam_phone(
            str(detail.get("publisher_phone_candidate") or "")
        )
        if scoped_phone in _KNOWN_GULAND_HOTLINES:
            scoped_phone = ""

    if source_id:
        return PublisherEvidence(
            status="identified",
            identity_type="member_id",
            confidence="high",
            source_id=source_id,
            profile_url=profile_url,
            name=name,
            phone=scoped_phone,
            reason="member_id",
        )
    if profile_url:
        return PublisherEvidence(
            status="identified",
            identity_type="profile_url",
            confidence="high",
            profile_url=profile_url,
            name=name,
            phone=scoped_phone,
            reason="canonical_profile_url",
        )
    if scoped_phone:
        return PublisherEvidence(
            status="identified",
            identity_type="listing_phone",
            confidence="medium",
            name=name,
            phone=scoped_phone,
            reason="listing_scoped_phone",
        )

    description_phone = _description_phone(description)
    if description_phone:
        return PublisherEvidence(
            status="identified",
            identity_type="description_phone",
            confidence="medium",
            name=name,
            phone=description_phone,
            reason="description_phone",
        )
    return PublisherEvidence(
        status="unknown",
        identity_type="unknown",
        confidence="low",
        name=name,
        reason="no_reliable_identity",
    )


def _namespaced_identity(evidence: PublisherEvidence) -> str:
    if evidence.identity_type == "member_id":
        value = evidence.source_id
    elif evidence.identity_type == "profile_url":
        value = evidence.profile_url
    elif evidence.identity_type in {"listing_phone", "description_phone"}:
        value = normalize_vietnam_phone(evidence.phone)
    else:
        return ""
    return f"guland:{evidence.identity_type}:{value}"


def build_publisher_key(evidence: PublisherEvidence, secret: str) -> str:
    """Create a stable non-reversible publisher key from reliable evidence."""
    identity = _namespaced_identity(evidence)
    if not identity:
        return ""
    if len(str(secret or "")) < 32:
        raise ValueError(
            "GULAND_PUBLISHER_KEY_SECRET must contain at least 32 characters"
        )
    return hmac.new(
        str(secret).encode("utf-8"),
        identity.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def validated_raw_publisher_fields(
    detail: Mapping[str, object],
    *,
    secret: str | None = None,
) -> dict[str, object]:
    """Return validated raw payload fields without making crawl configuration fatal."""
    evidence = validate_publisher_evidence(
        detail,
        str(detail.get("description") or ""),
    )
    try:
        publisher_key = build_publisher_key(
            evidence,
            GULAND_PUBLISHER_KEY_SECRET if secret is None else secret,
        )
    except ValueError:
        logger.warning(
            "Guland publisher identity ignored because key secret is missing or short"
        )
        evidence = PublisherEvidence(
            status="unknown",
            identity_type="unknown",
            confidence="low",
            name=evidence.name,
            reason="identity_secret_missing",
        )
        publisher_key = ""

    return {
        "publisher_identity_status": evidence.status,
        "publisher_identity_type": evidence.identity_type,
        "publisher_identity_confidence": evidence.confidence,
        "publisher_identity_reason": evidence.reason,
        "publisher_key": publisher_key,
        "publisher_source_id": evidence.source_id,
        "publisher_profile_url": evidence.profile_url,
        "publisher_name": evidence.name,
        "publisher_phone": evidence.phone,
    }


def classify_publisher(
    metrics: PublisherMetrics,
    confidence: str,
) -> PublisherClassification:
    """Classify publisher behavior without affecting listing quality or valuation."""
    if str(confidence or "").lower() not in _IDENTIFIED_CONFIDENCE:
        return PublisherClassification("unknown", "insufficient_identity")
    if metrics.max_new_on_day >= 30:
        return PublisherClassification("automated_repost", "new_30_or_more_in_day")
    if metrics.bumps_7d >= 3:
        return PublisherClassification("automated_repost", "three_bumps_in_7d")
    if metrics.near_duplicates_max_day >= 10:
        return PublisherClassification(
            "automated_repost",
            "ten_near_duplicates_in_day",
        )
    if metrics.days_ge_15_with_templates_14d >= 3:
        return PublisherClassification(
            "automated_repost",
            "repeated_high_volume_template_days",
        )
    if metrics.max_new_on_day > 5:
        return PublisherClassification("high_activity", "more_than_five_in_day")
    if metrics.new_30d > 30:
        return PublisherClassification("high_activity", "more_than_thirty_in_30d")
    return PublisherClassification("low_manual", "within_manual_activity_limits")


def effective_publisher_class(
    activity_class: str,
    manual_override: str | None,
) -> str:
    """Apply the two supported admin overrides to a stored activity class."""
    normalized = (
        activity_class if activity_class in _ACTIVITY_CLASSES else "unknown"
    )
    if manual_override == "allow_manual":
        return "low_manual"
    if manual_override == "hide_high_activity":
        return "high_activity"
    return normalized
