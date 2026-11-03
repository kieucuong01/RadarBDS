const test=require('node:test'),assert=require('node:assert/strict');
const api=require('../../static/js/main/planning_parcel_cells.js');
const flush=()=>new Promise(resolve=>setImmediate(resolve));
function harness(featureTemplate,liveTemplate){
 let enabled=true,x=52177,y=30749;const pending=[],polygons=[],status=[],frames=[];
 const groups=[],listeners={},domEvents=[];let hit=null;const canvas={style:{},addEventListener:(n,f)=>listeners[n]=f,removeEventListener:n=>delete listeners[n]};const renderer={_container:canvas,on(n,f){if(n==='add')f();}};
 const L={layerGroup(){const members=new Set(),g={members,addTo(){return g;},addLayer(l){members.add(l);},removeLayer(l){members.delete(l);},clearLayers(){members.clear();}};groups.push(g);return g;},
 stamp:el=>el.id,canvas:()=>renderer,geoJSON(f,options){const layer={feature:f};polygons.push(layer);options.onEachFeature(f,{bindTooltip(text){layer.tooltip=text;},on(n,fn){layer[n]=fn;}});return layer;},DomEvent:{stopPropagation(){}}};
 const env={document:{elementsFromPoint:()=>hit?[canvas,hit]:[canvas]},MouseEvent:class {constructor(type,values){this.type=type;Object.assign(this,values);}},AbortController,setTimeout,clearTimeout,requestAnimationFrame(fn){frames.push(fn);return frames.length;},cancelAnimationFrame(){},fetch(url,options){return new Promise((resolve,reject)=>pending.push({url,options,resolve,reject}));}};
 function lng(a){return a/65536*360-180;}function lat(b){return Math.atan(Math.sinh(Math.PI*(1-2*b/65536)))*180/Math.PI;}
 const bounds=()=>({getWest:()=>lng(x+.1),getEast:()=>lng(x+.9),getNorth:()=>lat(y+.1),getSouth:()=>lat(y+.9)});
 const map={_targets:{},getBounds:bounds,removeLayer(g){if(g.clearLayers)g.clearLayers();}};
 const selected=[];
 const controller=api.mount(map,L,env,{featureTemplate,liveTemplate,zoom:16,template:'/api/planning/parcel-cells/version/{x}/{y}.json',enabled:()=>enabled,status:(...args)=>status.push(args),select:f=>selected.push(f)});
 function deliver(i,ids,display=false,needsLive=false){pending[i].resolve({ok:true,json:async()=>({type:'FeatureCollection',needs_live:needsLive,features:ids.map(id=>({type:'Feature',id,display_only:display,properties:{parcel:id},geometry:{type:'Polygon',coordinates:[[[lng(x+.5),lat(y+.5)],[lng(x+.6),lat(y+.6)],[lng(x+.5),lat(y+.5)]]]} }))})});}
 return {renderer,listeners,canvas,domEvents,map,setHit(el){hit=el;},controller,pending,polygons,status,selected,frames,groups,deliver,setX(v){x=v;},disable(){enabled=false;},enable(){enabled=true;},tick(){while(frames.length)frames.shift()();}};
}
test('fixed cells reuse warm data, keep existing geometry and avoid duplicate parcel objects',async()=>{
 const h=harness();h.controller.update();assert.equal(h.pending.length,1);assert.equal(h.pending[0].options.credentials,'omit');h.deliver(0,[1,2]);await flush();
 assert.equal(h.polygons.length,2);assert.equal(h.polygons[0].tooltip,'Tờ — · Thửa 1');h.polygons[0].click({});assert.equal(h.selected[0].id,1);
 h.controller.update();assert.equal(h.pending.length,1,'Same cell makes no new requests');assert.equal(h.polygons.length,2);
 h.setX(52178);h.controller.update();h.deliver(1,[2,3]);await flush();
 h.setX(52177);h.controller.update();assert.equal(h.pending.length,2,'Returning to a warm cell never fetches');
 assert.equal(h.groups[0].members.size,2);h.controller.dispose();assert.equal(h.groups[0].members.size,0);
});
test('obsolete fetches are cancelled and cannot paint, disabled view clears geometry',async()=>{
 const h=harness();h.controller.update();h.setX(52178);h.controller.update();
 assert(h.pending[0].options.signal.aborted);h.deliver(0,[99]);h.deliver(1,[1]);await flush();
 assert(!h.polygons.some(p=>p.feature.id===99));h.disable();h.controller.update();assert.equal(h.groups[0].members.size,0);h.controller.dispose();
});
test('painting large responses is split into bounded animation frames',async()=>{
 const h=harness();h.controller.update();h.deliver(0,Array.from({length:500},(_,i)=>i));await flush();
 assert.equal(h.polygons.length,75);h.tick();assert.equal(h.polygons.length,500);h.controller.dispose();
});
test('failed cells preserve successful geometry and report incomplete state',async()=>{
 const h=harness();h.controller.update();h.pending[0].resolve({ok:false});await flush();
 assert(h.status.at(-1)[0].includes('chưa tải'));assert.equal(h.status.at(-1)[1],false);h.controller.dispose();
});

test('simplified display resolves original geometry locally and never calls GIS planning',async()=>{
 const h=harness('/api/planning/parcel-original/version/{id}.json');h.controller.update();h.deliver(0,[1],true);await flush();
 h.polygons[0].click({});assert.equal(h.selected[0].display_only,true);assert.equal(h.pending.length,2);
 assert(h.pending[1].url.includes('/parcel-original/'));assert(!h.pending[1].url.includes('/planning.json'));
 const original={type:'Feature',id:1,properties:{area:100},geometry:{type:'Polygon',coordinates:[]}};
 h.pending[1].resolve({ok:true,json:async()=>original});await flush();assert.equal(h.selected.at(-1),original);
 h.polygons[0].click({});assert.equal(h.pending.length,2,'Warm original geometry is reused');h.controller.dispose();
});
test('closing a parcel cancels its original read and a late response cannot reopen it',async()=>{
 const h=harness('/api/planning/parcel-original/version/{id}.json');h.controller.update();h.deliver(0,[1],true);await flush();
 h.polygons[0].click({});h.controller.cancelSelection();assert(h.pending[1].options.signal.aborted);
 h.pending[1].resolve({ok:true,json:async()=>({type:'Feature',id:1})});await flush();assert.equal(h.selected.length,1);h.controller.dispose();
});

test('snapshot geometry appears before a slow live supplement and survives live errors',async()=>{
 const h=harness(undefined,'/api/planning/parcel-cells/version/live/{x}/{y}.json');
 h.controller.update();h.deliver(0,[1],true,true);await flush();
 assert.equal(h.polygons.length,1);assert.equal(h.pending.length,2);assert(h.pending[1].url.includes('/live/'));
 h.pending[1].resolve({ok:false,status:502});await flush();assert.equal(h.groups[0].members.size,1);
 h.controller.update();assert.equal(h.pending.length,2,'Busy sources cool down instead of repeating on every small pan');h.controller.dispose();
});


test('canvas hover forwards only empty parcel space and cancels listener on disposal',()=>{
 const h=harness(),events=[];let closed=0;
 const path={id:9,dispatchEvent:event=>events.push(event.type)};
 h.map._targets[9]={closeTooltip(){closed++;}};h.setHit(path);
 h.listeners.mousemove({target:h.canvas,clientX:20,clientY:30});h.tick();
 assert.deepEqual(events,['mouseover','mousemove']);
 h.renderer._hoveredLayer={};h.listeners.mousemove({target:h.canvas,clientX:20,clientY:30});h.tick();
 assert.equal(events.at(-1),'mouseout');assert.ok(closed>0);
 h.controller.dispose();assert.equal(h.listeners.mousemove,undefined);
});


test('disabled or empty parcel canvas releases pointers and reenabling restores hover',async()=>{
 const h=harness();h.controller.update();h.deliver(0,[1]);await flush();
 assert.equal(h.canvas.style.pointerEvents,'auto');
 let closed=0;h.renderer._hoveredLayer={closeTooltip(){closed++;}};
 h.disable();h.controller.update();
 assert.equal(h.canvas.style.pointerEvents,'none');assert.equal(closed,1);assert.equal(h.renderer._hoveredLayer,null);
 h.enable();h.controller.update();assert.equal(h.canvas.style.pointerEvents,'auto');
 h.controller.pause();assert.equal(h.canvas.style.pointerEvents,'none');h.controller.update();assert.equal(h.canvas.style.pointerEvents,'auto');
 h.controller.dispose();
 const other=harness();other.controller.update();other.deliver(0,[]);await flush();
 assert.equal(other.canvas.style.pointerEvents,'none');other.controller.dispose();
});
