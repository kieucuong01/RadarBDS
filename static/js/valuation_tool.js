(function () {
  'use strict';

  const state = {
    wardsByCity: window.INITIAL_WARDS_BY_CITY || {},
  };

  const money = new Intl.NumberFormat('vi-VN', { maximumFractionDigits: 2 });
  const ppm = new Intl.NumberFormat('vi-VN', { maximumFractionDigits: 1 });

  function $(id) {
    return document.getElementById(id);
  }

  function esc(value) {
    return String(value ?? '').replace(/[&<>"']/g, (ch) => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;',
    }[ch]));
  }

  function setMessage(text) {
    const el = $('formMessage');
    if (el) el.textContent = text || '';
  }

  function initWardPickers() {
    const city = $('cityInput');
    const ward = $('wardInput');
    if (!city || !ward) return;
    const cityNames = Object.keys(state.wardsByCity);
    city.innerHTML = cityNames.map((name) => `<option value="${esc(name)}">${esc(name)}</option>`).join('');

    function renderWards() {
      const wards = state.wardsByCity[city.value] || [];
      ward.innerHTML = wards.map((name) => `<option value="${esc(name)}">${esc(name)}</option>`).join('');
    }

    city.addEventListener('change', renderWards);
    if (cityNames.includes('Thủ Dầu Một')) city.value = 'Thủ Dầu Một';
    renderWards();
  }

  function formPayload(form) {
    const data = new FormData(form);
    const payload = Object.fromEntries(data.entries());
    payload.has_so = Boolean(data.get('has_so'));
    for (const key of ['area_m2', 'frontage_m', 'depth_m', 'tho_cu_m2', 'road_tier']) {
      if (payload[key] !== undefined && payload[key] !== '') payload[key] = Number(payload[key]);
    }
    return payload;
  }

  function renderComparables(rows) {
    const list = $('comparableList');
    if (!list) return;
    if (!rows || !rows.length) {
      list.innerHTML = '<p class="model-note">Chưa có tin so sánh đủ gần để hiển thị.</p>';
      return;
    }
    list.innerHTML = rows.map((row) => `
      <div class="comparable-row">
        <div class="comparable-title">${esc(row.title || `Tin #${row.id}`)}</div>
        <div class="comparable-meta">${money.format(row.price_ty)} tỷ · ${ppm.format(row.price_per_m2)} tr/m² · ${ppm.format(row.area_m2)} m²</div>
      </div>
    `).join('');
  }

  function renderResult(payload) {
    const estimate = payload.estimate;
    $('resultEmpty').hidden = true;
    $('resultContent').hidden = false;
    $('resultWard').textContent = `${estimate.ward} · ${estimate.property_type_label}`;
    $('resultMos').textContent = typeof estimate.mos_pct === 'number'
      ? `MOS ${ppm.format(estimate.mos_pct)}%`
      : 'Giá tham khảo';
    $('fairPrice').textContent = `${money.format(estimate.fair_price_ty)} tỷ`;
    $('fairPpm2').textContent = `${ppm.format(estimate.fair_ppm2)} tr/m²`;
    $('areaMetric').textContent = `${ppm.format(estimate.area_m2)} m²`;
    $('segmentN').textContent = `${estimate.segment_n} tin`;
    $('modelNote').textContent = `${estimate.confidence} · ${estimate.note}`;
    renderComparables(payload.comparables || []);
  }

  async function submitValuation(ev) {
    ev.preventDefault();
    setMessage('');
    const form = ev.currentTarget;
    const button = form.querySelector('button[type="submit"]');
    if (button) button.disabled = true;

    try {
      const res = await fetch('/api/valuation-tool/estimate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(formPayload(form)),
      });
      const data = await res.json();
      if (res.status === 403 && data.error === 'tier_required') {
        if (window.RadarAuth) {
          window.RadarAuth.openAuthModal('Đăng nhập để chạy định giá lô đất.');
        }
        setMessage('Bạn cần đăng nhập để chạy định giá.');
        return;
      }
      if (res.status === 422) {
        setMessage('Thông tin nhập chưa hợp lệ. Kiểm tra diện tích và khu vực.');
        return;
      }
      if (!res.ok || !data.ok) {
        setMessage(data.message || 'Chưa đủ dữ liệu để định giá lô này.');
        return;
      }
      renderResult(data);
    } catch (err) {
      setMessage('Mất kết nối, thử lại sau.');
    } finally {
      if (button) button.disabled = false;
    }
  }

  function init() {
    initWardPickers();
    const form = $('valuationForm');
    if (form) form.addEventListener('submit', submitValuation);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, { once: true });
  } else {
    init();
  }
})();
