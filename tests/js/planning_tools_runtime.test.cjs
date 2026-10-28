const test=require('node:test');
const assert=require('node:assert/strict');
const measure=require('../../static/js/main/planning_measure.js');
const legend=require('../../static/js/main/planning_legend.js');
const catalog=require('../../static/data/planning_symbols.json');
function harness() {
 const nodes=[],events={},layers=new Set(),frames=new Map();let seq=0,fetches=0,resolve;
 function element(tag) {
  const n={tag,children:[],attrs:{},events:{},hidden:false,value:'',style:{},textContent:'',
   appendChild(c){this.children.push(c);},replaceChildren(){this.children=[];},
   setAttribute(k,v){this.attrs[k]=v;},addEventListener(k,fn){this.events[k]=fn;},removeEventListener(k){delete this.events[k];},
   remove(){this.removed=true;},focus(){this.focused=true;},contains(t){return t===this||this.children.some(c=>c.contains&&c.contains(t));}};
  nodes.push(n);return n;
 }
 const doc={createElement:element,createTextNode:text=>({textContent:text}),addEventListener(){},removeEventListener(){}};
 const classes=new Set(),container=element('map');container.classList={toggle(k,on){if(on)classes.add(k);else classes.delete(k);},contains:k=>classes.has(k)};
 const map={createPane:()=>({style:{}}),getContainer:()=>container,getCenter:()=>({lat:11,lng:106}),
  on(k,fn){events[k]=fn;},off(k){delete events[k];},fire(k,event){if(events[k])events[k](event);},
  hasLayer:l=>layers.has(l),removeLayer:l=>layers.delete(l),
  doubleClickZoom:{value:true,enabled(){return this.value;},disable(){this.value=false;},enable(){this.value=true;}}};
 function layer(kind,points,options){return {kind,points,options,events:{},
  addTo(owner){if(owner===map)layers.add(this);else owner.children.push(this);return this;},
  on(k,fn){this.events[k]=fn;return this;},remove(){layers.delete(this);},
  setLatLngs(p){this.points=p;return this;},setLatLng(p){this.at=p;return this;},setContent(c){this.content=c;return this;},
  getBounds(){return {getCenter:()=>points[0]};}};}
 const L={svg:()=>layer('renderer'),layerGroup:()=>Object.assign(layer('group'),{children:[],clearLayers(){this.children=[];}}),
  polyline:(p,o)=>layer('line',p,o),polygon:(p,o)=>layer('polygon',p,o),circleMarker:(p,o)=>layer('vertex',p,o),
  tooltip:o=>layer('tooltip',null,o),DomEvent:{stopPropagation(){}}};
 const env={document:doc,AbortController,requestAnimationFrame(fn){frames.set(++seq,fn);return seq;},cancelAnimationFrame(id){frames.delete(id);},
  fetch(url,options){fetches++;env.lastURL=url;env.signal=options.signal;return new Promise(r=>{resolve=r;});}};
 const ui={root:element('root'),panels:[]},actions=element('actions');
 return {nodes,map,env,L,ui,actions,events,frames,layers,container,control:label=>nodes.find(n=>n.attrs['aria-label']===label),
  count:()=>fetches,deliver(value=catalog){resolve({ok:true,json:async()=>value});}};
}
test('draw, close, delete, pause and cleanup preserve map interactions',()=>{
 const h=harness(),dispose=measure.mount(h.map,h.L,h.env,h.ui,h.actions);
 const draw=h.control('Vẽ ranh đo khoảng cách và diện tích'),clear=h.control('Xóa ranh đã vẽ');
 assert(clear.disabled);draw.events.click();assert(!h.map.doubleClickZoom.enabled());
 assert(h.container.classList.contains('planning-is-drawing'));
 const click=(lat,lng)=>h.events.click({latlng:{lat,lng}});
 click(11,106);click(11,106.001);click(11.001,106.001);
 h.control('Khép ranh và tính diện tích').events.click();
 assert(h.map.doubleClickZoom.enabled());assert(!h.container.classList.contains('planning-is-drawing'));
 assert(h.nodes.some(n=>n.attrs.role==='status'&&n.textContent.includes('Diện tích')));
 clear.events.click();assert(clear.disabled);
 draw.events.click();click(11,106);click(11,106.001);
 h.container.events.keydown({key:'Escape',target:h.container,preventDefault(){},stopPropagation(){}});
 assert(h.map.doubleClickZoom.enabled());assert(!clear.disabled,'Pausing must retain the draft');
 draw.events.click();h.map.fire('planning:panel-open');
 assert(h.map.doubleClickZoom.enabled());assert(!clear.disabled,'Opening a panel pauses without discarding the outline');
 draw.events.click();h.events.mousemove({latlng:{lat:11.001,lng:106.001}});assert.equal(h.frames.size,1);
 dispose();assert.equal(h.frames.size,0);assert.equal(h.layers.size,0);assert.deepEqual(Object.keys(h.events),[]);
 assert(h.map.doubleClickZoom.enabled());dispose();
});
test('drawing never enables double-click zoom when it was already disabled',()=>{
 const h=harness();h.map.doubleClickZoom.value=false;
 const dispose=measure.mount(h.map,h.L,h.env,h.ui,h.actions);
 h.control('Vẽ ranh đo khoảng cách và diện tích').events.click();dispose();
 assert.equal(h.map.doubleClickZoom.enabled(),false);
});
test('legend is source-specific, lazy, searchable and aborts on disposal',async()=>{
 assert(legend.valid(catalog));assert.equal(catalog.groups.reduce((n,g)=>n+g.rows.length,0),400);
 assert.equal(catalog.groups.filter(g=>g.theme!=='land_codes').reduce((n,g)=>n+g.rows.length,0),333);
 assert(!legend.valid({...catalog,groups:[{...catalog.groups[1],theme:'urban_general'}]}),'A partition legend must not be labelled general planning');
 assert(!legend.valid({...catalog,groups:[{...catalog.groups[0],source_url:'https://evil.invalid'}]}));
 assert(!legend.valid({...catalog,groups:[{...catalog.groups[0],rows:[{code:'A',label:'B',image:'data:image/svg+xml,<svg>'}]}]}));
 assert.equal(legend.normalize('Đất ở đô thị'),'dat o do thi');
 const h=harness(),dispose=legend.mount(h.map,h.L,h.env,h.ui,h.actions,()=>({theme:'urban_general',active:true,source:'gis'}));
 assert.equal(h.count(),0);const button=h.control('Bảng ký hiệu các loại đất');button.events.click();
 assert.equal(h.count(),1);h.deliver();await new Promise(r=>setImmediate(r));
 assert(h.nodes.some(n=>n.tag==='td'&&n.textContent==='MN'));
 const search=h.control('Tìm ký hiệu hoặc loại đất');search.value='khong co ma nay';search.events.input();
 assert(h.nodes.some(n=>n.attrs.role==='status'&&n.textContent==='Không tìm thấy ký hiệu phù hợp.'));
 button.events.click();button.events.click();assert.equal(h.count(),1);dispose();assert(h.env.signal.aborted);
});
test('an invalid legend shows a retry state and common land codes are searchable',async()=>{
 const h=harness(),dispose=legend.mount(h.map,h.L,h.env,h.ui,h.actions,()=>({theme:'land_use_2030',source:'guland'}));
 h.control('Bảng ký hiệu các loại đất').events.click();h.deliver({groups:[]});await new Promise(r=>setImmediate(r));
 const retry=h.nodes.find(n=>n.tag==='button'&&n.textContent==='Thử tải lại');assert.equal(retry.hidden,false);
 retry.events.click();h.deliver();await new Promise(r=>setImmediate(r));
 const search=h.control('Tìm ký hiệu hoặc loại đất');search.value='ODT';search.events.input();
 assert(h.nodes.some(n=>n.tag==='td'&&n.textContent==='Đất ở tại đô thị'));
 assert.equal(h.count(),2);dispose();
});
