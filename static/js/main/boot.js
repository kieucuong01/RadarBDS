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
  const searchParams = new URLSearchParams(window.location.search);
  const initialTab = searchParams.get('tab') || window.location.hash.replace(/^#/, '');
  const shouldOpenInitialTab = ['signals', 'all', 'market', 'insights'].includes(initialTab);
  if (shouldOpenInitialTab) searchParams.delete('tab');
  if (typeof syncKeywordSearchInputs === 'function') {
    syncKeywordSearchInputs(searchParams.get('q') || searchParams.get('keyword') || '');
  }
  if (typeof syncCoreFilterVisuals === 'function') syncCoreFilterVisuals();
  if (window.INITIAL_WARDS_BY_CITY) {
    globalWardsByCity = window.INITIAL_WARDS_BY_CITY;
    updateWardFilters(globalWardsByCity, [], { preserveScroll: false, preserveSearch: false });
  }
  if (searchParams.toString()) {
    currentFilters = searchParams.toString();
    applyFilters();
  } else {
    detectLocation();
  }
  if (shouldOpenInitialTab && initialTab !== 'signals') {
    requestAnimationFrame(() => switchTab(initialTab, null));
  }
});
