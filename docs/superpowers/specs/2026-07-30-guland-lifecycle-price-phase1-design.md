# Guland Lifecycle and Price Refresh Phase 1 Design

## Goal

Make Guland listings keep their original Radar BDS discovery date across daily
reposts, refresh the current price when the same Guland listing changes price,
feed every real price change into the existing price-history chart, and replace
the current unreliable active/inactive lifecycle with source-aware evidence.

The same release also makes crawl outcomes truthful: database write failures
must not look like duplicates, partial target failures must not look fully
successful, and `crawl-health` plus its PostgreSQL tests must work.

## Product Rules

- `first_seen_at` is the immutable time Radar BDS first observed a listing.
- A daily Guland repost with the same URL/source ID and the same price does not
  change the card date and does not add a price-history point.
- Any confirmed price change, increase or decrease, updates the current price,
  appends one `price_history` row, sets `price_updated_at`, and revalues only the
  affected listing.
- Guland card recency is based on `price_updated_at` when a price has changed;
  otherwise it is based on `first_seen_at`.
- Facebook recency semantics remain unchanged.
- A Guland listing absent from the daily one-day result window is not evidence
  that the source listing is inactive.
- Guland lot identity remains URL/source-ID based. The release must not add
  cross-URL same-lot heuristics.
- Both price increases and decreases appear in the existing history plot.
  Only a valid decrease receives the existing "Chủ hạ" treatment.

## Scope Decomposition

This is one release with two independently testable subprojects:

1. **Guland source reconciliation:** lifecycle observations, same-listing price
   refresh, price-history integration, and source-specific card dates.
2. **Crawl reliability:** explicit insert results, partial-run status, useful
   per-target statistics, a repaired health query, and PostgreSQL test
   isolation.

The release does not add Bến Cát sources, change Facebook deduplication, harden
the image downloader, or broadly reprocess unrelated listings.

## Data Model

The existing fields keep these meanings:

- `first_seen_at`: immutable first observation time.
- `last_seen_at`: most recent time the listing was positively observed on a
  source result/detail page.
- `consecutive_missing`: consecutive explicit source-removal confirmations.
- `delisted_at` and `is_active`: compatibility fields derived from confirmed
  source status, not elapsed time alone.
- `price_history`: append-only distinct price observations for one listing.

Add:

- `price_updated_at TIMESTAMPTZ NULL`: time Radar BDS confirmed the latest real
  price change.
- `source_status TEXT NOT NULL DEFAULT 'unknown'`: one of `unknown`, `active`,
  `inactive`, or `unreachable`.
- `last_source_check_at TIMESTAMPTZ NULL`: most recent direct source-status
  verification attempt, whether successful or not.
- `source_status_reason TEXT NOT NULL DEFAULT ''`: machine-readable reason such
  as `seen_in_results`, `detail_live`, `explicit_removed`, `http_not_found`, or
  `transient_error`.

Schema migration is idempotent and uses PostgreSQL-compatible column types and
constraints. Existing rows are not marked active merely because they are
displayable.

## Guland Reconciliation Flow

### Result-page phase

The crawler continues to extract the configured recent result cards. It loads
the existing Guland rows for the discovered URLs in one query instead of one
query per card.

For each card:

1. **New identity:** fetch detail, validate, insert raw/listing/image data, set
   `first_seen_at`, `last_seen_at`, and `source_status='active'`, and retain the
   initial price-history point.
2. **Existing identity, unchanged valid price:** set `last_seen_at`, clear
   `consecutive_missing`, set `source_status='active'` with
   `source_status_reason='seen_in_results'`, and do not touch card recency,
   raw content, listing price, valuation, or price history.
3. **Existing identity, changed valid price:** place the URL in the detail
   refresh batch. After confirmation, update the current raw snapshot and
   listing, append one distinct `price_history` row, set `price_updated_at`,
   and revalue only the affected listing.
4. **Missing, masked, zero, or unparsable card price:** preserve the last known
   good price and record an observation metric; do not create history.

Price comparison uses a canonical monetary value, not display strings. Values
are normalized to VND and rounded to the nearest million VND so equivalent
formats such as `2,5 tỷ` and `2500 triệu` do not create false changes.

### Price confirmation and quality guards

A changed card price must pass the existing positive/plausible price limits.
The detail page is fetched before the stored price changes. If the detail page
is unavailable, removed, or contradicts the result card, the old price remains
and the run records a refresh error.

A decrease greater than 40 percent follows the existing suspicious-bait rule:
it may be recorded only when the live detail page confirms the same advertised
price, and it remains excluded from normal price-drop promotion. Equivalent
validation applies to implausibly large increases. A transient network error
must never erase a known price.

The refresh updates the existing raw row for the same Guland identity and
preserves `first_seen_at`. It does not create a second `raw_listings` row for
the same URL.

## Price History and Card Presentation

The existing `price_history` table and `/api/history/<listing_id>` response are
the single source for both Facebook and Guland price plots.

- The first stored price remains the first plot point.
- Each later distinct confirmed price creates one plot point at the exact
  `recorded_at` time.
- Repeated observations of the same normalized price create no row.
- Multiple genuine changes in one day remain separate timestamped points.
- `price_first_ty`, `price_dropped`, and `price_drop_pct` continue to be derived
  from trusted history according to current product quality gates.

For Guland only, API sorting, date filters, `days_ago`, the "new" state, and the
visible card time use:

```sql
COALESCE(price_updated_at, first_seen_at, crawled_at)
```

The API also exposes a compact `card_date_reason` value:

- `first_seen`: render "Theo dõi từ …".
- `price_updated`: render "Cập nhật giá …".

Facebook keeps `COALESCE(posted_at, crawled_at)` and its current copy.

## Source Activity Semantics

Seeing a Guland card is positive evidence and immediately sets the listing
active. Not seeing it in the configured one-day result window has no effect.

A bounded verifier checks stale, displayable Guland URLs directly after the
main crawl. It prioritizes `unknown`, oldest `last_source_check_at`, and
currently displayed Map candidates.

- A valid detail page sets `source_status='active'`, refreshes `last_seen_at`,
  clears `consecutive_missing`, and keeps the listing displayable.
- Explicit removed/not-found source evidence increments
  `consecutive_missing`.
- Only two consecutive explicit removal confirmations set
  `source_status='inactive'`, `is_active=0`, and `delisted_at`.
- Timeout, blocking, DNS, browser, or server errors set
  `source_status='unreachable'` without incrementing the removal count.
- Public feed/Map filters exclude confirmed `inactive` rows. `unknown` and
  `unreachable` remain visible until evidence is conclusive.

The verifier has an explicit per-run limit and shares the crawler lock so it
cannot overlap another Guland run.

## Crawl Reliability

Raw insertion returns an explicit result:

- `inserted`
- `duplicate`

Validation failures remain a classified skip. Operational database exceptions
propagate and increment errors; callers may not reinterpret them as duplicates.

Crawl-run status rules:

- `done`: completed with zero operational errors.
- `partial`: at least one target or record failed but the run made progress.
- `error`: fatal setup/browser/database failure prevented a trustworthy run.

Per target URL, persist or log these counters without sensitive payloads:

- cards fetched
- existing identities seen
- new identities inserted
- changed prices confirmed
- unchanged prices
- invalid/masked prices
- explicit removals
- transient errors

`crawl-health` compares PostgreSQL timestamps using real timestamp expressions
and reports partial runs separately. Systemd and cron paths use the same command
status and log-name resolution.

## Migration and Historical Reconciliation

Migration/backfill order:

1. Add the new nullable/defaulted columns and indexes idempotently.
2. Fill missing `first_seen_at` from the earliest trustworthy existing
   `crawled_at`; never replace a non-null first-seen value.
3. Set `price_updated_at` only where `price_history` already contains at least
   two distinct valid prices, using the latest distinct change time.
4. Initialize existing Guland `source_status` to `unknown`.
5. Run a bounded, dry-run-first reconciliation over currently displayable
   Guland rows.
6. On apply, any current price that differs from stored history is recorded at
   the reconciliation time. The release does not fabricate an earlier change
   date.
7. Revalue only IDs whose confirmed current price changed.

The existing 1,722 source-coordinate rows and image assets are not modified by
this migration.

## Security and Abuse Cases

Guland HTML and prices are untrusted external input.

- Source URLs must retain the existing Guland host/identity validation.
- All writes use parameterized queries.
- Prices must pass type, finite-number, positive-value, and plausibility
  validation before storage.
- A source timeout or malformed page cannot clear a prior good value.
- Logs and health output contain counters and IDs, not phone numbers, tokens,
  raw HTML, or database connection strings.
- The bounded verifier prevents a source page or config mistake from causing
  unbounded outbound requests.

## Testing Strategy

Tests are written before production code and must demonstrate the old failure:

- Existing Guland URL with a changed price enters the refresh batch.
- Existing Guland URL with the same normalized price only refreshes lifecycle.
- Increase and decrease both append a distinct price-history point.
- Same-price daily repost adds no history and preserves `first_seen_at`.
- Invalid/masked/transient price input preserves the last good price.
- Greater-than-40-percent decrease follows suspicious-bait quality handling.
- Source absence from the one-day results does not mark a listing inactive.
- Two explicit removals mark inactive; transient errors do not.
- Guland card recency uses price-update time or first-seen time.
- Facebook card recency is unchanged.
- Database write error is not reported as duplicate.
- A run with record/target errors is `partial`; fatal setup is `error`.
- `crawl-health` executes against PostgreSQL and includes partial runs.

Database integration tests use an explicit `RADAR_TEST_DATABASE_URL` whose
database name must contain `test`. They do not load the normal application
`DATABASE_URL` as a fallback. Tests use transaction rollback or unique test
identities and deterministic cleanup.

Focused verification includes Python compilation, JavaScript syntax for changed
card files, price-history/dedup/drop tests, crawler tests, health tests, and API
tests for `/api/signals` and `/api/history/<id>`.

## Rollout and Rollback

Rollout is staged:

1. Deploy additive schema and code with verifier/apply reconciliation disabled.
2. Run migration and reconciliation dry-run; review counts and sampled changes.
3. Enable daily card reconciliation and a conservative verifier limit.
4. Apply the bounded historical reconciliation.
5. Verify crawl status, changed-price rows, history plots, card labels, Map
   visibility, valuation updates, and source-level error rates.

Rollback disables reconciliation/verifier execution and restores prior card
date selection. Additive columns and valid price-history rows remain; rollback
does not destructively remove history or rewrite first-seen dates.

## Acceptance Criteria

- A same-URL Guland price increase or decrease appears in the existing history
  plot after one successful crawl.
- Same-price reposts do not make old Guland cards appear new.
- A confirmed price change moves the card date to the detected change time with
  "Cập nhật giá" copy.
- No known price is cleared by masked content or transient source failure.
- Daily list absence alone never marks a Guland listing inactive.
- Confirmed inactive Guland rows disappear from public feed/Map only after two
  explicit source confirmations.
- Facebook date, dedup, and price-history behavior remains unchanged.
- Crawl health distinguishes done, partial, and error without leaking secrets.
- Focused PostgreSQL and API regression tests pass before release.
