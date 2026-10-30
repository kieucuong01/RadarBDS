const test=require('node:test'),assert=require('node:assert/strict');
const api=require('../../static/js/main/planning_area.js');
const provinces=require('../../config/planning_landuse_areas.json').provinces;

test('whole province fills the viewport at a closer zoom; district keeps its fitted extent',()=>{
 const calls=[],bounds={getCenter:()=>({lat:11,lng:106})};
 const L={latLngBounds:b=>{assert.deepEqual(b,provinces[0].bounds);return bounds;}};
 const map={getBoundsZoom(b,inside,pad){assert.equal(b,bounds);assert.deepEqual(pad,[0,0]);return inside?12:10;},
  setView(c,z,o){calls.push({c,z,o});},fitBounds(b,o){calls.push({b,o});}};
 api.focus(map,L,{bounds:provinces[0].bounds,district:''});assert.equal(calls[0].z,12);
 api.focus(map,L,{bounds:provinces[0].bounds,district:'718',max_zoom:13});assert.equal(calls[1].o.maxZoom,13);
 map.getBoundsZoom=()=>18;api.focus(map,L,{bounds:provinces[0].bounds,district:''});assert.equal(calls[2].z,13);
});
test('ordinary Maps defaults to historic Binh Duong and Thu Dau Mot regardless of listing geography',()=>{
 const area=api.initial(provinces);assert.equal(area.province,'binh-duong');assert.equal(area.district,'718');
 assert.deepEqual(area.bounds,provinces[0].districts.find(d=>d.id==='718').bounds);assert.equal(area.max_zoom,13);
});
test('historic province deep links keep their area and expanded links select one former province',()=>{
 for(const [region,province] of [['hcm-legacy','hcm'],['hcm-expanded','hcm'],['dong-nai-expanded','dong-nai'],['binh-phuoc-legacy','binh-phuoc'],['con-dao','brvt'],['tay-ninh-legacy','tay-ninh'],['long-an-legacy','long-an']]){
  const area=api.initial(provinces,region);assert.equal(area.province,province);
  if(region==='con-dao')assert.equal(area.district,'con-dao');else assert.equal(area.district,'');
 }
 assert.equal(api.initial([],null),null);
});
test('area menu applies only after submit, resets districts across provinces, and keeps other popovers exclusive',()=>{
 const nodes=[],changes=[];
 const doc={createElement(tag){const e={tagName:tag,children:[],attributes:{},events:{},appendChild(c){this.children.push(c);},
  replaceChildren(){this.children=[];},setAttribute(k,v){this.attributes[k]=v;},addEventListener(k,f){this.events[k]=f;}};nodes.push(e);return e;}};
 const other={open:true},ui={areaSlot:doc.createElement('div'),panels:[other]};
 const panel=api.mount({document:doc},ui,provinces,api.initial(provinces),(p,s)=>changes.push({p,s}));
 const province=nodes.find(e=>e.attributes['aria-label']==='Tỉnh/TP (Cũ)'),district=nodes.find(e=>e.attributes['aria-label']==='Quận/Huyện (Cũ)');
 assert.deepEqual(province.children.map(e=>e.textContent),['Bình Dương','TP.HCM','Bà Rịa–Vũng Tàu','Đồng Nai','Bình Phước','Tây Ninh','Long An']);
 assert.equal(district.value,'718');province.value='binh-phuoc';province.events.change();
 assert.equal(district.value,'');assert(district.children.some(e=>e.textContent==='Phú Riềng'));assert.equal(changes.length,0);
 district.value='dong-xoai';nodes.find(e=>e.tagName==='form').events.submit({preventDefault(){}});
 assert.equal(changes[0].p.id,'binh-phuoc');assert.equal(changes[0].s.district,'dong-xoai');assert.equal(panel.open,false);
 panel.open=true;panel.events.toggle();assert.equal(other.open,false);
});
