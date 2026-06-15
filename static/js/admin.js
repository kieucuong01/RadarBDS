const STATUS = {
  new: { label: 'Chá» xá»­ lÃ½', cls: 'status-new' },
  called: { label: 'Äang tÆ° váº¥n', cls: 'status-called' },
  viewing: { label: 'Äi xem Ä‘áº¥t', cls: 'status-viewing' },
  deposit: { label: 'Chá»‘t cá»c', cls: 'status-deposit' },
  cancelled: { label: 'Há»§y', cls: 'status-cancelled' }
};
const STATUS_KEYS = Object.keys(STATUS);
const SOURCE_NAMES = { facebook: 'Facebook', guland: 'Guland', batdongsan: 'BDS.vn' };
const PTYPES = { dat_nen: 'Äáº¥t ná»n', dat_vuon: 'Äáº¥t vÆ°á»n', nha_dat: 'NhÃ  Ä‘áº¥t', nha_tro: 'NhÃ  trá»', chung_cu: 'Chung cÆ°', nha_o_xa_hoi: 'NhÃ  á»Ÿ xÃ£ há»™i' };
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
    ? showAdminToast(method === 'GET' ? 'Äang táº£i dá»¯ liá»‡u' : 'Äang xá»­ lÃ½ tÃ¡c vá»¥', 'loading', { sticky: true })
    : null;
  try {
    const res = await fetch(clean.toString(), options);
    if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
    const data = await res.json();
    if (toast) updateAdminToast(toast, method === 'GET' ? 'ÄÃ£ táº£i dá»¯ liá»‡u' : 'ÄÃ£ xá»­ lÃ½ xong', 'success');
    return data;
  } catch (error) {
    if (toast) updateAdminToast(toast, `TÃ¡c vá»¥ lá»—i: ${formatAdminError(error)}`, 'error', { delay: 5200 });
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
        <strong>Äang táº£i dá»¯ liá»‡u...</strong>
        <small>Vui lÃ²ng Ä‘á»£i trong giÃ¢y lÃ¡t</small>
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
  const msg = String(error?.message || error || 'KhÃ´ng rÃµ lá»—i');
  return msg.length > 150 ? `${msg.slice(0, 150)}...` : msg;
}

async function withAdminToast(loadingMessage, task, successMessage = 'HoÃ n táº¥t', errorMessage = 'CÃ³ lá»—i xáº£y ra') {
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
  return `${Number(v).toLocaleString('vi-VN', { maximumFractionDigits: 2 })} tá»·`;
}

function area(v) {
  if (v === null || v === undefined || v === '') return '-';
  return `${Number(v).toLocaleString('vi-VN', { maximumFractionDigits: 1 })} mÂ²`;
}

function ppm2(v) {
  if (v === null || v === undefined || v === '') return '-';
  const n = Number(v);
  if (!Number.isFinite(n) || n <= 0) return '-';
  return `${n.toLocaleString('vi-VN', { maximumFractionDigits: 1 })} tr/mÂ²`;
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
  const panelLabels = { crm: 'CRM', quality: 'Quality', training: 'AI Training', infra: 'Háº¡ táº§ng', users: 'Users', crawl: 'Facebook Crawl' };
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
    withAdminToast(`Äang má»Ÿ ${panelLabels[name] || 'tab'}`, loader, `ÄÃ£ má»Ÿ ${panelLabels[name] || 'tab'}`, 'KhÃ´ng táº£i Ä‘Æ°á»£c tab');
  }
}

// â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
// Facebook crawl manager
// Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬

function crawlProfileLabel(p) {
  const name = p.broker_name || p.url.replace('https://www.facebook.com/', '');
  return `${name}${p.city ? ' Â· ' + p.city : ''}`;
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
    body.innerHTML = `<tr><td colspan="7"><div class="empty">ChÆ°a cÃ³ key trong pool. Náº¿u trá»‘ng, crawler sáº½ dÃ¹ng APIFY_TOKEN tá»« .env.</div></td></tr>`;
    return;
  }
  body.innerHTML = apifyTokens.map(t => {
    const pct = t.monthly_quota ? Math.min(100, Math.round((Number(t.used_this_month || 0) / Number(t.monthly_quota)) * 100)) : 0;
    const warn = Number(t.remaining || 0) <= 100 ? 'warn' : '';
    return `
      <tr data-token-id="${esc(t.id)}">
        <td data-label="Báº­t">
          <label class="crawl-switch">
            <input type="checkbox" ${t.active ? 'checked' : ''} onchange="toggleApifyToken('${esc(t.id)}', this.checked)">
            <span></span>
          </label>
        </td>
        <td data-label="Key"><strong>${esc(t.label)}</strong><br><small>${esc(t.token_mask)}</small></td>
        <td data-label="Quota">${Number(t.monthly_quota || 0).toLocaleString('vi-VN')}</td>
        <td data-label="ÄÃ£ dÃ¹ng">
          <div class="apify-usage"><span style="width:${pct}%"></span></div>
          <small>${Number(t.used_this_month || 0).toLocaleString('vi-VN')} post Â· ${esc(t.month || '')}</small>
        </td>
        <td data-label="CÃ²n láº¡i"><strong class="${warn}">${Number(t.remaining || 0).toLocaleString('vi-VN')}</strong></td>
        <td data-label="Tráº¡ng thÃ¡i">${t.last_error ? `<span class="crawl-error">${esc(t.last_error)}</span>` : `<span class="ok-text">OK</span>`}<br><small>${esc(shortDate(t.last_used_at))}</small></td>
        <td data-label="Thao tÃ¡c" class="apify-token-actions">
          <button class="icon-btn" onclick="resetApifyTokenUsage('${esc(t.id)}')">Reset</button>
          <button class="icon-btn danger" onclick="deleteApifyToken('${esc(t.id)}')">XÃ³a</button>
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
  if (button) button.textContent = apifyTokensExpanded ? 'Thu gá»n' : (stats.total ? 'Quáº£n lÃ½ key' : 'ThÃªm key');
  if (summary) {
    summary.textContent = stats.total
      ? `${stats.active}/${stats.total} key Ä‘ang báº­t Â· cÃ²n ${stats.remaining.toLocaleString('vi-VN')} post thÃ¡ng nÃ y`
      : 'ChÆ°a cáº¥u hÃ¬nh key pool, crawler sáº½ dÃ¹ng APIFY_TOKEN tá»« .env.';
  }
  if (miniStats) {
    const usagePct = stats.quota ? Math.min(100, Math.round((stats.used / stats.quota) * 100)) : 0;
    miniStats.innerHTML = `
      <span><strong>${stats.remaining.toLocaleString('vi-VN')}</strong><small>cÃ²n láº¡i</small></span>
      <span><strong>${usagePct}%</strong><small>Ä‘Ã£ dÃ¹ng</small></span>
      <span class="${stats.errors ? 'danger' : stats.low ? 'warn' : 'ok'}"><strong>${stats.errors || stats.low || 'OK'}</strong><small>${stats.errors ? 'lá»—i key' : stats.low ? 'sáº¯p háº¿t' : 'quota á»•n'}</small></span>
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
  if (!token.startsWith('apify_api_')) return alert('Token Apify chÆ°a Ä‘Ãºng Ä‘á»‹nh dáº¡ng apify_api_...');
  await withAdminToast('Äang thÃªm Apify key', async () => {
    await saveApifyToken({ label, token, monthly_quota, active: true });
    document.getElementById('apifyTokenLabel').value = '';
    document.getElementById('apifyTokenValue').value = '';
  }, 'ÄÃ£ thÃªm Apify key', 'KhÃ´ng thÃªm Ä‘Æ°á»£c Apify key');
}

async function toggleApifyToken(id, active) {
  const current = apifyTokens.find(t => t.id === id);
  if (!current) return;
  await withAdminToast(active ? 'Äang báº­t Apify key' : 'Äang táº¯t Apify key', () => (
    saveApifyToken({ id, label: current.label, monthly_quota: current.monthly_quota, active })
  ), active ? 'ÄÃ£ báº­t Apify key' : 'ÄÃ£ táº¯t Apify key', 'KhÃ´ng cáº­p nháº­t Ä‘Æ°á»£c Apify key');
}

async function resetApifyTokenUsage(id) {
  if (!confirm('Reset sá»‘ post Ä‘Ã£ dÃ¹ng thÃ¡ng nÃ y cho key nÃ y?')) return;
  await withAdminToast('Äang reset lÆ°á»£t dÃ¹ng Apify key', async () => {
    const data = await fetchJSON(`/admin/api/facebook-crawl/tokens/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'reset_usage' }),
    });
    apifyTokens = data.tokens || [];
    renderApifyTokens();
  }, 'ÄÃ£ reset lÆ°á»£t dÃ¹ng Apify key', 'KhÃ´ng reset Ä‘Æ°á»£c lÆ°á»£t dÃ¹ng');
}

async function deleteApifyToken(id) {
  if (!confirm('XÃ³a key Apify nÃ y khá»i pool?')) return;
  await withAdminToast('Äang xÃ³a Apify key', async () => {
    const data = await fetchJSON(`/admin/api/facebook-crawl/tokens/${id}`, { method: 'DELETE' });
    apifyTokens = data.tokens || [];
    renderApifyTokens();
  }, 'ÄÃ£ xÃ³a Apify key', 'KhÃ´ng xÃ³a Ä‘Æ°á»£c Apify key');
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
    ['MÃ´i giá»›i báº­t', active, 'Ä‘ang dÃ¹ng'],
    ['Tá»•ng mÃ´i giá»›i', crawlProfiles.length, 'trong cáº¥u hÃ¬nh'],
    ['Listing FB', summary.facebook_listings || 0, 'Ä‘Ã£ xá»­ lÃ½'],
    ['Signal', ops.signal_count || 0, 'Ä‘ang active'],
    ['Tin má»›i gáº§n nháº¥t', last24.new || 0, 'new'],
    ['Nguá»“n lá»—i', sourceErrors.length || 0, 'cáº§n xem'],
    ['Lock káº¹t', blockers.length || 0, 'job'],
    ['Job hiá»‡n táº¡i', summary.active_job ? summary.active_job.status : 'Idle', summary.active_job ? summary.active_job.stage : 'sáºµn sÃ ng'],
  ];
  items.splice(3, 0, [
    'áº¢nh FB thiáº¿u',
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
  const serviceFailureText = [serviceState, serviceResult, serviceExit].filter(Boolean).join(' Â· ');
  const scheduleOk = schedule.installed && !serviceFailed && (schedule.run_time === '21:00' || String(schedule.next_run_time || '').includes('9:00'));
  const healthClass = serviceFailed || lock_blockers.length ? 'danger' : source_errors.length ? 'warn' : 'ok';
  const serviceAlert = serviceFailed ? `
    <div class="crawl-ops-alert danger">
      <strong>Daily crawl láº§n gáº§n nháº¥t bá»‹ lá»—i</strong>
      <span>${esc(serviceFailureText || 'radar-bds-crawl.service failed')} Â· xem log: <code>${esc(serviceLogHint)}</code></span>
    </div>
  ` : '';
  const sourceList = source_errors.length
    ? source_errors.map(x => `
        <li>
          <strong>${esc(x.source || 'unknown')}</strong>
          <span>${esc(x.status || 'error')} Â· fetched=${Number(x.fetched || 0)} Â· new=${Number(x.new || 0)}</span>
          ${x.error_msg ? `<em>${esc(x.error_msg)}</em>` : ''}
        </li>
      `).join('')
    : `<li><strong>OK</strong><span>KhÃ´ng cÃ³ lá»—i nguá»“n trong cÃ¡c run gáº§n Ä‘Ã¢y.</span></li>`;
  const lockList = lock_blockers.length
    ? lock_blockers.map(x => `
        <li>
          <strong>${esc(x.name || 'lock')}</strong>
          <span>${esc(x.state || 'locked')}${x.pid ? ` Â· pid=${esc(x.pid)}` : ''}</span>
          ${x.error ? `<em>${esc(x.error)}</em>` : ''}
        </li>
      `).join('')
    : `<li><strong>OK</strong><span>KhÃ´ng cÃ³ crawl/reprocess lock Ä‘ang cháº·n.</span></li>`;

  el.innerHTML = `
    <div class="crawl-ops-head">
      <div>
        <small>Daily Automation</small>
        <strong>${esc(schedule.task_name || scheduleName)}</strong>
      </div>
      <span class="ops-pill ${healthClass}">${lock_blockers.length ? 'Lock Ä‘ang káº¹t' : source_errors.length ? 'Cáº§n xem lá»—i nguá»“n' : 'Äang á»•n Ä‘á»‹nh'}</span>
    </div>
    <div class="crawl-ops-grid">
      <div class="crawl-ops-card ${scheduleOk ? 'ok' : 'warn'}">
        <small>Lich daily</small>
        <strong>${schedule.installed ? (schedule.run_time || shortDate(schedule.next_run_time) || 'ÄÃ£ cÃ i') : 'ChÆ°a cÃ i'}</strong>
        <span>${schedule.installed ? `Next: ${esc(schedule.next_run_time || 'chÆ°a rÃµ')}` : `Cáº§n cÃ i ${esc(scheduleName)} lÃºc 21:00`}</span>
        ${schedule.error ? `<em>${esc(schedule.error)}</em>` : ''}
      </div>
      <div class="crawl-ops-card">
        <small>Lan chay gan nhat</small>
        <strong>${last.source ? `${esc(last.source)} Â· ${esc(last.status || '')}` : 'ChÆ°a cÃ³ run'}</strong>
        <span>${last.started_at ? `${esc(shortDate(last.started_at))} Â· new=${Number(last.new || 0)} Â· fetched=${Number(last.fetched || 0)}` : 'ChÆ°a cÃ³ crawl_runs'}</span>
      </div>
      <div class="crawl-ops-card">
        <small>Batch gan nhat</small>
        <strong>${Number(last24.new || 0).toLocaleString('vi-VN')} tin má»›i</strong>
        <span>${Number(last24.runs || 0)} runs Â· fetched=${Number(last24.fetched || 0).toLocaleString('vi-VN')} Â· skipped=${Number(last24.skipped || 0).toLocaleString('vi-VN')}</span>
      </div>
      <div class="crawl-ops-card ${missingImageRefs ? 'warn' : 'ok'}">
        <small>áº¢nh Facebook cÃ²n thiáº¿u</small>
        <strong>${missingImageRefs.toLocaleString('vi-VN')} áº£nh</strong>
        <span>${Number(missingImages.listings_with_missing_images || 0).toLocaleString('vi-VN')} listing Â· ${missingPct.toLocaleString('vi-VN')}% tá»•ng áº£nh FB</span>
      </div>
    </div>
    <div class="crawl-ops-lists">
      <div>
        <h3>Lá»—i nguá»“n gáº§n Ä‘Ã¢y</h3>
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
    if (pill) pill.textContent = 'Daily crawl lá»—i';
    const head = el.querySelector('.crawl-ops-head');
    if (head) head.insertAdjacentHTML('afterend', serviceAlert);
    const scheduleCard = el.querySelector('.crawl-ops-card');
    if (scheduleCard) {
      scheduleCard.classList.remove('ok', 'warn');
      scheduleCard.classList.add('danger');
      const strong = scheduleCard.querySelector('strong');
      const span = scheduleCard.querySelector('span');
      if (strong) strong.textContent = 'Láº§n cháº¡y gáº§n nháº¥t lá»—i';
      if (span) span.textContent = `${serviceFailureText || 'service failed'} Â· log: ${serviceLogHint}`;
    }
  }
}

function qualityFlagLabel(flag) {
  const labels = {
    parsed_discount_as_price: 'Nháº§m giáº£m giÃ¡ thÃ nh giÃ¡ bÃ¡n',
    down_payment_as_price: 'Nháº§m cá»c thÃ nh giÃ¡ bÃ¡n',
    too_low_absolute_price: 'GiÃ¡ tuyá»‡t Ä‘á»‘i quÃ¡ tháº¥p',
    large_lot_model_risk: 'Rá»§i ro lÃ´ lá»›n',
    area_dimension_conflict: 'MÃ¢u thuáº«n DT/kÃ­ch thÆ°á»›c',
    source_category_conflict: 'Sai loáº¡i hÃ¬nh nguá»“n',
    multi_lot_listing: 'Tin nhiá»u lÃ´',
    guland_weak_signal: 'Guland signal yáº¿u',
    guland_user_facing_risk: 'Guland cáº§n kiá»ƒm tra',
    old_guland_post: 'Guland bÃ i cÅ©',
    extreme_guland_ppm2: 'Guland giÃ¡/mÂ² báº¥t thÆ°á»ng',
    suspicious_bait: 'Nghi má»“i giÃ¡',
    guland_cluster_flood: 'Cá»¥m Guland trÃ¹ng',
    review_bad_valuation: 'Review Ä‘á»‹nh giÃ¡ sai',
    review_bad_extraction: 'Review bÃ³c tÃ¡ch sai',
    source_quality_recheck: 'Cáº§n QC nguá»“n',
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
  const kpis = [
    {
      cls: missingRefs ? 'warn' : 'ok',
      label: 'áº¢nh thiáº¿u',
      value: missingRefs.toLocaleString('vi-VN'),
      note: `${missingListings.toLocaleString('vi-VN')} listing Â· ${Number(images.missing_pct || 0).toLocaleString('vi-VN')}% tá»•ng áº£nh`
    },
    {
      cls: !activeTokens || remaining <= 100 ? 'warn' : 'ok',
      label: 'Apify cÃ²n láº¡i',
      value: activeTokens ? remaining.toLocaleString('vi-VN') : 'ChÆ°a cÃ³ key',
      note: activeTokens ? `${activeTokens} key báº­t Â· quota ${quota.toLocaleString('vi-VN')}/thÃ¡ng` : 'Crawler sáº½ cáº§n APIFY_TOKEN env hoáº·c key pool'
    },
    {
      cls: crawlProblemCount ? 'danger' : 'ok',
      label: 'Nguá»“n crawl lá»—i',
      value: sourceErrors.length.toLocaleString('vi-VN'),
      note: lockBlockers.length ? `${lockBlockers.length} lock Ä‘ang cháº·n` : `Run gáº§n nháº¥t: ${shortDate(crawl.last_run?.started_at)}`
    },
    {
      cls: suppressedTotal ? 'warn' : 'ok',
      label: 'Signal bá»‹ suppress',
      value: suppressedTotal.toLocaleString('vi-VN'),
      note: sources.length ? sources.map(x => `${SOURCE_NAMES[x.source] || x.source}: ${Number(x.count || 0).toLocaleString('vi-VN')}`).join(' Â· ') : 'KhÃ´ng cÃ³ signal bá»‹ cháº·n'
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
              <span>${t.active ? 'Äang báº­t' : 'ÄÃ£ táº¯t'} Â· ${esc(t.token_mask || '')}</span>
              <div class="quality-token-bar"><i style="width:${pct}%"></i></div>
            </div>
            <b class="${tRemaining <= 100 ? 'warn' : ''}">${tRemaining.toLocaleString('vi-VN')}</b>
            ${t.last_error ? `<em>${esc(t.last_error)}</em>` : ''}
          </li>
        `;
      }).join('')
    : `<li><div><strong>ChÆ°a cÃ³ Apify key trong pool</strong><span>ThÃªm key á»Ÿ tab Facebook Crawl Ä‘á»ƒ theo dÃµi quota rÃµ hÆ¡n.</span></div></li>`;
  const sourceList = sourceErrors.length
    ? sourceErrors.map(x => `
        <li>
          <div>
            <strong>${esc(SOURCE_NAMES[x.source] || x.source || 'unknown')}</strong>
            <span>${esc(x.status || 'error')} Â· fetched=${Number(x.fetched || 0).toLocaleString('vi-VN')} Â· new=${Number(x.new || 0).toLocaleString('vi-VN')}</span>
          </div>
          ${x.error_msg ? `<em>${esc(x.error_msg)}</em>` : ''}
        </li>
      `).join('')
    : `<li><div><strong>KhÃ´ng cÃ³ lá»—i nguá»“n gáº§n Ä‘Ã¢y</strong><span>CÃ¡c run gáº§n nháº¥t khÃ´ng bÃ¡o error hoáº·c fetched=0.</span></div></li>`;
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
    : `<li><div><strong>KhÃ´ng cÃ³ quality flag Ä‘ang cháº·n signal</strong><span>Signal model-cheap hiá»‡n khÃ´ng bá»‹ suppress bá»Ÿi source quality.</span></div></li>`;

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
        <h3>Apify quota</h3>
        ${apify.error ? `<div class="quality-mini-alert danger">${esc(apify.error)}</div>` : ''}
        <ul class="quality-list">${tokenList}</ul>
      </article>
      <article class="surface quality-detail-card">
        <h3>Lá»—i crawl theo nguá»“n</h3>
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

function renderCrawlProfiles() {
  const body = document.getElementById('crawlProfileRows');
  if (!body) return;
  if (!crawlProfiles.length) {
    body.innerHTML = `<tr><td colspan="9"><div class="empty">ChÆ°a cÃ³ mÃ´i giá»›i Facebook.</div></td></tr>`;
    return;
  }
  body.innerHTML = crawlProfiles.map(p => `
    <tr data-url="${esc(p.url)}">
      <td data-label="Báº­t">
        <label class="crawl-switch">
          <input type="checkbox" data-crawl-field="active" ${p.active !== false ? 'checked' : ''}>
          <span></span>
        </label>
      </td>
      <td data-label="MÃ´i giá»›i">
        <div class="crawl-broker-cell">
          <input class="crawl-inline-input crawl-broker-name" data-crawl-field="broker_name" value="${esc(p.broker_name || '')}" placeholder="TÃªn mÃ´i giá»›i">
          <input class="crawl-inline-input crawl-url" value="${esc(p.url)}" readonly>
          <input class="crawl-inline-input crawl-city" data-crawl-field="city" value="${esc(p.city || '')}" placeholder="Khu vá»±c">
        </div>
      </td>
      <td data-label="Daily"><input class="crawl-small-input" type="number" min="1" max="500" data-crawl-field="daily_limit" value="${Number(p.daily_limit || p.tier || 20)}"></td>
      <td data-label="Range"><input class="crawl-small-input" type="number" min="1" max="60" data-crawl-field="range_days" value="${Number(p.range_days || 7)}"> <small>ngÃ y</small></td>
      <td data-label="Nhá»‹p Ä‘Äƒng">${crawlActivityHtml(p.activity || {})}</td>
      <td data-label="Gá»£i Ã½">${crawlRecommendationHtml(p)}</td>
      <td data-label="Äá»™ sáº¡ch">${crawlQualityHtml(p.data_quality || {})}</td>
      <td data-label="Dá»¯ liá»‡u">
        <div class="crawl-data-meta">
          <strong>${Number(p.raw_count || 0)}</strong>
          <small>${esc(shortDate(p.latest_crawled_at))}</small>
        </div>
      </td>
      <td data-label="Cháº¡y" class="crawl-row-actions">
        <div class="crawl-action-grid">
          <button class="icon-btn primary-lite" title="Crawl láº§n Ä‘áº§u" onclick="runCrawlForUrl('${esc(p.url)}', 'first')">Láº§n 1</button>
          <button class="icon-btn" title="Crawl daily" onclick="runCrawlForUrl('${esc(p.url)}', 'daily')">Daily</button>
          <button class="icon-btn" title="Crawl theo range days" onclick="runCrawlForUrl('${esc(p.url)}', 'range')">Range</button>
          <button class="icon-btn danger" title="XÃ³a mÃ´i giá»›i" onclick="removeCrawlProfile('${esc(p.url)}')">XÃ³a</button>
        </div>
      </td>
    </tr>
  `).join('');
}

function crawlActivityHtml(activity) {
  const tier = activity.cadence_tier || 'muted';
  const label = activity.cadence_label || 'ChÆ°a cÃ³ dá»¯ liá»‡u';
  return `
    <div class="broker-insight">
      <span class="broker-pill ${esc(tier)}">${esc(label)}</span>
      <strong>${Number(activity.avg_posts_per_active_day_14d || 0).toFixed(1)} bÃ i/ngÃ y active</strong>
      <small>${Number(activity.posts_30d || 0)} bÃ i / 30 ngÃ y Â· ${Number(activity.active_days_30d || 0)} ngÃ y cÃ³ Ä‘Äƒng</small>
    </div>
  `;
}

function crawlRecommendationHtml(profile) {
  const activity = profile.activity || {};
  const daily = Number(activity.recommended_daily_limit || profile.daily_limit || profile.tier || 30);
  const weekly = Number(activity.recommended_weekly_limit || daily * 7);
  return `
    <div class="broker-rec">
      <strong>${daily}/ngÃ y</strong>
      <small>${weekly}/tuáº§n</small>
      <button class="broker-apply-btn" type="button" onclick="applyCrawlRecommendedDailyLimit('${esc(profile.url)}', ${daily})">Ãp dá»¥ng</button>
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
        <strong>${esc(quality.label || 'ChÆ°a Ä‘á»§ máº«u')}</strong>
        <small>${Number(quality.sample_size || 0)} máº«u Â· giÃ¡ ${Number(quality.price_pct || 0)}% Â· DT ${Number(quality.area_pct || 0)}%</small>
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
  showAdminToast('ÄÃ£ Ã¡p dá»¥ng quota gá»£i Ã½ cho mÃ´i giá»›i', 'success');
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
  const city = document.getElementById('crawlCity').value.trim() || 'BÃ¬nh DÆ°Æ¡ng';
  if (!url.startsWith('https://www.facebook.com/')) return alert('URL Facebook chÆ°a há»£p lá»‡.');
  if (crawlProfiles.some(p => p.url === url)) return alert('MÃ´i giá»›i nÃ y Ä‘Ã£ cÃ³ trong danh sÃ¡ch.');
  crawlProfiles.push({ broker_name: broker, url, city, active: true, daily_limit: 30, tier: 30, range_days: 7 });
  document.getElementById('crawlBrokerName').value = '';
  document.getElementById('crawlProfileUrl').value = '';
  renderCrawlProfiles();
  renderCrawlRunSelect();
  showAdminToast('ÄÃ£ thÃªm mÃ´i giá»›i vÃ o danh sÃ¡ch táº¡m', 'success');
}

function removeCrawlProfile(url) {
  if (!confirm('XÃ³a mÃ´i giá»›i nÃ y khá»i danh sÃ¡ch crawl?')) return;
  crawlProfiles = crawlProfiles.filter(p => p.url !== url);
  renderCrawlProfiles();
  renderCrawlRunSelect();
  showAdminToast('ÄÃ£ xÃ³a mÃ´i giá»›i khá»i danh sÃ¡ch táº¡m', 'success');
}

async function saveCrawlProfiles() {
  await withAdminToast('Äang lÆ°u danh sÃ¡ch mÃ´i giá»›i', async () => {
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
  }, 'ÄÃ£ lÆ°u danh sÃ¡ch mÃ´i giá»›i', 'KhÃ´ng lÆ°u Ä‘Æ°á»£c danh sÃ¡ch');
}

function setCrawlMode(mode) {
  crawlMode = mode;
  document.querySelectorAll('[data-crawl-mode]').forEach(btn => btn.classList.toggle('active', btn.dataset.crawlMode === mode));
  syncCrawlRunInputs();
}

async function runCrawlForUrl(url, mode = crawlMode) {
  await withAdminToast('Äang táº¡o job crawl', async () => {
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
  }, 'ÄÃ£ táº¡o job crawl, Ä‘ang theo dÃµi tiáº¿n trÃ¬nh', 'KhÃ´ng táº¡o Ä‘Æ°á»£c job crawl');
}

async function runSelectedCrawl() {
  const url = document.getElementById('crawlRunProfile')?.value;
  if (!url) return alert('Chá»n mÃ´i giá»›i cáº§n crawl.');
  await runCrawlForUrl(url, crawlMode);
}

async function runCrawlMaintenance(action) {
  const label = action === 'valuation_only' ? 'valuation-only' : 'reprocess';
  await withAdminToast(`Dang tao job ${label}`, async () => {
    const data = await fetchJSON('/admin/api/facebook-crawl/maintenance', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action }),
    });
    activeCrawlJobId = data.job.id;
    renderCrawlJob(data.job);
    startCrawlPolling(activeCrawlJobId);
  }, `Da tao job ${label}`, `Khong tao duoc job ${label}`);
}

function renderCrawlJob(job) {
  const status = document.getElementById('crawlJobStatus');
  const meta = document.getElementById('crawlJobMeta');
  const log = document.getElementById('crawlJobLog');
  const pct = Math.max(0, Math.min(100, Number(job.progress_pct || 0)));
  const progressLabel = job.progress_label || job.stage || 'Äang chá»';
  const progressPct = document.getElementById('crawlProgressPct');
  const progressFill = document.getElementById('crawlProgressFill');
  const progressText = document.getElementById('crawlProgressLabel');
  if (status) {
    status.textContent = `${job.status || 'idle'} Â· ${job.stage || '-'}`;
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
      ${job.stats?.reprocess ? `<span>Reprocess new ${Number(reprocess.new || 0)} Â· updated ${Number(reprocess.updated || 0)} Â· skipped ${Number(reprocess.skipped || 0)}</span>` : ''}
      ${valuation.total !== undefined ? `<span>Valuation total ${Number(valuation.total || 0)} Â· signals ${Number(valuation.signals || 0)} Â· outliers ${Number(valuation.outliers || 0)}</span>` : ''}
      ${job.error ? `<span class="crawl-error">${esc(job.error)}</span>` : ''}
    `;
  }
  if (meta && !job.maintenance_action) {
    meta.innerHTML = `
      <strong>${esc(job.broker_name || job.profile_url || '')}</strong>
      <span>${esc(job.mode || '')} Â· limit ${esc(job.limit || '')}${job.mode === 'range' ? ' Â· ' + esc(job.days || '') + ' ngÃ y' : ''}</span>
      <span>Fetched ${Number(crawl.fetched || 0)} Â· Imported ${Number(crawl.inserted || 0)} Â· Refreshed ${Number(crawl.refreshed_images || 0)} Â· Skipped ${Number(crawl.skipped || 0)}</span>
      <span>Irrelevant ${Number(crawl.irrelevant || 0)} Â· Out area ${Number(crawl.out_of_area || 0)} Â· Range filter ${Number(crawl.range_filtered || 0)}${downloaded !== undefined ? ' Â· áº¢nh ' + Number(downloaded || 0) : ''}</span>
      ${job.stats?.reprocess ? `<span>Reprocess new ${Number(reprocess.new || 0)} Â· updated ${Number(reprocess.updated || 0)} Â· skipped ${Number(reprocess.skipped || 0)}</span>` : ''}
      ${job.error ? `<span class="crawl-error">${esc(job.error)}</span>` : ''}
    `;
  }
  if (log) log.textContent = (job.logs || []).join('\n') || 'Job Ä‘ang chá» báº¯t Ä‘áº§u.';
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
    ['Total Users', s.total || 0, 'táº¥t cáº£'],
    ['VIP', s.vip || 0, 'Ä‘ang tráº£ phÃ­'],
    ['Free', s.free || 0, 'miá»…n phÃ­'],
    ['Admin', s.admin || 0, 'ná»™i bá»™'],
    ['Banned', s.banned || 0, 'Ä‘Ã£ cháº·n'],
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
    body.innerHTML = `<tr><td colspan="10"><div class="empty">KhÃ´ng cÃ³ user phÃ¹ há»£p.</div></td></tr>`;
    return;
  }
  body.innerHTML = items.map(u => {
    const tierBadgeColor = u.effective_tier === 'vip' ? 'var(--green)' : u.effective_tier === 'admin' ? 'var(--orange)' : 'var(--ink-muted)';
    const banned = u.is_banned ? `<span style="color:var(--red)">BANNED</span>` : '';
    const vipExp = u.vip_expires_at ? shortDate(u.vip_expires_at) : '-';
    const expired = u.tier === 'vip' && u.effective_tier !== 'vip' ? ' <small style="color:var(--red)">(háº¿t háº¡n)</small>' : '';
    const tg = u.telegram_linked ? 'âœ“' : '-';
    return `
      <tr>
        <td data-label="ID">#${u.id}</td>
        <td data-label="TÃ i khoáº£n"><strong>${esc(u.identifier || '-')}</strong><br><small>${esc(u.identifier_type || '')}</small></td>
        <td data-label="TÃªn">${esc(u.display_name || '-')}</td>
        <td data-label="Tier"><strong style="color:${tierBadgeColor}">${esc((u.effective_tier || u.tier || '').toUpperCase())}</strong>${expired} ${banned}</td>
        <td data-label="VIP háº¿t háº¡n">${vipExp}</td>
        <td data-label="Telegram">${tg}</td>
        <td data-label="Watchlist">${Number(u.watchlist_count || 0)}</td>
        <td data-label="ÄÄƒng kÃ½">${shortDate(u.created_at)}</td>
        <td data-label="Last login">${shortDate(u.last_login_at)}</td>
        <td data-label="HÃ nh Ä‘á»™ng">
          <button class="icon-btn" onclick="grantVip(${u.id}, 30)">+30d VIP</button>
          <button class="icon-btn" onclick="grantVip(${u.id}, 7)">+7d</button>
          <button class="icon-btn" onclick="revokeVip(${u.id})">Revoke</button>
          <button class="icon-btn" onclick="toggleBan(${u.id}, ${u.is_banned ? 0 : 1})">${u.is_banned ? 'Unban' : 'Ban'}</button>
          <button class="icon-btn danger" onclick="deleteUser(${u.id})">XÃ³a</button>
        </td>
      </tr>
    `;
  }).join('');
}

async function grantVip(userId, days) {
  const customDays = prompt(`Cáº¥p VIP bao nhiÃªu ngÃ y? (default ${days})`, String(days));
  if (customDays === null) return;
  const n = parseInt(customDays, 10);
  if (!n || n <= 0) return alert('Sá»‘ ngÃ y khÃ´ng há»£p lá»‡');
  try {
    await fetchJSON(`/admin/api/users/${userId}/grant-vip`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ days: n }),
    });
    loadUsers();
  } catch (e) { alert('Lá»—i: ' + (e.message || e)); }
}

async function revokeVip(userId) {
  if (!confirm(`Thu há»“i VIP cá»§a user #${userId}?`)) return;
  try {
    await fetchJSON(`/admin/api/users/${userId}/revoke`, { method: 'POST' });
    loadUsers();
  } catch (e) { alert('Lá»—i: ' + (e.message || e)); }
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
  } catch (e) { alert('Lá»—i: ' + (e.message || e)); }
}

async function deleteUser(userId) {
  if (!confirm(`XÃ³a user #${userId}? Session, watchlist vÃ  log thÃ´ng bÃ¡o sáº½ bá»‹ xÃ³a; lead cÅ© chá»‰ bá» liÃªn káº¿t user.`)) return;
  await withAdminToast(
    'Äang xÃ³a ngÆ°á»i dÃ¹ng',
    async () => {
      await fetchJSON(`/admin/api/users/${userId}`, { method: 'DELETE', silent: true });
      await loadUsers();
    },
    'ÄÃ£ xÃ³a ngÆ°á»i dÃ¹ng',
    'KhÃ´ng xÃ³a Ä‘Æ°á»£c ngÆ°á»i dÃ¹ng'
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
    ['Total Leads', summary.total || 0, 'táº¥t cáº£'],
    ['Won Deals', summary.deposit || 0, 'Ä‘Ã£ chá»‘t cá»c'],
    ['Pending', summary.new || 0, 'cáº§n xá»­ lÃ½'],
    ['Äi xem Ä‘áº¥t', summary.viewing || 0, 'Ä‘ang háº¹n'],
    ['Há»§y', summary.cancelled || 0, 'Ä‘Ã£ há»§y']
  ];
  document.getElementById('leadStats').innerHTML = stats.map((s, idx) => `
    <div class="stat-card">
      <small>${esc(s[0])}</small>
      <div><strong style="color:${idx === 1 ? 'var(--green)' : idx === 2 ? 'var(--orange)' : idx === 4 ? 'var(--red)' : 'var(--ink)'}">${s[1]}</strong><span>${esc(s[2])}</span></div>
    </div>
  `).join('');
}

function renderLeadRows(items) {
  document.getElementById('leadCountMeta').textContent = `Hiá»ƒn thá»‹ ${items.length} lead`;
  const body = document.getElementById('leadRows');
  if (!items.length) {
    body.innerHTML = `<tr><td colspan="5"><div class="empty">ChÆ°a cÃ³ lead phÃ¹ há»£p.</div></td></tr>`;
    return;
  }
  body.innerHTML = items.map(x => {
    const st = STATUS[x.status] || STATUS.new;
    const listingLabel = x.listing_title ? `#${x.listing_id} Â· ${x.listing_title}` : (x.listing_id ? `Deal #${x.listing_id}` : (x.listing_url || '-'));
    const link = x.listing_id ? `/listing/${x.listing_id}` : (x.listing_url || '#');
    return `
      <tr>
        <td data-label="NgÃ y nháº­n">${shortDate(x.created_at)}</td>
        <td data-label="Sá»‘ Zalo" class="phone">${esc(x.zalo_phone || '-')}</td>
        <td data-label="LÃ´ Ä‘áº¥t"><a class="deal-pill" href="${esc(link)}" target="_blank">${esc(listingLabel)}</a></td>
        <td data-label="Tráº¡ng thÃ¡i">
          <select class="status-select ${st.cls}" data-lead="${x.id}">
            ${STATUS_KEYS.map(k => `<option value="${k}" ${x.status === k ? 'selected' : ''}>${STATUS[k].label}</option>`).join('')}
          </select>
        </td>
        <td data-label="Thao tÃ¡c">
          <button class="icon-btn" onclick="window.open('${esc(link)}','_blank')">Má»Ÿ</button>
          <button class="icon-btn danger" onclick="deleteLead(${x.id})">XÃ³a</button>
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
  if (!confirm(`XÃ³a lead #${leadId} khá»i CRM?`)) return;
  await withAdminToast(
    'Äang xÃ³a lead',
    async () => {
      await fetchJSON(`/admin/api/leads/${leadId}`, { method: 'DELETE', silent: true });
      await loadLeads();
    },
    'ÄÃ£ xÃ³a lead',
    'KhÃ´ng xÃ³a Ä‘Æ°á»£c lead'
  );
}

function exportLeads() {
  const q = leadQuery();
  const clean = new URL(`/admin/api/leads/export.csv${q ? '?' + q : ''}`, window.location.href);
  clean.username = '';
  clean.password = '';
  showAdminToast('Äang táº£i file CSV leads', 'success', { delay: 1800 });
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
  root.innerHTML = `<div class="empty">Äang táº£i queue kiá»ƒm dá»‹ch...</div>`;
  const p = new URLSearchParams({ queue, limit: '60', sort: 'default' });
  const data = await fetchJSON('/admin/api/data-quality/items?' + p.toString());
  const items = data.items || [];
  if (!items.length) {
    root.innerHTML = `<div class="empty">KhÃ´ng cÃ³ má»¥c nÃ o trong queue nÃ y.</div>`;
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
    root.innerHTML = `<div class="empty">ChÆ°a cÃ³ item háº¡ táº§ng nÃ o.</div>`;
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
        <button class="secondary-btn" onclick="editInfra(${x.id})">Sá»­a</button>
        <button class="secondary-btn" onclick="deactivateInfra(${x.id})">áº¨n</button>
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
    window.alert('Cáº§n nháº­p tiÃªu Ä‘á».');
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
    root.innerHTML = `<div class="empty">KhÃ´ng cÃ²n cáº·p tin nghi trÃ¹ng cáº§n xá»­ lÃ½.</div>`;
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
  return `${(price * 1000 / areaVal).toLocaleString('vi-VN', { maximumFractionDigits: 1 })} tr/mÂ²`;
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
    ? `<a class="dup-open-source" href="${esc(d.originalUrl)}" target="_blank" rel="noopener">Má»Ÿ tin gá»‘c</a>`
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
  const role = isCanon ? 'Tin gá»‘c Ä‘á»ƒ so sÃ¡nh' : 'Tin nghi trÃ¹ng';
  const roleHint = isCanon ? 'Náº¿u gá»™p, há»‡ thá»‘ng giá»¯ tin nÃ y lÃ m deal chÃ­nh.' : 'Tin nÃ y sáº½ Ä‘Æ°á»£c áº©n náº¿u admin xÃ¡c nháº­n gá»™p.';
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
          <a class="ad-title" href="${esc(d.detail)}" target="_blank" rel="noopener">${esc(d.title || 'KhÃ´ng cÃ³ tiÃªu Ä‘á»')}</a>
          <div class="dup-facts">
            ${dupFact('GiÃ¡', money(d.price), 'price')}
            ${dupFact('ÄÆ¡n giÃ¡', dupMoneyPerM2(d.price, d.area))}
            ${dupFact('DT', dupLotSize(d))}
            ${dupFact('Khu vá»±c', d.ward)}
            ${dupFact('ÄÆ°á»ng', d.road)}
            ${dupFact('Loáº¡i', PTYPES[d.prop] || d.prop)}
            ${dupFact('Nguá»“n', sourceName)}
            ${dupFact('MÃ£ nguá»“n', d.sourceId)}
            ${dupFact('NgÃ y', shortDate(d.dt))}
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
    ? 'Thiáº¿u giÃ¡'
    : Math.abs(priceA - priceB) / Math.max(priceA, priceB) < 0.01
      ? 'Gáº§n nhÆ° báº±ng nhau'
      : `${priceA > priceB ? 'Tin nghi trÃ¹ng cao hÆ¡n' : 'Tin gá»‘c cao hÆ¡n'} ${(Math.abs(priceA - priceB) / Math.max(priceA, priceB) * 100).toFixed(1)}%`;
  const areaNote = (!areaA || !areaB)
    ? 'Thiáº¿u diá»‡n tÃ­ch'
    : `Lá»‡ch ${Math.abs(areaA - areaB).toLocaleString('vi-VN', { maximumFractionDigits: 1 })} mÂ²`;
  const roadNote = (leftData.road && rightData.road)
    ? (leftData.road === rightData.road ? 'CÃ¹ng tÃªn Ä‘Æ°á»ng' : 'KhÃ¡c tÃªn Ä‘Æ°á»ng')
    : 'Thiáº¿u tÃªn Ä‘Æ°á»ng';
  const rows = [
    ['GiÃ¡ rao', money(leftData.price), money(rightData.price), priceNote],
    ['ÄÆ¡n giÃ¡', dupMoneyPerM2(leftData.price, leftData.area), dupMoneyPerM2(rightData.price, rightData.area), 'So theo tr/mÂ²'],
    ['Diá»‡n tÃ­ch', dupLotSize(leftData), dupLotSize(rightData), areaNote],
    ['Khu vá»±c', leftData.ward || '-', rightData.ward || '-', leftData.ward === rightData.ward ? 'CÃ¹ng khu' : 'Cáº§n soi vá»‹ trÃ­'],
    ['TÃªn Ä‘Æ°á»ng', leftData.road || '-', rightData.road || '-', roadNote],
    ['Loáº¡i hÃ¬nh', PTYPES[leftData.prop] || leftData.prop || '-', PTYPES[rightData.prop] || rightData.prop || '-', leftData.prop === rightData.prop ? 'TrÃ¹ng loáº¡i' : 'Cáº§n xem láº¡i'],
    ['NgÃ y Ä‘Äƒng', shortDate(leftData.dt), shortDate(rightData.dt), 'Tin gá»‘c lÃ  má»‘c Ä‘á» xuáº¥t giá»¯']
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
  const title = x.suspected_duplicate ? 'Tin nghi trÃ¹ng cáº§n admin review' : 'Tin trÃ¹ng cáº§n rÃ  láº¡i';
  const subtitle = x.suspected_duplicate
    ? 'Há»‡ thá»‘ng tháº¥y giá»‘ng cÃ¹ng lÃ´ nhÆ°ng chÆ°a Ä‘á»§ cháº¯c Ä‘á»ƒ tá»± gá»™p. Má»Ÿ tin gá»‘c, so ná»™i dung vÃ  quyáº¿t Ä‘á»‹nh giá»¯/gá»™p.'
    : 'Cáº·p nÃ y Ä‘Ã£ Ä‘Æ°á»£c Ä‘Ã¡nh dáº¥u trÃ¹ng nhÆ°ng cÃ³ Ä‘iá»ƒm chÆ°a cháº¯c, cáº§n admin xÃ¡c nháº­n trÆ°á»›c khi khÃ³a dá»¯ liá»‡u.';
  const reasons = (x.qc_reasons || []).length
    ? `<div class="dup-review-reasons"><b>LÃ½ do vÃ o hÃ ng chá»</b>${x.qc_reasons.map(r => `<span>${esc(r)}</span>`).join('')}</div>`
    : '';
  return `
    <article class="dup-card">
      <div class="dup-head">
        <div>
          <div class="dup-kicker">${title} <span class="deal-pill">DUP-${x.id}</span></div>
          <p>${subtitle}</p>
        </div>
        <div class="dup-score">
          <span>Äá»™ giá»‘ng</span>
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
          <strong>So sÃ¡nh nhanh</strong>
          <span>Æ¯u tiÃªn xem giÃ¡, diá»‡n tÃ­ch, tÃªn Ä‘Æ°á»ng vÃ  ná»™i dung mÃ´ táº£ trÆ°á»›c khi báº¥m gá»™p.</span>
        </div>
        <div class="dup-summary-grid">
          <div class="dup-summary-row header">
            <strong>TiÃªu chÃ­</strong>
            <span>Tin nghi trÃ¹ng</span>
            <span>Tin gá»‘c</span>
            <em>Káº¿t luáº­n</em>
          </div>
          ${dupCompareRows(x)}
        </div>
      </div>
      <div class="dup-actions">
        <button class="primary-btn merge-btn" onclick="mergeDup(${x.id}, ${x.duplicate_of_id})">
          <strong>Gá»™p vÃ o tin gá»‘c</strong>
          <span class="dup-decision-copy">áº¨n tin nghi trÃ¹ng, giá»¯ tin gá»‘c lÃ m deal chÃ­nh</span>
        </button>
        <button class="secondary-btn split-btn" onclick="splitDup(${x.id}, ${x.duplicate_of_id})">
          <strong>KhÃ¡c lÃ´</strong>
          <span class="dup-decision-copy">Giá»¯ cáº£ hai tin vÃ  khÃ´ng há»i láº¡i cáº·p nÃ y</span>
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
  const note = window.prompt('LÃ½ do tÃ¡ch lÃ´?', 'not_same_lot') || 'not_same_lot';
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
    root.innerHTML = `<div class="empty">ChÆ°a cÃ³ SÄT trong blacklist.</div>`;
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
let _trnAllWards = [];     // má»i phÆ°á»ng cÃ³ signal (ká»ƒ cáº£ ngoÃ i CITY_MAP)
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
  wardSel.innerHTML = '<option value="">Táº¥t cáº£ phÆ°á»ng</option>' +
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

    // Badge: luÃ´n "chÆ°a review / tá»•ng signal"
    const badge = document.getElementById('trainingCount');
    if (badge) badge.textContent = `${data.pending || 0}/${data.total || 0}`;
    const meta = document.getElementById('trainingMeta');
    const shown = append ? (_trnOffset + items.length) : items.length;
    const queueLabel = data.queue_label || 'Review má»›i';
    if (meta) meta.textContent = `Â· ${queueLabel} Â· ${data.pending || 0} má»¥c / ${data.total || 0} signal Â· hiá»ƒn thá»‹ ${shown}`;

    // City + ward dropdowns (populate once)
    if (!_trnWardsLoaded && (data.ward_cities || data.wards)) {
      _trnWardCities = data.ward_cities || {};
      _trnAllWards = (data.wards || []).slice();
      const citySel = document.getElementById('trnCity');
      if (citySel) {
        citySel.innerHTML = '<option value="">Táº¥t cáº£ TP</option>' +
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
      root.innerHTML = `<div class="empty">KhÃ´ng cÃ³ signal nÃ o khá»›p bá»™ lá»c.</div>`;
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

// Sentinel cuá»‘i lÆ°á»›i: scroll tá»›i â†’ tá»± load thÃªm (infinite scroll)
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
  if (btn) btn.textContent = expanded ? 'â–² Thu gá»n' : 'â–¼ Má»Ÿ review';
}

function trnToggleDesc(id) {
  const wrap = document.querySelector(`.train-desc-wrap[data-desc-wrap="${id}"]`);
  const btn = document.querySelector(`.train-desc-toggle[data-desc-toggle="${id}"]`);
  if (!wrap) return;
  const expanded = wrap.classList.toggle('expanded');
  if (btn) btn.textContent = expanded ? 'Thu gá»n' : 'Xem thÃªm';
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
    btn.textContent = wrap.classList.contains('expanded') ? 'Thu gá»n' : 'Xem thÃªm';
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
  const missing = (explain.missing_fields || []).length ? explain.missing_fields.join(', ') : 'khÃ´ng';
  const nImg = (x.images && x.images.length) || 0;
  const desc = (x.description || '').trim();
  const actualPpm2 = x.actual_ppm2 || x.price_per_m2 || '';
  const fairPpm2 = x.fair_ppm2 || '';
  const sourceFlags = (x.source_quality_flags || '').split(',').filter(Boolean);
  const fairTitle = x.fair_ty
    ? `(Fair Value: ${money(x.fair_ty)}${fairPpm2 ? ` Â· ${ppm2(fairPpm2)}` : ''})`
    : '';
  return `
    <article class="training-card" data-id="${x.id}">
      <div class="train-img-wrap">
        <img class="train-img" src="${esc(x.image || PLACEHOLDER)}" onerror="this.src=PLACEHOLDER" alt="">
        <div class="mos-chip">BiÃªn an toÃ n ${Math.round(x.mos_pct || 0)}%</div>
        ${nImg ? `<button class="train-gallery-btn" onclick="openTrnGallery(${x.id})">ðŸ–¼ï¸ áº¢nh (${nImg})</button>` : ''}
      </div>
      <div class="train-body">
        <div class="train-title">
          <a href="${esc(x.detail_url)}" target="_blank">${esc(x.ward || 'Unknown')}</a>
          <span>TD-${x.id}</span>
        </div>
        <div class="train-lines">
          <div><strong>${esc(x.title || 'KhÃ´ng cÃ³ tiÃªu Ä‘á»')}</strong></div>
          <div>${esc(x.road_type || 'ChÆ°a rÃµ Ä‘Æ°á»ng')} Â· ${esc(PTYPES[x.property_type] || x.property_type || 'ChÆ°a rÃµ loáº¡i')}</div>
          <div>DT: <strong>${area(x.area_m2)}</strong> Â· GiÃ¡ rao: <strong>${money(x.price_ty)}</strong> Â· GiÃ¡/mÂ²: <strong>${ppm2(actualPpm2)}</strong></div>
        </div>
        ${desc ? `
          <div class="train-desc-wrap" data-desc-wrap="${x.id}">
            <div class="train-desc">${esc(desc)}</div>
            <button type="button" class="train-desc-toggle" data-desc-toggle="${x.id}" onclick="trnToggleDesc(${x.id})" hidden>Xem thÃªm</button>
          </div>` : ''}

        <div class="trn-review-cols${x.ai_verdict ? ' has-ai' : ''}">
          <div class="trn-review-main">
            <div class="review-box">
              <div class="review-title">Äá»‹nh giÃ¡ AI ${fairTitle}</div>
              <div class="chip-row">
                <button class="chip" data-card="${cid}" data-group="valuation" data-value="cheap_real">Ráº» tháº­t</button>
                <button class="chip" data-card="${cid}" data-group="valuation" data-value="fair">GiÃ¡ há»£p lÃ½</button>
                <button class="chip" data-card="${cid}" data-group="valuation" data-value="overpriced">Äang cao</button>
                <button class="chip" data-card="${cid}" data-group="valuation" data-value="fake_price">GiÃ¡ áº£o</button>
                <button class="chip" data-card="${cid}" data-group="valuation" data-value="cannot_price">KhÃ´ng Ä‘á»‹nh giÃ¡</button>
              </div>
              <ul class="explain-list">
                <li>Score ${Math.round(x.signal_score || 0)}, segment ${esc(x.segment || '-')} (${x.n_segment || 0} máº«u)</li>
                <li>GiÃ¡ thá»±c ${money(x.price_ty)} (${ppm2(actualPpm2)}), fair ${money(x.fair_ty)} (${ppm2(fairPpm2)}), thiáº¿u field: ${esc(missing)}</li>
                ${sourceFlags.length ? `<li>Source QC: ${sourceFlags.map(esc).join(', ')}</li>` : ''}
              </ul>
              <div class="review-title" style="margin-top:10px">NguyÃªn nhÃ¢n</div>
              <div class="chip-row">
                ${[['bad_fengshui','Phong thá»§y xáº¥u'],['deep_alley','Háº»m sÃ¢u'],['corner_lot','Äáº¥t gÃ³c'],['bait_listing','Tin má»“i'],['fake_price','GiÃ¡ áº£o']].map(([v,l]) => `<button class="chip reason-chip" data-card="${cid}" data-group="reason" data-value="${v}">${l}</button>`).join('')}
              </div>
            </div>
            <button class="primary-btn save-training" onclick="saveTraining(${x.id})">LÆ°u nhÃ£n Ä‘á»‹nh giÃ¡</button>
          </div>
          <div class="trn-review-aside">${x.ai_verdict ? `
            <div class="review-box" style="opacity:.92;height:100%">
              <div class="review-title">ðŸ¤– Claude pre-review</div>
              <ul class="explain-list">
                <li><strong>${esc(x.ai_verdict)}</strong>${x.ai_confidence != null ? ` Â· ${Math.round(x.ai_confidence * 100)}%` : ''}</li>
                ${x.ai_reasoning ? `<li>${esc(x.ai_reasoning)}</li>` : ''}
                ${(() => { let f = []; try { f = JSON.parse(x.ai_red_flags || '[]'); } catch (e) { f = []; } return (f && f.length) ? `<li>ðŸš© ${f.map(esc).join(', ')}</li>` : ''; })()}
                ${x.ai_needs_map_check ? `<li>ðŸ—ºï¸ Cáº§n kiá»ƒm tra quy hoáº¡ch/phÃ¡p lÃ½/vá»‹ trÃ­</li>` : ''}
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
  const missing = (explain.missing_fields || []).length ? explain.missing_fields.join(', ') : 'khÃ´ng';
  const legal = x.legal_summary || {};
  const legalFlags = String(legal.flags || '').split(',').filter(Boolean);
  const showLegalTools = queue === 'legal_qc' && String(legal.status || '').trim() !== 'has_document';
  const legalTools = showLegalTools ? `
        <div class="review-box legal-qc-box">
          <div class="review-title">Legal QC Â· ${esc(legal.status || 'unverified')} Â· ${Math.round(legal.trust_score || legal.confidence_score || 0)}%</div>
          <ul class="explain-list">
            <li>Thá»­a/tá»: ${esc(legal.thua_so || '-')} / ${esc(legal.to_ban_do || '-')}</li>
            <li>DT sá»•: ${area(legal.legal_area_m2)} Â· Thá»• cÆ°: ${area(legal.legal_residential_m2)}</li>
            <li>PhÆ°á»ng: ${esc(legal.legal_ward || '-')} Â· ÄÆ°á»ng: ${esc(legal.legal_road_text || '-')}</li>
            ${legalFlags.length ? `<li>Flags: ${legalFlags.map(esc).join(', ')}</li>` : ''}
          </ul>
          <div class="legal-qc-grid">
            <input id="legal-road-${x.id}" value="${esc(legal.legal_road_text || '')}" placeholder="ÄÆ°á»ng trÃªn sá»•">
            <input id="legal-ward-${x.id}" value="${esc(legal.legal_ward || '')}" placeholder="PhÆ°á»ng trÃªn sá»•">
            <input id="legal-area-${x.id}" value="${esc(legal.legal_area_m2 || '')}" placeholder="DT sá»•">
            <input id="legal-res-${x.id}" value="${esc(legal.legal_residential_m2 || '')}" placeholder="Thá»• cÆ°">
            <input id="legal-thua-${x.id}" value="${esc(legal.thua_so || '')}" placeholder="Thá»­a sá»‘">
            <input id="legal-to-${x.id}" value="${esc(legal.to_ban_do || '')}" placeholder="Tá» báº£n Ä‘á»“">
          </div>
          <div class="chip-row">
            <button class="secondary-btn legal-qc-action" onclick="saveLegalVerification(${x.id}, 'verified')">XÃ¡c nháº­n Ä‘Ãºng sá»•</button>
            <button class="secondary-btn legal-qc-action" onclick="saveLegalVerification(${x.id}, 'needs_review')">Cáº§n soi tiáº¿p</button>
            <button class="secondary-btn legal-qc-action" onclick="saveLegalVerification(${x.id}, 'conflict')">CÃ³ xung Ä‘á»™t</button>
          </div>
        </div>` : '';
  return `
    <article class="training-card quality-review-card" data-id="${x.id}">
      <div class="train-img-wrap">
        <img class="train-img" src="${esc(x.image || PLACEHOLDER)}" onerror="this.src=PLACEHOLDER" alt="">
        <div class="mos-chip">BiÃªn an toÃ n ${Math.round(x.mos_pct || 0)}%</div>
        ${nImg ? `<button class="train-gallery-btn" onclick="openTrnGallery(${x.id})">áº¢nh (${nImg})</button>` : ''}
      </div>
      <div class="train-body">
        <div class="train-title">
          <a href="${esc(x.detail_url)}" target="_blank">${esc(x.ward || 'Unknown')}</a>
          <span>TD-${x.id}</span>
        </div>
        <div class="train-lines">
          <div><strong>${esc(x.title || 'KhÃ´ng cÃ³ tiÃªu Ä‘á»')}</strong></div>
          <div>${esc(SOURCE_NAMES[x.source] || x.source || '-')} Â· ${esc(x.road_type || 'ChÆ°a rÃµ Ä‘Æ°á»ng')} Â· ${esc(PTYPES[x.property_type] || x.property_type || 'ChÆ°a rÃµ loáº¡i')}</div>
          <div>DT: <strong>${area(x.area_m2)}</strong> Â· GiÃ¡ rao: <strong>${money(x.price_ty)}</strong> Â· GiÃ¡/mÂ²: <strong>${ppm2(actualPpm2)}</strong></div>
        </div>
        ${desc ? `
          <div class="train-desc-wrap" data-desc-wrap="${x.id}">
            <div class="train-desc">${esc(desc)}</div>
            <button type="button" class="train-desc-toggle" data-desc-toggle="${x.id}" onclick="trnToggleDesc(${x.id})" hidden>Xem thÃªm</button>
          </div>` : ''}
        ${legalTools}
        <div class="review-box">
          <div class="review-title">ThÃ´ng tin kiá»ƒm dá»‹ch</div>
          <ul class="explain-list">
            <li>Queue: ${esc(queue)} Â· Feedback: ${esc(x.feedback_verdict || '-')} Â· Valuation: ${esc(x.valuation_verdict || '-')} Â· Data: ${esc(x.extraction_verdict || '-')}</li>
            <li>Score ${Math.round(x.signal_score || 0)}, segment ${esc(x.segment || '-')} (${x.n_segment || 0} máº«u)</li>
            <li>GiÃ¡ thá»±c ${money(x.price_ty)} (${ppm2(actualPpm2)}), fair ${money(x.fair_ty)} (${ppm2(fairPpm2)}), thiáº¿u field: ${esc(missing)}</li>
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
    alert('Chá»n nhÃ£n Ä‘á»‹nh giÃ¡ trÆ°á»›c khi lÆ°u.');
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
