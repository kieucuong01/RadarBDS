// Signal detail modal, gallery, memo, price history, and generic modal helpers.
const INVESTMENT_MEMO_ENABLED = true;
// Slider state
let _smSlideIdx = 0;
let _smSlideImgs = [];
let _smSlideLocked = false;
let _smSlideLockTimer = null;

function updateSignalSlideUi() {
  const counter = document.getElementById('sm-img-count');
  if (counter) counter.innerText = _smSlideImgs.length > 1 ? `${_smSlideIdx + 1} / ${_smSlideImgs.length}` : '';
  document.querySelectorAll('#sm-dots .sm-dot').forEach((d, i) => {
    d.classList.toggle('active', i === _smSlideIdx);
  });
  document.querySelectorAll('#sm-thumbs .sm-thumb').forEach((thumb, i) => {
    thumb.classList.toggle('active', i === _smSlideIdx);
  });
}

function setSignalSlide(index, opts = {}) {
  if (!_smSlideImgs.length) return;
  const slides = document.getElementById('sm-slides');
  if (!slides) return;
  const count = _smSlideImgs.length;
  const previous = _smSlideIdx;
  const next = ((index % count) + count) % count;
  const rawDistance = Math.abs(index - previous);
  const normalizedDistance = Math.abs(next - previous);
  const isWrap = index < 0 || index >= count || normalizedDistance > 1 || rawDistance > 1;
  const instant = Boolean(opts.instant || isWrap);

  _smSlideIdx = next;
  if (_smSlideLockTimer) {
    clearTimeout(_smSlideLockTimer);
    _smSlideLockTimer = null;
  }
  if (instant) {
    _smSlideLocked = false;
    slides.style.transition = 'none';
  } else {
    _smSlideLocked = true;
    slides.style.transition = '';
    _smSlideLockTimer = setTimeout(() => {
      _smSlideLocked = false;
      _smSlideLockTimer = null;
    }, 430);
  }
  slides.style.transform = `translate3d(-${_smSlideIdx * 100}%, 0, 0)`;
  if (instant) {
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        slides.style.transition = '';
      });
    });
  }
  updateSignalSlideUi();
}

function slideSignal(dir) {
  if (_smSlideImgs.length <= 1 || _smSlideLocked) return;
  setSignalSlide(_smSlideIdx + dir);
}

function renderSignalThumbs() {
  const thumbsEl = document.getElementById('sm-thumbs');
  if (!thumbsEl) return;
  thumbsEl.innerHTML = _smSlideImgs.length > 1
    ? _smSlideImgs.map((src, i) => `<img class="sm-thumb ${i === _smSlideIdx ? 'active' : ''}" src="${escHtml(src)}" alt="Ảnh tin đăng ${i + 1}" role="button" tabindex="0" onclick="setSignalSlide(${i})" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();setSignalSlide(${i});}" ondblclick="openGallery(${i})" onerror="this.style.display='none'">`).join('')
    : '';
}

function buildSlider(imgs) {
  _smSlideIdx = 0;
  _smSlideLocked = false;
  if (_smSlideLockTimer) {
    clearTimeout(_smSlideLockTimer);
    _smSlideLockTimer = null;
  }
  _smSlideImgs = imgs.length ? imgs : [PLACEHOLDER_IMG];
  const slides = document.getElementById('sm-slides');
  const dots = document.getElementById('sm-dots');
  const counter = document.getElementById('sm-img-count');
  const prevBtn = document.getElementById('sm-prev');
  const nextBtn = document.getElementById('sm-next');

  // Build slides
  slides.classList.add('sm-slides-track');
  slides.style.transition = '';
  slides.style.transform = 'translate3d(0, 0, 0)';
  slides.innerHTML = _smSlideImgs.map((src, i) => `
    <div class="sm-slide">
      <img class="sm-slide-img" src="${escHtml(src)}"
        alt="Ảnh tin đăng ${i + 1}"
        role="button"
        tabindex="0"
        onclick="openGallery(${i})"
        onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();openGallery(${i});}"
        onerror="this.onerror=null;this.src=PLACEHOLDER_IMG;">
    </div>`
  ).join('');

  // Dots
  dots.innerHTML = _smSlideImgs.length > 1
    ? _smSlideImgs.map((_, i) => `<button type="button" class="sm-dot ${i === 0 ? 'active' : ''}" onclick="setSignalSlide(${i})" aria-label="Ảnh ${i + 1}"></button>`).join('')
    : '';

  // Arrows + counter
  const multi = _smSlideImgs.length > 1;
  prevBtn.style.display = multi ? 'flex' : 'none';
  nextBtn.style.display = multi ? 'flex' : 'none';
  updateSignalSlideUi();
}

let smHistoryChart = null;
let smHistoryChartTimeline = [];
let galleryImages = [];
let galleryIndex = 0;
let signalModalHistoryManaged = false;
let signalModalClosingFromHistory = false;

function _signalModalIsOpen() {
  const modal = document.getElementById('signalModal');
  return Boolean(modal && modal.style.display === 'flex');
}

function _signalModalUrl(listingId) {
  const url = new URL(window.location.href);
  url.searchParams.set('signal', String(listingId));
  return `${url.pathname}${url.search}${url.hash}`;
}

function _pushSignalModalHistory(listingId) {
  if (!listingId || !window.history || typeof window.history.pushState !== 'function') return;
  const currentSignal = new URLSearchParams(window.location.search).get('signal');
  if (history.state && history.state.signalModal && currentSignal === String(listingId)) {
    signalModalHistoryManaged = true;
    return;
  }
  history.pushState(
    { signalModal: true, signalId: String(listingId) },
    '',
    _signalModalUrl(listingId)
  );
  signalModalHistoryManaged = true;
}

function _closeSignalModalDirect() {
  const modal = document.getElementById('signalModal');
  if (!modal) return;
  modal.style.display = 'none';
  setSignalModalOpen(false);
  signalModalHistoryManaged = false;
  signalModalClosingFromHistory = false;
}

function _closeSignalModalViaHistory() {
  const modal = document.getElementById('signalModal');
  if (!modal || !signalModalHistoryManaged || signalModalClosingFromHistory) return false;
  signalModalClosingFromHistory = true;
  const closingId = modal.dataset.listingId;
  history.back();
  window.setTimeout(() => {
    if (signalModalClosingFromHistory && _signalModalIsOpen() && modal.dataset.listingId === closingId) {
      _closeSignalModalDirect();
    }
  }, 650);
  return true;
}

function propertyTypeLabel(v) {
  return PROPERTY_TYPE_LABELS[v] || v || 'N/A';
}

function _signalTagText(value) {
  const text = String(value || '').trim();
  if (!text || text === '-' || text === 'N/A') return '';
  return text;
}

function _signalTagArea(data) {
  const n = Number(String((data && data.area) || '').replace(',', '.'));
  if (!Number.isFinite(n) || n <= 0) return '';
  const area = n.toLocaleString('vi-VN', { maximumFractionDigits: 1 }).replace(',', '.');
  const frontage = Number(String((data && data.frontage) || '').replace(',', '.'));
  const depth = Number(String((data && data.depth) || '').replace(',', '.'));
  if (Number.isFinite(frontage) && frontage > 0 && Number.isFinite(depth) && depth > 0) {
    const frontageText = frontage.toLocaleString('vi-VN', { maximumFractionDigits: 1 }).replace(',', '.');
    const depthText = depth.toLocaleString('vi-VN', { maximumFractionDigits: 1 }).replace(',', '.');
    return `${frontageText}x${depthText} (${area}m²)`;
  }
  return `${area}m²`;
}

function _signalTagThoCu(data) {
  if (data.thoCuLabel) return _signalTagText(data.thoCuLabel);
  const n = Number(String(data.thoCuM2 || '').replace(',', '.'));
  if (!Number.isFinite(n) || n <= 0) return '';
  return `TC ${n.toLocaleString('vi-VN', { maximumFractionDigits: 1 }).replace(',', '.')} m²`;
}

function renderSignalTags(data) {
  const tags = [
    { icon: '📍', label: _signalTagText(data.ward) },
    { icon: '📐', label: _signalTagArea(data) },
    { icon: '🛣️', label: _signalTagText(data.roadLabel || data.road) },
    { icon: '↱', label: _signalTagText(data.streetLabel) },
    { icon: '🏷️', label: _signalTagText(data.propertyTypeLabel || propertyTypeLabel(data.propertyType)) },
    { icon: '▣', label: _signalTagThoCu(data) },
  ].filter((t) => t.label);
  document.getElementById('sm-tags').innerHTML = tags
    .map((t) => `
      <span class="sm-tag-chip">
        <span class="sm-tag-icon">${escHtml(t.icon)}</span>
        <span class="sm-tag-text">${escHtml(t.label)}</span>
      </span>
    `)
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

function renderModalMetaLine(data = {}) {
  const el = document.getElementById('sm-meta-line');
  if (!el) return;
  const timeText = _signalTagText(data.time || data.daysAgo || '');
  el.innerHTML = timeText
    ? `<span>Đăng ${timeText}</span>`
    : '<span>Đăng gần đây</span>';
}

function syncModalFavoriteButton(listingId) {
  const btn = document.getElementById('sm-favorite');
  if (!btn) return;
  btn.dataset.listingId = String(listingId || '');
  if (window.RadarFavorites) {
    window.RadarFavorites.load();
    window.RadarFavorites.refresh();
  }
}

function _modalNumber(value) {
  if (value === null || value === undefined || value === '' || value === '-') return NaN;
  const n = Number(String(value).replace(',', '.'));
  return Number.isFinite(n) ? n : NaN;
}

function _modalFormatTy(value) {
  const n = _modalNumber(value);
  if (!Number.isFinite(n) || n <= 0) return '-';
  return `${n.toFixed(2).replace(/\.?0+$/, '')} tỷ`;
}

function _modalFormatPpm2(value) {
  const n = _modalNumber(value);
  if (!Number.isFinite(n) || n <= 0) return '-';
  return `${n.toFixed(1).replace(/\.?0+$/, '')} tr/m²`;
}

function _modalSetText(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value;
}

function _modalValuationItems(data = {}) {
  const area = _modalNumber(data.area_m2 ?? data.area);
  if (!Number.isFinite(area) || area <= 0) return [];
  const items = [];
  const oldPpm2 = _modalNumber(data.fair_ppm2_old ?? data.fairPpm2Old);
  const newPpm2 = _modalNumber(data.fair_ppm2_new ?? data.fairPpm2New);
  if (Number.isFinite(oldPpm2) && oldPpm2 > 0) {
    items.push({ key: 'old', ppm2: oldPpm2, total: oldPpm2 * area / 1000 });
  }
  if (Number.isFinite(newPpm2) && newPpm2 > 0) {
    items.push({ key: 'new', ppm2: newPpm2, total: newPpm2 * area / 1000 });
  }
  if (!items.length) {
    const fairPpm2 = _modalNumber(data.fair_ppm2_display ?? data.fairPpm2Display ?? data.fair_ppm2 ?? data.fppm2);
    if (Number.isFinite(fairPpm2) && fairPpm2 > 0) {
      items.push({ key: 'legacy', ppm2: fairPpm2, total: fairPpm2 * area / 1000 });
    }
  }
  return items.sort((a, b) => a.total - b.total);
}

function _modalActualPriceState(actualPpm2, valuationItems = []) {
  const fairPpm2Values = valuationItems
    .map((item) => _modalNumber(item.ppm2))
    .filter((value) => Number.isFinite(value) && value > 0);
  if (!Number.isFinite(actualPpm2) || actualPpm2 <= 0 || !fairPpm2Values.length) return '';

  const lowFairPpm2 = Math.min(...fairPpm2Values);
  const highFairPpm2 = Math.max(...fairPpm2Values);
  if (actualPpm2 < lowFairPpm2) return 'is-actual-below';
  if (actualPpm2 > highFairPpm2) return 'is-actual-above';
  return 'is-actual-within';
}

function updateSignalSummary(data = {}) {
  const price = _modalNumber(data.price_ty ?? data.price);
  const area = _modalNumber(data.area_m2 ?? data.area);
  const actualPpm2 = _modalNumber(data.actual_ppm2 ?? data.actualPpm2 ?? data.price_per_m2 ?? data.pricePerM2 ?? data.ppm2);
  const fairPpm2 = _modalNumber(data.fair_ppm2_display ?? data.fairPpm2Display ?? data.fair_ppm2 ?? data.fppm2);
  let fairTotal = _modalNumber(data.fair_total_ty ?? data.fair);
  if ((!Number.isFinite(fairTotal) || fairTotal <= 0) && Number.isFinite(fairPpm2) && Number.isFinite(area) && area > 0) {
    fairTotal = fairPpm2 * area / 1000;
  }
  const computedActualPpm2 = Number.isFinite(actualPpm2)
    ? actualPpm2
    : (Number.isFinite(price) && Number.isFinite(area) && area > 0 ? price * 1000 / area : NaN);
  const valuationItems = _modalValuationItems(data);
  const mos = _modalNumber(data.mos_pct_display ?? data.mosPctDisplay ?? data.mos_pct ?? data.mos);
  const score = _modalNumber(data.signal_score ?? data.score);

  _modalSetText('sm-sum-price', _modalFormatTy(price));
  _modalSetText('sm-sum-price-m2', _modalFormatPpm2(computedActualPpm2));
  if (valuationItems.length) {
    _modalSetText('sm-sum-fair', valuationItems.map((item) => _modalFormatTy(item.total)).join(' ~ '));
    _modalSetText('sm-sum-fair-m2', valuationItems.map((item) => _modalFormatPpm2(item.ppm2)).join(' ~ '));
  } else {
    _modalSetText('sm-sum-fair', _modalFormatTy(fairTotal));
    _modalSetText('sm-sum-fair-m2', _modalFormatPpm2(fairPpm2));
  }
  const priceCard = document.querySelector('.sm-summary-price');
  if (priceCard) {
    priceCard.classList.remove('is-actual-below', 'is-actual-above', 'is-actual-within');
    const priceState = _modalActualPriceState(computedActualPpm2, valuationItems);
    if (priceState) priceCard.classList.add(priceState);
  }
  _modalSetText('sm-sum-mos', Number.isFinite(mos) ? `${mos.toFixed(1).replace(/\.0$/, '')}%` : '-');
  _modalSetText('sm-sum-score', Number.isFinite(score) ? `Score ${Math.round(score)}` : 'Score -');
}

function switchSignalPanel(panel = 'desc', btn = null) {
  const modal = document.getElementById('signalModal');
  if (!modal) return;
  modal.dataset.activePanel = panel;
  modal.querySelectorAll('.sm-tab').forEach((tab) => {
    const isActive = tab === btn || (!btn && tab.dataset.smTab === panel);
    tab.classList.toggle('active', isActive);
    tab.setAttribute('aria-selected', isActive ? 'true' : 'false');
  });
  modal.querySelectorAll('.sm-panel[data-sm-panel]').forEach((section) => {
    const isActive = section.dataset.smPanel === panel;
    section.classList.toggle('active', isActive);
    section.setAttribute('aria-hidden', isActive ? 'false' : 'true');
  });
  if (panel === 'history' && smHistoryChart) {
    setTimeout(() => smHistoryChart.resize(), 0);
  }
}

function setSignalModalOpen(open) {
  document.body.classList.toggle('signal-modal-open', Boolean(open));
  document.body.style.overflow = open ? 'hidden' : '';
}

function toggleModalComps(btn) {
  const list = btn.closest('.sm-comps-list');
  if (!list) return;
  const expanded = list.classList.toggle('is-expanded');
  const count = btn.dataset.count || '0';
  btn.textContent = expanded ? 'Thu gọn' : `Xem thêm ${count} lô`;
}

function renderSignalDetailLocation(location) {
  const root = document.getElementById('sm-detail-location');
  if (!root || !window.RadarDetailLocationMap) return;
  window.RadarDetailLocationMap.mount({
    root,
    location,
    initialLayer: 'street'
  });
}

function renderCompInfoTag(icon, label, extraClass = '') {
  const text = _signalTagText(label);
  if (!text) return '';
  return `
    <span class="sm-comp-tag ${extraClass}">
      <span class="sm-comp-tag-icon">${escHtml(icon)}</span>
      <span>${escHtml(text)}</span>
    </span>
  `;
}

function renderCompTags(c = {}) {
  const areaLabel = _signalTagArea({
    area: c.area_m2 || c.area,
    frontage: c.frontage_m || c.frontage,
    depth: c.depth_m || c.depth,
  });
  const roadLabel = c.street_label || c.streetLabel || c.road_label || c.roadLabel || c.road_type || c.road;
  const propertyLabel = c.property_type_label || c.prop_type_label || propertyTypeLabel(c.property_type || c.ptype);
  const landLabel = _signalTagThoCu({
    thoCuLabel: c.tho_cu_label || c.thoCuLabel,
    thoCuM2: c.tho_cu_m2 || c.thoCu,
  });
  const ppm2Label = _modalFormatPpm2(c.price_per_m2 || c.actual_ppm2 || c.ppm2);
  return [
    renderCompInfoTag('📍', c.ward, 'sm-comp-ward'),
    renderCompInfoTag('📐', areaLabel, 'sm-comp-area'),
    renderCompInfoTag('↱', roadLabel, 'sm-comp-road'),
    renderCompInfoTag('🏷️', propertyLabel, 'sm-comp-property'),
    renderCompInfoTag('▣', landLabel, 'sm-comp-land'),
    renderCompInfoTag('₫', ppm2Label, 'sm-comp-ppm2'),
  ].filter(Boolean).join('');
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
  document.body.style.overflow = document.body.classList.contains('signal-modal-open') ? 'hidden' : '';
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
  renderSignalThumbs();

  // Signal badge
  const mosValue = d.mos_pct_display ?? d.mos_pct ?? d.mos;
  const mosNum = parseFloat(mosValue) || 0;
  const badgeLabel = mosNum >= 25 ? 'TÍN HIỆU MẠNH' : 'TÍN HIỆU';
  document.getElementById('sm-signal-badge').innerHTML = `<span>${badgeLabel} · -${mosNum.toFixed(1).replace(/\.0$/, '')}%</span>`;

  // Title
  document.getElementById('sm-title').innerText = d.title;

  // Meta line
  renderModalMetaLine(d);

  // Description is lazy-loaded from /api/listing/<id>.
  document.getElementById('sm-desc').innerText = 'Đang tải mô tả chi tiết...';

  // Legacy AI assessment is intentionally hidden while advisory notes own this slot.
  const price = parseFloat(d.price) || 0;
  const area = parseFloat(d.area) || 0;
  hideLegacyAiAssessment();

  // Tags
  const tags = [
    { icon: '📐', label: `${d.area} m²` },
    { icon: '📍', label: d.ward },
    { icon: '🛣️', label: d.road },
  ];
  document.getElementById('sm-tags').innerHTML = tags
    .map(t => `<span>${t.icon} ${t.label}</span>`).join('');
  renderSignalTags({
    area: d.area,
    frontage: d.frontage,
    depth: d.depth,
    ward: d.ward,
    road: d.road,
    roadLabel: d.roadLabel,
    streetLabel: d.streetLabel,
    score: d.score,
    propertyType: d.ptype,
    propertyTypeLabel: d.propLabel,
    thoCuM2: d.thoCu,
    thoCuLabel: d.thoCuLabel
  });

  // Links
  document.getElementById('sm-zalo').dataset.listingId = d.id;
  document.getElementById('sm-zalo').dataset.listingUrl = d.url || `/listing/${d.id}`;
  { const _d = document.getElementById('sm-detail'); if (_d) _d.href = d.url || `/listing/${d.id}`; };
  syncModalFavoriteButton(d.id);
  {
    const actions = modal.querySelector('[data-listing-actions]');
    if (actions) actions.dataset.listingId = d.id;
  }

  // Load price history + comps
  loadSignalHistory(d.id, price, area, d.ward, {
    frontage_m: d.frontage,
    depth_m: d.depth,
    price_per_m2: d.ppm2,
    road_label: d.roadLabel || d.road,
    street_label: d.streetLabel,
    property_type: d.ptype,
    property_type_label: d.propLabel,
    tho_cu_m2: d.thoCu,
    tho_cu_label: d.thoCuLabel,
  });
  hydrateSignalDetail(d.id);

  modal.style.display = 'flex';
}

async function _hydrateSignalDetailLegacy(listingId) {
  const modal = document.getElementById('signalModal');
  try {
    const res = await fetch(`/api/listing/${listingId}`, { cache: 'no-store' });
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    const data = await res.json();
    if (modal.dataset.listingId !== String(listingId)) return;

    document.getElementById('sm-title').innerText = data.title || document.getElementById('sm-title').innerText;
    document.getElementById('sm-desc').innerHTML = renderTextWithContactCta(
      data.description || 'Không có mô tả.',
      data.id || listingId,
      'redacted_description_modal'
    );
    renderSignalDetailLocation(data.map_location);
    document.getElementById('sm-zalo').dataset.listingId = data.id || listingId;
    document.getElementById('sm-zalo').dataset.listingUrl = data.url || `/listing/${listingId}`;
    { const _d = document.getElementById('sm-detail'); if (_d) _d.href = data.url || `/listing/${listingId}`; };
    syncModalFavoriteButton(data.id || listingId);
    renderSignalTags({
      area: data.area_m2,
      frontage: data.frontage_m,
      depth: data.depth_m,
      ward: data.ward,
      road: data.road_type || data.road_tier || '-',
      roadLabel: data.road_label,
      streetLabel: data.street_label,
      score: data.signal_score || '-',
      propertyType: data.property_type,
      propertyTypeLabel: data.property_type_label,
      thoCuM2: data.tho_cu_m2,
      thoCuLabel: data.tho_cu_label
    });

    const imgs = Array.isArray(data.imgs) ? data.imgs.filter(Boolean) : [];
    galleryImages = imgs.length ? imgs : [PLACEHOLDER_IMG];
    if (galleryImages.length) {
      buildSlider(galleryImages);
      renderSignalThumbs();
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
      await ensureChartJs();
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

function _memoDisplayText(text) {
  return String(text || '')
    .replace(/Investment Memo Cố Vấn/gi, 'Ghi chú cố vấn đầu tư')
    .replace(/Investment Memo/gi, 'Ghi chú cố vấn đầu tư')
    .replace(/\bVerdict\b/gi, 'Kết luận')
    .replace(/\bMOS\b/g, 'biên an toàn')
    .replace(/Stress test/gi, 'Kiểm tra giả định')
    .replace(/fair value/gi, 'giá trị tham chiếu')
    .replace(/fair total/gi, 'tổng giá trị tham chiếu')
    .replace(/signal score/gi, 'điểm tín hiệu')
    .replace(/\bcomps?\b/gi, 'lô so sánh')
    .replace(/market approach/gi, 'phương pháp so sánh thị trường')
    .replace(/sales comparison approach/gi, 'phương pháp so sánh thị trường')
    .replace(/income approach/gi, 'phương pháp dòng tiền')
    .replace(/cost approach/gi, 'phương pháp chi phí/thay thế')
    .replace(/highest and best use/gi, 'giá trị sử dụng tốt nhất')
    .replace(/due diligence/gi, 'kiểm tra trước khi đặt cọc')
    .replace(/\bsignal\b/gi, 'tín hiệu')
    .replace(/\bdeal\b/gi, 'thương vụ')
    .replace(/\bsource\b/gi, 'nguồn')
    .replace(/\btrust\b/gi, 'độ tin cậy')
    .replace(/\blegal\b/gi, 'pháp lý');
}

function _memoMarkdownToHtml(markdown) {
  const lines = _memoDisplayText(markdown).split(/\r?\n/);
  const html = [];
  let listOpen = false;
  const closeList = () => {
    if (listOpen) {
      html.push('</ul>');
      listOpen = false;
    }
  };
  lines.forEach((raw) => {
    const line = raw.trim();
    if (!line) {
      closeList();
      return;
    }
    if (/^#{1,3}\s+/.test(line)) {
      closeList();
      html.push(`<h4>${escHtml(line.replace(/^#{1,3}\s+/, ''))}</h4>`);
      return;
    }
    if (/^[-*]\s+/.test(line)) {
      if (!listOpen) {
        html.push('<ul class="sm-memo-list">');
        listOpen = true;
      }
      html.push(`<li>${escHtml(line.replace(/^[-*]\s+/, ''))}</li>`);
      return;
    }
    closeList();
    html.push(`<p>${escHtml(line)}</p>`);
  });
  closeList();
  return html.join('');
}

function _splitMemoForPreview(markdown) {
  const lines = _memoDisplayText(markdown).split(/\r?\n/);
  const isH1 = (line) => /^#\s+/.test(line.trim());
  const isH2 = (line) => /^##\s+/.test(line.trim());
  const splitDenseSection = (startIdx, endIdx) => {
    const section = lines.slice(startIdx, endIdx);
    const detailIdx = section.findIndex((line, idx) => (
      idx > 0 && /^(Thương vụ|Deal|Tóm tắt|Thông tin|Dữ liệu)\s*:/i.test(line.trim())
    ));
    if (detailIdx > 0) {
      const preview = section.slice(0, detailIdx).join('\n').trim();
      const rest = [
        '## Chi tiết cố vấn',
        ...section.slice(detailIdx),
        ...lines.slice(endIdx),
      ].join('\n').trim();
      return { preview, rest };
    }

    let paragraphCount = 0;
    let previewEnd = section.length;
    for (let i = 1; i < section.length; i += 1) {
      const line = section[i].trim();
      if (!line) {
        if (paragraphCount >= 2) {
          previewEnd = i + 1;
          break;
        }
        continue;
      }
      paragraphCount += 1;
    }
    if (previewEnd < section.length) {
      return {
        preview: section.slice(0, previewEnd).join('\n').trim(),
        rest: [
          '## Chi tiết cố vấn',
          ...section.slice(previewEnd),
          ...lines.slice(endIdx),
        ].join('\n').trim(),
      };
    }
    return {
      preview: section.join('\n').trim(),
      rest: lines.slice(endIdx).join('\n').trim(),
    };
  };
  const conclusionIdx = lines.findIndex((line) => /^##\s+Kết luận\b/i.test(line.trim()));
  if (conclusionIdx >= 0) {
    let endIdx = lines.length;
    for (let i = conclusionIdx + 1; i < lines.length; i += 1) {
      if (isH2(lines[i])) {
        endIdx = i;
        break;
      }
    }
    return splitDenseSection(conclusionIdx, endIdx);
  }

  const firstContent = lines.findIndex((line) => line.trim() && !isH1(line));
  const start = firstContent >= 0 ? firstContent : 0;
  let end = lines.length;
  for (let i = start + 1; i < lines.length; i += 1) {
    if (isH2(lines[i])) {
      end = i;
      break;
    }
  }
  return {
    preview: lines.slice(start, end).join('\n').trim(),
    rest: lines.slice(end).join('\n').trim(),
  };
}

function _memoVerdictLabel(verdict) {
  const labels = {
    cheap_real: 'Rẻ thật',
    fair: 'Giá hợp lý',
    overpriced: 'Giá cao',
    fake_price: 'Nghi giá mồi',
    cannot_price: 'Không đủ dữ liệu định giá',
    suspect: 'Cần nghi ngờ',
    not_cheap: 'Chưa đủ rẻ',
    insufficient_info: 'Thiếu thông tin',
    memo: 'Cố vấn',
  };
  return labels[verdict] || verdict || 'Cố vấn';
}

function _memoFlagLabel(flag) {
  const labels = {
    low_segment_confidence: 'mẫu so sánh mỏng',
    approximate_price_text: 'giá ghi ước lượng',
    missing_road_info: 'thiếu thông tin đường',
    missing_location_detail: 'thiếu vị trí cụ thể',
    planning_or_tho_cu_dependency: 'phụ thuộc quy hoạch/thổ cư',
    needs_location_check: 'cần kiểm tra vị trí',
    needs_map_check: 'cần kiểm tra bản đồ',
    legal_unverified: 'pháp lý chưa xác minh',
    many_reposts: 'đăng lại nhiều lần',
    repost_history: 'có lịch sử đăng lại',
    high_total_price: 'giá tổng cao',
    extreme_low_ppm2: 'giá/m2 thấp bất thường',
    large_land_check: 'đất diện tích lớn cần soi kỹ',
    thin_margin: 'biên an toàn mỏng',
    parsed_price_mismatch: 'giá đọc được có thể lệch',
    needs_price_confirmation: 'cần xác nhận giá chốt',
    low_tho_cu_ratio: 'tỷ lệ thổ cư thấp',
    road_width_check: 'cần kiểm tra độ rộng đường',
    verify_tho_cu: 'cần xác minh thổ cư',
    verify_exact_lot: 'cần xác minh đúng lô',
  };
  return labels[flag] || _memoDisplayText(flag).replace(/_/g, ' ');
}

function renderInvestmentMemoLoading() {
  const body = document.getElementById('sm-memo-body');
  if (!body) return;
  body.innerHTML = '<div class="sm-empty-state">Đang tải ghi chú...</div>';
}

function renderInvestmentMemoLocked() {
  const body = document.getElementById('sm-memo-body');
  if (!body) return;
  body.innerHTML = `
    <div class="sm-memo-locked">
      <b>Đăng nhập để xem Cố vấn</b><br>
      Tài khoản miễn phí có thể xem ghi chú cố vấn cho từng tín hiệu: định giá, rủi ro cần kiểm tra và góc nhìn đầu tư.
      <div style="margin-top:10px;">
        <button type="button" class="sm-comps-toggle" onclick="RadarAuth.openAuthModal('Đăng nhập miễn phí để xem cố vấn đầu tư.')">Đăng nhập</button>
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
  if (data.pending) {
    body.innerHTML = `
      <div class="sm-memo-head">
        <span class="sm-memo-verdict muted">Đang chờ ghi chú</span>
        <p class="sm-memo-summary">${escHtml(_memoDisplayText(data.message || 'Chưa có ghi chú cố vấn cho thương vụ này.'))}</p>
      </div>
    `;
    return;
  }
  const verdict = data.verdict || 'memo';
  const confidence = Number(data.confidence);
  const confidenceText = Number.isFinite(confidence) ? ` · ${Math.round(confidence * 100)}%` : '';
  const flags = Array.isArray(data.red_flags) ? data.red_flags.filter(Boolean) : [];
  const memoParts = _splitMemoForPreview(data.memo_markdown || '');
  const hasFullMemo = Boolean((data.memo_markdown || '').trim());
  const restHtml = memoParts.rest
    ? `
      <details class="sm-memo-more">
        <summary>Xem thêm</summary>
        <div class="sm-memo-markdown sm-memo-more-body">${_memoMarkdownToHtml(memoParts.rest)}</div>
      </details>
    `
    : '';
  const adminWorkflow = data.admin_valuation_workflow_markdown
    ? `
      <details class="sm-memo-admin-tech">
        <summary>Luồng định giá kỹ thuật</summary>
        <div class="sm-memo-markdown sm-memo-admin-markdown">${_memoMarkdownToHtml(data.admin_valuation_workflow_markdown)}</div>
      </details>
    `
    : '';
  body.innerHTML = `
    <div class="sm-memo-head">
      <span class="sm-memo-verdict ${escHtml(verdict)}">${escHtml(_memoVerdictLabel(verdict))}${confidenceText}</span>
      ${!hasFullMemo && data.reasoning ? `<p class="sm-memo-summary">${escHtml(_memoDisplayText(data.reasoning))}</p>` : ''}
    </div>
    <div class="sm-memo-markdown">${_memoMarkdownToHtml(memoParts.preview || data.memo_markdown || '')}</div>
    ${restHtml}
    ${adminWorkflow}
    ${flags.length ? `<div class="sm-memo-note">Điểm cần lưu ý: ${escHtml(flags.map(_memoFlagLabel).join(', '))}</div>` : ''}
  `;
}

function hideLegacyAiAssessment() {
  const aiSection = document.getElementById('sm-ai-section');
  const aiText = document.getElementById('sm-ai-text');
  if (aiText) aiText.innerHTML = '';
  if (aiSection) {
    aiSection.hidden = true;
    aiSection.setAttribute('aria-hidden', 'true');
    aiSection.style.display = 'none';
  }
}

function setInvestmentMemoVisible(visible) {
  const section = document.getElementById('sm-memo-section');
  const body = document.getElementById('sm-memo-body');
  if (body && !visible) body.innerHTML = '';
  if (section) {
    section.hidden = !visible;
    section.setAttribute('aria-hidden', visible ? 'false' : 'true');
    section.style.display = visible ? '' : 'none';
  }
}

async function loadInvestmentMemo(listingId) {
  if (!INVESTMENT_MEMO_ENABLED) {
    setInvestmentMemoVisible(false);
    return;
  }
  setInvestmentMemoVisible(true);
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
    console.error('Advisory memo load error:', err);
    const body = document.getElementById('sm-memo-body');
    if (body) body.innerHTML = '<div class="sm-empty-state">Không tải được cố vấn đầu tư.</div>';
  }
}

// Override modal handlers with finalized V2 logic (keeps backward compatibility with existing onclick hooks).
function openSignal(card) {
  _openSignalFromData(card.dataset, { pushHistory: true });
}

function _openSignalFromData(d, opts = {}) {
  const modal = document.getElementById('signalModal');
  const listingIdNumber = Number(d.id);
  if (!Number.isSafeInteger(listingIdNumber) || listingIdNumber <= 0) return;
  const listingId = String(listingIdNumber);
  modal.dataset.listingId = listingId;
  const actions = modal.querySelector('[data-listing-actions]');
  if (actions) actions.dataset.listingId = listingId;
  const locationSection = modal.querySelector('[data-detail-location]');
  if (locationSection && window.RadarDetailLocationMap) {
    window.RadarDetailLocationMap.unmount(locationSection);
  }
  switchSignalPanel('desc');

  const imgs = d.primary ? [d.primary] : [];
  buildSlider(imgs);
  galleryImages = imgs.length ? imgs : [PLACEHOLDER_IMG];
  renderSignalThumbs();

  const mosValue = d.mos_pct_display ?? d.mos_pct ?? d.mos;
  const mosNum = parseFloat(mosValue) || 0;
  const badgeLabel = mosNum >= 25 ? 'TÍN HIỆU MẠNH' : 'TÍN HIỆU';
  document.getElementById('sm-signal-badge').innerHTML = `<span>${badgeLabel} · -${mosNum.toFixed(1).replace(/\.0$/, '')}%</span>`;
  renderModalTitle(d.title || '');
  renderModalMetaLine(d);
  document.getElementById('sm-desc').innerText = 'Đang tải mô tả chi tiết...';

  // Legacy AI assessment is intentionally hidden for now.
  const price = parseFloat(d.price) || 0;
  const area = parseFloat(d.area) || 0;
  hideLegacyAiAssessment();

  renderSignalTags({
    area: d.area,
    frontage: d.frontage,
    depth: d.depth,
    ward: d.ward,
    road: d.road,
    roadLabel: d.roadLabel,
    streetLabel: d.streetLabel,
    score: d.score,
    propertyType: d.ptype,
    propertyTypeLabel: d.propLabel,
    thoCuM2: d.thoCu,
    thoCuLabel: d.thoCuLabel
  });
  updateSignalSummary(d);

  document.getElementById('sm-zalo').dataset.listingId = listingId;
  document.getElementById('sm-zalo').dataset.listingUrl = d.url || `/listing/${listingId}`;
  { const _d = document.getElementById('sm-detail'); if (_d) _d.href = d.url || `/listing/${listingId}`; };
  syncModalFavoriteButton(listingId);

  loadSignalHistory(listingId, price, area, d.ward, {
    frontage_m: d.frontage,
    depth_m: d.depth,
    price_per_m2: d.ppm2,
    road_label: d.roadLabel || d.road,
    street_label: d.streetLabel,
    property_type: d.ptype,
    property_type_label: d.propLabel,
    tho_cu_m2: d.thoCu,
    tho_cu_label: d.thoCuLabel,
  });
  loadInvestmentMemo(listingId);
  hydrateSignalDetail(listingId);
  const content = modal.querySelector('.signal-modal-content');
  if (content) content.scrollTop = 0;
  setSignalModalOpen(true);
  modal.style.display = 'flex';
  if (opts.pushHistory !== false) {
    _pushSignalModalHistory(listingId);
  }
}

function openListingModal(row) {
  const d = row.dataset;
  _openSignalFromData({
    id: d.id,
    title: d.title,
    primary: d.primary,
    price: d.price,
    ppm2: d.ppm2,
    fair: d.fair,
    area: d.area,
    frontage: d.frontage,
    depth: d.depth,
    ward: d.ward,
    road: d.road,
    time: d.time,
    profit: d.profit,
    mos: d.mos,
    mos_pct_display: d.mosPctDisplay,
    mos_pct_old: d.mosPctOld,
    mos_pct_new: d.mosPctNew,
    fair_ppm2_old: d.fairPpm2Old,
    fair_ppm2_new: d.fairPpm2New,
    fair_ppm2_display: d.fairPpm2Display,
    source: d.source,
    drop: d.drop,
    score: d.score,
    url: d.url,
    ptype: d.ptype,
    roadLabel: d.roadLabel,
    streetLabel: d.streetLabel,
    propLabel: d.propLabel,
    thoCu: d.thoCu,
    thoCuLabel: d.thoCuLabel
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
    document.getElementById('sm-desc').innerHTML = renderTextWithContactCta(
      data.description || 'Không có mô tả.',
      data.id || listingId,
      'redacted_description_modal'
    );
    renderSignalDetailLocation(data.map_location);
    document.getElementById('sm-zalo').dataset.listingId = data.id || listingId;
    document.getElementById('sm-zalo').dataset.listingUrl = data.url || `/listing/${listingId}`;
    { const _d = document.getElementById('sm-detail'); if (_d) _d.href = data.url || `/listing/${listingId}`; };
    syncModalFavoriteButton(data.id || listingId);
    renderSignalTags({
      area: data.area_m2,
      frontage: data.frontage_m,
      depth: data.depth_m,
      ward: data.ward,
      road: data.road_type || data.road_tier || '-',
      roadLabel: data.road_label,
      streetLabel: data.street_label,
      score: data.signal_score || '-',
      propertyType: data.property_type,
      propertyTypeLabel: data.property_type_label,
      thoCuM2: data.tho_cu_m2,
      thoCuLabel: data.tho_cu_label
    });
    updateSignalSummary(data);

    const imgs = Array.isArray(data.imgs) ? data.imgs.filter(Boolean) : [];
    galleryImages = imgs.length ? imgs : [PLACEHOLDER_IMG];
    buildSlider(galleryImages);
    renderSignalThumbs();
  } catch (err) {
    console.error(err);
    if (modal.dataset.listingId === String(listingId)) {
      document.getElementById('sm-desc').innerText = 'Không tải được mô tả chi tiết.';
    }
  }
}

const SM_HISTORY_VISIBLE_LIMIT = 3;

function _historyPriceLabel(value) {
  const n = Number(value);
  if (!Number.isFinite(n) || n <= 0) return '-';
  return `${n.toLocaleString('vi-VN', { maximumFractionDigits: 2 })} tỷ`;
}

function _historyShortDate(value) {
  const text = String(value || '').slice(0, 10);
  const parts = text.split('-');
  if (parts.length === 3) return `${parts[2]}/${parts[1]}/${parts[0]}`;
  return text || '-';
}

function _decorateSignalHistoryTimeline(timeline) {
  let previousPrice = null;
  return timeline.map((h, index) => {
    const price = Number(h.price_ty);
    let changePct = null;
    if (previousPrice && Number.isFinite(price) && previousPrice > 0) {
      changePct = ((price - previousPrice) / previousPrice) * 100;
    }
    if (Number.isFinite(price)) previousPrice = price;
    return {
      ...h,
      _change_pct: changePct,
      _is_latest: index === timeline.length - 1,
    };
  });
}

function _historySummaryHtml(timeline, fallbackCurrentPrice) {
  if (!timeline.length) return '';
  const first = timeline[0];
  const latest = timeline[timeline.length - 1];
  const firstPrice = Number(first.price_ty);
  const latestPrice = Number(latest.price_ty || fallbackCurrentPrice);
  const netPct = Number.isFinite(firstPrice) && firstPrice > 0 && Number.isFinite(latestPrice)
    ? ((latestPrice - firstPrice) / firstPrice) * 100
    : null;
  const netClass = Number.isFinite(netPct) && netPct < 0 ? 'is-down' : (Number.isFinite(netPct) && netPct > 0 ? 'is-up' : 'is-flat');
  const netText = Number.isFinite(netPct)
    ? `${netPct > 0 ? '+' : ''}${netPct.toFixed(1)}%`
    : '-';

  return `
    <div class="sm-history-summary" aria-label="Tóm tắt lịch sử giá">
      <span><strong>${timeline.length}</strong><small>mốc giá</small></span>
      <span><strong>${_historyPriceLabel(latestPrice)}</strong><small>mới nhất</small></span>
      <span class="${netClass}"><strong>${netText}</strong><small>biến động</small></span>
    </div>
  `;
}

function renderSignalHistoryRows(timeline, opts = {}) {
  if (!timeline.length) return '<div class="sm-empty-state">Chưa có lịch sử giá cho lô này.</div>';
  const isAdmin = opts.isAdmin === true;
  const visibleLimit = opts.visibleLimit || SM_HISTORY_VISIBLE_LIMIT;
  const rows = [...timeline].reverse().map((h, index) => {
    const hidden = index >= visibleLimit;
    const change = Number(h._change_pct);
    const changeHtml = Number.isFinite(change)
      ? `<span class="ph-change ${change < 0 ? 'is-down' : (change > 0 ? 'is-up' : 'is-flat')}">${change === 0 ? 'Không đổi' : `${change > 0 ? '+' : ''}${change.toFixed(1)}%`}</span>`
      : '<span class="ph-change is-flat">Mốc đầu</span>';
    const originLink = isAdmin && h.url
      ? `<a class="ph-lot-link" href="${escHtml(h.url)}" target="_blank" rel="noopener noreferrer" onclick="event.stopPropagation()">Tin gốc</a>`
      : '';
    return `<div class="ph-row ph-price-row ${h._is_latest ? 'is-latest' : ''} ${hidden ? 'is-history-extra' : ''}"${hidden ? ' hidden' : ''}>
      <span class="ph-dot" aria-hidden="true"></span>
      <div class="ph-main">
        <span class="ph-date">${escHtml(_historyShortDate(h.date))}</span>
        <span class="ph-sub">${h._is_latest ? 'Giá mới nhất' : 'Mốc lịch sử'}</span>
      </div>
      <span class="ph-price">${escHtml(_historyPriceLabel(h.price_ty))}</span>
      ${changeHtml}
      ${originLink}
    </div>`;
  }).join('');

  const hiddenCount = Math.max(0, timeline.length - visibleLimit);
  const toggle = hiddenCount > 0
    ? `<button type="button" class="sm-history-toggle" data-collapsed-text="Xem thêm ${hiddenCount} mốc" data-expanded-text="Thu gọn lịch sử" onclick="toggleSignalHistoryRows(this)">Xem thêm ${hiddenCount} mốc</button>`
    : '';
  return `${rows}${toggle}`;
}

function _historyChartTimeline(timeline) {
  return Array.isArray(timeline) ? timeline : [];
}

function toggleSignalHistoryRows(button) {
  const root = button && button.closest('.sm-price-history');
  if (!root) return;
  const expanded = root.classList.toggle('is-expanded');
  root.querySelectorAll('.is-history-extra').forEach((row) => {
    row.hidden = !expanded;
  });
  button.textContent = expanded
    ? (button.dataset.expandedText || 'Thu gọn lịch sử')
    : (button.dataset.collapsedText || 'Xem thêm');
}

async function loadSignalHistory(listingId, currentPrice, area, ward, currentMeta = {}) {
  // Chart/history elements only exist for admin tier. Comps table is always present.
  const modal = document.getElementById('signalModal');
  const historyEl = document.getElementById('sm-price-history');
  const chartEl = document.getElementById('sm-history-chart');
  const compsBody = document.getElementById('sm-comps-body');
  if (historyEl) historyEl.innerHTML = '<div style="opacity:0.5;padding:8px 0;">Đang tải lịch sử...</div>';
  if (compsBody) compsBody.innerHTML = '<div class="sm-empty-state">Đang tải giao dịch tương tự...</div>';
  if (smHistoryChart) { smHistoryChart.destroy(); smHistoryChart = null; }
  smHistoryChartTimeline = [];

  try {
    const res = await fetch(`/api/history/${listingId}`);
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    const data = await res.json();
    if (modal && modal.dataset.listingId !== String(listingId)) return;
    const sameListingHistory = Array.isArray(data.history) ? data.history : [];
    const lotHistory = Array.isArray(data.lot_history) ? data.lot_history : [];

    const timelineByKey = new Map();
    [...sameListingHistory, ...lotHistory]
      .filter((h) => h && h.date && h.price_ty)
      .sort((a, b) => String(a.date || '').localeCompare(String(b.date || '')))
      .forEach((h) => {
        const priceKey = Number(h.price_ty);
        const key = `${h.date}|${Number.isFinite(priceKey) ? priceKey.toFixed(6) : h.price_ty}`;
        const existing = timelineByKey.get(key);
        if (!existing) {
          timelineByKey.set(key, { ...h });
          return;
        }
        if (!existing.url && h.url) existing.url = h.url;
        if (!existing.is_current && h.is_current) existing.is_current = true;
      });
    const timeline = Array.from(timelineByKey.values());

    const isAdmin = window.USER_TIER === 'admin';
    const decoratedTimeline = _decorateSignalHistoryTimeline(timeline);

    if (historyEl) {
      historyEl.innerHTML = `
        <div class="sm-section-label sm-history-label">Lịch sử giá lô này</div>
        ${_historySummaryHtml(decoratedTimeline, currentPrice)}
        <div class="sm-history-timeline">
          ${renderSignalHistoryRows(decoratedTimeline, { isAdmin })}
        </div>
      `;
    }

    smHistoryChartTimeline = decoratedTimeline;
    const chartTimeline = _historyChartTimeline(decoratedTimeline);
    const labels = chartTimeline.map((h) => _historyShortDate(h.date));

    if (labels.length > 0 && chartEl) {
      await ensureChartJs();
      const ctx = chartEl.getContext('2d');
      smHistoryChart = new Chart(ctx, {
        type: 'line',
        data: {
          labels,
          datasets: [
            {
              label: 'Lịch sử giá',
              data: chartTimeline.map((h) => h.price_ty),
              borderColor: '#2563eb',
              backgroundColor: 'rgba(37,99,235,0.1)',
              pointBackgroundColor: chartTimeline.map((h) => h._is_latest ? '#10b981' : '#2563eb'),
              pointBorderColor: '#ffffff',
              pointHoverRadius: 5,
              fill: true,
              tension: 0.32,
              pointRadius: labels.length > 10 ? 2.5 : 3.5,
              borderWidth: 2.5
            }
          ]
        },
        options: {
          maintainAspectRatio: false,
          interaction: { intersect: false, mode: 'index' },
          plugins: {
            legend: { display: false },
            tooltip: {
              callbacks: {
                label: (ctx) => `Giá rao: ${_historyPriceLabel(ctx.parsed.y)}`
              }
            }
          },
          scales: {
            x: {
              grid: { display: false },
              ticks: { font: { size: 10, weight: '700' }, maxRotation: 0, autoSkip: true, maxTicksLimit: 5 }
            },
            y: {
              grid: { color: 'rgba(148,163,184,0.18)', drawBorder: false },
              ticks: {
                font: { size: 10, weight: '700' },
                callback: (value) => `${Number(value).toLocaleString('vi-VN', { maximumFractionDigits: 1 })} tỷ`
              }
            }
          }
        }
      });
    }

    if (compsBody && window.RadarComparableCarousel) {
      window.RadarComparableCarousel.mount(
        document.getElementById('sm-panel-comps'),
        Array.isArray(data.comps) ? data.comps : [],
        { openMode: 'modal', openHandler: 'openSignal' },
      );
    }
  } catch (err) {
    console.error('History load error:', err);
    if (historyEl) historyEl.innerHTML = '<div style="opacity:0.5;padding:8px 0;">Không tải được dữ liệu.</div>';
    if (compsBody) compsBody.innerHTML = '<div class="sm-empty-state">Lỗi tải dữ liệu.</div>';
  }
}


async function openHistory(id, title) {
  document.getElementById('historyTitle').innerText = `Lịch sử giá: ${title}`;
  document.getElementById('historyModal').style.display = 'flex';

  try {
    const res = await fetch(`/api/history/${id}`);
    const data = await res.json();

    if (historyChartInstance) historyChartInstance.destroy();

    await ensureChartJs();
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
  const modal = document.getElementById(id);
  if (!modal) return;
  if (id === 'signalModal') {
    if (_closeSignalModalViaHistory()) return;
    _closeSignalModalDirect();
    return;
  }
  modal.style.display = 'none';
  if (id === 'galleryModal') {
    document.body.style.overflow = document.body.classList.contains('signal-modal-open') ? 'hidden' : '';
  }
}

window.addEventListener('popstate', () => {
  if (!_signalModalIsOpen()) return;
  const modal = document.getElementById('signalModal');
  const nextSignal = new URLSearchParams(window.location.search).get('signal');
  const state = history.state || {};
  if (!state.signalModal || nextSignal !== modal.dataset.listingId) {
    _closeSignalModalDirect();
  }
});

window.onclick = function (event) {
  if (event.target.classList.contains('modal')) {
    closeModal(event.target.id);
  }
}

document.addEventListener('keydown', (event) => {
  const galleryModal = document.getElementById('galleryModal');
  if (galleryModal && galleryModal.style.display === 'flex') {
    if (event.key === 'Escape') closeGallery();
    if (event.key === 'ArrowLeft') slideGallery(-1);
    if (event.key === 'ArrowRight') slideGallery(1);
    return;
  }
  const signalModal = document.getElementById('signalModal');
  if (signalModal && signalModal.style.display === 'flex' && event.key === 'Escape') {
    closeModal('signalModal');
    return;
  }
  const leadModal = document.getElementById('leadCaptureModal');
  if (leadModal && leadModal.style.display === 'flex' && event.key === 'Escape') {
    closeLeadCaptureModal();
  }
});

