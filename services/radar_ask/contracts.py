from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Annotated, Literal
from uuid import UUID
from urllib.parse import urlparse

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    field_validator,
    model_validator,
)


Tier = Literal["free", "vip", "admin"]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=512)]
EvidenceId = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.:-]+$"),
]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class AskDepth(str, Enum):
    FAST = "fast"
    STANDARD = "standard"
    DEEP = "deep"


class AskVerdict(str, Enum):
    WORTH_REVIEWING = "dang_xem"
    NEEDS_CHECKS = "can_kiem_tra_them"
    HIGH_RISK = "rui_ro_cao"
    INSUFFICIENT = "khong_du_du_lieu"


class RunStatus(str, Enum):
    CREATED = "created"
    CLARIFYING = "clarifying"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    INSUFFICIENT = "insufficient"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RunOutcome(str, Enum):
    ANSWERED = "answered"
    INSUFFICIENT = "insufficient"
    CLARIFICATION = "clarification"
    PROVIDER_FAILURE = "provider_failure"
    VALIDATION_FAILURE = "validation_failure"
    DATABASE_FAILURE = "database_failure"
    BUDGET_HARD_STOP = "budget_hard_stop"
    CANCELLED = "cancelled"


class SourceKind(str, Enum):
    LISTING = "listing"
    VALUATION = "valuation"
    COMPARABLE = "comparable"
    PRICE_HISTORY = "price_history"
    LOT_HISTORY = "lot_history"
    MARKET_STAT = "market_stat"
    OFFICIAL_PRICE = "official_price"
    OFFICIAL_DOCUMENT = "official_document"
    RADAR_METHOD = "radar_method"


class RetrievalQuality(str, Enum):
    SUFFICIENT = "sufficient"
    REPAIR = "repair"
    INSUFFICIENT = "insufficient"
    CONFLICTED = "conflicted"


class AskQuestionRequest(ContractModel):
    question: str = Field(min_length=1, max_length=2_000)
    session_id: UUID | None = None
    requested_depth: AskDepth | None = None

    @field_validator("question")
    @classmethod
    def normalize_question(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("question must not be blank")
        return normalized


class PageContext(ContractModel):
    listing_id: int | None = Field(default=None, gt=0)
    city: str | None = Field(default=None, max_length=120)
    ward: str | None = Field(default=None, max_length=120)
    road: str | None = Field(default=None, max_length=180)
    active_filters: dict[str, JsonValue] = Field(default_factory=dict, max_length=20)

    @model_validator(mode="after")
    def bound_serialized_filters(self) -> "PageContext":
        encoded = json.dumps(self.active_filters, ensure_ascii=False, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > 8_192:
            raise ValueError("active filters exceed 8192 bytes")
        return self


class AskContext(ContractModel):
    user_id: int = Field(gt=0)
    tier: Tier
    page: PageContext = Field(default_factory=PageContext)
    session_summary: str | None = Field(default=None, max_length=2_000)
    recent_turns: list[str] = Field(default_factory=list, max_length=6)


class ToolCall(ContractModel):
    call_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.:-]+$")
    name: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_]*$")
    arguments: dict[str, JsonValue] = Field(default_factory=dict, max_length=32)

    @model_validator(mode="after")
    def bound_serialized_arguments(self) -> "ToolCall":
        encoded = json.dumps(self.arguments, ensure_ascii=False, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > 8_192:
            raise ValueError("tool arguments exceed 8192 bytes")
        return self


class RouteDecision(ContractModel):
    depth: AskDepth
    question_type: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_]*$")
    tool_calls: list[ToolCall] = Field(default_factory=list, max_length=8)
    generated: bool
    use_thinking: bool = False
    needs_clarification: bool = False
    clarification_question: str | None = Field(default=None, max_length=500)
    required_freshness_hours: int | None = Field(default=None, ge=1, le=24 * 365)

    @model_validator(mode="after")
    def validate_clarification_shape(self) -> "RouteDecision":
        if self.needs_clarification and not self.clarification_question:
            raise ValueError("clarification_question is required")
        if self.needs_clarification and self.tool_calls:
            raise ValueError("clarification cannot include tool calls")
        return self


class EvidenceItem(ContractModel):
    evidence_id: EvidenceId
    source_kind: SourceKind
    source_ref: str = Field(min_length=1, max_length=512)
    value: JsonValue
    unit: str | None = Field(default=None, max_length=80)
    calculation_method: str | None = Field(default=None, max_length=500)
    as_of: datetime
    dataset_version: str = Field(min_length=1, max_length=120)
    model_version: str | None = Field(default=None, max_length=120)
    sample_size: int | None = Field(default=None, ge=0, le=1_000_000)
    confidence: Decimal | None = Field(default=None, ge=Decimal("0"), le=Decimal("1"))
    provenance: dict[str, str] = Field(default_factory=dict, max_length=20)
    quality_flags: list[ShortText] = Field(default_factory=list, max_length=20)
    min_tier: Tier = "free"
    parent_evidence_ids: list[EvidenceId] = Field(default_factory=list, max_length=10)


class EvidenceConflict(ContractModel):
    evidence_ids: list[EvidenceId] = Field(min_length=2, max_length=10)
    reason: str = Field(min_length=1, max_length=500)


class EvidenceBundle(ContractModel):
    question_snapshot: str = Field(min_length=1, max_length=2_000)
    resolved_entities: dict[str, JsonValue] = Field(default_factory=dict, max_length=32)
    items: list[EvidenceItem] = Field(default_factory=list, max_length=50)
    calculations: dict[str, JsonValue] = Field(default_factory=dict, max_length=64)
    conflicts: list[EvidenceConflict] = Field(default_factory=list, max_length=20)
    warnings: list[ShortText] = Field(default_factory=list, max_length=20)
    missing_requirements: list[ShortText] = Field(default_factory=list, max_length=20)
    retrieval_quality: RetrievalQuality = RetrievalQuality.SUFFICIENT
    needs_clarification: bool = False
    clarification_candidates: list[ShortText] = Field(default_factory=list, max_length=10)


class AnswerClaim(ContractModel):
    text: str = Field(min_length=1, max_length=1_000)
    evidence_ids: list[EvidenceId] = Field(default_factory=list, max_length=10)
    material: bool = True
    numeric_value: Decimal | None = None
    unit: str | None = Field(default=None, max_length=80)


class KeyMetric(ContractModel):
    label: ShortText
    value: JsonValue
    unit: str | None = Field(default=None, max_length=80)
    evidence_ids: list[EvidenceId] = Field(default_factory=list, max_length=5)


class SourceCard(ContractModel):
    evidence_id: EvidenceId
    title: ShortText
    source_kind: SourceKind
    source_ref: str = Field(min_length=1, max_length=512)
    as_of: datetime
    href: str | None = Field(default=None, max_length=1_000)

    @field_validator("href")
    @classmethod
    def validate_safe_href(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value.startswith("/") and not value.startswith("//") and "\\" not in value:
            return value
        parsed = urlparse(value)
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError("href must be a safe HTTPS or same-origin path")
        return value


class AnswerEnvelope(ContractModel):
    answered: bool
    depth: AskDepth
    verdict: AskVerdict | None = None
    direct_answer: str = Field(min_length=1, max_length=6_000)
    claims: list[AnswerClaim] = Field(default_factory=list, max_length=20)
    key_metrics: list[KeyMetric] = Field(default_factory=list, max_length=12)
    favorable_thesis: str | None = Field(default=None, max_length=3_000)
    counter_thesis: str | None = Field(default=None, max_length=3_000)
    risks: list[ShortText] = Field(default_factory=list, max_length=12)
    confidence: Decimal | None = Field(default=None, ge=Decimal("0"), le=Decimal("1"))
    confidence_reasons: list[ShortText] = Field(default_factory=list, max_length=10)
    next_verification_steps: list[ShortText] = Field(default_factory=list, max_length=12)
    source_cards: list[SourceCard] = Field(default_factory=list, max_length=20)
    suggested_followups: list[ShortText] = Field(default_factory=list, max_length=6)
    as_of: datetime
    dataset_version: str = Field(min_length=1, max_length=120)


class ProviderUsage(ContractModel):
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cache_hit_input_tokens: int = Field(default=0, ge=0)
    cache_miss_input_tokens: int = Field(default=0, ge=0)


class ProviderToolDefinition(ContractModel):
    name: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_]*$")
    description: str = Field(min_length=1, max_length=1_000)
    parameters: dict[str, JsonValue] = Field(default_factory=dict, max_length=32)


class ProviderMessage(ContractModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = Field(default=None, max_length=50_000)
    tool_call_id: str | None = Field(default=None, max_length=80)
    tool_calls: list[ToolCall] = Field(default_factory=list, max_length=8)
    reasoning_content: str | None = Field(default=None, max_length=50_000, repr=False, exclude=True)


class ProviderRequest(ContractModel):
    model: str = Field(min_length=1, max_length=120)
    messages: list[ProviderMessage] = Field(min_length=1, max_length=30)
    tools: list[ProviderToolDefinition] = Field(default_factory=list, max_length=18)
    max_output_tokens: int = Field(ge=1, le=8_000)
    thinking_enabled: bool = False
    json_mode: bool = False


class ProviderResponse(ContractModel):
    content: str | None = Field(default=None, max_length=50_000)
    tool_calls: list[ToolCall] = Field(default_factory=list, max_length=8)
    usage: ProviderUsage = Field(default_factory=ProviderUsage)
    finish_reason: str | None = Field(default=None, max_length=80)
    reasoning_content: str | None = Field(default=None, max_length=50_000, repr=False, exclude=True)
    json_value: JsonValue | None = None


class ModelPolicy(ContractModel):
    model: str = Field(min_length=1, max_length=120)
    max_input_tokens: int = Field(ge=0, le=128_000)
    max_output_tokens: int = Field(ge=0, le=8_000)
    max_cost_usd: Decimal = Field(ge=Decimal("0"), le=Decimal("10"))
    thinking_enabled: bool = False


class UsageReservation(ContractModel):
    reservation_id: UUID
    run_id: UUID
    user_id: int = Field(gt=0)
    tier: Tier
    reserved_usd: Decimal = Field(ge=Decimal("0"), le=Decimal("50"))
    warning_active: bool = False


class UsageSettlement(ContractModel):
    reservation_id: UUID
    outcome: RunOutcome
    actual_usd: Decimal = Field(ge=Decimal("0"), le=Decimal("50"))
    question_consumed: bool


class AskRunResult(ContractModel):
    run_id: UUID
    session_id: UUID
    status: RunStatus
    answer: AnswerEnvelope | None = None
    retryable: bool = False
    error_code: str | None = Field(default=None, max_length=80, pattern=r"^[a-z0-9_]*$")
