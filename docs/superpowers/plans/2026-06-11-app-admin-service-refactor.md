# App Admin Service Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move high-risk admin/QC/leads/users logic out of `app.py` into focused service modules while preserving existing routes and API responses.

**Architecture:** Keep Flask route functions in `app.py` as request/response adapters for now. Move DB-heavy and formatting-heavy logic into `services.admin_quality`, `services.admin_leads`, and `services.admin_users`, with tiny compatibility wrappers left in `app.py` only where existing tests or routes patch those symbols.

**Tech Stack:** Flask, PostgreSQL via `db.connection` / `config.database_sqlite`, pytest characterization tests.

---

### Task 1: Admin Quality Service

**Files:**
- Create: `services/admin_quality.py`
- Modify: `app.py`
- Test: `tests/test_admin_control_room.py`

- [x] Move image summary, crawl ops summary, Apify pool summary, and data-quality summary helpers from `app.py` into `services.admin_quality`.
- [x] Keep patchable wrappers in `app.py` for `_facebook_crawl_summary`, `_data_quality_summary`, `_apify_tokens_public`, `_daily_crawl_schedule_status`, and `_active_radar_lock_blockers`.
- [x] Run:

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $py -X utf8 -m pytest tests\test_admin_control_room.py::AdminControlRoomGateTest::test_admin_crawl_config_includes_ops_summary tests\test_admin_control_room.py::AdminControlRoomGateTest::test_admin_data_quality_summary_includes_images_tokens_errors_and_suppressed_signals -q
```

### Task 2: Leads Service

**Files:**
- Create: `services/admin_leads.py`
- Modify: `app.py`
- Test: `tests/test_admin_control_room.py`

- [x] Move lead ack helpers, lead creation, listing validation, lead listing/export/status/delete operations into `services.admin_leads`.
- [x] Keep Flask route functions in `app.py` responsible for JSON/CSV `Response` objects and audit logging where needed.
- [x] Run:

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $py -X utf8 -m pytest tests\test_admin_control_room.py -q
```

### Task 3: Users Service

**Files:**
- Create: `services/admin_users.py`
- Modify: `app.py`
- Test: `tests/test_admin_control_room.py`

- [x] Move admin user row shaping, list summary, delete, grant/revoke VIP, and ban operations into `services.admin_users`.
- [x] Inject effective-tier and audit callbacks from `app.py` so the service does not import Flask globals.
- [x] Run:

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $py -X utf8 -m pytest tests\test_admin_control_room.py -q
```

### Task 4: Final Verification

**Files:**
- Modify: touched Python files only

- [x] Run syntax checks:

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $py -X utf8 -m py_compile app.py services\admin_quality.py services\admin_leads.py services\admin_users.py
```

- [x] Run full tests:

```powershell
& $py -X utf8 -m pytest tests
```

- [x] Run `git diff --check` and inspect `git diff --stat`.
