(function () {
  const form = document.getElementById('landPriceSearch');
  const query = document.getElementById('landPriceQuery');
  const area = document.getElementById('landPriceArea');
  const suggestionsEl = document.getElementById('keywordSuggestions');
  const rowsEl = document.getElementById('landPriceRows');
  const statusEl = document.getElementById('landPriceStatus');
  if (!form || !query || !area || !rowsEl || !statusEl) return;
  let suggestTimer = 0;
  let suggestRequest = 0;

  function esc(value) {
    return String(value || '').replace(/[&<>"']/g, (ch) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[ch]));
  }

  function price(value) {
    const n = Number(value);
    return Number.isFinite(n) && n > 0 ? n.toLocaleString('vi-VN') : '-';
  }

  function render(items) {
    if (!items.length) {
      rowsEl.innerHTML = '<tr class="empty-row"><td colspan="7">Không tìm thấy dòng phù hợp. Hãy thử tên đường không dấu hoặc chọn phường/xã.</td></tr>';
      return;
    }
    rowsEl.innerHTML = items.map((r) => `
      <tr>
        <td>${esc(r.area)}</td>
        <td><strong>${esc(r.street)}</strong><br><small>${esc(r.appendix)} · trang ${esc(r.page)}</small></td>
        <td>${esc(r.from || 'TRỌN ĐƯỜNG')}</td>
        <td>${esc(r.to)}</td>
        <td class="price-cell">${price(r.residential)}</td>
        <td class="price-cell">${price(r.commerce_service)}</td>
        <td class="price-cell">${price(r.production_business)}</td>
      </tr>
    `).join('');
  }

  function hideSuggestions() {
    if (!suggestionsEl) return;
    suggestionsEl.hidden = true;
    suggestionsEl.innerHTML = '';
    query.setAttribute('aria-expanded', 'false');
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

    suggestionsEl.innerHTML = suggestions.map((item) => `
      <button type="button" class="keyword-suggestion" data-street="${esc(item.street)}" data-area="${esc(item.area)}">
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

  async function search() {
    const params = new URLSearchParams({
      q: query.value.trim(),
      area: area.value.trim(),
      limit: '80',
    });
    hideSuggestions();
    statusEl.textContent = 'Đang tra cứu...';
    const res = await fetch(`/api/tphcm-land-prices?${params.toString()}`, { cache: 'no-store' });
    if (!res.ok) throw new Error(`search ${res.status}`);
    const data = await res.json();
    render(data.items || []);
    statusEl.textContent = `${(data.items || []).length} kết quả đầu tiên · ${data.unit || '1.000 đồng/m²'}`;
  }

  form.addEventListener('submit', (event) => {
    event.preventDefault();
    search().catch(() => {
      statusEl.textContent = 'Không tải được dữ liệu. Vui lòng thử lại.';
    });
  });

  query.addEventListener('input', () => {
    clearTimeout(suggestTimer);
    suggestTimer = window.setTimeout(suggest, 180);
  });

  area.addEventListener('input', () => {
    clearTimeout(suggestTimer);
    suggestTimer = window.setTimeout(suggest, 180);
  });

  document.addEventListener('click', (event) => {
    if (form.contains(event.target)) return;
    hideSuggestions();
  });

  if (suggestionsEl) {
    suggestionsEl.addEventListener('click', (event) => {
      const btn = event.target.closest('.keyword-suggestion');
      if (!btn) return;
      query.value = btn.dataset.street || '';
      area.value = btn.dataset.area || '';
      hideSuggestions();
      form.requestSubmit();
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

  render([]);
})();
