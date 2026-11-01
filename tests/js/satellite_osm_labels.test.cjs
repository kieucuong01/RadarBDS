const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('static/js/main/satellite_osm_labels.js','utf8');
const flush=()=>new Promise(resolve=>setImmediate(resolve));

function harness(guide=false){
 const active=new Set(),events={},tasks=[],credits=[];let zoom=12,options,vector,readFn=async()=>new Map();
 const emitter=()=>({events:{},on(n,fn){this.events[n]=fn;return this;},off(n){delete this.events[n];}});
 const map={hasLayer:l=>active.has(l),getZoom:()=>zoom,on(n,fn){events[n]=fn;},off(n){delete events[n];},fire(n,e){tasks.push(e);},removeLayer(l){active.delete(l);l.events?.remove?.();}};
 const satellite=emitter();
 function Symbolizer(o){this.options=o;}
 const P={LineSymbolizer:Symbolizer,LineLabelSymbolizer:Symbolizer,CenteredTextSymbolizer:Symbolizer,leafletLayer(o){options=o;vector=emitter();vector.views=new Map([['',{tileCache:{source:{get:(...args)=>readFn(...args),zoomaborts:[]}}}]]);vector.addTo=()=>{active.add(vector);return vector;};return vector;}};
 const L={tileLayer(url,options){const layer=emitter();layer.addTo=()=>{active.add(layer);return layer;};layer.url=url;layer.options=options;return layer;},control(){const c={addTo(){credits.push(this);this.onAdd();},remove(){credits.splice(credits.indexOf(this),1);}};return c;},DomUtil:{create(){return {}; }},DomEvent:{disableClickPropagation(){}}};
 const window={protomapsL:P,setTimeout,clearTimeout};vm.runInNewContext(source,{window});
 const dispose=window.RadarSatelliteLabels.mount(L,map,satellite,undefined,guide);
 function open(){active.add(satellite);satellite.events.add();}
 function street(){active.delete(satellite);satellite.events.remove();}
 return {active,events,tasks,credits,open,street,dispose,P,api:window.RadarSatelliteLabels,
  setRead(fn){readFn=fn;},zoom(z){zoom=z;events.zoomend?.();},get vector(){return vector;},get options(){return options;}};
}

test('OSM uses name tags for DX 126, DX 127 and NG2 without painting a street basemap',()=>{
 const h=harness(),rules=h.api.labelRules(h.P),street=rules.find(r=>r.dataLayer==='street_labels'&&r.minzoom===15&&r.filter(17,{props:{kind:'residential'}}));
 assert.equal(street.minzoom,15);
 assert.deepEqual(Array.from(street.symbolizer.options.labelProps),['name']);
 assert.equal(street.symbolizer.options.font,'600 12px sans-serif');
 for(const name of ['Đường ĐX 126','Đường Đx 127','Đường NG2'])assert.ok(street.filter(17,{props:{kind:'residential',name}}));
 assert.equal(rules.find(r=>r.dataLayer==='place_labels').minzoom,15);
});

test('zoom, base switching and disposal keep one noninteractive OSM label layer and its visible attribution',async()=>{
 const h=harness();assert.equal(h.vector,undefined,'Street mode does not load satellite names');
 h.open();await flush();assert.equal(h.vector,undefined,'Overview must not initialize the decoder or request vector tiles');
 h.zoom(16);await flush();assert.ok(h.active.has(h.vector));
 assert.equal(h.options.url,'/api/map-labels/osm/{z}/{x}/{y}.mvt');assert.equal(h.options.maxDataZoom,14);
 assert.equal(h.options.levelDiff,0);assert.equal(h.options.paintRules.length,0);assert.equal(h.options.pane,'satelliteLabels');
 assert.equal(h.credits.length,1);h.zoom(17);assert.equal(h.credits.length,1);
 h.street();assert.ok(!h.active.has(h.vector));assert.equal(h.credits.length,0);
 h.open();await flush();assert.ok(h.active.has(h.vector));assert.equal(h.credits.length,1);
 h.zoom(5);assert.ok(!h.active.has(h.vector),'Overview removes the vector layer');assert.equal(h.credits.length,0);
 h.dispose();assert.equal(h.credits.length,0);assert.equal(Object.keys(h.events).length,0);
});

test('pinned vector decoder rejects HTTP failures before parsing error text as an empty tile',()=>{
 const vendor=fs.readFileSync('static/vendor/protomaps-leaflet-4.0.1.js','utf8');
 assert.ok(vendor.includes('if(!c.ok)throw new Error("Vector tile HTTP "+c.status)'));
 assert.ok(!vendor.includes('eval('));
 assert.ok(vendor.includes('fetch(n,{signal:s,credentials:"omit"})'),'Public MVT reads omit dashboard cookies');
});

test('OSM reads are bounded at two and queued work is cancelled on base switch',async()=>{
 const h=harness(),releases=[];let started=0;
 h.setRead(()=>{started++;return new Promise(resolve=>releases.push(resolve));});
 h.open();h.zoom(16);await flush();
 const source=h.vector.views.get('').tileCache.source;
 const result=Promise.allSettled([1,2,3,4].map(x=>source.get({z:14,x,y:7687},256)));
 assert.equal(started,2);
 h.street();releases.forEach(resolve=>resolve(new Map()));
 const outcomes=await result;await flush();
 assert.equal(started,2,'Never start pending reads after switching to streets');
 assert.equal(outcomes.filter(x=>x.status==='rejected'&&x.reason.name==='AbortError').length,2);
});

test('transient tile failure retries once and preserves already loaded labels',async()=>{
 const h=harness();h.open();h.zoom(16);await flush();let reads=0;
 h.setRead(async()=>{if(++reads===1)throw new Error('Vector tile HTTP 502');return new Map();});
 await h.vector.views.get('').tileCache.source.get({z:14,x:13044,y:7687},256);
 assert.equal(reads,2);assert.ok(h.active.has(h.vector));
});

test('permanent tile failure preserves successful tiles without adding a fallback source',async()=>{
 const h=harness();h.open();h.zoom(16);await flush();
 h.setRead(async()=>{throw new Error('Vector tile HTTP 502');});
 await assert.rejects(h.vector.views.get('').tileCache.source.get({z:14,x:13044,y:7687},256));
 assert.ok(h.active.has(h.vector));assert.equal(h.active.size,2,'Imagery and existing OSM labels remain');assert.equal(h.credits.length,1);
});

test('queued requests for an obsolete native zoom never run',async()=>{
 const h=harness(),releases=[];let started=[];
 h.setRead(coords=>{started.push(coords.z);return new Promise(resolve=>releases.push(resolve));});
 h.open();h.zoom(16);await flush();const source=h.vector.views.get('').tileCache.source;
 const jobs=[1,2,3].map(x=>source.get({z:14,x,y:7687},256));
 const done=Promise.allSettled(jobs);
 const next=source.get({z:13,x:6522,y:3840},256);
 releases.splice(0).forEach(resolve=>resolve(new Map()));await flush();
 assert.deepEqual(started,[14,14,13]);releases.splice(0).forEach(resolve=>resolve(new Map()));
 await next;const results=await done;assert.equal(results.filter(r=>r.status==='rejected'&&r.reason.name==='AbortError').length,1);
});

test('switching basemap cancels a pending retry immediately',async()=>{
 const h=harness();h.open();h.zoom(16);await flush();let reads=0,settled=false;
 h.setRead(async()=>{reads++;throw new Error('Vector tile HTTP 503');});
 const result=h.vector.views.get('').tileCache.source.get({z:14,x:13044,y:7687},256).catch(error=>{settled=true;return error;});
 await flush();h.street();await flush();
 assert.equal(settled,true);assert.equal((await result).name,'AbortError');assert.equal(reads,1);
});


test('overview is a ready-made Esri raster, removed at detail zoom and when satellite is off',async()=>{
 const h=harness();h.open();await flush();
 const raster=Array.from(h.active).find(layer=>layer.url);
 assert.ok(raster.url.includes('World_Hybrid_Overlay'));assert.equal(raster.options.maxZoom,14);
 assert.equal(h.vector,undefined,'No OSM decoder layer is created at overview');
 h.zoom(16);await flush();assert(!h.active.has(raster));assert(h.active.has(h.vector));
 h.zoom(12);assert(h.active.has(raster));assert(!h.active.has(h.vector));
 h.street();assert(!h.active.has(raster));
 h.open();assert(h.active.has(raster));h.dispose();assert(!h.active.has(raster));
});
