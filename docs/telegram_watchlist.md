# Telegram Watchlist Push

This document is for agents touching VIP notifications, zrok/webhook setup, or Telegram message format.

## Product Model

- One shared Telegram bot serves all users.
- Each user links the bot through a unique `/start <token>`.
- The app stores the user's private `users.telegram_chat_id`.
- VIP/admin push sends only to that user's linked chat/email, filtered by active watchlists or explicitly enabled saved-listing alerts. Global account channel preferences always apply.
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

1. Fetches new/updated signals since timestamp and all previously notified or explicitly followed listings, in pages of 500. Old listings remain eligible for change detection.
2. Fetches active, unexpired VIP users plus admin users with active watchlists.
3. Groups unique matches per user.
4. Sends at most 6 Telegram updates and 10 email updates per user/run, prioritizing changes. Overflow stays pending for the next run.
5. Logs price, source state and event after actual successful delivery; commits each channel independently. Undelivered/overflow items have a `pending` record in `notification_log`, excluded from the delivery baseline and removed on success. They survive the next crawl window without scanning all historical signals. Failed channels retry without repeating successful channels. A PostgreSQL advisory lock prevents overlapping jobs.
6. Updates `user_watchlists.last_notified_at`.

## Telegram Digest Format

`alerts/telegram.py::send_watchlist_digest(...)` sends one VIP-only watchlist message:

- Header: `RADAR BDS - CẬP NHẬT BĐS ĐANG THEO DÕI`.
- Summary count and matched watchlist names.
- Up to 6 deals by default.
- Each deal title is an HTML link to `/listing/<id>` under `DASHBOARD_BASE_URL`.
- Each deal shows price, area, MOS, ward, property type, and a neutral verification note.
- Footer links to the dashboard and says how many older matches remain when applicable.

Keep messages under Telegram's 4096-character limit. If increasing `max_items`, check message length.

## Saved-listing alerts and meaningful changes

- `/bds-da-luu` has a per-listing **Bật báo thay đổi** toggle. Saving alone does not subscribe. Free users may save; effective VIP/admin is required to enable alerts. Any signed-in owner may disable them.
- `PATCH /api/favorites/<id>` accepts a JSON boolean `alert_enabled`. Ownership is enforced server-side. Enabling captures the current price/source status as baseline; repeated enable requests retain it. Disable/re-enable starts a new baseline.
- `GET /api/favorites` retains `listing_ids` and adds `items` with per-listing `alert_enabled`.
- Price alerts compare against the last successful notification on that channel (or opt-in baseline), with `SIGNAL_REALERT_THRESHOLD_PCT` (default 5%). Drops above 40%, invalid prices, unreachable sources and extraction-quality blockers are suppressed pending QC. A followed saved listing need not remain a signal to receive a valid price update.
- Confirmed `inactive` triggers **tin bị gỡ khỏi nguồn — chưa xác nhận đã bán**; a subsequent `active` triggers **tin xuất hiện lại**. `unknown`/`unreachable` do not claim a sale or trigger source-state alerts.
- Identical price/state does not send again. Notification timestamps use explicit UTC offsets; event ordering uses log IDs, preventing timezone skew from reviving old alerts.
- Hidden/blacklisted listings and hidden Guland publishers are excluded; VIP notification titles undergo public redaction. Original source URLs/phones are not sent.
- Dry-run or unconfigured delivery does not consume notification history. Provider success followed by a process crash before DB commit can still repeat on retry; these providers offer no transaction spanning delivery and PostgreSQL.
- Schema initialization adds saved-listing opt-in/baseline fields and notification state/event fields; run with a role allowed to alter these tables before starting a release. No existing favorite is automatically opted in.

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
