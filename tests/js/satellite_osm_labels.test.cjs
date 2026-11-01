const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('static/js/main/satellite_osm_labels.js','utf8');
const flush=()=>new Promise(resolve=>setImmediate(resolve));

function harness(){
 const active=new Set(),events={},tasks=[],credits=[];let zoom=12,options,vector,readFn=async()=>new Map();
 const emitter=()=>({events:{},on(n,fn){this.events[n]=fn;return this;},off(n){delete this.events[n];}});
 const map={hasLayer:l=>active.has(l),getZoom:()=>zoom,on(n,fn){events[n]=fn;},off(n){delete events[n];},fire(n,e){tasks.push(e);},removeLayer(l){active.delete(l);l.events?.remove?.();}};
 const satellite=emitter();
 function Symbolizer(o){this.options=o;}
 const P={LineLabelSymbolizer:Symbolizer,CenteredTextSymbolizer:Symbolizer,leafletLayer(o){options=o;vector=emitter();vector.views=new Map([['',{tileCache:{source:{get:(...args)=>readFn(...args),zoomaborts:[]}}}]]);vector.addTo=()=>{active.add(vector);return vector;};return vector;}};
 const L={control(){const c={addTo(){credits.push(this);this.onAdd();},remove(){credits.splice(credits.indexOf(this),1);}};return c;},DomUtil:{create(){return {}; }},DomEvent:{disableClickPropagation(){}}};
 const window={protomapsL:P};vm.runInNewContext(source,{window});
 const dispose=window.RadarSatelliteLabels.mount(L,map,satellite);
 function open(){active.add(satellite);satellite.events.add();}
 function street(){active.delete(satellite);satellite.events.remove();}
 return {active,events,tasks,credits,open,street,dispose,P,api:window.RadarSatelliteLabels,
  setRead(fn){readFn=fn;},zoom(z){zoom=z;events.zoomend?.();},get vector(){return vector;},get options(){return options;}};
}

test('OSM uses name tags for DX 126, DX 127 and NG2 without painting a street basemap',()=>{
 const h=harness(),rules=h.api.labelRules(h.P),street=rules.find(r=>r.dataLayer==='street_labels'&&r.minzoom===15);
 assert.equal(street.minzoom,15);
 assert.deepEqual(Array.from(street.symbolizer.options.labelProps),['name']);
 assert.equal(street.symbolizer.options.font,'600 12px sans-serif');
 for(const name of ['Đường ĐX 126','Đường Đx 127','Đường NG2'])assert.ok(street.filter(17,{props:{kind:'residential',name}}));
 assert.equal(rules.find(r=>r.dataLayer==='place_labels').minzoom,3);
});

test('zoom, base switching and disposal keep one noninteractive OSM label layer and its visible attribution',async()=>{
 const h=harness();assert.equal(h.vector,undefined,'Street mode does not load satellite names');
 h.open();await flush();assert.ok(h.active.has(h.vector),'Overview names also use OSM');
 h.zoom(16);await flush();assert.ok(h.active.has(h.vector));
 assert.equal(h.options.url,'/api/map-labels/osm/{z}/{x}/{y}.mvt');assert.equal(h.options.maxDataZoom,14);
 assert.equal(h.options.levelDiff,0);assert.equal(h.options.paintRules.length,0);assert.equal(h.options.pane,'satelliteLabels');
 assert.equal(h.credits.length,1);h.zoom(17);assert.equal(h.credits.length,1);
 h.street();assert.ok(!h.active.has(h.vector));assert.equal(h.credits.length,0);
 h.open();await flush();assert.ok(h.active.has(h.vector));assert.equal(h.credits.length,1);
 h.zoom(5);assert.ok(h.active.has(h.vector),'Zooming out never switches to an Esri label layer');
 h.dispose();assert.equal(h.credits.length,0);assert.equal(Object.keys(h.events).length,0);
});

test('pinned vector decoder rejects HTTP failures before parsing error text as an empty tile',()=>{
 const vendor=fs.readFileSync('static/vendor/protomaps-leaflet-4.0.1.js','utf8');
 assert.ok(vendor.includes('if(!c.ok)throw new Error("Vector tile HTTP "+c.status)'));
 assert.ok(!vendor.includes('eval('));
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

test('upstream read failure clears loading without reintroducing Esri labels',async()=>{
 const h=harness();h.open();h.zoom(16);await flush();
 h.setRead(async()=>{throw new Error('Vector tile HTTP 502');});
 await assert.rejects(h.vector.views.get('').tileCache.source.get({z:14,x:13044,y:7687},256));
 assert.ok(!h.active.has(h.vector));assert.equal(h.active.size,1,'Only imagery remains');assert.equal(h.credits.length,0);
});
