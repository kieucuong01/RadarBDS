(function () {
  'use strict';

  const DEFAULT_CITY = 'THỦ DẦU MỘT';
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

  function track(eventName, params) {
    const safeParams = Object.assign({ event_category: 'valuation_tool' }, params || {});
    if (typeof window.gtag === 'function') {
      window.gtag('event', eventName, safeParams);
      return;
    }
    window.dataLayer = window.dataLayer || [];
    window.dataLayer.push(Object.assign({ event: eventName }, safeParams));
  }

  function setMessage(text) {
    const el = $('formMessage');
    if (el) el.textContent = text || '';
  }

  function clearFieldErrors() {
    document.querySelectorAll('[data-error-for]').forEach((el) => {
      el.textContent = '';
    });
    document.querySelectorAll('[aria-invalid="true"]').forEach((el) => {
      el.removeAttribute('aria-invalid');
    });
  }

  function errorFieldName(code) {
    const exact = {
      city_invalid: 'city',
      ward_required: 'ward',
      ward_invalid: 'ward',
      property_type_invalid: 'property_type',
      area_m2_invalid: 'area_m2',
      price_ty_invalid: 'price_ty',
      frontage_m_invalid: 'frontage_m',
      depth_m_invalid: 'depth_m',
      road_tier_invalid: 'road_tier',
    };
    return exact[code] || '';
  }

  function errorCopy(code) {
    const messages = {
      city_invalid: 'Công cụ hiện chỉ hỗ trợ Thủ Dầu Một và Bến Cát.',
      ward_required: 'Vui lòng chọn phường.',
      ward_invalid: 'Phường không thuộc khu vực đã chọn.',
      property_type_invalid: 'Loại hình chưa hợp lệ.',
      area_m2_invalid: 'Diện tích phải lớn hơn 0 m².',
      price_ty_invalid: 'Giá đang chào phải lớn hơn 0.',
      frontage_m_invalid: 'Chiều ngang phải lớn hơn 0.',
      depth_m_invalid: 'Chiều dài phải lớn hơn 0.',
      road_tier_invalid: 'Loại đường chưa hợp lệ.',
    };
    return messages[code] || 'Thông tin nhập chưa hợp lệ.';
  }

  function showFieldError(code) {
    const fieldName = errorFieldName(code);
    const copy = errorCopy(code);
    if (!fieldName) {
      setMessage(copy);
      return;
    }
    const input = document.querySelector(`[name="${fieldName}"]`);
    const error = document.querySelector(`[data-error-for="${fieldName}"]`);
    if (input) {
      input.setAttribute('aria-invalid', 'true');
      input.focus({ preventScroll: true });
      input.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
    if (error) error.textContent = copy;
    setMessage(copy);
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
    if (cityNames.includes(DEFAULT_CITY)) city.value = DEFAULT_CITY;
    renderWards();
  }

  function formPayload(form) {
    const data = new FormData(form);
    const payload = Object.fromEntries(data.entries());
    payload.has_so = Boolean(data.get('has_so'));
    for (const key of ['area_m2', 'frontage_m', 'depth_m', 'price_ty', 'road_tier']) {
      if (payload[key] !== undefined && payload[key] !== '') payload[key] = Number(payload[key]);
    }
    return payload;
  }

  function setLoading(isLoading) {
    const button = document.querySelector('#valuationForm button[type="submit"]');
    if (!button) return;
    button.disabled = isLoading;
    button.setAttribute('aria-busy', String(isLoading));
    const label = button.querySelector('.submit-label');
    const loading = button.querySelector('.submit-loading');
    if (label) label.hidden = isLoading;
    if (loading) loading.hidden = !isLoading;
  }

  function renderComparables(rows) {
    const list = $('comparableList');
    const section = $('comparablesSection');
    if (!list || !section) return;
    if (
      !Array.isArray(rows)
      || !rows.length
      || !window.RadarValuationComparableCard
    ) {
      list.innerHTML = '';
      section.hidden = true;
      return;
    }
    list.innerHTML = window.RadarValuationComparableCard.renderGrid(rows);
    section.hidden = !list.querySelector('.valuation-comparable-card');
  }

  function formatDataDate(value) {
    if (!value) return 'chưa xác định';
    const parsed = new Date(`${value}T00:00:00`);
    if (Number.isNaN(parsed.getTime())) return value;
    return new Intl.DateTimeFormat('vi-VN').format(parsed);
  }

  function renderResult(payload) {
    const estimate = payload.estimate;
    $('resultEmpty').hidden = true;
    $('resultContent').hidden = false;
    $('resultWard').textContent = `${estimate.ward} · ${estimate.property_type_label}`;
    $('resultMos').textContent = typeof estimate.mos_pct === 'number'
      ? `${estimate.price_position_label} · ${ppm.format(Math.abs(estimate.mos_pct))}%`
      : 'Giá tham khảo';
    $('fairPrice').textContent = `${money.format(estimate.fair_price_ty)} tỷ`;
    $('fairPpm2').textContent = `${ppm.format(estimate.fair_ppm2)} tr/m²`;
    $('areaMetric').textContent = `${ppm.format(estimate.area_m2)} m²`;
    $('basisCount').textContent = `${estimate.basis_count} mẫu hợp lệ`;
    $('modelNote').textContent = `${estimate.confidence_label} · Dữ liệu cập nhật đến ${formatDataDate(estimate.data_as_of)}. Đây là giá tham khảo, không thay thế thẩm định thực tế.`;

    renderComparables(payload.comparables || []);

    const dashboard = $('dashboardCta');
    if (dashboard) dashboard.href = payload.dashboard_url || '/';
    if ($('dashboardWard')) $('dashboardWard').textContent = estimate.ward;

    const result = $('resultContent');
    if (result) {
      result.focus({ preventScroll: true });
      if (window.matchMedia('(max-width: 700px)').matches) {
        result.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    }
  }

  async function submitValuation(ev) {
    ev.preventDefault();
    setMessage('');
    clearFieldErrors();
    const form = ev.currentTarget;
    const payload = formPayload(form);
    setLoading(true);
    track('valuation_start', {
      city: payload.city,
      property_type: payload.property_type,
      has_asking_price: Boolean(payload.price_ty),
    });

    try {
      const res = await fetch('/api/valuation-tool/estimate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (res.status === 422) {
        showFieldError(data.field);
        track('valuation_error', {
          error_type: 'validation_error',
          field: errorFieldName(data.field) || 'unknown',
        });
        return;
      }
      if (!res.ok || !data.ok) {
        setMessage(data.message || 'Chưa đủ dữ liệu để định giá lô này.');
        track('valuation_error', { error_type: data.error || `http_${res.status}` });
        return;
      }
      renderResult(data);
      track('valuation_success', {
        city: payload.city,
        property_type: payload.property_type,
        confidence: data.estimate.confidence,
        has_asking_price: Boolean(payload.price_ty),
      });
    } catch (err) {
      setMessage('Mất kết nối, vui lòng thử lại sau.');
      track('valuation_error', { error_type: 'network_error' });
    } finally {
      setLoading(false);
    }
  }

  function init() {
    initWardPickers();
    const form = $('valuationForm');
    if (form) form.addEventListener('submit', submitValuation);
    const comparables = $('comparableList');
    if (comparables) {
      comparables.addEventListener('click', (event) => {
        const card = event.target.closest('.valuation-comparable-card');
        if (!card) return;
        const position = Number(card.dataset.comparablePosition);
        track('valuation_comparable_click', {
          position: Number.isInteger(position) ? position : 0,
          property_type: card.dataset.propertyType || 'unknown',
          source: 'valuation_result',
        });
      });
    }
    const dashboard = $('dashboardCta');
    if (dashboard) {
      dashboard.addEventListener('click', () => track('valuation_dashboard_click', { source: 'result' }));
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, { once: true });
  } else {
    init();
  }
})();
