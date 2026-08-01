const test = require('node:test');
const assert = require('node:assert/strict');
const vitals = require('../../static/js/main/web_vitals.js');

test('rates approved Core Web Vitals thresholds', () => {
  assert.equal(vitals.rate('LCP', 2500), 'good');
  assert.equal(vitals.rate('LCP', 2501), 'needs-improvement');
  assert.equal(vitals.rate('LCP', 4001), 'poor');
  assert.equal(vitals.rate('INP', 200), 'good');
  assert.equal(vitals.rate('INP', 500), 'needs-improvement');
  assert.equal(vitals.rate('CLS', 0.1), 'good');
  assert.equal(vitals.rate('CLS', 0.26), 'poor');
});

test('rejects unknown metric names', () => {
  assert.equal(vitals.rate('URL', 1), 'unknown');
});
