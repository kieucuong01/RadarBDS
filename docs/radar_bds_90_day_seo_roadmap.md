# Radar BDS — 90-Day Sustainable SEO Roadmap

This roadmap turns daily `/tin-tuc` publishing into a durable topic system instead of a one-off daily topic picker.

Principle: Radar BDS should become the data authority for Bình Dương real-estate search by combining location pages, monthly reports, data explainers, comparison articles, and filtered dashboard CTAs.

## Operating principles

1. **Data-first, not opinion-first** — every article must use production DB numbers or clearly be an evergreen explainer.
2. **Topic clusters beat random posts** — each article supports a pillar/location/report/dashboard path.
3. **Avoid cannibalization** — deduplicate by reader intent, not slug.
4. **Freshness compounds** — after ~60-90 URLs, refresh/update becomes as important as new publishing.
5. **One data atom, two outputs** — every daily SEO run produces a publish/refreshed page plus a social post draft.

## Pillar architecture

```text
/binh-duong
  ├─ /binh-duong/phuong-<ward>
  │    ├─ /bao-cao/<ward>-thang-MM-YYYY
  │    ├─ /tin-tuc/gia-dat-<ward>-hien-bao-nhieu
  │    ├─ /tin-tuc/dat-nen-<ward>-gia-trung-vi
  │    ├─ /tin-tuc/nha-dat-<ward>-khac-dat-nen-the-nao
  │    └─ filtered dashboard: /?tab=signals&ward=<ward>
  ├─ comparison articles
  ├─ buyer explainers
  └─ free tools / calculators
```

## Sustainable content clusters

| Cluster | Funnel stage | Purpose | URL pattern | Internal link targets |
|---|---|---|---|---|
| Giá đất theo phường | TOFU/MOFU | Capture local search | `/tin-tuc/gia-dat-{ward}-hien-bao-nhieu` | ward page, monthly report, dashboard ward filter |
| Đất nền vs nhà đất | TOFU/MOFU | Teach correct price reading | `/tin-tuc/dat-nen-vs-nha-dat-{ward}` | dashboard prop_type filter, report type chart |
| So sánh phường | MOFU | Buyer evaluation | `/tin-tuc/{ward-a}-vs-{ward-b}-nen-xem-khu-nao` | both ward pages, reports, dashboard filters |
| MOS / dưới giá cơ sở | BOFU | Push dashboard usage | `/tin-tuc/mos-la-gi-loc-tin-duoi-gia-co-so` | dashboard `mos_min`, `/san-deal-bds` |
| Báo cáo → tin tức | TOFU/MOFU | Refresh + internal links | `/tin-tuc/tu-bao-cao-thang-MM-phuong-nao-nhieu-tin-dang-kiem-tra` | `/bao-cao`, master report, ward reports |
| Buyer guides | TOFU | Build trust | `/tin-tuc/cach-doc-gia-rao-binh-duong` | valuation tool, dashboard, reports |
| Bến Cát/Mỹ Phước expansion | TOFU/MOFU | New geography | `/tin-tuc/gia-dat-my-phuoc-ben-cat-hien-bao-nhieu` | Bến Cát landing pages, dashboard filters |
| Free tools | Link/share | Durable acquisition | `/dinh-gia-bds`, future calculators | all articles and reports |

## Topic scoring rule

Daily cron/Codex should score candidate actions before writing.

| Score | Criterion | Notes |
|---:|---|---|
| 30 | Long-lived search intent | People search it beyond today; e.g. “giá đất Phú Tân”, “Phú Mỹ vs Hiệp An”. |
| 25 | Radar proprietary data advantage | DB has enough listings/signals/price split to make the page unique. |
| 20 | Funnel linkage | Can link to dashboard/report/location/tool with useful filters. |
| 15 | No cannibalization | No existing URL answers the same reader intent. If duplicate, refresh instead. |
| 10 | Social reuse | Can become one useful Facebook/Zalo/group post. |

Action rule:

| Score | Action |
|---:|---|
| ≥ 70 | Publish new `/tin-tuc` article |
| 50–69 | Refresh existing article/report section or add internal links |
| < 50 | Skip publishing; do internal-link, technical SEO, or topic research |

## Daily action mix

### First 60–90 days

Because the site is early-stage and `/tin-tuc` is new, keep momentum high:

```text
5 days/week: publish new /tin-tuc article
1 day/week: refresh or internal-link older content
1 day/week: optional strategy/social-only if production has blocker
```

### After ~60–90 useful URLs

Switch to compounding quality:

```text
3 days/week: publish new article
2 days/week: refresh/update existing winners
1 day/week: internal-link consolidation
1 day/week: topic research / social / technical SEO
```

## 90-day roadmap

### Month 1 — Build Thủ Dầu Một foundation

Goal: create enough TDM topical coverage that reports, location pages, and dashboard filters reinforce each other.

| Week | Focus | New pages | Refresh/internal-link |
|---|---|---:|---|
| W1 | Core explainers + high-signal wards | 5–6 | Link `/tin-tuc` hub, `/bao-cao`, dashboard |
| W2 | 13 ward price pages begin | 5–6 | Add links from reports to articles where relevant |
| W3 | Finish key ward price pages | 5–6 | Add dashboard filter CTAs per ward |
| W4 | Comparison pages | 5–6 | Create comparison hub links from related ward pages |

Month 1 article bank:

| Priority | Intent | Suggested title | URL target |
|---:|---|---|---|
| 1 | Giá đất Phú Tân | Giá đất Phú Tân hiện bao nhiêu? Đọc riêng đất nền và nhà đất | `/tin-tuc/gia-dat-phu-tan-hien-bao-nhieu` |
| 2 | Giá đất Phú Mỹ | Giá đất Phú Mỹ hiện bao nhiêu? So đất nền và nhà đất | `/tin-tuc/gia-dat-phu-my-hien-bao-nhieu` |
| 3 | Giá đất Hiệp An | Giá đất Hiệp An Thủ Dầu Một: xem mức giá trung vị thế nào? | `/tin-tuc/gia-dat-hiep-an-thu-dau-mot` |
| 4 | Giá đất Tân An | Giá đất Tân An hiện nay: khi nào nên mở dashboard kiểm tra? | `/tin-tuc/gia-dat-tan-an-thu-dau-mot` |
| 5 | Định Hòa | Giá đất Định Hòa: vì sao phải tách đất nền và nhà đất? | `/tin-tuc/gia-dat-dinh-hoa-thu-dau-mot` |
| 6 | Explainer | Giá trung vị là gì trong dữ liệu nhà đất? | `/tin-tuc/gia-trung-vi-la-gi-trong-du-lieu-nha-dat` |
| 7 | Explainer | Giá rao thấp hơn thị trường có đáng tin không? | `/tin-tuc/gia-rao-thap-hon-thi-truong-co-dang-tin-khong` |
| 8 | MOS | MOS là gì và cách lọc tin dưới giá cơ sở trên Radar BDS | `/tin-tuc/mos-la-gi-loc-tin-duoi-gia-co-so` |
| 9 | Comparison | Phú Tân vs Định Hòa: nên xem khu nào trước? | `/tin-tuc/phu-tan-vs-dinh-hoa-nen-xem-khu-nao` |
| 10 | Comparison | Phú Mỹ vs Hiệp An: khác nhau thế nào khi đọc giá/m²? | `/tin-tuc/phu-my-vs-hiep-an-so-gia-dat` |
| 11 | Buyer guide | Cách đọc giá/m² để không so sai đất nền với nhà đất | `/tin-tuc/cach-doc-gia-m2-khong-so-sai-dat-nen-nha-dat` |
| 12 | Report bridge | Từ báo cáo tháng: phường nào có nhiều tin đáng kiểm tra? | `/tin-tuc/bao-cao-thang-phuong-nao-nhieu-tin-dang-kiem-tra` |

### Month 2 — Expand to Bến Cát and Mỹ Phước

Goal: avoid depending only on TDM, capture industrial-town land demand.

| Week | Focus | New pages | Notes |
|---|---|---:|---|
| W5 | Bến Cát/Mỹ Phước price pages | 5–6 | Use DB only if enough data; otherwise make buyer guide with caveat |
| W6 | TDM vs Bến Cát comparisons | 5–6 | Good MOFU search intent |
| W7 | Buyer guides for Bến Cát | 5–6 | KCN, đất nền, pháp lý caveats; only verified data |
| W8 | Free-tool supporting content | 4–5 | Push `/dinh-gia-bds`, dashboard filters |

Month 2 article bank:

| Intent | Suggested title |
|---|---|
| Mỹ Phước | Giá đất Mỹ Phước Bến Cát hiện bao nhiêu? |
| Bến Cát overview | Bến Cát có những khu nào nên theo dõi khi mua đất? |
| TDM vs Bến Cát | Mua đất Thủ Dầu Một hay Bến Cát: khác nhau ở điểm nào? |
| Mỹ Phước 1/2/3 guide | Mỹ Phước 1, 2, 3 khác nhau thế nào khi xem giá đất? |
| KCN angle | Gần khu công nghiệp có làm giá đất cao hơn không? Cách đọc dữ liệu |
| Buyer guide | 5 bước kiểm tra giá rao trước khi đi xem đất Bình Dương |

### Month 3 — Refresh, consolidate, and build durable assets

Goal: improve winners, reduce thin/duplicate pages, and make the site useful beyond daily articles.

| Week | Focus | Action |
|---|---|---|
| W9 | Refresh top pages | Update numbers, add FAQ/source/freshness |
| W10 | Internal-link consolidation | Link articles ↔ reports ↔ dashboard ↔ tools |
| W11 | Data hub pages | Build/refresh “bảng giá trung vị theo phường” style pages |
| W12 | Free tools / calculators | Ship or improve shareable utilities |

Durable asset ideas:

| Asset | Purpose | Notes |
|---|---|---|
| Giá/m² calculator | Shareable utility | User enters price + area; explains price/m² |
| Compare with ward median | BOFU conversion | Show “cao/thấp hơn giá trung vị phường” with caveat |
| MOS explainer/filter | Dashboard education | Link to `mos_min=10` / `mos_min=15` |
| Bình Dương ward price table | Data hub | Refresh monthly from reports |
| Đi xem đất checklist | TOFU/share | Useful social handoff |

## Internal linking rules

Each new `/tin-tuc` article should include:

- 1 link to the most relevant `/bao-cao` report.
- 1 link to the relevant `/binh-duong/...` location page.
- 1 filtered dashboard CTA.
- 1 link to `/dinh-gia-bds` or `/san-deal-bds` when relevant.
- 2–3 links to related `/tin-tuc` articles once the cluster exists.

Do not overload links. The goal is a clear next step, not a link farm.

## Refresh rules

Refresh an existing article instead of publishing a new one when:

- The same reader intent already exists.
- The article is older than one month and the DB has meaningfully changed.
- A monthly report adds stronger numbers that should be linked.
- GSC later shows impressions but weak CTR/rank.

Refresh checklist:

- Update date/source/freshness.
- Replace stale numbers with current DB numbers.
- Add one table or visual if missing.
- Add internal links to new reports/articles.
- Improve answer-first intro and FAQ.
- Verify live URL and sitemap.

## What not to write

Avoid:

- Generic real-estate articles with no Radar data angle.
- Thin location pages that only swap ward names.
- Planning/infrastructure claims without verified source.
- Duplicate articles that answer the same intent as an existing URL.
- Aggressive “deal ngon”, guaranteed profit, or legal certainty claims.

## Daily cron instruction summary

The daily cron should choose from this priority order:

1. If there is a production blocker: fix/report blocker.
2. If a ≥70 score new topic exists: publish new `/tin-tuc` article.
3. If no strong new topic but an existing page is stale: refresh it.
4. If no article action is useful: add internal links or prepare a data/social asset.
5. Always return a social draft and a concise verification summary.
