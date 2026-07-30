# Facebook Profiles DB Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Store Facebook broker crawl profile configuration in PostgreSQL instead of `data/facebook_profiles.json`.

**Architecture:** Add an idempotent `facebook_crawl_profiles` table and a small DB repository that normalizes, versions, and returns profiles in the existing config shape. Admin APIs write to DB and no longer persist profile edits to the runtime JSON file; crawler loading reads DB only by default. JSON paths are allowed only for explicit legacy fixtures/imports, never as automatic runtime fallback.

**Tech Stack:** Flask, PostgreSQL via `db.connection.get_conn`, psycopg-compatible sqlite test adapter, pytest, Node syntax checks.

## Global Constraints

- Preserve existing production profile data by importing from `data/facebook_profiles.json` into DB before the DB-only deploy, then delete the JSON from repo/production checkout.
- Do not print or commit secrets.
- Keep admin authorization unchanged.
- Use parameterized SQL only.
- Do not keep `data/facebook_profiles.json` as a runtime fallback.
- Preserve unrelated dirty work and production runtime files.

---

### Task 1: DB Repository and Migration

**Files:**
- Create: `db/facebook_profiles.py`
- Modify: `db/schema.py`
- Test: `tests/test_facebook_profiles_db.py`

**Interfaces:**
- Produces: `db.facebook_profiles.read_profile_config() -> dict`
- Produces: `db.facebook_profiles.write_profile_config(config: dict, *, updated_by: str = "") -> dict`
- [ ] Write failing tests proving schema creates `facebook_crawl_profiles` and preserves profile fields.
- [ ] Run `pytest tests/test_facebook_profiles_db.py` and confirm failure because repository/table does not exist.
- [ ] Implement the table, repository read/write helpers, URL normalization, and idempotent migration.
- [ ] Run `pytest tests/test_facebook_profiles_db.py` and confirm pass.

### Task 2: Admin API Uses DB

**Files:**
- Modify: `services/admin_quality.py`
- Modify: `app.py`
- Test: `tests/test_facebook_crawl_admin_api.py`

**Interfaces:**
- Consumes: `read_profile_config`, `write_profile_config`
- Existing API shape stays compatible: `/admin/api/facebook-crawl/config`, `/overview`, `/profiles`, `/duplicates`

- [ ] Write failing tests proving admin config save updates DB and does not touch `data/facebook_profiles.json`.
- [ ] Run the focused admin API test and confirm failure.
- [ ] Replace profile config read/write path with DB-backed helpers without JSON fallback.
- [ ] Run the focused admin API test and confirm pass.

### Task 3: Crawler Uses DB Source

**Files:**
- Modify: `crawler/facebook_apify.py`
- Test: `tests/test_facebook_profiles_db.py`

**Interfaces:**
- Consumes: DB-backed read helper and returns the same active profile list used by the crawler today.

- [ ] Write failing test proving `load_profiles()` sees DB profiles when JSON is absent and fails closed when DB is unavailable.
- [ ] Run the focused test and confirm failure.
- [ ] Update crawler profile loading to read DB only by default.
- [ ] Run focused test and confirm pass.

### Task 4: Deploy Verification

**Files:**
- Modify if needed: `scripts/deploy_production.ps1`

- [ ] Ensure production deploy can initialize/import profile schema without relying on dirty JSON writes.
- [ ] Run `py_compile`, focused pytest, Node checks, and `git diff --check`.
- [ ] Commit the scoped change.
