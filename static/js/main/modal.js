// Signal detail modal, gallery, memo, price history, and generic modal helpers.
const INVESTMENT_MEMO_ENABLED = false;
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
    ? _smSlideImgs.map((src, i) => `<img class="sm-thumb ${i === _smSlideIdx ? 'active' : ''}" src="${escHtml(src)}" onclick="setSignalSlide(${i})" ondblclick="openGallery(${i})" onerror="this.style.display='none'">`).join('')
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
        onclick="openGallery(${i})"
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

function updateSignalSummary(data = {}) {
  const price = _modalNumber(data.price_ty ?? data.price);
  const area = _modalNumber(data.area_m2 ?? data.area);
  const actualPpm2 = _modalNumber(data.actual_ppm2 ?? data.ppm2);
  const fairPpm2 = _modalNumber(data.fair_ppm2 ?? data.fppm2);
  let fairTotal = _modalNumber(data.fair_total_ty ?? data.fair);
  if ((!Number.isFinite(fairTotal) || fairTotal <= 0) && Number.isFinite(fairPpm2) && Number.isFinite(area) && area > 0) {
    fairTotal = fairPpm2 * area / 1000;
  }
  const computedActualPpm2 = Number.isFinite(actualPpm2)
    ? actualPpm2
    : (Number.isFinite(price) && Number.isFinite(area) && area > 0 ? price * 1000 / area : NaN);
  const mos = _modalNumber(data.mos_pct ?? data.mos);
  const score = _modalNumber(data.signal_score ?? data.score);

  _modalSetText('sm-sum-price', _modalFormatTy(price));
  _modalSetText('sm-sum-price-m2', _modalFormatPpm2(computedActualPpm2));
  _modalSetText('sm-sum-fair', _modalFormatTy(fairTotal));
  _modalSetText('sm-sum-fair-m2', _modalFormatPpm2(fairPpm2));
  _modalSetText('sm-sum-mos', Number.isFinite(mos) ? `${mos.toFixed(1).replace(/\.0$/, '')}%` : '-');
  _modalSetText('sm-sum-score', Number.isFinite(score) ? `Score ${Math.round(score)}` : 'Score -');
}

function switchSignalPanel(panel = 'desc', btn = null) {
  const modal = document.getElementById('signalModal');
  if (!modal) return;
  modal.dataset.activePanel = panel;
  modal.querySelectorAll('.sm-tab').forEach((tab) => {
    tab.classList.toggle('active', tab === btn || (!btn && tab.dataset.smTab === panel));
  });
  modal.querySelectorAll('.sm-panel[data-sm-panel]').forEach((section) => {
    section.classList.toggle('active', section.dataset.smPanel === panel);
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
    document.getElementById('sm-desc').innerHTML = renderTextWithContactCta(
      data.description || 'Không có mô tả.',
      data.id || listingId,
      'redacted_description_modal'
    );
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
  switchSignalPanel('desc');

  const imgs = d.primary ? [d.primary] : [];
  buildSlider(imgs);
  galleryImages = imgs.length ? imgs : [PLACEHOLDER_IMG];
  renderSignalThumbs();

  const mosNum = parseFloat(d.mos) || 0;
  const badgeLabel = mosNum >= 25 ? 'SUPER SIGNAL' : 'SIGNAL';
  document.getElementById('sm-signal-badge').innerHTML = `<span>${badgeLabel} · -${d.mos}%</span>`;
  renderModalTitle(d.title || '');
  document.getElementById('sm-meta-line').innerHTML = `<span>Dang ${d.time || '-'}</span> · <span>${d.source || '-'}</span>`;
  document.getElementById('sm-desc').innerText = 'Dang tai mo ta chi tiet...';

  // Groq assessment is intentionally hidden for now.
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
  updateSignalSummary(d);

  document.getElementById('sm-zalo').dataset.listingId = d.id;
  document.getElementById('sm-zalo').dataset.listingUrl = d.url || `/listing/${d.id}`;
  { const _d = document.getElementById('sm-detail'); if (_d) _d.href = d.url || `/listing/${d.id}`; };

  loadSignalHistory(d.id, price, area, d.ward);
  setInvestmentMemoVisible(false);
  hydrateSignalDetail(d.id);
  const content = modal.querySelector('.signal-modal-content');
  if (content) content.scrollTop = 0;
  setSignalModalOpen(true);
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
    document.getElementById('sm-desc').innerHTML = renderTextWithContactCta(
      data.description || 'Không có mô tả.',
      data.id || listingId,
      'redacted_description_modal'
    );
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
    updateSignalSummary(data);

    const imgs = Array.isArray(data.imgs) ? data.imgs.filter(Boolean) : [];
    galleryImages = imgs.length ? imgs : [PLACEHOLDER_IMG];
    buildSlider(galleryImages);
    renderSignalThumbs();
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

    const seenTimeline = new Set();
    const timeline = [...sameListingHistory, ...lotHistory]
      .filter((h) => h && h.date && h.price_ty)
      .sort((a, b) => String(a.date || '').localeCompare(String(b.date || '')))
      .filter((h) => {
        const priceKey = Number(h.price_ty);
        const key = `${h.date}|${Number.isFinite(priceKey) ? priceKey.toFixed(6) : h.price_ty}`;
        if (seenTimeline.has(key)) return false;
        seenTimeline.add(key);
        return true;
      });

    let previousPrice = null;
    const timelineRows = timeline.map((h) => {
      let changeHtml = '';
      if (previousPrice && h.price_ty && previousPrice > 0) {
        const pct = ((h.price_ty - previousPrice) / previousPrice * 100).toFixed(1);
        const cls = Number(pct) < 0 ? 'ph-change is-down' : 'ph-change';
        changeHtml = `<span class="${cls}">${Number(pct) > 0 ? '+' : ''}${pct}%</span>`;
      }
      previousPrice = h.price_ty;
      const subText = h.is_current ? 'Đang rao hiện tại' : 'Giá ghi nhận';
      return `<div class="ph-row ph-price-row">
        <div class="ph-main">
          <span class="ph-date">${escHtml(h.date || '-')}</span>
          <span class="ph-sub">${subText}</span>
        </div>
        <span class="ph-price">${escHtml(h.price_ty || '-')} tỷ</span>
        ${changeHtml}
      </div>`;
    }).join('');

    if (historyEl) {
      historyEl.innerHTML = `
        <div class="sm-section-label sm-history-label">Lịch sử giá lô này</div>
        ${timelineRows || '<div class="sm-empty-state">Chưa có lịch sử giá cho lô này.</div>'}
      `;
    }

    const labels = timeline.map((h) => h.date);

    if (labels.length > 0 && chartEl) {
      const ctx = chartEl.getContext('2d');
      smHistoryChart = new Chart(ctx, {
        type: 'line',
        data: {
          labels,
          datasets: [
            {
              label: 'Lịch sử giá',
              data: timeline.map((h) => h.price_ty),
              borderColor: '#6366f1',
              backgroundColor: 'rgba(99,102,241,0.12)',
              fill: false,
              tension: 0.25,
              pointRadius: 3,
              borderWidth: 2
            }
          ]
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
  const modal = document.getElementById(id);
  if (!modal) return;
  modal.style.display = 'none';
  if (id === 'signalModal') {
    setSignalModalOpen(false);
  }
  if (id === 'galleryModal') {
    document.body.style.overflow = document.body.classList.contains('signal-modal-open') ? 'hidden' : '';
  }
}

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
