(function (root) {
  'use strict';

  const LAND_TYPE_LABELS = {
    residential: 'Đất ở',
    commerce_service: 'Thương mại, dịch vụ',
    production_business: 'SXKD phi nông nghiệp',
  };
  const BAND_LABELS = {
    front: 'Phần phía trước',
    middle: 'Phần ở giữa',
    rear: 'Phần phía sau',
  };
  const AGRICULTURAL_PRICING_LABELS = {
    normal_table: 'Bảng giá nông nghiệp thông thường',
    article_5_8: 'Khoản 8 Điều 5',
    manual_review: 'Cần đối chiếu thủ công',
  };
  let openHandler = function () {};

  function esc(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, (ch) => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;',
    }[ch]));
  }

  function formatNumber(value, maximumFractionDigits) {
    const number = Number(value);
    if (!Number.isFinite(number)) return '—';
    return new Intl.NumberFormat('vi-VN', {
      maximumFractionDigits: maximumFractionDigits == null ? 2 : maximumFractionDigits,
    }).format(number);
  }

  function formatUnitPrice(value) {
    const number = Number(value);
    if (!Number.isFinite(number) || number <= 0) return 'Không áp dụng';
    return `${formatNumber(number / 1000000, 3)} triệu/m²`;
  }

  function formatMoney(value) {
    const number = Number(value);
    if (!Number.isFinite(number) || number <= 0) return 'Không áp dụng';
    if (number >= 1000000000) {
      return `${formatNumber(number / 1000000000, 3)} tỷ`;
    }
    return `${formatNumber(number / 1000000, 3)} triệu`;
  }

  function formatFactor(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) return '—';
    return formatNumber(number, 4);
  }

  function buildPayload(values) {
    const location = { mode: values.mode || 'standard' };
    if (location.mode === 'standard') {
      location.access = values.access || '';
      if (location.access === 'alley') {
        location.alley_min_width_m = values.alleyWidth;
        location.alley_surface = values.alleySurface;
        location.distance_to_named_road_m = values.roadDistance;
      }
    }
    const payload = {
      row_key: values.rowKey,
      land_area_m2: values.landArea,
      frontage_m: values.frontage,
      depth_m: values.depth,
      location,
    };
    if (!values.mixedMode) return payload;

    payload.parcel_mode = 'mixed';
    payload.residential_area_m2 = values.residentialArea;
    payload.agricultural_area_m2 = values.agriculturalArea;
    payload.residential_geometry = {
      use_custom: Boolean(values.residentialUseCustom),
    };
    if (payload.residential_geometry.use_custom) {
      payload.residential_geometry.frontage_m = values.residentialFrontage;
      payload.residential_geometry.depth_m = values.residentialDepth;
    }
    payload.agricultural = {
      land_type: values.agriculturalType,
      position: values.agriculturalPosition,
      in_residential_area: Boolean(values.inResidentialArea),
      same_parcel_has_house: Boolean(values.sameParcelHasHouse),
    };
    return payload;
  }

  function renderBreakdown(position) {
    const items = (position && Array.isArray(position.breakdown))
      ? position.breakdown
      : [];
    if (!items.length) return '';
    return `
      <div class="calculation-factor-list" aria-label="Các hệ số vị trí">
        ${items.map((item) => `
          <span>${esc(item.label)} <strong>× ${esc(formatFactor(item.factor))}</strong></span>
        `).join('')}
      </div>
    `;
  }

  function renderBands(landType, value) {
    const bands = value && Array.isArray(value.bands) ? value.bands : [];
    if (!bands.length) return '';
    return `
      <div class="calculation-band-section">
        <h5>Phân dải chiều sâu · ${esc(LAND_TYPE_LABELS[landType] || landType)}</h5>
        <div class="calculation-table-wrap">
          <table class="calculation-band-table">
            <thead>
              <tr>
                <th>Phần thửa</th>
                <th>Diện tích</th>
                <th>Hệ số sâu</th>
                <th>Đơn giá áp dụng</th>
                <th>Thành tiền</th>
              </tr>
            </thead>
            <tbody>
              ${bands.map((band) => `
                <tr>
                  <td data-label="Phần thửa">${esc(BAND_LABELS[band.code] || band.code)}</td>
                  <td data-label="Diện tích">${esc(formatNumber(band.area_m2, 2))} m²</td>
                  <td data-label="Hệ số sâu">× ${esc(formatFactor(band.factor))}</td>
                  <td data-label="Đơn giá">${esc(formatUnitPrice(band.unit_price))}</td>
                  <td data-label="Thành tiền">${esc(formatMoney(band.subtotal))}</td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        </div>
      </div>
    `;
  }

  function renderWarnings(warnings) {
    return warnings.map((warning) => `
      <div class="calculator-warning" role="status">${esc(warning.message)}</div>
    `).join('');
  }

  function renderMixedResult(data) {
    const position = data && data.position ? data.position : {};
    const mixed = data && data.mixed_use ? data.mixed_use : {};
    const residential = mixed.residential || {};
    const agricultural = mixed.agricultural || {};
    const warnings = data && Array.isArray(data.warnings) ? data.warnings : [];
    const formula = Array.isArray(agricultural.formula) ? agricultural.formula : [];
    const totalText = mixed.total_value == null
      ? 'Chưa thể tính tổng'
      : formatMoney(mixed.total_value);
    const agriculturalValue = agricultural.total_value == null
      ? 'Cần đối chiếu'
      : formatMoney(agricultural.total_value);
    const romanZone = ['', 'I', 'II', 'III', 'IV'][Number(agricultural.zone)]
      || formatNumber(agricultural.zone, 0);
    const pricingLabel = AGRICULTURAL_PRICING_LABELS[agricultural.pricing_mode]
      || agricultural.pricing_mode
      || 'Bảng giá nông nghiệp';
    const pricingNotes = [];
    if (agricultural.special_unit_price != null) {
      pricingNotes.push(`Giá theo khoản 8: ${formatUnitPrice(agricultural.special_unit_price)}`);
    }
    if (agricultural.floor_applied) {
      pricingNotes.push('Đã áp giá sàn bằng bảng nông nghiệp thông thường');
    }
    if (agricultural.cap_applied) {
      pricingNotes.push(`Đã áp trần giá đất ở: ${formatUnitPrice(agricultural.residential_cap_unit_price)}`);
    }

    return `
      <div class="calculation-result-head">
        <div>
          <p class="section-label">Kết quả thửa có nhiều loại đất</p>
          <h4>Giá theo bảng Nhà nước</h4>
          <p>Diện tích toàn thửa: <strong>${esc(formatNumber(mixed.total_area_m2, 2))} m²</strong>
            · Phần đất ở: <strong>${esc(position.label || 'Vị trí đã chọn')}</strong>
          </p>
        </div>
      </div>
      ${renderBreakdown(position)}
      <div class="calculation-summary-grid">
        <article class="calculation-summary-card">
          <p>Phần đất ở · ${esc(formatNumber(residential.area_m2, 2))} m²</p>
          <strong>${esc(formatMoney(residential.total_value))}</strong>
          <span>${esc(formatUnitPrice(residential.average_unit_price))} bình quân</span>
          <small>Giá vị trí 1: ${esc(formatUnitPrice(residential.base_unit_price))}</small>
        </article>
        <article class="calculation-summary-card">
          <p>${esc(agricultural.land_type_label || 'Phần đất nông nghiệp')} · ${esc(formatNumber(agricultural.area_m2, 2))} m²</p>
          <strong>${esc(agriculturalValue)}</strong>
          <span>${esc(formatUnitPrice(agricultural.unit_price))}</span>
          <small>Vùng ${esc(romanZone)} · Vị trí ${esc(formatNumber(agricultural.position, 0))}</small>
        </article>
        <article class="calculation-summary-card is-total">
          <p>Tổng giá trị theo bảng Nhà nước</p>
          <strong>${esc(totalText)}</strong>
          <span>${mixed.total_value == null ? 'Thiếu đơn giá cần đối chiếu thủ công' : 'Đất ở + đất nông nghiệp'}</span>
          <small>Không phải giá giao dịch thị trường</small>
        </article>
      </div>
      <div class="mixed-result-context" aria-label="Căn cứ phần đất nông nghiệp">
        <span>Vùng ${esc(romanZone)}</span>
        <span>Vị trí ${esc(formatNumber(agricultural.position, 0))}</span>
        <span>${esc(pricingLabel)}</span>
        ${pricingNotes.map((note) => `<span>${esc(note)}</span>`).join('')}
      </div>
      ${renderWarnings(warnings)}
      ${formula.length ? `
        <div class="agricultural-formula">
          <h5>Cách tính phần đất nông nghiệp</h5>
          <ul>${formula.map((step) => `<li>${esc(step)}</li>`).join('')}</ul>
        </div>
      ` : ''}
      ${renderBands('residential', residential)}
      <p class="calculation-disclaimer">
        Kết quả là phép tính tham khảo từ bảng giá đất có hiệu lực 01/01/2026.
        Hãy đối chiếu mục đích sử dụng, vị trí và hình thể trên hồ sơ địa chính.
      </p>
    `;
  }

  function renderResult(data) {
    if (data && data.parcel_mode === 'mixed') {
      return renderMixedResult(data);
    }
    const position = data && data.position ? data.position : {};
    const geometry = data && data.geometry ? data.geometry : {};
    const values = data && data.values ? data.values : {};
    const warnings = data && Array.isArray(data.warnings) ? data.warnings : [];
    const summaries = Object.keys(LAND_TYPE_LABELS).map((landType) => {
      const value = values[landType] || {};
      return `
        <article class="calculation-summary-card">
          <p>${esc(LAND_TYPE_LABELS[landType])}</p>
          <strong>${esc(formatMoney(value.total_value))}</strong>
          <span>${esc(formatUnitPrice(value.average_unit_price))} bình quân</span>
          <small>Giá vị trí 1: ${esc(formatUnitPrice(value.base_unit_price))}</small>
        </article>
      `;
    }).join('');
    const bands = Object.keys(LAND_TYPE_LABELS)
      .map((landType) => renderBands(landType, values[landType]))
      .join('');

    return `
      <div class="calculation-result-head">
        <div>
          <p class="section-label">Kết quả theo bảng giá Nhà nước</p>
          <h4>${esc(position.label || 'Vị trí đã chọn')}</h4>
          <p>Hệ số vị trí tổng: <strong>${esc(formatFactor(position.factor))}</strong>
            · Diện tích tính: <strong>${esc(formatNumber(geometry.legal_area_m2, 2))} m²</strong>
          </p>
        </div>
      </div>
      ${renderBreakdown(position)}
      <div class="calculation-summary-grid">${summaries}</div>
      ${renderWarnings(warnings)}
      ${bands}
      <p class="calculation-disclaimer">
        Kết quả là phép tính tham khảo từ bảng giá đất có hiệu lực 01/01/2026,
        không phải giá giao dịch thị trường.
      </p>
    `;
  }

  function openForRow(row) {
    return openHandler(row || {});
  }

  root.RadarLandPriceCalculator = {
    buildPayload,
    renderResult,
    openForRow,
  };

  if (typeof document === 'undefined') return;

  function init() {
    const panel = document.getElementById('landPriceCalculator');
    const form = document.getElementById('landPriceCalculatorForm');
    const rowKey = document.getElementById('landPriceCalculatorRowKey');
    const road = document.getElementById('landPriceCalculatorRoad');
    const title = document.getElementById('landPriceCalculatorTitle');
    const closeButton = document.getElementById('landPriceCalculatorClose');
    const alleyFields = document.getElementById('landPriceAlleyFields');
    const standardLocation = document.getElementById('landPriceStandardLocation');
    const mixedMode = document.getElementById('landPriceMixedMode');
    const mixedFields = document.getElementById('landPriceMixedFields');
    const agriculturalType = document.getElementById('landPriceAgriculturalType');
    const agriculturalSpecialContext = document.getElementById('landPriceAgriculturalSpecialContext');
    const wardContextNote = document.getElementById('landPriceWardContextNote');
    const residentialCustomGeometry = document.getElementById('landPriceResidentialCustomGeometry');
    const residentialGeometryFields = document.getElementById('landPriceResidentialGeometryFields');
    const result = document.getElementById('landPriceCalculatorResult');
    const error = document.getElementById('landPriceCalculatorError');
    const advanced = panel && panel.querySelector('.land-price-advanced');
    const submitButton = form && form.querySelector('.calculator-submit');
    if (!panel || !form || !rowKey || !road || !result || !error) return;
    let selectedArea = '';

    function track(eventName, params) {
      const safeParams = Object.assign({ tool: 'tphcm_land_price' }, params || {});
      if (typeof root.gtag === 'function') {
        root.gtag('event', eventName, safeParams);
        return;
      }
      root.dataLayer = root.dataLayer || [];
      root.dataLayer.push(Object.assign({ event: eventName }, safeParams));
    }

    function selectedValue(name) {
      const selected = form.querySelector(`input[name="${name}"]:checked`);
      return selected ? selected.value : '';
    }

    function clearErrors() {
      error.hidden = true;
      error.textContent = '';
      form.querySelectorAll('[data-calculator-error]').forEach((node) => {
        node.hidden = true;
        node.textContent = '';
      });
      form.querySelectorAll('[aria-invalid="true"]').forEach((node) => {
        node.removeAttribute('aria-invalid');
      });
    }

    function inputForError(field) {
      const names = {
        land_area_m2: 'land_area_m2',
        frontage_m: 'frontage_m',
        depth_m: 'depth_m',
        parcel_mode: 'parcel_mode',
        residential_area_m2: 'residential_area_m2',
        agricultural_area_m2: 'agricultural_area_m2',
        residential_geometry: 'residential_use_custom',
        'residential_geometry.use_custom': 'residential_use_custom',
        'residential_geometry.frontage_m': 'residential_frontage_m',
        'residential_geometry.depth_m': 'residential_depth_m',
        agricultural: 'agricultural_land_type',
        'agricultural.zone': 'agricultural_land_type',
        'agricultural.land_type': 'agricultural_land_type',
        'agricultural.position': 'agricultural_position',
        'agricultural.in_residential_area': 'in_residential_area',
        'agricultural.same_parcel_has_house': 'same_parcel_has_house',
        'location.access': 'access',
        'location.mode': 'mode',
        'location.alley_min_width_m': 'alley_min_width_m',
        'location.alley_surface': 'alley_surface',
        'location.distance_to_named_road_m': 'distance_to_named_road_m',
      };
      return names[field] ? form.querySelector(`[name="${names[field]}"]`) : null;
    }

    function showFieldErrors(fieldErrors) {
      let firstInput = null;
      Object.keys(fieldErrors || {}).forEach((field) => {
        const message = String(fieldErrors[field] || 'Giá trị chưa hợp lệ.');
        const node = Array.from(form.querySelectorAll('[data-calculator-error]'))
          .find((item) => item.dataset.calculatorError === field);
        const input = inputForError(field);
        if (node) {
          node.textContent = message;
          node.hidden = false;
        }
        if (input) {
          input.setAttribute('aria-invalid', 'true');
          if (!firstInput) firstInput = input;
        }
      });
      if (firstInput) firstInput.focus();
    }

    function validateAreaSplit(options) {
      if (!mixedMode || !mixedMode.checked) return true;
      const totalInput = form.elements.land_area_m2;
      const residentialInput = form.elements.residential_area_m2;
      const agriculturalInput = form.elements.agricultural_area_m2;
      const total = Number(totalInput && totalInput.value);
      const residentialArea = Number(residentialInput && residentialInput.value);
      const agriculturalArea = Number(agriculturalInput && agriculturalInput.value);
      if (
        !Number.isFinite(total)
        || !Number.isFinite(residentialArea)
        || !Number.isFinite(agriculturalArea)
        || total <= 0
        || residentialArea <= 0
        || agriculturalArea <= 0
      ) {
        return true;
      }
      const errorNode = form.querySelector(
        '[data-calculator-error="agricultural_area_m2"]'
      );
      if (Math.abs(total - residentialArea - agriculturalArea) <= 0.0100001) {
        if (errorNode) {
          errorNode.hidden = true;
          errorNode.textContent = '';
        }
        agriculturalInput.removeAttribute('aria-invalid');
        return true;
      }
      if (errorNode) {
        errorNode.textContent = 'Tổng đất ở và đất nông nghiệp phải khớp diện tích toàn thửa (sai số tối đa 0,01 m²).';
        errorNode.hidden = false;
      }
      agriculturalInput.setAttribute('aria-invalid', 'true');
      if (options && options.focus) agriculturalInput.focus();
      return false;
    }

    function setLoading(loading) {
      form.setAttribute('aria-busy', loading ? 'true' : 'false');
      if (submitButton) submitButton.disabled = loading;
      form.querySelectorAll('input, select').forEach((input) => {
        if (input.name !== 'access' && input.name !== 'mode') return;
        input.dataset.loadingDisabled = loading ? 'true' : '';
      });
    }

    function updateConditionalFields() {
      const mode = selectedValue('mode') || 'standard';
      const access = selectedValue('access') || 'frontage';
      const standard = mode === 'standard';
      if (standardLocation) standardLocation.classList.toggle('is-disabled', !standard);
      form.querySelectorAll('input[name="access"]').forEach((input) => {
        input.disabled = !standard;
      });
      const showAlley = standard && access === 'alley';
      alleyFields.hidden = !showAlley;
      alleyFields.querySelectorAll('input, select').forEach((input) => {
        input.disabled = !showAlley;
      });

      const isMixed = Boolean(mixedMode && mixedMode.checked);
      if (mixedMode) mixedMode.setAttribute('aria-expanded', isMixed ? 'true' : 'false');
      if (mixedFields) {
        mixedFields.hidden = !isMixed;
        mixedFields.querySelectorAll('input, select').forEach((input) => {
          input.disabled = !isMixed;
        });
      }

      const useCustom = isMixed && Boolean(
        residentialCustomGeometry && residentialCustomGeometry.checked
      );
      if (residentialCustomGeometry) {
        residentialCustomGeometry.disabled = !isMixed;
        residentialCustomGeometry.setAttribute(
          'aria-expanded',
          useCustom ? 'true' : 'false'
        );
      }
      if (residentialGeometryFields) {
        residentialGeometryFields.hidden = !useCustom;
        residentialGeometryFields.querySelectorAll('input').forEach((input) => {
          input.disabled = !useCustom;
        });
      }

      const isWard = selectedArea.trim().toLocaleLowerCase('vi-VN').startsWith('phường ');
      if (agriculturalSpecialContext) {
        const contextChoices = agriculturalSpecialContext.querySelector('.calculator-choice-grid');
        if (contextChoices) contextChoices.hidden = !isMixed || isWard;
        agriculturalSpecialContext.querySelectorAll('input').forEach((input) => {
          input.disabled = !isMixed || isWard;
        });
      }
      if (wardContextNote) {
        wardContextNote.textContent = isWard
          ? 'Dòng giá thuộc phường: backend tự áp dụng điều kiện trong địa giới hành chính phường.'
          : 'Chỉ xác nhận khi hồ sơ tại xã/đặc khu thể hiện đất trong khu dân cư hoặc cùng thửa có nhà ở.';
      }
    }

    function valuesFromForm() {
      return {
        rowKey: rowKey.value,
        landArea: form.elements.land_area_m2.value,
        frontage: form.elements.frontage_m.value,
        depth: form.elements.depth_m.value,
        mode: selectedValue('mode'),
        access: selectedValue('access'),
        alleyWidth: form.elements.alley_min_width_m.value,
        alleySurface: form.elements.alley_surface.value,
        roadDistance: form.elements.distance_to_named_road_m.value,
        mixedMode: Boolean(mixedMode && mixedMode.checked),
        residentialArea: form.elements.residential_area_m2
          ? form.elements.residential_area_m2.value
          : '',
        agriculturalArea: form.elements.agricultural_area_m2
          ? form.elements.agricultural_area_m2.value
          : '',
        agriculturalType: form.elements.agricultural_land_type
          ? form.elements.agricultural_land_type.value
          : '',
        agriculturalPosition: selectedValue('agricultural_position'),
        inResidentialArea: Boolean(
          form.elements.in_residential_area
          && form.elements.in_residential_area.checked
        ),
        sameParcelHasHouse: Boolean(
          form.elements.same_parcel_has_house
          && form.elements.same_parcel_has_house.checked
        ),
        residentialUseCustom: Boolean(
          residentialCustomGeometry && residentialCustomGeometry.checked
        ),
        residentialFrontage: form.elements.residential_frontage_m
          ? form.elements.residential_frontage_m.value
          : '',
        residentialDepth: form.elements.residential_depth_m
          ? form.elements.residential_depth_m.value
          : '',
      };
    }

    openHandler = function (selectedRow) {
      rowKey.value = selectedRow.rowKey || '';
      selectedArea = selectedRow.area || '';
      const segmentStart = selectedRow.from || 'TRỌN ĐƯỜNG';
      const segmentEnd = selectedRow.to ? ` → ${selectedRow.to}` : '';
      road.textContent = `${selectedRow.street || 'Tuyến đã chọn'} · ${selectedRow.area || ''} · ${segmentStart}${segmentEnd}`;
      clearErrors();
      result.hidden = true;
      result.innerHTML = '';
      panel.hidden = false;
      updateConditionalFields();
      track('land_price_calculator_open', {
        source: selectedRow.source === 'mobile' ? 'mobile_card' : 'desktop_table',
      });
      if (title) {
        title.focus({ preventScroll: true });
        title.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    };

    document.addEventListener('click', (event) => {
      const button = event.target.closest('[data-calculate-row]');
      if (!button) return;
      event.preventDefault();
      openForRow({
        rowKey: button.dataset.rowKey,
        area: button.dataset.area,
        street: button.dataset.street,
        from: button.dataset.from,
        to: button.dataset.to,
        source: button.dataset.calculateSource,
      });
    });

    form.addEventListener('change', (event) => {
      if (
        event.target.name === 'access'
        || event.target.name === 'mode'
        || event.target.name === 'parcel_mode'
        || event.target.name === 'residential_use_custom'
      ) {
        updateConditionalFields();
      }
      if (event.target.name === 'parcel_mode') {
        track('land_price_mixed_mode_toggle', {
          enabled: event.target.checked ? 'true' : 'false',
        });
      }
    });

    ['land_area_m2', 'residential_area_m2', 'agricultural_area_m2'].forEach((name) => {
      const input = form.elements[name];
      if (input) input.addEventListener('blur', () => validateAreaSplit());
    });

    if (advanced) {
      advanced.addEventListener('toggle', () => {
        if (advanced.open) track('land_price_calculator_advanced_open');
      });
    }

    if (closeButton) {
      closeButton.addEventListener('click', () => {
        panel.hidden = true;
        clearErrors();
        result.hidden = true;
        result.innerHTML = '';
      });
    }

    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      clearErrors();
      result.hidden = true;
      const values = valuesFromForm();
      if (!validateAreaSplit({ focus: true })) return;
      const payload = buildPayload(values);
      const mode = values.mode || 'standard';
      const access = mode === 'standard' ? (values.access || 'unknown') : 'special';
      const parcelMode = values.mixedMode ? 'mixed' : 'single';
      setLoading(true);
      track('land_price_calculator_start', {
        mode,
        access,
        parcel_mode: parcelMode,
      });
      try {
        const response = await fetch('/api/tphcm-land-prices/calculate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
          if (data.field_errors) showFieldErrors(data.field_errors);
          throw new Error(data.error || `calculate ${response.status}`);
        }
        result.innerHTML = renderResult(data);
        result.hidden = false;
        track('land_price_calculator_success', {
          mode,
          access,
          position: data.position && data.position.position != null
            ? String(data.position.position)
            : 'special',
          has_warning: Boolean(data.warnings && data.warnings.length),
          parcel_mode: parcelMode,
          agricultural_type: values.mixedMode
            ? values.agriculturalType
            : 'not_applicable',
          agricultural_zone: values.mixedMode
            && data.mixed_use
            && data.mixed_use.agricultural
            ? String(data.mixed_use.agricultural.zone)
            : 'not_applicable',
          agricultural_position: values.mixedMode
            ? String(values.agriculturalPosition)
            : 'not_applicable',
          pricing_mode: values.mixedMode
            && data.mixed_use
            && data.mixed_use.agricultural
            ? data.mixed_use.agricultural.pricing_mode
            : 'not_applicable',
        });
        if (root.matchMedia && root.matchMedia('(max-width: 860px)').matches) {
          result.setAttribute('tabindex', '-1');
          result.focus({ preventScroll: true });
          result.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
      } catch (requestError) {
        error.textContent = requestError.message === 'validation_error'
          ? 'Vui lòng kiểm tra các trường được đánh dấu.'
          : 'Không thể tính giá lúc này. Vui lòng thử lại.';
        error.hidden = false;
        track('land_price_calculator_error', {
          mode,
          access,
          parcel_mode: parcelMode,
          error_type: requestError.message === 'validation_error' ? 'validation' : 'request',
        });
      } finally {
        setLoading(false);
        updateConditionalFields();
      }
    });

    updateConditionalFields();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})(window);
