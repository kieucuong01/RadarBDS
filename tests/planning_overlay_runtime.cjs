const assert = require('node:assert/strict');
const api = require('../static/js/main/planning_overlay.js');
const referenceTemplate = 'https://r4gmiynxmeobj.vcdn.cloud/binh-duong-2030/{z}/{x}/{y}.png';
assert.equal(api.referenceClipPath(referenceTemplate, {z:11,x:1630,y:960}),
  'path(evenodd, "M0 0H256V256H0Z M39 228L170 368L146 391L15 251Z")');
assert.equal(api.referenceClipPath(referenceTemplate, {z:12,x:3260,y:1921}),
  'path(evenodd, "M0 0H256V256H0Z M78 200L340 480L292 526L30 246Z")');
assert.equal(api.referenceClipPath(referenceTemplate, {z:11,x:1631,y:960}), '');
assert.equal(api.referenceClipPath(referenceTemplate, {z:11,x:1631,y:961}),
  'path(evenodd, "M0 0H256V256H0Z M190 174L311 174L311 203L190 203Z")');
assert.equal(api.referenceClipPath(referenceTemplate.replace('binh-duong','tp-ho-chi-minh'), {z:11,x:1630,y:960}), '');

const manifest = {id: 'thoi-hoa-2909-qh01', status: 'local_experiment',
  bounds: [[11.07, 106.58], [11.14, 106.67]], title: 'Thoi Hoa', notice: 'Pilot',
  decision: '2909/2022', check_max_m: 53.6, check_count: 3};
const officialManifest = {...manifest, id:'my-phuoc-2913', source_kind:'official_gis',
  alignment_method:'official_coordinates', legend_available:false,
  bounds:[[11.01,106.55],[11.16,106.70]]};
delete officialManifest.check_max_m; delete officialManifest.check_count;
const catalog = {layers: [{id: manifest.id,name: 'Thới Hòa',status:'overlay_ready',
  decision: manifest.decision,source:'gis',source_url:'https://drive.google.com/file/d/example/view',manifest},
  {id:'tan-dinh-2910-qh01',name:'Tân Định',status:'overlay_ready',decision:'2910/2022',
   source:'gis',source_url:'https://drive.google.com/file/d/tan-dinh/view',manifest:{...manifest,id:'tan-dinh-2910-qh01'}},
  {id:'hoa-loi-2911-qh01',name:'Hòa Lợi',status:'document_only',decision:'2911/2022',
   source_url:'https://drive.google.com/file/d/hoa-loi/view',preview_url:'/local-planning/hoa-loi-2911-qh01/preview.webp',message:'Chờ căn chỉnh'},
  {id:officialManifest.id,name:'Mỹ Phước',status:'overlay_ready',decision:'2913/2022',
   source:'gis',source_url:'https://gisxaydung.tphcm.gov.vn/tracuuttqh',manifest:officialManifest}]};

function harness(cityValue, publicConfig, openingBounds, initialTheme, listingOptions) {
  const nodes = [], layers = new Set(), handlers = {}, zoomHandlers = new Set();
  let resolveFetch, removed = false, signal, visibleBounds = openingBounds;
  const fetches=[];
  const env = {AbortController, RADAR_PLANNING_CONFIG:publicConfig, matchMedia: () => ({matches: false}),
    document: {getElementById(id) {return id==='cityInput'?{value:cityValue}:null;}, createElement(tag) {
      const el = {tag, style: {}, events: {}, attributes: {}, children: [],
        appendChild(child) {this.children.push(child);},
        setAttribute(k,v) {this.attributes[k]=v;}, getAttribute(k) {return this.attributes[k];},
        removeAttribute(k) {delete this.attributes[k];},
        addEventListener(k,fn) {this.events[k]=fn;}};
      el.remove=()=>{removed=true;};
      nodes.push(el); return el;
    }},
    fetch(url, options) {fetches.push(url);signal=options.signal; return new Promise(r=>{resolveFetch=r;});}};
  const map = {createPane: () => ({style: {}}), removeLayer(x) {
      layers.delete(x); x.attached=false;
      if (x.events.remove) x.events.remove();
    },
    getContainer:()=>({appendChild(){}}),
    getCenter:()=>visibleBounds ? {lat:(visibleBounds[0][0]+visibleBounds[1][0])/2,lng:(visibleBounds[0][1]+visibleBounds[1][1])/2} : null,
    on(k,fn) {handlers[k]=fn;}, off(k) {delete handlers[k];},
    getBounds: () => ({intersects: b => !visibleBounds || (visibleBounds[0][0] <= b[1][0] && visibleBounds[1][0] >= b[0][0]
      && visibleBounds[0][1] <= b[1][1] && visibleBounds[1][1] >= b[0][1])}), fitBounds(bounds) {this.fitted=bounds;}};
  const L = {DomEvent: {disableClickPropagation() {}, disableScrollPropagation() {}},
    control: () => ({addTo() {}, remove() {removed=true;}}),
    tileLayer(url,options) {const layer=this.imageOverlay(url,options.bounds,options);layer.kind='tile';return layer;},
    imageOverlay(url,bounds,options) {
      return {events: {}, options, url, on(k,fn) {this.events[k]=fn;}, off() {this.events={};},
        _isValidTile(){return true;},_tileCoordsToBounds(coords){return {intersects:b=>coords.bounds[0][0]<=b[1][0]&&coords.bounds[1][0]>=b[0][0]&&coords.bounds[0][1]<=b[1][1]&&coords.bounds[1][1]>=b[0][1]};},
        addTo() {
          layers.add(this); this.attached=true;
          const zoom=()=>assert.equal(this.attached,true,'Detached layer retained a zoom handler');
          zoomHandlers.add(zoom);
          // Leaflet registers its own remove listener to unbind map events.
          this.events.remove=()=>zoomHandlers.delete(zoom);
        }, setOpacity(value) {this.options.opacity=value;}};
    }};
  const dispose = api.mount(map,L,env,{initialTheme,...listingOptions});
  return {nodes,layers,handlers,dispose,map,fetches, zoom() {zoomHandlers.forEach(fn=>fn());},
    move(bounds) {visibleBounds=bounds;handlers.moveend();},
    get signal() {return signal;}, get removed() {return removed;},
    deliver(data=catalog) {resolveFetch({ok: true,json: async()=>data});}};
}
const flush = () => new Promise(resolve=>setImmediate(resolve));
(async () => {
  assert.equal(api.validManifest(manifest),true);
  assert.equal(api.validManifest({...manifest,status:'reference_overlay'}),true);
  assert.equal(api.validManifest({...manifest,bounds:[[0,0],[90,180]]}),false);
  assert.equal(api.validCatalog(catalog),true);
  assert.equal(api.validCatalog({layers:[{...catalog.layers[0],source_url:'javascript:alert(1)'}]}),false);
  assert.equal(api.validCatalog({layers:[{...catalog.layers[0],theme:'district_landuse'}]}),false);
  assert.equal(api.validCatalog({layers:[{...catalog.layers[0],source_url:'https://aapbinhduong.com/attachs/source.png'}]}),true);
  assert.equal(api.validCatalog({layers:[{...catalog.layers[0],source_url:'https://gisxaydung.tphcm.gov.vn.evil.invalid/'}]}),false);
  assert.equal(api.opacity(120),1); assert.equal(api.opacity(-5),0); assert.equal(api.opacity('bad'),.35);
  const general={...catalog.layers[0],id:'ben-cat-general-gis',name:'Bến Cát',city:'Bến Cát',theme:'urban_general',scope:'city',
    manifest:{...officialManifest,id:'ben-cat-general-gis',map_scale:10000}};
  const tdmWard={...catalog.layers[3],id:'tdm-phu-cuong',name:'Phú Cường',city:'Thủ Dầu Một',
    manifest:{...officialManifest,id:'tdm-phu-cuong',map_scale:2000,bounds:[[10.94,106.63],[11.09,106.72]]}};
  const tdmGeneral={...general,id:'tdm-general',name:'Thủ Dầu Một',city:'Thủ Dầu Một',
    manifest:{...tdmWard.manifest,id:'tdm-general',map_scale:null}};
  let listingsVisible=false,toggled=0;
  const visibility=harness('BẾN CÁT',undefined,undefined,'partition',{
    listingsVisible:false,onToggleListings(){toggled++;return listingsVisible=!listingsVisible;}});
  const visibilityButton=visibility.nodes.find(x=>x.className==='planning-listings-toggle');
  const visibilityToolbar=visibility.nodes.find(x=>x.className==='planning-map-toolbar');
  assert.ok(visibilityToolbar.children.indexOf(visibilityButton)===3,'Listing toggle immediately follows map layers');
  assert.equal(visibilityButton.textContent,'Hiện tin đăng');
  assert.equal(visibilityButton.attributes['aria-pressed'],'false');
  visibilityButton.events.click();assert.equal(toggled,1);
  assert.equal(visibilityButton.textContent,'Ẩn tin đăng');
  assert.equal(visibilityButton.attributes['aria-pressed'],'true');
  visibilityButton.events.click();assert.equal(visibilityButton.textContent,'Hiện tin đăng');
  visibility.dispose();
  const pdf={...catalog.layers[0],id:'thoi-hoa-document',source:'document',manifest:{...manifest,id:'thoi-hoa-document'}};
  const explicit=harness('BẾN CÁT',undefined,undefined,'urban_general');
  explicit.deliver({layers:[catalog.layers[0],general]});await flush();
  assert.equal(explicit.nodes.find(x=>x.attributes['aria-label']==='Bật quy hoạch chung đô thị').checked,true);
  assert.equal(explicit.nodes.find(x=>x.attributes['aria-label']==='Bật quy hoạch phân khu').checked,false);
  assert.equal(explicit.layers.size,1);
  assert.ok([...explicit.layers].every(x=>x.url.includes('ben-cat-general-gis')&&x.options.opacity===.35));
  explicit.dispose();
  const invalidEntry=harness('BẾN CÁT',undefined,undefined,'invalid-theme');
  invalidEntry.deliver({layers:[catalog.layers[0],general]});await flush();
  assert.equal(invalidEntry.layers.size,0);invalidEntry.dispose();
  const h=harness('THỦ DẦU MỘT');h.deliver({layers:[...catalog.layers,pdf,general,tdmWard,tdmGeneral]});await flush();
  const control=name=>h.nodes.find(x=>x.attributes['aria-label']===name);
  const part=control('Bật quy hoạch phân khu'),gen=control('Bật quy hoạch chung đô thị');
  const dock=h.nodes.find(n=>n.className==='planning-layer-dock');
  assert.deepEqual(dock.children.map(n=>n.textContent),['QH SDĐ 2030','QH Chung','QH Phân khu','QH Chi tiết']);
  const partSource=control('Nguồn quy hoạch phân khu'),genSource=control('Nguồn quy hoạch chung đô thị');
  const partSlider=control('Độ hiển thị quy hoạch phân khu'),genSlider=control('Độ hiển thị quy hoạch chung đô thị');
  const inspect=control('Xem hồ sơ và chú giải quy hoạch');
  const change=(el,value)=>{el.value=value;el.events.change();};
  const toggle=(el,checked)=>{el.checked=checked;el.events.change();};
  assert.equal(h.layers.size,0,'Planning tiles stay off until the user enables them');
  assert.equal(part.checked,false);assert.equal(gen.checked,false);
  toggle(part,true);
  assert.equal(h.layers.size,4);
  assert.ok([...h.layers].every(x=>x.options.opacity===.35),'First enable uses 35 percent opacity');
  const quickGen=control('Bật/tắt quy hoạch chung đô thị');
  const quickOpacity=control('Độ hiển thị lớp đang chọn');
  assert.ok(quickGen,'Planning types must be reachable outside the layers popover');
  quickGen.events.click();assert.equal(gen.checked,true);assert.equal(h.layers.size,6);
  const originalLayers=[...h.layers];
  quickOpacity.value='35';quickOpacity.events.input();
  assert.ok([...h.layers].filter(x=>x.url.includes('general')).every(x=>x.options.opacity===.35));
  assert.deepEqual([...h.layers],originalLayers,'Opacity must never rebuild or download images');
  quickGen.events.click();assert.equal(gen.checked,false);
  toggle(gen,true);assert.equal(h.layers.size,6);
  assert.equal(partSource.value,'gis');assert.equal(genSource.value,'gis');
  assert.equal(h.nodes.filter(x=>x.type==='checkbox').length,4,'Only map-type toggles remain');
  assert.ok(!h.nodes.some(x=>x.attributes['aria-label']?.startsWith('Chọn quy hoạch')));
  assert.ok(!h.nodes.some(x=>x.attributes['aria-label']?.startsWith('Chọn toàn bộ quy hoạch')));
  assert.equal(control('Bật các lớp quy hoạch đã chọn'),undefined);
  const fit=h.nodes.find(x=>x.tag==='button'&&x.textContent==='Xem vùng có quy hoạch');
  fit.events.click(); assert.deepEqual(h.map.fitted,[[10.94,106.55],[11.16,106.72]]);
  const credits=[...h.layers].filter(x=>x.url.includes('my-phuoc-2913')||x.url.includes('tdm-phu-cuong'));
  assert.equal(new Set(credits.map(x=>x.options.attribution)).size,1);
  const generalLayer=[...h.layers].find(x=>x.url.includes('ben-cat-general-gis'));
  genSlider.value='20';genSlider.events.input();
  assert.equal(generalLayer.options.opacity,.2);
  assert.ok([...h.layers].filter(x=>!x.url.includes('general')).every(x=>x.options.opacity===.35));
  change(partSource,'document');h.zoom();assert.equal(h.layers.size,3);
  assert.ok(h.layers.has(generalLayer),'Changing one source preserves the other map type');
  assert.ok([...h.layers].some(x=>x.url.includes('thoi-hoa-document')));
  change(partSource,'gis');assert.equal(h.layers.size,6);assert.equal(generalLayer.options.opacity,.2);
  change(genSource,'document');assert.equal(h.layers.size,4,'Missing general PDF never substitutes partition data');
  change(genSource,'gis');assert.equal(h.layers.size,6);
  const failed=[...h.layers].find(x=>x.url.includes('tdm-phu-cuong'));
  const staleLoad=failed.events.load,staleError=failed.events.error;
  failed.events.error();assert.equal(h.layers.size,5);
  assert.ok(h.nodes.some(x=>x.textContent?.includes('Maps vẫn hoạt động')));
  toggle(part,false);h.zoom();assert.equal(h.layers.size,2);assert.equal(partSlider.disabled,true);
  toggle(part,true);h.zoom();assert.equal(h.layers.size,6,'Map-type off/on retries failed images');
  staleLoad();staleError();assert.equal(h.layers.size,6,'Old callbacks cannot remove a replacement layer');
  toggle(gen,false);assert.equal(h.layers.size,4);
  toggle(part,false);assert.equal(h.layers.size,0);assert.equal(fit.disabled,true);
  toggle(gen,true);assert.equal(h.layers.size,2);assert.equal(part.checked,false);
  toggle(part,true);assert.equal(h.layers.size,6);h.zoom();
  change(inspect,'tdm-general');assert.equal(h.layers.size,6,'Inspecting documents never filters the map');
  assert.ok(h.nodes.some(x=>x.tag==='p'&&x.textContent?.includes('Chưa xác minh tỷ lệ')));
  assert.ok(!h.nodes.some(x=>x.tag==='p'&&x.textContent?.includes('Quy hoạch chung · 1/10.000')));
  assert.ok(!h.nodes.some(x=>x.textContent?.includes('undefined')));
  const legend=h.nodes.filter(x=>x.tag==='details')[1];legend.open=true;legend.events.toggle();
  assert.equal(h.nodes.find(x=>x.tag==='img').src,undefined,'No fabricated native GIS legend');
  change(inspect,'hoa-loi-2911-qh01');assert.equal(h.layers.size,6,'Preview-only documents stay off the map');
  partSlider.value='58';partSlider.events.input();
  toggle(part,false);toggle(part,true);
  assert.ok([...h.layers].filter(x=>!x.url.includes('general')).every(x=>x.options.opacity===.58),'Off/on retains user opacity');
  h.dispose();h.dispose();h.zoom();assert.equal(h.layers.size,0);assert.equal(h.signal.aborted,true);
  assert.equal(h.removed,true);assert.deepEqual(h.handlers,{});
  const unavailable=harness();unavailable.deliver({layers:[pdf,{...catalog.layers[0],status:'source_unavailable',manifest:undefined,message:'GIS unavailable'}]});await flush();
  assert.equal(unavailable.layers.size,0,'Unavailable GIS never silently falls back to a PDF');
  const pdfSource=unavailable.nodes.find(x=>x.attributes['aria-label']==='Nguồn quy hoạch phân khu');
  const pdfToggle=unavailable.nodes.find(x=>x.attributes['aria-label']==='Bật quy hoạch phân khu');
  pdfToggle.checked=true;pdfToggle.events.change();
  pdfSource.value='document';pdfSource.events.change();assert.equal(unavailable.layers.size,1);
  unavailable.dispose();unavailable.zoom();
  const cityOnly=harness();cityOnly.deliver({layers:[general,tdmGeneral]});await flush();
  assert.equal(cityOnly.layers.size,0,'General plans stay off until explicitly enabled');
  const cityGeneral=cityOnly.nodes.find(x=>x.attributes['aria-label']==='Bật quy hoạch chung đô thị');
  cityGeneral.checked=true;cityGeneral.events.change();
  assert.equal(cityOnly.layers.size,2,'General plans render when explicitly enabled');
  cityOnly.dispose();cityOnly.zoom();
  const coverage=harness();coverage.deliver({layers:[{...tdmWard,id:'tdm-supplement',
    manifest:{...tdmWard.manifest,id:'tdm-supplement',map_scale:null}}]});await flush();
  const coverageToggle=coverage.nodes.find(x=>x.attributes['aria-label']==='Bật quy hoạch phân khu');
  coverageToggle.checked=true;coverageToggle.events.change();
  assert.equal(coverage.layers.size,1);
  assert.ok(!coverage.nodes.some(x=>x.textContent==='Quy hoạch phân khu · 1/2.000'),
    'A regional GIS supplement must not inherit a verified 1/2000 scale label');
  assert.ok(coverage.nodes.some(x=>x.tag==='p'&&x.textContent?.includes('Phân khu · Chưa xác minh tỷ lệ')));
  coverage.dispose();coverage.zoom();
  const prefix='/static/maps/planning/overlays/0123456789abcdef/';
  const published=harness(undefined,{catalogUrl:prefix+'catalog.json',assetBase:prefix});
  published.deliver({layers:catalog.layers.filter(x=>x.status==='overlay_ready').map(x=>({...x,
    manifest:{...x.manifest,status:'reference_overlay'}}))});await flush();
  assert.deepEqual(published.fetches,[prefix+'catalog.json']);
  const publishedToggle=published.nodes.find(x=>x.attributes['aria-label']==='Bật quy hoạch phân khu');
  publishedToggle.checked=true;publishedToggle.events.change();
  assert.equal(published.layers.size,3);
  assert.ok([...published.layers].every(x=>x.url.startsWith(prefix)));
  assert.ok(!published.nodes.some(x=>x.textContent==='THỬ NGHIỆM LOCAL'));
  published.dispose();published.zoom();
  const nearBounds=[[11.01,106.59],[11.05,106.63]],farBounds=[[11.10,106.60],[11.16,106.70]];
  const lazy=harness(undefined,undefined,nearBounds);
  lazy.deliver({layers:[{...catalog.layers[0],manifest:{...manifest,bounds:nearBounds}},
    {...catalog.layers[1],manifest:{...manifest,id:catalog.layers[1].id,bounds:farBounds}}]});await flush();
  const lazyToggle=lazy.nodes.find(x=>x.attributes['aria-label']==='Bật quy hoạch phân khu');
  lazyToggle.checked=true;lazyToggle.events.change();
  assert.equal(lazy.layers.size,1,'Off-screen images must not start downloading');
  assert.ok([...lazy.layers][0].url.includes(manifest.id));
  lazy.move(farBounds);lazy.zoom();assert.equal(lazy.layers.size,1);
  assert.ok([...lazy.layers][0].url.includes(catalog.layers[1].id),'Panning loads the new region and detaches old zoom handlers');
  lazy.move([[11,106.5],[11.18,106.8]]);assert.equal(lazy.layers.size,2,'Zooming out loads all neighboring visible regions');
  lazy.move([[11.3,106.8],[11.4,106.9]]);lazy.zoom();assert.equal(lazy.layers.size,0);
  lazy.dispose();lazy.zoom();
  const nativePart={...catalog.layers[3],id:'bd-partition-tiles',city:'Bình Dương (cũ)',scope:'region',
    manifest:{...officialManifest,id:'bd-partition-tiles',render_mode:'xyz',tile_size:256,min_zoom:8,max_zoom:23,
      tile_template:'/local-planning/gis-tiles/partition/{z}/{x}/{y}.png'}};
  const nativeGeneral={...nativePart,id:'bd-general-tiles',theme:'urban_general',
    manifest:{...nativePart.manifest,id:'bd-general-tiles',tile_template:'/local-planning/gis-tiles/urban_general/{z}/{x}/{y}.png'}};
  assert.equal(api.validCatalog({layers:[nativePart,nativeGeneral]}),true);
  assert.equal(api.validManifest({...nativePart.manifest,bounds:[[8.5,106.25],[11.65,107.65]]}),true,'Native partition tiles cover the new HCM including islands');
  assert.equal(api.validManifest({...nativeGeneral.manifest,bounds:[[8.5,106.25],[11.65,107.65]]}),true,'General planning covers all three former regions');
  const sourceTiles={primary:'https://api-gisxaydung.tphcm.gov.vn/arcm/rest/services/HCM/SuDungDat_QHC_HCM/MapServer/tile/{z}/{y}/{x}',
    supplement:'https://api-gisxaydung.tphcm.gov.vn/arcm/rest/services/HCM/QHXD_SDD_2025_QHCDT/MapServer/tile/{z}/{y}/{x}'};
  assert.equal(api.validManifest({...nativeGeneral.manifest,source_tiles:sourceTiles}),true);
  assert.equal(api.validManifest({...nativeGeneral.manifest,source_tiles:{...sourceTiles,primary:'https://evil.invalid/tile/{z}/{y}/{x}'}}),false);
  assert.equal(api.validManifest({...nativePart.manifest,source_tiles:sourceTiles}),false,'Do not substitute another planning family');
  assert.equal(api.validManifest({...manifest,bounds:[[8.5,106.25],[11.65,107.65]]}),false,'Old drawing assets keep their verified footprint');
  assert.equal(api.validManifest({...nativePart.manifest,tile_template:'https://evil.invalid/{z}.png'}),false);
  const native=harness(undefined,undefined,nearBounds);
  native.deliver({layers:[{...catalog.layers[3],inspection_only:true},nativePart,nativeGeneral]});await flush();
  const nativeToggle=native.nodes.find(x=>x.attributes['aria-label']==='Bật quy hoạch phân khu');
  nativeToggle.checked=true;nativeToggle.events.change();
  assert.equal(native.layers.size,1,'Archived GIS snapshots must not overpaint the native grid');
  const nativeLayer=[...native.layers][0];assert.equal(nativeLayer.kind,'tile');
  assert.equal(nativeLayer.options.tileSize,256);assert.equal(nativeLayer.options.maxNativeZoom,23);
  native.move(farBounds);native.zoom();assert(native.layers.has(nativeLayer),'Panning/zooming reuses the native tile provider');
  nativeLayer.events.tileerror();assert(native.layers.has(nativeLayer),'One failed tile must not remove the whole GIS collection');
  native.dispose();native.zoom();assert.equal(native.layers.size,0);
  const detail={...nativePart,id:'hcm-detailed-tiles',theme:'detailed',
    manifest:{...nativePart.manifest,id:'hcm-detailed-tiles',bounds:[[8.5,106.25],[11.65,107.65]],
      tile_template:'/local-planning/gis-tiles/detailed/{z}/{x}/{y}.png'}};
  assert.equal(api.validCatalog({layers:[detail]}),true);
  const dt=harness(undefined,undefined,nearBounds);dt.deliver({layers:[nativePart,detail]});await flush();
  const detailedToggle=dt.nodes.find(n=>n.attributes['aria-label']==='Bật quy hoạch chi tiết');
  assert.equal(detailedToggle.checked,false);assert.equal(dt.layers.size,0);
  toggle(detailedToggle,true);const dl=[...dt.layers][0];assert(dl.url.includes('/detailed/'));
  assert.equal(dl.options.opacity,.35);assert.equal(dl.options.maxNativeZoom,23);
  toggle(detailedToggle,false);dt.zoom();assert.equal(dt.layers.size,0);
  toggle(detailedToggle,true);dt.zoom();assert.equal(dt.layers.size,1);
  dt.move([[8.68,106.6],[8.69,106.62]]);assert.equal(dt.layers.size,1);
  dt.dispose();dt.zoom();
  const landuse=require('../config/planning_landuse_2030.json').layers;
  assert.equal(api.validCatalog({layers:landuse}),true);
  assert.equal(api.validCatalog({layers:[{...landuse[0],source:'gis'}]}),false,'Guland must not be relabeled as official GIS');
  assert.equal(api.validManifest({...landuse[0].manifest,tile_template:'https://r4gmiynxmeobj.vcdn.cloud.evil.invalid/binh-duong-2030/{z}/{x}/{y}.png'}),false);
  assert.equal(api.validManifest({...landuse[0].manifest,tile_template:landuse[0].manifest.tile_template+'?token=anything'}),false);
  assert.equal(api.validManifest({...landuse[0].manifest,max_native_zoom:23}),false);
  const lu=harness(undefined,undefined,[[11.2,106.6],[11.21,106.61]]);
  lu.deliver({layers:[{...nativePart,manifest:{...nativePart.manifest,bounds:[[10.75,106.25],[11.65,107.1]]}},...landuse]});await flush();
  const lut=lu.nodes.find(n=>n.attributes['aria-label']==='Bật quy hoạch sử dụng đất 2030');
  assert.equal(lut.checked,false);assert.equal(lu.layers.size,0,'2030 requests must stay off by default');
  toggle(lut,true);assert.equal(lu.layers.size,1);
  assert.equal(lu.nodes.some(n=>/guland/i.test(n.textContent||'')),false,'Visible controls and notes use generic source labels');
  const luLayer=[...lu.layers][0];assert(luLayer.url.includes('binh-duong-2030'));
  assert.equal(luLayer.options.maxNativeZoom,17);assert.equal(luLayer.options.tileSize,256);
  assert.equal(luLayer.options.opacity,.35);
  const lus=lu.nodes.find(n=>n.attributes['aria-label']==='Độ hiển thị quy hoạch sử dụng đất 2030');
  lus.value='60';lus.events.input();assert.equal(luLayer.options.opacity,.6);
  const other=lu.nodes.find(n=>n.attributes['aria-label']==='Bật quy hoạch phân khu');
  toggle(other,true);assert.equal(lu.layers.size,2);
  assert.equal([...lu.layers].find(l=>l!==luLayer).options.opacity,.35,'2030 opacity is independent of partition');
  toggle(lut,false);lu.zoom();assert.equal(lu.layers.size,1);
  toggle(other,false);
  lu.move([[8.68,106.6],[8.69,106.62]]);toggle(lut,true);
  assert.equal(lu.layers.size,1);assert([...lu.layers][0].url.includes('/qh-brvt/sdd/'));
  assert.equal([...lu.layers][0].options.opacity,.6,'Toggling and moving preserve 2030 opacity');
  lu.dispose();lu.zoom();assert.equal(lu.layers.size,0);
  const dn=landuse.find(x=>x.area_id==='dong-nai-expanded');
  assert.equal(api.validManifest({...dn.manifest,min_native_zoom:8}),false,'Source images start at zoom 9');
  assert.equal(api.validManifest({...dn.manifest,bounds:[[10.49,106.39],[13,107.6]]}),false);
  assert.equal(api.validManifest({...landuse[0].manifest,bounds:dn.manifest.bounds}),false,'Existing HCM sources keep their original limits');
  assert.equal(api.validManifest({...dn.manifest,coverage_windows:[[[0,0],[90,180]]]}),false);
  const dnh=harness(undefined,undefined,[[10.93,107.23],[10.94,107.24]],'land_use_2030');
  dnh.deliver({layers:landuse});await flush();assert.equal(dnh.layers.size,1);
  const dnTile=[...dnh.layers][0];assert(dnTile.url.includes('/qh-dong-nai/sdd/'));
  assert.equal(dnh.nodes.find(n=>n.attributes['aria-label']==='Xem hồ sơ và chú giải quy hoạch').value,dn.id,'Source inspector follows the opening region');
  assert.equal(dnTile.options.minNativeZoom,9);assert.equal(dnTile.options.maxNativeZoom,17);
  assert.equal(dnTile._isValidTile({bounds:[[11.12,106.6],[11.13,106.61]]}),false,'Do not request Dong Nai images for Binh Duong-only cells');
  assert.equal(dnTile._isValidTile({bounds:[[11.53,106.88],[11.54,106.89]]}),true);
  dnh.move([[11.53,106.88],[11.54,106.89]]);assert.equal(dnh.layers.size,1);
  assert.equal([...dnh.layers][0],dnTile,'One native layer spans Dong Nai and Binh Phuoc without duplicate opacity');
  dnh.move([[11.12,106.6],[11.13,106.61]]);
  assert.ok(!dnh.layers.has(dnTile),'A Binh Duong-only view does not load Dong Nai imagery');
  dnh.dispose();dnh.zoom();
  const late=harness();late.dispose();late.deliver();await flush();
  assert.equal(late.nodes.find(x=>x.type==='checkbox').disabled,true);assert.equal(late.layers.size,0);
  const invalid=harness();invalid.deliver({...manifest,status:'approved'});await flush();
  assert.equal(invalid.nodes.find(x=>x.type==='checkbox').disabled,true);assert.equal(invalid.layers.size,0);
  invalid.dispose();
  console.log('Planning overlay: viewport loading, layers off by default, independent sources/opacity and zoom lifecycle passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
