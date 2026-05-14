---
paths:
  - "radar.py"
---

# CLI Reference (radar.py)

## Crawl

```bash
python radar.py crawl-all                           # full crawl tất cả nguồn
python radar.py crawl-all --source guland           # chỉ Guland
python radar.py crawl-all --source batdongsan       # chỉ BatDongSan
python radar.py crawl-all --visible                 # debug: hiện browser
python radar.py crawl-all --no-reprocess            # bỏ qua bước reprocess

python radar.py crawl-daily                         # incremental + Telegram alert
python radar.py crawl-daily --source guland
python radar.py crawl-daily --visible
python radar.py crawl-daily --no-alert
```

## Data Quality

```bash
python radar.py repair-missing --source guland      # re-fetch thiếu price/area
python radar.py repair-missing --source guland --limit 10  # test 10 records trước
python radar.py repair-missing --visible            # debug browser
```

## Reprocess & Backup

```bash
python radar.py import-raw-backup                   # restore từ raw_backup.json + reprocess
python radar.py import-raw-backup --file PATH       # custom backup file
python radar.py import-raw-backup --no-reprocess    # chỉ import, bỏ reprocess

python radar.py export-raw                          # backup → data/raw_backup.json
python radar.py export-raw --out PATH               # custom path

python radar.py reprocess                           # normalize + valuation tất cả
python radar.py reprocess --source guland
python radar.py reprocess --since 2026-04-01
python radar.py reprocess --valuation-only
python radar.py reprocess --listings-only
```

## Inspect (AI Agent snapshot)

```bash
python radar.py inspect                             # snapshot đầy đủ: counts, quality, dedup, signals
```

## Query

```bash
python radar.py query --stats                       # tổng quan DB
python radar.py query --signals                     # top signals (mặc định 20)
python radar.py query --signals --limit 50
python radar.py query --top50-cheap                 # top 50 giá rẻ nhất
python radar.py query --top50-cheap --source guland
python radar.py query --search KEYWORD              # tìm trong title/desc listings
python radar.py query --raw-search KEYWORD          # tìm trong raw_json
```

## Dashboard

```bash
python radar.py dashboard                           # sinh dashboard_signals.html
python radar.py dashboard --db PATH                 # custom DB path
python radar.py dashboard --out PATH                # custom output path
```

## Deal Analysis

```bash
python radar.py deal-brief --id 123                 # brief chi tiết 1 listing
python radar.py deal-brief --top 5                  # top 5 signals brief
```

## Lifecycle

```bash
python radar.py lifecycle                           # sweep delisted (default 48h)
python radar.py lifecycle --sweep-hours 72
python radar.py lifecycle --alert                   # Telegram nếu signal bị delisted
python radar.py lifecycle --velocity                # hotness metric per segment
```

## Facebook (Apify)

```bash
python radar.py crawl-facebook                      # full crawl 2 profiles (100 posts/profile)
python radar.py crawl-facebook --mode incremental   # chỉ bài trong 24h (dùng cho daily)
python radar.py crawl-facebook --profile URL        # 1 profile cụ thể
python radar.py crawl-facebook --limit 20           # giới hạn số bài (tiết kiệm credits)
python radar.py crawl-facebook --no-reprocess       # chỉ import, bỏ reprocess
python radar.py import-facebook-json FILE.json      # import thủ công từ file JSON
```

> ⚠️ Apify free tier $5/tháng ≈ 2,500 posts. Full crawl (200 posts) ≈ $0.40.
> Dùng `--mode incremental` cho crawl hàng ngày để tiết kiệm credits.

## Import / Xóa từng nguồn

```bash
python radar.py import-guland --file PATH.json
python radar.py import-batdongsan --file PATH.json

python radar.py delete-guland --yes                 # xóa toàn bộ Guland khỏi DB
python radar.py delete-batdongsan --yes
```

## Schedule Windows

```bash
python radar.py schedule-setup                      # Task Scheduler mỗi ngày 10:15 sáng
python radar.py schedule-setup --time 07:00         # đổi giờ
python radar.py schedule-setup --every 3            # mỗi 3 ngày thay vì hàng ngày
python radar.py schedule-setup --remove             # xóa task
```
