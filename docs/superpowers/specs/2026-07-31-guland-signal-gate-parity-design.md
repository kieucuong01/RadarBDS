# Guland Signal Gate Parity Design

**Date:** 2026-07-31  
**Scope:** User-facing `Săn Deal` eligibility and its displayed count

## Goal

Treat Guland and Facebook the same at the source-strength layer. A Guland
listing that is a model signal and passes the shared data-quality rules may
appear in `Săn Deal`; it must not need an additional Guland-only MOS or score
threshold.

The change must also make the `Săn Deal` badge count the exact same eligible
set as `/api/signals`.

## Eligibility Contract

The common eligibility contract is:

1. The latest canonical valuation has `is_signal=1`.
2. The displayed MOS meets the user's current `mos_min`.
3. The listing passes the shared visibility, completeness, source, ward,
   property, price, area, keyword, date, duplicate, and lifecycle filters.
4. No hard data-quality flag is present.

Guland no longer receives an extra source gate. The valuation pipeline must
stop generating `guland_weak_signal` and `guland_user_facing_risk`.

Historical rows carrying either retired flag must not be blocked solely by
those flags or by a stale `source_quality_recheck=1`. A targeted Guland
reprocess after deployment will clear the retired flags and refresh the
stored recheck value.

## Hard Blocking Flags

Keep blocking flags that identify a concrete data or trust problem:

- `too_low_absolute_price`
- `missing_area_evidence`
- `area_dimension_conflict`
- `ambiguous_price_text`
- `source_category_conflict`
- `multi_lot_listing`
- `extreme_guland_ppm2`
- `suspicious_bait`
- `guland_cluster_flood`
- `review_bad_valuation`
- `review_bad_extraction`

`source_quality_recheck` is metadata for the QC workflow, not an independent
user-facing rejection reason. User-facing eligibility is determined from the
explicit blocking flags above.

## Warning-Only Flags

These flags remain visible as warnings but do not suppress a card:

- `low_road_confidence`
- `low_segment_confidence`
- `approximate_price_text`
- other flags not explicitly listed in the hard-blocking contract

## Count Parity

`load_dashboard_summary()` must use the same shared deal SQL contract as
`load_signals()`. The dashboard badge must not count raw MOS candidates that
the card feed suppresses.

The frontend may keep `include_total=0` for the first card request to preserve
the current signals-first performance flow. The background dashboard response
will provide the authoritative filtered count once both backend queries share
the same predicate.

## Data Flow

```text
valuation
  -> shared is_signal + MOS threshold
  -> shared hard quality flags
  -> shared listing filters
  -> /api/signals cards
  -> /api/dashboard stats.signals
```

There is no schema migration and no crawler change.

## Tests

Add regression coverage proving:

1. `guland_weak_signal` and `guland_user_facing_risk` do not suppress an
   otherwise eligible signal.
2. `source_quality_recheck=1` alone does not suppress a signal.
3. Every retained hard flag still suppresses a signal.
4. Guland valuation no longer creates the two retired source-only flags.
5. Dashboard signal count and `/api/signals` total are equal for identical
   Guland source/date/MOS filters.
6. Existing Facebook eligibility remains unchanged.

## Production Rollout

After tests, commit, merge, push, and deploy are separately authorized:

1. Deploy code.
2. Run a targeted full Guland reprocess so stored flags and recheck values
   match the new contract.
3. Clear dashboard/signal caches through the normal service restart or cache
   refresh path.
4. Verify production with the admin filter `source=guland`, `date_range=3m`,
   `mos_min=10`: badge count equals the complete card-feed total.

