const assert = require('node:assert/strict');
const api = require('../static/js/main/planning_native_tiles.js');
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
console.log('Native planning tiles: composite reuse, bounded expiry, source isolation, fallback and cancellation passed');
