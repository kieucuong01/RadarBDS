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
 let zoom=10,viewport=[[8.5,106.25],[11.65,107.75]];const handlers=new Set(),calls=[],requests=[];
 const map={getZoom:()=>zoom,getSize:()=>({x:1280,y:800}),latLngToContainerPoint:()=>({x:200,y:200}),
  getBounds:()=>({intersects:b=>viewport[0][0]<=b[1][0]&&viewport[1][0]>=b[0][0]&&viewport[0][1]<=b[1][1]&&viewport[1][1]>=b[0][1]}),
  on(k,fn){handlers.add(fn);},off(k,fn){handlers.delete(fn);}};
 function group(children=[]){const events=new Map();return {children,options:{},on(k,fn){if(!events.has(k))events.set(k,[]);events.get(k).push(fn);return this;},
  fire(k){for(const fn of events.get(k)||[])fn();return this;},clearLayers(){this.children=[];},addLayer(x){this.children.push(x);},eachLayer(fn){this.children.forEach(fn);}};}
 const L={layerGroup:group,geoJSON(_,opts){return {...group(),opts,addData(f){this.children.push(f);},setStyle(s){this.style=s;}};},
  divIcon:x=>x,marker(point,opts){return {point,opts,setOpacity(v){this.opts.opacity=v;},addTo(target){target.addLayer(this);return this;}};}};
 const env={document:{createElement:()=>({style:{},textContent:''})},fetch(url){calls.push(url);return new Promise(resolve=>requests.push({url,resolve}));}};
 const create=()=>api.create(map,L,env,{}, {opacity:1,attribution:'GIS'});
 function deliver(request,data){request.resolve({ok:true,json:async()=>data});}
 return {create,calls,requests,handlers,deliver,move(b,z=zoom){viewport=b;zoom=z;[...handlers].forEach(fn=>fn());}};
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
