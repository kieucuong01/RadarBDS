# Radar Ask Direct Grounded Answers Design

## Goal

Radar Ask must answer the user's question directly from database evidence. Source cards are supporting citations, never a substitute for the answer. This applies consistently to every deterministic simple-question route, not only budget matching.

## Confirmed Root Cause

The database tools already compute useful results, but `_deterministic_answer()` ignores those calculations unless an `answer_summary` string happens to exist. Current production tools do not set `answer_summary`, so the response falls back to a generic sentence. That fallback cites only the first evidence item, and `_source_cards()` consequently exposes only that first item. For `match_budget`, the first item is an individual listing ordered primarily by asking price, not evidence representing the recommended ward.

## Considered Approaches

1. **Server-owned deterministic presenters — selected.** Each supported question type converts typed calculations and evidence into Vietnamese answer text, claims, key metrics, follow-ups, and relevant citations. It is fast, inexpensive, testable, and keeps business logic on the server.
2. **Always send simple questions to DeepSeek.** This can produce natural prose but adds latency, cost, provider failure modes, and unnecessary variability for calculations the server already owns.
3. **Render calculations into prose in the browser.** This duplicates business rules in JavaScript, weakens citation validation, and makes API consumers disagree with the website.

The user approved approach 1: keep simple questions simple, but make their deterministic answers useful.

## Scope

Add direct presenters for all current deterministic question types:

- `budget_match`
- `area_comparison`
- `deal_search`
- `price_drop_ranking`
- `road_market_estimate`

Generated valuation, official-document, and genuinely complex routes keep the existing typed DeepSeek synthesis path, but must obey the same direct-answer contract below. Questions outside the five deterministic patterns continue through the typed planner, which may select approved database or knowledge tools and then synthesize a grounded answer. Insufficient or conflicted evidence keeps the current fail-closed answer instead of fabricating a recommendation.

## Universal Answer Contract

This contract applies to every current and future Radar Ask route, not only the five examples above:

1. The response body answers the user's question first. Source cards only support claims made in that response.
2. Deterministic questions use server-owned presenters. Complex questions use the typed planner and DeepSeek synthesis over retrieved evidence.
3. Valuation explanations state the important inputs, comparable market evidence, adjustments, model fair value, and uncertainty instead of merely linking the listing.
4. Official-price and legal-context answers explain how the cited document applies, distinguish official schedules from observed asking or transaction prices, and cite only the relevant document passages.
5. Free-form investment questions may combine approved tools, but every material factual claim must map to relevant evidence returned by those tools.
6. If the question is ambiguous, Radar asks one useful clarification. If evidence is missing or weak, Radar says what is missing and does not pad the response with unrelated sources.
7. A response that contains source cards but no substantive answer is invalid and must fail validation or be replaced with a useful safe fallback.

## Architecture

Create a focused `services/radar_ask/answer_presenters.py` module. Its public boundary consumes a validated `RouteDecision` and merged `EvidenceBundle`, then returns a complete `AnswerEnvelope` candidate for server validation.

The orchestrator remains responsible for choosing deterministic versus provider synthesis. It delegates known deterministic question types to the presenter and passes the result through the existing `validate_answer()` gate. The presenter never queries the database, never builds URLs, and never receives raw source URLs or contacts.

Database tools remain responsible for evidence quality and calculations. They must expose aggregate evidence that directly supports aggregate claims:

- Budget recommendations add one `MARKET_STAT` evidence item per ranked ward. Individual matching listings remain available as examples but are not used as the sole citation for a ward recommendation.
- Area comparison already emits one ward aggregate item per area.
- Deal search cites each returned actionable signal that appears in the answer.
- Price-drop ranking cites each ward aggregate and links it to the equivalent filtered Signals view.
- Road-market estimates cite the exact-road or explicit fallback aggregate and link it to the corresponding filtered listing view.

## Answer Contract By Question Type

### Budget Match

The answer ranks up to three wards. Each row states matching listing count, median asking price, median asking price per square metre, and budget headroom. The prose explains that the ranking reflects current eligible asking listings, not completed transactions. Claims cite the matching ward aggregate. Suggested follow-ups offer property-type refinement or comparison between the top two wards.

### Area Comparison

The answer compares up to four requested areas using sample count, median asking price per square metre, range, and freshness. It states which area is cheaper on the observed asking sample and flags small samples. Every area statement cites that area's aggregate evidence.

### Deal Search

The answer lists up to five matching deals, ordered by the existing actionable signal policy. Each result states listing reference, ward, asking price, asking price per square metre, fair price per square metre, MOS, and signal score when present. Every result cites its own signal evidence and opens the correct listing detail.

### Price-Drop Ranking

The answer ranks up to five wards by actionable price-drop signal count, with median drop and median MOS. Each ward claim cites the corresponding aggregate. Sources open Signals filtered by ward, price-drop state, and time window.

### Road Market Estimate

The answer states the observed median asking price per square metre, price range, sample count, ward, and window. It explicitly says whether the sample is exact-road or a ward/same-road-tier fallback. Low sample and extended-window warnings are translated into natural Vietnamese. The source opens Listings filtered by ward, road keyword, and time window.

## Source Relevance Rules

- Aggregate recommendation → aggregate source for the same ward/road/window.
- Individual deal statement → that exact listing source.
- Never select a source merely because it is the first item in the bundle.
- Show no more source cards than the cited claims require, with the existing maximum of 20.
- Same-origin listing and dashboard links remain server-owned; official links remain curated HTTPS only.
- Unsupported internal calculations remain labeled references rather than fake links.

## Natural-Language Rules

- Lead with the conclusion, then the evidence.
- Use compact Vietnamese suitable for an investor, without deterministic promises.
- Distinguish asking price, model fair value, official price, and transaction price.
- State sample size and weak-sample warnings near the conclusion.
- Do not expose internal identifiers except public `#listing_id` references that open Radar listing details.
- Do not add DeepSeek calls to these five simple routes.

## Failure Behaviour

- No eligible evidence: answer that current Radar data is insufficient and name the missing filter/data requirement in natural Vietnamese.
- One-area or one-row samples: answer cautiously and identify the small sample; do not manufacture a comparison.
- Missing optional statistics: omit that metric without replacing it with zero.
- A presenter producing unsupported numbers or citations must be rejected by the existing validator.

## Verification

Use focused TDD fixtures that exercise real presenter output and the existing validator:

- One test per deterministic question type proves the direct answer contains calculated values and relevant evidence IDs.
- Budget regression proves the top ward aggregate, not the first listing, is cited.
- Source-link tests prove budget, price-drop, and road aggregates open equivalent filtered views.
- Orchestrator tests prove these routes make zero provider calls and still return useful answers.
- Generated-route tests prove valuation, official-document, and typed-planner answers lead with grounded prose and never return source cards as the answer itself.
- A contract regression rejects any successful response that has citations but only generic source-directed prose.
- Existing privacy, contract, validation, routing, JavaScript rendering, and golden-evaluation tests remain green.
- Production QA asks at least one budget, comparison, deal, drop, and road question with the Admin account, then verifies answer content and opened sources.

## Non-Goals

- No crawler, reprocess, valuation-model, schema, vector-RAG, or database migration changes.
- No new provider or model.
- No redesign of the chat layout.
- No attempt to infer transaction prices from asking prices.
