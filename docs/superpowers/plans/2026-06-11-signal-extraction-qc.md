# Signal Extraction QC Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sync production DB to local, audit current actionable signal listings for extraction mismatches, expose those cases in admin Data Quality, and harden parser behavior with regression tests.

**Architecture:** Add a pure `services/extraction_audit.py` module that scores listing rows against textual evidence without writing human labels. Reuse that module from a read-only audit script and the admin Data Quality queue, while parser fixes stay in `cleansing/feature_extractor.py` / `cleansing/normalizer.py` with targeted tests.

**Tech Stack:** Flask, PostgreSQL, existing `db.connection` wrapper, existing admin control-room HTML/CSS/JS, pytest.

---

### Task 1: Baseline Signal Audit

**Files:**
- Create: `services/extraction_audit.py`
- Create: `scripts/audit_signal_extraction.py`
- Test: `tests/test_extraction_audit.py`

- [ ] Write failing unit tests in `tests/test_extraction_audit.py` for price, area/dimension, ward, road, property type, and thổ cư evidence mismatch objects.
- [ ] Run `.\.venv312\Scripts\python.exe -X utf8 -m pytest tests\test_extraction_audit.py -q` and confirm it fails because `services.extraction_audit` is missing.
- [ ] Implement `services/extraction_audit.py` with `audit_listing_extraction(listing)` returning `{"findings": [...], "score": int, "fields": [...]}`.
- [ ] Run the new unit test and confirm it passes.
- [ ] Implement `scripts/audit_signal_extraction.py` to query current actionable signals with `LATEST_VALUATION_CTE`, run the audit module, and write a JSON report under `.local/extraction-audit/`.
- [ ] Run the audit script against the synced local DB and save the baseline counts.

### Task 2: Admin Extraction QC Queue

**Files:**
- Modify: `app.py`
- Modify: `templates/admin_control_room.html`
- Modify: `static/js/admin.js`
- Modify: `static/css/admin.css`
- Test: `tests/test_admin_control_room.py`

- [ ] Write failing tests proving `/admin/api/data-quality/items?queue=extraction_qc` is accepted and returns audited findings for a seeded signal row.
- [ ] Write failing tests proving the admin Data Quality shell contains `data-quality-tab="extraction_qc"` and JS maps it to `qualityExtractionQcGrid`.
- [ ] Extend `admin_api_data_quality_items()` allowed queues with `extraction_qc`.
- [ ] Filter the fetched data-quality rows through `audit_listing_extraction()` for that queue, attach `extraction_audit`, and keep only rows with findings.
- [ ] Add the Data Quality tab markup and grid.
- [ ] Update admin JS queue root mapping and card rendering to display the audit findings, original extracted fields, and original listing link.
- [ ] Add minimal CSS for audit badges/findings using existing quality card patterns.
- [ ] Run the admin control-room tests and JS syntax check.

### Task 3: Parser Fixes With Regression Tests

**Files:**
- Modify: `cleansing/feature_extractor.py`
- Modify: `cleansing/normalizer.py` only if needed for source/ward context.
- Modify: `tests/test_feature_extractor.py`

- [ ] From the baseline audit, choose high-confidence repeated error classes only.
- [ ] For each error class, add one or more failing regression tests using the exact listing text.
- [ ] Run `.\.venv312\Scripts\python.exe -X utf8 -m pytest tests\test_feature_extractor.py -q` and confirm the new tests fail for the intended behavior.
- [ ] Implement the minimal parser fix for that class.
- [ ] Re-run `tests\test_feature_extractor.py` and ensure existing correct cases still pass.
- [ ] Run `scripts/audit_signal_extraction.py` again and compare baseline vs after-fix findings.

### Task 4: Verification And Report

**Files:**
- No code files unless verification finds a blocker.

- [ ] Run `.\.venv312\Scripts\python.exe -X utf8 -m py_compile app.py services\extraction_audit.py cleansing\feature_extractor.py cleansing\normalizer.py`.
- [ ] Run `node --check static\js\admin.js`.
- [ ] Run focused pytest: `tests\test_extraction_audit.py`, `tests\test_admin_control_room.py`, `tests\test_feature_extractor.py`.
- [ ] Run the audit script one final time and record before/after counts plus representative listing IDs and root causes.
- [ ] Report DB sync result, mismatched listings, UI path, parser changes, tests run, and remaining risk.
