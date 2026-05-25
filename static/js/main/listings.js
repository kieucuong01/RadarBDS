// All-listings table filtering, sorting, pagination, and lazy loading.
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

function renderListingSkeletonRows(tbody) {
  if (!tbody) return;
  tbody.innerHTML = Array.from({ length: 6 }).map(() => `
    <tr class="listing-skeleton-row" aria-hidden="true">
      <td><span class="skeleton-line short"></span></td>
      <td><span class="skeleton-line"></span></td>
      <td><span class="skeleton-line skeleton-thumb"></span></td>
      <td><span class="skeleton-line short"></span></td>
      <td><span class="skeleton-line"></span></td>
      <td><span class="skeleton-line"></span></td>
      <td><span class="skeleton-line short"></span></td>
      <td><span class="skeleton-line"></span></td>
    </tr>
  `).join('');
}

async function loadListings(page) {
  if (listingsLoading) return;
  listingsLoading = true;
  const tbody = document.getElementById('listingsTableBody');
  const sentinel = document.getElementById('listingsSentinel');
  if (page === 1) {
    listingsHasMore = false;
    renderListingSkeletonRows(tbody);
  }
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
    if (page === 1) tbody.innerHTML = '';
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
    if (page === 1) {
      tbody.innerHTML = '<tr><td colspan="8" class="indicator-empty-row">Không tải được dữ liệu. Vui lòng thử lại.</td></tr>';
    }
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
