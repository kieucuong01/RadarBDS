# RBAC, Leads, and Tier Gating

This is the compact current-state reference for auth and permission work. For the Telegram/watchlist push flow, read `docs/telegram_watchlist.md`.

## Tiers

`auth/core.py` owns tier logic.

```python
TIER_ORDER = {"guest": 0, "free": 1, "vip": 2, "admin": 3}
```

- **Guest**: no session. Can browse the deal feed and listing detail content. No phone/original URL. MOS/drop filters are disabled. VIP market indicators are gated.
- **Free**: logged in. Sees full listing content, but still no phone/original URL. Can save watchlists for upsell/readiness.
- **VIP**: Free plus Telegram watchlist push and deep market indicators. Still no phone/original URL; lead/rap-moi flow protects commission.
- **Admin**: can see original URL/phone/source fields where APIs intentionally return them. Admin control room uses the same app session tier, so a logged-in `tier=admin` user can open `/admin/control-room` without a browser Basic Auth popup.

`current_tier()` checks every request and downgrades expired VIP to Free.

## Server-Side Redaction Rules

Do not rely on CSS or `window.USER_TIER` for security.

`services/market_data.py::redact_for_tier(record, tier)`:

- Admin: unchanged.
- Non-admin: forces `contact_phone`, `url`, `source_url` to `None` when present.
- Fresh/new listings are visible to Guest; `fresh_lock_hours_for(...)` returns 0 for all tiers.

History:

- `/api/history/<id>` is open for all tiers for price/lot context.
- Original URLs inside `lot_history` and `comps` are admin-only. Non-admin gets empty `url`, but `detail_url` remains available.

## Important Endpoints

Auth:

- `POST /api/auth/check`: phone-only identifier check; rate-limited.
- `POST /api/auth/register`: phone registration; creates a session; rate-limited.
- `POST /api/auth/login`: login; rate-limited.
- `POST /api/auth/logout`: deletes current session.
- `GET /api/auth/me`: public session/tier snapshot.

Watchlists:

- `GET /api/watchlists`
- `POST /api/watchlists`
- `PATCH /api/watchlists/<id>`
- `DELETE /api/watchlists/<id>`

These require `free`, so Free users can save filters, but only active VIP users receive push notifications.

Lead capture:

- `POST /api/leads`: logged-in or anonymous lead capture; phone required.
- `POST /api/lead-capture-guest`: guest/free/vip mini-form; phone only; server fills default note when missing.
- VIP/Admin lead requests are marked urgent and include 1-1 consultation wording.

VIP market indicators:

- `GET /api/market-indicators` requires `vip`.
- UI overlays are only UX; backend gate is the source of truth.

## Rate Limits

Use `auth/core.py::rate_limit(scope, limits=None)`.

Current important scopes:

- `auth_check`, `auth_register`, `auth_login`
- `dashboard`
- `listings`
- `track`
- `lead_capture`

Default limit is guest 60/h, free 300/h, VIP/admin unlimited unless overridden.

## Admin Notes

Admin control room:

- `/admin/control-room` renders an in-app login modal for non-admin visitors instead of challenging with browser Basic Auth. A logged-in `tier=admin` user sees the workspace immediately.
- `/admin/*` accepts app-session admins (`tier=admin`) first. Legacy `ADMIN_BASIC_USER`/`ADMIN_BASIC_PASS` is only a compatibility fallback when a request already sends an Authorization header. Admin APIs still return `admin_required` when the session is not admin.
- `/admin/api/users` now includes `watchlist_count` plus `telegram_linked`.
- Admin user table shows TG status and watchlist count, enough for current ops. A separate notification-ops screen is not yet needed.

## Common Security Checks

Run these after permission changes:

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $py -X utf8 -m py_compile app.py services\market_data.py auth\core.py
node --check static\js\auth.js
```

Guest API probes:

```powershell
Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:5000/api/signals?page=1&limit=1"
Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:5000/api/listing/<fresh_id>"
Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:5000/api/history/<id>"
```

Expected:

- Guest can see fresh listing title/price/description/images.
- Non-admin `url` fields are blank/null.
- `/api/market-indicators` returns 403 for guest/free.
