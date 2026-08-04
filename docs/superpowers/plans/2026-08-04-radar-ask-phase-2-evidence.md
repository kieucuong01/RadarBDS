# Hỏi Radar BĐS Phase 2 — Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Radar Ask deterministic, tier-safe evidence for listings, valuation, roads, wards, opportunities, risks, and curated official documents, then validate every material claim against that evidence.

**Architecture:** Existing PostgreSQL facts and deterministic analytics remain authoritative. Valuation writes a versioned trace during reprocess. Read-only, parameterized tools convert bounded query results into typed evidence. Curated documents use PostgreSQL full-text search by default and an optional benchmark-gated local pgvector path. DeepSeek sees only the sanitized `EvidenceBundle`.

**Tech Stack:** Python 3.12, PostgreSQL/psycopg 3, Pydantic 2, existing valuation/read-model services, PostgreSQL FTS, optional pgvector and local multilingual sentence-transformers benchmark, pytest.

---

## Phase Boundary

Phase 1 must be green. This phase does not add public routes or live provider calls. It may change valuation output and schema, but the production full reprocess is deferred to the guarded Phase 4 rollout.

## File Map

| File | Responsibility |
|---|---|
| `analytics/valuation.py` | Produce deterministic, versioned valuation traces |
| `cleansing/reprocess.py` | Persist trace with the main valuation result |
| `db/schema.py` | Add `valuation_trace`, curated knowledge tables, FTS indexes, and retrieval metadata |
| `services/radar_ask/evidence.py` | Build/deduplicate evidence, conflicts, provenance, and safe provider bundles |
| `services/radar_ask/tools/entities.py` | Listing, canonical location, and road resolution |
| `services/radar_ask/tools/listings.py` | Listing facts, price history, and lot history |
| `services/radar_ask/tools/valuation.py` | Stored trace explanation, comparables, and sample quality |
| `services/radar_ask/tools/market.py` | Road/area/trend/budget/deal/drop/risk calculations |
| `services/radar_ask/tools/knowledge.py` | Official land-price and curated-document retrieval |
| `services/radar_ask/registry.py` | Register real tool handlers and typed arguments |
| `services/radar_ask/validator.py` | Corrective retrieval decision and claim-level numeric/source checks |
| `services/radar_ask/orchestrator.py` | Execute bounded evidence/repair/synthesis loop |
| `scripts/radar_ask_knowledge.py` | Validate/import curated documents and create chunks |
| `scripts/radar_ask_retrieval_benchmark.py` | Compare FTS and local embedding candidates on Vietnamese fixtures |
| `scripts/radar_ask_vector_migration.py` | Check/apply owner-authorized pgvector schema only after benchmark |
| `requirements-radar-ask-retrieval.txt` | Isolate optional local retrieval benchmark dependencies from web runtime |
| `tests/fixtures/radar_ask/official_land_price_sample.json` | Small curated ingestion fixture without production data |
| `tests/fixtures/radar_ask/retrieval_cases.json` | Versioned non-PII Vietnamese retrieval truth set |
| `tests/test_valuation_trace.py` | Trace arithmetic and persistence tests |
| `tests/test_radar_ask_entities.py` | Resolution/ambiguity tests |
| `tests/test_radar_ask_listing_tools.py` | Listing/history/tier evidence tests |
| `tests/test_radar_ask_market_tools.py` | Statistical semantics and actionable-signal tests |
| `tests/test_radar_ask_knowledge.py` | Ingestion, FTS, optional vector, and citation tests |
| `tests/test_radar_ask_validation.py` | Corrective retrieval and claim-grounding tests |

## Stable Tool Surface Produced

```text
resolve_listing
resolve_location
resolve_road
get_listing_facts
get_price_history
get_lot_history
explain_valuation
find_comparables
check_sample_quality
estimate_road_market
compare_areas
get_market_trend
match_budget
search_deals
rank_price_drop_areas
inspect_listing_risks
lookup_official_land_price
search_official_documents
```

Every tool reads through `get_radar_ask_read_conn()` and returns `EvidenceBundle`; no tool returns a cursor, DB connection, raw row, SQL fragment, phone number, or unrestricted URL.

## Task 1: Persist a Deterministic Valuation Trace

**Files:**

- Modify: `analytics/valuation.py`
- Modify: `cleansing/reprocess.py`
- Modify: `db/schema.py`
- Test: `tests/test_valuation.py`
- Test: `tests/test_valuation_snapshot.py`
- Create: `tests/test_valuation_trace.py`

**Interfaces:** Adds `ValuationTrace` and `ValuationAdjustment` dataclasses and a `valuation_trace: dict[str, object]` field on `ValuationResult`. `valuate()` produces it; `_insert_main_results()` persists it as JSONB. `explain_valuation` consumes it in Task 4.

- [ ] **Step 1: Write failing trace arithmetic and snapshot tests.**

```python
def test_trace_reproduces_fair_ppm2(sample_listing, valuation_engine):
    result = valuation_engine.valuate(sample_listing)
    trace = result.valuation_trace
    assert trace["trace_version"] == 1
    assert trace["final_fair_ppm2"] == pytest.approx(result.fair_ppm2, rel=0, abs=1)
    assert trace["final_fair_total"] == pytest.approx(result.fair_ppm2 * sample_listing.area_m2, rel=0.001)
    assert len(trace["comparable_listing_ids"]) <= 20
    assert trace["sample_count"] == result.n_segment


def test_trace_records_fallback_and_suppressed_factors(fallback_listing, valuation_engine):
    trace = valuation_engine.valuate(fallback_listing).valuation_trace
    assert trace["requested_segment"]
    assert trace["effective_segment"]
    assert trace["fallback_reason"]
    assert isinstance(trace["suppressed_factors"], list)
```

Add a persistence assertion that the latest `valuation_results.valuation_trace` survives JSONB round-trip.

- [ ] **Step 2: Run valuation tests and confirm trace failures.**

```powershell
& $py -X utf8 -m pytest tests\test_valuation.py tests\test_valuation_snapshot.py tests\test_valuation_trace.py -q
```

Expected: missing trace type/field/column assertions fail.

- [ ] **Step 3: Refactor calculation steps to emit named adjustments without changing results.**

Keep existing formula behavior. Capture the actual intermediate values used by `_select_pricing_basis()`, `predict_fair_ppm2()`, and `valuate()` rather than recomputing them after the fact.

```python
@dataclass(frozen=True)
class ValuationAdjustment:
    code: str
    input_value: float | str | None
    multiplier: float
    delta_ppm2: float
    applied: bool
    reason: str


@dataclass(frozen=True)
class ValuationTrace:
    trace_version: int
    model_name: str
    model_version: str
    requested_segment: str
    effective_segment: str
    fallback_reason: str | None
    baseline_ppm2: float
    adjustments: Sequence[ValuationAdjustment]
    final_fair_ppm2: float
    final_fair_total: float
    confidence_low_ppm2: float | None
    confidence_high_ppm2: float | None
    sample_count: int
    comparable_listing_ids: Sequence[int]
    quality_flags: Sequence[str]
    suppressed_factors: Sequence[str]
    measurement_provenance: dict[str, str]
```

Serialize with a dedicated `to_json_dict()` that rejects NaN/Infinity and sorts comparable IDs. Add `valuation_trace JSONB NOT NULL DEFAULT '{}'::jsonb` through the existing schema/migration mechanism so old rows remain readable until reprocess.

- [ ] **Step 4: Prove valuation parity.**

```powershell
& $py -X utf8 -m pytest tests\test_valuation.py tests\test_valuation_snapshot.py tests\test_valuation_trace.py -q
```

Expected: all tests pass and existing snapshot fair values remain unchanged except for the new trace field.

- [ ] **Step 5: Commit the trace.**

```powershell
git add -- analytics/valuation.py cleansing/reprocess.py db/schema.py tests/test_valuation.py tests/test_valuation_snapshot.py tests/test_valuation_trace.py
git commit -m "feat: persist deterministic valuation traces"
```

## Task 2: Build Evidence Construction and Entity Resolution

**Files:**

- Create: `services/radar_ask/evidence.py`
- Create: `services/radar_ask/tools/__init__.py`
- Create: `services/radar_ask/tools/entities.py`
- Modify: `services/radar_ask/registry.py`
- Test: `tests/test_radar_ask_entities.py`

**Interfaces:** Implements `resolve_listing`, `resolve_location`, and `resolve_road`. Produces stable evidence IDs from server-controlled kind/reference/version tuples and explicit clarification candidates.

- [ ] **Step 1: Write failing resolution and bundle-sanitization tests.**

Cover numeric listing IDs, current UI listing context, missing listing, old canonical ward mappings (`TDC Phu Chanh` → `Phu Tan`, `KDC Hiep Thanh` → `Hiep Thanh`), post-merger aliases, ambiguous road names, duplicate evidence, conflict recording, maximum evidence rows, and provider bundle removal of internal fields.

```python
def test_ambiguous_road_requires_clarification(tool_context):
    bundle = resolve_road(
        args=ResolveRoadArgs(road="Đường 30/4", city=None, ward=None),
        context=tool_context,
    )
    assert bundle.needs_clarification is True
    assert len(bundle.clarification_candidates) >= 2
    assert bundle.items == []


def test_provider_bundle_never_contains_private_fields(raw_listing_evidence):
    safe = build_provider_bundle(raw_listing_evidence, tier="admin")
    encoded = safe.model_dump_json()
    assert "phone" not in encoded.lower()
    assert "database_url" not in encoded.lower()
    assert "raw_sql" not in encoded.lower()
```

- [ ] **Step 2: Run the test and confirm modules are missing.**

```powershell
& $py -X utf8 -m pytest tests\test_radar_ask_entities.py -q
```

Expected: evidence/entity module import failure.

- [ ] **Step 3: Implement deterministic resolution.**

Use parameterized queries and the existing canonical valuation ward vocabulary. Exact canonical match wins, then an explicit alias table, then accent-insensitive candidate search. Never select the first fuzzy match when more than one eligible entity remains. `resolve_listing` must enforce current tier visibility before returning existence.

Stable evidence IDs use `sha256(f"{kind}|{source_ref}|{dataset_version}")[:20]`; raw DB primary keys may remain in server-side provenance but provider-safe evidence uses a public reference.

- [ ] **Step 4: Run tests.**

```powershell
& $py -X utf8 -m pytest tests\test_radar_ask_entities.py tests\test_radar_ask_routing.py -q
```

Expected: all tests pass and registry exposes only typed entity arguments.

- [ ] **Step 5: Commit entity evidence.**

```powershell
git add -- services/radar_ask/evidence.py services/radar_ask/tools/__init__.py services/radar_ask/tools/entities.py services/radar_ask/registry.py tests/test_radar_ask_entities.py
git commit -m "feat: add Radar Ask entity resolution"
```

## Task 3: Add Listing, History, and Tier-Redacted Evidence Tools

**Files:**

- Create: `services/radar_ask/tools/listings.py`
- Modify: `services/radar_ask/registry.py`
- Test: `tests/test_radar_ask_listing_tools.py`
- Test: `tests/test_security_hardening.py`

**Interfaces:** Implements `get_listing_facts`, `get_price_history`, and `get_lot_history`. Consumes resolved listing context and existing listing/history data ownership.

- [ ] **Step 1: Write failing fact/history/redaction tests.**

Prove current price/area/ppm²/location/property dimensions/provenance are evidence, price history is time ordered, lot history follows source-specific identity rules, hidden publisher policy is preserved, and no Free/VIP evidence or provider bundle contains phone/original URL. Admin may receive original URL only in an explicitly marked UI-only source card; `build_provider_bundle()` still strips it.

```python
@pytest.mark.parametrize("tier", ["free", "vip"])
def test_listing_evidence_redacts_source_and_phone(tier, listing_tool_context):
    bundle = get_listing_facts(args=GetListingFactsArgs(listing_id=123), context=listing_tool_context(tier=tier))
    payload = bundle.model_dump_json()
    assert "090" not in payload
    assert "facebook.com" not in payload
    assert "source_url" not in payload
```

- [ ] **Step 2: Run focused tests and confirm missing handlers.**

```powershell
& $py -X utf8 -m pytest tests\test_radar_ask_listing_tools.py tests\test_security_hardening.py -q
```

Expected: tool imports or registry dispatch fail.

- [ ] **Step 3: Implement bounded queries and evidence mapping.**

Reuse existing listing/detail/history semantics rather than duplicating visibility rules. Cap history at 50 observations and reject ranges over 365 days. Report asking price as `asking_price`, never `transaction_price`. Each value includes `as_of`, unit, dataset version, and extraction/measurement quality flags.

- [ ] **Step 4: Run tests.**

```powershell
& $py -X utf8 -m pytest tests\test_radar_ask_listing_tools.py tests\test_security_hardening.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit listing tools.**

```powershell
git add -- services/radar_ask/tools/listings.py services/radar_ask/registry.py tests/test_radar_ask_listing_tools.py tests/test_security_hardening.py
git commit -m "feat: add Radar Ask listing evidence tools"
```

## Task 4: Add Valuation, Market, Opportunity, and Risk Tools

**Files:**

- Create: `services/radar_ask/tools/valuation.py`
- Create: `services/radar_ask/tools/market.py`
- Modify: `services/radar_ask/registry.py`
- Test: `tests/test_radar_ask_market_tools.py`
- Test: `tests/test_valuation_tool.py`
- Test: `tests/test_valuation_tool_service.py`

**Interfaces:** Implements the 10 valuation/market/opportunity/risk tools listed above. Reuses `services/valuation_tool.py`, `services/advisory_memo.py`, latest valuation semantics, and `services.signal_quality.actionable_signal_sql()`.

- [ ] **Step 1: Write failing deterministic tool tests.**

Cover stored trace explanation, missing legacy trace disclaimer, comparable limits, exact-road 5+/3–4/<3 policy, 90→180 day disclosed fallback, median/P25/P75/sample count, asking/fair/official labels, budget matching, area comparison, trend/change, latest valuation only, public MOS ≥15 versus VIP/Admin explicit 10–14.9 inspection, quality blockers, and low segment confidence warning behavior.

```python
@pytest.mark.parametrize(
    ("sample_count", "expected_scope", "warning"),
    [(5, "exact_road", None), (3, "exact_road", "low_sample"), (2, "ward_road_tier_fallback", "insufficient_exact_road")],
)
def test_exact_road_thresholds(sample_count, expected_scope, warning, road_market_fixture):
    bundle = road_market_fixture(sample_count=sample_count).estimate()
    assert bundle.calculations["market_scope"] == expected_scope
    assert warning in bundle.warnings if warning else warning not in bundle.warnings


def test_search_deals_uses_actionable_gate(db, tool_context):
    insert_latest_cheap_but_non_actionable_listing(db, listing_id=701)
    bundle = search_deals(args=SearchDealsArgs(max_ppm2=20_000_000), context=tool_context(tier="free"))
    assert 701 not in bundle.server_listing_ids
```

- [ ] **Step 2: Run focused tests and confirm handler failures.**

```powershell
& $py -X utf8 -m pytest tests\test_radar_ask_market_tools.py tests\test_valuation_tool.py tests\test_valuation_tool_service.py -q
```

Expected: missing handler failures.

- [ ] **Step 3: Implement server-owned calculations.**

Use SQL/application code for medians, quantiles, samples, trends, budget bounds, rankings, and valuation arithmetic. Set a local `statement_timeout` from `RADAR_ASK_STATEMENT_TIMEOUT_MS`, cap rows at `RADAR_ASK_EVIDENCE_ROW_LIMIT`, and use allowlisted enum sorts. Exact-road results exclude deterministic quality blockers, duplicates, and bait-like prices.

`explain_valuation` returns the persisted trace, redacted input measurements, and bounded comparables. For `{}` or missing legacy trace, it sets `missing_requirements=["historical_valuation_trace"]` and never reverse-engineers an alleged historical calculation.

`search_deals` and `rank_price_drop_areas` build on latest eligible valuations and the shared actionable SQL. User-facing default is MOS ≥15; VIP/Admin may request a bounded `min_mos_pct` down to 10 and receive a caution flag below 15.

- [ ] **Step 4: Run the combined tool suite.**

```powershell
& $py -X utf8 -m pytest tests\test_radar_ask_entities.py tests\test_radar_ask_listing_tools.py tests\test_radar_ask_market_tools.py tests\test_valuation_tool.py tests\test_valuation_tool_service.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit analytical tools.**

```powershell
git add -- services/radar_ask/tools/valuation.py services/radar_ask/tools/market.py services/radar_ask/registry.py tests/test_radar_ask_market_tools.py tests/test_valuation_tool.py tests/test_valuation_tool_service.py
git commit -m "feat: add Radar Ask market evidence tools"
```

## Task 5: Add Curated Official Knowledge and Full-Text Retrieval

**Files:**

- Modify: `db/schema.py`
- Create: `services/radar_ask/tools/knowledge.py`
- Create: `scripts/radar_ask_knowledge.py`
- Modify: `scripts/configure_radar_ask_db_role.py`
- Modify: `services/radar_ask/registry.py`
- Create: `tests/test_radar_ask_knowledge.py`

**Interfaces:** Implements `lookup_official_land_price` and the always-available FTS branch of `search_official_documents`. Produces exact chunk/source citations and separates official, Radar-method, and editorial trust classes.

- [ ] **Step 1: Write failing schema, ingestion, and retrieval tests.**

Test trusted-source allowlist, HTTPS canonical URL, title/effective/publication dates, SHA-256 content idempotency, deterministic chunk IDs, updated-version supersession, Vietnamese FTS query, exact source/chunk references, effective-date filtering, arbitrary URL rejection, and official price versus market/fair labels.

```python
def test_document_import_is_idempotent(knowledge_cli, official_fixture):
    first = knowledge_cli.import_file(official_fixture)
    second = knowledge_cli.import_file(official_fixture)
    assert first.document_id == second.document_id
    assert second.inserted_chunks == 0


def test_search_returns_exact_chunk_citations(knowledge_tool_context):
    bundle = search_official_documents(
        args=SearchOfficialDocumentsArgs(query="bảng giá đất dùng để làm gì", limit=5),
        context=knowledge_tool_context,
    )
    assert bundle.items
    assert all(item.source_ref.startswith("knowledge:") for item in bundle.items)
    assert all(item.provenance["source_url"].startswith("https://") for item in bundle.items)
```

- [ ] **Step 2: Run tests and confirm missing schema/tool.**

```powershell
& $py -X utf8 -m pytest tests\test_radar_ask_knowledge.py -q
```

Expected: missing knowledge relations or tool imports.

- [ ] **Step 3: Add curated tables and FTS.**

Create `knowledge_sources`, `knowledge_documents`, and `knowledge_chunks`. Store source trust class, canonical URL, jurisdiction, document dates/version/hash, text, token count, and `search_vector`. Add a GIN index and a trigger/generated update path compatible with the current PostgreSQL version. Imports accept local UTF-8 JSON/Markdown plus a source slug already present in `knowledge_sources`; the script never downloads a URL. Extend `scripts/configure_radar_ask_db_role.py apply --phase knowledge` to create/grant `radar_ask_v_knowledge_chunks` with safe columns only.

```sql
CREATE INDEX idx_knowledge_chunks_search_vector
ON knowledge_chunks USING GIN (search_vector);
```

Rank FTS with `websearch_to_tsquery('simple', %s)` plus accent-normalized lexical terms; cap results at 10. `lookup_official_land_price` uses existing TP.HCM data and cites the governing curated document when available.

- [ ] **Step 4: Run tests and a dry-run import fixture.**

```powershell
& $py -X utf8 -m pytest tests\test_radar_ask_knowledge.py -q
& $py -X utf8 scripts\radar_ask_knowledge.py validate tests\fixtures\radar_ask\official_land_price_sample.json
& $py -X utf8 scripts\configure_radar_ask_db_role.py check --phase knowledge
```

Expected: tests pass and validation reports zero rejected documents/chunks.

- [ ] **Step 5: Commit full-text knowledge retrieval.**

```powershell
git add -- db/schema.py services/radar_ask/tools/knowledge.py services/radar_ask/registry.py scripts/radar_ask_knowledge.py scripts/configure_radar_ask_db_role.py tests/test_radar_ask_knowledge.py tests/fixtures/radar_ask/official_land_price_sample.json
git commit -m "feat: add curated Radar Ask knowledge retrieval"
```

## Task 6: Benchmark and Gate Optional Local Semantic Retrieval

**Files:**

- Create: `requirements-radar-ask-retrieval.txt`
- Create: `scripts/radar_ask_retrieval_benchmark.py`
- Create: `scripts/radar_ask_vector_migration.py`
- Create: `tests/fixtures/radar_ask/retrieval_cases.json`
- Modify: `services/radar_ask/tools/knowledge.py`
- Modify: `tests/test_radar_ask_knowledge.py`
- Modify: `docs/operations.md`

**Interfaces:** Adds `SemanticRetriever` and reciprocal-rank fusion behind `RADAR_ASK_KNOWLEDGE_VECTOR_ENABLED`. FTS remains the mandatory fallback. No production flag changes in this task.

- [ ] **Step 1: Add a non-PII Vietnamese benchmark and failing ranking tests.**

The fixture must include at least 50 cases across address aliases, post-merger wards, legal terminology, official land-price intent, paraphrased market questions, and exact-source questions. Each case stores query, accepted chunk IDs, category, and required trust class.

```python
def test_vector_flag_cannot_enable_without_extension_and_model(monkeypatch, knowledge_service):
    monkeypatch.setenv("RADAR_ASK_KNOWLEDGE_VECTOR_ENABLED", "1")
    with pytest.raises(VectorRetrievalNotReady):
        knowledge_service.reload_settings()


def test_rrf_deduplicates_and_preserves_exact_source(knowledge_service):
    fused = knowledge_service.fuse(fts=[ranked("c1", 1), ranked("c2", 2)], semantic=[ranked("c2", 1)])
    assert [item.chunk_id for item in fused] == ["c2", "c1"]
```

- [ ] **Step 2: Run the FTS/vector tests and confirm missing adapter.**

```powershell
& $py -X utf8 -m pytest tests\test_radar_ask_knowledge.py -q
```

Expected: semantic adapter/readiness test fails.

- [ ] **Step 3: Implement two offline candidates and the activation gate.**

Pin the benchmark-only dependencies in `requirements-radar-ask-retrieval.txt`, not the base web runtime. Benchmark `intfloat/multilingual-e5-small` and `BAAI/bge-m3` from an explicitly pre-downloaded local model directory. The script must use `--model-path`; it must not download models implicitly.

Record MRR@10, Recall@5 by category, peak memory, corpus indexing time, and p95 query latency. Selection rule: enable only if the chosen candidate improves macro Recall@5 by at least 8 percentage points over FTS, reaches at least 0.85 exact-source Recall@5, fits the VPS memory allowance recorded in `docs/operations.md`, and p95 local query latency is at most 250 ms.

`scripts/radar_ask_vector_migration.py check` verifies extension, vector dimension, model ID, embedding coverage, and index. `apply` requires explicit `--model-id`, `--dimension`, and database-owner access. Never call `CREATE EXTENSION` during normal app startup.

- [ ] **Step 4: Run unit tests and the FTS-only benchmark.**

```powershell
& $py -X utf8 -m pytest tests\test_radar_ask_knowledge.py -q
& $py -X utf8 scripts\radar_ask_retrieval_benchmark.py --mode fts --cases tests\fixtures\radar_ask\retrieval_cases.json --output reports\radar_ask_retrieval_fts.json
```

Expected: tests pass; report contains all categories and no raw document text. Run local-model candidates only on a machine with approved model assets, then record the selected model ID and evidence in operations docs. If no candidate passes, keep the vector flag `0`.

- [ ] **Step 5: Commit benchmark and optional adapter.**

```powershell
git add -- requirements-radar-ask-retrieval.txt scripts/radar_ask_retrieval_benchmark.py scripts/radar_ask_vector_migration.py tests/fixtures/radar_ask/retrieval_cases.json services/radar_ask/tools/knowledge.py tests/test_radar_ask_knowledge.py docs/operations.md
git commit -m "feat: benchmark Radar Ask semantic retrieval"
```

## Task 7: Add Corrective Retrieval and Claim-Level Validation

**Files:**

- Modify: `services/radar_ask/validator.py`
- Modify: `services/radar_ask/orchestrator.py`
- Create: `tests/test_radar_ask_validation.py`
- Modify: `tests/test_radar_ask_orchestrator.py`

**Interfaces:** Strengthens `validate_answer()` and `run_question()`. Adds deterministic `grade_evidence()` and tier/depth-bounded correction; provider critique is permitted only for Standard/Deep and never overrides server checks.

- [ ] **Step 1: Write failing corrective and grounding tests.**

Cover unsupported evidence IDs, number/unit mismatch, stale evidence, conflicting sources, claim missing citation, exact-source chunk mismatch, official/fair/asking label confusion, too-small road sample, prohibited purchase imperative, malicious prompt text inside a document, correction limits by depth/tier, and grounded `khong_du_du_lieu` behavior.

```python
def test_numeric_claim_must_match_cited_evidence():
    evidence = bundle_with_number(evidence_id="e-price", value=20_000_000, unit="VND/m2")
    answer = answer_with_claim(text="Giá 25 triệu/m²", evidence_ids=["e-price"])
    with pytest.raises(UnsupportedNumericClaim):
        validate_answer(answer, evidence, tier="vip")


def test_deep_vip_corrective_retrieval_runs_at_most_twice(orchestrator_deps):
    orchestrator_deps.validator.queue_results(EvidenceGrade.REPAIR, EvidenceGrade.REPAIR, EvidenceGrade.REPAIR)
    result = run_question(deep_request(), make_context(tier="vip"), dependencies=orchestrator_deps)
    assert orchestrator_deps.retriever.call_count == 3
    assert result.answer.verdict is AskVerdict.INSUFFICIENT
```

- [ ] **Step 2: Run validation tests and confirm failures.**

```powershell
& $py -X utf8 -m pytest tests\test_radar_ask_validation.py tests\test_radar_ask_orchestrator.py -q
```

Expected: unsupported claims currently pass or repair types are missing.

- [ ] **Step 3: Implement deterministic validation before optional critique.**

Parse material numbers and normalized units from each claim; require exact or declared-rounding agreement with cited `EvidenceItem` values or named server calculations. Check evidence freshness requirements, visibility, conflict state, and citation membership. Treat retrieved document text as quoted evidence data, never instructions.

Evidence grade outcomes are `SUFFICIENT`, `REPAIR`, `INSUFFICIENT`, or `CONFLICTED`. A correction may expand the time window once, resolve one missing entity, or request additional registered tools within the original plan bounds. Fast permits zero corrections; Standard and Free Deep permit one; VIP/Admin Deep permits two. After the allowed corrections are exhausted, return a grounded insufficient envelope with missing requirements and next checks.

- [ ] **Step 4: Run the complete Phase 2 suite.**

```powershell
& $py -X utf8 -m pytest tests\test_valuation.py tests\test_valuation_snapshot.py tests\test_valuation_trace.py tests\test_radar_ask_entities.py tests\test_radar_ask_listing_tools.py tests\test_radar_ask_market_tools.py tests\test_radar_ask_knowledge.py tests\test_radar_ask_validation.py tests\test_radar_ask_orchestrator.py tests\test_security_hardening.py tests\test_valuation_tool.py tests\test_valuation_tool_service.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Run static and scope checks.**

```powershell
& $py -X utf8 -m py_compile analytics\valuation.py cleansing\reprocess.py services\radar_ask\evidence.py services\radar_ask\tools\entities.py services\radar_ask\tools\listings.py services\radar_ask\tools\valuation.py services\radar_ask\tools\market.py services\radar_ask\tools\knowledge.py services\radar_ask\validator.py services\radar_ask\orchestrator.py
git diff --check
git status --short
```

- [ ] **Step 6: Commit validation.**

```powershell
git add -- services/radar_ask/validator.py services/radar_ask/orchestrator.py tests/test_radar_ask_validation.py tests/test_radar_ask_orchestrator.py
git commit -m "feat: validate Radar Ask claims and citations"
```

## Phase 2 Stop/Go Gate

- [ ] Trace arithmetic reproduces stored fair value within the declared rounding tolerance.
- [ ] Existing valuation snapshots prove no unintended price-model change.
- [ ] Tool registry contains exactly the 18 approved tools and rejects unknown/extra arguments.
- [ ] Road sample thresholds and 90→180 day disclosure pass.
- [ ] Deal tools use latest valuation plus `actionable_signal_sql()`; cheap non-actionable fixtures stay hidden.
- [ ] Free/VIP evidence and every provider bundle contain no phone/original source URL.
- [ ] FTS works when vector is disabled or unavailable.
- [ ] `radar_ask_ro` has SELECT on exactly seven final safe views and no unrestricted base-table or write privilege.
- [ ] Vector flag remains `0` unless all benchmark and owner-applied migration gates pass.
- [ ] All material numeric claims and official document claims resolve to exact evidence.
- [ ] No task added LLM behavior to crawl, normalization, deduplication, valuation, or reprocess.
- [ ] Record the committed SHA and note that production still requires a full valuation reprocess.
