# Guland Publisher Activity Filter Design

**Date:** 2026-07-31
**Status:** Approved in conversation; awaiting written-spec review
**Scope:** Guland publisher identity capture, activity classification, user-facing ranking/filtering, and active-listing backfill

## 1. Goal

Prefer Guland listings that are more likely to come from an occasional owner or
a broker posting manually. De-prioritize or hide listings from publishers that
post or bump at tool-like volume.

This is a source-behavior signal, not a data-correctness verdict:

- It must not delete listings.
- It must not merge Guland listings across source IDs.
- It must not write publisher activity into valuation/source-quality flags.
- It must not change fair value, MOS, signal scoring, price history, or
  `first_seen_at`.

## 2. Current-State Findings

The current `guland_cluster_flood` rule groups four or more nearly identical
Guland listings by ward, property type, rounded area, rounded price, and title
signature. It is a content-cluster rule, not a publisher-activity rule, and it
currently participates in the actionable-signal suppression gate.

A local database audit found:

- 6,167 Guland listings.
- No populated `seller_name` values.
- 6,143 populated `contact_phone` values, but recent Guland rows all shared one
  normalized value.
- None of those stored values matched the phone extracted from the listing
  description.
- 1,770 descriptions contained an extractable phone, representing 150 distinct
  description phones.

The crawler currently selects the first `tel:` link on the whole detail page,
which can capture a Guland support/footer hotline. The existing
`contact_phone` field cannot be used as publisher identity until this is fixed.

## 3. Chosen Approach

Use a hybrid of explicit thresholds and a transparent activity score.

Pure fixed thresholds are easy to explain but fail to distinguish a busy manual
broker from automated bumping. A score-only model is flexible but difficult to
audit. The hybrid keeps the user-facing classes deterministic while using
multiple pieces of evidence to identify automated repost behavior.

## 4. Publisher Identity Capture

### 4.1 Evidence priority

Capture the strongest available publisher identity in this order:

1. Guland member/user ID or canonical publisher profile URL.
2. Phone found inside the listing's contact/author component.
3. Phone extracted from the listing description.
4. No reliable identity: `unknown`.

A page-global `tel:` link is never accepted. Known Guland support/hotline
numbers and contact elements inside footer/header/support components are
rejected.

### 4.2 Raw fields

Preserve source evidence in `raw_json` and raw revisions:

- `publisher_source_id`
- `publisher_profile_url`
- `publisher_name`
- `publisher_phone`
- `publisher_identity_type`
- `publisher_identity_confidence`

Missing fields are valid. A failed identity extraction must not make the
listing crawl fail.

### 4.3 Stable publisher key

Create a stable, non-public `publisher_key`:

- Member identity: keyed hash of `guland:member:<member-id>`.
- Profile identity: keyed hash of the canonical profile URL.
- Phone identity: keyed hash of the normalized Vietnamese phone.

Use a dedicated production environment secret for the keyed hash. Never expose
`publisher_key`, raw publisher phone, or profile identifiers through non-admin
APIs.

### 4.4 Processed data

Use isolated publisher tables rather than overloading listing quality fields:

- `source_publishers`: one row per stable publisher key, current class,
  confidence, reasons, first/last observation, and aggregate activity.
- `listing_publishers`: one current publisher link per listing, including
  evidence type and confidence.
- `publisher_activity_daily`: daily counts used to recompute classifications.

The raw listing remains the source of truth, so publisher links and aggregates
can be rebuilt.

## 5. Activity Measurements

Use:

- `first_seen_at` for a newly discovered source ID.
- Raw revision observations for date changes, content refreshes, and repeated
  reappearance.
- Distinct source IDs for new-listing volume.
- Similarity signatures only for spam classification, never for Guland dedup or
  same-lot history.

Do not use the latest Guland displayed date as the listing's original date.
Guland may change that date when a listing is bumped.

For each publisher, calculate:

- New distinct listings in 1, 7, and 30 days.
- Maximum new listings on one day.
- Days active in the last 30 days.
- Existing source IDs refreshed/bumped in 7 and 30 days.
- Same-day near-duplicate source IDs.
- Proportion of listings using repeated title/description templates.

## 6. Classification Rules

Classification requires medium- or high-confidence publisher identity. Missing
or low-confidence identity remains `unknown`.

### 6.1 `low_manual`

All of the following:

- No more than 5 new listings on any observed day.
- No more than 30 new listings in the last 30 days.
- Does not match an automated-repost rule.

This class includes occasional owners and lower-volume/manual brokers. It does
not claim that the publisher is legally the owner.

### 6.2 `high_activity`

Either:

- More than 5 new listings on an observed day; or
- More than 30 new listings in the last 30 days.

The publisher does not yet meet the stronger automated-repost evidence below.

### 6.3 `automated_repost`

Any of the following:

- At least 30 distinct new listings on one observed day.
- The same source ID is bumped or has its source date changed at least 3 times
  in 7 days.
- At least 10 near-duplicate source IDs are observed for the publisher on one
  day.
- At least 15 new listings per day are observed on 3 days within a rolling
  14-day window and repeated-template evidence is present.

### 6.4 `unknown`

Publisher identity is missing or confidence is insufficient. Unknown is not a
spam verdict and remains visible after `low_manual`.

### 6.5 Positive manual override

Admin can override a publisher to:

- `allow_manual`
- `hide_high_activity`
- `clear_override`

Overrides are audited and take precedence over automatic classification.

## 7. User-Facing Behavior

### 7.1 Normal users

Change the default Guest/Free/VIP source policy from Facebook-only to
Facebook plus Guland. Guland rows then pass through the publisher visibility
policy below; Facebook behavior is unchanged.

For every normal user-facing surface:

- Show `low_manual`.
- Show `unknown` after `low_manual`.
- Hide `high_activity` and `automated_repost`.
- Preserve the existing deal/date ordering within each visible publisher class.

Apply the same predicate to:

- Paginated listing/signal cards.
- Guland map markers.
- Dashboard/tab counts derived from the feed.
- Infinite-scroll page 2+ queries.

This prevents count/card mismatches.

Normal users do not receive a control that reveals `high_activity` or
`automated_repost`. Selecting Guland in the public source filter, where that
control is rendered, still applies the publisher visibility policy.

### 7.2 Admin

Admin receives a toggle:

> Ẩn người đăng dày/repost

The toggle defaults to on. When off, admin sees all four classes. Admin cards
may show the class and short reason, but no publisher identity is added to
regular-user payloads.

### 7.3 Failure behavior

The filter is fail-open for missing data:

- Missing identity becomes `unknown`.
- A failed activity refresh keeps the previous class.
- A listing with no publisher link remains visible in the `unknown` group.
- Crawl/network errors never promote a publisher to `high_activity` or
  `automated_repost`.

## 8. Retiring `guland_cluster_flood` as a Hard Gate

Stop generating `guland_cluster_flood` as a valuation/source-quality flag and
remove it from the actionable-signal suppression set.

Historical valuation rows may retain the old text for audit, but it must no
longer suppress user-facing signals. New publisher classifications live only in
the publisher activity subsystem.

Content similarity may still be reused as one input to `automated_repost`, but
it must never merge Guland source IDs or change lot/price history.

## 9. Backfill

### 9.1 Target set

Backfill the union of:

1. Guland source IDs discovered in the current configured ward/category crawl
   URLs.
2. Database Guland listings with `is_active=1` and
   `source_status='active'`.
3. `unknown` or `unreachable` listings attempted once; include them only if the
   direct detail page is confirmed live.

Exclude confirmed `inactive` listings.

### 9.2 Backfill behavior

The command is dry-run by default and requires `--apply` to write.

It must:

- Be bounded by `--limit` and support resume/checkpoint.
- Respect Guland crawl throttling and the existing crawl lock.
- Refresh source evidence through the existing raw revision mechanism.
- Update only publisher evidence, publisher links, and publisher aggregates.
- Preserve `first_seen_at`, listing identity, posted-date semantics, price
  history, images, coordinates, and valuation data.
- Be idempotent.

The command reports before apply:

- Candidate count by source status.
- Pages expected to fetch.
- Identity coverage by evidence type.
- Estimated class counts.
- Count of records that would remain `unknown`.

## 10. Daily Crawl Integration

For new and refreshed Guland listings:

1. Extract publisher evidence with the listing detail.
2. Save raw listing/revision.
3. Resolve or create the publisher link.
4. Update the publisher's daily activity row.
5. Recompute only affected publisher classifications.
6. Continue existing normalization, valuation, image, coordinate, and lifecycle
   processing unchanged.

The publisher update must not add an external LLM or paid enrichment step.

## 11. API and Query Contract

Create one shared SQL/helper predicate for publisher visibility and reuse it on
all user-facing Guland queries.

Admin payload additions:

- `publisher_activity_class`
- `publisher_activity_reason`
- `publisher_identity_confidence`

Non-admin payloads may receive only a presentation-safe trust group if needed
for ordering. They must not receive phone, profile URL, member ID, or stable
publisher key.

Dashboard counts and card/map queries must use the same classification snapshot
to remain consistent during recomputation.

## 12. Testing

### 12.1 Extraction

- Reject page footer/header/support hotline.
- Accept listing-scoped contact phone.
- Fall back to description phone.
- Prefer member/profile identity over phone.
- Return `unknown` without failing when no identity exists.

### 12.2 Classification

- Exact boundary tests for 5/day, 6/day, 30/30 days, and 31/30 days.
- Exact boundary tests for 29/day and 30/day automated volume.
- Three bumps in 7 days.
- Ten same-day near-duplicate source IDs.
- High volume without sufficient identity remains `unknown`.
- Admin override precedence.

### 12.3 Data safety

- Backfill dry-run performs no writes.
- Apply is idempotent.
- `first_seen_at`, price history, valuation results, coordinates, images, and
  source ID remain unchanged.
- Similar content never creates a Guland `duplicate_of_id` relationship.
- Raw revisions contain only actual source changes.

### 12.4 Visibility

- Normal user sees `low_manual` then `unknown`.
- Normal user does not see `high_activity` or `automated_repost`.
- Admin toggle on matches normal-user filtering.
- Admin toggle off shows all classes.
- Dashboard count equals paginated feed count.
- Map marker count follows the same visibility predicate.
- Page 2+ cannot reintroduce hidden publishers.

## 13. Observability and Rollout

Log and expose admin-only metrics:

- Identity coverage percentage.
- Class counts and transitions.
- Number hidden from normal-user surfaces.
- Hotline rejection count.
- Backfill attempted/live/unreachable/error counts.

Roll out in this order:

1. Deploy schema and extraction with fail-open `unknown`.
2. Run a production dry-run for the bounded target set.
3. Review identity coverage and class distribution.
4. Apply the approved backfill.
5. Enable normal-user filtering and verify card, count, and map parity.

Production apply remains a separate explicit data operation. Deployment alone
must not start a full historical backfill.

## 14. Non-Goals

- Proving that a publisher is the legal property owner.
- Deleting broker listings.
- Changing Guland lot dedup from source-ID identity.
- Using an LLM to classify publishers.
- Re-crawling confirmed inactive historical listings.
- Replacing price/source correctness gates with publisher activity.
