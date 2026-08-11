# Traffic P1-P3 System Design

**Date:** 2026-08-11
**Project:** Radar BDS
**Status:** Conversational design approved; awaiting written-spec review

## Objective

Turn the existing marketing inventory into a small, measurable traffic system
that improves discovery, qualified visits, and movement into the signal-first
dashboard. The system must preserve the public funnel:

```text
SEO / social / AI answer / referral
  -> exact priority page
  -> filtered signal dashboard or valuation tool
  -> signal card
  -> contact or lead CTA
```

P1-P3 is an optimization of shared positioning, measurement, proof, internal
links, and distribution. It is not a request to publish more pages at scale,
change crawl or valuation logic, or automate external posting.

## Baseline and Problem Statement

The AI-SEO work already merged into `main` provides a broad, valid public
surface, reusable trust markup, machine-readable discovery, and a deterministic
marketing audit. The current worktree starts from commit `638afa2`.

The focused baseline passed 108 tests covering public SEO, marketing trust,
tracking, page auditing, content hubs, homepage UI, social queueing, and the
14-day growth workflow. This proves the current local contracts; it is not
proof of Google indexing, production traffic, or external distribution.

The remaining traffic constraints are:

1. The regular homepage has no meaningful product H1. Its only H1 is the
   hidden-by-state `BDS đã lưu` heading that also serves `/bds-da-luu`.
2. Product positioning still overemphasizes product mechanics and older
   watchlist/alert jobs instead of the current decision job: find a reasonably
   comparable Bình Dương listing, inspect its evidence, then decide whether to
   contact.
3. The site has many valid pages but no single deterministic registry that says
   which pages should receive indexing checks, proof enrichment, internal-link
   equity, and distribution effort first.
4. Local HTTP and sitemap checks cannot establish Google Search Console truth.
   Query, impression, CTR, and index-coverage evidence must remain explicitly
   unknown until imported or inspected through an authorized GSC session.
5. Existing social tooling is capable of queueing and posting, but P3 needs a
   reviewable distribution and outreach asset first. External posting or
   outreach is outside this design's authorization.

## Chosen Approach

Use one deterministic 20-page priority registry as the shared source for:

- P1 visibility and GSC reporting;
- P2 proof and internal-link validation;
- P3 distribution packs, UTM URLs, deduplication, and outreach drafts.

This integrated approach is preferred over two alternatives:

- **Content-first expansion:** rejected because the site already has a broad
  inventory and more pages would dilute validation and internal links before
  current visibility is understood.
- **Measurement-only work:** rejected because measurement would expose gaps but
  would not improve the homepage promise, evidence, or distribution assets that
  can earn qualified clicks.

## Priority Registry Contract

Add `config/traffic_priority.py` as the sole P1-P3 priority registry. It does
not replace `config/seo_pages.py`, `config/seo_articles.py`,
`config/seo_locations.py`, or the sitemap registry; those remain authoritative
for page content and canonical existence.

The registry exports `TRAFFIC_PRIORITY_PAGES` in stable order. Every item has:

| Field | Contract |
|---|---|
| `path` | Absolute, canonical, query-free public path |
| `cluster` | Stable acquisition cluster used for related links and reporting |
| `buyer_stage` | `discover`, `compare`, or `decide` |
| `dashboard_href` | Internal CTA with only supported dashboard/tool query keys |
| `proof_mode` | `live_snapshot`, `published_dataset`, or `method_only` |
| `proof_source` | Named existing source/helper; never a prose metric placeholder |
| `distribution_angle` | Short factual angle used by the pack generator |
| `active` | Boolean; only active rows participate in P1-P3 commands |

The registry contains exactly these 20 active, unique paths:

| # | Path | Cluster | Stage |
|---:|---|---|---|
| 1 | `/` | product | decide |
| 2 | `/binh-duong` | market | discover |
| 3 | `/bao-cao` | reports | compare |
| 4 | `/dinh-gia-bds` | valuation | decide |
| 5 | `/binh-duong/phuong-tan-an` | ward | compare |
| 6 | `/binh-duong/phuong-hiep-an` | ward | compare |
| 7 | `/binh-duong/phuong-tuong-binh-hiep` | ward | compare |
| 8 | `/binh-duong/phuong-dinh-hoa` | ward | compare |
| 9 | `/binh-duong/phuong-chanh-my` | ward | compare |
| 10 | `/binh-duong/phuong-phu-my` | ward | compare |
| 11 | `/binh-duong/phuong-phu-cuong` | ward | compare |
| 12 | `/binh-duong/phuong-phu-hoa` | ward | compare |
| 13 | `/binh-duong/phuong-phu-loi` | ward | compare |
| 14 | `/binh-duong/phuong-hiep-thanh` | ward | compare |
| 15 | `/binh-duong/phuong-chanh-nghia` | ward | compare |
| 16 | `/binh-duong/phuong-phu-tan` | ward | compare |
| 17 | `/binh-duong/phuong-hoa-phu` | ward | compare |
| 18 | `/quy-hoach-binh-duong/dia-gioi-36-phuong-xa-binh-duong-cu` | transition | discover |
| 19 | `/tin-tuc/nha-dat-thu-dau-mot-duoi-3-ty-phuong-nao-nhieu-lua-chon` | budget | decide |
| 20 | `/tin-tuc/cach-dinh-gia-nha-dat-binh-duong-bang-gia-rao-theo-phuong` | valuation | decide |

The 13 ward paths must be derived/tested against `TDM_LIVE_WARDS`; the written
list is an acceptance snapshot, not a second ward taxonomy. Existing valuation
aliases remain unchanged: TDC/TDC Phú Chánh data resolves through Phú Tân, and
KDC Hiệp Thành through Hiệp Thành.

## P1 - Indexing, Positioning, and Measurement

### Homepage semantics

The regular homepage renders exactly one visible H1:

> Săn deal nhà đất Bình Dương bằng dữ liệu

`/bds-da-luu` retains exactly one H1:

> BDS đã lưu

The saved-listings title must be an H2 or absent from the regular homepage's
heading outline. This is a conditional render contract, not a CSS-only fix.
The homepage title, description, H1, trust copy, and primary CTA must describe
the same signal-first promise.

### Product-marketing context

Update `.agents/product-marketing.md` without inventing traction. The new
context must include:

- a one-line promise centered on comparing public Bình Dương listings and
  finding signals worth checking;
- the current primary job-to-be-done and the steps from question to contact;
- named alternatives: Batdongsan.com.vn, Nhà Tốt, Thư Viện Pháp Luật for legal
  lookup, local broker pages/groups, and manual Facebook scanning;
- truthful differentiation: normalized listings, comparable local segments,
  fair-value/MOS screening, source warnings, and direct filtered handoff;
- proof inventory split into `verified`, `needs live verification`, and
  `unavailable`; no placeholder conversion rate or market-size claim;
- the current conversion path, with watchlist/Telegram/VIP as secondary product
  capabilities rather than the homepage promise.

### Visibility verifier

Add `scripts/verify_traffic_visibility.py`. Its default input is the priority
registry; it supports:

```text
--base-url URL       target local or production origin
--gsc-csv PATH       optional Search Console Performance CSV export
--json               bounded machine-readable output
--timeout SECONDS    bounded per-request timeout
```

For the target origin it checks:

- `/robots.txt` is reachable, does not disallow the priority paths, and names
  the canonical sitemap;
- `/sitemap.xml` is valid XML and contains every active priority path;
- every priority response is successful and lacks blocking `X-Robots-Tag` or
  meta-robots directives;
- each page has one self-canonical and exactly one H1;
- canonical URLs do not retain UTM or unsupported filter parameters.

The verifier separates three states: `pass`, `fail`, and `unknown`. Network,
authentication, missing GSC export, and rate-limit failures are `unknown`, not
passes.

When `--gsc-csv` is supplied, the importer accepts Google's page/query export
columns in Vietnamese or English, normalizes each page to a canonical path,
and aggregates only the priority registry. The report provides:

```text
query -> canonical page -> clicks -> impressions -> CTR -> average position
```

It then joins local `cta_clicked`/`seo_landing_viewed` aggregates only when an
explicit compatible export is provided. A missing analytics join is shown as
`unknown`; it must never be inferred from GSC clicks.

During implementation, use an existing authorized logged-in GSC browser
session if available to inspect sitemap submission and representative URLs.
Do not log in, request credentials, submit changes, or claim index coverage
when that session is unavailable.

## P2 - Money Pages, Proof, and Internal Links

### Priority proof block

Add a small reusable proof presenter and partial for the priority pages. It
must render the strongest truthful evidence already available in this order:

1. a page-specific live snapshot with its actual query/update time;
2. a published report/article dataset with its recorded period/date;
3. a factual method-only statement that names coverage, source type, and
   limitations without numbers.

The block exposes visible, consistent labels for scope, source, updated/period,
method, and limitation. Missing optional values are omitted. A failed live
lookup falls back to method-only text and must not substitute seeded rows,
stale generated counts, or today's date.

Reuse `templates/partials/seo_trust.html` where it already expresses the
contract; do not display duplicate trust boxes on the same page. Reports keep
their stronger existing methodology sections.

### Internal-link graph

Add a deterministic helper driven by the registry that selects up to four
related priority pages:

1. same cluster and adjacent decision stage;
2. relevant market/report/valuation hub;
3. the signal-first dashboard CTA.

Existing editorial links remain. Generated priority links are deduplicated by
canonical path and cannot repeat the current page. Anchor text is descriptive,
not generic `xem thêm`. The helper must not create cross-links solely because
two pages share a keyword; the registry cluster and explicit related rules are
the contract.

### Audit extension

Extend the existing `services/marketing_page_audit.py` and
`scripts/audit_marketing_pages.py`; do not create a competing config-only
auditor.

Priority hard failures are:

- count is not exactly 20, active paths are duplicated, or a path is absent
  from the canonical inventory;
- the 13 ward rows drift from `TDM_LIVE_WARDS`;
- sitemap or self-canonical coverage is missing;
- a `dashboard_href` contains unsupported filters or an invalid tab;
- a priority page lacks the proof/trust contract or a signal-first/tool CTA;
- a priority link points to itself, duplicates another link, or points to an
  inactive/noncanonical path.

Possible intent overlap, long metadata, and missing optional visuals remain
warnings until query/impression evidence justifies a redirect, merge, or
rewrite.

## P3 - Citeable Authority and Reviewable Distribution

### Data and methodology authority asset

Upgrade the existing `/tin-tuc/du-lieu-radarbds` page rather than adding a thin
new URL. Keep its current searchable article archive and add an answer-first,
citeable methodology section above it covering:

- geographic coverage and the Bình Dương-cũ naming transition;
- Facebook-primary and Guland-secondary public listing sources;
- normalization, canonical listing identity, comparable local segments,
  fair value, MOS, and actionable quality gates at a public-safe level;
- update cadence stated as a process, not an unsupported freshness guarantee;
- price-ratio, legal, planning, duplicate, publisher, and real-world inspection
  limitations;
- links to the report hub, all 13 ward pages, the valuation tool, and the
  signal-first dashboard.

Visible copy and JSON-LD must agree. A `Dataset` or methodology schema node may
be added only for facts displayed on the page. Do not publish internal
credentials, private endpoints, original restricted listing URLs, phone
numbers, or admin-only fields.

### Distribution pack generator

Add `scripts/generate_traffic_distribution_pack.py`. It consumes only active
priority rows and emits deterministic Markdown and JSON into a caller-selected
directory:

```text
--date YYYY-MM-DD
--channel facebook|broker|local_media|community|all
--output-dir PATH
--format markdown|json|both
```

Each queue item contains:

| Field | Contract |
|---|---|
| `queue_id` | Stable SHA-256 key of path, channel, campaign, and content angle |
| `path` | Canonical priority path |
| `canonical_url` | Clean production URL without tracking parameters |
| `utm_url` | Same URL with normalized lowercase UTM parameters |
| `channel` | Explicit supported channel |
| `angle` | Registry-derived factual distribution angle |
| `copy` | Reviewable draft; no invented metric or legal conclusion |
| `status` | Always `review_required` in generated output |

UTM keys are limited to `utm_source`, `utm_medium`, `utm_campaign`, and
`utm_content`. Values are lowercase ASCII slugs. Query ordering is stable.
Regeneration with the same inputs produces the same queue IDs and does not
append duplicates to an existing JSON queue.

The command includes validators that reject phone-like strings, email
addresses, non-public listing URLs, admin/auth URLs, and unsupported query
parameters. It imports no browser, Facebook, email, webhook, or posting client.
It must not call `scripts/radar_social_auto_post.py` or any external service.

### Outreach/citation pack

The Markdown output includes separate, short drafts for brokers, local media,
and communities. Each draft leads with a useful data/methodology asset, states
the limitation of asking-price data, and links to one priority page using the
channel's UTM contract. These are review assets, not sent messages.

P3 is complete when the authority page, deterministic generator, deduplicated
queue, and review-ready outreach drafts pass tests. Earned backlinks, group
posts, replies, and media publication are external outcomes and cannot be
claimed without later authorization and live evidence.

## Data Flow

```text
canonical page registries + TDM_LIVE_WARDS
                |
                v
       traffic_priority.py
          /       |       \
         v        v        v
 visibility    proof +    distribution
 verifier      links      pack generator
     |            |             |
 optional GSC   rendered      Markdown/JSON
 CSV report     pages         review queue
```

No P1-P3 path writes to PostgreSQL, changes dataset versions, starts a crawl,
reprocesses listings, alters valuation, or sends an external message.

## Expected Files in Scope

- `.agents/product-marketing.md`;
- `config/traffic_priority.py`;
- `templates/index.html` and the smallest CSS needed for the homepage H1;
- existing public SEO/content-hub templates plus at most one new shared proof
  partial;
- a small presenter/helper in the existing public marketing layer;
- `services/marketing_page_audit.py`;
- `scripts/audit_marketing_pages.py`;
- `scripts/verify_traffic_visibility.py`;
- `scripts/generate_traffic_distribution_pack.py`;
- focused P1-P3 tests and durable workflow documentation.

Facebook crawl, admin pages, social auto-post code, analytics database schema,
auth/RBAC, Telegram, valuation, normalization, deduplication, and production
data are out of scope.

## Test-First Verification

Implementation follows red-green-refactor in these slices:

1. Homepage tests prove the regular homepage and `/bds-da-luu` each have
   exactly one correct H1 before changing the template.
2. Registry tests prove exactly 20 unique active canonical paths, exact ward
   parity, supported CTA queries, and sitemap coverage.
3. Proof tests cover live, published, and method-only fallbacks and reject
   invented dates/counts.
4. Audit tests prove hard-failure and warning boundaries.
5. Visibility-verifier fixtures cover robots, sitemap, meta/X-Robots,
   canonical, H1, network unknowns, and English/Vietnamese GSC CSV columns.
6. Distribution tests prove deterministic output, stable lowercase UTM,
   queue deduplication, PII/restricted-URL rejection, and absence of any posting
   side effect.
7. Existing focused public SEO, trust, tracking, content-hub, homepage, social
   queue, and growth tests remain green.

Final implementation verification includes:

- Python compilation for changed modules and scripts;
- JavaScript syntax checks only if JavaScript changes;
- strict marketing audit with zero hard failures;
- the focused marketing/P1-P3 pytest matrix;
- local rendered smoke for all 20 paths, canonical/H1/JSON-LD parsing, and safe
  CTA query validation;
- live visibility/GSC checks reported separately from local tests;
- after an authorized release, production HTTP, sitemap, schema, tracking, and
  browser verification.

A timeout, unavailable GSC session, blocked network, or missing analytics
export is reported as unverified/unknown, never as success.

## Release and Safety

All work stays on `codex/traffic-p1-p3`, created from `main`, and staging names
only scoped P1-P3 files. The unrelated Facebook branch and root
`.playwright-cli/` directory remain untouched.

Implementation may be merged back to local `main` only after focused
verification and an explicit integration choice. Push, deploy, sitemap
submission, external posting, and outreach require separate authorization.

## Acceptance Criteria

### P1

- Regular homepage and saved-listings page each render exactly one correct H1.
- Product-marketing context reflects the current signal-first decision job,
  named alternatives, truthful differentiation, and proof status.
- The live verifier checks all 20 paths and separates fail from unknown.
- Optional GSC CSV produces query/page/click/impression/CTR/position reporting
  without fabricating unavailable dashboard conversion data.

### P2

- Exactly 20 active priority paths exist, including all and only the 13
  canonical Thủ Dầu Một wards in the ward slice.
- Every priority path is canonical, sitemap-covered, CTA-valid, and has a
  truthful proof/trust mode.
- Deterministic related links direct authority toward priority pages without
  self-links, duplicates, or unsupported URLs.
- The strict marketing audit reports zero priority hard failures.

### P3

- `/tin-tuc/du-lieu-radarbds` visibly explains sources, method, MOS, scope,
  cadence, and limitations while retaining the article archive.
- The distribution generator produces deterministic Markdown/JSON, lowercase
  safe UTM URLs, stable dedupe keys, and `review_required` status.
- Generated assets contain no PII, restricted listing URLs, auto-post action,
  or invented evidence.
- Outreach drafts are ready for human review; no backlink, post, or outreach
  success is claimed without external evidence.

### Preservation

- Existing public contracts, crawl order, valuation rules, tier redaction,
  tracking sanitization, and AI-SEO behavior remain intact.
- Unrelated user work remains untouched.
- No production completion claim is made without a pushed commit, authorized
  deployment, and public verification.
