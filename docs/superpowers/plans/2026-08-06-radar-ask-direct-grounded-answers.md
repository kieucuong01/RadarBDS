# Radar Ask Direct Grounded Answers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every successful Radar Ask response answer the question directly, with only relevant database or official-document evidence shown as supporting sources.

**Architecture:** Keep deterministic arithmetic in the existing database tools, add a small server-owned presenter boundary for the five common question types, and retain typed DeepSeek synthesis for complex routes. The existing validator remains the final grounding gate and additionally rejects the known source-only boilerplate failure mode.

**Tech Stack:** Python 3.12, Flask service layer, Pydantic contracts, PostgreSQL-backed Radar Ask tools, pytest.

## Global Constraints

- Do not add LLM calls to deterministic routes.
- Do not change crawl, reprocess, valuation, schema, vector retrieval, quotas, models, or chat layout.
- Aggregate recommendations cite matching aggregate evidence; individual claims cite exact listings.
- Sources support the prose and never replace it.
- Asking prices, model fair values, official schedules, and transaction prices remain explicitly distinct.
- Tests stay focused on the regression, grounding, source relevance, and provider-call boundary.

---

### Task 1: Make Tool Evidence Match the Recommendation

**Files:**
- Modify: `services/radar_ask/tools/market.py`
- Modify: `services/radar_ask/source_links.py`
- Test: `tests/test_radar_ask_market_tools.py`
- Test: `tests/test_radar_ask_validation.py`

**Interfaces:**
- Consumes: `match_budget(args: MatchBudgetArgs, context: ToolContext) -> EvidenceBundle` and existing `EvidenceItem`/`SourceKind.MARKET_STAT` contracts.
- Produces: one `MARKET_STAT` evidence item per `area_matches` row using `source_ref="budget-area:<ward>:<city-or-all>"`; deterministic filtered links for `budget-area`, `price-drop-area`, and `road-market` source references.

- [ ] **Step 1: Write the failing budget aggregate test**

Add an assertion to `test_match_budget_ranks_areas_without_calling_llm_for_arithmetic` that would fail if budget recommendations still cite only individual listings:

```python
area_items = [item for item in bundle.items if item.source_kind is SourceKind.MARKET_STAT]
assert [item.value["ward"] for item in area_items] == [
    row["ward"] for row in bundle.calculations["area_matches"]
]
assert area_items[0].sample_size == bundle.calculations["area_matches"][0]["listing_count"]
```

- [ ] **Step 2: Run the budget test and confirm RED**

Run: `python -X utf8 -m pytest tests/test_radar_ask_market_tools.py::test_match_budget_ranks_areas_without_calling_llm_for_arithmetic -q`

Expected: FAIL because `match_budget()` currently emits only `LISTING` evidence.

- [ ] **Step 3: Add aggregate budget evidence**

For each sorted `area_matches` row, add an item before listing examples:

```python
EvidenceItem(
    evidence_id=stable_evidence_id("market_stat", source_ref, version),
    source_kind=SourceKind.MARKET_STAT,
    source_ref=source_ref,
    value={**area_match, "budget_ty": budget, "city": canonical_city},
    unit="billion_vnd",
    calculation_method="bounded_budget_listing_ward_aggregate",
    as_of=aggregate_as_of,
    dataset_version=version,
    sample_size=area_match["listing_count"],
    provenance={"method": "current_eligible_asking_listings"},
)
```

Use the newest activity timestamp among that ward's eligible rows for `as_of`; do not query the database again.

- [ ] **Step 4: Run the budget test and confirm GREEN**

Run: `python -X utf8 -m pytest tests/test_radar_ask_market_tools.py::test_match_budget_ranks_areas_without_calling_llm_for_arithmetic -q`

Expected: PASS.

- [ ] **Step 5: Write failing source-link cases**

Extend the existing source-card parameterization with literal expected destinations:

```python
(SourceKind.MARKET_STAT, "budget-area:Phú Mỹ:Thủ Dầu Một", "/?tab=all&ward=Ph%C3%BA+M%E1%BB%B9"),
(SourceKind.MARKET_STAT, "price-drop-area:Phú Mỹ:1d", "/?tab=signals&ward=Ph%C3%BA+M%E1%BB%B9&date_range=1w"),
(SourceKind.MARKET_STAT, "road-market:Phú Mỹ:ĐL1:exact_road:90d", "/?tab=all&ward=Ph%C3%BA+M%E1%BB%B9&q=%C4%90L1&date_range=3m"),
```

Assert the returned title is human-readable and the returned `href` equals the literal expected path.

- [ ] **Step 6: Run source-link tests and confirm RED**

Run: `python -X utf8 -m pytest tests/test_radar_ask_validation.py -k "source_cards_receive_deterministic_safe_destinations" -q`

Expected: FAIL for unsupported aggregate reference formats.

- [ ] **Step 7: Implement deterministic aggregate links**

Add anchored regex patterns and construct same-origin URLs only through `urlencode`. Keep existing official HTTPS allowlisting unchanged. Budget links filter by ward, price-drop links use `tab=signals`, and road links use ward/search/date range.

- [ ] **Step 8: Run Task 1 tests and commit**

Run: `python -X utf8 -m pytest tests/test_radar_ask_market_tools.py::test_match_budget_ranks_areas_without_calling_llm_for_arithmetic tests/test_radar_ask_validation.py -k "match_budget or source_cards_receive_deterministic_safe_destinations" -q`

Commit: `git commit -m "fix: align Radar Ask evidence with recommendations"`

---

### Task 2: Present Direct Answers for Common Questions

**Files:**
- Create: `services/radar_ask/answer_presenters.py`
- Create: `tests/test_radar_ask_answer_presenters.py`
- Modify: `services/radar_ask/orchestrator.py`
- Test: `tests/test_radar_ask_orchestrator.py`

**Interfaces:**
- Consumes: `RouteDecision`, merged `EvidenceBundle`, and timezone-aware `now`.
- Produces: `present_deterministic_answer(decision: RouteDecision, bundle: EvidenceBundle, *, now: datetime) -> AnswerEnvelope`.
- The presenter performs no I/O and calls no provider. The orchestrator passes its result through `validate_answer()` exactly as before.

- [ ] **Step 1: Write failing presenter tests**

Create literal fixtures for the five supported `question_type` values. Each test names the break it catches and asserts consumer-visible behavior rather than helper internals:

```python
def test_budget_answer_ranks_wards_and_cites_each_aggregate():
    answer = present_deterministic_answer(decision("budget_match"), budget_bundle(), now=NOW)
    assert "Phú Mỹ" in answer.direct_answer
    assert "2,5 tỷ" in answer.direct_answer
    assert answer.claims[0].evidence_ids == ["budget:phu-my"]
    assert all(item.evidence_ids for item in answer.key_metrics)

def test_area_comparison_answers_which_area_is_cheaper(): ...
def test_deal_search_lists_matching_deals_and_cites_exact_listings(): ...
def test_price_drop_answer_ranks_ward_aggregates(): ...
def test_road_market_answer_labels_exact_sample_or_fallback(): ...
```

The fixtures use hand-derived expected values and complete `EvidenceItem` shapes. Add one insufficient-evidence test proving no unrelated claim/source is created.

- [ ] **Step 2: Run presenter tests and confirm RED**

Run: `python -X utf8 -m pytest tests/test_radar_ask_answer_presenters.py -q`

Expected: collection FAIL because `answer_presenters` does not exist.

- [ ] **Step 3: Implement the pure presenter boundary**

Implement a dispatch map for exactly these routes:

```python
PRESENTERS = {
    "budget_match": _present_budget_match,
    "area_comparison": _present_area_comparison,
    "deal_search": _present_deal_search,
    "price_drop_ranking": _present_price_drop_ranking,
    "road_market_estimate": _present_road_market_estimate,
}
```

Each presenter:

- leads with the conclusion;
- uses up to 3 wards for budget, 4 areas for comparison, and 5 rows for deals/drop ranking;
- cites the evidence that contains the stated values;
- adds compact key metrics only when grounded;
- says `giá chào` for asking values and labels fair value separately;
- includes sample-size/weak-sample warnings;
- never selects `bundle.items[0]` merely by position.

Retain the current grounded insufficient response as the shared fallback. For an unknown non-generated route, return an insufficient answer instead of generic source-directed prose.

- [ ] **Step 4: Run presenter tests and confirm GREEN**

Run: `python -X utf8 -m pytest tests/test_radar_ask_answer_presenters.py -q`

Expected: PASS.

- [ ] **Step 5: Write the failing orchestrator regression**

Change the deterministic fixture so it has no `answer_summary`, then assert:

```python
assert "mở các nguồn bên dưới" not in result.answer.direct_answer.lower()
assert "Phú Mỹ" in result.answer.direct_answer
assert result.answer.source_cards[0].source_ref.startswith("price-drop-area:Phú Mỹ:")
assert deps.provider.requests == []
```

- [ ] **Step 6: Run the orchestrator regression and confirm RED**

Run: `python -X utf8 -m pytest tests/test_radar_ask_orchestrator.py::test_fast_deterministic_answer_has_zero_provider_cost_and_grounded_sources -q`

Expected: FAIL on the old generic fallback or old evidence source.

- [ ] **Step 7: Delegate deterministic output to the presenter**

Replace `_deterministic_answer()`'s generic summary/first-item behavior with `present_deterministic_answer()`. Keep dataset merging, tier filtering, validation, persistence, cost reservation, and generated-provider flow unchanged.

- [ ] **Step 8: Run Task 2 tests and commit**

Run: `python -X utf8 -m pytest tests/test_radar_ask_answer_presenters.py tests/test_radar_ask_orchestrator.py -k "deterministic or direct or presenter" -q`

Commit: `git commit -m "feat: answer common Radar questions directly"`

---

### Task 3: Enforce the Universal Direct-Answer Contract

**Files:**
- Modify: `services/radar_ask/validator.py`
- Modify: `services/radar_ask/orchestrator.py`
- Test: `tests/test_radar_ask_validation.py`
- Test: `tests/test_radar_ask_orchestrator.py`

**Interfaces:**
- Consumes: all deterministic and generated `AnswerEnvelope` candidates.
- Produces: validation failure for the known generic source-only response; existing grounded generated responses remain valid.

- [ ] **Step 1: Write the failing validator regression**

Add a successful envelope with a valid citation but the production boilerplate:

```python
answer = valid_answer(
    direct_answer="Radar đã tổng hợp dữ liệu hiện có; nên mở các nguồn bên dưới để kiểm tra chi tiết.",
    claims=[AnswerClaim(text="Mở các nguồn bên dưới.", evidence_ids=[item.evidence_id])],
)
with pytest.raises(AnswerValidationError, match="does not directly answer"):
    validate_answer(answer, [bundle(items=[item])], tier="admin", expected_depth=AskDepth.STANDARD)
```

- [ ] **Step 2: Run the validator regression and confirm RED**

Run: `python -X utf8 -m pytest tests/test_radar_ask_validation.py -k "source_only" -q`

Expected: FAIL because the current validator accepts grounded but non-substantive boilerplate.

- [ ] **Step 3: Add a narrow source-only answer guard**

Fold Vietnamese accents using the validator's existing `_fold()` helper. Reject an answered response when its direct answer matches the known generic synthesis phrase or is only a directive to open/view sources. Do not reject substantive answers merely because they also recommend opening a citation.

- [ ] **Step 4: Add provider instruction and generated-route regression**

Update the existing provider request instruction to state that `direct_answer` must contain the conclusion and explanation, while citations are supporting evidence. Add an orchestrator test with a valid substantive generated answer and assert it still passes and returns canonical source cards.

- [ ] **Step 5: Run Task 3 tests and confirm GREEN**

Run: `python -X utf8 -m pytest tests/test_radar_ask_validation.py tests/test_radar_ask_orchestrator.py -k "source_only or generated_standard or direct_answer" -q`

Expected: PASS.

- [ ] **Step 6: Commit the universal contract**

Commit: `git commit -m "fix: reject source-only Radar answers"`

---

### Task 4: Focused Verification and Production Release

**Files:**
- Verify only; no planned production-file changes.

**Interfaces:**
- Consumes: completed Tasks 1-3.
- Produces: fresh test, Git, deploy, service, public API, and browser evidence.

- [ ] **Step 1: Run focused Radar Ask regression tests**

Run:

```powershell
python -X utf8 -m pytest `
  tests/test_radar_ask_answer_presenters.py `
  tests/test_radar_ask_market_tools.py `
  tests/test_radar_ask_validation.py `
  tests/test_radar_ask_orchestrator.py `
  tests/test_radar_ask_api.py `
  tests/test_radar_ask_ui.py -q
```

Expected: all selected tests PASS with no failures.

- [ ] **Step 2: Run syntax and diff checks**

Run: `python -X utf8 -m py_compile services/radar_ask/answer_presenters.py services/radar_ask/orchestrator.py services/radar_ask/tools/market.py services/radar_ask/source_links.py services/radar_ask/validator.py`

Run: `git diff --check`

Expected: both exit 0.

- [ ] **Step 3: Re-read the design and inspect the final diff**

Confirm all deterministic routes answer directly, generated routes retain typed synthesis, source relevance follows claim scope, and no non-goal was introduced.

- [ ] **Step 4: Commit remaining scoped changes, update from origin, and push main**

Stage only the Radar Ask files listed in this plan. Fetch origin, rebase the feature branch onto `origin/main` if needed, then push `HEAD:main` only after verification stays green.

- [ ] **Step 5: Deploy production and verify boundaries**

Run `scripts/deploy_production.ps1`. Verify deployed SHA, web/worker service state, and `https://radarbds.vn` HTTP health. A timeout or HTTP 200 alone is not deployment proof.

- [ ] **Step 6: Perform five Admin-account browser checks**

Ask one budget, comparison, deal, price-drop, and road-market question. Confirm each response leads with useful prose, each source supports the cited claim, and each clickable source opens the matching listing or filtered view.
