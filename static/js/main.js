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
  if (!navigator.geolocation) {
    console.warn("Geolocation not supported. Using fallback.");
    applyFilters();
    return;
  }

  navigator.geolocation.getCurrentPosition((pos) => {
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
    // Fallback: Ensure THỦ DẦU MỘT is checked (which triggers Tân An fallback in updateWardFilters)
    const radios = document.getElementsByName('city');
    radios.forEach(r => { if (r.value === "THỦ DẦU MỘT") r.checked = true; });
    applyFilters();
  });
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
  chung_cu: 'Chung cư'
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

function selectCity(btn) {
  document.querySelectorAll('.city-pill').forEach(p => p.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById('cityInput').value = btn.dataset.city;
  updateWardFilters(globalWardsByCity, [], { preserveScroll: false, preserveSearch: false });
  applyFilters();
}

function filterWards(query) {
  const q = query.toLowerCase().trim();
  document.querySelectorAll('#wardFilters .filter-option').forEach(label => {
    const text = label.textContent.toLowerCase();
    label.style.display = text.includes(q) ? '' : 'none';
  });
}

function updateWardSelectionSummary() {
  const boxes = Array.from(document.querySelectorAll('#wardFilters input[name="ward"]'));
  const countEl = document.getElementById('wardSelectedCount');
  const selectedCount = boxes.filter(b => b.checked).length;
  if (countEl) countEl.textContent = `${selectedCount}/${boxes.length} phường`;
}

function setAllWards(checked) {
  document.querySelectorAll('#wardFilters input[name="ward"]').forEach(box => {
    box.checked = checked;
  });
  updateWardSelectionSummary();
  scheduleApplyFilters();
}

function getFilterQuery() {
  const form = document.getElementById('filterForm');
  const fd = new FormData(form);
  const params = new URLSearchParams();
  for (let [k, v] of fd.entries()) {
    params.append(k, v);
  }
  const wardBoxes = Array.from(document.querySelectorAll('#wardFilters input[name="ward"]'));
  if (wardBoxes.length > 0 && wardBoxes.every(box => !box.checked)) {
    params.set('ward_mode', 'none');
  }
  // Command-bar controls live outside #filterForm, so append them explicitly.
  const mosSlider = document.getElementById('mosSlider');
  if (mosSlider) {
    params.set('mos_min', mosSlider.value || '0');
  }
  const onlyDrops = document.querySelector('input[name="only_drops"]');
  if (onlyDrops && onlyDrops.checked) {
    params.set('only_drops', '1');
  }
  params.append('trend_period', trendPeriod);
  return params.toString();
}

function setPriceRangePreset(min, max) {
  const minEl = document.getElementById('priceMin');
  const maxEl = document.getElementById('priceMax');
  if (minEl) minEl.value = min === '' || min === null || min === undefined ? '' : String(min);
  if (maxEl) maxEl.value = max === '' || max === null || max === undefined ? '' : String(max);
  scheduleApplyFilters();
}

function setSquareRangePreset(min, max) {
  const minEl = document.getElementById('areaMin');
  const maxEl = document.getElementById('areaMax');
  if (minEl) minEl.value = min === '' || min === null || min === undefined ? '' : String(min);
  if (maxEl) maxEl.value = max === '' || max === null || max === undefined ? '' : String(max);
  scheduleApplyFilters();
}

function activateSuperSignal() {
  const mosSlider = document.getElementById('mosSlider');
  const mosValue = document.getElementById('mosValue');
  const onlyDrops = document.querySelector('input[name="only_drops"]');
  if (mosSlider) mosSlider.value = 25;
  if (mosValue) mosValue.textContent = '25';
  if (onlyDrops && !onlyDrops.checked) {
    onlyDrops.checked = true;
    onlyDrops.dispatchEvent(new Event('change', { bubbles: true }));
  }
  scheduleApplyFilters();
}

function syncSignalSortSelect() {
  const select = document.getElementById('signalSortSelect');
  if (select && select.value !== signalSort) {
    select.value = signalSort;
  }
}

function setSignalSort(sortKey) {
  signalSort = sortKey || 'newest';
  syncSignalSortSelect();
  loadSignals(1, { reset: true });
}

function updateTrendPeriod(p, btn) {
  trendPeriod = p;
  document.querySelectorAll('.p-pill').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');

  currentFilters = getFilterQuery();
  loadTrendData(false);
}

function applyFilters() {
  currentFilters = getFilterQuery();
  currentPageNo = 1;
  listingsHasMore = false;
  const tab = activeTabId();
  if (tab === 'signals') {
    loadSignals(1, { reset: true });
    refreshDashboardMeta(false);
  } else {
    refreshDashboardMeta(false);
  }

  if (tab === 'market') {
    loadMarketIndicators(false);
    loadMarketCharts(false);
    loadTrendData(false);
  }
  if (tab === 'insights') {
    loadInsights(false);
  }
  if (tab === 'all') {
    loadListings(1);
  }
}

function scheduleApplyFilters() {
  clearTimeout(filterDebounceTimer);
  filterDebounceTimer = setTimeout(applyFilters, 200);
}

async function initDashboard() {
  return refreshDashboardMeta(false);
}

async function refreshDashboardMeta(useCache = false) {
  const dashboardKey = currentFilters;
  if (inflightDashboardQueryKey === dashboardKey) return;
  inflightDashboardQueryKey = dashboardKey;
  const runId = ++dashboardRunSeq;
  try {
    const data = await fetchJSONCached('dashboard', `/api/dashboard?${currentFilters}`, useCache);
    if (runId !== dashboardRunSeq) return;

    // Update Stats
    document.getElementById('statTotal').innerText = data.stats.total;
    document.getElementById('statSignals').innerText = data.stats.signals;
    // Tin mới (3 ngày) dựa trên posted/crawled_at <= 3 ngày (thống nhất với badge trên card)
    const el = document.getElementById('statNewRecent');
    if (el) el.innerText = data.stats.new_recent_days_7 || 0;


    const bSig = document.getElementById('badgeSignals');
    const bTot = document.getElementById('badgeTotal');
    if (bSig) bSig.innerText = data.stats.signals;
    if (bTot) bTot.innerText = data.stats.total;

    // Update Wards based on City
    globalWardsByCity = data.wards_by_city;
    updateWardFilters(data.wards_by_city, data.active_wards, { preserveScroll: true });
    signalsVersion = String(data.signals_version || '0');
    syncSignalSortSelect();

  } catch (err) {
    if (err.name === 'AbortError') return;
    console.error(err);
  } finally {
    if (runId === dashboardRunSeq) {
      inflightDashboardQueryKey = '';
    }
  }
}

function setSortPill(btn) {
  if (!btn) return;
  setSignalSort(btn.dataset.sort || 'newest');
}

function sortAndRenderSignals() {
  loadSignals(1, { reset: true });
}

let _sigObserver = null;

function signalQuery(page) {
  const params = new URLSearchParams(currentFilters);
  params.set('sort', signalSort);
  params.set('page', String(page));
  params.set('limit', String(SIGNAL_PAGE_SIZE));
  params.set('sigv', String(signalsVersion || '0'));
  return params.toString();
}

function _severityText(level) {
  if (level === 'critical') return 'Cập nhật quan trọng';
  if (level === 'warning') return 'Cần theo dõi';
  return 'Thông tin';
}

function _timelineIcon(statusTag) {
  if (statusTag === 'done') return '✓';
  if (statusTag === 'in_progress') return '◔';
  return '◷';
}

function _timelinePercent(progressPct, statusTag) {
  if (progressPct === null || progressPct === undefined || progressPct === '') {
    if (statusTag === 'done') return 100;
    if (statusTag === 'planned') return 10;
    return 35;
  }
  const n = Number(progressPct);
  if (!Number.isFinite(n)) return 0;
  return Math.max(0, Math.min(100, n));
}

function _renderInsightsTimeline(items) {
  const root = document.getElementById('insightTimeline');
  if (!root) return;
  if (!items || !items.length) {
    root.innerHTML = `<div class="insight-empty">Chưa có dữ liệu hạ tầng.</div>`;
    return;
  }
  root.innerHTML = items.map((x) => {
    const percent = _timelinePercent(x.progress_pct, x.status_tag);
    const place = [x.ward, x.road_ref].filter(Boolean).join(' · ');
    return `
      <article class="timeline-item status-${x.status_tag || 'planned'}">
        <div class="timeline-dot">${_timelineIcon(x.status_tag)}</div>
        <div class="timeline-card">
          <div class="timeline-top">
            <h4>${escHtml(x.title || '')}</h4>
            <span>${escHtml(x.milestone_label || '')}</span>
          </div>
          <p>${escHtml(x.subtitle || x.summary || '')}</p>
          <div class="timeline-meta">
            <strong>${escHtml(place || 'Bình Dương')}</strong>
            <small>${escHtml(x.relative_time || '')}</small>
          </div>
          <div class="timeline-bar"><span style="width:${percent}%"></span></div>
        </div>
      </article>
    `;
  }).join('');
}

function _renderInsightsPolicy(items) {
  const root = document.getElementById('insightPolicy');
  if (!root) return;
  if (!items || !items.length) {
    root.innerHTML = `<div class="insight-empty">Chưa có policy alert.</div>`;
    return;
  }
  root.innerHTML = items.map((x) => {
    const severity = x.severity || 'info';
    return `
      <article class="policy-item severity-${severity}">
        <div class="policy-top">
          <h4>${escHtml(x.title || '')}</h4>
          <span>${escHtml(x.relative_time || '')}</span>
        </div>
        <p>${escHtml(x.summary || x.subtitle || '')}</p>
        <div class="policy-foot">
          <small>${escHtml(_severityText(severity))}</small>
          ${x.source_url ? `<a href="${escHtml(x.source_url)}" target="_blank" rel="noopener noreferrer">Nguồn</a>` : ''}
        </div>
      </article>
    `;
  }).join('');
}

async function loadInsights(useCache = true) {
  const runId = ++insightsRunSeq;
  try {
    const data = await fetchJSONCached('insights', '/api/insights', useCache);
    if (runId !== insightsRunSeq) return;
    _renderInsightsTimeline(data.timeline || []);
    _renderInsightsPolicy(data.policy_alerts || []);
    const total = Number((data.counts && data.counts.projects) || 0) + Number((data.counts && data.counts.alerts) || 0);
    const badge = document.getElementById('badgeInsights');
    if (badge) badge.innerText = total;
    insightsLoaded = true;
  } catch (err) {
    if (err.name === 'AbortError') return;
    console.error('Insights load error', err);
    if (!insightsLoaded) {
      _renderInsightsTimeline([]);
      _renderInsightsPolicy([]);
    }
  }
}

function renderSignalSkeleton() {
  const grid = document.getElementById('signalsGrid');
  grid.innerHTML = Array.from({ length: 6 }).map(() => `
    <div class="scard" style="min-height:420px; opacity:.65; pointer-events:none;">
      <div class="sc-img-wrap" style="background:var(--border);"></div>
      <div class="sc-body">
        <div style="height:22px; width:85%; background:var(--border); border-radius:6px; margin-bottom:16px;"></div>
        <div class="price-container" style="min-height:96px;"></div>
        <div style="height:14px; width:70%; background:var(--border); border-radius:6px; margin-top:18px;"></div>
        <div style="height:14px; width:55%; background:var(--border); border-radius:6px; margin-top:12px;"></div>
      </div>
    </div>
  `).join('');
}

function renderSignalError(message) {
  const grid = document.getElementById('signalsGrid');
  if (!grid) return;
  grid.innerHTML = `
    <div style="grid-column: 1/-1; padding: 48px 20px; text-align: center; border: 1px dashed var(--border); border-radius: 16px; margin-top: 20px; color: var(--text-muted);">
      ${message}
    </div>
  `;
}

function _daysAgoValue(v) {
  const n = Number(v);
  return Number.isFinite(n) && n >= 0 ? n : null;
}

function _timeAgoText(v) {
  const n = _daysAgoValue(v);
  if (n === null) return 'Chưa rõ ngày';
  return n === 0 ? 'hôm nay' : `${n} ngày trước`;
}

function _isNewWithin(v, maxDays = 4) {
  const n = _daysAgoValue(v);
  return n !== null && n <= maxDays;
}

async function loadSignals(page = 1, opts = {}) {
  const reset = Boolean(opts.reset);
  const queryKey = signalQuery(page);
  if (reset && signalLoading && inflightSignalQueryKey === queryKey) return;
  const runId = reset ? ++signalRunSeq : signalRunSeq;
  if (signalLoading && !reset) return;
  signalLoading = true;
  inflightSignalQueryKey = queryKey;
  if (reset) {
    if (_sigObserver) _sigObserver.disconnect();
    signalRenderSeq++;
    signalPageNo = 1;
    signalHasMore = false;
    renderedSignalIds = new Set();
    if (!firstSignalsLoaded) {
      renderSignalSkeleton();
    }
  }
  try {
    const data = await fetchJSONCached('signals', `/api/signals?${queryKey}`, false);
    if (runId !== signalRunSeq) return;
    const bSig = document.getElementById('badgeSignals');
    if (bSig && Number.isFinite(Number(data.total))) {
      bSig.innerText = data.total;
    }
    if (reset) document.getElementById('signalsGrid').innerHTML = '';
    renderSignals(data.signals || [], { append: !reset });
    signalPageNo = data.page || page;
    signalHasMore = Boolean(data.has_more);
    if (!signalHasMore && _sigObserver) _sigObserver.disconnect();
    if (!firstSignalsLoaded) {
      firstSignalsLoaded = true;
      hideLoader();
    }
  } catch (err) {
    if (err.name !== 'AbortError') {
      console.error(err);
      renderSignalError('Không tìm thấy signal theo bộ lọc hiện tại.');
      if (!firstSignalsLoaded) {
        firstSignalsLoaded = true;
        hideLoader();
      }
    }
  } finally {
    if (runId === signalRunSeq) {
      signalLoading = false;
      inflightSignalQueryKey = '';
    }
  }
}

function renderSignals(signals, options = {}) {
  const append = Boolean(options.append);
  const freshSignals = (signals || []).filter((x) => {
    const id = Number(x && x.id);
    if (!Number.isFinite(id)) return true;
    if (renderedSignalIds.has(id)) return false;
    return true;
  });
  for (const x of freshSignals) {
    const id = Number(x && x.id);
    if (Number.isFinite(id)) renderedSignalIds.add(id);
  }
  if (!freshSignals || freshSignals.length === 0) {
    if (!append) renderSignalError('Không tìm thấy signal theo bộ lọc hiện tại.');
    return;
  }

  _renderSignalCards(freshSignals);
  _setupSignalScroll();
}

function _renderSignalCards(signals) {
  const grid = document.getElementById('signalsGrid');
  if (!signals || signals.length === 0) return;
  const renderSeq = signalRenderSeq;

  const renderChunk = (start) => {
    if (renderSeq !== signalRenderSeq) return;
    const chunk = signals.slice(start, start + SIGNAL_RENDER_CHUNK_SIZE);
    if (chunk.length === 0) return;
    grid.insertAdjacentHTML('beforeend', chunk.map(x => {
      const fairPrice = x.fair_ppm2 ? (x.fair_ppm2 * x.area_m2 / 1000).toFixed(2) : '-';
      const fairNum = fairPrice !== '-' ? parseFloat(fairPrice) : NaN;
      const priceNum = parseFloat(x.price_ty);
      const profit = fairPrice !== '-' ? (fairNum - priceNum).toFixed(2) : '-';
      const isOverpriced = Number.isFinite(priceNum) && Number.isFinite(fairNum) && priceNum > fairNum;
      const actualClass = isOverpriced ? 'price-over' : 'price-deal';

      const daysAgo = _daysAgoValue(x.days_ago);
      let timeStr = _timeAgoText(daysAgo);
      let legalStr = (x.has_so === true || x.has_so === 1) ? 'Sổ Hồng' : ((x.has_so === false || x.has_so === 0) ? 'Chờ sổ' : 'Đang cập nhật');

      const roadTiers = {
        1: 'Mặt tiền',
        2: 'Đường nhựa',
        3: 'Hẻm xe hơi',
        4: 'Hẻm xe máy'
      };
      let roadStr = roadTiers[x.road_tier] || 'Chưa rõ';

      const safeTitle = String(x.title || '').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
      const imgSrc = x.primary_img || PLACEHOLDER_IMG;
      const dataAttr = `data-id="${x.id}" data-title="${safeTitle}" data-primary="${imgSrc}" data-price="${x.price_ty}" data-ppm2="${x.actual_ppm2}" data-fair="${fairPrice}" data-fppm2="${x.fair_ppm2}" data-area="${x.area_m2}" data-ward="${x.ward}" data-road="${roadStr}" data-time="${timeStr}" data-profit="${profit}" data-mos="${x.mos_pct}" data-source="${sourceNames[x.source] || x.source}" data-drop="${x.drop_pct || ''}" data-score="${x.signal_score || '-'}" data-url="${x.url || ''}" data-ptype="${x.prop_type || ''}"`;

      const isNew = _isNewWithin(x.days_ago, 7);
      const newBadgeHtml = isNew ? `<div class="new-badge"><svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/></svg> MỚI</div>` : '';

      const srcName = sourceNames[x.source] || x.source;
      const dropBadge = x.price_dropped ? `<span class="sc-drop-tag"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="12 4 12 20"/><polyline points="6 14 12 20 18 14"/></svg> Chủ hạ: ${x.drop_pct ? x.drop_pct + '%' : 'N/A'}</span>` : '';

      return `
      <div class="scard" onclick="openSignal(this)" ${dataAttr}>
        <div class="sc-img-wrap">
          <img class="sc-img" src="${imgSrc}" loading="lazy" decoding="async" width="640" height="416" alt="Img" onerror="this.onerror=null;this.src=PLACEHOLDER_IMG">
          <div class="mos-badge"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4"><rect x="4" y="9" width="16" height="10" rx="4"/><circle cx="9" cy="14" r="1"/><circle cx="15" cy="14" r="1"/><path d="M12 9V5"/><circle cx="12" cy="4" r="1"/></svg> So với Định Giá: -${Math.round(x.mos_pct)}%</div>
          ${newBadgeHtml}
          <div class="sc-img-tags">
            <span class="sc-source-tag">${srcName}</span>
            <span class="sc-time-tag"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg> ${timeStr}</span>
            ${dropBadge}
          </div>
        </div>
        <div class="sc-body">
          <div class="sc-title" title="${safeTitle}">${x.title}</div>

          <div class="price-container">
            <div class="price-actual">
              <span class="price-label price-label-actual ${actualClass}">THỰC TẾ</span>
              <div class="price-val ${actualClass}">${x.price_ty || '-'} tỷ</div>
              <div class="price-m2">${x.actual_ppm2 || '-'} tr/m²</div>
            </div>
            <div class="price-fair">
              <span class="price-label price-label-fair">ĐỊNH GIÁ</span>
              <div class="price-val-fair">${fairPrice} tỷ</div>
              <div class="price-m2">${x.fair_ppm2 || '-'} tr/m²</div>
            </div>
          </div>

          <div class="sc-meta-grid">
            <div class="meta-item"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/></svg> ${x.ward}</div>
            <div class="meta-item"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/></svg> ${x.area_m2 || '-'} m²</div>
            <div class="meta-item"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"/><line x1="4" y1="22" x2="4" y2="15"/></svg> ${roadStr}</div>
            <div class="meta-item"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg> ${legalStr}</div>
          </div>

          <div class="sc-actions" onclick="event.stopPropagation()">
            <a href="#" onclick="event.preventDefault();const c=this.closest('.scard').dataset;tierCTA(c.id,c.url,'card_signal');" class="btn-zalo"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg> ${(window.USER_TIER === 'vip' || window.USER_TIER === 'admin') ? '⚡ Ráp mối VIP' : '💬 Ráp mối'}</a>
          </div>
        </div>
      </div>
    `;
    }).join(''));
    if (start + SIGNAL_RENDER_CHUNK_SIZE < signals.length) {
      requestAnimationFrame(() => renderChunk(start + SIGNAL_RENDER_CHUNK_SIZE));
    }
  };

  requestAnimationFrame(() => renderChunk(0));
}

function _setupSignalScroll() {
  if (_sigObserver) _sigObserver.disconnect();
  const grid = document.getElementById('signalsGrid');
  const root = grid.closest('.tab-content');
  const sentinel = document.getElementById('sig-scroll-sentinel');
  if (!sentinel) {
    const s = document.createElement('div');
    s.id = 'sig-scroll-sentinel';
    s.style.height = '1px';
    grid.parentElement.appendChild(s);
  }
  const el = document.getElementById('sig-scroll-sentinel');
  _sigObserver = new IntersectionObserver(entries => {
    if (entries[0].isIntersecting && signalHasMore && !signalLoading) {
      loadSignals(signalPageNo + 1, { reset: false });
    }
  }, { root, rootMargin: '400px' });
  _sigObserver.observe(el);
}

// Slider state
let _smSlideIdx = 0;
let _smSlideImgs = [];

function slideSignal(dir) {
  if (_smSlideImgs.length <= 1) return;
  _smSlideIdx = (_smSlideIdx + dir + _smSlideImgs.length) % _smSlideImgs.length;
  document.getElementById('sm-slides').style.transform = `translateX(-${_smSlideIdx * 100}%)`;
  // Update counter
  document.getElementById('sm-img-count').innerText = `${_smSlideIdx + 1} / ${_smSlideImgs.length}`;
  // Update dots
  document.querySelectorAll('#sm-dots span').forEach((d, i) => {
    d.style.background = i === _smSlideIdx ? '#fff' : 'rgba(255,255,255,0.4)';
  });
}

function buildSlider(imgs) {
  _smSlideIdx = 0;
  _smSlideImgs = imgs.length ? imgs : [PLACEHOLDER_IMG];
  const slides = document.getElementById('sm-slides');
  const dots = document.getElementById('sm-dots');
  const counter = document.getElementById('sm-img-count');
  const prevBtn = document.getElementById('sm-prev');
  const nextBtn = document.getElementById('sm-next');

  // Build slides
  slides.style.transform = 'translateX(0)';
  slides.innerHTML = _smSlideImgs.map((src, i) => `
    <div style="min-width:100%; height:100%; flex-shrink:0; background:#0f172a;">
      <img src="${src}" style="width:100%; height:100%; object-fit:contain; display:block; background:#0f172a; cursor:zoom-in;"
        onclick="openGallery(${i})"
        onerror="this.onerror=null;this.src=PLACEHOLDER_IMG;">
    </div>`
  ).join('');

  // Dots
  dots.innerHTML = _smSlideImgs.length > 1
    ? _smSlideImgs.map((_, i) => `<span onclick="_smSlideIdx=${i - 1}; slideSignal(1);" style="width:7px; height:7px; border-radius:50%; background:${i === 0 ? '#fff' : 'rgba(255,255,255,0.4)'}; cursor:pointer; transition:background 0.2s; display:inline-block;"></span>`).join('')
    : '';

  // Arrows + counter
  const multi = _smSlideImgs.length > 1;
  prevBtn.style.display = multi ? 'flex' : 'none';
  nextBtn.style.display = multi ? 'flex' : 'none';
  counter.innerText = multi ? `1 / ${_smSlideImgs.length}` : '';
}

let smHistoryChart = null;
let galleryImages = [];
let galleryIndex = 0;

function propertyTypeLabel(v) {
  return PROPERTY_TYPE_LABELS[v] || v || 'N/A';
}

function renderSignalTags(data) {
  const tags = [
    { icon: '📐', label: `${data.area || '-'} m²` },
    { icon: '📍', label: data.ward || '-' },
    { icon: '🛣️', label: data.road || '-' },
    { icon: '🏷️', label: propertyTypeLabel(data.propertyType) },
    { icon: '📊', label: `Score: ${data.score || '-'}` },
  ];
  document.getElementById('sm-tags').innerHTML = tags
    .map((t) => `<span>${t.icon} ${t.label}</span>`)
    .join('');
}

function renderModalTitle(rawTitle) {
  const el = document.getElementById('sm-title');
  if (!el) return;
  const parts = String(rawTitle || '')
    .split(/\n+/)
    .map((x) => x.trim())
    .filter(Boolean);
  if (!parts.length) {
    el.innerHTML = '';
    return;
  }
  const main = parts[0];
  const sub = parts.slice(1).join(' · ');
  el.innerHTML = `
    <span class="sm-title-main">${escHtml(main)}</span>
    ${sub ? `<span class="sm-title-sub">${escHtml(sub)}</span>` : ''}
  `;
}

function toggleModalComps(btn) {
  const list = btn.closest('.sm-comps-list');
  if (!list) return;
  const expanded = list.classList.toggle('is-expanded');
  const count = btn.dataset.count || '0';
  btn.textContent = expanded ? 'Thu gọn' : `Xem thêm ${count} lô`;
}

function openGallery(idx = 0) {
  if (!galleryImages.length) return;
  galleryIndex = Math.max(0, Math.min(idx, galleryImages.length - 1));
  const modal = document.getElementById('galleryModal');
  const img = document.getElementById('galleryImage');
  const counter = document.getElementById('galleryCounter');
  img.src = galleryImages[galleryIndex];
  counter.innerText = `${galleryIndex + 1} / ${galleryImages.length}`;
  modal.style.display = 'flex';
  document.body.style.overflow = 'hidden';
}

function closeGallery() {
  const modal = document.getElementById('galleryModal');
  modal.style.display = 'none';
  document.body.style.overflow = '';
}

function slideGallery(delta) {
  if (!galleryImages.length) return;
  galleryIndex = (galleryIndex + delta + galleryImages.length) % galleryImages.length;
  openGallery(galleryIndex);
}

function _openSignalLegacy(card) {
  const d = card.dataset;
  const modal = document.getElementById('signalModal');
  modal.dataset.listingId = d.id;

  // Build image slider
  const imgs = d.primary ? [d.primary] : [];
  buildSlider(imgs);
  galleryImages = imgs.length ? imgs : [PLACEHOLDER_IMG];

  // Thumbnails
  const thumbsEl = document.getElementById('sm-thumbs');
  thumbsEl.innerHTML = galleryImages.length > 1
    ? galleryImages.map((src, i) => `<img src="${src}" onclick="_smSlideIdx=${i - 1}; slideSignal(1);" ondblclick="openGallery(${i})" onerror="this.style.display='none'">`).join('')
    : '';

  // Signal badge
  const mosNum = parseFloat(d.mos) || 0;
  const badgeLabel = mosNum >= 25 ? 'SUPER SIGNAL' : 'SIGNAL';
  document.getElementById('sm-signal-badge').innerHTML = `<span>${badgeLabel} · -${d.mos}%</span>`;

  // Title
  document.getElementById('sm-title').innerText = d.title;

  // Meta line
  document.getElementById('sm-meta-line').innerHTML = `<span>Đăng ${d.time}</span> · <span>${d.source}</span>`;

  // Description is lazy-loaded from /api/listing/<id>.
  document.getElementById('sm-desc').innerText = 'Đang tải mô tả chi tiết...';

  // Groq assessment is intentionally hidden while Investment Memo owns this slot.
  const price = parseFloat(d.price) || 0;
  const area = parseFloat(d.area) || 0;
  hideGroqAssessment();

  // Tags
  const tags = [
    { icon: '📐', label: `${d.area} m²` },
    { icon: '📍', label: d.ward },
    { icon: '🛣️', label: d.road },
    { icon: '📊', label: `Score: ${d.score || '-'}` },
  ];
  document.getElementById('sm-tags').innerHTML = tags
    .map(t => `<span>${t.icon} ${t.label}</span>`).join('');
  renderSignalTags({
    area: d.area,
    ward: d.ward,
    road: d.road,
    score: d.score,
    propertyType: d.ptype
  });

  // Links
  document.getElementById('sm-zalo').dataset.listingId = d.id;
  document.getElementById('sm-zalo').dataset.listingUrl = d.url || `/listing/${d.id}`;
  { const _d = document.getElementById('sm-detail'); if (_d) _d.href = d.url || `/listing/${d.id}`; };

  // Load price history + comps
  loadSignalHistory(d.id, price, area, d.ward);
  hydrateSignalDetail(d.id);

  modal.style.display = 'flex';
}

async function _hydrateSignalDetailLegacy(listingId) {
  const modal = document.getElementById('signalModal');
  try {
    const res = await fetch(`/api/listing/${listingId}`);
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    const data = await res.json();
    if (modal.dataset.listingId !== String(listingId)) return;

    document.getElementById('sm-title').innerText = data.title || document.getElementById('sm-title').innerText;
    document.getElementById('sm-desc').innerText = data.description || 'Không có mô tả.';
    document.getElementById('sm-zalo').dataset.listingId = data.id || listingId;
    document.getElementById('sm-zalo').dataset.listingUrl = data.url || `/listing/${listingId}`;
    { const _d = document.getElementById('sm-detail'); if (_d) _d.href = data.url || `/listing/${listingId}`; };
    renderSignalTags({
      area: data.area_m2,
      ward: data.ward,
      road: data.road_type || data.road_tier || '-',
      score: data.signal_score || '-',
      propertyType: data.property_type
    });

    const imgs = Array.isArray(data.imgs) ? data.imgs.filter(Boolean) : [];
    galleryImages = imgs.length ? imgs : [PLACEHOLDER_IMG];
    if (galleryImages.length) {
      buildSlider(galleryImages);
      const thumbsEl = document.getElementById('sm-thumbs');
      thumbsEl.innerHTML = galleryImages.length > 1
        ? galleryImages.map((src, i) => `<img src="${src}" onclick="_smSlideIdx=${i - 1}; slideSignal(1);" ondblclick="openGallery(${i})" onerror="this.style.display='none'">`).join('')
        : '';
    }
  } catch (err) {
    console.error(err);
    if (modal.dataset.listingId === String(listingId)) {
      document.getElementById('sm-desc').innerText = 'Không tải được mô tả chi tiết.';
    }
  }
}

async function _loadSignalHistoryLegacyOld(listingId, currentPrice, area, ward) {
  const historyEl = document.getElementById('sm-price-history');
  const compsBody = document.getElementById('sm-comps-body');
  const LOADING_ROW = '<tr><td colspan="4" style="text-align:center;padding:12px;opacity:0.5;">⏳ Đang tải...</td></tr>';
  historyEl.innerHTML = '<div style="opacity:0.5;padding:8px 0;">⏳ Đang tải lịch sử...</div>';
  compsBody.innerHTML = LOADING_ROW;

  // Destroy old chart
  if (smHistoryChart) { smHistoryChart.destroy(); smHistoryChart = null; }

  try {
    const res = await fetch(`/api/history/${listingId}`);
    const data = await res.json();

    // Price history rows with % change
    if (data.history && data.history.length > 0) {
      let prevPrice = null;
      const priceHistoryHtml = data.history.map(h => {
        let changeHtml = '';
        if (prevPrice && h.price_ty) {
          const pct = ((h.price_ty - prevPrice) / prevPrice * 100).toFixed(1);
          changeHtml = `<span class="ph-change">${pct}%</span>`;
        }
        prevPrice = h.price_ty;
        return `<div class="ph-row"><span class="ph-date">📅 ${h.date}</span><span class="ph-price">${h.price_ty} tỷ</span>${changeHtml}</div>`;
      }).join('');
      historyEl.innerHTML = priceHistoryHtml;

      // Mini chart
      const ctx = document.getElementById('sm-history-chart').getContext('2d');
      smHistoryChart = new Chart(ctx, {
        type: 'line',
        data: {
          labels: data.history.map(h => h.date),
          datasets: [{
            data: data.history.map(h => h.price_ty),
            borderColor: '#6366f1', backgroundColor: 'rgba(99,102,241,0.1)',
            fill: true, tension: 0.3, pointRadius: 4, pointBackgroundColor: '#6366f1', borderWidth: 2
          }]
        },
        options: {
          maintainAspectRatio: false,
          plugins: { legend: { display: false } },
          scales: {
            x: { grid: { color: 'rgba(0,0,0,0.05)' }, ticks: { font: { size: 10 } } },
            y: { grid: { color: 'rgba(0,0,0,0.05)', drawBorder: false }, ticks: { font: { size: 10 } } }
          }
        }
      });
    }

    // COMPS — similar listings in same ward
    if (data.lot_history && data.lot_history.length > 1) {
      const lotRows = data.lot_history.map(h => {
        const drop = h.price_dropped && h.drop_pct ? `<span class="ph-change">-${h.drop_pct}%</span>` : '';
        const current = h.is_current ? ' - current' : '';
        const source = h.source ? ` - ${h.source}` : '';
        const title = String(h.title || '').replace(/"/g, '&quot;');
        const label = `Lot ${h.date}${source}${current}`;
        const dateHtml = h.url
          ? `<a class="ph-date" href="${h.url}" target="_blank" rel="noopener noreferrer" onclick="event.stopPropagation()" title="${title}">${label}</a>`
          : `<span class="ph-date" title="${title}">${label}</span>`;
        return `<div class="ph-row">${dateHtml}<span class="ph-price">${h.price_ty || '-'} ty</span>${drop}</div>`;
      }).join('');
      historyEl.innerHTML += `<div style="margin-top:10px; padding-top:8px; border-top:1px solid var(--border);">${lotRows}</div>`;
    }

    if (data.comps && data.comps.length > 0) {
      compsBody.innerHTML = data.comps.map(c =>
        `<tr><td>${c.address || c.title || '-'}</td><td>${c.area_m2 || '-'} m²</td><td><b>${c.price_ty} tỷ</b></td><td>${c.date || '-'}</td></tr>`
      ).join('');
    }
    // Add current deal row
    compsBody.innerHTML += `<tr><td>Deal hiện tại</td><td>${area} m²</td><td><b>${currentPrice} tỷ</b></td><td>Now</td></tr>`;

  } catch (err) {
    console.error('History load error:', err);
    historyEl.innerHTML = '<div style="opacity:0.5;padding:8px 0;">Không tải được dữ liệu.</div>';
    compsBody.innerHTML = '';
  }
}

function _memoTy(v) {
  const n = Number(v);
  return Number.isFinite(n) ? `${n.toFixed(2)} tỷ` : '-';
}

function _memoPct(v) {
  const n = Number(v);
  return Number.isFinite(n) ? `${n.toFixed(1)}%` : '-';
}

function _memoList(items, emptyText) {
  const list = Array.isArray(items) ? items.filter(Boolean) : [];
  if (!list.length) return `<div class="sm-empty-state">${escHtml(emptyText || 'Chưa có dữ liệu.')}</div>`;
  return `<ul class="sm-memo-list">${list.map((x) => `<li>${escHtml(x)}</li>`).join('')}</ul>`;
}

function hideGroqAssessment() {
  const aiSection = document.getElementById('sm-ai-section');
  const aiText = document.getElementById('sm-ai-text');
  if (aiText) aiText.innerHTML = '';
  if (aiSection) {
    aiSection.hidden = true;
    aiSection.setAttribute('aria-hidden', 'true');
    aiSection.style.display = 'none';
  }
}

function renderInvestmentMemoLoading() {
  const body = document.getElementById('sm-memo-body');
  if (!body) return;
  body.innerHTML = '<div class="sm-empty-state">Đang tải memo...</div>';
}

function renderInvestmentMemoLocked() {
  const body = document.getElementById('sm-memo-body');
  if (!body) return;
  body.innerHTML = `
    <div class="sm-memo-locked">
      <b>Investment Memo đang khóa</b><br>
      Đăng ký miễn phí để xem giải thích định giá, dữ liệu còn thiếu và các cảnh báo rủi ro.
      <div style="margin-top:10px;">
        <button type="button" class="sm-comps-toggle" onclick="RadarAuth.openAuthModal('Đăng ký để xem giải thích định giá cho từng deal.')">Đăng ký miễn phí</button>
      </div>
    </div>
  `;
}

function renderInvestmentMemo(data) {
  const body = document.getElementById('sm-memo-body');
  if (!body) return;
  if (!data || data.locked) {
    renderInvestmentMemoLocked();
    return;
  }
  const metrics = data.metrics || {};
  const comps = data.comps_summary || {};
  const price = data.price_context || {};
  const tone = data.verdict_tone || 'muted';
  const dropText = price.price_dropped
    ? `Đã ghi nhận giảm ${_memoPct(price.drop_pct)}${price.suspicious_bait ? ' (cần xác minh)' : ''}.`
    : 'Chưa có biến động giảm giá đáng kể.';
  const missingInfo = data.missing_info || data.data_quality_warnings;
  const riskWarnings = data.risk_warnings || data.risks;
  const questions = data.verification_questions || data.broker_questions;
  body.innerHTML = `
    <div class="sm-memo-head">
      <span class="sm-memo-verdict ${escHtml(tone)}">${escHtml(data.verdict_label || data.verdict || '-')}</span>
      <p class="sm-memo-summary">${escHtml(data.summary || '')}</p>
    </div>
    <div class="sm-memo-metrics">
      <div class="sm-memo-metric"><span>Giá hiện tại</span><b>${_memoTy(metrics.current_price_ty)}</b></div>
      <div class="sm-memo-metric"><span>Fair total</span><b>${_memoTy(metrics.fair_total_ty)}</b></div>
      <div class="sm-memo-metric"><span>Biên an toàn hiện tại</span><b>${_memoPct(metrics.mos_pct)}</b></div>
      <div class="sm-memo-metric"><span>Comps gần nhất</span><b>${Number(comps.count || 0)}</b></div>
    </div>
    <div class="sm-memo-grid">
      <div><p class="sm-memo-block-title">Cách định giá</p>${_memoList(data.valuation_explanation, 'Chưa đủ dữ liệu để giải thích định giá.')}</div>
      <div><p class="sm-memo-block-title">Thiếu thông tin ảnh hưởng định giá</p>${_memoList(missingInfo, 'Chưa phát hiện thiếu dữ liệu lớn từ hệ thống.')}</div>
      <div><p class="sm-memo-block-title">Cảnh báo rủi ro</p>${_memoList(riskWarnings, 'Vẫn cần kiểm tra pháp lý, quy hoạch và hiện trạng.')}</div>
      <div><p class="sm-memo-block-title">Câu hỏi xác minh</p>${_memoList(questions, 'Cần xin thêm thông tin để xác minh định giá.')}</div>
      <div class="sm-memo-note">${escHtml(dropText)} Lịch sử lô: ${Number(price.repost_count || 0)} repost.</div>
    </div>
  `;
}

async function loadInvestmentMemo(listingId) {
  const modal = document.getElementById('signalModal');
  renderInvestmentMemoLoading();
  if ((window.USER_TIER || 'guest') === 'guest') {
    renderInvestmentMemoLocked();
    return;
  }
  try {
    const res = await fetch(`/api/listing/${listingId}/memo`);
    if (res.status === 403) {
      renderInvestmentMemoLocked();
      return;
    }
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    const data = await res.json();
    if (modal && modal.dataset.listingId !== String(listingId)) return;
    renderInvestmentMemo(data);
  } catch (err) {
    console.error('Investment memo load error:', err);
    const body = document.getElementById('sm-memo-body');
    if (body) body.innerHTML = '<div class="sm-empty-state">Không tải được Investment Memo.</div>';
  }
}

// Override modal handlers with finalized V2 logic (keeps backward compatibility with existing onclick hooks).
function openSignal(card) {
  _openSignalFromData(card.dataset);
}

function _openSignalFromData(d) {
  const modal = document.getElementById('signalModal');
  modal.dataset.listingId = d.id;

  const imgs = d.primary ? [d.primary] : [];
  buildSlider(imgs);
  galleryImages = imgs.length ? imgs : [PLACEHOLDER_IMG];
  const thumbsEl = document.getElementById('sm-thumbs');
  thumbsEl.innerHTML = galleryImages.length > 1
    ? galleryImages.map((src, i) => `<img src="${src}" onclick="_smSlideIdx=${i - 1}; slideSignal(1);" ondblclick="openGallery(${i})" onerror="this.style.display='none'">`).join('')
    : '';

  const mosNum = parseFloat(d.mos) || 0;
  const badgeLabel = mosNum >= 25 ? 'SUPER SIGNAL' : 'SIGNAL';
  document.getElementById('sm-signal-badge').innerHTML = `<span>${badgeLabel} · -${d.mos}%</span>`;
  renderModalTitle(d.title || '');
  document.getElementById('sm-meta-line').innerHTML = `<span>Dang ${d.time || '-'}</span> · <span>${d.source || '-'}</span>`;
  document.getElementById('sm-desc').innerText = 'Dang tai mo ta chi tiet...';

  // Groq assessment is intentionally hidden while Investment Memo owns this slot.
  const price = parseFloat(d.price) || 0;
  const area = parseFloat(d.area) || 0;
  hideGroqAssessment();

  renderSignalTags({
    area: d.area,
    ward: d.ward,
    road: d.road,
    score: d.score,
    propertyType: d.ptype
  });

  document.getElementById('sm-zalo').dataset.listingId = d.id;
  document.getElementById('sm-zalo').dataset.listingUrl = d.url || `/listing/${d.id}`;
  { const _d = document.getElementById('sm-detail'); if (_d) _d.href = d.url || `/listing/${d.id}`; };

  loadSignalHistory(d.id, price, area, d.ward);
  loadInvestmentMemo(d.id);
  hydrateSignalDetail(d.id);
  modal.style.display = 'flex';
}

function openListingModal(row) {
  const d = row.dataset;
  _openSignalFromData({
    id: d.id,
    title: d.title,
    primary: d.primary,
    price: d.price,
    fair: d.fair,
    area: d.area,
    ward: d.ward,
    road: d.road,
    time: d.time,
    profit: d.profit,
    mos: d.mos,
    source: d.source,
    drop: d.drop,
    score: d.score,
    url: d.url,
    ptype: d.ptype
  });
}

async function hydrateSignalDetail(listingId) {
  const modal = document.getElementById('signalModal');
  try {
    const res = await fetch(`/api/listing/${listingId}`);
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    const data = await res.json();
    if (modal.dataset.listingId !== String(listingId)) return;

    renderModalTitle(data.title || document.getElementById('sm-title').innerText);
    document.getElementById('sm-desc').innerText = data.description || 'Không có mô tả.';
    document.getElementById('sm-zalo').dataset.listingId = data.id || listingId;
    document.getElementById('sm-zalo').dataset.listingUrl = data.url || `/listing/${listingId}`;
    { const _d = document.getElementById('sm-detail'); if (_d) _d.href = data.url || `/listing/${listingId}`; };
    renderSignalTags({
      area: data.area_m2,
      ward: data.ward,
      road: data.road_type || data.road_tier || '-',
      score: data.signal_score || '-',
      propertyType: data.property_type
    });

    const imgs = Array.isArray(data.imgs) ? data.imgs.filter(Boolean) : [];
    galleryImages = imgs.length ? imgs : [PLACEHOLDER_IMG];
    buildSlider(galleryImages);
    const thumbsEl = document.getElementById('sm-thumbs');
    thumbsEl.innerHTML = galleryImages.length > 1
      ? galleryImages.map((src, i) => `<img src="${src}" onclick="_smSlideIdx=${i - 1}; slideSignal(1);" ondblclick="openGallery(${i})" onerror="this.style.display='none'">`).join('')
      : '';
  } catch (err) {
    console.error(err);
    if (modal.dataset.listingId === String(listingId)) {
      document.getElementById('sm-desc').innerText = 'Khong tai duoc mo ta chi tiet.';
    }
  }
}

async function loadSignalHistory(listingId, currentPrice, area, ward) {
  // Chart/history elements only exist for admin tier. Comps table is always present.
  const historyEl = document.getElementById('sm-price-history');
  const chartEl = document.getElementById('sm-history-chart');
  const compsBody = document.getElementById('sm-comps-body');
  if (historyEl) historyEl.innerHTML = '<div style="opacity:0.5;padding:8px 0;">Đang tải lịch sử...</div>';
  if (compsBody) compsBody.innerHTML = '<div class="sm-empty-state">Đang tải giao dịch tương tự...</div>';
  if (smHistoryChart) { smHistoryChart.destroy(); smHistoryChart = null; }

  try {
    const res = await fetch(`/api/history/${listingId}`);
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    const data = await res.json();
    const sameListingHistory = Array.isArray(data.history) ? data.history : [];
    const lotHistory = Array.isArray(data.lot_history) ? data.lot_history : [];

    let prettyPrevPrice = null;
    const sameRowsPretty = sameListingHistory.map((h) => {
      let changeHtml = '';
      if (prettyPrevPrice && h.price_ty && prettyPrevPrice > 0) {
        const pct = ((h.price_ty - prettyPrevPrice) / prettyPrevPrice * 100).toFixed(1);
        const cls = Number(pct) < 0 ? 'ph-change is-down' : 'ph-change';
        changeHtml = `<span class="${cls}">${pct}%</span>`;
      }
      prettyPrevPrice = h.price_ty;
      return `<div class="ph-row ph-price-row">
        <div class="ph-main">
          <span class="ph-date">${escHtml(h.date || '-')}</span>
          <span class="ph-sub">Giá ghi nhận</span>
        </div>
        <span class="ph-price">${escHtml(h.price_ty || '-')} tỷ</span>
        ${changeHtml}
      </div>`;
    }).join('');

    const lotRowsPretty = lotHistory.length > 1 ? lotHistory.map((h) => {
      const drop = h.price_dropped && h.drop_pct ? `<span class="ph-change is-down">-${escHtml(h.drop_pct)}%</span>` : '';
      const title = escHtml(h.title || 'Tin cùng lô');
      const sourceText = escHtml([h.source, h.is_current ? 'đang rao' : ''].filter(Boolean).join(' · ') || 'Cùng lô');
      const origin = h.url
        ? `<a class="ph-date" href="${escHtml(h.url)}" target="_blank" rel="noopener noreferrer" onclick="event.stopPropagation()" title="${title}">${escHtml(h.date || '-')}</a>`
        : `<span class="ph-date">${escHtml(h.date || '-')}</span>`;
      const detail = h.detail_url
        ? `<a class="ph-lot-link" href="${escHtml(h.detail_url)}" target="_blank" rel="noopener noreferrer" onclick="event.stopPropagation()">Chi tiết</a>`
        : '';
      return `<div class="ph-row ph-lot-row">
        <div class="ph-main">${origin}<span class="ph-sub">${sourceText}</span></div>
        <span class="ph-price">${escHtml(h.price_ty || '-')} tỷ</span>
        ${drop}
        ${detail}
      </div>`;
    }).join('') : '';

    if (historyEl) {
      historyEl.innerHTML = `
        <div class="sm-section-label sm-history-label">Giá theo bài đăng</div>
        ${sameRowsPretty || '<div class="sm-empty-state">Chưa có biến động giá.</div>'}
        <div class="sm-section-label sm-history-label">Lịch sử đăng BĐS</div>
        ${lotRowsPretty || '<div class="sm-empty-state">Không có repost cùng lô.</div>'}
      `;
    }

    const labels = Array.from(new Set([
      ...sameListingHistory.map((h) => h.date),
      ...lotHistory.map((h) => h.date)
    ])).sort();
    const mapSame = {};
    sameListingHistory.forEach((h) => { mapSame[h.date] = h.price_ty; });
    const mapLot = {};
    lotHistory.forEach((h) => { mapLot[h.date] = h.price_ty; });

    if (labels.length > 0 && chartEl) {
      const ctx = chartEl.getContext('2d');
      smHistoryChart = new Chart(ctx, {
        type: 'line',
        data: {
          labels,
          datasets: [
            {
              label: 'Cung tin',
              data: labels.map((d) => (mapSame[d] ?? null)),
              borderColor: '#6366f1',
              backgroundColor: 'rgba(99,102,241,0.12)',
              fill: false,
              tension: 0.25,
              pointRadius: 3,
              borderWidth: 2
            },
            {
              label: 'Cung lo',
              data: labels.map((d) => (mapLot[d] ?? null)),
              borderColor: '#0ea5a4',
              backgroundColor: 'rgba(14,165,164,0.12)',
              fill: false,
              tension: 0.25,
              pointRadius: 3,
              borderWidth: 2,
              borderDash: [5, 4]
            }
          ]
        },
        options: {
          maintainAspectRatio: false,
          plugins: { legend: { display: true, labels: { usePointStyle: true, boxWidth: 8 } } },
          scales: {
            x: { grid: { color: 'rgba(0,0,0,0.05)' }, ticks: { font: { size: 10 } } },
            y: { grid: { color: 'rgba(0,0,0,0.05)', drawBorder: false }, ticks: { font: { size: 10 } } }
          }
        }
      });
    }

    if (compsBody) {
      const isAdmin = window.USER_TIER === 'admin';
      const currentTitle = document.getElementById('sm-title')?.innerText || 'Deal hiện tại';
      const renderCompRow = (c, opts = {}) => {
        const isCurrent = Boolean(opts.isCurrent);
        const hidden = Boolean(opts.hidden);
        const title = escHtml(c.title || (isCurrent ? currentTitle : 'Tin tương tự'));
        const areaText = c.area_m2 || c.area || '-';
        const priceText = c.price_ty || c.price || '-';
        const rowHref = isCurrent ? '' : (isAdmin && c.url ? c.url : (c.detail_url || ''));
        const clickAttrs = rowHref
          ? ` role="link" tabindex="0" data-href="${escHtml(rowHref)}" onclick="window.open(this.dataset.href,'_blank','noopener,noreferrer')" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();this.click();}"`
          : '';
        const sourceBadge = isAdmin && c.url ? '<span class="sm-comp-source-badge">TIN GỐC</span>' : '';
        return `<article class="sm-comp-card sm-comp-row ${isCurrent ? 'is-current' : ''} ${hidden ? 'sm-comp-extra' : ''} ${rowHref ? 'is-clickable' : ''}"${clickAttrs}>
          <div class="sm-comp-main">
            <div class="sm-comp-title-line">
              <div class="sm-comp-title" title="${title}">${title}</div>
              ${isCurrent ? '<span class="sm-current-badge">Đang xem</span>' : sourceBadge}
            </div>
            <div class="sm-comp-metrics">
              <span><b>${escHtml(areaText)}</b><small>m²</small></span>
              <span><b>${escHtml(priceText)}</b><small>tỷ</small></span>
            </div>
          </div>
        </article>`;
      };
      const comps = Array.isArray(data.comps) ? data.comps : [];
      const baseline = renderCompRow({
        title: currentTitle,
        area_m2: area || '-',
        price_ty: currentPrice || '-'
      }, { isCurrent: true });
      const compRows = comps.length
        ? comps.map((c, index) => renderCompRow(c, { hidden: index >= 3 })).join('')
        : '<div class="sm-empty-state">Chưa có lô tương tự phù hợp.</div>';
      const extraCount = Math.max(0, comps.length - 3);
      const toggle = extraCount > 0
        ? `<button type="button" class="sm-comps-toggle" data-count="${extraCount}" onclick="toggleModalComps(this)">Xem thêm ${extraCount} lô</button>`
        : '';
      compsBody.classList.remove('is-expanded');
      compsBody.innerHTML = baseline + compRows + toggle;
    }
  } catch (err) {
    console.error('History load error:', err);
    if (historyEl) historyEl.innerHTML = '<div style="opacity:0.5;padding:8px 0;">Không tải được dữ liệu.</div>';
    if (compsBody) compsBody.innerHTML = '<div class="sm-empty-state">Lỗi tải dữ liệu.</div>';
  }
}

async function loadMarketCharts(useCache = true) {
  const container = document.getElementById('heatmapContainer');
  const gapContainer = document.getElementById('priceGapContainer');
  if (container) container.classList.add('loading');
  if (gapContainer) gapContainer.classList.add('loading');
  try {
    const data = await fetchJSONCached('market', `/api/heatmap?${currentFilters}`, useCache);
    renderHeatmap(data);
    renderPriceGapChart(data);
  } catch (err) {
    if (err.name !== 'AbortError') console.error("Market charts error:", err);
  } finally {
    if (container) container.classList.remove('loading');
    if (gapContainer) gapContainer.classList.remove('loading');
  }
}

async function loadHeatmap() {
  const container = document.getElementById('heatmapContainer');
  container.classList.add('loading');
  try {
    const data = await fetchJSONCached('market', `/api/heatmap?${currentFilters}`);
    renderHeatmap(data);
  } catch (err) {
    if (err.name !== 'AbortError') console.error("Heatmap error:", err);
  } finally {
    container.classList.remove('loading');
  }
}

function renderHeatmap(data) {
  if (treemapInstance) {
    treemapInstance.destroy();
    treemapInstance = null;
  }

  const canvas = document.getElementById('treemapChart');
  const container = document.getElementById('heatmapContainer');
  const oldEmpty = document.getElementById('heatmapEmptyState');
  if (oldEmpty) oldEmpty.remove();

  const opportunityData = (data || []).filter(d => (d.deal_count || 0) > 0 && (d.median_mos || 0) > 0);
  if (canvas) canvas.style.display = '';

  if (opportunityData.length === 0) {
    if (canvas) canvas.style.display = 'none';
    if (container) {
      container.insertAdjacentHTML('beforeend', `
          <div id="heatmapEmptyState" style="position:absolute; inset:0; display:flex; align-items:center; justify-content:center; text-align:center; color:var(--text-muted); padding:24px;">
            <div>
              <div style="font-size:2rem; margin-bottom:10px;">📡</div>
              <div style="font-weight:800; color:var(--text); margin-bottom:4px;">Chưa có deal MOS dương</div>
              <div style="font-size:0.85rem;">Hãy nới filter phường, nguồn tin hoặc loại hình để radar có thêm mẫu signal.</div>
            </div>
          </div>
        `);
    }
    return;
  }

  const ctx = canvas.getContext('2d');

  // Gradient coloring based on avg_price
  treemapInstance = new Chart(ctx, {
    type: 'treemap',
    data: {
      datasets: [{
        tree: opportunityData,
        key: 'deal_count',
        spacing: 2,
        borderWidth: 0,
        backgroundColor(ctx) {
          if (ctx.type !== 'data') return 'transparent';
          const d = ctx.raw._data || ctx.raw;
          const mos = d ? (d.median_mos || 0) : 0;
          const ratio = Math.min(1, mos / 50);
          return `rgba(16, 185, 129, ${0.35 + ratio * 0.65})`;
        },
        labels: {
          display: true,
          align: 'center',
          position: 'center',
          color: 'white',
          font: { family: 'Inter', size: 14, weight: 'bold' },
          formatter(ctx) {
            if (ctx.type !== 'data') return '';
            const d = ctx.raw._data || ctx.raw;
            if (!d || !d.ward) return '';
            const mos = d.median_mos || 0;
            return [d.ward, `${d.deal_count || 0} deal`, `MOS trung vị +${mos}%`];
          }
        }
      }]
    },
    options: {
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            title: (items) => {
              const d = items[0].raw._data || items[0].raw;
              return d ? d.ward : '';
            },
            label: (item) => {
              const d = item.raw._data || item.raw;
              if (!d) return '';
              return [
                `Deal signal: ${d.deal_count || 0} tin`,
                `MOS trung vị: +${d.median_mos || 0}%`,
                `MOS trung bình: +${d.avg_signal_mos || 0}%`,
                `Tỷ lệ deal: ${d.signal_rate || 0}%`,
                `Tổng tin hợp lệ: ${d.total_count || 0}`,
                `Giá TB: ${d.avg_price || 0} tr/m²`
              ];
            }
          }
        }
      }
    }
  });
}

async function loadPriceGapChart() {
  const container = document.getElementById('priceGapContainer');
  if (!container) return;
  container.classList.add('loading');
  try {
    const data = await fetchJSONCached('market', `/api/heatmap?${currentFilters}`);
    renderPriceGapChart(data);
  } catch (err) {
    if (err.name !== 'AbortError') console.error('Price gap chart error:', err);
  } finally {
    container.classList.remove('loading');
  }
}

function renderPriceGapChart(data) {
  if (priceGapInstance) { priceGapInstance.destroy(); priceGapInstance = null; }
  if (!data || data.length === 0) return;

  // Sort by avg_price_ty descending, take top wards with fair value data
  const filtered = data.filter(d => d.avg_price_ty > 0 && d.avg_fair_ty > 0)
    .sort((a, b) => b.avg_price_ty - a.avg_price_ty)
    .slice(0, 10);

  if (filtered.length === 0) return;

  const ctx = document.getElementById('priceGapChart').getContext('2d');
  priceGapInstance = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: filtered.map(d => d.ward),
      datasets: [
        {
          label: 'Giá chào TB',
          data: filtered.map(d => d.avg_price_ty),
          backgroundColor: '#6366f1',
          borderRadius: 4, barPercentage: 0.7, categoryPercentage: 0.8
        },
        {
          label: 'Định giá AI',
          data: filtered.map(d => d.avg_fair_ty),
          backgroundColor: '#10b981',
          borderRadius: 4, barPercentage: 0.7, categoryPercentage: 0.8
        }
      ]
    },
    options: {
      maintainAspectRatio: false,
      plugins: {
        legend: { position: 'top', labels: { font: { family: 'Plus Jakarta Sans', size: 12, weight: '600' }, usePointStyle: true, pointStyle: 'rectRounded' } },
        tooltip: {
          callbacks: {
            label: (item) => `${item.dataset.label}: ${item.raw.toFixed(2)} tỷ`
          }
        }
      },
      scales: {
        x: { grid: { display: false }, ticks: { font: { family: 'Plus Jakarta Sans', size: 11 } } },
        y: { grid: { color: 'rgba(0,0,0,0.06)' }, ticks: { font: { size: 10 }, callback: v => v + ' tỷ' }, beginAtZero: true }
      }
    }
  });
}

function _fmtIndicatorNumber(value, digits = 0) {
  const n = Number(value);
  if (!Number.isFinite(n)) return '-';
  return n.toLocaleString('vi-VN', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits
  });
}

function _fmtIndicatorPct(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return '-';
  return `${n.toLocaleString('vi-VN', { maximumFractionDigits: n >= 10 ? 0 : 1 })}%`;
}

function _indicatorBadge(levelKey, level) {
  return `<span class="indicator-badge level-${escHtml(levelKey || 'normal')}">${escHtml(level || '')}</span>`;
}

function _renderDistressRatio(rows, summary) {
  const body = document.getElementById('distressRatioBody');
  const summaryEl = document.getElementById('distressRatioSummary');
  if (!body) return;

  if (summaryEl) {
    const hotspots = Number((summary && summary.distress_hotspots) || 0);
    const scanned = Number((summary && summary.wards_scanned) || 0);
    summaryEl.innerHTML = `
      <span><strong>${hotspots}</strong> khu vực áp lực cao</span>
      <span>Ngưỡng săn ép giá: từ 25%, vùng rất mạnh: từ 35%</span>
      <span>${scanned} khu vực được quét</span>
    `;
  }

  if (!rows || !rows.length) {
    body.innerHTML = `<tr><td colspan="6" class="indicator-empty-row">Chưa đủ dữ liệu giảm giá theo khu vực.</td></tr>`;
    return;
  }

  body.innerHTML = rows.map((x) => {
    const ratio = Number(x.ratio_pct || 0);
    const meterWidth = Math.max(2, Math.min(100, ratio));
    return `
      <tr>
        <td><strong>${escHtml(x.ward || '')}</strong></td>
        <td>${_fmtIndicatorNumber(x.total_count)}</td>
        <td>${_fmtIndicatorNumber(x.distress_count)}</td>
        <td>
          <div class="indicator-meter"><span class="level-${escHtml(x.level_key || 'normal')}" style="width:${meterWidth}%"></span></div>
          <b>${_fmtIndicatorPct(ratio)}</b>
        </td>
        <td>${_indicatorBadge(x.level_key, x.level)}</td>
        <td class="indicator-action">${escHtml(x.action || '')}</td>
      </tr>
    `;
  }).join('');
}

function _renderSupplyAnomaly(rows, summary) {
  const body = document.getElementById('supplyAnomalyBody');
  const summaryEl = document.getElementById('supplyAnomalySummary');
  if (!body) return;

  if (summaryEl) {
    const month = (summary && summary.current_month) || '';
    const hotspots = Number((summary && summary.supply_hotspots) || 0);
    const prev = ((summary && summary.previous_months) || []).join(', ');
    summaryEl.innerHTML = `
      <span><strong>${hotspots}</strong> khu vực tăng cung</span>
      <span>Tháng đang đo: ${escHtml(month || '-')}</span>
      <span>Nền so sánh: ${escHtml(prev || '-')}</span>
    `;
  }

  if (!rows || !rows.length) {
    body.innerHTML = `<tr><td colspan="6" class="indicator-empty-row">Chưa đủ dữ liệu nguồn cung theo tháng.</td></tr>`;
    return;
  }

  body.innerHTML = rows.map((x) => {
    const delta = Number(x.delta || 0);
    const growthText = x.growth_pct === null || x.growth_pct === undefined
      ? (Number(x.current_count || 0) > 0 ? 'Mới bật' : '-')
      : `${delta >= 0 ? '+' : ''}${_fmtIndicatorPct(x.growth_pct)}`;
    return `
      <tr>
        <td><strong>${escHtml(x.ward || '')}</strong></td>
        <td>${_fmtIndicatorNumber(x.current_count)}</td>
        <td>${_fmtIndicatorNumber(x.prev_avg, 1)}</td>
        <td>
          <b class="${delta > 0 ? 'indicator-up' : 'indicator-flat'}">${escHtml(growthText)}</b>
          <small>${delta >= 0 ? '+' : ''}${_fmtIndicatorNumber(delta, 1)} tin</small>
        </td>
        <td>${_indicatorBadge(x.level_key, x.level)}</td>
        <td class="indicator-action">${escHtml(x.action || '')}</td>
      </tr>
    `;
  }).join('');
}

async function loadMarketIndicators(useCache = true) {
  const distressContainer = document.getElementById('distressRatioContainer');
  const supplyContainer = document.getElementById('supplyAnomalyContainer');
  if (!distressContainer && !supplyContainer) return;
  if (distressContainer) distressContainer.classList.add('loading');
  if (supplyContainer) supplyContainer.classList.add('loading');
  const runId = ++marketIndicatorRunSeq;
  try {
    const data = await fetchJSONCached('marketIndicators', `/api/market-indicators?${currentFilters}`, useCache);
    if (runId !== marketIndicatorRunSeq) return;
    _renderDistressRatio(data.distress_ratio || [], data.summary || {});
    _renderSupplyAnomaly(data.supply_anomaly || [], data.summary || {});
  } catch (err) {
    if (err.name !== 'AbortError') console.error('Market indicators error:', err);
    _renderDistressRatio([], {});
    _renderSupplyAnomaly([], {});
  } finally {
    if (runId === marketIndicatorRunSeq) {
      if (distressContainer) distressContainer.classList.remove('loading');
      if (supplyContainer) supplyContainer.classList.remove('loading');
    }
  }
}

async function loadTrendData(useCache = true) {
  const container = document.getElementById('trendContainer');
  if (!container) return;
  container.classList.add('loading');
  try {
    const data = await fetchJSONCached('trend', `/api/trends?${currentFilters}`, useCache);
    renderTrendChart(data.trend_data || {});
  } catch (err) {
    if (err.name !== 'AbortError') console.error('Trend chart error:', err);
  } finally {
    container.classList.remove('loading');
  }
}

function renderTrendChart(trendData) {
  const ctx = document.getElementById('trendChart').getContext('2d');
  if (trendInstance) {
    trendInstance.destroy();
    trendInstance = null;
  }

  if (!trendData || Object.keys(trendData).length === 0) {
    return;
  }

  const datasets = [];
  const colors = ['#4f46e5', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899', '#06b6d4', '#f97316'];
  const allTimeKeys = new Set();

  for (const w in trendData) {
    trendData[w].forEach(d => allTimeKeys.add(d.week));
  }
  const sortedKeys = Array.from(allTimeKeys).sort();
  const labels = sortedKeys.map(w => w.replace('D-', '').replace('M-', ''));

  let i = 0;
  for (const ward in trendData) {
    const data = trendData[ward];
    const dataMap = {};
    data.forEach(d => dataMap[d.week] = d.median_ppm2);
    const wardData = sortedKeys.map(w => dataMap[w] || null);

    const color = colors[i % colors.length];
    datasets.push({
      label: ward,
      data: wardData,
      borderColor: color,
      backgroundColor: color + '10',
      borderWidth: 3,
      tension: 0.4,
      fill: false,
      pointRadius: sortedKeys.length > 30 ? 0 : 4,
      pointHoverRadius: 8,
      spanGaps: true,
      borderCapStyle: 'round'
    });
    i++;
  }

  Chart.defaults.font.family = "'Inter', sans-serif";
  trendInstance = new Chart(ctx, {
    type: 'line',
    data: { labels, datasets },
    options: {
      animation: { duration: 0 }, // Disable animation to prevent "jumping"
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: {
          position: 'bottom',
          labels: { boxWidth: 12, padding: 20, font: { size: 11, weight: '600' } }
        },
        tooltip: {
          padding: 12,
          backgroundColor: 'rgba(0,0,0,0.8)',
          titleFont: { size: 14, weight: 'bold' },
          bodyFont: { size: 13 },
          cornerRadius: 8
        }
      },
      scales: {
        y: {
          title: { display: true, text: 'Giá (tr/m²)', font: { weight: '600' } },
          grid: { color: 'rgba(255,255,255,0.05)' },
          ticks: { font: { size: 11 } }
        },
        x: {
          grid: { display: false },
          ticks: {
            font: { size: 10 },
            maxRotation: 45,
            autoSkip: true,
            maxTicksLimit: 12
          }
        }
      }
    }
  });
}

let tableSort = { col: 'date', dir: 'desc' };

function sortTable(th) {
  const col = th.dataset.col;
  if (tableSort.col === col) {
    tableSort.dir = tableSort.dir === 'asc' ? 'desc' : 'asc';
  } else {
    tableSort.col = col;
    tableSort.dir = 'asc';
  }
  document.querySelectorAll('.th-sort').forEach(el => {
    el.classList.remove('sort-asc', 'sort-desc');
    el.querySelector('.sort-icon').textContent = '↕';
  });
  th.classList.add(tableSort.dir === 'asc' ? 'sort-asc' : 'sort-desc');
  th.querySelector('.sort-icon').textContent = tableSort.dir === 'asc' ? '↑' : '↓';
  loadListings(1);
}

function applyTableFilters() { loadListings(1); }
function resetTableFilters() {
  ['tfAreaMin', 'tfAreaMax', 'tfPriceMin', 'tfPriceMax'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.value = '';
  });
  loadListings(1);
}

async function loadListings(page) {
  if (listingsLoading) return;
  listingsLoading = true;
  const tbody = document.getElementById('listingsTableBody');
  const sentinel = document.getElementById('listingsSentinel');
  if (page === 1) { tbody.innerHTML = ''; listingsHasMore = false; }
  tbody.classList.add('loading');
  if (sentinel) sentinel.textContent = '⏳ Đang tải...';
  try {
    const areaMin = document.getElementById('tfAreaMin')?.value || '';
    const areaMax = document.getElementById('tfAreaMax')?.value || '';
    const priceMin = document.getElementById('tfPriceMin')?.value || '';
    const priceMax = document.getElementById('tfPriceMax')?.value || '';
    let tableParams = '';
    if (areaMin) tableParams += `&area_min=${areaMin}`;
    if (areaMax) tableParams += `&area_max=${areaMax}`;
    if (priceMin) tableParams += `&price_min=${priceMin}`;
    if (priceMax) tableParams += `&price_max=${priceMax}`;
    currentPageNo = page;
    const data = await fetchJSONCached('listings', `/api/listings?${currentFilters}${tableParams}&sort_by=${tableSort.col}&sort_dir=${tableSort.dir}&page=${page}&limit=50`);
    listingsHasMore = (typeof data.has_more === 'boolean') ? data.has_more : ((data.listings || []).length >= 50);
    if (sentinel) sentinel.textContent = listingsHasMore ? '' : `Đã hiển thị tất cả ${data.total} tin`;
    const rows = (data.listings || []).map(x => {
      const fair = x.fair_ppm2 ? (x.fair_ppm2 * x.area_m2 / 1000).toFixed(2) : '-';
      return `
        <tr class="clickable-row" onclick="openListingModal(this)" data-id="${x.id}" data-title="${String(x.title || '').replace(/"/g, '&quot;')}" data-price="${x.price_ty || ''}" data-fair="${fair !== '-' ? fair : ''}" data-area="${x.area_m2 || ''}" data-ward="${x.ward || ''}" data-road="${x.road_type || x.road_tier || ''}" data-time="${_timeAgoText(x.days_ago)}" data-profit="${x.price_ty && fair !== '-' ? (parseFloat(fair) - parseFloat(x.price_ty)).toFixed(2) : ''}" data-mos="${x.mos_pct || ''}" data-source="${sourceNames[x.source] || x.source || ''}" data-drop="${x.drop_pct || ''}" data-score="${x.signal_score || ''}" data-url="${x.url || ''}" data-ptype="${x.prop_type || ''}">
          <td><span style="font-size:0.75rem; font-weight:700; color:var(--text-muted);">${x.prop_type}</span></td>
          <td><span style="padding:4px 8px; border-radius:6px; font-weight:600; font-size:0.8rem;">${x.ward}</span></td>
          <td><img src="${x.imgs && x.imgs.length ? x.imgs[0] : PLACEHOLDER_IMG}" class="td-img" loading="lazy" onerror="this.onerror=null;this.src=PLACEHOLDER_IMG"></td>
          <td style="font-weight:700;">${x.area_m2 ? x.area_m2 + ' m²' : '-'}</td>
          <td>
            <div style="color:var(--accent); font-weight:800; font-size:1rem;">${x.price_ty ? x.price_ty + ' tỷ' : '-'}</div>
            <div style="font-size:0.75rem; color:var(--text-muted); margin-top:2px;">${x.price_per_m2 || '-'} tr/m²</div>
          </td>
          <td>
            <div style="color:var(--primary); font-weight:800;">${fair !== '-' ? fair + ' tỷ' : '-'}</div>
            <div style="font-size:0.75rem; color:var(--primary); opacity:0.8; margin-top:2px;">${x.fair_ppm2 || '-'} tr/m²</div>
          </td>
          <td style="white-space:nowrap; font-size:0.8rem; color:var(--text-muted);">
            <div>${x.posted_at || '-'}</div>
            <div style="font-size:0.72rem; opacity:0.7;">${_timeAgoText(x.days_ago)}</div>
          </td>
          <td style="max-width: 300px;">
            <div class="td-title" title="${String(x.title || '').replace(/"/g, '&quot;')}">${x.title}</div>
            <div class="td-desc" title="${String(x.description || '').replace(/"/g, '&quot;')}">${x.description}</div>
          </td>
        </tr>
      `;
    }).join('');
    tbody.insertAdjacentHTML('beforeend', rows);
  } catch (e) {
    if (e.name !== 'AbortError') console.error(e);
    if (sentinel) sentinel.textContent = '';
  } finally {
    tbody.classList.remove('loading');
    listingsLoading = false;
  }
}

function setupListingsObserver() {
  const sentinel = document.getElementById('listingsSentinel');
  const scrollEl = document.querySelector('.table-scroll');
  if (!sentinel || !scrollEl) return;
  new IntersectionObserver(entries => {
    if (entries[0].isIntersecting && listingsHasMore && !listingsLoading) {
      loadListings(currentPageNo + 1);
    }
  }, { root: scrollEl, rootMargin: '100px' }).observe(sentinel);
}

async function openHistory(id, title) {
  document.getElementById('historyTitle').innerText = `Lịch sử giá: ${title}`;
  document.getElementById('historyModal').style.display = 'flex';

  try {
    const res = await fetch(`/api/history/${id}`);
    const data = await res.json();

    if (historyChartInstance) historyChartInstance.destroy();

    const ctx = document.getElementById('historyChartCanvas').getContext('2d');
    historyChartInstance = new Chart(ctx, {
      type: 'line',
      data: {
        labels: (data.history || data).map(d => d.date),
        datasets: [{
          label: 'Giá (tỷ)',
          data: (data.history || data).map(d => d.price_ty),
          borderColor: '#10b981', backgroundColor: 'rgba(16, 185, 129, 0.1)',
          borderWidth: 3, tension: 0.1, fill: true, stepped: true,
          pointRadius: 6, pointHoverRadius: 8,
        }]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          y: { title: { display: true, text: 'Tổng giá (tỷ)' } },
          x: { grid: { display: false } }
        }
      }
    });
  } catch (e) {
    console.error(e);
  }
}

function closeModal(id) {
  document.getElementById(id).style.display = 'none';
}

window.onclick = function (event) {
  if (event.target.classList.contains('modal')) {
    event.target.style.display = 'none';
    if (event.target.id === 'galleryModal') {
      document.body.style.overflow = '';
    }
  }
}

document.addEventListener('keydown', (event) => {
  const galleryModal = document.getElementById('galleryModal');
  if (galleryModal && galleryModal.style.display === 'flex') {
    if (event.key === 'Escape') closeGallery();
    if (event.key === 'ArrowLeft') slideGallery(-1);
    if (event.key === 'ArrowRight') slideGallery(1);
  }
  const leadModal = document.getElementById('leadCaptureModal');
  if (leadModal && leadModal.style.display === 'flex' && event.key === 'Escape') {
    closeLeadCaptureModal();
  }
});

function updateWardFilters(wardsByCity, activeWards, opts = {}) {
  const selectedCity = document.getElementById('cityInput').value;
  const wards = wardsByCity[selectedCity] || [];
  const container = document.getElementById('wardFilters');
  const searchInput = document.getElementById('wardSearch');
  const sidebar = document.getElementById('sidebar');
  const wardScroll = document.querySelector('.ward-scroll-area');
  const sidebarScrollTop = sidebar ? sidebar.scrollTop : 0;
  const wardScrollTop = wardScroll ? wardScroll.scrollTop : 0;
  const preserveSearch = opts.preserveSearch !== false;
  if (searchInput && !preserveSearch) searchInput.value = '';
  const selected = new Set(activeWards || []);
  const shouldCheckAll = selected.size === 0;

  container.innerHTML = wards.map(w => {
    const checked = shouldCheckAll || selected.has(w) ? 'checked' : '';
    return `
      <label class="filter-option">
        <input type="checkbox" name="ward" value="${w}" ${checked}> ${w}
      </label>
    `;
  }).join('');
  updateWardSelectionSummary();

  requestAnimationFrame(() => {
    if (sidebar) sidebar.scrollTop = sidebarScrollTop;
    if (wardScroll) wardScroll.scrollTop = wardScrollTop;
  });
}

// Global listener for Filter changes (Auto-apply)
document.addEventListener('change', (e) => {
  if (e.target.matches('#wardFilters input[name="ward"]')) {
    updateWardSelectionSummary();
  }
  if (e.target.closest('#filterForm')) {
    scheduleApplyFilters();
  }
});

// Init on load
document.addEventListener('DOMContentLoaded', () => {
  showLoader();
  setupListingsObserver();
  if (window.INITIAL_WARDS_BY_CITY) {
    globalWardsByCity = window.INITIAL_WARDS_BY_CITY;
    updateWardFilters(globalWardsByCity, [], { preserveScroll: false, preserveSearch: false });
  }
  if (window.location.search) {
    currentFilters = window.location.search.substring(1);
    applyFilters();
  } else {
    detectLocation();
  }
});

const LEAD_CAPTURE = {
  listingId: null,
  listingUrl: '',
  sourceContext: 'signal',
  urgency: 'standard'
};

function captureLeadAndOpen(listingId, listingUrl, sourceContext = 'signal', urgency = 'standard') {
  LEAD_CAPTURE.listingId = listingId ? Number(listingId) : null;
  LEAD_CAPTURE.listingUrl = listingUrl || '';
  LEAD_CAPTURE.sourceContext = sourceContext || 'signal';
  LEAD_CAPTURE.urgency = urgency || 'standard';
  openGuestLeadForm(listingId, sourceContext, listingUrl);
}

function closeLeadCaptureModal() {
  const modal = document.getElementById('leadCaptureModal');
  const errorEl = document.getElementById('leadError');
  if (errorEl) errorEl.textContent = '';
  if (modal) modal.style.display = 'none';
}

function _openZaloDirect() {
  const zaloHref = 'https://zalo.me/0343216024';
  const w = window.open(zaloHref, '_blank', 'noopener,noreferrer');
  if (!w) window.location.href = zaloHref;
}

function _isLikelyPhone(v) {
  const digits = (v || '').replace(/\D/g, '');
  return digits.length >= 9;
}

async function submitLeadAndOpenZalo() {
  const input = document.getElementById('leadPhoneInput');
  const errorEl = document.getElementById('leadError');
  const raw = (input?.value || '').trim();

  if (!raw) {
    closeLeadCaptureModal();
    _openZaloDirect();
    return;
  }
  if (!_isLikelyPhone(raw)) {
    if (errorEl) errorEl.textContent = 'Số Zalo chưa hợp lệ, vui lòng kiểm tra lại.';
    return;
  }

  try {
    const res = await fetch('/api/leads', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        listing_id: LEAD_CAPTURE.listingId,
        listing_url: LEAD_CAPTURE.listingUrl,
        zalo_phone: raw,
        source_context: LEAD_CAPTURE.sourceContext,
        urgency: LEAD_CAPTURE.urgency
      })
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      if (data && data.error === 'invalid_phone') {
        if (errorEl) errorEl.textContent = 'Số Zalo chưa hợp lệ, vui lòng nhập lại.';
        return;
      }
    }
  } catch (err) {
    console.warn('Lead capture failed:', err);
  } finally {
    closeLeadCaptureModal();
    _openZaloDirect();
  }
}

function skipLeadAndOpenZalo() {
  closeLeadCaptureModal();
  _openZaloDirect();
}

// AI Chat Logic
let chatHistory = [];

function toggleChat() {
  const win = document.getElementById('chatWindow');
  win.style.display = win.style.display === 'flex' ? 'none' : 'flex';
  if (win.style.display === 'flex') {
    document.getElementById('chatInput').focus();
  }
}

async function sendMessage() {
  const input = document.getElementById('chatInput');
  const msg = input.value.trim();
  if (!msg) return;

  // Add user message to UI
  appendMessage('user', msg);
  input.value = '';

  // Add loading indicator
  const loadingId = 'loading-' + Date.now();
  const msgContainer = document.getElementById('chatMessages');
  const loadingDiv = document.createElement('div');
  loadingDiv.className = 'message bot';
  loadingDiv.id = loadingId;
  loadingDiv.innerText = 'RadarBDS AI đang trả lời...';
  msgContainer.appendChild(loadingDiv);
  msgContainer.scrollTop = msgContainer.scrollHeight;

  try {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: msg, history: chatHistory })
    });
    const data = await res.json();

    // Remove loading and show response
    loadingDiv.remove();
    appendMessage('bot', data.response);

    // Update history
    chatHistory.push({ role: 'user', content: msg });
    chatHistory.push({ role: 'assistant', content: data.response });
    if (chatHistory.length > 10) chatHistory = chatHistory.slice(-10); // Keep last 5 turns

  } catch (err) {
    loadingDiv.innerText = 'Lỗi kết nối. Vui lòng thử lại.';
    console.error(err);
  }
}

function appendMessage(role, text) {
  const container = document.getElementById('chatMessages');
  const div = document.createElement('div');
  div.className = `message ${role}`;
  div.innerText = text;
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
}

/* ───────────────────────────────────────────────────────────────
   Conversion tracker — fire-and-forget POST /api/track
   ─────────────────────────────────────────────────────────────── */
window.track = function (action, opts) {
  opts = opts || {};
  try {
    fetch('/api/track', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({
        action: action,
        listing_id: opts.listing_id || null,
        context: opts.context || {},
      }),
      keepalive: true,
    }).catch(() => { });
  } catch (e) { /* silent */ }
};

// Track + nudge wrappers for locked UI elements
function onLockedTabClick(tab, reason) {
  window.track('locked_tab_click', {
    context: { tab: tab || 'unknown', reason: reason || 'tier_required' },
  });
  if (window.RadarAuth && typeof RadarAuth.nudgeVipUpgrade === 'function') {
    RadarAuth.nudgeVipUpgrade(reason || 'Mở khoá Phân Tích Chuyên Sâu');
  }
}

/* ───────────────────────────────────────────────────────────────
   Tier-aware CTA dispatcher + Guest Lead modal
   ─────────────────────────────────────────────────────────────── */
function tierCTA(listingId, url, ctx) {
  const t = window.USER_TIER || 'guest';
  if (t === 'guest') {
    window.track('vip_cta_click', { listing_id: listingId, context: { tier: 'guest', ctx: ctx } });
  } else if (t === 'free') {
    window.track('cta_vip', { listing_id: listingId, context: { tier: 'free', ctx: ctx } });
  } else if (t === 'vip' || t === 'admin') {
    window.track('lead_vip_click', { listing_id: listingId, context: { tier: t, ctx: ctx } });
  }
  openGuestLeadForm(listingId, ctx, url);
}

let _guestLeadListingId = null;
let _guestLeadCtx = null;
let _guestLeadListingUrl = '';

function _currentUserPhone() {
  return ((window.CURRENT_USER && window.CURRENT_USER.phone) || '').trim();
}

function _guestLeadDefaultNote(tier, listingId) {
  const lotRef = listingId ? `#${listingId}` : 'này';
  let note = `Tôi quan tâm lô ${lotRef}, hãy gửi thêm thông tin.`;
  if (tier === 'vip' || tier === 'admin') {
    note += ' Tôi muốn được tư vấn và phân tích 1-1 với chuyên gia.';
  }
  return note;
}

function openGuestLeadForm(listingId, ctx, listingUrl = '') {
  _guestLeadListingId = listingId;
  _guestLeadCtx = ctx || 'card_signal';
  _guestLeadListingUrl = listingUrl || '';
  const tier = window.USER_TIER || 'guest';
  const m = document.getElementById('guestLeadModal');
  if (!m) return;
  const err = document.getElementById('guestLeadError');
  const title = document.getElementById('guestLeadTitle');
  const sub = document.getElementById('guestLeadSub');
  const vipNote = document.getElementById('guestLeadVipNote');
  const contactEl = document.getElementById('guestLeadContact');
  const noteEl = document.getElementById('guestLeadNote');

  if (err) { err.textContent = ''; err.classList.remove('show'); }
  if (title) title.textContent = tier === 'guest' ? 'Yêu cầu RadarBDS ráp mối' : 'Gửi yêu cầu tư vấn';
  if (sub) {
    sub.textContent = tier === 'guest'
      ? 'Chỉ cần để lại SĐT/Zalo, admin sẽ gửi thêm thông tin lô này.'
      : 'RadarBDS đã điền sẵn SĐT từ tài khoản của bạn. Bạn có thể gửi yêu cầu hoặc chat Zalo trực tiếp.';
  }
  if (vipNote) {
    if (tier === 'vip' || tier === 'admin') {
      vipNote.textContent = 'Đặc quyền VIP: yêu cầu này sẽ được ưu tiên và có tư vấn, phân tích 1-1 với chuyên gia.';
      vipNote.style.display = 'flex';
    } else {
      vipNote.textContent = '';
      vipNote.style.display = 'none';
    }
  }
  if (contactEl) contactEl.value = tier === 'guest' ? '' : _currentUserPhone();
  if (noteEl) noteEl.value = _guestLeadDefaultNote(tier, listingId);
  m.classList.add('show');
  setTimeout(() => {
    const contact = document.getElementById('guestLeadContact');
    const submitBtn = document.getElementById('guestLeadSubmitBtn');
    if (contact && !contact.value) contact.focus();
    else if (submitBtn) submitBtn.focus();
  }, 80);
}
function closeGuestLeadModal() {
  const m = document.getElementById('guestLeadModal');
  if (m) m.classList.remove('show');
}
function guestLeadChatZalo() {
  closeGuestLeadModal();
  _openZaloDirect();
}
async function submitGuestLead() {
  const contactEl = document.getElementById('guestLeadContact');
  const noteEl = document.getElementById('guestLeadNote');
  const err = document.getElementById('guestLeadError');
  const btn = document.getElementById('guestLeadSubmitBtn');
  const contact = (contactEl && contactEl.value || '').trim();
  const note = (noteEl && noteEl.value || '').trim();
  if (!contact) {
    if (err) { err.textContent = 'Vui lòng nhập số điện thoại/Zalo.'; err.classList.add('show'); }
    return;
  }
  if (!_isLikelyPhone(contact)) {
    if (err) { err.textContent = 'Số điện thoại chưa hợp lệ, vui lòng kiểm tra lại.'; err.classList.add('show'); }
    return;
  }
  if (btn) btn.disabled = true;
  try {
    const res = await fetch('/api/lead-capture-guest', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        listing_id: _guestLeadListingId,
        listing_url: _guestLeadListingUrl,
        contact,
        note,
        context: _guestLeadCtx,
      }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.ok === false) {
      if (err) { err.textContent = data.error || 'Không gửi được, thử lại sau.'; err.classList.add('show'); }
      return;
    }
    closeGuestLeadModal();
    alert('Đã gửi yêu cầu. RadarBDS sẽ liên hệ và gửi thêm thông tin cho bạn.');
  } catch (e) {
    if (err) { err.textContent = 'Mất kết nối, thử lại sau.'; err.classList.add('show'); }
  } finally {
    if (btn) btn.disabled = false;
  }
}


