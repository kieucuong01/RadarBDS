# Radar BDS - Agent Quick Context

Read this first in every new AI/dev session. It is the token-light map, not the full manual.

## Read Order

1. `AGENTS.md` - current runtime facts, hard rules, and doc routing.
2. `docs/README.md` - choose the smallest doc set for the task.
3. Only read the task-specific doc below.

| Task | Read |
|---|---|
| Growth marketing, SEO strategy, CRO, marketing loops | `docs/growth_marketing_workflow.md` + relevant `.agents/skills/<skill>/SKILL.md` |
| Code workflow, traps, verification | `docs/agent_playbook.md` |
| Module boundaries, API shape, refactor target | `docs/architecture.md` |
| Crawl jobs, signal creation, daily automation | `docs/daily_crawl_flow.md` |
| Daily SEO article publishing | `docs/daily_seo_publisher.md` |
| Deploy, VPS ops, local/prod DB sync, logs | `docs/operations.md` |
| Product/data rules, dedup/history, quality gates | `docs/product_rules.md` |
| Exact local commands and test matrix | `docs/dev_commands.md` |
| Auth, tier gating, redaction | `docs/rbac.md` |
| VIP Telegram watchlist/webhook | `docs/telegram_watchlist.md` |

Avoid broad reads of `.claude/worktrees/`, `_legacy/`, `data/`, `logs/`, `reports/`, `scratch/`, `browser_recordings/`, and `artifacts/` unless the task explicitly requires runtime evidence from them.

## Project Summary

Radar BDS is a PostgreSQL + Flask dashboard for Bình Dương real-estate deal signals.

```text
crawler/* -> raw_listings -> cleansing/normalizer.py
          -> listings -> cleansing/dedup.py
          -> analytics/valuation.py -> valuation_results
          -> services/market_data.py -> Flask APIs/UI/VIP Telegram
```

Signal extraction and crawl post-processing are deterministic. Do not add
external LLM verification/enrichment back into crawl or reprocess without an
explicit product decision.

Focus areas:

- Thủ Dầu Một wards.
- Bến Cát wards and Mỹ Phước sub-zones.
- Production sources: Facebook primary, Guland secondary. BatDongSan is legacy/disabled and must not be added back into daily crawl without an explicit product decision.

Marketing skills:

- Project-local marketing skills from `coreyhaines31/marketingskills` live in `.agents/skills/`.
- For Radar BDS marketing work, prefer these project-local skills over global skill copies.
- Start with `.agents/product-marketing.md`, then use the smallest relevant skill (`marketing-loops`, `content-strategy`, `seo-audit`, `site-architecture`, `cro`, `analytics`, `schema`, `free-tools`, etc.).
- Do not treat the daily SEO publisher as the entire marketing strategy; it is one acquisition loop inside the broader dashboard -> watchlist -> Telegram/VIP funnel.

## Runtime Facts

- Canonical DB: PostgreSQL via `DATABASE_URL`.
- Local dev DB: installed PostgreSQL 18 service `postgresql-x64-18` on `127.0.0.1:5432`, database `radar_bds`, managed with pgAdmin4. The passworded local `DATABASE_URL` lives only in `.env`; never print or commit it.
- Portable PostgreSQL 17 in `tools/postgresql-17.10/` with data in `.local/postgres-data` is legacy/fallback for isolated restore or recovery only; it is not the normal local DB.
- Remote Supabase project `ozdjzfiqcjnlfuihqqjy` is sync/backup only. Passwords live only in local `.env`; never print or commit them.
- Production: Ubuntu Server 24.04 LTS, Python 3.12, systemd services, Nginx, domain `https://radarbds.vn`.
- Production env must set `PUBLIC_BASE_URL=https://radarbds.vn` and `DASHBOARD_BASE_URL=https://radarbds.vn`.
- Runtime data is ignored by git: DB dumps, `data/images/`, thumbnails, logs, reports, and backups must stay uncommitted.

## Core Entry Points

- `radar.py`: CLI router.
- `app.py`: Flask setup plus current route implementations.
- `routes/`: public/auth/market/admin blueprints; many still delegate to `app.py`.
- `services/market_data.py`: hot-path dashboard/listing read models and API shaping.
- `services/signal_quality.py`: latest valuation CTE and actionable signal gate.
- `services/image_assets.py`: image URL and thumbnail resolution.
- `cleansing/reprocess.py`: normalize, dedup, valuation orchestration.
- `cleansing/dedup.py`, `cleansing/feature_extractor.py`: lot identity, repost/history, extracted property features.
- `analytics/valuation.py`: fair value, MOS, signal scoring.
- `auth/core.py`: session, tier, rate-limit, VIP expiry, audit.
- `alerts/telegram.py`, `cli/notify.py`: VIP Telegram digest.
- `db/connection.py`, `db/schema.py`, `db/listings.py`: DB connection, schema, writes.

## Hard Rules

- Do not contaminate human labels: AI/Claude verdicts go only to `ai_deal_review`; never write them into `ai_training_feedback`.
- Only admin can expose original listing URLs and phone numbers. Guest/Free/VIP APIs must redact them.
- `/api/dashboard` is lightweight summary only. It must not return all signals, descriptions, or image arrays.
- `/api/signals` is the paginated card feed. Keep it compact and thumbnail-first.
- User-facing signal surfaces use latest valuation plus `services.signal_quality.actionable_signal_sql()`, not raw `valuation_results.is_signal` alone.
- `low_segment_confidence` alone does not suppress user-facing signals; show a warning badge instead.
- Facebook repost matching may use heuristics, but only with strong guards for type, location, area/dimensions, thổ cư, and phone.
- Guland and legacy BatDongSan use source-id identity only for lot history/dedup; do not use cross-URL same-lot heuristics for them.
- Daily production crawl is Facebook-first. Guland runs as a secondary timer/fallback cron. Do not put slow secondary crawl before Facebook.
- Do not reintroduce external LLM verification into crawl/reprocess. Advisory notes and Claude review stay manual/explicit and write only to `ai_deal_review`.

## Fast Commands

PowerShell local dev:

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
# .env should set DATABASE_URL=postgresql://postgres:<local-password>@127.0.0.1:5432/radar_bds
& $py -X utf8 radar.py inspect
& $py -X utf8 app.py
```

Common verification:

```powershell
& $py -X utf8 -m py_compile app.py services\market_data.py cleansing\dedup.py cleansing\feature_extractor.py analytics\valuation.py
node --check static\js\main.js
& $py -X utf8 -m pytest tests\test_dedup.py tests\test_price_history.py tests\test_lot_history.py tests\test_drop_filter.py
```

Deploy after pushing `main`:

```powershell
.\scripts\deploy_production.ps1
```

For exact commands, use `docs/dev_commands.md`.
