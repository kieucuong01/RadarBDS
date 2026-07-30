(function (root, factory) {
  var api = factory(root);
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root && root.document) root.RadarSignalCard = api;
})(typeof window !== 'undefined' ? window : null, function (root) {
  'use strict';

  var DEFAULT_IMAGE = 'data:image/svg+xml;charset=UTF-8,' + encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 520 338" role="img" aria-label="Ảnh mặc định Radar BĐS">'
    + '<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#172554"/><stop offset="1" stop-color="#0f766e"/></linearGradient></defs>'
    + '<rect width="520" height="338" fill="url(#g)"/>'
    + '<path d="M74 247l102-95 67 59 64-68 139 104H74z" fill="#dbeafe" opacity=".3"/>'
    + '<circle cx="388" cy="91" r="36" fill="#fbbf24" opacity=".78"/>'
    + '<path d="M222 121h76v76h-76z" fill="none" stroke="#fff" stroke-width="11" transform="rotate(45 260 159)"/>'
    + '<circle cx="260" cy="159" r="15" fill="#fff"/>'
    + '<text x="260" y="292" text-anchor="middle" fill="#fff" font-family="Arial,sans-serif" font-size="25" font-weight="700">Radar BĐS</text>'
    + '</svg>'
  );

  function defaultImage() {
    return DEFAULT_IMAGE;
  }

  function useFallbackImage(image) {
    if (!image) return;
    image.onerror = null;
    image.src = DEFAULT_IMAGE;
    image.dataset.defaultImage = 'true';
    if (image.classList) image.classList.add('is-default');
    if (image.parentElement && image.parentElement.classList) {
      image.parentElement.classList.add('is-image-missing');
    }
  }

  function esc(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function number(value) {
    if (value === null || value === undefined || value === '') return null;
    var parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }

  function positive(value) {
    var parsed = number(value);
    return parsed !== null && parsed > 0 ? parsed : null;
  }

  function format(value, digits) {
    var parsed = positive(value);
    if (parsed === null) return '';
    return parsed.toLocaleString('vi-VN', { maximumFractionDigits: digits == null ? 1 : digits });
  }

  function detailHref(item) {
    var id = Number(item && item.id);
    return Number.isSafeInteger(id) && id > 0 ? '/listing/' + id : '';
  }

  function areaLabel(item) {
    var area = format(item.area_m2 || item.area);
    var frontage = format(item.frontage_m || item.frontage);
    var depth = format(item.depth_m || item.depth);
    if (frontage && depth && area) return frontage + 'x' + depth + ' (' + area + 'm²)';
    return area ? area + 'm²' : '';
  }

  function chip(label, className) {
    var text = String(label || '').trim();
    if (!text || text === '-') return '';
    return '<span class="meta-chip ' + className + '"><span class="meta-chip-label">'
      + esc(text) + '</span></span>';
  }

  function daysAgoValue(value) {
    var parsed = number(value);
    return parsed !== null && parsed >= 0 ? parsed : null;
  }

  function timeAgoText(value) {
    var days = daysAgoValue(value);
    if (days === null) return 'Chưa rõ ngày';
    return days === 0 ? 'hôm nay' : days + ' ngày trước';
  }

  function cardDateText(item) {
    var relative = timeAgoText(item && item.days_ago);
    var reason = String((item && item.card_date_reason) || 'posted');
    if (reason === 'price_updated') return 'Cập nhật giá ' + relative;
    if (reason === 'first_seen') return 'Theo dõi từ ' + relative;
    return relative;
  }

  function formatTy(value) {
    var parsed = positive(value);
    if (parsed === null) return '-';
    return parsed.toFixed(2).replace(/\.?0+$/, '');
  }

  function formatPpm2(value) {
    var parsed = positive(value);
    if (parsed === null) return '';
    return parsed.toFixed(1).replace(/\.0$/, '');
  }

  function valuationItems(item) {
    var area = positive(item.area_m2 || item.area);
    if (area === null) return [];
    var items = [];
    var oldPpm2 = positive(item.fair_ppm2_old);
    var newPpm2 = positive(item.fair_ppm2_new);
    if (oldPpm2 !== null) {
      items.push({ key: 'old', ppm2: oldPpm2, total: oldPpm2 * area / 1000 });
    }
    if (newPpm2 !== null) {
      items.push({ key: 'new', ppm2: newPpm2, total: newPpm2 * area / 1000 });
    }
    if (!items.length) {
      var fairPpm2 = positive(item.fair_ppm2_display || item.fair_ppm2 || item.fppm2);
      if (fairPpm2 !== null) {
        items.push({ key: 'legacy', ppm2: fairPpm2, total: fairPpm2 * area / 1000 });
      }
    }
    return items.sort(function (a, b) { return a.total - b.total; });
  }

  function fairPrice(item) {
    var items = valuationItems(item);
    if (items.length) return formatTy(items[0].total);
    if (item.fair_total_ty) return formatTy(item.fair_total_ty);
    if (item.fair) return String(item.fair);
    return '-';
  }

  function valuationHtml(item) {
    var items = valuationItems(item);
    if (!items.length) return '<div class="price-val price-val-fair">-</div><div class="price-m2">-</div>';
    var totals = items.map(function (entry) {
      return '<span class="valuation-value">' + esc(formatTy(entry.total)) + ' tỷ</span>';
    }).join('<span class="valuation-sep">~</span>');
    var ppm2Values = items.map(function (entry) {
      return '<span class="valuation-ppm2">' + esc(formatPpm2(entry.ppm2)) + ' tr/m²</span>';
    }).join('<span class="valuation-ppm2-gap"></span>');
    return '<div class="price-val price-val-fair valuation-total-row">' + totals + '</div>'
      + '<div class="price-m2 valuation-ppm2-row">' + ppm2Values + '</div>';
  }

  function actualPriceClass(item) {
    var actual = positive(item.actual_ppm2 || item.price_per_m2 || item.ppm2);
    var items = valuationItems(item);
    if (actual === null || !items.length) return 'price-deal';
    var values = items.map(function (entry) { return entry.ppm2; });
    var low = Math.min.apply(null, values);
    var high = Math.max.apply(null, values);
    if (actual < low) return 'price-deal';
    if (actual > high) return 'price-over';
    return 'price-neutral';
  }

  function qualityBadges(item) {
    var flags = String(item.source_quality_flags || '')
      .split(',')
      .map(function (flag) { return flag.trim(); })
      .filter(Boolean);
    if (flags.indexOf('low_segment_confidence') === -1) return '';
    return '<span class="sc-quality-tag" title="Dữ liệu so sánh còn ít, cần kiểm tra thêm trước khi xuống tiền.">'
      + '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4"><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"/><path d="M12 9v4"/><path d="M12 17h.01"/></svg>'
      + 'Mẫu giá mỏng</span>';
  }

  function favoriteIconSvg() {
    return '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.6l-1-1a5.5 5.5 0 1 0-7.8 7.8l1 1L12 21l7.8-7.6 1-1a5.5 5.5 0 0 0 0-7.8Z"/></svg>';
  }

  function sourceName(source) {
    var names = { facebook: 'Facebook', guland: 'Guland.vn', batdongsan: 'BatDongSan' };
    return names[source] || source || '';
  }

  function dataAttrs(item, computedFair, timeText, roadText) {
    var attrs = {
      id: item.id,
      title: item.title || '',
      primary: item.primary_img || (item.imgs && item.imgs[0]) || '',
      price: item.price_ty || item.price || '',
      ppm2: item.actual_ppm2 || item.price_per_m2 || '',
      fair: computedFair !== '-' ? computedFair : '',
      fppm2: item.fair_ppm2_display || item.fair_ppm2 || '',
      'fair-ppm2-old': item.fair_ppm2_old || '',
      'fair-ppm2-new': item.fair_ppm2_new || '',
      'mos-pct-old': item.mos_pct_old || '',
      'mos-pct-new': item.mos_pct_new || '',
      'mos-pct-display': item.mos_pct_display || item.mos_pct || '',
      area: item.area_m2 || item.area || '',
      frontage: item.frontage_m || item.frontage || '',
      depth: item.depth_m || item.depth || '',
      ward: item.ward || '',
      road: roadText || item.road_label || item.road_type || item.road_tier || '',
      'road-label': item.road_label || '',
      'street-label': item.street_label || '',
      'tho-cu': item.tho_cu_m2 || '',
      'tho-cu-label': item.tho_cu_label || '',
      'prop-label': item.prop_type_label || item.property_type_label || '',
      time: timeText || '',
      mos: item.mos_pct_display || item.mos_pct || '',
      source: sourceName(item.source),
      drop: item.drop_pct || '',
      score: item.signal_score || '',
      url: item.url || '',
      ptype: item.prop_type || item.property_type || ''
    };
    return Object.keys(attrs).map(function (key) {
      return 'data-' + key + '="' + esc(attrs[key]) + '"';
    }).join(' ');
  }

  function render(item, options) {
    options = options || {};
    var href = detailHref(item);
    if (!href) return '';
    var showFavorite = options.showFavorite !== false;
    var showContact = options.showContact !== false;
    var openMode = options.openMode || 'modal';
    var handler = String(options.openHandler || 'openSignal').replace(/[^A-Za-z0-9_$]/g, '');
    var image = item.primary_img || (Array.isArray(item.imgs) ? item.imgs[0] : '') || '';
    var isDefaultImage = !image;
    var imageSource = image || DEFAULT_IMAGE;
    var price = positive(item.price_ty || item.price);
    var actual = positive(item.actual_ppm2 || item.price_per_m2);
    var mos = positive(item.mos_pct_display || item.mos_pct || item.mos);
    var dateReason = String(item.card_date_reason || 'posted');
    var newListing = dateReason !== 'price_updated'
      && number(item.days_ago) !== null
      && number(item.days_ago) >= 0
      && number(item.days_ago) <= 7;
    var priceUpdated = dateReason === 'price_updated';
    var property = item.prop_type_label || item.property_type_label || item.prop_type || item.property_type || '';
    var road = item.road_label || item.street_label || item.road_type || '';
    var thoCu = item.tho_cu_label || (item.tho_cu_m2 ? 'TC ' + format(item.tho_cu_m2) + 'm²' : '');
    var timeText = cardDateText(item);
    var computedFair = fairPrice(item);
    var actualClass = actualPriceClass(item);
    var dropBadge = item.price_dropped
      ? '<span class="sc-drop-tag"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="12 4 12 20"/><polyline points="6 14 12 20 18 14"/></svg> Chủ hạ: '
        + (item.drop_pct ? esc(item.drop_pct) + '%' : 'N/A') + '</span>'
      : '';
    var source = sourceName(item.source);
    var sourceTag = root && root.USER_TIER === 'admin' && source
      ? '<span class="sc-source-tag">' + esc(source) + '</span>'
      : '';
    var wrapperOpen = openMode === 'link'
      ? '<a class="scard signal-shared-card ' + (newListing ? 'is-new-signal' : '') + '" href="' + href + '"'
      : `<div class="scard signal-shared-card ${newListing ? 'is-new-signal' : ''}" role="button" tabindex="0" onclick="${handler}(this)" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();${handler}(this);}"`;
    var wrapperClose = openMode === 'link' ? '</a>' : '</div>';
    var favorite = showFavorite
      ? '<button type="button" class="favorite-btn" data-listing-id="' + esc(item.id) + '" aria-pressed="false" title="Lưu lô này" onclick="event.stopPropagation();toggleFavoriteListing(this.dataset.listingId,event)">'
        + favoriteIconSvg() + '<span>Lưu</span></button>'
      : '';
    var contactContext = options.context === 'all' ? 'card_all' : 'card_signal';
    var ctaLabel = root && (root.USER_TIER === 'vip' || root.USER_TIER === 'admin') ? '⚡ Ráp mối VIP' : '💬 Ráp mối';
    var contact = showContact
      ? `<a href="#" class="btn-zalo" onclick="event.preventDefault();event.stopPropagation();const c=this.closest('.scard').dataset;tierCTA(c.id,c.url,'${contactContext}')">${ctaLabel}</a>`
      : '';
    return wrapperOpen + ' ' + dataAttrs(item, computedFair, timeText, road) + ' aria-label="Xem chi tiết ' + esc(item.title || ('tin #' + item.id)) + '">'
      + '<div class="sc-img-wrap' + (isDefaultImage ? ' sc-img-wrap-empty' : '') + '">'
      + '<img class="sc-img' + (isDefaultImage ? ' is-default' : '') + '" src="' + esc(imageSource)
      + '" loading="lazy" decoding="async" width="520" height="338" alt="'
      + (isDefaultImage ? 'Ảnh mặc định Radar BĐS' : 'Ảnh tin đăng')
      + '" data-default-image="' + (isDefaultImage ? 'true' : 'false')
      + '" onerror="RadarSignalCard.useFallbackImage(this)">'
      + '<div class="sc-empty-media"><div class="sc-empty-media-copy"><strong>Chưa có ảnh</strong><span>Xem giá và vị trí</span></div></div>'
      + (mos ? '<div class="mos-badge">Rẻ hơn ' + Math.round(mos) + '%</div>' : '')
      + (priceUpdated
        ? '<div class="new-badge price-update-badge">CẬP NHẬT GIÁ</div>'
        : (newListing ? '<div class="new-badge">MỚI</div>' : ''))
      + '<div class="sc-img-tags">'
      + sourceTag
      + '<span class="sc-time-tag"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg> ' + esc(timeText) + '</span>'
      + dropBadge
      + qualityBadges(item)
      + '</div>'
      + '</div>'
      + '<div class="sc-body"><div class="sc-title" title="' + esc(item.title || '') + '">' + esc(item.title || '-') + '</div>'
      + '<div class="price-container"><div class="price-actual"><span class="price-label price-label-actual ' + actualClass + '">THỰC TẾ</span>'
      + '<div class="price-val ' + actualClass + '">' + (price ? esc(format(price, 2)) + ' tỷ' : '-') + '</div>'
      + '<div class="price-m2">' + (actual ? esc(format(actual)) + ' tr/m²' : '-') + '</div></div>'
      + '<div class="price-fair"><span class="price-label price-label-fair">ĐỊNH GIÁ</span>'
      + valuationHtml(item) + '</div></div>'
      + '<div class="sc-meta-chips">'
      + chip(item.ward || 'Chưa rõ', 'meta-chip-ward')
      + chip(areaLabel(item), 'meta-chip-area')
      + chip(road, 'meta-chip-road')
      + chip(property, 'meta-chip-property')
      + chip(thoCu, 'meta-chip-land')
      + '</div>'
      + ((favorite || contact) ? '<div class="sc-actions" onclick="event.stopPropagation()">' + favorite + contact + '</div>' : '')
      + '</div>' + wrapperClose;
  }

  return {
    render: render,
    detailHref: detailHref,
    cardDateText: cardDateText,
    defaultImage: defaultImage,
    useFallbackImage: useFallbackImage
  };
});
