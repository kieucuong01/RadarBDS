# P1 Marketing Source Funnel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the existing admin growth dashboard with a truthful, bounded, PII-free view of marketing channels, landing pages, campaigns, CTA targets, directly attributable lead submissions, and explicit attribution gaps.

**Architecture:** Centralize marketing-event context validation in a focused sanitizer, attach sanitized acquisition data to canonical page-view events, aggregate first-party audit events and lead rows inside the existing admin growth database scope, and render compact tables in the current growth panel. Preserve compatibility events while refusing inferred cross-session journeys.

**Tech Stack:** Python 3.12, Flask, PostgreSQL 17, server-rendered Jinja, vanilla JavaScript, CSS, pytest

## Global Constraints

- This plan starts only after the P0 quality gate is green.
- Event totals are events, not unique users; the UI must say so.
- A lead is attributable only when `lead_captures.listing_url`, `lead_captures.source_context`, or a `lead_capture_submit` event directly carries the landing/campaign value.
- Never join anonymous events by IP, user-agent, timestamp proximity, fingerprint, phone, email, or free-form note.
- The response must not expose raw audit context, IP, user-agent, phone, email, listing source URL, or lead note.
- Existing `social_utm_visit` and `ai_referral_visit` events stay enabled for backward compatibility.
- Historical canonical views without `channel` are `legacy_unknown`; they are not relabeled from nearby compatibility events.
- All event queries use the selected current-plus-previous period window and existing `user_audit_log(action, created_at)` index.
- All returned lists are deterministically sorted and capped.
- No new public endpoint, analytics vendor, cookie, production credential, or database migration is added.

---

## File Structure

- Create `services/marketing_tracking.py`: stable action set, enums, internal-path normalization, destination classification, and PII-free context sanitizer.
- Create `tests/test_marketing_tracking.py`: unit and endpoint sanitizer contracts.
- Modify `app.py`: delegate the selected tracking actions to the sanitizer before audit logging.
- Modify `templates/partials/seo_tracking.html`: compute acquisition metadata once and attach it to the canonical page-view event.
- Modify `templates/seo_landing.html`: apply the same canonical-view contract to the legacy inline landing tracker.
- Modify `tests/test_traffic_seo_aio.py` and `tests/test_public_seo.py`: tracking compatibility and canonical acquisition assertions.
- Create `services/admin_marketing.py`: bounded aggregation over audit events and directly attributable leads.
- Create `tests/test_admin_marketing.py`: aggregation, malformed legacy JSON, direct-attribution, boundedness, and safe-output tests.
- Modify `services/admin_growth.py`: call the marketing aggregator inside the existing connection/time bounds and expose `marketing`.
- Modify `tests/test_admin_growth.py`: endpoint, authentication/cache, and response integration assertions.
- Modify `templates/admin_control_room.html`, `static/js/admin.js`, and `static/css/admin.css`: compact marketing source cards/tables and coverage states.
- Modify `tests/test_admin_growth_ui.py`: template, script, accessibility, and responsive UI contract.
- Modify `docs/growth_marketing_workflow.md`: metric definitions and attribution limits.

### Task 1: Define and enforce the marketing tracking contract

**Files:**
- Create: `services/marketing_tracking.py`
- Create: `tests/test_marketing_tracking.py`
- Modify: `app.py:1437-1665`

**Interfaces:**
- Produces: `MARKETING_TRACK_ACTIONS: frozenset[str]`.
- Produces: `sanitize_marketing_context(action: str, context: object) -> dict[str, object]`.
- Consumes: `seo_landing_viewed`, `report_viewed`, `social_utm_visit`, `ai_referral_visit`, `cta_clicked`, and `lead_capture_submit` contexts.
- Guarantees: output contains only stable, bounded analytics fields and never echoes unknown keys.

- [ ] **Step 1: Write failing sanitizer unit tests**

Cover allowlists, enums, truncation, external URLs, malformed input, and explicit PII rejection:

```python
def test_marketing_context_keeps_only_safe_bounded_fields():
    safe = sanitize_marketing_context("seo_landing_viewed", {
        "path": "/binh-duong/phuong-hiep-thanh?x=1",
        "page_slug": "binh-duong/phuong-hiep-thanh",
        "page_title": "private@example.test 0900000000",
        "channel": "social",
        "utm_source": "facebook",
        "utm_campaign": "ward_launch",
        "phone": "0900000000",
        "email": "private@example.test",
        "referrer": "https://external.test/private",
    })
    assert safe["path"] == "/binh-duong/phuong-hiep-thanh"
    assert "page_title" not in safe
    assert safe["channel"] == "social"
    assert "phone" not in safe
    assert "email" not in safe
    assert "referrer" not in safe

def test_cta_destination_is_internal_path_or_stable_class():
    assert sanitize_marketing_context("cta_clicked", {
        "destination": "/?tab=signals&utm_source=facebook",
    })["destination"] == "/"
    assert sanitize_marketing_context("cta_clicked", {
        "destination": "https://zalo.me/0900000000",
    })["destination"] == "external:zalo"
```

Also assert non-dict input returns `{}`, unknown actions return `{}`, invalid channels/AI sources are dropped, all string bounds are enforced, and protocol-relative or control-character paths are rejected.

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `& $py -X utf8 -m pytest tests\test_marketing_tracking.py -q`

Expected: import failure because the module does not exist.

- [ ] **Step 3: Implement the sanitizer as a pure module**

Use explicit constants:

```python
MARKETING_TRACK_ACTIONS = frozenset({
    "seo_landing_viewed", "report_viewed", "social_utm_visit",
    "ai_referral_visit", "cta_clicked", "lead_capture_submit",
})
CHANNELS = frozenset({"organic", "social", "ai", "direct_unknown"})
AI_SOURCES = frozenset({"chatgpt", "gemini", "perplexity", "copilot"})
```

Normalize `path`, `page_path`, and internal CTA destinations with `urllib.parse.urlsplit`; keep only an absolute internal path, strip query/fragment, require it to start with one `/`, and cap at 180 characters. Map recognized external hosts to non-identifying classes such as `external:zalo`, `external:facebook`, `external:telegram`, and otherwise `external:other`. Normalize UTM and CTA tokens to lowercase bounded text with a conservative character allowlist; reject phone-like and IP-address values, omit client-supplied page titles entirely, and cap slug/path at 180, UTM/CTA/source fields at 80, and destination at 180.

- [ ] **Step 4: Wire the sanitizer into `/api/track`**

Import `MARKETING_TRACK_ACTIONS` and `sanitize_marketing_context` in `app.py`. In `api_track()`, place this branch before the generic fallback:

```python
elif action in MARKETING_TRACK_ACTIONS:
    ctx = sanitize_marketing_context(action, ctx)
```

Do not change product, checkout, listing-map, listing-share, or `public_*` sanitizers.

- [ ] **Step 5: Add endpoint tests proving safe audit writes**

Patch `log_audit`, post a malicious marketing context, and assert the captured context includes allowed fields but excludes `phone`, `email`, `ip`, `user_agent`, `note`, `referrer`, and unknown keys. Assert the endpoint remains `200 {"ok": true}` for malformed context and rejects an unknown action with `400`.

- [ ] **Step 6: Run focused tests and commit**

```powershell
& $py -X utf8 -m pytest tests\test_marketing_tracking.py tests\test_traffic_seo_aio.py -q
git add services/marketing_tracking.py app.py tests/test_marketing_tracking.py
git commit -m "feat: sanitize first-party marketing events"
```

### Task 2: Attach acquisition fields to canonical page-view events

**Files:**
- Modify: `templates/partials/seo_tracking.html`
- Modify: `templates/seo_landing.html:690-782`
- Modify: `tests/test_traffic_seo_aio.py`
- Modify: `tests/test_public_seo.py`

**Interfaces:**
- Consumes: query-string UTM fields and a hostname-only AI referrer classification.
- Produces: canonical `seo_landing_viewed` or `report_viewed` context with `channel` and sanitized acquisition fields.
- Preserves: `social_utm_visit` and `ai_referral_visit` compatibility events.

- [ ] **Step 1: Write failing template-contract tests**

Assert both tracking implementations define one acquisition object before sending the canonical page view:

```python
for template_name in ("partials/seo_tracking.html", "seo_landing.html"):
    text = (ROOT / "templates" / template_name).read_text(encoding="utf-8")
    assert "const acquisitionContext" in text
    assert "channel:" in text
    assert "utm_content" in text
    assert "Object.assign({}, acquisitionContext" in text
    view_call = "sendRadarEvent(viewEvent" if "const viewEvent" in text else "sendRadarEvent(canonicalViewEvent"
    assert text.index("const acquisitionContext") < text.index(view_call)
```

Retain the existing assertions that full referrer URLs are never sent.

- [ ] **Step 2: Run the template tests and verify RED**

Run: `& $py -X utf8 -m pytest tests\test_traffic_seo_aio.py tests\test_public_seo.py -q`

- [ ] **Step 3: Compute a deterministic acquisition context**

In each template, derive exactly one channel using this precedence:

1. recognized AI UTM/referrer -> `ai` plus `ai_source` and hostname only;
2. recognized social source/medium -> `social`;
3. UTM medium `organic` or recognized search-engine hostname -> `organic`;
4. otherwise -> `direct_unknown`.

Attach bounded raw UTM values to the object; backend sanitizer remains authoritative. Send compatibility events as today, then send the canonical view with:

```javascript
sendRadarEvent(viewEvent, Object.assign({}, acquisitionContext));
```

For the legacy inline template, compute `canonicalViewEvent` and call the same shape. Never send `document.referrer`; only a recognized `referrer_host` for AI compatibility.

- [ ] **Step 4: Verify rendered HTML and compatibility**

Run the two focused test modules and render one ward page plus one report page with Flask test client. Assert canonical tracking, social compatibility, AI compatibility, and CTA tracking strings are all present.

- [ ] **Step 5: Commit canonical page-view tracking**

```powershell
git add templates/partials/seo_tracking.html templates/seo_landing.html tests/test_traffic_seo_aio.py tests/test_public_seo.py
git commit -m "feat: attach acquisition data to landing views"
```

### Task 3: Build bounded marketing aggregation

**Files:**
- Create: `services/admin_marketing.py`
- Create: `tests/test_admin_marketing.py`

**Interfaces:**
- Produces: `build_marketing_source_view(conn, *, start: datetime, end: datetime, previous: datetime, limit: int = 20) -> dict[str, object]`.
- Consumes: selected `user_audit_log` actions and `lead_captures` rows within `[previous, end)`.
- Returns: `coverage`, `channels`, `landing_pages`, `campaigns`, `cta_targets`, and `unattributed`.

- [ ] **Step 1: Write failing pure aggregation tests using fixture rows**

Seed canonical page views for all channels, compatibility events, CTA events, a valid `lead_capture_submit`, malformed JSON, legacy JSON without channel, and lead rows with and without direct URL attribution. Verify:

```python
view = build_marketing_source_view(conn, start=start, end=end, previous=previous)
assert [row["channel"] for row in view["channels"]] == [
    "organic", "social", "ai", "direct_unknown", "legacy_unknown"
]
assert view["coverage"]["event_count"] == expected_views
assert view["coverage"]["with_stable_channel"] == expected_stable
assert view["coverage"]["without_stable_channel"] == expected_legacy
assert view["unattributed"]["lead_rows"] == expected_unattributed
```

Assert `lead_capture_submit` is counted as a directly attributable lead event only when it contains a normalized `page_path` or campaign fields. Keep lead-row counts and lead-event counts separate so the same human action is not claimed as a unique lead.

- [ ] **Step 2: Run the aggregation tests and verify RED**

Run: `& $py -X utf8 -m pytest tests\test_admin_marketing.py -q`

- [ ] **Step 3: Implement safe row parsing and normalizers**

Use small pure helpers:

```python
def _safe_context(value: object) -> dict[str, object]:
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}

def _campaign_key(context: dict[str, object]) -> tuple[str, str, str] | None: ...
def _lead_url_attribution(value: object) -> dict[str, str]: ...
```

Pass parsed contexts back through `sanitize_marketing_context()` before aggregation. Parse lead URLs without returning host, credentials, query strings, or fragments. Only accept site-relative paths or configured public hostnames; extract allowed UTM values through the same sanitizer.

- [ ] **Step 4: Implement bounded SQL and deterministic result shapes**

Use one audit query and one lead query, both bounded by `[previous, end)`. The audit query selects only `action`, `context`, and `created_at`; the lead query selects only `created_at`, `listing_url`, `source_context`, and `status`. Cap fetched audit rows at `20_000` and lead rows at `5_000`; expose `coverage.truncated` when either cap is reached.

Aggregate:

- channels in the fixed order `organic`, `social`, `ai`, `direct_unknown`, `legacy_unknown`, each with current/previous view counts;
- landing pages sorted by current views descending then path, cap `limit`;
- campaigns sorted by current views, then CTA clicks, then the key tuple, cap `limit`;
- CTA targets sorted by click count descending then name/destination, cap `limit`;
- direct lead event counts and direct lead-row counts as separate numeric fields;
- lead status counts only from directly attributed `lead_captures` rows;
- explicit unattributed current/previous counts for both lead events and lead rows.

`coverage.first_event_at` and `last_event_at` are safe ISO timestamps or `None`. Do not return event IDs, user IDs, listing IDs, raw contexts, raw URLs, or row samples.

- [ ] **Step 5: Add safety, malformed JSON, and cap tests**

Walk the serialized response and assert seeded phone/email/IP/user-agent/raw URL strings are absent. Seed more than the requested display limit and assert deterministic caps. Seed malformed JSON, an external credential-bearing URL, and non-dict JSON and assert the aggregator returns a valid response with those inputs unattributed.

- [ ] **Step 6: Run focused tests and commit**

```powershell
& $py -X utf8 -m pytest tests\test_admin_marketing.py tests\test_marketing_tracking.py -q
git add services/admin_marketing.py tests/test_admin_marketing.py
git commit -m "feat: aggregate bounded marketing source metrics"
```

### Task 4: Integrate marketing metrics into the admin growth endpoint

**Files:**
- Modify: `services/admin_growth.py:134-320`
- Modify: `tests/test_admin_growth.py`
- Modify: `tests/test_admin_growth_ui.py`

**Interfaces:**
- Extends: `get_growth_dashboard(period, anchor, include_guland=False)` response with `marketing`.
- Reuses: the existing database connection plus `start`, `end`, and `previous` bounds.
- Preserves: existing admin authentication and `_cached_admin_read_payload("growth", ...)` behavior.

- [ ] **Step 1: Add failing endpoint integration tests**

Seed one sanitized view, CTA, lead submission, and attributed lead row in the fixture window. Assert `/admin/api/growth` includes the marketing object and current counts. Add tests that unauthenticated and non-admin clients cannot access the object, an invalid period remains `400`, and a malformed legacy context still returns `200`.

Add a source contract asserting `build_marketing_source_view(conn, ...)` is called inside the existing `with db_mod.get_conn() as conn:` block, rather than opening a second connection.

- [ ] **Step 2: Run integration tests and verify RED**

Run: `& $py -X utf8 -m pytest tests\test_admin_growth.py tests\test_admin_growth_ui.py -q`

- [ ] **Step 3: Call the aggregator in the current database scope**

Import `build_marketing_source_view`. Immediately before leaving the current connection scope, call:

```python
marketing = build_marketing_source_view(
    conn,
    start=start,
    end=end,
    previous=previous,
)
```

Return it under `"marketing"`. Do not condition marketing metrics on the Facebook/Guland listing-source toggle; acquisition channels are a separate dimension. Do not change existing summary/ratio/series semantics.

- [ ] **Step 4: Verify cache and bounded-query contracts**

Retain the existing admin growth cache key dimensions (`period`, `anchor`, `include_guland`). Assert marketing SQL contains both lower and upper time bounds and does not select `ip`, `user_agent`, `zalo_phone`, `guest_email`, or `note`.

- [ ] **Step 5: Run focused tests and commit**

```powershell
& $py -X utf8 -m pytest tests\test_admin_growth.py tests\test_admin_marketing.py tests\test_admin_growth_ui.py -q
git add services/admin_growth.py tests/test_admin_growth.py tests/test_admin_growth_ui.py
git commit -m "feat: expose marketing metrics in admin growth"
```

### Task 5: Render the compact marketing-source section

**Files:**
- Modify: `templates/admin_control_room.html:904-932`
- Modify: `static/js/admin.js:2658-2703`
- Modify: `static/css/admin.css:3265-3305`
- Modify: `tests/test_admin_growth_ui.py`

**Interfaces:**
- Consumes: `data.marketing` from the existing growth request.
- Produces: channel cards, landing/campaign/CTA tables, a coverage note, an unattributed count, and empty/partial states.
- Preserves: the four current charts and bucket table.

- [ ] **Step 1: Write failing UI contract tests**

Require stable element IDs:

```python
for marker in (
    'id="growthMarketing"', 'id="growthMarketingChannels"',
    'id="growthMarketingCoverage"', 'id="growthLandingTableBody"',
    'id="growthCampaignTableBody"', 'id="growthCtaTableBody"',
    'id="growthMarketingEmpty"',
):
    assert marker in template
assert "function renderGrowthMarketing" in script
assert "directly_attributed" in script
assert ".growth-marketing-grid" in styles
```

Assert table headings say “Lead gán trực tiếp”, the coverage note says counts are events rather than people, and no export control is added.

- [ ] **Step 2: Run UI tests and verify RED**

Run: `& $py -X utf8 -m pytest tests\test_admin_growth_ui.py -q`

- [ ] **Step 3: Add semantic markup and empty states**

Place the marketing section after growth ratios and before the existing charts. Use semantic headings, caption/summary text, `aria-live="polite"` on the coverage note, and horizontally scrollable table wrappers. Include one section-level empty state and a partial-coverage note when `without_stable_channel > 0` or `coverage.truncated` is true.

- [ ] **Step 4: Implement defensive rendering**

Add `renderGrowthMarketing(marketing)` and call it from `renderGrowth(data)`. Treat missing arrays/objects as empty. Render all strings through existing `esc()`, all numbers through `growthFmt()`, and do not create HTML from raw server fragments. Display channel labels from a local fixed mapping. Show attributed lead events and lead rows separately in explanatory text; do not calculate visitor conversion percentages.

- [ ] **Step 5: Add responsive styles**

Use the existing surface/table tokens. Channel cards use five columns on wide screens, two columns under 1000px, and one column under 600px. Keep 44px touch targets where interactive elements exist and respect the existing reduced-motion behavior.

- [ ] **Step 6: Run UI and backend tests, then commit**

```powershell
& $py -X utf8 -m pytest tests\test_admin_growth_ui.py tests\test_admin_growth.py tests\test_admin_marketing.py -q
git add templates/admin_control_room.html static/js/admin.js static/css/admin.css tests/test_admin_growth_ui.py
git commit -m "feat: show truthful marketing funnel in admin"
```

### Task 6: Document definitions and run the P1 marketing gate

**Files:**
- Modify: `docs/growth_marketing_workflow.md`
- Modify: `tests/test_admin_growth_ui.py`

**Interfaces:**
- Documents: event vs user semantics, channel precedence, direct attribution, legacy coverage, caps, and troubleshooting.
- Produces: locally verified marketing workstream with no production writes.

- [ ] **Step 1: Add a failing documentation contract**

Assert the workflow document contains `legacy_unknown`, `directly attributed`, `event counts`, `unattributed`, and the rule prohibiting IP/user-agent/time-proximity joins.

- [ ] **Step 2: Update the workflow documentation**

Document the response fields, channel precedence, display caps, current/previous period behavior, malformed-context behavior, and why lead events and lead rows are separate. Include one safe diagnostic command using the admin endpoint only in local/test context; do not add a public analytics endpoint.

- [ ] **Step 3: Run the complete marketing regression set**

```powershell
& $py -X utf8 -m pytest tests\test_marketing_tracking.py tests\test_admin_marketing.py tests\test_admin_growth.py tests\test_admin_growth_ui.py tests\test_traffic_seo_aio.py tests\test_public_seo.py -q
node --check static\js\admin.js
git diff --check
```

Expected: all commands exit `0`; serialized fixture responses contain none of the seeded PII values.

- [ ] **Step 4: Commit documentation**

```powershell
git add docs/growth_marketing_workflow.md tests/test_admin_growth_ui.py
git commit -m "docs: define marketing attribution boundaries"
```
