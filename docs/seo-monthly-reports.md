# SEO Monthly Reports — Architecture & Operations

Monthly market reports for Bình Dương / Thủ Dầu Một, generated from live Facebook listing data.

## Quick Start (Generate Reports)

```bash
# Generate all reports for a month
sudo -u radar /opt/radar-bds/.venv/bin/python \
  /opt/radar-bds/current/scripts/generate_monthly_report.py \
  --all --month MM --year YYYY

# Generate master + single ward
sudo -u radar /opt/radar-bds/.venv/bin/python \
  /opt/radar-bds/current/scripts/generate_monthly_report.py \
  --month 07 --year 2026 --ward "Phú Mỹ"

# Restart after injecting
sudo systemctl restart radar-bds
```

## System Overview

```
generate_monthly_report.py
  └─ query_ward_stats(ward, month_start, month_end)
       └─ listings table (PostgreSQL)
  └─ generate_master_report(month, year)
       └─ → dict entry (SEO_PAGES)
  └─ generate_ward_report(ward, month, year)
       └─ → dict entry (SEO_PAGES)
  └─ inject_report(config_path, entry)
       └─ injects into config/seo_pages.py

templates/seo_landing.html
  └─ renders page dict by variant
       ├─ variant: "report"   → ward reports
       ├─ variant: "hub"      → /bao-cao index
       └─ variant: "market"   → location pages

config/seo_pages.py
  └─ SEO_PAGES dict — all page content
       ├─ "bao-cao"             → hub entry
       ├─ "bao-cao/bds-binh-duong-thang-MM-YYYY"  → master report
       └─ "bao-cao/{ward_slug}-thang-MM-YYYY"     → ward reports
```

## Page structure

Each report entry in `SEO_PAGES` contains these sections rendered by the template:

| Field | Type | Description |
|---|---|---|
| `variant` | `"report"` | Route type |
| `path` | string | URL path |
| `title`, `description`, `keywords` | strings | SEO meta |
| `hero_*` | strings/bools/lists | Hero banner |
| `property_card` | dict | Sidebar property card |
| `value_cards` | list[dict] | 3 value proposition cards |
| `report` | dict | Main content: metrics, area_rows, insights, methodology |
| `charts` | list[dict] | Chart.js data (bar/doughnut) |
| `final_cta` | dict | CTA section at bottom |
| `local_links` | list[dict] | Internal link cards |

## Charts

Chart.js v4.4.4 via CDN. Data embedded as `window.CHART_DATA` JSON in page.

**Master report** (2 charts):
- `ward-supply-chart` — bar chart of listings per ward (sorted desc)
- `ward-price-chart` — bar chart of median price per ward

**Ward report** (2 charts):
- `type-dist-chart` — doughnut of property type distribution
- `type-price-chart` — bar chart of median price by property type

Charts render in the `.report-chart-grid` section, before the metric grid.

## URL Structure

```
/bao-cao                                 → Hub (month selector)
/bao-cao/bds-binh-duong-thang-{MM}-{YYYY} → Master report (all 13 wards)
/bao-cao/{ward_slug}-thang-{MM}-{YYYY}    → Ward report
```

Routes in `routes/public.py`:
- `GET /bao-cao` → `seo_bao_cao_index()` → `seo_landing_page(slug="bao-cao")`
- `GET /bao-cao/<path:report_slug>` → `seo_market_report()` → `seo_landing_page(slug=f"bao-cao/{report_slug}")`

## Wards

13 wards of Thủ Dầu Một:

| Ward | Slug | Typical data volume |
|---|---|---|
| Hiệp An | `hiep-an` | ~1,200 listings |
| Tân An | `tan-an` | ~965 |
| Định Hòa | `dinh-hoa` | ~780 |
| Phú Mỹ | `phu-my` | ~720 |
| Tương Bình Hiệp | `tuong-binh-hiep` | ~695 |
| Phú Tân | `phu-tan` | ~620 |
| Phú Hòa | `phu-hoa` | ~565 |
| Hiệp Thành | `hiep-thanh` | ~500 |
| Phú Lợi | `phu-loi` | ~375 |
| Chánh Nghĩa | `chanh-nghia` | ~264 |
| Chánh Mỹ | `chanh-my` | ~233 |
| Hòa Phú | `hoa-phu` | ~67 |
| Phú Cường | `phu-cuong` | ~54 |

## Data Source

- **Table**: `listings` in PostgreSQL (local VPS)
- **Source filter**: `source = 'facebook'`
- **Exclusions**: `is_blacklisted = 0`, `review_hidden = 0`
- **Month filter**: `crawled_at::timestamp >= {month_start} AND crawled_at::timestamp < {month_end}`
- **Price stats**: `PERCENTILE_CONT(0.5)` for median, filtered by `price_per_m2 > 0 AND price_per_m2 < 500`
- **Signals**: `is_hot = 1 OR price_dropped = 1`
- Use `?` placeholder syntax (project wrapper translates to `%s`)

## Key Queries (for reference)

```sql
-- Total listings in a ward for a month
SELECT COUNT(*) FROM listings 
WHERE ward = '{ward}' AND source = 'facebook' 
  AND is_blacklisted = 0 AND review_hidden = 0
  AND crawled_at::timestamp >= '{start}' AND crawled_at::timestamp < '{end}';

-- Median price per m²
SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY price_per_m2::numeric)
FROM listings WHERE ward = '{ward}' AND property_type = 'dat_nen'
  AND price_per_m2::numeric > 0 AND price_per_m2::numeric < 500
  AND crawled_at::timestamp >= '{start}' AND crawled_at::timestamp < '{end}';
```

## Adding a new month

1. Run the script:
   ```bash
   sudo -u radar /opt/radar-bds/.venv/bin/python \
     scripts/generate_monthly_report.py --all --month MM --year YYYY
   ```
2. Restart: `sudo systemctl restart radar-bds`
3. Verify: `curl -s https://radarbds.vn/bao-cao/bds-binh-duong-thang-MM-YYYY`
4. Update hub entry in `config/seo_pages.py`: add a new entry in `"bao-cao"`'s `local_links`

## Adding a new ward

1. Add ward + slug to `TDM_WARDS` and `WARDS_SLUG` in `generate_monthly_report.py`
2. Add ward to `no_diacritics` dict if it has non-diacritics variant
3. Regenerate: `--all --month MM --year YYYY`
4. Optionally add a tagline in `titles` dict

## Hub Page

Located at `/bao-cao`. Entry in `SEO_PAGES["bao-cao"]`:
- `local_links`: links to each month's master report
- `value_cards`: describes report types
- `hero`: intro text

## MoM Comparison

The script compares the requested month against the previous month's data. The comparison uses `generate_insights()` which computes delta in median price and supply count between `month` and `month-1`.

## Known Limitations

- Wards with < 20 listings in a month may have unreliable median prices
- June vs July comparison uses raw listing counts, not deduplicated lots
- Some wards have mixed diacritics in the DB (e.g. both "Phu My" and "Phú Mỹ") — handled by the `no_diacritics` fallback
