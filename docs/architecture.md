# Radar BDS Architecture

This document is for agents that need module boundaries or data-flow context. For quick work, start with `AGENTS.md`.

## Data Flow

```text
Source crawlers
  -> raw_listings
  -> cleansing/normalizer.py
  -> listings
  -> cleansing/dedup.py
  -> analytics/valuation.py
  -> valuation_results
  -> app.py APIs / alerts / CLI reports
```

## Runtime Data

- Canonical SQLite DB: `data/radar_bds.db`.
- Override: `RADAR_DB_PATH`; relative paths resolve from repo root.
- Local images: `data/images/`.
- Card thumbnails: `data/images/thumbs/*.webp`.
- Runtime data is ignored by git and should not be committed.

## Main Boundaries

- `crawler/`: fetch source data and store raw rows. Avoid valuation or dashboard logic here.
- `cleansing/`: normalize text, extract features, deduplicate, enrich, and prepare listings.
- `analytics/`: valuation and market signal logic. No crawler calls.
- `db/`: schema, connection, migrations, and write-side repository helpers.
- `services/`: read models for API/dashboard; keep expensive shaping here, not in routes.
- `auth/`: sessions, tier checks, VIP expiry, audit, and rate limiting.
- `alerts/`: Telegram/email formatting and send helpers.
- `cli/notify.py`: VIP watchlist push orchestration after crawls.
- `static/` and `templates/`: dashboard UI.
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

## Signal Filter Runtime Flow

- Main tab filtering should run in two stages:
  - stage 1: request `/api/signals` immediately and update cards,
  - stage 2: request `/api/dashboard` in background for header/meta updates.
- `insights` data is not part of normal signal-filter refresh and should load on Insights tab activation.
- Infinite scroll must dedupe by listing id on client render to avoid race-condition duplicates.

## Dedup and Price Drop Policy

- Same URL/source_id is the same listing and should use `price_history` for same-listing price changes.
- Guland and BatDongSan cross-URL heuristics are disabled for duplicate/lot identity. Use source-id only.
- Facebook repost heuristics are allowed because broker reposts are meaningful, but only with strict guards.
- Same-price Facebook reposts may support lot history. Same-price Guland/BatDongSan reposts must not.
- `price_dropped=1` means a reliable drop. Drops over 40% should be `suspicious_bait=1`.

## Image Policy

- Cards use thumbnails via `services/image_assets.resolve_image_url(..., prefer_thumb=True)`.
- Detail/modal uses original images via `prefer_thumb=False`.
- `cleansing/download_images.py` creates thumbnails after new downloads.
- `scripts/generate_thumbnails.py` backfills thumbnails for existing images.

## Refactor Guidance

- Do not move files only for aesthetics.
- Move SQL out of `app.py` into `services/` when touching dashboard read behavior.
- Keep `config/database_sqlite.py` and `db/sqlite.py` as compatibility facades.
- If schema changes become frequent, add migration versioning instead of scattered ad hoc `ALTER TABLE`.
- For RBAC or Telegram push work, prefer `docs/rbac.md` and `docs/telegram_watchlist.md` over broad codebase reads.
