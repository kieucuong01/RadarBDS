# Guland Signal Gate Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Guland use the same source-strength eligibility as Facebook, retain only explicit hard data-quality blockers, and make the `Săn Deal` badge equal the eligible card-feed total.

**Architecture:** Keep one shared actionable contract in `services/signal_quality.py` and one shared deal SQL builder in `services/market_data.py`. The valuation engine will stop generating Guland-only weak/user-facing flags; historical retired flags and a stale `source_quality_recheck` will not independently suppress cards, while explicit hard flags continue to do so.

**Tech Stack:** Python 3.12, Flask, PostgreSQL compatibility layer, pytest/unittest

## Global Constraints

- Guland and Facebook use the same model-signal and user-selected MOS threshold.
- Keep explicit hard data-quality flags blocking.
- Warning-only or retired flags must not suppress user-facing cards.
- `source_quality_recheck` is QC metadata, not an independent rejection reason.
- `/api/dashboard.stats.signals` and `/api/signals.total` must use the same predicate.
- No schema migration, crawler change, or external LLM enrichment.
- Preserve the current signals-first frontend flow with `include_total=0`.

---

### Task 1: Make Explicit Hard Flags the Only Quality Blockers

**Files:**
- Modify: `services/signal_quality.py:3-76`
- Modify: `tests/test_market_data_trust.py:18-36`
- Modify: `tests/test_listing_map_query_scope.py:1-14`

**Interfaces:**
- Consumes: valuation rows containing `is_signal`, `source_quality_flags`, and `source_quality_recheck`
- Produces: `is_actionable_signal(row) -> bool` and `actionable_signal_sql(alias: str) -> str` with equivalent explicit-flag semantics

- [ ] **Step 1: Write failing actionability tests**

Extend `tests/test_market_data_trust.py` so retired Guland flags and a bare
recheck remain actionable, while a hard flag still blocks:

```python
def test_retired_guland_flags_and_bare_recheck_do_not_suppress_signal():
    from services.signal_quality import is_actionable_signal

    for flags in ("guland_weak_signal", "guland_user_facing_risk", ""):
        row = {
            "is_signal": 1,
            "source_quality_recheck": 1,
            "source_quality_flags": flags,
        }
        assert is_actionable_signal(row) is True


def test_actionable_sql_uses_explicit_flags_not_recheck_boolean():
    from services.signal_quality import actionable_signal_sql

    sql = actionable_signal_sql("v")
    assert "source_quality_recheck" not in sql
    assert "ambiguous_price_text" in sql
    assert "guland_weak_signal" not in sql
    assert "guland_user_facing_risk" not in sql
```

Update `tests/test_listing_map_query_scope.py` to assert the shared deal
condition contains explicit hard flags but not `source_quality_recheck`.

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
& $py -X utf8 -m pytest tests/test_market_data_trust.py tests/test_listing_map_query_scope.py -q
```

Expected: failures show retired flags and a bare recheck are currently
suppressed, and SQL still contains `source_quality_recheck`.

- [ ] **Step 3: Implement the explicit-flag contract**

In `services/signal_quality.py`:

- Remove `guland_weak_signal` and `guland_user_facing_risk` from
  `ACTIONABLE_SUPPRESS_FLAGS`.
- Simplify `is_actionable_signal()` to require `is_signal` and reject only
  `flags & ACTIONABLE_SUPPRESS_FLAGS`.
- Remove the generic `source_quality_recheck` clause from
  `actionable_signal_sql()`; retain one `NOT LIKE` predicate per hard flag.
- Remove the now-unused `NON_BLOCKING_RECHECK_FLAGS`.

- [ ] **Step 4: Run the tests and verify GREEN**

Run the same focused pytest command. Expected: all selected tests pass.

- [ ] **Step 5: Commit Task 1**

```powershell
git add services/signal_quality.py tests/test_market_data_trust.py tests/test_listing_map_query_scope.py
git commit -m "fix: make signal quality blockers explicit"
```

---

### Task 2: Remove Guland-Only Strength Gates from Valuation

**Files:**
- Modify: `analytics/valuation.py:30-45`
- Modify: `analytics/valuation.py:230-263`
- Modify: `analytics/valuation.py:890-925`
- Modify: `tests/test_valuation.py:380-470`

**Interfaces:**
- Consumes: `ValuationEngine.valuate(listing: Listing)`
- Produces: the same `ValuationResult`, without generating
  `guland_weak_signal` or `guland_user_facing_risk`

- [ ] **Step 1: Replace the stronger-source test with a parity test**

Change the existing Guland strength test to:

```python
def test_guland_uses_same_signal_strength_gate_as_facebook():
    from services.signal_quality import is_actionable_signal

    listings = [_make_listing(i, 15.0, source="facebook") for i in range(30)]
    engine = ValuationEngine()
    engine.fit(listings)

    facebook_result = engine.valuate(_make_listing(1001, 12.5, source="facebook"))
    guland_result = engine.valuate(_make_listing(1002, 12.5, source="guland"))

    assert facebook_result.is_signal is True
    assert guland_result.is_signal is True
    assert "guland_weak_signal" not in guland_result.source_quality_flags
    assert "guland_user_facing_risk" not in guland_result.source_quality_flags
    assert guland_result.source_quality_recheck is False
    assert is_actionable_signal(guland_result) is True
```

Update the old-post test so `old_guland_post` remains warning-only unless
combined with an explicit hard flag.

- [ ] **Step 2: Run the valuation tests and verify RED**

Run:

```powershell
& $py -X utf8 -m pytest tests/test_valuation.py -q
```

Expected: Guland still receives `guland_weak_signal` or
`guland_user_facing_risk`, so the parity test fails.

- [ ] **Step 3: Remove the Guland-only gate implementation**

In `analytics/valuation.py`:

- Remove `GULAND_SIGNAL_EXTRA_MOS`, `GULAND_STRONG_SIGNAL_SCORE`,
  `GULAND_USER_ACTIONABLE_EXTRA_MOS`, and
  `GULAND_USER_ACTIONABLE_MIN_SCORE`.
- Remove `_passes_source_signal_gate()` and
  `_passes_guland_user_facing_gate()`.
- Stop adding `guland_weak_signal` and `guland_user_facing_risk` in
  `ValuationEngine.valuate()`.
- Compute `source_quality_recheck` only when a model signal carries a flag in
  `ACTIONABLE_SUPPRESS_FLAGS`.
- Remove `SOURCE_SIGNAL_SUPPRESS_FLAGS`; its still-valid hard members are
  already represented by `ACTIONABLE_SUPPRESS_FLAGS`, and
  `old_guland_post` becomes warning-only.

- [ ] **Step 4: Run valuation and reprocess regressions**

Run:

```powershell
& $py -X utf8 -m pytest tests/test_valuation.py tests/test_reprocess_review_hidden.py -q
```

Expected: all tests pass after updating assertions that intentionally encoded
the retired Guland-only gates.

- [ ] **Step 5: Commit Task 2**

```powershell
git add analytics/valuation.py tests/test_valuation.py tests/test_reprocess_review_hidden.py
git commit -m "fix: align guland signal strength with facebook"
```

---

### Task 3: Enforce Dashboard and Card-Feed Count Parity

**Files:**
- Modify: `services/market_data.py:1330-1363`
- Modify: `tests/test_source_policy.py:200-225`
- Modify: `tests/test_market_data_performance.py:295-355`

**Interfaces:**
- Consumes: `build_deal_sql(mos_min: float) -> DealSql`
- Produces: `load_dashboard_summary(...).stats["signals"]` matching
  `load_signals(..., include_total=True)["total"]`

- [ ] **Step 1: Add a failing API parity test**

In `SourcePolicyTest`, seed a second Guland MOS candidate and mark its latest
valuation with a hard flag:

```python
def test_admin_guland_dashboard_count_matches_actionable_signal_total(self):
    from db.connection import get_conn

    self._login_as_admin()
    blocked_id = self._seed_signal(
        source="guland",
        title="Blocked Guland price candidate",
        source_id="guland-blocked",
    )
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE valuation_results
            SET source_quality_recheck=1,
                source_quality_flags='ambiguous_price_text'
            WHERE listing_id=?
            """,
            (blocked_id,),
        )

    query = f"city=Khac&ward={self.ward}&source=guland&date_range=3m&mos_min=10"
    signals = self.client.get(f"/api/signals?{query}&limit=20").get_json()
    dashboard = self.client.get(f"/api/dashboard?{query}&cache_refresh=1").get_json()

    self.assertEqual(signals["total"], 1)
    self.assertEqual(dashboard["stats"]["signals"], signals["total"])
```

- [ ] **Step 2: Run the parity test and verify RED**

Run:

```powershell
& $py -X utf8 -m pytest tests/test_source_policy.py::SourcePolicyTest::test_admin_guland_dashboard_count_matches_actionable_signal_total -q
```

Expected: `/api/signals.total` is `1`, but dashboard count is `2`.

- [ ] **Step 3: Reuse the shared deal condition in the dashboard query**

Replace the dashboard-only MOS condition with:

```python
deal = build_deal_sql(mos_min)
signal_condition = deal.condition
```

Keep the existing latest valuation/shadow CTEs, shared listing filters, and
completeness checks unchanged.

- [ ] **Step 4: Run focused API and performance tests**

Run:

```powershell
& $py -X utf8 -m pytest tests/test_source_policy.py tests/test_guest_visibility.py tests/test_market_data_performance.py -q
```

Expected: parity test passes, existing source/tier behavior remains intact,
and the compact dashboard read-model assertions still pass.

- [ ] **Step 5: Commit Task 3**

```powershell
git add services/market_data.py tests/test_source_policy.py tests/test_market_data_performance.py
git commit -m "fix: align dashboard deal count with feed"
```

---

### Task 4: Final Verification and Rollout Readiness

**Files:**
- Verify only: `services/signal_quality.py`
- Verify only: `analytics/valuation.py`
- Verify only: `services/market_data.py`
- Verify only: focused tests above

**Interfaces:**
- Consumes: all three completed implementation tasks
- Produces: a verified branch ready for review and separately authorized
  production rollout

- [ ] **Step 1: Run syntax checks**

```powershell
& $py -X utf8 -m py_compile analytics/valuation.py services/signal_quality.py services/market_data.py
```

- [ ] **Step 2: Run the complete relevant regression set**

```powershell
& $py -X utf8 -m pytest tests/test_market_data_trust.py tests/test_listing_map_query_scope.py tests/test_valuation.py tests/test_reprocess_review_hidden.py tests/test_source_policy.py tests/test_guest_visibility.py tests/test_market_data_performance.py -q
```

- [ ] **Step 3: Check repository scope**

```powershell
git status --short --branch
git diff --check
git log --oneline -6
```

Expected: only intended commits exist, no runtime data or temporary files are
tracked, and the worktree is clean.

- [ ] **Step 4: Record production follow-up without executing it**

The handoff must state that production still needs a targeted full Guland
reprocess after deployment to clear retired stored flags and recheck values,
followed by a live `source=guland`, `date_range=3m`, `mos_min=10` parity check.

