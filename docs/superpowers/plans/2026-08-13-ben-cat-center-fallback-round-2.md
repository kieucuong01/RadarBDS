# Bến Cát Center Fallback Round 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move trustworthy Mỹ Phước, Chánh Phú Hòa, and Thới Hòa listings out of “Theo trung tâm” when their text names a known road or Mỹ Phước sub-zone.

**Architecture:** Keep all enrichment deterministic and offline. Improve `extract_map_location_context()` only for bounded, explicit road/sub-zone clues, then expand the versioned static registry with official/OSM/Google-public evidence; `resolve_listing_location()` and the existing derived-table backfill remain the only write path.

**Tech Stack:** Python 3.12, pytest, JSON registry builder, PostgreSQL derived map tables, browser-use CDP verification.

## Global Constraints

- Never mutate canonical listing fields, valuation rows, human labels, or AI review.
- Never call Google Maps, OSM, or a geocoder from crawl or a public request.
- Ambiguous multi-zone text stays on the safest available fallback.
- `TC` thổ-cư and `DT` diện-tích tokens must not become road codes.
- Preserve unrelated `.playwright-cli/` worktree content.

---

### Task 1: Add production-derived RED tests

**Files:**
- Modify: `tests/test_listing_map_context.py`
- Modify: `tests/test_listing_location_resolver.py`

**Interfaces:**
- Consumes: `extract_map_location_context(title, description, stored_road_name)`
- Produces: regression cases for ĐH604/2-9, ĐH605, ĐH602, ĐH607/Bến Chà Vi, Mỹ Phước 1-4, and Khu F-L

- [ ] **Step 1: Write failing parser tests**

Add assertions that “Đường 2/9” resolves to `dh 604` candidate semantics, “Bến Chà Vi” to `dh 607`, a single explicit Mỹ Phước number to its aggregate landmark, and `DT 5x32` / `TC 60m` to no road.

- [ ] **Step 2: Write failing resolver tests**

Use small in-memory `LocationRegistry` fixtures proving Khu G/H/K/L can resolve for the three requested ward labels and ĐH604 aliases retain road precision.

- [ ] **Step 3: Run RED gate**

Run:

```powershell
& $py -X utf8 -m pytest tests\test_listing_map_context.py tests\test_listing_location_resolver.py -q
```

Expected: only the newly added cases fail before implementation.

### Task 2: Tighten deterministic map clue extraction

**Files:**
- Modify: `services/listing_map_context.py`
- Test: `tests/test_listing_map_context.py`

**Interfaces:**
- Consumes: normalized title, description, and stored road name
- Produces: bounded `MapLocationContext` with either a reliable road or landmark clue

- [ ] **Step 1: Normalize official Bến Cát road aliases**

Recognize Đường 2/9 as ĐH604, Bến Chà Vi as ĐH607, Ba Làng Xi as ĐH602, and Lộ 7B as one bounded road token.

- [ ] **Step 2: Add single-zone area extraction**

Return Khu F-L first; otherwise return one explicit Mỹ Phước 1-4 area. If two different numbered areas are named and no letter zone disambiguates them, return no numbered landmark.

- [ ] **Step 3: Prevent dimension/marketing false positives**

Reject `TC <number>` unless explicit road wording exists and keep generic landmark capture from swallowing price/marketing sentences.

- [ ] **Step 4: Run parser tests GREEN**

Run the Task 1 parser subset and require all cases to pass.

### Task 3: Expand the evidence-backed registry

**Files:**
- Modify: `config/listing_map_location_overrides.json`
- Modify: `tests/test_listing_location_registry.py`
- Generated: `static/maps/listing-locations/*.json`

**Interfaces:**
- Consumes: manual aliases/anchors plus existing OSM artifacts
- Produces: one version-matched ward, road, landmark, and manifest registry

- [ ] **Step 1: Add road aliases and anchors**

Add:

- Chánh Phú Hòa ĐH604 aliases `Đường 2/9`, `2/9`;
- Chánh Phú Hòa ĐH605 at the midpoint of official endpoints 11°08'52”/106°37'50” and 11°09'43”/106°40'15”;
- Thới Hòa ĐH602 using the existing official 11.0830556/106.6452778 anchor;
- Mỹ Phước ĐH607/Bến Chà Vi using the Google public road result 11.1639132/106.6061853;
- Mỹ Phước Lộ 7B using the official route identity plus the bounded Google Maps search viewport anchor.

- [ ] **Step 2: Add cross-scope zone aliases**

Reuse the already verified Mỹ Phước 1-4 and Khu F-L anchors for Mỹ Phước, Chánh Phú Hòa, and Thới Hòa only where the text explicitly names that zone.

- [ ] **Step 3: Increment resolver version once**

Change all override/generated registry artifacts to one new resolver version.

- [ ] **Step 4: Build twice and compare hashes**

Run the documented registry builder twice from the same inputs and require identical hashes.

- [ ] **Step 5: Run registry and resolver tests GREEN**

Run all listing-map context, registry, resolver, backfill, and coverage tests.

### Task 4: Measure local and production impact

**Files:**
- No tracked file changes

**Interfaces:**
- Consumes: versioned registry and production derived tables
- Produces: before/after precision counts and unresolved candidate counts

- [ ] **Step 1: Run local full dry-run**

Run `radar.py map-locations --full --dry-run` against the configured local database.

- [ ] **Step 2: Re-run the production audit logic locally against the new resolver**

Use the production listing IDs already identified in the bounded audits and verify that only explicit road/zone cases upgrade.

- [ ] **Step 3: Run focused and full regression gates**

Run Python compile, all map tests, and the normal test set excluding documented live integration tests.

### Task 5: Release and prove the live Maps behavior

**Files:**
- Commit only the scoped parser, tests, overrides, generated artifacts, and this plan

**Interfaces:**
- Consumes: tested main-branch change
- Produces: pushed SHA, deployed SHA, production backfill, idempotence, and browser proof

- [ ] **Step 1: Stage scoped files and commit**

Verify `git diff --cached --name-only` excludes `.playwright-cli/` and ignored audit files.

- [ ] **Step 2: Push and deploy**

Push `main`, run `scripts/deploy_production.ps1`, and verify the exact VPS SHA plus HTTP 200.

- [ ] **Step 3: Backfill production twice**

Run full dry-run, apply once, then dry-run again. The second dry-run must report zero updates.

- [ ] **Step 4: Compare requested ward counts**

Report before/after `ward`, `road`, and `landmark` counts for Mỹ Phước, Chánh Phú Hòa, and Thới Hòa.

- [ ] **Step 5: Verify with browser-use**

Open the production Maps overlay with the Bến Cát filters, confirm the canvas loads, confirm new road/zone groups replace relevant “Theo trung tâm” rows, open and close one listing modal, and confirm Maps state is preserved.
