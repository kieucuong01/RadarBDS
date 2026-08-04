from __future__ import annotations

import os
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

from .contracts import AskDepth, ModelPolicy, Tier


TIER_DAILY_LIMITS: dict[Tier, int] = {"free": 5, "vip": 20, "admin": 100}
TIER_BURST_LIMITS: dict[Tier, int] = {"free": 2, "vip": 5, "admin": 10}
VALID_TIERS = frozenset(TIER_DAILY_LIMITS)


def _parse_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean")


def _parse_int(name: str, default: int, *, minimum: int, maximum: int, label: str) -> int:
    raw = os.getenv(name)
    try:
        value = default if raw is None or not raw.strip() else int(raw.strip())
    except ValueError as exc:
        raise ValueError(f"{label} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{label} must be between {minimum} and {maximum}")
    return value


def _parse_decimal(
    name: str,
    default: str,
    *,
    minimum: Decimal,
    maximum: Decimal,
    label: str,
) -> Decimal:
    raw = os.getenv(name, default).strip()
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError(f"{label} must be a decimal") from exc
    if not value.is_finite() or not minimum <= value <= maximum:
        raise ValueError(f"{label} must be between {minimum} and {maximum}")
    return value


def _parse_allowed_tiers() -> frozenset[Tier]:
    raw = os.getenv("RADAR_ASK_ALLOWED_TIERS", "admin")
    values = frozenset(part.strip().lower() for part in raw.split(",") if part.strip())
    invalid = values - VALID_TIERS
    if not values or invalid:
        raise ValueError("allowed tier list must contain only free, vip, or admin")
    return values  # type: ignore[return-value]


def _validated_https_url(name: str, default: str) -> str:
    value = os.getenv(name, default).strip().rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError(f"{name} must be an HTTPS origin without credentials")
    return value


@dataclass(frozen=True)
class RadarAskSettings:
    enabled: bool
    allowed_tiers: frozenset[Tier]
    deepseek_api_key: str = field(repr=False)
    deepseek_base_url: str
    database_url: str = field(repr=False)
    db_pool_max: int
    router_model: str
    free_model: str
    smart_model: str
    monthly_warning_usd: Decimal
    monthly_hard_stop_usd: Decimal
    cost_safety_multiplier: Decimal
    retention_days: int
    usage_retention_months: int
    provider_timeout_seconds: int
    deep_timeout_seconds: int
    worker_concurrency: int
    statement_timeout_ms: int
    evidence_row_limit: int
    knowledge_vector_enabled: bool

    @classmethod
    def from_env(cls) -> "RadarAskSettings":
        warning = _parse_decimal(
            "RADAR_ASK_MONTHLY_WARN_USD",
            "20",
            minimum=Decimal("0.01"),
            maximum=Decimal("50"),
            label="monthly warning",
        )
        hard_stop = _parse_decimal(
            "RADAR_ASK_MONTHLY_HARD_USD",
            "50",
            minimum=Decimal("0.01"),
            maximum=Decimal("1000"),
            label="monthly hard stop",
        )
        if warning >= hard_stop:
            raise ValueError("monthly warning must be below monthly hard stop")

        settings = cls(
            enabled=_parse_bool("RADAR_ASK_ENABLED", False),
            allowed_tiers=_parse_allowed_tiers(),
            deepseek_api_key=os.getenv("DEEPSEEK_API_KEY", "").strip(),
            deepseek_base_url=_validated_https_url("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            database_url=os.getenv("RADAR_ASK_DATABASE_URL", "").strip(),
            db_pool_max=_parse_int(
                "RADAR_ASK_DB_POOL_MAX", 1, minimum=1, maximum=4, label="read-only DB pool max"
            ),
            router_model=os.getenv("RADAR_ASK_ROUTER_MODEL", "deepseek-v4-flash").strip(),
            free_model=os.getenv("RADAR_ASK_FREE_MODEL", "deepseek-v4-flash").strip(),
            smart_model=os.getenv("RADAR_ASK_SMART_MODEL", "deepseek-v4-pro").strip(),
            monthly_warning_usd=warning,
            monthly_hard_stop_usd=hard_stop,
            cost_safety_multiplier=_parse_decimal(
                "RADAR_ASK_COST_SAFETY_MULTIPLIER",
                "2.0",
                minimum=Decimal("1"),
                maximum=Decimal("10"),
                label="cost safety multiplier",
            ),
            retention_days=_parse_int(
                "RADAR_ASK_RETENTION_DAYS", 90, minimum=1, maximum=365, label="retention days"
            ),
            usage_retention_months=_parse_int(
                "RADAR_ASK_USAGE_RETENTION_MONTHS",
                13,
                minimum=1,
                maximum=60,
                label="usage retention months",
            ),
            provider_timeout_seconds=_parse_int(
                "RADAR_ASK_PROVIDER_TIMEOUT_SECONDS",
                30,
                minimum=1,
                maximum=120,
                label="provider timeout",
            ),
            deep_timeout_seconds=_parse_int(
                "RADAR_ASK_DEEP_TIMEOUT_SECONDS",
                60,
                minimum=1,
                maximum=300,
                label="deep timeout",
            ),
            worker_concurrency=_parse_int(
                "RADAR_ASK_WORKER_CONCURRENCY",
                2,
                minimum=1,
                maximum=8,
                label="worker concurrency",
            ),
            statement_timeout_ms=_parse_int(
                "RADAR_ASK_STATEMENT_TIMEOUT_MS",
                2_000,
                minimum=100,
                maximum=10_000,
                label="statement timeout",
            ),
            evidence_row_limit=_parse_int(
                "RADAR_ASK_EVIDENCE_ROW_LIMIT",
                50,
                minimum=1,
                maximum=50,
                label="evidence row limit",
            ),
            knowledge_vector_enabled=_parse_bool("RADAR_ASK_KNOWLEDGE_VECTOR_ENABLED", False),
        )
        if settings.deep_timeout_seconds < settings.provider_timeout_seconds:
            raise ValueError("deep timeout must be at least provider timeout")
        for label, model in (
            ("router model", settings.router_model),
            ("free model", settings.free_model),
            ("smart model", settings.smart_model),
        ):
            if not model or len(model) > 120:
                raise ValueError(f"{label} must be between 1 and 120 characters")
        return settings


def resolve_model_policy(
    *,
    tier: str,
    depth: AskDepth,
    generated: bool,
    settings: RadarAskSettings | None = None,
) -> ModelPolicy:
    if tier not in VALID_TIERS:
        raise ValueError("Radar Ask requires an authenticated tier")
    if not generated:
        return ModelPolicy(
            model="none",
            max_input_tokens=0,
            max_output_tokens=0,
            max_cost_usd=Decimal("0"),
            thinking_enabled=False,
        )

    effective_settings = settings or RadarAskSettings.from_env()
    smart_tier = tier in {"vip", "admin"}
    return ModelPolicy(
        model=effective_settings.smart_model if smart_tier else effective_settings.free_model,
        max_input_tokens=24_000 if depth is AskDepth.DEEP else 12_000,
        max_output_tokens=3_000 if depth is AskDepth.DEEP else 1_500,
        max_cost_usd=Decimal("0.12") if smart_tier else Decimal("0.03"),
        thinking_enabled=smart_tier and depth is AskDepth.DEEP,
    )
