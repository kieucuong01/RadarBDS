const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const api=require('../../static/js/main/planning_administrative.js');
const directory=path.join(__dirname,'../../static/data/admin_hcm_2025');
const overview=JSON.parse(fs.readFileSync(path.join(directory,'overview.json'),'utf8'));
const flush=()=>new Promise(r=>setImmediate(r));
test('administrative source includes exactly 168 unique units and Con Dao with bounded geometry',()=>{
 assert(api.valid(overview));assert.equal(overview.features.length,168);
 assert(overview.features.some(f=>f.properties.name==='Đặc khu Côn Đảo'));
 for(const f of overview.features){const full=JSON.parse(fs.readFileSync(path.join(directory,f.properties.code+'.json'),'utf8'));assert(api.validFeature(full,f.properties));}
 const duplicate=structuredClone(overview);duplicate.features[1]=duplicate.features[0];assert(!api.valid(duplicate));
 const malformed=structuredClone(overview);malformed.features[0].geometry.coordinates=[[[0,0],[1,0],[1,1],[0,0]]];assert(!api.valid(malformed));
 assert(!api.valid({...overview,features:overview.features.slice(1)}));
 const f=overview.features[0];assert(!api.validFeature({...f,properties:{...f.properties,code:'../bad'}}));
});
function harness(){
 let zoom=10,viewport=[[8.5,106.25],[11.65,107.75]];const handlers=new Set(),calls=[],requests=[],interactions=new Map(),views=[],events=new Map();
 const container={classList:{contains:()=>false}};
 const map={getContainer:()=>container,getMaxZoom:()=>19,getBoundsZoom:()=>14,setView:(point,z)=>views.push({point,zoom:z}),getZoom:()=>zoom,getSize:()=>({x:1280,y:800}),latLngToContainerPoint:()=>({x:200,y:200}),
  getBounds:()=>({intersects:b=>viewport[0][0]<=b[1][0]&&viewport[1][0]>=b[0][0]&&viewport[0][1]<=b[1][1]&&viewport[1][1]>=b[0][1]}),
  on(k,fn){handlers.add(fn);if(!events.has(k))events.set(k,new Set());events.get(k).add(fn);},off(k,fn){handlers.delete(fn);if(events.has(k))events.get(k).delete(fn);}};
 function group(children=[]){const events=new Map();return {children,options:{},on(k,fn){if(!events.has(k))events.set(k,[]);events.get(k).push(fn);return this;},
  fire(k){for(const fn of events.get(k)||[])fn();return this;},clearLayers(){this.children=[];},addLayer(x){this.children.push(x);},getLayers(){return this.children.slice();},removeLayer(x){this.children=this.children.filter(c=>c!==x);},eachLayer(fn){this.children.forEach(fn);}};}
 const L={layerGroup:group,geoJSON(_,opts){return {...group(),opts,drawCount:0,addData(f){this.drawCount++;this.children.push(f);if(opts.onEachFeature){const polygon={bindTooltip(text,options){this.tooltip={text,options};return this;},on(type,fn){this[type]=fn;return this;}};opts.onEachFeature(f,polygon);interactions.set(f.properties.code,polygon);}},setStyle(s){this.style=s;}};},
  divIcon:x=>x,marker(point,opts){return {point,opts,setOpacity(v){this.opts.opacity=v;},addTo(target){target.addLayer(this);return this;}};}};
 const env={document:{createElement:()=>({style:{},textContent:''})},fetch(url){calls.push(url);return new Promise(resolve=>requests.push({url,resolve}));}};
 const create=(manifest={})=>api.create(map,L,env,manifest, {opacity:1,attribution:'GIS'});
 function deliver(request,data){request.resolve({ok:true,json:async()=>data});}
 return {create,calls,requests,handlers,interactions,views,container,deliver,start(){for(const fn of events.get('movestart')||[])fn();},move(b,z=zoom){viewport=b;zoom=z;for(const fn of events.get('moveend')||[])fn();}};
}
test('overview is lazy, ignores hidden late responses, and cached toggles do not re-download',async()=>{
 const h=harness(),root=h.create();assert.equal(h.calls.length,0);root.fire('add');assert.equal(h.calls.length,1);
 root.fire('remove');h.deliver(h.requests[0],overview);await flush();assert.equal(root.children[0].children.length,0);
 root.fire('add');assert.equal(h.calls.length,1);assert(root.children[0].children.length>0);
 assert(h.calls.every(url=>url.includes('overview.json')),'No full-geometry requests below zoom 13');
 root.setOpacity(.6);assert.equal(root.children[0].style.fillOpacity,.6*.17);
 root.fire('remove');assert.equal(h.handlers.size,0);
 const next=h.create();next.fire('add');assert.equal(h.calls.length,1);next.fire('remove');
});
test('detail requests are bounded and a viewport move replaces queued wards',async()=>{
 const h=harness(),root=h.create();root.fire('add');h.deliver(h.requests[0],overview);await flush();
 h.move([[8.5,106.25],[11.65,107.75]],13);assert.equal(h.requests.length,5,'At most four full-geometry requests start');
 root.fire('remove');const replacement=h.create();replacement.fire('add');
 assert.equal(h.requests.length,5,'Rapid off/on does not duplicate or exceed four in-flight detail requests');
 h.move([[8.63,106.53],[8.77,106.75]],13);
 for(const r of h.requests.slice(1,5)){const code=r.url.match(/\/(\d{5})\.json/)[1];h.deliver(r,JSON.parse(fs.readFileSync(path.join(directory,code+'.json'),'utf8')));}
 await flush();
 const newRequests=h.requests.slice(5);assert(newRequests.length>0);assert(newRequests.every(r=>r.url.includes('/26732.json')),'Do not fetch old viewport wards after panning to Con Dao');
 const request=newRequests[0];h.deliver(request,JSON.parse(fs.readFileSync(path.join(directory,'26732.json'),'utf8')));await flush();
 assert(replacement.children[0].children.every(f=>f.properties.name==='Đặc khu Côn Đảo'));
 replacement.fire('remove');assert.equal(h.handlers.size,0);
});
test('panning retains unchanged polygons and one detail response replaces only its own geometry',async()=>{
 const h=harness(),root=h.create();root.fire('add');h.deliver(h.requests[0],overview);await flush();
 const areas=root.children[0],before=areas.children.slice(),count=areas.drawCount;
 h.move([[8.5,106.25],[11.65,107.75]],10);
 assert.equal(areas.drawCount,count,'A settled move with the same visible wards must not recreate polygons');
 assert.deepEqual(areas.children,before);
 h.move([[8.5,106.25],[11.65,107.75]],13);
 const request=h.requests[1],code=request.url.match(/\/(\d{5})\.json/)[1];
 h.deliver(request,JSON.parse(fs.readFileSync(path.join(directory,code+'.json'),'utf8')));await flush();
 assert.equal(areas.drawCount,count+1,'Only the arriving detail geometry is painted');
 assert.equal(root.children.length,1,'No permanent label layer');
 assert.equal(areas.children.length,168);
 h.move([[8.63,106.53],[8.77,106.75]],10);
 assert(areas.children.every(f=>f.properties.code==='26732'),'Offscreen polygons are removed');root.fire('remove');
});

test('Dong Nai has 95 units, preserves strict HCM validation and isolates source caches',async()=>{
 const dnDir=path.join(__dirname,'../../static/data/admin_dongnai_2025');
 const dn=JSON.parse(fs.readFileSync(path.join(dnDir,'overview.json'),'utf8'));
 assert(api.valid(dn,'dongnai-administrative-2025'));
 assert(!api.valid(dn));assert(!api.valid(overview,'dongnai-administrative-2025'));
 for(const f of dn.features)assert(api.validFeature(JSON.parse(fs.readFileSync(path.join(dnDir,f.properties.code+'.json'),'utf8')),f.properties,'dongnai-administrative-2025'));
 const h=harness(),hcm=h.create();hcm.fire('add');h.deliver(h.requests[0],overview);await flush();hcm.fire('remove');
 const layer=h.create({id:'dongnai-administrative-2025'});layer.fire('add');
 assert.equal(h.calls.length,2);assert(h.calls[1].includes('/admin_dongnai_2025/'));
 h.deliver(h.requests[1],dn);await flush();assert(layer.children[0].children.length>0);
 layer.fire('remove');h.create({id:'dongnai-administrative-2025'}).fire('add');assert.equal(h.calls.length,2);
});

test('catalog accepts only the curated Dong Nai source and both historic provinces',()=>{
 const overlay=require('../../static/js/main/planning_overlay.js'),area=require('../../static/js/main/planning_area.js');
 const catalog=require('../../config/planning_administrative.json'),dn=catalog.layers[1];
 assert(overlay.validCatalog(catalog));
 assert(!overlay.validCatalog({layers:[{...dn,source_url:'https://github.com/unknown/boundaries'}]}));
 assert(!overlay.validManifest({...dn.manifest,unit_count:94}));
 assert(!overlay.validManifest({...dn.manifest,geojson_url:'/remote.json'}));
 assert(area.coversProvince(dn,{id:'dong-nai'}));assert(area.coversProvince(dn,{id:'binh-phuoc'}));
 assert(!area.coversProvince(dn,{id:'binh-duong'}));
});


test('ward names appear only as hover tooltips and clicks zoom to the ward',async()=>{
 const h=harness(),root=h.create();root.fire('add');h.deliver(h.requests[0],overview);await flush();
 assert.equal(root.children.length,1,'Remove permanent ward name markers');
 const f=overview.features[0],polygon=h.interactions.get(f.properties.code);
 assert(polygon);assert.equal(polygon.tooltip.text.textContent,f.properties.name);
 assert.equal(polygon.tooltip.options.permanent,false);assert.equal(polygon.tooltip.options.sticky,true);
 assert.equal(root.children[0].opts.bubblingMouseEvents,false);
 polygon.click();assert.deepEqual(h.views[0],{point:f.properties.label,zoom:14});
 h.move([[8.5,106.25],[11.65,107.75]],17);polygon.click();assert.equal(h.views[1].zoom,18,'Already close: never zoom out');
 h.container.classList.contains=()=>true;polygon.click();assert.equal(h.views.length,2,'Drawing mode takes priority');
 root.fire('remove');polygon.click();assert.equal(h.views.length,2,'Removed layers cannot move map');
});


test('animation pauses detail queues until the new viewport settles',async()=>{
 const h=harness(),root=h.create();root.fire('add');h.deliver(h.requests[0],overview);await flush();
 h.move([[8.5,106.25],[11.65,107.75]],13);assert.equal(h.requests.length,5);
 h.start();
 for(const r of h.requests.slice(1,5)){const code=r.url.match(/\/(\d{5})\.json/)[1];h.deliver(r,JSON.parse(fs.readFileSync(path.join(directory,code+'.json'),'utf8')));}
 await flush();assert.equal(h.requests.length,5,'No replacement requests from an animating old viewport');
 h.move([[8.63,106.53],[8.77,106.75]],13);
 assert(h.requests.slice(5).every(r=>r.url.includes('/26732.json')));
 assert.equal(h.requests.length,6);root.fire('remove');assert.equal(h.handlers.size,0);
});
