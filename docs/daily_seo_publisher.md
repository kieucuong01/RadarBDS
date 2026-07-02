# Daily SEO Publisher

Use this doc for the Radar BDS automation that must publish exactly one new SEO
URL per successful run and move it toward the dashboard -> watchlist ->
Telegram/VIP funnel.

## Read Order

1. `../AGENTS.md`
2. `../.agents/product-marketing.md`
3. `README.md`
4. `growth_marketing_workflow.md`
5. `.agents/skills/marketing-loops/SKILL.md`
6. `.agents/skills/content-strategy/SKILL.md`
7. `.agents/skills/seo-audit/SKILL.md`
8. `.agents/skills/site-architecture/SKILL.md`
9. `.agents/skills/cro/SKILL.md`
10. `config/seo_pages.py`
11. `config/seo_locations.py`
12. `config/seo_articles.py`
13. `../.agents/seo-publish-history.md`

Read `operations.md` only when the run reaches push/deploy/live verification.

## Loop Contract

This workflow is the first Radar BDS acquisition loop. It must obey the
`marketing-loops` anatomy:

| Part | Radar BDS setting |
|---|---|
| Check cadence | Daily at the configured Codex automation time |
| Acts when | There is an unpublished topic with real search intent and a safe implementation path |
| Purpose | Bring qualified Bình Dương buyers/investors into dashboard -> watchlist -> Telegram/VIP |
| Skills used | `product-marketing`, `content-strategy`, `seo-audit`, `site-architecture`, `cro`, `schema`, `ai-seo`, `copywriting` |
| Self-check | No duplicate primary keyword + intent, no doorway page, canonical/sitemap/render verified |
| State / idempotency | `.agents/seo-publish-history.md` plus `.agents/loops/daily-seo-publisher.log` |
| Stop / bail-out | Real blocker prevents publishing/deploy/live verification; report production unchanged |
| Output | One live SEO URL, verification evidence, next topic candidate |

Do not let this become a generic "write one article" habit. Each published URL
must strengthen at least one of: topical authority, internal linking, CTA path,
watchlist activation, or a future free-tool/checklist path.

## Topic Selection Rules

- Publish exactly one new URL per successful run.
- Read `.agents/seo-publish-history.md` before choosing the topic.
- Do not repeat the same primary keyword + search intent combination.
- Prefer the highest 80/20 topic that can ship safely today.
- For the first money-keyword cluster, use broad keywords only once, then move
  to the next location or buyer-education angle instead of rewriting the same
  intent.
- Run a light `seo-audit` / `site-architecture` check before choosing the topic:
  avoid cannibalizing an existing URL, avoid orphan pages, and prefer topics that
  can link to an existing hub/location/method page.
- If the best 80/20 opportunity is a free tool or checklist, still ship one
  supporting `/kien-thuc/<slug>` URL for that run and log the tool as the next
  build candidate. Do not silently change the daily publisher into a tool build.

## URL And Content Contract

- Default article system: `/kien-thuc/<slug>`.
- Page must be indexable, canonicalized, and included in `sitemap.xml`.
- Include at least 3 FAQ items.
- Include internal links to hub, location, and method pages.
- Keep CTA path explicit: article -> dashboard -> watchlist -> Telegram/VIP.
- Keep the due-diligence caveat explicit: Radar BDS is a data filter, not a
  legal appraisal or profit guarantee.

## Repo State To Update

- Add or update `config/seo_articles.py`.
- Append one shipped entry to `../.agents/seo-publish-history.md`.
- Append one run entry to `../.agents/loops/daily-seo-publisher.log`.
- Add or update focused tests in `tests/test_public_seo.py`.
- If the article changes shared public SEO behavior, document that in the same
  commit instead of leaving workflow knowledge only in chat.

Run log format:

```text
2026-07-02T09:00+07:00 checked=1 acted=1 url="/kien-thuc/..." note="published article -> watchlist"
```

For blocked runs, log `acted=0` with the blocker. Do not log secrets, phone
numbers, original listing URLs, or other PII.

## Verification Contract

Local checks before commit:

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $py -X utf8 -m py_compile app.py config\seo_articles.py routes\public.py
& $py -X utf8 -m pytest tests\test_public_seo.py -q
```

Push + deploy:

```powershell
git push origin main
.\scripts\deploy_production.ps1
```

Live verification:

```powershell
.\scripts\verify_live_seo_article.ps1 `
  -Url "https://radarbds.vn/kien-thuc/<slug>" `
  -HeadingContains "heading marker" `
  -RequireWatchlistIntent
```

## Deploy Guardrail

`deploy_production.ps1` now auto-archives a small allowlist of known temporary
audit/report files from the VPS checkout to `/tmp/radar-bds-deploy-known-temp-*.tgz`
before deploy continues.

Important:

- This cleanup is only for the exact known temp-file allowlist embedded in the
  script.
- The deploy must still fail if any other unexpected dirty file remains.
- Report the archive path if the cleanup path was used.

## Reporting Shape

- `Che do: shipped / blocked`
- `Bai SEO moi da publish`
- `Ly do 80/20`
- `Funnel path touched`
- `Files touched`
- `Verification run`
- `Production status`
- `Next article candidate`
- `Giai thich de hieu: toi da lam marketing bang cach nao`
