# Baseline Test Repair And Extraction-Valuation Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Windows local full pytest suite deterministic, then integrate and deploy the completed extraction-to-valuation hardening release.

**Architecture:** Keep the three baseline repairs isolated: refresh stale admin asset assertions, add pytest-only production public-URL isolation without changing `.env.local` runtime semantics, and resolve a usable TrueType font from explicit platform candidates. The release remains a normal `main` fast-forward deployment followed by the required production full reprocess and public smoke checks.

**Tech Stack:** Python 3.12, pytest, Pillow, Flask, PostgreSQL, PowerShell, Git, systemd/Nginx/Redis.

## Global Constraints

- Preserve `.env.local` as the local runtime override and never print secrets.
- Do not change production canonical URL behavior to satisfy tests.
- Keep the Linux DejaVu font as the first production candidate and use Windows Arial only as a local fallback.
- Rebase on current `origin/main`; never force-push.
- Run the production full reprocess because extraction and valuation behavior changed.
- Do not write AI review outcomes into `ai_training_feedback`.

---

### Task 1: Refresh Admin Asset Contract Assertions

**Files:**
- Modify: `tests/test_admin_growth_ui.py`

**Interfaces:**
- Consumes: current template cache key `admin-v51-facebook-broker-guland-publisher`
- Produces: tests that verify the actual CSS/JS release marker while retaining the focused Facebook module marker

- [ ] **Step 1: Verify the existing contract tests fail on the stale v50 marker**

Run: `python -X utf8 -m pytest tests/test_admin_growth_ui.py::test_growth_admin_ui_contract tests/test_admin_growth_ui.py::test_facebook_crawl_admin_is_task_first_and_loads_focused_module -q`

Expected: two assertion failures mentioning `admin-v50-facebook-broker-delete-ui`.

- [ ] **Step 2: Replace only the stale v50 assertions with the current v51 marker**

Keep the separate `admin-facebook-crawl-v2-broker-delete-ui` module assertion unchanged.

- [ ] **Step 3: Verify the two contract tests pass**

Run the Step 1 command again; expected: `2 passed`.

### Task 2: Isolate Public URL Configuration During Tests

**Files:**
- Create: `tests/conftest.py`

**Interfaces:**
- Consumes: `config.settings.PUBLIC_BASE_URL`, `DASHBOARD_BASE_URL`, and `SITE_OG_IMAGE`
- Produces: an autouse fixture that patches production public URL constants for every test while allowing each test's own monkeypatches to win

- [ ] **Step 1: Verify representative canonical and PayOS tests fail with the ignored local URL override**

Run: `python -X utf8 -m pytest tests/test_public_seo.py::test_public_seo_defaults_point_to_radarbds_domain tests/test_payos_client.py::test_create_link_uses_immutable_server_terms_and_official_request_type -q`

Expected: failures showing `http://127.0.0.1:5000` instead of `https://radarbds.vn`.

- [ ] **Step 2: Add the minimal autouse fixture**

At fixture setup, patch the three settings constants, then patch already-imported `app` and `services.payos_client` module constants when present. Do not import either application module merely to patch it.

- [ ] **Step 3: Verify URL, PayOS, and SEO tests pass**

Run: `python -X utf8 -m pytest tests/test_public_seo.py tests/test_payos_client.py tests/test_traffic_seo_aio.py tests/test_thu_dau_mot_map_product_page.py -q`

If the report-hub contract still targets the June report after a published July master report exists, update only that hub assertion to `/bao-cao/bds-binh-duong-thang-07-2026`; retain the June landing-page assertion until its curated link changes in application data.

### Task 3: Resolve Social Visual Fonts Cross-Platform

**Files:**
- Modify: `scripts/radar_social_queue.py`
- Test: `tests/test_radar_social_queue.py`

**Interfaces:**
- Consumes: Linux DejaVu paths and Windows `%WINDIR%/Fonts/arial*.ttf`
- Produces: `_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont`

- [ ] **Step 1: Verify the existing visual tests fail on Windows**

Run: `python -X utf8 -m pytest tests/test_radar_social_queue.py -q`

Expected: visual tests fail with Pillow `OSError: cannot open resource` for `/usr/share/fonts/...`.

- [ ] **Step 2: Add ordered existing-file font candidates**

Keep DejaVu first. Use Windows Arial regular/bold as fallback and raise one explicit runtime error listing only safe candidate paths if no supported font exists.

- [ ] **Step 3: Verify the social queue suite passes**

Run the Step 1 command again; expected: all tests pass and generated assets exist under pytest temporary directories.

### Task 4: Full Verification, Integration, And Production Release

**Files:**
- Modify only if verification exposes a branch-caused regression.

**Interfaces:**
- Consumes: green baseline repair suites and the existing extraction-integrity report command
- Produces: rebased `main`, deployed production SHA, completed production reprocess, and public health evidence

- [ ] **Step 1: Run focused extraction/valuation and downstream suites**

Run the documented integrity gate and downstream public-feed/cache tests.

- [ ] **Step 2: Run full pytest and `git diff --check`**

Run: `python -X utf8 -m pytest tests -q --disable-warnings`

Expected: zero failures.

- [ ] **Step 3: Commit baseline repairs, fetch, and rebase on `origin/main`**

Resolve only scoped conflicts, then rerun the focused and full verification gates.

- [ ] **Step 4: Fast-forward local `main`, push `origin/main`, and deploy**

Use `scripts/deploy_production.ps1`; do not force-push.

- [ ] **Step 5: Run the required production full reprocess**

Load `/etc/radar-bds/radar.env` on the VPS and run `radar.py reprocess --full` from `/opt/radar-bds/current`.

- [ ] **Step 6: Verify production**

Confirm deployed SHA, active service, schema/integrity command output, public HTTP 200s, and `scripts/verify_public_cache.ps1 -RequireCdn`.
