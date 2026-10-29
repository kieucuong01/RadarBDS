const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const api=require('../../static/js/main/planning_transport.js');
const data=JSON.parse(fs.readFileSync(require('node:path').join(__dirname,'../../static/data/planning_transport_roads.geojson'),'utf8'));
const flush=()=>new Promise(r=>setImmediate(r));

test('GIS transport keeps original road provenance and never reintroduces the yellow raster',()=>{
 assert(api.valid(data));assert.equal(data.features.length,73);
 assert.equal(data.features.filter(f=>f.properties.group==='corridor').length,11);
 assert.equal(data.features.filter(f=>f.properties.group==='ring').length,16);
 assert(data.features.some(f=>f.properties.group==='ring2'));
 assert(data.features.some(f=>f.properties.group==='ring1_segments'));
 assert(data.notice.includes('chưa xác minh tuyến khép kín'));
 for(const f of data.features){assert.notEqual(api.style(f,1).color,'#ffff00');}
 const config=JSON.parse(fs.readFileSync(require('node:path').join(__dirname,'../../config/planning_transport.json'),'utf8'));
 assert(!JSON.stringify(config).includes('hcm-road-2'));
 const altered=structuredClone(data);altered.features[0].geometry.coordinates[0][0][0]=NaN;assert(!api.valid(altered));
 const unverified=structuredClone(data);unverified.features[0].properties.source_service='unverified';assert(!api.valid(unverified));
 assert(!api.valid({...data,features:[...data.features,...Array(200).fill(data.features[0])]}));
});
function harness(){
 const handlers=new Map();let bounds=[[10.7,106.5],[10.9,106.8]],resolve,fetches=0;
 const map={getZoom:()=>12,getBounds:()=>({intersects:b=>bounds[0][0]<=b[1][0]&&bounds[1][0]>=b[0][0]&&bounds[0][1]<=b[1][1]&&bounds[1][1]>=b[0][1]}),
  on(k,fn){if(!handlers.has(k))handlers.set(k,new Set());handlers.get(k).add(fn);},off(k,fn){handlers.get(k)?.delete(fn);}};
 const env={document:{createElement:()=>({textContent:''})},fetch(url){assert.equal(url,api.url);fetches++;return new Promise(r=>resolve=r);}};
 const L={geoJSON(_,opts){const events=new Map();return {opts,features:[],labels:[],style:null,
   on(k,fn){if(!events.has(k))events.set(k,[]);events.get(k).push(fn);return this;},
   eachLayer(){},fire(k){for(const f of events.get(k)||[])f();return this;},clearLayers(){this.features=[];this.labels=[];},
   addData(f){this.features.push(f);opts.onEachFeature(f,{bindTooltip:(text)=>this.labels.push(text.textContent)});},setStyle(s){this.style=s;}};}};
 const options={pane:'planningTransportRoads',opacity:1,attribution:'GIS'};
 const create=()=>api.create(map,L,env,{},options);
 return {create,env,handlers,get fetches(){return fetches;},deliver(d=data){resolve({ok:true,json:async()=>d});},move(b){bounds=b;for(const fn of handlers.get('moveend')||[])fn();}};
}
test('vector roads load lazily, ignore late data after hiding, reuse cached data and filter the viewport',async()=>{
 const h=harness(),layer=h.create();assert.equal(h.fetches,0);
 layer.fire('add');assert.equal(h.fetches,1);layer.setOpacity(.6);layer.fire('remove');h.deliver();await flush();
 assert.equal(layer.features.length,0,'A late response cannot restore hidden roads');
 layer.fire('add');assert.equal(h.fetches,1);assert(layer.features.length>0);
 assert.equal(layer.opts.style(layer.features[0]).opacity,.6);
 h.move([[13,106],[13.1,106.1]]);assert.equal(layer.features.length,0);
 h.move([[10.7,106.5],[10.9,106.8]]);assert(layer.features.length>0);
 assert(layer.labels.every(t=>typeof t==='string'));
 layer.fire('remove');assert.equal(h.handlers.get('moveend').size,0);
 const second=h.create();second.fire('add');assert.equal(h.fetches,1);assert(second.features.length>0);second.fire('remove');
});
test('invalid GIS road data fails closed',async()=>{
 const h=harness(),layer=h.create();let errors=0;layer.on('error',()=>errors++);layer.fire('add');h.deliver({type:'FeatureCollection',features:[]});await flush();
 assert.equal(errors,1);assert.equal(layer.features.length,0);layer.fire('remove');
});
