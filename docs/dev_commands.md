# Development Commands

Use UTF-8 mode on Windows because the project contains Vietnamese text.

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python39\python.exe"
```

## App and DB

```powershell
& $py -X utf8 radar.py inspect
& $py -X utf8 app.py
& $py -X utf8 radar.py reprocess
& $py -X utf8 radar.py reprocess --full
```

Check DB path:

```powershell
& $py -X utf8 -c "import db.connection as c; print(c.DB_PATH)"
```

## Crawl and Jobs

```powershell
& $py -X utf8 radar.py crawl-daily
& $py -X utf8 radar.py crawl-facebook --mode incremental --limit 30
& $py -X utf8 radar.py schedule-setup --every 3
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

## Telegram / VIP Watchlist

Check bot identity without printing secrets:

```powershell
$token = (Get-Content .env | Select-String '^TELEGRAM_BOT_TOKEN=').Line.Split('=',2)[1]
Invoke-RestMethod "https://api.telegram.org/bot$token/getMe"
Invoke-RestMethod "https://api.telegram.org/bot$token/getWebhookInfo"
```

Public local Flask with zrok:

```powershell
.\zrok.exe share public http://127.0.0.1:5000 --headless
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
