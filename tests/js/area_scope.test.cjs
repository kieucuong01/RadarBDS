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
  'TÂN UYÊN': ['Uyên Hưng', 'Tân Phước Khánh'],
};

assert.equal(api.STORAGE_KEY, 'radar_area_scope_v2');
assert.equal(api.LEGACY_STORAGE_KEY, 'radar_area_scope_v1');

const urlScope = api.scopeFromSearchParams(
  new URLSearchParams('tab=signals&ward=T%C3%A2n+An&ward=Ph%C3%BA+T%C3%A2n'),
  wardsByCity
);
assert.deepEqual(plain(urlScope), {
  version: 2,
  activeCity: 'THỦ DẦU MỘT',
  selections: { 'THỦ DẦU MỘT': ['Tân An', 'Phú Tân'] },
  mode: 'custom',
  label: 'Tân An + Phú Tân',
});

const cityScope = api.scopeFromSearchParams(
  new URLSearchParams('tab=signals&city=B%E1%BA%BEN+C%C3%81T'),
  wardsByCity
);
assert.deepEqual(plain(cityScope), {
  version: 2,
  activeCity: 'BẾN CÁT',
  selections: { 'BẾN CÁT': ['Mỹ Phước', 'Mỹ Phước 3'] },
  mode: 'city_all',
  label: 'Toàn Bến Cát',
});

const tanUyenCityScope = api.scopeFromSearchParams(
  new URLSearchParams('tab=signals&city=T%C3%82N+UY%C3%8AN'),
  wardsByCity
);
assert.deepEqual(plain(tanUyenCityScope), {
  version: 2,
  activeCity: 'TÂN UYÊN',
  selections: { 'TÂN UYÊN': ['Uyên Hưng', 'Tân Phước Khánh'] },
  mode: 'city_all',
  label: 'Toàn Tân Uyên',
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
  version: 2,
  activeCity: 'THỦ DẦU MỘT',
  selections: { 'THỦ DẦU MỘT': ['Hiệp Thành'] },
  mode: 'preset',
  label: 'Hiệp Thành',
  updatedAt: '2026-08-06T10:00:00.000Z',
});

const tdmCity = Object.keys(wardsByCity)[0];
const benCatCity = Object.keys(wardsByCity)[1];
const tanAnWard = wardsByCity[tdmCity][0];
const phuTanWard = wardsByCity[tdmCity][1];
const myPhuocWard = wardsByCity[benCatCity][0];

const multiCityScope = api.validateScope({
  version: 2,
  activeCity: benCatCity,
  mode: 'custom',
  selections: {
    [tdmCity]: [tanAnWard],
    [benCatCity]: [myPhuocWard],
  },
}, wardsByCity);
assert.deepEqual(plain(api.flattenScopeWards(multiCityScope, wardsByCity)), [
  tanAnWard,
  myPhuocWard,
]);
assert.deepEqual(plain(api.selectionCounts(multiCityScope)), {
  wards: 2,
  cities: 2,
});

const multiCityParams = new URLSearchParams(`city=${encodeURIComponent(benCatCity)}`);
api.applyScopeToParams(multiCityParams, multiCityScope, wardsByCity);
assert.equal(multiCityParams.has('city'), false);
assert.deepEqual(multiCityParams.getAll('ward'), [tanAnWard, myPhuocWard]);

const multiCityFromUrl = api.scopeFromSearchParams(
  new URLSearchParams(`ward=${encodeURIComponent(tanAnWard)}&ward=${encodeURIComponent(myPhuocWard)}`),
  wardsByCity
);
assert.deepEqual(plain(multiCityFromUrl.selections), {
  [tdmCity]: [tanAnWard],
  [benCatCity]: [myPhuocWard],
});

const migratedV1Scope = api.validateScope({
  version: 1,
  city: tdmCity,
  wards: [tanAnWard],
  mode: 'custom',
}, wardsByCity);
assert.equal(migratedV1Scope.version, 2);
assert.deepEqual(plain(migratedV1Scope.selections), {
  [tdmCity]: [tanAnWard],
});

api.setCurrentScope(multiCityScope, wardsByCity);
api.setActiveScopeCity(tdmCity, wardsByCity);
api.updateCitySelection(tdmCity, [tanAnWard, phuTanWard], wardsByCity);
api.setActiveScopeCity(benCatCity, wardsByCity);
assert.deepEqual(plain(api.getCurrentScope().selections), {
  [tdmCity]: [tanAnWard, phuTanWard],
  [benCatCity]: [myPhuocWard],
});
assert.equal(api.getCurrentScope().activeCity, benCatCity);
assert.deepEqual(plain(api.selectionCounts(api.getCurrentScope())), {
  wards: 3,
  cities: 2,
});

assert.deepEqual(plain(api.nextDraftWardScope(null, tdmCity, tanAnWard, wardsByCity)), {
  version: 2,
  activeCity: tdmCity,
  selections: { [tdmCity]: [tanAnWard] },
  mode: 'custom',
  label: tanAnWard,
});

assert.deepEqual(plain(api.nextDraftWardScope({
  version: 1,
  city: tdmCity,
  wards: [tanAnWard],
  mode: 'custom',
}, tdmCity, phuTanWard, wardsByCity)), {
  version: 2,
  activeCity: tdmCity,
  selections: { [tdmCity]: [tanAnWard, phuTanWard] },
  mode: 'custom',
  label: `${tanAnWard} + ${phuTanWard}`,
});

assert.deepEqual(plain(api.nextDraftWardScope({
  version: 1,
  city: tdmCity,
  wards: [tanAnWard, phuTanWard],
  mode: 'custom',
}, tdmCity, tanAnWard, wardsByCity)), {
  version: 2,
  activeCity: tdmCity,
  selections: { [tdmCity]: [phuTanWard] },
  mode: 'custom',
  label: phuTanWard,
});

assert.deepEqual(plain(api.nextDraftWardScope({
  version: 1,
  city: tdmCity,
  wards: [tanAnWard],
  mode: 'custom',
}, benCatCity, myPhuocWard, wardsByCity)), {
  version: 2,
  activeCity: benCatCity,
  selections: {
    [tdmCity]: [tanAnWard],
    [benCatCity]: [myPhuocWard],
  },
  mode: 'custom',
  label: '2 phường · 2 thành phố',
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
  'TÃ¢n An | > 500 m2 | Đất + Nhà đất'
);

assert.equal(
  api.scopeStatusLabel({
    version: 1,
    city: 'THá»¦ Dáº¦U Má»˜T',
    wards: ['TÃ¢n An'],
    mode: 'custom',
  }, new URLSearchParams('price_range=1%3A2&area_min=120&area_max=300&prop_type=dat_nen&prop_type=nha_dat&prop_type=chung_cu&prop_type=nha_tro')),
  'TÃ¢n An | 1 - 2 tỷ | 120 - 300 m2'
);

assert.deepEqual(plain(api.scopeStatusParts({
  version: 1,
  city: 'THá»¦ Dáº¦U Má»˜T',
  wards: ['TÃ¢n An'],
  mode: 'custom',
}, new URLSearchParams('area_range=500%3A&prop_type=dat_nen&prop_type=nha_dat'))), [
  { kind: 'location', label: 'TÃ¢n An' },
  { kind: 'area', label: '> 500 m2' },
  { kind: 'type', label: 'Đất + Nhà đất' },
]);

const storage = {
  value: '',
  setItem(key, value) {
    assert.equal(key, api.STORAGE_KEY);
    this.value = value;
  },
  getItem(key) {
    if (key === api.STORAGE_KEY) return this.value;
    if (key === api.LEGACY_STORAGE_KEY) return '';
    assert.fail(`unexpected storage key: ${key}`);
  },
  removeItem(key) {
    assert.ok([api.STORAGE_KEY, api.LEGACY_STORAGE_KEY].includes(key));
    this.value = '';
  },
};
api.saveScope({
  version: 1,
  city: 'THỦ DẦU MỘT',
  wards: ['Tân An'],
  mode: 'custom',
}, storage, {
  area_range: ['500:'],
  prop_type: ['dat_nen', 'nha_dat'],
});
assert.match(storage.value, /"updatedAt"/);
assert.deepEqual(plain(api.readStoredScope(storage, wardsByCity)), {
  version: 2,
  activeCity: 'THỦ DẦU MỘT',
  selections: { 'THỦ DẦU MỘT': ['Tân An'] },
  mode: 'custom',
  label: 'Tân An',
  filters: {
    area_range: ['500:'],
    prop_type: ['dat_nen', 'nha_dat'],
  },
  updatedAt: JSON.parse(storage.value).updatedAt,
});

const storedParams = new URLSearchParams('tab=signals');
api.applyStoredFiltersToParams(storedParams, api.readStoredScope(storage, wardsByCity));
assert.equal(
  storedParams.toString(),
  'tab=signals&area_range=500%3A&prop_type=dat_nen&prop_type=nha_dat'
);

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
const cityInput = { value: 'THỦ DẦU MỘT' };
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
      cityInput,
    }[id] || null;
  },
  querySelectorAll(selector) {
    if (selector === '#wardFilters input[name="ward"]') {
      return [
        { checked: true, value: 'Tân An' },
        { checked: true, value: 'Phú Tân' },
      ];
    }
    if (selector === '.range-chip.active[data-range-kind="price"]') return [];
    if (selector === '.range-chip.active[data-range-kind="area"]') return [];
    if (selector === '#filterForm input[name="prop_type"]') return [];
    if (selector === '.area-scope-city-tab') return [];
    if (selector === '.area-scope-city-group') return [];
    if (selector === '.area-scope-ward-chip') return [];
    return [];
  },
};

api.showChooser(doc);
assert.equal(chooser.hidden, false);
assert.equal(bar.hidden, true);
assert.equal(chooser.focused, true);
assert.equal(bodyClasses.has('area-scope-modal-open'), true);

let savedByClose = false;
let appliedByClose = 0;
window.INITIAL_WARDS_BY_CITY = {
  'THỦ DẦU MỘT': ['Tân An', 'Phú Tân'],
};
window.localStorage = {
  setItem() {
    savedByClose = true;
  },
  removeItem() {
    savedByClose = true;
  },
};
window.applyFilters = function applyFilters() {
  appliedByClose += 1;
};
window.document = doc;
api.setCurrentScope({
  version: 2,
  activeCity: 'THỦ DẦU MỘT',
  selections: { 'THỦ DẦU MỘT': ['Tân An', 'Phú Tân'] },
  mode: 'city_all',
}, window.INITIAL_WARDS_BY_CITY);
window.closeAreaScopeChooser();
assert.equal(chooser.hidden, true);
assert.equal(bar.hidden, false);
assert.equal(label.textContent, 'Toàn Thủ Dầu Một');
assert.equal(bodyClasses.has('area-scope-modal-open'), false);
assert.equal(savedByClose, false);
assert.equal(appliedByClose, 1);

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

const chipLabel = {
  textContent: '',
  children: [],
  appendChild(child) {
    this.children.push(child);
  },
  setAttribute(name, value) {
    this[name] = value;
  },
};
const chipDoc = {
  body: doc.body,
  createElement(tagName) {
    return {
      tagName,
      className: '',
      textContent: '',
    };
  },
  getElementById(id) {
    return {
      areaScopeChooser: chooser,
      areaScopeBar: bar,
      areaScopeLabel: chipLabel,
    }[id] || null;
  },
  querySelectorAll(selector) {
    if (selector === '.range-chip.active[data-range-kind="price"]') return [];
    if (selector === '.range-chip.active[data-range-kind="area"]') {
      return [{ dataset: { min: '500', max: '' } }];
    }
    if (selector === '#filterForm input[name="prop_type"]') {
      return [
        { checked: true, value: 'dat_nen' },
        { checked: true, value: 'nha_dat' },
        { checked: false, value: 'chung_cu' },
      ];
    }
    return [];
  },
};
api.updateScopeUi({
  version: 1,
  city: 'THá»¦ Dáº¦U Má»˜T',
  wards: ['TÃ¢n An'],
  mode: 'custom',
}, chipDoc);
assert.deepEqual(chipLabel.children.map((child) => child.textContent), [
  'TÃ¢n An',
  '> 500 m2',
  'Đất + Nhà đất',
]);
assert.deepEqual(chipLabel.children.map((child) => child.className), [
  'area-scope-chip area-scope-chip-location',
  'area-scope-chip area-scope-chip-area',
  'area-scope-chip area-scope-chip-type',
]);
assert.equal(chipLabel['aria-label'], 'TÃ¢n An > 500 m2 Đất + Nhà đất');

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
