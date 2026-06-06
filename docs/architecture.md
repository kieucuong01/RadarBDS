# Radar BDS Architecture

This document is for agents that need module boundaries or data-flow context. For quick work, start with `AGENTS.md` and `docs/README.md`.

## Data Flow

```text
Source crawlers
  -> raw_listings
  -> cleansing/normalizer.py
  -> listings
  -> cleansing/legal_image_classifier.py
  -> cleansing/legal_verification.py -> legal_verifications
  -> cleansing/dedup.py
  -> analytics/valuation.py
  -> valuation_results
  -> routes/* blueprints -> app.py API implementations / alerts / CLI reports
```

## Runtime Data

- Canonical relational DB: PostgreSQL via `DATABASE_URL`.
- Remote Supabase project `ozdjzfiqcjnlfuihqqjy` is kept for sync/backup. Local dev normally uses portable PostgreSQL.
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
- `cleansing/`: normalize text, extract features, deduplicate, verify legal image evidence, and prepare listings.
- `cleansing/legal_verification.py`: mark listings with detected so hong/so do images as `has_legal_doc`. OCR/parsing is disabled for now.
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

- `services/market_data.py` is on the hot path for Supabase-backed local dev. Use the shared read connection scope from `db.connection.get_conn()` instead of opening a fresh PostgreSQL connection per read.
- `/api/dashboard` is cached in-process for a short TTL by filter key. Guest dashboard rate limiting is in-memory; write-sensitive scopes such as lead capture still use DB-backed rate limiting.
- `/api/signals` should avoid avoidable remote round-trips. The card feed query uses `COUNT(*) OVER()` and a lateral primary-image subquery so page data, total count, and thumbnail are fetched together.
- Feed ordering depends on legal trust fields, so keep the trust/feed indexes in `db/schema.py` aligned with `_signal_sort_sql()`.

## Signal Filter Runtime Flow

- Main tab filtering should run in two stages:
  - stage 1: request `/api/signals` immediately and update cards,
  - stage 2: request `/api/dashboard` in background for header/meta updates.
- `insights` data is not part of normal signal-filter refresh and should load on Insights tab activation.
- Infinite scroll must dedupe by listing id on client render to avoid race-condition duplicates.

## Legal Trust Layer

- `valuation_results.is_signal` still means "cheap by model"; trust is tracked separately.
- Runtime signal fields are deterministic: parser/normalizer/feature extractor, dedup, legal image verification, and valuation. Crawl/reprocess does not call external LLM verification.
- User/VIP-facing queues use latest actionable valuation from `services.signal_quality`, which excludes duplicate reposts, `source_quality_recheck`, and fatal quality flags while preserving model-cheap rows for admin QC.
- Valuation training is Facebook-primary. Thin canonical Facebook segments (`n < 35`) can be supplemented by strict-pass Guland rows at weight 0.4; this improves sparse segments without letting Guland promote itself directly to user/VIP surfaces.
- Regression valuation caps tier-3 roads at max 80% of the same-listing tier-2 counterfactual, so learned coefficients cannot make tier 3 equal to or higher than tier 2.
- Trust tiers currently used by the feed are `candidate_signal` and `has_legal_doc`.
- `legal_verifications` currently tracks whether a listing has a detected document image. Existing OCR columns remain in schema for old data/admin notes, but runtime OCR code is not shipped or called.
- Hard legal conflict inference from OCR is disabled until OCR is intentionally re-enabled with a fresh module and tests.
- `/api/signals`, `/api/listing/<id>`, investment memo, and VIP push expose or prioritize trust fields without exposing source URL/phone to non-admin users.

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
