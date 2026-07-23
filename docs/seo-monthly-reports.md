# SEO Monthly Reports — Closed-Month Automation

This is the canonical repo doc for Radar BDS monthly market reports under `/bao-cao/*`.
It is written for human maintainers and AI coding agents (Codex/Hermes/Claude). Read this before touching report generation, `/bao-cao` hub UX, or monthly report cron automation.

## TL;DR for Codex / AI agents

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

5. Never commit runtime data: `data/facebook_profiles.json`, images, dumps, logs, reports, backups.
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
| Ward reports | 13 | `/bao-cao/{ward_slug}-thang-MM-YYYY` | 4 charts, 6 signal-style listing cards, MOS links, property-type links, filtered dashboard CTA |

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
| Exclusions | `is_blacklisted = 0`, `review_hidden = 0` |
| Do not use active filter for monthly stats | Monthly reports should include the month crawl window, not only currently active listings |
| Median | PostgreSQL has no `MEDIAN()`; use `PERCENTILE_CONT(0.5)` |
| Numeric columns | `price_per_m2`, `price_ty`, `area` are text-ish; cast with `::numeric` and guard invalid area strings |
| Signals | `is_hot = 1 OR price_dropped = 1` for base signal counts |
| Placeholders | Project DB wrapper expects `?`, not `%s` |

Known TDM wards:

```text
Tân An, Hiệp An, Tương Bình Hiệp, Định Hòa, Chánh Mỹ, Phú Mỹ,
Phú Cường, Phú Hòa, Phú Lợi, Hiệp Thành, Chánh Nghĩa, Phú Tân, Hòa Phú
```

Always handle both Vietnamese diacritics and non-diacritics variants when querying wards.

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
| each ward report | HTTP 200, 4 `<canvas>`, 6 `.report-signal-card`, MOS/type links, filtered dashboard CTA |
| browser sample | 0 JS console errors |
| mobile hub | header/nav visually OK around 390px width |

## Git and deploy behavior

- The cron wrapper commits only `config/seo_pages.py` when monthly report content changes.
- Code/doc/script changes should be committed manually by the developer/agent.
- Runtime file `data/facebook_profiles.json` is allowed to remain dirty on the VPS and must not be committed.
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
| Commit fails due dirty runtime data | `data/facebook_profiles.json` dirty | Do not stage it; stage only intended config/code/docs |

## Related docs

- `AGENTS.md` — fast entry point for AI agents.
- `docs/README.md` — doc routing map.
- `docs/agent_playbook.md` — change discipline and verification matrix.
- `docs/operations.md` — deploy/VPS smoke checks.
