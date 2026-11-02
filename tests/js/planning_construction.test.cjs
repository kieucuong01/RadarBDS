const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs');
const overlay=require('../../static/js/main/planning_overlay.js');
const area=require('../../static/js/main/planning_area.js');
const layers=JSON.parse(fs.readFileSync('config/planning_construction.json','utf8')).layers;
const rules=Object.fromEntries(layers.map(l=>[l.id,{...l.manifest,...l}]));

test('construction uses exact registered sources and cannot be relabeled as partition or GIS',()=>{
 assert.equal(overlay.validCatalog({layers},null,rules),true);
 for(const layer of layers){
  const changed=structuredClone(layer);changed.manifest.tile_template='https://evil.invalid/{z}/{x}/{y}.png';
  assert.equal(overlay.validCatalog({layers:[changed]},null,rules),false);
  assert.equal(overlay.validCatalog({layers:[{...layer,theme:'partition'}]},null,rules),false);
  assert.equal(overlay.validCatalog({layers:[{...layer,source:'gis'}]},null,rules),false);
  assert.equal(overlay.validCatalog({layers:[layer]}),false);
  assert.equal(area.coversProvince(layer,{id:layer.coverage_provinces[0]}),true);
  assert.equal(area.coversProvince(layer,{id:'unsupported'}),false);
 }
});
