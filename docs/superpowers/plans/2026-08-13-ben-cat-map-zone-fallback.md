# Bến Cát Map Zone Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve roadless Bến Cát listings to honest Mỹ Phước and Tân Định sub-area markers, and correct the Mỹ Phước 4 fallback location.

**Architecture:** Extend map-only context extraction with unambiguous zone clues, preserve them in the static landmark registry, and let ward fallback optionally delegate to a configured area landmark. Existing exact-coordinate and road resolution remain higher priority.

**Tech Stack:** Python 3.12, PostgreSQL, Flask resolver services, deterministic JSON registry builder, pytest, browser-use CDP.

## Global Constraints

- Resolver priority is `exact -> road -> zone/landmark -> ward`.
- Do not mutate canonical listing road or ward data.
- Do not choose one zone when a listing names multiple different zones.
- Use `apply_patch` for source edits and preserve unrelated `.playwright-cli/` files.
- Registry output must be deterministic and all manual points must include HTTPS provenance.

---

### Task 1: Zone extraction contract

**Files:**
- Modify: `services/listing_map_context.py`
- Test: `tests/test_listing_map_context.py`

**Interfaces:**
- Consumes: normalized title and description strings.
- Produces: `MapLocationContext.landmark` values `khu f` through `khu l` and `khu pho 1 tan dinh` through `khu pho 4 tan dinh` only for an unambiguous zone.

- [ ] **Step 1: Write failing extraction tests** for single letter/numeric zones, multiple-zone rejection, and a road-plus-zone example.
- [ ] **Step 2: Run the focused context tests** and confirm they fail on missing zone extraction.
- [ ] **Step 3: Implement `_subzone_landmark(text: str) -> str`** using exact regex matches and unique-value checks.
- [ ] **Step 4: Run the focused context tests** and confirm road extraction remains unchanged.

### Task 2: Configured area fallback and registry points

**Files:**
- Modify: `services/listing_location_resolver.py`
- Modify: `scripts/build_listing_location_registry.py`
- Modify: `config/listing_map_location_sources.json`
- Modify: `config/listing_map_location_overrides.json`
- Test: `tests/test_listing_location_resolver.py`

**Interfaces:**
- Consumes: optional ward registry property `fallback_landmark`.
- Produces: a `ResolvedLocation` with `precision="landmark"` whenever the configured fallback entry exists; otherwise preserves the existing ward fallback.

- [ ] **Step 1: Write failing resolver tests** for Mỹ Phước 1-4 defaults, corrected Mỹ Phước 4 coordinates, Khu F-L, Tân Định KP1-4, ambiguity, and Chợ Bến Lớn.
- [ ] **Step 2: Run focused resolver tests** and confirm expected missing landmarks/fallbacks.
- [ ] **Step 3: Preserve `fallback_landmark` in ward registry output** and resolve it inside `_ward_fallback` before using the ward point.
- [ ] **Step 4: Add provenance-backed landmark aliases/points and Chợ Bến Lớn road aliases/point**, then bump all registry versions together.
- [ ] **Step 5: Build the registry and run focused tests** until green.

### Task 3: Coverage verification and release

**Files:**
- Regenerate: `static/maps/listing-locations/ward-centers.json`
- Regenerate: `static/maps/listing-locations/road-centers.json`
- Regenerate: `static/maps/listing-locations/landmark-centers.json`
- Update: `graphify-out/graph.json`

**Interfaces:**
- Consumes: deterministic config and resolver behavior from Tasks 1-2.
- Produces: updated derived locations and measurable Bến Cát coverage.

- [ ] **Step 1: Build twice and compare SHA-256 hashes** for all three registry outputs.
- [ ] **Step 2: Run targeted and full listing-map tests** plus Python compilation.
- [ ] **Step 3: Run local per-ward dry-run and full backfill**, compare `road`, `landmark`, `ward`, `not_found`, and `ambiguous` counts.
- [ ] **Step 4: Inspect representative IDs from every new zone** and confirm labels/coordinates.
- [ ] **Step 5: Refresh Graphify, commit scoped files, push `main`, deploy, and run production dry-run/backfill**.
- [ ] **Step 6: Verify production HTTP/API and authenticated browser Maps behavior**, including Mỹ Phước 4 and Tân Định modal navigation state.
