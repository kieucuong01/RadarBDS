# Facebook Broker Compact Roster Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add STT and area columns, link broker names safely to Facebook, and compact desktop roster rows.

**Architecture:** Keep the existing roster view model and API. Extend the Jinja headers and DOM renderer; use CSS for desktop density while retaining the mobile card behavior.

**Tech Stack:** Flask/Jinja, vanilla JavaScript, CSS, Node test runner, pytest.

## Global Constraints

- Keep `.playwright-cli/` untracked and unstaged.
- Do not change APIs, filters, draft-save flow, delete confirmation, or drawer behavior.
- Only `safeFacebookProfileLink()` may authorize an external broker-name link.
- Preserve keyboard focus, reduced motion, and 44px mobile actions.

---

### Task 1: Add red compact-roster contracts

**Files:**

- Modify: `tests/js/test_facebook_crawl_admin.js`
- Modify: `tests/test_admin_growth_ui.py`

- [ ] Add assertions for headers `STT`/`Khu vực`, renderer cells
  `crawl-broker-ordinal`/`crawl-broker-area`, safe name-link behavior, nine
  system-row columns, and compact CSS selectors.
- [ ] Run `node --test tests/js/test_facebook_crawl_admin.js` and focused
  `pytest` to prove these contracts fail before source changes.

### Task 2: Render the compact semantic table

**Files:**

- Modify: `templates/admin_control_room.html`
- Modify: `static/js/admin/facebook-crawl.js`

- [ ] Add the first and third headers: `<th scope="col">STT</th>` and
  `<th scope="col">Khu vực</th>`.
- [ ] Enumerate `filteredProfiles`, render one-based ordinal and area cells,
  turn only validated broker names into safe external links, and set empty
  system rows to `colSpan = 9`.

### Task 3: Compact desktop density and retain mobile usability

**Files:**

- Modify: `static/css/admin.css`

- [ ] Set fixed desktop column widths, 8px vertical cell padding, compact
  badges/action buttons, and one-line text truncation.
- [ ] Remove only secondary desktop sublines from visual flow; preserve values
  in DOM/drawer and keep mobile card labels, column ordering, and 44px actions.

### Task 4: Verify and release

**Files:**

- Verify: `static/js/admin/facebook-crawl.js`, focused JS/Python tests.

- [ ] Run JS syntax, broker admin contract, focused UI/API pytest, and
  `git diff --check`.
- [ ] Commit only spec, plan, roster source/CSS, and focused tests; push `main`,
  deploy with `scripts/deploy_production.ps1`, and verify SHA/service/public
  smoke.
