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
 const L={control(){const c={addTo(){credits.push(this);this.onAdd();},remove(){credits.splice(credits.indexOf(this),1);}};return c;},DomUtil:{create(){return {}; }},DomEvent:{disableClickPropagation(){}}};
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

test('overview paints only major roads red, with name/ref, and adds no neighbourhood labels',()=>{
 const h=harness(),rules=h.api.paintRules(h.P),major={props:{kind:'primary'}},minor={props:{kind:'residential'}};
 assert.equal(rules[1].symbolizer.options.color,'#dc5555');
 for(const rule of rules){assert.ok(rule.filter(12,major));assert.equal(rule.filter(12,minor),false);assert.equal(rule.filter(15,major),false);}
 assert.equal(h.api.roadLabel({name:'Đại lộ Bình Dương',ref:'QL.13'}),'Đại lộ Bình Dương · QL.13');
 assert.equal(h.api.roadLabel({name:'QL13',ref:'QL.13'}),'QL13');
 assert.equal(h.api.roadLabel({ref:'ĐT.744'}),'ĐT.744');
 const data=new Map([['street_labels',[
  {props:{kind:'trunk',name:'Quốc lộ 13',ref:'QL.13'},geom:[[{x:0,y:0},{x:4,y:5},{x:8,y:10}]]},
  {props:{kind:'trunk',name:'Cầu Ông Cộ',ref:'ĐT.744'},geom:[[{x:1,y:2}]]}
 ]]]);
 h.api.prepareNames(data);
 const label=data.get('radar_major_labels')[0];
 assert.equal(label.props.radar_road_label,'QL13');
 assert.equal(label.geom[0][0].x,4);assert.equal(label.geom[0][0].y,5);
 assert.equal(data.get('radar_major_labels').length,1,'Bridge POI names do not clutter the overview');
 const P={...h.P,CenteredTextSymbolizer:class{place(){return [{}];}}};
 const symbolizer=h.api.labelRules(P).find(rule=>rule.dataLayer==='radar_major_labels').symbolizer;
 const placed=symbolizer.place({},[],{props:{ref:'QL.13'}})[0];
 assert.equal(placed.deduplicationKey,'road-guide:ql13');assert.equal(placed.deduplicationDistance,240);
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

 test('major-road guide is opt-in through transport, independent of street or satellite basemap',async()=>{
 const h=harness(true);h.open();await flush();assert.equal(h.vector,undefined);
 h.events['planning:transport']({enabled:true});await flush();assert.ok(h.active.has(h.vector));
 assert.equal(h.options.paintRules.length,2);assert.ok(h.options.labelRules.every(r=>r.minzoom<15));
 h.street();assert.ok(h.active.has(h.vector),'Transport remains on street basemap');
 h.events['planning:transport']({enabled:false});assert.ok(!h.active.has(h.vector));
 h.events['planning:transport']({enabled:true});await flush();h.zoom(16);assert.ok(!h.active.has(h.vector));
 h.dispose();assert.equal(Object.keys(h.events).length,0);
 });
