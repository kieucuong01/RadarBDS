# Radar BDS Architecture Notes

## Current Shape

Pipeline flow:

```text
crawler/* -> raw_listings -> cleansing/normalizer.py -> listings
          -> cleansing/dedup.py -> analytics/valuation.py
          -> valuation_results -> app.py / alerts/telegram.py / cli/*
```

Main entrypoints:

- `radar.py`: CLI router.
- `app.py`: Flask dashboard and review UI.
- `cleansing/reprocess.py`: normalization, valuation, enrichment orchestration.
- `db/connection.py`: SQLite path and connection lifecycle.
- `db/schema.py`: schema and idempotent migrations.
- `db/raw_listings.py`, `db/listings.py`, `db/crawl_runs.py`, `db/analytics.py`: write-side repository helpers.
- `db/sqlite.py` and `config/database_sqlite.py`: compatibility facades for existing imports.

## Boundaries

- `crawler/`: fetch source data only; write raw records, avoid valuation logic.
- `cleansing/`: parse, normalize, enrich, deduplicate.
- `analytics/`: market logic and valuation, no crawler calls.
- `services/`: read models for dashboard/API.
- `cli/`: command orchestration and user-facing output.
- `alerts/`: Telegram formatting and send logic.

## Refactor Targets

Keep future changes surgical. The highest-value splits are:

1. Move dashboard SQL out of `app.py` into `services/` or read-model repository modules.
2. Centralize ward/city config in `config/area_profiles.py`; avoid duplicating ward lists in dashboard and normalizer.
3. Split `cleansing/feature_extractor.py` by concern when touching it heavily: price/area, road, legal, property type.
4. Add migration versioning if DB schema changes become frequent.

Do not move files only for aesthetics. Move a boundary when it reduces test scope or prevents agents from editing unrelated logic.
