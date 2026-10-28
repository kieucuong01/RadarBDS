(function (root, factory) {
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.RadarPlanningOverlay = api;
})(typeof window !== 'undefined' ? window : null, function () {
  'use strict';

  function validManifest(data) {
    if (!data || !/^[a-z0-9-]+$/.test(data.id || '') || ['local_experiment','reference_overlay'].indexOf(data.status) < 0) return false;
    if (data.render_mode !== undefined && (data.render_mode !== 'xyz'
        || !/^\/(local-planning|api\/planning)\/gis-tiles\/(partition|urban_general)\/\{z\}\/\{x\}\/\{y\}\.png$/.test(data.tile_template || '')
        || data.tile_size !== 256 || data.min_zoom !== 8 || data.max_zoom !== 23)) return false;
    var b = data.bounds;
    var expanded = data.render_mode === 'xyz' && /\/partition\//.test(data.tile_template);
    return Array.isArray(b) && b.length === 2 && b.every(function (point) {
      return Array.isArray(point) && point.length === 2 && point.every(Number.isFinite);
    }) && b[0][0] >= (expanded ? 8.5 : 10.75) && b[1][0] <= 11.65 && b[0][0] < b[1][0]
      && b[0][1] >= 106.25 && b[1][1] <= (expanded ? 107.65 : 107.10) && b[0][1] < b[1][1]
      && typeof data.title === 'string' && typeof data.notice === 'string';
  }

  function opacity(value) {
    var number = Number(value);
    return Number.isFinite(number) ? Math.max(0, Math.min(100, number)) / 100 : 0.35;
  }

  function themeLabel(item) {
    var scale = item.manifest && item.manifest.map_scale;
    return (item.theme === 'urban_general' ? 'Quy hoạch chung' : 'Phân khu') + ' · ' + (Number.isInteger(scale) && scale > 0
      ? '1/' + scale.toLocaleString('vi-VN') : 'Chưa xác minh tỷ lệ');
  }

  function validCatalog(data) {
    if (!data || !Array.isArray(data.layers) || !data.layers.length || data.layers.length > 64) return false;
    var ids = new Set();
    return data.layers.every(function (item) {
      if (!item || !/^[a-z0-9-]+$/.test(item.id || '') || ids.has(item.id)) return false;
      ids.add(item.id);
      if (item.city !== undefined && (typeof item.city !== 'string' || !item.city.trim() || item.city.length > 80)) return false;
      if (item.theme !== undefined && ['partition', 'urban_general'].indexOf(item.theme) < 0) return false;
      if (item.source !== undefined && ['gis', 'document'].indexOf(item.source) < 0) return false;
      if (item.scope !== undefined && ['area', 'city', 'region'].indexOf(item.scope) < 0) return false;
      if (item.inspection_only !== undefined && typeof item.inspection_only !== 'boolean') return false;
      if (typeof item.name !== 'string' || typeof item.decision !== 'string'
          || !/^https:\/\/(drive\.google\.com\/|bencat\.binhduong\.gov\.vn\/|bencat-hochiminhcity\.gov\.vn\/|gisxaydung\.tphcm\.gov\.vn\/|government\.cdn\.myaloha\.com\.vn\/|(?:www\.)?aapbinhduong\.com\/)/.test(item.source_url || '')) return false;
      if (item.status === 'overlay_ready') return validManifest(item.manifest) && item.manifest.id === item.id;
      if (item.status === 'document_only') return item.preview_url === '/local-planning/' + item.id + '/preview.webp';
      return ['source_unavailable', 'source_missing_map', 'artifact_unavailable'].indexOf(item.status) >= 0;
    });
  }

  function mount(map, L, environment) {
    var env = environment || window;
    var doc = env.document;
    var published = env.RADAR_PLANNING_CONFIG;
    var assetBase = published ? published.assetBase : '/local-planning/';
    var controller = new env.AbortController();
    var disposed = false;
    var manifest = null;
    var catalog = [];
    var themes = [
      {id: 'partition', name: 'quy hoạch phân khu', title: 'Quy hoạch phân khu'},
      {id: 'urban_general', name: 'quy hoạch chung đô thị', title: 'Quy hoạch chung đô thị'}
    ];
    var overlays = new Map(), failedIds = new Set();
    var pane = map.createPane('planningPilot');
    pane.style.zIndex = '350';
    pane.style.pointerEvents = 'none';

    function node(tag, parent, text) {
      var item = doc.createElement(tag);
      if (text) item.textContent = text;
      if (parent) parent.appendChild(item);
      return item;
    }
    var ui = {root: node('div'), panels: []};
    ui.root.className = 'planning-map-ui';
    map.getContainer().appendChild(ui.root);
    var toolbar = node('div', ui.root); toolbar.className = 'planning-map-toolbar';
    toolbar.setAttribute('aria-label', 'Công cụ quy hoạch');
    ui.areaSlot = node('div', toolbar); ui.parcelSlot = node('div', toolbar);
    var box = node('details', toolbar);
    box.className = 'planning-overlay-control planning-map-popover';
    ui.panels.push(box);
    box.addEventListener('toggle', function () {
      if (box.open) ui.panels.forEach(function (p) { if (p !== box) p.open = false; });
    });
    node('summary', box, 'Lớp bản đồ');
    var body = node('div', box);
    body.className = 'planning-overlay-body';
    node('span', body, published ? 'DỮ LIỆU QUY HOẠCH THAM KHẢO' : 'THỬ NGHIỆM LOCAL').className = 'planning-overlay-badge';
    var fit = node('button', body, 'Xem vùng có quy hoạch');
    fit.type = 'button'; fit.disabled = true;
    var activeTheme = themes[0];
    var dock = node('div', ui.root); dock.className = 'planning-layer-dock';
    ui.dock = dock;
    dock.setAttribute('aria-label', 'Bật tắt nhanh quy hoạch');
    var rail = node('div', ui.root); rail.className = 'planning-opacity-control';
    var railType = node('select', rail); railType.setAttribute('aria-label', 'Lớp điều chỉnh độ hiển thị');
    themes.forEach(function (theme) { theme.railOption = node('option', railType, theme.id === 'partition' ? 'Phân khu' : 'QH chung'); theme.railOption.value = theme.id; });
    railType.value = activeTheme.id;
    var increase = node('button', rail, '+'); increase.type = 'button'; increase.setAttribute('aria-label', 'Tăng độ hiển thị 10 phần trăm');
    var railValue = node('output', rail, '35%');
    var railSlider = node('input', rail); railSlider.type = 'range'; railSlider.min = '0'; railSlider.max = '100'; railSlider.value = '35'; railSlider.step = '1';
    railSlider.disabled = increase.disabled = true;
    railSlider.setAttribute('aria-label', 'Độ hiển thị lớp đang chọn');
    var decrease = node('button', rail, '−'); decrease.type = 'button'; decrease.setAttribute('aria-label', 'Giảm độ hiển thị 10 phần trăm');
    decrease.disabled = true;
    function syncQuickControls() {
      if (!activeTheme.toggle.checked) activeTheme = themes.find(function (t) { return t.toggle.checked; }) || activeTheme;
      railType.value = activeTheme.id;
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
      theme.quick = node('button', dock, theme.id === 'partition' ? 'Phân khu' : 'QH chung');
      theme.quick.type = 'button'; theme.quick.className = 'planning-layer-chip'; theme.quick.disabled = true;
      theme.quick.setAttribute('aria-label', 'Bật/tắt ' + theme.name);
      theme.quick.setAttribute('aria-pressed', 'false');
      var card = node('fieldset', body);
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
      node('option', theme.source, 'GIS · Cổng dữ liệu').value = 'gis';
      node('option', theme.source, 'Bản vẽ / PDF').value = 'document';
      theme.source.value = 'gis';
      var opacityLabel = node('label', card, 'Độ hiển thị ');
      theme.value = node('output', opacityLabel, '35%');
      theme.slider = node('input', opacityLabel); theme.slider.type = 'range';
      theme.slider.min = '0'; theme.slider.max = '100'; theme.slider.step = '1'; theme.slider.value = '35';
      theme.slider.disabled = true;
      theme.slider.setAttribute('aria-label', 'Độ hiển thị ' + theme.name);
      theme.status = node('p', card, 'Đang kiểm tra nguồn dữ liệu…');
      theme.status.className = 'planning-overlay-metadata';
      function changeTheme() {
        if (disposed) return;
        if (theme.toggle.checked) {
          activeTheme = theme;
          catalog.forEach(function (item) { if (item.theme === theme.id) failedIds.delete(item.id); });
        }
        updateLayers();
      }
      theme.toggle.addEventListener('change', changeTheme);
      theme.quick.addEventListener('click', function () { theme.toggle.checked = !theme.toggle.checked; changeTheme(); });
      theme.source.addEventListener('change', function () {
        if (disposed) return;
        failedIds.clear(); updateLayers();
        var records = catalog.filter(function (entry) { return entry.theme === theme.id && entry.source === theme.source.value; });
        var item = records.find(function (entry) { return entry.status === 'overlay_ready' && !entry.inspection_only; }) || records[0];
        if (item) chooseLayer(item);
      });
      theme.slider.addEventListener('input', function () {
        setOpacity(theme, theme.slider.value);
      });
    });
    var status = node('p', body, 'Đang tải thông tin lớp bản đồ…');
    status.className = 'planning-overlay-status';
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
    function keydown(event) {
      event.stopPropagation();
      if (event.key === 'Escape') ui.panels.forEach(function (p) { p.open = false; });
    }
    ui.root.addEventListener('keydown', keydown);

    function wantedItems(readyOnly) {
      return catalog.filter(function (item) {
        var theme = themes.find(function (entry) { return entry.id === item.theme; });
        return theme.toggle.checked && item.source === theme.source.value
          && (!readyOnly || (item.status === 'overlay_ready' && !item.inspection_only));
      });
    }

    function reportCoverage() {
      if (disposed) return;
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
      if (errors.length) status.textContent += ' Không tải được: ' + errors.map(function (item) { return item.name; }).join(', ')
        + '. Tắt/bật loại bản đồ để thử lại; Maps vẫn hoạt động.';
      if (entries.some(function (entry) { return entry.tileError; })) status.textContent += ' Một số ô GIS chưa tải được; thử thu phóng hoặc chuyển vùng để tải lại.';
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

    function syncOverlays() {
      if (disposed) return;
      var viewport = map.getBounds();
      var near = typeof viewport.pad === 'function' ? viewport.pad(0.05) : viewport;
      var desired = wantedItems(true).filter(function (item) { return near.intersects(item.manifest.bounds); });
      var desiredIds = new Set(desired.map(function (item) { return item.id; }));
      Array.from(overlays.keys()).forEach(function (id) {
        if (!desiredIds.has(id)) removeOverlay(id);
      });
      catalog.forEach(function (item, index) {
        if (!desiredIds.has(item.id) || overlays.has(item.id) || failedIds.has(item.id)) return;
        var data = item.manifest;
        var theme = themes.find(function (entry) { return entry.id === item.theme; });
        var layerOptions = {
          pane: 'planningPilot', opacity: opacity(theme.slider.value), interactive: false,
          zIndex: (item.theme === 'partition' ? 100 : 200) + index,
          // Leaflet deduplicates identical provider credits across selected wards.
          attribution: data.source_kind === 'official_gis'
            ? 'Sở Quy hoạch – Kiến trúc TP.HCM · GIS công khai'
            : data.attribution || item.city + ' · ' + item.name + ' · bản thử căn chỉnh'
        };
        var tiled = data.render_mode === 'xyz';
        var layer = tiled ? L.tileLayer(data.tile_template, Object.assign(layerOptions, {
          bounds:data.bounds, tileSize:256, minZoom:8, maxZoom:23, maxNativeZoom:23,
          updateWhenIdle:true, updateWhenZooming:false, keepBuffer:1
        })) : L.imageOverlay(assetBase + item.id + '/overlay.webp', data.bounds, layerOptions);
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

    function updateLayers() {
      themes.forEach(function (theme) {
        var all = catalog.filter(function (item) { return item.theme === theme.id; });
        var records = all.filter(function (item) { return item.source === theme.source.value; });
        var ready = records.filter(function (item) { return item.status === 'overlay_ready' && !item.inspection_only; });
        theme.toggle.disabled = !ready.length;
        var expected = new Set(all.map(function (item) { return item.city + '|' + item.area_id; }));
        var covered = new Set(ready.map(function (item) { return item.city + '|' + item.area_id; }));
        var missing = expected.size - covered.size;
        var native = ready.some(function (item) { return item.manifest.render_mode === 'xyz'; });
        theme.status.textContent = native ? 'Ô GIS gốc theo từng mức zoom · ' + ready.find(function (item) { return item.manifest.render_mode === 'xyz'; }).city + '. Vùng trống cần kiểm tra thêm nguồn.' : ready.length + ' lớp sẵn sàng' + (missing && ready.length
          ? ' · ' + missing + ' khu vực chưa có nguồn này.' : '.')
          + (!ready.length
            ? ' ' + ((records[0] && records[0].message) || 'Nguồn này chưa có lớp phủ được xác minh.') : '');
      });
      fit.disabled = !wantedItems(true).length;
      syncOverlays();
    }

    fit.addEventListener('click', function () {
      if (disposed || !wantedItems(true).length) return;
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
      source.textContent = (manifest && manifest.source_kind === 'official_gis' ? 'Cổng GIS và chú giải · ' : 'Hồ sơ gốc · ') + item.name;
      preview.hidden = item.status !== 'document_only';
      if (!preview.hidden) { preview.href = item.preview_url; preview.textContent = 'Xem bản vẽ ' + item.name; }
      legendImage.alt = 'Chú giải gốc · ' + item.name;
      metadata.textContent = themeLabel(item)
        + ' · ' + (item.source === 'gis' ? 'GIS' : 'Bản vẽ / PDF') + ' · ' + item.decision + (manifest
        ? manifest.alignment_method === 'official_coordinates' ? ' · Căn chỉnh theo tọa độ gốc của cổng GIS.'
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
        if (!validCatalog(data)) throw new Error('invalid catalog');
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
            + ' · ' + (item.source === 'gis' ? 'GIS' : 'PDF/ảnh') + suffix).value = item.id;
        });
        selector.disabled = false;
        themes.forEach(function (theme) { theme.source.disabled = false; });
        var initial = wantedItems(true)[0] || catalog[0];
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
      if (disposeParcels) disposeParcels();
      map.off('moveend', viewportChanged);
      map.off('unload', dispose);
      Array.from(overlays.keys()).forEach(removeOverlay);
      ui.root.remove();
    }
    map.on('unload', dispose);
    return dispose;
  }

  return { mount: mount, validManifest: validManifest, validCatalog: validCatalog, opacity: opacity };
});
