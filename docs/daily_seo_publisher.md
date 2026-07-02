# Daily SEO Publisher

Use this doc for the Radar BDS automation that must publish exactly one new SEO
URL per successful run and move it toward the dashboard -> watchlist ->
Telegram/VIP funnel.

## Read Order

1. `../AGENTS.md`
2. `../.agents/product-marketing.md`
3. `README.md`
4. `growth_marketing_workflow.md`
5. `config/seo_pages.py`
6. `config/seo_locations.py`
7. `config/seo_articles.py`
8. `../.agents/seo-publish-history.md`

Read `operations.md` only when the run reaches push/deploy/live verification.

## Topic Selection Rules

- Publish exactly one new URL per successful run.
- Read `.agents/seo-publish-history.md` before choosing the topic.
- Do not repeat the same primary keyword + search intent combination.
- Prefer the highest 80/20 topic that can ship safely today.
- For the first money-keyword cluster, use broad keywords only once, then move
  to the next location or buyer-education angle instead of rewriting the same
  intent.

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
- Add or update focused tests in `tests/test_public_seo.py`.
- If the article changes shared public SEO behavior, document that in the same
  commit instead of leaving workflow knowledge only in chat.

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
