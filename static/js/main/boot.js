// DOM event wiring and initial dashboard boot sequence.
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
    const wardName = escHtml(w);
    return `
      <label class="filter-option">
        <input type="checkbox" name="ward" value="${wardName}" ${checked}>
        <span class="ward-option-name">${wardName}</span>
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
    if (window.RadarAreaScope && typeof window.persistCurrentAreaScope === 'function') {
      window.persistCurrentAreaScope({ updateUrl: true });
    }
  }
  if (e.target.closest('#filterForm')) {
    scheduleApplyFilters();
  }
});

// Init on load
document.addEventListener('DOMContentLoaded', () => {
  showLoader();
  if (typeof setupListingsViewToggle === 'function') setupListingsViewToggle();
  if (typeof setupListingsObserver === 'function') setupListingsObserver();
  if (window.RADAR_SAVED_PAGE) {
    if (typeof loadSavedListingsPage === 'function') {
      loadSavedListingsPage(false);
    } else {
      hideLoader();
    }
    return;
  }
  const searchParams = new URLSearchParams(window.location.search);
  const initialTab = searchParams.get('tab') || window.location.hash.replace(/^#/, '');
  const shouldOpenInitialTab = ['signals', 'all', 'market', 'insights'].includes(initialTab);
  if (shouldOpenInitialTab) searchParams.delete('tab');
  const landingIntent = (searchParams.get('intent') || '').trim().toLowerCase();
  if (landingIntent) searchParams.delete('intent');
  if (typeof syncKeywordSearchInputs === 'function') {
    syncKeywordSearchInputs(searchParams.get('q') || searchParams.get('keyword') || '');
  }
  const initialCity = searchParams.get('city');
  if (initialCity) {
    const cityInput = document.getElementById('cityInput');
    if (cityInput) cityInput.value = initialCity;
    document.querySelectorAll('.city-pill').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.city === initialCity);
    });
  }
  const initialDateRange = searchParams.get('date_range');
  if (initialDateRange) {
    const dateRadio = document.querySelector(`input[name="date_range"][value="${CSS.escape(initialDateRange)}"]`);
    if (dateRadio) dateRadio.checked = true;
  }
  const initialMosMin = searchParams.get('mos_min');
  if (initialMosMin !== null) {
    const mosSlider = document.getElementById('mosSlider');
    if (mosSlider && !mosSlider.disabled) mosSlider.value = initialMosMin;
  }
  const initialPropTypes = searchParams.getAll('prop_type').filter(Boolean);
  if (initialPropTypes.length) {
    document.querySelectorAll('input[name="prop_type"]').forEach(box => {
      box.checked = initialPropTypes.includes(box.value);
    });
  }
  if (typeof syncCoreFilterVisuals === 'function') syncCoreFilterVisuals();
  if (window.INITIAL_WARDS_BY_CITY) {
    globalWardsByCity = window.INITIAL_WARDS_BY_CITY;
    updateWardFilters(globalWardsByCity, searchParams.getAll('ward'), { preserveScroll: false, preserveSearch: false });
  }

  let handledInitialAreaScope = false;
  if (window.RadarAreaScope && window.INITIAL_WARDS_BY_CITY) {
    const urlScope = window.RadarAreaScope.scopeFromSearchParams(searchParams, globalWardsByCity);
    const hasAnyUrlFilter = searchParams.toString().length > 0;
    if (urlScope) {
      window.RadarAreaScope.syncScopeControls(urlScope, globalWardsByCity, document, updateWardFilters);
      window.RadarAreaScope.updateScopeUi(urlScope, document);
      window.RadarAreaScope.saveScope(urlScope, window.localStorage);
      currentFilters = searchParams.toString();
      applyFilters();
      handledInitialAreaScope = true;
    } else if (!hasAnyUrlFilter) {
      const storedScope = window.RadarAreaScope.readStoredScope(window.localStorage, globalWardsByCity);
      if (storedScope) {
        window.RadarAreaScope.syncScopeControls(storedScope, globalWardsByCity, document, updateWardFilters);
        window.RadarAreaScope.updateScopeUi(storedScope, document);
        window.RadarAreaScope.replaceUrlWithScope(storedScope);
        applyFilters();
      } else {
        window.RadarAreaScope.showChooser(document);
        hideLoader();
      }
      handledInitialAreaScope = true;
    }
  }

  if (!handledInitialAreaScope) {
    if (searchParams.toString()) {
      currentFilters = searchParams.toString();
      applyFilters();
    } else {
      applyFilters();
    }
  }
  if (shouldOpenInitialTab && initialTab !== 'signals') {
    requestAnimationFrame(() => switchTab(initialTab, null));
  }
  if (landingIntent === 'watchlist' && window.RadarAuth && typeof window.RadarAuth.openWatchlistModal === 'function') {
    setTimeout(() => {
      window.RadarAuth.openWatchlistModal();
    }, 180);
  }
});
