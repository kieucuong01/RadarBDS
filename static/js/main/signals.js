// Signal feed, insights panels, and infinite-scroll card rendering.
let _sigObserver = null;

function signalQuery(page) {
  const params = new URLSearchParams(currentFilters);
  params.set('sort', signalSort);
  params.set('page', String(page));
  params.set('limit', String(SIGNAL_PAGE_SIZE));
  params.set('include_total', '0');
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

function renderSignalCardMedia(x, imgSrc, imageCount, overlaysHtml) {
  const hasImage = Boolean(imgSrc);
  const mediaClass = hasImage ? 'sc-img-wrap' : 'sc-img-wrap sc-img-wrap-empty';
  const imageHtml = hasImage
    ? `<img class="sc-img" src="${escHtml(imgSrc)}" loading="lazy" decoding="async" width="640" height="416" alt="Ảnh tin đăng" onerror="this.closest('.sc-img-wrap').classList.add('is-image-missing');this.remove();">`
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
    renderSignalMetaChip(pinIcon, signal.ward || 'Chưa rõ'),
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
  if (x.fair_total_ty) return Number(x.fair_total_ty).toFixed(2).replace(/\.?0+$/, '');
  if (x.fair) return String(x.fair);
  const fairPpm2 = Number(x.fair_ppm2);
  const area = Number(x.area_m2 || x.area);
  if (!Number.isFinite(fairPpm2) || !Number.isFinite(area) || area <= 0) return '-';
  return (fairPpm2 * area / 1000).toFixed(2);
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
    ['mos', x.mos_pct || x.mos || ''],
    ['source', sourceNames[x.source] || x.source || ''],
    ['drop', x.drop_pct || x.drop || ''],
    ['score', x.signal_score || x.score || '-'],
    ['url', x.url || ''],
    ['ptype', x.prop_type || x.ptype || ''],
  ];
  return attrs.map(([key, value]) => `data-${key}="${escHtml(value)}"`).join(' ');
}

function renderSignalDealCard(x, opts = {}) {
  const cardContext = opts.cardContext || 'signal';
  const contactContext = opts.contactContext || (cardContext === 'all' ? 'card_all' : 'card_signal');
  const openHandler = opts.openHandler || (cardContext === 'all' ? 'openListingModal' : 'openSignal');
  const fairPrice = signalDealFairPrice(x);
  const fairNum = fairPrice !== '-' ? parseFloat(fairPrice) : NaN;
  const priceNum = parseFloat(x.price_ty || x.price);
  const priceLabel = x.price_label || (x.price_ty ? `${x.price_ty} tỷ` : (x.price ? `${x.price} tỷ` : '-'));
  const profit = fairPrice !== '-' && Number.isFinite(priceNum) ? (fairNum - priceNum).toFixed(2) : '-';
  const isOverpriced = Number.isFinite(priceNum) && Number.isFinite(fairNum) && priceNum > fairNum;
  const actualClass = isOverpriced ? 'price-over' : 'price-deal';
  const mosNum = _signalNumber(x.mos_pct || x.mos);
  const mosRounded = Math.round(mosNum || 0);
  const areaLabel = _signalAreaLabel(x);
  const qualityBadgeHtml = _signalQualityBadges(x).map((badge) => (
    `<span class="sc-quality-tag" title="${escHtml(badge.title)}">${badge.icon || ''}${escHtml(badge.label)}</span>`
  )).join('');

  const daysAgo = _daysAgoValue(x.days_ago);
  const timeStr = _timeAgoText(daysAgo);
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
  const isNew = _isNewWithin(x.days_ago, 7);
  const newCardClass = isNew ? 'is-new-signal' : '';
  const newBadgeHtml = isNew ? `<div class="new-badge"><svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/></svg> MỚI</div>` : '';
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
  `);

  return `
  <div class="scard ${newCardClass} ${cardContext === 'all' ? 'listing-grid-card' : ''}" onclick="${openHandler}(this)" ${dataAttr}>
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
          <div class="price-val-fair">${fairPrice !== '-' ? `${escHtml(fairPrice)} tỷ` : '-'}</div>
          <div class="price-m2">${escHtml(fairPpm2)}${fairPpm2 !== '-' ? ' tr/m²' : ''}</div>
        </div>
      </div>

      <div class="sc-meta-chips">
        ${metaChipsHtml}
      </div>

      <div class="sc-actions" onclick="event.stopPropagation()">
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
    grid.insertAdjacentHTML('beforeend', chunk.map((x) => renderSignalDealCard(x, {
      cardContext: 'signal',
      contactContext: 'card_signal',
      openHandler: 'openSignal'
    })).join(''));
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
