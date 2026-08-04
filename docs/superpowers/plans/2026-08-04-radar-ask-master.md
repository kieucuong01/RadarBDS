# Hỏi Radar BĐS Master Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the legacy Radar Assistant with a production-grade, authenticated real-estate investment research agent that answers simple questions quickly and deep questions with typed, validated, source-grounded evidence.

**Architecture:** Execute four independently reviewable phases: establish typed DeepSeek/provider, quota, budget, and persistence foundations; add valuation traces and the structured/document evidence layer; deliver authenticated API, worker, history, and adaptive UI; then prove quality/security/performance, remove the legacy system, and roll out by tier. PostgreSQL remains the source of truth, deterministic code owns all calculations, and DeepSeek only plans or explains allowlisted evidence.

**Tech Stack:** Python 3.12, Flask 3.1, PostgreSQL, psycopg 3, Redis 5, `requests`, Pydantic 2, DeepSeek OpenAI-compatible API, PostgreSQL full-text search, pgvector plus a benchmarked local multilingual embedding model, vanilla JavaScript, pytest, Node test runner, Playwright, Gunicorn, systemd, and Nginx.

## Global Constraints

- The approved design is `docs/superpowers/specs/2026-08-04-radar-ask-investment-research-agent-design.md`.
- Guest cannot ask questions. Free receives 5 successful questions/day, VIP 20, and Admin 100; Asia/Bangkok owns the day boundary.
- Burst limits are Free 2/minute, VIP 5/minute, and Admin 10/minute.
- Free generated answers use `deepseek-v4-flash`; VIP/Admin generated analytical answers use `deepseek-v4-pro`; the router uses Flash.
- The monthly warning threshold is USD 20 and the application hard stop is USD 50, enforced by an atomic reservation ledger before any provider call.
- Raw messages, runs, tool calls, and evidence expire after 90 days; content-free usage aggregates remain for 13 months.
- Simple deterministic questions must bypass unnecessary planning, critique, and LLM calls.
- Standard runs use at most two tools and one retrieval correction. Deep runs use at most two tools/one correction for Free and four tools/two corrections for VIP/Admin.
- DeepSeek never receives database credentials, executable SQL, secrets, phone numbers, or non-admin original URLs.
- Evidence tools use a separately budgeted `radar_ask_ro` PostgreSQL role/pool with SELECT only on explicit safe views; repository writes continue through the primary bounded pool.
- Model output is untrusted data. Pydantic validation, an allowlisted tool registry, parameterized SQL, claim-level evidence checks, bounded loops, and token/time limits are mandatory.
- User-facing signal tools use latest valuation plus `services.signal_quality.actionable_signal_sql()` and effective tier MOS policy; `valuation_results.is_signal=1` alone is insufficient.
- Deterministic crawl, normalization, deduplication, valuation, and reprocess remain LLM-free.
- AI conclusions and feedback write only to `radar_ask_*`; never contaminate `ai_training_feedback`.
- `/api/radar-ask/*` and `/hoi-radar-bds` are private/no-store and must never enter anonymous Nginx/application public caches.
- Guest/Free/VIP redaction rules remain server-side; Admin visibility on an existing page does not authorize sending PII to DeepSeek.
- `RADAR_ASK_ENABLED` defaults to `0`. USD 20/USD 50 controls must be active before the first live request.
- The legacy `/api/chat`, code, UI, and tests are removed before the first deployment of the new feature. The four dormant legacy tables are dropped only after the new production gates pass, without archive.
- Adding `valuation_trace` requires an explicit full production reprocess; deploy alone is not completion.
- Preserve unrelated `.playwright-cli/`, dirty files, runtime data, reviews, human labels, and full-database backups.
- Production completion requires commit, push, deployed SHA, migrations, service/worker state, API checks, desktop and 390px rendered proof, cost controls, and public API health.

---

## 0. Execution Prerequisites

Run implementation from the repository root with the local PostgreSQL override in `.env.local`. Do not print either database URL or the DeepSeek key.

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
.\scripts\local_postgres.ps1 start
& $py -X utf8 radar.py inspect
git status --short
```

Expected: the portable PostgreSQL 17 instance accepts connections on the configured local port, `radar.py inspect` succeeds, and unrelated `.playwright-cli/` remains untouched.

## 1. Approved Plan Set

Execute the plans in order. Each phase ends with a testable deliverable and a stop/go gate.

| Phase | Plan | Working deliverable |
|---|---|---|
| 1 | `2026-08-04-radar-ask-phase-1-foundation.md` | Typed contracts, DeepSeek client, model policy, durable sessions/runs, isolated read-only DB access, quotas, burst limits, atomic cost reservation, Fast Path, and a provider-independent orchestrator |
| 2 | `2026-08-04-radar-ask-phase-2-evidence.md` | Deterministic valuation trace, listing/market/official-document tools, hybrid retrieval, corrective evidence grading, and claim-level validation |
| 3 | `2026-08-04-radar-ask-phase-3-product.md` | Authenticated API, deep-research worker, 90-day retention, owned history, full workspace, compact drawer, contextual entry points, and Admin usage view |
| 4 | `2026-08-04-radar-ask-phase-4-release.md` | Golden evaluation, security/performance gates, legacy removal/drop migration, deployment units/runbook, staged tier rollout, and production proof |

Do not begin Phase 2 until Phase 1 interfaces and persistence tests pass. Phase 3 may start after Phase 2 tool contracts are stable, but it must not deploy ahead of valuation/evidence safety. Phase 4 owns destructive legacy table removal and production enablement.

## 2. Stable Package Boundaries

Create `services/radar_ask/` with one responsibility per module:

```text
services/radar_ask/
  contracts.py       Pydantic request, plan, evidence, answer, and status types
  config.py          env parsing, tier/model/depth/token/cost policy
  provider.py        DeepSeek HTTP client and usage normalization
  repository.py      sessions, messages, runs, tool audit, evidence, usage
  limits.py          durable daily quota and atomic monthly reservations
  burst.py           Redis per-minute protection with fail-closed bounds
  routing.py         deterministic Fast Path plus typed planner fallback
  registry.py        allowlisted tool definitions and dispatch
  orchestrator.py    run lifecycle, depth policy, retries, synthesis, validation
  evidence.py        evidence builders, deduplication, conflicts, provenance
  validator.py       claim/citation/numeric/tier validation
  tools/
    entities.py      listing/location/road resolution
    listings.py      listing facts and history
    valuation.py     valuation explanation and comparables
    market.py        road/ward/budget/drop calculations
    knowledge.py     official land price and curated document retrieval
```

Routes live in `routes/radar_ask_api.py`; they contain authentication, request parsing, and response mapping only. `app.py` supplies page rendering and existing compatibility delegates until route ownership can move without an unrelated refactor.

## 3. Stable Interfaces

Later phases rely on these exact public Python contracts:

```python
class AskDepth(str, Enum):
    FAST = "fast"
    STANDARD = "standard"
    DEEP = "deep"

class AskVerdict(str, Enum):
    WORTH_REVIEWING = "dang_xem"
    NEEDS_CHECKS = "can_kiem_tra_them"
    HIGH_RISK = "rui_ro_cao"
    INSUFFICIENT = "khong_du_du_lieu"

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

HTTP contracts:

```text
POST   /api/radar-ask/questions
GET    /api/radar-ask/runs/<run_id>
GET    /api/radar-ask/sessions
GET    /api/radar-ask/sessions/<session_id>
PATCH  /api/radar-ask/sessions/<session_id>
DELETE /api/radar-ask/sessions/<session_id>
DELETE /api/radar-ask/sessions
POST   /api/radar-ask/messages/<message_id>/feedback
GET    /admin/api/radar-ask/metrics
GET    /hoi-radar-bds
```

`POST /questions` always returns `run_id`. Completed Fast/Standard runs include `answer` with HTTP 200. Queued Deep runs return HTTP 202. Technical failure never masquerades as an answered envelope.

## 4. Feature Flags and Configuration

Add documented, safe defaults:

```dotenv
RADAR_ASK_ENABLED=0
RADAR_ASK_ALLOWED_TIERS=admin
DEEPSEEK_API_KEY=
DEEPSEEK_BASE_URL=https://api.deepseek.com
RADAR_ASK_DATABASE_URL=
RADAR_ASK_DB_POOL_MAX=1
RADAR_ASK_ROUTER_MODEL=deepseek-v4-flash
RADAR_ASK_FREE_MODEL=deepseek-v4-flash
RADAR_ASK_SMART_MODEL=deepseek-v4-pro
RADAR_ASK_MONTHLY_WARN_USD=20
RADAR_ASK_MONTHLY_HARD_USD=50
RADAR_ASK_COST_SAFETY_MULTIPLIER=2.0
RADAR_ASK_RETENTION_DAYS=90
RADAR_ASK_USAGE_RETENTION_MONTHS=13
RADAR_ASK_PROVIDER_TIMEOUT_SECONDS=30
RADAR_ASK_DEEP_TIMEOUT_SECONDS=60
RADAR_ASK_WORKER_CONCURRENCY=2
RADAR_ASK_STATEMENT_TIMEOUT_MS=2000
RADAR_ASK_EVIDENCE_ROW_LIMIT=50
RADAR_ASK_KNOWLEDGE_VECTOR_ENABLED=0
```

Production may enable vector retrieval only after the Phase 2 Vietnamese retrieval benchmark and owner-applied pgvector migration pass. The full-text path remains available when the flag is `0`.

## 5. High-Level Commit Series

Expected focused commits:

```text
feat: add typed Radar Ask contracts and DeepSeek client
feat: add Radar Ask persistence and retention schema
feat: isolate Radar Ask read-only database access
feat: enforce Radar Ask quota and monthly budget
feat: add adaptive Radar Ask orchestration
feat: persist deterministic valuation traces
feat: add listing and market evidence tools
feat: add curated knowledge retrieval
feat: validate Radar Ask claims and citations
feat: add authenticated Radar Ask API and worker
feat: add Radar Ask workspace and contextual drawer
feat: add Radar Ask admin observability
test: add Radar Ask golden evaluation gates
refactor: remove legacy Radar Assistant
ops: add Radar Ask worker and retention units
docs: document Radar Ask production rollout
chore: drop dormant legacy assistant tables
```

Before every commit:

```powershell
git diff --check
git status --short
```

Stage only task-owned files. Do not add `.playwright-cli/`, local models, embedding caches, fixtures generated from production PII, logs, or secrets.

## 6. Cross-Phase Gates

### Gate A — Foundation

- Provider client correctly normalizes tool calls, thinking continuity, JSON/empty output, timeout, and usage fields using mocks.
- Concurrent quota/budget tests cannot exceed tier daily limits or USD 50.
- Technical failures and clarification requests do not consume quota.
- Fast deterministic questions complete with zero provider calls.

### Gate B — Evidence

- Valuation trace reproduces the stored final fair price within rounding tolerance.
- Exact-road sample thresholds and fallback labels pass.
- Every numeric claim can be resolved to server evidence.
- User-facing deal tools preserve actionable signal gates and redaction.
- Full-text retrieval passes; semantic retrieval cannot enable without benchmark and pgvector proof.

### Gate C — Product

- Guest receives 401/login state; Free/VIP/Admin receive correct models and quotas.
- Cross-user session reads/deletes return 404 or 403 without revealing existence.
- Deep work does not occupy public Gunicorn threads after queue handoff.
- Desktop and 390px flows keep simple answers compact and deep details progressively disclosed.

### Gate D — Release

- Golden-set routing is at least 95%; numeric/citation/auth/privacy gates are 100%.
- Assistant load does not materially regress public APIs.
- Feature-off rollback works without restoring legacy code.
- Admin, then VIP, then Free production gates pass before dormant legacy tables are dropped.
- Final proof includes deployed SHA, DB schema, worker/timer state, cost warning/hard stop, redaction, and rendered UI.

## 7. Completion Evidence

The final release report separates:

1. unit and mock-provider tests;
2. local PostgreSQL integration and concurrency tests;
3. valuation trace full-reprocess comparison;
4. retrieval benchmark and citation evaluation;
5. desktop and 390px browser evidence;
6. VPS-local service/worker/database evidence;
7. live DeepSeek smoke cost and usage reconciliation;
8. public endpoint health and assistant-load isolation;
9. commit, push, deployed commit, migrations, feature flags, and rollback state;
10. confirmation that legacy code/routes/UI/tests and active tables are absent.

An HTTP 200, local green tests, or a committed plan is not production completion.

## 8. Approved-Spec Coverage Map

| Approved design concern | Owning plan/task |
|---|---|
| Product vocabulary, typed request/plan/evidence/answer contracts | Phase 1 Tasks 1 and 6 |
| Adaptive Fast/Standard/Deep depth without over-processing simple questions | Phase 1 Tasks 5 and 6; Phase 2 Task 7 |
| DeepSeek Flash/Pro/Thinking policy, JSON/tool behavior, context-cache-safe prompts | Phase 1 Tasks 1 and 2; Phase 4 Task 4 |
| New 90-day conversation namespace and owned deletion | Phase 1 Task 3; Phase 3 Tasks 1 and 3 |
| Free 5, VIP 20, Admin 100; burst 2/5/10 | Phase 1 Task 4; Phase 4 Task 2 |
| USD 20 warning, USD 50 atomic hard stop | Phase 1 Task 4; Phase 3 Task 6; Phase 4 Tasks 2 and 5 |
| Dedicated read-only role/pool and allowlisted DB routing with no model SQL/credentials/private data | Phase 1 Tasks 4 and 6; Phase 2 Tasks 2–5; Phase 4 Tasks 2 and 4 |
| Listing facts/history and canonical entity resolution | Phase 2 Tasks 2 and 3 |
| Deterministic valuation explanation and full reprocess | Phase 2 Task 1; Phase 4 Task 5 |
| Road/ward/budget/trend/deal/drop/risk semantics | Phase 2 Task 4 |
| Curated official knowledge, FTS, optional benchmarked semantic retrieval | Phase 2 Tasks 5 and 6 |
| Corrective retrieval and claim-level numeric/source validation | Phase 2 Task 7; Phase 4 Task 1 |
| Authenticated API, Deep worker, private cache behavior | Phase 3 Tasks 1 and 2 |
| Full workspace, drawer, contextual entry points, simple/deep disclosure | Phase 3 Tasks 4 and 5; Phase 4 Task 3 |
| Admin aggregate observability without raw conversation exposure | Phase 3 Task 6 |
| Golden accuracy, security, concurrency, performance, desktop/390px proof | Phase 4 Tasks 1–3 |
| Admin → VIP → Free rollout and rollback | Phase 4 Tasks 4 and 5 |
| Permanent legacy code/UI/table removal without archive | Phase 3 Task 5; Phase 4 Task 6 |
