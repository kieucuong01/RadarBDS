const assert = require('node:assert/strict');
const path = require('node:path');

const api = require(path.join(
  __dirname,
  '..',
  '..',
  'static',
  'js',
  'main',
  'listing_detail_actions.js',
));

assert.equal(
  api.canonicalListingUrl('https://radarbds.vn/path?secret=1', 42),
  'https://radarbds.vn/listing/42',
);
assert.equal(api.canonicalListingUrl('https://radarbds.vn', '42'), 'https://radarbds.vn/listing/42');
for (const invalid of [0, -1, 1.2, '1.2', 'abc', null, undefined]) {
  assert.equal(api.canonicalListingUrl('https://radarbds.vn', invalid), null);
}
assert.equal(api.canonicalListingUrl('javascript:alert(1)', 42), null);
assert.equal(
  api.facebookShareUrl('https://radarbds.vn/listing/42'),
  'https://www.facebook.com/sharer/sharer.php?u=https%3A%2F%2Fradarbds.vn%2Flisting%2F42',
);
assert.deepEqual(api.normalizeReportPayload(' wrong_location ', '  Sai phường  '), {
  reason: 'wrong_location',
  note: 'Sai phường',
});
assert.equal(api.normalizeReportPayload('unknown', ''), null);
assert.equal(api.normalizeReportPayload('other', 'x'.repeat(501)), null);

console.log('listing detail actions contract: ok');
