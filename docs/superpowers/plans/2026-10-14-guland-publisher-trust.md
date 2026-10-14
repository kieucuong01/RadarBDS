# Guland Publisher Trust Implementation Plan

**Goal:** Tighten Guland promotion without changing Facebook, valuation inputs, or stored listings.

**Approved design:** The in-chat proposal approved on 2026-10-14. Unknown or insufficiently observed Guland publishers remain available for inspection but are excluded from Săn Deal, its counts/maps, and VIP alerts. Price changes do not override spam classification. Existing audited admin overrides remain supported.

**Architecture:** Extend the existing deterministic publisher classifier and shared SQL policy. Store a separate promotion boolean in the card projection; keep all-listings visibility independent. No LLM, external dependency, or automatic owner-verification claim.

**Initial thresholds:** 14 calendar days between first actual observation and classification, with actual observations on at least 3 distinct Vietnam dates within 30 days. Backfilled posting dates do not establish coverage. Existing volume thresholds remain unchanged and take precedence over coverage.

## Tasks

- [x] Add failing tests for insufficient observation, safe repost evidence, unknown publisher promotion, explicit admin override, and unchanged Facebook eligibility.
- [x] Implement metrics/classifier, shared legacy/projection/VIP promotion policy, and corrected date-only bump detection. Publish every affected publisher's linked cards through existing refresh paths.
- [x] Provide a read-only impact/sample report and an explicit reclassification command that publishes the projection transactionally; update product/ops documentation and honest admin labels.
- [x] Run focused PostgreSQL, read-model parity, listing/Maps/counts/VIP regressions, syntax and diff checks; review the complete change.

## Review focus

- Missing identity or old metrics must fail closed for promotion, while retaining existing all-listings policy.
- A fresh publisher or a single backfill batch cannot manufacture 14 days of observations.
- A legitimate price change, missing price, or backward date correction must not count as an unchanged repost.
- Repeated observations remain idempotent; overrides and all linked card publication remain atomic.
- Facebook predicates always pass; valuation inputs and human labels are untouched.

## Execution evidence

- Baseline: 36 publisher activity/repository tests passed on the dedicated local PostgreSQL test database.
- Local discovery: 6,167 Guland listings, zero publisher identities/observations. This is not evidence of production coverage or calibrated thresholds.
- Work in the existing checkout; preserve unrelated untracked `.playwright-cli/` and `.superpowers/` directories. No push/deploy is part of this implementation turn.
- Review corrections: measure maturity across actual observation history, not only the rolling window; replay raw collection timestamps rather than the reprocess clock; publish all linked cards after identity backfill and retain pending publication IDs across resume. These paths do not revalue extra linked listings.
- Final verification: 219 related tests passed; 21 existing `datetime.utcnow()` deprecation warnings in auth code. Python compilation, admin JavaScript syntax, and `git diff --check` passed. Fresh review found no remaining important issue after midnight Vietnam and source-last-seen regressions were fixed.
- Read-only local impact report: 6,167 unidentified Guland listings, including 933 price/MOS candidates held back from promotion; 30 non-PII sample IDs saved in ignored `.local/guland-trust-impact-2026-10-14.json`. No production measurements or deployment were performed.
- Graphify query ran before source exploration; the ignored structural code graph was refreshed after implementation (14,241 nodes / 35,081 edges, no LLM or clustering).
