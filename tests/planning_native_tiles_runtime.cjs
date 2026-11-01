const assert = require('node:assert/strict');
const api = require('../static/js/main/planning_native_tiles.js');
function referenceQueueTest() {
 const images=[],timers=new Map(),results=[];let tick=0;
 class Tile {constructor(options){this.options=options;this.events={};}on(k,fn){this.events[k]=fn;}}
 Tile.extend=methods=>{class Child extends Tile {}Object.assign(Child.prototype,methods);return Child;};
 const env={document:{createElement(){const img={naturalWidth:256,naturalHeight:256,setAttribute(){}};images.push(img);return img;}},
  setTimeout(fn,ms){timers.set(++tick,{fn,ms});return tick;},clearTimeout(id){timers.delete(id);}};
 const source={tile_template:'https://public.example/{z}/{x}/{y}.png'};
 const first=api.createReference({TileLayer:Tile},env,source,{}),second=api.createReference({TileLayer:Tile},env,source,{});
 const tiles=Array.from({length:6},(_,x)=>(x<3?first:second).createTile({z:15,x,y:4},(error)=>results.push(error)));
 assert.equal(images.filter(i=>i.src).length,4,'Reference sheets share four active image loads');
 assert.equal(timers.size,4,'Queued images do not time out before starting');
 second.events.tileunload({tile:tiles[5]});images[0].onload();
 assert(images[4].src.endsWith('/15/4/4.png'));assert(!images[5].src.includes('public.example'));
 images[1].onerror();assert.equal(results.length,2);assert(results[1]);
 const late=images[2].onload;first.events.remove();late();assert.equal(results.length,2);
 second.events.remove();assert.equal(timers.size,0);assert(images.every(i=>i.onload===null));
 const zoomLayer=api.createReference({TileLayer:Tile},env,source,{});
 const stale=Array.from({length:6},(_,x)=>zoomLayer.createTile({z:15,x,y:9},()=>assert.fail('Old zoom completion')));
 zoomLayer._tileZoom=16;zoomLayer._abortLoading();
 assert.equal(timers.size,0,'Zoom abort releases active jobs and cancels queued old-zoom images immediately');
 assert(stale.every(i=>!i.src.includes('public.example')));
 let completed=0;
 const fresh=zoomLayer.createTile({z:16,x:4,y:9},(error,tile)=>{
   assert(error);assert.notEqual(tile.src,'data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs=','Leaflet ignores completion with its empty-image sentinel');completed++;
 });
 assert(fresh.src.endsWith('/16/4/9.png'),'New zoom starts without waiting15seconds');
 [...timers.values()][0].fn();assert.equal(completed,1);assert.equal(timers.size,0);zoomLayer.events.remove();
}
referenceQueueTest();
function harness() {
  const images=[], draws=[], results=[];
  const doc={createElement(tag){
    if(tag==='img') {const img={naturalWidth:256,naturalHeight:256};images.push(img);return img;}
    return {attrs:{},setAttribute(k,v){this.attrs[k]=v;},getContext(){return {
      clearRect(){draws.length=0;},drawImage(img){draws.push(img.src || img);}};}};
  }};
  class Grid {constructor(options){this.options=options;this.events={};}on(k,fn){this.events[k]=fn;}}
  Grid.extend=methods=>{class Derived extends Grid {}Object.assign(Derived.prototype,methods);return Derived;};
  const manifest={tile_template:'/api/planning/gis-tiles/urban_general/{z}/{x}/{y}.png',
    source_tiles:{primary:'https://source/primary/{z}/{y}/{x}',supplement:'https://source/supplement/{z}/{y}/{x}'}};
  const timers=new Map();let seq=0;
  const env={Date:{now:()=>env.now},now:0,document:doc,setTimeout(fn,ms){timers.set(++seq,{fn,ms});return seq;},clearTimeout(id){timers.delete(id);}};
  const layer=api.create({GridLayer:Grid},env,manifest,{opacity:.35});
  const tile=layer.createTile({z:15,x:42,y:84},(err,tile)=>results.push({err,tile}));
  return {layer,tile,images,draws,results,timers,env,manifest,L:{GridLayer:Grid}};
}
{
 const h=harness();const [p,s]=h.images;assert(p.src.endsWith('/15/84/42'));
 s.onload();assert.equal(h.results.length,0);p.onload();
 assert.deepEqual(h.draws,['https://source/supplement/15/84/42','https://source/primary/15/84/42']);
 assert.equal(h.tile.attrs['data-planning-transport'],'direct');assert.equal(h.results.length,1);
 assert.equal(h.layer.options.opacity,.35);
 assert.equal(h.timers.size,0);
}
{
 const h=harness();h.images[0].onerror();assert.equal(h.images.length,3);
 const fallback=h.images[2];assert.equal(fallback.src,'/api/planning/gis-tiles/urban_general/15/42/84.png');
 fallback.onload();assert.deepEqual(h.draws,['/api/planning/gis-tiles/urban_general/15/42/84.png']);
 assert.equal(h.tile.attrs['data-planning-transport'],'gateway');assert.equal(h.results.length,1);
}
{
 const h=harness();h.images[0].naturalWidth=512;h.images[0].onload();
 h.images[2].onerror();assert(h.results[0].err);assert.equal(h.results.length,1);
}
{
 const h=harness();const late=h.images[0].onload;h.layer.events.tileunload({tile:h.tile});late();
 assert.equal(h.results.length,0);assert.equal(h.images[1].onload,null);
}
{
 const h=harness();const late=h.images[1].onload;h.layer.events.remove();late();
 assert.equal(h.results.length,0);assert.equal(h.images[0].onload,null);
 assert.equal(h.timers.size,0);
}
{
 const h=harness();const directTimeout=[...h.timers.values()][0];assert.equal(directTimeout.ms,8000);
 directTimeout.fn();assert.equal(h.images.length,3);
 const fallbackTimeout=[...h.timers.values()][0];assert.equal(fallbackTimeout.ms,15000);
 fallbackTimeout.fn();assert(h.results[0].err);assert.equal(h.tile.attrs['data-planning-transport'],'error');
 assert.equal(h.timers.size,0);
}
{
 const h=harness();
 const second=api.create(h.L,h.env,h.manifest,{opacity:.35});
 const extra=Array.from({length:4},(_,x)=>second.createTile({z:15,x,y:84},()=>{}));
 assert.equal(h.images.length,8,'Four tiles across both layers may load their two sources');
 assert.equal(h.timers.size,4,'Queued tiles have no timeout yet');
 extra[3].cancelPlanningLoad();
 h.images[0].onload();h.images[1].onload();
 assert.equal(h.images.length,8,'A cancelled queued tile must never start');
 second.events.remove();assert.equal(h.timers.size,0);
}
{
 const h=harness();
 for(let x=0;x<4;x++)h.layer.createTile({z:15,x,y:84},()=>{});
 assert.equal(h.images.length,8);
 h.images[0].onload();h.images[1].onload();
 assert.equal(h.images.length,10,'Completing a tile starts the next queued tile');
 assert.equal(h.timers.size,4);
 h.layer.events.remove();assert.equal(h.timers.size,0);
}
{
 const h=harness();h.images[0].onerror();h.images[2].onload();
 const next=api.create(h.L,h.env,h.manifest,{opacity:.65});
 const warm=next.createTile({z:15,x:42,y:84},(err,tile)=>h.results.push({err,tile}));
 assert.equal(h.images.length,3,'A successful gateway composite is reused without repeating failed source requests');
 assert.equal(h.results.length,1,'Leaflet must register the tile before its completion callback');
 [...h.timers.values()][0].fn();assert.equal(h.results.length,2);
 assert.equal(warm.attrs['data-planning-transport'],'memory');assert.equal(h.draws.at(-1),h.tile);
 assert.equal(next.options.opacity,.65,'Cached pixels do not bake in the previous layer opacity');
 const changed={...h.manifest,source_tiles:{...h.manifest.source_tiles,primary:'https://other/{z}/{x}/{y}'}};
 api.create(h.L,h.env,changed,{}).createTile({z:15,x:42,y:84},()=>{});
 assert.equal(h.images.length,5,'Different source identities cannot share composites');
 next.events.remove();
}
{
 const h=harness();h.images[0].onload();h.images[1].onload();
 const next=api.create(h.L,h.env,h.manifest,{});
 const warm=next.createTile({z:15,x:42,y:84},()=>assert.fail('Cancelled cache hit must not finish'));
 const late=[...h.timers.values()][0].fn;next.events.tileunload({tile:warm});late();
 h.env.now=180001;next.createTile({z:15,x:42,y:84},()=>{});
 assert.equal(h.images.length,4,'Expired composites must reload');next.events.remove();
}
{
 const h=harness();h.images[0].onerror();h.images[2].onerror();
 h.layer.createTile({z:15,x:42,y:84},()=>{});assert.equal(h.images.length,5,'Failures remain retryable');h.layer.events.remove();
}
{
 const h=harness();h.images[0].onload();h.images[1].onload();
 for(let x=0;x<64;x++){
  const at=h.images.length;h.layer.createTile({z:15,x,y:85},()=>{});h.images[at].onload();h.images[at+1].onload();
 }
 const at=h.images.length;h.layer.createTile({z:15,x:42,y:84},()=>{});
 assert.equal(h.images.length,at+2,'Only 64 completed composites are retained across layers');h.layer.events.remove();
}
{
 const h=harness();h.layer.events.remove();const start=h.images.length;
 const layer=api.create(h.L,h.env,{...h.manifest,gateway_first:true},{});
 layer.createTile({z:17,x:44,y:85},()=>{});
 assert.equal(h.images.length,start+1,'Published GIS uses one composited image instead of two upstream images');
 assert(h.images.at(-1).src.startsWith('/api/planning/gis-tiles/'));
 h.images.at(-1).onload();layer.events.remove();
}
console.log('Native planning tiles: composite reuse, bounded expiry, source isolation, fallback and cancellation passed');

(async()=>{
 const h=harness();h.layer.events.remove();const requests=[],revoked=[];let blobs=0;
 h.env.AbortController=AbortController;
 h.env.URL={createObjectURL(){blobs++;return 'blob:planning-test';},revokeObjectURL(value){revoked.push(value);}};
 h.env.fetch=(url,options)=>new Promise(resolve=>requests.push({url,options,resolve}));
 const layer=api.create(h.L,h.env,{...h.manifest,gateway_first:true},{});
 layer.createTile({z:17,x:1,y:2},()=>{});
 assert.equal(requests[0].options.credentials,'omit','Public images use anonymous delivery even on a signed-in dashboard');
 requests[0].resolve({ok:true,blob:async()=>({})});await new Promise(resolve=>setImmediate(resolve));
 assert.equal(h.images.at(-1).src,'blob:planning-test');h.images.at(-1).onload();
 assert.deepEqual(revoked,['blob:planning-test'],'Completed image blob is released after drawing');
 layer.createTile({z:17,x:2,y:2},()=>{});layer.events.remove();
 assert(requests[1].options.signal.aborted,'Hiding a layer cancels its anonymous image fetch');
 requests[1].resolve({ok:true,blob:async()=>({})});await new Promise(resolve=>setImmediate(resolve));
 assert.equal(blobs,1,'Late images cannot recreate blobs after the layer is removed');
 console.log('Public image delivery: omitted credentials, blob cleanup and late cancellation passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
