---
paths:
  - "config/database_sqlite.py"
  - "config/settings.py"
---

# Database

## Locations

- **Runtime DB:** `C:\Users\ASUS\radar_bds.db` (Windows home — writable)
- **Backup (source of truth):** `data/raw_backup.json`

> ⚠️ SQLite không write được lên NTFS mount path của project.
> `_resolve_db_path()` tự resolve về `~/radar_bds.db`.

## Quy trình persist

```
Crawl / thay đổi xong → python radar.py export-raw
Session mới            → python radar.py import-raw-backup
```

## Schema

### raw_listings
```
id          INTEGER PK
source      TEXT              -- 'guland' | 'batdongsan'
source_id   TEXT
url         TEXT UNIQUE
raw_json    TEXT              -- toàn bộ data gốc từ crawler
crawled_at  TIMESTAMP
```

### listings
```
id                INTEGER PK
raw_id            INTEGER FK → raw_listings.id
source            TEXT
url               TEXT
title             TEXT
price_ty          REAL          -- tỷ VND
area_m2           REAL
price_per_m2      REAL          -- triệu/m²
property_type     TEXT          -- dat_nen | dat_vuon | nha_dat | nha_pho
tx_type           TEXT          -- ban | thue
ward              TEXT          -- NULL nếu không match keyword
road_type         TEXT          -- nhua | be_tong | dat | unknown
road_tier         INTEGER       -- 0–5
has_so            INTEGER       -- 0/1 (⚠️ hiện luôn=0, extraction chưa fix)
frontage_m        REAL
is_outlier        INTEGER       -- 0/1
price_dropped     INTEGER       -- 0/1
probably_sold     INTEGER       -- 0/1
possibly_duplicate INTEGER      -- 0/1
duplicate_of_id   INTEGER       -- FK → listings.id canonical
is_hot            INTEGER       -- 0/1 (bán gấp, cắt lỗ...)
signal_score      REAL          -- 0–100
area              TEXT          -- khu vực (Tân An, Thủ Dầu Một...)
```

### valuation_results
```
listing_id   INTEGER FK → listings.id
fair_ppm2    REAL          -- triệu/m²
actual_ppm2  REAL
mos_pct      REAL          -- margin of safety (0.0–1.0)
is_signal    INTEGER       -- 0/1
signal_score REAL          -- 0–100
n_segment    INTEGER       -- số listings trong segment
segment      TEXT          -- "{area}_{property_type}_{tx_type}"
confidence   TEXT          -- 'high' | 'medium' | 'low'
```

### Bảng phụ
```
market_weekly:  segment, median_ppm2, n, min_ppm2, max_ppm2, week
price_history:  listing_id FK, price_ty, price_per_m2, recorded_at
alert_logs:     listing_id FK, alert_type, sent_at
crawl_runs:     source, mode, started_at, finished_at, n_new, n_updated
```

## Auto-migrations (`_run_migrations()`)

Tự động thêm columns mới vào DB cũ — không cần tay:
`possibly_duplicate`, `duplicate_of_id`, `road_tier`, `ward`, `has_so`, `is_hot`, `signal_score`

## Key functions

| Function | Mô tả |
|----------|-------|
| `get_conn()` | Context manager, busy_timeout=5000ms |
| `init_schema()` | Tạo bảng + chạy migrations |
| `insert_raw(conn, source, source_id, url, raw_json)` | Thêm vào raw_listings |
| `upsert_listing(conn, data)` | Insert hoặc update listings |
| `save_valuation_result(conn, result)` | Lưu kết quả valuation |
