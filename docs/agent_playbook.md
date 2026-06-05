# Agent Playbook

This playbook is the day-to-day workflow guide for AI agents. Keep it compact; put product rules in `product_rules.md` and deploy details in `operations.md`.

## Start of Session

1. Read `AGENTS.md`.
2. Read `docs/README.md` and pick the smallest task-specific doc set.
3. Run or inspect `radar.py inspect` only when DB state matters.
4. Use `rg` for targeted search. Avoid scanning ignored runtime folders.
5. Check `git status --short --branch` before editing. Do not revert unrelated user changes.

## Folders to Avoid by Default

- `.claude/worktrees/`
- `_legacy/`
- `data/`
- `logs/`
- `reports/`
- `scratch/`
- `browser_recordings/`
- `artifacts/`

## Token Discipline

- Search exact symbols first: endpoint path, table name, CSS class, function, listing id, or source id.
- Read headings before full files.
- For UI issues, inspect the affected template/CSS/JS only, then verify the specific viewport.
- For data issues, inspect the affected DB rows or API payload before changing parser/dedup logic.
- Do not open generated reports/logs/images unless they are the evidence for the current bug.

## Change Discipline

- Crawler task: read `daily_crawl_flow.md`; keep changes in `crawler/` or `cli/crawlers.py`; verify raw row shape.
- Normalizer/extractor task: focus `cleansing/`; run extractor/dedup tests.
- Dedup/drop task: read `product_rules.md`; focus `cleansing/dedup.py`, `cleansing/feature_extractor.py`, `db/listings.py`, and related tests.
- Dashboard/API task: keep route handlers thin; put read shaping in `services/market_data.py`.
- RBAC/auth task: read `docs/rbac.md` first; security must be backend-side, not only hidden in UI.
- Telegram/watchlist task: read `docs/telegram_watchlist.md` first; one bot maps to per-user `telegram_chat_id`.
- Image performance task: use `services/image_assets.py`, `cleansing/download_images.py`, and `scripts/generate_thumbnails.py`.
- DB task: prefer `db/connection.py`, `db/schema.py`, or the focused repository file. Compatibility facades should stay thin.
- Deploy/ops task: read `operations.md`; prefer `scripts/deploy_production.ps1` and documented smoke checks.

## Current Traps

- Do not reintroduce `C:\Users\ASUS\radar_bds.db`; runtime DB is PostgreSQL via `DATABASE_URL`.
- Current local dev target is portable PostgreSQL; Supabase project `ozdjzfiqcjnlfuihqqjy` is sync/backup only. Never print or commit the password from `.env`.
- Tests run against PostgreSQL too. Use unique URL/ward/user tokens and cleanup by those tokens; patching `DB_PATH` no longer creates an isolated SQLite DB.
- Do not put all signals back into `/api/dashboard`; use `/api/signals`.
- Do not put full descriptions or full image arrays into signal card payloads.
- Do not make signal filtering wait on dashboard/insights; keep `signals-first` flow.
- Do not assume command-bar controls are inside `#filterForm`; keep explicit query append for `mos_min` and `only_drops`.
- Do not use Guland or legacy BatDongSan cross-URL heuristics for same-lot detection.
- Do not add BatDongSan back to daily crawl; it is legacy/disabled.
- Do not commit DB backups, `data/images/`, thumbnails, logs, or reports.
- Do not print `.env` secrets or Telegram bot token; mask tokens in status output.
- Do not assume zrok URLs are stable; update webhook when zrok restarts.
- Some terminal output may display Vietnamese as mojibake; prefer UTF-8 Python mode and inspect files with an editor/browser when text fidelity matters.

## Verification Matrix

- Python syntax: `py_compile` touched files.
- JS syntax: `node --check static/js/auth.js` plus touched `static/js/main/*.js` feature files.
- Auth UI syntax: `node --check static/js/auth.js`.
- Telegram push syntax: `py_compile alerts/telegram.py cli/notify.py`.
- Dedup: `tests/test_dedup.py`, `tests/test_price_history.py`, `tests/test_lot_history.py`, `tests/test_drop_filter.py`.
- Dashboard performance: payload check for `/api/dashboard` and `/api/signals?page=1&limit=30`.
- Filter performance: rapidly change MOS/drop/source/ward and confirm:
  - one signal fetch per settled interaction,
  - no stale overwrite from older requests,
  - no duplicate cards when scrolling page 2/3.
- Images: confirm card uses `/data/images/thumbs/*.webp` and modal uses `/data/images/*`.
- Docs-only change: run `git diff --check` and search for stale source/runtime claims.

## When Updating Docs

- Keep `AGENTS.md` short and current.
- Keep long history in `SUMMARY_HISTORY.md`.
- Prefer linking to `docs/*.md` over duplicating details.
- Remove stale dates/counts unless they are part of a historical note.
