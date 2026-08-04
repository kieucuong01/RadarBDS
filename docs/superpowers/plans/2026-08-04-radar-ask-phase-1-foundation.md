# Hỏi Radar BĐS Phase 1 — Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish typed contracts, a mocked and production-safe DeepSeek adapter, durable conversation/run storage, exact quota and budget controls, adaptive routing, and a provider-independent orchestrator without exposing a live route.

**Architecture:** Add an isolated `services/radar_ask` package. PostgreSQL owns durable state and atomic reservations, Redis owns short burst protection, deterministic routing owns obvious Fast Path questions, and the provider adapter is injected behind a protocol so all foundation tests run without a live DeepSeek request.

**Tech Stack:** Python 3.12, Pydantic 2, Flask configuration, `requests`, PostgreSQL/psycopg 3, Redis 5, pytest.

---

## Phase Boundary

This phase creates no user-facing route and does not remove the legacy assistant. It produces the stable interfaces consumed by Phases 2 and 3. Keep `RADAR_ASK_ENABLED=0` throughout.

## File Map

| File | Responsibility |
|---|---|
| `requirements.txt` | Pin Pydantic 2 used for untrusted model output validation |
| `.env.example` | Document safe feature, provider, quota, cost, timeout, and retrieval defaults |
| `services/radar_ask/__init__.py` | Export the small public package surface |
| `services/radar_ask/contracts.py` | Typed request, route, tool, evidence, answer, run, provider, and usage contracts |
| `services/radar_ask/config.py` | Strict environment parsing and tier/depth/model policy |
| `services/radar_ask/provider.py` | DeepSeek HTTP boundary, tool-call/thinking continuity, JSON retry, and normalized usage |
| `db/schema.py` | Add active `radar_ask_*` tables, indexes, constraints, and migrations |
| `db/connection.py` | Include new tables in test reset order without dropping legacy tables yet |
| `db/radar_ask_connection.py` | Lazy separately bounded read-only evidence pool |
| `scripts/configure_radar_ask_db_role.py` | Owner-run creation/check of safe views and `radar_ask_ro` grants |
| `services/radar_ask/repository.py` | Owned sessions/messages/runs/tool/evidence/usage persistence |
| `services/radar_ask/limits.py` | Daily quota plus atomic monthly cost reservation/settlement |
| `services/radar_ask/burst.py` | Redis per-minute limits with bounded fail-closed behavior |
| `services/radar_ask/routing.py` | Deterministic Fast Path and typed planner fallback |
| `services/radar_ask/registry.py` | Allowlisted tool metadata and dispatcher; no SQL from model output |
| `services/radar_ask/validator.py` | Foundation envelope, vocabulary, evidence-reference, and redaction validation |
| `services/radar_ask/orchestrator.py` | Injected run lifecycle and Fast/Standard/Deep handoff contracts |
| `tests/test_radar_ask_contracts.py` | Type/config/model-policy tests |
| `tests/test_radar_ask_provider.py` | Provider mock tests |
| `tests/test_radar_ask_repository.py` | PostgreSQL ownership/state tests |
| `tests/test_radar_ask_readonly_db.py` | Role/view/pool permission and isolation tests |
| `tests/test_radar_ask_limits.py` | Daily/burst/monthly concurrency and settlement tests |
| `tests/test_radar_ask_routing.py` | Route selection and tool allowlist tests |
| `tests/test_radar_ask_orchestrator.py` | End-to-end foundation lifecycle with fakes |

## Stable Interfaces Produced

```python
def resolve_model_policy(*, tier: str, depth: AskDepth, generated: bool) -> ModelPolicy:
    raise NotImplementedError

def reserve_question(*, user_id: int, tier: str, run_id: str, max_cost_usd: Decimal) -> UsageReservation:
    raise NotImplementedError

def settle_question(*, reservation_id: str, usage: ProviderUsage, outcome: RunOutcome) -> UsageSettlement:
    raise NotImplementedError

def route_question(request: AskQuestionRequest, context: AskContext) -> RouteDecision:
    raise NotImplementedError

def execute_tool(call: ToolCall, context: ToolContext) -> EvidenceBundle:
    raise NotImplementedError

def validate_answer(answer: AnswerEnvelope, evidence: EvidenceBundle, tier: str) -> AnswerEnvelope:
    raise NotImplementedError

def run_question(request: AskQuestionRequest, context: AskContext) -> AskRunResult:
    raise NotImplementedError
```

## Task 1: Pin Pydantic and Define Contracts, Configuration, and Model Policy

**Files:**

- Modify: `requirements.txt`
- Modify: `.env.example`
- Create: `services/radar_ask/__init__.py`
- Create: `services/radar_ask/contracts.py`
- Create: `services/radar_ask/config.py`
- Test: `tests/test_radar_ask_contracts.py`

**Interfaces:** Produces every enum/model used later, including `AskDepth`, `AskVerdict`, `RunStatus`, `RunOutcome`, `AskQuestionRequest`, `AskContext`, `RouteDecision`, `ToolCall`, `EvidenceItem`, `EvidenceBundle`, `AnswerClaim`, `AnswerEnvelope`, `ProviderUsage`, `AskRunResult`, `ModelPolicy`, and `resolve_model_policy()`.

- [ ] **Step 1: Write the failing contract and model-policy tests.**

```python
from decimal import Decimal

import pytest
from pydantic import ValidationError

from services.radar_ask.config import RadarAskSettings, resolve_model_policy
from services.radar_ask.contracts import AskDepth, AskQuestionRequest


def test_question_strips_text_and_rejects_empty_input():
    assert AskQuestionRequest(question="  Giá Phú Mỹ?  ").question == "Giá Phú Mỹ?"
    with pytest.raises(ValidationError):
        AskQuestionRequest(question="   ")


def test_tier_model_policy_is_exact():
    assert resolve_model_policy(tier="free", depth=AskDepth.FAST, generated=True).model == "deepseek-v4-flash"
    assert resolve_model_policy(tier="vip", depth=AskDepth.STANDARD, generated=True).model == "deepseek-v4-pro"
    assert resolve_model_policy(tier="admin", depth=AskDepth.DEEP, generated=True).model == "deepseek-v4-pro"
    assert resolve_model_policy(tier="free", depth=AskDepth.FAST, generated=False).max_cost_usd == Decimal("0")


def test_safe_defaults_keep_feature_disabled(monkeypatch):
    monkeypatch.delenv("RADAR_ASK_ENABLED", raising=False)
    settings = RadarAskSettings.from_env()
    assert settings.enabled is False
    assert settings.allowed_tiers == frozenset({"admin"})
    assert settings.monthly_warning_usd == Decimal("20")
    assert settings.monthly_hard_stop_usd == Decimal("50")
    assert settings.cost_safety_multiplier == Decimal("2.0")
```

- [ ] **Step 2: Run the test and confirm imports fail.**

Run:

```powershell
& $py -X utf8 -m pytest tests\test_radar_ask_contracts.py -q
```

Expected: `ModuleNotFoundError: No module named 'services.radar_ask'`.

- [ ] **Step 3: Implement the typed contracts and strict configuration.**

Pin `pydantic==2.11.7`. Use `ConfigDict(extra="forbid")` for every model that parses request or provider output. Bound question length, tool calls, evidence count, claims, and text fields. Do not accept arbitrary provider fields into persisted domain models.

```python
class AskQuestionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

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


TIER_DAILY_LIMITS = {"free": 5, "vip": 20, "admin": 100}
TIER_BURST_LIMITS = {"free": 2, "vip": 5, "admin": 10}


def resolve_model_policy(*, tier: str, depth: AskDepth, generated: bool) -> ModelPolicy:
    if tier not in TIER_DAILY_LIMITS:
        raise ValueError("Radar Ask requires an authenticated tier")
    if not generated:
        return ModelPolicy(model="none", max_input_tokens=0, max_output_tokens=0, max_cost_usd=Decimal("0"))
    smart = tier in {"vip", "admin"}
    return ModelPolicy(
        model="deepseek-v4-pro" if smart else "deepseek-v4-flash",
        max_input_tokens=24_000 if depth is AskDepth.DEEP else 12_000,
        max_output_tokens=3_000 if depth is AskDepth.DEEP else 1_500,
        max_cost_usd=Decimal("0.12") if smart else Decimal("0.03"),
    )
```

Document every master-plan environment variable in `.env.example` with `RADAR_ASK_ENABLED=0` and `RADAR_ASK_ALLOWED_TIERS=admin`; never add a real key. Strictly validate the allowed-tier CSV against `free`, `vip`, and `admin`.

- [ ] **Step 4: Run focused tests.**

```powershell
& $py -X utf8 -m pytest tests\test_radar_ask_contracts.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit the contract.**

```powershell
git add -- requirements.txt .env.example services/radar_ask/__init__.py services/radar_ask/contracts.py services/radar_ask/config.py tests/test_radar_ask_contracts.py
git commit -m "feat: add typed Radar Ask contracts"
```

## Task 2: Implement the DeepSeek Provider Boundary

**Files:**

- Create: `services/radar_ask/provider.py`
- Test: `tests/test_radar_ask_provider.py`

**Interfaces:** Consumes `ModelPolicy`, typed messages and tool definitions. Produces `ProviderResponse` and normalized `ProviderUsage`. The orchestrator may depend only on the `RadarAskProvider` protocol, never on `requests` response dictionaries.

- [ ] **Step 1: Write failing mock-provider tests.**

Cover: authorization header, timeout, `deepseek-v4-flash`/`deepseek-v4-pro`, tool calls, assistant `reasoning_content` continuity before a tool result, usage normalization, non-2xx errors, one retry for an empty JSON response, and no retry after a valid response.

```python
def test_empty_json_content_retries_once(fake_session, settings):
    fake_session.queue_json({"choices": [{"message": {"content": ""}}], "usage": {}})
    fake_session.queue_json({
        "choices": [{"message": {"content": '{"route":"fast"}'}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 4, "prompt_cache_hit_tokens": 6},
    })
    client = DeepSeekProvider(settings=settings, session=fake_session)
    response = client.complete_json(model="deepseek-v4-flash", messages=[{"role": "user", "content": "x"}])
    assert response.json_value == {"route": "fast"}
    assert response.usage.input_tokens == 10
    assert response.usage.cache_hit_input_tokens == 6
    assert fake_session.call_count == 2
```

- [ ] **Step 2: Run the test and confirm the provider is missing.**

```powershell
& $py -X utf8 -m pytest tests\test_radar_ask_provider.py -q
```

Expected: import failure for `services.radar_ask.provider`.

- [ ] **Step 3: Implement a narrow HTTP adapter.**

Use `requests.Session.post()` against `${DEEPSEEK_BASE_URL}/chat/completions`; send a bearer token only in the header. Call `raise_for_status()`, enforce configured connect/read timeouts, cap response bytes before JSON parsing, and translate network/provider/shape errors into typed `ProviderUnavailable`, `ProviderRejected`, or `ProviderInvalidResponse` exceptions. Do not log request messages or the API key.

```python
class RadarAskProvider(Protocol):
    def complete(self, request: ProviderRequest) -> ProviderResponse:
        raise NotImplementedError


def _extract_usage(payload: dict[str, object]) -> ProviderUsage:
    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    return ProviderUsage(
        input_tokens=int(usage.get("prompt_tokens", 0)),
        output_tokens=int(usage.get("completion_tokens", 0)),
        cache_hit_input_tokens=int(usage.get("prompt_cache_hit_tokens", 0)),
        cache_miss_input_tokens=int(usage.get("prompt_cache_miss_tokens", 0)),
    )
```

Preserve `reasoning_content` only inside the in-memory provider conversation needed for DeepSeek tool continuation. Do not return it to users or persist it.

- [ ] **Step 4: Run focused tests.**

```powershell
& $py -X utf8 -m pytest tests\test_radar_ask_provider.py tests\test_radar_ask_contracts.py -q
```

Expected: all tests pass without network access.

- [ ] **Step 5: Commit the provider.**

```powershell
git add -- services/radar_ask/provider.py tests/test_radar_ask_provider.py
git commit -m "feat: add DeepSeek provider boundary"
```

## Task 3: Add Durable Radar Ask Persistence and Ownership

**Files:**

- Modify: `db/schema.py`
- Modify: `db/connection.py`
- Create: `services/radar_ask/repository.py`
- Test: `tests/test_radar_ask_repository.py`
- Test: `tests/test_schema_init_permissions.py`

**Interfaces:** Produces owned session/message/run CRUD, state transition methods, immutable tool/evidence audit writes, and usage aggregate reads. It does not enforce quota; Task 4 performs reservations in the same database.

- [ ] **Step 1: Write failing PostgreSQL tests.**

Test schema creation, foreign keys, indexes, unique idempotency key, cross-user lookup returning `None`, allowed run transitions, terminal-state immutability, delete-one/delete-all ownership, and cascade deletion of raw content while preserving content-free usage aggregates.

```python
def test_session_lookup_is_owner_scoped(radar_ask_repo, users):
    session = radar_ask_repo.create_session(user_id=users.free_id, title="Phú Mỹ")
    assert radar_ask_repo.get_session(user_id=users.free_id, session_id=session.id) is not None
    assert radar_ask_repo.get_session(user_id=users.vip_id, session_id=session.id) is None


def test_terminal_run_cannot_return_to_running(radar_ask_repo, users):
    run = radar_ask_repo.create_run(user_id=users.free_id, question="Giá Phú Mỹ?", idempotency_key="k-1")
    radar_ask_repo.transition_run(run.id, expected={"created"}, target="completed")
    with pytest.raises(InvalidRunTransition):
        radar_ask_repo.transition_run(run.id, expected={"completed"}, target="running")
```

- [ ] **Step 2: Run the tests and confirm schema/repository failures.**

```powershell
& $py -X utf8 -m pytest tests\test_radar_ask_repository.py tests\test_schema_init_permissions.py -q
```

Expected: missing `radar_ask_*` relations or repository import failure.

- [ ] **Step 3: Add tables and constraints.**

Add `radar_ask_sessions`, `radar_ask_messages`, `radar_ask_runs`, `radar_ask_tool_calls`, `radar_ask_evidence`, `radar_ask_usage`, and `radar_ask_feedback`. Use UUID public identifiers, `users.id` ownership, `TIMESTAMPTZ`, JSONB only for bounded typed payloads, and check constraints for statuses/roles/outcomes. Store monthly estimated/reserved/actual USD as `NUMERIC(12,6)`, never floating point.

Required uniqueness/indexes:

```sql
UNIQUE (user_id, idempotency_key)
UNIQUE (run_id, tool_call_key)
UNIQUE (run_id, evidence_key)
UNIQUE (run_key)
CREATE INDEX idx_radar_ask_sessions_owner_updated ON radar_ask_sessions(user_id, updated_at DESC);
CREATE INDEX idx_radar_ask_runs_queue ON radar_ask_runs(status, available_at, created_at);
CREATE INDEX idx_radar_ask_messages_retention ON radar_ask_messages(created_at);
CREATE INDEX idx_radar_ask_usage_user_day ON radar_ask_usage(user_id, usage_date);
CREATE INDEX idx_radar_ask_usage_month ON radar_ask_usage(usage_month, settlement_status);
```

Do not alter or drop the four legacy assistant tables in this phase.

- [ ] **Step 4: Implement repository methods through `get_conn()`.**

Every read/update includes `user_id` when ownership is relevant. Use parameterized SQL exclusively. State transitions use one guarded update whose `WHERE` includes `id = %s AND status = ANY(%s)` and whose `RETURNING` list contains `id, status`; fail if no row returns.

- [ ] **Step 5: Run database tests.**

```powershell
& $py -X utf8 -m pytest tests\test_radar_ask_repository.py tests\test_schema_init_permissions.py -q
```

Expected: all tests pass against `RADAR_TEST_DATABASE_URL`.

- [ ] **Step 6: Commit persistence.**

```powershell
git add -- db/schema.py db/connection.py services/radar_ask/repository.py tests/test_radar_ask_repository.py tests/test_schema_init_permissions.py
git commit -m "feat: add Radar Ask persistence schema"
```

## Task 4: Create the Dedicated Read-Only Evidence Role and Pool

**Files:**

- Create: `db/radar_ask_connection.py`
- Create: `scripts/configure_radar_ask_db_role.py`
- Modify: `services/radar_ask/config.py`
- Modify: `.env.example`
- Create: `tests/test_radar_ask_readonly_db.py`
- Modify: `tests/test_schema_init_permissions.py`

**Interfaces:** Produces `get_radar_ask_read_conn()` for evidence tools only. Repository/quota/session writes continue to use `db.connection.get_conn()`. The provider layer has no reference to either connection API.

- [ ] **Step 1: Write failing role, view, and pool tests.**

Test that `radar_ask_ro` can select only explicitly safe views; cannot select `users`, sessions, credentials, payments, raw listings, or arbitrary base tables; cannot INSERT/UPDATE/DELETE/DDL; starts read-only transactions; enforces statement timeout; returns connections to a lazy pool; and never exceeds configured max size.

```python
def test_radar_ask_role_can_read_safe_view_but_not_users(readonly_conn):
    assert readonly_conn.execute("SELECT listing_id FROM radar_ask_v_listings LIMIT 1").fetchall() is not None
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        readonly_conn.execute("SELECT * FROM users LIMIT 1").fetchall()


def test_radar_ask_role_cannot_write(readonly_conn):
    with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
        readonly_conn.execute("UPDATE radar_ask_v_listings SET title = 'x'")
```

- [ ] **Step 2: Run the tests and confirm the role/pool is missing.**

```powershell
& $py -X utf8 -m pytest tests\test_radar_ask_readonly_db.py tests\test_schema_init_permissions.py -q
```

Expected: missing module, role, or safe-view assertions fail.

- [ ] **Step 3: Implement owner-run, idempotent safe views and grants.**

The script supports `check` and `apply`; `apply` requires an owner connection and reads the role password from `RADAR_ASK_DB_PASSWORD` without printing it. Create/login-harden `radar_ask_ro` with `NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION`, revoke public schema/table privileges, and grant CONNECT, schema USAGE, and SELECT only on this exact manifest:

```text
radar_ask_v_listings
radar_ask_v_valuations
radar_ask_v_price_history
radar_ask_v_lot_history
radar_ask_v_signal_cards
radar_ask_v_knowledge_chunks
radar_ask_v_official_land_prices
```

`apply --phase foundation` creates/grants the six views backed by existing listing, valuation, history, signal, and official-price relations. It records `radar_ask_v_knowledge_chunks` as required for the later knowledge phase but does not create a fake view over missing tables. Phase 2 Task 5 runs `apply --phase knowledge` after the knowledge schema exists and brings the effective set to seven.

Each materialized view enumerates safe columns explicitly; none contains phone, original listing-source URL, auth/session/payment data, raw JSON, or secrets. The knowledge view may contain only canonical URLs from the curated official-source allowlist so answer citations remain usable. Own the views with a dedicated `radar_ask_view_owner` NOLOGIN role that has only the base-table SELECT needed to define them. Fully qualify every relation, use owner-evaluated view permissions, and grant `radar_ask_ro` SELECT on the views only—never on their base tables. The check command accepts `--phase foundation|knowledge`, enumerates effective grants for both roles, and fails on any unexpected relation or write privilege.

- [ ] **Step 4: Implement the separately bounded pool.**

`RADAR_ASK_DATABASE_URL` is required only when the feature is enabled. Create a lazy psycopg pool with minimum 0 and default maximum 1 per web process; the worker unit in Phase 4 overrides maximum to 2 for concurrency 2. On checkout, start a transaction with `READ ONLY`, set local statement timeout from `RADAR_ASK_STATEMENT_TIMEOUT_MS`, and always return through a context manager.

```python
@contextmanager
def get_radar_ask_read_conn() -> Iterator[psycopg.Connection]:
    pool = _get_pool()
    with pool.connection() as conn:
        with conn.transaction():
            conn.execute("SET TRANSACTION READ ONLY")
            conn.execute("SELECT set_config('statement_timeout', %s, true)", (str(settings.statement_timeout_ms),))
            yield conn
```

- [ ] **Step 5: Run permission and pool tests.**

```powershell
& $py -X utf8 -m pytest tests\test_radar_ask_readonly_db.py tests\test_schema_init_permissions.py -q
```

Expected: all tests pass; foundation effective grants contain only the six materialized safe views and no write permission, while a knowledge-phase fixture proves the seventh view can be added without broadening base-table access.

- [ ] **Step 6: Commit DB isolation.**

```powershell
git add -- db/radar_ask_connection.py scripts/configure_radar_ask_db_role.py services/radar_ask/config.py .env.example tests/test_radar_ask_readonly_db.py tests/test_schema_init_permissions.py
git commit -m "feat: isolate Radar Ask read-only database access"
```

## Task 5: Enforce Daily Quotas, Burst Limits, and Atomic Monthly Budget

**Files:**

- Modify: `db/schema.py`
- Create: `services/radar_ask/limits.py`
- Create: `services/radar_ask/burst.py`
- Test: `tests/test_radar_ask_limits.py`

**Interfaces:** Implements `reserve_question()` and `settle_question()`. Produces `QuotaExceeded`, `BurstExceeded`, `BudgetWarning`, and `BudgetHardStop` domain outcomes. The reservation method accepts an existing `run_id` and is idempotent.

- [ ] **Step 1: Write failing sequential and concurrent tests.**

Test Asia/Bangkok date rollover, Free 5/VIP 20/Admin 100, clarification release, technical-failure release, grounded insufficient-data consumption, Redis Free 2/VIP 5/Admin 10 per minute, Redis-unavailable bounded local fail-closed behavior, $20 warning, $50 reservation denial, duplicate idempotent settlement, and 20 concurrent $3 reservations never exceeding $50.

```python
def test_concurrent_reservations_never_cross_hard_stop(limit_service, run_ids):
    results = run_concurrently(
        [lambda run_id=run_id: limit_service.reserve_monthly(run_id=run_id, max_cost_usd=Decimal("3")) for run_id in run_ids]
    )
    reserved = [result for result in results if not isinstance(result, BudgetHardStop)]
    assert sum(item.reserved_usd for item in reserved) <= Decimal("50")
    assert limit_service.month_snapshot().committed_plus_reserved_usd <= Decimal("50")
```

- [ ] **Step 2: Run tests and confirm the limit services are missing.**

```powershell
& $py -X utf8 -m pytest tests\test_radar_ask_limits.py -q
```

Expected: import failure for `services.radar_ask.limits`.

- [ ] **Step 3: Implement a transactionally locked monthly ledger.**

Store one content-free `radar_ask_usage` reservation row per question, keyed by the run UUID but without a cascading foreign key so user history deletion cannot reset quota/cost accounting. Serialize monthly reservations with `SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))`, using the key `radar_ask_budget:YYYY-MM`, then sum settled actual plus active reserved USD for that month in the same transaction. Reject when `actual_usd + reserved_usd + requested_usd > 50`. Return the warning state when the same sum is at least 20. Multiply the provider-price estimate by the configured 2.0 safety factor before reservation. Settlement atomically changes the row from reserved to settled/released and records actual calculated cost once.

Daily reservation takes an advisory transaction lock keyed by `radar_ask_quota:{user_id}:{Asia/Bangkok date}`, counts active-reserved plus answered `radar_ask_usage` rows, and inserts the run-keyed reservation only below the tier limit. On success it changes the row to answered; on clarification or technical/provider/validation failure it releases the row. An `INSUFFICIENT` answer with valid grounded evidence settles as answered.

- [ ] **Step 4: Implement Redis burst protection.**

Use an atomic Redis Lua script over `radar-ask:burst:{user_id}:{minute_epoch}` with a 120-second TTL. When Redis is unavailable, use a process-local limiter with half the tier allowance, minimum one, and never write to PostgreSQL for per-minute checks.

- [ ] **Step 5: Run concurrency tests three times.**

```powershell
1..3 | ForEach-Object { & $py -X utf8 -m pytest tests\test_radar_ask_limits.py -q }
```

Expected: all three runs pass with no overspend or over-quota flake.

- [ ] **Step 6: Commit limits.**

```powershell
git add -- db/schema.py services/radar_ask/limits.py services/radar_ask/burst.py tests/test_radar_ask_limits.py
git commit -m "feat: enforce Radar Ask quota and budget"
```

## Task 6: Add Deterministic Fast Routing and the Tool Allowlist

**Files:**

- Create: `services/radar_ask/routing.py`
- Create: `services/radar_ask/registry.py`
- Test: `tests/test_radar_ask_routing.py`

**Interfaces:** Implements `route_question()` and `execute_tool()`. Tool functions are dependency-injected registrations until Phase 2 supplies evidence implementations.

- [ ] **Step 1: Write failing routing and registry tests.**

Use the five approved sample questions plus deep examples. Prove simple listing lookup/comparison/market-filter questions route without a planner call; ambiguous entity requests return clarification; explicit “nghiên cứu sâu/phân tích kỹ” selects Deep; arbitrary `sql`, URL fetch, shell, unknown tools, extra arguments, and out-of-range limits are rejected before dispatch.

```python
@pytest.mark.parametrize(
    ("question", "tool_name"),
    [
        ("Tin nào dưới 20 triệu/m² đang đáng kiểm tra?", "search_deals"),
        ("Khu nào có nhiều tín hiệu giảm giá hôm nay?", "rank_price_drop_areas"),
        ("Phú Mỹ và Định Hòa giá đất nền khác nhau sao?", "compare_areas"),
    ],
)
def test_simple_questions_use_fast_path_without_planner(question, tool_name, planner_spy):
    decision = route_question(AskQuestionRequest(question=question), make_context(planner=planner_spy))
    assert decision.depth is AskDepth.FAST
    assert decision.tool_calls[0].name == tool_name
    assert planner_spy.call_count == 0
```

- [ ] **Step 2: Run tests and confirm imports fail.**

```powershell
& $py -X utf8 -m pytest tests\test_radar_ask_routing.py -q
```

Expected: routing/registry import failure.

- [ ] **Step 3: Implement bounded deterministic patterns and typed planner fallback.**

Normalize Vietnamese text for intent matching but preserve original entity text. Deterministic patterns may choose only registered tools and bounded arguments. If no high-confidence pattern matches, call an injected planner that must return a `RouteDecision` validated by Pydantic. Cap Standard at two tool calls. Cap Deep at two tool calls for Free and four for VIP/Admin, with no recursive planning.

```python
TOOL_REGISTRY: dict[str, ToolRegistration] = {}


def execute_tool(call: ToolCall, context: ToolContext) -> EvidenceBundle:
    registration = TOOL_REGISTRY.get(call.name)
    if registration is None:
        raise ToolNotAllowed(call.name)
    args = registration.args_model.model_validate(call.arguments)
    return registration.handler(args=args, context=context)
```

Register metadata only for the Phase 2 tools; tests use fake handlers. Never accept SQL, table names, column names, URLs, Python expressions, or filesystem paths as tool arguments.

- [ ] **Step 4: Run focused tests.**

```powershell
& $py -X utf8 -m pytest tests\test_radar_ask_routing.py tests\test_radar_ask_contracts.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit routing.**

```powershell
git add -- services/radar_ask/routing.py services/radar_ask/registry.py tests/test_radar_ask_routing.py
git commit -m "feat: add adaptive Radar Ask routing"
```

## Task 7: Implement the Provider-Independent Orchestrator and Foundation Validator

**Files:**

- Create: `services/radar_ask/validator.py`
- Create: `services/radar_ask/orchestrator.py`
- Modify: `services/radar_ask/__init__.py`
- Test: `tests/test_radar_ask_orchestrator.py`

**Interfaces:** Implements `validate_answer()` and `run_question()`. Consumes repository, limits, burst, router, registry, provider, and clock protocols through an `OrchestratorDependencies` object.

- [ ] **Step 1: Write failing lifecycle tests with fakes.**

Cover: deterministic Fast answer with zero provider calls and zero cost reservation; generated Standard answer with reservation/settlement; Deep returns a queued result without provider execution; clarification releases quota; provider/validator failure releases quota and money; idempotency returns the existing run; unsupported verdict or “mua ngay” fails validation; evidence IDs must exist; Free/VIP output cannot contain phone/source URL tokens even if a malicious fake provider emits them.

```python
def test_fast_deterministic_answer_does_not_call_provider(deps):
    deps.router.return_value = fast_decision("rank_price_drop_areas")
    deps.registry.return_value = grounded_market_bundle()
    result = run_question(sample_request(), make_context(tier="free"), dependencies=deps)
    assert result.status is RunStatus.COMPLETED
    assert deps.provider.call_count == 0
    assert deps.limits.reserve_cost.call_count == 0


def test_provider_failure_releases_question_and_cost(deps):
    deps.provider.side_effect = ProviderUnavailable("timeout")
    result = run_question(sample_request(), make_context(tier="vip"), dependencies=deps)
    assert result.status is RunStatus.FAILED
    deps.limits.release_question.assert_called_once()
    deps.limits.release_cost.assert_called_once()
```

- [ ] **Step 2: Run the test and confirm missing orchestration.**

```powershell
& $py -X utf8 -m pytest tests\test_radar_ask_orchestrator.py -q
```

Expected: import failure for orchestrator/validator.

- [ ] **Step 3: Implement the explicit run state machine.**

Use only these transitions:

```text
created -> clarifying
created -> queued
created -> running
queued -> running
running -> completed
running -> insufficient
running -> failed
created|queued|running -> cancelled
```

Order operations as: authenticate context already supplied → feature setting → burst → idempotent run creation → question reservation → route → optional cost reservation → tools → optional provider → validate → persist answer/evidence/tool audit → settle. Persist sanitized exception categories, never raw prompts/provider bodies.

Foundation validation enforces the four approved verdict values, neutral advisor vocabulary, maximum text/claim counts, evidence ID existence, numeric claim citation presence, and a final redaction scan. Phase 2 strengthens semantic/numeric agreement.

- [ ] **Step 4: Run the complete Phase 1 suite.**

```powershell
& $py -X utf8 -m pytest tests\test_radar_ask_contracts.py tests\test_radar_ask_provider.py tests\test_radar_ask_repository.py tests\test_radar_ask_readonly_db.py tests\test_radar_ask_limits.py tests\test_radar_ask_routing.py tests\test_radar_ask_orchestrator.py tests\test_schema_init_permissions.py -q
```

Expected: all tests pass; provider tests make no external request.

- [ ] **Step 5: Run static checks and inspect scope.**

```powershell
& $py -X utf8 -m py_compile db\radar_ask_connection.py scripts\configure_radar_ask_db_role.py services\radar_ask\contracts.py services\radar_ask\config.py services\radar_ask\provider.py services\radar_ask\repository.py services\radar_ask\limits.py services\radar_ask\burst.py services\radar_ask\routing.py services\radar_ask\registry.py services\radar_ask\validator.py services\radar_ask\orchestrator.py
git diff --check
git status --short
```

Expected: checks pass and `.playwright-cli/` remains untracked/unstaged.

- [ ] **Step 6: Commit orchestration.**

```powershell
git add -- services/radar_ask/__init__.py services/radar_ask/validator.py services/radar_ask/orchestrator.py tests/test_radar_ask_orchestrator.py
git commit -m "feat: add Radar Ask orchestration foundation"
```

## Phase 1 Stop/Go Gate

- [ ] Run the complete Phase 1 suite three consecutive times.
- [ ] Confirm no network call occurs in tests and no live route exists.
- [ ] Confirm the evidence role has only the six foundation safe-view SELECT grants, no base-table overreach, no writes, and a separately bounded pool; Phase 2 must add the seventh knowledge view before its gate.
- [ ] Confirm Fast deterministic fixtures report `provider_calls=0`.
- [ ] Confirm 20 concurrent monthly reservations cannot cross USD 50.
- [ ] Confirm Free/VIP/Admin concurrent daily tests cannot exceed 5/20/100.
- [ ] Confirm technical failures and clarification do not consume quota.
- [ ] Confirm `RADAR_ASK_ENABLED` defaults off and the API key is absent from git diff.
- [ ] Record the committed SHA before beginning Phase 2.
