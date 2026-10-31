const assert = require('node:assert/strict');
const api = require('../static/js/main/planning_parcels.js');
const nodes = [], pending = [], layers = new Set(), events = {};
const doc = {querySelector:()=>null, createElement(tag) {
  const el = {tag,style:{},attributes:{},children:[],events:{},textContent:'',
    appendChild(child){this.children.push(child);return child;},
    replaceChildren(){this.children=[];},remove(){},
    setAttribute(k,v){this.attributes[k]=v;},addEventListener(k,fn){this.events[k]=fn;}};
  nodes.push(el);return el;
}};
let west=106.61;
const map = {createPane:()=>({style:{}}),on(k,f){events[k]=f;},off(k){delete events[k];},
  getContainer:()=>({appendChild(){}}),
  getZoom:()=>18,getCenter:()=>({lat:11.02,lng:106.65}),
  getBounds:()=>({getWest:()=>west,getEast:()=>west+.004,getSouth:()=>11.02,getNorth:()=>11.024,intersects:()=>true}),
  removeLayer(l){layers.delete(l);},fitBounds(bounds){this.fitted=bounds;},setView(){}};
const L = {DomEvent:{disableClickPropagation(){},disableScrollPropagation(){},stopPropagation(){}},
  control:()=>({addTo(){},remove(){}}),geoJSON(data,options){
    const layer={data,options,addTo(){layers.add(this);return this;},getBounds:()=>[[11.02,106.65],[11.021,106.651]]};
    if(options && options.onEachFeature) for(const f of data.features||[]) {
      const polygon={bindTooltip(){},on(k,fn){this[k]=fn;}};
      options.onEachFeature(f,polygon);layer.polygon=polygon;
    }
    return layer;
  }};
const env={document:doc,AbortController,matchMedia:()=>({matches:false}),setTimeout:(f)=>{env.tick=f;return 1;},clearTimeout(){},
  fetch(url,options){return new Promise(resolve=>pending.push({url,options,resolve}));}};
const flush=()=>new Promise(r=>setImmediate(r));
const deliver=(i,data)=>pending[i].resolve({ok:true,json:async()=>data});
const feature={type:'Feature',id:900,geometry:{type:'Polygon',coordinates:[]},
  properties:{id:900,area_id:'25813',ward:'Mỹ Phước',city:'Bến Cát',sheet:'1',parcel:'2',area:100}};
(async()=>{
  const dispose=api.mount(map,L,env);
  deliver(0,{min_zoom:17,count:2,excluded_count:0,areas:[
    {area_id:'25765',ward:'Tân An',city:'Thủ Dầu Một',bounds:[[11.02,106.61],[11.03,106.62]],sample_id:33013},
    {area_id:'25813',ward:'Mỹ Phước',city:'Bến Cát',bounds:[[11.02,106.65],[11.03,106.66]],sample_id:900}]});
  await flush();
  assert(pending[1].url.includes('viewport.json?bbox='),'All-ward config must load the visible area');
  deliver(1,{type:'FeatureCollection',features:[feature],matched:1});await flush();
  const old=[...layers][0];
  west=106.65;events.moveend();env.tick();
  assert(layers.has(old),'Keep current geometry while the next view loads');
  deliver(2,{type:'FeatureCollection',features:[feature],matched:1});await flush();
  assert(!layers.has(old));
  [...layers][0].polygon.click({});
  assert.equal(pending.length,3,'Clicking a parcel must not request GIS planning');
  nodes.filter(n=>n.className==='planning-parcel-expand').at(-1).events.click();
  assert(pending[3].url.includes('/900/planning.json?area=25813'));
  assert(nodes.some(n=>n.textContent==='Mỹ Phước · Bến Cát (đơn vị cũ)'));
  deliver(3,{parcel:feature.properties,plans:[],queried_at:'2026-10-27'});await flush();
  const expanded=nodes.filter(n=>n.className==='planning-parcel-expand').at(-1);
  assert.equal(expanded.disabled,false);expanded.events.click();expanded.events.click();
  assert.equal(pending.length,4,'Reopening cached details must not repeat the GIS request');
  const field=name=>nodes.find(n=>n.attributes['aria-label']===name);
  const close=field('Đóng thông tin thửa');
  assert(close,'Parcel information needs an explicit close control');
  close.events.click();
  assert.equal(layers.size,1,'Closing parcel details keeps the visible boundaries');
  field('Quận / Huyện (Cũ)').value='Bến Cát';field('Quận / Huyện (Cũ)').events.change();
  field('Phường / Xã (Cũ)').value='25813';
  field('Số tờ bản đồ').value='1';field('Số thửa đất').value='2';
  field('Tra tờ thửa').events.submit({preventDefault(){}});
  assert(pending[4].url.includes('search.json?area=25813&sheet=1&parcel=2'));
  deliver(4,{type:'FeatureCollection',features:[feature],matched:1,truncated:false});await flush();
  assert.equal(pending.length,5,'Sheet search opens basic information without GIS');
  nodes.filter(n=>n.className==='planning-parcel-expand').at(-1).events.click();
  assert(pending[5].url.includes('/900/planning.json?area=25813'));
  close.events.click();
  deliver(5,{parcel:feature.properties,plans:[{type:'LATE RESULT'}],queried_at:'2026-10-27'});await flush();
  assert(!nodes.some(n=>n.textContent==='LATE RESULT'),'Closed details must ignore late responses');
  field('Tra tờ thửa').events.submit({preventDefault(){}});
  const beforePan=pending.length;events.movestart();
  deliver(beforePan-1,{type:'FeatureCollection',features:[feature],matched:1});await flush();
  assert.equal(pending.length,beforePan,'A late search must not move the map after a manual pan');
  const toggle=nodes.find(n=>n.attributes['aria-label']==='Bật ranh thửa đất');
  toggle.checked=false;toggle.events.change();assert.equal(layers.size,0);
  dispose();assert.equal(Object.keys(events).length,0);
  env.RADAR_PLANNING_CONFIG={parcelBase:'/api/planning/parcels'};
  env.RADAR_PLANNING_REGIONS=[{id:'hcm-legacy',name:'TP.HCM (cũ)',bounds:[[10.3,106.3],[11.2,107.05]],max_zoom:12},
    {id:'dong-nai-expanded',name:'Đồng Nai mới',bounds:[[10.49,106.39],[12.33,107.6]],max_zoom:10,notice:'Bật QH 2030 để xem Đồng Nai và Bình Phước cũ.'}];
  const beforeProduction=pending.length;
  const disposeProduction=api.mount(map,L,env);
  assert.equal(pending[beforeProduction].url,'/api/planning/parcels/config.json');
  deliver(beforeProduction,{min_zoom:17,count:1,excluded_count:0,live_expanded:true,
    coverage_bounds:[[8.5,106.25],[11.65,107.65]],areas:[
    {area_id:'25813',ward:'Mỹ Phước',city:'Bến Cát',district:'721',bounds:[[11.02,106.65],[11.03,106.66]],sample_id:900},
    {area_id:'26740',ward:'Bến Nghé',city:'Quận 1',district:'760',bounds:[[10.77,106.69],[10.78,106.71]]}]});
  await flush();
  assert(pending[beforeProduction+1].url.startsWith('/api/planning/parcels/viewport.json?bbox='));
  const province=nodes.filter(n=>n.attributes['aria-label']==='Tỉnh/TP').at(-1);
  const district=nodes.filter(n=>n.attributes['aria-label']==='Quận / Huyện (Cũ)').at(-1);
  const searchWard=nodes.filter(n=>n.attributes['aria-label']==='Phường / Xã (Cũ)').at(-1);
  province.value='hcm';province.events.change();
  assert.deepEqual(district.children.map(n=>n.value),['Quận 1']);
  assert.deepEqual(searchWard.children.map(n=>n.value),['26740']);
  province.value='brvt';province.events.change();
  assert.equal(district.children.length,0);assert.equal(searchWard.value,'');
  province.value='binh-duong';province.events.change();
  assert.deepEqual(searchWard.children.map(n=>n.value),['25813']);
  deliver(beforeProduction+1,{type:'FeatureCollection',features:[feature],matched:1});await flush();
  [...layers][0].polygon.click({});
  nodes.filter(n=>n.className==='planning-parcel-expand').at(-1).events.click();
  assert(pending[beforeProduction+2].url.startsWith('/api/planning/parcels/900/planning.json'));
  const city=nodes.filter(n=>n.attributes['aria-label']==='Thành phố trên bản đồ').at(-1);
  const ward=nodes.filter(n=>n.attributes['aria-label']==='Phường trên bản đồ').at(-1);
  assert(city.children.some(n=>n.value==='hcm-legacy'));
  city.value='hcm-legacy';city.events.change();assert.equal(ward.disabled,true);
  const beforeRegion=pending.length;
  const regionForm=nodes.filter(n=>n.tag==='form'&&!n.attributes['aria-label']).at(-1);
  regionForm.events.submit({preventDefault(){}});
  assert.deepEqual(map.fitted,[[10.3,106.3],[11.2,107.05]]);
  assert.equal(pending.length,beforeRegion,'Region navigation must not ask the Bình Dương-only listing service for bounds');
  city.value='dong-nai-expanded';city.events.change();
  regionForm.events.submit({preventDefault(){}});
  assert.deepEqual(map.fitted,[[10.49,106.39],[12.33,107.6]]);
  assert.equal(pending.length,beforeRegion);
  assert.ok(nodes.some(n=>n.textContent==='Bật QH 2030 để xem Đồng Nai và Bình Phước cũ.'));
  city.value='Quận 1';city.events.change();ward.value='26740';
  regionForm.events.submit({preventDefault(){}});
  assert.deepEqual(map.fitted,[[10.77,106.69],[10.78,106.71]]);
  assert.equal(pending.length,beforeRegion,'Expanded ward navigation uses public reference windows, not BD listing bounds');
  events.moveend();env.tick();
  const busy=pending.length-1;
  pending[busy].resolve({ok:false,status:503});await flush();
  assert(nodes.some(n=>n.textContent==='GIS đang bận; đang thử tải lại ranh…'));
  env.tick();assert.equal(pending.length,busy+2,'A settled view retries bounded upstream backpressure');
  const coordinateMethod=nodes.filter(n=>n.attributes['aria-label']==='Tra cứu theo').at(-1);
  coordinateMethod.value='coordinates';coordinateMethod.events.change();
  const first=nodes.filter(n=>n.attributes['aria-label']==='Vĩ độ').at(-1);
  const second=nodes.filter(n=>n.attributes['aria-label']==='Kinh độ').at(-1);
  first.value='11.0205';second.value='106.6505';
  first.events.input();
  assert(nodes.some(n=>n.textContent==='Chọn hệ tọa độ và nhập đủ hai giá trị.'));
  const coordinateForm=nodes.filter(n=>n.attributes['aria-label']==='Tra tờ thửa').at(-1);
  let coordinateIndex=pending.length;coordinateForm.events.submit({preventDefault(){}});
  assert(pending[coordinateIndex].url.includes('/coordinates.json?system=wgs84'));
  const coordinateFeature={...feature};
  deliver(coordinateIndex,{type:'FeatureCollection',features:[coordinateFeature],matched:1,point:[11.0205,106.6505]});await flush();
  assert(!pending.at(-1).url.includes('/900/planning.json'),'Coordinate lookup opens only basic information');
  nodes.filter(n=>n.className==='planning-parcel-expand').at(-1).events.click();
  assert(pending.at(-1).url.includes('/900/planning.json?area=25813'),'Coordinate lookup opens the actual returned parcel, independent of the sheet-search ward');
  coordinateIndex=pending.length;coordinateForm.events.submit({preventDefault(){}});
  map.fitted=null;events.movestart();
  deliver(coordinateIndex,{type:'FeatureCollection',features:[coordinateFeature],matched:1,point:[11.0205,106.6505]});await flush();
  assert.equal(map.fitted,null,'A late coordinate result must not move the map after a manual pan');
  coordinateMethod.value='corners';coordinateMethod.events.change();
  const cornerField=nodes.filter(n=>n.attributes['aria-label']==='Danh sách góc ranh').at(-1);
  cornerField.value='11.02 106.61\n11.02 106.611\n11.021 106.611';
  assert.equal(first.required,false);assert.equal(cornerField.required,true);
  env.RadarParcelTools=require('../static/js/main/planning_parcel_tools.js');
  const fired=[];map.fire=(name,data)=>fired.push({name,data});
  const outline={type:'Feature',properties:{origin:'user_corners',area:6100},geometry:{type:'Polygon',coordinates:[[[106.61,11.02],[106.611,11.02],[106.611,11.021],[106.61,11.02]]]}};
  let cornersIndex=pending.length;coordinateForm.events.submit({preventDefault(){}});
  assert(pending[cornersIndex].url.endsWith('/corners.json'));assert.equal(pending[cornersIndex].options.method,'POST');
  assert.equal(JSON.parse(pending[cornersIndex].options.body).corners,cornerField.value);
  deliver(cornersIndex,outline);await flush();
  assert.equal(pending.length,cornersIndex+1,'Corner input must not start a planning lookup');
  assert(fired.some(e=>e.name==='planning:measure-parcel'&&e.data.origin==='user_corners'&&e.data.points.length===3));
  cornersIndex=pending.length;coordinateForm.events.submit({preventDefault(){}});
  map.fitted=null;events.movestart();const beforeLate=fired.length;
  deliver(cornersIndex,outline);await flush();
  assert.equal(map.fitted,null);assert.equal(fired.length,beforeLate,'Late corners cannot redraw after a manual pan');
  disposeProduction();
  console.log('Parcel viewport, multi-area selection, toggle and cleanup passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
