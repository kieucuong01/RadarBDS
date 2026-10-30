const test=require('node:test'),assert=require('node:assert/strict');
const api=require('../../static/js/main/planning_overlay.js');
const layers=require('../../config/planning_landuse_2030.json').layers;
const keys=['tile_template','bounds','min_zoom','max_zoom','tile_size','min_native_zoom','max_native_zoom','coverage_windows'];
const rules=Object.fromEntries(layers.map(l=>[l.id,Object.fromEntries(keys.filter(k=>l.manifest[k]!==undefined).map(k=>[k,l.manifest[k]]))]));

test('all 63 national references validate only against their registered source descriptors',()=>{
 assert.equal(layers.length,63);assert(api.validCatalog({layers},rules));
 for(const l of layers)assert(api.validManifest(l.manifest,rules),l.id);
 const m=layers.find(l=>l.area_id==='ha-noi-legacy').manifest;
 assert.equal(api.validManifest(m),false,'unregistered remote images remain denied');
 for(const changed of [
  {tile_template:m.tile_template+'?redirect=evil'}, {tile_template:'https://evil.invalid/{z}/{x}/{y}.png'},
  {bounds:[[0,0],[90,180]]},{min_zoom:0},{min_native_zoom:1},{max_native_zoom:23},
  {source_tiles:{primary:'https://evil.invalid/a',supplement:'https://evil.invalid/b'}},
  {source_kind:'official_gis'}, {coverage_windows:[[[0,0],[90,180]]]},
 ])assert.equal(api.validManifest({...m,...changed},rules),false,JSON.stringify(changed));
 assert.equal(api.validCatalog({layers:Array(129).fill(layers[0])},rules),false);
});

test('national manifests do not widen the official GIS or draft family limits',()=>{
 const official={id:'bad-gis',status:'reference_overlay',source_kind:'official_gis',render_mode:'xyz',
  tile_template:'/api/planning/gis-tiles/partition/{z}/{x}/{y}.png',tile_size:256,min_zoom:8,max_zoom:23,
  bounds:[[20,104],[22,106]],title:'Bad',notice:'Test'};
 assert.equal(api.validManifest(official,rules),false);
 assert.equal(api.validCatalog({layers:[{...layers[0],theme:'urban_general'}]},rules),false);
});
