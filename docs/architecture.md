# Radar BDS Architecture

This document is for agents that need module boundaries or data-flow context. For quick work, start with `AGENTS.md` and `docs/README.md`.

## Data Flow

```text
Source crawlers
  -> raw_listings
  -> cleansing/normalizer.py
  -> listings
  -> cleansing/dedup.py
  -> analytics/valuation.py
  -> valuation_results
  -> services/public_data_publish.py
  -> signal_card_read_model + public_dataset_versions
  -> routes/* blueprints -> app.py API implementations / alerts / CLI reports
```

## Runtime Data

- Canonical relational DB: PostgreSQL via `DATABASE_URL`.
- Local dev normally uses installed PostgreSQL 18 service `postgresql-x64-18` on `127.0.0.1:5432`, database `radar_bds`, managed with pgAdmin4.
- Remote Supabase project `ozdjzfiqcjnlfuihqqjy` is kept for sync/backup.
- Portable PostgreSQL 17 in `tools/postgresql-17.10/` is legacy/fallback for isolated restore or recovery only.
- Legacy SQLite DB: `data/radar_bds.db` is read only by `scripts/migrate_sqlite_to_postgres.py`.
- Local images: `data/images/`.
- Card thumbnails: `data/images/thumbs/*.webp`.
- Runtime data is ignored by git and should not be committed.

PostgreSQL migration status:

- On 2026-05-25, the local SQLite dataset was migrated to Supabase Postgres.
- `raw_listings` and `listings` each migrated 6,991 rows.
- Orphan child rows that violated PostgreSQL foreign keys were skipped during migration: 18 `listing_images`, 18 `price_history`, and 13 `user_audit_log` rows.
- Direct Supabase connection works locally; use Session Pooler only if direct networking fails.

## Main Boundaries

- `crawler/`: fetch source data and store raw rows. Avoid valuation or dashboard logic here.
- `cleansing/`: normalize text, extract features, deduplicate, and prepare listings.
- `analytics/`: valuation and market signal logic. No crawler calls.
- `db/`: schema, connection, migrations, and write-side repository helpers.
- `services/`: read models for API/dashboard; keep expensive shaping here, not in routes.
- `routes/`: public/auth/market/admin Flask blueprints. The current handlers delegate to `app.py` implementations; move logic into services before making route handlers fatter.
- `auth/`: sessions, tier checks, VIP expiry, audit, and rate limiting.
- `alerts/`: Telegram/email formatting and send helpers.
- `cli/notify.py`: VIP watchlist push orchestration after crawls.
- `static/js/main/`, `static/css/main/`, and `templates/`: dashboard UI split by feature/domain.
- `cli/`: command orchestration.

## Dashboard API Shape

- `/api/dashboard`: lightweight summary. No full signal list, no descriptions, no image arrays.
- `/api/signals`: paginated card summaries. It accepts the dashboard filters plus `page`, `limit`, `sort`.
- `/api/listing/<id>`: full detail payload for modal, including description and original images.
- `/api/history/<id>`: price history, lot history, and comparable data for modal.
- `/api/listings`: paginated table data for the all-listings tab.
- `/api/watchlists`: user saved filters for VIP Telegram push.
- `/api/auth/telegram/*`: bot linking via webhook or local sync fallback.
- `/api/market-indicators`: VIP-only deep analysis.

Security boundary:

- Non-admin payloads must not expose original listing URL, source URL, or phone.
- Guest can see listing content in the deal feed and detail pages; only original URL/phone stay redacted for non-admin users.

Performance boundary:

- `services/market_data.py` is on the hot path for PostgreSQL-backed local dev. Use the bounded `db.connection.get_conn()` pool scope instead of opening a fresh PostgreSQL connection per read. Each process defaults to pool min/max `1/4` with a one-second acquire timeout; three Gunicorn workers therefore admit at most 12 application DB connections.
- `/api/signals`, `/api/counts`, and `/api/dashboard` use `services/public_cache.py` when `RADAR_PUBLIC_CACHE_ENABLED=1`; production enabled it after the Phase 4 integration, privacy, failure, and rollback gates. The old per-process route dictionaries no longer exist. Guest/Free/VIP keys are separate; admin and explicit local/admin `cache_refresh=1` requests bypass response caching.
- `/api/signals` keeps `load_signals()` as its stable interface. With `RADAR_SIGNAL_READ_MODEL_ENABLED=0` it uses `_load_signals_legacy()`; with the flag enabled it reads `signal_card_read_model` through one bounded page query and joins the preselected image by primary key.
- With the same flag enabled, `load_dashboard_summary()` obtains `stats.signals` through `count_signals_from_read_model()` on its existing pooled connection. The count reuses the exact ward/source/property/range/keyword/date/publisher/tier filters from the public feed and never rebuilds latest valuation CTEs at request time. Flag `0` keeps the legacy CTE branch for immediate rollback only.
- The read-model query applies a transaction-local `statement_timeout`, clamps `limit` to 100, uses `limit + 1` when `include_total=0`, and reuses the existing formatter plus tier redaction. It must not fork API serialization or masking rules.
- Legacy feed publisher policy is set-based through one `listing_publishers`/`source_publishers` join. Do not restore correlated publisher subqueries.
- Feed ordering should not depend on retired legal-image verification paths.

### Shared public response cache

- PostgreSQL `public_dataset_versions` is the source of truth. Redis keys `radar:dataset-version:signals` and `radar:dataset-version:market` are disposable mirrors; publication updates them only after the DB transaction exits successfully.
- Response keys are `radar:public:v<schema>:<endpoint>:<tier>:<version-tuple>:<sha256(canonical-json-query)>`. Canonical queries contain only parsed response-changing fields. Multi-value filters are sorted/deduplicated; page is clamped to `1..2000`, limit to `1..100`, wards/sources/property types to `64/4/8`, range groups to `12` each, and keyword to 80 characters before both the key and SQL loader.
- Each key has `<key>:fresh` for 60 seconds, `<key>:stale` for the configured stale window, and `<key>:lock` for five seconds. The production stale window is 86,400 seconds so expensive dashboard data survives idle periods and can be served during dependency failure; the code default remains 180 seconds for environments that do not override it. A token-owned Lua compare/delete releases the lock. Waiters spend at most 250 ms looking for the winning fresh result.
- Redis failure falls back to a process-local 256-entry LRU. A process-wide bounded semaphore admits at most two uncached DB loaders; excess work receives controlled `503 Retry-After: 1`. A bounded stale value may be served when a loader or dependency fails.
- Anonymous guest homepage/API responses may carry `X-Radar-Public-Cache: 1` and a 15-second shared-cache policy. Any `radar_session`, `Authorization`, admin response, `Set-Cookie`, non-2xx result, or controlled error remains private/no-store and must never enter an edge cache.
- Guest cache values are produced only after tier redaction. Original listing/source URLs, seller names, contact phones, and embedded phone numbers may not enter the guest namespace.
- `services/public_prewarm.py` reads at most 20 allowlisted relative routes, never sends Cookie/Authorization, caps response reads at 2 MiB, and reports status only. `services/public_data_publish.py` mirrors committed versions first, then prewarms only while the shared-cache flag is enabled; Redis/HTTP failures never relabel committed DB data as failed.

### Production concurrency topology

```text
anonymous GET /, /api/signals, /api/counts, /api/dashboard
  -> Nginx exact-location guest cache (15 s, lock + background update, stale-on-error)
  -> Gunicorn 3 workers x 4 threads, timeout 45 s, max 12 concurrent app requests
  -> Redis public response cache (loopback, 256 MB, allkeys-lru, no persistence)
  -> bounded PostgreSQL pool (max 4/worker, max 12 web sessions)
```

Cookie, Authorization, `Set-Cookie`, non-2xx, admin, and non-allowlisted routes bypass or are rejected from the edge cache. Nginx hides the application's internal `X-Radar-Public-Cache` marker and exposes `X-Radar-Edge-Cache` for operations. The proxy cache keeps inactive keys for 24 hours, serves stale entries while updating or on upstream error/timeout, and accepts IPv4 TLS connections with backlog 8,192. Global Nginx capacity is 4,096 worker connections per worker; kernel accept and SYN backlogs are 8,192.

This topology collapses repeated/common public keys; it does not turn one 2-vCPU origin into a safe 5,000-unique-cold-query service or high-availability deployment. The 2026-08-01 production test passed the browser-compressed normal homepage at 100 VUs and a prewarmed 50-key mixed-filter corpus at 500 VUs. External 500 normal and 1,000 mixed stages missed their latency/error gates while Redis, PostgreSQL, CPU, memory, and accept queues remained bounded. A CDN/origin shield plus distributed load generation is required before claiming the 1,000-5,000 target. See `docs/operations.md` for the exact evidence and rollback.

The follow-up distributed run `30698414443` removed the single Windows generator but failed closed at its first default-100 stage: every response/check was valid, while p95/p99 reached 2.24/3.10 seconds and the origin remained far below abort thresholds. External transfer plateaus at roughly 1.2-2.2 MB/s versus about 8 MB/s from a same-host diagnostic, so the remaining scaling boundary is the direct public network path. Cloudflare is designed as the next edge in `docs/superpowers/specs/2026-08-01-cloudflare-origin-shield-design.md`, but is not active yet. Until it is, the active topology begins at Nginx exactly as shown above.

### Signal-card read model publication

- `signal_card_read_model` stores deterministic card/filter fields, the selected primary image id, public publisher visibility/rank, and the latest actionable valuation projection.
- `public_dataset_versions` has durable `signals` and `market` rows. `signals` increments only after the final read-model insert in the same transaction.
- Full refresh builds a temporary stage, locks only for delete/insert publication, then bumps the version. If any step raises, PostgreSQL rollback preserves the previous complete version.
- Incremental refresh deletes/rebuilds only processed listing ids plus their current duplicate parents. More than 500 ids switches to full refresh; full/large publication runs `ANALYZE` on the fixed public-read table allowlist.
- Creating the read-model/version tables is required. Autovacuum/analyze reloptions on pre-existing hot tables are optional during runtime migration because the app DB role may not own those tables; inspect `pg_class.reloptions` and apply missing tuning with the PostgreSQL owner instead of failing deploy.
- In the limited-owner migration path, commit `public_dataset_versions`, `signal_card_read_model`, and `listing_map_locations` before attempting best-effort legacy migrations. Any later `insufficient_privilege` error aborts the active PostgreSQL transaction; the handler must roll that optional transaction back so required tables are never silently lost.
- The read model retains normalized `activity_at` but `newest` ordering deliberately reuses `listing_activity_at_sql()` over the preserved text columns. Production Guland rows contain both `YYYY-MM-DD HH...` and `YYYY-MM-DDTHH...`; replacing the legacy lexical key with `TIMESTAMPTZ` changes feed order and fails the parity gate. Treat a chronological-order migration as a separate product change, not a performance refactor.
- `cleansing/reprocess.py` publishes after valuation, lifecycle, trends, dedup, map work, and content hashes. Targeted reprocess publishes only touched ids. Guland publisher override refreshes linked listings inside the override transaction.
- Phases 1-4 are deployed: read-model SQL, bounded pool/shared cache, signal-first browser flow, and reversible Redis/Nginx/Gunicorn capacity configuration. Distributed load tooling and CDN-required evidence gates are implemented. The 1,000-5,000 acceptance gate remains open until an authenticated CDN cutover passes every serial stage.

## Signal Filter Runtime Flow

- `static/js/main/filter_runtime.js` owns browser-side canonicalization. It sorts query keys, trims values, removes the retired `sigv`, and sorts/deduplicates order-insensitive ward/source/property/range values. Range values use numeric lower/upper-bound ordering so the browser string matches the parsed server cache-key tuple.
- On the Signals tab, `applyFilters()` snapshots the canonical query, resets pagination, and starts exactly one immediate `/api/signals?page=1&include_total=0...` request. Only after that promise settles, and only if the snapshot is still current, it schedules `/api/counts` through `requestIdleCallback` (100 ms timer fallback).
- `/api/counts` owns the filtered total shown in desktop/mobile Săn Deal badges through `stats.signals`. The feed deliberately omits `total`; adding its `COUNT(*) OVER()` back would regress first-card latency.
- `/api/dashboard` is not part of Signals-tab filtering. Non-Signals tabs may refresh counts and dashboard metadata immediately; Market/Insights/All keep their existing lazy loaders.
- Rapid changes retain three layers of stale-work protection: `fetchJSONCached()` aborts the prior scope controller; `signalRunSeq` prevents an older response from rendering; `signalRenderSeq` cancels old animation-frame chunks. `renderedSignalIds` resets on page 1 and deduplicates appended pages.
- `insights` data is not part of normal signal-filter refresh and should load on Insights tab activation.
- Infinite scroll must dedupe by listing id on client render to avoid race-condition duplicates.

### Homepage listing Maps read path

- `mode=signals` summary and item requests reuse `signal_card_read_model` and the canonical read-model filter predicate, then join `listing_map_locations`. Their cache version is `public_dataset_versions.signals`; they must not scan valuation history or compute the legacy publisher policy at click time.
- `mode=all` remains on the legacy listing/valuation path because it is not an actionable-signal feed. The shared `RADAR_SIGNAL_READ_MODEL_ENABLED` flag preserves the data-safe fallback for both the card feed and signals-mode Maps.
- Signals-mode map items reuse `signal_card_read_model.primary_image_id` instead of a per-listing lateral image lookup. The summary stays grouped and contains no descriptions, phone numbers, source URLs, seller identity, or image arrays. Guest/Free/VIP item titles pass through the same embedded-phone redaction as normal cards; only admin retains the original title.
- Leaflet uses its Canvas renderer for the large grouped marker set. The directory remains accessible and both desktop/mobile panels consume the same compact summary payload.

### Browser performance telemetry

- `static/js/main/web_vitals.js` observes native LCP, layout shifts without recent input, and the largest interaction event at the 40 ms threshold. It sends each available metric once on page-hidden through GA4 event `web_vital` with only `metric_name`, rounded `metric_value`, `metric_rating`, and `non_interaction`.
- Approved good/poor boundaries are LCP `2500/4000 ms`, INP `200/500 ms`, and CLS `0.1/0.25`. The helper must not include URLs, filters, listing/user identifiers, cookies, or free-form text.
- Every reset signal load marks `radar-signals-request-start`; the first inserted chunk marks `radar-first-signal-cards-rendered` and measures `radar-first-signal-cards`. This measures request plus JSON/render time to useful cards, not image completion.
- `filter_runtime.js` plus `web_vitals.js` has a 5 KiB uncompressed budget. Both are loaded below visible HTML and before `boot.js`; neither may add a network dependency.

## Trust Layer

- `valuation_results.is_signal` still means "cheap by model"; trust is tracked separately.
- Runtime signal fields are deterministic: parser/normalizer/feature extractor, dedup, and valuation. Crawl/reprocess does not call external LLM verification.
- User/VIP-facing queues use latest actionable valuation from `services.signal_quality`, which excludes duplicate reposts and explicit hard quality flags while preserving model-cheap rows for admin QC. `source_quality_recheck` is QC metadata and does not independently suppress a signal.
- Valuation training is Facebook-primary. Thin canonical Facebook segments (`n < 35`) can be supplemented by strict-pass Guland rows at weight 0.4. Presentation is independent of that training policy: Guland and Facebook use the same model-signal/MOS threshold, then the same explicit hard quality blockers.
- Regression valuation caps tier-3 roads at max 80% of the same-listing tier-2 counterfactual, so learned coefficients cannot make tier 3 equal to or higher than tier 2.
- Trust tiers should now be treated as listing/valuation metadata, not as a live legal-image verification product path.
- `/api/signals`, `/api/listing/<id>`, investment memo, and VIP push must keep source URL/phone redacted for non-admin users.

## Dedup and Price Drop Policy

Full product rules live in `docs/product_rules.md`.

- Same URL/source_id is the same listing and should use `price_history` for same-listing price changes.
- Guland and legacy BatDongSan cross-URL heuristics are disabled for duplicate/lot identity. Use source-id only.
- Facebook repost heuristics are allowed because broker reposts are meaningful, but only with strict guards.
- Same-price Facebook reposts may support lot history. Same-price Guland/legacy BatDongSan reposts must not.
- `price_dropped=1` means a reliable drop. Drops over 40% should be `suspicious_bait=1`.

## Image Policy

- Cards use thumbnails via `services/image_assets.resolve_image_url(..., prefer_thumb=True)`.
- Detail/modal uses original images via `prefer_thumb=False`.
- `cleansing/download_images.py` creates thumbnails after new downloads.
- `scripts/generate_thumbnails.py` backfills thumbnails for existing images.

## Refactor Guidance

- Do not move files only for aesthetics.
- Move SQL out of `app.py` into `services/` when touching dashboard read behavior.
- Keep `config/database_sqlite.py` and `db/sqlite.py` as compatibility facades only; runtime connections are PostgreSQL.
- Use `schema_migrations` / `db/schema.py` for schema changes instead of SQLite-style ad hoc migrations.
- For RBAC or Telegram push work, prefer `docs/rbac.md` and `docs/telegram_watchlist.md` over broad codebase reads.
