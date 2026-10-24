# SEO Monthly Reports — Closed-Month Automation

This is the canonical repo doc for Radar BDS monthly market reports under `/bao-cao/*`.
It is written for human maintainers and AI coding agents (Codex/Hermes/Claude). Read this before touching report generation, `/bao-cao` hub UX, or monthly report cron automation.

## TL;DR for Codex / AI agents

Presentation uses `static/css/public_research.css` plus the report templates.
See [Research UI audit and verification](public_research_ui.md) before changing
layout. Keep closed-month data, chart summaries, source dates and filtered
dashboard destinations intact; a visual refresh must not regenerate reports.

1. Do **not** publish current/in-progress month as a formal `/bao-cao` report.
2. The monthly job publishes the **previous closed month** at `08:00` on the 1st day of each month.
3. Pipeline is script-first and deterministic; do not ask an LLM to rewrite the 14 reports manually.
4. Important files:

| Purpose | File |
|---|---|
| Monthly cron wrapper / orchestrator | `scripts/radar_monthly_report_publish.py` |
| Base master + ward report generator | `scripts/generate_monthly_report.py` |
| Rich v2/v3 enhancer | `scripts/enhance_monthly_report_rich.py` |
| Published page config | `config/seo_pages.py` |
| Report detail template | `templates/seo_report.html` |
| Report hub template | `templates/seo_report_hub.html` |
| Report/hub styles | `static/css/seo.css` |

5. Never commit runtime data: images, dumps, logs, reports, backups.
6. Always verify live rendering, not just HTTP 200.

## Production locations

| Item | Path / value |
|---|---|
| Production repo | `/opt/radar-bds/current` |
| Python | `/opt/radar-bds/.venv/bin/python` |
| Env file | `/etc/radar-bds/radar.env` |
| Service | `radar-bds.service` |
| Public domain | `https://radarbds.vn` |
| Hermes cron job | `@rb Monthly Market Reports Publish` |
| Hermes job id | `5f5c7eac733d` |
| Cron schedule | `0 8 1 * *` |
| Cron script | `/opt/radar-bds/current/scripts/radar_monthly_report_publish.py` |

The cron script is now inside the repository, not only in Hermes profile storage. This is intentional so Codex and future agents can inspect, edit, commit, and restore the full workflow from Git.

## Pipeline

```text
scripts/radar_monthly_report_publish.py
  ├─ chooses previous closed month by default
  ├─ runs scripts/generate_monthly_report.py --all --month MM --year YYYY
  ├─ runs scripts/enhance_monthly_report_rich.py --month MM --year YYYY
  ├─ restarts radar-bds if config/seo_pages.py changed
  ├─ verifies master + 13 ward report URLs, chart/card/link counts, sitemap
  └─ commits + pushes config/seo_pages.py if changed
```

### Outputs per month

| Report type | Count | URL pattern | Expected structure |
|---|---:|---|---|
| Master TDM report | 1 | `/bao-cao/bds-binh-duong-thang-MM-YYYY` | 2 charts, 0 signal cards, 13 child ward report links, SEO/internal link block |
| Ward reports | 13 | `/bao-cao/{ward_slug}-thang-MM-YYYY` | Up to 4 charts (empty price charts omitted), up to 6 saved examples, MOS/type links, filtered dashboard CTA |

## Manual commands

Run from the VPS.

### Safe dry-run against an already-published closed month

```bash
python3 \
  /opt/radar-bds/current/scripts/radar_monthly_report_publish.py \
  --month 06 --year 2026 --dry-run
```

Dry-run runs generator/enhancer in dry-run mode and verifies live pages when the month already exists. It does not restart, commit, or push.

### Normal monthly publish for a specific closed month

```bash
python3 \
  /opt/radar-bds/current/scripts/radar_monthly_report_publish.py \
  --month 07 --year 2026
```

### Cron/default mode

```bash
python3 \
  /opt/radar-bds/current/scripts/radar_monthly_report_publish.py
```

Default mode computes the previous month from the current date. On `2026-08-01`, it publishes `07/2026`.

### Lower-level scripts

```bash
# Base reports only
sudo -u radar /opt/radar-bds/.venv/bin/python \
  scripts/generate_monthly_report.py --month MM --year YYYY --all

# Rich v2/v3 enhancement only; base entries must already exist
sudo -u radar /opt/radar-bds/.venv/bin/python \
  scripts/enhance_monthly_report_rich.py --month MM --year YYYY

# Dry-run rich enhancer
sudo -u radar /opt/radar-bds/.venv/bin/python \
  scripts/enhance_monthly_report_rich.py --month MM --year YYYY --dry-run
```

## Data source and query rules

Reports are based on `listings` in PostgreSQL.

| Rule | Detail |
|---|---|
| Source | `source = 'facebook'` |
| Month window | `crawled_at::timestamp >= month_start AND crawled_at::timestamp < month_end` |
| Raw volume | `source = 'facebook'`, loại blacklist/hidden nhưng vẫn gồm repost |
| Statistical basis | Chỉ canonical lot; loại `duplicate_of_id`, `possibly_duplicate`, `is_outlier`, `probably_sold`, blacklist và hidden |
| Do not use active filter for monthly stats | Monthly reports should include the month crawl window, not only currently active listings |
| Median | PostgreSQL has no `MEDIAN()`; use `PERCENTILE_CONT(0.5)` |
| Numeric columns | `price_per_m2`, `price_ty`, `area` are text-ish; cast with `::numeric` and guard invalid area strings |
| Signals | Latest valuation + `services.signal_quality.actionable_signal_sql()` và `actionable_listing_sql()` |
| Placeholders | Project DB wrapper expects `?`, not `%s` |

Known TDM wards:

```text
Tân An, Hiệp An, Tương Bình Hiệp, Định Hòa, Chánh Mỹ, Phú Mỹ,
Phú Cường, Phú Hòa, Phú Lợi, Hiệp Thành, Chánh Nghĩa, Phú Tân, Hòa Phú
```

Always handle both Vietnamese diacritics and non-diacritics variants when querying wards. Snapshot phải lưu riêng `raw_listing_count`, `basis_count`, `actionable_signal_count`, `data_as_of` và `data_contract_version`.

## Required SEO/internal linking rules

### Master TDM report

The master report must act as a hub. It must include exactly 13 child report links in `page.local_links`:

```python
"local_links_title": "Tổng hợp 13 báo cáo phường Thủ Dầu Một tháng MM/YYYY",
"local_links": [
    {
        "label": "Báo cáo Hiệp An tháng MM/YYYY",
        "href": "/bao-cao/hiep-an-thang-MM-YYYY",
        "description": "646 tin rao, giá đất nền 16.0 tr/m², 54 tín hiệu đáng chú ý.",
    },
    # ... 12 more ward reports, sorted by listing count desc
]
```

Do not replace this master child-link section with generic location links. Broader SEO links belong in `page.report.internal_links` / `.report-seo-links`.

### Ward reports

Ward reports should include contextual links:

| Link intent | Expected filter/path |
|---|---|
| MOS ≥ 10% | dashboard with `ward=<current ward>` + `mos_min=10` |
| MOS ≥ 15% | dashboard with `ward=<current ward>` + `mos_min=15` |
| Đất nền | dashboard with `ward=<current ward>` + `prop_type=dat_nen` |
| Nhà đất | dashboard with `ward=<current ward>` + `prop_type=nha_dat` |
| Listing cards | internal `/listing/<id>`, not the raw source URL |
| Back to master | `/bao-cao/bds-binh-duong-thang-MM-YYYY` |

Use safe language: “Tin đáng kiểm tra”, “Tin dưới giá cơ sở”, “MOS tốt”, “Cơ hội cần thẩm định”. Do not promise “deal ngon”.

## Verification checklist

A completed monthly publish is only done when all checks pass:

```bash
# Syntax
sudo -u radar bash -lc 'cd /opt/radar-bds/current && \
  python3 -m py_compile \
    scripts/radar_monthly_report_publish.py \
    scripts/generate_monthly_report.py \
    scripts/enhance_monthly_report_rich.py \
    config/seo_pages.py && \
  git diff --check'

# Live hub/master
curl -fsS https://radarbds.vn/bao-cao >/dev/null
curl -fsS https://radarbds.vn/bao-cao/bds-binh-duong-thang-MM-YYYY >/dev/null

# Sitemap
curl -fsS https://radarbds.vn/sitemap.xml >/dev/null
```

Preferred full check:

```bash
python3 \
  /opt/radar-bds/current/scripts/radar_monthly_report_publish.py \
  --month MM --year YYYY --dry-run
```

Expected live structure:

| Page | Check |
|---|---|
| `/bao-cao` | HTTP 200, thumbnails/search/filter still work |
| master report | HTTP 200, 2 `<canvas>`, 13 child ward report links, sitemap includes master and 13 wards |
| each ward report | HTTP 200, 4 `<canvas>`, 0–6 `.report-signal-card` theo số actionable thực tế, MOS/type links, filtered dashboard CTA |
| browser sample | 0 JS console errors |
| mobile hub | header/nav visually OK around 390px width |

## Git and deploy behavior

- The cron wrapper commits only `config/seo_pages.py` when monthly report content changes.
- Code/doc/script changes should be committed manually by the developer/agent.
- Facebook broker profile config lives in PostgreSQL `facebook_crawl_profiles`; `data/facebook_profiles.json` should not remain dirty on the VPS.
- After editing scripts or templates, commit and push to `origin/main`.

## VPS cleanup safety

Safe to clean:

```text
/tmp/*
__pycache__
Python/npm/uv caches
old logs after rotation
ad-hoc fix_*.py/query_*.py temp scripts
```

Do not delete:

```text
/opt/radar-bds/current/scripts/radar_monthly_report_publish.py
/opt/radar-bds/current/scripts/generate_monthly_report.py
/opt/radar-bds/current/scripts/enhance_monthly_report_rich.py
/opt/radar-bds/current/config/seo_pages.py
/home/hermesops/.hermes/profiles/portfolio-ops/cron/
```

The monthly report workflow itself is now source-controlled in the repo. Hermes cron metadata is still in the Hermes profile, but the executable script is in Git.

## Common failure modes

| Symptom | Likely cause | Fix |
|---|---|---|
| Report HTTP 200 but empty sections | Wrong dict field names in `SEO_PAGES` | Compare template field names in `templates/seo_report.html`; do not rely only on 200 |
| Chart canvas present but empty | Missing `window.CHART_DATA` or Chart.js init issue | Inspect `templates/seo_report.html` and browser console |
| All months show same numbers | Query used unfiltered `base` instead of month-filtered `month_base` | Fix every stats query in `query_ward_stats()` to use month window |
| Master report has only 2 generic location links | A hard-coded override replaced generated child links | Restore `local_links` to 13 `/bao-cao/{ward}-thang-MM-YYYY` links |
| Cron produces no output | Script stdout empty or job script path wrong | Check Hermes job `5f5c7eac733d` and script path |
| Commit fails due dirty runtime data | Runtime files such as images, dumps, logs, reports, or backups are dirty | Do not stage them; stage only intended config/code/docs |

## Report archive pagination — 21/10/2026

`/bao-cao` renders at most 12 archive cards plus the latest featured report on
the first unfiltered page. Page 2 onward has a distinct self-canonical URL and
title, real previous/next/page links, and JSON-LD containing only rendered
reports. Invalid or out-of-range page numbers return 404.

GET filters `city`, `ward`, `period`, `q` run on the entire published archive
before pagination. Filtered views include the latest report if it matches,
restore controls server-side, and use noindex/follow to avoid indexing search
combinations. Search supports Vietnamese accents or unaccented input. Filter
changes reset pagination. The form and city/page links also work without JS;
JS only auto-submits selects and emits filter context without raw search text.
Snapshot contents, publishing jobs and report detail pages are unchanged.

Tests: `tests/test_report_hub_pagination.py`, `tests/test_public_content_hubs.py`,
`tests/test_public_seo.py`, `tests/test_public_research_ui.py`.

## Downloadable PDF reports

Each closed-month report can have a prebuilt A4 PDF with its original charts,
tables, insights and methodology. The detail page and featured hub card show
**Tải báo cáo PDF** only after the current artifact exists. No signup is required.
The download route `/bao-cao/<slug>/pdf?v=<snapshot-version>` sends an attachment,
with noindex and a canonical link back to the HTML report. It never starts a
browser or queries live market data. Old versions are not served as current.

`scripts/build_report_pdfs.py` uses the existing Playwright dependency, local web
fonts and the same Chart.js version as the report page. It waits for every chart
and font, checks the web snapshot matches the job, prints with
`static/css/report_print.css`, and atomically publishes the PDF. Internal links
in the PDF point at the public domain, including when built against localhost.
It skips analytics and lead capture submission. Failed renders fail the job and
leave existing artifacts intact; a missing artifact leaves the HTML readable.

Runtime files live in ignored `reports/monthly-pdf/`. The fingerprint includes
the report config and print/template code. Deploying a layout change requires a
backfill after restarting the web service. Do not commit generated PDFs.

```bash
# Once per environment, as the same user/env as the monthly job:
PLAYWRIGHT_SKIP_BROWSER_GC=1 /opt/radar-bds/.venv/bin/python -m playwright install chromium --only-shell

# Backfill all existing published reports (does not regenerate market data):
/opt/radar-bds/.venv/bin/python scripts/build_report_pdfs.py --all

# Only one closed month, or one report for visual QA:
/opt/radar-bds/.venv/bin/python scripts/build_report_pdfs.py --month 09 --year 2026
/opt/radar-bds/.venv/bin/python scripts/build_report_pdfs.py --slug tan-an-thang-09-2026
```

The normal monthly publisher prebuilds that month's PDFs after the web restart
and before live verification. Dry-run never creates files. PDF checks:
`tests/test_report_pdf.py`; visually inspect a master and ward PDF after any
layout change, including all pages, Vietnamese text, chart labels, tables and
page numbers. Build against local origin, not the CDN, to avoid stale snapshots.

## Buyer report contract (25 October 2026)

One shared buyer flow serves web and PDF: summary/limits, budget bands, price
ranges by property type, ward comparisons, observed history, saved examples,
coverage/source context, and a viewing/total-cost checklist. No audience split.
`services/report_buyer.py` is a pure adapter over frozen config facts; report
requests and downloads never query current listing prices for historical tables.
`static/css/report_buyer.css` supplements the shared blue public brand.

Published legacy reports retain their saved facts. Prices/trends with fewer than
15 samples in the actual property segment are suppressed; selected-MOS percentages
and the weighted average of ward medians are removed from presentation. Raw
collection volume can include reposts and is not market inventory. Missing budget
quartiles/history/model dates remain explicitly unavailable. Current discovery
links are Facebook-only, one month, with ward/type/budget filters; they are clearly
labelled current and are not historical stock counts.

Newly generated closed-month reports capture `report.buyer_snapshot`, schema 1,
contract `buyer-cohort-v1`, through `services/report_buyer_snapshot.py`. This packet
contains counts and P25/median/P75 for total asking price, area and price/m² by
type, half-open budget band and canonical ward. Sale-only Facebook cohorts use
canonical visibility plus extraction/valuation quality gates and consistent
price/area measurements. There is a separate qualified/excluded count. Every
price group requires at least 15 samples; zero samples and missing values differ.

Prices are **current known asking prices of records collected in that period at
generation**, not proof of prices observed precisely at month-end. The packet
stores period boundaries and the actual generation timestamp. Observed price drops
require successive stored old/new prices with an event inside the period. Radar
observation duration is not time-to-sale. No original seller URL or phone is stored
in the public packet. Source-policy and valuation inputs are unchanged.

The enhancer preserves existing published packets and all legacy reports. Trend
prices/counts use the same qualified packet as the buyer section; previous periods
are read only from compatible frozen packets, never recalculated from today's
prices. Missing historical counts display “Chưa lưu”, not synthetic zero. Context
links route to planning/legal/source hubs; no infrastructure event is asserted
without a verified saved source. The PDF version also tracks related ward facts.
After a layout release restart the app and rebuild all PDFs against the origin;
this does not regenerate historical market data. Keep artifact directories group
writable for the monthly job (`umask 0002`).

Validation: `tests/test_report_buyer.py`, `tests/test_report_buyer_snapshot.py`
(including isolated PostgreSQL SQL/history/alias checks), existing report/PDF/
public UI suites, plus all-page visual inspection of master/large/small ward PDFs.

## Related docs

- `AGENTS.md` — fast entry point for AI agents.
- `docs/README.md` — doc routing map.
- `docs/agent_playbook.md` — change discipline and verification matrix.
- `docs/operations.md` — deploy/VPS smoke checks.
