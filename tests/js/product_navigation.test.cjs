const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

test('discovery switches to signals without losing filters; modified links keep browser behavior', () => {
  const source = fs.readFileSync('static/js/main/core.js', 'utf8');
  const start = source.indexOf("document.addEventListener('click', function (event) {");
  const handler = source.slice(start, source.indexOf("document.addEventListener('keydown'", start));
  for (const modified of [false, true]) {
    let callback, switched, prevented = false;
    const discovery = {open: true};
    const context = {
      document: {addEventListener: (_, cb) => {callback = cb;}, getElementById: () => discovery, querySelectorAll: () => []},
      _sendTrackEvent() {}, switchTab: tab => {switched = tab;},
    };
    vm.runInNewContext(handler, context);
    callback({button: 0, ctrlKey: modified, preventDefault: () => {prevented = true;}, target: {closest: () => ({dataset: {dashboardTool: 'signals'}, getAttribute: () => '/?tab=signals'})}});
    assert.equal(prevented, !modified);
    assert.equal(switched, modified ? undefined : 'signals');
    assert.equal(discovery.open, modified);
  }
});

test('mobile sheet keeps Tab focus inside its visible controls', () => {
  const source = fs.readFileSync('static/js/main/core.js', 'utf8');
  const start = source.indexOf("document.addEventListener('keydown', function (event) {");
  const handler = source.slice(start, source.indexOf('function syncDashboardTabState', start));
  let callback, focused, prevented;
  const first = {getClientRects: () => [1], focus: () => {focused = 'first';}};
  const last = {getClientRects: () => [1], focus: () => {focused = 'last';}};
  const document = {addEventListener: (_, cb) => {callback = cb;}, getElementById: () => ({hidden: false, querySelectorAll: () => [first, last]}), activeElement: last};
  vm.runInNewContext(handler, {document});
  callback({key: 'Tab', shiftKey: false, preventDefault: () => {prevented = true;}});
  assert.equal(focused, 'first');
  assert.equal(prevented, true);
  document.activeElement = first;
  callback({key: 'Tab', shiftKey: true, preventDefault() {}});
  assert.equal(focused, 'last');
});
