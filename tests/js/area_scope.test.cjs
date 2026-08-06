'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..', '..');
const source = fs.readFileSync(
  path.join(root, 'static', 'js', 'main', 'area_scope.js'),
  'utf8'
);

const window = {};
vm.runInNewContext(source, {
  window,
  URLSearchParams,
  Date,
  JSON,
  Object,
  Array,
  Set,
  String,
});

const api = window.RadarAreaScope;
assert.ok(api, 'area scope API must be exposed on window');

function plain(value) {
  return JSON.parse(JSON.stringify(value));
}

const wardsByCity = {
  'THỦ DẦU MỘT': ['Tân An', 'Phú Tân', 'Hiệp Thành'],
  'BẾN CÁT': ['Mỹ Phước', 'Mỹ Phước 3'],
};

assert.equal(api.STORAGE_KEY, 'radar_area_scope_v1');

const urlScope = api.scopeFromSearchParams(
  new URLSearchParams('tab=signals&ward=T%C3%A2n+An&ward=Ph%C3%BA+T%C3%A2n'),
  wardsByCity
);
assert.deepEqual(plain(urlScope), {
  version: 1,
  city: 'THỦ DẦU MỘT',
  wards: ['Tân An', 'Phú Tân'],
  mode: 'custom',
  label: 'Tân An + Phú Tân',
});

const cityScope = api.scopeFromSearchParams(
  new URLSearchParams('tab=signals&city=B%E1%BA%BEN+C%C3%81T'),
  wardsByCity
);
assert.deepEqual(plain(cityScope), {
  version: 1,
  city: 'BẾN CÁT',
  wards: [],
  mode: 'city_all',
  label: 'Toàn Bến Cát',
});

assert.equal(
  api.scopeFromSearchParams(new URLSearchParams('tab=signals'), wardsByCity),
  null
);

assert.equal(
  api.validateScope({
    version: 1,
    city: 'THỦ DẦU MỘT',
    wards: ['Tân An', 'Phường Cũ'],
    mode: 'custom',
  }, wardsByCity),
  null
);

const restored = api.validateScope({
  version: 1,
  city: 'THỦ DẦU MỘT',
  wards: ['Hiệp Thành'],
  mode: 'preset',
  label: 'ignored label',
  updatedAt: '2026-08-06T10:00:00.000Z',
}, wardsByCity);
assert.deepEqual(plain(restored), {
  version: 1,
  city: 'THỦ DẦU MỘT',
  wards: ['Hiệp Thành'],
  mode: 'preset',
  label: 'Hiệp Thành',
  updatedAt: '2026-08-06T10:00:00.000Z',
});

const params = new URLSearchParams('tab=signals&q=ql13&city=B%E1%BA%BEN+C%C3%81T');
api.applyScopeToParams(params, {
  version: 1,
  city: 'THỦ DẦU MỘT',
  wards: ['Tân An', 'Phú Tân'],
  mode: 'custom',
});
assert.equal(
  params.toString(),
  'tab=signals&q=ql13&city=TH%E1%BB%A6+D%E1%BA%A6U+M%E1%BB%98T&ward=T%C3%A2n+An&ward=Ph%C3%BA+T%C3%A2n'
);

const storage = {
  value: '',
  setItem(key, value) {
    assert.equal(key, api.STORAGE_KEY);
    this.value = value;
  },
  getItem(key) {
    assert.equal(key, api.STORAGE_KEY);
    return this.value;
  },
  removeItem(key) {
    assert.equal(key, api.STORAGE_KEY);
    this.value = '';
  },
};
api.saveScope({
  version: 1,
  city: 'THỦ DẦU MỘT',
  wards: ['Tân An'],
  mode: 'custom',
}, storage);
assert.match(storage.value, /"updatedAt"/);
assert.deepEqual(plain(api.readStoredScope(storage, wardsByCity)), {
  version: 1,
  city: 'THỦ DẦU MỘT',
  wards: ['Tân An'],
  mode: 'custom',
  label: 'Tân An',
  updatedAt: JSON.parse(storage.value).updatedAt,
});

console.log('area scope: ok');
