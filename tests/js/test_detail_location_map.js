const assert = require('node:assert/strict');
const path = require('node:path');

const api = require(path.join(
  __dirname,
  '..',
  '..',
  'static',
  'js',
  'main',
  'detail_location_map.js',
));

assert.equal(api.precisionCopy('exact').title, 'Vị trí chính xác');
assert.match(api.precisionCopy('road').note, /tên đường/i);
assert.match(api.precisionCopy('ward').note, /tâm phường/i);
assert.equal(api.precisionCopy('unknown'), null);

assert.deepEqual(
  api.normalizeLocation({
    lat: '10.992',
    lng: 106.676,
    precision: 'road',
    label: 'Theo tên đường ĐX 43, Phú Lợi',
    resolver_version: 'osm-v1',
  }),
  {
    lat: 10.992,
    lng: 106.676,
    precision: 'road',
    label: 'Theo tên đường ĐX 43, Phú Lợi',
    resolverVersion: 'osm-v1',
  },
);
assert.equal(api.normalizeLocation({ lat: 200, lng: 106, precision: 'road' }), null);
assert.equal(api.normalizeLocation({ lat: 10, lng: 106, precision: 'guess' }), null);
assert.equal(api.normalizeLocation(null), null);

(async () => {
  let entered = 0;
  let exited = 0;
  const canvas = {
    requestFullscreen: async () => { entered += 1; },
  };
  const doc = {
    fullscreenElement: null,
    exitFullscreen: async () => { exited += 1; },
  };

  assert.equal(api.fullscreenAvailable(canvas, doc), true);
  assert.equal(await api.toggleFullscreen(canvas, doc), true);
  assert.equal(entered, 1);

  doc.fullscreenElement = canvas;
  assert.equal(await api.toggleFullscreen(canvas, doc), false);
  assert.equal(exited, 1);
  assert.equal(api.fullscreenAvailable({}, doc), false);

  console.log('detail location map contract: ok');
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
