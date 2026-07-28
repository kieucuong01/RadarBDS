'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..', '..');
const source = fs.readFileSync(
  path.join(root, 'static', 'js', 'valuation_comparable_card.js'),
  'utf8'
);
const window = {};
vm.runInNewContext(source, { window, Intl, Number, String, Math });

const renderer = window.RadarValuationComparableCard;
assert.ok(renderer, 'renderer must be exposed on window');

const comparable = {
  id: 42,
  detail_href: '/listing/42',
  title: 'Lô đẹp <script>alert(1)</script>',
  primary_img: '/static/data/images/thumbs/42.webp',
  image_count: 3,
  price_ty: 1.8,
  price_label: '1,8 tỷ',
  actual_ppm2: 18,
  fair_ppm2: 20,
  mos_pct: 10,
  mos_pct_display: 10,
  area_m2: 100,
  frontage_m: 5,
  depth_m: 20,
  ward: 'Phú Mỹ',
  prop_type: 'dat_nen',
  prop_type_label: 'Đất nền',
  road_tier: 2,
  road_label: 'Đường nhựa 6m',
  street_label: 'Đường DX 01',
  tho_cu_m2: 100,
  tho_cu_label: 'TC 100 m²',
  has_so: 'Có sổ',
  source: 'facebook',
  days_ago: 2,
  price_dropped: true,
  drop_pct: 5,
  source_quality_flags: 'low_segment_confidence',
  url: 'https://facebook.example/private',
  contact_phone: '0909123456',
};

const html = renderer.renderCard(comparable, 0);
assert.match(html, /<a[^>]+class="[^"]*scard/);
assert.match(html, /href="\/listing\/42"/);
assert.match(html, /data-comparable-position="1"/);
assert.match(html, /sc-img-wrap/);
assert.match(html, /mos-badge/);
assert.match(html, /price-container/);
assert.match(html, /meta-chip/);
assert.match(html, /&lt;script&gt;/);
assert.doesNotMatch(html, /<script>/);
assert.doesNotMatch(html, /<button/);
assert.doesNotMatch(html, /Ráp mối|>Lưu</);
assert.doesNotMatch(html, /facebook\.example|0909123456/);

assert.equal(renderer.renderCard({ id: 'not-an-id', title: 'bad' }, 0), '');
assert.equal(renderer.renderCard({ title: 'missing id' }, 0), '');

const gridHtml = renderer.renderGrid(
  Array.from({ length: 7 }, (_, index) => ({
    ...comparable,
    id: index + 1,
    detail_href: `/listing/${index + 1}`,
  }))
);
assert.equal((gridHtml.match(/<a\b/g) || []).length, 6);
assert.doesNotMatch(gridHtml, /\/listing\/7"/);

console.log('valuation comparable card renderer: ok');
