const assert = require('node:assert/strict');
const path = require('node:path');

const api = require(path.join(
  __dirname,
  '..',
  '..',
  'static',
  'js',
  'main',
  'comparable_carousel.js',
));

const items = (count) => Array.from({ length: count }, (_, index) => ({ id: index + 1 }));

assert.deepEqual(api.paginate(items(13), 6).map((page) => page.length), [6, 6, 1]);
assert.deepEqual(api.paginate(items(9), 4).map((page) => page.length), [4, 4, 1]);
assert.deepEqual(api.paginate(items(3), 1).map((page) => page.length), [1, 1, 1]);
assert.deepEqual(api.paginate([], 6), []);
assert.equal(api.pageSize(1440), 6);
assert.equal(api.pageSize(900), 4);
assert.equal(api.pageSize(390), 1);
assert.equal(api.clampPage(-1, 3), 0);
assert.equal(api.clampPage(9, 3), 2);
assert.equal(api.clampPage(1, 3), 1);
assert.equal(api.swipeDirection(100, 40), 1);
assert.equal(api.swipeDirection(40, 100), -1);
assert.equal(api.swipeDirection(100, 70), 0);

console.log('comparable carousel contract: ok');
