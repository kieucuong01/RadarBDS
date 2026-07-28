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

assert.deepEqual(
  JSON.parse(JSON.stringify(calculator.buildPayload({
    rowKey: 'row-mixed',
    landArea: '500',
    frontage: '10',
    depth: '50',
    mode: 'standard',
    access: 'frontage',
    mixedMode: true,
    residentialArea: '100',
    agriculturalArea: '400',
    agriculturalType: 'perennial',
    agriculturalPosition: '1',
    inResidentialArea: false,
    sameParcelHasHouse: true,
    residentialUseCustom: true,
    residentialFrontage: '5',
    residentialDepth: '20',
  }))),
  {
    row_key: 'row-mixed',
    parcel_mode: 'mixed',
    land_area_m2: '500',
    frontage_m: '10',
    depth_m: '50',
    residential_area_m2: '100',
    agricultural_area_m2: '400',
    residential_geometry: {
      use_custom: true,
      frontage_m: '5',
      depth_m: '20',
    },
    location: {
      mode: 'standard',
      access: 'frontage',
    },
    agricultural: {
      land_type: 'perennial',
      position: '1',
      in_residential_area: false,
      same_parcel_has_house: true,
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

const mixedHtml = calculator.renderResult({
  parcel_mode: 'mixed',
  position: { label: 'Vị trí 1', factor: 1, breakdown: [] },
  geometry: { legal_area_m2: 500 },
  mixed_use: {
    total_area_m2: 500,
    residential: {
      area_m2: 100,
      assumption: 'front_strip',
      base_unit_price: 687_200_000,
      average_unit_price: 687_200_000,
      total_value: 68_720_000_000,
      bands: [{
        code: 'front',
        area_m2: 100,
        factor: 1,
        unit_price: 687_200_000,
        subtotal: 68_720_000_000,
      }],
    },
    agricultural: {
      area_m2: 400,
      land_type: 'perennial',
      land_type_label: 'Đất trồng cây lâu năm',
      zone: 1,
      position: 1,
      pricing_mode: 'article_5_8',
      normal_unit_price: 1_440_000,
      special_unit_price: 68_720_000,
      unit_price: 68_720_000,
      total_value: 27_488_000_000,
      floor_applied: false,
      cap_applied: false,
      manual_review_required: false,
      formula: [
        'Áp dụng khoản 8 Điều 5.',
        '<script>alert(1)</script>',
      ],
    },
    total_value: 96_208_000_000,
  },
  warnings: [{
    code: 'residential_front_strip_assumption',
    message: 'Giả định phần đất ở nằm phía trước.',
  }],
});

assert.match(mixedHtml, /Tổng giá trị theo bảng Nhà nước/);
assert.match(mixedHtml, /96,208 tỷ/);
assert.match(mixedHtml, /Đất trồng cây lâu năm/);
assert.match(mixedHtml, /Vùng I/);
assert.match(mixedHtml, /Vị trí 1/);
assert.match(mixedHtml, /Khoản 8 Điều 5/);
assert.match(mixedHtml, /68,72 triệu\/m²/);
assert.match(mixedHtml, /Giả định phần đất ở nằm phía trước/);
assert.doesNotMatch(mixedHtml, /<script>/);
assert.match(mixedHtml, /&lt;script&gt;/);

const manualMixedHtml = calculator.renderResult({
  parcel_mode: 'mixed',
  position: { label: 'Vị trí 1', factor: 1, breakdown: [] },
  geometry: { legal_area_m2: 100 },
  mixed_use: {
    total_area_m2: 100,
    residential: {
      area_m2: 50,
      base_unit_price: 10_000_000,
      average_unit_price: 10_000_000,
      total_value: 500_000_000,
      bands: [],
    },
    agricultural: {
      area_m2: 50,
      land_type_label: 'Đất nông nghiệp khác',
      zone: 3,
      position: 1,
      pricing_mode: 'manual_review',
      unit_price: null,
      total_value: null,
      manual_review_required: true,
      formula: ['Cần đối chiếu loại đất liền kề.'],
    },
    total_value: null,
  },
  warnings: [],
});

assert.match(manualMixedHtml, /Chưa thể tính tổng/);
assert.match(manualMixedHtml, /Cần đối chiếu loại đất liền kề/);
