const test=require('node:test'),assert=require('node:assert/strict');
const api=require('../../static/js/main/planning_overlay.js');
const item={id:'ha-noi-partition-reference',theme:'partition',source:'guland',
 name:'Phân khu · Hà Nội',city:'Hà Nội (cũ)',scope:'region',area_id:'ha-noi-legacy',
 coverage_provinces:['ha-noi'],source_url:'https://guland.vn/soi-quy-hoach/ha-noi',
 status:'overlay_ready',decision:'Chưa đối chiếu hồ sơ',manifest:{
 id:'ha-noi-partition-reference',status:'reference_overlay',source_kind:'guland_reference',
 render_mode:'xyz',tile_template:'https://s3-hn-2.cloud.cmctelecom.vn/guland4/hanoi-qhpk2/{z}/{x}/{y}.png',
 bounds:[[20.5,105.2],[21.4,106]],min_zoom:11,max_zoom:23,min_native_zoom:12,max_native_zoom:17,
 tile_size:256,title:'Phân khu · Hà Nội',notice:'Bản đồ tham khảo'}};
const keys=['tile_template','bounds','focus_bounds','overview','min_zoom','max_zoom','tile_size','min_native_zoom','max_native_zoom','coverage_windows'];
const rules={[item.id]:{...Object.fromEntries(keys.filter(k=>item.manifest[k]!==undefined).map(k=>[k,item.manifest[k]])),
 source_url:item.source_url,area_id:item.area_id,coverage_provinces:item.coverage_provinces}};

test('partition references require the exact registered public source and coverage',()=>{
 assert.equal(api.validCatalog({layers:[item]},null,rules),true);
 assert.equal(api.validManifest(item.manifest,null,rules),true);
 assert.equal(api.validManifest(item.manifest),false);
 assert.equal(api.validCatalog({layers:[item]}),false);
 for(const changed of [{theme:'land_use_2030'},{theme:'urban_general'},{source:'gis'},
  {coverage_provinces:['binh-duong']},{area_id:'binh-duong-legacy'},
  {source_url:item.source_url+'/other'}, {source_url:'https://evil.invalid/'}]){
  assert.equal(api.validCatalog({layers:[{...item,...changed}]},null,rules),false,JSON.stringify(changed));
 }
 for(const changed of [{tile_template:item.manifest.tile_template+'?key=changed'},
  {tile_template:'https://evil.invalid/{z}/{x}/{y}.png'}, {source_kind:'official_gis'},
  {source_tiles:{primary:'https://evil.invalid/a'}},{bounds:[[0,0],[90,180]]},
  {tile_size:512},{max_native_zoom:23},{overview:{tile_template:'https://evil.invalid/{z}/{x}/{y}.png',min_zoom:0,max_zoom:14}},{focus_bounds:[[20,105],[21,106]]},{coverage_windows:[[[20,105],[21,106]]]},
  {planning_status:'draft'}]){
  assert.equal(api.validCatalog({layers:[{...item,manifest:{...item.manifest,...changed}}]},null,rules),false,JSON.stringify(changed));
 }
});

test('overview descriptors accept Flask sorted object keys but reject added or changed fields',()=>{
 const expected={tile_template:'/static/overview/{z}/{x}/{y}.png',min_zoom:0,max_zoom:14};
 const actual={max_zoom:14,min_zoom:0,tile_template:expected.tile_template};
 const registered={[item.id]:{...rules[item.id],overview:expected}};
 const layer={...item,manifest:{...item.manifest,overview:actual}};
 assert.equal(api.validCatalog({layers:[layer]},null,registered),true);
 for(const changed of [{...actual,max_zoom:18},{...actual,extra:'unregistered'},{...actual,tile_template:'https://evil.invalid/{z}/{x}/{y}.png'}]){
  assert.equal(api.validCatalog({layers:[{...layer,manifest:{...layer.manifest,overview:changed}}]},null,registered),false);
 }
});

test('source choice keeps a working selection and falls back only to available partition providers',()=>{
 const gis={status:'overlay_ready',source:'gis'},ref={status:'overlay_ready',source:'guland'};
 assert.equal(api.partitionSource([ref],'gis'),'guland');
 assert.equal(api.partitionSource([gis],'guland'),'gis');
 assert.equal(api.partitionSource([gis,ref],'gis'),'gis');
 assert.equal(api.partitionSource([gis,ref],'guland'),'guland');
 assert.equal(api.partitionSource([{...gis,inspection_only:true},ref],'gis'),'guland');
 assert.equal(api.partitionSource([],'gis'),'gis');
});

test('actual checked partition registry validates and filters by historic province',()=>{
 const layers=require('../../config/planning_partition_reference.json').layers;
 const area=require('../../static/js/main/planning_area.js');
 const actual=Object.fromEntries(layers.map(l=>[l.id,{
  ...Object.fromEntries(keys.filter(k=>l.manifest[k]!==undefined).map(k=>[k,l.manifest[k]])),
  source_url:l.source_url,area_id:l.area_id,coverage_provinces:l.coverage_provinces,
 }]));
 assert(layers.length>0);assert(api.validCatalog({layers},null,actual));
 for(const l of layers){
  assert(area.coversProvince(l,{id:l.coverage_provinces[0]}));
  assert.equal(area.coversProvince(l,{id:'binh-duong'}),false);
  assert.equal(api.validCatalog({layers:[{...l,theme:'land_use_2030'}]},null,actual),false);
 }
});

test('a provincial mosaic can contain hundreds of registered schemes with a fixed catalogue ceiling',()=>{
 const layers=Array.from({length:1025},(_,i)=>({...item,id:'scheme-'+i,manifest:{...item.manifest,id:'scheme-'+i}}));
 const registered=Object.fromEntries(layers.map(l=>[l.id,rules[item.id]]));
 assert.equal(api.validCatalog({layers:layers.slice(0,500)},null,registered),true);
 assert.equal(api.validCatalog({layers},null,registered),false);
});
