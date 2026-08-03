# Extraction-to-Valuation Integrity Hardening Design

**Date:** 2026-08-03

**Status:** Approved for implementation

**Scope:** Deterministic extraction integrity, automatic quality suppression, multi-lot detection, reprocess ordering, valuation provenance, and atomic valuation replacement from `raw_listings` through `valuation_results`.

## 1. Problem

The production pipeline is healthy and current, but the end-to-end audit found several integrity risks that can create false deal signals:

- a stored `area_m2` can represent residential land (`tho_cu_m2`) while `price_per_m2` was calculated from total land area;
- `_dimension_area_override()` currently replaces a reported area when `frontage_m * depth_m` differs by only 15%, which is too aggressive for skewed, tapered, rear-widening, or otherwise irregular lots;
- low absolute-price suppression applies only to landed property, so an obviously misparsed apartment price can remain actionable;
- the multi-lot detector can miss phrases such as `bán gấp 2 lô Chánh Mỹ` when the post does not contain two complete area/price pairs;
- valuation currently runs before price-drop detection, lifecycle updates, and cross-source deduplication, so training membership and signal scores can use stale flags;
- a full valuation run deletes the previous main and shadow results before both replacements have been computed and committed;
- main valuation rows do not identify their model run, and `crawl_run_id` is not populated;
- conversion failures in `row_to_listing()` are swallowed, making incomplete valuation coverage hard to diagnose.

The system must resolve routine cases automatically. The operator is not expected to manually review normal extraction discrepancies. When deterministic evidence cannot safely resolve a severe contradiction, the system must preserve the listing but automatically suppress it from valuation-driven signal surfaces.

## 2. Chosen Approach

Use a deterministic evidence resolver with adaptive geometry tolerance.

This is preferred over a single fixed tolerance because frontage multiplied by depth is only a rectangular approximation. It is also preferred over aggressive reconstruction because silently manufacturing a total area or per-lot price can contaminate both valuation training and deal ranking.

The implementation remains deterministic. It must not add an external LLM call to crawl, normalization, reprocess, or valuation.

The resolver follows three outcomes:

1. **Auto-repair:** correct a field only when the source text supplies stronger, unambiguous evidence.
2. **Accept:** keep the source value when differences are within the applicable tolerance or geometry is only approximate.
3. **Fail closed:** preserve the listing, attach a suppressing quality flag to its valuation result, and exclude it from baseline training and actionable signals when a severe contradiction cannot be resolved.

## 3. Extraction Integrity Rules

### 3.1 Area evidence precedence

Area candidates are classified before one is selected:

1. an explicitly declared total area, using markers such as `diện tích`, `DT`, `DT đất`, `tổng DT`, or an explicit calculated total;
2. a structured source area;
3. a single valid frontage/depth pair;
4. residential area markers such as `thổ cư`, `TC`, or `ODT`, which are stored only as `tho_cu_m2`.

An explicit `tho_cu_m2` value must never become `area_m2` when a distinct total-area candidate exists. If the structured area matches the residential-area candidate within 3% and the text supplies a larger explicit total area, the resolver automatically replaces `area_m2` with the total area and recomputes `price_per_m2`.

An explicit total area wins over `frontage_m * depth_m`. Dimensions are supporting evidence, not an automatic overwrite, whenever a reported total area exists.

When total area is missing, the resolver may infer `area_m2 = frontage_m * depth_m` only if:

- there is exactly one plausible frontage/depth pair;
- frontage is from 2 through 50 metres;
- depth is from 5 through 500 metres;
- the text has no irregular-geometry cue;
- the post is not detected as a multi-lot offer.

### 3.2 Adaptive geometry tolerance

The symmetric geometry difference is:

```text
geometry_difference = abs(reported_area - frontage * depth)
                      / max(reported_area, frontage * depth)
```

Irregular-geometry cues include folded Vietnamese variants of `xéo`, `xéo hậu`, `nở hậu`, `thóp hậu`, `thắt hậu`, `hình thang`, `tam giác`, `hai mặt tiền`, and posts that provide multiple frontage or depth values.

The suppressing `area_dimension_conflict` flag is applied only when all compared values are plausible and:

| Geometry evidence | Severe threshold |
|---|---:|
| No irregular cue, one dimension pair | greater than 40% |
| Irregular cue or multiple side dimensions | greater than 60% |

Differences at or below those thresholds do not overwrite an explicit total area and do not suppress the listing. This deliberately tolerates normal measurement error and non-rectangular lots.

If an explicit total area and dimensions disagree beyond the severe threshold, the explicit total remains stored but the valuation receives `area_dimension_conflict`. The listing remains visible in Tin rao but cannot train the model or become an actionable signal.

### 3.3 Price and unit-price consistency

The canonical invariant is:

```text
price_per_m2 = price_ty * 1000 / area_m2
```

After final price and total area are selected, `price_per_m2` is always recomputed from those two values. A stale structured `price_per_m2` never survives merely because it was non-null.

Clear total-price evidence in title or description may replace a structured price when the values differ by more than 15%. Masked, deposit, discount, monthly-rent, and multi-lot aggregate prices are not treated as clear asking-price evidence.

For sale listings, `too_low_absolute_price` applies to every property type when `price_ty <= 0.05` billion VND. The existing stricter landed-property rule remains in force. This catches unit errors such as an apartment stored as `0.002` billion while avoiding a new broad upper/lower market-price model.

If price, total area, and unit price still cannot be reconciled deterministically, the valuation receives `price_area_inconsistent`, which is a suppressing flag. No value is fabricated solely to keep the listing eligible.

### 3.4 Multi-lot offers

The detector is expanded to recognize a numeric lot count followed by a lot noun even without complete repeated price/area pairs, including phrases such as:

- `bán gấp 2 lô Chánh Mỹ`;
- `còn 3 nền liền kề`;
- `bán 2 lô đất`.

Rental inventory phrases and numbered room/unit descriptions remain excluded.

Phase 1 does not split one raw post into synthetic child listings. A detected multi-lot sale receives `multi_lot_listing` and is automatically excluded from valuation training and actionable signals. This is safer than guessing whether price and area are totals or per-lot values. The original listing and raw content remain intact.

## 4. Module Boundaries

Create `cleansing/extraction_integrity.py` as the focused deterministic policy module. It owns:

- area-evidence classification;
- irregular-geometry detection;
- geometry-difference calculation and severe-conflict decision;
- price/area/unit-price reconciliation;
- structured integrity flags and counters.

`cleansing/normalizer.py` remains the orchestrator that gathers source fields and text, calls the resolver once, and writes the selected `price_ty`, `area_m2`, `tho_cu_m2`, and derived `price_per_m2` into the normalized record.

Persist unresolved deterministic flags in `listings.extraction_quality_flags` so valuation can reproduce the same fail-closed decision after the normalized row has been committed. Each deterministic reprocess overwrites this field, including clearing stale flags; it is not a human or AI label.

`cleansing/feature_extractor.py` continues to own text extraction and gains only the bounded multi-lot phrase coverage needed by the policy.

`cleansing/reprocess.py` consumes the same integrity policy when building valuation quality flags. This ensures already-normalized rows and future incremental rows receive identical suppression semantics.

`services/extraction_audit.py` uses the same tolerance and candidate classification helpers instead of independently treating a 5% area difference as an extraction error. The audit becomes an automated measurement tool; it no longer assumes every geometric difference is a correction.

`services/signal_quality.py` adds `price_area_inconsistent` to `ACTIONABLE_SUPPRESS_FLAGS`. Existing flags and the rule that `low_segment_confidence` is warning-only remain unchanged.

## 5. Reprocess Data Flow

The full and incremental pipeline order becomes:

```text
raw_listings
  -> normalize/upsert listings
  -> content hashes and cross-source dedup
  -> price-drop detection and lifecycle state
  -> market trend refresh
  -> fit main and shadow models from current eligible rows
  -> valuate the requested rows
  -> atomically replace main and shadow valuation results
  -> refresh maps/public read models and publish dataset versions
```

Valuation must run after dedup and price-drop detection so:

- duplicates do not enter the current training baseline;
- a current `price_dropped` flag contributes to the same run's signal score;
- stale price-drop state cannot continue contributing after it is cleared;
- user-facing actionable results match the state published in the same pipeline run.

Public read-model refresh and cache/version publication occur only after valuation replacement commits successfully. A failed valuation run must not publish a mixed dataset.

## 6. Atomic Valuation Replacement and Provenance

Both models are fitted and evaluated in memory before destructive database work begins.

One database transaction then performs the complete replacement:

1. create complete `valuation_model_runs` metadata for the main and shadow engines;
2. delete the prior target rows: all rows for a full run or only requested listing IDs for an incremental run;
3. insert main `valuation_results` and shadow `valuation_shadow_results`;
4. update listing outlier fields;
5. commit once.

Any insert or update failure rolls back the transaction and leaves the previous main, shadow, and listing-outlier state active.

Add nullable `model_run_id` to `valuation_results`, referencing `valuation_model_runs`. Main rows use `analytics.valuation.MAIN_MODEL_VERSION`; shadow rows retain their existing model identity. Populate each valuation row's existing `crawl_run_id` from its listing so an output can be traced to the normalization/reprocess run that produced it; `listings.raw_id -> raw_listings.crawl_run_id` remains the source-crawl provenance path.

`upsert_listing()` must therefore persist its existing `crawl_run_id` argument on both insert and update, retaining the previous value only when a caller supplies no run ID.

Each model run records deterministic metrics in `metrics_json`:

- training input count;
- valuation input count;
- actionable signal count;
- suppressing integrity-flag counts;
- rejected conversion count.

`row_to_listing()` conversion errors must not be swallowed. The run logs the listing ID and reason, increments the rejected count, and aborts before replacement. Because replacement has not begun, the previous snapshot remains active and the next scheduled run can retry safely.

## 7. Compatibility and Data Preservation

- Do not modify or delete `raw_listings`.
- Reprocessing may update deterministic fields on `listings`, but must preserve URLs, images, price history, dedup history, user saves, audit records, `ai_deal_review`, and `ai_training_feedback`.
- AI or Claude verdicts remain isolated in `ai_deal_review`; this work does not create human labels.
- Guest, Free, and VIP redaction rules remain unchanged.
- User-facing signal queries continue to require latest valuation plus `actionable_signal_sql()`.
- The main valuation formula and signal MOS threshold are unchanged.
- The shadow model remains diagnostic; no main-to-shadow switch is authorized.
- Guland publisher-activity flags remain visibility/ranking policy only and do not become valuation features.

## 8. Automated Verification

All behavior changes follow test-driven development: add one failing behavior test, observe the expected failure, implement the minimum change, and rerun the focused and regression suites.

Required tests include:

- explicit total area is preserved when dimensions differ by 15%, 30%, or 40%;
- a regular lot becomes `area_dimension_conflict` only above 40%;
- an irregular/xéo lot is tolerated through 60% and suppressed only above 60%;
- a distinct total area replaces a structured area that equals `tho_cu_m2`;
- missing regular-lot area can still be inferred from one valid dimension pair;
- missing irregular-lot area is not manufactured from dimensions;
- final `price_per_m2` equals `price_ty * 1000 / area_m2` within rounding tolerance;
- an unambiguous text price automatically repairs a unit-scaled structured price;
- a sale price at or below `0.05` billion is suppressed for apartments and other non-land types;
- numeric multi-lot phrases are detected without creating false positives for rental inventory;
- automated extraction audit shares the adaptive geometry thresholds;
- reprocess calls dedup and price-drop/lifecycle work before valuation;
- injected main or shadow save failure leaves the previous valuation snapshot unchanged;
- main and shadow rows share the intended replacement transaction and carry model/crawl provenance;
- conversion failure is reported and aborts before replacement;
- existing signal quality, source policy, dedup, price history, lifecycle, read-model, cache, and redaction suites remain green.

Before any production reprocess, run an automated local comparison over the current PostgreSQL snapshot and report:

- records whose canonical price, area, or unit price would change;
- counts by repair reason and suppressing flag;
- current actionable signals newly suppressed or restored;
- training-set membership changes;
- main/shadow result counts and large MOS deltas;
- invariant violations remaining after the proposed normalization.

The production gate requires zero remaining price/area/unit-price invariant violations among actionable signals and zero partial-snapshot failures in integration tests. Model parity is diagnostic only; it is not a gate to switch models.

## 9. Rollout and Rollback

Rollout sequence:

1. rebase on current `origin/main` and implement in an isolated `codex/` worktree;
2. run focused tests, the broader extraction/valuation regression suite, and PostgreSQL integration tests;
3. run the non-mutating comparison against the current local production-shaped snapshot;
4. have the implementation agent evaluate the aggregate invariant report for systemic anomalies; no user listing-by-listing approval is required;
5. commit, push, and deploy the application/schema changes;
6. run one controlled full production reprocess because normalization, dedup ordering, and valuation provenance have changed;
7. refresh/compare the signal read model, publish dataset/cache versions, and verify public APIs and rendered signal surfaces.

Rollback is data-preserving:

1. stop further reprocess publication;
2. revert and redeploy the scoped application commits;
3. run the prior deterministic full reprocess to rebuild compatible valuation rows;
4. refresh public read models and cache versions;
5. do not delete raw listings, normalized listing history, user data, or review data.

## 10. Out of Scope

- changing the main valuation algorithm from its current road-tier hierarchical model;
- promoting `median_road_tier` shadow output to production;
- synthesizing child listings from one multi-lot post;
- external LLM extraction or verification in scheduled jobs;
- manual approval queues as a normal operating dependency;
- unrelated UI, crawler-source, publisher-policy, or marketing changes.
