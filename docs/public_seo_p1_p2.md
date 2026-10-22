# Public SEO and tools: P1/P2 behavior

## Public data and valuation

- Live ward landing pages use the same Facebook / one-month scope as their dashboard handoff. Sources and dates are included in both cache keys and loaders.
- Valuation comparison cards follow source permissions before the candidate limit. Guland remains in the valuation training dataset and remains inspectable by admin.
- Training reads the latest quality row using the existing `(listing_id, computed_at, id)` index and a lateral `LIMIT 1`. Keep the same computed-at/id ordering: rows without a valuation must remain available. This is a read-query optimization, not a valuation-model migration; no reprocess is required.
- The valuation results CTA opens signals in the same ward/type, with area ±25%, Facebook, one month and an optional maximum equal to the entered asking price. The UI explains these bounds; an asking price is not silently presented as a confirmed transaction or valuation.

## News discovery

`/tin-tuc/du-lieu-radarbds` has its own title and description. The latest updated article is featured on the first unfiltered page. Other cards are served in pages of 12.

- `q` searches the complete archive before slicing; Vietnamese accent-insensitive matching is supported.
- `category` keeps the selected topic when searching; switching category resets page 1 and retains the query.
- Pagination uses ordinary GET links and works without JavaScript. Each page has a normalized self-canonical and prev/next discovery.
- Search/category combinations are `noindex,follow`; do not add them to the sitemap. Unfiltered numbered pages remain indexable. Invalid/out-of-range page numbers return 404.
- Keep source/event/editorial dates. Do not change an article's date just to make it appear fresh, or merge articles based only on a title-length warning. Original figures/illustrations require source evidence; use GSC query data before claiming cannibalization.

## Leads and measurement

- Tool forms keep their page path, source context and current request context. Street/ward/area/asking-price details belong in the private lead note, not the analytics payload.
- `/chinh-sach-bao-mat` explains the data currently handled, browser storage, analytics, external links and manual support requests. It is linked from the shared footer and forms. There is no automatic deletion/subscription-management feature to imply in copy.
- `seo_landing_viewed`, `cta_clicked` and `lead_capture_submit` retain their existing first-party contracts. Tools now also emit `tool_used` with only `tool=valuation|land_price` and `step=start|success|empty|error` plus sanitized page/acquisition fields.
- `/admin/tang-truong` shows tool steps alongside page views, dashboard handoffs and lead rows/events. Counts are events, not unique people or a joined user conversion funnel. Zero historical tool events before release is not evidence that nobody used the tools.
- Reconcile GSC finalized query/page data with these events before selecting further article refreshes. Missing GSC/GA4 access means unavailable metrics, not zero traffic. Do not expand publication volume from unverified conversion assumptions.

## Verification and operations

Run focused Python tests for news archive, public SEO/trust/cache headers, valuation tool/service/UI, land-price tool, marketing audit/tracking/admin aggregation; run the JavaScript suite. The deterministic marketing gate must have no hard failures:

```powershell
& $py -X utf8 scripts/audit_marketing_pages.py --strict
node --test tests/js/*.cjs tests/js/test_*.js
```

The audit allows CR/LF only in `social_editorial.caption`; title/path/URL controls and other unsafe caption controls remain errors. Metadata and introductory-paragraph length findings remain editorial warnings.

For performance, separate DNS/connect/TLS, time-to-first-byte and total HTTP time. Public HTML supplies `Server-Timing: app;dur=...`; that is origin generation time and may be the historical generation value on an edge cache hit. Read it together with cache headers, not as a live cache-hit processing duration or Core Web Vitals metric. No public-cache allowlist was expanded.

After a release, verify guest links, scoped ward counts/CTA, valuation output/comparison permissions, news pages 1/2/search, mobile land-price pagination and the privacy page. Inspect the exact commit's Ubuntu Quality gates before deploying. Roll back application code through the documented guarded deploy process; no database migration is introduced here.
