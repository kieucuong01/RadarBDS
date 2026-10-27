const assert = require('node:assert/strict');
const api = require('../static/js/main/planning_overlay.js');

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

function harness(cityValue, publicConfig) {
  const nodes = [], layers = new Set(), handlers = {}, zoomHandlers = new Set();
  let resolveFetch, removed = false, signal;
  const fetches=[];
  const env = {AbortController, RADAR_PLANNING_CONFIG:publicConfig, matchMedia: () => ({matches: false}),
    document: {getElementById(id) {return id==='cityInput'?{value:cityValue}:null;}, createElement(tag) {
      const el = {tag, style: {}, events: {}, attributes: {}, children: [],
        appendChild(child) {this.children.push(child);},
        setAttribute(k,v) {this.attributes[k]=v;}, getAttribute(k) {return this.attributes[k];},
        removeAttribute(k) {delete this.attributes[k];},
        addEventListener(k,fn) {this.events[k]=fn;}};
      nodes.push(el); return el;
    }},
    fetch(url, options) {fetches.push(url);signal=options.signal; return new Promise(r=>{resolveFetch=r;});}};
  const map = {createPane: () => ({style: {}}), removeLayer(x) {
      layers.delete(x); x.attached=false;
      if (x.events.remove) x.events.remove();
    },
    on(k,fn) {handlers[k]=fn;}, off(k) {delete handlers[k];},
    getBounds: () => ({intersects: () => true}), fitBounds(bounds) {this.fitted=bounds;}};
  const L = {DomEvent: {disableClickPropagation() {}, disableScrollPropagation() {}},
    control: () => ({addTo() {}, remove() {removed=true;}}),
    imageOverlay(url,bounds,options) {
      return {events: {}, options, url, on(k,fn) {this.events[k]=fn;}, off() {this.events={};},
        addTo() {
          layers.add(this); this.attached=true;
          const zoom=()=>assert.equal(this.attached,true,'Detached layer retained a zoom handler');
          zoomHandlers.add(zoom);
          // Leaflet registers its own remove listener to unbind map events.
          this.events.remove=()=>zoomHandlers.delete(zoom);
        }, setOpacity(value) {this.options.opacity=value;}};
    }};
  const dispose = api.mount(map,L,env);
  return {nodes,layers,handlers,dispose,map,fetches, zoom() {zoomHandlers.forEach(fn=>fn());},
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
  assert.equal(api.opacity(120),1); assert.equal(api.opacity(-5),0); assert.equal(api.opacity('bad'),.65);
  const general={...catalog.layers[0],id:'ben-cat-general-gis',name:'Bến Cát',city:'Bến Cát',theme:'urban_general',scope:'city',
    manifest:{...officialManifest,id:'ben-cat-general-gis',map_scale:10000}};
  const tdmWard={...catalog.layers[3],id:'tdm-phu-cuong',name:'Phú Cường',city:'Thủ Dầu Một',
    manifest:{...officialManifest,id:'tdm-phu-cuong',map_scale:2000,bounds:[[10.94,106.63],[11.09,106.72]]}};
  const tdmGeneral={...general,id:'tdm-general',name:'Thủ Dầu Một',city:'Thủ Dầu Một',
    manifest:{...tdmWard.manifest,id:'tdm-general',map_scale:null}};
  const pdf={...catalog.layers[0],id:'thoi-hoa-document',source:'document',manifest:{...manifest,id:'thoi-hoa-document'}};
  const h=harness('THỦ DẦU MỘT');h.deliver({layers:[...catalog.layers,pdf,general,tdmWard,tdmGeneral]});await flush();
  const control=name=>h.nodes.find(x=>x.attributes['aria-label']===name);
  const part=control('Bật quy hoạch phân khu'),gen=control('Bật quy hoạch chung đô thị');
  const partSource=control('Nguồn quy hoạch phân khu'),genSource=control('Nguồn quy hoạch chung đô thị');
  const partSlider=control('Độ hiển thị quy hoạch phân khu'),genSlider=control('Độ hiển thị quy hoạch chung đô thị');
  const inspect=control('Xem hồ sơ và chú giải quy hoạch');
  const change=(el,value)=>{el.value=value;el.events.change();};
  const toggle=(el,checked)=>{el.checked=checked;el.events.change();};
  assert.equal(h.layers.size,6,'All available GIS layers across both cities render immediately');
  assert.equal(part.checked,true);assert.equal(gen.checked,true);
  assert.equal(partSource.value,'gis');assert.equal(genSource.value,'gis');
  assert.equal(h.nodes.filter(x=>x.type==='checkbox').length,2,'Only map-type toggles remain');
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
  assert.ok([...h.layers].filter(x=>!x.url.includes('general')).every(x=>x.options.opacity===.65));
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
  h.dispose();h.dispose();h.zoom();assert.equal(h.layers.size,0);assert.equal(h.signal.aborted,true);
  assert.equal(h.removed,true);assert.deepEqual(h.handlers,{});
  const unavailable=harness();unavailable.deliver({layers:[pdf,{...catalog.layers[0],status:'source_unavailable',manifest:undefined,message:'GIS unavailable'}]});await flush();
  assert.equal(unavailable.layers.size,0,'Unavailable GIS never silently falls back to a PDF');
  const pdfSource=unavailable.nodes.find(x=>x.attributes['aria-label']==='Nguồn quy hoạch phân khu');
  pdfSource.value='document';pdfSource.events.change();assert.equal(unavailable.layers.size,1);
  unavailable.dispose();unavailable.zoom();
  const cityOnly=harness();cityOnly.deliver({layers:[general,tdmGeneral]});await flush();
  assert.equal(cityOnly.layers.size,2,'City-wide general sources render without any ward catalogue');
  cityOnly.dispose();cityOnly.zoom();
  const coverage=harness();coverage.deliver({layers:[{...tdmWard,id:'tdm-supplement',
    manifest:{...tdmWard.manifest,id:'tdm-supplement',map_scale:null}}]});await flush();
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
  assert.equal(published.layers.size,3);
  assert.ok([...published.layers].every(x=>x.url.startsWith(prefix)));
  assert.ok(!published.nodes.some(x=>x.textContent==='THỬ NGHIỆM LOCAL'));
  published.dispose();published.zoom();
  const late=harness();late.dispose();late.deliver();await flush();
  assert.equal(late.nodes.find(x=>x.type==='checkbox').disabled,true);assert.equal(late.layers.size,0);
  const invalid=harness();invalid.deliver({...manifest,status:'approved'});await flush();
  assert.equal(invalid.nodes.find(x=>x.type==='checkbox').disabled,true);assert.equal(invalid.layers.size,0);
  invalid.dispose();
  console.log('Planning overlay: all-area defaults, independent types/sources/opacity, retry/zoom and lifecycle passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
