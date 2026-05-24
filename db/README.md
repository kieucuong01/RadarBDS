# Database Layer

Canonical DB path: `data/radar_bds.db`.

Override with `RADAR_DB_PATH`. If the override is relative, it resolves from repo root.

## Module Map

- `connection.py`: DB path resolution and SQLite connection lifecycle.
- `schema.py`: `SCHEMA_SQL`, `init_schema()`, idempotent schema migrations.
- `raw_listings.py`: raw crawler rows.
- `listings.py`: processed listing upsert, images, price history, outlier flags.
- `crawl_runs.py`: crawl run lifecycle.
- `analytics.py`: valuation results and legacy analytics helpers.
- `sqlite.py`: compatibility facade that re-exports the public DB API.

`config.database_sqlite` is also a compatibility facade. New code should prefer focused `db.*` modules.

## Current Data Rules

- `price_history` tracks same-listing price changes only; do not insert unchanged snapshots.
- Same URL/source_id is the same listing.
- Guland/BatDongSan duplicate identity is source-id only.
- Facebook may use repost heuristics, guarded by property type, location, thổ cư, area/dimensions, and phone.
- Admin Control Room tables:
  - `lead_captures` (CRM lead intake)
  - `dedup_overrides` (manual merge/split precedence after auto-dedup)
  - `broker_blacklist` (phone blacklist for crawler + reprocess + display filters)
- Listings moderation columns:
  - `is_blacklisted`, `blacklisted_at`, `blacklist_phone_norm`
- Runtime DB files, WAL/SHM files, images, logs, and reports are ignored by git.

## Safe Checks

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python39\python.exe"
& $py -X utf8 -c "import db.connection as c; print(c.DB_PATH)"
& $py -X utf8 radar.py inspect
```
