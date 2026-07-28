# TP.HCM Land-Position Calculator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend `/bang-gia-dat-tphcm` so a user can select a road-price row, enter parcel dimensions and access conditions, then receive an explainable position-adjusted average unit price and total value for all three non-agricultural land types.

**Architecture:** Keep the official road table as the only base-price source. A focused Python calculation service owns all legal factors and depth-band math; the Flask endpoint resolves a server-generated `row_key` before calling it. A separate browser module owns the calculator panel while the existing lookup module continues to own search, ranking and pagination.

**Tech Stack:** Python 3.12, Flask 3.1, Decimal, vanilla JavaScript, CSS, pytest, Node built-ins, browser smoke testing.

## Global Constraints

- The official source of truth is Nghị quyết 87/2025/NQ-HĐND and its Appendix I, not the draft PDF.
- The client never supplies or overrides a position-1 base price.
- The current JSON source unit remains `1.000 đồng/m²`; calculation output uses whole VND.
- Position factors are exactly `1.00`, `0.50`, `0.40`, `0.32`.
- Dirt-alley factor is `0.80`; non-frontage walking distance at least `100m` applies `0.90`.
- Residential depth bands are `1.00` through `5R`, `0.80` through `8R`, then `0.70`.
- Commerce/service and non-agricultural production bands are `1.00` through `2R`, `0.60` through `4R`, then `0.40`.
- Special modes are mutually exclusive: `multiple_frontages=1.10` and `special_seventy_percent=0.70`.
- Legal area more than 10% different from `frontage × depth` produces a warning but does not block calculation.
- The endpoint remains guest-accessible and analytics never include query, address, dimensions or calculated values.
- Preserve unrelated dirty work and stage only the paths named in each task.

---

### Task 1: Deterministic calculation service

**Files:**
- Create: `services/tphcm_land_price_calculator.py`
- Create: `tests/test_tphcm_land_price_calculator.py`

**Interfaces:**
- Produces: `CalculationValidationError(field_errors: dict[str, str])`
- Produces: `resolve_location(location: Mapping[str, object]) -> dict[str, object]`
- Produces: `build_depth_bands(land_area_m2: object, frontage_m: object, depth_m: object, land_type: str) -> list[dict[str, object]]`
- Produces: `calculate_land_price(base_prices_thousand: Mapping[str, object], *, land_area_m2: object, frontage_m: object, depth_m: object, location: Mapping[str, object]) -> dict[str, object]`

- [ ] **Step 1: Write failing position-factor tests**

Create `tests/test_tphcm_land_price_calculator.py` with hand-derived boundary values:

```python
from decimal import Decimal

import pytest

from services.tphcm_land_price_calculator import (
    CalculationValidationError,
    build_depth_bands,
    calculate_land_price,
    resolve_location,
)


@pytest.mark.parametrize(
    ("width", "position", "factor"),
    [
        ("2.99", 4, Decimal("0.32")),
        ("3", 3, Decimal("0.40")),
        ("4.99", 3, Decimal("0.40")),
        ("5", 2, Decimal("0.50")),
    ],
)
def test_alley_width_boundaries_select_official_position(width, position, factor):
    result = resolve_location({
        "mode": "standard",
        "access": "alley",
        "alley_min_width_m": width,
        "alley_surface": "paved",
        "distance_to_named_road_m": "20",
    })

    assert result["position"] == position
    assert result["factor"] == factor


def test_dirt_and_one_hundred_meter_factors_are_explainable():
    result = resolve_location({
        "mode": "standard",
        "access": "alley",
        "alley_min_width_m": "4",
        "alley_surface": "dirt",
        "distance_to_named_road_m": "100",
    })

    assert result["position"] == 3
    assert result["factor"] == Decimal("0.288")
    assert result["breakdown"] == [
        {"code": "position_3", "label": "Vị trí 3", "factor": Decimal("0.40")},
        {"code": "dirt_alley", "label": "Hẻm đất", "factor": Decimal("0.80")},
        {"code": "distance_100m", "label": "Cách đường có tên từ 100m", "factor": Decimal("0.90")},
    ]


def test_distance_below_one_hundred_meters_is_not_discounted():
    result = resolve_location({
        "mode": "standard",
        "access": "alley",
        "alley_min_width_m": "4",
        "alley_surface": "paved",
        "distance_to_named_road_m": "99.99",
    })

    assert result["factor"] == Decimal("0.40")


@pytest.mark.parametrize(
    ("mode", "factor"),
    [
        ("multiple_frontages", Decimal("1.10")),
        ("special_seventy_percent", Decimal("0.70")),
    ],
)
def test_special_mode_replaces_standard_alley_factors(mode, factor):
    result = resolve_location({
        "mode": mode,
        "access": "alley",
        "alley_min_width_m": "2",
        "alley_surface": "dirt",
        "distance_to_named_road_m": "200",
    })

    assert result["factor"] == factor
    assert len(result["breakdown"]) == 1
```

- [ ] **Step 2: Run the position tests and verify RED**

Run:

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $py -X utf8 -m pytest tests\test_tphcm_land_price_calculator.py -q
```

Expected: collection fails because `services.tphcm_land_price_calculator` does not exist.

- [ ] **Step 3: Implement validation and position resolution**

Create `services/tphcm_land_price_calculator.py` with:

```python
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Mapping


LAND_TYPES = ("residential", "commerce_service", "production_business")


class CalculationValidationError(ValueError):
    def __init__(self, field_errors: dict[str, str]):
        super().__init__("Invalid land-price calculation input")
        self.field_errors = field_errors


def _positive_decimal(value: object, field: str, *, maximum: str) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise CalculationValidationError({field: "Giá trị phải là một số hợp lệ."})
    if not number.is_finite() or number <= 0:
        raise CalculationValidationError({field: "Giá trị phải lớn hơn 0."})
    if number > Decimal(maximum):
        raise CalculationValidationError({field: f"Giá trị không được vượt quá {maximum}."})
    return number


def _non_negative_decimal(value: object, field: str, *, maximum: str) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise CalculationValidationError({field: "Giá trị phải là một số hợp lệ."})
    if not number.is_finite() or number < 0:
        raise CalculationValidationError({field: "Giá trị không được âm."})
    if number > Decimal(maximum):
        raise CalculationValidationError({field: f"Giá trị không được vượt quá {maximum}."})
    return number


def resolve_location(location: Mapping[str, object]) -> dict[str, object]:
    mode = str(location.get("mode") or "standard")
    if mode == "multiple_frontages":
        return {
            "position": 1,
            "label": "Từ hai mặt tiền trở lên",
            "factor": Decimal("1.10"),
            "breakdown": [{"code": mode, "label": "Từ hai mặt tiền trở lên", "factor": Decimal("1.10")}],
        }
    if mode == "special_seventy_percent":
        return {
            "position": None,
            "label": "Trường hợp áp dụng 70%",
            "factor": Decimal("0.70"),
            "breakdown": [{"code": mode, "label": "Trường hợp đặc biệt 70%", "factor": Decimal("0.70")}],
        }
    if mode != "standard":
        raise CalculationValidationError({"location.mode": "Chế độ vị trí không hợp lệ."})

    access = str(location.get("access") or "")
    if access == "frontage":
        return {
            "position": 1,
            "label": "Vị trí 1",
            "factor": Decimal("1.00"),
            "breakdown": [{"code": "position_1", "label": "Vị trí 1", "factor": Decimal("1.00")}],
        }
    if access != "alley":
        raise CalculationValidationError({"location.access": "Hãy chọn mặt tiền hoặc trong hẻm."})

    width = _positive_decimal(
        location.get("alley_min_width_m"),
        "location.alley_min_width_m",
        maximum="100",
    )
    distance = _non_negative_decimal(
        location.get("distance_to_named_road_m"),
        "location.distance_to_named_road_m",
        maximum="10000",
    )
    surface = str(location.get("alley_surface") or "")
    if surface not in {"paved", "dirt"}:
        raise CalculationValidationError({"location.alley_surface": "Hãy chọn mặt hẻm."})

    if width >= Decimal("5"):
        position, factor = 2, Decimal("0.50")
    elif width >= Decimal("3"):
        position, factor = 3, Decimal("0.40")
    else:
        position, factor = 4, Decimal("0.32")

    breakdown = [{"code": f"position_{position}", "label": f"Vị trí {position}", "factor": factor}]
    if surface == "dirt":
        factor *= Decimal("0.80")
        breakdown.append({"code": "dirt_alley", "label": "Hẻm đất", "factor": Decimal("0.80")})
    if distance >= Decimal("100"):
        factor *= Decimal("0.90")
        breakdown.append({
            "code": "distance_100m",
            "label": "Cách đường có tên từ 100m",
            "factor": Decimal("0.90"),
        })

    return {
        "position": position,
        "label": f"Vị trí {position}",
        "factor": factor,
        "breakdown": breakdown,
    }
```

- [ ] **Step 4: Run position tests and verify GREEN**

Run the Task 1 test file. Expected: all position-factor tests pass.

- [ ] **Step 5: Write failing depth-band and total-value tests**

Append:

```python
def test_residential_depth_bands_use_five_and_eight_frontage_multiples():
    bands = build_depth_bands("500", "5", "100", "residential")

    assert bands == [
        {"code": "front", "area_m2": Decimal("125"), "factor": Decimal("1.00")},
        {"code": "middle", "area_m2": Decimal("75"), "factor": Decimal("0.80")},
        {"code": "rear", "area_m2": Decimal("300"), "factor": Decimal("0.70")},
    ]


def test_commerce_depth_bands_use_two_and_four_frontage_multiples():
    bands = build_depth_bands("500", "5", "100", "commerce_service")

    assert bands == [
        {"code": "front", "area_m2": Decimal("50"), "factor": Decimal("1.00")},
        {"code": "middle", "area_m2": Decimal("50"), "factor": Decimal("0.60")},
        {"code": "rear", "area_m2": Decimal("400"), "factor": Decimal("0.40")},
    ]


def test_calculation_returns_average_and_total_for_each_land_type():
    result = calculate_land_price(
        {
            "residential": 10_000,
            "commerce_service": 6_000,
            "production_business": 4_000,
        },
        land_area_m2="100",
        frontage_m="5",
        depth_m="20",
        location={"mode": "standard", "access": "frontage"},
    )

    assert result["values"]["residential"]["average_unit_price"] == 10_000_000
    assert result["values"]["residential"]["total_value"] == 1_000_000_000
    assert result["values"]["commerce_service"]["average_unit_price"] == 4_800_000
    assert result["values"]["commerce_service"]["total_value"] == 480_000_000
    assert result["values"]["production_business"]["average_unit_price"] == 3_200_000
    assert result["values"]["production_business"]["total_value"] == 320_000_000


def test_geometry_mismatch_over_ten_percent_adds_warning():
    result = calculate_land_price(
        {"residential": 10_000, "commerce_service": 6_000, "production_business": 4_000},
        land_area_m2="130",
        frontage_m="5",
        depth_m="20",
        location={"mode": "standard", "access": "frontage"},
    )

    assert result["geometry"]["mismatch_warning"] is True
    assert result["warnings"][0]["code"] == "geometry_mismatch"
    assert sum(
        band["area_m2"]
        for band in result["values"]["residential"]["bands"]
    ) == Decimal("130")
```

- [ ] **Step 6: Run the new tests and verify RED**

Expected: `build_depth_bands` and `calculate_land_price` are missing.

- [ ] **Step 7: Implement depth bands and totals**

Use Decimal throughout. Split depth into literal front/middle/rear lengths,
scale each length by `legal_area / depth`, multiply the base thousand-dong
price by 1,000, the location factor and the band factor, and round whole VND
with `ROUND_HALF_UP`.

The returned dictionaries must preserve Decimal values internally:

```python
def build_depth_bands(land_area_m2, frontage_m, depth_m, land_type):
    area = _positive_decimal(land_area_m2, "land_area_m2", maximum="1000000")
    frontage = _positive_decimal(frontage_m, "frontage_m", maximum="10000")
    depth = _positive_decimal(depth_m, "depth_m", maximum="10000")
    if land_type == "residential":
        first_end, second_end = frontage * 5, frontage * 8
        factors = (Decimal("1.00"), Decimal("0.80"), Decimal("0.70"))
    elif land_type in {"commerce_service", "production_business"}:
        first_end, second_end = frontage * 2, frontage * 4
        factors = (Decimal("1.00"), Decimal("0.60"), Decimal("0.40"))
    else:
        raise ValueError(f"Unsupported land type: {land_type}")

    lengths = (
        min(depth, first_end),
        max(Decimal("0"), min(depth, second_end) - first_end),
        max(Decimal("0"), depth - second_end),
    )
    names = ("front", "middle", "rear")
    return [
        {"code": name, "area_m2": area * length / depth, "factor": factor}
        for name, length, factor in zip(names, lengths, factors)
        if length > 0
    ]
```

`calculate_land_price` must validate all three geometry fields, call
`resolve_location`, calculate all three land types, and add a
`geometry_mismatch` warning when
`abs(legal_area - frontage * depth) / (frontage * depth) > Decimal("0.10")`.

- [ ] **Step 8: Run Task 1 tests and verify GREEN**

Run:

```powershell
& $py -X utf8 -m pytest tests\test_tphcm_land_price_calculator.py -q
```

Expected: all Task 1 tests pass.

- [ ] **Step 9: Commit Task 1**

```powershell
git add -- services/tphcm_land_price_calculator.py tests/test_tphcm_land_price_calculator.py
git commit -m "Add deterministic land position calculator"
```

---

### Task 2: Stable row keys and guest calculation API

**Files:**
- Modify: `services/tphcm_land_prices.py`
- Modify: `app.py:1519-1555`
- Modify: `tests/test_tphcm_land_price_tool.py`

**Interfaces:**
- Consumes: `calculate_land_price(...)` and `CalculationValidationError`
- Produces: `land_price_row_key(row: Mapping[str, object]) -> str`
- Produces: `find_land_price_row(rows: Iterable[dict], row_key: str) -> dict | None`
- Produces: `POST /api/tphcm-land-prices/calculate`

- [ ] **Step 1: Write failing row-key and API tests**

Add tests that exercise the real Flask boundary:

```python
def test_search_returns_unique_stable_row_keys():
    import app as radar_app

    client = radar_app.app.test_client()
    first = client.get(
        "/api/tphcm-land-prices?q=nguyen%20hue&area=PH%C6%AF%E1%BB%9CNG%20S%C3%80I%20G%C3%92N"
    ).get_json()
    second = client.get(
        "/api/tphcm-land-prices?q=nguyen%20hue&area=PH%C6%AF%E1%BB%9CNG%20S%C3%80I%20G%C3%92N"
    ).get_json()

    first_keys = [item["row_key"] for item in first["items"]]
    assert first_keys == [item["row_key"] for item in second["items"]]
    assert len(first_keys) == len(set(first_keys))


def test_guest_calculation_uses_server_side_base_prices():
    import app as radar_app

    client = radar_app.app.test_client()
    row = client.get(
        "/api/tphcm-land-prices?q=nguyen%20hue&area=PH%C6%AF%E1%BB%9CNG%20S%C3%80I%20G%C3%92N&limit=1"
    ).get_json()["items"][0]

    response = client.post(
        "/api/tphcm-land-prices/calculate",
        json={
            "row_key": row["row_key"],
            "base_prices": {"residential": 1},
            "land_area_m2": 100,
            "frontage_m": 5,
            "depth_m": 20,
            "location": {"mode": "standard", "access": "frontage"},
        },
    )
    data = response.get_json()

    assert response.status_code == 200
    assert data["ok"] is True
    assert data["values"]["residential"]["base_unit_price"] == 687_200_000
    assert data["row"]["street"] == "NGUYỄN HUỆ"


def test_calculation_returns_field_errors_and_missing_row():
    import app as radar_app

    client = radar_app.app.test_client()
    missing = client.post(
        "/api/tphcm-land-prices/calculate",
        json={
            "row_key": "missing",
            "land_area_m2": 100,
            "frontage_m": 5,
            "depth_m": 20,
            "location": {"mode": "standard", "access": "frontage"},
        },
    )
    invalid = client.post(
        "/api/tphcm-land-prices/calculate",
        json={
            "row_key": client.get(
                "/api/tphcm-land-prices?q=nguyen%20hue&limit=1"
            ).get_json()["items"][0]["row_key"],
            "land_area_m2": 0,
            "frontage_m": 5,
            "depth_m": 20,
            "location": {"mode": "standard", "access": "frontage"},
        },
    )

    assert missing.status_code == 404
    assert missing.get_json()["error"] == "row_not_found"
    assert invalid.status_code == 400
    assert "land_area_m2" in invalid.get_json()["field_errors"]
```

- [ ] **Step 2: Run the API tests and verify RED**

Expected: search items do not contain `row_key` and POST returns 404.

- [ ] **Step 3: Implement stable keys**

In `services/tphcm_land_prices.py`:

```python
import hashlib
from collections.abc import Iterable, Mapping


def land_price_row_key(row: Mapping[str, object]) -> str:
    identity = "\x1f".join(str(row.get(field) or "") for field in IDENTITY_FIELDS)
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]


def find_land_price_row(rows: Iterable[dict], row_key: str) -> dict | None:
    if not row_key:
        return None
    return next((row for row in rows if land_price_row_key(row) == row_key), None)
```

When copying a matched item, add `item["row_key"] = land_price_row_key(row)`.

- [ ] **Step 4: Implement POST API and JSON serialization**

Import the key lookup and calculator in `app.py`. Add a recursive serializer
that converts Decimal to int when integral and float otherwise, then add:

```python
@app.post("/api/tphcm-land-prices/calculate")
def api_tphcm_land_price_calculate():
    payload = request.get_json(silent=True) or {}
    data = _load_tphcm_land_price_data()
    row = find_land_price_row(data.get("rows", []), str(payload.get("row_key") or ""))
    if row is None:
        return jsonify({"ok": False, "error": "row_not_found"}), 404
    try:
        result = calculate_land_price(
            {
                "residential": row.get("residential"),
                "commerce_service": row.get("commerce_service"),
                "production_business": row.get("production_business"),
            },
            land_area_m2=payload.get("land_area_m2"),
            frontage_m=payload.get("frontage_m"),
            depth_m=payload.get("depth_m"),
            location=payload.get("location") or {},
        )
    except CalculationValidationError as exc:
        return jsonify({
            "ok": False,
            "error": "validation_error",
            "field_errors": exc.field_errors,
        }), 400

    return jsonify(_json_ready({
        "ok": True,
        "row": {
            "row_key": land_price_row_key(row),
            "area": row.get("area"),
            "street": row.get("street"),
            "from": row.get("from"),
            "to": row.get("to"),
        },
        **result,
        "source_url": data.get("source_url"),
        "data_as_of": data.get("data_as_of"),
    }))
```

- [ ] **Step 5: Run API and existing lookup tests**

Run:

```powershell
& $py -X utf8 -m pytest tests\test_tphcm_land_price_calculator.py tests\test_tphcm_land_price_tool.py -q
```

Expected: all tests pass; existing result ranking and pagination remain green.

- [ ] **Step 6: Commit Task 2**

```powershell
git add -- app.py services/tphcm_land_prices.py tests/test_tphcm_land_price_tool.py
git commit -m "Add guest land position calculation API"
```

---

### Task 3: Accessible calculator panel and responsive result design

**Files:**
- Modify: `templates/tphcm_land_price_tool.html`
- Modify: `static/css/tphcm_land_price_tool.css`
- Modify: `tests/test_tphcm_land_price_tool.py`

**Interfaces:**
- Produces DOM root `#landPriceCalculator`
- Produces form `#landPriceCalculatorForm`
- Produces hidden key input `#landPriceCalculatorRowKey`
- Produces result container `#landPriceCalculatorResult`
- Produces field-error nodes using `data-calculator-error="<field>"`

- [ ] **Step 1: Write a failing rendered-page structure test**

Add a test against the real Flask-rendered page:

```python
def test_land_price_page_renders_accessible_position_calculator_shell():
    import app as radar_app

    html = radar_app.app.test_client().get("/bang-gia-dat-tphcm").get_data(as_text=True)

    assert 'id="landPriceCalculator"' in html
    assert 'id="landPriceCalculatorForm"' in html
    assert 'id="landPriceCalculatorRowKey"' in html
    assert '<label for="landPriceLandArea">' in html
    assert '<label for="landPriceFrontage">' in html
    assert '<label for="landPriceDepth">' in html
    assert 'name="access"' in html
    assert 'id="landPriceAlleyFields"' in html
    assert '<details class="land-price-advanced">' in html
    assert 'id="landPriceCalculatorResult"' in html
    assert 'aria-live="polite"' in html
```

- [ ] **Step 2: Run the page test and verify RED**

Expected: calculator IDs are absent.

- [ ] **Step 3: Add the calculator shell**

Insert the panel after `#landPricePagination` and before result actions.
Keep it hidden until a road row is selected. The common section must contain:

- selected road/segment summary;
- `land_area_m2`, `frontage_m`, `depth_m`;
- access radio buttons for `frontage` and `alley`;
- conditional alley inputs for minimum width, surface and walking distance;
- a submit button with loading label and spinner;
- field-specific error nodes.

The advanced `<details>` contains mutually exclusive mode radios:

- standard;
- multiple frontages with copy requiring the highest-priced road;
- special 70% with the exact covered categories;
- a non-calculable-cases note for irregular geometry and no-access parcels.

Load the new browser module before `tphcm_land_price_tool.js` and bump both
asset versions to `tphcm-land-position-20260728`.

- [ ] **Step 4: Add responsive CSS**

Add focused classes:

```css
.land-price-calculate-button { min-height: 44px; }
.land-price-calculator[hidden] { display: none !important; }
.land-price-calculator-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }
.land-price-alley-fields { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }
.calculation-summary-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }
.calculation-band-table { width: 100%; border-collapse: collapse; }
.calculator-warning { border-left: 3px solid #b7791f; background: #fff8e6; }
```

At `max-width: 700px`, collapse all grids to one column, render band rows as
cards, keep every input/button at least 44px high and font size 16px.

- [ ] **Step 5: Run page tests and syntax checks**

Run:

```powershell
& $py -X utf8 -m pytest tests\test_tphcm_land_price_tool.py -q
```

Expected: calculator shell test and all existing page/API tests pass.

- [ ] **Step 6: Commit Task 3**

```powershell
git add -- templates/tphcm_land_price_tool.html static/css/tphcm_land_price_tool.css tests/test_tphcm_land_price_tool.py
git commit -m "Add land position calculator interface"
```

---

### Task 4: Browser calculator module and lookup integration

**Files:**
- Create: `static/js/tphcm_land_price_calculator.js`
- Create: `tests/js/test_tphcm_land_price_calculator.js`
- Modify: `static/js/tphcm_land_price_tool.js`

**Interfaces:**
- Consumes search item fields: `row_key`, `area`, `street`, `from`, `to`
- Produces global `window.RadarLandPriceCalculator`
- Produces `buildPayload(values: object) -> object`
- Produces `renderResult(data: object) -> string`
- Produces `openForRow(row: object) -> void`

- [ ] **Step 1: Write failing pure JavaScript behavior tests**

Create `tests/js/test_tphcm_land_price_calculator.js` using `node:assert`,
`node:fs` and `node:vm`, matching the repository's current JS test pattern:

```javascript
'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..', '..');
const source = fs.readFileSync(
  path.join(root, 'static', 'js', 'tphcm_land_price_calculator.js'),
  'utf8'
);
const window = {};
vm.runInNewContext(source, { window, Intl, Number, String, Math });

const calculator = window.RadarLandPriceCalculator;
assert.ok(calculator);

assert.deepEqual(
  JSON.parse(JSON.stringify(calculator.buildPayload({
    rowKey: 'row-1',
    landArea: '100',
    frontage: '5',
    depth: '20',
    mode: 'standard',
    access: 'alley',
    alleyWidth: '4',
    alleySurface: 'dirt',
    roadDistance: '100',
  }))),
  {
    row_key: 'row-1',
    land_area_m2: '100',
    frontage_m: '5',
    depth_m: '20',
    location: {
      mode: 'standard',
      access: 'alley',
      alley_min_width_m: '4',
      alley_surface: 'dirt',
      distance_to_named_road_m: '100',
    },
  }
);

const html = calculator.renderResult({
  position: {
    label: 'Vị trí 3 <script>alert(1)</script>',
    factor: 0.288,
    breakdown: [{ label: 'Hẻm đất', factor: 0.8 }],
  },
  geometry: { legal_area_m2: 100, mismatch_warning: true },
  values: {
    residential: {
      base_unit_price: 10_000_000,
      average_unit_price: 2_880_000,
      total_value: 288_000_000,
      bands: [{ code: 'front', area_m2: 100, factor: 1, unit_price: 2_880_000 }],
    },
  },
  warnings: [{ code: 'geometry_mismatch', message: 'Cần đối chiếu hình thể thửa.' }],
});

assert.match(html, /2,88 triệu\/m²/);
assert.match(html, /288 triệu/);
assert.match(html, /Cần đối chiếu hình thể thửa/);
assert.doesNotMatch(html, /<script>/);
assert.match(html, /&lt;script&gt;/);
```

- [ ] **Step 2: Run Node test and verify RED**

Run:

```powershell
node tests\js\test_tphcm_land_price_calculator.js
```

Expected: `ENOENT` because the browser module does not exist.

- [ ] **Step 3: Implement pure payload and result helpers**

Create an IIFE that exposes:

```javascript
window.RadarLandPriceCalculator = {
  buildPayload,
  renderResult,
  openForRow,
};
```

`renderResult` must:

- HTML-escape all server strings;
- format unit prices in triệu/m²;
- format totals using triệu/tỷ labels;
- show factor breakdown;
- show the three land-type summaries;
- render each depth band;
- render every warning;
- never insert address or dimension values into analytics.

- [ ] **Step 4: Add real DOM integration**

On DOM ready:

- cache the calculator form, panel, selected-row summary, result and field
  errors;
- listen for `[data-calculate-row]` clicks by event delegation;
- populate only `row_key` and selected road display;
- toggle hẻm fields from the access selection;
- disable standard alley fields when a special mode is selected;
- POST JSON to `/api/tphcm-land-prices/calculate`;
- map `field_errors` to `data-calculator-error` nodes;
- replace loading/error/result states without overlap;
- focus and scroll to the result on mobile;
- emit only the analytics events in the spec.

- [ ] **Step 5: Integrate result buttons into lookup rendering**

In both desktop row and mobile card templates produced by
`tphcm_land_price_tool.js`, add:

```html
<button
  type="button"
  class="land-price-calculate-button"
  data-calculate-row
  data-row-key="..."
  data-area="..."
  data-street="..."
  data-from="..."
  data-to="..."
>Tính theo vị trí</button>
```

Escape all data attributes through the existing `esc` function. Clicking must
not change pagination or trigger a new search.

- [ ] **Step 6: Run JS and Python regression tests**

Run:

```powershell
node --check static\js\tphcm_land_price_calculator.js
node --check static\js\tphcm_land_price_tool.js
node tests\js\test_tphcm_land_price_calculator.js
& $py -X utf8 -m pytest tests\test_tphcm_land_price_calculator.py tests\test_tphcm_land_price_tool.py -q
```

Expected: all commands exit zero.

- [ ] **Step 7: Commit Task 4**

```powershell
git add -- static/js/tphcm_land_price_calculator.js static/js/tphcm_land_price_tool.js tests/js/test_tphcm_land_price_calculator.js
git commit -m "Connect land position calculator UX"
```

---

### Task 5: End-to-end verification and production release

**Files:**
- Modify only if a failing test or browser defect requires a scoped fix.

**Interfaces:**
- Consumes all Task 1-4 deliverables.
- Produces a deployed production commit with public verification evidence.

- [ ] **Step 1: Run the scoped automated gate**

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $py -X utf8 -m py_compile app.py services\tphcm_land_prices.py services\tphcm_land_price_calculator.py
node --check static\js\tphcm_land_price_tool.js
node --check static\js\tphcm_land_price_calculator.js
node tests\js\test_tphcm_land_price_calculator.js
& $py -X utf8 -m pytest `
  tests\test_tphcm_land_price_calculator.py `
  tests\test_tphcm_land_price_data.py `
  tests\test_tphcm_land_price_tool.py `
  tests\test_public_seo.py `
  tests\test_public_content_hubs.py -q
git diff --check
```

Expected: every command exits zero. The repository-wide pytest caveat remains
the pre-existing Windows/VPS-path and missing-worktree-`DATABASE_URL` issue; do
not expand scope to those tests.

- [ ] **Step 2: Run local desktop browser smoke**

At 1280×720:

1. Open `/bang-gia-dat-tphcm?q=nguyen+hue&area=PHƯỜNG+SÀI+GÒN`.
2. Confirm exact road remains first.
3. Click `Tính theo vị trí`.
4. Enter 100m², frontage 5m, depth 20m, paved 4m alley, distance 100m.
5. Confirm position 3, total location factor 0.36 and three result summaries.
6. Confirm a special mode hides/disables alley inputs.
7. Confirm browser console has no errors.

- [ ] **Step 3: Run local mobile browser smoke**

At 390×844:

1. Confirm lookup uses cards and no horizontal overflow.
2. Open the calculator from a card.
3. Confirm all inputs are at least 44px high with 16px text.
4. Submit and confirm focus moves to the result.
5. Confirm band rows render as cards and the total remains readable.

- [ ] **Step 4: Review the final diff and staged scope**

```powershell
git status --short
git diff --stat origin/main...HEAD
git diff --check origin/main...HEAD
```

Verify only calculator/spec/plan paths are included after the prior deployed
commit. Preserve all dirty files in the main workspace.

- [ ] **Step 5: Push and deploy**

Push the feature branch and fast-forward `origin/main` only if remote main still
matches the known base. Run the standard deploy first. If the VPS remote still
fails with `github.com-radarbds`, use the repository's validated git-bundle
fallback and preserve production runtime data.

- [ ] **Step 6: Verify production**

On `https://radarbds.vn` confirm:

- production commit equals the pushed commit and service is active;
- search API returns `row_key`;
- calculation API ignores a forged base price;
- alley-width boundaries, 100m factor and a depth-band sample match literals;
- desktop and 390px mobile flows complete;
- official source link remains Công báo TP.HCM;
- browser console is clean;
- analytics handlers are loaded without exposing address or dimensions.
