# Radar BDS Traffic Marketing Workflow

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

## Analytics Questions

Track only what drives decisions:

| Question | Events / source |
|---|---|
| Which SEO pages bring qualified traffic? | GA4 + `seo_landing_viewed`, `report_viewed` |
| Which social posts create visits? | UTM + `social_utm_visit` |
| Which AI tools send visits? | `ai_referral_visit` |
| Which public pages push users to dashboard? | `cta_clicked` with target path |
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
- `directly_attributed`: lead submit event counts and lead-table row counts kept
  as separate measurements, plus statuses from directly attributed rows only;
- `unattributed`: explicit current/previous counts for evidence that cannot be
  assigned without inference.

### Measurement definitions

These are **event counts**, not unique visitors or people. The same person may
produce several page views, CTA clicks, a `lead_capture_submit` event, and one
`lead_captures` row. Never add those values together and label the sum as leads
or users.

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
