# Market Analysis Tab P0-P2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Phan tich tab decision-grade for investors by fixing market data correctness, removing the slow heatmap route shape, and improving the rendered decision workflow.

**Architecture:** Keep Flask routes thin. Move market opportunity shaping into `services/market_data.py`, reuse existing request filters, shared signal semantics, and pooled read connections. The frontend consumes server-owned metadata instead of inferring totals from a sliced top-six list.

**Tech Stack:** Flask, PostgreSQL-compatible DB wrapper, vanilla JS, Chart.js, existing CSS/template split.

## Global Constraints

- Public/default signal semantics are MOS >= 15 for Guest/Free; VIP/Admin may explicitly request lower allowed values.
- User-facing signal surfaces use `services.signal_quality.actionable_signal_sql()`.
- Read paths should use `db.connection.get_conn()`/`_read_conn` bounded scopes, not fresh ad hoc `connect()` in route handlers.
- `/api/dashboard` remains lightweight; market tab APIs stay separate from signal feed payloads.
- Non-admin payloads must not expose original URLs or phone data.
- Work proceeds P0, then P1, then P2; each stage must have focused tests before production code changes.

---

### Task 1: P0 Market Scope And Opportunity API

**Files:**
- Modify: `services/market_data.py`
- Modify: `app.py`
- Test: `tests/test_market_data_performance.py`

**Interfaces:**
- Produces: `load_market_opportunities(db_path, ..., mos_min, tier, date_range, keyword, include_guland_high_activity) -> dict`
- Route payload: `{"rows": [...], "summary": {...}, "applied_filters": {...}, "as_of": "..."}`

- [ ] Write failing tests that `/api/heatmap` delegates to a service loader with normalized MOS/date/keyword filters.
- [ ] Write failing tests that the market loader uses `_read_conn`, applies date/keyword/MOS 15, and returns global totals plus top rows without slicing totals.
- [ ] Implement `load_market_opportunities()` in `services/market_data.py`.
- [ ] Thin `api_heatmap()` to request parsing plus `jsonify(load_market_opportunities(...))`.
- [ ] Run focused tests.

### Task 2: P0 Trend And Indicator Filter Parity

**Files:**
- Modify: `services/market_data.py`
- Modify: `app.py`
- Test: `tests/test_market_data_performance.py`
- Test: `tests/test_market_indicators.py`

**Interfaces:**
- Extend `load_trend_data(..., keyword="", date_range=None)`.
- Extend `load_market_indicators(..., keyword="", date_range=None, mos_min=..., tier=...)`.

- [ ] Write failing test that `load_trend_data()` applies `date_range`.
- [ ] Write failing test that market indicators receive date range and keyword from route.
- [ ] Implement date/keyword filter parity.
- [ ] Keep indicator heuristics labelled as heuristics and add sample-confidence fields.
- [ ] Run focused tests.

### Task 3: P1 Decision-First Frontend

**Files:**
- Modify: `static/js/main/market.js`
- Modify: `static/css/main/market.css`
- Modify: `templates/index.html`
- Test: `tests/test_refactor_structure.py`

**Interfaces:**
- Frontend accepts old array response and new object response during rollout.
- Add scope/freshness chips, correct totals, transparent ranking label, accessible chart summaries.

- [ ] Write failing structure tests for metadata chips, decision table, trend cap, and canvas accessibility.
- [ ] Render opportunity list from `payload.rows`, totals from `payload.summary`.
- [ ] Add sortable/comparison-style opportunity table for key metrics.
- [ ] Cap default trend series to top decision wards plus context, with sample warnings.
- [ ] Run JS syntax and structure tests.

### Task 4: P2 Accessibility, Feedback, And Conversion Hygiene

**Files:**
- Modify: `static/js/main/market.js`
- Modify: `static/css/main/market.css`
- Modify: `templates/index.html`
- Test: `tests/test_refactor_structure.py`

**Interfaces:**
- Period buttons expose pressed state.
- Canvas has label/fallback content.
- Loading/error states are visible and retryable.
- Locked VIP content is compact.

- [ ] Write failing structure tests for `aria-pressed`, canvas labels/fallbacks, retry state hooks, and compact locked preview.
- [ ] Implement visible error/retry rendering for heatmap, trend, and indicators.
- [ ] Raise mobile touch targets to at least 44px.
- [ ] Add privacy-safe analytics events for market tab drill-downs where existing GA helper is available.
- [ ] Run browser QA on desktop and 390px mobile.

### Task 5: Verification

**Files:**
- No production edits unless verification exposes a bug.

- [ ] Run Python syntax on touched Python files.
- [ ] Run JS syntax on touched JS files.
- [ ] Run focused pytest files.
- [ ] Run browser smoke for Phan tich tab desktop/mobile.
- [ ] Confirm `git status --short` only contains intended changes plus pre-existing `.playwright-cli/`.
