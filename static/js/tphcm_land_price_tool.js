(function () {
  const form = document.getElementById('landPriceSearch');
  const query = document.getElementById('landPriceQuery');
  const area = document.getElementById('landPriceArea');
  const suggestionsEl = document.getElementById('keywordSuggestions');
  const rowsEl = document.getElementById('landPriceRows');
  const cardsEl = document.getElementById('landPriceCards');
  const tableEl = document.getElementById('landPriceTable');
  const emptyEl = document.getElementById('landPriceEmpty');
  const errorEl = document.getElementById('landPriceError');
  const statusEl = document.getElementById('landPriceStatus');
  const paginationEl = document.getElementById('landPricePagination');
  const pageStatusEl = document.getElementById('landPricePageStatus');
  const actionsEl = document.getElementById('landPriceActions');
  const sourceCta = document.getElementById('landPriceSourceCta');
  const valuationCta = document.getElementById('landPriceValuationCta');
  const resultTitle = document.getElementById('landPriceResultTitle');
  const searchError = document.getElementById('landPriceSearchError');
  const submitButton = form && form.querySelector('.land-price-submit');
  if (!form || !query || !area || !rowsEl || !cardsEl || !statusEl) return;

  const pageSize = 24;
  let suggestTimer = 0;
  let suggestRequest = 0;
  let activeSuggestionIndex = -1;
  let searchRequest = 0;
  let searchController = null;
  let currentPage = 1;
  let totalPages = 1;

  function track(eventName, params) {
    const safeParams = Object.assign({ tool: 'tphcm_land_price' }, params || {});
    if (typeof window.gtag === 'function') {
      window.gtag('event', eventName, safeParams);
      return;
    }
    window.dataLayer = window.dataLayer || [];
    window.dataLayer.push(Object.assign({ event: eventName }, safeParams));
  }

  function esc(value) {
    return String(value || '').replace(/[&<>"']/g, (ch) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[ch]));
  }

  function rawPrice(value) {
    const n = Number(value);
    return Number.isFinite(n) && n > 0 ? n.toLocaleString('vi-VN') : '-';
  }

  function price(value) {
    const n = Number(value);
    if (!Number.isFinite(n) || n <= 0) return 'Không áp dụng';
    return `${new Intl.NumberFormat('vi-VN', { maximumFractionDigits: 3 }).format(n / 1000)} triệu/m²`;
  }

  function matchLabel(matchType) {
    return {
      exact_street: 'Khớp chính xác tên đường',
      street_prefix: 'Tên đường bắt đầu bằng từ khóa',
      street_contains: 'Tên đường có chứa từ khóa',
      segment_endpoint: 'Khớp mốc từ/đến',
      related: 'Kết quả liên quan',
      area: 'Theo khu vực',
    }[matchType] || 'Kết quả liên quan';
  }

  function setLoading(loading) {
    if (submitButton) submitButton.disabled = loading;
    form.setAttribute('aria-busy', loading ? 'true' : 'false');
  }

  function setResultState(state, message) {
    const hasResults = state === 'results';
    if (tableEl) tableEl.hidden = !hasResults;
    cardsEl.hidden = !hasResults;
    if (paginationEl) paginationEl.hidden = !hasResults;
    if (actionsEl) actionsEl.hidden = !hasResults;
    if (emptyEl) {
      emptyEl.hidden = !['idle', 'empty'].includes(state);
      if (state === 'empty') {
        emptyEl.innerHTML = `<strong>Không tìm thấy kết quả phù hợp</strong><p>${esc(message || 'Hãy thử tên đường ngắn hơn hoặc bỏ bớt bộ lọc phường/xã.')}</p>`;
      }
    }
    if (errorEl) {
      errorEl.hidden = state !== 'error';
      errorEl.textContent = state === 'error' ? message : '';
    }
    if (!hasResults) {
      rowsEl.innerHTML = '';
      cardsEl.innerHTML = '';
    }
  }

  function updateActions(items) {
    if (!valuationCta) return;
    valuationCta.hidden = !items.some((item) => item.appendix === 'Phụ lục III');
  }

  function calculateButton(row, source) {
    return `
      <button
        type="button"
        class="land-price-calculate-button"
        data-calculate-row
        data-calculate-source="${esc(source)}"
        data-row-key="${esc(row.row_key)}"
        data-area="${esc(row.area)}"
        data-street="${esc(row.street)}"
        data-from="${esc(row.from)}"
        data-to="${esc(row.to)}"
      >Tính theo vị trí</button>
    `;
  }

  function render(items) {
    rowsEl.innerHTML = items.map((r) => `
      <tr>
        <td>${esc(r.area)}</td>
        <td>
          <strong>${esc(r.street)}</strong>
          <span class="match-badge">${esc(matchLabel(r.match_type))}</span>
          <small>${esc(r.appendix)} · trang ${esc(r.page)}</small>
        </td>
        <td>${esc(r.from || 'TRỌN ĐƯỜNG')}</td>
        <td>${esc(r.to)}</td>
        <td class="price-cell" title="${rawPrice(r.residential)} nghìn đồng/m²">${price(r.residential)}</td>
        <td class="price-cell" title="${rawPrice(r.commerce_service)} nghìn đồng/m²">${price(r.commerce_service)}</td>
        <td class="price-cell" title="${rawPrice(r.production_business)} nghìn đồng/m²">${price(r.production_business)}</td>
        <td class="calculate-cell">${calculateButton(r, 'desktop')}</td>
      </tr>
    `).join('');

    cardsEl.innerHTML = items.map((r) => `
      <article class="land-price-card">
        <div class="land-price-card-head">
          <div>
            <p>${esc(r.area)}</p>
            <h3>${esc(r.street)}</h3>
          </div>
          <span class="match-badge">${esc(matchLabel(r.match_type))}</span>
        </div>
        <dl class="segment-grid">
          <div><dt>Từ</dt><dd>${esc(r.from || 'TRỌN ĐƯỜNG')}</dd></div>
          <div><dt>Đến</dt><dd>${esc(r.to || '—')}</dd></div>
        </dl>
        <dl class="price-grid">
          <div><dt>Đất ở</dt><dd>${price(r.residential)}</dd></div>
          <div><dt>Thương mại, dịch vụ</dt><dd>${price(r.commerce_service)}</dd></div>
          <div><dt>SXKD phi nông nghiệp</dt><dd>${price(r.production_business)}</dd></div>
        </dl>
        <p class="source-row">${esc(r.appendix)} · trang ${esc(r.page)} · đơn vị gốc ${rawPrice(r.residential)} nghìn đồng/m²</p>
        ${calculateButton(r, 'mobile')}
      </article>
    `).join('');
  }

  function hideSuggestions() {
    if (!suggestionsEl) return;
    suggestionsEl.hidden = true;
    suggestionsEl.innerHTML = '';
    activeSuggestionIndex = -1;
    query.setAttribute('aria-expanded', 'false');
    query.removeAttribute('aria-activedescendant');
  }

  function setActiveSuggestion(index) {
    if (!suggestionsEl) return;
    const options = Array.from(suggestionsEl.querySelectorAll('[role="option"]'));
    if (!options.length) return;
    activeSuggestionIndex = Math.max(0, Math.min(index, options.length - 1));
    options.forEach((option, optionIndex) => {
      const selected = optionIndex === activeSuggestionIndex;
      option.setAttribute('aria-selected', selected ? 'true' : 'false');
    });
    const active = options[activeSuggestionIndex];
    query.setAttribute('aria-activedescendant', active.id);
    active.scrollIntoView({ block: 'nearest' });
  }

  function chooseSuggestion(button) {
    query.value = button.dataset.street || '';
    area.value = button.dataset.area || '';
    hideSuggestions();
    form.requestSubmit();
  }

  function renderSuggestions(items, requestId) {
    if (!suggestionsEl || requestId !== suggestRequest) return;
    const seen = new Set();
    const suggestions = [];
    items.forEach((item) => {
      const key = `${item.street || ''}|${item.area || ''}`;
      if (!item.street || seen.has(key)) return;
      seen.add(key);
      suggestions.push(item);
    });

    if (!suggestions.length) {
      hideSuggestions();
      return;
    }

    suggestionsEl.innerHTML = suggestions.map((item, index) => `
      <button type="button" class="keyword-suggestion" id="landPriceSuggestion${index}" role="option" aria-selected="false" tabindex="-1" data-street="${esc(item.street)}" data-area="${esc(item.area)}">
        <strong>${esc(item.street)}</strong>
        <small>${esc(item.area)}${item.from ? ` · từ ${esc(item.from)}` : ''}</small>
      </button>
    `).join('');
    suggestionsEl.hidden = false;
    query.setAttribute('aria-expanded', 'true');
  }

  async function suggest() {
    const value = query.value.trim();
    if (value.length < 2) {
      hideSuggestions();
      return;
    }
    const requestId = ++suggestRequest;
    const params = new URLSearchParams({
      q: value,
      area: area.value.trim(),
      limit: '8',
    });
    try {
      const res = await fetch(`/api/tphcm-land-prices?${params.toString()}`, { cache: 'no-store' });
      if (!res.ok) return;
      const data = await res.json();
      renderSuggestions(data.items || [], requestId);
    } catch (_) {
      hideSuggestions();
    }
  }

  function updateUrl(page, mode) {
    const params = new URLSearchParams();
    if (query.value.trim()) params.set('q', query.value.trim());
    if (area.value.trim()) params.set('area', area.value.trim());
    if (page > 1) params.set('page', String(page));
    const url = `${window.location.pathname}?${params.toString()}`;
    window.history[mode === 'replace' ? 'replaceState' : 'pushState']({}, '', url);
  }

  function updatePagination(data) {
    currentPage = data.page || 1;
    totalPages = Math.max(1, Math.ceil((data.total || 0) / (data.limit || pageSize)));
    if (!paginationEl || !pageStatusEl) return;
    const prev = paginationEl.querySelector('[data-page-action="prev"]');
    const next = paginationEl.querySelector('[data-page-action="next"]');
    if (prev) prev.disabled = currentPage <= 1;
    if (next) next.disabled = !data.has_more;
    pageStatusEl.textContent = `Trang ${currentPage}/${totalPages}`;
  }

  async function search(options) {
    const settings = Object.assign({ page: 1, historyMode: 'push', focusResult: true }, options);
    const q = query.value.trim();
    const selectedArea = area.value.trim();
    if (!q && !selectedArea) {
      query.setAttribute('aria-invalid', 'true');
      area.setAttribute('aria-invalid', 'true');
      if (searchError) searchError.hidden = false;
      statusEl.textContent = 'Cần nhập tên đường hoặc phường/xã.';
      query.focus();
      return;
    }
    query.removeAttribute('aria-invalid');
    area.removeAttribute('aria-invalid');
    if (searchError) searchError.hidden = true;

    if (searchController) searchController.abort();
    searchController = new AbortController();
    const requestId = ++searchRequest;
    const params = new URLSearchParams({
      q,
      area: selectedArea,
      limit: String(pageSize),
      page: String(settings.page),
    });
    hideSuggestions();
    setLoading(true);
    statusEl.textContent = 'Đang tra cứu...';
    track('land_price_search', {
      page: settings.page,
      has_area: Boolean(selectedArea),
      query_length_bucket: q.length < 5 ? 'short' : q.length < 15 ? 'medium' : 'long',
    });
    try {
      const res = await fetch(`/api/tphcm-land-prices?${params.toString()}`, {
        cache: 'no-store',
        signal: searchController.signal,
      });
      if (!res.ok) throw new Error(`search ${res.status}`);
      const data = await res.json();
      if (requestId !== searchRequest) return;
      const items = data.items || [];
      if (!items.length) {
        setResultState('empty');
        statusEl.textContent = 'Không có kết quả phù hợp.';
        if (settings.historyMode) updateUrl(data.page || 1, settings.historyMode);
        track('land_price_no_result', {
          has_area: Boolean(selectedArea),
          page: data.page || 1,
        });
      } else {
        render(items);
        setResultState('results');
        updateActions(items);
        updatePagination(data);
        const start = ((data.page || 1) - 1) * (data.limit || pageSize) + 1;
        const end = start + items.length - 1;
        statusEl.textContent = `Đang xem ${start}–${end} trong ${data.total} kết quả · giá hiển thị theo triệu đồng/m²`;
        track('land_price_success', {
          result_count: items.length,
          total: data.total,
          page: data.page || 1,
          top_match_type: items[0].match_type || 'related',
          has_binh_duong_result: items.some((item) => item.appendix === 'Phụ lục III'),
        });
        if (settings.historyMode) updateUrl(data.page || 1, settings.historyMode);
        if (settings.focusResult && resultTitle && window.matchMedia('(max-width: 860px)').matches) {
          resultTitle.focus({ preventScroll: true });
          resultTitle.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
      }
    } catch (error) {
      if (error.name === 'AbortError') return;
      if (requestId !== searchRequest) return;
      setResultState('error', 'Không tải được dữ liệu. Vui lòng thử lại.');
      statusEl.textContent = 'Tra cứu thất bại.';
      track('land_price_error', { page: settings.page });
    } finally {
      if (requestId === searchRequest) setLoading(false);
    }
  }

  form.addEventListener('submit', (event) => {
    event.preventDefault();
    search({ page: 1 });
  });

  query.addEventListener('input', () => {
    clearTimeout(suggestTimer);
    hideSuggestions();
    suggestTimer = window.setTimeout(suggest, 180);
  });

  area.addEventListener('input', () => {
    clearTimeout(suggestTimer);
    hideSuggestions();
    suggestTimer = window.setTimeout(suggest, 180);
  });

  query.addEventListener('keydown', (event) => {
    if (!suggestionsEl || suggestionsEl.hidden) return;
    const options = suggestionsEl.querySelectorAll('[role="option"]');
    if (!options.length) return;
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      setActiveSuggestion(activeSuggestionIndex + 1);
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      setActiveSuggestion(activeSuggestionIndex <= 0 ? options.length - 1 : activeSuggestionIndex - 1);
    } else if (event.key === 'Enter' && activeSuggestionIndex >= 0) {
      event.preventDefault();
      chooseSuggestion(options[activeSuggestionIndex]);
    } else if (event.key === 'Escape') {
      event.preventDefault();
      hideSuggestions();
    }
  });

  document.addEventListener('click', (event) => {
    if (form.contains(event.target)) return;
    hideSuggestions();
  });

  if (suggestionsEl) {
    suggestionsEl.addEventListener('click', (event) => {
      const btn = event.target.closest('.keyword-suggestion');
      if (!btn) return;
      chooseSuggestion(btn);
    });
  }

  document.querySelectorAll('.quick-searches button').forEach((btn) => {
    btn.addEventListener('click', () => {
      query.value = btn.dataset.query || '';
      area.value = btn.dataset.area || '';
      hideSuggestions();
      form.requestSubmit();
    });
  });

  if (paginationEl) {
    paginationEl.addEventListener('click', (event) => {
      const button = event.target.closest('[data-page-action]');
      if (!button || button.disabled) return;
      const nextPage = button.dataset.pageAction === 'next' ? currentPage + 1 : currentPage - 1;
      search({ page: nextPage });
    });
  }

  if (sourceCta) {
    sourceCta.addEventListener('click', () => track('land_price_source_open', {
      page: currentPage,
    }));
  }

  if (valuationCta) {
    valuationCta.addEventListener('click', () => track('land_price_valuation_click', {
      page: currentPage,
    }));
  }

  function loadFromUrl() {
    const params = new URLSearchParams(window.location.search);
    query.value = params.get('q') || '';
    area.value = params.get('area') || '';
    const page = Math.max(1, Number(params.get('page')) || 1);
    if (query.value.trim() || area.value.trim()) {
      search({ page, historyMode: '', focusResult: false });
    } else {
      setResultState('idle');
    }
  }

  window.addEventListener('popstate', loadFromUrl);
  loadFromUrl();
})();
