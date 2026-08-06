'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..', '..');
const source = fs.readFileSync(
  path.join(root, 'static', 'js', 'main', 'filters.js'),
  'utf8'
);

function makeChip(kind, min, max) {
  const classes = new Set(['range-chip']);
  return {
    dataset: { rangeKind: kind, min, max },
    classList: {
      add(name) {
        classes.add(name);
      },
      remove(name) {
        classes.delete(name);
      },
      toggle(name, force) {
        if (force) classes.add(name);
        else classes.delete(name);
      },
      contains(name) {
        return classes.has(name);
      },
    },
    setAttribute(name, value) {
      this[name] = value;
    },
  };
}

const chips = [
  makeChip('price', '', '1'),
  makeChip('price', '1', '2'),
  makeChip('area', '', '150'),
  makeChip('area', '500', ''),
];
const inputs = {
  priceMin: { value: '1' },
  priceMax: { value: '2' },
  areaMin: { value: '0' },
  areaMax: { value: '150' },
};
const document = {
  querySelectorAll(selector) {
    const kindMatch = selector.match(/data-range-kind="([^"]+)"/);
    const activeOnly = selector.includes('.active');
    return chips.filter((chip) => {
      if (kindMatch && chip.dataset.rangeKind !== kindMatch[1]) return false;
      if (activeOnly && !chip.classList.contains('active')) return false;
      return true;
    });
  },
  getElementById(id) {
    return inputs[id] || null;
  },
  addEventListener() {},
};
const context = {
  document,
  window: { RadarFilterRuntime: { canonicalize: (params) => params.toString() } },
  URLSearchParams,
  Array,
  Set,
  String,
  Number,
  clearTimeout() {},
  setTimeout() {},
  console,
};
vm.runInNewContext(source, context);

assert.equal(typeof context.applyRangeParamsFromUrl, 'function');

context.applyRangeParamsFromUrl('area', ['500:']);
assert.deepEqual(context.selectedRangeTokens('area'), ['500:']);
assert.equal(inputs.areaMin.value, '');
assert.equal(inputs.areaMax.value, '');

context.applyRangeParamsFromUrl('price', ['1:2']);
assert.deepEqual(context.selectedRangeTokens('price'), ['1:2']);
assert.equal(inputs.priceMin.value, '');
assert.equal(inputs.priceMax.value, '');

context.applyRangeParamsFromUrl('area', []);
assert.deepEqual(context.selectedRangeTokens('area'), []);

console.log('range filters: ok');
