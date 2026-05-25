# Agent Playbook

This playbook helps agents work without wasting context or breaking local runtime state.

## Start of Session

1. Read `AGENTS.md`.
2. Run or inspect `radar.py inspect` only when DB state matters.
3. Use `rg` for targeted search. Avoid scanning ignored runtime folders.
4. Check `git status --short` before editing. Do not revert unrelated user changes.

## Folders to Avoid by Default

- `.claude/worktrees/`
- `_legacy/`
- `data/`
- `logs/`
- `reports/`
- `scratch/`
- `browser_recordings/`
- `artifacts/`

## Change Discipline

- Crawler task: keep changes in `crawler/` or `cli/crawlers.py`; verify raw row shape.
- Normalizer/extractor task: focus `cleansing/`; run extractor/dedup tests.
- Dedup/drop task: focus `cleansing/dedup.py`, `db/listings.py`, and related tests.
- Dashboard/API task: keep route handlers thin; put read shaping in `services/market_data.py`.
- RBAC/auth task: read `docs/rbac.md` first; security must be backend-side, not only hidden in UI.
- Telegram/watchlist task: read `docs/telegram_watchlist.md` first; one bot maps to per-user `telegram_chat_id`.
- Image performance task: use `services/image_assets.py`, `cleansing/download_images.py`, and `scripts/generate_thumbnails.py`.
- DB task: prefer `db/connection.py`, `db/schema.py`, or the focused repository file. Compatibility facades should stay thin.

## Current Traps

- Do not reintroduce `C:\Users\ASUS\radar_bds.db`; runtime DB is PostgreSQL via `DATABASE_URL`.
- Current local DB target is Supabase project `ozdjzfiqcjnlfuihqqjy`; never print or commit the password from `.env`.
- Tests run against PostgreSQL too. Use unique URL/ward/user tokens and cleanup by those tokens; patching `DB_PATH` no longer creates an isolated SQLite DB.
- Do not put all signals back into `/api/dashboard`; use `/api/signals`.
- Do not put full descriptions or full image arrays into signal card payloads.
- Do not make signal filtering wait on dashboard/insights; keep `signals-first` flow.
- Do not assume command-bar controls are inside `#filterForm`; keep explicit query append for `mos_min` and `only_drops`.
- Do not use Guland/BatDongSan cross-URL heuristics for same-lot detection.
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

## When Updating Docs

- Keep `AGENTS.md` short and current.
- Keep long history in `SUMMARY_HISTORY.md`.
- Prefer linking to `docs/*.md` over duplicating details.
- Remove stale dates/counts unless they are part of a historical note.
