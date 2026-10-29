(function (root, factory) {
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.RadarPlanningParcels = api;
})(typeof window !== 'undefined' ? window : null, function () {
  'use strict';
  function mount(map, L, env, sharedUI) {
    var doc = env.document, disposed = false, config, navigationAreas, timer, viewRequest, selectionRequest;
    var navigationRegions = Array.isArray(env.RADAR_PLANNING_REGIONS) ? env.RADAR_PLANNING_REGIONS : [];
    var apiBase = env.RADAR_PLANNING_CONFIG && env.RADAR_PLANNING_CONFIG.parcelBase || '/local-planning/parcels';
    var viewSeq = 0, selectionSeq = 0, searchSeq = 0, navigationSeq = 0, layer, highlight, searchRequest, navigationRequest;
    var lifetime = new env.AbortController();
    function node(tag, parent, text) {
      var element = doc.createElement(tag);
      if (text !== undefined) element.textContent = text;
      if (parent) parent.appendChild(element);
      return element;
    }
    function format(value) {
      return typeof value === 'number' && Number.isFinite(value)
        ? value.toLocaleString('vi-VN', {maximumFractionDigits: 2}) : String(value == null || value === '' ? 'Chưa có dữ liệu' : value);
    }
    function area(value) { return typeof value === 'number' && Number.isFinite(value) ? format(value) + ' m²' : 'Chưa có dữ liệu'; }
    function row(parent, label, value) {
      var item = node('div', parent); item.className = 'parcel-info-row';
      node('dt', item, label); node('dd', item, format(value));
    }
    var pane = map.createPane('planningParcels'); pane.style.zIndex = '410';
    var selectedPane = map.createPane('planningParcelSelected'); selectedPane.style.zIndex = '420';
    selectedPane.style.pointerEvents = 'none';
    var ui = sharedUI || {root: node('div'), panels: []};
    if (!sharedUI) {
      ui.root.className = 'planning-map-ui'; map.getContainer().appendChild(ui.root);
      var toolbar = node('div', ui.root); toolbar.className = 'planning-map-toolbar';
      ui.areaSlot = node('div', toolbar); ui.parcelSlot = node('div', toolbar);
      ui.layerBody = node('div', ui.root); ui.layerBody.className = 'planning-parcel-standalone-settings';
    }
    function popover(slot, title, className) {
      var panel = node('details', slot); panel.className = 'planning-map-popover ' + className;
      node('summary', panel, title); ui.panels.push(panel);
      panel.addEventListener('toggle', function () {
        if (panel.open) ui.panels.forEach(function (p) { if (p !== panel) p.open = false; });
      });
      return panel;
    }
    function field(tag, parent, title) {
      var label = node('label', parent, title), input = node(tag, label);
      input.setAttribute('aria-label', title); return input;
    }
    var areaMenu = popover(ui.areaSlot, 'Khu vực', 'planning-area-menu');
    var areaForm = node('form', areaMenu); areaForm.className = 'planning-map-form';
    node('h3', areaForm, 'Đến khu vực');
    var citySelect = field('select', areaForm, 'Thành phố trên bản đồ');
    var wardSelect = field('select', areaForm, 'Phường trên bản đồ');
    var areaSubmit = node('button', areaForm, 'Xem khu vực'); areaSubmit.type = 'submit'; areaSubmit.disabled = true;
    var areaStatus = node('p', areaForm, 'Địa bàn theo dữ liệu cũ. Kéo bản đồ để xem thêm vùng bên cạnh.'); areaStatus.setAttribute('role', 'status');
    var searchMenu = popover(ui.parcelSlot, 'Tờ/thửa', 'planning-parcel-search');
    var searchForm = node('form', searchMenu); searchForm.className = 'planning-map-form'; searchForm.setAttribute('aria-label', 'Tra tờ thửa');
    node('h3', searchForm, 'Tra tờ / thửa');
    var searchArea = field('select', searchForm, 'Phường tra tờ thửa');
    var inputRow = node('div', searchForm); inputRow.className = 'planning-parcel-inputs';
    var sheetInput = field('input', inputRow, 'Số tờ bản đồ');
    var parcelInput = field('input', inputRow, 'Số thửa đất');
    [sheetInput,parcelInput].forEach(function (input) { input.type = 'text'; input.inputMode = 'numeric'; input.maxLength = 32; input.required = true; input.autocomplete = 'off'; });
    var searchSubmit = node('button', searchForm, 'Tìm thửa đất'); searchSubmit.type = 'submit'; searchSubmit.disabled = true;
    var searchStatus = node('p', searchForm, 'Nhập đúng số tờ, số thửa và phường theo dữ liệu GIS.'); searchStatus.setAttribute('role', 'status');
    var results = node('div', searchForm); results.className = 'planning-parcel-results';
    var settings = node('div', ui.layerBody); settings.className = 'planning-parcel-settings';
    var label = node('label', settings); label.className = 'planning-parcel-toggle';
    var toggle = node('input', label); toggle.type = 'checkbox'; toggle.checked = true;
    toggle.setAttribute('aria-label', 'Bật ranh thửa đất');
    node('span', label, 'Hiển thị ranh thửa đất');
    var quickBoundaries = ui.dock ? node('button', ui.dock, 'Ranh thửa') : null;
    if (quickBoundaries) {
      ui.dock.prepend(quickBoundaries);
      quickBoundaries.type = 'button'; quickBoundaries.className = 'planning-layer-chip'; quickBoundaries.disabled = true;
      quickBoundaries.setAttribute('aria-label', 'Bật/tắt ranh thửa'); quickBoundaries.setAttribute('aria-pressed', 'true');
      quickBoundaries.title = 'Ranh thửa hiển thị khi phóng gần';
    }
    var buttons = node('div', settings); buttons.className = 'planning-parcel-actions';
    var example = node('button', buttons, 'Xem thửa mẫu'); example.type = 'button'; example.disabled = true;
    var status = node('p', settings, 'Đang tải dữ liệu ranh thửa…'); status.setAttribute('role', 'status');
    var badge = node('p', settings); badge.className = 'planning-parcel-notice';
    var box = node('section', ui.root); box.className = 'planning-parcel-card'; box.hidden = true;
    box.setAttribute('aria-label', 'Thông tin quy hoạch thửa đất');
    var close = node('button', box, '×'); close.type = 'button'; close.className = 'planning-parcel-close'; close.setAttribute('aria-label', 'Đóng thông tin thửa');
    var body = node('div', box); body.className = 'planning-parcel-body';
    var info = node('section', body); info.className = 'planning-parcel-info';
    info.setAttribute('aria-live', 'polite');
    var source = node('a', body, 'Nguồn: Cổng GIS TP.HCM');
    source.href = 'https://gisxaydung.tphcm.gov.vn/tracuuttqh'; source.target = '_blank'; source.rel = 'noopener noreferrer';
    node('p', body, 'Dữ liệu GIS tham khảo, chưa xác minh hiệu lực hoặc độ chính xác địa chính; không thay thế xác nhận quy hoạch.').className = 'planning-parcel-notice';
    L.DomEvent.disableClickPropagation(ui.root); L.DomEvent.disableScrollPropagation(ui.root);
    function remove(which) { if (which) map.removeLayer(which); }
    function clearInfo() { info.replaceChildren(); }
    function showParcel(feature) {
      clearInfo();
      node('h3', info, 'Thửa ' + format(feature.properties.parcel) + ' · Tờ ' + format(feature.properties.sheet));
      node('strong', info, area(feature.properties.area)).className = 'planning-parcel-area';
      node('p', info, (feature.properties.ward || config.ward) + ' · ' + (feature.properties.city || config.city) + ' (đơn vị cũ)').className = 'planning-parcel-location';
    }
    function closeInfo() {
      ++selectionSeq; if (selectionRequest) selectionRequest.abort();
      ++searchSeq; if (searchRequest) searchRequest.abort(); searchSubmit.disabled = !config;
      box.hidden = true; remove(highlight); highlight = null;
      var container = map.getContainer(); if (container.focus) container.focus({preventScroll:true});
    }
    close.addEventListener('click', closeInfo);
    box.addEventListener('keydown', function (event) { if (event.key === 'Escape') closeInfo(); });
    function select(feature) {
      if (disposed || !toggle.checked) return;
      var mapClasses = map.getContainer().classList;
      if (mapClasses && mapClasses.contains('planning-is-drawing')) return;
      ++searchSeq; if (searchRequest) searchRequest.abort(); searchSubmit.disabled = !config;
      if (selectionRequest) selectionRequest.abort();
      var sequence = ++selectionSeq;
      selectionRequest = new env.AbortController();
      remove(highlight);
      highlight = L.geoJSON(feature, {pane: 'planningParcelSelected', interactive: false,
        style: {color: '#facc15', weight: 3, fillColor: '#facc15', fillOpacity: 0.18}}).addTo(map);
      box.hidden = false;
      if (close.focus) close.focus({preventScroll:true});
      ui.panels.forEach(function (p) { p.open = false; });
      if (env.matchMedia('(max-width: 1100px)').matches) {
        map.fitBounds(highlight.getBounds(), {maxZoom: map.getZoom(), animate: false,
          paddingTopLeft: [30, 130], paddingBottomRight: [30, Math.min(440, env.innerHeight * 0.5)]});
      } else {
        map.fitBounds(highlight.getBounds(), {maxZoom: map.getZoom(), animate: false,
          paddingTopLeft: [40, 100], paddingBottomRight: [544, 40]});
      }
      showParcel(feature);
      var message = node('p', info, 'Đang tra cứu thông tin thửa từ GIS…');
      var areaQuery = feature.properties.area_id ? '?area=' + encodeURIComponent(feature.properties.area_id) : '';
      env.fetch(apiBase + '/' + feature.id + '/planning.json' + areaQuery, {signal: selectionRequest.signal, cache: 'no-store'})
        .then(function (response) { if (!response.ok) throw new Error('GIS unavailable'); return response.json(); })
        .then(function (data) {
          if (disposed || sequence !== selectionSeq) return;
          if (!data || !data.parcel || data.parcel.id !== feature.id || !Array.isArray(data.plans)) throw new Error('Invalid GIS response');
          message.remove();
          if (!data.plans.length) node('p', info, 'GIS chưa trả về đồ án giao thửa này. Chưa thể kết luận thửa không có quy hoạch.');
          data.plans.forEach(function (plan) {
            var section = node('section', info); section.className = 'parcel-planning-plan';
            node('h4', section, plan.type || 'Đồ án quy hoạch');
            node('p', section, plan.name || 'Chưa có tên đồ án').className = 'parcel-plan-name';
            (plan.zones || []).forEach(function (zone) {
              var card = node('details', section); card.className = 'parcel-planning-zone';
              var summary = node('summary', card);
              node('span', summary, zone.maMucDichSuDungDat || '—').className = 'parcel-zone-code';
              node('strong', summary, area(zone.dienTich)).className = 'parcel-zone-area';
              node('span', summary, zone.mucDichSuDungDat || 'Chưa có chức năng sử dụng đất').className = 'parcel-zone-name';
              var zoneFields = node('dl', card);
              if (zone.kyHieuLoDat) row(zoneFields, 'Ký hiệu lô', zone.kyHieuLoDat);
              row(zoneFields, 'Tầng cao', zone.tangCaoXayDung);
              row(zoneFields, 'Mật độ xây dựng', zone.matDoXayDungTrungBinh);
              row(zoneFields, 'Hệ số sử dụng đất', zone.heSoSuDungDat);
            });
            var metadata = node('details', section); metadata.className = 'parcel-plan-metadata';
            node('summary', metadata, 'Hồ sơ GIS' + (plan.scale ? ' · ' + plan.scale : ''));
            var fields = node('dl', metadata);
            row(fields, 'Quyết định theo GIS', plan.decision);
            row(fields, 'Ngày ký theo GIS', plan.date); row(fields, 'Tỷ lệ theo GIS', plan.scale);
            if (plan.amendment) row(fields, 'Điều chỉnh theo GIS', plan.amendment + ' · ' + (plan.amendment_date || ''));
            row(fields, 'Diện tích giao GIS', area(plan.intersection_area));
          });
          node('p', info, 'Diện tích giao do GIS tính, có thể khác diện tích thửa. Chỉ tiêu được giữ nguyên giá trị nguồn.').className = 'planning-parcel-notice';
          node('p', info, 'Tra cứu: ' + new Date(data.queried_at).toLocaleString('vi-VN'));
        }).catch(function (error) {
          if (!disposed && sequence === selectionSeq && error.name !== 'AbortError') {
            message.textContent = 'Chưa lấy được thông tin GIS. Chưa thể kết luận quy hoạch thửa này; bấm lại thửa để thử lại.';
            var retry = node('button', info, 'Thử lại tra cứu'); retry.type = 'button';
            retry.addEventListener('click', function () { select(feature); });
          }
        });
    }
    function loadViewport(retryAttempt) {
      if (disposed || !config) return;
      var attempt = Number.isInteger(retryAttempt) ? retryAttempt : 0;
      if (viewRequest) viewRequest.abort();
      var sequence = ++viewSeq;
      var visible = config.coverage_bounds ? map.getBounds().intersects(config.coverage_bounds)
        : config.areas.some(function (a) { return map.getBounds().intersects(a.bounds); });
      if (!toggle.checked || map.getZoom() < config.min_zoom || !visible) {
        remove(layer); layer = null;
        status.textContent = !toggle.checked ? 'Đang tắt ranh thửa đất.' : !visible
          ? 'Chưa có ranh thửa cho khu vực này.' : 'Phóng to để xem ranh thửa; hoặc chọn “Xem thửa mẫu”.';
        return;
      }
      var b = map.getBounds(), bbox = [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()].join(',');
      viewRequest = new env.AbortController(); status.textContent = 'Đang tải ranh trong vùng xem…';
      env.fetch(apiBase + '/viewport.json?bbox=' + encodeURIComponent(bbox), {signal: viewRequest.signal, cache: 'no-store'})
        .then(function (response) {
          if (!response.ok) { var error = new Error('Parcel data unavailable'); error.status = response.status; throw error; }
          return response.json();
        })
        .then(function (data) {
          if (disposed || sequence !== viewSeq) return;
          if (data.type !== 'FeatureCollection' || !Array.isArray(data.features) || data.features.length > 1500) throw new Error('Invalid parcel data');
          var previous = layer;
          layer = L.geoJSON(data, {pane: 'planningParcels', style: {color: '#334155', weight: 0.7, opacity: 0.28, fillOpacity: 0},
            onEachFeature: function (feature, polygon) {
              polygon.bindTooltip('Tờ ' + format(feature.properties.sheet) + ' · Thửa ' + format(feature.properties.parcel));
              polygon.on('click', function (event) { L.DomEvent.stopPropagation(event); select(feature); });
            }}).addTo(map);
          remove(previous);
          status.textContent = (data.features.length ? data.features.length + ' ranh thửa trong vùng xem'
            : 'GIS chưa trả ranh thửa trong vùng xem này.')
            + (data.truncated ? ' Vùng quá dày; phóng to để xem đầy đủ.' : '')
            + (data.excluded_count ? ' Có ' + data.excluded_count + ' ranh lỗi nguồn được tạm loại.' : '');
        }).catch(function (error) {
          if (disposed || sequence !== viewSeq || error.name === 'AbortError') return;
          if (error.status === 503 && attempt < 2) {
            status.textContent = 'GIS đang bận; đang thử tải lại ranh…';
            env.clearTimeout(timer);
            timer = env.setTimeout(function () { loadViewport(attempt+1); }, (attempt+1)*1000);
          } else status.textContent = 'Chưa tải được ranh. Thử phóng to hoặc di chuyển bản đồ.';
        });
    }
    function move() {
      if (viewRequest) viewRequest.abort();
      ++viewSeq;
      env.clearTimeout(timer); timer = env.setTimeout(loadViewport, 180);
    }
    function closestArea(areas) {
      var center = map.getCenter();
      return (areas || config.areas).slice().sort(function (a, b) {
        function distance(value) {
          var lat = value.center ? value.center[0] : (value.bounds[0][0]+value.bounds[1][0])/2;
          var lng = value.center ? value.center[1] : (value.bounds[0][1]+value.bounds[1][1])/2;
          return Math.pow(center.lat-lat, 2) + Math.pow(center.lng-lng, 2);
        }
        return distance(a)-distance(b);
      })[0];
    }
    function fillWards(selected) {
      var region = navigationRegions.find(function (r) { return r.id === citySelect.value; });
      wardSelect.disabled = Boolean(region);
      wardSelect.replaceChildren(); node('option', wardSelect, region ? 'Toàn khu vực' : 'Toàn thành phố').value = '';
      navigationAreas.filter(function (a) { return a.city === citySelect.value; }).forEach(function (a) {
        node('option', wardSelect, a.ward).value = a.area_id || a.code;
      });
      wardSelect.value = selected || '';
    }
    citySelect.addEventListener('change', function () {
      if (!config) return;
      ++navigationSeq; if (navigationRequest) navigationRequest.abort(); areaSubmit.disabled = false;
      fillWards();
    });
    wardSelect.addEventListener('change', function () {
      ++navigationSeq; if (navigationRequest) navigationRequest.abort(); areaSubmit.disabled = !config;
    });
    areaForm.addEventListener('submit', function (event) {
      event.preventDefault(); if (!config || disposed) return;
      if (navigationRequest) navigationRequest.abort();
      var seq = ++navigationSeq, selected = navigationAreas.find(function (a) { return (a.area_id || a.code) === wardSelect.value; });
      var region = navigationRegions.find(function (r) { return r.id === citySelect.value; });
      if (region) {
        closeInfo();
        map.fitBounds(region.bounds, {maxZoom: region.max_zoom, padding: [24,24], animate: false});
        areaMenu.open = false;
        areaStatus.textContent = region.notice || 'Đã đến ' + region.name + '. Bật Phân khu để xem quy hoạch GIS.';
        return;
      }
      var cityAreas = navigationAreas.filter(function (a) { return a.city === citySelect.value; });
      var district = cityAreas.length ? Number(cityAreas[0].district) : 0;
      if (config.live_expanded && cityAreas.length && !(district >= 718 && district <= 726)) {
        var windows = selected ? [selected] : cityAreas;
        var bounds = [[Math.min.apply(null, windows.map(function (a) { return a.bounds[0][0]; })),
          Math.min.apply(null, windows.map(function (a) { return a.bounds[0][1]; }))],
          [Math.max.apply(null, windows.map(function (a) { return a.bounds[1][0]; })),
          Math.max.apply(null, windows.map(function (a) { return a.bounds[1][1]; }))]];
        closeInfo();
        map.fitBounds(bounds, {maxZoom: selected ? 15 : 13, padding: [24,24], animate: false});
        areaMenu.open = false;
        areaStatus.textContent = 'Đã đến ' + (selected ? selected.ward + ' · ' : '') + citySelect.value + '. Phóng gần để xem ranh GIS.';
        return;
      }
      var query = new URLSearchParams({city: citySelect.value}); if (selected) query.set('ward', selected.ward);
      navigationRequest = new env.AbortController(); areaSubmit.disabled = true;
      areaStatus.textContent = 'Đang mở khu vực…'; closeInfo();
      env.fetch('/api/map-initial-bounds?' + query.toString(), {signal: navigationRequest.signal})
        .then(function (response) { if (!response.ok) throw new Error('Area unavailable'); return response.json(); })
        .then(function (data) {
          if (disposed || seq !== navigationSeq) return;
          if (!Array.isArray(data.bounds) || data.bounds.length !== 2) throw new Error('Invalid area');
          map.fitBounds(data.bounds, {maxZoom: selected ? 15 : 13, padding: [24,24], animate: false});
          if (selected && map.getZoom() < 14) map.setZoom(14, {animate: false});
          areaMenu.open = false;
          areaStatus.textContent = 'Đã đến ' + (selected ? selected.ward + ' · ' : '') + citySelect.value + '. Có thể kéo sang vùng lân cận.';
        }).catch(function (error) {
          if (!disposed && seq === navigationSeq && error.name !== 'AbortError') areaStatus.textContent = 'Chưa mở được khu vực. Vui lòng thử lại.';
        }).finally(function () { if (!disposed && seq === navigationSeq) areaSubmit.disabled = false; });
    });
    function focusFeature(feature) {
      toggle.checked = true;
      if (quickBoundaries) quickBoundaries.setAttribute('aria-pressed', 'true');
      map.fitBounds(L.geoJSON(feature).getBounds(), {maxZoom: 19, padding: [70,70], animate: false});
      select(feature);
    }
    function cancelSearch() {
      ++searchSeq; if (searchRequest) searchRequest.abort(); searchSubmit.disabled = !config; results.replaceChildren();
      searchStatus.textContent = 'Nhập đúng số tờ, số thửa và phường theo dữ liệu GIS.';
    }
    function moveStart() {
      if (disposed) return;
      cancelSearch(); ++navigationSeq; if (navigationRequest) navigationRequest.abort(); areaSubmit.disabled = !config;
      if (viewRequest) viewRequest.abort(); ++viewSeq;
    }
    searchArea.addEventListener('change', cancelSearch);
    sheetInput.addEventListener('input', cancelSearch); parcelInput.addEventListener('input', cancelSearch);
    searchForm.addEventListener('submit', function (event) {
      event.preventDefault(); if (disposed || !config) return;
      var sheet = String(sheetInput.value || '').trim(), parcel = String(parcelInput.value || '').trim(), areaId = searchArea.value;
      cancelSearch();
      if (!sheet || !parcel) { searchStatus.textContent = 'Nhập đủ số tờ và số thửa.'; return; }
      var seq = searchSeq; searchRequest = new env.AbortController(); searchSubmit.disabled = true;
      searchStatus.textContent = 'Đang tìm thửa trong dữ liệu GIS…';
      var query = new URLSearchParams({area: areaId, sheet: sheet, parcel: parcel});
      env.fetch(apiBase + '/search.json?' + query.toString(), {signal: searchRequest.signal, cache: 'no-store'})
        .then(function (response) { if (!response.ok) throw new Error('Parcel search failed'); return response.json(); })
        .then(function (data) {
          if (disposed || seq !== searchSeq) return;
          if (data.type !== 'FeatureCollection' || !Array.isArray(data.features) || data.features.length > 20
              || data.features.some(function (f) { return !f.properties || f.properties.area_id !== areaId; })) throw new Error('Invalid search response');
          if (!data.features.length) { searchStatus.textContent = 'Không tìm thấy thửa khớp. Kiểm tra số tờ, số thửa và phường theo dữ liệu cũ.'; return; }
          if (data.matched === 1 && data.features.length === 1) {
            searchStatus.textContent = 'Đã tìm thấy thửa. Bấm từng dòng quy hoạch để xem chỉ tiêu.';
            focusFeature(data.features[0]); return;
          }
          searchStatus.textContent = 'Nguồn có ' + (data.truncated ? 'ít nhất ' : '') + data.matched + ' bản ghi trùng tờ/thửa. Chọn để kiểm tra vị trí.'
            + (data.truncated ? ' Đang hiện 20 kết quả đầu.' : '');
          data.features.forEach(function (feature, index) {
            var button = node('button', results, 'Kết quả ' + (index+1) + ' · ' + area(feature.properties.area)); button.type = 'button';
            button.addEventListener('click', function () { if (!disposed) focusFeature(feature); });
          });
        }).catch(function (error) {
          if (!disposed && seq === searchSeq && error.name !== 'AbortError') searchStatus.textContent = 'Chưa tìm được thửa. Vui lòng thử lại.';
        }).finally(function () { if (!disposed && seq === searchSeq) searchSubmit.disabled = false; });
    });
    function changeBoundaries() {
      if (!toggle.checked) {
        closeInfo(); clearInfo();
      }
      if (quickBoundaries) quickBoundaries.setAttribute('aria-pressed', String(toggle.checked));
      loadViewport();
    }
    toggle.addEventListener('change', changeBoundaries);
    if (quickBoundaries) quickBoundaries.addEventListener('click', function () { toggle.checked = !toggle.checked; changeBoundaries(); });
    example.addEventListener('click', function () {
      if (!config) return;
      var startingView = viewSeq, nearest = closestArea();
      if (config.live_expanded && !config.areas.some(function (a) { return map.getBounds().intersects(a.bounds); })) {
        status.textContent = 'GIS chưa có phường tham chiếu tại đây. Hãy phóng gần để kiểm tra ranh theo vùng xem.';
        return;
      }
      example.disabled = true;
      var request = config.example ? Promise.resolve(config.example) :
        env.fetch(apiBase + '/sample.json?area=' + encodeURIComponent(nearest.area_id), {signal: lifetime.signal, cache: 'no-store'})
          .then(function (response) { if (!response.ok) throw new Error('Sample unavailable'); return response.json(); });
      request.then(function (feature) {
        if (disposed || startingView !== viewSeq) return;
        focusFeature(feature);
      }).catch(function (error) {
        if (!disposed && error.name !== 'AbortError') status.textContent = 'Chưa lấy được thửa mẫu. Hãy phóng to để chọn thửa trực tiếp.';
      }).finally(function () { if (!disposed) example.disabled = false; });
    });
    env.fetch(apiBase + '/config.json', {signal: lifetime.signal, cache: 'no-store'})
      .then(function (response) { if (!response.ok) throw new Error('Parcel config missing'); return response.json(); })
      .then(function (data) {
        if (disposed) return;
        searchMenu.hidden = !Array.isArray(data.areas);
        if (!data.areas && data.ward && data.bounds) data.areas = [{area_id:'25765',ward:data.ward,city:data.city,bounds:data.bounds}];
        if (!Array.isArray(data.areas) || !data.areas.length || data.min_zoom !== 17
            || data.areas.some(function (a) { return !Array.isArray(a.bounds) || a.bounds.length !== 2; })) throw new Error('Invalid parcel config');
        config = data; example.disabled = false; areaSubmit.disabled = searchSubmit.disabled = false;
        if (quickBoundaries) quickBoundaries.disabled = false;
        navigationAreas = Array.isArray(data.navigation_areas) && data.navigation_areas.length ? data.navigation_areas : data.areas;
        var nearest = closestArea(), navigationNearest = closestArea(navigationAreas);
        Array.from(new Set(navigationAreas.map(function (a) { return a.city; }))).forEach(function (city) { node('option', citySelect, city).value = city; });
        navigationRegions.forEach(function (region) { node('option', citySelect, region.name).value = region.id; });
        citySelect.value = navigationRegions.some(function (r) { return r.id === ui.initialRegion; }) ? ui.initialRegion : navigationNearest.city;
        fillWards(citySelect.value === navigationNearest.city ? navigationNearest.area_id || navigationNearest.code : '');
        data.areas.forEach(function (a) { node('option', searchArea, a.city + ' · ' + a.ward).value = a.area_id; });
        searchArea.value = nearest.area_id;
        badge.textContent = data.live_expanded ? 'Ranh GIS tải theo vùng xem · TP.HCM mới. Dữ liệu nguồn chưa phủ kín mọi khu vực.'
          : data.areas.length + ' phường · ' + format(data.count) + ' ranh thửa GIS. Phóng to để bấm chọn.';
        if (data.excluded_count) node('p', settings, format(data.excluded_count) + ' ranh lỗi nguồn đã được tạm loại.').className = 'planning-parcel-notice';
        loadViewport();
      }).catch(function (error) { if (!disposed && error.name !== 'AbortError') status.textContent = 'Chưa có dữ liệu ranh thửa cho bản thử.'; });
    map.on('moveend', move); map.on('movestart', moveStart); map.on('planning:drawing-start', closeInfo);
    function dispose() {
      if (disposed) return;
      disposed = true; ++viewSeq; ++selectionSeq; ++searchSeq; ++navigationSeq;
      lifetime.abort(); if (viewRequest) viewRequest.abort(); if (selectionRequest) selectionRequest.abort();
      if (searchRequest) searchRequest.abort(); if (navigationRequest) navigationRequest.abort();
      env.clearTimeout(timer); map.off('moveend', move); map.off('movestart', moveStart); map.off('unload', dispose);
      map.off('planning:drawing-start', closeInfo);
      remove(layer); remove(highlight);
      if (!sharedUI) ui.root.remove();
    }
    map.on('unload', dispose);
    return dispose;
  }
  return {mount: mount};
});
