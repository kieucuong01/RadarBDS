// Sidebar filters, city/ward controls, sorting, and dashboard metadata refresh.
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
