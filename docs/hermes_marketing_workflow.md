# Hermes Marketing Workflow

This is the operating contract for running Radar BDS SEO and marketing tasks
with Hermes on the production VPS. Another AI session should be able to continue
from these files without reading old chat history.

## Scope

Hermes owns daily marketing checks for:

- SEO page refreshes;
- one new SEO URL when justified;
- Facebook/Page draft creation with UTM links;
- AI SEO checks;
- tracking QA for SEO/social/AI traffic.

Hermes does not own crawl logic, valuation, parser changes, DB schema changes,
pricing, VIP strategy, Telegram push, or broad product refactors.

## Funnel

```text
Google / Facebook / AI assistant
  -> exact SEO page or filtered URL
  -> dashboard signal feed filtered by ward/cluster
  -> user reviews signal card
  -> user clicks contact / lead CTA
```

The default dashboard URL is `/?tab=signals`.

Ward pages should prefer `/?tab=signals&ward=<ward name>`.

## Daily Cadence

Run once per day after crawl data is expected to be fresh.

A daily run may skip. Do not force a new page or post just because the job ran.

## Required State

Keep repo state:

- `.agents/seo-publish-history.md`
- `.agents/loops/daily-seo-publisher.log`
- `.agents/distribution-pack-history.md`

Recommended VPS-only Hermes state:

```text
/srv/radar-bds-marketing/state/state.json
/srv/radar-bds-marketing/state/runs.ndjson
/srv/radar-bds-marketing/drafts/
/srv/radar-bds-marketing/STOP
```

If any state source disagrees, the first run is reconciliation only.

## Decision Order

1. If `/srv/radar-bds-marketing/STOP` exists, stop immediately.
2. Pull latest repo state in a separate Hermes checkout, not the live production
   checkout.
3. Verify expected marketing files are readable.
4. Compare SEO article registry, publish history, run log, sitemap, and live URL
   status.
5. Choose exactly one action:
   - repair state drift;
   - refresh one existing SEO page;
   - add/fix one internal link or CTA to a filtered dashboard URL;
   - publish one new non-duplicate SEO URL;
   - draft one Facebook/Page post with UTM;
   - skip.
6. Verify locally.
7. Deploy only through the approved production deploy wrapper with rollback.
8. Verify live route, canonical, sitemap, CTA target, and tracking.
9. Append run state.

## 80/20 Scoring

Score candidates before acting:

| Weight | Factor |
|---:|---|
| 40% | real search/customer demand |
| 30% | direct fit to filtered dashboard and signal contact path |
| 20% | unique Radar data/evidence |
| 10% | effort/risk |

Choose the highest score that can be safely verified today.

## SEO/AIO Rules

- Prefer improving existing location/report pages over creating new articles.
- New articles are capped at one per week unless the user explicitly changes
  cadence.
- Do not create thin street pages or keyword-swapped ward variants.
- Keep `llms.txt`, FAQ, structured data, update date, source, and methodology
  consistent.
- Run AI visibility checks monthly, not daily.

## Facebook/Page Draft Rules

Use Facebook as distribution, not as the main strategy.

Draft format:

```text
Hook: one specific number or signal
Insight: 1-2 short observations
Caveat: verify field/legal/source before acting
Link: exact SEO page or filtered dashboard URL with UTM
```

Default UTM:

```text
utm_source=facebook
utm_medium=social
utm_campaign=traffic_p1_p3_<yyyymmdd>
utm_content=<cluster_stage_index>
```

Generate the bounded P1-P3 review pack from the 20-page traffic registry:

```powershell
& $py -X utf8 scripts\generate_traffic_distribution_pack.py `
  --date 2026-08-11 `
  --channel all `
  --output-dir artifacts\marketing\traffic-p1-p3 `
  --format both
```

The command creates deterministic JSON and Markdown for Facebook, brokers,
local media, and communities. Every item must remain `review_required`; stable
queue IDs prevent duplicate entries when the same date/channel pack is rebuilt.
Generated artifacts are drafts and stay ignored until a human reviews them.

Do not auto-post or send these drafts. External distribution still requires a
separate explicit authorization, an allowlisted destination, isolated tokens,
duplicate guards, and a bounded daily cap.

## Tracking QA

Marketing tracking should answer:

- Which SEO/report pages got visits?
- Which UTM posts brought visits?
- Which AI tools referred visits?
- Which pages sent users to dashboard?
- Which filtered sessions produced contact/lead clicks?

The current admin screen is `/admin/tang-truong`. It is a growth/product panel,
not yet a dedicated marketing attribution screen. Treat a dedicated
SEO/social/AI dashboard as a future small improvement.

## Hard Stops

Stop and report `blocked` if:

- repo state is dirty in unexpected files;
- publish history and registry disagree;
- live route/canonical/sitemap cannot be verified;
- deployment rollback wrapper is unavailable;
- action would require secrets, Meta tokens, admin cookies, phone numbers, or
  original listing URLs in prompt/logs;
- proposed work touches crawl, valuation, dedup, parser, or production DB schema.

## Output Shape

```text
Mode:
Action:
Evidence:
Files touched:
Dashboard/filter URL:
UTM:
Verification:
State updated:
Blocked reason:
Next priority:
```
