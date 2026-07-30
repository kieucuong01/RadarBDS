# Development Commands

Use UTF-8 mode on Windows because the project contains Vietnamese text.
This is a command cookbook. For deploy decisions, crawl health, and production
runbooks, read `docs/operations.md` first.

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
```

## App and DB

Local PostgreSQL setup:

Normal local development uses the installed PostgreSQL 18 Windows service,
managed through pgAdmin4:

- service: `postgresql-x64-18`
- host/port: `127.0.0.1:5432`
- database: `radar_bds`
- user: `postgres`
- password: keep it in local `.env`; do not paste it into docs, commits, or chat
- pgAdmin registration: host `127.0.0.1`, port `5432`, maintenance DB `radar_bds`

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"

Get-Service postgresql-x64-18
# .env should set DATABASE_URL=postgresql://postgres:<local-password>@127.0.0.1:5432/radar_bds
& $py -X utf8 radar.py inspect
& $py -X utf8 app.py
& $py -X utf8 radar.py reprocess
& $py -X utf8 radar.py reprocess --full
```

### Backfill vị trí bản đồ

```powershell
& $py -X utf8 radar.py map-locations --dry-run
& $py -X utf8 radar.py map-locations --full
```

Kết quả gồm `scanned`, `exact`, `road`, `landmark`, `nearby`, `ward`,
`unmapped`, `ambiguous`, `not_found`, `invalid`, `inserted`, `updated`,
`unchanged`, và `deleted`. Lệnh chỉ cập nhật các bảng dẫn xuất
`listing_map_locations` và `listing_map_location_coverage`; không cập nhật bất
kỳ cột nào trong `listings`.

### Tọa độ nguồn Guland

Lệnh này chỉ xét tin Guland còn hoạt động và đủ điều kiện hiển thị Maps. Chế độ
mặc định là read-only:

```powershell
# Read-only by default
& $py -X utf8 radar.py guland-coordinate-backfill --dry-run

# Apply only after reviewing dry-run JSON
& $py -X utf8 radar.py guland-coordinate-backfill --apply

# Restore the five coordinate fields from one run manifest
& $py -X utf8 radar.py guland-coordinate-backfill `
  --rollback-run 20260730T120000Z
```

Apply chỉ merge năm field `source_lat`, `source_lng`,
`source_coordinate_url`, `source_coordinate_provider` và
`source_coordinate_captured_at` vào `raw_json`, sau đó cập nhật map location
cho đúng listing IDs đã đổi. Nó không chạy valuation, dedup hay full reprocess.

Rollback manifest có dạng
`.local/guland-coordinate-backfill/20260730T120000Z-before.jsonl`. Đây là
runtime data đã gitignore; manifest chỉ chứa raw/listing IDs và năm field tọa
độ cũ, không chứa tiêu đề, mô tả, số điện thoại, ảnh hoặc URL tin rao gốc.

API smoke cho bản đồ:

```powershell
Invoke-RestMethod "http://127.0.0.1:5000/api/map-listings?mode=signals"
Invoke-RestMethod "http://127.0.0.1:5000/api/map-listings?mode=all&complete=1"
Invoke-RestMethod "http://127.0.0.1:5000/api/map-listing-items?mode=signals&location_key=ward:thu-dau-mot:phu-loi&page=1&limit=20"
```

Direct `psql` access to the same local DB:

```powershell
& "C:\Program Files\PostgreSQL\18\bin\psql.exe" -h 127.0.0.1 -p 5432 -U postgres -d radar_bds
```

The old portable PostgreSQL 17 bundle in `tools/postgresql-17.10/` and
`.local/postgres-data` is only a fallback for isolated restore or recovery.
Do not start it as the default local DB.

Remote Supabase project ref `ozdjzfiqcjnlfuihqqjy` is kept only for sync/backup.
The real password is in local `.env` only. Do not paste it into docs or commits.
Avoid Supabase Transaction Pooler for the Flask app/crawler unless psycopg
prepared statements are explicitly disabled; local Postgres should be the normal
dev/reprocess target because remote round trips make full jobs slow.

After a migration or DB credential change, smoke test the Postgres-backed app:

```powershell
& $py -X utf8 radar.py inspect
& $py -X utf8 -c "from app import app; c=app.test_client(); [print(p, c.get(p).status_code) for p in ['/api/dashboard','/api/signals?page=1&limit=3']]"
```

Pull the current production DB down to local when the VPS has crawled new data.
This is one-way production -> local: it creates a production dump on the VPS,
downloads it, backs up the current local DB, then restores production into the
local `radar_bds` DB.

```powershell
.\scripts\sync_prod_to_local.ps1
```

If the new production rows reference images that local has not downloaded yet,
also pull missing production images into local `data/images/`:

```powershell
.\scripts\sync_prod_to_local.ps1 -SyncImages
```

For daily use on Windows, create a Task Scheduler job that runs the same command
from the repo root. Keep the generated backups in `.local/prod-sync/` ignored by
git.

For the daily signal LLM review workflow, do not sync the full production DB.
Export the production queue of actionable signals still missing LLM review coverage:

```powershell
.\scripts\export_prod_signal_llm_review_queue.ps1 -MissingReviewOnly
.\scripts\export_prod_signal_llm_review_queue.ps1 -MissingReviewOnly -Since "2026-06-14T00:00:00+07:00"
```

Apply manual extraction overrides back to production and refresh valuation only
for the touched listing IDs:

```powershell
.\scripts\apply_prod_signal_llm_review_results.ps1 -InputPath .local\llm-review\structured\signal-llm-qc-results-YYYYMMDD.jsonl -Revalue
```

## Ubuntu 24.04 Production Target

Production is Ubuntu Server 24.04 LTS with Python 3.12, native systemd
services, local PostgreSQL, and Nginx. Templates and setup steps live in
`deployment/ubuntu24/`. The public production domain is `https://radarbds.vn`;
set both `PUBLIC_BASE_URL` and `DASHBOARD_BASE_URL` to that value in
`/etc/radar-bds/radar.env`.

Dependency smoke on a fresh Ubuntu 24.04 host:

```bash
python3 --version  # expected Python 3.12.x
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -U pip setuptools wheel
pip install -r requirements.txt -r requirements-dev.txt
python -c "import flask, numpy, cv2, PIL, psycopg, playwright; print('ok')"
```

Production service smoke after installing `deployment/ubuntu24/*.service`:

```bash
sudo systemctl status radar-bds.service
sudo systemctl list-timers radar-bds-crawl.timer
sudo systemctl list-timers radar-bds-guland-crawl.timer
systemctl status radar-bds-crawl.service --no-pager
systemctl status radar-bds-guland-crawl.service --no-pager
crontab -l | grep 'radar.py crawl-daily --source guland'
tail -n 120 logs/crawl-daily.log
curl -fsS http://127.0.0.1:5000/api/dashboard >/dev/null
curl -fsS "http://127.0.0.1:5000/api/signals?page=1&limit=3" >/dev/null
curl -fsS "http://127.0.0.1:5000/api/dashboard?cache_refresh=1" >/dev/null
curl -fsS https://radarbds.vn/robots.txt >/dev/null
curl -fsS https://radarbds.vn/sitemap.xml >/dev/null
```

Deploy latest `origin/main` to the VPS after pushing:

```powershell
.\scripts\deploy_production.ps1
```

The script uses the local deploy key at
`$env:USERPROFILE\.ssh\radar_bds_deploy_rsa`, removes legacy
`data/facebook_profiles.json` after DB migration/backup, pulls with `--ff-only`, restarts
`radar-bds.service`, and smokes `/api/dashboard` plus `/api/signals`.
It also auto-archives a small allowlist of known temporary audit/report files
from the VPS checkout before deploy continues, but still fails on any other
unexpected dirty file.

Verify a live SEO article after deploy:

```powershell
.\scripts\verify_live_seo_article.ps1 `
  -Url "https://radarbds.vn/kien-thuc/<slug>" `
  -HeadingContains "heading marker" `
  -RequireWatchlistIntent
```

## Crawl and Jobs

```powershell
& $py -X utf8 radar.py crawl-daily
& $py -X utf8 radar.py crawl-facebook --mode incremental --limit 30
& $py -X utf8 radar.py schedule-setup --time 21:00
```

## Images

```powershell
& $py -X utf8 radar.py download-images
& $py -X utf8 scripts\generate_thumbnails.py --signals 300
& $py -X utf8 scripts\generate_thumbnails.py --limit 1000
```

## Fast Verification

```powershell
& $py -X utf8 -m py_compile app.py services\market_data.py services\image_assets.py cleansing\download_images.py
& $py -X utf8 -m py_compile analytics\valuation.py scripts\apply_llm_extraction_results.py
node --check static\js\main.js
node --check static\js\auth.js
```

Targeted tests:

```powershell
& $py -X utf8 -m pytest tests\test_dedup.py
& $py -X utf8 -m pytest tests\test_price_history.py
& $py -X utf8 -m pytest tests\test_lot_history.py
& $py -X utf8 -m pytest tests\test_drop_filter.py
& $py -X utf8 -m pytest tests\test_feature_extractor.py
& $py -X utf8 -m pytest tests\test_valuation.py
& $py -X utf8 -m pytest tests\test_market_data_performance.py tests\test_postgres_connection.py tests\test_market_data_trust.py
```

Post-merger location resolver:

```powershell
& $py -X utf8 -m py_compile cleansing\normalizer.py config\location_aliases.py scripts\audit_post_merger_locations.py
& $py -X utf8 -m pytest tests\test_feature_extractor.py tests\test_dedup.py tests\test_price_history.py -q

# Read-only DB audit before any reprocess.
# Uses the current local PostgreSQL 18 DATABASE_URL from .env.
& $py -X utf8 scripts\audit_post_merger_locations.py --limit 2000 --samples 3
```

Full pytest:

```powershell
& $py -X utf8 -m pytest tests
```

Integration checks such as `tests\test_guland.py` and `tests\sanity_test.py` may touch live services or local app state. Run them only when the task needs that coverage.

## API Smoke Checks

Assumes Flask is running at `http://127.0.0.1:5000`.

```powershell
Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:5000/api/dashboard"
Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:5000/api/signals?page=1&limit=30"
Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:5000/api/listing/1"
```

Filter sanity:

```powershell
Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:5000/api/signals?page=1&limit=30&mos_min=25&only_drops=1&sort=mos_desc"
Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:5000/api/dashboard?mos_min=25&only_drops=1"
```

## Listing Map Registry And Coverage

Install the pinned map dependencies once:

```powershell
& $py -X utf8 -m pip install -r requirements-map.txt
```

Fetch the OSM input only into ignored local storage. If the combined Overpass
query times out, fetch the named/ref highway part separately and keep the
result at the same ignored path after JSON validation:

```powershell
$query = Get-Content -Raw -LiteralPath config\listing_map_overpass.ql
$osmPath = ".local\listing-map\osm-binh-duong-20260729-v2.json"
New-Item -ItemType Directory -Force -Path (Split-Path $osmPath) | Out-Null
Invoke-WebRequest -Method Post `
  -Uri "https://overpass-api.de/api/interpreter" `
  -Headers @{"User-Agent"="RadarBDS-registry-build/2.0"} `
  -Body @{data=$query} `
  -TimeoutSec 300 `
  -OutFile $osmPath
& $py -X utf8 -m json.tool $osmPath > $null
```

Build the four versioned artifacts atomically:

```powershell
& $py -X utf8 scripts\build_listing_location_registry.py `
  --osm-json .local\listing-map\osm-binh-duong-20260729-v2.json `
  --sources config\listing_map_location_sources.json `
  --overrides config\listing_map_location_overrides.json `
  --auto-overrides config\listing_map_location_auto_overrides.json `
  --boundary config\map_products\thu_dau_mot_legacy_boundaries.geojson `
  --boundary config\map_products\ben_cat_legacy_boundaries.geojson `
  --output-dir static\maps\listing-locations
```

Validate, preview the full derivation, then apply and audit unresolved
candidates:

```powershell
& $py -X utf8 -m pytest `
  tests\test_listing_location_registry.py `
  tests\test_listing_map_context.py `
  tests\test_listing_location_resolver.py `
  tests\test_listing_location_backfill.py `
  tests\test_listing_location_coverage.py -q
& $py -X utf8 radar.py map-locations --full --dry-run
& $py -X utf8 radar.py map-locations --full
& $py -X utf8 radar.py map-location-coverage --status unresolved --limit 100
```

These commands write only derived map-location and coverage tables. They do
not change canonical listing, valuation, human feedback, or AI review fields,
and public requests never call a live geocoder.

Browser-assisted registry maintenance stays outside crawl and public request
paths. Export a bounded queue, validate evidence with a dry run, then apply
only automatically accepted entries:

Quy trình production đầy đủ, browser evidence contract và stop gates nằm tại
`docs/listing_map_registry_automation.md`.

```powershell
& $py -X utf8 radar.py map-location-research-queue `
  --limit 50 `
  --candidate-type all

& $py -X utf8 radar.py map-location-ingest-evidence `
  --input .local\listing-map-evidence\batch.json

& $py -X utf8 radar.py map-location-ingest-evidence `
  --input .local\listing-map-evidence\batch.json `
  --apply
```

Evidence files belong under ignored `.local/`. They may contain only the
bounded candidate identity and selected public Google Maps result fields;
never put listing descriptions, phone numbers, cookies, browser history, or
account state in these files.

## Cleanup Policy

`radar.py db-cleanup` is dry-run by default. It removes rows that cannot support
valuation when applied: listings with missing/zero `price_ty` or missing/zero
`area_m2`, plus their source `raw_listings` rows so full reprocess does not
recreate them. It also deletes old sold rows, stale orphan raw rows, old
notifications, and orphan local image files.

```powershell
& $py -X utf8 radar.py db-cleanup
& $py -X utf8 radar.py db-cleanup --apply
```

Quick local API timing without starting a browser:

```powershell
& $py -X utf8 -c "import time, app as a; c=a.app.test_client(); a.clear_dashboard_cache(); [print(p, c.get(p).status_code) for p in ['/api/dashboard','/api/signals?page=1&limit=30&sort=score_desc']]"
```

## Telegram / VIP Watchlist

Check bot identity without printing secrets:

```powershell
$token = (Get-Content .env | Select-String '^TELEGRAM_BOT_TOKEN=').Line.Split('=',2)[1]
Invoke-RestMethod "https://api.telegram.org/bot$token/getMe"
Invoke-RestMethod "https://api.telegram.org/bot$token/getWebhookInfo"
```

Public local Flask with zrok:

```powershell
$zrok = "zrok"
if (Test-Path ".\tools\zrok\zrok.exe") { $zrok = ".\tools\zrok\zrok.exe" }
& $zrok share public http://127.0.0.1:5000 --headless
```

Set webhook after adding `DASHBOARD_BASE_URL` and `TELEGRAM_WEBHOOK_SECRET` to `.env` and restarting Flask:

```powershell
$token = (Get-Content .env | Select-String '^TELEGRAM_BOT_TOKEN=').Line.Split('=',2)[1]
$base = (Get-Content .env | Select-String '^DASHBOARD_BASE_URL=').Line.Split('=',2)[1].TrimEnd('/')
$secret = (Get-Content .env | Select-String '^TELEGRAM_WEBHOOK_SECRET=').Line.Split('=',2)[1]
$webhook = "$base/api/auth/telegram/webhook?secret=$secret"
Invoke-RestMethod "https://api.telegram.org/bot$token/setWebhook?url=$([uri]::EscapeDataString($webhook))"
```

Run VIP push manually:

```powershell
& $py -X utf8 -c "from cli.notify import push_new_listings_to_vip; print(push_new_listings_to_vip(since='2026-01-01T00:00:00'))"
```
