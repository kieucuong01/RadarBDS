# Hỏi Radar BĐS — Investment Research Agent Design

**Date:** 2026-08-04

**Status:** Approved

**Scope:** Permanently replace the legacy Radar Assistant with an authenticated, source-grounded real-estate investment research assistant using DeepSeek, database routing, typed agentic RAG, adaptive-depth analysis, claim-level citations, durable quotas, and hard monthly cost controls.

## 1. Product Decision

The new product is named **Hỏi Radar BĐS**. It is not a general chatbot and it is not a direct buy/sell recommender. It is a decision-support research agent for Vietnamese real-estate investors.

Its conclusion vocabulary is deliberately bounded:

- `đáng xem`;
- `cần kiểm tra thêm`;
- `rủi ro cao`;
- `không đủ dữ liệu`.

It may explain an investment thesis, counter-thesis, evidence quality, and the next checks an investor should perform. It must not claim that the user should "mua ngay", promise returns, present asking prices as completed transaction prices, or substitute for legal due diligence or a licensed valuation certificate.

The feature is available only to authenticated Free, VIP, and Admin users. Guest users see a login prompt and cannot create a question run.

## 2. Goals

The system must answer both simple and deep questions without making simple questions slow or verbose.

Representative questions include:

- `Ngân sách 2.5 tỷ ở Thủ Dầu Một nên xem phường nào?`
- `Phú Mỹ và Định Hòa giá đất nền khác nhau sao?`
- `Tin nào dưới 20 triệu/m² đang đáng kiểm tra?`
- `Khu nào có nhiều tín hiệu giảm giá hôm nay?`
- `Bảng giá đất TP.HCM có dùng để định giá thực tế không?`
- `Lô đất này tại sao được định giá 2,8 tỷ?`
- `Giá hiện tại với đất mặt tiền đường XXX là bao nhiêu?`

The answer must:

1. use current Radar data or curated official sources;
2. distinguish facts, calculations, interpretation, and uncertainty;
3. attach evidence to each material claim;
4. preserve tier redaction before any data reaches DeepSeek;
5. expose the data timestamp and model/dataset version;
6. refuse or qualify the answer when evidence is insufficient;
7. remain useful when DeepSeek is unavailable for deterministic lookup questions.

## 3. Chosen Architecture

Use an **adaptive-depth, database-routed, typed RAG pipeline**.

```text
User question
  -> authentication, quota, burst limit, and budget reservation
  -> context/entity resolution
  -> complexity gate
      -> Fast Path: one deterministic tool, compact answer
      -> Standard Path: bounded plan, one or two tools, synthesis
      -> Deep Research: typed research plan, multi-source evidence,
                        corrective retrieval, analysis, counter-analysis
  -> evidence bundle
  -> typed answer generation
  -> deterministic claim/citation validation
  -> private response and durable audit record
```

This is intentionally not an unrestricted agent loop. DeepSeek may select only registered tools and typed arguments. Application code validates every call and executes parameterized, read-only queries. The model never receives database credentials, never generates executable SQL, and never performs writes.

The architecture combines the useful patterns from:

- `rag_database_routing`: route a question to the relevant data domain;
- `agentic_typed_rag_pydanticai`: typed retrieval, typed answers, validated citations, and refusal on weak evidence;
- `corrective_rag`: grade retrieval quality and retry with a corrected query;
- `hybrid_search_rag`: keyword plus semantic retrieval and reranking;
- `knowledge_graph_rag_citations`: multi-hop evidence with provenance;
- `devpulse_ai`: keep deterministic collection/calculation as utilities and reserve agents for judgment;
- `ai_real_estate_agent_team`: separate property search, market analysis, valuation, and recommendation concerns.

Qdrant and Neo4j are not introduced. PostgreSQL remains the source of truth. Structured relations already present in Radar form the domain graph, while document retrieval uses PostgreSQL full-text search plus a benchmarked local semantic index. This avoids a second paid provider and prevents another database from becoming stale relative to Radar.

## 4. Adaptive Depth and Fast Path

The first rule is: **answer at the minimum depth that fully satisfies the question**.

### 4.1 Fast Path

Fast Path applies to an exact lookup or one-aggregate question, for example:

- current asking price of one listing;
- count of listings under a price-per-square-metre threshold;
- current ward median;
- definition of the official land-price table.

Flow:

```text
resolve intent/entity -> call exactly one tool -> compact answer
```

Fast Path does not run a research planner, multi-agent critique, or corrective loop. If the fact can be rendered safely with a deterministic template, no LLM call is made. Otherwise the tier's answer model receives only the small typed result.

Fast answers contain one to three sentences, an `as_of` timestamp, relevant citations, and an optional `Phân tích sâu` action.

### 4.2 Standard Path

Standard Path applies to a comparison or recommendation that can be answered with at most two evidence domains. It allows:

- one plan or deterministic route;
- at most two tools;
- at most one retrieval correction;
- one synthesis call.

### 4.3 Deep Research

Deep Research applies when the question asks why, evaluates investment suitability, combines several constraints, compares several markets, or encounters conflicting evidence.

It allows:

- a typed research plan;
- up to four tools for VIP/Admin and two for Free;
- up to two retrieval corrections for VIP/Admin and one for Free;
- a DeepSeek Pro analysis for VIP/Admin;
- a conditional counter-analysis when the evidence conflicts, the conclusion is sensitive to assumptions, or the monetary decision is material;
- deterministic validation after synthesis.

The user may explicitly request `Phân tích sâu`. That action counts as a new daily question. The system may also select Deep Research automatically when the question requires it.

## 5. Core Typed Contracts

### 5.1 Research plan

`ResearchPlan` contains:

- `question_type`;
- normalized entities: listing, city, canonical ward, road, property type, budget, area, and time window;
- `questions_to_prove`;
- ordered, allowlisted tools and typed arguments;
- required freshness;
- maximum depth and stop conditions.

Tool names outside the registry, unknown arguments, extra properties, excessive ranges, or unauthorized scopes cause validation failure before execution.

### 5.2 Evidence item

Every `EvidenceItem` contains:

- stable `evidence_id`;
- source kind and source reference;
- value, unit, and calculation method when numeric;
- `as_of` timestamp;
- dataset and model version;
- sample size and confidence when statistical;
- provenance and quality flags;
- tier visibility;
- optional parent evidence IDs for multi-hop reasoning.

### 5.3 Evidence bundle

`EvidenceBundle` contains the question snapshot, resolved entities, all evidence items, server-computed calculations, conflicts, warnings, missing requirements, and retrieval-quality decision.

The bundle is the only domain context passed to the answer model. Raw rows, raw SQL, secrets, source phone numbers, and non-admin source URLs are excluded before prompt construction.

### 5.4 Answer envelope

`AnswerEnvelope` contains:

- `answered`;
- `depth`;
- optional `verdict`; when the question asks for investment judgment it must use the bounded vocabulary, while a purely factual Fast Path omits it;
- direct answer text;
- material `claims`, each with supporting evidence IDs;
- key metrics;
- favorable thesis;
- counter-thesis and risks;
- confidence and confidence reasons;
- next verification steps;
- source cards;
- suggested follow-up questions;
- `as_of` and dataset version.

Fast answers may omit the deep-analysis sections. An answered response must contain at least one valid evidence reference. A refusal contains no fabricated citation.

## 6. Tool Registry

Tools are focused read services, not agents.

### 6.1 Entity and context tools

- `resolve_listing`: resolve a listing ID or the listing currently open in the UI.
- `resolve_location`: map Vietnamese aliases and post-merger wording to the current canonical valuation ward without manufacturing a ward.
- `resolve_road`: normalize a road name within city/ward context and return ambiguity candidates.

Ambiguous locations or duplicate road names produce a clarification request instead of a guessed query.

### 6.2 Listing tools

- `get_listing_facts`;
- `get_price_history`;
- `get_lot_history`.

These use existing listing/detail/history ownership and apply tier redaction before producing evidence.

### 6.3 Valuation tools

- `explain_valuation`;
- `find_comparables`;
- `check_sample_quality`.

They use the latest eligible valuation and the same quality semantics as user-facing Radar surfaces. `valuation_results.is_signal=1` alone is not treated as an investable or actionable conclusion.

### 6.4 Market tools

- `estimate_road_market`;
- `compare_areas`;
- `get_market_trend`;
- `match_budget`.

Market calculations are performed in application/SQL code, not by DeepSeek. They return medians, P25-P75 ranges, sample counts, time windows, quality filters, and any fallback segment used.

### 6.5 Opportunity and risk tools

- `search_deals`;
- `rank_price_drop_areas`;
- `inspect_listing_risks`.

Deal retrieval continues to use latest valuation plus `services.signal_quality.actionable_signal_sql()` and the effective tier MOS policy. A cheap model candidate is not promoted merely because the model called it relevant.

### 6.6 Official knowledge tools

- `lookup_official_land_price`;
- `search_official_documents`.

These use the existing TP.HCM official land-price data and curated source registry. The assistant cannot fetch an arbitrary user-provided URL or perform unrestricted web search.

## 7. Valuation Explanation and Audit Trace

Add a versioned `valuation_trace` JSONB payload to each current main valuation result. It is produced during deterministic valuation, not reconstructed by DeepSeek at question time.

The trace records:

- model name, model version, and valuation timestamp;
- canonical segment and any fallback segment;
- baseline price per square metre;
- road-tier adjustment;
- area/size adjustment;
- frontage, depth, and shape adjustments when applicable;
- final fair price per square metre and total fair price;
- confidence interval;
- sample count and bounded comparable listing IDs;
- quality flags and suppressed factors;
- measurement provenance needed to explain the input.

`explain_valuation` returns the stored trace plus current redacted listing facts and comparable evidence. If a legacy valuation lacks a trace, the answer explicitly says that the exact historical calculation is unavailable; it may describe current factors but must not present a reconstructed trace as historical fact.

Adding the trace changes valuation/schema behavior, so deployment alone is insufficient. A controlled full production reprocess is required after the schema and deterministic trace writer are deployed.

## 8. Road and Area Price Semantics

The assistant must keep three concepts separate:

1. **asking market price:** observed listing distribution;
2. **Radar fair value:** deterministic model estimate;
3. **official land price:** state schedule for its legal/administrative purposes.

It may describe completed transaction price only when Radar has an explicit, authorized transaction source. It never relabels asking prices as transaction prices.

For exact-road estimates:

- five or more eligible samples: return road-specific median and P25-P75;
- three or four samples: return the road estimate with low-sample warning;
- fewer than three samples: do not claim an exact-road market price; fall back to the same ward, property type, and road tier and label the fallback prominently.

The default current-market window is 90 days. When evidence is insufficient, the retriever may expand to 180 days and must disclose that expansion. Quality blockers, duplicates, bait-like prices, and ineligible sources are excluded by deterministic policy.

## 9. Document Retrieval and Evidence Graph

Curated reports, official documents, method explanations, and public content are stored as versioned `knowledge_documents` and `knowledge_chunks` with source URL, source title, publication/effective dates, content hash, and trust class.

Retrieval uses:

1. PostgreSQL `tsvector`/GIN full-text candidates;
2. a local multilingual embedding index stored with `pgvector`;
3. reciprocal-rank fusion of lexical and semantic candidates;
4. bounded reranking for document questions only;
5. an exact source/chunk citation check after generation.

The local embedding model is selected through a Vietnamese retrieval benchmark before production activation. The benchmark must cover address aliases, legal terminology, post-merger wards, paraphrased market questions, and exact-source questions. No second paid embedding provider is introduced. If semantic retrieval is unavailable, full-text retrieval remains functional and the answer reports reduced retrieval confidence.

The evidence graph is a typed relation layer over existing PostgreSQL data:

```text
listing -> valuation -> comparable
listing -> price history -> drop signal
listing -> road -> ward -> market snapshot
official price row -> official document -> cited chunk
```

No LLM extraction is added to crawl, normalization, deduplication, valuation, or reprocess.

## 10. DeepSeek Model Policy

DeepSeek is accessed through the OpenAI-compatible API with an isolated provider client.

### 10.1 Tier routing

| Work | Free | VIP | Admin |
|---|---|---|---|
| Router/planner | `deepseek-v4-flash` | `deepseek-v4-flash` | `deepseek-v4-flash` |
| Final answer | `deepseek-v4-flash` | `deepseek-v4-pro` | `deepseek-v4-pro` |
| Deep analysis | bounded Flash | Pro Thinking | Pro Thinking |

Deterministic Fast Path may bypass the model for every tier. VIP/Admin still receive Pro whenever a generated analytical answer is required.

Thinking is disabled for simple questions. Pro Thinking is enabled only for Deep Research. Internal `reasoning_content` is never shown to users and is not retained as conversation history. The durable audit trail stores the typed plan, tool calls, evidence, validator result, and final answer instead.

Do not rely on DeepSeek beta strict mode as the security boundary. All JSON and tool calls are validated with application-side Pydantic schemas. Empty or invalid JSON is retried once within the same question run; a second failure produces a safe error or refusal and does not consume an additional daily question.

Stable system instructions and tool schemas are placed at the beginning of prompts to benefit from DeepSeek context caching. Each path has explicit input/output token caps; the advertised maximum context is never treated as a reason to send full database rows or full chat history.

## 11. Conversation Memory and Retention

Create a new namespace; do not migrate or reuse legacy assistant history.

Tables:

- `radar_ask_sessions`;
- `radar_ask_messages`;
- `radar_ask_runs`;
- `radar_ask_tool_calls`;
- `radar_ask_evidence`;
- `radar_ask_usage`;
- `radar_ask_feedback`.

Raw messages, run detail, tool calls, and evidence are retained for 90 days. A daily retention job hard-deletes expired content in bounded batches. `radar_ask_usage` retains only content-free daily/monthly counts, tokens, model, tier, and cost for 13 months so quota, budget reconciliation, and abuse investigation remain auditable.

A user may hard-delete one owned session or all owned history. The transaction cascades through messages, runs, tool calls, evidence, and feedback. Aggregate quota/cost records may remain without message content so abuse prevention and monthly accounting remain correct.

Prompt context contains only:

- the active listing/filter/page context;
- resolved entities and user preferences relevant to the question;
- a compact structured session summary;
- the small number of recent turns needed for coreference.

Cross-user context is forbidden. Session ownership is checked server-side on every read, rename, and delete.

## 12. Authentication, Quotas, and Cost Controls

### 12.1 Daily and burst limits

- Free: 5 successful questions per day; burst limit 2 per minute.
- VIP: 20 successful questions per day; burst limit 5 per minute.
- Admin: 100 successful questions per day; burst limit 10 per minute.

The day boundary is Asia/Bangkok. PostgreSQL owns the durable daily count across all Gunicorn workers. Redis owns short-window burst protection. A question is consumed when the system returns a valid answered envelope or a valid grounded `không đủ dữ liệu` conclusion. A clarification request, provider failure, internal failure, or validator failure does not consume a question. Retries and corrective sub-steps inside one run do not consume extra questions.

### 12.2 Monthly budget

The global monthly DeepSeek budget uses an atomic reservation ledger:

```text
settled monthly cost
+ active reservations
+ maximum cost reserved for the new run
<= monthly hard limit
```

- warning threshold: USD 20;
- hard stop: USD 50;
- cost is recorded from actual cache-hit, cache-miss, input, reasoning, and output usage returned by the provider;
- reservations use a defensive price multiplier so a provider price-window change cannot cross the hard limit;
- abandoned reservations expire safely;
- warning state is visible to Admin in the control room and emitted as an operations event;
- the system never switches providers automatically.

At the hard stop, deterministic no-LLM shortcuts remain available. Questions that require DeepSeek return a clear monthly-budget message without consuming quota.

## 13. Security and Trust Boundaries

Create a dedicated `radar_ask_ro` database role. It has `SELECT` only on explicit assistant views and no direct permission on authentication, secret, payment, or unrestricted user tables. The provider never receives the connection string.

Security controls include:

- authentication and current-tier evaluation before quota reservation;
- tier redaction before evidence serialization;
- parameterized SQL only;
- strict Pydantic schemas with no extra properties;
- fixed tool registry, row caps, time-window caps, and statement timeouts;
- bounded tool count, loop count, tokens, and concurrency;
- no arbitrary URL fetch, filesystem access, shell access, database writes, or side-effect tools;
- user content, listing text, and documents treated as untrusted data, never as authority to change tools or policy;
- server-rendered/DOM text escaping; no model-generated HTML;
- private/no-store responses excluded from the anonymous public-cache allowlist;
- no phone, secret, session token, source credential, or non-admin original URL in prompts;
- generic user errors and detailed private operational logs;
- ownership tests for session/history deletion;
- audit events for tier, model, tool, cost, refusal, and validation status without logging prohibited PII.

Admin may see original URLs and phones only on existing intentional Radar surfaces. This does not authorize sending those fields to DeepSeek.

## 14. Runtime Isolation and Performance

Simple and standard requests run through the Flask API with bounded provider and database timeouts. Deep Research runs use a dedicated bounded `radar-ask-worker` service so a slow model call cannot occupy the public Gunicorn path.

`POST /api/radar-ask/questions` always creates a run ID. It may return a completed Fast/Standard answer immediately or `202` for a queued Deep Research run. The browser polls the authenticated run endpoint for status; no public long-lived connection is required.

The assistant uses a separately budgeted read-only connection pool. Pool sizing must be verified against the production total connection budget before enablement. Deep-worker concurrency starts bounded and may increase only after database/provider/load evidence.

Redis may cache redacted tool evidence, keyed by normalized typed arguments, effective tier, and durable dataset version. Full conversational answers are not shared between users. A cache hit does not bypass authorization or current ownership checks.

Target service levels:

- deterministic Fast Path p95 below 1.5 seconds;
- one-tool generated response target p95 below 6 seconds;
- Deep Research target p95 below 20 seconds under the bounded production profile;
- assistant load must not materially regress `/api/signals`, `/api/listings`, `/api/counts`, or `/api/dashboard`.

## 15. User Experience

Provide two surfaces backed by the same service:

1. a compact dashboard chat drawer for quick questions;
2. `/hoi-radar-bds` as the full research workspace with owned session history, source panels, comparisons, and deep analysis.

Contextual entry points include:

- `Hỏi Radar về lô này` on listing detail;
- `Tại sao đây là tín hiệu?` on eligible signal detail;
- `Phân tích khu vực đang lọc` from the current filter state;
- `Phân tích lần giảm giá này` from price history.

Client-supplied page context is only a hint. The server reloads the referenced listing/filterable data and applies permissions.

Fast answers show the direct result, timestamp, citations, and an optional `Phân tích sâu` action. Deep answers use progressive disclosure:

1. verdict and direct answer;
2. key metrics;
3. favorable thesis;
4. counter-thesis and risks;
5. comparables and charts;
6. confidence and evidence gaps;
7. verification checklist;
8. source details and follow-up questions.

Tables and charts are generated from typed server data. DeepSeek cannot emit executable UI components or raw HTML.

## 16. Error and Refusal Behavior

- Entity ambiguity: ask one targeted clarification.
- No eligible evidence: do not call the answer model; return `không đủ dữ liệu`.
- Weak evidence after permitted corrections: return a qualified answer or refusal with the missing evidence stated.
- Database busy/timeout: fail fast before provider synthesis and do not consume quota.
- Provider timeout/error: mark the run retryable, release the cost reservation, and do not consume quota.
- Invalid/empty typed output: retry once; then refuse or fail safely.
- Citation or numeric validation failure: remove unsupported claims only when the remaining answer is coherent; otherwise refuse.
- Budget hard stop: preserve deterministic shortcuts and reject provider-dependent runs.
- Stale evidence: show `as_of` and reduce confidence rather than implying current truth.

### 16.1 Paid-call lease and database-outage boundary

Synchronous and planner runs use a 300-second PostgreSQL owner lease. The provider receives one absolute monotonic deadline of at most 240 seconds across its bounded JSON attempts, leaving more than 30 seconds for tool and persistence work. Immediately before each paid HTTP call, one short database transaction renews the run and reservation and rotates `planner:claimed:*` or `sync:claimed:*` to the matching `*:provider:*` owner. No database transaction remains open across provider HTTP.

Terminal persistence retries are bounded to three mutation attempts with 0/50/150 ms backoff and two final readbacks; they never repeat planner or answer provider work. If every mutation and readback fails, the request raises a sanitized internal failure while the long provider-phase lease and reservation remain intact for recovery. On expiry, a claimed-phase run settles only exact known planner/attempt usage, which may be zero. A provider-phase run is payment-ambiguous and settles conservatively to the greater of exact known usage and `reserved_usd`, with a clear `database_failure` outcome. Normal queued/worker expiry always sums planner usage plus every immutable recorded Deep attempt exactly once. This deliberately favors budget safety during a total database outage; an operator may later reconcile the conservative reservation against the provider bill.

## 17. Evaluation and Observability

Build a versioned golden evaluation set from production-shaped, redacted Radar snapshots. It covers:

- exact listing lookup;
- valuation explanation;
- road and ward pricing;
- area comparison;
- budget matching;
- price-drop analysis;
- official versus market price;
- ambiguous entities;
- insufficient samples;
- conflicting data;
- tier redaction and cross-user access;
- prompt injection and prohibited tool requests;
- provider error and cost-limit paths.

Required gates:

| Metric | Gate |
|---|---:|
| Server-computed numeric accuracy | 100% |
| Citation existence and tier validity | 100% |
| Free/VIP phone or original-URL leakage | 0 |
| SQL or unregistered tool execution | 0 |
| Answered material claims without evidence | 0 |
| Router/tool-family accuracy | at least 95% |
| Session ownership and deletion authorization | 100% |
| Quota and hard-budget race tests | 100% |

Retrieval is evaluated separately with recall@k, citation precision, alias resolution, and document freshness. LLM-as-judge may assist qualitative review but cannot override deterministic numeric, authorization, or citation failures.

Each run records model, depth, route, tools, database time, provider time, token/cost usage, cache usage, validator status, refusal reason, and dataset versions. The Admin control room shows aggregate usage, cost, failures, latency, and top routing errors without exposing other users' raw conversations.

User feedback is stored only in `radar_ask_feedback`. It must never be written into `ai_training_feedback`; AI-generated investment conclusions must never contaminate human valuation labels.

## 18. Legacy Radar Assistant Removal

The new system does not import, wrap, or reuse legacy assistant code or data.

Remove:

- `services/radar_assistant.py`;
- `services/assistant_intents.py`;
- `services/assistant_tools.py`;
- legacy import and implementation in `app.py`;
- `POST /api/chat` registration in `routes/market_api.py`;
- legacy chat HTML in `templates/index.html`;
- legacy `toggleChat`/send/render behavior in `static/js/main/auth_cta.js` and associated globals/contracts in `static/js/main/core.js`;
- obsolete chat CSS selectors;
- `tests/test_radar_assistant.py` and obsolete refactor-contract expectations.

Drop the active production tables in an explicit migration after the new system passes its production gates:

- `assistant_feedback`;
- `assistant_messages`;
- `assistant_sessions`;
- `assistant_user_profiles`.

Drop dependent tables before parents. Remove the tables from schema creation, reset helpers, and migrations. Do not copy rows into `radar_ask_*`, create an archive table, or write an export file.

This scoped migration does not rewrite or delete unrelated whole-database backups. Backup-retention policy is an operations concern and must not be modified in a way that risks unrelated Radar data.

## 19. Verification Strategy

Implementation follows test-driven development.

Required automated coverage includes:

- typed plan, tool arguments, evidence, and answer validation;
- Fast/Standard/Deep complexity classification;
- deterministic no-LLM Fast Path;
- every registered tool against PostgreSQL fixtures;
- valuation trace completeness and explanation;
- exact-road sample thresholds and fallback labeling;
- canonical ward and ambiguous-road resolution;
- hybrid document retrieval and exact citation matching;
- claim-level numeric validation;
- prompt injection, arbitrary SQL, arbitrary URL, and excessive-agency rejection;
- Free/VIP/Admin model selection and redaction;
- daily quota concurrency and Asia/Bangkok reset;
- USD 20 warning, USD 50 reservation race, reservation expiry, and provider reconciliation;
- 90-day retention and owned hard deletion;
- provider timeout, invalid JSON, empty JSON, retry, refusal, and no-charge failure paths;
- private/no-store/cache isolation;
- public endpoint performance regression protection;
- desktop and 390px browser behavior.

Provider-contract tests use a mock client. A small, explicitly budgeted live DeepSeek smoke suite validates current model names, tool-call shape, thinking-mode continuity, JSON behavior, token usage fields, and error mapping before production enablement.

## 20. Rollout

1. Rebase on current `origin/main` and implement in an isolated `codex/` worktree while preserving unrelated local files.
2. Add new schema, read-only role/views, provider client, tool registry, typed contracts, and tests behind `RADAR_ASK_ENABLED=0`.
3. Remove the legacy route, UI, services, JavaScript contracts, and tests so the old assistant cannot remain active or be reused. Keep its four database tables temporarily dormant only until the destructive production gate.
4. Add deterministic `valuation_trace` and run local full reprocess/evidence comparison.
5. Add the new API, worker, UI surfaces, retention job, usage ledger, and Admin observability.
6. Run focused, PostgreSQL integration, security, cost-race, retrieval-eval, JS, and browser suites.
7. Deploy with the new feature disabled and the legacy feature absent; apply additive schema/role changes and start the bounded worker.
8. Run the controlled full production reprocess required for valuation traces, then refresh affected read models/dataset versions.
9. Enable Admin only and run the production-shaped golden set plus live smoke questions.
10. Enable VIP, observe cost/latency/grounding, then enable Free.
11. After the new assistant passes production gates, execute the destructive migration that drops the four dormant legacy tables without archive.
12. Verify deployed SHA, service/worker state, database migrations, API authorization, tier/model routing, quota, budget, redaction, desktop UI, 390px UI, and public endpoint health.

The USD 20 warning and USD 50 hard stop are enabled before the first live DeepSeek request.

## 21. Rollback

The new assistant has an independent kill switch:

- set `RADAR_ASK_ENABLED=0`;
- stop `radar-ask-worker`;
- preserve user history and usage ledgers;
- leave the public dashboard/listing APIs unaffected.

Provider failures, cost spikes, or retrieval defects do not authorize re-enabling the legacy assistant. Once the legacy code/tables are removed, rollback means disabling or reverting the new assistant code while retaining compatible additive schema. The old assistant is not restored.

Before the destructive legacy drop, rollback may disable the new feature without altering old active tables. After the approved drop, restoration of old assistant data is explicitly out of scope.

## 22. Acceptance Criteria

The feature is complete only when:

- Guest cannot ask questions; authenticated tiers receive the approved daily limits;
- Free uses Flash and VIP/Admin use Pro for generated analytical answers;
- simple deterministic questions avoid unnecessary agent stages;
- deep questions can retrieve and reconcile multiple evidence domains;
- valuation explanations use stored deterministic traces;
- road-price answers disclose sample size, range, time window, and fallback;
- every displayed material claim has valid, tier-safe evidence;
- unsupported or weak answers refuse or qualify themselves;
- no model output can execute SQL, writes, URLs, shell commands, or arbitrary tools;
- raw conversation history expires at 90 days and users can hard-delete owned history;
- monthly warning/hard-stop behavior passes concurrent tests;
- assistant traffic does not materially regress public APIs;
- the old route, code, UI, tests, schema definitions, and active assistant tables are removed without archive;
- production verification proves the deployed version, migrations, worker, APIs, rendered UI, budget controls, and redaction.

## 23. Out of Scope

- direct `mua`/`không mua` commands or guaranteed-return language;
- autonomous contacting of brokers, lead submission, purchase, payment, watchlist mutation, or notification actions;
- arbitrary web browsing or user-provided URL ingestion;
- exposing original URLs or phone numbers to Free/VIP or to DeepSeek;
- replacing deterministic crawl, normalization, deduplication, valuation, or signal gates with LLM judgment;
- writing AI conclusions into `ai_training_feedback`;
- automatically changing valuation-model weights from chat feedback;
- adding BatDongSan back to the production crawl;
- deleting or rewriting unrelated full-database backups;
- switching from DeepSeek to another provider without a separate product decision.

## 24. Primary References

- https://github.com/Shubhamsaboo/awesome-llm-apps/tree/main/rag_tutorials/rag_database_routing
- https://github.com/Shubhamsaboo/awesome-llm-apps/tree/main/rag_tutorials/agentic_typed_rag_pydanticai
- https://github.com/Shubhamsaboo/awesome-llm-apps/tree/main/rag_tutorials/corrective_rag
- https://github.com/Shubhamsaboo/awesome-llm-apps/tree/main/rag_tutorials/hybrid_search_rag
- https://github.com/Shubhamsaboo/awesome-llm-apps/tree/main/rag_tutorials/knowledge_graph_rag_citations
- https://github.com/Shubhamsaboo/awesome-llm-apps/tree/main/advanced_ai_agents/multi_agent_apps/devpulse_ai
- https://github.com/Shubhamsaboo/awesome-llm-apps/tree/main/advanced_ai_agents/multi_agent_apps/agent_teams/ai_real_estate_agent_team
- https://api-docs.deepseek.com/guides/tool_calls/
- https://api-docs.deepseek.com/guides/thinking_mode/
- https://api-docs.deepseek.com/guides/json_mode/
- https://api-docs.deepseek.com/guides/kv_cache/
- https://api-docs.deepseek.com/quick_start/pricing/
