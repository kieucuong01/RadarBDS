# Facebook Broker Removal and List UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let admins remove a Facebook broker from future crawl configuration without deleting crawled listings, while making the Brokers tab clearer and touch-friendly.

**Architecture:** Keep deletion inside the existing browser-side profile draft and continue saving the full draft through `POST /admin/api/facebook-crawl/profiles` with its revision token. Extend the dedicated Facebook Crawl module to render a destructive action, then improve the table/action CSS in the existing admin stylesheet; no server route, schema, or listing-table operation is added.

**Tech Stack:** Flask admin page, PostgreSQL-backed `facebook_crawl_profiles`, vanilla JavaScript, CSS, Node `assert`, pytest.

## Global Constraints

- Only an existing admin-authorized profile save may persist the change.
- Deletion removes only a `facebook_crawl_profiles` configuration entry; it must never call or add a listing/raw-listing deletion path.
- Confirmation copy explicitly states that already crawled listings remain intact.
- Preserve revision-conflict behavior, server normalization, filters, duplicate recommendations, and run-profile selection.
- Use DOM `textContent`/node creation; do not add unsafe `innerHTML` rendering.
- Preserve responsive behavior at narrow widths with controls at least 44px tall and visible keyboard focus.

---

### Task 1: Draft-only broker removal contract

**Files:**
- Modify: `static/js/admin/facebook-crawl.js:31-49,456-513`
- Modify: `tests/js/test_facebook_crawl_admin.js:12-92`

**Interfaces:**
- Consumes: `state.draft: Array<{url: string}>` and the selected canonical Facebook profile URL.
- Produces: `removeProfileFromDraft(draft: Array<object>, url: string): Array<object>`, exported from `RadarFacebookCrawlAdmin` for the module contract test.
- Consumed by later task: the Brokers-row `Xóa` event uses the helper before re-rendering dependent controls.

- [ ] **Step 1: Write the failing test**

```javascript
const draftForRemoval = [
  {url: 'https://www.facebook.com/broker-a', broker_name: 'A'},
  {url: 'https://www.facebook.com/broker-b', broker_name: 'B'},
];
const remaining = api.removeProfileFromDraft(
  draftForRemoval,
  'https://www.facebook.com/broker-a',
);
assert.deepEqual(remaining, [
  {url: 'https://www.facebook.com/broker-b', broker_name: 'B'},
]);
assert.deepEqual(draftForRemoval, [
  {url: 'https://www.facebook.com/broker-a', broker_name: 'A'},
  {url: 'https://www.facebook.com/broker-b', broker_name: 'B'},
]);
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node tests/js/test_facebook_crawl_admin.js`

Expected: FAIL because `api.removeProfileFromDraft` is not defined.

- [ ] **Step 3: Write minimal implementation**

```javascript
function removeProfileFromDraft(draft, url) {
  return (Array.isArray(draft) ? draft : []).filter((profile) => profile.url !== url);
}
```

Export the helper. In `renderProfiles`, add a `Xóa` button after `Chạy`; after
native confirmation, assign `state.draft = removeProfileFromDraft(state.draft,
profile.url)`, then call `renderProfiles()`, `renderRunProfiles()`, and
`syncDirty()`. The confirmation includes both the broker name and `Tin đã crawl
vẫn được giữ nguyên`.

- [ ] **Step 4: Run test to verify it passes**

Run: `node tests/js/test_facebook_crawl_admin.js`

Expected: PASS and prints `facebook crawl admin contracts: ok`.

- [ ] **Step 5: Commit**

Run: `git add static/js/admin/facebook-crawl.js tests/js/test_facebook_crawl_admin.js; git commit -m "feat: add safe Facebook broker removal"`

### Task 2: Broker-list hierarchy and responsive destructive action

**Files:**
- Modify: `static/js/admin/facebook-crawl.js:456-513`
- Modify: `static/css/admin.css` in the existing `.facebook-crawl-shell`, `.crawl-broker-table`, and mobile media-query rules.
- Modify: `tests/test_admin_growth_ui.py:181-210`

**Interfaces:**
- Consumes: existing `active`, `due_today`, `data_quality`, `daily_limit`, `crawl_every_days`, and `latest_crawled_at` profile fields.
- Produces: semantic status/action class names: `crawl-broker-identity`, `crawl-status-badge`, `crawl-broker-actions`, and `danger-btn`.
- Preserves: `Sửa`, `Chạy`, and `Xóa` remain real buttons with text labels.

- [ ] **Step 1: Write the failing style regression test**

```python
def test_facebook_broker_actions_have_explicit_safe_delete_and_responsive_styles():
    source = (ROOT / "static" / "js" / "admin" / "facebook-crawl.js").read_text(encoding="utf-8")
    css = (ROOT / "static" / "css" / "admin.css").read_text(encoding="utf-8")
    assert "Tin đã crawl vẫn được giữ nguyên" in source
    assert "crawl-broker-actions" in source
    assert ".crawl-broker-actions" in css
    assert ".danger-btn" in css
```

- [ ] **Step 2: Run test to verify it fails**

Run: `& $py -X utf8 -m pytest tests/test_admin_growth_ui.py -q`

Expected: FAIL because the safe-delete copy and action/style hooks are absent.

- [ ] **Step 3: Write minimal implementation**

Render broker identity as a name plus muted city sublabel, status/cadence/quality
as short textual badges, and the three actions in a `.crawl-broker-actions`
group. Add compact CSS using existing admin variables: blue focus ring, neutral
actions, spatially separate red `danger-btn`, 44px action height, and a narrow
layout that wraps actions without horizontal scrolling. Respect
`prefers-reduced-motion` for any opacity/transform transition.

- [ ] **Step 4: Run tests to verify they pass**

Run: `& $py -X utf8 -m pytest tests/test_admin_growth_ui.py -q; node tests/js/test_facebook_crawl_admin.js; node --check static/js/admin/facebook-crawl.js; git diff --check`

Expected: every command exits 0.

- [ ] **Step 5: Perform rendered verification**

Run the local Flask application and inspect `/admin/facebook-crawl?view=brokers`
at desktop and approximately 375px wide. Verify readable identity, visible
status text, keyboard focus, touch-sized actions, the delete confirmation,
draft-only removal, enabled save button, and that reloading without save
restores the profile.

- [ ] **Step 6: Commit**

Run: `git add static/js/admin/facebook-crawl.js static/css/admin.css tests/test_admin_growth_ui.py; git commit -m "style: clarify Facebook broker management"`

### Task 3: Focused API safety regression

**Files:**
- Modify: `tests/test_facebook_crawl_admin_api.py:302-374`
- Verify: `app.py:5632-5677`

**Interfaces:**
- Consumes: `POST /admin/api/facebook-crawl/profiles` with `profiles` and a 64-character `revision`.
- Produces: a regression assertion that a one-profile-removal submission uses the existing configuration writer, not listing-data code.

- [ ] **Step 1: Write the failing API test**

```python
submitted = [current[1]]
response = app_module.app.test_client().post(
    "/admin/api/facebook-crawl/profiles",
    json={"profiles": submitted, "revision": facebook_profile_revision(current)},
)
assert response.status_code == 200
assert saved_calls[0][0] == submitted
```

The fake writer returns the submitted profile collection; no fake or assertion
targets `raw_listings`, `listings`, or a delete route.

- [ ] **Step 2: Run test to verify it fails or exposes missing coverage**

Run: `& $py -X utf8 -m pytest tests/test_facebook_crawl_admin_api.py -q`

Expected: the new named removal case fails before it is wired to the existing
successful-save fixture, or exposes the missing one-profile branch.

- [ ] **Step 3: Add only test fixture/wiring required by the existing endpoint**

Keep `app.py` unchanged unless the test reveals a real contract gap. The endpoint
must still authenticate, lock the profile-config advisory key, compare revision,
normalize the submitted collection, clear crawl caches, and return the refreshed
profile payload.

- [ ] **Step 4: Run focused verification**

Run: `& $py -X utf8 -m pytest tests/test_facebook_crawl_admin_api.py tests/test_admin_growth_ui.py -q; node tests/js/test_facebook_crawl_admin.js; & $py -X utf8 -m py_compile app.py; node --check static/js/admin/facebook-crawl.js; git diff --check`

Expected: every command exits 0.

- [ ] **Step 5: Commit**

Run: `git add tests/test_facebook_crawl_admin_api.py; git commit -m "test: protect Facebook profile removal contract"`

## Plan self-review

- Spec coverage: Task 1 implements draft-only deletion and keeps run and duplicate
  surfaces synchronized. Task 2 covers hierarchy, destructive separation, focus,
  touch size, and responsive layout. Task 3 protects profile-only persistence.
- Placeholder scan: no placeholders or undefined follow-up behavior remain.
- Type consistency: every task uses `state.draft`, `profile.url`,
  `removeProfileFromDraft`, and the existing `profiles`/`revision` API shape.
