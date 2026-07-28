# TP.HCM Mixed-Use Land Calculator Implementation Plan

> **Execution:** Use `superpowers:executing-plans` and strict red-green-refactor
> cycles. Do not write production behavior before its failing test.

**Goal:** Let `/bang-gia-dat-tphcm` calculate a parcel containing both
residential and agricultural land, with explainable legal formulas and a
responsive, accessible form.

**Architecture:** Put agricultural zone tables and formulas in a focused
service. Extend the existing land-price calculator with a mixed-use
orchestrator. The Flask route remains thin and resolves the official road row
server-side. The existing browser calculator owns progressive disclosure,
payload shaping and safe result rendering.

**Tech stack:** Python 3.12, Flask, Decimal, vanilla JavaScript, CSS, pytest,
Node built-ins, browser smoke.

## Task 1: Agricultural zone and formula service

**Files**

- Create `services/tphcm_agricultural_land_prices.py`
- Create `tests/test_tphcm_agricultural_land_prices.py`

**Red**

- Test representative and boundary area names for zones I-IV.
- Test every official area is mapped, including
  `XÃ PHÚ BÌNH MỸ -> zone III`.
- Test annual and perennial tables for all 12 zone/position cells.
- Test production forest, protected/special forest, aquaculture, livestock
  cap and salt formulas.
- Test Article 5.8 for a ward and for an opted-in commune.
- Test the normal-table floor and `other_agricultural` manual result.
- Test invalid enums, positions, missing zones and non-finite inputs.

Run and confirm failure:

```powershell
& $py -X utf8 -m pytest tests\test_tphcm_agricultural_land_prices.py -q
```

**Green**

- Add immutable zone sets, price tables and allowlisted land types.
- Add `resolve_agricultural_zone(area_name)`.
- Add `calculate_agricultural_land_price(...)`.
- Keep arithmetic as `Decimal`; expose formula steps and floor/cap metadata.

Run the same test file and confirm green.

## Task 2: Mixed-use calculation orchestrator and API

**Files**

- Modify `services/tphcm_land_price_calculator.py`
- Modify `app.py`
- Modify `tests/test_tphcm_land_price_calculator.py`
- Modify `tests/test_tphcm_land_price_tool.py`

**Red**

- Test exact area split within 0.01m² and rejection outside tolerance.
- Test default residential front-strip geometry.
- Test custom residential geometry and mismatch warning.
- Test total equals residential plus agricultural values.
- Test manual agricultural result forces total to `null`.
- API test a Nguyễn Huệ mixed parcel and a commune mixed parcel.
- API test that forged zone and base prices are ignored.
- API test malformed nested objects, unsupported type and invalid position.
- Regression test current single-parcel response.

Run and confirm expected failures:

```powershell
& $py -X utf8 -m pytest `
  tests\test_tphcm_land_price_calculator.py `
  tests\test_tphcm_land_price_tool.py -q
```

**Green**

- Add `calculate_mixed_land_price(...)`.
- Reuse `calculate_land_price(...)` only for the residential portion.
- Derive default residential depth from its legal area and parcel frontage.
- Validate nested payloads and enums at the Flask boundary.
- Resolve row, area and residential base price only on the server.
- Preserve the existing response for `parcel_mode=single` or omitted mode.

Run the same tests and confirm green.

## Task 3: Accessible mixed-use form shell

**Files**

- Modify `templates/tphcm_land_price_tool.html`
- Modify `static/css/tphcm_land_price_tool.css`
- Modify `tests/test_tphcm_land_price_tool.py`

**Red**

- Assert the mixed-mode control, area fields, land-type select, position
  controls, special-context controls and residential-geometry `<details>`.
- Assert associated labels, helper/error IDs and `aria-live`.
- Assert asset version is bumped.

Run the focused rendered-page test and confirm failure.

**Green**

- Add integrated `Thửa có nhiều loại đất` switch.
- Reveal mixed fields progressively and keep single mode unchanged.
- Use fieldset/legend for agricultural position and Article 5.8 context.
- Add result styles for residential/agricultural/total hierarchy.
- Keep controls at least 44px and mobile font at least 16px.
- Collapse grids/tables without horizontal overflow at 375/390px.
- Respect `prefers-reduced-motion`.

Run rendered-page tests and confirm green.

## Task 4: Browser behavior and safe rendering

**Files**

- Modify `static/js/tphcm_land_price_calculator.js`
- Modify `tests/js/test_tphcm_land_price_calculator.js`
- Modify `tests/test_tphcm_land_price_tool.py`

**Red**

- Test mixed payload shape and absence of client-provided zone/base prices.
- Test single payload remains unchanged.
- Test mixed result labels, legal formula, floor/cap and total.
- Test manual-result handling and HTML escaping.
- Static-test non-sensitive analytics names/payloads.

Run and confirm failure:

```powershell
node tests\js\test_tphcm_land_price_calculator.js
```

**Green**

- Extend `buildPayload` and `renderResult`.
- Toggle, enable and clear conditional fields without stale values.
- Map new server field errors to the first relevant input.
- Add blur validation for the area split; backend remains authoritative.
- Add `land_price_mixed_mode_toggle` and safe enum-only success dimensions.
- Preserve loading, focus and mobile scroll behavior.

Run Node syntax/test and Python static analytics tests.

## Task 5: Verification and release

**Files**

- Modify only scoped files required by a failing test or browser defect.

**Automated gate**

```powershell
& $py -X utf8 -m py_compile `
  app.py `
  services\tphcm_land_prices.py `
  services\tphcm_land_price_calculator.py `
  services\tphcm_agricultural_land_prices.py
node --check static\js\tphcm_land_price_tool.js
node --check static\js\tphcm_land_price_calculator.js
node tests\js\test_tphcm_land_price_calculator.js
& $py -X utf8 -m pytest `
  tests\test_tphcm_agricultural_land_prices.py `
  tests\test_tphcm_land_price_calculator.py `
  tests\test_tphcm_land_price_data.py `
  tests\test_tphcm_land_price_tool.py `
  tests\test_public_seo.py `
  tests\test_public_content_hubs.py -q
git diff --check
```

**Security review**

- Confirm all nested input is allowlisted and bounded.
- Confirm row price and zone are server-derived.
- Confirm errors omit stack traces and UI escapes every server string.
- Confirm analytics contains no location, dimensions, row key or price.
- Scan staged diff for secrets.

**Browser smoke**

- Desktop 1280px: single mode regression, mixed ward calculation, manual
  agricultural type and visible formula.
- Mobile 375px and 390px: no horizontal overflow, 44px controls, correct
  conditional fields, focus after validation and success.
- Console and network clean.

**Release**

- Review `origin/main...HEAD` and stage only scoped paths.
- Push feature branch, integrate to `main` using the established release flow,
  then run `scripts/deploy_production.ps1`.
- Verify production commit/service, live API for ward and commune cases,
  forged-field resistance, source link, browser desktop/mobile and analytics.
