(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.RadarFacebookCrawlAdmin = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  const VIEWS = new Set(['overview', 'brokers', 'run']);
  const PROFILE_FIELDS = [
    'url',
    'broker_name',
    'city',
    'active',
    'daily_limit',
    'range_days',
    'crawl_every_days',
  ];
  const MODE_LABELS = {
    first: 'Lần đầu',
    daily: 'Hằng ngày',
    range: 'Theo số ngày gần đây',
  };
  let currentInstance = null;

  function normalizeView(value) {
    return VIEWS.has(String(value || '').toLowerCase())
      ? String(value).toLowerCase()
      : 'overview';
  }

  function normalizedProfile(profile) {
    const item = {};
    PROFILE_FIELDS.forEach((field) => {
      let value = profile && profile[field];
      if (field === 'active') value = value !== false;
      else if (['daily_limit', 'range_days', 'crawl_every_days'].includes(field)) {
        value = Number(value || (field === 'range_days' ? 7 : 1));
      } else value = String(value || '').trim();
      item[field] = value;
    });
    return item;
  }

  function normalizedProfilesHash(profiles) {
    const canonical = (Array.isArray(profiles) ? profiles : [])
      .map(normalizedProfile)
      .sort((left, right) => left.url.localeCompare(right.url));
    const text = JSON.stringify(canonical);
    let hash = 2166136261;
    for (let index = 0; index < text.length; index += 1) {
      hash ^= text.charCodeAt(index);
      hash = Math.imul(hash, 16777619);
    }
    return (hash >>> 0).toString(16).padStart(8, '0');
  }

  function isDraftDirty(baseline, draft) {
    return normalizedProfilesHash(baseline) !== normalizedProfilesHash(draft);
  }

  function requestsForView(view) {
    const normalized = normalizeView(view);
    if (normalized === 'brokers') {
      return [
        '/admin/api/facebook-crawl/profiles',
        '/admin/api/facebook-crawl/duplicates?actionable=1&limit=20&offset=0',
      ];
    }
    if (normalized === 'run') return ['/admin/api/facebook-crawl/jobs'];
    return ['/admin/api/facebook-crawl/overview'];
  }

  function buildRunPreview(input) {
    const mode = MODE_LABELS[input.mode] || MODE_LABELS.daily;
    const broker = String(input.broker_name || 'Môi giới chưa chọn');
    const limit = Math.max(1, Number(input.limit || 1));
    const range = input.mode === 'range'
      ? ` · ${Math.max(1, Number(input.days || 7))} ngày gần đây`
      : '';
    const images = input.download_images ? 'Có tải ảnh' : 'Không tải ảnh';
    return `${broker} · ${mode} · tối đa ${limit} bài${range} · ${images}.`;
  }

  function buildMaintenancePreview(action) {
    if (action === 'valuation_only') {
      return 'Chạy lại định giá cho dữ liệu hiện có. Không crawl Facebook mới.';
    }
    return 'Reprocess toàn bộ dữ liệu Facebook chưa xử lý. Không crawl bài mới.';
  }

  function runLimitForMode(mode, profile) {
    if (mode === 'first') return 330;
    return Math.max(1, Number(profile && profile.daily_limit || 30));
  }

  function nextDuplicateOffset(page) {
    return Math.max(0, Number(page && page.offset || 0))
      + (Array.isArray(page && page.items) ? page.items.length : 0);
  }

  function preselectRun(state, profile) {
    return {
      ...state,
      view: 'run',
      runProfileUrl: profile && profile.url || '',
      shouldSubmit: false,
    };
  }

  function profileSaveFailure(state, error) {
    if (Number(error && error.status) === 409
      && error.payload
      && error.payload.error === 'profile_revision_conflict') {
      return {
        ...state,
        conflict: {
          revision: error.payload.revision,
          profiles: error.payload.profiles || [],
        },
      };
    }
    return {...state, conflict: null};
  }

  function clone(value) {
    return value == null ? value : JSON.parse(JSON.stringify(value));
  }

  function text(element, value) {
    if (element) element.textContent = String(value == null ? '' : value);
  }

  function clear(element) {
    if (element) element.replaceChildren();
  }

  function button(label, className, onClick) {
    const control = document.createElement('button');
    control.type = 'button';
    control.className = className || 'secondary-btn';
    control.textContent = label;
    control.addEventListener('click', onClick);
    return control;
  }

  async function defaultFetchJSON(url, options) {
    const response = await fetch(url, {
      credentials: 'same-origin',
      ...(options || {}),
      headers: {
        'Content-Type': 'application/json',
        ...((options && options.headers) || {}),
      },
    });
    let payload = {};
    try {
      payload = await response.json();
    } catch (_error) {
      payload = {};
    }
    if (!response.ok) {
      const error = new Error(payload.error || `HTTP ${response.status}`);
      error.status = response.status;
      error.payload = payload;
      throw error;
    }
    return payload;
  }

  function create(options) {
    const root = options.root;
    const fetchJSON = options.fetchJSON || defaultFetchJSON;
    const confirmAction = options.confirm || ((message) => window.confirm(message));
    const locationObject = options.location || window.location;
    const historyObject = options.history || window.history;
    const beforeUnloadTarget = options.beforeUnloadTarget || window;
    const state = {
      view: 'overview',
      baseline: [],
      draft: [],
      revision: '',
      conflict: null,
      profilesLoaded: false,
      overviewLoadedAt: 0,
      overview: null,
      duplicates: null,
      duplicateActionable: true,
      jobs: [],
      tokens: [],
      tokensLoaded: false,
      runProfileUrl: '',
      drawerIndex: null,
      pollTimer: null,
    };

    const byId = (id) => root.querySelector(`#${id}`);

    function dirty() {
      return isDraftDirty(state.baseline, state.draft);
    }

    function syncDirty() {
      const badge = byId('crawlUnsavedBadge');
      if (badge) badge.hidden = !dirty();
      const save = byId('crawlSaveProfilesBtn');
      if (save) save.disabled = !dirty();
    }

    function viewFromLocation() {
      const params = new URL(locationObject.href).searchParams;
      return normalizeView(params.get('view'));
    }

    function writeViewToLocation(view) {
      const url = new URL(locationObject.href);
      url.searchParams.set('view', view);
      historyObject.replaceState({}, '', `${url.pathname}${url.search}${url.hash}`);
    }

    async function setView(view, settings) {
      const next = normalizeView(view);
      if (next !== state.view && dirty() && !(settings && settings.force)) {
        if (!confirmAction('Bạn có thay đổi chưa lưu. Rời màn hình và bỏ các thay đổi này?')) {
          return false;
        }
        state.draft = clone(state.baseline);
        state.conflict = null;
        syncDirty();
      }
      state.view = next;
      root.querySelectorAll('[data-crawl-view]').forEach((control) => {
        const active = control.dataset.crawlView === next;
        control.classList.toggle('active', active);
        control.setAttribute('aria-selected', active ? 'true' : 'false');
      });
      root.querySelectorAll('[data-crawl-view-panel]').forEach((panel) => {
        panel.hidden = panel.dataset.crawlViewPanel !== next;
      });
      if (!(settings && settings.updateUrl === false)) writeViewToLocation(next);
      await loadCurrentView();
      return true;
    }

    function renderOverview(payload) {
      const cards = byId('crawlOverviewCards');
      clear(cards);
      const values = [
        ['Lịch crawl', payload.schedule && payload.schedule.installed
          ? (payload.schedule.next_run_time || 'Đã bật')
          : 'Chưa hoạt động'],
        ['Lần Facebook gần nhất', payload.last_facebook_run
          ? (payload.last_facebook_run.finished_at || payload.last_facebook_run.status || 'Đã chạy')
          : 'Chưa có dữ liệu'],
        ['Tác vụ gần nhất', payload.latest_job
          ? (payload.latest_job.progress_label || payload.latest_job.status)
          : 'Chưa có tác vụ'],
        ['Apify khả dụng', `${Number(payload.apify && payload.apify.enabled_tokens || 0)} / ${Number(payload.apify && payload.apify.total_tokens || 0)} key`],
      ];
      values.forEach(([label, value]) => {
        const card = document.createElement('article');
        card.className = 'surface crawl-overview-card';
        const small = document.createElement('span');
        small.textContent = label;
        const strong = document.createElement('strong');
        strong.textContent = value;
        card.append(small, strong);
        cards.appendChild(card);
      });
      const problems = byId('crawlProblems');
      clear(problems);
      if (!payload.problems || !payload.problems.length) {
        problems.className = 'crawl-healthy-state';
        text(problems, 'Không có việc cần xử lý. Lịch crawl và tài nguyên đang ổn.');
      } else {
        problems.className = 'crawl-problem-list';
        payload.problems.forEach((problem) => {
          const item = document.createElement('div');
          item.className = 'crawl-problem-item';
          item.textContent = problem.label;
          problems.appendChild(item);
        });
      }
    }

    async function loadOverview(force) {
      const now = Date.now();
      if (!force && state.overview && now - state.overviewLoadedAt < 10000) {
        renderOverview(state.overview);
        return;
      }
      text(byId('crawlOverviewStatus'), 'Đang tải tổng quan…');
      try {
        state.overview = await fetchJSON('/admin/api/facebook-crawl/overview');
        state.overviewLoadedAt = Date.now();
        renderOverview(state.overview);
        text(byId('crawlOverviewStatus'), 'Đã cập nhật');
      } catch (_error) {
        text(byId('crawlOverviewStatus'), 'Không tải được tổng quan. Hãy thử lại.');
      }
    }

    function renderTokens() {
      const list = byId('crawlTokenList');
      clear(list);
      if (!state.tokens.length) {
        text(list, 'Chưa có key trong pool. Hệ thống có thể đang dùng APIFY_TOKEN từ môi trường.');
        return;
      }
      state.tokens.forEach((token) => {
        const row = document.createElement('article');
        row.className = 'crawl-token-row';
        const name = document.createElement('strong');
        name.textContent = token.label || token.id || 'Apify key';
        const quota = document.createElement('span');
        quota.textContent = `${Number(token.remaining || 0)} còn lại / ${Number(token.monthly_quota || 0)} tháng`;
        const status = document.createElement('span');
        status.textContent = token.last_error
          ? 'Đang lỗi'
          : (token.active ? 'Đang bật' : 'Đã tắt');
        const actions = document.createElement('div');
        actions.className = 'crawl-row-actions';
        actions.append(
          button(token.active ? 'Tắt' : 'Bật', 'secondary-btn', async () => {
            const payload = await fetchJSON('/admin/api/facebook-crawl/tokens', {
              method: 'POST',
              body: JSON.stringify({
                id: token.id,
                label: token.label,
                monthly_quota: token.monthly_quota,
                active: !token.active,
              }),
            });
            state.tokens = payload.tokens || [];
            state.overviewLoadedAt = 0;
            renderTokens();
          }),
          button('Reset lượt dùng', 'secondary-btn', async () => {
            if (!confirmAction(`Reset số bài đã dùng của ${token.label || 'key này'}?`)) return;
            const payload = await fetchJSON(
              `/admin/api/facebook-crawl/tokens/${encodeURIComponent(token.id)}`,
              {
                method: 'PATCH',
                body: JSON.stringify({action: 'reset_usage'}),
              },
            );
            state.tokens = payload.tokens || [];
            state.overviewLoadedAt = 0;
            renderTokens();
          }),
          button('Xóa', 'secondary-btn', async () => {
            if (!confirmAction(`Xóa ${token.label || 'Apify key này'} khỏi pool?`)) return;
            const payload = await fetchJSON(
              `/admin/api/facebook-crawl/tokens/${encodeURIComponent(token.id)}`,
              {method: 'DELETE'},
            );
            state.tokens = payload.tokens || [];
            state.overviewLoadedAt = 0;
            renderTokens();
          }),
        );
        row.append(name, quota, status, actions);
        list.appendChild(row);
      });
    }

    async function loadTokens(force) {
      if (state.tokensLoaded && !force) {
        renderTokens();
        return;
      }
      text(byId('crawlTokenList'), 'Đang tải danh sách key…');
      try {
        const payload = await fetchJSON('/admin/api/facebook-crawl/tokens');
        state.tokens = payload.tokens || [];
        state.tokensLoaded = true;
        renderTokens();
      } catch (_error) {
        text(byId('crawlTokenList'), 'Không tải được danh sách key.');
      }
    }

    async function addToken() {
      const token = byId('crawlTokenValue').value.trim();
      if (!token.startsWith('apify_api_')) {
        text(byId('crawlTokenList'), 'Token phải bắt đầu bằng apify_api_.');
        return;
      }
      try {
        const payload = await fetchJSON('/admin/api/facebook-crawl/tokens', {
          method: 'POST',
          body: JSON.stringify({
            label: byId('crawlTokenLabel').value.trim(),
            token,
            monthly_quota: Number(byId('crawlTokenQuota').value || 950),
            active: true,
          }),
        });
        byId('crawlTokenLabel').value = '';
        byId('crawlTokenValue').value = '';
        state.tokens = payload.tokens || [];
        state.tokensLoaded = true;
        state.overviewLoadedAt = 0;
        renderTokens();
      } catch (_error) {
        text(byId('crawlTokenList'), 'Không thêm được key. Kiểm tra định dạng và thử lại.');
      }
    }

    function qualityLabel(profile) {
      const quality = profile.data_quality || {};
      if (quality.score == null) return 'Chưa đủ mẫu';
      return `${quality.label || 'Chất lượng'} · ${quality.score}/100`;
    }

    function filteredProfiles() {
      const search = String(byId('crawlBrokerSearch') && byId('crawlBrokerSearch').value || '').trim().toLocaleLowerCase('vi');
      const city = String(byId('crawlBrokerCityFilter') && byId('crawlBrokerCityFilter').value || '');
      const active = String(byId('crawlBrokerActiveFilter') && byId('crawlBrokerActiveFilter').value || '');
      const cadence = String(byId('crawlBrokerCadenceFilter') && byId('crawlBrokerCadenceFilter').value || '');
      const due = String(byId('crawlBrokerDueFilter') && byId('crawlBrokerDueFilter').value || '');
      const quality = String(byId('crawlBrokerQualityFilter') && byId('crawlBrokerQualityFilter').value || '');
      return state.draft.filter((profile) => {
        const haystack = `${profile.broker_name || ''} ${profile.url || ''}`.toLocaleLowerCase('vi');
        if (search && !haystack.includes(search)) return false;
        if (city && profile.city !== city) return false;
        if (active && String(profile.active !== false) !== active) return false;
        if (cadence && String(profile.crawl_every_days || 1) !== cadence) return false;
        if (due && String(Boolean(profile.due_today)) !== due) return false;
        const score = profile.data_quality && profile.data_quality.score;
        if (quality === 'good' && !(score >= 68)) return false;
        if (quality === 'needs_attention' && !(score == null || score < 68)) return false;
        return true;
      });
    }

    function fillCityFilter() {
      const select = byId('crawlBrokerCityFilter');
      if (!select) return;
      const selected = select.value;
      clear(select);
      const all = document.createElement('option');
      all.value = '';
      all.textContent = 'Tất cả thành phố';
      select.appendChild(all);
      [...new Set(state.draft.map((item) => item.city).filter(Boolean))]
        .sort((a, b) => a.localeCompare(b, 'vi'))
        .forEach((city) => {
          const option = document.createElement('option');
          option.value = city;
          option.textContent = city;
          select.appendChild(option);
        });
      select.value = selected;
    }

    function renderProfiles() {
      fillCityFilter();
      const rows = byId('crawlBrokerRows');
      clear(rows);
      const profiles = filteredProfiles();
      text(byId('crawlBrokerCount'), `${profiles.length} / ${state.draft.length} môi giới`);
      if (!profiles.length) {
        const row = document.createElement('tr');
        const cell = document.createElement('td');
        cell.colSpan = 8;
        cell.className = 'empty';
        cell.textContent = 'Không có môi giới phù hợp bộ lọc.';
        row.appendChild(cell);
        rows.appendChild(row);
        return;
      }
      profiles.forEach((profile) => {
        const index = state.draft.indexOf(profile);
        const row = document.createElement('tr');
        row.dataset.profileUrl = profile.url;
        const cells = [
          `${profile.broker_name || 'Chưa đặt tên'}\n${profile.city || 'Chưa có khu vực'}`,
          profile.active !== false ? 'Đang bật' : 'Đã tắt',
          profile.due_today ? 'Đến lịch hôm nay' : `Kế tiếp ${profile.next_due_date || '—'}`,
          `${Number(profile.daily_limit || 20)} bài · ${Number(profile.crawl_every_days || 1)} ngày/lần`,
          qualityLabel(profile),
          profile.latest_crawled_at || 'Chưa crawl',
        ];
        cells.forEach((value) => {
          const cell = document.createElement('td');
          cell.textContent = value;
          row.appendChild(cell);
        });
        const actions = document.createElement('td');
        actions.className = 'crawl-row-actions';
        actions.append(
          button('Sửa', 'secondary-btn', () => openDrawer(index)),
          button('Chạy', 'secondary-btn', async () => {
            const selected = preselectRun(state, profile);
            state.runProfileUrl = selected.runProfileUrl;
            await setView('run', {force: true});
            applyRunDefaults();
          }),
        );
        row.appendChild(actions);
        rows.appendChild(row);
      });
    }

    function drawerFields() {
      return {
        broker_name: byId('crawlDrawerName'),
        url: byId('crawlDrawerUrl'),
        city: byId('crawlDrawerCity'),
        active: byId('crawlDrawerActive'),
        daily_limit: byId('crawlDrawerLimit'),
        range_days: byId('crawlDrawerRange'),
        crawl_every_days: byId('crawlDrawerCadence'),
      };
    }

    function openDrawer(index) {
      state.drawerIndex = index;
      const profile = index == null ? {
        broker_name: '',
        url: '',
        city: 'Thủ Dầu Một',
        active: true,
        daily_limit: 30,
        range_days: 7,
        crawl_every_days: 1,
      } : state.draft[index];
      const fields = drawerFields();
      Object.entries(fields).forEach(([key, field]) => {
        if (!field) return;
        if (key === 'active') field.checked = profile[key] !== false;
        else field.value = profile[key] == null ? '' : profile[key];
      });
      const drawer = byId('crawlBrokerDrawer');
      drawer.hidden = false;
      byId('crawlDrawerName').focus();
    }

    function closeDrawer() {
      byId('crawlBrokerDrawer').hidden = true;
      state.drawerIndex = null;
    }

    function saveDrawer() {
      const fields = drawerFields();
      const profile = {
        broker_name: fields.broker_name.value.trim(),
        url: fields.url.value.trim(),
        city: fields.city.value.trim(),
        active: fields.active.checked,
        daily_limit: Number(fields.daily_limit.value || 20),
        tier: Number(fields.daily_limit.value || 20),
        range_days: Number(fields.range_days.value || 7),
        crawl_every_days: Number(fields.crawl_every_days.value || 1),
      };
      if (!profile.url || !profile.city) {
        text(byId('crawlDrawerError'), 'Cần nhập URL Facebook và thành phố.');
        return;
      }
      if (state.drawerIndex == null) state.draft.push(profile);
      else state.draft[state.drawerIndex] = {...state.draft[state.drawerIndex], ...profile};
      closeDrawer();
      renderProfiles();
      renderRunProfiles();
      syncDirty();
    }

    function renderDuplicates(page, append) {
      state.duplicates = page;
      text(
        byId('crawlDuplicateSummary'),
        `${Number(page.actionable || 0)} cặp cần xử lý / ${Number(page.total || 0)} cặp đã phân tích`,
      );
      const list = byId('crawlDuplicateList');
      if (!append) clear(list);
      (page.items || []).forEach((item) => {
        const card = document.createElement('article');
        card.className = 'crawl-duplicate-card';
        const title = document.createElement('strong');
        title.textContent = `${item.broker_a_name || 'Môi giới A'} ↔ ${item.broker_b_name || 'Môi giới B'}`;
        const detail = document.createElement('span');
        detail.textContent = `${item.shared_lots || 0} lô chung · ${item.city || 'Chưa rõ khu vực'}`;
        card.append(title, detail);
        if ([3, 7].includes(Number(item.recommended_crawl_every_days))) {
          card.appendChild(button(
            `Đề xuất ${item.recommended_crawl_every_days} ngày/lần`,
            'secondary-btn',
            () => {
              const profile = state.draft.find((value) => value.url === item.reduce_url);
              if (!profile) return;
              profile.crawl_every_days = Number(item.recommended_crawl_every_days);
              renderProfiles();
              syncDirty();
            },
          ));
        }
        list.appendChild(card);
      });
      const more = byId('crawlDuplicateMoreBtn');
      if (more) {
        more.hidden = nextDuplicateOffset(page) >= Number(page.filtered || 0);
      }
    }

    async function loadDuplicates(append) {
      const offset = append && state.duplicates
        ? nextDuplicateOffset(state.duplicates)
        : 0;
      const actionable = state.duplicateActionable ? '1' : '0';
      const url = `/admin/api/facebook-crawl/duplicates?actionable=${actionable}&limit=20&offset=${offset}`;
      try {
        const page = await fetchJSON(url);
        if (append && state.duplicates) {
          page.items = [...(state.duplicates.items || []), ...(page.items || [])];
          page.offset = 0;
        }
        renderDuplicates(page, false);
      } catch (_error) {
        text(byId('crawlDuplicateSummary'), 'Không tải được phân tích trùng.');
      }
    }

    async function loadProfiles(force) {
      if (state.profilesLoaded && !force) {
        renderProfiles();
        return;
      }
      text(byId('crawlBrokerStatus'), 'Đang tải danh sách môi giới…');
      try {
        const payload = await fetchJSON('/admin/api/facebook-crawl/profiles');
        state.baseline = clone(payload.profiles || []);
        state.draft = clone(payload.profiles || []);
        state.revision = payload.revision || '';
        state.conflict = null;
        state.profilesLoaded = true;
        renderProfiles();
        renderRunProfiles();
        syncDirty();
        text(byId('crawlBrokerStatus'), 'Đã cập nhật');
        await loadDuplicates(false);
      } catch (_error) {
        text(byId('crawlBrokerStatus'), 'Không tải được danh sách môi giới.');
      }
    }

    async function saveProfiles() {
      const save = byId('crawlSaveProfilesBtn');
      save.disabled = true;
      text(byId('crawlBrokerStatus'), 'Đang lưu thay đổi…');
      try {
        const payload = await fetchJSON('/admin/api/facebook-crawl/profiles', {
          method: 'POST',
          body: JSON.stringify({
            profiles: state.draft,
            revision: state.revision,
          }),
        });
        state.baseline = clone(payload.profiles || []);
        state.draft = clone(payload.profiles || []);
        state.revision = payload.revision || '';
        state.conflict = null;
        byId('crawlConflictBanner').hidden = true;
        renderProfiles();
        renderRunProfiles();
        syncDirty();
        text(byId('crawlBrokerStatus'), 'Đã lưu danh sách môi giới.');
      } catch (error) {
        const next = profileSaveFailure(state, error);
        state.conflict = next.conflict;
        if (state.conflict) {
          const banner = byId('crawlConflictBanner');
          banner.hidden = false;
          text(
            byId('crawlConflictText'),
            'Dữ liệu đã thay đổi ở nơi khác. Bản nháp của bạn vẫn được giữ.',
          );
          banner.focus();
        }
        text(byId('crawlBrokerStatus'), 'Lưu thất bại. Bản nháp chưa bị mất.');
        syncDirty();
      }
    }

    function renderRunProfiles() {
      const input = byId('crawlRunProfile');
      const options = byId('crawlRunProfileOptions');
      if (!input || !options) return;
      const selected = state.runProfileUrl || input.value;
      clear(options);
      state.draft.filter((profile) => profile.active !== false).forEach((profile) => {
        const option = document.createElement('option');
        option.value = profile.url;
        option.label = `${profile.broker_name || profile.url} · ${profile.city || 'Chưa rõ'}`;
        options.appendChild(option);
      });
      input.value = selected;
      state.runProfileUrl = input.value;
      syncRunForm();
    }

    function applyRunDefaults() {
      const rawUrl = byId('crawlRunProfile').value.trim();
      const profile = state.draft.find((item) => item.url === rawUrl) || {};
      byId('crawlRunLimit').value = runLimitForMode(byId('crawlRunMode').value, profile);
      byId('crawlRunDays').value = Number(profile.range_days || 7);
      syncRunForm();
    }

    function selectedRunInput() {
      const rawUrl = byId('crawlRunProfile').value.trim();
      const profile = state.draft.find((item) => item.url === rawUrl) || {};
      const mode = byId('crawlRunMode').value;
      return {
        url: profile.url || rawUrl,
        broker_name: profile.broker_name || rawUrl,
        city: profile.city || '',
        mode,
        limit: Number(byId('crawlRunLimit').value || (mode === 'first' ? 330 : profile.daily_limit || 30)),
        days: Number(byId('crawlRunDays').value || profile.range_days || 7),
        download_images: byId('crawlRunImages').checked,
      };
    }

    function syncRunForm() {
      if (!byId('crawlRunProfile') || !byId('crawlRunMode')) return;
      const input = selectedRunInput();
      byId('crawlRunDaysField').hidden = input.mode !== 'range';
      text(byId('crawlRunPreview'), buildRunPreview(input));
    }

    function renderJobs(jobs) {
      const history = byId('crawlJobHistory');
      clear(history);
      if (!jobs.length) {
        text(history, 'Chưa có lịch sử tác vụ.');
        return;
      }
      jobs.slice(0, 20).forEach((job) => {
        const card = document.createElement('article');
        card.className = 'crawl-job-card';
        const title = document.createElement('strong');
        title.textContent = job.broker_name || job.mode || 'Tác vụ';
        const status = document.createElement('span');
        status.className = `crawl-job-status status-${job.status || 'queued'}`;
        status.textContent = job.progress_label || job.status || 'queued';
        const time = document.createElement('small');
        time.textContent = job.finished_at || job.started_at || 'Đang chờ';
        card.append(title, status, time);
        if (job.error) {
          const error = document.createElement('p');
          error.textContent = job.error;
          card.appendChild(error);
        }
        history.appendChild(card);
      });
    }

    async function loadJobs() {
      try {
        const payload = await fetchJSON('/admin/api/facebook-crawl/jobs');
        state.jobs = payload.jobs || [];
        renderJobs(state.jobs);
        const active = state.jobs.find((job) => ['queued', 'running'].includes(job.status));
        if (active) schedulePoll(active.id);
      } catch (_error) {
        text(byId('crawlJobHistory'), 'Không tải được lịch sử tác vụ.');
      }
    }

    function schedulePoll(jobId) {
      if (state.pollTimer) clearTimeout(state.pollTimer);
      state.pollTimer = setTimeout(async () => {
        try {
          const payload = await fetchJSON(`/admin/api/facebook-crawl/jobs/${encodeURIComponent(jobId)}`);
          const job = payload.job;
          state.jobs = [job, ...state.jobs.filter((item) => item.id !== job.id)].slice(0, 20);
          renderJobs(state.jobs);
          if (['queued', 'running'].includes(job.status)) schedulePoll(job.id);
        } catch (_error) {
          state.pollTimer = setTimeout(() => schedulePoll(jobId), 5000);
        }
      }, 2500);
    }

    async function runSelected() {
      const input = selectedRunInput();
      const preview = buildRunPreview(input);
      if (!input.url || !confirmAction(`Xác nhận chạy?\n\n${preview}`)) return;
      const run = byId('crawlRunBtn');
      run.disabled = true;
      try {
        const payload = await fetchJSON('/admin/api/facebook-crawl/run', {
          method: 'POST',
          body: JSON.stringify(input),
        });
        state.jobs = [payload.job, ...state.jobs.filter((item) => item.id !== payload.job.id)].slice(0, 20);
        renderJobs(state.jobs);
        schedulePoll(payload.job.id);
      } catch (_error) {
        text(byId('crawlRunStatus'), 'Không tạo được tác vụ. Kiểm tra tác vụ đang chạy.');
      } finally {
        run.disabled = false;
      }
    }

    async function runMaintenance(action) {
      const preview = buildMaintenancePreview(action);
      if (!confirmAction(`Xác nhận tác vụ nâng cao?\n\n${preview}`)) return;
      try {
        const payload = await fetchJSON('/admin/api/facebook-crawl/maintenance', {
          method: 'POST',
          body: JSON.stringify({action}),
        });
        state.jobs = [payload.job, ...state.jobs.filter((item) => item.id !== payload.job.id)].slice(0, 20);
        renderJobs(state.jobs);
        schedulePoll(payload.job.id);
      } catch (_error) {
        text(byId('crawlRunStatus'), 'Không tạo được tác vụ nâng cao.');
      }
    }

    async function loadCurrentView(force) {
      if (state.view === 'overview') return loadOverview(force);
      if (state.view === 'brokers') return loadProfiles(force);
      renderRunProfiles();
      return loadJobs();
    }

    async function refreshCurrentView() {
      if (dirty() && !confirmAction('Tải lại sẽ bỏ các thay đổi môi giới chưa lưu. Tiếp tục?')) {
        return;
      }
      if (dirty()) {
        state.draft = clone(state.baseline);
        state.conflict = null;
        syncDirty();
      }
      await loadCurrentView(true);
    }

    function bind() {
      root.querySelectorAll('[data-crawl-view]').forEach((control) => {
        control.addEventListener('click', () => setView(control.dataset.crawlView));
      });
      byId('crawlRefreshViewBtn').addEventListener('click', refreshCurrentView);
      byId('crawlTokenDetails').addEventListener('toggle', (event) => {
        if (event.target.open) loadTokens(false);
      });
      byId('crawlTokenAddBtn').addEventListener('click', addToken);
      byId('crawlSaveProfilesBtn').addEventListener('click', saveProfiles);
      byId('crawlAddBrokerBtn').addEventListener('click', () => openDrawer(null));
      byId('crawlDrawerCloseBtn').addEventListener('click', closeDrawer);
      byId('crawlDrawerCancelBtn').addEventListener('click', closeDrawer);
      byId('crawlDrawerSaveBtn').addEventListener('click', saveDrawer);
      byId('crawlConflictReloadBtn').addEventListener('click', async () => {
        state.draft = clone(state.baseline);
        state.conflict = null;
        byId('crawlConflictBanner').hidden = true;
        state.profilesLoaded = false;
        await loadProfiles(true);
      });
      [
        'crawlBrokerSearch',
        'crawlBrokerCityFilter',
        'crawlBrokerActiveFilter',
        'crawlBrokerCadenceFilter',
        'crawlBrokerDueFilter',
        'crawlBrokerQualityFilter',
      ].forEach((id) => {
        const control = byId(id);
        control.addEventListener(control.tagName === 'INPUT' ? 'input' : 'change', renderProfiles);
      });
      byId('crawlDuplicateAllBtn').addEventListener('click', async () => {
        state.duplicateActionable = !state.duplicateActionable;
        text(
          byId('crawlDuplicateAllBtn'),
          state.duplicateActionable ? 'Xem toàn bộ phân tích' : 'Chỉ xem cặp cần xử lý',
        );
        await loadDuplicates(false);
      });
      byId('crawlDuplicateMoreBtn').addEventListener('click', () => loadDuplicates(true));
      byId('crawlRunProfile').addEventListener('input', (event) => {
        state.runProfileUrl = event.target.value;
        syncRunForm();
      });
      byId('crawlRunProfile').addEventListener('change', applyRunDefaults);
      byId('crawlRunMode').addEventListener('change', applyRunDefaults);
      ['crawlRunLimit', 'crawlRunDays', 'crawlRunImages'].forEach((id) => {
        byId(id).addEventListener('change', syncRunForm);
        byId(id).addEventListener('input', syncRunForm);
      });
      byId('crawlRunBtn').addEventListener('click', runSelected);
      root.querySelectorAll('[data-crawl-maintenance]').forEach((control) => {
        control.addEventListener('click', () => runMaintenance(control.dataset.crawlMaintenance));
      });
      beforeUnloadTarget.addEventListener('beforeunload', (event) => {
        if (!dirty()) return;
        event.preventDefault();
        event.returnValue = '';
      });
    }

    async function init() {
      bind();
      state.view = viewFromLocation();
      await setView(state.view, {updateUrl: true, force: true});
      return state;
    }

    function canLeave() {
      if (!dirty()) return true;
      if (!confirmAction('Bạn có thay đổi môi giới chưa lưu. Rời màn hình và bỏ thay đổi?')) {
        return false;
      }
      state.draft = clone(state.baseline);
      state.conflict = null;
      syncDirty();
      return true;
    }

    return {
      state,
      init,
      setView,
      loadCurrentView,
      loadOverview,
      loadProfiles,
      loadDuplicates,
      loadJobs,
      renderProfiles,
      canLeave,
      preselect(profile) {
        state.runProfileUrl = profile.url;
        return setView('run', {force: true});
      },
    };
  }

  function autoInit() {
    if (typeof document === 'undefined') return;
    const root = document.getElementById('facebookCrawlAdmin');
    if (!root) return;
    currentInstance = create({root});
    currentInstance.init();
  }

  const api = {
    normalizeView,
    normalizedProfilesHash,
    isDraftDirty,
    requestsForView,
    buildRunPreview,
    buildMaintenancePreview,
    runLimitForMode,
    nextDuplicateOffset,
    preselectRun,
    profileSaveFailure,
    create,
    loadCurrentView(force) {
      return currentInstance ? currentInstance.loadCurrentView(force) : Promise.resolve();
    },
    canLeave() {
      return currentInstance ? currentInstance.canLeave() : true;
    },
  };

  if (typeof document !== 'undefined') {
    document.addEventListener('DOMContentLoaded', autoInit);
  }

  return api;
});
