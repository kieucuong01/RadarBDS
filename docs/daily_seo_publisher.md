# Daily SEO Publisher — Radar BDS (`/tin-tuc`)

This is the canonical repo runbook for the daily `@rb Daily SEO Publish + Social Post` Hermes cron and for Codex/AI agents asked to publish Radar BDS SEO content.

## TL;DR for Codex / AI agents

1. Read `../AGENTS.md`, `docs/README.md`, this file, then `docs/radar_bds_90_day_seo_roadmap.md`.
2. Run the context helper first; do not load raw DB dumps into the prompt:
   ```bash
   sudo -u radar /opt/radar-bds/.venv/bin/python \
     /opt/radar-bds/current/scripts/radar_daily_seo_context.py --days 14 --limit 8
   ```
3. Publish **1 SEO/AIO/AI-SEO article per day** on `/tin-tuc/<slug>` when there is no production blocker.
4. Draft **1 social post** from the same data atom for Facebook/Zalo/group handoff.
5. Use real production DB numbers only; no invented counts, prices, legal certainty, testimonials, or guaranteed profit.
6. Verify production URL, rendered content, sitemap, and logs before reporting done.
7. Create a social queue item with `scripts/radar_social_queue.py`; Page auto-post is currently enabled through `@rb Daily Social Auto Post` / `scripts/radar_social_auto_post.py`.
8. Commit + push repo changes; do not commit runtime data such as `data/facebook_profiles.json`.

## Current automation

| Item | Value |
|---|---|
| Hermes job | `@rb Daily SEO Publish + Social Post` |
| Job ID | `d4d23485acd7` |
| Schedule | `10 18 * * *` |
| Delivery | Origin Telegram chat |
| Mode | LLM-driven cron, not `no_agent` |
| Skills | `radar-bds-seo`, `portfolio-project-ops` |
| Toolsets | `terminal`, `file`, `web`, `browser` |
| Repo helper | `scripts/radar_daily_seo_context.py` |
| Main content config | `config/seo_articles.py` |
| Article route | `/tin-tuc/<slug>` |
| Legacy route | `/kien-thuc/*` — do not publish new content here |

Daily SEO content needs judgment/writing, so it is **not** script-only like monthly reports. The token-light part is the repo helper script: it emits compact article inventory + ward data pulse so the cron/agent does not need raw table dumps.

## Funnel goal

```text
SEO/AIO query
  -> /tin-tuc/<slug> article
  -> filtered dashboard or related /bao-cao report
  -> user reviews signal cards
  -> contact / lead CTA
```

Do not make Telegram/VIP/watchlist the default SEO funnel. The primary CTA is to the dashboard signal feed, preferably filtered by ward/property type/MOS.

## URL taxonomy

| Content type | Path |
|---|---|
| Daily SEO/AIO/AI-SEO article, news, evergreen guide, comparison, buying guide | `/tin-tuc/<slug>` |
| Monthly/ward market reports | `/bao-cao/<slug>` |
| Legacy knowledge articles | `/kien-thuc/<slug>` |

Rules:

- New daily content goes to `/tin-tuc/<slug>`.
- Do not publish new content to `/kien-thuc`.
- Do not put formal monthly report pages under `/tin-tuc`; use `/bao-cao` after the month closes.

## Repo files

| Purpose | File |
|---|---|
| Token-light daily context | `scripts/radar_daily_seo_context.py` |
| Article definitions | `config/seo_articles.py` |
| Public routes | `routes/public.py` |
| Route implementation / sitemap | `app.py` |
| Article template | `templates/seo_article.html` |
| Header/nav | `templates/partials/seo_header.html` |
| SEO styles | `static/css/seo.css` |
| Verification script | `scripts/verify_live_seo_article.ps1` |
| Tests | `tests/test_public_seo.py`, `tests/test_public_content_hubs.py` |
| Social queue/auto-post | `scripts/radar_social_queue.py`, `scripts/browser_use_page_post.py`, `scripts/radar_social_auto_post.py`, `docs/social-care-workflow.md` |

## Daily decision order

Use `docs/radar_bds_90_day_seo_roadmap.md` as the strategy source of truth. Daily topic selection is not just “which ward has signals today”; it must build topical authority over time.

Each daily run should do the smallest high-impact action:

1. Check production health and state drift: sitemap, latest articles, repo status.
2. Run `scripts/radar_daily_seo_context.py` for compact current data.
3. Score candidate actions with the 100-point rule from the roadmap:
   - 30 long-lived search intent,
   - 25 Radar proprietary data advantage,
   - 20 funnel linkage to dashboard/report/location/tool,
   - 15 no cannibalization,
   - 10 social reuse.
4. If score ≥ 70: publish one new `/tin-tuc/<slug>` article.
5. If score is 50–69 or the intent already exists: refresh/update an existing article or add internal links.
6. Draft one social post from the same data atom and create a queue file with `scripts/radar_social_queue.py`.
7. If explicitly approved, use `scripts/browser_use_page_post.py`; otherwise hand off queue path + draft.
8. Verify live and commit/push.

Current early-stage default mix: 5 new articles/week, 1 refresh/internal-link day/week, 1 optional strategy/social-only day only if there is a real blocker. After roughly 60–90 useful URLs, shift to 3 new + 2 refresh + 1 internal-link + 1 strategy/social per week.

If there is a production blocker, fix/report the blocker first. Otherwise default expectation is `acted=1` daily.

## Article quality bar

Every daily article should include:

- Answer-first intro, ideally 40–60 words.
- Real production DB data with source/freshness note.
- Price paired with property type: `đất nền` vs `nhà đất`.
- Summary cards.
- At least one useful data table.
- A simple chart/visual if enough data exists.
- FAQ schema.
- Internal links to dashboard/report/location pages.
- Safety caveat: Radar is initial data filtering, not legal/valuation/profit guarantee.

Tone:

- Plain Vietnamese for ordinary buyers/sellers.
- Use “giá trung vị” where report/data standards require it; explain simply when needed.
- Avoid jargon-heavy wording; explain “dấu hiệu đáng chú ý”, “giá rao”, “nguồn và ngày cập nhật”.
- Avoid aggressive sales claims like “deal ngon”. Use “tin đáng kiểm tra”, “cần thẩm định”.

## Article config requirements

`config/seo_articles.py` contains `SEO_ARTICLES` dict entries. New daily article entries must have:

```python
"slug-here": {
    "variant": "knowledge",
    "path": "/tin-tuc/slug-here",
    "title": "... | Radar BDS",
    "description": "...",
    "keywords": "...",
    "breadcrumb_label": "...",
    "hero_badge": "Tin tức BĐS Bình Dương",
    "hero_title": "...",
    "hero_text": "...",
    "scope_label": "Thủ Dầu Một · <phường/chủ đề>",
    "hero_checks": [...],
    "primary_cta": "Mở dashboard ...",
    "primary_href": "/?tab=signals&ward=...",
    "secondary_cta": "Xem báo cáo liên quan",
    "secondary_href": "/bao-cao/....",
    "map_label": "Tin tức / ...",
    "hero_metric": {...},
    "property_card": {...},
    "local_links_title": "Đọc tiếp",
    "local_links": [...],
    "faq": [{"q": "...", "a": "..."}],
    "article": {
        "published_at": "YYYY-MM-DD",
        "modified_at": "YYYY-MM-DD",
        "intro": ["...", "..."],
        "summary_cards": [...],
        "data_tables": [...],
        "charts": [...],
        "sections": [...],
        "checklist": [...],
    },
    "final_cta": {...},
}
```

Important pitfalls:

- Hyphenated slug keys must be quoted.
- Do not use raw `repr()` output blindly if it creates field names/templates that do not match.
- `seo_article.html` silently skips missing optional fields; HTTP 200 alone is not enough.
- Article URLs in sitemap come from `SEO_ARTICLES[*]["path"]`.

## Safe publish procedure

Use the setgid-safe pattern; files under `/opt/radar-bds/current` are owned by `radar`.

```bash
cd /opt/radar-bds/current

# 1) Context
sudo -u radar /opt/radar-bds/.venv/bin/python \
  scripts/radar_daily_seo_context.py --days 14 --limit 8

# 2) Edit config/seo_articles.py with the new /tin-tuc entry.
# Prefer a small Python update script copied/chowned into the repo when inserting dict blocks.

# 3) Syntax + tests
sudo -u radar python3 -m py_compile app.py routes/public.py config/seo_articles.py
sudo -u radar /opt/radar-bds/.venv/bin/python -m pytest \
  tests/test_public_content_hubs.py tests/test_public_seo.py -q

# 4) Restart
sudo systemctl restart radar-bds

# 5) Live verify
curl -fsS https://radarbds.vn/tin-tuc/<slug> >/dev/null
curl -fsS https://radarbds.vn/sitemap.xml | grep '/tin-tuc/<slug>'
sudo journalctl -u radar-bds --since '2 min ago' --no-pager | grep -E 'Traceback|jinja2|NameError|500' || true

# 6) Commit/push
git add app.py routes/public.py config/seo_articles.py templates/ static/ docs/ scripts/
git commit -m "publish daily SEO article <short-topic>"
git push
```

Use `git add <specific files>` instead of broad `git add .` when `data/facebook_profiles.json` or runtime files are dirty.

## Production verification checklist

After publish or patch:

- `/tin-tuc` returns 200.
- New `/tin-tuc/<slug>` returns 200.
- Canonical link matches the live URL.
- Rendered page contains the H1, answer-first intro, table/chart, FAQ, internal links, CTA.
- Dashboard CTA has relevant filters (`tab=signals`, ward/property type/MOS when applicable).
- `sitemap.xml` includes the new URL and has no obvious non-200 report/article URLs.
- Browser console has 0 JS errors on the new article.
- `journalctl -u radar-bds` has no new Traceback/Jinja2/NameError errors.
- Commit and push completed.

## Social post output

Use `docs/social-care-workflow.md` for the optimized queue-first social workflow. Every daily run should include one handoff-ready social draft and, when possible, a queue JSON file:

```text
Hook:
Data point:
Short interpretation:
CTA:
URL:
Hashtags:
```

For @rb, anh has approved auto-post while the user base is small. The daily SEO run should create the queue/social draft; the separate no-agent cron posts the latest queue/article through browser-use and dedupes by `slug:article_date`. Switch back to review/queue mode if anh asks to pause.

## Reporting shape back to anh Cường

```text
Mode: shipped / refreshed / blocked
SEO URL:
Primary intent:
Data used:
Dashboard/filter URL:
Social draft:
Verification:
Commit:
Next candidate:
```

Keep it concise. Always include the production URL when shipped.
