const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

test('land price lead keeps the searched street and ward without submitting a lead', async () => {
  const listeners = {};
  const input = () => ({
    value: '', innerHTML: '', dataset: {},
    setAttribute() {}, removeAttribute() {}, focus() {},
    addEventListener() {},
  });
  const note = input();
  const listingUrl = input();
  const leadForm = {
    dataset: {},
    querySelector: (selector) => selector.includes('listing_url') ? listingUrl : note,
  };
  const button = {};
  const form = {
    querySelector: () => button,
    setAttribute() {},
    addEventListener: (event, callback) => { listeners[event] = callback; },
  };
  const query = input();
  const area = input();
  const nodes = {
    landPriceSearch: form, landPriceQuery: query, landPriceArea: area,
    landPriceRows: input(), landPriceCards: input(), landPriceStatus: input(),
  };
  const location = new URL('https://radarbds.vn/bang-gia-dat-tphcm');
  const window = {
    location, addEventListener() {}, matchMedia: () => ({matches: true}),
    history: { pushState(_state, _unused, url) { location.href = new URL(url, location).href; } },
  };
  const requests = [];
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../../static/js/tphcm_land_price_tool.js'), 'utf8'), {
    document: {
      getElementById: (id) => nodes[id] || null,
      querySelector: () => leadForm, querySelectorAll: () => [], addEventListener() {},
    },
    window, URLSearchParams, AbortController, Intl, clearTimeout,
    fetch: async (url) => {
      requests.push(url);
      return { ok: true, json: async () => ({ items: [], page: 1 }) };
    },
  });

  query.value = 'ĐT.742';
  area.value = 'Phú Chánh';
  listeners.submit({ preventDefault() {} });
  await new Promise(setImmediate);
  assert.match(leadForm.dataset.note, /ĐT\.742/);
  assert.match(leadForm.dataset.note, /Phú Chánh/);
  assert.equal(note.value, leadForm.dataset.note);
  assert.equal(new URL(listingUrl.value).searchParams.get('q'), 'ĐT.742');

  query.value = 'QL.13';
  area.value = '';
  listeners.submit({ preventDefault() {} });
  await new Promise(setImmediate);
  assert.match(note.value, /QL\.13/);
  assert.match(note.value, /tất cả/);
  assert.doesNotMatch(note.value, /ĐT\.742|Phú Chánh/);
  assert.equal(requests.length, 2);
  assert.ok(requests.every((url) => url.startsWith('/api/tphcm-land-prices?')));
});
