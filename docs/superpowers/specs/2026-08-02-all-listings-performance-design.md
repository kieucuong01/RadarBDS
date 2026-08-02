# All-Listings Tab Performance Design

**Date:** 2026-08-02

**Status:** Approved conversationally by the user on 2026-08-02

**Scope:** Homepage `Tin rao` tab, `/api/listings`, its PostgreSQL read path, shared response cache, Nginx guest microcache, parity tooling, rollout, and rollback

## 1. Problem and Evidence

The earlier homepage performance release optimized the `Săn Deal` feed and its supporting counts/dashboard APIs. The `Tin rao` tab remained on an independent legacy route in `app.py::api_listings()`.

Production measurements on 2026-08-02 showed:

| Surface | Result |
|---|---:|
| Public `/api/listings?date_range=3m&sort_by=date&sort_dir=desc&page=1&limit=50` | about 51.8 s |
| VPS-local equivalent request | about 50.2 s |
| Response size | about 96.6 KB |
| PostgreSQL execution for the representative first-page query | about 75.8 s |

`EXPLAIN (ANALYZE, BUFFERS)` proved that network transfer and browser rendering were not the primary bottleneck. PostgreSQL estimated one candidate but produced 11,735. It chose nested-loop joins from those listings into two materialized latest-valuation CTEs, removed about 431 million join pairs, and read about 8.3 million temporary pages.

The route also has the following scaling gaps:

- it rebuilds both latest-valuation datasets on every request;
- it opens and closes a direct connection instead of using the bounded pooled read scope;
- it selects `l.*` before reducing to the requested page;
- it performs a separate exact count and image/drop enrichment after the expensive query;
- it is not covered by the Redis single-flight/stale cache or Nginx guest microcache;
- a burst therefore occupies Gunicorn threads and PostgreSQL connections for tens of seconds.

## 2. Goal and Success Criteria

Make the `Tin rao` tab use the same bounded, versioned architecture as `Săn Deal` without changing its visible filtering, sorting, pagination, modal, or authorization behavior.

Release criteria:

- VPS-local normal cold first-page p95 is at most 500 ms for the default `date_range=3m` query.
- Public guest cache-hit p95 is at most 250 ms.
- The browser replaces the skeleton with the first 50 cards/rows within 1.5 s on the production desktop test connection.
- Default, filtered, sorted, complete-only, price-drop, pagination, and tier parity contain zero unexplained differences.
- Guest/Free/VIP never receive original URLs, seller/contact fields, or embedded phone numbers; admin behavior remains unchanged.
- Identical anonymous requests collapse to one application loader and are eligible for the existing 15-second Nginx microcache.
- A failed refresh or unavailable listing read model leaves the legacy endpoint available; it never serves a partially rebuilt projection.

These measurements are latency gates, not a claim of 5,000 sustained requests per second. The existing controlled capacity-test approval and abort rules remain in force.

## 3. Chosen Design

### 3.1 Broaden the existing public card projection

Continue using the additive `signal_card_read_model` table as the shared public listing-card projection. Do not rename the production table in this release; a rename would add migration and rollback risk without improving latency.

The refresh will include every listing that satisfies the stable public base rules:

- not probably sold;
- not blacklisted;
- not review-hidden;
- source status is not inactive.

It will no longer exclude a row merely because ward, price, area, or listing price/m² is incomplete. Signal behavior remains exact by defining `is_actionable` as the existing actionable valuation predicate **and** the existing signal completeness predicate. `/api/signals` continues to require `is_actionable`, so broadening the stored row set cannot introduce an incomplete signal.

Add one nullable projection field for the original listing `price_per_m2`. The all-listings API currently filters, sorts, and serializes that listing value; it must not silently substitute the signal valuation's `actual_ppm2`.

Preserve the existing `Tin rao` card badge separately as `listing_is_signal`. The legacy route currently requires both the old and shadow valuation actionability predicates for that presentation field, which is not identical to the canonical `is_actionable` subset used by `Săn Deal`. `listing_is_signal` is display compatibility only and must never replace `is_actionable` in `/api/signals`, counts, dashboard, or signals-mode Maps.

The refresh remains transactional: stage a complete replacement, lock only at the final swap, replace rows, and bump durable versions in the same transaction. A failed refresh leaves both the old projection and versions active.

### 3.2 Separate all-listings query semantics from signal semantics

Create a focused all-listings loader rather than adding conditionals throughout `api_listings()` or weakening the canonical signal filter.

The all-listings predicate will reuse the projection fields but will not require `is_actionable` or apply `mos_min`. It will preserve the current behavior for:

- source, ward, property type, area, price, keyword, and date filters;
- hidden duplicates by default and valid repost drops when `only_drops=1`;
- public Guland publisher visibility, with admin-only high-activity override;
- `complete=1`, defined exactly as non-empty ward plus positive price and area;
- sort keys `area`, `price`, `price_m2`, `fair`, `date`, `ward`, and `prop_type`;
- deterministic publisher rank and listing-ID tie breaking;
- clamped page `1..2000` and limit `1..100`.

The page query will read compact candidate rows from the projection, calculate the exact total in the same bounded query, and only then enrich the selected listing IDs with images. The response keeps the existing `imgs` array and current image ordering so no external or modal consumer loses data in this release.

Serialization stays tier-aware and returns the existing response contract:

```text
listings, total, page, limit, pages, has_more, tier
```

The route handler will become parsing/cache orchestration only. Database selection, shaping, and parity logic belong in a focused service.

### 3.3 Independent readiness and versioning

Add `DATASET_LISTINGS = "listings"` to `public_dataset_versions`. Signal read-model publication bumps `signals` and `listings` together because the same atomic projection feeds both endpoints. `market` remains independent.

`/api/listings` uses the new path only when all of these are true:

1. `RADAR_LISTING_READ_MODEL_ENABLED` is not disabled;
2. `RADAR_SIGNAL_READ_MODEL_ENABLED=1` keeps the shared projection active;
3. the durable `listings` dataset version is greater than zero.

The new flag defaults to enabled-with-readiness-gate. On first deployment the absent/zero `listings` version keeps requests on the legacy route. After the expanded full refresh and successful parity check bump the version, the endpoint can switch without a partial-data window. Setting `RADAR_LISTING_READ_MODEL_ENABLED=0` provides a route-specific rollback without disabling the Săn Deal feed.

Durable readiness must be checked independently from the disposable Redis mirror. A short process cache may bound PostgreSQL readiness reads, but a stale-positive Redis key after restore/reset must not enable the projection or select a positive-version response-cache namespace. Configured prewarm has the same fail-closed rule: publication supplies its committed version, while standalone prewarm reads PostgreSQL and skips `/api/listings` on zero or error.

### 3.4 Shared application cache and Nginx guest cache

Wrap `/api/listings` with the existing `get_or_load_public_payload()` contract:

- endpoint namespace: `listings`;
- version tuple: durable `listings` version;
- canonical query: bounded public filters plus complete flag, sort, page, and limit;
- cache tier: separate Guest/Free/VIP/admin namespaces;
- current Redis fresh, stale, lock, waiter, local-LRU, DB-slot, and controlled-503 behavior.

The response is eligible for `X-Radar-Public-Cache: 1` only for an anonymous guest request without session cookie, Authorization, or Set-Cookie. Add an exact Nginx `/api/listings` location using the existing guest-cache include. Cookie/authenticated requests continue to bypass edge storage.

Add the default first-page route to publication prewarm and to `scripts/verify_public_cache.ps1`. Unknown query parameters must not create new application cache keys.

## 4. Alternatives Considered

### 4.1 Separate `listing_card_read_model` table

This produces cleaner names and independent refresh schedules, but duplicates almost all public card data, adds another large refresh and parity surface, and creates two projections that can drift. The existing projection already contains nearly every all-listings card field, so duplication is not justified.

### 4.2 Candidate-first SQL or indexed lateral valuation lookups only

Selecting the page before valuation joins would make the default date sort much faster. It cannot fully solve fair-price sorting, broad filtered counts, cold-key stampedes, or the 1,000-5,000 in-flight burst objective. It remains useful as the legacy rollback improvement only if later measurement shows rollback latency itself must be bounded.

### 4.3 Cache the existing 50-second query

Warm common keys would improve, but a Redis restart, version change, uncommon filter, or lock winner would still execute the catastrophic query. This violates the cold-path and backpressure goals.

## 5. Security and Product Invariants

- Existing source, duplicate, price-drop, completeness, date, and sort semantics are authoritative; performance work cannot redefine them.
- Signal eligibility remains the latest valuation plus `actionable_signal_sql()` and the current signal completeness gate.
- Guest/Free/VIP redaction occurs before any shared payload is cached.
- Admin may retain original listing URL/title content under the current policy, but admin responses remain private and edge-cache bypassed.
- Descriptions remain in the all-listings response because the table view currently displays them; removing or truncating them requires a separately approved API/UI change.
- Full listing details and histories continue to load from their existing detail endpoints.
- No crawler, normalization, deduplication, valuation formula, URL, or SEO behavior changes in this release.

## 6. Verification and Parity Gates

Automated tests must first fail against the current implementation and then cover:

- expanded refresh includes incomplete public rows while `is_actionable` still requires signal completeness;
- all-listings query contains no request-time valuation CTE and uses the bounded pooled connection;
- exact filter/sort/complete/drop/pagination behavior and stable tie breaking;
- legacy versus read-model response parity for representative fixture cases;
- Guest/Free/VIP/admin redaction and cache namespace separation;
- canonical cache keys, unknown-parameter stability, dataset version invalidation, Redis failure, busy response, and Nginx bypass rules;
- frontend first-page request remains one paginated request and renders table/grid without duplicate infinite-scroll rows.

Production release gate:

1. Deploy code while `listings` version is absent or zero; verify legacy behavior still works.
2. Run the expanded full refresh and confirm transaction success.
3. Run deterministic parity across default plus representative filters, sorts, tiers, and pages; require zero unexplained differences.
4. Confirm the durable `listings` version and Redis mirror advance together.
5. Verify VPS-local cold/warm timings before public exposure.
6. Verify public cache MISS/HIT, cookie/auth bypass, exact totals, desktop/mobile rendering, modal opening, and browser errors.
7. Record production commit, service state, latency, version, and rollback evidence in `docs/operations.md`.

## 7. Rollback

Rollback is data-preserving:

1. disable Nginx caching for `/api/listings` if any privacy or cache-key concern appears;
2. set `RADAR_LISTING_READ_MODEL_ENABLED=0` and restart `radar-bds.service` to route only this endpoint back to legacy SQL;
3. keep the expanded projection and `listings` version for diagnosis;
4. revert source only if the projection refresh or shared signal path itself is defective.

Disabling the all-listings read path must not disable `/api/signals`, `/api/counts`, `/api/dashboard`, or signals-mode Maps.
