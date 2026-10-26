# Proprietary asking-price SEO — registered ward slices

## Authority and boundary

Owner authority: active portfolio profile `projects/rb-data-seo/CONTRACT.md`.
The foundation added `/gia-dat/phu-loi` plus its named parent
`/gia-dat/thu-dau-mot`; registry v2 adds `/gia-dat/hiep-thanh`,
`/gia-dat/phu-my` and `/gia-dat/tan-an`. Registry v3 adds `/gia-dat/phu-hoa`,
`/gia-dat/dinh-hoa` and `/gia-dat/phu-tan`: seven candidate wards plus one
named parent, not 20 ward pages or 12 buyer intents. Each still requires
>=15 valid monthly samples. The existing
indexed directory/article owners are unchanged. Parent pages do not count as
an additional candidate ward. Listing SEO and the closed-month warehouse
report remain separate unimplemented batches.

## Deterministic daily engine

After the crawl, the existing data-SEO owner runs as `radar`, with the existing
protected runtime environment already loaded:

```bash
cd /opt/radar-bds/current
/opt/radar-bds/.venv/bin/python scripts/refresh_data_price_seo.py
```

No new scheduler, model or service is required. It performs a bounded
repeatable-read READ ONLY query, verifies the transaction state, then rolls
back. It never initializes schema, updates listings/valuation, refreshes core
read models or publishes social content. `--output-dir` supports isolated QA.
A failed query cannot replace the previous latest pointer. Concurrent refresh
is rejected by a nonblocking filesystem lock.

Runtime root: `reports/data-seo/` (ignored by Git, not a web route).
- `<date>-<content-id>.json`: immutable, mode 0600, aggregate facts only.
- `latest.json`: atomic replaceable pointer, binds packet filename and SHA256.
- `private/<same-id>.json`: mode 0600 under mode 0700 directory; canonical
  cohort listing IDs, normalized eligible price/area/observation inputs and their
  hash, generation time and source commit; never returned by any public endpoint.
  Unneeded seller/contact/title fields are excluded even from this provenance.

Snapshot `source_commit` is the exact checkout SHA used to generate it.
New packets explicitly declare `scope_registry_version=3`. Frozen v1 packets
(without that member) retain exactly their original two-scope registry; frozen
v2 retains its original five scopes. Both retain their bytes, hashes and fact
bindings. Unknown versions and missing/extra scopes fail closed.
The daily engine can read v1/v2 history while generating v3; a new route returns
503/noindex until a packet containing that registered scope exists. No old
packet is rewritten or expanded with invented history. The parent and ward
pages link only to eligible scopes present in the validated packet.
The SHA256 is over canonical UTF-8 JSON excluding the `sha256` member, not a
hash of pretty-printed JSON. The snapshot ID is a separate content-derived
identifier. Receipts must retain both exact values.

## Population and temporal limits

Only land for sale, Facebook/Guland, whitelisted normalized wards. Drop
current known duplicates/possible duplicates, hidden/blacklisted, outlier/bait,
inactive source, probably-sold, fatal extraction/latest-valuation flags,
nonfinite/nonpositive/inconsistent price-area records. No cross-source lot
heuristics are introduced. Price consistency tolerance is 1% with 0.001
million VND/m² rounding allowance, disclosed in the machine contract.

One qualifying listing ID counts once after CURRENT known-duplicate exclusions;
this is not a promise of physically unique lots across sources. A last-seen
observation must be in the current Vietnam month and not in the future. No
fallback from missing last-seen to ingestion/post dates. Current known prices
on these records form a **snapshot of MTD-observed listings**, not a full panel
of every price observed during the month or an entire market census.

`price_ty` is billion VND; `price_per_m2` is million VND/m². Each mean, median,
minimum and maximum has its own n, unit, scope, source basis, window,
contract version and canonical display. Below 15 samples suppress all local
prices and histogram; an eligible named parent is linked, never relabeled as
local. Active count is independently computed as `is_active=1` within that
qualified monthly cohort; it is not the number of public cards or sales.

Six-month history uses ONLY frozen real snapshots, with the actual endpoint
for every point. Missing/insufficient history stays null, not zero. Same-day
MTD comparison requires both n>=15 and the exact same elapsed day in the prior
month. `price_history` events are intentionally not read as an observation
panel. Historical monthly coverage will accumulate from this first snapshot;
this release does not claim to reconstruct the five absent past months.

## Public rendering and privacy

SSR reads the shared packet, no request-time warehouse statistics query.
Snapshot failures return 503/noindex; only validated eligible pages enter the
existing sitemap, lastmod is the real data date. Pages deliberately remain
private/no-store and do not opt into guest HTML CDN caching.

Fresh cards call the existing `load_signals` dispatcher with guest tier,
Facebook-only source, registered wards, land type, 1-month window, MOS sort,
limit=5 and include_total=False. A second allowlist discards non-Facebook
records and projects ONLY public listing ID, ward, area and asking price.
No internal Guland ID, title, image, description, phone or raw URL is output.
The compact shared feed does not expose transaction type and may mix rentals.
A bounded primary-key lookup of at most five candidates requires current
`tx_type='ban'`, land type and Facebook source before rendering. Missing or
rental types are discarded; the page may honestly show fewer than five cards.
A cards error is labeled unavailable, not an empty-market assertion.

## Cross-channel fact handoff (read-side contract)

This section extends the actual handoff contract in
`docs/social/news-workflow.md`. Before a new group/video draft uses these
price facts, it MUST include:

```json
{"price_fact_binding":{"snapshot_id":"exact packet id","snapshot_sha256":"exact 64-hex hash","facts":["complete, unmodified fact objects selected from the packet"]}}
```

The `facts` member is an array of actual objects, not the explanatory string
shown above. Load the bound frozen file, not a newly queried DB/latest pointer,
assert the exact snapshot ID, and call:

```python
from services.data_price_seo import validate_claims
assert snapshot['snapshot_id'] == binding['snapshot_id']
validate_claims(snapshot, binding['snapshot_sha256'], binding['facts'])
```

The helper rejects mismatched hashes and changed numbers, units, n, periods,
displays, source basis, fact IDs or contract version; suppressed prices cannot
be bound. Copy uses the stored display, unit, n and period. A later live card
is NOT a frozen monthly fact. Fact validation never replaces source/rights,
review stamps, image QA, approval, dedupe, platform or live-post verification.
No group/video/post was published by this engine. Existing queue adapters are
not yet wired to enforce the new binding automatically; do not describe this
read-side contract as end-to-end social publishing enforcement.

## Gates and release/rollback

Run new tests plus `test_public_seo`, `test_public_cache_headers`,
`test_listing_feed`, `test_source_policy` and `test_signal_read_model` against
an isolated TEST database, never the production URL. Verify real read-only
cohort/provenance, SSR DOM and narrow mobile/desktop screenshots. Full Quality
gates CI on the exact pushed SHA must pass before production activation.

Commit explicit source paths from the isolated radar worktree. Recheck live
HEAD, remote and dirty-file fingerprints, no active crawler/reprocess; scoped
source backup, non-force push, source fast-forward only, restart only
`radar-bds.service`. Preserve unrelated dirty files exactly. Re-run the engine
on the deployed SHA, verify canonical/robots/sitemap/rendered packet hash and
public-card source/privacy. Rollback only this release's explicit source paths
from the scoped backup/verified previous commit; never reset the dirty tree.
Leave immutable packets intact, restore only a prior latest pointer if needed.

Before extending to further scopes: extend tests and registry deliberately;
retain the 20 manifest candidates and 12 intent copy/filter specs. Historical
packets are frozen. Future registry/contract migrations must not silently
invalidate or rewrite old snapshots. Retaining eligible closed-month facts
when a mature ward has insufficient new-month samples is a required follow-up
before the first month rollover; it is not yet implemented in this first MTD
slice. Google Inspection receipts belong in the owner manifest; HTTP/sitemap
success is not index proof.
