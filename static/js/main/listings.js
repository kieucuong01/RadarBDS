// All-listings table/grid filtering, sorting, pagination, and lazy loading.
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

function renderListingSkeletonCards(grid) {
  if (!grid) return;
  grid.innerHTML = Array.from({ length: 6 }).map(() => `
    <div class="scard" style="min-height:420px; opacity:.65; pointer-events:none;" aria-hidden="true">
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

function listingFairPrice(x) {
  const fairPpm2 = Number(x.fair_ppm2);
  const area = Number(x.area_m2);
  if (!Number.isFinite(fairPpm2) || !Number.isFinite(area) || area <= 0) return '-';
  return (fairPpm2 * area / 1000).toFixed(2);
}

function listingImage(x) {
  return x.imgs && x.imgs.length ? x.imgs[0] : PLACEHOLDER_IMG;
}

function listingDataAttrs(x, fair, imgSrc) {
  const priceNum = Number(x.price_ty);
  const fairNum = Number(fair);
  const profit = Number.isFinite(priceNum) && Number.isFinite(fairNum) ? (fairNum - priceNum).toFixed(2) : '';
  return [
    ['id', x.id],
    ['title', x.title || ''],
    ['primary', imgSrc || ''],
    ['price', x.price_ty || ''],
    ['ppm2', x.price_per_m2 || ''],
    ['fair', fair !== '-' ? fair : ''],
    ['fppm2', x.fair_ppm2 || ''],
    ['area', x.area_m2 || ''],
    ['ward', x.ward || ''],
    ['road', x.road_type || x.road_tier || ''],
    ['time', _timeAgoText(x.days_ago)],
    ['profit', profit],
    ['mos', x.mos_pct || ''],
    ['source', sourceNames[x.source] || x.source || ''],
    ['drop', x.drop_pct || ''],
    ['score', x.signal_score || ''],
    ['url', x.url || ''],
    ['ptype', x.prop_type || ''],
  ].map(([key, value]) => `data-${key}="${escHtml(value)}"`).join(' ');
}

function listingTableRow(x) {
  const fair = listingFairPrice(x);
  const imgSrc = listingImage(x);
  const dataAttr = listingDataAttrs(x, fair, imgSrc);
  const priceLabel = x.price_label || (x.price_ty ? `${x.price_ty} tỷ` : '-');
  return `
    <tr class="clickable-row" onclick="openListingModal(this)" ${dataAttr}>
      <td><span style="font-size:0.75rem; font-weight:700; color:var(--text-muted);">${escHtml(x.prop_type || '-')}</span></td>
      <td><span style="padding:4px 8px; border-radius:6px; font-weight:600; font-size:0.8rem;">${escHtml(x.ward || '-')}</span></td>
      <td><img src="${escHtml(imgSrc)}" class="td-img" loading="lazy" onerror="this.onerror=null;this.src=PLACEHOLDER_IMG"></td>
      <td style="font-weight:700;">${x.area_m2 ? `${escHtml(x.area_m2)} m²` : '-'}</td>
      <td>
        <div style="color:var(--accent); font-weight:800; font-size:1rem;">${escHtml(priceLabel)}</div>
        <div style="font-size:0.75rem; color:var(--text-muted); margin-top:2px;">${x.price_per_m2 ? `${escHtml(x.price_per_m2)} tr/m²` : '-'}</div>
      </td>
      <td>
        <div style="color:var(--primary); font-weight:800;">${fair !== '-' ? `${fair} tỷ` : '-'}</div>
        <div style="font-size:0.75rem; color:var(--primary); opacity:0.8; margin-top:2px;">${x.fair_ppm2 ? `${escHtml(x.fair_ppm2)} tr/m²` : '-'}</div>
      </td>
      <td style="white-space:nowrap; font-size:0.8rem; color:var(--text-muted);">
        <div>${escHtml(x.posted_at || '-')}</div>
        <div style="font-size:0.72rem; opacity:0.7;">${escHtml(_timeAgoText(x.days_ago))}</div>
      </td>
      <td style="max-width: 300px;">
        <div class="td-title" title="${escHtml(x.title || '')}">${escHtml(x.title || '-')}</div>
        <div class="td-desc" title="${escHtml(x.description || '')}">${renderTextWithContactCta(x.description || '', x.id, 'redacted_description_table')}</div>
      </td>
    </tr>
  `;
}

function listingCard(x) {
  const fair = listingFairPrice(x);
  const fairNum = Number(fair);
  const priceNum = Number(x.price_ty);
  const isOverpriced = Number.isFinite(priceNum) && Number.isFinite(fairNum) && priceNum > fairNum;
  const actualClass = isOverpriced ? 'price-over' : 'price-deal';
  const priceLabel = x.price_label || (x.price_ty ? `${x.price_ty} tỷ` : '-');
  const imgSrc = listingImage(x);
  const dataAttr = listingDataAttrs(x, fair, imgSrc);
  const daysAgo = _daysAgoValue(x.days_ago);
  const timeStr = _timeAgoText(daysAgo);
  const sourceName = sourceNames[x.source] || x.source || '-';
  const isNew = _isNewWithin(x.days_ago, 7);
  const mosNum = Number(x.mos_pct);
  const mosRounded = Math.round(mosNum || 0);
  const mosBadge = Number.isFinite(mosNum) && mosNum > 0
    ? `<div class="mos-badge"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4"><rect x="4" y="9" width="16" height="10" rx="4"/><circle cx="9" cy="14" r="1"/><circle cx="15" cy="14" r="1"/><path d="M12 9V5"/><circle cx="12" cy="4" r="1"/></svg> Rẻ hơn ${mosRounded}%</div>`
    : '';
  const newBadge = isNew ? `<div class="new-badge"><svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/></svg> MỚI</div>` : '';
  const dropBadge = x.price_dropped
    ? `<span class="sc-drop-tag"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="12 4 12 20"/><polyline points="6 14 12 20 18 14"/></svg> Chủ hạ: ${x.drop_pct ? `${escHtml(x.drop_pct)}%` : 'N/A'}</span>`
    : '';
  const propType = PROPERTY_TYPE_LABELS[x.prop_type] || x.prop_type || '-';
  const imageCount = Array.isArray(x.imgs) ? x.imgs.length : 0;
  const imageCounterHtml = imageCount > 1 ? `<div class="sc-image-count">1/${imageCount}</div>` : '';
  const areaLabel = typeof _signalAreaLabel === 'function' ? _signalAreaLabel(x) : (x.area_m2 ? `${x.area_m2}m²` : '-');
  const roadTiers = {
    1: 'Mặt tiền',
    2: 'Đường nhựa',
    3: 'Hẻm xe hơi',
    4: 'Hẻm xe máy'
  };
  const roadStr = roadTiers[x.road_tier] || x.road_type || 'Chưa rõ';

  return `
    <div class="scard listing-grid-card" onclick="openListingModal(this)" ${dataAttr}>
      <div class="sc-img-wrap">
        <img class="sc-img" src="${escHtml(imgSrc)}" loading="lazy" decoding="async" width="640" height="416" alt="Img" onerror="this.onerror=null;this.src=PLACEHOLDER_IMG">
        ${mosBadge}
        ${newBadge}
        ${imageCounterHtml}
        <div class="sc-img-tags">
          <span class="sc-source-tag">${escHtml(sourceName)}</span>
          <span class="sc-time-tag"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg> ${escHtml(timeStr)}</span>
          ${dropBadge}
        </div>
      </div>
      <div class="sc-body">
        <div class="sc-title" title="${escHtml(x.title || '')}">${escHtml(x.title || '-')}</div>

        <div class="price-container">
          <div class="price-actual">
            <span class="price-label price-label-actual ${actualClass}">THỰC TẾ</span>
            <div class="price-val ${actualClass}">${escHtml(priceLabel)}</div>
            <div class="price-m2">${x.price_per_m2 ? `${escHtml(x.price_per_m2)} tr/m²` : '-'}</div>
          </div>
          <div class="price-fair">
            <span class="price-label price-label-fair">ĐỊNH GIÁ</span>
            <div class="price-val-fair">${fair !== '-' ? `${fair} tỷ` : '-'}</div>
            <div class="price-m2">${x.fair_ppm2 ? `${escHtml(x.fair_ppm2)} tr/m²` : '-'}</div>
          </div>
        </div>

        <div class="sc-meta-chips">
          <span class="meta-chip"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/></svg>${escHtml(x.ward || 'Chưa rõ')}</span>
          <span class="meta-chip meta-chip-area"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/></svg>${escHtml(areaLabel)}</span>
          <span class="meta-chip"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"/><line x1="4" y1="22" x2="4" y2="15"/></svg>${escHtml(roadStr)}</span>
          <span class="meta-chip"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 7h18"/><path d="M7 3v18"/><path d="M17 3v18"/><path d="M3 17h18"/></svg>${escHtml(propType)}</span>
        </div>

        <div class="sc-actions" onclick="event.stopPropagation()">
          <a href="#" onclick="event.preventDefault();const c=this.closest('.scard').dataset;tierCTA(c.id,c.url,'card_all');" class="btn-zalo"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg> ${(window.USER_TIER === 'vip' || window.USER_TIER === 'admin') ? 'Ráp mối VIP' : 'Ráp mối'}</a>
        </div>
      </div>
    </div>
  `;
}

function renderListingRows(items, options = {}) {
  const tbody = document.getElementById('listingsTableBody');
  if (!tbody) return;
  if (!options.append) tbody.innerHTML = '';
  tbody.insertAdjacentHTML('beforeend', (items || []).map(listingTableRow).join(''));
}

function renderListingCards(items, options = {}) {
  const grid = document.getElementById('listingsGrid');
  if (!grid) return;
  if (!options.append) grid.innerHTML = '';
  grid.insertAdjacentHTML('beforeend', (items || []).map(listingCard).join(''));
}

function renderLoadedListings() {
  if (listingsView === 'grid') {
    renderListingCards(loadedListings, { append: false });
  } else {
    renderListingRows(loadedListings, { append: false });
  }
}

function setListingsSentinelText(text) {
  ['listingsSentinel', 'listingsGridSentinel'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.textContent = text || '';
  });
}

function setListingsView(view, options = {}) {
  listingsView = view === 'grid' ? 'grid' : 'table';
  const isGrid = listingsView === 'grid';
  document.getElementById('listingsTableView')?.toggleAttribute('hidden', isGrid);
  document.getElementById('listingsGridView')?.toggleAttribute('hidden', !isGrid);
  document.getElementById('tab-all')?.classList.toggle('listings-grid-mode', isGrid);
  document.getElementById('listingsViewTable')?.classList.toggle('active', !isGrid);
  document.getElementById('listingsViewGrid')?.classList.toggle('active', isGrid);
  document.getElementById('listingsViewTable')?.setAttribute('aria-pressed', String(!isGrid));
  document.getElementById('listingsViewGrid')?.setAttribute('aria-pressed', String(isGrid));
  try { localStorage.setItem('listingsViewV2', listingsView); } catch (e) {}
  if (options.render !== false) {
    renderLoadedListings();
    if (activeTabId() === 'all' && loadedListings.length === 0 && !listingsLoading) {
      loadListings(1);
    }
  }
}

function setupListingsViewToggle() {
  let savedView = 'grid';
  try { savedView = localStorage.getItem('listingsViewV2') || 'grid'; } catch (e) {}
  setListingsView(savedView, { render: false });
  document.querySelectorAll('.listings-view-btn').forEach(btn => {
    btn.addEventListener('click', () => setListingsView(btn.dataset.view || 'table'));
  });
}

async function loadListings(page) {
  if (listingsLoading) return;
  listingsLoading = true;
  const tbody = document.getElementById('listingsTableBody');
  const grid = document.getElementById('listingsGrid');
  if (page === 1) {
    listingsHasMore = false;
    loadedListings = [];
    if (listingsView === 'grid') {
      renderListingSkeletonCards(grid);
    } else {
      renderListingSkeletonRows(tbody);
    }
  }
  if (tbody) tbody.classList.add('loading');
  if (grid) grid.classList.add('is-refreshing');
  setListingsSentinelText('Đang tải...');
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
    setListingsSentinelText(listingsHasMore ? '' : `Đã hiển thị tất cả ${data.total} tin`);
    const items = data.listings || [];
    loadedListings = page === 1 ? items.slice() : loadedListings.concat(items);
    if (listingsView === 'grid') {
      renderListingCards(items, { append: page !== 1 });
    } else {
      renderListingRows(items, { append: page !== 1 });
    }
  } catch (e) {
    if (e.name !== 'AbortError') console.error(e);
    if (page === 1) {
      if (tbody) tbody.innerHTML = '<tr><td colspan="8" class="indicator-empty-row">Không tải được dữ liệu. Vui lòng thử lại.</td></tr>';
      if (grid) grid.innerHTML = '<div class="listing-grid-empty">Không tải được dữ liệu. Vui lòng thử lại.</div>';
    }
    setListingsSentinelText('');
  } finally {
    if (tbody) tbody.classList.remove('loading');
    if (grid) grid.classList.remove('is-refreshing');
    listingsLoading = false;
  }
}

function setupListingsObserver() {
  const tableSentinel = document.getElementById('listingsSentinel');
  const scrollEl = document.querySelector('.table-scroll');
  if (tableSentinel && scrollEl) {
    new IntersectionObserver(entries => {
      if (entries[0].isIntersecting && listingsView === 'table' && listingsHasMore && !listingsLoading) {
        loadListings(currentPageNo + 1);
      }
    }, { root: scrollEl, rootMargin: '100px' }).observe(tableSentinel);
  }

  const gridSentinel = document.getElementById('listingsGridSentinel');
  const gridRoot = document.getElementById('tab-all');
  if (!gridSentinel || !gridRoot) return;
  new IntersectionObserver(entries => {
    if (entries[0].isIntersecting && listingsView === 'grid' && listingsHasMore && !listingsLoading) {
      loadListings(currentPageNo + 1);
    }
  }, { root: gridRoot, rootMargin: '400px' }).observe(gridSentinel);
}
