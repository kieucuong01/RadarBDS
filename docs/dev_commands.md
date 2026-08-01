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
Current local override uses the repo portable PostgreSQL instance:

- start command: `.\scripts\local_postgres.ps1 start`
- host/port: `127.0.0.1:15432`
- database: `radar_bds`
- user: `postgres`
- test database: `radar_bds_test`
- env source: `.env` is production-shaped base; `.env.local` is local override

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"

.\scripts\local_postgres.ps1 start
# .env.local should set DATABASE_URL and RADAR_TEST_DATABASE_URL
& $py -X utf8 radar.py inspect
& $py -X utf8 app.py
& $py -X utf8 radar.py reprocess
& $py -X utf8 radar.py reprocess --full
```

PostgreSQL integration tests must use `RADAR_TEST_DATABASE_URL` from
`.env.local`. Its database name must contain `test`:

```powershell
if (-not $env:RADAR_TEST_DATABASE_URL) { throw "Set RADAR_TEST_DATABASE_URL to the local radar_bds_test database" }
& $py -X utf8 -m pytest tests\test_postgres_connection.py tests\test_price_history.py -q
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

### Người đăng Guland

`GULAND_PUBLISHER_KEY_SECRET` phải có ít nhất 32 ký tự ngẫu nhiên trong
`.env.local`; không in hoặc commit giá trị. Backfill mặc định dry-run và chỉ
xét tin Guland còn hoạt động/đang có thể hiển thị:

```powershell
# Read-only; giới hạn một browser session
& $py -X utf8 radar.py guland-publisher-backfill --limit 100

# Chỉ chạy sau khi xem dry-run và được duyệt riêng
& $py -X utf8 radar.py guland-publisher-backfill --limit 100 --apply

# Bỏ checkpoint cũ và duyệt lại tập mục tiêu
& $py -X utf8 radar.py guland-publisher-backfill --limit 100 --no-resume
```

Dry-run chỉ trả số lượng candidate/live/identity/class và không trả HMAC key,
phone, profile URL hay member ID. Apply ghi checkpoint an toàn tại
`.local/guland-publisher-backfill/<run-id>.json`, có thể resume idempotent và
chỉ targeted reprocess các raw row thật sự đổi. Activity lịch sử được dựng từ
`first_seen_at` đã có, không sửa ngày card hay giả lập ngày đăng nguồn.

Direct `psql` access to the same local DB:

```powershell
& ".\tools\postgresql-17.10\pgsql\bin\psql.exe" -h 127.0.0.1 -p 15432 -U postgres -d radar_bds
```

The installed PostgreSQL 18 service on port 5432 may exist for pgAdmin, but
do not assume it is the active app DB unless `.env.local` points there.

Remote Supabase project ref `ozdjzfiqcjnlfuihqqjy` is kept only for sync/backup.
The real passwords are in ignored env files only. Do not paste them into docs or commits.
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
python -c "import flask, numpy, cv2, PIL, psycopg, psycopg_pool, redis, playwright; print('ok')"
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

# Eligible Guland only: dry-run by default. Scope is zero-ready, including
# rows that exist but are NULL/NOT_FOUND/missing S3 original or thumbnail.
# Live inspection is bounded to 1-200 listings; default is 50.
& $py -X utf8 radar.py guland-image-backfill --limit 50
& $py -X utf8 radar.py guland-image-backfill --limit 50 --apply

# Broader audit/repair: include inactive/hidden/duplicate Guland listings.
# Prefer dry-run first because this can refetch many historical pages.
& $py -X utf8 radar.py guland-image-backfill --include-inactive --limit 50
& $py -X utf8 radar.py guland-image-backfill --include-inactive --limit 50 --apply
```

Production `--apply` requires explicit user approval. Apply merges live image
URLs into revisioned raw history, resets only confirmed retryable rows, and
downloads only the bounded zero-ready listing IDs.

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

### Homepage signal read model

Initialize the additive schema, publish a complete local snapshot, and compare only safe identifiers/field names:

```powershell
& $py -X utf8 radar.py signal-read-model --refresh --compare --limit 200
```

Feature-off is the default and rollback path:

```powershell
$env:RADAR_SIGNAL_READ_MODEL_ENABLED = "0"
& $py -X utf8 app.py
```

For a controlled feature-on local process:

```powershell
$env:RADAR_SIGNAL_READ_MODEL_ENABLED = "1"
$env:RADAR_SIGNAL_QUERY_TIMEOUT_MS = "5000"
& $py -X utf8 app.py
```

Focused Phase 1 verification:

```powershell
& $py -X utf8 -m py_compile `
  app.py `
  db\guland_publishers.py `
  db\public_dataset_versions.py `
  services\market_data.py `
  services\signal_read_model.py `
  services\public_data_publish.py `
  cleansing\reprocess.py `
  scripts\benchmark_public_read_path.py

& $py -X utf8 -m pytest `
  tests\test_market_data_performance.py `
  tests\test_public_dataset_versions.py `
  tests\test_signal_read_model.py `
  tests\test_guest_visibility.py `
  tests\test_source_policy.py `
  tests\test_guland_targeted_reprocess.py `
  tests\test_guland_publisher_repository.py `
  tests\test_reprocess_review_hidden.py `
  tests\test_schema_init_permissions.py `
  tests\test_benchmark_public_read_path.py -q
```

With Flask running, record cold/warm status, TTFB, total time, and bytes without printing bodies/cookies:

```powershell
& $py -X utf8 scripts\benchmark_public_read_path.py `
  --base-url http://127.0.0.1:5000 `
  --repeat 5
```

Local parity and single-request timings are not the concurrency acceptance test. Follow the staged load gates in `docs/superpowers/plans/2026-08-01-homepage-performance-scale-master.md` before claiming 1,000-5,000 simultaneous in-flight capacity.

### Shared public cache and bounded PostgreSQL pool

Phase 2 static/focused verification:

```powershell
& $py -X utf8 -m py_compile `
  app.py `
  db\connection.py `
  services\public_cache_keys.py `
  services\public_cache.py `
  services\public_data_publish.py `
  services\public_prewarm.py

& $py -X utf8 -m pytest `
  tests\test_postgres_connection.py `
  tests\test_public_cache_keys.py `
  tests\test_public_cache.py `
  tests\test_public_cache_headers.py `
  tests\test_public_cache_redis_integration.py `
  tests\test_public_prewarm.py `
  tests\test_signal_read_model.py `
  tests\test_market_data_performance.py `
  tests\test_guest_visibility.py `
  tests\test_source_policy.py `
  tests\test_security_hardening.py -q
```

The real Redis integration test skips unless an isolated Redis test database is explicitly configured. Do not point it at an unknown/shared cache:

```powershell
$env:RADAR_TEST_REDIS_URL = "redis://127.0.0.1:6379/15"
& $py -X utf8 -m pytest tests\test_public_cache_redis_integration.py -q
```

Run application code locally with cache disabled (the deploy-safe default):

```powershell
$env:RADAR_PUBLIC_CACHE_ENABLED = "0"
$env:RADAR_DB_POOL_MIN = "1"
$env:RADAR_DB_POOL_MAX = "4"
$env:RADAR_DB_POOL_TIMEOUT_SECONDS = "1.0"
& $py -X utf8 app.py
```

Only after a local Redis is intentionally running, use a disposable DB number and enable the application cache for focused tests:

```powershell
$env:RADAR_REDIS_URL = "redis://127.0.0.1:6379/15"
$env:RADAR_PUBLIC_CACHE_ENABLED = "1"
& $py -X utf8 app.py
```

Inspect headers without printing JSON bodies:

```powershell
$paths = @(
  "/",
  "/api/signals?include_total=0&limit=30&page=1&sort=newest",
  "/api/counts",
  "/api/dashboard"
)
foreach ($path in $paths) {
  $response = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:5000$path"
  [pscustomobject]@{
    Path = $path
    Status = $response.StatusCode
    AppCache = $response.Headers["X-Radar-Cache"]
    Public = $response.Headers["X-Radar-Public-Cache"]
    CacheControl = $response.Headers["Cache-Control"]
  }
}
```

Use `services.public_prewarm.prewarm_configured_routes()` for the allowlisted no-cookie prewarm. Do not add raw URLs, user identifiers, cookies, auth headers, saved listings, admin pages, or checkout/order routes.

### Signal-first frontend performance

Focused Phase 3 gate:

```powershell
node --test tests\js\filter_runtime.test.cjs tests\js\web_vitals.test.cjs
node --check static\js\main\filter_runtime.js
node --check static\js\main\web_vitals.js
node --check static\js\main\filters.js
node --check static\js\main\signals.js
node --check static\js\main\core.js
node --check static\js\main\boot.js

$bytes = (Get-Item -LiteralPath static\js\main\web_vitals.js).Length +
  (Get-Item -LiteralPath static\js\main\filter_runtime.js).Length
if ($bytes -gt 5120) { throw "New performance JS exceeds 5 KB uncompressed" }

& $py -X utf8 -m pytest `
  tests\test_refactor_structure.py `
  tests\test_traffic_seo_aio.py `
  tests\test_market_data_performance.py `
  tests\test_guest_visibility.py `
  tests\test_source_policy.py `
  tests\test_security_hardening.py -q
```

Real-browser verification must cover desktop and `390x844`:

1. On a fresh guest load, `/api/signals` is the first dynamic dashboard request; cards render before `/api/counts` finishes; no `/api/dashboard` occurs on the Signals tab.
2. Change several filters faster than a slow response. Confirm the old request is canceled, the newest payload alone renders, and page 2 contains no duplicate `data-id` values.
3. Switch to Market, change a filter, and confirm counts/dashboard plus Market resources still load.
4. Repeat a filter with a real disposable Free session. `/`, signals, and counts must be `private, no-store`, have no `X-Radar-Public-Cache`, and retain correct visible tier/card behavior. Remove the disposable session afterward.
5. Record HTML TTFB, first signal duration, `radar-first-signal-cards`, LCP, an INP interaction sample (or `<40 ms` when the observer has no qualifying event), CLS, resource count, and transfer bytes under the same viewport/network profile as the baseline.

Do not treat source-contract tests as browser evidence. Do not leave CDP throttling, request interception, synthetic cookies/users, or a viewport override active after the run.

### Staged public concurrency test

Validate the k6 profile without generating load:

```powershell
k6 inspect scripts\load\radar_public_load.js
```

Run stages serially from a machine outside the VPS. `RUN_ID` is one shared, non-secret edge-key suffix for the whole stage; change it between stages, never per virtual user:

```powershell
$env:BASE_URL = "https://radarbds.vn"
$env:SCENARIO = "default"
$env:RUN_ID = "stage-100"
$env:VUS = "100"
$env:DURATION = "2m"
k6 run scripts\load\radar_public_load.js
```

Advance only after the prior result and simultaneous host observations pass:

| Scenario | Serial VUs | Limit |
|---|---|---|
| `default` | `100`, `500`, `1000`, `5000` | p95 < 1,000 ms; p99 < 2,000 ms; failures < 0.5% |
| `mixed` | `100`, `500`, `1000` | p95 < 1,500 ms; p99 < 2,000 ms; failures < 0.5% |

The mixed setup prewarms exactly 50 canonical filter pairs and requires the second probe for each route to be `HIT`. Never run the two scenarios or two stages in parallel. Stop at the first abort threshold from `docs/operations.md`; do not compensate by raising workers, PostgreSQL connections, timeouts, or Redis memory.

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
& $py -X utf8 scripts\benchmark_public_read_path.py --base-url http://127.0.0.1:5000 --repeat 5
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
