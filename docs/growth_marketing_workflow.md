# Radar BDS Growth Marketing Workflow

Use this doc for marketing, SEO, social, lead magnet, CRO, analytics, and Codex automation work. It is intentionally narrower than a full marketing plan: it tells future agents what to do first and what to avoid.

## Framework

Radar BDS uses the `coreyhaines31/marketingskills` framework:

- `product-marketing` is the source of truth for positioning, ICP, customer language, and proof points.
- AARRR is the operating structure: Acquisition, Activation, Retention, Referral, Revenue.
- Channel skills execute stage-specific work: `content-strategy`, `ai-seo`, `schema`, `social`, `community-marketing`, `cro`, `lead-magnets`, `free-tools`, and `analytics`.

Read order for growth work:

1. `AGENTS.md`
2. `.agents/product-marketing.md`
3. `docs/README.md`
4. This file
5. The smallest task-specific product/operations doc needed for data truth

## 80/20 Priorities

| Rank | AARRR stage | Priority | Why |
|---|---|---|---|
| 1 | Acquisition | Data-backed Bình Dương SEO/report assets | Uses Radar's unique data and compounds through search |
| 2 | Activation | Clear path from public page to dashboard/watchlist | Turns visitors into first-value users |
| 3 | Retention | Watchlist and Telegram loop | Gives users a reason to return when new listings appear |
| 4 | Referral | Shareable market notes | Useful local insights travel better than generic promotion |
| 5 | Revenue | VIP lead and advisory CTA | Monetizes high-intent users without forcing paid ads |

## Content Pillars

Every public asset should fit at least one pillar:

1. **BDS Bình Dương theo khu**: Thủ Dầu Một, Bến Cát, Mỹ Phước, ward/sub-zone pages, and monthly/weekly market reports.
2. **Lọc deal và MOS**: fair value, price per m2, MOS, price drops, comparable context, and how to read signal cards.
3. **Cảnh báo tin nhiễu/tin mồi**: fake cheap prices, wrong area, wrong ward, reposts, source-quality warnings, and due-diligence caveats.

Preferred formats:

- Searchable: hub/report/area pages with FAQ, visible methodology, canonical URL, and internal links.
- Shareable: 1-chart or 1-insight social posts, short video scripts, and weekly market notes.
- Lead capture: checklist, saved watchlist, Telegram connect, and VIP advisory CTA.

Do not create doorway pages by street or thin area variants. Add or refresh pages only when there is enough local data or product value to justify them.

## CTA Rules

Use outcome CTAs. Avoid vague CTAs when a higher-intent action is available.

Preferred CTAs:

- `Lưu watchlist Bình Dương`
- `Nhận deal mới qua Telegram`
- `Xem các tin MOS cao hôm nay`
- `Soi khu này trên dashboard`
- `Hỏi VIP/advisory về tin này`

CTA hierarchy:

1. Public SEO/report pages: dashboard/watchlist first, method/report links second.
2. Dashboard signal cards: listing detail or lead/VIP contact.
3. Free users: save watchlist and connect Telegram as the bridge to VIP.
4. VIP/admin: advisory and fast contact flow.

Keep due-diligence language visible: Radar BDS is a data filter, not a legal appraisal or profit guarantee.

## Lead Magnet And Free Tool Ideas

Implement only after the foundation and tracking work are in place.

High-priority lead magnet:

- **Checklist 10 điểm kiểm tra một tin đất Bình Dương trước khi đi xem**
- Format: ungated preview plus optional email/Zalo/Telegram capture for full version.
- Buyer stage: consideration.
- Natural next step: open dashboard, save watchlist, connect Telegram.

High-priority free tool candidate:

- **MOS quick check / giá m2 khu vực**
- MVP: user enters price, area, ward/sub-zone; tool explains price per m2 and points to relevant dashboard filters.
- Capture: optional, after preview. Do not block the result entirely.

Skip for now:

- Broad ebooks.
- Paid lead ads.
- Mass outreach.
- Fake community seeding.

## Social And Community

Community goal for the first 30 days is not to create a large public community. It is to nurture 20-50 manually selected early investors/buyers and learn which notes make them return.

Recurring share formats:

- `3 khu nên soi tuần này`
- `1 tin rẻ nhưng cần cẩn thận`
- `Giá/m2 theo khu`
- `Tin giảm giá: cơ hội hay mồi giá?`
- `Cách đọc MOS trước khi gọi môi giới`

Short video structure:

1. Hook in first 3 seconds: "Tin rẻ chưa chắc là deal."
2. One Radar insight from real data.
3. One practical interpretation.
4. CTA to dashboard/watchlist/Telegram.

Do not auto-post to external platforms from Codex automations. Produce packs for manual publishing.

## Distribution Pack Anti-Duplication

Distribution packs must optimize for novelty of angle, not volume.

Before producing a pack:

1. Read the latest automation memory if available: `$CODEX_HOME/automations/radar-bds-distribution-pack/memory.md`.
2. Read `.agents/distribution-pack-history.md`.
3. Compare the candidate pack against at least the last 3 shipped entries.

Treat a pack as a duplicate if it reuses the same combination of:

- source asset/page
- primary content atom or insight
- opening hook
- audience pain being addressed

Allowed reuse:

- Same source asset is allowed only when the new pack changes the angle materially.
- Material change means at least 2 of these change: pillar, core insight, hook, CTA path, target audience pain.

Required behavior:

- If the latest verified asset has already been used recently, first look for a different verified content atom inside that same asset.
- If no fresh atom exists, reuse a different verified public page/report.
- If no fresh verified angle exists at all, output `Mode: skipped` with the duplicate reason instead of forcing a near-copy.

When a pack ships, append one short log entry to `.agents/distribution-pack-history.md` with:

- date
- source asset
- pillar
- primary atom
- opening hook
- audience pain
- CTA path
- UTM content slug

Do not treat minor copy edits, synonym swaps, or different caption lengths as a new angle.

## Analytics Events

Use lowercase snake_case. Put context in properties, not event names.

| Event | Trigger | Required context |
|---|---|---|
| `seo_landing_viewed` | Public SEO/area page view | `path`, `page_slug`, `variant` |
| `report_viewed` | Public report page view | `path`, `page_slug`, `variant` |
| `social_utm_visit` | Pageview with `utm_source` | `utm_source`, `utm_medium`, `utm_campaign`, `path` |
| `cta_clicked` | Public-page CTA click | `location`, `target`, `page_slug`, `button_text` |
| `signup_completed` | Account created | `type` |
| `watchlist_create` | Watchlist saved | `ward_count`, `prop_count`, `notify_telegram` |
| `telegram_linked` | Telegram account linked | no PII |
| `vip_cta_click` | Guest clicks VIP/contact CTA | `ctx`, `tier` |
| `cta_vip` | Free user clicks VIP/contact CTA | `ctx`, `tier` |
| `lead_vip_click` | VIP/admin opens lead/advisory CTA | `ctx`, `tier` |

Measurement questions:

- Which public pages produce `watchlist_create` and `telegram_linked`?
- Which social UTM sources produce qualified activation, not just visits?
- Which CTA locations produce VIP inquiries?
- Which content themes lead to repeated dashboard use?

Do not store phone numbers, original listing URLs, or other PII inside analytics context.

## Codex Automation Guardrails

All growth automations must:

- Use real repo/product data or report a skip/blocker.
- Keep output narrow: one strategy queue, one growth task, or one distribution pack per run.
- Avoid mass publishing, paid ads, fake reviews, fake community posts, link spam, and doorway pages.
- Not modify crawl/reprocess/valuation logic.
- Not reintroduce external LLM verification into crawl or reprocess.
- Never write marketing/advisory/AI verdicts into `ai_training_feedback`.
- Keep production URLs, CTAs, schema, and sitemap visibility verifiable before claiming success.

## Daily SEO Publisher Guardrail

Use `daily_seo_publisher.md` for the exact one-URL-per-run workflow.

Extra rules for daily SEO publishing:

- Read `.agents/seo-publish-history.md` before choosing the topic.
- Treat repeated primary keyword + search intent as a duplicate, even if the slug changes.
- A local render is not enough; the run is only `shipped` after live URL + canonical + sitemap verification pass.
- Prefer the reusable verifier command over ad-hoc manual checks:
  `.\scripts\verify_live_seo_article.ps1 -Url "https://radarbds.vn/kien-thuc/<slug>" -HeadingContains "..." -RequireWatchlistIntent`
- If deploy is blocked by known temporary audit/report files on the VPS checkout, let `scripts/deploy_production.ps1` auto-archive only its built-in allowlist; if any other dirty file remains, stop and report the blocker.

## Automation Output Shapes

Weekly strategy output:

- 7-day growth queue
- One priority SEO/report/landing task
- Three social atoms
- One CRO task
- One metric to inspect
- One topic to avoid

Daily growth output:

- Mode: shipped / blocked / skipped
- One asset or task completed
- Data evidence used
- CTA/funnel path touched
- Verification run
- Next 24-hour priority

Distribution pack output:

- Facebook/Zalo post
- TikTok/Reels/Shorts 20-35s script
- Telegram teaser
- UTM links
- Manual publishing notes
- Source asset/page used
- One-line novelty note versus the most recent pack, or `Mode: skipped` if novelty failed

Measurement review output:

- Top pages by qualified activation
- Signup/watchlist/Telegram/VIP funnel counts
- Keep / kill / change decisions
- Next week's highest-leverage experiment
