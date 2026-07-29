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

  function dataAttrs(item) {
    var attrs = {
      id: item.id,
      title: item.title || '',
      primary: item.primary_img || (item.imgs && item.imgs[0]) || '',
      price: item.price_ty || item.price || '',
      ppm2: item.actual_ppm2 || item.price_per_m2 || '',
      fair: item.fair_total_ty || '',
      fppm2: item.fair_ppm2_display || item.fair_ppm2 || '',
      'mos-pct-display': item.mos_pct_display || item.mos_pct || '',
      area: item.area_m2 || item.area || '',
      frontage: item.frontage_m || item.frontage || '',
      depth: item.depth_m || item.depth || '',
      ward: item.ward || '',
      road: item.road_label || item.road_type || item.road_tier || '',
      'road-label': item.road_label || '',
      'street-label': item.street_label || '',
      'tho-cu': item.tho_cu_m2 || '',
      'tho-cu-label': item.tho_cu_label || '',
      'prop-label': item.prop_type_label || item.property_type_label || '',
      mos: item.mos_pct_display || item.mos_pct || '',
      source: item.source || '',
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
    var fair = positive(item.fair_ppm2_display || item.fair_ppm2);
    var area = positive(item.area_m2 || item.area);
    var fairTotal = fair && area ? fair * area / 1000 : null;
    var mos = positive(item.mos_pct_display || item.mos_pct || item.mos);
    var newListing = number(item.days_ago) !== null && number(item.days_ago) >= 0 && number(item.days_ago) <= 7;
    var property = item.prop_type_label || item.property_type_label || item.prop_type || item.property_type || '';
    var road = item.road_label || item.street_label || item.road_type || '';
    var thoCu = item.tho_cu_label || (item.tho_cu_m2 ? 'TC ' + format(item.tho_cu_m2) + 'm²' : '');
    var wrapperOpen = openMode === 'link'
      ? '<a class="scard signal-shared-card ' + (newListing ? 'is-new-signal' : '') + '" href="' + href + '"'
      : `<div class="scard signal-shared-card ${newListing ? 'is-new-signal' : ''}" role="button" tabindex="0" onclick="${handler}(this)" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();${handler}(this);}"`;
    var wrapperClose = openMode === 'link' ? '</a>' : '</div>';
    var favorite = showFavorite
      ? '<button type="button" class="favorite-btn" data-listing-id="' + esc(item.id) + '" onclick="event.stopPropagation();toggleFavoriteListing(this.dataset.listingId,event)">Lưu</button>'
      : '';
    var contact = showContact
      ? `<a href="#" class="btn-zalo" onclick="event.preventDefault();event.stopPropagation();const c=this.closest('.scard').dataset;tierCTA(c.id,c.url,'card_signal')">Ráp mối</a>`
      : '';
    return wrapperOpen + ' ' + dataAttrs(item) + ' aria-label="Xem chi tiết ' + esc(item.title || ('tin #' + item.id)) + '">'
      + '<div class="sc-img-wrap' + (isDefaultImage ? ' sc-img-wrap-empty' : '') + '">'
      + '<img class="sc-img' + (isDefaultImage ? ' is-default' : '') + '" src="' + esc(imageSource)
      + '" loading="lazy" decoding="async" width="520" height="338" alt="'
      + (isDefaultImage ? 'Ảnh mặc định Radar BĐS' : 'Ảnh tin đăng')
      + '" data-default-image="' + (isDefaultImage ? 'true' : 'false')
      + '" onerror="RadarSignalCard.useFallbackImage(this)">'
      + '<div class="sc-empty-media"><div class="sc-empty-media-copy"><strong>Chưa có ảnh</strong><span>Xem giá và vị trí</span></div></div>'
      + (mos ? '<div class="mos-badge">Rẻ hơn ' + Math.round(mos) + '%</div>' : '')
      + (newListing ? '<div class="new-badge">MỚI</div>' : '')
      + '</div>'
      + '<div class="sc-body"><div class="sc-title" title="' + esc(item.title || '') + '">' + esc(item.title || '-') + '</div>'
      + '<div class="price-container"><div class="price-actual"><span class="price-label price-label-actual price-deal">THỰC TẾ</span>'
      + '<div class="price-val price-deal">' + (price ? esc(format(price, 2)) + ' tỷ' : '-') + '</div>'
      + '<div class="price-m2">' + (actual ? esc(format(actual)) + ' tr/m²' : '-') + '</div></div>'
      + '<div class="price-fair"><span class="price-label price-label-fair">ĐỊNH GIÁ</span>'
      + '<div class="price-val price-val-fair">' + (fairTotal ? esc(format(fairTotal, 2)) + ' tỷ' : '-') + '</div>'
      + '<div class="price-m2">' + (fair ? esc(format(fair)) + ' tr/m²' : '-') + '</div></div></div>'
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
    defaultImage: defaultImage,
    useFallbackImage: useFallbackImage
  };
});
