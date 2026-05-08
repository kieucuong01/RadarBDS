---
paths:
  - "generate_dashboard.py"
---

# Dashboard (generate_dashboard.py)

## Chạy

```bash
python radar.py dashboard                # sinh dashboard_signals.html
python radar.py dashboard --out PATH     # custom output
```

## Sections của dashboard

1. **Market Pulse** — Median price/m² theo 3 segments (dat_nen, dat_vuon, nha_dat)
   - Hiển thị: median, min, max, n samples
2. **Headline Deals** — Top 3 signals ranked by `signal_score × mos_pct`
3. **All Signals Grid** — Cards filterable, collapsible (≥20% MOS)
4. **Price/m² Histogram** — 18 bins per property type, tô màu signal/outlier
5. **Full Table** — Sortable, searchable listings, 40 rows per page

## Filters mặc định

- Loại `probably_sold=1` và `possibly_duplicate=1` khỏi view
- Chỉ hiển thị listings có `price_ty > 0` và `area_m2 > 0`

## URL canonicalization

Dashboard tự sửa URL cũ khi render:
- Guland: thêm `/post/` nếu URL dạng `guland.vn/slug` (không có `/post/`)
- BatDongSan: rebuild slug từ title nếu URL bị corrupt

## Data loading (load_data)

```python
load_data(db_path) → {
    signals:       # valuation_results WHERE is_signal=1, joined listings
    all_listings:  # tất cả listings (not probably_sold, not duplicate)
    market_weekly: # median per segment
    images:        # first image per listing_id
}
```

## Key constants

```python
PROP_LABELS = {
    'dat_nen':  'Đất nền',
    'dat_vuon': 'Đất vườn',
    'nha_dat':  'Nhà đất',
    'nha_pho':  'Nhà phố',
}
HISTOGRAM_BINS = 18      # per property type
PAGE_SIZE_SIGNALS = 6    # cards per load
PAGE_SIZE_TABLE = 40     # rows per page
```
