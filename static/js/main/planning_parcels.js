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
    var viewSeq = 0, selectionSeq = 0, searchSeq = 0, navigationSeq = 0, layer, highlight, coordinateMarker, searchRequest, navigationRequest;
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
    function busy(key,value,label){if(map.fire)map.fire('planning:busy',{key:key,busy:value,label:label});}
    var parcelTools=env.RadarParcelTools&&L.layerGroup?env.RadarParcelTools.mount(map,L,env):null;
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
    if (ui.onToggleFilters) areaMenu.hidden = true;
    var areaForm = node('form', areaMenu); areaForm.className = 'planning-map-form';
    node('h3', areaForm, 'Đến khu vực');
    var citySelect = field('select', areaForm, 'Thành phố trên bản đồ');
    var wardSelect = field('select', areaForm, 'Phường trên bản đồ');
    var areaSubmit = node('button', areaForm, 'Xem khu vực'); areaSubmit.type = 'submit'; areaSubmit.disabled = true;
    var areaStatus = node('p', areaForm, 'Địa bàn theo dữ liệu cũ. Kéo bản đồ để xem thêm vùng bên cạnh.'); areaStatus.setAttribute('role', 'status');
    var searchMenu = popover(ui.parcelSlot, 'Tờ/thửa', 'planning-parcel-search');
    var searchForm = node('form', searchMenu); searchForm.className = 'planning-map-form'; searchForm.setAttribute('aria-label', 'Tra tờ thửa');
    node('h3', searchForm, 'Tra thửa đất');
    var closeSearch=node('button',searchForm,'×');closeSearch.type='button';closeSearch.className='planning-parcel-search-close';
    closeSearch.setAttribute('aria-label','Đóng tra tờ thửa');
    closeSearch.addEventListener('click',function(){searchMenu.open=false;searchMenu.querySelector('summary').focus();});
    var searchMethod = field('select', searchForm, 'Tra cứu theo');
    [['sheet','Tờ / thửa'],['coordinates','Tọa độ'],['corners','Góc ranh']].forEach(function(item){node('option',searchMethod,item[1]).value=item[0];});
    searchMethod.value='sheet';
    var sheetSection = node('div', searchForm);
    var searchProvince = field('select', sheetSection, 'Tỉnh/TP');
    var searchDistrict = field('select', sheetSection, 'Quận / Huyện (Cũ)');
    var searchArea = field('select', sheetSection, 'Phường / Xã (Cũ)');
    var inputRow = node('div', sheetSection); inputRow.className = 'planning-parcel-inputs';
    var sheetInput = field('input', inputRow, 'Số tờ bản đồ');
    var parcelInput = field('input', inputRow, 'Số thửa đất');
    [sheetInput,parcelInput].forEach(function (input) { input.type = 'text'; input.inputMode = 'numeric'; input.maxLength = 32; input.required = true; input.autocomplete = 'off'; });
    var coordinateSection=node('div',searchForm);coordinateSection.hidden=true;
    var coordinateSystem=field('select',coordinateSection,'Hệ tọa độ');
    [['wgs84','WGS84 · Google Maps'],['vn2000','VN-2000']].forEach(function(item){node('option',coordinateSystem,item[1]).value=item[0];});coordinateSystem.value='wgs84';
    var projectionLabel=node('label',coordinateSection,'Hệ chiếu VN-2000');projectionLabel.hidden=true;
    var coordinateProjection=node('select',projectionLabel);coordinateProjection.setAttribute('aria-label','Hệ chiếu VN-2000');
    node('option',coordinateProjection,'Chọn hệ chiếu theo hồ sơ').value='';
    ['10300','10400','10430','10445','10500','10530','10545','10600','10615','10630','10700','10715','10730','10745','10815','10830'].forEach(function(code){
      node('option',coordinateProjection,'Múi 3° · KTT '+code.slice(0,3)+'°'+code.slice(3)+'′').value='tm3-'+code;
    });
    [['utm48','Múi 6° · UTM 48N'],['utm49','Múi 6° · UTM 49N']].forEach(function(item){node('option',coordinateProjection,item[1]).value=item[0];});coordinateProjection.value='';
    var firstLabel=node('label',coordinateSection),firstTitle=node('span',firstLabel,'Vĩ độ'),coordinateFirst=node('input',firstLabel);
    var secondLabel=node('label',coordinateSection),secondTitle=node('span',secondLabel,'Kinh độ'),coordinateSecond=node('input',secondLabel);
    [coordinateFirst,coordinateSecond].forEach(function(input){input.type='text';input.inputMode='decimal';input.maxLength=32;input.autocomplete='off';});
    node('p',coordinateSection,'Nhập tọa độ thập phân, không dùng dấu phân cách hàng nghìn. VN-2000 cần chọn đúng hệ chiếu theo hồ sơ; kết quả tham khảo.');
    var cornerLabel=node('label',coordinateSection,'Danh sách góc ranh');cornerLabel.hidden=true;
    var cornerInput=node('textarea',cornerLabel);cornerInput.rows=6;cornerInput.maxLength=12000;cornerInput.setAttribute('aria-label','Danh sách góc ranh');
    cornerInput.placeholder='11.0200 106.6100\n11.0200 106.6110\n11.0210 106.6110';
    node('p',cornerLabel,'Mỗi dòng một điểm theo thứ tự quanh ranh: vĩ độ kinh độ (WGS84) hoặc X Y (VN-2000). Có thể dán bảng 2 cột hoặc STT X Y; cách nhau bằng khoảng trắng hoặc dấu chấm phẩy. Tối đa 100 điểm.');
    var scanHost=node('div',coordinateSection);scanHost.hidden=true;
    var cornerScan=env.RadarCornerScan?env.RadarCornerScan.mount(env,scanHost,{url:apiBase+'/corners/scan.json',system:function(){return coordinateSystem.value;},onApply:function(text){cancelSearch();cornerInput.value=text;searchStatus.textContent='Đã nhận tọa độ từ ảnh. Kiểm tra hệ chiếu trước khi vẽ.';}}):null;
    var validatedCornerInput=null;
    function cornerValues(){return {system:coordinateSystem.value,crs:coordinateProjection.value,corners:cornerInput.value};}
    var savedHost=node('div',cornerLabel);
    if(env.RadarCornerSaved)env.RadarCornerSaved.mount(env,savedHost,{
      validated:function(){var values=cornerValues();return JSON.stringify(values)===validatedCornerInput?values:null;},
      open:function(row){
        if(row.system==='vn2000'&&!Array.from(coordinateProjection.children).some(function(option){return option.value===row.crs;})){
          searchStatus.textContent='Hệ chiếu trong bản lưu chưa được hỗ trợ.';return;
        }
        cancelSearch();if(cornerScan)cornerScan.reset();coordinateSystem.value=row.system;coordinateProjection.value=row.crs;cornerInput.value=row.corners;coordinateLabels();
        searchSubmit.click();
      }
    });
    searchMenu.addEventListener('toggle',function(){if(!searchMenu.open&&cornerScan)cornerScan.reset();});
    function coordinateLabels(){
      var vn=coordinateSystem.value==='vn2000';projectionLabel.hidden=!vn;
      coordinateProjection.required=vn&&searchMethod.value!=='sheet';
      cornerInput.placeholder=vn?'1218730.50 594520.25\n1218730.50 594550.25\n1218760.50 594550.25':'11.0200 106.6100\n11.0200 106.6110\n11.0210 106.6110';
      firstTitle.textContent=vn?'X · Tọa độ bắc (m)':'Vĩ độ';secondTitle.textContent=vn?'Y · Tọa độ đông (m)':'Kinh độ';
      coordinateFirst.setAttribute('aria-label',firstTitle.textContent);coordinateSecond.setAttribute('aria-label',secondTitle.textContent);
      coordinateFirst.placeholder=vn?'Ví dụ 1220000.50':'Ví dụ 11.0205';coordinateSecond.placeholder=vn?'Ví dụ 600000.25':'Ví dụ 106.6105';
    }
    coordinateLabels();
    var searchSubmit = node('button', searchForm, 'Tìm thửa đất'); searchSubmit.type = 'submit'; searchSubmit.disabled = true;
    var searchStatus = node('p', searchForm, 'Nhập đúng số tờ, số thửa và phường theo dữ liệu GIS.'); searchStatus.setAttribute('role', 'status');
    var results = node('div', searchForm); results.className = 'planning-parcel-results';
    var settings = node('div', ui.layerBody); settings.className = 'planning-parcel-settings';
    var label = node('label', settings); label.className = 'planning-parcel-toggle';
    var toggle = node('input', label); toggle.type = 'checkbox'; toggle.checked = false;
    toggle.setAttribute('aria-label', 'Bật ranh thửa đất');
    node('span', label, 'Hiển thị ranh thửa đất');
    var boundaryHost=ui.boundarySlot||ui.dock;
    var quickBoundaries = boundaryHost ? node('button', boundaryHost, 'Ranh thửa') : null;
    if (quickBoundaries) {
      if(!ui.boundarySlot)ui.dock.prepend(quickBoundaries);
      quickBoundaries.type = 'button'; quickBoundaries.className = 'planning-layer-chip'; quickBoundaries.disabled = true;
      quickBoundaries.setAttribute('aria-label', 'Bật/tắt ranh thửa'); quickBoundaries.setAttribute('aria-pressed', 'false');
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
    var footer=node('p', body, 'Dữ liệu GIS tham khảo, chưa xác minh hiệu lực hoặc độ chính xác địa chính; không thay thế xác nhận quy hoạch.');footer.className = 'planning-parcel-notice';
    L.DomEvent.disableClickPropagation(ui.root); L.DomEvent.disableScrollPropagation(ui.root);
    function remove(which) { if (which) map.removeLayer(which); }
    function clearInfo() { info.replaceChildren(); }
    function showParcel(feature) {
      remove(coordinateMarker);coordinateMarker=null;
      clearInfo();
      var dongnai = feature.properties.source === 'https://gis.dongnai.gov.vn/';
      var khanhhoa = feature.properties.source === 'https://gis.khanhhoa.gov.vn/';
      source.textContent = khanhhoa ? 'Nguồn: Cổng GIS Khánh Hòa' : dongnai ? 'Nguồn: Cổng GIS Đồng Nai · Bình Phước cũ' : 'Nguồn: Cổng GIS TP.HCM';
      source.href = khanhhoa ? 'https://gis.khanhhoa.gov.vn/public/8192/' : dongnai ? 'https://gis.dongnai.gov.vn/' : 'https://gisxaydung.tphcm.gov.vn/tracuuttqh';
      var heading=node('h3', info, 'Thửa ' + format(feature.properties.parcel) + ' · Tờ ' + format(feature.properties.sheet));
      node('strong', heading, ' · '+area(feature.properties.area)).className = 'planning-parcel-area';
      node('p', info, (feature.properties.ward || config.ward) + ' · ' + (feature.properties.city || config.city) + ' (đơn vị cũ)').className = 'planning-parcel-location';
    }
    function closeInfo() {
      if(cellsView)cellsView.cancelSelection();
      ++selectionSeq; if (selectionRequest) selectionRequest.abort();
      ++searchSeq; if (searchRequest) searchRequest.abort(); busy('parcel-search',false);searchSubmit.disabled = !config;
      box.hidden = true;
      busy('parcel-detail',false);
      var container = map.getContainer(); if (container.focus) container.focus({preventScroll:true});
    }
    function clearSelection(){
      closeInfo();remove(highlight);highlight=null;remove(coordinateMarker);coordinateMarker=null;
      if(parcelTools)parcelTools.clear();
      if(map.fire)map.fire('planning:selection-change',{selected:false});
    }
    close.addEventListener('click', closeInfo);
    box.addEventListener('keydown', function (event) { if (event.key === 'Escape') closeInfo(); });
    function placeCard(){
      if(box.hidden||!ui.dock||!ui.dock.getBoundingClientRect||!map.getContainer().getBoundingClientRect)return;
      var frame=map.getContainer().getBoundingClientRect(),dock=ui.dock.getBoundingClientRect();
      box.style.bottom=Math.max(8,frame.bottom-dock.top+8)+'px';
      box.style.maxHeight=Math.max(100,frame.height-(frame.bottom-dock.top)-90)+'px';
    }
    var cardObserver=env.ResizeObserver&&ui.dock?new env.ResizeObserver(placeCard):null;
    if(cardObserver){cardObserver.observe(ui.dock);cardObserver.observe(map.getContainer());}
    function select(feature) {
      if(cellsView)cellsView.cancelSelection();
      if(disposed||!toggle.checked)return;
      var mapClasses=map.getContainer().classList;
      if(mapClasses&&mapClasses.contains('planning-is-drawing'))return;
      ++searchSeq;if(searchRequest)searchRequest.abort();busy('parcel-search',false);searchSubmit.disabled=!config;
      if(selectionRequest)selectionRequest.abort();selectionRequest=null;
      var sequence=++selectionSeq;busy('parcel-detail',false);
      remove(highlight);
      highlight=feature.display_only?null:L.geoJSON(feature,{pane:'planningParcelSelected',interactive:false,
        style:{color:'#0f766e',weight:2.5,fillColor:'#14b8a6',fillOpacity:.1}}).addTo(map);
      if(map.fire)map.fire('planning:selection-change',{selected:!!highlight});
      box.hidden=false;source.hidden=footer.hidden=true;
      if(box.classList)box.classList.remove('is-expanded');
      showParcel(feature);
      if(parcelTools&&feature.display_only)parcelTools.clear();
      var metrics=parcelTools&&!feature.display_only?parcelTools.show(feature):null;
      var actions=node('div',info);actions.className='planning-parcel-quick-actions';
      if(metrics){
        var route=node('a',actions,'↗ Chỉ đường');route.href=env.RadarParcelTools.directions(metrics.center);route.target='_blank';route.rel='noopener noreferrer';
        var draw=node('button',actions,'✎ Đo vẽ');draw.type='button';
        draw.addEventListener('click',function(){if(map.fire)map.fire('planning:draw-request');});
      }
      var detailsButton=node('button',info,'Xem đầy đủ thông tin quy hoạch chi tiết');detailsButton.type='button';detailsButton.className='planning-parcel-expand';
      var detailBody=node('div',info);detailBody.className='planning-parcel-detail';detailBody.hidden=true;
      var requestState={loaded:false,pending:false};
      detailsButton.addEventListener('click',function(){
        if(cellsView)cellsView.cancelSelection();
        if(disposed||sequence!==selectionSeq||requestState.pending)return;
        if(requestState.loaded){detailBody.hidden=!detailBody.hidden;source.hidden=footer.hidden=detailBody.hidden;
          detailsButton.textContent=detailBody.hidden?'Xem đầy đủ thông tin quy hoạch chi tiết':'Ẩn thông tin quy hoạch chi tiết';
          if(box.classList)box.classList.toggle('is-expanded',!detailBody.hidden);placeCard();return;}
        loadPlanning(feature,sequence,detailBody,detailsButton,requestState);
      });
      ui.panels.forEach(function(panel){panel.open=false;});placeCard();
      if(metrics&&map.panInside)map.panInside(metrics.center,{paddingTopLeft:[45,90],paddingBottomRight:[80,Math.min(300,(box.offsetHeight||160)+85)],animate:false});
    }
    function loadPlanning(feature,sequence,detailBody,button,requestState){
      if(disposed||sequence!==selectionSeq||requestState.pending)return;
      requestState.pending=true;selectionRequest=new env.AbortController();
      button.disabled=true;button.setAttribute('aria-busy','true');button.textContent='Đang tra cứu quy hoạch…';
      detailBody.hidden=false;detailBody.replaceChildren();source.hidden=footer.hidden=false;
      if(box.classList)box.classList.add('is-expanded');placeCard();busy('parcel-detail',true,'Đang tra cứu quy hoạch từ GIS…');
      var message = node('p', detailBody, 'Đang tra cứu thông tin thửa từ GIS…');
      var areaQuery = feature.properties.area_id ? '?area=' + encodeURIComponent(feature.properties.area_id) : '';
      env.fetch(apiBase + '/' + feature.id + '/planning.json' + areaQuery, {signal: selectionRequest.signal, cache: 'no-store'})
        .then(function (response) { if (!response.ok) throw new Error('GIS unavailable'); return response.json(); })
        .then(function (data) {
          if (disposed || sequence !== selectionSeq) return;
          if (!data || !data.parcel || data.parcel.id !== feature.id || !Array.isArray(data.plans)) throw new Error('Invalid GIS response');
          message.remove();requestState.loaded=true;button.textContent='Ẩn thông tin quy hoạch chi tiết';
          if (!data.plans.length) node('p', detailBody, data.unavailable_layers && data.unavailable_layers.length
            ? 'Chưa tải đủ các lớp quy hoạch. Chưa thể kết luận quy hoạch của thửa này.' : data.planning_available === false
            ? 'Đã có ranh thửa. Nguồn này chưa hỗ trợ tra giao quy hoạch; hãy đối chiếu lớp bản đồ đang bật.'
            : 'GIS chưa trả về đồ án giao thửa này. Chưa thể kết luận thửa không có quy hoạch.');
          data.plans.forEach(function (plan) {
            var section = node('section', detailBody); section.className = 'parcel-planning-plan';
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
          if (data.plans.length) node('p', detailBody, data.intersection_method === 'geodesic_wgs84'
            ? 'Diện tích giao do RadarBDS tính từ hình học GIS, có thể khác diện tích hồ sơ. Các đồ án có thể chồng lấn; chỉ tiêu giữ nguyên theo nguồn.'
            : 'Diện tích giao do GIS tính, có thể khác diện tích thửa. Chỉ tiêu được giữ nguyên giá trị nguồn.').className = 'planning-parcel-notice';
          if (data.intersection_method === 'geodesic_wgs84') node('p', detailBody, 'Tra QH chi tiết và QH chung của GIS Đồng Nai. Chưa bao gồm QH phân khu và QH SDĐ 2030.').className = 'planning-parcel-notice';
          if (Array.isArray(data.unavailable_layers) && data.unavailable_layers.length) node('p', detailBody,
            'Chưa tải được: ' + data.unavailable_layers.join(', ') + '. Kết quả hiện tại chưa đầy đủ; vui lòng thử lại sau.').className = 'planning-parcel-notice';
          node('p', detailBody, 'Tra cứu: ' + new Date(data.queried_at).toLocaleString('vi-VN'));
        }).catch(function (error) {
          if (!disposed && sequence === selectionSeq && error.name !== 'AbortError') {
            message.textContent = 'Chưa lấy được thông tin GIS. Chưa thể kết luận quy hoạch thửa này; bấm Thử lại để tra cứu.';
            var retry = node('button', detailBody, 'Thử lại tra cứu'); retry.type = 'button';
            retry.addEventListener('click', function () { loadPlanning(feature,sequence,detailBody,button,requestState); });
          }
        }).finally(function(){
          if(!disposed&&sequence===selectionSeq){requestState.pending=false;button.disabled=false;button.setAttribute('aria-busy','false');busy('parcel-detail',false);if(!requestState.loaded)button.textContent='Xem đầy đủ thông tin quy hoạch chi tiết';}
        });
    }
    var cellsView;
    function loadViewport(retryAttempt) {
      if(config&&config.parcel_cells&&env.RadarParcelCells){
        if(!cellsView)cellsView=env.RadarParcelCells.mount(map,L,env,{
          template:config.parcel_cells.template,featureTemplate:config.parcel_cells.feature_template,liveTemplate:config.parcel_cells.live_template,zoom:config.parcel_cells.zoom,select:select,
          enabled:function(){return toggle.checked&&map.getZoom()>=config.min_zoom&&(config.coverage_bounds?map.getBounds().intersects(config.coverage_bounds):config.areas.some(function(a){return map.getBounds().intersects(a.bounds);}));},
          status:function(message,loading){status.textContent=message;busy('parcel-view',loading,message);}
        });
        cellsView.update();return;
      }
      if (disposed || !config) return;
      var attempt = Number.isInteger(retryAttempt) ? retryAttempt : 0;
      if (viewRequest) viewRequest.abort();
      busy('parcel-view',false);
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
      viewRequest = new env.AbortController(); status.textContent = 'Đang tải ranh trong vùng xem…';busy('parcel-view',true,status.textContent);
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
        }).finally(function(){if(sequence===viewSeq)busy('parcel-view',false);});
    }
    function move() {
      if (viewRequest) viewRequest.abort();
      ++viewSeq;busy('parcel-view',false);
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
      ++navigationSeq; if (navigationRequest) navigationRequest.abort(); busy('parcel-area',false);areaSubmit.disabled = false;
      fillWards();
    });
    wardSelect.addEventListener('change', function () {
      ++navigationSeq; if (navigationRequest) navigationRequest.abort(); busy('parcel-area',false);areaSubmit.disabled = !config;
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
        map.fitBounds(bounds, {maxZoom: selected ? 16 : 13, padding: [24,24], animate: false});
        areaMenu.open = false;
        areaStatus.textContent = 'Đã đến ' + (selected ? selected.ward + ' · ' : '') + citySelect.value + '. Phóng gần để xem ranh GIS.';
        return;
      }
      var query = new URLSearchParams({city: citySelect.value}); if (selected) query.set('ward', selected.ward);
      navigationRequest = new env.AbortController(); areaSubmit.disabled = true;
      areaStatus.textContent = 'Đang mở khu vực…';busy('parcel-area',true,areaStatus.textContent);closeInfo();
      env.fetch('/api/map-initial-bounds?' + query.toString(), {signal: navigationRequest.signal})
        .then(function (response) { if (!response.ok) throw new Error('Area unavailable'); return response.json(); })
        .then(function (data) {
          if (disposed || seq !== navigationSeq) return;
          if (!Array.isArray(data.bounds) || data.bounds.length !== 2) throw new Error('Invalid area');
          map.fitBounds(data.bounds, {maxZoom: selected ? 16 : 13, padding: [24,24], animate: false});
          if (selected && map.getZoom() < 15) map.setZoom(15, {animate: false});
          areaMenu.open = false;
          areaStatus.textContent = 'Đã đến ' + (selected ? selected.ward + ' · ' : '') + citySelect.value + '. Có thể kéo sang vùng lân cận.';
        }).catch(function (error) {
          if (!disposed && seq === navigationSeq && error.name !== 'AbortError') areaStatus.textContent = 'Chưa mở được khu vực. Vui lòng thử lại.';
        }).finally(function () { if (!disposed && seq === navigationSeq){areaSubmit.disabled = false;busy('parcel-area',false);} });
    });
    function focusFeature(feature) {
      toggle.checked = true;
      if (quickBoundaries) quickBoundaries.setAttribute('aria-pressed', 'true');
      map.fitBounds(L.geoJSON(feature).getBounds(), {maxZoom: 19, padding: [70,70], animate: false});
      select(feature);
    }
    function cancelSearch() {
      ++searchSeq; if (searchRequest) searchRequest.abort(); busy('parcel-search',false);searchSubmit.disabled = !config; results.replaceChildren();
      searchStatus.textContent = searchMethod.value==='corners'
        ? 'Dán các góc theo thứ tự quanh ranh. Ranh tự nhập dùng để đối chiếu lớp bản đồ.' : searchMethod.value==='coordinates'
        ? 'Chọn hệ tọa độ và nhập đủ hai giá trị.' : 'Nhập đúng số tờ, số thửa và phường theo dữ liệu GIS.';
    }
    function changeSearchMethod(){
      cancelSearch();if(cornerScan)cornerScan.reset();var coordinates=searchMethod.value==='coordinates',corners=searchMethod.value==='corners';
      sheetSection.hidden=coordinates||corners;coordinateSection.hidden=!(coordinates||corners);
      firstLabel.hidden=secondLabel.hidden=corners;cornerLabel.hidden=scanHost.hidden=!corners;
      sheetInput.required=parcelInput.required=!(coordinates||corners);
      coordinateFirst.required=coordinateSecond.required=coordinates;cornerInput.required=corners;
      coordinateProjection.required=(coordinates||corners)&&coordinateSystem.value==='vn2000';
      searchSubmit.textContent=corners?'Xem ranh từ tọa độ':coordinates?'Tìm thửa theo tọa độ':'Tìm thửa đất';
      searchSubmit.disabled=!config;searchStatus.textContent=corners?'Dán các góc theo thứ tự quanh ranh. Ranh tự nhập dùng để đối chiếu lớp bản đồ.':coordinates?'Chọn hệ tọa độ và nhập đủ hai giá trị.':'Nhập đúng số tờ, số thửa và phường theo dữ liệu GIS.';
    }
    searchMethod.addEventListener('change',changeSearchMethod);
    coordinateSystem.addEventListener('change',function(){cancelSearch();if(cornerScan)cornerScan.reset();coordinateLabels();});
    coordinateProjection.addEventListener('change',function(){cancelSearch();if(cornerScan)cornerScan.reset();});
    [coordinateProjection,coordinateFirst,coordinateSecond,cornerInput].forEach(function(input){input.addEventListener('change',cancelSearch);input.addEventListener('input',cancelSearch);});
    function moveStart() {
      if (disposed) return;
      if(cellsView)cellsView.pause();
      cancelSearch(); ++navigationSeq; if (navigationRequest) navigationRequest.abort(); busy('parcel-area',false);areaSubmit.disabled = !config;
      if (viewRequest) viewRequest.abort(); ++viewSeq;
    }
    function provinceFor(a) {
      if (a.province === 'binh-phuoc' || a.province === 'khanh-hoa') return a.province;
      var district = Number(a.district);
      if (district >= 760 && district <= 787) return 'hcm';
      if (district >= 747 && district <= 755) return 'brvt';
      return 'binh-duong';
    }
    function fillSearchWards(selected) {
      searchArea.replaceChildren();
      config.areas.filter(function (a) { return provinceFor(a) === searchProvince.value && a.city === searchDistrict.value; })
        .forEach(function (a) { node('option', searchArea, a.ward).value = a.area_id || a.code; });
      searchArea.value = selected || (searchArea.children[0] && searchArea.children[0].value) || '';
      searchSubmit.disabled = !searchArea.value;
    }
    function fillSearchDistricts(selected, ward) {
      searchDistrict.replaceChildren();
      Array.from(new Set(config.areas.filter(function (a) { return provinceFor(a) === searchProvince.value; }).map(function (a) { return a.city; })))
        .forEach(function (city) { node('option', searchDistrict, city).value = city; });
      searchDistrict.value = selected || (searchDistrict.children[0] && searchDistrict.children[0].value) || '';
      fillSearchWards(ward);
    }
    [['binh-duong','Bình Dương'],['hcm','TP.HCM'],['brvt','Bà Rịa – Vũng Tàu']].forEach(function (item) {
      node('option', searchProvince, item[1]).value = item[0];
    });
    searchProvince.addEventListener('change', function () { cancelSearch(); fillSearchDistricts(); });
    searchDistrict.addEventListener('change', function () { cancelSearch(); fillSearchWards(); });
    searchArea.addEventListener('change', cancelSearch);
    sheetInput.addEventListener('input', cancelSearch); parcelInput.addEventListener('input', cancelSearch);
    searchForm.addEventListener('submit', function (event) {
      event.preventDefault(); if (disposed || !config) return;
      var sheet = String(sheetInput.value || '').trim(), parcel = String(parcelInput.value || '').trim(), areaId = searchArea.value;
      var coordinates=searchMethod.value==='coordinates',corners=searchMethod.value==='corners';
      cancelSearch();
      if (!coordinates&&!corners&&(!areaId || !sheet || !parcel)) { searchStatus.textContent = 'Chọn địa bàn và nhập đủ số tờ, số thửa.'; return; }
      if(coordinates&&(!coordinateFirst.value.trim()||!coordinateSecond.value.trim())){searchStatus.textContent='Nhập đủ hai tọa độ.';return;}
      if(corners&&!String(cornerInput.value||'').trim()){searchStatus.textContent='Nhập ít nhất 3 góc ranh.';return;}
      var seq = searchSeq; searchRequest = new env.AbortController(); searchSubmit.disabled = true;
      searchStatus.textContent = corners?'Đang chuyển tọa độ và dựng ranh…':'Đang tìm thửa trong dữ liệu GIS…';busy('parcel-search',true,searchStatus.textContent);
      var query = new URLSearchParams({area: areaId, sheet: sheet, parcel: parcel});
      if(coordinates)query=new URLSearchParams({system:coordinateSystem.value,crs:coordinateProjection.value,first:coordinateFirst.value.trim(),second:coordinateSecond.value.trim()});
      var requestOptions={signal:searchRequest.signal,cache:'default',credentials:'omit'};
      if(corners){requestOptions.method='POST';requestOptions.headers={'Content-Type':'application/json'};requestOptions.body=JSON.stringify(cornerValues());validatedCornerInput=null;}
      env.fetch(apiBase + (corners?'/corners.json':(coordinates?'/coordinates.json?':'/search.json?')+query.toString()),requestOptions)
        .then(function (response) { if (!response.ok) throw new Error('Parcel search failed'); return response.json(); })
        .then(function (data) {
          if (disposed || seq !== searchSeq) return;
          if(corners){
            var metrics=env.RadarParcelTools&&env.RadarParcelTools.metrics(data);
            if(!metrics||!data.properties||data.properties.origin!=='user_corners')throw new Error('Invalid corner outline');
            validatedCornerInput=requestOptions.body;
            searchStatus.textContent='Đã dựng ranh tự nhập. Bật lớp quy hoạch để đối chiếu; đây không phải ranh thửa đã xác minh từ GIS.';
            searchMenu.open=false;remove(coordinateMarker);coordinateMarker=null;
            if(map.fire)map.fire('planning:measure-parcel',{points:metrics.outline,origin:'user_corners'});
            map.fitBounds(L.geoJSON(data).getBounds(),{maxZoom:19,padding:[65,100],animate:false});return;
          }
          if (data.type !== 'FeatureCollection' || !Array.isArray(data.features) || data.features.length > 20
              || data.features.some(function (f) { return !f.properties || !coordinates&&f.properties.area_id !== areaId; })) throw new Error('Invalid search response');
          if (!data.features.length) {
            if(coordinates){
              if(!Array.isArray(data.point)||data.point.length!==2||!data.point.every(Number.isFinite))throw new Error('Invalid coordinate result');
              map.setView(data.point,19,{animate:false});remove(coordinateMarker);
              if(L.circleMarker)coordinateMarker=L.circleMarker(data.point,{pane:'planningParcelSelected',interactive:false,radius:7,color:'#7c3aed',fillOpacity:.65}).addTo(map);
              searchStatus.textContent='Đã đến tọa độ. Nguồn hiện chưa trả ranh tại điểm này; hãy kiểm tra hệ chiếu và vùng có dữ liệu.';
            }else searchStatus.textContent = 'Không tìm thấy thửa khớp. Kiểm tra số tờ, số thửa và phường theo dữ liệu cũ.';
            return;
          }
          if (data.matched === 1 && data.features.length === 1) {
            searchStatus.textContent = 'Đã tìm thấy thửa. Bấm xem đầy đủ nếu cần tra cứu quy hoạch.';
            focusFeature(data.features[0]); return;
          }
          searchStatus.textContent = 'Nguồn có ' + (data.truncated ? 'ít nhất ' : '') + data.matched + ' bản ghi trùng tờ/thửa. Chọn để kiểm tra vị trí.'
            + (data.truncated ? ' Đang hiện 20 kết quả đầu.' : '');
          data.features.forEach(function (feature, index) {
            var button = node('button', results, 'Kết quả ' + (index+1) + ' · ' + area(feature.properties.area)); button.type = 'button';
            button.addEventListener('click', function () { if (!disposed) focusFeature(feature); });
          });
        }).catch(function (error) {
          if (!disposed && seq === searchSeq && error.name !== 'AbortError') searchStatus.textContent = corners?'Chưa dựng được ranh. Kiểm tra 3–100 điểm theo thứ tự, hệ chiếu và các cạnh giao nhau.':coordinates?'Chưa tra được tọa độ. Kiểm tra thứ tự hai giá trị, hệ chiếu và thử lại.':'Chưa tìm được thửa. Vui lòng thử lại.';
        }).finally(function () { if (!disposed && seq === searchSeq){searchSubmit.disabled = false;busy('parcel-search',false);} });
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
      example.disabled = true;busy('parcel-sample',true,'Đang tải thửa mẫu…');
      var request = config.example ? Promise.resolve(config.example) :
        env.fetch(apiBase + '/sample.json?area=' + encodeURIComponent(nearest.area_id), {signal: lifetime.signal, cache: 'no-store'})
          .then(function (response) { if (!response.ok) throw new Error('Sample unavailable'); return response.json(); });
      request.then(function (feature) {
        if (disposed || startingView !== viewSeq) return;
        focusFeature(feature);
      }).catch(function (error) {
        if (!disposed && error.name !== 'AbortError') status.textContent = 'Chưa lấy được thửa mẫu. Hãy phóng to để chọn thửa trực tiếp.';
      }).finally(function () { if (!disposed){example.disabled = false;busy('parcel-sample',false);} });
    });
    env.fetch(apiBase + '/config.json', {signal: lifetime.signal, cache: 'default', credentials:'omit'})
      .then(function (response) { if (!response.ok) throw new Error('Parcel config missing'); return response.json(); })
      .then(function (data) {
        if (disposed) return;
        searchMenu.hidden = !Array.isArray(data.areas);
        if (!data.areas && data.ward && data.bounds) data.areas = [{area_id:'25765',ward:data.ward,city:data.city,bounds:data.bounds}];
        if (!Array.isArray(data.areas) || !data.areas.length || data.min_zoom !== 17
            || data.areas.some(function (a) { return !Array.isArray(a.bounds) || a.bounds.length !== 2; })) throw new Error('Invalid parcel config');
        config = data; example.disabled = false; areaSubmit.disabled = searchSubmit.disabled = false;
        if (data.areas.some(function (a) { return a.province === 'binh-phuoc'; })) {
          node('option', searchProvince, 'Bình Phước (cũ) · Đồng Nai').value = 'binh-phuoc';
        }
        if (data.areas.some(function (a) { return a.province === 'khanh-hoa'; })) {
          node('option', searchProvince, 'Khánh Hòa (cũ)').value = 'khanh-hoa';
        }
        if (quickBoundaries) quickBoundaries.disabled = false;
        navigationAreas = Array.isArray(data.navigation_areas) && data.navigation_areas.length ? data.navigation_areas : data.areas;
        var nearest = closestArea(), navigationNearest = closestArea(navigationAreas);
        Array.from(new Set(navigationAreas.map(function (a) { return a.city; }))).forEach(function (city) { node('option', citySelect, city).value = city; });
        navigationRegions.forEach(function (region) { node('option', citySelect, region.name).value = region.id; });
        citySelect.value = navigationRegions.some(function (r) { return r.id === ui.initialRegion; }) ? ui.initialRegion : navigationNearest.city;
        fillWards(citySelect.value === navigationNearest.city ? navigationNearest.area_id || navigationNearest.code : '');
        searchProvince.value = provinceFor(nearest);
        fillSearchDistricts(nearest.city, nearest.area_id || nearest.code);
        badge.textContent = data.regional_sources ? 'Ranh tải theo vùng xem · TP.HCM và Bình Phước cũ thuộc Đồng Nai. Nguồn chưa phủ kín; chưa có ranh Đồng Nai cũ.'
          : data.live_expanded ? 'Ranh GIS tải theo vùng xem · TP.HCM mới. Dữ liệu nguồn chưa phủ kín mọi khu vực.'
          : data.areas.length + ' phường · ' + format(data.count) + ' ranh thửa GIS. Phóng to để bấm chọn.';
        if (data.excluded_count) node('p', settings, format(data.excluded_count) + ' ranh lỗi nguồn đã được tạm loại.').className = 'planning-parcel-notice';
        loadViewport();
      }).catch(function (error) { if (!disposed && error.name !== 'AbortError') status.textContent = 'Chưa có dữ liệu ranh thửa cho bản thử.'; });
    map.on('moveend', move); map.on('movestart', moveStart); map.on('planning:drawing-start', closeInfo); map.on('planning:listing-selected',closeInfo); map.on('planning:area-change', closeInfo);
    map.on('planning:clear-boundaries',clearSelection);
    function dispose() {
      if (disposed) return;
      disposed = true; ++viewSeq; ++selectionSeq; ++searchSeq; ++navigationSeq;
      if(cornerScan)cornerScan.dispose();
      if(cellsView)cellsView.dispose();
      lifetime.abort(); if (viewRequest) viewRequest.abort(); if (selectionRequest) selectionRequest.abort();
      if (searchRequest) searchRequest.abort(); if (navigationRequest) navigationRequest.abort();
      env.clearTimeout(timer); map.off('moveend', move); map.off('movestart', moveStart); map.off('unload', dispose);
      map.off('planning:area-change', closeInfo);
      map.off('planning:clear-boundaries',clearSelection);
      map.off('planning:drawing-start', closeInfo);map.off('planning:listing-selected',closeInfo);
      if(cardObserver)cardObserver.disconnect();if(parcelTools)parcelTools.dispose();
      ['parcel-view','parcel-detail','parcel-search','parcel-area','parcel-sample'].forEach(function(key){busy(key,false);});
      remove(layer); remove(highlight);remove(coordinateMarker);
      if (!sharedUI) ui.root.remove();
    }
    map.on('unload', dispose);
    return dispose;
  }
  return {mount: mount};
});
