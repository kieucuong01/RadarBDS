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

- `services/market_data.py` is on the hot path for PostgreSQL-backed local dev. Use the shared read connection scope from `db.connection.get_conn()` instead of opening a fresh PostgreSQL connection per read.
- `/api/dashboard` is cached in-process for a short TTL by filter key. Guest dashboard rate limiting is in-memory; write-sensitive scopes such as lead capture still use DB-backed rate limiting.
- `/api/signals` keeps `load_signals()` as its stable interface. With `RADAR_SIGNAL_READ_MODEL_ENABLED=0` it uses `_load_signals_legacy()`; with the flag enabled it reads `signal_card_read_model` through one bounded page query and joins the preselected image by primary key.
- The read-model query applies a transaction-local `statement_timeout`, clamps `limit` to 100, uses `limit + 1` when `include_total=0`, and reuses the existing formatter plus tier redaction. It must not fork API serialization or masking rules.
- Legacy feed publisher policy is set-based through one `listing_publishers`/`source_publishers` join. Do not restore correlated publisher subqueries.
- Feed ordering should not depend on retired legal-image verification paths.

### Signal-card read model publication

- `signal_card_read_model` stores deterministic card/filter fields, the selected primary image id, public publisher visibility/rank, and the latest actionable valuation projection.
- `public_dataset_versions` has durable `signals` and `market` rows. `signals` increments only after the final read-model insert in the same transaction.
- Full refresh builds a temporary stage, locks only for delete/insert publication, then bumps the version. If any step raises, PostgreSQL rollback preserves the previous complete version.
- Incremental refresh deletes/rebuilds only processed listing ids plus their current duplicate parents. More than 500 ids switches to full refresh; full/large publication runs `ANALYZE` on the fixed public-read table allowlist.
- `cleansing/reprocess.py` publishes after valuation, lifecycle, trends, dedup, map work, and content hashes. Targeted reprocess publishes only touched ids. Guland publisher override refreshes linked listings inside the override transaction.
- Phase 1 improves origin SQL and gives safe rollback. Redis, bounded connection pooling, Nginx microcache, browser request fan-out reduction, and the 1,000-5,000 in-flight load gate belong to later phases in the master plan.

## Signal Filter Runtime Flow

- Main tab filtering should run in two stages:
  - stage 1: request `/api/signals` immediately and update cards,
  - stage 2: request `/api/dashboard` in background for header/meta updates.
- `insights` data is not part of normal signal-filter refresh and should load on Insights tab activation.
- Infinite scroll must dedupe by listing id on client render to avoid race-condition duplicates.

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
