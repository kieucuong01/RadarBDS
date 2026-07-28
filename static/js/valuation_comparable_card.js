(function () {
  'use strict';

  const PROPERTY_LABELS = {
    dat_nen: 'Đất nền',
    nha_rieng: 'Nhà riêng',
    dat_vuon: 'Đất vườn',
  };

  const ROAD_LABELS = {
    1: 'Mặt tiền',
    2: 'Đường nhựa',
    3: 'Hẻm xe hơi',
    4: 'Hẻm xe máy',
    5: 'Hẻm xe máy',
  };

  const ICONS = {
    pin: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/></svg>',
    area: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/></svg>',
    road: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"/><line x1="4" y1="22" x2="4" y2="15"/></svg>',
    street: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 3v18M18 3v18M6 8h18M0 16h18"/></svg>',
    property: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 7h18M7 3v18M17 3v18M3 17h18"/></svg>',
    land: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 18h16M7 18 12 4l5 14M9 13h6"/></svg>',
    legal: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M7 3h10v18H7zM9 7h6M9 11h6"/></svg>',
  };

  function esc(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function finiteNumber(value) {
    const number = Number(value);
    return Number.isFinite(number) ? number : null;
  }

  function positiveNumber(value) {
    const number = finiteNumber(value);
    return number !== null && number > 0 ? number : null;
  }

  function formatNumber(value, digits = 1) {
    const number = positiveNumber(value);
    if (number === null) return '';
    return new Intl.NumberFormat('vi-VN', {
      maximumFractionDigits: digits,
    }).format(number);
  }

  function priceLabel(row) {
    if (row.price_label) return String(row.price_label);
    const price = positiveNumber(row.price_ty);
    return price === null ? '-' : `${formatNumber(price, 2)} tỷ`;
  }

  function fairTotal(row) {
    const fairPpm2 = positiveNumber(row.fair_ppm2_display || row.fair_ppm2);
    const area = positiveNumber(row.area_m2);
    if (fairPpm2 === null || area === null) return '-';
    return `${formatNumber(fairPpm2 * area / 1000, 2)} tỷ`;
  }

  function timeLabel(daysAgo) {
    const days = finiteNumber(daysAgo);
    if (days === null || days < 0) return 'Chưa rõ ngày';
    if (days === 0) return 'hôm nay';
    return `${Math.round(days)} ngày trước`;
  }

  function areaLabel(row) {
    const area = formatNumber(row.area_m2);
    const frontage = formatNumber(row.frontage_m);
    const depth = formatNumber(row.depth_m);
    if (frontage && depth && area) return `${frontage}x${depth} (${area}m²)`;
    return area ? `${area}m²` : '';
  }

  function propertyLabel(row) {
    return row.prop_type_label || PROPERTY_LABELS[row.prop_type] || row.prop_type || '';
  }

  function roadLabel(row) {
    return row.road_label || ROAD_LABELS[Number(row.road_tier)] || row.road_type || 'Chưa rõ';
  }

  function thoCuLabel(row) {
    if (row.tho_cu_label) return row.tho_cu_label;
    const value = formatNumber(row.tho_cu_m2);
    return value ? `TC ${value}m²` : '';
  }

  function metaChip(icon, label, extraClass) {
    const text = String(label || '').trim();
    if (!text || text === '-' || text === 'N/A') return '';
    return `<span class="meta-chip ${extraClass || ''}">${icon}<span class="meta-chip-label">${esc(text)}</span></span>`;
  }

  function metaChips(row) {
    const hasSo = row.has_so === true ? 'Có sổ' : (row.has_so === false ? 'Chưa có sổ' : '');
    return [
      metaChip(ICONS.pin, row.ward || 'Chưa rõ', 'meta-chip-ward'),
      metaChip(ICONS.area, areaLabel(row), 'meta-chip-area'),
      metaChip(ICONS.road, roadLabel(row), 'meta-chip-road'),
      metaChip(ICONS.street, row.street_label, 'meta-chip-street'),
      metaChip(ICONS.property, propertyLabel(row), 'meta-chip-property'),
      metaChip(ICONS.land, thoCuLabel(row), 'meta-chip-land'),
      metaChip(ICONS.legal, hasSo, 'meta-chip-legal'),
    ].join('');
  }

  function qualityBadges(row) {
    const flags = String(row.source_quality_flags || '');
    const badges = [];
    if (flags.includes('low_segment_confidence')) badges.push('Ít mẫu định giá');
    if (flags.includes('low_road_confidence')) badges.push('Cấp đường cần kiểm tra');
    return badges.map((label) => `<span class="sc-quality-tag">${esc(label)}</span>`).join('');
  }

  function media(row, overlays) {
    const image = String(row.primary_img || '').trim();
    const hasImage = Boolean(image);
    const imageHtml = hasImage
      ? `<img class="sc-img" src="${esc(image)}" loading="lazy" fetchpriority="auto" decoding="async" width="520" height="338" alt="Ảnh tin đăng" onerror="this.closest('.sc-img-wrap').classList.add('is-image-missing');this.remove();">`
      : '';
    return `
      <div class="sc-img-wrap${hasImage ? '' : ' sc-img-wrap-empty'}" data-has-image="${hasImage ? '1' : '0'}">
        ${imageHtml}
        <div class="sc-empty-media" aria-label="Tin đăng chưa có ảnh">
          <div class="sc-empty-media-map" aria-hidden="true"><span></span><span></span><span></span><span></span></div>
          <div class="sc-empty-media-mark" aria-hidden="true">
            <svg width="38" height="38" viewBox="0 0 48 48" fill="none"><path d="M24 42s13-10.6 13-24a13 13 0 1 0-26 0c0 13.4 13 24 13 24Z" stroke="currentColor" stroke-width="3"/><path d="M18 20h12M18 25h8" stroke="currentColor" stroke-width="3" stroke-linecap="round"/></svg>
          </div>
          <div class="sc-empty-media-copy"><strong>Chưa có ảnh</strong><span>Xem giá và vị trí</span></div>
        </div>
        ${overlays}
      </div>
    `;
  }

  function renderCard(row, index) {
    const id = Number(row && row.id);
    if (!Number.isSafeInteger(id) || id <= 0) return '';

    const position = Math.min(Math.max(Number(index) || 0, 0), 5) + 1;
    const detailHref = `/listing/${id}`;
    const mos = finiteNumber(row.mos_pct_display ?? row.mos_pct);
    const isNew = finiteNumber(row.days_ago) !== null
      && finiteNumber(row.days_ago) >= 0
      && finiteNumber(row.days_ago) <= 7;
    const actualPpm2 = formatNumber(row.actual_ppm2 || row.price_per_m2);
    const fairPpm2 = formatNumber(row.fair_ppm2_display || row.fair_ppm2);
    const actualBelowFair = positiveNumber(row.actual_ppm2 || row.price_per_m2) !== null
      && positiveNumber(row.fair_ppm2_display || row.fair_ppm2) !== null
      && Number(row.actual_ppm2 || row.price_per_m2) < Number(row.fair_ppm2_display || row.fair_ppm2);
    const actualClass = actualBelowFair ? 'price-deal' : 'price-neutral';
    const sourceTag = window.USER_TIER === 'admin' && row.source
      ? `<span class="sc-source-tag">${esc(row.source)}</span>`
      : '';
    const mosBadge = mos !== null && mos > 0
      ? `<div class="mos-badge">Rẻ hơn ${esc(Math.round(mos))}%</div>`
      : '';
    const newBadge = isNew ? '<div class="new-badge">MỚI</div>' : '';
    const dropBadge = row.price_dropped
      ? `<span class="sc-drop-tag">Chủ hạ: ${row.drop_pct ? `${esc(row.drop_pct)}%` : 'N/A'}</span>`
      : '';
    const overlays = `
      ${mosBadge}
      ${newBadge}
      <div class="sc-img-tags">
        ${sourceTag}
        <span class="sc-time-tag">${esc(timeLabel(row.days_ago))}</span>
        ${dropBadge}
        ${qualityBadges(row)}
      </div>
    `;

    return `
      <a class="scard valuation-comparable-card${isNew ? ' is-new-signal' : ''}"
         href="${detailHref}"
         data-comparable-position="${position}"
         data-property-type="${esc(row.prop_type || '')}"
         aria-label="Xem chi tiết ${esc(row.title || `tin #${id}`)}">
        ${media(row, overlays)}
        <div class="sc-body">
          <div class="sc-title" title="${esc(row.title || '')}">${esc(row.title || `Tin #${id}`)}</div>
          <div class="price-container">
            <div class="price-actual">
              <span class="price-label price-label-actual ${actualClass}">THỰC TẾ</span>
              <div class="price-val ${actualClass}">${esc(priceLabel(row))}</div>
              <div class="price-m2">${actualPpm2 ? `${esc(actualPpm2)} tr/m²` : '-'}</div>
            </div>
            <div class="price-fair">
              <span class="price-label price-label-fair">ĐỊNH GIÁ</span>
              <div class="price-val price-val-fair">${esc(fairTotal(row))}</div>
              <div class="price-m2">${fairPpm2 ? `${esc(fairPpm2)} tr/m²` : '-'}</div>
            </div>
          </div>
          <div class="sc-meta-chips">${metaChips(row)}</div>
        </div>
      </a>
    `;
  }

  function renderGrid(rows) {
    if (!Array.isArray(rows)) return '';
    return rows.slice(0, 6).map(renderCard).join('');
  }

  window.RadarValuationComparableCard = {
    renderCard,
    renderGrid,
  };
}());
