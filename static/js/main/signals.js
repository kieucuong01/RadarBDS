// Signal feed, insights panels, and infinite-scroll card rendering.
let _sigObserver = null;

function signalQuery(page) {
  const params = new URLSearchParams(currentFilters);
  params.set('sort', signalSort);
  params.set('page', String(page));
  params.set('limit', String(SIGNAL_PAGE_SIZE));
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

function setSignalLoadMoreUI(isLoading) {
  const sentinel = document.getElementById('sig-scroll-sentinel');
  if (!sentinel) return;
  sentinel.classList.toggle('is-loading', Boolean(isLoading));
  sentinel.textContent = isLoading ? 'Đang tải thêm...' : '';
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

function _formatDealDelta(fairNum, priceNum) {
  if (!Number.isFinite(fairNum) || !Number.isFinite(priceNum)) return null;
  const delta = fairNum - priceNum;
  if (!Number.isFinite(delta)) return null;
  return {
    className: delta >= 0 ? 'is-positive' : 'is-negative',
    text: delta >= 0
      ? `Chênh +${delta.toFixed(2)} tỷ`
      : `Cao hơn ${Math.abs(delta).toFixed(2)} tỷ`
  };
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
    grid.insertAdjacentHTML('beforeend', chunk.map(x => {
      const fairPrice = x.fair_ppm2 ? (x.fair_ppm2 * x.area_m2 / 1000).toFixed(2) : '-';
      const fairNum = fairPrice !== '-' ? parseFloat(fairPrice) : NaN;
      const priceNum = parseFloat(x.price_ty);
      const dealDelta = _formatDealDelta(fairNum, priceNum);
      const priceLabel = x.price_label || (x.price_ty ? `${x.price_ty} tỷ` : '-');
      const profit = fairPrice !== '-' ? (fairNum - priceNum).toFixed(2) : '-';
      const isOverpriced = Number.isFinite(priceNum) && Number.isFinite(fairNum) && priceNum > fairNum;
      const actualClass = isOverpriced ? 'price-over' : 'price-deal';
      const mosRounded = Math.round(_signalNumber(x.mos_pct) || 0);
      const imageCount = Math.max(0, Math.floor(_signalNumber(x.image_count) || 0));
      const imageCounterHtml = imageCount > 1 ? `<div class="sc-image-count">1/${imageCount}</div>` : '';

      const daysAgo = _daysAgoValue(x.days_ago);
      let timeStr = _timeAgoText(daysAgo);
      let legalStr = (x.has_so === true || x.has_so === 1) ? 'Sổ Hồng' : ((x.has_so === false || x.has_so === 0) ? 'Chờ sổ' : 'Đang cập nhật');

      const roadTiers = {
        1: 'Mặt tiền',
        2: 'Đường nhựa',
        3: 'Hẻm xe hơi',
        4: 'Hẻm xe máy'
      };
      let roadStr = roadTiers[x.road_tier] || 'Chưa rõ';

      const safeTitle = String(x.title || '').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
      const imgSrc = x.primary_img || PLACEHOLDER_IMG;
      const dataAttr = `data-id="${x.id}" data-title="${safeTitle}" data-primary="${imgSrc}" data-price="${x.price_ty}" data-ppm2="${x.actual_ppm2}" data-fair="${fairPrice}" data-fppm2="${x.fair_ppm2}" data-area="${x.area_m2}" data-ward="${x.ward}" data-road="${roadStr}" data-time="${timeStr}" data-profit="${profit}" data-mos="${x.mos_pct}" data-source="${sourceNames[x.source] || x.source}" data-drop="${x.drop_pct || ''}" data-score="${x.signal_score || '-'}" data-url="${x.url || ''}" data-ptype="${x.prop_type || ''}"`;

      const isNew = _isNewWithin(x.days_ago, 7);
      const newBadgeHtml = isNew ? `<div class="new-badge"><svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/></svg> MỚI</div>` : '';

      const srcName = sourceNames[x.source] || x.source;
      const dropBadge = x.price_dropped ? `<span class="sc-drop-tag"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="12 4 12 20"/><polyline points="6 14 12 20 18 14"/></svg> Chủ hạ: ${x.drop_pct ? x.drop_pct + '%' : 'N/A'}</span>` : '';

      return `
      <div class="scard" onclick="openSignal(this)" ${dataAttr}>
        <div class="sc-img-wrap">
          <img class="sc-img" src="${imgSrc}" loading="lazy" decoding="async" width="640" height="416" alt="Img" onerror="this.onerror=null;this.src=PLACEHOLDER_IMG">
          <div class="mos-badge"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4"><rect x="4" y="9" width="16" height="10" rx="4"/><circle cx="9" cy="14" r="1"/><circle cx="15" cy="14" r="1"/><path d="M12 9V5"/><circle cx="12" cy="4" r="1"/></svg> Rẻ hơn ${mosRounded}%</div>
          ${newBadgeHtml}
          ${imageCounterHtml}
          <div class="sc-img-tags">
            <span class="sc-source-tag">${srcName}</span>
            <span class="sc-time-tag"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg> ${timeStr}</span>
            ${dropBadge}
          </div>
        </div>
        <div class="sc-body">
          <div class="sc-title" title="${safeTitle}">${x.title}</div>

          <div class="price-container">
            <div class="price-actual">
              <span class="price-label price-label-actual ${actualClass}">THỰC TẾ</span>
              <div class="price-val ${actualClass}">${escHtml(priceLabel)}</div>
              <div class="price-m2">${x.actual_ppm2 || '-'} tr/m²</div>
            </div>
            <div class="price-fair">
              <span class="price-label price-label-fair">ĐỊNH GIÁ</span>
              <div class="price-val-fair">${fairPrice} tỷ</div>
              <div class="price-m2">${x.fair_ppm2 || '-'} tr/m²</div>
            </div>
            ${dealDelta ? `<div class="price-delta ${dealDelta.className}">${dealDelta.text}</div>` : ''}
          </div>

          <div class="sc-meta-chips">
            <span class="meta-chip"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/></svg>${escHtml(x.ward || 'Chưa rõ')}</span>
            <span class="meta-chip"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/></svg>${escHtml(x.area_m2 || '-')} m²</span>
            <span class="meta-chip"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"/><line x1="4" y1="22" x2="4" y2="15"/></svg>${escHtml(roadStr)}</span>
            <span class="meta-chip"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>${escHtml(legalStr)}</span>
          </div>

          <div class="sc-actions" onclick="event.stopPropagation()">
            <a href="#" onclick="event.preventDefault();const c=this.closest('.scard').dataset;tierCTA(c.id,c.url,'card_signal');" class="btn-zalo"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg> ${(window.USER_TIER === 'vip' || window.USER_TIER === 'admin') ? '⚡ Ráp mối VIP' : '💬 Ráp mối'}</a>
          </div>
        </div>
      </div>
    `;
    }).join(''));
    if (start + SIGNAL_RENDER_CHUNK_SIZE < signals.length) {
      requestAnimationFrame(() => renderChunk(start + SIGNAL_RENDER_CHUNK_SIZE));
    }
  };

  requestAnimationFrame(() => renderChunk(0));
}

function _setupSignalScroll() {
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
