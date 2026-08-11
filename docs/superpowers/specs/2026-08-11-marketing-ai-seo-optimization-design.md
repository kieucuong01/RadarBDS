# Marketing and AI SEO Optimization Design

**Date:** 2026-08-11
**Project:** Radar BDS
**Status:** Approved design, awaiting written-spec review

## Objective

Optimize the complete public marketing surface of Radar BDS for traditional
search, AI citation, and qualified conversion. The work must preserve the
current funnel:

```text
SEO / social / AI assistant
  -> exact public page
  -> filtered dashboard
  -> signal card
  -> contact or lead CTA
```

The optimization should improve shared systems before editing individual
pages. It must not create thin pages, invent market evidence, or promote
watchlist, Telegram, or VIP upgrade as the default public marketing promise.

## Audited Surface

The static canonical inventory contains 124 URLs:

| Surface | Count |
|---|---:|
| Homepage and public tools | 3 |
| Core market/method landing pages | 3 |
| Location landing pages | 26 |
| Report hub and report pages | 29 |
| Curated Radar articles | 44 |
| News portal and content hubs | 4 |
| Map, planning, and map-product pages | 15 |
| **Total** | **124** |

Dynamic legal-document detail pages are additional public acquisition pages
but are not part of the static count. Machine-readable surfaces are audited
separately: `/robots.txt`, `/sitemap.xml`, `/llms.txt`, `/agent/site.json`, and
`/agent/openapi.json`.

## Baseline Evidence

- Production returned HTTP 200 and a correct self-canonical for the sampled
  article, report, location, method, hub, planning, and map-product pages.
- The sampled rendered JSON-LD blocks parsed successfully and covered
  `BlogPosting`, `Report`, `CollectionPage`, `WebPage`, `Product`, `Dataset`,
  `BreadcrumbList`, and `FAQPage` where appropriate.
- Production `/sitemap.xml` contained 125 URLs and included the latest sampled
  article and report.
- Production `/robots.txt` allowed `OAI-SearchBot` and all user agents.
- Production `/llms.txt` exposed the public read-only agent contract and core
  market pages.
- 152 focused tests passed across public SEO, content hubs, AIO tracking,
  planning pages, city-map products, valuation UI, and land-price tools.

The audit also confirmed two live CTA defects:

1. `/tin-tuc/gia-dat-dinh-hoa-thu-dau-mot-cap-nhat-thang-7-2026` uses an
   invalid `tab=tin đáng kiểm tras` value.
2. `/tin-tuc/dat-nen-thu-dau-mot-duoi-20-trieu-m2-con-o-phuong-nao` uses
   `property_type=dat_nen`, while the dashboard URL contract requires
   `prop_type=dat_nen`.

## Chosen Approach

Use a phased, system-first optimization. Shared route helpers, templates,
generators, machine-readable files, and validation rules are corrected before
targeted content edits. This gives all 124 URLs consistent behavior and keeps
future generated reports/articles aligned.

Rejected approaches:

- **Quick-fix only:** too narrow; it would repair the two CTA defects but leave
  inconsistent trust and AI-extractability signals.
- **Rewrite every page:** too risky; it would create a large unverified content
  diff and increase cannibalization and data-accuracy risk.

## Architecture

### Source registries

Existing configuration remains authoritative:

- `config/seo_pages.py` for core landing pages and generated reports;
- `config/seo_articles.py` for curated `/tin-tuc` articles;
- `config/seo_locations.py` for location landing pages;
- `config/planning_pages.py` and `config/content_hubs.py` for planning/news;
- `config/city_map_products.py` and `config/binh_duong_map.py` for maps.

No production content will be moved into a new CMS or database as part of this
work.

### Rendering flow

```text
config registry
  -> route/decorator hydration
  -> page-specific template
  -> visible trust information + matching JSON-LD
  -> sitemap / llms discovery
```

The current runtime hydration in `app.py` remains responsible for live ward
snapshots. Templates remain responsible for presentation, but shared trust
markup is moved into a small reusable partial to avoid drift.

### Visible trust contract

Each page type must display the strongest truthful values already available:

- editorial owner: `Nhóm dữ liệu Radar BDS` or `Radar BDS`;
- actual modified, published, snapshot, or dataset date;
- source and methodology appropriate to that page type;
- due-diligence limitation when the content discusses market or property data.

Fallbacks must be explicit. If a live snapshot cannot be loaded, the page says
that live data is temporarily unavailable and retains evergreen methodology;
it must not substitute generated numbers or a current date.

### Structured data contract

Existing schemas remain in place. They are enriched only where visible content
supports the fields:

- stable Organization/WebSite identifiers and URLs;
- `inLanguage: vi-VN`;
- article/report author and publisher URLs;
- correct published/modified dates;
- FAQ schema only when matching questions and answers are visible;
- no ratings, reviews, people, credentials, or claims that do not exist on the
  page.

## Planned Changes

### 1. CTA and funnel correctness

- Replace the invalid article tab with `tab=signals`.
- Replace `property_type=dat_nen` with `prop_type=dat_nen` in both the primary
  and final CTA.
- Validate every configured root-dashboard CTA against the supported query
  contract: `tab`, `ward`, `city`, `source`, `prop_type`, price/area ranges,
  `date_range`, `mos_min`, search terms, signal ID, and sanitized UTM fields.
- Replace remaining public default copy such as “lọc watchlist”, “Ráp mối VIP”,
  or dashboard/Telegram promises with “lọc signal”, “xem tin phù hợp”, or
  “liên hệ tin này”.
- Update report generators so future monthly reports do not recreate legacy
  funnel copy.

### 2. Complete Thủ Dầu Một live location coverage

Extend the existing `live_ward` contract from eight to all 13 canonical Thủ
Dầu Một wards. The five missing pages are:

- Tương Bình Hiệp;
- Chánh Mỹ;
- Phú Cường;
- Phú Tân;
- Hòa Phú.

They use the existing bounded/fail-open snapshot mechanism. This does not
change normalization, valuation, crawl, or database schema behavior.
Existing valuation-ward aliases remain authoritative: TDC/TDC Phú Chánh data
continues to resolve through Phú Tân, and KDC Hiệp Thành through Hiệp Thành.

### 3. Trust and AI extractability

- Add a shared public trust partial and use it only where it does not duplicate
  a stronger existing source/method section.
- Show editorial ownership on articles and reports.
- Show update/source/method information on static location pages and hubs.
- Preserve the existing report and map source sections.
- Tighten the eight clearly overlong answer-first introductions identified by
  the audit while preserving their verified numbers and caveats.
- Treat remaining title/description length findings as warnings until Search
  Console supplies impression, CTR, or cannibalization evidence.
- Do not redirect or merge suspected duplicate-intent pages without query-level
  evidence.

### 4. Machine-readable discovery

- Generate the priority ward list in `/llms.txt` from the canonical location
  registry and cover all 13 Thủ Dầu Một wards.
- Add a bounded list of the newest reports and the highest-priority Radar
  articles from the registries.
- Add `/llms.txt` to the XML sitemap.
- Keep `/agent/site.json` and `/agent/openapi.json` linked from `llms.txt`; do
  not add JSON API documents to the web-page sitemap.
- Retain the permissive wildcard robots policy. Explicit user-agent blocks or
  decorative duplicate rules are out of scope.

### 5. Durable audit command

Add `scripts/audit_marketing_pages.py` with a deterministic, config-only
default mode. It must not require the production database or an external LLM.

Hard failures:

- conflicting duplicate canonical definitions or missing canonical paths;
  identical registry aliases are deduplicated and remain valid;
- invalid dashboard query keys or tab values;
- article path/date/FAQ contract failures;
- required sitemap coverage gaps;
- invalid generated JSON-LD in render tests;
- missing live-ward coverage for the canonical 13-ward set.

Warnings:

- unusually long/short metadata;
- answer-first passages outside the preferred range;
- possible duplicate reader intent;
- missing optional visual, table, or secondary internal link.

The command should provide a human-readable summary by default and a bounded
JSON result for automation. A non-zero exit status is reserved for hard
failures.

## Files in Scope

Expected files include:

- `app.py` and, only if routing changes are needed, `routes/public.py`;
- `config/seo_articles.py`;
- `config/seo_locations.py`;
- `config/seo_pages.py`;
- `scripts/generate_monthly_report.py` and/or the report enhancer;
- shared public SEO templates and one new trust partial;
- `scripts/audit_marketing_pages.py`;
- focused SEO/audit tests;
- documentation only where the durable workflow contract changes.

Files related to Facebook crawl, admin screens, valuation, normalization,
deduplication, production DB schema, auth, or Telegram delivery are out of
scope.

## Error Handling

- Live ward lookup failure renders a safe evergreen page and logs the failure.
- Missing optional trust metadata omits that row rather than rendering a blank
  label.
- Missing required registry data fails the audit/test before release.
- Redis/cache/prewarm failures remain separate from committed content truth.
- No external AI verification is added to crawl, reprocess, or page rendering.
- No market number, legal status, testimonial, author credential, or source is
  invented to fill a content gap.

## Verification

Implementation will follow test-first coverage for each behavior change:

1. Add failing tests for the CTA query contract, 13 live wards, legacy funnel
   language, trust rendering, machine-readable coverage, and audit exit codes.
2. Apply the smallest implementation that makes each test pass.
3. Run the new audit command in strict mode.
4. Run focused Python compilation and JavaScript syntax checks.
5. Run the existing 152-test marketing/public-page matrix plus new tests.
6. Render representative pages for every page type and parse canonical and
   JSON-LD output.
7. After an authorized clean release, verify every sitemap URL over HTTP and
   perform browser QA on one representative page per page type.

A timeout is reported as unverified, never as a pass.

## Git and Release Safety

The current workspace may contain unrelated user-owned work. Staging and
commits must name only the AI SEO files. Unrelated files must not be stashed,
reverted, reformatted, or included in the release.

Push/deploy is allowed only when the scoped commit can reach the production
branch without carrying unrelated Facebook/admin work. If the branch topology
does not allow a clean release, implementation stops after verified scoped
commits and reports the exact integration blocker.

When a clean production release is possible, completion requires:

```text
focused tests
  -> scoped commit
  -> push production branch
  -> approved deploy wrapper
  -> live HTTP/sitemap/schema/browser verification
```

## Acceptance Criteria

- All 124 static canonical marketing URLs remain represented by the registry.
- No marketing CTA uses `property_type=` or an unsupported `tab` value.
- All 13 Thủ Dầu Một ward pages implement the current live/fail-open contract.
- Public page types display truthful editorial/update/source/method signals.
- Rendered JSON-LD parses and matches visible page content.
- `/llms.txt` contains all 13 priority wards and bounded current content links.
- `/llms.txt` appears in the sitemap; agent JSON remains linked from llms only.
- The audit command reports zero hard failures.
- New tests and the existing focused marketing matrix pass.
- Unrelated workspace changes remain untouched.
- No deployment success is claimed without public production evidence.
