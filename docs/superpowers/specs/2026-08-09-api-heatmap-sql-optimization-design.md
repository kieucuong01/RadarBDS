# `/api/heatmap` SQL Optimization Design

**Date:** 2026-08-09  
**Status:** Design approved; written spec pending review  
**Branch:** `codex/p0-p1-foundation`

## 1. Objective

Reduce the uncached PostgreSQL latency of `/api/heatmap` while preserving the
current request filters, public response shape, signal semantics, ranking, and
tier behavior.

The acceptance target is an uncached local p95 of at most 300 ms for each
representative scope in this document. "Uncached" means the application and
HTTP response caches are disabled; the PostgreSQL/OS buffer cache is not
artificially flushed. The optimization must remain SQL-only: no new schema,
response cache, read model, feature flag, or frontend change is part of this
task.

## 2. Current Behavior

`app.py::api_heatmap()` parses the shared dashboard filters and delegates to
`services.market_data.load_market_opportunities()`. The loader:

1. materializes eligible listings in `filtered_listings`;
2. materializes the latest primary and shadow valuation rows for those ids;
3. joins the three materialized scopes;
4. aggregates listing and actionable-deal metrics by ward; and
5. returns ranked rows plus global summary and applied-filter metadata.

The endpoint returns a small payload, approximately 6 KB for the default local
scope. Serialization and transfer size are not the bottleneck.

## 3. Measured Baseline and Root Cause

Five sequential uncached requests for
`/api/heatmap?date_range=3m&mos_min=15` took 1,096-3,261 ms on the local
PostgreSQL development database.

`EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` measured 1,403 ms of database
execution for a representative default request. The dominant plan repeatedly
scanned the materialized latest-valuation CTEs:

- the primary valuation CTE scan looped about 2,036 times;
- the shadow valuation CTE scan looped about 1,811 times; and
- the repeated nested-loop work dominated the final ward aggregate.

The listing prefilter is effective and must remain. The remaining bottleneck is
how the latest valuation rows are retrieved and joined after that prefilter.

### Read-only candidate measurement

An in-memory SQL candidate replaced the two latest-valuation CTEs with indexed
`LEFT JOIN LATERAL` lookups. No source or database data was changed.

| Representative scope | Current SQL | LATERAL candidate | Speedup | Result parity |
|---|---:|---:|---:|---|
| Default, 3 months | 1,354.5 ms | 64.3 ms | 21.1x | exact |
| One ward, Facebook, 1 month | 16.9 ms | 14.3 ms | 1.2x | exact |
| Property and area/price ranges | 56.1 ms | 29.8 ms | 1.9x | exact |
| Price drops, 1 year | 44,071.6 ms | 257.2 ms | 171.3x | exact |

The candidate used the existing indexes
`idx_valuation_listing_computed` and
`idx_shadow_valuation_listing_computed`. Its measured `EXPLAIN ANALYZE`
execution was 105 ms for the default scope.

Changing the latest-valuation CTEs to `NOT MATERIALIZED` was rejected. It
improved some samples but still produced nested-loop plans and an observed
execution near 3 seconds.

## 4. Proposed Architecture

Keep the route and service boundary unchanged. Modify only the SQL inside
`load_market_opportunities()`.

### 4.1 Listing scope

Retain `filtered_listings AS MATERIALIZED`. It continues to apply the shared
source, ward, property type, price, area, date, keyword, publisher visibility,
and price-drop filters before valuation work.

The CTE must expose only the fields required by the opportunity aggregation:
listing id, ward, price per square metre, listing price, and area.

### 4.2 Latest valuation lookup

Remove `latest_valuation` and `latest_shadow_valuation` as materialized CTEs.
Build `opportunity_rows` from `filtered_listings` and retrieve at most one row
per valuation source:

```sql
FROM filtered_listings l
LEFT JOIN LATERAL (
    SELECT vr.*
    FROM valuation_results vr
    WHERE vr.listing_id = l.id
    ORDER BY vr.computed_at DESC, vr.id DESC
    LIMIT 1
) v ON TRUE
LEFT JOIN LATERAL (
    SELECT vsr.*
    FROM valuation_shadow_results vsr
    WHERE vsr.listing_id = l.id
    ORDER BY vsr.computed_at DESC, vsr.id DESC
    LIMIT 1
) sv ON TRUE
```

The ordering exactly matches the current latest-row rule. The composite
listing/timestamp/id indexes provide bounded index lookups instead of repeated
full scans of materialized CTE results.

### 4.3 Aggregation and response

Do not change:

- `effective_signal_mos_min()` or guest-tier MOS clamping;
- `actionable_signal_sql()` or primary/shadow deal selection;
- outlier exclusion;
- ward aggregation fields and rounding;
- `_market_opportunity_rank()` and rank labels;
- `rows`, `all_rows`, `summary`, `applied_filters`, or `as_of`; or
- the maximum displayed row limit.

Missing valuation rows remain valid because both joins are left joins. The
existing expressions continue to produce non-signal/null fair-value behavior
for those listings.

## 5. Error and Safety Boundaries

- The loader continues to use the bounded `_read_conn()` pool scope.
- No writes, migrations, new indexes, or transaction behavior are introduced.
- Existing database errors continue through the current Flask error handling;
  the optimization must not convert a timeout or query failure into an empty
  successful payload.
- No cache headers or public-cache eligibility change. `/api/heatmap` remains
  outside the anonymous shared-response cache allowlist.
- The response remains aggregate-only and introduces no URL, phone, seller, or
  other private fields.

## 6. Test and Verification Strategy

Implementation must follow TDD.

### RED

Extend the existing market-opportunity query contract test so the current SQL
fails because it materializes and repeatedly joins latest-valuation result
sets. The test must require:

- a materialized `filtered_listings` scope;
- one bounded lateral lookup for each valuation table;
- latest-row ordering by `computed_at DESC, id DESC`;
- `LIMIT 1` for each lookup; and
- no materialized latest-valuation CTE.

The existing route-delegation and payload assertions remain unchanged.

### GREEN

Implement only the SQL rewrite needed to satisfy the new contract. Run the
focused market performance tests and verify all existing response assertions.

### Real PostgreSQL verification

On the local PostgreSQL database, run the same four filter scopes used for the
baseline. For every scope:

1. execute the old and new SQL against one read-only snapshot;
2. compare ordered aggregate rows for exact equality;
3. record at least 20 uncached new-query timings, including the first
   execution; and
4. run `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` for the default and slowest
   representative scopes.

The gate passes only when:

- all payload comparisons are exact;
- every representative scope has local p95 at most 300 ms under the cache
  definition in Section 1;
- plans use the two existing composite indexes for latest-row lookup; and
- no valuation CTE scan is repeated per filtered listing.

### Regression gates

- `py_compile` the touched Python module.
- Run `tests/test_market_data_performance.py` and related market API tests.
- Run `git diff --check`.
- Run the broader Python suite before completion.

## 7. Rollout and Rollback

This task ends with a verified branch change. Merge, push, and production
deployment remain separate user choices.

If deployed later, verify the feature endpoint itself with default and
price-drop scopes. Record application-local and public timings separately;
HTTP 200 alone is insufficient performance evidence.

Rollback is a normal code revert to the previous SQL. No schema, cache, or data
rollback is required.

## 8. Non-goals

- Adding `/api/heatmap` to Redis or Nginx public caching.
- Creating a heatmap or market aggregate read model.
- Changing market opportunity formulas, labels, or frontend presentation.
- Refactoring other market APIs or `app.py` routes.
- Reprocessing listings or valuations.
- Running a new production capacity campaign.
