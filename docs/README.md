# Radar BDS Docs Map

This folder is organized so a new developer or AI agent can read only what the task needs.

## Minimal Onboarding

Read these in order:

1. `../AGENTS.md` - runtime facts, hard rules, and routing.
2. This file - choose the smallest extra doc set.
3. One task-specific file from the table below.

Do not load every doc by default. The project has long crawl and product notes; broad reads waste context and increase the chance of following stale guidance.

## Task Routing

| If the task is about | Read first | Usually touch |
|---|---|---|
| General coding workflow | `agent_playbook.md` | any touched module |
| Architecture or moving code out of `app.py` | `architecture.md` | `services/*`, `routes/*`, `app.py` |
| Crawl failed, daily automation, Apify/Facebook/Guland | `daily_crawl_flow.md`, `operations.md` | `cli/crawlers.py`, `crawler/*`, systemd/logs |
| Deploy/VPS/prod smoke/local-prod sync | `operations.md`, `dev_commands.md` | `scripts/deploy_production.ps1`, `deployment/ubuntu24/*` |
| Dedup, lot history, price drops, quality flags | `product_rules.md`, `architecture.md` | `cleansing/dedup.py`, `cleansing/feature_extractor.py`, `db/listings.py`, tests |
| Dashboard/API performance | `architecture.md`, `product_rules.md` | `services/market_data.py`, `routes/*`, `app.py` |
| Admin AI Training | `product_rules.md`, `agent_playbook.md` | `routes/admin_api.py`, `static/js/admin.js`, `templates/admin_control_room.html` |
| Advisory investment memo / signal memo updates | `investment_memo_workflow.md`, `operations.md` | `ai_deal_review`, `cli/review.py`, `app.py` |
| Auth, VIP, guest/free/admin masking | `rbac.md` | `auth/*`, `routes/auth.py`, frontend auth files |
| Telegram watchlist push/webhook | `telegram_watchlist.md` | `alerts/telegram.py`, `cli/notify.py`, auth Telegram routes |
| Local commands/tests | `dev_commands.md` | command line only |

## Source Policy Snapshot

- Facebook is the primary production source.
- Guland is secondary and runs after Facebook in a separate timer or fallback cron.
- BatDongSan is legacy/disabled. Existing import/delete helpers may remain for old data cleanup, but do not re-add BatDongSan to daily crawl unless the user explicitly changes that product decision.

## Token Budget Rules For Agents

- Prefer `rg` on exact symbols, API paths, table names, or listing IDs.
- Read headings before reading whole files.
- For data bugs, inspect the DB rows or API payload that proves the issue before editing parser/dedup logic.
- For UI bugs, inspect the specific template/CSS/JS and render the affected viewport when feasible.
- Avoid `_legacy/`, `.claude/worktrees/`, `data/`, `logs/`, `reports/`, `scratch/`, `browser_recordings/`, and `artifacts/` unless the current task explicitly needs them.

## Current Production Shape

- Domain: `https://radarbds.vn`.
- OS/runtime: Ubuntu Server 24.04 LTS, Python 3.12, systemd, Nginx.
- Flask service: `radar-bds.service`.
- Facebook daily timer: `radar-bds-crawl.timer`.
- Guland secondary timer: `radar-bds-guland-crawl.timer`, with deploy-user crontab fallback when systemd unit install is unavailable.
- Main crawl log: `logs/crawl-daily.log` under the production checkout.
