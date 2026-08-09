# Read-Only AI Agent Discovery Design

## Context

Radar BDS already exposes server-rendered public pages, JSON-LD, `robots.txt`,
`sitemap.xml`, `llms.txt`, and bounded Guest APIs. The public signal feed is
already the canonical read path for actionable deals: `/api/signals` applies
the current signal-quality gate, clamps public filters, uses the public cache,
and redacts seller, phone, and original-source fields for every non-admin tier.

The missing layer is an explicit, stable contract that tells an autonomous AI
agent what Radar BDS is, what it may read, which filters are supported, how to
compare signal cards, and which public URL it should return to the user. Today
an agent has to infer those rules from the dashboard JavaScript or guess API
parameters.

This design adds a discovery and documentation layer over the existing Guest
read path. It does not create a separate AI data store, a new valuation model,
or an agent with permission to act on behalf of the user.

## Goals

- Let an AI agent discover Radar BDS and understand its Bình Dương scope.
- Let an anonymous agent find, filter, sort, and compare current public signal
  cards through the existing `/api/signals` implementation.
- Give the agent deterministic filtered-dashboard and listing-detail URL rules
  so it can hand the final decision back to the user.
- Document data meaning, freshness, citation guidance, and due-diligence
  limitations in a stable machine-readable contract.
- Reuse the existing Guest redaction, cache, bounds, and actionable-signal
  policy without introducing another query path.
- Improve the high-value dashboard journey for browser agents through targeted
  semantic HTML and accessibility fixes only where the current markup fails an
  explicit check.

## Non-Goals

- Agent login, registration, session creation, or tier escalation.
- Creating, updating, or deleting watchlists, favorites, leads, reports, or
  any other user or admin record.
- Revealing phone numbers, seller identity, original listing URLs, private
  memos, admin data, or fields hidden from Guest users.
- Letting an agent contact a seller, submit a lead, purchase a product, or make
  an investment decision for the user.
- Publishing auth, admin, checkout, order, webhook, or other write-capable
  endpoints in the agent contract.
- Adding MCP, WebMCP, Universal Commerce Protocol, an OpenAI App, or another
  action protocol in this phase.
- Creating a server-side comparison or recommendation engine. The consuming
  agent compares already-redacted signal cards.
- Rewriting public content for bots, mass-producing AI-only pages, changing
  existing canonical URLs, or redesigning the dashboard.
- Changing crawl, normalization, deduplication, valuation, signal creation,
  database schema, or production data.

## Approaches Considered

### 1. Contract-first discovery over existing Guest APIs (selected)

Publish a compact site manifest and a read-only OpenAPI document. Both point to
the current `/api/signals` and optional `/api/counts` routes. The routes remain
the single source of runtime truth, so agent traffic receives the same cache,
filter, redaction, and signal-quality behavior as the browser dashboard.

This provides a standard machine-readable surface without duplicating data
access logic or creating another production query path.

### 2. Extend only `llms.txt`, robots, and page schema

This is the smallest change, but prose alone cannot reliably communicate exact
parameter types, enum values, bounds, pagination, error responses, or the
read-only security boundary. Agents would still have to guess how to call the
signal feed.

### 3. Add a dedicated AI search API or action protocol

A new `/agent/search` endpoint, MCP server, or browser-action protocol could
provide more agent-specific behavior. It would also duplicate query shaping,
expand the attack surface, and risk drifting from the public dashboard. It is
not justified while the required capability is anonymous read-only discovery.

## Architecture

Create one pure service module and two thin public routes:

```text
services/
  agent_resources.py       # static contract builders and allowlists
routes/
  public.py                # /agent/site.json and /agent/openapi.json routes
app.py                     # thin delegated implementations and discovery links
tests/
  test_agent_readiness.py  # contract, security, discovery, and semantic checks
```

`services/agent_resources.py` owns two deterministic builders:

```python
def build_agent_site_manifest(*, base_url: str) -> dict: ...
def build_agent_openapi_document(*, base_url: str) -> dict: ...
```

The module must not import Flask request/session state, open a database
connection, call a runtime API, or contain current signal rows. It owns the
contract version, the exact endpoint allowlist, filter documentation,
comparison guidance, link templates, and safety limitations.

`app.py` exposes thin functions used by the public blueprint. They call the
builders with the runtime public base URL and return JSON with a short public
cache policy. `routes/public.py` owns the URL registrations:

```text
GET /agent/site.json
GET /agent/openapi.json
```

No new route accepts `POST`, `PUT`, `PATCH`, or `DELETE`.

## Agent Site Manifest

`GET /agent/site.json` is the first machine-readable orientation surface. It
uses a versioned top-level object with these sections:

- `schema_version`: contract schema identifier.
- `name`, `description`, `base_url`, `language`, and `markets`: site identity
  and Bình Dương geographic scope.
- `capabilities`: `read_signals`, `filter_signals`, `sort_signals`,
  `compare_signals`, and `link_user_to_radar`.
- `not_supported`: authentication, mutation, contact submission, seller
  outreach, payment, legal verification, and autonomous investment decisions.
- `discovery`: canonical URLs for `llms.txt`, sitemap, the OpenAPI document,
  methodology/deal explanation, news hub, report hub, and signal dashboard.
- `usage`: recommended first request, pagination guidance, comparison fields,
  filtered-dashboard link guidance, and listing-detail link guidance.
- `freshness`: instructions to use the response's
  `X-Radar-Dataset-Version` header and the agent's own access time rather than
  treating the contract publication date as signal freshness.
- `citation`: cite Radar BDS, include the public Radar URL, identify the filter
  context, and state that asking prices/fair value/MOS are reference signals.
- `limitations`: data comes from public listings; MOS is not a guarantee or
  legal appraisal; field, planning, legal, and source verification remain the
  user's responsibility.

The manifest contains no live listing, user, seller, lead, or session data.

## Read-Only OpenAPI Contract

`GET /agent/openapi.json` publishes OpenAPI 3.1 documentation for exactly two
existing operations:

```text
GET /api/signals
GET /api/counts
```

`/api/signals` is the primary operation. `/api/counts` is optional and should
be called only when an exact filtered count materially helps the answer. The
recommended signal request uses `include_total=0` and a limit of at most 30 so
the agent does not force unnecessary count work or oversized responses.

The document defines only parameter names and values already parsed by the
current handlers. It documents:

- city and ward scope;
- source and property-type filters;
- area and asking-price bounds/ranges;
- MOS threshold;
- keyword and date range;
- price-drop filter where the effective Guest policy permits it;
- the existing signal sort allowlist;
- page, limit, and `include_total` bounds;
- successful compact signal responses;
- `503 temporarily_busy` plus `Retry-After` behavior;
- `X-Radar-Dataset-Version` as the runtime freshness/version signal.

The OpenAPI document must not contain any path under `/admin`, `/auth`,
`/checkout`, `/orders`, `/webhook`, `/watchlist`, `/favorites`, `/leads`, or
other write-capable surfaces. It must not advertise an authorization scheme or
ask agents to send cookies. Agents are instructed to call the public endpoints
anonymously as Guest.

The response schema documents only fields useful for safe comparison, such as
public ID, title, location, property type, area, asking price, price per square
metre, displayed fair-value context, displayed MOS, signal score, activity
date, safe quality warnings, and public navigation information. Seller,
contact, and original-source values are not agent capabilities even if the
runtime Guest payload retains null placeholders for backward compatibility.

## Data and Control Flow

```text
AI agent
  -> GET /llms.txt or /agent/site.json
  -> GET /agent/openapi.json
  -> construct an allowlisted anonymous Guest query
  -> GET /api/signals?include_total=0&limit<=30&...
  -> existing bounded filters
  -> existing public cache/read model
  -> existing actionable-signal query
  -> existing tier-safe redaction
  -> compact public signal payload + dataset-version header
  -> agent compares safe fields and states limitations
  -> agent returns filtered dashboard and optional /listing/<id> URL
  -> user opens Radar BDS and decides whether to inspect/contact
```

There is no agent-specific database query, valuation, ranking, or persistence
step. The selected sort only orders signals already admitted by the current
public signal-quality policy.

## Comparison and Recommendation Language

The contract may teach an agent to compare signal cards using:

- asking price and asking price per square metre;
- displayed fair-value reference and displayed MOS;
- signal score;
- ward, road/sub-zone, property type, area, and dimensions when present;
- price-drop or activity recency;
- quality and source warnings visible to Guest.

The contract must not describe the highest score or MOS as the "best
investment", a guaranteed bargain, or a replacement for due diligence. The
preferred language is "signal đáng kiểm tra trước", "deal đáng soi", or
"phù hợp với bộ lọc". Every comparison should distinguish measured public
listing facts from Radar BDS estimates and from the agent's own synthesis.

## User Handoff URLs

The agent's final answer should link the user back to Radar BDS instead of
attempting a private or write action.

- Broad results use `/?tab=signals`.
- Area results add the current canonical city/ward filter using the same URL
  conventions as the dashboard.
- Other supported filters are included only when the browser dashboard can
  reproduce them deterministically.
- A specific card may include `/listing/<public-id>` as a secondary link.
- Links must never point directly to an original Facebook/Guland URL or expose
  a contact value.

Implementation must derive or validate these templates against the current
frontend query contract rather than documenting guessed parameter names.

## Discovery and Crawler Policy

`llms.txt` gains a short machine-readable section linking to
`/agent/site.json` and `/agent/openapi.json`. Existing priority market, ward,
methodology, report, and news links remain intact.

`robots.txt` keeps the existing public allow policy and adds an explicit
`OAI-SearchBot` allow group so ChatGPT search discoverability is auditable. It
does not change the training policy for GPTBot or add a blanket bot block in
this scope. The sitemap declaration remains canonical.

The agent resources are discovery aids for non-Google agents and direct agent
access. They are not represented as a Google ranking mechanism. Google Search
continues to depend on crawlable, useful, people-first public pages, internal
links, semantic HTML, and accurate visible structured data.

## Browser-Agent Semantics

The implementation includes a narrow audit of the public signal journey, not a
visual redesign. The audit covers:

- filter controls have stable accessible names and associated labels;
- native buttons and links are used for actionable controls where practical;
- tab state and expanded/collapsed state are exposed semantically;
- the signal result region has a stable accessible name;
- loading, empty, error, and updated-result states are machine-observable;
- signal-card detail links have names that identify the associated card;
- decorative overlays do not hide the primary signal actions.

Only confirmed failures in this path are fixed. CSS appearance, filter
behavior, request sequencing, cancellation, pagination, and the
signals-first/counts-after invariant remain unchanged.

## Caching and Performance

- Agent discovery JSON is static for a deployed contract version and uses a
  short public cache such as `public, max-age=300, stale-while-revalidate=86400`.
- Discovery routes do not use PostgreSQL or Redis and do not prewarm the public
  signal cache.
- Agent signal requests use the existing anonymous Guest cache namespace and
  durable dataset versioning.
- The contract recommends `include_total=0`, `limit<=30`, bounded pagination,
  and no parallel retry storm.
- On `503`, the agent respects `Retry-After`; it does not switch to a private
  endpoint or broaden the query automatically.

## Security and Privacy

- The service builders use a literal allowlist of public GET operations.
- Tests fail if an operation is not `GET` or if a path contains a forbidden
  auth, admin, commerce, personal-data, or mutation segment.
- No cookies, API keys, bearer tokens, OAuth scheme, or session instructions
  appear in either resource.
- Runtime agent calls still pass through `current_tier()`, public cache
  classification, `_tier_safe_signal_payload()`, and `redact_for_tier()`.
- Existing Guest API tests remain the authority for embedded-phone masking and
  null original-source/contact fields.
- Agent resources do not include example secrets, real listing contacts, raw
  source URLs, production database values, or user-generated free text.
- Response headers retain the project's security policy. No CORS expansion is
  required for server-side agents.

## Error Handling

- Unknown or invalid filter values keep the current handler behavior: clamp,
  whitelist fallback, or an empty result as already implemented.
- Empty results are a valid response. The agent should suggest narrowing or
  changing explicit public filters, not invent a deal.
- A `503 temporarily_busy` response is documented with `Retry-After` and must
  remain uncached.
- Contract generation errors fail the discovery request; they do not fall back
  to exposing a broader route set.
- A mismatch between the documented contract and the actual public handler is
  a test failure and blocks release.

## Testing

Add focused tests in `tests/test_agent_readiness.py`:

1. Both agent routes return HTTP 200, UTF-8 JSON, the expected schema version,
   canonical production URLs, and the intended public cache header.
2. The OpenAPI document contains exactly the approved `GET` paths and no
   security scheme, mutation method, or forbidden route segment.
3. Every documented signal query parameter maps to a parameter accepted by the
   current public handler, including enum and numeric bounds.
4. The documented signal schema and examples contain no real phone, seller,
   original-source, cookie, token, or private memo value.
5. `llms.txt` links both agent resources without removing existing priority
   URLs or due-diligence language.
6. `robots.txt` explicitly permits `OAI-SearchBot`, retains the wildcard public
   allow rule, and keeps the canonical sitemap URL.
7. Anonymous `/api/signals` contract examples pass through the existing Guest
   redaction and cache-header tests.
8. Homepage/filter markup checks cover accessible names, form-label
   association, signal-region semantics, and named detail actions for any
   confirmed markup changes.
9. No agent route opens a DB connection; pure builder tests run without a
   database or runtime environment secrets.

Run the new test file plus the focused existing suites that protect public SEO,
Guest visibility, public cache headers, filter behavior, and public navigation.
Compile touched Python modules and run `git diff --check` before completion.

## Rollout and Verification

This is an additive application release with no schema migration, data
backfill, crawl, valuation reprocess, Redis change, or Cloudflare configuration
change.

After normal local verification and deployment, production smoke must prove:

- `/agent/site.json`, `/agent/openapi.json`, `/llms.txt`, and `/robots.txt`
  return 200 with the intended content types;
- both JSON documents parse and contain only approved public GET operations;
- an anonymous filtered `/api/signals?include_total=0&limit=3` request returns
  a tier-safe payload and dataset-version/cache evidence;
- an agent-generated filtered dashboard URL returns 200 and preserves the
  intended filter context;
- no source URL or phone is present in the checked Guest payload;
- browser-agent semantic checks pass on the rendered public signal journey.

HTTP 200 alone is not enough to call the release complete. Local tests, pushed
commit, deployed production revision, live resource content, Guest payload
redaction, and rendered browser behavior are separate evidence boundaries.

## Success Criteria

- A generic AI agent can discover the site manifest and read-only OpenAPI
  contract without executing JavaScript or logging in.
- The agent can construct a supported anonymous signal query, parse a compact
  response, compare safe signal fields, and return a reproducible Radar BDS URL
  to the user.
- The runtime signal data still comes exclusively from the existing public
  signal feed and its current signal-quality, cache, and redaction path.
- No write, auth, admin, seller-contact, original-source, or private-data
  capability is exposed.
- The main browser signal journey has no confirmed accessibility-tree blocker
  for reading filters, result state, cards, and detail actions.
- Existing public SEO URLs, canonicals, sitemap behavior, dashboard request
  sequencing, and human-facing funnel remain unchanged except for additive
  discovery links and verified semantic fixes.

## References

- OpenAI publisher and developer guidance:
  https://help.openai.com/en/articles/12627856
- Google Search guidance for generative AI features:
  https://developers.google.com/search/docs/fundamentals/ai-optimization-guide
- web.dev browser-agent guidance:
  https://web.dev/articles/ai-agent-site-ux
