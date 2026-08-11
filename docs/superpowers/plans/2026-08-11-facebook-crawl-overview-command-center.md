# Facebook Crawl Overview Command Center Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the equal-card Facebook Crawl overview with a responsive, decision-first operations command center while preserving the current route, lightweight API, token security, and view-switching behavior.

**Architecture:** Keep the Flask template as the semantic layout skeleton, derive a defensive overview view model in the existing framework-free JavaScript module, and render all dynamic content with DOM APIs. Reuse the current admin theme tokens and isolate new layout rules under the Facebook Crawl namespace so Brokers and Run inherit only the shared header and navigation refresh.

**Tech Stack:** Flask/Jinja, vanilla JavaScript UMD module, native CSS, Node `assert`, pytest, Chrome browser QA.

## Global Constraints

- Preserve `/admin/facebook-crawl?view=overview`, admin authentication, authorization, and existing `?view=` behavior.
- The Overview initial load requests only `/admin/api/facebook-crawl/overview`.
- Do not add profile-statistics or duplicate-analysis requests to Overview.
- Do not change the overview API response fields or crawler execution behavior.
- Preserve Apify add, enable, disable, reset, and delete behavior and the existing token security copy.
- Use existing admin CSS variables and support current light and dark themes.
- Use RadarBDS blue as the single brand accent; red, amber, and green are semantic status colors only.
- Use 14px radii for primary surfaces, 10px for controls, and pill radii only for status badges.
- Do not use `innerHTML`, new frontend packages, perpetual animation, decorative glow, em dashes, or invented metrics.
- Honor `prefers-reduced-motion` and retain visible keyboard focus.
- Do not modify or stage `.playwright-cli/`.
- Deployment is outside this plan.

Define the project runtime once at the start of execution:

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
```

---

## File Structure

- `static/js/admin/facebook-crawl.js`: owns defensive overview normalization, health derivation, DOM rendering, refresh state, and existing view behavior.
- `templates/admin_control_room.html`: owns the semantic command-center skeleton and stable DOM hooks.
- `static/css/admin.css`: owns namespaced command-center visuals and responsive behavior.
- `tests/js/test_facebook_crawl_admin.js`: owns pure JavaScript view-model and source-contract tests.
- `tests/test_admin_growth_ui.py`: owns template, asset-version, responsive CSS, and accessibility contracts.
- `tests/test_facebook_crawl_admin_api.py`: proves the overview endpoint remains lightweight; change only if a preservation assertion is missing.

---

### Task 1: Build the defensive overview view model

**Files:**
- Modify: `tests/js/test_facebook_crawl_admin.js:58-109`
- Modify: `static/js/admin/facebook-crawl.js:18-129`
- Modify: `static/js/admin/facebook-crawl.js:977-996`

**Interfaces:**
- Consumes: the existing overview payload with `schedule`, `last_facebook_run`, `latest_job`, `active_job`, `apify`, and `problems`.
- Produces: `groupOverviewProblems(problems)` and `buildOverviewViewModel(payload)` exported from `RadarFacebookCrawlAdmin`.

- [ ] **Step 1: Add failing grouping and severity tests**

Append these assertions before the final `console.log` in `tests/js/test_facebook_crawl_admin.js`:

```js
const groupedProblems = api.groupOverviewProblems([
  {code: 'source_error', label: 'Nguồn guland đang lỗi'},
  {code: 'source_error', label: 'Nguồn guland đang lỗi'},
  {code: 'schedule_missing', label: 'Lịch crawl chưa hoạt động'},
  {code: '', label: ''},
]);
assert.deepEqual(groupedProblems, [
  {
    key: 'source_error:nguồn guland đang lỗi',
    code: 'source_error',
    label: 'Nguồn guland đang lỗi',
    severity: 'warning',
    count: 2,
  },
  {
    key: 'schedule_missing:lịch crawl chưa hoạt động',
    code: 'schedule_missing',
    label: 'Lịch crawl chưa hoạt động',
    severity: 'critical',
    count: 1,
  },
  {
    key: 'unknown:có vấn đề cần kiểm tra',
    code: 'unknown',
    label: 'Có vấn đề cần kiểm tra',
    severity: 'warning',
    count: 1,
  },
]);
```

- [ ] **Step 2: Run the Node contract test and verify RED**

Run:

```powershell
node tests\js\test_facebook_crawl_admin.js
```

Expected: FAIL because `api.groupOverviewProblems` is not a function.

- [ ] **Step 3: Add failing view-model tests**

Add:

```js
const warningOverview = api.buildOverviewViewModel({
  schedule: {installed: true, next_run_time: '2026-08-11 21:00'},
  last_facebook_run: null,
  latest_job: {
    status: 'succeeded',
    progress_label: 'Recovered: crawl/reprocess done, images recovered',
  },
  apify: {enabled_tokens: 5, total_tokens: 12},
  problems: [
    {code: 'source_error', label: 'Nguồn facebook đang lỗi'},
  ],
});
assert.equal(warningOverview.health, 'warning');
assert.equal(warningOverview.healthLabel, 'Cần theo dõi');
assert.equal(warningOverview.nextRun, '2026-08-11 21:00');
assert.equal(warningOverview.lastFacebookRun, 'Chưa có dữ liệu lần chạy Facebook');
assert.equal(warningOverview.latestJob.status, 'succeeded');
assert.equal(warningOverview.latestJob.statusLabel, 'Đã hoàn tất');
assert.equal(warningOverview.latestJob.label, 'Recovered: crawl/reprocess done, images recovered');
assert.equal(warningOverview.apify.ratioLabel, '5 / 12 key');

const criticalOverview = api.buildOverviewViewModel({
  schedule: {installed: false},
  apify: {enabled_tokens: 0, total_tokens: 2},
  problems: [
    {code: 'schedule_missing', label: 'Lịch crawl chưa hoạt động'},
    {code: 'apify_unavailable', label: 'Không có Apify token khả dụng'},
  ],
});
assert.equal(criticalOverview.health, 'critical');
assert.equal(criticalOverview.healthLabel, 'Cần xử lý ngay');
assert.equal(criticalOverview.problems.length, 2);

const healthyOverview = api.buildOverviewViewModel({
  schedule: {installed: true},
  apify: {enabled_tokens: 1, total_tokens: 1},
  problems: [],
});
assert.equal(healthyOverview.health, 'healthy');
assert.equal(healthyOverview.healthLabel, 'Hệ thống ổn định');
```

- [ ] **Step 4: Implement normalization, grouping, and health derivation**

Add after `MODE_LABELS` in `static/js/admin/facebook-crawl.js`:

```js
const OVERVIEW_CRITICAL_CODES = new Set([
  'schedule_missing',
  'apify_unavailable',
]);
const OVERVIEW_JOB_STATUS_LABELS = {
  queued: 'Đang chờ',
  running: 'Đang chạy',
  succeeded: 'Đã hoàn tất',
  failed: 'Thất bại',
  empty: 'Chưa có tác vụ',
  unknown: 'Chưa rõ',
};

function overviewText(value, fallback) {
  const normalized = String(value == null ? '' : value).trim();
  return normalized || fallback;
}

function groupOverviewProblems(problems) {
  const grouped = new Map();
  (Array.isArray(problems) ? problems : []).forEach((problem) => {
    const code = overviewText(problem && problem.code, 'unknown').toLowerCase();
    const label = overviewText(problem && problem.label, 'Có vấn đề cần kiểm tra');
    const key = `${code}:${label.toLocaleLowerCase('vi')}`;
    const existing = grouped.get(key);
    if (existing) {
      existing.count += 1;
      return;
    }
    grouped.set(key, {
      key,
      code,
      label,
      severity: OVERVIEW_CRITICAL_CODES.has(code) ? 'critical' : 'warning',
      count: 1,
    });
  });
  return [...grouped.values()];
}

function buildOverviewViewModel(payload) {
  const source = payload && typeof payload === 'object' ? payload : {};
  const problems = groupOverviewProblems(source.problems);
  const critical = problems.some((problem) => problem.severity === 'critical');
  const health = critical ? 'critical' : (problems.length ? 'warning' : 'healthy');
  const healthLabels = {
    critical: 'Cần xử lý ngay',
    warning: 'Cần theo dõi',
    healthy: 'Hệ thống ổn định',
  };
  const summaries = {
    critical: 'Có điều kiện đang chặn hoặc làm gián đoạn lịch crawl.',
    warning: 'Hệ thống vẫn hoạt động nhưng có cảnh báo cần kiểm tra.',
    healthy: 'Lịch crawl và tài nguyên hiện không có cảnh báo hoạt động.',
  };
  const schedule = source.schedule || {};
  const lastRun = source.last_facebook_run || null;
  const latestJob = source.latest_job || null;
  const apify = source.apify || {};
  const enabled = Math.max(0, Number(apify.enabled_tokens || 0));
  const total = Math.max(0, Number(apify.total_tokens || 0));
  const fullJobLabel = latestJob
    ? overviewText(latestJob.progress_label || latestJob.status, 'Chưa có tác vụ gần đây')
    : 'Chưa có tác vụ gần đây';
  const latestJobStatus = latestJob
    ? overviewText(latestJob.status, 'unknown').toLowerCase()
    : 'empty';

  return {
    health,
    healthLabel: healthLabels[health],
    healthSummary: summaries[health],
    nextRun: schedule.installed
      ? overviewText(schedule.next_run_time, 'Lịch đã bật, chưa có thời gian kế tiếp')
      : 'Lịch crawl chưa hoạt động',
    lastFacebookRun: lastRun
      ? overviewText(lastRun.finished_at || lastRun.status, 'Đã có lần chạy Facebook')
      : 'Chưa có dữ liệu lần chạy Facebook',
    latestJob: {
      status: latestJobStatus,
      statusLabel: OVERVIEW_JOB_STATUS_LABELS[latestJobStatus]
        || OVERVIEW_JOB_STATUS_LABELS.unknown,
      label: fullJobLabel,
      fullLabel: fullJobLabel,
    },
    apify: {
      enabled,
      total,
      ratioLabel: `${enabled} / ${total} key`,
    },
    problems,
  };
}
```

- [ ] **Step 5: Export the helpers**

Add both functions to the `api` object near `buildRunPreview`:

```js
groupOverviewProblems,
buildOverviewViewModel,
```

- [ ] **Step 6: Run the Node test and verify GREEN**

Run:

```powershell
node tests\js\test_facebook_crawl_admin.js
```

Expected: `facebook crawl admin contracts: ok`.

- [ ] **Step 7: Commit the view-model slice**

```powershell
git add -- static/js/admin/facebook-crawl.js tests/js/test_facebook_crawl_admin.js
git commit -m "feat: derive facebook crawl overview health"
```

---

### Task 2: Replace the Overview semantic skeleton

**Files:**
- Modify: `tests/test_admin_growth_ui.py:241-267`
- Modify: `templates/admin_control_room.html:399-445`

**Interfaces:**
- Consumes: existing IDs used by token management and top-level view switching.
- Produces: stable DOM hooks consumed by the Task 3 renderer.

- [ ] **Step 1: Add a failing semantic-layout contract test**

Add to `tests/test_admin_growth_ui.py`:

```python
def test_facebook_crawl_overview_has_command_center_semantics():
    template = (ROOT / "templates" / "admin_control_room.html").read_text(encoding="utf-8")

    required_ids = (
        "crawlOverviewCommand",
        "crawlOverviewHealth",
        "crawlOverviewHealthBadge",
        "crawlOverviewHealthLabel",
        "crawlOverviewHealthSummary",
        "crawlOverviewNextRun",
        "crawlOverviewLastRun",
        "crawlOverviewLatestJob",
        "crawlOverviewApify",
        "crawlProblems",
        "crawlOverviewError",
        "crawlOverviewRetryBtn",
        "crawlOverviewRunBtn",
        "crawlOverviewBrokersBtn",
    )
    for element_id in required_ids:
        assert f'id="{element_id}"' in template
    assert 'aria-live="polite"' in template
    assert 'aria-labelledby="crawlOverviewHealthLabel"' in template
    assert 'aria-labelledby="crawlProblemsTitle"' in template
```

- [ ] **Step 2: Run the focused pytest and verify RED**

Run:

```powershell
& $py -X utf8 -m pytest tests\test_admin_growth_ui.py::test_facebook_crawl_overview_has_command_center_semantics -q
```

Expected: FAIL because the command-center IDs do not exist.

- [ ] **Step 3: Replace the current Overview heading and equal-card grid**

Replace the contents of `#crawlView-overview` before `#crawlTokenDetails` with this semantic structure:

```html
<div class="crawl-overview-toolbar">
  <div>
    <p class="crawl-overview-kicker">Trạng thái vận hành</p>
    <h2>Điều hành Facebook Crawl</h2>
  </div>
  <span id="crawlOverviewStatus" class="crawl-inline-status" aria-live="polite">Đang tải tổng quan</span>
</div>

<div id="crawlOverviewCommand" class="crawl-command-layout" aria-busy="true">
  <section id="crawlOverviewHealth" class="surface crawl-health-panel state-loading"
           aria-labelledby="crawlOverviewHealthLabel">
    <div class="crawl-health-copy">
      <span id="crawlOverviewHealthBadge" class="crawl-status-badge">Đang tải</span>
      <h3 id="crawlOverviewHealthLabel">Đang kiểm tra hệ thống</h3>
      <p id="crawlOverviewHealthSummary">Đang lấy lịch crawl, lần chạy gần nhất và tài nguyên Apify.</p>
    </div>
    <dl class="crawl-health-facts">
      <div><dt>Lịch kế tiếp</dt><dd id="crawlOverviewNextRun">Đang tải</dd></div>
      <div><dt>Facebook gần nhất</dt><dd id="crawlOverviewLastRun">Đang tải</dd></div>
    </dl>
    <div class="crawl-command-actions">
      <button class="primary-btn" id="crawlOverviewRunBtn" type="button">Chạy tác vụ</button>
      <button class="secondary-btn" id="crawlOverviewBrokersBtn" type="button">Quản lý môi giới</button>
    </div>
  </section>

  <section class="surface crawl-attention-panel" aria-labelledby="crawlProblemsTitle">
    <div class="crawl-section-head">
      <div>
        <h3 id="crawlProblemsTitle">Việc cần xử lý</h3>
        <p>Ưu tiên điều kiện có thể làm gián đoạn crawl.</p>
      </div>
    </div>
    <div id="crawlProblems" class="crawl-problem-skeleton" aria-live="polite">Đang kiểm tra cảnh báo</div>
  </section>
  <aside class="crawl-resource-rail" aria-label="Tài nguyên và hoạt động">
    <article id="crawlOverviewApify" class="surface crawl-resource-card">
      <span>Tài nguyên Apify</span>
      <strong id="crawlOverviewApifyValue">Đang tải</strong>
      <p id="crawlOverviewApifyNote">Đang kiểm tra key khả dụng</p>
    </article>
    <article id="crawlOverviewLatestJob" class="surface crawl-resource-card">
      <span>Tác vụ gần nhất</span>
      <strong id="crawlOverviewJobStatus">Đang tải</strong>
      <p id="crawlOverviewJobLabel">Đang kiểm tra lịch sử tác vụ</p>
    </article>
  </aside>
</div>

<section id="crawlOverviewError" class="crawl-overview-error" role="alert" hidden>
  <div>
    <strong>Không tải được tổng quan</strong>
    <p>Dữ liệu gần nhất được giữ lại nếu có. Hãy thử tải lại.</p>
  </div>
  <button class="secondary-btn" id="crawlOverviewRetryBtn" type="button">Thử lại</button>
</section>
```

Keep the existing `#crawlTokenDetails`, token form, token list, and security copy immediately after these sections. Change only its summary to:

```html
<summary>
  <span>Quản lý Apify key</span>
  <span id="crawlTokenSummaryCount" class="crawl-token-summary-count">Đang tải tài nguyên</span>
</summary>
```

- [ ] **Step 4: Keep the shared header and navigation stable**

Retain the existing `Facebook Crawl` title, the three `data-crawl-view` controls, `crawlRefreshViewBtn`, and all Brokers and Run markup. Do not rename form fields or token controls.

- [ ] **Step 5: Run the semantic contract test and verify GREEN**

Run:

```powershell
& $py -X utf8 -m pytest tests\test_admin_growth_ui.py::test_facebook_crawl_overview_has_command_center_semantics -q
```

Expected: PASS.

- [ ] **Step 6: Commit the semantic skeleton**

```powershell
git add -- templates/admin_control_room.html tests/test_admin_growth_ui.py
git commit -m "feat: structure facebook crawl command center"
```

---

### Task 3: Render health, resources, attention, loading, and errors

**Files:**
- Modify: `tests/js/test_facebook_crawl_admin.js:106-109`
- Modify: `static/js/admin/facebook-crawl.js:248-304`
- Modify: `static/js/admin/facebook-crawl.js:871-925`

**Interfaces:**
- Consumes: `buildOverviewViewModel(payload)` from Task 1 and DOM IDs from Task 2.
- Produces: deterministic DOM state for loading, healthy, warning, critical, retry, and cached-data failure behavior.

- [ ] **Step 1: Add failing source contracts for safe rendering and controls**

Add before the final Node test log:

```js
assert.match(source, /function setOverviewLoading/);
assert.match(source, /function renderOverviewProblem/);
assert.match(source, /crawlOverviewRunBtn/);
assert.match(source, /crawlOverviewBrokersBtn/);
assert.match(source, /crawlOverviewRetryBtn/);
assert.match(source, /dataset\.health/);
assert.match(source, /aria-busy/);
assert.doesNotMatch(source, /\.innerHTML\s*=/);
```

- [ ] **Step 2: Run the Node test and verify RED**

Run:

```powershell
node tests\js\test_facebook_crawl_admin.js
```

Expected: FAIL because the new render helpers do not exist.

- [ ] **Step 3: Implement loading and problem rendering helpers**

Add inside `create(options)` before `renderOverview`:

```js
function setOverviewLoading(loading, statusLabel) {
  const command = byId('crawlOverviewCommand');
  const refresh = byId('crawlRefreshViewBtn');
  if (command) command.setAttribute('aria-busy', loading ? 'true' : 'false');
  if (refresh) {
    refresh.disabled = loading;
    refresh.setAttribute('aria-busy', loading ? 'true' : 'false');
  }
  text(
    byId('crawlOverviewStatus'),
    statusLabel || (loading ? 'Đang làm mới' : 'Đã cập nhật'),
  );
}

function renderOverviewProblem(problem) {
  const item = document.createElement('li');
  item.className = `crawl-problem-item severity-${problem.severity}`;
  const copy = document.createElement('div');
  const label = document.createElement('strong');
  label.textContent = problem.label;
  const hint = document.createElement('span');
  hint.textContent = problem.severity === 'critical'
    ? 'Cần kiểm tra trước lần crawl kế tiếp'
    : 'Theo dõi và xử lý khi phù hợp';
  copy.append(label, hint);
  item.appendChild(copy);
  if (problem.count > 1) {
    const count = document.createElement('span');
    count.className = 'crawl-problem-count';
    count.textContent = `${problem.count} lần`;
    item.appendChild(count);
  }
  return item;
}
```

- [ ] **Step 4: Replace `renderOverview(payload)`**

Implement the function with these required assignments:

```js
function renderOverview(payload) {
  const model = buildOverviewViewModel(payload);
  const health = byId('crawlOverviewHealth');
  if (health) {
    health.dataset.health = model.health;
    health.className = `surface crawl-health-panel state-${model.health}`;
  }
  text(byId('crawlOverviewHealthLabel'), model.healthLabel);
  text(byId('crawlOverviewHealthSummary'), model.healthSummary);
  text(byId('crawlOverviewNextRun'), model.nextRun);
  text(byId('crawlOverviewLastRun'), model.lastFacebookRun);
  text(byId('crawlOverviewApifyValue'), model.apify.ratioLabel);
  text(
    byId('crawlOverviewApifyNote'),
    model.apify.enabled
      ? `${model.apify.enabled} key đang sẵn sàng`
      : 'Không có key đang sẵn sàng',
  );
  text(byId('crawlOverviewJobStatus'), model.latestJob.statusLabel);
  text(byId('crawlOverviewJobLabel'), model.latestJob.label);
  byId('crawlOverviewJobLabel').title = model.latestJob.fullLabel;
  text(
    byId('crawlTokenSummaryCount'),
    `${model.apify.enabled} / ${model.apify.total} key khả dụng`,
  );
  text(byId('crawlOverviewHealthBadge'), model.healthLabel);
  byId('crawlOverviewHealthBadge').dataset.health = model.health;

  const problems = byId('crawlProblems');
  clear(problems);
  if (!model.problems.length) {
    problems.className = 'crawl-healthy-state';
    text(problems, 'Không có việc cần xử lý. Lịch crawl và tài nguyên đang ổn.');
  } else {
    const list = document.createElement('ul');
    list.className = 'crawl-problem-list';
    model.problems.forEach((problem) => list.appendChild(renderOverviewProblem(problem)));
    problems.className = '';
    problems.appendChild(list);
  }
}
```

- [ ] **Step 5: Upgrade `loadOverview(force)` without hiding cached data**

Implement this state flow:

```js
async function loadOverview(force) {
  const now = Date.now();
  if (!force && state.overview && now - state.overviewLoadedAt < 10000) {
    renderOverview(state.overview);
    setOverviewLoading(false, 'Đã cập nhật');
    return;
  }
  setOverviewLoading(true, 'Đang làm mới');
  byId('crawlOverviewError').hidden = true;
  try {
    state.overview = await fetchJSON('/admin/api/facebook-crawl/overview');
    state.overviewLoadedAt = Date.now();
    renderOverview(state.overview);
    setOverviewLoading(false, 'Đã cập nhật');
  } catch (_error) {
    byId('crawlOverviewError').hidden = false;
    setOverviewLoading(false, 'Không tải được tổng quan');
  }
}
```

- [ ] **Step 6: Bind the three new actions through existing paths**

In `bind()` add:

```js
byId('crawlOverviewRunBtn').addEventListener('click', () => setView('run'));
byId('crawlOverviewBrokersBtn').addEventListener('click', () => setView('brokers'));
byId('crawlOverviewRetryBtn').addEventListener('click', () => loadOverview(true));
```

- [ ] **Step 7: Run Node syntax and contract tests**

Run:

```powershell
node --check static\js\admin\facebook-crawl.js
node tests\js\test_facebook_crawl_admin.js
```

Expected: both commands exit 0; the contract test prints `facebook crawl admin contracts: ok`.

- [ ] **Step 8: Commit the renderer slice**

```powershell
git add -- static/js/admin/facebook-crawl.js tests/js/test_facebook_crawl_admin.js
git commit -m "feat: render facebook crawl command states"
```

---

### Task 4: Implement the command-center visual system and responsive order

**Files:**
- Modify: `tests/test_admin_growth_ui.py:263-285`
- Modify: `static/css/admin.css:3328-3525`

**Interfaces:**
- Consumes: semantic classes and `data-health` states from Tasks 2 and 3.
- Produces: theme-aware desktop, tablet, mobile, focus, skeleton, truncation, and reduced-motion presentation.

- [ ] **Step 1: Add failing CSS contract assertions**

Add:

```python
def test_facebook_crawl_overview_command_center_css_contract():
    css = (ROOT / "static" / "css" / "admin.css").read_text(encoding="utf-8")

    required = (
        ".crawl-command-layout",
        ".crawl-health-panel",
        '.crawl-health-panel[data-health="critical"]',
        '.crawl-health-panel[data-health="warning"]',
        '.crawl-health-panel[data-health="healthy"]',
        ".crawl-resource-rail",
        ".crawl-attention-panel",
        ".crawl-overview-error",
        ".crawl-problem-count",
        "text-overflow: ellipsis",
        "prefers-reduced-motion: reduce",
    )
    for marker in required:
        assert marker in css

    mobile = css[css.index("@media (max-width: 760px)", css.index(".facebook-crawl-shell")):]
    assert "grid-template-columns: 1fr;" in mobile
    assert 'grid-template-areas: "health" "attention" "rail";' in mobile
```

- [ ] **Step 2: Run the CSS contract test and verify RED**

Run:

```powershell
& $py -X utf8 -m pytest tests\test_admin_growth_ui.py::test_facebook_crawl_overview_command_center_css_contract -q
```

Expected: FAIL because the command-center selectors are absent.

- [ ] **Step 3: Replace Overview-specific equal-card rules**

Remove `.crawl-overview-grid` and `.crawl-overview-card` rules. Add namespaced rules with these required properties:

```css
.crawl-overview-toolbar {
  display: flex;
  align-items: end;
  justify-content: space-between;
  gap: 16px;
}
.crawl-overview-kicker {
  margin: 0 0 5px;
  color: var(--blue);
  font-size: 12px;
  font-weight: 800;
}
.crawl-overview-toolbar h2 { margin: 0; font-size: clamp(24px, 3vw, 36px); }
.crawl-command-layout {
  display: grid;
  grid-template-columns: minmax(0, 2fr) minmax(280px, 1fr);
  grid-template-areas: "health rail" "attention attention";
  gap: 14px;
}
.crawl-health-panel {
  grid-area: health;
  min-width: 0;
  padding: clamp(20px, 3vw, 32px);
  border-radius: 14px;
  border-color: color-mix(in srgb, var(--blue) 22%, var(--line));
}
.crawl-health-panel[data-health="critical"] {
  border-color: color-mix(in srgb, var(--red) 42%, var(--line));
  background: color-mix(in srgb, var(--red) 5%, var(--panel));
}
.crawl-health-panel[data-health="warning"] {
  border-color: color-mix(in srgb, #d97706 42%, var(--line));
  background: color-mix(in srgb, #d97706 6%, var(--panel));
}
.crawl-health-panel[data-health="healthy"] {
  border-color: color-mix(in srgb, #15803d 34%, var(--line));
  background: color-mix(in srgb, #15803d 5%, var(--panel));
}
.crawl-health-copy h3 {
  max-width: 18ch;
  margin: 14px 0 8px;
  font-size: clamp(30px, 4vw, 48px);
  line-height: 1.05;
  letter-spacing: -.035em;
}
.crawl-health-copy p { max-width: 62ch; margin: 0; color: var(--muted); }
.crawl-health-facts {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin: 26px 0 0;
}
.crawl-health-facts > div {
  padding-top: 12px;
  border-top: 1px solid var(--line);
}
.crawl-health-facts dt { color: var(--muted); font-size: 12px; font-weight: 800; }
.crawl-health-facts dd {
  margin: 6px 0 0;
  color: var(--ink);
  font-family: ui-monospace, "Cascadia Code", Consolas, monospace;
  font-weight: 800;
}
.crawl-command-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 24px; }
.crawl-resource-rail { grid-area: rail; display: grid; gap: 14px; min-width: 0; }
.crawl-resource-card { min-width: 0; padding: 20px; border-radius: 14px; }
.crawl-resource-card > span { color: var(--muted); font-size: 12px; font-weight: 800; }
.crawl-resource-card > strong { display: block; margin-top: 12px; font-size: 24px; }
.crawl-resource-card > p {
  margin: 7px 0 0;
  overflow: hidden;
  color: var(--muted);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.crawl-attention-panel { grid-area: attention; padding: 20px; border-radius: 14px; }
.crawl-problem-list { display: grid; gap: 8px; margin: 14px 0 0; padding: 0; list-style: none; }
.crawl-problem-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 13px 14px;
  border: 1px solid color-mix(in srgb, #d97706 40%, var(--line));
  border-radius: 10px;
  background: color-mix(in srgb, #d97706 6%, var(--panel));
}
.crawl-problem-item.severity-critical {
  border-color: color-mix(in srgb, var(--red) 42%, var(--line));
  background: color-mix(in srgb, var(--red) 6%, var(--panel));
}
.crawl-problem-item div { display: grid; gap: 3px; }
.crawl-problem-item span { color: var(--muted); font-size: 12px; }
.crawl-problem-count {
  flex: 0 0 auto;
  padding: 5px 9px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--ink) 8%, var(--panel));
  color: var(--ink) !important;
  font-weight: 800;
}
.crawl-overview-error {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 16px;
  border: 1px solid color-mix(in srgb, var(--red) 42%, var(--line));
  border-radius: 14px;
  background: color-mix(in srgb, var(--red) 6%, var(--panel));
}
.crawl-overview-error[hidden] { display: none; }
.crawl-overview-error p { margin: 4px 0 0; color: var(--muted); }
```

- [ ] **Step 4: Add semantic badge, loading, and active feedback rules**

Add:

```css
.crawl-status-badge {
  display: inline-flex;
  width: fit-content;
  min-height: 28px;
  align-items: center;
  padding: 4px 10px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--blue) 12%, var(--panel));
  color: var(--blue);
  font-size: 12px;
  font-weight: 800;
}
.crawl-status-badge[data-health="critical"] {
  background: color-mix(in srgb, var(--red) 12%, var(--panel));
  color: var(--red);
}
.crawl-status-badge[data-health="warning"] {
  background: color-mix(in srgb, #d97706 13%, var(--panel));
  color: #a35b04;
}
.crawl-status-badge[data-health="healthy"] {
  background: color-mix(in srgb, #15803d 12%, var(--panel));
  color: #15803d;
}
.crawl-problem-skeleton,
.crawl-health-panel.state-loading .crawl-health-copy,
.crawl-health-panel.state-loading .crawl-health-facts,
.crawl-resource-card:has(strong:empty) {
  min-height: 72px;
  border-radius: 10px;
  background: color-mix(in srgb, var(--soft) 72%, var(--panel));
}
@media (prefers-reduced-motion: no-preference) {
  .crawl-health-panel,
  .crawl-resource-card,
  .crawl-problem-item,
  .crawl-command-actions button {
    transition: border-color .18s ease, background-color .18s ease, transform .18s ease;
  }
  .crawl-command-actions button:active { transform: translateY(1px); }
}
@media (prefers-reduced-motion: reduce) {
  .crawl-health-panel,
  .crawl-resource-card,
  .crawl-problem-item,
  .crawl-command-actions button { transition: none; }
}
```

Keep the existing `.facebook-crawl-shell button:focus-visible` outline rule unchanged.

- [ ] **Step 5: Add tablet and mobile layout contracts**

Inside the existing Facebook Crawl responsive blocks add:

```css
@media (max-width: 1100px) {
  .crawl-command-layout { grid-template-columns: minmax(0, 1.35fr) minmax(260px, .65fr); }
}

@media (max-width: 760px) {
  .crawl-overview-toolbar { align-items: stretch; flex-direction: column; }
  .crawl-command-layout {
    grid-template-columns: 1fr;
    grid-template-areas: "health" "attention" "rail";
  }
  .crawl-health-panel { padding: 20px; }
  .crawl-health-facts { grid-template-columns: 1fr; }
  .crawl-command-actions { display: grid; grid-template-columns: 1fr; }
  .crawl-command-actions button { width: 100%; min-height: 44px; }
  .crawl-problem-item { align-items: flex-start; flex-direction: column; }
  .crawl-overview-error { align-items: stretch; flex-direction: column; }
  .crawl-overview-error button { width: 100%; min-height: 44px; }
}
```

The `grid-template-areas: "health" "attention" "rail"` declaration is the required mobile ordering contract.

- [ ] **Step 6: Run focused CSS and existing mobile tests**

Run:

```powershell
& $py -X utf8 -m pytest `
  tests\test_admin_growth_ui.py::test_facebook_crawl_overview_command_center_css_contract `
  tests\test_admin_growth_ui.py::test_facebook_crawl_mobile_drawer_stays_in_viewport_with_touch_sized_actions `
  tests\test_admin_growth_ui.py::test_facebook_broker_actions_have_explicit_safe_delete_and_responsive_styles -q
```

Expected: 3 passed.

- [ ] **Step 7: Commit the visual-system slice**

```powershell
git add -- static/css/admin.css tests/test_admin_growth_ui.py
git commit -m "feat: style facebook crawl command center"
```

---

### Task 5: Cache bust, regression gates, and browser verification

**Files:**
- Modify: `tests/test_admin_growth_ui.py:241-267`
- Modify: `templates/admin_control_room.html:11,1031`
- Verify: `tests/test_facebook_crawl_admin_api.py`
- Verify: all files changed in Tasks 1-4

**Interfaces:**
- Consumes: completed command-center implementation.
- Produces: a release-ready local commit set with focused automated and visual evidence. It does not push or deploy.

- [ ] **Step 1: Add failing asset-version assertions**

Update the Facebook Crawl UI test to require:

```python
assert "?v=admin-facebook-crawl-command-center-v1" in template
assert "css/admin.css') }}?v=admin-v53-facebook-crawl-command-center" in template
```

- [ ] **Step 2: Run the asset assertion and verify RED**

Run:

```powershell
& $py -X utf8 -m pytest tests\test_admin_growth_ui.py::test_facebook_crawl_admin_is_task_first_and_loads_focused_module -q
```

Expected: FAIL on the old asset query keys.

- [ ] **Step 3: Bump only the two affected asset keys**

In `templates/admin_control_room.html` set:

```html
<link rel="stylesheet" href="{{ url_for('static', filename='css/admin.css') }}?v=admin-v53-facebook-crawl-command-center">
```

and:

```html
<script src="{{ url_for('static', filename='js/admin/facebook-crawl.js') }}?v=admin-facebook-crawl-command-center-v1"></script>
```

- [ ] **Step 4: Run the complete focused automated gate**

Run:

```powershell
node --check static\js\admin\facebook-crawl.js
node tests\js\test_facebook_crawl_admin.js
& $py -X utf8 -m pytest `
  tests\test_admin_growth_ui.py `
  tests\test_facebook_crawl_admin_api.py `
  tests\test_admin_control_room.py -q
git diff --check
```

Expected: JavaScript syntax exit 0, Node contract log `facebook crawl admin contracts: ok`, focused pytest exit 0, and no diff-check output.

- [ ] **Step 5: Verify no new Overview requests**

Confirm both automated and source evidence:

```powershell
rg -n "requestsForView|facebook-crawl/overview|facebook-crawl/profiles|facebook-crawl/duplicates" static\js\admin\facebook-crawl.js tests\js\test_facebook_crawl_admin.js
```

Expected: `requestsForView('overview')` still returns only `/admin/api/facebook-crawl/overview`.

- [ ] **Step 6: Run authenticated desktop browser QA at 1536px**

Start the local Flask app with the project Python and local PostgreSQL configuration. Open `/admin/facebook-crawl?view=overview` through the authenticated admin flow. Verify:

- health panel and resource rail share the first command row;
- duplicate warnings show one row with a count;
- long job text truncates without changing the grid width;
- Run and Brokers actions update `?view=` through existing `setView()`;
- refresh disables while loading and restores after completion;
- no console errors.

- [ ] **Step 7: Run mobile browser QA at 390px by 844px**

Set the temporary browser viewport to `390 x 844` and verify:

- no horizontal document overflow;
- health and attention are visible before secondary resource cards;
- actions are at least 44px high and labels do not wrap awkwardly;
- tabs remain usable;
- the advanced token disclosure does not dominate the first viewport.

Reset the viewport after the check.

- [ ] **Step 8: Verify dark theme, keyboard focus, reduced motion, and error fixtures**

Use the current theme control and browser emulation or fixture payloads to verify:

- light and dark contrast;
- keyboard traversal through refresh, tabs, command actions, retry, and token disclosure;
- no transition under reduced motion;
- healthy, warning, critical, loading, and request-error presentation.

- [ ] **Step 9: Refresh Graphify structural evidence**

Run:

```powershell
graphify update .
```

If the Windows wrapper reports `uv trampoline failed to canonicalize script path`, record Graphify refresh as unverified and do not relabel source/test/browser evidence as Graphify success.

- [ ] **Step 10: Review the final diff against the design acceptance criteria**

Run:

```powershell
git status --short
git diff --stat HEAD~3..HEAD
git diff --name-only HEAD~3..HEAD
```

Confirm the implementation touches only the planned files and leaves `.playwright-cli/` untracked and unstaged.

- [ ] **Step 11: Commit the cache-bust and verification contracts**

```powershell
git add -- templates/admin_control_room.html tests/test_admin_growth_ui.py
git commit -m "test: verify facebook crawl command center"
```

Do not push or deploy without a separate explicit instruction.
