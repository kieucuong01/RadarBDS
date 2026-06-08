// Shared dashboard state, shell helpers, and cached fetch helpers.
// Init theme on load before body renders
const savedTheme = localStorage.getItem('radar_theme') || 'light';
document.documentElement.setAttribute('data-theme', savedTheme);

function toggleTheme() {
  const isLight = document.documentElement.getAttribute('data-theme') === 'light';
  if (isLight) {
    document.documentElement.setAttribute('data-theme', 'dark');
    localStorage.setItem('radar_theme', 'dark');
  } else {
    document.documentElement.setAttribute('data-theme', 'light');
    localStorage.setItem('radar_theme', 'light');
  }
}

function toggleMenu() {
  if (window.innerWidth <= 1024) {
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('mobileOverlay');
    const shouldShow = !sidebar.classList.contains('show');
    sidebar.classList.toggle('show', shouldShow);
    sidebar.setAttribute('aria-hidden', shouldShow ? 'false' : 'true');
    overlay.classList.toggle('show', shouldShow);
    document.body.classList.toggle('sidebar-open', shouldShow);
  } else {
    document.getElementById('sidebar').classList.toggle('collapsed');
  }
}

function hideSidebarMobile() {
  if (window.innerWidth <= 1024) {
    const sidebar = document.getElementById('sidebar');
    sidebar.classList.remove('show');
    sidebar.setAttribute('aria-hidden', 'true');
    document.getElementById('mobileOverlay').classList.remove('show');
    document.body.classList.remove('sidebar-open');
  }
}

function toggleFilterSection(titleEl) {
  const group = titleEl.closest('.filter-group');
  if (!group || !group.hasAttribute('data-collapsible')) return;
  if (group.hasAttribute('data-collapsed')) {
    group.removeAttribute('data-collapsed');
  } else {
    group.setAttribute('data-collapsed', '');
  }
}

// Global State
let currentFilters = "";
let currentPageNo = 1;
let listingsHasMore = false;
let listingsLoading = false;
let listingsView = 'table';
let loadedListings = [];
let trendPeriod = 'month';
let historyChartInstance = null;
let globalWardsByCity = {};
let signalPageNo = 1;
let signalHasMore = false;
let signalLoading = false;
let signalSort = 'newest';
let signalsVersion = '0';
let signalRunSeq = 0;
let signalRenderSeq = 0;
let firstSignalsLoaded = false;
let renderedSignalIds = new Set();
let inflightSignalQueryKey = '';
let inflightDashboardQueryKey = '';
const SIGNAL_PAGE_SIZE = 30;
const SIGNAL_RENDER_CHUNK_SIZE = 10;
const CACHE_TTL_MS = 60000;
const responseCache = new Map();
const requestControllers = {};
let filterDebounceTimer = null;
let countsRunSeq = 0;
let dashboardRunSeq = 0;
let insightsRunSeq = 0;
let insightsLoaded = false;
let marketIndicatorRunSeq = 0;

const CITY_COORDS = {
  "THỦ DẦU MỘT": { lat: 10.98, lon: 106.65 },
  "BẾN CÁT": { lat: 11.13, lon: 106.61 },
  "THUẬN AN": { lat: 10.91, lon: 106.70 },
  "DĨ AN": { lat: 10.91, lon: 106.77 },
  "TÂN UYÊN": { lat: 11.05, lon: 106.81 }
};

function detectLocation() {
  // First paint wins: load the default dashboard immediately. Browser
  // geolocation used to trigger a second automatic fetch on first load, which
  // made the dashboard feel jumpy on mobile.
  applyFilters();
}
let trendInstance = null;
const PLACEHOLDER_IMG = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='800' height='520' viewBox='0 0 800 520'%3E%3Cdefs%3E%3ClinearGradient id='bg' x1='0' y1='0' x2='1' y2='1'%3E%3Cstop offset='0%25' stop-color='%230f172a'/%3E%3Cstop offset='100%25' stop-color='%231e293b'/%3E%3C/linearGradient%3E%3C/defs%3E%3Crect width='800' height='520' fill='url(%23bg)'/%3E%3Ccircle cx='140' cy='88' r='110' fill='rgba(148,163,184,0.08)'/%3E%3Ccircle cx='690' cy='430' r='140' fill='rgba(148,163,184,0.06)'/%3E%3Ctext x='400' y='278' text-anchor='middle' font-family='Plus Jakarta Sans,Arial,sans-serif' font-size='56' font-weight='700' fill='rgba(203,213,225,0.12)'%3ERadarBDS%3C/text%3E%3Ctext x='400' y='322' text-anchor='middle' font-family='Plus Jakarta Sans,Arial,sans-serif' font-size='24' font-weight='600' fill='rgba(203,213,225,0.55)'%3EKhong co anh hien thi%3C/text%3E%3C/svg%3E";

const sourceNames = { 'batdongsan': 'BDS.vn', 'facebook': 'Facebook', 'guland': 'Guland' };
const sourceClasses = { 'batdongsan': 'source-bds', 'facebook': 'source-fb', 'guland': 'source-gl' };
const PROPERTY_TYPE_LABELS = {
  dat_nen: 'Đất nền',
  dat_vuon: 'Đất vườn',
  nha_dat: 'Nhà đất',
  nha_tro: 'Nhà trọ',
  chung_cu: 'Chung cư',
  nha_o_xa_hoi: 'Nhà ở xã hội'
};
const CONTACT_CTA_LABEL = 'Liên hệ tư vấn';

function escHtml(v) {
  return String(v ?? '').replace(/[&<>"']/g, (ch) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]
  ));
}

function renderTextWithContactCta(text, listingId, context = 'redacted_contact') {
  return String(text || '').split(/\r?\n/).map((line) => {
    if (line.trim() !== CONTACT_CTA_LABEL) return escHtml(line);
    return `<button type="button" class="inline-contact-cta" data-listing-id="${escHtml(listingId || '')}" data-ctx="${escHtml(context)}" onclick="event.preventDefault();event.stopPropagation();tierCTA(this.dataset.listingId,'',this.dataset.ctx);">${CONTACT_CTA_LABEL}</button>`;
  }).join('<br>');
}

function showLoader() { document.getElementById('mainLoader').classList.add('show'); }
function hideLoader() { document.getElementById('mainLoader').classList.remove('show'); }

function isCacheFresh(entry) {
  return entry && (Date.now() - entry.ts) < CACHE_TTL_MS;
}

async function fetchJSONCached(scope, url, useCache = true) {
  const cacheKey = `${scope}|${url}`;
  const cached = responseCache.get(cacheKey);
  if (useCache && isCacheFresh(cached)) {
    return cached.data;
  }

  if (requestControllers[scope]) {
    requestControllers[scope].abort();
  }

  const controller = new AbortController();
  requestControllers[scope] = controller;

  const res = await fetch(url, { signal: controller.signal, cache: 'no-store' });
  if (!res.ok) {
    throw new Error(`${res.status} ${res.statusText}`);
  }
  const data = await res.json();
  responseCache.set(cacheKey, { ts: Date.now(), data });

  if (requestControllers[scope] === controller) {
    delete requestControllers[scope];
  }

  return data;
}

function activeTabId() {
  const active = document.querySelector('.tab-content.active');
  return active ? active.id.replace('tab-', '') : 'signals';
}

const TAB_TITLES = {
  signals: 'Săn Deal',
  all: 'Tin rao',
  market: 'Thị trường',
  insights: 'Insights'
};

function syncMobileBadge(sourceId, targetId) {
  const source = document.getElementById(sourceId);
  const target = document.getElementById(targetId);
  if (source && target) target.textContent = source.textContent || '0';
}

function syncMobileBadges() {
  syncMobileBadge('badgeSignals', 'mobileBadgeSignals');
  syncMobileBadge('badgeTotal', 'mobileBadgeTotal');
}

function switchTab(tabId, btn) {
  document.querySelectorAll('.nav-link, .bottom-nav-item').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
  document.querySelectorAll(`[data-tab-target="${tabId}"]`).forEach(b => b.classList.add('active'));
  if (btn && !btn.dataset.tabTarget) btn.classList.add('active');
  const tab = document.getElementById(`tab-${tabId}`);
  if (!tab) return;
  tab.classList.add('active');
  const mobileTitle = document.getElementById('mobileActiveTabTitle');
  if (mobileTitle) mobileTitle.textContent = TAB_TITLES[tabId] || 'Radar BDS';
  hideSidebarMobile();
  syncMobileBadges();

  if (tabId === 'market') {
    loadMarketIndicators();
    loadMarketCharts();
    loadTrendData();
  }
  if (tabId === 'insights') {
    loadInsights(false);
  }
  if (tabId === 'all') {
    loadListings(1);
  }
  if (tabId === 'signals' && typeof ensureSignalScrollRoot === 'function') {
    requestAnimationFrame(() => ensureSignalScrollRoot({ refreshObserver: true }));
  }
}
