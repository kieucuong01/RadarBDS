const STATUS = {
  new: { label: 'Chờ xử lý', cls: 'status-new' },
  called: { label: 'Đang tư vấn', cls: 'status-called' },
  viewing: { label: 'Đi xem đất', cls: 'status-viewing' },
  deposit: { label: 'Chốt cọc', cls: 'status-deposit' },
  cancelled: { label: 'Hủy', cls: 'status-cancelled' }
};
const STATUS_KEYS = Object.keys(STATUS);
const SOURCE_NAMES = { facebook: 'Facebook', guland: 'Guland', batdongsan: 'BDS.vn' };
const PTYPES = { dat_nen: 'Đất nền', dat_vuon: 'Đất vườn', nha_dat: 'Nhà đất', nha_tro: 'Nhà trọ', chung_cu: 'Chung cư', nha_o_xa_hoi: 'Nhà ở xã hội' };
const PLACEHOLDER = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='640' height='420' viewBox='0 0 640 420'%3E%3Crect width='640' height='420' fill='%23eef2f7'/%3E%3Cpath d='M250 250l55-72 44 57 25-32 66 82H204z' fill='%2394a3b8'/%3E%3Ccircle cx='392' cy='150' r='24' fill='%2394a3b8'/%3E%3C/svg%3E";
const ADMIN_THEME_KEY = 'radar_admin_theme';
const ADMIN_PANEL_SLUGS = Object.assign({
  crm: 'crm',
  quality: 'data-quality',
  crawl: 'facebook-crawl',
  training: 'ai-training',
  infra: 'infrastructure',
  users: 'users'
}, window.ADMIN_CONTROL_ROOM_PANEL_SLUGS || {});
const ADMIN_SLUG_TO_PANEL = Object.entries(ADMIN_PANEL_SLUGS).reduce((acc, [panel, slug]) => {
  acc[slug] = panel;
  return acc;
}, {});

let leadTimer = null;
let activeQualityTab = 'dups';
let activeInfraFilter = 'timeline';
let crawlProfiles = [];
let crawlSummary = {};
let apifyTokens = [];
let apifyTokensExpanded = false;
let dataQualitySummary = {};
let crawlMode = 'first';
let crawlPollTimer = null;
let activeCrawlJobId = null;
let adminToastSeq = 0;
let adminToastDepth = 0;

function initAdminTheme() {
  const saved = localStorage.getItem(ADMIN_THEME_KEY) || 'light';
  document.documentElement.setAttribute('data-theme', saved);
}

function toggleAdminTheme() {
  const current = document.documentElement.getAttribute('data-theme') || 'light';
  const next = current === 'dark' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', next);
  localStorage.setItem(ADMIN_THEME_KEY, next);
}

function esc(v) {
  return String(v ?? '').replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
}

async function fetchJSON(url, options = {}) {
  const clean = new URL(url, window.location.href);
  clean.username = '';
  clean.password = '';
  const method = String(options.method || 'GET').toUpperCase();
  const isPoll = clean.pathname.includes('/admin/api/facebook-crawl/jobs/');
  const shouldToast = !options.silent && !isPoll && adminToastDepth === 0;
  const toast = shouldToast
    ? showAdminToast(method === 'GET' ? 'Đang tải dữ liệu' : 'Đang xử lý tác vụ', 'loading', { sticky: true })
    : null;
  try {
    const res = await fetch(clean.toString(), options);
    if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
    const data = await res.json();
    if (toast) updateAdminToast(toast, method === 'GET' ? 'Đã tải dữ liệu' : 'Đã xử lý xong', 'success');
    return data;
  } catch (error) {
    if (toast) updateAdminToast(toast, `Tác vụ lỗi: ${formatAdminError(error)}`, 'error', { delay: 5200 });
    throw error;
  }
}

function ensureToastRoot() {
  let root = document.getElementById('adminToastRoot');
  if (!root) {
    root = document.createElement('div');
    root.id = 'adminToastRoot';
    root.className = 'admin-toast-root';
    root.setAttribute('aria-live', 'polite');
    root.setAttribute('aria-atomic', 'false');
    document.body.appendChild(root);
  }
  return root;
}

function ensureAdminLoadingOverlay() {
  let overlay = document.getElementById('adminLoadingOverlay');
  if (!overlay) {
    overlay = document.createElement('div');
    overlay.id = 'adminLoadingOverlay';
    overlay.className = 'admin-main-loading';
    overlay.setAttribute('aria-hidden', 'true');
    overlay.innerHTML = `
      <div class="admin-main-loading-box" role="status" aria-live="polite">
        <span class="admin-main-loading-spinner"></span>
        <strong>Đang tải dữ liệu...</strong>
        <small>Vui lòng đợi trong giây lát</small>
      </div>
    `;
    (document.querySelector('.admin-main') || document.body).appendChild(overlay);
  }
  return overlay;
}

function syncAdminLoadingOverlay() {
  const active = document.querySelectorAll('.admin-toast.loading').length > 0;
  const overlay = active ? ensureAdminLoadingOverlay() : document.getElementById('adminLoadingOverlay');
  const main = document.querySelector('.admin-main');
  if (main) main.setAttribute('aria-busy', active ? 'true' : 'false');
  if (!overlay) return;
  overlay.classList.toggle('active', active);
  overlay.setAttribute('aria-hidden', active ? 'false' : 'true');
}

function showAdminToast(message, type = 'loading', options = {}) {
  const root = ensureToastRoot();
  const toast = document.createElement('div');
  toast.className = `admin-toast ${type}`;
  toast.dataset.toastId = String(++adminToastSeq);
  toast.innerHTML = `
    <span class="admin-toast-dot"></span>
    <span class="admin-toast-text">${esc(message)}</span>
  `;
  root.prepend(toast);
  if (!options.sticky && type !== 'loading') {
    setTimeout(() => dismissAdminToast(toast), options.delay || 2400);
  }
  syncAdminLoadingOverlay();
  return toast;
}

function updateAdminToast(toast, message, type = 'success', options = {}) {
  if (!toast) return;
  toast.className = `admin-toast ${type}`;
  const text = toast.querySelector('.admin-toast-text');
  if (text) text.textContent = message;
  if (!options.sticky && type !== 'loading') {
    setTimeout(() => dismissAdminToast(toast), options.delay || 2400);
  }
  syncAdminLoadingOverlay();
}

function dismissAdminToast(toast) {
  if (!toast || !toast.parentNode) return;
  toast.classList.add('leaving');
  setTimeout(() => {
    toast.remove();
    syncAdminLoadingOverlay();
  }, 180);
}

function formatAdminError(error) {
  const msg = String(error?.message || error || 'Không rõ lỗi');
  return msg.length > 150 ? `${msg.slice(0, 150)}...` : msg;
}

async function withAdminToast(loadingMessage, task, successMessage = 'Hoàn tất', errorMessage = 'Có lỗi xảy ra') {
  const toast = showAdminToast(loadingMessage, 'loading', { sticky: true });
  try {
    adminToastDepth += 1;
    const result = await task();
    updateAdminToast(toast, successMessage, 'success');
    return result;
  } catch (error) {
    console.error(error);
    updateAdminToast(toast, `${errorMessage}: ${formatAdminError(error)}`, 'error', { delay: 5200 });
    return null;
  } finally {
    adminToastDepth = Math.max(0, adminToastDepth - 1);
  }
}

function money(v) {
  if (v === null || v === undefined || v === '') return '-';
  return `${Number(v).toLocaleString('vi-VN', { maximumFractionDigits: 2 })} tỷ`;
}

function area(v) {
  if (v === null || v === undefined || v === '') return '-';
  return `${Number(v).toLocaleString('vi-VN', { maximumFractionDigits: 1 })} m²`;
}

function ppm2(v) {
  if (v === null || v === undefined || v === '') return '-';
  const n = Number(v);
  if (!Number.isFinite(n) || n <= 0) return '-';
  return `${n.toLocaleString('vi-VN', { maximumFractionDigits: 1 })} tr/m²`;
}

function formatAuditValue(v) {
  if (v === null || v === undefined || v === '') return '-';
  if (typeof v === 'number') return v.toLocaleString('vi-VN', { maximumFractionDigits: 3 });
  return String(v);
}

function shortDate(v) {
  return (v || '').replace('T', ' ').slice(0, 16) || '-';
}

function normalizePanelName(name) {
  return ADMIN_PANEL_SLUGS[name] ? name : 'crm';
}

function panelSlug(name) {
  return ADMIN_PANEL_SLUGS[normalizePanelName(name)] || 'crm';
}

function panelUrl(name) {
  return `/admin/${panelSlug(name)}`;
}

function panelFromLocation() {
  const path = window.location.pathname.replace(/\/+$/, '');
  if (path === '/admin' || path === '/admin/control-room') {
    return 'crm';
  }
  const match = path.match(/\/admin(?:\/control-room)?\/([^/]+)$/);
  if (match) {
    const slug = decodeURIComponent(match[1]);
    if (ADMIN_SLUG_TO_PANEL[slug]) return ADMIN_SLUG_TO_PANEL[slug];
  }
  const initial = window.ADMIN_INITIAL_PANEL || document.body?.dataset.adminInitialPanel || 'crm';
  return normalizePanelName(initial);
}

function syncPanelUrl(name) {
  if (!window.history?.pushState) return;
  const nextPath = panelUrl(name);
  if (window.location.pathname === nextPath) return;
  history.pushState({ adminPanel: normalizePanelName(name) }, '', nextPath);
}

function switchPanel(name, options = {}) {
  name = normalizePanelName(name);
  document.querySelectorAll('.nav-item').forEach(btn => btn.classList.toggle('active', btn.dataset.panel === name));
  document.querySelectorAll('.workspace-panel').forEach(panel => panel.classList.toggle('active', panel.id === `panel-${name}`));
  if (options.updateUrl !== false) syncPanelUrl(name);
  const panelLabels = { crm: 'CRM', quality: 'Quality', training: 'AI Training', infra: 'Hạ tầng', users: 'Users', crawl: 'Facebook Crawl' };
  let loader = null;
  if (name === 'crm') loader = loadLeads;
  if (name === 'quality') {
    loader = async () => {
      await loadDataQualitySummary();
      if (activeQualityTab === 'dups') await loadDuplicates();
      else if (activeQualityTab === 'blacklist') await loadBlacklist();
      else await loadDataQualityQueue(activeQualityTab);
    };
  }
  if (name === 'training') loader = () => loadTrainingItems(false);
  if (name === 'infra') loader = loadInfraItems;
  if (name === 'users') loader = loadUsers;
  if (name === 'crawl') loader = loadCrawlConfig;
  if (loader) {
    withAdminToast(`Đang mở ${panelLabels[name] || 'tab'}`, loader, `Đã mở ${panelLabels[name] || 'tab'}`, 'Không tải được tab');
  }
}

// â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
// Facebook crawl manager
// â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

function crawlProfileLabel(p) {
  const name = p.broker_name || p.url.replace('https://www.facebook.com/', '');
  return `${name}${p.city ? ' · ' + p.city : ''}`;
}

function readCrawlTableState() {
  document.querySelectorAll('#crawlProfileRows tr[data-url]').forEach(row => {
    const p = crawlProfiles.find(x => x.url === row.dataset.url);
    if (!p) return;
    p.active = !!row.querySelector('[data-crawl-field="active"]')?.checked;
    p.broker_name = row.querySelector('[data-crawl-field="broker_name"]')?.value.trim() || '';
    p.city = row.querySelector('[data-crawl-field="city"]')?.value.trim() || '';
    p.daily_limit = Number(row.querySelector('[data-crawl-field="daily_limit"]')?.value || p.daily_limit || 20);
    p.tier = p.daily_limit;
    p.range_days = Number(row.querySelector('[data-crawl-field="range_days"]')?.value || p.range_days || 7);
  });
}

async function loadCrawlConfig() {
  const data = await fetchJSON('/admin/api/facebook-crawl/config');
  crawlProfiles = data.profiles || [];
  crawlSummary = data.summary || {};
  apifyTokens = data.apify_tokens || [];
  renderCrawlStats(crawlSummary);
  renderCrawlOps(crawlSummary.ops || {});
  renderApifyTokens();
  renderCrawlProfiles();
  renderCrawlRunSelect();
  if (data.summary?.active_job?.id) {
    activeCrawlJobId = data.summary.active_job.id;
    renderCrawlJob(data.summary.active_job);
    startCrawlPolling(activeCrawlJobId);
  }
}

function renderApifyTokens() {
  const body = document.getElementById('apifyTokenRows');
  renderApifyTokenShell();
  if (!body) return;
  if (!apifyTokens.length) {
    body.innerHTML = `<tr><td colspan="7"><div class="empty">Chưa có key trong pool. Nếu trống, crawler sẽ dùng APIFY_TOKEN từ .env.</div></td></tr>`;
    return;
  }
  body.innerHTML = apifyTokens.map(t => {
    const pct = t.monthly_quota ? Math.min(100, Math.round((Number(t.used_this_month || 0) / Number(t.monthly_quota)) * 100)) : 0;
    const warn = Number(t.remaining || 0) <= 100 ? 'warn' : '';
    return `
      <tr data-token-id="${esc(t.id)}">
        <td data-label="Bật">
          <label class="crawl-switch">
            <input type="checkbox" ${t.active ? 'checked' : ''} onchange="toggleApifyToken('${esc(t.id)}', this.checked)">
            <span></span>
          </label>
        </td>
        <td data-label="Key"><strong>${esc(t.label)}</strong><br><small>${esc(t.token_mask)}</small></td>
        <td data-label="Quota">${Number(t.monthly_quota || 0).toLocaleString('vi-VN')}</td>
        <td data-label="Đã dùng">
          <div class="apify-usage"><span style="width:${pct}%"></span></div>
          <small>${Number(t.used_this_month || 0).toLocaleString('vi-VN')} post · ${esc(t.month || '')}</small>
        </td>
        <td data-label="Còn lại"><strong class="${warn}">${Number(t.remaining || 0).toLocaleString('vi-VN')}</strong></td>
        <td data-label="Trạng thái">${t.last_error ? `<span class="crawl-error">${esc(t.last_error)}</span>` : `<span class="ok-text">OK</span>`}<br><small>${esc(shortDate(t.last_used_at))}</small></td>
        <td data-label="Thao tác" class="apify-token-actions">
          <button class="icon-btn" onclick="resetApifyTokenUsage('${esc(t.id)}')">Reset</button>
          <button class="icon-btn danger" onclick="deleteApifyToken('${esc(t.id)}')">Xóa</button>
        </td>
      </tr>
    `;
  }).join('');
}

function apifyTokenStats() {
  const total = apifyTokens.length;
  const active = apifyTokens.filter(t => t.active).length;
  const used = apifyTokens.reduce((sum, t) => sum + Number(t.used_this_month || 0), 0);
  const quota = apifyTokens.reduce((sum, t) => sum + Number(t.monthly_quota || 0), 0);
  const remaining = apifyTokens.reduce((sum, t) => sum + Math.max(0, Number(t.remaining || 0)), 0);
  const errors = apifyTokens.filter(t => t.last_error).length;
  const low = apifyTokens.filter(t => t.active && !t.last_error && Number(t.remaining || 0) <= 100).length;
  return { total, active, used, quota, remaining, errors, low };
}

function renderApifyTokenShell() {
  const panel = document.getElementById('apifyTokenPanel');
  const body = document.getElementById('apifyTokenBody');
  const button = document.getElementById('toggleApifyTokensBtn');
  const summary = document.getElementById('apifyTokenSummary');
  const miniStats = document.getElementById('apifyTokenMiniStats');
  const stats = apifyTokenStats();
  if (panel) panel.classList.toggle('is-collapsed', !apifyTokensExpanded);
  if (body) body.hidden = !apifyTokensExpanded;
  if (button) button.textContent = apifyTokensExpanded ? 'Thu gọn' : (stats.total ? 'Quản lý key' : 'Thêm key');
  if (summary) {
    summary.textContent = stats.total
      ? `${stats.active}/${stats.total} key đang bật · còn ${stats.remaining.toLocaleString('vi-VN')} post tháng này`
      : 'Chưa cấu hình key pool, crawler sẽ dùng APIFY_TOKEN từ .env.';
  }
  if (miniStats) {
    const usagePct = stats.quota ? Math.min(100, Math.round((stats.used / stats.quota) * 100)) : 0;
    miniStats.innerHTML = `
      <span><strong>${stats.remaining.toLocaleString('vi-VN')}</strong><small>còn lại</small></span>
      <span><strong>${usagePct}%</strong><small>đã dùng</small></span>
      <span class="${stats.errors ? 'danger' : stats.low ? 'warn' : 'ok'}"><strong>${stats.errors || stats.low || 'OK'}</strong><small>${stats.errors ? 'lỗi key' : stats.low ? 'sắp hết' : 'quota ổn'}</small></span>
    `;
  }
}

function toggleApifyTokensPanel() {
  apifyTokensExpanded = !apifyTokensExpanded;
  renderApifyTokenShell();
}

async function saveApifyToken(payload) {
  const data = await fetchJSON('/admin/api/facebook-crawl/tokens', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  apifyTokens = data.tokens || [];
  renderApifyTokens();
}

async function addApifyToken() {
  const label = document.getElementById('apifyTokenLabel').value.trim();
  const token = document.getElementById('apifyTokenValue').value.trim();
  const monthly_quota = Number(document.getElementById('apifyTokenQuota').value || 950);
  if (!token.startsWith('apify_api_')) return alert('Token Apify chưa đúng định dạng apify_api_...');
  await withAdminToast('Đang thêm Apify key', async () => {
    await saveApifyToken({ label, token, monthly_quota, active: true });
    document.getElementById('apifyTokenLabel').value = '';
    document.getElementById('apifyTokenValue').value = '';
  }, 'Đã thêm Apify key', 'Không thêm được Apify key');
}

async function toggleApifyToken(id, active) {
  const current = apifyTokens.find(t => t.id === id);
  if (!current) return;
  await withAdminToast(active ? 'Đang bật Apify key' : 'Đang tắt Apify key', () => (
    saveApifyToken({ id, label: current.label, monthly_quota: current.monthly_quota, active })
  ), active ? 'Đã bật Apify key' : 'Đã tắt Apify key', 'Không cập nhật được Apify key');
}

async function resetApifyTokenUsage(id) {
  if (!confirm('Reset số post đã dùng tháng này cho key này?')) return;
  await withAdminToast('Đang reset lượt dùng Apify key', async () => {
    const data = await fetchJSON(`/admin/api/facebook-crawl/tokens/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'reset_usage' }),
    });
    apifyTokens = data.tokens || [];
    renderApifyTokens();
  }, 'Đã reset lượt dùng Apify key', 'Không reset được lượt dùng');
}

async function deleteApifyToken(id) {
  if (!confirm('Xóa key Apify này khỏi pool?')) return;
  await withAdminToast('Đang xóa Apify key', async () => {
    const data = await fetchJSON(`/admin/api/facebook-crawl/tokens/${id}`, { method: 'DELETE' });
    apifyTokens = data.tokens || [];
    renderApifyTokens();
  }, 'Đã xóa Apify key', 'Không xóa được Apify key');
}

function renderCrawlStats(summary) {
  const active = crawlProfiles.filter(p => p.active !== false).length;
  const ops = summary.ops || {};
  const last24 = ops.last_24h || {};
  const blockers = ops.lock_blockers || [];
  const sourceErrors = ops.source_errors || [];
  const missingImages = summary.missing_images || {};
  const missingImageRefs = Number(missingImages.missing_image_refs || summary.pending_images || 0);
  const missingImageListings = Number(missingImages.listings_with_missing_images || 0);
  const items = [
    ['Môi giới bật', active, 'đang dùng'],
    ['Tổng môi giới', crawlProfiles.length, 'trong cấu hình'],
    ['Listing FB', summary.facebook_listings || 0, 'đã xử lý'],
    ['Signal', ops.signal_count || 0, 'đang active'],
    ['Tin mới gần nhất', last24.new || 0, 'new'],
    ['Nguồn lỗi', sourceErrors.length || 0, 'cần xem'],
    ['Lock kẹt', blockers.length || 0, 'job'],
    ['Job hiện tại', summary.active_job ? summary.active_job.status : 'Idle', summary.active_job ? summary.active_job.stage : 'sẵn sàng'],
  ];
  items.splice(3, 0, [
    'Ảnh FB thiếu',
    missingImageRefs.toLocaleString('vi-VN'),
    `${missingImageListings.toLocaleString('vi-VN')} listing`,
    missingImageRefs ? 'var(--orange)' : 'var(--green)',
  ]);
  const el = document.getElementById('crawlStats');
  if (!el) return;
  el.innerHTML = items.map((s, idx) => `
    <div class="stat-card">
      <small>${esc(s[0])}</small>
      <div><strong style="color:${s[3] || (idx === 6 && Number(s[1]) ? 'var(--orange)' : idx === 7 && Number(s[1]) ? 'var(--red)' : idx === 8 && s[1] !== 'Idle' ? 'var(--blue)' : 'var(--ink)')}">${esc(s[1])}</strong><span>${esc(s[2])}</span></div>
    </div>
  `).join('');
}

function renderCrawlOps(ops = {}) {
  const el = document.getElementById('crawlOpsPanel');
  if (!el) return;
  const schedule = ops.schedule || {};
  const last = ops.last_run || {};
  const last24 = ops.last_24h || {};
  const source_errors = ops.source_errors || [];
  const lock_blockers = ops.lock_blockers || [];
  const missingImages = crawlSummary.missing_images || {};
  const missingImageRefs = Number(missingImages.missing_image_refs || crawlSummary.pending_images || 0);
  const missingPct = Number(missingImages.missing_pct || 0);
  const scheduleName = schedule.task_name || 'RadarBDS_DailyCrawl';
  const serviceFailed = Boolean(schedule.service_failed);
  const serviceExit = schedule.service_exit_code ? `exit=${schedule.service_exit_code}` : '';
  const serviceResult = schedule.service_result || '';
  const serviceState = schedule.service_state || '';
  const serviceLogHint = schedule.service_log_hint || 'logs/crawl-daily.log';
  const serviceFailureText = [serviceState, serviceResult, serviceExit].filter(Boolean).join(' · ');
  const scheduleOk = schedule.installed && !serviceFailed && (schedule.run_time === '21:00' || String(schedule.next_run_time || '').includes('9:00'));
  const healthClass = serviceFailed || lock_blockers.length ? 'danger' : source_errors.length ? 'warn' : 'ok';
  const serviceAlert = serviceFailed ? `
    <div class="crawl-ops-alert danger">
      <strong>Daily crawl lần gần nhất bị lỗi</strong>
      <span>${esc(serviceFailureText || 'radar-bds-crawl.service failed')} · xem log: <code>${esc(serviceLogHint)}</code></span>
    </div>
  ` : '';
  const sourceList = source_errors.length
    ? source_errors.map(x => `
        <li>
          <strong>${esc(x.source || 'unknown')}</strong>
          <span>${esc(x.status || 'error')} · fetched=${Number(x.fetched || 0)} · new=${Number(x.new || 0)}</span>
          ${x.error_msg ? `<em>${esc(x.error_msg)}</em>` : ''}
        </li>
      `).join('')
    : `<li><strong>OK</strong><span>Không có lỗi nguồn trong các run gần đây.</span></li>`;
  const lockList = lock_blockers.length
    ? lock_blockers.map(x => `
        <li>
          <strong>${esc(x.name || 'lock')}</strong>
          <span>${esc(x.state || 'locked')}${x.pid ? ` · pid=${esc(x.pid)}` : ''}</span>
          ${x.error ? `<em>${esc(x.error)}</em>` : ''}
        </li>
      `).join('')
    : `<li><strong>OK</strong><span>Không có crawl/reprocess lock đang chặn.</span></li>`;

  el.innerHTML = `
    <div class="crawl-ops-head">
      <div>
        <small>Daily Automation</small>
        <strong>${esc(schedule.task_name || scheduleName)}</strong>
      </div>
      <span class="ops-pill ${healthClass}">${lock_blockers.length ? 'Lock đang kẹt' : source_errors.length ? 'Cần xem lỗi nguồn' : 'Đang ổn định'}</span>
    </div>
    <div class="crawl-ops-grid">
      <div class="crawl-ops-card ${scheduleOk ? 'ok' : 'warn'}">
        <small>Lich daily</small>
        <strong>${schedule.installed ? (schedule.run_time || shortDate(schedule.next_run_time) || 'Đã cài') : 'Chưa cài'}</strong>
        <span>${schedule.installed ? `Next: ${esc(schedule.next_run_time || 'chưa rõ')}` : `Cần cài ${esc(scheduleName)} lúc 21:00`}</span>
        ${schedule.error ? `<em>${esc(schedule.error)}</em>` : ''}
      </div>
      <div class="crawl-ops-card">
        <small>Lần chạy gần nhất</small>
        <strong>${last.source ? `${esc(last.source)} · ${esc(last.status || '')}` : 'Chưa có run'}</strong>
        <span>${last.started_at ? `${esc(shortDate(last.started_at))} · new=${Number(last.new || 0)} · fetched=${Number(last.fetched || 0)}` : 'Chưa có crawl_runs'}</span>
      </div>
      <div class="crawl-ops-card">
        <small>Batch gan nhat</small>
        <strong>${Number(last24.new || 0).toLocaleString('vi-VN')} tin mới</strong>
        <span>${Number(last24.runs || 0)} runs · fetched=${Number(last24.fetched || 0).toLocaleString('vi-VN')} · skipped=${Number(last24.skipped || 0).toLocaleString('vi-VN')}</span>
      </div>
      <div class="crawl-ops-card ${missingImageRefs ? 'warn' : 'ok'}">
        <small>Ảnh Facebook còn thiếu</small>
        <strong>${missingImageRefs.toLocaleString('vi-VN')} ảnh</strong>
        <span>${Number(missingImages.listings_with_missing_images || 0).toLocaleString('vi-VN')} listing · ${missingPct.toLocaleString('vi-VN')}% tổng ảnh FB</span>
      </div>
    </div>
    <div class="crawl-ops-lists">
      <div>
        <h3>Lỗi nguồn gần đây</h3>
        <ul>${sourceList}</ul>
      </div>
      <div>
        <h3>Lock crawl/reprocess</h3>
        <ul>${lockList}</ul>
      </div>
    </div>
  `;
  if (serviceFailed) {
    const pill = el.querySelector('.ops-pill');
    if (pill) pill.textContent = 'Daily crawl lỗi';
    const head = el.querySelector('.crawl-ops-head');
    if (head) head.insertAdjacentHTML('afterend', serviceAlert);
    const scheduleCard = el.querySelector('.crawl-ops-card');
    if (scheduleCard) {
      scheduleCard.classList.remove('ok', 'warn');
      scheduleCard.classList.add('danger');
      const strong = scheduleCard.querySelector('strong');
      const span = scheduleCard.querySelector('span');
      if (strong) strong.textContent = 'Lần chạy gần nhất lỗi';
      if (span) span.textContent = `${serviceFailureText || 'service failed'} · log: ${serviceLogHint}`;
    }
  }
}

function qualityFlagLabel(flag) {
  const labels = {
    parsed_discount_as_price: 'Nhầm giảm giá thành giá bán',
    down_payment_as_price: 'Nhầm cọc thành giá bán',
    too_low_absolute_price: 'Giá tuyệt đối quá thấp',
    large_lot_model_risk: 'Rủi ro lô lớn',
    area_dimension_conflict: 'Mâu thuẫn DT/kích thước',
    source_category_conflict: 'Sai loại hình nguồn',
    multi_lot_listing: 'Tin nhiều lô',
    guland_weak_signal: 'Guland signal yếu',
    guland_user_facing_risk: 'Guland cần kiểm tra',
    old_guland_post: 'Guland bài cũ',
    extreme_guland_ppm2: 'Guland giá/m² bất thường',
    suspicious_bait: 'Nghi mồi giá',
    guland_cluster_flood: 'Cụm Guland trùng',
    review_bad_valuation: 'Review định giá sai',
    review_bad_extraction: 'Review bóc tách sai',
    source_quality_recheck: 'Cần QC nguồn',
    test_artifact: 'Tin test'
  };
  return labels[flag] || flag.replaceAll('_', ' ');
}

async function loadDataQualitySummary() {
  const data = await fetchJSON('/admin/api/data-quality/summary');
  dataQualitySummary = data || {};
  renderDataQualitySummary(dataQualitySummary);
}

function renderDataQualitySummary(data = {}) {
  const el = document.getElementById('qualityOverview');
  if (!el) return;
  const images = data.missing_images || {};
  const apify = data.apify_pool || {};
  const crawl = data.crawl_health || {};
  const suppressed = data.suppressed_signals || {};
  const sourceErrors = crawl.source_errors || [];
  const lockBlockers = crawl.lock_blockers || [];
  const tokens = apify.tokens || [];
  const flags = suppressed.by_flag || [];
  const sources = suppressed.by_source || [];
  const missingRefs = Number(images.missing_image_refs || 0);
  const missingListings = Number(images.listings_with_missing_images || 0);
  const remaining = Number(apify.total_remaining || 0);
  const quota = Number(apify.monthly_quota || 0);
  const activeTokens = Number(apify.active_tokens || 0);
  const suppressedTotal = Number(suppressed.total || 0);
  const crawlProblemCount = sourceErrors.length + lockBlockers.length;
  const retryableSources = new Set(['facebook', 'guland']);
  const kpis = [
    {
      cls: missingRefs ? 'warn' : 'ok',
      label: 'Ảnh thiếu',
      value: missingRefs.toLocaleString('vi-VN'),
      note: `${missingListings.toLocaleString('vi-VN')} listing · ${Number(images.missing_pct || 0).toLocaleString('vi-VN')}% tổng ảnh`
    },
    {
      cls: !activeTokens || remaining <= 100 ? 'warn' : 'ok',
      label: 'Apify còn lại',
      value: activeTokens ? remaining.toLocaleString('vi-VN') : 'Chưa có key',
      note: activeTokens ? `${activeTokens} key bật · quota ${quota.toLocaleString('vi-VN')}/tháng` : 'Crawler sẽ cần APIFY_TOKEN env hoặc key pool'
    },
    {
      cls: crawlProblemCount ? 'danger' : 'ok',
      label: 'Nguồn crawl lỗi',
      value: sourceErrors.length.toLocaleString('vi-VN'),
      note: lockBlockers.length ? `${lockBlockers.length} lock đang chặn` : `Run gần nhất: ${shortDate(crawl.last_run?.started_at)}`
    },
    {
      cls: suppressedTotal ? 'warn' : 'ok',
      label: 'Signal bị suppress',
      value: suppressedTotal.toLocaleString('vi-VN'),
      note: sources.length ? sources.map(x => `${SOURCE_NAMES[x.source] || x.source}: ${Number(x.count || 0).toLocaleString('vi-VN')}`).join(' · ') : 'Không có signal bị chặn'
    }
  ];
  const tokenList = tokens.length
    ? tokens.map(t => {
        const tQuota = Number(t.monthly_quota || 0);
        const tUsed = Number(t.used_this_month || 0);
        const tRemaining = Number(t.remaining || 0);
        const pct = tQuota ? Math.min(100, Math.round((tUsed / tQuota) * 100)) : 0;
        return `
          <li>
            <div>
              <strong>${esc(t.label || 'Apify key')}</strong>
              <span>${t.active ? 'Đang bật' : 'Đã tắt'} · ${esc(t.token_mask || '')}</span>
              <div class="quality-token-bar"><i style="width:${pct}%"></i></div>
            </div>
            <b class="${tRemaining <= 100 ? 'warn' : ''}">${tRemaining.toLocaleString('vi-VN')}</b>
            ${t.last_error ? `<em>${esc(t.last_error)}</em>` : ''}
          </li>
        `;
      }).join('')
    : `<li><div><strong>Chưa có Apify key trong pool</strong><span>Thêm key ở tab Facebook Crawl để theo dõi quota rõ hơn.</span></div></li>`;
  const sourceList = sourceErrors.length
    ? sourceErrors.map(x => {
        const source = String(x.source || '').trim().toLowerCase().replace(/[^a-z0-9_-]/g, '');
        const retryButton = retryableSources.has(source)
          ? `<button class="quality-action-btn danger" type="button" onclick="retryDataQualitySourceCrawl('${esc(source)}')">Crawl lại nguồn</button>`
          : '';
        return `
        <li>
          <div>
            <strong>${esc(SOURCE_NAMES[x.source] || x.source || 'unknown')}</strong>
            <span>${esc(x.status || 'error')} · fetched=${Number(x.fetched || 0).toLocaleString('vi-VN')} · new=${Number(x.new || 0).toLocaleString('vi-VN')}</span>
          </div>
          ${x.error_msg ? `<em>${esc(x.error_msg)}</em>` : ''}
          ${retryButton}
        </li>
      `;
      }).join('')
    : `<li><div><strong>Không có lỗi nguồn gần đây</strong><span>Các run gần nhất không báo error hoặc fetched=0.</span></div></li>`;
  const flagList = flags.length
    ? flags.map(x => `
        <li>
          <div>
            <strong>${esc(qualityFlagLabel(x.flag))}</strong>
            <span>${esc(x.flag)}</span>
          </div>
          <b>${Number(x.count || 0).toLocaleString('vi-VN')}</b>
        </li>
      `).join('')
    : `<li><div><strong>Không có quality flag đang chặn signal</strong><span>Signal model-cheap hiện không bị suppress bởi source quality.</span></div></li>`;

  el.innerHTML = `
    <div class="quality-kpi-grid">
      ${kpis.map(item => `
        <article class="quality-kpi-card ${item.cls}">
          <small>${esc(item.label)}</small>
          <strong>${esc(item.value)}</strong>
          <span>${esc(item.note)}</span>
        </article>
      `).join('')}
    </div>
    <div class="quality-detail-grid">
      <article class="surface quality-detail-card">
        <h3>Ảnh thiếu</h3>
        <p class="quality-detail-note">${missingRefs ? `${missingRefs.toLocaleString('vi-VN')} ảnh còn thiếu local từ ${missingListings.toLocaleString('vi-VN')} listing.` : 'Không còn ảnh thiếu trong hàng chờ.'}</p>
        <div class="quality-card-actions">
          <button class="primary-btn" type="button" onclick="downloadMissingImagesFromQuality()" ${missingRefs ? '' : 'disabled'}>Tải ảnh thiếu</button>
        </div>
      </article>
      <article class="surface quality-detail-card">
        <h3>Apify quota</h3>
        ${apify.error ? `<div class="quality-mini-alert danger">${esc(apify.error)}</div>` : ''}
        <ul class="quality-list">${tokenList}</ul>
      </article>
      <article class="surface quality-detail-card">
        <h3>Lỗi crawl theo nguồn</h3>
        <ul class="quality-list">${sourceList}</ul>
      </article>
      <article class="surface quality-detail-card">
        <h3>Quality flags suppress signal</h3>
        ${suppressed.error ? `<div class="quality-mini-alert danger">${esc(suppressed.error)}</div>` : ''}
        <ul class="quality-list">${flagList}</ul>
      </article>
    </div>
  `;
}

async function downloadMissingImagesFromQuality() {
  const images = dataQualitySummary.missing_images || {};
  const limit = Math.max(1, Math.min(5000, Number(images.missing_image_refs || 500)));
  await withAdminToast('Đang tạo job tải ảnh thiếu', async () => {
    const data = await fetchJSON('/admin/api/data-quality/download-missing-images', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ limit }),
    });
    activeCrawlJobId = data.job.id;
    switchPanel('crawl');
    renderCrawlJob(data.job);
    startCrawlPolling(activeCrawlJobId);
  }, 'Đã tạo job tải ảnh thiếu', 'Không tạo được job tải ảnh thiếu');
}

async function retryDataQualitySourceCrawl(source) {
  const cleanSource = String(source || '').trim().toLowerCase().replace(/[^a-z0-9_-]/g, '');
  if (!['facebook', 'guland'].includes(cleanSource)) return;
  const label = SOURCE_NAMES[cleanSource] || cleanSource;
  if (!confirm(`Crawl lại nguồn ${label}?`)) return;
  await withAdminToast(`Đang tạo job crawl lại ${label}`, async () => {
    const data = await fetchJSON('/admin/api/data-quality/retry-source-crawl', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source: cleanSource }),
    });
    activeCrawlJobId = data.job.id;
    switchPanel('crawl');
    renderCrawlJob(data.job);
    startCrawlPolling(activeCrawlJobId);
  }, `Đã tạo job crawl lại ${label}`, `Không tạo được job crawl lại ${label}`);
}

function renderCrawlProfiles() {
  const body = document.getElementById('crawlProfileRows');
  if (!body) return;
  if (!crawlProfiles.length) {
    body.innerHTML = `<tr><td colspan="9"><div class="empty">Chưa có môi giới Facebook.</div></td></tr>`;
    return;
  }
  body.innerHTML = crawlProfiles.map(p => `
    <tr data-url="${esc(p.url)}">
      <td data-label="Bật">
        <label class="crawl-switch">
          <input type="checkbox" data-crawl-field="active" ${p.active !== false ? 'checked' : ''}>
          <span></span>
        </label>
      </td>
      <td data-label="Môi giới">
        <div class="crawl-broker-cell">
          <input class="crawl-inline-input crawl-broker-name" data-crawl-field="broker_name" value="${esc(p.broker_name || '')}" placeholder="Tên môi giới">
          <input class="crawl-inline-input crawl-url" value="${esc(p.url)}" readonly>
          <input class="crawl-inline-input crawl-city" data-crawl-field="city" value="${esc(p.city || '')}" placeholder="Khu vực">
        </div>
      </td>
      <td data-label="Daily"><input class="crawl-small-input" type="number" min="1" max="500" data-crawl-field="daily_limit" value="${Number(p.daily_limit || p.tier || 20)}"></td>
      <td data-label="Range"><input class="crawl-small-input" type="number" min="1" max="60" data-crawl-field="range_days" value="${Number(p.range_days || 7)}"> <small>ngày</small></td>
      <td data-label="Nhịp đăng">${crawlActivityHtml(p.activity || {})}</td>
      <td data-label="Gợi ý">${crawlRecommendationHtml(p)}</td>
      <td data-label="Độ sạch">${crawlQualityHtml(p.data_quality || {})}</td>
      <td data-label="Dữ liệu">
        <div class="crawl-data-meta">
          <strong>${Number(p.raw_count || 0)}</strong>
          <small>${esc(shortDate(p.latest_crawled_at))}</small>
        </div>
      </td>
      <td data-label="Chạy" class="crawl-row-actions">
        <div class="crawl-action-grid">
          <button class="icon-btn primary-lite" title="Crawl lần đầu" onclick="runCrawlForUrl('${esc(p.url)}', 'first')">Lần 1</button>
          <button class="icon-btn" title="Crawl daily" onclick="runCrawlForUrl('${esc(p.url)}', 'daily')">Daily</button>
          <button class="icon-btn" title="Crawl theo range days" onclick="runCrawlForUrl('${esc(p.url)}', 'range')">Range</button>
          <button class="icon-btn danger" title="Xóa môi giới" onclick="removeCrawlProfile('${esc(p.url)}')">Xóa</button>
        </div>
      </td>
    </tr>
  `).join('');
}

function crawlActivityHtml(activity) {
  const tier = activity.cadence_tier || 'muted';
  const label = activity.cadence_label || 'Chưa có dữ liệu';
  return `
    <div class="broker-insight">
      <span class="broker-pill ${esc(tier)}">${esc(label)}</span>
      <strong>${Number(activity.avg_posts_per_active_day_14d || 0).toFixed(1)} bài/ngày active</strong>
      <small>${Number(activity.posts_30d || 0)} bài / 30 ngày · ${Number(activity.active_days_30d || 0)} ngày có đăng</small>
    </div>
  `;
}

function crawlRecommendationHtml(profile) {
  const activity = profile.activity || {};
  const daily = Number(activity.recommended_daily_limit || profile.daily_limit || profile.tier || 30);
  const weekly = Number(activity.recommended_weekly_limit || daily * 7);
  return `
    <div class="broker-rec">
      <strong>${daily}/ngày</strong>
      <small>${weekly}/tuần</small>
      <button class="broker-apply-btn" type="button" onclick="applyCrawlRecommendedDailyLimit('${esc(profile.url)}', ${daily})">Áp dụng</button>
    </div>
  `;
}

function crawlQualityHtml(quality) {
  const tier = quality.tier || 'muted';
  const score = quality.score === null || quality.score === undefined ? '--' : Number(quality.score);
  const reasons = Array.isArray(quality.reasons) ? quality.reasons.slice(0, 2).join(', ') : '';
  return `
    <div class="broker-quality">
      <span class="broker-score ${esc(tier)}">${score}</span>
      <div>
        <strong>${esc(quality.label || 'Chưa đủ mẫu')}</strong>
        <small>${Number(quality.sample_size || 0)} mẫu · giá ${Number(quality.price_pct || 0)}% · DT ${Number(quality.area_pct || 0)}%</small>
        <em>${esc(reasons)}</em>
      </div>
    </div>
  `;
}

function applyCrawlRecommendedDailyLimit(url, daily) {
  readCrawlTableState();
  const profile = crawlProfiles.find(p => p.url === url);
  if (!profile) return;
  profile.daily_limit = daily;
  profile.tier = daily;
  const row = Array.from(document.querySelectorAll('#crawlProfileRows tr[data-url]')).find(item => item.dataset.url === url);
  const input = row?.querySelector('[data-crawl-field="daily_limit"]');
  if (input) input.value = daily;
  syncCrawlRunInputs();
  showAdminToast('Đã áp dụng quota gợi ý cho môi giới', 'success');
}

function renderCrawlRunSelect() {
  const sel = document.getElementById('crawlRunProfile');
  if (!sel) return;
  const selected = sel.value;
  sel.innerHTML = crawlProfiles.map(p => `<option value="${esc(p.url)}">${esc(crawlProfileLabel(p))}</option>`).join('');
  if (selected && crawlProfiles.some(p => p.url === selected)) sel.value = selected;
  syncCrawlRunInputs();
}

function syncCrawlRunInputs() {
  const url = document.getElementById('crawlRunProfile')?.value;
  const p = crawlProfiles.find(x => x.url === url) || {};
  const limit = document.getElementById('crawlRunLimit');
  const days = document.getElementById('crawlRunDays');
  if (limit) limit.value = crawlMode === 'first' ? 330 : Number(p.daily_limit || p.tier || 30);
  if (days) days.value = Number(p.range_days || 7);
  updateCrawlModeFields();
}

function updateCrawlModeFields() {
  const fields = document.getElementById('crawlRunFields');
  const daysField = document.querySelector('.crawl-days-field');
  const showDays = crawlMode === 'range';
  if (fields) fields.classList.toggle('days-hidden', !showDays);
  if (daysField) daysField.hidden = !showDays;
}

function addCrawlProfile() {
  const broker = document.getElementById('crawlBrokerName').value.trim();
  const url = document.getElementById('crawlProfileUrl').value.trim();
  const city = document.getElementById('crawlCity').value.trim() || 'Bình Dương';
  if (!url.startsWith('https://www.facebook.com/')) return alert('URL Facebook chưa hợp lệ.');
  if (crawlProfiles.some(p => p.url === url)) return alert('Môi giới này đã có trong danh sách.');
  crawlProfiles.push({ broker_name: broker, url, city, active: true, daily_limit: 30, tier: 30, range_days: 7 });
  document.getElementById('crawlBrokerName').value = '';
  document.getElementById('crawlProfileUrl').value = '';
  renderCrawlProfiles();
  renderCrawlRunSelect();
  showAdminToast('Đã thêm môi giới vào danh sách tạm', 'success');
}

function removeCrawlProfile(url) {
  if (!confirm('Xóa môi giới này khỏi danh sách crawl?')) return;
  crawlProfiles = crawlProfiles.filter(p => p.url !== url);
  renderCrawlProfiles();
  renderCrawlRunSelect();
  showAdminToast('Đã xóa môi giới khỏi danh sách tạm', 'success');
}

async function saveCrawlProfiles() {
  await withAdminToast('Đang lưu danh sách môi giới', async () => {
    readCrawlTableState();
    const data = await fetchJSON('/admin/api/facebook-crawl/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ profiles: crawlProfiles }),
    });
    crawlProfiles = data.profiles || [];
    crawlSummary = data.summary || {};
    renderCrawlStats(crawlSummary);
    renderCrawlOps(crawlSummary.ops || {});
    renderCrawlProfiles();
    renderCrawlRunSelect();
  }, 'Đã lưu danh sách môi giới', 'Không lưu được danh sách');
}

function setCrawlMode(mode) {
  crawlMode = mode;
  document.querySelectorAll('[data-crawl-mode]').forEach(btn => btn.classList.toggle('active', btn.dataset.crawlMode === mode));
  syncCrawlRunInputs();
}

async function runCrawlForUrl(url, mode = crawlMode) {
  await withAdminToast('Đang tạo job crawl', async () => {
    readCrawlTableState();
    const p = crawlProfiles.find(x => x.url === url) || {};
    const payload = {
      url,
      mode,
      broker_name: p.broker_name || '',
      city: p.city || '',
      limit: Number(document.getElementById('crawlRunLimit')?.value || (mode === 'first' ? 330 : p.daily_limit || 30)),
      days: Number(document.getElementById('crawlRunDays')?.value || p.range_days || 7),
      download_images: !!document.getElementById('crawlDownloadImages')?.checked,
    };
    const data = await fetchJSON('/admin/api/facebook-crawl/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    activeCrawlJobId = data.job.id;
    renderCrawlJob(data.job);
    startCrawlPolling(activeCrawlJobId);
  }, 'Đã tạo job crawl, đang theo dõi tiến trình', 'Không tạo được job crawl');
}

async function runSelectedCrawl() {
  const url = document.getElementById('crawlRunProfile')?.value;
  if (!url) return alert('Chọn môi giới cần crawl.');
  await runCrawlForUrl(url, crawlMode);
}

async function runCrawlMaintenance(action) {
  const label = action === 'valuation_only' ? 'valuation-only' : 'reprocess';
  await withAdminToast(`Đang tạo job ${label}`, async () => {
    const data = await fetchJSON('/admin/api/facebook-crawl/maintenance', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action }),
    });
    activeCrawlJobId = data.job.id;
    renderCrawlJob(data.job);
    startCrawlPolling(activeCrawlJobId);
  }, `Đã tạo job ${label}`, `Không tạo được job ${label}`);
}

function renderCrawlJob(job) {
  const status = document.getElementById('crawlJobStatus');
  const meta = document.getElementById('crawlJobMeta');
  const log = document.getElementById('crawlJobLog');
  const pct = Math.max(0, Math.min(100, Number(job.progress_pct || 0)));
  const progressLabel = job.progress_label || job.stage || 'Đang chờ';
  const progressPct = document.getElementById('crawlProgressPct');
  const progressFill = document.getElementById('crawlProgressFill');
  const progressText = document.getElementById('crawlProgressLabel');
  if (status) {
    status.textContent = `${job.status || 'idle'} · ${job.stage || '-'}`;
    status.dataset.status = job.status || '';
  }
  if (progressPct) progressPct.textContent = `${pct.toFixed(0)}%`;
  if (progressFill) progressFill.style.width = `${pct}%`;
  if (progressText) progressText.textContent = progressLabel;
  const crawl = job.stats?.crawl || {};
  const reprocess = job.stats?.reprocess?.listings || {};
  const valuation = job.stats?.valuation || job.stats?.reprocess?.valuation || {};
  const downloaded = job.stats?.downloaded_images;
  if (meta && job.maintenance_action) {
    meta.innerHTML = `
      <strong>${esc(job.mode || 'maintenance')}</strong>
      ${job.stats?.reprocess ? `<span>Reprocess new ${Number(reprocess.new || 0)} · updated ${Number(reprocess.updated || 0)} · skipped ${Number(reprocess.skipped || 0)}</span>` : ''}
      ${valuation.total !== undefined ? `<span>Valuation total ${Number(valuation.total || 0)} · signals ${Number(valuation.signals || 0)} · outliers ${Number(valuation.outliers || 0)}</span>` : ''}
      ${job.error ? `<span class="crawl-error">${esc(job.error)}</span>` : ''}
    `;
  }
  if (meta && !job.maintenance_action) {
    meta.innerHTML = `
      <strong>${esc(job.broker_name || job.profile_url || '')}</strong>
      <span>${esc(job.mode || '')} · limit ${esc(job.limit || '')}${job.mode === 'range' ? ' · ' + esc(job.days || '') + ' ngày' : ''}</span>
      <span>Fetched ${Number(crawl.fetched || 0)} · Imported ${Number(crawl.inserted || 0)} · Refreshed ${Number(crawl.refreshed_images || 0)} · Skipped ${Number(crawl.skipped || 0)}</span>
      <span>Irrelevant ${Number(crawl.irrelevant || 0)} · Out area ${Number(crawl.out_of_area || 0)} · Range filter ${Number(crawl.range_filtered || 0)}${downloaded !== undefined ? ' · Ảnh ' + Number(downloaded || 0) : ''}</span>
      ${job.stats?.reprocess ? `<span>Reprocess new ${Number(reprocess.new || 0)} · updated ${Number(reprocess.updated || 0)} · skipped ${Number(reprocess.skipped || 0)}</span>` : ''}
      ${job.error ? `<span class="crawl-error">${esc(job.error)}</span>` : ''}
    `;
  }
  if (log) log.textContent = (job.logs || []).join('\n') || 'Job đang chờ bắt đầu.';
}

function startCrawlPolling(jobId) {
  clearInterval(crawlPollTimer);
  crawlPollTimer = setInterval(async () => {
    try {
      const data = await fetchJSON(`/admin/api/facebook-crawl/jobs/${jobId}`);
      renderCrawlJob(data.job);
      if (['succeeded', 'failed'].includes(data.job.status)) {
        clearInterval(crawlPollTimer);
        loadCrawlConfig();
      }
    } catch (e) {
      clearInterval(crawlPollTimer);
    }
  }, 2500);
}

// User management (RBAC)
// â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
let userTimer = null;

function userQuery() {
  const q = new URLSearchParams();
  const text = document.getElementById('userSearch').value.trim();
  const tier = document.getElementById('userTierFilter').value;
  if (text) q.set('q', text);
  if (tier) q.set('tier', tier);
  return q.toString();
}

async function loadUsers() {
  const data = await fetchJSON(`/admin/api/users?${userQuery()}`);
  renderUserStats(data.summary || {});
  renderUserRows(data.items || []);
}

function renderUserStats(s) {
  const items = [
    ['Total Users', s.total || 0, 'tất cả'],
    ['VIP', s.vip || 0, 'đang trả phí'],
    ['Free', s.free || 0, 'miễn phí'],
    ['Admin', s.admin || 0, 'nội bộ'],
    ['Banned', s.banned || 0, 'đã chặn'],
  ];
  document.getElementById('userStats').innerHTML = items.map((s, idx) => `
    <div class="stat-card">
      <small>${esc(s[0])}</small>
      <div><strong style="color:${idx === 1 ? 'var(--green)' : idx === 4 ? 'var(--red)' : 'var(--ink)'}">${s[1]}</strong><span>${esc(s[2])}</span></div>
    </div>
  `).join('');
}

function renderUserRows(items) {
  const body = document.getElementById('userTableBody');
  if (!items.length) {
    body.innerHTML = `<tr><td colspan="10"><div class="empty">Không có user phù hợp.</div></td></tr>`;
    return;
  }
  body.innerHTML = items.map(u => {
    const tierBadgeColor = u.effective_tier === 'vip' ? 'var(--green)' : u.effective_tier === 'admin' ? 'var(--orange)' : 'var(--ink-muted)';
    const banned = u.is_banned ? `<span style="color:var(--red)">BANNED</span>` : '';
    const vipExp = u.vip_expires_at ? shortDate(u.vip_expires_at) : '-';
    const expired = u.tier === 'vip' && u.effective_tier !== 'vip' ? ' <small style="color:var(--red)">(hết hạn)</small>' : '';
    const tg = u.telegram_linked ? 'âœ“' : '-';
    return `
      <tr>
        <td data-label="ID">#${u.id}</td>
        <td data-label="Tài khoản"><strong>${esc(u.identifier || '-')}</strong><br><small>${esc(u.identifier_type || '')}</small></td>
        <td data-label="Tên">${esc(u.display_name || '-')}</td>
        <td data-label="Tier"><strong style="color:${tierBadgeColor}">${esc((u.effective_tier || u.tier || '').toUpperCase())}</strong>${expired} ${banned}</td>
        <td data-label="VIP hết hạn">${vipExp}</td>
        <td data-label="Telegram">${tg}</td>
        <td data-label="Watchlist">${Number(u.watchlist_count || 0)}</td>
        <td data-label="Đăng ký">${shortDate(u.created_at)}</td>
        <td data-label="Last login">${shortDate(u.last_login_at)}</td>
        <td data-label="Hành động">
          <button class="icon-btn" onclick="grantVip(${u.id}, 30)">+30d VIP</button>
          <button class="icon-btn" onclick="grantVip(${u.id}, 7)">+7d</button>
          <button class="icon-btn" onclick="revokeVip(${u.id})">Revoke</button>
          <button class="icon-btn" onclick="toggleBan(${u.id}, ${u.is_banned ? 0 : 1})">${u.is_banned ? 'Unban' : 'Ban'}</button>
          <button class="icon-btn danger" onclick="deleteUser(${u.id})">Xóa</button>
        </td>
      </tr>
    `;
  }).join('');
}

async function grantVip(userId, days) {
  const customDays = prompt(`Cấp VIP bao nhiêu ngày? (default ${days})`, String(days));
  if (customDays === null) return;
  const n = parseInt(customDays, 10);
  if (!n || n <= 0) return alert('Số ngày không hợp lệ');
  try {
    await fetchJSON(`/admin/api/users/${userId}/grant-vip`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ days: n }),
    });
    loadUsers();
  } catch (e) { alert('Lỗi: ' + (e.message || e)); }
}

async function revokeVip(userId) {
  if (!confirm(`Thu hồi VIP của user #${userId}?`)) return;
  try {
    await fetchJSON(`/admin/api/users/${userId}/revoke`, { method: 'POST' });
    loadUsers();
  } catch (e) { alert('Lỗi: ' + (e.message || e)); }
}

async function toggleBan(userId, banned) {
  const verb = banned ? 'Ban' : 'Unban';
  if (!confirm(`${verb} user #${userId}?`)) return;
  try {
    await fetchJSON(`/admin/api/users/${userId}/ban`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ banned: !!banned }),
    });
    loadUsers();
  } catch (e) { alert('Lỗi: ' + (e.message || e)); }
}

async function deleteUser(userId) {
  if (!confirm(`Xóa user #${userId}? Session, watchlist và log thông báo sẽ bị xóa; lead cũ chỉ bỏ liên kết user.`)) return;
  await withAdminToast(
    'Đang xóa người dùng',
    async () => {
      await fetchJSON(`/admin/api/users/${userId}`, { method: 'DELETE', silent: true });
      await loadUsers();
    },
    'Đã xóa người dùng',
    'Không xóa được người dùng'
  );
}

function leadQuery() {
  const q = new URLSearchParams();
  const text = document.getElementById('leadSearch').value.trim();
  const status = document.getElementById('leadStatusFilter').value;
  if (text) q.set('q', text);
  if (status) q.set('status', status);
  return q.toString();
}

async function loadLeads() {
  const data = await fetchJSON(`/admin/api/leads?${leadQuery()}`);
  renderLeadStats(data.summary || {});
  renderLeadRows(data.items || []);
}

function renderLeadStats(summary) {
  const stats = [
    ['Total Leads', summary.total || 0, 'tất cả'],
    ['Won Deals', summary.deposit || 0, 'đã chốt cọc'],
    ['Pending', summary.new || 0, 'cần xử lý'],
    ['Đi xem đất', summary.viewing || 0, 'đang hẹn'],
    ['Hủy', summary.cancelled || 0, 'đã hủy']
  ];
  document.getElementById('leadStats').innerHTML = stats.map((s, idx) => `
    <div class="stat-card">
      <small>${esc(s[0])}</small>
      <div><strong style="color:${idx === 1 ? 'var(--green)' : idx === 2 ? 'var(--orange)' : idx === 4 ? 'var(--red)' : 'var(--ink)'}">${s[1]}</strong><span>${esc(s[2])}</span></div>
    </div>
  `).join('');
}

function renderLeadRows(items) {
  document.getElementById('leadCountMeta').textContent = `Hiển thị ${items.length} lead`;
  const body = document.getElementById('leadRows');
  if (!items.length) {
    body.innerHTML = `<tr><td colspan="5"><div class="empty">Chưa có lead phù hợp.</div></td></tr>`;
    return;
  }
  body.innerHTML = items.map(x => {
    const st = STATUS[x.status] || STATUS.new;
    const listingLabel = x.listing_title ? `#${x.listing_id} · ${x.listing_title}` : (x.listing_id ? `Deal #${x.listing_id}` : (x.listing_url || '-'));
    const link = x.listing_id ? `/listing/${x.listing_id}` : (x.listing_url || '#');
    return `
      <tr>
        <td data-label="Ngày nhận">${shortDate(x.created_at)}</td>
        <td data-label="Số Zalo" class="phone">${esc(x.zalo_phone || '-')}</td>
        <td data-label="Lô đất"><a class="deal-pill" href="${esc(link)}" target="_blank">${esc(listingLabel)}</a></td>
        <td data-label="Trạng thái">
          <select class="status-select ${st.cls}" data-lead="${x.id}">
            ${STATUS_KEYS.map(k => `<option value="${k}" ${x.status === k ? 'selected' : ''}>${STATUS[k].label}</option>`).join('')}
          </select>
        </td>
        <td data-label="Thao tác">
          <button class="icon-btn" onclick="window.open('${esc(link)}','_blank')">Mở</button>
          <button class="icon-btn danger" onclick="deleteLead(${x.id})">Xóa</button>
        </td>
      </tr>
    `;
  }).join('');
  body.querySelectorAll('.status-select').forEach(sel => {
    sel.addEventListener('change', async () => {
      await fetchJSON(`/admin/api/leads/${sel.dataset.lead}/status`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: sel.value })
      });
      loadLeads();
    });
  });
}

async function deleteLead(leadId) {
  if (!confirm(`Xóa lead #${leadId} khỏi CRM?`)) return;
  await withAdminToast(
    'Đang xóa lead',
    async () => {
      await fetchJSON(`/admin/api/leads/${leadId}`, { method: 'DELETE', silent: true });
      await loadLeads();
    },
    'Đã xóa lead',
    'Không xóa được lead'
  );
}

function exportLeads() {
  const q = leadQuery();
  const clean = new URL(`/admin/api/leads/export.csv${q ? '?' + q : ''}`, window.location.href);
  clean.username = '';
  clean.password = '';
  showAdminToast('Đang tải file CSV leads', 'success', { delay: 1800 });
  window.location.href = clean.toString();
}

function switchQualityTab(name) {
  activeQualityTab = name;
  document.querySelectorAll('.segment[data-quality-tab]').forEach(btn => btn.classList.toggle('active', btn.dataset.qualityTab === name));
  document.querySelectorAll('.quality-tab').forEach(tab => tab.classList.toggle('active', tab.id === `quality-${name}`));
  if (name === 'dups') loadDuplicates();
  else if (name === 'blacklist') loadBlacklist();
  else loadDataQualityQueue(name);
}

function qualityQueueRoot(queue) {
  return {
    source_qc: 'qualitySourceQcGrid',
    legal_qc: 'qualityLegalQcGrid'
  }[queue] || '';
}

async function loadDataQualityQueue(queue) {
  const rootId = qualityQueueRoot(queue);
  const root = rootId ? document.getElementById(rootId) : null;
  if (!root) return;
  root.innerHTML = `<div class="empty">Đang tải queue kiểm dịch...</div>`;
  const p = new URLSearchParams({ queue, limit: '60', sort: 'default' });
  const data = await fetchJSON('/admin/api/data-quality/items?' + p.toString());
  const items = data.items || [];
  if (!items.length) {
    root.innerHTML = `<div class="empty">Không có mục nào trong queue này.</div>`;
    return;
  }
  items.forEach(it => { _trnGal[it.id] = (it.images && it.images.length) ? it.images : []; });
  root.innerHTML = items.map(x => dataQualityReviewCard(x, queue)).join('');
  requestAnimationFrame(() => _trnSyncDescriptionToggles(root));
}

function infraFilters() {
  if (!activeInfraFilter || activeInfraFilter === 'all') return '';
  const q = new URLSearchParams();
  q.set('kind', activeInfraFilter);
  return q.toString();
}

function resetInfraForm() {
  document.getElementById('infraId').value = '';
  document.getElementById('infraKind').value = 'timeline';
  document.getElementById('infraTitle').value = '';
  document.getElementById('infraSubtitle').value = '';
  document.getElementById('infraSummary').value = '';
  document.getElementById('infraWard').value = '';
  document.getElementById('infraRoadRef').value = '';
  document.getElementById('infraProjectCode').value = '';
  document.getElementById('infraMilestone').value = '';
  document.getElementById('infraStatus').value = '';
  document.getElementById('infraSeverity').value = '';
  document.getElementById('infraProgress').value = '';
  document.getElementById('infraDate').value = '';
  document.getElementById('infraSortOrder').value = '0';
  document.getElementById('infraSourceUrl').value = '';
}

function renderInfraRows(items) {
  const root = document.getElementById('infraRows');
  if (!items.length) {
    root.innerHTML = `<div class="empty">Chưa có item hạ tầng nào.</div>`;
    return;
  }
  root.innerHTML = items.map((x) => `
    <article class="infra-item" data-id="${x.id}">
      <div class="infra-item-top">
        <div>
          <span class="infra-kind">${esc(x.kind)}</span>
          <h4>${esc(x.title)}</h4>
        </div>
        <small>${esc(x.relative_time || '')}</small>
      </div>
      <p>${esc(x.summary || x.subtitle || '')}</p>
      <div class="infra-meta">
        ${x.ward ? `<span>${esc(x.ward)}</span>` : ''}
        ${x.road_ref ? `<span>${esc(x.road_ref)}</span>` : ''}
        ${x.milestone_label ? `<span>${esc(x.milestone_label)}</span>` : ''}
        ${x.progress_pct !== null && x.progress_pct !== undefined ? `<span>${Number(x.progress_pct).toFixed(0)}%</span>` : ''}
        ${x.status_tag ? `<span>${esc(x.status_tag)}</span>` : ''}
        ${x.severity ? `<span>${esc(x.severity)}</span>` : ''}
      </div>
      <div class="infra-item-actions">
        <button class="secondary-btn" onclick="editInfra(${x.id})">Sửa</button>
        <button class="secondary-btn" onclick="deactivateInfra(${x.id})">Ẩn</button>
      </div>
    </article>
  `).join('');
}

async function loadInfraItems() {
  const query = infraFilters();
  const data = await fetchJSON(`/admin/api/infra${query ? '?' + query : ''}`);
  renderInfraRows(data.items || []);
}

function switchInfraFilter(name) {
  activeInfraFilter = name;
  document.querySelectorAll('.segment[data-infra-filter]').forEach((btn) => {
    btn.classList.toggle('active', btn.dataset.infraFilter === name);
  });
  loadInfraItems();
}

function collectInfraPayload() {
  return {
    id: Number(document.getElementById('infraId').value || 0),
    kind: document.getElementById('infraKind').value,
    title: document.getElementById('infraTitle').value.trim(),
    subtitle: document.getElementById('infraSubtitle').value.trim(),
    summary: document.getElementById('infraSummary').value.trim(),
    ward: document.getElementById('infraWard').value.trim(),
    road_ref: document.getElementById('infraRoadRef').value.trim(),
    project_code: document.getElementById('infraProjectCode').value.trim(),
    milestone_label: document.getElementById('infraMilestone').value.trim(),
    status_tag: document.getElementById('infraStatus').value,
    severity: document.getElementById('infraSeverity').value,
    progress_pct: document.getElementById('infraProgress').value.trim(),
    event_date: document.getElementById('infraDate').value.trim(),
    sort_order: document.getElementById('infraSortOrder').value.trim() || '0',
    source_url: document.getElementById('infraSourceUrl').value.trim()
  };
}

async function saveInfra() {
  const payload = collectInfraPayload();
  if (!payload.title) {
    window.alert('Cần nhập tiêu đề.');
    return;
  }
  await fetchJSON('/admin/api/infra', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
  resetInfraForm();
  await loadInfraItems();
}

async function editInfra(id) {
  const data = await fetchJSON('/admin/api/infra?active=0');
  const item = (data.items || []).find((x) => Number(x.id) === Number(id));
  if (!item) return;
  document.getElementById('infraId').value = item.id;
  document.getElementById('infraKind').value = item.kind || 'timeline';
  document.getElementById('infraTitle').value = item.title || '';
  document.getElementById('infraSubtitle').value = item.subtitle || '';
  document.getElementById('infraSummary').value = item.summary || '';
  document.getElementById('infraWard').value = item.ward || '';
  document.getElementById('infraRoadRef').value = item.road_ref || '';
  document.getElementById('infraProjectCode').value = item.project_code || '';
  document.getElementById('infraMilestone').value = item.milestone_label || '';
  document.getElementById('infraStatus').value = item.status_tag || '';
  document.getElementById('infraSeverity').value = item.severity || '';
  document.getElementById('infraProgress').value = item.progress_pct ?? '';
  document.getElementById('infraDate').value = (item.event_date || '').slice(0, 10);
  document.getElementById('infraSortOrder').value = item.sort_order ?? 0;
  document.getElementById('infraSourceUrl').value = item.source_url || '';
  document.getElementById('infraTitle').focus();
}

async function deactivateInfra(id) {
  await fetchJSON(`/admin/api/infra/${id}`, { method: 'DELETE' });
  await loadInfraItems();
}

async function loadDuplicates() {
  const data = await fetchJSON('/admin/api/qc/duplicates');
  const items = data.items || [];
  document.getElementById('dupCount').textContent = items.length;
  const root = document.getElementById('duplicateCards');
  if (!items.length) {
    root.innerHTML = `<div class="empty">Không còn cặp tin nghi trùng cần xử lý.</div>`;
    return;
  }
  root.innerHTML = items.map(x => duplicateCard(x)).join('');
}

function dupSideData(x, side) {
  const isCanon = side === 'canonical';
  return {
    id: isCanon ? x.duplicate_of_id : x.id,
    source: isCanon ? x.canonical_source : x.source,
    sourceId: isCanon ? x.canonical_source_id : x.source_id,
    price: isCanon ? x.canonical_price_ty : x.price_ty,
    area: isCanon ? x.canonical_area_m2 : x.area_m2,
    frontage: isCanon ? x.canonical_frontage_m : x.frontage_m,
    depth: isCanon ? x.canonical_depth_m : x.depth_m,
    desc: isCanon ? x.canonical_description_excerpt : x.description_excerpt,
    img: isCanon ? x.canonical_image : x.image,
    dt: isCanon ? x.canonical_dt : x.dt,
    detail: isCanon ? x.canonical_detail_url : x.detail_url,
    originalUrl: isCanon ? x.canonical_url : x.url,
    title: isCanon ? x.canonical_title : x.title,
    ward: isCanon ? x.canonical_ward : x.ward,
    prop: isCanon ? x.canonical_property_type : x.property_type,
    road: isCanon ? x.canonical_road_name : x.road_name
  };
}

function dupConfidence(x) {
  const priceA = Number(x.price_ty || 0);
  const priceB = Number(x.canonical_price_ty || 0);
  const areaA = Number(x.area_m2 || 0);
  const areaB = Number(x.canonical_area_m2 || 0);
  let score = 82;
  if (priceA && priceB) score += Math.max(-16, 10 - Math.abs(priceA - priceB) / Math.max(priceA, priceB) * 90);
  if (areaA && areaB) score += Math.max(-10, 10 - Math.abs(areaA - areaB) / Math.max(areaA, areaB) * 120);
  if ((x.ward || '') && x.ward === x.canonical_ward) score += 4;
  if ((x.property_type || '') && x.property_type === x.canonical_property_type) score += 4;
  return Math.min(98, Math.max(58, Math.round(score)));
}

function dupMoneyPerM2(priceTy, areaM2) {
  const price = Number(priceTy || 0);
  const areaVal = Number(areaM2 || 0);
  if (!price || !areaVal) return '-';
  return `${(price * 1000 / areaVal).toLocaleString('vi-VN', { maximumFractionDigits: 1 })} tr/m²`;
}

function dupLotSize(d) {
  const frontage = Number(d.frontage || 0);
  const depth = Number(d.depth || 0);
  if (frontage && depth) {
    return `${frontage.toLocaleString('vi-VN', { maximumFractionDigits: 1 })}x${depth.toLocaleString('vi-VN', { maximumFractionDigits: 1 })} (${area(d.area)})`;
  }
  return area(d.area);
}

function dupFact(label, value, tone = '') {
  if (value === undefined || value === null || value === '' || value === '-') return '';
  return `<span class="dup-fact ${tone}"><small>${esc(label)}</small>${esc(String(value))}</span>`;
}

function dupSourceLinks(d) {
  const original = d.originalUrl
    ? `<a class="dup-open-source" href="${esc(d.originalUrl)}" target="_blank" rel="noopener">Mở tin gốc</a>`
    : '';
  return `
    <div class="dup-source-links">
      <a href="${esc(d.detail)}" target="_blank" rel="noopener">AD-${esc(d.id)}</a>
      ${original}
    </div>
  `;
}

function dupListingPanel(x, side) {
  const d = dupSideData(x, side);
  const isCanon = side === 'canonical';
  const role = isCanon ? 'Tin gốc để so sánh' : 'Tin nghi trùng';
  const roleHint = isCanon ? 'Nếu gộp, hệ thống giữ tin này làm deal chính.' : 'Tin này sẽ được ẩn nếu admin xác nhận gộp.';
  const sourceName = SOURCE_NAMES[d.source] || d.source || '-';
  return `
    <section class="dup-ad-panel ${isCanon ? 'canonical' : 'candidate'}">
      <div class="dup-ad-role">
        <div>
          <span>${role}</span>
          <small>${roleHint}</small>
        </div>
        ${dupSourceLinks(d)}
      </div>
      <div class="dup-ad-body">
        <img class="ad-img" src="${esc(d.img || PLACEHOLDER)}" onerror="this.onerror=null;this.src='${PLACEHOLDER}'" loading="lazy" referrerpolicy="no-referrer" alt="">
        <div class="dup-ad-content">
          <a class="ad-title" href="${esc(d.detail)}" target="_blank" rel="noopener">${esc(d.title || 'Không có tiêu đề')}</a>
          <div class="dup-facts">
            ${dupFact('Giá', money(d.price), 'price')}
            ${dupFact('Đơn giá', dupMoneyPerM2(d.price, d.area))}
            ${dupFact('DT', dupLotSize(d))}
            ${dupFact('Khu vực', d.ward)}
            ${dupFact('Đường', d.road)}
            ${dupFact('Loại', PTYPES[d.prop] || d.prop)}
            ${dupFact('Nguồn', sourceName)}
            ${dupFact('Mã nguồn', d.sourceId)}
            ${dupFact('Ngày', shortDate(d.dt))}
          </div>
          <div class="ad-desc">${esc(d.desc || '-')}</div>
        </div>
      </div>
    </section>
  `;
}

function dupCompareRows(x) {
  const leftData = dupSideData(x, 'listing');
  const rightData = dupSideData(x, 'canonical');
  const priceA = Number(x.price_ty || 0);
  const priceB = Number(x.canonical_price_ty || 0);
  const areaA = Number(x.area_m2 || 0);
  const areaB = Number(x.canonical_area_m2 || 0);
  const priceNote = (!priceA || !priceB)
    ? 'Thiếu giá'
    : Math.abs(priceA - priceB) / Math.max(priceA, priceB) < 0.01
      ? 'Gần như bằng nhau'
      : `${priceA > priceB ? 'Tin nghi trùng cao hơn' : 'Tin gốc cao hơn'} ${(Math.abs(priceA - priceB) / Math.max(priceA, priceB) * 100).toFixed(1)}%`;
  const areaNote = (!areaA || !areaB)
    ? 'Thiếu diện tích'
    : `Lệch ${Math.abs(areaA - areaB).toLocaleString('vi-VN', { maximumFractionDigits: 1 })} m²`;
  const roadNote = (leftData.road && rightData.road)
    ? (leftData.road === rightData.road ? 'Cùng tên đường' : 'Khác tên đường')
    : 'Thiếu tên đường';
  const rows = [
    ['Giá rao', money(leftData.price), money(rightData.price), priceNote],
    ['Đơn giá', dupMoneyPerM2(leftData.price, leftData.area), dupMoneyPerM2(rightData.price, rightData.area), 'So theo tr/m²'],
    ['Diện tích', dupLotSize(leftData), dupLotSize(rightData), areaNote],
    ['Khu vực', leftData.ward || '-', rightData.ward || '-', leftData.ward === rightData.ward ? 'Cùng khu' : 'Cần soi vị trí'],
    ['Tên đường', leftData.road || '-', rightData.road || '-', roadNote],
    ['Loại hình', PTYPES[leftData.prop] || leftData.prop || '-', PTYPES[rightData.prop] || rightData.prop || '-', leftData.prop === rightData.prop ? 'Trùng loại' : 'Cần xem lại'],
    ['Ngày đăng', shortDate(leftData.dt), shortDate(rightData.dt), 'Tin gốc là mốc đề xuất giữ']
  ];
  return rows.map(([label, left, right, note]) => `
    <div class="dup-summary-row">
      <strong>${esc(label)}</strong>
      <span>${esc(left)}</span>
      <span>${esc(right)}</span>
      <em>${esc(note)}</em>
    </div>
  `).join('');
}

function duplicateCard(x) {
  const confidence = dupConfidence(x);
  const title = x.suspected_duplicate ? 'Tin nghi trùng cần admin review' : 'Tin trùng cần rà lại';
  const subtitle = x.suspected_duplicate
    ? 'Hệ thống thấy giống cùng lô nhưng chưa đủ chắc để tự gộp. Mở tin gốc, so nội dung và quyết định giữ/gộp.'
    : 'Cặp này đã được đánh dấu trùng nhưng có điểm chưa chắc, cần admin xác nhận trước khi khóa dữ liệu.';
  const reasons = (x.qc_reasons || []).length
    ? `<div class="dup-review-reasons"><b>Lý do vào hàng chờ</b>${x.qc_reasons.map(r => `<span>${esc(r)}</span>`).join('')}</div>`
    : '';
  return `
    <article class="dup-card">
      <div class="dup-head">
        <div>
          <div class="dup-kicker">${title} <span class="deal-pill">DUP-${x.id}</span></div>
          <p>${subtitle}</p>
        </div>
        <div class="dup-score">
          <span>Độ giống</span>
          <strong>${confidence}%</strong>
        </div>
      </div>
      ${reasons}
      <div class="dup-grid">
        ${dupListingPanel(x, 'listing')}
        ${dupListingPanel(x, 'canonical')}
      </div>
      <div class="dup-summary">
        <div class="dup-summary-title">
          <strong>So sánh nhanh</strong>
          <span>Ưu tiên xem giá, diện tích, tên đường và nội dung mô tả trước khi bấm gộp.</span>
        </div>
        <div class="dup-summary-grid">
          <div class="dup-summary-row header">
            <strong>Tiêu chí</strong>
            <span>Tin nghi trùng</span>
            <span>Tin gốc</span>
            <em>Kết luận</em>
          </div>
          ${dupCompareRows(x)}
        </div>
      </div>
      <div class="dup-actions">
        <button class="primary-btn merge-btn" onclick="mergeDup(${x.id}, ${x.duplicate_of_id})">
          <strong>Gộp vào tin gốc</strong>
          <span class="dup-decision-copy">Ẩn tin nghi trùng, giữ tin gốc làm deal chính</span>
        </button>
        <button class="secondary-btn split-btn" onclick="splitDup(${x.id}, ${x.duplicate_of_id})">
          <strong>Khác lô</strong>
          <span class="dup-decision-copy">Giữ cả hai tin và không hỏi lại cặp này</span>
        </button>
      </div>
    </article>
  `;
}

async function mergeDup(id, target) {
  await fetchJSON('/admin/api/qc/duplicates/merge', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ listing_id: id, target_listing_id: target, note: 'admin_control_room_merge' })
  });
  loadDuplicates();
}

async function splitDup(id, target) {
  const note = window.prompt('Lý do tách lô?', 'not_same_lot') || 'not_same_lot';
  await fetchJSON('/admin/api/qc/duplicates/split', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ listing_id: id, target_listing_id: target, note })
  });
  loadDuplicates();
}

async function loadBlacklist() {
  const data = await fetchJSON('/admin/api/blacklist');
  const items = data.items || [];
  document.getElementById('blacklistCount').textContent = items.filter(x => x.active).length;
  const root = document.getElementById('blacklistRows');
  if (!items.length) {
    root.innerHTML = `<div class="empty">Chưa có SĐT trong blacklist.</div>`;
    return;
  }
  root.innerHTML = items.map(x => `
    <div class="blacklist-row">
      <strong>${esc(x.phone_norm)}</strong>
      <span>${esc(x.reason || '-')}</span>
      <span style="color:${x.active ? 'var(--green)' : 'var(--muted)'}">${x.active ? 'active' : 'inactive'}</span>
      <button class="secondary-btn" ${x.active ? '' : 'disabled'} onclick="deactivateBlacklist('${esc(x.phone_norm)}')">Deactivate</button>
    </div>
  `).join('');
}

async function addBlacklist() {
  const phone = document.getElementById('blacklistPhone').value.trim();
  const reason = document.getElementById('blacklistReason').value.trim();
  if (!phone) return;
  await fetchJSON('/admin/api/blacklist', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ phone, reason })
  });
  document.getElementById('blacklistPhone').value = '';
  document.getElementById('blacklistReason').value = '';
  loadBlacklist();
}

async function deactivateBlacklist(phone) {
  await fetchJSON('/admin/api/blacklist', {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ phone })
  });
  loadBlacklist();
}

let _trnGal = {};
let _trnGalIds = [];
let _trnGalIdx = 0;
let _trnWardsLoaded = false;
let _trnWardCities = {};   // { city: [wards] }
let _trnAllWards = [];     // mọi phường có signal (kể cả ngoài CITY_MAP)
let _trnOffset = 0;
let _trnLoading = false;
let _trnHasMore = false;
let _trnChipDelegated = false;
const TRN_PAGE = 50;

function trnFilterQuery(offset = 0) {
  const city  = document.getElementById('trnCity')?.value || '';
  const ward  = document.getElementById('trnWard')?.value || '';
  const mos   = document.getElementById('trnMos')?.value || '0';
  const sort  = document.getElementById('trnSort')?.value || 'default';
  const p = new URLSearchParams({ limit: String(TRN_PAGE), sort, offset: String(offset) });
  if (city) p.set('city', city);
  if (ward) p.set('ward', ward);
  if (mos && mos !== '0') p.set('mos_min', mos);
  return p.toString();
}

function _trnPopulateWards(city) {
  const wardSel = document.getElementById('trnWard');
  if (!wardSel) return;
  const cur = wardSel.value;
  const list = city && _trnWardCities[city] ? _trnWardCities[city]
    : (_trnAllWards.length ? _trnAllWards : Object.values(_trnWardCities).flat().sort());
  wardSel.innerHTML = '<option value="">Tất cả phường</option>' +
    list.map(w => `<option value="${esc(w)}">${esc(w)}</option>`).join('');
  if (list.includes(cur)) wardSel.value = cur;
}

function _trnBindChipDelegation(root) {
  if (_trnChipDelegated) return;
  _trnChipDelegated = true;
  root.addEventListener('click', (ev) => {
    const chip = ev.target.closest('.chip');
    if (!chip || !root.contains(chip)) return;
    const group = chip.dataset.group;
    if (group !== 'reason') {
      root.querySelectorAll(`.chip[data-card="${chip.dataset.card}"][data-group="${group}"]`).forEach(c => c.classList.remove('active'));
    }
    chip.classList.toggle('active');
  });
}

async function loadTrainingItems(append = false) {
  if (_trnLoading) return;
  _trnLoading = true;
  try {
    if (!append) _trnOffset = 0;
    const data = await fetchJSON('/admin/api/ai-training/items?' + trnFilterQuery(_trnOffset));
    const root = document.getElementById('trainingGrid');
    const items = data.items || [];

    // Badge: luôn "chưa review / tổng signal"
    const badge = document.getElementById('trainingCount');
    if (badge) badge.textContent = `${data.pending || 0}/${data.total || 0}`;
    const meta = document.getElementById('trainingMeta');
    const shown = append ? (_trnOffset + items.length) : items.length;
    const queueLabel = data.queue_label || 'Review mới';
    if (meta) meta.textContent = `· ${queueLabel} · ${data.pending || 0} mục / ${data.total || 0} signal · hiển thị ${shown}`;

    // City + ward dropdowns (populate once)
    if (!_trnWardsLoaded && (data.ward_cities || data.wards)) {
      _trnWardCities = data.ward_cities || {};
      _trnAllWards = (data.wards || []).slice();
      const citySel = document.getElementById('trnCity');
      if (citySel) {
        citySel.innerHTML = '<option value="">Tất cả TP</option>' +
          Object.keys(_trnWardCities).map(c => `<option value="${esc(c)}">${esc(c)}</option>`).join('');
      }
      _trnPopulateWards('');
      _trnWardsLoaded = true;
    }

    _trnOffset += items.length;
    _trnHasMore = !!data.has_more;

    // Gallery store
    items.forEach(it => { _trnGal[it.id] = (it.images && it.images.length) ? it.images : []; });

    if (!items.length && !append) {
      root.innerHTML = `<div class="empty">Không có signal nào khớp bộ lọc.</div>`;
      _trnSyncSentinel();
      return;
    }
    const html = items.map(trainingCard).join('');
    if (append) root.insertAdjacentHTML('beforeend', html);
    else root.innerHTML = html;
    _trnBindChipDelegation(root);
    requestAnimationFrame(() => _trnSyncDescriptionToggles(root));
    _trnSyncSentinel();
  } finally {
    _trnLoading = false;
  }
}

// Sentinel cuối lưới: scroll tới → tự load thêm (infinite scroll)
let _trnObserver = null;
function _trnSyncSentinel() {
  const sent = document.getElementById('trnSentinel');
  if (!sent) return;
  sent.style.display = _trnHasMore ? 'block' : 'none';
  if (!_trnObserver) {
    _trnObserver = new IntersectionObserver((entries) => {
      if (entries.some(e => e.isIntersecting) && _trnHasMore && !_trnLoading) {
        loadTrainingItems(true);
      }
    }, { rootMargin: '400px' });
    _trnObserver.observe(sent);
  }
}

async function loadMoreTraining() {
  await loadTrainingItems(true);
}

async function saveLegalVerification(id, status) {
  const val = (suffix) => document.getElementById(`legal-${suffix}-${id}`)?.value || '';
  const payload = {
    listing_id: id,
    status,
    legal_road_text: val('road'),
    legal_ward: val('ward'),
    legal_area_m2: val('area'),
    legal_residential_m2: val('res'),
    thua_so: val('thua'),
    to_ban_do: val('to')
  };
  const result = await fetchJSON('/admin/api/legal-verification', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
  if (result && result.ok) {
    await loadDataQualityQueue('legal_qc');
    await loadDataQualitySummary();
  }
}

function trnToggleExpand(id) {
  const card = document.querySelector(`.training-card[data-id="${id}"]`);
  const btn = document.getElementById(`expbtn-${id}`);
  if (!card) return;
  const expanded = card.classList.toggle('expanded');
  if (btn) btn.textContent = expanded ? '▲ Thu gọn' : '▼ Mở review';
}

function trnToggleDesc(id) {
  const wrap = document.querySelector(`.train-desc-wrap[data-desc-wrap="${id}"]`);
  const btn = document.querySelector(`.train-desc-toggle[data-desc-toggle="${id}"]`);
  if (!wrap) return;
  const expanded = wrap.classList.toggle('expanded');
  if (btn) btn.textContent = expanded ? 'Thu gọn' : 'Xem thêm';
}

function _trnSyncDescriptionToggles(scope = document) {
  scope.querySelectorAll('.train-desc-wrap').forEach(wrap => {
    const desc = wrap.querySelector('.train-desc');
    const btn = wrap.querySelector('.train-desc-toggle');
    if (!desc || !btn) return;
    const wasExpanded = wrap.classList.contains('expanded');
    if (wasExpanded) wrap.classList.remove('expanded');
    const needsToggle = desc.scrollHeight > desc.clientHeight + 1;
    if (wasExpanded) wrap.classList.add('expanded');
    btn.hidden = !needsToggle;
    if (!needsToggle) wrap.classList.remove('expanded');
    btn.textContent = wrap.classList.contains('expanded') ? 'Thu gọn' : 'Xem thêm';
  });
}

function openTrnGallery(id) {
  const imgs = _trnGal[id] || [];
  if (!imgs.length) return;
  _trnGalIds = imgs;
  _trnGalIdx = 0;
  _trnGalRender();
  document.getElementById('trnGallery').classList.add('open');
}
function closeTrnGallery() {
  document.getElementById('trnGallery').classList.remove('open');
}
function trnGalleryNav(delta) {
  if (!_trnGalIds.length) return;
  _trnGalIdx = (_trnGalIdx + delta + _trnGalIds.length) % _trnGalIds.length;
  _trnGalRender();
}
function _trnGalRender() {
  document.getElementById('trnGalleryImg').src = _trnGalIds[_trnGalIdx];
  document.getElementById('trnGalleryCounter').textContent =
    `${_trnGalIdx + 1} / ${_trnGalIds.length}`;
}

function trainingCard(x) {
  const cid = `card-${x.id}`;
  const explain = x.explain || {};
  const missing = (explain.missing_fields || []).length ? explain.missing_fields.join(', ') : 'không';
  const nImg = (x.images && x.images.length) || 0;
  const desc = (x.description || '').trim();
  const actualPpm2 = x.actual_ppm2 || x.price_per_m2 || '';
  const fairPpm2 = x.fair_ppm2 || '';
  const sourceFlags = (x.source_quality_flags || '').split(',').filter(Boolean);
  const fairTitle = x.fair_ty
    ? `(Fair Value: ${money(x.fair_ty)}${fairPpm2 ? ` · ${ppm2(fairPpm2)}` : ''})`
    : '';
  return `
    <article class="training-card" data-id="${x.id}">
      <div class="train-img-wrap">
        <img class="train-img" src="${esc(x.image || PLACEHOLDER)}" onerror="this.src=PLACEHOLDER" alt="">
        <div class="mos-chip">Biên an toàn ${Math.round(x.mos_pct || 0)}%</div>
        ${nImg ? `<button class="train-gallery-btn" onclick="openTrnGallery(${x.id})">🖼️ Ảnh (${nImg})</button>` : ''}
      </div>
      <div class="train-body">
        <div class="train-title">
          <a href="${esc(x.detail_url)}" target="_blank">${esc(x.ward || 'Unknown')}</a>
          <span>TD-${x.id}</span>
        </div>
        <div class="train-lines">
          <div><strong>${esc(x.title || 'Không có tiêu đề')}</strong></div>
          <div>${esc(x.road_type || 'Chưa rõ đường')} · ${esc(PTYPES[x.property_type] || x.property_type || 'Chưa rõ loại')}</div>
          <div>DT: <strong>${area(x.area_m2)}</strong> · Giá rao: <strong>${money(x.price_ty)}</strong> · Giá/m²: <strong>${ppm2(actualPpm2)}</strong></div>
        </div>
        ${desc ? `
          <div class="train-desc-wrap" data-desc-wrap="${x.id}">
            <div class="train-desc">${esc(desc)}</div>
            <button type="button" class="train-desc-toggle" data-desc-toggle="${x.id}" onclick="trnToggleDesc(${x.id})" hidden>Xem thêm</button>
          </div>` : ''}

        <div class="trn-review-cols${x.ai_verdict ? ' has-ai' : ''}">
          <div class="trn-review-main">
            <div class="review-box">
              <div class="review-title">Định giá AI ${fairTitle}</div>
              <div class="chip-row">
                <button class="chip" data-card="${cid}" data-group="valuation" data-value="cheap_real">Rẻ thật</button>
                <button class="chip" data-card="${cid}" data-group="valuation" data-value="fair">Giá hợp lý</button>
                <button class="chip" data-card="${cid}" data-group="valuation" data-value="overpriced">Đang cao</button>
                <button class="chip" data-card="${cid}" data-group="valuation" data-value="fake_price">Giá ảo</button>
                <button class="chip" data-card="${cid}" data-group="valuation" data-value="cannot_price">Không định giá</button>
              </div>
              <ul class="explain-list">
                <li>Score ${Math.round(x.signal_score || 0)}, segment ${esc(x.segment || '-')} (${x.n_segment || 0} mẫu)</li>
                <li>Giá thực ${money(x.price_ty)} (${ppm2(actualPpm2)}), fair ${money(x.fair_ty)} (${ppm2(fairPpm2)}), thiếu field: ${esc(missing)}</li>
                ${sourceFlags.length ? `<li>Source QC: ${sourceFlags.map(esc).join(', ')}</li>` : ''}
              </ul>
              <div class="review-title" style="margin-top:10px">Nguyên nhân</div>
              <div class="chip-row">
                ${[['bad_fengshui','Phong thủy xấu'],['deep_alley','Hẻm sâu'],['corner_lot','Đất góc'],['bait_listing','Tin mồi'],['fake_price','Giá ảo']].map(([v,l]) => `<button class="chip reason-chip" data-card="${cid}" data-group="reason" data-value="${v}">${l}</button>`).join('')}
              </div>
            </div>
            <button class="primary-btn save-training" onclick="saveTraining(${x.id})">Lưu nhãn định giá</button>
          </div>
          <div class="trn-review-aside">${x.ai_verdict ? `
            <div class="review-box" style="opacity:.92;height:100%">
              <div class="review-title">🤖 Claude pre-review</div>
              <ul class="explain-list">
                <li><strong>${esc(x.ai_verdict)}</strong>${x.ai_confidence != null ? ` · ${Math.round(x.ai_confidence * 100)}%` : ''}</li>
                ${x.ai_reasoning ? `<li>${esc(x.ai_reasoning)}</li>` : ''}
                ${(() => { let f = []; try { f = JSON.parse(x.ai_red_flags || '[]'); } catch (e) { f = []; } return (f && f.length) ? `<li>🚩 ${f.map(esc).join(', ')}</li>` : ''; })()}
                ${x.ai_needs_map_check ? `<li>🗺️ Cần kiểm tra quy hoạch/pháp lý/vị trí</li>` : ''}
              </ul>
            </div>` : ''}</div>
        </div>
      </div>
    </article>
  `;
}

function dataQualityReviewCard(x, queue) {
  const nImg = (x.images && x.images.length) || 0;
  const desc = (x.description || '').trim();
  const actualPpm2 = x.actual_ppm2 || x.price_per_m2 || '';
  const fairPpm2 = x.fair_ppm2 || '';
  const sourceFlags = (x.source_quality_flags || '').split(',').filter(Boolean);
  const explain = x.explain || {};
  const missing = (explain.missing_fields || []).length ? explain.missing_fields.join(', ') : 'không';
  const legal = x.legal_summary || {};
  const legalFlags = String(legal.flags || '').split(',').filter(Boolean);
  const showLegalTools = queue === 'legal_qc' && String(legal.status || '').trim() !== 'has_document';
  const legalTools = showLegalTools ? `
        <div class="review-box legal-qc-box">
          <div class="review-title">Legal QC · ${esc(legal.status || 'unverified')} · ${Math.round(legal.trust_score || legal.confidence_score || 0)}%</div>
          <ul class="explain-list">
            <li>Thửa/tờ: ${esc(legal.thua_so || '-')} / ${esc(legal.to_ban_do || '-')}</li>
            <li>DT sổ: ${area(legal.legal_area_m2)} · Thổ cư: ${area(legal.legal_residential_m2)}</li>
            <li>Phường: ${esc(legal.legal_ward || '-')} · Đường: ${esc(legal.legal_road_text || '-')}</li>
            ${legalFlags.length ? `<li>Flags: ${legalFlags.map(esc).join(', ')}</li>` : ''}
          </ul>
          <div class="legal-qc-grid">
            <input id="legal-road-${x.id}" value="${esc(legal.legal_road_text || '')}" placeholder="Đường trên sổ">
            <input id="legal-ward-${x.id}" value="${esc(legal.legal_ward || '')}" placeholder="Phường trên sổ">
            <input id="legal-area-${x.id}" value="${esc(legal.legal_area_m2 || '')}" placeholder="DT sổ">
            <input id="legal-res-${x.id}" value="${esc(legal.legal_residential_m2 || '')}" placeholder="Thổ cư">
            <input id="legal-thua-${x.id}" value="${esc(legal.thua_so || '')}" placeholder="Thửa số">
            <input id="legal-to-${x.id}" value="${esc(legal.to_ban_do || '')}" placeholder="Tờ bản đồ">
          </div>
          <div class="chip-row">
            <button class="secondary-btn legal-qc-action" onclick="saveLegalVerification(${x.id}, 'verified')">Xác nhận đúng sổ</button>
            <button class="secondary-btn legal-qc-action" onclick="saveLegalVerification(${x.id}, 'needs_review')">Cần soi tiếp</button>
            <button class="secondary-btn legal-qc-action" onclick="saveLegalVerification(${x.id}, 'conflict')">Có xung đột</button>
          </div>
        </div>` : '';
  return `
    <article class="training-card quality-review-card" data-id="${x.id}">
      <div class="train-img-wrap">
        <img class="train-img" src="${esc(x.image || PLACEHOLDER)}" onerror="this.src=PLACEHOLDER" alt="">
        <div class="mos-chip">Biên an toàn ${Math.round(x.mos_pct || 0)}%</div>
        ${nImg ? `<button class="train-gallery-btn" onclick="openTrnGallery(${x.id})">Ảnh (${nImg})</button>` : ''}
      </div>
      <div class="train-body">
        <div class="train-title">
          <a href="${esc(x.detail_url)}" target="_blank">${esc(x.ward || 'Unknown')}</a>
          <span>TD-${x.id}</span>
        </div>
        <div class="train-lines">
          <div><strong>${esc(x.title || 'Không có tiêu đề')}</strong></div>
          <div>${esc(SOURCE_NAMES[x.source] || x.source || '-')} · ${esc(x.road_type || 'Chưa rõ đường')} · ${esc(PTYPES[x.property_type] || x.property_type || 'Chưa rõ loại')}</div>
          <div>DT: <strong>${area(x.area_m2)}</strong> · Giá rao: <strong>${money(x.price_ty)}</strong> · Giá/m²: <strong>${ppm2(actualPpm2)}</strong></div>
        </div>
        ${desc ? `
          <div class="train-desc-wrap" data-desc-wrap="${x.id}">
            <div class="train-desc">${esc(desc)}</div>
            <button type="button" class="train-desc-toggle" data-desc-toggle="${x.id}" onclick="trnToggleDesc(${x.id})" hidden>Xem thêm</button>
          </div>` : ''}
        ${legalTools}
        <div class="review-box">
          <div class="review-title">Thông tin kiểm dịch</div>
          <ul class="explain-list">
            <li>Queue: ${esc(queue)} · Feedback: ${esc(x.feedback_verdict || '-')} · Valuation: ${esc(x.valuation_verdict || '-')} · Data: ${esc(x.extraction_verdict || '-')}</li>
            <li>Score ${Math.round(x.signal_score || 0)}, segment ${esc(x.segment || '-')} (${x.n_segment || 0} mẫu)</li>
            <li>Giá thực ${money(x.price_ty)} (${ppm2(actualPpm2)}), fair ${money(x.fair_ty)} (${ppm2(fairPpm2)}), thiếu field: ${esc(missing)}</li>
            ${sourceFlags.length ? `<li>Source QC: ${sourceFlags.map(flag => esc(qualityFlagLabel(flag))).join(', ')}</li>` : ''}
          </ul>
        </div>
      </div>
    </article>
  `;
}

async function saveTraining(id) {
  const card = document.querySelector(`.training-card[data-id="${id}"]`);
  const valuation = card.querySelector('.chip[data-group="valuation"].active')?.dataset.value || '';
  if (!valuation) {
    alert('Chọn nhãn định giá trước khi lưu.');
    return;
  }
  const tags = Array.from(card.querySelectorAll('.chip[data-group="reason"].active')).map(x => x.dataset.value);
  let verdict;
  if (tags.includes('fake_price') || valuation === 'fake_price') {
    verdict = 'fake_price';
  } else {
    verdict = valuation;
  }
  await fetchJSON('/admin/api/ai-training/feedback', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      listing_id: id,
      verdict,
      extraction_verdict: 'all_correct',
      valuation_verdict: valuation,
      reason_tags: tags,
      reason_code: tags[0] || valuation,
      reason_text: 'admin_valuation_training'
    })
  });
  card.remove();
}

document.addEventListener('DOMContentLoaded', () => {
  initAdminTheme();
  document.querySelectorAll('.nav-item').forEach(btn => btn.addEventListener('click', () => switchPanel(btn.dataset.panel)));
  window.addEventListener('popstate', () => switchPanel(panelFromLocation(), { updateUrl: false }));
  document.querySelectorAll('.segment[data-quality-tab]').forEach(btn => btn.addEventListener('click', () => switchQualityTab(btn.dataset.qualityTab)));
  document.querySelectorAll('.segment[data-infra-filter]').forEach(btn => btn.addEventListener('click', () => switchInfraFilter(btn.dataset.infraFilter)));
  document.getElementById('leadStatusFilter').addEventListener('change', loadLeads);
  document.getElementById('leadSearch').addEventListener('input', () => {
    clearTimeout(leadTimer);
    leadTimer = setTimeout(loadLeads, 220);
  });
  document.getElementById('exportLeadsBtn').addEventListener('click', exportLeads);
  document.getElementById('addBlacklistBtn').addEventListener('click', addBlacklist);
  document.getElementById('refreshCrawlBtn')?.addEventListener('click', loadCrawlConfig);
  document.getElementById('saveCrawlProfilesBtn')?.addEventListener('click', saveCrawlProfiles);
  document.getElementById('addCrawlProfileBtn')?.addEventListener('click', addCrawlProfile);
  document.getElementById('toggleApifyTokensBtn')?.addEventListener('click', toggleApifyTokensPanel);
  document.getElementById('addApifyTokenBtn')?.addEventListener('click', addApifyToken);
  document.getElementById('runCrawlBtn')?.addEventListener('click', runSelectedCrawl);
  document.getElementById('runManualReprocessBtn')?.addEventListener('click', () => runCrawlMaintenance('reprocess'));
  document.getElementById('runValuationOnlyBtn')?.addEventListener('click', () => runCrawlMaintenance('valuation_only'));
  document.getElementById('crawlRunProfile')?.addEventListener('change', syncCrawlRunInputs);
  document.querySelectorAll('[data-crawl-mode]').forEach(btn => btn.addEventListener('click', () => setCrawlMode(btn.dataset.crawlMode)));
  document.getElementById('refreshTrainingBtn').addEventListener('click', loadTrainingItems);
  ['trnMos', 'trnSort', 'trnWard'].forEach(idv => {
    const el = document.getElementById(idv);
    if (el) el.addEventListener('change', () => {
      _trnWardsLoaded = true;
      loadTrainingItems();
    });
  });
  const citySel = document.getElementById('trnCity');
  if (citySel) citySel.addEventListener('change', () => {
    _trnPopulateWards(citySel.value);
    document.getElementById('trnWard').value = '';
    loadTrainingItems();
  });
  // Sidebar collapse
  const toggleSidebar = document.getElementById('toggleSidebar');
  if (toggleSidebar) {
    let collapsed = false;
    try { collapsed = localStorage.getItem('sidebarCollapsed') === '1'; } catch (e) {}
    if (collapsed) document.body.classList.add('sidebar-collapsed');
    toggleSidebar.addEventListener('click', () => {
      document.body.classList.toggle('sidebar-collapsed');
      const c = document.body.classList.contains('sidebar-collapsed');
      try { localStorage.setItem('sidebarCollapsed', c ? '1' : '0'); } catch (e) {}
    });
  }
  const applyTrnView = (view) => {
    const grid = document.getElementById('trainingGrid');
    if (grid) grid.classList.toggle('view-list', view === 'list');
    document.getElementById('trnViewGrid')?.classList.toggle('active', view !== 'list');
    document.getElementById('trnViewList')?.classList.toggle('active', view === 'list');
    try { localStorage.setItem('trnView', view); } catch (e) {}
    if (grid) requestAnimationFrame(() => _trnSyncDescriptionToggles(grid));
  };
  document.getElementById('trnViewGrid')?.addEventListener('click', () => applyTrnView('grid'));
  document.getElementById('trnViewList')?.addEventListener('click', () => applyTrnView('list'));
  let savedView = 'grid';
  try { savedView = localStorage.getItem('trnView') || 'grid'; } catch (e) {}
  applyTrnView(savedView);
  document.addEventListener('keydown', (e) => {
    const g = document.getElementById('trnGallery');
    if (!g || !g.classList.contains('open')) return;
    if (e.key === 'Escape') closeTrnGallery();
    else if (e.key === 'ArrowLeft') trnGalleryNav(-1);
    else if (e.key === 'ArrowRight') trnGalleryNav(1);
  });
  document.getElementById('refreshInfraBtn').addEventListener('click', loadInfraItems);
  document.getElementById('saveInfraBtn').addEventListener('click', saveInfra);
  document.getElementById('resetInfraBtn').addEventListener('click', resetInfraForm);
  document.getElementById('adminThemeToggle').addEventListener('click', toggleAdminTheme);
  const refreshUsersBtn = document.getElementById('refreshUsersBtn');
  if (refreshUsersBtn) refreshUsersBtn.addEventListener('click', loadUsers);
  const userTierFilter = document.getElementById('userTierFilter');
  if (userTierFilter) userTierFilter.addEventListener('change', loadUsers);
  const userSearch = document.getElementById('userSearch');
  if (userSearch) userSearch.addEventListener('input', () => {
    clearTimeout(userTimer);
    userTimer = setTimeout(loadUsers, 220);
  });
  switchPanel(panelFromLocation(), { updateUrl: false });
});
