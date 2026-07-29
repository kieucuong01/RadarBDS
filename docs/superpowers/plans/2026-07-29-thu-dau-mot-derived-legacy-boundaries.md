# Thu Dau Mot Derived Legacy Boundaries Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the old pre-merger point-only product layer with 14 pre-merger ward boundary polygons, using 12 sourced polygons plus 2 derived polygons for Hoa Phu and Phu Tan.

**Architecture:** Keep the existing map-product pipeline. Add a legacy boundary source snapshot, derive missing boundaries deterministically from the current post-2025 Binh Duong ward polygon plus adjacent known old polygons and reference centers, then render legacy PDF/SVG/KML from polygon layers. Product copy and release validation must disclose derived boundaries as reference map data, not cadastral/legal boundaries.

**Tech Stack:** Python 3.12, Flask/Jinja, Shapely, ReportLab, SVG/KML ElementTree, pytest, Node syntax checks.

## Global Constraints

- Do not copy coordinates from DiaOcThongThai.
- Legacy edition must contain exactly 14 Polygon/MultiPolygon ward boundaries.
- Hoa Phu and Phu Tan may be derived only from existing licensed/snapshot geometry and legacy center points.
- Metadata must mark derived boundaries with `boundary_source=derived_boundary`.
- Public/product copy must include a disclaimer that boundaries are for reference and not cadastral/legal confirmation.
- Keep product version 1.0 unless a separate migration is required.
- Use TDD: write failing tests before production code.

---

### Task 1: Source and geometry contract tests

**Files:**
- Modify: `tests/test_thu_dau_mot_map_sources.py`
- Modify: `map_products/models.py`
- Modify: `map_products/geometry.py`

**Interfaces:**
- Produces: `NormalizedMapLayers.legacy_boundaries: tuple[NamedGeometry, ...]`
- Produces: source properties `boundary_source`, `derived_from`, and `boundary_claim` on legacy boundary features.

- [ ] Write tests expecting exact 14 legacy Polygon/MultiPolygon boundaries and two derived names.
- [ ] Run the tests and confirm they fail because only legacy points exist.
- [ ] Add loader/normalizer support for `legacy_boundaries`.
- [ ] Run the tests and confirm they pass.

### Task 2: Release/render contract

**Files:**
- Modify: `map_products/scene.py`
- Modify: `map_products/renderers.py`
- Modify: `map_products/release.py`
- Modify: `scripts/build_thu_dau_mot_map_product.py`
- Modify: `tests/test_thu_dau_mot_map_release.py`
- Modify: `tests/test_thu_dau_mot_map_renderers.py`

**Interfaces:**
- Consumes: `NormalizedMapLayers.legacy_boundaries`.
- Produces: legacy KML folder `legacy-boundaries` with 14 placemarks.

- [ ] Write tests expecting legacy SVG/PDF/KML metadata to describe 14 reference boundaries.
- [ ] Run and confirm failures against point-only renderer.
- [ ] Update scene/renderers/release validation and package guide/license copy.
- [ ] Run tests and confirm pass.

### Task 3: Product page and interactive map

**Files:**
- Modify: `templates/thu_dau_mot_map_product.html`
- Modify: `static/css/thu_dau_mot_map_product.css`
- Modify: `static/js/thu_dau_mot_map_product.js`
- Modify: `tests/test_thu_dau_mot_map_product_page.py`

**Interfaces:**
- The product page exposes interactive map data URLs and uses Leaflet if available.
- Purchase block remains below interactive map content.

- [ ] Write tests for before/after interactive map copy, order, and safe disclaimer.
- [ ] Run and confirm failures.
- [ ] Update template/CSS/JS.
- [ ] Run tests and node syntax check.

### Task 4: Rebuild release artifacts and registry

**Files:**
- Modify: `config/map_products/thu_dau_mot_sources.json`
- Add: `config/map_products/thu_dau_mot_legacy_boundaries.geojson`
- Modify: `static/images/seo/thu-dau-mot-map-before.webp`
- Modify: `static/images/seo/thu-dau-mot-map-after.webp`
- Modify: `services/digital_products.py`

**Interfaces:**
- Protected production package keeps filename `radarbds-thu-dau-mot-map-v1.0.zip`.

- [ ] Generate source snapshot and derived boundaries.
- [ ] Build candidate/package locally.
- [ ] Update approved package and manifest checksums.
- [ ] Run release gate tests.

### Task 5: Verification and release

**Files:**
- Stage only files touched by this task.

- [ ] Run py_compile, node --check, targeted pytest, git diff --check.
- [ ] Commit.
- [ ] Push branch/main as requested.
- [ ] Deploy with the project wrapper only after package is installed and verified.
