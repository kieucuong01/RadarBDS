# Facebook Crawl Brokers Roster Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn `/admin/facebook-crawl?view=brokers` into a roster-first broker management workbench with scan-friendly status, complete local filters, safe profile links, explicit data states, and a compact responsive layout.

**Architecture:** Keep the existing Flask/Jinja/vanilla-JavaScript boundary and both focused APIs unchanged. Add pure exported roster helpers to `static/js/admin/facebook-crawl.js`, then make the existing DOM renderer consume that view model while preserving draft, revision-conflict, single-save, Run, Delete, and duplicate-suggestion behavior. Recompose only the Brokers markup and CSS, with source-contract tests plus real browser verification.

**Tech Stack:** Flask, Jinja2, vanilla JavaScript with CommonJS-compatible exports, Node `assert` tests, pytest source-contract tests, existing admin CSS tokens.

## Global Constraints

- Route remains `/admin/facebook-crawl?view=brokers`.
- Profiles remain loaded from `/admin/api/facebook-crawl/profiles`.
- Duplicate suggestions remain loaded independently from `/admin/api/facebook-crawl/duplicates`.
- Add, edit, delete, and duplicate suggestions update only `state.draft`; only `Lưu thay đổi` persists.
- Revision conflicts, unsaved-navigation protection, single-profile Run, and safe Delete confirmation remain intact.
- Summary counts are client-side only: Active is `profile.active !== false`; Due now is active plus `due_today === true`; Needs attention is active plus due now, missing quality score, or quality score below `68`.
- Filters stay client-side and do not enter the route URL.
- No API shape, database schema, frontend framework, font, icon library, or runtime dependency changes.
- Continue using DOM `textContent` and element creation; do not add `innerHTML`.
- Treat profile URLs as untrusted display data. Create an external link only for `http:` or `https:` URLs whose hostname is `facebook.com` or a `.facebook.com` subdomain; use `target="_blank"` and `rel="noopener noreferrer"`.
- Keep blue as the restrained action/focus accent and semantic colors paired with visible text.
- User-facing copy must not use em dashes.
- Desktop table semantics must remain valid; the 390-pixel viewport must have no page-level horizontal overflow and row actions must have at least 44-by-44-pixel targets.

## Security Boundary

- **Trust boundary:** profile fields arrive from an authenticated admin API and can also be edited in the drawer before entering the DOM.
- **Assets:** the admin session, profile configuration, crawl actions, and the operator's browser context.
- **Abuse cases:** stored markup in broker fields, a `javascript:` or off-domain URL disguised as a Facebook profile, tabnabbing from a new tab, and accidental persistence caused by a presentation-only interaction.
- **Controls:** render every field with `textContent`; allow external anchors only through `safeFacebookProfileLink`; add `noopener noreferrer`; preserve server-side admin authorization and explicit Save; do not fetch the displayed URL.
- There is no project-root `package.json` or lockfile and this plan adds no package, so `npm audit` is not an applicable gate. Node verification uses only built-in modules already used by the repository.

---

## File Structure

- `static/js/admin/facebook-crawl.js`: owns pure roster derivation, safe URL presentation, Brokers DOM rendering, local filters, drawer behavior, and duplicate-queue states.
- `templates/admin_control_room.html`: owns semantic Brokers workbench markup, stable element IDs, grouped form fields, and static asset version keys.
- `static/css/admin.css`: owns the roster workbench hierarchy, semantic state styling, dark theme, mobile record transformation, drawer scrim, and reduced-motion behavior.
- `tests/js/test_facebook_crawl_admin.js`: verifies pure derivation and security-sensitive URL behavior without a browser.
- `tests/test_admin_growth_ui.py`: verifies required template/CSS/JS contracts and asset cache-key changes.
- `tests/test_facebook_crawl_admin_api.py`: remains unchanged and serves as the focused backend regression gate.

---

### Task 1: Add the pure broker roster view model

**Files:**
- Modify: `tests/js/test_facebook_crawl_admin.js:1-157`
- Modify: `static/js/admin/facebook-crawl.js:8-236`
- Modify: `static/js/admin/facebook-crawl.js:1125-1148`

**Interfaces:**
- Produces: `brokerQualityState(profile) -> {key, score, label}`
- Produces: `brokerStatusState(profile) -> {key, label}`
- Produces: `brokerScheduleState(profile) -> {key, label, detail}`
- Produces: `safeFacebookProfileLink(rawUrl) -> {href, display} | null`
- Produces: `buildBrokerRosterViewModel(profiles, filters) -> {summary, filteredProfiles, resultCount, activeFilterCount, emptyState}`
- Consumes: existing profile fields `url`, `broker_name`, `city`, `active`, `crawl_every_days`, `due_today`, `next_due_date`, and `data_quality.score`.

- [ ] **Step 1: Write failing Node assertions for summary, filters, states, immutability, and hostile URLs**

Append these assertions before the final `console.log` in `tests/js/test_facebook_crawl_admin.js`:

```javascript
const rosterProfiles = [
  {
    url: 'https://www.facebook.com/broker-a/',
    broker_name: 'Broker A',
    city: 'Thủ Dầu Một',
    active: true,
    crawl_every_days: 1,
    due_today: true,
    next_due_date: '2026-08-11',
    data_quality: {score: 82, label: 'Tốt'},
  },
  {
    url: 'https://m.facebook.com/broker-b',
    broker_name: 'Broker B',
    city: 'Bến Cát',
    active: true,
    crawl_every_days: 3,
    due_today: false,
    next_due_date: '2026-08-13',
    data_quality: {score: 50, label: 'Cần xem'},
  },
  {
    url: 'https://www.facebook.com/broker-c',
    broker_name: 'Broker C',
    city: 'Bến Cát',
    active: false,
    crawl_every_days: 7,
    due_today: true,
    data_quality: {score: null},
  },
];
const rosterSnapshot = JSON.stringify(rosterProfiles);
const roster = api.buildBrokerRosterViewModel(rosterProfiles, {});
assert.deepEqual(roster.summary, {
  total: 3,
  active: 2,
  due: 1,
  needsAttention: 2,
});
assert.equal(roster.resultCount, 3);
assert.equal(roster.activeFilterCount, 0);
assert.equal(roster.emptyState, '');
assert.equal(JSON.stringify(rosterProfiles), rosterSnapshot);

const filteredRoster = api.buildBrokerRosterViewModel(rosterProfiles, {
  search: 'broker-b',
  city: 'Bến Cát',
  active: 'true',
  cadence: '3',
  due: 'false',
  quality: 'needs_attention',
});
assert.deepEqual(filteredRoster.filteredProfiles, [rosterProfiles[1]]);
assert.equal(filteredRoster.activeFilterCount, 6);
assert.equal(
  api.buildBrokerRosterViewModel([], {}).emptyState,
  'empty',
);
assert.equal(
  api.buildBrokerRosterViewModel(rosterProfiles, {search: 'không tồn tại'}).emptyState,
  'filtered',
);

assert.deepEqual(api.brokerStatusState(rosterProfiles[0]), {
  key: 'active',
  label: 'Đang bật',
});
assert.deepEqual(api.brokerStatusState(rosterProfiles[2]), {
  key: 'paused',
  label: 'Đã tắt',
});
assert.equal(api.brokerScheduleState(rosterProfiles[0]).key, 'due');
assert.equal(api.brokerScheduleState(rosterProfiles[1]).detail, '2026-08-13');
assert.equal(api.brokerQualityState(rosterProfiles[0]).key, 'good');
assert.equal(api.brokerQualityState(rosterProfiles[1]).key, 'needs_attention');
assert.equal(api.brokerQualityState(rosterProfiles[2]).score, null);

assert.deepEqual(
  api.safeFacebookProfileLink('https://www.facebook.com/broker-a/'),
  {
    href: 'https://www.facebook.com/broker-a/',
    display: 'facebook.com/broker-a',
  },
);
assert.equal(api.safeFacebookProfileLink('javascript:alert(1)'), null);
assert.equal(api.safeFacebookProfileLink('https://example.com/broker-a'), null);
```

- [ ] **Step 2: Run the Node contract test and confirm the new helper assertions fail**

Run:

```powershell
node --test tests/js/test_facebook_crawl_admin.js
```

Expected: FAIL because `buildBrokerRosterViewModel` and the related exported helpers do not exist.

- [ ] **Step 3: Add deterministic pure helpers above `buildRunPreview`**

Add this implementation to `static/js/admin/facebook-crawl.js` after `requestsForView`:

```javascript
  const BROKER_QUALITY_GOOD_THRESHOLD = 68;

  function brokerQualityState(profile) {
    const quality = profile && profile.data_quality && typeof profile.data_quality === 'object'
      ? profile.data_quality
      : {};
    const rawScore = quality.score;
    const hasScore = rawScore !== null
      && rawScore !== undefined
      && rawScore !== ''
      && Number.isFinite(Number(rawScore));
    if (!hasScore) {
      return {key: 'needs_attention', score: null, label: 'Chưa đủ mẫu'};
    }
    const score = Math.max(0, Math.min(100, Math.round(Number(rawScore))));
    const key = score >= BROKER_QUALITY_GOOD_THRESHOLD ? 'good' : 'needs_attention';
    return {
      key,
      score,
      label: String(quality.label || (key === 'good' ? 'Ổn' : 'Cần xem')),
    };
  }

  function brokerStatusState(profile) {
    return profile && profile.active === false
      ? {key: 'paused', label: 'Đã tắt'}
      : {key: 'active', label: 'Đang bật'};
  }

  function brokerScheduleState(profile) {
    if (profile && profile.due_today === true) {
      return {
        key: 'due',
        label: 'Đến lịch hôm nay',
        detail: String(profile.next_due_date || 'Sẵn sàng chạy'),
      };
    }
    return {
      key: 'scheduled',
      label: 'Kế tiếp',
      detail: String(profile && profile.next_due_date || 'Chưa có lịch'),
    };
  }

  function safeFacebookProfileLink(rawUrl) {
    const value = String(rawUrl || '').trim();
    if (!value) return null;
    try {
      const parsed = new URL(value);
      const hostname = parsed.hostname.toLowerCase();
      const allowedHost = hostname === 'facebook.com' || hostname.endsWith('.facebook.com');
      if (!['http:', 'https:'].includes(parsed.protocol) || !allowedHost) return null;
      const pathname = parsed.pathname.replace(/\/+$/, '');
      return {
        href: parsed.href,
        display: `facebook.com${pathname}`,
      };
    } catch (_error) {
      return null;
    }
  }

  function buildBrokerRosterViewModel(profiles, filters) {
    const source = Array.isArray(profiles) ? profiles : [];
    const selected = {
      search: String(filters && filters.search || '').trim().toLocaleLowerCase('vi'),
      city: String(filters && filters.city || ''),
      active: String(filters && filters.active || ''),
      cadence: String(filters && filters.cadence || ''),
      due: String(filters && filters.due || ''),
      quality: String(filters && filters.quality || ''),
    };
    const activeFilterCount = Object.values(selected).filter(Boolean).length;
    const activeProfiles = source.filter((profile) => profile.active !== false);
    const filteredProfiles = source.filter((profile) => {
      const haystack = `${profile.broker_name || ''} ${profile.url || ''}`
        .toLocaleLowerCase('vi');
      if (selected.search && !haystack.includes(selected.search)) return false;
      if (selected.city && profile.city !== selected.city) return false;
      if (selected.active && String(profile.active !== false) !== selected.active) return false;
      if (selected.cadence
        && String(Number(profile.crawl_every_days || 1)) !== selected.cadence) return false;
      if (selected.due && String(Boolean(profile.due_today)) !== selected.due) return false;
      if (selected.quality && brokerQualityState(profile).key !== selected.quality) return false;
      return true;
    });
    const needsAttention = activeProfiles.filter((profile) => (
      profile.due_today === true || brokerQualityState(profile).key === 'needs_attention'
    )).length;
    return {
      summary: {
        total: source.length,
        active: activeProfiles.length,
        due: activeProfiles.filter((profile) => profile.due_today === true).length,
        needsAttention,
      },
      filteredProfiles,
      resultCount: filteredProfiles.length,
      activeFilterCount,
      emptyState: source.length === 0 ? 'empty' : (filteredProfiles.length === 0 ? 'filtered' : ''),
    };
  }
```

Export the five helpers in the bottom `api` object:

```javascript
    brokerQualityState,
    brokerStatusState,
    brokerScheduleState,
    safeFacebookProfileLink,
    buildBrokerRosterViewModel,
```

- [ ] **Step 4: Run syntax and Node tests**

Run:

```powershell
node --check static/js/admin/facebook-crawl.js
node --test tests/js/test_facebook_crawl_admin.js
```

Expected: both commands exit 0 and the test prints `facebook crawl admin contracts: ok`.

- [ ] **Step 5: Commit the pure view-model slice**

```powershell
git add -- static/js/admin/facebook-crawl.js tests/js/test_facebook_crawl_admin.js
git commit -m "feat: derive facebook broker roster states"
```

---

### Task 2: Recompose and render the roster-first workbench

**Files:**
- Modify: `templates/admin_control_room.html:498-554`
- Modify: `static/js/admin/facebook-crawl.js:565-686`
- Modify: `static/js/admin/facebook-crawl.js:1047-1057`
- Modify: `tests/test_admin_growth_ui.py:241-275`
- Modify: `tests/js/test_facebook_crawl_admin.js:1-190`

**Interfaces:**
- Consumes: Task 1 helpers and their exact return shapes.
- Produces: `readBrokerFilters() -> {search, city, active, cadence, due, quality}`
- Produces: `renderProfiles()` that updates summary, result count, filter count, reset state, empty state, and semantic rows without mutating the draft.
- Preserves: existing `openDrawer(index)`, Run preselection, safe Delete confirmation, `renderRunProfiles()`, and `syncDirty()` callbacks.

- [ ] **Step 1: Add failing source-contract assertions for the workbench**

Add a new pytest test after `test_facebook_crawl_mobile_drawer_stays_in_viewport_with_touch_sized_actions`:

```python
def test_facebook_brokers_has_roster_workbench_semantics():
    template = (ROOT / "templates" / "admin_control_room.html").read_text(
        encoding="utf-8"
    )
    source = (
        ROOT / "static" / "js" / "admin" / "facebook-crawl.js"
    ).read_text(encoding="utf-8")

    required_ids = (
        "crawlBrokerWorkbench",
        "crawlBrokerSummary",
        "crawlBrokerTotal",
        "crawlBrokerActive",
        "crawlBrokerDue",
        "crawlBrokerAttention",
        "crawlBrokerFilters",
        "crawlBrokerFilterCount",
        "crawlBrokerResetBtn",
        "crawlBrokerTableHelp",
    )
    for element_id in required_ids:
        assert f'id="{element_id}"' in template
    assert 'aria-describedby="crawlBrokerTableHelp"' in template
    assert "function readBrokerFilters" in source
    assert "buildBrokerRosterViewModel(state.draft, readBrokerFilters())" in source
    assert "safeFacebookProfileLink(profile.url)" in source
    assert "noopener noreferrer" in source
    assert "cell.dataset.label = label" in source
    assert ".innerHTML =" not in source
```

Append these source assertions before the final `console.log` in the Node test:

```javascript
assert.match(source, /crawlBrokerResetBtn/);
assert.match(source, /buildBrokerRosterViewModel\(state\.draft, readBrokerFilters\(\)\)/);
assert.match(source, /safeFacebookProfileLink\(profile\.url\)/);
assert.match(source, /noopener noreferrer/);
```

- [ ] **Step 2: Run focused tests and confirm the new roster contract fails**

Run:

```powershell
node --test tests/js/test_facebook_crawl_admin.js
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -X utf8 -m pytest tests/test_admin_growth_ui.py::test_facebook_brokers_has_roster_workbench_semantics -q
```

Expected: both fail on missing workbench IDs and rendering hooks.

- [ ] **Step 3: Replace the Brokers heading, summary, filters, meta, and table wrapper with semantic markup**

Keep the existing conflict banner and existing control IDs. Replace the heading through table wrapper with this structure:

```html
<div id="crawlBrokerWorkbench" class="crawl-broker-workbench">
  <div class="crawl-view-heading crawl-broker-heading">
    <div>
      <span class="crawl-section-kicker">Roster vận hành</span>
      <h2>Danh sách môi giới</h2>
      <p>Tìm nhanh, kiểm tra lịch crawl và chỉnh bản nháp trước khi lưu.</p>
    </div>
    <div class="crawl-view-actions">
      <span id="crawlUnsavedBadge" class="crawl-unsaved-badge" hidden>Chưa lưu</span>
      <button class="secondary-btn" id="crawlAddBrokerBtn" type="button">Thêm môi giới</button>
      <button class="primary-btn" id="crawlSaveProfilesBtn" type="button" disabled>Lưu thay đổi</button>
    </div>
  </div>

  <dl id="crawlBrokerSummary" class="crawl-broker-summary" aria-label="Tóm tắt danh sách môi giới">
    <div><dt>Tổng số</dt><dd id="crawlBrokerTotal">0</dd></div>
    <div><dt>Đang bật</dt><dd id="crawlBrokerActive">0</dd></div>
    <div><dt>Đến lịch</dt><dd id="crawlBrokerDue">0</dd></div>
    <div class="is-attention"><dt>Cần chú ý</dt><dd id="crawlBrokerAttention">0</dd></div>
  </dl>

  <section id="crawlBrokerFilters" class="surface crawl-broker-filters" aria-label="Tìm và lọc môi giới">
    <label class="crawl-search-field">Tìm môi giới hoặc URL
      <input id="crawlBrokerSearch" type="search" placeholder="Nhập tên hoặc facebook.com/…">
    </label>
    <div class="crawl-filter-head">
      <strong>Bộ lọc</strong>
      <span id="crawlBrokerFilterCount" class="crawl-filter-count">0 đang áp dụng</span>
      <button class="secondary-btn crawl-filter-reset" id="crawlBrokerResetBtn" type="button" disabled>Đặt lại</button>
    </div>
    <div class="crawl-filter-rail">
      <label>Thành phố<select id="crawlBrokerCityFilter"><option value="">Tất cả thành phố</option></select></label>
      <label>Trạng thái<select id="crawlBrokerActiveFilter"><option value="">Tất cả</option><option value="true">Đang bật</option><option value="false">Đã tắt</option></select></label>
      <label>Chu kỳ<select id="crawlBrokerCadenceFilter"><option value="">Tất cả</option><option value="1">Mỗi ngày</option><option value="3">3 ngày/lần</option><option value="7">7 ngày/lần</option></select></label>
      <label>Đến lịch<select id="crawlBrokerDueFilter"><option value="">Tất cả</option><option value="true">Hôm nay</option><option value="false">Chưa đến lịch</option></select></label>
      <label>Chất lượng<select id="crawlBrokerQualityFilter"><option value="">Tất cả</option><option value="good">Ổn</option><option value="needs_attention">Cần xem</option></select></label>
    </div>
  </section>

  <div class="crawl-broker-meta">
    <span id="crawlBrokerCount">0 / 0 môi giới</span>
    <span id="crawlBrokerStatus" role="status" aria-live="polite"></span>
  </div>
  <p id="crawlBrokerTableHelp" class="sr-only">Bảng môi giới. Các thao tác sửa, chạy và xóa nằm ở cuối mỗi dòng.</p>
  <div class="surface crawl-broker-table-wrap">
    <table class="data-table crawl-broker-table" aria-describedby="crawlBrokerTableHelp">
      <thead>
        <tr>
          <th scope="col">Môi giới</th>
          <th scope="col">Trạng thái</th>
          <th scope="col">Lịch kế tiếp</th>
          <th scope="col">Quota / chu kỳ</th>
          <th scope="col">Chất lượng</th>
          <th scope="col">Lần crawl cuối</th>
          <th scope="col">Thao tác</th>
        </tr>
      </thead>
      <tbody id="crawlBrokerRows"></tbody>
    </table>
  </div>
</div>
```

Place the existing conflict banner after the heading and before the summary inside `crawlBrokerWorkbench`, so conflict feedback remains prominent without separating the toolbar from the roster.

- [ ] **Step 4: Replace DOM-coupled filtering with the pure view model and render semantic row content**

Add:

```javascript
    function readBrokerFilters() {
      return {
        search: byId('crawlBrokerSearch').value,
        city: byId('crawlBrokerCityFilter').value,
        active: byId('crawlBrokerActiveFilter').value,
        cadence: byId('crawlBrokerCadenceFilter').value,
        due: byId('crawlBrokerDueFilter').value,
        quality: byId('crawlBrokerQualityFilter').value,
      };
    }

    function resetBrokerFilters() {
      [
        'crawlBrokerSearch',
        'crawlBrokerCityFilter',
        'crawlBrokerActiveFilter',
        'crawlBrokerCadenceFilter',
        'crawlBrokerDueFilter',
        'crawlBrokerQualityFilter',
      ].forEach((id) => {
        byId(id).value = '';
      });
      renderProfiles();
      byId('crawlBrokerSearch').focus();
    }

    function brokerCell(label, className) {
      const cell = document.createElement('td');
      cell.dataset.label = label;
      if (className) cell.className = className;
      return cell;
    }

    function renderBrokerBadge(stateValue, prefix) {
      const badge = document.createElement('span');
      badge.className = `crawl-broker-badge ${prefix}-${stateValue.key}`;
      badge.textContent = stateValue.label;
      return badge;
    }

    function renderBrokerSystemRow(kind, titleText, detailText, actionLabel, onAction) {
      const rows = byId('crawlBrokerRows');
      clear(rows);
      const row = document.createElement('tr');
      const cell = brokerCell('Trạng thái', `crawl-broker-empty state-${kind}`);
      cell.colSpan = 7;
      const title = document.createElement('strong');
      title.textContent = titleText;
      const detail = document.createElement('span');
      detail.textContent = detailText;
      cell.append(title, detail);
      if (actionLabel && onAction) {
        cell.appendChild(button(actionLabel, 'secondary-btn', onAction));
      }
      row.appendChild(cell);
      rows.appendChild(row);
    }
```

Inside `renderProfiles()`, replace `filteredProfiles()` and the positional `cells` array with:

```javascript
      const viewModel = buildBrokerRosterViewModel(state.draft, readBrokerFilters());
      text(byId('crawlBrokerTotal'), viewModel.summary.total);
      text(byId('crawlBrokerActive'), viewModel.summary.active);
      text(byId('crawlBrokerDue'), viewModel.summary.due);
      text(byId('crawlBrokerAttention'), viewModel.summary.needsAttention);
      text(byId('crawlBrokerCount'), `${viewModel.resultCount} / ${viewModel.summary.total} môi giới`);
      text(
        byId('crawlBrokerFilterCount'),
        `${viewModel.activeFilterCount} đang áp dụng`,
      );
      byId('crawlBrokerResetBtn').disabled = viewModel.activeFilterCount === 0;

      if (viewModel.emptyState) {
        const row = document.createElement('tr');
        const cell = brokerCell('Trạng thái', 'crawl-broker-empty');
        cell.colSpan = 7;
        const title = document.createElement('strong');
        title.textContent = viewModel.emptyState === 'empty'
          ? 'Chưa có môi giới trong danh sách'
          : 'Không có môi giới phù hợp bộ lọc';
        const detail = document.createElement('span');
        detail.textContent = viewModel.emptyState === 'empty'
          ? 'Thêm môi giới đầu tiên để cấu hình lịch crawl.'
          : 'Đặt lại bộ lọc hoặc thử một từ khóa khác.';
        cell.append(title, detail);
        if (viewModel.emptyState === 'filtered') {
          cell.appendChild(button('Đặt lại bộ lọc', 'secondary-btn', resetBrokerFilters));
        } else {
          cell.appendChild(button('Thêm môi giới', 'secondary-btn', () => openDrawer(null)));
        }
        row.appendChild(cell);
        rows.appendChild(row);
        return;
      }
```

For every profile, create seven labeled cells. The identity cell must create a `strong`, a city `small`, and either a safe anchor or a plain text URL:

```javascript
        const identity = brokerCell('Môi giới', 'crawl-broker-identity-cell');
        const identityStack = document.createElement('div');
        identityStack.className = 'crawl-broker-identity';
        const brokerName = document.createElement('strong');
        brokerName.textContent = profile.broker_name || 'Chưa đặt tên';
        const brokerCity = document.createElement('small');
        brokerCity.textContent = profile.city || 'Chưa có khu vực';
        const safeLink = safeFacebookProfileLink(profile.url);
        const brokerUrl = document.createElement(safeLink ? 'a' : 'span');
        brokerUrl.className = 'crawl-broker-url';
        brokerUrl.textContent = safeLink ? safeLink.display : String(profile.url || 'URL chưa hợp lệ');
        brokerUrl.title = String(profile.url || '');
        if (safeLink) {
          brokerUrl.href = safeLink.href;
          brokerUrl.target = '_blank';
          brokerUrl.rel = 'noopener noreferrer';
        }
        identityStack.append(brokerName, brokerCity, brokerUrl);
        identity.appendChild(identityStack);

        const statusState = brokerStatusState(profile);
        const statusCell = brokerCell('Trạng thái', 'crawl-broker-state');
        statusCell.appendChild(renderBrokerBadge(statusState, 'status'));

        const scheduleState = brokerScheduleState(profile);
        const scheduleCell = brokerCell('Lịch kế tiếp', 'crawl-broker-schedule');
        scheduleCell.appendChild(renderBrokerBadge(scheduleState, 'schedule'));
        const scheduleDetail = document.createElement('small');
        scheduleDetail.textContent = scheduleState.detail;
        scheduleCell.appendChild(scheduleDetail);

        const planCell = brokerCell('Quota / chu kỳ', 'crawl-broker-plan');
        const quota = document.createElement('strong');
        quota.textContent = `${Number(profile.daily_limit || 20)} bài/ngày`;
        const cadence = document.createElement('small');
        cadence.textContent = `${Number(profile.crawl_every_days || 1)} ngày/lần`;
        planCell.append(quota, cadence);

        const qualityState = brokerQualityState(profile);
        const qualityCell = brokerCell('Chất lượng', `crawl-broker-quality quality-${qualityState.key}`);
        qualityCell.appendChild(renderBrokerBadge(qualityState, 'quality'));
        const qualityScore = document.createElement('small');
        qualityScore.textContent = qualityState.score == null
          ? 'Chưa có điểm'
          : `${qualityState.score}/100`;
        qualityCell.appendChild(qualityScore);

        const latestCell = brokerCell('Crawl cuối', 'crawl-broker-latest');
        latestCell.textContent = profile.latest_crawled_at || 'Chưa crawl';

        const actions = brokerCell('Thao tác', 'crawl-row-actions crawl-broker-actions');
```

Append the existing Sửa, Chạy, and Xóa buttons to `actions` with their current callbacks, then append all seven cells in this order:

```javascript
        row.classList.toggle(
          'needs-attention',
          profile.active !== false
            && (profile.due_today === true || qualityState.key === 'needs_attention'),
        );
        row.append(
          identity,
          statusCell,
          scheduleCell,
          planCell,
          qualityCell,
          latestCell,
          actions,
        );
```

Delete the obsolete `qualityLabel()` and `filteredProfiles()` functions.

- [ ] **Step 5: Bind reset and retain the six existing local filter listeners**

Add this line beside the existing filter binding in `bind()`:

```javascript
      byId('crawlBrokerResetBtn').addEventListener('click', resetBrokerFilters);
```

- [ ] **Step 6: Make roster loading and error states preserve prior data**

At the start of `loadProfiles(force)`, set the workbench busy state and show a table loading row only when no prior roster is available:

```javascript
      const workbench = byId('crawlBrokerWorkbench');
      workbench.setAttribute('aria-busy', 'true');
      text(byId('crawlBrokerStatus'), 'Đang tải danh sách môi giới…');
      if (!state.profilesLoaded) {
        renderBrokerSystemRow(
          'loading',
          'Đang tải danh sách môi giới',
          'Dữ liệu sẽ xuất hiện ngay khi máy chủ phản hồi.',
        );
      }
```

After a successful payload is rendered, clear the busy state and use the existing success copy:

```javascript
        workbench.setAttribute('aria-busy', 'false');
        text(byId('crawlBrokerStatus'), 'Đã cập nhật');
```

Replace the catch block with behavior that keeps old rows during a failed refresh and offers retry after an initial failure:

```javascript
      } catch (_error) {
        workbench.setAttribute('aria-busy', 'false');
        if (state.profilesLoaded) {
          renderProfiles();
          text(
            byId('crawlBrokerStatus'),
            'Không thể làm mới. Danh sách đang hiển thị là dữ liệu gần nhất.',
          );
        } else {
          renderBrokerSystemRow(
            'error',
            'Không tải được danh sách môi giới',
            'Kiểm tra kết nối rồi thử lại.',
            'Thử lại',
            () => loadProfiles(true),
          );
          text(byId('crawlBrokerStatus'), 'Không tải được danh sách môi giới.');
        }
      }
```

Extend `test_facebook_brokers_has_roster_workbench_semantics` with:

```python
    assert "function renderBrokerSystemRow" in source
    assert "Danh sách đang hiển thị là dữ liệu gần nhất" in source
    assert 'workbench.setAttribute(\'aria-busy\', \'true\')' in source
```

- [ ] **Step 7: Run focused tests**

Run:

```powershell
node --check static/js/admin/facebook-crawl.js
node --test tests/js/test_facebook_crawl_admin.js
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -X utf8 -m pytest tests/test_admin_growth_ui.py::test_facebook_brokers_has_roster_workbench_semantics tests/test_admin_growth_ui.py::test_facebook_broker_actions_have_explicit_safe_delete_and_responsive_styles -q
```

Expected: all commands exit 0.

- [ ] **Step 8: Commit the roster workbench behavior**

```powershell
git add -- templates/admin_control_room.html static/js/admin/facebook-crawl.js tests/js/test_facebook_crawl_admin.js tests/test_admin_growth_ui.py
git commit -m "feat: build facebook broker roster workbench"
```

---

### Task 3: Make duplicate and drawer states explicit and accessible

**Files:**
- Modify: `templates/admin_control_room.html:555-587`
- Modify: `static/js/admin/facebook-crawl.js:687-824`
- Modify: `static/js/admin/facebook-crawl.js:1034-1067`
- Modify: `tests/test_admin_growth_ui.py:269-330`
- Modify: `tests/js/test_facebook_crawl_admin.js:1-210`

**Interfaces:**
- Produces: `duplicatePresentationState(page, error) -> 'loading' | 'error' | 'empty' | 'ready'`
- Produces: `setDuplicateState(kind, message)` for the existing duplicate live region.
- Preserves: duplicate actionable/all toggle, accumulated load-more items, cadence suggestion mutation, draft dirty state, and drawer apply-to-draft semantics.

- [ ] **Step 1: Add failing state and accessibility tests**

Append to `tests/js/test_facebook_crawl_admin.js`:

```javascript
assert.equal(api.duplicatePresentationState(null, false), 'loading');
assert.equal(api.duplicatePresentationState(null, true), 'error');
assert.equal(api.duplicatePresentationState({items: []}, false), 'empty');
assert.equal(api.duplicatePresentationState({items: [{}]}, false), 'ready');
assert.match(source, /crawlBrokerDrawerBackdrop/);
assert.match(source, /event\.key === 'Escape'/);
assert.match(source, /event\.key !== 'Tab'/);
```

Add this pytest test:

```python
def test_facebook_brokers_duplicate_queue_and_drawer_expose_states():
    template = (ROOT / "templates" / "admin_control_room.html").read_text(
        encoding="utf-8"
    )
    source = (
        ROOT / "static" / "js" / "admin" / "facebook-crawl.js"
    ).read_text(encoding="utf-8")

    for element_id in (
        "crawlDuplicateState",
        "crawlBrokerDrawerBackdrop",
        "crawlDrawerIdentity",
        "crawlDrawerSchedule",
        "crawlDrawerLimits",
    ):
        assert f'id="{element_id}"' in template
    drawer_start = template.index('id="crawlBrokerDrawer"')
    drawer_end = template.index("</aside>", drawer_start)
    drawer = template[drawer_start:drawer_end]
    assert 'role="dialog"' in drawer
    assert 'aria-modal="true"' in drawer
    assert "function setDuplicateState" in source
    assert "duplicatePresentationState" in source
    assert "drawerReturnFocus" in source
```

- [ ] **Step 2: Run tests and confirm missing state helpers and markup fail**

Run:

```powershell
node --test tests/js/test_facebook_crawl_admin.js
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -X utf8 -m pytest tests/test_admin_growth_ui.py::test_facebook_brokers_duplicate_queue_and_drawer_expose_states -q
```

Expected: FAIL on `duplicatePresentationState`, duplicate-state markup, and drawer accessibility hooks.

- [ ] **Step 3: Add duplicate-state markup and group the existing drawer fields**

Add this live region between `crawlDuplicateSummary` and `crawlDuplicateList`:

```html
<p id="crawlDuplicateState" class="crawl-duplicate-state" role="status" aria-live="polite">Đang tải phân tích trùng…</p>
```

Add a drawer backdrop immediately before the drawer:

```html
<button id="crawlBrokerDrawerBackdrop" class="crawl-drawer-backdrop" type="button" tabindex="-1" aria-label="Đóng ngăn chỉnh sửa" hidden></button>
```

Change the drawer opening tag and group its unchanged controls:

```html
<aside id="crawlBrokerDrawer" class="crawl-broker-drawer" role="dialog" aria-modal="true" aria-labelledby="crawlDrawerTitle" hidden>
  <div class="crawl-drawer-head">
    <div>
      <span class="crawl-section-kicker">Bản nháp môi giới</span>
      <h3 id="crawlDrawerTitle">Thông tin môi giới</h3>
    </div>
    <button class="icon-btn" id="crawlDrawerCloseBtn" type="button" aria-label="Đóng">×</button>
  </div>
  <div class="crawl-drawer-fields">
    <fieldset id="crawlDrawerIdentity" class="crawl-drawer-group">
      <legend>Nhận diện</legend>
      <label>Tên môi giới<input id="crawlDrawerName" maxlength="160"></label>
      <label>URL Facebook<input id="crawlDrawerUrl" inputmode="url" placeholder="https://www.facebook.com/…"></label>
      <label>Thành phố<input id="crawlDrawerCity" maxlength="100"></label>
    </fieldset>
    <fieldset id="crawlDrawerSchedule" class="crawl-drawer-group">
      <legend>Lịch crawl</legend>
      <label class="toggle-line"><input id="crawlDrawerActive" type="checkbox"><span>Bật crawl tự động</span></label>
      <label>Chu kỳ<select id="crawlDrawerCadence"><option value="1">Mỗi ngày</option><option value="3">3 ngày/lần</option><option value="7">7 ngày/lần</option></select></label>
    </fieldset>
    <fieldset id="crawlDrawerLimits" class="crawl-drawer-group">
      <legend>Giới hạn thu thập</legend>
      <label>Giới hạn bài/ngày<input id="crawlDrawerLimit" type="number" min="1" max="500"></label>
      <label>Số ngày khi chạy range<input id="crawlDrawerRange" type="number" min="1" max="60"></label>
    </fieldset>
    <p id="crawlDrawerError" class="crawl-field-error" aria-live="polite"></p>
  </div>
  <div class="crawl-drawer-actions">
    <button class="secondary-btn" id="crawlDrawerCancelBtn" type="button">Hủy</button>
    <button class="primary-btn" id="crawlDrawerSaveBtn" type="button">Áp dụng vào bản nháp</button>
  </div>
</aside>
```

- [ ] **Step 4: Add duplicate presentation derivation and explicit loading, empty, and error rendering**

Add this pure helper beside `nextDuplicateOffset` and export it:

```javascript
  function duplicatePresentationState(page, error) {
    if (error) return 'error';
    if (!page) return 'loading';
    return Array.isArray(page.items) && page.items.length ? 'ready' : 'empty';
  }
```

Inside `create()`, add:

```javascript
    function setDuplicateState(kind, message) {
      const stateNode = byId('crawlDuplicateState');
      stateNode.dataset.state = kind;
      stateNode.hidden = kind === 'ready';
      text(stateNode, message);
    }
```

At the beginning of `loadDuplicates(append)`, use:

```javascript
      setDuplicateState('loading', append ? 'Đang tải thêm cặp trùng…' : 'Đang tải phân tích trùng…');
```

After merging the page and before `renderDuplicates`, derive and show the state:

```javascript
        const presentation = duplicatePresentationState(page, false);
        setDuplicateState(
          presentation,
          presentation === 'empty'
            ? 'Không có cặp môi giới phù hợp phạm vi đang xem.'
            : '',
        );
```

In the catch block, keep existing rendered cards when `append` fails, hide the load-more control, and show:

```javascript
        setDuplicateState('error', 'Không tải được phân tích trùng. Thử lại bằng nút chuyển phạm vi.');
        text(byId('crawlDuplicateSummary'), 'Phân tích trùng tạm thời chưa khả dụng.');
        byId('crawlDuplicateMoreBtn').hidden = true;
```

- [ ] **Step 5: Add drawer scrim, keyboard containment, error reset, and focus return**

Add `drawerReturnFocus: null` to `state`. Update `openDrawer`:

```javascript
      state.drawerReturnFocus = root.ownerDocument.activeElement;
      text(byId('crawlDrawerError'), '');
      byId('crawlBrokerDrawerBackdrop').hidden = false;
      const drawer = byId('crawlBrokerDrawer');
      drawer.hidden = false;
      byId('crawlDrawerName').focus();
```

Update `closeDrawer`:

```javascript
      byId('crawlBrokerDrawer').hidden = true;
      byId('crawlBrokerDrawerBackdrop').hidden = true;
      state.drawerIndex = null;
      const returnFocus = state.drawerReturnFocus;
      state.drawerReturnFocus = null;
      if (returnFocus && typeof returnFocus.focus === 'function') returnFocus.focus();
```

Bind the backdrop and contain keyboard focus while the modal drawer is open:

```javascript
      byId('crawlBrokerDrawerBackdrop').addEventListener('click', closeDrawer);
      root.addEventListener('keydown', (event) => {
        const drawer = byId('crawlBrokerDrawer');
        if (drawer.hidden) return;
        if (event.key === 'Escape') {
          closeDrawer();
          return;
        }
        if (event.key !== 'Tab') return;
        const controls = [...drawer.querySelectorAll(
          'button:not([disabled]), input:not([disabled]), select:not([disabled])',
        )].filter((control) => !control.hidden);
        if (!controls.length) return;
        const first = controls[0];
        const last = controls[controls.length - 1];
        if (event.shiftKey && root.ownerDocument.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && root.ownerDocument.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      });
```

- [ ] **Step 6: Run focused tests**

Run:

```powershell
node --check static/js/admin/facebook-crawl.js
node --test tests/js/test_facebook_crawl_admin.js
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -X utf8 -m pytest tests/test_admin_growth_ui.py::test_facebook_brokers_duplicate_queue_and_drawer_expose_states tests/test_admin_growth_ui.py::test_facebook_crawl_mobile_drawer_stays_in_viewport_with_touch_sized_actions -q
```

Expected: all commands exit 0.

- [ ] **Step 7: Commit duplicate and drawer state handling**

```powershell
git add -- templates/admin_control_room.html static/js/admin/facebook-crawl.js tests/js/test_facebook_crawl_admin.js tests/test_admin_growth_ui.py
git commit -m "feat: clarify facebook broker secondary states"
```

---

### Task 4: Apply the roster visual system and responsive behavior

**Files:**
- Modify: `static/css/admin.css:3570-3726`
- Modify: `templates/admin_control_room.html:11`
- Modify: `templates/admin_control_room.html:1081`
- Modify: `tests/test_admin_growth_ui.py:241-330`

**Interfaces:**
- Consumes: Task 2 classes `crawl-broker-workbench`, `crawl-broker-summary`, `crawl-broker-filters`, `crawl-filter-rail`, semantic badge/state classes, and `data-label`.
- Consumes: Task 3 classes `crawl-duplicate-state`, `crawl-drawer-backdrop`, and `crawl-drawer-group`.
- Produces: desktop roster hierarchy, dark-theme semantic colors, mobile broker records, 44-pixel actions, and new cache keys.

- [ ] **Step 1: Add failing CSS and asset-version assertions**

Extend `test_facebook_crawl_admin_is_task_first_and_loads_focused_module`:

```python
    assert "?v=admin-facebook-crawl-brokers-v2" in template
    assert "css/admin.css') }}?v=admin-v55-facebook-crawl-brokers" in template
```

Add:

```python
def test_facebook_broker_roster_is_dense_semantic_and_mobile_safe():
    css = (ROOT / "static" / "css" / "admin.css").read_text(encoding="utf-8")
    roster_css = css[css.index(".crawl-broker-workbench"):]

    for selector in (
        ".crawl-broker-summary",
        ".crawl-broker-filters",
        ".crawl-filter-rail",
        ".crawl-broker-badge",
        ".crawl-broker-url",
        ".crawl-broker-empty",
        ".crawl-duplicate-state",
        ".crawl-drawer-backdrop",
        ".crawl-drawer-group",
    ):
        assert selector in roster_css
    assert '[data-label]::before' in roster_css
    assert ".crawl-broker-metric:nth-child" not in roster_css
    assert '[data-theme="dark"] .crawl-broker-badge' in roster_css
    mobile_css = roster_css[roster_css.index("@media (max-width: 760px)"):]
    assert "grid-template-columns: 1fr 1fr;" in mobile_css
    assert "min-height: 44px" in mobile_css
```

- [ ] **Step 2: Run the focused CSS contracts and confirm they fail**

Run:

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -X utf8 -m pytest tests/test_admin_growth_ui.py::test_facebook_crawl_admin_is_task_first_and_loads_focused_module tests/test_admin_growth_ui.py::test_facebook_broker_roster_is_dense_semantic_and_mobile_safe -q
```

Expected: FAIL on old cache keys and missing roster selectors.

- [ ] **Step 3: Replace the old broker toolbar/table positional styling**

Remove `.crawl-broker-toolbar`, `.crawl-broker-metric:nth-child(...)`, and mobile `td:nth-child(...)::before` rules. Add these desktop foundations using existing variables:

```css
.crawl-broker-workbench { display: grid; gap: 14px; }
.crawl-section-kicker {
  display: block; margin-bottom: 5px; color: var(--blue);
  font-size: 11px; font-weight: 900; letter-spacing: .08em; text-transform: uppercase;
}
.crawl-broker-summary {
  display: grid; grid-template-columns: repeat(4, minmax(0, 1fr));
  margin: 0; border: 1px solid var(--line); border-radius: 12px; background: var(--panel);
}
.crawl-broker-summary > div { padding: 12px 14px; border-right: 1px solid var(--line); }
.crawl-broker-summary > div:last-child { border-right: 0; }
.crawl-broker-summary dt { color: var(--muted); font-size: 11px; font-weight: 800; }
.crawl-broker-summary dd { margin: 4px 0 0; color: var(--ink); font-size: 20px; font-weight: 900; }
.crawl-broker-summary .is-attention dd { color: #b45309; }
.crawl-broker-filters { display: grid; grid-template-columns: minmax(260px, 1.4fr) minmax(0, 2fr); gap: 12px; padding: 14px; }
.crawl-broker-filters label {
  display: grid; gap: 6px; color: var(--muted); font-size: 12px; font-weight: 800;
}
.crawl-broker-filters input, .crawl-broker-filters select {
  width: 100%; min-height: 44px; padding: 9px 11px;
  border: 1px solid var(--line); border-radius: 9px; background: var(--panel); color: var(--ink); font: inherit;
}
.crawl-search-field { grid-row: 1 / span 2; }
.crawl-filter-head { display: flex; align-items: center; gap: 9px; min-width: 0; }
.crawl-filter-count { color: var(--muted); font-size: 12px; font-weight: 700; }
.crawl-filter-reset { margin-left: auto; min-height: 36px; padding: 6px 10px; }
.crawl-filter-rail { display: grid; grid-template-columns: repeat(5, minmax(112px, 1fr)); gap: 8px; }
.crawl-broker-table-wrap { padding: 0; overflow-x: auto; }
.crawl-broker-table { min-width: 1040px; }
.crawl-broker-table td { vertical-align: middle; }
.crawl-broker-table tbody tr { position: relative; transition: background-color .18s ease; }
.crawl-broker-table tbody tr:hover { background: #f8fbff; }
.crawl-broker-table tbody tr.needs-attention::before {
  position: absolute; inset: 12px auto 12px 0; width: 3px;
  border-radius: 0 3px 3px 0; background: #f59e0b; content: "";
}
.crawl-broker-identity { display: grid; gap: 2px; min-width: 180px; }
.crawl-broker-identity strong { color: var(--ink); font-size: 14px; line-height: 1.4; }
.crawl-broker-identity small, .crawl-broker-schedule small,
.crawl-broker-plan small, .crawl-broker-quality small {
  color: var(--muted); font-size: 11.5px; line-height: 1.4;
}
.crawl-broker-url {
  display: block; max-width: 220px; overflow: hidden; color: var(--blue);
  font-size: 11.5px; font-weight: 700; text-overflow: ellipsis; white-space: nowrap;
}
.crawl-broker-state, .crawl-broker-schedule,
.crawl-broker-plan, .crawl-broker-quality { display: grid; gap: 5px; justify-items: start; }
.crawl-broker-plan strong { color: var(--ink); font-size: 12.5px; }
.crawl-broker-badge {
  display: inline-flex; align-items: center; min-height: 26px; padding: 4px 8px;
  border-radius: 7px; font-size: 11.5px; font-weight: 850; line-height: 1.2;
}
.status-active, .quality-good { color: #166534; background: #dcfce7; }
.status-paused { color: #475569; background: #e2e8f0; }
.schedule-due, .quality-needs_attention { color: #92400e; background: #fef3c7; }
.schedule-scheduled { color: #1d4ed8; background: #dbeafe; }
.crawl-broker-latest { color: #475569; font-size: 12px; font-weight: 700; }
.crawl-broker-empty { padding: 34px 18px !important; text-align: center; }
.crawl-broker-empty strong, .crawl-broker-empty span { display: block; }
.crawl-broker-empty span { margin: 6px 0 14px; color: var(--muted); }
```

- [ ] **Step 4: Style the secondary duplicate queue, drawer, dark theme, and reduced motion**

Add:

```css
.crawl-duplicate-workspace { margin-top: 4px; border-style: dashed; box-shadow: none; }
.crawl-duplicate-state {
  margin: 12px 0 0; padding: 12px; border: 1px solid var(--line);
  border-radius: 9px; color: var(--muted); background: var(--soft); font-size: 13px;
}
.crawl-duplicate-state[hidden] { display: none; }
.crawl-duplicate-state[data-state="error"] { border-color: #fecaca; color: #991b1b; background: #fff1f2; }
.crawl-drawer-backdrop {
  position: fixed; z-index: 89; inset: 0; border: 0;
  background: rgba(15, 23, 42, .42); cursor: default;
}
.crawl-drawer-backdrop[hidden] { display: none; }
.crawl-drawer-group {
  display: grid; gap: 12px; min-width: 0; margin: 0; padding: 14px;
  border: 1px solid var(--line); border-radius: 10px;
}
.crawl-drawer-group legend { padding: 0 5px; color: var(--ink); font-size: 12px; font-weight: 900; }
[data-theme="dark"] .crawl-broker-table tbody tr:hover { background: rgba(37, 99, 235, .09); }
[data-theme="dark"] .crawl-broker-summary .is-attention dd { color: #fbbf24; }
[data-theme="dark"] .crawl-broker-badge { border: 1px solid rgba(148, 163, 184, .2); }
[data-theme="dark"] .status-active,
[data-theme="dark"] .quality-good { color: #86efac; background: rgba(22, 101, 52, .36); }
[data-theme="dark"] .status-paused { color: #cbd5e1; background: rgba(71, 85, 105, .42); }
[data-theme="dark"] .schedule-due,
[data-theme="dark"] .quality-needs_attention { color: #fde68a; background: rgba(146, 64, 14, .38); }
[data-theme="dark"] .schedule-scheduled { color: #bfdbfe; background: rgba(30, 64, 175, .34); }
[data-theme="dark"] .crawl-duplicate-state[data-state="error"] {
  border-color: rgba(251, 113, 133, .42); color: #fecdd3; background: rgba(159, 18, 57, .2);
}
@media (prefers-reduced-motion: reduce) {
  .crawl-broker-table tbody tr, .crawl-broker-drawer { transition: none; }
}
```

- [ ] **Step 5: Add predictable tablet wrapping and replace positional mobile labels with `data-label` records**

Inside the existing `@media (max-width: 1100px)` block, replace the obsolete broker-toolbar rules with:

```css
  .crawl-broker-filters { grid-template-columns: 1fr; }
  .crawl-search-field { grid-row: auto; }
  .crawl-filter-rail { grid-template-columns: repeat(3, minmax(0, 1fr)); }
```

Inside the existing `@media (max-width: 760px)` block, add or replace with:

```css
  .crawl-broker-summary { grid-template-columns: 1fr 1fr; }
  .crawl-broker-summary > div { border-bottom: 1px solid var(--line); }
  .crawl-broker-summary > div:nth-child(2n) { border-right: 0; }
  .crawl-broker-summary > div:nth-last-child(-n + 2) { border-bottom: 0; }
  .crawl-broker-filters { grid-template-columns: 1fr; }
  .crawl-search-field { grid-row: auto; }
  .crawl-filter-head { flex-wrap: wrap; }
  .crawl-filter-reset { min-height: 44px; }
  .crawl-filter-rail { grid-template-columns: 1fr 1fr; }
  .crawl-filter-rail label:last-child { grid-column: 1 / -1; }
  .crawl-broker-table { min-width: 0; }
  .crawl-broker-table thead { display: none; }
  .crawl-broker-table, .crawl-broker-table tbody,
  .crawl-broker-table td { display: block; width: 100%; }
  .crawl-broker-table tr {
    display: flex; flex-direction: column; padding: 15px;
    border-bottom: 1px solid var(--line);
  }
  .crawl-broker-table td {
    display: grid; grid-template-columns: 104px minmax(0, 1fr);
    gap: 10px; padding: 7px 0; border: 0;
  }
  .crawl-broker-table [data-label]::before {
    color: var(--muted); content: attr(data-label);
    font-size: 10.5px; font-weight: 850; letter-spacing: .04em; text-transform: uppercase;
  }
  .crawl-broker-identity-cell { grid-template-columns: 1fr !important; padding-top: 0 !important; }
  .crawl-broker-identity-cell::before { display: none; }
  .crawl-broker-identity-cell { order: 1; }
  .crawl-broker-state { order: 2; }
  .crawl-broker-schedule { order: 3; }
  .crawl-broker-quality { order: 4; }
  .crawl-broker-plan { order: 5; }
  .crawl-broker-latest { order: 6; }
  .crawl-broker-actions { order: 7; }
  .crawl-broker-url { max-width: min(100%, 280px); }
  .crawl-broker-actions { display: grid !important; grid-template-columns: repeat(3, 1fr) !important; }
  .crawl-broker-actions::before { grid-column: 1 / -1; }
  .crawl-broker-actions .secondary-btn { min-width: 0; min-height: 44px; margin: 0; }
  .crawl-drawer-actions button { min-height: 44px; }
```

- [ ] **Step 6: Bump the CSS and focused module cache keys**

In `templates/admin_control_room.html`, replace:

```html
?v=admin-v54-facebook-crawl-command-center
?v=admin-facebook-crawl-command-center-v1
```

with:

```html
?v=admin-v55-facebook-crawl-brokers
?v=admin-facebook-crawl-brokers-v2
```

Update the old cache-key assertions in `test_facebook_crawl_admin_is_task_first_and_loads_focused_module` so the test contains only the new values.

- [ ] **Step 7: Run CSS and focused UI contracts**

Run:

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -X utf8 -m pytest tests/test_admin_growth_ui.py::test_facebook_crawl_admin_is_task_first_and_loads_focused_module tests/test_admin_growth_ui.py::test_facebook_crawl_mobile_drawer_stays_in_viewport_with_touch_sized_actions tests/test_admin_growth_ui.py::test_facebook_brokers_has_roster_workbench_semantics tests/test_admin_growth_ui.py::test_facebook_brokers_duplicate_queue_and_drawer_expose_states tests/test_admin_growth_ui.py::test_facebook_broker_roster_is_dense_semantic_and_mobile_safe -q
```

Expected: 5 passed.

- [ ] **Step 8: Commit the visual system**

```powershell
git add -- static/css/admin.css templates/admin_control_room.html tests/test_admin_growth_ui.py
git commit -m "feat: style facebook broker roster workbench"
```

---

### Task 5: Run focused regression and real-browser acceptance gates

**Files:**
- Verify: `static/js/admin/facebook-crawl.js`
- Verify: `templates/admin_control_room.html`
- Verify: `static/css/admin.css`
- Verify: `tests/js/test_facebook_crawl_admin.js`
- Verify: `tests/test_admin_growth_ui.py`
- Verify: `tests/test_facebook_crawl_admin_api.py`

**Interfaces:**
- Validates all Task 1-4 outputs together.
- Does not broaden scope into deployment, API changes, or unrelated admin views.

- [ ] **Step 1: Run static and focused regression tests**

Run:

```powershell
node --check static/js/admin/facebook-crawl.js
node --test tests/js/test_facebook_crawl_admin.js
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -X utf8 -m pytest tests/test_admin_growth_ui.py tests/test_facebook_crawl_admin_api.py -q
```

Expected: JavaScript syntax passes, the Node contract prints `facebook crawl admin contracts: ok`, and both pytest files pass.

- [ ] **Step 2: Check patch hygiene and intended scope**

Run:

```powershell
git diff --check
git status --short
git diff --stat e4a7cbf..HEAD
```

Expected: no whitespace errors; only the five planned implementation/test files plus plan/spec documents are present in the branch history.

- [ ] **Step 3: Start the local app without changing data**

Run:

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -X utf8 app.py
```

Expected: Flask starts on the configured local address. Do not run crawl, reprocess, duplicate mutation, or production deployment commands.

- [ ] **Step 4: Verify desktop behavior at 1536 pixels**

Use an existing authorized local admin session and open `/admin/facebook-crawl?view=brokers`. Confirm:

1. Search, summary, and the first roster rows appear in the first viewport.
2. Summary counts match the loaded roster definitions in Global Constraints.
3. Search works once by broker name and once by URL.
4. City plus quality filters can be combined; the applied count and result count update locally with no new profiles request.
5. `Đặt lại` clears all six controls and restores the full roster.
6. Active, paused, due, scheduled, good-quality, and needs-attention states have visible text, not color alone.
7. A valid Facebook URL opens in a new tab with `noopener noreferrer`; the Node contract proves invalid and non-Facebook values remain plain text.
8. Add and Edit open the grouped drawer; Cancel, backdrop click, and Escape close it and return focus.
9. Applying drawer changes marks the draft unsaved without issuing the profile POST.
10. Delete confirmation states that crawled listings remain; canceling leaves the draft unchanged.
11. Run moves to the Run view with the selected broker and does not auto-submit.
12. Saving once sends one profiles POST. The Node and API regression tests prove a 409 keeps the local draft and exposes the conflict state without requiring a destructive browser fixture.
13. Duplicate all/actionable toggle, cadence suggestion, and load-more remain functional.
14. Roster and duplicate loading, empty, filtered-empty, and error states are understandable.

- [ ] **Step 5: Verify mobile and themes**

At `390x844`, test both light and dark themes:

1. No page-level horizontal scrollbar appears.
2. Summary uses a two-by-two grid.
3. Filters use a two-column rail with the final quality control spanning full width.
4. Each broker reads as a compact labeled record with identity first.
5. Sửa, Chạy, and Xóa are visible, fit one row where copy allows, and each is at least 44 pixels high.
6. The drawer stays inside the viewport and its footer actions remain reachable.
7. Focus rings, text, semantic badges, error states, and disabled controls remain legible.
8. Reduced-motion emulation removes non-essential roster/drawer transitions.

- [ ] **Step 6: Inspect browser request and console evidence**

Confirm:

- Initial Brokers entry requests profiles once and actionable duplicates once.
- Local search/filter/reset does not request either endpoint.
- Duplicate scope toggle requests only the duplicates endpoint.
- No `/admin/api/facebook-crawl/config` request occurs.
- No uncaught console error, mixed-content warning, unsafe-navigation warning, or horizontal-overflow warning appears.

- [ ] **Step 7: Commit only corrections required by browser QA**

If browser QA changes code, rerun Steps 1 and 2, then stage only the planned files and commit:

```powershell
git add -- static/js/admin/facebook-crawl.js templates/admin_control_room.html static/css/admin.css tests/js/test_facebook_crawl_admin.js tests/test_admin_growth_ui.py
git commit -m "fix: verify facebook broker roster interactions"
```

If QA requires no correction, do not create an empty commit.

- [ ] **Step 8: Stop and report the verified boundary**

Report local test counts, browser viewport/theme coverage, observed request behavior, commit SHAs, and remaining unverified production behavior. Do not push, merge, or deploy unless the user explicitly expands the request.
