# Radar BDS Traffic Marketing Workflow

Content pruning on 2026-11-03 consolidated three duplicate answers and added
planning/Săn Deal guides. Follow [the decisions and URL inventory](seo-content-review-2026-11-03.md)
before creating another price or ward-comparison article. A subsequent read-only
GSC review prioritized existing Maps and land-price pages over more templated
ward comparisons. See [the GA4/GSC/Maps release](ga4-gsc-maps-release-2026-11-03.md).
Search gains after these changes remain unmeasured.

## Product discovery update — 2026-11-03

The approved site architecture now exposes four entry tasks: **Bản đồ quy hoạch,
Săn Deal BĐS, Định giá đất, Bảng giá đất**. Navigation keeps that order across the
dashboard and public pages; mobile uses Quy hoạch / Săn Deal / Định giá / Bảng giá /
Thêm. News, reports and market pages remain accessible under Kiến thức & dữ liệu.
See `site-architecture-research-2026-11-03.md` for the research and migration scope.

Users entering a planning tool may complete that task without being forced into
the signal funnel. Offer the next relevant tool only where its geographic data
exists. Keep Maps coverage, listing coverage, valuation coverage and official
land-price coverage distinct. Valuation uses asking-price data, not completed
transactions or the official land-price table.

The homepage retains its working feed, old query URLs and Maps deep links.
Its four-task explanation is a collapsed native disclosure; it makes no extra
API requests and does not automatically cover the results. Existing daily SEO
cadence and source requirements below remain unchanged.

Use this doc for SEO, AI SEO, social distribution, analytics, and Hermes daily
marketing work. The goal is deliberately narrow: bring qualified users into
`radarbds.vn`, let them filter the dashboard by area, then contact on matching
signal deals.

## Current Funnel

The marketing funnel is:

```text
Google / Facebook / AI answer
  -> SEO page, report, or filtered URL
  -> dashboard with ward/filter context
  -> user reviews signal cards
  -> user clicks contact / lead CTA on a suitable deal
```

Do not optimize marketing toward watchlist, Telegram, VIP upgrade, community,
video, paid ads, or lead magnets in the first 90 days unless the user explicitly
changes this scope.

Product features such as watchlists and Telegram may still exist in the app.
They are not the primary traffic funnel for marketing work.

## 80/20 Strategy

Spend effort where Radar BDS has an unfair advantage: local Bình Dương data and
filtered signal pages.

| Priority | Work | Why |
|---|---|---|
| 1 | Improve existing SEO location/report pages | They already exist, are indexable, and map directly to filtered dashboard demand. |
| 2 | Publish or refresh one high-intent SEO page only when there is a clear gap | Prevents thin articles and duplicate intent. |
| 3 | Turn the same data atom into one Facebook/Page post with a UTM link | Creates short-term traffic while Google ranking builds. |
| 4 | Measure traffic to filtered dashboard and contact clicks | This is the actual conversion path. |
| 5 | Monthly AI visibility check | AI SEO is a layer over good SEO, not a separate daily content treadmill. |

Skip broad campaigns: nationwide SEO, daily news, TikTok/YouTube, influencer
work, paid ads, fake community seeding, link spam, and generic product posts.

## Page And CTA Rules

Every public page should answer one search intent and send the user to the most
specific dashboard view possible.

- Ward pages link to `/?tab=signals&ward=<ward name>`.
- Broad Bình Dương pages link to `/?tab=signals`.
- Reports link to the relevant filtered dashboard if the report has a ward or
  cluster, otherwise to the signal feed.
- Facebook posts link to the exact page or filtered dashboard URL with UTM.
- CTA language should say "lọc signal", "xem tin phù hợp", or "liên hệ tin này".
  Do not use "lưu watchlist", "nhận Telegram", or "nâng VIP" as the marketing
  promise.

## AI SEO Layer

Keep AI SEO practical:

- Maintain `/llms.txt` with the priority market and ward pages.
- Keep answer-first H2/FAQ blocks on SEO pages.
- Keep JSON-LD for Article/Breadcrumb/FAQ where relevant.
- Show update date, data source, methodology, and due-diligence caveat.
- Run a monthly manual check for 10-20 key queries in ChatGPT, Gemini,
  Perplexity, and Google AI results. Daily AI-visibility checking is noise.

### Deterministic public-page audit

Run this config-only gate before a marketing release:

```powershell
& $py -X utf8 scripts\audit_marketing_pages.py --strict
& $py -X utf8 scripts\audit_marketing_pages.py --json --limit 200
```

Hard failures cover canonical definitions, dashboard query contracts, dates,
FAQ completeness, required discovery documents, and live-ward coverage.
Metadata length, answer-first length, duplicate intent, and optional
visual/link gaps are warnings only. This audit does not prove production
indexing, rankings, or traffic.

### Priority visibility and Search Console evidence

The P1-P3 traffic registry is bounded to 20 pages. Verify their live or local
HTTP visibility separately from the config audit:

```powershell
& $py -X utf8 scripts\verify_traffic_visibility.py --base-url http://127.0.0.1:5000 --json
& $py -X utf8 scripts\verify_traffic_visibility.py --base-url https://radarbds.vn --timeout 10 --json
```

The command checks robots, sitemap coverage, status, `X-Robots-Tag`, meta
robots, self-canonical, and one-H1 rendering. Fetch, authentication, and network
failures are `unknown`; they are never relabeled as passes.

To add query evidence, export the Search Console Performance table as CSV and
pass the file explicitly:

```powershell
& $py -X utf8 scripts\verify_traffic_visibility.py --base-url https://radarbds.vn --gsc-csv .\scratch\gsc-pages-queries.csv --json
```

The importer accepts English or Vietnamese GSC column headers and aggregates
only canonical priority paths. It reports clicks, impressions, recalculated
CTR, and impression-weighted position. Dashboard/contact clicks remain
`unknown` unless a separate compatible analytics export is supplied; GSC
clicks must not be treated as product conversions.

## Analytics Questions

Track only what drives decisions:

| Question | Events / source |
|---|---|
| Which SEO pages bring qualified traffic? | GA4 + `seo_landing_viewed`, `report_viewed` |
| Which social posts create visits? | UTM + `social_utm_visit` |
| Which AI tools send visits? | `ai_referral_visit` |
| Which public pages push users to a filtered dashboard? | `cta_clicked` with target path plus PII-free `dashboard_tab` and `dashboard_filter_keys` |
| Which filtered dashboard sessions contact a deal? | `lead_vip_click`, `vip_cta_click`, lead rows |

Do not treat `watchlist_create` or `telegram_linked` as primary marketing
success metrics for this phase.

## Existing Admin Tracking Screen

There is an admin growth panel at `/admin/tang-truong` backed by
`/admin/api/growth`. It tracks crawl volume, signal count, unique lots, price
drops, users, leads, and a bounded marketing-source view. The marketing object
is independent of the Facebook/Guland listing-source toggle and contains:

- `coverage`: canonical page-view coverage, scan counts, first/last event time,
  legacy coverage, and the truncation flag;
- `channels`: current/previous view counts in fixed channel order;
- `landing_pages`, `campaigns`, and `cta_targets`: compact, deterministic top
  tables, capped at 20 display rows by default;
- `dashboard_handoffs`: current/previous count of CTA clicks that opened the
  root dashboard with at least one approved response-changing filter name;
- `directly_attributed`: lead submit event counts and lead-table row counts kept
  as separate measurements, plus statuses from directly attributed rows only;
- `unattributed`: explicit current/previous counts for evidence that cannot be
  assigned without inference.

The **Hành vi, quay lại và thanh toán** section adds three views to the same
admin-only API and follows the selected Vietnam calendar period.

- **Behavior** counts instrumented actions and distinct signed-in accounts
  per action. Guest actions contribute to event totals. Do not sum the account
  column across actions. Use the existing tool table to distinguish attempts,
  results, and failures. Use GA4 for sitewide sessions and anonymous visitors.
- **D1 and D7** use the accounts registered during the selected period. A
  return is a tracked product action on the exact Vietnam calendar day after
  signup. The denominator excludes accounts whose return day has yet to end.
- **Commerce** counts created digital-product orders, confirmed paid orders
  from that cohort, and pending or closed unpaid orders. Cash received and
  its order count are independently grouped by payment date. This report does
  not attribute a purchase to an anonymous session or traffic channel.

The page engagement table uses first-party measurements from instrumented public
pages. Each document load has a random ID with no cross-page identity. One
initial measurement and periodic updates use cumulative visible time, stopping
after 60 seconds of inactivity and capped at 30 minutes per load. Tabs restored
from browser history may continue the same measurement. A departure under 10
seconds is measured only where the browser delivered a departure event.
Scroll milestones apply to long article content and show the share reaching each
depth. They indicate scroll position, not whether the reader read each paragraph.
Time and depth are deduplicated per page load within the reporting period.
Coverage begins with this release and excludes admin and browsers that opt out
via Global Privacy Control or Do Not Track.

### Measurement definitions

These are **event counts**, not unique visitors or people. The same person may
produce several page views, CTA clicks, a `lead_capture_submit` event, and one
`lead_captures` row. Never add those values together and label the sum as leads
or users.

`dashboard_handoffs.filtered_cta_clicks_*` is a CTA-intent metric, not proof
that the destination loaded or that a person contacted a listing. It retains
only the dashboard tab and approved filter *names* (for example `ward` or
`mos_min`), never their values, free-text search, phone, email, or raw URL
query. Older events do not gain this field retrospectively.

Use `docs/seo_geo_lead_baseline.md` for the fixed 20-query watchlist and the
two-week GSC/GA4/admin baseline procedure. Keep Search Console clicks, CTA
events, and lead rows as separate measurements; do not infer a person-level
funnel by joining anonymous records.

Canonical page views use exactly one channel with this precedence:

1. recognized AI UTM/referrer -> `ai`;
2. recognized social source/medium -> `social`;
3. organic UTM medium or recognized search hostname -> `organic`;
4. everything else -> `direct_unknown`.

Historical `seo_landing_viewed` or `report_viewed` records without a sanitized
channel remain `legacy_unknown`. Compatibility events such as
`social_utm_visit` and `ai_referral_visit` do not relabel a nearby canonical
view.

A lead event is **directly attributed** only when that same
`lead_capture_submit` context contains a normalized page path or campaign
fields. A lead row is directly attributed only when its own allowlisted
`listing_url` or marketing `source_context` carries the landing/campaign
evidence. Otherwise it remains `unattributed`. Never join anonymous records by
IP, user-agent, or timestamp proximity; also never join by phone, email,
fingerprint, free-form note, or guessed session continuity.

Current means `[current_start, current_end)` and previous means
`[previous_start, current_start)`, using the period boundaries returned by the
growth endpoint. Queries read only that combined window. Audit reads stop at
20,000 rows and lead reads stop at 5,000 rows; reaching either cap sets
`coverage.truncated=true`. Malformed or non-object legacy JSON is treated as an
empty context, never as an endpoint failure and never as inferred attribution.

For a local/test diagnostic only, authenticate a local admin session first and
inspect the existing admin endpoint (there is no public analytics endpoint):

```powershell
$radarGrowthUri = "http://127.0.0.1:5000/admin/api/growth?period=day&anchor=2026-08-08&include_guland=0"
Invoke-RestMethod -Uri $radarGrowthUri -WebSession $radarAdminSession
```

## Hermes Ownership

Codex marketing automations are retired. Hermes on the VPS is the intended
operator for daily SEO and marketing tasks.

Hermes must use `docs/hermes_marketing_workflow.md` as the operating contract.
Keep durable state in repo files or the Hermes state directory described there;
never keep the only copy of marketing state in a chat session.

## Output Shape For Any Marketing Run

Use this short report shape:

```text
Mode: shipped / drafted / skipped / blocked
Task: SEO refresh / new SEO URL / Facebook draft / tracking QA
Source evidence:
URL affected:
Dashboard/filter URL:
CTA path:
UTM if any:
Verification:
State updated:
Next priority:
```
