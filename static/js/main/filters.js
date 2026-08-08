// Sidebar filters, city/ward controls, sorting, and dashboard metadata refresh.
function selectCity(btn) {
  document.querySelectorAll('.city-pill').forEach(p => p.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById('cityInput').value = btn.dataset.city;
  updateWardFilters(globalWardsByCity, [], { preserveScroll: false, preserveSearch: false });
  if (window.RadarAreaScope && typeof window.RadarAreaScope.applyDashboardScope === 'function') {
    window.RadarAreaScope.applyDashboardScope({
      version: 1,
      city: btn.dataset.city,
      wards: [],
      mode: 'city_all',
    }, { persist: true, updateUrl: true, apply: true });
    return;
  }
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

function getKeywordSearchValue() {
  const input = document.querySelector('.keyword-search-input');
  return input ? input.value.trim().replace(/\s+/g, ' ').slice(0, 80) : '';
}

function syncCoreFilterVisuals() {
  const mosSlider = document.getElementById('mosSlider');
  const mosValue = document.getElementById('mosValue');
  const mosShell = document.querySelector('.command-mos');
  if (mosSlider) {
    const min = Number(mosSlider.min || 0);
    const max = Number(mosSlider.max || 70);
    const value = Number(mosSlider.value || 0);
    const pct = max > min ? Math.max(0, Math.min(100, ((value - min) / (max - min)) * 100)) : 0;
    mosSlider.style.setProperty('--mos-progress', `${pct}%`);
    if (mosShell) mosShell.dataset.mosLevel = value >= 25 ? 'strong' : value >= 10 ? 'active' : 'open';
    if (mosValue) mosValue.textContent = String(value);
  }

  const onlyDrops = document.querySelector('input[name="only_drops"]');
  const dropShell = onlyDrops ? onlyDrops.closest('.command-drop-toggle') : null;
  if (dropShell) dropShell.classList.toggle('is-active', Boolean(onlyDrops.checked));
}

function syncKeywordSearchInputs(value, source = null) {
  const normalized = String(value || '').slice(0, 80);
  document.querySelectorAll('.keyword-search-input').forEach(input => {
    if (input !== source && input.value !== normalized) input.value = normalized;
    const root = input.closest('.keyword-search');
    if (root) root.classList.toggle('has-value', normalized.length > 0);
  });
}

function onKeywordSearchInput(input) {
  syncKeywordSearchInputs(input.value, input);
  scheduleApplyFilters();
}

function clearKeywordSearch() {
  syncKeywordSearchInputs('');
  scheduleApplyFilters();
  const activeInput = document.querySelector(`#tab-${activeTabId()} .keyword-search-input`) || document.querySelector('.keyword-search-input');
  if (activeInput) activeInput.focus();
}

function setAllWards(checked) {
  document.querySelectorAll('#wardFilters input[name="ward"]').forEach(box => {
    box.checked = checked;
  });
  updateWardSelectionSummary();
  if (checked && window.RadarAreaScope && typeof window.selectCurrentCityAllAreaScope === 'function') {
    window.selectCurrentCityAllAreaScope();
    return;
  }
  scheduleApplyFilters();
}

function getFilterQuery() {
  const form = document.getElementById('filterForm');
  const fd = new FormData(form);
  const params = new URLSearchParams();
  for (let [k, v] of fd.entries()) {
    params.append(k, v);
  }
  const hideGulandReposts = document.getElementById('hideGulandReposts');
  if (hideGulandReposts) {
    params.set(
      'hide_guland_reposts',
      hideGulandReposts.checked ? '1' : '0'
    );
  }
  selectedRangeTokens('price').forEach(token => params.append('price_range', token));
  selectedRangeTokens('area').forEach(token => params.append('area_range', token));
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
  const keyword = getKeywordSearchValue();
  if (keyword) {
    params.set('q', keyword);
  }
  params.append('trend_period', trendPeriod);
  return window.RadarFilterRuntime.canonicalize(params);
}

function rangeToken(btn) {
  const min = btn?.dataset.min ?? '';
  const max = btn?.dataset.max ?? '';
  return `${min}:${max}`;
}

function selectedRangeTokens(kind) {
  return Array.from(document.querySelectorAll(`.range-chip.active[data-range-kind="${kind}"]`))
    .map(rangeToken)
    .filter(token => token !== ':');
}

function applyRangeParamsFromUrl(kind, tokens) {
  const selectedTokens = new Set((tokens || []).map(String).filter(Boolean));
  document.querySelectorAll(`.range-chip[data-range-kind="${kind}"]`).forEach(btn => {
    const selected = selectedTokens.has(rangeToken(btn));
    btn.classList.toggle('active', selected);
    btn.setAttribute('aria-pressed', selected ? 'true' : 'false');
  });
  if (selectedTokens.size) {
    setRangeInputs(kind, '', '');
  }
}

function setRangeInputs(kind, min = '', max = '') {
  const prefix = kind === 'price' ? 'price' : 'area';
  const minEl = document.getElementById(`${prefix}Min`);
  const maxEl = document.getElementById(`${prefix}Max`);
  if (minEl) minEl.value = min === null || min === undefined ? '' : String(min);
  if (maxEl) maxEl.value = max === null || max === undefined ? '' : String(max);
}

function clearRangeFilters(kind) {
  document.querySelectorAll(`.range-chip[data-range-kind="${kind}"]`).forEach(btn => {
    btn.classList.remove('active');
    btn.setAttribute('aria-pressed', 'false');
  });
  setRangeInputs(kind, '', '');
  scheduleApplyFilters();
}

function onManualRangeInput(kind) {
  document.querySelectorAll(`.range-chip[data-range-kind="${kind}"]`).forEach(btn => {
    btn.classList.remove('active');
    btn.setAttribute('aria-pressed', 'false');
  });
  scheduleApplyFilters();
}

function toggleRangePreset(btn, kind) {
  if (!btn) return;
  btn.classList.toggle('active');
  btn.setAttribute('aria-pressed', btn.classList.contains('active') ? 'true' : 'false');
  setRangeInputs(kind, '', '');
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
  syncCoreFilterVisuals();
  scheduleApplyFilters();
}

document.addEventListener('input', (e) => {
  if (e.target && e.target.id === 'mosSlider') syncCoreFilterVisuals();
});

document.addEventListener('change', (e) => {
  if (e.target && (e.target.id === 'mosSlider' || e.target.name === 'only_drops')) syncCoreFilterVisuals();
});

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
  document.querySelectorAll('.p-pill').forEach((button) => {
    button.classList.remove('active');
    button.setAttribute('aria-pressed', 'false');
  });
  btn.classList.add('active');
  btn.setAttribute('aria-pressed', 'true');

  currentFilters = getFilterQuery();
  ensureDashboardScript('market').then(() => loadTrendData(false)).catch((err) => console.error(err));
}

function deferCountsRefresh(useCache = false) {
  const run = () => refreshCounts(useCache);
  if (typeof window.requestIdleCallback === 'function') {
    window.requestIdleCallback(run, { timeout: 1200 });
  } else {
    setTimeout(run, 100);
  }
}

function applyFilters() {
  currentFilters = getFilterQuery();
  if (window.RadarAreaScope && window.RADAR_AREA_SCOPE_SKIP_PERSIST_ONCE) {
    window.RADAR_AREA_SCOPE_SKIP_PERSIST_ONCE = false;
    if (typeof window.RadarAreaScope.refreshCurrentScopeUi === 'function') {
      window.RadarAreaScope.refreshCurrentScopeUi();
    }
  } else if (window.RadarAreaScope && typeof window.persistCurrentAreaScope === 'function') {
    window.persistCurrentAreaScope({ updateUrl: false });
  } else if (window.RadarAreaScope && typeof window.RadarAreaScope.refreshCurrentScopeUi === 'function') {
    window.RadarAreaScope.refreshCurrentScopeUi();
  }
  const filterSnapshot = currentFilters;
  currentPageNo = 1;
  listingsHasMore = false;
  const tab = activeTabId();

  if (tab === 'signals') {
    window.RadarFilterRuntime.runSignalFirst(
      () => loadSignals(1, { reset: true }),
      () => deferCountsRefresh(false),
      () => currentFilters === filterSnapshot,
    ).catch((err) => {
      if (err && err.name !== 'AbortError') console.error(err);
    });
  } else {
    refreshCounts(false);
    refreshDashboardMeta(false);
  }

  if (tab === 'market') {
    ensureDashboardScript('market')
      .then(() => {
        loadMarketIndicators(false);
        loadMarketCharts(false);
        loadTrendData(false);
      })
      .catch((err) => console.error(err));
  }
  if (tab === 'insights') {
    loadInsights(false);
  }
  if (tab === 'all') {
    ensureDashboardScript('listings')
      .then(() => { initializeListingsUi(); loadListings(1); })
      .catch((err) => console.error(err));
  }
}

function scheduleApplyFilters() {
  clearTimeout(filterDebounceTimer);
  filterDebounceTimer = setTimeout(applyFilters, 200);
}

async function initDashboard() {
  refreshCounts(false);
  return refreshDashboardMeta(false);
}

function applyStatsCounts(stats = {}) {
  const statTotal = document.getElementById('statTotal');
  const statSignals = document.getElementById('statSignals');
  const statNewRecent = document.getElementById('statNewRecent');
  const badgeSignals = document.getElementById('badgeSignals');
  const badgeTotal = document.getElementById('badgeTotal');

  if (Object.prototype.hasOwnProperty.call(stats, 'total')) {
    const total = Number(stats.total || 0);
    if (statTotal) statTotal.innerText = total;
    if (badgeTotal) badgeTotal.innerText = total;
  }
  if (Object.prototype.hasOwnProperty.call(stats, 'signals')) {
    const signals = Number(stats.signals || 0);
    if (statSignals) statSignals.innerText = signals;
    if (badgeSignals) badgeSignals.innerText = signals;
  }
  if (Object.prototype.hasOwnProperty.call(stats, 'new_recent_days_7')) {
    const newRecent = Number(stats.new_recent_days_7 || 0);
    if (statNewRecent) statNewRecent.innerText = newRecent;
  }
  if (typeof syncMobileBadges === 'function') syncMobileBadges();
}

async function refreshCounts(useCache = false) {
  const runId = ++countsRunSeq;
  try {
    const data = await fetchJSONCached('counts', `/api/counts?${currentFilters}`, useCache);
    if (runId !== countsRunSeq) return;
    applyStatsCounts(data.stats || {});
  } catch (err) {
    if (err.name === 'AbortError') return;
    console.error(err);
  }
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
    if (typeof syncMobileBadges === 'function') syncMobileBadges();

    // Update Wards based on City
    globalWardsByCity = data.wards_by_city;
    updateWardFilters(data.wards_by_city, data.active_wards, { preserveScroll: true });
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
