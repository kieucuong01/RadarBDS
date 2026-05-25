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
    document.getElementById('sidebar').classList.toggle('show');
    document.getElementById('mobileOverlay').classList.toggle('show');
  } else {
    document.getElementById('sidebar').classList.toggle('collapsed');
  }
}

function hideSidebarMobile() {
  if (window.innerWidth <= 1024) {
    document.getElementById('sidebar').classList.remove('show');
    document.getElementById('mobileOverlay').classList.remove('show');
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
  // Never block first paint on browser geolocation permission. Load the default
  // dashboard immediately, then refine the city only if geolocation returns.
  applyFilters();
  const initialQuery = currentFilters;

  if (!navigator.geolocation) {
    console.warn("Geolocation not supported. Using fallback.");
    return;
  }

  navigator.geolocation.getCurrentPosition((pos) => {
    if (currentFilters !== initialQuery) return;

    const lat = pos.coords.latitude;
    const lon = pos.coords.longitude;

    let closestCity = "THỦ DẦU MỘT";
    let minDist = Infinity;

    for (const [city, coords] of Object.entries(CITY_COORDS)) {
      const d = Math.sqrt(Math.pow(lat - coords.lat, 2) + Math.pow(lon - coords.lon, 2));
      if (d < minDist) {
        minDist = d;
        closestCity = city;
      }
    }

    const radios = document.getElementsByName('city');
    radios.forEach(r => {
      if (r.value === closestCity) {
        r.checked = true;
      }
    });

    console.log("Detected location, closest city:", closestCity);
    applyFilters();
  }, (err) => {
    console.warn("Geolocation error:", err.message);
  }, { timeout: 1500, maximumAge: 600000 });
}
let treemapInstance = null;
let trendInstance = null;
let priceGapInstance = null;
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

function escHtml(v) {
  return String(v ?? '').replace(/[&<>"']/g, (ch) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]
  ));
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

  const res = await fetch(url, { signal: controller.signal });
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

function switchTab(tabId, btn) {
  document.querySelectorAll('.nav-link').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
  if (btn) btn.classList.add('active');
  document.getElementById(`tab-${tabId}`).classList.add('active');

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
}
