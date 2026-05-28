// Signal detail modal, gallery, memo, price history, and generic modal helpers.
const INVESTMENT_MEMO_ENABLED = false;
// Slider state
let _smSlideIdx = 0;
let _smSlideImgs = [];

function slideSignal(dir) {
  if (_smSlideImgs.length <= 1) return;
  _smSlideIdx = (_smSlideIdx + dir + _smSlideImgs.length) % _smSlideImgs.length;
  document.getElementById('sm-slides').style.transform = `translateX(-${_smSlideIdx * 100}%)`;
  // Update counter
  document.getElementById('sm-img-count').innerText = `${_smSlideIdx + 1} / ${_smSlideImgs.length}`;
  // Update dots
  document.querySelectorAll('#sm-dots span').forEach((d, i) => {
    d.style.background = i === _smSlideIdx ? '#fff' : 'rgba(255,255,255,0.4)';
  });
}

function buildSlider(imgs) {
  _smSlideIdx = 0;
  _smSlideImgs = imgs.length ? imgs : [PLACEHOLDER_IMG];
  const slides = document.getElementById('sm-slides');
  const dots = document.getElementById('sm-dots');
  const counter = document.getElementById('sm-img-count');
  const prevBtn = document.getElementById('sm-prev');
  const nextBtn = document.getElementById('sm-next');

  // Build slides
  slides.style.transform = 'translateX(0)';
  slides.innerHTML = _smSlideImgs.map((src, i) => `
    <div style="min-width:100%; height:100%; flex-shrink:0; background:#0f172a;">
      <img src="${src}" style="width:100%; height:100%; object-fit:contain; display:block; background:#0f172a; cursor:zoom-in;"
        onclick="openGallery(${i})"
        onerror="this.onerror=null;this.src=PLACEHOLDER_IMG;">
    </div>`
  ).join('');

  // Dots
  dots.innerHTML = _smSlideImgs.length > 1
    ? _smSlideImgs.map((_, i) => `<span onclick="_smSlideIdx=${i - 1}; slideSignal(1);" style="width:7px; height:7px; border-radius:50%; background:${i === 0 ? '#fff' : 'rgba(255,255,255,0.4)'}; cursor:pointer; transition:background 0.2s; display:inline-block;"></span>`).join('')
    : '';

  // Arrows + counter
  const multi = _smSlideImgs.length > 1;
  prevBtn.style.display = multi ? 'flex' : 'none';
  nextBtn.style.display = multi ? 'flex' : 'none';
  counter.innerText = multi ? `1 / ${_smSlideImgs.length}` : '';
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
    { icon: '📊', label: `Score: ${data.score || '-'}` },
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
  document.body.style.overflow = '';
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
  const thumbsEl = document.getElementById('sm-thumbs');
  thumbsEl.innerHTML = galleryImages.length > 1
    ? galleryImages.map((src, i) => `<img src="${src}" onclick="_smSlideIdx=${i - 1}; slideSignal(1);" ondblclick="openGallery(${i})" onerror="this.style.display='none'">`).join('')
    : '';

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
    { icon: '📊', label: `Score: ${d.score || '-'}` },
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
      const thumbsEl = document.getElementById('sm-thumbs');
      thumbsEl.innerHTML = galleryImages.length > 1
        ? galleryImages.map((src, i) => `<img src="${src}" onclick="_smSlideIdx=${i - 1}; slideSignal(1);" ondblclick="openGallery(${i})" onerror="this.style.display='none'">`).join('')
        : '';
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

  const imgs = d.primary ? [d.primary] : [];
  buildSlider(imgs);
  galleryImages = imgs.length ? imgs : [PLACEHOLDER_IMG];
  const thumbsEl = document.getElementById('sm-thumbs');
  thumbsEl.innerHTML = galleryImages.length > 1
    ? galleryImages.map((src, i) => `<img src="${src}" onclick="_smSlideIdx=${i - 1}; slideSignal(1);" ondblclick="openGallery(${i})" onerror="this.style.display='none'">`).join('')
    : '';

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

  document.getElementById('sm-zalo').dataset.listingId = d.id;
  document.getElementById('sm-zalo').dataset.listingUrl = d.url || `/listing/${d.id}`;
  { const _d = document.getElementById('sm-detail'); if (_d) _d.href = d.url || `/listing/${d.id}`; };

  loadSignalHistory(d.id, price, area, d.ward);
  setInvestmentMemoVisible(false);
  hydrateSignalDetail(d.id);
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

    const imgs = Array.isArray(data.imgs) ? data.imgs.filter(Boolean) : [];
    galleryImages = imgs.length ? imgs : [PLACEHOLDER_IMG];
    buildSlider(galleryImages);
    const thumbsEl = document.getElementById('sm-thumbs');
    thumbsEl.innerHTML = galleryImages.length > 1
      ? galleryImages.map((src, i) => `<img src="${src}" onclick="_smSlideIdx=${i - 1}; slideSignal(1);" ondblclick="openGallery(${i})" onerror="this.style.display='none'">`).join('')
      : '';
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

    let prettyPrevPrice = null;
    const sameRowsPretty = sameListingHistory.map((h) => {
      let changeHtml = '';
      if (prettyPrevPrice && h.price_ty && prettyPrevPrice > 0) {
        const pct = ((h.price_ty - prettyPrevPrice) / prettyPrevPrice * 100).toFixed(1);
        const cls = Number(pct) < 0 ? 'ph-change is-down' : 'ph-change';
        changeHtml = `<span class="${cls}">${pct}%</span>`;
      }
      prettyPrevPrice = h.price_ty;
      return `<div class="ph-row ph-price-row">
        <div class="ph-main">
          <span class="ph-date">${escHtml(h.date || '-')}</span>
          <span class="ph-sub">Giá ghi nhận</span>
        </div>
        <span class="ph-price">${escHtml(h.price_ty || '-')} tỷ</span>
        ${changeHtml}
      </div>`;
    }).join('');

    const lotRowsPretty = lotHistory.length > 1 ? lotHistory.map((h) => {
      const drop = h.price_dropped && h.drop_pct ? `<span class="ph-change is-down">-${escHtml(h.drop_pct)}%</span>` : '';
      const title = escHtml(h.title || 'Tin cùng lô');
      const sourceText = escHtml([h.source, h.is_current ? 'đang rao' : ''].filter(Boolean).join(' · ') || 'Cùng lô');
      const origin = h.url
        ? `<a class="ph-date" href="${escHtml(h.url)}" target="_blank" rel="noopener noreferrer" onclick="event.stopPropagation()" title="${title}">${escHtml(h.date || '-')}</a>`
        : `<span class="ph-date">${escHtml(h.date || '-')}</span>`;
      const detail = h.detail_url
        ? `<a class="ph-lot-link" href="${escHtml(h.detail_url)}" target="_blank" rel="noopener noreferrer" onclick="event.stopPropagation()">Chi tiết</a>`
        : '';
      return `<div class="ph-row ph-lot-row">
        <div class="ph-main">${origin}<span class="ph-sub">${sourceText}</span></div>
        <span class="ph-price">${escHtml(h.price_ty || '-')} tỷ</span>
        ${drop}
        ${detail}
      </div>`;
    }).join('') : '';

    if (historyEl) {
      historyEl.innerHTML = `
        <div class="sm-section-label sm-history-label">Giá theo bài đăng</div>
        ${sameRowsPretty || '<div class="sm-empty-state">Chưa có biến động giá.</div>'}
        <div class="sm-section-label sm-history-label">Lịch sử đăng BĐS</div>
        ${lotRowsPretty || '<div class="sm-empty-state">Không có repost cùng lô.</div>'}
      `;
    }

    const labels = Array.from(new Set([
      ...sameListingHistory.map((h) => h.date),
      ...lotHistory.map((h) => h.date)
    ])).sort();
    const mapSame = {};
    sameListingHistory.forEach((h) => { mapSame[h.date] = h.price_ty; });
    const mapLot = {};
    lotHistory.forEach((h) => { mapLot[h.date] = h.price_ty; });

    if (labels.length > 0 && chartEl) {
      const ctx = chartEl.getContext('2d');
      smHistoryChart = new Chart(ctx, {
        type: 'line',
        data: {
          labels,
          datasets: [
            {
              label: 'Cung tin',
              data: labels.map((d) => (mapSame[d] ?? null)),
              borderColor: '#6366f1',
              backgroundColor: 'rgba(99,102,241,0.12)',
              fill: false,
              tension: 0.25,
              pointRadius: 3,
              borderWidth: 2
            },
            {
              label: 'Cung lo',
              data: labels.map((d) => (mapLot[d] ?? null)),
              borderColor: '#0ea5a4',
              backgroundColor: 'rgba(14,165,164,0.12)',
              fill: false,
              tension: 0.25,
              pointRadius: 3,
              borderWidth: 2,
              borderDash: [5, 4]
            }
          ]
        },
        options: {
          maintainAspectRatio: false,
          plugins: { legend: { display: true, labels: { usePointStyle: true, boxWidth: 8 } } },
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
  document.getElementById(id).style.display = 'none';
}

window.onclick = function (event) {
  if (event.target.classList.contains('modal')) {
    event.target.style.display = 'none';
    if (event.target.id === 'galleryModal') {
      document.body.style.overflow = '';
    }
  }
}

document.addEventListener('keydown', (event) => {
  const galleryModal = document.getElementById('galleryModal');
  if (galleryModal && galleryModal.style.display === 'flex') {
    if (event.key === 'Escape') closeGallery();
    if (event.key === 'ArrowLeft') slideGallery(-1);
    if (event.key === 'ArrowRight') slideGallery(1);
  }
  const leadModal = document.getElementById('leadCaptureModal');
  if (leadModal && leadModal.style.display === 'flex' && event.key === 'Escape') {
    closeLeadCaptureModal();
  }
});
