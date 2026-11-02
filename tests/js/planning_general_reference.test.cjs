const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs');
const api=require('../../static/js/main/planning_overlay.js');
const area=require('../../static/js/main/planning_area.js');
const layers=JSON.parse(fs.readFileSync('config/planning_general_reference.json','utf8')).layers;
const rules=Object.fromEntries(layers.map(l=>[l.id,{...l.manifest,...l}]));

test('general planning needs exact rules and cannot replace GIS or another planning category',()=>{
 assert.equal(api.validCatalog({layers},null,rules),true);
 for(const layer of layers){
  const changed=structuredClone(layer);changed.manifest.tile_template='https://evil.invalid/{z}/{x}/{y}.png';
  assert.equal(api.validCatalog({layers:[changed]},null,rules),false);
  for(const theme of ['partition','construction','land_use_2030'])assert.equal(api.validCatalog({layers:[{...layer,theme}]},null,rules),false);
  assert.equal(api.validCatalog({layers:[{...layer,source:'gis'}]},null,rules),false);
  assert.equal(api.validCatalog({layers:[layer]}),false);
  assert.equal(area.coversProvince(layer,{id:layer.coverage_provinces[0]}),true);
  assert.equal(area.coversProvince(layer,{id:'binh-duong'}),false);
 }
});
