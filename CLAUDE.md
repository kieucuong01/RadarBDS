# Radar BDS - Claude Context

Claude should use the shared agent context in `AGENTS.md`.

This file is intentionally short to avoid duplicate, stale context across AI tools.

## Start Here

1. Read `AGENTS.md`.
2. Read `docs/agent_playbook.md` only if you need workflow detail.
3. Read `docs/architecture.md` only if you need module boundaries.
4. Read `docs/dev_commands.md` for exact Windows commands.

## Claude-Specific Reminder

- Do not scan runtime folders by default: `data/`, `logs/`, `reports/`, `scratch/`, `.claude/worktrees/`, `_legacy/`.
- Do not duplicate long project history into this file. Put durable history in `SUMMARY_HISTORY.md`.
- Treat `data/radar_bds.db` as the canonical runtime DB unless `RADAR_DB_PATH` is explicitly set.
