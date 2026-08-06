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

const tdmCity = Object.keys(wardsByCity)[0];
const benCatCity = Object.keys(wardsByCity)[1];
const tanAnWard = wardsByCity[tdmCity][0];
const phuTanWard = wardsByCity[tdmCity][1];
const myPhuocWard = wardsByCity[benCatCity][0];

assert.deepEqual(plain(api.nextDraftWardScope(null, tdmCity, tanAnWard, wardsByCity)), {
  version: 1,
  city: tdmCity,
  wards: [tanAnWard],
  mode: 'custom',
  label: tanAnWard,
});

assert.deepEqual(plain(api.nextDraftWardScope({
  version: 1,
  city: tdmCity,
  wards: [tanAnWard],
  mode: 'custom',
}, tdmCity, phuTanWard, wardsByCity)), {
  version: 1,
  city: tdmCity,
  wards: [tanAnWard, phuTanWard],
  mode: 'custom',
  label: `${tanAnWard} + ${phuTanWard}`,
});

assert.deepEqual(plain(api.nextDraftWardScope({
  version: 1,
  city: tdmCity,
  wards: [tanAnWard, phuTanWard],
  mode: 'custom',
}, tdmCity, tanAnWard, wardsByCity)), {
  version: 1,
  city: tdmCity,
  wards: [phuTanWard],
  mode: 'custom',
  label: phuTanWard,
});

assert.deepEqual(plain(api.nextDraftWardScope({
  version: 1,
  city: tdmCity,
  wards: [tanAnWard],
  mode: 'custom',
}, benCatCity, myPhuocWard, wardsByCity)), {
  version: 1,
  city: benCatCity,
  wards: [myPhuocWard],
  mode: 'custom',
  label: myPhuocWard,
});

assert.equal(api.nextDraftWardScope({
  version: 1,
  city: tdmCity,
  wards: [tanAnWard],
  mode: 'custom',
}, tdmCity, tanAnWard, wardsByCity), null);
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

const optionalParams = new URLSearchParams('tab=signals');
api.applyOptionalFiltersToParams(optionalParams, {
  price_range: ['1:2', '2:'],
  area_range: [':150'],
  prop_type: ['dat_nen', 'nha_dat'],
});
assert.equal(
  optionalParams.toString(),
  'tab=signals&price_range=1%3A2&price_range=2%3A&area_range=%3A150&prop_type=dat_nen&prop_type=nha_dat'
);
api.applyOptionalFiltersToParams(optionalParams, { price_range: [] });
assert.equal(
  optionalParams.toString(),
  'tab=signals&area_range=%3A150&prop_type=dat_nen&prop_type=nha_dat'
);
api.applyOptionalFiltersToParams(optionalParams, { area_range: [], prop_type: [] });
assert.equal(optionalParams.toString(), 'tab=signals');

assert.equal(
  api.scopeStatusLabel({
    version: 1,
    city: 'THá»¦ Dáº¦U Má»˜T',
    wards: ['TÃ¢n An'],
    mode: 'custom',
  }, new URLSearchParams('area_range=500%3A&prop_type=dat_nen&prop_type=nha_dat')),
  'TÃ¢n An | Diện tích: > 500 m2 | Loại hình: Đất + Nhà đất'
);

assert.equal(
  api.scopeStatusLabel({
    version: 1,
    city: 'THá»¦ Dáº¦U Má»˜T',
    wards: ['TÃ¢n An'],
    mode: 'custom',
  }, new URLSearchParams('price_range=1%3A2&area_min=120&area_max=300&prop_type=dat_nen&prop_type=nha_dat&prop_type=chung_cu&prop_type=nha_tro')),
  'TÃ¢n An | Giá: 1 - 2 tỷ | Diện tích: 120 - 300 m2'
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

const bodyClasses = new Set();
const chooser = {
  hidden: true,
  focused: false,
  querySelector() {
    return {
      focus() {
        chooser.focused = true;
      },
    };
  },
};
const bar = { hidden: false };
const label = { textContent: '' };
const doc = {
  body: {
    classList: {
      add(name) {
        bodyClasses.add(name);
      },
      remove(name) {
        bodyClasses.delete(name);
      },
      toggle(name, force) {
        if (force) bodyClasses.add(name);
        else bodyClasses.delete(name);
      },
    },
  },
  getElementById(id) {
    return {
      areaScopeChooser: chooser,
      areaScopeBar: bar,
      areaScopeLabel: label,
    }[id] || null;
  },
};

api.showChooser(doc);
assert.equal(chooser.hidden, false);
assert.equal(bar.hidden, true);
assert.equal(chooser.focused, true);
assert.equal(bodyClasses.has('area-scope-modal-open'), true);

let savedByClose = false;
window.localStorage = {
  setItem() {
    savedByClose = true;
  },
  removeItem() {
    savedByClose = true;
  },
};
window.document = doc;
window.closeAreaScopeChooser();
assert.equal(chooser.hidden, true);
assert.equal(bodyClasses.has('area-scope-modal-open'), false);
assert.equal(savedByClose, false);

api.showChooser(doc);
api.hideChooser(doc);
assert.equal(chooser.hidden, true);
assert.equal(bodyClasses.has('area-scope-modal-open'), false);

api.updateScopeUi({
  version: 1,
  city: 'THá»¦ Dáº¦U Má»˜T',
  wards: ['TÃ¢n An'],
  mode: 'custom',
}, doc);
assert.equal(label.textContent, 'TÃ¢n An');
assert.equal(bar.hidden, false);
assert.equal(chooser.hidden, true);
assert.equal(bodyClasses.has('area-scope-modal-open'), false);

const sidebarClasses = new Set(['collapsed']);
const sidebar = {
  classList: {
    add(name) {
      sidebarClasses.add(name);
    },
    remove(name) {
      sidebarClasses.delete(name);
    },
    contains(name) {
      return sidebarClasses.has(name);
    },
  },
};
const wardSearch = {
  focused: false,
  focus() {
    this.focused = true;
  },
};
window.document = {
  body: doc.body,
  getElementById(id) {
    return {
      areaScopeChooser: chooser,
      sidebar,
      wardSearch,
    }[id] || null;
  },
};

let toggleCount = 0;
window.toggleMenu = function toggleMenu() {
  toggleCount += 1;
  sidebarClasses.add('show');
};

window.innerWidth = 1280;
chooser.hidden = false;
bodyClasses.add('area-scope-modal-open');
window.openAreaScopeFilterSheet();
assert.equal(toggleCount, 0);
assert.equal(chooser.hidden, true);
assert.equal(sidebarClasses.has('collapsed'), false);
assert.equal(wardSearch.focused, true);
assert.equal(bodyClasses.has('area-scope-modal-open'), false);

window.innerWidth = 390;
wardSearch.focused = false;
chooser.hidden = false;
window.openAreaScopeFilterSheet();
assert.equal(toggleCount, 1);
assert.equal(sidebarClasses.has('show'), true);
assert.equal(wardSearch.focused, true);

console.log('area scope: ok');
