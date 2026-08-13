# Multi-city Ward Filters and Map Marker Hierarchy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cho phép chọn nhiều phường thuộc nhiều thành phố trong cùng bộ lọc và làm marker Maps có thứ bậc `exact = road < landmark < ward` với màu landmark riêng biệt.

**Architecture:** Giữ public request contract bằng tham số `ward` lặp lại và đặt mô hình scope version 2 trong `area_scope.js` làm nguồn state duy nhất cho sidebar lẫn chooser. UI thành phố chỉ đổi tab đang xem; mọi thay đổi checkbox cập nhật `selections` toàn cục rồi serialize qua một hàm duy nhất. Marker chỉ đổi style Leaflet và màu chú giải, không đổi dữ liệu hoặc API Maps.

**Tech Stack:** JavaScript ES6/UMD, Flask/Jinja, Leaflet, CSS, Node test runner, pytest.

## Global Constraints

- Exact và road cùng radius 6; landmark radius 7; ward radius 8; tất cả weight 2.
- Landmark dùng viền `#be123c` và nền `#fb7185`; exact/road/ward giữ màu đã duyệt.
- `Chọn tất cả` và `Bỏ chọn` chỉ tác động thành phố đang mở.
- Chuyển tab thành phố không được tự chạy filter hoặc xóa lựa chọn thành phố khác.
- Multi-city query dùng nhiều `ward` và không gửi `city`; single-city query vẫn tương thích deep link cũ.
- URL scope có ưu tiên hơn localStorage; localStorage version 1 phải tự chuyển sang version 2.
- Signals giữ một request ngay sau filter ổn định; Counts chỉ chạy sau Signals; Maps dùng cùng filter snapshot.
- Không thêm dependency hoặc request mạng/DB mới.
- Giữ nguyên `.playwright-cli/` và mọi thay đổi không liên quan.

---

### Task 1: Xây mô hình scope version 2 và migration tương thích

**Files:**
- Modify: `static/js/main/area_scope.js`
- Modify: `tests/js/area_scope.test.cjs`

**Interfaces:**
- Consumes: `wardsByCity: Record<string, string[]>`, URLSearchParams, payload `radar_area_scope_v1` hiện tại.
- Produces: `validateScope(candidate, wardsByCity)`, `scopeFromSearchParams(params, wardsByCity)`, `applyScopeToParams(params, scope, wardsByCity)`, `flattenScopeWards(scope, wardsByCity)`, `selectionCounts(scope)`, `updateCitySelection(scope, city, wards, wardsByCity)`.

- [ ] **Step 1: Viết test đỏ cho state đa thành phố, URL và migration**

Thêm các assertions sau vào `tests/js/area_scope.test.cjs`:

```js
const multi = api.validateScope({
  version: 2,
  activeCity: 'BẾN CÁT',
  mode: 'custom',
  selections: {
    'THỦ DẦU MỘT': ['Tân An'],
    'BẾN CÁT': ['Mỹ Phước'],
  },
}, wardsByCity);
assert.deepEqual(api.flattenScopeWards(multi, wardsByCity), ['Tân An', 'Mỹ Phước']);
assert.deepEqual(api.selectionCounts(multi), { wards: 2, cities: 2 });

const params = api.applyScopeToParams(new URLSearchParams('city=BẾN CÁT'), multi, wardsByCity);
assert.equal(params.has('city'), false);
assert.deepEqual(params.getAll('ward'), ['Tân An', 'Mỹ Phước']);

const restored = api.scopeFromSearchParams(
  new URLSearchParams('ward=Tân+An&ward=Mỹ+Phước'),
  wardsByCity,
);
assert.deepEqual(restored.selections, {
  'THỦ DẦU MỘT': ['Tân An'],
  'BẾN CÁT': ['Mỹ Phước'],
});

const migrated = api.validateScope({
  version: 1,
  city: 'THỦ DẦU MỘT',
  wards: ['Tân An'],
  mode: 'custom',
}, wardsByCity);
assert.equal(migrated.version, 2);
assert.deepEqual(migrated.selections, { 'THỦ DẦU MỘT': ['Tân An'] });
```

- [ ] **Step 2: Chạy test để xác nhận RED**

Run:

```powershell
node --test tests/js/area_scope.test.cjs
```

Expected: FAIL vì `flattenScopeWards`, `selectionCounts` và state version 2 chưa tồn tại.

- [ ] **Step 3: Cài đặt model version 2 tối thiểu**

Trong `static/js/main/area_scope.js`, thay normalization một-city bằng các helper thuần:

```js
const STORAGE_KEY = 'radar_area_scope_v2';
const LEGACY_STORAGE_KEY = 'radar_area_scope_v1';

function cityForWard(ward, wardsByCity) {
  return Object.keys(wardsByCity || {}).find((city) =>
    (wardsByCity[city] || []).includes(ward)
  ) || '';
}

function flattenScopeWards(scope, wardsByCity) {
  if (!scope) return [];
  if (scope.mode === 'city_all') return Array.from(wardsByCity[scope.activeCity] || []);
  return Object.keys(scope.selections || {}).flatMap((city) => scope.selections[city]);
}

function selectionCounts(scope) {
  const selections = (scope && scope.selections) || {};
  const cityLists = Object.values(selections).filter((wards) => wards.length);
  return {
    wards: cityLists.reduce((sum, wards) => sum + wards.length, 0),
    cities: cityLists.length,
  };
}
```

`validateScope()` phải nhận cả v1/v2, loại city/ward không thuộc `wardsByCity`, giữ `filters`, và luôn trả payload version 2. `scopeFromSearchParams()` nhóm từng ward bằng `cityForWard()`. `applyScopeToParams()` xóa `city`, `ward`, `ward[]`, `ward_mode`; multi-city chỉ append ward, single-city custom set city và append ward, single city-all chỉ set city.

`readStoredScope()` đọc v2 trước; nếu không hợp lệ mới đọc legacy v1. `saveScope()` chỉ ghi v2 sau khi `validateScope()` thành công.

- [ ] **Step 4: Chạy test GREEN và toàn bộ area-scope tests**

Run:

```powershell
node --test tests/js/area_scope.test.cjs tests/js/filter_runtime.test.cjs
```

Expected: PASS, bao gồm deep link v1 hiện tại và multi-city mới.

- [ ] **Step 5: Commit model scope**

```powershell
git add static/js/main/area_scope.js tests/js/area_scope.test.cjs
git commit -m "feat: add multi-city area scope model"
```

---

### Task 2: Nối sidebar vào state đa thành phố

**Files:**
- Modify: `static/js/main/boot.js`
- Modify: `static/js/main/filters.js`
- Modify: `static/js/main/area_scope.js`
- Modify: `templates/index.html`
- Modify: `static/css/main/filters.css`
- Modify: `tests/js/area_scope.test.cjs`
- Modify: `tests/test_refactor_structure.py`

**Interfaces:**
- Consumes: scope v2 và helpers Task 1.
- Produces: `setCurrentScope(scope)`, `getCurrentScope()`, `setActiveScopeCity(city)`, `commitVisibleCitySelection(doc, wardsByCity)`, badge `[data-city-count]`, summary `#wardSelectedCount`.

- [ ] **Step 1: Viết test đỏ cho chuyển tab, bulk action và query**

Mở rộng DOM mock trong `tests/js/area_scope.test.cjs` để tạo hai city pills và checkbox theo tab. Assert:

```js
api.setCurrentScope(multi);
api.setActiveScopeCity('THỦ DẦU MỘT');
api.updateCitySelection('THỦ DẦU MỘT', ['Tân An', 'Hiệp An'], wardsByCity);
api.setActiveScopeCity('BẾN CÁT');
assert.deepEqual(api.getCurrentScope().selections['THỦ DẦU MỘT'], ['Tân An', 'Hiệp An']);
assert.deepEqual(api.getCurrentScope().selections['BẾN CÁT'], ['Mỹ Phước']);
assert.deepEqual(api.selectionCounts(api.getCurrentScope()), { wards: 3, cities: 2 });
```

Trong `tests/test_refactor_structure.py`, assert template có `data-city-count`, summary có `aria-live="polite"`, và asset token mới xuất hiện cho `filters.js`, `area_scope.js`, `boot.js`, `filters.css`.

- [ ] **Step 2: Chạy test để xác nhận RED**

Run:

```powershell
node --test tests/js/area_scope.test.cjs
& $py -X utf8 -m pytest tests/test_refactor_structure.py -q
```

Expected: FAIL vì UI chưa có badge và `selectCity()` còn xóa wards rồi áp filter.

- [ ] **Step 3: Đổi city pill thành tab điều hướng**

Trong `templates/index.html`, mỗi pill chứa badge riêng:

```html
<button type="button" class="city-pill" data-city="{{ city_value }}"
        aria-pressed="false" onclick="selectCity(this)">
  <span>{{ city_label }}</span>
  <span class="city-pill-count" data-city-count="{{ city_value }}" hidden>0</span>
</button>
```

Đổi `#wardSelectedCount` thành vùng status:

```html
<span class="ward-count" id="wardSelectedCount" aria-live="polite">0 phường · 0 thành phố</span>
```

Trong `filters.js`, `selectCity(btn)` chỉ gọi `RadarAreaScope.setActiveScopeCity()`, cập nhật `#cityInput`, trạng thái `active`/`aria-pressed`, render wards và không gọi `applyFilters()`.

`setAllWards(true)` lấy toàn bộ ward của city hiện tại; `setAllWards(false)` dùng mảng rỗng. Cả hai gọi `updateCitySelection()`, persist scope và schedule filter đúng một lần.

- [ ] **Step 4: Render checklist/badge từ một nguồn state**

Trong `boot.js`, `updateWardFilters()` lấy `activeCity` và `selections[activeCity]` từ current scope thay vì nhận mảng ward cục bộ. Checkbox chỉ checked nếu ward thuộc selection của city đang mở; không dùng `selected.size === 0` để tự check tất cả.

Trong `area_scope.js`, thêm `renderCitySelectionBadges()` cập nhật từng `[data-city-count]` và `updateWardSelectionSummary()` bằng tổng toàn scope. Handler checkbox gọi `commitVisibleCitySelection()` trước khi persist/apply.

`getFilterQuery()` trong `filters.js` phải xóa city/ward thu được từ FormData rồi gọi:

```js
window.RadarAreaScope.applyScopeToParams(
  params,
  window.RadarAreaScope.getCurrentScope(),
  globalWardsByCity,
);
```

Nếu selections rỗng, helper set `ward_mode=none`.

- [ ] **Step 5: Thêm CSS badge và responsive**

Trong `filters.css`, badge dùng kích thước gọn nhưng pill vẫn có vùng bấm tối thiểu 44px trên mobile:

```css
.city-pill-count {
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 0.62rem;
  font-weight: 900;
  background: rgba(255, 255, 255, 0.2);
}

.city-pill-count[hidden] { display: none; }

@media (max-width: 760px) {
  .sidebar .city-pill { min-height: 44px; }
}
```

- [ ] **Step 6: Chạy test GREEN**

Run:

```powershell
node --test tests/js/area_scope.test.cjs tests/js/filter_runtime.test.cjs
& $py -X utf8 -m pytest tests/test_refactor_structure.py -q
node --check static/js/main/area_scope.js
node --check static/js/main/filters.js
node --check static/js/main/boot.js
```

Expected: PASS; city tab không tạo request, bulk action chỉ đổi current city, query multi-city có hai ward và không có city.

- [ ] **Step 7: Commit sidebar đa thành phố**

```powershell
git add static/js/main/boot.js static/js/main/filters.js static/js/main/area_scope.js templates/index.html static/css/main/filters.css tests/js/area_scope.test.cjs tests/test_refactor_structure.py
git commit -m "feat: support multi-city ward filters"
```

---

### Task 3: Đồng bộ chooser, URL restore và localStorage

**Files:**
- Modify: `static/js/main/area_scope.js`
- Modify: `static/js/main/boot.js`
- Modify: `tests/js/area_scope.test.cjs`
- Modify: `tests/test_refactor_structure.py`

**Interfaces:**
- Consumes: current scope v2 Task 1–2.
- Produces: chooser draft v2, v1 migration, URL-first restore không làm mất multi-city selections.

- [ ] **Step 1: Viết test đỏ cho chooser và boot restore**

Thêm test cho chuỗi thao tác:

```js
let draft = api.updateCitySelection(multi, 'THỦ DẦU MỘT', ['Tân An'], wardsByCity);
draft = api.updateCitySelection(draft, 'BẾN CÁT', ['Mỹ Phước', 'Tân Định'], wardsByCity);
assert.deepEqual(draft.selections['THỦ DẦU MỘT'], ['Tân An']);
assert.deepEqual(draft.selections['BẾN CÁT'], ['Mỹ Phước', 'Tân Định']);
assert.equal(api.scopeLabel(draft), '3 phường · 2 thành phố');
```

Test localStorage phải có cả key v2 không hợp lệ và v1 hợp lệ để chứng minh fallback migration, sau đó save ghi payload version 2.

- [ ] **Step 2: Chạy test RED**

Run:

```powershell
node --test tests/js/area_scope.test.cjs
```

Expected: FAIL vì chooser draft hiện xóa scope khi đổi city.

- [ ] **Step 3: Nâng chooser và boot restore**

`selectAreaScopeCity(city)` chỉ đổi `activeCity` của draft. `toggleAreaScopeWard()` gọi `updateCitySelection()` với danh sách city đang chỉnh. `renderAreaScopeDraft()` đọc selections theo từng city và hiển thị trạng thái chọn đúng khi quay lại tab.

`applyAreaScopeWardSelection()` áp toàn draft. Preset và `selectAreaCityAll()` tạo scope v2 `mode: 'city_all'` cho đúng một city và thay draft có chủ đích.

Trong `boot.js`, URL scope hợp lệ được set làm current scope trước render. Khi không có URL filter, đọc v2 rồi legacy v1; sau migration, gọi save v2. Đóng chooser dùng current scope nếu có, không thay bằng default city-all.

- [ ] **Step 4: Chạy test GREEN và contract signals-first**

Run:

```powershell
node --test tests/js/area_scope.test.cjs tests/js/filter_runtime.test.cjs
& $py -X utf8 -m pytest tests/test_refactor_structure.py::test_homepage_area_scope_boot_uses_url_then_local_storage_then_chooser tests/test_refactor_structure.py::test_signal_filter_flow_loads_cards_before_counts_without_dashboard -q
```

Expected: PASS và không thay đổi thứ tự signals/counts.

- [ ] **Step 5: Commit chooser/state restore**

```powershell
git add static/js/main/area_scope.js static/js/main/boot.js tests/js/area_scope.test.cjs tests/test_refactor_structure.py
git commit -m "feat: persist multi-city area scopes"
```

---

### Task 4: Áp thứ bậc marker và màu landmark

**Files:**
- Modify: `static/js/main/listing_map.js`
- Modify: `static/css/main/listing_map.css`
- Modify: `tests/test_listing_map_js.py`
- Modify: `tests/test_listing_map_ui.py`

**Interfaces:**
- Consumes: `markerStyle(precision)` hiện có và legend precision CSS.
- Produces: exact/road radius 6, landmark radius 7 rose, ward radius 8.

- [ ] **Step 1: Sửa regression test trước và xác nhận RED**

Trong `tests/test_listing_map_js.py`, đổi assertions:

```python
assert _run_node("mapApi.markerStyle('exact').radius") == 6
assert _run_node("mapApi.markerStyle('road').radius") == 6
assert _run_node("mapApi.markerStyle('landmark')") == {
    "radius": 7,
    "color": "#be123c",
    "weight": 2,
    "fillColor": "#fb7185",
    "fillOpacity": 0.84,
}
assert _run_node("mapApi.markerStyle('ward').radius") == 8
```

Trong `tests/test_listing_map_ui.py`, assert `.listing-map-precision-landmark` chứa `#be123c`.

Run:

```powershell
& $py -X utf8 -m pytest tests/test_listing_map_js.py::test_map_markers_use_compact_visual_radius_and_border tests/test_listing_map_ui.py -q
```

Expected: FAIL vì road đang radius 7 và landmark còn màu teal.

- [ ] **Step 2: Cài đặt style marker và legend**

Trong `markerStyle()`:

```js
if (precision === 'road') return { radius: 6, color: '#3730a3', weight: 2, fillColor: '#6366f1', fillOpacity: 0.84 };
if (precision === 'landmark') return { radius: 7, color: '#be123c', weight: 2, fillColor: '#fb7185', fillOpacity: 0.84 };
```

Trong CSS:

```css
.listing-map-precision-landmark { color: #be123c; }
```

- [ ] **Step 3: Chạy test GREEN**

Run:

```powershell
& $py -X utf8 -m pytest tests/test_listing_map_js.py tests/test_listing_map_ui.py -q
node --check static/js/main/listing_map.js
```

Expected: PASS; label model tests không đổi.

- [ ] **Step 4: Commit marker hierarchy**

```powershell
git add static/js/main/listing_map.js static/css/main/listing_map.css tests/test_listing_map_js.py tests/test_listing_map_ui.py
git commit -m "ui: clarify listing map marker hierarchy"
```

---

### Task 5: Asset versions, regression, browser smoke và production release

**Files:**
- Modify: `templates/index.html`
- Modify: `tests/test_refactor_structure.py`
- Modify: `tests/test_listing_map_ui.py`

**Interfaces:**
- Consumes: toàn bộ feature Tasks 1–4.
- Produces: immutable asset URLs mới và bằng chứng production.

- [ ] **Step 1: Đổi asset tokens và test expectations**

Dùng token `multi-city-ward-filter-20260814` cho `area_scope.js`, `filters.js`, `boot.js`, `filters.css`; dùng `listing-map-marker-hierarchy-20260814` cho `listing_map.js` và `listing_map.css`. Cập nhật đúng assertions version trong hai test Python.

- [ ] **Step 2: Chạy focused regression đầy đủ**

Run:

```powershell
node --test tests/js/area_scope.test.cjs tests/js/filter_runtime.test.cjs tests/js/range_filters.test.cjs
& $py -X utf8 -m pytest tests/test_refactor_structure.py tests/test_listing_map_js.py tests/test_listing_map_ui.py tests/test_listing_map_api.py -q
node --check static/js/main/area_scope.js
node --check static/js/main/filters.js
node --check static/js/main/boot.js
node --check static/js/main/listing_map.js
git diff --check
```

Expected: tất cả PASS, không có syntax error hoặc whitespace error.

- [ ] **Step 3: Browser smoke desktop và mobile**

Trên desktop và viewport 390×844:

1. Chọn Tân An trong tab Thủ Dầu Một.
2. Chuyển tab Bến Cát; xác nhận Tân An vẫn được badge giữ lại và không có request filter chỉ vì đổi tab.
3. Chọn Mỹ Phước; xác nhận summary `2 phường · 2 thành phố`.
4. Xác nhận URL có hai `ward`, không có `city`.
5. Mở Săn Deal, Tin Rao và Maps; xác nhận cả ba dùng cùng scope.
6. Reload; xác nhận URL phục hồi đúng.
7. Xóa query rồi reload; xác nhận localStorage v2 phục hồi đúng.
8. Mở chooser, đổi city qua lại; xác nhận draft không mất selections.
9. Kiểm tra marker exact và road bằng nhau, landmark lớn hơn/màu rose, ward lớn nhất.

- [ ] **Step 4: Commit release assets**

```powershell
git add templates/index.html tests/test_refactor_structure.py tests/test_listing_map_ui.py
git commit -m "chore: version multi-city filter assets"
```

- [ ] **Step 5: Push, deploy và xác minh production**

Run:

```powershell
git push origin main
.\scripts\deploy_production.ps1
.\scripts\verify_public_cache.ps1 -BaseUrl "https://radarbds.vn" -RequireCdn
```

Xác minh riêng:

- local HEAD = `origin/main` = `/opt/radar-bds/current` HEAD;
- `radar-bds.service` active;
- homepage, new JS/CSS assets, `/api/signals`, `/api/counts`, `/api/map-listings` trả HTTP 200;
- production browser smoke Tân An + Mỹ Phước giữ đúng URL/state và Maps;
- `.playwright-cli/` vẫn untracked và không nằm trong commit.
