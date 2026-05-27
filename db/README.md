# Database Layer

Canonical runtime DB: PostgreSQL via `DATABASE_URL`.

Legacy SQLite source: `data/radar_bds.db`, read only by `scripts/migrate_sqlite_to_postgres.py`.

For local development, use portable PostgreSQL 17 in `tools/postgresql-17.10/`
with data in `.local/postgres-data`. Start it with:

```powershell
.\scripts\local_postgres.ps1 start
```

Normal local `.env` should point to:

```env
DATABASE_URL=postgresql://postgres@127.0.0.1:5432/radar_bds
```

Remote Supabase is for sync/backup. Do not use a remote DB for normal full
reprocess work because the app still has many row-by-row DB operations.

Current remote Supabase project: `ozdjzfiqcjnlfuihqqjy` (`kieucuong02`,
`ap-southeast-2`). The DB password belongs in local `.env` only.

Migration snapshot from 2026-05-25:

- `raw_listings`: 6,991 rows.
- `listings`: 6,991 rows.
- `listing_images`: 38,951 rows copied, 18 orphan rows skipped.
- `price_history`: 6,971 rows copied, 18 orphan rows skipped.
- `valuation_results`: 5,911 rows.
- `users`: 13 rows.

## Module Map

- `connection.py`: PostgreSQL connection lifecycle, sqlite-shaped row/execute compatibility, and advisory locks.
- `schema.py`: `SCHEMA_SQL`, `init_schema()`, idempotent schema migrations.
- `raw_listings.py`: raw crawler rows.
- `listings.py`: processed listing upsert, images, price history, outlier flags.
- `crawl_runs.py`: crawl run lifecycle.
- `analytics.py`: valuation results and legacy analytics helpers.
- `sqlite.py`: legacy compatibility facade that re-exports the public DB API.

`config.database_sqlite` is also a legacy compatibility facade. Runtime code should import focused `db.*` modules directly.

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
- Runtime DB backups, images, logs, and reports are ignored by git.

## Safe Checks

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python39\python.exe"
.\scripts\local_postgres.ps1 start
$env:DATABASE_URL = "postgresql://postgres@127.0.0.1:5432/radar_bds"
& $py -X utf8 scripts\migrate_sqlite_to_postgres.py --sqlite data\radar_bds.db --database-url $env:DATABASE_URL --truncate
& $py -X utf8 radar.py inspect
```
