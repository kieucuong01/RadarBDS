# Ben Cat Sequential Listing Map Registry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Process every legacy Ben Cat ward and My Phuoc market sub-zone one at a time, moving every public ward-center listing with a trustworthy road or landmark reference onto an evidence-backed map marker.

**Architecture:** Reuse the approved listing-map resolver and registry workflow. For each ward, join the production active-row audit with the public `/api/map-listings` ward group, classify failures as parser, scope, ambiguity, missing OSM, or invalid prose, then ship one reversible resolver version before starting the next ward.

**Tech Stack:** Python 3.12, PostgreSQL, OpenStreetMap pinned JSON, Google Maps public browser evidence, Flask APIs, static JSON registry, pytest, PowerShell.

## Execution Outcome: Resolver v55

- Completed the first evidence-backed pass across all 12 Bến Cát legacy wards and Mỹ Phước market sub-zones in one release candidate.
- Added explicit Thới Hòa road scopes for Mỹ Phước 1, 3, and 4 while preserving the honest Mỹ Phước ward-center fallback label.
- Expanded deterministic extraction for proven industrial road families and clipped common trailing advertising copy.
- Added only source-backed aliases, OSM aggregates, and bounded public-coordinate landmarks; unresolved N13, DA1, 7B, DH605/DH616, and other missing geometries remain quarantined instead of being guessed.
- Local audit estimates at least 1,014 current ward-center rows can resolve to a road or landmark after backfill.
- Two independent builds of all four artifacts produced byte-identical SHA-256 hashes; the full listing Maps/location test suite and local full backfill dry-run passed before release.

## Global Constraints

- Process wards in this order: `Phu An`, `An Dien`, `An Tay`, `My Phuoc 3`, `Tan Dinh`, `Chanh Phu Hoa`, `Hoa Loi`, `My Phuoc 1`, `My Phuoc 2`, `My Phuoc 4`, `My Phuoc`, `Thoi Hoa`.
- Treat `My Phuoc 1` through `My Phuoc 4` as distinct market sub-zones even though their ward centers fall back to `My Phuoc`.
- Measure both all active production rows and the exact public IDs currently returned inside each ward-center location group.
- Never use a bare road-width or lot-dimension token such as `DT 5`, `DT 10`, or `DT 5x40` as a road.
- Support industrial-grid codes only when the full prefix-number family is proven, including `DL`, `DJ`, `NJ`, `NK`, and `NH`; add each parser family through RED -> GREEN tests.
- Prefer clipped OSM geometry. Browser/Google Maps evidence may create a bounded point only when a unique public result or a visually proven named road is available.
- Store map evidence only in the map registry. Do not write it into canonical listing, valuation, deduplication, feedback, or AI-review fields.
- Build all four registry artifacts twice and require byte-identical SHA-256 values before every release.
- Release each ward separately: focused tests -> full Maps suite -> commit -> push -> deploy -> dry-run -> apply -> second dry-run with `updated=0` -> production ward audit -> public API/browser smoke.
- Preserve unrelated `.playwright-cli/` and all runtime `.local/` evidence outside Git.

---

### Task 1: Complete Phu An

**Files:**
- Modify as required: `services/listing_map_context.py`, `services/listing_location_resolver.py`
- Modify: `config/listing_map.py`, `config/listing_map_location_sources.json`, `config/listing_map_location_overrides.json`
- Test: `tests/test_listing_map_context.py`, `tests/test_listing_location_resolver.py`, `tests/test_listing_location_registry.py`
- Regenerate: `static/maps/listing-locations/*.json`

**Interfaces:**
- Consumes 188 public ward-center rows, including 118 rows with a current road or landmark candidate.
- Produces one new resolver version and exact production before/after counts for Phu An.

- [ ] Record the public and active baseline, then inspect every candidate family with at least two public rows.
- [ ] Classify `DT744`, `DH609`, numbered roads, Phu An local roads, and landmarks as OSM, scoped reuse, browser-backed override, or invalid prose.
- [ ] Write literal failing parser/resolver/registry tests for every accepted family and verify RED.
- [ ] Add only the minimum parser aliases and registry evidence required, then verify GREEN.
- [ ] Build twice, run the full Maps suite, release, backfill, and prove the new public ward count.

### Task 2: Complete An Dien

**Files:** Same bounded resolver/config/test/artifact surfaces as Task 1.

**Interfaces:**
- Consumes 79 public ward-center rows; the initial audit exposes 57 candidate-bearing rows, led by `DT748`.
- Produces a separate resolver version and production evidence for An Dien.

- [ ] Verify the correct An Dien segment of DT748 rather than reusing the Phu An point blindly.
- [ ] Resolve `Vanh dai 4`, `Hung Vuong`, valid numbered roads, and KDC Rach Bap only with ward-compatible evidence.
- [ ] Reject unfinished-road and dimension prose such as `dang mo rong` and `vanh 4 10 x 27 m`.
- [ ] Complete RED/GREEN, deterministic build, release, backfill, API, and browser gates.

### Task 3: Complete An Tay

**Interfaces:**
- Consumes 68 public ward-center rows; 44 currently contain candidates led by `DT744`, `DH609`, and `Nguyen Cum`.

- [ ] Clip/reuse the correct DT744 and DH609 geometry for An Tay.
- [ ] Verify Nguyen Cum, Lien Thanh, Hung Vuong, Vanh dai 4, and KDC An Tay A.
- [ ] Quarantine future-project and marketing landmark prose.
- [ ] Complete all per-ward release gates.

### Task 4: Complete My Phuoc 3

**Interfaces:**
- Consumes 182 public ward-center rows; at least 91 have current candidates and another group contains missed industrial-grid codes.

- [ ] Add explicit My Phuoc 3 road scopes instead of relying only on the My Phuoc parent fallback.
- [ ] Verify My Phuoc - Tan Van, QL13/Dai lo Binh Duong, DL12, DL14, and accepted My Phuoc 3 landmarks.
- [ ] Add RED/GREEN parser support for proven `DJ`, `NJ`, `NK`, and `NH` code families without accepting dimensions.
- [ ] Separate direct grid codes from prose-contaminated candidates such as `NA7 va KCN...`.
- [ ] Complete all per-ward release gates.

### Task 5: Complete Tan Dinh

**Interfaces:**
- Consumes 190 public ward-center rows; 52 expose current candidates, with additional false `DT` dimension tokens requiring parser hardening.

- [ ] Disambiguate QL13/Dai lo Binh Duong and My Phuoc - Tan Van using the Tan Dinh segment.
- [ ] Verify DH601, QL14 aliases, Cho Hoang, and valid local roads.
- [ ] Add regression tests proving `DT 5`, `DT 6`, and `DT 5x40` dimensions are not provincial-road candidates.
- [ ] Complete all per-ward release gates.

### Task 6: Complete Chanh Phu Hoa

- [ ] Verify QL14/Quoc lo 14, My Phuoc - Tan Van, DT741, DH605, Pham Ngoc Thach, and numbered roads.
- [ ] Add only real KDC/project landmarks; reject generic `du an nam` and business prose.
- [ ] Complete all per-ward release gates for the 79 public ward-center rows.

### Task 7: Complete Hoa Loi

- [ ] Verify QL14, DT741, DH601, DH602, Tran Dai Nghia, and Vanh dai 4 in the Hoa Loi scope.
- [ ] Canonicalize TDC Hoa Loi variants and valid named residential projects.
- [ ] Reject surface/status phrases such as `dang lam` and `chuan bi len nhua`.
- [ ] Complete all per-ward release gates for the 85 public ward-center rows.

### Task 8: Complete My Phuoc 1

- [ ] Create explicit My Phuoc 1 scope for QL13, My Phuoc - Tan Van, D8/D9/D18/D18A, Le Loi, and accepted N-grid codes.
- [ ] Verify the scope prevents collisions with same-named roads in other My Phuoc zones.
- [ ] Complete all per-ward release gates for the 54 public ward-center rows.

### Task 9: Complete My Phuoc 2

- [ ] Create explicit My Phuoc 2 scope for QL13, DA1, DA11, NA3, DB4, DH605, road 2, and road 7B.
- [ ] Keep lot/block prose such as `lo 7B vai buoc...` out of the canonical road parser.
- [ ] Complete all per-ward release gates for the 54 public ward-center rows.

### Task 10: Complete My Phuoc 4

- [ ] Create explicit My Phuoc 4 scope for N12/N13/N16/N18, DH616, My Phuoc - Tan Van, and the My Phuoc 4 landmark.
- [ ] Verify same-code N roads do not resolve to Hoa Loi or another My Phuoc zone.
- [ ] Complete all per-ward release gates for the 20 public ward-center rows.

### Task 11: Complete parent My Phuoc

- [ ] Resolve QL13, My Phuoc - Tan Van, DT742, Tran Dai Nghia, road 2, Ho Da, Nam Thai, and TDC My Phuoc.
- [ ] Ensure parent entries do not override explicit My Phuoc 1-4 scopes.
- [ ] Complete all per-ward release gates for the 36 public ward-center rows.

### Task 12: Complete Thoi Hoa and close Ben Cat

- [ ] Resolve the Thoi Hoa segment of QL13 and valid N/NL codes plus accepted My Phuoc 3 boundary landmarks.
- [ ] Re-audit all 12 scopes after the final backfill.
- [ ] Prove every remaining public ward-center row has no trustworthy road/landmark reference or is explicitly quarantined with a deterministic reason.
- [ ] Run the full Maps suite, double build, production dry/apply/dry, all 12 public APIs, and browser smoke before marking Ben Cat complete.
