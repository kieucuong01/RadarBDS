# Daily SEO Publisher

This workflow is now a Hermes-compatible SEO runbook. Codex cron automations for
Radar BDS marketing are retired.

## Goal

Bring qualified real-estate searchers into Radar BDS pages and then into the
dashboard signal feed.

```text
SEO query
  -> public page/report/article
  -> dashboard filtered by ward/cluster when possible
  -> signal card review
  -> contact / lead CTA
```

Do not make watchlist, Telegram, or VIP upgrade the default SEO funnel.

## Read Order

1. `../AGENTS.md`
2. `../.agents/product-marketing.md`
3. `README.md`
4. `growth_marketing_workflow.md`
5. `hermes_marketing_workflow.md`
6. `.agents/skills/content-strategy/SKILL.md`
7. `.agents/skills/seo-audit/SKILL.md`
8. `.agents/skills/ai-seo/SKILL.md`
9. `.agents/skills/analytics/SKILL.md`
10. `config/seo_pages.py`
11. `config/seo_locations.py`
12. `config/seo_articles.py`
13. `../.agents/seo-publish-history.md`
14. `../.agents/loops/daily-seo-publisher.log`

Read `operations.md` only when the run will commit, deploy, or verify
production.

## Decision Order

Each run checks daily but does not have to publish daily.

1. Fix state drift if `config/seo_articles.py`, publish history, sitemap, or
   live production disagree.
2. Refresh an existing high-intent location/report page when it can rank better.
3. Add internal links from reports/articles to the right filtered dashboard URL.
4. Publish one new SEO URL only when there is a non-duplicate intent with clear
   search demand.
5. Draft one Facebook post from the same data atom with UTM.
6. Skip and report why.

The best run is often `checked=1 acted=0` when there is no useful change.

## Page Standard

Every SEO page or article must include:

- one clear primary intent;
- a title/H1 that matches that intent;
- answer-first sections useful for Google and AI assistants;
- visible date/source/methodology/caveat;
- FAQ and structured data when relevant;
- internal links to hub/location/report pages;
- a CTA to `/?tab=signals` or a filtered URL such as
  `/?tab=signals&ward=Hi%E1%BB%87p+Th%C3%A0nh`;
- no invented market numbers, testimonials, legal certainty, or guaranteed
  profit claims.

## State And Idempotency

Successful SEO runs update:

- `../.agents/seo-publish-history.md`
- `../.agents/loops/daily-seo-publisher.log`

Run log format:

```text
2026-07-18T09:00+07:00 checked=1 acted=1 url="/kien-thuc/..." note="published -> filtered dashboard/contact"
```

Blocked or skipped runs also get logged with `acted=0`. Do not log secrets,
phone numbers, original listing URLs, or other PII.

## Verification

Local checks before commit:

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $py -X utf8 -m py_compile app.py config\seo_articles.py config\seo_pages.py routes\public.py
& $py -X utf8 -m pytest tests\test_public_seo.py tests\test_traffic_seo_aio.py -q
```

Live verification after deploy:

```powershell
.\scripts\verify_live_seo_article.ps1 `
  -Url "https://radarbds.vn/kien-thuc/<slug>" `
  -HeadingContains "heading marker"
```

For Hermes on Linux, use the equivalent checks documented in
`docs/hermes_marketing_workflow.md`.

## Reporting Shape

```text
Mode: shipped / refreshed / drafted / skipped / blocked
SEO URL:
Primary intent:
Why 80/20:
Dashboard/filter URL:
Contact path:
AI SEO checks:
Verification:
State updated:
Next candidate:
```
