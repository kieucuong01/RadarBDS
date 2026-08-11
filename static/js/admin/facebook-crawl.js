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
  let currentInstance = null;

  function overviewText(value, fallback) {
    const normalized = String(value == null ? '' : value).trim();
    return normalized || fallback;
  }

  function overviewCount(value) {
    const normalized = Number(value);
    return Number.isFinite(normalized) ? Math.max(0, Math.trunc(normalized)) : 0;
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
    const schedule = source.schedule && typeof source.schedule === 'object'
      ? source.schedule
      : {};
    const lastRun = source.last_facebook_run && typeof source.last_facebook_run === 'object'
      ? source.last_facebook_run
      : null;
    const latestJob = source.latest_job && typeof source.latest_job === 'object'
      ? source.latest_job
      : null;
    const apify = source.apify && typeof source.apify === 'object' ? source.apify : {};
    const enabled = overviewCount(apify.enabled_tokens);
    const total = overviewCount(apify.total_tokens);
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

  function removeProfileFromDraft(draft, url) {
    return (Array.isArray(draft) ? draft : []).filter((profile) => profile.url !== url);
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
        display: 'facebook.com' + pathname,
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
      const haystack = String(profile.broker_name || '') + ' ' + String(profile.url || '');
      const normalizedHaystack = haystack.toLocaleLowerCase('vi');
      if (selected.search && !normalizedHaystack.includes(selected.search)) return false;
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

  function duplicatePresentationState(page, error) {
    if (error) return 'error';
    if (!page) return 'loading';
    return Array.isArray(page.items) && page.items.length ? 'ready' : 'empty';
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
      drawerReturnFocus: null,
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

    function setOverviewLoading(loading, statusLabel) {
      const command = byId('crawlOverviewCommand');
      const health = byId('crawlOverviewHealth');
      const refresh = byId('crawlRefreshViewBtn');
      if (command) {
        command.setAttribute('aria-busy', loading ? 'true' : 'false');
        command.classList.toggle('is-loading', loading);
      }
      if (health) health.classList.toggle('state-loading', loading);
      if (refresh) refresh.disabled = loading;
      if (statusLabel) text(byId('crawlOverviewStatus'), statusLabel);
    }

    function renderOverviewProblem(problem) {
      const item = document.createElement('article');
      item.className = `crawl-problem-item severity-${problem.severity}`;

      const marker = document.createElement('span');
      marker.className = 'crawl-problem-marker';
      marker.setAttribute('aria-hidden', 'true');

      const copy = document.createElement('div');
      const label = document.createElement('strong');
      label.textContent = problem.label;
      const severity = document.createElement('span');
      severity.className = 'crawl-problem-severity';
      severity.textContent = problem.severity === 'critical' ? 'Cần xử lý ngay' : 'Cần kiểm tra';
      copy.append(label, severity);

      item.append(marker, copy);
      if (problem.count > 1) {
        const count = document.createElement('span');
        count.className = 'crawl-problem-count';
        count.textContent = `×${problem.count}`;
        count.setAttribute('aria-label', `${problem.count} cảnh báo giống nhau`);
        item.appendChild(count);
      }
      return item;
    }

    function renderOverview(payload) {
      const model = buildOverviewViewModel(payload);
      const health = byId('crawlOverviewHealth');
      const badge = byId('crawlOverviewHealthBadge');
      health.classList.remove('state-loading', 'state-healthy', 'state-warning', 'state-critical');
      health.classList.add(`state-${model.health}`);
      health.dataset.health = model.health;
      badge.dataset.health = model.health;
      text(badge, model.healthLabel);
      text(byId('crawlOverviewHealthLabel'), model.healthLabel);
      text(byId('crawlOverviewHealthSummary'), model.healthSummary);
      text(byId('crawlOverviewNextRun'), model.nextRun);
      text(byId('crawlOverviewLastRun'), model.lastFacebookRun);

      text(byId('crawlOverviewApifyValue'), model.apify.ratioLabel);
      text(
        byId('crawlOverviewApifyNote'),
        model.apify.enabled
          ? `${model.apify.enabled} key đang sẵn sàng cho tác vụ crawl.`
          : 'Không có key khả dụng cho tác vụ mới.',
      );
      text(byId('crawlTokenSummaryCount'), `${model.apify.enabled}/${model.apify.total} key khả dụng`);

      const jobStatus = byId('crawlOverviewJobStatus');
      jobStatus.className = `crawl-job-status status-${model.latestJob.status}`;
      text(jobStatus, model.latestJob.statusLabel);
      const jobLabel = byId('crawlOverviewJobLabel');
      jobLabel.title = model.latestJob.fullLabel;
      text(jobLabel, model.latestJob.label);

      const problems = byId('crawlProblems');
      clear(problems);
      if (!model.problems.length) {
        problems.className = 'crawl-healthy-state';
        const title = document.createElement('strong');
        title.textContent = 'Không có việc cần xử lý';
        const note = document.createElement('span');
        note.textContent = 'Lịch crawl và tài nguyên đang ổn.';
        problems.append(title, note);
      } else {
        problems.className = 'crawl-problem-list';
        model.problems.forEach((problem) => {
          problems.appendChild(renderOverviewProblem(problem));
        });
      }
      byId('crawlOverviewError').hidden = true;
    }

    async function loadOverview(force) {
      const now = Date.now();
      if (!force && state.overview && now - state.overviewLoadedAt < 10000) {
        renderOverview(state.overview);
        return;
      }
      setOverviewLoading(true, 'Đang tải tổng quan…');
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
      badge.className = 'crawl-broker-badge ' + prefix + '-' + stateValue.key;
      badge.textContent = stateValue.label;
      return badge;
    }

    function renderBrokerSystemRow(kind, titleText, detailText, actionLabel, onAction) {
      const rows = byId('crawlBrokerRows');
      clear(rows);
      const row = document.createElement('tr');
      const cell = brokerCell('Trạng thái', 'crawl-broker-empty state-' + kind);
      cell.colSpan = 6;
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

    function renderProfiles() {
      fillCityFilter();
      const rows = byId('crawlBrokerRows');
      clear(rows);
      const viewModel = buildBrokerRosterViewModel(state.draft, readBrokerFilters());
      text(byId('crawlBrokerTotal'), viewModel.summary.total);
      text(byId('crawlBrokerActive'), viewModel.summary.active);
      text(byId('crawlBrokerDue'), viewModel.summary.due);
      text(byId('crawlBrokerAttention'), viewModel.summary.needsAttention);
      text(
        byId('crawlBrokerCount'),
        String(viewModel.resultCount) + ' / ' + String(viewModel.summary.total) + ' môi giới',
      );
      text(
        byId('crawlBrokerFilterCount'),
        String(viewModel.activeFilterCount) + ' đang áp dụng',
      );
      byId('crawlBrokerResetBtn').disabled = viewModel.activeFilterCount === 0;

      if (viewModel.emptyState) {
        const empty = viewModel.emptyState === 'empty';
        renderBrokerSystemRow(
          viewModel.emptyState,
          empty ? 'Chưa có môi giới trong danh sách' : 'Không có môi giới phù hợp bộ lọc',
          empty
            ? 'Thêm môi giới đầu tiên để cấu hình lịch crawl.'
            : 'Đặt lại bộ lọc hoặc thử một từ khóa khác.',
          empty ? 'Thêm môi giới' : 'Đặt lại bộ lọc',
          empty ? () => openDrawer(null) : resetBrokerFilters,
        );
        return;
      }

      viewModel.filteredProfiles.forEach((profile) => {
        const index = state.draft.indexOf(profile);
        const row = document.createElement('tr');
        row.dataset.profileUrl = profile.url;

        const identity = brokerCell('Môi giới', 'crawl-broker-identity-cell');
        const identityStack = document.createElement('div');
        identityStack.className = 'crawl-broker-identity';
        const safeLink = safeFacebookProfileLink(profile.url);
        const brokerName = document.createElement(safeLink ? 'a' : 'strong');
        brokerName.className = 'crawl-broker-name';
        brokerName.textContent = profile.broker_name || 'Chưa đặt tên';
        if (safeLink) {
          brokerName.href = safeLink.href;
          brokerName.target = '_blank';
          brokerName.rel = 'noopener noreferrer';
        }
        const identityMeta = document.createElement('div');
        identityMeta.className = 'crawl-broker-identity-meta';
        const city = document.createElement('span');
        city.className = 'crawl-broker-city-chip';
        city.textContent = profile.city || 'Chưa có khu vực';
        identityMeta.appendChild(city);
        const urlNode = document.createElement(safeLink ? 'a' : 'span');
        urlNode.className = 'crawl-broker-url';
        urlNode.textContent = safeLink ? safeLink.display : (profile.url || 'Chưa có URL');
        if (safeLink) {
          urlNode.href = safeLink.href;
          urlNode.target = '_blank';
          urlNode.rel = 'noopener noreferrer';
        }
        identityMeta.appendChild(urlNode);
        identityStack.append(brokerName, identityMeta);
        identity.appendChild(identityStack);

        const statusState = brokerStatusState(profile);
        const scheduleState = brokerScheduleState(profile);
        const opsCell = brokerCell('Vận hành', 'crawl-broker-ops');
        opsCell.append(
          renderBrokerBadge(statusState, 'status'),
          renderBrokerBadge(scheduleState, 'schedule'),
        );
        const scheduleDetail = document.createElement('small');
        scheduleDetail.textContent = scheduleState.detail;
        opsCell.appendChild(scheduleDetail);

        const planCell = brokerCell('Kế hoạch', 'crawl-broker-plan');
        const quota = document.createElement('strong');
        quota.textContent = String(Number(profile.daily_limit || 20)) + ' bài/ngày';
        const cadence = document.createElement('small');
        cadence.textContent = String(Number(profile.crawl_every_days || 1))
          + ' ngày/lần · lấy '
          + String(Number(profile.range_days || 7))
          + ' ngày';
        planCell.append(quota, cadence);

        const qualityState = brokerQualityState(profile);
        const qualityCell = brokerCell(
          'Chất lượng',
          'crawl-broker-quality quality-' + qualityState.key,
        );
        qualityCell.appendChild(renderBrokerBadge(qualityState, 'quality'));
        const qualityScore = document.createElement('small');
        qualityScore.textContent = qualityState.score == null
          ? 'Chưa có điểm'
          : String(qualityState.score) + '/100';
        qualityCell.appendChild(qualityScore);

        const latestCell = brokerCell('Crawl cuối', 'crawl-broker-latest');
        latestCell.textContent = profile.latest_crawled_at || 'Chưa crawl';

        const actions = brokerCell('Thao tác', 'crawl-row-actions crawl-broker-actions');
        actions.append(
          button('Sửa', 'secondary-btn', () => openDrawer(index)),
          button('Chạy', 'secondary-btn', async () => {
            const selected = preselectRun(state, profile);
            state.runProfileUrl = selected.runProfileUrl;
            await setView('run', {force: true});
            applyRunDefaults();
          }),
          button('Xóa', 'secondary-btn danger-btn', () => {
            const label = profile.broker_name || profile.url;
            if (!confirmAction(
              'Xóa ' + label + ' khỏi danh sách crawl? Tin đã crawl vẫn được giữ nguyên.',
            )) return;
            state.draft = removeProfileFromDraft(state.draft, profile.url);
            if (state.runProfileUrl === profile.url) state.runProfileUrl = '';
            renderProfiles();
            renderRunProfiles();
            if (state.duplicates) renderDuplicates(state.duplicates, false);
            syncDirty();
            text(
              byId('crawlBrokerStatus'),
              'Đã bỏ môi giới khỏi bản nháp. Bấm Lưu thay đổi để áp dụng.',
            );
          }),
        );
        row.classList.toggle(
          'needs-attention',
          profile.active !== false
            && (profile.due_today === true || qualityState.key === 'needs_attention'),
        );
        row.append(
          identity,
          opsCell,
          planCell,
          qualityCell,
          latestCell,
          actions,
        );
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
      state.drawerReturnFocus = root.ownerDocument.activeElement;
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
      text(byId('crawlDrawerError'), '');
      byId('crawlBrokerDrawerBackdrop').hidden = false;
      const drawer = byId('crawlBrokerDrawer');
      drawer.hidden = false;
      byId('crawlDrawerName').focus();
    }

    function closeDrawer() {
      byId('crawlBrokerDrawer').hidden = true;
      byId('crawlBrokerDrawerBackdrop').hidden = true;
      state.drawerIndex = null;
      const returnFocus = state.drawerReturnFocus;
      state.drawerReturnFocus = null;
      if (returnFocus && typeof returnFocus.focus === 'function') returnFocus.focus();
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

    function setDuplicateState(kind, message) {
      const stateNode = byId('crawlDuplicateState');
      if (!stateNode) return;
      stateNode.dataset.state = kind;
      stateNode.hidden = kind === 'ready';
      text(stateNode, message);
    }

    function renderDuplicates(page, append) {
      state.duplicates = page;
      setDuplicateState(
        duplicatePresentationState(page, false),
        Array.isArray(page.items) && page.items.length
          ? ''
          : 'Không có cặp môi giới phù hợp phạm vi đang xem.',
      );
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
      setDuplicateState(
        'loading',
        append ? 'Đang tải thêm cặp trùng…' : 'Đang tải phân tích trùng…',
      );
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
        setDuplicateState(
          'error',
          'Không tải được phân tích trùng. Thử lại bằng nút chuyển phạm vi.',
        );
        text(byId('crawlDuplicateSummary'), 'Phân tích trùng tạm thời chưa khả dụng.');
        byId('crawlDuplicateMoreBtn').hidden = true;
      }
    }

    async function loadProfiles(force) {
      if (state.profilesLoaded && !force) {
        renderProfiles();
        return;
      }
      const workbench = byId('crawlBrokerWorkbench');
      if (workbench) workbench.setAttribute('aria-busy', 'true');
      text(byId('crawlBrokerStatus'), 'Đang tải danh sách môi giới…');
      if (!state.profilesLoaded) {
        renderBrokerSystemRow(
          'loading',
          'Đang tải danh sách môi giới',
          'Dữ liệu sẽ xuất hiện ngay khi máy chủ phản hồi.',
        );
      }
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
        if (workbench) workbench.setAttribute('aria-busy', 'false');
        text(byId('crawlBrokerStatus'), 'Đã cập nhật');
        await loadDuplicates(false);
      } catch (_error) {
        if (workbench) workbench.setAttribute('aria-busy', 'false');
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
      byId('crawlOverviewRunBtn').addEventListener('click', () => setView('run'));
      byId('crawlOverviewBrokersBtn').addEventListener('click', () => setView('brokers'));
      byId('crawlOverviewRetryBtn').addEventListener('click', () => loadOverview(true));
      byId('crawlTokenDetails').addEventListener('toggle', (event) => {
        if (event.target.open) loadTokens(false);
      });
      byId('crawlTokenAddBtn').addEventListener('click', addToken);
      byId('crawlSaveProfilesBtn').addEventListener('click', saveProfiles);
      byId('crawlAddBrokerBtn').addEventListener('click', () => openDrawer(null));
      byId('crawlDrawerCloseBtn').addEventListener('click', closeDrawer);
      byId('crawlDrawerCancelBtn').addEventListener('click', closeDrawer);
      byId('crawlDrawerSaveBtn').addEventListener('click', saveDrawer);
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
      byId('crawlBrokerResetBtn').addEventListener('click', resetBrokerFilters);
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
    removeProfileFromDraft,
    requestsForView,
    brokerQualityState,
    brokerStatusState,
    brokerScheduleState,
    safeFacebookProfileLink,
    buildBrokerRosterViewModel,
    groupOverviewProblems,
    buildOverviewViewModel,
    buildRunPreview,
    buildMaintenancePreview,
    runLimitForMode,
    nextDuplicateOffset,
    duplicatePresentationState,
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
