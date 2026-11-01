const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('static/js/main/listing_map.js', 'utf8');

test('satellite labels follow base-layer lifecycle without blocking parcels or duplicating on reactivation', () => {
  const handlers = {}, active = new Set(), tiles = [], pane = {style: {}};
  const map = {
    createPane(name) { assert.equal(name, 'satelliteLabels'); return pane; },
    hasLayer(layer) { return active.has(layer); },
    removeLayer(layer) { active.delete(layer); }
  };
  let additions = 0;
  const L = {
    tileLayer(url, options) { const layer = {url, options}; tiles.push(layer); return layer; },
    layerGroup(children) { return {children, addTo() { additions++; active.add(this); }}; }
  };
  const start = source.indexOf('  function bindSatelliteLabels(');
  const ctx = {L, map, satellite: {on(name, fn) { handlers[name] = fn; }}};
  vm.createContext(ctx);
  vm.runInContext(source.slice(start, source.indexOf('\n  function ', start + 1)) +
    '\nlabels = bindSatelliteLabels(L, map, satellite);', ctx);
  assert.equal(active.size, 0, 'street mode must not request satellite labels');
  handlers.add(); handlers.add();
  assert.equal(active.size, 1); assert.equal(additions, 1);
  assert.equal(tiles.length, 2);
  assert.ok(tiles.some(tile => tile.url.includes('World_Transportation')));
  assert.ok(tiles.some(tile => tile.url.includes('World_Boundaries_and_Places')));
  for (const tile of tiles) {
    assert.equal(tile.options.maxNativeZoom, 19);
    assert.equal(tile.options.maxZoom, 23);
    assert.equal(tile.options.interactive, false);
    assert.equal(tile.options.updateWhenIdle, true);
  }
  assert.equal(pane.style.pointerEvents, 'none');
  assert.ok(Number(pane.style.zIndex) > 400 && Number(pane.style.zIndex) < 410);
  handlers.remove(); handlers.remove();
  assert.equal(active.size, 0, 'control switch and imagery-error fallback both remove labels');
  handlers.add(); assert.equal(active.size, 1); assert.equal(additions, 2);
});
