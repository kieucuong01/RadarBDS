# Operations And Deploy

Use this for VPS deploy, production smoke checks, DB sync, crawl logs, and one-off production maintenance.

## Environments

| Environment | Purpose | Notes |
|---|---|---|
| Local Windows | Development and safe reprocess/audit | Python 3.12, `.env.local` override, local PostgreSQL on `127.0.0.1:15432` |
| Production VPS | Public site and daily crawl | Ubuntu Server 24.04 LTS, Python 3.12, systemd, Nginx |
| Supabase project `ozdjzfiqcjnlfuihqqjy` | Sync/backup | Password only in local `.env`; do not print/commit |

Public domain: `https://radarbds.vn`. Production env file: `/etc/radar-bds/radar.env`.

## Deploy Flow

For the normal local one-command ship:

```powershell
.\scripts\ship_production.ps1 -Message "Short commit message" -All
```

Use `-Path file1,file2` instead of `-All` when the worktree has unrelated dirty
files that should not be committed.

The ship script stages the requested files, commits, pushes `origin/main`, then
runs production deploy. If the VPS checkout cannot fetch from GitHub because of
the `github.com-radarbds` alias/auth path, it automatically deploys the pushed
commit through a local `git bundle` fallback.

After code is already committed and pushed to `origin/main`:

```powershell
.\scripts\deploy_production.ps1
```

The deploy script:

- uses `$env:USERPROFILE\.ssh\radar_bds_deploy_rsa`,
- fast-forwards the VPS checkout,
- removes legacy `data/facebook_profiles.json` after a DB migration/backup so Facebook broker configuration comes only from `facebook_crawl_profiles`,
- allows runtime `data/raw_backup.json` to stay dirty on the VPS,
- auto-archives a small allowlist of known temporary audit/report files from the VPS checkout to `/tmp/radar-bds-deploy-known-temp-*.tgz`,
- restarts `radar-bds.service`,
- smokes `/api/dashboard` and `/api/signals`,
- prewarms dashboard cache,
- installs/falls back Guland secondary scheduling when needed.

The archive cleanup is intentionally narrow. If any dirty production file remains
outside the built-in allowlist, deploy must still stop and report the exact file list.

Deploy does not automatically run a full production reprocess for every code change. For parser, dedup, valuation, schema, or quality-gate changes, run an explicit reprocess after deploy.

Map registry/browser-evidence releases use the dedicated sequence in
`docs/listing_map_registry_automation.md`, including deterministic double-build,
production `map-locations --full --dry-run`, apply, and browser smoke. Browser
research is an offline maintenance step and must never be added to crawl or a
public request path.

When removing or changing extraction/valuation logic, use this sequence:

```powershell
git push origin main
.\scripts\deploy_production.ps1
ssh -i "$env:USERPROFILE\.ssh\radar_bds_deploy_rsa" deploy@103.90.226.230 "set -a; . /etc/radar-bds/radar.env; set +a; cd /opt/radar-bds/current && /opt/radar-bds/.venv/bin/python -X utf8 radar.py reprocess --full"
ssh -i "$env:USERPROFILE\.ssh\radar_bds_deploy_rsa" deploy@103.90.226.230 "cd /opt/radar-bds/current && curl -fsS http://127.0.0.1:5000/api/dashboard >/dev/null && curl -fsS 'http://127.0.0.1:5000/api/signals?page=1&limit=3' >/dev/null && curl -fsS 'http://127.0.0.1:5000/api/dashboard?cache_refresh=1' >/dev/null"
```

## Production Reprocess

Use the deploy user and production env file:

```powershell
ssh -i "$env:USERPROFILE\.ssh\radar_bds_deploy_rsa" deploy@103.90.226.230 "set -a; . /etc/radar-bds/radar.env; set +a; cd /opt/radar-bds/current && /opt/radar-bds/.venv/bin/python -X utf8 radar.py reprocess --full"
```

Then smoke:

```powershell
ssh -i "$env:USERPROFILE\.ssh\radar_bds_deploy_rsa" deploy@103.90.226.230 "cd /opt/radar-bds/current && curl -fsS http://127.0.0.1:5000/api/dashboard >/dev/null && curl -fsS 'http://127.0.0.1:5000/api/signals?page=1&limit=3' >/dev/null"
```

## Signal Read Model Rollout And Rollback

Phase 1 is additive and must be deployed feature-off first. In `/etc/radar-bds/radar.env` keep:

```bash
RADAR_SIGNAL_READ_MODEL_ENABLED=0
RADAR_SIGNAL_QUERY_TIMEOUT_MS=5000
```

After deploying code and confirming the legacy API still works, initialize/backfill and compare as the runtime user:

```bash
cd /opt/radar-bds/current
set -a
. /etc/radar-bds/radar.env
set +a
/opt/radar-bds/.venv/bin/python -X utf8 radar.py signal-read-model --refresh --compare --limit 200
```

The command is safe for logs: it prints counts, listing ids, case names, and differing field names only. It never prints descriptions, phone numbers, source URLs, response bodies, cookies, or env values. Do not enable the flag unless `difference_count` is `0`.

Then set `RADAR_SIGNAL_READ_MODEL_ENABLED=1`, restart `radar-bds.service`, and check VPS-local plus public paths:

```bash
sudo systemctl restart radar-bds.service
sudo systemctl is-active radar-bds.service
/opt/radar-bds/.venv/bin/python -X utf8 scripts/benchmark_public_read_path.py --base-url http://127.0.0.1:5000 --repeat 5
/opt/radar-bds/.venv/bin/python -X utf8 scripts/benchmark_public_read_path.py --base-url https://radarbds.vn --repeat 5
```

Rollback is immediate and data-preserving: set the feature flag back to `0` and restart the service. Keep `signal_card_read_model` and `public_dataset_versions`; they are additive and useful for diagnosis. A failed refresh returns `public_read_model.status=error` to crawl/admin stats and leaves the prior complete rows/version active. The strict CLI exits nonzero.

Useful read-only inspection:

```sql
SELECT dataset_name, version, updated_at
FROM public_dataset_versions
ORDER BY dataset_name;

SELECT COUNT(*) AS rows, MAX(refreshed_at) AS newest_refresh
FROM signal_card_read_model;

SELECT relname, reloptions
FROM pg_class
WHERE relname IN (
  'signal_card_read_model', 'listings', 'valuation_results',
  'valuation_shadow_results', 'listing_images',
  'listing_publishers', 'source_publishers'
)
ORDER BY relname;
```

The runtime migration catches `insufficient_privilege` only for the optional reloption tuning on pre-existing tables. The new read-model/version tables remain mandatory. If the inspection query shows missing options, have the PostgreSQL table owner apply `autovacuum_analyze_scale_factor=0.02` and `autovacuum_analyze_threshold=100`; do not grant broader ownership to the web runtime role merely to pass deploy.

After schema init under a limited-owner runtime role, verify the required objects separately before restarting or enabling the flag. A warning that a later legacy migration was skipped is not proof that the earlier transaction committed:

```sql
SELECT to_regclass('public.public_dataset_versions') AS versions_table,
       to_regclass('public.signal_card_read_model') AS read_model_table,
       to_regclass('public.listing_map_locations') AS map_locations_table;

SELECT dataset_name, version
FROM public_dataset_versions
ORDER BY dataset_name;
```

All three object names must be non-null and the version table must contain `market` and `signals`. `db.schema.init_schema()` commits these required objects before best-effort legacy migrations; if an optional migration then hits `insufficient_privilege`, it rolls back that optional transaction only.

If compare reports only `order_mismatch` for Guland with identical IDs and fields, inspect `price_updated_at`, `first_seen_at`, and `crawled_at` string formats before changing indexes. Mixed space/`T` separators are present in production, and Phase 1 must preserve the existing lexical `listing_activity_at_sql()` order. Do not sort `newest` solely by normalized `signal_card_read_model.activity_at` unless that user-visible behavior change has its own migration and acceptance test.

This rollout proves parity and normal-load latency only. Do not claim the 1,000-5,000 simultaneous in-flight request objective until the later pooling/cache/Nginx phases and staged load gates pass.

## Shared Public Cache And PostgreSQL Pool Rollout

Phase 2 application code is safe to deploy before Redis, but production must initially keep:

```bash
RADAR_DB_POOL_MIN=1
RADAR_DB_POOL_MAX=4
RADAR_DB_POOL_TIMEOUT_SECONDS=1.0
RADAR_PUBLIC_CACHE_ENABLED=0
RADAR_REDIS_URL=redis://127.0.0.1:6379/0
RADAR_CACHE_SCHEMA_VERSION=1
RADAR_PUBLIC_CACHE_FRESH_SECONDS=60
RADAR_PUBLIC_CACHE_STALE_SECONDS=180
RADAR_PUBLIC_CACHE_LOCK_SECONDS=5
RADAR_PUBLIC_CACHE_WAIT_SECONDS=0.25
RADAR_PUBLIC_DB_SLOTS=2
RADAR_PUBLIC_STATEMENT_TIMEOUT_MS=1500
RADAR_PUBLIC_PREWARM_URL=http://127.0.0.1:5000
```

The connection budget is `Gunicorn workers * RADAR_DB_POOL_MAX`. The approved Phase 4 target is `3 * 4 = 12` web connections. Do not increase either value independently. Under ordinary web-only traffic, inspect PostgreSQL from a privileged SQL session and keep the Radar database/user count within that budget; exclude a separately running crawl/reprocess before interpreting the count:

```sql
SELECT datname, usename, state, COUNT(*) AS sessions
FROM pg_stat_activity
WHERE datname = current_database()
GROUP BY datname, usename, state
ORDER BY usename, state;
```

Pool saturation raises a controlled application error instead of creating unbounded connections. Confirm service logs contain the configured `PostgreSQL pool initialized min=1 max=4` line and that `/api/signals`, `/api/counts`, and `/api/dashboard` remain correct with the cache flag off.

Do not enable the cache flag until Phase 4 has installed a local-only Redis service and these checks pass:

```bash
sudo systemctl is-active redis-server
redis-cli -h 127.0.0.1 -p 6379 PING
ss -lntp | grep '127.0.0.1:6379'
redis-cli -h 127.0.0.1 -p 6379 INFO server | grep '^redis_version:'
redis-cli -h 127.0.0.1 -p 6379 INFO memory | grep -E '^(used_memory_human|maxmemory_human|maxmemory_policy):'
```

Expected: `active`, `PONG`, loopback-only listening, the installed Redis version, and the Phase 4 cache-only memory/policy limits. Redis contains no source-of-truth data and persistence remains disabled by the Phase 4 service configuration.

Dataset and cache inspection without response bodies or credentials:

```bash
sudo -u radar bash -lc 'set -a; . /etc/radar-bds/radar.env; set +a; cd /opt/radar-bds/current && /opt/radar-bds/.venv/bin/python -X utf8 -c "from services.public_cache import get_current_dataset_versions; print(get_current_dataset_versions((\"signals\",\"market\")))"'
curl -sS -D - -o /dev/null 'http://127.0.0.1:5000/api/signals?include_total=0&limit=30&page=1&sort=newest'
curl -sS -D - -o /dev/null 'http://127.0.0.1:5000/api/counts'
curl -sS -D - -o /dev/null 'http://127.0.0.1:5000/api/dashboard'
```

`X-Radar-Cache` is `miss`, `hit`, `stale`, or `bypass`; `Server-Timing` reports cache status and loader duration. Only anonymous guest responses may include `X-Radar-Public-Cache: 1` plus the public 15-second policy. Repeat with a harmless `Cookie: radar_session=invalid-probe` and with an `Authorization` header; both must return `Cache-Control: private, no-store` and no public marker. Do not log real session/admin values.

Committed read-model publication follows this order: DB refresh/version commit, Redis version mirror, then the six allowlisted warm routes from `config/public_cache_warm_routes.json`. Publication output keeps DB `status=ok` and reports mirror/prewarm state separately under `cache`. Prewarm sends no cookie/authorization, reads at most 2 MiB, and logs status only.

Rollback order:

1. For any privacy/key/version issue, set `RADAR_PUBLIC_CACHE_ENABLED=0` and restart `radar-bds.service` immediately.
2. Verify all three endpoints return `X-Radar-Cache: bypass` and correct tier redaction.
3. Redis may then be stopped or repaired without affecting PostgreSQL truth.
4. Keep the pool limits in place. Roll back pool code only by deploying the prior commit; never compensate by raising PostgreSQL connection limits during an incident.

The Phase 2 runtime gate is complete only after the Phase 4 controlled drill proves a shared hit/lock across at least two Gunicorn workers, one loader for 100 identical cold requests, bounded work/stale-or-503 while Redis is stopped, version bootstrap after restart, and both cache flags `0` and `1`. Until then the production cache flag stays `0`.

## Signal-First Frontend Runtime

The Signals-tab request contract is:

```text
canonical filter snapshot -> /api/signals immediately -> first card chunk
                                                   \-> /api/counts after settle/idle
```

`/api/dashboard` is intentionally absent while the Signals tab stays active. It is still used when a filter changes on a non-Signals tab. Cache-busting version `homepage-perf-20260801` covers `core.js`, `filter_runtime.js`, `filters.js`, `signals.js`, and `web_vitals.js`; all changed immutable assets must retain a coordinated version bump on later edits.

Keep these browser-visible safeguards together during incident diagnosis: AbortController per request scope, canonical snapshot check before deferred counts, signal response run id, render-chunk sequence, and listing-id deduplication. A stale response in Network is acceptable only when it is visibly canceled and cannot mutate the final cards.

Controlled local browser evidence from 2026-08-01 (cache disabled, local PostgreSQL, not a capacity claim):

- desktop HTML TTFB `4.7 ms`; first signals `321.8 ms`; `radar-first-signal-cards` `337.1 ms`; counts began at `519.4 ms`; LCP `528 ms`; CLS `0.0015`;
- mobile `390x844`: HTML TTFB `45.8 ms`; first signals `277.0 ms`; first cards `299.9 ms`; counts began at `517.4 ms`; LCP `580 ms`; CLS `0.00023`; the tested interaction produced no event at the 40 ms observer threshold, so the controlled sample is `<40 ms`;
- mobile rendered one card column with zero horizontal overflow; the first trace contained signals then counts and no dashboard;
- a deliberately paused signal request was canceled as `net::ERR_ABORTED`; only the replacement response rendered; page 2 produced `60/60` unique card ids;
- a disposable Free session showed tier `free` and returned `Cache-Control: private, no-store`, `X-Radar-Cache: bypass`, and no public marker for signals/counts. The synthetic user/session and browser cookie were removed after the proof.

These measurements validate Phase 3 request ordering and rendering only. Redis, Nginx microcache, Gunicorn sizing, and 1,000-5,000 in-flight evidence remain the Phase 4 gate.

## Crawl Automation

Primary daily job:

- `radar-bds-crawl.timer`
- runs Facebook-first daily crawl using admin `daily_limit` per broker profile,
- reprocesses,
- downloads/backfills images,
- does not call external LLM verification/enrichment,
- pushes VIP notifications,
- prewarms dashboard cache.

Secondary job:

- `radar-bds-guland-crawl.timer`, or fallback deploy-user crontab at 23:15,
- runs `radar.py crawl-daily --source guland --no-alert`,
- uses the same crawl lock so it does not overlap with the primary job.

BatDongSan is legacy/disabled. Do not add it to production schedules without explicit approval.

## Logs And Health

First places to inspect:

```bash
cd /opt/radar-bds/current
tail -n 160 logs/crawl-daily.log
tail -n 160 logs/guland-crawl.log
systemctl status radar-bds.service --no-pager
systemctl status radar-bds-crawl.service --no-pager
systemctl status radar-bds-guland-crawl.service --no-pager
systemctl list-timers radar-bds-crawl.timer radar-bds-guland-crawl.timer --no-pager
```

Admin crawl health should surface the latest timer/service failure and point to `logs/crawl-daily.log`.

## Local Production Sync

Pull production DB to local:

```powershell
.\scripts\sync_prod_to_local.ps1
```

Pull DB plus missing images:

```powershell
.\scripts\sync_prod_to_local.ps1 -SyncImages
```

This is production -> local only. It creates a dump on the VPS, downloads it,
backs up current local DB, then restores into the local `radar_bds` selected by
`.env.local`. If the production app DB role lacks full dump privileges, the
script retries on the VPS with the local `postgres` role.

## Guland Historical Reconciliation

The bounded reconciliation command checks only currently displayable Guland
listings, with unknown or stale source checks first. Dry-run is the default and
does not write lifecycle, raw listing, history, or reprocess data:

```powershell
& $py -X utf8 radar.py guland-reconcile --limit 100
```

Review the bounded counts before considering apply. Production apply always
requires explicit user approval:

```powershell
& $py -X utf8 radar.py guland-reconcile --limit 100 --apply
```

Apply backfills deterministic metadata, uses two explicit removal
confirmations before hiding a listing, refreshes only confirmed price changes,
and runs targeted reprocess for those changed raw rows. It never fabricates
missing historical prices. Keep the limit between 1 and 200.

## Guland Zero-ready Image Recovery

The image repair command treats a listing as ready only when it has a usable
original and, in S3 mode, the matching WebP thumbnail. It therefore includes
rows that already exist but are `NULL`, `NOT_FOUND`, or point to a missing S3
object:

```powershell
& $py -X utf8 radar.py guland-image-backfill --limit 50
```

Dry-run is the default and may perform bounded read-only source checks. Review
`zero_ready_total`, `zero_ready_targets`, `live_recoverable_targets`,
`missing_original_rows`, and `missing_thumbnail_rows` before apply.

Production apply always requires explicit user approval:

```powershell
& $py -X utf8 radar.py guland-image-backfill --limit 50 --apply
```

Apply writes changed raw snapshots to `raw_listing_revisions`, resets only
live-confirmed `NOT_FOUND` URLs or missing originals, and invokes targeted
downloads for the selected listing IDs. New image objects include image-row
identity and an asset fingerprint, so Facebook revisions cannot overwrite the
same immutable S3 key.

## Guland Publisher Activity Backfill

Before crawl or backfill, `/etc/radar-bds/radar.env` must contain a private
`GULAND_PUBLISHER_KEY_SECRET` with at least 32 random characters. Never print
or copy the value into logs, checkpoints, JSON output, source control, or an
admin response.

The command only checks Guland listings that are active/displayable, plus
currently configured source cards whose publisher status still needs checking.
Dry-run is the default:

```bash
set -a
. /etc/radar-bds/radar.env
set +a
cd /opt/radar-bds/current
/opt/radar-bds/.venv/bin/python -X utf8 radar.py guland-publisher-backfill --limit 100
```

Review candidate, live, identified/unknown/unreachable, and estimated class
counts. Output must contain aggregates only. Production apply is a separate
data mutation and always requires explicit approval:

```bash
/opt/radar-bds/.venv/bin/python -X utf8 radar.py guland-publisher-backfill --limit 100 --apply
```

Apply checkpoints to `.local/guland-publisher-backfill/<run-id>.json`, resumes
idempotently, updates publisher evidence/activity, and runs targeted listing
normalization only. Historical new-listing activity is reconstructed from the
preserved `first_seen_at`; the command does not rerun valuation or change
first-seen, posted, price-update, price history, images, coordinates, map rows,
or valuation rows.

After an approved apply, verify counts and payload redaction:

```bash
curl -fsS "http://127.0.0.1:5000/api/dashboard?source=guland&cache_refresh=1" >/dev/null
curl -fsS "http://127.0.0.1:5000/api/signals?source=guland&page=1&limit=3" >/dev/null
curl -fsS "http://127.0.0.1:5000/api/map-listings?mode=signals&source=guland" >/dev/null
```

Deployment may create the idempotent tables and deploy the code, but it must
not automatically run publisher backfill `--apply`.

## Cache Prewarm

With `RADAR_PUBLIC_CACHE_ENABLED=1`, crawl/reprocess publication automatically mirrors versions and warms the bounded route file. Manual status-only prewarm for diagnosis:

```bash
sudo -u radar bash -lc 'set -a; . /etc/radar-bds/radar.env; set +a; cd /opt/radar-bds/current && /opt/radar-bds/.venv/bin/python -X utf8 -c "from services.public_prewarm import prewarm_configured_routes; print(prewarm_configured_routes())"'
```

Never add authenticated, admin, checkout/order, saved-listing, arbitrary-host, fragment, credential, or user-specific URLs to the warm-route file.

## Thu Dau Mot Digital Map Commerce

The paid package is runtime data, not a deploy artifact. Keep it outside the
repository and public static folders at:

```text
/var/lib/radar-bds/products/thu-dau-mot-map-bundle/1.0/
```

The exact production setup and rollback commands are in
`deployment/ubuntu24/README.md`. Keep
`DIGITAL_PRODUCT_SALES_ENABLED=0` while installing or validating the package.
Do not enable sales until the ZIP, sibling `MANIFEST.json`, PayOS credentials,
cookie secret, schema, webhook registration, and service smoke all pass.

Reconcile one existing order without printing its recovery token, QR content,
signature, credentials, or bank-transfer payload:

```bash
cd /opt/radar-bds/current
sudo -u radar bash -lc 'set -a; source /etc/radar-bds/radar.env; set +a; /opt/radar-bds/.venv/bin/python -X utf8 scripts/reconcile_digital_product_order.py --public-id <32-lowercase-hex-public-id>'
```

The command prints only the public ID, local status, remote status, changed
flag, and the applicable expiry. It may reconcile an existing `pending` or
`payment_review` order, including a `pending` order that expires during that
check or an unpaid order already marked `expired` by status polling. It does
not query PayOS again for `paid`, `cancelled`, or an expired order that already
contains a paid grant.

## Production Smoke Checklist

```bash
python3 --version
sudo systemctl status radar-bds.service --no-pager
curl -fsS https://radarbds.vn/robots.txt >/dev/null
curl -fsS https://radarbds.vn/sitemap.xml >/dev/null
curl -fsS https://radarbds.vn/api/dashboard >/dev/null
curl -fsS "https://radarbds.vn/api/signals?page=1&limit=3" >/dev/null
```

## What Not To Do

- Do not print `.env`, Telegram tokens, Supabase passwords, or admin cookies.
- Do not commit runtime images, dumps, logs, reports, or backups.
- Do not run destructive DB cleanup without an explicit `--apply` decision and a backup.
- Do not run full production reprocess casually after UI-only changes.
- Do not move Guland or any secondary source ahead of Facebook in daily crawl.
