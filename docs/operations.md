# Operations And Deploy

Use this for VPS deploy, production smoke checks, DB sync, crawl logs, and one-off production maintenance.

## Environments

| Environment | Purpose | Notes |
|---|---|---|
| Local Windows | Development and safe reprocess/audit | Python 3.12, installed PostgreSQL 18 service `postgresql-x64-18`, pgAdmin4 |
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
- preserves production-only `data/facebook_profiles.json`,
- allows runtime `data/raw_backup.json` to stay dirty on the VPS,
- auto-archives a small allowlist of known temporary audit/report files from the VPS checkout to `/tmp/radar-bds-deploy-known-temp-*.tgz`,
- restarts `radar-bds.service`,
- smokes `/api/dashboard` and `/api/signals`,
- prewarms dashboard cache,
- installs/falls back Guland secondary scheduling when needed.

The archive cleanup is intentionally narrow. If any dirty production file remains
outside the built-in allowlist, deploy must still stop and report the exact file list.

Deploy does not automatically run a full production reprocess for every code change. For parser, dedup, valuation, schema, or quality-gate changes, run an explicit reprocess after deploy.

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

This is production -> local only. It creates a dump on the VPS, downloads it, backs up current local DB, then restores into local `radar_bds`.
Local restore target is the installed PostgreSQL 18 service on `127.0.0.1:5432`.

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
check. It does not query PayOS again for an already terminal local order.

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
