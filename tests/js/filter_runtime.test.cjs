const test = require('node:test');
const assert = require('node:assert/strict');
const runtime = require('../../static/js/main/filter_runtime.js');

test('canonicalize sorts keys and deduplicates order-insensitive filters', () => {
  const params = new URLSearchParams();
  params.append('ward', 'Tan An');
  params.append('source', 'guland');
  params.append('ward', 'Hiep An');
  params.append('source', 'facebook');
  params.append('ward', 'Tan An');
  params.set('page', '1');

  assert.equal(
    runtime.canonicalize(params),
    'page=1&source=facebook&source=guland&ward=Hiep+An&ward=Tan+An',
  );
});

test('canonicalize keeps range tokens stable and drops client sigv', () => {
  const params = new URLSearchParams(
    'sigv=12&price_range=5%3A&price_range=%3A1&mos_min=10',
  );
  assert.equal(
    runtime.canonicalize(params),
    'mos_min=10&price_range=%3A1&price_range=5%3A',
  );
});

test('runSignalFirst schedules counts only after signal settles', async () => {
  const events = [];
  let release;
  const signal = new Promise((resolve) => { release = resolve; });
  const running = runtime.runSignalFirst(
    () => { events.push('signals-start'); return signal; },
    () => events.push('counts'),
  );

  await Promise.resolve();
  assert.deepEqual(events, ['signals-start']);
  release('ok');
  assert.equal(await running, 'ok');
  assert.deepEqual(events, ['signals-start', 'counts']);
});

test('runSignalFirst still schedules counts after a signal error', async () => {
  const events = [];
  await assert.rejects(
    runtime.runSignalFirst(
      () => Promise.reject(new Error('signal failed')),
      () => events.push('counts'),
    ),
    /signal failed/,
  );
  assert.deepEqual(events, ['counts']);
});

test('runSignalFirst suppresses counts for a superseded filter snapshot', async () => {
  const events = [];
  await runtime.runSignalFirst(
    () => Promise.resolve('aborted-old-run'),
    () => events.push('counts'),
    () => false,
  );
  assert.deepEqual(events, []);
});
