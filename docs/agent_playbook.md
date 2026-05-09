# Agent Playbook

## Read First

- `AGENTS.md` for project context.
- `docs/architecture.md` for module boundaries.
- `docs/dev_commands.md` for verification commands.

## Avoid By Default

Do not inspect or edit these unless the task explicitly requires it:

- `.claude/worktrees/`
- `_legacy/`
- `data/`
- `logs/`
- `reports/`
- `scratch/`
- `browser_recordings/`
- `artifacts/`

These directories are runtime output, old code, or agent workspaces. Reading them during broad searches creates false context.

## Change Discipline

- For crawler changes, verify raw record shape and avoid touching valuation.
- For normalizer/extractor changes, run feature extractor and valuation tests.
- For valuation changes, run valuation and dedup tests, then consider `radar.py inspect` if a real DB is available.
- For dashboard changes, keep route handlers thin and prefer moving SQL/read shaping into `services/`.
- For DB changes, prefer the focused `db.*` module that owns the table or concern. `db.sqlite` and `config.database_sqlite` are compatibility facades.

## Current Known Architecture Debt

- Dashboard read SQL still lives partly in `app.py` and `services/market_data.py`.
- Ward/city config is duplicated across normalizer, settings, and dashboard services.
- Some tests are smoke-test compatible and can run directly without pytest.
