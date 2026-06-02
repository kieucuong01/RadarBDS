# Telegram Watchlist Push

This document is for agents touching VIP notifications, zrok/webhook setup, or Telegram message format.

## Product Model

- One shared Telegram bot serves all users.
- Each user links the bot through a unique `/start <token>`.
- The app stores the user's private `users.telegram_chat_id`.
- VIP push sends only to that user's `telegram_chat_id`, filtered by that user's active watchlists.
- `TELEGRAM_CHAT_ID` is no longer used for listing notifications. Do not add admin/global broadcasts back.

## Files

- `app.py`
  - `/api/auth/telegram/start`
  - `/api/auth/telegram/sync`
  - `/api/auth/telegram/webhook`
  - `/api/watchlists`
- `static/js/auth.js`: account menu watchlist modal, Telegram connect, local sync polling.
- `templates/index.html`: watchlist modal markup.
- `static/css/auth.css`: watchlist modal styling.
- `cli/notify.py`: `push_new_listings_to_vip(since)`.
- `alerts/telegram.py`: Telegram send helpers and digest formatting.
- `alerts/email.py`: optional batched email alert.
- `db/schema.py`: `users.telegram_chat_id`, `user_watchlists`, `notification_log`.

## Environment

Required for Telegram:

```env
TELEGRAM_BOT_USERNAME=your_bot_username_without_or_with_at
TELEGRAM_BOT_TOKEN=123456:bot_token
```

Required for webhook/public links:

```env
PUBLIC_BASE_URL=https://radarbds.vn
DASHBOARD_BASE_URL=https://radarbds.vn
TELEGRAM_WEBHOOK_SECRET=some_secret
```

`config/settings.py` loads `.env`. Restart Flask after editing `.env`.

## Linking Flow

1. User opens **Khu vực quan tâm** from the account menu.
2. User clicks **Kết nối Telegram**.
3. `POST /api/auth/telegram/start` creates a 10-minute token and returns:

```text
https://t.me/<bot_username>?start=<token>
```

4. User presses Start in Telegram.
5. Production path: Telegram calls `/api/auth/telegram/webhook?secret=...`.
6. Local fallback path: the dashboard polls `POST /api/auth/telegram/sync`, which calls `getUpdates` and binds the matching `/start <token>`.
7. Backend writes `users.telegram_chat_id`, clears token fields, and sends a confirmation message.

## zrok Local Public URL

`zrok.exe` is a local-only binary and is not committed to the repo. Install zrok
locally and make it available on `PATH`, or place it under the ignored
`tools/zrok/zrok.exe` path. Start Flask first, then run:

```powershell
$zrok = "zrok"
if (Test-Path ".\tools\zrok\zrok.exe") { $zrok = ".\tools\zrok\zrok.exe" }
& $zrok share public http://127.0.0.1:5000 --headless
```

The log line contains the public host, for example:

```text
https://abc123.shares.zrok.io
```

Set `.env`:

```env
DASHBOARD_BASE_URL=https://abc123.shares.zrok.io
TELEGRAM_WEBHOOK_SECRET=radar_bds_zrok_20260515
```

Restart Flask, then set webhook:

```powershell
$token = "<TELEGRAM_BOT_TOKEN>"
$secret = "radar_bds_zrok_20260515"
$base = "https://abc123.shares.zrok.io"
$webhook = "$base/api/auth/telegram/webhook?secret=$secret"
Invoke-RestMethod "https://api.telegram.org/bot$token/setWebhook?url=$([uri]::EscapeDataString($webhook))"
Invoke-RestMethod "https://api.telegram.org/bot$token/getWebhookInfo"
```

Expected `getWebhookInfo.result.url` equals the webhook URL and `last_error_message` is empty.

Test the route through zrok without Telegram:

```powershell
$body = @{ message = @{ text = "noop"; chat = @{ id = 1 } } } | ConvertTo-Json -Depth 5
Invoke-RestMethod "$base/api/auth/telegram/webhook?secret=$secret" -Method Post -ContentType "application/json" -Body $body
```

Expected:

```json
{"ok": true, "ignored": true}
```

## Watchlist Matching

Watchlist fields:

- `wards`: JSON array.
- `prop_types`: JSON array.
- `mos_min`.
- `price_min_ty`, `price_max_ty`.
- `area_min`, `area_max`.
- `notify_telegram`, `notify_email`, `active`.

`cli/notify.py::_listing_matches(listing, watchlist)` applies the filters.

`push_new_listings_to_vip(since)`:

1. Fetches new signal listings since timestamp.
2. Fetches active, unexpired VIP users with active watchlists.
3. Groups unique matches per user.
4. Sends one Telegram digest per user.
5. Logs `notification_log` per user/listing/channel for idempotency.
6. Updates `user_watchlists.last_notified_at`.

## Telegram Digest Format

`alerts/telegram.py::send_watchlist_digest(...)` sends one VIP-only watchlist message:

- Header: `RADAR BDS - TIN KHỚP WATCHLIST VIP`.
- Summary count and matched watchlist names.
- Up to 6 deals by default.
- Each deal title is an HTML link to `/listing/<id>` under `DASHBOARD_BASE_URL`.
- Each deal shows price, area, MOS, ward, property type, and a neutral verification note.
- Footer links to the dashboard and says how many older matches remain when applicable.

Keep messages under Telegram's 4096-character limit. If increasing `max_items`, check message length.

## Manual Test

Check bot token and username:

```powershell
$token = "<TELEGRAM_BOT_TOKEN>"
Invoke-RestMethod "https://api.telegram.org/bot$token/getMe"
```

Run a VIP push using current data:

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $py -X utf8 -c "from cli.notify import push_new_listings_to_vip; print(push_new_listings_to_vip(since='2026-01-01T00:00:00'))"
```

For a non-spam format preview, call `send_watchlist_digest` with a small query and a known linked test user.

## Gotchas

- If webhook URL is blank, Telegram will not reply to `/start`.
- If zrok is stopped, webhook breaks and must be set again with the new URL.
- If the dashboard still says bot config missing after `.env` edit, restart Flask.
- Browser popup can be blocked; `static/js/auth.js` opens a blank tab immediately and later redirects it.
- Local fallback `/api/auth/telegram/sync` uses `getUpdates`. If a webhook is active, pending updates may not be available, which is fine in production.
