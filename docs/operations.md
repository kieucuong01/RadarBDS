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
RADAR_SIGNAL_CACHE_TTL_SECONDS=60
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

Use after deploy and after crawl/reprocess:

```bash
curl -fsS "http://127.0.0.1:5000/api/dashboard?cache_refresh=1" >/dev/null
curl -fsS "http://127.0.0.1:5000/api/signals?page=1&limit=3" >/dev/null
```

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
