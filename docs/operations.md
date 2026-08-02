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
runs production deploy. On 2026-08-01 the VPS checkout origin was normalized to
`https://github.com/kieucuong01/RadarBDS.git` after the old
`github.com-radarbds` hostname stopped resolving; a live fetch proved the new
origin and production HEAD matched `origin/main`. The local `git bundle`
fallback remains the guarded recovery path if a future GitHub fetch fails.

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

All three object names must be non-null and the version table must contain `market`, `signals`, and `listings`. `db.schema.init_schema()` commits these required objects before best-effort legacy migrations; if an optional migration then hits `insufficient_privilege`, it rolls back that optional transaction only.

If compare reports only `order_mismatch` for Guland with identical IDs and fields, inspect `price_updated_at`, `first_seen_at`, and `crawled_at` string formats before changing indexes. Mixed space/`T` separators are present in production, and Phase 1 must preserve the existing lexical `listing_activity_at_sql()` order. Do not sort `newest` solely by normalized `signal_card_read_model.activity_at` unless that user-visible behavior change has its own migration and acceptance test.

This rollout proves parity and normal-load latency only. Do not claim the 1,000-5,000 simultaneous in-flight request objective until the later pooling/cache/Nginx phases and staged load gates pass.

## All-Listings Read Model Rollout And Rollback

`/api/listings` shares `signal_card_read_model` but has independent readiness, cache versioning, and rollback. Deploy with the route off even though its code default is enabled. Set this in `/etc/radar-bds/radar.env` before the first deployment:

```bash
RADAR_LISTING_READ_MODEL_ENABLED=0
```

After the code is active, run the full refresh and both safe-metadata parity checks as the runtime user. The command exits nonzero on either signal or all-listings mismatch and never logs descriptions, URLs, phone numbers, cookies, or credentials:

```bash
cd /opt/radar-bds/current
set -a
. /etc/radar-bds/radar.env
set +a
/opt/radar-bds/.venv/bin/python -X utf8 radar.py signal-read-model --refresh --compare --compare-listings --limit 200
/opt/radar-bds/.venv/bin/python -X utf8 -c 'from services.public_cache import get_current_dataset_versions; print(get_current_dataset_versions(("signals","listings","market")))'
```

Require both comparisons to report `difference_count=0`, a positive durable `listings` version, and a matching Redis mirror. Redis mirror/prewarm errors are separate from the committed PostgreSQL refresh and must still be resolved before enabling the route. Route dispatch rechecks PostgreSQL readiness through a separate one-second process cache and ignores a divergent Redis mirror. Configured publication passes the just-committed version; standalone prewarm reads the durable version itself. Either mode skips `/api/listings` while a flag is disabled or durable readiness is zero, so it never prewarms the known slow legacy query.

Then set `RADAR_LISTING_READ_MODEL_ENABLED=1`, restart, prewarm once, and measure the canonical route without printing its body:

```bash
sudo systemctl restart radar-bds.service
sudo systemctl is-active radar-bds.service
sudo -u radar bash -lc 'set -a; . /etc/radar-bds/radar.env; set +a; cd /opt/radar-bds/current && /opt/radar-bds/.venv/bin/python -X utf8 -c "from services.public_prewarm import prewarm_configured_routes; print(prewarm_configured_routes())"'
/opt/radar-bds/.venv/bin/python -X utf8 scripts/benchmark_public_read_path.py --base-url http://127.0.0.1:5000 --repeat 5 --path '/api/listings?date_range=3m&sort_by=date&sort_dir=desc&page=1&limit=50'
curl -sS -D - -o /dev/null 'http://127.0.0.1:5000/api/listings?date_range=3m&sort_by=date&sort_dir=desc&page=1&limit=50'
```

From Windows, run `scripts/verify_public_cache.ps1` against the public domain. It must prove guest HIT plus cookie/Authorization bypass, private/no-store headers, and recursive redaction for the listings response. Browser smoke must cover desktop and mobile Tin rao activation, first visible rows, filters, each sort, page append, full image arrays/modal, and no duplicate first-page request. Record first-content time from browser navigation/network evidence, not a unit test.

Route-only rollback is data-preserving: set `RADAR_LISTING_READ_MODEL_ENABLED=0`, restart `radar-bds.service`, and use a VPS-local `cache_refresh=1` probe or temporarily disable the application cache for the diagnostic so an old equivalent cached payload cannot hide the legacy dispatch. Keep the projection and `listings` version. This rollback must not disable `/api/signals`, `/api/counts`, `/api/dashboard`, or signals-mode Maps. For a privacy/key concern, also remove or disable the exact Nginx `/api/listings` cache location and reload Nginx before further public traffic.

Release evidence is incomplete unless it records: commit SHA, service status, durable and Redis `listings` version, full-refresh row count/duration, parity difference count, five VPS-local cold/warm samples and cold p95, public HIT p95, browser first-content time, cache/privacy headers, redaction checks, and the route-only rollback probe.

### Production follow-up on 2026-08-02

The all-listings projection and application path are active in production, but the edge/capacity rollout is intentionally still open. Preserve these facts for the next agent instead of repeating the expensive audits:

- deployed feature commits include `d5c7e3f` (post-load/hover Maps and Tin rao asset warm-up) and `c4705c1` (`/api/counts` metrics from the shared projection);
- the published projection contained 23,059 rows; durable PostgreSQL and Redis mirrors matched at `signals=5`, `listings=1`, `market=1` at verification time;
- full local parity completed with 36 signal cases and 76 listing cases at limit 200, all with `difference_count=0`; production completed an eight-case, limit-50 sampled parity smoke with zero differences. The full production Cartesian comparison was stopped because the legacy CTE path repeatedly exceeded the bounded audit window, so it must not be reported as complete;
- production VPS-local `/api/listings` forced-loader samples were 101-173 ms cold and 116-154 ms warm. Public warm samples were 65-145 ms. A real Admin browser click showed the Tin rao tab active in 2.6 ms, skeletons in 6.7 ms, and 50 real cards in 332.2 ms; its `/api/listings` request took 233.5 ms;
- before `d5c7e3f`, a cold first Maps click kept the dashboard visible for about 2,908 ms while CSS, module code, and Leaflet loaded. After post-load idle warm-up, the same production interaction opened and completed in 55 ms. Warm-up starts only after `window.load`/idle, or on launcher hover/focus, so it does not block the initial homepage render;
- before `c4705c1`, a real Admin `/api/counts` request took 22,477 ms and left the Săn Deal badge at the initial `0`. After the fix, the browser request took 77.9 ms and five forced VPS-local probes took 54-98 ms. Initial badges render an unknown placeholder until the deferred count arrives; do not reintroduce a false zero placeholder;
- the 2026-08-02 ACL maintenance completed the origin install. `/etc/nginx/sites-available/radar-bds.conf` now has the exact `/api/listings` public-cache location, `/etc/radar-bds/radar.env` contains exactly one `RADAR_LISTING_READ_MODEL_ENABLED=1`, and the ignored `.env.local` override was moved to the timestamped recovery directory `/tmp/radar-perf-20260802T142202Z`. The pre-change Nginx and base-env SHA-256 values were `0236d648c3f52682ae8a84b21d792c72971bbccaa3a6a907c974d88fd867e671` and `451604d2c638a9b0ee6fdfa3e5b88100fa41c285def4aebf4d58429632dfba8e`;
- origin prewarm succeeded for all seven configured routes. Repeated HTTPS origin probes changed `/api/listings` from `MISS` to `HIT`, and the public `scripts/verify_public_cache.ps1` passed all five path classes: guest `HIT`, cookie and Authorization `BYPASS`, private/no-store enforcement, recursive redaction, hidden internal marker, and `listings` version `1`;
- the route-dispatch rollback drill is complete and data-preserving. With `RADAR_LISTING_READ_MODEL_ENABLED=0`, a VPS-local `cache_refresh=1` legacy probe returned HTTP 200 in 51.737 seconds. The mandatory restore set the flag back to `1`, restarted the service, prewarmed seven of seven routes, and returned the same read-model route in 91 ms. PostgreSQL and Redis versions remained matched at `signals=5`, `listings=1`, `market=1`; `/api/signals`, `/api/counts`, `/api/dashboard`, Maps, and stored data were not disabled or changed.

The user-visible hot paths and VPS origin phase are therefore fixed and deployed. Revoke the temporary ACL after inspection with `sudo setfacl -x u:deploy /etc/nginx/sites-available/radar-bds.conf /etc/radar-bds/radar.env`. Remaining work is Cloudflare/Vietnix DNS cutover, the documented distributed 100 -> 500 -> 1,000 -> 5,000 gates, and optional full production Cartesian parity if a longer maintenance window is approved. Do not claim the 5,000-concurrent public objective before the CDN gates pass.

## Shared Public Cache And PostgreSQL Pool Rollout

Phase 2 application code is safe to deploy before Redis. Current production, after the completed Phase 4 safety drills, uses:

```bash
RADAR_DB_POOL_MIN=1
RADAR_DB_POOL_MAX=4
RADAR_DB_POOL_TIMEOUT_SECONDS=1.0
RADAR_PUBLIC_CACHE_ENABLED=1
RADAR_REDIS_URL=redis://127.0.0.1:6379/0
RADAR_CACHE_SCHEMA_VERSION=1
RADAR_PUBLIC_CACHE_FRESH_SECONDS=60
RADAR_PUBLIC_CACHE_STALE_SECONDS=86400
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

For a new environment, do not enable the cache flag until Phase 4 has installed a local-only Redis service and these checks pass:

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
sudo -u radar bash -lc 'set -a; . /etc/radar-bds/radar.env; set +a; cd /opt/radar-bds/current && /opt/radar-bds/.venv/bin/python -X utf8 -c "from services.public_cache import get_current_dataset_versions; print(get_current_dataset_versions((\"signals\",\"listings\",\"market\")))"'
curl -sS -D - -o /dev/null 'http://127.0.0.1:5000/api/signals?include_total=0&limit=30&page=1&sort=newest'
curl -sS -D - -o /dev/null 'http://127.0.0.1:5000/api/listings?date_range=3m&sort_by=date&sort_dir=desc&page=1&limit=50'
curl -sS -D - -o /dev/null 'http://127.0.0.1:5000/api/counts'
curl -sS -D - -o /dev/null 'http://127.0.0.1:5000/api/dashboard'
```

`X-Radar-Cache` is `miss`, `hit`, `stale`, or `bypass`; `Server-Timing` reports cache status and loader duration. Only anonymous guest responses may include `X-Radar-Public-Cache: 1` plus the public 15-second policy. Repeat with a harmless `Cookie: radar_session=invalid-probe` and with an `Authorization` header; both must return `Cache-Control: private, no-store` and no public marker. Do not log real session/admin values.

Committed read-model publication follows this order: DB refresh/version commit, Redis version mirror, then the seven allowlisted warm routes from `config/public_cache_warm_routes.json`. Publication output keeps DB `status=ok` and reports mirror/prewarm state separately under `cache`. Prewarm sends no cookie/authorization, reads at most 2 MiB, logs status only, and skips the configured listings route until both read-model flags and a positive committed/durable `listings` version are present.

Rollback order:

1. For any privacy/key/version issue, set `RADAR_PUBLIC_CACHE_ENABLED=0` and restart `radar-bds.service` immediately.
2. Verify all three endpoints return `X-Radar-Cache: bypass` and correct tier redaction.
3. Redis may then be stopped or repaired without affecting PostgreSQL truth.
4. Keep the pool limits in place. Roll back pool code only by deploying the prior commit; never compensate by raising PostgreSQL connection limits during an incident.

The production Phase 2 runtime gate passed on 2026-08-01: real Redis DB 15 integration, shared cache isolation, Redis-stop/recovery at 100 VUs, bounded DB sessions, and cache flags `0` and `1` were all exercised. This is environment-specific evidence, not permission to skip the gate elsewhere.

## Signal-First Frontend Runtime

The Signals-tab request contract is:

```text
canonical filter snapshot -> /api/signals immediately -> first card chunk
                                                   \-> /api/counts after settle/idle
```

`/api/dashboard` is intentionally absent while the Signals tab stays active. It is still used when a filter changes on a non-Signals tab. `core.js` uses the later `homepage-counts-20260802` cache-busting version; `filter_runtime.js`, `filters.js`, `signals.js`, and `web_vitals.js` retain `homepage-perf-20260801`. Every changed immutable asset must receive an explicit version bump on later edits.

Keep these browser-visible safeguards together during incident diagnosis: AbortController per request scope, canonical snapshot check before deferred counts, signal response run id, render-chunk sequence, and listing-id deduplication. A stale response in Network is acceptable only when it is visibly canceled and cannot mutate the final cards.

The Săn Deal badge and Maps click have an additional regression gate:

1. Keep `/api/signals?...&include_total=0` as the first dynamic request.
2. Confirm the later `/api/counts` response contains numeric `stats.signals`, and both `#badgeSignals` and `#mobileBadgeSignals` show that value.
3. Click `Xem trên Maps` from the Signals tab. `/api/map-listings?...&mode=signals` must complete from `signal_card_read_model`; its SQL must contain neither `latest_valuation` nor `latest_shadow_valuation`.
4. Confirm the map status becomes `aria-busy=false`, one Leaflet Canvas exists, no SVG marker surface is created, and the desktop panel/mobile sheet remains interactive.
5. After a production deploy that changes the counts payload, refresh/publish the signals read model once so the durable and Redis `signals` versions advance together; otherwise the old cached counts payload may remain valid under the previous version key.
6. Query one map item as Guest/Free/VIP and confirm any phone embedded in `title` is redacted; admin may retain the original title. With `RADAR_SIGNAL_READ_MODEL_ENABLED=0`, confirm `stats.signals` is still the legacy exact count rather than `0`.

Focused verification:

```powershell
& $py -X utf8 -m pytest `
  tests\test_listing_map_service.py `
  tests\test_listing_map_api.py `
  tests\test_listing_map_js.py `
  tests\test_listing_map_ui.py `
  tests\test_market_data_performance.py -q
node --check static\js\main\listing_map.js
```

Controlled local browser evidence from 2026-08-01 (cache disabled, local PostgreSQL, not a capacity claim):

- desktop HTML TTFB `4.7 ms`; first signals `321.8 ms`; `radar-first-signal-cards` `337.1 ms`; counts began at `519.4 ms`; LCP `528 ms`; CLS `0.0015`;
- mobile `390x844`: HTML TTFB `45.8 ms`; first signals `277.0 ms`; first cards `299.9 ms`; counts began at `517.4 ms`; LCP `580 ms`; CLS `0.00023`; the tested interaction produced no event at the 40 ms observer threshold, so the controlled sample is `<40 ms`;
- mobile rendered one card column with zero horizontal overflow; the first trace contained signals then counts and no dashboard;
- a deliberately paused signal request was canceled as `net::ERR_ABORTED`; only the replacement response rendered; page 2 produced `60/60` unique card ids;
- a disposable Free session showed tier `free` and returned `Cache-Control: private, no-store`, `X-Radar-Cache: bypass`, and no public marker for signals/counts. The synthetic user/session and browser cookie were removed after the proof.

These measurements validate Phase 3 request ordering and rendering only. The following section records the later Phase 4 infrastructure and capacity evidence; neither section alone is permission to claim the still-unmet 1,000-5,000 external gate.

## Production Public-Read Capacity Runbook

This is the production truth recorded on 2026-08-01. The implementation is deployed, cache/privacy/failure behavior is verified, and the highest passing external stages are recorded below. The requested 1,000-5,000 acceptance target is **not** complete; do not round the highest passing stage upward.

### Active capacity contract

| Layer | Active production setting | Ownership |
|---|---|---|
| Nginx | exact guest cache for `/`, `/api/signals`, `/api/counts`, `/api/dashboard`; TTL 15 s; inactive 24 h; 512 MB zone; lock/background update/stale-on-error | absorbs repeated/common public concurrency; never caches session/auth/admin/error/`Set-Cookie` responses |
| TLS accept queue | IPv4 `backlog=8192`; `worker_connections=4096`; `multi_accept on`; kernel `somaxconn=8192`, `tcp_max_syn_backlog=8192` | accepts bursts without scaling Flask/DB work one-for-one |
| Gunicorn | 3 workers x 4 threads; timeout 45 s; graceful 30 s; keepalive 5 s; max requests 2,000 + jitter 200; `LimitNOFILE=65536` | bounded origin request concurrency |
| Redis | loopback only; persistence off; 256 MB; `allkeys-lru`; max clients 256 | disposable shared response/version cache, never source of truth |
| Application cache | fresh 60 s; stale 86,400 s; lock 5 s; wait 250 ms; at most 2 uncached loaders/process | protects slow/cold reads and retains a stale dashboard across idle periods |
| PostgreSQL | pool min/max 1/4 per worker; acquire timeout 1 s | at most 12 normal web connections; crawl/reprocess is accounted separately |

The 45-second origin timeout is still the deployed bound but is no longer required by the dashboard signal count. Before commit `4ad6e79`, a forced dashboard cache miss rebuilt latest valuation history and repeatedly took about 27.49 seconds. After that commit, `stats.signals` counts the already-published signal read model with the exact feed filters: five production `cache_refresh=1` probes took `195`, `147`, `138`, `158`, and `158` ms, all returned `signals=1367` and `total=7939`, and `/api/signals?page=1&limit=1` independently returned `total=1367`. Keep the timeout change, if any, as a separate measured operational change. The 24-hour Nginx inactive window and 86,400-second application stale window remain failure protection, not compensation for a known 27-second SQL path.

### Install, verify, observe, and rollback

Normal deploy does not mutate system Redis/Nginx/sysctl settings. Installation is an explicit root operation and creates a dated backup:

```bash
cd /opt/radar-bds/current
sudo ./scripts/install_performance_infra.sh install
```

The installer validates a temporary Redis instance through a Unix socket before activation, validates Nginx syntax before reload, and traps nested-function failures for automatic rollback. A missing vendor `/etc/redis/redis.conf` is restored with `--force-confmiss`; never hand-create an incomplete vendor file.

From Windows, verify public cache/privacy/freshness without printing bodies, cookies, or credentials:

```powershell
.\scripts\verify_public_cache.ps1 -BaseUrl "https://radarbds.vn"
```

Expected for all five allowlisted public path classes: repeated guest request `HIT`; fake cookie and Bearer request `BYPASS` plus `private, no-store`; no source URL, original URL, phone, seller, or embedded phone fields. Useful host checks:

```bash
systemctl is-active nginx radar-bds redis-server postgresql
redis-cli -h 127.0.0.1 PING
redis-cli -h 127.0.0.1 CONFIG GET save appendonly maxmemory maxmemory-policy maxclients
ss -lnt '( sport = :443 or sport = :6379 or sport = :5000 )'
systemctl show radar-bds.service -p LimitNOFILE
sysctl net.core.somaxconn net.ipv4.tcp_max_syn_backlog
```

For an application privacy/key/version incident, first set `RADAR_PUBLIC_CACHE_ENABLED=0`, restart `radar-bds.service`, and verify private/bypass headers. Full infrastructure rollback for the latest production install is:

```bash
sudo /opt/radar-bds/current/scripts/install_performance_infra.sh rollback /var/backups/radar-bds-performance/20260801-111210
```

The corresponding environment snapshots are `/etc/radar-bds/radar.env.before-phase4-20260801-103830` and `/etc/radar-bds/radar.env.before-stale-20260801-111210`. Before using an older backup on a later deployment, inspect its manifest and current files; do not assume paths remain current.

### Measured production evidence

External tests used browser-style compression (`Accept-Encoding: gzip`). The first uncompressed 100-VU run transferred 383 MB and was rejected as a harness error; it is not a capacity result.

| External scenario | Result | p95 / p99 | Edge behavior and origin state |
|---|---:|---:|---|
| normal homepage, 100 VUs | pass, 0% errors, 21,752 requests | 192.64 / 656.77 ms | 21,715 HIT, 2 MISS, 35 STALE; DB app sessions 4 |
| mixed 50-key filters, 100 VUs | pass, 0% errors, 23,722 requests | 29.02 / 79.72 ms | 22,796 HIT, 726 STALE |
| mixed 50-key filters, 500 VUs | pass, 0.12% errors, 99,510 requests | 248.33 / 869 ms | 98,248 HIT, 938 STALE; DB app sessions <=7 |
| normal homepage, 500 VUs | fail gate, 0.75% errors | 8.49 / 25.56 s | origin stayed stable; after backlog fix kernel listen drops did not increase |
| mixed 50-key filters, 1,000 VUs | fail gate, 0.83% errors | 2.85 / 8.36 s | origin stayed stable; DB app sessions 6-7; Redis had no rejected clients/evictions |
| distributed default, 100 VUs (`30698414443`) | fail latency gate, 0% HTTP errors, 100% checks, 11,096 requests | 2.24 / 3.10 s | GitHub-hosted path delivered 143 MB at ~1.2 MB/s; CPU peaked ~14%; DB 3/0 active; Redis/listen counters/services stayed healthy |
| Cloudflare default, 100 VUs (`30756753673`) | pass, 16/35,178 edge errors (0.0455%) | 18.17 / 34.15 ms | 34,063 HIT, 1,096 stale/updating, 3 MISS; no CDN bypass/unknown responses |
| Cloudflare mixed, 100 VUs (`30756753673`) | pass, 4/35,991 edge errors (0.0111%) | 13.32 / 45.28 ms | 33,682 HIT, 2,005 stale/updating; no CDN bypass/unknown responses |
| all-listings Maps cold query, one VPS-local request | legacy timed out with 0 bytes after 20 s; read-model candidate 276.2 ms | same default filter total `7,968` | legacy stayed in materialized latest-valuation CTE; candidate used durable `listings:1`, returned the same feed total, and did not change the running service |
| forced dashboard cache bypass after `4ad6e79` | pass, 5/5 HTTP 200, exact signal-feed parity | 138-195 ms per request | `X-Radar-Cache: bypass`; `signals=1367` matched `/api/signals`; no request-time latest-valuation CTE |

The Redis-stop drill at 100 VUs passed with 0% errors, p95 199.98 ms, p99 532.45 ms, and 10,846 requests while Redis was unavailable for 21 seconds. Public responses remained `HIT`/`STALE`, PostgreSQL stayed at 4 app sessions/1 active, and Redis recovered with `PONG` and prewarm. The full rollback/reinstall drill also passed.

The IPv4 listen backlog was raised from the Linux/Nginx default queue to 8,192 after the first 500-VU test showed cumulative listen overflows. On retest, both kernel counters stayed exactly unchanged while the client still saw latency/timeouts, isolating the remaining bottleneck to the single direct-origin/network-generator path rather than new origin accept drops.

Evidence is retained locally at `C:\tmp\radar-phase4-evidence-20260801-172749`, including `public-cache-verification-final.txt`, `k6-default-100-gzip.*`, `k6-mixed-500.*`, `k6-mixed-1000.*`, `k6-redis-drill-100.*`, and host observation logs. Runtime evidence stays uncommitted.

Distributed workflow run `30698414443` stopped all dependent stages after `default-100`, as designed. All 33,288 content/cache checks passed and no HTTP request failed; only the unchanged latency thresholds crossed. Local external compressed tests top out around 2.2 MB/s, while `k6-vps-diagnostic-500` on the same host delivered about 8 MB/s at p95 665 ms. This is the decision evidence for CDN/origin shielding, not permission to relax the p95/p99 gates.

The paired 30-minute observer retained 152 samples in `distributed-20260801-1848`. It showed no service restart, Redis rejection/eviction, PostgreSQL saturation, or new listen drop during the load stage. The observer nevertheless ended `ABORT` after the workflow had already stopped because its final three samples recorded nonzero swap-in values `8`, `8`, and `16`, exactly triggering the fail-closed sustained-swap rule. The last sample still had about 2.23 GB available memory, CPU 4%, PostgreSQL 0/3 active/total, and all four services active. A later idle diagnostic found about 2.16 GB available memory, 176 MB swap allocated, `vm.swappiness=60`, and zero swap-in/out on every live interval after the initial `vmstat` since-boot row. This does not turn the failed observer into a pass; require a clean observer alongside the post-CDN rerun and diagnose fresh sustained swap if it returns.

Cloudflare is now the active public edge. Authoritative NS are `ara.ns.cloudflare.com` and `mcgrory.ns.cloudflare.com`; public A answers are Cloudflare anycast rather than `103.90.226.230`. Dashboard evidence for `30756753673` showed the two 100-VU stages served predominantly as HIT/updating from Cloudflare; CDN-required verification and the aggregator rejected neither bypass nor unknown traffic. Keep the preserved Vietnix record snapshot and the paired Cloudflare design/rollback spec as the rollback source of truth. Do not infer 500-5,000 capacity from the active proxy alone.

The first Cloudflare default-500 attempt was cancelled safely. The observer reached six consecutive CPU samples above 90% from 23:40:19 to 23:41:19 GMT+7, but the GitHub runner was still sleeping until 23:41:24 and k6 did not begin iterations until 23:41:32. Cloudflare Security Analytics isolated 52 dynamic requests from one Vietnam Safari client between 23:39:37 and 23:40:55, including all-listings Maps at 23:40:16. PostgreSQL backends created at 23:40:06/23:40:15 then consumed the CPU. A controlled single-request reproduction confirmed `/api/map-listings?mode=all&date_range=3m` remained in the legacy latest-valuation CTE for more than 20 seconds. Treat the cancelled 500 stage and all skipped higher stages as no result; deploy/verify the read-model Maps path, then start again from default-100 with a clean observer.

Post-deploy run `30759069065` proved the corrected default-100 gate: 35,100 requests, p95/p99 16.53/28.43 ms, failure rate 0.037%, and check rate 99.973%. The observer then aborted during mixed-100 after three live `vmstat` samples reported only 8/4/4 KB/s swap-in. At abort, about 1.59 GB memory remained available, CPU was 29%, PostgreSQL was 0/5 active/total, Redis used 8.45 MB, all services were active, and no restart, Redis rejection/eviction, listen-drop increase, or recent service error occurred. Mixed-100 was cancelled and all 500+ stages were skipped, so only default-100 is a capacity pass from that run.

The observer now treats memory pressure explicitly: abort immediately below 512 MB available memory, or after aggregate swap I/O reaches at least 1,024 KB/s for three samples. Single-digit KB/s paging with ample available memory remains recorded but no longer aborts. This keeps a fail-closed low-memory/sustained-swap guard without misclassifying negligible background page-ins as capacity failure.

Cloudflare run `30759522225` subsequently passed `default-100`, `mixed-100`, and `default-500`; the production observer remained clean through those executed load stages. Its `mixed-500` job is **not a capacity failure or pass**: k6 stopped inside `setup()` after the default 60-second setup limit, having issued only 258 of the 300 serial prewarm requests and zero VU iterations/checks. The workflow correctly skipped 1,000 and 5,000. Commit `41c69b3` therefore proves the common homepage path through 500 VUs and the mixed path through 100 VUs only. The harness now gives the fixed 50-key prewarm a bounded five-minute setup window and makes every mixed shard wait for the same post-prewarm VU epoch. Aggregation requires all configured VUs to record their first iteration within the ten-second synchronized-start window, preventing a staggered run from being mislabeled as concurrent capacity. Repeat the full serial gates with a fresh paired observer before raising the boundary.

Production browser smoke after `4ad6e79` covered desktop `1280x720` and mobile `390x844`. Both rendered 30 signal cards. Removing Tân An changed the first card set and produced one new `/api/signals` plus one `/api/counts` request, with no `/api/dashboard` request; the mobile snapshot recorded `13/14` wards and a one-column layout without horizontal overflow. Application/filter/card runtime logs were clean. Playwright did report the existing GA collector requests to `analytics.google.com`, `www.google.com`, and `stats.g.doubleclick.net` being blocked by the current CSP; treat those third-party telemetry messages separately from application regressions.

### Honest capacity boundary and next architecture

The current single 2-vCPU/4-GB origin plus Cloudflare edge has proven cache collapse, privacy isolation, Redis failure recovery, bounded DB sessions, CDN-required default/mixed 100 VUs, and the earlier origin-cache mixed-filter 500-VU stage. It has **not** proven the 500-VU Cloudflare stage, the 1,000-5,000 external acceptance target, 5,000 unique cold filters, sustained 5,000 RPS, or high availability. The first Cloudflare 500 attempt was cancelled because the observer detected an independent production SQL hotspot before k6 began.

The next capacity phase must keep the active guest-only Cloudflare contract, keep authenticated traffic private, deploy and smoke the all-listings Maps read path, then repeat 100 -> 500 -> 1,000 -> 5,000 serial gates. The production verifier must continue to pass with `-RequireCdn` before the capacity branch is pushed again:

```powershell
.\scripts\verify_public_cache.ps1 -BaseUrl "https://radarbds.vn" -RequireCdn
```

That mode requires `CF-Ray`, guest Cloudflare HIT/stale evidence, private Cloudflare BYPASS/DYNAMIC, origin `private, no-store`, redaction, and the existing Nginx marker contract. Do not compensate by increasing Gunicorn workers, PostgreSQL connections, Redis memory, or timeouts.

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
