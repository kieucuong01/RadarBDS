# Radar BDS - Agent Quick Context

Use this file as the first read for Codex, Claude Code, Antigravity, or any new AI session. It is intentionally compact. Read deeper docs only when the task touches that area.

## Read Order

1. `AGENTS.md` - this quick context.
2. `docs/agent_playbook.md` - workflow rules and common traps.
3. `docs/architecture.md` - module boundaries and current data flow.
4. `docs/dev_commands.md` - exact Windows commands for checks.

Avoid broad reads of `.claude/worktrees/`, `_legacy/`, `data/`, `logs/`, `reports/`, `scratch/`, `browser_recordings/`, and `artifacts/` unless the task explicitly requires them.

## Project Summary

Radar BDS is a local SQLite + Flask dashboard for Bình Dương real-estate signals.

Pipeline:

```text
crawler/* -> raw_listings -> cleansing/normalizer.py
          -> listings -> cleansing/dedup.py
          -> analytics/valuation.py -> valuation_results
          -> Flask dashboard / Telegram alerts / CLI reports
```

Supported focus areas:

- Thủ Dầu Một wards.
- Bến Cát wards and Mỹ Phước sub-zones.
- Sources: Facebook, Guland, BatDongSan.

## Canonical Runtime State

- Canonical DB: `data/radar_bds.db`.
- Override: `RADAR_DB_PATH`; relative values resolve from repo root.
- Runtime images: `data/images/`.
- Card thumbnails: `data/images/thumbs/*.webp`.
- Runtime data is ignored by git. Do not commit DB files, images, reports, or logs.
- If app behavior differs from code, check which DB is loaded:

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python39\python.exe"
& $py -X utf8 -c "import db.connection as c; print(c.DB_PATH)"
```

## Core Entry Points

- `radar.py`: CLI router.
- `app.py`: Flask routes only; keep route handlers thin.
- `services/market_data.py`: dashboard/listing read models and API shaping.
- `services/image_assets.py`: image URL normalization and thumbnail resolution.
- `cleansing/reprocess.py`: normalize, dedup, valuation orchestration.
- `cleansing/dedup.py`: duplicate and price-drop policy.
- `db/connection.py`, `db/schema.py`, `db/listings.py`: DB path, schema, writes.
- `config/database_sqlite.py`: compatibility facade; new code should prefer `db.*`.

## Current Product Rules

Dedup and price drop:

- Same URL/source_id: same listing; track price changes with `price_history`.
- Guland/BatDongSan: source-id only for duplicate/lot identity. Do not use cross-URL heuristics for lot history or price drop.
- Facebook: heuristic repost matching is allowed, but must pass strong guards for property type, thổ cư, location, area/dimensions, and phone.
- `only_drops=1` may show duplicate reposts if `price_dropped=1`.
- Suspicious drops over 40% should be `suspicious_bait`, not normal price-drop signal.

Dashboard/API:

- `/api/dashboard` is lightweight summary only. It must not return all signals, descriptions, or image arrays.
- `/api/signals` is paginated card data. Default limit is 30. It returns `primary_img` thumbnail when available.
- `/api/listing/<id>` is full modal/detail data, including description and full image list.
- `/api/history/<id>` returns same-listing price history and lot history/comps payload used by modal.
- Filtering UX is `signals-first`: update `/api/signals` immediately, then refresh `/api/dashboard` in background.
- Do not block signal rendering behind dashboard/insights fetches.
- In command-bar flow, `mos_min` and `only_drops` controls are outside `#filterForm`; query assembly must append them explicitly.

Images/performance:

- Cards must use thumbnails from `data/images/thumbs/`.
- Modal/detail may use original images.
- `download_images()` creates thumbnails for new downloads.
- Backfill thumbnails with `python scripts/generate_thumbnails.py --signals 300` or full backfill without `--signals`.

## Common Commands

Use UTF-8 mode on Windows:

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python39\python.exe"
& $py -X utf8 radar.py inspect
& $py -X utf8 app.py
& $py -X utf8 radar.py reprocess
& $py -X utf8 scripts\generate_thumbnails.py --signals 300
```

Targeted checks:

```powershell
& $py -X utf8 -m py_compile app.py services\market_data.py services\image_assets.py cleansing\download_images.py
node --check static\js\main.js
& $py -X utf8 -m pytest tests\test_dedup.py tests\test_price_history.py tests\test_lot_history.py tests\test_drop_filter.py
```

## Verification Defaults

- Backend/API change: run `py_compile` for touched Python files and the relevant pytest file.
- Frontend JS change: run `node --check static/js/main.js` and smoke test `http://127.0.0.1:5000`.
- Dashboard/API performance change: check payload sizes for `/api/dashboard`, `/api/signals?page=1&limit=30`, and `/api/listing/<id>`.
- Filter performance change: verify no duplicate requests per interaction and no duplicate cards across signal pages.
- Dedup/price-drop change: run targeted dedup/history/drop tests, then recompute only if explicitly needed.

## Agent Discipline

- Make surgical changes; do not refactor adjacent code for aesthetics.
- Do not revert user changes or runtime data unless explicitly requested.
- Prefer repo patterns and existing service boundaries.
- Keep docs concise; move long historical notes to `SUMMARY_HISTORY.md`.
- When changing behavior, update this file only if future agents need to know it.
