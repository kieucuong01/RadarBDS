# Database Layer

Current module map:

- `connection.py`: DB path resolution, per-thread SQLite connections.
- `schema.py`: `SCHEMA_SQL`, `init_schema()`, idempotent migrations.
- `raw_listings.py`: raw-listing reads/writes.
- `listings.py`: processed listing upsert, images, outlier updates.
- `crawl_runs.py`: crawl run lifecycle helpers.
- `analytics.py`: alert logs and valuation result writes.
- `sqlite.py`: compatibility facade that re-exports the public SQLite API.

`config.database_sqlite` is now only a compatibility facade. Existing code can
keep importing from it, but new code should prefer `db.sqlite` or future
repository modules under `db/`.

Next safe split points:

- Move direct dashboard SQL from `app.py` and `services/market_data.py` into
  read-model services or repository modules.
- Add migration versioning if schema changes become frequent.
