// Signal feed, insights panels, and infinite-scroll card rendering.
let _sigObserver = null;
let favoriteListingIds = new Set();
let favoriteListingsLoaded = false;
let favoriteListingsPromise = null;
let favoriteListingsUserKey = null;

function favoriteIconSvg() {
  return '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.6l-1-1a5.5 5.5 0 1 0-7.8 7.8l1 1L12 21l7.8-7.6 1-1a5.5 5.5 0 0 0 0-7.8Z"/></svg>';
}

function favoriteButtonHtml(listingId) {
  const id = Number(listingId);
  const active = favoriteListingIds.has(id);
  return `
    <button type="button" class="favorite-btn ${active ? 'is-favorite' : ''}"
      data-listing-id="${escHtml(id)}"
      aria-pressed="${active ? 'true' : 'false'}"
      title="${active ? 'Bỏ lưu lô này' : 'Lưu lô này'}"
      onclick="toggleFavoriteListing(${escHtml(id)}, event)">
      ${favoriteIconSvg()}
      <span>Lưu</span>
    </button>
  `;
}

function updateFavoriteButtonState(btn, favorite) {
  if (!btn) return;
  btn.classList.toggle('is-favorite', favorite);
  btn.setAttribute('aria-pressed', favorite ? 'true' : 'false');
  btn.title = favorite ? 'Bỏ lưu lô này' : 'Lưu lô này';
  const label = btn.querySelector('span');
  if (label) label.textContent = 'Lưu';
}

function refreshFavoriteButtons() {
  document.querySelectorAll('.favorite-btn[data-listing-id]').forEach((btn) => {
    const id = Number(btn.dataset.listingId);
    updateFavoriteButtonState(btn, favoriteListingIds.has(id));
  });
}

async function loadFavoriteListings() {
  const userKey = window.CURRENT_USER ? String(window.CURRENT_USER.id || window.CURRENT_USER.email || window.CURRENT_USER.phone || 'user') : 'guest';
  if (favoriteListingsUserKey !== userKey) {
    favoriteListingIds = new Set();
    favoriteListingsLoaded = false;
    favoriteListingsPromise = null;
    favoriteListingsUserKey = userKey;
  }
  if (!window.CURRENT_USER) {
    favoriteListingIds = new Set();
    favoriteListingsLoaded = true;
    refreshFavoriteButtons();
    return;
  }
  if (favoriteListingsLoaded) {
    refreshFavoriteButtons();
    return;
  }
  if (!favoriteListingsPromise) {
    favoriteListingsPromise = fetch('/api/favorites', { credentials: 'same-origin', cache: 'no-store' })
      .then((res) => {
        if (!res.ok) throw new Error(`favorites ${res.status}`);
        return res.json();
      })
      .then((data) => {
        favoriteListingIds = new Set((data.listing_ids || []).map(Number));
        favoriteListingsLoaded = true;
      })
      .catch(() => {
        favoriteListingsLoaded = true;
      })
      .finally(() => {
        favoriteListingsPromise = null;
        refreshFavoriteButtons();
      });
  }
  return favoriteListingsPromise;
}

function setFavoriteListingState(listingId, favorite) {
  const id = Number(listingId);
  if (favorite) favoriteListingIds.add(id);
  else favoriteListingIds.delete(id);
  favoriteListingsLoaded = true;
  refreshFavoriteButtons();
  if (window.RADAR_SAVED_PAGE && !favorite) {
    const savedCard = document.querySelector(`#savedListingsGrid .scard[data-id="${id}"]`);
    if (savedCard) savedCard.remove();
    updateSavedListingsEmptyState();
  }
}

async function toggleFavoriteListing(listingId, event) {
  if (event) {
    event.preventDefault();
    event.stopPropagation();
  }
  const id = Number(listingId);
  if (!Number.isFinite(id) || id <= 0) return;
  if (!window.CURRENT_USER) {
    if (window.RadarAuth && typeof window.RadarAuth.openAuthModal === 'function') {
      window.RadarAuth.openAuthModal('Đăng nhập để lưu lô đất ưa thích.');
    }
    return;
  }
  const favorite = favoriteListingIds.has(id);
  const buttons = Array.from(document.querySelectorAll(`.favorite-btn[data-listing-id="${id}"]`));
  buttons.forEach((btn) => { btn.disabled = true; });
  try {
    const res = await fetch(`/api/favorites/${encodeURIComponent(id)}`, {
      method: favorite ? 'DELETE' : 'POST',
      credentials: 'same-origin',
    });
    if (res.status === 403 && window.RadarAuth && typeof window.RadarAuth.openAuthModal === 'function') {
      window.RadarAuth.openAuthModal('Đăng nhập để lưu lô đất ưa thích.');
      return;
    }
    if (!res.ok) throw new Error(`favorite ${res.status}`);
    const data = await res.json();
    setFavoriteListingState(id, Boolean(data.favorite));
  } catch (e) {
    refreshFavoriteButtons();
  } finally {
    buttons.forEach((btn) => { btn.disabled = false; });
  }
}

window.toggleFavoriteListing = toggleFavoriteListing;
window.RadarFavorites = {
  load: loadFavoriteListings,
  refresh: refreshFavoriteButtons,
  set: setFavoriteListingState,
};

function setSavedListingsStatus(message, opts = {}) {
  const status = document.getElementById('savedListingsStatus');
  if (!status) return;
  if (!message) {
    status.hidden = true;
    status.innerHTML = '';
    return;
  }
  status.hidden = false;
  status.innerHTML = opts.html ? message : escHtml(message);
}

function updateSavedListingsEmptyState() {
  if (!window.RADAR_SAVED_PAGE) return;
  const grid = document.getElementById('savedListingsGrid');
  if (!grid) return;
  if (grid.children.length === 0) {
    setSavedListingsStatus('Bạn chưa lưu BDS nào. Quay lại Săn Deal và bấm Lưu trên các lô muốn theo dõi.');
  } else {
    setSavedListingsStatus('');
  }
}

function savedListingToSignalCard(data) {
  const images = Array.isArray(data.imgs) ? data.imgs.filter(Boolean) : [];
  const priceLabel = data.price_ty ? `${data.price_ty} tỷ` : '-';
  return {
    id: data.id,
    title: data.title || '',
    description: data.description || '',
    price_ty: data.price_ty,
    price_label: priceLabel,
    actual_ppm2: data.actual_ppm2,
    fair_ppm2: data.fair_ppm2_display || data.fair_ppm2,
    fair_ppm2_display: data.fair_ppm2_display,
    fair_ppm2_old: data.fair_ppm2_old,
    fair_ppm2_new: data.fair_ppm2_new,
    mos_pct: data.mos_pct,
    mos_pct_display: data.mos_pct_display,
    mos_pct_old: data.mos_pct_old,
    mos_pct_new: data.mos_pct_new,
    area_m2: data.area_m2,
    frontage_m: data.frontage_m,
    depth_m: data.depth_m,
    ward: data.ward,
    road_type: data.road_type,
    road_tier: data.road_tier,
    road_label: data.road_label,
    street_label: data.street_label,
    tho_cu_m2: data.tho_cu_m2,
    tho_cu_ratio: data.tho_cu_ratio,
    tho_cu_label: data.tho_cu_label,
    property_type: data.property_type,
    property_type_label: data.property_type_label,
    source: data.source,
    url: data.url || `/listing/${data.id}`,
    price_dropped: Boolean(data.price_dropped),
    drop_pct: data.drop_pct,
    price_first_ty: data.price_first_ty,
    signal_score: data.signal_score,
    trust_tier: data.trust_tier,
    trust_score: data.trust_score,
    legal_status: data.legal_status,
    legal_flags: data.legal_flags,
    days_ago: data.days_ago,
    card_date_reason: data.card_date_reason,
    primary_img: images[0] || '',
    primary_image: images[0] || '',
    imgs: images,
    images,
  };
}

async function fetchSavedListingDetail(listingId) {
  const res = await fetch(`/api/listing/${encodeURIComponent(listingId)}`, {
    credentials: 'same-origin',
    cache: 'no-store',
  });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`listing ${listingId} ${res.status}`);
  return res.json();
}

async function loadSavedListingsPage(force = false) {
  if (!window.RADAR_SAVED_PAGE) return;
  const grid = document.getElementById('savedListingsGrid');
  if (!grid) return;
  if (!window.CURRENT_USER) {
    grid.innerHTML = '';
    setSavedListingsStatus(
      'Đăng nhập để xem BDS đã lưu trong tài khoản. <button type="button" class="saved-inline-login" onclick="RadarAuth.openAuthModal()">Đăng nhập</button>',
      { html: true }
    );
    if (typeof hideLoader === 'function') hideLoader();
    return;
  }

  setSavedListingsStatus('Đang tải BDS đã lưu...');
  if (force) grid.innerHTML = '';
  try {
    favoriteListingsLoaded = false;
    await loadFavoriteListings();
    const ids = Array.from(favoriteListingIds).filter((id) => Number.isFinite(Number(id)) && Number(id) > 0);
    if (ids.length === 0) {
      grid.innerHTML = '';
      updateSavedListingsEmptyState();
      return;
    }
    const details = await Promise.all(ids.map((id) => fetchSavedListingDetail(id).catch(() => null)));
    const cards = details.filter(Boolean).map(savedListingToSignalCard);
    grid.innerHTML = cards.map((x, index) => renderSignalDealCard(x, {
      cardContext: 'saved',
      contactContext: 'card_saved',
      openHandler: 'openSignal',
      priorityImage: index === 0,
    })).join('');
    refreshFavoriteButtons();
    if (cards.length === 0) {
      setSavedListingsStatus('Các BDS đã lưu hiện không còn hiển thị.');
    } else {
      setSavedListingsStatus('');
    }
  } catch (err) {
    console.error(err);
    setSavedListingsStatus('Không tải được BDS đã lưu. Vui lòng thử lại.');
  } finally {
    if (typeof hideLoader === 'function') hideLoader();
  }
}

window.loadSavedListingsPage = loadSavedListingsPage;

function signalQuery(page) {
  const params = new URLSearchParams(currentFilters);
  params.set('sort', signalSort);
  params.set('page', String(page));
  params.set('limit', String(SIGNAL_PAGE_SIZE));
  params.set('include_total', '0');
  return window.RadarFilterRuntime.canonicalize(params);
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

function _signalQualityBadges(signal) {
  const flags = String(signal.source_quality_flags || '')
    .split(',')
    .map((x) => x.trim())
    .filter(Boolean);
  const badges = [];
  if (flags.includes('low_segment_confidence')) {
    badges.push({
      label: 'Mẫu giá mỏng',
      title: 'Dữ liệu so sánh còn ít, cần kiểm tra thêm trước khi xuống tiền.',
      icon: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4"><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"/><path d="M12 9v4"/><path d="M12 17h.01"/></svg>'
    });
  }
  return badges;
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
    <div class="scard signal-skeleton-card" aria-hidden="true">
      <div class="signal-skeleton-media skeleton-block"></div>
      <div class="sc-body">
        <span class="skeleton-line signal-skeleton-title"></span>
        <div class="signal-skeleton-summary">
          <span class="skeleton-line short"></span>
          <span class="skeleton-line"></span>
        </div>
        <div class="signal-skeleton-price">
          <span class="skeleton-line"></span>
          <span class="skeleton-line short"></span>
        </div>
        <span class="skeleton-line"></span>
        <span class="skeleton-line short"></span>
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

function setSignalLoadingUI(isLoading, message = 'Đang lọc signal...') {
  const bar = document.getElementById('signalsLoadingBar');
  const text = document.getElementById('signalsLoadingText');
  const grid = document.getElementById('signalsGrid');
  const tab = document.getElementById('tab-signals');
  if (text) text.textContent = message;
  if (bar) bar.hidden = !isLoading;
  if (grid) {
    grid.classList.toggle('is-refreshing', Boolean(isLoading && grid.children.length > 0));
    grid.setAttribute('aria-busy', isLoading ? 'true' : 'false');
  }
  if (tab) tab.setAttribute('aria-busy', isLoading ? 'true' : 'false');
}

function renderSignalCardMedia(x, imgSrc, imageCount, overlaysHtml, mediaOpts = {}) {
  const hasImage = Boolean(imgSrc);
  const mediaClass = hasImage ? 'sc-img-wrap' : 'sc-img-wrap sc-img-wrap-empty';
  const loadingAttr = mediaOpts.priorityImage ? 'eager' : 'lazy';
  const fetchPriorityAttr = mediaOpts.priorityImage ? 'high' : 'auto';
  const imageHtml = hasImage
    ? `<img class="sc-img" src="${escHtml(imgSrc)}" loading="${loadingAttr}" fetchpriority="${fetchPriorityAttr}" decoding="async" width="520" height="338" alt="Ảnh tin đăng" onerror="this.closest('.sc-img-wrap').classList.add('is-image-missing');this.remove();">`
    : '';

  return `
    <div class="${mediaClass}" data-has-image="${hasImage ? '1' : '0'}">
      ${imageHtml}
      <div class="sc-empty-media" aria-label="Tin đăng chưa có ảnh">
        <div class="sc-empty-media-map" aria-hidden="true">
          <span></span><span></span><span></span><span></span>
        </div>
        <div class="sc-empty-media-mark" aria-hidden="true">
          <svg width="38" height="38" viewBox="0 0 48 48" fill="none">
            <path d="M24 42s13-10.6 13-24a13 13 0 1 0-26 0c0 13.4 13 24 13 24Z" stroke="currentColor" stroke-width="3" stroke-linejoin="round"/>
            <path d="M18 20h12M18 25h8" stroke="currentColor" stroke-width="3" stroke-linecap="round"/>
          </svg>
        </div>
        <div class="sc-empty-media-copy">
          <strong>Chưa có ảnh</strong>
          <span>Xem giá và vị trí</span>
        </div>
      </div>
      ${overlaysHtml}
    </div>
  `;
}

function setSignalLoadMoreUI(isLoading) {
  const sentinel = document.getElementById('sig-scroll-sentinel');
  if (!sentinel) return;
  sentinel.classList.toggle('is-loading', Boolean(isLoading));
  sentinel.textContent = isLoading ? 'Đang tải thêm...' : '';
}

function ensureSignalScrollRoot(opts = {}) {
  const tab = document.getElementById('tab-signals');
  if (!tab) return;
  tab.classList.add('signals-scroll-ready');
  if (opts.refreshObserver && document.getElementById('sig-scroll-sentinel')) {
    _setupSignalScroll();
  }
}

function _daysAgoValue(v) {
  if (v === null || v === undefined || v === '') return null;
  const n = Number(v);
  return Number.isFinite(n) && n >= 0 ? n : null;
}

function _timeAgoText(v) {
  const n = _daysAgoValue(v);
  if (n === null) return 'Chưa rõ ngày';
  return n === 0 ? 'hôm nay' : `${n} ngày trước`;
}

function _cardDateText(item) {
  const relative = _timeAgoText(item && item.days_ago);
  const reason = String((item && item.card_date_reason) || 'posted');
  if (reason === 'price_updated') return `Cập nhật giá ${relative}`;
  if (reason === 'first_seen') return `Theo dõi từ ${relative}`;
  return relative;
}

function _isNewWithin(v, maxDays = 4) {
  const n = _daysAgoValue(v);
  return n !== null && n <= maxDays;
}

function _signalNumber(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : NaN;
}

function _formatSignalNumber(value) {
  const n = _signalNumber(value);
  if (!Number.isFinite(n) || n <= 0) return '';
  return n.toLocaleString('vi-VN', { maximumFractionDigits: 1 }).replace(',', '.');
}

function _signalAreaLabel(signal) {
  const area = _formatSignalNumber(signal && signal.area_m2);
  const frontage = _formatSignalNumber(signal && signal.frontage_m);
  const depth = _formatSignalNumber(signal && signal.depth_m);
  if (frontage && depth && area) return `${frontage}x${depth} (${area}m²)`;
  if (area) return `${area}m²`;
  return '-';
}

function _signalThoCuLabel(signal) {
  if (!signal) return '';
  if (signal.tho_cu_label) return signal.tho_cu_label;
  const value = _formatSignalNumber(signal.tho_cu_m2);
  return value ? `TC ${value}m²` : '';
}

function _signalPropertyTypeLabel(signal) {
  if (!signal) return '';
  return signal.prop_type_label || PROPERTY_TYPE_LABELS[signal.prop_type] || signal.prop_type || '';
}

function renderSignalMetaChip(iconSvg, label, extraClass = '') {
  const text = String(label || '').trim();
  if (!text || text === '-' || text === 'N/A') return '';
  return `
    <span class="meta-chip ${extraClass}">
      ${iconSvg}
      <span class="meta-chip-label">${escHtml(text)}</span>
    </span>
  `;
}

function renderSignalMetaChips(signal, areaLabel, roadLabel) {
  const pinIcon = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/></svg>';
  const areaIcon = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/></svg>';
  const roadIcon = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"/><line x1="4" y1="22" x2="4" y2="15"/></svg>';
  const propertyIcon = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 7h18"/><path d="M7 3v18"/><path d="M17 3v18"/><path d="M3 17h18"/></svg>';
  const landIcon = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 18h16"/><path d="M7 18 12 4l5 14"/><path d="M9 13h6"/></svg>';
  const streetIcon = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 3v18"/><path d="M18 3v18"/><path d="M6 8h18"/><path d="M0 16h18"/></svg>';

  return [
    renderSignalMetaChip(pinIcon, signal.ward || 'Chưa rõ', 'meta-chip-ward'),
    renderSignalMetaChip(areaIcon, areaLabel, 'meta-chip-area'),
    renderSignalMetaChip(roadIcon, roadLabel, 'meta-chip-road'),
    renderSignalMetaChip(streetIcon, signal.street_label, 'meta-chip-street'),
    renderSignalMetaChip(propertyIcon, _signalPropertyTypeLabel(signal), 'meta-chip-property'),
    renderSignalMetaChip(landIcon, _signalThoCuLabel(signal), 'meta-chip-land'),
  ].join('');
}

function signalDealImageSrc(x) {
  if (x && x.primary_img) return x.primary_img;
  if (x && x.primary) return x.primary;
  if (x && Array.isArray(x.imgs) && x.imgs.length) return x.imgs[0];
  return '';
}

function signalDealFairPrice(x) {
  if (!x) return '-';
  const valuationItems = signalValuationItems(x);
  if (valuationItems.length) return valuationItems[0].totalLabel;
  if (x.fair_total_ty) return Number(x.fair_total_ty).toFixed(2).replace(/\.?0+$/, '');
  if (x.fair) return String(x.fair);
  const fairPpm2 = Number(x.fair_ppm2);
  const area = Number(x.area_m2 || x.area);
  if (!Number.isFinite(fairPpm2) || !Number.isFinite(area) || area <= 0) return '-';
  return (fairPpm2 * area / 1000).toFixed(2);
}

function _signalFormatTy(value) {
  const n = Number(value);
  if (!Number.isFinite(n) || n <= 0) return '-';
  return n.toFixed(2).replace(/\.?0+$/, '');
}

function signalValuationItems(x) {
  if (!x) return [];
  const area = Number(x.area_m2 || x.area);
  if (!Number.isFinite(area) || area <= 0) return [];
  const items = [];
  const oldPpm2 = Number(x.fair_ppm2_old);
  const newPpm2 = Number(x.fair_ppm2_new);
  if (Number.isFinite(oldPpm2) && oldPpm2 > 0) {
    const total = oldPpm2 * area / 1000;
    items.push({ key: 'old', ppm2: oldPpm2, total, totalLabel: _signalFormatTy(total) });
  }
  if (Number.isFinite(newPpm2) && newPpm2 > 0) {
    const total = newPpm2 * area / 1000;
    items.push({ key: 'new', ppm2: newPpm2, total, totalLabel: _signalFormatTy(total) });
  }
  if (!items.length) {
    const fairPpm2 = Number(x.fair_ppm2 || x.fppm2);
    if (Number.isFinite(fairPpm2) && fairPpm2 > 0) {
      const total = fairPpm2 * area / 1000;
      items.push({ key: 'legacy', ppm2: fairPpm2, total, totalLabel: _signalFormatTy(total) });
    }
  }
  return items.sort((a, b) => a.total - b.total);
}

function signalActualPriceClass(x) {
  const actualPpm2 = _signalNumber(x && (x.actual_ppm2 || x.price_per_m2 || x.ppm2));
  const valuationItems = signalValuationItems(x);
  const fairPpm2Values = valuationItems
    .map((item) => _signalNumber(item.ppm2))
    .filter((value) => Number.isFinite(value) && value > 0);
  if (!Number.isFinite(actualPpm2) || actualPpm2 <= 0 || !fairPpm2Values.length) return 'price-deal';

  const lowFairPpm2 = Math.min(...fairPpm2Values);
  const highFairPpm2 = Math.max(...fairPpm2Values);
  if (actualPpm2 < lowFairPpm2) return 'price-deal';
  if (actualPpm2 > highFairPpm2) return 'price-over';
  return 'price-neutral';
}

function signalValuationHtml(x) {
  const items = signalValuationItems(x);
  if (!items.length) return '<div class="price-val price-val-fair">-</div><div class="price-m2">-</div>';
  const totals = items.map((item) => (
    `<span class="valuation-value">${escHtml(item.totalLabel)} tỷ</span>`
  )).join('<span class="valuation-sep">~</span>');
  const ppm2Values = items.map((item) => (
    `<span class="valuation-ppm2">${escHtml(item.ppm2.toFixed(1).replace(/\.0$/, ''))} tr/m²</span>`
  )).join('<span class="valuation-ppm2-gap"></span>');
  return `
    <div class="price-val price-val-fair valuation-total-row">${totals}</div>
    <div class="price-m2 valuation-ppm2-row">${ppm2Values}</div>
  `;
}

function signalDealDataAttrs(x, fairPrice, imgSrc, timeStr, roadStr, profit) {
  const attrs = [
    ['id', x.id],
    ['title', x.title || ''],
    ['primary', imgSrc || ''],
    ['price', x.price_ty || x.price || ''],
    ['ppm2', x.actual_ppm2 || x.price_per_m2 || x.ppm2 || ''],
    ['fair', fairPrice !== '-' ? fairPrice : ''],
    ['fppm2', x.fair_ppm2 || x.fppm2 || ''],
    ['fair-ppm2-old', x.fair_ppm2_old || ''],
    ['fair-ppm2-new', x.fair_ppm2_new || ''],
    ['mos-pct-old', x.mos_pct_old || ''],
    ['mos-pct-new', x.mos_pct_new || ''],
    ['mos-pct-display', x.mos_pct_display || ''],
    ['area', x.area_m2 || x.area || ''],
    ['frontage', x.frontage_m || x.frontage || ''],
    ['depth', x.depth_m || x.depth || ''],
    ['ward', x.ward || ''],
    ['road', roadStr || x.road_type || x.road_tier || x.road || ''],
    ['road-label', x.road_label || x.roadLabel || ''],
    ['street-label', x.street_label || x.streetLabel || ''],
    ['tho-cu', x.tho_cu_m2 || x.thoCuM2 || x.thoCu || ''],
    ['tho-cu-label', x.tho_cu_label || x.thoCuLabel || _signalThoCuLabel(x)],
    ['prop-label', _signalPropertyTypeLabel(x)],
    ['time', timeStr || ''],
    ['profit', profit || ''],
    ['mos', x.mos_pct_display || x.mos_pct || x.mos || ''],
    ['source', sourceNames[x.source] || x.source || ''],
    ['drop', x.drop_pct || x.drop || ''],
    ['score', x.signal_score || x.score || '-'],
    ['url', x.url || ''],
    ['ptype', x.prop_type || x.ptype || ''],
  ];
  return attrs.map(([key, value]) => `data-${key}="${escHtml(value)}"`).join(' ');
}

function renderSignalDealCard(x, opts = {}) {
  if (window.RadarSignalCard && typeof window.RadarSignalCard.render === 'function') {
    return window.RadarSignalCard.render(x, {
      context: opts.cardContext || 'signal',
      openMode: 'modal',
      openHandler: opts.openHandler || ((opts.cardContext || 'signal') === 'all' ? 'openListingModal' : 'openSignal'),
      showFavorite: true,
      showContact: true,
      priorityImage: Boolean(opts.priorityImage)
    });
  }
  const cardContext = opts.cardContext || 'signal';
  const contactContext = opts.contactContext || (cardContext === 'all' ? 'card_all' : 'card_signal');
  const openHandler = opts.openHandler || (cardContext === 'all' ? 'openListingModal' : 'openSignal');
  const fairPrice = signalDealFairPrice(x);
  const fairNum = fairPrice !== '-' ? parseFloat(fairPrice) : NaN;
  const priceNum = parseFloat(x.price_ty || x.price);
  const priceLabel = x.price_label || (x.price_ty ? `${x.price_ty} tỷ` : (x.price ? `${x.price} tỷ` : '-'));
  const profit = fairPrice !== '-' && Number.isFinite(priceNum) ? (fairNum - priceNum).toFixed(2) : '-';
  const actualClass = signalActualPriceClass(x);
  const fairHtml = signalValuationHtml(x);
  const mosNum = _signalNumber(x.mos_pct_display || x.mos_pct || x.mos);
  const mosRounded = Math.round(mosNum || 0);
  const areaLabel = _signalAreaLabel(x);
  const qualityBadgeHtml = _signalQualityBadges(x).map((badge) => (
    `<span class="sc-quality-tag" title="${escHtml(badge.title)}">${badge.icon || ''}${escHtml(badge.label)}</span>`
  )).join('');

  const daysAgo = _daysAgoValue(x.days_ago);
  const timeStr = _cardDateText(x);
  const roadTiers = {
    1: 'Mặt tiền',
    2: 'Đường nhựa',
    3: 'Hẻm xe hơi',
    4: 'Hẻm xe máy',
    5: 'Hẻm xe máy'
  };
  const roadStr = x.road_label || x.roadLabel || roadTiers[x.road_tier] || x.road_type || x.road || 'Chưa rõ';
  const metaChipsHtml = renderSignalMetaChips(x, areaLabel, roadStr);
  const safeTitle = escHtml(x.title || '');
  const imgSrc = signalDealImageSrc(x);
  const dataAttr = signalDealDataAttrs(x, fairPrice, imgSrc, timeStr, roadStr, profit);
  const isPriceUpdated = x.card_date_reason === 'price_updated';
  const isNew = !isPriceUpdated && _isNewWithin(x.days_ago, 7);
  const newCardClass = isNew ? 'is-new-signal' : '';
  const newBadgeHtml = isPriceUpdated
    ? '<div class="new-badge price-update-badge">CẬP NHẬT GIÁ</div>'
    : (isNew ? `<div class="new-badge"><svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/></svg> MỚI</div>` : '');
  const srcName = sourceNames[x.source] || x.source;
  const sourceTagHtml = window.USER_TIER === 'admin' && srcName
    ? `<span class="sc-source-tag">${escHtml(srcName)}</span>`
    : '';
  const dropBadge = x.price_dropped ? `<span class="sc-drop-tag"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="12 4 12 20"/><polyline points="6 14 12 20 18 14"/></svg> Chủ hạ: ${x.drop_pct ? `${escHtml(x.drop_pct)}%` : 'N/A'}</span>` : '';
  const mosBadge = Number.isFinite(mosNum) && mosNum > 0
    ? `<div class="mos-badge"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4"><rect x="4" y="9" width="16" height="10" rx="4"/><circle cx="9" cy="14" r="1"/><circle cx="15" cy="14" r="1"/><path d="M12 9V5"/><circle cx="12" cy="4" r="1"/></svg> Rẻ hơn ${mosRounded}%</div>`
    : '';
  const actualPpm2 = x.actual_ppm2 || x.price_per_m2 || x.ppm2 || '-';
  const fairPpm2 = x.fair_ppm2 || x.fppm2 || '-';
  const ctaLabel = (window.USER_TIER === 'vip' || window.USER_TIER === 'admin') ? '⚡ Ráp mối VIP' : '💬 Ráp mối';
  const mediaHtml = renderSignalCardMedia(x, imgSrc, 0, `
      ${mosBadge}
      ${newBadgeHtml}
      <div class="sc-img-tags">
        ${sourceTagHtml}
        <span class="sc-time-tag"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg> ${escHtml(timeStr)}</span>
        ${dropBadge}
        ${qualityBadgeHtml}
      </div>
  `, { priorityImage: Boolean(opts.priorityImage) });
  const cardLabel = `Mở chi tiết ${safeTitle || 'tin đăng'}`;

  return `
  <div class="scard ${newCardClass} ${cardContext === 'all' ? 'listing-grid-card' : ''}" role="button" tabindex="0"
    aria-label="${escHtml(cardLabel)}" onclick="${openHandler}(this)"
    onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();${openHandler}(this);}" ${dataAttr}>
    ${mediaHtml}
    <div class="sc-body">
      <div class="sc-title" title="${safeTitle}">${safeTitle || '-'}</div>

      <div class="price-container">
        <div class="price-actual">
          <span class="price-label price-label-actual ${actualClass}">THỰC TẾ</span>
          <div class="price-val ${actualClass}">${escHtml(priceLabel)}</div>
          <div class="price-m2">${escHtml(actualPpm2)}${actualPpm2 !== '-' ? ' tr/m²' : ''}</div>
        </div>
        <div class="price-fair">
          <span class="price-label price-label-fair">ĐỊNH GIÁ</span>
          ${fairHtml}
        </div>
      </div>

      <div class="sc-meta-chips">
        ${metaChipsHtml}
      </div>

      <div class="sc-actions" onclick="event.stopPropagation()">
        ${favoriteButtonHtml(x.id)}
        <a href="#" onclick="event.preventDefault();const c=this.closest('.scard').dataset;tierCTA(c.id,c.url,'${contactContext}');" class="btn-zalo"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg> ${ctaLabel}</a>
      </div>
    </div>
  </div>
`;
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
    setSignalLoadMoreUI(false);
    signalRenderSeq++;
    signalPageNo = 1;
    signalHasMore = false;
    renderedSignalIds = new Set();
    if (!firstSignalsLoaded) {
      renderSignalSkeleton();
    } else {
      setSignalLoadingUI(true, 'Đang lọc signal...');
    }
  } else {
    setSignalLoadMoreUI(true);
  }
  try {
    const data = await fetchJSONCached('signals', `/api/signals?${queryKey}`, false);
    if (runId !== signalRunSeq) return;
    const bSig = document.getElementById('badgeSignals');
    if (bSig && Number.isFinite(Number(data.total))) {
      bSig.innerText = data.total;
      if (typeof syncMobileBadges === 'function') syncMobileBadges();
    }
    if (reset) document.getElementById('signalsGrid').innerHTML = '';
    renderSignals(data.signals || [], { append: !reset, priorityFirstImage: reset && !firstSignalsLoaded });
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
      if (reset) setSignalLoadingUI(false);
      setSignalLoadMoreUI(false);
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

  _renderSignalCards(freshSignals, { priorityFirstImage: Boolean(options.priorityFirstImage) });
  _setupSignalScroll();
}

function _renderSignalCards(signals, options = {}) {
  const grid = document.getElementById('signalsGrid');
  if (!signals || signals.length === 0) return;
  const renderSeq = signalRenderSeq;

  const renderChunk = (start) => {
    if (renderSeq !== signalRenderSeq) return;
    const chunk = signals.slice(start, start + SIGNAL_RENDER_CHUNK_SIZE);
    if (chunk.length === 0) return;
    grid.insertAdjacentHTML('beforeend', chunk.map((x, i) => {
      const index = start + i;
      return renderSignalDealCard(x, {
        cardContext: 'signal',
        contactContext: 'card_signal',
        openHandler: 'openSignal',
        priorityImage: Boolean(options.priorityFirstImage && index === 0)
      });
    }).join(''));
    loadFavoriteListings();
    if (options.priorityFirstImage && !firstSignalRenderEventSent) {
      firstSignalRenderEventSent = true;
      window.dispatchEvent(new CustomEvent('radar:first-signals-rendered'));
    }
    if (start + SIGNAL_RENDER_CHUNK_SIZE < signals.length) {
      requestAnimationFrame(() => renderChunk(start + SIGNAL_RENDER_CHUNK_SIZE));
    }
  };

  requestAnimationFrame(() => renderChunk(0));
}

function _setupSignalScroll() {
  ensureSignalScrollRoot();
  if (_sigObserver) _sigObserver.disconnect();
  const grid = document.getElementById('signalsGrid');
  const root = grid.closest('.tab-content');
  const sentinel = document.getElementById('sig-scroll-sentinel');
  if (!sentinel) {
    const s = document.createElement('div');
    s.id = 'sig-scroll-sentinel';
    s.className = 'signal-load-more';
    grid.parentElement.appendChild(s);
  }
  const el = document.getElementById('sig-scroll-sentinel');
  el.classList.add('signal-load-more');
  _sigObserver = new IntersectionObserver(entries => {
    if (entries[0].isIntersecting && signalHasMore && !signalLoading) {
      loadSignals(signalPageNo + 1, { reset: false });
    }
  }, { root, rootMargin: '400px' });
  _sigObserver.observe(el);
}
