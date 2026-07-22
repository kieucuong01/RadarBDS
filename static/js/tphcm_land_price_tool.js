(function () {
  const form = document.getElementById('landPriceSearch');
  const query = document.getElementById('landPriceQuery');
  const area = document.getElementById('landPriceArea');
  const rowsEl = document.getElementById('landPriceRows');
  const statusEl = document.getElementById('landPriceStatus');
  if (!form || !query || !area || !rowsEl || !statusEl) return;

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

  async function search() {
    const params = new URLSearchParams({
      q: query.value.trim(),
      area: area.value,
      limit: '80',
    });
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

  document.querySelectorAll('.quick-searches button').forEach((btn) => {
    btn.addEventListener('click', () => {
      query.value = btn.dataset.query || '';
      area.value = btn.dataset.area || '';
      form.requestSubmit();
    });
  });

  render([]);
})();
