# Radar Ask LLM-First Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Radar Ask use the typed LLM planner as the first intent layer, with deterministic routing kept as fallback and safety guardrail.

**Architecture:** `run_question()` should use the planner path first whenever a planner is configured. `route_question()` should also prefer the supplied planner for direct routing calls, while retaining deterministic fallback when planner output is unavailable or invalid. Existing typed route validation, tool allowlist, answer presenters, quotas, and budget guards remain unchanged.

**Tech Stack:** Python 3.12, Flask, Pydantic contracts, DeepSeek typed planner, PostgreSQL-backed Radar Ask repository, pytest.

## Global Constraints

- Do not reprocess listings, valuations, or read models.
- Do not add crawl-time LLM enrichment.
- Do not broaden tool permissions or expose private listing URLs/phones to non-admin users.
- Keep deterministic routing as fallback, not primary routing, when a planner is available.
- Keep verification 80/20: focused Radar Ask tests, compile, production route smoke.

---

### Task 1: Route-level planner-first behavior

**Files:**
- Modify: `services/radar_ask/routing.py`
- Test: `tests/test_radar_ask_routing.py`

**Interfaces:**
- Consumes: `route_question(request, context, planner=..., registry=...)`
- Produces: planner-first routing when `planner` is supplied; deterministic fallback when planner is absent or unusable.

- [x] **Step 1: Write failing tests**

Add tests proving that simple investor questions call the planner first, and planner invalid output falls back to deterministic routing.

- [x] **Step 2: Verify tests fail**

Run: `pytest -p no:cacheprovider tests/test_radar_ask_routing.py -q`

- [x] **Step 3: Implement minimal routing change**

Change `route_question()` so it attempts `planner(...)` before `_deterministic_route()` when a planner is provided. If the planner raises `ProviderError`, `ValidationError`, `TypeError`, or `ValueError`, fall back to deterministic routing; if no deterministic route exists, raise `RoutingPolicyViolation` for invalid planner output or `PlannerRequired` for unavailable planner.

- [x] **Step 4: Verify tests pass**

Run: `pytest -p no:cacheprovider tests/test_radar_ask_routing.py -q`

### Task 2: Orchestrator planner-first execution

**Files:**
- Modify: `services/radar_ask/orchestrator.py`
- Test: `tests/test_radar_ask_orchestrator.py`

**Interfaces:**
- Consumes: `OrchestratorDependencies.planner`
- Produces: planner path is used before deterministic fast path when planner exists; planner failure can fall back to deterministic safe route instead of service error.

- [x] **Step 1: Write failing tests**

Add tests proving a simple question uses planner reservation/usage first, and a planner provider failure falls back to deterministic routing when possible.

- [x] **Step 2: Verify tests fail**

Run: `pytest -p no:cacheprovider tests/test_radar_ask_orchestrator.py -q`

- [x] **Step 3: Implement minimal orchestrator change**

In `run_question()`, if `dependencies.planner` exists, skip the initial deterministic-only router call and enter the planned route branch. If planner provider failure occurs before a route is persisted, try deterministic fallback once and execute it with a normal sync reservation.

- [x] **Step 4: Verify tests pass**

Run: `pytest -p no:cacheprovider tests/test_radar_ask_orchestrator.py -q`

### Task 3: Verification and release

**Files:**
- Verify touched Python files and focused Radar Ask tests.

**Interfaces:**
- Produces: committed, pushed, deployed production SHA with route smoke.

- [x] **Step 1: Compile touched files**

Run: `py_compile services/radar_ask/routing.py services/radar_ask/orchestrator.py services/radar_ask/planner.py routes/radar_ask_api.py`

- [x] **Step 2: Run focused tests**

Run: `pytest -p no:cacheprovider tests/test_radar_ask_routing.py tests/test_radar_ask_orchestrator.py tests/test_radar_ask_planner.py tests/test_radar_ask_api.py -q`

- [ ] **Step 3: Commit, push, deploy**

Commit the plan and implementation, push `HEAD:main`, run `scripts/deploy_production.ps1`.

- [ ] **Step 4: Production smoke**

Verify deployed SHA, `https://radarbds.vn/` HTTP 200, and production route behavior for the user-reported questions.
