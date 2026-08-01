# Radar BDS - Agent Quick Context

Read this first in every new AI/dev session. It is the token-light map, not the full manual.

## Read Order

1. `AGENTS.md` - current runtime facts, hard rules, and doc routing.
2. `docs/README.md` - choose the smallest doc set for the task.
3. Only read the task-specific doc below.

| Task | Read |
|---|---|
| Growth marketing, SEO strategy, CRO, Hermes marketing loops | `docs/growth_marketing_workflow.md` + `docs/hermes_marketing_workflow.md` + relevant `.agents/skills/<skill>/SKILL.md` |
| Code workflow, traps, verification | `docs/agent_playbook.md` |
| Module boundaries, API shape, refactor target | `docs/architecture.md` |
| Crawl jobs, signal creation, daily automation | `docs/daily_crawl_flow.md` |
| Daily SEO article publishing, `/tin-tuc`, @rb daily cron | `docs/daily_seo_publisher.md` + `docs/radar_bds_90_day_seo_roadmap.md` |
| Browser-use social ops, Facebook groups/Page, broker discovery, trend monitoring | `docs/browser-use-social-ops.md` + `docs/social-care-workflow.md` + `docs/broker-discovery.md` (auto-post wrapper: `scripts/radar_social_auto_post.py`; broker scoring: `scripts/radar_broker_discovery.py`) |
| Monthly market reports, `/bao-cao` hub, report cron automation | `docs/seo-monthly-reports.md` |
| Deploy, VPS ops, local/prod DB sync, logs | `docs/operations.md` |
| Homepage/filter performance, cache/read-model scaling, CDN, 1,000-5,000 concurrent public requests | `docs/superpowers/specs/2026-08-01-homepage-filter-performance-scale-design.md` + `docs/superpowers/plans/2026-08-01-homepage-performance-scale-master.md` + `docs/superpowers/specs/2026-08-01-cloudflare-origin-shield-design.md` + production truth in `docs/operations.md` |
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
- Do not treat the daily SEO publisher as the entire marketing strategy; it is one acquisition loop inside the broader SEO/social/AI -> filtered dashboard -> signal contact funnel.

## Runtime Facts

- Canonical DB: PostgreSQL via `DATABASE_URL`.
- Environment files: `.env` is the production-shaped base copied from the VPS when needed; `.env.local` is ignored local override and wins on this machine.
- Current local dev DB override: portable PostgreSQL 17 at `127.0.0.1:15432`, database `radar_bds`; test DB `radar_bds_test`. Start it with `scripts/local_postgres.ps1 start` if port 15432 is not accepting connections.
- Installed PostgreSQL 18 service `postgresql-x64-18` on `127.0.0.1:5432` exists but local credentials may drift; do not assume it is the active dev DB unless `.env.local` points there.
- Remote Supabase project `ozdjzfiqcjnlfuihqqjy` is sync/backup only. Passwords live only in ignored env files; never print or commit them.
- Production: Ubuntu Server 24.04 LTS, Python 3.12, systemd services, Nginx, domain `https://radarbds.vn`.
- Production public-read path uses guest-only Nginx microcache -> bounded Gunicorn `3x4` -> Redis cache/read model -> PostgreSQL pool max `4` per worker. Redis is loopback-only, disposable, persistence-off, and capped at 256 MB. Current exact settings, evidence, and rollback are in `docs/operations.md`.
- Public DNS currently points directly to `103.90.226.230` on Vietnix nameservers; Cloudflare/CDN is not active. The direct external path is the measured capacity bottleneck. Do not rerun the distributed capacity branch until the authenticated CDN cutover and `-RequireCdn` verifier pass.
- Production env must set `PUBLIC_BASE_URL=https://radarbds.vn` and `DASHBOARD_BASE_URL=https://radarbds.vn`.
- Local and production env must set a private `GULAND_PUBLISHER_KEY_SECRET` of at least 32 random characters before publisher identity capture/backfill.
- Runtime data is ignored by git: DB dumps, `data/images/`, thumbnails, logs, reports, and backups must stay uncommitted.

## Core Entry Points

- `radar.py`: CLI router.
- `app.py`: Flask setup plus current route implementations.
- `routes/`: public/auth/market/admin blueprints; many still delegate to `app.py`.
- `services/market_data.py`: hot-path dashboard/listing read models and API shaping.
- `services/signal_read_model.py`: transactional `signal_card_read_model` refresh and feature-flagged compact signal query.
- `services/public_cache_keys.py`, `services/public_cache.py`: canonical tier/version keys, Redis fresh/stale single-flight, and bounded local fallback.
- `services/public_data_publish.py`, `services/public_prewarm.py`: post-commit version mirror and no-cookie allowlisted warming after deterministic data jobs.
- `deployment/ubuntu24/*`, `scripts/install_performance_infra.sh`, `scripts/verify_public_cache.ps1`, `scripts/load/radar_public_load.js`, `scripts/load/aggregate_k6_shards.py`, `scripts/load/observe_production_capacity.ps1`: bounded production capacity, reversible install, origin/CDN privacy proof, conservative distributed aggregation, and host observation.
- `static/js/main/filter_runtime.js`: canonical browser filter queries and the signal-first/counts-after sequencing helper.
- `static/js/main/web_vitals.js`: dependency-free LCP/INP/CLS observation and PII-free GA4 emission; `signals.js` owns the `radar-first-signal-cards` measure.
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
- `RADAR_SIGNAL_READ_MODEL_ENABLED` defaults to `0`. Enable it only after `radar.py signal-read-model --refresh --compare` reports zero differences in the target environment; rollback is flag `0` plus service restart.
- A failed signal read-model refresh must leave the previous complete rows/version active. Never bump `public_dataset_versions.signals` outside the refresh transaction.
- `db.connection.get_conn()` is a lazy bounded pool scope (default max 4/process). Always return connections through that context; keep `connect()` only for explicit fresh-connection owners.
- Production has `RADAR_PUBLIC_CACHE_ENABLED=1` only after local-only Redis, the real integration test, guest/private isolation checks, rollback drill, and Redis-stop/recovery drill passed. A new environment must repeat those gates before enabling it.
- Public cache keys use only parsed/clamped response-changing values plus effective tier and durable dataset versions. Admin bypasses; guest/Free/VIP never share namespaces.
- Only anonymous guest `/`, `/api/signals`, `/api/counts`, and `/api/dashboard` may carry `X-Radar-Public-Cache: 1`. Any session, Authorization, Set-Cookie, admin, error, saved/auth/admin/checkout/order response remains private/no-store.
- Publish read-model/version data in PostgreSQL first, exit/commit, then mirror Redis and prewarm. Redis/prewarm failure must be reported separately and must not relabel committed DB data as failed.
- The capacity objective means roughly 1,000-5,000 simultaneous in-flight public requests, not 5,000 sustained origin RPS. Do not claim that gate from unit tests or single-request timings; use the staged production load plan.
- The 2026-08-01 direct-origin gate passed the local normal profile at 100 VUs and mixed filters at 500 VUs. Distributed run `30698414443` then failed closed at external default 100 with 0% HTTP/check errors but p95 2.24 s and p99 3.10 s while CPU/DB/Redis/listen queues stayed healthy. This, the 1.2-2.2 MB/s external plateau, and the same-host ~8 MB/s diagnostic prove the public egress/path is the next bottleneck. Do not rerun 500-5,000 or raise backend bounds before CDN/origin shielding is active and verified.
- On the Signals tab, one settled filter starts exactly one immediate `/api/signals` request. `/api/counts` is deferred until that signal load settles; `/api/dashboard` must not run on this path. Dashboard metadata remains a non-Signals-tab concern.
- Keep browser request cancellation and newest-response-wins together: `requestControllers[scope].abort()`, `signalRunSeq`, `signalRenderSeq`, `renderedSignalIds`, and page-1 reset are one invariant set. Do not remove one in isolation.
- User-facing signal surfaces use latest valuation plus `services.signal_quality.actionable_signal_sql()`, not raw `valuation_results.is_signal` alone.
- `low_segment_confidence` alone does not suppress user-facing signals; show a warning badge instead.
- Facebook repost matching may use heuristics, but only with strong guards for type, location, area/dimensions, thổ cư, and phone.
- Guland and legacy BatDongSan use source-id identity only for lot history/dedup; do not use cross-URL same-lot heuristics for them.
- Guest/Free/VIP may see Guland `low_manual` and fail-open `unknown` publishers. Hide `high_activity` and `automated_repost`; only admin may reveal or override them.
- Guland publisher activity is a feed/map ranking and visibility policy, not a source-quality flag or valuation input. `guland_cluster_flood` is retired as a hard gate.
- Daily production crawl is Facebook-first. Guland runs as a secondary timer/fallback cron. Do not put slow secondary crawl before Facebook.
- Do not reintroduce external LLM verification into crawl/reprocess. Advisory notes and Claude review stay manual/explicit and write only to `ai_deal_review`.

## Fast Commands

PowerShell local dev:

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
# .env.local should set local DATABASE_URL and RADAR_TEST_DATABASE_URL
& $py -X utf8 radar.py inspect
& $py -X utf8 app.py
```

Common verification:

```powershell
& $py -X utf8 -m py_compile app.py services\market_data.py cleansing\dedup.py cleansing\feature_extractor.py analytics\valuation.py
node --check static\js\main.js
& $py -X utf8 -m pytest tests\test_dedup.py tests\test_price_history.py tests\test_lot_history.py tests\test_drop_filter.py
& $py -X utf8 radar.py signal-read-model --refresh --compare --limit 200
& $py -X utf8 -m pytest tests\test_postgres_connection.py tests\test_public_cache_keys.py tests\test_public_cache.py tests\test_public_cache_headers.py tests\test_public_prewarm.py -q
```

Deploy after pushing `main`:

```powershell
.\scripts\deploy_production.ps1
```

For exact commands, use `docs/dev_commands.md`.
