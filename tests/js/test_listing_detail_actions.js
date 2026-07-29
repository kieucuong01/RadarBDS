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
assert.equal(api.resolveListingId('42', '99', '100'), 42);
assert.equal(api.resolveListingId('', '99', '100'), 99);
assert.equal(api.resolveListingId('', '', '100'), 100);
assert.equal(api.resolveListingId('bad', '', 0), null);
const canonicalFromModal = api.canonicalListingUrl(
  'https://radarbds.vn/?signal=42',
  api.resolveListingId('', '42', null),
);
assert.equal(canonicalFromModal, 'https://radarbds.vn/listing/42');
assert.equal(
  api.facebookShareUrl(canonicalFromModal),
  'https://www.facebook.com/sharer/sharer.php?u=https%3A%2F%2Fradarbds.vn%2Flisting%2F42',
);
assert.deepEqual(api.normalizeReportPayload(' wrong_location ', '  Sai phường  '), {
  reason: 'wrong_location',
  note: 'Sai phường',
});
assert.equal(api.normalizeReportPayload('unknown', ''), null);
assert.equal(api.normalizeReportPayload('other', 'x'.repeat(501)), null);

(async () => {
  const calls = [];
  const result = await api.submitReport(async (url, options) => {
    calls.push({ url, options });
    return {
      ok: true,
      status: 201,
      json: async () => ({ ok: true, duplicate: false }),
    };
  }, 42, 'wrong_location', '  Sai phường  ');
  assert.equal(result.ok, true);
  assert.equal(calls[0].url, '/api/listings/42/report');
  assert.deepEqual(JSON.parse(calls[0].options.body), {
    reason: 'wrong_location',
    note: 'Sai phường',
  });
  assert.equal(await api.submitReport(async () => {
    throw new Error('must not fetch');
  }, 42, 'unknown', ''), null);

  console.log('listing detail actions contract: ok');
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
