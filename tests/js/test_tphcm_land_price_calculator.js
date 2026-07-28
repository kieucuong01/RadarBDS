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
assert.ok(calculator, 'calculator must be exposed on window');

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

assert.deepEqual(
  JSON.parse(JSON.stringify(calculator.buildPayload({
    rowKey: 'row-2',
    landArea: '80',
    frontage: '4',
    depth: '20',
    mode: 'multiple_frontages',
    access: 'alley',
    alleyWidth: '3',
    alleySurface: 'dirt',
    roadDistance: '120',
  }))),
  {
    row_key: 'row-2',
    land_area_m2: '80',
    frontage_m: '4',
    depth_m: '20',
    location: {
      mode: 'multiple_frontages',
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
      bands: [{
        code: 'front',
        area_m2: 100,
        factor: 1,
        unit_price: 2_880_000,
        subtotal: 288_000_000,
      }],
    },
  },
  warnings: [{
    code: 'geometry_mismatch',
    message: 'Cần đối chiếu hình thể thửa.',
  }],
});

assert.match(html, /2,88 triệu\/m²/);
assert.match(html, /288 triệu/);
assert.match(html, /Cần đối chiếu hình thể thửa/);
assert.match(html, /Hẻm đất/);
assert.match(html, /Phần phía trước/);
assert.doesNotMatch(html, /<script>/);
assert.match(html, /&lt;script&gt;/);

const emptyHtml = calculator.renderResult({
  position: { label: 'Vị trí 1', factor: 1, breakdown: [] },
  geometry: { legal_area_m2: 100 },
  values: {
    residential: {
      base_unit_price: null,
      average_unit_price: null,
      total_value: null,
      bands: [],
    },
  },
  warnings: [],
});
assert.match(emptyHtml, /Không áp dụng/);
