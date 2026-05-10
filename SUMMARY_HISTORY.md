# Radar BDS - Summary History and Handoff

This file keeps durable handoff notes for future AI sessions. For day-to-day context, read `AGENTS.md` first.

## Current Handoff - 2026-05-10

- Canonical DB is `data/radar_bds.db`; `RADAR_DB_PATH` remains the override.
- Runtime data is ignored by git: DB files, `data/images/`, thumbnails, logs, reports, and scratch output.
- Dashboard first load was optimized:
  - `/api/dashboard` is lightweight summary only.
  - `/api/signals` is paginated card summary, default `limit=30`.
  - `/api/listing/<id>` lazy-loads full modal detail and original images.
- Signal card scroll was optimized:
  - Cards use WebP thumbnails from `data/images/thumbs/`.
  - Modal/detail still uses original images from `data/images/`.
  - `scripts/generate_thumbnails.py` backfills thumbnails.
  - `cleansing/download_images.py` creates thumbnails for new downloads.
- Current dedup policy:
  - Same URL/source_id means same listing.
  - Guland/BatDongSan cross-URL lot heuristics are disabled; source-id only.
  - Facebook repost heuristics remain, with strict property/location/thổ cư guards.
- Current doc policy:
  - `AGENTS.md` is the primary quick context for all agents.
  - `CLAUDE.md` intentionally points to `AGENTS.md` instead of duplicating content.
  - `docs/architecture.md`, `docs/dev_commands.md`, and `docs/agent_playbook.md` hold deeper context.

## Older Stable Milestones

- Refactored `app.py` toward thin Flask routes and moved dashboard read shaping into `services/market_data.py`.
- Refactored DB layer into focused modules under `db/`; `config/database_sqlite.py` remains a compatibility facade.
- Added incremental reprocess flow for daily crawls.
- Moved valuation to per-ward models with recent-record training limits.
- Added Facebook/Guland/BatDongSan crawl flows and local image download pipeline.
- Added dashboard filters, sorting, modal detail, history/comps, and all-listings tab.

## What Not To Reintroduce

- Do not document `C:\Users\ASUS\radar_bds.db` as the default DB.
- Do not make `/api/dashboard` return all signals/descriptions/images again.
- Do not use Guland/BatDongSan cross-URL heuristics for same-lot price drop.
- Do not rely on remote Facebook image URLs for dashboard cards; use local images and thumbnails.
