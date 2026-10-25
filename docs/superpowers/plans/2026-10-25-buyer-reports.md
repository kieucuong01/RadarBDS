# Buyer report implementation

Approved design: `docs/report_buyer_upgrade.md`; one shared buyer audience.

- [x] P0: safe legacy presentation from frozen report facts: separate n, suppress
  small-sample prices/trends, remove selected-MOS percentages, clarify dates,
  sample coverage and legal uncertainty. Never query today's prices into old reports.
- [x] P1: immutable buyer facts for newly generated closed-month reports: sale-only
  cohorts, price/area quartiles, budget bands, comparable ward/type tables, exact
  counts and observation metadata. Existing reports retain their saved facts.
- [x] P2: observed price-change/history summaries where evidence exists; coverage
  overview, contextual source references and a practical viewing/cost checklist.
- [x] Render one shared model on web and PDF; preserve report links, permissions,
  monthly automation, public-brand CSS order and the no-browser download path.
- [x] Verify unit/data edge cases, render master/large/small ward reports at mobile
  width and inspect every page of representative PDFs (master 9, small ward 9, large ward 10 pages).
- [ ] Rebuild all available production PDFs and verify public downloads.
- [ ] Review the whole diff, push only intended files, wait for the exact successful
  CI revision, deploy preserving unrelated VPS work, and verify public downloads.

Files: `services/report_buyer.py` (frozen presentation),
`services/report_buyer_snapshot.py` (generation-only facts),
`services/monthly_report_data.py`, monthly generators, report templates/styles,
`services/report_pdf.py`, focused tests and monthly-report documentation.

Historical bounds: published reports without raw cohort snapshots cannot acquire
historical budget quartiles from current listings. Show missing-data labels and
links to current filtered discovery; new facts start with genuinely newly generated
reports and preserve their generation timestamp. No in-progress formal report.

Ledger: base `21088b7`; unrelated `.playwright-cli/` and `.superpowers/` preserved.

Local evidence (25 October): 154 focused tests passed; final buyer/snapshot/PDF
regressions 26 passed after review. PostgreSQL integration covers source/sale,
price-event chronology and canonical aliases. Mobile 390px master/large/small
reports have no horizontal page overflow, 13 master ward comparisons, and one
lead form at the end. All pages of three representative PDFs were inspected;
empty price charts and near-blank pages were removed. Graphify was refreshed.
Independent review found five issues; all were repaired and reviewed again with
no remaining release blocker. Existing historical market facts were not regenerated.
Production release evidence will be recorded separately after exact-revision CI.

CI uncovered four pre-existing UTC/Vietnam midnight failures outside report code.
Listing age now compares both instants on the Vietnam calendar (naive DB values
are Vietnam-local). Publisher-policy tests use frozen actual observation instants
and the matching Vietnam as-of date; production publisher policy is unchanged.
Three new deterministic listing-age regressions failed before the repair; the
74 related timezone/source-policy/publisher tests passed after it.
