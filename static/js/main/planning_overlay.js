(function (root, factory) {
  var branding = typeof module === 'object' && module.exports
    ? require('./planning_reference_branding.js') : root && root.RadarPlanningReferenceBranding;
  var administrative = typeof module === 'object' && module.exports
    ? require('./planning_administrative.js') : root && root.RadarAdministrativeBoundaries;
  var api = factory(branding, administrative);
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.RadarPlanningOverlay = api;
})(typeof window !== 'undefined' ? window : null, function (branding, administrative) {
  'use strict';

  function dismissOutsidePanels(panels,target) {
    if(!target)return;
    panels.forEach(function(panel){if(panel.open&&!panel.contains(target))panel.open=false;});
  }

  function validBounds(b, limits) {
    return Array.isArray(b) && b.length === 2 && b.every(function (p) {
      return Array.isArray(p) && p.length === 2 && p.every(Number.isFinite);
    }) && b[0][0] >= limits[0] && b[0][1] >= limits[1] && b[1][0] <= limits[2] && b[1][1] <= limits[3]
      && b[0][0] < b[1][0] && b[0][1] < b[1][1];
  }

  function transportTemplate(template) {
    return template === 'https://s3.hn-1.cloud.cmctelecom.vn/guland7/metro-hcm-3/{z}/{x}/{y}.png' ? 19 : 0;
  }

  function validManifest(data, landuseRules) {
    if (!data || !/^[a-z0-9-]+$/.test(data.id || '') || ['local_experiment','reference_overlay'].indexOf(data.status) < 0) return false;
    var rule = landuseRules && landuseRules[data.id];
    if (rule) return data.status === 'reference_overlay' && data.source_kind === 'guland_reference' && data.render_mode === 'xyz'
      && data.source_tiles === undefined && data.planning_status !== 'draft'
      && validBounds(data.bounds,[7,101,24,118])
      && ['tile_template','bounds','min_zoom','max_zoom','tile_size','min_native_zoom','max_native_zoom','coverage_windows'].every(function(key){
        return JSON.stringify(data[key]) === JSON.stringify(rule[key]);
      }) && typeof data.title === 'string' && typeof data.notice === 'string';
    if (data.render_mode === 'geojson' && ['official_gis_administrative','open_administrative_reference'].indexOf(data.source_kind)>=0)
      return !!administrative && administrative.validManifest(data);
    if (data.render_mode === 'geojson') return data.id === 'hcm-transport-gis-roads'
      && data.source_kind === 'official_gis_transport'
      && data.geojson_url === '/static/data/planning_transport_roads.geojson?v=transport-gis-20261029'
      && validBounds(data.bounds,[10,105,12.3,108]) && typeof data.title === 'string' && typeof data.notice === 'string';
    var referenceRaster = data.source_kind === 'guland_reference';
    var referenceTemplate = /^https:\/\/(?:r4gmiynxmeobj\.vcdn\.cloud\/(?:binh-duong|tp-ho-chi-minh|tay-ninh|long-an)-2030|s3\.hn-1\.cloud\.cmctelecom\.vn\/guland9\/qh-(?:brvt|dong-nai)\/sdd)\/\{z\}\/\{x\}\/\{y\}\.png$/;
    var tayNinh2030 = referenceRaster && /^https:\/\/r4gmiynxmeobj\.vcdn\.cloud\/(?:tay-ninh|long-an)-2030\/\{z\}\/\{x\}\/\{y\}\.png$/.test(data.tile_template || '');
    var vision100 = referenceRaster && data.tile_template === 'https://r4gmiynxmeobj.vcdn.cloud/hcm-100-nam-2/sdd/{z}/{x}/{y}.png';
    var transport = referenceRaster && transportTemplate(data.tile_template);
    if (vision100 && data.planning_status !== 'draft') return false;
    var dongNai2030 = referenceRaster && data.tile_template === 'https://s3.hn-1.cloud.cmctelecom.vn/guland9/qh-dong-nai/sdd/{z}/{x}/{y}.png';
    if (data.render_mode !== undefined && (data.render_mode !== 'xyz'
        || !(referenceRaster ? (transport ? data.max_native_zoom === transport : vision100 ? data.max_native_zoom === 19 : referenceTemplate.test(data.tile_template || '') && data.max_native_zoom === (tayNinh2030 ? 18 : 17))
          : /^\/(local-planning|api\/planning)\/gis-tiles\/(partition|urban_general|detailed)\/\{z\}\/\{x\}\/\{y\}\.png$/.test(data.tile_template || ''))
        || data.tile_size !== 256 || data.min_zoom !== 8 || data.max_zoom !== 23)) return false;
    if (referenceRaster && data.render_mode !== 'xyz') return false;
    if (data.source_tiles !== undefined) {
      var collection = (data.tile_template || '').match(/\/gis-tiles\/(partition|urban_general|detailed)\//);
      var sources = {partition:['SuDungDat_QHPK_HCM_V2','QHXD_SDD_2025_QHPK_V3'],
        urban_general:['SuDungDat_QHC_HCM','QHXD_SDD_2025_QHCDT'],detailed:['SuDungDat_QHCT_HCM','QHXD_SDD_2025_QHCT']};
      if (data.source_kind !== 'official_gis' || !collection || !data.source_tiles) return false;
      var base = 'https://api-gisxaydung.tphcm.gov.vn/arcm/rest/services/HCM/';
      var suffix = '/MapServer/tile/{z}/{y}/{x}';
      if (data.source_tiles.primary !== base + sources[collection[1]][0] + suffix
          || data.source_tiles.supplement !== base + sources[collection[1]][1] + suffix) return false;
    }
    var b = data.bounds;
    var expanded = data.render_mode === 'xyz';
    var limits = tayNinh2030 ? [10.25,105.45,11.85,106.85] : transport ? [10.35,106.35,11.2,107.05] : vision100 ? [10.3,106.25,11.65,107.65] : dongNai2030 ? [10.49,106.39,12.33,107.60] : expanded ? [8.5,106.25,11.65,107.65] : [10.75,106.25,11.65,107.10];
    if (!validBounds(b, limits)) return false;
    if (data.min_native_zoom !== undefined && (!(dongNai2030 || vision100 || transport) || data.min_native_zoom !== (transport ? 12 : vision100 ? 10 : 9))) return false;
    if (transport && data.min_native_zoom !== 12) return false;
    if (vision100 && data.min_native_zoom !== 10) return false;
    if (dongNai2030 && data.min_native_zoom !== 9) return false;
    if (data.coverage_windows !== undefined && (!dongNai2030 || !Array.isArray(data.coverage_windows)
        || data.coverage_windows.length !== 2 || !data.coverage_windows.every(function (w) {
          return validBounds(w, [b[0][0],b[0][1],b[1][0],b[1][1]]);
        }))) return false;
    return typeof data.title === 'string' && typeof data.notice === 'string';
  }

  function opacity(value) {
    var number = Number(value);
    return Number.isFinite(number) ? Math.max(0, Math.min(100, number)) / 100 : 0.35;
  }

  function referenceAnnotations(template) {
    // Reviewed logo footprints in zoom-11 world pixels, keyed by exact source.
    return branding && branding[template] || [];
  }

  function referenceClipPath(template, coords) {
    var rings = referenceAnnotations(template);
    var scale = Math.pow(2, coords.z - 11);
    var holes = rings.map(function (ring) {
      return ring.map(function (p) { return [p[0] * scale - coords.x * 256, p[1] * scale - coords.y * 256]; });
    }).filter(function (points) {
      return !(Math.max.apply(null, points.map(function (p) { return p[0]; })) <= 0
        || Math.min.apply(null, points.map(function (p) { return p[0]; })) >= 256
        || Math.max.apply(null, points.map(function (p) { return p[1]; })) <= 0
        || Math.min.apply(null, points.map(function (p) { return p[1]; })) >= 256);
    });
    if (!holes.length) return '';
    return 'path(evenodd, "M0 0H256V256H0Z ' + holes.map(function (points) {
      return 'M' + points.map(function (p) {
        return p.map(function (n) { return Math.round(n * 1000) / 1000; }).join(' ');
      }).join('L') + 'Z';
    }).join(' ') + '")';
  }

  function referenceBranding(layer, map, L, template) {
    var labels = referenceAnnotations(template).map(function (ring) {
      var xs=ring.map(function(p){return p[0];}), ys=ring.map(function(p){return p[1];});
      var w=Math.min.apply(null,xs), e=Math.max.apply(null,xs), n=Math.min.apply(null,ys), s=Math.max.apply(null,ys);
      var dx=ring[1][0]-ring[0][0], dy=ring[1][1]-ring[0][1];
      var hx=ring[3][0]-ring[0][0], hy=ring[3][1]-ring[0][1];
      var width=Math.hypot(dx,dy), height=Math.hypot(hx,hy);
      var svg='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 '+(e-w)+' '+(s-n)+'">'
        +'<g transform="matrix('+[dx/width,dy/width,hx/height,hy/height,ring[0][0]-w,ring[0][1]-n].join(' ')+')">'
        +'<rect width="'+width+'" height="'+height+'" rx="'+height*.18+'" fill="white" fill-opacity=".94"/>'
        +'<text x="'+width*.04+'" y="'+height*.78+'" font-family="Arial,sans-serif" font-weight="700" font-size="'+height*.82+'" textLength="'+width*.92+'" lengthAdjust="spacingAndGlyphs" fill="#0f172a">Radar<tspan fill="#4f46e5">BDS</tspan></text></g></svg>';
      function lat(y) { return Math.atan(Math.sinh(Math.PI*(1-2*y/524288)))*180/Math.PI; }
      return L.imageOverlay('data:image/svg+xml,'+encodeURIComponent(svg),[[lat(s),w/524288*360-180],[lat(n),e/524288*360-180]],
        Object.assign({},layer.options,{interactive:false,attribution:''}));
    });
    if (!labels.length) return;
    layer.on('add',function(){labels.forEach(function(label){label.addTo(map);});});
    layer.on('remove',function(){labels.forEach(function(label){map.removeLayer(label);});});
    var setOpacity=layer.setOpacity;
    layer.setOpacity=function(value){
      setOpacity.call(this,value);
      labels.forEach(function(label){label.setOpacity(value);});
      return this;
    };
  }

  function themeLabel(item) {
    var scale = item.manifest && item.manifest.map_scale;
    return (item.theme === 'administrative' ? 'Địa giới hành chính 2025' : item.theme === 'transport' ? 'QH Giao thông' : item.theme === 'urban_vision_100' ? 'QH 100 năm (Dự thảo)' : item.theme === 'land_use_2030' ? 'Sử dụng đất 2030' : item.theme === 'detailed' ? 'Quy hoạch chi tiết' : item.theme === 'urban_general' ? 'Quy hoạch chung' : 'Phân khu') + ' · ' + (Number.isInteger(scale) && scale > 0
      ? '1/' + scale.toLocaleString('vi-VN') : 'Chưa xác minh tỷ lệ');
  }

  function validCatalog(data, landuseRules) {
    if (!data || !Array.isArray(data.layers) || !data.layers.length || data.layers.length > 160) return false;
    var ids = new Set();
    return data.layers.every(function (item) {
      if (!item || !/^[a-z0-9-]+$/.test(item.id || '') || ids.has(item.id)) return false;
      ids.add(item.id);
      if (item.city !== undefined && (typeof item.city !== 'string' || !item.city.trim() || item.city.length > 80)) return false;
      if (item.theme !== undefined && ['partition', 'urban_general', 'detailed', 'land_use_2030', 'urban_vision_100', 'transport', 'administrative'].indexOf(item.theme) < 0) return false;
      if (item.source !== undefined && ['gis', 'document', 'guland'].indexOf(item.source) < 0) return false;
      if ((item.source === 'guland' || item.theme === 'land_use_2030' || item.manifest && item.manifest.source_kind === 'guland_reference')
          && !(item.source === 'guland' && ['land_use_2030', 'urban_vision_100', 'transport'].indexOf(item.theme) >= 0 && item.manifest && item.manifest.source_kind === 'guland_reference')) return false;
      if (item.theme === 'administrative' && (!administrative || !administrative.validCatalogItem(item))) return false;
      if ((item.theme === 'administrative') !== Boolean(item.manifest && ['official_gis_administrative','open_administrative_reference'].indexOf(item.manifest.source_kind) >= 0)) return false;
      if ((item.theme === 'transport') !== Boolean(item.manifest && (transportTemplate(item.manifest.tile_template) || item.manifest.source_kind === 'official_gis_transport'))) return false;
      if (item.theme === 'urban_vision_100' && (!item.manifest || item.manifest.planning_status !== 'draft' || item.manifest.tile_template !== 'https://r4gmiynxmeobj.vcdn.cloud/hcm-100-nam-2/sdd/{z}/{x}/{y}.png')) return false;
      if (item.theme === 'land_use_2030' && item.manifest && item.manifest.planning_status === 'draft') return false;
      if (item.scope !== undefined && ['area', 'city', 'region'].indexOf(item.scope) < 0) return false;
      if (item.inspection_only !== undefined && typeof item.inspection_only !== 'boolean') return false;
      var openAdministrativeSource = item.theme === 'administrative' && administrative && administrative.validCatalogItem(item);
      if (typeof item.name !== 'string' || typeof item.decision !== 'string'
          || !openAdministrativeSource && !/^https:\/\/(drive\.google\.com\/|bencat\.binhduong\.gov\.vn\/|bencat-hochiminhcity\.gov\.vn\/|gisxaydung\.tphcm\.gov\.vn\/|government\.cdn\.myaloha\.com\.vn\/|(?:www\.)?aapbinhduong\.com\/|guland\.vn\/(?:soi-quy-hoach(?:[/?]|$)|xem-quy-hoach\/quy-hoach-chung-tp-ho-chi-minh-2025-2050-tam-nhin-100-nam$))/.test(item.source_url || '')) return false;
      if (item.status === 'overlay_ready') return validManifest(item.manifest,landuseRules) && item.manifest.id === item.id;
      if (item.status === 'document_only') return item.preview_url === '/local-planning/' + item.id + '/preview.webp';
      return ['source_unavailable', 'source_missing_map', 'artifact_unavailable'].indexOf(item.status) >= 0;
    });
  }

  function mount(map, L, environment, options) {
    options = options || {};
    var env = environment || window;
    var doc = env.document;
    var published = env.RADAR_PLANNING_CONFIG;
    var assetBase = published ? published.assetBase : '/local-planning/';
    var controller = new env.AbortController();
    var disposed = false;
    var manifest = null;
    var catalog = [];
    var provinces = Array.isArray(env.RADAR_LANDUSE_AREAS) ? env.RADAR_LANDUSE_AREAS : [];
    var selectedArea = options.initialArea || (env.RadarPlanningArea && env.RadarPlanningArea.initial(provinces, options.initialRegion));
    var selectedProvince = provinces.find(function(p){return p.id === (selectedArea ? selectedArea.province : 'binh-duong');});
    var themes = [
      {id: 'land_use_2030', name: 'quy hoạch sử dụng đất 2030', title: 'Quy hoạch sử dụng đất 2030', short: 'QH SDĐ 2030'},
      {id: 'urban_general', name: 'quy hoạch chung đô thị', title: 'Quy hoạch chung đô thị', short: 'QH Chung'},
      {id: 'partition', name: 'quy hoạch phân khu', title: 'Quy hoạch phân khu', short: 'QH Phân khu'},
      {id: 'detailed', name: 'quy hoạch chi tiết', title: 'Quy hoạch chi tiết', short: 'QH Chi tiết'},
      {id: 'urban_vision_100', name: 'quy hoạch chung 100 năm (Dự thảo)', title: 'QH chung 100 năm (Dự thảo)', short: 'QH 100 năm (Dự thảo)'},
      {id: 'transport', name: 'quy hoạch giao thông', title: 'Quy hoạch giao thông · Metro và đường chính', short: 'QH Giao thông'},
      {id: 'administrative', name: 'địa giới hành chính', title: 'Địa giới hành chính mới', short: 'Địa giới'}
    ];
    var overlays = new Map(), failedIds = new Set();
    var pane = map.createPane('planningPilot');
    pane.style.zIndex = '350';
    pane.style.pointerEvents = 'none';
    ['planningTransportRoads','planningTransportMetro'].forEach(function(name,index){
      var transportPane=map.createPane(name);transportPane.style.zIndex=String(355+index);transportPane.style.pointerEvents='none';
    });

    ['planningAdministrative','planningAdministrativeLabels'].forEach(function(name,index){
      var adminPane=map.createPane(name);adminPane.style.zIndex=String(index?400:357);adminPane.style.pointerEvents=index?'none':'auto';
    });

    function node(tag, parent, text) {
      var item = doc.createElement(tag);
      if (text) item.textContent = text;
      if (parent) parent.appendChild(item);
      return item;
    }
    var ui = {root: node('div'), panels: [], initialRegion: options.initialRegion, onToggleFilters: options.onToggleFilters};
    ui.root.className = 'planning-map-ui';
    map.getContainer().appendChild(ui.root);
    var toolbar = node('div', ui.root); toolbar.className = 'planning-map-toolbar';
    toolbar.setAttribute('aria-label', 'Công cụ quy hoạch');
    var filterSlot = node('div', toolbar);
    ui.areaSlot = node('div', toolbar); ui.parcelSlot = node('div', toolbar);
    if (typeof options.onToggleFilters === 'function') {
      var filterButton = node('button', filterSlot, 'Bộ lọc');
      filterButton.type = 'button'; filterButton.className = 'planning-filter-button';
      filterButton.addEventListener('click', options.onToggleFilters);
    }
    if (selectedArea && env.RadarPlanningArea) env.RadarPlanningArea.mount(env, ui, provinces, selectedArea, function(province, area){
      if (disposed) return;
      if (!selectedProvince || selectedProvince.id !== province.id) {
        Array.from(overlays.values()).forEach(function(entry){if(entry.item.theme === 'land_use_2030')removeOverlay(entry.item.id);});
      }
      selectedProvince = province; selectedArea = area;
      updateLayers(true);
      if (activeTheme.id === 'land_use_2030') {
        var item = wantedItems(true).find(function(entry){return entry.theme === 'land_use_2030';});
        if (item) chooseLayer(item);
      }
      map.fire('planning:area-change');
      env.RadarPlanningArea.focus(map,L,area);
    });
    var box = node('details', toolbar);
    box.className = 'planning-overlay-control planning-map-popover';
    ui.panels.push(box);
    box.addEventListener('toggle', function () {
      if (box.open) ui.panels.forEach(function (p) { if (p !== box) p.open = false; });
    });
    node('summary', box, 'Lớp bản đồ');
    if (typeof options.onToggleListings === 'function') {
      var listingsToggle = node('button', toolbar);
      listingsToggle.type = 'button'; listingsToggle.className = 'planning-listings-toggle';
      listingsToggle.setAttribute('aria-controls', 'listingMapPanel listingMapMobileSheet');
      function syncListingsToggle(visible) {
        listingsToggle.textContent = visible ? 'Ẩn tin đăng' : 'Hiện tin đăng';
        listingsToggle.setAttribute('aria-pressed', String(visible));
      }
      syncListingsToggle(options.listingsVisible !== false);
      listingsToggle.addEventListener('click', function () {
        syncListingsToggle(options.onToggleListings());
      });
    }
    var body = node('div', box);
    body.className = 'planning-overlay-body';
    node('span', body, published ? 'DỮ LIỆU QUY HOẠCH THAM KHẢO' : 'THỬ NGHIỆM LOCAL').className = 'planning-overlay-badge';
    var fit = node('button', body, 'Xem vùng có quy hoạch');
    fit.type = 'button'; fit.disabled = true;
    var activeTheme = themes.find(function (theme) { return theme.id === options.initialTheme; })
      || themes.find(function (theme) { return theme.id === 'partition'; });
    var dock = node('div', ui.root); dock.className = 'planning-layer-dock';
    ui.dock = dock;
    dock.setAttribute('aria-label', 'Bật tắt nhanh quy hoạch');
    var rail = node('div', ui.root); rail.className = 'planning-opacity-control';
    var railType = node('select', rail); railType.setAttribute('aria-label', 'Lớp điều chỉnh độ hiển thị');
    themes.forEach(function (theme) { theme.railOption = node('option', railType, theme.short); theme.railOption.value = theme.id; });
    railType.value = activeTheme.id;
    var increase = node('button', rail, '+'); increase.type = 'button'; increase.setAttribute('aria-label', 'Tăng độ hiển thị 10 phần trăm');
    var initialOpacity = (activeTheme.id === 'transport' || activeTheme.id === 'administrative') ? '100' : activeTheme.id === 'land_use_2030' ? '65' : '35';
    var railValue = node('output', rail, initialOpacity + '%');
    var railSlider = node('input', rail); railSlider.type = 'range'; railSlider.min = '0'; railSlider.max = '100'; railSlider.value = initialOpacity; railSlider.step = '1';
    railSlider.disabled = increase.disabled = true;
    railSlider.setAttribute('aria-label', 'Độ hiển thị lớp đang chọn');
    var decrease = node('button', rail, '−'); decrease.type = 'button'; decrease.setAttribute('aria-label', 'Giảm độ hiển thị 10 phần trăm');
    decrease.disabled = true;
    function syncQuickControls() {
      if (!activeTheme.toggle.checked) activeTheme = themes.find(function (t) { return t.toggle.checked; }) || activeTheme;
      railType.value = activeTheme.id;
      railType.disabled = !themes.some(function (theme) { return theme.toggle.checked; });
      railValue.title = activeTheme.short;
      railSlider.value = activeTheme.slider.value;
      railValue.textContent = activeTheme.slider.value + '%';
      railSlider.disabled = activeTheme.slider.disabled;
      increase.disabled = decrease.disabled = railSlider.disabled;
      themes.forEach(function (t) {
        t.quick.disabled = t.toggle.disabled;
        t.railOption.disabled = !t.toggle.checked;
        t.quick.setAttribute('aria-pressed', String(t.toggle.checked));
      });
    }
    function setOpacity(theme, value) {
      var amount = opacity(value);
      theme.slider.value = String(Math.round(amount * 100));
      theme.value.textContent = theme.slider.value + '%';
      overlays.forEach(function (entry) { if (entry.item.theme === theme.id) entry.layer.setOpacity(amount); });
      syncQuickControls();
    }
    railType.addEventListener('change', function () {
      activeTheme = themes.find(function (t) { return t.id === railType.value; }) || activeTheme;
      syncQuickControls();
    });
    railSlider.addEventListener('input', function () { setOpacity(activeTheme, railSlider.value); });
    increase.addEventListener('click', function () { setOpacity(activeTheme, Number(activeTheme.slider.value)+10); });
    decrease.addEventListener('click', function () { setOpacity(activeTheme, Number(activeTheme.slider.value)-10); });
    themes.forEach(function (theme) {
      theme.quick = node('button', dock, theme.short);
      theme.quick.type = 'button'; theme.quick.className = 'planning-layer-chip'; theme.quick.disabled = true;
      theme.quick.setAttribute('aria-label', 'Bật/tắt ' + theme.name);
      theme.quick.setAttribute('aria-pressed', 'false');
      if (theme.id === 'detailed') theme.quick.title = 'Quy hoạch chi tiết theo từng đồ án; phóng gần để xem rõ';
      var card = node('fieldset', body);
      theme.card = card;
      card.className = 'planning-overlay-theme';
      var themeLabel = node('label', card);
      themeLabel.className = 'planning-overlay-toggle';
      theme.toggle = node('input', themeLabel); theme.toggle.type = 'checkbox';
      theme.toggle.checked = false; theme.toggle.disabled = true;
      theme.toggle.setAttribute('aria-label', 'Bật ' + theme.name);
      node('span', themeLabel, theme.title);
      var sourceLabel = node('label', card, 'Nguồn');
      theme.source = node('select', sourceLabel); theme.source.disabled = true;
      theme.source.setAttribute('aria-label', 'Nguồn ' + theme.name);
      if (theme.id === 'administrative') {
        node('option', theme.source, 'Địa giới hành chính mới').value = 'gis';
        theme.source.value = 'gis';
      } else if (theme.id === 'transport') {
        node('option', theme.source, 'Metro + GIS giao thông').value = 'combined';
        theme.source.value = 'combined';
      } else if (theme.id === 'land_use_2030' || theme.id === 'urban_vision_100' || theme.id === 'transport') {
        node('option', theme.source, 'Bản đồ tham khảo').value = 'guland';
        theme.source.value = 'guland';
      } else {
        node('option', theme.source, 'GIS · Cổng dữ liệu').value = 'gis';
        node('option', theme.source, 'Bản vẽ / PDF').value = 'document';
        theme.source.value = 'gis';
      }
      var opacityLabel = node('label', card, 'Độ hiển thị ');
      var defaultOpacity = (theme.id === 'transport' || theme.id === 'administrative') ? '100' : theme.id === 'land_use_2030' ? '65' : '35';
      theme.value = node('output', opacityLabel, defaultOpacity + '%');
      theme.slider = node('input', opacityLabel); theme.slider.type = 'range';
      theme.slider.min = '0'; theme.slider.max = '100'; theme.slider.step = '1'; theme.slider.value = defaultOpacity;
      theme.slider.disabled = true;
      theme.slider.setAttribute('aria-label', 'Độ hiển thị ' + theme.name);
      theme.status = node('p', card, 'Đang kiểm tra nguồn dữ liệu…');
      theme.status.className = 'planning-overlay-metadata';
      function changeTheme() {
        if (disposed) return;
        if (theme.toggle.checked) {
          activeTheme = theme;
          if (options.onThemeEnabled) options.onThemeEnabled(theme.id);
          catalog.forEach(function (item) { if (item.theme === theme.id) failedIds.delete(item.id); });
          var selected = catalog.find(function (item) { return item.theme === theme.id && (theme.id === 'transport' || item.source === theme.source.value) && item.status === 'overlay_ready' && !item.inspection_only; });
          if (selected) chooseLayer(selected);
        }
        updateLayers();
      }
      theme.toggle.addEventListener('change', changeTheme);
      theme.quick.addEventListener('click', function () { theme.toggle.checked = !theme.toggle.checked; changeTheme(); });
      theme.source.addEventListener('change', function () {
        if (disposed) return;
        failedIds.clear(); updateLayers();
        var records = catalog.filter(function (entry) { return entry.theme === theme.id && (theme.id === 'transport' || entry.source === theme.source.value); });
        var item = records.find(function (entry) { return entry.status === 'overlay_ready' && !entry.inspection_only; }) || records[0];
        if (item) chooseLayer(item);
      });
      theme.slider.addEventListener('input', function () {
        setOpacity(theme, theme.slider.value);
      });
    });
    var status = node('p', body, 'Đang tải thông tin lớp bản đồ…');
    status.className = 'planning-overlay-status';
    var zoomHint = node('button',ui.root,'Phóng to để xem QH SDĐ 2030');
    zoomHint.type='button';zoomHint.className='planning-source-zoom-hint';zoomHint.hidden=true;
    zoomHint.addEventListener('click',function(){if(!disposed && selectedProvince)focusProvince();});
    status.setAttribute('role', 'status');
    status.setAttribute('aria-live', 'polite');
    var selectorLabel = node('label', body, 'Hồ sơ / chú giải của lớp');
    var selector = node('select', selectorLabel);
    selector.disabled = true;
    selector.setAttribute('aria-label', 'Xem hồ sơ và chú giải quy hoạch');
    var metadata = node('p', body);
    metadata.className = 'planning-overlay-metadata';
    var legend = node('details', body);
    node('summary', legend, 'Chú giải và hồ sơ gốc');
    var source = node('a', legend, 'Mở bản vẽ gốc · trang 4');
    source.href = 'https://drive.google.com/file/d/12OJDgFVXtPZkXh2DGk5XzEeRAwbCEbiv/view';
    source.target = '_blank'; source.rel = 'noopener noreferrer';
    var preview = node('a', body, 'Xem bản vẽ 1/2.000');
    preview.hidden = true; preview.target = '_blank'; preview.rel = 'noopener noreferrer';
    var legendImage = node('img', legend);
    legendImage.alt = 'Chú giải nguyên bản tờ QH01 Thới Hòa';
    legendImage.loading = 'lazy';
    legend.addEventListener('toggle', function () {
      if (legend.open && manifest && manifest.legend_available !== false && !legendImage.getAttribute('src')) {
        legendImage.src = assetBase + manifest.id + '/legend.webp';
      }
    });
    var notice = node('p', body);
    notice.className = 'planning-overlay-notice';
    L.DomEvent.disableClickPropagation(ui.root);
    L.DomEvent.disableScrollPropagation(ui.root);
    ui.layerBody = body;
    var disposeParcels = env.RADAR_PARCEL_PILOT && env.RadarPlanningParcels
      ? env.RadarPlanningParcels.mount(map, L, env, ui) : null;
    var actions = node('div', rail); actions.className = 'planning-drawing-actions';
    var disposeMeasure = env.RadarPlanningMeasure ? env.RadarPlanningMeasure.mount(map, L, env, ui, actions) : null;
    var disposeLegend = env.RadarPlanningLegend ? env.RadarPlanningLegend.mount(map, L, env, ui, actions, function () {
      var documents = catalog.filter(function (item) { return item.source === 'document' && item.manifest && item.manifest.legend_available !== false; });
      return {theme:activeTheme.id, active:activeTheme.toggle.checked, source:activeTheme.source.value, assetBase:assetBase, documents:documents,
        selectedDocument:documents.some(function (item) { return item.id === selector.value && item.theme === activeTheme.id; }) ? selector.value : null};
    }) : null;
    function keydown(event) {
      event.stopPropagation();
      if (event.key === 'Escape') ui.panels.forEach(function (p) { p.open = false; });
    }
    ui.root.addEventListener('keydown', keydown);
    function outsidePointer(event){dismissOutsidePanels(ui.panels,event.target);}
    if(doc.addEventListener)doc.addEventListener('pointerdown',outsidePointer,true);

    function wantedItems(readyOnly) {
      return catalog.filter(function (item) {
        var theme = themes.find(function (entry) { return entry.id === item.theme; });
        return inSelectedProvince(item) && theme.toggle.checked && (theme.id === 'transport' || item.source === theme.source.value)
          && (theme.id !== 'land_use_2030' || (selectedProvince ? selectedProvince.layer_ids.indexOf(item.id) >= 0 : item.area_id === 'binh-duong-legacy'))
          && (!readyOnly || (item.status === 'overlay_ready' && !item.inspection_only));
      });
    }

    function reportCoverage() {
      if (disposed) return;
      zoomHint.hidden=true;
      if (!themes.some(function (theme) { return theme.toggle.checked; })) {
        status.textContent = 'Đang tắt các lớp quy hoạch.'; return;
      }
      var entries = Array.from(overlays.values());
      var loading = entries.filter(function (entry) { return !entry.loaded; }).length;
      var errors = wantedItems(true).filter(function (item) {
        return failedIds.has(item.id) && map.getBounds().intersects(item.manifest.bounds);
      });
      if (loading) status.textContent = 'Đang tải ' + loading + ' lớp quy hoạch…';
      else if (entries.length) {
        status.textContent = entries.some(function (entry) { return map.getBounds().intersects(entry.item.manifest.bounds); })
          ? 'Đang hiển thị ' + entries.length + ' lớp quy hoạch trong vùng nhìn.'
          : 'Ngoài vùng có dữ liệu. Chọn “Xem vùng có quy hoạch”.';
      } else status.textContent = 'Vùng nhìn chưa có lớp đang bật. Kéo bản đồ để xem vùng lân cận hoặc chọn “Xem vùng có quy hoạch”.';
      if (!entries.length && typeof map.getZoom === 'function' && wantedItems(true).some(function(item){
        return nearSource(item) && map.getZoom() < (item.manifest.min_zoom || 8);
      })) {
        status.textContent = 'Phóng to để xem QH SDĐ 2030; nguồn này chưa có ảnh tổng quan ở mức thu nhỏ hiện tại.';
        zoomHint.hidden=!selectedProvince;
      }
      if (errors.length) status.textContent += ' Không tải được: ' + errors.map(function (item) { return item.name; }).join(', ')
        + '. Tắt/bật loại bản đồ để thử lại; Maps vẫn hoạt động.';
      if (entries.some(function (entry) { return entry.tileError; })) status.textContent += ' Một số ô bản đồ chưa tải được; thử thu phóng hoặc chuyển vùng để tải lại.';
    }

    function removeOverlay(id) {
      var entry = overlays.get(id);
      if (!entry) return;
      map.removeLayer(entry.layer);
      // Leaflet's remove listener detaches zoom/viewreset handlers from the map.
      // Clearing listeners first leaves a detached layer receiving later zooms.
      entry.layer.off();
      overlays.delete(id);
    }

    function overlayBounds(item) {
      var b=item.manifest.bounds;
      if(item.theme !== 'land_use_2030' || !selectedProvince || !selectedProvince.load_bounds)return b;
      var p=selectedProvince.load_bounds;
      return [[Math.max(b[0][0],p[0][0]),Math.max(b[0][1],p[0][1])],
        [Math.min(b[1][0],p[1][0]),Math.min(b[1][1],p[1][1])]];
    }
    function nearSource(item) { return map.getBounds().intersects(overlayBounds(item)); }
    function focusProvince() {
      env.RadarPlanningArea.focus(map,L,{bounds:selectedProvince.focus_bounds||selectedProvince.bounds,
        district:'',min_zoom:selectedProvince.min_zoom||8});
    }
    function syncOverlays() {
      if (disposed) return;
      var viewport = map.getBounds();
      var near = typeof viewport.pad === 'function' ? viewport.pad(0.05) : viewport;
      var desired = wantedItems(true).filter(function (item) {
        return (typeof map.getZoom !== 'function' || map.getZoom() >= (item.manifest.min_zoom || 8))
          && near.intersects(overlayBounds(item)) && (item.manifest.coverage_windows || [item.manifest.bounds]).some(function (b) { return near.intersects(b); });
      });
      var desiredIds = new Set(desired.map(function (item) { return item.id; }));
      Array.from(overlays.keys()).forEach(function (id) {
        if (!desiredIds.has(id)) removeOverlay(id);
      });
      catalog.forEach(function (item, index) {
        if (!desiredIds.has(item.id) || overlays.has(item.id) || failedIds.has(item.id)) return;
        var data = item.manifest;
        var theme = themes.find(function (entry) { return entry.id === item.theme; });
        var layerOptions = {
          pane: item.theme === 'transport' ? (data.render_mode === 'geojson' ? 'planningTransportRoads' : 'planningTransportMetro') : 'planningPilot', opacity: opacity(theme.slider.value), interactive: false,
          zIndex: (item.theme === 'transport' ? 400 : item.theme === 'partition' ? 100 : item.theme === 'detailed' ? 250 : item.theme === 'urban_vision_100' ? 350 : item.theme === 'land_use_2030' ? 300 : 200) + index,
          // Leaflet deduplicates identical provider credits across selected wards.
          attribution: data.source_kind === 'official_gis'
            ? 'Sở Quy hoạch – Kiến trúc TP.HCM · GIS công khai'
            : data.attribution || item.city + ' · ' + item.name + ' · bản thử căn chỉnh'
        };
        var tiled = data.render_mode === 'xyz';
        var tileBounds = overlayBounds(item);
        var tileOptions = Object.assign({}, layerOptions, {
          bounds:tileBounds, tileSize:256, minZoom:data.min_zoom || 8, minNativeZoom:data.min_native_zoom || 8,
          maxZoom:23, maxNativeZoom:data.max_native_zoom || 23,
          updateWhenIdle:true, updateWhenZooming:false, keepBuffer:1
        });
        var layer = data.render_mode === 'geojson'
          ? (item.theme === 'administrative' ? env.RadarAdministrativeBoundaries : env.RadarPlanningTransport).create(map,L,env,data,Object.assign({},layerOptions,{signal:controller.signal}))
          : tiled ? data.source_tiles && env.RadarPlanningNativeTiles
          ? env.RadarPlanningNativeTiles.create(L, env, data, tileOptions)
          : L.tileLayer(data.tile_template, tileOptions)
          : L.imageOverlay(assetBase + item.id + '/overlay.webp', data.bounds, layerOptions);
        if (tiled && data.source_kind === 'guland_reference' && typeof layer.createTile === 'function') {
          var createTile = layer.createTile;
          layer.createTile = function (coords, done) {
            var tile = createTile.call(this, coords, done);
            var clip = referenceClipPath(data.tile_template, coords);
            if (clip) tile.style.clipPath = clip;
            return tile;
          };
          referenceBranding(layer,map,L,data.tile_template);
        }
        if (tiled && (data.coverage_windows || item.theme === 'land_use_2030') && typeof layer._isValidTile === 'function') {
          var validTile = layer._isValidTile;
          layer._isValidTile = function (coords) {
            if (!validTile.call(this, coords)) return false;
            var cell = this._tileCoordsToBounds(coords);
            return cell.intersects(tileBounds) && (data.coverage_windows || [tileBounds]).some(function (b) { return cell.intersects(b); });
          };
        }
        var entry = {item: item, layer: layer, loaded: false};
        overlays.set(item.id, entry);
        layer.on('load', function () {
          if (disposed || overlays.get(item.id) !== entry) return;
          entry.loaded = true; reportCoverage();
        });
        if (tiled) {
          layer.on('loading', function () { if (!disposed && overlays.get(item.id) === entry) { entry.loaded=false; entry.tileError=false; reportCoverage(); } });
          layer.on('tileerror', function () { if (!disposed && overlays.get(item.id) === entry) { entry.tileError=true; reportCoverage(); } });
        } else {
          layer.on('error', function () {
            if (disposed || overlays.get(item.id) !== entry) return;
            removeOverlay(item.id); failedIds.add(item.id); reportCoverage();
          });
        }
        layer.addTo(map);
      });
      themes.forEach(function (theme) {
        theme.slider.disabled = !wantedItems(true).some(function (item) { return item.theme === theme.id; });
      });
      syncQuickControls();
      reportCoverage();
    }

    function updateLayers(provinceChanged) {
      themes.forEach(function (theme) {
        var all = catalog.filter(function (item) { return item.theme === theme.id && inSelectedProvince(item); });
        var available = all.some(function(item){return item.status==='overlay_ready'&&!item.inspection_only||item.status==='document_only';});
        theme.quick.hidden = theme.card.hidden = theme.railOption.hidden = !available;
        if (!available) theme.toggle.checked = false;
        var records = all.filter(function (item) { return theme.id === 'transport' || item.source === theme.source.value; });
        var ready = records.filter(function (item) { return item.status === 'overlay_ready' && !item.inspection_only; });
        theme.toggle.disabled = !ready.length;
        var expected = new Set(all.map(function (item) { return item.city + '|' + item.area_id; }));
        var covered = new Set(ready.map(function (item) { return item.city + '|' + item.area_id; }));
        var missing = expected.size - covered.size;
        var native = ready.some(function (item) { return item.manifest.render_mode === 'xyz'; });
        theme.status.textContent = theme.id === 'administrative'
          ? (ready.length ? ready.map(function(item){return item.name;}).join(' · ') + '. Tải chi tiết theo vùng nhìn; bản hiển thị tham khảo.' : 'Chưa có dữ liệu địa giới cho khu vực này.')
          : native ? (theme.id === 'transport'
          ? 'Metro tham khảo + GIS đường hành lang / vành đai. VĐ1 gồm các đoạn đã đối chiếu, chưa xác minh khép kín. Giữ trạng thái từng đoạn GIS; xem hồ sơ nguồn.'
          : theme.id === 'urban_vision_100'
          ? 'DỰ THẢO · Định hướng 2025–2050, tầm nhìn 100 năm. Chưa xác minh phê duyệt; đối chiếu hồ sơ gốc trước khi sử dụng.'
          : theme.id === 'land_use_2030'
          ? 'Bản đồ tham khảo · tải ô ảnh theo vùng nhìn. Chưa xác minh phủ kín hoặc hiệu lực hồ sơ; xem nguồn để đối chiếu.'
          : theme.id === 'detailed' ? 'Quy hoạch chi tiết theo từng đồ án · phóng gần để xem rõ. Vùng trống cần đối chiếu nguồn.'
          : 'Ô GIS gốc theo từng mức zoom · ' + ready.find(function (item) { return item.manifest.render_mode === 'xyz'; }).city + '. Vùng trống cần kiểm tra thêm nguồn.') : ready.length + ' lớp sẵn sàng' + (missing && ready.length
          ? ' · ' + missing + ' khu vực chưa có nguồn này.' : '.')
          + (!ready.length
            ? ' ' + ((records[0] && records[0].message) || 'Nguồn này chưa có lớp phủ được xác minh.') : '');
      });
      if (selectedProvince && (provinceChanged || activeTheme.quick.hidden) && !themes.some(function(theme){return theme.toggle.checked;})) {
        var fallback = themes.find(function(theme){return theme.id==='land_use_2030'&&!theme.toggle.disabled;});
        if (fallback) {fallback.toggle.checked=true;activeTheme=fallback;}
      }
      Array.from(selector.children).forEach(function(option){
        var item=catalog.find(function(entry){return entry.id===option.value;});
        option.hidden=option.disabled=!!item&&!inSelectedProvince(item);
      });
      var selected=catalog.find(function(item){return item.id===selector.value;});
      if(selected&&!inSelectedProvince(selected)) {
        var replacement=wantedItems(true)[0]||catalog.find(inSelectedProvince);
        if(replacement)chooseLayer(replacement);
      }
      fit.disabled = !wantedItems(true).length;
      syncOverlays();
    }

    function inSelectedProvince(item) {
      return !env.RadarPlanningArea || !env.RadarPlanningArea.coversProvince
        || env.RadarPlanningArea.coversProvince(item,selectedProvince);
    }

    fit.addEventListener('click', function () {
      if (disposed || !wantedItems(true).length) return;
      if (activeTheme.id === 'land_use_2030' && selectedProvince) {
        focusProvince();return;
      }
      var bounds = [[Infinity, Infinity], [-Infinity, -Infinity]];
      wantedItems(true).forEach(function (item) {
        var b = item.manifest.bounds;
        bounds[0][0] = Math.min(bounds[0][0], b[0][0]); bounds[0][1] = Math.min(bounds[0][1], b[0][1]);
        bounds[1][0] = Math.max(bounds[1][0], b[1][0]); bounds[1][1] = Math.max(bounds[1][1], b[1][1]);
      });
      map.fitBounds(bounds, { padding: [30, 30], maxZoom: 15 });
    });
    function viewportChanged() { syncOverlays(); }
    map.on('moveend', viewportChanged);

    function chooseLayer(item) {
      manifest = item.status === 'overlay_ready' ? item.manifest : null;
      selector.value = item.id;
      legendImage.removeAttribute('src');
      source.href = item.source_url;
      source.textContent = (item.source === 'guland' ? 'Nguồn dữ liệu · ' : manifest && manifest.source_kind === 'official_gis' ? 'Cổng GIS và chú giải · ' : 'Hồ sơ gốc · ') + item.name;
      preview.hidden = item.status !== 'document_only';
      if (!preview.hidden) { preview.href = item.preview_url; preview.textContent = 'Xem bản vẽ ' + item.name; }
      legendImage.alt = 'Chú giải gốc · ' + item.name;
      metadata.textContent = themeLabel(item)
        + ' · ' + (item.source === 'guland' ? 'Tham khảo' : item.source === 'gis' ? 'GIS' : 'Bản vẽ / PDF') + ' · ' + item.decision + (manifest
        ? item.theme === 'administrative' ? ' · Ranh theo tọa độ nguồn; chỉ tham khảo.' : manifest.alignment_method === 'official_coordinates' ? ' · Căn chỉnh theo tọa độ gốc của cổng GIS.'
        : manifest.alignment_method === 'source_xyz' ? ' · Theo lưới ô bản đồ của nguồn.'
        : ' · Kiểm tra căn chỉnh: sai số lớn nhất ' + manifest.check_max_m + ' m tại ' + manifest.check_count + ' điểm thử.'
        : ' · ' + item.message)
        + (manifest && item.source === 'gis' && manifest.captured_on ? ' · Bản lưu GIS ngày ' + manifest.captured_on + '.' : '');
      notice.textContent = manifest ? manifest.notice : item.notice
        || 'Hồ sơ công bố 2022–2023. Chưa xác minh hiệu lực hiện tại và căn chỉnh tọa độ để chồng lên Maps.';
      if (legend.open && manifest && manifest.legend_available !== false) legendImage.src = assetBase + manifest.id + '/legend.webp';
    }
    selector.addEventListener('change', function () {
      var item = catalog.find(function (entry) { return entry.id === selector.value; });
      if (item && !disposed) chooseLayer(item);
    });

    env.fetch(published ? published.catalogUrl : '/local-planning/catalog.json', { signal: controller.signal, cache: published ? 'default' : 'no-store' })
      .then(function (response) {
        if (!response.ok) throw new Error('manifest unavailable');
        return response.json();
      }).then(function (data) {
        if (disposed) return;
        if (!validCatalog(data,env.RADAR_LANDUSE_SOURCE_RULES)) throw new Error('invalid catalog');
        catalog = data.layers.map(function (item) {
          var city = item.city || 'Bến Cát';
          return Object.assign({}, item, {
            city: city, theme: item.theme || 'partition', scope: item.scope || 'area',
            area_id: item.area_id || city + '|' + item.name,
            source: item.source || (item.manifest && item.manifest.source_kind === 'official_gis' ? 'gis' : 'document')
          });
        });
        catalog.forEach(function (item) {
          var suffix = item.status === 'overlay_ready' ? String(item.manifest.source_kind || '').indexOf('primary_consultant') === 0 ? ' · Nguồn tư vấn' : ' · Lớp phủ'
            : item.status === 'document_only' ? ' · Bản vẽ' : ' · Chưa có lớp';
          node('option', selector, item.name + ' · ' + themeLabel(item)
            + ' · ' + (item.source === 'guland' ? 'Tham khảo' : item.source === 'gis' ? 'GIS' : 'PDF/ảnh') + suffix).value = item.id;
        });
        selector.disabled = false;
        themes.forEach(function (theme) { theme.source.disabled = false; });
        var requested = themes.find(function (theme) { return theme.id === options.initialTheme; });
        if (requested) { requested.toggle.checked = true; activeTheme = requested; }
        var ready = wantedItems(true), center = typeof map.getCenter === 'function' ? map.getCenter() : null;
        var initial = ready.find(function (item) { return options.initialRegion && item.area_id === options.initialRegion; })
          || ready.find(function (item) {
            return center && (item.manifest.coverage_windows || [item.manifest.bounds]).some(function (b) {
              return b[0][0] <= center.lat && center.lat <= b[1][0] && b[0][1] <= center.lng && center.lng <= b[1][1];
            });
          }) || ready[0] || catalog[0];
        chooseLayer(initial); updateLayers();
      }).catch(function (error) {
        if (!disposed && error.name !== 'AbortError') {
          status.textContent = 'Chưa tải được dữ liệu quy hoạch. Đóng và mở lại Maps để thử.';
        }
      });

    function dispose() {
      if (disposed) return;
      disposed = true;
      controller.abort();
      if(doc.removeEventListener)doc.removeEventListener('pointerdown',outsidePointer,true);
      if (disposeMeasure) disposeMeasure();
      if (disposeLegend) disposeLegend();
      if (disposeParcels) disposeParcels();
      map.off('moveend', viewportChanged);
      map.off('unload', dispose);
      Array.from(overlays.keys()).forEach(removeOverlay);
      ui.root.remove();
    }
    map.on('unload', dispose);
    return dispose;
  }

  return { mount: mount, validManifest: validManifest, validCatalog: validCatalog, opacity: opacity, dismissOutsidePanels: dismissOutsidePanels,
    referenceClipPath: referenceClipPath, referenceAnnotations: referenceAnnotations, referenceBranding: referenceBranding };
});
