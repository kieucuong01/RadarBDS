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
let apifyTokens = [];
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
    loader = activeQualityTab === 'dups' ? loadDuplicates : loadBlacklist;
  }
  if (name === 'training') loader = () => loadTrainingItems(false);
  if (name === 'infra') loader = loadInfraItems;
  if (name === 'users') loader = loadUsers;
  if (name === 'crawl') loader = loadCrawlConfig;
  if (loader) {
    withAdminToast(`Đang mở ${panelLabels[name] || 'tab'}`, loader, `Đã mở ${panelLabels[name] || 'tab'}`, 'Không tải được tab');
  }
}

// ──────────────────────────────────────────────────────────────
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
  apifyTokens = data.apify_tokens || [];
  renderCrawlStats(data.summary || {});
  renderCrawlOps(data.summary?.ops || {});
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
  const el = document.getElementById('crawlStats');
  if (!el) return;
  el.innerHTML = items.map((s, idx) => `
    <div class="stat-card">
      <small>${esc(s[0])}</small>
      <div><strong style="color:${idx === 5 && Number(s[1]) ? 'var(--orange)' : idx === 6 && Number(s[1]) ? 'var(--red)' : idx === 7 && s[1] !== 'Idle' ? 'var(--blue)' : 'var(--ink)'}">${esc(s[1])}</strong><span>${esc(s[2])}</span></div>
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
  const scheduleOk = schedule.installed && (schedule.run_time === '21:00' || String(schedule.next_run_time || '').includes('9:00'));
  const healthClass = lock_blockers.length ? 'danger' : source_errors.length ? 'warn' : 'ok';
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
        <strong>RadarBDS_DailyCrawl</strong>
      </div>
      <span class="ops-pill ${healthClass}">${lock_blockers.length ? 'Lock đang kẹt' : source_errors.length ? 'Cần xem lỗi nguồn' : 'Đang ổn định'}</span>
    </div>
    <div class="crawl-ops-grid">
      <div class="crawl-ops-card ${scheduleOk ? 'ok' : 'warn'}">
        <small>Lich daily</small>
        <strong>${schedule.installed ? (schedule.run_time || shortDate(schedule.next_run_time) || 'Đã cài') : 'Chưa cài'}</strong>
        <span>${schedule.installed ? `Next: ${esc(schedule.next_run_time || 'chưa rõ')}` : 'Cần cài RadarBDS_DailyCrawl lúc 21:00'}</span>
        ${schedule.error ? `<em>${esc(schedule.error)}</em>` : ''}
      </div>
      <div class="crawl-ops-card">
        <small>Lan chay gan nhat</small>
        <strong>${last.source ? `${esc(last.source)} · ${esc(last.status || '')}` : 'Chưa có run'}</strong>
        <span>${last.started_at ? `${esc(shortDate(last.started_at))} · new=${Number(last.new || 0)} · fetched=${Number(last.fetched || 0)}` : 'Chưa có crawl_runs'}</span>
      </div>
      <div class="crawl-ops-card">
        <small>Batch gan nhat</small>
        <strong>${Number(last24.new || 0).toLocaleString('vi-VN')} tin mới</strong>
        <span>${Number(last24.runs || 0)} runs · fetched=${Number(last24.fetched || 0).toLocaleString('vi-VN')} · skipped=${Number(last24.skipped || 0).toLocaleString('vi-VN')}</span>
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
}

function renderCrawlProfiles() {
  const body = document.getElementById('crawlProfileRows');
  if (!body) return;
  if (!crawlProfiles.length) {
    body.innerHTML = `<tr><td colspan="6"><div class="empty">Chưa có môi giới Facebook.</div></td></tr>`;
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
    renderCrawlStats(data.summary || {});
    renderCrawlOps(data.summary?.ops || {});
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
  const downloaded = job.stats?.downloaded_images;
  if (meta) {
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
// ──────────────────────────────────────────────────────────────
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
    body.innerHTML = `<tr><td colspan="9"><div class="empty">Không có user phù hợp.</div></td></tr>`;
    return;
  }
  body.innerHTML = items.map(u => {
    const tierBadgeColor = u.effective_tier === 'vip' ? 'var(--green)' : u.effective_tier === 'admin' ? 'var(--orange)' : 'var(--ink-muted)';
    const banned = u.is_banned ? `<span style="color:var(--red)">BANNED</span>` : '';
    const vipExp = u.vip_expires_at ? shortDate(u.vip_expires_at) : '-';
    const expired = u.tier === 'vip' && u.effective_tier !== 'vip' ? ' <small style="color:var(--red)">(hết hạn)</small>' : '';
    const tg = u.telegram_linked ? '✓' : '-';
    return `
      <tr>
        <td>#${u.id}</td>
        <td><strong>${esc(u.identifier || '-')}</strong><br><small>${esc(u.identifier_type || '')}</small></td>
        <td>${esc(u.display_name || '-')}</td>
        <td><strong style="color:${tierBadgeColor}">${esc((u.effective_tier || u.tier || '').toUpperCase())}</strong>${expired} ${banned}</td>
        <td>${vipExp}</td>
        <td>${tg}</td>
        <td>${Number(u.watchlist_count || 0)}</td>
        <td>${shortDate(u.created_at)}</td>
        <td>${shortDate(u.last_login_at)}</td>
        <td>
          <button class="icon-btn" onclick="grantVip(${u.id}, 30)">+30d VIP</button>
          <button class="icon-btn" onclick="grantVip(${u.id}, 7)">+7d</button>
          <button class="icon-btn" onclick="revokeVip(${u.id})">Revoke</button>
          <button class="icon-btn" onclick="toggleBan(${u.id}, ${u.is_banned ? 0 : 1})">${u.is_banned ? 'Unban' : 'Ban'}</button>
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
        <td>${shortDate(x.created_at)}</td>
        <td class="phone">${esc(x.zalo_phone || '-')}</td>
        <td><a class="deal-pill" href="${esc(link)}" target="_blank">${esc(listingLabel)}</a></td>
        <td>
          <select class="status-select ${st.cls}" data-lead="${x.id}">
            ${STATUS_KEYS.map(k => `<option value="${k}" ${x.status === k ? 'selected' : ''}>${STATUS[k].label}</option>`).join('')}
          </select>
        </td>
        <td><button class="icon-btn" onclick="window.open('${esc(link)}','_blank')">Mở</button></td>
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
  document.querySelectorAll('.quality-tab').forEach(tab => tab.classList.toggle('active', tab.id === `quality-${name === 'dups' ? 'dups' : 'blacklist'}`));
  if (name === 'dups') loadDuplicates();
  else loadBlacklist();
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
    root.innerHTML = `<div class="empty">Không còn cặp duplicate cần xử lý.</div>`;
    return;
  }
  root.innerHTML = items.map(x => duplicateCard(x)).join('');
}

function adPanel(x, side) {
  const isCanon = side === 'canonical';
  const id = isCanon ? x.duplicate_of_id : x.id;
  const source = isCanon ? x.canonical_source : x.source;
  const price = isCanon ? x.canonical_price_ty : x.price_ty;
  const areaVal = isCanon ? x.canonical_area_m2 : x.area_m2;
  const desc = isCanon ? x.canonical_description_excerpt : x.description_excerpt;
  const img = isCanon ? x.canonical_image : x.image;
  const dt = isCanon ? x.canonical_dt : x.dt;
  const detail = isCanon ? x.canonical_detail_url : x.detail_url;
  return `
    <div class="ad-box">
      <img class="ad-img" src="${esc(img || PLACEHOLDER)}" onerror="this.src=PLACEHOLDER" alt="">
      <div>
        <a class="ad-title" href="${esc(detail)}" target="_blank">AD-${id} · ${esc(SOURCE_NAMES[source] || source || '-')}</a>
        <div class="ad-meta">${money(price)} · ${area(areaVal)} · ${shortDate(dt)}</div>
        <div class="ad-desc">${esc(desc || '-')}</div>
      </div>
    </div>
  `;
}

function duplicateCard(x) {
  const confidence = Math.min(96, Math.max(72, Math.round(100 - Math.abs((x.price_ty || 0) - (x.canonical_price_ty || 0)) * 5)));
  return `
    <article class="dup-card">
      <div class="dup-head">
        <div>Cặp nghi trùng <span class="deal-pill">DUP-${x.id}</span></div>
        <div style="color:var(--muted)">AI confidence: <strong style="color:var(--red)">${confidence}%</strong></div>
      </div>
      <div class="dup-grid">
        ${adPanel(x, 'listing')}
        ${adPanel(x, 'canonical')}
      </div>
      <div class="dup-actions">
        <button class="primary-btn merge-btn" onclick="mergeDup(${x.id}, ${x.duplicate_of_id})">Gộp thành 1 Deal</button>
        <button class="secondary-btn" onclick="splitDup(${x.id}, ${x.duplicate_of_id})">Khác lô</button>
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
  const queue = document.getElementById('trnQueue')?.value || 'main';
  const p = new URLSearchParams({ limit: String(TRN_PAGE), sort, offset: String(offset) });
  if (queue && queue !== 'main') p.set('queue', queue);
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
    if (group === 'extraction') syncExtractionState(chip.dataset.card);
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

// Trích xuất sai → ẩn mục "2. Định giá AI" (tin đó để học làm sạch dữ liệu);
// chỉ khi trích xuất "Đúng hết" mới chấm định giá (để cải tiến phần định giá).
function syncExtractionState(cid) {
  const active = document.querySelector(`.chip[data-card="${cid}"][data-group="extraction"].active`);
  const ok = !active || active.dataset.value === 'all_correct';
  const valbox = document.getElementById(`valbox-${cid}`);
  const note = document.getElementById(`exnote-${cid}`);
  if (valbox) valbox.style.display = ok ? '' : 'none';
  if (note) note.style.display = ok ? 'none' : '';
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
    loadTrainingItems();
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
  const legal = x.legal_summary || {};
  const legalFlags = String(legal.flags || '').split(',').filter(Boolean);
  const legalBox = (x.is_legal_qc || legal.status) ? `
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
  const fairTitle = x.fair_ty
    ? `(Fair Value: ${money(x.fair_ty)}${fairPpm2 ? ` · ${ppm2(fairPpm2)}` : ''})`
    : '';
  return `
    <article class="training-card" data-id="${x.id}">
      <div class="train-img-wrap">
        <img class="train-img" src="${esc(x.image || PLACEHOLDER)}" onerror="this.src=PLACEHOLDER" alt="">
        <div class="mos-chip">MOS ${Math.round(x.mos_pct || 0)}%</div>
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
            ${legalBox}
            <div class="review-box">
              <div class="review-title">1. Thông tin trích xuất</div>
              <div class="chip-row">
                <button class="chip active" data-card="${cid}" data-group="extraction" data-value="all_correct">Đúng hết</button>
                <button class="chip" data-card="${cid}" data-group="extraction" data-value="wrong_ward">Sai phường</button>
                <button class="chip" data-card="${cid}" data-group="extraction" data-value="wrong_road">Sai đường</button>
                <button class="chip" data-card="${cid}" data-group="extraction" data-value="wrong_property_type">Sai loại hình</button>
                <button class="chip" data-card="${cid}" data-group="extraction" data-value="wrong_price">Sai giá</button>
                <button class="chip" data-card="${cid}" data-group="extraction" data-value="wrong_area">Sai diện tích</button>
              </div>
              <div class="extraction-note" id="exnote-${cid}" style="display:none;margin-top:8px;font-size:11px;color:var(--muted)">
                Trích xuất sai → tin này dùng để học <strong>làm sạch dữ liệu</strong>, không cần chấm định giá.
              </div>
            </div>
            <div class="review-box" id="valbox-${cid}">
              <div class="review-title">2. Định giá AI ${fairTitle}</div>
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
                ${[['bad_fengshui','Phong thủy xấu'],['deep_alley','Hẻm sâu'],['corner_lot','Đất góc'],['bait_listing','Tin mồi'],['fake_price','Giá ảo'],['bad_data','Dữ liệu sai']].map(([v,l]) => `<button class="chip reason-chip" data-card="${cid}" data-group="reason" data-value="${v}">${l}</button>`).join('')}
              </div>
            </div>
            <button class="primary-btn save-training" onclick="saveTraining(${x.id})">Lưu Phản Hồi & Dạy AI</button>
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

async function saveTraining(id) {
  const card = document.querySelector(`.training-card[data-id="${id}"]`);
  const extraction = card.querySelector('.chip[data-group="extraction"].active')?.dataset.value || 'all_correct';
  const extractionOk = extraction === 'all_correct';
  // Trích xuất sai → bỏ qua chấm định giá, tin này về nhánh học làm sạch dữ liệu.
  const valuation = extractionOk
    ? (card.querySelector('.chip[data-group="valuation"].active')?.dataset.value || '')
    : 'cannot_price';
  if (extractionOk && !valuation) {
    alert('Chọn nhãn định giá trước khi lưu.');
    return;
  }
  const tags = Array.from(card.querySelectorAll('.chip[data-group="reason"].active')).map(x => x.dataset.value);
  let verdict;
  if (tags.includes('fake_price') || valuation === 'fake_price') {
    verdict = 'fake_price';
  } else if (!extractionOk) {
    verdict = 'bad_data';                       // sai trích xuất → học làm sạch dữ liệu
  } else if (tags.includes('bad_data')) {
    verdict = 'cannot_price';
  } else {
    verdict = valuation;                        // nhãn định giá tách riêng: cheap_real|fair|overpriced|fake_price|cannot_price
  }
  await fetchJSON('/admin/api/ai-training/feedback', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      listing_id: id,
      verdict,
      extraction_verdict: extraction,
      valuation_verdict: valuation,
      reason_tags: tags,
      reason_code: tags[0] || extraction || valuation,
      reason_text: 'admin_ai_training'
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
  document.getElementById('addApifyTokenBtn')?.addEventListener('click', addApifyToken);
  document.getElementById('runCrawlBtn')?.addEventListener('click', runSelectedCrawl);
  document.getElementById('crawlRunProfile')?.addEventListener('change', syncCrawlRunInputs);
  document.querySelectorAll('[data-crawl-mode]').forEach(btn => btn.addEventListener('click', () => setCrawlMode(btn.dataset.crawlMode)));
  document.getElementById('refreshTrainingBtn').addEventListener('click', loadTrainingItems);
  ['trnMos', 'trnSort', 'trnWard', 'trnQueue'].forEach(idv => {
    const el = document.getElementById(idv);
    if (el) el.addEventListener('change', () => {
      if (idv === 'trnQueue') {
        _trnWardsLoaded = false;
        _trnAllWards = [];
        _trnWardCities = {};
      } else {
        _trnWardsLoaded = true;
      }
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
