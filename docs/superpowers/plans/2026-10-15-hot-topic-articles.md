# Hot-topic articles implementation plan

> **For agentic workers:** Execute inline with superpowers:executing-plans. User approved implementation on 2026-10-15.

**Goal:** Connect sourced Radar articles and verified social media to Tin tức → Chủ đề nóng without duplicating events or mixing the data archive.

**Architecture:** Reuse SEO_ARTICLES and article template. Explicit `news` metadata identifies event, sources, topic, status and verified media. A small presentation service merges configured news articles with external metadata cards, using canonical source URLs to suppress matching source cards. Existing external-only and legal paths remain available.

**Tech stack:** Python, Flask/Jinja, existing CSS and progressive JS.

**Spec:** docs/radar_bds_hot_topics_content_strategy.md (approved).

**Result:** Implemented and verified locally. Four sourced pilot articles are registered;
the Bà Điểm event also links a verified YouTube Short and Facebook post.
105 focused public/SEO/JS-contract tests and 36 Linux news/social tests passed.
After the final malformed-media guard, the 20 editorial tests passed again.
Production checkout and current social publications were not changed.

## Global constraints

- One internal article URL per event; original press links remain available.
- Use existing article registry, public source evidence and verified social permalinks; no new DB or provider dependency.
- Preserve existing article URLs, data archive, legal pages, redaction and listing pipelines.
- Source dates and editorial dates are distinct; no invented fresh news, price data or published media.
- Preserve unrelated local and VPS changes. No deployment overwrites of dirty VPS social scripts.

## Review focus

- Sources with tracking parameters must match without merging different article identities.
- Draft/malformed news entries must not appear as public articles or suppress valid source cards.
- Existing data articles and featured fallback remain unchanged.
- Unsafe external media URLs are never rendered as active links/embeds.
- Hub links, breadcrumbs, Article schema and sitemap agree with visible destinations.

## Task 1: Connect registry to hubs and article evidence

Files: new services/news_editorial.py, tests/test_news_editorial.py; app.py; templates/public_content_hub.html, news_portal.html, seo_article.html; config/content_hubs.py; static/css/seo.css.

- [x] Add failing tests for internal news cards, source dedupe, external fallback, draft exclusion, classification, breadcrumb/schema and safe source/media rendering.
- [x] Add metadata validation and merged-card presentation using existing source records, without modifying their canonical URLs.
- [x] Render sources, event status and verified media links in articles. Reuse existing progressive controls and tracking.
- [x] Run focused public-content and SEO tests; inspect compatibility failures before changing assertions.

## Task 2: Pilot content and repeatable publishing handoff

Files: config/seo_hot_topic_articles.py; config/seo_articles.py; scripts/radar_daily_seo_context.py; docs/daily_seo_publisher.md; docs/social/news-workflow.md; tests/test_news_editorial.py.

- [x] Inspect current news queues and public permalinks read-only; select up to three distinct verified events and write original explainers with explicit sources and dates.
- [x] Register pilot articles and surface event/source metadata in daily context inventory for reuse by news/social selection.
- [x] Document exact metadata contract and web-before-social handoff; use existing cron cadence, no new scheduler.
- [x] Test pilot URLs, sources, schema, sitemap and archive separation.

## Task 3: Rendered verification and final review

- [x] Run focused Python/JS checks and desktop/mobile browser flow: portal → hot topic → article → source/media.
- [x] Inspect full diff for unsafe links, duplicate cards, stale taxonomy and source/date inconsistencies.
- [x] Report exact local result and remaining production boundary; no claims of a live release without deployment evidence.

## Execution notes

- User's “ok làm đi” authorizes proceeding with the approved strategy; no second design confirmation is required.
- Initial VPS inspection found unrelated dirty social scripts/tests; preserve them.
- Browser plugin skill is absent; use available computer-use browser or installed Playwright for rendered verification.
- Review: both malformed-metadata findings were reproduced, covered by tests and fixed.
- Browser evidence: local hub search reduced four cards to one; the card opened the matching
  article with source links and YouTube/Facebook destinations. Mobile width and scrollWidth
  were both 390px. Desktop/mobile screenshots saved under ignored local QA artifacts.
- Final desktop check: trust-panel overflow fixed; document clientWidth and scrollWidth
  both 1265px after loading versioned CSS. No relevant console errors observed.
- Graphify code update completed: 14,306 nodes, 32,690 edges, 724 communities.
- Ruling: news entries are excluded from the default Radar data social lane, including
  latest-article selection, so adding an explainer cannot bypass the reviewed news workflow.
- Ruling: pilot scope expanded from three to four after the user supplied actual channels;
  the additional Bà Điểm article is the verified web/video/Facebook integration example.
